// render_act_frames.ts — 评书幕帧渲染器（storyteller-video 的导演层实现）
// （skills/storyteller-video/scripts/render_act_frames.py 的 TS 归流）。
//
// 舞台模型（茶馆书场，一个连贯空间，不是图层拼贴）：
//   墙面（prerenderBg 渐变 + 幕 scene 注册表道具，identity 调色）
//     → 挂木匾（幕名：章 + 回目）→ 说书人立绘半身近景（rig.drawCharacter，
//     幕 pose/mood；可见身高 ≈53%）站在案后 → 说书案（案沿遮住腰下）→
//     案上摊开的唱词书卷（卡拉OK文字长在卷面上）→ 镜头变换最后作用于整幅合成。
//
// 归流决定：
// - 人物 / 舞台绘制消费 @feuille/core 唯一实现：rig.drawCharacter / poseFor /
//   POSE_CODES / SCENE / mix / hexc、scenes.prerenderBg / DrawScaled、
//   data.storytellers——包内零重复；
// - ffprobe 时长 = core audio.probeDuration（消掉脚本内 ffprobe 拷贝）；
//   Python round() 银行家舍入 = core roundHalfEven（不自造第二份）；
// - ffmpeg 只剩醒木合成一处（platform 解析顺序照 Python：先 ffmpeg 后
//   浏览器校验；import 期零依赖）；
// - 字卡截图走 Edge headless（参数组与 Python 版同集：headless=new /
//   disable-gpu / hide-scrollbars / force-device-scale-factor=1 / window-size /
//   screenshot / virtual-time-budget，不带 user-data-dir）；
// - matte_unpremultiply（黑底字卡按色表分解）是本产线专属逻辑，留在包内；
// - 帧数口径与 karaoke build 一致：preroll + Σ词段 + tail + done；
// - 错误信息里的 TTS 前置指引随 P5-7d 改指 `feuille karaoke tts`
//   （Python 版写的是 karaoke-video 的 gen_tts.py——归流后命令名变了，所指没变）。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

import { createCanvas } from '@napi-rs/canvas'
import sharp from 'sharp'

import {
  FeuilleError, roundHalfEven, audio, createPilDraw, data, platform, rig, scenes,
} from '@feuille/core'
import type { PilDraw, RGB, RGBA } from '@feuille/core'

// ---- 舞台几何（单一事实源：绘制与字卡 HTML 坐标由同一份常量注入）----
//
// 几何**按画幅分开**，不是把竖版缩一缩：两个画幅的宽高比不同，缩不出来。
// 竖版 1080×1920 的数值是历史实况（既有成片逐像素消费），一个都不许动；
// 横版 1920×1080 另立一套（下方 LANDSCAPE），同一套空间模型按宽比重排。
export type Rect = readonly [number, number, number, number]

export interface StageGeo {
  beam: Rect            // 顶梁
  plaque: Rect          // 木匾（幕名）
  ptext: Rect           // 匾内文字区（HTML 同源）
  panel: Rect           // 台口护墙板（挡低处道具）
  slab: Rect            // 案沿（说书人双手搭在案沿上）
  skirt: Rect           // 案身前脸（书卷后面）
  roll_l: Rect          // 书卷左卷尾
  roll_r: Rect          // 书卷右卷尾
  paper: Rect           // 案上摊开的唱词书卷
  ktext: Rect           // 卷面唱词文字区（HTML 同源）
  quote: Rect           // 卷面原文摘录行（有 quote 才有）
}

/** 案沿条上的道具与人物接触影（同一套坐标，竖横各一份）。 */
export interface StageProps {
  contact: Rect                     // 双手搭案沿的接触影
  gavelShadow: Rect
  gavel: Rect
  gavelTop: Rect
  fanShadow: Rect
  fanHandle: Rect
  fanPaper: Rect
  fanRib: { from: number; to: number; step: number; y0: number; y1: number }
}

/** 卡面字号（匾与卷面）。center = 卷面文字竖直居中（横版卷面宽而矮，不居中会悬在顶边）。 */
export interface StageCard {
  ch: number
  chTrack: number
  sub: number
  subTrack: number
  ktext: number
  ktextLh: number
  quoteSize: number
  center: boolean
}

/** 一套完整舞台：画布尺寸 + 几何 + 站位 + 道具 + 卡面字号。 */
export interface Stage {
  w: number
  h: number
  geo: StageGeo
  actor: { x: number; y: number; s: number }
  props: StageProps
  card: StageCard
}

export const GEO: StageGeo = {
  beam: [0, 0, 1080, 90],            // 顶梁
  plaque: [330, 300, 750, 470],      // 木匾（幕名）
  ptext: [340, 312, 740, 462],       // 匾内文字区（HTML 同源）
  panel: [0, 1450, 1080, 1540],      // 台口护墙板（挡低处道具）
  slab: [0, 1540, 1080, 1630],       // 案沿（说书人双手搭在案沿上）
  skirt: [0, 1630, 1080, 1920],      // 案身前脸（书卷后面）
  roll_l: [30, 1620, 78, 1915],      // 书卷左卷尾
  roll_r: [1002, 1620, 1050, 1915], // 书卷右卷尾
  paper: [60, 1630, 1020, 1905],    // 案上摊开的唱词书卷
  ktext: [90, 1645, 990, 1872],     // 卷面唱词文字区（HTML 同源）
  quote: [100, 1878, 980, 1900],    // 卷面原文摘录行（有 quote 才有）
}

// 说书人站位：face_geo 原生 ground=1700、头顶≈962（wide 脸型）。
// scale 1.75 + yoff 180 + xoff −135（中轴 405）→ 头顶（含发）≈521、
// 双手≈1567 恰在案沿 1540 之上；可见身高 521→1540 ≈ 53%（>45%）。
export const ACTOR_X = -135.0, ACTOR_Y = 180.0, ACTOR_S = 1.75

