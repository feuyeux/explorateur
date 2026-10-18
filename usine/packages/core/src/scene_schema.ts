// scene_schema.ts — 场景数据前置校验层（parse 与 render 之间）（scene_schema.py 的 TS 移植）
//
// 判定源全部现取 feuille 渲染线注册表，不抄名单（名单必腐烂，纪律 7）：情绪/姿态取
// rig，装置样式取 devices。
//
// 使用契约：`validateScene(scene, personas?, cards?) → 问题列表`（空 = 通过）。
// 纯函数、不做 I/O、不抛异常——反向验证可以直接喂坏数据。选角/班底检查只在给了
// personas 与 cards 两份数据时才跑（parse 自检不给、doctor 全量给）。
//
// **为什么需要**：`scene.json` 此前是自由 dict，没有任何 schema 约束。字段缺失、token
// 对不上、装置 style 拼错，都要等到**渲染时**才炸，或者更糟——不炸但静默出错片。
//
// **人物数量不写死**：合法说话人 = §0.4 `roles` 里**本课自己声明**了谁，就是谁。
// 判定依据全部来自既有事实源，零硬编码：
//   - 情绪集   → rig.MOOD_FACE 的键
//   - 姿态码集 → rig.POSE_CODES（+ 入场专用 bounce_in）
//   - 装置样式 → devices.DEVICE_STYLES
//   - 选角     → personas.json × intro-cards.json cast 表（dialogue）／
//                §0.6 同台表按 `locale + energy` 唯一解出（polyglot）
//
// 接入点（两处）：parse_scene 写完 scene.json 立刻自检（P5-2b 接）；`scene validate`
// 独立复查（main 随 parse_scene/data.sceneDoc 一并接入）。
import { MOOD_FACE, POSE_CODES } from "./rig.js"
import { DEVICE_STYLES } from "./devices.js"

const HEX_RE = /^#[0-9A-Fa-f]{6}$/
const ENERGIES = ["lively", "steady"] as const
// 取景（framing）是**场景级的摆位决定**，不是人物的固有属性：写在剧本 §0.6，
// 不写进 personas.json。
const FRAMINGS = ["full", "seated", "bust"] as const
// 已实现的形态。**刻意只放真的能渲染的**：把未实现的形态写进注册表会造出
// 「声明合法但渲不出来」的坑，比直接报错更难查。
const FORMS = ["dialogue", "polyglot"] as const
// 入场动画不是 pose_for 注册的姿态码，单独放行（scene_video 入口处理）
export const ENTRY_POSE = "bounce_in"

type Scene = Record<string, any>
type PersonaMap = Record<string, any>

/** Python 真值口径（报错判断用）：None/""/0/false/空数组/空对象 皆 falsy。 */
function pyFalsy(v: unknown): boolean {
  if (v == null || v === false || v === 0 || v === "") return true
  if (Array.isArray(v)) return v.length === 0
  if (typeof v === "object") return Object.keys(v as object).length === 0
  return false
}

/** Python repr 口径（报错串用；测试只断关键词，显示层保持单引号习惯）。 */
function repr(v: unknown): string {
  if (typeof v === "string") return `'${v}'`
  if (v === null || v === undefined) return "None"
  if (Array.isArray(v)) return `[${v.map(repr).join(", ")}]`
  if (typeof v === "object") {
    return `{${Object.entries(v as object).map(([k, x]) => `'${k}': ${repr(x)}`).join(", ")}}`
  }
  return String(v)
}

const sortedStrs = (xs: Iterable<string>): string[] => [...xs].sort()

/** 本课声明的合法角色（§0.4 roles 的键），按声明序。**空 = 没人可说话**。 */
export function declaredRoles(scene: Scene): string[] {
  return Object.keys((scene["roles"] ?? {}) as Record<string, unknown>)
}

/** polyglot = 多人同台共用**一份**剧本（`scene["dialogue"]`），不是每语种一份。 */
export function isSharedStage(scene: Scene): boolean {
  return (scene["form"] ?? "dialogue") === "polyglot"
}

/** 渲染单元：[unit_key, locale, lines, loc]。dialogue → 每语种一个；
 * polyglot → 只有一个单元（unit_key = 舞台），台词里每行自带语种。
 * 校验层、渲染层、qa 探针都按这份清单走，不各自 if/else 一遍。 */
