// build_episode.mjs — 「各国美食名称」系列：**一期数据 → 一套产物源文件**
//
// 输入：data/epNN-<slug>.json（12 个语种的词形/来源/旁白句/转写/人设）
// 输出（到 --out 目录）：
//   poster_src.html  海报源（12 格，逐字着色）
//   video_src.html   12 场景卡拉OK状态机页源
//   voices.json      配音脚本（文本 + token 切分）
//   fonts.json       字体子集清单（text 由门禁自己算，见下）
//
// 设计要点：
// - **逐字着色由规则推导**（元音红/辅音蓝/垫片透明），不是逐期手抄：
//   拉丁/西里尔/希腊按元音表切分，片假名按「有无声母」分 .cv/.v，
//   阿拉伯/希伯来/天城文走「下层整词红 + 上层辅音蓝/元音透明」两行叠印。
// - **字体子集由 audit-charset 自己的口径反推**（同一套家族栈逻辑，
//   不另写一份收集器）：先用空 text 建清单，让门禁报缺字，补进去，直到收敛。
// - 韩语逐音节补丁类由 `feuille poster measure-korean` 测量后注入
//   （占位 /*__KO_CSS__*/；每期音节不同，不能跨期复用）。
//
// 跑法（仓库根目录）：
//   pnpm exec tsx tools/foodnames/build_episode.mjs --data tools/foodnames/data/ep02-coffee.json --out examples/foodnames-ep02-coffee
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { audit_charset } from '../../packages/poster/src/index.ts'

const here = dirname(fileURLToPath(import.meta.url))

// ---------------------------------------------------------------- 参数
function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const DATA = resolve(arg('data'))
const OUT = resolve(arg('out'))
const TMPL = join(here, 'templates')

// ---------------------------------------------------------------- 分词规则
const VOWELS = {
  latin: 'aeiouyáàâäéèêëíìîïóòôöúùûüýÿæœāēīōū',
  cyrillic: 'аеёиоуыэюяАЕЁИОУЫЭЮЯ',
  greek: 'αεηιουωάέήίόύώΑΕΗΙΟΥΩ',
}
const KANA_VOWEL = 'あいうえおアイウエオゐゑ'
const AR_VOWEL = 'اويىء'
const HE_VOWEL = 'אהעוי'
const DEVA_MATRA = /[ऺ-ॏ॑-ॗॢॣ]/u

/** 拉丁/西里尔/希腊：元音连成一段 (.v)，辅音连成一段 (.c)。 */
function runs(word, vowelSet) {
  const out = []
  for (const ch of word) {
    const isV = vowelSet.includes(ch)
    const cls = isV ? 'v' : 'c'
    const last = out[out.length - 1]
    if (last && last.cls === cls) last.text += ch
    else out.push({ cls, text: ch })
  }
  return out
}

/** 假名：纯元音 .v；带声母 .cv；长音符 ー .n（不发音符号）。 */
function kanaRuns(word) {
  const out = []
  for (const ch of word) {
    const cls = ch === 'ー' ? 'n' : KANA_VOWEL.includes(ch) ? 'v' : /[ぁ-ゖァ-ヺ]/.test(ch) ? 'cv' : null
    const last = out[out.length - 1]
    if (cls !== null && last && last.cls === cls) last.text += ch
    else out.push({ cls, text: ch })
  }
  return out
}

