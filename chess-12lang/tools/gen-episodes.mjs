// tools/gen-episodes.mjs —— 从 data/series.json 派生 12 支的成片工程文件
//
// 用法（在本项目根）：
//   node tools/gen-episodes.mjs fonts     → 写 fonts.json（字符清单由数据派生）
//   node tools/gen-episodes.mjs episodes  → 写每支的 video_src.html / voices.json / video.json / cover_src.html
//
// 纪律：属性一律派生（走法落点由规则现算，不手抄）；文本只写 data/series.json 一处。
// 运行：Node ≥24（无第三方依赖），跨平台。
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DATA = JSON.parse(readFileSync(join(ROOT, 'data', 'series.json'), 'utf8'))
const MODE = process.argv[2] ?? 'episodes'

const FILES = 'abcdefgh'
const fid = (f) => FILES.indexOf(f)
const isDark = (f, r) => (fid(f) + r) % 2 === 1   // a1 是深格

/** 阿语 harakat 与希伯来语 niqqud：TTS 与展示都去掉附标（附标可能被拼读）。 */
const HARAKAT = /[ً-ٰٟۖ-ۭ]/g
const NIQQUD = /[֑-ׇ]/g
const stripMarks = (s) => s.replace(HARAKAT, '').replace(NIQQUD, '')

// ── 走法：规则现算（属性派生，不抄格子表）────────────────────────────────
function dests(type, color) {
  const white = color === 'white'
  const f = fid(type.square.file)
  const r = white ? type.square.rank : 9 - type.square.rank
  const on = (x, y) => x >= 0 && x < 8 && y >= 1 && y <= 8
  const out = []
  const push = (x, y, cap = false) => { if (on(x, y)) out.push({ x, y, cap }) }
  switch (type.key) {
    case 'queen': case 'rook': case 'bishop': {
      const dirs = []
      if (type.key !== 'bishop') dirs.push([1, 0], [-1, 0], [0, 1], [0, -1])
      dirs.push([1, 1], [1, -1], [-1, 1], [-1, -1])
      for (const [dx, dy] of dirs) {
        let x = f + dx, y = r + dy
        while (on(x, y)) { push(x, y); x += dx; y += dy }
      }
      break
    }
    case 'king':
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) if (dx || dy) push(f + dx, r + dy)
      break
    case 'knight':
      for (const [dx, dy] of [[1, 2], [2, 1], [2, -1], [1, -2], [-1, -2], [-2, -1], [-2, 1], [-1, 2]]) push(f + dx, r + dy)
      break
    case 'pawn': {
      const dir = white ? 1 : -1
      push(f, r + dir)
      if (r === (white ? 2 : 7)) push(f, r + 2 * dir)
      push(f - 1, r + dir, true)
      push(f + 1, r + dir, true)
      break
    }
  }
  return out
}

// ── 棋盘 SVG（8×8；黑方视角翻转）─────────────────────────────────────
const CELL = 64
const PIECE_SHAPES = {
  pawn: `<circle cx="50" cy="46" r="15"/><path d="M40,58 h20 v18 h-20 z"/><path d="M26,88 h48 l-6,10 h-36 z"/>`,
  rook: `<path d="M28,30 h10 v10 h8 v-10 h8 v10 h8 v-10 h10 v18 h-44 z"/><path d="M34,48 h32 v28 h-32 z"/><path d="M26,88 h48 l-6,10 h-36 z"/>`,
  bishop: `<path d="M50,20 c14,16 20,30 20,42 h-40 c0,-12 6,-26 20,-42 z"/><circle cx="50" cy="14" r="6"/><path d="M42,30 l16,26" stroke-width="3" fill="none"/><path d="M26,88 h48 l-6,10 h-36 z"/>`,
  knight: `<path d="M40,86 l0,-30 c0,-12 8,-22 20,-26 l14,-6 4,12 -12,8 4,12 -12,8 -2,22 z"/><circle cx="60" cy="42" r="3.4"/><path d="M26,88 h48 l-6,10 h-36 z"/>`,
  queen: `<path d="M22,66 l-4,-38 16,14 16,-20 16,20 16,-14 -4,38 z"/><circle cx="18" cy="24" r="5"/><circle cx="34" cy="40" r="5"/><circle cx="50" cy="18" r="5"/><circle cx="66" cy="40" r="5"/><circle cx="82" cy="24" r="5"/><path d="M26,88 h48 l-6,10 h-36 z"/>`,
  king: `<path d="M24,66 l-4,-32 16,12 14,-18 14,18 16,-12 -4,32 z"/><path d="M50,10 v18 M41,19 h18" stroke-width="6" fill="none"/><path d="M26,88 h48 l-6,10 h-36 z"/>`,
}

