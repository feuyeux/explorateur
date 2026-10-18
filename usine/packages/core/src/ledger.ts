// ledger.ts — 产物缓存账本（build/manifest.json）：谁新鲜、谁过期了、为什么
// （ledger.py 的 TS 移植）
//
// **它解决什么**：render 曾每次全渲，因为没有任何东西能回答「这批产物还是
// 不是当前代码/数据渲出来的」。有了账本：report() 立刻回答哪些产物过期、因为
// 什么（不用渲）；渲染可以跳过指纹未变的单元；改完代码知道该只重做哪几条线。
//
// **保守优先：宁可多渲，不可漏渲**。零像素漂移是硬判据：
// - 指纹只由「确实可能影响该产物」的模块 + 数据 + 工具链构成，粒度是**文件级**。
// - 指纹算不出来的输入（读不到的文件、未知工具链）→ 直接判过期，绝不假设没影响；
// - 产物文件本身不存在 → 无论指纹是否匹配一律过期。
//
// 移植口径说明：
// - `_digest` 的哈希构造**与 Python 逐字节同构**（v2 前缀 + `|label:sha` 逐段），
//   金样本批次 2 有逐字节 parity 门禁（migration/golden/ledger.json）。
// - 工具链字段随运行时**换血**：python/pillow → node/sharp（sharp 指纹含 vips
//   版本——vips 才是 TS 侧栅格化的真相源）。跨语言指纹值不可比是**设计内**：
//   迁移切换后全部条目判一次过期（保守重渲一遍），不假装两套指纹能对上。
// - **性能修复直接内置**（Python 侧已知瓶颈）：toolchain() 每次指纹计算都要
//   spawn 一次 `ffmpeg -version`——这里 memoize 进程内缓存（浏览器 size+mtime
//   与 ffmpeg 版本在一次进程内不会变），测试用 resetToolchainCacheForTests()。
//
// 三条守门规则（内嵌在实现里）：
// 1. 账本不把自己算进指纹。改 _digest / fingerprint 算法必须升 VERSION。
// 2. 账本键必须能区分产物身份（`kind:unit`）。
// 3. statusOf 对带 extra 的条目按条目里记录的那份复算（账本自描述）。
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'

import { browser, ffmpeg as resolveFfmpeg } from './platform.js'

// 账本 schema 版本。**键的格式是 schema 的一部分**：v2 起 `scene:<unit>` 由
// 使用方保证唯一。版本不匹配 → 整本作废。（沿用 v2：键格式与算法未变。）
export const VERSION = 2

export interface Toolchain {
  node: string | null
  sharp: string | null
  browser: string | null
  ffmpeg: string | null
}

export interface LedgerEntry {
  kind: string
  unit: string
  fingerprint: string | null
  extra: string[]
  artifacts: string[]
  toolchain: Toolchain
  builtAt: string
}

export interface LedgerDoc {
  version: number
  updatedAt: string | null
  entries: Record<string, LedgerEntry>
}

// 已注册的产物线：kind -> { modules（包内文件名）, data（相对 root；"@" 开头 = glob）。
const LINES = new Map<string, { modules: string[]; data: string[] }>()

// 包内基准目录：modules 的文件名相对这里（与 Python _PACKAGE_DIR 同语义）
const PACKAGE_DIR = dirname(fileURLToPath(import.meta.url))

export function registerLine(kind: string, modules: string[], data: string[]): void {
  LINES.set(kind, { modules, data })
}

// ---------------------------------------------------------------- 工具链（memoize）

let toolchainCache: Toolchain | null = null

// 测试缝：Python 侧反向验证用 monkeypatch ledger.toolchain 模拟「工具链读不到」；
// ESM 导出绑定不能被外部改写，这里给显式覆盖入口（仅测试用）。
let toolchainOverride: Toolchain | null = null

export function overrideToolchainForTests(tc: Toolchain | null): void {
  toolchainOverride = tc
  toolchainCache = null
}

export function resetToolchainCacheForTests(): void {
  toolchainCache = null
}

export function toolchain(): Toolchain {
  if (toolchainOverride) return toolchainOverride
  if (toolchainCache) return toolchainCache
  const b = browser()
  let browserId: string | null = null
  if (b) {
    try {
      const st = statSync(b[1]!)
      browserId = `${b[0]}:${st.size}-${Math.floor(st.mtimeMs / 1000)}`
    } catch {
      browserId = null
    }
  }
  const ff = resolveFfmpeg()
  const versions = (sharp as unknown as { versions?: Record<string, string> }).versions
  const sharpId = versions?.sharp && versions?.vips ? `${versions.sharp}/vips-${versions.vips}` : null
  toolchainCache = {
    node: process.version,
    // vips 版本入指纹：sharp 的预编译二进制里 vips 才是栅格化真相源
    sharp: sharpId,
    browser: browserId,
    ffmpeg: ff ? runFirstLine([ff, '-version']) : null,
  }
  return toolchainCache
}

