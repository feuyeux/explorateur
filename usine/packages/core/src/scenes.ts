// scenes.ts — 场景原语（scenes.py 的 TS 移植；判定口径 = scenes_ref 金样本结构几何）。
//
// DrawScaled 超采样代理 / SS 全局超采样倍率 / prerenderBg 渐变背景与场景装配 /
// _sun / SCENES 注册表与全部 s_* 场景函数：62 个函数、65 个注册名
// （arch / lantern / boardn 三件双名注册）。
//
// 自洽无路径耦合：prerenderBg(p, card) 只读 p["identity"] 与 card["scene"]，
// 其余全靠参数注入。色表与画布基准来自 rig：SCENE（场景中性色）、
// W / H（语义画布 1080×1920）、mix / hexc——场景原语禁写字面 RGB，
// 坐标锚定画布基准（判据见 rig 源码注释）。
import { createCanvas } from "@napi-rs/canvas"
import sharp from "sharp"

import { H, SCENE, W, hexc, mix } from "./rig.js"
import { createPilDraw } from "./imaging/pildraw.js"
import type { Box, DrawOpts, PilDraw, Pt, RGB } from "./imaging/pildraw.js"

// sharp 实例类型（sharp 的 d.ts 是 `export =` 命名空间，default import 下
// sharp.Sharp 不可作类型用——ReturnType 取可调用返回型）
type SharpInstance = ReturnType<typeof sharp>

// ---- 场景原语 ----

/** 坐标等比缩放的 ImageDraw 代理：1x 语义坐标 → kx 画布，
 * 配合 LANCZOS 缩回实现全形状抗锯齿（超采样）。 */
export class DrawScaled implements PilDraw {
  constructor(
    private readonly _b: PilDraw,
    private readonly _k: number,
  ) {}

  private _box(bbox: Box): Box {
    return [bbox[0] * this._k, bbox[1] * this._k, bbox[2] * this._k, bbox[3] * this._k]
  }

  private _pts(pts: readonly Pt[] | readonly number[]): readonly Pt[] {
    // PIL 也接受扁平坐标序列（scenes 里的 d.line([0, 1010, 1080, 1010]) …）
    let list: readonly Pt[]
    if (pts.length > 0 && typeof pts[0] === "number") {
      const flat = pts as readonly number[]
      const paired: Pt[] = []
      for (let i = 0; i + 1 < flat.length; i += 2) paired.push([flat[i]!, flat[i + 1]!])
      list = paired
    } else {
      list = pts as readonly Pt[]
    }
    return list.map(([x, y]) => [x * this._k, y * this._k])
  }

  ellipse(bbox: Box, opts?: DrawOpts): void {
    this._b.ellipse(this._box(bbox), opts)
  }

  rectangle(bbox: Box, opts?: DrawOpts): void {
    this._b.rectangle(this._box(bbox), opts)
  }

  roundedRectangle(bbox: Box, rad: number, opts?: DrawOpts): void {
    this._b.roundedRectangle(this._box(bbox), Math.max(2, rad * this._k), opts)
  }

  line(pts: readonly Pt[] | readonly number[], opts?: DrawOpts): void {
    this._b.line(this._pts(pts), {
      ...opts,
      width: Math.max(1, Math.trunc((opts?.width ?? 1) * this._k)),
    })
  }

  arc(bbox: Box, a0: number, a1: number, opts?: DrawOpts): void {
    this._b.arc(this._box(bbox), a0, a1, {
      ...opts,
      width: Math.max(1, Math.trunc((opts?.width ?? 1) * this._k)),
    })
  }

  pieslice(bbox: Box, a0: number, a1: number, opts?: DrawOpts): void {
    this._b.pieslice(this._box(bbox), a0, a1, opts)
  }

  chord(bbox: Box, a0: number, a1: number, opts?: DrawOpts): void {
    this._b.chord(this._box(bbox), a0, a1, opts)
  }