function boardSVG(type, color) {
  const white = color === 'white'
  const size = CELL * 8
  const pf = white ? (x) => x : (x) => 7 - x        // 黑方视角：左右翻转
  const pr = white ? (y) => 9 - y : (y) => y        // 行号 1..8（自上而下）；白方 rank8 在顶，黑方 rank1 在顶
  const cells = []
  for (let x = 0; x < 8; x++) {
    for (let y = 1; y <= 8; y++) {
      const f = FILES[x]
      const dark = isDark(f, y)
      const px = pf(x) * CELL
      const py = (pr(y) - 1) * CELL
      cells.push(`<rect x="${px}" y="${py}" width="${CELL}" height="${CELL}" fill="${dark ? '#C0AE8C' : '#EFE7D5'}"/>`)
    }
  }
  // 落点标记
  const marks = []
  for (const d of dests(type, color)) {
    const px = pf(d.x) * CELL + CELL / 2
    const py = (pr(d.y) - 1) * CELL + CELL / 2
    marks.push(d.cap
      ? `<circle cx="${px}" cy="${py}" r="12" fill="none" stroke="#C9403A" stroke-width="4"/>`
      : `<circle cx="${px}" cy="${py}" r="10" fill="#C9403A" fill-opacity="0.85"/>`)
  }
  // 棋子
  const fx = pf(fid(type.square.file))
  const fy = pr(white ? type.square.rank : 9 - type.square.rank)
  const piece = `<g transform="translate(${fx * CELL + 6},${(fy - 1) * CELL + 4}) scale(0.52)">${PIECE_SHAPES[type.key]}</g>`
  // 坐标
  const labels = []
  for (let x = 0; x < 8; x++) {
    labels.push(`<text x="${pf(x) * CELL + CELL / 2}" y="${size + 20}" class="coord" text-anchor="middle">${FILES[x]}</text>`)
  }
  for (let y = 1; y <= 8; y++) {
    labels.push(`<text x="${size + 20}" y="${(pr(y) - 1) * CELL + CELL / 2 + 6}" class="coord" text-anchor="middle">${y}</text>`)
  }
  const ink = white ? '#F7F3EA' : '#241F1A'
  const stroke = white ? '#2C2620' : '#0F0D0B'
  return `<svg class="board" viewBox="0 0 ${size + 34} ${size + 34}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .coord { font: 600 17px "Noto Sans", sans-serif; fill: #8A7E6C; }
    .piece { fill: ${ink}; stroke: ${stroke}; stroke-width: 3.5; stroke-linejoin: round; }
  </style>
  <rect x="-2" y="-2" width="${size + 4}" height="${size + 4}" fill="none" stroke="#B9AC95" stroke-width="3"/>
  ${cells.join('\n  ')}
  ${marks.join('\n  ')}
  <g class="piece">${piece}</g>
  ${labels.join('\n  ')}
</svg>`
}

// ── 文本工具 ─────────────────────────────────────────────────────────
/** 旁白：句子按标点切成小句；TTS 文本用空格连接（空格在词边界映射时被跳过 → 高亮零漂移）。 */
function splitClauses(sentences) {
  const out = []
  for (const s of sentences) {
    for (const p of s.split(/(?<=[，。！？；：、])/)) {
      const t = p.trim()
      if (t) out.push(t)
    }
  }
  return out
}
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** 尾部标点（，。！？：；、）——edge-tts 的词边界不覆盖标点，
 *  标点若留在 TTS 文本里，词边界与 token 流的字符位会错位（高亮漂移，
 *  甚至末尾 token 拿不到边界 → tokenTimings 抛错）。故 TTS 文本去标点、
 *  用空格断句，标点只留在画面上。 */
const stripTrail = (s) => s.replace(/[，。！？：；、]+$/u, '').trim()

// ── 字体族：字符归族 = 脚本判定 ───────────────────────────────────────
//
// 一个字该由哪一族渲染，只由**字符本身**决定：中文→sc、日文假名→jp、谚文→kr、
// 阿拉伯→ar、希伯来→he、天城→deva，其余（拉丁/希腊/西里尔/IPA/数字/标点）→west。
// 不靠人肉分族：混排文字（「阿语 ملكة = 王后」）由 spans() 按脚本切成带 f-* 的片段，
// 每段自带族类，落到哪一族的 subset 由脚本说了算。
// 术语大字、本语自称、班底人名走「本族专用」（force）——它们是那个语种的**名字**，
// 应当用那个语种自己的字体排，而不是被脚本猜。
const FAMS = [
  { key: 'sc',   family: 'OB Chess SC',     google: 'Noto+Serif+SC:wght@600;700',        cls: 'f-sc' },
  { key: 'west', family: 'OB Chess West',   google: 'Noto+Sans:wght@400;500;600;700',    cls: 'f-west' },
  { key: 'jp',   family: 'OB Chess JP',     google: 'Noto+Sans+JP:wght@500;700',          cls: 'f-jp' },
  { key: 'kr',   family: 'OB Chess KR',     google: 'Noto+Sans+KR:wght@500;700',          cls: 'f-kr' },
  { key: 'ar',   family: 'OB Chess Arabic', google: 'Noto+Sans+Arabic:wght@500;700',     cls: 'f-ar' },
  { key: 'he',   family: 'OB Chess Hebrew', google: 'Noto+Sans+Hebrew:wght@500;700',     cls: 'f-he' },
  { key: 'deva', family: 'OB Chess Deva',   google: 'Noto+Sans+Devanagari:wght@500;700', cls: 'f-deva' },
]
const FAM_CLASS = Object.fromEntries(FAMS.map((f) => [f.cls, f.key]))
const FAM_CLS = Object.fromEntries(FAMS.map((f) => [f.key, f.cls]))

