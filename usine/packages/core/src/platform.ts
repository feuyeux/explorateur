// platform.ts — 外部可执行文件（浏览器 / ffmpeg / ffprobe / magick）的跨平台解析，
// 全仓唯一事实源（platform.py 的 TS 移植）。
//
// **它防的两种静默故障**（两次真实事故换来的）：
// 1. 写死路径在别的系统上直接 file-not-found——而浏览器明明装了；
// 2. 更阴的：账本类工具读到 null 按「不可信 = 保守判过期」处理——每个产物
//    永久判过期、每次全量重做，且没有任何东西报错。
//
// 移植要点：
// - 候选表**顺序即优先级**：edge 在 chrome 前（像素基线同源）；`FEUILLE_BROWSER`
//   显式指定找不到 = 配置错误返回 null，不静默换人。
// - magick 不收 `convert` 兜底（Windows 的 convert.exe 是文件系统转换工具）。
// - 探测不到一律返回 null，绝不编造路径；调用方拿到 null 必须显式失败（missing()）。
// - Python os.path.expanduser/expandvars → Node 无内建等价物，这里实现最小版：
//   `~` 前缀展开 + `$VAR`/`${VAR}`/`%VAR%`（Windows 候选用 %USERNAME%）。
// - shutil.which → PATH 逐目录扫描（Windows 加 PATHEXT 扩展名补全）。
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { basename, delimiter, join, resolve } from 'node:path'
import { homedir, tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'

import { FeuilleError } from './errors.js'

// ---------------------------------------------------------------- 浏览器候选
// (内核名, 路径或命令名)。**顺序即优先级**：edge 在 chrome 前（像素基线同源）。
export const BROWSERS: readonly (readonly [string, string])[] = [
  // ---- Windows（Edge/Chrome 默认装在 per-user %LOCALAPPDATA%，机器级 PF 只是次选）----
  ['edge', 'C:\\Users\\%USERNAME%\\AppData\\Local\\Microsoft\\Edge\\Application\\msedge.exe'],
  ['edge', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'],
  ['edge', 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'],
  ['edge', 'msedge'],
  // ---- macOS（.app 内部可执行名 = 产品名）----
  ['edge', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'],
  ['edge', '~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'],
  ['edge', 'microsoft-edge'],
  // ---- Linux ----
  ['edge', '/usr/bin/microsoft-edge'],
  ['edge', '/opt/microsoft/msedge/msedge'],
  ['edge', 'microsoft-edge-stable'],
  // ---- Chromium 同源的 Chrome：Edge 没装时的落点（发布器也用它 + 持久 profile）----
  ['chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'],
  ['chrome', '~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'],
  ['chrome', 'google-chrome'],
  ['chrome', 'google-chrome-stable'],
  ['chrome', '/usr/bin/google-chrome'],
  ['chrome', '/opt/google/chrome/chrome'],
  ['chrome', 'C:\\Users\\%USERNAME%\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe'],
  ['chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'],
  ['chrome', 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'],
  ['chrome', 'chrome'],
  // ---- 最后的兜底 ----
  ['chromium', 'chromium'],
  ['chromium', 'chromium-browser'],
  ['chromium', '/Applications/Chromium.app/Contents/MacOS/Chromium'],
]

// ffmpeg / ffprobe / magick：先 PATH，再各平台常见安装位（Windows 补 scoop shim）。
export const FFMPEG_CANDIDATES: readonly string[] = [
  'ffmpeg', '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg',
  'C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe', 'C:\\Users\\%USERNAME%\\scoop\\shims\\ffmpeg.exe',
]
export const FFPROBE_CANDIDATES: readonly string[] = [
  'ffprobe', '/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe', '/usr/bin/ffprobe',
  'C:\\ProgramData\\chocolatey\\bin\\ffprobe.exe', 'C:\\Users\\%USERNAME%\\scoop\\shims\\ffprobe.exe',
]
export const MAGICK_CANDIDATES: readonly string[] = [
  'magick', '/opt/homebrew/bin/magick', '/usr/local/bin/magick', '/usr/bin/magick',
  'C:\\ProgramData\\chocolatey\\bin\\magick.exe',
]

/** `~` 前缀展开（os.path.expanduser 的最小版）。 */
function expanduser(p: string): string {
  if (p === '~') return homedir()
  if (p.startsWith('~/') || p.startsWith('~\\')) return join(homedir(), p.slice(2))
  return p
}

/** `$VAR` / `${VAR}` / `%VAR%` 展开（os.path.expandvars 的最小版；未定义变量原样保留）。 */
function expandvars(p: string): string {
  return p
    .replace(/\$\{(\w+)\}/g, (_, k) => process.env[k] ?? `\${${k as string}}`)
    .replace(/\$(\w+)/g, (_, k) => process.env[k] ?? `$${k as string}`)
    .replace(/%(\w+)%/g, (_, k) => process.env[k] ?? `%${k as string}%`)
}

/** shutil.which 的最小移植：PATH 逐目录扫描 + Windows PATHEXT 补全。 */
export function which(cmd: string): string | null {
  if (cmd.includes('/') || cmd.includes('\\')) {
    const abs = resolve(expandvars(expanduser(cmd)))
    return existsSync(abs) ? abs : null
  }
  const pathEnv = process.env.PATH ?? ''
  const exts = process.platform === 'win32'
    ? (process.env.PATHEXT ?? '.EXE;.CMD;.BAT;.COM').split(';')
    : ['']
  for (const dir of pathEnv.split(delimiter)) {
    if (!dir) continue
    const base = resolve(expandvars(expanduser(dir)), cmd)
    for (const ext of exts) {
      const cand = base + ext.toLowerCase()
      if (existsSync(cand)) return cand
    }
  }
  return null
}

/** 候选列表 → 第一个真实存在的可执行文件（或 null）。**不编造路径。** */
export function firstExisting(candidates: readonly string[]): string | null {
  for (const cand of candidates) {
    const p = resolve(expandvars(expanduser(cand)))
    if (isFile(p)) return p
    const found = which(cand)
    if (found) return found
  }
  return null
}

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile()
  } catch {
    return false
  }
}

/** `(内核名, 绝对路径)` 或 null。FEUILLE_BROWSER 优先于一切（找不到 = null，不静默换人）。 */
export function browser(only?: string): [string, string] | null {
  const override = process.env['FEUILLE_BROWSER']
  if (override) {
    const p = resolve(expanduser(override))
    if (isFile(p)) return ['custom', p]
    const found = which(override)
    if (found) return ['custom', found]
    return null
  }
  for (const [name, cand] of BROWSERS) {
    if (only && name !== only) continue
    const p = resolve(expandvars(expanduser(cand)))
    if (isFile(p)) return [name, p]
    const found = which(cand)
    if (found) return [name, found]
  }
  return null
}

export function browserPath(only?: string): string | null {
  return browser(only)?.[1] ?? null
}

// ---------------------------------------------------------------- 视口亏空
/**
 * `--window-size=W,H` 给的是**窗口**尺寸，Chromium 的实际**视口**往往更矮：
 * 2026-10-22 实测本机 Chrome 155，`innerHeight = 窗口高 − 95` CSS px。
 * 差值随浏览器版本/机器变，**写死常数迟早过期**——过期那天不会报错，
 * 只会把画布底部一整条渲成底色（画面看起来「只是矮了一点」）。
 *
 * 2026-10-20 Chrome 自动升级到 155 之后，foodnames 12 期全卡在
 * `poster verify-colors` 的「grid not found」：海报网格的底边正好落在
 * 被切掉的 95px 里。视频帧没中招（走 textlayer 那条路，它早有补偿）。
 *
 * **这里探一次、之后按浏览器路径 memoize**：探针页只报 `innerHeight` 与
 * `document.documentElement.clientWidth`（后者是**排版宽度**，不含滚动条）。
 *
 * 为什么宽度那一项常常是 0：`innerWidth` 含滚动条、`clientWidth` 不含，
 * 而 `--hide-scrollbars` 让排版宽度等于窗口宽——所以补偿宽度反而会把
 * 居中内容整体推开（实测：窗口 +16 → 海报右移 8px，网格竖线从 101 变 117）。
 * **只补高度**是稳的那条。
 */
export interface ViewportDeficit {
  /** 要额外加到窗口宽度上的 px（排版宽度比窗口窄多少）。 */
  width: number
  /** 要额外加到窗口高度上的 px（视口比窗口矮多少）。 */
  height: number
}

const viewportDeficitCache = new Map<string, ViewportDeficit>()

/** 探针窗口尺寸：够大够小都试不出差别（实测 4 种尺寸的亏空完全相同）。 */
const PROBE_W = 1080
const PROBE_H = 300

export function viewportDeficit(browser?: string | null): ViewportDeficit {
  const b = browser ?? browserPath()
  if (!b) return { width: 0, height: 0 }
  const cached = viewportDeficitCache.get(b)
  if (cached) return cached
  const deficit: ViewportDeficit = { width: 0, height: 0 }
  const dir = join(tmpdir(), `feuille-vp-probe-${process.pid}`)
  const probe = join(dir, 'probe.html')
  try {
    mkdirSync(dir, { recursive: true })
    writeFileSync(
      probe,
      `<!doctype html><meta charset="utf-8"><title>VP</title>`
      + `<script>document.title='VP '+window.innerHeight+'x'+document.documentElement.clientWidth</script>`,
      'utf8',
    )
    const dom = execFileSync(
      b,
      ['--headless=new', '--disable-gpu', ...HEADLESS_FLAGS,
        `--window-size=${PROBE_W},${PROBE_H}`, '--virtual-time-budget=800', '--dump-dom',
        pathToFileURL(probe).href],
      { timeout: 60_000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    )
    const m = /<title>VP (\d+)x(\d+)<\/title>/.exec(dom)
    if (m) {
      deficit.height = Math.max(0, PROBE_H - Number.parseInt(m[1]!, 10))
      deficit.width = Math.max(0, PROBE_W - Number.parseInt(m[2]!, 10))
    }
  } catch {
    // 探不到就按「没有亏空」处理：渲染照常跑，最坏是底部少一条，
    // **不许在这里抛**——浏览器探测失败不该把整条产线带崩。
    deficit.width = 0
    deficit.height = 0
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
  viewportDeficitCache.set(b, deficit)
  return deficit
}

/** 测试用：清掉亏空缓存（换浏览器版本后要重新探）。 */
export function resetViewportDeficitCacheForTests(): void {
  viewportDeficitCache.clear()
}

/**
 * headless 渲染的公共旗标（每个启动点必须带上）。
 * --use-mock-keychain / --password-store=basic：headless 渲染绝不碰用户
 * 钥匙串。真实钥匙串在隔离环境（如 RSI guest 把 HOME 钉到沙箱盘）里会
 * 首启挂起并拖死关停——2026-10-18 macOS 实测：HOME 非真实家目录时
 * Edge headless 稳定以 2 退出（teardown watchdog），带上这对旗标即 0。
 * 两者都不影响光栅化，像素基线不受牵动。
 */
export const HEADLESS_FLAGS: readonly string[] = [
  '--use-mock-keychain', '--password-store=basic',
]

export function ffmpeg(): string | null {
  return firstExisting(FFMPEG_CANDIDATES)
}

export function ffprobe(): string | null {
  return firstExisting(FFPROBE_CANDIDATES)
}

/** ImageMagick 7（裁切安全拼图 / 对照图拼版用）。不收 `convert` 兜底，见模块头。 */
export function magick(): string | null {
  return firstExisting(MAGICK_CANDIDATES)
}

/**
 * 解析成功就返回路径，解析不到就**显式抛出**（带下一步）——调用方只想要路径、
 * 不想自己写「拿到 null 该怎么办」时用它。
 *
 * 为什么这一条要收口在这里：`ffmpegBin()` 这种「取 resolver 结果 + 拿不到就抛」
 * 的五行函数曾在本仓被抄了六份（bgm / karaoke ×2 / poetry ×2 / storyteller），
 * 六份的报错文案各不相同，而行为一模一样。缺件是所有产线共同的失败模式，
 * **它该只有一种说法**——否则改一句提示要改六个文件，改漏一个就有一处说旧话。
 *
 * `browser()` 不走这条路：它在无浏览器主机上是**合法状态**（渲染用例转 SKIP），
 * 拿不到就该返回 null 让调用方决定，见 `missing()` 与 textlayer。
 */
export function requireTool(tool: string | null, what: string): string {
  if (tool === null) {
    throw new FeuilleError(
      `缺 ${what}：请安装后重跑（@feuille/core platform 解析；外部可执行文件一律不写死路径，`
      + '缺件清单见 platform.missing()）')
  }
  return tool
}

/** 缺哪些外部件——供报错与体检如实说「缺什么」。 */
export function missing(): string[] {
  const out: string[] = []
  if (!browser()) out.push('浏览器（Edge / Chrome / Chromium 任一，或设 FEUILLE_BROWSER）')
  if (!ffmpeg()) out.push('ffmpeg')
  if (!ffprobe()) out.push('ffprobe')
  if (!magick()) out.push('magick（ImageMagick 7，裁切安全拼图用）')
  return out
}

/** platform.system()/machine() 的口径对齐（Python：'Darwin' / 'arm64'）。 */
export function systemName(): string {
  switch (process.platform) {
    case 'darwin': return 'Darwin'
    case 'win32': return 'Windows'
    case 'linux': return 'Linux'
    default: return process.platform
  }
}

export function machineArch(): string {
  // Python platform.machine() 在 Apple Silicon 上给 'arm64'；x64 Linux 给 'x86_64'
  const arch = process.arch
  if (arch === 'arm64' && process.platform === 'darwin') return 'arm64'
  if (arch === 'x64') return 'x86_64'
  return arch
}

/** 本机解析结果——给体检与排障，一眼说清「用的是哪一件」。 */
export function describe(): Record<string, string | string[] | null> {
  const b = browser()
  return {
    platform: `${systemName()} ${machineArch()}`,
    browser: b ? `${b[0]}: ${b[1]}` : null,
    ffmpeg: ffmpeg(),
    ffprobe: ffprobe(),
    magick: magick(),
    missing: missing(),
  }
}
