// devices.ts — 装置外框样式注册表（devices.py 的 TS 移植）。
//
// ②③ 校验层的判据源 + ⑥ 渲染线的外框画法：
// LAST_WELL_RGB（drawDevice 铺下的井底实色，浅色 chip 判对比用）/
// deviceOf · wellColor · chipColor（装置规格读取 + chip 两型契约）/
// scenePal（场景中性色 pal 约定，ink 为道具描边唯一色）/
// DEVICE_STYLES 注册表 + dv_* 外框画法 + GROUND_Y 地面线 + drawDevice——
// 装置是数据不是代码：加样式 = 加一个注册函数（现 16 样式）。
//
// 本模块只画外框与井底色；井内 token 的逐帧填充层属场景渲染管线。
// 井位几何由调用方算好经 cells 传入，本模块不持井位常量；RTL 名单在剧本
// 数据里，由场景线持有。
//
// 使用契约：
// - **校验层只取键集**：sceneSchema / sceneDraft / lesson 判「装置 style 合法」的唯一
//   事实源是 DEVICE_STYLES 的键集，不抄第二份名单（纪律 7：手抄名单必腐烂，
//   造出「声明合法但渲不出来」的坑）。
// - **chip 两型契约**：以 `#` 开头 = 色片（须 #RRGGBB，chipColor() 返回 RGB）；
//   其余非空字符串 = 字牌（chipColor() 返回 null，走文字层贴图）。
//   parse 落库后 `"1"` 与 `1` 不可区分——引号只是书写习惯，不是判据。
// - **渲染线调用**：scenePal(identA, identB) 造 pal → drawDevice(d, device, cells, pal)
//   画外框与空井（井内 token 由逐帧填充层压在井底色之上）。
import { hexc, mix } from "./rig.js"
import type { Box, PilDraw, RGB } from "./imaging/pildraw.js"
import type { Pal } from "./scenes.js"

/** 井位：box = [x0, y0, x1, y1] + 可选井形（circle/poly/rect，缺省=圆角 18）。 */
export type Cell = readonly [number, number, number, number, (string | undefined)?]

// ---------------------------------------------------------------- 井底实色（跨调用副作用）
/** 上一轮 drawDevice 铺下的井底实色（浅色 chip 判对比用）。export let = ES live binding，
 * 与 Python 模块级 global 同语义：外部 import 读到的永远是最新值。 */
export let LAST_WELL_RGB: RGB | null = null


/** 该语种的舞台装置规格（剧本 §0.2）；缺行 = 纯对话无装置。 */
export function deviceOf(loc: any): any {
  return (loc["prop"] ?? {})["device"]
}


/** 空井底色：§0.2 `well` 显式给色则用之，否则由场景中性色推导
 * （浅色 token 落在同色底上会看不见——手册场景线配方）。 */
export function wellColor(device: any, pal: Pal): RGB {
  const w = String((device ?? {})["well"] ?? "")
  return w.startsWith("#") ? hexc(w) : mix(pal.soft, [255, 255, 255], 0.55)
}


/** 教学 token chip 两型：`#hex` 色片 → RGB；`"文本"` 字牌 → null（走文字层贴图）。 */
export function chipColor(chip: unknown): RGB | null {
  return typeof chip === "string" && chip.startsWith("#") ? hexc(chip) : null
}


/** 场景中性色：与 prerenderBg 同族的 pal 约定（ink 为道具描边唯一色——不变量⑤）。 */
export function scenePal(identA: RGB, identB: RGB): Pal {
  const ident = mix(identA, identB, 0.5)
  return {
    ink: [150, 144, 134],
    soft: mix([214, 208, 196], ident, 0.20),
    soft2: mix([190, 183, 170], ident, 0.30),
    tint: mix([255, 255, 255], ident, 0.30),
    tint2: mix([255, 255, 255], ident, 0.16),
    accent: ident,
    paper: [245, 241, 232],
  }
}


// 装置外框样式注册表（与 scenes.SCENES / rig._POSES 同构）。
// 此前是 drawDevice 里一条 15 分支 if/elif 链 + 一个裸元组闭集：加一种装置样式必须
// 改函数体，改名/漏改闭集则等到渲染时才报错。注册后「有哪些样式」由注册调用自己声明，
// 装置是数据不是代码这条原则在场景线也成立。
export const DEVICE_STYLES: Record<string, DeviceStyleFn> = {}

/** 装置样式的「地面线」：立柱/底座类装置撑到这里。`null` = 不画落地支撑（封面用——
 * 封面没有人物也没有地面，立柱只会变成两根悬空竖线）。成片恒为 1700，既有课不变。
 * 外部（封面线）要改它走 setGroundY——ES import 绑定只读，写必须经模块内函数。 */
export let GROUND_Y: number | null = 1700

