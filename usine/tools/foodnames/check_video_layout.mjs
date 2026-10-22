// check_video_layout.mjs — **视频版式判据门**（「各国美食名称」系列）
//
// 为什么有这道门：这一系列的**海报**把「词」做成了主角（巨型字 + 红蓝逐字着色 +
// 注音），而**视频**把词埋进了旁白句里——`.stage` 里装的是 tokens 拼成的整句，
// 词只是句首的第一个 token。于是：
//   ① 观众在成片里看不到「这道菜的名字」本身（一个美食名称系列的视频没有名字）；
//   ② 未唱到的 token 不透明度 0.18，画面大半是隐形的；
//   ③ 当前词的高亮是中性灰，跟整片红/蓝/金的品牌色系不搭；
//   ④ 竖屏画面上下两段各空掉近 1/4，像没做完的稿子。
// 这些是**肉眼可见**的缺陷，但 `pnpm verify` 管不到 `tools/`（成片模板不在
// packages 里），于是这一层没有闸——本文件就是那道闸。
//
// 判据的依据（不许比被改进对象自己的文件更严）：
//   · 「词必须是主角」——**海报就是仓内的参照实现**（`templates/poster_style.css`
//     同一套红/蓝/金、同一套逐字着色）；视频侧的现状是 `templates/video_style.css`。
//   · 「留白有上限」——海报是 4×3 满版网格，整版没有空白带；视频帧是单栏，
//     留白超过画面高 15% 就变成「空场」。
//   · 「未唱到的词要看得见」——0.18 不透明度下正文对比度约 1.2:1，低于任何
//     平台字幕的底线。
//   · 「高亮必须是品牌色」——页脚图例只承诺三色（元音红/辅音蓝/声调灰金），
//     画面里出现第四种灰不属于任何一套。
//
// 本门只读：**不改产物、不重渲染**。DOM 探针渲染的是一份**副本**
// （`_vl_probe_*.html`，留在期目录里便于复查），像素读的是已渲染的帧。
//
// Usage: node --import tsx tools/foodnames/check_video_layout.mjs --out <期目录>
//        [--formats portrait,landscape] [--report <json 路径>]
// 退出码：0 全部达标；1 有判据不达标（逐条列出，不达标项给实测值与阈值）。
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { platform } from '../../packages/core/src/index.ts'
import { rgbRaw } from '../../packages/poster/src/pixels.ts'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const OUT = resolve(arg('out'))
const REPORT = arg('report') ? resolve(arg('report')) : join(OUT, 'video_layout.json')
const WANT = String(arg('formats', 'portrait,landscape')).split(',').map((s) => s.trim()).filter(Boolean)

// ── 阈值（设计判据，不是「跑出来什么样就定成什么样」）──────────────────────────
//
// **阈值与品牌色的唯一事实源是 `layout_rules.mjs`**——场景页面那道门
// （`check_scene_tokens.mjs`）量的是同一组要求，两道门必须用同一份数字与同一套
// 三色，否则「成片过了、手搭页面却没过」会变成一句没人查得出的口话。
import { BRAND, TH } from './layout_rules.mjs'

const FORMATS = {
  portrait: { key: 'portrait', fmt: 'v', w: 1080, h: 1920, dir: 'frames_v' },
  landscape: { key: 'landscape', fmt: null, w: 1920, h: 1080, dir: 'frames' },
}

