// framehash.ts — 成片逐帧像素基线（⑬ 验收检查的像素判据）（framehash.py 的 TS 移植）
//
// **判据是什么**：`ffmpeg -f hash` 算的是**解码后每一帧像素**的 MD5，不是容器字节。
// 容器会因 mux 参数、时间戳写入顺序而变，字节哈希一碰就红；像素哈希只在
// **画面真的变了**时才红。
//
// **`-map 0:v` 是承重的**（实测）：少了它 ffmpeg 走默认流选择，同一支片子算出来
// 是不同数字——不报错、不警告，只是数字不同。反向验证套件有源级断言盯着。
//
// **基线按平台分桶**（桶 = 系统 + 架构 + 浏览器 + 成像库）。跨平台的逐帧像素
// 本来就不可能一致（系统字体 → 字形栅格化不同），每台机器各采一份、互不比较；
// 判据仍是「与本机上次渲的相比有没有变」。TS 侧桶的成像库段是 sharp（Python
// 侧是 pillow）——**桶名不同是设计内**：两套栅格化的基线本来就不能互比。
//
// 移植口径：
// - ffmpeg/ffprobe argv 与 Python **逐字一致**（口径即尺子）。
// - **性能修复直接内置**：framehash() 对同一支片子连算多次的场景（report 循环
//   里 status + compare 反复点名同一文件）加 (size, mtime) 键记忆化——文件字节
//   变了键就变，不会算错；测试用 resetHashCacheForTests()。
// - 差异热力图：PIL ImageChops.difference 的逐像素数学 → sharp 解码 raw + JS
//   逐像素运算（灰度用 PIL 的 601 定点口径 L = (R*299 + G*587 + B*114)/1000）。
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import sharp from 'sharp'

import { browser, ffmpeg as resolveFfmpeg, ffprobe as resolveFfprobe, machineArch, systemName } from './platform.js'
import { FeuilleError } from './errors.js'

// 注意：这里曾有 `FPS_DEFAULT = 30.0`，probeFps 拿它当「解不出帧率」的返回值。
// 那等于把「测不到」写成「就是 30」，帧数会跟着算错且无任何提示。已删除——
// probeFps 现在与 framehash / perFrame 同契约：解不出就抛。

// ---------------------------------------------------------------- 哈希（memoize）

const hashCache = new Map<string, string>()

export function resetHashCacheForTests(): void {
  hashCache.clear()
}

function cacheKey(path: string): string | null {
  try {
    const st = statSync(path)
    return `${st.size}-${Math.floor(st.mtimeMs)}`
  } catch {
    return null
  }
}

function runCapture(cmd: string[], timeoutMs?: number): { code: number; stdout: string; stderr: string } {
  try {
    const stdout = execFileSync(cmd[0]!, cmd.slice(1), {
      encoding: 'utf8', timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024,
    })
    return { code: 0, stdout, stderr: '' }
  } catch (e) {
    const err = e as { status?: number; stdout?: string; stderr?: string }
    return { code: err.status ?? 1, stdout: err.stdout ?? '', stderr: err.stderr ?? '' }
  }
}

/** 解码后全部帧的像素 MD5（`MD5=…`）。失败即抛——静默跳过等于把「渲坏了」当「不在基线里」。 */
export function framehash(path: string): string {
  const k = cacheKey(path)
  if (k !== null) {
    const cached = hashCache.get(`${path}|${k}`)
    if (cached) return cached
  }
  const ffmpeg = resolveFfmpeg()
  if (ffmpeg === null) throw new FeuilleError('缺 ffmpeg（resolver 未找到）')
  const r = runCapture([ffmpeg, '-v', 'error', '-i', path, '-map', '0:v', '-f', 'hash', '-hash', 'md5', '-'])
  if (r.code !== 0) throw new Error(`ffmpeg hash 失败 ${path}: ${r.stderr.trim()}`)
  for (const line of r.stdout.split('\n')) {
    if (line.startsWith('MD5=')) {
      const out = line.trim()
      if (k !== null) hashCache.set(`${path}|${k}`, out)
      return out
    }
  }
  throw new Error(`ffmpeg 未输出 MD5：${path}`)
}

