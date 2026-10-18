// rig.test.ts — 人物 rig 几何探针反向验证（verify_rig.py 的 vitest 移植）。
//
// 几何判据跑在 rig 上（28 项全绿），按其原公式：
// A1 颈肩缝（判定窗精确落在颏线下 chin+0.005H…0.10H——正常解剖凹角不算缺陷）、
// A2 胯块（取样 x 用 0.80·torso_hw，绝不用 hip_hw：判据 ∌ 被测字段）、
// B1 手臂可读（剪影 + 袖色阶差）、B2 头身重叠、
// C1/C2 五官可见（抬臂姿态族数五官自身颜色，不数衣色）、
// D1/D2/D3 下颌（可见肤色宽 / face_profile 单调 / 斜率内凹）、
// E1/E2 胡须（八字胡在场、不下脖子）。
//
// 探针自证（纪律 2）：在 A1 判定窗里**人为凿洞** → A1 必须 FAIL；
// 幂等（不变量⑦）：同参数两渲 PNG 逐字节一致。
// 第 0 条好数据放行：三名典型人设（心形/方脸/大胡子）全探针通过。
//
// fixture：personas/personas.json（28 人班底，经 data.personas()）。
import { createCanvas } from "@napi-rs/canvas"
import sharp from "sharp"
import { describe, expect, it } from "vitest"

import { personas } from "../src/data.js"
import * as rig from "../src/rig.js"
import { SS } from "../src/scenes.js"
import { createPilDraw } from "../src/imaging/pildraw.js"

const ALPHA_THR = 24
const HOLE_MIN = 3
const JAW_OPEN_MIN = 0.30
const RAISED_POSES = ["wave", "ciao_wave", "thumbs_up", "hand_shoot", "point", "both_hands"] as const
const W = rig.W
const H = rig.H

const PERSONAS = Object.values(personas())

/** int() = 向零截断（探针几何窗口一律整数像素）。 */
const int = Math.trunc

/** 渲一张人物层（RGBA，1080×1920，与成片坐标一致）——qa_shape 同款口径。
 * napi canvas 起始全透明（等价 PIL Image.new RGBA (0,0,0,0)）；
 * SS 超采样画布 → 2×2 块平均（PIL BOX 下采样的整数倍精确等价）→ 语义分辨率探针层。 */
interface Layer {
  /** 语义分辨率 RGBA（W×H×4）——幂等判据的编码原料。 */
  rgba: Buffer
  /** alpha 通道（W×H）——剪影空洞探针读它。 */
  mask: Uint8Array
  /** RGB 三通道平铺（W×H×3）——色阶/对比探针读它。 */
  rgb: Int32Array
}

function renderPersona(
  p: rig.Persona,
  opts: { mood?: string; openness?: number; blink?: boolean; pose?: Record<string, any> } = {},
): Layer {
  const canvas = createCanvas(W * SS, H * SS)
  const ctx = canvas.getContext("2d")
  const ctxDict: rig.RigCtx = {
    scale: 1.0, xoff: 0.0, yoff: 0.0, squash: 0.0, xscale: 1.0,
    head_dx: 0, head_dy: 0, brow_lift_extra: 0, pose: { ...(opts.pose ?? {}) },
    openness: opts.openness ?? 0.0, blink: opts.blink ?? false, mood: opts.mood ?? "neutral",
    ss: SS,
  }
  rig.drawCharacter(canvas, createPilDraw(ctx), p, 0.0, ctxDict)
  const src = ctx.getImageData(0, 0, W * SS, H * SS).data
  const rgba = Buffer.alloc(W * H * 4)
  const mask = new Uint8Array(W * H)
  const rgb = new Int32Array(W * H * 3)
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const o = (y * W + x) * 4
      const s00 = ((2 * y) * W * SS + 2 * x) * 4
      const s10 = s00 + W * SS * 4   // 下一行
      const s01 = s00 + 4           // 右一列
      const s11 = s10 + 4
      for (let c = 0; c < 4; c++) {
        rgba[o + c] = Math.round((src[s00 + c]! + src[s01 + c]! + src[s10 + c]! + src[s11 + c]!) / 4)
      }
      mask[y * W + x] = rgba[o + 3]!
      rgb[(y * W + x) * 3] = rgba[o]!
      rgb[(y * W + x) * 3 + 1] = rgba[o + 1]!
      rgb[(y * W + x) * 3 + 2] = rgba[o + 2]!
    }
  }
  return { rgba, mask, rgb }
}

