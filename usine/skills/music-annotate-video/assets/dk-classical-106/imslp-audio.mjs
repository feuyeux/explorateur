#!/usr/bin/env node
// IMSLP 作品页 → PD 录音台账（元数据）。
//
// 为什么有这个脚本：规划里写「Beethoven 第五页 27 个录音块、17 个 PD」不是手抄的
// ——它必须能被任何人重跑复算（纪律 #7 派生而非手抄）。同时它把两条踩过的坑固化成代码：
//   1. 块以 `{{#fte:imslpaudio` 起、到**行首** `}}` 止；用贪婪匹配会把后面所有块吞进第一块。
//   2. IMSLP 同一作品常有多份页面变体（`Symphony No.1` vs `Symphony No.1, GMW 11`），
//      录音只挂在其中一份。所以这里收的是**页面清单**，不是「作品清单」。
//
// **只取元数据，不下载音频。** IMSLP 的音频直链会撞 `IMSLP - Bot Check`，
// 按 usine/AGENTS.md 纪律 #21（认证与风控一律人工）不许写抓取器去对抗它。
//
// 用法：node imslp-audio.mjs "Symphony No.5, Op.67 (Beethoven, Ludwig van)" [...]

const API = 'https://imslp.org/api.php'
const UA = 'feuille/1.0 (research; https://github.com/) node'

/** 一个 `{{#fte:imslpaudio}}` 块。 */
export function parseAudioBlocks(wikitext) {
  const out = []
  let idx = -1
  while ((idx = wikitext.indexOf('{{#fte:imslpaudio', idx + 1)) !== -1) {
    const end = wikitext.indexOf('\n}}', idx)
    if (end === -1) continue
    const body = wikitext.slice(idx, end)
    const get = (k) => {
      const re = new RegExp('\\|\\s*' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*=\\s*([^\\n|]*)', 'i')
      const m = re.exec(body)
      return m ? m[1].trim() : ''
    }
    const files = []
    for (let n = 1; n <= 60; n++) {
      const f = get('File Name ' + n)
      if (!f) break
      files.push(f)
    }
    out.push({
      files,
      license: get('Copyright'),
      performers: get('Performers'),
      performerCategories: get('Performer Categories'),
      publisherInformation: get('Publisher Information'),
      notes: get('Misc. Notes'),
    })
  }
  return out
}

/** 许可是否落在「可商用 + 可改」的白名单。IMSLP 的许可是散文式，先判禁止项。 */
export function licenseOf(raw) {
  const s = raw.toLowerCase().trim()
  if (!s) return 'unknown'
  if (s === 'public domain') return 'public-domain'
  if (/non-?commercial|\bnc\b/.test(s)) return 'cc-nc' // 禁止项先判，否则会被 Attribution 抢先命中
  if (/no-?deriv|\bnd\b/.test(s)) return 'cc-nd'
  if (/attribution.*share\s*alike|share\s*alike/.test(s)) return 'cc-by-sa'
  if (/attribution/.test(s)) return 'cc-by'
  if (/cc0/.test(s)) return 'cc0'
  return 'other'
}

/** 可用的录音块：许可在白名单内且真有文件。 */
export function usableBlocks(blocks) {
  const ok = new Set(['public-domain', 'cc0', 'cc-by', 'cc-by-sa'])
  return blocks.filter((b) => b.files.length > 0 && ok.has(licenseOf(b.license)))
}

async function wikitextOf(title) {
  const url = `${API}?action=parse&format=json&page=${encodeURIComponent(title)}&prop=wikitext`
  const r = await fetch(url, { headers: { 'user-agent': UA }, signal: AbortSignal.timeout(30000) })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const j = await r.json()
  if (j.error) throw new Error(`api: ${j.error.code}`)
  return j.parse.wikitext['*']
}

async function main(argv) {
  const titles = argv.filter((a) => !a.startsWith('--'))
  if (!titles.length) {
    console.error('usage: node imslp-audio.mjs "<IMSLP page title>" [...]')
    return 2
  }
  const ledger = []
  for (const title of titles) {
    try {
      const wt = await wikitextOf(title)
      const blocks = parseAudioBlocks(wt)
      const usable = usableBlocks(blocks)
      const byLicense = {}
      for (const b of blocks) byLicense[licenseOf(b.license)] = (byLicense[licenseOf(b.license)] ?? 0) + 1
      ledger.push({
        title,
        blocks: blocks.length,
        usable: usable.length,
        byLicense,
        performers: usable.map((b) => b.performerCategories || b.performers).filter(Boolean),
      })
      console.log(
        `${title}\n  块 ${blocks.length} / 可用 ${usable.length}  ${JSON.stringify(byLicense)}` +
          (usable[0] ? `\n  首个演绎：${(usable[0].performerCategories || usable[0].performers).slice(0, 70)}` : ''),
      )
    } catch (e) {
      ledger.push({ title, error: String(e.message ?? e) })
      console.log(`${title}\n  ERROR ${e.message ?? e}`)
    }
    await new Promise((r) => setTimeout(r, 400)) // 取数礼仪：串行 + 间隔
  }
  console.log('\n' + JSON.stringify(ledger, null, 1))
  return 0
}

if (process.argv[1] && process.argv[1].endsWith('imslp-audio.mjs')) {
  main(process.argv.slice(2)).then((c) => process.exit(c))
}
