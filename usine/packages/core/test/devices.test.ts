// devices.test.ts — 装置外框注册表的反向验证（Python 无单列 verify_devices 门禁——
// ②③ 校验层与 ⑥ 渲染线共用本表；本套守注册表键集对金样本、chip 两型契约、
// 井底色推导与 LAST_WELL_RGB 副作用、未知 style 当场报错（纪律 19）、
// panel 的 GROUND_Y 地面线语义（封面 null = 不画悬空立柱））。
//
// 画法断言用录制桩（PilDraw 接口的最小实现），不断像素——装置画的是
// 几何图形序列，录制桩断的是「画了什么」，比像素反推更精确。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it } from "vitest"

import * as devices from "../src/devices.js"
import { hexc, mix } from "../src/rig.js"
import type { Box, DrawOpts, PilDraw, Pt, RGB } from "../src/imaging/pildraw.js"

const GOLDEN = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../../migration/golden/scenes_registry.json", import.meta.url)), "utf8"),
) as { device_styles: string[] }

afterEach(() => {
  devices.setGroundY(1700)  // 成片默认地面线还原（封面用例会把它置 null）
})

/** 录制桩：把每次绘制记成结构化调用（不落像素）。 */
interface Recorded {
  op: string
  box?: readonly number[]
  rad?: number
  pts?: readonly (readonly number[] | number[])[]
  a0?: number
  a1?: number
  opts?: DrawOpts & { width?: number }
}

class Recorder implements PilDraw {
  calls: Recorded[] = []
  rectangle(box: Box, opts?: DrawOpts): void {
    this.calls.push({ op: "rectangle", box, opts })
  }
  roundedRectangle(box: Box, rad: number, opts?: DrawOpts): void {
    this.calls.push({ op: "roundedRectangle", box, rad, opts })
  }
  ellipse(box: Box, opts?: DrawOpts): void {
    this.calls.push({ op: "ellipse", box, opts })
  }
  line(pts: readonly Pt[] | readonly number[], opts?: DrawOpts & { width?: number }): void {
    this.calls.push({ op: "line", pts: pts as readonly (readonly number[] | number[])[], opts })
  }
  arc(box: Box, a0: number, a1: number, opts?: DrawOpts & { width?: number }): void {
    this.calls.push({ op: "arc", box, a0, a1, opts })
  }
  pieslice(box: Box, a0: number, a1: number, opts?: DrawOpts): void {
    this.calls.push({ op: "pieslice", box, a0, a1, opts })
  }
  chord(box: Box, a0: number, a1: number, opts?: DrawOpts): void {
    this.calls.push({ op: "chord", box, a0, a1, opts })
  }
  polygon(pts: readonly Pt[], opts?: DrawOpts): void {
    this.calls.push({ op: "polygon", pts, opts })
  }
}

describe("DEVICE_STYLES 注册表（单一事实源 ↔ Python 金样本）", () => {
  it("键集与 Python 注册表逐名一致（16 样式）", () => {
    expect(Object.keys(devices.DEVICE_STYLES).sort()).toEqual([...GOLDEN.device_styles].sort())
  })
})

describe("装置规格读取与 chip 两型契约", () => {
  it("deviceOf：prop.device 存在则取之，缺行 = 纯对话无装置", () => {
    expect(devices.deviceOf({ prop: { device: { style: "palette" } } })).toEqual({ style: "palette" })
    expect(devices.deviceOf({ prop: {} })).toBeUndefined()
    expect(devices.deviceOf({})).toBeUndefined()
  })

  it("wellColor：§0.2 显式 #hex 则用之，否则由场景中性色推导", () => {
    const pal = devices.scenePal([200, 60, 60], [60, 120, 200])
    expect(devices.wellColor({ well: "#112233" }, pal)).toEqual(hexc("#112233"))
    expect(devices.wellColor({}, pal)).toEqual(mix(pal.soft, [255, 255, 255], 0.55))
  })

  it("chipColor：`#hex` 色片 → RGB；其余字符串（含纯数字字牌）→ null", () => {
    expect(devices.chipColor("#AB10CD")).toEqual([171, 16, 205])
    expect(devices.chipColor("un café")).toBeNull()
    expect(devices.chipColor("1")).toBeNull()  // parse 落库后 "1" 与 1 不可区分——引号不是判据
    expect(devices.chipColor(1)).toBeNull()
    expect(devices.chipColor(null)).toBeNull()
  })

  it("scenePal：ink 为道具描边唯一色、accent = 双身份等权混合", () => {
    const a: RGB = [200, 60, 60]
    const b: RGB = [60, 120, 200]
    const pal = devices.scenePal(a, b)
    expect(pal.ink).toEqual([150, 144, 134])
    expect(pal.accent).toEqual(mix(a, b, 0.5))
    expect(pal.paper).toEqual([245, 241, 232])
  })
})

