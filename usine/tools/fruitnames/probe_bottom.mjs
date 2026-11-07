// probe_bottom.mjs — 一次性诊断：看底边/底部实际像素（为何底边没有底色）
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe', 'v2_cream_short.jpg'))
const { data, info } = await sharp(p).removeAlpha().raw().toBuffer({ resolveWithObject: true })
const W = info.width, H = info.height
const px = (x, y) => { const o = (y * W + x) * 3; return [data[o], data[o + 1], data[o + 2]] }
const hex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('')

console.log('--- 底边 y=1023 每 32px ---')
for (let x = 0; x < W; x += 32) console.log(`x=${String(x).padStart(4)} ${hex(px(x, H - 1))}`)

console.log('\n--- 底部倒数 5 行，每 128px ---')
for (const dy of [0, 1, 2, 3, 4]) {
  const row = []
  for (let x = 0; x < W; x += 128) row.push(hex(px(x, H - 1 - dy)))
  console.log(`y=${H - 1 - dy}`.padEnd(10), row.join(' '))
}
