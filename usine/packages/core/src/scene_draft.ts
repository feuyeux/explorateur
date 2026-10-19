// scene_draft.ts — 教学创意 → lessons/<id>/scene.md 草稿生成环节
// （scene_draft.py 的 TS 移植）
//
// 注册表现取 feuille 渲染线本体（rig / devices，与 scene_schema 同一份——单一
// 事实源，不抄名单）；输出路径由 --brief 的同目录推导，无模块级路径常量。
// 语种 / 班底数据可指目录：langs 与 mainDraft 带 languages / personas 参数。
//
// 使用契约：`render(brief, personas, cards, langs, reg)` 纯函数生成全文（一个字的
// 内容都不生成，只填结构）；落盘前拒覆盖已定稿文件（frontmatter 无 `draft: true`
// 标记必须 --force）；`--gaps` 只数 TODO 欠账不生成。
//
// **分工**：本模块只生成**结构**，一个字的内容都不生成——台词、词表词义、舞台
// 描述留 TODO 给作者。事实源全部现取：引号对与语种名来自 languages/<locale>/
// manifest.json，选角来自 personas.json × intro-cards.json 的 cast 表，情绪/姿态/
// 装置样式的合法取值来自渲染线注册表（姿态码先过 parse_scene.normPose 再查注册
// 表——md 体例里写 `jump-celebrate`，解析器会归一成 `jump_celebrate`）。
//
// 错误通道与 Python 同构：本模块的失败全是「作者可修的输入问题」→ FeuilleError；
// 输入坏到 Python 会 KeyError/TypeError 崩溃的（缺 lines 键、style 缺失混排），
// 这里同样抛裸错——两层通道不混。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"

import { argValue } from "./argv.js"
import { cardsDoc, languageManifests, personas } from "./data.js"
import { DEVICE_STYLES } from "./devices.js"
import { FeuilleError } from "./errors.js"
import { MOOD_FACE, POSE_CODES } from "./rig.js"
import { normPose } from "./parse_scene.js"

type Json = any

export const TODO = "TODO"

// 草稿落盘时必须带这个标记，否则下次运行会被 --force 拒掉。
export const DRAFT_MARK = "draft: true"

// Python str(list[str]) 口径：单引号、逗号加空格——错误信息里的名单照此渲染
// （f"{bad}" 走的就是这条通道）。
function pyStrList(arr: (string | null)[]): string {
  return `[${arr.map((s) => (s === null ? "None" : `'${s}'`)).join(", ")}]`
}

/** Python `if d` 口径：null / 空串 / 0 / false / 空对象为假（空 dict 也跳过）。 */
function pyFalsy(v: Json): boolean {
  return (
    v == null || v === "" || v === 0 || v === false
    || (typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0)
  )
}

/** Python `k in d` 口径：键存在即真（值假也算）。 */
function has(obj: Json, k: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, k)
}


// ---------------------------------------------------------------- 语言 / 班底事实源

/** languages 目录 → {locale: manifest}；空目录 = 还没建语种注册表 → 显式失败。 */
export function langs(languagesDir?: string): Record<string, Json> {
  const m = languageManifests(languagesDir)
  if (!Object.keys(m).length) {
    throw new FeuilleError(
      "语种目录为空：先建 languages/<locale>/manifest.json（见 languages/README.md）")
  }
  return m
}

export interface Registries {
  moods: Set<string>
  poses: Set<string>
  deviceStyles: Set<string>
}

/** 情绪 / 姿态 / 装置样式的合法取值——从渲染线现取，避免本模块硬编码一份。 */
export function registries(): Registries {
  return {
    moods: new Set(Object.keys(MOOD_FACE)),
    poses: new Set([...POSE_CODES].map(normPose).concat(["bounce_in"])),
    deviceStyles: new Set(Object.keys(DEVICE_STYLES)),
  }
}

