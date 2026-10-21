// render_poster.ts — Headless Chromium 把海报 HTML 渲成 PNG，全确定性。
// （promoted from skills/one-page-poster/scripts/render_poster.sh，P5-7e 归流）
//
// Usage: poster render <in.html[?query]> <out.png> [css_width] [css_height] [scale]
//   query 后缀照单全收（如 cover_src.html?fmt=P 竖版封面变体）——少了 ?fmt=P
//   时 boot 脚本会静默按**横版**几何渲染，下游每道机检全部失准。
//
// 浏览器解析走 @feuille/core platform 的这一个事实源，不写死名字。
// 优先级：$CHROME_BIN > platform.browserPath()（见 platform.browser()：解析不到
// 返回 null，绝不静默换人；调用方拿到 null 必须显式失败）。
//
// 隔离：**不带 --user-data-dir**（与 textlayer / karaoke / storyteller 四个同类
// 渲染口一致）。AGENTS.md 实测：macOS + Edge 上带 --user-data-dir 图能出但进程
// **永不退出**，整个 build 挂死。singleton 抢占由下面的 existsSync(out) 判据兜住，
// 挂死由 spawnSync 自带的 timeout 兜住——不依赖机器上有没有 GNU coreutils。
// 另：`--force-device-scale-factor` 保留本入口自己的 $S（海报要 2x 出图），
// textlayer 固定 1 是因为它要 png 尺寸严格等于窗口尺寸。
import { spawnSync } from 'node:child_process'
import { existsSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import sharp from 'sharp'
import { platform } from '@feuille/core'

/** 兜底超时（秒）。与 karaoke 同量级：够渲完一页，也短到挂死时能响亮地失败。 */
const RENDER_TIMEOUT_SECS = 180

export async function main(argv: string[]): Promise<number> {
  if (argv.length < 2) {
    console.error('usage: feuille poster render <in.html[?query]> <out.png> [css_width] [css_height] [scale]')
    return 2
  }
  let inArg = argv[0]!
  let qs = ''
  const qi = inArg.indexOf('?')
  if (qi >= 0) {
    qs = '?' + inArg.slice(qi + 1)
    inArg = inArg.slice(0, qi)
  }
  const out = argv[1]!
  const w = argv[2] !== undefined ? argv[2]! : '1240'
  const h = argv[3] !== undefined ? argv[3]! : '1754'
  const s = argv[4] !== undefined ? argv[4]! : '2'

  // $CHROME_BIN 与 FEUILLE_BROWSER 走同一条事实源：写进 FEUILLE_BROWSER 再解析，
  // 这样「解析不到 → null → 显式报缺」的重试契约不会被旁路成一个裸路径
  // （裸路径过期时只会抛 ENOENT，报不出「你设的 CHROME_BIN 不存在」）。
  const override = process.env['CHROME_BIN']
  if (override) process.env['FEUILLE_BROWSER'] = override
  const browser = platform.browserPath() ?? ''
  if (!browser) {
    console.error('找不到可用的 Chromium 系浏览器。')
    console.error(override
      ? `装 Chrome 或 Edge，或把 CHROME_BIN 改成一个真实存在的可执行文件（当前值：${override}）。`
      : '装 Chrome 或 Edge，或设 CHROME_BIN / FEUILLE_BROWSER 指向浏览器可执行文件。')
    return 1
  }

  // 视口亏空补偿：`--window-size` 给的是窗口尺寸，实际视口更矮（本机 Chrome 155
  // 实测矮 95 CSS px）。不补这一下，画布底部一整条不会被画上——海报网格的底边
  // 正好落在那儿，`poster verify-colors` 立刻报「grid not found」。
  //
  // 亏空是**探出来的**，不是写死的（浏览器自动升级就会变）。只补高度：宽度补了
  // 会把居中内容整体推开（实测海报网格竖线从 101 挪到 117）。
  // 补完把 PNG 裁回 w*scale × h*scale（内容锚在左上角）。
  const deficit = platform.viewportDeficit(browser)
  const wantW = Number(w) * Number(s)
  const wantH = Number(h) * Number(s)

  const args = [
    '--headless=new', '--disable-gpu', ...platform.HEADLESS_FLAGS,
    '--no-sandbox', '--hide-scrollbars',
    '--virtual-time-budget=10000',
    `--window-size=${Number(w) + deficit.width},${Number(h) + deficit.height}`,
    `--force-device-scale-factor=${s}`,
    // 相对路径的 --screenshot 在 Windows 上会**静默失败**（退出 0、文件不落盘，
    // Chrome 按自己的 cwd 解析路径）——统一给绝对路径。
    `--screenshot=${resolve(out)}`, pathToFileURL(resolve(inArg)).href + qs,
  ]
  // timeout 是 spawnSync 自己的选项：三系统都有，不依赖外部 GNU coreutils。
  const r = spawnSync(browser, args, {
    stdio: 'inherit',
    timeout: RENDER_TIMEOUT_SECS * 1000,
  })
  if (r.error) {
    console.error(`浏览器渲染失败：${r.error.message}`)
    return 1
  }
  if (r.status !== 0) return r.status ?? 1 // bash set -e：浏览器非零码原样透传
  if (!existsSync(out)) {
    console.error(`浏览器退出 0 但没有写出 ${out}——大概率被已开着的桌面浏览器抢占（singleton 移交）。`)
    console.error('关掉桌面浏览器后重试。')
    return 1
  }
  // 裁回画布尺寸（补亏空后 PNG 更大；内容锚在左上角，裁左上即可）。
  const meta = await sharp(out).metadata()
  if (meta.width !== wantW || meta.height !== wantH) {
    if (meta.width! < wantW || meta.height! < wantH) {
      console.error(`渲染结果比画布还小：(${meta.width}, ${meta.height}) < (${wantW}, ${wantH})——视口亏空补偿没兜住`)
      return 1
    }
    const buf = await sharp(out).extract({ left: 0, top: 0, width: wantW, height: wantH }).png().toBuffer()
    writeFileSync(out, buf)
  }
  console.log(`wrote ${out} (${wantW}x${wantH})`)
  return 0
}
