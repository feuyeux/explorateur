// 舞台几何门：两套画幅的构图不许「看着差不多」，要有可量的位置。
//
// 为什么需要这道门：横版几何是照着竖版重排的一套新数值（说书人降倍、中轴
// 居中、卷面横铺），而改错一格像素不会报错——只会出一道「人掉出画面」或
// 「头顶钻进匾里」的成品，退出码照样 0。这里把四件事钉成断言：
//   1. 画幅 → 舞台是白名单：没定义的画幅必须抛错，不许退化成竖版；
//   2. 说书人头顶 / 中轴 / 可见身高落在预期（人的位置是构图的主锚点）；
//   3. 所有版面矩形（匾 / 案 / 卷面 / 文字区 / 道具）都在画布内且互不越界；
//   4. 两套几何都真的能画出东西（空画布是「几何对但没接线」的典型症状）。
//
// 头顶位置用 rig 的坐标变换复算，不抄死数字：
//   y = ground + yoff + s·(y_native − ground)，ground=1700，头顶含发 y_native≈923.4
import { createCanvas } from '@napi-rs/canvas'
import { describe, expect, it } from 'vitest'

import { createPilDraw, data, rig, scenes } from '@feuille/core'
import type { RGB } from '@feuille/core'

import {
  GEO, LANDSCAPE_STAGE, PORTRAIT_STAGE, type Stage,
  bgLayoutFor, drawStageBack, drawStageFront, stageGeometry,
} from '../src/render_act_frames.js'

const HEAD_NATIVE = 923.4
const HAND_NATIVE = 1521.0
const GROUND = 1700

const ST = data.storytellers()['changlianke']!

/** 画一次说书人，返回 alpha 包围盒（画幅原尺寸，ss=1 便于直接读像素） */
function actorBox(stage: Stage, mood = 'neutral', pose = 'both_hands') {
  const canvas = createCanvas(stage.w, stage.h)
  const ctx = canvas.getContext('2d')
  const d = createPilDraw(ctx)
  const raw = rig.poseFor(pose, 0.0, 0, ST)
  rig.drawCharacter(canvas, d, ST, 0, {
    scale: stage.actor.s, xoff: stage.actor.x, yoff: stage.actor.y,
    squash: 0.0, xscale: 1.0, head_dx: 0, head_dy: 0, brow_lift_extra: 0,
    pose: Object.fromEntries(
      Object.entries(raw).filter(([k]) => ['armL', 'armR', 'legL', 'legR'].includes(k))),
    openness: 0.0, blink: false, mood, ss: 1,
  })
  const px = ctx.getImageData(0, 0, stage.w, stage.h).data
  let x0 = stage.w, x1 = -1, y0 = stage.h, y1 = -1, n = 0
  for (let y = 0; y < stage.h; y++) {
    for (let x = 0; x < stage.w; x++) {
      if (px[(y * stage.w + x) * 4 + 3]! > 8) {
        n++
        if (x < x0) x0 = x
        if (x > x1) x1 = x
        if (y < y0) y0 = y
        if (y > y1) y1 = y
      }
    }
  }
  return { x0, x1, y0, y1, n, w: stage.w, h: stage.h }
}

const headTop = (stage: Stage) =>
  GROUND + stage.actor.y + stage.actor.s * (HEAD_NATIVE - GROUND)
const handY = (stage: Stage) =>
  GROUND + stage.actor.y + stage.actor.s * (HAND_NATIVE - GROUND)

/** 头部横向中心：扫头顶下方 180px 一带，避开手臂——both_hands 会把手臂张到画布边，
 *  整幅 bbox 的横向中心量出来是 504 而不是 405，容易被误当成站位错了。 */