/** 字符 → 族键（按 Unicode 区块判脚本）。 */
function famOfChar(ch) {
  const c = ch.codePointAt(0)
  if (c >= 0x4e00 && c <= 0x9fff) return 'sc'   // 中日韩统一表意文字
  if (c >= 0x3400 && c <= 0x4dbf) return 'sc'   // 扩展 A
  if (c >= 0x3000 && c <= 0x303f) return 'sc'   // 中日韩标点
  if (c >= 0xff00 && c <= 0xffef) return 'sc'   // 全角
  if (c === 0x2014 || c === 0x2026) return 'sc'  // 破折号 / 省略号（中文排版）
  if (c >= 0x3040 && c <= 0x30ff) return 'jp'   // 平假名 / 片假名
  if (c >= 0x31f0 && c <= 0x31ff) return 'jp'   // 假名补充
  if (c >= 0xac00 && c <= 0xd7af) return 'kr'   // 谚文音节
  if (c >= 0x1100 && c <= 0x11ff) return 'kr'   // 谚文字母
  if (c >= 0x3130 && c <= 0x318f) return 'kr'   // 谚文兼容字母
  if (c >= 0x0600 && c <= 0x06ff) return 'ar'   // 阿拉伯
  if (c >= 0x0750 && c <= 0x077f) return 'ar'   // 阿拉伯补充
  if (c >= 0x0590 && c <= 0x05ff) return 'he'   // 希伯来
  if (c >= 0x0900 && c <= 0x097f) return 'deva' // 天城文
  return 'west'                                // 拉丁 / 希腊 / 西里尔 / IPA / 数字 / 标点
}

/** 混排文本 → 带 f-* 类的片段（每段一个族）。force = 本族专用（术语大字/本语自称/人名）。 */
function spans(text, force) {
  const s = String(text ?? '')
  if (!s) return ''
  let out = '', cur = null, buf = ''
  for (const ch of s) {
    const k = force ?? famOfChar(ch)
    if (cur !== null && k !== cur) { out += `<span class="${FAM_CLS[cur]}">${esc(buf)}</span>`; buf = '' }
    cur = k
    buf += ch
  }
  if (cur !== null) out += `<span class="${FAM_CLS[cur]}">${esc(buf)}</span>`
  return out
}

/** 语种 → 族键（loc.font 是 CSS 族类）。 */
const famOfLocale = (loc) => FAM_CLASS[loc.font] ?? 'west'

/** 音色显示名：zh-CN-XiaoxiaoNeural → Xiaoxiao Neural */
const voiceLabel = (voice) => voice.split('-').slice(2).join('-').replace('Neural', ' Neural')

// ── TTS 文本可覆盖性（实测，别凭记忆）────────────────────────────────
//
// edge-tts 的**中文**语音只对中文/拉丁/希腊发词边界；西里尔、阿语、天城、
// 希伯来整段被丢掉——实测「俄语叫 слон」只回「俄语」「叫」两个边界（漏 4 字），
// 「阿语 حصان」只回「阿语」（漏 4 字）。词边界少覆盖 → 工厂按字符位把边界映到
// token 上时刻意左漂 → 末尾 token 拿不到边界 → tokenTimings 返回 null →
// 卡拉OK 合片直接崩（ep05 白象 / ep07 白马 实测炸在 `fmt2(null)`）。
//
// 所以：**旁白是中文语音，不许出现这些文字**；那些词由 12 张词卡逐字展示，
// 中文旁白只用中文说法提到它们（「俄语和阿拉伯语里，它干脆直接叫大象」）。
const TTS_UNCOVERED = /[\u0400-\u04FF\u0600-\u06FF\u0750-\u077F\u0590-\u05FF\u0900-\u097F]/

for (const ep of DATA.episodes) {
  for (const s of ep.narration) {
    const m = s.match(TTS_UNCOVERED)
    if (m) {
      throw new Error(`${ep.id}（${ep.title_zh}）的旁白里有中文语音不覆盖的文字「${[...new Set(m)].join(' ')}」：\n  ${s}\n`
        + '  中文语音只对中文/拉丁/希腊发词边界；这些文字会让卡拉OK 的 token 时刻意漂移，\n'
        + '  末尾 token 拿不到边界，合片时炸在 `fmt2(null)`。改法：旁白改用中文说法，\n'
        + '  外文词留给 12 张词卡。')
    }
  }
}

