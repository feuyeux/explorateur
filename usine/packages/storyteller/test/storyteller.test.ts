// storyteller.test.ts — @feuille/storyteller 归流门禁（storyteller-video/scripts
// 两脚本的行为契约对应）：
//   shot_transform   镜头插值（static/pull/pan + s<1 端点镜像）
//   synth_gavel      醒木合成（apad whole_dur=0.25）
//   build_card_html  字卡页：GEO 注入坐标 + token/pun/vow span + 状态契约
//   matte_unpremultiply  黑底字卡按色表分解（精确色 255 / 纯黑 0 / 近色部分透明）
//   draw_stage_*     舞台像素（接触影 = PIL RGBA 替换语义的直证）
//   render e2e       真实 Edge 字卡 + 假 mp3（lavfi 静音）→ 帧序列 + 幂等
//   assemble e2e     合成帧（32×64）→ 叠化转场 + 醒木混音成片
// 反向验证：缺 TTS 产物 / --act 未知幕 必须 FAIL（错误信息里 gen_tts.py
// 引用已随归流改指 feuille karaoke tts）。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { createCanvas } from '@napi-rs/canvas'
import sharp from 'sharp'
import { afterAll, describe, expect, it } from 'vitest'

import { audio, createPilDraw, platform, rig, scenes } from '@feuille/core'
import type { RGB } from '@feuille/core'

import * as st from '../src/index.js'
import {
  GEO, buildCardHtml, drawStageBack, drawStageFront, matteUnpremultiply,
  renderWordCard, shotTransform, synthGavel,
} from '../src/render_act_frames.js'

const HAS_BROWSER = platform.browserPath() !== null

function lavfi(out: string, args: string[]): void {
  const FFMPEG = platform.ffmpeg()!
  const r = spawnSync(FFMPEG, ['-y', '-loglevel', 'error', ...args, out], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`lavfi FAILED: ${r.stderr}`)
}

async function solidPng(path: string, rgb: [number, number, number], w = 32, h = 64): Promise<void> {
  await sharp({ create: { width: w, height: h, channels: 3, background: { r: rgb[0], g: rgb[1], b: rgb[2] } } })
    .png().toFile(path)
}

describe('shotTransform：帧序 → (scale, xoff, yoff)', () => {
  it('static：全程 (1, 0, 0)', () => {
    for (const [s, x, y] of shotTransform({ kind: 'static' }, 5, 30)) {
      expect(s).toBe(1.0)
      expect(x).toBe(0.0)
      expect(y).toBe(0.0)
    }
  })

  it('push：s0→s1 平滑推进（smoothstep：首尾一阶导 0）', () => {
    const got = shotTransform({ kind: 'push', start: 1.0, end: 1.1 }, 9, 30)
    expect(got[0]![0]).toBeCloseTo(1.0, 10)
    expect(got[8]![0]).toBeCloseTo(1.1, 10)
    for (let k = 1; k < 8; k++) {
      const u = k / 8, e = u * u * (3 - 2 * u)
      expect(got[k]![0]).toBeCloseTo(1.0 + 0.1 * e, 10)
    }
  })

  it('pull：push 端点对调（zoom-out 语义）', () => {
    const got = shotTransform({ kind: 'pull', start: 1.0, end: 1.1 }, 9, 30)
    expect(got[0]![0]).toBeCloseTo(1.1, 10)
    expect(got[8]![0]).toBeCloseTo(1.0, 10)
  })

  it('pan_l/pan_r：行程 = 画布宽 4%，方向由 kind 定', () => {
    const l = shotTransform({ kind: 'pan_l' }, 5, 30, 1080)
    expect(l[0]![1]).toBeCloseTo(0.04 * 1080, 10)
    expect(l[2]![1]).toBeCloseTo(0, 10)
    expect(l[4]![1]).toBeCloseTo(-0.04 * 1080, 10)
    const r = shotTransform({ kind: 'pan_r' }, 5, 30, 1080)
    expect(r[0]![1]).toBeCloseTo(-0.04 * 1080, 10)
    expect(r[4]![1]).toBeCloseTo(0.04 * 1080, 10)
  })

  it('画布满幅纪律：s<1 的端点镜像到 ≥1（不露底）', () => {
    const got = shotTransform({ kind: 'push', start: 0.8, end: 1.0 }, 5, 30)
    // lo=0.8 → s0=0.8+0.4=1.2、s1=1.0+0.4=1.4
    expect(got[0]![0]).toBeCloseTo(1.2, 10)
    expect(got[4]![0]).toBeCloseTo(1.4, 10)
    for (const [s] of got) expect(s).toBeGreaterThanOrEqual(1.0)
  })

  it('nFrames=1：u=0 → 起点', () => {
    const got = shotTransform({ kind: 'push', start: 1.0, end: 1.2 }, 1, 30)
    expect(got).toEqual([[1.0, 0.0, 0.0]])
  })
})

