// audit.ts — 格律计数审计（audit.py 的 TS 移植）：计数器库 + 声称 vs 实测驱动。
//
// 三套音节计数器（印地 Matra / 阿拉伯长短音节 / 希伯来音节）。阿拉伯语计数
// 按「一核一音节」：辅音+sukun 吞并音节的数法会多数（实测 الصَّبَا 曾被数成 4，
// 实际 3）。
//
// **机制 / 内容分离**：每语言计数器是**机制**（本模块）；手写音节拆分 SPLITS、
// 声称表 CLAIMED、语种顺序是**内容**（归内容项目持有）。
//
// **审计纪律（工作流 ④ 检查的三态）**：
// 1. **手写拆分供人眼复核 + 算法交叉验证，不一致以算法为准并告警**——
//   审计结果本身必须可复核，不可复核的审计是装饰。
// 2. **声称必须可测**：声称与实测不符 = ❌；验证不了的体式声明**主动撤下**，
//   「不作声称」是合法的第三态（既不算通过也不算待处理）——
//   阿拉伯语古诗律无法自证、希伯来语 Parallelismus 的准则是意义对位不是拍数，
//   这两处宁可留白，也不换一个同样验证不了的标签。
//
// unicodedata 的对应物：`\p{M}`（组合记号类 Mn/Me/Mf 的并集，与 Python
// category().startswith("M") 同域）+ String.normalize("NFC"/"NFD")。
const COMBINING = /\p{M}/u

/** Python list repr 口径（`[7, 7]` 带空格）——审计消息给人读，格式与 Python 侧一致。 */
function pyList(a: number[] | null): string {
  return a === null ? "None" : `[${a.join(", ")}]`
}

// ---------------------------------------------------------------- 印地语 Matra
// 规则：辅音记 1，独立元音记 1，依附元音符号（ा ि ी …）记 0，
//       虚音 ् ं ँ ः ़ 与句读 । ॥ 记 0。
const DEV_CONS = new Set("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहऱऴवऩ")
const DEV_IND_V = new Set("अआइईउऊऋएऐओऔऍऎएऐऑऒओऔ")
const DEV_DEP_V = new Set("ािीुूृॄॅॆेैॉॊोौॎॏ")
const DEV_IGNORE = new Set("् ं ँ ः ़ ‍ \n")

export function countHiMatras(text: string): number {
  let n = 0
  for (const c of text) {
    if (DEV_CONS.has(c) || DEV_IND_V.has(c)) n += 1
    else if (DEV_DEP_V.has(c) || DEV_IGNORE.has(c)) continue
    else if (COMBINING.test(c)) continue
  }
  return n
}

/** 按 । ॥ ，逗号切成前半/后半，返回两段 matra（Doha 13+11 的判定基础）。 */
export function hindiSplit(text: string): [number, number] {
  const parts = text.split(/[।॥，,]/).filter((p) => p.trim() !== "")
  if (parts.length >= 2) {
    return [countHiMatras(parts[0]!), countHiMatras(parts[1]!)]
  }
  return [countHiMatras(text), 0]
}

// ---------------------------------------------------------------- 阿拉伯语
// 一核一音节：每个「辅音(+元音)」或「ا/و/ي」算一个音节。
// 长 (–) = 长元音 / 带 shadda / 后面是 sukun（闭音节）；短 (⏑) = 短元音开口。
const AR_SHORT_V = new Set("\u064e\u064f\u0650")       // fatha damma kasra
const AR_LONG_V = new Set("\u0648\u062a\u0627\u0622\u0623\u0625\u0623\u0671\u0649")
const AR_SUKUN = new Set("\u0652")
const AR_SHADDA = new Set("\u0651")
const AR_TANWEEN = new Set("\u064b\u064c\u064d\u0650\u064b")
const AR_PUNCT = new Set("\u060c\u061b\u061f.,;:\u2014\u2013 ")
const AR_MARKS = new Set([
  ...AR_SHORT_V, ...AR_SUKUN, ...AR_SHADDA, ...AR_TANWEEN,
  ..."\u0670\u0653\u0654\u0655",
])

