// build_episode.mjs — 「水果名称」系列：一期数据 → 一套产物源文件
//
// 输入：data/fruitlist.json（40 词 × 12 语）+ --episode N + art/ 插画
// 输出（到 --out 目录）：poster_src.html / video_src.html / voices.json /
//   fonts.json / episode.json / art/<key>.png
//
// 与 foodnames 版的差异：
// - 一格（一个语种）装 **4 个词**（对应 4 张贴纸），不是 1 词 + 1 句；
//   旁白句 = 4 个词按序连读（tokens = 4 词，D1 句子门不适用——没有句子）。
// - 海报在 grid 上方多一条**贴纸带**（4 张插画 + 序号徽章），词格用
//   ①②③④ 与贴纸对应。
// - 韩语融合音节在 build 时未知（要等 measure-korean 实测）——由
//   run_episode 走「build → measure → 标记 fused → rebuild → 注入」两遍。
//   --fused "<sy1,sy2>" 指定哪些音节走 .cv 渐变。
//
// 跑法：node --import tsx tools/fruitnames/build_episode.mjs --episode 1 --out examples/fruitnames-ep01
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { audit_charset } from '../../packages/poster/src/index.ts'

const here = dirname(fileURLToPath(import.meta.url))
const USINE = resolve(here, '..', '..')

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const EPISODE = Number(arg('episode'))
const OUT = resolve(arg('out'))
const FUSED = new Set((arg('fused', '') ? String(arg('fused')) : '').split(',').filter(Boolean))
const TMPL = join(here, 'templates')
const ART_SRC = join(USINE, 'examples', 'fruitnames', 'art')

if (!EPISODE) { console.error('usage: build_episode.mjs --episode <N> --out <dir> [--fused a,b]'); process.exit(2) }

// ---------------------------------------------------------------- 分词规则（与 foodnames 版逐字一致）
const VOWELS = {
  latin: 'aeiouyáàâäéèêëíìîïóòôöúùûüýÿæœāēīōū',
  cyrillic: 'аеёиоуыэюяАЕЁИОУЫЭЮЯ',
  greek: 'αεηιουωάέήίόύώΑΕΗΙΟΥΩ',
}
const KANA_VOWEL = 'あいうえおアイウエオゐゑ'
const AR_VOWEL = 'اويىء'
const HE_VOWEL = 'אהעוי'
const DEVA_MATRA = /[ऺ-ॏ॑-ॗॢॣ]/u

function runs(word, vowelSet) {
  const out = []
  for (const ch of word) {
    const cls = vowelSet.includes(ch) ? 'v' : 'c'
    const last = out[out.length - 1]
    if (last && last.cls === cls) last.text += ch
    else out.push({ cls, text: ch })
  }
  return out
}
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

/** 注音符号着色：声母蓝、韵母红、调号灰。 */
const ZH_INITIAL = 'ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ'
const ZH_FINAL = 'ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦㄧㄨㄩ'
function zhuyinHtml(syl) {
  return [...syl].map((ch) => {
    const cls = ZH_INITIAL.includes(ch) ? 'c' : ZH_FINAL.includes(ch) ? 'v' : 'n'
    return `<span class="${cls}">${esc(ch)}</span>`
  }).join('')
}