// ═══════════════════════════════════════════════════════════ 探针（页内量几何）
//
// 探针跑在**只留目标语种那一格**的副本上（其余 11 格 display:none，删掉不影响布局）。
// 它量的全是**渲染后**的事实：盒子的实际大小、实际不透明度、实际高亮色。
const PROBE = `
<script>
(async () => {
  const BRAND_PAGE = ${JSON.stringify(BRAND)}
  const q = new URLSearchParams(location.search)
  const lang = q.get('lang')
  const forms = [q.get('vlword') || '', q.get('vlinline') || ''].filter(Boolean)
  // 句子比对要**同时去空白和标点**：卡拉OK的 token 合法地丢掉标点
  // （俄语「Суши, японское блюдо」的词边界是「Суши」，仓库 README 已记），
  // 所以带标点的句子本来就不该逐字相等——判据要比的是**词序与词形**。
  // 但首词被替换成词形那种错（冠词被吃、词重复）仍然会被抓住：词序不同。
  const strip = (s) => (s || '').replace(/[\\s\\p{P}]/gu, '')
  const sent = strip(q.get('vlsent') || '')
  const out = { lang, hero: null, hero_found: false, sentence_found: false,
               tokens: [], annot: [], frame: null, others_opacity: null, highlight: null }
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const isAnnot = (el) => el.classList && el.classList.contains('annot')
  function wordText(el) {
    const c = el.cloneNode(true)
    // 去两样「不是句子本身」的东西：
    //   .annot       —— 注音层（ㄕㄡ…），它挂在字下面，不属于词形
    //   .stack > .top —— 叠印的上层（辅音蓝/母音透明），**下层 .lay 才是词形**；
    //     不去掉的话 ar/he/deva 三个语种的文本会是「词形 ×2」，句子比对必然对不上。
    c.querySelectorAll('.annot').forEach((n) => n.remove())
    c.querySelectorAll('.stack > .top').forEach((n) => n.remove())
    return norm(c.textContent)
  }
  function box(el) {
    const r = el.getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height }
  }
  function leafInk(root) {
    // 元素内部**字形墨迹**的并集框（去掉注音层）
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, n = 0
    root.querySelectorAll('*').forEach((el) => {
      if (el.children.length) return
      if (isAnnot(el)) return
      if (el.closest('.annot')) return
      if (!norm(el.textContent)) return
      const r = el.getBoundingClientRect()
      if (r.width <= 0 || r.height <= 0) return
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top)
      x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom)
      n++
    })
    if (!n) return null
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
  }
  function isBrand(css) {
    if (!css) return false
    const nums = css.match(/[\\d.]+/g)
    if (!nums) return false
    const hex = nums.slice(0, 3).map((v) => Math.round(Number(v)).toString(16).padStart(2, '0')).join('')
    // ⚠️ 品牌色表要**在页内**再声明一份：探针跑在浏览器里，Node 侧的常量
    //    在那儿不存在——引用它会抛 ReferenceError，而异常被 catch 吃掉后
    //    表现是「暗词/高亮全测不出来」，看起来像画面没问题。
    return BRAND_PAGE.indexOf(hex) >= 0
  }
  // 祖先链上第一个非透明底色（高亮常挂在 token 父元素上，叶子自己透明）。
  // ⚠️ **到 .scene 为止（不含 .scene）**：.scene 自己有纸色底，若把它算进来，
  //    每一个字都会被判成「被高亮」——暗词不透明度就永远量不出来。
  function effBg(el, scene) {
    for (let n = el; n && n !== scene; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg
    }
    return 'rgba(0, 0, 0, 0)'
  }
  function effShadow(el, scene) {
    for (let n = el; n && n !== scene; n = n.parentElement) {
      const s = getComputedStyle(n).boxShadow + ' ' + getComputedStyle(n).textShadow
      if (s && s !== 'none') return s
    }
    return 'none'
  }
  // ⚠️ **不能光 await document.fonts.ready**：headless 的 --virtual-time-budget 下
  // 这个 promise 可能一直不落定（虚拟时间不等字体解码），于是标题永不落地，
  // 探针交白卷——「没输出」和「页面结构变了」长得一模一样，难辨。用竞速兜底。
  try {
    if (document.fonts && document.fonts.ready) {
      await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 2500))])
    }
  } catch (e) {}
  try {
    measure()
  } catch (e) {
    out.error = String(e)
  }
  document.title = 'VL ' + JSON.stringify(out)

  function measure() {
  const scene = document.querySelector('.scene[data-lang="' + lang + '"]')
  if (!scene) { out.error = 'scene not found'; return }
  out.frame = { w: window.innerWidth, h: window.innerHeight }

  // —— 主角：词形自身成元素（不再是句首 token）
  const cands = []
  scene.querySelectorAll('*').forEach((el) => {
    const t = wordText(el)
    if (t && forms.indexOf(t) >= 0) cands.push(el)
  })
  if (cands.length) {
    let best = null
    for (const el of cands) {
      const fs = parseFloat(getComputedStyle(el).fontSize) || 0
      const ink = leafInk(el)
      const a = ink ? ink.w * ink.h : 0
      if (!best || fs > best.fs || (fs === best.fs && a > best.area)) {
        best = { el, fs, area: a, ink }
      }
    }
    const ink = best.ink || box(best.el)
    out.hero = { font_size: best.fs, x: ink.x, y: ink.y, w: ink.w, h: ink.h }
    out.hero_found = true
  }

  // —— 旁白句：必须与配音念的那句**逐词一致**（去空白去标点后）
  if (sent) {
    scene.querySelectorAll('*').forEach((el) => {
      if (strip(wordText(el)) === sent) { out.sentence_found = true }
    })
  }

  // —— token 状态：不透明度 + 高亮色
  const CHROME = '.brand,.pageno,.langline,.badge,.translit,.footer,.footrule,.headrule'
  const atoms = []
  const dbg = { all: 0, not_leaf: 0, chrome: 0, annot: 0, no_text: 0, zero_box: 0 }
  scene.querySelectorAll('*').forEach((el) => {
    dbg.all++
    if (el.children.length) { dbg.not_leaf++; return }
    if (el.closest(CHROME)) { dbg.chrome++; return }
    if (el.closest('.annot')) { dbg.annot++; return }
    if (!norm(el.textContent)) { dbg.no_text++; return }
    const r = el.getBoundingClientRect()
    if (r.width <= 0 || r.height <= 0) { dbg.zero_box++; return }
    const st = getComputedStyle(el)
    atoms.push({ el, text: norm(el.textContent), opacity: parseFloat(st.opacity), bg: effBg(el, scene), shadow: effShadow(el, scene) })
  })
  out.dbg = dbg
  const hl = atoms.filter((a) => (a.bg && a.bg !== 'rgba(0, 0, 0, 0)') || isBrand(a.shadow))
  out.tokens = atoms.map((a) => ({ text: a.text, opacity: a.opacity, bg: a.bg, hl: hl.includes(a) }))
  if (hl.length) out.highlight = { bg: hl[0].bg, brand: isBrand(hl[0].bg) || isBrand(hl[0].shadow) }
  const others = atoms.filter((a) => !hl.includes(a))
  out.others_opacity = others.length ? Math.min(...others.map((a) => a.opacity)) : null

  // —— 注音列：字心 vs 注音心
  scene.querySelectorAll('.annot').forEach((an) => {
    const col = an.parentElement
    if (!col) return
    const chars = [...col.children].filter((c) => c !== an && !isAnnot(c))
    if (!chars.length) return
    const cr = chars[0].getBoundingClientRect()
    const ar = an.getBoundingClientRect()
    out.annot.push({ dx: Math.abs((cr.left + cr.right) / 2 - (ar.left + ar.right) / 2) })
  })
  }
})()
</script>
`