/** locale → {role: native 姓名}。班底里该语种的 A/B 各一人（scene_schema 第 7 组在守）。 */
export function castFor(locale: string, personas: Record<string, Json>, cards: Json): Record<string, string> {
  const out: Record<string, string> = {}
  for (const role of ["A", "B"] as const) {
    const cast = (cards["cast"] ?? {}) as Record<string, string>
    const ids = Object.entries(personas)
      .filter(([pid, p]) => p["locale"] === locale && cast[pid] === role)
      .map(([pid]) => pid)
    if (ids.length !== 1) {
      throw new FeuilleError(
        `${locale} ${role} 角选派异常：${ids.length ? pyStrList(ids) : "班底里没有该 locale 的人"}`
        + "——先补 personas.json / intro-cards.json")
    }
    out[role] = personas[ids[0]!]["name"]["native"]
  }
  return out
}


// ---------------------------------------------------------------- 骨架展开

export interface Beat {
  beat: string
  from: number
  to: number
  count: number
  ask: string
  askBy: string
  relFrom: boolean
  relTo: boolean
}

/** 骨架行数规格 → Beat[]，边界用 `n-K` 记法（relFrom/relTo 标记）。
 *
 * `lines: "rest"` = 吸收其余全部行：作者只写「开场 1 行、来回 N 轮、收 3 行」，
 * 边界要不要写成 `n-K` 看它**依不依赖各语种的台词行数 n**：rest 之前起止写死、
 * rest 本身起点写死终点 n-K、rest 之后起止都 n-K——否则某语种多写一行台词，
 * apply_beats 就会抛「有 1 行未被任何节拍覆盖」，病因在几百行外。
 */
export function expandSkeleton(skeleton: Json[], n?: number | null): Beat[] {
  const rest = skeleton.filter((s) => s["lines"] === "rest")
  if (rest.length > 1) {
    throw new FeuilleError(`骨架里只能有一个 rest，实得 ${pyStrList(rest.map((s) => s["beat"]))}`)
  }
  // Python int(s["lines"])：缺键 = KeyError 崩溃（非 FeuilleError），小数截断
  const linesOf = (s: Json): number => {
    if (!has(s, "lines")) throw new Error("KeyError: 'lines'")
    return Math.trunc(Number(s["lines"]))
  }
  const fixed = skeleton.filter((s) => s["lines"] !== "rest").reduce((a, s) => a + linesOf(s), 0)
  const total = n ?? null
  if (!rest.length && total === null) {
    throw new FeuilleError("骨架没有 rest 项，必须给出总行数 n")
  }
  let plan: Json[]
  if (rest.length) {
    // 条件与文案按原样镜像：rest 在场且未给 n 时触发（文案说「不需要再给」，
    // 实际这时必须给——rest_n 得靠 total 减出来）。
    if (total === null) {
      throw new FeuilleError("骨架含 rest 项时不需要再给 n")
    }
    const restN = total - fixed
    if (restN < 1) {
      throw new FeuilleError(`骨架行数超了：rest 只剩 ${restN} 行（总 ${total} - 固定 ${fixed}）`)
    }
    plan = skeleton.map((s) => ({ beat: s["beat"], count: s["lines"] !== "rest" ? linesOf(s) : restN, s }))
  } else {
    if (total !== null && total !== fixed) {
      throw new FeuilleError(`n=${total} 与骨架各节之和 ${fixed} 不一致`)
    }
    plan = skeleton.map((s) => ({ beat: s["beat"], count: linesOf(s), s }))
  }

  const out: Beat[] = []
  let i = 0
  const restAt = skeleton.findIndex((s) => s["lines"] === "rest")
  for (const [k, p] of plan.entries()) {
    const relTo = restAt !== -1 && k >= restAt
    const relFrom = restAt !== -1 && k > restAt
    out.push({
      beat: p["beat"], from: i, to: i + p["count"] - 1, count: p["count"],
      ask: p["s"]["ask"] ?? "-", askBy: p["s"]["askBy"] ?? "-",
      relFrom, relTo,
    })
    i += p["count"]
  }
  return out
}

