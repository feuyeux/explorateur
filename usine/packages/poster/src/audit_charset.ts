// audit_charset.ts — 字符子集门：每个「先嵌子集字体」的 family 渲染的字符都必须
// 在它的 fonts.json subset text 名单里——防止改稿后出豆腐块。
// （promoted from skills/one-page-poster/scripts/audit_charset.py，P5-7e 归流）
//
// Usage: audit-charset [poster_src.html] [fonts.json]
// fonts.json 条目须带 "classes"（用该 family 渲字的 CSS 类，如 "f-deva"）；
// 含转写行 class 的 family 连 Latin 行也一并覆盖。任何自带 font-family 的类
// （.annot/.jyut/.tagline…）都必须进这份名单——审计只透过它看 family。
//
// 家族归属是**栈式**的，镜像 CSS font-family 继承：
// - class 映射到某 family 的元素压栈该 family；
// - 其他元素（无 class、或 class 不在 fonts.json）继承外层 family。逐字着色
//   包裹层（.stack/.lay/.top/.t/.c/.sp、韩文 .ksyl 垫片、.zi/.hz/.annot 列）
//   全是「带 class 但无映射族」——旧扁平实现在任何带 class 的标签上清空家族态，
//   叠印层整词（a01 धन्यवाद / a02 माफ़ कीजिए）恰好从这里逃过 tofu 门；
// - 闭合标签弹栈。
//
// 手写海报源逐标签显式闭合；隐式闭合 HTML（p/li/td）只可能往**多归**方向失步，
// 失步会响亮失败。void 元素与自闭合标签永不压栈（不会有闭合标签来弹它们）。
//
// 第二道门——垫片规则绑定（A-03）：.ksyl 垫片规则名由 measure-korean 按
// `k%04X`（ord(glyph)）起名，贴错名字的规则会被错误的字形静默穿上，且没有别的
// 门能抓到：measure-korean 拿规则**自己的**标签自证，子集门只查页面字符 ⊆
// fonts.json。A-03 实锤出货过一次（class .kB9CC = 만 的几何贴在 많 字形上）。
// 逐垫片字形断言：class 码位 == 字形码位、规则存在、无孤儿规则。
import { readFileSync } from 'node:fs'

const VOID = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr',
])

const PATCH_CLASS = /^k([0-9A-Fa-f]{4})$/

// html.unescape 的具名实体表：Python 是全 HTML5 名录（2000+ 条），此处收录
// 排版面最常见的条目 + 数字引用——名录外的具名实体原样保留（Python 对未知实体
// 同样原样保留；差异只可能发生在罕见具名实体上，方向是「少解出字符 → 审计多报
// → 响亮失败」而非漏网）。带分号才认——Python 还认无分号的老式写法，同样按
// 「多报不漏报」的方向偏差记录在案。
const NAMED_ENTITIES: Record<string, string> = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: '\u00a0',
  copy: '©', reg: '®', trade: '™', hellip: '…', mdash: '—', ndash: '–',
  lsquo: '\u2018', rsquo: '\u2019', ldquo: '\u201c', rdquo: '\u201d',
  laquo: '«', raquo: '»', deg: '°', plusmn: '±', times: '×', divide: '÷',
  minus: '−', middot: '·', sect: '§', para: '¶', bull: '•',
  dagger: '†', Dagger: '‡', prime: '′', Prime: '″', permil: '‰',
  larr: '←', rarr: '→', uarr: '↑', darr: '↓', harr: '↔',
  euro: '€', pound: '£', yen: '¥', cent: '¢', curren: '¤',
  frac12: '½', frac14: '¼', frac34: '¾', sup2: '²', sup3: '³',
  szlig: 'ß', agrave: 'à', aacute: 'á', eacute: 'é', egrave: 'è',
  ccedil: 'ç', ntilde: 'ñ', ouml: 'ö', uuml: 'ü', auml: 'ä',
  oacute: 'ó', iacute: 'í', uacute: 'ú', oelig: 'œ', aelig: 'æ',
  fnof: 'ƒ', alpha: 'α', beta: 'β', pi: 'π', micro: 'µ', omega: 'ω',
}

