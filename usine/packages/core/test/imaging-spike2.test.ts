// imaging-spike2.test.ts — spike 2 成像管线证明（P1）。
//
// 判据（金样本纪律）：
// 1. matte 数学：同一对 matte_w/matte_b 截图输入下，TS(sharp) 与
//    Python(Pillow+numpy) 的 matte_combine 是「解码后的纯数学」——期望逐像素
//    逐字节相等；若有差异先量化（差多少、差在哪），不盲目放宽。
// 2. rig/scenes 渲染：Pillow 与 Skia 栅格化器不同，边缘 AA 必然不同——
//    比结构与几何（降采样灰度的均值差 / p99），不比像素。阈值以实测量化
//    后落定，不拍脑袋。
import { describe, expect, it } from "vitest"
import { fileURLToPath } from "node:url"
import { readFileSync } from "node:fs"
import sharp from "sharp"
import { matteCombineBuffer, alphaStats, renderSpec, type DrawSpec } from "../src/index.js"

const GOLDEN = fileURLToPath(new URL("../../../migration/golden", import.meta.url))

describe("spike2: matte 数学 parity（sharp vs Python numpy）", () => {
  const golden = JSON.parse(
    readFileSync(`${GOLDEN}/textlayer.json`, "utf8"),
  ) as { data: { matte_shot: { alpha_stats: { size: [number, number]; coverage: number; alpha_mean_nonzero: number; alpha_max: number; bbox: [number, number, number, number] } } } }

  it("同一对截图输入 → 与 Python 金样本逐像素逐字节相等", async () => {
    const tsPng = await matteCombineBuffer(
      `${GOLDEN}/assets/textlayer/matte_w.png`,
      `${GOLDEN}/assets/textlayer/matte_b.png`,
    )
    const [tsRaw, refRaw] = await Promise.all([
      sharp(tsPng).ensureAlpha().raw().toBuffer({ resolveWithObject: true }),
      sharp(`${GOLDEN}/assets/textlayer/matte.png`).ensureAlpha().raw().toBuffer({ resolveWithObject: true }),
    ])
    expect(tsRaw.info.width).toBe(refRaw.info.width)
    expect(tsRaw.info.height).toBe(refRaw.info.height)
    let mismatches = 0
    const n = tsRaw.data.length
    for (let i = 0; i < n; i++) {
      if (tsRaw.data[i] !== refRaw.data[i]) mismatches++
    }
    expect(mismatches, `RGBA 逐字节不等个数 / ${n}`).toBe(0)
  })

  it("alpha 结构统计与金样本 alpha_stats 一致（coverage/均值/极值/包围盒）", async () => {
    const tsPng = await matteCombineBuffer(
      `${GOLDEN}/assets/textlayer/matte_w.png`,
      `${GOLDEN}/assets/textlayer/matte_b.png`,
    )
    const stats = await alphaStats(tsPng)
    const g = golden.data.matte_shot.alpha_stats
    expect(stats.size).toEqual(g.size)
    expect(stats.coverage).toBeCloseTo(g.coverage, 5)
    expect(stats.alphaMeanNonzero).toBeCloseTo(g.alpha_mean_nonzero, 1)
    expect(stats.alphaMax).toBe(g.alpha_max)
    expect(stats.bbox).toEqual(g.bbox)
  })
})

describe("spike2: 场景渲染结构 parity（Skia vs Pillow）", () => {
  const spec = JSON.parse(
    readFileSync(`${GOLDEN}/assets/scenes_ref.spec.json`, "utf8"),
  ) as DrawSpec

  /** 降采样灰度后的差分统计：均值绝对差 + p99。 */
  async function diffStats(aBuf: Buffer, bBuf: Buffer, w: number, h: number) {
    const toGray = (buf: Buffer) =>
      sharp(buf).resize(w, h, { kernel: "lanczos3" }).grayscale().raw().toBuffer()
    const [a, b] = await Promise.all([toGray(aBuf), toGray(bBuf)])
    const diffs = Array.from({ length: a.length }, (_, i) => Math.abs(a[i]! - b[i]!))
    diffs.sort((x, y) => x - y)
    const mean = diffs.reduce((s, d) => s + d, 0) / diffs.length
    const p99 = diffs[Math.min(diffs.length - 1, Math.floor(diffs.length * 0.99))]!
    return { mean, p99 }
  }

  it("TS(Skia) 渲染与 Pillow 参照：结构与几何一致（均值差 < 0.5 / p99 < 15，阈值实测校定）", async () => {
    const tsPng = await renderSpec(spec)
    const refBuf = readFileSync(`${GOLDEN}/assets/scenes_ref.png`)
    const { mean, p99 } = await diffStats(tsPng, refBuf, 270, 480)
    // 实测（arc 内缩修正后）：mean=0.144 / p99=5 / max=79（max 为单像素 AA 尾部）。
    // 阈值留机桶余量（Pillow↔Skia 的 AA 差异随系统/架构漂移），不贴地皮。
    expect(mean, `降采样灰度均值绝对差（实测 ${mean.toFixed(3)}）`).toBeLessThan(0.5)
    expect(p99, `降采样灰度 p99（实测 ${p99}）`).toBeLessThan(15)
  })
})
