// textlayer.ts — Edge headless 渲字：视口探测 / 截图 / 双 matte 抠像
// （textlayer.py 的 TS 移植）。
//
// **为什么文字必须走 Edge 截图而不是成像库画字**：阿拉伯语 / 希伯来语 /
// 天城文需要完整塑形（HarfBuzz/FriBiDi），Chromium 内核自带，一次截图就对。
// 这是铁律级的经验（workspace AGENTS.md）。
//
// **视口亏空**：Edge 的 `--window-size` 高度 ≠ 实际视口高度（实测 300 → 206，
// 差值随版本/机器变）。**先探一次差值**、之后所有截图用补偿后的窗口高度——
// 不写死差值，换机器自动重测。探法：`--dump-dom` 读 `window.innerHeight`。
// 探测结果按 (browser, nominal) memoize（设计内置的性能修复：Python 侧每次
// 截图都要多开一次浏览器探亏空；亏空只随浏览器版本/机器变，进程内不变）。
//
// **双 matte 抠像的数学**：白底/黑底各截一次，`C_w - C_b = (1-a)·255` →
// `alpha = 255 - max(C_w - C_b)`；去预乘 `rgb = C_b / a`。半透明投影可精确还原
// （实现与像素口径在 imaging/matte.ts）。不透明整图（封面）**不需要**这套，
// 单次截图即可。双底截图后**载入前裁齐画布**：补高后的 opaque 截图比画布
// 高一截，不裁会把画布外的深色像素贴进成片。
//
// **Edge 截图一律串行**：4 线程并发曾被系统 SIGKILL——并发收益是分钟级，
// 炸掉是整批重做，不赌。execFileSync 天然串行（阻塞事件循环），保持同步
// spawn 不改 async，纪律由机制承载。
//
// 浏览器一律经 `platform` 解析，绝不写死路径（跨平台约定 1）。
import { execFileSync } from "node:child_process"
import { mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs"
import { basename, dirname, join, resolve } from "node:path"
import { pathToFileURL } from "node:url"

import sharp from "sharp"

import { FeuilleError } from "./errors.js"
import { matteCombineBuffer } from "./imaging/matte.js"
import { browser as resolveBrowser, HEADLESS_FLAGS } from "./platform.js"

const HTML_HEAD = (w: number, h: number, body: string, bg: string, font: string, dir: string) =>
  `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;width:${w}px;height:${h}px;overflow:hidden;background:${bg};
font-family:${font};-webkit-font-smoothing:antialiased;direction:${dir};}
*{box-sizing:border-box}
</style></head><body>${body}<script>document.body.offsetHeight;</script></body></html>`

export function htmlEscape(s: string): string {
  return s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
}

/** 整页 HTML（尺寸/底色/字体栈/书写方向全部参数化；流式布局，别用 absolute）。 */
export function page(
  w: number,
  h: number,
  body: string,
  opts?: { bg?: string; font?: string; dir?: string },
): string {
  return HTML_HEAD(w, h, body, opts?.bg ?? "#FFFFFF", opts?.font ?? "sans-serif", opts?.dir ?? "ltr")
}

function requireBrowser(): string {
  const b = resolveBrowser()
  if (b === null) {
    throw new FeuilleError(
      "缺 Chromium 内核浏览器（渲字必需；resolver 未找到，缺件清单见 platform.missing()）",
    )
  }
  return b[1]
}

// --force-device-scale-factor=1：保证 png 尺寸 == 窗口尺寸，不随系统缩放漂
function shotArgs(
  browser: string,
  width: number,
  winH: number,
  png: string,
  html: string,
  budgetMs: number,
): string[] {
  return [
    "--headless=new", "--disable-gpu", ...HEADLESS_FLAGS, "--hide-scrollbars",
    "--force-device-scale-factor=1", `--window-size=${width},${winH}`,
    `--screenshot=${png}`, `--virtual-time-budget=${budgetMs}`,
    pathToFileURL(html).href,
  ]
}

// 视口亏空 memoize：键 = browser|nominal（亏空与 canvas_h 无关，探测 HTML 里的
// canvas_h 只是 title 缺失时的回退值）。进程内浏览器版本不变，无需失效机制。
const deficitCache = new Map<string, number>()
export function resetDeficitCacheForTests(): void {
  deficitCache.clear()
}

/** 探一次视口亏空（坑⑩；按 browser memoize）。返回 [亏空 px, 补偿后的窗口高度]。
 *
 * 补偿后的 opaque 截图会比 canvasH 高一截——**调用方载入前必须裁到
 * (0, 0, W, canvasH)**（本模块的截图函数已内置裁齐，直接用它们即可）。 */
export function viewportDeficit(
  canvasH: number,
  opts?: { browser?: string | null; nominal?: number; workdir?: string },
): [number, number] {
  const browser = opts?.browser ?? requireBrowser()
  const nominal = opts?.nominal ?? 300
  const cacheKey = `${browser}|${nominal}`
  const cached = deficitCache.get(cacheKey)
  if (cached !== undefined) return [cached, canvasH + Math.max(0, cached)]

  const probeDir = opts?.workdir ?? process.cwd()
  mkdirSync(probeDir, { recursive: true })
  const probe = join(probeDir, "_vp_probe.html")
  writeFileSync(
    probe,
    HTML_HEAD(100, canvasH,
      "<div style='height:100vh'></div><script>document.title=window.innerHeight;</script>",
      "#FFFFFF", "sans-serif", "ltr"),
    "utf8",
  )
  const dom = execFileSync(
    browser,
    ["--headless=new", "--disable-gpu", ...HEADLESS_FLAGS,
      `--window-size=1080,${nominal}`,
      "--virtual-time-budget=800", "--dump-dom", pathToFileURL(probe).href],
    { timeout: 60_000, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  )
  const m = /<title>(\d+)<\/title>/.exec(dom)
  const viewport = m ? Number.parseInt(m[1]!, 10) : canvasH
  const chromePx = nominal - viewport
  deficitCache.set(cacheKey, chromePx)
  return [chromePx, canvasH + Math.max(0, chromePx)]
}

/** 补高后的截图裁回画布尺寸（viewportDeficit 的残留尾巴，就地裁）。 */
async function cropTo(png: string, w: number, h: number): Promise<void> {
  const meta = await sharp(png).metadata()
  if (meta.width === w && meta.height === h) return
  const tmp = `${png}.crop` // sharp 不支持就地写：tmp 落盘后顶替原名
  await sharp(png).extract({ left: 0, top: 0, width: w, height: h }).toFile(tmp)
  renameSync(tmp, png)
}

/** 浏览器 `--screenshot` 的输出目标：**必须绝对路径，且父目录必须已存在**。
 *
 * 两条都是「进程退出 0、文件不产出、也不报错」的静默失败（实测：相对路径 → 文件
 * 不落盘，报错一路拖到下游 sharp 才以 `Input file is missing: xxx.png` 露头，看着
 * 像「文件丢了」；目录不存在同样静默，与绝对/相对无关）。所以这两件事由机制在
 * 一处保证：调用方给什么路径都行，交给浏览器的永远是绝对路径。
 *
 * 为什么不一并在 `shotArgs` 里做：那样只是把相对路径蒙对，父目录仍然可能不存在，
 * 而且测试只能验「实参长什么样」、验不了「目录被建了」。
 */
export function shotTarget(outPng: string): string {
  const abs = resolve(outPng)
  mkdirSync(dirname(abs), { recursive: true })
  return abs
}

/** 不透明整图**单次**截图（封面等用这个；透明叠加层用 shootMatte）。
 * 视口亏空自动补偿 + 裁齐到 canvasH（坑⑩ + 残留尾巴一次处理完）。 */
export async function edgeScreenshot(
  html: string,
  outPng: string,
  opts: { width: number; canvasH: number; browser?: string | null; workdir?: string; budgetMs?: number },
): Promise<string> {
  const browser = opts.browser ?? requireBrowser()
  const out = shotTarget(outPng)
  const workdir = resolve(opts.workdir ?? process.cwd())
  mkdirSync(workdir, { recursive: true })
  const [, winH] = viewportDeficit(opts.canvasH, { browser, workdir })
  const hPath = join(workdir, `${basename(out).replace(/\.png$/, "")}.html`)
  writeFileSync(hPath, html, "utf8")
  rmSync(out, { force: true })
  execFileSync(
    browser,
    shotArgs(browser, opts.width, winH, out, hPath, opts.budgetMs ?? 1600),
    { timeout: 180_000, stdio: ["ignore", "pipe", "pipe"] },
  )
  await cropTo(out, opts.width, opts.canvasH)
  return out
}

/** 透明文字层：同一 HTML 在白底 / 黑底各截一次 → matteCombine 出精确 alpha。
 *
 * htmlFn(bgColor) 返回该底色下的整页 HTML（除底色外两份 HTML 必须逐字节同构，
 * 否则 matte 数学不成立）。输出已裁齐 canvasH。 */
export async function shootMatte(
  htmlFn: (bg: string) => string,
  outPng: string,
  opts: { width: number; canvasH: number; browser?: string | null; workdir?: string; budgetMs?: number },
): Promise<string> {
  const browser = opts.browser ?? requireBrowser()
  const out = shotTarget(outPng)
  const workdir = resolve(opts.workdir ?? process.cwd())
  mkdirSync(workdir, { recursive: true })
  const [, winH] = viewportDeficit(opts.canvasH, { browser, workdir })
  const stem = basename(out).replace(/\.png$/, "")
  const shots: string[] = []
  for (const [tag, bg] of [["_w", "#FFFFFF"], ["_b", "#000000"]] as const) {
    const hPath = join(workdir, `${stem}${tag}.html`)
    writeFileSync(hPath, htmlFn(bg), "utf8")
    const png = join(workdir, `${stem}${tag}.png`)
    rmSync(png, { force: true })
    execFileSync(
      browser,
      shotArgs(browser, opts.width, winH, png, hPath, opts.budgetMs ?? 1600),
      { timeout: 180_000, stdio: ["ignore", "pipe", "pipe"] },
    )
    await cropTo(png, opts.width, opts.canvasH)
    shots.push(png)
  }
  const combined = await matteCombineBuffer(shots[0]!, shots[1]!)
  writeFileSync(out, combined)
  return out
}
