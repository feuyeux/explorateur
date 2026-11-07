// probe_sides.mjs — 一次性诊断：四边各自的近底色种子数
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe', 'v2_cream_short.jpg'))
const img = sharp(p).removeAlpha()
const meta = await img.metadata()
const W = meta.width, H = meta.height
const { data } = await img.raw().toBuffer({ resolveWithObject: true })
const sm = await img.blur(1.2).raw().toBuffer({ resolveWithObject: true })

const counts = new Map()
for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) {
  const o = (y * W + x) * 3
  const k = ((data[o] >> 2) << 12) | ((data[o + 1] >> 2) << 6) | (data[o + 2] >> 2)
  counts.set(k, (counts.get(k) ?? 0) + 1)
}
let best = -1, bk = 0
for (const [k, c] of counts) if (c > best) { best = c; bk = k }
const bg = [((bk >> 12) & 63) << 2, ((bk >> 6) & 63) << 2, (bk & 63) << 2]
console.log('底色', bg, '尺寸', W, H)

const dist = (i) => Math.abs(sm.data[i] - bg[0]) + Math.abs(sm.data[i + 1] - bg[1]) + Math.abs(sm.data[i + 2] - bg[2])
for (const TOL of [42, 60, 80]) {
  const sides = {
    top: 0, bottom: 0, left: 0, right: 0,
  }
  for (let x = 0; x < W; x++) {
    if (dist((0 * W + x) * 4) <= TOL) sides.top++
    if (dist(((H - 1) * W + x) * 4) <= TOL) sides.bottom++
  }
  for (let y = 0; y < H; y++) {
    if (dist((y * W + 0) * 4) <= TOL) sides.left++
    if (dist((y * W + W - 1) * 4) <= TOL) sides.right++
  }
  console.log(`TOL=${TOL}`, JSON.stringify(sides), `（边长 ${W}/${H}）`)
}
