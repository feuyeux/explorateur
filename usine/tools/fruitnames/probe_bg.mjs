// probe_bg.mjs — 量生成图的底色（要贴近参考图的 #fffcf5）
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'
import { readdirSync } from 'node:fs'

const USINE = resolve(process.cwd())
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const dir = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe'))
const hex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('')

for (const f of readdirSync(dir).filter((x) => /\.(png|jpg)$/i.test(x) && !x.startsWith('_'))) {
  const { data, info } = await sharp(join(dir, f)).raw().toBuffer({ resolveWithObject: true })
  const px = (x, y) => {
    const o = (y * info.width + x) * info.channels
    return [data[o], data[o + 1], data[o + 2]]
  }
  const corners = [px(2, 2), px(info.width - 3, 2), px(2, info.height - 3), px(info.width - 3, info.height - 3)]
  console.log(f.padEnd(24), '四角:', corners.map(hex).join(' '), '尺寸', `${info.width}x${info.height}`)
}
console.log('\n参考图底色 = #fffcf5')
