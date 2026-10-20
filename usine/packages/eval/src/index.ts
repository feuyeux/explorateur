// index.ts — 离线产线健康分 v0（@feuille/eval）。
//
// **这个包为什么存在**：门禁只能证明「没改坏」，证不出「比合并前更好」。RSI 自我
// 进化要的正是后者，于是缺一条**机器可读、确定性**的判据。这个包提供它：一份
// JSON 报告（健康分）+ 一条 compare 语义（improved / regressed / unchanged /
// not-comparable），出现 regressed 即退出码非 0——可以直接当合并闸用。
//
// **它不做什么**：不调 TTS、不开浏览器、不发 HTTP、不烧额度、不改任何既有产物。
// 纯读 + 纯算，报告落盘与否由调用方决定。
//
// **口径一律建在既有模块之上**（纪律 10：不另造平行实现）：
//   locale_matrix     → @feuille/core scene_schema.validateScene（与 `feuille scene
//                       validate` 同一套判据，逐语种跑）+ data.languageManifests
//                       （languages/ 下的 14 个语种注册表）
//   layout_fit        → 无可离线复算的入口 → null（纪律 8）
//   timeline_alignment → 无可离线复算的入口 → null（纪律 8）
//
// **没数据留 null 不填 0**（纪律 8）：null = 不知道，0 = 实测为零。两者在 compare
// 里后果不同——null 一律 not-comparable（不判退化），0 是可判定的实测值。编出来
// 的数据比没有数据更坏：它让后续每个「结论」都建立在虚构样本上。
//
// **样本不足不排名**（纪律 8）：任一侧 samples < MIN_GROUP（沿用 core.metrics 的
// 同一常量）→ not-comparable，不判退化。
//
// **确定性**：同一份输入跑两次，报告逐字节相同——报告里没有时间戳、没有随机数、
// 没有绝对路径；输入版本用**输入内容哈希**（inputs_sha256）标识。
//
// **单文件**：本包的全部代码在这一个文件里。归属门禁（packages/gate）按
// packages/<pkg>/src/**/*.ts（index.ts 除外）记模块 ID，多一个源文件就是多一条
// 归属声明；本包不新建 skill、不改 ownership.json，所以代码只落在这一个桶文件里。
import { createHash } from "node:crypto"
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

import {
  FeuilleError, data, ledger, metrics as coreMetrics, parse_scene, roundHalfEven, scene_schema,
} from "@feuille/core"

/** 报告 schema 版本：字段是 schema 的一部分，版本不同不许互相比较。 */
export const SCHEMA_VERSION = 1

/** v0 的三个指标（先少后多）。 */
export const METRIC_NAMES = ["layout_fit", "timeline_alignment", "locale_matrix"] as const
export type MetricName = (typeof METRIC_NAMES)[number]

/** 指标的好坏方向——compare 靠它判断「变大是变好还是变坏」。不写清楚就不是判据。 */
export type Direction = "lower_is_better" | "higher_is_better"

/** 样本下限：沿用 core.metrics.MIN_GROUP（同一事实源，不另抄一份 5）。 */
export const MIN_GROUP = coreMetrics.MIN_GROUP

export interface HealthMetric {
  /** 指标值；null = 没数据（**不是 0**）。 */
  value: number | null
  /** 量纲（events / rate …）。 */
  unit: string
  /** 样本数：任一侧 < MIN_GROUP 即不排名、不判退化。 */
  samples: number
  /** 好坏方向。 */
  direction: Direction
  /** 口径细节：怎么算的、为什么算不出来、逐项明细。 */
  detail: Record<string, unknown>
}

export interface HealthReport {
  schema_version: number
  /** 输入内容哈希（不含时间戳/路径）：同一份输入 → 同一个哈希。 */
  inputs_sha256: string
  metrics: Record<string, HealthMetric>
}

export interface HealthOptions {
  /** 课例 id（缺省 = lessons/ 下唯一的一课；多于一课时要求显式指定，不猜）。 */
  lessonId?: string
  /** 课例目录（缺省 = 仓库根 lessons/）。 */
  lessonsDir?: string
  /** 语种注册表目录（缺省 = 仓库根 languages/）。 */
  languagesDir?: string
  /** 班底目录（缺省 = 仓库根 personas/）。 */
  personasDir?: string
}

