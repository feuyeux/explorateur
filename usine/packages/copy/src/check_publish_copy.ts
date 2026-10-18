// check_publish_copy.ts — 发布词自检（零平台流量，零外部依赖）
// （promoted from skills/publish-copy/scripts/check_publish_copy.py，P5-7f 归流）
//
// 写完 `publish/*.md` 之后、在交给 `multilingual-video-publishing` 之前必跑。
// 本工具只读本地 markdown，**不碰任何平台**，所以可以随时跑、随便跑。
//
// 检查项（每项都有可观测判据，「机检门」与 SKILL.md `## 验收判据` 表一一对应
// ——纪律 6：不变量必须有机检；指不出判据就不算判据）：
//
// 1. 必需 H2 段落齐全 — checkRequiredSections
// 2. 标题字数 — 小红书 ≤20 / 抖音 ≤30 / B站 ≤80（publish-playbook §2 同源）
// 3. 话题末尾尾随空格 — 抖音 + 小红书必带；B 站无 #tag 区免检
// 4. 互动钩短语 — 报数 / 点单 / 跟读 / 催更 / 评论区 / 弹幕 / 敢不敢
//    （单字「敢」被否决——勇敢 / 不敢 / 哪里敢 都会撞，太松）
// 5. 置顶话术 — 发布贴士里同时出现「置顶」+ 引号示例（"..." 或 「...」）
// 6. no-hard-wrap 零违规 — 与 markdown-no-hard-wrap skill §自查判定逻辑对齐
//    （drift 风险：本文件是上游 heredoc 的内联副本，上游改判据时这里要同步改）
// 7. AI 指纹零命中 — checkAiFingerprint：只查**读者面**（标题 + 正文/文案/简介），
//    发布贴士是写给操作者的（允许提规则本身），不在扫描面内。
//    机检的是**可枚举签名**；语感判不了的部分仍归编辑走查
// 8. 数字可溯源 — checkFactProvenance（--facts 给了才跑；没给 SKIP，SKIP 不是 PASS）
//
// Usage: feuille copy check <publish_dir> [--facts facts.json] [--strict]
import { existsSync, readFileSync, readdirSync } from 'node:fs'

import { FeuilleError, roundHalfEven } from '@feuille/core'

// 平台硬约定（与 SKILL.md `## 各平台规格`、publish-playbook §2 同源）
export interface PlatformSpec {
  filename: string
  titleMax: number
  requiredH2: string[]
  bodySection: string
  tagsSection: string
  tagStyle: 'hash' | 'space'
}

export const PLATFORM: Record<string, PlatformSpec> = {
  xiaohongshu: {
    filename: 'xiaohongshu.md',
    titleMax: 20,
    requiredH2: ['标题（20 字内）', '正文', '话题标签', '发布贴士'],
    bodySection: '正文',
    tagsSection: '话题标签',
    tagStyle: 'hash', // #xxx 风格；末尾必带尾随空格
  },
  douyin: {
    filename: 'douyin.md',
    titleMax: 30,
    requiredH2: ['文案', '话题', '发布贴士'],
    bodySection: '文案',
    tagsSection: '话题',
    tagStyle: 'hash', // 同上
  },
  bilibili: {
    filename: 'bilibili.md',
    titleMax: 80,
    requiredH2: ['标题', '简介', '标签', '发布贴士'],
    bodySection: '简介',
    tagsSection: '标签',
    tagStyle: 'space', // 空格分隔不带 #；无尾随空格问题
  },
}

// 互动钩短语（多字，避免单字「敢」误伤「勇敢 / 不敢」等无关上下文）
export const HOOK_PHRASES = ['报数', '点单', '跟读', '催更', '评论区', '弹幕', '敢不敢']

