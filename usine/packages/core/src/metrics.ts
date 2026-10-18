// metrics.ts — 指标回流（metrics.py 的 TS 移植）：results 合并 / 发布侧检查 /
// 分组分析。
//
// root 与分析维度都参数化；默认维度取 manifest 派生属性。
//
// **没数据留 null 不填 0**：编出来的数据比没有数据更坏——它让后续每个「结论」
// 都建立在虚构样本上。分析器对全 null 台账必须如实说「这不是效果为零，是不知道」。
//
// **部分回填是常态不是异常**：平台后台导出往往只给一部分指标（只有 likes 没有
// views）。筛选必须落在**这一项指标**上（`(e.metrics ?? {}).get(metric)`），
// 不能按「有没有 metrics」筛——否则只回填 likes 时查 views 会在取值处炸。
//
// **样本不足不排名**（MIN_GROUP=5）：一条数据排出来的第一名是最容易骗人的结论形态。
//
// **已发布凭据两级分开判，别合成一个布尔**：合成后 `weak = verifiedBy && verifiedAt`
// 在「有方式没日期」时为假，会掉进「无任何凭据」分支，而真正的「缺核验日期」
// 分支永远走不到。
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
import { join } from "node:path"

import { FeuilleError } from "./errors.js"
import { sortKeysDeep } from "./ledger.js"
import { PLATFORMS } from "./manifest.js"
import type { Json } from "./data.js"

export const LEDGER_NAME = "ledger.json"
export const VERSION = 1

export const COUNT_METRICS = ["views", "likes", "comments", "collects", "shares", "follows"] as const
export const RATE_METRICS = ["completionRate", "interactionRate"] as const
export const ALL_METRICS: readonly string[] = [...COUNT_METRICS, ...RATE_METRICS]
export const MIN_GROUP = 5

// 分析维度默认表：[字段, 标签, 是否分箱]。维度字段应来自 manifest 派生属性。
export type Dim = readonly [string, string, boolean]
export const DEFAULT_DIMS: readonly Dim[] = [
  ["platform", "平台", false],
  ["hook", "钩子形态", false],
  ["locale", "语种", false],
  ["title_chars", "标题字数", true],
  ["topic_count", "话题数", true],
  ["durationSec", "时长", true],
]

const RESULT_FIELDS = ["published", "url", "postId", "publishedAt", "verifiedBy", "verifiedAt"]

export function ledgerPath(root: string): string {
  return join(root, "publish", LEDGER_NAME)
}

export function load(root: string): Json {
  const p = ledgerPath(root)
  if (!existsSync(p)) {
    throw new FeuilleError(`台账不存在：${p}（先构建发布台账）`)
  }
  const doc = JSON.parse(readFileSync(p, "utf8"))
  if (doc["version"] !== VERSION) {
    throw new FeuilleError(
      `台账 schema 版本 ${doc["version"]} != ${VERSION}，请重建`
      + "（字段是 schema 的一部分，旧文件不作猜读）")
  }
  return doc
}

/** Python datetime.now(timezone.utc).isoformat(timespec="seconds") 同款。 */
function utcNowIso(): string {
  return new Date().toISOString().slice(0, 19) + "+00:00"
}

export function save(root: string, doc: Json): void {
  const p = ledgerPath(root)
  mkdirSync(join(p, ".."), { recursive: true })
  doc["updatedAt"] = utcNowIso()
  const tmp = p.replace(/\.json$/, ".json.tmp")
  writeFileSync(tmp, JSON.stringify(sortKeysDeep(doc), null, 1), "utf8")
  renameSync(tmp, p) // 原子换，不留半个台账
}

/** 人工层 results 合并进台账。返回合并条数。
 *
 * results 形如 `{"results": {"<键>": {published/url/…/metrics}}}`。
 * **悬空引用当场报错**：键在台账里没有对应记录 = 那条发布对应的文案/素材
 * 被删了或改名了——不修就合并，会把指标挂到别的发布上。
 */
