// color_contrast.ts — 文字压实拍画面：量背景亮度，不靠眼睛挑颜色
// （multilingual-video-poetry/scripts/color_contrast.py 的 TS 归流）。
//
// ## 为什么不能靠色
//
// 配色是看着挑的就会漏。实测教训：冬季冰蓝初版 `#69B4E8` 叠在白雪上几乎看不见，
// 因为「冷色配雪」在直觉上成立。而**量化之后原因很清楚**——四季文字区的背景亮度：
// 冬季背景亮度是其余三季的 3.6 倍。目视只能看出「看不见」，量能量出「差多少倍」。
//
// ## ⚠️ WCAG 对比度**不适用**于彩字压实拍
//
// 脚本会顺带算出 WCAG 亮度对比，但**不要拿它判定合格**：WCAG 为 UI 文字压平底色
// 设计，只看亮度差，会系统性低估「亮度差 + 色相差 + 阴影光晕」三者叠加的彩字可读
// 性。所以本模块**不以 WCAG 判定退出码**，只报背景亮度与原始比值。真正的验收是
// **目视复核渲染后的合成帧**——但**先量背景亮度**，才知道该重点盯哪一季。
//
// ## `--gate`：把「该季可读」降级成二值判据（阈值自标定，不内置）
//
// 任一季低于阈值 → 逐季 PASS/FAIL + 退出码 1。**阈值没有默认值，必须由项目自己
// 标定**（在已目视验收过的成片帧上跑本工具，取各季实测亮度差的最低档再留余量；
// 编普适阈值就是编数据——纪律 8）。`--gap-ref p50|p90` 选参照环带（默认 p90）。
//
// 归流决定：ffmpeg 解析走 @feuille/core platform 唯一实现；成像走 sharp
// （PIL LANCZOS → sharp lanczos3 同族核）；季色默认值不再 import Python 归档模块，
// 而是读同一份归档文件、解析 `SEASON_COLOR` 字面量（机制变了、事实源没变）。
import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import sharp from 'sharp'

import { FeuilleError, platform } from '@feuille/core'

export const SEASON_SHOT: Record<string, number> = { 春: 2.6, 夏: 7.8, 秋: 11.9, 冬: 16.7 } // 只对四季节项目母版成立，别的母版用 --shots 给
export const BANDS: Record<string, readonly [number, number]> = { top: [0.00, 0.22], bottom: [0.50, 1.00] }
export const GLYPH_HUE_TOL = 0.03
export const GLYPH_V_MIN = 0.5
export const GLYPH_S_MIN = 0.25
export const RING_PX = 14

const HELP = `usage: feuille poetry color-contrast [-h] [--band {top,bottom}]
                                        [--seasons SEASONS] [--cards CARDS]
                                        [--colors COLORS] [--shots SHOTS]
                                        [--suggest SUGGEST] [--gate GATE]
                                        [--gap-ref {p50,p90}]
                                        [image]

positional arguments:
  image                 原始帧 png

options:
  -h, --help            show this help message and exit
  --band {top,bottom}   文字区带（默认 bottom）
  --seasons SEASONS     母版 mp4：四季一次量完
  --cards CARDS         字幕层目录，如 cards/横版
  --colors COLORS       季色 JSON，如 {"春":["#F0568C","#C9889E"]}
  --shots SHOTS         各季取帧秒点 JSON，如 {"春":2.6,"夏":7.8}；
                        默认值是四季节项目母版的标定值，别的母版必须给
  --suggest SUGGEST     给一个色，返回保留色相的深浅几档
  --gate GATE           二值判据阈值：|字芯亮度 − 环带背景| 低于它的季 FAIL、
                        退出码 1。没有默认值——在已目视验收的成片帧上标定后再给
  --gap-ref {p50,p90}   gate 参照的环带分位（默认 p90）
`

/** 外部可执行文件经 @feuille/core platform 解析（懒解析，barrel 导入永不炸）。 */
function ffmpegBin(): string {
  return platform.requireTool(platform.ffmpeg(), 'ffmpeg')
}

/** argparse 同款解析：全部旗标都带值（`--k v` / `--k=v` 皆收，后者覆盖）；
 * 旗标值不落进位置参数，多余位置参数 / 未知旗标 / 缺值 → usage + 2。 */