// AI 指纹（与 SKILL.md `## 失败模式` 末条同源；drift 风险同 HOOK_PHRASES——
// 上游清单更新时这里要同步改）。「原来」只判**句首**形态：句中作叙事词的
// 「原来」不少见，全量禁会误伤；AI 的指纹是「原来 + 揭秘句式」的开头用法。
export const AI_FINGERPRINT_WORDS = ['yyds', 'xswl', '绝绝子', '狠狠地', '藏了心机', '宝藏', '把世界上好听的话']
export const AI_REVEAL_RE = /(?:^|\n|(?<=[。！？!]))\s*原来/
export const AI_EXCLAIM_RUN_RE = /[!！]{2,}/ // ！！连刷（单个 ！ 合法）
export const AI_SIMILE_RE = /像[^，。！？\n“”"']{1,12}一样的/ // 像 X 一样的 Y 模板句
export const EMOJI_PER_LINE_MAX = 3 // 一行 >3 个 emoji = 滥用（SKILL.md：一句三四个）

// Python str.splitlines() 逐位镜像：按通用换行边界切（含 \v \f \x1c-\x1e
// \x85 \u2028 \u2029），且结尾换行不产空段——裸 split 会多出一个 ''，
// 段末行判定（如话题末尾尾随空格）会被它顶掉。
const splitLines = (text: string): string[] => {
  if (text === '') return []
  const parts = text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)
  if (parts[parts.length - 1] === '') parts.pop()
  return parts
}

/** emoji 粗计（0x1F000 起的 emoji 平面 + 2600–27BF 杂项符号/装饰符号，
 * ✨ U+2728 在后者）。粗计够用：判的是「一行刷四五个」的滥用，不是精确字形学。 */
export function emojiCount(line: string): number {
  let n = 0
  for (const ch of line) {
    const cp = ch.codePointAt(0)!
    if (cp >= 0x1f000 || (cp >= 0x2600 && cp <= 0x27bf)) n++
  }
  return n
}

// ============================================================
//  Markdown 段切分：把 ## H2 切成 (标题, 内容) 列表
// ============================================================

/** [(h2_title, body_lines)]。H1 (`# Title`) 不算段。 */
export function splitH2Sections(text: string): Array<[string, string[]]> {
  const sections: Array<[string, string[]]> = []
  let curTitle: string | null = null
  let curBody: string[] = []
  for (const line of splitLines(text)) {
    const m = /^##\s+(.+?)\s*$/.exec(line)
    if (m) {
      if (curTitle !== null) sections.push([curTitle, curBody])
      curTitle = m[1]!.trim()
      curBody = []
    } else if (curTitle !== null) {
      curBody.push(line)
    }
  }
  if (curTitle !== null) sections.push([curTitle, curBody])
  return sections
}

/** 给定 H2 段的正文文本（trim 后），段不在返回 null。 */
export function sectionText(title: string, sections: Array<[string, string[]]>): string | null {
  for (const [t, body] of sections) {
    if (t.trim() === title) return body.join('\n').trim()
  }
  return null
}

/** 给定 H2 段的非空正文行，段不在返回 []。 */
export function sectionBodyLines(title: string, sections: Array<[string, string[]]>): string[] {
  for (const [t, body] of sections) {
    if (t.trim() === title) return body.filter((ln) => ln.trim() !== '')
  }
  return []
}

// ============================================================
//  Python repr 镜像（报错文案与 Python 版逐字一致——f-string 直接吃 list）
// ============================================================

function pyStr(s: string): string {
  // Python repr：默认单引号；内含单引号且不含双引号时换双引号
  if (s.includes("'") && !s.includes('"')) return `"${s}"`
  return `'${s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n')}'`
}

function pyList(items: Array<string | number>): string {
  return `[${items.map((x) => (typeof x === 'string' ? pyStr(x) : String(x))).join(', ')}]`
}

function readText(path: string): string {
  return readFileSync(path, 'utf8')
}

// ============================================================
//  Checks — 每条与 SKILL.md `## 验收判据` 表一一对应
// ============================================================

