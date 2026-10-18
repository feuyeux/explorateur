// platform.test.ts — 跨平台解析的反向验证（verify_platform.py 的 vitest 对应移植）
//
// **它要证的那句话**：「feuille 在 Windows / macOS / Linux 上都能跑。」
// 这句话在有产物的机器上看起来永远是绿的，全靠记忆——所以把「会不会退化成
// 单平台」变成断言。四条判据各对应一种真实退化：
// 1. 代码里不再有写死的可执行文件路径（候选表之外）
// 2. 浏览器解析落到真实存在的文件上；FEUILLE_BROWSER 指到不存在 → null（不静默换人）
// 3. 候选全不命中 → null（拿不到就说拿不到，不编造路径）
// 4. 候选表覆盖三套系统
// 第 0 条纪律是好数据放行：恒判 FAIL 的检查毫无价值。
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import * as pt from '../src/platform.js'

// 写死的可执行文件路径：Windows 盘符，或 macOS .app 内部路径（与 Python 侧同口径）。
// 只查代码，不查文档。
const WIN_EXE = /[A-Za-z]:\\?[A-Za-z0-9_ .\\-]+\.(?:exe|cmd|bat)\b/gi
const MAC_APP = /\/Applications\/[\w .]+\.app\//g

// 唯一合法例外：候选表自己（它出现系统路径是职责所在；全仓禁止会把候选表
// 拆散成多处，那正是「第二个事实源」的由来）。
const ALLOWED = ['packages/core/src/platform.ts']

function walkTs(dir: string): string[] {
  const out: string[] = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name)
    if (e.isDirectory()) out.push(...walkTs(p))
    else if (e.isFile() && e.name.endsWith('.ts')) out.push(p)
  }
  return out
}

describe('跨平台：外部件解析（浏览器 / ffmpeg / ffprobe / magick）', () => {
  it('好数据放行：本机在装的件解析得到', () => {
    for (const name of ['ffmpeg', 'ffprobe']) {
      const installed = pt.which(name) !== null
      const got = name === 'ffmpeg' ? pt.ffmpeg() : pt.ffprobe()
      if (installed) expect(got).not.toBeNull()
      // 未装不算失败；缺件由 missing() 如实报
    }
  })

  it('候选表之外，packages/*/src 里没有写死的可执行路径', () => {
    const packagesDir = fileURLToPath(new URL('../../', import.meta.url))
    const hits: string[] = []
    let nFiles = 0
    for (const p of walkTs(packagesDir).sort()) {
      // 归一化为仓库相对路径再比对白名单。相对 packages/ 的父目录算，
      // 与 checkout 目录名无关：RSI 演进客体的检出叫 evolution_project。
      const rel = relative(dirname(packagesDir), p)
      if (ALLOWED.includes(rel)) continue
      nFiles += 1
      const text = readFileSync(p, 'utf8')
      for (const m of text.matchAll(WIN_EXE)) hits.push(`${rel}: ${m[0]}`)
      for (const m of text.matchAll(MAC_APP)) hits.push(`${rel}: ${m[0]}`)
      WIN_EXE.lastIndex = 0
      MAC_APP.lastIndex = 0
    }
    expect(hits, `扫 ${nFiles} 个文件，白名单 ${ALLOWED.join(',')}；违例：${hits.slice(0, 3).join('　')}`).toEqual([])
  })

  it('浏览器解析到真实存在且可执行的文件', () => {
    const b = pt.browser()
    if (b) {
      const st = statSync(b[1])
      expect(st.isFile()).toBe(true)
      expect(st.mode & 0o111).not.toBe(0)
    }
    // 本机找不到 Chromium 只是渲不了，不算失败；解析逻辑由下面几条证明
  })

  it('FEUILLE_BROWSER 指向不存在的文件 → 返回 null（不静默换浏览器）', () => {
    const old = process.env['FEUILLE_BROWSER']
    process.env['FEUILLE_BROWSER'] = '/nonexistent/definitely-not-a-browser'
    try {
      expect(pt.browser()).toBeNull()
    } finally {
      if (old === undefined) delete process.env['FEUILLE_BROWSER']
      else process.env['FEUILLE_BROWSER'] = old
    }
  })

  it('browser(only="chrome") 不会落到别家内核', () => {
    // FEUILLE_BROWSER 按设计「优先于一切」（含 only=；RSI guest 用它把
    // 启动导到 HOME 还原 shim）。本条纪律验证的是候选表自身的内核归属，
    // 须在无覆盖状态下判。
    const old = process.env['FEUILLE_BROWSER']
    delete process.env['FEUILLE_BROWSER']
    try {
      const cb = pt.browser('chrome')
      expect(cb === null || cb[0] === 'chrome').toBe(true)
    } finally {
      if (old !== undefined) process.env['FEUILLE_BROWSER'] = old
    }
  })

  it('候选全不命中 → 返回 None（拿不到就说拿不到，不编造路径）', () => {
    expect(pt.firstExisting(['/nonexistent/a', 'definitely-not-a-command-xyz'])).toBeNull()
    expect(pt.firstExisting(['/nonexistent/magick', 'definitely-not-magick-xyz'])).toBeNull()
  })

  it('浏览器候选表覆盖 Windows / macOS / Linux', () => {
    const cands = pt.BROWSERS.map(([, c]) => c)
    const hasWin = cands.some((c) => /^[A-Za-z]:/.test(c))
    const hasMac = cands.some((c) => c.startsWith('/Applications/'))
    const hasNix = cands.some((c) => c.includes('/usr/bin/') || c.includes('/opt/'))
    expect(hasWin && hasMac && hasNix).toBe(true)
  })

  it('magick 候选表不含 convert（Windows 系统自带 convert.exe 是文件系统工具）', () => {
    expect(pt.MAGICK_CANDIDATES.every((c) => !c.includes('convert'))).toBe(true)
  })

  it('expandvars / which 的最小移植口径', () => {
    // which 带路径分隔符 → 直接按文件解析（与 shutil.which 同语义）
    expect(pt.which('/nonexistent/definitely/not/a/file')).toBeNull()
    const ffmpeg = pt.ffmpeg()
    if (ffmpeg) {
      expect(existsSync(ffmpeg)).toBe(true)
      expect(pt.which(join(ffmpeg))).toBe(ffmpeg) // 绝对路径回环
    }
  })

  it('missing() 如实报缺件（不装样子）', () => {
    const m = pt.missing()
    expect(Array.isArray(m)).toBe(true)
    // 有 ffmpeg 的机器上 missing 不应把 ffmpeg 报成缺
    if (pt.ffmpeg()) expect(m.some((x) => x === 'ffmpeg')).toBe(false)
  })

  it('systemName / machineArch 口径对齐 Python platform 模块', () => {
    expect(pt.systemName()).toBe(process.platform === 'darwin' ? 'Darwin'
      : process.platform === 'win32' ? 'Windows'
        : process.platform === 'linux' ? 'Linux' : process.platform)
    if (process.platform === 'darwin' && process.arch === 'arm64') expect(pt.machineArch()).toBe('arm64')
    if (process.arch === 'x64') expect(pt.machineArch()).toBe('x86_64')
  })
})
