// ledger.test.ts — 缓存账本的反向验证（verify_ledger.py 的 vitest 对应移植）
//
// **第 0 条纪律是好数据放行**：登记 → status 必须报 fresh；这条不过，后面的
// 「能抓坏」全部没有意义。其余各条各防一种真实退化（见每条断言的注释）。
//
// 另含**金样本批次 2 核心判据**：_digest 是纯字节数学，跨语言（Python↔TS）
// 逐字节可对齐——夹具字节内嵌在 migration/golden/ledger.json（base64），
// 这里重建同字节文件复算，断言与 Python 引擎算出的指纹**逐字一致**。
//
// 全部断言自带夹具（临时 root / 临时数据文件），不碰真实源码与真实产物——
// 门禁必须能在任何没渲过东西的机器上跑（纪律 12：没验不许长得像验过了）。
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it } from 'vitest'

import * as ledger from '../src/ledger.js'

// 金样本：migration/golden/ledger.json（Python 引擎在删场前落盘的不可变参照）
const GOLDEN = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../../migration/golden/ledger.json', import.meta.url)), 'utf8'),
) as {
  data: {
    fixtures: Array<{ name: string; bytes_b64: string }>
    sha256: Record<string, string>
    digest: Record<string, string | null>
  }
}

let tmpRoots: string[] = []

function freshRoot(): string {
  const d = mkdtempSync(join(tmpdir(), 'feuille-ledger-'))
  tmpRoots.push(d)
  return d
}

afterEach(() => {
  for (const d of tmpRoots) rmSync(d, { recursive: true, force: true })
  tmpRoots = []
  // 工具链覆盖与 memoize 都要还原：账本指纹跨测试必须回到真实工具链
  ledger.overrideToolchainForTests(null)
  ledger.resetToolchainCacheForTests()
})

