// manifest.ts — 发布清单（manifest.py 的 TS 移植）：文案稿解析 / 平台限制检查 /
// 标注回填 / 清单构建。
//
// 体例（机器可解析，人写可 diff）；节头的时长字段可选：
//
//     ### 01 · 英语 `en-US` · 00:52 [· ✅ 已发布]      ← 时长与已发布标记可选
//     **标题**（20 字）                                  ← 括号标注会被 fillAnnotations
//     ```                                                  按 len() 实测回填
//     四种语言聊颜色｜第01话 …
//     ```
//     **正文**（154 / 1000）
//     ```
//     …（小红书的末行是话题，会被解析进 topics）
//     ```
//     **话题**
//     ```
//     #语言学习 #多语言对比
//     ```
//     源文件：`build/scene/scene-colors_en-US.mp4`
//
// 铁律（纪律 7 的机制化）：
// - **属性一律派生**：titleChars / bodyChars / topicCount / hook 全部现算
//   （手标字数实测全错过）。
// - **素材存在性前置**：视频 / 封面**真实在盘**才算清单齐（发到一半发现文件缺失
//   是最贵的失败方式，卡在 build 阶段最便宜）。
// - hook 分类**可判定、可复现**，不做语义猜测：emoji × question 两个特征交叉
//   （抖音=question、小红书=emoji+question——压成一维会把两个变量混进一个结论）。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { basename, dirname } from "node:path"

import { FeuilleError } from "./errors.js"

// ---------------------------------------------------------------- 平台约束
// 写成数据不是 if/else：加平台 = 加一行。B 站 80 是手测口径。
export interface PlatformMeta {
  label: string
  titleMax: number
  bodyMax: number | null
  hook: string | null
  /** 知乎是长文一篇，不走逐支模板 */
  copy?: null
}

export const PLATFORMS: Record<string, PlatformMeta> = {
  douyin: { label: "抖音", titleMax: 30, bodyMax: 1000, hook: "question" },
  xiaohongshu: { label: "小红书", titleMax: 20, bodyMax: 1000, hook: "emoji+question" },
  bilibili: { label: "哔哩哔哩", titleMax: 80, bodyMax: null, hook: null },
  zhihu: { label: "知乎", titleMax: 100, bodyMax: null, hook: null, copy: null },
}

// ---------------------------------------------------------------- 文案解析

// 时长字段可选：完整体例带 `· MM:SS [· ✅ 已发布]`，最简只到 `locale`。
const SEC = /^###\s+(\d+)\s*·\s*(\S+)\s*`([^`]+)`(?:\s*·\s*(\d\d):(\d\d))?(.*)$/
const FENCE = /\*\*(标题|正文|话题)\*\*[^\n]*\n```\n(.*?)\n```/s
const TOPICS = /(?:^|\s)#([^\s#]+)/gm
const ANN = /^\*\*(标题|正文)\*\*（([^）]*)）$/
const SENT_END = /[。！？!?]/
const EMOJI_RANGES: readonly (readonly [number, number])[] = [
  [0x1f000, 0x1faff], [0x2600, 0x27bf], [0x2b00, 0x2bff],
  [0x2190, 0x21ff], [0xfe0f, 0xfe0f],
]

export function isEmoji(ch: string): boolean {
  /** 码位区间判定。**不能写成 `ch in "🎰-🫿…"`**——那是「这个字符是不是字符串里
   * 某一个字」的成员测试，`🎨` 不等于任何单个字符，于是永远 False（坑㉲）。 */
  const cp = ch.codePointAt(0)!
  return EMOJI_RANGES.some(([lo, hi]) => lo <= cp && cp <= hi)
}

/** 首句（到第一个句读为止）。取首句不取首行：抖音正文一整行三句话，
 * 按行切会把问句钩子判成陈述句——判据必须对齐钩子的定义。 */
function firstSentence(body: string): string {
  const text = body.split("\n").map((ln) => ln.trim()).find((ln) => ln !== "") ?? ""
  const m = SENT_END.exec(text)
  return m ? text.slice(0, m.index + m[0].length) : text
}

