// covers.ts — 封面机制（covers.py 的 TS 移植）：平台规格表 / 预裁底图 /
// 截图 / 展示裁切模拟 / 检查。
//
// 机制与版式分离：**版式是内容**，归各内容项目；本模块只留平台规格、
// 预裁、截图、裁切模拟与检查。
//
// **铁律**：
// - 封面永远是**预生成带文字图**，不是平台默认帧；纯画面首帧 = 未完成。
// - **上传比例 ≠ 展示比例**：平台会在信息流里二次裁切，贴边的文字会被切掉。
//   SPECS 的 `safe` 就是各平台真实展示裁切框——文字三要素（片名/首句/标签）
//   必须整体落在 safe 内。两次学费：小红书文字块排到 y1790 诗体标签整行被切；
//   B 站左图右文版式 4:3 中央裁切后只剩窄边（→ 改居中卡片）。
// - **底图预裁，不靠 CSS cover**：取景框写死（cropBackdrop 的 box 参数），
//   CSS cover 的裁切时机不可控，会把主体切到面板底下。
// - 文字标签**从单一事实源取**（调用方传入），不在封面代码里硬编码——
//   内容改了之后旧标签会一直印在封面上。
//
// **判定证据**：尺寸/底色可程序判（check）；**文字有没有被展示裁切换掉，
// 最终以 displayCrop 出的预览对照图 + 人眼为准**（照片底图无法程序判墨迹）。
import { mkdirSync, readFileSync } from "node:fs"
import { basename, dirname } from "node:path"

import sharp from "sharp"

import { FeuilleError } from "./errors.js"
import { browser as resolveBrowser } from "./platform.js"
import { edgeScreenshot } from "./textlayer.js"

// 平台规格（唯一事实源：尺寸 / 底色 / 展示裁切安全区）。
// safe = (x0, y0, x1, y1)：平台信息流实际展示的区域；null = 上传即展示、无裁切。
//   - 抖音竖封面槽实为 3:4：9:16 传上去会被居中裁掉上下各 240px（标题带正好被切没）
//   - 小红书信息流 3:4：1080×1920 上下各切 240 → 只保留 y 240–1680
//   - B 站首页推荐 4:3：1920×1080 左右各切 240 → 只保留 x 240–1680（个人空间 16:9 无裁切）
export interface CoverSpec {
  name: string
  w: number
  h: number
  bg: string
  safe: readonly [number, number, number, number] | null
}

export const SPECS: Record<string, CoverSpec> = {
  douyin: { name: "抖音", w: 1080, h: 1920, bg: "#000000", safe: null },
  douyin34: { name: "抖音3:4", w: 1080, h: 1440, bg: "#000000", safe: null },
  xiaohongshu: {
    name: "小红书", w: 1080, h: 1920, bg: "#FFFFFF",
    safe: [0, 240, 1080, 1680],
  },
  bilibili: {
    name: "哔哩哔哩", w: 1920, h: 1080, bg: "#FB7299",
    safe: [240, 0, 1680, 1080],
  },
  zhihu: { name: "知乎", w: 1920, h: 1080, bg: "#0084FF", safe: null },
}

/** 封面文件名（唯一命名口径，发布清单与检查同源）。 */
export function filename(name: string, key: string): string {
  const s = SPECS[key]!
  return `${name}_${key}_${s.w}x${s.h}.png`
}

export function spec(key: string): CoverSpec {
  const s = SPECS[key]
  if (s === undefined) {
    throw new FeuilleError(
      `未知封面规格 '${key}'（合法：${Object.keys(SPECS).sort().join(" / ")}）`,
    )
  }
  return s
}

/** 按写死的取景框从源图裁底图（**预裁**，不靠 CSS cover——裁切时机不可控）。
 *
 * box 的坐标空间跟调用方约定（示例项目用母版像素空间）；预裁后底图比例
 * 与画面区一致，叠版式时 CSS 不再做二次裁切。输出格式随扩展名（PIL save
 * 同款口径）；quality 只对 jpeg 系生效。
 */
export async function cropBackdrop(
  src: string,
  box: readonly [number, number, number, number],
  out: string,
  quality = 92,
): Promise<string> {
  const [l, t, r, b] = box
  mkdirSync(dirname(out), { recursive: true })
  const pipe = sharp(src)
    .extract({ left: l, top: t, width: r - l, height: b - t })
    .removeAlpha()
    .toColorspace("srgb")
  if (out.toLowerCase().endsWith(".png")) {
    await pipe.png().toFile(out)
  } else {
    await pipe.jpeg({ quality }).toFile(out)
  }
  return out
}

/** 整页封面 HTML → 不透明整图**单次**截图（文字一律 Edge 渲，不透明不需要双 matte）。
 *
 * html 由版式方（内容）产出；尺寸/裁齐由本机制按 SPECS 保证。
 */
export async function make(
  key: string,
  html: string,
  outPng: string,
  opts: { workdir?: string } = {},
): Promise<string> {
  const s = spec(key)
  return edgeScreenshot(html, outPng, {
    width: s.w,
    canvasH: s.h,
    workdir: opts.workdir,
    budgetMs: 2200,
  })
}

/** 模拟平台信息流的**真实展示裁切**（safe=null 原样返回）。
 *
 * 判定文字是否被切，以这个预览为准——上传图好看不等于发出去好看。
 * 返回 PNG 编码的 RGB 图（对齐 PIL convert("RGB").crop 的语义）。
 */