describe('缓存账本（注册制 + root 参数化）', () => {
  it('好数据放行：登记后 status=fresh', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline', 'unit-a', ['build/out.bin'])
    const [ok, why] = ledger.statusOf(root, 'testline', 'unit-a', ['build/out.bin'])
    expect(ok).toBe(true)
    expect(why).toContain('指纹一致')
  })

  it('数据文件改一个字节 → 判过期', () => {
    const root = freshRoot()
    const dataFile = join(root, 'data.json')
    writeFileSync(dataFile, '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline2', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline2', 'unit-a', ['build/out.bin'])
    writeFileSync(dataFile, '{"a": 2}', 'utf8')
    const [ok, why] = ledger.statusOf(root, 'testline2', 'unit-a', ['build/out.bin'])
    expect(ok).toBe(false)
    expect(why).toContain('指纹')
    // 改回去 → 恢复 fresh（不是「一旦红就永久红」）
    writeFileSync(dataFile, '{"a": 1}', 'utf8')
    expect(ledger.statusOf(root, 'testline2', 'unit-a', ['build/out.bin'])[0]).toBe(true)
  })

  it('敏感性：改一个字节 → 指纹必变；读不到 → digest 为 null（保守，不编指纹）', () => {
    const root = freshRoot()
    const a = join(root, 'mod_a.py')
    const b = join(root, 'data_b.json')
    writeFileSync(a, 'x = 1\n', 'utf8')
    writeFileSync(b, '{}', 'utf8')
    const base = ledger.digest([
      ['mod:a', a],
      ['data:b', b],
    ])
    writeFileSync(a, 'x = 2\n', 'utf8')
    expect(
      ledger.digest([
        ['mod:a', a],
        ['data:b', b],
      ]),
    ).not.toBe(base)
    expect(ledger.digest([['mod:a', join(root, 'nope')]])).toBeNull()
  })

  it('产物被删 / 账本没这条 / 指纹不符 → 各自判过期且原因可辨', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline3', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline3', 'unit-a', ['build/out.bin'])

    const [, whyMissing] = ledger.statusOf(root, 'testline3', 'unit-a', ['build/out.bin.gone'])
    expect(whyMissing).toContain('产物缺失')

    const [okNone, whyNone] = ledger.statusOf(root, 'testline3', 'never-recorded', ['build/out.bin'])
    expect(okNone).toBe(false)
    expect(whyNone).toContain('没有这条')

    writeFileSync(join(root, 'data.json'), '{"a": 9}', 'utf8')
    const [, whyChanged] = ledger.statusOf(root, 'testline3', 'unit-a', ['build/out.bin'])
    expect(whyChanged).toContain('指纹变了')
  })

  it('账本损坏 → 降级为空账本而不是抛异常', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline4', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline4', 'unit-a', ['build/out.bin'])
    writeFileSync(ledger.ledgerPath(root), '{oops', 'utf8')
    const [ok, why] = ledger.statusOf(root, 'testline4', 'unit-a', ['build/out.bin'])
    expect(ok).toBe(false)
    expect(why).toContain('没有这条')
    // 降级后 record 可重建
    ledger.record(root, 'testline4', 'unit-a', ['build/out.bin'])
    expect(ledger.statusOf(root, 'testline4', 'unit-a', ['build/out.bin'])[0]).toBe(true)
  })

  it('账本版本不匹配 → 整本作废（旧结构条目不会被误读）', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline5', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline5', 'unit-a', ['build/out.bin'])
    const doc = ledger.load(root)
    doc.version = ledger.VERSION - 1
    doc.entries['testline5:unit-a'] = {
      kind: 'testline5', unit: 'unit-a', fingerprint: 'x', extra: [],
      artifacts: [], toolchain: { node: null, sharp: null, browser: null, ffmpeg: null },
      builtAt: '',
    }
    ledger.save(root, doc)
    const [ok, why] = ledger.statusOf(root, 'testline5', 'unit-a', ['build/out.bin'])
    expect(ok).toBe(false)
    expect(why).toContain('没有这条')
  })

  it('未注册的产物线 → 指纹算不出（null），不会拿别线的指纹凑数', () => {
    const root = freshRoot()
    expect(ledger.fingerprint(root, 'never-registered', 'u')).toBeNull()
  })

  it('不同 unit 键不碰撞（键不带身份段会互相覆盖）', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline6', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline6', 'unit-a', ['build/out.bin'])
    ledger.record(root, 'testline6', 'unit-b', ['build/out.bin'])
    const entries = ledger.load(root).entries
    expect('testline6:unit-a' in entries).toBe(true)
    expect('testline6:unit-b' in entries).toBe(true)
  })

  it('extra 账本自描述：按条目里记录的那份复算', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline7', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline7', 'unit-extra', ['build/out.bin'], ['16x9'])
    expect(ledger.statusOf(root, 'testline7', 'unit-extra', ['build/out.bin'])[0]).toBe(true)
    // 调用方换 extra 值 → 指纹必变
    expect(ledger.statusOf(root, 'testline7', 'unit-extra', ['build/out.bin'], ['9x16'])[0]).toBe(false)
  })

  it('@glob 数据线：目录内文件字节变 → 指纹必变', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')
    mkdirSync(join(root, 'langs', 'zh-CN'), { recursive: true })
    writeFileSync(join(root, 'langs', 'zh-CN', 'manifest.json'), '{}', 'utf8')

    ledger.registerLine('testglobe', ['index.ts'], ['data.json', '@langs/*/manifest.json'])
    expect(ledger.fingerprint(root, 'testglobe', 'g1')).not.toBeNull()
    const fp1 = ledger.fingerprint(root, 'testglobe', 'g1')
    mkdirSync(join(root, 'langs', 'ja-JP'), { recursive: true })
    writeFileSync(join(root, 'langs', 'ja-JP', 'manifest.json'), '{}', 'utf8')
    const fp2 = ledger.fingerprint(root, 'testglobe', 'g1')
    writeFileSync(join(root, 'langs', 'ja-JP', 'manifest.json'), '{"x":1}', 'utf8')
    const fp3 = ledger.fingerprint(root, 'testglobe', 'g1')
    expect(fp1).not.toBeNull()
    expect(fp2).not.toBeNull()
    expect(fp1).not.toBe(fp2) // 目录内容变（新增文件）→ 指纹变
    expect(fp2).not.toBe(fp3) // 文件字节变 → 指纹变
  })

  it('工具链读不到 → 指纹 null（保守判过期，绝不假设没影响）', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline8', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline8', 'unit-a', ['build/out.bin'])
    // Python 侧用 monkeypatch toolchain 模拟「读不到」；ESM 导出不可改写 → 显式覆盖缝
    ledger.overrideToolchainForTests({ node: null, sharp: null, browser: null, ffmpeg: null })
    expect(ledger.fingerprint(root, 'testline8', 'unit-a')).toBeNull()
  })

  it('report() 不炸、条目可读', () => {
    const root = freshRoot()
    writeFileSync(join(root, 'data.json'), '{"a": 1}', 'utf8')
    mkdirSync(join(root, 'build'), { recursive: true })
    writeFileSync(join(root, 'build', 'out.bin'), 'x', 'utf8')

    ledger.registerLine('testline9', ['index.ts'], ['data.json'])
    ledger.record(root, 'testline9', 'unit-a', ['build/out.bin'])
    const [fresh, stale] = ledger.report(root)
    expect(fresh.length + stale.length).toBeGreaterThan(0)
  })

  it('mainStatus 退出码口径：空账本 0 / 全新鲜 0 / 有过期 1', () => {
    const leafRoot = freshRoot()
    expect(ledger.mainStatus(['--root', leafRoot])).toBe(0) // 还没登记 ≠ 失败

    const leafData = join(leafRoot, 'leaf.json')
    writeFileSync(leafData, '{}', 'utf8')
    mkdirSync(join(leafRoot, 'build'), { recursive: true })
    writeFileSync(join(leafRoot, 'build', 'out.bin'), 'x', 'utf8')
    ledger.registerLine('leafline', ['index.ts'], ['leaf.json'])
    ledger.record(leafRoot, 'leafline', 'u1', ['build/out.bin'])
    expect(ledger.mainStatus(['--root', leafRoot])).toBe(0)

    writeFileSync(leafData, '{"k": 1}', 'utf8') // 输入指纹变了
    expect(ledger.mainStatus(['--root', leafRoot])).toBe(1) // 「有活要干」的信号
  })

  it('toolchain() memoize：进程内缓存，浏览器/ffmpeg 版本只探一次（性能修复内建）', () => {
    ledger.resetToolchainCacheForTests()
    const a = ledger.toolchain()
    const b = ledger.toolchain()
    expect(a).toBe(b) // 同一对象引用 = 命中缓存，没再 spawn ffmpeg -version
    expect(a.node).toBe(process.version)
    expect(a.sharp).toMatch(/\/vips-/)
  })
})

