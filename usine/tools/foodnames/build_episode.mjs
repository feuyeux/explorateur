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
function wordHtml(w, { inline, text, wordHtmlOk = true, koPatches = true } = {}) {
  const natural = inline ? (w.inline ?? w.word) : w.word
  const t = text ?? natural
  if (wordHtmlOk && t === natural && w.word_html) return w.word_html // 逃生口：自动规则覆盖不到的（如日语汉字词）
  switch (w.script) {
    case 'sc': {
      // 汉字逐字成列，注音在本字列里（只有整词对得上时才有注音）
      if (t === natural) {
        const chars = w.zhuyin ?? []
        return chars.map(([hz, annot]) => {
          const a = annot ? `<span class="annot">${annot}</span>` : ''
          return `<span class="zi"><span class="hz">${esc(hz)}</span>${a}</span>`
        }).join('')
      }
      return `<span class="zi"><span class="hz">${esc(t)}</span></span>`
    }
    case 'ko':
    case 'kr': {
      const fused = new Set(w.ko_fused_syllables ?? [])
      // 视频侧：补丁类 `.k####` 的 background-position 是按**海报**字号实测的；
      // 视频的主角词被拟合到另一个字号（D2），补丁必然错位 → 视频一律走 `.cv` 融合渐变。
      return [...t]
        .map((s) => (!koPatches || fused.has(s)
          ? `<span class="ksyl cv">${esc(s)}</span>`
          : `<span class="ksyl k${s.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}">${esc(s)}</span>`))
        .join('')
    }
    case 'ar': {
      const top = overlayRuns(t, (c) => AR_VOWEL.includes(c))
      return `<span class="stack f-ar" dir="rtl"><span class="lay" dir="rtl" aria-hidden="true" style="color:var(--vowel)">${esc(t)}</span><span class="top" dir="rtl">${spans(top)}</span></span>`
    }
    case 'he': {
      const top = overlayRuns(t, (c) => HE_VOWEL.includes(c))
      return `<span class="stack f-he" dir="rtl"><span class="lay v" dir="rtl" aria-hidden="true">${esc(t)}</span><span class="top" dir="rtl">${spans(top)}</span></span>`
    }
    case 'deva': {
      const top = overlayRuns(t, (c) => DEVA_MATRA.test(c))
      return `<span class="stack f-deva"><span class="lay v" aria-hidden="true">${esc(t)}</span><span class="top">${spans(top)}</span></span>`
    }
    case 'jp': return spans(kanaRuns(t))
    case 'latin': return spans(runs(t, VOWELS.latin))
    case 'cyrillic': return spans(runs(t, VOWELS.cyrillic))
    case 'greek': return spans(runs(t, VOWELS.greek))
    default: return esc(t)
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

// ---------------------------------------------------------------- D1：句中的词形
// 判据：画面句子必须与配音句**逐 token 相同**。旧实现无条件把第一个 token 换成词形，
// 句首是冠词/助词（Le / El / Το / 카레는）时那个词被吃掉、词本身再重复一遍。
// 现在只给「真的是这个词」的那一段上色：token 序列一个不动（不吃、不重复）。
const fold = (s) => String(s).toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')

/** 在 token 序列里定位词形：返回半开区间 { a: [token, ch], b: [token, ch] }，找不到返回 null。 */
function wordSpan(tokens, forms, script) {
  const fs = [...new Set(forms.filter(Boolean).map((f) => String(f).trim()).filter(Boolean))]
  // ① 整个 token 就是词形（忽略大小写与变音符号）
  for (const f of fs) {
    for (let i = 0; i < tokens.length; i++) {
      if (fold(tokens[i]) === fold(f)) return { a: [i, 0], b: [i, tokens[i].length] }
    }
  }
  // ② 逐字流上找：每个原始字带自己的折叠形（NFD 会一变多，如韩语音节→字母、
  //    天城文的元音符号），因此按「折叠串前缀」推进，而不是按单字相等。
  const flat = []
  tokens.forEach((t, i) => {
    for (let k = 0; k < t.length; k++) flat.push({ c: t[k], f: fold(t[k]), ti: i, ki: k })
    if (i < tokens.length - 1) flat.push({ c: ' ', f: ' ', ti: i, ki: t.length })
  })
  // 汉字/假名/谚文里词可以续在 token 内部（카레는 / カレーは / フライドポテトは），
  // 拉丁/西里尔/希腊/阿拉伯/希伯来/天城文要求词在 token 边界收尾。
  const noSpace = ['sc', 'jp', 'kr'].includes(script)
  for (const f of fs) {
    const target = fold(f)
    for (let s = 0; s < flat.length; s++) {
      if (s > 0 && flat[s - 1].c !== ' ') continue
      let t = 0, q = s, ok = true
      while (t < target.length) {
        if (q >= flat.length) { ok = false; break }
        const el = flat[q]
        const atWordStart = t === 0 || target[t - 1] === ' '
        if (target[t] === ' ') {
          if (el.c === ' ') { t++; q++; continue }
          ok = false; break
        }
        if (el.f && target.startsWith(el.f, t)) { t += el.f.length; q++; continue }
        // 词首容忍流里多一个定冠词（القهوة vs قهوة）
        if (atWordStart && script === 'ar' && el.f === 'ا' && flat[q + 1]?.f === 'ل') { q += 2; continue }
        ok = false; break
      }
      if (!ok) continue
      const nxt = flat[q]
      if (nxt && nxt.c !== ' ' && !noSpace) continue
      const a = [flat[s].ti, flat[s].ki]
      const b = !nxt
        ? [tokens.length - 1, tokens[tokens.length - 1].length]
        : nxt.c === ' '
          ? [nxt.ti, tokens[nxt.ti].length]
          : [nxt.ti, nxt.ki]
      return { a, b }
    }
  }
  return null
}

/** 当前词的高亮按 token 的字母种类挑（D5：只能是品牌三色）。
 *  含元音 → 元音红 #c9403a；只有辅音 → 辅音蓝 #2f5d9e；
 *  声调/不发音/汉字/假名/整词素色 → 声调金 #b8860b。
 *  注音层（.annot）不是 token 的字母，先剥掉再判。 */
function tokKind(html) {
  const bare = html.replace(/<span class="annot">[\s\S]*?<\/span>\s*<\/span>/g, '')
  if (/class="[^"]*\bv\b/.test(bare)) return 'kv'
  if (/class="[^"]*\bcv\b|class="[^"]*\bc\b/.test(bare)) return 'kc'
  return 'kt'
}

