// tts-synth.test.ts — synth_line 重试纪律 + synth_cached 缓存口径（verify_tts §4–§5 的移植，
// 离线跑：真机合成在 tts-live.test.ts，FEUILLE_LIVE=1 门控）。
//
// 各防一种真实退化：
// - NoAudioReceived 重试后能成功；耗尽抛出；**其他异常不重试**（参数错误稳定复现，重试烧时间）
// - 缓存命中不重复合成（miss→NEW 写盘，再调→HIT 读盘）；改文本 → 新键 → 重新合成
// - 时长边车（{key}.dur）：HIT 读边车**零 ffprobe**（哨兵值即证）；边车缺失探测一次并补写
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import {
  NoAudioReceived,
  overrideSynthOnceForTests,
  setRetryBackoffForTests,
  synthLine,
} from "../src/tts/client.js"
import { contentHash, type Word } from "../src/tts/pure.js"
import { synthCached } from "../src/tts/synth.js"

const assetMp3 = fileURLToPath(
  new URL("../../../migration/golden/assets/tts-cache/04a0db8809562777.mp3", import.meta.url),
)

const REAL_WORDS: Word[] = [
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

describe("synth_cached：内容寻址缓存（离线假合成）", () => {
  const mp3Bytes = new Uint8Array(readFileSync(assetMp3))

  function fakeSynth(calls: { n: number }) {
    overrideSynthOnceForTests(async (req) => {
      calls.n++
      const mp3 = new Uint8Array(mp3Bytes.length + req.text.length)
      mp3.set(mp3Bytes)
      return { mp3, words: REAL_WORDS }
    })
  }

  it("miss→NEW 写盘，再调→HIT 读盘（合成只发生一次）", async () => {
    const calls = { n: 0 }
    fakeSynth(calls)
    const cache = join(tmp(), "audio")
    const r1 = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    const r2 = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    expect(r1.state).toBe("NEW")
    expect(r2.state).toBe("HIT")
    expect(r1.key).toBe(r2.key)
    expect(calls.n).toBe(1)
    expect(existsSync(r1.mp3)).toBe(true)
    expect(r1.words).toEqual(REAL_WORDS)
    expect(r2.words).toEqual(REAL_WORDS)
    expect(r1.duration).toBeGreaterThan(2.0)
    expect(r2.duration).toBe(r1.duration)
  })

  it("改文本 → 新键 → 重新合成", async () => {
    const calls = { n: 0 }
    fakeSynth(calls)
    const cache = join(tmp(), "audio")
    const r1 = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    const r3 = await synthCached("行二", "v", "-8%", "+0Hz", cache)
    expect(r3.state).toBe("NEW")
    expect(r3.key).not.toBe(r1.key)
    expect(calls.n).toBe(2)
  })

  it("键口径：sha256(voice|rate|pitch|text)[:16]，逐项敏感", async () => {
    const k = contentHash("zh-CN-XiaoxiaoNeural", "-8%", "+0Hz", "一叶知秋")
    expect(k).toMatch(/^[0-9a-f]{16}$/)
    for (const parts of [
      ["v2", "-8%", "+0Hz", "一叶知秋"],
      ["zh-CN-XiaoxiaoNeural", "-9%", "+0Hz", "一叶知秋"],
      ["zh-CN-XiaoxiaoNeural", "-8%", "+1Hz", "一叶知秋"],
      ["zh-CN-XiaoxiaoNeural", "-8%", "+0Hz", "一叶知秋。"],
    ] as [string, string, string, string][]) {
      expect(contentHash(...parts)).not.toBe(k)
    }
  })

  it("时长边车：HIT 读 {key}.dur 零探测（哨兵值即证）+ 边车缺失补写", async () => {
    const calls = { n: 0 }
    fakeSynth(calls)
    const cache = join(tmp(), "audio")
    mkdirSync(cache, { recursive: true })
    // 预置缓存三件套（模拟老进程的 NEW 产物），边车放哨兵值
    const key = contentHash("v", "-8%", "+0Hz", "行一")
    writeFileSync(join(cache, `${key}.mp3`), mp3Bytes)
    writeFileSync(join(cache, `${key}.json`), JSON.stringify(REAL_WORDS, null, 1))
    writeFileSync(join(cache, `${key}.dur`), "1.234")
    const r = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    expect(r.state).toBe("HIT")
    expect(r.duration).toBe(1.234) // 边车哨兵直接生效——没跑 ffprobe
    expect(calls.n).toBe(0) // 没合成
    // 边车缺失：探测一次并补写，下个进程起零探测
    rmSync(join(cache, `${key}.dur`))
    const r2 = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    expect(r2.duration).toBeGreaterThan(2.0)
    expect(readFileSync(join(cache, `${key}.dur`), "utf8")).toBe(String(r2.duration))
  })

  it("词表 meta 双形态直读：纯数组（Python 同形态）与 {words:[…]} 都认", async () => {
    const cache = join(tmp(), "audio")
    mkdirSync(cache, { recursive: true })
    const key = contentHash("v", "-8%", "+0Hz", "行一")
    writeFileSync(join(cache, `${key}.mp3`), mp3Bytes)
    writeFileSync(join(cache, `${key}.dur`), "1.234")
    // 老形态 {words:[…]}
    writeFileSync(join(cache, `${key}.json`), JSON.stringify({ words: REAL_WORDS }))
    const r = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    expect(r.state).toBe("HIT")
    expect(r.words).toEqual(REAL_WORDS)
    // 纯数组（Python json.dumps(words) 形态，迁移期互读）
    writeFileSync(join(cache, `${key}.json`), JSON.stringify(REAL_WORDS))
    const r2 = await synthCached("行一", "v", "-8%", "+0Hz", cache)
    expect(r2.words).toEqual(REAL_WORDS)
  })
})
