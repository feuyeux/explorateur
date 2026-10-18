// persona.ts — 人设契约校验器（persona.py 的 TS 移植；②③ 数据检查层的 persona 半边）
//
// 契约文档：`personas/schema.md`。本模块是它的机器判定：
// `validatePersona(p) → 问题列表`（纯函数、不做 I/O——因此反向验证可以直接喂坏数据）。
//
// **合法值一律现取注册表，不复制**（纪律 7）：
// - 脸型 → rig.FACE_SPECS 的键（那正是绘制规格的唯一事实源）；
// - moves 槽位值 → rig.POSE_CODES 的键（姿态库的唯一事实源）；
// - 声线安全域 → tts.SAFE_RATE / SAFE_PITCH（|rate|≤20%、|pitch|≤12Hz——越界劈嗓）。
//
// **班底级不变量**（选角规则）：每语种恰两人、一男一女、一活泼一沉稳
// （活泼者当 A / 沉稳者当 B 的戏剧分工天然成立）；id 全局唯一（id = rnd 种子
// 命名空间，撞 id = 幂等破坏）。`validateRoster(personas)` 判这两条。
//
// 字段存在性按 schema 实存口径：`movement.seed`/`gaze` 不落 JSON（seed ≡ id、
// gaze 由 rig 统一实现）；`name.gloss`/`voice.timbre`/`relation`/`quirk` 是
// 档案维度，缺了不炸渲染但档案不完整——按「档案字段缺失」报。
import { FACE_SPECS, POSE_CODES } from "./rig.js"
import { SAFE_PITCH, SAFE_RATE, parseSigned } from "./tts/pure.js"
import { personasDoc } from "./data.js"

const HEX_RE = /^#[0-9A-Fa-f]{6}$/
const LOCALE_RE = /^[a-z]{2,3}-[A-Z]{2}$/
const SLOTS = ["point", "palm_open", "both_hands", "nod", "jump_celebrate",
  "mini_jump", "wave", "scratch_head", "deadpan_nod"] as const
const PHYSICS = ["swing", "bounce", "reflect"] as const
const OUTFIT_KINDS = ["tunic", "pinafore", "vest"] as const

/** Python repr 口径（报错串用；测试只断关键词，显示层保持单引号习惯）。 */
function repr(v: unknown): string {
  if (typeof v === "string") return `'${v}'`
  if (v === null || v === undefined) return "None"
  if (typeof v === "object") return JSON.stringify(v)
  return String(v)
}

function badHex(v: unknown): boolean {
  return typeof v !== "string" || !HEX_RE.test(v)
}

const isBlankStr = (v: unknown): boolean => typeof v !== "string" || v.trim() === ""