  polygon(pts: readonly Pt[], opts?: DrawOpts): void {
    this._b.polygon(this._pts(pts) as readonly Pt[], opts)
  }
}


export const SS = 2  // 全局超采样倍率（人物层/场景层）


/** 场景中性色 pal 约定（rig.SCENE 之外、由人设标识色调和的那一组）。 */
export interface Pal {
  readonly ink: RGB
  readonly soft: RGB
  readonly soft2: RGB
  readonly tint: RGB
  readonly tint2: RGB
  readonly accent: RGB
  readonly paper: RGB
}

/** 渐变背景（逐语义行 mix 截断）+ 地面/站位阴影 + 场景装配。
 * 返回已就绪的 sharp 管道（LANCZOS 缩回 W×H）——调用方 .png().toBuffer() 或 composite。 */
export async function prerenderBg(
  p: { identity: string },
  card: { scene?: readonly string[] },
): Promise<SharpInstance> {
  const ident = hexc(p["identity"])
  const top = mix([246, 243, 238], ident, 0.10)
  const bottom = mix([236, 232, 224], ident, 0.20)
  const rows: Buffer = Buffer.allocUnsafe(H * W * 3)
  for (let y = 0; y < H; y++) {
    const c = mix(top, bottom, y / (H - 1))
    for (let x = 0; x < W; x++) {
      const o = (y * W + x) * 3
      rows[o] = c[0]
      rows[o + 1] = c[1]
      rows[o + 2] = c[2]
    }
  }
  // 语义分辨率渐变 → BILINEAR 上采样到 SS 画布（sharp kernel 名 linear = PIL BILINEAR）
  const up = await sharp(rows, { raw: { width: W, height: H, channels: 3 } })
    .resize(W * SS, H * SS, { kernel: "linear" })
    .raw()
    .toBuffer()
  const canvas = createCanvas(W * SS, H * SS)
  const ctx = canvas.getContext("2d")
  const img = ctx.createImageData(W * SS, H * SS)
  // up 是 3 通道 RGB raw——按步长散布进 RGBA（直接 data.set(up) 会把 RGB 字节流
  // 错位铺进 RGBA 行、尾部 1/4 留全透明；P5-7d storyteller 接线时实测抓到）
  for (let i = 0, j = 0; i < img.data.length; i += 4, j += 3) {
    img.data[i] = up[j]!
    img.data[i + 1] = up[j + 1]!
    img.data[i + 2] = up[j + 2]!
    img.data[i + 3] = 255
  }
  ctx.putImageData(img, 0, 0)
  const d = new DrawScaled(createPilDraw(ctx), SS)
  const ground = mix([230, 226, 216], ident, 0.18)
  d.rectangle([0, 1700, W, H], { fill: ground })
  d.ellipse([310, 1682, 770, 1758], { fill: mix(ground, [50, 45, 40], 0.14) })  // 站位阴影
  const pal: Pal = {
    ink: [188, 182, 170],
    soft: mix([214, 208, 196], ident, 0.22),
    soft2: mix([196, 189, 176], ident, 0.34),
    tint: mix([255, 255, 255], ident, 0.30),
    tint2: mix([255, 255, 255], ident, 0.16),
    accent: ident,
    paper: [245, 241, 232],
  }
  for (const name of card["scene"] ?? []) {
    const fn = SCENES[name]
    if (fn) fn(d, pal)
  }
  // SS 超采样 → LANCZOS 缩回 1080×1920（sharp lanczos3 ≈ PIL LANCZOS）
  return sharp(canvas.encodeSync("png")).resize(W, H, { kernel: "lanczos3" })
}


type SceneFn = (d: PilDraw, pal: Pal) => void

// 场景注册表（与 devices.DEVICE_STYLES / rig._POSES 同构的单一事实源：
// 「有哪些场景」由注册调用自己声明——加场景 = 加一个函数 + 一次注册）。
export const SCENES: Record<string, SceneFn> = {}

