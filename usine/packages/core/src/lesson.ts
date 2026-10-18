// lesson.ts — 新课接入的两个动作：`new`（开坑）与 `doctor`（体检）
// （lesson.py 的 TS 移植）
//
// 目录全部参数化：lessons 经 `--lessons`（缺省 = feuille 仓库根 lessons/，data.ts
// 锚定），personas / languages 经 `--personas` / `--languages`。项目根（build/
// 产物、publish/ 台账、build/baseline/ 基线所在层）= lessons 目录上推一层。
// 判定用的注册表一律经 scene_draft.registries() 现取，不抄名单——名单必腐烂。
// 发布层判据接 feuille 事实源：平台文案名按 manifest.PLATFORMS 的 `{plat}-copy.md`
// 派生（copy 显式 None 的平台不走逐支模板）；台账路径 = metrics.ledgerPath(root)；
// 逐帧基线 = framehash.baselinePath(root)（按平台分桶）。`--all` 在 lessons 目录尚
// 不存在时回落到 findSceneIds。
//
// 使用契约：`cmdNew(argv)` 开坑（拒覆盖已有 brief；空跑草稿生成证明这份 brief
// 渲得出来）；`cmdDoctor(argv)` 七层体检（①创意…⑦验收），每条未完成带下一条
// 命令，返回码 0 = 无 FAIL（--strict 时可选拘认 TODO 计失败）/ 1 = 有 FAIL /
// 2 = 用法错。
//
// **为什么要有这两个动作**：接入流程实际是 6 步（brief → 草稿 → 填词 → parse →
// validate → 渲染），而每一步都有静默失败（TODO 没填完照样渲、改了 md 忘重跑
// parse 成片脱节 git diff 干净……）。`new` 把能从注册表现取的一律现取并**在作者
// 投入任何时间之前**空跑草稿证明渲得出来；`doctor` 把 6 步完成度变成一张可机读
// 的表，每条未完成都带下一条命令。
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs"
import { dirname, join, relative } from "node:path"

import { LESSONS_DIR, cardsDoc, personas, personasDoc } from "./data.js"
import { FeuilleError } from "./errors.js"
import * as framehash from "./framehash.js"
import * as persona from "./persona.js"
import { findSceneIds, parseScene } from "./parse_scene.js"
import { SCENES } from "./scenes.js"
import { validateScene } from "./scene_schema.js"
import {
  DRAFT_MARK, castFor, gaps, langs, registries as draftRegistries, render,
} from "./scene_draft.js"
import { timelineName } from "./scene_audio.js"
import { PLATFORMS } from "./manifest.js"
import { ledgerPath } from "./metrics.js"

type Json = any

function lessonsDirOf(lessonsDir?: string | null): string {
  return lessonsDir ? lessonsDir : LESSONS_DIR
}

// 两门示范课共用的骨架：开场 1 + 接题 1 + 来回 2×rounds + 收束 1 + 告别 2。
// 这是**从 colors/numbers 提炼出来的结构常量**（rounds=6 时 5+12=17 行 = numbers
// 的 n=17），换课只换 `rounds`，不必手算 n-K 边界——手算正是坑㉗的来源。
const FIXED_LINES = 1 + 1 + 1 + 2
export const DEFAULT_STYLE = "tray"
export const DEFAULT_SHAPE = "round"
export const DEFAULT_CELL = 112
// 两门课的 `well` 都是同一个浅中性色。**字牌 chip 必须有 well**——井底色不给，
// 深色数字贴在透明底上看不清，而这件事在 numbers 课渲坏过一次才被发现。
export const DEFAULT_WELL = "#F5F3EE"


// ================================================================ 事实源现取

export interface LessonRegistries {
  moods: Set<string>
  poses: Set<string>
  deviceStyles: Set<string>
  scenes: Set<string>
  shapes: Set<string>
}

/** 情绪 / 姿态 / 装置 / 背景原语的合法取值——**从渲染线现取，绝不手抄**。
 *
 * 前三项直接复用 `scene_draft.registries()`：那正是 `render()` 自己做集合运算
 * 时依赖的那一份，自己再抄一份看着等价实际会漂。背景原语与井形是
 * scene_draft 不关心的两项：井形取自 devices.drawDevice 的分支
 * （circle / poly / rect，其余走 round），不是一个独立枚举。
 */
export function registries(): LessonRegistries {
  const reg = draftRegistries()
  return {
    ...reg,
    // 背景原语（scene_draft 不关心）
    scenes: new Set(Object.keys(SCENES)),
    shapes: new Set(["round", "circle", "rect", "poly"]),
  }
}

export { langs }


// ================================================================ new：开坑

/** `--tokens` 文本 / `--tokens-file` JSON → `[{key, chip}]`。
 *
 * chip 两型与 devices.chip_color 的真实契约同源：以 `#` 开头 = 色片（须 #RRGGBB），
 * 其余非空 = 字牌（走文字层贴图）。这里**当场校验**，因为色片写错要到渲完 14 支
 * 才发现。逗号是分隔符，所以 chip 自身不能含逗号——真要教带逗号的字，就用
 * `--tokens-file`。
 */
