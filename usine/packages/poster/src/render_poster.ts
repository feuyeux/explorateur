// render_poster.ts — Headless Chromium 把海报 HTML 渲成 PNG，全确定性。
// （promoted from skills/one-page-poster/scripts/render_poster.sh，P5-7e 归流）
//
// Usage: poster render <in.html[?query]> <out.png> [css_width] [css_height] [scale]
//   query 后缀照单全收（如 cover_src.html?fmt=P 竖版封面变体）——少了 ?fmt=P
//   时 boot 脚本会静默按**横版**几何渲染，下游每道机检全部失准。
//
// 浏览器解析走 @feuille/core platform 的这一个事实源，不写死名字。
// 优先级：$CHROME_BIN > platform.browserPath()。
//
// 隔离：每次运行用**全新的临时 --user-data-dir**。不带它时 Chromium 落到默认
// profile，桌面浏览器若已开着，singleton 锁会把启动移交给现有进程、退出 0 且
// 不写截图。实测 macOS + Edge 上挂住不退的是**持久化** profile；空目录规避了
// 它。就算在别的环境再挂，timeout 兜底让它响亮地失败。
// 另：`--force-device-scale-factor` 保留本入口自己的 $S（海报要 2x 出图），
// textlayer 固定 1 是因为它要 png 尺寸严格等于窗口尺寸。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { platform } from '@feuille/core'

const hasTimeout = (): boolean => {
  // Windows System32 也有个叫 timeout 的东西（延时命令），不能只看退出码——
  // 必须确认是 GNU coreutils 的 timeout 才拿它做 120s 兜底。
  const r = spawnSync('timeout', ['--version'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
  return r.status === 0 && /GNU coreutils/.test(r.stdout ?? '')
}

export function main(argv: string[]): number {
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

  const browser = process.env['CHROME_BIN'] || platform.browserPath() || ''
  if (!browser) {
    console.error('找不到可用的 Chromium 系浏览器。')
    console.error('装 Chrome 或 Edge，或设 CHROME_BIN 指向浏览器可执行文件。')
    return 1
  }

  const profile = mkdtempSync(join(tmpdir(), 'poster-render-'))
  try {
    const args = [
      '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
      `--user-data-dir=${profile}`, '--virtual-time-budget=10000',
      `--window-size=${w},${h}`, `--force-device-scale-factor=${s}`,
      `--screenshot=${out}`, pathToFileURL(resolve(inArg)).href + qs,
    ]
    // 有 GNU coreutils 的 timeout 就包一层 120s 兜底；否则裸跑
    // （macOS 默认无 timeout，Windows System32 的同名延时命令不算数）。
    const r = hasTimeout()
      ? spawnSync('timeout', ['120', browser, ...args], { stdio: 'inherit' })
      : spawnSync(browser, args, { stdio: 'inherit' })
    if (r.status !== 0) return r.status ?? 1 // bash set -e：浏览器非零码原样透传
    if (!existsSync(out)) {
      console.error(`浏览器退出 0 但没有写出 ${out}——大概率被已开着的桌面浏览器抢占（singleton 移交）。`)
      console.error('关掉桌面浏览器后重试。')
      return 1
    }
    console.log(`wrote ${out} (${Number(w) * Number(s)}x${Number(h) * Number(s)})`)
    return 0
  } finally {
    rmSync(profile, { recursive: true, force: true })
  }
}