export function mergeResults(doc: Json, results: Json): number {
  let n = 0
  for (const [key, patch] of Object.entries(results["results"] ?? {}) as [string, Json][]) {
    const e = doc["entries"][key]
    if (e === undefined) {
      throw new FeuilleError(
        `results 里的 '${key}' 在台账里没有对应记录——`
        + "这条发布对应的源被删了或改名了（悬空引用必须先修）")
    }
    for (const field of RESULT_FIELDS) {
      if (field in patch) e[field] = patch[field]
    }
    if (patch["metrics"] && Object.keys(patch["metrics"]).length > 0) e["metrics"] = patch["metrics"]
    n += 1
  }
  return n
}

/** 发布侧检查（问题列表；空 = 通过）。判据取**真实目的**：
 *
 * - 「素材真的在盘上」不是「video 字段非空」；
 * - 「已发布有据可查」不是「必须有 url」——两级凭据（url/postId 强、
 *   verifiedBy+verifiedAt 次）**分开判**；
 * - 「这数是个比率」不是「比率字段存在」——比率折成 0–1，写 12.3% 填 0.123；
 * - 「指标挂在真实发布过的记录上」——没发出去的作品不会有平台数据，
 *   有 = 手工填错了一行。
 */
export function check(doc: Json, root: string): string[] {
  const problems: string[] = []
  const entries = doc["entries"] ?? {}
  if (Object.keys(entries).length === 0) {
    return ["台账一条记录都没有（没构建过？）"]
  }
  for (const key of Object.keys(entries).sort()) {
    const e = entries[key]
    const want = `${e["lesson"] ?? e["lang"] ?? "?"}/${e["locale"] ?? "?"}/${e["platform"] ?? "?"}`
    if (key !== want && "key" in e) { // 键自洽（无 lesson 字段的老条目跳过）
      problems.push(`${key}: 键与字段不自洽`)
    }
    const v = e["video"]
    if (v && !existsSync(join(root, v))) {
      problems.push(`${key}: 视频不在盘上：${v}`)
    }
    if (e["cover"] && !existsSync(join(root, e["cover"]))) {
      problems.push(`${key}: 封面不在盘上：${e["cover"]}`)
    }
    const meta = PLATFORMS[e["platform"] ?? ""]
    if (meta && meta.titleMax && (e["title_chars"] ?? 0) > meta.titleMax) {
      problems.push(
        `${key}: 标题 ${e["title_chars"]} 字 > ${meta.label}上限 ${meta.titleMax}（会被截断）`)
    }
    if (e["published"]) {
      const strong = Boolean(e["url"] || e["postId"])
      if (e["verifiedBy"]) {
        if (!e["verifiedAt"]) {
          problems.push(
            `${key}: 凭据有 verifiedBy 但缺 verifiedAt（核验是哪天做的？半截凭据无法复核）`)
        }
      } else if (!strong) {
        problems.push(
          `${key}: 标了已发布但无任何凭据（要 url/postId，或 verifiedBy+verifiedAt）`)
      }
    }
    const m = e["metrics"]
    // Python 假值语义：空 dict 为假——空 metrics 不算「有效果指标」
    if (m && Object.keys(m).length > 0) {
      for (const [k, val] of Object.entries(m)) {
        if ((COUNT_METRICS as readonly string[]).includes(k)) {
          if (typeof val !== "number" || !Number.isInteger(val) || val < 0) {
            problems.push(`${key}: 指标 ${k}=${JSON.stringify(val)} 不是非负整数`)
          }
        } else if ((RATE_METRICS as readonly string[]).includes(k)) {
          if (typeof val !== "number" || !(0.0 <= val && val <= 1.0)) {
            problems.push(`${key}: 指标 ${k}=${JSON.stringify(val)} 不在 0–1 之间`)
          }
        } else {
          problems.push(`${key}: 未知指标 '${k}'（${ALL_METRICS.join("/")}）`)
        }
      }
    }
    if (m && Object.keys(m).length > 0 && !e["published"]) {
      problems.push(`${key}: 有效果指标但没标已发布——没发出去的作品不会有平台数据`)
    }
  }
  return problems
}