function headCenterX(stage: Stage) {
  const canvas = createCanvas(stage.w, stage.h)
  const ctx = canvas.getContext('2d')
  const st = data.storytellers()['changlianke']!
  rig.drawCharacter(canvas, createPilDraw(ctx), st, 0, {
    scale: stage.actor.s, xoff: stage.actor.x, yoff: stage.actor.y,
    squash: 0.0, xscale: 1.0, head_dx: 0, head_dy: 0, brow_lift_extra: 0,
    pose: {}, openness: 0.0, blink: false, mood: 'neutral', ss: 1,
  })
  const yTop = Math.round(headTop(stage))
  const band = 180
  const px = ctx.getImageData(0, 0, stage.w, stage.h).data
  let x0 = stage.w, x1 = -1
  for (let y = yTop; y < Math.min(yTop + band, stage.h); y++) {
    for (let x = 0; x < stage.w; x++) {
      if (px[(y * stage.w + x) * 4 + 3]! > 8) {
        if (x < x0) x0 = x
        if (x > x1) x1 = x
      }
    }
  }
  return { x0, x1, cx: (x0 + x1) / 2 }
}

describe('画幅 → 舞台：白名单，未定义画幅判死', () => {
  it('1080×1920 → 竖版，1920×1080 → 横版（按对象身份，不是按数值相同）', () => {
    expect(stageGeometry(1080, 1920)).toBe(PORTRAIT_STAGE)
    expect(stageGeometry(1920, 1080)).toBe(LANDSCAPE_STAGE)
  })

  it('别的画幅抛错而不是退化成竖版（退化的症状是「画面全错但退出 0」）', () => {
    const bad: Array<[number, number]> = [[1080, 1081], [720, 1280], [3840, 2160], [1920, 1920]]
    for (const [w, h] of bad) {
      expect(() => stageGeometry(w, h), `${w}×${h}`).toThrow(/没有 .* 的舞台几何/)
    }
  })

  it('竖版数值保真：加横版这套改动没碰竖版几何', () => {
    expect(PORTRAIT_STAGE.actor).toEqual({ x: -135, y: 180, s: 1.75 })
    expect(PORTRAIT_STAGE.geo['paper']).toEqual([60, 1630, 1020, 1905])
    expect(PORTRAIT_STAGE.card.center).toBe(false)
    // GEO 仍是竖版那张表（同一个对象，不是复制品）
    expect(PORTRAIT_STAGE.geo).toBe(GEO)
  })

  it('两套几何是各自独立的表（横版不许引用竖版的矩形）', () => {
    expect(LANDSCAPE_STAGE.geo).not.toBe(PORTRAIT_STAGE.geo)
    expect(LANDSCAPE_STAGE.props).not.toBe(PORTRAIT_STAGE.props)
    expect(LANDSCAPE_STAGE.card).not.toBe(PORTRAIT_STAGE.card)
  })
})

