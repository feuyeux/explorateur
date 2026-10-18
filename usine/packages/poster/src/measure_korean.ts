// measure_korean.ts — 从真实墨量测韩文音节块垫片，自校验。
// （promoted from skills/one-page-poster/scripts/measure_korean.py，P5-7e 归流）
//
// 韩文字内着色法（见 references/script-coloring.md）用 `background-clip:text` 把
// 各 jamo 的墨涂成红（元音）/蓝（声母），垫片是硬边背景块。垫片几何**逐字形**：
// 别把测得的分数跨主题/跨字体复用——每个音节单独测。
//
// 对每个输入音节，本脚本：
//   1. NFD 分解成 jamo → 知道哪个是元音（中声）哪个是声母（初声/终声）；
//   2. 搭测量页（每个音节一个特大 .ksyl，字体栈与子集 css 与真海报完全一致——
//      传 --css），用 headless Chrome 渲（--dump-dom 拿元素框、--screenshot 拿墨）；
//   3. 墨连通域漫填，按中声 jamo 的几何先验逐域打元音/声母标签：
//      - 终声（若有）：伸进底部带（ymax > 顶 + 80% 墨高）的连通域——中声从不
//        下探那么深；
//      - 竖向中声笔画（ㅏ ㅓ ㅣ ㅐ …）在右半：非终声域中心过 50% 墨宽即元音；
//      - 中声 U+1169..U+1174（ㅗ ㅜ ㅡ 及复合 ㅘ..ㅢ）还画低位横向墨：非终声
//        域中（中心在墨高最低者 15% 以内的）最底一组即元音；
//      - 其余全是初声——可能是多个连通域（ㅎ 是弧+环，都算声母）；
//     复合元音（ㅝ ㅘ …）跨多个连通域、被终声截短的竖笔（일 的 ㅣ）都由标签
//     规则处理，不靠固定杠高；
//   4. 用至多 12 个矩形（对像素掩膜贪心最大矩形覆盖）盖住元音墨（外扩
//      --margin、避开同样外扩的声母墨），按可直接粘贴的 CSS 规则输出：
//      N 层红（双值百分比定位，见 emitRule）盖一个整框蓝层。分数相对元素框
//      （advance × line-height），任意 font-size 可迁移；
//   5. VERIFY：把生成的 CSS 真渲一遍（透明文字 + 垫片），逐墨像素对标签比色
//      ——逐音节 PASS/FAIL，任一 FAIL 退出非零，坏规则（百分比语义错、kerning
//      过紧、矩形截帽）响亮失败而不是默默涂错海报。注意 verify 只校验「CSS 能
//      复现标签」；标签自身的 jamo 真值是打印出来的连通域表，操作员须对照 jamo
//      分解行人工 sanity-check。
//
// 硬边界（设计使然）：
//   - 元音墨与声母墨相触（OBS KR 里 ㅓ 的勾碰到 ㅇ、ㅜ 坐在终声 ㄱ 上）时整个
//     音节渲成**一个**连通域，任何逐域标签都拆不开：脚本打印连通域表并响亮
//     失败。--vowel-comp 救不了融合连通域；换措辞避开融合音节，或整个字形降级
//     处理。探测是不变量不是启发式：>=2 个非终声域才正常（初声+中声，ㅎ/ㅘ 更
//     多），恰好 1 个即初声中声融合。绝不许让 classify() 给孤blob 标 V——横向
//     中声时它就是「最底一组」，生成的规则会把声母涂红、verify 还照样 PASS
//     （A-03 복/요：两者都整字 --vowel-comp 0 全蓝出货，与 auto 判相悖）；
//   - ㅛ/ㅠ 在中部叠两个杯；上杯可能两规则都漏——查表后用 --vowel-comp 覆盖。
//
// 手工微调允许，但必须保住：元音墨全覆盖、红矩形内无声母墨、红矩形与声母墨
// 间距 ≥margin px、verify 绿。
//
// Usage:
//     measure-korean 차 한 잔 --family "OBS KR" --css fonts.css [--out DIR]
//     measure-korean 한 --css fonts.css              # family 从 css @font-face 读
//     measure-korean 원 --css fonts.css --vowel-comp 2,3   # 覆盖标签（1 基）
//
// 需要：Chromium 系浏览器（platform 解析，或设 $CHROME_BIN）。
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { isAbsolute, join, resolve } from 'node:path'
import { FeuilleError, platform, roundHalfEven } from '@feuille/core'
import { pilL, rgbRaw } from './pixels.js'

export const RED: [number, number, number] = [0xC9, 0x40, 0x3A]
export const BLUE: [number, number, number] = [0x2F, 0x5D, 0x9E]

// 由两个声母构成的终声。NFD 不拆成两个 jamo——它发一个 Extended-B 码位
// （많 → ㅁ + ㅏ + ᆭ U+11AD），所以 len(nfd) > 3 永不成立、指望不上。要紧的
// 是标签器的终声带判据吃 T 码位：많 的 T 槽墨坐在右半带而非底部带，会被标成
// 元音。A-03 实测：auto → 3 红矩形（错），--vowel-comp 1 → 1 红矩形。
export const CLUSTER_FINALS = new Set([
  0x11AA, 0x11AC, 0x11AD, 0x11B0, 0x11B1, 0x11B2,
  0x11B3, 0x11B4, 0x11B5, 0x11B6, 0x11B9,
])