const PROPS_PORTRAIT: StageProps = {
  contact: [180, 1544, 640, 1566],
  gavelShadow: [146, 1598, 252, 1614],
  gavel: [150, 1562, 242, 1600],
  gavelTop: [154, 1566, 238, 1580],
  fanShadow: [838, 1602, 964, 1620],
  fanHandle: [840, 1574, 862, 1594],
  fanPaper: [846, 1565, 950, 1602],
  fanRib: { from: 866, to: 946, step: 12, y0: 1570, y1: 1598 },
}

const CARD_PORTRAIT: StageCard = {
  ch: 52, chTrack: 10, sub: 28, subTrack: 12,
  ktext: 36, ktextLh: 1.6, quoteSize: 20, center: false,
}

export const PORTRAIT_STAGE: Stage = {
  w: 1080, h: 1920,
  geo: GEO,
  actor: { x: ACTOR_X, y: ACTOR_Y, s: ACTOR_S },
  props: PROPS_PORTRAIT,
  card: CARD_PORTRAIT,
}

// ---- 横版 1920×1080 ----
// 宽高比 16:9 与 9:16 差太远，缩不出来，只能重排：卷面横铺（1752 宽 → 36px
// 一行 48 字、约 4 行容量），匾缩窄上移，说书人降到 0.78 倍、中轴落在画面
// 正中（竖版中轴 405 是偏左的，横版居中才稳）。
//
// 站位换算（rig 原生：头顶含发≈923、双手≈1521、ground=1700）：
//   y = −870.4 → 双手 = −870.4 + 1700 + 0.78·(1521−1700) ≈ 690（落进案沿 664–728 条内）
//   头顶 = −870.4 + 1700 + 0.78·(923−1700) ≈ 224（匾底 192 之下留 32px 气口）
//   x = 420 → 中轴 = 540 + 420 = 960（画面正中）
//   可见身高 224→690 = 466px ≈ 43%（横版低于竖版 53%，因为宽画幅要先让出卷面）
export const LANDSCAPE_STAGE: Stage = {
  w: 1920,
  h: 1080,
  geo: {
    beam: [0, 0, 1920, 54],
    plaque: [700, 44, 1220, 192],
    ptext: [708, 52, 1212, 184],
    panel: [0, 600, 1920, 664],
    slab: [0, 664, 1920, 728],
    skirt: [0, 728, 1920, 1080],
    roll_l: [8, 716, 60, 1052],
    roll_r: [1860, 716, 1912, 1052],
    paper: [44, 728, 1876, 1044],
    ktext: [84, 742, 1836, 992],
    quote: [90, 1000, 1830, 1036],
  },
  actor: { x: 420.0, y: -870.4, s: 0.78 },
  props: {
    contact: [700, 668, 1220, 686],
    gavelShadow: [196, 700, 286, 714],
    gavel: [200, 672, 282, 704],
    gavelTop: [204, 676, 278, 686],
    fanShadow: [1636, 706, 1740, 720],
    fanHandle: [1640, 686, 1658, 700],
    fanPaper: [1646, 672, 1734, 706],
    fanRib: { from: 1660, to: 1726, step: 10, y0: 676, y1: 702 },
  },
  card: {
    ch: 52, chTrack: 10, sub: 28, subTrack: 12,
    ktext: 36, ktextLh: 1.6, quoteSize: 22, center: true,
  },
}

/** 画幅 → 舞台。只定义了两套（竖 1080×1920 / 横 1920×1080），别的画幅
 * 直接判死而不是悄悄退化成竖版几何——退化的症状是「画面全错但退出 0」。 */
export function stageGeometry(w: number, h: number): Stage {
  if (w === PORTRAIT_STAGE.w && h === PORTRAIT_STAGE.h) return PORTRAIT_STAGE
  if (w === LANDSCAPE_STAGE.w && h === LANDSCAPE_STAGE.h) return LANDSCAPE_STAGE
  throw new FeuilleError(
    `没有 ${w}×${h} 的舞台几何：只定义了 1080×1920（竖）与 1920×1080（横）。`
    + `新画幅要在 render_act_frames 里补一套几何，不能靠缩竖版。`)
}

/** 背景落版方式：rig 语义画布（1080×1920）怎么摆进当前画幅。
 *
 * 竖版返回 undefined（原样，**逐像素不变**——竖版成片已交付，一个像素都不许动）。
 *
 * 横版 1920×1080 的墙带只有 600 高、宽 1920，rig 墙面是 1080×1450，比例差 3.16 倍：
 * 「不变形」「不裁切」「铺满宽度」三者只能取二。这里取**不变形 + 不裁切**——
 * 道具按竖版原尺寸摆在中段 1080 宽，两侧各 420 像素由渐变自然延伸（渐变逐行
 * 恒定，横向延伸没有痕迹）。
 *
 * 另两种做法的实测代价（墙带 0–600 内可见道具占比，a02/a05）：
 * - 整墙等比缩到护墙板线（41%）= 0.72% / 1.92%：道具糊进渐变，等于空墙；
 * - 横向铺满、放大 1.78× 取局部 = 8.69% / 39.75%：道具被放大且上下切边。
 */
export function bgLayoutFor(stage: Stage): scenes.BgLayout | undefined {
  if (stage === PORTRAIT_STAGE) return undefined
  return { w: stage.w, h: stage.h, dx: (stage.w - rig.W) / 2, dy: -BG_NATIVE_TOP }
}

/** 横版取景窗上沿（rig 行）。560 是量出来的：13 幕道具带并集 = rig 600–1600
 * （逐行偏差剖面：0–600 是纯渐变），窗口正好 1080 行，560–1640 上下各留 40 行
 * 余量，道具一个都不切。 */
