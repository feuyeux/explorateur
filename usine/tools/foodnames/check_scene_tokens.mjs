// check_scene_tokens.mjs —— **场景页面的 token 版式门**（「各国美食名称」系列）
//
// 它量的是**智能体/人手搭出来的场景页面**（一个自包含 HTML），不是已渲染的成片。
// 成片那道门是 `check_video_layout.mjs`（要 frames，量得到像素与几何）；这一道只量
// **DOM 层能算的两条事实**，所以**不需要成片、不需要像素**，一个浏览器就能跑完：
//
//   ① `token_readable` —— **没唱到的词也要看得见**：非当前 token 的计算不透明度 ≥ 0.45
//   ② `highlight_brand` —— **当前词的高亮必须落在品牌三色里**（c9403a / 2f5d9e / b8860b）
//
// 判据的依据（不许比被改进对象自己的文件更严）：
//   · 两条都是**产线自己的**要求：`templates/video_style.css` 第 17 行写死
//     `.tok.dim { opacity: 0.45; }`，第 23–25 行给当前词上品牌三色；README「两条视频门」
//     一节把同一组阈值与三色复述了一遍（阈值与三色的唯一事实源在 `layout_rules.mjs`）。
//   · token 的类名契约（`.tok` / `.dim` / `.sung` / `.cur`）同样来自那份模板——
//     **通用 karaoke 模板用的也是这一套类名**，所以同一把尺子对「照通用模板做的页面」
//     和「照产线手册做的页面」都量得动，量出来的差别就是手册的效应。
//
// 为什么这道门值得单做：通用技能给的模板把这两条**教成了错的**
// （`.tok.dim{opacity:0.18}`、当前词高亮是中性灰 `rgba(44,38,32,0.09)`）——
// 那是旧 12 期成片的 D2–D5 实伤。这道门就是**量那两条**用的。
//
// 本门只读：**不改产物、不重渲染交付物**。探针跑在**副本**上（副本在临时目录里，
// 本地样式表被内联进去，所以相对路径的 `<link>` 不会因为换目录而失效）。
//
// Usage: node --import tsx tools/foodnames/check_scene_tokens.mjs --html <页面.html>
//        [--params '',?lang=zh-CN&state=0] [--report <json 路径>]
// 退出码：0 两条都达标；1 有不达标（逐条给出实测值与阈值）；2 门本身跑不成（不是零分）。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

import { platform } from '../../packages/core/src/index.ts'
import { BRAND, TH, TOKEN_CLASS } from './layout_rules.mjs'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const HTML = arg('html') ? resolve(arg('html')) : ''
const REPORT = arg('report') ? resolve(arg('report')) : ''
const DEBUG = process.argv.includes('--debug')
//: 同一个页面可能要带参数才肯渲染出内容（通用 karaoke 模板要 `?lang=` 才点亮一格，
//: `?state=` 决定唱到第几个词）。**多渲几组、取并集**：哪一组量到了就算量到了。
const PARAM_SETS = String(arg('params', ",?lang=zh-CN&state=0,?state=0"))
  .split(',')
  .map((s) => s.trim())
  .filter((s) => s !== '||')