export function parseTokens(spec: string | undefined, tokenFile: string | undefined): Array<{ key: string; chip: string }> {
  let items: Array<{ key: string; chip: string }>
  if (tokenFile) {
    const raw = JSON.parse(readFileSync(tokenFile, "utf8"))
    items = raw.map((t: Json) => ({ key: t["key"], chip: String(t["chip"]) }))
  } else {
    if (!spec) {
      throw new FeuilleError('要教什么词？给 --tokens "key:chip,key:chip" 或 --tokens-file')
    }
    items = []
    for (let part of spec.split(",")) {
      part = part.trim()
      if (!part) continue
      if (!part.includes(":")) {
        throw new FeuilleError(`--tokens 项缺 chip：'${part}'（应写 key:#RRGGBB 或 key:"文本"）`)
      }
      // Python split(":", 1)：余下冒号归 chip（JS split 的第二参是「丢尾巴」，不是「最多切一次」）
      const ci = part.indexOf(":")
      const k = part.slice(0, ci)
      const chip = part.slice(ci + 1)
      items.push({ key: k.trim(), chip: chip.trim().replace(/^"+/, "").replace(/"+$/, "") })
    }
  }
  if (!items.length) {
    throw new FeuilleError("--tokens 是空的")
  }
  const seen = new Set<string>()
  for (const t of items) {
    const k = t.key
    if (!k) {
      throw new FeuilleError(`--tokens 里有空 key：{'key': '${t.key}', 'chip': '${t.chip}'}`)
    }
    if (seen.has(k)) {
      throw new FeuilleError(`--tokens 里有重复 key：${k}`)
    }
    seen.add(k)
    const chip = t.chip
    if (!chip) {
      throw new FeuilleError(`token '${k}' 的 chip 为空`)
    }
    if (chip.startsWith("#") && chip.length !== 7) {
      throw new FeuilleError(`token '${k}' 的 chip '${chip}' 像色片但不是 #RRGGBB`
        + "（字牌就写文本，别加 #）")
    }
  }
  return items
}

/** 每节拍的情绪/姿态——两门示范课的同一套（bounce-in 入场 → nod 接题 →
 * point 提问 / palm-open 回答 → jump-celebrate 收束 → wave 告别）。
 * 取值全部来自注册表，所以这份默认是**可渲的**。 */
export function defaultSpec(rounds: number, reg: LessonRegistries): Record<string, any> {
  const need = new Set(["happy", "neutral", "encouraging"])
  const missing = [...need].filter((m) => !reg.moods.has(m)).sort()
  if (missing.length) {
    throw new FeuilleError(`MOOD_FACE 缺默认骨架要用的情绪：[${missing.map((m) => `'${m}'`).join(", ")}]`)
  }
  return {
    "open.mood": "happy",
    "open.pose": "bounce-in both-hands",
    "reply.speakers": "B",
    "reply.mood": "neutral",
    "reply.pose": "nod",
    "round.moodAsk": "happy",
    "round.poseAsk": "point",
    "round.moodReply": "neutral",
    "round.poseReply": "palm-open",
    "summary.mood": "happy",
    "summary.pose": "jump-celebrate",
    "bye.speakers": ["B", "A"],
    "bye.mood": ["encouraging", "happy"],
    "bye.pose": ["wave", "wave"],
  }
}

/** 拼一份**能渲**的 brief：能现取的一律现取，留给人做主的只有 TODO。
 * 键序 = 落库序（brief.json 按 JSON.stringify 插入序写出）。 */
export function scaffoldBrief(args: {
  sid: string; title: string; tokens: Array<{ key: string; chip: string }>; locales: string[]
  rounds: number; style: string; shape: string; cell: number; well: string
  durationBudget: string; noteFloor: number; askBalance: string
  goal: string; structure: string; reg: LessonRegistries
}): Record<string, any> {
  const { sid, title, tokens, locales, rounds, style, shape, cell, well, reg } = args
  if (!reg.deviceStyles.has(style)) {
    throw new FeuilleError(`--style '${style}' 不在 DEVICE_STYLES 注册表内。`
      + `合法值：${[...reg.deviceStyles].sort().join(", ")}`)
  }
  if (!reg.shapes.has(shape)) {
    throw new FeuilleError(`--shape '${shape}' 不合法。合法值：${[...reg.shapes].sort().join(", ")}`)
  }
  const lines = FIXED_LINES + 2 * rounds
  return {
    sceneId: sid,
    title,
    goal: args.goal || "TODO：一句话说清这课教什么",
    structure: args.structure || `开场提议 → ${rounds} 轮一来一往 → 开心再会`,
    description: "TODO：一句话说明这课与既有课的可对照差异（colors 色片 / numbers 字牌）",
    form: "dialogue",
    durationBudget: args.durationBudget,
    noteFloor: args.noteFloor,
    askBalance: args.askBalance,
    locales,
    lines,
    tokens,
    devices: Object.fromEntries(locales.map((lc) =>
      [lc, { style, shape, cellW: cell, cellH: cell, well }])),
    roles: { A: { energy: "lively", note: "先问方 · 节奏引擎" },
             B: { energy: "steady", note: "沉稳接题方 · 短问稳答" } },
    skeleton: [
      { beat: "open", lines: 1 },
      { beat: "reply", lines: 1 },
      { beat: "round", lines: "rest", ask: "even", askBy: "A" },
      { beat: "summary", lines: 1 },
      { beat: "bye", lines: 2 },
    ],
    spec: defaultSpec(rounds, reg),
    // 逐行给：只有 A（最后一行动作者）蹦跳出画，B 原地挥手。写成字符串
    // `{"bye": "exit"}` 会把 exit 铺满整节，于是两人一起跑出画——
    // numbers 课的定稿是 A 出画 / B 祝福，所以这里对齐定稿而不是对齐旧 brief。
    noteOn: { bye: ["", "exit"] },
    stage: Object.fromEntries(locales.map((lc) =>
      [lc, "TODO：这门课的舞台与道具（按语种自洽，不从中文直译）"])),
  }
}