function parseArgs(argv: string[]): { vals: Record<string, string>; image: string | undefined } | null {
  const known = ['--band', '--seasons', '--cards', '--colors', '--shots', '--suggest',
    '--gate', '--gap-ref']
  const vals: Record<string, string> = {}
  const pos: string[] = []
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (!a.startsWith('--')) {
      pos.push(a)
      continue
    }
    const eq = a.indexOf('=')
    const flag = eq >= 0 ? a.slice(0, eq) : a
    if (!known.includes(flag)) return null
    const val = eq >= 0 ? a.slice(eq + 1) : argv[++i]
    if (val === undefined) return null
    vals[flag] = val
  }
  if (pos.length > 1) return null
  return { vals, image: pos[0] }
}

function loadJson(text: string, flag: string): Record<string, unknown> {
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch (e) {
    throw new FeuilleError(`${flag} 不是合法 JSON：${e instanceof Error ? e.message : e}`)
  }
}

export function hex2rgb(h: string): [number, number, number] {
  const s = h.replace(/^#/, '')
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)]
}

/** sRGB → 线性（逐值；numpy 广播 → 循环）。 */
function srgbToLin(c: number): number {
  const v = c / 255.0
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
}

/** 相对亮度（RGB 原始字节 → 加权和）。 */
function lumOf(r: number, g: number, b: number): number {
  return 0.2126 * srgbToLin(r) + 0.7152 * srgbToLin(g) + 0.0722 * srgbToLin(b)
}

export function lumHex(h: string): number {
  const [r, g, b] = hex2rgb(h)
  return lumOf(r, g, b)
}

export function wcagRatio(hexA: string, lumB: number): number {
  const la = lumHex(hexA)
  const hi = Math.max(la, lumB)
  const lo = Math.min(la, lumB)
  return (hi + 0.05) / (lo + 0.05)
}

/** colorsys.rgb_to_hls（Python 标准库逐式镜像）。 */
export function rgbToHls(r: number, g: number, b: number): [number, number, number] {
  const maxc = Math.max(r, g, b)
  const minc = Math.min(r, g, b)
  const l = (minc + maxc) / 2
  if (minc === maxc) return [0, l, 0]
  return [hueOf(r, g, b, maxc, minc), l, satOf(l, maxc, minc)]
}

function hueOf(r: number, g: number, b: number, maxc: number, minc: number): number {
  const rc = (maxc - r) / (maxc - minc)
  const gc = (maxc - g) / (maxc - minc)
  const bc = (maxc - b) / (maxc - minc)
  let h: number
  if (r === maxc) h = bc - gc
  else if (g === maxc) h = 2.0 + rc - bc
  else h = 4.0 + gc - rc
  h = (h / 6.0) % 1.0
  return h < 0 ? h + 1.0 : h
}

function satOf(l: number, maxc: number, minc: number): number {
  if (l <= 0.5) return (maxc - minc) / (maxc + minc)
  return (maxc - minc) / (2.0 - maxc - minc)
}

/** colorsys.hls_to_rgb（suggest 的取档机制）。 */
export function hlsToRgb(h: number, l: number, s: number): [number, number, number] {
  if (s === 0) return [l, l, l]
  const m2 = l <= 0.5 ? l * (1 + s) : l + s - l * s
  const m1 = 2.0 * l - m2
  return [_v(m1, m2, h + 1 / 3), _v(m1, m2, h), _v(m1, m2, h - 1 / 3)]
}

function _v(m1: number, m2: number, hue: number): number {
  let h = hue % 1.0
  if (h < 0) h += 1
  if (h < 1 / 6) return m1 + (m2 - m1) * h * 6.0
  if (h < 1 / 2) return m2
  if (h < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - h) * 6.0
  return m1
}

/** Python round()：四舍六入五成双（banker's rounding），不是 Math.round。 */
function pyRound(x: number): number {
  const f = Math.floor(x)
  const d = x - f
  if (d > 0.5) return f + 1
  if (d < 0.5) return f
  return f % 2 === 0 ? f : f + 1
}

/** Python f"{v:g}"：去尾零的最短形态（0.30 → "0.3"、30 → "30"）。 */
function pyG(v: number): string {
  return String(v)
}

/** numpy.percentile 默认线性插值：rank=(n-1)*p/100，两侧线性内插（先排序）。 */
export function percentile(sorted: number[] | Float64Array, p: number): number {
  const n = sorted.length
  if (n === 0) return Number.NaN
  if (n === 1) return sorted[0]!
  const rank = ((n - 1) * p) / 100
  const lo = Math.floor(rank)
  const hi = Math.ceil(rank)
  if (lo === hi) return sorted[lo]!
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (rank - lo)
}