// unicodedata.name(T, '?') 只在 CLUSTER_FINALS 分支被调——硬编这 11 条。
const CLUSTER_NAMES: Record<number, string> = {
  0x11AA: 'HANGUL JONGSEONG KIYEOK-SIOS',
  0x11AC: 'HANGUL JONGSEONG NIEUN-CIEUC',
  0x11AD: 'HANGUL JONGSEONG NIEUN-HIEUH',
  0x11B0: 'HANGUL JONGSEONG RIEUL-KIYEOK',
  0x11B1: 'HANGUL JONGSEONG RIEUL-MIEUM',
  0x11B2: 'HANGUL JONGSEONG RIEUL-PIEUP',
  0x11B3: 'HANGUL JONGSEONG RIEUL-SIOS',
  0x11B4: 'HANGUL JONGSEONG RIEUL-THIEUTH',
  0x11B5: 'HANGUL JONGSEONG RIEUL-PHIEUPH',
  0x11B6: 'HANGUL JONGSEONG RIEUL-HIEUH',
  0x11B9: 'HANGUL JONGSEONG PIEUP-SIOS',
}

// —— unicodedata.name 的算法名（UAX34 LVT 转写拼接；Python 实测校准）——
// 19 初声（UAX34 转写；ㅇ 初声在音节名里不出现、ㅈ=J、ㅊ=C——Python 实测校准）
const L_PART = ['G', 'GG', 'N', 'D', 'DD', 'R', 'M', 'B', 'BB', 'S', 'SS', '', 'J', 'JJ', 'C', 'K', 'T', 'P', 'H']
const V_PART = ['A', 'AE', 'YA', 'YAE', 'EO', 'E', 'YEO', 'YE', 'O', 'WA', 'WAE', 'OE', 'YO', 'U', 'WEO', 'WE', 'WI', 'YU', 'EU', 'YI', 'I']
// 28 终声（UAX34 转写；单ㄹ 在终声位是 'L' 不是 'R'——初声位的 ㄹ 才是 R）
const T_PART = ['', 'G', 'GG', 'GS', 'N', 'NJ', 'NH', 'D', 'L', 'LG', 'LM', 'LB', 'LS', 'LT', 'LP', 'LH', 'M', 'B', 'BS', 'S', 'SS', 'NG', 'J', 'C', 'K', 'T', 'P', 'H']

/** unicodedata.name(音节, '?')：HANGUL SYLLABLE + 转写（非音节回 '?'）。 */
export function hangulSyllableName(syl: string): string {
  const cp = syl.codePointAt(0)!
  const S = cp - 0xac00
  if (S < 0 || S >= 11172) return '?'
  return `HANGUL SYLLABLE ${L_PART[Math.floor(S / 588)]!}${V_PART[Math.floor((S % 588) / 28)]!}${T_PART[S % 28]!}`
}

function cp4(s: string): string {
  return s.codePointAt(0)!.toString(16).toUpperCase().padStart(4, '0')
}

// ============ 布尔掩膜（numpy → Uint8Array） ============

export interface BMask {
  h: number
  w: number
  d: Uint8Array
}

export function mNew(h: number, w: number): BMask {
  return { h, w, d: new Uint8Array(h * w) }
}

export function mAny(m: BMask): boolean {
  for (let i = 0; i < m.d.length; i++) if (m.d[i]) return true
  return false
}

export function mCount(m: BMask): number {
  let n = 0
  for (let i = 0; i < m.d.length; i++) if (m.d[i]) n++
  return n
}

export function mOr(a: BMask, b: BMask): BMask {
  const out = mNew(a.h, a.w)
  for (let i = 0; i < out.d.length; i++) out.d[i] = a.d[i] || b.d[i] ? 1 : 0
  return out
}

export function mAnd(a: BMask, b: BMask): BMask {
  const out = mNew(a.h, a.w)
  for (let i = 0; i < out.d.length; i++) out.d[i] = a.d[i] && b.d[i] ? 1 : 0
  return out
}

export function mNot(a: BMask): BMask {
  const out = mNew(a.h, a.w)
  for (let i = 0; i < out.d.length; i++) out.d[i] = a.d[i] ? 0 : 1
  return out
}

/** a & ~b（shape 取 a）。 */
export function mAndNot(a: BMask, b: BMask): BMask {
  const out = mNew(a.h, a.w)
  for (let i = 0; i < out.d.length; i++) out.d[i] = a.d[i] && !b.d[i] ? 1 : 0
  return out
}

/** 方形结构元（半径 r）布尔膨胀——numpy 切片 OR 的逐位移植。 */
export function dilate(m: BMask, r: number): BMask {
  if (r <= 0) return { h: m.h, w: m.w, d: m.d.slice() }
  const out = mNew(m.h, m.w)
  for (let dy = -r; dy <= r; dy++) {
    const ys0 = Math.max(0, dy)
    const ys1 = Math.min(m.h, m.h + dy)
    for (let dx = -r; dx <= r; dx++) {
      const xs0 = Math.max(0, dx)
      const xs1 = Math.min(m.w, m.w + dx)
      for (let y = ys0; y < ys1; y++) {
        const src = (y - dy) * m.w - dx
        const dst = y * m.w
        for (let x = xs0; x < xs1; x++) {
          if (m.d[src + x]) out.d[dst + x] = 1
        }
      }
    }
  }
  return out
}