export function unitsOf(scene: Scene): [string, string | null, any[], any][] {
  if (isSharedStage(scene)) {
    const lines = (scene["dialogue"] ?? []) as any[]
    const locales = (scene["locales"] ?? {}) as Record<string, any>
    return [["stage", null, lines, { locales }]]
  }
  const out: [string, string | null, any[], any][] = []
  for (const [lc, loc] of Object.entries(scene["locales"] ?? {})) {
    out.push([lc, lc, ((loc as Scene)["dialogue"] ?? []) as any[], loc])
  }
  return out
}

/** 事实源注册表（每次现取，与 Python 延迟 import 同效：注册表永不脱节）。 */
function registries(): { moods: Set<string>; poses: Set<string>; device_styles: Set<string> } {
  return {
    moods: new Set(Object.keys(MOOD_FACE)),
    poses: new Set([...POSE_CODES, ENTRY_POSE]),
    device_styles: new Set(Object.keys(DEVICE_STYLES)),
  }
}

/** 校验 scene dict。返回问题字符串列表（空 = 通过）。
 *
 * @param scene parse_scene 产出的 scene.json 内容
 * @param personas {id: persona}；给了才查选角与班底覆盖
 * @param cards intro-cards.json 全文（含 cast 表）；给了才查选角 */