/** argparse 同款取值：`--k v` 与 `--k=v` 两种写法都收；重复旗标后者覆盖前者。 */
function argValue(argv: string[], flag: string): string | undefined {
  const i = argv.lastIndexOf(flag)
  if (i >= 0) return argv[i + 1]
  const p = `${flag}=`
  for (let j = argv.length - 1; j >= 0; j--) {
    if (argv[j]!.startsWith(p)) return argv[j]!.slice(p.length)
  }
  return undefined
}

/** 第一个非旗标实参（argparse 的位置参数）。带值的旗标连值一起跳过。 */
function positional(argv: string[], valueFlags: readonly string[]): string | undefined {
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (a.startsWith("--")) {
      // 带值旗标（--title X）连值一起跳；布尔旗标（--force）只跳自己
      if (!a.includes("=") && valueFlags.includes(a)) i++
    } else {
      return a
    }
  }
  return undefined
}

const NEW_VALUE_FLAGS = ["--title", "--tokens", "--tokens-file", "--locales", "--rounds",
  "--style", "--shape", "--cell", "--well", "--scenes", "--duration-budget",
  "--note-floor", "--ask-balance", "--lessons", "--languages", "--personas"] as const

/** `feuille lesson new <id> --title … [--tokens …]`：新课开坑。FeuilleError 向上
 * 抛（统一入口接住 → stderr + 1）；用法错（缺 id/--title、int/choices 不合法）
 * → 2（argparse 同款口径）。 */
