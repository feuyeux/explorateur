// framehash.test.ts — 逐帧像素基线的反向验证（verify_framehash.py 的 vitest 对应移植）
//
// 第 0 条好数据放行：两支确定性测试视频（lavfi 造）连算两次哈希一致；
// 基线保存→回读→比对零漂移。反向各防一种退化：
// - **-map 0:v 是承重的**（源级断言：缺它数字不同且不报错——Python 侧用
//   inspect.getsource 抓，TS 侧读源文件抓同一件事）
// - 内容变一个像素级细节 → 整支哈希必变（能抓真漂移）
// - 帧数不同 → firstDrift 必报（坑⑯「丢帧尾巴」症状）
// - 子集核查：基线里不在范围的归 skipped 不归 gone（门禁不喊狼嚎）
// - 差异热力图没有参考帧就返回 false（不做「假装有参考」的合成图）
// - 桶标识可读、含 sharp、**不含 ffmpeg**（合成器入桶只会让基线无谓失效）
// - memoize 键含 (size, mtime)：文件字节变了不会拿到旧哈希（性能修复内建的
//   反向面——快不能以错为代价）
// 另含金样本批次 2：classify / firstDrift / 基线文件格式与 Python 逐字节对齐。
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it } from 'vitest'

import * as fh from '../src/framehash.js'
import * as platform from '../src/platform.js'

const GOLDEN = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../../migration/golden/framehash.json', import.meta.url)), 'utf8'),
) as {
  data: {
    classify: {
      base: Record<string, string>
      cur: Record<string, string>
      full: fh.ClassifyResult
      subset: fh.ClassifyResult
      empty_base: fh.ClassifyResult
    }
    first_drift: Array<{ ref: string[]; cur: string[]; out: [number | null, number | null] }>
    baseline_text: string
    baseline_roundtrip: Record<string, string>
  }
}

const FFMPEG = platform.ffmpeg()

let tmpRoots: string[] = []

function freshDir(): string {
  const d = mkdtempSync(join(tmpdir(), 'feuille-framehash-'))
  tmpRoots.push(d)
  return d
}

afterEach(() => {
  for (const d of tmpRoots) rmSync(d, { recursive: true, force: true })
  tmpRoots = []
  fh.resetHashCacheForTests()
})

function makeVideo(path: string, color: string, seconds = 0.5): string {
  const ffm = FFMPEG!
  execFileSync(
    ffm,
    ['-y', '-f', 'lavfi', '-i', `color=c=${color}:s=320x240:d=${seconds}:r=30`,
     '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', path],
    { stdio: 'pipe' },
  )
  return path
}