type Raw = { data: Uint8Array; width: number; height: number }

/** 帧装入 RGB 原始像素（PIL `convert("RGB")` 语义：丢 alpha 通道，不混合）。
 * card 非空则先 LANCZOS 缩到帧尺寸再 alpha 合成
 * （PIL alpha_composite + resize(LANCZOS) → sharp composite + lanczos3 同族核）。
 *
 * ⚠ sharp 的 `raw()` 以 info.channels 为准（实测 ensureAlpha+removeAlpha 会被
 * 优化掉、照样回 4 通道）——按通道数抽 RGB，不能假设 3 通道布局。 */
async function loadRegion(
  frame: string, card: string | null,
): Promise<Raw> {
  const meta = await sharp(frame).metadata()
  let img = sharp(frame)
  if (card !== null) {
    const cardBuf = await sharp(card)
      .resize(meta.width!, meta.height!, { kernel: 'lanczos3' })
      .ensureAlpha().png().toBuffer()
    img = img.composite([{ input: cardBuf }])
  }
  const { data, info } = await img.raw().toBuffer({ resolveWithObject: true })
  const n = info.channels
  const px = info.width * info.height
  const out = new Uint8Array(px * 3)
  if (n === 3) {
    out.set(data.subarray(0, px * 3))
  } else {
    for (let i = 0; i < px; i++) {
      out[i * 3] = data[i * n]!
      out[i * 3 + 1] = data[i * n + 1]!
      out[i * 3 + 2] = data[i * n + 2]!
    }
  }
  return { data: out, width: info.width, height: info.height }
}

/** 字形掩膜。参数是**标定**出来的，不是拍的：色相容差 0.09 会把夏天的天空与
 * 草地一并抓进来（占区域 68.5%）；0.03 + v>0.5 才精准命中字芯——此时字形亮度
 * p75 与该色实算亮度一致（实测 0.635 vs 0.636）。
 *
 * 色相向量化算（Python numpy 分支优先级 r>g>b 与 colorsys.rgb_to_hsv 一致：
 * 灰像素 r 分支给出 0，两通道并列最大时结果也一致）。 */
export function glyphMask(reg: Uint8Array, w: number, h: number, color: string): Uint8Array {
  const [tr, tg, tb] = hex2rgb(color)
  const hueT = rgbToHls(tr / 255, tg / 255, tb / 255)[0]
  const out = new Uint8Array(w * h)
  for (let i = 0; i < w * h; i++) {
    const R = reg[i * 3]!, G = reg[i * 3 + 1]!, B = reg[i * 3 + 2]!
    const mxf = Math.max(R, G, B)
    const mnf = Math.min(R, G, B)
    const v = mxf / 255.0
    const s = mxf > 0 ? (mxf - mnf) / Math.max(mxf, 1e-6) : 0.0
    const r = R / 255.0, g = G / 255.0, b = B / 255.0
    const mx = Math.max(r, g, b)
    const mn = Math.min(r, g, b)
    const c = mx - mn
    const safeC = c > 0 ? c : 1.0
    let hue6: number
    if (mx === r) hue6 = (((g - b) / safeC) % 6.0 + 6.0) % 6.0
    else if (mx === g) hue6 = (b - r) / safeC + 2.0
    else hue6 = (r - g) / safeC + 4.0
    const hsv = hue6 / 6.0
    const dh = Math.min(Math.abs(hsv - hueT), 1 - Math.abs(hsv - hueT))
    out[i] = dh < GLYPH_HUE_TOL && s > GLYPH_S_MIN && v > GLYPH_V_MIN ? 1 : 0
  }
  return out
}

/** 4 邻域膨胀 n 次（布尔图）。 */
export function dilate(m: Uint8Array, w: number, h: number, n: number): Uint8Array {
  let out = m
  for (let k = 0; k < n; k++) {
    const d = Uint8Array.from(out)
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x
        if (out[i]) {
          if (y + 1 < h) d[(y + 1) * w + x] = 1
          if (y > 0) d[(y - 1) * w + x] = 1
          if (x + 1 < w) d[i + 1] = 1
          if (x > 0) d[i - 1] = 1
        }
      }
    }
    out = d
  }
  return out
}

export type MeasureResult = {
  gl: number | null
  p50: number
  p90: number
  npx: number
}