// ================================================================ 输入清单与哈希

interface InputDoc {
  /** 逻辑输入名（稳定、与文件系统路径无关：报告里不许出现绝对路径）。 */
  name: string
  doc: unknown
}

/** 输入内容哈希：逻辑名 + 规范化 JSON（键序无关，走 core.ledger.sortKeysDeep）。
 *
 * **为什么哈希内容而不是路径**：路径会随机器变，内容不会；同一份课例搬到别的
 * 目录，哈希不变——这才是「输入版本」的含义。 */
function inputsSha256(inputs: InputDoc[]): string {
  const h = createHash("sha256")
  for (const f of inputs) {
    h.update(f.name)
    h.update("\0")
    h.update(JSON.stringify(ledger.sortKeysDeep(f.doc)))
    h.update("\n")
  }
  return h.digest("hex")
}

/** 缺省课例：lessons/ 下**恰好一课**时用它；0 课或多课都显式失败，不猜。 */
export function defaultLessonId(lessonsDir?: string): string {
  const ids = parse_scene.findSceneIds(lessonsDir)
  if (ids.length === 1) return ids[0]!
  if (ids.length === 0) {
    throw new FeuilleError(
      "lessons 目录里没有课例（scene.md 存在即算一课）——先建课，或用 --lesson 指定",
    )
  }
  throw new FeuilleError(
    `lessons 目录里有 ${ids.length} 课（${ids.join("、")}）：一次只评一课，用 --lesson 指定是哪一课`,
  )
}

// ================================================================ 指标一：layout_fit

/** 排版「装不下」事件数——**v0 离线算不出来，值留 null**。
 *
 * 查过的既有入口与它们算不出的原因（逐条写进报告，别让「null」变成无话可说）：
 *   poster/fit_diag        溢出旗标 overflowX/overflowY 来自浏览器渲染出的 DIAG 块；
 *                          仓库里没有预渲的 DIAG 产物，本包也不开浏览器。
 *   poster/measure_korean  测墨量要 Chromium 渲染。
 *   poster/audit_charset   判的是**字符子集覆盖**（缺字/tofu），不是「文本装不下」——
 *                          两者不是一回事，不拿它冒充溢出事件。
 *   core/textlayer         Edge headless 截图渲染，需浏览器。
 *
 * 口径纪律：宁可少一个指标，不要编一个（纪律 8）。 */
function layoutFitMetric(): HealthMetric {
  return {
    value: null,
    unit: "events",
    samples: 0,
    direction: "lower_is_better",
    detail: {
      status: "no_offline_entry",
      reason: "无可离线复算的入口：排版「装不下」只在 Edge headless 实测（浏览器渲染出的 "
        + "DIAG 块里带 overflowX/overflowY 旗标），本包零浏览器、仓库内也没有预渲的 DIAG "
        + "产物——按纪律 8 留 null，不拿别的判据（字符子集覆盖）冒充溢出事件。",
      checked_entries: [
        {
          module: "packages/poster/src/fit_diag.ts",
          why_not: "要浏览器渲染出的 DIAG 块；仓库内无此产物，离线不可复算",
        },
        {
          module: "packages/poster/src/measure_korean.ts",
          why_not: "要 Chromium 渲染测墨量",
        },
        {
          module: "packages/poster/src/audit_charset.ts",
          why_not: "判的是字符子集覆盖（缺字/tofu），不是「文本装不下」——口径不同，不冒充",
        },
        {
          module: "packages/core/src/textlayer.ts",
          why_not: "Edge headless 截图渲染，需浏览器",
        },
      ],
      to_become_computable: "离线渲一页（Edge headless）并把 DIAG 块落盘进仓库，"
        + "本指标即可改为统计 DIAG cells 里的溢出旗标",
    },
  }
}

// ================================================================ 指标二：timeline_alignment