/** §0.5 节拍表：随 n 变化的边界一律用 `n-K`。 */
export function beatTableMd(beats: Beat[], n: number): string {
  const rows = ["| beat | from | to | ask | askBy |", "| --- | --- | --- | --- | --- |"]
  for (const b of beats) {
    const frm = b.relFrom ? `n-${n - b.from}` : String(b.from)
    const to = b.relTo ? `n-${n - b.to}` : String(b.to)
    rows.push(`| ${b.beat} | ${frm} | ${to} | ${b.ask} | ${b.askBy} |`)
  }
  return rows.join("\n")
}

/** 节拍内取值：字符串 = 整节同一个；列表 = 按行偏移逐行给。 */
function at(spec: Json, offset: number, fallback?: Json): Json {
  if (spec == null) return fallback
  if (Array.isArray(spec)) return offset < spec.length ? spec[offset] : fallback
  return spec
}

export interface LinePlan {
  i: number
  beat: string
  speaker: string
  mood: string
  pose: string
  isQuestion: boolean
}

/** 骨架 → 每行的 {speaker, mood, pose, isQuestion}。规则与 parse_scene.applyBeats
 * 对齐：非问句节整节同一说话人；问句节按 ask 奇偶发问，另一行给对方；问句节可
 * 用 .moodAsk/.moodReply、.poseAsk/.poseReply 覆盖整节取值。 */
export function assignLines(beats: Beat[], spec: Json): LinePlan[] {
  const pick = (beat: string, kind: string, q: boolean): Json => {
    // 问句行优先取 Ask 变体、答话行取 Reply 变体；没给就退回整节取值
    const key = q ? `${beat}.${kind}Ask` : `${beat}.${kind}Reply`
    let v = spec[key]
    if (v == null) v = spec[`${beat}.${kind}`]
    return v
  }

  const lines: LinePlan[] = []
  for (const b of beats) {
    const ask = b.ask
    const isAsk = ask === "even" || ask === "odd"
    for (let i = b.from; i <= b.to; i++) {
      const off = i - b.from
      let sp: string, mood: Json, pose: Json
      if (isAsk) {
        const q = (i % 2 === 0) === (ask === "even")
        sp = q ? b.askBy : (b.askBy === "A" ? "B" : "A")
        mood = at(pick(b.beat, "mood", q), off, "neutral")
        pose = at(pick(b.beat, "pose", q), off, "")
      } else {
        sp = at(spec[`${b.beat}.speakers`], off, "A")
        mood = at(spec[`${b.beat}.mood`], off, "neutral")
        pose = at(spec[`${b.beat}.pose`], off, "")
      }
      lines.push({
        i, beat: b.beat, speaker: sp, mood,
        pose: pose || "",
        isQuestion: isAsk && ((i % 2 === 0) === (ask === "even")),
      })
    }
  }
  return lines
}


// ---------------------------------------------------------------- 各节渲染

function mdTable(header: string[], rows: Json[][]): string {
  const out = [
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
  ]
  for (const r of rows) out.push(`| ${r.map((c) => String(c)).join(" | ")} |`)
  return out.join("\n")
}

