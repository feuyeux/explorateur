// probe_ref.mjs — 一次性诊断：量参考海报的底色、栏边框色、插画区底色
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = 'C:/Users/feuye/.minimax/v2/assets/2026/11/06/20-46-39-225-asset_20261106-204639-225_2dbf81610925_516c3a15-三栏水果中英图鉴海报.png'
const { data, info } = await sharp(p).raw().toBuffer({ resolveWithObject: true })
const px = (x, y) => {
  const o = (y * info.width + x) * info.channels
  return [data[o], data[o + 1], data[o + 2]]
}
const hex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('')
console.log('channels', info.channels, info.width, info.height)

const probes = [
  [3, 3, '画布最外底'],
  [300, 8, '第一栏上方'],
  [300, 26, '第一栏内顶'],
  [505, 300, '第一栏中部'],
  [520, 300, '栏间缝'],
  [3, 300, '左边缘'],
]
for (const [x, y, label] of probes) {
  console.log(label.padEnd(14), `${x},${y}`.padEnd(10), hex(px(x, y)))
}

// 沿 y=300 横扫，找栏边框（颜色突变处）
console.log('\n--- y=300 横扫（每 8px 采样，找边框）---')
let prev = null
for (let x = 0; x < info.width; x += 4) {
  const c = px(x, 300)
  const key = c.join(',')
  if (prev && key !== prev) {
    const d = Math.abs(c[0] - prev.split(',')[0]) + Math.abs(c[1] - prev.split(',')[1]) + Math.abs(c[2] - prev.split(',')[2])
    if (d > 40) console.log(`x=${x} ${hex(prev.split(',').map(Number))} → ${hex(c)}`)
  }
  prev = key
}