const BG_NATIVE_TOP = 560

// 字卡文字实色（与 matteUnpremultiply 色表一致，勿单边改）。
// dim 态用实色暗字而不用 CSS opacity：字卡页是纯黑底，半透明墨字会被
// 黑底压暗（obs = a·墨），matte 无法与「深色文字」区分——dim 与 sung 分不清。
export const INK: RGB = [44, 36, 24]
export const GOLD: RGB = [184, 134, 11]
export const MUT: RGB = [138, 124, 98]
export const DIM: RGB = [196, 188, 170]
export const VOWEL: RGB = [176, 85, 46]
export const PAPER: RGB = [242, 234, 216]

const PALETTE: readonly RGB[] = [INK, GOLD, MUT, DIM, VOWEL, PAPER]

type Cfg = Record<string, any>

/** 帧序 → (scale, xoff, yoff)。kind ∈ push|pull|pan_l|pan_r|static。
 *
 * ease = smoothstep（与 rig 同式，Ken Burns 不抖）；pan 位移 = 画布宽 4% 行程。
 * 画布满幅纪律：行程 <1 的端点镜像到 ≥1（zoom-out 语义 = 主体变小，画布不露底）。 */
export function shotTransform(
  shot: Cfg | undefined,
  nFrames: number,
  fps: number,
  w = 1080,
): Array<[number, number, number]> {
  const kind = (shot ?? {})['kind'] ?? 'static'
  let s0 = Number((shot ?? {})['start'] ?? 1.0)
  let s1 = Number((shot ?? {})['end'] ?? 1.0)
  if (kind === 'pull') { const t = s0; s0 = s1; s1 = t }
  if (kind === 'static') { s0 = 1.0; s1 = 1.0 }
  if (s0 < 1.0 || s1 < 1.0) {
    const lo = Math.min(s0, s1)
    s0 = s0 + (1 - lo) * 2
    s1 = s1 + (1 - lo) * 2
  }
  const out: Array<[number, number, number]> = []
  for (let k = 0; k < nFrames; k++) {
    const u = k / Math.max(1, nFrames - 1)
    const e = u * u * (3 - 2 * u)
    const scale = s0 + (s1 - s0) * e
    let xoff = 0.0
    if (kind === 'pan_l') xoff = 0.04 * w * (1 - 2 * e)
    else if (kind === 'pan_r') xoff = -0.04 * w * (1 - 2 * e)
    out.push([scale, xoff, 0.0])
  }
  return out
}

/** 醒木声：60ms 低频正弦（150Hz→70Hz 扫频）× 指数衰减 + 3ms 噪声瞬态。
 *
 * 纯库内合成器（sine/anoisesrc 滤波组，无额度、无外部依赖）。峰值 ≈ −3 dBFS。
 * fps 形参 Python 版就未参与滤镜图——按原样镜像保留（删除另立议题）。 */
export function synthGavel(path: string, fps: number, ffmpegBin: string): void {
  void fps
  const flt = 'sine=frequency=150:duration=0.06[s1];'
    + 'sine=frequency=70:duration=0.06[s2];'
    + '[s1][s2]amix=inputs=2:normalize=0[drone];'
    + 'anoisesrc=color=brown:duration=0.004:amplitude=0.9[nz];'
    + '[nz]adelay=0|0,apad=whole_dur=0.06[trans];'
    + '[drone][trans]amix=inputs=2:normalize=0,'
    + 'afade=t=out:st=0.004:d=0.056:curve=exp,'
    + 'volume=0.7,apad=whole_dur=0.25'
  const r = spawnSync(ffmpegBin, ['-y', '-loglevel', 'error',
    '-filter_complex', flt, '-ar', '48000', '-ac', '1', path],
    { encoding: 'utf8' })
  if (r.error || r.status !== 0) {
    throw new FeuilleError(`FAILED: ffmpeg ${path}\n${r.error?.message ?? (r.stderr ?? '').slice(-2000)}`)
  }
}

/** 近纯白像素占比（min(R,G,B) >= 250；与 karaoke build_video 白页哨兵同口径）。 */
async function whiteRatio(png: string, w: number, h: number): Promise<number> {
  const { data } = await sharp(png).removeAlpha().resize(w, h).raw()
    .toBuffer({ resolveWithObject: true })
  let white = 0
  for (let i = 0; i < data.length; i += 3) {
    if (data[i]! >= 250 && data[i + 1]! >= 250 && data[i + 2]! >= 250) white++
  }
  return white / (w * h)
}

/** 字卡层截图（Edge headless；参数组与 Python 版同集，不带 user-data-dir）。 */
export async function renderWordCard(
  htmlPath: string, png: string, w: number, h: number,
  query: string, browser: string,
): Promise<void> {
  const url = pathToFileURL(resolve(htmlPath)).href + query
  const r = spawnSync(browser, ['--headless=new', '--disable-gpu',
    ...platform.HEADLESS_FLAGS,
    '--hide-scrollbars', '--force-device-scale-factor=1',
    `--window-size=${w},${h}`, `--screenshot=${png}`,
    '--virtual-time-budget=10000', url],
    { encoding: 'utf8', timeout: 180 * 1000, stdio: ['ignore', 'ignore', 'ignore'] })
  if (r.error || r.status !== 0) {
    throw new FeuilleError(`FAILED: ${browser} --screenshot=${png}\n${r.error?.message ?? ''}`)
  }
  if (!existsSync(png)) {
    // 退出 0 但没出图 = 被已开着的桌面浏览器 singleton 锁抢走（singleton 移交）。
    // 这条消息要能直接指到处置动作，否则报出来只是个没有下一步的 FAILED。
    throw new FeuilleError(
      `浏览器退出 0 但没有写出 ${png}——大概率被已开着的桌面浏览器抢占`
      + `（singleton 移交）。关掉桌面浏览器后重试。\nURL was: ${url}`)
  }
  // 白页哨兵（AGENTS.md：截图后跑白页哨兵）：文件存在 ≠ 渲对了。file:// URL
  // 写错时 headless 抓的是一张近纯白的错误页，尺寸合法、有文件、exit 0——
  // 没有这道判据，它会一路静默流进字卡视频。
  if (await whiteRatio(png, 64, 36) > 0.9) {
    throw new FeuilleError(
      `BLANK RENDER (页面没渲出来？): ${png}\nURL was: ${url}`)
  }
}