/** 逐行找「夹在实心像素之间的透明游程」＝剪影空洞（轮廓外背景不算）。
 * skipCenter：胯部两腿之间是合法空洞，不排除会全员误判。 */
function holesInBand(
  mask: Uint8Array,
  y0: number,
  y1: number,
  xlo: number,
  xhi: number,
  skipCenter?: readonly [number, number],
): [number, number, number][] {
  const out: [number, number, number][] = []
  const yHi = Math.min(H, y1)
  for (let y = Math.max(0, y0); y < yHi; y++) {
    const row = y * W
    const lo = Math.max(0, xlo)
    const hi = Math.min(W - 1, xhi)
    let segs: number[][]
    if (skipCenter) {
      const [cx, r] = skipCenter
      const segL: number[] = []
      for (let i = lo; i < Math.min(hi, cx - r); i++) if (mask[row + i]! <= ALPHA_THR) segL.push(i)
      const segR: number[] = []
      for (let i = Math.max(lo, cx + r); i < hi; i++) if (mask[row + i]! <= ALPHA_THR) segR.push(i)
      segs = [segL, segR]
    } else {
      const segL: number[] = []
      for (let i = lo; i < hi; i++) if (mask[row + i]! <= ALPHA_THR) segL.push(i)
      segs = [segL, segL]  // Python 里 seg_r = seg_l 同表遍历两次——按原样保留
    }
    for (const seg of segs) {
      let run: number[] = []
      for (const x of [...seg, NaN]) {
        if (!Number.isNaN(x) && (run.length === 0 || x === run[run.length - 1]! + 1)) {
          run.push(x)
          continue
        }
        if (run.length >= HOLE_MIN) {
          const a = run[0]!
          const b = run[run.length - 1]!
          if (a - 1 >= 0 && mask[row + a - 1]! > ALPHA_THR && b + 1 < W && mask[row + b + 1]! > ALPHA_THR) {
            out.push([a, b, y])
          }
        }
        run = []
      }
    }
  }
  return out
}

/** 窗口 [y0,y1)×[x0,x1) 内与 ref 三通道极差 ≤ tol 的像素数（Python 切片自带钳制）。 */
function countNear(
  L: Layer,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  ref: readonly number[],
  tol = 18,
): number {
  const xa = Math.max(0, x0)
  const xb = Math.min(W, x1)
  const ya = Math.max(0, y0)
  const yb = Math.min(H, y1)
  let n = 0
  for (let y = ya; y < yb; y++) {
    for (let x = xa; x < xb; x++) {
      const o = (y * W + x) * 3
      if (Math.max(
        Math.abs(L.rgb[o]! - ref[0]!), Math.abs(L.rgb[o + 1]! - ref[1]!), Math.abs(L.rgb[o + 2]! - ref[2]!),
      ) <= tol) n++
    }
  }
  return n
}

/** 窗口内与 ref 的最大单通道极差（B1 袖色阶差）。 */
function maxDiff(
  L: Layer,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  ref: readonly number[],
): number {
  const xa = Math.max(0, x0)
  const xb = Math.min(W, x1)
  const ya = Math.max(0, y0)
  const yb = Math.min(H, y1)
  let m = 0
  for (let y = ya; y < yb; y++) {
    for (let x = xa; x < xb; x++) {
      const o = (y * W + x) * 3
      m = Math.max(m,
        Math.abs(L.rgb[o]! - ref[0]!), Math.abs(L.rgb[o + 1]! - ref[1]!), Math.abs(L.rgb[o + 2]! - ref[2]!))
    }
  }
  return m
}