function _scene(name: string, fn: SceneFn): void {
  SCENES[name] = fn
}


function _sun(d: PilDraw, pal: Pal, x = 810, y = 520, r = 95, color?: RGB): void {
  d.ellipse([x - r, y - r, x + r, y + r], { fill: color ?? pal.tint })
}


_scene("sun", (d, pal) => {
  _sun(d, pal, 780, 480, 95, pal.tint)
  const radii = [46, 66, 86]
  for (let i = 0; i < radii.length; i++) {
    const r = radii[i]!
    d.arc([780 - r - 40, 480 - r - 40, 780 + r + 40, 480 + r + 40], 200, 340,
      { fill: mix(pal.tint, SCENE.white, 0.4 - i * 0.15), width: 6 })
  }
})

_scene("sun_low", (d, pal) => {
  _sun(d, pal, 820, 1020, 120, mix(SCENE.sun1, pal.accent, 0.25))
})

_scene("sky_dusk", (d, pal) => {
  for (let i = 0; i < 5; i++) {
    d.ellipse([120 + i * 190, 380 + (i % 2) * 40, 168 + i * 190, 428 + (i % 2) * 40],
      { fill: mix(SCENE.sun2, pal.accent, 0.18) })
  }
})

_scene("sky_sunset", (d, pal) => {
  d.ellipse([700, 940, 1060, 1300], { fill: mix(SCENE.sun3, pal.accent, 0.22) })
  d.line([0, 1010, 1080, 1010], { fill: mix(SCENE.white, pal.accent, 0.30), width: 8 })
})

_scene("mountains", (d, pal) => {
  d.polygon([[0, 1500], [260, 1060], [520, 1500]], { fill: pal.soft2 })
  d.polygon([[300, 1500], [620, 980], [940, 1500]], { fill: pal.soft })
  d.polygon([[556, 1078], [620, 980], [684, 1078]], { fill: SCENE.snow })
})

// 双名注册：gate_arch / arch 同一画法
const s_arch: SceneFn = (d, pal) => {
  d.roundedRectangle([140, 700, 220, 1500], 30, { fill: pal.soft2 })
  d.roundedRectangle([860, 700, 940, 1500], 30, { fill: pal.soft2 })
  d.arc([140, 560, 940, 1120], 180, 360, { fill: pal.soft2, width: 70 })
}
_scene("gate_arch", s_arch)
_scene("arch", s_arch)

_scene("flowers", (d, pal) => {
  for (const [x, y, c] of [[180, 1560, pal.accent], [250, 1620, SCENE.lantern], [900, 1580, pal.accent],
    [840, 1640, SCENE.white]] as const) {
    d.ellipse([x - 16, y - 16, x + 16, y + 16], { fill: c })
    d.line([x, y + 16, x, y + 52], { fill: SCENE.stem, width: 6 })
  }
})

_scene("studio_set", (d, pal) => {
  // 演播室景（锵锵三人行那种围坐圆桌的棚）：两侧对称弧形墙板 + 落地灯 + 圆地毯。
  // **对称是这个景的全部意义**——左右两个方向用同一个循环画，
  // 以后加装饰也只能照这个循环加，否则对称一破这里就废了。
  const ink = pal.ink
  for (const s of [-1, 1]) {                            // 对称墙板：上缘与背屏齐平，下缘到地毯
    const x0 = Math.min(540 + s * 300, 540 + s * 580)
    const x1 = Math.max(540 + s * 300, 540 + s * 580)
    d.roundedRectangle([x0, 1000, x1, 1560], 40, { fill: pal.soft, outline: ink, width: 5 })
  }
  for (const s of [-1, 1]) {                            // 落地灯：灯罩要小，杆要深
    // **灯杆必须落在背屏左右两侧之外**（|dx| > 340）：压在背屏正下方时，
    // 背屏一画完就把杆的上半截盖住，成片读成「背屏被吊着」。
    const lx = 540 + s * 498
    d.line([lx, 1150, lx, 1664], { fill: mix(pal.soft2, [90, 84, 74], 0.35), width: 9 })
    d.ellipse([lx - 26, 1092, lx + 26, 1144],
      { fill: mix(SCENE.glow, pal.accent, 0.30) })
  }
  d.ellipse([236, 1568, 844, 1792], { fill: pal.soft2 })   // 圆地毯
})

