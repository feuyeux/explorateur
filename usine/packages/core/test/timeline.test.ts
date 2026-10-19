// timeline.test.ts — 时间轴与词级进度轴：verify_timeline.py 的反向验证移植。
//
// karaoke_points 字符进度按码点（Python len()），增补平面字符不双计——
// 这条独立可验；纯函数 parity 段在 P0-P8 删场后已不再需要逐字节金样本。
// enrich_lines 的反向验证用 lavfi 自造 mp3，durs 哨兵值钉「传入即零探测」
// 性能契约。
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import { platform } from "../src/index.js"
import {
  computeStarts,
  enrichLines,
  karaokePoints,
  type KaraokeWord,
  type TimelineLine,
} from "../src/timeline.js"

const FFMPEG = platform.ffmpeg()

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-timeline-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("compute_starts 累进口径", () => {
  it("累加：单段直写 + 多段累加 + gap", () => {
    // 形态① 单行：单段直写
    expect(computeStarts([3.5], 0.4)).toEqual([0])
    // 形态② 多行等长：每行收尾 + gap
    expect(computeStarts([1, 1, 1], 0.5)).toEqual([0, 1.5, 3.0])
    // 形态③ 不等长：每行收尾 + gap
    expect(computeStarts([1.5, 0.5, 2.0], 0.3)).toEqual([0, 1.8, 2.6])
    // 形态④ 单行且 gap>0：起点仍是 0
    expect(computeStarts([2], 0.5)).toEqual([0])
  })
})

describe("karaoke_points 字符进度按码点（与 Python len() 一致）", () => {
  it("增补平面字符不双计（UTF-16 .length 会把 😀 算 2 → 进度错位）", () => {
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

describe.skipIf(FFMPEG === null)("enrich_lines 反向验证（verify_timeline 移植）", () => {
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