export function validateScene(scene: Scene, personas?: PersonaMap | null, cards?: Scene | null): string[] {
  const reg = registries()
  const errs: string[] = []
  const bad = errs.push.bind(errs)

  // ---- 1. 顶层必填 ----
  for (const k of ["id", "sceneId", "title", "tokenOrder", "tokens", "tokenWords", "locales"]) {
    if (pyFalsy(scene[k])) bad(`顶层字段缺失或为空：${k}`)
  }
  if (errs.length) return errs               // 必填都没齐，后面读会 KeyError

  const form = scene["form"] ?? "dialogue"
  const shared = isSharedStage(scene)
  const roles = (scene["roles"] ?? {}) as Record<string, any>
  const allowedSpeakers = declaredRoles(scene)

  // ---- 2. 时长预算 ----
  const db = scene["durationBudget"]
  if (db != null) {
    if (!Array.isArray(db) || db.length !== 2) {
      bad(`durationBudget 应为 [lo, hi] 两元素，实得 ${repr(db)}`)
    } else if (!(Number(db[0]) < Number(db[1]))) {
      bad(`durationBudget 区间反了：${db[0]} ≥ ${db[1]}`)
    }
  }

  // ---- 3. RTL 名单必须指向真实存在的 locale ----
  const locales = scene["locales"] as Record<string, any>
  for (const lc of (scene["rtlLocales"] ?? []) as string[]) {
    if (!(lc in locales)) bad(`rtlLocales 列了不存在的 locale：${lc}`)
  }

  // ---- 4. token 表：键集一致 + chip 两型 ----
  const order = [...(scene["tokenOrder"] as string[])]
  const tokens = scene["tokens"] as Record<string, any>
  const missing = order.filter((k) => !(k in tokens))
  const extra = Object.keys(tokens).filter((k) => !order.includes(k))
  if (missing.length) bad(`tokenOrder 有、tokens 没有：${repr(missing)}`)
  if (extra.length) bad(`tokens 有、tokenOrder 没有：${repr(extra)}`)
  if (new Set(order).size !== order.length) {
    const dup = [...new Set(order)].filter((k) => order.filter((x) => x === k).length > 1)
    bad(`tokenOrder 有重复 key：${repr(dup)}`)
  }
  for (const k of order) {
    const chip = tokens[k]
    if (chip == null) continue
    const s = String(chip).trim()
    // chip 两型的真实契约在 devices.chipColor：以 # 开头 = 色片（须是 #RRGGBB），
    // 其余非空字符串 = 字牌（走文字层贴图）。parse_spec 会把 md 里的引号 strip 掉，
    // 所以 `"1"` 与 `1` 在落库后不可区分——**引号只是书写习惯，不是判据**。
    if (!s) bad(`token ${repr(k)} 的 chip 为空`)
    else if (s.startsWith("#") && !HEX_RE.test(s)) {
      bad(`token ${repr(k)} 的 chip 非法：${repr(chip)}（以 # 开头必须是 #RRGGBB）`)
    }
  }

  // ---- 5. §0.4 角色声明（先于台词：说话人合法性全靠它）----
  if (!Object.keys(roles).length) {
    bad("§0.4 没声明任何角色——合法说话人由本课声明驱动，没有声明就没有人能说话")
  }
  for (const [r, energy] of Object.entries(roles)) {
    if (!(ENERGIES as readonly string[]).includes(energy)) {
      bad(`roles[${r}] 的 energy=${repr(energy)} 不认识（${repr(sortedStrs(ENERGIES))}）`)
    }
  }

  // ---- 5b. §0.6 同台表（仅 polyglot 需要：角色 ↔ 语种 ↔ 取景的绑定）----
  const cast = (scene["cast"] ?? []) as Scene[]
  const castRoles = cast.map((c) => c["role"])
  if (shared) {
    if (!cast.length) {
      bad("form=polyglot 但缺 §0.6 同台表——每个角色必须绑定一个语种与一种取景")
    }
    for (const c of cast) {
      const r = c["role"]
      if (!(r in roles)) bad(`§0.6 声明了 §0.4 没有的角色：${repr(r)}`)
      if (!c["locale"]) {
        bad(`§0.6 角色 ${repr(r)} 没绑定 locale（polyglot 里每行台词都要认语种）`)
      } else if (!(c["locale"] in locales)) {
        bad(`§0.6 角色 ${repr(r)} 绑定的 locale 不在 locales 内：${repr(c["locale"])}`)
      }
      const fr = c["framing"]
      if (!(FRAMINGS as readonly string[]).includes(fr)) {
        bad(`§0.6 角色 ${repr(r)} 的 framing=${repr(fr)} 不认识（${repr(sortedStrs(FRAMINGS))}）`)
      }
    }
    if (new Set(castRoles).size !== castRoles.length) {
      bad(`§0.6 有角色重复：${repr(castRoles)}`)
    }
    const missingInCast = Object.keys(roles).filter((r) => !castRoles.includes(r))
    if (missingInCast.length) {
      bad(`§0.4 声明了角色但 §0.6 没给他安排语种/取景：${repr(missingInCast)}`)
    }
    const used = new Set<unknown>()
    for (const [, , lines] of unitsOf(scene)) for (const ln of lines) used.add(ln["speaker"])
    const ghost = sortedStrs([...used].filter((x) => x && !allowedSpeakers.includes(x as string)) as string[])
    if (ghost.length) bad(`台词里出现了 §0.4 未声明的角色：${repr(ghost)}`)
  } else {
    for (const c of cast) {
      bad(`form=dialogue 不该有 §0.6 同台表（角色 ${repr(c["role"])}）——`
        + "dialogue 形态的角色按语种各配各的")
    }
  }

  // ---- 6. 逐渲染单元 ----
  for (const [unitKey, lc, lines, loc] of unitsOf(scene)) {
    if (shared) {
      if (!lines.length) bad("共享剧本（polyglot）的台词为空")
      // 每行必须自带语种：同台一份剧本混着好几种语言，annotate 要按**这行是谁在说**
      // 去取词表。缺了语标，那一行会去查一张空壳的词表，token 静默不亮——症状要到
      // 看片才发现「这一轮怎么没点亮」。解析层会拒，但 scene.json 是能被手改、
      // 也能被别的工具写出来的，校验层不能只在解析层守这条。
      const noLang = lines.filter((ln) => !(ln["lang"] || "")).map((ln) => ln["i"])
      if (noLang.length) {
        bad(`共享剧本里这些行没标语种：${repr(noLang.slice(0, 8))}——`
          + "同台形态每行都要写 `**角色 · locale**`")
      }
      for (const ln of lines) {
        const unitLang = ln["lang"]    // 行内语标；不遮蔽外层循环变量 lc（渲染单元语种）
        if (unitLang && !(unitLang in locales)) {
          bad(`#${ln["i"]}: 台词行标的 locale ${repr(unitLang)} 不在本课 locales 内`)
        }
      }
      checkLines(bad, lines, unitKey, allowedSpeakers, reg, order)
      checkNotes(bad, lines, scene)
      continue
    }

    for (const k of ["langLabel", "aName", "bName"]) {
      if (pyFalsy(loc[k])) bad(`${lc}: 字段缺失或为空 ${k}`)
    }
    if (pyFalsy(loc["dialogue"])) bad(`${lc}: dialogue 为空（该语种没有台词）`)

    // 6a. 词表覆盖：§5 词表必须与 §0 token 书写序一致
    const words = ((scene["tokenWords"] ?? {}) as Record<string, any>)[lc as string]
    if (words == null) {
      bad(`${lc}: tokenWords 缺该语种（§5 词表必须逐语种齐备）`)
    } else {
      const wkeys = (words as Scene[]).map((w) => w["key"])
      if (JSON.stringify(wkeys) !== JSON.stringify(order)) {
        bad(`${lc}: §5 词表列序/键集与 §0.1 token 书写序不一致：${repr(wkeys)} ≠ ${repr(order)}`)
      }
    }

    // 6b. 装置样式在注册表内
    const dev = ((loc["prop"] ?? {}) as Scene)["device"]
    if (dev) {
      const st = dev["style"]
      if (!reg.device_styles.has(st)) {
        bad(`${lc}: 装置 style ${repr(st)} 不在 DEVICE_STYLES 注册表内`)
      }
    }

    // 6c. 台词行
    checkLines(bad, lines, unitKey, allowedSpeakers, reg, order, lc as string)
    checkNotes(bad, lines, scene, lc as string)
  }

  // polyglot 的词表同样逐语种校验（台词按行取语种，词表按语种给）
  if (shared) {
    for (const lc of Object.keys(locales)) {
      const words = ((scene["tokenWords"] ?? {}) as Record<string, any>)[lc]
      if (words == null) {
        bad(`${lc}: tokenWords 缺该语种（同台每行台词都按自己的语种取词）`)
      } else {
        const wkeys = (words as Scene[]).map((w) => w["key"])
        if (JSON.stringify(wkeys) !== JSON.stringify(order)) {
          bad(`${lc}: §5 词表列序/键集与 §0.1 token 书写序不一致：${repr(wkeys)} ≠ ${repr(order)}`)
        }
      }
      const dev = ((locales[lc]["prop"] ?? {}) as Scene)["device"]
      if (dev && !reg.device_styles.has(dev["style"])) {
        bad(`${lc}: 装置 style ${repr(dev["style"])} 不在 DEVICE_STYLES 注册表内`)
      }
    }
  }

  // ---- 7. 语体差承诺（§0.3）：列了就必须有非空 marker ----
  for (const [lc, spec] of Object.entries((scene["speechLevels"] ?? {}) as Record<string, any>)) {
    if (!(lc in locales)) bad(`speechLevels 列了不存在的 locale：${lc}`)
    if (pyFalsy((spec ?? {})["marker"])) {
      bad(`speechLevels[${lc}] 缺 marker：§0.3 承诺的语体差没有验收标记，`
        + "这条承诺在文本层无法验证（等于没承诺）")
    }
  }

  // ---- 8. 选角可解（需要班底数据）----
  if (personas != null && cards != null) {
    if (shared) {
      checkSharedCast(bad, scene, personas, cards, cast)
    } else {
      for (const lc of Object.keys(locales)) {
        for (const role of allowedSpeakers) {
          // 姓名槽位随角色名走：§2 的小节头写 `<role>Name`（A→aName / B→bName）。
          // 沿用既有键名，既有课零改动；第三个人只需在 md 里多写一个 cName。
          const want = (locales[lc] as Scene)[`${role.toLowerCase()}Name`]
          const p = findDialogueRole(personas, cards, lc, role)
          if (p == null) {
            bad(`${lc} ${role} 角选派异常：班底里没有该 locale 的人或 cast 表没派角`)
            continue
          }
          const got = (p["name"] ?? {})["native"]
          if (want && got !== want) {
            bad(`${lc} ${role} 角与剧本 §4 不符：档案 ${repr(got)} ≠ 剧本 ${repr(want)}`)
          }
          checkEnergy(bad, p, role, roles[role], lc)
        }
        const rosterLocales = new Set(Object.values(personas).map((p) => (p as Scene)["locale"]))
        if (!rosterLocales.has(lc)) {
          bad(`${lc}: 班底里没有这个语种的人（personas.json 无对应 locale）`)
        }
      }
    }
    // 8b. 跨文件彩蛋引用
    checkEggs(bad, scene, personas, cards, cast, allowedSpeakers)
  }

  // ---- 9. 形态 / 骨架声明（§0.4 §0.5）----
  if (!(FORMS as readonly string[]).includes(form)) {
    bad(`form=${repr(form)} 尚未实现（已实现：${repr(sortedStrs(FORMS))}）`)
  }

  const beats = (scene["beats"] ?? []) as Scene[]
  if (!beats.length) {
    bad("§0.5 缺骨架节拍表（beats）——台词行的角色/问句归属没有来源")
  }
  for (const b of beats) {
    if (!["even", "odd", "-", "none", ""].includes(b["ask"])) {
      bad(`节拍 ${repr(b["beat"])} 的 ask=${repr(b["ask"])} 只能是 even/odd/-`)
    }
    const ab = b["askBy"] ?? "-"
    if (ab !== "-" && !allowedSpeakers.includes(ab)) {
      bad(`节拍 ${repr(b["beat"])} 的 askBy=${repr(ab)} 未在 §0.4 roles 里声明`)
    }
  }
  const seenBeats = beats.map((b) => b["beat"])
  if (new Set(seenBeats).size !== seenBeats.length) {
    bad(`节拍名有重复：${repr(seenBeats)}`)
  }

  return errs
}

