// parse_scene.ts — 通用教学场景解析器：lessons/<id>/scene.md → lessons/<id>/scene.json
// （parse_scene.py 的 TS 移植）
//
// lessons 目录参数化：scenePaths / findSceneIds / analysisDir / parseScene 都带可选
// lessonsDir（缺省 = feuille 仓库根 lessons/，data.ts 锚定）——doctor 与内容项目要把
// lessons 指到自己的目录。命令名 `feuille scene parse`（P7 后改 pnpm/dsh 口径）；
// 入口 mainParse(argv)（统一入口以 fn(argv) 调用）。
//
// 使用契约：`parseScene(sceneId, lessonsDir?) → [doc, outPath]`——解析 + 前置校验
// （scene_schema.validateScene）通过才返回，不产出半成品 scene.json；main 落盘后跑
// token 零遗漏零重复 / 轮次气泡齐备自检。
//
// 剧本 md 是场景唯一事实源（台词 + 机器规格），本模块只做**抽取**不做改写：§0 机读
// 规格、§2 各语种台词、§5 token 词表全部按体例取回，保证 md 与 JSON 两处同步。
//
// **场景无关**：新教学场景 = 在 `lessons/<id>/` 新建 `scene.md` 照抄体例，
// 本模块与渲染线零改动。
//
// 错误通道与 Python 同构：FeuilleError 仅用于「剧本不存在」（库层显式失败）；
// 解析层的体例违规在 Python 侧是 ValueError（CLI 不接、直接 traceback 退出码 1），
// 这里对应普通 Error——两层通道不混。
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs"
import { basename, join } from "node:path"

import { languageManifests, lessonsDirOf, scenePaths } from "./data.js"
import { FeuilleError } from "./errors.js"
import { validateScene } from "./scene_schema.js"

// scenePaths 的口径本体在 data（与 LESSONS_DIR 同址，见该文件注释：纯路径拼接、
// 无业务，归 library 正合适）。这里转出保兼容面，scene_audio 与既有调用方仍按
// parse_scene 取。这样 data ⇄ parse_scene 的静态环彻底消失——本模块本就依赖
// data 的 languageManifests，方向单一，不再有 library 反向依赖 skill 专属层。
export { scenePaths } from "./data.js"

type Json = Record<string, any>

const LOC_RE = /[a-z]{2,3}-[A-Z]{2}/
// polyglot 的小节头没有 `×` 分隔符：三个人都演，标题后是一串名字
const HEAD_RE = /^### (?:\d+\.\d+\s+)?([^｜\n]+)｜([^×\n]+)×\s*([^\n（]+)/gm
const HEAD_RE_SHARED = /^### (?:\d+\.\d+\s+)?([^｜\n]+)｜([^\n（]+)/gm
const TABLE_ROW_RE = /^\|(.+)\|\s*$/gm

/** 仓库内已有的场景 id（lessons/<id>/scene.md 存在即算），供缺省选择与报错提示。 */
export function findSceneIds(lessonsDir?: string): string[] {
  const base = lessonsDirOf(lessonsDir)
  if (!existsSync(base)) return []
  // Python glob 隐含跳过点开头目录；readdirSync 不跳，补上同款口径
  return readdirSync(base)
    .filter((n) => !n.startsWith(".") && existsSync(join(base, n, "scene.md")))
    .sort()
}

/** id → lessons/<id>/analysis/（逐句解析 <locale>.json + _source/<locale>.md 的家）。 */
export function analysisDir(sceneId: string, lessonsDir?: string): string {
  return join(lessonsDirOf(lessonsDir), sceneId, "analysis")
}