export function cmdNew(argv: string[] = []): number {
  const sidRaw = positional(argv, NEW_VALUE_FLAGS)
  const title = argValue(argv, "--title")
  if (sidRaw === undefined || title === undefined) {
    console.error("usage: feuille lesson new <id> --title \"…\" [--tokens \"k:#RRGGBB\"] "
      + "[--tokens-file f.json] [--locales zh-CN,en-US] [--rounds 3] [--lessons DIR] [--force]")
    return 2
  }
  const tokensFile = argValue(argv, "--tokens-file")
  const tokensSpec = argValue(argv, "--tokens") ?? ""
  const localesSpec = argValue(argv, "--locales") ?? "zh-CN,en-US"
  const rounds = Number(argValue(argv, "--rounds") ?? 3)
  const style = argValue(argv, "--style") ?? DEFAULT_STYLE
  const shape = argValue(argv, "--shape") ?? DEFAULT_SHAPE
  const cell = Number(argValue(argv, "--cell") ?? DEFAULT_CELL)
  const well = argValue(argv, "--well") ?? DEFAULT_WELL
  const scenesSpec = argValue(argv, "--scenes") ?? ""
  const durationBudget = argValue(argv, "--duration-budget") ?? "20-55"
  const noteFloor = Number(argValue(argv, "--note-floor") ?? 0)
  const askBalance = argValue(argv, "--ask-balance") ?? "any"
  const lessonsDir = argValue(argv, "--lessons")
  const languagesDir = argValue(argv, "--languages")
  const personasDir = argValue(argv, "--personas")
  const force = argv.includes("--force")
  // argparse 的 int 转换与 choices 校验失败 → 退出码 2（同款口径，不静默 NaN）
  if (!Number.isFinite(rounds) || !Number.isFinite(cell) || !Number.isFinite(noteFloor)
    || (askBalance !== "any" && askBalance !== "symmetric")) {
    console.error("feuille lesson new: 无效参数（--rounds/--cell/--note-floor 须整数，"
      + "--ask-balance 须 any|symmetric）")
    return 2
  }

  const sid = sidRaw.trim()
  if (!sid || sid.includes("/") || sid.startsWith(".")) {
    throw new FeuilleError(`课程 id 不合法：'${sid}'（纯目录名，不要路径分隔符或前导点）`)
  }
  const outDir = join(lessonsDirOf(lessonsDir), sid)
  const briefPath = join(outDir, "brief.json")
  if (existsSync(briefPath) && !force) {
    throw new FeuilleError(`${briefPath} 已存在。加 --force 覆盖。`)
  }

  const reg = registries()
  const langTable = langs(languagesDir)
  const locales = localesSpec.split(",").map((c) => c.trim()).filter(Boolean)
  const unknown = locales.filter((lc) => !(lc in langTable))
  if (unknown.length) {
    throw new FeuilleError(`没有语种目录：[${unknown.map((l) => `'${l}'`).join(", ")}]（先建 languages/<loc>/manifest.json）`)
  }
  if (rounds < 1) {
    throw new FeuilleError(`--rounds 至少 1（实得 ${rounds}）`)
  }
  const badScenes = scenesSpec.split(",").map((c) => c.trim()).filter((s) => s && !reg.scenes.has(s))
  if (badScenes.length) {
    throw new FeuilleError(`--scenes 里有不存在的背景原语：[${badScenes.map((s) => `'${s}'`).join(", ")}]\n`
      + "合法值见 `uv run python -c \"from feuille import scenes;print(sorted(scenes.SCENES))\"`")
  }

  const brief = scaffoldBrief({
    sid, title, tokens: parseTokens(tokensSpec, tokensFile),
    locales, rounds, style, shape, cell, well,
    durationBudget, noteFloor, askBalance, goal: "", structure: "", reg,
  })
  if (scenesSpec) {
    for (const lc of locales) {
      brief["devices"][lc]["scenes"] = scenesSpec.split(",").map((c) => c.trim()).filter(Boolean)
    }
  }

  // 选角当场验：班底里该语种必须恰好有 A/B 各一人。错在这里是**最好的时机**——
  // 等到写完 14 份剧本才发现某个语种没有 A 角，白写。
  const pers = personas(personasDir)
  const cards = cardsDoc(personasDir)
  for (const lc of locales) castFor(lc, pers, cards)

  // 空跑一遍草稿生成：**证明这份 brief 渲得出来**，在作者投入任何时间之前。
  const md = render(brief, pers, cards, langTable, reg)
  const g = gaps(md)

  mkdirSync(outDir, { recursive: true })
  // Python json.dumps(ensure_ascii=False, indent=2) + "\n" 的对应物：键序 = 插入序
  writeFileSync(briefPath, JSON.stringify(brief, null, 2) + "\n", "utf8")

  const nLines = brief["lines"]
  // `relative_to(项目根)` 在 lessons 目录被指向仓库外时会抛 ValueError，而这里
  // 只是给人看的一行字——**显示代码不该有能力让命令失败**。Node 的 relative
  // 不抛错：以「跑出根外」判定回落，与 Python 的 ValueError 回落同义
  // （--lessons 把 lessons 指到仓库外/临时目录是常态）。
  const rootBase = dirname(lessonsDirOf(lessonsDir))   // 项目根 = lessons 目录上推一层
  const shown = (p: string): string => {
    const rel = relative(rootBase, p)
    return rel.startsWith("..") || rel === "" ? p : rel
  }
  console.log(`已写 ${shown(briefPath)}　（${brief["tokens"].length} 个 token × `
    + `${locales.length} 语种 = ${nLines} 行台词）`)
  console.log(`选角已验：${locales.map((lc) => {
    const cast = castFor(lc, pers, cards)
    return `${lc} ${cast["A"]}×${cast["B"]}`
  }).join("、")}`)
  console.log(`装置已验：style=${style} shape=${shape} well=${well}（井位取自注册表，非手抄）`)
  console.log("空跑草稿通过——这份 brief 渲得出来。欠账：" + Object.entries(g).map(([k, v]) => `${k}=${v}`).join("　"))
  console.log()
  console.log("接下来（②生成结构草稿 → ③填台词 → ④全链路）：")
  console.log(`  uv run feuille scene draft --brief lessons/${sid}/brief.json`)
  console.log(`  uv run python -m feuille.scene_draft --brief lessons/${sid}/brief.json --gaps   # 看还欠多少`)
  console.log("  # 填完所有 TODO 后：")
  console.log(`  uv run feuille scene parse --scene ${sid} && uv run feuille scene validate --scene ${sid}`)
  console.log(`  uv run feuille lesson doctor --scene ${sid}      # 体检：还差哪几项`)
  console.log()
  console.log("需要你做主的四件事（工具替不了）：")
  console.log(`  1. 舞台：${locales.length} 个语种各自的 stage（brief.stage，现在都是 TODO）`)
  console.log(`  2. 台词：每语种 ${nLines} 行（引号对已按 languages/<loc>/manifest.json 填好）`)
  console.log(`  3. 词表：§5 每语种 ${brief["tokens"].length} 格（tokenWords，写作序 = §0.1）`)
  if (!scenesSpec) {
    console.log(`  4. 背景原语：§0.2 scenes（合法值 ${reg.scenes.size} 个：`
      + `${[...reg.scenes].sort().slice(0, 8).join(" ")} …）`)
  }
  if (noteFloor < 3) {
    console.log(`  ⚑ note-floor=${noteFloor}，而 colors/numbers 两门课都是 3——`
      + "低于它就是主动放宽质量线，确认是有意的")
  }
  return 0
}


// ================================================================ doctor：体检

/** `(命中数, 应命中数, 基线文件路径)`。
 *
 * 基线路径经 framehash.baselinePath（**按平台分桶**——跨平台像素基线本来就
 * 不可比）。**为什么按「应命中数」而不是「总数」**：一门课刚建时成片一支都
 * 没有，此时 `命中 0 / 应命中 0` 是「还没渲」，不是「漏了基线」——两者不能
 * 混报，否则新课上线的第一屏就会显示一条红色「基线缺失」，而它其实什么也没
 * 做错。
 */
export function baselineHits(
  sceneId: string, locales: string[], root: string, path?: string,
): [number, number, string] {
  const p = path ?? framehash.baselinePath(root)
  const table = framehash.readBaseline(p)
  const names = new Set(locales.map((lc) => `scene-${sceneId}_${lc}.mp4`))
  if (!Object.keys(table).length) return [0, 0, p]
  let have = 0
  for (const n of names) if (n in table) have++
  return [have, names.size, p]
}

export const OK = "ok"
export const TODO_STATE = "todo"
export const FAIL = "fail"
export const SKIP = "skip"
const MARK: Record<string, string> = {
  [OK]: "[ ok ]", [TODO_STATE]: "[todo]", [FAIL]: "[FAIL]", [SKIP]: "[skip]",
}