/** 布尔腐蚀（dilate 的逆对）。 */
export function erode(m: BMask, r: number): BMask {
  return mNot(dilate(mNot(m), r))
}

/** 8 连通连通域；返回 [(ys, xs)] 索引数组（按行主序发现序）。 */
export function labelComponents(m: BMask): Array<{ ys: number[]; xs: number[] }> {
  const seen = new Uint8Array(m.h * m.w)
  const comps: Array<{ ys: number[]; xs: number[] }> = []
  for (let y0 = 0; y0 < m.h; y0++) {
    for (let x0 = 0; x0 < m.w; x0++) {
      const seed = y0 * m.w + x0
      if (!m.d[seed] || seen[seed]) continue
      seen[seed] = 1
      const stack: Array<[number, number]> = [[y0, x0]]
      const ys: number[] = []
      const xs: number[] = []
      while (stack.length > 0) {
        const [y, x] = stack.pop()!
        ys.push(y)
        xs.push(x)
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const ny = y + dy
            const nx = x + dx
            if (ny >= 0 && ny < m.h && nx >= 0 && nx < m.w) {
              const ni = ny * m.w + nx
              if (m.d[ni] && !seen[ni]) {
                seen[ni] = 1
                stack.push([ny, nx])
              }
            }
          }
        }
      }
      comps.push({ ys, xs })
    }
  }
  return comps
}

/** 全 True 最大轴对齐矩形：(area, x0, y0, x1, y1) 或 null（直方图栈算法）。 */
export function largestRect(m: BMask): [number, number, number, number, number] | null {
  const H = m.h
  const W = m.w
  const h = new Array<number>(W + 1).fill(0)
  let best: [number, number, number, number, number] | null = null
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) h[x] = m.d[y * W + x] ? h[x]! + 1 : 0
    const stack: Array<[number, number]> = []
    for (let x = 0; x <= W; x++) {
      const cur = x < W ? h[x]! : 0
      let start = x
      while (stack.length > 0 && stack[stack.length - 1]![1] > cur) {
        const [sx, sh] = stack.pop()!
        const area = sh * (x - sx)
        if (best === null || area > best[0]) best = [area, sx, y - sh + 1, x - 1, y]
        start = sx
      }
      if (stack.length === 0 || stack[stack.length - 1]![1] < cur) stack.push([start, cur])
    }
  }
  return best
}

/** 贪心最大矩形覆盖 + 细笔残条的水平带兜底；返回 (rects, uncovered)。 */
export function rectCover(m0: BMask, cap = 12): [Rect[], BMask] {
  const rects: Rect[] = []
  const m: BMask = { h: m0.h, w: m0.w, d: m0.d.slice() }
  while (mAny(m) && rects.length < cap) {
    const r = largestRect(m)
    if (r === null || r[0] === 0) break
    const [, x0, y0, x1, y1] = r
    rects.push([x0, y0, x1, y1])
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) m.d[y * m.w + x] = 0
    }
  }
  const H = m.h
  const W = m.w
  while (mAny(m) && rects.length < cap) {
    // np.lexsort((xs, ys))[0] = 最上、再最左像素（行主序首像素同值）
    let y = -1
    let x = -1
    let found = false
    for (let yy = 0; yy < H && !found; yy++) {
      for (let xx = 0; xx < W; xx++) {
        if (m.d[yy * W + xx]) {
          y = yy
          x = xx
          found = true
          break
        }
      }
    }
    let x0 = x
    while (x0 > 0 && m.d[y * W + x0 - 1]) x0--
    let x1 = x
    while (x1 + 1 < W && m.d[y * W + x1 + 1]) x1++
    let y1 = y
    let go = true
    while (go && y1 + 1 < H) {
      for (let xx = x0; xx <= x1; xx++) {
        if (!m.d[(y1 + 1) * W + xx]) {
          go = false
          break
        }
      }
      if (go) y1++
    }
    rects.push([x0, y, x1, y1])
    for (let yy = y; yy <= y1; yy++) {
      for (let xx = x0; xx <= x1; xx++) m.d[yy * W + xx] = 0
    }
  }
  return [rects, m]
}

/** 每条边向 ~forbidden（空地/己色余地）外扩到扩不动；保住安全边距。 */
export function expandRects(rects: Rect[], forbidden: BMask, shape: [number, number]): void {
  const [H, W] = shape
  const f = forbidden
  const colAny = (y0: number, y1: number, x: number): boolean => {
    for (let y = y0; y <= y1; y++) if (f.d[y * W + x]) return true
    return false
  }
  const rowAny = (y: number, x0: number, x1: number): boolean => {
    for (let x = x0; x <= x1; x++) if (f.d[y * W + x]) return true
    return false
  }
  for (const r of rects) {
    let [x0, y0, x1, y1] = r
    while (x0 > 0 && !colAny(y0, y1, x0 - 1)) x0--
    while (y0 > 0 && !rowAny(y0 - 1, x0, x1)) y0--
    while (x1 + 1 < W && !colAny(y0, y1, x1 + 1)) x1++
    while (y1 + 1 < H && !rowAny(y1 + 1, x0, x1)) y1++
    r[0] = x0
    r[1] = y0
    r[2] = x1
    r[3] = y1
  }
}

