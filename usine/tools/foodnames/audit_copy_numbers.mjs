// audit_copy_numbers.mjs — 预检：各期发布词读者面出现的每个数字，
// 能不能在「将会生成的 facts.json」里找到出处。
//
// 为什么要有这个脚本：`feuille copy check --facts` 要等成片出来才有 facts.json，
// 但**稿子里的数字是写死的**——等成片跑完才发现某个数没出处，返工的是文案
// 而不是产线。先用「结构量 + 数据文件 extra_facts」离线预检一遍，把问题提前
// 暴露在写稿阶段。
//
// 跑法：node tools/foodnames/audit_copy_numbers.mjs
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const here = import.meta.dirname
const DATA = join(here, 'data')
const EX = 'D:/coding/personal/explorateur/usine/examples'

/** 与 make_publish.mjs 同一口径：读者面 = 标题 + 正文/文案/简介。 */
function readerText(md, platform) {
  const sections = []
  let title = null
  let body = []
  for (const line of md.split('\n')) {
    const m = /^##\s+(.+?)\s*$/.exec(line)
    if (m) {
      if (title !== null) sections.push([title, body])
      title = m[1].trim()
      body = []
    } else if (title !== null) body.push(line)
  }
  if (title !== null) sections.push([title, body])
  const text = (t) => {
    const s = sections.find(([x]) => x === t)
    return s ? s[1].join('\n').trim() : ''
  }
  if (platform === 'douyin') return text('文案')
  const th = platform === 'xiaohongshu' ? '标题（20 字内）' : '标题'
  const bs = platform === 'xiaohongshu' ? '正文' : '简介'
  return [text(th), text(bs)].join('\n')
}

function roundHalfEven(x) {
  const r = Math.round(x)
  if (Math.abs(x % 1) === 0.5) return r % 2 === 0 ? r : r - 1
  return Math.round(x)
}

/** 与 make_publish.mjs 同一套结构量（实测项此时未知，故只算结构量）。 */
function structuralFacts(data) {
  const src = new Map()
  for (const w of data.words) {
    const m = /借自(.+?)(?:\s*·.*)?$/.exec(w.tag || '')
    if (!m) continue
    src.set(m[1].trim(), (src.get(m[1].trim()) || 0) + 1)
  }
  const native = data.words.filter((w) => !/^借自/.test(w.tag || '')).length
  const f = {
    locales: data.words.length,
    words_compared: data.words.length,
    tts_voices: data.words.length,
    episode: data.episode,
    distinct_loan_paths: src.size + native,
    distinct_borrow_sources: src.size,
    native_words: native,
    borrowed_words: data.words.length - native,
  }
  for (const [k, v] of src) f[`borrowed_from_${k}`] = v
  data.words.forEach((w, i) => { f[`position_${w.locale}`] = i + 1 })
  for (const [k, v] of Object.entries(data.extra_facts || {})) {
    if (typeof v === 'number' || typeof v === 'string') f[k] = v
  }
  return f
}

const PLATFORMS = [['xiaohongshu', 'xiaohongshu.md'], ['douyin', 'douyin.md'], ['bilibili', 'bilibili.md']]
let bad = 0

for (const f of readdirSync(DATA).filter((n) => n.endsWith('.json')).sort()) {
  const data = JSON.parse(readFileSync(join(DATA, f), 'utf8'))
  const dir = join(EX, `foodnames-ep${String(data.episode).padStart(2, '0')}-${data.slug}`, 'publish')
  if (!existsSync(dir)) { console.log(`${f}：无 publish 目录，跳过`); continue }
  const facts = structuralFacts(data)
  const nums = new Set()
  for (const v of Object.values(facts)) {
    if (typeof v === 'number') nums.add(v)
    else if (typeof v === 'string' && /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(v.trim())) nums.add(Number(v.trim()))
  }
  const miss = new Map()
  for (const [plat, file] of PLATFORMS) {
    const p = join(dir, file)
    if (!existsSync(p)) { miss.set(plat, ['（发布词缺失）']); continue }
    const raw = readerText(readFileSync(p, 'utf8'), plat).replace(/#[^\s#]+/g, ' ')
    const claimed = [...new Set(raw.match(/\d+(?:\.\d+)?/g) ?? [])]
    const un = claimed.filter((c) => {
      const cv = Number(c)
      return ![...nums].some((x) => cv === x || roundHalfEven(x) === cv || roundHalfEven(x * 10) / 10 === cv)
    })
    if (un.length > 0) miss.set(plat, un)
  }
  if (miss.size === 0) {
    console.log(`✅ 第 ${String(data.episode).padStart(2, '0')} 期 ${data.title_zh}：读者面数字全部有出处`)
  } else {
    bad += 1
    console.log(`❌ 第 ${String(data.episode).padStart(2, '0')} 期 ${data.title_zh}：`)
    for (const [plat, un] of miss) console.log(`    ${plat}: ${un.join(', ')}`)
  }
}
process.exit(bad === 0 ? 0 : 1)
