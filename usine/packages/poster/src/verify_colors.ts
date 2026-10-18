// verify_colors.ts — 渲出的 poster.png 的像素验收：网格线探测 + 逐格颜色
// 统计。抓空格子、缺色、豆腐块（大词该有墨的地方没墨）。
// （promoted from skills/one-page-poster/scripts/verify_colors.py，P5-7e 归流）
//
// Usage: verify-colors <poster.png> [--cols 3] [--rows 4] [--langs a,b,c]
//                      [--line d9cdb7]
// （网格线探测与缩放无关——任意渲染倍率可用）
// 颜色目标（tol 45）：--red c9403a --blue 2f5d9e --gray a2967f --ink 2c2620
// 按海报调色板改目标值。某格 0 red 或 0 blue 记为问题（纯红海报传
// --allow-missing blue）。
import { FeuilleError, roundHalfEven } from '@feuille/core'
import { hex6, rgbRaw } from './pixels.js'

interface Args {
  png: string
  cols: number
  rows: number
  langs: string
  line: string
  red: string
  blue: string
  gray: string
  ink: string
  allowMissing: string
}

const USAGE = 'usage: feuille poster verify-colors <poster.png> [--cols 3] [--rows 4] [--langs a,b,c]\n' +
  '                         [--line d9cdb7] [--red c9403a] [--blue 2f5d9e] [--gray a2967f]\n' +
  '                         [--ink 2c2620] [--allow-missing red,blue,gray,ink]'

function parseArgs(argv: string[]): { a: Args } | { code: number } {
  let png: string | undefined
  let cols = 3
  let rows = 4
  let langs = ''
  let line = 'd9cdb7'
  let red = 'c9403a'
  let blue = '2f5d9e'
  let gray = 'a2967f'
  let ink = '2c2620'
  let allowMissing = ''
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
    if (t === '--cols') cols = intArg(take())
    else if (t === '--rows') rows = intArg(take())
    else if (t === '--langs') langs = take()
    else if (t === '--line') line = take()
    else if (t === '--red') red = take()
    else if (t === '--blue') blue = take()
    else if (t === '--gray') gray = take()
    else if (t === '--ink') ink = take()
    else if (t === '--allow-missing') allowMissing = take()
    else if (t.startsWith('--')) throw new FeuilleError(`未知旗标：${t}`)
    else png = t
  }
  if (png === undefined) return { code: 2 }
  return { a: { png, cols, rows, langs, line, red, blue, gray, ink, allowMissing } }
}

/** 间隙 ≤2 的列簇 → 均值（Python cluster）。 */
function cluster(vals: number[]): number[] {
  const out: number[][] = []
  for (const v of vals) {
    if (out.length && v - out[out.length - 1]![out.length - 1]! <= 2) out[out.length - 1]!.push(v)
    else out.push([v])
  }
  return out.map((c) => c.reduce((s, v) => s + v, 0) / c.length)
}

export async function main(argv: string[]): Promise<number> {
  const parsed = parseArgs(argv)
  if ('code' in parsed) {
    console.error(USAGE)
    return parsed.code
  }
  const a = parsed.a
  const TARGETS: Record<string, [number, number, number]> = {
    red: hex6(a.red), blue: hex6(a.blue), gray: hex6(a.gray), ink: hex6(a.ink),
  }
  const LANGS = a.langs
    ? a.langs.split(',')
    : Array.from({ length: a.cols * a.rows }, (_, i) => `cell${i + 1}`)

  const im = await rgbRaw(a.png)
  const { data, width: W, height: H } = im
  const px = (x: number, y: number): [number, number, number] => {
    const o = (y * W + x) * 3
    return [data[o]!, data[o + 1]!, data[o + 2]!]
  }
  const close = (p: [number, number, number], t: [number, number, number], tol = 45): boolean =>
    Math.abs(p[0] - t[0]) <= tol && Math.abs(p[1] - t[1]) <= tol && Math.abs(p[2] - t[2]) <= tol

  // ---- 网格线探测 ----
  const LINE = hex6(a.line)
  const ysProbe: number[] = []
  for (let y = Math.trunc(H * 0.25); y < Math.trunc(H * 0.95); y += 7) ysProbe.push(y)
  const vcols: number[] = []
  for (let x = 0; x < W; x++) {
    let n = 0
    for (const y of ysProbe) if (close(px(x, y), LINE, 18)) n++
    if (n > ysProbe.length * 0.6) vcols.push(x)
  }
  const vlines = cluster(vcols)
  const xsProbe: number[] = []
  for (let x = Math.trunc(W * 0.05); x < Math.trunc(W * 0.95); x += 7) xsProbe.push(x)
  const hrows: number[] = []
  for (let y = 0; y < H; y++) {
    let n = 0
    for (const x of xsProbe) if (close(px(x, y), LINE, 18)) n++
    if (n > xsProbe.length * 0.6) hrows.push(y)
  }
  const hlines = cluster(hrows)
  console.log(`vertical lines: [${vlines.map((v) => roundHalfEven(v, 1).toFixed(1)).join(', ')}]`)
  console.log(`horizontal lines: [${hlines.map((v) => roundHalfEven(v, 1).toFixed(1)).join(', ')}]`)

  // Python assert：网格没找到 → 响亮失败
  if (!(vlines.length >= a.cols + 1 && hlines.length >= a.rows + 1)) {
    throw new FeuilleError('grid not found')
  }

  const problems: string[] = []
  let k = 0
  for (let r = 0; r < a.rows; r++) {
    for (let c = 0; c < a.cols; c++) {
      const x0 = Math.trunc(vlines[c]!) + 3
      const x1 = Math.trunc(vlines[c + 1]!) - 3
      const y0 = Math.trunc(hlines[r]!) + 3
      const y1 = Math.trunc(hlines[r + 1]!) - 3
      const cnt: Record<string, number> = { red: 0, blue: 0, gray: 0, ink: 0 }
      for (let yy = y0; yy < y1; yy += 2) {
        // step 2 采样：存在性统计足够
        for (let xx = x0; xx < x1; xx += 2) {
          const p = px(xx, yy)
          for (const kk of ['red', 'blue', 'gray', 'ink'] as const) {
            if (close(p, TARGETS[kk]!)) {
              cnt[kk] = (cnt[kk] ?? 0) + 1
              break
            }
          }
        }
      }
      const name = k < LANGS.length ? LANGS[k]! : `cell${k + 1}`
      k++
      console.log(
        `${name.padEnd(10)} red=${String(cnt['red']).padStart(6)} blue=${String(cnt['blue']).padStart(6)}`
          + ` gray=${String(cnt['gray']).padStart(5)} ink=${String(cnt['ink']).padStart(6)}`,
      )
      const allow = a.allowMissing ? a.allowMissing.split(',') : []
      for (const kk of ['red', 'blue', 'gray', 'ink'] as const) {
        if (cnt[kk] === 0 && !allow.includes(kk)) problems.push(`${name}: NO ${kk} pixels`)
      }
    }
  }

  console.log()
  if (problems.length > 0) {
    console.log('PROBLEMS:')
    for (const p of problems) console.log(` - ${p}`)
    return 1
  }
  console.log('all cells OK')
  return 0
}