export function unescapeHtml(s: string): string {
  return s.replace(/&#(\d+);?|&#[xX]([0-9a-fA-F]+);?|&([a-zA-Z][a-zA-Z0-9]*);/g, (m0, dec, hex, name) => {
    if (dec !== undefined) return String.fromCodePoint(Number(dec))
    if (hex !== undefined) return String.fromCodePoint(parseInt(hex, 16))
    return NAMED_ENTITIES[name] ?? m0
  })
}

/** Python str.isspace() 的镜像（\x1c-\x1f 与 \x85 是 JS \s 不含的尾巴）。 */
function isPySpace(ch: string): boolean {
  const c = ch.codePointAt(0)!
  return (c >= 0x1c && c <= 0x1f) || c === 0x85 || /\s/u.test(ch)
}

function bodyOf(src: string): string {
  const i = src.indexOf('<body>')
  let body = i >= 0 ? src.slice(i + '<body>'.length) : src
  body = body.replace(/<!--[\s\S]*?-->/g, '')
  body = body.replace(/<script>[\s\S]*?<\/script>/g, '')
  body = body.replace(/<style>[\s\S]*?<\/style>/g, '')
  return body
}

export interface CharsetMissing {
  fam: string
  ch: string
  code: string
}

/** 子集门本体：missing = [(family, 字符, hex(ord))]——归属到某 family 但不在其
 * subset text 里的每个字符；counts = {family: 检过的去重字符数}。 */
export function check(srcPath: string, specPath: string): [CharsetMissing[], Record<string, number>] {
  const spec = JSON.parse(readFileSync(specPath, 'utf8')) as Array<{
    family: string
    text: string
    classes?: string[]
  }>
  const fams: Record<string, string> = {}
  const class2fam: Record<string, string> = {}
  for (const e of spec) {
    fams[e['family']!] = e['text']!
    for (const c of (e['classes'] === undefined ? [] : e['classes'])!) class2fam[c] = e['family']
  }

  const src = readFileSync(srcPath, 'utf8')
  const body = bodyOf(src)

  // 逐 token 走标签流，按模块头说明维护家族栈
  const stack: Array<string | null> = [] // 栈顶 = 最内层 family；null = 不在任何 family 里
  const use: Record<string, Set<string>> = {}
  for (const m of body.matchAll(/<(\/?)(\w+)([^>]*)>|([^<]+)/g)) {
    const closing = m[1]!
    if (closing) {
      if (stack.length) stack.pop()
      continue
    }
    const name = m[2]
    if (name !== undefined) {
      const attrs = m[3] ?? ''
      if (VOID.has(name.toLowerCase()) || attrs.trimEnd().endsWith('/')) continue // 永不被闭合
      let fam = stack.length > 0 ? stack[stack.length - 1]! : null // 缺省继承
      const cm = attrs.match(/class="([^"]*)"/)
      if (cm) {
        for (const c of cm[1]!.split(/\s+/)) {
          if (c in class2fam) {
            fam = class2fam[c]!
            break
          }
        }
      }
      stack.push(fam)
    } else {
      const text = unescapeHtml(m[4] ?? '')
      // 启发式跳过 script 正文残段
      if (text.includes('function') || text.includes('const ') || text.includes('document.')) continue
      const top = stack.length > 0 ? stack[stack.length - 1]! : null
      if (top !== null) {
        const set = (use[top] ??= new Set())
        for (const ch of text) if (!isPySpace(ch)) set.add(ch)
      }
    }
  }

  const missing: CharsetMissing[] = []
  for (const fam of Object.keys(use).sort()) {
    for (const ch of [...use[fam]!].sort((a, b) => a.codePointAt(0)! - b.codePointAt(0)!)) {
      if (!fams[fam]!.includes(ch) && ch !== ' ') {
        missing.push({ fam, ch, code: '0x' + ch.codePointAt(0)!.toString(16) })
      }
    }
  }
  const counts: Record<string, number> = {}
  for (const f of Object.keys(use)) counts[f] = use[f]!.size
  return [missing, counts]
}

