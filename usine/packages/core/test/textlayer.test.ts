// textlayer.test.ts — Edge 渲字层：html_escape/page 金样本逐字节 parity +
// verify_textlayer.py 的反向验证移植 + 视口亏空 memoize 契约。
//
// matte 数学用合成夹具（不依赖浏览器）精确验收「双底除底色外逐字节同构」
// 这条使用契约；真机（有浏览器时）验视口亏空/截图裁齐/中文渲字/阿拉伯 RTL
// 渲字——后者正是「文字必须走 Edge 截图不许成像库画字」铁律的活证据。
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it } from "vitest"

import sharp from "sharp"

import { alphaStats, matteCombineBuffer } from "../src/imaging/matte.js"
import { platform } from "../src/index.js"
import {
  edgeScreenshot,
  htmlEscape,
  page,
  resetDeficitCacheForTests,
  shootMatte,
  viewportDeficit,
} from "../src/textlayer.js"

const BROWSER = platform.browser()
const goldenPath = fileURLToPath(new URL("../../../migration/golden/textlayer.json", import.meta.url))
const golden = JSON.parse(readFileSync(goldenPath, "utf8")) as {
  data: {
    html_escape: { s: string; out: string }[]
    page: { w: number; h: number; body: string; bg: string; font: string; dir_: string; out: string }[]
    viewport_deficit: Record<string, { deficit: number; win_h: number }>
    matte_shot: { alpha_stats: { size: [number, number]; coverage: number; alpha_mean_nonzero: number; alpha_max: number; bbox: [number, number, number, number] } }
  }
}
const assetsDir = fileURLToPath(new URL("../../../migration/golden/assets/textlayer", import.meta.url))

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-textlayer-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("html_escape / page 金样本 parity（逐字节）", () => {
  it("html_escape：& < > 三字符（含中文/阿拉伯语原文直通）", () => {
    expect(golden.data.html_escape.length).toBe(4)
    for (const c of golden.data.html_escape) {
      expect(htmlEscape(c.s)).toBe(c.out)
    }
  })

  it("page：两形态与 Python 逐字节一致（ltr 中文 / rtl 阿拉伯）", () => {
    expect(golden.data.page.length).toBe(2)
    for (const c of golden.data.page) {
      expect(page(c.w, c.h, c.body, { bg: c.bg, font: c.font, dir: c.dir_ })).toBe(c.out)
    }
  })

  it("page() 五参数全部落进 HTML + 布局就绪探针 script（verify_textlayer §0）", () => {
    const pg = page(1080, 300, "<p>你好</p>", { bg: "#000123", font: "'PingFang SC',sans-serif", dir: "rtl" })
    for (const x of ["width:1080px", "height:300px", "#000123", "'PingFang SC',sans-serif", "direction:rtl"]) {
      expect(pg).toContain(x)
    }
    expect(pg).toContain("document.body.offsetHeight")
  })
})

describe("matte 数学：合成夹具精确还原（verify_textlayer §1 移植）", () => {
  // 与 Python 侧同构：在白/黑底上叠同一块半透明 (200,50,50,128)
  function makeShot(bg: number, alpha: number, out: string): Promise<string> {
    const W = 400, H = 220
    const a = alpha / 255
    const raw = Buffer.alloc(W * H * 3)
    for (let i = 0; i < W * H; i++) {
      const x = i % W, y = Math.floor(i / W)
      const inRect = x >= 100 && x < 300 && y >= 60 && y < 160
      for (let c = 0; c < 3; c++) {
        const fg = [200, 50, 50][c]!
        raw[i * 3 + c] = inRect ? Math.round(fg * a + bg * (1 - a)) : bg
      }
    }
    return sharp(raw, { raw: { width: W, height: H, channels: 3 } }).png().toFile(out).then(() => out)
  }

  async function regionStats(png: string) {
    const { data, info } = await sharp(png).raw().toBuffer({ resolveWithObject: true })
    let sum = 0, sumSq = 0, n = 0, rSum = 0
    for (let y = 80; y < 140; y++) {
      for (let x = 120; x < 280; x++) {
        const p = (y * info.width + x) * 4
        const al = data[p + 3]!
        sum += al
        sumSq += al * al
        rSum += data[p]!
        n++
      }
    }
    const mean = sum / n
    return { mean, std: Math.sqrt(sumSq / n - mean * mean), rMean: rSum / n }
  }

  it("半透明块：alpha ≈128 区内均匀，去预乘 R ≈200，底区全透明", async () => {
    const d = tmp()
    const pw = await makeShot(255, 128, join(d, "w.png"))
    const pb = await makeShot(0, 128, join(d, "b.png"))
    const out = join(d, "m.png")
    writeFileSync(out, await matteCombineBuffer(pw, pb))
    const st = await regionStats(out)
    expect(Math.abs(st.mean - 128)).toBeLessThanOrEqual(2.0)
    expect(st.std).toBeLessThanOrEqual(1.5)
    expect(Math.abs(st.rMean - 200)).toBeLessThanOrEqual(4.0)
    const { data } = await sharp(out).raw().toBuffer({ resolveWithObject: true })
    expect(data[(5 * 400 + 5) * 4 + 3]!).toBe(0) // 底区全透明
  })

  it("全不透明区 → alpha ≈255", async () => {
    const d = tmp()
    const pw = await makeShot(255, 255, join(d, "w.png"))
    const pb = await makeShot(0, 255, join(d, "b.png"))
    const out = join(d, "m.png")
    writeFileSync(out, await matteCombineBuffer(pw, pb))
    const { data } = await sharp(out).raw().toBuffer({ resolveWithObject: true })
    expect(data[(100 * 400 + 200) * 4 + 3]!).toBeGreaterThanOrEqual(253)
  })

  it("金样本双底输入对 → 与 Python PIL 输出逐像素一致（matte 只做解码后的纯数学）", async () => {
    const got = await matteCombineBuffer(
      join(assetsDir, "matte_w.png"),
      join(assetsDir, "matte_b.png"),
    )
    const want = await sharp(join(assetsDir, "matte.png")).raw().toBuffer({ resolveWithObject: true })
    const g = await sharp(got).raw().toBuffer({ resolveWithObject: true })
    expect(g.info.width).toBe(want.info.width)
    expect(g.info.height).toBe(want.info.height)
    let diff = 0
    for (let i = 0; i < g.data.length; i++) {
      if (g.data[i] !== want.data[i]) diff++
    }
    expect(diff, "与 Python matte_combine 逐像素差异数").toBe(0)
  })
})