_scene("lamp", (d, pal) => {
  d.line([200, 980, 200, 1500], { fill: pal.soft2, width: 14 })
  d.ellipse([160, 920, 240, 1000], { fill: mix(SCENE.glow, pal.accent, 0.3) })
})

_scene("bus_sign", (d, pal) => {
  d.roundedRectangle([830, 1180, 920, 1500], 16, { fill: pal.soft2 })
  d.roundedRectangle([780, 1060, 970, 1200], 16, { fill: pal.accent, outline: pal.ink, width: 6 })
  d.rectangle([800, 1090, 950, 1114], { fill: SCENE.white })
  d.rectangle([800, 1130, 920, 1154], { fill: SCENE.white })
})

_scene("bench", (d, pal) => {
  d.roundedRectangle([740, 1460, 1000, 1500], 14, { fill: pal.soft2 })
  d.roundedRectangle([740, 1360, 1000, 1396], 14, { fill: pal.soft2 })
  d.rectangle([770, 1400, 786, 1560], { fill: pal.soft2 })
  d.rectangle([954, 1400, 970, 1560], { fill: pal.soft2 })
})

_scene("awning", (d, pal) => {
  d.roundedRectangle([60, 700, 560, 1240], 30, { fill: pal.tint2, outline: pal.ink, width: 6 })
  for (let i = 0; i < 6; i++) {
    const c = i % 2 === 0 ? pal.accent : SCENE.white
    d.polygon([[60 + i * 84, 700], [60 + (i + 1) * 84, 700], [60 + (i + 1) * 84 - 6, 780], [60 + i * 84 - 6, 780]], { fill: c })
  }
})

_scene("counter", (d, pal) => {
  d.roundedRectangle([120, 1300, 480, 1560], 20, { fill: pal.soft2 })
  d.rectangle([120, 1300, 480, 1330], { fill: pal.soft })
})

_scene("steam", (d) => {
  for (const [x, y0] of [[240, 1120], [330, 1080]] as const) {
    d.arc([x - 30, y0, x + 30, y0 + 90], 180, 360, { fill: SCENE.white, width: 10 })
    d.arc([x - 30, y0 - 70, x + 30, y0 + 20], 0, 180, { fill: SCENE.white, width: 10 })
  }
})

_scene("windows_big", (d, pal) => {
  d.rectangle([80, 640, 520, 1220], { fill: pal.tint2, outline: pal.ink, width: 6 })
  d.line([300, 640, 300, 1220], { fill: SCENE.lamp, width: 6 })
  d.line([80, 930, 520, 930], { fill: SCENE.lamp, width: 6 })
})

_scene("board_timetable", (d, pal) => {
  d.roundedRectangle([640, 620, 1040, 1000], 24, { fill: SCENE.night_blue, outline: pal.ink, width: 6 })
  for (let r = 0; r < 4; r++) {
    d.rectangle([670, 660 + r * 80, 940, 700 + r * 80], { fill: mix(SCENE.night_blue, pal.accent, 0.5) })
  }
})

_scene("luggage", (d, pal) => {
  d.roundedRectangle([880, 1380, 1040, 1580], 24, { fill: pal.accent, outline: pal.ink, width: 6 })
  d.roundedRectangle([840, 1420, 900, 1580], 18, { fill: pal.soft2, outline: pal.ink, width: 6 })
})

