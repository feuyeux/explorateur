// karaoke.test.ts — @feuille/karaoke 归流门禁（karaoke-video/scripts 四脚本的
// 行为契约对应）：
//   gen_tts     词级时间线映射（纯函数）+ 真实 edge-tts 一次（免费服务，
//               不在额度红线内——verify_tts 同款先例）
//   build_video d30 网格吸附 + 最小产线端到端（真 Chrome 状态帧 + 假 mp3 →
//               成片 → verify-sync 验收闭环）+ video_build.html 原样镜像怪癖
//   verify_sync 灰度差口径（≥12 才计数）+ 探点数学 + 失配 → SYNC FAILURES
//   scan_blank  白帧判定 + 采样扫描两态
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import sharp from 'sharp'
import { afterAll, describe, expect, it, vi } from 'vitest'

import { platform } from '@feuille/core'

import { build_video, gen_tts, scan_blank, verify_sync } from '../src/index.js'

const HAS_BROWSER = platform.browserPath() !== null

async function solidPng(path: string, rgb: [number, number, number], w = 64, h = 64): Promise<string> {
  await sharp({ create: { width: w, height: h, channels: 3, background: { r: rgb[0], g: rgb[1], b: rgb[2] } } })
    .png().toFile(path)
  return path
}

function lavfi(out: string, src: string): void {
  const FFMPEG = platform.ffmpeg()!
  const r = spawnSync(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', src,
    '-pix_fmt', 'yuv420p', out], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`lavfi FAILED: ${r.stderr}`)
}

describe('tokenTimings：词边界 → 显示 token 的按比例切分', () => {
  it('zh「一本」一界跨两 token：start 按字符份额切、end 同界', () => {
    const got = gen_tts.tokenTimings(['一', '本'], [{ w: '一本', t: 1.0, d: 0.4 }])
    expect(got).toEqual([
      { text: '一', start: 1.0, end: 1.4 },
      { text: '本', start: 1.2, end: 1.4 },
    ])
  })

  it('token 内空格：流内空格跳过不计界内字符（"hello world" 单 token）', () => {
    const got = gen_tts.tokenTimings(['hello world'], [
      { w: 'hello', t: 0.1, d: 0.2 },
      { w: 'world', t: 0.3, d: 0.2 },
    ])
    expect(got).toEqual([{ text: 'hello world', start: 0.1, end: 0.5 }])
  })

  it('界只盖住部分 token：未被盖到的 token start/end = null（Python None 落 json null）', () => {
    const got = gen_tts.tokenTimings(['a', 'b'], [{ w: 'a', t: 0.1, d: 0.2 }])
    expect(got).toHaveLength(2)
    expect(got[0]!['text']).toBe('a')
    expect(got[0]!['start']).toBe(0.1)
    // 0.1+0.2 的 IEEE 尾数（Python 同款浮点算术，逐位一致）
    expect(got[0]!['end']).toBe(0.1 + 0.2)
    expect(got[1]).toEqual({ text: 'b', start: null, end: null })
  })

  it('多 token 多界逐段覆盖（ja 嵌套界形态：切点在 token START，嵌套零长态无害）', () => {
    // お茶一杯 → 界 いっぱい（0.38–0.84）盖住 一+杯 的形态。into 数的是**本界内**
    // 已消费字符（wl - cov），不是流内前缀：杯 前只吃了一（1/4），
    // 故 杯 start = 0.38 + 0.46*(1/4)，两者 end = 0.84
    const got = gen_tts.tokenTimings(['お', '茶', '一', '杯'], [
      { w: 'お茶', t: 0.0, d: 0.38 },
      { w: 'いっぱい', t: 0.38, d: 0.46 },
    ])
    expect(got[0]).toEqual({ text: 'お', start: 0, end: 0.38 })
    expect(got[1]!['start']).toBeCloseTo(0.38 / 2, 10) // 0 + 0.38*(1/2)
    expect(got[1]!['end']).toBe(0.38)
    expect(got[2]!['text']).toBe('一')
    expect(got[2]!['start']).toBe(0.38)
    expect(got[2]!['end']).toBeCloseTo(0.84, 10) // 0.38+0.46 的 IEEE 尾数
    expect(got[3]!['start']).toBeCloseTo(0.38 + 0.46 * (1 / 4), 10)
    expect(got[3]!['end']).toBeCloseTo(0.84, 10)
  })
})

