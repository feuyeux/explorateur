// score.ts — **谱面真值的采集侧**（SKILL.md 早就许诺、一直缺的那个叶子）。
//
// 为什么需要它（缺口原文）：`align` 的 Tier A 要一份 MIDI/谱面真值，但此前
// 「MIDI/乐谱仍全靠手取」——Mutopia 的 `*-mids.zip` 手工能下，抓取没归流。
// 结果是每做一支片，谱面这一段都是人工劳动，而且**取来的那份谱到底对应哪个
// 版本、许可是什么、sha256 多少**全靠记忆。这与 `source`（录音台账）不对称：
// 录音有账，谱面没账。
//
// 本叶子把「找谱 → 读元数据 → 判许可 → 下字节 → 记 sha256」收成一条可复核
// 的路径，产出与 `source` 同形的台账条目，进同一个 `sources.json`。
//
// ## 唯一事实源与三道门槛
//
// 谱面元数据只有一个结构化来源：Mutopia 的 **RDF**（`<work>.rdf`，紧邻 zip）。
// HTML 列表页（`make-table.cgi?Composer=<id>`）只用来**发现**作品与目录名，
// 不用来读许可——HTML 里那行「Creative Commons Attribution 3.0」是同一个值
// 的第二次出现，两处解析等于给未来的自己埋一个「哪份是对的」。
//
// 1. **身份**：`mp:composer` / `mp:title` / `mp:opus` / `mp:for` 全部落账；
//    `mp:id`（`Mutopia-YYYY/MM/DD-NNNN`）是这一版谱的唯一标识。
// 2. **许可**：只收 **PD / CC0 / CC BY / CC BY-SA**（复用 `source.isUsableLicense`
//    的同一张白名单——白名单只许有一份，否则录音收得进的谱面收不进）。
//    NC / ND 一律拒；许可读不到 = 拒（**不许**因为「Mutopia 一般都是 CC」就放行，
//    这正是 `source` 那边用 16 条伪造署名换来的教训）。
// 3. **字节**：下载后记 sha256。同一 URL 的内容会变（重新排版、换 LilyPond
//    版本重编），sha256 才是「同一份」的判据。
//
// ## 为什么解 zip 而不是直接存 zip
//
// Mutopia 的 `-mids.zip` 里是**一堆** `.mid`（分谱 + `score.mid`）。Tier A 要
// 的是总谱：`score.mid` 优先，没有则取音数最多的一份（分谱通常音少），并把
// 「挑了哪一份、为什么」写进条目——不许静默挑第一个（zip 条目顺序不是语义）。
import { createHash } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { FeuilleError, platform } from '@feuille/core'

import { numOpt, parseArgs, strOpt } from './cli.js'
import { parseMidi } from './midi.js'
import { isUsableLicense } from './source.js'

/** Mutopia 站点根。抽成常量：测试注入接缝时按它拼假 URL，不必散落字符串。 */
export const MUTOPIA = 'https://www.mutopiaproject.org'

/** 自定义 UA：与 `source` 同一条取数礼仪（默认 UA 会被挡/被限流）。 */
const UA = 'feuille-music-score/0.1 (classical music appreciation pipeline; local research use)'