describe.each([
  ['竖版', PORTRAIT_STAGE, 405],
  ['横版', LANDSCAPE_STAGE, 960],
] as const)('%s：说书人站位', (_name, stage, axisX) => {
  it(`头顶落在 ${Math.round(headTop(stage))}px（±14），没钻出画布也没顶穿匾`, () => {
    const b = actorBox(stage)
    expect(b.n).toBeGreaterThan(0)
    expect(b.y0).toBeGreaterThan(0)
    expect(Math.abs(b.y0 - headTop(stage))).toBeLessThanOrEqual(14)
    // 头顶不许被匾压住：匾底之下留气口
    expect(b.y0).toBeGreaterThan(stage.geo['plaque']![3]! + 16)
  })

  it(`中轴落在 ${axisX}px（±14）`, () => {
    const h = headCenterX(stage)
    expect(h.x1).toBeGreaterThan(h.x0)
    expect(Math.abs(h.cx - axisX)).toBeLessThanOrEqual(14)
  })

  it('人物不出画：头部与躯干都在画布内（双腿按半身近景允许跑出画底）', () => {
    const b = actorBox(stage)
    expect(b.y0).toBeGreaterThan(0)
    // 横向：both_hands 手臂张到边上也不许出界
    expect(b.x0).toBeGreaterThanOrEqual(0)
    expect(b.x1).toBeLessThanOrEqual(b.w - 1)
    // 头部横向必须留边（头贴边 = 构图崩了）
    const h = headCenterX(stage)
    expect(h.x0).toBeGreaterThan(0)
    expect(h.x1).toBeLessThan(stage.w - 1)
  })

  it('可见身高（头顶→台沿）占画高 35%~62%（太小看不清表情，太大挤掉卷面）', () => {
    const b = actorBox(stage)
    const slabY0 = stage.geo['slab']![1]!
    const ratio = (slabY0 - b.y0) / stage.h
    expect(ratio).toBeGreaterThan(0.35)
    expect(ratio).toBeLessThan(0.62)
  })

  it('六种表情都能画且头顶高度不漂（mood 不许改人的位置）', () => {
    const base = actorBox(stage).y0
    for (const mood of ['neutral', 'happy', 'puzzled', 'encouraging', 'emphatic', 'teach']) {
      const b = actorBox(stage, mood)
      expect(b.n, mood).toBeGreaterThan(0)
      expect(Math.abs(b.y0 - base), mood).toBeLessThanOrEqual(14)
    }
  })

  it(`双手落在 ${Math.round(handY(stage))}px，压在台沿条里（「双手搭案沿」不是假的）`, () => {
    const [, slabY0, , slabY1] = stage.geo['slab']!
    const hy = handY(stage)
    expect(hy).toBeGreaterThan(slabY0 - 24)
    expect(hy).toBeLessThan(slabY1 + 8)
  })
})

describe.each([
  ['竖版', PORTRAIT_STAGE],
  ['横版', LANDSCAPE_STAGE],
] as const)('%s：版面矩形', (_name, stage) => {
  const { w, h, geo } = stage

  it('每个矩形都在画布内且宽高为正', () => {
    for (const [k, r] of Object.entries(geo) as Array<[string, number[]]>) {
      const [x0, y0, x1, y1] = r as [number, number, number, number]
      expect(r.length, k).toBe(4)
      expect(x0, k).toBeGreaterThanOrEqual(0)
      expect(y0, k).toBeGreaterThanOrEqual(0)
      expect(x1, k).toBeLessThanOrEqual(w)
      expect(y1, k).toBeLessThanOrEqual(h)
      expect(x1 - x0, k).toBeGreaterThan(0)
      expect(y1 - y0, k).toBeGreaterThan(0)
    }
  })

  it('卷面文字区 / 原文行都在卷面纸内（文字不许写到卷外）', () => {
    const paper = geo['paper']!
    for (const k of ['ktext', 'quote'] as const) {
      const r = geo[k]
      expect(r[0]!, k).toBeGreaterThanOrEqual(paper[0]!)
      expect(r[1]!, k).toBeGreaterThanOrEqual(paper[1]!)
      expect(r[2]!, k).toBeLessThanOrEqual(paper[2]!)
      expect(r[3]!, k).toBeLessThanOrEqual(paper[3]!)
    }
  })

  it('匾文区在匾板内，匾垂在顶梁之下', () => {
    const [px0, py0, px1, py1] = geo['plaque']!
    const [tx0, ty0, tx1, ty1] = geo['ptext']!
    expect(tx0).toBeGreaterThanOrEqual(px0)
    expect(ty0).toBeGreaterThanOrEqual(py0)
    expect(tx1).toBeLessThanOrEqual(px1)
    expect(ty1).toBeLessThanOrEqual(py1)
    // 匾从梁上挂下来：上沿可以在梁内（横版就是这样，上沿压梁），但下沿必须落出梁外
    expect(py0).toBeGreaterThanOrEqual(geo['beam']![1]!)
    expect(py1).toBeGreaterThan(geo['beam']![3]!)
  })

  it('案面顺序：护墙板 → 台沿条 → 卷面（卷面接在案沿下沿，不悬空）', () => {
    const [, panelY0, , panelY1] = geo['panel']!
    const [slabX0, slabY0, slabX1, slabY1] = geo['slab']!
    expect(panelY0).toBeLessThan(panelY1)
    expect(slabY0).toBeGreaterThanOrEqual(panelY1)
    expect(slabX0).toBe(0)
    expect(slabX1).toBe(w)
    // 卷面上沿接在台沿条里（竖版正好齐案沿下沿 1630，横版齐 728）
    const paperY0 = geo['paper']![1]!
    expect(paperY0).toBeGreaterThanOrEqual(slabY0)
    expect(paperY0).toBeLessThanOrEqual(slabY1 + 8)
  })

  it('道具（醒木 / 折扇 / 接触影）都在画布内', () => {
    const rects: Array<[string, readonly number[]]> = [
      ['contact', stage.props.contact], ['gavelShadow', stage.props.gavelShadow],
      ['gavel', stage.props.gavel], ['gavelTop', stage.props.gavelTop],
      ['fanShadow', stage.props.fanShadow], ['fanHandle', stage.props.fanHandle],
      ['fanPaper', stage.props.fanPaper],
    ]
    for (const [k, r] of rects) {
      const [x0, y0, x1, y1] = r as [number, number, number, number]
      expect(x0, k).toBeGreaterThanOrEqual(0)
      expect(y0, k).toBeGreaterThanOrEqual(0)
      expect(x1, k).toBeLessThanOrEqual(w)
      expect(y1, k).toBeLessThanOrEqual(h)
      expect(x1, k).toBeGreaterThan(x0)
      expect(y1, k).toBeGreaterThan(y0)
    }
    const rib = stage.props.fanRib
    expect(rib.from).toBeLessThan(rib.to)
    expect(rib.to).toBeLessThan(w)
  })

  it('卷面横向留边对称（横版卷面横铺时最容易一边宽一边窄）', () => {
    const [px0, , px1] = geo['paper']!
    expect(Math.abs(px0 - (w - px1))).toBeLessThanOrEqual(8)
  })
})