/** 去掉被别的矩形完全包含的（外扩常让残条收敛成同一条带）。 */
export function dedupeRects(rects: Rect[]): Rect[] {
  const keep: Rect[] = []
  for (const r of [...rects].sort(
    (a, b) => (b[2] - b[0] + 1) * (b[3] - b[1] + 1) - (a[2] - a[0] + 1) * (a[3] - a[1] + 1),
  )) {
    if (!keep.some((k) => k[0] <= r[0] && k[1] <= r[1] && k[2] >= r[2] && k[3] >= r[3])) {
      keep.push(r)
    }
  }
  return keep
}

/** 红矩形垫片：盖住全部 `red` 墨、离 `blue` 墨 ≥margin。抗锯齿掩膜有 1px 锯
 * 齿洞：先盖闭合核、外扩进安全区、再残条覆盖。返回 (rects, error|None)。 */
export function coverVowel(red: BMask, blue: BMask, margin: number): [Rect[] | null, string | null] {
  if (mAny(mAnd(red, blue))) return [null, 'vowel and consonant ink overlap']
  const forbidden = dilate(blue, margin)
  const core = erode(dilate(red, 2), 2)
  let [rects] = rectCover(core, 12)
  expandRects(rects, forbidden, [red.h, red.w])

  const uncovered = (): BMask => {
    const u = mNew(red.h, red.w)
    for (const [x0, y0, x1, y1] of rects) {
      for (let y = y0; y <= y1; y++) {
        for (let x = x0; x <= x1; x++) u.d[y * red.w + x] = 1
      }
    }
    return mAndNot(red, u)
  }

  if (mAny(uncovered())) {
    const [extra] = rectCover(uncovered(), 4)
    expandRects(extra, forbidden, [red.h, red.w])
    rects = rects.concat(extra)
  }
  rects = dedupeRects(rects)
  if (mAny(uncovered())) return [null, `${mCount(uncovered())} vowel px not coverable`]
  for (const [x0, y0, x1, y1] of rects) {
    // 蓝墨绝不许落进红矩形
    let hit = false
    for (let y = y0; y <= y1 && !hit; y++) {
      for (let x = x0; x <= x1; x++) {
        if (blue.d[y * red.w + x]) {
          hit = true
          break
        }
      }
    }
    if (hit) return [null, 'patch would paint consonant ink red']
  }
  return [rects, null]
}

// ============ jamo / 标签 / 规则 ============

export type Rect = [number, number, number, number]

export interface Comp {
  mask: BMask
  x0: number
  x1: number
  y0: number
  y1: number
  cx: number
  cy: number
}

/** 一个预组 Hangul 音节的 NFD jamo → (初声, 中声, 终声|None)。 */
export function jamoDeomp(syl: string): [string, string, string | null] {
  const d = syl.normalize('NFD')
  const cps = [...d]
  if (cps.length < 2 || !cps.every((c) => {
    const v = c.codePointAt(0)!
    return v >= 0x1100 && v <= 0x11FF
  })) {
    throw new FeuilleError(`'${syl}': expected one precomposed Hangul syllable`)
  }
  const L = cps[0]!
  const V = cps[1]!
  const T = cps.length > 2 ? cps[2]! : null
  const lcp = L.codePointAt(0)!
  const vcp = V.codePointAt(0)!
  if (!(lcp >= 0x1100 && lcp <= 0x1112) || !(vcp >= 0x1161 && vcp <= 0x1175)
    || (T !== null && !(T.codePointAt(0)! >= 0x11A8 && T.codePointAt(0)! <= 0x11C2))) {
    throw new FeuilleError(`'${syl}': unexpected jamo decomposition ${d}`)
  }
  return [L, V, T]
}

/** 逐连通域标 'V'/'C'；返回 (labels, error|None)。几何先验见模块头步骤 3。
 * 已知局限：ㅛ/ㅠ 的杯叠在中心右的中部，上杯可能漏出规则 2–3；查输出的规则表，
 * 不对就 --vowel-comp 覆盖。 */