// ── 场景 HTML ───────────────────────────────────────────────────────
const CSS = `
:root{
  --paper:#F6F1E6; --ink:#26221B; --line:#DCD0B8; --accent:#9A6F18; --red:#B23A2F;
  --mut:#8A7E6C; --sub:#6E6455; --soft:#EFE7D6;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#E4DCCB;width:1920px;height:1080px;overflow:hidden}
.scene{width:1920px;height:1080px;background:var(--paper);color:var(--ink);
  font-family:"OB Chess West","Noto Sans",sans-serif;display:none;flex-direction:column;
  padding:40px 72px 32px;position:relative}
.scene.on{display:flex}
.brand{font-size:20px;letter-spacing:.16em;color:var(--sub);font-weight:600;display:flex;gap:14px;align-items:baseline}
.brand b{color:var(--ink);letter-spacing:.22em}
.brand .gold{color:var(--accent);font-weight:700}
.brand .zh{font-family:"OB Chess SC","Noto Serif SC",serif;letter-spacing:.08em}
.pageno{position:absolute;top:40px;right:72px;font-size:20px;color:var(--mut);letter-spacing:.2em}
.headrule{border-bottom:2.5px solid var(--ink);margin-top:14px}
.body{flex:1;min-height:0;display:flex;gap:48px;align-items:stretch;padding-top:26px}
.left{flex:1 1 auto;min-width:0;display:flex;flex-direction:column}
.right{flex:0 0 560px;display:flex;align-items:center;justify-content:center}
/* 棋盘：给固定高、宽随比例走——SVG 有 viewBox，width:auto 才能保住正方形不被拉扁 */
.board{height:540px;width:auto;max-width:100%;display:block}
.langline{display:flex;align-items:baseline;gap:20px}
.langlabel{font-size:40px;font-weight:700;letter-spacing:.04em}
.langlabel small{font-size:21px;color:var(--mut);letter-spacing:.18em;margin-left:10px;font-weight:500}
.natv{font-size:28px;color:var(--mut)}
.wordbox{flex:1 1 auto;min-height:0;display:flex;align-items:center;padding:8px 0}
.word{white-space:nowrap;line-height:1.18;font-weight:600}
.script{line-height:1.62;font-size:34px;max-width:100%}
.tok{border-radius:.14em}
.word .tok.dim{opacity:.42}
.word .tok.sung{opacity:1}
.word .tok.cur{opacity:1;background:rgba(154,111,24,.18)}
.script .tok{color:var(--mut);transition:color .12s}
.script .tok.sung{color:var(--ink)}
.script .tok.cur{color:var(--red);font-weight:700;background:rgba(178,58,47,.08)}
.gloss{margin-top:10px;font-size:30px;color:var(--ink);font-weight:600}
.gloss em{font-style:normal;color:var(--accent)}
.note{margin-top:8px;font-size:25px;color:var(--sub);line-height:1.45}
.chips{margin-top:16px;display:flex;gap:12px;flex-wrap:wrap}
.chip{border:1.5px solid var(--line);border-radius:999px;padding:7px 18px;font-size:22px;color:var(--sub);background:var(--soft)}
.chip b{color:var(--accent);font-weight:700}
.badge{margin-top:18px;display:flex;align-items:center;gap:14px;font-size:25px}
.badge .pdot{width:15px;height:15px;border-radius:50%;background:var(--accent);flex:none}
.badge .pname{font-weight:700}
.badge .platin{color:var(--sub)}
.badge .pvoice{color:var(--mut);font-size:19px}
.footrule{border-bottom:1.5px solid var(--line);margin-top:16px}
.footer{margin-top:10px;display:flex;justify-content:space-between;font-size:17px;color:var(--mut);letter-spacing:.1em}
.f-sc{font-family:"OB Chess SC","Noto Serif SC",serif}
.f-jp{font-family:"OB Chess JP","Noto Sans JP",sans-serif}
.f-kr{font-family:"OB Chess KR","Noto Sans KR",sans-serif}
.f-ar{font-family:"OB Chess Arabic","Noto Sans Arabic",sans-serif}
.f-he{font-family:"OB Chess Hebrew","Noto Sans Hebrew",sans-serif}
.f-deva{font-family:"OB Chess Deva","Noto Sans Devanagari",sans-serif}
.f-west{font-family:"OB Chess West","Noto Sans",sans-serif}
html.vert,body.vert{width:1080px;height:1920px}
body.vert .scene{width:1080px;height:1920px;padding:44px 48px 34px}
body.vert .brand{font-size:19px;letter-spacing:.1em;flex-wrap:wrap;gap:8px}
body.vert .pageno{top:44px;right:48px;font-size:18px}
body.vert .body{flex-direction:column;gap:20px;padding-top:18px}
body.vert .right{flex:0 0 560px}
body.vert .board{height:540px}
body.vert .langlabel{font-size:40px}
body.vert .langlabel small{font-size:20px}
body.vert .natv{font-size:26px}
body.vert .script{font-size:33px;line-height:1.66}
body.vert .wordbox{padding:10px 0}
body.vert .gloss{font-size:28px}
body.vert .note{font-size:24px}
body.vert .chip{font-size:21px;padding:6px 16px}
body.vert .badge{font-size:23px;gap:12px}
body.vert .badge .pvoice{font-size:18px}
body.vert .footer{font-size:16px}
`

