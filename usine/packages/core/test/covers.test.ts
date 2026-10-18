// covers.test.ts — 封面机制的反向验证（verify_covers.py 的 TS 移植）。
//
// 第 0 条好数据放行：五个平台规格、命名、裁切几何全部正确。反向各防一种
// 真实退化：尺寸不符 → check 必报（错版上传平台会二次裁切）、底色不符 →
// check 必报（外圈众数取样——平均值会被照片出血带偏）、**文字放错安全区 →
// displayCrop 的预览里墨迹消失**（两次学费的教训做成可执行判据）。
//
// 展示裁切的几何判定用 sharp 画的墨块夹具（任何机器可跑，无浏览器依赖）；
// Edge 渲字部分（文字真实渲出来的墨迹判定 + 真机封面过 check）浏览器门控。
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import sharp from "sharp"

import {
  SPECS, check, displayCrop, filename, make, sheet, spec,
} from "../src/covers.js"
import { FeuilleError } from "../src/errors.js"
import { platform } from "../src/index.js"
import { page } from "../src/textlayer.js"

const BROWSER = platform.browser()

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-covers-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

/** 纯色底图 + 一块墨迹矩形（sharp 画夹具，不依赖浏览器）。 */
async function inkFixture(path: string, w: number, h: number, bg: string, ink: string,
  rect: { left: number; top: number; width: number; height: number }): Promise<string> {
  await sharp({ create: { width: w, height: h, channels: 4, background: bg } })
    .composite([{
      input: Buffer.from(
        `<svg width="${rect.width}" height="${rect.height}">` +
        `<rect width="100%" height="100%" fill="${ink}"/></svg>`),
      left: rect.left, top: rect.top,
    }])
    .png().toFile(path)
  return path
}

/** 纯色底夹具里的墨迹像素数（通道差 >60 计墨）。 */
async function inkCount(png: string | Buffer, bg: string): Promise<number> {
  const bgRgb = [1, 3, 5].map((i) => parseInt(bg.slice(i, i + 2), 16)) as [number, number, number]
  const { data, info } = await sharp(png).removeAlpha().toColorspace("srgb")
    .raw().toBuffer({ resolveWithObject: true })
  let n = 0
  for (let i = 0; i < info.width * info.height; i++) {
    let isInk = false
    for (let c = 0; c < 3; c++) {
      if (Math.abs(data[i * info.channels + c]! - bgRgb[c]!) > 60) isInk = true
    }
    if (isInk) n++
  }
  return n
}

describe("好数据放行：规格表 / 命名（纯函数）", () => {
  it("展示裁切框正确（小红书 3:4 y240–1680 / B 站 4:3 x240–1680 / 抖音3:4 无裁切）", () => {
    expect(SPECS.xiaohongshu!.safe).toEqual([0, 240, 1080, 1680])
    expect(SPECS.bilibili!.safe).toEqual([240, 0, 1680, 1080])
    expect(SPECS.douyin34!.safe).toBeNull()
  })

  it("命名口径（中文_规格键_宽x高.png）", () => {
    expect(filename("中文", "douyin34")).toBe("中文_douyin34_1080x1440.png")
  })

  it("未知规格 → FeuilleError（合法键清单在消息里）", () => {
    expect(() => spec("nope")).toThrow(FeuilleError)
    expect(() => spec("nope")).toThrow("nope")
  })
})

describe("check：尺寸 + 外圈众数底色（sharp 夹具，任何机器可跑）", () => {
  it("好数据：白底 1080×1920 过 xiaohongshu 检查", async () => {
    const d = tmp()
    const good = join(d, "good_xhs.png")
    await sharp({ create: { width: 1080, height: 1920, channels: 3, background: "#FFFFFF" } })
      .png().toFile(good)
    expect(await check(good, "xiaohongshu")).toEqual([])
  })

  it("反向：1080×1920 传 douyin34 规格 → check 报尺寸", async () => {
    const d = tmp()
    const wrongSize = join(d, "wrong_size.png")
    await sharp({ create: { width: 1080, height: 1920, channels: 3, background: "#000000" } })
      .png().toFile(wrongSize)
    const probs = await check(wrongSize, "douyin34")
    expect(probs.some((s) => s.includes("尺寸"))).toBe(true)
  })

  it("反向：白底传抖音黑底规格 → check 报底色（众数取样）", async () => {
    const d = tmp()
    const wrongBg = join(d, "wrong_bg.png")
    await sharp({ create: { width: 1080, height: 1440, channels: 3, background: "#FFFFFF" } })
      .png().toFile(wrongBg)
    const probs = await check(wrongBg, "douyin34")
    expect(probs.some((s) => s.includes("底色"))).toBe(true)
  })
})