// ------------------------------------------------------------------ 台词行（两形态共用）

function checkLines(bad: (m: string) => number, lines: any[], _unitKey: string,
  allowed: string[], reg: { moods: Set<string>; poses: Set<string>; device_styles: Set<string> },
  order: string[], locale?: string): void {
  /** 逐行校验：说话人 ∈ §0.4 声明的角色、情绪/手势/词在注册表内、台词非空。 */
  const where = locale ? `${locale} ` : ""
  if (!allowed.length) {
    bad(`${where}台词存在但 §0.4 没声明任何角色，无法判断说话人是否合法`)
    return
  }
  const seenI = new Set<unknown>()
  for (const ln of lines as Scene[]) {
    const i = ln["i"]
    if (seenI.has(i)) bad(`${where}台词行号重复 i=${i}`)
    seenI.add(i)
    const sp = ln["speaker"]
    if (!allowed.includes(sp)) {
      bad(`${where}#${i}: speaker=${repr(sp)} 非法（本课 §0.4 声明的角色：${repr(allowed)}）`)
    }
    if (!reg.moods.has(ln["mood"])) {
      bad(`${where}#${i}: mood=${repr(ln["mood"])} 不在情绪表内（${repr(sortedStrs(reg.moods))}）`)
    }
    for (const pose of (((ln["gesture"] ?? {}) as Scene)["poses"] ?? []) as string[]) {
      if (!reg.poses.has(pose)) bad(`${where}#${i}: 手势码 ${repr(pose)} 不在 POSE_CODES 注册表内`)
    }
    const tk = ln["tokenKey"]
    if (tk && !order.includes(tk)) bad(`${where}#${i}: tokenKey=${repr(tk)} 不在 §0.1 token 表内`)
    if (!String(ln["text"] ?? "").trim()) bad(`${where}#${i}: 台词为空`)
  }
}