/** 一格里的「一个词」HTML（海报与视频共用；foodnames 的 wordHtml 的 4 词版）。 */
function wordHtml(script, t, { koFused = new Set() } = {}) {
  switch (script) {
    case 'sc': return `<span class="zi"><span class="hz">${esc(t)}</span></span>`
    case 'kr': {
      return [...t]
        .map((s) => (koFused.has(s)
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
function wordBoxClass(script) {
  return { sc: 'f-sc', jp: 'f-jp', kr: 'f-kr' }[script] ?? ''
}
/** 当前词高亮的三色归类（与 foodnames 的 tokKind 同口径）。 */
function tokKind(script, word) {
  const bare = word
  if (script === 'latin' && [...bare].some((c) => VOWELS.latin.includes(c))) return 'kv'
  if (script === 'cyrillic' && [...bare].some((c) => VOWELS.cyrillic.includes(c))) return 'kv'
  if (script === 'greek' && [...bare].some((c) => VOWELS.greek.includes(c))) return 'kv'
  if (script === 'jp' && [...bare].some((c) => KANA_VOWEL.includes(c))) return 'kv'
  if (script === 'kr') return 'kt'
  return 'kc'
}

// ---------------------------------------------------------------- 语种名册 + 音色（承 foodnames 班底）
const ROSTER = [
  { locale: 'zh-CN', label: '汉语', label_en: 'CHINESE', natv: '中文', script: 'sc', voice: 'zh-CN-XiaoxiaoNeural', pname: '林小满', platin: 'Lín Xiǎomǎn' },
  { locale: 'en-US', label: '英语', label_en: 'ENGLISH', natv: 'English', script: 'latin', voice: 'en-US-JennyNeural', pname: 'Ruby', platin: 'Ruby' },
  { locale: 'de-DE', label: '德语', label_en: 'GERMAN', natv: 'Deutsch', script: 'latin', voice: 'de-DE-ConradNeural', pname: 'Felix', platin: 'Felix' },
  { locale: 'fr-FR', label: '法语', label_en: 'FRENCH', natv: 'Français', script: 'latin', voice: 'fr-FR-HenriNeural', pname: 'Théo', platin: 'Théo' },
  { locale: 'es-ES', label: '西班牙语', label_en: 'SPANISH', natv: 'Español', script: 'latin', voice: 'es-ES-ElviraNeural', pname: 'Lucía', platin: 'Lucía' },
  { locale: 'ru-RU', label: '俄语', label_en: 'RUSSIAN', natv: 'Русский', script: 'cyrillic', voice: 'ru-RU-SvetlanaNeural', pname: 'Аня', platin: 'Anya' },
  { locale: 'el-GR', label: '希腊语', label_en: 'GREEK', natv: 'Ελληνικά', script: 'greek', voice: 'el-GR-NestorasNeural', pname: 'Νίκος', platin: 'Nikos' },
  { locale: 'hi-IN', label: '印地语', label_en: 'HINDI', natv: 'हिन्दी', script: 'deva', voice: 'hi-IN-MadhurNeural', pname: 'अर्जुन', platin: 'Arjun' },
  { locale: 'ar-SA', label: '阿拉伯语', label_en: 'ARABIC', natv: 'العربية', script: 'ar', voice: 'ar-SA-HamedNeural', pname: 'عمر', platin: 'Omar' },
  { locale: 'he-IL', label: '希伯来语', label_en: 'HEBREW', natv: 'עברית', script: 'he', voice: 'he-IL-HilaNeural', pname: 'נועה', platin: 'Noa' },
  { locale: 'ja-JP', label: '日语', label_en: 'JAPANESE', natv: '日本語', script: 'jp', voice: 'ja-JP-KeitaNeural', pname: 'リク', platin: 'Riku' },
  { locale: 'ko-KR', label: '韩语', label_en: 'KOREAN', natv: '한국어', script: 'kr', voice: 'ko-KR-SunHiNeural', pname: '서연', platin: 'Seoyeon' },
]

// 汉语注音（40 词；审核稿见 examples/fruitnames/checklists/ep01，其余按同一体系补全）
const ZHUYIN = {
  apple: 'ㄆㄧㄥˊㄍㄨㄛˇ', banana: 'ㄒㄧㄤㄐㄧㄠ', orange: 'ㄔㄥˊ˙ㄗ', strawberry: 'ㄘㄠˇㄇㄟˊ',
  watermelon: 'ㄒㄧㄍㄨㄚ', grape: 'ㄆㄨˊㄊㄠˊ', pear: 'ㄌㄧˊ', peach: 'ㄊㄠˊ˙ㄗ',
  mango: 'ㄇㄤˊㄍㄨㄛˇ', pineapple: 'ㄅㄛˊㄌㄨㄛˊ', lemon: 'ㄋㄧㄥˊㄇㄥˊ', cherry: 'ㄧㄥㄊㄠˊ',
  kiwi: 'ㄇㄧˊㄏㄡˊㄊㄠˊ', melon: 'ㄏㄚㄇㄧˋㄍㄨㄚ', plum: 'ㄌㄧˇ˙ㄗ', coconut: 'ㄧㄝˊ˙ㄗ',
  pomegranate: 'ㄕˊㄌㄧㄡˊ', blueberry: 'ㄌㄢˊㄇㄟˊ', lime: 'ㄑㄧㄥㄋㄧㄥˊ', grapefruit: 'ㄒㄧㄧㄡˋ',
  avocado: 'ㄋㄧㄡˊㄧㄡˊㄍㄨㄛˇ', papaya: 'ㄇㄨˋㄍㄨㄚ', durian: 'ㄌㄧㄡˊㄌㄧㄢˊ', persimmon: 'ㄕˋ˙ㄗ',
  lychee: 'ㄌㄧˋㄓ', dragonfruit: 'ㄏㄨㄛˇㄌㄨㄥˊㄍㄨㄛˇ', guava: 'ㄈㄢㄕˊㄌㄧㄡˊ', mangosteen: 'ㄕㄢㄓㄨˊ',
  raspberry: 'ㄈㄨˋㄆㄣˊ˙ㄗ', fig: 'ㄨˊㄏㄨㄚㄍㄨㄛˇ', passionfruit: 'ㄅㄞˇㄒㄧㄤㄍㄨㄛˇ', date: 'ㄧㄝˊㄗㄠˇ',
  apricot: 'ㄒㄧㄥˋ', nectarine: 'ㄧㄡˊㄊㄠˊ', mulberry: 'ㄙㄤㄕㄣˋ', olive: 'ㄍㄢˇㄌㄢˇ',
  loquat: 'ㄆㄧˊㄆㄚˊ', cranberry: 'ㄇㄢˋㄩㄝˋㄇㄟˊ', hawthorn: 'ㄕㄢㄓㄚ', capegooseberry: 'ㄍㄨㄋㄧㄤˊㄍㄨㄛˇ',
}

// ---------------------------------------------------------------- 数据读入
const list = JSON.parse(readFileSync(join(USINE, 'examples', 'fruitnames', 'data', 'fruitlist.json'), 'utf8'))
const ep = list.episodes.find((e) => e.episode === EPISODE)
if (!ep) { console.error(`✖ fruitlist.json 里没有第 ${EPISODE} 集`); process.exit(2) }
const FRUITS = ep.fruits
if (FRUITS.length !== 4) { console.error(`✖ 第 ${EPISODE} 集词数 ${FRUITS.length} ≠ 4`); process.exit(2) }
for (const f of FRUITS) {
  if (!existsSync(join(ART_SRC, `${f.key}.png`))) {
    console.error(`✖ 缺插画 ${f.key}.png（先跑 gen_art.mjs）`); process.exit(2)
  }
}

const WORDS = ROSTER.map((r) => ({
  ...r,
  items: FRUITS.map((f) => ({
    key: f.key,
    zh: f.zh,
    en: f.en,
    word: f.words[r.locale],
    zhuyin: r.script === 'sc' ? (ZHUYIN[f.key] ?? '') : '',
  })),
}))

// ---------------------------------------------------------------- 海报
const posterStyle = readFileSync(join(USINE, 'tools', 'foodnames', 'templates', 'poster_style.css'), 'utf8')
  .replace('{{KO_CSS}}', '/*__KO_CSS__*/')
  .replace('--paper: #f7f2e6;', '--paper: #fffcf5;') // 纸色 = 参考海报画布底色（插画底已归一到它）
const fruitPosterCss = `
/* ---------- fruit series overrides ---------- */
.title-zh { font-size: 56px; letter-spacing: .04em; }
.artstrip { display: flex; justify-content: space-between; margin: 22px 0 0; }
.sticker { width: 262px; text-align: center; }
.sticker img { width: 236px; height: 236px; display: block; margin: 0 auto; }
.sticker .cap { margin-top: 2px; font-size: 22px; font-weight: 600; letter-spacing: .04em; }
.sticker .cap small { color: var(--mut); font-weight: 500; font-size: 16px; margin-left: 8px; letter-spacing: .05em; }
.sticker .idx { display: inline-block; transform: translateY(-1px); margin-right: 6px; color: var(--gold); font-weight: 700; }
.grid { margin-top: 22px; }
.cell { padding: 12px 18px 10px; }
.wordrows { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: space-evenly; }
.wrow { display: flex; align-items: center; gap: 10px; min-height: 0; }
.wrow .idx { flex: none; width: 24px; text-align: center; color: var(--gold); font-weight: 700; font-size: 17px; }
.wrow .word { white-space: nowrap; line-height: 1.22; }
.cellfoot { flex: none; display: flex; justify-content: flex-end; font-size: 12px; color: var(--mut); letter-spacing: .08em; }
/* 注音随词号缩放：foodnames 版 .annot 定值 34px 是给 ~150px 大词的；
   水果格词 ~40-60px，定值会让注音比字还大。 */
.wrow .annot { font-size: 0.32em; margin-top: 0.1em; margin-left: 0; }
/* make-covers 的注入标记锚在「ruby rt {...}\n</style>」上——水果覆盖块必须
   以同一行规则收尾，否则变体 CSS 静默不注入（ep01 实测：封面 = 海报被硬
   塞进 1080p，文字重叠 + 底行裁切）。 */
ruby rt { font-weight: 500; }
`
const posterFit = readFileSync(join(TMPL, 'poster_fit.js'), 'utf8')
const LEGEND = [
  ['v', '元音', 'vowel'],
  ['c', '辅音', 'consonant'],
  ['n', '声调 · 不发音符号', 'tone / silent'],
  ['cv', '辅音＋元音合体', 'kana'],
  ['ink', '汉字 · 注音', 'ink + annotation'],
]

const badges = ['①', '②', '③', '④']
const artStrip = FRUITS.map((f, i) => `
    <div class="sticker"><img src="art/${f.key}.png" alt=""><div class="cap"><span class="idx">${badges[i]}</span><span class="f-sc">${esc(f.zh)}</span><small>${esc(f.en)}</small></div></div>`).join('')

const cells = WORDS.map((r) => {
  const cls = wordBoxClass(r.script)
  const rows = r.items.map((it, i) => {
    const inner = r.script === 'sc' && it.zhuyin
      ? `<span class="zi"><span class="hz">${esc(it.word)}</span><span class="annot">${zhuyinHtml(it.zhuyin)}</span></span>`
      : wordHtml(r.script, it.word, { koFused: FUSED })
    return `      <div class="wrow"><span class="idx">${badges[i]}</span><div class="word ${cls}" data-fit>${inner}</div></div>`
  }).join('\n')
  return `    <!-- ${r.label} -->
    <div class="cell">
      <div class="cellhead"><div class="lang"><span class="f-sc">${esc(r.label)}</span><small>${esc(r.label_en)}</small></div><div class="natv">${esc(r.natv)}</div></div>
      <div class="wordrows">
${rows}
      </div>
      <div class="cellfoot">FRUIT NAMES</div>
    </div>`
}).join('\n\n')

const posterHtml = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>${esc(ep.title_zh)} · Twelve Scripts</title>
<style>
/*__FONTS__*/
${posterStyle}
${fruitPosterCss}</style>
</head>
<body>
<div class="poster">
  <header>
    <div>
      <div class="title-zh f-sc">${esc(ep.title_zh)}</div>
      <div class="title-sub"><b>${esc(ep.title_en)} · FRUIT NAMES IN TWELVE LANGUAGES</b> <span class="f-sc">第 ${String(EPISODE).padStart(2, '0')} 集</span></div>
    </div>
    <div class="legend">
${LEGEND.map(([c, zh, en]) => `      <div class="li"><span class="dot ${c}"></span><b class="f-sc">${zh}</b> ${en}</div>`).join('\n')}
    </div>
  </header>
  <div class="rule"></div>
  <div class="artstrip">${artStrip}
  </div>
  <div class="grid">
${cells}
  </div>
</div>

${posterFit}
</body>
</html>
`

// ---------------------------------------------------------------- 封面（自包含，不走 make-covers）
// 为什么不用 make-covers：它的变体注入靠两个文本锚（ruby rt 行 + per-cell
// auto-fit 注释），与水果版的追加 CSS 相互打架——规则进了文件却没进样式表
// （2026-11-07 ep01 实测，几何探针定位）。封面=标题+4 大贴纸+图例行，字大
// 干净；12 语网格是海报（1240×1754）的事，封面不塞。
// 平台契约：每个全屏变体保留自己的边框色（cover check 采样 2px 环，B站粉/
// 小红书白），与 foodnames 同口径。
const coverBoot = `
<script>
const FMT = new URLSearchParams(location.search).get("fmt");
document.querySelector(".poster").classList.add(FMT === "P" ? "pt" : FMT === "T" ? "t34" : "lc");
</script>
`
const coverCss = `
/* ---------- fruit cover (self-contained) ---------- */
/* ⚠️ 本块必须自给自足：fruitPosterCss 只进海报，封面用不到——基础样式
   （artstrip/sticker/cap/idx）在这里重复一份（ep01 实测：漏了基础规则，
   贴纸竖排、4 张只露出 2 张）。 */
.artstrip { display: flex; justify-content: space-between; }
.sticker { text-align: center; }
.sticker img { display: block; margin: 0 auto; border-radius: 16px; }
.sticker .cap { margin-top: 2px; font-weight: 600; letter-spacing: .04em; }
.sticker .cap small { color: var(--mut); font-weight: 500; margin-left: 8px; letter-spacing: .05em; }
.sticker .idx { display: inline-block; transform: translateY(-1px); margin-right: 6px; color: var(--gold); font-weight: 700; }
.poster { margin: 0 auto; }
.coverbody { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.coverfoot { margin-top: auto; border-top: 1.5px solid var(--line); padding-top: 14px;
  display: flex; justify-content: space-between; font-size: 18px; color: var(--mut); letter-spacing: .14em; }
.poster.lc { width: 1920px; height: 1080px; padding: 44px 64px 36px; }
.poster.lc .title-zh { font-size: 76px; }
.poster.lc .title-sub { font-size: 21px; margin-top: 12px; }
.poster.lc .artstrip { margin: 20px 0 0; }
.poster.lc .sticker { width: 420px; }
.poster.lc .sticker img { width: 360px; height: 360px; }
.poster.lc .sticker .cap { font-size: 30px; }
.poster.lc .sticker .cap small { font-size: 21px; }
.poster.lc .coverfoot { font-size: 20px; }
.poster.pt { width: 1080px; height: 1920px; padding: 60px 52px 48px; }
.poster.pt .title-zh { font-size: 68px; }
.poster.pt .title-sub { font-size: 18px; }
/* 竖版/3:4：4 张贴纸改 2×2——横排一行 4×460=1840 装不进 1080 宽，
   第 4 张被切出画（ep02 实测）。中段余量用 space-evenly 均摊。 */
.poster.pt .coverbody { justify-content: space-evenly; }
.poster.pt .coverfoot { margin-top: 0; }
.poster.pt .artstrip { display: grid; grid-template-columns: repeat(2, 470px); gap: 22px 16px; justify-content: center; }
.poster.pt .sticker { width: 470px; }
.poster.pt .sticker img { width: 420px; height: 420px; }
.poster.pt .sticker .cap { font-size: 32px; }
.poster.pt .sticker .cap small { font-size: 22px; }
.poster.pt .coverfoot { font-size: 20px; }
.poster.t34 { width: 1080px; height: 1440px; padding: 44px 48px 38px; }
.poster.t34 .title-zh { font-size: 52px; }
.poster.t34 .title-sub { font-size: 15px; margin-top: 8px; }
.poster.t34 .coverbody { justify-content: space-evenly; }
.poster.t34 .coverfoot { margin-top: 0; }
.poster.t34 .artstrip { display: grid; grid-template-columns: repeat(2, 400px); gap: 16px 14px; justify-content: center; }
.poster.t34 .sticker { width: 400px; }
.poster.t34 .sticker img { width: 340px; height: 340px; }
.poster.t34 .sticker .cap { font-size: 25px; }
.poster.t34 .sticker .cap small { font-size: 17px; }
.poster.t34 .coverfoot { font-size: 16px; }
body:has(.poster.pt) .poster { border: 8px solid #FFFFFF; }
body:has(.poster.lc) .poster { border: 8px solid #FB7299; }
body:has(.poster.t34) .poster { border: 8px solid #FFFFFF; }
`
const coverHtml = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>${esc(ep.title_zh)} · Cover</title>
<style>
/*__FONTS__*/
${posterStyle}
${coverCss}
</style>
</head>
<body>
<div class="poster cover">
  <header>
    <div>
      <div class="title-zh f-sc">${esc(ep.title_zh)}</div>
      <div class="title-sub"><b>${esc(ep.title_en)}</b> <span class="f-sc">FRUIT NAMES IN TWELVE LANGUAGES · 第 ${String(EPISODE).padStart(2, '0')} 集</span></div>
    </div>
    <div class="legend">
${LEGEND.map(([c, zh, en]) => `      <div class="li"><span class="dot ${c}"></span><b class="f-sc">${zh}</b> ${en}</div>`).join('\n')}
    </div>
  </header>
  <div class="rule"></div>
  <div class="coverbody">
    <div class="artstrip">${artStrip}
    </div>
    <div class="coverfoot"><span class="f-sc">十二种语言 · ${esc(FRUITS.map((f) => f.zh).join(' '))}</span><span class="f-sc">FRUIT NAMES · TWELVE LANGUAGES</span></div>
  </div>
</div>

${coverBoot}
</body>
</html>
`

// ---------------------------------------------------------------- 视频
const videoStyle = readFileSync(join(USINE, 'tools', 'foodnames', 'templates', 'video_style.css'), 'utf8')
  .replace('{{KO_CSS}}', '/*__KO_CSS__*/')
  .replace('--paper: #f7f2e6;', '--paper: #fffcf5;')
const fruitVideoCss = `
/* ---------- fruit series overrides ---------- */
/* 设计口径（用户定稿）：**不加另一份大字**——卡片上原有的词直接放大，
   当前水果用卡片本身（金圈 + 词的品牌底色）高亮，其余卡 dim ≥ 0.45。
   卡宽/画幅预算（防溢出，竖版优先）：
     landscape 1920×1080：4 卡 = 4×414 + 3×24 = 1728 ≤ 1920−2×80
     portrait 1080×1920：2×2 = 2×458 + 16 = 932 ≤ 1080−2×60 */
.scene { padding: 44px 80px 36px; }
.cards { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; gap: 24px; }
.card {
  width: 414px; display: flex; flex-direction: column; align-items: center;
  border-radius: 26px; padding: 16px 16px 18px;
}
.card img { width: 300px; height: 300px; display: block; border-radius: 20px; }
.card .idx { margin-top: 4px; color: var(--gold); font-weight: 700; font-size: 24px; }
.card .wordbox { width: 100%; height: 150px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.card .word { white-space: nowrap; line-height: 1.24; }
.card.cur { background: rgba(184, 134, 11, 0.10); box-shadow: 0 0 0 3px var(--gold) inset; }
html.vert .cards, body.vert .cards { display: grid; grid-template-columns: repeat(2, 458px); gap: 16px; align-content: center; justify-content: center; }
body.vert .card { width: 458px; padding: 12px 12px 14px; }
body.vert .card img { width: 310px; height: 310px; }
body.vert .card .wordbox { height: 150px; }
body.vert .langline { margin-top: 0; }
body.vert .footrule, body.vert .footer { margin-top: 0; }
`
const scenes = WORDS.map((r, i) => {
  const cls = wordBoxClass(r.script)
  const cards = r.items.map((it, j) => {
    const kind = tokKind(r.script, it.word)
    return `  <div class="card" data-fruit="${j}">
    <img src="art/${it.key}.png" alt="">
    <div class="idx">${badges[j]}</div>
    <div class="wordbox"><div class="word tok ${cls}" data-kind="${kind}" dir="auto">${wordHtml(r.script, it.word, { koFused: FUSED })}</div></div>
  </div>`
  }).join('\n')
  return `<!-- ${i + 1} ${r.locale} -->
<section class="scene" id="sc-${r.locale}" data-lang="${r.locale}">
  <div class="brand"><b>FRUIT NAMES</b> · <span class="f-sc gold">${esc(ep.title_zh)}</span> · IN TWELVE LANGUAGES</div>
  <div class="pageno">${String(i + 1).padStart(2, '0')} / 12</div>
  <div class="headrule"></div>
  <div class="langline"><span class="langlabel">${esc(r.label)}<small>${esc(r.label_en)}</small></span><span class="natv">${esc(r.natv)}</span></div>
  <div class="cards">
${cards}
  </div>
  <div class="footrule"></div>
  <div class="footer"><span class="f-sc">元音 <span class="v">■</span> · 辅音 <span class="c">■</span> · 汉字/假名/谚文 <span class="n">■</span></span><span class="f-sc">配音</span> · EDGE TTS NEURAL</div>
</section>`
}).join('\n\n')

const videoScript = readFileSync(join(TMPL, 'video_script.js'), 'utf8')

const videoHtml = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>${esc(ep.title_zh)} · Video Scenes</title>
<style>
/*__FONTS__*/
${videoStyle}
${fruitVideoCss}</style>
</head>
<body>

${scenes}

${videoScript}
</body>
</html>
`

// ---------------------------------------------------------------- 配音脚本（旁白 = 4 词按序连读）
const SEP = { 'zh-CN': '、', 'ja-JP': '、' }
const voices = {
  tts_dir: 'tts',
  langs: WORDS.map((r) => {
    const text = r.items.map((it) => it.word).join(SEP[r.locale] ?? ', ')
    return {
      locale: r.locale,
      persona: r.pname,
      latin: r.platin,
      gender: null,
      voice: r.voice,
      text,
      tokens: r.items.map((it) => it.word),
    }
  }),
}

// ---------------------------------------------------------------- 落盘 + 字体子集收敛
mkdirSync(OUT, { recursive: true })
mkdirSync(join(OUT, 'art'), { recursive: true })
for (const f of FRUITS) cpSync(join(ART_SRC, `${f.key}.png`), join(OUT, 'art', `${f.key}.png`))

writeFileSync(join(OUT, 'poster_src.html'), posterHtml, 'utf8')
writeFileSync(join(OUT, 'cover_src.html'), coverHtml, 'utf8')
writeFileSync(join(OUT, 'video_src.html'), videoHtml, 'utf8')
writeFileSync(join(OUT, 'voices.json'), JSON.stringify(voices, null, 1) + '\n', 'utf8')
writeFileSync(join(OUT, 'episode.json'), JSON.stringify({ episode: EPISODE, slug: ep.slug, title_zh: ep.title_zh, title_en: ep.title_en, fruits: FRUITS }, null, 1) + '\n', 'utf8')

const FAMILY_CLASSES = {
  'Food SC': ['f-sc', 'annot', 'tag'],
  'Food JP': ['f-jp'],
  'Food KR': ['f-kr'],
  'Food Arabic': ['f-ar'],
  'Food Hebrew': ['f-he'],
  'Food Deva': ['f-deva'],
  'Food West': ['f-west', 'translit', 'brand', 'pageno', 'footer', 'voice', 'idx', 'cap'],
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
const fontsPath = join(OUT, 'fonts.json')
const spec = Object.keys(FAMILY_CLASSES).map((family) => ({ family, google: GOOGLE[family], text: '', classes: FAMILY_CLASSES[family] }))
writeFileSync(fontsPath, JSON.stringify(spec, null, 1) + '\n', 'utf8')

for (const src of [join(OUT, 'poster_src.html'), join(OUT, 'video_src.html'), join(OUT, 'cover_src.html')]) {
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

console.log(`built ep${EPISODE} ${ep.slug} → ${OUT}`)