_scene("cobble_arcs", (d, pal) => {
  for (const r of [190, 320, 450]) {
    const rh = Math.floor(r / 2)
    d.arc([540 - r, 1700 - rh, 540 + r, 1700 + rh], 180, 360, { fill: pal.soft, width: 10 })
  }
})

_scene("fountain", (d, pal) => {
  d.ellipse([120, 1360, 460, 1500], { fill: mix(SCENE.sky, pal.accent, 0.25) })
  d.ellipse([200, 1390, 380, 1470], { fill: SCENE.white })
})

_scene("pigeons", (d, pal) => {
  for (const [x, y] of [[200, 1620], [280, 1660], [860, 1600]] as const) {
    d.ellipse([x - 18, y - 12, x + 18, y + 12], { fill: pal.soft2 })
    d.ellipse([x + 10, y - 22, x + 30, y - 4], { fill: pal.soft2 })
  }
})

_scene("pigeons_on_wire", (d, pal) => {
  d.line([0, 700, 1080, 760], { fill: SCENE.lamp, width: 5 })
  for (const x of [260, 460, 700]) {
    const y = 700 + (760 - 700) * x / 1080
    d.ellipse([x - 14, y - 26, x + 14, y + 2], { fill: pal.soft2 })
  }
})

_scene("shopfront", (d, pal) => {
  d.roundedRectangle([620, 760, 1020, 1500], 26, { fill: pal.tint2, outline: pal.ink, width: 6 })
  d.rectangle([660, 900, 980, 1200], { fill: mix(SCENE.glow2, pal.accent, 0.25) })
})

_scene("books_stack", (d, pal) => {
  const cols: RGB[] = [pal.accent, pal.soft2, pal.soft]
  for (let i = 0; i < cols.length; i++) {
    d.roundedRectangle([140, 1520 - i * 34, 360, 1550 - i * 34], 8, { fill: cols[i]! })
  }
})

_scene("desk_lamp", (d, pal) => {
  d.roundedRectangle([700, 1240, 1010, 1290], 16, { fill: pal.soft2 })
  d.line([960, 1250, 900, 1060], { fill: pal.soft2, width: 16 })
  d.polygon([[830, 1060], [970, 1060], [940, 990], [860, 990]], { fill: pal.accent })
})

_scene("window", (d, pal) => {
  d.roundedRectangle([700, 620, 1000, 1060], 40, { fill: mix(SCENE.sky2, pal.accent, 0.15),
    outline: pal.ink, width: 6 })
  d.line([850, 620, 850, 1060], { fill: SCENE.lamp, width: 5 })
  d.line([700, 840, 1000, 840], { fill: SCENE.lamp, width: 5 })
})

_scene("shelf", (d, pal) => {
  const cols: RGB[] = [pal.accent, pal.soft, pal.soft2]
  for (let r = 0; r < 3; r++) {
    const y = 980 + r * 160
    d.rectangle([80, y, 460, y + 16], { fill: pal.soft2 })
    for (let b = 0; b < 4; b++) {
      const c = cols[(r + b) % 3]!
      d.roundedRectangle([100 + b * 90, y - 90, 168 + b * 90, y], 6, { fill: c })
    }
  }
})

_scene("signpost", (d, pal) => {
  d.line([840, 950, 840, 1520], { fill: pal.soft2, width: 16 })
  d.roundedRectangle([760, 980, 1000, 1060], 12, { fill: pal.accent })
  d.polygon([[860, 1080], [1000, 1120], [860, 1160]], { fill: pal.accent })
})

_scene("trail", (d, pal) => {
  d.polygon([[0, 1920], [380, 1400], [760, 1920]], { fill: pal.soft })
  d.polygon([[540, 1920], [900, 1480], [1080, 1700], [1080, 1920]], { fill: pal.soft2 })
})