// ═══════════════════════════════════════════════════════════ 工具
function chromePath() {
  const p = platform.browserPath()
  if (!p) {
    console.error('✖ 找不到 Chromium 系浏览器（设 CHROME_BIN / FEUILLE_BROWSER）')
    process.exit(1)
  }
  return p
}

/** 从 video.html 里切出「只留目标语种那一格」的探针副本。 */
function probeHtml(html, lang) {
  const parts = html.split(/(?=<section class="scene")/)
  const head = parts[0]
  const target = parts.find((p) => p.startsWith('<section class="scene"') && p.includes(`data-lang="${lang}"`))
  if (!target) return null
  const end = target.indexOf('</section>')
  if (end < 0) return null
  const section = target.slice(0, end + '</section>'.length)
  const tail = html.slice(html.lastIndexOf('</section>') + '</section>'.length)
  if (!tail.includes('<script>')) return null
  return head + section + tail.replace('<script>', PROBE + '<script>')
}

/** 跑一次探针：返回页内报的 JSON。 */
function probe(outDir, lang, forms, sentence, fmt, w, h) {
  const src = join(outDir, 'video.html')
  if (!existsSync(src)) return null
  const html = readFileSync(src, 'utf8')
  const ph = probeHtml(html, lang)
  if (!ph) return null
  const probePath = join(outDir, `_vl_probe_${fmt || 'l'}.html`)
  writeFileSync(probePath, ph, 'utf8')
  const q = new URLSearchParams({ lang, state: '0', vlword: forms[0] ?? '', vlsent: sentence })
  if (forms[1]) q.set('vlinline', forms[1])
  if (fmt) q.set('fmt', fmt)
  const url = 'file:///' + probePath.replace(/\\/g, '/') + '?' + q.toString()
  const r = spawnChrome([
    '--headless=new', '--disable-gpu', '--no-sandbox', '--virtual-time-budget=12000',
    `--window-size=${w},${h}`, '--force-device-scale-factor=1', '--hide-scrollbars', '--dump-dom', url,
  ])
  const m = /<title>VL ([\s\S]*?)<\/title>/.exec(r.stdout ?? '')
  if (!m) {
    if (process.argv.includes('--debug')) {
      console.error(`  [debug ${lang}] chrome 退出码 ${r.status}，stdout ${(r.stdout ?? '').length} 字节`)
      console.error(`  [debug ${lang}] stdout 头：${(r.stdout ?? '').slice(0, 300)}`)
      console.error(`  [debug ${lang}] stderr 头：${(r.stderr ?? '').slice(-600)}`)
    }
    return null
  }
  try { return JSON.parse(m[1]) } catch (e) {
    if (process.argv.includes('--debug')) console.error(`  [debug ${lang}] JSON 解析失败：${e.message}\n${m[1].slice(0, 400)}`)
    return null
  }
}