function faceWindows(G: rig.FaceGeo) {
  const cx = G.cx
  const mw = G.WH * 0.26
  const mh = G.H * 0.115
  const eyes = [
    [cx - G.eye_dx - G.scl_rx * 1.15, G.eye_y - G.scl_ry * 1.25,
      cx - G.eye_dx + G.scl_rx * 1.15, G.eye_y + G.scl_ry * 1.25],
    [cx + G.eye_dx - G.scl_rx * 1.15, G.eye_y - G.scl_ry * 1.25,
      cx + G.eye_dx + G.scl_rx * 1.15, G.eye_y + G.scl_ry * 1.25],
  ] as const
  return { mouth: [cx - mw, G.mouth_y - mh, cx + mw, G.mouth_y + mh] as const, eyes }
}

function probeA1(mask: Uint8Array, G: rig.FaceGeo): number {
  const band = holesInBand(mask,
    int(G.chin + G.H * 0.005), int(G.chin + G.H * 0.10),
    int(G.cx - G.sh_out * 1.15), int(G.cx + G.sh_out * 1.15),
    [int(G.cx), int(G.H * 0.115)])
  return band.reduce((m, [a, b]) => Math.max(m, b - a + 1), 0)
}

/** 一名人物的全部探针（qa_shape 公式）。 */
function probePerson(p: rig.Persona): [boolean, string][] {
  const res: [boolean, string][] = []
  const face = p["movement"]["face"]
  const G = rig.faceGeo(face)
  const hasBeard = (p["accessories"] ?? []).some((a: any) => a["code"] === "beard")
  const tunic = (p["outfit"] ?? {})["kind"] === "tunic"
  const torsoBot = G.torso_top + G.torso_h * (tunic ? 1.30 : 1.0)
  const shY = G.torso_top + G.sh_dy

  const base = renderPersona(p, { openness: 0.0 })

  // A1 颈肩缝
  const worst = probeA1(base.mask, G)
  res.push([worst <= HOLE_MIN, `${p["id"]} A1 颈肩缝最宽 ${worst}px（须 ≤${HOLE_MIN}）`])

  // A2 胯块：上色 + 腿根不断
  const yProbe = int(torsoBot + G.H * 0.12)
  const xProbe = int(G.cx + G.torso_hw * 0.80)
  const hit = countNear(base, xProbe - 3, yProbe - 3, xProbe + 3, yProbe + 3,
    rig.hexc(p["palette"]["outfitBottom"]), 40)
  const hipBand = holesInBand(base.mask,
    int(torsoBot - G.H * 0.16), int(torsoBot + G.H * 0.10),
    int(G.cx - G.torso_hw * 0.72), int(G.cx + G.torso_hw * 0.72),
    [int(G.cx), int(G.leg_cx - G.leg_w * 0.35)])
  const worstHip = hipBand.reduce((m, [a, b]) => Math.max(m, b - a + 1), 0)
  res.push([hit >= 25 && worstHip <= HOLE_MIN,
    `${p["id"]} A2 胯块 ${hit}/36px 且腿根缝 ${worstHip}px（须 ≥25 且 ≤${HOLE_MIN}）`])

  // B1 手臂可读
  const restA1 = G.arm_rest[0]
  const armOuter = G.sh_x + Math.sin(restA1 * Math.PI / 180) * G.up_len * 0.85 + G.arm_w * 0.5
  const protr = armOuter - G.torso_hw
  const yS = int(shY + G.up_len * 0.55)
  const xS = int(G.cx + G.torso_hw + G.arm_w * 0.14)
  const tone = maxDiff(base, xS - 3, yS - 5, xS + 3, yS + 5, rig.hexc(p["palette"]["outfitTop"]))
  res.push([protr >= G.arm_w * 0.22 && tone >= 10,
    `${p["id"]} B1 手臂探出 ${protr.toFixed(1)}px、袖色阶差 ${tone}（须 ≥${(G.arm_w * 0.22).toFixed(1)}px 且 ≥10）`])

  // B2 头身重叠
  const overlap = shY - (G.chin - G.H * 0.02)
  res.push([overlap >= G.H * 0.02,
    `${p["id"]} B2 下颌压过肩线 ${overlap.toFixed(1)}px（须 ≥${(G.H * 0.02).toFixed(1)}）`])

  // D1 下颌开口（大胡子合法盖住，跳过）
  const yJaw = int(G.hy + G.ry * 0.90)
  const xa = Math.max(0, int(G.cx - G.rx * 1.3))
  const xb = int(G.cx + G.rx * 1.3)
  const skin = rig.hexc(p["palette"]["skin"])
  let iMin = -1
  let iMax = -1
  for (let x = xa; x < Math.min(W, xb); x++) {
    const o = (yJaw * W + x) * 3
    const isSkin = Math.max(
      Math.abs(base.rgb[o]! - skin[0]!), Math.abs(base.rgb[o + 1]! - skin[1]!),
      Math.abs(base.rgb[o + 2]! - skin[2]!)) <= 26
    if (isSkin) {
      if (iMin < 0) iMin = x
      iMax = x
    }
  }
  const halfJaw = iMin >= 0 ? (iMax - iMin) / 2 / G.rx : 0.0
  res.push([hasBeard || halfJaw >= JAW_OPEN_MIN,
    `${p["id"]} D1 可见肤色半宽 ${halfJaw.toFixed(2)}·rx`
    + (hasBeard ? "（skip：大胡子合法盖住）" : `（须 ≥${JAW_OPEN_MIN}）`)])

  // D2/D3 下颌单调与内凹（查几何函数，免疫发量遮挡）
  let worstGrow = 0.0
  let prev = rig.faceProfile(face, 0.0)
  for (let i = 1; i <= 60; i++) {
    const cur = rig.faceProfile(face, i / 60.0)
    worstGrow = Math.max(worstGrow, cur - prev)
    prev = cur
  }
  res.push([worstGrow <= 1e-6, `${p["id"]} D2 face_profile 回涨 ${worstGrow.toFixed(4)}（须 0）`])
  const vEnd = rig.JAW[face as keyof typeof rig.JAW]?.y1 ?? 1.0
  const vals = Array.from({ length: 61 }, (_, i) => rig.faceProfile(face, (vEnd * i) / 60.0))
  let prevD: number | null = null
  let worstCurve = 0.0
  for (let i = 0; i < vals.length - 1; i++) {
    const dcur = vals[i + 1]! - vals[i]!
    if (prevD !== null) worstCurve = Math.max(worstCurve, dcur - prevD)
    prevD = dcur
  }
  res.push([worstCurve <= 1e-9, `${p["id"]} D3 斜率增量 ${worstCurve.toFixed(4)}（须 ≤0）`])

  // E1/E2 胡须
  if (hasBeard) {
    const beardC = rig.mix(rig.hexc(p["palette"]["hair"]), rig.hexc(p["palette"]["skin"]), 0.25)
    const isBeard = (y: number): number => countNear(base,
      int(G.cx - G.rx * 1.3), int(y) - 2, int(G.cx + G.rx * 1.3), int(y) + 3, beardC, 20)
    const below = isBeard(G.chin + G.ry * 0.10)
    const above = isBeard(G.mouth_y - G.ry * 0.15)
    res.push([below === 0, `${p["id"]} E1 颏线下胡须色 ${below}px（须 0——不下脖子）`])
    res.push([above >= 25, `${p["id"]} E2 嘴上八字胡 ${above}px（须 ≥25）`])
  }
  return res
}

