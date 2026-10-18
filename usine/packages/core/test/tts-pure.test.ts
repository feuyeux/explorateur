// tts-pure.test.ts — 纯函数金样本 parity（migration/golden/tts.json 的语料）：
// content_hash / parse_signed / voice_params / is_fake_word / effective_dur。
// 确定性部分逐字节对齐——这是迁移判据，不是普通单测。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import {
  contentHash,
  effectiveDur,
  isFakeWord,
  parseSigned,
  voiceParams,
  type Word,
} from "../src/tts/pure.js"

const goldenPath = fileURLToPath(new URL("../../../migration/golden/tts.json", import.meta.url))
const golden = JSON.parse(readFileSync(goldenPath, "utf8")) as {
  data: {
    content_hash: { parts: (string | number)[]; key: string }[]
    parse_signed: { v: string; out: number }[]
    voice_params: { base_rate: string; base_pitch: string; rate_off: number; pitch_off: number; out: [string, string] }[]
    is_fake_word: { words: Word[]; text: string; out: boolean }[]
    effective_dur: { words: Word[]; probe: number; text: string; out: number }[]
  }
}

describe("tts 纯函数金样本 parity", () => {
  it("content_hash：缓存键口径逐字节一致", () => {
    expect(golden.data.content_hash.length).toBeGreaterThanOrEqual(10)
    for (const c of golden.data.content_hash) {
      expect(contentHash(...c.parts)).toBe(c.key)
    }
  })

  it("parse_signed：整段后缀剥单位，垃圾输入 → 0", () => {
    for (const c of golden.data.parse_signed) {
      expect(parseSigned(c.v)).toBe(c.out)
    }
  })

  it("voice_params：基线 + 偏移夹安全域", () => {
    for (const c of golden.data.voice_params) {
      expect(voiceParams(c.base_rate, c.base_pitch, c.rate_off, c.pitch_off)).toEqual(c.out)
    }
  })

  it("is_fake_word：单词且词面为前 12 字", () => {
    for (const c of golden.data.is_fake_word) {
      expect(isFakeWord(c.words, c.text)).toBe(c.out)
    }
  })

  it("effective_dur：词级真值裁尾，伪词不裁", () => {
    for (const c of golden.data.effective_dur) {
      expect(effectiveDur(c.words, c.probe, c.text)).toBeCloseTo(c.out, 10)
    }
  })

  it("parse_signed 残缺单位不许被剥成数字（口径反例内嵌）", () => {
    expect(parseSigned("12H")).toBe(0)
    expect(parseSigned("12z")).toBe(0)
    expect(parseSigned("12%Hz")).toBe(12)
    expect(parseSigned("  +12  ")).toBe(12)
  })
})