let CHROME = null
function spawnChrome(args) {
  if (!CHROME) CHROME = chromePath()
  return spawnSync(CHROME, args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
}

// ═══════════════════════════════════════════════════════════ 像素层
/**
 * 墨迹覆盖率 + 最大空白水平带。
 * 背景色取「出现最多的颜色」（画面绝大部分是纸色），墨迹 = 与背景色距离 > 阈值。
 *
 * ⚠️ **行必须逐行扫，不能隔行抽样。**
 * 2026-10-21 实测踩到的坑：原先按 `y += 2` 抽样（注释写「2 倍抽样最多差 1 行误差」——
 * **这句话是错的**）。画面里的页脚分隔线只有 1.5px，落在**奇数行**时整条会被抽样漏掉，
 * 于是「细线下面 ~149px + 细线上面 ~146px」两段空隙被并成一段 297px（15.5%），
 * 判它「空掉一大块」——而那一帧的排版其实完全正常（同一帧逐行扫只有 9.7%）。
 * 误差不是 1 行，是**整条细线 + 它两侧的空气**，量级 ~150px。
 *
 * 而且这个假阳性还会**随细线落在奇数行还是偶数行而翻转**：同一份版式，量出 297px 或 150px
 * 都有可能——一把会自己变答案的尺子不能用来判对错。逐行扫没有这个问题，代价只是
 * 多扫一倍的行（实测每帧多 ~0.3s）。
 */
async function pixelMetrics(pngPath) {
  if (!existsSync(pngPath)) return null
  const { data, width: W, height: H } = await rgbRaw(pngPath)
  // 背景色：四角 + 中心取样，取众数
  const counts = new Map()
  const at = (x, y) => {
    const o = (y * W + x) * 3
    return [data[o], data[o + 1], data[o + 2]]
  }
  for (let y = 4; y < H; y += 97) for (let x = 4; x < W; x += 97) {
    const p = at(x, y)
    const k = (p[0] >> 3) + ',' + (p[1] >> 3) + ',' + (p[2] >> 3)
    counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  let bg = [247, 242, 230]
  let best = -1
  for (const [k, c] of counts) {
    if (c > best) {
      best = c
      const [r, g, b] = k.split(',').map((v) => Number(v) << 3)
      bg = [r, g, b]
    }
  }
  const rowInk = new Uint8Array(H)
  let inkPx = 0
  for (let y = 0; y < H; y++) {
    let row = 0
    for (let x = 0; x < W; x += 2) {
      const p = at(x, y)
      const d = Math.abs(p[0] - bg[0]) + Math.abs(p[1] - bg[1]) + Math.abs(p[2] - bg[2])
      if (d > 60) row++
    }
    if (row > 0) { rowInk[y] = 1; inkPx += row }
  }
  let band = 0
  let cur = 0
  for (let y = 0; y < H; y++) {
    if (rowInk[y]) { cur = 0 } else { cur++; if (cur > band) band = cur }
  }
  return {
    ink_ratio: inkPx / (H * Math.ceil(W / 2)),
    max_empty_band: band / H,
    bg: bg.map((v) => v.toString(16).padStart(2, '0')).join(''),
    rows_sampled: H,
  }
}

// ═══════════════════════════════════════════════════════════ 判据
const failures = []
function check(locale, name, ok, actual, need, note) {
  if (!ok) failures.push({ locale, name, actual, need, note })
  return ok
}

// ═══════════════════════════════════════════════════════════ 主流程
const epPath = join(OUT, 'episode.json')
if (!existsSync(epPath)) {
  console.error(`✖ ${epPath} 不存在——这不是一期 foodnames 的产物目录`)
  process.exit(1)
}
const ep = JSON.parse(readFileSync(epPath, 'utf8'))
const words = ep.words.map((w) => ({
  locale: w.locale,
  word: w.word,
  inline: w.inline ?? w.word,
  sentence: w.sentence,
}))

console.log(`\n═══ 视频版式判据 · ${ep.slug ?? OUT} ═══`)

const report = { episode: ep.episode ?? null, slug: ep.slug ?? null, thresholds: TH, formats: {} }

for (const key of WANT) {
  const F = FORMATS[key]
  if (!F) { console.error(`✖ 未知画幅 ${key}`); process.exit(1) }
  console.log(`\n▶ ${key}（${F.w}×${F.h}）`)
  const perLocale = []
  for (const w of words) {
    const dom = probe(OUT, w.locale, [w.word, w.inline], w.sentence, F.fmt, F.w, F.h)
    if (!dom) {
      console.error(`✖ ${w.locale}：探针没拿到几何（video.html 结构变了？）`)
      failures.push({ locale: w.locale, name: 'probe', actual: null, need: 'DOM 几何', note: '探针无输出' })
      continue
    }
    const fh = dom.frame?.h ?? F.h
    const fw = dom.frame?.w ?? F.w
    const hero = dom.hero
    const heroH = hero ? hero.h / fh : 0
    const heroW = hero ? hero.w / fw : 0
    check(w.locale, 'hero_found', !!dom.hero_found, hero ? '有' : '无', '词形独立成元素',
      '词形必须是自己一个元素（现在它只是旁白句里的第一个 token）')
    check(w.locale, 'hero_prominence', heroH >= TH.hero_height_ratio || heroW >= TH.hero_width_ratio,
      `h=${(heroH * 100).toFixed(1)}% w=${(heroW * 100).toFixed(1)}%`,
      `h≥${TH.hero_height_ratio * 100}% 或 w≥${TH.hero_width_ratio * 100}%`,
      '主角词在画面里要占得住位置（海报就是参照实现）')
    check(w.locale, 'sentence_matches_voice', !!dom.sentence_found, dom.sentence_found ? '一致' : '不一致',
      '画面句子 == 数据里的旁白句',
      '配音念的就是这句：画面句子必须与它逐字相同（2026-10-21 实测：首词被无条件替换成词形，' +
      '冠词/助词被吃掉、词重复一遍，卡拉OK高亮整体错开一词＝音画不同步）')
    // **量不到 ≠ 达标**（与 `check_scene_tokens.mjs` 同一条纪律）：`others_opacity`
    // 为 null 说明「没唱到的词」一个都没量到——它们没渲染（零尺寸 / 隐藏），或者
    // 画面上根本没有非当前 token。两种都是「暗词看不见」，比「不透明度低于阈值」
    // 更严重。原来这一行写的是 `dom.others_opacity === null || ...`——**量不到就
    // 当成通过**。
    //
    // 2026-10-22 实测：这条在 `check_scene_tokens.mjs` 上真的放过了一个只渲染当前
    // 词、其余全藏起来的页面（第三臂 r5，白拿一分）。本门当时没被这个坑咬到，
    // 是因为两代 12 期的实测值分别是 0.45 与 0.18，**从来不是 null**——修完仍然
    // 不会动任何一条已记的读数（2026-10-22 复核：24 期报告里没有一条 null）。
    check(w.locale, 'token_readable',
      dom.others_opacity !== null && dom.others_opacity >= TH.other_token_opacity,
      dom.others_opacity === null ? 'n/a（暗词一个都没量到）' : dom.others_opacity.toFixed(2),
      `≥${TH.other_token_opacity}`, '没唱到的词也要看得见（一个都没渲染出来＝看不见，比不透明度不足更严重）')
    check(w.locale, 'highlight_brand', !!dom.highlight?.brand,
      dom.highlight ? dom.highlight.bg : '无高亮', '品牌色 ' + BRAND.join('/'),
      '当前词的高亮必须落在页脚图例承诺的三色里')
    const maxAnn = dom.annot.length ? Math.max(...dom.annot.map((a) => a.dx)) : 0
    check(w.locale, 'annot_aligned', maxAnn <= TH.annot_offset_px, maxAnn.toFixed(1) + 'px',
      `≤${TH.annot_offset_px}px`, '注音列要和它注的那个字对齐')

    // 像素层：只量竖屏（发布平台吃的那一版），每语种取「唱到中段」与「唱完」两帧
    let pix = null
    if (key === 'portrait') {
      const mid = join(OUT, F.dir, `${w.locale}-2.png`)
      const done = join(OUT, F.dir, `${w.locale}-done.png`)
      const a = await pixelMetrics(mid)
      const b = await pixelMetrics(done)
      const list = [a, b].filter(Boolean)
      if (list.length) {
        pix = {
          ink_ratio: Math.min(...list.map((x) => x.ink_ratio)),
          max_empty_band: Math.max(...list.map((x) => x.max_empty_band)),
        }
        check(w.locale, 'no_big_empty_band', pix.max_empty_band <= TH.max_empty_band,
          (pix.max_empty_band * 100).toFixed(1) + '%', `≤${TH.max_empty_band * 100}%`,
          '画面上下不要空掉一大块')
      }
    }
    perLocale.push({ locale: w.locale, hero_h: heroH, hero_w: heroW, others_opacity: dom.others_opacity, highlight: dom.highlight, annot_max_dx: maxAnn, pixels: pix, tokens: dom.tokens, dbg: dom.dbg, error: dom.error ?? null })
    console.log(
      `  ${w.locale.padEnd(6)} 主角 ${(heroH * 100).toFixed(1).padStart(5)}%h/${(heroW * 100).toFixed(1).padStart(5)}%w` +
      `  暗词 ${dom.others_opacity === null ? ' n/a ' : dom.others_opacity.toFixed(2)}` +
      `  高亮 ${dom.highlight ? dom.highlight.bg : '无'}` +
      `  注音 ${maxAnn.toFixed(1)}px` +
      (pix ? `  空白带 ${(pix.max_empty_band * 100).toFixed(1)}%` : ''),
    )
  }
  report.formats[key] = perLocale
}

// ═══════════════════════════════════════════════════════════ 出报告
report.failures = failures
writeFileSync(REPORT, JSON.stringify(report, null, 2) + '\n', 'utf8')

if (failures.length) {
  console.error(`\n✖ 视频版式判据：${failures.length} 条不达标`)
  for (const f of failures) {
    console.error(`  [${f.locale}] ${f.name}：实测 ${f.actual}（要 ${f.need}）——${f.note}`)
  }
  console.error(`  报告：${REPORT}`)
  process.exit(1)
}
console.log(`\n✓ 视频版式判据全过 · 报告：${REPORT}`)