/** 逐帧像素 MD5 列表。整支一个 MD5 只能回答「变没变」，回答不了「哪一帧开始变」。 */
export function perFrame(path: string): string[] {
  const ffmpeg = resolveFfmpeg()
  if (ffmpeg === null) throw new FeuilleError('缺 ffmpeg（resolver 未找到）')
  const r = runCapture([ffmpeg, '-v', 'error', '-i', path, '-map', '0:v', '-f', 'framehash', '-hash', 'md5', '-'])
  if (r.code !== 0) throw new Error(`ffmpeg framehash 失败 ${path}: ${r.stderr.trim()}`)
  return r.stdout
    .split('\n')
    .filter((ln) => ln && !ln.startsWith('#'))
    .map((ln) => (ln.split(',', 2)[1] ?? '').trim())
}

/** 视频平均帧率。缺 ffprobe 或解不出数字一律抛——与 framehash/perFrame 同契约。
 *
 * 旧实现返回 FPS_DEFAULT(30)，那是把「我不知道」写成「就是 30」：帧率错会
 * 直接算错帧数，且静默值比报错更坏（纪律 8：没数据留 null 不填 0；纪律 19：
 * 任何「失败退回默认值」的静默兜底都禁止）。 */
export function probeFps(path: string): number {
  const ffprobe = resolveFfprobe()
  if (ffprobe === null) throw new FeuilleError('缺 ffprobe（resolver 未找到）')
  const r = runCapture([
    ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
    'stream=avg_frame_rate', '-of', 'csv=p=0', path,
  ])
  if (r.code !== 0) throw new Error(`ffprobe avg_frame_rate 失败 ${path}: ${r.stderr.trim()}`)
  const s = r.stdout.trim()
  const slash = s.indexOf('/')
  const num = slash < 0 ? s : s.slice(0, slash)
  const den = slash < 0 ? '1' : s.slice(slash + 1)
  const f = Number(num) / Number(den)
  if (!(f > 0) || !Number.isFinite(f)) {
    throw new Error(`ffprobe 未给出可用帧率 ${path}（avg_frame_rate=${s || '<空>'}）`)
  }
  return f
}

/** (第一处不同的帧号, 末处不同的帧号)。帧数不同也算漂移（丢帧尾巴的症状）。 */
export function firstDrift(ref: string[], cur: string[]): [number | null, number | null] {
  const n = Math.min(ref.length, cur.length)
  let first: number | null = null
  let last: number | null = null
  for (let i = 0; i < n; i++) {
    if (ref[i] !== cur[i]) {
      if (first === null) first = i
      last = i
    }
  }
  if (first === null && ref.length !== cur.length) first = last = n
  return [first, last]
}

/** 抽第 index 帧存 PNG 当证据图。失败返回 false（证据图是辅助，不是判据）。 */
export function extractFrame(video: string, index: number, outPng: string): boolean {
  const ffmpeg = resolveFfmpeg()
  if (ffmpeg === null) return false
  mkdirSync(dirname(outPng), { recursive: true })
  const r = runCapture([
    ffmpeg, '-v', 'error', '-y', '-i', video, '-map', '0:v',
    '-vf', `select=eq(n\\,${index})`, '-vsync', '0', '-frames:v', '1', outPng,
  ])
  return r.code === 0 && existsSync(outPng)
}

/**
 * 参考帧 vs 当前帧差异热力图（红=差得多）。没有参考帧就诚实返回 false——
 * **不做「假装有参考」的合成图**：造一张像差异图的图比不给更坏。
 * 逐像素数学与 PIL 版一致：|a-b| → 601 定点灰度 ×6 截断 → (d, 255-d, 255)。
 */
