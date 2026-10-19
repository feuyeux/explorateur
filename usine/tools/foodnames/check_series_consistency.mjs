// check_series_consistency.mjs — 跨期一致性检查
//
// 12 期是同一个系列的同一套版式。「每期各自跑绿」不等于「系列看起来是一家人」——
// 这道门查的是**跨期**才暴露的问题：标题字串、图例、页脚、画幅、格数、语种序。
//
// 跑法：node tools/foodnames/check_series_consistency.mjs
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const here = import.meta.dirname
const DATA = join(here, 'data')
const EX = 'D:/coding/personal/explorateur/usine/examples'
const ORDER = ['zh-CN', 'en-US', 'de-DE', 'fr-FR', 'es-ES', 'ru-RU', 'el-GR', 'hi-IN', 'ar-SA', 'he-IL', 'ja-JP', 'ko-KR']
const LANGS = ['汉语', '英语', '德语', '法语', '西班牙语', '俄语', '希腊语', '印地语', '阿拉伯语', '希伯来语', '日语', '韩语']

const problems = []
const note = (ep, msg) => problems.push(`第 ${ep} 期：${msg}`)

const eps = []
for (const f of readdirSync(DATA).filter((n) => /^ep\d\d-.*\.json$/.test(n)).sort()) {
  const d = JSON.parse(readFileSync(join(DATA, f), 'utf8'))
  eps.push(d)
}

// ---- 1 数据层：12 格 / 语种序 / 标签非空 / tokens 与句子一致 ----
for (const d of eps) {
  const ep = String(d.episode).padStart(2, '0')
  if (d.words.length !== 12) note(ep, `格数 ${d.words.length} ≠ 12`)
  d.words.forEach((w, i) => {
    if (w.locale !== ORDER[i]) note(ep, `第 ${i + 1} 格语种序错：${w.locale} ≠ ${ORDER[i]}`)
    if (w.label !== LANGS[i]) note(ep, `第 ${i + 1} 格语种名错：${w.label} ≠ ${LANGS[i]}`)
    if (!w.tag || !w.tag.trim()) note(ep, `${w.locale} 的来源标签为空`)
    if (!w.sentence || !w.tokens?.length) note(ep, `${w.locale} 缺旁白句或 tokens`)
    if (!w.persona?.name || !w.voice) note(ep, `${w.locale} 缺人设或音色`)
  })
  if (!d.origin_locale) note(ep, '缺 origin_locale（词源语）')
  if (!d.spine || !d.spine.trim()) note(ep, '缺 spine（题眼）')
  if (!d.title_zh || !d.title_en) note(ep, '缺中/英标题')
}

// ---- 2 版式层：海报源文件的结构件逐期一致 ----
// ⚠️ 判据按**实际源文件结构**写，不按想当然：
//   海报 = `.grid` 里 12 个 `.cell`（cell 数 24 是因为还有 overlay 副本），
//   品牌字在 `.title-sub`，格子里是 `.cellhead` + `.wordbox`。
//   视频 = 12 个 `<section class="scene" id="sc-<locale>">`。
const sig = (ep, kind, html) => {
  if (kind === 'poster') {
    for (const m of ['class="poster"', 'class="legend"', 'class="grid"', 'class="cellhead"', 'class="wordbox"']) {
      if (!html.includes(m)) note(ep, `poster_src 缺结构件「${m}」`)
    }
    // 12 格：海报每格前有 `<!-- N 语种名 -->` 注释（源文件的唯一定位标记）
    const marks = [...html.matchAll(/<!--\s*\d+\s+([^\s>]+?)\s*-->/g)].map((m) => m[1])
    for (const lang of LANGS) {
      if (!marks.includes(lang)) note(ep, `poster_src 缺「${lang}」格`)
    }
    if (marks.length !== 12) note(ep, `poster_src 格注释数 ${marks.length} ≠ 12`)
    if (!html.includes('IN TWELVE LANGUAGES')) note(ep, 'poster_src 缺系列副题「IN TWELVE LANGUAGES」')
  } else {
    for (const m of ['class="brand"', 'class="pageno"', 'class="headrule"', 'class="langline"']) {
      if (!html.includes(m)) note(ep, `video_src 缺结构件「${m}」`)
    }
    for (const loc of ORDER) {
      if (!html.includes(`id="sc-${loc}"`)) note(ep, `video_src 缺 ${loc} 场景`)
    }
    if (!html.includes('IN TWELVE LANGUAGES')) note(ep, 'video_src 缺系列副题「IN TWELVE LANGUAGES」')
  }
}

for (const d of eps) {
  const ep = String(d.episode).padStart(2, '0')
  const dir = join(EX, `foodnames-ep${ep}-${d.slug}`)
  const ps = join(dir, 'poster_src.html')
  const vs = join(dir, 'video_src.html')
  if (existsSync(ps)) sig(ep, 'poster', readFileSync(ps, 'utf8'))
  if (existsSync(vs)) sig(ep, 'video', readFileSync(vs, 'utf8'))
}

// ---- 3 产物层：画幅 / 帧率 / 语种集一致 ----
for (const d of eps) {
  const ep = String(d.episode).padStart(2, '0')
  const dir = join(EX, `foodnames-ep${ep}-${d.slug}`)
  const man = join(dir, 'publish', 'manifest.json')
  if (!existsSync(man)) continue
  const m = JSON.parse(readFileSync(man, 'utf8'))
  const plats = Object.keys(m)
  if (plats.length !== 3) note(ep, `清单平台数 ${plats.length} ≠ 3`)
  const sets = plats.map((p) => m[p].map((t) => t.lang).join('|'))
  if (new Set(sets).size !== 1) note(ep, '三平台语种集合不一致')
  for (const p of plats) {
    const t = m[p][0]
    if (!t) { note(ep, `${p} 清单无条目`); continue }
    if (t.lang !== d.title_zh) note(ep, `${p} 清单 lang「${t.lang}」≠ 标题「${d.title_zh}」`)
    if (t.locale !== d.origin_locale) note(ep, `${p} 清单 locale「${t.locale}」≠ origin_locale「${d.origin_locale}」`)
    const vd = join(dir, t.video)
    const cd = join(dir, t.cover)
    if (!existsSync(vd)) note(ep, `${p} 视频缺失 ${t.video}`)
    if (!existsSync(cd)) note(ep, `${p} 封面缺失 ${t.cover}`)
  }
}

if (problems.length === 0) {
  console.log(`✅ 跨期一致性通过：${eps.length} 期（数据层 12 格/语种序/标签 · 版式层结构件 · 产物层画幅与清单）`)
} else {
  console.log(`❌ ${problems.length} 项跨期不一致：`)
  for (const p of problems) console.log('  · ' + p)
  process.exit(1)
}