/** GROUND_Y 的写通道（Python `devices.GROUND_Y = None` 的对应物——封面线用）。 */
export function setGroundY(v: number | null): void {
  GROUND_Y = v
}

type DeviceStyleFn = (d: PilDraw, cells: readonly Cell[], box: Box, pal: Pal) => void

function deviceStyle(name: string, fn: DeviceStyleFn): void {
  DEVICE_STYLES[name] = fn
}

// 装置几何（井宽/井高/井形/空井色）全部由剧本 §0.2 装置规格表给定（parse_scene 落 data），
// 注册函数只负责**外框画法**：井位/井形/空井色都不在这里（井内 token 由逐帧填充层画）。
// box = (x0, y0, x1, y1) 由 drawDevice 按 cells 算好后传入。


deviceStyle("palette", (d, _cells, [x0, y0, x1, y1], pal) => {           // 美术教室·调色盘
  d.roundedRectangle([x0, y0, x1, y1], 40, { fill: pal.soft2, outline: pal.ink, width: 5 })
})

deviceStyle("chalkboard", (d, _cells, [x0, y0, x1, y1], pal) => {         // 咖啡馆·小黑板
  const ink = pal.ink
  d.roundedRectangle([x0, y0 - 6, x1, y1 + 10], 18, { fill: [58, 66, 62], outline: ink, width: 6 })
  d.rectangle([x0 - 10, y1 + 10, x1 + 10, y1 + 30], { fill: [146, 116, 82], outline: ink, width: 4 })
})

deviceStyle("bookspine", (d, _cells, [x0, y0, x1, y1], pal) => {          // 书店·橱窗书脊
  const ink = pal.ink
  d.rectangle([x0, y0 - 10, x1, y0 + 14], { fill: [132, 100, 72], outline: ink, width: 4 })
  d.rectangle([x0 - 8, y1, x1 + 8, y1 + 22], { fill: [132, 100, 72], outline: ink, width: 4 })
})

deviceStyle("signpost", (d, _cells, [x0, y0, x1, y1], pal) => {           // 徒步·指路牌柱
  d.rectangle([(x0 + x1) / 2 - 16, y0, (x0 + x1) / 2 + 16, y1 + 54], { fill: [140, 115, 90],
    outline: pal.ink, width: 4 })
})

deviceStyle("fruit_basket", (d, cells, _box, pal) => {                    // 果摊·果筐
  const ink = pal.ink
  for (const c of cells) {
    d.polygon([[c[0] - 4, c[1] + 6], [c[2] + 4, c[1] + 6], [c[2] - 6, c[3] + 16],
      [c[0] + 6, c[3] + 16]], { fill: [178, 138, 92], outline: ink, width: 4 })
  }
})

deviceStyle("chalk_stone", (d, _cells, [x0, _y0, x1, y1], pal) => {        // 庭院·石板粉笔
  d.rectangle([x0 - 40, y1 + 4, x1 + 40, y1 + 30], { fill: pal.soft2, outline: pal.ink, width: 4 })
})

deviceStyle("doorframe", (d, _cells, [x0, y0, x1, y1], pal) => {           // 港口·漆色门框
  d.rectangle([x0 - 16, y0 - 14, x1 + 16, y1 + 12], { fill: pal.soft2, outline: pal.ink, width: 5 })
})

deviceStyle("lanterns", (d, cells, [_x0, y0, _x1, _y1], pal) => {          // 咖啡座·灯笼
  const ink = pal.ink
  d.line([_x0, y0 - 30, _x1, y0 - 30], { width: 6, fill: ink })
  for (const c of cells) {
    d.line([(c[0] + c[2]) / 2, y0 - 30, (c[0] + c[2]) / 2, c[1] - 2], { width: 3, fill: ink })
  }
})

deviceStyle("rangoli", (d, cells, _box, _pal) => {                          // 走廊·rangoli
  for (const c of cells) {
    for (let k = 0; k < 8; k++) {
      const a = k * Math.PI / 4
      d.line([[(c[0] + c[2]) / 2 + 16 * Math.cos(a), (c[1] + c[3]) / 2 + 16 * Math.sin(a)],
        [(c[0] + c[2]) / 2 + 30 * Math.cos(a), (c[1] + c[3]) / 2 + 30 * Math.sin(a)]],
        { width: 4, fill: _pal.soft2 })
    }
  }
})

deviceStyle("traffic_lamp", (d, cells, [x0, _y0, x1, y1], pal) => {        // 商店街·街灯
  const ink = pal.ink
  d.rectangle([x0 - 20, y1 + 6, x1 + 20, y1 + 22], { fill: pal.soft2, outline: ink, width: 4 })
  for (const c of cells) {
    d.line([(c[0] + c[2]) / 2, c[3], (c[0] + c[2]) / 2, y1 + 8], { width: 6, fill: ink })
  }
})