/** 词级时间轴对齐误差——**v0 离线算不出来，值留 null**。
 *
 * 查过的既有入口与它们算不出的原因：
 *   core/timeline.enrichLines  行起点要 ffprobe 实测 mp3（仓库内没有音频产物）。
 *   core/timeline.karaokePoints 纯函数，但入参是**词级时间戳**——那些时间戳只存在于
 *                              TTS 产物（core/scene_audio 落的 build/scene/audio/
 *                              scene-<id>_<lc>.timeline.json），仓库内一份都没有。
 *   core/scene_audio            要真调 TTS（额度 + 网络）才能产出词级时间戳。
 *   karaoke/verify_sync         要成片 + 期望帧图（ffmpeg 抓帧 + 像素差）。
 *
 * 唯一带词级时间戳的文件在 examples/ 归档里——那是内容项目的历史产物（AGENTS.md
 * 标注「绝不触碰」），不是本产线的当前产物，拿它算「当前健康」是拿旧账充新账。 */
function timelineAlignmentMetric(): HealthMetric {
  return {
    value: null,
    unit: "seconds",
    samples: 0,
    direction: "lower_is_better",
    detail: {
      status: "no_offline_entry",
      reason: "无可离线复算的入口：词级时间戳只存在于 TTS 产物"
        + "（build/scene/audio/scene-<id>_<lc>.timeline.json），仓库内没有任何词级时间轴"
        + "产物；补齐它要真调 TTS（网络 + 额度）或成片抓帧——本包两者都不做。",
      checked_entries: [
        {
          module: "packages/core/src/timeline.ts",
          why_not: "enrichLines 要 ffprobe 实测音频；karaokePoints 是纯函数但入参是词级时间戳，"
            + "而那些时间戳只在 TTS 产物里",
        },
        {
          module: "packages/core/src/scene_audio.ts",
          why_not: "要真调 TTS 才有词级时间戳（网络 + 额度）",
        },
        {
          module: "packages/karaoke/src/verify_sync.ts",
          why_not: "要成片与期望帧图（ffmpeg 抓帧 + 像素差）",
        },
      ],
      to_become_computable: "把 scene_audio 落的 timeline.json 纳入仓库输入（本指标即可按词级"
        + "时间戳算行内对齐误差），或另立一条「成片 AV 同步」指标",
    },
  }
}

// ================================================================ 指标三：locale_matrix

export interface LocaleRow {
  locale: string
  /** 课例是否覆盖该语种。 */
  covered: boolean
  status: "pass" | "fail" | "not_covered"
  /** 失败原因：逐条取自校验器的原话（可判定，不做语义猜测）。 */
  reasons: string[]
}

/** 把课例收窄到单个语种，好让**同一套 schema 校验**能逐语种跑。
 *
 * 收窄掉的只有「别的语种的数据」（locales / tokenWords / speechLevels / rtlLocales），
 * 与语种无关的结构性判据（顶层字段、token 表、§0.4 roles、§0.5 beats、form）原样
 * 保留——它们在逐语种跑里照样判，只是每个语种都判一遍。
 *
 * polyglot（同台一份剧本）例外：它的台词是共享的，按语种切开会切出假错误，
 * 因此整课例跑一遍，所有语种共用同一份判据。 */
function scopeScene(scene: data.Json, lc: string, shared: boolean): data.Json {
  if (shared) return { ...scene }
  const speechLevels = scene["speechLevels"]
  return {
    ...scene,
    locales: { [lc]: scene["locales"][lc] },
    tokenWords: { [lc]: scene["tokenWords"]?.[lc] },
    // 只在原课例真声明过该语种时才保留条目——原课例没声明 = 没承诺，不该判它「缺 marker」
    speechLevels: speechLevels && lc in speechLevels ? { [lc]: speechLevels[lc] } : undefined,
    rtlLocales: ((scene["rtlLocales"] ?? []) as string[]).filter((x) => x === lc),
  }
}

/** 语种矩阵覆盖/通过率：注册表里每个语种，在课例里跑一遍同一套 schema 校验。
 *
 * 口径：
 *   - 分母 = 语种注册表（languages/ 下 14 个 manifest 目录）——矩阵的集合是注册表
 *     定的，不是课例定的（课例说它覆盖了几个，不说矩阵该有几个）。
 *   - 分子 = 通过的语种数：既被课例覆盖、又跑过校验且零错误。
 *   - 未覆盖的语种算**未通过**（矩阵未覆盖是事实，不是「不知道」——课例里根本没有
 *     这个语种的数据，这是可判定的事实）。
 *   - 跨语种结构错误（任何单语种跑都复现不了的那种）会让所有语种不通过，并单列在
 *     detail.cross_locale_errors——它是整课例的毛病，不该算到某个语种头上。 */