function checkNotes(bad: (m: string) => number, lines: any[], scene: Scene, locale?: string): void {
  /** 该课自己声明的 ⚑ 注记行下限——在 parse 阶段就查，不等渲染。
   * （门禁要放在「还能便宜地修」的地方：处方是加 ⚑ 段，改文本远比改代码便宜。） */
  const floor = Math.trunc(Number(scene["noteFloor"] || 0))
  if (!floor) return
  const nNote = (lines as Scene[]).filter((ln) => ln["note"]).length
  if (nNote < floor) {
    bad(`${locale ?? ""}: ⚑ 注记行 ${nNote} < §0 noteFloor 声明的 ${floor}`
      + "（注记按设计可选，但本课声明了就要够）")
  }
}

// ------------------------------------------------------------------ 选角

function findDialogueRole(personas: PersonaMap, cards: Scene, locale: string, role: string): Scene | null {
  /** dialogue 形态：某语种的某角色 = 班底里 locale 匹配且 cast 表派了这个角的那一个。 */
  const ids = Object.keys(personas).filter(
    (pid) => (personas[pid] as Scene)["locale"] === locale && ((cards["cast"] ?? {}) as Record<string, any>)[pid] === role)
  return ids.length === 1 ? (personas[ids[0]!] as Scene) : null
}

function checkSharedCast(bad: (m: string) => number, scene: Scene, personas: PersonaMap,
  _cards: Scene, cast: Scene[]): void {
  /** polyglot 形态：角色 ↔ 演员靠 §0.6 的 `locale + energy` 唯一解出。
   *
   * 为什么不用 intro-cards 的 cast 表：那张表记的是**亮相卡**里谁演 A/B，一个演员
   * 在全表里只有一个角色。同台三人分属三个语种，卡表里根本没有第三个人的角。 */
  const roles = (scene["roles"] ?? {}) as Record<string, any>
  for (const c of cast) {
    const role = c["role"], lc = c["locale"]
    if (!role || !lc) continue
    const wantEnergy = roles[role]
    const cands = Object.values(personas).filter((p) => (p as Scene)["locale"] === lc) as Scene[]
    if (!cands.length) {
      bad(`${role} 角绑定 ${lc}，但班底里没有这个语种的人`)
      continue
    }
    const picked = wantEnergy ? cands.filter((p) => p["energy"] === wantEnergy) : cands
    if (picked.length !== 1) {
      bad(`${role} 角在 ${lc} 里按 energy=${repr(wantEnergy)} 解出 ${picked.length} 个：`
        + `${picked.length ? repr(picked.map((p) => p["name"]["native"])) : "（无）"}——必须唯一`)
      continue
    }
    checkEnergy(bad, picked[0]!, role, wantEnergy, lc, `${lc} `)
  }
}