/** 1. 必需 H2 段落齐全。 */
export function checkRequiredSections(path: string, platform: string): string[] {
  const sections = splitH2Sections(readText(path))
  const present = new Set(sections.map(([t]) => t.trim()))
  const spec = PLATFORM[platform]!
  return spec.requiredH2.filter((h2) => !present.has(h2)).map((h2) => `缺必需 H2 段落「${h2}」`)
}

/** 2. 标题字数：按码点计（emoji / ASCII 都按 1 字，与用户所见一致）。
 *
 * 取标题源的规则（与 multilingual-video-publishing 的 check-plan 读 title
 * 的方式同源——publishing 端从清单的 `title` 字段核，本 skill 从 markdown
 * 同位字段核，确保两边不漂移）：
 *
 * - 小红书：`## 标题（20 字内）` 段内容
 * - B站：`## 标题` 段内容
 * - 抖音：**没有 `## 标题` 段**——`## 文案` 段的第一行就是标题
 *   （抖音投稿表单的「标题」与「正文」共用一个输入框，文案开头即标题）
 */
export function checkTitleLen(path: string, platform: string): string[] {
  const spec = PLATFORM[platform]!
  const sections = splitH2Sections(readText(path))
  let title: string
  if (platform === 'douyin') {
    const lines = sectionBodyLines('文案', sections)
    if (lines.length === 0) return ['「文案」段为空——抖音的标题与正文都在这一段']
    title = lines[0]!
  } else {
    const titleH2 = platform === 'xiaohongshu' ? '标题（20 字内）' : '标题'
    const lines = sectionBodyLines(titleH2, sections)
    if (lines.length === 0) return [`标题 H2「${titleH2}」内容为空`]
    title = lines.join(' ')
  }
  const n = [...title].length
  if (n > spec.titleMax) return [`标题 ${n} 字 > 上限 ${spec.titleMax}：${pyStr(title)}`]
  return []
}

/** 3. 话题末尾尾随空格（仅抖音 + 小红书；B站无 #tag 区）。 */
export function checkTrailingSpace(path: string, platform: string): string[] {
  const spec = PLATFORM[platform]!
  if (spec.tagStyle !== 'hash') return []
  const sections = splitH2Sections(readText(path))
  const lines = sectionBodyLines(spec.tagsSection, sections)
  if (lines.length === 0) {
    // 段落缺失由 check_required_sections 报；这里不重复
    return []
  }
  const last = lines[lines.length - 1]!
  if (!last.endsWith(' ')) {
    return [
      `「${spec.tagsSection}」末尾缺尾随空格`
        + `（publish-playbook 坑 ①：Slate 联想面板会吃掉末段话题）`
        + `，当前末行：${pyStr(last)}`,
    ]
  }
  return []
}

/** 4. 互动钩短语至少出现一个。 */
export function checkHookPhrase(path: string, platform: string): string[] {
  const spec = PLATFORM[platform]!
  const sections = splitH2Sections(readText(path))
  const body = sectionText(spec.bodySection, sections) ?? ''
  if (!HOOK_PHRASES.some((phrase) => body.includes(phrase))) {
    return [
      `「${spec.bodySection}」缺互动钩短语`
        + `（${pyList(HOOK_PHRASES)} 至少一个）——评论区会冷场`,
    ]
  }
  return []
}