/** brief → scene.md 全文。 */
export function render(
  brief: Json, personas: Record<string, Json>, cards: Json,
  langs: Record<string, Json>, reg: Registries,
): string {
  const sid = brief["sceneId"]
  const locales = brief["locales"] as string[]
  const unknown = locales.filter((l) => !(l in langs))
  if (unknown.length) {
    throw new FeuilleError(`没有语种目录：${pyStrList(unknown)}（先建 languages/<loc>/manifest.json）`)
  }

  const n = brief["lines"] ?? null
  const beats = expandSkeleton(brief["skeleton"], n)
  const nLines = beats.reduce((a, b) => a + b.count, 0)
  if (nLines < 2) {
    throw new FeuilleError(`骨架只展开出 ${nLines} 行台词，parse_locales 要求 ≥2`)
  }

  const spec = brief["spec"] ?? {}
  const plan = assignLines(beats, spec)

  const codes = new Set<string>()
  for (const ln of plan) {
    for (const c of String(ln.pose || "").split(" ").filter(Boolean)) codes.add(normPose(c))
  }
  let bad = [...codes].filter((c) => !reg.poses.has(c)).sort()
  if (bad.length) {
    throw new FeuilleError(`brief 里的姿态 ${pyStrList(bad)} 不在 POSE_CODES 注册表内（渲染会炸）`)
  }
  bad = [...new Set(plan.map((l) => String(l.mood)))].filter((m) => !reg.moods.has(m)).sort()
  if (bad.length) {
    throw new FeuilleError(`brief 里的情绪 ${pyStrList(bad)} 不在 MOOD_FACE 内（渲染会炸）`)
  }
  // Python {d.get("style") for d in devices.values() if d}：集合可含 None——
  // None 混排字符串时 sorted() 抛 TypeError，原样镜像崩溃通道；单 None 则进
  // 报错名单（印作 None）。
  const styles = new Set<string | null>()
  for (const d of Object.values((brief["devices"] ?? {}) as Record<string, Json>)) {
    if (!pyFalsy(d)) styles.add(d["style"] ?? null)
  }
  const badStyles = [...styles].filter((s) => s === null || !reg.deviceStyles.has(s))
  if (badStyles.includes(null) && badStyles.length > 1) {
    throw new TypeError("'<' not supported between instances of 'NoneType' and 'str'")
  }
  if (badStyles.length) {
    throw new FeuilleError(
      `brief 里的装置 style ${pyStrList(badStyles.slice().sort() as (string | null)[])}`
      + " 不在 DEVICE_STYLES 注册表内")
  }

  const L: string[] = []
  L.push("---")
  L.push('type: "Content"')
  L.push(`title: "${brief["title"]}"`)
  L.push(`description: "${brief["description"] ?? ""}"`)
  L.push("tags: [content, scene, teaching-video]")
  L.push(`generated: { by: scene_draft, ${DRAFT_MARK} }`)
  L.push("---")
  L.push("")
  L.push(`# ${brief["title"]}`)
  L.push("")
  L.push(`> **学习目标**：${brief["goal"] ?? TODO}`)
  L.push(`> **结构**：${brief["structure"] ?? TODO}`)
  L.push(`> **待办**：本文件是 ${brief["sceneId"]} 的**结构草稿**，由 \`feuille scene draft\` 从 `
    + `\`lessons/${sid}/brief.json\` 生成。所有 \`${TODO}\` 都是待填槽位。`)
  L.push(`> 填完跑 \`feuille scene parse --scene ${sid}\` + \`feuille scene draft --brief ... --gaps\` 查欠账。`)
  L.push("")
  L.push("## 0. 场景规格（机读体例——parse_scene.py 只认本节 + §2 台词体例 + §5 词表）")
  L.push("")
  L.push(`sceneId: ${brief["sceneId"]}`)
  L.push(`title: ${brief["title"]}`)
  L.push(`form: ${brief["form"] ?? "dialogue"}`)
  if (brief["rtlLocales"]) L.push(`rtlLocales: ${(brief["rtlLocales"] as string[]).join(", ")}`)
  if (brief["durationBudget"]) L.push(`durationBudget: ${brief["durationBudget"]}`)
  if (brief["noteFloor"]) L.push(`noteFloor: ${brief["noteFloor"]}`)
  if (brief["askBalance"]) L.push(`askBalance: ${brief["askBalance"]}`)
  L.push("")
  L.push("### 0.1 教学 token（书写序 = 出场序）")
  L.push("")
  L.push(mdTable(["key", "chip"], (brief["tokens"] as Json[]).map((t) => [t["key"], t["chip"]])))
  L.push("")
  L.push("### 0.2 舞台装置规格（style = devices 的 `@device_style` 注册表；well = 空井底色）")
  L.push("")
  const devRows: Json[][] = []
  for (const loc of locales) {
    const d = ((brief["devices"] ?? {}) as Record<string, Json>)[loc] ?? {}
    const sc = d["scenes"]
    const scenes = typeof sc === "string" ? sc : ((sc ?? []) as string[]).join(", ")
    devRows.push([
      loc, scenes || TODO,
      d["style"] ?? "tray", d["shape"] ?? "round",
      d["cellW"] ?? 112, d["cellH"] ?? 112,
      d["well"] ?? "", d["label"] ?? TODO,
    ])
  }
  L.push(mdTable(["locale", "scenes", "style", "shape", "cellW", "cellH", "well", "label"], devRows))
  L.push("")
  if (brief["levels"]) {
    L.push("### 0.3 语种文本规范")
    L.push("")
    L.push(mdTable(
      ["locale", "语体 A", "语体 B", "区分标记", "说明"],
      Object.entries(brief["levels"] as Record<string, Json>)
        .map(([k, v]) => [k, v["a"] ?? TODO, v["b"] ?? TODO, v["marker"] ?? TODO, v["note"] ?? ""])))
    L.push("")
  }
  L.push("### 0.4 角色声明（选角纪律的可验收形式）")
  L.push("")
  L.push(mdTable(
    ["role", "energy", "说明"],
    (["A", "B"] as const)
      .filter((r) => has(brief["roles"], r))
      .map((r) => [r, brief["roles"][r]["energy"] ?? "lively", brief["roles"][r]["note"] ?? ""])))
  L.push("")
  L.push("### 0.5 骨架节拍（台词行的角色与问句归属由本表决定，不按行号硬推）")
  L.push("")
  L.push(`\`n\` = 该语种台词行数（本课 n=${nLines}）。节拍须完整覆盖 \`[0, n-1]\` 且不重叠。`)
  L.push("")
  L.push(beatTableMd(beats, nLines))
  L.push("")
  L.push("## 1. 规格总则")
  L.push("")
  L.push(`### 1.1 骨架（全语种共享）\n\n${brief["structure"] ?? TODO}\n`)
  L.push("### 1.2 独立创作原则（承 colors 课 §1.2）\n\n"
    + "一骨架、每语种独立剧本：说法、语气、舞台道具全部在语种内自洽，不从中文直译。\n")
  L.push("## 2. 剧本\n")
  L.push("体例：台词 = 原文（*注音*）——中文对照。罗马注音永不入音；对照仅供阅读理解。\n")

  for (const loc of locales) {
    const m = langs[loc]!
    const cast = castFor(loc, personas, cards)
    const quote = m["quote"] as string
    const qo = quote[0]!, qc = quote[quote.length - 1]! // manifest 存的是「一对」，这里拆开用
    const beatFrom = new Map(beats.map((b) => [b.beat, b.from])) // noteOn 逐行取值要节内偏移
    L.push(`### 2.${locales.indexOf(loc) + 1} ${m["label"]} ${loc}｜${cast["A"]} × ${cast["B"]}\n`)
    L.push(`**舞台**：${((brief["stage"] ?? {}) as Record<string, Json>)[loc] ?? TODO}`
      + `　**道具装置**：${(((((brief["devices"] ?? {}) as Record<string, Json>)[loc] ?? {}) as Json)["label"] ?? TODO)}\n`)
    for (const ln of plan) {
      // 一行可有多姿态码（`bounce-in` 入场 + `both-hands`）：空格分隔全部反引号化
      const codes2 = String(ln.pose || "").split(" ").filter(Boolean).map((c) => `\`${c}\``).join(" ")
      // 手势锚词槽必须是**带引号**的 `「TODO」处`——parse_line 认锚词的正则只匹配
      // 带引号形式，把占位符写成最终形状，「填词」才真的只是填词。引号对取自 manifest。
      let seg = codes2 ? `｜${qo}${TODO}${qc} 处 ${codes2}` : ""
      // noteOn 按**节内行偏移**取值：收尾节常只有最后一行动作，字符串 = 整节同值
      const b0 = beatFrom.get(ln.beat) ?? 0
      const mark = at(((brief["noteOn"] ?? {}) as Record<string, Json>)[ln.beat], ln.i - b0, "") || ""
      if (String(mark).includes(TODO)) seg += `｜⚑${TODO}`
      if (String(mark).includes("exit")) seg = (seg || "｜") + "＋蹦跳出画"
      L.push(`- **${ln.speaker}**（${ln.mood}）：${qo}${TODO}${qc}${seg}`)
    }
    L.push("")
  }

  L.push("## 5. token 词表（对照参考——列序 = §0.1 token 书写序，机读按位置对位）\n")
  const keys = (brief["tokens"] as Json[]).map((t) => t["key"])
  L.push(mdTable(
    ["locale", ...(brief["tokens"] as Json[]).map((t) => t["head"] ?? t["key"])],
    locales.map((loc) => [loc, ...keys.map(() => TODO)])))
  L.push("")
  return L.join("\n")
}