/** 返回 [[kind, 音节字母串]]，kind ∈ {'-', '⏑'}。 */
export function arSyllables(text: string): [string, string][] {
  const out: [string, string][] = []
  const cs = [...text]
  let i = 0
  const n = cs.length
  while (i < n) {
    const c = cs[i]!
    if (AR_PUNCT.has(c) || AR_MARKS.has(c)) {
      i += 1
      continue
    }
    const nxt = i + 1 < n ? cs[i + 1]! : ""
    let syl = c
    let longv = false
    let step = 1
    if (AR_LONG_V.has(c) && !AR_SHORT_V.has(nxt)) {
      longv = true
    } else if (AR_LONG_V.has(nxt)) {
      syl = c + nxt
      longv = true
      step = 2
    } else if (AR_SHORT_V.has(nxt) || AR_TANWEEN.has(nxt)) {
      longv = false
      step = 2
    } else if (AR_SHADDA.has(nxt)) {
      longv = true
      step = 2
    } else if (AR_SUKUN.has(nxt) || nxt === "" || AR_PUNCT.has(nxt)) {
      longv = true
      step = 2
    } else {
      longv = true // 非冗余分支：进入时 longv 初值是 False；辅音后无元音标记 → 视作闭音节记长
    }
    out.push([longv ? "-" : "⏑", syl])
    i += step
  }
  return out
}

// ---------------------------------------------------------------- 希伯来语
const HE_MARKS = new Set("֑־׃׀")
const HE_STRESS = new Set("ֽֿׁׂׅ")
const HE_POINTS = new Set(
  [...Array(0x05c8 - 0x05b0)].map((_, k) => String.fromCharCode(0x05b0 + k)),
)
for (const c of ["־", "׀", "׃"]) HE_POINTS.delete(c)

/** 希伯来语是「辅音 + 尼库德」拼写，**元音在符号上不在字母上**。
 * 闭音节优先：带元音的辅音开启音节，不带元音的辅音是前一音节的韵尾
 * （`שַׁר` 是一个音节不是两个）。 */
export function hebrewSyllables(text: string): string[] {
  const toks: [string, boolean][] = []
  for (const c of text.normalize("NFC")) {
    if (HE_POINTS.has(c)) {
      if (toks.length > 0) {
        toks[toks.length - 1] = [toks[toks.length - 1]![0] + c, true]
      }
      continue
    }
    if (/\s/.test(c) || HE_MARKS.has(c) || "—–.,;:׳״".includes(c)) {
      toks.push(["|", false])
      continue
    }
    toks.push([c, false])
  }
  const out: string[] = []
  let cur = ""
  for (const [letters, hasV] of toks) {
    if (letters === "|") {
      if (cur) out.push(cur)
      cur = ""
      continue
    }
    if (hasV) {
      if (cur) out.push(cur)
      cur = letters
    } else {
      cur += letters
    }
  }
  if (cur) out.push(cur)
  return out
}

// ---------------------------------------------------------------- 其余计数器

/** 汉字按字数；七言律句是一整句里两半，逗号才是断句处。
 *
 * 断句同时认全角 "，" 与半角 ","（写稿两形都合法）——分句前把半角归一成全角；
 * 句读 "。；、,.!?" 一律不计入字数。
 */
export function countZhChars(lines: string[]): number[] {
  return lines.flatMap((ln) =>
    ln.replace(/,/g, "，").split("，").filter((h) => h !== "")
      .map((h) => h.replace(/[，。；、,.!?]/g, "").length))
}

export function countRuVowels(lines: string[]): number[] {
  const ru = new Set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
  return lines.map((ln) => [...ln].filter((c) => ru.has(c)).length)
}

/** 希腊语：双元音（αι αυ ευ ει οι ου υι ηυ）只算一音节。
 * 去变音符号后先小写再数：句首大写元音（如 Ένα 的 Έ）不在小写字母表
 * 成员里，不小写会漏数句首音节（俄语大小写双列、德语/西语先 lower
 * ——本计数器与兄弟计数器同口径）。 */
export function countElSyllables(lines: string[]): number[] {
  const diph = new Set(["αι", "αυ", "ευ", "ει", "οι", "ου", "υι", "ηυ"])
  const out: number[] = []
  for (const ln of lines) {
    const s = ln.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase()
    let count = 0
    let i = 0
    const cs = [...s]
    while (i < cs.length) {
      if ("αειουηω".includes(cs[i]!)) {
        i += diph.has(cs[i]! + (cs[i + 1] ?? "")) ? 2 : 1
        count += 1
      } else {
        i += 1
      }
    }
    out.push(count)
  }
  return out
}

/** 德语按元音组；ie/ö 等当一个单元音（die=1、Jahreswende=4）。 */
export function countDeVowelGroups(lines: string[]): number[] {
  const deV = new Set("aeiouäöüy")
  const out: number[] = []
  for (const ln of lines) {
    const s = ln.normalize("NFC").toLowerCase().replace(/sch|ch|ph|th/g, "X")
    let n = 0
    let prev = false
    for (const c of s) {
      if (deV.has(c)) {
        if (!prev) n += 1
        prev = true
      } else {
        prev = false
      }
    }
    out.push(n)
  }
  return out
}