describe('舞台可画：两套几何都能真正画出来', () => {
  // 墙与地面由 scenes.prerenderBg 另外画（不在 drawStageBack 里），所以背层
  // 覆盖率高≠对；改为直查「该实的地方实了」：
  //   back  —— 匾面中心必须不透明，顶梁必须不透明；
  //   front —— 卷面中心必须不透明（书卷压在台前），案沿条必须不透明。
  const alphaAt = (stage: Stage, fn: typeof drawStageBack, x: number, y: number) => {
    const canvas = createCanvas(stage.w, stage.h)
    const ctx = canvas.getContext('2d')
    fn(new scenes.DrawScaled(createPilDraw(ctx), 1),
      rig.SCENE as Record<string, RGB>, rig.hexc('#8C6239'), stage)
    return ctx.getImageData(Math.round(x), Math.round(y), 1, 1).data[3]!
  }
  const center = (r: readonly number[]) => [(r[0]! + r[2]!) / 2, (r[1]! + r[3]!) / 2] as const

  it.each([
    ['竖版', PORTRAIT_STAGE],
    ['横版', LANDSCAPE_STAGE],
  ] as const)('%s 背层：匾面与顶梁都画出来了', (_name, stage) => {
    const [pcx, pcy] = center(stage.geo['plaque']!)
    expect(alphaAt(stage, drawStageBack, pcx, pcy)).toBeGreaterThan(200)
    const [bx, by] = center(stage.geo['beam']!)
    expect(alphaAt(stage, drawStageBack, bx, by)).toBeGreaterThan(200)
  })

  it.each([
    ['竖版', PORTRAIT_STAGE],
    ['横版', LANDSCAPE_STAGE],
  ] as const)('%s 前层：卷面与台沿条都画出来了', (_name, stage) => {
    const [papx, papy] = center(stage.geo['paper']!)
    expect(alphaAt(stage, drawStageFront, papx, papy)).toBeGreaterThan(200)
    const [sx, sy] = center(stage.geo['slab']!)
    expect(alphaAt(stage, drawStageFront, sx, sy)).toBeGreaterThan(200)
  })

  it.each([
    ['竖版', PORTRAIT_STAGE],
    ['横版', LANDSCAPE_STAGE],
  ] as const)('%s 两层都有实质像素（空画布 = 几何对但没接线）', (_name, stage) => {
    for (const fn of [drawStageBack, drawStageFront]) {
      const canvas = createCanvas(stage.w, stage.h)
      const ctx = canvas.getContext('2d')
      fn(new scenes.DrawScaled(createPilDraw(ctx), 1),
        rig.SCENE as Record<string, RGB>, rig.hexc('#8C6239'), stage)
      const px = ctx.getImageData(0, 0, stage.w, stage.h).data
      let opaque = 0
      for (let i = 3; i < px.length; i += 4) if (px[i]! > 0) opaque++
      expect(opaque / (stage.w * stage.h)).toBeGreaterThan(0.05)
    }
  })
})