/** 一个人设的全部问题（空列表 = 通过）。where 用于批量报错时定位（如 id）。 */
export function validatePersona(p: Record<string, any>, where = ""): string[] {
  const idv = p["id"]
  const w = where || (idv ? String(idv) : "<无 id>")
  const problems: string[] = []
  const add = problems.push.bind(problems)

  // ---- 身份 ----
  if (isBlankStr(p["id"])) {
    add(`${w}: id 缺失或为空（id = rnd 种子命名空间，空 id 破坏幂等）`)
  }
  if (typeof p["locale"] !== "string" || !LOCALE_RE.test(p["locale"] ?? "")) {
    add(`${w}: locale 非法（${repr(p["locale"])}，应为 xx-XX）`)
  }
  if (p["gender"] !== "female" && p["gender"] !== "male") {
    add(`${w}: gender 非法（${repr(p["gender"])}）`)
  }
  if (p["energy"] !== "lively" && p["energy"] !== "steady") {
    add(`${w}: energy 非法（${repr(p["energy"])}，活泼/沉稳决定 bounce 与语速基线族）`)
  }
  const name = p["name"] ?? {}
  for (const k of ["native", "latin"] as const) {
    if (isBlankStr(name[k])) add(`${w}: name.${k} 缺失`)
  }
  for (const k of ["archetype", "quirk"] as const) {
    if (isBlankStr(p[k])) add(`${w}: 档案字段 ${k} 缺失（28 人全量入档）`)
  }
  const rel = p["relation"] ?? {}
  if (isBlankStr(rel["partner"])) add(`${w}: relation.partner 缺失（语种内搭档）`)

  // ---- 声线（消费方 = tts / rig 的情绪增量）----
  // 实存 JSON 无 engine 字段（引擎由 tts 固定为 edge-tts）；带上了就必须对。
  const v = p["voice"] ?? {}
  if (v["engine"] !== undefined && v["engine"] !== null && v["engine"] !== "edge-tts") {
    add(`${w}: voice.engine 应为 edge-tts（得 ${repr(v["engine"])}）`)
  }
  if (isBlankStr(v["voiceId"])) add(`${w}: voiceId 缺失（固定音色，永不随场景重选）`)
  const r = parseSigned(v["rate"] ?? "+0%")
  const pi = parseSigned(v["pitch"] ?? "+0Hz")
  if (!(SAFE_RATE[0] <= r && r <= SAFE_RATE[1])) {
    add(`${w}: rate ${repr(v["rate"])} 越出安全域 ±${SAFE_RATE[1]}%（劈嗓）`)
  }
  if (!(SAFE_PITCH[0] <= pi && pi <= SAFE_PITCH[1])) {
    add(`${w}: pitch ${repr(v["pitch"])} 越出安全域 ±${SAFE_PITCH[1]}Hz`)
  }
  if (isBlankStr(v["timbre"])) add(`${w}: voice.timbre 缺失（选型依据）`)

  // ---- 运动（消费方 = rig.faceGeo / drawCharacter）----
  const m = p["movement"] ?? {}
  const face = m["face"]
  if (!Object.prototype.hasOwnProperty.call(FACE_SPECS, face)) {  // ← 现取注册表
    add(`${w}: movement.face ${repr(face)} 不在 FACE_SPECS（${Object.keys(FACE_SPECS).sort()}）`)
  }
  for (const k of ["bounce", "blinkCycleSec", "breathAmp"] as const) {
    const val = m[k]
    // Python：not isinstance(val,(int,float)) or isinstance(val,bool) or val <= 0
    // NaN 两边都放行（val <= 0 假）——按原式镜像，不「顺手修正」
    if (typeof val !== "number" || val <= 0) {
      add(`${w}: movement.${k} 应为正数（得 ${repr(val)}）`)
    }
  }

  // ---- moves 槽位表（值必须是姿态库里的码）----
  const moves = p["moves"] ?? {}
  for (const [slot, code] of Object.entries(moves)) {
    if (!(SLOTS as readonly string[]).includes(slot)) {
      add(`${w}: moves 槽位 ${repr(slot)} 不在已知槽位表（${SLOTS}）——私加槽位=剧本语义漂移`)
    }
    if (!POSE_CODES.has(String(code))) {  // ← 现取注册表
      add(`${w}: moves.${slot} = ${repr(code)} 不在 POSE_CODES（姿态库 ${POSE_CODES.size} 码）`)
    }
  }

  // ---- 调色板（六键、hex；identity 在**顶层**（语种标识色，每人恰一处点缀）；
  //      描边/五官常量色走 rig.THEME，不在此表）----
  if (badHex(p["identity"])) {
    add(`${w}: identity 非法（${repr(p["identity"])}，应为 #RRGGBB）`)
  }
  const pal = p["palette"] ?? {}
  for (const k of ["hair", "hairHighlight", "skin", "skinShade",
    "outfitTop", "outfitBottom"] as const) {
    if (badHex(pal[k])) {
      add(`${w}: palette.${k} 非法（${repr(pal[k])}，应为 #RRGGBB）`)
    }
  }
  // hairStyle 的合法形由 drawCharacter 的分支决定（无注册表可现取）——只判非空
  if (isBlankStr(p["hairStyle"])) add(`${w}: hairStyle 缺失（绘制分支按它选发型）`)

  // ---- 可选段 ----
  const outfit = p["outfit"] ?? {}
  if ("bottom" in outfit && outfit["bottom"] !== "skirt") {
    add(`${w}: outfit.bottom 非法（${repr(outfit["bottom"])}）`)
  }
  if ("kind" in outfit && !(OUTFIT_KINDS as readonly string[]).includes(outfit["kind"])) {
    add(`${w}: outfit.kind 非法（${repr(outfit["kind"])}，${OUTFIT_KINDS}）`)
  }
  // ---- 挂件（实存口径：{code, accent?, physics?}——code 是绘制分支的判据，
  //      如 qa_shape 以 code=="beard" 分流下颌探针）----
  let accs = p["accessories"] ?? []
  if (!Array.isArray(accs)) {
    add(`${w}: accessories 应为列表`)
    accs = []
  }
  for (let i = 0; i < accs.length; i++) {
    const a = accs[i]
    if (typeof a !== "object" || a === null) {
      add(`${w}: accessories[${i}] 应为对象`)
      continue
    }
    if (isBlankStr(a["code"])) add(`${w}: accessories[${i}].code 缺失（绘制分支按它选挂件）`)
    if (a["accent"] !== undefined && a["accent"] !== null && typeof a["accent"] !== "boolean") {
      add(`${w}: accessories[${i}].accent 应为布尔`)
    }
    if (a["physics"] !== undefined && a["physics"] !== null
      && !(PHYSICS as readonly string[]).includes(a["physics"])) {
      add(`${w}: accessories[${i}].physics 非法（${repr(a["physics"])}）`)
    }
  }
  const skin = p["skin"] ?? {}
  const patches = skin["patches"] ?? []
  for (let i = 0; i < patches.length; i++) {
    if (badHex(patches[i]?.["color"])) add(`${w}: skin.patches[${i}].color 非法 hex`)
  }
  return problems
}