describe('gen_tts main：真实 edge-tts 一次（免费服务；verify_tts 同款先例）', () => {
  it('voices.json → mp3 + json（键序 = Python dict 插入序）+ 逐 token 打印行', async () => {
    const d = mkdtempSync(join(tmpdir(), 'karaoke-gentts-'))
    try {
      writeFileSync(join(d, 'voices.json'), JSON.stringify({
        tts_dir: 'out',
        langs: [{
          locale: 'zh-CN', voice: 'zh-CN-XiaoxiaoNeural', text: '一杯茶',
          tokens: ['一', '杯', '茶'], persona: 'lin', latin: false, gender: 'female',
        }],
      }), 'utf8')
      const log: string[] = []
      const spy = vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => { log.push(a[0] as string) })
      try {
        // 原版 out_dir 缺省是**相对 cwd** 的 cfg.tts_dir（Python pathlib 相对
        // 路径同款）——显式传绝对 outdir，不往仓库 cwd 里拉屎
        expect(await gen_tts.main([join(d, 'voices.json'), join(d, 'out')])).toBe(0)
      } finally {
        spy.mockRestore()
      }
      const out = join(d, 'out')
      expect(existsSync(join(out, 'zh-CN.mp3'))).toBe(true)
      expect((readFileSync(join(out, 'zh-CN.mp3')) as Buffer).length).toBeGreaterThan(1000)
      const data = JSON.parse(readFileSync(join(out, 'zh-CN.json'), 'utf8'))
      // 键序逐键断言（Python dict 插入序 → JSON 落盘序）
      expect(Object.keys(data)).toEqual(
        ['locale', 'persona', 'latin', 'gender', 'text', 'words', 'tokens'])
      expect(data['locale']).toBe('zh-CN')
      expect((data['words'] as unknown[]).length).toBeGreaterThan(0)
      expect((data['tokens'] as Array<{ text: string }>).map((t) => t['text'])).toEqual(['一', '杯', '茶'])
      for (const t of data['tokens'] as Array<{ start: unknown; end: unknown }>) {
        expect(typeof t['start']).toBe('number')
        expect(typeof t['end']).toBe('number')
      }
      // 打印行：'<locale>: <tok> <start:.2f>-<end:.2f> | …'
      expect(log[0]).toMatch(/^zh-CN: 一 0\.\d\d-0\.\d\d \| 杯 /)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  }, 30_000)

  it('缺 voices.json → usage + 2（Python IndexError 裸炸的叶子统一口径）', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      expect(await gen_tts.main([])).toBe(2)
    } finally {
      err.mockRestore()
    }
  })
})

describe('build_video：d30 网格吸附与 CLI 口径', () => {
  it('d30：整格不动、非整格向上吸附（ceil(d*30-1e-9)/30）', () => {
    expect(build_video.d30(1.0)).toBe(1.0)       // 30 帧整 → 不动
    expect(build_video.d30(0.5)).toBe(0.5)       // 15 帧整 → 不动
    expect(build_video.d30(1 / 30)).toBe(1 / 30)
    expect(build_video.d30(0.0334)).toBe(2 / 30) // 1.002 帧 → 2 帧
    expect(build_video.d30(0.032)).toBe(1 / 30)  // 0.96 帧 → 1 帧
  })

  it('缺 video.json → usage + 2', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      expect(await build_video.main([])).toBe(2)
    } finally {
      err.mockRestore()
    }
  })
})