export interface RgbaRaw {
  data: Buffer
  width: number
  height: number
}

/** 任意 PNG → 3 通道 raw（sharp 的 ensureAlpha+removeAlpha 会被优化掉、
 * raw 实返 4 通道——按 info.channels 步长抽取，勿按 3 通道直读）。 */
async function rgbRaw(png: string): Promise<{ data: Buffer; width: number; height: number }> {
  const { data, info } = await sharp(png).raw().toBuffer({ resolveWithObject: true })
  if (info.channels === 3) return { data, width: info.width, height: info.height }
  const out = Buffer.alloc(info.width * info.height * 3)
  for (let i = 0, j = 0; i < info.width * info.height; i++, j += 3) {
    const s = i * info.channels
    out[j] = data[s]!
    out[j + 1] = data[s + 1]!
    out[j + 2] = data[s + 2]!
  }
  return { data, width: info.width, height: info.height }
}

/** 黑底字卡 → RGBA 文字层（字卡页全部实色已知，按色表分解 matte）。
 *
 * headless screenshot 永远输出不透明图（transparent body 会被填底），
 * 所以字卡页用纯黑底渲染：文字全部实色（含 dim 态——opacity 会与黑底
 * 混色、matte 分不清深浅），每像素必是色表色之一，距色表色过远（≈黑底）
 * 视为透明，其余 alpha = 255 − 最近色距。 */
export async function matteUnpremultiply(png: string): Promise<RgbaRaw> {
  const { data, width, height } = await rgbRaw(png)
  const out = Buffer.alloc(width * height * 4)
  for (let i = 0; i < width * height; i++) {
    const r = data[i * 3]!, g = data[i * 3 + 1]!, b = data[i * 3 + 2]!
    let best = 0, bd = Infinity
    for (let p = 0; p < PALETTE.length; p++) {
      const c = PALETTE[p]!
      const dr = r - c[0], dg = g - c[1], db = b - c[2]
      const d = Math.sqrt(dr * dr + dg * dg + db * db)
      if (d < bd) { bd = d; best = p }
    }
    let alpha = Math.min(255, Math.max(0, 255.0 - bd))   // Buffer 赋值截断 = astype(uint8)
    if (Math.max(r, g, b) < 20) alpha = 0                 // 纯黑基底 = 透明
    const c = PALETTE[best]!
    out[i * 4] = c[0]
    out[i * 4 + 1] = c[1]
    out[i * 4 + 2] = c[2]
    out[i * 4 + 3] = alpha
  }
  return { data: out, width, height }
}

/** Python html.escape 的镜像（quote=True 口径：&, <, >, ", '）。 */
const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#x27;')

/** 自生成字卡页：黑底 + 每幕一节（匾文 + 卷面唱词），绝对定位坐标与
 * 舞台几何同源（GEO 注入）。按词序切开正文：与 token 文本逐段匹配，
 * token 之间的字符（标点/空白）一律 .pun（常暗，充当分隔）。
 *
 * 状态契约不变：?lang=zh-<act>&state=N——state<0 全 dim；0<N<len 前 N 个
 * token 亮（最新一个金色 .cur）；N≥len 全亮。字卡只出文字层，匾/卷/案等
 * 形状由舞台绘制。字体用系统楷体（评书面相），fonts.css 仍注入（字符集
 * 子集化的门留着）但 font-family 不引用 OBS SC。 */