describe.skipIf(FFMPEG === null)('逐帧像素基线（framehash / 分桶 / 漂移定位）', () => {
  it('好数据放行：确定性 + 基线往返零漂移', () => {
    const d = freshDir()
    const a = makeVideo(join(d, 'a.mp4'), '0x808080')
    const b = makeVideo(join(d, 'b.mp4'), '0x808080')

    const h1 = fh.framehash(a)
    expect(h1).toBe(fh.framehash(a)) // 同支连算两次一致
    expect(h1).toMatch(/^MD5=/)
    expect(fh.framehash(a)).toBe(fh.framehash(b)) // 同内容两支一致（判的是像素不是容器字节）

    const baseOnlyA = fh.saveBaseline({ 'a.mp4': h1 }, join(d, 'base-only.txt'))
    expect(fh.readBaseline(baseOnlyA)).toEqual({ 'a.mp4': h1 })

    const [r, rc] = fh.compare([a, b], baseOnlyA, { subset: false })
    expect(rc).toBe(0)
    expect(r.same).toEqual(['a.mp4'])
    expect(r.new).toEqual(['b.mp4'])
    expect(r.gone).toEqual([])

    const baseWithOld = fh.saveBaseline(
      { 'a.mp4': h1, 'old.mp4': 'MD5=dead' }, fh.baselinePath(d),
    )
    const [r2, rc2] = fh.compare([a, b], baseWithOld, { subset: false })
    expect(rc2).toBe(1)
    expect(r2.gone).toEqual(['old.mp4'])
  })

  it('-map 0:v 承重（源级断言：framehash/perFrame 都带它，少了数字不同且不报错）', () => {
    const src = readFileSync(
      fileURLToPath(new URL('../src/framehash.ts', import.meta.url)), 'utf8',
    )
    const bodyOf = (fn: string): string => {
      const start = src.indexOf(`export function ${fn}(`)
      expect(start).toBeGreaterThanOrEqual(0)
      const next = src.indexOf('\nexport function ', start + 1)
      return src.slice(start, next < 0 ? src.length : next)
    }
    expect(bodyOf('framehash')).toContain(`'-map', '0:v'`)
    expect(bodyOf('perFrame')).toContain(`'-map', '0:v'`)
  })

  it('内容变 → 整支哈希必变（能抓真漂移）', () => {
    const d = freshDir()
    const a = makeVideo(join(d, 'a.mp4'), '0x808080')
    const c = makeVideo(join(d, 'c.mp4'), '0x909090')
    expect(fh.framehash(a)).not.toBe(fh.framehash(c))
  })

  it('memoize 不以错换快：文件字节变（size+mtime 变）→ 不会拿到旧哈希', () => {
    const d = freshDir()
    const p = join(d, 'v.mp4')
    makeVideo(p, '0x707070')
    const h1 = fh.framehash(p)
    expect(fh.framehash(p)).toBe(h1) // 命中缓存
    makeVideo(p, '0xA0A0A0') // 覆写成不同内容
    expect(fh.framehash(p)).not.toBe(h1)
  })

  it('帧数不同 → firstDrift 必报；完全一致 → 不报', () => {
    const d = freshDir()
    const a = makeVideo(join(d, 'a.mp4'), '0x808080')
    const short = makeVideo(join(d, 'short.mp4'), '0x808080', 0.2)
    const fullFrames = fh.perFrame(a)
    const shortFrames = fh.perFrame(short)
    expect(fullFrames.length).not.toBe(shortFrames.length)
    const [first] = fh.firstDrift(shortFrames, fullFrames)
    expect(first).not.toBeNull() // 只比公共长度会把丢帧当一致
    const [first2] = fh.firstDrift(fullFrames, fullFrames)
    expect(first2).toBeNull()
  })

  it('子集核查：范围外归 skipped 不归 gone（退出码 0，门禁不喊狼嚎）', () => {
    const d = freshDir()
    const a = makeVideo(join(d, 'a.mp4'), '0x808080')
    const b = makeVideo(join(d, 'b.mp4'), '0x808080')
    const h1 = fh.framehash(a)
    const baseWithOld = fh.saveBaseline(
      { 'a.mp4': h1, 'old.mp4': 'MD5=dead' }, fh.baselinePath(d),
    )
    const c = makeVideo(join(d, 'c.mp4'), '0x909090')
    const [r, rc] = fh.compare([c], baseWithOld, { subset: true })
    expect(rc).toBe(0)
    expect(r.skipped).toEqual(['a.mp4', 'old.mp4'])
    expect(r.gone).toEqual([])
    expect(r.new).toEqual(['c.mp4'])
  })

  it('证据帧 + 热力图契约', async () => {
    const d = freshDir()
    const a = makeVideo(join(d, 'a.mp4'), '0x808080')
    const c = makeVideo(join(d, 'c.mp4'), '0x909090')
    expect(fh.extractFrame(a, 0, join(d, 'f0.png'))).toBe(true)
    // 无参考帧 → false（不做「假装有参考」的合成图）
    expect(await fh.diffPng(join(d, 'nope1.png'), join(d, 'nope2.png'), join(d, 'heat.png'))).toBe(false)
    fh.extractFrame(a, 0, join(d, 'ref0.png'))
    fh.extractFrame(c, 0, join(d, 'cur0.png'))
    expect(await fh.diffPng(join(d, 'ref0.png'), join(d, 'cur0.png'), join(d, 'heat.png'))).toBe(true)
    expect(existsSync(join(d, 'heat.png'))).toBe(true)
  })

  it('桶标识：可读、含 sharp、不含 ffmpeg；基线路径按桶命名', () => {
    const bkt = fh.bucket()
    expect(bkt).toContain('sharp')
    expect(bkt).toContain('-')
    expect(bkt).not.toContain('ffmpeg')
    const d = freshDir()
    expect(basename(fh.baselinePath(d))).toBe(`framehash-${bkt}.txt`)
  })

  it('CLI 叶子端到端：真造产物、真采、真查、真改坏（薄编排也有自己的死法）', () => {
    const proj = freshDir()
    mkdirSync(join(proj, 'build', 'sub'), { recursive: true })
    const x = makeVideo(join(proj, 'build', 'x.mp4'), '0x707070')
    const y = makeVideo(join(proj, 'build', 'sub', 'y.mp4'), '0x707070')

    expect(fh.mainSave(['--root', proj])).toBe(0)
    expect(fh.readBaseline(fh.baselinePath(proj))).toEqual({
      'x.mp4': fh.framehash(x),
      'y.mp4': fh.framehash(y),
    })

    expect(fh.mainCheck(['--root', proj])).toBe(0)

    makeVideo(join(proj, 'build', 'sub', 'y.mp4'), '0xA0A0A0') // 改坏一支
    expect(fh.mainCheck(['--root', proj])).toBe(1)

    rmSync(join(proj, 'build', 'sub', 'y.mp4')) // 产物没了
    expect(fh.mainCheck(['--root', proj])).toBe(1)

    // 筛空显式报错（坑㟃：不静默产空基线/不静默成功）
    const noBuild = freshDir()
    expect(() => fh.discoverVideos(noBuild)).toThrow(/没有 build/)
    const bareBuild = freshDir()
    mkdirSync(join(bareBuild, 'build'), { recursive: true })
    expect(() => fh.discoverVideos(bareBuild)).toThrow(/没有 mp4/)
  })
})

describe('金样本批次 2：纯函数跨语言逐字节 parity', () => {
  it('classify：full / subset / empty-base 三形态与 Python 一致', () => {
    const { base, cur, full, subset, empty_base: emptyBase } = GOLDEN.data.classify
    expect(fh.classify(base, cur, false)).toEqual(full)
    expect(fh.classify(base, cur, true)).toEqual(subset)
    expect(fh.classify({}, cur, false)).toEqual(emptyBase)
  })

  it('firstDrift：一致 / 中段漂移 / 帧数缺失 / 尾帧漂移 四形态与 Python 一致', () => {
    for (const { ref, cur, out } of GOLDEN.data.first_drift) {
      expect(fh.firstDrift(ref, cur)).toEqual(out)
    }
  })

  it('基线文件格式逐字节一致（含非 ASCII 文件名）+ 回读往返一致', () => {
    const d = freshDir()
    const p = fh.saveBaseline(
      { 'b.mp4': 'MD5=bbb', 'a.mp4': 'MD5=aaa', '中文视频.mp4': 'MD5=ccc' },
      join(d, 'base.txt'),
    )
    expect(readFileSync(p, 'utf8')).toBe(GOLDEN.data.baseline_text)
    expect(fh.readBaseline(p)).toEqual(GOLDEN.data.baseline_roundtrip)
  })
})