/** 按**显示宽度**补齐（CJK 记 2 格），不是按字符数——`'成片 mp4'.padEnd(18)`
 * 对 4 个汉字只补 14 格，两行在终端里就错开，表格看着像坏了。
 * 宽度判定镜像 Python unicodedata.east_asian_width 的 W/F 类（覆盖标签字符集：
 * CJK / 假名 / 谚文 / 全角形式 / 表情符号）。 */
function codeWidth(cp: number): number {
  const wide = (cp >= 0x1100 && cp <= 0x115f) || (cp >= 0x2e80 && cp <= 0x303e)
    || (cp >= 0x3041 && cp <= 0x33ff) || (cp >= 0x3400 && cp <= 0x4dbf)
    || (cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0xa000 && cp <= 0xa4cf)
    || (cp >= 0xa960 && cp <= 0xa97f) || (cp >= 0xac00 && cp <= 0xd7a3)
    || (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xfe10 && cp <= 0xfe19)
    || (cp >= 0xfe30 && cp <= 0xfe52) || (cp >= 0xfe54 && cp <= 0xfe66)
    || (cp >= 0xfe68 && cp <= 0xfe6b) || (cp >= 0xff00 && cp <= 0xff60)
    || (cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x1f300 && cp <= 0x1f64f)
    || (cp >= 0x1f900 && cp <= 0x1f9ff) || (cp >= 0x20000 && cp <= 0x2fffd)
    || (cp >= 0x30000 && cp <= 0x3fffd)
  return wide ? 2 : 1
}

function pad(text: string, width = 18): string {
  let w = 0
  for (const ch of text) w += codeWidth(ch.codePointAt(0)!)
  return text + " ".repeat(Math.max(0, width - w))
}

export interface Check {
  tier: string
  name: string
  state: string
  detail: string
  nxt: string
}

export class Report {
  checks: Check[] = []
  constructor(readonly scene: string) {}
  get failed(): Check[] { return this.checks.filter((c) => c.state === FAIL) }
  get pending(): Check[] { return this.checks.filter((c) => c.state === TODO_STATE) }
}

/** Python dict == 口径的深比较（键序无关；45 与 45.0/PyFloat 互等）。 */
function pyEq(a: any, b: any): boolean {
  if (a === b) return true
  if (typeof a === "number" && b !== null && typeof b === "object" && !Array.isArray(b)) {
    return a === Number(b)   // PyFloat 经 valueOf 解包（durationBudget 45.0 落库后回读为 45）
  }
  if (typeof b === "number" && a !== null && typeof a === "object" && !Array.isArray(a)) {
    return Number(a) === b
  }
  if (a == null || b == null) return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  if (Array.isArray(a)) {
    return a.length === b.length && a.every((x, i) => pyEq(x, b[i]))
  }
  if (typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a), kb = Object.keys(b)
    if (ka.length !== kb.length) return false
    return ka.every((k) => k in b && pyEq(a[k], b[k]))
  }
  return false
}

/** Python `x or fallback` 口径（null/undefined/0/""/false → fallback）。 */
function pyOr<T>(v: T, fallback: T): T {
  return v ? v : fallback
}

/** Python set 的 repr 口径（style 集合那一格显示用；None 无引号，str 单引号）。 */
function pySetRepr(items: Iterable<string | null>): string {
  return `{${[...items].sort().map((s) => (s === null ? "None" : `'${s}'`)).join(", ")}}`
}

type Add = (tier: string, name: string, state: string, detail?: string, nxt?: string) => void

/** ① 创意：brief.json 体检（可选输入）。brief 是**可选输入**，不是必填：colors
 * 课早于草稿生成器直接手写 scene.md，至今没补 brief——「没 brief」只在连
 * scene.md 都没有时才是欠账。 */
function checkTierBrief(add: Add, sid: string, briefP: string, mdP: string): void {
  if (!existsSync(briefP) && existsSync(mdP)) {
    add("①创意", "brief.json", SKIP, "无 brief（直接维护 scene.md，可选）")
  } else if (!existsSync(briefP)) {
    add("①创意", "brief.json", TODO_STATE, "还没有教学创意",
      `uv run feuille lesson new ${sid} --title "…" --tokens "k:#RRGGBB"`)
  } else {
    let brief: Json
    try {
      brief = JSON.parse(readFileSync(briefP, "utf8"))
    } catch (e) {
      add("①创意", "brief.json", FAIL, `JSON 解析失败：${(e as Error).message}`)
      return
    }
    const nTok = pyOr(brief["tokens"], []).length
    const nLoc = pyOr(brief["locales"], []).length
    const styles = new Set<string | null>()
    for (const v of Object.values(pyOr(brief["devices"], {})) as Json[]) {
      styles.add(v["style"] === undefined || v["style"] === null ? null : String(v["style"]))
    }
    add("①创意", "brief.json", OK,
      `${nTok} token × ${nLoc} 语种 · ${brief["lines"] ?? "None"} 行 · `
      + `style=${pySetRepr(styles)}`)
  }
}

