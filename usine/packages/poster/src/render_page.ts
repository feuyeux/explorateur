// render_page.ts — Windows 渲染/倒 DOM 助手（Edge headless=new）。
// （promoted from skills/one-page-poster/scripts/render_page.py，P5-7e 归流）
//
// 与 render_poster（macOS/Linux）成对；同样两件活，外加 Windows 上探明的
// 窗框开销补偿：
//
//   --window-size 给的是**窗口**尺寸，实际**视口**更矮（本机 Chrome 155 实测
//   矮 95 CSS px）。**这个差值随浏览器版本变，写死的常数会过期**——过期那天
//   不报错，只会把画布底部一整条渲成底色（画面看起来「只是矮了一点」）。
//   2026-10-20 Chrome 自动升级到 155 之后，foodnames 12 期全卡在
//   `poster verify-colors` 的「grid not found」：海报网格的底边正好落在被
//   切掉的那 95px 里。
//
//   现在改成**探出来的**（@feuille/core platform.viewportDeficit：渲一页只报
//   innerHeight/clientWidth 的探针页，量出差值，按浏览器路径 memoize），
//   窗口按差值放大、渲完把 PNG 裁回 w*scale × h*scale（内容锚在设备 (0,0)）。
//   宽度那一项常常是 0（`--hide-scrollbars` 让排版宽度等于窗口宽），补了反而
//   会把居中内容整体推开——**只补高度**是稳的那条。
//
// 另两个已处理的 Windows 坑：
//   - --screenshot=<绝对路径> 才写文件：相对路径静默失败（退出 0、无文件）；
//   - 任何 JS rect 探测（fit_diag/verify）必须挂在 document.fonts.ready 门后
//     （+ 小 setTimeout），否则量到的是 fallback 字体度量（探针字体解码竞速）；
//   - dump 走同一套补偿：传页面尺寸 + 实测亏空——否则 DOM 的视口比目标画布
//     矮一截，?verify=1 的每个词框都错位。
//
// Usage（在海报项目目录里跑）：
//   feuille poster page-dump dump <file.html> <out.txt> [w] [h]
//   feuille poster render-page render <file.html> <query|-> <out.png> <w> <h> <scale>
// query 是 "?" 后面的部分（如 "fmt=T"）；无 query 传 "-"。
import { spawnSync } from 'node:child_process'
import { existsSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import sharp from 'sharp'
import { FeuilleError, platform } from '@feuille/core'

function chrome(): string {
  const p = platform.browserPath()
  if (p === null) {
    // Python 直接把 None 塞进 subprocess 崩掉——保持「响亮失败」不静默兜底
    throw new FeuilleError('找不到 Chromium 系浏览器：请装 Chrome / Edge，或设 $CHROME_BIN')
  }
  return p
}

/** 先把 ?query 从路径上拆下来再转 file:// URL（as_uri 会把 ? 百分号转义）。 */
function fileUrl(p: string): string {
  const qi = p.indexOf('?')
  const head = qi >= 0 ? p.slice(0, qi) : p
  const q = qi >= 0 ? p.slice(qi + 1) : ''
  return pathToFileURL(resolve(head)).href + (q ? `?${q}` : '')
}

function baseCmd(w: string, h: string): string[] {
  return [chrome(), '--headless=new', '--disable-gpu',
    ...platform.HEADLESS_FLAGS, '--no-sandbox',
    '--virtual-time-budget=10000', `--window-size=${w},${h}`,
    '--force-device-scale-factor=1', '--hide-scrollbars']
}

function dumpDom(target: string, out: string, w = '1080', h = '1440'): number {
  // dump 的视口必须等于目标画布，否则页内量到的 rect 全部错位——
  // 窗口按实测亏空放大，让视口正好落在 w×h。
  const deficit = platform.viewportDeficit(chrome())
  const cmd = [...baseCmd(String(Number(w) + deficit.width), String(Number(h) + deficit.height)),
    '--dump-dom', fileUrl(target)]
  const r = spawnSync(cmd[0]!, cmd.slice(1), { timeout: 180000, encoding: 'buffer', maxBuffer: 64 * 1024 * 1024 })
  if (r.error) throw r.error // Python TimeoutExpired 同为响亮崩溃
  writeFileSync(out, r.stdout)
  console.log(`dumped ${out} (${r.stdout.length} bytes)`)
  return 0
}

async function render(target: string, query: string, out: string, w: string, h: string, scale: string): Promise<number> {
  // 窗口按**实测**视口亏空放大（探针在 core/platform.ts），渲完裁回
  // w*scale x h*scale（内容锚在设备 (0,0)，底色带只出现在右/下）
  const url = fileUrl(target) + (query ? `?${query}` : '')
  const outAbs = resolve(out) // Windows + Edge：相对路径 --screenshot= 静默失败
  const deficit = platform.viewportDeficit(chrome())
  const cmd = [...baseCmd(String(Number(w) + deficit.width), String(Number(h) + deficit.height)),
    `--force-device-scale-factor=${scale}`, `--screenshot=${outAbs}`, url]
  const r = spawnSync(cmd[0]!, cmd.slice(1), { timeout: 180000, stdio: 'ignore', maxBuffer: 64 * 1024 * 1024 })
  if (r.error) throw r.error
  if (!existsSync(out)) {
    console.error(`screenshot not written: ${out}`)
    return 1
  }
  const wantW = Number(w) * Number(scale)
  const wantH = Number(h) * Number(scale)
  const meta = await sharp(out).metadata()
  if (meta.width !== wantW || meta.height !== wantH) {
    if (meta.width! < wantW || meta.height! < wantH) {
      console.error(`render ${out} smaller than expected: (${meta.width}, ${meta.height}) < (${wantW}, ${wantH})`)
      return 1
    }
    const buf = await sharp(out).extract({ left: 0, top: 0, width: wantW, height: wantH }).png().toBuffer()
    writeFileSync(out, buf)
  }
  console.log(`wrote ${out} (${wantW}x${wantH})`)
  return 0
}

export async function main(argv: string[]): Promise<number> {
  if (argv[0] === 'dump') {
    return dumpDom(
      argv[1] ?? (() => { throw new FeuilleError('dump: 缺 file.html') })(),
      argv[2] ?? (() => { throw new FeuilleError('dump: 缺 out.txt') })(),
      argv[3] !== undefined ? argv[3]! : '1080',
      argv[4] !== undefined ? argv[4]! : '1440',
    )
  }
  if (argv[2] === undefined) throw new FeuilleError('render: 缺 query 参数（无 query 传 "-"）')
  const q = argv[2] === '-' || argv[2] === '' ? '' : argv[2]
  return render(argv[1]!, q, argv[3]!, argv[4]!, argv[5]!, argv[6]!)
}