/** 按一级节切分：{节号或 '': 文本}。§0 机读规格只在本节内找，避免与 §5 词表混淆。 */
function splitMd(md: string): Record<string, string> {
  const parts: Record<string, string> = {}
  const marks = [...md.matchAll(/^## (\S*)[^\n]*$/gm)]
  marks.forEach((m, idx) => {
    const end = idx + 1 < marks.length ? marks[idx + 1]!.index! : md.length
    parts[(m[1] ?? "").replace(/[.:：]+$/, "")] = md.slice(m.index! + m[0].length, end)
  })
  return parts
}

/** 文本内所有 markdown 表 → [[headerCells, [rowCells…]]]，跳过分隔行。 */
function tables(text: string): [string[], string[][]][] {
  const rows: string[][] = []
  for (const m of text.matchAll(TABLE_ROW_RE)) {
    const cells = (m[1] ?? "").split("|").map((c) => c.trim())
    if (cells.every((c) => /^:?-{3,}:?$/.test(c))) continue
    rows.push(cells)
  }
  const out: [string[], string[][]][] = []
  let i = 0
  while (i < rows.length) {
    const header = rows[i]!
    const body: string[][] = []
    i += 1
    while (i < rows.length && rows[i]!.length === header.length) {
      body.push(rows[i]!)
      i += 1
    }
    out.push([header, body])
  }
  return out
}

/** §0 机读规格的返回值。**给字段起名是为了让外部脚本按名字取**。
 *
 * 此前它是个裸元组，调用方只能靠下标：§0.6 同台表加进来那天，beats 从下标 6
 * 挪到了 7，旧门禁里的 `parse_spec(md)[6]` 静默取到了 cast——**报「0 节」而不是
 * 崩**，门禁看起来是绿的，判据其实已经取错了东西。命名字段把下标这条路堵上。 */
export interface Spec {
  meta: Json
  tokenOrder: string[]
  tokens: Record<string, string>
  devices: Record<string, Json>
  levels: Record<string, Json>
  roles: Record<string, string>
  cast: Json[]
  beats: Json[]
}

/** §0 机读规格 → Spec（meta / tokenOrder / tokens / devices / levels / roles / cast / beats）。
 *
 * tokens: {key: chip}；chip 以 # 开头 = 色片，否则 = 字牌文本。
 * devices: {locale: {scenes,style,shape,cellW,cellH,well,label}}；缺行语种不在表内。
 * levels:  {locale: {levelA,levelB,marker,note}}（§0.3 语种文本规范；缺行 = 不检查）。
 * roles:   {role: energy}（§0.4 角色声明；**合法说话人就是这张表的键**，没有第二份名单）。
 * cast:    [{role, locale, framing, note}]（§0.6 同台表；仅 polyglot 填，dialogue 留空）。
 * beats:   [{beat, from, to, ask, askBy}]（§0.5 骨架节拍；from/to 支持 `n-K` 记法）。 */
export function parseSpec(md: string): Spec {
  const sec0 = splitMd(md)["0"] ?? ""
  if (!sec0.trim()) {
    throw new Error("缺 §0 场景规格节（机读体例，见 lessons/colors/scene.md §0）")
  }

  const metaVal = (key: string): string => {
    // 分隔处用 `[^\S\n]*` 而不是 `\s*`：`\s` 吃换行，于是留空的 `rtlLocales:`
    // 会把**下一行**（`### 0.1 …`）当成本键的值——留空就炸，这是真踩过的坑。
    const m = sec0.match(new RegExp(`^${key}:[^\\S\\n]*(.+)$`, "m"))
    return m ? (m[1] ?? "").trim() : ""
  }

  const meta: Json = {
    sceneId: metaVal("sceneId"),
    title: metaVal("title"),
    form: metaVal("form") || "dialogue",
    rtlLocales: metaVal("rtlLocales").split(",").map((x) => x.trim()).filter(Boolean),
  }
  if (!meta["sceneId"] || !meta["title"]) throw new Error("§0 缺 sceneId / title")

  // durationBudget: "40-55" → [40.0, 55.0]；缺省不设预算（验收跳过时长检查而非判过）
  const budget = metaVal("durationBudget")
  if (budget) {
    const m = /^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$/.exec(budget)
    if (!m) throw new Error(`§0 durationBudget 格式应为 40-55，实得：'${budget}'`)
    meta["durationBudget"] = [new PyFloat(Number(m[1])), new PyFloat(Number(m[2]))]
  }

  // askBalance: 该课对「问句在 A/B 之间的分布」的要求。**不能默认替所有课定一种
  // 戏剧结构**——A 主导的计数游戏、单人讲解都同样合理，判失败等于把一种写法当规范。
  const ab = metaVal("askBalance")
  if (ab && ab !== "symmetric" && ab !== "any") {
    throw new Error(`§0 askBalance 只能是 symmetric / any，实得：'${ab}'`)
  }
  meta["askBalance"] = ab || "any"

  // noteFloor: 该课对 ⚑ 注记行的**自己声明**下限（缺省 0 = 不要求）。
  const nf = metaVal("noteFloor")
  if (nf) {
    if (!/^\d+$/.test(nf)) throw new Error(`§0 noteFloor 应为非负整数，实得：'${nf}'`)
    meta["noteFloor"] = Number(nf)
  }

  const tokenOrder: string[] = []
  const tokens: Record<string, string> = {}
  for (const [header, body] of tables(sec0)) {
    if (header[0] === "key" && header[1] === "chip") {
      for (const row of body) {
        if (row.length < 2 || !row[0]) continue
        const key = row[0]!
        let chip = row[1]!.trim()
        while (chip.startsWith('"')) chip = chip.slice(1)
        while (chip.endsWith('"')) chip = chip.slice(0, -1)
        if (key in tokens) throw new Error(`§0 token 重复：${key}`)
        tokenOrder.push(key)
        tokens[key] = chip
      }
    }
  }
  if (!Object.keys(tokens).length) {
    throw new Error("§0 缺教学 token 表（| key | chip |）；纯对话场景省略本表即可，"
      + "但当前体例要求至少给出表格标题行")
  }

  const devices: Record<string, Json> = {}
  for (const [header, body] of tables(sec0)) {
    if (header.length >= 2 && header[0] === "locale" && header[1] === "scenes") {
      for (const row of body) {
        const loc = row[0]!
        devices[loc] = {
          scenes: row[1]!.split(",").map((s) => s.trim()).filter(Boolean),
          style: row.length > 2 ? row[2]! : "tray",
          shape: row.length > 3 ? row[3]! : "round",
          cellW: row.length > 4 && row[4] ? Math.trunc(Number(row[4])) : 112,
          cellH: row.length > 5 && row[5] ? Math.trunc(Number(row[5])) : 112,
          well: row.length > 6 && row[6] ? row[6]! : "",
          label: row.length > 7 ? row[7]! : "",
        }
      }
    }
  }
  const levels: Record<string, Json> = {}
  for (const [header, body] of tables(sec0)) {
    if (header.length >= 4 && header[0] === "locale" && header.includes("区分标记")) {
      for (const row of body) {
        if (!row[0]) continue
        levels[row[0]!] = {
          levelA: row[1]!, levelB: row[2]!,
          marker: row[3]!, note: row.length > 4 ? row[4]! : "",
        }
      }
    }
  }

  const roles: Record<string, string> = {}
  for (const [header, body] of tables(sec0)) {
    if (header.length >= 2 && header[0] === "role" && (header[1] ?? "").includes("energy")) {
      for (const row of body) {
        if (row[0]) roles[row[0]!] = row[1]!
      }
    }
  }

  // §0.6 同台表（仅 form: polyglot 需要）：角色 ↔ 语种 ↔ 取景的绑定。
  // **为什么另起一张表而不塞进 §0.4 roles**：roles 是 `{角色: energy}`，两门既有的
  // dialogue 课就是这一个形状；往里加列就得改它们的 scene.json。另起一表，
  // 既有课的 scene.json 逐字节不变。
  const cast: Json[] = []
  for (const [header, body] of tables(sec0)) {
    if (header.length >= 2 && header[0] === "role" && (header[1] ?? "").includes("locale")) {
      for (const row of body) {
        if (!row[0]) continue
        cast.push({
          role: row[0]!,
          locale: row[1]!.trim(),
          framing: row.length > 2 && row[2] ? row[2]!.trim() : "full",
          note: row.length > 3 ? row[3]! : "",
        })
      }
    }
  }

  const beats: Json[] = []
  for (const [header, body] of tables(sec0)) {
    if (header.length >= 3 && header[0] === "beat"
      && (header[1] ?? "").includes("from") && (header[2] ?? "").includes("to")) {
      for (const row of body) {
        if (!row[0]) continue
        beats.push({
          beat: row[0]!,
          from: row[1]!.trim(),
          to: row[2]!.trim(),
          ask: row.length > 3 ? (row[3]!.trim() || "-") : "-",
          askBy: row.length > 4 ? (row[4]!.trim() || "-") : "-",
        })
      }
    }
  }
  if (!beats.length) {
    throw new Error("§0 缺骨架节拍表（| beat | from | to | ask | askBy |）——"
      + "台词行的角色/问句归属由它决定，不按行号硬推")
  }

  return { meta, tokenOrder, tokens, devices, levels, roles, cast, beats }
}

const QUOTE_PAIRS: [string, string][] = [["「", "」"], ["«", "»"], ["“", "”"], ['"', '"']]

/** 取行首引号对内的正文（优先级：汉字圈「」→ «»→ 直角"）。
 * 只认**位于 rest 开头**的引号：否则会误取中文对照里的「夜」这类嵌套引号。 */
function matchQuote(rest: string): [string | null, string] {
  rest = rest.replace(/^\s+/, "")
  for (const [op, cl] of QUOTE_PAIRS) {
    if (!rest.startsWith(op)) continue
    const j = rest.indexOf(cl, op.length)
    if (j < 0) continue
    return [rest.slice(op.length, j), rest.slice(j + cl.length)]
  }
  return [null, rest]
}

/** 姿态码归一（scene_draft 同款复用）：`jump-celebrate` → `jump_celebrate`。 */
export function normPose(code: string): string {
  let s = code.trim()
  while (s.startsWith("`")) s = s.slice(1)
  while (s.endsWith("`")) s = s.slice(0, -1)
  return s.replaceAll("-", "_").toLowerCase()
}

const EGG_HEX = /#([0-9A-Fa-f]{6})/

/** 行内「班底彩蛋」批注 → {label, hex}（无则 null）。
 *
 * 这类批注此前只活在 md 散文里，解析时被整段丢弃，于是**没有任何东西能校验它**：
 * 人设换了色板、md 里手抄错一位，都不会有人发现——而剧本自己的验收清单写着
 * 「换角即失效」。抽成数据后由 scene_schema 校验。 */
function parseEasterEgg(seg: string): Json | null {
  const m = EGG_HEX.exec(seg)
  if (!m) return null
  const pre = seg.slice(0, m.index)
  // 标注文字 = 紧邻 hex 之前、最后一个全/半角冒号之后的那段（「班底彩蛋：」/「面瘫自指：」）
  const tail = /[：:]/.test(pre) ? pre.split(/[：:]/).pop()! : pre
  let label = tail.trim()
  label = label.replace(/^[—-]+|[—-]+$/g, "")
  label = label.trim().replace(/^`+|`+$/g, "").trim()
  return { label, hex: `#${m[1]!.toUpperCase()}` }
}

/** 一行台词 → {speaker, lang, mood, text, romanization, gloss, note, gesture, exits}。
 *
 * 体例 `- **<角色>**（<情绪>）：「原文」`；**角色名不写死 A/B**——`- **C**（happy）` 与
 * `- **主持人**（happy）` 一样能解析，合法性由 §0.4 roles 决定（见 scene_schema）。
 *
 * polyglot 形态多一段 `· <locale>`：`- **A · en-US**（happy）："..."`。
 * 这一段是**该行台词用什么语言说**。缺省（`·` 后面没有）= 沿用该语种块自己的
 * 语言——既有 dialogue 课的写法，一个字都不用改。
 *
 * 非 null 返回对象的键序 = 落库键序（scene.json 逐字节 parity 依赖插入序）。 */
export function parseLine(line: string): Json | null {
  const m = /^[ \t]*(?:→)?- \*\*([^*]+)\*\*（([\p{L}\p{N}_]+)）：(.*)$/u
    .exec(line.trim())
  if (!m) return null
  const who = (m[1] ?? "").trim(), mood = m[2] ?? "", rest = (m[3] ?? "").trim()
  // `·`（U+00B7）分隔角色与语种：角色名里不会出现这个符号
  const bits = who.split("·").map((b) => b.trim())
  const speaker = bits[0]!
  const lang = bits.length > 1 && bits[1] ? bits[1]! : ""

  const [text, tail0] = matchQuote(rest)
  if (text === null) throw new Error(`引号解析失败: ${line.slice(0, 60)}`)
  let tail = tail0

  const romM = /^\s*（\*([^*]+)\*）/.exec(tail)     // 注音：永不入音，仅 display 参考
  const romanization = romM ? (romM[1] ?? "").trim() : ""
  if (romM) tail = tail.slice(romM.index + romM[0].length)

  // 注记段（⚑）先剥离：注记文字里允许出现「——」，不得被下面的对照解析吃掉
  const parts = tail.split("｜").slice(1)                    // ｜ 后的段（注记 + 手势）
  const noteParts = parts.filter((x) => x.trim().startsWith("⚑"))
  const note = noteParts.length ? noteParts[0]!.replace(/^\s*⚑\s*/, "").trim() : ""
  const seg = parts.filter((x) => !x.trim().startsWith("⚑")).join("｜")

  // 中文对照只认首段（第一个 ｜ 之前）的「——」：手势段/注记段的「——」是行内批注，不是翻译
  const glM = /——(.*?)(?:｜|$)/.exec(tail.split("｜")[0] ?? "")
  const gloss = glM ? (glM[1] ?? "").trim() : ""
  const poses = [...seg.matchAll(/`([a-zA-Z][a-zA-Z0-9_-]*)`/g)].map((x) => normPose(x[1]!))
  const wm = /(?:「([^」]+)」|“([^”]+)”|«([^»]+)»|"([^"]+)")\s*处/.exec(seg)
  const word = wm ? [wm[1], wm[2], wm[3], wm[4]].find((g) => g)?.trim() ?? "" : ""

  const lineObj: Json = {
    speaker,
    mood,
    text: text.trim(),
    romanization,
    gloss,
    note,
    gesture: { word, poses },
    easterEgg: parseEasterEgg(seg),
    exits: seg.includes("出画"),
  }
  // `lang` 只在真写了语种时才落库：既有 dialogue 课的 scene.json 必须逐字节不变，
  // 多一个恒为空的键就是「既有课被改过」的铁证。
  if (lang) lineObj["lang"] = lang
  return lineObj
}

/** 节拍边界求值：支持 `0` / `5` / `n` / `n-4`（n = 该语种台词行数）。 */
function resolveIndex(expr: string, n: number): number {
  const e = expr.trim()
  const m = /^n\s*-\s*(\d+)$/.exec(e)
  if (m) return n - Number(m[1])
  if (e === "n") return n
  return Number.parseInt(e, 10)   // Python int(e) 对垃圾输入直接 ValueError；这里 NaN 落进范围检查报错
}

/** 按 §0.5 声明的骨架节拍标注每行的 role / isQuestion（**不按行号硬推**）。
 *
 * 旧实现在 parseLocales 里写死 open/reply/round/summary/bye 四个偏移与「偶数行=问句」，
 * 那是 dialogue 这一种形态的骨架，却长在通用解析器里——换个教学形态就得改代码。
 * 现在骨架是数据：新增形态只加节拍表，解析器与渲染线零改动。
 *
 * 节拍必须**完整覆盖** [0, n-1] 且不重叠：留白会让某行既无角色也无问句归属，
 * 而那正是「为什么这一行没有思考气泡」这类问题的根因。 */
export function applyBeats(dialogue: Json[], beats: Json[], locale: string): Json[] {
  const n = dialogue.length
  const cover: Record<number, string> = {}
  for (const b of beats) {
    const i0 = resolveIndex(b["from"], n), i1 = resolveIndex(b["to"], n)
    if (i0 > i1) {
      throw new Error(`${locale} 节拍 '${b["beat"]}' 区间反了：${b["from"]} > ${b["to"]}`)
    }
    for (let i = i0; i <= i1; i++) {
      if (!(i >= 0 && i < n)) {
        throw new Error(`${locale} 节拍 '${b["beat"]}' 覆盖到台词范围外：i=${i}（共 ${n} 行）`)
      }
      if (i in cover) {
        throw new Error(`${locale} 第 ${i} 行被两个节拍覆盖：'${cover[i]}' 与 '${b["beat"]}'`)
      }
      cover[i] = b["beat"]
    }
  }
  const gap: number[] = []
  for (let i = 0; i < n; i++) if (!(i in cover)) gap.push(i)
  if (gap.length) {
    throw new Error(`${locale} 有 ${gap.length} 行未被任何节拍覆盖：[${gap.slice(0, 8).join(", ")}]（骨架声明必须完整）`)
  }

  dialogue.forEach((ln, i) => {
    ln["i"] = i
    const b = beats.find((x) => cover[i] === x["beat"])!
    ln["role"] = b["beat"]
    const wantParity = b["ask"]
    let isQ = false
    if (wantParity === "even" || wantParity === "odd") {
      if ((i % 2 === 0) === (wantParity === "even")) {
        isQ = b["askBy"] === "-" || ln["speaker"] === b["askBy"]
      }
    } else if (!["-", "none", ""].includes(wantParity)) {
      throw new Error(`${locale} 节拍 '${b["beat"]}' 的 ask 只能是 even/odd/-，实得 '${wantParity}'`)
    }
    ln["isQuestion"] = isQ
  })
  // 声明了问句、却一条问句都没产生——静默放过等于交出一支「该有思考气泡的轮次
  // 悄悄没了气泡」的片子。**最常见的原因是 even/odd 选错**：奇偶按**绝对行号**算，
  // 不是节拍内偏移，节拍起点落在哪一侧就写哪一侧。
  const nRows = dialogue.length
  for (const b of beats) {
    if (b["ask"] !== "even" && b["ask"] !== "odd") continue
    const i0 = resolveIndex(b["from"], nRows), i1 = resolveIndex(b["to"], nRows)
    if (!dialogue.slice(i0, i1 + 1).some((ln) => ln["isQuestion"])) {
      throw new Error(
        `${locale} 节拍 '${b["beat"]}'（第 ${i0}–${i1} 行）声明了 ask=${b["ask"]}，`
        + "但这一节没有一行被判为问句——多半是 even/odd 写反了："
        + `奇偶按绝对行号算，起点第 ${i0} 行是${i0 % 2 === 0 ? "偶" : "奇"}数。`)
    }
  }
  return dialogue
}

/** 各语种剧本节 → {locale: {...}}；同时按位置骨架标注每行 role/isQuestion。 */
export function parseLocales(md: string, devices: Record<string, Json>, beats: Json[]): Record<string, Json> {
  const locales: Record<string, Json> = {}
  const heads = [...md.matchAll(HEAD_RE)]
  heads.forEach((h, idx) => {
    const locM = LOC_RE.exec(h[0])
    if (!locM) return
    const locale = locM[0]
    const aName = (h[2] ?? "").trim(), bName = (h[3] ?? "").trim()
    const label = (h[1] ?? "").replaceAll(locale, "").trim().replace(/★+$/, "").trim()

    const end = idx + 1 < heads.length
      ? heads[idx + 1]!.index!
      : md.indexOf("\n## ", h.index! + h[0].length)
    const block = md.slice(h.index! + h[0].length, end > 0 ? end : md.length)

    const stM = /\*\*舞台\*\*：(.+?)。\*\*道具装置\*\*：(.+)/.exec(block)
    const noteM = /\*\*文化注记\*\*：(.+)/.exec(block)

    const dialogue = block.split("\n")
      .map(parseLine)
      .filter((ln): ln is Json => ln !== null)
    if (dialogue.length < 2) {
      throw new Error(`${locale} 台词仅 ${dialogue.length} 行，疑似解析漏行`)
    }

    // 位置骨架由 §0.5 声明驱动（applyBeats）：台词行数由剧本自定，骨架是数据不是代码。
    applyBeats(dialogue, beats, locale)

    const dev = devices[locale]
    const prop: Json = {
      scenes: dev ? dev["scenes"] : [],
      device: dev ? { ...dev } : null,
      label: dev ? dev["label"] : "",
      desc: stM ? (stM[2] ?? "").trim() : "",
    }
    locales[locale] = {
      locale,
      langLabel: label,
      aName,
      bName,
      stage: stM ? (stM[1] ?? "").trim() : "",
      prop,
      notes: noteM ? (noteM[1] ?? "").trim() : "",
      dialogue,
    }
  })
  if (Object.keys(devices).length) {
    const extra = Object.keys(devices).filter((k) => !(k in locales)).sort()
    if (extra.length) throw new Error(`§0.2 装置规格表含无剧本语种：[${extra.join(", ")}]`)
  }
  return locales
}

/** locale → 母语名（languages/<lc>/manifest.json）。取不到就退回 locale 码本身。
 * 目录缺失不该拦住解析（Python 侧同款兜底）。 */
function langLabels(): Record<string, string> {
  try {
    const out: Record<string, string> = {}
    for (const [lc, m] of Object.entries(languageManifests())) {
      out[lc] = (m as Json)["label"] || lc
    }
    return out
  } catch {
    return {}
  }
}

/** polyglot：一份**共享**剧本 → [stageInfo, {locale: 薄壳}, dialogue]。
 *
 * 与 dialogue 的根本差别：台词只有一份，三个人轮流在上面说各的语种，
 * 所以 scene["dialogue"] 是**顶层**列表，而 locales[lc]["dialogue"] 是空的——
 * 每个 locale 在这里只是一份「词表 + 装置 + 名字」的壳，供渲染层查 token 词与背景。
 * 这条分界让校验层（scene_schema.unitsOf）能把两种形态走同一套判据。 */
export function parseSharedStage(md: string, devices: Record<string, Json>, beats: Json[]):
  [Json, Record<string, Json>, Json[]] {
  const heads = [...md.matchAll(HEAD_RE_SHARED)]
  if (!heads.length) {
    throw new Error("form=polyglot 需要一个 §2 小节：`### 2.1 <标题>｜<演员A> · <演员B> · …`")
  }
  const h = heads[0]!
  const names = (h[2] ?? "").split("·").map((x) => x.trim()).filter(Boolean)
  const end = md.indexOf("\n## ", h.index! + h[0].length)
  const block = md.slice(h.index! + h[0].length, end > 0 ? end : md.length)

  const stM = /\*\*舞台\*\*：(.+?)。\*\*道具装置\*\*：(.+)/.exec(block)
  const noteM = /\*\*文化注记\*\*：(.+)/.exec(block)
  const dialogue = block.split("\n")
    .map(parseLine)
    .filter((ln): ln is Json => ln !== null)
  if (dialogue.length < 2) {
    throw new Error(`共享剧本台词仅 ${dialogue.length} 行，疑似解析漏行`)
  }

  applyBeats(dialogue, beats, "polyglot")

  const labels = langLabels()
  const locales: Record<string, Json> = {}
  const stage: Json = {
    title: (h[1] ?? "").trim(),
    cast: names,
    stage: stM ? (stM[1] ?? "").trim() : "",
    notes: noteM ? (noteM[1] ?? "").trim() : "",
  }
  const seenLc: string[] = []
  for (const ln of dialogue) {
    const lc = ln["lang"]
    if (!lc) {
      throw new Error(`第 ${ln["i"]} 行没标语种：同台形态每行都要写 \`**角色 · locale**\``)
    }
    if (!seenLc.includes(lc)) seenLc.push(lc)
  }
  for (const lc of seenLc) {
    const dev = devices[lc]
    locales[lc] = {
      locale: lc,
      langLabel: labels[lc] ?? lc,
      aName: seenLc.indexOf(lc) < names.length ? names[seenLc.indexOf(lc)]! : "",
      prop: {
        scenes: dev ? dev["scenes"] : [],
        device: dev ? { ...dev } : null,
        label: dev ? dev["label"] : "",
        desc: stage["stage"],
      },
      stage: stage["stage"],
      notes: stage["notes"],
      dialogue: [],
    }
  }
  if (Object.keys(devices).length) {
    const extra = Object.keys(devices).filter((k) => !(k in locales)).sort()
    if (extra.length) {
      throw new Error(`§0.2 装置规格表含不在共享剧本里的语种：[${extra.join(", ")}]`)
    }
  }
  return [stage, locales, dialogue]
}

/** token 词表 → {locale: [{key, word, forms, romanization}]}（§0 外的 locale 表，
 * 列序 = token 书写序）。单元格 `词 = 别形`（注音）：全部书写形都用于台词命中。 */
export function parseTokenWords(md: string, tokenOrder: string[]): Record<string, Json[]> {
  const n = tokenOrder.length
  const out: Record<string, Json[]> = {}
  for (const [header, body] of tables(md)) {
    if (header[0] !== "locale" || header.length !== n + 1) continue
    if (header.length > 1 && ["chip", "scenes"].includes(header[1] ?? "")) {
      continue                                       // §0 内的规格表，不是词表
    }
    for (const row of body) {
      if (!/^[a-z]{2,3}-[A-Z]{2}$/.test(row[0] ?? "")) continue
      const entries: Json[] = []
      const cells = row.slice(1)
      // Python zip(token_order, row[1:])：按较短一侧截断
      for (let k = 0; k < tokenOrder.length && k < cells.length; k++) {
        const key = tokenOrder[k]!
        let cell = cells[k] ?? ""
        let rom = ""
        const rm = /(?:\(\*([^*]+)\*\)|\*([^*]+)\*)\s*$/.exec(cell)
        if (rm) {
          rom = (rm[1] || rm[2] || "").trim()
          cell = cell.slice(0, rm.index).trim()
        }
        const forms = cell.split(/\s*[=＝]\s*/).map((f) => f.trim()).filter(Boolean)
        entries.push({ key, word: forms.length ? forms[0]! : "", forms, romanization: rom })
      }
      out[row[0]!] = entries
    }
  }
  return out
}

/** 这一行命中哪个 token：取**命中的词里最长的那个**，同长时按 §0.1 序取。
 *
 * 为什么不能「按序第一个命中」：多语种词表里存在**互为子串**的词。
 * 法语 ouest 里含着 est（o-u-e-s-t），而 est 的出场序在 ouest 前面——说到「西」
 * 那一轮，按序命中会点亮「东」的卡片，token 游标从 west 倒退回 east。
 *
 * 为什么不改成「按词边界匹配」：CJK 没有词边界，只能子串；而俄/希/阿/印地等语言
 * 的词表写的是词干，台词里是变格形（красный → красного），一加边界就把它们全打瞎。
 * 「取最长」只在一行命中 ≥2 个 token 时才与旧行为不同——只命中一个词时行为不变。 */
export function matchToken(words: Json[], text: string): Json | null {
  // casefold 的 JS 近似：toLowerCase + ß→ss（德语词表真实语料里唯一的高频分歧）
  const low = text.toLowerCase().replaceAll("ß", "ss")
  const hit = (f: unknown): f is string =>
    typeof f === "string" && !!f && low.includes(f.toLowerCase().replaceAll("ß", "ss"))
  const hits = words.filter((e) => (e["forms"] as unknown[]).some(hit))
  if (!hits.length) return null
  if (hits.length === 1) return hits[0]!
  const orderOf = new Map(words.map((e, i) => [e["key"] as string, i]))
  let best: Json | null = null
  let bestLen = -1
  let bestOrd = 0
  for (const e of hits) {
    const maxLen = Math.max(0, ...(e["forms"] as string[]).filter(hit).map((f) => f.length))
    const ord = -(orderOf.get(e["key"] as string) ?? 0)
    if (maxLen > bestLen || (maxLen === bestLen && ord > bestOrd)) {
      best = e
      bestLen = maxLen
      bestOrd = ord
    }
  }
  return best
}

/** 标注当前 token 与气泡：按书写形（含别形，大小写不敏感）命中台词，按出场序推进。
 * 问句→思考气泡给 token 词预览；答句→提示气泡给联想物（＝该行手势词）。
 * 无 token 场景：只有提示气泡，纯对话。
 *
 * shared = polyglot 的那份顶层台词：此时每行**按自己的语种**取词表（一份剧本混着
 * 三种语言，用哪张词表取决于这行是谁在说），而游标仍跨全剧单调推进。 */
export function annotate(locales: Record<string, Json>, tokenWords: Record<string, Json[]>,
  tokenOrder: string[], tokens: Record<string, string>, shared?: Json[] | null): Record<string, Json> {
  const sweep = (dialogue: Json[], langOf: (ln: Json) => string): void => {
    let cur: string | null = null
    for (const ln of dialogue) {
      const words = tokenWords[langOf(ln)] ?? []
      const hitTok = matchToken(words, ln["text"])
      if (hitTok && hitTok["key"] !== cur) cur = hitTok["key"]    // 首次提到即点亮；后续行沿用
      ln["tokenKey"] = cur
      ln["tokenChip"] = cur ? (tokens[cur] ?? null) : null
      ln["tokenWord"] = words.find((e) => e["key"] === cur)?.["word"] ?? ""
      if (ln["isQuestion"] && ln["tokenWord"]) {
        ln["bubble"] = { kind: "think", text: ln["tokenWord"] }
      } else if (ln["gesture"]["word"]) {
        ln["bubble"] = { kind: "hint", text: ln["gesture"]["word"] }
      } else {
        ln["bubble"] = null
      }
    }
  }

  if (shared != null) {
    sweep(shared, (ln) => ln["lang"] ?? "")
  } else {
    for (const [lc, loc] of Object.entries(locales)) {
      sweep(loc["dialogue"], () => lc)
    }
  }
  return locales
}

/** 解析 + 前置校验 → [doc, outPath]。校验不过就地失败，不产出半成品 scene.json。 */
export function parseScene(sceneId: string, lessonsDir?: string): [Json, string] {
  const [mdPath, outPath] = scenePaths(sceneId, lessonsDir)
  if (!existsSync(mdPath)) {
    throw new FeuilleError(
      `剧本不存在：${mdPath}（已有场景：${findSceneIds(lessonsDir).join(", ") || "无"}）`)
  }
  const md = readFileSync(mdPath, "utf8")
  const spec = parseSpec(md)
  const tokenWords = parseTokenWords(md, spec.tokenOrder)
  const form = spec.meta["form"] || "dialogue"
  let shared: Json[] | null = null
  let stage: Json | null = null
  let locales: Record<string, Json>
  if (form === "polyglot") {
    const r = parseSharedStage(md, spec.devices, spec.beats)
    stage = r[0]
    locales = r[1]
    shared = r[2]
  } else {
    locales = parseLocales(md, spec.devices, spec.beats)
  }
  if (spec.tokenOrder.length) {
    const missing = Object.keys(locales).filter((lc) => !(tokenWords[lc] ?? []).length)
    if (missing.length) {
      throw new Error(`token 词表缺语种：[${missing.join(", ")}]（§5 词表列序 = §0.1 书写序）`)
    }
  }
  locales = annotate(locales, tokenWords, spec.tokenOrder, spec.tokens, shared)

  const doc: Json = {
    id: sceneId,
    sceneId: spec.meta["sceneId"],
    title: spec.meta["title"],
    form,
    source: basename(mdPath),
    noteFloor: spec.meta["noteFloor"] ?? 0,
    askBalance: spec.meta["askBalance"] ?? "any",
    rtlLocales: spec.meta["rtlLocales"],
    durationBudget: spec.meta["durationBudget"] ?? [],
    roles: spec.roles,
    beats: spec.beats,
    speechLevels: spec.levels,
    tokenOrder: spec.tokenOrder,
    tokens: spec.tokens,
    tokenWords,
    locales,
  }
  // cast/stage/dialogue 只在 polyglot 落库：dialogue 课的 scene.json 必须逐字节不变，
  // 多一个空键就是「既有课被改过」的证据。
  if (shared != null) {
    doc["cast"] = spec.cast
    doc["stage"] = stage
    doc["dialogue"] = shared
  }

  // 前置校验：解析完立刻对账，不合规就地失败，不产出半成品 scene.json。
  const errs = validateScene(doc)
  if (errs.length) {
    throw new Error("场景数据不合规（parse 自检）：\n  - " + errs.join("\n  - "))
  }
  return [doc, outPath]
}

// ------------------------------------------------------------------ 落盘口径

/** Python float 落库口径的标记值：str(45.0) = "45.0"（json.dumps 写浮点带 .0），
 * JS Number(45) 写出 "45"——durationBudget 逐字节 parity 依赖这个区分。
 * valueOf/toString 让 scene_schema 的数值比较与报错串免拆箱。 */
class PyFloat {
  constructor(readonly v: number) {}
  valueOf(): number { return this.v }
  toString(): string { return Number.isInteger(this.v) ? `${this.v}.0` : String(this.v) }
}

/** json.dumps(ensure_ascii=False, indent=1) 的字节级对应物：键序 = 插入序、
 * 非 ASCII 不转义、PyFloat 写 Python repr（45.0）、普通数字写整数口径。
 * scene_audio 等模块的落盘 parity 同源复用（manifest.ts 的落盘数据无浮点，
 * JSON.stringify(null, 1) 已够用——两处口径差异是数据形状决定的，不是漂移）。 */
export function pyJsonDump(v: unknown, indent = 0): string {
  const pad = " ".repeat(indent)
  const padIn = " ".repeat(indent + 1)
  if (v === null || v === undefined) return "null"
  if (v instanceof PyFloat) return v.toString()
  if (typeof v === "number") return String(v)
  if (typeof v === "boolean") return String(v)
  if (typeof v === "string") return JSON.stringify(v)
  if (Array.isArray(v)) {
    if (!v.length) return "[]"
    return "[\n" + v.map((x) => padIn + pyJsonDump(x, indent + 1)).join(",\n")
      + "\n" + pad + "]"
  }
  const entries = Object.entries(v as Record<string, unknown>)
  if (!entries.length) return "{}"
  return "{\n" + entries.map(([k, x]) => `${padIn}${JSON.stringify(k)}: ${pyJsonDump(x, indent + 1)}`)
    .join(",\n") + "\n" + pad + "}"
}

/** argparse 同款取值：`--k v` 与 `--k=v` 两种写法都收。 */
function argValue(argv: string[], flag: string): string | undefined {
  const i = argv.indexOf(flag)
  if (i >= 0) return argv[i + 1]
  const p = `${flag}=`
  const j = argv.findIndex((a) => a.startsWith(p))
  return j >= 0 ? argv[j]!.slice(p.length) : undefined
}

/** `feuille scene parse [--scene colors] [--lessons DIR] [--list]`。 */
export function mainParse(argv: string[] = []): number {
  const sceneId = argValue(argv, "--scene") ?? "colors"
  const lessonsDir = argValue(argv, "--lessons")
  if (argv.includes("--list")) {
    for (const sid of findSceneIds(lessonsDir)) console.log(sid)
    return 0
  }

  const [doc, outPath] = parseScene(sceneId, lessonsDir)
  const locales = doc["locales"] as Record<string, Json>
  const tokenOrder = doc["tokenOrder"] as string[]
  writeFileSync(outPath, pyJsonDump(doc), "utf8")

  // ---- 自检：token 零遗漏零重复 / 轮次气泡齐备（各场景通用口径）----
  // polyglot 只有一份共享台词，游标跨全剧推进，所以按「台词在哪儿」而不是
  // 「哪个语种」来列——否则同台那一支永远显示 0 行，看不出是漏了还是没台词。
  const scripts: [string, Json[]][] = "dialogue" in doc
    ? [["stage", (doc["dialogue"] ?? []) as Json[]]]
    : Object.entries(locales).map(([lc, loc]) => [lc, loc["dialogue"] as Json[]])
  const gaps: [string, string[], number][] = []
  const orderDev: [string, string[]][] = []
  console.log(`${"locale".padEnd(8)} ${"rows".padStart(4)} ${"rounds".padStart(6)}  token 序`)
  for (const [locale, dialogue] of scripts) {
    const qs = dialogue.filter((ln) => ln["isQuestion"])
    const seen: string[] = []
    for (const ln of dialogue) {
      if (ln["tokenKey"] && !seen.includes(ln["tokenKey"])) seen.push(ln["tokenKey"])
    }
    const missingBubble = dialogue
      .filter((ln) => ln["role"] === "round" && !ln["bubble"])
      .map((ln) => ln["i"])
    if (tokenOrder.length && missingBubble.length) {
      throw new Error(`${locale} 轮次行缺气泡：行 [${missingBubble.join(", ")}]`)
    }
    if (tokenOrder.length) {
      const setEq = seen.length === tokenOrder.length
        && seen.every((k) => tokenOrder.includes(k))
      if (!setEq) {
        gaps.push([locale, seen, dialogue.length])
      } else if (JSON.stringify(seen) !== JSON.stringify(tokenOrder)) {
        orderDev.push([locale, seen])      // token 齐全，仅出场次序与 §0.1 不同
      }
    }
    console.log(`${locale.padEnd(8)} ${String(dialogue.length).padStart(4)} ${String(qs.length).padStart(6)}`
      + `  ${seen.length ? seen.join(">") : "-"}`)
  }
  console.log(`\n[parse] ${doc["sceneId"]}（${doc["title"]}）：${Object.keys(locales).length} 语种`
    + ` · ${tokenOrder.length} token`
    + ` · 装置 ${Object.values(locales).filter((l: Json) => l["prop"]["device"]).length}`
    + ` -> ${basename(outPath)}`)
  if (gaps.length) {
    console.log("[parse] !! token 有缺（与 §0.1 出场序冲突，需补写轮次）：")
    for (const [locale, seen, rows] of gaps) {
      console.log(`        ${locale}: 缺 ${tokenOrder.filter((k) => !seen.includes(k)).join("/")}`
        + `  原文 ${rows} 行`)
    }
  } else {
    console.log(`[parse] 自检通过：${Object.keys(locales).length} 语种 token 零遗漏零重复、轮次气泡齐备`)
  }
  if (orderDev.length) {
    console.log("[parse] · 次序偏差（token 齐全，出场次序与 §0.1 不同）：")
    for (const [locale, seen] of orderDev) console.log(`        ${locale}: ${seen.join(">")}`)
  }
  return 0
}