export function buildCardHtml(
  cardActs: Array<[Cfg, string, Array<{ text: string; start: number }>]>,
  fontsCss: string,
  stage: Stage = PORTRAIT_STAGE,
): string {
  const C = stage.card
  const sheetCss = C.center
    ? 'display:flex;align-items:center;'
    : ''
  const ktextCss = C.center ? 'width:100%;' : ''
  const tmpl = `<!doctype html><html><head><meta charset="utf-8"><style>
__FONTS__
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:${stage.w}px; height:${stage.h}px; background:#000;
  font-family:'Kaiti SC','STKaiti','Songti SC',serif; }
section.act { display:none; }
section.act.on { display:block; }
.plaque { position:absolute; left:{ptx}px; top:{pty}px; width:{ptw}px; height:{pth}px;
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; }
.plaque .ch { font-size:${C.ch}px; font-weight:700; color:#2c2418; letter-spacing:${C.chTrack}px; }
.plaque .sub { font-size:${C.sub}px; color:#b8860b; letter-spacing:${C.subTrack}px; }
.sheet { position:absolute; left:{ktx}px; top:{kty}px; width:{ktw}px; height:{kth}px;
  overflow:hidden; ${sheetCss}}
.ktext { font-size:${C.ktext}px; line-height:${C.ktextLh}; color:#2c2418; ${ktextCss}
  text-align:justify; text-justify:inter-ideograph; }
.ktext .tok.dim, .ktext .pun { color:#c4bcaa; }
.ktext .tok.sung { color:#2c2418; }
.ktext .tok.vow.sung { color:#b0552e; }
.ktext .tok.cur, .ktext .tok.vow.cur { color:#b8860b; }
.quote { position:absolute; left:{qtx}px; top:{qty}px; width:{qtw}px; height:{qth}px;
  font-size:${C.quoteSize}px; color:#8a7c62; text-align:center; }
</style></head><body>
__SECTIONS__
<script>
(function () {
  var q = new URLSearchParams(location.search);
  var lang = q.get('lang') || '';
  var state = parseInt(q.get('state') || '-1', 10);
  var sec = document.getElementById('s-' + lang);
  if (!sec) return;
  sec.classList.add('on');
  var kt = sec.querySelector('.ktext');
  // 自适应：正文超长时逐 2px 缩字号装进卷面（只依赖文本，逐状态确定）
  var maxFs = ${C.ktext};
  for (var fs = maxFs; fs > 22 && kt.scrollHeight > kt.clientHeight; fs -= 2)
    kt.style.fontSize = fs + 'px';
  var n = parseInt(sec.dataset.n || '0', 10);
  sec.querySelectorAll('.tok').forEach(function (el) {
    var i = parseInt(el.dataset.i || '0', 10);
    el.classList.remove('dim', 'sung', 'cur');
    if (isNaN(state) || state < 0) el.classList.add('dim');
    else if (state >= n) el.classList.add('sung');
    else if (i < state) el.classList.add(i === state - 1 ? 'cur' : 'sung');
  });
})();
</script></body></html>
`
  const px = (k: keyof StageGeo) => {
    const [x0, y0, x1, y1] = stage.geo[k]
    return [String(x0), String(y0), String(x1 - x0), String(y1 - y0)] as const
  }
  const [ptx, pty, ptw, pth] = px('ptext')
  const [ktx, kty, ktw, kth] = px('ktext')
  const [qtx, qty, qtw, qth] = px('quote')

  const bodySecs: string[] = []
  for (const [act, text, toks] of cardActs) {
    const vow = new Set<string>((act['vowel'] || []) as string[])
    const spans: string[] = []
    let i = 0, pos = 0
    while (pos < text.length) {
      if (i < toks.length && text.startsWith(toks[i]!['text'], pos)) {
        const cls = vow.has(toks[i]!['text']) ? 'tok dim vow' : 'tok dim'
        spans.push(`<span class="${cls}" data-i="${i}">`
          + `${escapeHtml(toks[i]!['text'])}</span>`)
        pos += toks[i]!['text'].length
        i++
      } else {
        spans.push(`<span class="pun">${escapeHtml(text[pos]!)}</span>`)
        pos++
      }
    }
    const ch = escapeHtml(act['chapter'] || '评书')
    const sub = escapeHtml(act['subtitle'] || '')
    const quote = escapeHtml(act['quote'] || '')
    const qdiv = quote ? `<div class="quote">${quote}</div>` : ''
    bodySecs.push(
      `<section class="act" id="s-zh-${act['id']}" data-n="${toks.length}">\n`
      + `<div class="plaque"><div class="ch">${ch}</div>`
      + `<div class="sub">${sub}</div></div>\n`
      + `<div class="sheet"><div class="ktext">${spans.join('')}</div></div>\n`
      + `${qdiv}\n</section>`)
  }
  return tmpl
    .replace('__FONTS__', fontsCss || '')
    .replace('__SECTIONS__', bodySecs.join('\n'))
    .replace('{ptx}', ptx).replace('{pty}', pty)
    .replace('{ptw}', ptw).replace('{pth}', pth)
    .replace('{ktx}', ktx).replace('{kty}', kty)
    .replace('{ktw}', ktw).replace('{kth}', kth)
    .replace('{qtx}', qtx).replace('{qty}', qty)
    .replace('{qtw}', qtw).replace('{qth}', qth)
}

/** 墙侧舞台层（人物身后）：顶梁 / 台口护墙板 / 木匾。 */
export function drawStageBack(
  d: PilDraw, SCENE_P: Record<string, RGB>, ident: RGB, stage: Stage = PORTRAIT_STAGE,
): void {
  const geo = stage.geo
  const beam = geo.beam
  const beamW = rig.mix(SCENE_P['wood']!, [40, 30, 20], 0.45)
  d.rectangle(beam, { fill: beamW })
  d.rectangle([beam[0], beam[3] - 12, beam[2], beam[3]], { fill: rig.mix(beamW, [0, 0, 0], 0.25) })

  // 台口护墙板：顶亮条（横枋）+ 板缝
  const [x0, y0, x1, y1] = geo.panel
  const panelC = rig.mix(SCENE_P['wood']!, [52, 38, 26], 0.35)
  d.rectangle([x0, y0, x1, y1], { fill: panelC })
  d.rectangle([x0, y0, x1, y0 + 34], { fill: rig.mix(SCENE_P['wood2']!, panelC, 0.35) })
  for (let yy = y0 + 90; yy < y1; yy += 68) {
    d.line([x0, yy, x1, yy], { fill: rig.mix(panelC, [0, 0, 0], 0.18), width: 3 })
  }

  // 木匾（幕名）：吊索 + 匾板 + 右下投影
  const [px0, py0, px1, py1] = geo.plaque
  for (const cx of [px0 + 40, px1 - 40]) {
    d.line([cx, beam[3], cx, py0 + 14], { fill: SCENE_P['lamp']!, width: 4 })
  }
  d.roundedRectangle([px0 + 6, py0 + 10, px1 + 6, py1 + 10], 14, { fill: [0, 0, 0, 60] as RGBA })
  d.roundedRectangle([px0, py0, px1, py1], 14, { fill: rig.mix(PAPER, ident, 0.08) })
  d.roundedRectangle([px0, py0, px1, py1], 14,
    { outline: rig.mix(SCENE_P['wood']!, [0, 0, 0], 0.25), width: 8 })

  // 卷轴幡已下台：唱词改躺在案面书卷上（见 drawStageFront），
  // 墙侧到此为止——半身近景下墙面只留匾，干净不抢戏。
}