// 背景落版门：横版曾经拿竖版画布当基底，「推/摇镜头把基底放大」的幕蒙混过关，
// 第一个 static 幕才抛 Image to composite must have same dimensions。这组断言把
// 「背景就是画幅尺寸」和「道具真的画进去了」两件事钉死。
describe('背景落版（bgLayoutFor）', () => {
  it('竖版返回 undefined（原样落版，逐像素不变的唯一保证）', () => {
    expect(bgLayoutFor(PORTRAIT_STAGE)).toBeUndefined()
  })

  it('横版：不缩放、横向居中、窗口覆盖 13 幕道具带并集（不裁切）', () => {
    const l = bgLayoutFor(LANDSCAPE_STAGE)!
    expect(l.w).toBe(LANDSCAPE_STAGE.w)
    expect(l.h).toBe(LANDSCAPE_STAGE.h)
    expect(l.scale ?? 1).toBe(1)                        // 不变形：缩放必须恰好 1
    expect(l.dx).toBe((LANDSCAPE_STAGE.w - rig.W) / 2)   // 两侧渐变等宽
    const top = -(l.dy ?? 0)
    expect(top).toBeLessThanOrEqual(600)                       // 道具带上界
    expect(top + LANDSCAPE_STAGE.h).toBeGreaterThanOrEqual(1600) // 道具带下界
  })

  it('真渲染出来的背景就是画幅尺寸（差一像素就到了 composite 才炸）', async () => {
    for (const stage of [PORTRAIT_STAGE, LANDSCAPE_STAGE]) {
      const bg = await (await scenes.prerenderBg(
        { identity: '#8C6239' }, { scene: ['board_timetable'] }, bgLayoutFor(stage)))
        .ensureAlpha().raw().toBuffer({ resolveWithObject: true })
      expect([bg.info.width, bg.info.height]).toEqual([stage.w, stage.h])
    }
  })

  it('横版背景里道具真的画进去了（与纯渐变有差异，不是空墙）', async () => {
    const render = async (scene: readonly string[]) => (await (await scenes.prerenderBg(
      { identity: '#8C6239' }, { scene }, bgLayoutFor(LANDSCAPE_STAGE)))
      .ensureAlpha().raw().toBuffer({ resolveWithObject: true })).data
    const withProps = await render(['board_timetable'])
    const plain = await render([])
    let diff = 0
    for (let i = 0; i < withProps.length; i += 4) {
      if (Math.abs(withProps[i]! - plain[i]!) > 6) diff++
    }
    expect(diff).toBeGreaterThan(0.01 * LANDSCAPE_STAGE.w * LANDSCAPE_STAGE.h)
  })
})