// series_report.mjs — 汇总 12 期的交付状态与实测数据（生成人读的一览表）
//
// 单一事实源 = 各期目录里的实测产物（facts.json / out/*.mp4 / publish/manifest.json）。
// 本脚本**只读**，不重算、不猜测——某期没跑完就如实标「未完成」。
//
// 跑法：node tools/foodnames/series_report.mjs [--md <输出路径>]
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const here = import.meta.dirname
const DATA = join(here, 'data')
const EX = 'D:/coding/personal/explorateur/usine/examples'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}

const rows = []
for (const f of readdirSync(DATA).filter((n) => /^ep\d\d-.*\.json$/.test(n)).sort()) {
  const d = JSON.parse(readFileSync(join(DATA, f), 'utf8'))
  const dir = join(EX, `foodnames-ep${String(d.episode).padStart(2, '0')}-${d.slug}`)
  const pub = join(dir, 'publish')
  const factsPath = join(pub, 'facts.json')
  const facts = existsSync(factsPath) ? JSON.parse(readFileSync(factsPath, 'utf8')) : null
  const manPath = join(pub, 'manifest.json')
  const man = existsSync(manPath) ? JSON.parse(readFileSync(manPath, 'utf8')) : null
  const outDir = join(dir, 'out')
  const vids = existsSync(outDir)
    ? readdirSync(outDir).filter((n) => n.endsWith('.mp4')).sort()
    : []
  const poster = existsSync(join(dir, 'poster.png'))
  const covers = ['cover_lc.png', 'cover_pt.png', 'cover_t34.png']
    .filter((c) => existsSync(join(dir, c)))
  const copyOk = ['xiaohongshu.md', 'douyin.md', 'bilibili.md']
    .every((c) => existsSync(join(pub, c)))
  rows.push({
    ep: d.episode, slug: d.slug, title: d.title_zh, dir,
    origin: d.origin_locale ?? null,
    poster, covers: covers.length, vids, copyOk,
    facts, man,
    complete: poster && covers.length === 3 && vids.length === 2 && copyOk && man !== null,
  })
}

const md = []
md.push('# 「各国美食名称」系列 · 12 期一览')
md.push('')
md.push('单一事实源 = 各期目录里的实测产物（`publish/facts.json` / `out/*.mp4` / `publish/manifest.json`）。')
md.push('本表由 `tools/foodnames/series_report.mjs` 只读生成——某期没跑完就如实标「未完成」。')
md.push('')
md.push('| 期 | 主题 | slug | 词源语 | 海报 | 封面 | 成片 | 时长 | 帧 | 旁白 dBFS | 床 dBFS | gain | 来路 | 发布词 | 清单 |')
md.push('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for (const r of rows) {
  const f = r.facts
  const cell = (b) => (b ? '✓' : '—')
  md.push([
    String(r.ep).padStart(2, '0'),
    r.title,
    r.slug,
    r.origin ?? '—',
    cell(r.poster),
    r.covers ? `${r.covers}/3` : '0/3',
    r.vids.length ? `${r.vids.length}/2` : '0/2',
    f ? `${f.duration_sec}s` : '—',
    f ? String(f.frames) : '—',
    f ? String(f.narration_rms_dbfs) : '—',
    f ? String(f.bed_rms_dbfs) : '—',
    f ? String(f.bgm_gain) : '—',
    f ? String(f.distinct_loan_paths) : '—',
    cell(r.copyOk),
    cell(r.man),
  ].join(' | '))
}
md.push('')
const done = rows.filter((r) => r.complete).length
md.push(`**${done} / ${rows.length} 期完整交付**（海报 + 三封面 + 横竖双成片 + 三平台发布词 + 发布清单）。`)
md.push('')
md.push('## 每期词源标签')
md.push('')
for (const r of rows) {
  const d = JSON.parse(readFileSync(join(DATA, `ep${String(r.ep).padStart(2, '0')}-${r.slug}.json`), 'utf8'))
  md.push(`### 第 ${String(r.ep).padStart(2, '0')} 期 · ${r.title}（${r.slug}）`)
  md.push('')
  md.push('| 语种 | 词形 | 来源 |')
  md.push('|---|---|---|')
  for (const w of d.words) md.push(`| ${w.label} | ${w.word} | ${w.tag} |`)
  md.push('')
}
const outPath = arg('md')
if (outPath) {
  writeFileSync(outPath, md.join('\n'), 'utf8')
  console.log(`wrote ${outPath}`)
}
// ⚠️ 切片边界：表头 6 行（标题/空/说明/空/表头/分隔）+ N 行数据。
//    少一行就会把**最后一期**（ep12）整行吞掉——看着像「那期没跑完」，
//    实际产物全在。宁可多打一行空行，也不能少打一期。
//    下面的自检就是防这个：行数与期数不等就响亮失败。
const HEAD_LINES = 6
const mdOut = md.slice(0, HEAD_LINES + rows.length + 1)
const dataLines = mdOut.filter((l) => /^\|?\s*\d\d\s\|/.test(l))
if (dataLines.length !== rows.length) {
  console.error(`✖ 表格行数 ${dataLines.length} ≠ 期数 ${rows.length}——有期被截掉了`)
  process.exit(1)
}
console.log(mdOut.join('\n'))
console.log(`\n${done}/${rows.length} 期完整`)
