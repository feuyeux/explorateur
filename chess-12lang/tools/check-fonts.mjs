// tools/check-fonts.mjs —— 字体子集覆盖度门：fonts.css 里的每个 @font-face
// 带 unicode-range；fonts.json 里每个「族→字符」必须真的被该族的某一档字重覆盖。
//
// 为什么要有这扇门：audit-charset 只验「页面字符 ⊆ fonts.json 名单」，
// 那是**我们自己的请求**；但 Google 返回的子集里可能没有某些字（字体本身不含
// 那个码位），此时请求里有、实际渲染里没有 → 画面上是豆腐块，而 audit-charset
// 全绿。���一扇门验的是「实际拿到的字体」覆盖了「实际要渲染的字」。
//
// 用法：node tools/check-fonts.mjs [fonts.json] [fonts.css]
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const specPath = process.argv[2] ?? join(ROOT, 'fonts.json')
const cssPath = process.argv[3] ?? join(ROOT, 'fonts.css')

const spec = JSON.parse(readFileSync(specPath, 'utf8'))
const css = readFileSync(cssPath, 'utf8')

/** unicode-range 串 → 码位集合。 */
function parseRange(u) {
  const s = new Set()
  for (const part of u.split(',')) {
    const t = part.trim().replace(/^U\+/i, '')
    if (t.includes('-')) {
      const [a, b] = t.split('-').map((x) => parseInt(x, 16))
      for (let i = a; i <= b; i++) s.add(i)
    } else s.add(parseInt(t, 16))
  }
  return s
}

const faces = css.match(/@font-face\s*\{[^}]+\}/g) ?? []
if (faces.length === 0) {
  console.error('FAIL: fonts.css 里没有 @font-face')
  process.exit(1)
}

const cov = new Map()   // family → { weight → Set(codepoint) }
for (const b of faces) {
  const fam = b.match(/font-family:\s*'([^']+)'/)?.[1]
  const wght = b.match(/font-weight:\s*(\d+)/)?.[1] ?? '400'
  const ur = b.match(/unicode-range:\s*([^;]+)/)?.[1]
  if (!fam || !ur) continue
  if (!cov.has(fam)) cov.set(fam, new Map())
  cov.get(fam).set(wght, parseRange(ur))
}

let bad = 0
for (const e of spec) {
  const weights = cov.get(e.family)
  if (!weights) {
    console.error(`FAIL: ${e.family} 在 fonts.css 里没有 @font-face`)
    bad++
    continue
  }
  // 该族所有字重的并集 = 这个族能渲染的字符
  const all = new Set()
  for (const set of weights.values()) for (const c of set) all.add(c)
  const missing = []
  for (const ch of new Set([...e.text])) {
    if (ch === ' ') continue
    if (!all.has(ch.codePointAt(0))) {
      missing.push(`${ch} U+${ch.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`)
    }
  }
  const perWeight = [...weights.entries()].map(([w, s]) => `${w}:${s.size}`).join(' ')
  if (missing.length) {
    console.error(`FAIL: ${e.family} 缺 ${missing.length} 个字 → ${missing.join(' ')}`)
    bad++
  } else {
    console.log(`  ok ${e.family.padEnd(18)} 请求 ${new Set(e.text).size} 字  实际覆盖 ${all.size} 字  [${perWeight}]`)
  }
}

if (bad > 0) {
  console.error(`\n字体覆盖度门：${bad} 族不合格`)
  process.exit(1)
}
console.log('\n字体覆盖度门：全部通过（无豆腐块）')
