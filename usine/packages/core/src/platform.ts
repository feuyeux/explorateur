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
import { existsSync, statSync } from 'node:fs'
import { basename, delimiter, join, resolve } from 'node:path'
import { homedir } from 'node:os'

// ---------------------------------------------------------------- 浏览器候选
// (内核名, 路径或命令名)。**顺序即优先级**：edge 在 chrome 前（像素基线同源）。
export const BROWSERS: readonly (readonly [string, string])[] = [
  // ---- Windows ----
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