/** 一个谱面候选（= 一个 Mutopia 作品）。 */
export interface ScoreCandidate {
  /** Mutopia 作品 id（`Mutopia-2009/09/05-1695`）；RDF 读不到时为 null。 */
  mutopiaId: string | null
  /** RDF 里的标题。 */
  title: string
  /** Mutopia 作曲家目录名（`BachJS`）——**不是**作曲家全名。 */
  composerDir: string
  /** RDF 里的作曲家字段（通常也是目录名形态）。 */
  composer: string
  /** 作品号（`BWV 16`；RDF 缺省为 ''）。 */
  opus: string
  /** 编制（`for ...`）。 */
  instrumentation: string
  /** 创作/出版年（字符串，原样保留——RDF 里是自由文本）。 */
  date: string
  /** 风格（Baroque 等）。 */
  style: string
  /** 许可原文（`Creative Commons Attribution 3.0`）。 */
  license: string
  /** 许可链接（站点把许可全指向 legal.html 的锚点，故这里记锚点 URL）。 */
  licenseUrl: string
  /** 来源说明（原书/原谱版本，`mp:source`）。 */
  sourceNote: string
  /** 维护者。 */
  maintainer: string
  /** mids.zip 直链（该版本有打包时）；否则为空串。 */
  midUrl: string
  /**
   * 目录里**直接**摆着的单个 `.mid`（`<work>.mid`）——Mutopia 的两种交付形态之一。
   *
   * 为什么必须区分：同一个站点上，老作品给 `<work>-mids.zip`（里面一堆分谱 +
   * score.mid），新作品给目录里一个 `<work>.mid`。2026-11-06 实测 BWV 259
   * 只有后者，按「一律拼 -mids.zip」去取就是 404——而 404 会被误读成
   * 「这件没有 MIDI」。形态是**目录列表里的事实**，必须在发现阶段读出来，
   * 不能靠猜。
   */
  midUrlDirect: string
  /** 该作品的 FTP 目录（人可复核的落脚点）。 */
  dirUrl: string
  /** 许可是否在白名单内。 */
  usable: boolean
}

/** 一次采集的产物（与 `source` 的 LedgerItem 同形的账目字段 + 谱面侧补充）。 */
export interface ScoreLedgerItem {
  id: string
  kind: 'score'
  /** 落盘文件名（`score.mid` 或分谱名）。 */
  title: string
  /** 直链（zip）。 */
  url: string
  /** 出处页 = RDF 的 URL（许可证据）。 */
  pageUrl: string
  license: string
  license_url: string
  /** 署名行：Mutopia 的约定是标注作品 id + 维护者。 */
  attribution: string
  retrieved: string
  sha256: string
  /** 从 zip 里挑出来的那一份。 */
  entryName: string
  /** 为什么挑它（`score.mid 优先` / `音数最多` …）。 */
  pickReason: string
  /** 挑出来那份字节的 sha256（zip 的 sha256 之外再记一份）。 */
  payloadSha256: string
  /** 音符数（用本包的 midi 解析器实测——**不是**从文件名猜）。 */
  noteCount: number
  /** 谱面时长（秒，实测）。 */
  durationS: number
  mutopiaId: string | null
  opus: string
  instrumentation: string
}

// ============================================================
//  RDF 解析（唯一的结构化事实源）
// ============================================================

/** 取一个 `mp:` 字段的文本（RDF 里是 `<mp:title>…</mp:title>`，自闭合时给 ''）。 */
export function rdfField(rdf: string, name: string): string {
  const m = new RegExp(`<mp:${name}>([\\s\\S]*?)</mp:${name}>`).exec(rdf)
  if (m) return decodeXml(m[1]!.trim())
  // 自闭合 / 空元素：`<mp:lyricist/>`
  return ''
}

function decodeXml(s: string): string {
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
}

/**
 * 把 Mutopia 的许可原文归一到白名单判据。
 *
 * 为什么要归一：RDF 写的是人话（`Creative Commons Attribution 3.0`、
 * `Public Domain`、`Creative Commons Attribution-ShareAlike 3.0`），而白名单
 * 判据收的是标识（`CC BY 3.0` / `PD` …）。不归一就会出现「人看着能用、机器判
 * 不能用」或者更糟的反向——所以转换规则集中在这一个函数里，测试逐条钉住。
 *
 * **不认识的一律不映射**（返回原文）→ 白名单判否 → 拒。宁可不收，不许猜。
 */