/** 5. 发布贴士含「置顶」+ 引号示例。 */
export function checkPinnedQuote(path: string, _platform: string): string[] {
  const sections = splitH2Sections(readText(path))
  const tip = sectionText('发布贴士', sections) ?? ''
  if (!tip.includes('置顶')) return ['「发布贴士」缺「置顶」——发布后自己置顶是拉新的硬动作']
  // 引号示例：英文双引号 / 中文「」/ 中文“” 都算
  const hasQuote = /["“”「」][^"“”「」]+["“”「」]/.test(tip)
  if (!hasQuote) {
    return ['「发布贴士」含「置顶」但缺引号示例（"…" 或 「…」）——话术必须落到具体字面，临时编的钩子弱']
  }
  return []
}

/** 6. no-hard-wrap 检查（违规行号，1-based）。
 *
 * 源码：markdown-no-hard-wrap skill §自查。内联副本而非导入——上游是
 * bash heredoc，没有可 import 的模块。⚠️ drift 风险：上游改判据时这里要同步改。
 */
export function noHardWrapViolations(text: string): number[] {
  let lines = splitLines(text)

  const fenceLine = (l: string): boolean => /^\s*```/.test(l)

  const structural = (l: string): boolean => {
    const st = l.replace(/^\s+/, '')
    if (st === '') return true
    if (st.startsWith('#') || st.startsWith('|') || st.startsWith('>') || st.startsWith('```')) return true
    if (/^(\d+\.\s|[-*+]\s)/.test(st)) return true
    return false
  }

  // 剥掉前置元数据（frontmatter）——与上游 heredoc 同
  if (lines.length > 0 && lines[0]!.trim() === '---') {
    const end = lines.findIndex((l, i) => i >= 1 && l.trim() === '---')
    if (end >= 0) lines = [...lines.slice(0, 1), ...lines.slice(end + 1)]
  }

  const bad: number[] = []
  let inCode = false
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]!
    if (fenceLine(l)) {
      inCode = !inCode
      continue
    }
    if (inCode || structural(l)) continue
    const nxt = i + 1 < lines.length ? lines[i + 1]! : ''
    if (nxt.trim() !== '' && !fenceLine(nxt) && !structural(nxt)) bad.push(i + 1)
  }
  return bad
}

/** 6. no-hard-wrap 零违规。 */
export function checkNoHardWrap(path: string, _platform: string): string[] {
  const bad = noHardWrapViolations(readText(path))
  if (bad.length > 0) return [`段内硬换行违规于第 ${pyList(bad)} 行（合并为单行）`]
  return []
}

// ============================================================
//  读者面文字（AI 指纹与数字溯源的扫描面）
// ============================================================

/** 读者会看到的文字：标题 + 正文/文案/简介。
 *
 * **发布贴士不在扫描面**——它是写给操作者的内部说明，允许提规则本身
 * （「别用绝绝子」「标题 20 字内」这类话在贴士里合法，进了正文才是 AI 味）。
 * 话题标签另查（尾随空格），不在这里重复。
 */
export function readerText(path: string, platform: string): string {
  const spec = PLATFORM[platform]!
  const sections = splitH2Sections(readText(path))
  if (platform === 'douyin') {
    // 抖音的标题与正文共用 `## 文案`（投稿表单只有一个输入框）
    return sectionText('文案', sections) ?? ''
  }
  const titleH2 = platform === 'xiaohongshu' ? '标题（20 字内）' : '标题'
  const parts = [sectionText(titleH2, sections) ?? '', sectionText(spec.bodySection, sections) ?? '']
  return parts.join('\n')
}

/** 7. AI 指纹零命中（机检部分——枚举得出的签名）。
 *
 * 语感（节奏 / 模板感 / 脊柱一致）判不了，仍归编辑走查；这里拦的是
 * 能写成规则的硬签名。清单与 SKILL.md 失败模式末条同源。
 */
export function checkAiFingerprint(path: string, platform: string): string[] {
  const raw = readerText(path, platform)
  const low = raw.toLowerCase()
  const problems: string[] = []
  for (const w of AI_FINGERPRINT_WORDS) {
    if (low.includes(w)) problems.push(`AI 指纹「${w}」命中——读一遍全砍（见失败模式末条）`)
  }
  if (AI_REVEAL_RE.test(raw)) problems.push('句首「原来…」揭秘句式命中——AI 指纹，用自己的话说')
  if (AI_EXCLAIM_RUN_RE.test(raw)) problems.push('连续感叹号（！！+）命中——句末感叹号刷屏')
  if (AI_SIMILE_RE.test(raw)) problems.push('「像 X 一样的 Y」模板句命中')
  for (const ln of splitLines(raw)) {
    const n = emojiCount(ln)
    if (n > EMOJI_PER_LINE_MAX) {
      problems.push(`一行内 emoji ${n} 个 > ${EMOJI_PER_LINE_MAX}——emoji 滥用`)
      break
    }
  }
  return problems
}

