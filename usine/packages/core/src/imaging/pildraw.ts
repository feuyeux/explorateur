// pildraw.ts — PIL ImageDraw 语义层（rig / devices / scenes 的绘制底座）。
//
// spike 2（draw.ts op 面）实测校定过的 Pillow↔Skia 语义差，在这里以
// 「方法调用」的形式供 rig/scenes 直接使用（op 面保留给 DrawSpec 金样本判据）：
// - PIL 的 box 是闭区间（含右/下边界）：canvas 用 (x1-x0+1) 尺寸补齐这一格差。
// - PIL 的 outline 以 box 内缩 width 像素描边（外沿含 box 边界）→ strokeRect 内缩 lw/2。
// - PIL 的 ellipse/arc 描边从 box 内接椭圆**向内**加粗；canvas 居中描边 → 路径内缩 lw/2。
// - PIL 的 line 端点是平头（无 cap）——rig 的 CAP 胶囊靠「粗线 + 两端补圆」实现；
//   joint="curve" 只圆滑拐角。lineCap 用 butt，lineJoin 用 round。
// - 栅格化器不同（Pillow vs Skia），边缘 AA 必然不同——判据比结构与几何，不比像素。
import type { SKRSContext2D } from "@napi-rs/canvas"

export type RGB = readonly [number, number, number]
export type Box = readonly [number, number, number, number]
export type Pt = readonly [number, number]

export interface DrawOpts {
  fill?: RGB
  outline?: RGB
  width?: number
  joint?: "curve"
}

/** PIL ImageDraw 子集的 TS 形状（rig/devices/scenes 全部绘制原语都在这上面）。 */
export interface PilDraw {
  rectangle(box: Box, opts?: DrawOpts): void
  roundedRectangle(box: Box, rad: number, opts?: DrawOpts): void
  ellipse(box: Box, opts?: DrawOpts): void
  line(pts: readonly Pt[] | readonly number[], opts?: DrawOpts & { width?: number }): void
  arc(box: Box, a0: number, a1: number, opts?: DrawOpts & { width?: number }): void
  pieslice(box: Box, a0: number, a1: number, opts?: DrawOpts): void
  chord(box: Box, a0: number, a1: number, opts?: DrawOpts): void
  polygon(pts: readonly Pt[], opts?: DrawOpts): void
}

const css = (c: RGB): string => `rgb(${c[0]},${c[1]},${c[2]})`
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

function roundRectPath(ctx: SKRSContext2D, x0: number, y0: number, w: number, h: number, r: number): void {
  ctx.beginPath()
  if (typeof (ctx as SKRSContext2D & { roundRect?: unknown }).roundRect === "function") {
    ctx.roundRect(x0, y0, w, h, r)
  } else {
    pathRoundRect(ctx, x0, y0, w, h, r)
  }
}