export async function displayCrop(png: string, key: string): Promise<Buffer> {
  const s = spec(key)
  let pipe = sharp(png).removeAlpha().toColorspace("srgb")
  if (s.safe !== null) {
    const [x0, y0, x1, y1] = s.safe
    pipe = pipe.extract({ left: x0, top: y0, width: x1 - x0, height: y1 - y0 })
  }
  return pipe.png().toBuffer()
}

/** 把若干预览纵向拼成对照图（发布后核对 / 裁切安全的人眼判据载体）。 */
export async function sheet(pngs: readonly (string | Buffer)[], out: string): Promise<string> {
  const metas = await Promise.all(
    pngs.map(async (p) => {
      const meta = await sharp(p).metadata()
      return { w: meta.width!, h: meta.height! }
    }),
  )
  const wmax = Math.max(...metas.map((m) => m.w))
  const totalH = metas.reduce((acc, m) => acc + m.h, 0) + 2 * (metas.length - 1)
  // 画布底色 (51,51,51)，逐张贴到 (0, y)，y 累加 h+2（2px 深灰间隔）
  const canvas = Buffer.alloc(wmax * totalH * 3, 51)
  let y = 0
  for (let i = 0; i < pngs.length; i++) {
    const { w, h } = metas[i]!
    const raw = await sharp(pngs[i]).removeAlpha().toColorspace("srgb").raw().toBuffer()
    for (let r = 0; r < h; r++) {
      raw.copy(canvas, wmax * (y + r) * 3, r * w * 3, w * 3)
    }
    y += h + 2
  }
  mkdirSync(dirname(out), { recursive: true })
  await sharp(canvas, { raw: { width: wmax, height: totalH, channels: 3 } }).png().toFile(out)
  return out
}

/** 尺寸 + 底色检查（问题列表；空 = 通过）。
 *
 * 底色按**外圈众数**取样：平均值会被照片出血带偏（实测知乎蓝被算成 (7,67,128)）。
 * 版式带边框/半幅面板时，外圈的主导色仍是契约底色——众数取的是「出现最多的」，
 * 照片色散、契约色聚，众数天然站得住。
 */
export async function check(png: string, key: string): Promise<string[]> {
  const s = spec(key)
  const problems: string[] = []
  const { data, info } = await sharp(png).removeAlpha().toColorspace("srgb")
    .raw().toBuffer({ resolveWithObject: true })
  if (info.width !== s.w || info.height !== s.h) {
    problems.push(
      `${basename(png)}: 尺寸 (${info.width}, ${info.height}) ≠ 规格 ${s.w}×${s.h}（${key}）`,
    )
    return problems
  }
  const want = [1, 3, 5].map((i) => parseInt(s.bg.slice(i, i + 2), 16))
  const ch = info.channels
  const px = (x: number, y: number): string => {
    const o = (y * info.width + x) * ch
    return `${data[o]!},${data[o + 1]!},${data[o + 2]!}`
  }
  // 外圈环取样（d=2）：上下各两行扫全宽，左右各两列扫中间段
  const counts = new Map<string, number>()
  const bump = (k: string) => counts.set(k, (counts.get(k) ?? 0) + 1)
  const d = 2
  for (let x = 0; x < info.width; x++) {
    for (const y of [0, 1, info.height - d, info.height - 1]) bump(px(x, y))
  }
  for (let y = d; y < info.height - d; y++) {
    for (const x of [0, 1, info.width - d, info.width - 1]) bump(px(x, y))
  }
  // 众数（Counter.most_common 同口径：计数取最大，并列取先出现）
  let mode = ""
  let modeN = 0
  for (const [k, n] of counts) {
    if (n > modeN) {
      mode = k
      modeN = n
    }
  }
  const modeC = mode.split(",").map(Number)
  if (modeC.some((a, i) => Math.abs(a - want[i]!) > 8)) {
    problems.push(
      `${basename(png)}: 外圈众数色 (${modeC.join(", ")}) ≠ 契约底色 ${s.bg}（通道差 >8）`,
    )
  }
  return problems
}

// ── CLI 适配层（commands.ts 路由叶子；业务在上面，这里只接线） ───────────────

/** commands.ts 路由入口：`feuille cover make <key> <html> <out.png>`。
 *
 * key 从 SPECS 注册表现取（不猜）；html 是**整页封面 HTML 文件路径**
 * （内容，不是 URL——渲染在 textlayer.edgeScreenshot）。
 */
export async function mainMake(argv: string[]): Promise<number> {
  if (resolveBrowser() === null) {
    throw new FeuilleError("缺 Chromium 内核浏览器（resolver 未找到；文字渲染走 Edge headless）")
  }
  const [key, htmlPath, outPng] = argv
  if (!key || !htmlPath || !outPng) {
    throw new FeuilleError(
      `用法：feuille cover make <key> <html> <out.png>（规格键：${Object.keys(SPECS).join(" / ")}）`,
    )
  }
  const out = await make(key, readFileSync(htmlPath, "utf8"), outPng)
  process.stdout.write(`wrote ${out}\n`)
  return 0
}

/** commands.ts 路由入口：`feuille cover check <png> <key>`（问题列表空 = 通过）。 */
export async function mainCheck(argv: string[]): Promise<number> {
  const [png, key] = argv
  if (!png || !key) {
    throw new FeuilleError(
      `用法：feuille cover check <png> <key>（规格键：${Object.keys(SPECS).join(" / ")}）`,
    )
  }
  const problems = await check(png, key)
  for (const p of problems) process.stdout.write(`  - ${p}\n`)
  process.stdout.write(problems.length ? `FAIL：${problems.length} 项问题\n` : "OK\n")
  return problems.length ? 1 : 0
}
