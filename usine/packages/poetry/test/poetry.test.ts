// poetry.test.ts — @feuille/poetry 反向验证（verify_skill_scripts.py 的
// color_contrast 段随本包归流移植 + 新增离线端到端）。
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import sharp from 'sharp'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FeuilleError, platform } from '@feuille/core'

import { audio_profile, color_contrast } from '../src/index.js'

const FFMPEG = platform.ffmpeg()

function makeTmp(): string {
  return mkdtempSync(join(tmpdir(), 'poetry-test-'))
}

async function solidPng(path: string, color: string, w = 100, h = 100): Promise<void> {
  await sharp({ create: { width: w, height: h, channels: 3, background: color } })
    .png().toFile(path)
}

/** SVG → png：透明底 + 一块实心矩形（字幕卡片的最小形态）。 */
async function cardPng(path: string, color: string, x: number, y: number,
  w: number, h: number, W = 100, H = 100): Promise<void> {
  const svg = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">`
    + `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${color}"/></svg>`)
  await sharp(svg).png().toFile(path)
}

function captureLog(): { log: string[]; spy: ReturnType<typeof vi.spyOn> } {
  const log: string[] = []
  const spy = vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(''))
  })
  return { log, spy }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('color_contrast：纯数学口径（verify_skill_scripts.py 移植 + 补充）', () => {
  it('gap_verdict：差 ≥ 阈值 → PASS、差 < 阈值 → FAIL（阈值自标定，不内置默认）', () => {
    expect(color_contrast.gapVerdict(0.35, 0.30, '春').startsWith('PASS')).toBe(true)
    expect(color_contrast.gapVerdict(0.25, 0.30, '冬').startsWith('FAIL')).toBe(true)
  })

  it('percentile：numpy 线性插值口径（[1..5] p50=3；p90 在 4.6 处内插）', () => {
    const a = [1, 2, 3, 4, 5]
    expect(color_contrast.percentile(a, 50)).toBe(3)
    expect(color_contrast.percentile(a, 90)).toBeCloseTo(4.6, 10)
    expect(color_contrast.percentile(a, 0)).toBe(1)
    expect(color_contrast.percentile(a, 100)).toBe(5)
  })

  it('hex/lum/wcag：纯白对纯黑 = 21:1；红字亮度 = 0.2126（sRGB 线性加权）', () => {
    expect(color_contrast.hex2rgb('#2E7CB8')).toEqual([0x2e, 0x7c, 0xb8])
    expect(color_contrast.lumHex('#FFFFFF')).toBe(1)
    expect(color_contrast.lumHex('#FF0000')).toBeCloseTo(0.2126, 6)
    expect(color_contrast.wcagRatio('#FFFFFF', 0)).toBeCloseTo(21, 6)
  })

  it('rgbToHls：红 → h=0/l=0.5/s=1；灰 → h=0/s=0（colorsys 口径）', () => {
    expect(color_contrast.rgbToHls(1, 0, 0)).toEqual([0, 0.5, 1])
    expect(color_contrast.rgbToHls(0.5, 0.5, 0.5)).toEqual([0, 0.5, 0])
    const [h, , s] = color_contrast.rgbToHls(0x2e / 255, 0x7c / 255, 0xb8 / 255)
    expect(h).toBeCloseTo(207 / 360, 2)
    expect(s).toBeGreaterThan(0.5)
  })

  it('suggest：同色相四档、由亮到暗；hls_to_rgb 逆变换闭环', () => {
    const got = color_contrast.suggest('#2E7CB8')
    expect(got).toHaveLength(4)
    expect(got.every((c) => /^#[0-9A-F]{6}$/.test(c))).toBe(true)
    const lums = got.map((c) => color_contrast.lumHex(c))
    expect(lums[0]!).toBeGreaterThan(lums[1]!)
    expect(lums[1]!).toBeGreaterThan(lums[2]!)
    expect(lums[2]!).toBeGreaterThan(lums[3]!)
  })

  it('glyph_mask：命中目标色相+饱和+明度的像素，暗背景不命中', () => {
    // 4×2：前 4 像素纯红，后 4 像素暗灰
    const reg = new Uint8Array([
      255, 0, 0, 255, 0, 0, 255, 0, 0, 255, 0, 0,
      40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40,
    ])
    const g = color_contrast.glyphMask(reg, 4, 2, '#FF0000')
    expect([...g]).toEqual([1, 1, 1, 1, 0, 0, 0, 0])
  })

  it('dilate：4 邻域膨胀逐次外扩', () => {
    const m = new Uint8Array(9)
    m[4] = 1 // 3×3 中心
    const d1 = color_contrast.dilate(m, 3, 3, 1)
    expect([...d1].filter(Boolean).length).toBe(5)
    const d2 = color_contrast.dilate(m, 3, 3, 2)
    expect([...d2].filter(Boolean).length).toBe(9)
  })

  it('seasonColorsFromArchive：归档 季节与译文.py 的 SEASON_COLOR 字面量可解析（事实源没变）', () => {
    const got = color_contrast.seasonColorsFromArchive()
    expect(got).not.toBeNull()
    expect(Object.keys(got!)).toEqual(['春', '夏', '秋', '冬'])
    expect(got!['春']).toEqual(['#F0568C', '#C9889E'])
    expect(got!['冬']).toEqual(['#2E7CB8', '#3E5F7A'])
  })
})

describe('color_contrast measure：真 sharp 成像（离线）', () => {
  it('合成卡片后量出字芯亮度与环带背景；无卡片 → 只量背景', async () => {
    const d = makeTmp()
    try {
      const frame = join(d, 'frame.png')
      const card = join(d, 'card.春.png')
      await solidPng(frame, '#282828')
      await cardPng(card, '#FF0000', 30, 60, 40, 30)
      const m = await color_contrast.measure(frame, card, '#FF0000', 'bottom')
      expect(m.gl).not.toBeNull()
      expect(m.gl!).toBeCloseTo(color_contrast.lumHex('#FF0000'), 3)
      expect(m.npx).toBeGreaterThanOrEqual(60)
      expect(m.p50).toBeGreaterThan(0)
      expect(m.p50).toBeLessThan(m.gl!)
      const b = await color_contrast.measure(frame, null, '#FF0000', 'bottom')
      expect(b.gl).toBeNull()
      expect(b.p50).toBeCloseTo(color_contrast.lumHex('#282828'), 6)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('色相对不上 → 字形零命中 → gl=null（查 --colors 的提示路径）', async () => {
    const d = makeTmp()
    try {
      const frame = join(d, 'frame.png')
      const card = join(d, 'card.春.png')
      await solidPng(frame, '#282828')
      await cardPng(card, '#FF0000', 30, 60, 40, 30)
      const m = await color_contrast.measure(frame, card, '#00FF00', 'bottom')
      expect(m.gl).toBeNull()
      expect(m.npx).toBe(0)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('color_contrast main：argparse 口径 + seasons 端到端（真 ffmpeg，离线）', () => {
  function makeSeasonsVideo(d: string): string {
    // 母版：4s 纯暗底 mp4
    const vid = join(d, '母版.mp4')
    const r = spawnSync(FFMPEG!, ['-y', '-v', 'error', '-f', 'lavfi',
      '-i', 'color=c=0x282828:s=100x100:d=4:r=10', '-pix_fmt', 'yuv420p', vid],
      { encoding: 'utf8' })
    expect(r.status).toBe(0)
    return vid
  }

  it('缺 image/seasons → 2；-h → 0；未知旗标 / 坏 choice / 坏 gate / 双位置参数 → 2', async () => {
    const { spy } = captureLog()
    const errSpy = vi.spyOn(process.stderr, 'write').mockImplementation(() => true)
    try {
      expect(await color_contrast.main([])).toBe(2)
      expect(await color_contrast.main(['-h'])).toBe(0)
      expect(await color_contrast.main(['--nope'])).toBe(2)
      expect(await color_contrast.main(['x.png', '--band', 'middle'])).toBe(2)
      expect(await color_contrast.main(['x.png', '--gap-ref', 'p99'])).toBe(2)
      expect(await color_contrast.main(['x.png', '--gate', 'abc'])).toBe(2)
      expect(await color_contrast.main(['a.png', 'b.png'])).toBe(2)
      expect(errSpy).toHaveBeenCalled()
      expect(spy).toHaveBeenCalled()
    } finally {
      spy.mockRestore()
      errSpy.mockRestore()
    }
  })

  it('seasons：母版 + 卡片 → 逐季行；--gate 阈值内 PASS → 0、阈值外 FAIL → 1', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      const vid = makeSeasonsVideo(d)
      await cardPng(join(d, 'card.春.png'), '#FF0000', 30, 60, 40, 30)
      await cardPng(join(d, 'card.冬.png'), '#FF0000', 30, 60, 40, 30)
      const args = ['--seasons', vid, '--cards', d,
        '--colors', '{"春":["#FF0000","#900000"],"冬":["#FF0000","#900000"]}',
        '--shots', '{"春":1.0,"冬":2.0}']
      expect(await color_contrast.main([...args, '--gate', '0.1'])).toBe(0)
      const gateLine = log.find((l) => l.includes('GATE PASS'))!
      expect(gateLine).toContain('阈值 0.1')
      expect(gateLine).toContain('gap-ref p90')
      expect(log.some((l) => l.startsWith('PASS 春：') && l.includes('≥ 阈值'))).toBe(true)
      expect(log.some((l) => l.startsWith('PASS 冬：'))).toBe(true)
      expect(log.some((l) => l.includes('字形') && l.includes('px'))).toBe(true)

      log.length = 0
      expect(await color_contrast.main([...args, '--gate', '0.5'])).toBe(1)
      expect(log.find((l) => l.includes('GATE FAIL'))).toBeDefined()
      expect(log.some((l) => l.startsWith('FAIL 春：'))).toBe(true)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('gate 下没量到的季不许静默混过（SKIP 不是 PASS——未合成 → FAIL 未量到）', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      const vid = makeSeasonsVideo(d)
      // 不给 --cards：整季走「未合成」行，gate 下必须 FAIL 未量到
      const args = ['--seasons', vid,
        '--colors', '{"春":["#FF0000","#900000"]}', '--shots', '{"春":1.0}',
        '--gate', '0.1']
      expect(await color_contrast.main(args)).toBe(1)
      expect(log.some((l) => l.endsWith('未合成'))).toBe(true)
      expect(log.some((l) => l.startsWith('FAIL 春：未量到'))).toBe(true)
      expect(log.find((l) => l.includes('GATE FAIL'))).toBeDefined()
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('母版不在盘 → 找不到 + 2；--colors 坏 JSON → FeuilleError', async () => {
    const { log, spy } = captureLog()
    try {
      expect(await color_contrast.main(['--seasons', '/nonexistent/x.mp4'])).toBe(2)
      expect(log[0]).toMatch(/找不到/)
      const d = makeTmp()
      const vid = makeSeasonsVideo(d)
      await expect(color_contrast.main(['--seasons', vid, '--colors', '{oops']))
        .rejects.toThrow(FeuilleError)
      rmSync(d, { recursive: true, force: true })
    } finally {
      spy.mockRestore()
    }
  })

  it('image 单帧模式：背景亮度行；--suggest 四档深浅', async () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      const frame = join(d, 'frame.png')
      await solidPng(frame, '#282828')
      expect(await color_contrast.main([frame])).toBe(0)
      expect(log[0]).toBe(`frame.png 区域=bottom  背景亮度 p50=${color_contrast.lumHex('#282828').toFixed(3)}  `
        + `p90=${color_contrast.lumHex('#282828').toFixed(3)}`)
      log.length = 0
      expect(await color_contrast.main([frame, '--suggest', '#2E7CB8'])).toBe(0)
      expect(log[0]).toMatch(/^该区域背景 p50=/)
      expect(log.filter((l) => /^  #/.test(l))).toHaveLength(4)
      expect(log[1]).toMatch(/亮度=0\.\d{3}  WCAG比值\(仅供参考\)=\d+\.\d{2}$/)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('audio_profile：真 ffmpeg 测量（离线）', () => {
  /** 2s 响（0.5 幅度）+ 2s 床（0.004 幅度）的 wav。 */
  function makeTwoLevelWav(d: string): string {
    const out = join(d, 'mix.wav')
    const r = spawnSync(FFMPEG!, ['-y', '-v', 'error',
      '-f', 'lavfi', '-i', 'sine=f=440:r=44100:d=2',
      '-f', 'lavfi', '-i', 'sine=f=440:r=44100:d=2',
      '-filter_complex', '[0]volume=0.5[a];[1]volume=0.004[b];[a][b]concat=n=2:v=0:a=1',
      '-ac', '1', out], { encoding: 'utf8' })
    expect(r.status).toBe(0)
    return out
  }

  it('curve：逐 0.1s 电平曲线，响段高、床段低', () => {
    const d = makeTmp()
    try {
      const wav = makeTwoLevelWav(d)
      const c = audio_profile.curve(wav)
      const ts = Object.keys(c).map(Number).sort((x, y) => x - y)
      expect(ts[0]).toBe(0)
      expect(ts[ts.length - 1]).toBe(4)
      // astats 逐点值与 volumedetect 不一致（脚本 docstring 自己声明只看趋势）：
      // Python 实测同素材 c[0.1]=-27.1、c[3.5]=-69.1，阈值按趋势留余量
      expect(c[0.1]!).toBeGreaterThan(-35)
      expect(c[3.5]!).toBeLessThan(-50)
      expect(c[0.1]! - c[3.5]!).toBeGreaterThan(20)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('meanVolume / lufs：响段远高于床段（LUFS 差 ≥ 8 dB 是判据线）', () => {
    const d = makeTmp()
    try {
      const wav = makeTwoLevelWav(d)
      const mv = audio_profile.meanVolume(wav, 0, 1.5)
      const mg = audio_profile.meanVolume(wav, 2.5, 1.0)
      expect(mv).not.toBeNull()
      expect(mg).not.toBeNull()
      expect(mv! - mg!).toBeGreaterThan(20)
      const lv = audio_profile.lufs(wav, 0, 1.5)
      const lg = audio_profile.lufs(wav, 2.5, 1.0)
      expect(lv).not.toBeNull()
      expect(lg).not.toBeNull()
      expect(lv! - lg!).toBeGreaterThan(8)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('in_windows：原样保留的辅助函数行为正确', () => {
    const wins: Array<[number, number]> = [[0.5, 1.5], [3, 4]]
    expect(audio_profile.inWindows(0.5, wins)).toBe(true)
    expect(audio_profile.inWindows(1.6, wins)).toBe(false)
    expect(audio_profile.inWindows(3.2, wins)).toBe(true)
  })

  it('main：窗口模式人声 vs 床 → 差值行 + ✓；--rms 附 RMS 旁证', () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      const wav = makeTwoLevelWav(d)
      const spec = JSON.stringify({ voice: [[0, 1.5]], gaps: [[2.5, 3.5]] })
      expect(audio_profile.main([wav, spec, '--rms'])).toBe(0)
      expect(log[0]).toBe('mix.wav  （窗口测量用 LUFS，感知口径）\n')
      expect(log[1]).toBe('【人声段】')
      expect(log[2]).toContain('0.00–')
      expect(log[2]).toContain('LUFS')
      expect(log[2]).toMatch(/（RMS {0,6}-?\d+\.\d dB）$/)
      expect(log[3]).toBe('【空档段（底床）】')
      const diff = log.find((l) => l.includes('人声均值'))!
      expect(diff).toMatch(/差 \+\d+\.\d dB  ✓ 人声盖过底床$/)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('main：全曲曲线模式（显式空窗口 JSON 避开 stdin）', () => {
    const d = makeTmp()
    const { log, spy } = captureLog()
    try {
      const wav = makeTwoLevelWav(d)
      expect(audio_profile.main([wav, '{}'])).toBe(0)
      expect(log[0]).toBe('mix.wav 逐 0.1s 电平\n')
      expect(log[1]).toMatch(/^ {3}0\.0s/)
      expect(log[1]).toMatch(/-?\d+\.\d$/)
      expect(log[log.length - 1]!).toMatch(/^ {3}4\.0s/)
    } finally {
      spy.mockRestore()
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('main：缺参 → __doc__ + 2；文件不在盘 → 找不到 + 2', () => {
    const { log, spy } = captureLog()
    try {
      expect(audio_profile.main([])).toBe(2)
      expect(log[0]).toMatch(/^音频拆轨对比：/)
      expect(audio_profile.main(['/nonexistent/x.wav'])).toBe(2)
      expect(log[1]).toBe('找不到 /nonexistent/x.wav')
    } finally {
      spy.mockRestore()
    }
  })
})