describe.skipIf(BROWSER === null)("真机：视口亏空 / 截图裁齐 / 渲字（verify_textlayer §2 移植）", () => {
  it("视口亏空探测：金样本同机桶一致 + memoize 命中不再探测", () => {
    resetDeficitCacheForTests()
    const d1 = tmp()
    const d2 = tmp()
    const [deficit1, winH1] = viewportDeficit(300, { workdir: d1 })
    expect(existsSync(join(d1, "_vp_probe.html"))).toBe(true) // 首调真探测
    const [deficit2, winH2] = viewportDeficit(800, { workdir: d2 })
    // memoize 契约：同 browser 键命中 → 不再写探测 HTML（d2 里没有）
    expect(existsSync(join(d2, "_vp_probe.html"))).toBe(false)
    expect([deficit1, winH1]).toEqual([
      golden.data.viewport_deficit["300"]!.deficit,
      golden.data.viewport_deficit["300"]!.win_h,
    ])
    expect([deficit2, winH2]).toEqual([
      golden.data.viewport_deficit["800"]!.deficit,
      golden.data.viewport_deficit["800"]!.win_h,
    ])
    expect(winH1).toBeGreaterThanOrEqual(300)
    expect(deficit1).toBeGreaterThanOrEqual(0)
    // 缓存键含 browser：换（不存在的）浏览器 → cache miss → 显式炸
    expect(() => viewportDeficit(300, { browser: "/nonexistent-browser", workdir: d2 })).toThrow()
  })

  it("单次截图裁齐画布（补偿尾巴已裁）+ 中文渲字", async () => {
    const d = tmp()
    const body = '<div style="display:flex;align-items:center;justify-content:center;height:300px;font-size:64px;color:#333">一叶知秋</div>'
    const png = await edgeScreenshot(page(400, 300, body), join(d, "opaque.png"), {
      width: 400, canvasH: 300, workdir: join(d, "html"),
    })
    const meta = await sharp(png).metadata()
    expect([meta.width, meta.height]).toEqual([400, 300])
  })

  it("阿拉伯 RTL 渲字 matte：有墨、RGBA、裁齐，结构统计与金样本同机桶一致", async () => {
    const d = tmp()
    // 与 capture_textlayer 的 matte_html 同构（RTL + text-shadow——成像库画不出的塑形）
    const htmlFn = (bg: string) => page(
      480, 320,
      '<div style="font-size:48px;color:#2b2b2b;text-shadow:0 2px 6px rgba(0,0,0,.35)">أوراق الخريف</div>',
      { bg, font: "sans-serif", dir: "rtl" },
    )
    const out = await shootMatte(htmlFn, join(d, "matte.png"), {
      width: 480, canvasH: 320, workdir: join(d, "html"),
    })
    const st = await alphaStats(out)
    const want = golden.data.matte_shot.alpha_stats
    expect(st.size).toEqual(want.size)
    expect(st.coverage).toBeCloseTo(want.coverage, 5)
    expect(st.alphaMeanNonzero).toBeCloseTo(want.alpha_mean_nonzero, 2)
    expect(st.alphaMax).toBe(want.alpha_max)
    expect(st.bbox).toEqual(want.bbox)
  })
})
