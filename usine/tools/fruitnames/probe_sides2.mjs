// probe_sides2.mjs — 一次性诊断：直接打印四边每 32px 的判定结果
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe', 'v2_cream_short.jpg'))
const { data: sm } = await sharp(p).removeAlpha().blur(1.2).raw().toBuffer({ resolveWithObject: true })
const W = 1024, H = 1024
const bg = [248, 240, 216]
const d = (i) => Math.abs(sm[i] - bg[0]) + Math.abs(sm[i + 1] - bg[1]) + Math.abs(sm[i + 2] - bg[2])

console.log('top  y=0:')
for (let x = 0; x < W; x += 64) console.log(`  x=${String(x).padStart(4)} d=${d((0 * W + x) * 4)} ${d((0 * W + x) * 4) <= 42 ? 'HIT' : 'miss'}`)
console.log('bottom y=1023:')
for (let x = 0; x < W; x += 64) console.log(`  x=${String(x).padStart(4)} d=${d(((H - 1) * W + x) * 4)} ${d(((H - 1) * W + x) * 4) <= 42 ? 'HIT' : 'miss'}`)