const SCRIPT_JS = `
const q = new URLSearchParams(location.search);
const lang = q.get("lang");
const state = parseInt(q.get("state") ?? "-1", 10);
const vert = q.get("fmt") === "v";
if (vert) { document.body.classList.add("vert"); document.documentElement.classList.add("vert"); }
for (const sc of document.querySelectorAll(".scene")) {
  if (sc.dataset.lang !== lang) continue;
  sc.classList.add("on");
  for (const box of sc.querySelectorAll(".fitbox")) {
    const el = box.querySelector(".word, .script");
    if (!el) continue;
    const maxH = box.clientHeight, maxW = box.clientWidth;
    const cap = Number(box.dataset.max || 420);
    let lo = 16, hi = cap;
    for (let i = 0; i < 34; i++) {
      const mid = (lo + hi) / 2;
      el.style.fontSize = mid + "px";
      if (el.offsetWidth <= maxW && el.offsetHeight <= maxH) lo = mid; else hi = mid;
    }
    el.style.fontSize = lo + "px";
  }
  const toks = sc.querySelectorAll(".tok");
  toks.forEach((t, i) => {
    t.classList.remove("dim", "sung", "cur");
    if (state < 0) t.classList.add("dim");
    else if (state >= toks.length) t.classList.add("sung");
    else if (i < state) t.classList.add("sung");
    else if (i === state) t.classList.add("cur");
    else t.classList.add("dim");
  });
}
`

function termTokens(locale, word) {
  if (locale === 'zh-CN') return [...word]
  return [word]
}

function cardScene(ep, type, loc, idx, total) {
  const t = type.terms[loc.locale]
  const word = stripMarks(t.word)
  const tokens = termTokens(loc.locale, word)
  const rtl = loc.dir === 'rtl'
  const fk = famOfLocale(loc)
  // token 之间**不留空格**：中文逐字 token（皇/后）拼起来要是一个词「皇后」，
  // 不是「皇 后」。时序不依赖这个空格——工厂按 token 序号驱动 ?state=N，
  // TTS 侧按字符区间切分边界（tokenTimings）。
  const script = tokens.map((tk) => `<span class="tok">${esc(tk)}</span>`).join('')
  return `<!-- ${loc.locale} -->
<section class="scene" id="sc-${ep.id}-${loc.locale}" data-lang="${loc.locale}" data-mode="term">
  <div class="brand"><b>${spans(DATA.series.name_en)}</b><span class="gold">· ${spans(DATA.series.tagline_en)} ·</span><span class="zh">${spans(DATA.series.name_zh)}</span></div>
  <div class="pageno">${spans(`${String(idx + 2).padStart(2, '0')} / ${total}`)}</div>
  <div class="headrule"></div>
  <div class="body">
    <div class="left">
      <div class="langline"><span class="langlabel">${spans(loc.name_zh)}<small>${spans(loc.name_en)}</small></span><span class="natv ${loc.font}"${rtl ? ' dir="rtl"' : ''}>${spans(loc.native, fk)}</span></div>
      <div class="fitbox wordbox" data-max="260"><div class="word ${loc.font}"${rtl ? ' dir="rtl"' : ''}>${script}</div></div>
      <div class="gloss">${spans(type.zh)}<em>${spans(` · ${type.en} · ${t.translit}`)}</em></div>
      <div class="note">${spans(t.note)}</div>
      <div class="chips"><span class="chip"><b>${spans(type.value_text)}</b></span><span class="chip">${spans(type.move)}</span><span class="chip">${spans(`起手 ${type.square.file}${type.square.rank}`)}</span></div>
    </div>
    <div class="right">${boardSVG(type, ep.color)}</div>
  </div>
  <div class="badge"><span class="pdot"></span><span class="pname ${loc.font}"${rtl ? ' dir="rtl"' : ''}>${spans(loc.persona, fk)}</span><span class="platin">${spans(loc.latin)}</span><span class="pvoice">${spans(`${loc.locale} · ${voiceLabel(loc.voice)}`)}</span></div>
  <div class="footrule"></div>
  <div class="footer"><span>${spans(DATA.series.thesis)}</span><span>${spans(`${ep.title_zh} · 配音 EDGE TTS NEURAL`)}</span></div>
</section>`
}

function narrationScene(ep, type) {
  const clauses = splitClauses(ep.narration)
  const html = clauses.map((c) => `<span class="tok">${spans(c)}</span>`).join('')
  return `<!-- narration -->
<section class="scene" id="sc-${ep.id}-nar" data-lang="nar" data-mode="script">
  <div class="brand"><b>${spans(DATA.series.name_en)}</b><span class="gold">· ${spans(DATA.series.tagline_en)} ·</span><span class="zh">${spans(DATA.series.name_zh)}</span></div>
  <div class="pageno">${spans(`01 / ${DATA.locales.length + 1}`)}</div>
  <div class="headrule"></div>
  <div class="body">
    <div class="left">
      <div class="langline"><span class="langlabel">${spans(ep.title_zh)}<small>${spans(ep.title_en)}</small></span><span class="natv f-sc">${spans(`${type.zh_full} · ${type.en}`)}</span></div>
      <div class="fitbox wordbox"><div class="script f-sc">${html}</div></div>
      <div class="chips"><span class="chip"><b>${spans(type.value_text)}</b></span><span class="chip">${spans(type.move)}</span><span class="chip">${spans(ep.tactic_zh)}</span></div>
    </div>
    <div class="right">${boardSVG(type, ep.color)}</div>
  </div>
  <div class="badge"><span class="pdot"></span><span class="pname f-sc">${spans(DATA.narration_voice.name_zh)}</span><span class="platin">${spans(DATA.narration_voice.latin)}</span><span class="pvoice">${spans(`zh-CN · ${voiceLabel(DATA.narration_voice.voice)}`)}</span></div>
  <div class="footrule"></div>
  <div class="footer"><span>${spans(DATA.series.thesis)}</span><span>${spans(`${ep.title_zh} · 配音 EDGE TTS NEURAL`)}</span></div>
</section>`
}

