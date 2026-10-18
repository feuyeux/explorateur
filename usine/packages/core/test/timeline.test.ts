// timeline.test.ts — 时间轴与词级进度轴：金样本 parity（migration/golden/timeline.json，
// 纯函数逐字节）+ verify_timeline.py 的反向验证移植。
//
// enrich_lines 的金样本用真实 mp3 实测（migration/golden/assets/tts-cache），
// 同机 ffprobe 桶内确定性；`durs` 传参的性能契约（传入即零探测）也在
// 这里的哨兵值测试里钉住。
import { execFileSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it } from "vitest"

import { platform } from "../src/index.js"
import {
  computeStarts,
  enrichLines,
  fracAt,
  karaokePoints,
  type KaraokeWord,
  type TimelineLine,
} from "../src/timeline.js"

const FFMPEG = platform.ffmpeg()
const goldenPath = fileURLToPath(new URL("../../../migration/golden/timeline.json", import.meta.url))
const golden = JSON.parse(readFileSync(goldenPath, "utf8")) as {
  data: {
    compute_starts: { speech_durs: number[]; gap: number; out: number[] }[]
    karaoke_points: {
      line: { start: number; dur: number; words: { w: string; s: number; e: number }[] }
      out: [number, number][]
    }
    frac_at: { pts: [number, number][]; t: number; out: number }[]
    enrich_lines: {
      gap: number
      lines_in: { key: string; dur: number; words: unknown[] }[]
      lines_out: Record<string, unknown>[]
      total: number
      span: number
    }
  }
}
const cacheDir = fileURLToPath(new URL("../../../migration/golden/assets/tts-cache", import.meta.url))

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-timeline-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("compute_starts 金样本 parity（累进口径与已验收成片一致）", () => {
  it("四种形态逐字节一致", () => {
    expect(golden.data.compute_starts.length).toBe(4)
    for (const c of golden.data.compute_starts) {
      expect(computeStarts(c.speech_durs, c.gap), JSON.stringify(c.speech_durs)).toEqual(c.out)
    }
  })
})

describe("karaoke_points 金样本 parity（浮点逐位一致）", () => {
  it("词首/词尾字符进度点逐字节对齐", () => {
    const { line, out } = golden.data.karaoke_points
    const pts = karaokePoints({ start: line.start, dur: line.dur, words: line.words })
    expect(pts).toEqual(out)
  })

  it("字符进度按码点（Python len()），增补平面字符不双计", () => {
    const words: KaraokeWord[] = [
      { w: "😀", s: 0, e: 0.5 },
      { w: "叶", s: 0.5, e: 1 },
    ]
    const pts = karaokePoints({ start: 0, dur: 1.2, words })
    // total = 1 + 1 + 1（词距）= 3：首词首点 1/3（UTF-16 .length 会把 😀 算 2 得 2/4）
    expect(pts[1]![0]).toBe(0)
    expect(pts[1]![1]).toBeCloseTo(1 / 3, 12)
    // 首词尾点 = (1 字 + 词距 1) / 3
    expect(pts[2]![0]).toBe(0.5)
    expect(pts[2]![1]).toBeCloseTo(2 / 3, 12)
    expect(pts[3]![0]).toBe(0.5)
    expect(pts[3]![1]).toBe(1) // 第二词首点：进度已满（字符数+词距=total）
    expect(pts[4]![0]).toBe(1)
    expect(pts[4]![1]).toBe(1)
  })
})

describe("frac_at 金样本 parity", () => {
  it("九个时刻：区间外夹 0/1、区间内线性插值，逐位一致", () => {
    expect(golden.data.frac_at.length).toBe(9)
    for (const c of golden.data.frac_at) {
      expect(fracAt(c.pts, c.t)).toBe(c.out)
    }
  })
})

describe.skipIf(FFMPEG === null)("enrich_lines 金样本 + 反向验证（verify_timeline 移植）", () => {
  it("三行金样本 mp3 实测：file_dur/tail_silence/start/total/span 全对齐", () => {
    const g = golden.data.enrich_lines
    expect(g.lines_in.length).toBe(3)
    const lines: TimelineLine[] = g.lines_in.map((ln) => ({
      key: ln.key,
      dur: ln.dur,
      words: ln.words as TimelineLine["words"],
    }))
    const [total, span] = enrichLines(lines, g.gap, cacheDir)
    lines.forEach((ln, i) => {
      const want = g.lines_out[i]!
      expect(ln.speechDur).toBe(want.speech_dur)
      expect(ln.fileDur).toBe(want.file_dur)
      expect(ln.tailSilence).toBe(want.tail_silence)
      expect(ln.start).toBe(want.start)
    })
    expect(total).toBe(g.total)
    expect(span).toBe(g.span)
  })

  it("tail_silence = file_dur - speech（就地补齐）", () => {
    const d = tmp()
    execFileSync(FFMPEG!, ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
      join(d, "k1.mp3")])
    const lines: TimelineLine[] = [{ key: "k1", dur: 0.5 }, { key: "k1", dur: 0.5 }]
    const [total, span] = enrichLines(lines, 0.35, d)
    expect(lines[0]!.start).toBe(0.0)
    expect(Math.abs(lines[0]!.fileDur! - 1.0)).toBeLessThan(0.05)
    expect(lines[0]!.tailSilence).toBeCloseTo(lines[0]!.fileDur! - 0.5, 6)
    expect(Math.abs(lines[1]!.start! - 0.85)).toBeLessThan(1e-6)
    expect(Math.abs(total - 1.0)).toBeLessThan(1e-6)
    expect(Math.abs(span - 1.35)).toBeLessThan(1e-6)
  })

  it("durs 传入即零探测：哨兵值直接生效（synthCached 实测时长的性能契约）", () => {
    const lines: TimelineLine[] = [{ key: "k1", dur: 0.5 }]
    const durs = new Map([["k1", 1.111]]) // 哨兵：若仍走 ffprobe，会得到别的数
    enrichLines(lines, 0.4, tmp(), durs) // 目录里根本没有 mp3——探测会炸，能过即证明没探测
    expect(lines[0]!.fileDur).toBe(1.111)
    expect(lines[0]!.tailSilence).toBeCloseTo(1.111 - 0.5, 10)
  })
})
