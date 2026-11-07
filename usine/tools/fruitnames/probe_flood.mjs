// probe_flood.mjs — 一次性诊断：洪水填充到底扩散了多少
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe', 'v2_cream_short.jpg'))
const { data, info } = await sharp(p).removeAlpha().raw().toBuffer({ resolveWithObject: true })
const W = info.width, H = info.height

const counts = new Map()
for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) {
  const o = (y * W + x) * 3
  const k = ((data[o] >> 2) << 12) | ((data[o + 1] >> 2) << 6) | (data[o + 2] >> 2)
  counts.set(k, (counts.get(k) ?? 0) + 1)
}
let best = -1, bk = 0
for (const [k, c] of counts) if (c > best) { best = c; bk = k }
const bg = [((bk >> 12) & 63) << 2, ((bk >> 6) & 63) << 2, (bk & 63) << 2]
console.log('底色', bg)

const dist = (i) => Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2])
const TOL = 42
const near = new Uint8Array(W * H)
let nearCount = 0
for (let q = 0; q < W * H; q++) { if (dist(q * 4) <= TOL) { near[q] = 1; nearCount++ } }
console.log('near 像素', nearCount)

const mask = new Uint8Array(W * H)
const stack = []
let seedCount = 0
function push(x, y) {
  if (x < 0 || y < 0 || x >= W || y >= H) return
  const q = y * W + x
  if (mask[q]) return
  if (!near[q]) { seedCount++; return }   // 诊断：撞到非近底色就停
  mask[q] = 1
  stack.push(q)
}
for (let x = 0; x < W; x++) { push(x, 0); push(x, H - 1) }
for (let y = 0; y < H; y++) { push(0, y); push(W - 1, y) }
console.log('边界种子栈初始', stack.length)

let iter = 0
while (stack.length) {
  const q = stack.pop()
  const x = q % W, y = (q / W) | 0
  push(x + 1, y); push(x - 1, y); push(x, y + 1); push(x, y - 1)
  iter++
  if (iter > W * H * 4) break
}
let filled = 0
for (let q = 0; q < W * H; q++) if (mask[q]) filled++
console.log('洪水填充后 mask 像素', filled, '期望 ≈', nearCount)
console.log('填充率', (filled / nearCount * 100).toFixed(1), '%')