/** 班底级不变量：id 唯一；每语种恰 {一男一女} × {一活泼一沉稳}。 */
export function validateRoster(personas: Record<string, any>[]): string[] {
  const problems: string[] = []
  const ids = new Map<string, number>()
  const byLocale = new Map<string, Record<string, any>[]>()
  for (const p of personas) {
    const pid = p["id"]
    ids.set(pid, (ids.get(pid) ?? 0) + 1)
    const loc = p["locale"] ?? "?"
    if (!byLocale.has(loc)) byLocale.set(loc, [])
    byLocale.get(loc)!.push(p)
  }
  for (const [pid, n] of ids) {
    if (n > 1) {
      problems.push(`id ${repr(pid)} 重复 ${n} 次（id = 种子命名空间，撞 id 破坏幂等）`)
    }
  }
  for (const loc of [...byLocale.keys()].sort()) {
    const ps = byLocale.get(loc)!
    const genders = ps.map((p) => p["gender"] ?? "?").sort()
    const energies = ps.map((p) => p["energy"] ?? "?").sort()
    if (ps.length !== 2 || genders.join(",") !== "female,male"
      || energies.join(",") !== "lively,steady") {
      problems.push(
        `${loc}: 班底配对应为 一男一女 × 一活泼一沉稳（实得 gender=[${genders}] `
        + `energy=[${energies}]，${ps.length} 人）——活泼当 A / 沉稳当 B 的选角分工依赖它`)
    }
  }
  return problems
}

/** cli 路由入口：`feuille persona validate [--personas DIR]`（无参可调用——
 * 缺省体检班底目录）。退出码：有问题 → 1。
 *
 * 人设契约的**独立**体检入口：不经过任何 skill 文档或课件目录也能跑。
 * 判定本体就是上面的 validatePersona / validateRoster（纯函数，反向验证在
 * persona.test.ts）；这里只做取数与报告。
 * 逐人走**原始清单**（personasDoc()）而不是 {id: persona} 索引——
 * 索引会把重复 id 静默折叠成一个，班底级「id 唯一」就永远验不出来。
 */
export function mainValidate(argv: string[] = []): number {
  const i = argv.indexOf("--personas")
  const dir = i >= 0 ? argv[i + 1] : undefined
  const plist = personasDoc(dir)["personas"] as Record<string, any>[]

  const problems: string[] = []
  for (const p of plist) problems.push(...validatePersona(p))
  problems.push(...validateRoster(plist))

  console.log("=".repeat(66))
  console.log(`人设契约体检：${plist.length} 人班底（validatePersona 逐人 + 班底不变量）`)
  console.log("=".repeat(66))
  if (!problems.length) {
    console.log("  PERSONA PASS：逐人零问题；班底不变量全过"
      + "（id 唯一 / 每语种一男一女 × 一活泼一沉稳）")
    return 0
  }
  for (const e of problems) console.log(`  FAIL ${e}`)
  console.log(`\n${problems.length} 项不合规`)
  return 1
}
