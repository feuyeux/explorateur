// probe_edge.mjs — 一次性诊断：看边界像素的颜色序列（为何种子不连通）
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

const bg = [248, 240, 216]
const dist = (c) => Math.abs(c[0] - bg[0]) + Math.abs(c[1] - bg[1]) + Math.abs(c[2] - bg[2])

console.log('--- 顶行 y=0，x=0..60 逐像素 ---')
for (let x = 0; x < 60; x++) {
  const c = px(x, 0)
  console.log(`x=${String(x).padStart(3)} ${hex(c)} d=${dist(c)}`)
}
