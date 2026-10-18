// scenes.test.ts — 场景原语的反向验证（Python 无单列 verify_scenes 门禁——
// 绘制面 parity 已由 imaging-spike2（scenes_ref 金样本）覆盖；本套守注册表
// 与 prerenderBg 装配线：键集对金样本（Python 注册表落盘）、全场景渲染冒烟、
// 未知场景名静默跳过（Python 语义）、幂等（不变量⑦））。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import sharp from "sharp"
import { describe, expect, it } from "vitest"

import { prerenderBg, SCENES } from "../src/scenes.js"
import { H, W } from "../src/rig.js"

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
