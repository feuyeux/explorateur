// tts-split.test.ts — 4096 字节分片：边界与一致性反向验证。
//
// 边界口径：≤0 拒绝、空文本返回空块、Buffer / String 同源（字节级，
// 不是 UTF-16 码元）。逐字节 parity 段在 P0-P8 删场后不再保留——
// 行为契约留在纯函数测试里钉住。
import { describe, expect, it } from "vitest"

import { splitTextByByteLength } from "../src/tts/split.js"

describe("splitTextByByteLength 边界与一致性", () => {
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
