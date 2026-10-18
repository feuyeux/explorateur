// draw.ts — op-spec 场景绘制（scenes.py DrawScaled/SS 超采样语义的 TS 移植，
// @napi-rs/canvas 承载）。spike 2 产物，P4 时 scenes.ts 在此面上铺开注册表。
//
// 与 Python 参照（migration/spike2_scenes_ref.py）共享同一份 op-spec JSON：
// 坐标为 1× 语义坐标（1080×1920），SS 超采样绘制后 LANCZOS 缩回。
//
// 语义对齐要点：
// - setTransform(SS,0,0,SS,0,0) 之后所有坐标/线宽按语义单位书写，device 像素
//   自动 ×SS——等价 Python 的「坐标全乘 k」写法（lineWidth 随变换缩放）。
// - PIL 与 canvas 同一角度约定：0° = 三点钟方向，y 向下时角度顺时针增大。
// - PIL 的 box 是闭区间（含右/下边界）；canvas 用 (x1-x0+1) 尺寸补齐这一格差，
//   画布为不透明底、无 AA 缝。
// - gradient 按 Python 逐行带状着色（每语义行一个 round 后的纯色，band 对齐
//   device 整数行），round 取 banker's rounding（Python round 的口径）。
// - 栅格化器不同（Pillow vs Skia），边缘 AA 必然不同——比对走「结构与几何」
//   （降采样灰度均值/分位差），不比像素。这是机桶纪律，不是缺陷。
import { createCanvas, type SKRSContext2D } from "@napi-rs/canvas"
import sharp from "sharp"

export type RGB = readonly [number, number, number]
export interface BaseOp {
  op: string
}
export interface GradientOp extends BaseOp {
  op: "gradient"
  box: readonly [number, number, number, number]
  top: RGB
  bottom: RGB
}
export interface BoxOp extends BaseOp {
  op: "rectangle" | "rounded_rectangle" | "ellipse" | "arc" | "pieslice" | "chord"
  box: readonly [number, number, number, number]
  fill?: RGB
  outline?: RGB
  width?: number
  start?: number
  end?: number
  radius?: number
}
export interface PolylineOp extends BaseOp {
  op: "line"
  pts: readonly (readonly [number, number])[]
  fill: RGB
  width?: number
  joint?: "curve"
}
export interface PolygonOp extends BaseOp {
  op: "polygon"
  pts: readonly (readonly [number, number])[]
  fill: RGB
}
export type DrawOp = GradientOp | BoxOp | PolylineOp | PolygonOp

export interface DrawSpec {
  w: number
  h: number
  ss: number
  ops: readonly DrawOp[]
}

const css = (c: RGB): string => `rgb(${c[0]},${c[1]},${c[2]})`

/** Python round()：四舍五入取偶（ties-to-even）。 */
function roundHalfEven(x: number): number {
  const f = Math.floor(x)
  const diff = x - f
  if (diff > 0.5) return f + 1
  if (diff < 0.5) return f
  return f % 2 === 0 ? f : f + 1
}

const rad = (deg: number): number => (deg * Math.PI) / 180

