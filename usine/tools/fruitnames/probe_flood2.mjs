// probe_flood2.mjs — 一次性诊断：不同 TOL 下的填充率，找断点来源
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
const dist = (i) => Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2])

for (const TOL of [42, 60, 80, 100]) {
  const near = new Uint8Array(W * H)
  for (let q = 0; q < W * H; q++) if (dist(q * 4) <= TOL) near[q] = 1
  const mask = new Uint8Array(W * H)
  const stack = []
  const push = (x, y) => {
    if (x < 0 || y < 0 || x >= W || y >= H) return
    const q = y * W + x
    if (mask[q] || !near[q]) return
    mask[q] = 1
    stack.push(q)
  }
  for (let x = 0; x < W; x++) { push(x, 0); push(x, H - 1) }
  for (let y = 0; y < H; y++) { push(0, y); push(W - 1, y) }
  while (stack.length) {
    const q = stack.pop()
    const x = q % W, y = (q / W) | 0
    push(x + 1, y); push(x - 1, y); push(x, y + 1); push(x, y - 1)
  }
  let filled = 0
  for (let q = 0; q < W * H; q++) if (mask[q]) filled++
  console.log(`TOL=${String(TOL).padStart(3)}  filled=${String(filled).padStart(7)}  (${(filled / (W * H) * 100).toFixed(1)}%)`)
}

// 关键：看 near 掩膜在**顶行**是否连续
const TOL = 42
const row0 = []
for (let x = 0; x < 200; x++) row0.push(dist(x * 4) <= TOL ? 1 : 0)
console.log('\n顶行 near 掩膜前 200 位:', row0.join(''))