/** 台前层（人物身前）：案沿窄条（双手搭上面）+ 案身 + 案上摊开的
 * 唱词书卷（卷尾圆柱 + 卷面纸）+ 醒木 + 折扇。 */
export function drawStageFront(
  d: PilDraw, SCENE_P: Record<string, RGB>, ident: RGB, stage: Stage = PORTRAIT_STAGE,
): void {
  const geo = stage.geo
  const P = stage.props
  const [sx0, sy0, sx1, sy1] = geo.slab
  const slabC = rig.mix(SCENE_P['wood2']!, [150, 110, 70], 0.55)
  d.rectangle([sx0, sy0, sx1, sy1], { fill: slabC })
  d.rectangle([sx0, sy0, sx1, sy0 + 12], { fill: rig.mix(slabC, [0, 0, 0], 0.22) })  // 案沿暗线
  // 说书人双手落在案沿：条面上一道柔和接触影，把人和案锁在一起
  d.ellipse(P.contact, { fill: [0, 0, 0, 26] as RGBA })
  // 案身前脸：竖板缝（两侧从书卷后露出）
  const [kx0, ky0, kx1, ky1] = geo.skirt
  const skirtC = rig.mix(SCENE_P['wood']!, [34, 24, 16], 0.42)
  d.rectangle([kx0, ky0, kx1, ky1], { fill: skirtC })
  for (let xx = kx0 + 90; xx < kx1; xx += 150) {
    d.line([xx, ky0, xx, ky1], { fill: rig.mix(skirtC, [0, 0, 0], 0.20), width: 4 })
  }
  // 书卷卷尾（左右两根立着的卷轴圆柱，比卷面高出一线）
  const rodC = rig.mix(SCENE_P['wood']!, [28, 20, 14], 0.4)
  for (const [rx0, ry0, rx1, ry1] of [geo.roll_l, geo.roll_r]) {
    d.roundedRectangle([rx0 + 5, ry0 + 10, rx1 + 5, ry1 + 10], 16, { fill: [0, 0, 0, 46] as RGBA })
    d.roundedRectangle([rx0, ry0, rx1, ry1], 16, { fill: rodC })
    d.line([Math.floor((rx0 + rx1) / 2) - 4, ry0 + 16, Math.floor((rx0 + rx1) / 2) - 4, ry1 - 6],
      { fill: rig.mix(rodC, [120, 90, 55], 0.30), width: 6 })
    d.ellipse([rx0 + 2, ry0 - 8, rx1 - 2, ry0 + 30],
      { fill: rig.mix(rodC, [200, 170, 130], 0.22) })                    // 卷口螺旋端面
  }
  // 卷面（摊开的宣纸）：卷口顶缘阴影 + 右下投影感（底缘暗线）
  const [ppx0, ppy0, ppx1, ppy1] = geo.paper
  d.rectangle([ppx0, ppy0, ppx1, ppy1], { fill: rig.mix(PAPER, ident, 0.05) })
  d.rectangle([ppx0, ppy0, ppx1, ppy0 + 8], { fill: rig.mix(PAPER, [0, 0, 0], 0.10) })
  d.rectangle([ppx0, ppy1 - 6, ppx1, ppy1], { fill: rig.mix(PAPER, [0, 0, 0], 0.07) })
  // 醒木（案沿条上左）：底影 + 木块 + 顶面亮
  d.ellipse(P.gavelShadow, { fill: [0, 0, 0, 40] as RGBA })
  d.roundedRectangle(P.gavel, 8, { fill: rig.mix(SCENE_P['wood']!, [20, 14, 10], 0.30) })
  d.roundedRectangle(P.gavelTop, 6, { fill: rig.mix(SCENE_P['wood2']!, [60, 45, 30], 0.2) })
  // 折扇（案沿条上右）：扇柄 + 纸面 + 细骨线
  const R = P.fanRib
  d.ellipse(P.fanShadow, { fill: [0, 0, 0, 40] as RGBA })
  d.roundedRectangle(P.fanHandle, 6, { fill: rig.mix(SCENE_P['wood']!, [20, 14, 10], 0.30) })
  d.roundedRectangle(P.fanPaper, 10, { fill: rig.mix(PAPER, [200, 190, 170], 0.35) })
  for (let xx = R.from; xx < R.to; xx += R.step) {
    d.line([xx, R.y0, xx, R.y1], { fill: rig.mix(MUT, [0, 0, 0], 0.05), width: 2 })
  }
}

