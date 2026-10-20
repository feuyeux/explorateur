// packaging.test.ts — 打包的反向验证（verify_audit.py 第 3 节「打包」的 vitest 对应移植；
// audit 部分属 P4，届时随模块迁入）
//
// **它防的事故**：macOS 自带 Info-ZIP 对非 ASCII 文件名不置 UTF-8 flag（bit
// 0x800），解包到别的机器上中文/阿拉伯语文件名全变乱码。所以打包一律走库、
// 不走命令行 zip；本套断言「库真的置位了」——这是判据不是摆设。
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import * as packaging from '../src/packaging.js'

let tmpRoots: string[] = []

function freshDir(): string {
  const d = mkdtempSync(join(tmpdir(), 'feuille-pack-'))
  tmpRoots.push(d)
  return d
}

afterEach(() => {
  for (const d of tmpRoots) rmSync(d, { recursive: true, force: true })
  tmpRoots = []
})

describe('交付打包（zipTree / UTF-8 flag / 条目完整性）', () => {
  it('非 ASCII 文件名置 UTF-8 flag 0x800（Info-ZIP 不置位的教训）', async () => {
    const d = freshDir()
    const src = join(d, 'pack')
    mkdirSync(join(src, '子目录'), { recursive: true })
    writeFileSync(join(src, '子目录', '中文_抖音封面.png'), 'x')
    writeFileSync(join(src, '普通.txt'), 'x')

    const zp = await packaging.zipTree(src, join(d, 'out.zip'))
    expect(await packaging.hasUtf8Flag(zp, '子目录/中文_抖音封面.png')).toBe(true)
    // ASCII 条目 yazl 也置位（本行的断言就是那个探针的结论；Python 时代的
    // 探针记录已随金样本退役，行为改由这一行机检）
    expect(await packaging.hasUtf8Flag(zp, '普通.txt')).toBe(true)

    const entries = await packaging.listEntries(zp)
    expect(Object.keys(entries).sort()).toEqual(['子目录/中文_抖音封面.png', '普通.txt'])
    // 条目元数据：未压缩大小与源文件一致
    expect(entries['普通.txt']!.uncompressedSize).toBe(1)
  })

  it('内容逐字节不被打包层碰（readEntry 往返一致）', async () => {
    const d = freshDir()
    const src = join(d, 'pack')
    mkdirSync(src, { recursive: true })
    const payload = Buffer.from([0, 1, 2, 0x80, 0xfe, 0xff, 10]) // 二进制：不留任何转码余地
    writeFileSync(join(src, 'bin.dat'), payload)
    writeFileSync(join(src, '文本.txt'), '落叶知秋\n')

    const zp = await packaging.zipTree(src, join(d, 'out.zip'))
    expect(Buffer.compare(await packaging.readEntry(zp, 'bin.dat'), payload)).toBe(0)
    expect((await packaging.readEntry(zp, '文本.txt')).toString('utf8')).toBe('落叶知秋\n')
  })

  it('include 过滤器生效（跳过 build 产物/临时件）；缺条目读出时报错不静默', async () => {
    const d = freshDir()
    const src = join(d, 'pack')
    mkdirSync(src, { recursive: true })
    writeFileSync(join(src, 'keep.txt'), 'a')
    writeFileSync(join(src, 'build-junk.txt'), 'b')

    const zp = await packaging.zipTree(src, join(d, 'out.zip'), (rel) => !rel.startsWith('build-'))
    const entries = await packaging.listEntries(zp)
    expect(Object.keys(entries)).toEqual(['keep.txt'])
    // 没有 utf8flag 帮手的条目 → 显式报错（不静默返回 false）
    await expect(packaging.hasUtf8Flag(zp, 'build-junk.txt')).rejects.toThrow(/没有条目/)
    await expect(packaging.readEntry(zp, 'nope.txt')).rejects.toThrow(/没有条目/)
  })

  it('目录序 = 路径排序（与 Python sorted(rglob) 同序，跨语言结构 parity）', async () => {
    const d = freshDir()
    const src = join(d, 'pack')
    for (const rel of ['b.txt', 'a.txt', 'z/dir2/x.txt', 'z/dir1/y.txt', 'z/m.txt']) {
      const p = join(src, ...rel.split('/'))
      mkdirSync(dirname(p), { recursive: true })
      writeFileSync(p, 'x')
    }
    const zp = await packaging.zipTree(src, join(d, 'out.zip'))
    const names = Object.keys(await packaging.listEntries(zp))
    expect(names).toEqual([...names].sort())
    expect(names).toEqual(['a.txt', 'b.txt', 'z/dir1/y.txt', 'z/dir2/x.txt', 'z/m.txt'])
  })
})