export function normalizeMutopiaLicense(raw: string): string {
  const s = raw.trim()
  if (s === '') return ''
  // 已是指标识：原样（让 isUsableLicense 去判）
  if (/^(PD|CC0|CC BY(-SA|-NC|-ND)?( \d\.\d)?)$/i.test(s)) return s
  if (/public domain/i.test(s)) return 'PD'
  if (/cc0/i.test(s)) return 'CC0'
  // **顺序是判据，不是风格**：先判 NC / ND（禁止项），再判 SA，最后才 BY。
  // 反过来的话 `Attribution-NonCommercial 4.0` 会被 `Attribution` 抢先匹配成
  // 「CC BY 4.0」——而 CC BY 在白名单里，一件**禁止商用**的谱面就此被判「可用」。
  // 这不是假设：v1 的代码就是这个顺序，被 2026-11-06 的坏例测试当场抓住
  // （`expected 'CC BY' to be 'CC BY-NC'`）。禁止项必须拥有最高优先级。
  if (/non[\s-]*commercial/i.test(s)) return 'CC BY-NC'
  if (/no[\s-]*deriv/i.test(s)) return 'CC BY-ND'
  // 然后才是 SA（`Attribution-ShareAlike` 不许被 `Attribution` 抢先）
  const sa = /creative\s+commons\s+attribution[\s-]*share[\s-]*alike\s*(\d\.\d)?/i.exec(s)
  if (sa) return `CC BY-SA${sa[1] ? ' ' + sa[1] : ''}`
  const by = /creative\s+commons\s+attribution\s*(\d\.\d)?/i.exec(s)
  if (by) return `CC BY${by[1] ? ' ' + by[1] : ''}`
  return s
}

/**
 * 从 RDF 文本构造候选。`midUrl` / `dirUrl` 由调用方按目录拼（RDF 只有文件名）。
 */
export function candidateFromRdf(
  rdf: string,
  opts: { composerDir: string; midUrl: string; midUrlDirect?: string; dirUrl: string },
): ScoreCandidate {
  const licenseRaw = rdfField(rdf, 'licence') || rdfField(rdf, 'license')
  const license = normalizeMutopiaLicense(licenseRaw)
  return {
    mutopiaId: rdfField(rdf, 'id') || null,
    title: rdfField(rdf, 'title'),
    composerDir: opts.composerDir,
    composer: rdfField(rdf, 'composer') || opts.composerDir,
    opus: rdfField(rdf, 'opus'),
    instrumentation: rdfField(rdf, 'for'),
    date: rdfField(rdf, 'date'),
    style: rdfField(rdf, 'style'),
    license,
    // 站点把许可统一指到 legal.html 的锚点；CC BY 是 #cca。
    licenseUrl: license.startsWith('CC BY') ? `${MUTOPIA}/legal.html#cca`
      : license === 'PD' || license === 'CC0' ? `${MUTOPIA}/legal.html#pd`
        : `${MUTOPIA}/legal.html`,
    sourceNote: rdfField(rdf, 'source'),
    maintainer: rdfField(rdf, 'maintainer'),
    midUrl: opts.midUrl,
    midUrlDirect: opts.midUrlDirect ?? '',
    dirUrl: opts.dirUrl,
    usable: isUsableLicense(license),
  }
}

/** 这件有没有可取的 MIDI（两种形态任一）。 */
export function hasMidi(c: ScoreCandidate): boolean {
  return c.midUrl !== '' || c.midUrlDirect !== ''
}

// ============================================================
//  列表页发现（只用来找目录名，不读许可）
// ============================================================

/**
 * 解析目录列表里的可下载文件名（只看同层 `href`，跳过 `../` 与 `?C=` 排序链接）。
 *
 * 用途：判这件作品给的是 `<work>-mids.zip` 还是目录里直接一个 `<work>.mid`。
 */
export function parseDirEntries(html: string): string[] {
  const out: string[] = []
  for (const m of html.matchAll(/href="((?![a-z]+:|[?/]|\.\.)[^"]+)"/gi)) {
    const name = m[1]!
    if (!out.includes(name)) out.push(name)
  }
  return out
}

/**
 * 从目录条目里定出 MIDI 的两种形态（zip / 单个 .mid）。
 *
 * 返回 null = 这件作品**确实没有** MIDI（只有 PDF/PS），调用方据此把它从
 * 「可用」里摘掉，而不是等下载时撞 404。
 */
export function midiUrlsOf(
  dirUrl: string,
  entries: readonly string[],
): { midUrl: string; midUrlDirect: string } | null {
  const base = dirUrl.replace(/\/$/, '')
  const zip = entries.find((n) => /-mids\.zip$/i.test(n))
  // 单文件形态：目录根上的 `*.mid`（不带子目录），取第一个（Mutopia 一件作品一个）
  const single = entries.find((n) => /^[^/]+\.midi?$/i.test(n))
  if (zip === undefined && single === undefined) return null
  return {
    midUrl: zip !== undefined ? `${base}/${zip}` : '',
    midUrlDirect: single !== undefined ? `${base}/${single}` : '',
  }
}