/** 正文首句形态：emoji × question 两特征交叉，可判定、可复现，不做语义猜测。 */
export function hookShape(body: string): string {
  const first = firstSentence(body)
  if (!first) return "empty"
  // JS 的 first[0] 对 astral 字符只取到半个代理对（Python first[0] 是整字）——
  // 必须按码位取首字符。
  const emoji = isEmoji([...first][0]!)
  const question = first.endsWith("？") || first.endsWith("?")
  if (emoji && question) return "emoji+question"
  if (question) return "question"
  if (emoji) return "emoji"
  return "statement"
}

export interface CopyRecord {
  order: number
  lang: string
  locale: string
  durationSec: number | null
  publishedMark: boolean
  source: string | null
  title: string
  body: string
  topics: string[]
  titleChars: number
  bodyChars: number
  topicCount: number
  hook: string
}

/** `{plat}-copy.md` → 每支一条记录。**只抽取，不改写。**
 *
 * 缺标题或正文块 = 体例被改了 → 当场报错（宁可拒解析，不做静默降级）。
 * 属性全派生：titleChars / bodyChars / topics / hook 现算，不信任何手标。
 */
export function parseCopy(path: string): CopyRecord[] {
  if (!existsSync(path)) {
    throw new FeuilleError(`文案事实源不存在：${path}`)
  }
  const lines = readFileSync(path, "utf8").split("\n")
  const out: CopyRecord[] = []
  let i = 0
  while (i < lines.length) {
    const m = SEC.exec(lines[i]!)
    if (!m) {
      i += 1
      continue
    }
    const [, orderS, lang, locale, mm, ss, tail] = m
    const cur: Omit<CopyRecord, "title" | "body" | "topics" | "titleChars"
      | "bodyChars" | "topicCount" | "hook"> = {
      order: Number(orderS),
      lang: lang!,
      locale: locale!,
      durationSec: mm ? Number(mm) * 60 + Number(ss) : null,
      publishedMark: (tail ?? "").includes("已发布"),
      source: null,
    }
    const chunks: Record<string, string> = {}
    let j = i + 1
    while (j < lines.length && !lines[j]!.startsWith("### ")) {
      const fm = FENCE.exec(lines.slice(j).join("\n") + "\n")
      if (fm && !(fm[1]! in chunks)) {
        chunks[fm[1]!] = fm[2]!
        j += fm[0].split("\n").length
        continue
      }
      if (lines[j]!.startsWith("源文件：")) {
        const t = lines[j]!.split("`")[1]
        cur.source = t && t !== "" ? t : null
      }
      j += 1
    }
    // 话题：小红书把话题放正文末行，抖音是独立 **话题** 块——同一真实目的
    //（发出去得有话题），两种来源都收进 topics。
    const topicsSrc = chunks["话题"] ?? chunks["正文"] ?? ""
    const topics = [...topicsSrc.matchAll(TOPICS)].map((t) => t[1]!)
    const title = chunks["标题"]
    const body = chunks["正文"]
    if (title === undefined || body === undefined) {
      throw new FeuilleError(
        `${basename(path)} 第 ${cur.order} 支缺标题或正文块（体例被改了？）`)
    }
    out.push({
      ...cur,
      title,
      body,
      topics,
      // 派生属性（纪律 7：一律现算）
      titleChars: [...title].length,
      bodyChars: [...body].length,
      topicCount: topics.length,
      hook: hookShape(body),
    })
    i = j
  }
  return out
}

/** 平台限制检查（问题列表；空 = 通过）。
 *
 * expect：该平台应有条数（缺支/多支都报——「12 条齐」本身是发布一致性的一部分）。
 */