/** 事实表里全部可作数字出处的值（数值直接收；字符串能 parse 成数字的也收）。 */
export function factNumbers(facts: Record<string, unknown> | null | undefined): Set<number> {
  const out = new Set<number>()
  if (!facts) return out
  // 只按 Python float() 的接受面收：可选符号 + 数字（含 . 与科学计数）。
  // JS Number() 会吞 "0x10"（Python float() 不收），十六进制不能当出处。
  const pyFloatAble = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/
  for (const v of Object.values(facts)) {
    if (typeof v === 'boolean') continue
    if (typeof v === 'number') {
      out.add(v)
      continue
    }
    if (typeof v === 'string') {
      const s = v.trim()
      if (s !== '' && pyFloatAble.test(s)) out.add(Number(s))
    }
  }
  return out
}

/** 8. 数字可溯源：读者面文字里出现的每个数字都能在事实表里找到出处。
 *
 * 事实表 = `--facts facts.json`（键随便起，值是可核对的数：实测时长、
 * 语种/条目数、bgm 边车的 gain_basis 数字等）。对账规则：声称值 n 匹配
 * 事实值 f 当且仅当 n == f 或 round(f) == n 或 round(f, 1) == n
 * （Python round 是银行家舍入——「52 秒」对实测 52.4s 合法：四舍五入是
 * 写作，不是编造）。话题标签（#xxx）先剥掉——标签不是数字载体。
 */