// ---------------------------------------------------------------- 欠账清单

/** 数出草稿里还剩多少 TODO —— 它决定了「还要写多少字」。 */
export function gaps(md: string): Record<string, number> {
  const lines = md.split("\n")
  const nLine = lines.filter((l) => l.trim().startsWith("- **")).length
  const nTodoLine = lines.filter((l) => l.trim().startsWith("- **") && l.includes(TODO)).length
  const nCell = lines.filter((l) => l.startsWith("|") && l.split(TODO).length - 1 > 0).length
  const stages = md.split(`**舞台**：${TODO}`).length - 1
  return {
    "台词行": nLine,
    "仍带 TODO 的台词行": nTodoLine,
    "词表/表格里的 TODO 格": nCell,
    "待写舞台的语种": stages,
  }
}


// ---------------------------------------------------------------- CLI

/** `feuille scene draft --brief ... [--out ...] [--languages DIR] [--personas DIR]
 * [--force] [--print-plan] [--gaps]`。 */
export function mainDraft(argv: string[] = []): number {
  const briefPath = argValue(argv, "--brief")
  if (briefPath === undefined) {
    console.error("usage: feuille scene draft --brief lessons/<id>/brief.json"
      + " [--out ...] [--languages DIR] [--personas DIR] [--force] [--print-plan] [--gaps]")
    return 2
  }
  const languagesDir = argValue(argv, "--languages")
  const personasDir = argValue(argv, "--personas")
  const force = argv.includes("--force") || argv.includes("--force=true")
  const printPlan = argv.includes("--print-plan")
  const gapsOnly = argv.includes("--gaps")

  const brief = JSON.parse(readFileSync(briefPath, "utf8"))
  const out = argValue(argv, "--out") ?? join(dirname(briefPath), "scene.md")

  if (gapsOnly) {
    if (!existsSync(out)) {
      throw new FeuilleError(`没有 ${out}`)
    }
    const g = gaps(readFileSync(out, "utf8"))
    console.log(`欠账清单：${Object.entries(g).map(([k, v]) => `${k}=${v}`).join("　")}`)
    return 0
  }

  const md = render(brief, personas(personasDir), cardsDoc(personasDir),
    langs(languagesDir), registries())

  if (printPlan) {
    console.log(md)
    return 0
  }

  if (existsSync(out) && !force) {
    const head = readFileSync(out, "utf8").slice(0, 2000)
    if (!head.includes(DRAFT_MARK)) {
      throw new FeuilleError(
        `${out} 存在且不是草稿（缺 \`${DRAFT_MARK}\` 标记）——拒绝覆盖。\n`
        + "确实要重写请加 --force，或换个 --out。")
    }
  }
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, md, "utf8")

  const g = gaps(md)
  console.log(`已生成草稿 → ${out}`)
  console.log(`欠账清单：${Object.entries(g).map(([k, v]) => `${k}=${v}`).join("　")}`)
  return 0
}