/**
 * 从作曲家列表页抽出全部作品的 FTP 目录（相对路径，如
 * `ftp/BachJS/BWV16/Cantata_16_no_5`）。
 *
 * 为什么用目录而不是 `-mids.zip` 直链：一个作品可能没有 MIDI（只有 PDF/PS），
 * 而 RDF 一定在目录里。先拿目录，再探 RDF 与目录里的 MIDI，能干净地报「这件
 * 没有 MIDI」而不是把「404」误当成「作品不存在」。
 *
 * 去重 + 保持出现顺序：同一作品的多个下载链接指向同一目录，重复计数只会让
 * 「找到 N 件」这个数字虚高。
 */
export function parseListingDirs(html: string): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const re = /href="(?:[^"]*?\/)?((?:\.\.\/)?ftp\/[^"]+)"/g
  for (const m of html.matchAll(re)) {
    let path = m[1]!.replace(/^\.\.\//, '')
    // 链接可能是文件（`…-mids.zip`）而不是目录（`…/`）——**两种都要认**。
    // 只认带尾斜杠的目录链接会让「只挂了文件链接」的作品整件消失；实测列表页
    // 每行都有 "Appropriate FTP area" 目录链接，所以老代码在真站点上碰巧够用，
    // 但这属于「靠页面模板的巧合工作」，模板一改就静默漏作品。
    if (!path.endsWith('/')) {
      const cut = path.lastIndexOf('/')
      if (cut <= 0) continue
      path = path.slice(0, cut)
    }
    path = path.replace(/\/$/, '')
    if (seen.has(path)) continue
    seen.add(path)
    out.push(path)
  }
  return out
}

// ============================================================
//  zip 里的谱面挑选
// ============================================================

/** zip 里的一个候选条目（只留 .mid）。 */
export interface MidiEntry {
  name: string
  size: number
  data: Buffer
}

/**
 * 挑总谱。
 *
 * 规则（顺序即优先级，**每条都写进 pickReason**）：
 * 1. 名字（不含目录、不含扩展名）等于 `score`（大小写不敏感）→ 总谱；
 * 2. 否则音数最多的那份；
 * 3. 音数并列时取字节大的（同样音数下，长曲子字节更多）。
 *
 * 为什么不取第一个：zip 条目顺序由打包工具决定，不是语义。实测 Mutopia 的
 * Cantata_16_no_5-mids.zip 里第一个是 `continuo.mid`（数字低音，5.4KB），
 * 拿它当总谱去对齐会把整首曲子的和声结构当成四个声部之一。
 */
export function pickScoreMidi(
  entries: readonly MidiEntry[],
  noteCount: (buf: Buffer) => number,
): { entry: MidiEntry; reason: string } | null {
  const mids = entries.filter((e) => /\.midi?$/i.test(e.name))
  if (mids.length === 0) return null

  const stem = (n: string): string => n.replace(/^.*[\\/]/, '').replace(/\.midi?$/i, '').toLowerCase()
  const named = mids.find((e) => stem(e.name) === 'score')
  if (named) return { entry: named, reason: '文件名 stem = score（总谱命名约定）' }

  let best: MidiEntry | null = null
  let bestNotes = -1
  for (const e of mids) {
    const n = noteCount(e.data)
    if (n > bestNotes || (n === bestNotes && best !== null && e.size > best.size)) {
      best = e
      bestNotes = n
    }
  }
  if (best === null) return null
  return {
    entry: best,
    reason: `没有 score.mid；按音数最多挑（${bestNotes} 音符 / ${best.size} 字节）`,
  }
}

// ============================================================
//  网络
// ============================================================

async function get(url: string, timeoutMs = 30000): Promise<{
  ok: boolean
  status: number
  text: string
  bytes: Buffer
}> {
  const res = await fetch(url, {
    headers: { 'User-Agent': UA },
    signal: AbortSignal.timeout(timeoutMs),
  })
  const buf = Buffer.from(await res.arrayBuffer())
  return { ok: res.ok, status: res.status, text: buf.toString('utf8'), bytes: buf }
}

/** 读一个作品的 RDF；404 返回 null（该目录不是作品目录），其他错误抛出。 */
export async function fetchRdf(dir: string): Promise<string | null> {
  const work = dir.replace(/^.*\//, '')
  const url = `${MUTOPIA}/${dir}/${work}.rdf`
  const r = await get(url)
  if (r.status === 404) return null
  if (!r.ok) throw new FeuilleError(`读 RDF 失败 ${r.status}：${url}`)
  return r.text
}

/** 列出某作曲家的全部作品候选（读 RDF 定许可；RDF 缺的作品跳过并记原因）。 */
export async function searchScores(
  composerDir: string,
  opts: { limit?: number; intervalMs?: number } = {},
): Promise<{ candidates: ScoreCandidate[]; skipped: Array<{ dir: string; why: string }> }> {
  const limit = opts.limit ?? 50
  const interval = opts.intervalMs ?? 800
  const listUrl = `${MUTOPIA}/cgibin/make-table.cgi?Composer=${encodeURIComponent(composerDir)}`
  const listing = await get(listUrl)
  if (!listing.ok) throw new FeuilleError(`读列表页失败 ${listing.status}：${listUrl}`)
  const dirs = parseListingDirs(listing.text).slice(0, limit)

  const candidates: ScoreCandidate[] = []
  const skipped: Array<{ dir: string; why: string }> = []
  for (const dir of dirs) {
    await new Promise((r) => setTimeout(r, interval))
    let rdf: string | null
    try {
      rdf = await fetchRdf(dir)
    } catch (e) {
      skipped.push({ dir, why: e instanceof Error ? e.message : String(e) })
      continue
    }
    if (rdf === null) {
      // 目录不是作品（`-lys/` 之类的子目录），不是错误。
      skipped.push({ dir, why: '该目录没有 RDF（不是作品目录）' })
      continue
    }
    const work = dir.replace(/^.*\//, '')
    const dirUrl = `${MUTOPIA}/${dir}/`
    // 读目录列表定 MIDI 形态（zip / 单文件 / 没有）。这一步不能用「一律拼
    // -mids.zip」代替：实测两者并存，猜错就是 404，而 404 会被读成「没有谱」。
    let midi: { midUrl: string; midUrlDirect: string } | null = null
    try {
      const dl = await get(dirUrl)
      if (dl.ok) midi = midiUrlsOf(dirUrl, parseDirEntries(dl.text))
    } catch {
      // 目录读不到：不阻断候选，但**不假装有 MIDI**（midi 保持 null）。
    }
    await new Promise((r) => setTimeout(r, interval))
    candidates.push(candidateFromRdf(rdf, {
      composerDir,
      midUrl: midi?.midUrl ?? '',
      midUrlDirect: midi?.midUrlDirect ?? '',
      dirUrl,
    }))
  }
  return { candidates, skipped }
}

// ============================================================
//  落盘
// ============================================================

/** 解 zip：只留 .mid 条目（其余——ly、pdf、png——不读进来，省内存）。 */
export async function midiEntries(zipPath: string): Promise<MidiEntry[]> {
  // yauzl 是 CJS：ESM 侧只能用 default 互操作对象，走 `mod.default.open`。
  const mod = await import('yauzl')
  const open = (mod as unknown as { default: typeof import('yauzl') }).default.open
  return new Promise<MidiEntry[]>((resolve_, reject_) => {
    open(zipPath, { lazyEntries: true }, (err, zip) => {
      if (err || !zip) return reject_(err ?? new Error('cannot open zip'))
      const out: MidiEntry[] = []
      zip.on('error', reject_)
      zip.on('entry', (e: any) => {
        if (!/\.midi?$/i.test(e.fileName)) return zip.readEntry()
        zip.openReadStream(e, (err2: Error | null, rs: any) => {
          if (err2 || !rs) return reject_(err2 ?? new Error('no stream'))
          const chunks: Buffer[] = []
          rs.on('data', (c: Buffer) => chunks.push(c))
          rs.on('end', () => {
            const data = Buffer.concat(chunks)
            out.push({ name: e.fileName, size: data.length, data })
            zip.readEntry()
          })
          rs.on('error', reject_)
        })
      })
      zip.on('end', () => resolve_(out))
      zip.readEntry()
    })
  })
}

export function sha256(buf: Buffer): string {
  return createHash('sha256').update(buf).digest('hex')
}

export function today(): string {
  return new Date().toISOString().slice(0, 10)
}

// ============================================================
//  CLI：`feuille music score <composerDir> [--out-dir DIR] [--id ID] [--match TEXT]`
// ============================================================

/**
 * 采一件谱面并落盘。
 *
 * 落盘：`<out-dir>/<id>.json`（台账条目）+ `<out-dir>/<id>.mid`（挑出来的谱）。
 * 不落 zip 原始包——留一件已经挑好的、可直接喂 `align --score` 的文件，比留
 * 一个还要再解的包少一步出错的机会（zip 本身可随时按 `url` 重取）。
 */
export async function main(argv: string[]): Promise<number> {
  const a = parseArgs(argv)
  if (a.positional.length < 1) {
    console.error('usage: feuille music score <composerDir> [--out-dir DIR] [--id ID] '
      + '[--match TEXT] [--limit N]')
    return 2
  }
  const composerDir = a.positional[0]!
  const outDir = strOpt(a, 'out-dir', 'assets/scores')
  const match = strOpt(a, 'match', '')
  const limit = numOpt(a, 'limit', 50)

  const { candidates, skipped } = await searchScores(composerDir, { limit })
  for (const s of skipped) process.stderr.write(`  skip ${s.dir}：${s.why}\n`)

  // **先按 MIDI 可用性过滤，再按许可过滤**——两者分开计数，因为它们是两种
  // 完全不同的失败：许可不合格是「不能用」，没有 MIDI 是「Tier A 用不上」。
  // 混成一个数字，下次看到「6 件可用」就说不清是哪一种短缺。
  const noMidi = candidates.filter((c) => !hasMidi(c))
  const withMidi = candidates.filter((c) => hasMidi(c))
  const usable = withMidi.filter((c) => c.usable)
  if (usable.length === 0) {
    console.error(`没有「许可合格且带 MIDI」的谱面：读到 ${candidates.length} 件，`
      + `其中 ${noMidi.length} 件只有 PDF/PS（无 MIDI），`
      + `${withMidi.length - usable.length} 件许可不合格。`)
    return 1
  }

  // 选哪一件：--match 按标题/作品号子串过滤（大小写不敏感）；不匹配就是错误，
  // **不许**退回「那就挑第一件」——那会把某支片子的谱面悄悄换成别的作品。
  let picked: ScoreCandidate
  if (match !== '') {
    const needle = match.toLowerCase()
    const hits = usable.filter((c) =>
      c.title.toLowerCase().includes(needle)
      || c.opus.toLowerCase().includes(needle)
      || c.mutopiaId?.toLowerCase().includes(needle))
    if (hits.length === 0) {
      console.error(`--match ${JSON.stringify(match)} 没有命中。可用（${usable.length} 件）：`)
      for (const c of usable.slice(0, 20)) console.error(`  ${c.opus || '?'} — ${c.title}`)
      return 1
    }
    if (hits.length > 1) {
      console.error(`--match ${JSON.stringify(match)} 命中 ${hits.length} 件，需要更精确：`)
      for (const c of hits.slice(0, 20)) console.error(`  ${c.opus || '?'} — ${c.title}`)
      return 1
    }
    picked = hits[0]!
  } else {
    if (usable.length > 1) {
      console.error(`${composerDir} 有 ${usable.length} 件可用谱面，请用 --match 指定：`)
      for (const c of usable.slice(0, 20)) console.error(`  ${c.opus || '?'} — ${c.title}`)
      return 1
    }
    picked = usable[0]!
  }

  const id = strOpt(a, 'id', `score-${(picked.opus || picked.composerDir).replace(/[^A-Za-z0-9]+/g, '-')}`)
  // 出目录在建**两种形态**之前建：形态 B（单文件 .mid）不落 zip，早先只在
  // 形态 A 里 mkdir，于是 B 分支写完 .json 立刻 ENOENT（实测第一版）。
  mkdirSync(outDir, { recursive: true })

  // 两种交付形态分开走，但**产出一致**：最后都是一个 `<id>.mid` 进盘。
  // 480 行前那段注释解释过为什么要分开——猜形态 = 404 = 误读成「没有谱」。
  let midiBuf: Buffer
  let entryName: string
  let pickReason: string
  let sourceUrl: string
  let archiveSha: string

  if (picked.midUrlDirect !== '') {
    // 形态 B：目录里直接一个 .mid
    const r = await get(picked.midUrlDirect)
    if (!r.ok) throw new FeuilleError(`下载 MIDI 失败 ${r.status}：${picked.midUrlDirect}`)
    midiBuf = r.bytes
    entryName = picked.midUrlDirect.replace(/^.*\//, '')
    pickReason = '目录里唯一的 .mid（无 zip 打包形态）'
    sourceUrl = picked.midUrlDirect
    archiveSha = ''
  } else if (picked.midUrl !== '') {
    // 形态 A：-mids.zip，里面一堆分谱 + score.mid
    const zipRes = await get(picked.midUrl)
    if (!zipRes.ok) throw new FeuilleError(`下载 MIDI 包失败 ${zipRes.status}：${picked.midUrl}`)
    mkdirSync(outDir, { recursive: true })
    const zipPath = join(outDir, `${id}.zip`)
    writeFileSync(zipPath, zipRes.bytes)
    const entries = await midiEntries(zipPath)
    const chosen = pickScoreMidi(entries, (buf) => parseMidi(buf).notes.length)
    if (chosen === null) {
      console.error(`${picked.midUrl} 里没有 .mid 条目（${entries.length} 个）——这件没有 MIDI`)
      return 1
    }
    midiBuf = chosen.entry.data
    entryName = chosen.entry.name
    pickReason = chosen.reason
    sourceUrl = picked.midUrl
    archiveSha = sha256(zipRes.bytes)
  } else {
    // 发现阶段就该拦住的情况：候选没有 MIDI，却走到了下载。**不猜**。
    console.error(`${picked.opus || picked.title}：这件没有 MIDI（只有 PDF/PS）`)
    console.error(`  Tier A 需要 MIDI 谱面真值。取 PDF/PS 手工转：${picked.dirUrl}`)
    return 1
  }

  const parsed = parseMidi(midiBuf)
  // 出处页 = RDF 本身。它就是许可与身份的唯一结构化证据，比「FTP 目录列表」
  // 更精确（目录页只证明有这样一堆文件，RDF 证明**这一版**的许可与 id）。
  const rdfUrl = `${picked.dirUrl.replace(/\/$/, '')}/${picked.dirUrl.replace(/\/$/, '').split('/').pop()}.rdf`
  const item: ScoreLedgerItem = {
    id,
    kind: 'score',
    title: entryName,
    url: sourceUrl,
    pageUrl: rdfUrl,
    license: picked.license,
    license_url: picked.licenseUrl,
    attribution: `Mutopia Project ${picked.mutopiaId ?? ''}`.trim()
      + ` (maintainer: ${picked.maintainer || 'unknown'})`,
    retrieved: today(),
    sha256: archiveSha,
    entryName,
    pickReason,
    payloadSha256: sha256(midiBuf),
    noteCount: parsed.notes.length,
    durationS: Math.round(parsed.duration * 1000) / 1000,
    mutopiaId: picked.mutopiaId,
    opus: picked.opus,
    instrumentation: picked.instrumentation,
  }

  writeFileSync(join(outDir, `${id}.mid`), midiBuf)
  writeFileSync(join(outDir, `${id}.json`), JSON.stringify(item, null, 1), 'utf8')

  console.log(`${id}：${picked.opus || '?'} ${picked.title}`)
  console.log(`  ${entryName}（${pickReason}）`
    + ` ${parsed.notes.length} 音符 / ${parsed.duration.toFixed(1)}s`)
  console.log(`  许可 ${picked.license} · ${picked.mutopiaId ?? '无 id'}`)
  console.log(`  → ${join(outDir, `${id}.json`)} + ${id}.mid`)
  return 0
}