const COVER_VARIANTS = {
  pt: { w: 1080, h: 1920, cls: 'c-pt' },
  t34: { w: 1080, h: 1440, cls: 'c-34' },
  lc: { w: 1920, h: 1080, cls: 'c-lc' },
}

function coverHTML(ep, type, variant, fonts) {
  const V = COVER_VARIANTS[variant]
  const rows = DATA.locales.map((loc) => {
    const t = type.terms[loc.locale]
    const rtl = loc.dir === 'rtl'
    return `<div class="crow"><span class="cl ${loc.font}"${rtl ? ' dir="rtl"' : ''}>${esc(stripMarks(t.word))}</span><span class="cn f-sc">${spans(loc.name_zh)}</span></div>`
  }).join('\n    ')
  const board = boardSVG(type, ep.color)
  const head = `<div class="cbrand"><b>${spans(DATA.series.name_en)}</b> <span class="gold">· ${spans(DATA.series.tagline_en)}</span> · <span class="f-sc">${spans(DATA.series.name_zh)}</span> · ${spans(`${String(ep.no).padStart(2, '0')}/12`)}</div>`
  const title = `<div class="ctitle f-sc">${spans(ep.title_zh)}</div>
  <div class="cen f-west">${spans(`${ep.title_en} · ${type.en}`)}</div>
  <div class="cmove f-sc">${spans(type.move_detail)}</div>
  <div class="cval f-sc">${spans(`${type.value_text} · 同一个子，十二种语言十二个名字`)}</div>`
  const list = `<div class="clist">
    ${rows}
  </div>`
  const foot = `<div class="cfoot"><span class="f-sc">${spans(DATA.series.account_zh)}</span><span class="f-sc">${spans(DATA.series.collection_zh)}</span></div>`
  const body = variant === 'lc'
    ? `<div class="cmain"><div class="clft">${head}${title}${list}</div><div class="crgt">${board}</div></div>${foot}`
    : `${head}${title}<div class="cboard">${board}</div>${list}${foot}`
  return `<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>${esc(ep.title_zh)} · ${esc(DATA.series.name_zh)}</title>
<style>
${fonts}
:root{
  --paper:#F6F1E6; --ink:#26221B; --line:#DCD0B8; --accent:#9A6F18; --mut:#8A7E6C; --sub:#6E6455; --soft:#EFE7D6;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#E4DCCB}
.cover{background:var(--paper);color:var(--ink);font-family:"OB Chess West","Noto Sans",sans-serif;display:flex;flex-direction:column;overflow:hidden}
.cbrand{font-size:24px;letter-spacing:.16em;color:var(--sub);font-weight:600}
.cbrand b{color:var(--ink);letter-spacing:.2em}
.cbrand .gold{color:var(--accent)}
.ctitle{font-weight:700;line-height:1.04;letter-spacing:.04em}
.cen{letter-spacing:.24em;color:var(--accent);font-weight:600}
.cmove{color:var(--ink);font-weight:600;line-height:1.5}
.cval{color:var(--sub)}
.clist{display:grid;gap:8px 26px}
.crow{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--line);padding-bottom:4px}
.cl{font-size:32px;font-weight:600;flex:1 1 auto}
.cn{font-size:19px;color:var(--mut)}
.cfoot{margin-top:auto;padding-top:18px;display:flex;justify-content:space-between;font-size:22px;color:var(--mut);letter-spacing:.08em}
.board{max-width:100%;height:auto;width:auto;display:block}
.f-sc{font-family:"OB Chess SC","Noto Serif SC",serif}
.f-jp{font-family:"OB Chess JP","Noto Sans JP",sans-serif}
.f-kr{font-family:"OB Chess KR","Noto Sans KR",sans-serif}
.f-ar{font-family:"OB Chess Arabic","Noto Sans Arabic",sans-serif}
.f-he{font-family:"OB Chess Hebrew","Noto Sans Hebrew",sans-serif}
.f-deva{font-family:"OB Chess Deva","Noto Sans Devanagari",sans-serif}
.f-west{font-family:"OB Chess West","Noto Sans",sans-serif}

/* 竖版 1080×1920 */
.c-pt{width:1080px;height:1920px;padding:76px 62px 56px}
.c-pt .cbrand{font-size:25px}
.c-pt .ctitle{font-size:168px;margin-top:40px}
.c-pt .cen{font-size:40px;margin-top:10px}
.c-pt .cmove{font-size:34px;margin-top:30px}
.c-pt .cval{font-size:27px;margin-top:12px}
.c-pt .cboard{margin-top:34px;display:flex;justify-content:center}
.c-pt .board{height:560px;width:auto}
.c-pt .clist{margin-top:40px;grid-template-columns:1fr 1fr}
.c-pt .cl{font-size:34px}
.c-pt .cn{font-size:20px}

/* 3:4 1080×1440 */
.c-34{width:1080px;height:1440px;padding:60px 56px 44px}
.c-34 .cbrand{font-size:22px}
.c-34 .ctitle{font-size:138px;margin-top:28px}
.c-34 .cen{font-size:34px;margin-top:8px}
.c-34 .cmove{font-size:29px;margin-top:22px}
.c-34 .cval{font-size:24px;margin-top:10px}
.c-34 .cboard{margin-top:24px;display:flex;justify-content:center}
.c-34 .board{height:430px;width:auto}
.c-34 .clist{margin-top:28px;grid-template-columns:1fr 1fr 1fr;gap:6px 20px}
.c-34 .cl{font-size:28px}
.c-34 .cn{font-size:17px}
.c-34 .crow{padding-bottom:3px}

/* 横版 1920×1080 */
.c-lc{width:1920px;height:1080px;padding:56px 70px 44px}
.cmain{flex:1 1 auto;display:flex;gap:56px;align-items:center;min-height:0}
.clft{flex:1 1 auto;min-width:0;display:flex;flex-direction:column}
.crgt{flex:0 0 700px;display:flex;align-items:center;justify-content:center}
.c-lc .board{height:700px;width:auto}
.c-lc .cbrand{font-size:24px}
.c-lc .ctitle{font-size:150px;margin-top:30px}
.c-lc .cen{font-size:38px;margin-top:8px}
.c-lc .cmove{font-size:33px;margin-top:26px;max-width:1000px}
.c-lc .cval{font-size:26px;margin-top:10px}
.c-lc .clist{margin-top:28px;grid-template-columns:1fr 1fr}
.c-lc .cl{font-size:32px}
.c-lc .cn{font-size:19px}
</style></head>
<body>
<div class="cover ${V.cls}">
  ${body}
</div>
</body></html>`
}