describe("drawDevice 外框与空井", () => {
  const pal = devices.scenePal([200, 60, 60], [60, 120, 200])
  const CELLS: devices.Cell[] = [
    [100, 100, 200, 200],
    [300, 100, 400, 200, "circle"],
    [500, 100, 600, 200, "rect"],
    [700, 100, 800, 200, "poly"],
  ]

  it("未知 style 当场报错（渲染时才炸 ≠ 静默渲错版）", () => {
    const rec = new Recorder()
    expect(() => devices.drawDevice(rec, { style: "bogus" }, CELLS, pal))
      .toThrowError(/未知装置 style：bogus/)
  })

  it("缺 style 默认 tray：只铺空井不画外框；box = cells 外扩 26", () => {
    const rec = new Recorder()
    const box = devices.drawDevice(rec, {}, CELLS, pal)
    expect([...box]).toEqual([100 - 26, 100 - 26, 800 + 26, 200 + 26])
    // tray 故意不画外框：井之外零绘制
    expect(rec.calls.length).toBe(4)
    expect(rec.calls.every((c) => (c.opts?.fill as unknown) === devices.LAST_WELL_RGB)).toBe(true)
    // 井形分派：缺省圆角 18 / circle→ellipse / rect→rectangle / poly→三角
    expect(rec.calls[0]).toMatchObject({ op: "roundedRectangle", rad: 18, box: [100, 100, 200, 200] })
    expect(rec.calls[1]).toMatchObject({ op: "ellipse", box: [300, 100, 400, 200] })
    expect(rec.calls[2]).toMatchObject({ op: "rectangle", box: [500, 100, 600, 200] })
    expect(rec.calls[3]).toMatchObject({
      op: "polygon",
      pts: [[750, 100], [700, 200], [800, 200]],
    })
  })

  it("LAST_WELL_RGB 逐调用更新（浅色 chip 判对比的直接背景层）", () => {
    const rec = new Recorder()
    devices.drawDevice(rec, { well: "#101010" }, CELLS.slice(0, 1), pal)
    expect(devices.LAST_WELL_RGB).toEqual(hexc("#101010"))
    devices.drawDevice(rec, {}, CELLS.slice(0, 1), pal)
    expect(devices.LAST_WELL_RGB).toEqual(mix(pal.soft, [255, 255, 255], 0.55))
  })

  it("panel：GROUND_Y=1700 画两根落地立柱（屏框外缘之外）", () => {
    const rec = new Recorder()
    const box = devices.drawDevice(rec, { style: "panel" }, CELLS.slice(0, 1), pal)
    const pillars = rec.calls.filter((c) => c.op === "rectangle" && c.box?.[3] === 1700)
    expect(pillars.length).toBe(2)
    const [x0, y0, x1, y1] = [...box] as [number, number, number, number]
    expect(pillars[0]?.box).toEqual([x0 - 62, y1 + 34, x0 - 62 + 24, 1700])
    expect(pillars[1]?.box).toEqual([x1 + 14, y1 + 34, x1 + 14 + 24, 1700])
    // 屏框 + 屏面在立柱之后（井底铺在最后）
    const frame = rec.calls.find((c) => c.op === "roundedRectangle" && c.rad === 26)
    expect(frame?.box).toEqual([x0 - 34, y0 - 30, x1 + 34, y1 + 34])
    const screen = rec.calls.find((c) => c.op === "roundedRectangle" && c.rad === 18)
    expect(screen?.box).toEqual([x0 - 14, y0 - 10, x1 + 14, y1 + 10])
  })

  it("panel：GROUND_Y=null（封面）不画立柱——没有地面，立柱只会悬空", () => {
    devices.setGroundY(null)
    const rec = new Recorder()
    devices.drawDevice(rec, { style: "panel" }, CELLS.slice(0, 1), pal)
    expect(rec.calls.some((c) => c.op === "rectangle" && c.box?.[3] === 1700)).toBe(false)
    // 屏框屏面照画
    expect(rec.calls.some((c) => c.op === "roundedRectangle" && c.rad === 26)).toBe(true)
  })
})