/** ② 剧本：scene.md 欠账与定稿标记体检。 */
function checkTierScript(add: Add, sid: string, mdP: string): void {
  if (!existsSync(mdP)) {
    add("②剧本", "scene.md", TODO_STATE, "还没有剧本",
      `uv run feuille scene draft --brief lessons/${sid}/brief.json`)
  } else {
    const text = readFileSync(mdP, "utf8")
    const g = gaps(text)
    // gaps 的四键恒在（scene_draft.gaps 固定键集）；?? 0 只是类型收口，缺键不影响判定
    const debt = (g["仍带 TODO 的台词行"] ?? 0) + (g["词表/表格里的 TODO 格"] ?? 0)
      + (g["待写舞台的语种"] ?? 0)
    if (debt) {
      add("②剧本", "scene.md 欠账", TODO_STATE,
        Object.entries(g).map(([k, v]) => `${k}=${v}`).join("　"),
        `uv run python -m feuille.scene_draft --brief lessons/${sid}/brief.json --gaps`)
    } else {
      add("②剧本", "scene.md 欠账", OK, "TODO 清零")
    }
    // `draft: true` = 还没定稿。scene_draft 默认拒覆盖带这个标记的文件——
    // 留着它就等于「随时可能被草稿生成器整份抹掉」，定稿就该摘掉。
    if (text.slice(0, 2000).includes(DRAFT_MARK)) {
      add("②剧本", "已定稿", TODO_STATE, `frontmatter 仍带 \`${DRAFT_MARK}\` → scene-draft 会覆盖它`,
        "定稿后删掉 frontmatter 里的 draft 标记")
    } else {
      add("②剧本", "已定稿", OK, "无 draft 标记，重跑草稿不会覆盖")
    }
  }
}

/** ③ 数据：班底体检 → scene.json 解析/新鲜度 → schema 前置校验。返回解析出的 scene。
 *
 * 班底体检先于一切剧本检查：班底坏了（id 撞 / 配对破 / 字段缺），任何课都渲
 * 不出来——报在「还能便宜地修」的那一层。判定本体是 persona 的纯函数，这里只
 * 接线。逐人走**原始清单**（personasDoc）而不是 {id: persona} 索引——索引会把
 * 重复 id 静默折叠成一个，班底级「id 唯一」就永远验不出来。 */
function checkTierData(add: Add, sid: string, mdP: string, jsonP: string,
                       lessonsDir?: string, personasDir?: string): Json | null {
  // try/else 口径：读得走班底才做体检（读不了只报读不了，不拿空清单冒充体检）。
  try {
    const plist = personasDoc(personasDir)["personas"]
    const bad = [...persona.validateRoster(plist)]
    for (const p of plist) bad.push(...persona.validatePersona(p))
    if (bad.length) {
      add("③数据", "班底体检", FAIL, `${bad.length} 项：${bad[0]}`,
        "uv run feuille persona validate 看全量")
    } else {
      add("③数据", "班底体检", OK, `${plist.length} 人零问题（id 唯一 / 配对齐）`)
    }
  } catch (e) {
    add("③数据", "班底体检", FAIL, `personas.json 读不了：${(e as Error).message}`,
      "修好班底文件再体检（契约见 personas/schema.md）")
  }
  let scene: Json | null = null
  if (!existsSync(mdP)) {
    add("③数据", "scene.json", TODO_STATE, "没有剧本可解析",
      `uv run feuille scene parse --scene ${sid}`)
  } else {
    try {
      scene = parseScene(sid, lessonsDir)[0]
    } catch (e) {
      if (e instanceof FeuilleError) {
        add("③数据", "scene.json", FAIL, String(e))
      } else {
        add("③数据", "scene.md 不合解析体例", FAIL, `${(e as Error).name}: ${(e as Error).message}`)
      }
    }
    if (scene !== null) {
      if (!existsSync(jsonP)) {
        add("③数据", "scene.json", TODO_STATE, "还没落盘",
          `uv run feuille scene parse --scene ${sid}`)
      } else if (!pyEq(JSON.parse(readFileSync(jsonP, "utf8")), scene)) {
        // 这是最阴的一种漂移：剧本改了、JSON 没重跑，成片与剧本脱节而 git diff 干净。
        add("③数据", "scene.json 新鲜度", FAIL,
          "scene.md 改了但 scene.json 没重跑（成片会与剧本脱节）",
          `uv run feuille scene parse --scene ${sid}`)
      } else {
        add("③数据", "scene.json 新鲜度", OK, "与 scene.md 逐字段一致")
      }

      const errs = validateScene(scene, personas(personasDir), cardsDoc(personasDir))
      if (errs.length) {
        add("③数据", "schema 前置校验", FAIL, `${errs.length} 项：${errs[0]}`,
          `uv run feuille scene validate --scene ${sid}`)
      } else {
        add("③数据", "schema 前置校验", OK,
          `${Object.keys(scene["locales"]).length} 语种 × ${scene["tokenOrder"].length} token`)
      }
    }
  }
  return scene
}

/** ④ 成片：逐语种查语音 / 文字层 / mp4。返回本课语种清单 locs。 */
function checkTierOutputs(add: Add, sid: string, scene: Json | null, sceneOut: string): string[] {
  const locs = scene && scene["locales"] ? Object.keys(scene["locales"]) : []
  if (!locs.length) {
    add("④成片", "成片", TODO_STATE, "等 scene.json 出来")
  } else {
    const missTts = locs.filter((lc) => !existsSync(join(sceneOut, "audio", timelineName(sid, lc))))
    const missTxt = locs.filter((lc) => !existsSync(join(sceneOut, "text"))
      || !existsSync(join(sceneOut, "text", `pill_scene-${sid}_${lc}.png`)))
    const missMp4 = locs.filter((lc) => !existsSync(join(sceneOut, `scene-${sid}_${lc}.mp4`)))
    add("④成片", "语音", missTts.length ? TODO_STATE : OK,
      missTts.length ? `缺 ${missTts.length} 语种：${missTts.slice(0, 6).join(", ")}` : "全语种齐",
      missTts.length ? `uv run feuille scene tts --scene ${sid}` : "")
    add("④成片", "文字层", missTxt.length ? TODO_STATE : OK,
      missTxt.length ? `缺 ${missTxt.length} 语种：${missTxt.slice(0, 6).join(", ")}` : "全语种齐",
      missTxt.length ? `uv run feuille scene assets --scene ${sid}（渲染线预留）` : "")
    add("④成片", "成片 mp4", missMp4.length ? TODO_STATE : OK,
      missMp4.length ? `缺 ${missMp4.length} 支：${missMp4.slice(0, 6).join(", ")}`
        : `${locs.length - missMp4.length}/${locs.length} 支`,
      missMp4.length ? `uv run feuille scene render --scene ${sid}（渲染线预留）` : "")
  }
  return locs
}