describe('verify_sync：灰度差口径与探点数学（真 ffmpeg，离线素材）', () => {
  const d = mkdtempSync(join(tmpdir(), 'karaoke-vs-'))
  afterAll(() => rmSync(d, { recursive: true, force: true }))

  it('diffGray：差 <12 的编码噪声不计、≥12 逐像素计数（histogram[12:] 口径）', async () => {
    const a = await solidPng(join(d, 'a.png'), [100, 100, 100])
    const b = await solidPng(join(d, 'b.png'), [105, 105, 105])  // 差 5 → 不计
    const c = await solidPng(join(d, 'c.png'), [160, 160, 160])  // 差 60 → 全计
    expect(await verify_sync.diffGray(a, a)).toBe(0)
    expect(await verify_sync.diffGray(a, b)).toBe(0)
    expect(await verify_sync.diffGray(a, c)).toBe(64 * 64)
  })

  it('缺必填 → usage + 2；--threshold 坏值 → 2（argparse int 口径）', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      expect(await verify_sync.main(['--video', 'x'])).toBe(2)
      expect(await verify_sync.main(
        ['--video', 'x', '--frames', 'f', '--tts', 't', '--locales', 'xx',
          '--threshold', 'bogus'])).toBe(2)
    } finally {
      err.mockRestore()
    }
  })

  it('端到端两态：成片与状态帧同色 → 全 OK 0；状态帧异色 → SYNC FAILURES 抛出', async () => {
    const F = join(d, 'frames')
    const T = join(d, 'tts')
    mkdirSync(F, { recursive: true })
    mkdirSync(T, { recursive: true })
    // 状态帧：纯红（L≈76）
    for (const n of ['xx-pre.png', 'xx-0.png', 'xx-done.png']) {
      await solidPng(join(F, n), [255, 0, 0])
    }
    // seg wav 3 秒（scene 起点累进的时长源）
    const FFMPEG = platform.ffmpeg()!
    const r = spawnSync(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'lavfi',
      '-i', 'anullsrc=r=24000:cl=mono', '-t', '3', join(F, 'xx-seg.wav')], { encoding: 'utf8' })
    if (r.status !== 0) throw new Error(`seg wav FAILED: ${r.stderr}`)
    // tokens json：单 token → s0 = d - preroll - done = 3-0.8-0.5 = 1.7
    writeFileSync(join(T, 'xx.json'),
      JSON.stringify({ tokens: [{ text: 'x', start: 0.5, end: 1.5 }] }), 'utf8')
    // 成片 A：纯红 3 秒 → 与状态帧零差
    const vidA = join(d, 'ok.mp4')
    lavfi(vidA, 'color=red:s=64x64:d=3')
    const log: string[] = []
    const spy = vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => { log.push(a[0] as string) })
    try {
      expect(await verify_sync.main(
        ['--video', vidA, '--frames', F, '--tts', T, '--locales', 'xx',
          '--intro', '0', '--threshold', '100'])).toBe(0)
      expect(log.length).toBe(4) // pre / word0 / done + all scenes in sync
      expect(log[0]).toMatch(/^xx {7}pre +t=/)
      // word0 探 0+0.8+1.7/2 = 1.65（t= 按 7 位宽右对齐）
      expect(log[1]).toContain('t=   1.65')
      expect(log[3]).toBe('all scenes in sync')
    } finally {
      spy.mockRestore()
    }

    // 状态帧换纯蓝（L≈29，灰度差 ≈47 ≥12 → 全像素计数）→ 失配
    for (const n of ['xx-pre.png', 'xx-0.png', 'xx-done.png']) {
      await solidPng(join(F, n), [0, 0, 255])
    }
    await expect(verify_sync.main(
      ['--video', vidA, '--frames', F, '--tts', T, '--locales', 'xx',
        '--intro', '0', '--threshold', '100']))
      .rejects.toThrow(/SYNC FAILURES: xx\/(pre|word0|done)/)
  })
})

describe('scan_blank：白帧判定与 CLI 两态', () => {
  const d = mkdtempSync(join(tmpdir(), 'karaoke-sb-'))
  afterAll(() => rmSync(d, { recursive: true, force: true }))

  it('whiteRatio：纯白 ≈1、纸色/深色 ≈0（min(R,G,B) >= 250 口径）', async () => {
    expect(await scan_blank.whiteRatio(await solidPng(join(d, 'w.png'), [255, 255, 255]))).toBeGreaterThan(0.99)
    expect(await scan_blank.whiteRatio(await solidPng(join(d, 'p.png'), [232, 226, 212]))).toBe(0)
    expect(await scan_blank.whiteRatio(await solidPng(join(d, 'k.png'), [28, 27, 24]))).toBe(0)
  })

  it('scan：纯白视频含白帧 → false；纸色视频全干净 → true（真 ffmpeg 采样）', async () => {
    const whiteV = join(d, 'white.mp4')
    const paperV = join(d, 'paper.mp4')
    lavfi(whiteV, 'color=white:s=64x64:d=2')
    lavfi(paperV, 'color=0xE8E2D4:s=64x64:d=2')
    const log: string[] = []
    const spy = vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => { log.push(a[0] as string) })
    try {
      expect(await scan_blank.scan(whiteV, 1, 0.75)).toBe(false)
      expect(log[0]).toMatch(/white\.mp4: 2 frames sampled, blank\/white: \[\('f001\.png', 1\), \('f002\.png', 1\)\]  \[FAIL\]/)
      expect(await scan_blank.scan(paperV, 1, 0.75)).toBe(true)
      expect(log[1]).toMatch(/paper\.mp4: \d+ frames sampled, blank\/white: none  \[ok\]/)
    } finally {
      spy.mockRestore()
    }
  })

  it('main：无视频 → 2；-h → 0；白片 → 1；干净片 → 0；--fps 坏值 → 2', async () => {
    const whiteV = join(d, 'w2.mp4')
    const paperV = join(d, 'p2.mp4')
    lavfi(whiteV, 'color=white:s=64x64:d=1')
    lavfi(paperV, 'color=0xE8E2D4:s=64x64:d=1')
    const log = vi.spyOn(console, 'log').mockImplementation(() => {})
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      expect(await scan_blank.main([])).toBe(2)
      expect(await scan_blank.main(['-h'])).toBe(0)
      expect(await scan_blank.main([whiteV])).toBe(1)
      expect(await scan_blank.main([paperV, whiteV])).toBe(1)
      expect(await scan_blank.main([paperV])).toBe(0)
      expect(await scan_blank.main(['--fps', 'bogus', paperV])).toBe(2)
    } finally {
      log.mockRestore()
      err.mockRestore()
    }
  })
})