export async function diffPng(refPng: string, curPng: string, outPng: string): Promise<boolean> {
  if (!existsSync(refPng) || !existsSync(curPng)) return false
  const [a, b] = await Promise.all([
    sharp(refPng).removeAlpha().raw().toBuffer({ resolveWithObject: true }),
    sharp(curPng).removeAlpha().raw().toBuffer({ resolveWithObject: true }),
  ])
  if (a.info.width !== b.info.width || a.info.height !== b.info.height) return false
  const n = a.info.width * a.info.height
  const heat = Buffer.alloc(n * 3)
  for (let i = 0; i < n; i++) {
    const p3 = i * 3
    let d = 0
    for (let c = 0; c < 3; c++) {
      // PIL RGB→L 的 601 定点口径
      const dv = Math.abs(a.data[p3 + c]! - b.data[p3 + c]!)
      d += dv * [299, 587, 114][c]!
    }
    d = Math.min(255, Math.floor(d / 1000) * 6)
    heat[p3] = d
    heat[p3 + 1] = 255 - d
    heat[p3 + 2] = 255
  }
  mkdirSync(dirname(outPng), { recursive: true })
  await sharp(heat, { raw: { width: a.info.width, height: a.info.height, channels: 3 } }).png().toFile(outPng)
  return true
}

// ---------------------------------------------------------------- 分桶

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9.-]/g, (c) => (c.match(/[a-z0-9.-]/) ? c : '-'))
}

/** 本机像素桶标识（故意**可读**不取哈希：「基线为什么全红」需要一眼看出是平台不同还是浏览器换了）。 */
export function bucket(): string {
  const b = browser()
  const name = b ? b[0] : 'no-browser'
  const versions = (sharp as unknown as { versions?: Record<string, string> }).versions
  const sharpId = versions?.sharp ?? 'no-sharp'
  return [slug(systemName() || 'unknown'), slug(machineArch() || 'unknown'), slug(name), slug(`sharp${sharpId}`)].join('-')
}

export function baselinePath(root: string, bucketId?: string): string {
  return join(root, 'build', 'baseline', `framehash-${bucketId ?? bucket()}.txt`)
}

/** 基线表 → {成片文件名: 哈希}。不存在返回空表不抛——「没有基线 → 明确报错」由 compare 层负责。 */
export function readBaseline(path: string): Record<string, string> {
  if (!existsSync(path)) return {}
  const out: Record<string, string> = {}
  for (const ln of readFileSync(path, 'utf8').split('\n')) {
    if (!ln.trim() || ln.startsWith('#')) continue
    const idx = ln.indexOf('  ')
    if (idx < 0) continue
    const name = ln.slice(0, idx).trim()
    const h = ln.slice(idx + 2).trim()
    if (name && h) out[name] = h
  }
  return out
}

export function saveBaseline(hashes: Record<string, string>, path: string): string {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, Object.keys(hashes).sort().map((n) => `${n}  ${hashes[n]}\n`).join(''), 'utf8')
  return path
}

export interface ClassifyResult {
  same: string[]
  diff: string[]
  new: string[]
  gone: string[]
  skipped: string[]
}

/** 比对结果分桶（纯函数，供反向验证与金样本 parity）。subset 时范围外归 skipped 不归 gone。 */
export function classify(base: Record<string, string>, cur: Record<string, string>, subset: boolean): ClassifyResult {
  const missing = Object.keys(base).filter((k) => !(k in cur)).sort()
  const curSorted = Object.keys(cur).sort()
  return {
    same: curSorted.filter((n) => n in base && base[n] === cur[n]),
    diff: curSorted.filter((n) => n in base && base[n] !== cur[n]),
    new: curSorted.filter((n) => !(n in base)),
    gone: subset ? [] : missing,
    skipped: subset ? missing : [],
  }
}