/** 连续值分箱，否则「标题字数」会分成一堆各 1 条的组、一条都排不出。 */
export function bucket(val: unknown): string {
  if (typeof val === "boolean" || typeof val !== "number") {
    return val === null || val === undefined ? "(缺)" : String(val)
  }
  for (const [lo, hi, name] of [[0, 100, "0-100"], [100, 150, "100-150"],
    [150, 200, "150-200"], [200, 300, "200-300"], [300, 10 ** 9, "300+"]] as const) {
    if (lo <= val && val < hi) return name
  }
  return String(val)
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2
}

/** 按维度分组比表现（中位数）。样本不足不排名。返回码 0 正常 / 1 指标名不合法。 */
export function analyze(
  doc: Json,
  metric = "views",
  opts: { minGroup?: number; dims?: readonly Dim[] } = {},
): number {
  const minGroup = opts.minGroup ?? MIN_GROUP
  const dims = opts.dims ?? DEFAULT_DIMS
  if (!ALL_METRICS.includes(metric)) {
    process.stdout.write(`未知指标 '${metric}'；可用：${ALL_METRICS.join("/")}\n`)
    return 1
  }
  // 筛选落在**这一项指标**上（部分回填是常态，见模块头）
  const rows = (Object.values(doc["entries"] ?? {}) as Json[])
    .filter((e) => e["metrics"]?.[metric] !== undefined && e["metrics"]?.[metric] !== null)
  const have = Object.keys(doc["entries"] ?? {}).length
  process.stdout.write("=".repeat(70) + "\n")
  process.stdout.write(`发布回流分析 · 指标 ${metric} · 有指标 ${rows.length}/${have} 条记录\n`)
  process.stdout.write("=".repeat(70) + "\n")
  if (rows.length === 0) {
    process.stdout.write(
      "平台数据尚未回填。台账里 metrics 全是 null——这不是「效果为零」，是「不知道」。\n")
    return 0
  }
  for (const [dim, dimLabel, bucketed] of dims) {
    const groups: Record<string, number[]> = {}
    for (const e of rows) {
      const v = e[dim]
      const key = bucketed ? bucket(v) : String(v)
      ;(groups[key] ??= []).push(e["metrics"][metric])
    }
    const sized = Object.fromEntries(
      Object.entries(groups).filter(([, v]) => v.length >= minGroup))
    const thin = Object.fromEntries(
      Object.entries(groups).filter(([, v]) => v.length < minGroup).map(([k, v]) => [k, v.length]))
    if (Object.keys(sized).length === 0) {
      const ns = Object.values(thin).sort((a, b) => b - a).slice(0, 6)
      process.stdout.write(
        `\n【${dimLabel}】无任何分组达到样本量 ${minGroup}（各组 n：${JSON.stringify(ns)}）→ 不下结论\n`)
      continue
    }
    const ranked = Object.entries(sized)
      .sort((a, b) => median(b[1]) - median(a[1]))
    process.stdout.write(`\n【${dimLabel}】按 ${metric} 中位数（n≥${minGroup}）\n`)
    for (const [k, vals] of ranked) {
      const xs = [...vals].sort((a, b) => a - b)
      process.stdout.write(
        `  ${k.padEnd(14)} n=${String(vals.length).padEnd(3)} 中位 ${median(xs).toFixed(1).padStart(10)}  `
        + `范围 ${xs[0]}–${xs[xs.length - 1]}\n`)
    }
    if (Object.keys(thin).length > 0) {
      const thinSorted: Record<string, number> = {}
      for (const [k, n] of Object.entries(thin).sort((a, b) => b[1] - a[1])) {
        thinSorted[k] = n
      }
      process.stdout.write(`  样本不足未排：${JSON.stringify(thinSorted)}\n`)
    }
  }
  return 0
}