/** HTML 的可见文字：跳过 .annot 与 .stack > .top（与门禁同口径）。 */
function visibleText(html) {
  const stack = []
  let out = ''
  for (const t of html.match(/<[^>]+>|[^<]+/g) ?? []) {
    if (t.startsWith('</')) { stack.pop(); continue }
    if (t.startsWith('<')) {
      const cls = (t.match(/class="([^"]*)"/) ?? [, ''])[1].split(/\s+/).filter(Boolean)
      const skip = cls.includes('annot') || (stack.some((s) => s.includes('stack')) && cls.includes('top'))
      stack.push(skip ? '__skip__' : cls.join(' '))
      continue
    }
    if (stack.includes('__skip__')) continue
    out += t
  }
  return out
}

/** 一句 = 一段一个不动的 token 序列，只有词形那一段带逐字着色。 */
function sentenceHtml(w) {
  const span = wordSpan(w.tokens, [w.word, w.inline ?? w.word], w.script)
  if (!span) console.error(`  ! ${w.locale}：句中未找到词形（句子保持素色，token 序列不变）`)
  const html = w.tokens.map((t, i) => {
    let from = null, to = null
    if (span && i >= span.a[0] && i <= span.b[0]) {
      from = i === span.a[0] ? span.a[1] : 0
      to = i === span.b[0] ? span.b[1] : t.length
      if (to <= from) { from = null; to = null }
    }
    const mid = from === null ? '' : wordHtml(w, { inline: true, text: t.slice(from, to), wordHtmlOk: false, koPatches: false })
    const inner = from === null ? esc(t) : esc(t.slice(0, from)) + mid + esc(t.slice(to))
    return `<span class="tok ${mid ? tokKind(mid) : 'kt'}">${inner}</span>`
  }).join(' ')
  // D1 自检：画面上的可见文字必须与 w.tokens 逐 token 相同（不吃、不重复）。
  // 可见文字 = 去掉标签、去掉注音层 .annot、去掉叠印上层 .stack > .top。
  if (visibleText(html) !== w.tokens.join(' ')) {
    throw new Error(`${w.locale}：画面句子与 token 序列不一致\n  画面=${visibleText(html)}\n  tokens=${w.tokens.join(' ')}`)
  }
  return html
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
  // D2：词形是**自己一个元素**（不是句首 token），由 video_script.js 拟合到
  // ≥12% 帧高（竖屏 230px）或 ≥30% 帧宽（竖屏 324px）。
  // 注音（ruby 的 <rt>）包进 .annot：注音不是词形本身，量墨迹/量文字时都要排除。
  const heroHtml = wordHtml(w, { inline: false, koPatches: false })
    .replace(/<rt>([\s\S]*?)<\/rt>/g, '<rt><span class="annot">$1</span></rt>')
  return `<!-- ${i + 1} ${w.locale} -->
<section class="scene" id="sc-${w.locale}" data-lang="${w.locale}">
  <div class="brand"><b>FOOD NAMES</b> · <span class="f-sc gold">${esc(data.title_zh)}</span> · IN TWELVE LANGUAGES</div>
  <div class="pageno">${String(i + 1).padStart(2, '0')} / 12</div>
  <div class="headrule"></div>
  <div class="langline"><span class="langlabel">${esc(w.label)}<small>${esc(w.label_en)}</small></span><span class="natv ${w.natv_class ?? ''}">${esc(w.natv)}</span><span class="tag">${esc(w.tag)}</span></div>
  <div class="hero word ${cls}" id="hero-${w.locale}" dir="auto"${wordInlineStyle(w)}${wordItalic(w)}>${heroHtml}</div>
  <div class="stage"><div class="sentence" id="w-${w.locale}" dir="auto">${sentenceHtml(w)}</div></div>
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