/** 返回 (字芯亮度, 紧邻背景 p50/p90, 字形像素数)。card=null 则只量背景。
 * 字形/环带命中不足 → gl=null（Python NaN 路径），p50/p90 为 NaN 不入排名。 */
export async function measure(
  frame: string, card: string | null, color: string, bandName: string,
): Promise<MeasureResult> {
  const raw = await loadRegion(frame, card)
  const [lo, hi] = BANDS[bandName]!
  const y0 = Math.trunc(raw.height * lo)
  const y1 = Math.trunc(raw.height * hi)
  const w = raw.width
  const regH = y1 - y0
  const reg: Uint8Array = new Uint8Array(w * regH * 3)
  for (let y = 0; y < regH; y++) {
    const src = (y0 + y) * w * 3
    reg.set(raw.data.subarray(src, src + w * 3), y * w * 3)
  }
  const lums = new Float64Array(w * regH)
  for (let i = 0; i < w * regH; i++) {
    lums[i] = lumOf(reg[i * 3]!, reg[i * 3 + 1]!, reg[i * 3 + 2]!)
  }
  const sortedLums = Array.from(lums).sort((a, b) => a - b)
  if (card === null) {
    return { gl: null, p50: percentile(sortedLums, 50), p90: percentile(sortedLums, 90), npx: 0 }
  }
  const g = glyphMask(reg, w, regH, color)
  let npx = 0
  for (let i = 0; i < g.length; i++) npx += g[i]!
  if (npx < 60) return { gl: null, p50: Number.NaN, p90: Number.NaN, npx }
  const ring = dilate(g, w, regH, RING_PX)
  const ringLums: number[] = []
  const glyphLums: number[] = []
  for (let i = 0; i < g.length; i++) {
    if (g[i]) glyphLums.push(lums[i]!)
    else if (ring[i]) ringLums.push(lums[i]!)
  }
  if (ringLums.length < 60) return { gl: null, p50: Number.NaN, p90: Number.NaN, npx }
  glyphLums.sort((a, b) => a - b)
  ringLums.sort((a, b) => a - b)
  return {
    gl: percentile(glyphLums, 75),
    p50: percentile(ringLums, 50),
    p90: percentile(ringLums, 90),
    npx,
  }
}

/** 给一个色，输出保留色相的深浅几档供挑选。 */
export function suggest(hexCol: string): string[] {
  const [r, g, b] = hex2rgb(hexCol)
  const [h, , s] = rgbToHls(r / 255, g / 255, b / 255)
  const out: string[] = []
  for (const L of [0.90, 0.72, 0.50, 0.28]) {
    const [rr, gg, bb] = hlsToRgb(h, L, Math.min(1.0, s * 1.2))
    out.push(`#${[pyRound(rr * 255), pyRound(gg * 255), pyRound(bb * 255)]
      .map((v) => v.toString(16).padStart(2, '0').toUpperCase()).join('')}`)
  }
  return out
}

/** `--gate` 的二值判据（纯函数；反向验证在 packages/poetry/test，从
 * verify_skill_scripts.py 随本模块归流一起移植）。
 *
 * 判的是「字芯与紧邻背景的亮度差 ≥ 项目标定阈值」。阈值**必须外部给**：
 * 在已目视验收的成片帧上实测后标定，不内置默认（四季归档只覆盖一个项目，
 * 编普适阈值违反纪律 8）。 */
export function gapVerdict(gap: number, minGap: number, season: string): string {
  if (gap >= minGap) {
    return `PASS ${season}：亮度差 ${gap.toFixed(3)} ≥ 阈值 ${pyG(minGap)}`
  }
  return `FAIL ${season}：亮度差 ${gap.toFixed(3)} < 阈值 ${pyG(minGap)}`
    + `——该季彩字会先失效，压深字色或压暗底色后再量`
}

/** 季色默认值：读归档的 季节与译文.py、解析 `SEASON_COLOR` 字面量。
 *
 * Python 原版 `import 季节与译文`（执行归档模块）；TS 复刻为解析同一份文件的
 * 字面量——归档 .py 是**数据资产**（P7 清场不删 assets/example），机制换了、
 * 事实源没换。先取入库归档副本（assets/example），再退到本机工作目录
 * （examples/sijijie，不入库）——fresh clone 上只有前者。 */