_scene("awning_market", (d, pal) => {
  for (let i = 0; i < 5; i++) {
    const c = i % 2 === 0 ? pal.accent : SCENE.white
    d.polygon([[620 + i * 90, 820], [620 + (i + 1) * 90, 820], [614 + (i + 1) * 90, 900], [614 + i * 90, 900]], { fill: c })
  }
  d.rectangle([620, 820, 1070, 838], { fill: SCENE.lamp })
})

_scene("crates", (d, pal) => {
  d.roundedRectangle([130, 1360, 330, 1540], 14, { fill: pal.soft2, outline: pal.ink, width: 6 })
  d.roundedRectangle([200, 1210, 400, 1360], 14, { fill: pal.soft, outline: pal.ink, width: 6 })
})

_scene("fruit_balls", (d, pal) => {
  for (const [x, y, c] of [[180, 1300, SCENE.flower], [240, 1330, SCENE.blossom], [300, 1300, pal.accent]] as const) {
    d.ellipse([x - 34, y - 34, x + 34, y + 34], { fill: c })
  }
})

_scene("umbrella", (d, pal) => {
  d.chord([700, 760, 1080, 1100], 180, 360, { fill: pal.accent })
  d.line([890, 930, 890, 1400], { fill: SCENE.lamp, width: 12 })
})

_scene("table", (d, pal) => {
  d.roundedRectangle([700, 1420, 1000, 1470], 12, { fill: pal.soft2 })
  d.rectangle([730, 1470, 750, 1620], { fill: pal.soft2 })
  d.rectangle([950, 1470, 970, 1620], { fill: pal.soft2 })
  d.ellipse([770, 1360, 830, 1420], { fill: SCENE.white })
})

_scene("plant", (d, pal) => {
  d.polygon([[180, 1600], [260, 1380], [340, 1600]], { fill: mix(SCENE.grass2, pal.accent, 0.3) })
  d.roundedRectangle([200, 1600, 320, 1690], 14, { fill: pal.soft2 })
})

_scene("arch_windows", (d, pal) => {
  d.roundedRectangle([90, 760, 250, 1200], 60, { fill: pal.tint2, outline: pal.ink, width: 6 })
  d.roundedRectangle([90, 1260, 250, 1560], 60, { fill: pal.soft2, outline: pal.ink, width: 6 })
})

_scene("fence_low", (d, pal) => {
  for (let x = 700; x < 1040; x += 80) {
    d.rectangle([x, 1480, x + 22, 1620], { fill: pal.soft2 })
  }
  d.rectangle([700, 1520, 1020, 1544], { fill: pal.soft2 })
})

_scene("tree", (d, pal) => {
  d.rectangle([880, 1250, 916, 1600], { fill: SCENE.wood })
  d.ellipse([770, 1000, 1030, 1300], { fill: mix(SCENE.grass, pal.accent, 0.25) })
})

_scene("domes", (d, pal) => {
  d.chord([120, 900, 400, 1240], 180, 360, { fill: pal.accent })
  d.chord([330, 960, 560, 1220], 180, 360, { fill: pal.soft2 })
  d.rectangle([240, 1070, 280, 1100], { fill: SCENE.white })
})

_scene("water", (d, pal) => {
  d.rectangle([0, 1480, 560, 1700], { fill: mix(SCENE.sky3, pal.accent, 0.30) })
  for (const y of [1540, 1620]) {
    d.arc([100, y, 300, y + 60], 180, 360, { fill: SCENE.white, width: 8 })
  }
})

_scene("bunting", (d, pal) => {
  d.line([0, 640, 1080, 700], { fill: SCENE.lamp, width: 4 })
  const cols: RGB[] = [pal.accent, SCENE.lantern, SCENE.white]
  for (let i = 0; i < 9; i++) {
    const x = 40 + i * 120
    const y = 640 + (700 - 640) * x / 1080
    const c = cols[i % 3]!
    d.polygon([[x, y], [x + 56, y + 4], [x + 28, y + 64]], { fill: c })
  }
})