describe('synthGavel：醒木合成（fps 形参原样保留未参与滤镜图）', () => {
  it('apad whole_dur=0.25 → 时长 ≈0.25s', () => {
    const d = mkdtempSync(join(tmpdir(), 'storyteller-gavel-'))
    try {
      const wav = join(d, 'gavel.wav')
      synthGavel(wav, 30, platform.ffmpeg()!)
      expect(existsSync(wav)).toBe(true)
      const dur = audio.probeDuration(wav)
      expect(dur).toBeGreaterThan(0.24)
      expect(dur).toBeLessThan(0.30)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('buildCardHtml：字卡页（GEO 注入 + 状态契约）', () => {
  const ACT = { id: 'a1', chapter: '第一回', subtitle: '回目', quote: '原文摘录', vowel: ['开讲'] }
  const toks = [{ text: '开讲', start: 0.2 }, { text: '一段', start: 0.8 }]
  const html = buildCardHtml([[ACT, '开讲一段。', toks]], '/*fonts*/')

  it('GEO 坐标注入：ptext/ktext/quote 与舞台几何同源', () => {
    expect(html).toContain(`left:${GEO.ptext[0]}px; top:${GEO.ptext[1]}px; `
      + `width:${GEO.ptext[2] - GEO.ptext[0]}px; height:${GEO.ptext[3] - GEO.ptext[1]}px;`)
    expect(html).toContain(`left:${GEO.ktext[0]}px; top:${GEO.ktext[1]}px; `
      + `width:${GEO.ktext[2] - GEO.ktext[0]}px; height:${GEO.ktext[3] - GEO.ktext[1]}px;`)
    expect(html).toContain(`left:${GEO.quote[0]}px; top:${GEO.quote[1]}px;`)
  })

  it('按词序切正文：token span（data-i）+ 标点 .pun + 韵脚 .vow + data-n', () => {
    expect(html).toContain('<span class="tok dim vow" data-i="0">开讲</span>')
    expect(html).toContain('<span class="tok dim" data-i="1">一段</span>')
    expect(html).toContain('<span class="pun">。</span>')
    expect(html).toContain('id="s-zh-a1" data-n="2"')
  })

  it('quote 有则出、无则不出；fonts.css 注入；章文转义', () => {
    expect(html).toContain('<div class="quote">原文摘录</div>')
    expect(html).toContain('/*fonts*/')
    const noQuote = buildCardHtml([[{ id: 'a2', chapter: '<回>' } as never, '书', [{ text: '书', start: 0 }]]], '')
    expect(noQuote).not.toContain('class="quote"')
    expect(noQuote).toContain('<div class="ch">&lt;回&gt;</div>')
  })

  it('状态契约脚本照发：state<0 全 dim / N≥len 全亮 / 最新金色 .cur', () => {
    expect(html).toContain(`if (isNaN(state) || state < 0) el.classList.add('dim');`)
    expect(html).toContain(`else if (state >= n) el.classList.add('sung');`)
    expect(html).toContain(`else if (i < state) el.classList.add(i === state - 1 ? 'cur' : 'sung');`)
  })
})

describe('matteUnpremultiply：黑底字卡按色表分解', () => {
  it('精确色表色 → alpha 255；纯黑 → 0；近色 → 255−最近色距（截断）', async () => {
    const d = mkdtempSync(join(tmpdir(), 'storyteller-matte-'))
    try {
      // 4×2：INK / GOLD / 纯黑 / MUT / DIM / VOWEL / PAPER / 近 INK 的 (50,40,30)
      const rgb = Buffer.from([
        44, 36, 24, 184, 134, 11, 0, 0, 0, 138, 124, 98,
        196, 188, 170, 176, 85, 46, 242, 234, 216, 50, 40, 30,
      ])
      const png = join(d, 'card.png')
      await sharp(rgb, { raw: { width: 4, height: 2, channels: 3 } }).png().toFile(png)
      const { data } = await matteUnpremultiply(png)
      const px = (i: number): [number, number, number, number] =>
        [data[i * 4]!, data[i * 4 + 1]!, data[i * 4 + 2]!, data[i * 4 + 3]!]
      expect(px(0)).toEqual([44, 36, 24, 255])    // INK
      expect(px(1)).toEqual([184, 134, 11, 255])  // GOLD
      expect(px(2)).toEqual([44, 36, 24, 0])      // 纯黑 → 透明（色值无意义，最近色仍是 INK）
      expect(px(3)).toEqual([138, 124, 98, 255])  // MUT
      expect(px(4)).toEqual([196, 188, 170, 255]) // DIM
      expect(px(5)).toEqual([176, 85, 46, 255])   // VOWEL
      expect(px(6)).toEqual([242, 234, 216, 255]) // PAPER
      // 近 INK：最近色距 sqrt(88) → alpha = 255−9.38 截断（astype(uint8) 口径）
      expect(px(7)).toEqual([44, 36, 24, Math.trunc(255 - Math.sqrt(88))])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('舞台像素（PIL RGBA 4 元组 fill = 替换语义的直证）', () => {
  it('接触影：不透明案沿上画 (0,0,0,26) → 像素恰为 (0,0,0,26)（不是混合）', () => {
    const canvas = createCanvas(1080, 1920)
    const ctx = canvas.getContext('2d')
    const d = new scenes.DrawScaled(createPilDraw(ctx), 1)
    drawStageBack(d, rig.SCENE as Record<string, RGB>, rig.hexc('#8C6239'))
    drawStageFront(d, rig.SCENE as Record<string, RGB>, rig.hexc('#8C6239'))
    const px = ctx.getImageData(410, 1555, 1, 1).data   // 椭圆 [180,1544,640,1566] 中心
    expect([px[0], px[1], px[2], px[3]]).toEqual([0, 0, 0, 26])
  })

  it('顶梁 / 匾板 / 卷面色：mix 公式直查（canvas 8bit 舍入 ±1）', () => {
    const canvas = createCanvas(1080, 1920)
    const ctx = canvas.getContext('2d')
    const ident = rig.hexc('#8C6239')
    const d = new scenes.DrawScaled(createPilDraw(ctx), 1)
    drawStageBack(d, rig.SCENE as Record<string, RGB>, ident)
    const beam = ctx.getImageData(540, 40, 1, 1).data
    const expBeam = rig.mix(rig.SCENE['wood']!, [40, 30, 20], 0.45)
    const plaque = ctx.getImageData(540, 385, 1, 1).data
    const expPlaque = rig.mix([242, 234, 216], ident, 0.08)
    for (let c = 0; c < 3; c++) {
      expect(Math.abs(beam[c]! - expBeam[c]!)).toBeLessThanOrEqual(1)
      expect(Math.abs(plaque[c]! - expPlaque[c]!)).toBeLessThanOrEqual(1)
    }
  })
})

describe('render e2e：真 Edge 字卡 + lavfi 静音 mp3 → 帧序列', () => {
  const d = mkdtempSync(join(tmpdir(), 'storyteller-render-'))
  afterAll(() => rmSync(d, { recursive: true, force: true }))

  // 帧数口径（fps=5）：preroll 0.2→1 | tok1 0.6→3 | tok2 (1.4−0.8)+0.2=0.8→4 | done 0.2→1 = 9 帧
  function writeFixture(): void {
    mkdirSync(join(d, 'tts'), { recursive: true })
    lavfi(join(d, 'tts', 'zh-a1.mp3'),
      ['-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono', '-t', '1.4', '-c:a', 'libmp3lame'])
    writeFileSync(join(d, 'tts', 'zh-a1.json'), JSON.stringify({
      text: '开讲一段。',
      tokens: [{ text: '开讲', start: 0.2 }, { text: '一段', start: 0.8 }],
    }))
    writeFileSync(join(d, 'acts.json'), JSON.stringify({
      storyteller_id: 'changlianke',
      formats: [{ w: 1080, h: 1920 }],
      timing: { preroll: 0.2, tail: 0.2, done: 0.2 },
      acts: [{
        id: 'a1', scene: ['sun'], chapter: '测试', subtitle: '回目', quote: '原文',
        vowel: ['开讲'], gavel: true,
        shot: { kind: 'push', start: 1.0, end: 1.05 },
      }],
    }))
  }

  // 这两条错误路径断言要走到参数校验，而 render 前置的浏览器探测在无浏览器
  // 主机（RSI macOS guest 的 FEUILLE_BROWSER 哨兵）上先行报缺——按本文件
  // 惯例跳过并明说；SKIP 不是 PASS，浏览器真机覆盖归 Windows wave host。
  it(HAS_BROWSER
    ? '缺 TTS 产物 → FAIL（错误信息指 feuille karaoke tts，不再指 gen_tts.py）'
    : '跳过：本机无 Chromium 系浏览器', async () => {
    if (!HAS_BROWSER) return
    mkdirSync(join(d, 'tts'), { recursive: true })
    writeFileSync(join(d, 'acts.json'), JSON.stringify({
      storyteller_id: 'changlianke',
      formats: [{ w: 1080, h: 1920 }],
      acts: [{ id: 'a1', scene: ['sun'] }],
    }))
    await expect(st.render_act_frames.main([join(d, 'acts.json'), join(d, 'out-err')]))
      .rejects.toThrow(/缺 TTS 产物 .*先跑 feuille karaoke tts/)
  })

  it(HAS_BROWSER
    ? '--act 未知幕 → FAIL：幕表里没有'
    : '跳过：本机无 Chromium 系浏览器', async () => {
    if (!HAS_BROWSER) return
    writeFixture()
    await expect(st.render_act_frames.main(
      [join(d, 'acts.json'), join(d, 'out-act'), '--act', 'nope']))
      .rejects.toThrow(/幕表里没有/)
  })

  it(HAS_BROWSER
    ? '幕帧全链路：gavel + 字卡缓存 + 9 帧合成（幂等：重渲逐字节一致）'
    : '跳过：本机无 Chromium 系浏览器', { timeout: 300_000 }, async () => {
    if (!HAS_BROWSER) return
    writeFixture()
    const out = join(d, 'out')
    const rc1 = await st.render_act_frames.main([join(d, 'acts.json'), out, '--fps', '5'])
    expect(rc1).toBe(0)
    expect(existsSync(join(out, 'gavel.wav'))).toBe(true)
    expect(existsSync(join(out, '_cards', 'src.html'))).toBe(true)
    // 状态截图缓存：pre(-1) + 0 + 1 + done(2) = 4 张
    const cards = ['a1-pre', 'a1-0', 'a1-1', 'a1-2']
      .map((k) => join(out, '_cards', `${k}.png`))
    for (const c of cards) expect(existsSync(c)).toBe(true)
    // 9 帧全出，全 1080×1920
    const hashes: string[] = []
    for (let k = 0; k < 9; k++) {
      const f = join(out, `fa1-${String(k).padStart(4, '0')}.png`)
      expect(existsSync(f)).toBe(true)
      const meta = await sharp(f).metadata()
      expect(meta.width).toBe(1080)
      expect(meta.height).toBe(1920)
      hashes.push(readFileSync(f).toString('base64'))
    }
    // 卷面唱词区域随状态变亮（dim → sung 色差必须在帧里可见）
    const pre = await sharp(join(out, 'fa1-0000.png'))
      .extract({ left: 90, top: 1645, width: 900, height: 227 }).raw().toBuffer()
    const done = await sharp(join(out, 'fa1-0008.png'))
      .extract({ left: 90, top: 1645, width: 900, height: 227 }).raw().toBuffer()
    expect(pre.equals(done)).toBe(false)
    // 幂等（不变量⑦）：同参数重渲逐字节一致（字卡缓存命中，Edge 不再跑）
    const rc2 = await st.render_act_frames.main([join(d, 'acts.json'), out, '--fps', '5'])
    expect(rc2).toBe(0)
    for (let k = 0; k < 9; k++) {
      const f = join(out, `fa1-${String(k).padStart(4, '0')}.png`)
      expect(readFileSync(f).toString('base64')).toBe(hashes[k])
    }
  })

  // AGENTS.md：截图后跑白页哨兵。文件存在 ≠ 渲对了——file:// URL 写错时
  // headless 抓的是一张近纯白的错误页：尺寸合法、有文件、exit 0。没有这道
  // 判据，白页会一路静默流进字卡视频（这是纪律12「没验不许长得像验过了」）。
  it(HAS_BROWSER
    ? '白页哨兵：真页面放行，近纯白页面当场判失败'
    : '跳过：本机无 Chromium 系浏览器', { timeout: 180_000 }, async () => {
    if (!HAS_BROWSER) return
    const browser = platform.browserPath()!

    // (a) 真页面（有字）→ 放行
    const good = join(d, 'card-good.html')
    const goodPng = join(d, 'card-good.png')
    writeFileSync(good,
      '<!DOCTYPE html><html><body style="margin:0;background:#101010;color:#fff">'
      + '<h1>开讲</h1></body></html>', 'utf-8')
    await expect(renderWordCard(good, goodPng, 400, 700, '', browser)).resolves
      .toBeUndefined()

    // (b) 近纯白页面 → BLANK RENDER。构造方式与真实故障同源：URL 抓不到
    //     目标时 headless 给出的就是一张空白底
    const blank = join(d, 'card-blank.html')
    const blankPng = join(d, 'card-blank.png')
    writeFileSync(blank,
      '<!DOCTYPE html><html><body style="margin:0;background:#fff"></body></html>', 'utf-8')
    await expect(renderWordCard(blank, blankPng, 400, 700, '', browser))
      .rejects.toThrow(/BLANK RENDER/)
  })
})

describe('assemble e2e：合成帧 → 叠化转场 + 醒木混音成片', () => {
  const d = mkdtempSync(join(tmpdir(), 'storyteller-assemble-'))
  afterAll(() => rmSync(d, { recursive: true, force: true }))

  it('两幕 + 转场 + gavel → 单画幅 mp4（24 帧 @5fps）', { timeout: 180_000 }, async () => {
    const F = join(d, 'frames')
    mkdirSync(F, { recursive: true })
    mkdirSync(join(d, 'tts'), { recursive: true })
    mkdirSync(join(d, 'video'), { recursive: true })
    await solidPng(join(d, 'video', 'cover_portrait.png'), [200, 180, 160])
    await solidPng(join(d, 'video', 'outro_card.png'), [160, 150, 140])
    synthGavel(join(F, 'gavel.wav'), 5, platform.ffmpeg()!)
    for (const [aid, col] of [['a1', [180, 60, 60]], ['a2', [60, 60, 180]]] as const) {
      lavfi(join(d, 'tts', `zh-${aid}.mp3`),
        ['-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono', '-t', '1.4', '-c:a', 'libmp3lame'])
      writeFileSync(join(d, 'tts', `zh-${aid}.json`), JSON.stringify({
        text: '开讲一段。',
        tokens: [{ text: '开讲', start: 0.2 }, { text: '一段', start: 0.8 }],
      }))
      for (let k = 0; k < 9; k++) {
        await solidPng(join(F, `f${aid}-${String(k).padStart(4, '0')}.png`), col as [number, number, number])
      }
    }
    writeFileSync(join(d, 'acts.json'), JSON.stringify({
      formats: [{ w: 1080, h: 1920 }],
      timing: { fps: 5, intro: 0.4, outro: 0.4, transition: 0.4, preroll: 0.2, tail: 0.2, done: 0.2 },
      acts: [{ id: 'a1', gavel: true }, { id: 'a2' }],
    }))
    const out = join(d, 'out.mp4')
    const rc = await st.assemble_storyteller.main([join(d, 'acts.json'), F, out])
    expect(rc).toBe(0)
    expect(existsSync(out)).toBe(true)
    // cover 2 + a1 9 + 转场 2 + a2 9 + outro 2 = 24 帧 @5fps = 4.8s
    const dur = audio.probeDuration(out)
    expect(Math.abs(dur - 4.8)).toBeLessThan(0.3)
    const r = spawnSync(platform.ffmpeg()!, ['-hide_banner', '-i', out], { encoding: 'utf8' })
    expect(r.stderr).toMatch(/Audio: aac/)
  })
})

describe('barrel：@feuille/storyteller 导出面', () => {
  it('两个子模块 + CLI main', () => {
    expect(Object.keys(st).sort()).toEqual(['assemble_storyteller', 'render_act_frames'])
    expect(typeof st.render_act_frames.main).toBe('function')
    expect(typeof st.assemble_storyteller.main).toBe('function')
  })
})
