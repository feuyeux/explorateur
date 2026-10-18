// scenes.test.ts — 场景原语的反向验证（Python 无单列 verify_scenes 门禁——
// 绘制面 parity 已由 imaging-spike2（scenes_ref 金样本）覆盖；本套守注册表
// 与 prerenderBg 装配线：键集对金样本（Python 注册表落盘）、全场景渲染冒烟、
// 未知场景名静默跳过（Python 语义）、幂等（不变量⑦））。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import sharp from "sharp"
import { describe, expect, it } from "vitest"

import { prerenderBg, SCENES } from "../src/scenes.js"
import { H, hexc, mix, W } from "../src/rig.js"

const GOLDEN = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../../migration/golden/scenes_registry.json", import.meta.url)), "utf8"),
) as { scenes: string[] }

describe("scenes 注册表（单一事实源 ↔ Python 金样本）", () => {
  it("键集与 Python 注册表逐名一致（65 场景名，含 arch/lantern/boardn 双名）", () => {
    const names = Object.keys(SCENES).sort()
    expect(names).toEqual([...GOLDEN.scenes].sort())
    expect(names.length).toBe(65)
    // 双名注册：两个名字指到同一实现（不是两个各自为政的拷贝）
    expect(SCENES["gate_arch"]).toBe(SCENES["arch"])
    expect(SCENES["lantern"]).toBe(SCENES["lanterns"])
    expect(SCENES["board_notice"]).toBe(SCENES["board"])
  })
})

describe("prerenderBg 装配线", () => {
  it("全 65 场景一张卡渲染冒烟：W×H 产物、无抛错", { timeout: 120_000 }, async () => {
    const png = await (await prerenderBg({ identity: "#C46A4A" }, { scene: Object.keys(SCENES) }))
      .png().toBuffer()
    const meta = await sharp(png).metadata()
    expect(meta.width).toBe(W)
    expect(meta.height).toBe(H)
  })

  it("未知场景名静默跳过（Python SCENES.get 语义），不抛错", { timeout: 60_000 }, async () => {
    const png = await (await prerenderBg({ identity: "#5A8AC4" }, { scene: ["no_such_scene", "sun"] as const }))
      .png().toBuffer()
    expect(png.length).toBeGreaterThan(0)
  })

  it("幂等：同参数两渲 PNG 逐字节一致（不变量⑦）", { timeout: 120_000 }, async () => {
    const card = { scene: ["sun", "mountains", "bunting"] as const }
    const a = await (await prerenderBg({ identity: "#8A5AC4" }, card)).png().toBuffer()
    const b = await (await prerenderBg({ identity: "#8A5AC4" }, card)).png().toBuffer()
    expect(a.equals(b)).toBe(true)
  })
})

describe("prerenderBg 渐变像素回归（P5-7d 接线 storyteller 时实测抓出的错位 bug）", () => {
  // 曾有 bug：3 通道 raw 一把 data.set 进 RGBA ImageData——RGB 字节流错位铺开、
  // 尾部 1/4 全透明。此用例直接采样渐变行像素，冒烟测尺寸/幂等都拦不住它。
  it("渐变行像素 = mix(top, bottom, y/(H-1)) 且全不透明；地被行是 ground 色", { timeout: 60_000 }, async () => {
    const ident = hexc("#8a6d4e")
    const pipe = await prerenderBg({ identity: "#8a6d4e" }, { scene: [] })
    const { data, info } = await pipe.png().raw().toBuffer({ resolveWithObject: true })
    const px = (x: number, y: number): [number, number, number, number] => {
      const o = (y * info.width + x) * info.channels
      return [data[o]!, data[o + 1]!, data[o + 2]!, info.channels === 4 ? data[o + 3]! : 255]
    }
    const near = (got: readonly number[], want: readonly number[]) =>
      got.every((v, i) => Math.abs(v - want[i]!) <= 3)
    const top = mix([246, 243, 238], ident, 0.10)
    const bottom = mix([236, 232, 224], ident, 0.20)
    // 顶行 = top；y=1690 = 线性插值；地被（y≥1700）= ground（画在 ground 色上）
    expect(near(px(50, 2), [...top, 255])).toBe(true)
    const mid = mix(top, bottom, 1690 / (H - 1))
    expect(near(px(50, 1690), [...mid, 255])).toBe(true)
    const ground = mix([230, 226, 216], ident, 0.18)
    expect(near(px(50, 1900), [...ground, 255])).toBe(true)
    // 全图不透明（曾出现尾部 1/4 alpha=0）
    let opaque = true
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] !== 255) { opaque = false; break }
    }
    expect(opaque).toBe(true)
    expect(info.width).toBe(W)
    expect(info.height).toBe(H)
  })
})