function localeMatrixMetric(input: {
  lessonId: string
  scene: data.Json
  registry: Record<string, data.Json>
  personas: Record<string, data.Json>
  cards: data.Json
}): HealthMetric {
  const locales = Object.keys(input.registry).sort()
  const shared = (input.scene["form"] ?? "dialogue") === "polyglot"
  const rows: LocaleRow[] = []
  const scopedErrors = new Map<string, string[]>()
  for (const lc of locales) {
    const covered = Object.prototype.hasOwnProperty.call(input.scene["locales"] ?? {}, lc)
    if (!covered) {
      rows.push({
        locale: lc,
        covered: false,
        status: "not_covered",
        reasons: ["课例未覆盖该语种（scene.locales 里没有它）"],
      })
      continue
    }
    const errs = scene_schema.validateScene(
      scopeScene(input.scene, lc, shared), input.personas, input.cards,
    )
    scopedErrors.set(lc, errs)
    rows.push({
      locale: lc,
      covered: true,
      status: errs.length > 0 ? "fail" : "pass",
      reasons: errs,
    })
  }

  // 整课例跑一遍：跨语种的结构性错误在这里现形（单语种跑复现不了）
  const fullErrors = scene_schema.validateScene(input.scene, input.personas, input.cards)
  const scopedUnion = new Set([...scopedErrors.values()].flat())
  const crossLocaleErrors = fullErrors.filter((e) => !scopedUnion.has(e))

  let passed = 0
  for (const row of rows) {
    if (row.status === "pass" && crossLocaleErrors.length === 0) passed += 1
  }
  const covered = rows.filter((r) => r.covered).length
  const value = locales.length > 0 ? roundHalfEven(passed / locales.length, 6) : null
  return {
    value,
    unit: "rate",
    samples: locales.length,
    direction: "higher_is_better",
    detail: {
      lesson: input.lessonId,
      validator: "@feuille/core scene_schema.validateScene（与 `feuille scene validate` 同一套判据）",
      registry: `languages/ 语种注册表（${locales.length} 个语种）`,
      covered,
      passed,
      failed: locales.length - passed,
      cross_locale_errors: crossLocaleErrors,
      locales: rows,
    },
  }
}

// ================================================================ 报告

export function computeHealth(opts: HealthOptions = {}): HealthReport {
  const lessonId = opts.lessonId ?? defaultLessonId(opts.lessonsDir)
  const scene = data.sceneDoc(lessonId, opts.lessonsDir)
  const registry = data.languageManifests(opts.languagesDir)
  const personas = data.personas(opts.personasDir)
  const cards = data.cardsDoc(opts.personasDir)
  const inputs: InputDoc[] = [
    { name: "scene.json", doc: scene },
    { name: "personas/personas.json", doc: data.personasDoc(opts.personasDir) },
    { name: "personas/intro-cards.json", doc: cards },
    ...Object.keys(registry).sort().map((lc) => ({
      name: `languages/${lc}/manifest.json`,
      doc: registry[lc],
    })),
  ]
  return {
    schema_version: SCHEMA_VERSION,
    inputs_sha256: inputsSha256(inputs),
    metrics: {
      layout_fit: layoutFitMetric(),
      timeline_alignment: timelineAlignmentMetric(),
      locale_matrix: localeMatrixMetric({ lessonId, scene, registry, personas, cards }),
    },
  }
}

/** 报告的规范文本（落盘 / 打印用它）：键序固定，缩进 2 空格，行尾换行。 */
export function reportText(report: HealthReport): string {
  return JSON.stringify(report, null, 2) + "\n"
}

// ================================================================ compare

export type Verdict = "improved" | "regressed" | "unchanged" | "not-comparable"

export interface MetricComparison {
  metric: string
  verdict: Verdict
  /** 判据说明：为什么是这个结论（人可读、可复核）。 */
  reason: string
  unit: string
  direction: Direction
  baseline: number | null
  candidate: number | null
  baseline_samples: number
  candidate_samples: number
}