deviceStyle("cone", (d, _cells, [x0, _y0, x1, y1], pal) => {               // 街球场·训练锥
  d.rectangle([x0 - 30, y1 + 2, x1 + 30, y1 + 20], { fill: pal.soft, outline: pal.ink, width: 4 })
})

deviceStyle("gelato", (d, _cells, [x0, y0, x1, y1], pal) => {              // 广场·gelato 柜
  const ink = pal.ink
  d.roundedRectangle([x0 - 30, y0 - 6, x1 + 30, y1 + 26], 22, { fill: pal.paper,
    outline: ink, width: 5 })
  d.line([x0 - 20, y0 + 6, x1 + 20, y0 + 6], { width: 5, fill: pal.soft2 })
})

deviceStyle("dyed_cloth", (d, _cells, [x0, y0, x1, _y1], _pal) => {        // 天台·晾绳染布
  d.line([x0 - 60, y0 - 24, x1 + 60, y0 - 24], { width: 6, fill: _pal.ink })
})

deviceStyle("neon", (d, _cells, [x0, _y0, x1, y1], pal) => {               // 街市·neon 招牌
  d.rectangle([x0 - 24, y1 + 2, x1 + 24, y1 + 24], { fill: [64, 58, 66], outline: pal.ink, width: 4 })
})

deviceStyle("panel", (d, _cells, [x0, y0, x1, y1], pal) => {               // 演播室·背屏
  // 人物身后的一块宽背屏：落地底座 + 外框 + 一层比井底更亮的屏面。
  // 屏面画在**井底色铺好之前**——屏面被井盖住才是「卡片贴在屏上」。
  // **背屏必须有落地底座**：只画屏框时它悬在半空（墙板边线正好从屏底两侧垂下来，
  // 成片读成「屏被吊在半空」）。两条立柱把屏撑到地面，悬空感消失。
  // 立柱落在**屏框外缘之外**：柱心必须比屏框外缘再外推 30 以上，才落在空墙上，
  // 放在框内时柱身正好从三个人的身体中间穿过去。GROUND_Y=null（封面）时不画立柱。
  if (GROUND_Y !== null) {
    for (const lx of [x0 - 62, x1 + 14]) {                // 落地立柱：屏宽内缩，两侧各一根
      d.rectangle([lx, y1 + 34, lx + 24, GROUND_Y], { fill: pal.soft2 })
    }
  }
  d.roundedRectangle([x0 - 34, y0 - 30, x1 + 34, y1 + 34], 26,
    { fill: pal.soft2, outline: pal.ink, width: 6 })
  d.roundedRectangle([x0 - 14, y0 - 10, x1 + 14, y1 + 10], 18, { fill: pal.tint })
})

deviceStyle("tray", (_d, _cells, _box, _pal) => {                          // 裸托盘·只画井（默认值）
  // 故意不画外框：纯对话场景的默认样式，井由下方 well 铺底。
})


/** 装置外框（井内 token 由逐帧填充层画）：style 决定外框画法，井位/井形/空井色来自
 * 剧本 §0.2。§1.2 原则4「舞台原生」：每语种独立装置，不共用布景。 */
export function drawDevice(d: PilDraw, device: any, cells: readonly Cell[], pal: Pal): Box {
  const kind = (device ?? {})["style"] || "tray"
  const fn = DEVICE_STYLES[kind]
  if (!fn) {
    throw new Error(`未知装置 style：${kind}（可用 ${Object.keys(DEVICE_STYLES).sort()}）`)
  }
  const box: Box = [
    Math.min(...cells.map((c) => c[0])) - 26,
    Math.min(...cells.map((c) => c[1])) - 26,
    Math.max(...cells.map((c) => c[2])) + 26,
    Math.max(...cells.map((c) => c[3])) + 26,
  ]
  fn(d, cells, box, pal)

  // 空井：先铺底色，逐帧 token 填充压在其上——白/浅色 chip 才有对比
  const well = wellColor(device, pal)
  // 记下「token 点亮后紧贴在它背后的那层实色」：浅色 chip 靠它决定要不要加深边。
  // 这里取的是**井底色**而不是屏面色——井铺在屏面之上，chip 落在井里，
  // 观众看到 chip 的直接背景是井底。取错一层，判据就量不到观众看到的东西。
  LAST_WELL_RGB = well
  for (const c of cells) {
    const b: Box = [c[0], c[1], c[2], c[3]]
    if (c[4] === "circle") {
      d.ellipse(b, { fill: well })
    } else if (c[4] === "poly") {
      d.polygon([[(c[0] + c[2]) / 2, c[1]], [c[0], c[3]], [c[2], c[3]]], { fill: well })
    } else if (c[4] === "rect") {
      d.rectangle(b, { fill: well })
    } else {
      d.roundedRectangle(b, 18, { fill: well })
    }
  }
  return box
}