describe("展示裁切几何：文字进/出安全区（两次学费的可执行判据，sharp 夹具）", () => {
  it("小红书：墨块落在 y240 裁切带 → displayCrop 后墨迹消失", async () => {
    const d = tmp()
    const png = await inkFixture(join(d, "xhs_100.png"), 1080, 1920, "#FFFFFF", "#111111",
      { left: 340, top: 100, width: 400, height: 64 })
    const origInk = await inkCount(png, SPECS.xiaohongshu!.bg)
    const prev = await displayCrop(png, "xiaohongshu")
    const prevInk = await inkCount(prev, SPECS.xiaohongshu!.bg)
    expect(prevInk).toBeLessThanOrEqual(origInk * 0.2)
  })

  it("小红书：墨块在安全区 y240–1680 内 → 展示裁切后保留", async () => {
    const d = tmp()
    const png = await inkFixture(join(d, "xhs_900.png"), 1080, 1920, "#FFFFFF", "#111111",
      { left: 340, top: 900, width: 400, height: 64 })
    const origInk = await inkCount(png, SPECS.xiaohongshu!.bg)
    const prev = await displayCrop(png, "xiaohongshu")
    const prevInk = await inkCount(prev, SPECS.xiaohongshu!.bg)
    expect(prevInk).toBeGreaterThanOrEqual(origInk * 0.8)
  })

  it("B 站：墨块落在 x240 裁切带 → displayCrop 后墨迹消失", async () => {
    const d = tmp()
    const png = await inkFixture(join(d, "bili_left.png"), 1920, 1080, "#FB7299", "#FFFFFF",
      { left: 40, top: 400, width: 160, height: 64 })
    const origInk = await inkCount(png, SPECS.bilibili!.bg)
    const prev = await displayCrop(png, "bilibili")
    const prevInk = await inkCount(prev, SPECS.bilibili!.bg)
    expect(prevInk).toBeLessThanOrEqual(origInk * 0.2)
  })

  it("B 站：墨块在安全区 x240–1680 内 → 展示裁切后保留", async () => {
    const d = tmp()
    const png = await inkFixture(join(d, "bili_mid.png"), 1920, 1080, "#FB7299", "#FFFFFF",
      { left: 800, top: 400, width: 320, height: 64 })
    const origInk = await inkCount(png, SPECS.bilibili!.bg)
    const prev = await displayCrop(png, "bilibili")
    const prevInk = await inkCount(prev, SPECS.bilibili!.bg)
    expect(prevInk).toBeGreaterThanOrEqual(origInk * 0.8)
  })

  it("safe=null 原样返回（douyin34 上传即展示，无裁切）", async () => {
    const d = tmp()
    const png = await inkFixture(join(d, "dy34.png"), 1080, 1440, "#000000", "#FFFFFF",
      { left: 340, top: 40, width: 400, height: 64 })
    const origInk = await inkCount(png, SPECS.douyin34!.bg)
    const prev = await displayCrop(png, "douyin34")
    const prevInk = await inkCount(prev, SPECS.douyin34!.bg)
    expect(prevInk).toBe(origInk)
  })

  it("对照图 sheet：纵向拼接（宽=最宽预览，2px 深灰间隔）", async () => {
    const d = tmp()
    const xhs = await inkFixture(join(d, "s_xhs.png"), 1080, 1920, "#FFFFFF", "#111111",
      { left: 340, top: 900, width: 400, height: 64 })
    const bili = await inkFixture(join(d, "s_bili.png"), 1920, 1080, "#FB7299", "#FFFFFF",
      { left: 800, top: 400, width: 320, height: 64 })
    const prev1 = join(d, "prev_xhs.png")
    const prev2 = join(d, "prev_bili.png")
    await sharp(await displayCrop(xhs, "xiaohongshu")).png().toFile(prev1)
    await sharp(await displayCrop(bili, "bilibili")).png().toFile(prev2)
    const out = await sheet([prev1, prev2], join(d, "sheet.png"))
    const meta = await sharp(out).metadata()
    // xhs 预览 3:4（1440 高）+ bili 预览 4:3（1080 高）+ 间隔 2
    expect([meta.width, meta.height]).toEqual([1440, 1440 + 1080 + 2])
  })
})

describe.skipIf(BROWSER === null)("Edge 渲字演示：文字真实渲出来的墨迹判定", () => {
  function demoHtml(w: number, h: number, bg: string, textY: number,
    text = "一叶知秋 · 演示", ink = "#111111"): string {
    return page(w, h,
      `<div style="position:absolute;left:0;right:0;top:${textY}px;` +
      `text-align:center;font-size:64px;font-weight:600;color:${ink}">${text}</div>`,
      { bg })
  }

  // 小红书 y=100 在 240 裁切带内 → 发出去就没了；y=900 在安全区；B 站 y=0 全高安全
  it.each([
    ["xiaohongshu", 100, "#14171E", false],
    ["xiaohongshu", 900, "#14171E", true],
    ["bilibili", 0, "#FFFFFF", true],
  ] as const)("demo_%s 文字 y=%i → %s", async (key, textY, ink, expectSurvive) => {
    const d = tmp()
    const s = SPECS[key]!
    const png = join(d, `demo_${key}_${textY}.png`)
    await make(key, demoHtml(s.w, s.h, s.bg, textY, undefined, ink as string), png, { workdir: join(d, "html") })
    const origInk = await inkCount(png, s.bg)
    const prev = await displayCrop(png, key)
    const prevInk = await inkCount(prev, s.bg)
    if (expectSurvive) {
      expect(prevInk).toBeGreaterThanOrEqual(origInk * 0.8)
    } else {
      // 这正是小红书标签整行被切的事故：预览里墨迹消失
      expect(prevInk).toBeLessThanOrEqual(origInk * 0.2)
    }
  })

  it("真机封面也过尺寸/底色检查", async () => {
    const d = tmp()
    const png = join(d, "demo_douyin34.png")
    await make("douyin34", demoHtml(1080, 1440, "#000000", 600, "一叶知秋 · 演示", "#FFFFFF"),
      png, { workdir: join(d, "html") })
    expect(await check(png, "douyin34")).toEqual([])
  })
})