export function checkFactProvenance(
  path: string,
  platform: string,
  facts: Record<string, unknown>,
): string[] {
  const raw0 = readerText(path, platform)
  const raw = raw0.replace(/#[^\s#]+/g, ' ')
  const claimed = [...new Set(raw.match(/\d+(?:\.\d+)?/g) ?? [])].sort()
  if (claimed.length === 0) return []
  const nums = factNumbers(facts)
  const untraced = claimed.filter((c) => {
    const cv = Number(c)
    return ![...nums].some((f) => cv === f || roundHalfEven(f) === cv || roundHalfEven(f * 10) / 10 === cv)
  })
  if (untraced.length > 0) {
    return [
      `数字 ${pyList(untraced)} 在 --facts 事实表里找不到出处——`
        + '编造规格是本 skill 最严重的失败模式；要么删，'
        + '要么把真实数字写进事实表（实测时长 / 条目数 / 边车数字）',
    ]
  }
  return []
}

// 注册表：机检名 → check 函数（与 SKILL.md `## 验收判据` 表的实现列对齐）
export const CHECKS: Array<[string, (path: string, platform: string) => string[]]> = [
  ['必需 H2 段落齐全', checkRequiredSections],
  ['标题字数', checkTitleLen],
  ['话题末尾尾随空格', checkTrailingSpace],
  ['互动钩短语', checkHookPhrase],
  ['置顶话术', checkPinnedQuote],
  ['no-hard-wrap 零违规', checkNoHardWrap],
  ['AI 指纹零命中', checkAiFingerprint],
]

// ============================================================
//  Top-level orchestrator
// ============================================================

const USAGE = 'usage: feuille copy check <publish_dir> [--facts facts.json] [--strict]'

/** 检查 publish_dir 下的所有平台文件。返回非零退出码当存在 FAIL。
 *
 * 缺失的 `xiaohongshu.md` / `douyin.md` / `bilibili.md` 是真实投诉
 * （写者没交齐），不是静默 SKIP。
 * facts：--facts 事实表（给了才跑数字溯源；没给 = SKIP，SKIP 不是 PASS）。
 */
export function checkPublishDir(publishDir: string, facts?: Record<string, unknown>): number {
  let rc = 0
  let anyFile = false
  for (const [platform, spec] of Object.entries(PLATFORM)) {
    const path = `${publishDir}/${spec.filename}`
    console.log(`\n=== ${platform}（${spec.filename}）===`)
    if (!existsSync(path)) {
      console.log('  ❌ 文件缺失——publishing 端取不到字段')
      rc = 1
      continue
    }
    anyFile = true
    for (const [label, fn] of CHECKS) {
      const fails = fn(path, platform)
      if (fails.length > 0) {
        rc = 1
        for (const msg of fails) console.log(`  ❌ ${label}：${msg}`)
      } else {
        console.log(`  ✅ ${label}`)
      }
    }
    // 数字溯源：--facts 给了才跑；没给 = SKIP（纪律 12：SKIP 与 PASS 分列，
    // 把 SKIP 显示成 PASS 就是假绿灯）
    if (facts === undefined) {
      console.log('  ⏭️  数字溯源：SKIP（未给 --facts——没验，不是 PASS）')
    } else {
      const fails = checkFactProvenance(path, platform, facts)
      if (fails.length > 0) {
        rc = 1
        for (const msg of fails) console.log(`  ❌ 数字溯源：${msg}`)
      } else {
        console.log('  ✅ 数字溯源（读者面数字全部对上事实表）')
      }
    }
    // 副信息：标题字数实测
    const sections = splitH2Sections(readText(path))
    let title: string
    if (platform === 'douyin') {
      const tlines = sectionBodyLines('文案', sections)
      title = tlines.length > 0 ? tlines[0]! : ''
    } else {
      const titleH2 = platform === 'xiaohongshu' ? '标题（20 字内）' : '标题'
      const tlines = sectionBodyLines(titleH2, sections)
      title = tlines.length > 0 ? tlines.join(' ') : ''
    }
    if (title !== '') console.log(`  ℹ️  标题实测 ${[...title].length}/${spec.titleMax} 字`)
  }

  // 其它 *.md 文件：WARN（不 FAIL——可能用户加了其它平台，留个口子）
  const known = new Set(Object.values(PLATFORM).map((s) => s.filename))
  const extras = (() => {
    try {
      return readdirSync(publishDir).filter((n) => n.endsWith('.md'))
    } catch {
      return []
    }
  })().filter((n) => !known.has(n)).sort()
  if (extras.length > 0) {
    console.log('\n=== 其它文件（WARN：不在三平台硬约定里）===')
    for (const p of extras) console.log(`  ⚠️  ${p}`)
  }

  if (!anyFile) {
    console.log(`\n❌ publish_dir=${publishDir} 下没有任何已知平台文件`)
    return 1
  }
  console.log(`\n${rc === 0 ? '✅ 全部通过' : '❌ 存在 FAIL，见上'}`)
  return rc
}

export function main(argv: string[]): number {
  let dir: string | undefined
  let facts: Record<string, unknown> | undefined
  let strict = false // 预留：把 WARN 升级为 FAIL
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i]!
    const take = (): string => {
      const v = argv[++i]
      if (v === undefined) throw new FeuilleError(`${t} 缺值`)
      return v
    }
    if (t === '--facts') {
      facts = JSON.parse(readText(take())) as Record<string, unknown>
    } else if (t === '--strict') {
      strict = true
    } else if (t.startsWith('--')) {
      throw new FeuilleError(`未知旗标：${t}`)
    } else if (dir === undefined) {
      dir = t
    } else {
      console.error(USAGE)
      return 2
    }
  }
  if (strict) {
    // Python --strict 是 argparse 预留占位，行为未接——镜像之
  }
  if (dir === undefined) {
    console.error(USAGE)
    return 2
  }
  return checkPublishDir(dir, facts)
}