describe('金样本批次 2：_digest 跨语言逐字节 parity（Python 删场前的不可变参照）', () => {
  // 夹具在每个测试内重建：afterEach 清空的是共享 tmpRoots，收集期建的目录活不过第一个测试
  function buildGoldenFixtures(): { root: string; parts: Array<[string, string]>; binPart: Array<[string, string]> } {
    const root = freshRoot()
    for (const f of GOLDEN.data.fixtures) {
      writeFileSync(join(root, f.name), Buffer.from(f.bytes_b64, 'base64'))
    }
    const parts: Array<[string, string]> = [
      ['mod:a', join(root, 'mod_a.py')],
      ['data:b', join(root, 'data_b.json')],
    ]
    return { root, parts, binPart: [...parts, ['data:bin', join(root, 'bin.bin')]] }
  }

  it('夹具文件 sha256 与 Python 引擎一致（含 UTF-8 中文与二进制字节）', () => {
    const { root } = buildGoldenFixtures()
    for (const [name, sha] of Object.entries(GOLDEN.data.sha256)) {
      expect(ledger.sha256File(join(root, name))).toBe(sha)
    }
  })

  it('digest 各形态与 Python 逐字一致', () => {
    const { root, parts, binPart } = buildGoldenFixtures()
    const g = GOLDEN.data.digest
    expect(ledger.digest(parts)).toBe(g.two_parts)
    expect(ledger.digest([...parts].reverse())).toBe(g.order_swapped)
    expect(
      ledger.digest([
        ['zzz:a', join(root, 'mod_a.py')],
        ['data:b', join(root, 'data_b.json')],
      ]),
    ).toBe(g.label_changed)
    expect(ledger.digest(binPart)).toBe(g.with_binary)
    expect(ledger.digest([])).toBe(g.empty)
    expect(ledger.digest([['mod:a', join(root, 'nope.py')]])).toBeNull()
    expect(g.missing).toBeNull() // Python 侧同为 null（对照自证）

    writeFileSync(join(root, 'mod_a.py'), 'x = 2\n', 'utf8')
    expect(ledger.digest(parts)).toBe(g.one_byte_changed)
    writeFileSync(join(root, 'mod_a.py'), 'x = 1\n', 'utf8')
    expect(ledger.digest(parts)).toBe(g.two_parts) // 可复现
  })
})