describe('build_video 端到端：最小产线闭环（真 Chrome 状态帧 → 成片 → 验收）', () => {
  // 无 Chromium 的机器整块 SKIP（Python 侧脚本的「找不到浏览器就退出」对应形态）
  it.skipIf(!HAS_BROWSER)('video.json → 状态帧 + 成片；verify-sync 对成品回 0；video_build.html 落盘但截图走原始 src（原样镜像）', async () => {
    const FFMPEG = platform.ffmpeg()!
    const d = mkdtempSync(join(tmpdir(), 'karaoke-e2e-'))
    try {
      // 最小场景页：?state= 控制背景色（-1 preroll 深色、0 红、1 done 绿）——
      // 纸色系选色避开白页哨兵（min 通道 < 250）
      writeFileSync(join(d, 'video_src.html'), `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>/*__FONTS__*/</style>
<style>body{margin:0;width:100vw;height:100vh}</style></head><body>
<script>
const s = new URLSearchParams(location.search).get('state')
const c = s === '-1' ? '#1c1b18' : s === '0' ? '#d8453b' : '#367850'
document.body.style.background = c
</script></body></html>`, 'utf8')
      writeFileSync(join(d, 'fonts.css'), '/* no fonts needed */', 'utf8')
      // 假 TTS：1.2 秒静音 mp3 + 单 token（state0 从 0.5s 起）
      const ttsDir = join(d, 'tts')
      mkdirSync(ttsDir, { recursive: true })
      const r = spawnSync(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'lavfi',
        '-i', 'anullsrc=r=24000:cl=mono', '-t', '1.2', '-c:a', 'libmp3lame',
        join(ttsDir, 'xx.mp3')], { encoding: 'utf8' })
      if (r.status !== 0) throw new Error(`mp3 FAILED: ${r.stderr}`)
      writeFileSync(join(ttsDir, 'xx.json'),
        JSON.stringify({ locale: 'xx', words: [{ w: 'x', t: 0.5, d: 0.4 }],
          tokens: [{ text: 'x', start: 0.5, end: 0.9 }] }), 'utf8')
      // 红色 intro 图（卡片 filter 是 no-op scale，防白页哨兵误杀）
      await solidPng(join(d, 'poster.png'), [216, 69, 59], 128, 96)
      // 探点几何：preroll 0.6 > pre 探针偏移 0.4（pre 探针必须落在 pre 状态内）
      writeFileSync(join(d, 'video.json'), JSON.stringify({
        src: 'video_src.html', fonts_css: 'fonts.css', tts_dir: 'tts',
        locales: ['xx'], preroll: 0.6, tail: 0.2, done: 0.2,
        intro: 0.3, outro: 0.3, intro_image: 'poster.png', desk: '0xe8e2d4',
        formats: [{ name: 'mini', w: 128, h: 96, frames: 'frames',
          output: 'out.mp4', fmt: null, poster_filter: 'scale=128:96' }],
      }), 'utf8')

      const log: string[] = []
      const spy = vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => { log.push(a[0] as string) })
      try {
        expect(await build_video.main([join(d, 'video.json')])).toBe(0)
      } finally {
        spy.mockRestore()
      }
      const out = join(d, 'out.mp4')
      expect(existsSync(out)).toBe(true)
      // 状态帧齐：pre / 0 / done（状态机 URL 渲出来的真 Chrome 帧）
      for (const n of ['xx-pre.png', 'xx-0.png', 'xx-done.png']) {
        expect(existsSync(join(d, 'frames', n)), `frames/${n}`).toBe(true)
      }
      // video_build.html 落盘（fonts 注入产物）但截图走原始 src——原样镜像的怪癖
      expect(existsSync(join(d, 'video_build.html'))).toBe(true)
      expect(readFileSync(join(d, 'video_build.html'), 'utf8')).toContain('/* no fonts needed */')
      // 中间产物已清
      expect(existsSync(join(d, 'audio_all.wav'))).toBe(false)
      expect(existsSync(join(d, 'video_noaudio.mp4'))).toBe(false)
      expect(log.some((l) => l.startsWith('format: mini (128x96)'))).toBe(true)
      expect(log.some((l) => l.includes('wrote'))).toBe(true)

      // 成品回验：verify-sync 探点全 OK（宽松阈值：编码器噪声 + 页面渲染细节）
      // seg = preroll 0.6 + state0 (1.2-0.5+0.2=0.9) + done 0.2 = 1.7s
      expect(await verify_sync.main(
        ['--video', out, '--frames', join(d, 'frames'), '--tts', ttsDir,
          '--locales', 'xx', '--intro', '0.3', '--preroll', '0.6', '--done', '0.2',
          '--threshold', '3000'])).toBe(0)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  }, 120_000)
})