/** 两行叠印的「下层元音色 + 上层辅音蓝/元音透明」：返回 {lay, top}。 */
function overlayRuns(word, isVowelCarrier) {
  const top = []
  for (const ch of word) {
    const cls = isVowelCarrier(ch) ? 't' : 'c'
    const last = top[top.length - 1]
    if (last && last.cls === cls) last.text += ch
    else top.push({ cls, text: ch })
  }
  return top
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function spans(segs) {
  return segs.map((s) => (s.cls === null ? esc(s.text) : `<span class="${s.cls}">${esc(s.text)}</span>`)).join('')
}

// ---------------------------------------------------------------- 各语种的词形 HTML
/** 一格的「词」HTML（海报与视频共用同一份构造）。 */
function wordHtml(w, { inline }) {
  if (w.word_html) return w.word_html // 逃生口：自动规则覆盖不到的（如日语汉字词）
  const text = inline ? (w.inline ?? w.word) : w.word
  switch (w.script) {
    case 'sc': {
      // 汉字逐字成列，注音在本字列里
      const chars = w.zhuyin ?? []
      return chars.map(([hz, annot], i) => {
        const a = annot ? `<span class="annot">${annot}</span>` : ''
        return `<span class="zi"><span class="hz">${esc(hz)}</span>${a}</span>`
      }).join('')
    }
    case 'ko':
    case 'kr': {
      const syls = w.ko_syllables ?? []
      // 融合音节（初声+中声笔画横接成一个连通域，矩形补丁拆不开）：
      // 走 `.cv` 融合渐变整字降级，不生成 .k<码位> 补丁类。
      // ⚠️ 哪些音节融合**必须实测**（measure-korean 会响亮报 LABEL FAIL），
      //    在数据文件里用 ko_fused_syllables 显式声明，不在这里猜。
      const fused = new Set(w.ko_fused_syllables ?? [])
      return syls
        .map((s) => {
          if (fused.has(s)) return `<span class="ksyl cv">${esc(s)}</span>`
          return `<span class="ksyl k${s.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}">${esc(s)}</span>`
        })
        .join('')
    }
    case 'ar': {
      const top = overlayRuns(text, (c) => AR_VOWEL.includes(c))
      return `<span class="stack f-ar" dir="rtl"><span class="lay" dir="rtl" aria-hidden="true" style="color:var(--vowel)">${esc(text)}</span><span class="top" dir="rtl">${spans(top)}</span></span>`
    }
    case 'he': {
      const top = overlayRuns(text, (c) => HE_VOWEL.includes(c))
      return `<span class="stack f-he" dir="rtl"><span class="lay v" dir="rtl" aria-hidden="true">${esc(text)}</span><span class="top" dir="rtl">${spans(top)}</span></span>`
    }
    case 'deva': {
      const top = overlayRuns(text, (c) => DEVA_MATRA.test(c))
      return `<span class="stack f-deva"><span class="lay v" aria-hidden="true">${esc(text)}</span><span class="top">${spans(top)}</span></span>`
    }
    case 'jp': return spans(kanaRuns(text))
    case 'latin': return spans(runs(text, VOWELS.latin))
    case 'cyrillic': return spans(runs(text, VOWELS.cyrillic))
    case 'greek': return spans(runs(text, VOWELS.greek))
    default: return esc(text)
  }
}

/** 一格的词外框 class：汉字格用 .f-sc，RTL 用 .f-ar/.f-he，其余继承西文栈。 */
function wordBoxClass(w) {
  if (w.script === 'sc') return 'f-sc'
  if (w.script === 'jp') return 'f-jp'
  if (w.script === 'kr') return 'f-kr'
  if (w.script === 'ar') return ''
  if (w.script === 'he') return ''
  if (w.script === 'deva') return ''
  return ''
}
function wordInlineStyle(w) {
  // 汉字格整词墨色（注音另起一行）；其余继承
  return w.script === 'sc' ? ' style="color:var(--ink)"' : ''
}
function wordItalic(w) {
  return w.italic ? ' style="font-style:italic"' : ''
}

// ---------------------------------------------------------------- 数据读入与自检
const data = JSON.parse(readFileSync(DATA, 'utf8'))
const WORDS = data.words
if (!Array.isArray(WORDS) || WORDS.length !== 12) {
  throw new Error(`数据必须给 12 个语种（给的是 ${WORDS?.length ?? 'none'}）`)
}
const ORDER = ['zh-CN', 'en-US', 'de-DE', 'fr-FR', 'es-ES', 'ru-RU', 'el-GR', 'hi-IN', 'ar-SA', 'he-IL', 'ja-JP', 'ko-KR']
for (const [i, w] of WORDS.entries()) {
  if (w.locale !== ORDER[i]) throw new Error(`第 ${i + 1} 格应是 ${ORDER[i]}，给的是 ${w.locale}`)
  // 旁白句必须由 tokens 拼成（卡拉OK按 token 逐帧亮）。
  // ⚠️ 比对时**去掉标点与空白**：edge-tts 的词边界不带标点（实测 ru 的
  // "Суши, японское блюдо" 边界是 "Суши"，逗号不在词里），所以
  // 「tokens 拼出的串 == 原句」只在去标点后成立。
  const bare = (s) => s.replace(/[.,!?;:'"“”‘’·、。，！？：；「」『』（）()\[\]\-—…]/g, '').replace(/\s+/g, '')
  if (bare(w.tokens.join('')) !== bare(w.sentence)) {
    throw new Error(`${w.locale}：tokens 拼不出 sentence\n  tokens=${w.tokens.join(' ')}\n  sentence=${w.sentence}`)
  }
}

// ---------------------------------------------------------------- 海报
const posterStyle = readFileSync(join(TMPL, 'poster_style.css'), 'utf8')
  // 韩语逐音节补丁类由 measure-korean 测量后注入（每期音节不同）→
  // 这里先留 CSS 注释占位（不能留裸文本，会被 CSS 解析器当成坏规则）
  .replace('{{KO_CSS}}', '/*__KO_CSS__*/')
const posterFit = readFileSync(join(TMPL, 'poster_fit.js'), 'utf8')
const LEGEND = [
  ['v', '元音', 'vowel'],
  ['c', '辅音', 'consonant'],
  ['n', '声调 · 不发音符号', 'tone / silent'],
  ['cv', '辅音＋元音合体', 'kana'],
  ['ink', '汉字 · 注音', 'ink + annotation'],
]

const cells = WORDS.map((w, i) => {
  const cls = wordBoxClass(w)
  return `    <!-- ${i + 1} ${w.label} -->
    <div class="cell">
      <div class="cellhead"><div class="lang"><span class="f-sc">${esc(w.label)}</span><small class="f-west">${esc(w.label_en)}</small></div><div class="natv ${w.natv_class ?? ''}">${esc(w.natv)}</div></div>
      <div class="wordbox"><div class="word ${cls}"${wordInlineStyle(w)}${wordItalic(w)}>${wordHtml(w, { inline: false })}</div></div>
      <div class="tagrow"><span class="tag">${esc(w.tag)}</span></div>
      <div class="translit">${w.translit_html}</div>
    </div>`
}).join('\n\n')

const posterHtml = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>${esc(data.title_zh)} · Twelve Scripts</title>
<style>
/*__FONTS__*/
${posterStyle}
</style>
</head>
<body>
<div class="poster">
  <header>
    <div>
      <div class="title-zh f-sc">${esc(data.title_zh)}</div>
      <div class="title-sub"><b>${esc(data.title_en)} · IN TWELVE LANGUAGES</b> <span class="f-sc">${esc(data.series_sub)}</span></div>
    </div>
    <div class="legend">
${LEGEND.map(([c, zh, en]) => `      <div class="li"><span class="dot ${c}"></span><b class="f-sc">${zh}</b> ${en}</div>`).join('\n')}
    </div>
  </header>
  <div class="rule"></div>

  <div class="grid">
${cells}
  </div>
</div>

${posterFit}
</body>
</html>
`

// ---------------------------------------------------------------- 视频
const videoStyle = readFileSync(join(TMPL, 'video_style.css'), 'utf8')
  .replace('{{KO_CSS}}', '/*__KO_CSS__*/')
const videoScript = readFileSync(join(TMPL, 'video_script.js'), 'utf8')

const scenes = WORDS.map((w, i) => {
  const cls = wordBoxClass(w)
  const inlineWord = wordHtml(w, { inline: true })
  // 句中：第一个 token 是菜名（带逐字着色），其余 token 素色
  const toks = w.tokens.map((t, ti) => {
    if (ti === 0) return `<span class="tok">${inlineWord}</span>`
    return `<span class="tok">${esc(t)}</span>`
  }).join(' ')
  return `<!-- ${i + 1} ${w.locale} -->
<section class="scene" id="sc-${w.locale}" data-lang="${w.locale}">
  <div class="brand"><b>FOOD NAMES</b> · <span class="f-sc gold">${esc(data.title_zh)}</span> · IN TWELVE LANGUAGES</div>
  <div class="pageno">${String(i + 1).padStart(2, '0')} / 12</div>
  <div class="headrule"></div>
  <div class="langline"><span class="langlabel">${esc(w.label)}<small>${esc(w.label_en)}</small></span><span class="natv ${w.natv_class ?? ''}">${esc(w.natv)}</span><span class="tag">${esc(w.tag)}</span></div>
  <div class="stage"><div class="word ${cls}" id="w-${w.locale}">${toks}</div></div>
  <div class="badge"><span class="pdot"></span><span class="pname ${w.persona_class ?? ''}">${esc(w.persona.name)}</span><span class="platin">${esc(w.persona.latin)}</span><span class="pvoice">${esc(w.locale)} · ${esc(w.voice_short)}</span></div>
  <div class="translit">${w.translit_html}</div>
  <div class="footrule"></div>
  <div class="footer"><span class="f-sc">${w.foot_html}</span><span class="f-sc">配音</span> · EDGE TTS NEURAL</div>
</section>`
}).join('\n\n')

const videoHtml = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>${esc(data.title_zh)} · Video Scenes</title>
<style>
/*__FONTS__*/
${videoStyle}
</style>
</head>
<body>

${scenes}

${videoScript}
</body>
</html>
`

// ---------------------------------------------------------------- 配音脚本
const voices = {
  tts_dir: 'tts',
  langs: WORDS.map((w) => ({
    locale: w.locale,
    persona: w.persona.name,
    latin: w.persona.latin,
    gender: w.gender,
    voice: w.voice,
    text: w.sentence,
    tokens: w.tokens,
  })),
}

// ---------------------------------------------------------------- 字体子集
const FAMILY_CLASSES = {
  'Food SC': ['f-sc', 'annot', 'tag'],
  'Food JP': ['f-jp'],
  'Food KR': ['f-kr'],
  'Food Arabic': ['f-ar'],
  'Food Hebrew': ['f-he'],
  'Food Deva': ['f-deva'],
  'Food West': ['f-west', 'translit', 'brand', 'pageno', 'footer', 'voice'],
}
const GOOGLE = {
  'Food SC': 'Noto+Serif+SC:wght@600',
  'Food JP': 'Noto+Sans+JP:wght@500',
  'Food KR': 'Noto+Sans+KR:wght@500',
  'Food Arabic': 'Noto+Sans+Arabic:wght@500',
  'Food Hebrew': 'Noto+Sans+Hebrew:wght@500',
  'Food Deva': 'Noto+Sans+Devanagari:wght@500',
  'Food West': 'Noto+Sans:wght@500;700',
}

mkdirSync(OUT, { recursive: true })
const posterPath = join(OUT, 'poster_src.html')
const videoPath = join(OUT, 'video_src.html')
const fontsPath = join(OUT, 'fonts.json')
writeFileSync(posterPath, posterHtml, 'utf8')
writeFileSync(videoPath, videoHtml, 'utf8')
writeFileSync(join(OUT, 'voices.json'), JSON.stringify(voices, null, 1) + '\n', 'utf8')
writeFileSync(join(OUT, 'episode.json'), JSON.stringify(data, null, 1) + '\n', 'utf8')

// 字体子集：先用空 text 建清单，让 audit-charset（家族栈口径）报缺字，补进去直到收敛。
// 收敛 = 页面里每个归属到该 family 的字符都在它的子集名单里。
const spec = Object.keys(FAMILY_CLASSES).map((family) => ({
  family,
  google: GOOGLE[family],
  text: '',
  classes: FAMILY_CLASSES[family],
}))
writeFileSync(fontsPath, JSON.stringify(spec, null, 1) + '\n', 'utf8')

for (const src of [posterPath, videoPath]) {
  for (let round = 0; round < 12; round++) {
    const [missing] = audit_charset.check(src, fontsPath)
    if (missing.length === 0) break
    for (const { fam, ch } of missing) {
      const e = spec.find((x) => x.family === fam)
      if (e && !e.text.includes(ch)) e.text += ch
    }
    writeFileSync(fontsPath, JSON.stringify(spec, null, 1) + '\n', 'utf8')
  }
  const [missing, counts] = audit_charset.check(src, fontsPath)
  if (missing.length > 0) {
    console.error(`字体子集未收敛：${src}`)
    for (const m of missing.slice(0, 20)) console.error(`  ${m.fam}: '${m.ch}' ${m.code}`)
    process.exit(1)
  }
  console.log(`${src.split(/[\\/]/).pop()}：子集收敛 ${JSON.stringify(counts)}`)
}

console.log(`built ep${data.episode} ${data.slug} → ${OUT}`)