function pick(pred: (p: rig.Persona) => boolean, what: string): rig.Persona {
  for (const p of PERSONAS) if (pred(p)) return p
  throw new Error(`夹具里找不到${what}`)
}

const pHeart = () => pick(
  (p) => p["movement"]["face"] === "heart"
    && !(p["accessories"] ?? []).some((a: any) => a["code"] === "beard"), "心形脸")
const pBeard = () => pick(
  (p) => (p["accessories"] ?? []).some((a: any) => a["code"] === "beard"), "大胡子")
const pSquare = () => pick((p) => p["movement"]["face"] === "square", "方脸")

describe("rig 几何探针（verify_rig.py 移植）", () => {
  it("第 0 条好数据放行：三名典型人设全探针（心形/方脸/大胡子）", { timeout: 120_000 }, () => {
    const rows: [boolean, string][] = []
    for (const p of [pHeart(), pBeard(), pSquare()]) rows.push(...probePerson(p))
    const fails = rows.filter(([ok]) => !ok).map(([, msg]) => msg)
    expect(fails, fails.join("\n")).toEqual([])
  })

  it("C1/C2 抬臂姿态族五官可见（数五官自身颜色，不数衣色）", { timeout: 120_000 }, () => {
    const ph = pHeart()
    const G = rig.faceGeo(ph["movement"]["face"])
    const fw = faceWindows(G)
    const [mx0, my0, mx1, my1] = fw.mouth.map(int) as [number, number, number, number]
    const mouthPx = Math.max(0.16 * (mx1 - mx0) * (my1 - my0), 24)
    const sclPx = 0.16 * (fw.eyes[0][2] - fw.eyes[0][0]) * (fw.eyes[0][3] - fw.eyes[0][1])
    let worstM: [string, number] | null = null
    let worstE: [string, number] | null = null
    for (const code of RAISED_POSES) {
      const pose = { ...rig.poseFor(code, 0.5, 0.0, ph) }
      const lay = renderPersona(ph, { mood: "happy", openness: 0.9, pose })
      const mCnt = Math.max(
        countNear(lay, mx0, my0, mx1, my1, rig.THEME.mouth),
        countNear(lay, mx0, my0, mx1, my1, rig.THEME.tongue),
        countNear(lay, mx0, my0, mx1, my1, rig.THEME.ink),
      )
      const eCnt = fw.eyes.reduce(
        (s, [ex0, ey0, ex1, ey1]) => s + countNear(lay, int(ex0), int(ey0), int(ex1), int(ey1), [255, 255, 255], 12),
        0)
      if (mCnt < mouthPx && (worstM === null || mCnt / mouthPx < worstM[1])) {
        worstM = [code, mCnt / mouthPx]
      }
      if (eCnt < sclPx && (worstE === null || eCnt / sclPx < worstE[1])) {
        worstE = [code, eCnt / sclPx]
      }
    }
    if (worstM !== null) {
      expect.fail(`C1 抬臂姿态族嘴部可见：最差 ${worstM[0]} ${(worstM[1] * 100).toFixed(0)}% ← 遮嘴`)
    }
    if (worstE !== null) {
      expect.fail(`C2 抬臂姿态族眼部可见：最差 ${worstE[0]} ${(worstE[1] * 100).toFixed(0)}% ← 遮眼`)
    }
  })

  it("探针自证：A1 判定窗凿 12px 洞 → A1 必须 FAIL（探针不瞎）", { timeout: 120_000 }, () => {
    const ph = pHeart()
    const G = rig.faceGeo(ph["movement"]["face"])
    const base = renderPersona(ph)
    const damaged = Uint8Array.from(base.mask)
    const holeY0 = int(G.chin + G.H * 0.01)
    const holeY1 = int(G.chin + G.H * 0.035)
    const holeX0 = int(G.cx + G.sh_out * 0.4)
    const holeX1 = holeX0 + 12
    for (let y = holeY0; y < holeY1; y++) {
      for (let x = holeX0; x < holeX1; x++) damaged[y * W + x] = 0
    }
    const worst = probeA1(damaged, G)
    expect(worst >= HOLE_MIN, `A1 报 ${worst}px（须 ≥${HOLE_MIN}——探针不瞎）`).toBe(true)
  })

  it("幂等：同参数两渲 PNG 逐字节一致（不变量⑦）", { timeout: 120_000 }, async () => {
    const ph = pHeart()
    const a = renderPersona(ph, { pose: { ...rig.poseFor("wave", 0.5, 0.0, ph) } })
    const b = renderPersona(ph, { pose: { ...rig.poseFor("wave", 0.5, 0.0, ph) } })
    expect(a.rgba.equals(b.rgba)).toBe(true)
    const enc = (L: Layer) => sharp(L.rgba, { raw: { width: W, height: H, channels: 4 } })
      .png().toBuffer()
    expect((await enc(a)).equals(await enc(b))).toBe(true)
  })
})