export interface CompareResult {
  schema_version: number
  metrics: MetricComparison[]
  improved: string[]
  regressed: string[]
  unchanged: string[]
  not_comparable: string[]
  /** 0 = 无退化；1 = 有退化（合并闸的判据）。 */
  exit_code: number
}

function fmt(v: number | null): string {
  return v === null ? "null" : String(v)
}

/** 单指标比较。
 *
 * 判定顺序（语义不许含糊）：
 *   1. 一方缺这个指标 → not-comparable；
 *   2. 任一方值是 null → not-comparable（不知道 ≠ 退化，纪律 8）；
 *   3. 任一方样本 < MIN_GROUP → not-comparable（样本不足不排名，纪律 8）；
 *   4. 两侧口径方向不同 → not-comparable（方向都变了，数值不可比）；
 *   5. 否则按方向比大小：变好 improved / 变坏 regressed / 一样 unchanged。 */
export function compareMetric(
  name: string,
  baseline: HealthMetric | undefined,
  candidate: HealthMetric | undefined,
): MetricComparison {
  const base: MetricComparison = {
    metric: name,
    verdict: "not-comparable",
    reason: "",
    unit: baseline?.unit ?? candidate?.unit ?? "",
    direction: baseline?.direction ?? candidate?.direction ?? "lower_is_better",
    baseline: baseline?.value ?? null,
    candidate: candidate?.value ?? null,
    baseline_samples: baseline?.samples ?? 0,
    candidate_samples: candidate?.samples ?? 0,
  }
  if (!baseline || !candidate) {
    return { ...base, reason: "一方报告里没有这个指标——不判退化" }
  }
  if (baseline.value === null || candidate.value === null) {
    return { ...base, reason: "值是 null：不知道，不是「零」——不判退化（纪律 8）" }
  }
  const minSamples = Math.min(baseline.samples, candidate.samples)
  if (minSamples < MIN_GROUP) {
    return { ...base, reason: `样本不足（${minSamples} < ${MIN_GROUP}）：不排名、不判退化（纪律 8）` }
  }
  if (baseline.direction !== candidate.direction) {
    return { ...base, reason: "两侧口径方向不同（lower_is_better vs higher_is_better）——数值不可比" }
  }
  const lowerBetter = baseline.direction === "lower_is_better"
  const word = lowerBetter ? "越低越好" : "越高越好"
  const tail = `${fmt(baseline.value)} → ${fmt(candidate.value)}（${word}）`
  if (candidate.value === baseline.value) {
    return { ...base, verdict: "unchanged", reason: `两值相同：${tail}` }
  }
  const better = lowerBetter ? candidate.value < baseline.value : candidate.value > baseline.value
  return {
    ...base,
    verdict: better ? "improved" : "regressed",
    reason: `${better ? "变好" : "变坏"}：${tail}`,
  }
}

/** 逐指标比较两份报告。任一指标 regressed → exit_code = 1（合并闸的判据）。 */
export function compareReports(baseline: HealthReport, candidate: HealthReport): CompareResult {
  const names = [...new Set([
    ...Object.keys(baseline.metrics ?? {}),
    ...Object.keys(candidate.metrics ?? {}),
  ])].sort()
  const metrics = names.map((n) => compareMetric(n, baseline.metrics?.[n], candidate.metrics?.[n]))
  const pick = (v: Verdict): string[] => metrics.filter((m) => m.verdict === v).map((m) => m.metric)
  const regressed = pick("regressed")
  return {
    schema_version: SCHEMA_VERSION,
    metrics,
    improved: pick("improved"),
    regressed,
    unchanged: pick("unchanged"),
    not_comparable: pick("not-comparable"),
    exit_code: regressed.length > 0 ? 1 : 0,
  }
}

// ================================================================ CLI

export function usage(): string {
  return [
    "用法：feuille-eval <命令> [参数…]",
    "",
    "  health   算健康分，JSON 打到 stdout",
    "          [--lesson <id>] [--lessons DIR] [--languages DIR] [--personas DIR]",
    "          [--out <file.json>]",
    "  compare  逐指标比两份报告；任一指标 regressed → 退出码 1",
    "          --baseline <a.json> --candidate <b.json> [--json]",
    "",
  ].join("\n")
}