// ═══════════════════════════════════════════════════════════ 页内探针
//
// 量的是**渲染后**的事实：`getComputedStyle` 的 opacity、祖先链上第一个非透明底色、
// 文字阴影色。「当前 token」按类名认（产线模板的契约），其余一律按「非当前」算。
const PROBE = `
<script>
(() => {
  const BRAND = ${JSON.stringify(BRAND)}
  const TOK = ${JSON.stringify(TOKEN_CLASS)}
  function hexOf(css) {
    if (!css) return ''
    const m = /rgba?\\(([^)]+)\\)/.exec(css)
    if (m) {
      const nums = m[1].split(/[,\\s\\/]+/).filter(Boolean).map(Number)
      if (nums.length < 3 || nums.some((n) => Number.isNaN(n))) return ''
      return nums.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
    }
    const h = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(css).trim())
    if (!h) return ''
    const s = h[1].length === 3 ? h[1].split('').map((c) => c + c).join('') : h[1]
    return s.toLowerCase()
  }
  function isBrand(css) {
    const hex = hexOf(css)
    return !!hex && BRAND.indexOf(hex) >= 0
  }
  function effBg(el) {
    for (let n = el; n; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && !/transparent/.test(bg)) return bg
    }
    return ''
  }
  function effShadow(el) {
    const sh = getComputedStyle(el).textShadow
    if (!sh || sh === 'none') return ''
    const parts = sh.split(/,(?![^(]*\\))/)
    for (const p of parts) {
      const c = p.trim().match(/rgba?\\([^)]*\\)|#[0-9a-f]{3,8}/i)
      if (c && isBrand(c[0])) return c[0]
    }
    return ''
  }
  function visible(el) {
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || st.display === 'none') return false
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0
  }
  function collect() {
    const toks = Array.from(document.querySelectorAll('.' + TOK.token))
    const cur = []
    const others = []
    let invisible = 0
    for (const t of toks) {
      if (!visible(t)) { invisible++; continue }
      const st = getComputedStyle(t)
      const op = parseFloat(st.opacity)
      const bg = effBg(t)
      const sh = effShadow(t)
      let brand = isBrand(bg) || isBrand(sh)
      let brandAt = brand ? (isBrand(bg) ? bg : sh) : ''
      // 当前词的高亮可能挂在子元素上（逐字着色时常见）：子元素的底色也算
      for (const kid of t.querySelectorAll('*')) {
        if (brand) break
        const kb = effBg(kid)
        const ks = effShadow(kid)
        if (isBrand(kb) || isBrand(ks)) { brand = true; brandAt = isBrand(kb) ? kb : ks; break }
      }
      const item = {
        text: String(t.textContent || '').slice(0, 40),
        opacity: Number.isNaN(op) ? 1 : op,
        bg: bg,
        brand: brand,
        brandAt: brandAt,
      }
      if (t.classList.contains(TOK.cur)) cur.push(item)
      else others.push(item)
    }
    return {
      tokens: toks.length,
      invisible: invisible,
      visible: cur.length + others.length,
      curCount: cur.length,
      othersCount: others.length,
      minOpacity: others.length ? Math.min.apply(null, others.map((o) => o.opacity)) : null,
      brandHit: cur.some((o) => o.brand),
      curSample: cur.slice(0, 4),
      othersSample: others.slice(0, 4),
    }
  }
  function report() {
    let payload
    try { payload = JSON.stringify(collect()) } catch (e) { payload = JSON.stringify({ error: String(e) }) }
    try { document.title = 'SCENE_TOKENS ' + payload } catch (e) {}
    try {
      const d = document.createElement('script')
      d.setAttribute('id', '__scene_tokens__')
      d.setAttribute('type', 'application/json')
      d.textContent = payload
      ;(document.body || document.documentElement).appendChild(d)
    } catch (e) {}
  }
  window.addEventListener('load', function () { report(); setTimeout(report, 250) })
  setTimeout(report, 1200)
})()
</script>
`

