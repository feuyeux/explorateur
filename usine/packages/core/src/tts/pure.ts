// pure.ts — TTS 纯函数（tts.py 的 TS 移植；判定口径 = 金样本语料逐字节对齐）。
//
// 口径纪律（全部实测过的教训，不许"顺手优化"）：
// - 缓存键 sha256(voice|rate|pitch|text)[:16]——变了等于换缓存空间。
// - parse_signed 只按整段后缀剥单位（"%" / "Hz" 可叠）——rstrip 字符集会把
//   "12H"/"12z" 残缺单位剥成 12，静默读错；空/垃圾 → 0（不猜）。
// - 伪词不裁尾（裁了会误伤无词边界事件的语言）。
import { createHash } from "node:crypto"

import { clamp } from "../num.js"

// clamp 的口径本体在 num（数值口径底座），这里只做转出保兼容面：
// tts 侧历史上从这里取 clamp，仓内已全部改走 num，再导出只为不打断外部调用方。
export { clamp } from "../num.js"

/** 内容寻址缓存键：sha256("|".join(parts))[:16]。口径不许变。 */
export function contentHash(...parts: (string | number)[]): string {
  const joined = parts.map((x) => String(x)).join("|")
  return createHash("sha256").update(joined, "utf8").digest("hex").slice(0, 16)
}

/** "+7%" / "-3Hz" → 整数偏移；空/垃圾 → 0（不猜）。单位只按整段后缀剥。 */
export function parseSigned(v: string | number): number {
  let s = String(v).trim()
  for (;;) {
    if (s.endsWith("%")) s = s.slice(0, -1)
    else if (s.endsWith("Hz")) s = s.slice(0, -2)
    else break
  }
  const n = Number(s)
  if (!Number.isFinite(n)) return 0
  return Math.trunc(n)
}

/** 声线安全域：越界声音会破音、发机械声。调预算不动声线。 */
export const SAFE_RATE = [-20, 20] as const
export const SAFE_PITCH = [-12, 12] as const

/** 数值夹取：口径本体在 core.num（数值口径底座），此处仅为 tts 侧的转出面。 */

/** 人设基线 + 项目偏移，夹取在安全域内，返回 edge-tts 的 rate/pitch 串。 */
export function voiceParams(
  baseRate: string | number,
  basePitch: string | number,
  rateOff = 0,
  pitchOff = 0,
): [string, string] {
  const r = clamp(parseSigned(baseRate) + rateOff, SAFE_RATE[0], SAFE_RATE[1])
  const p = clamp(parseSigned(basePitch) + pitchOff, SAFE_PITCH[0], SAFE_PITCH[1])
  return [`${r >= 0 ? "+" : ""}${r}%`, `${p >= 0 ? "+" : ""}${p}Hz`]
}

export interface Word {
  /** 词首秒（tts 输出为相对行首） */
  t: number
  /** 词长秒 */
  d: number
  /** 词面 */
  w: string
}

/** 伪词判定：整行只有一个词、且词面是文本前 12 字。伪词是兜底产物。 */
export function isFakeWord(words: Word[], text: string): boolean {
  return words.length === 1 && words[0]!.w === text.slice(0, 12)
}

/** 行时长：词级真值裁尾 min(探针时长, 末词 end + 0.2s)；伪词不裁。 */
export function effectiveDur(words: Word[], probeDur: number, text: string): number {
  if (words.length === 0 || isFakeWord(words, text)) return probeDur
  const last = words[words.length - 1]!
  const end = last.t + last.d
  return Math.min(probeDur, end + 0.2)
}