/** 在 SKRSContext2D 上铺一层 PIL ImageDraw 语义。 */
export function createPilDraw(ctx: SKRSContext2D): PilDraw {
  const asPts = (pts: readonly Pt[] | readonly number[]): Pt[] => {
    // PIL 也接受扁平坐标序列（scenes 里的 d.line([0, 1010, 1080, 1010]) …）
    if (pts.length > 0 && typeof pts[0] === "number") {
      const flat = pts as readonly number[]
      const out: Pt[] = []
      for (let i = 0; i + 1 < flat.length; i += 2) out.push([flat[i]!, flat[i + 1]!])
      return out
    }
    return pts as Pt[]
  }

  return {
    rectangle([x0, y0, x1, y1], opts = {}) {
      const w = x1 - x0 + 1
      const h = y1 - y0 + 1
      if (opts.fill) {
        ctx.fillStyle = css(opts.fill)
        ctx.fillRect(x0, y0, w, h)
      }
      if (opts.outline) {
        const lw = opts.width ?? 1
        ctx.lineWidth = lw
        ctx.strokeStyle = css(opts.outline)
        const inset = lw / 2
        ctx.strokeRect(x0 + inset, y0 + inset, w - lw, h - lw)
      }
    },
    roundedRectangle([x0, y0, x1, y1], r, opts = {}) {
      const w = x1 - x0 + 1
      const h = y1 - y0 + 1
      if (opts.fill) {
        ctx.fillStyle = css(opts.fill)
        roundRectPath(ctx, x0, y0, w, h, r)
        ctx.fill()
      }
      if (opts.outline) {
        const lw = opts.width ?? 1
        ctx.lineWidth = lw
        ctx.strokeStyle = css(opts.outline)
        const inset = lw / 2
        const wr = Math.max(0, r - inset)
        roundRectPath(ctx, x0 + inset, y0 + inset, w - lw, h - lw, wr)
        ctx.stroke()
      }
    },
    ellipse([x0, y0, x1, y1], opts = {}) {
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const rx = (x1 - x0 + 1) / 2
      const ry = (y1 - y0 + 1) / 2
      const lw = opts.width ?? 1
      if (opts.fill) {
        ctx.beginPath()
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2)
        ctx.fillStyle = css(opts.fill)
        ctx.fill()
      }
      if (opts.outline) {
        ctx.beginPath()
        ctx.ellipse(cx, cy, Math.max(0, rx - lw / 2), Math.max(0, ry - lw / 2), 0, 0, Math.PI * 2)
        ctx.lineWidth = lw
        ctx.strokeStyle = css(opts.outline)
        ctx.stroke()
      }
    },
    line(ptsRaw, opts = {}) {
      const pts = asPts(ptsRaw)
      if (pts.length === 0) return
      ctx.beginPath()
      ctx.moveTo(pts[0]![0], pts[0]![1])
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i]![0], pts[i]![1])
      ctx.lineWidth = Math.max(1, Math.trunc(opts.width ?? 1))
      if (opts.fill || opts.outline) {
        ctx.strokeStyle = css((opts.fill ?? opts.outline)!)
      }
      // PIL line 端点平头（无 cap）；joint="curve" 只把拐角圆滑
      ctx.lineCap = "butt"
      ctx.lineJoin = opts.joint === "curve" ? "round" : "miter"
      ctx.stroke()
    },
    arc([x0, y0, x1, y1], a0, a1, opts = {}) {
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const lw = Math.max(1, Math.trunc(opts.width ?? 1))
      // PIL 的 arc 带从 box 内接椭圆向内加粗 → 路径内缩 lw/2
      const rx = Math.max(0, (x1 - x0 + 1) / 2 - lw / 2)
      const ry = Math.max(0, (y1 - y0 + 1) / 2 - lw / 2)
      ctx.beginPath()
      ctx.ellipse(cx, cy, rx, ry, 0, rad(a0), rad(a1))
      ctx.lineWidth = lw
      ctx.strokeStyle = css(opts.fill ?? opts.outline ?? [0, 0, 0])
      ctx.lineCap = "butt"
      ctx.stroke()
    },
    pieslice([x0, y0, x1, y1], a0, a1, opts = {}) {
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const rx = (x1 - x0 + 1) / 2
      const ry = (y1 - y0 + 1) / 2
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.ellipse(cx, cy, rx, ry, 0, rad(a0), rad(a1))
      ctx.closePath()
      ctx.fillStyle = css(opts.fill ?? [0, 0, 0])
      ctx.fill()
    },
    chord([x0, y0, x1, y1], a0, a1, opts = {}) {
      const cx = (x0 + x1) / 2
      const cy = (y0 + y1) / 2
      const rx = (x1 - x0 + 1) / 2
      const ry = (y1 - y0 + 1) / 2
      ctx.beginPath()
      ctx.ellipse(cx, cy, rx, ry, 0, rad(a0), rad(a1))
      ctx.closePath()
      ctx.fillStyle = css(opts.fill ?? [0, 0, 0])
      ctx.fill()
    },
    polygon(pts, opts = {}) {
      if (pts.length === 0) return
      ctx.beginPath()
      ctx.moveTo(pts[0]![0], pts[0]![1])
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i]![0], pts[i]![1])
      ctx.closePath()
      ctx.fillStyle = css(opts.fill ?? [0, 0, 0])
      ctx.fill()
    },
  }
}