function runFirstLine(cmd: string[]): string | null {
  try {
    const out = execFileSync(cmd[0]!, cmd.slice(1), { encoding: 'utf8', timeout: 20_000 })
    const first = out.split('\n')[0]?.trim()
    return first || null
  } catch {
    return null
  }
}

// ---------------------------------------------------------------- 指纹

export function sha256File(path: string): string {
  const h = createHash('sha256')
  h.update(readFileSync(path))
  return h.digest('hex')
}

/** (标签, 路径) 列表 → 指纹。**任何一项读不到就返回 null（= 判过期）**。 */
export function digest(parts: readonly (readonly [string, string])[]): string | null {
  const h = createHash('sha256')
  h.update(`v${VERSION}`)
  for (const [label, path] of parts) {
    if (!isFile(path)) return null
    h.update(`|${label}:${sha256File(path)}`)
  }
  return h.digest('hex').slice(0, 16)
}

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile()
  } catch {
    return false
  }
}

/** 该产物线的全部输入（标签, 路径）。未注册的线返回 null（= 指纹算不出）。 */
export function inputParts(root: string, kind: string): Array<[string, string]> | null {
  const line = LINES.get(kind)
  if (!line) return null
  const tc = toolchain()
  if (tc.sharp === null) return null // 成像库版本读不到 → 不敢假设没影响（同 Python 的 pillow 判空）
  const parts: Array<[string, string]> = []
  parts.push(...line.modules.map((n) => [`mod:${n}`, join(PACKAGE_DIR, n)] as [string, string]))
  for (const rel of line.data) {
    if (rel.startsWith('@')) {
      const matches = globFiles(root, rel.slice(1))
      if (matches.length === 0) return null // glob 一条都不中 → 不敢假设没影响
      parts.push(...matches.map((m) => [`data:${relative(root, m).split('\\').join('/')}`, m] as [string, string]))
    } else {
      parts.push([`data:${rel}`, join(root, rel)])
    }
  }
  return parts
}

/** 极简 glob：`langs/<*>/manifest.json` 形态（单层通配目录 + 固定文件名；够用即止）。注意：块注释里写不出「星号+斜杠」字面量（会提前关掉注释）——这正是上面写成 `<*>` 的原因。 */
function globFiles(root: string, pattern: string): string[] {
  const segs = pattern.split('/')
  const walk = (dir: string, i: number): string[] => {
    if (!isDir(dir)) return []
    if (i === segs.length - 1) {
      if (segs[i] === '*' || segs[i]!.includes('*')) {
        // 末段是文件名通配（账本线用不到，兜底：前缀匹配）
        try {
          return readdirFiles(dir).filter((f) => f.endsWith(segs[i]!.replace('*', '')))
        } catch {
          return []
        }
      }
      const p = join(dir, segs[i]!)
      return isFile(p) ? [p] : []
    }
    if (segs[i] === '*') {
      const out: string[] = []
      for (const sub of subDirs(dir)) out.push(...walk(sub, i + 1))
      return out
    }
    return walk(join(dir, segs[i]!), i + 1)
  }
  return walk(root, 0).sort()
}

function isDir(p: string): boolean {
  try {
    return statSync(p).isDirectory()
  } catch {
    return false
  }
}

function subDirs(dir: string): string[] {
  try {
    return readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => join(dir, e.name)).sort()
  } catch {
    return []
  }
}

function readdirFiles(dir: string): string[] {
  return readdirSync(dir).map((f) => join(dir, f))
}

/** 该单元产物的输入指纹。**任何一项读不到就返回 null = 判为过期**。 */
export function fingerprint(root: string, kind: string, unit: string, extra: readonly (string | number)[] = []): string | null {
  const tc = toolchain()
  const parts = inputParts(root, kind)
  if (parts === null) return null
  const base = digest(parts)
  if (base === null) return null
  const h = createHash('sha256')
  h.update(
    `${base}|${kind}|${unit}|${tc.sharp}|${tc.node}` +
      `|${tc.ffmpeg}|${tc.browser}|${extra.map(String).join('|')}`,
  )
  return h.digest('hex').slice(0, 16)
}

// ---------------------------------------------------------------- 存取

export function ledgerPath(root: string): string {
  return join(root, 'build', 'manifest.json')
}