/** ⑤ 文档（可选层：numbers 就没做，也完全不影响成片）。 */
function checkTierDocs(add: Add, sid: string, locs: string[], d: string, root: string): void {
  if (locs.length) {
    const ad = join(d, "analysis")
    const noSrc = locs.filter((lc) => !existsSync(join(ad, "_source", `${lc}.md`)))
    const noAna = locs.filter((lc) => !existsSync(join(ad, `${lc}.json`)))
    const html = join(root, "build", "lesson", sid, "index.html")
    add("⑤文档", "解析源文本", noSrc.length ? TODO_STATE : OK,
      noSrc.length ? `缺 ${noSrc.length} 语种` : "全语种齐",
      noSrc.length ? `uv run feuille lesson dump --scene ${sid}（教学文档管线尚未接入）` : "")
    add("⑤文档", "逐句解析", noAna.length ? TODO_STATE : OK,
      noAna.length ? `缺 ${noAna.length} 语种（人工产出，无法自动生成）` : "全语种齐",
      noAna.length ? `编辑 lessons/${sid}/analysis/{locale}.json` : "")
    add("⑤文档", "教学文档 HTML", existsSync(html) ? OK : TODO_STATE,
      existsSync(html) ? relative(root, html) : "还没合并",
      existsSync(html) ? "" : `uv run feuille lesson build --scene ${sid}（教学文档管线尚未接入）`)
  }
}

/** ⑥ 发布（可选层）：平台文案与发布台账。
 *
 * 平台文案文件名按 manifest 的 parse_copy 契约（`{plat}-copy.md`）从平台表派生：
 * **显式**写了 `"copy": null` 的平台（知乎：一课一篇长文）不走逐支模板；
 * 没声明 copy 键的平台 = 逐支模板平台。台账路径走 metrics.ledgerPath。 */
function checkTierPublish(add: Add, sid: string, d: string, root: string): void {
  const copies = Object.entries(PLATFORMS)
    .filter(([, m]) => !("copy" in m && !m["copy"]))
    .map(([plat]) => `${plat}-copy.md`)
  const noCopy = copies.filter((c) => !existsSync(join(d, "publish", c)))
  let ledgerN = 0
  const ledgerP = ledgerPath(root)
  if (existsSync(ledgerP)) {
    const entries = JSON.parse(readFileSync(ledgerP, "utf8"))["entries"] as Record<string, Json>
    ledgerN = Object.values(entries).filter((e) => e["lesson"] === sid).length
  }
  add("⑥发布", "平台文案", noCopy.length ? TODO_STATE : OK,
    noCopy.length ? `缺 ${noCopy.join(", ")}` : `齐（${copies.join(", ")}）`,
    noCopy.length ? `写进 lessons/${sid}/publish/{plat}-copy.md` : "")
  add("⑥发布", "发布台账", ledgerN ? OK : TODO_STATE,
    ledgerN ? `${ledgerN} 条` : "台账里没有这课",
    ledgerN ? "" : "项目侧组装 plans 后经 feuille.manifest.build_manifest 建台账"
      + "（该契约吃闭包，有意不设 CLI 叶子）")
}

/** ⑦ 验收：场景线验收状态位 + 逐帧像素基线查表。qa_scene（逐帧读 mp4）尚未
 * 接入：状态位判定的「下一步」如实说明判据暂由逐帧像素基线承担——
 * **「没验」不许长得像「验过了」**。 */
function checkTierAcceptance(add: Add, sid: string, locs: string[], sceneOut: string, root: string): void {
  if (!locs.length) {
    add("⑦验收", "场景线验收", TODO_STATE, "等成片出来",
      "qa_scene 尚未接入（依赖场景渲染线）；验收暂以下方像素基线为准")
  } else if (!locs.some((lc) => existsSync(join(sceneOut, `scene-${sid}_${lc}.mp4`)))) {
    add("⑦验收", "场景线验收", SKIP, "没有成片可验（qa_scene 要逐帧读 mp4）",
      `uv run feuille scene render --scene ${sid} 之后才有意义（场景渲染线尚未接入）`)
  } else {
    add("⑦验收", "场景线验收", TODO_STATE, "跑一次确认没退化",
      "qa_scene 尚未接入（依赖场景渲染线）；验收暂以下方像素基线为准")
  }
  // 逐帧像素基线是**零像素漂移**这条硬判据的载体。基线是一个
  // `{成片名: hash}` 表，这里直接查表——「跑过了」和「覆盖到这课了」是两件事。
  const [have, total, baseP] = baselineHits(sid, locs, root)
  if (!total) {
    add("⑦验收", "逐帧像素基线", SKIP, "还没有基线表（成片渲完才有东西可比）",
      "uv run feuille framehash save")
  } else if (have < total) {
    add("⑦验收", "逐帧像素基线", TODO_STATE,
      `基线覆盖 ${have}/${total} 支，缺的这几支漂移了也没人知道`,
      "uv run feuille framehash save")
  } else {
    add("⑦验收", "逐帧像素基线", OK, `${have}/${total} 支在基线内（${baseP}）`)
  }
}

