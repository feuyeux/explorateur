// probe_geom.mjs — 一次性诊断：看生成图的像素分布（底色占多大面积、边界长什么样）
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

console.log('尺寸', W, H)
console.log('\n--- 第一行 y=0 每 64px ---')
for (let x = 0; x < W; x += 64) console.log(`x=${String(x).padStart(4)} ${hex(px(x, 0))}`)

console.log('\n--- 第一列 x=0 每 64px ---')
for (let y = 0; y < H; y += 64) console.log(`y=${String(y).padStart(4)} ${hex(px(0, y))}`)

console.log('\n--- 中心行 y=512 每 64px ---')
for (let x = 0; x < W; x += 64) console.log(`x=${String(x).padStart(4)} ${hex(px(x, 512))}`)