/** argparse 同款取值：`--k v` 与 `--k=v` 都收，重复旗标后者覆盖。 */
function argValue(argv: string[], flag: string): string | undefined {
  const i = argv.lastIndexOf(flag)
  if (i >= 0 && argv[i + 1] !== undefined) return argv[i + 1]
  const p = `${flag}=`
  for (let j = argv.length - 1; j >= 0; j--) {
    const a = argv[j]!
    if (a.startsWith(p)) return a.slice(p.length)
  }
  return undefined
}

function readReport(path: string): HealthReport {
  let raw: string
  try {
    raw = readFileSync(path, "utf8")
  } catch (e) {
    throw new FeuilleError(`报告读不了：${path}（${String(e)}）`)
  }
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    throw new FeuilleError(`报告不是合法 JSON：${path}（${String(e)}）`)
  }
  if (doc === null || typeof doc !== "object") {
    throw new FeuilleError(`报告内容不是对象：${path}`)
  }
  return doc as HealthReport
}

function printCompare(result: CompareResult): void {
  for (const m of result.metrics) {
    const line = [
      m.metric.padEnd(18),
      m.verdict.padEnd(15),
      `${fmt(m.baseline)} → ${fmt(m.candidate)}`.padEnd(24),
      `样本 ${m.baseline_samples}/${m.candidate_samples}`.padEnd(12),
      m.reason,
    ].join(" ")
    process.stdout.write(line + "\n")
  }
  process.stdout.write(
    `结论：regressed ${result.regressed.length} · improved ${result.improved.length}`
    + ` · unchanged ${result.unchanged.length} · not-comparable ${result.not_comparable.length}`
    + ` → 退出码 ${result.exit_code}\n`,
  )
}

/** CLI 入口。返回退出码（0 正常 / 1 有退化 / 2 用法或输入错）。 */
export function main(argv: string[] = process.argv.slice(2)): number {
  const [cmd, ...rest] = argv
  if (!cmd || cmd === "-h" || cmd === "--help" || cmd === "help") {
    process.stdout.write(usage())
    return 0
  }
  try {
    if (cmd === "health") {
      const out = argValue(rest, "--out")
      const report = computeHealth({
        lessonId: argValue(rest, "--lesson"),
        lessonsDir: argValue(rest, "--lessons"),
        languagesDir: argValue(rest, "--languages"),
        personasDir: argValue(rest, "--personas"),
      })
      const text = reportText(report)
      if (out) {
        writeFileSync(out, text, "utf8")
        process.stderr.write(`已写 ${out}\n`)
        return 0
      }
      process.stdout.write(text)
      return 0
    }
    if (cmd === "compare") {
      const basePath = argValue(rest, "--baseline")
      const candPath = argValue(rest, "--candidate")
      if (!basePath || !candPath) {
        process.stderr.write("usage: feuille-eval compare --baseline <a.json> --candidate <b.json>\n")
        return 2
      }
      const baseline = readReport(basePath)
      const candidate = readReport(candPath)
      if (baseline.schema_version !== candidate.schema_version) {
        process.stderr.write(
          `报告 schema 版本不同（${String(baseline.schema_version)} vs `
          + `${String(candidate.schema_version)}）——字段是 schema 的一部分，拒绝比较\n`,
        )
        return 2
      }
      const result = compareReports(baseline, candidate)
      if (rest.includes("--json")) {
        process.stdout.write(JSON.stringify(result, null, 2) + "\n")
      } else {
        printCompare(result)
      }
      return result.exit_code
    }
    process.stderr.write(`未知命令：${cmd}\n\n${usage()}`)
    return 2
  } catch (e) {
    if (e instanceof FeuilleError) {
      process.stderr.write(`${e.message}\n`)
      return 1
    }
    throw e
  }
}

// ESM 入口判定：作为脚本直跑时执行；被 import（测试/库调用）时不执行。
const invokedAs = process.argv[1] ? pathToFileURL(process.argv[1]).href : ""
if (invokedAs === import.meta.url) {
  process.exit(main(process.argv.slice(2)))
}