export function load(root: string): LedgerDoc {
  const p = ledgerPath(root)
  if (!existsSync(p)) return { version: VERSION, updatedAt: null, entries: {} }
  try {
    const d = JSON.parse(readFileSync(p, 'utf8')) as Partial<LedgerDoc>
    if (d.version !== VERSION) return { version: VERSION, updatedAt: null, entries: {} }
    return { version: VERSION, updatedAt: d.updatedAt ?? null, entries: d.entries ?? {} }
  } catch {
    // 账本坏了就当没有：它是省时间的依据，不是正确性依据，不能因此拦住构建
    return { version: VERSION, updatedAt: null, entries: {} }
  }
}

function sortKeysDeep<T>(v: T): T {
  if (Array.isArray(v)) return v.map(sortKeysDeep) as unknown as T
  if (v !== null && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(v as Record<string, unknown>).sort()) {
      out[k] = sortKeysDeep((v as Record<string, unknown>)[k])
    }
    return out as T
  }
  return v
}

export function save(root: string, doc: LedgerDoc): void {
  const p = ledgerPath(root)
  mkdirSync(dirname(p), { recursive: true })
  doc.updatedAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
  const tmp = p.replace(/\.json$/, '.json.tmp')
  writeFileSync(tmp, JSON.stringify(sortKeysDeep(doc), null, 1), 'utf8')
  renameSync(tmp, p) // 原子换：中途断电不会留下半个账本
}

export function statusOf(
  root: string,
  kind: string,
  unit: string,
  artifacts: readonly string[],
  extra?: readonly (string | number)[],
): [boolean, string] {
  const e = load(root).entries[`${kind}:${unit}`]
  const useExtra =
    extra === undefined
      ? ((e?.extra ?? []) as (string | number)[]) // 账本自描述：按条目里记录的那份复算
      : extra
  const fp = fingerprint(root, kind, unit, useExtra)
  if (fp === null) return [false, '指纹算不出（模块/数据/工具链读不到），保守判过期']
  if (!e) return [false, '账本里没有这条（首次构建或账本被清）']
  if (e.fingerprint !== fp) return [false, '输入指纹变了（源码/数据/工具链有改动）']
  const missing = artifacts.filter((a) => !existsSync(join(root, a)))
  if (missing.length) return [false, `产物缺失：${missing.slice(0, 3).join('、')}`]
  return [true, '指纹一致且产物齐全']
}

export function record(
  root: string,
  kind: string,
  unit: string,
  artifacts: readonly string[],
  extra: readonly (string | number)[] = [],
): void {
  const doc = load(root)
  doc.entries[`${kind}:${unit}`] = {
    kind,
    unit,
    fingerprint: fingerprint(root, kind, unit, extra),
    extra: extra.map(String),
    artifacts: artifacts.map(String),
    toolchain: toolchain(),
    builtAt: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  }
  save(root, doc)
}

/** 列出全部已登记单元的新鲜度。返回 (新鲜条目, 过期条目) 并打印报表。 */
export function report(root: string, kinds?: readonly string[]): [Array<[string, string]>, Array<[string, string]>] {
  const doc = load(root)
  const stale: Array<[string, string]> = []
  const fresh: Array<[string, string]> = []
  for (const [key, e] of Object.entries(doc.entries).sort(([a], [b]) => (a < b ? -1 : 1))) {
    if (kinds && !kinds.includes(e.kind)) continue
    const [ok, why] = statusOf(root, e.kind, e.unit, e.artifacts ?? [])
    ;(ok ? fresh : stale).push([key, why])
  }
  const line = '='.repeat(68)
  console.log(line)
  console.log(`缓存账本：${fresh.length} 新鲜 / ${stale.length} 过期（${ledgerPath(root)}）`)
  console.log(line)
  for (const [k, why] of stale) console.log(`  [STALE] ${k.padEnd(28)} ${why}`)
  for (const [k] of fresh) console.log(`  [OK]    ${k}`)
  if (!Object.keys(doc.entries).length) console.log('  （空：先跑一次 render 才会登记）')
  return [fresh, stale]
}

/** cli 路由入口：`feuille ledger status [--root DIR] [--kind KIND]`。退出码：有过期 → 1。 */
export function mainStatus(argv: string[] = []): number {
  const rootIdx = argv.indexOf('--root')
  const root = rootIdx >= 0 ? resolve(argv[rootIdx + 1] ?? '.') : resolve('.')
  const kinds: string[] = []
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--kind' && argv[i + 1]) {
      kinds.push(argv[i + 1]!)
      i++
    }
  }
  if (!Object.keys(load(root).entries).length) {
    console.log(`账本是空的（${ledgerPath(root)}）——还没有登记过任何产物`)
    return 0
  }
  const [, stale] = report(root, kinds.length ? kinds : undefined)
  return stale.length ? 1 : 0
}