export function classify(comps: Comp[], hasT: boolean, medialCp: number): [string[] | null, string | null] {
  const n = comps.length
  const left = Math.min(...comps.map((c) => c.x0))
  const top = Math.min(...comps.map((c) => c.y0))
  const wink = Math.max(...comps.map((c) => c.x1)) - left
  const hink = Math.max(...comps.map((c) => c.y1)) - top
  const hasH = 0x1169 <= medialCp && medialCp <= 0x1174
  const tIdx = new Set<number>()
  if (hasT) {
    const thr = top + 0.80 * Math.max(hink, 1)
    for (let i = 0; i < n; i++) if (comps[i]!.y1 > thr) tIdx.add(i)
    if (tIdx.size === 0) return [null, 'final jamo present but no component reaches the bottom band']
  }
  const labels = new Array<string>(n).fill('C')
  const rest: number[] = []
  for (let i = 0; i < n; i++) if (!tIdx.has(i)) rest.push(i)
  // 初声+中声融合：正常音节留下 >=2 个非终声连通域（初声 + 中声，ㅎ 型初声与
  // ㅘ 型中声只会更多）。恰好 1 个即元音墨贴着声母墨长成一整块——任何标签都
  // 拆不开。没有这道检查 classify 会乐呵呵把这块标 V（has_h 时它就是「最底一
  // 组」）、生成的规则把**声母**涂红——verify 还 PASS，因为 verify 只校验 CSS
  // 复现标签。A-03 实测：복 ㅂ+ㅗ → 2 域，规则 = 全宽 67.2% 红带盖住整个 ㅂ+ㅗ
  // 块；요 ㅇ+ㅛ → 1 域，规则 = 100% 红（整字含 ㅇ）。两者都 "PASS"。
  if (rest.length === 1) {
    return [null, 'initial and medial ink are ONE fused component — this '
      + 'syllable cannot be split by labeling; use --vowel-comp 0 '
      + '(whole-consonant blue) or the .cv fusion gradient']
  }
  for (const i of rest) {
    if (comps[i]!.cx - left > 0.50 * wink) labels[i] = 'V'
  }
  if (hasH && rest.length > 0) {
    // 横向元音墨 = 非终声域的最底一组；相对窗口胜过绝对阈值，因为 ㅜ/ㅗ 的
    // 分叉会把 bbox 中心拉离笔画的带位。
    const cyMax = Math.max(...rest.map((i) => comps[i]!.cy))
    for (const i of rest) {
      if (comps[i]!.cy >= cyMax - 0.15 * Math.max(hink, 1)) labels[i] = 'V'
    }
  }
  if (!labels.includes('V')) return [null, 'no component labeled vowel']
  return [labels, null]
}

/** CSS 规则。定位故意用双值百分比形式：百分比遵循对齐公式
 * offset = P% * (area - image)——Chrome 对所有百分比定位都这么算（4 值的
 * `left X%` 形式在那里不是单纯偏移——实测，别信）。 */
export function emitRule(cls: string, rects: Rect[], w: number, h: number): string {
  const imgs = [...rects.map(() => 'linear-gradient(var(--vowel),var(--vowel))'),
    'linear-gradient(var(--cons),var(--cons))'].join(', ')
  const pos: string[] = []
  for (const [x0, y0, x1, y1] of rects) {
    const iw = x1 - x0 + 1
    const ih = y1 - y0 + 1
    const px = w > iw ? (100.0 * x0) / (w - iw) : 0.0
    const py = h > ih ? (100.0 * y0) / (h - ih) : 0.0
    pos.push(`${px.toFixed(1)}% ${py.toFixed(1)}%`)
  }
  const size = rects.map(([x0, y0, x1, y1]) =>
    `${(((x1 - x0 + 1) / w) * 100).toFixed(1)}% ${(((y1 - y0 + 1) / h) * 100).toFixed(1)}%`).join(', ')
    + ', 100% 100%'
  return `.${cls} {\n`
    + `  background-image: ${imgs};\n`
    + `  background-position: ${pos.join(', ')}, 0 0;\n`
    + `  background-size: ${size};\n`
    + `}`
}

// ============ 测量页模板 ============

const DUMP_RECTS_JS = `function dumpRects() {
  const out = {};
  for (const el of document.querySelectorAll(".ksyl")) {
    const r = el.getBoundingClientRect();
    out[el.id] = [r.x, r.y, r.width, r.height];
  }
  document.getElementById("rects").textContent = "RECTS " + JSON.stringify(out);
}
// probe-font-decode race：rect 必须在字体子集真正解码后取——verify 行里
// patched span 的 x 取决于前一个 gt span 的 advance，fallback 度量会整体
// 错位，verify 全 FAIL 且模式一致（vowel 0 / consonant 全错）。
(document.fonts && document.fonts.ready
  ? document.fonts.ready.then(() => setTimeout(dumpRects, 300))
  : setTimeout(dumpRects, 0));`

