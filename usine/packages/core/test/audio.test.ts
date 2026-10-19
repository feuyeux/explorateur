// audio.test.ts — 滤镜图金样本 parity（migration/golden/audio.json）+
// verify_audio.py 的反向验证移植。
//
// 核心是坑③那条顺序纪律：**apad 必须在 loudnorm 之前**（实测的非确定 EOF
// 冲刷竞态：后置时 10 连跑丢补尾 3 次）。顺序写错不会立刻炸，只会随机
// 出片——所以用断言钉住 filterGraph 的字符串顺序，不跑 ffmpeg 也能验。
import { execFileSync } from "node:child_process"
import { copyFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import { composeTrack, filterGraph, probeDuration } from "../src/audio.js"
import { platform } from "../src/index.js"
import { roundHalfEven } from "../src/num.js"

const FFMPEG = platform.ffmpeg()
const FFPROBE = platform.ffprobe()

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-audio-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("filter_graph 反向验证（verify_audio 移植）", () => {
  const g2 = filterGraph(2, [0.0, 1.5], 10.0)
  const g1 = filterGraph(1, [0.0], 10.0)

  it("好数据放行：两行滤镜图要素齐全", () => {
    for (const x of ["adelay=0|0", "adelay=1500|1500", "amix=inputs=2:normalize=0",
      "apad=whole_dur=10.0", "loudnorm=", "atrim=0:10.0"]) {
      expect(g2).toContain(x)
    }
  })

  it("单行走 anull 直通（滤镜链形状统一，不分叉）", () => {
    expect(g1).toContain("anull[m]")
    expect(g1).not.toContain("amix")
  })

  it("loudness_i 可配（轨道级 -16 / 终混 -14 由调用方定）", () => {
    expect(filterGraph(1, [0], 10, -14)).toContain("loudnorm=I=-14")
  })

  it("坑③顺序纪律：apad 必须在 loudnorm 之前（后置是实测的非确定竞态）", () => {
    for (const g of [g1, g2]) {
      const iApad = g.indexOf("apad=whole_dur")
      const iLoud = g.indexOf("loudnorm")
      expect(iApad).toBeGreaterThanOrEqual(0)
      expect(iApad).toBeLessThan(iLoud)
    }
  })

  it("adelay 毫秒口径：banker's rounding 与 Python round 一致", () => {
    // 2.5s → 2500 精确；12345.5/12344.5 平手取偶；2.675 的二进制真值略小 → 2675
    expect(filterGraph(1, [2.5], 10)).toContain("adelay=2500|2500")
    expect(filterGraph(1, [2.675], 10)).toContain("adelay=2675|2675")
    expect(roundHalfEven(12345.5)).toBe(12346)
    expect(roundHalfEven(12344.5)).toBe(12344)
    expect(roundHalfEven(2.5)).toBe(2)
    expect(roundHalfEven(3.5)).toBe(4)
    expect(roundHalfEven(-1.5)).toBe(-2)
    // Python round(0.125, 2) == 0.12（平手取偶）；round(2.675, 2) == 2.67（二进制真值）
    expect(roundHalfEven(0.125, 2)).toBe(0.12)
    expect(roundHalfEven(2.675, 2)).toBe(2.67)
  })
})

describe.skipIf(FFMPEG === null || FFPROBE === null)("真机混音 smoke（verify_audio 移植）", () => {
  function mkSines(d: string): [string, string] {
    const a1 = join(d, "a1.mp3")
    const a2 = join(d, "a2.mp3")
    execFileSync(FFMPEG!, ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
      "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
      "-filter_complex", "[0:a][1:a]amix=inputs=2[a]", "-map", "[a]", a1])
    copyFileSync(a1, a2)
    return [a1, a2]
  }

  it("两行混到恰好 3.0s（apad 补齐 + atrim 裁齐）且连跑 3 次逐次相等（坑③确定性验收）", () => {
    const d = tmp()
    const [a1, a2] = mkSines(d)
    const durs: number[] = []
    for (let i = 0; i < 3; i++) {
      const out = join(d, `mix${i}.m4a`)
      composeTrack([a1, a2], [0.0, 1.0], 3.0, out)
      durs.push(roundHalfEven(probeDuration(out), 2))
    }
    for (const x of durs) expect(Math.abs(x - 3.0)).toBeLessThanOrEqual(0.05)
    expect(new Set(durs).size).toBe(1)
    expect(Math.abs(probeDuration(a1) - 1.0)).toBeLessThan(0.05)
  })

  it("坏文件显式炸（check=True 口径：不静默返回垃圾）", () => {
    const d = tmp()
    const junk = join(d, "junk.mp3")
    writeFileSync(junk, "not audio")
    expect(() => probeDuration(junk)).toThrow()
  })
})