export function checkCopy(path: string, platform: string, opts: { expect?: number } = {}): string[] {
  const recs = parseCopy(path)
  const meta = PLATFORMS[platform]
  if (meta === undefined) {
    throw new FeuilleError(`未知平台：${platform}（合法：${Object.keys(PLATFORMS).join(" / ")}）`)
  }
  const problems: string[] = []
  const where = basename(path)
  if (opts.expect !== undefined && recs.length !== opts.expect) {
    problems.push(`${where}: 条数 ${recs.length} ≠ ${opts.expect}`)
  }
  for (const r of recs) {
    const tag = `${where} ${String(r.order).padStart(2, "0")} ${r.lang}`
    if (r.titleChars > meta.titleMax) {
      problems.push(`${tag}: 标题 ${r.titleChars} > ${meta.titleMax} 字（会被截断）`)
    }
    if (meta.bodyMax !== null && r.bodyChars > meta.bodyMax) {
      problems.push(`${tag}: 正文 ${r.bodyChars} > ${meta.bodyMax}`)
    }
    if (r.topics.length === 0) {
      problems.push(`${tag}: 无话题`)
    }
    if (meta.hook !== null && r.hook !== meta.hook) {
      problems.push(`${tag}: 钩子 ${r.hook} ≠ 约定 ${meta.hook}`)
    }
  }
  return problems
}

/** 把 `**标题**（N 字）` / `**正文**（N / 1000）` 标注改成 len() 实测值。
 *
 * 字数必须来自解析出的整块 `len()`——数代码块首行是错的（首行只是一句话，
 * --fix 早期版本标过 17 而实际正文 117）。返回改写处数。
 */
export function fillAnnotations(path: string, recs: CopyRecord[]): number {
  const byOrder = new Map(recs.map((r) => [r.order, r]))
  const lines = readFileSync(path, "utf8").split("\n")
  let changed = 0
  let cur: CopyRecord | undefined
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i]!
    const m = SEC.exec(ln)
    if (m) {
      cur = byOrder.get(Number(m[1]))
      continue
    }
    const a = ANN.exec(ln)
    if (!a || cur === undefined) continue
    const kind = a[1]!
    const want = kind === "标题"
      ? `**${kind}**（${cur.titleChars} 字）`
      : `**${kind}**（${cur.bodyChars} / 1000）`
    if (ln !== want) {
      lines[i] = want
      changed += 1
    }
  }
  if (changed > 0) {
    writeFileSync(path, lines.join("\n"), "utf8")
  }
  return changed
}

export interface ManifestTask {
  no: number
  lang: string
  locale: string
  title: string
  body: string
  tags: string[]
  video: string
  cover: string
}

export interface ManifestPlan {
  copy: string
  entries?: CopyRecord[]
  video: (r: CopyRecord) => string
  cover: (r: CopyRecord) => string
  tags?: (r: CopyRecord) => string[]
}

/** 文案 + 素材 → 结构化发布清单（素材存在性前置校验）。
 *
 * plans: {platform: plan}。返回 (manifest, problems)。
 * **素材不存在 = 清单不齐**：宁可现在报，不发到一半才发现文件缺失。
 * outPath 给了就落盘（indent=1，键序保持插入序——与 Python json.dumps 一致）。
 */
export function buildManifest(
  plans: Record<string, ManifestPlan>,
  outPath?: string,
): [Record<string, ManifestTask[]>, string[]] {
  const manifest: Record<string, ManifestTask[]> = {}
  const problems: string[] = []
  for (const [plat, cfg] of Object.entries(plans)) {
    const recs = cfg.entries ?? parseCopy(cfg.copy)
    const tasks: ManifestTask[] = []
    for (const r of recs) {
      const video = cfg.video(r)
      const cover = cfg.cover(r)
      const tags = cfg.tags ? cfg.tags(r) : r.topics
      const t: ManifestTask = {
        no: r.order, lang: r.lang, locale: r.locale,
        title: r.title, body: r.body, tags,
        video, cover,
      }
      if (!r.title) problems.push(`${plat} ${r.lang}: 标题为空`)
      if (!r.body) problems.push(`${plat} ${r.lang}: 正文为空`)
      if (tags.length === 0) problems.push(`${plat} ${r.lang}: 话题为空`)
      if (!existsSync(video)) problems.push(`${plat} ${r.lang}: 视频缺失 ${video}`)
      if (!existsSync(cover)) problems.push(`${plat} ${r.lang}: 封面缺失 ${cover}`)
      tasks.push(t)
    }
    manifest[plat] = tasks
  }
  if (outPath !== undefined) {
    mkdirSync(dirname(outPath), { recursive: true })
    writeFileSync(outPath, JSON.stringify(manifest, null, 1), "utf8")
  }
  return [manifest, problems]
}