// ═══════════════════════════════════════════════════════════ 副本与渲染
let CHROME = null
function chromePath() {
  const p = platform.browserPath()
  if (!p) return ''
  return p
}
function spawnChrome(args) {
  if (!CHROME) CHROME = chromePath()
  if (!CHROME) return null
  return spawnSync(CHROME, args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
}

/**
 * 把页面里的**本地样式表内联进来**，并把相对 `url()` 改成绝对文件路径。
 *
 * 为什么必须这么做：通用 karaoke 模板用 `<link href="../../theme-tokens.css">`
 * 引主题令牌。若把探针副本放到临时目录里，相对路径就断了——**样式全丢**，
 * 于是每个 token 的 opacity 都变成默认的 1，量出来是「全部达标」的**假绿**。
 * 内联之后副本自洽，放哪儿都能量。
 */
function inlineCss(html, baseDir, depth = 0) {
  if (depth > 3) return html
  return html.replace(/<link\b[^>]*href=["']([^"']+)["'][^>]*>/gi, (whole, href) => {
    if (/^(https?:|data:|\/\/)/i.test(href)) return whole
    const file = isAbsolute(href) ? href : resolve(baseDir, href)
    if (!existsSync(file)) return whole
    let css
    try {
      css = readFileSync(file, 'utf8')
    } catch {
      return whole
    }
    css = css.replace(/url\(\s*['"]?([^'")]+)['"]?\s*\)/gi, (w, u) => {
      if (/^(https?:|data:|#)/i.test(u)) return w
      const abs = isAbsolute(u) ? u : resolve(dirname(file), u)
      return 'url("file:///' + abs.replace(/\\/g, '/') + '")'
    })
    css = inlineCss(css, dirname(file), depth + 1)
    return '<style data-inlined="' + href + '">\n' + css + '\n</style>'
  })
}

function makeProbeCopy(html, baseDir) {
  const withCss = inlineCss(html, baseDir)
  const probe = withCss.includes('<script>')
    ? withCss.replace('<script>', PROBE + '<script>')
    : withCss.replace(/<\/body>/i, '<script>' + PROBE + '</script></body>')
  return probe
}

/** 渲一组参数，把页内报的 JSON 取出来。 */
function renderOnce(probeHtml, params) {
  const dir = mkdtempSync(join(tmpdir(), 'scene-tokens-'))
  try {
    const p = join(dir, 'probe.html')
    writeFileSync(p, probeHtml, 'utf8')
    const url = 'file:///' + p.replace(/\\/g, '/') + (params ? (params.startsWith('?') ? params : '?' + params) : '')
    const r = spawnChrome([
      '--headless=new', '--disable-gpu', '--no-sandbox', '--virtual-time-budget=9000',
      '--window-size=1080,1920', '--force-device-scale-factor=1', '--hide-scrollbars', '--dump-dom', url,
    ])
    if (!r) {
      if (DEBUG) console.error('[debug] 找不到浏览器')
      return null
    }
    const out = r.stdout || ''
    let m = /<title>SCENE_TOKENS ([\s\S]*?)<\/title>/.exec(out)
    if (!m) m = /<script id="__scene_tokens__" type="application\/json">([\s\S]*?)<\/script>/.exec(out)
    if (!m) {
      if (DEBUG) {
        console.error(`[debug ${params || '(无)'}] 没找到标记：status=${r.status} stdout=${out.length} 字节`)
        console.error('[debug] stdout 头 300：' + out.slice(0, 300).replace(/\n/g, ' '))
        const t = /<title>([\s\S]*?)<\/title>/.exec(out)
        console.error('[debug] title = ' + (t ? t[1].slice(0, 200) : '(无)'))
        console.error('[debug] stderr 尾 300：' + (r.stderr || '').slice(-300).replace(/\n/g, ' '))
      }
      return null
    }
    try {
      return JSON.parse(m[1])
    } catch (e) {
      if (DEBUG) console.error(`[debug] JSON 解析失败：${e.message}｜${m[1].slice(0, 200)}`)
      return null
    }
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

// ═══════════════════════════════════════════════════════════ 门
function measure(htmlPath) {
  const html = readFileSync(htmlPath, 'utf8')
  const probe = makeProbeCopy(html, dirname(htmlPath))
  const perParam = []
  for (const params of PARAM_SETS) {
    const d = renderOnce(probe, params)
    if (d) perParam.push({ params: params || '(无)', data: d })
  }
  const withTokens = perParam.filter((p) => p.data && p.data.visible > 0)
  const opacities = withTokens.map((p) => p.data.minOpacity).filter((v) => v !== null && v !== undefined)
  const minOpacity = opacities.length ? Math.min.apply(null, opacities) : null
  const brandHit = withTokens.some((p) => p.data.brandHit)
  return {
    file: htmlPath,
    params_tried: PARAM_SETS.length,
    renders_ok: perParam.length,
    renders_with_tokens: withTokens.length,
    minOpacity: minOpacity,
    brandHit: brandHit,
    perParam: perParam.map((p) => ({ params: p.params, tokens: p.data.tokens, visible: p.data.visible, cur: p.data.curCount, minOpacity: p.data.minOpacity, brandHit: p.data.brandHit })),
    curSample: withTokens.length ? withTokens[0].data.curSample : [],
    othersSample: withTokens.length ? withTokens[0].data.othersSample : [],
  }
}

/** 两条判据的判定。`null` = 量不到（门跑不成，不是零分）。 */
export function verdict(m) {
  const fails = []
  if (!m || m.renders_with_tokens === 0) {
    return {
      ok: false,
      measurable: false,
      fails: [
        {
          name: 'token_readable',
          actual: null,
          need: `≥${TH.other_token_opacity}`,
          note: '页面上没有可见的 token（契约未实现或页面不渲染）——量不到，不是零分',
        },
        {
          name: 'highlight_brand',
          actual: null,
          need: BRAND.join('/'),
          note: '页面上没有可见的 token（契约未实现或页面不渲染）——量不到，不是零分',
        },
      ],
    }
  }
  const opacityOk = m.minOpacity === null ? true : m.minOpacity >= TH.other_token_opacity
  if (!opacityOk) {
    fails.push({
      name: 'token_readable',
      actual: Number(m.minOpacity.toFixed(3)),
      need: `≥${TH.other_token_opacity}`,
      note: '没唱到的词也要看得见（暗词不透明度低于阈值就是几乎隐形）',
    })
  }
  if (!m.brandHit) {
    fails.push({
      name: 'highlight_brand',
      actual: '无品牌色高亮',
      need: BRAND.join('/'),
      note: '当前词的高亮必须落在页脚图例承诺的三色里',
    })
  }
  return { ok: fails.length === 0, measurable: true, fails: fails, minOpacity: m.minOpacity, brandHit: m.brandHit }
}

if (process.argv[1] && process.argv[1].endsWith('check_scene_tokens.mjs')) {
  if (!HTML) {
    console.error('用法：node --import tsx tools/foodnames/check_scene_tokens.mjs --html <页面.html>')
    process.exit(2)
  }
  if (!existsSync(HTML)) {
    console.error(`找不到页面：${HTML}`)
    process.exit(2)
  }
  const m = measure(HTML)
  const v = verdict(m)
  const out = { file: HTML, ok: v.ok, measurable: v.measurable, fails: v.fails, measure: m }
  console.log(JSON.stringify(out, null, 1))
  if (REPORT) writeFileSync(REPORT, JSON.stringify(out, null, 1), 'utf8')
  process.exit(v.measurable ? (v.ok ? 0 : 1) : 2)
}