_scene("masts", (d) => {
  for (const x of [180, 360]) {
    d.line([x, 940, x, 1480], { fill: SCENE.lamp, width: 8 })
    d.polygon([[x, 960], [x, 1200], [x - 90, 1120]], { fill: SCENE.white })
  }
})

_scene("tree_shadow", (d, pal) => {
  d.ellipse([140, 800, 520, 1160], { fill: mix(SCENE.grass, pal.accent, 0.20) })
  d.arc([120, 1120, 540, 1420], 180, 360, { fill: pal.soft, width: 12 })
})

// 双名注册：lantern / lanterns 同一画法
const s_lantern: SceneFn = (d, pal) => {
  d.roundedRectangle([140, 700, 210, 830], 20, { fill: pal.accent })
  d.rectangle([150, 830, 200, 850], { fill: SCENE.lamp })
  d.roundedRectangle([860, 730, 930, 860], 20, { fill: mix(SCENE.peach2, pal.accent, 0.4) })
}
_scene("lantern", s_lantern)
_scene("lanterns", s_lantern)

_scene("pot_brass", (d, pal) => {
  d.chord([720, 1180, 1000, 1480], 180, 360, { fill: mix(SCENE.wood2, pal.accent, 0.3) })
  d.rectangle([840, 1140, 880, 1190], { fill: SCENE.wood2 })
})

_scene("carpet", (d, pal) => {
  d.roundedRectangle([100, 1500, 420, 1620], 16, { fill: mix(SCENE.sign, pal.accent, 0.4) })
  d.rectangle([130, 1530, 390, 1590], { fill: SCENE.white })
})

_scene("brick_arches", (d, pal) => {
  for (const x of [100, 330]) {
    d.roundedRectangle([x, 820, x + 200, 1420], 70, { fill: pal.soft2 })
    d.roundedRectangle([x + 40, 980, x + 160, 1420], 50, { fill: pal.tint2 })
  }
})

// 双名注册：board_notice / board 同一画法
const s_boardn: SceneFn = (d, pal) => {
  d.roundedRectangle([740, 1000, 1020, 1300], 18, { fill: pal.paper, outline: pal.ink, width: 6 })
  for (let r = 0; r < 4; r++) {
    d.rectangle([770, 1050 + r * 60, 990, 1070 + r * 60], { fill: pal.soft })
  }
}
_scene("board_notice", s_boardn)
_scene("board", s_boardn)

_scene("palm", (d, pal) => {
  d.rectangle([170, 1150, 200, 1500], { fill: SCENE.wood })
  for (const [dx, dy] of [[-120, -60], [120, -60], [-80, -130], [80, -130], [0, -160]] as const) {
    d.ellipse([185 + dx - 70, 1150 + dy - 26, 185 + dx + 70, 1150 + dy + 26],
      { fill: mix(SCENE.grass, pal.accent, 0.25) })
  }
})

_scene("mapwall", (d, pal) => {
  d.rectangle([700, 700, 1020, 1150], { fill: pal.paper, outline: pal.ink, width: 6 })
  d.line([720, 780, 1000, 900], { fill: pal.accent, width: 8 })
  d.line([860, 760, 780, 1120], { fill: pal.soft2, width: 8 })
  d.ellipse([840, 880, 880, 920], { fill: pal.accent })
})

_scene("columns", (d, pal) => {
  for (const x of [110, 250]) {
    d.rectangle([x, 780, x + 60, 1420], { fill: pal.tint2, outline: pal.ink, width: 5 })
    d.rectangle([x - 16, 740, x + 76, 790], { fill: pal.soft2 })
  }
})

_scene("lantern_row", (d, pal) => {
  const xs = [120, 320, 900]
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i]!
    d.line([x, 620, x, 700], { fill: SCENE.lamp, width: 6 })
    d.ellipse([x - 34, 700, x + 34, 810], { fill: mix(SCENE.peach, pal.accent, 0.35 - i * 0.08) })
  }
})

