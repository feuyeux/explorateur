// textlayer.test.ts — Edge 渲字层：verify_textlayer.py 的反向验证移植 + matte
// 数学合成夹具契约（不依赖浏览器，精确验收「双底除底色外逐字节同构」）。
//
// html_escape / page 由 inline fixture 直接验；视口亏空 / 截图裁齐 / 中文 & RTL
// 渲字历史曾验，后者正是「文字必须走 Edge 截图不许成像库画字」铁律的活证据——
// 浏览器相关部分用描述级 skipIf 在没浏览器机器上跳过。
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { isAbsolute, join, resolve } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import sharp from "sharp"

import { matteCombineBuffer } from "../src/imaging/matte.js"
import { edgeScreenshot, page, resetDeficitCacheForTests } from "../src/textlayer.js"

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-textlayer-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  resetDeficitCacheForTests()
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

// 反向验证（纪律 2）：`--screenshot` 只认绝对路径、且父目录必须已存在——两条都是
// 「退出码 0 + 不产出文件 + 不报错」的静默失败。用**假浏览器**把真实调用路径上的
// 实参录下来，所以不需要真浏览器，也不受平台宽容度影响（真 Chrome 在 macOS 上可能
// 容忍相对路径，那样用真浏览器验不出修前红）。
describe("截图输出路径：交给浏览器的 --screenshot 必须绝对（相对路径静默不落盘）", () => {
  /** 假浏览器：`--dump-dom` 回视口探针，`--screenshot=` 复制夹具 png 并把实参记下来。 */
  function fakeBrowser(dir: string, fixture: string, argvLog: string): string {
    const sh = join(dir, "fake-browser.sh")
    writeFileSync(
      sh,
      [
        "#!/bin/sh",
        `FIX=${JSON.stringify(fixture)}`,
        `LOG=${JSON.stringify(argvLog)}`,
        'for a in "$@"; do case "$a" in',
        '  --screenshot=*) printf "%s\\n" "${a#--screenshot=}" >> "$LOG"; cp "$FIX" "${a#--screenshot=}" ;;',
        "esac; done",
        'printf "<html><head><title>300</title></head></html>"',
        "",
      ].join("\n"),
      "utf8",
    )
    chmodSync(sh, 0o755)
    return sh
  }

  it("相对 outPng → 浏览器收到绝对路径，父目录被建出来，文件真落盘", async () => {
    const d = tmp()
    const fixture = await sharp({
      create: { width: 200, height: 100, channels: 3, background: "#336699" },
    }).png().toBuffer()
    const fixPath = join(d, "fixture.png")
    writeFileSync(fixPath, fixture)
    const argvLog = join(d, "argv.log")
    const browser = fakeBrowser(d, fixPath, argvLog)

    // 关键：**相对**输出路径，且父目录一开始不存在（两条静默失败同时出现）
    const cwd = process.cwd()
    const workdir = join(d, "work")
    mkdirSync(workdir, { recursive: true })
    process.chdir(workdir)
    // chdir 后取真实 cwd：macOS 的 /var 是 /private/var 的软链，process.cwd() 会给出
    // 真实路径，直接拿 tmpdir() 的原始串比对会假红。
    const realWorkdir = process.cwd()
    let got: string
    try {
      got = await edgeScreenshot(page(200, 100, "<b>x</b>"), join("out", "rel.png"), {
        width: 200, canvasH: 100, browser,
      })
    } finally {
      process.chdir(cwd)
    }

    // 1. 调用方拿到的是绝对路径
    expect(isAbsolute(got)).toBe(true)
    expect(got).toBe(join(realWorkdir, "out", "rel.png"))
    // 2. 浏览器收到的 --screenshot 实参也是绝对路径（修前这里是 "out/rel.png"）
    const passed = readFileSync(argvLog, "utf8").trim().split("\n")
    expect(passed).toHaveLength(1)
    expect(isAbsolute(passed[0]!)).toBe(true)
    expect(passed[0]).toBe(got)
    // 3. 父目录确实被建了，文件确实存在（不是「退出 0 就当真」）
    expect(existsSync(got)).toBe(true)
  })

  it("凿洞：rel 路径直接喂浏览器（修前写法）→ 实参不是绝对路径", () => {
    // 把修前的行为原样复现一遍：证明上面那条断言不是恒真。
    const bad = join("out", "rel.png")
    expect(isAbsolute(bad)).toBe(false)
    expect(isAbsolute(resolve(bad))).toBe(true)
  })
})