/** CLI 入口：`feuille storyteller render-frames <acts.json> <out_dir> [--act a1] [--fps 30]`。 */
export async function main(argv: string[]): Promise<number> {
  const pos: string[] = []
  let act: string | null = null
  let fpsArg: number | null = null
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (a === '--act') {
      if (i + 1 >= argv.length) throw new FeuilleError('--act 缺值')
      act = argv[++i]!
    } else if (a === '--fps') {
      if (i + 1 >= argv.length) throw new FeuilleError('--fps 缺值')
      fpsArg = Number(argv[++i]!)
    } else if (a.startsWith('--')) {
      throw new FeuilleError(`未知旗标：${a}`)
    } else {
      pos.push(a)
    }
  }
  if (pos.length < 2) {
    console.error('usage: feuille storyteller render-frames <acts.json> <out_dir> [--act a1] [--fps 30]')
    return 2
  }
  const [actsJson, outDir] = pos as [string, string]

  const cfg = JSON.parse(readFileSync(actsJson, 'utf8')) as Cfg
  const st = data.storytellers()[String(cfg['storyteller_id'] ?? 'changlianke')]
  if (!st) {
    throw new FeuilleError('storyteller.json 里没有这个说书人 id')
  }
  const ident = rig.hexc(st['identity'])
  const timing = (cfg['timing'] ?? {}) as Cfg
  // fps 口径必须与 assemble 同源：assemble 读 timing.fps，这里也读同一个字段，
  // 否则「渲 30 / 合 25」会静默错长度（帧数按 30 算、装配按 25 摆，越到后面越歪）。
  const fps = fpsArg ?? Number(timing['fps'] ?? 30)
  const formats = cfg['formats'] as Array<Cfg>
  const W = formats[0]!['w'] as number, H = formats[0]!['h'] as number
  // 舞台几何按画幅取（未定义的画幅在这里判死，不退化成竖版）
  const stage = stageGeometry(W, H)
  const A = stage.actor
  const out = resolve(outDir)
  mkdirSync(out, { recursive: true })
  const browser = platform.browserPath()
  const FF = platform.ffmpeg()
  if (!FF) {
    throw new FeuilleError('找不到 ffmpeg（feuille.platform 解析）')
  }
  if (!browser) {
    throw new FeuilleError('找不到 Chromium 系浏览器（feuille.platform）')
  }

  // 醒木音（一次）
  const gavelPath = join(out, 'gavel.wav')
  if (!existsSync(gavelPath)) {
    synthGavel(gavelPath, fps, FF)
    console.log('  gavel.wav 合成完毕')
  }

  let acts = cfg['acts'] as Array<Cfg>
  if (act) {
    acts = acts.filter((a) => a['id'] === act)
    if (acts.length === 0) {
      throw new FeuilleError(`--act ${act}: 幕表里没有`)
    }
  }

  const here = resolve(actsJson, '..')
  const preroll = Number(timing['preroll'] ?? 0.8)
  const ttsDir = join(here, 'tts')

  // ---- 字卡页（一次生成：TTS meta 的 text/tokens + 幕表章回）----
  const cardActs: Array<[Cfg, string, Array<{ text: string; start: number }>]> = []
  for (const a of acts) {
    const cand = [join(ttsDir, `${a['id']}.json`), join(ttsDir, `zh-${a['id']}.json`)]
    const metaP = cand.find((c) => existsSync(c))
    if (!metaP) {
      throw new FeuilleError(`缺 TTS 产物 ${cand[0]}（先跑 feuille karaoke tts）`)
    }
    const meta = JSON.parse(readFileSync(metaP, 'utf8')) as Cfg
    cardActs.push([a, meta['text'], meta['tokens']])
  }
  const fontsP = join(here, 'fonts.css')
  const fontsCss = existsSync(fontsP) ? readFileSync(fontsP, 'utf8') : ''
  const cardsDir = join(out, '_cards')
  mkdirSync(cardsDir, { recursive: true })
  const buildHtml = join(cardsDir, 'src.html')
  writeFileSync(buildHtml, buildCardHtml(cardActs, fontsCss, stage), 'utf8')
  console.log(`  字卡页自生成：${buildHtml}`)

  for (const [actCfg, , toks] of cardActs) {
    const actId = String(actCfg['id'])
    const locale = 'zh-' + actId
    const mp3P = join(ttsDir, `${locale}.mp3`)
    const adur = audio.probeDuration(mp3P)
    // 帧数口径与 karaoke build 一致：preroll + Σ词段 + tail + done
    const durs: number[] = [preroll]
    for (let i = 0; i < toks.length; i++) {
      const d = i < toks.length - 1
        ? (toks[i + 1]!['start'] as number) - (toks[i]!['start'] as number)
        : (adur - (toks[i]!['start'] as number)) + Number(timing['tail'] ?? 0.8)
      durs.push(Math.ceil(d * fps - 1e-9) / fps)
    }
    durs.push(Number(timing['done'] ?? 0.5))
    const nFrames = durs.reduce((acc, d) => acc + roundHalfEven(d * fps), 0)

    // 背景墙面（每幕一次，按 identity 调色；低处道具由台口护墙板遮挡）
    const bgRaw = await (await scenes.prerenderBg(st, {
      scene: (actCfg['scene'] ?? []) as readonly string[],
    }, bgLayoutFor(stage))).ensureAlpha().raw().toBuffer({ resolveWithObject: true })
    // 合成基底必须就是画幅尺寸：sharp 的 composite 校验发生在 resize **之后**，
    // 尺寸不符时带推/摇镜头的幕会被那层放大蒙混过去，只在第一个 static 幕炸
    // （实测 a01–a05 全过、a06 抛 Image to composite must have same dimensions）。
    if (bgRaw.info.width !== W || bgRaw.info.height !== H) {
      throw new FeuilleError(
        `背景画布 ${bgRaw.info.width}×${bgRaw.info.height} 与画幅 ${W}×${H} 不符`
        + '（prerenderBg 的布局没跟上画幅：composite 会只在 static 镜头暴露）')
    }

    // 舞台静态层（墙侧/台前各一张，帧循环外缓存；SS=2 超采样抗锯齿）
    const backCanvas = createCanvas(W * 2, H * 2)
    drawStageBack(new scenes.DrawScaled(createPilDraw(backCanvas.getContext('2d')), 2),
      rig.SCENE as Record<string, RGB>, ident, stage)
    const backBuf = await sharp(backCanvas.encodeSync('png'))
      .resize(W, H, { kernel: 'lanczos3' }).raw()
      .toBuffer({ resolveWithObject: true })
    const frontCanvas = createCanvas(W * 2, H * 2)
    drawStageFront(new scenes.DrawScaled(createPilDraw(frontCanvas.getContext('2d')), 2),
      rig.SCENE as Record<string, RGB>, ident, stage)
    const frontBuf = await sharp(frontCanvas.encodeSync('png'))
      .resize(W, H, { kernel: 'lanczos3' }).raw()
      .toBuffer({ resolveWithObject: true })

    // 人物层（幕 pose/mood；blink 由帧序驱动——确定性）。
    // 站位见模块头注释：半身近景，双手搭案沿，唱词在身前卷面上。
    // act.pose 缺省 both_hands；显式 null 与 Python get 同义（falsy → 无姿态）。
    const actPose = actCfg['pose'] === undefined ? 'both_hands' : (actCfg['pose'] as string | null)
    const actorFrame = (tSec: number, poseOverride: string | null): Buffer => {
      const poseCode = poseOverride || actPose
      let pose: Record<string, any> = {}
      if (poseCode && rig.POSE_CODES.has(poseCode)) {
        const u = (tSec % 2.0) / 2.0
        const raw = rig.poseFor(poseCode, u, tSec, st)
        pose = Object.fromEntries(
          Object.entries(raw).filter(([k]) => ['armL', 'armR', 'legL', 'legR'].includes(k)))
      }
      const blink = (tSec % Number(st['movement']['blinkCycleSec'])) < 0.12
      const canvas = createCanvas(W * 2, H * 2)
      const d = createPilDraw(canvas.getContext('2d'))
      rig.drawCharacter(canvas, d, st, tSec, {
        scale: A.s, xoff: A.x, yoff: A.y, squash: 0.0, xscale: 1.0,
        head_dx: 0, head_dy: 0, brow_lift_extra: 0, pose,
        openness: 0.0, blink, mood: actCfg['mood'] ?? 'neutral',
        ss: 2,
      })
      // PIL Resampling.BOX（精确 2× 整数下采 = 2×2 均值）的直实现
      const src = canvas.getContext('2d').getImageData(0, 0, W * 2, H * 2).data
      const box = Buffer.alloc(W * H * 4)
      const row = W * 2 * 4
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          const o = (y * W + x) * 4
          const s0 = y * 2 * row + x * 8
          const s1 = s0 + 4, s2 = s0 + row, s3 = s2 + 4
          for (let c = 0; c < 4; c++) {
            box[o + c] = Math.round(
              (src[s0 + c]! + src[s1 + c]! + src[s2 + c]! + src[s3 + c]!) / 4)
          }
        }
      }
      return box
    }

    const shotFrames = shotTransform(actCfg['shot'], nFrames, fps, W)

    // 词边界 → 每帧该亮的 token 数
    const boundaries = [roundHalfEven(preroll * fps)]
    let acc = roundHalfEven(preroll * fps)
    for (const d of durs.slice(1, -1)) {
      acc += roundHalfEven(d * fps)
      boundaries.push(acc)
    }
    const doneStart = acc

    console.log(`  ${actId}: ${nFrames} 帧 (${(nFrames / fps).toFixed(1)}s), scene=${actCfg['scene']}, `
      + `shot=${((actCfg['shot'] ?? {})['kind'] ?? 'static')}`)

    // 合成循环：墙 → 匾 → 人物 → 案+卷 → 卷面/匾内文字 → 镜头（整帧）
    for (let k = 0; k < nFrames; k++) {
      const [scale, sx, sy] = shotFrames[k]!
      const tSec = k / fps
      let state: number
      if (k < boundaries[0]!) {
        state = -1
      } else if (k >= doneStart) {
        state = toks.length
      } else {
        // max(i for i, b in enumerate(boundaries) if k >= b)：boundaries
        // 单调不减，扫到最后的命中下标即 max
        state = -1
        for (let bi = 0; bi < boundaries.length; bi++) {
          if (k >= boundaries[bi]!) state = bi
        }
      }
      // 人物（拍案手 pose 在幕首 1.2s 内用 gavel 拍案 pose）
      let poseCode: string | null = actPose
      if (actCfg['gavel'] && k < roundHalfEven(1.2 * fps) && state < 1) {
        poseCode = 'fist'   // 拍案手（clap 近景下双手出框，fist 不出）
      }
      const actorBuf = actorFrame(tSec, poseCode)
      // 卷面/匾内文字：按 state 取缓存截图（?lang&state 契约），matte 后
      // 合成——文字长在人物身前的卷面/匾面上，与舞台一体
      const key = `${actId}-${state >= 0 ? state : 'pre'}`
      const cardCache = join(cardsDir, `${key}.png`)
      if (!existsSync(cardCache)) {
        await renderWordCard(buildHtml, cardCache, W, H, `?lang=${locale}&state=${state}`, browser)
      }
      const card = await matteUnpremultiply(cardCache)
      let frame = sharp(bgRaw.data, {
        raw: { width: bgRaw.info.width, height: bgRaw.info.height, channels: bgRaw.info.channels },
      }).composite([
        { input: backBuf.data, raw: { width: W, height: H, channels: backBuf.info.channels } },
        { input: actorBuf, raw: { width: W, height: H, channels: 4 } },
        { input: frontBuf.data, raw: { width: W, height: H, channels: frontBuf.info.channels } },
        { input: card.data, raw: { width: card.width, height: card.height, channels: 4 } },
      ])
      // 镜头最后作用于整幅合成（文字长在卷面上，随画面一起动）。
      // 行程一律锁 ≥1.0：画布满幅不露底（zoom-out 语义 = 主体变小）。
      if (Math.abs(scale - 1.0) > 1e-3 || Math.abs(sx) > 1e-3) {
        const eff = Math.max(scale, 1.0)
        const sw = Math.trunc(W * eff), sh = Math.trunc(H * eff)
        let ox = Math.trunc((sw - W) / 2 + sx)
        let oy = Math.trunc((sh - H) / 2 + sy)
        ox = Math.max(0, Math.min(sw - W, ox))
        oy = Math.max(0, Math.min(sh - H, oy))
        frame = frame.resize(sw, sh, { kernel: 'lanczos3' })
          .extract({ left: ox, top: oy, width: W, height: H })
      }
      await frame.removeAlpha().png().toFile(join(out, `f${actId}-${String(k).padStart(4, '0')}.png`))
    }
    console.log(`  ${actId}: 帧序列写完`)
  }
  return 0
}