_scene("wires", (d) => {
  d.line([0, 620, 1080, 680], { fill: SCENE.lamp, width: 5 })
  d.line([0, 700, 1080, 650], { fill: SCENE.lamp, width: 4 })
})

_scene("hoop", (d, pal) => {
  d.rectangle([820, 900, 852, 1500], { outline: pal.ink, width: 8 })
  d.ellipse([740, 800, 940, 1000], { outline: pal.ink, width: 14 })
  d.line([740, 950, 940, 950], { fill: SCENE.white, width: 10 })
})

_scene("fence", (d) => {
  for (let x = 80; x < 480; x += 90) {
    d.rectangle([x, 1180, x + 26, 1500], { fill: SCENE.metal })
  }
  for (const y of [1240, 1380]) {
    d.rectangle([80, y, 460, y + 20], { fill: SCENE.metal })
  }
})

_scene("skyline", (d, pal) => {
  for (const [x, w, h] of [[60, 120, 300], [220, 90, 420], [740, 140, 360], [920, 100, 260]] as const) {
    d.rectangle([x, 1500 - h, x + w, 1500], { fill: pal.soft2 })
    d.rectangle([x + 20, 1500 - h + 30, x + 40, 1500 - h + 60], { fill: SCENE.chalk })
  }
})

_scene("clothesline", (d, pal) => {
  d.line([60, 860, 520, 900], { fill: SCENE.lamp, width: 5 })
  const cols: RGB[] = [SCENE.white, pal.accent, SCENE.lantern]
  for (let i = 0; i < cols.length; i++) {
    const x = 120 + i * 130
    const y = 860 + (900 - 860) * x / 520
    d.roundedRectangle([x, y, x + 70, y + 90], 12, { fill: cols[i]! })
  }
})

_scene("stairs", (d, pal) => {
  for (let i = 0; i < 4; i++) {
    d.rectangle([680 + i * 60, 1660 - i * 90, 1080, 1680 - i * 90], { fill: mix(pal.soft, SCENE.white, i * 0.12) })
  }
})

_scene("shrubs", (d, pal) => {
  for (const [x, y] of [[180, 1560], [300, 1600]] as const) {
    d.ellipse([x - 60, y - 50, x + 60, y + 50], { fill: mix(SCENE.grass, pal.accent, 0.2) })
  }
})

_scene("neon_sign", (d, pal) => {
  d.roundedRectangle([720, 760, 1020, 940], 26, { outline: mix(SCENE.cyan, pal.accent, 0.4), width: 10 })
  d.rectangle([780, 800, 960, 830], { fill: mix(SCENE.cyan, pal.accent, 0.4) })
  d.rectangle([780, 860, 900, 890], { fill: mix(SCENE.pink, pal.accent, 0.4) })
})

_scene("window_grid", (d, pal) => {
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 2; c++) {
      const x = 110 + c * 150, y = 820 + r * 180
      d.roundedRectangle([x, y, x + 110, y + 130], 18, { fill: SCENE.steam, outline: pal.ink, width: 5 })
    }
  }
})

_scene("stall", (d, pal) => {
  d.roundedRectangle([640, 1280, 1020, 1500], 20, { fill: pal.soft2, outline: pal.ink, width: 6 })
  d.rectangle([640, 1280, 1020, 1310], { fill: pal.soft })
})

_scene("steamers", (d, pal) => {
  for (const x of [160, 260]) {
    d.ellipse([x, 1280, x + 90, 1350], { fill: pal.soft2, outline: pal.ink, width: 5 })
    for (let k = 0; k < 3; k++) {
      d.arc([x + 10 + k * 26, 1240, x + 36 + k * 26, 1290], 180, 360, { fill: SCENE.white, width: 6 })
    }
  }
})
