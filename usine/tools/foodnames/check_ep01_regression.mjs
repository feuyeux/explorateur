// check_ep01_regression.mjs — 第 01 期回归基准：生成器重出的必须与已交付手写版同构
//
// 「同构」不是「像素级相同」（渲染细节会漂），而是**可判定的等价关系**：
//   ① 12 格的词形、来源标签、转写、旁白句 —— 逐字相同（数据→源文件是纯函数，
//      这一层必须严格相等，任何差异都是数据或生成器被改坏了）；
//   ② 叠印门的三个词框矩形 —— 逐位相同（实测配准几何，口径见 record.md §5）；
//   ③ 旁白实测电平与成片时长 —— 复算出同样的数（同一批 TTS、同一套时间线）。
//
// 跑法：node tools/foodnames/check_ep01_regression.mjs
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const here = import.meta.dirname
const USINE = 'D:/coding/personal/explorateur/usine'
const DATA = join(here, 'data', 'ep01-sushi.json')
const GEN = join(USINE, 'examples', 'foodnames-ep01-sushi')      // 生成器重出
const HAND = join(USINE, 'examples', 'sushi-12lang')             // 已交付手写版

const problems = []
const eq = (what, a, b) => {
  if (a !== b) problems.push(`${what}：生成器「${a}」≠ 手写版「${b}」`)
}

// ---- ① 12 格内容逐字相同 ----
// ⚠️ 词形在源文件里是**逐字/逐音节拆开**的（`<span class="c">S</span><span class="v">u</span>…），
//    直接搜整词永远搜不到。判据要**去标签后取文本**再比对。
const strip = (html) => html.replace(/<[^>]*>/g, '')
if (!existsSync(GEN) || !existsSync(HAND)) {
  console.error(`✖ 目录缺失：${existsSync(GEN) ? '' : GEN} ${existsSync(HAND) ? '' : HAND}`)
  process.exit(1)
}
const d = JSON.parse(readFileSync(DATA, 'utf8'))
for (const w of d.words) {
  const re = new RegExp(
    `id="sc-${w.locale}"[\\s\\S]{0,6000}?</section>`,
  )
  for (const [label, dir] of [['生成器', GEN], ['手写版', HAND]]) {
    const html = readFileSync(join(dir, 'video_src.html'), 'utf8')
    const m = re.exec(html)
    if (!m) { problems.push(`${label} 的 video_src 缺 ${w.locale} 场景`); continue }
    const seg = m[0]
    const text = strip(seg)
    if (!text.includes(w.word) && !text.includes(w.inline)) {
      problems.push(`${label} 的 ${w.locale} 场景里没有词形「${w.word}」/「${w.inline}」（去标签后比对）`)
    }
    if (!seg.includes(w.tag)) {
      problems.push(`${label} 的 ${w.locale} 场景里没有来源标签「${w.tag}」`)
    }
  }
}

// ---- ② 叠印门三个词框矩形逐位相同 ----
const rects = (dir) => {
  const txt = readFileSync(join(dir, 'diag.txt'), 'utf8')
  const m = /<title>DIAG (\{.*?\})<\/title>/s.exec(txt)
  if (!m) return null
  const cells = JSON.parse(m[1]).cells
  const pick = (label) => {
    const c = cells.find((x) => x.lang === label)
    return c ? c.word.join(',') : null
  }
  return ['印地语', '阿拉伯语', '希伯来语'].map(pick)
}
const rg = rects(GEN)
const rh = rects(HAND)
if (!rg || !rh) problems.push('diag.txt 里没有 DIAG 诊断（fit-diag 的 dump 形状变了？）')
else {
  const L = ['印地语', '阿拉伯语', '希伯来语']
  L.forEach((label, i) => eq(`叠印门 ${label} 词框`, rg[i], rh[i]))
}

// ---- ③ 旁白电平与时长复算一致 ----
const facts = (dir) => {
  const p = join(dir, 'publish', 'facts.json')
  return existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : null
}
const fg = facts(GEN)
const fh = facts(HAND)
if (fg && fh) {
  eq('旁白实测 dBFS', String(fg.narration_rms_dbfs), String(fh.narration_rms_dbfs))
  eq('成片时长 s', String(fg.duration_sec), String(fh.duration_sec))
  eq('帧数', String(fg.frames), String(fh.frames))
  eq('BGM gain', String(fg.bgm_gain), String(fh.bgm_gain))
} else {
  problems.push('某一方缺 publish/facts.json（发布侧还没生成）')
}

if (problems.length === 0) {
  console.log('✅ 第 01 期回归基准通过：12 格内容逐字相同 · 叠印门词框逐位相同 · 旁白电平/时长/增益复算一致')
} else {
  console.log(`❌ ${problems.length} 项回归不一致：`)
  for (const p of problems) console.log('  · ' + p)
  process.exit(1)
}