/** 当前成片集 vs 基线。返回 [分类结果, 退出码 0/1]。 */
export function compare(
  videos: readonly string[],
  baselineFile: string,
  opts: { subset?: boolean } = {},
): [ClassifyResult, number] {
  if (!videos.length) throw new FeuilleError('没找到成片：videos 为空')
  const cur: Record<string, string> = {}
  for (const v of videos) cur[basename(v)] = framehash(v)
  const base = readBaseline(baselineFile)
  const r = classify(base, cur, opts.subset ?? false)
  const line = '='.repeat(72)
  console.log(line)
  console.log(
    `逐帧像素基线：${r.same.length}/${Object.keys(cur).length} 一致` +
      `${opts.subset ? '（子集核查）' : ''}　（基线 ${Object.keys(base).length} 行 / 当前 ${Object.keys(cur).length} 支）`,
  )
  console.log(line)
  for (const n of r.diff) console.log(`  [DRIFT] ${n}  ${base[n] ?? '?'} → ${cur[n]}`)
  for (const n of r.new) console.log(`  [NEW]   ${n}  ${cur[n]}`)
  for (const n of r.gone) console.log(`  [GONE]  ${n}  基线里有、当前没有`)
  if (r.skipped.length) console.log(`  [跳过]  基线中另有 ${r.skipped.length} 支不在本次范围内，未参与比对`)
  if (!(r.diff.length || r.new.length || r.gone.length)) console.log('  零漂移：全部成片逐帧一致')
  return [r, r.diff.length || r.gone.length ? 1 : 0]
}

function basename(p: string): string {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
  return p.slice(i + 1)
}

// ---- CLI 适配层（feuille framehash save|check）--------------------------------
// 库函数已有全部判据；叶子只做「发现产物 → 调库 → 定退出码」的薄编排。

/** build/ 下全部成片（全量发现）。没有产物时显式报错退出，绝不静默产出一个空基线。 */
export function discoverVideos(root: string): string[] {
  const build = join(root, 'build')
  if (!existsSync(build)) throw new FeuilleError(`没有 build/ 目录（root=${root}）——基线登记的是产物，先有产物`)
  const vids = walkMp4(build).sort()
  if (!vids.length) throw new FeuilleError(`build/ 下没有 mp4（root=${root}）——没找到成片，videos 为空`)
  return vids
}

function walkMp4(dir: string): string[] {
  const out: string[] = []
  const entries = readdirSync(dir, { withFileTypes: true })
  for (const e of entries) {
    const p = join(dir, e.name)
    if (e.isDirectory()) out.push(...walkMp4(p))
    else if (e.isFile() && e.name.endsWith('.mp4')) out.push(p)
  }
  return out
}

/** cli 路由入口：`feuille framehash save [--root DIR]`。采完立刻回读自证（坑㉞ 纪律内建）。 */
export function mainSave(argv: string[] = []): number {
  const rootIdx = argv.indexOf('--root')
  const root = resolveCwd(rootIdx >= 0 ? argv[rootIdx + 1] ?? '.' : '.')
  const cur: Record<string, string> = {}
  for (const p of discoverVideos(root)) cur[basename(p)] = framehash(p)
  const out = saveBaseline(cur, baselinePath(root))
  const back = readBaseline(out)
  const mismatch = Object.keys(cur).filter((n) => back[n] !== cur[n])
  const extra = Object.keys(back).filter((n) => !(n in cur))
  if (mismatch.length || extra.length) {
    throw new FeuilleError(
      `基线回读自证失败（写 ${Object.keys(cur).length} 读 ${Object.keys(back).length}）：` +
        `不符 ${mismatch.slice(0, 3).join('、')} 多出 ${extra.slice(0, 3).join('、')} → ${out}`,
    )
  }
  console.log(`基线已采：${Object.keys(cur).length} 支 → ${out}`)
  console.log(`分桶：${bucket()}（基线按平台分桶，跨平台不可比）`)
  return 0
}

/** cli 路由入口：`feuille framehash check [--root DIR] [--subset]`。退出码：diff 或 gone → 1。 */
export function mainCheck(argv: string[] = []): number {
  const rootIdx = argv.indexOf('--root')
  const root = resolveCwd(rootIdx >= 0 ? argv[rootIdx + 1] ?? '.' : '.')
  const subset = argv.includes('--subset')
  const [, rc] = compare(discoverVideos(root), baselinePath(root), { subset })
  return rc
}

function resolveCwd(p: string): string {
  // 与 Python Path(a.root).resolve() 同口径：相对 cwd 解析为绝对路径
  return resolve(p)
}
