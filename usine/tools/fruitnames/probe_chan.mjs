// probe_chan.mjs — 一次性诊断：平滑后 raw 的通道数与索引
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const p = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe', 'v2_cream_short.jpg'))
const a = await sharp(p).removeAlpha().raw().toBuffer({ resolveWithObject: true })
console.log('removeAlpha().raw()  channels =', a.info.channels, 'len', a.data.length)

const b = await sharp(p).removeAlpha().blur(1.2).raw().toBuffer({ resolveWithObject: true })
console.log('removeAlpha().blur().raw() channels =', b.info.channels, 'len', b.data.length)

const c = await sharp(p).blur(1.2).removeAlpha().raw().toBuffer({ resolveWithObject: true })
console.log('blur().removeAlpha().raw() channels =', c.info.channels, 'len', c.data.length)

const hex = (arr, i) => '#' + [arr[i], arr[i + 1], arr[i + 2]].map((v) => v.toString(16).padStart(2, '0')).join('')
console.log('\nb 通道数下 底边 y=1023, x=512 的读数：')
const W = b.info.width, H = b.info.height
const o = ((H - 1) * W + 512) * b.info.channels
console.log('  b（错按 3 通道读）', hex(b.data, o))
console.log('  b（按实际通道读）', hex(b.data, o))
