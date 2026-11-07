// build_fruitlist.mjs — 从人审词表派生机器可读的 fruitlist.json
//
// 事实源 = `usine/examples/fruitnames/data/fruitlist-12lang.md`（人审合并版，
// 逐格核对过）；本脚本把它解析成 `data/fruitlist.json`，供 gen_art.mjs 与
// 后续每集构建器消费。md 是唯一事实源，json 是派生物——改词先改 md 再重跑。
//
// 解析时顺手做三件事：
//   1. 双列格结构化：`toronja (América Latina) / pomelo (España)` 拆成
//      variants 数组（text + region），首项为默认词形——别让 ` / ` 和
//      括号注记流进渲染层。
//   2. 从集标题取 title_zh，从 English 列取 title_en（全大写 · 连接）。
//   3. 校验：40 集 × 4 词、key 唯一且全小写拉丁、每格非空。任何一格
//      异常就整体失败退出 1——坏数据不落盘。
//
// 跑法：`node tools/fruitnames/build_fruitlist.mjs`（加 --force 才覆盖已存在的 json）
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const DATA_DIR = resolve(here, '..', '..', 'examples', 'fruitnames', 'data')
const MD = join(DATA_DIR, 'fruitlist-12lang.md')
const OUT = join(DATA_DIR, 'fruitlist.json')
const FORCE = process.argv.includes('--force')

// 12 语种规范顺序与属性（与 one-page-poster §Conventions 一致；
// script 键 = 逐字着色的分派键，同 tools/foodnames 的口径）
const LANGS = [
  { locale: 'zh-CN', label: '汉语', natv: '中文', dir: 'ltr', script: 'sc' },
  { locale: 'en-US', label: '英语', natv: 'English', dir: 'ltr', script: 'latin' },
  { locale: 'de-DE', label: '德语', natv: 'Deutsch', dir: 'ltr', script: 'latin' },
  { locale: 'fr-FR', label: '法语', natv: 'Français', dir: 'ltr', script: 'latin' },
  { locale: 'es-ES', label: '西班牙语', natv: 'Español', dir: 'ltr', script: 'latin' },
  { locale: 'ru-RU', label: '俄语', natv: 'Русский', dir: 'ltr', script: 'cyrillic' },
  { locale: 'el-GR', label: '希腊语', natv: 'Ελληνικά', dir: 'ltr', script: 'greek' },
  { locale: 'hi-IN', label: '印地语', natv: 'हिन्दी', dir: 'ltr', script: 'deva' },
  { locale: 'ar-SA', label: '阿拉伯语', natv: 'العربية', dir: 'rtl', script: 'ar' },
  { locale: 'he-IL', label: '希伯来语', natv: 'עברית', dir: 'rtl', script: 'he' },
  { locale: 'ja-JP', label: '日语', natv: '日本語', dir: 'ltr', script: 'jp' },
  { locale: 'ko-KR', label: '韩语', natv: '한국어', dir: 'ltr', script: 'kr' },
]

// `A (region X) / B (region Y)` → [{text:'A', region:'region X'}, ...]
// 没有地区注记的 `A / B` 也拆（region 为空）；单一直接返回 null。
function parseVariants(cell) {
  if (!cell.includes('/')) return null
  const parts = cell.split(' / ').map((s) => s.trim()).filter(Boolean)
  if (parts.length < 2) return null
  return parts.map((p) => {
    const m = p.match(/^(.*?\S)\s*\((.+)\)$/)
    return m ? { text: m[1].trim(), region: m[2].trim() } : { text: p, region: null }
  })
}

const md = readFileSync(MD, 'utf8')
const lines = md.split(/\r?\n/)

const episodes = []
let cur = null
const problems = []

for (const ln of lines) {
  const h = ln.match(/^### 第 (\d+) 集 · (.+)$/)
  if (h) {
    cur = { episode: Number(h[1]), title_zh: h[2].trim(), fruits: [] }
    episodes.push(cur)
    continue
  }
  if (!cur || !ln.startsWith('|')) continue
  const c = ln.split('|').slice(1, -1).map((s) => s.trim())
  if (c.length !== 13 || c[0] === 'key' || /^-+$/.test(c[0])) continue

  const [key, ...cells] = c
  if (!/^[a-z]+$/.test(key)) problems.push(`key 不合规范：${key}`)
  const words = {}
  const variants = {}
  cells.forEach((cell, i) => {
    if (!cell) problems.push(`ep${cur.episode} ${key} 第 ${i + 1} 语为空`)
    words[LANGS[i].locale] = cell
    const v = parseVariants(cell)
    if (v) {
      variants[LANGS[i].locale] = v
      words[LANGS[i].locale] = v[0].text
    }
  })
  cur.fruits.push({ key, zh: cells[0], en: cells[1], words, ...(Object.keys(variants).length ? { variants } : {}) })
}

// ---- 校验（坏数据不落盘）
if (episodes.length !== 10) problems.push(`集数 ${episodes.length} ≠ 10`)
for (const ep of episodes) {
  if (ep.fruits.length !== 4) problems.push(`ep${ep.episode} 词数 ${ep.fruits.length} ≠ 4`)
  if (!ep.title_zh) problems.push(`ep${ep.episode} 缺标题`)
  for (const f of ep.fruits) {
    const missing = LANGS.filter((l) => !f.words[l.locale])
    if (missing.length) problems.push(`${f.key} 缺 ${missing.map((l) => l.locale).join(',')}`)
  }
}
const allKeys = episodes.flatMap((e) => e.fruits.map((f) => f.key))
if (new Set(allKeys).size !== 40) problems.push(`去重后 key ${new Set(allKeys).size} ≠ 40`)

if (problems.length) {
  console.error(`✖ 词表校验失败 ${problems.length} 条：\n  - ${problems.join('\n  - ')}`)
  process.exit(1)
}

for (const ep of episodes) {
  ep.slug = ep.fruits.map((f) => f.key).join('-')
  ep.title_en = ep.fruits.map((f) => f.en).join(' · ').toUpperCase()
}

const out = {
  _readme: '水果系列 40 种 × 12 语种。派生文件，唯一事实源是 data/fruitlist-12lang.md（人审合并版）；改词先改 md 再跑 tools/fruitnames/build_fruitlist.mjs --force。variants 里的首项 words[locale] 已取默认词形，地区变体见 variants。',
  generated_from: 'fruitlist-12lang.md',
  languages: LANGS,
  episodes,
}

if (existsSync(OUT) && !FORCE) {
  console.error(`✖ ${OUT} 已存在（生成类命令默认不覆盖；确认以 md 为准后加 --force）`)
  process.exit(1)
}
writeFileSync(OUT, JSON.stringify(out, null, 2) + '\n', 'utf8')
console.log(`✓ ${OUT}（10 集 / 40 词 / ${LANGS.length} 语种；变体格 ${Object.keys(episodes.flatMap((e) => e.fruits.filter((f) => f.variants))).length} 词）`)
