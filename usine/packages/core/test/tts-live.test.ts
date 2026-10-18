// tts-live.test.ts — 真机合成 parity（默认跳过；FEUILLE_LIVE=1 时跑）。
//
// edge-tts 是免费服务，不在额度红线内（AGENTS.md 口径）。判据（2026-10-18 实测定）：
// - words：与金样本逐字节相等——词级时间戳是服务端确定性部分。
// - mp3 字节：**服务端编码本就非确定**（Python 7.3.1 自身连跑两次 sha 即不同、
//   字节长度/词表/时长全同），故 mp3_sha256 只是采集时快照，不作 parity 门禁；
//   改比结构几何：字节长度容差（CBR 48kbps 下长度即时长）。
//   实证见 migration/README.md spike 1 结论。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { synthLine } from "../src/tts/client.js"
import { contentHash } from "../src/tts/pure.js"

const LIVE = process.env.FEUILLE_LIVE === "1"
const goldenPath = fileURLToPath(new URL("../../../migration/golden/tts.json", import.meta.url))
const golden = JSON.parse(readFileSync(goldenPath, "utf8")) as {
  data: {
    synth: { voice: string; text: string; key: string; words: { t: number; d: number; w: string }[]; mp3_sha256: string; mp3_bytes: number; probe_duration: number }[]
  }
}

describe.skipIf(!LIVE)("edge-tts v2 客户端真机合成 parity", () => {
  it("金样本三条语料：词级时间戳逐字节对齐 + 缓存键一致", { timeout: 120_000 }, async () => {
    expect(golden.data.synth.length).toBe(3)
    for (const g of golden.data.synth) {
      // 金样本以默认声线采集（+0% / +0Hz）
      const rate = "+0%"
      const pitch = "+0Hz"
      const key = contentHash(g.voice, rate, pitch, g.text)
      expect(key, "缓存键口径").toBe(g.key)
      const { mp3, words } = await synthLine({ text: g.text, voice: g.voice, rate, pitch })
      expect(words, `${g.voice} 词表`).toEqual(g.words)
      // mp3 字节非确定（服务端编码器）：比长度容差不比哈希；CBR 下长度即时长
      expect(Math.abs(mp3.length - g.mp3_bytes), `${g.voice} mp3 字节长度（±64 容差）`)
        .toBeLessThanOrEqual(64)
    }
  })

  it("长文本多段（>4096 字节）：跨段连接、词级时间戳单调连续（CBR 补偿）", { timeout: 180_000 }, async () => {
    // 带空格分隔（无分隔文本会触发上游超限单块 quirk，不走多段路径）
    const unit = "落叶知秋 岁月如歌 微风过隙 落地成霜"
    const text = Array.from({ length: 200 }, () => unit).join(" ")
    expect(Buffer.byteLength(text, "utf8")).toBeGreaterThan(4096 * 2) // 至少 3 段
    const { mp3, words } = await synthLine({
      text, voice: "zh-CN-XiaoxiaoNeural", rate: "+0%", pitch: "+0Hz",
    })
    expect(words.length).toBeGreaterThan(100)
    for (let i = 1; i < words.length; i++) {
      expect(words[i]!.t, `第 ${i} 词时刻不回退（段间补偿失效会跳变/回退）`)
        .toBeGreaterThanOrEqual(words[i - 1]!.t)
    }
    // 末词结束 + 垫尾应贴着 mp3 时长（CBR 48kbps 折算：bytes/6000 ≈ 秒）
    const lastEnd = words[words.length - 1]!.t + words[words.length - 1]!.d
    const seconds = mp3.length / 6000
    expect(lastEnd).toBeLessThanOrEqual(seconds)
    expect(lastEnd).toBeGreaterThan(seconds - 2)
  })
})
