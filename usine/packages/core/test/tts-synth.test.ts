// tts-synth.test.ts — synth_line 重试纪律（verify_tts §4 的移植，离线跑）。
//
// 各防一种真实退化：
// - NoAudioReceived 重试后能成功；耗尽抛出；**其他异常不重试**（参数错误稳定复现，重试烧时间）
//
// 真机合成的 LIVE 测试（FEUILLE_LIVE=1 门控 + 缓存命中 / 键口径 / 时长边车等）
// 在 P0-P8 删场后已无 Python 真机回归面，移除独立用例库。
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import {
  NoAudioReceived,
  overrideSynthOnceForTests,
  setRetryBackoffForTests,
  synthLine,
} from "../src/tts/client.js"

const REAL_WORDS = [
  { t: 0.1, d: 0.9, w: "一叶" },
  { t: 1.2, d: 0.6, w: "知秋" },
]

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-tts-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
  overrideSynthOnceForTests(null)
  setRetryBackoffForTests(1.2)
})

describe("synth_line 重试纪律：只认 NoAudioReceived", () => {
  beforeEach(() => setRetryBackoffForTests(0))

  it("NoAudioReceived 重试到成功（瞬时抖动，同文本重试即过）", async () => {
    let n = 0
    overrideSynthOnceForTests(async () => {
      n++
      if (n < 3) throw new NoAudioReceived("transient")
      return { mp3: new Uint8Array([1, 2, 3]), words: REAL_WORDS }
    })
    const r = await synthLine({ text: "一叶知秋", voice: "v", rate: "-8%", pitch: "+0Hz" })
    expect(r.mp3).toEqual(new Uint8Array([1, 2, 3]))
    expect(n).toBe(3)
  })

  it("重试耗尽 → 抛最后一次 NoAudioReceived", async () => {
    let n = 0
    overrideSynthOnceForTests(async () => {
      n++
      throw new NoAudioReceived("dead")
    })
    await expect(
      synthLine({ text: "一叶知秋", voice: "v", rate: "-8%", pitch: "+0Hz" }, 3),
    ).rejects.toThrow(NoAudioReceived)
    expect(n).toBe(3)
  })

  it("参数类异常不重试（稳定复现，重试只会烧时间）", async () => {
    let n = 0
    overrideSynthOnceForTests(async () => {
      n++
      throw new Error("参数错误——稳定复现的那种")
    })
    await expect(
      synthLine({ text: "一叶知秋", voice: "v", rate: "-8%", pitch: "+0Hz" }, 5),
    ).rejects.toThrow("参数错误")
    expect(n).toBe(1)
  })
})