function buildTpl(css: string, rows: string, rowpad: number, fs: number, family: string): string {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
${css}
body { margin: 0; background: #fff; }
.row { padding-top: ${rowpad}px; padding-left: 100px; }
.ksyl { display: inline-block; font-size: ${fs}px; line-height: 1.28;
        font-family: ${family}; color: #000; }
pre { position: absolute; top: 0; left: -9999px; }
</style></head><body>
${rows}
<pre id="rects">RECTS {}</pre>
<script>
${DUMP_RECTS_JS}
</script></body></html>`
}

function verifyTpl(css: string, rules: string, rows: string, rowpad: number, fs: number, family: string): string {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
${css}
:root { --vowel: #c9403a; --cons: #2f5d9e; }
body { margin: 0; background: #fff; }
.row { padding-top: ${rowpad}px; padding-left: 100px; }
.ksyl { display: inline-block; font-size: ${fs}px; line-height: 1.28;
        font-family: ${family}; background-repeat: no-repeat; }
.gap { display: inline-block; width: 80px; }
.gt { color: #000; }
.pt { color: transparent; -webkit-background-clip: text; background-clip: text; }
${rules}
pre { position: absolute; top: 0; left: -9999px; }
</style></head><body>
${rows}
<pre id="rects">RECTS {}</pre>
<script>
${DUMP_RECTS_JS}
</script></body></html>`
}

// ============ chrome ============

let CHROME = '' // main 里解析（模块级可变，镜像 Python global）

/** 参数与 library 的 `textlayer._shot_args` 对齐（实测过的组合）。
 * ⚠ 不要加 --user-data-dir：macOS + Edge 上带它图能出来但进程永不退出。 */
function renderChrome(url: string, w: number, h: number, out: string | null, dom = false): string {
  const args = [CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
    '--virtual-time-budget=10000', `--window-size=${w},${h}`,
    '--force-device-scale-factor=1', '--hide-scrollbars']
  if (dom) args.push('--dump-dom', url)
  else args.push(`--screenshot=${out}`, url)
  if (!dom && out !== null && !isAbsolute(out)) {
    // Windows + Edge headless：相对路径的 --screenshot= 静默失败（退出 0、不写
    // 文件）；macOS/Linux 无此问题。统一 resolve 成绝对路径。
    args[args.length - 2] = `--screenshot=${resolve(out)}`
  }
  const r = spawnSync(args[0]!, args.slice(1), { timeout: 120000, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (r.error) throw r.error
  if (r.status !== 0) throw new FeuilleError(`chrome failed: ${(r.stderr ?? '').slice(0, 500)}`)
  return r.stdout ?? ''
}

// ============ 图像装载 ============

async function grayMask(path: string): Promise<BMask> {
  const im = await rgbRaw(path)
  const d = new Uint8Array(im.width * im.height)
  for (let i = 0; i < d.length; i++) {
    const o = i * 3
    d[i] = pilL(im.data[o]!, im.data[o + 1]!, im.data[o + 2]!) < 128 ? 1 : 0
  }
  return { h: im.height, w: im.width, d }
}

/** 子框裁剪（numpy 切片越界静默收边——镜像；坐标约定非负）。 */
function subMask(m: BMask, x0: number, y0: number, w: number, h: number): BMask {
  const x1 = Math.min(m.w, x0 + w)
  const y1 = Math.min(m.h, y0 + h)
  const ww = Math.max(0, x1 - x0)
  const hh = Math.max(0, y1 - y0)
  const d = new Uint8Array(ww * hh)
  for (let y = 0; y < hh; y++) {
    const src = (y0 + y) * m.w + x0
    d.set(m.d.subarray(src, src + ww), y * ww)
  }
  return { h: hh, w: ww, d }
}

function subRgb(im: { data: Uint8Array; width: number; height: number }, x0: number, y0: number, w: number, h: number): { d: Uint8Array; w: number; h: number } {
  const x1 = Math.min(im.width, x0 + w)
  const y1 = Math.min(im.height, y0 + h)
  const ww = Math.max(0, x1 - x0)
  const hh = Math.max(0, y1 - y0)
  const d = new Uint8Array(ww * hh * 3)
  for (let y = 0; y < hh; y++) {
    const src = ((y0 + y) * im.width + x0) * 3
    d.set(im.data.subarray(src, src + ww * 3), y * ww * 3)
  }
  return { d, w: ww, h: hh }
}

// ============ main ============

interface Rec {
  syl: string
  err: string | null
  rule: string | null
  w: number
  h: number
  comps?: Comp[]
  labels?: string[]
  red?: BMask
  vrow?: string
}

interface MArgs {
  syllables: string[]
  family: string | null
  css: string | null
  out: string
  fontSize: number
  margin: number
  vowelComp: string | null
}

function parseArgs(argv: string[]): MArgs {
  const syllables: string[] = []
  let family: string | null = null
  let css: string | null = null
  let out = 'k_measure'
  let fontSize = 200
  let margin = 2
  let vowelComp: string | null = null
  const intArg = (v: string): number => {
    const n = Number(v)
    if (!Number.isInteger(n)) throw new FeuilleError(`${v} 不是整数`)
    return n
  }
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i]!
    const take = (): string => {
      const v = argv[++i]
      if (v === undefined) throw new FeuilleError(`${t} 缺值`)
      return v
    }
    if (t === '--family') family = take()
    else if (t === '--css') css = take()
    else if (t === '--out') out = take()
    else if (t === '--font-size') fontSize = intArg(take())
    else if (t === '--margin') margin = intArg(take())
    else if (t === '--vowel-comp') vowelComp = take()
    else if (t.startsWith('--')) throw new FeuilleError(`未知旗标：${t}`)
    else syllables.push(t)
  }
  return { syllables, family, css, out, fontSize, margin, vowelComp }
}

export async function main(argv: string[]): Promise<number> {
  const a = parseArgs(argv)
  if (a.syllables.length === 0) {
    console.error('usage: feuille poster measure-korean <syllables…> [--family "OBS KR"] [--css fonts.css]\n'
      + '                               [--out DIR] [--font-size 200] [--margin 2] [--vowel-comp I,J]')
    return 2
  }
  if (a.vowelComp !== null && a.syllables.length !== 1) {
    throw new FeuilleError('--vowel-comp needs exactly one syllable')
  }

  // 浏览器解析走 @feuille/core platform 唯一事实源，$CHROME_BIN 优先
  CHROME = process.env['CHROME_BIN'] || ''
  if (!CHROME) CHROME = platform.browserPath() || ''
  if (!CHROME) {
    throw new FeuilleError('找不到 Chromium 系浏览器：请装 Chrome / Edge，或设 $CHROME_BIN')
  }

  let css = ''
  if (a.css !== null) css = readFileSync(a.css, 'utf-8')
  let family = a.family
  if (family === null) {
    const fams = [...css.matchAll(/font-family:\s*['"]([^'"]+)/g)].map((m) => m[1]!)
    if (fams.length === 0) throw new FeuilleError('pass --family (no @font-face found in --css)')
    family = `'${fams[fams.length - 1]!}'`
  }

  mkdirSync(a.out, { recursive: true })
  const out = a.out
  const rowpad = 100
  const fs = a.fontSize
  const boxH = roundHalfEven(fs * 1.28)

  // ---- pass 1：黑墨测量 ----------------------------------------------
  const rows = a.syllables
    .map((s, i) => `<div class="row"><span class="ksyl" id="k${i}">${s}</span></div>`)
    .join('\n')
  const build = join(out, 'measure_build.html')
  writeFileSync(build, buildTpl(css, rows, rowpad, fs, family), 'utf-8')
  const url = 'file://' + resolve(build)
  const winW = 100 + fs * 2
  const winH = (rowpad + boxH) * a.syllables.length + 100
  const dom = renderChrome(url, winW, winH, null, true)
  const m = dom.match(/RECTS (\{[\s\S]*?\})/)
  if (!m) throw new FeuilleError('rect dump not found in DOM — chrome may not have run the JS')
  const rects: Record<string, [number, number, number, number]> = JSON.parse(m[1]!)
  const shot = join(out, 'measure_ink.png')
  renderChrome(url, winW, winH, shot)
  const ink = await grayMask(shot)

  console.log(`# measured on ${family} @ ${fs}px  (ink mask: ${shot})`)
  const recs: Rec[] = []
  for (const [i, syl] of a.syllables.entries()) {
    const cls = 'k' + cp4(syl)
    const [, V, T] = jamoDeomp(syl) // 初声 L 在后续流程不读——与 Python 解包后不用一致
    const nfd = syl.normalize('NFD')
    // 码位是音节的身份——绝不从「看到的字形」反推规则名（或 fonts.json 字符）：
    // ㅀ(rieul-hieuh) 和 ㄶ(nieun-hieuh) 渲染近乎一样，音节、误读的邻字与
    // 非词肉眼不可分。打印真值（码位 + Unicode 名 + 完整 NFD），操作员不用猜。
    if (T !== null && CLUSTER_FINALS.has(T.codePointAt(0)!)) {
      console.log(
        `#   ⚠ CLUSTER final ${CLUSTER_NAMES[T.codePointAt(0)!] ?? '?'} — its two `
        + `consonants share one jamo codepoint, and this final's ink may `
        + `sit in the RIGHT half-band (vowel territory) instead of the `
        + `bottom band; the labeler will then call it a vowel. Audit the `
        + `component table below by hand and override with --vowel-comp `
        + `if wrong (A-03 많: auto gave 3 red rects, --vowel-comp 1 gave `
        + `the correct 1)`,
      )
    }
    const [x, y, w, h] = rects[`k${i}`]!
    const sub = subMask(ink, Math.trunc(roundHalfEven(x)), Math.trunc(roundHalfEven(y)),
      Math.trunc(roundHalfEven(w)), Math.trunc(roundHalfEven(h)))
    if (!mAny(sub)) throw new FeuilleError(`${syl}: no ink in element box — wrong rect?`)
    const comps: Comp[] = []
    for (const { ys, xs } of labelComponents(sub)) {
      const cm = mNew(sub.h, sub.w)
      for (let j = 0; j < ys.length; j++) cm.d[ys[j]! * sub.w + xs[j]!] = 1
      const x0 = Math.min(...xs)
      const x1 = Math.max(...xs)
      const y0 = Math.min(...ys)
      const y1 = Math.max(...ys)
      comps.push({ mask: cm, x0, x1, y0, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 })
    }
    console.log(
      `# ${syl} U+${cp4(syl)} ${hangulSyllableName(syl)} (.${cls}) = `
      + [...nfd].map((c) => `${c} U+${cp4(c)}`).join(' + ')
      + `  (box ${w.toFixed(2)}x${roundHalfEven(h, 0).toFixed(0)})`,
    )
    const rec: Rec = { syl, err: null, rule: null, w, h }
    recs.push(rec)
    let labels: string[]
    if (a.vowelComp !== null) {
      const sel = new Set(a.vowelComp.split(',').map((t) => Number(t) - 1))
      labels = comps.map((_, j) => (sel.has(j) ? 'V' : 'C'))
    } else {
      const [ls, err] = classify(comps, T !== null, V.codePointAt(0)!)
      if (err !== null) {
        rec.err = `LABEL FAIL: ${err}`
        console.log(`#   !! ${err} — rerun with --vowel-comp`)
        for (const [j, c] of comps.entries()) {
          console.log(`#   comp${j + 1}: x[${c.x0},${c.x1}] y[${c.y0},${c.y1}] → ?`)
        }
        continue
      }
      labels = ls!
    }
    rec.comps = comps
    rec.labels = labels
    for (const [j, c] of comps.entries()) {
      console.log(`#   comp${j + 1}: x[${c.x0},${c.x1}] y[${c.y0},${c.y1}] → ${labels[j]}`)
    }
    let red = mNew(sub.h, sub.w)
    let blue = mNew(sub.h, sub.w)
    for (const [j, c] of comps.entries()) {
      if (labels[j] === 'V') red = mOr(red, c.mask)
      else blue = mOr(blue, c.mask)
    }
    if (mAny(mAnd(red, dilate(blue, 1))) || mAny(mAnd(blue, dilate(red, 1)))) {
      console.log('#   !! ink of different labels within 1px — margin at risk')
    }
    if (mAny(mAnd(red, dilate(blue, a.margin)))) {
      console.log('#   !! vowel ink lies within the margin of consonant ink')
    }
    const [rrects, err] = coverVowel(red, blue, a.margin)
    if (err !== null) {
      rec.err = `COVER FAIL: ${err}`
      console.log(`#   !! ${err}`)
      continue
    }
    rec.red = red
    rec.rule = emitRule(cls, rrects!, w, h)
    console.log(`#   patches: ${rrects!.length} red rect(s) over full-box blue`)
  }

  const ok = recs.filter((r) => r.rule !== null)
  if (ok.length === 0) throw new FeuilleError('no syllable produced a rule')
  console.log()
  for (const r of ok) {
    console.log(r.rule)
    console.log()
  }

  // ---- pass 2：真渲生成的规则做 verify ------------------------------
  for (const [i, r] of recs.entries()) {
    if (r.rule === null) continue
    const cls = 'k' + cp4(r.syl)
    r.vrow = `<div class="row"><span class="ksyl gt" id="g${i}">${r.syl}</span>`
      + `<span class="gap"></span>`
      + `<span class="ksyl pt ${cls}" id="p${i}">${r.syl}</span></div>`
  }
  const vrows = recs.filter((r) => r.rule !== null).map((r) => r.vrow!).join('\n')
  const vbuild = join(out, 'verify_build.html')
  writeFileSync(vbuild, verifyTpl(css, ok.map((r) => r.rule!).join('\n'), vrows, rowpad, fs, family), 'utf-8')
  const vurl = 'file://' + resolve(vbuild)
  const vH = (rowpad + boxH) * recs.length + 100
  const vdom = renderChrome(vurl, winW + 300, vH, null, true)
  const m2 = vdom.match(/RECTS (\{[\s\S]*?\})/)
  if (!m2) throw new FeuilleError('verify rect dump not found — chrome may not have run the JS')
  const vrects: Record<string, [number, number, number, number]> = JSON.parse(m2[1]!)
  const vshot = join(out, 'verify_ink.png')
  renderChrome(vurl, winW + 300, vH, vshot)
  const rgb = await rgbRaw(vshot)
  const gray = await grayMask(vshot)

  let failed = false
  for (const r of recs) {
    if (r.err !== null) {
      console.log(`${r.syl}: ${r.err}`)
      failed = true
    } else if (r.rule === null) failed = true
  }
  for (const [i, r] of recs.entries()) {
    if (r.rule === null) continue
    const [gx, gy, gw, gh] = vrects[`g${i}`]!
    const [px0, py0, pw, ph] = vrects[`p${i}`]!
    const g0x = Math.trunc(roundHalfEven(gx))
    const g0y = Math.trunc(roundHalfEven(gy))
    const gt = subMask(gray, g0x, g0y, Math.trunc(roundHalfEven(gw)), Math.trunc(roundHalfEven(gh)))
    const expV = mNew(gt.h, gt.w)
    for (const [j, c] of r.comps!.entries()) {
      if (r.labels![j] === 'V') {
        for (let y = 0; y < expV.h; y++) {
          for (let x = 0; x < expV.w; x++) {
            if (c.mask.d[y * c.mask.w + x]) expV.d[y * expV.w + x] = 1
          }
        }
      }
    }
    const p0x = Math.trunc(roundHalfEven(px0))
    const p0y = Math.trunc(roundHalfEven(py0))
    const ptRgb = subRgb(rgb, p0x, p0y, Math.trunc(roundHalfEven(pw)), Math.trunc(roundHalfEven(ph)))
    if (ptRgb.h !== gt.h || ptRgb.w !== gt.w) {
      r.err = `VERIFY FAIL: box (${ptRgb.h}, ${ptRgb.w}) != (${gt.h}, ${gt.w})`
      console.log(`${r.syl}: ${r.err}`)
      failed = true
      continue
    }
    const isv = mNew(gt.h, gt.w)
    for (let y = 0; y < ptRgb.h; y++) {
      for (let x = 0; x < ptRgb.w; x++) {
        const o = (y * ptRgb.w + x) * 3
        const dRed = Math.abs(ptRgb.d[o]! - RED[0]) + Math.abs(ptRgb.d[o + 1]! - RED[1])
          + Math.abs(ptRgb.d[o + 2]! - RED[2])
        const dBlue = Math.abs(ptRgb.d[o]! - BLUE[0]) + Math.abs(ptRgb.d[o + 1]! - BLUE[1])
          + Math.abs(ptRgb.d[o + 2]! - BLUE[2])
        if (dRed < dBlue) isv.d[y * ptRgb.w + x] = 1
      }
    }
    const badV = mCount(mAnd(mAnd(gt, expV), mNot(dilate(isv, 1))))
    const badC = mCount(mAnd(mAnd(gt, mNot(expV)), mNot(dilate(mNot(isv), 1))))
    const tag = badV + badC === 0 ? 'PASS' : 'FAIL'
    if (tag === 'FAIL') failed = true
    console.log(`verify ${r.syl}: ${tag}  (${badV + badC} wrong px of `
      + `${mCount(gt)} ink px — vowel ${badV}, consonant ${badC})`)
  }
  return failed ? 1 : 0
}