export function seasonColorsFromArchive(): Record<string, string[]> | null {
  const here = dirname(fileURLToPath(import.meta.url))
  const cands = [
    resolve(here, '../../../skills/multilingual-video-poetry/assets/example'),
    resolve(here, '../../../examples/sijijie'),
  ]
  for (const cand of cands) {
    const f = join(cand, '季节与译文.py')
    if (!existsSync(f)) continue
    const m = /SEASON_COLOR\s*=\s*\{([\s\S]*?)\n\}/.exec(readFileSync(f, 'utf8'))
    if (!m) continue
    const colors: Record<string, string[]> = {}
    const re = /"([^"]+)"\s*:\s*\(\s*"(#[0-9A-Fa-f]{6})"\s*,\s*"(#[0-9A-Fa-f]{6})"\s*\)/g
    for (const hit of m[1]!.matchAll(re)) {
      colors[hit[1]!] = [hit[2]!, hit[3]!]
    }
    if (Object.keys(colors).length) return colors
  }
  return null
}

/** CLI 入口：`feuille poetry color-contrast [image] [--seasons …] [--cards …] …`。
 * argparse 口径：-h → 0；坏 choice / 坏 float / 未知旗标 / 缺位置参数 → 2。 */
export async function main(argv: string[]): Promise<number> {
  if (argv.includes('-h') || argv.includes('--help')) {
    console.log(HELP)
    return 0
  }
  // argparse：全部旗标先解析，坏值当场退 2（哪怕走不进对应分支）
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write(`unrecognized arguments: ${argv.join(' ')}\n`)
    return 2
  }
  const { vals, image } = parsed
  const band = vals['--band'] ?? 'bottom'
  if (!(band in BANDS)) {
    process.stderr.write(`--band 只收 ${Object.keys(BANDS).join('/')}，不收 ${band}\n`)
    return 2
  }
  const gapRef = vals['--gap-ref'] ?? 'p90'
  if (gapRef !== 'p50' && gapRef !== 'p90') {
    process.stderr.write(`--gap-ref 只收 p50/p90，不收 ${gapRef}\n`)
    return 2
  }
  let gate: number | null = null
  if (vals['--gate'] !== undefined) {
    gate = Number(vals['--gate'])
    if (!Number.isFinite(gate)) {
      process.stderr.write(`--gate 只收数字，不收 ${vals['--gate']}\n`)
      return 2
    }
  }
  const seasons = vals['--seasons']
  const cards = vals['--cards']
  const colorsRaw = vals['--colors']
  const shotsRaw = vals['--shots']
  const suggestHex = vals['--suggest']

  if (seasons !== undefined) {
    const vid = seasons
    if (!existsSync(vid)) {
      console.log(`找不到 ${vid}`)
      return 2
    }
    let colors: Record<string, string[]> | null = null
    if (colorsRaw !== undefined) {
      colors = loadJson(colorsRaw, '--colors') as Record<string, string[]>
    } else {
      colors = seasonColorsFromArchive()
    }
    if (colors === null) {
      console.log('未给 --colors，也找不到 季节与译文.py。'
        + '用例：--colors \'{"春":["#F0568C","#C9889E"]}\'')
      return 2
    }
    console.log(`母版 ${basename(vid)} · 文字区 ${band} · 已合成字幕层\n`)
    console.log('季'.padEnd(4) + '主色'.padStart(10) + '字芯'.padStart(8)
      + '环带p50'.padStart(10) + '环带p90'.padStart(10) + 'WCAG比值'.padStart(10) + '  备注')
    const rows: Array<[string, number]> = []
    const gaps: Record<string, number> = {}
    const shots = shotsRaw !== undefined
      ? loadJson(shotsRaw, '--shots') as Record<string, number>
      : SEASON_SHOT
    const td = mkdtempSync(join(tmpdir(), 'color-contrast-'))
    try {
      for (const [s, sec] of Object.entries(shots)) {
        if (!(s in colors)) continue
        const fr = join(td, `${s}.png`)
        const r = spawnSync(ffmpegBin(),
          ['-y', '-v', 'error', '-ss', String(sec), '-i', vid, '-frames:v', '1', fr],
          { encoding: 'utf8', timeout: 120000 })
        if (r.status !== 0) {
          // Python subprocess.run(check=True)：失败当场炸（不静默跳过这一季）
          throw new FeuilleError(`ffmpeg 退出 ${r.status}：${(r.stderr ?? '').slice(-300)}`)
        }
        let card: string | null = null
        if (cards !== undefined) {
          const cands = readdirSync(cards).filter((f) => f.endsWith(`.${s}.png`)).sort()
          if (!cands.length) {
            console.log(`  ✗ ${cards} 下找不到 *.${s}.png，跳过 ${s}`)
            continue
          }
          card = join(cards, cands[0]!)
        }
        const mainC = colors[s]![0]!
        const m = await measure(fr, card, mainC, band)
        if (card === null) {
          console.log(s.padEnd(4) + mainC.padStart(10) + '—'.padStart(8)
            + m.p50.toFixed(3).padStart(10) + m.p90.toFixed(3).padStart(10)
            + '—'.padStart(10) + '  未合成')
          rows.push([s, m.p90])
          continue
        }
        if (m.gl === null) {
          // 字形没抓到：量出来的 p50/p90 是 NaN，硬印会出 "NaN"，
          // 进 rows 又会污染最亮/最暗季的排名——跳过并说原因
          console.log(s.padEnd(4) + mainC.padStart(10) + '—'.padStart(8)
            + '—'.padStart(10) + '—'.padStart(10) + '—'.padStart(10)
            + `  字形命中不足（${m.npx}px）——查 --colors 是否对、卡片是否这季、`
            + '--band 区里有没有字')
          continue
        }
        rows.push([s, m.p90])
        let note = `字形${m.npx}px`
        if (gate !== null) {
          gaps[s] = Math.abs(m.gl - (gapRef === 'p90' ? m.p90 : m.p50))
          note += `  亮度差 ${gaps[s]!.toFixed(3)}`
        }
        console.log(s.padEnd(4) + mainC.padStart(10) + m.gl.toFixed(3).padStart(8)
          + m.p50.toFixed(3).padStart(10) + m.p90.toFixed(3).padStart(10)
          + wcagRatio(mainC, m.p90).toFixed(2).padStart(10) + `  ${note}`)
      }
    } finally {
      rmSync(td, { recursive: true, force: true })
    }
    if (rows.length > 1) {
      const hi = rows.reduce((a, b) => (b[1] > a[1] ? b : a))
      const lo = rows.reduce((a, b) => (b[1] < a[1] ? b : a))
      console.log(`\n最亮季：${hi[0]}（p90=${hi[1].toFixed(3)}）；最暗季：${lo[0]}`
        + `（p90=${lo[1].toFixed(3)}）——相差 ${(hi[1] / lo[1]).toFixed(1)}×`)
      if (hi[1] / lo[1] > 2) {
        console.log(`→ ${hi[0]}的底色量级远高于其他季，同一套配色与阴影强度在它上面`
          + '最先失效，**目视复核优先盯这一季**。')
      }
    }
    console.log('\n注：WCAG 比值仅供参考、不作判定（见模块头说明）。'
      + '验收靠目视复核渲染后的合成帧。')
    if (gate === null) return 0
    // --gate：把「该季彩字可读」降成二值判据。没量到的季不许静默混过
    // （纪律 12：SKIP 不是 PASS——未合成 / 字形命中不足在 gate 下就是 FAIL）。
    let bad = 0
    for (const s of Object.keys(shots)) {
      if (!(s in colors)) continue
      if (!(s in gaps)) {
        console.log(`FAIL ${s}：未量到（未合成 / 字形命中不足）——gate 模式下没验不许当过`)
        bad++
        continue
      }
      const v = gapVerdict(gaps[s]!, gate, s)
      console.log(v)
      bad += v.startsWith('FAIL') ? 1 : 0
    }
    console.log(`\nGATE ${bad ? 'FAIL' : 'PASS'}：阈值 ${pyG(gate)}`
      + `（gap-ref ${gapRef}；阈值由项目在已验收帧上标定，不内置默认）`)
    return bad ? 1 : 0
  }

  if (!image) {
    process.stderr.write(HELP)
    return 2
  }
  if (suggestHex !== undefined) {
    const m = await measure(image, null, suggestHex, band)
    console.log(`该区域背景 p50=${m.p50.toFixed(3)} p90=${m.p90.toFixed(3)}；`
      + `${suggestHex} 的深浅几档：`)
    for (const c of suggest(suggestHex)) {
      console.log(`  ${c}  亮度=${lumHex(c).toFixed(3)}  WCAG比值(仅供参考)=${wcagRatio(c, m.p90).toFixed(2)}`)
    }
    return 0
  }
  const m = await measure(image, null, '#FFFFFF', band)
  console.log(`${basename(image)} 区域=${band}  背景亮度 p50=${m.p50.toFixed(3)}  p90=${m.p90.toFixed(3)}`)
  return 0
}