// ── 字符清单 → fonts.json（从生成的 HTML 反推）────────────────────────
//
// 族归属按**渲染元素的 class**走（audit-charset 的栈式口径）：一个字符必须
// 落在真正渲染它的那一族的 subset 里。族键：sc=Noto Serif SC，west=Noto Sans，
// jp/kr/ar/he/deva 各自语种族。
//
// 本实现与 audit_charset 用**同一套栈式算法**从生成好的 HTML 反推「每族实际
// 渲染了哪些字符」——所以「哪个族渲染哪个字」在 HTML 与子集清单之间不会失步：
// 改稿后忘了重抓字体，audit-charset 会立刻报缺字；反过来，这里也永远不会
// 多要一个用不到的字符（子集越精确，fonts.css 越小）。
const VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr',
])

/** 从 HTML 列表反推每族的字符集（栈式归属，镜像 audit_charset.check）。 */
function deriveCharSets(htmls) {
  const use = Object.fromEntries(FAMS.map((f) => [f.key, new Set()]))
  for (const html of htmls) {
    const i = html.indexOf('<body>')
    let body = i >= 0 ? html.slice(i + '<body>'.length) : html
    body = body.replace(/<!--[\s\S]*?-->/g, '')
    body = body.replace(/<script>[\s\S]*?<\/script>/g, '')
    body = body.replace(/<style>[\s\S]*?<\/style>/g, '')
    const stack = []
    for (const m of body.matchAll(/<(\/?)(\w+)([^>]*)>|([^<]+)/g)) {
      if (m[1]) { if (stack.length) stack.pop(); continue }
      const name = m[2]
      if (name !== undefined) {
        const attrs = m[3] ?? ''
        if (VOID_TAGS.has(name.toLowerCase()) || attrs.trimEnd().endsWith('/')) continue
        let key = stack.length > 0 ? stack[stack.length - 1] : null
        const cm = attrs.match(/class="([^"]*)"/)
        if (cm) {
          for (const c of cm[1].split(/\s+/)) {
            if (c in FAM_CLASS) { key = FAM_CLASS[c]; break }
          }
        }
        stack.push(key)
      } else {
        const text = m[4] ?? ''
        if (text.includes('function') || text.includes('const ') || text.includes('document.')) continue
        const top = stack.length > 0 ? stack[stack.length - 1] : null
        if (top !== null && use[top]) {
          for (const ch of text) if (!/\s/u.test(ch)) use[top].add(ch)
        }
      }
    }
  }
  return use
}

/** 字符集 → fonts.json 条目（text 按码位排序，fetch-fonts 会再去重排序）。 */
function fontSpecFrom(use) {
  return FAMS.filter((f) => use[f.key].size > 0).map((f) => ({
    family: f.family,
    google: f.google,
    text: [...use[f.key]].sort((a, b) => a.codePointAt(0) - b.codePointAt(0)).join(''),
    classes: [f.cls],
  }))
}