function checkEnergy(bad: (m: string) => number, p: Scene, role: string, wantEnergy: unknown,
  locale: string, label = ""): void {
  /** §0.4 声明的角色气质要与实际选角对账：A/B 选反是真实发生过的错误，
   * 而剧本只写姓名、看不出谁活泼谁沉稳——声明就是为这件事准备的。 */
  if (wantEnergy && p["energy"] !== wantEnergy) {
    bad(`${label}${role} 角气质与 §0.4 声明不符：${(p["name"] ?? {})["native"]} 的 energy=`
      + `${repr(p["energy"])} ≠ 声明 ${repr(wantEnergy)}`)
  }
}

function checkEggs(bad: (m: string) => number, scene: Scene, personas: PersonaMap,
  cards: Scene, cast: Scene[], allowedSpeakers: string[]): void {
  /** 剧本里「班底彩蛋：江远夹克 #35486E」这类批注必须指向**本课某位演员真实色板**里的值。
   * 抓的是 md 里的悬空引用：人设改色板后，剧本里的旧色值不会自动跟着变。 */
  for (const [, lc, lines] of unitsOf(scene)) {
    let performers: Scene[]
    if (lc != null) {
      performers = allowedSpeakers
        .map((r) => findDialogueRole(personas, cards, lc, r))
        .filter((p): p is Scene => p != null)
    } else {
      performers = cast
        .map((c) => findSharedRole(personas, scene, c))
        .filter((p): p is Scene => p != null)
    }
    for (const ln of lines as Scene[]) {
      const egg = ln["easterEgg"]
      if (!egg) continue
      const i = ln["i"]
      const hexv = String(egg["hex"] ?? "").toUpperCase()
      const label = egg["label"] ?? ""
      const named = performers.filter(
        (p) => (p["name"] ?? {})["native"] && label.includes((p["name"] ?? {})["native"]))
      if (named.length === 1) {
        const owner = named[0]!
        if (!paletteHexes(owner).has(hexv)) {
          bad(`${lc ?? ""} #${i}: 彩蛋色值 ${hexv} 不在 ${owner["name"]["native"]} `
            + `的色板里（标注「${label}」）——换角/改色板后剧本没跟着改`)
        }
      } else if (named.length > 1) {
        bad(`${lc ?? ""} #${i}: 彩蛋标注「${label}」同时匹配多位演员，指代不唯一`)
      } else {
        const union = new Set<string>()
        for (const p of performers) for (const h of paletteHexes(p)) union.add(h)
        if (!union.has(hexv)) {
          bad(`${lc ?? ""} #${i}: 彩蛋色值 ${hexv} 不在本课任何演员的色板里`
            + `（标注「${label}」未能解析到演员名）`)
        }
      }
    }
  }
}

function findSharedRole(personas: PersonaMap, scene: Scene, c: Scene): Scene | null {
  /** 同台表里某个角色解出的演员（与 checkSharedCast 同一判据，供彩蛋校验复用）。 */
  const want = ((scene["roles"] ?? {}) as Record<string, any>)[c["role"]]
  const cands = Object.values(personas).filter((p) => (p as Scene)["locale"] === c["locale"]) as Scene[]
  const picked = want ? cands.filter((p) => p["energy"] === want) : cands
  return picked.length === 1 ? picked[0]! : null
}

function paletteHexes(persona: Scene): Set<string> {
  /** 一个人设身上所有可被剧本引用的 hex：色板各槽 + identity。 */
  const out = new Set<string>()
  for (const v of Object.values((persona["palette"] ?? {}) as Record<string, unknown>)) {
    if (typeof v === "string" && v.startsWith("#")) out.add(v.toUpperCase())
  }
  const ident = persona["identity"]
  if (typeof ident === "string" && ident.startsWith("#")) out.add(ident.toUpperCase())
  return out
}