/** roundRect 兜底：老版 Skia 无 ctx.roundRect 时用 arcTo 拼。 */
function pathRoundRect(
  ctx: SKRSContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  const rr = Math.max(0, Math.min(r, w / 2, h / 2))
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

function strokeRoundRect(
  ctx: SKRSContext2D,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  r: number,
): void {
  const w = x1 - x0 + 1
  const h = y1 - y0 + 1
  ctx.beginPath()
  if (typeof (ctx as SKRSContext2D & { roundRect?: unknown }).roundRect === "function") {
    ctx.roundRect(x0, y0, w, h, r)
  } else {
    pathRoundRect(ctx, x0, y0, w, h, r)
  }
  ctx.stroke()
}

function applyOp(ctx: SKRSContext2D, op: DrawOp): void {
  switch (op.op) {
    case "gradient": {
      const [x0, y0, x1, y1] = op.box
      const span = Math.max(1, y1 - y0 - 1)
      // 每语义行一个纯色带（device 整数行对齐，带间无缝）
      for (let y = y0; y < y1; y++) {
        const t = (y - y0) / span
        const [tr, tg, tb] = op.top
        const [br, bg, bb] = op.bottom
        const c: RGB = [
          roundHalfEven(tr + (br - tr) * t),
          roundHalfEven(tg + (bg - tg) * t),
          roundHalfEven(tb + (bb - tb) * t),
        ]
        ctx.fillStyle = css(c)
        ctx.fillRect(x0, y, x1 - x0 + 1, 1)
      }
      return
    }
    case "rectangle": {
      const [x0, y0, x1, y1] = op.box
      const w = x1 - x0 + 1
      const h = y1 - y0 + 1
      if (op.fill) {
        ctx.fillStyle = css(op.fill)
        ctx.fillRect(x0, y0, w, h)
      }
      if (op.outline) {
        // PIL outline 以 box 内缩 width 像素描边（外沿含 box 边界）
        const lw = (op.width ?? 1)
        ctx.lineWidth = lw
        ctx.strokeStyle = css(op.outline)
        const inset = lw / 2
        ctx.strokeRect(x0 + inset, y0 + inset, w - lw, h - lw)
      }
      return
    }
    case "rounded_rectangle": {
      const [x0, y0, x1, y1] = op.box
      const w = x1 - x0 + 1
      const h = y1 - y0 + 1
      const r = op.radius ?? 0
      const lw = op.width ?? 1
      if (op.fill) {
        ctx.fillStyle = css(op.fill)
        ctx.beginPath()
        if (typeof (ctx as SKRSContext2D & { roundRect?: unknown }).roundRect === "function") {
          ctx.roundRect(x0, y0, w, h, r)
        } else {
          pathRoundRect(ctx, x0, y0, w, h, r)
        }
        ctx.fill()
      }
      if (op.outline) {
        ctx.lineWidth = lw
        ctx.strokeStyle = css(op.outline)
        // PIL 描边外沿含 box 边界：等效 box 内缩 lw/2 再描
        const inset = lw / 2
        const wr = Math.max(0, r - inset)
        ctx.beginPath()
        if (typeof (ctx as SKRSContext2D & { roundRect?: unknown }).roundRect === "function") {
          ctx.roundRect(x0 + inset, y0 + inset, w - lw, h - lw, wr)
        } else {
          pathRoundRect(ctx, x0 + inset, y0 + inset, w - lw, h - lw, wr)
        }
        ctx.stroke()
      }
      return
    }
    case "ellipse": {
      const [x0, y0, x1, y1] = op.box
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const rx = (x1 - x0 + 1) / 2
      const ry = (y1 - y0 + 1) / 2
      const lw = op.width ?? 1
      if (op.fill) {
        ctx.beginPath()
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2)
        ctx.fillStyle = css(op.fill)
        ctx.fill()
      }
      if (op.outline) {
        // PIL 的 outline 从 box 内接椭圆向内加粗；canvas 居中描边 → 路径内缩 lw/2
        ctx.beginPath()
        ctx.ellipse(cx, cy, rx - lw / 2, ry - lw / 2, 0, 0, Math.PI * 2)
        ctx.lineWidth = lw
        ctx.strokeStyle = css(op.outline)
        ctx.stroke()
      }
      return
    }
    case "line": {
      const [first, ...rest] = op.pts
      if (!first) return
      ctx.beginPath()
      ctx.moveTo(first[0], first[1])
      for (const p of rest) ctx.lineTo(p[0], p[1])
      ctx.lineWidth = Math.max(1, op.width ?? 1)
      ctx.strokeStyle = css(op.fill)
      ctx.lineCap = "round"
      ctx.lineJoin = op.joint === "curve" ? "round" : "miter"
      ctx.stroke()
      return
    }
    case "arc": {
      const [x0, y0, x1, y1] = op.box
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const lw = Math.max(1, op.width ?? 1)
      // PIL 的 arc 带从 box 内接椭圆向内加粗；canvas 居中描边 → 路径内缩 lw/2
      // （实测探针：box [0,0,200,200] w=20 时外沿触 y=0，带全在 box 内）
      const rx = (x1 - x0 + 1) / 2 - lw / 2
      const ry = (y1 - y0 + 1) / 2 - lw / 2
      ctx.beginPath()
      ctx.ellipse(cx, cy, rx, ry, 0, rad(op.start ?? 0), rad(op.end ?? 360))
      ctx.lineWidth = lw
      ctx.strokeStyle = css(op.fill ?? [0, 0, 0])
      ctx.lineCap = "butt"
      ctx.stroke()
      return
    }
    case "pieslice": {
      const [x0, y0, x1, y1] = op.box
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const rx = (x1 - x0 + 1) / 2
      const ry = (y1 - y0 + 1) / 2
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.ellipse(cx, cy, rx, ry, 0, rad(op.start ?? 0), rad(op.end ?? 360))
      ctx.closePath()
      ctx.fillStyle = css(op.fill ?? [0, 0, 0])
      ctx.fill()
      return
    }
    case "chord": {
      const [x0, y0, x1, y1] = op.box
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const rx = (x1 - x0 + 1) / 2
      const ry = (y1 - y0 + 1) / 2
      ctx.beginPath()
      ctx.ellipse(cx, cy, rx, ry, 0, rad(op.start ?? 0), rad(op.end ?? 360))
      ctx.closePath()
      ctx.fillStyle = css(op.fill ?? [0, 0, 0])
      ctx.fill()
      return
    }
    case "polygon": {
      const [first, ...rest] = op.pts
      if (!first) return
      ctx.beginPath()
      ctx.moveTo(first[0], first[1])
      for (const p of rest) ctx.lineTo(p[0], p[1])
      ctx.closePath()
      ctx.fillStyle = css(op.fill)
      ctx.fill()
      return
    }
    default:
      throw new Error(`unknown op: ${(op as DrawOp).op}`)
  }
}

/** 按语义底色铺满（PIL Image.new 的对应物；scenes 的画布底色）。 */
export function renderSpec(
  spec: DrawSpec,
  background: RGB = [246, 243, 238],
): Promise<Buffer> {
  const { w: W, h: H, ss: SS } = spec
  const canvas = createCanvas(W * SS, H * SS)
  const ctx = canvas.getContext("2d")
  // 语义坐标直书，device 自动 ×SS（等价 Python 的坐标全乘 k）
  ctx.setTransform(SS, 0, 0, SS, 0, 0)
  ctx.fillStyle = css(background)
  ctx.fillRect(0, 0, W, H)
  for (const op of spec.ops) applyOp(ctx, op)
  // SS 超采样 → LANCZOS 缩回 1080×1920（sharp lanczos3 ≈ PIL LANCZOS）
  return sharp(canvas.encodeSync("png"))
    .resize(W, H, { kernel: "lanczos3" })
    .png()
    .toBuffer()
}