/** 一节课的完成度。**每一层都以「下一条命令」收尾**——体检的价值不是骂人，
 * 是接手。分层依据是 colors / numbers 两门课**实际产出过的文件**：「必做」只有
 * 到成片那几层，文档层与发布层是**可选层**，未做记 todo 而不是 fail。 */
export function tierReport(sid: string, lessonsDir?: string, personasDir?: string): Report {
  // 项目根 = lessons 目录上推一层（build/ 产物、publish/ 台账、build/baseline/ 都在这层）。
  const root = dirname(lessonsDirOf(lessonsDir))
  const sceneOut = join(root, "build", "scene")
  const rep = new Report(sid)
  const d = join(lessonsDirOf(lessonsDir), sid)
  const mdP = join(d, "scene.md"), jsonP = join(d, "scene.json")
  const briefP = join(d, "brief.json")

  const add: Add = (tier, name, state, detail = "", nxt = "") => {
    rep.checks.push({ tier, name, state, detail, nxt })
  }

  checkTierBrief(add, sid, briefP, mdP)
  checkTierScript(add, sid, mdP)
  const scene = checkTierData(add, sid, mdP, jsonP, lessonsDir, personasDir)
  const locs = checkTierOutputs(add, sid, scene, sceneOut)
  checkTierDocs(add, sid, locs, d, root)
  checkTierPublish(add, sid, d, root)
  checkTierAcceptance(add, sid, locs, sceneOut, root)
  return rep
}

export function printReport(rep: Report): void {
  console.log("=".repeat(78))
  console.log(`课程体检：${rep.scene}`)
  console.log("=".repeat(78))
  let tier: string | null = null
  for (const c of rep.checks) {
    if (c.tier !== tier) {
      tier = c.tier
      console.log(`\n${tier}`)
    }
    console.log(`  ${MARK[c.state]} ${pad(c.name)} ${c.detail}`)
    if (c.nxt && (c.state === TODO_STATE || c.state === FAIL)) {
      console.log(`         └─ 下一步：${c.nxt}`)
    }
  }
  const nf = rep.failed.length, nt = rep.pending.length
  console.log()
  console.log("=".repeat(78))
  const verdict = !nf && !nt ? "就绪" : (nf ? `FAIL ${nf} 项` : `还差 ${nt} 项`)
  console.log(`${rep.scene}：${verdict}　（${rep.checks.length} 项检查）`)
  console.log("=".repeat(78))
}

/** `feuille lesson doctor [--scene ID] [--lessons DIR] [--all] [--json] [--strict]`。 */
export function cmdDoctor(argv: string[] = []): number {
  const scene = argValue(argv, "--scene") ?? ""
  const lessonsDir = argValue(argv, "--lessons")
  const personasDir = argValue(argv, "--personas")
  const all = argv.includes("--all")
  const json = argv.includes("--json")
  const strict = argv.includes("--strict")

  const base = lessonsDirOf(lessonsDir)
  const isDir = (p: string): boolean => {
    try { return statSync(p).isDirectory() } catch { return false }
  }
  // --all 在 lessons 目录尚不存在时回落到 findSceneIds（iterdir 会崩，这不是
  // 「还没有课」该有的死法）。
  let ids: string[]
  if (scene) {
    ids = [scene]
  } else if (all && isDir(base)) {
    ids = readdirSync(base, { withFileTypes: true })
      .filter((e) => e.isDirectory()).map((e) => e.name).sort()
  } else {
    ids = findSceneIds(lessonsDir)
  }
  if (!ids.length) {
    console.log("还没有课。`uv run feuille lesson new <id> --title \"…\" --tokens \"k:#RRGGBB\"` 开一门。")
    return 0
  }
  if (scene && !isDir(join(base, scene))) {
    console.log(`没有 lessons/${scene}/。开一门：uv run feuille lesson new ${scene} ...`)
    return 1
  }

  const reports = ids.map((sid) => tierReport(sid, lessonsDir, personasDir))
  if (json) {
    console.log(JSON.stringify(reports.map((r) => ({
      scene: r.scene,
      failed: r.failed.length,
      pending: r.pending.length,
      checks: r.checks.map((c) => ({ tier: c.tier, name: c.name, state: c.state, detail: c.detail, next: c.nxt })),
    })), null, 2))
  } else {
    for (const r of reports) {
      printReport(r)
      if (reports.length > 1) console.log()
    }
  }

  const OPTIONAL = ["⑤文档", "⑥发布"]
  const hard = reports.flatMap((r) => r.failed)
  const soft = reports.flatMap((r) => r.pending)
    .filter((c) => !(strict && OPTIONAL.includes(c.tier)))
  if (hard.length) return 1
  return strict && soft.length ? 1 : 0
}


// ================================================================ CLI（统一入口叶子）

export function mainNew(argv: string[] = []): number {
  return cmdNew(argv)
}

export function mainDoctor(argv: string[] = []): number {
  return cmdDoctor(argv)
}
