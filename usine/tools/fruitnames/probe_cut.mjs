// probe_cut.mjs — 一次性诊断：看清抠底失败在哪一步
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe', 'v2_cream_short.jpg'))
const { data, info } = await sharp(p).removeAlpha().raw().toBuffer({ resolveWithObject: true })
const W = info.width, H = info.height

function dominant() {
  const counts = new Map()
  for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) {
    const o = (y * W + x) * 3
    const k = ((data[o] >> 2) << 12) | ((data[o + 1] >> 2) << 6) | (data[o + 2] >> 2)
    counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  let best = -1, bk = 0
  for (const [k, c] of counts) if (c > best) { best = c; bk = k }
  return { rgb: [((bk >> 12) & 63) << 2, ((bk >> 6) & 63) << 2, (bk & 63) << 2], count: best, sampled: Math.ceil(W / 2) * Math.ceil(H / 2) }
}
const dom = dominant()
console.log('众数底色', dom.rgb, '命中采样点', dom.count, '/', dom.sampled, `(${(dom.count / dom.sampled * 100).toFixed(1)}%)`)

const dist = (i) => Math.abs(data[i] - dom.rgb[0]) + Math.abs(data[i + 1] - dom.rgb[1]) + Math.abs(data[i + 2] - dom.rgb[2])
for (const TOL of [20, 30, 42, 60, 80, 100]) {
  let n = 0
  for (let q = 0; q < W * H; q++) if (dist(q * 4) <= TOL) n++
  // 边界上有多少近底色像素（洪水填充的种子）
  let seeds = 0
  for (let x = 0; x < W; x++) if (dist((0 * W + x) * 4) <= TOL) seeds++
  for (let x = 0; x < W; x++) if (dist(((H - 1) * W + x) * 4) <= TOL) seeds++
  for (let y = 0; y < H; y++) if (dist((y * W + 0) * 4) <= TOL) seeds++
  for (let y = 0; y < H; y++) if (dist((y * W + W - 1) * 4) <= TOL) seeds++
  console.log(`TOL=${String(TOL).padStart(3)}  近底色像素 ${String(n).padStart(8)} (${(n / (W * H) * 100).toFixed(1)}%)  边界种子 ${seeds}`)
}
