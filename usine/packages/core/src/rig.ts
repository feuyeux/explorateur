// rig.ts — 人物 rig 本体（rig.py 的 TS 移植；判定口径 = verify_rig 几何探针 A1–E2）。
//
// 本模块只提供「绘制能力」，不含管线编排、文件/路径耦合或卡片布局常量——
// tts / assets / render 的产物目录与缓存账本由 usine 其他层负责。
//
// 绘制能力清单（每项均为单一事实源）：
// - 色表：THEME / SCENE / NECK_SHADE_F（人物·道具与场景中性色）
// - 物理与随机：rnd / gaze / phys / jumpHeight（种子命名空间、视线漂移、挂件物理）
// - 插值缓动：mix / hexc / easeOutCubic / popScale
// - 表情与头身几何：MOOD_FACE / EYE_MOOD / FACE_SPECS / JAW / HAIR_CHEEK_KEEP /
//   JAW_BELOW / BEARD_LEGACY / jawPoint / faceProfile / sleeveColor /
//   SUNGLASS_HEAD / sunglassesHeadGeo / faceGeo
// - 绘制主体：drawCharacter（按图层序编排 draw* 阶段函数，共享状态显式化成
//   CharCtx——图层序纪律：衣不遮嘴）
// - 姿态库：POSE_CODES / poseFor（注册表，与 scenes.SCENES 同构）；口型：opennessAt（词级时间轴驱动）
//
// ctx 契约：drawCharacter(img, d, p, t, ctx) 的输入全部由调用方注入
// （p = personas.json 人设 dict）。ctx 键：scale / squash / xoff / yoff /
// head_dx / head_dy / pose / mood / blink / openness（可选 xscale / ss /
// brow_lift_extra）；poseFor 产出的顶层键由调用方 pop 进 ctx 后再传入。
//
// 数值口径（实测教训，不许"顺手优化"）：
// - Python int() = 向零截断 → mix / LN / ARC 宽度一律 Math.trunc（不是 round）。
// - opennessAt 里 round(w['s'], 2) 走 num.roundHalfEven；拼种子串时还必须过
//   pyFloat（Python str(2.0)="2.0"、JS `${2}`="2"——差一个 ".0" 种子就换空间）。
// - rnd = sha256 前 8 字节大端 ÷ 2^64；(hi*2^32+lo)/2^64 与 Python 大整数除法逐位一致。
import { createHash } from "node:crypto"

import { clamp } from "./tts/index.js"
import { roundHalfEven } from "./num.js"
import type { Box, PilDraw, Pt, RGB } from "./imaging/pildraw.js"

/** 人设 dict（personas.json 原样 JSON，只读消费）——键访问走 any，口径同 data 的 Json。 */
export type Persona = any
/** drawCharacter 的注入 ctx（运行时 JSON）。 */
export type RigCtx = any

const rad = (deg: number): number => (deg * Math.PI) / 180
/** Python str(float) 口径：整值补 ".0"（f-string 拼种子串必须逐字节一致）。 */
const pyFloat = (n: number): string => (Number.isInteger(n) ? `${n}.0` : String(n))

// rig 语义画布基准：faceGeo 的 cx=540 / ground=1700 / hy=1140 与 scenes 的全部场景坐标
// 都锚定在 1080×1920 上（几何事实，非路径常量）；目标画布不同时经 ctx["ss"] 等比缩放。
export const W = 1080
export const H = 1920


// 人物/道具常量色唯一事实源（色值只存于 personas.json 与主题文件；qa_char 同源引用）
export const THEME = {
  ink: [46, 42, 54] as RGB,             // 瞳孔/眉毛/口型线（无描边人物的唯一深色）
  mouth: [122, 54, 60] as RGB, tongue: [236, 120, 112] as RGB, blush: [247, 197, 185] as RGB,
  shoe: [56, 56, 64] as RGB,
  gold: [232, 194, 74] as RGB, pearl: [246, 242, 234] as RGB, beads: [162, 120, 70] as RGB,
  bracelet_leather: [122, 88, 58] as RGB, bracelet_woven: [204, 172, 120] as RGB,
  metal_dark: [44, 44, 52] as RGB, lens: [70, 76, 92] as RGB, camera_body: [70, 70, 78] as RGB,
  headphones: [60, 60, 70] as RGB, lens_blue: [152, 194, 214] as RGB, glint_blue: [206, 226, 238] as RGB,
  glint_soft: [226, 238, 246] as RGB, hairpin_clear: [206, 236, 246] as RGB, scarf_red: [196, 88, 74] as RGB,
  glasses_plastic: [58, 74, 44] as RGB, glasses_thin: [66, 66, 76] as RGB, glasses_dark: [56, 60, 72] as RGB,
  headband_red: [214, 69, 65] as RGB,   // 红发带（意大利三色旗 wink 的红条）
  it_flag: [[0, 146, 70], [255, 255, 255], [214, 69, 65]] as readonly RGB[],
  straw: [246, 240, 226] as RGB, apron: [238, 233, 221] as RGB,
  paper: [250, 246, 236] as RGB, paper_map: [242, 235, 216] as RGB, paper_tote: [250, 246, 238] as RGB,
  book_leather: [122, 94, 70] as RGB, pen_blue: [58, 72, 96] as RGB, satchel: [122, 92, 62] as RGB,
  bottle_blue: [122, 184, 202] as RGB, bottle_green: [152, 202, 172] as RGB, bottle_green_dark: [120, 160, 132] as RGB,
  ball: [232, 138, 66] as RGB, ball_line: [120, 60, 30] as RGB,
  skate_deck: [240, 156, 84] as RGB, skate_wheel: [70, 70, 78] as RGB,
  bag_canvas: [245, 240, 230] as RGB, bag_woven: [226, 200, 160] as RGB, bag_pouch: [238, 226, 208] as RGB,
  sparkle: [255, 208, 92] as RGB,
  shade_dark: [25, 25, 32] as RGB,      // 服装体积影/袖口混入色
}
export const NECK_SHADE_F = 0.45         // 颈部 skinShade 混入比（qa_char 同源）


// 场景中性色（单一事实源：场景原语只引用本表 / pal 令牌 / mix()，禁写字面 RGB——不变量⑤）
export const SCENE = {
  white: [255, 255, 255] as RGB,    // 蒸汽/粉笔/高光
  lamp: [75, 75, 75] as RGB,        // 灯杆/电线/护栏/路缘
  night_blue: [43, 48, 70] as RGB,  // 夜色楼体/招牌底
  metal: [150, 150, 155] as RGB,    // 卷帘门/金属构件
  sun1: [255, 214, 150] as RGB,     // 晨昏天光三层
  sun2: [255, 205, 160] as RGB,
  sun3: [255, 190, 140] as RGB,
  lantern: [255, 214, 90] as RGB,   // 灯笼/灯串暖黄
  glow: [255, 230, 160] as RGB,     // 灯箱/窗光
  glow2: [255, 235, 190] as RGB,    // 橱窗光
  chalk: [255, 235, 180] as RGB,    // 暖粉笔/卷帘门亮条
  stem: [120, 150, 100] as RGB,     // 花茎
  grass: [120, 165, 110] as RGB,    // 草地/松枝
  grass2: [120, 160, 110] as RGB,   // 远山绿
  wood: [140, 115, 90] as RGB,      // 树干/木杆
  wood2: [230, 180, 90] as RGB,     // 木牌/遮阳篷骨
  sky: [180, 220, 240] as RGB,      // 天光/水面
  sky2: [200, 228, 245] as RGB,     // 水族箱体
  sky3: [150, 200, 225] as RGB,     // 镜面水面
  steam: [160, 210, 230] as RGB,    // 蒸笼/蒸汽层
  flower: [255, 170, 90] as RGB,    // 花瓣/灯串
  blossom: [255, 210, 110] as RGB,  // 霓虹花瓣
  peach: [255, 170, 120] as RGB,    // 灯罩暖光
  sign: [200, 90, 90] as RGB,       // 招牌红
  cyan: [90, 220, 240] as RGB,      // 霓虹青
  pink: [255, 170, 200] as RGB,     // 霓虹粉
  snow: [250, 250, 250] as RGB,     // 山顶积雪
  peach2: [255, 190, 120] as RGB,   // 摊位灯罩暖光
}


/** 种子化确定性随机：sha256 首 8 字节大端 ÷ 2^64（不变量⑦种子命名空间）。 */
export function rnd(seed: string): number {
  const h = createHash("sha256").update(seed, "utf8").digest()
  const hi = h.readUInt32BE(0)
  const lo = h.readUInt32BE(4)
  return (hi * 2 ** 32 + lo) / 2 ** 64
}


/** 视线跟随镜头（gaze="camera"）：瞳孔绕镜头注视点做种子化平滑有机微漂移，
 * 神采奕奕且确定性幂等。返回 (dx, dy)∈[-1,1]；像素幅度 = (巩膜−瞳孔) 余量 × 0.35。 */
export function gaze(seed: string, t: number): [number, number] {
  const ph = 2 * Math.PI * rnd(`${seed}:gaze`)
  const gx = 0.35 * Math.sin(2 * Math.PI * 0.16 * t + ph)
  const gy = 0.20 * Math.sin(2 * Math.PI * 0.11 * t + ph * 1.5)
  return [clamp(gx, -1, 1), clamp(gy, -1, 1)]
}


/** 挂件物理（四锚点分层）：相位频率种子化，确定性幂等。
 * swing→(dx,dy) 摆动；bounce→(0,dy) 柔和颠动（余弦缓冲无尖角）；reflect→(dx,0) 高光位移。 */
export function phys(seed: string, code: string, kind: string, t: number): [number, number] {
  const ph = 2 * Math.PI * rnd(`${seed}:phys:${code}`)
  if (kind === "swing") {
    return [4.5 * Math.sin(2 * Math.PI * 0.85 * t + ph),
            1.2 * (1.0 - Math.cos(2 * Math.PI * 0.85 * t + ph))]
  }
  if (kind === "bounce") return [0.0, -1.8 * (1.0 - Math.cos(2 * Math.PI * 1.15 * t + ph))]
  if (kind === "reflect") return [8.0 * Math.sin(2 * Math.PI * 0.55 * t + ph), 0.0]
  return [0.0, 0.0]
}


/** mini_jump 起跳高度：movement.bounce 越小越弹（个性参数；qa_char 同源引用）。 */
export function jumpHeight(p: Persona): number {
  return 60 + 28 * clamp(14.0 / p["movement"]["bounce"], 0.75, 1.6)
}


/** PIL→本引擎共用插值：Python int() = 向零截断（正值上与 floor 等价，但口径按截断写）。 */
export function mix(c1: RGB, c2: RGB, f: number): [number, number, number] {
  return [Math.trunc(c1[0] + (c2[0] - c1[0]) * f),
          Math.trunc(c1[1] + (c2[1] - c1[1]) * f),
          Math.trunc(c1[2] + (c2[2] - c1[2]) * f)]
}