// ── 写盘 ────────────────────────────────────────────────────────────
function episodeDir(ep) { return join(ROOT, 'episodes', ep.id) }

const FONTS_SLOT = '/*@@FONTS@@*/'

/** 造出 12 支的全部 HTML（场景页 + 3 张封面源）；字体先留占位。 */
function buildAll(fonts) {
  const built = []
  for (const ep of DATA.episodes) {
    const type = DATA.types.find((t) => t.key === ep.type)
    const scenes = [narrationScene(ep, type)]
    DATA.locales.forEach((loc, i) => scenes.push(cardScene(ep, type, loc, i, DATA.locales.length + 1)))
    const html = `<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>${esc(ep.title_zh)} · ${esc(DATA.series.name_zh)}</title>
<style>
${fonts}
${CSS}
</style></head>
<body>
${scenes.join('\n')}
<script>
${SCRIPT_JS}
</script>
</body></html>`
    const covers = {}
    for (const v of Object.keys(COVER_VARIANTS)) covers[v] = coverHTML(ep, type, v, fonts)
    built.push({ ep, type, html, covers })
  }
  return built
}

if (MODE === 'fonts' || MODE === 'episodes') {
  // ① 骨架（无字体）→ 反推「每族渲染了哪些字」→ fonts.json
  const built = buildAll(FONTS_SLOT)
  const use = deriveCharSets(built.flatMap((b) => [b.html, ...Object.values(b.covers)]))
  const spec = fontSpecFrom(use)
  writeFileSync(join(ROOT, 'fonts.json'), JSON.stringify(spec, null, 1), 'utf8')
  for (const f of spec) console.log(`  ${f.family}: ${new Set(f.text).size} chars`)
  if (MODE === 'fonts') process.exit(0)

  // ② 嵌上真实 fonts.css 写盘
  const fontsPath = join(ROOT, 'fonts.css')
  if (!existsSync(fontsPath)) {
    console.error('!! fonts.css 不存在——先跑：poster fetch-fonts fonts.json')
    process.exit(1)
  }
  const fonts = readFileSync(fontsPath, 'utf8')
  for (const b of built) {
    const { ep, type } = b
    const dir = episodeDir(ep)
    mkdirSync(dir, { recursive: true })

    // 1) 场景 HTML
    writeFileSync(join(dir, 'video_src.html'), b.html.replace(FONTS_SLOT, () => fonts), 'utf8')

    // 2) 配音清单（narration + 12 语种）
    const clauses = splitClauses(ep.narration)
    const narTokens = clauses.map((c, i) => (stripTrail(c) + (i < clauses.length - 1 ? ' ' : '')))
    const langs = [{
      locale: 'nar',
      persona: '旁白',
      latin: 'Yunyang',
      gender: 'm',
      voice: DATA.narration_voice.voice,
      text: narTokens.join(''),
      tokens: narTokens,
    }]
    for (const loc of DATA.locales) {
      const t = type.terms[loc.locale]
      const word = stripMarks(t.word)
      const tokens = termTokens(loc.locale, word)
      langs.push({
        locale: loc.locale,
        persona: loc.persona,
        latin: loc.latin,
        gender: loc.gender,
        voice: loc.voice,
        text: tokens.join(''),
        tokens,
      })
    }
    writeFileSync(join(dir, 'voices.json'), JSON.stringify({ tts_dir: 'tts', langs }, null, 1), 'utf8')

    // 3) 成片配置
    const cfg = {
      src: 'video_src.html',
      fonts_css: '../../fonts.css',
      tts_dir: 'tts',
      locales: ['nar', ...DATA.locales.map((l) => l.locale)],
      preroll: 0.8, tail: 0.8, done: 0.5, intro: 2.2, outro: 2.8,
      intro_image: 'cover_pt.png',
      desk: '0xe4dccb',
      formats: [
        { name: 'portrait', w: 1080, h: 1920, frames: 'frames_v', output: `out/${ep.id}_portrait.mp4`, fmt: 'v', poster_filter: 'scale=1080:1920', intro_image: 'cover_pt.png' },
        { name: 'landscape', w: 1920, h: 1080, frames: 'frames', output: `out/${ep.id}_landscape.mp4`, fmt: null, poster_filter: 'scale=1920:1080', intro_image: 'cover_lc.png' },
      ],
    }
    writeFileSync(join(dir, 'video.json'), JSON.stringify(cfg, null, 1), 'utf8')

    // 4) 封面源（三种版式：竖版 9:16 / 3:4 / 横版 16:9）
    for (const v of Object.keys(COVER_VARIANTS)) {
      writeFileSync(join(dir, `cover_${v}_src.html`), b.covers[v].replace(FONTS_SLOT, () => fonts), 'utf8')
    }
    console.log(`${ep.id}  ${ep.title_zh}  ${ep.no}/12`)
  }
  process.exit(0)
}

console.error('usage: node tools/gen-episodes.mjs [fonts|episodes]')
process.exit(2)
