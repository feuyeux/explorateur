// textlayer.test.ts — Edge 渲字层：verify_textlayer.py 的反向验证移植 + matte
// 数学合成夹具契约（不依赖浏览器，精确验收「双底除底色外逐字节同构」）。
//
// html_escape / page 由 inline fixture 直接验；视口亏空 / 截图裁齐 / 中文 & RTL
// 渲字历史曾验，后者正是「文字必须走 Edge 截图不许成像库画字」铁律的活证据——
// 浏览器相关部分用描述级 skipIf 在没浏览器机器上跳过。
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import sharp from "sharp"

import { matteCombineBuffer } from "../src/imaging/matte.js"
import { page } from "../src/textlayer.js"

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-textlayer-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("html_escape / page 形状与布局就绪探针", () => {
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
})