export function hexc(s: string): [number, number, number] {
  const t = s.replace(/^#+/, "")
  return [parseInt(t.slice(0, 2), 16), parseInt(t.slice(2, 4), 16), parseInt(t.slice(4, 6), 16)]
}


export function easeOutCubic(u: number): number {
  return 1 - (1 - u) ** 3
}


/** damp=movement.bounce：越小越弹（入场弹跳按个性参数缩放） */
export function popScale(t: number, t0: number, dur: number, overshoot = true, damp: number | null = null): number {
  if (t <= t0) return 0.0
  const u = (t - t0) / dur
  if (u >= 1) return 1.0
  if (overshoot) {
    const k = damp ? clamp(14.0 / damp, 0.75, 1.6) : 1.0
    return 1 - Math.exp(-6.0 * k * u) * Math.cos(9.0 * k * u)
  }
  return 1 - Math.exp(-5.0 * u) * (1 + 5.0 * u)
}


// ---- 人物 ----

export const MOOD_FACE = {
  neutral: { lift: 0, tilt: 0, smile: 0.6 },
  happy: { lift: 7, tilt: 0, smile: 1.0 },
  puzzled: { lift: 2, tilt: 11, smile: 0.15 },
  encouraging: { lift: 4, tilt: 0, smile: 0.8 },
  emphatic: { lift: 2, tilt: -6, smile: 0.5 },
  teach: { lift: 2, tilt: 0, smile: 0.55 },
} as const
// 眼形缩放（巩膜 ry 系数）：happy 微闭笑眼 / puzzled 睁大
export const EYE_MOOD = { neutral: 1.0, happy: 0.94, puzzled: 1.05, encouraging: 0.98, emphatic: 0.97, teach: 1.0 } as const


// 脸型规格表（6 型，按人设分配）。
// 元组 = (头高 H, 头宽系数 WH/H)。头身比与头面体量深度协调（全班底头高锚定 356~378）；
// heart＝上圆下圆收下巴、square＝方颌端庄——下颌轮廓只由这两个键驱动，其余型为纯椭圆。
export const FACE_SPECS = {
  round: [356.0, 0.955] as const,   // 婴儿圆：宽圆头，亲和萌态
  tall: [378.0, 0.81] as const,    // 窄长：清瘦秀气，挺拔匀称
  oval: [372.0, 0.86] as const,    // 端正椭圆：利落俊秀
  wide: [356.0, 0.98] as const,    // 宽和：开朗温和，面貌舒展
  heart: [368.0, 0.90] as const,    // 心形：清秀俏丽，下颌圆润微收
  square: [374.0, 0.88] as const,    // 方颌：端庄沉稳，骨相分明而不生硬
} as const

export interface JawSpec { readonly y0: number; readonly y1: number; readonly m: number; readonly n: number }

// 下颌轮廓参数（单一事实源）——heart / square 两种非椭圆下颌都走 jawPoint()。
// 轮廓 = **超椭圆** f(s) = (1 − s^m)^(1/m)，s ∈ [0,1] 从颊部走到下巴底，半宽相对 rx。
// 为什么不能用随手一条二次曲线（坑㉓「下巴太尖」）：顶点切线几乎水平的二次曲线
// 在 (hx, y) 折返成一根横向针；超椭圆 m>1 时底缘切线竖直，两支镜像合成光滑圆底。
// m 的含义：1.7 = 上圆下收（心形·圆下巴）；2.4 = 侧廓端庄俊朗、底缘微平（方颌）。
// y1 略小于 1 时底缘是一条短平边而不是收成一点——方颌要的就是这个。
export const JAW = {
  heart: { y0: 0.42, y1: 1.04, m: 1.70, n: 30 },
  square: { y0: 0.00, y1: 0.985, m: 2.40, n: 30 },
} as const

// 前发/侧发帘内缘下限（相对 rx）：脸颊高度以下不再向中轴收（否则下巴被夹成尖楔）。
export const HAIR_CHEEK_KEEP = 0.72

// 颏线以下「头宽 → 肩宽」的过渡带高度（相对头高 H）。
export const JAW_BELOW = 0.16

// 胡须反向验证接缝：True = 退回坑㉓ 之前的 PIE 形胡须。生产渲染恒为 False；
// 测试用它证明 E1/E2 不是恒真的（export let + live binding，等价 Python 猴补丁接缝）。
export let BEARD_LEGACY = false


/** 下颌轮廓上参数 s∈[0,1] 处的 (半宽/rx, 相对 hy 的高度/ry)。绘制与 qa 探针同源。 */
export function jawPoint(face: "heart" | "square", s: number): [number, number] {
  const p = JAW[face]
  return [(1.0 - s ** p.m) ** (1.0 / p.m), p.y0 + (p.y1 - p.y0) * s]
}


/** 脸颊以下（v = 相对 hy 的高度/ry，v ∈ [0,1]）的**脸**半宽系数，相对 rx。
 * 与下颌绘制同源：JAW 型走 jawPoint()，其余型是纯椭圆。qa_shape 的 D2 探针直接查
 * 这个函数的单调性——几何不变量就该用几何查（拿像素量会被发量遮挡污染）。 */
export function faceProfile(face: string, v: number): number {
  if (face === "heart" || face === "square") {
    const { y0, y1 } = JAW[face]
    if (v <= y0) return 1.0
    if (v >= y1) return 0.0
    return jawPoint(face, (v - y0) / (y1 - y0))[0]
  }
  return Math.sqrt(Math.max(0.0, 1.0 - v * v))
}


/** 袖子相对衣身的一档色阶（坑⑱）。纯平涂、禁描边（不变量⑤）——叠在躯干上的手臂
 * 只能靠**色阶**读出来。浅衣压深、深衣提亮，任意衣色都拉开一档。 */
export function sleeveColor(base: RGB, f = 0.13): [number, number, number] {
  const lum = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
  return mix(base, lum < 128 ? [255, 255, 255] : THEME.shade_dark, f)
}


// 顶戴墨镜（accessories: sunglasses_head）几何参数——单一事实源（坑㉑）。
// 旧实现散落魔数、探针与渲染必然漂移；绘制与探针现在都从这里取数。
export const SUNGLASS_HEAD = {
  top: 0.80,    // 镜架顶沿 = hy - ry*top（倒扣在发顶，不遮眼）
  dx: 52,       // 左右镜片中心距头心轴
  out_rx: 32,   // 镜框外接圆角矩形：半宽
  out_up: 22,   // 镜框上沿相对 sy0（向上）
  out_dn: 14,   // 镜框下沿相对 sy0（向下）
  rad: 14,      // 镜框圆角半径
  lens_rx: 24,  // 镜片椭圆：半宽
  lens_up: 16,  // 镜片上沿相对 sy0（向上）——与 out_up 之间是纯金属带
  lens_dn: 10,  // 镜片下沿相对 sy0（向下）
} as const

export interface SunglassHeadGeo {
  readonly sy0: number
  readonly cx_left: number
  readonly frame: Box
  readonly lens: Box
  readonly probe_band_in: Pt
  readonly probe_band_out: Pt
  readonly probe_lens: Pt
}


/** 顶戴墨镜左镜片的几何 + 探针取样点（渲染与 qa_char 同源）。
 * hdx/hdy = drawCharacter 的头部横/纵偏移（点头/走位/hop）——墨镜随头动。 */
export function sunglassesHeadGeo(G: FaceGeo, hdx = 0.0, hdy = 0.0): SunglassHeadGeo {
  const S = SUNGLASS_HEAD
  const hx = G.cx + hdx, hy = G.hy + hdy, ry = G.ry
  const sy0 = hy - ry * S.top
  const c = hx - S.dx                      // 左镜片中心
  return {
    sy0,
    cx_left: c,
    frame: [c - S.out_rx, sy0 - S.out_up, c + S.out_rx, sy0 + S.out_dn],
    lens: [c - S.lens_rx, sy0 - S.lens_up, c + S.lens_rx, sy0 + S.lens_dn],
    probe_band_in: [c, sy0 - (S.out_up + S.lens_up) * 0.5],
    probe_band_out: [c, sy0 - S.out_up - 4],
    probe_lens: [c, sy0 - (S.lens_up - S.lens_dn) * 0.5],
  }
}


/** 头身规格（单一事实源，渲染与 qa 探针共用）。单位 = 头高 H。键名保持 Python
 * snake_case：verify_rig 探针按 G["torso_hw"] 等口径逐字对齐。 */
export interface FaceGeo {
  readonly H: number
  readonly WH: number
  readonly rx: number
  readonly ry: number
  readonly hy: number
  readonly cx: number
  readonly ground: number
  readonly eye_dx: number
  readonly scl_rx: number
  readonly scl_ry: number
  readonly pup_r: number
  readonly eye_y: number
  readonly brow_y: number
  readonly mouth_y: number
  readonly blush_y: number
  readonly chin: number
  readonly torso_top: number
  readonly torso_h: number
  readonly torso_hw: number
  readonly sh_dy: number
  readonly sh_hw: number
  readonly neck_hw: number
  readonly neck_top: number
  readonly neck_bot: number
  readonly sh_x: number
  readonly sh_out: number
  readonly leg_cx: number
  readonly leg_w: number
  readonly foot_splay: number
  readonly hip_hw: number
  readonly foot_cy: number
  readonly foot_l: number
  readonly foot_h: number
  readonly up_len: number
  readonly lo_len: number
  readonly arm_w: number
  readonly hand_r: number
  readonly arm_rest: readonly [number, number]
}


export function faceGeo(face: string): FaceGeo {
  const [H_h, wfac] = (FACE_SPECS as Record<string, readonly [number, number] | undefined>)[face] ?? FACE_SPECS.round
  const WH = H_h * wfac
  const u = (f: number): number => f * H_h
  const hy = 1140.0
  const eye_y = hy - H_h / 2 + u(0.615)
  const chin = hy + H_h / 2
  const torso_top = chin + u(0.02)
  const torso_h = u(0.52)
  const torso_hw = 0.435 * WH
  const sh_dy = u(0.07)
  const sh_hw = 0.435 * WH
  const arm_w = u(0.155)
  const leg_cx = u(0.145), leg_w = u(0.185)
  return {
    H: H_h, WH, rx: WH / 2, ry: H_h / 2, hy, cx: 540.0, ground: 1700.0,
    eye_dx: 0.285 * WH, scl_rx: 0.136 * WH, scl_ry: 0.156 * WH, pup_r: 0.098 * WH,
    eye_y, brow_y: eye_y - 0.156 * WH - u(0.026),
    mouth_y: hy - H_h / 2 + u(0.810), blush_y: eye_y + 0.156 * WH * 0.95,
    chin,
    torso_top, torso_h, torso_hw,
    sh_dy, sh_hw,
    neck_hw: u(0.105), neck_top: chin - u(0.06), neck_bot: torso_top + u(0.03),
    sh_x: sh_hw - arm_w * 0.18,          // 肩点内收量（落在躯干轮廓上）
    sh_out: Math.min(sh_hw + arm_w * 0.45, WH / 2 * 0.99),  // 肩部体块外缘（不得超过头宽）
    leg_cx, leg_w, foot_splay: u(0.085),
    // 胯块半宽：取躯干的 0.92 而非腿外缘——身体是**连续柱体**，肩→胯同宽
    // （只按腿外缘铺胯块时躯干下缘圆角收进去，身体与手之间会露出背景缝，qa_shape A2）。
    hip_hw: torso_hw * 0.92,
    foot_cy: 1700.0 + u(0.006), foot_l: u(0.335), foot_h: u(0.145),
    up_len: u(0.27), lo_len: u(0.24), arm_w, hand_r: u(0.105),
    arm_rest: [7.0, 5.0],                // 静止姿态角（上臂/小臂）：手要搭在胯上
  }
}


/** drawCharacter 的绘制上下文：把绘制阶段间的共享状态显式化成实例属性，
 * 供各绘制阶段（模块级 draw* 函数）共享；绘制原语 T/TB/E/RR/LN/CAP/ARC/PIE
 * 与几何辅助 bodyEdge/sideCurtain/pfy/u/has 随之为**箭头方法**（可安全解构）。
 * 属性在构建期一次算好，阶段函数只读不改——全部数值与 Python 版逐字相同。 */
class CharCtx {
  img!: unknown
  d!: PilDraw
  p!: Persona
  t!: number
  ctx!: RigCtx
  hair_c!: RGB
  hl_c!: RGB
  skin!: RGB
  top!: RGB
  bottom!: RGB
  ident!: RGB
  skin_sh!: RGB
  face!: string
  female!: boolean
  seed!: string
  sk!: any
  G!: FaceGeo
  cx!: number
  ground!: number
  sc!: number
  q!: number
  sx!: number
  sy!: number
  bx!: number
  by!: number
  hdx!: number
  hdy!: number
  pose!: Record<string, any>
  acc!: Record<string, any>
  ss!: number
  out!: any
  skirt!: boolean
  tunic!: boolean
  pinafore!: boolean
  vest!: boolean
  rx!: number
  ry!: number
  hx!: number
  hy!: number
  eye_y!: number
  brow_y0!: number
  mouth_y!: number
  blush_y!: number
  eye_dx!: number
  scl_rx!: number
  scl_ry!: number
  pup_r!: number
  torso_top!: number
  torso_bot!: number
  torso_hw!: number
  sh_y!: number
  sh_x!: number
  sh_out!: number
  neck_hw!: number
  leg_cx!: number
  leg_w!: number
  foot_cy!: number
  foot_l!: number
  foot_h!: number
  up_len!: number
  lo_len!: number
  arm_w!: number
  hand_r!: number
  style!: string

  constructor(img: unknown, d: PilDraw, p: Persona, t: number, ctx: RigCtx) {
    const pal = p["palette"]
    this.hair_c = hexc(pal["hair"]); this.hl_c = hexc(pal["hairHighlight"])
    this.skin = hexc(pal["skin"])
    this.top = hexc(pal["outfitTop"]); this.bottom = hexc(pal["outfitBottom"])
    this.ident = hexc(p["identity"])
    this.face = p["movement"]["face"]
    this.female = p["gender"] === "female"
    this.seed = p["id"]  // 一切随机走人设 id 命名空间（不变量⑦；qa 探针同源可复算）
    this.skin_sh = hexc(pal["skinShade"])
    this.sk = p["skin"] ?? {}  // 皮肤层叠加槽（做旧/补丁，不改基型配色）
    // ---- 头身规格（faceGeo 单一事实源；cx/ground 永不手抄——不变量①）----
    this.G = faceGeo(this.face)
    this.cx = this.G.cx; this.ground = this.G.ground
    this.sc = ctx["scale"]
    this.q = ctx["squash"]
    this.sx = this.sc * (1 + this.q * 0.6) * (ctx["xscale"] ?? 1.0)
    this.sy = this.sc * (1 - this.q)
    this.bx = ctx["xoff"]; this.by = ctx["yoff"]
    this.hdx = ctx["head_dx"]; this.hdy = ctx["head_dy"]
    this.pose = ctx["pose"]
    this.acc = {}
    for (const a of (p["accessories"] ?? [])) this.acc[a["code"]] = a
    this.ss = ctx["ss"] ?? 1.0
    this.out = p["outfit"] ?? {}  // 服装轮廓槽（bottom=skirt 长裙装 / kind=tunic|pinafore|vest；缺省=长裤）
    this.skirt = this.out["bottom"] === "skirt"
    this.tunic = this.out["kind"] === "tunic"
    this.pinafore = this.out["kind"] === "pinafore"
    this.vest = this.out["kind"] === "vest"
    this.rx = this.G.rx; this.ry = this.G.ry
    this.hx = this.cx + this.hdx; this.hy = this.G.hy + this.hdy
    this.eye_y = this.G.eye_y + this.hdy
    this.brow_y0 = this.G.brow_y + this.hdy
    this.mouth_y = this.G.mouth_y + this.hdy
    this.blush_y = this.G.blush_y + this.hdy
    this.eye_dx = this.G.eye_dx
    this.scl_rx = this.G.scl_rx; this.scl_ry = this.G.scl_ry; this.pup_r = this.G.pup_r
    this.torso_top = this.G.torso_top
    // 长衫：下摆过臀（outfit.kind=tunic）
    this.torso_bot = this.torso_top + this.G.torso_h * (this.tunic ? 1.30 : 1.0)
    this.torso_hw = this.G.torso_hw
    this.sh_y = this.torso_top + this.G.sh_dy
    this.sh_x = this.G.sh_x; this.sh_out = this.G.sh_out; this.neck_hw = this.G.neck_hw
    this.leg_cx = this.G.leg_cx; this.leg_w = this.G.leg_w
    this.foot_cy = this.G.foot_cy; this.foot_l = this.G.foot_l; this.foot_h = this.G.foot_h
    this.up_len = this.G.up_len; this.lo_len = this.G.lo_len
    this.arm_w = this.G.arm_w; this.hand_r = this.G.hand_r
    this.style = p["hairStyle"]
    this.img = img; this.d = d; this.p = p; this.t = t; this.ctx = ctx
  }

  u = (f: number): number => f * this.G.H

  has = (code: string): boolean => code in this.acc

  /** 挂件物理偏移：数据声明了对应 physics 才生效（accessories.physics） */
  pfy = (code: string, kind: string): [number, number] =>
    this.has(code) && this.acc[code]["physics"] === kind
      ? phys(this.seed, code, kind, this.t)
      : [0.0, 0.0]

  T = (pt: Pt): [number, number] => [
    (this.cx + this.bx + this.sx * (pt[0] - this.cx)) * this.ss,
    (this.ground + this.by + this.sy * (pt[1] - this.ground)) * this.ss,
  ]

  TB = (x0: number, y0: number, x1: number, y1: number): Box => {
    const [a, b] = this.T([x0, y0])
    const [c, dd] = this.T([x1, y1])
    return [a, b, c, dd]
  }

  E = (x0: number, y0: number, x1: number, y1: number, fill: RGB): void => {
    this.d.ellipse(this.TB(x0, y0, x1, y1), { fill })
  }

  RR = (x0: number, y0: number, x1: number, y1: number, r: number, fill: RGB): void => {
    this.d.roundedRectangle(this.TB(x0, y0, x1, y1), Math.max(2, r * this.sc * this.ss), { fill })
  }

  LN = (pts: readonly Pt[], width: number, fill: RGB): void => {
    this.d.line(pts.map((pt) => this.T(pt)),
      { fill, width: Math.max(1, Math.trunc(width * this.sc * this.ss)), joint: "curve" })
  }

  // 胶囊：粗线 + 两端圆头（PIL line 是平头，圆头要自己补）
  CAP = (p0: Pt, p1: Pt, width: number, fill: RGB): void => {
    this.LN([p0, p1], width, fill)
    const r = width / 2
    this.E(p0[0] - r, p0[1] - r, p0[0] + r, p0[1] + r, fill)
    this.E(p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r, fill)
  }

  ARC = (x0: number, y0: number, x1: number, y1: number, a0: number, a1: number, width: number, fill: RGB): void => {
    this.d.arc(this.TB(x0, y0, x1, y1), a0, a1,
      { fill, width: Math.max(1, Math.trunc(width * this.sc * this.ss)) })
  }

  PIE = (x0: number, y0: number, x1: number, y1: number, a0: number, a1: number, fill: RGB): void => {
    this.d.pieslice(this.TB(x0, y0, x1, y1), a0, a1, { fill })
  }

  /** 人物剪影在高度 y、方向 s（−1 左 / +1 右）的边缘 x（带符号）。
   * 头发里凡是「挂在身上」的部件（辫子、低马尾、长发帘）都靠它定位；
   * 颏线以下是**平滑过渡**到肩宽 sh_out（smoothstep，两端一阶导为 0）。 */
  bodyEdge = (s: number, y: number): number => {
    const t = (y - this.hy) / this.ry
    const w = Math.abs(t) <= 1.0 ? this.rx * Math.sqrt(Math.max(0.0, 1.0 - t * t)) : 0.0
    const k = Math.min(1.0, Math.max(0.0, (y - this.G.chin) / this.u(JAW_BELOW)))
    return this.cx + s * (w + (this.sh_out - w) * k * k * (3 - 2 * k))
  }

  /** 侧发帘：内缘压在头/身上 in_w、外缘外挂 out_w，轮廓跟随剪影。
   * **内缘下限 HAIR_CHEEK_KEEP**：内缘不能一路跟着收窄的下颌走——颏线附近头半宽趋 0，
   * 固定 in_w 会把两侧内缘拉到中轴上，把脸夹成尖楔；颏线以下再平滑收到颈半宽。 */
  sideCurtain = (s: number, y0: number, y1: number, outW = 46.0, inW = 16.0, n = 18, col?: RGB): void => {
    const chin = this.G.chin
    const keepHi = this.rx * HAIR_CHEEK_KEEP
    const ptsO: Pt[] = []
    const ptsI: Pt[] = []
    for (let k = 0; k <= n; k++) {
      const yy = y0 + (y1 - y0) * k / n
      const e = this.bodyEdge(s, yy)
      const fk = Math.min(1.0, Math.max(0.0, (yy - chin) / this.u(JAW_BELOW)))
      const keep = keepHi + (this.neck_hw - keepHi) * fk * fk * (3 - 2 * fk)
      ptsO.push([e + s * outW, yy])
      ptsI.push([this.cx + s * Math.max(Math.abs(e - this.cx) - inW, keep), yy])
    }
    this.d.polygon([...ptsO, ...ptsI.reverse()], { fill: col ?? this.hair_c })
  }
}


/** 背发层（头后体积）——最底层，先画。 */
function drawBackHair(c: CharCtx): void {
  const { style, E, hx, rx, hy, ry, hair_c, seed, t, bodyEdge, sideCurtain } = c

  if (style === "ponytail_high" || style === "curly_ponytail") {
    for (const [fx, fy, r] of [[0.78, -0.52, 40], [0.92, -0.10, 34], [0.98, 0.30, 27]] as const) {
      E(hx + rx * fx - r, hy + ry * fy - r, hx + rx * fx + r, hy + ry * fy + r, hair_c)
    }
    if (style === "curly_ponytail") {
      for (const [fx, fy] of [[1.02, 0.62], [0.84, 0.78]] as const) {
        E(hx + rx * fx - 22, hy + ry * fy - 22, hx + rx * fx + 22, hy + ry * fy + 22, hair_c)
      }
    }
  }
  if (style === "ponytail_low") {
    for (const [fy, r] of [[0.12, 36], [0.54, 30], [0.94, 24]] as const) {
      // 坑⑱：低马尾沿体侧走，别钉死在头宽上（原来三颗全浮在下颌外侧空档里）
      E(bodyEdge(-1, hy + ry * fy) - r * 0.45, hy + ry * fy - r,
        bodyEdge(-1, hy + ry * fy) + r * 0.55, hy + ry * fy + r, hair_c)
    }
  }
  if (style === "braid" || style === "braid_long") {
    const n = style === "braid" ? 4 : 6
    const brPh = 2 * Math.PI * rnd(`${seed}:braid`)
    const dy = style === "braid" ? 0.52 : 0.40
    for (let i = 0; i < n; i++) {
      const fy = -0.02 + i * dy
      const r = 30 - i * 3
      const sw = 4.0 * Math.sin(2 * Math.PI * 0.7 * t + brPh + i * 0.7) * i / n  // 辫子摆动（种子相位）
      // 坑⑱：辫子原来钉在 hx−rx 的固定 x 上，下半身直接变成一串浮在体侧的圆点。
      // 改成**沿身体左缘走**：圆心 = 该高度的体侧边缘 + r·0.55，每颗都压在头/肩上。
      const bxx = bodyEdge(-1, hy + ry * fy) + r * 0.55 + sw
      E(bxx - r, hy + ry * fy - r, bxx + r, hy + ry * fy + r, hair_c)
    }
  }
  if (style === "wavy_lob" || style === "wavy_long" || style === "long_straight" || style === "long_bangs") {
    const y_end = style === "wavy_lob" ? 0.85 : 1.45
    for (const s of [-1, 1]) {   // 侧发帘跟随剪影（坑⑱），不再是两个固定位置的圆角矩形
      sideCurtain(s, hy - ry * 0.55, hy + ry * y_end, 46.0, 24.0)
    }
    if (style === "wavy_lob" || style === "wavy_long") {
      for (const sgn of [-1, 1]) {
        for (let k = 0; k < 2; k++) {
          const yy = hy + ry * y_end - 24 + k * 34
          E(bodyEdge(sgn, yy) + sgn * 38 - 26, yy, bodyEdge(sgn, yy) + sgn * 38 + 26,
            yy + 52, hair_c)
        }
      }
    }
  }
}


/** 腿与脚（含胯块）+ 脚下道具（滑板/篮球）：躯干/胯块压在腿根上，剪影连续。 */
function drawLegsFeet(c: CharCtx): void {
  const { pose, cx, G, torso_bot, u, foot_cy, foot_l, foot_h, leg_cx, leg_w, skirt, sk,
    skin, bottom, ident, has, acc, pfy, RR, E, LN, ARC } = c
  const legL_ang = pose["legL"] ?? 0, legR_ang = pose["legR"] ?? 0
  const leg_top = torso_bot - u(0.10)
  const leg_bot = foot_cy - foot_h * 0.30
  const worn_bottom = !skirt && ((sk["worn"] as string[] | undefined) ?? []).includes("bottom")  // 做旧：裤腿下半段轻微磨白
  const leg_col = skirt ? skin : bottom  // 裙装露腿：腿画肤色（裙身在躯干段画）
  // 胯块（坑⑱）：半宽取 torso_hw·0.92（faceGeo.hip_hw）——身体成为连续柱体，手也能搭在胯上。
  RR(cx - G.hip_hw, torso_bot - u(0.10), cx + G.hip_hw, torso_bot + u(0.19),
    G.hip_hw * 0.30, skirt ? leg_col : bottom)
  for (const [s, ang] of [[-1, legL_ang], [1, legR_ang]] as const) {
    const lx = cx + s * leg_cx
    RR(lx - leg_w / 2, leg_top, lx + leg_w / 2, leg_bot, leg_w / 2, leg_col)
    if (worn_bottom) {
      const wy = leg_top + (leg_bot - leg_top) * 0.42
      RR(lx - leg_w / 2, wy, lx + leg_w / 2, leg_bot, leg_w / 2, mix(leg_col, [255, 255, 255], 0.10))
    }
    RR(lx - leg_w / 2, leg_bot - u(0.05), lx + leg_w / 2, leg_bot, 10, mix(leg_col, THEME.shade_dark, 0.16))
    for (const pd of (sk["patches"] as any[] | undefined) ?? []) {  // 膝盖补丁：位置从 faceGeo 腿几何推导（不变量①）
      if (pd["on"] === "bottom" && pd["where"] === (s < 0 ? "knee_L" : "knee_R")) {
        const pc = hexc(pd["color"])
        const ky = (leg_top + leg_bot) / 2
        RR(lx - leg_w * 0.62, ky - leg_w * 0.40, lx + leg_w * 0.62, ky + leg_w * 0.40, 10, pc)
        for (const dyy of [-leg_w * 0.50, leg_w * 0.50]) {  // 补丁缝线
          LN([[lx - leg_w * 0.52, ky + dyy], [lx + leg_w * 0.52, ky + dyy]], 3,
            mix(pc, THEME.shade_dark, 0.35))
        }
      }
    }
    const fxp = lx + s * G.foot_splay + Math.sin(rad(ang)) * 72
    RR(fxp - foot_l / 2, foot_cy - foot_h / 2, fxp + foot_l / 2, foot_cy + foot_h / 2,
      foot_h * 0.46, THEME.shoe)
    E(fxp + s * foot_l * 0.16 - u(0.05), foot_cy - foot_h * 0.36,
      fxp + s * foot_l * 0.16 + u(0.05), foot_cy - foot_h * 0.04,
      mix(THEME.shoe, [255, 255, 255], 0.30))  // 鞋头高光
    if (has("shoe_accent")) {
      E(fxp - foot_l * 0.24, foot_cy - foot_h * 0.06, fxp + foot_l * 0.24, foot_cy + foot_h * 0.24,
        ident)
    }
  }
  if (has("skateboard")) {
    const kick = pose["skate_kick"] ?? 0
    const yy = 1746 - kick * 60 + pfy("skateboard", "bounce")[1]
    E(540 - 128, yy - 16, 540 + 128, yy + 16, THEME.skate_deck)
    if (acc["skateboard"]["accent"]) {  // 标识色贴纸（分镜 卡05：玫瑰点缀——滑板贴纸）
      RR(540 - 92, yy - 10, 540 + 92, yy + 2, 8, ident)
    }
    for (const wx of [540 - 78, 540 + 78]) {
      E(wx - 14, yy + 12, wx + 14, yy + 30, THEME.skate_wheel)
    }
  }
  if (has("basketball")) {
    const [bax, bay] = pfy("basketball", "bounce")
    E(540 + 196 + bax, 1618 + bay, 540 + 302 + bax, 1724 + bay, THEME.ball)
    ARC(540 + 196 + bax, 1618 + bay, 540 + 302 + bax, 1724 + bay, 100, 250, 4, THEME.ball_line)
  }
}


/** 躯干与背带/挂件：躯干压在腿上，服装轮廓（裙/背带裙/马甲）与胸前挂件逐层叠上。 */
function drawTorso(c: CharCtx): void {
  const { d, T, u, G, cx, torso_top, torso_bot, torso_hw, sh_out, sh_y, neck_hw,
    top, bottom, ident, skirt, pinafore, vest, out, has, acc, pose, pfy, seed, t,
    CAP, E, RR, ARC, LN } = c
  RR(cx - torso_hw, torso_top, cx + torso_hw, torso_bot, torso_hw * 0.62, top)
  // 肩部体块（坑⑱ 重设计）：四边形内上贴颈缘、外侧顶点落在颏线上——这是
  // 「夹心空洞」的唯一解法（外上角和头侧缘围出背景凹坑的充要条件是肩体块高过颏线）。
  for (const s of [-1, 1]) {
    const nx2 = cx + s * (neck_hw + u(0.004))
    const ox2 = cx + s * sh_out
    d.polygon([T([nx2, G.chin - u(0.03)]),
      T([ox2, G.chin + u(0.01)]),
      T([ox2, sh_y + u(0.15)]),
      T([nx2, G.chin + u(0.14)])], { fill: top })
  }
  RR(cx + torso_hw - u(0.11), torso_top + u(0.06), cx + torso_hw - u(0.025), torso_bot - u(0.05),
    u(0.08), mix(top, THEME.shade_dark, 0.10))  // 右侧体积影
  ARC(cx - 0.20 * G.WH, torso_top - u(0.055), cx + 0.20 * G.WH, torso_top + u(0.075),
    180, 360, u(0.032), mix(top, THEME.shade_dark, 0.20))  // 领口
  // ---- 服装轮廓（outfit 槽；缺省=长裤，零改动兼容） ----
  if (skirt) {  // A 字裙：腰线起、大腿中段圆摆（outfit.bottom=skirt；腿已画肤色）
    const waist = torso_top + G.torso_h - u(0.04)
    const hem = torso_top + G.torso_h + u(0.26)
    const flare = torso_hw * 1.55
    d.polygon([T([cx - torso_hw - u(0.02), waist]), T([cx - flare, hem]),
      T([cx + flare, hem]), T([cx + torso_hw + u(0.02), waist])], { fill: bottom })
    RR(cx - flare, hem - u(0.08), cx + flare, hem + u(0.02), u(0.08), bottom)  // 圆摆
    RR(cx - torso_hw - u(0.02), waist - u(0.06), cx + torso_hw + u(0.02), waist + u(0.04),
      u(0.05), mix(bottom, THEME.shade_dark, 0.14))  // 腰带
  }
  if (pinafore) {  // 背带裙：护胸＋双背带＋金色背带扣（outfit.kind=pinafore）
    const bib_w = torso_hw * 0.56
    RR(cx - bib_w, torso_top + u(0.10), cx + bib_w, torso_top + G.torso_h * 0.62, 14, bottom)
    CAP([cx - bib_w + u(0.01), torso_top + u(0.14)], [cx - u(0.115), torso_top - u(0.07)],
      u(0.055), bottom)
    CAP([cx + bib_w - u(0.01), torso_top + u(0.14)], [cx + u(0.115), torso_top - u(0.07)],
      u(0.055), bottom)
    for (const s2 of [-1, 1]) {
      E(cx + s2 * u(0.115) - u(0.016), torso_top + u(0.08), cx + s2 * u(0.115) + u(0.016),
        torso_top + u(0.112), THEME.gold)
    }
  }
  if (vest) {  // 马甲：两侧前襟片，中开白衬衫（outfit.kind=vest；面板收在内侧——外缘被垂臂遮挡）
    const vp_in = torso_hw * 0.16, vp_out = torso_hw * 0.72
    RR(cx - vp_out, torso_top + u(0.03), cx - vp_in, torso_bot - u(0.06), u(0.05), bottom)
    RR(cx + vp_in, torso_top + u(0.03), cx + vp_out, torso_bot - u(0.06), u(0.05), bottom)
  }
  if (out["buttons"]) {  // 前襟扣排（outfit.buttons；衬衫通勤感。胸前置物会自然遮住下扣）
    const bcol = mix(top, THEME.shade_dark, 0.38)
    for (const fy2 of [0.22, 0.44, 0.66]) {
      E(cx - u(0.020), torso_top + G.torso_h * fy2 - u(0.020),
        cx + u(0.020), torso_top + G.torso_h * fy2 + u(0.020), bcol)
    }
  }
  if (has("apron")) {
    RR(540 - 128, torso_top + 46, 540 + 128, torso_bot - 4, 44, THEME.apron)
    CAP([540 - 88, torso_top + 16], [540 - 62, torso_top + 52], 14, THEME.apron)
    CAP([540 + 88, torso_top + 16], [540 + 62, torso_top + 52], 14, THEME.apron)
  }
  if (has("cardigan_accent")) {
    RR(cx - torso_hw - u(0.03), torso_top, cx - torso_hw + u(0.09), torso_bot, u(0.05), mix(ident, top, 0.45))
    RR(cx + torso_hw - u(0.09), torso_top, cx + torso_hw + u(0.03), torso_bot, u(0.05), mix(ident, top, 0.45))
  }
  for (const code of ["backpack", "hikingpack", "canvas_backpack"]) {
    if (has(code)) {
      const dark = mix(top, [30, 30, 30], 0.30)
      const web = acc[code]["accent"] ? mix(ident, top, 0.25) : dark  // 标识色织带（挂件行）
      CAP([540 - 96, torso_top + 4], [540 - 56, torso_top + 40], 20, web)
      CAP([540 + 96, torso_top + 4], [540 + 56, torso_top + 40], 20, web)
      const [bx_p, by_p] = pfy(code, "bounce")
      RR(540 + 150 + bx_p, torso_top + 130 + by_p, 540 + 220 + bx_p, torso_top + 214 + by_p, 20, dark)
      if (has("bottle")) {
        const [bo_x, bo_y] = pfy("bottle", "swing")
        RR(540 + 160 + bo_x, torso_top + 104 + bo_y, 540 + 192 + bo_x, torso_top + 152 + bo_y, 12,
          THEME.bottle_blue)
      }
    }
  }
  if (has("satchel")) {
    CAP([540 - 116, torso_top + 8], [540 + 98, torso_bot - 46], 16, THEME.satchel)
    RR(540 + 66, torso_bot - 84, 540 + 152, torso_bot + 2, 18, THEME.satchel)
  }
  const bags: readonly (readonly [string, RGB, number])[] = [
    ["tote", THEME.bag_canvas, 92], ["woven_bag", THEME.bag_woven, 92],
    ["book_tote", THEME.paper_tote, 92], ["minibag", THEME.bag_canvas, 66],
    ["pouch", THEME.bag_pouch, 58]]
  for (const [code, bc, bw] of bags) {
    if (!has(code)) continue
    const bxr = 540 + 152
    const kind = acc[code]["physics"]  // 挎包物理：swing 摆 / bounce 颠
    const [sx_p, sy_p] = kind ? phys(seed, code, kind, t) : [0.0, 0.0]
    ARC(bxr - Math.floor(bw / 2) + 14 + sx_p, torso_top + 40 + sy_p * 0.4, bxr + Math.floor(bw / 2) - 14 + sx_p,
      torso_top + 128 + sy_p * 0.4, 180, 360, 8, bc)
    RR(bxr - Math.floor(bw / 2) + sx_p * 1.3, torso_top + 76 + sy_p, bxr + Math.floor(bw / 2) + sx_p * 1.3,
      torso_top + 76 + bw + 22 + sy_p, 20, bc)
    if (acc[code]["accent"]) {  // 书袋挂饰（分镜 卡17：藏红花橙点缀——书袋挂饰）
      E(bxr + sx_p * 1.3 - 10, torso_top + 76 + bw + 22 + sy_p, bxr + sx_p * 1.3 + 10,
        torso_top + 76 + bw + 32 + sy_p, ident)
    }
  }
  if (has("scarf")) {
    const col = acc["scarf"]["accent"] ? ident : THEME.scarf_red
    const [sc_x, sc_y] = pfy("scarf", "swing")
    RR(540 - 104, torso_top - 30, 540 + 104, torso_top + 34, 30, col)
    RR(540 + 18 + sc_x, torso_top + 18 + sc_y * 0.5, 540 + 66 + sc_x, torso_top + 128 + sc_y * 0.5, 18,
      col)  // 围巾垂尾随风摆
  }
  if (has("necklace")) {
    const [nx, ny] = pfy("necklace", "swing")
    ARC(540 - 58 + nx * 0.3, torso_top - 10, 540 + 58 + nx * 0.3, torso_top + 96, 15, 165, 5, THEME.gold)
    E(532 + nx, torso_top + 64 + ny, 548 + nx, torso_top + 80 + ny, THEME.gold)  // 吊坠摆动
  }
  if (has("lanyard")) {
    CAP([540 - 52, torso_top - 2], [540 - 12, torso_top + 74], 9, ident)
    CAP([540 + 52, torso_top - 2], [540 + 12, torso_top + 74], 9, ident)
    const [lx_p, ly_p] = pfy("lanyard", "swing")
    RR(540 - 28 + lx_p, torso_top + 70 + ly_p, 540 + 28 + lx_p, torso_top + 130 + ly_p, 12, [255, 255, 255])
    RR(540 - 28 + lx_p, torso_top + 70 + ly_p, 540 + 28 + lx_p, torso_top + 84 + ly_p, 6, ident)
  }
  if (has("pin_badge")) {
    E(540 - 104, torso_top + 60, 540 - 72, torso_top + 92, ident)
  }
  if (has("pen")) {
    CAP([540 + 92, torso_top + 62], [540 + 104, torso_top + 100], 9, THEME.pen_blue)
  }
  if (has("zipper")) {  // 外套拉链：前襟拉链线＋拉链头（标识色拉链头）
    LN([[cx, torso_top + u(0.04)], [cx, torso_top + G.torso_h * 0.88]], u(0.016),
      mix(top, THEME.shade_dark, 0.22))
    const zc = acc["zipper"]["accent"] ? ident : THEME.metal_dark
    CAP([cx, torso_top + u(0.10)], [cx, torso_top + u(0.24)], u(0.026), zc)
    E(cx - u(0.016), torso_top + u(0.24), cx + u(0.016), torso_top + u(0.272), zc)  // 拉链头坠
  }
  if (has("clipboard")) {  // 胸前笔记夹板：板＋纸＋标识色夹扣
    const cbx = cx + torso_hw * 0.42
    RR(cbx - u(0.085), torso_top + u(0.09), cbx + u(0.085), torso_top + u(0.40), 8, THEME.bag_woven)
    RR(cbx - u(0.062), torso_top + u(0.135), cbx + u(0.062), torso_top + u(0.365), 4, THEME.paper)
    const cbc = acc["clipboard"]["accent"] ? ident : THEME.metal_dark
    RR(cbx - u(0.050), torso_top + u(0.105), cbx + u(0.050), torso_top + u(0.135), 5, cbc)
    LN([[cbx - u(0.040), torso_top + u(0.19)], [cbx + u(0.040), torso_top + u(0.19)]], 3, THEME.pen_blue)
  }
  if (has("towel_shoulder")) {  // 肩搭白毛巾＋标识色毛巾条
    const twx = cx - torso_hw
    CAP([twx - u(0.03), torso_top - u(0.10)], [twx + u(0.04), torso_top + u(0.30)], u(0.10), [246, 246, 240])
    const twc = acc["towel_shoulder"]["accent"] ? ident : mix([246, 246, 240], THEME.shade_dark, 0.25)
    RR(twx + u(0.005), torso_top + u(0.20), twx + u(0.075), torso_top + u(0.30), 5, twc)
  }
  if (has("camera") || has("camera_neck")) {
    const s2 = has("strap_accent") ? ident : THEME.camera_body
    const ccode = has("camera") ? "camera" : "camera_neck"
    const [cx_p, cy_p] = pfy(ccode, "swing")
    CAP([540 - 74, torso_top - 4], [540 - 30 + cx_p * 0.4, torso_top + 66], 9, s2)
    CAP([540 + 74, torso_top - 4], [540 + 30 + cx_p * 0.4, torso_top + 66], 9, s2)
    RR(540 - 48 + cx_p, torso_top + 52 + cy_p, 540 + 48 + cx_p, torso_top + 132 + cy_p, 16, THEME.camera_body)
    E(540 - 18 + cx_p, torso_top + 76 + cy_p, 540 + 18 + cx_p, torso_top + 112 + cy_p, THEME.lens_blue)
  }
  if (has("sunglasses_neck")) {
    const [gx_n] = pfy("sunglasses_neck", "swing")
    RR(540 - 44 + gx_n, torso_top + 58, 540 + 44 + gx_n, torso_top + 94, 14, THEME.metal_dark)
    CAP([540 - 40 + gx_n, torso_top + 68], [540 + 40 + gx_n, torso_top + 68], 6, THEME.metal_dark)
    E(540 - 34 + gx_n * 1.4, torso_top + 62, 540 - 12 + gx_n * 1.4, torso_top + 74,
      THEME.glint_blue)  // 镜片反光（qa_motion 探针）
  }
  if (has("map")) {
    RR(540 - 178, torso_top + 118, 540 - 92, torso_top + 182, 10, THEME.paper_map)
    CAP([540 - 166, torso_top + 136], [540 - 104, torso_top + 162], 5, ident)
  }
  if (has("planner")) {
    RR(540 - 70, torso_top + 96, 540 + 20, torso_top + 168, 12, THEME.paper)
    CAP([540 - 70, torso_top + 120], [540 + 20, torso_top + 120], 4, ident)
  }
  if (has("pocketbook")) {
    RR(540 - 174, torso_top + 108, 540 - 82, torso_top + 178, 12, THEME.book_leather)
  }
  if (has("beads") && pose["hand_prop"] !== "beads") {
    const [bx_b, by_b] = pfy("beads", "swing")
    for (let k = 0; k < 5; k++) {
      const ak = k * 1.15
      const cxx = 540 + 162 + bx_b + Math.cos(ak) * 16
      const cyy = torso_top + 140 + by_b * 0.6 + Math.sin(ak) * 16
      E(cxx - 6, cyy - 6, cxx + 6, cyy + 6, THEME.beads)
    }
  }
  if (has("bottle_big") && pose["hand_prop"] !== "bottle") {
    const [bx_g, by_g] = pfy("bottle_big", "swing")
    RR(540 + 144 + bx_g, torso_top + 100 + by_g * 0.5, 540 + 182 + bx_g, torso_top + 180 + by_g * 0.5, 16,
      THEME.bottle_green)
  }
}


/** 手臂（胶囊袖 + 圆手 + 袖口）与腕上配饰、手中道具光效。 */
function drawArms(c: CharCtx): void {
  const { u, cx, sh_x, sh_y, up_len, lo_len, arm_w, hand_r, skin, top, ident,
    G, pose, t, has, CAP, E, RR } = c
  // 画在躯干之后、颈与头之前：袖子是「衣服层」，抬臂姿态会把袖子胶囊扫过人脸——
  // 衣层在脸前会遮嘴，故脸/嘴永远画在手臂之上（图层序纪律）。
  const sleeve = sleeveColor(top)

  const arm = (side: number, a1: number, a2: number, hand = "open", prop: string | null = null): [Pt, Pt] => {
    const s = side
    // 肩点内收（坑⑱）：落在躯干轮廓上（sh_x = sh_hw − arm_w·0.18）。
    const sh: Pt = [cx + s * sh_x, sh_y]
    const a1r = rad(a1), a2r = rad(a2)
    const el: Pt = [sh[0] + s * Math.sin(a1r) * up_len, sh[1] + Math.cos(a1r) * up_len]
    const ha: Pt = [el[0] + s * Math.sin(a1r + a2r) * lo_len, el[1] + Math.cos(a1r + a2r) * lo_len]
    const wr: Pt = [el[0] + (ha[0] - el[0]) * 0.82, el[1] + (ha[1] - el[1]) * 0.82]
    CAP(sh, el, arm_w, sleeve)
    CAP(el, ha, arm_w * 0.88, sleeve)
    const c0: Pt = [el[0] + (ha[0] - el[0]) * 0.72, el[1] + (ha[1] - el[1]) * 0.72]
    const c1: Pt = [el[0] + (ha[0] - el[0]) * 0.88, el[1] + (ha[1] - el[1]) * 0.88]
    CAP(c0, c1, arm_w * 0.90, mix(sleeve, THEME.shade_dark, 0.16))  // 袖口
    const hr = hand_r
    E(ha[0] - hr, ha[1] - hr, ha[0] + hr, ha[1] + hr, skin)
    if (hand === "thumb") {
      CAP([ha[0] + s * hand_r * 0.2, ha[1] - hr - u(0.018)], [ha[0] + s * hand_r * 0.66, ha[1] - hr - u(0.088)],
        u(0.044), skin)
    }
    if (hand === "index") {
      const ai = a1r + a2r
      const tip: Pt = [ha[0] + s * Math.sin(ai) * u(0.13), ha[1] + Math.cos(ai) * u(0.13)]
      CAP([ha[0] + s * u(0.018), ha[1] - u(0.018)], tip, u(0.036), skin)
    }
    if (prop === "bottle") {
      RR(ha[0] - u(0.055), ha[1] - u(0.197), ha[0] + u(0.055), ha[1] - u(0.028), u(0.04), THEME.bottle_green)
      RR(ha[0] - u(0.028), ha[1] - u(0.242), ha[0] + u(0.028), ha[1] - u(0.186), u(0.018), THEME.bottle_green_dark)
    }
    if (prop === "beads") {
      for (let k = 0; k < 6; k++) {
        const ak = k * 1.05
        const cxx = ha[0] + Math.cos(ak) * u(0.062), cyy = ha[1] + u(0.017) + Math.sin(ak) * u(0.062)
        E(cxx - u(0.02), cyy - u(0.02), cxx + u(0.02), cyy + u(0.02), THEME.beads)
      }
    }
    if (prop === "camera") {
      RR(ha[0] - u(0.096), ha[1] - u(0.073), ha[0] + u(0.096), ha[1] + u(0.073), u(0.034), THEME.camera_body)
      E(ha[0] - u(0.039), ha[1] - u(0.039), ha[0] + u(0.039), ha[1] + u(0.039), THEME.lens_blue)
    }
    return [ha, wr]
  }

  const [rest_a1, rest_a2] = G.arm_rest  // 静止姿态角（faceGeo 单一事实源，探针同源）
  const aL: any[] = pose["armL"] || [rest_a1 + 5 * Math.sin(2 * Math.PI * t * 0.55), rest_a2, "open", null]
  const aR: any[] = pose["armR"] || [rest_a1 - 5 * Math.sin(2 * Math.PI * t * 0.55), rest_a2, "open", null]
  arm(-1, aL[0], aL[1], aL[2], aL.length > 3 ? aL[3] : null)
  const [ha_pos, wr_pos] = arm(1, aR[0], aR[1], aR[2], aR.length > 3 ? aR[3] : null)
  for (const [code, bc] of [["watch", ident], ["bracelet", THEME.gold],
    ["bracelet_leather", THEME.bracelet_leather], ["bracelet_woven", THEME.bracelet_woven]] as const) {
    if (has(code)) {
      CAP([wr_pos[0] - u(0.05), wr_pos[1] - u(0.022)], [wr_pos[0] + u(0.05), wr_pos[1] - u(0.022)],
        u(0.042), bc)
    }
  }
  if (pose["hand_prop"] === "sparkle") {
    for (const ang3 of [210, 270, 330]) {
      const r0 = hand_r * 0.85, r1 = hand_r * 1.52
      CAP([ha_pos[0] + Math.cos(rad(ang3)) * r0, ha_pos[1] + Math.sin(rad(ang3)) * r0],
        [ha_pos[0] + Math.cos(rad(ang3)) * r1, ha_pos[1] + Math.sin(rad(ang3)) * r1],
        u(0.02), THEME.sparkle)
    }
  }
  if (pose["hand_prop"] === "flash") {
    E(ha_pos[0] - u(0.18), ha_pos[1] - u(0.18), ha_pos[0] + u(0.18), ha_pos[1] + u(0.18), [255, 250, 214])
  }
}


/** 颈与头：颈部受光少压深一层、头形（纯椭圆 / 超椭圆下颌）、耳朵。 */
function drawNeckHead(c: CharCtx): void {
  const { cx, neck_hw, u, G, skin, skin_sh, face, hx, rx, hy, ry, eye_y, RR, PIE, TB, T, d, E } = c
  const neck_c = mix(skin, skin_sh, NECK_SHADE_F)  // 颈部受光少：skinShade 压深（qa_char 探针同源）
  RR(cx - neck_hw, G.neck_top, cx + neck_hw, G.neck_bot, u(0.05), neck_c)
  RR(cx - neck_hw, G.neck_top, cx + neck_hw, G.neck_top + u(0.022), u(0.02),
    mix(skin_sh, skin, 0.30))  // 下颌阴影
  if (face === "heart" || face === "square") {  // heart / square：上半椭圆 + 直边 + 超椭圆下颌（参数见 JAW）
    const jp = JAW[face]
    PIE(hx - rx, hy - ry, hx + rx, hy + ry, 180, 360, skin)
    if (jp.y0 > 0) {      // 颊部到下颌起点之间补直边（square 从 y=0 起，无需补）
      d.rectangle(TB(hx - rx, hy, hx + rx, hy + ry * jp.y0), { fill: skin })
    }
    const jaw: Pt[] = []
    for (const sg of [-1, 1]) {
      const ks: number[] = []
      if (sg < 0) for (let k = 0; k <= jp.n; k++) ks.push(k)
      else for (let k = jp.n - 1; k >= 0; k--) ks.push(k)  // 顶点只出一次
      for (const k of ks) {
        const [jw, jv] = jawPoint(face, k / jp.n)
        jaw.push(T([hx + sg * rx * jw, hy + ry * jv]))
      }
    }
    d.polygon(jaw, { fill: skin })
  } else {
    E(hx - rx, hy - ry, hx + rx, hy + ry, skin)
  }
  for (const s of [-1, 1]) {  // 耳朵（多数发型被侧发覆盖，露出即增加真实感）
    const eax = hx + s * rx * 0.94
    E(eax - u(0.045), eye_y - u(0.085), eax + u(0.045), eye_y + u(0.045), skin)
    E(eax + s * u(0.005) - u(0.022), eye_y - u(0.058), eax + s * u(0.005) + u(0.022), eye_y - u(0.010),
      mix(skin, skin_sh, 0.30))  // 耳窝影走 skinShade（不再写死）
  }
}


/** 前发（有机圆润 + 高光）与发型件：压在脸/耳朵之上、表情之下。 */
function drawFrontHair(c: CharCtx): void {
  const { hx, rx, hy, ry, hair_c, hl_c, ident, style, skin, has, seed, t, u,
    sideCurtain, PIE, ARC, E, CAP, RR } = c
  const cap_lo = hy + ry * 0.45
  PIE(hx - rx - 10, hy - ry - 10, hx + rx + 10, cap_lo, 182, 358, hair_c)
  ARC(hx - rx * 0.60, hy - ry * 0.94, hx + rx * 0.28, hy - ry * 0.34, 220, 310, 12, hl_c)
  if (style === "bob_bangs" || style === "long_bangs") {
    for (const [fx, fr] of [[-0.62, 0.13], [-0.02, 0.16], [0.58, 0.13]] as const) {
      E(hx + rx * fx - rx * fr, hy - ry * 0.26 - rx * fr,
        hx + rx * fx + rx * fr, hy - ry * 0.26 + rx * fr, hair_c)
    }
  }
  if (style === "bob" || style === "bob_bangs" || style === "wavy_lob" || style === "wavy_long"
    || style === "long_straight" || style === "long_bangs") {
    const yl = (style === "bob" || style === "bob_bangs") ? 0.55 : (style === "wavy_lob" ? 0.95 : 1.25)
    for (const s of [-1, 1]) {
      sideCurtain(s, hy - ry * 0.45, hy + ry * yl, 34.0, 22.0)
    }
  }
  if (style === "short" || style === "short_messy" || style === "short_gray" || style === "short_stubble"
    || style === "crop" || style === "crop_ahoge") {
    for (const [fx, fy, fr] of [[-0.55, -0.92, 30], [-0.28, -0.98, 32], [0.02, -1.02, 34], [0.30, -0.98, 32], [0.55, -0.92, 30]] as const) {
      E(hx + rx * fx - fr, hy + ry * fy - fr, hx + rx * fx + fr, hy + ry * fy + fr, hair_c)
    }
    if (style === "short_messy") {
      E(hx + rx * 0.72, hy - ry * 1.04, hx + rx * 0.98 + 16, hy - ry * 0.84, hair_c)
    }
    if (style === "short_stubble") {
      ARC(hx - rx * 0.60, hy + ry * 0.50, hx + rx * 0.60, hy + ry * 1.05, 30, 150, 10,
        mix(hair_c, skin, 0.55))
    }
  }
  if (style === "short_ahoge" || style === "crop_ahoge") {  // 呆毛随晚风一颤（分镜 卡20 彩蛋；qa_motion 探针）
    const ax = 5.0 * Math.sin(2 * Math.PI * 0.9 * t + 2 * Math.PI * rnd(`${seed}:ahoge`))
    CAP([hx + 10, hy - ry * 0.92], [hx + 52 + ax, hy - ry * 1.28 - Math.abs(ax) * 0.35], 12, hair_c)
    CAP([hx + 52 + ax, hy - ry * 1.28 - Math.abs(ax) * 0.35], [hx + 88 + ax * 1.5, hy - ry * 1.08 - Math.abs(ax) * 0.15],
      12, hair_c)
  }
  if (style === "short_part") {  // 侧分头：斜扫刘海＋分缝高光（江远/人形路标）
    for (const [fx, fy, fr] of [[-0.46, -0.62, 0.40], [0.10, -0.56, 0.42], [0.58, -0.64, 0.32]] as const) {
      E(hx + rx * fx - rx * fr, hy + ry * fy - rx * fr, hx + rx * fx + rx * fr,
        hy + ry * fy + rx * fr, hair_c)
    }
    CAP([hx - rx * 0.58, hy - ry * 0.74], [hx - rx * 0.28, hy - ry * 1.00], u(0.026), hl_c)
  }
  if (style === "short_neat") {  // 一丝不苟短发：平直刘海边（Théo/慢先生）
    RR(hx - rx * 0.82, hy - ry * 0.60, hx + rx * 0.82, hy - ry * 0.34, 10, hair_c)
    CAP([hx - rx * 0.66, hy - ry * 0.70], [hx - rx * 0.20, hy - ry * 0.94], u(0.024), hl_c)
  }
  if (style === "short_wavy" || style === "short_curly" || style === "curly_short" || style === "curly_volume"
    || style === "undercut_curly") {
    const [a_lo, a_hi] = style === "undercut_curly" ? [232, 308] : [198, 342]
    const n = style === "undercut_curly" ? 5 : 7
    const rr2 = style === "curly_volume" ? 34 : 26
    for (let i = 0; i < n; i++) {
      const ang2 = rad(a_lo + i * (a_hi - a_lo) / (n - 1))
      const cxx = hx + (rx + 4) * Math.cos(ang2)
      const cyy = hy + (ry + 4) * Math.sin(ang2)
      E(cxx - rr2, cyy - rr2, cxx + rr2, cyy + rr2, hair_c)
    }
  }
  if (style === "bun") {
    E(hx - 44, hy - ry - 86, hx + 44, hy - ry + 2, hair_c)
    E(hx - 30, hy - ry - 72, hx + 30, hy - ry - 16, hl_c)
  }
  if (style === "ponytail_high" || style === "curly_ponytail") {
    E(hx + rx * 0.70 - 26, hy - ry * 0.66 - 26, hx + rx * 0.70 + 26, hy - ry * 0.66 + 26,
      has("hair_tie") ? ident : mix(hair_c, [255, 255, 255], 0.25))
  }
  if (style === "ponytail_low") {
    E(hx - rx * 0.90 - 22, hy + ry * 0.14 - 22, hx - rx * 0.90 + 22, hy + ry * 0.14 + 22,
      has("hair_tie") ? ident : mix(hair_c, [255, 255, 255], 0.25))
  }
  if (style === "braid" || style === "braid_long") {
    const n2 = style === "braid" ? 4 : 6
    const fy_end = -0.02 + n2 * (style === "braid" ? 0.52 : 0.40)
    E(hx - rx * 1.00 - 18, hy + ry * fy_end - 14, hx - rx * 1.00 + 18, hy + ry * fy_end + 16, ident)
  }
}


/** 胡须：表情之前画（嘴要盖在胡子上面）；BEARD_LEGACY 分支只给反向验证用。 */
function drawBeard(c: CharCtx): void {
  const { has, face, hair_c, skin, hx, rx, hy, ry, mouth_y, T, d, E, PIE } = c
  if (has("beard") && !BEARD_LEGACY) {  // 表情之前画：嘴要盖在胡子上面
    // 拆成两件：**八字须**（压在嘴上、两端挑出胡须线）+ **络腮**（实心块：上缘一条
    // 胡须线、下缘沿脸廓 faceProfile 走、圆胡尖只探出下巴 0.03·ry）。
    const bc = mix(hair_c, skin, 0.25)
    const v_side = 0.48, v_top = 0.60     // 鬓角起点 / 络腮上缘（自然贴合下颌轮廓）
    const w_side = faceProfile(face, v_side)
    const w_top = faceProfile(face, v_top) * 0.90
    const jaw_top: Pt[] = [[hx - w_side * rx, hy + ry * v_side], [hx - w_top * rx, hy + ry * v_top],
      [hx, hy + ry * v_top],
      [hx + w_top * rx, hy + ry * v_top], [hx + w_side * rx, hy + ry * v_side]]
    const nb = 26
    const lower: Pt[] = []                // 右鬓角 → 下巴 → 左鬓角，严格沿脸廓
    for (let k = 0; k <= 2 * nb; k++) {
      const uu = k / (2 * nb)
      const v = v_side + (1.0 - v_side) * (1 - Math.abs(2 * uu - 1))
      lower.push([hx + faceProfile(face, Math.min(v, 1.0)) * rx * (2 * uu - 1), hy + v * ry])
    }
    d.polygon([...jaw_top, ...lower.reverse()].map((p) => T(p)), { fill: bc })
    E(hx - rx * 0.18, hy + ry * 0.93, hx + rx * 0.18, hy + ry * 1.03, bc)   // 圆胡尖
    // 八字须：贴上唇一小片，两端挑到胡须线以上（这就是「八字」的形状来源）
    d.polygon([
      T([hx - rx * 0.32, mouth_y - ry * 0.17]), T([hx - rx * 0.20, mouth_y - ry * 0.13]),
      T([hx, mouth_y - ry * 0.08]),
      T([hx + rx * 0.20, mouth_y - ry * 0.13]), T([hx + rx * 0.32, mouth_y - ry * 0.17]),
      T([hx + rx * 0.20, mouth_y + ry * 0.02]), T([hx, mouth_y + ry * 0.03]),
      T([hx - rx * 0.20, mouth_y + ry * 0.02])], { fill: bc })
  } else if (has("beard")) {  // BEARD_LEGACY：坑㉓ 之前的 PIE 形胡须，**只给反向验证用**
    PIE(hx - rx * 0.70, hy + ry * 0.34, hx + rx * 0.70, hy + ry * 1.30, 25, 155,
      mix(hair_c, skin, 0.25))
  }
}


/** 表情：眼（眨眼弧 / 瞳孔双高光 / 视线跟随镜头）、眉、嘴（openness 驱动）、腮红。 */
function drawFace(c: CharCtx): void {
  const { ctx, seed, t, hx, eye_dx, eye_y, scl_rx, scl_ry, pup_r, brow_y0, mouth_y,
    blush_y, female, u, G, p, E, ARC, CAP, PIE, RR } = c
  const mood = MOOD_FACE[ctx["mood"] as keyof typeof MOOD_FACE]
  const lift = mood.lift + (ctx["brow_lift_extra"] ?? 0)
  const tilt = mood.tilt
  const eye_k = EYE_MOOD[ctx["mood"] as keyof typeof EYE_MOOD]  // 眼形：happy 微闭笑眼 / puzzled 睁大
  const [gdx, gdy] = gaze(seed, t)  // 视线跟随镜头：漂移 ≤ (巩膜−瞳孔) 余量 × 0.35（探针安全）
  const gpx = gdx * (scl_rx - pup_r) * 0.35
  const gpy = gdy * (scl_ry - pup_r * 1.2) * 0.35
  for (const s of [-1, 1]) {
    const ex = hx + s * eye_dx
    if (ctx["blink"]) {
      // 柔美笑眯弧（自然月牙眼与外挑睫羽）
      ARC(ex - scl_rx * 0.88, eye_y - scl_ry * 0.25, ex + scl_rx * 0.88, eye_y + scl_ry * 0.65,
        20, 160, u(0.022), THEME.ink)
      if (female) {
        CAP([ex + s * scl_rx * 0.82, eye_y + scl_ry * 0.08],
          [ex + s * scl_rx * 1.10, eye_y - scl_ry * 0.12], u(0.018), THEME.ink)
      }
    } else {
      // 巩膜白底（大眼舒展明亮）
      E(ex - scl_rx, eye_y - scl_ry * eye_k, ex + scl_rx, eye_y + scl_ry * eye_k, [255, 255, 255])
      const px = ex + gpx, py = eye_y + gpy
      const pup_rx = pup_r * 0.96
      const pup_ry = pup_r * 1.10
      // 瞳孔深色基底（占比饱满，彻底告别四白眼/死鱼眼）
      E(px - pup_rx, py - pup_ry, px + pup_rx, py + pup_ry, THEME.ink)
      // 下虹膜微光层（晶莹透亮，眼波流转）
      E(px - pup_rx * 0.76, py + pup_ry * 0.08, px + pup_rx * 0.76, py + pup_ry * 0.86,
        mix(THEME.ink, [115, 125, 155], 0.36))
      // 主高光（左上晶亮视线光点）
      E(px - pup_rx * 0.65, py - pup_ry * 0.72, px - pup_rx * 0.16, py - pup_ry * 0.20,
        [255, 255, 255])
      // 辅高光（右下环境微光点）
      E(px + pup_rx * 0.22, py + pup_ry * 0.25, px + pup_rx * 0.56, py + pup_ry * 0.60,
        [255, 255, 255])
      // 上眼睑自然眼褶描线（勾勒眼型轮廓）
      ARC(ex - scl_rx * 0.94, eye_y - scl_ry * eye_k * 1.04, ex + scl_rx * 0.94, eye_y + scl_ry * eye_k * 0.84,
        205, 335, u(0.016), THEME.ink)
      if (female) {
        // 灵动睫羽微挑（柔和贴合外眼角）
        CAP([ex + s * (scl_rx * 0.76), eye_y - scl_ry * eye_k * 0.62],
          [ex + s * (scl_rx * 1.14), eye_y - scl_ry * eye_k * 0.92], u(0.018), THEME.ink)
      }
    }
    const brow_y = brow_y0 - lift
    // 柔美秀气眉形（线条匀称有弧度，告别粗黑电工胶布）
    CAP([ex - s * u(0.054), brow_y - tilt], [ex + s * u(0.068), brow_y + tilt * 0.4], u(0.020),
      THEME.ink)
  }
  const mcx = hx, mcy = mouth_y
  const op = ctx["openness"]
  const WH = G.WH
  if (op > 0.07) {
    const mw = WH * (0.155 + 0.05 * op), mo = u(0.035) + u(0.10) * op
    PIE(mcx - mw, mcy - mo, mcx + mw, mcy + mo, 0, 180, THEME.mouth)
    const mt = mo * 0.45
    PIE(mcx - mw * 0.60, mcy + mo * 0.35 - mt, mcx + mw * 0.60, mcy + mo * 0.35 + mt, 0, 180,
      THEME.tongue)
    CAP([mcx - mw * 0.95, mcy], [mcx + mw * 0.95, mcy], u(0.015), THEME.ink)
  } else {
    // 微笑幅度适中匀称，带甜美唇角弧度（告别大嘴怪小丑弧）
    const sw = WH * (0.088 + 0.025 * mood.smile)
    if (mood.smile > 0.4) {
      ARC(mcx - sw, mcy - sw * 0.55, mcx + sw, mcy + sw * 0.70, 25, 155, u(0.020), THEME.ink)
    } else {
      CAP([mcx - u(0.040), mcy], [mcx + u(0.040), mcy + (tilt ? 3 : 0)], u(0.018), THEME.ink)
    }
  }
  if (p["energy"] === "lively") {
    for (const s of [-1, 1]) {
      // 腮红落在双眼正下方偏外侧（苹果肌处，元气透亮）
      const bx_c = hx + s * 0.290 * WH
      RR(bx_c - u(0.038), blush_y - u(0.016), bx_c + u(0.038), blush_y + u(0.016),
        8, THEME.blush)
    }
  }
}


/** 头部配饰（眼镜/顶戴墨镜/帽子/发夹/耳饰/耳机）+ face_cam 道具相机（最后画）。 */
function drawHeadGear(c: CharCtx): void {
  const { has, acc, ident, seed, t, u, hx, hy, rx, ry, eye_y, eye_dx, scl_rx, scl_ry,
    G, hdx, hdy, pose, d, TB, T, E, RR, CAP, ARC, PIE, sc, ss, pfy } = c
  for (const code of ["glasses_round", "glasses_thin", "glasses_square", "glasses_plastic"]) {
    if (has(code)) {
      const col = code === "glasses_plastic" ? THEME.glasses_plastic
        : code === "glasses_thin" ? THEME.glasses_thin : THEME.glasses_dark
      // 增大镜框尺寸，舒展大方地包裹大眼睛、睫毛与苹果肌（彻底告别小窄框压眼球）
      let wd: number, grx: number, gry: number, grad: number
      if (code === "glasses_thin") {
        wd = u(0.016); grx = scl_rx * 1.30; gry = scl_ry * 1.28; grad = u(0.042)
      } else if (code === "glasses_plastic") {
        wd = u(0.024); grx = scl_rx * 1.36; gry = scl_ry * 1.35; grad = u(0.065)
      } else if (code === "glasses_round") {
        wd = u(0.020); grx = scl_rx * 1.40; gry = scl_ry * 1.34; grad = 0
      } else {  // glasses_square
        wd = u(0.020); grx = scl_rx * 1.34; gry = scl_ry * 1.30; grad = u(0.046)
      }

      const bridge_y = eye_y - gry * 0.10
      for (const s of [-1, 1]) {
        const ex = hx + s * eye_dx
        if (code === "glasses_round") {
          d.ellipse(TB(ex - grx, eye_y - gry, ex + grx, eye_y + gry),
            { outline: col, width: Math.max(1, Math.trunc(wd * sc * ss)) })
        } else {
          d.roundedRectangle(TB(ex - grx, eye_y - gry, ex + grx, eye_y + gry),
            grad * sc * ss, { outline: col, width: Math.max(1, Math.trunc(wd * sc * ss)) })
        }
        const eax = hx + s * rx * 0.94
        CAP([ex + s * grx, eye_y - gry * 0.12], [eax + s * u(0.015), eye_y - gry * 0.24],
          wd * 0.75, col)  // 镜腿
      }
      CAP([hx - eye_dx + grx, bridge_y], [hx + eye_dx - grx, bridge_y],
        wd * 0.85, col)  // 鼻梁
      if (acc[code]["physics"] === "reflect") {  // 镜片反光随时间滑动（qa_motion 探针）
        const ggx = phys(seed, code, "reflect", t)[0]
        for (const s2 of [-1, 1]) {
          const ex2 = hx + s2 * eye_dx
          E(ex2 - grx * 0.65 + ggx, eye_y - gry * 0.60,
            ex2 - grx * 0.32 + ggx, eye_y - gry * 0.32, THEME.glint_soft)
        }
      }
    }
  }
  if (has("sunglasses_head")) {  // 顶戴：镜架倒扣在发顶，不遮眼（几何见 SUNGLASS_HEAD）
    const S = SUNGLASS_HEAD
    const sg = sunglassesHeadGeo(G, hdx, hdy)
    const sy0 = sg.sy0
    const ggx_h = pfy("sunglasses_head", "reflect")[0]
    for (const s of [-1, 1]) {
      const lcx = hx + s * S.dx
      RR(lcx - S.out_rx, sy0 - S.out_up, lcx + S.out_rx, sy0 + S.out_dn,
        S.rad, THEME.metal_dark)
      E(lcx - S.lens_rx, sy0 - S.lens_up, lcx + S.lens_rx, sy0 + S.lens_dn,
        THEME.lens)
      E(lcx - 20 + ggx_h, sy0 - 14, lcx - 4 + ggx_h, sy0 - 4, THEME.glint_blue)
    }
    CAP([hx - 28, sy0 - 14], [hx + 28, sy0 - 18], 7, THEME.metal_dark)
  }
  const hbdy = pfy("knit_hat", "bounce")[1]  // 帽子随步伐/点头轻弹（挂件物理；分镜 卡11）
  const cbdy = pfy("cap_backward", "bounce")[1]
  const shdy = pfy("sun_hat", "bounce")[1]
  if (has("knit_hat")) {
    PIE(hx - rx - 6, hy - ry - 16 + hbdy, hx + rx + 6, hy + ry * 0.17, 182, 358, ident)
    RR(hx - rx - 10, hy - ry * 0.46 + hbdy, hx + rx + 10, hy - ry * 0.24 + hbdy, 16, [255, 255, 255])
    E(hx - 26, hy - ry - 66 + hbdy, hx + 26, hy - ry - 14 + hbdy, [255, 255, 255])
  }
  if (has("cap_backward")) {
    PIE(hx - rx - 2, hy - ry - 8 + cbdy, hx + rx + 2, hy - ry * 0.10, 182, 358, ident)
    E(hx - rx * 1.42, hy - ry * 0.74 + cbdy, hx - rx * 0.20, hy - ry * 0.36 + cbdy, ident)
  }
  if (has("sun_hat")) {
    E(hx - rx - 52, hy - ry * 0.78 + shdy, hx + rx + 52, hy - ry * 0.32 + shdy, THEME.straw)
    PIE(hx - rx * 0.78, hy - ry - 24 + shdy, hx + rx * 0.78, hy + ry * 0.02, 182, 358, THEME.straw)
    E(hx - rx * 0.78, hy - ry * 0.54 + shdy, hx + rx * 0.78, hy - ry * 0.36 + shdy, ident)
  }
  if (has("headband_red")) {  // 红发带＋意大利三色旗 wink（分镜 卡23：红发带飘起）
    const gbdy = pfy("headband_red", "bounce")[1]
    ARC(hx - rx, hy - ry * 0.68 + gbdy, hx + rx, hy - ry * 0.14 + gbdy, 195, 345, 16, THEME.headband_red)
    for (let i = 0; i < THEME.it_flag.length; i++) {  // 右鬓角三色小条（绿白红；qa_char 探针）
      const flag_c = THEME.it_flag[i]!
      RR(hx + rx * 0.86 + i * 9, hy - ry * 0.52 + gbdy, hx + rx * 0.86 + i * 9 + 7, hy - ry * 0.24 + gbdy,
        2, flag_c)
    }
  }
  if (has("hairpin")) {
    CAP([hx + rx * 0.36, hy - ry * 0.80], [hx + rx * 0.64, hy - ry * 0.58], 12, ident)
  }
  if (has("hairpin_clear")) {
    CAP([hx + rx * 0.38, hy - ry * 0.74], [hx + rx * 0.68, hy - ry * 0.54], 10, THEME.hairpin_clear)
    if (acc["hairpin_clear"]["physics"] === "reflect") {  // 透明发夹一闪（分镜 卡27；qa_motion 探针）
      const hgx = phys(seed, "hairpin_clear", "reflect", t)[0]
      E(hx + rx * 0.50 - 4 + hgx * 0.6, hy - ry * 0.68, hx + rx * 0.50 + 4 + hgx * 0.6, hy - ry * 0.60,
        [255, 255, 255])
    }
  }
  if (has("earrings_hoop")) {
    const [hox, hoy] = pfy("earrings_hoop", "swing")
    for (const s of [-1, 1]) {
      ARC(hx + s * rx * 0.96 - 14 + hox, hy + ry * 0.38 + hoy, hx + s * rx * 0.96 + 14 + hox,
        hy + ry * 0.38 + 28 + hoy, 0, 360, 5, THEME.gold)
    }
  }
  if (has("jhumki")) {
    const [jhx, jhy] = pfy("jhumki", "swing")
    for (const s of [-1, 1]) {
      const ex2 = hx + s * rx * 0.97
      E(ex2 - 9 + jhx, hy + ry * 0.36 + jhy, ex2 + 9 + jhx, hy + ry * 0.36 + jhy + 18, THEME.gold)
    }
  }
  if (has("earrings_pearl")) {
    for (const s of [-1, 1]) {
      E(hx + s * rx * 0.97 - 9, hy + ry * 0.36, hx + s * rx * 0.97 + 9, hy + ry * 0.36 + 18,
        THEME.pearl)
      E(hx + s * rx * 0.97 - 4, hy + ry * 0.36 + 4, hx + s * rx * 0.97 + 1, hy + ry * 0.36 + 9,
        [255, 255, 255])  // 珍珠高光
    }
  }
  if (has("headphones_neck") || has("headphones_one_ear")) {
    const hpc = has("headphones_one_ear") ? "headphones_one_ear" : "headphones_neck"
    const hdy2 = pfy(hpc, "bounce")[1]
    ARC(hx - rx * 0.90, hy + ry * 0.52, hx + rx * 0.90, hy + ry * 1.35, 15, 165, 13, THEME.headphones)
    const sides = has("headphones_one_ear") ? [-1] : [-1, 1]
    for (const s of sides) {
      E(hx + s * rx * 0.95 - 24, hy + ry * 0.88 + hdy2, hx + s * rx * 0.95 + 24, hy + ry * 0.88 + 52 + hdy2,
        THEME.headphones)
      E(hx + s * rx * 0.95 - 12, hy + ry * 0.88 + 14 + hdy2, hx + s * rx * 0.95 + 12, hy + ry * 0.88 + 38 + hdy2,
        ident)
    }
  }

  // 手臂层已移至「颈与头」之前（衣服不得在人脸前面遮嘴）；face_cam 是举到脸前的道具相机，
  // 要的就是遮脸，故留在表情之后画。
  if (pose["face_cam"]) {
    RR(hx - u(0.20), hy - u(0.11), hx + u(0.20), hy + u(0.11), u(0.05), THEME.camera_body)
    E(hx - u(0.062), hy - u(0.056), hx + u(0.062), hy + u(0.056), THEME.lens_blue)
  }
}


/** 多邻国风格角色：无描边纯平涂、头身规格见 faceGeo()、大眼白+瞳孔双高光、
 * 胶囊眉、粗短四肢、圆润有机发型（双色高光）、耳朵/衣领/袖口细节。
 *
 * 阶段顺序 = 绘制顺序：背发 → 腿脚 → 躯干/挂件 → 手臂 → 颈/头/耳 → 前发 →
 * 胡须 → 表情 → 头部配饰 → face_cam。图层序纪律（衣不遮嘴）不变——袖子是
 * 「衣服层」，抬臂姿态会把袖子胶囊扫过人脸，故脸/嘴永远画在手臂之上。 */
export function drawCharacter(img: unknown, d: PilDraw, p: Persona, t: number, ctx: RigCtx): void {
  const c = new CharCtx(img, d, p, t, ctx)
  drawBackHair(c)
  drawLegsFeet(c)
  drawTorso(c)
  drawArms(c)
  drawNeckHead(c)
  drawFrontHair(c)
  drawBeard(c)
  drawFace(c)
  drawHeadGear(c)
}

// ---- 姿态库 ----

// 姿态实现注册表（姿势码 → 参数/分支函数），与 scenes.SCENES 同构的单一事实源：
// POSE_CODES 从本表现取派生（不另抄——纪律 7，注册表与实现永不脱节）。
// 分支函数签名 (u, t, p) → P（姿态参数 dict）；映射值与 Python 版逐字相同。
const _POSES: Record<string, PoseFn> = {}

type PoseFn = (u: number, t: number, p: Persona) => Record<string, any>

function _pose(name: string, fn: PoseFn): void {
  _POSES[name] = fn
}


_pose("wave", (_u, _t, _p) => ({ armR: [138, 26 + 26 * Math.sin(_t * 11), "open"] }))

// 原与 wave 同支：仅肩角差一档（旧 a1 = 138 if code == "wave" else 146）
_pose("ciao_wave", (_u, _t, _p) => ({ armR: [146, 26 + 26 * Math.sin(_t * 11), "open"] }))

_pose("thumbs_up", () => ({ armR: [150, 18, "thumb"] }))

_pose("palm_open", () => ({ armR: [78, 28, "open"] }))

_pose("point", () => ({ armR: [96, 6, "index"] }))

_pose("nod", (u, _t, _p) => ({
  head_dy: 8 * Math.sin(Math.min(u, 1) * Math.PI * 2) * (1 - Math.min(u, 1)),
}))

_pose("shrug", () => ({ armL: [52, 66, "open"], armR: [52, 66, "open"], yoff: -6, head_dy: -3 }))

_pose("mini_jump", (u, _t, p) => {
  const P: Record<string, any> = {}
  // 顺滑单次起跳抛物线：0..0.15 蓄力下沉，0.15..0.85 滞空抛物线，0.85..1.0 落地缓冲
  if (u < 0.15) {
    const c = Math.sin((u / 0.15) * Math.PI)
    P["yoff"] = 5.0 * c
    P["squash"] = 0.03 * c
  } else if (u < 0.85) {
    const ju = (u - 0.15) / 0.70
    const arc_ = Math.sin(ju * Math.PI)
    P["yoff"] = -arc_ * jumpHeight(p) * 0.85
    P["squash"] = -0.04 * Math.sin(ju * Math.PI * 2)
  } else {
    const c = Math.sin(((u - 0.85) / 0.15) * Math.PI)
    P["yoff"] = 4.0 * c
    P["squash"] = 0.02 * c
  }
  P["armL"] = [92, 28, "open"]
  P["armR"] = [92, 28, "open"]
  return P
})

_pose("jump_celebrate", (u, _t, p) => {  // 欢跃庆祝：蓄力舒展升空与柔和落地（告别一蹦一蹦）
  const P: Record<string, any> = {}
  if (u < 0.15) {
    const c = Math.sin((u / 0.15) * Math.PI)
    P["yoff"] = 6.0 * c
    P["squash"] = 0.04 * c
    P["armL"] = [90, 20, "open"]
    P["armR"] = [90, 20, "open"]
  } else if (u < 0.85) {
    const ju = (u - 0.15) / 0.70
    const air = Math.sin(ju * Math.PI)
    P["yoff"] = -air * jumpHeight(p) * 1.05
    P["squash"] = -0.05 * Math.sin(ju * Math.PI * 2)
    P["armL"] = [148 - 10 * air, 18, "open"]
    P["armR"] = [148 - 10 * air, 18, "open"]
    P["head_dy"] = -4 * air
  } else {
    const c = Math.sin(((u - 0.85) / 0.15) * Math.PI)
    P["yoff"] = 5.0 * c
    P["squash"] = 0.03 * c
    P["armL"] = [110, 20, "open"]
    P["armR"] = [110, 20, "open"]
  }
  return P
})

_pose("run_out", (u, t, _p) => ({
  xoff: 1500 * easeOutCubic(u),
  legL: 28 * Math.sin(t * 16),
  legR: -28 * Math.sin(t * 16),
  armL: [40 + 20 * Math.sin(t * 16), 40, "open"],
  armR: [40 - 20 * Math.sin(t * 16), 40, "open"],
  yoff: -4.0 * (1 - Math.cos(t * 16)),
}))

_pose("turn_freeze", (u, _t, _p) => ({
  xoff: -34 * u,
  head_dx: -12 * u,
  armR: [58, 122, "open"],
}))

_pose("come_along", (_u, t, _p) => ({
  armR: [86, 24 + 14 * Math.sin(t * 7), "open"],
  head_dx: 4,
}))

_pose("kick", (u, _t, _p) => ({
  legR: 38 * Math.sin(Math.min(u * 1.4, 1) * Math.PI),
  skate_kick: Math.sin(Math.min(u * 1.4, 1) * Math.PI),
  armL: [120, 30, "open"],
}))

_pose("snap", (u, _t, _p) => {
  const P: Record<string, any> = { armR: [42, 112, "fist"] }
  if (0.3 < u && u < 0.75) P["hand_prop"] = "sparkle"
  return P
})

_pose("camera_snap", (u, _t, _p) => {
  const P: Record<string, any> = {
    armL: [118, 62, "open"],
    armR: [118, 62, "open"],
    face_cam: true,
  }
  if (0.35 < u && u < 0.7) P["hand_prop"] = "flash"
  return P
})

_pose("chest_pat", (_u, t, _p) => ({ armR: [32, 116 + 14 * Math.sin(t * 8), "open"] }))

_pose("index_wait", () => ({ armR: [142, 22, "index"] }))

_pose("finger_count", () => ({ armR: [122, 32, "index"] }))

_pose("both_hands", () => ({ armL: [104, 18, "open"], armR: [104, 18, "open"] }))

_pose("beads_ponder", () => ({
  armR: [46, 100, "open", "beads"],
  hand_prop: null,
  head_dx: 7,
  head_dy: 4,
}))

_pose("cap_tap", (_u, t, _p) => ({ armR: [148, 40 + 12 * Math.sin(t * 10), "open"] }))

_pose("scratch_head", (_u, t, _p) => ({ armR: [132, 74 + 12 * Math.sin(t * 9), "open"] }))

_pose("hand_shoot", () => ({ armR: [176, 2, "open"] }))

_pose("brow_raise", (u, _t, _p) => ({
  brow_lift_extra: 10 * Math.sin(Math.min(u, 1) * Math.PI),
}))

_pose("head_tilt", () => ({ head_dx: 8 }))

_pose("breath", (u, _t, _p) => ({
  squash: 0.035 * Math.sin(Math.min(u, 1) * Math.PI),
  yoff: -8 * Math.sin(Math.min(u, 1) * Math.PI),
  armL: [24, 14, "open"],
  armR: [24, 14, "open"],
}))

_pose("planner_snap", (u, _t, _p) => {
  const P: Record<string, any> = {
    armL: [36, 108, "open"],
    armR: [36, 108, "open"],
  }
  if (0.25 < u && u < 0.6) P["hand_prop"] = "sparkle"
  return P
})

_pose("clap", () => ({ armL: [44, 96, "open"], armR: [44, 96, "open"] }))

_pose("fist", () => ({ armR: [46, 114, "fist"] }))

_pose("bottle_raise", () => ({ armR: [64, 92, "open", "bottle"] }))

_pose("deadpan_nod", (u, _t, _p) => ({  // 卡20：面无表情点头（数据触发两次＝分镜"只两次"）
  head_dy: 10 * Math.sin(Math.min(u, 1) * Math.PI * 2) * (1 - 0.4 * Math.min(u, 1)),
}))

_pose("twirl", (u, _t, _p) => ({  // 卡05/09 入场旋转：水平压缩翻转读作转身
  xscale: 0.16 + 0.84 * Math.abs(Math.cos(Math.min(u, 1) * Math.PI * 2)),
  yoff: -14 * Math.abs(Math.sin(Math.min(u, 1) * Math.PI * 2)),
  armL: [96, 26, "open"],
  armR: [96, 26, "open"],
}))

_pose("lean_in", () => ({  // 卡25：探身取景
  head_dx: 8,
  head_dy: 5,
  armR: [104, 38, "open"],
}))

_pose("pocket_sway", (u, _t, _p) => ({  // 卡24：插兜晃身
  armL: [14, 10, "open"],
  armR: [14, 10, "open"],
  head_dx: 6 * Math.sin(Math.min(u, 1) * Math.PI * 2),
}))

_pose("head_tilt_smile", () => ({  // 卡27：侧头一笑定格
  head_dx: 13,
  head_dy: 2,
  armR: [58, 30, "open"],
}))

_pose("thumbs_run", (u, t, _p) => {  // 卡28：thumbs-up 后招手小跑出画
  const P: Record<string, any> = {}
  if (u < 0.45) {
    P["armR"] = [150, 18, "thumb"]
    P["armL"] = [60, 30, "open"]
  } else {
    P["xoff"] = 1500 * easeOutCubic((u - 0.45) / 0.55)
    P["legL"] = 28 * Math.sin(t * 16)
    P["legR"] = -28 * Math.sin(t * 16)
    P["armL"] = [40 + 20 * Math.sin(t * 16), 40, "open"]
    P["armR"] = [140, 26 + 26 * Math.sin(t * 11), "open"]
    P["yoff"] = -6 * Math.abs(Math.sin(t * 16))
  }
  return P
})

_pose("shoot_run", (u, t, _p) => {  // 卡22：投篮手势后追球跑出画
  const P: Record<string, any> = {}
  if (u < 0.5) {
    P["armL"] = [128, 60, "open"]
    P["armR"] = [128, 60, "open"]
    P["squash"] = 0.04 * Math.sin(Math.min(u / 0.5, 1) * Math.PI)
  } else {
    P["xoff"] = 1500 * easeOutCubic((u - 0.5) / 0.5)
    P["legL"] = 28 * Math.sin(t * 16)
    P["legR"] = -28 * Math.sin(t * 16)
    P["armL"] = [40 + 20 * Math.sin(t * 16), 40, "open"]
    P["armR"] = [40 - 20 * Math.sin(t * 16), 40, "open"]
    P["yoff"] = -6 * Math.abs(Math.sin(t * 16))
  }
  return P
})


// poseFor 已实现的姿态码全集（场景线据此校验剧本标注）——现取注册表派生，不另抄
export const POSE_CODES: ReadonlySet<string> = new Set(Object.keys(_POSES))


/** 返回姿态参数：armL/armR=(a1,a2,hand[,prop]), legL/legR, head_dx/dy, squash, yoff, extras。
 * 未知姿态码返回空 dict（与旧 elif 链落空分支的行为一致）。 */
export function poseFor(code: string, u: number, t: number, p: Persona): Record<string, any> {
  const fn = _POSES[code]
  return fn ? fn(u, t, p) : {}
}


/** 词级时间轴驱动的口型开度：命中词取种子化幅值，词尾 0.13s 衰减，词前 0.05s 预备。 */
export function opennessAt(lines: any[], t: number, seed = ""): number {
  let op = 0.0
  for (const line of lines) {
    if (t < line["start"] - 0.05 || t > line["start"] + line["dur"] + 0.2) continue
    for (const w of line["words"]) {
      // 种子命名空间（不变量⑦）；round(s,2) 过 pyFloat——Python str(2.0)="2.0"，
      // JS `${2}`="2"，差一个 ".0" 种子就换空间（实测坑）。
      const amp = 0.55 + 0.45 * rnd(`${seed}:open:${w["w"]}:${pyFloat(roundHalfEven(w["s"], 2))}`)
      if (w["s"] <= t && t <= w["e"]) op = Math.max(op, amp)
      else if (w["e"] < t && t < w["e"] + 0.13) op = Math.max(op, amp * (1 - (t - w["e"]) / 0.13))
      else if (t < w["s"] && w["s"] < t + 0.05) op = Math.max(op, amp * 0.7)
    }
  }
  return op
}
