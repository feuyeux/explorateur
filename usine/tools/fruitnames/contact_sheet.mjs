// contact_sheet.mjs — 把多张图拼成一张联系表（便于人眼一次性比对风格一致性）
import { existsSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createRequire } from 'node:module'

const here = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const USINE = resolve(here, '..', '..')
const require = createRequire(join(USINE, 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

const dir = resolve(process.argv[2] ?? join(USINE, 'examples', 'fruitnames', 'probe'))
const out = resolve(process.argv[3] ?? join(USINE, 'examples', 'fruitnames', 'probe', '_sheet.jpg'))
const COLS = Number(process.argv[4] ?? 3)
const CELL = 420

const files = readdirSync(dir).filter((f) => /\.(png|jpg|jpeg)$/i.test(f) && !f.startsWith('_')).sort()
if (!files.length) {
  console.error('没有图')
  process.exit(1)
}
const rows = Math.ceil(files.length / COLS)
const comps = []
for (let i = 0; i < files.length; i++) {
  const buf = await sharp(join(dir, files[i]))
    .resize(CELL, CELL, { fit: 'contain', background: '#F7F2E6' })
    .flatten({ background: '#F7F2E6' })
    .jpeg({ quality: 92 })
    .toBuffer()
  comps.push({ input: buf, left: (i % COLS) * CELL, top: Math.floor(i / COLS) * CELL })
}
await sharp({ create: { width: COLS * CELL, height: rows * CELL, channels: 3, background: '#F7F2E6' } })
  .composite(comps)
  .jpeg({ quality: 92 })
  .toFile(out)
console.log(`${files.length} 张 → ${out}`)
console.log(files.map((f, i) => `${i + 1}. ${f}`).join('\n'))
