// tts-split.test.ts — 4096 字节分片的金样本 parity（migration/golden/tts_split.json）。
//
// 判据：逐字节对齐（含上游 quirk——无分隔符长文本会产出超过限长的单块，
// 行为钉住不"顺手修"）。这是迁移判据，不是普通单测。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { splitTextByByteLength } from "../src/tts/split.js"

const goldenPath = fileURLToPath(new URL("../../../migration/golden/tts_split.json", import.meta.url))
const golden = JSON.parse(readFileSync(goldenPath, "utf8")) as {
  data: {
    cases: { label: string; text: string; byte_length: number; chunks_b64: string[]; chunk_bytes: number[] }[]
  }
}

describe("split_text_by_byte_length 金样本 parity（逐字节）", () => {
  it("语料全覆盖：换行/空格/UTF-8 边界/& 实体/strip/quirk", () => {
    expect(golden.data.cases.length).toBeGreaterThanOrEqual(10)
    for (const c of golden.data.cases) {
      const chunks = splitTextByByteLength(c.text, c.byte_length)
      expect(chunks.length, `${c.label} 块数`).toBe(c.chunks_b64.length)
      c.chunks_b64.forEach((b64, i) => {
        expect(chunks[i]!.toString("base64"), `${c.label} 第 ${i} 块逐字节`).toBe(b64)
      })
      expect(chunks.map((ch) => ch.length), `${c.label} 块字节长`).toEqual(c.chunk_bytes)
    }
  })

  it("限长 ≤ 0 拒绝（ValueError 口径）", () => {
    expect(() => splitTextByByteLength("x", 0)).toThrow()
    expect(() => splitTextByByteLength("x", -1)).toThrow()
  })

  it("空文本 → 空块列表（走 turn.end 之前的老口径：不请求即无音频）", () => {
    expect(splitTextByByteLength("", 4096)).toEqual([])
  })

  it("Buffer 入参与字符串同源（字节级，不是 UTF-16 码元）", () => {
    const s = "落叶知秋，岁月如歌。"
    const fromStr = splitTextByByteLength(s, 16)
    const fromBuf = splitTextByByteLength(Buffer.from(s, "utf8"), 16)
    expect(fromBuf).toEqual(fromStr)
  })
})