/** 垫片规则绑定门（模块头第二道门）。 */
export function checkPatchBindings(srcPath: string): string[] {
  const src = readFileSync(srcPath, 'utf8')
  const defined = new Set<string>()
  for (const sm of src.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) {
    const sty = sm[1]!.replace(/\/\*[\s\S]*?\*\//g, '') // CSS 注释是散文，不是规则
    for (const m of sty.matchAll(/\.k([0-9A-Fa-f]{4})\s*[{,]/g)) defined.add(m[1]!.toUpperCase())
  }

  const body = bodyOf(src)
  const problems: string[] = []
  const used = new Set<string>()
  const openCls: string[][] = []
  for (const m of body.matchAll(/<(\/?)([\w-]+)([^>]*)>|([^<]+)/g)) {
    const closing = m[1]!
    if (closing) {
      if (openCls.length) openCls.pop()
      continue
    }
    const name = m[2]
    if (name !== undefined) {
      const attrs = m[3] ?? ''
      if (VOID.has(name.toLowerCase()) || attrs.trimEnd().endsWith('/')) continue // 永不被闭合
      const cm = attrs.match(/class="([^"]*)"/)
      const pcs = (cm ? cm[1]!.split(/\s+/) : []).filter((c) => PATCH_CLASS.test(c))
      openCls.push(pcs)
      continue
    }
    const glyphs = unescapeHtml(m[4] ?? '').trim()
    if (!openCls.length || !openCls[openCls.length - 1]!.length || !glyphs) {
      continue // 不在垫片 span 里 / 纯空白
    }
    for (const cls of openCls[openCls.length - 1]!) {
      const want = parseInt(cls.slice(1), 16)
      used.add(want.toString(16).toUpperCase().padStart(4, '0'))
      const gl = [...glyphs] // Python len()/ord() 按码点数：一个星面字形 .length 会是 2
      if (gl.length !== 1) {
        problems.push(`${cls}: expected ONE glyph, found ${gl.length}: '${glyphs}'`)
      } else if (gl[0]!.codePointAt(0)! !== want) {
        const got = gl[0]!.codePointAt(0)!
        problems.push(
          `${cls}: glyph '${glyphs}' is U+${got.toString(16).toUpperCase().padStart(4, '0')}, `
            + `not U+${want.toString(16).toUpperCase().padStart(4, '0')} — wearing another glyph's patches`,
        )
      }
      if (!defined.has(cls.slice(1).toUpperCase())) problems.push(`${cls}: no CSS rule .${cls} defined in the poster`)
    }
  }
  for (const cp of [...defined].filter((c) => !used.has(c)).sort()) {
    problems.push(`orphan rule .k${cp} is defined but worn by no glyph`)
  }
  return problems
}

export function main(argv: string[]): number {
  const srcPath = argv[0] !== undefined ? argv[0]! : 'poster_src.html'
  const specPath = argv[1] !== undefined ? argv[1]! : 'fonts.json'
  const [missing, counts] = check(srcPath, specPath)
  // 两道门都先报全再退出：子集失败不许遮住绑定失败（A-03 出货时两道同时
  // 活着——字形穿错了别人的规则，且子集已不再覆盖它）。
  const patch = checkPatchBindings(srcPath)
  if (missing.length > 0) {
    console.log('MISSING from subsets:')
    for (const { fam, ch, code } of missing) console.log(`  ${fam}: '${ch}' ${code}`)
  }
  if (patch.length > 0) {
    console.log('PATCH-RULE BINDING PROBLEMS:')
    for (const p of patch) console.log(`  ${p}`)
  }
  if (missing.length > 0 || patch.length > 0) return 1
  console.log('charset audit: all chars covered')
  for (const fam of Object.keys(counts).sort()) console.log(`  ${fam}: ${counts[fam]} distinct chars checked`)
  console.log('  patch rules: every .ksyl glyph wears the rule of its own codepoint')
  return 0
}