/** 西语按元音组；元音间的 y 当辅音断。 */
export function countEsVowelGroups(lines: string[]): number[] {
  const esV = new Set("aeiouáéíóúü")
  const out: number[] = []
  for (const ln of lines) {
    const s = ln.normalize("NFC").toLowerCase()
    let n = 0
    let prev = false
    for (const c of s) {
      if (esV.has(c)) {
        if (!prev) n += 1
        prev = true
      } else {
        prev = false
      }
    }
    out.push(n)
  }
  return out
}

/** 谚文方块一个一音节；组合型字母双写收一个音节。 */
export function countKoBlocks(lines: string[]): number[] {
  const out: number[] = []
  for (const ln of lines) {
    let n = 0
    let jamo = 0
    for (const c of ln) {
      const o = c.codePointAt(0)!
      if (0xac00 <= o && o <= 0xd7a3) {
        n += 1
        jamo = 0
      } else if ((0x1100 <= o && o <= 0x11ff) || (0x3130 <= o && o <= 0x318f)) {
        jamo += 1
        if (jamo === 2) {
          n += 1
          jamo = 0
        }
      }
    }
    out.push(n)
  }
  return out
}

export function countAr(lines: string[]): number[] {
  return lines.map((ln) => arSyllables(ln).length)
}

export function countHe(lines: string[]): number[] {
  return lines.map((ln) => hebrewSyllables(ln).length)
}

export function countHi(lines: string[]): number[] {
  return lines.map((ln) => countHiMatras(ln))
}

export type Counter = (lines: string[]) => number[]

// 计数器注册表：语种 → 函数。**新语种 = 加一行**，不是改逻辑。
export const COUNTERS: Record<string, Counter> = {
  "中文": countZhChars, "俄语": countRuVowels, "希腊语": countElSyllables,
  "德语": countDeVowelGroups, "西班牙语": countEsVowelGroups,
  "印地语": countHi, "阿拉伯语": countAr, "希伯来语": countHe,
  "韩语": countKoBlocks,
}

export interface AuditOneResult {
  lang: string
  hand: number[] | null
  algo: number[] | null
  actual: number[] | null
  claim: number[] | null
  status: string
  warn: string
}

/** 一个语种的审计（纯函数）。
 *
 * splits：手写音节拆分（人眼复核用）；claim：声称的数字表；
 * noClaim：验证不了的体式声明已主动撤下（合法第三态）。
 * 返回 status ∈ ✅ 相符 / ❌ 声称不符 / ❌ 未登记声称 / ○ 不作声称。
 * 手写拆分与算法都有且逐行结构一致而数值不同 → 以算法为准并告警。
 */
export function auditOne(
  lang: string,
  lines: string[],
  opts: {
    splits?: string[][] | null
    claim?: number[] | null
    noClaim?: boolean
  } = {},
): AuditOneResult {
  const hand = opts.splits ? opts.splits.map((p) => p.length) : null
  const algo = COUNTERS[lang] ? COUNTERS[lang]!(lines) : null
  const actual = algo ?? hand
  let warn = ""
  if (hand && algo && hand.length === algo.length && hand.join() !== algo.join()) {
    warn = `手写拆分 ${pyList(hand)} ≠ 算法 ${pyList(algo)}，以算法为准`
  }
  let status: string
  if (opts.noClaim) {
    status = "○ 不作声称（主动）"
  } else if (opts.claim === undefined || opts.claim === null) {
    status = "❌ 未登记声称值"
  } else if (actual !== null && actual.join() === opts.claim.join()) {
    status = "✅ 相符"
  } else {
    status = `❌ 声称 ${pyList(opts.claim)} 实测 ${pyList(actual)}`
  }
  return { lang, hand, algo, actual, claim: opts.claim ?? null, status, warn }
}

export interface AuditItem {
  lang: string
  lines: string[]
  splits?: string[][]
  claim?: number[] | null
  noClaim?: boolean
}

/** 跑一批语种。bad = ❌ + 有告警的条数（供退出码）。 */
export function auditAll(items: AuditItem[]): AuditOneResult[] {
  const rows = items.map((it) =>
    auditOne(it.lang, it.lines, { splits: it.splits, claim: it.claim, noClaim: it.noClaim }))
  for (const r of rows) {
    process.stdout.write(
      `${r.lang.padEnd(6)} ${r.status.padEnd(24)} 实测 ${pyList(r.actual)}`
      + (r.warn ? `　⚠ ${r.warn}` : "") + "\n")
  }
  const passed = rows.filter((r) => r.status.startsWith("✅")).length
  const noClaims = rows.filter((r) => r.status.startsWith("○")).length
  const bad = rows.filter((r) => r.status.startsWith("❌")).length
    + rows.filter((r) => r.warn !== "").length
  process.stdout.write(
    `\n实测通过 ${passed} · 不作声称 ${noClaims} · 需处理 ${bad} / 共 ${rows.length} 语种\n`)
  return rows
}
