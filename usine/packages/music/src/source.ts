// source.ts — 录音与谱面的**来源台账**（许可账本的采集侧）。
//
// 产线要能剪辑、混音、再发布，就必须先知道「这件录音/谱例的许可是什么、
// 出处页在哪、拿到的字节是不是同一份」。这三件事不能靠搜索结果的标题，
// 必须回到**出处页**（Wikimedia Commons 的 `File:` 页）去读。
//
// 三道门槛（与 skills/music-annotate-video/references/visual-research.md
// 同一套纪律，音频侧同款）：
//
// 1. **身份**：以出处页的作者 / 演出者 / 作品目录为准，与作品名交叉核对。
// 2. **许可**：PD-old / PD-US / CC0 首选；CC BY / CC BY-SA 可用但要带
//    attribution；`unknown`、聚合站转载、现代演出照一律不收。
// 3. **字节**：下载后记 sha256——同一个 URL 的内容会变（重新编码、上传者
//    换文件），sha256 才是「同一份」的判据。
//
// **为什么不信 extmetadata.Artist**：实测 Commons 上莫扎特 K.525 的录音，
// `Artist` 写的是「Wolfgang Amadeus Mozart」（作曲家）而不是演奏者。
// 署名一律从 **File: 页的 wikitext** 里读 `|author=` / `|credit=`。
//
// 取数礼仪：自定义 User-Agent（默认 UA 直接 403）、串行 + 间隔（并发 4+
// 会 429）、同一查询不重复跑。
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { FeuilleError, platform } from '@feuille/core'

import { numOpt, parseArgs, strOpt } from './cli.js'

/** Wikimedia Commons API 端点。 */
const API = 'https://commons.wikimedia.org/w/api.php'

/** 自定义 UA：Commons 对默认 UA（python-urllib 等）直接 403。 */
const UA = 'feuille-music-source/0.1 (classical music appreciation pipeline; local research use)'

/** 一个音频候选。 */
export interface AudioCandidate {
  /** Commons 文件名（不含 `File:` 前缀）。 */
  title: string
  /** 直链。 */
  url: string
  /** 出处页（许可证据）。 */
  pageUrl: string
  /** 字节数。 */
  size: number
  /** 时长（秒；Commons 未登记时为 null）。 */
  duration: number | null
  mime: string
  /** 许可标识（LicenseShortName）。 */
  license: string
  /** 许可链接。 */
  licenseUrl: string
  /** 署名行（从 File: 页 wikitext 的 author/credit 读，不信 extmetadata.Artist）。 */
  attribution: string
  /** 读出处页失败的原因（空/缺省 = 读成功）。有值 → 署名未知，**不是**「公有领域」。 */
  attributionError?: string
}

export interface SourceOptions {
  /** 每个作品取几个候选。 */
  limit?: number
  /**
   * 读出处的接缝（**给门禁用**）：默认打 Commons 的 `action=parse`。
   * 注入时必须不打网络——否则「读不到出处页」这条路径只能靠真的 429 来测，
   * 而门禁就变成了可用性测试。
   */
  readPage?: (title: string) => Promise<string>
  /** 最短时长（秒）——太短的片段不作数。 */
  minDurationSec?: number
  /** 下载并算 sha256。 */
  download?: boolean
  /** 下载目录（相对工作目录）。 */
  downloadDir?: string
  /** 请求间隔（毫秒）——别把 Commons 打出 429。 */
  intervalMs?: number
}

interface ExtMeta {
  LicenseShortName?: { value?: string }
  LicenseUrl?: { value?: string }
  UsageTerms?: { value?: string }
  Artist?: { value?: string }
  Credit?: { value?: string }
  DateTimeOriginal?: { value?: string }
}

function apiUrl(params: Record<string, string>): string {
  const u = new URL(API)
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v)
  return u.toString()
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

/**
 * 单次 API 请求。
 *
 * `curl --fail` 把 429 也变成失败退出码，所以这里要**区分 429 与真错**：
 * 429 是限速（该退避重试），其它 4xx/5xx 是查询本身的问题（重试无用）。
 */
function fetchJsonOnce(params: Record<string, string>): { ok: boolean; body?: unknown; status?: number; msg?: string } {
  const child = spawnSync('curl', [
    '-sS', '-A', UA, '-w', '\n%{http_code}', apiUrl(params),
  ], { encoding: 'utf8', timeout: 60_000, maxBuffer: 1 << 26 })
  if (child.error) return { ok: false, msg: `curl: ${child.error.message}` }
  const raw = child.stdout ?? ''
  const cut = raw.lastIndexOf('\n')
  const status = Number(raw.slice(cut + 1).trim())
  const body = raw.slice(0, cut)
  if (status !== 200) {
    return { ok: false, status, msg: body.slice(-300) || (child.stderr ?? '').slice(-300) }
  }
  try {
    return { ok: true, status, body: JSON.parse(body) }
  } catch (e) {
    return { ok: false, status, msg: `返回的不是 JSON：${String(e)}` }
  }
}

/** 带限速退避的 API 请求（429 → 线性退避重试；其它错误直接抛）。 */
async function fetchJson(params: Record<string, string>, tries = 5): Promise<unknown> {
  let wait = 2000
  for (let i = 0; i < tries; i++) {
    const r = fetchJsonOnce(params)
    if (r.ok) return r.body
    if (r.status === 429 && i < tries - 1) {
      await sleep(wait)
      wait *= 2
      continue
    }
    throw new FeuilleError(`Commons API 请求失败（${r.status ?? '?'}）：${r.msg ?? ''}`)
  }
  throw new FeuilleError('Commons API 请求失败：退避重试用尽')
}


/** 去掉 HTML 标签与实体，留下纯文本（wikitext 里常有 <span> 之类的装饰）。 */
function stripHtml(s: string): string {
  return s
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 展开 `{{Creator:Antonio Vivaldi}}` 这类模板 → `Antonio Vivaldi`。
 *
 * Commons 的 `|author=` 常年写模板而不是纯名字——不展开的话台账里就会出现
 * `{{Creator:Antonio Vivaldi}}` 这种没法用的署名行。 */
function expandCreator(s: string): string {
  return s.replace(/\{\{\s*Creator\s*:\s*([^|}]+?)\s*\}\}/gi, '$1')
}

/** 展开 `{{self|cc-by-sa-4.0|author=John Harrison}}` 的 author 参数。
 *
 * 许可模板里的 author 才是**录音的作者/演出者**；Information 模板的
 * `|author=` 常常是**作曲家**（实测维瓦尔第《四季》录音：许可模板的
 * author 是演奏者 John Harrison，而 Information 的 `|author=` 是作曲家
 * 维瓦尔第）。署名要用前者。 */
function licenseTemplateAuthor(wikitext: string): string {
  const re = /\{\{\s*self\s*\|[^}]*?\bauthor\s*=\s*([^|}]+)/gi
  const m = re.exec(wikitext)
  return m ? stripHtml(expandCreator(m[1]!)) : ''
}

/** 从 `|Description=` 里抠出演出者（描述里常见「… — 演奏者 / 指挥 / 乐团」）。 */
function performerFromDescription(wikitext: string): string {
  const m = /\|\s*Description\s*=\s*([^\n]+)/i.exec(wikitext)
  if (!m) return ''
  const desc = m[1]!
  const dash = desc.lastIndexOf('—')
  if (dash < 0) return ''
  const tail = desc.slice(dash + 1).replace(/\}\}.*$/, '').replace(/\|.*$/, '')
  return stripHtml(tail)
}

/** 从 File: 页的 wikitext 里取 `|key=` 的值（取第一个非空）。 */
function wikitextField(wikitext: string, key: string): string {
  const re = new RegExp(`\\|\\s*${key}\\s*=\\s*([^\\n|]+)`, 'i')
  const m = re.exec(wikitext)
  return m ? stripHtml(m[1]!) : ''
}

/**
 * 搜 Commons 的音频文件并读出处页，返回候选（许可 + 署名 + 直链）。
 *
 * `query` 建议写成「作曲家英文名 + 作品英文名 + 必要的编号」——足以排除
 * 同名作品。`filetype:audio` 限定媒体类型。
 */
export async function searchAudio(
  query: string,
  opts: SourceOptions = {},
): Promise<AudioCandidate[]> {
  const limit = opts.limit ?? 8
  const minDur = opts.minDurationSec ?? 30
  const interval = opts.intervalMs ?? 1200

  const search = await fetchJson({
    action: 'query', format: 'json', list: 'search',
    srsearch: `${query} filetype:audio`, srnamespace: '6', srlimit: String(limit),
  }) as { query?: { search?: Array<{ title: string }> } }
  const titles = (search.query?.search ?? []).map((s) => s.title)
  if (!titles.length) return []
  await sleep(interval)

  const info = await fetchJson({
    action: 'query', format: 'json', prop: 'imageinfo',
    iiprop: 'url|size|mime|mediatype|extmetadata',
    titles: titles.join('|'),
  }) as {
    query?: {
      pages?: Record<string, {
        title?: string
        imageinfo?: Array<{
          url?: string
          size?: number
          duration?: number
          mime?: string
          mediatype?: string
          descriptionurl?: string
          extmetadata?: ExtMeta
        }>
      }>
    }
  }

  const out: AudioCandidate[] = []
  for (const page of Object.values(info.query?.pages ?? {})) {
    const ii = page.imageinfo?.[0]
    if (!ii || ii.mediatype !== 'AUDIO') continue
    if (ii.duration !== undefined && ii.duration < minDur) continue
    const em = ii.extmetadata ?? {}
    const title = (page.title ?? '').replace(/^File:/, '')
    out.push({
      title,
      url: ii.url ?? '',
      pageUrl: ii.descriptionurl ?? `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(title)}`,
      size: ii.size ?? 0,
      duration: ii.duration ?? null,
      mime: ii.mime ?? '',
      license: stripHtml(em.LicenseShortName?.value ?? 'unknown'),
      licenseUrl: stripHtml(em.LicenseUrl?.value ?? ''),
      attribution: '',
    })
  }
  return out
}

/**
 * 读 File: 页的 wikitext，补上署名行。
 *
 * 署名优先取 `|author=`；没有就退到 `|credit=` / `|description=`。
 * **不采信 extmetadata.Artist**（它常写的是作曲家而不是演出者）。
 */
export async function fillAttribution(
  candidates: AudioCandidate[],
  opts: SourceOptions = {},
): Promise<AudioCandidate[]> {
  const interval = opts.intervalMs ?? 1200
  for (const c of candidates) {
    const page = `File:${c.title}`
    try {
      let wt: string
      if (opts.readPage) {
        wt = await opts.readPage(c.title)
      } else {
        const parsed = await fetchJson({
          action: 'parse', format: 'json', prop: 'wikitext', page,
        }) as { parse?: { wikitext?: { '*'?: string } } }
        wt = parsed.parse?.wikitext?.['*'] ?? ''
      }
      // 署名优先级：许可模板的 author（= 录音作者/演出者）→ Description 里的
      // 演出者 → Information 的 |author= → credit。**不采信 extmetadata.Artist**
      // （实测它写的是作曲家）。
      const licAuthor = licenseTemplateAuthor(wt)
      const performer = performerFromDescription(wt)
      const author = stripHtml(expandCreator(wikitextField(wt, 'author')))
      const credit = stripHtml(expandCreator(wikitextField(wt, 'credit')))
      const who = licAuthor || performer || author || credit
      c.attribution = who
        ? `${who} · ${c.license} via Wikimedia Commons`
        : `${c.license} via Wikimedia Commons`
      c.attributionError = ''
    } catch (e) {
      // **读不到出处页时绝不许编一个署名。** 第一版在这里写
      // `Public domain, via Wikimedia Commons`，于是 CC BY-SA 的录音被记成
      // 公有领域——那是一条伪造的许可声明，比空着危险得多（实测 16/64 条
      // 中招，多为 429）。这里只记错误 + 留空，`needsAttribution` 会把它们
      // 挑出来重读。
      c.attribution = ''
      c.attributionError = String((e as Error).message ?? e).slice(0, 160)
    }
    await sleep(interval)
  }
  return candidates
}

/**
 * 作品名里的「噪声词」：编号、调性、体裁修饰。它们几乎从不出现在文件名里，
 * 却会让 Commons 全文检索直接归零（实测：`Dufay Missa L'homme arme`
 * 命中 0，而 `Dufay` 命中 6，其中就有《Se la face ay pale》）。
 */
const NOISE = new Set([
  'op', 'opp', 'no', 'nos', 'nr', 'kk', 'rv', 'bwv', 'kv', 'hob', 'd', 'woo',
  'major', 'minor', 'flat', 'sharp', 'in', 'the', 'a', 'an', 'of', 'for', 'and',
  'from', 'de', 'la', 'le', 'les', 'der', 'die', 'das', 'il', 'el',
])

/** 把作品名切成有意义的检索词（去掉编号/调性/虚词）。 */
export function workTokens(work: string): string[] {
  // 撇号是词内字符（`L'homme`、`D'Arezzo`）——在撇号处切词会把它劈成单字母。
  return work
    .split(/[^\p{L}'\u2019]+/u)
    .map((t) => t.trim())
    .filter((t) => t.length >= 3)
    .filter((t) => !NOISE.has(t.toLowerCase()))
    .filter((t) => !/^[A-Z]?\d+$/.test(t))
}

/** 文件名与作品名的契合度（0–1；用于在候选里排序，不作硬判据）。 */
export function titleAffinity(fileTitle: string, work: string): number {
  const tokens = workTokens(work).map((t) => t.toLowerCase())
  if (!tokens.length) return 0
  const hay = fileTitle.toLowerCase()
  let hit = 0
  for (const t of tokens) if (hay.includes(t)) hit++
  return hit / tokens.length
}

/**
 * 分梯度检索：从最具体到最宽，逐步放宽。
 *
 * 只用「作曲家 + 作品名」这一条查询会漏掉大量真实存在的录音——Commons 的
 * 文件名常常只写作曲家与体裁（`Guillaume Dufay - Se La Face Ay Pale.ogg`），
 * 而检索是全词匹配的。梯度：全名 → 作品主词 → 作曲家。合并去重后按
 * `titleAffinity` 排序，**排序只是建议**：命中率不够时由人看台账决定。
 */
export async function searchAudioLadder(
  composer: string,
  work: string,
  opts: SourceOptions = {},
): Promise<AudioCandidate[]> {
  const tokens = workTokens(work)
  const queries: string[] = [`${composer} ${work}`]
  if (tokens.length) queries.push(`${composer} ${tokens.slice(0, 2).join(' ')}`)
  queries.push(composer)

  const seen = new Map<string, AudioCandidate>()
  for (const q of queries) {
    if (!q.trim()) continue
    try {
      const found = await searchAudio(q, opts)
      for (const c of found) if (!seen.has(c.title)) seen.set(c.title, c)
    } catch (e) {
      // 单条梯度失败（通常是 429）不该让整件作品归零——继续下一条更宽的。
      if (!seen.size) throw e
    }
    await sleep(opts.intervalMs ?? 1200)
  }

  const all = [...seen.values()]
  all.sort((a, b) => titleAffinity(b.title, work) - titleAffinity(a.title, work))
  return all
}

/** 下载并记 sha256（字节一致性的判据）。 */
export function downloadAndHash(
  url: string,
  destPath: string,
): { path: string; sha256: string; bytes: number } {
  mkdirSync(join(destPath, '..'), { recursive: true })
  const r = spawnSync('curl', ['-sSL', '--fail', '-A', UA, '-o', destPath, url],
    { encoding: 'utf8', timeout: 600_000 })
  if (r.status !== 0) {
    throw new FeuilleError(`下载失败（${r.status}）：${url}\n${(r.stderr ?? '').slice(-300)}`)
  }
  const buf = readAllBytes(destPath)
  const sha256 = createHash('sha256').update(buf).digest('hex')
  return { path: destPath, sha256, bytes: buf.length }
}

function readAllBytes(path: string): Buffer {
  // 用 node 内建读盘：与 skills 里的 sha256 口径一致（Node crypto + 原始字节）。
  return readFileSync(path)
}

/** 一条台账记录（与 `assets/template/sources.json` 的 items 同形）。 */
export interface LedgerItem {
  id: string
  kind: 'recording' | 'score' | 'image'
  title: string
  performer?: string
  url: string
  license: string
  license_url: string
  attribution: string
  /** 读出处页失败的原因（`''` = 读成功）。有值时署名未知，**不是**「公有领域」。 */
  attribution_error?: string
  retrieved: string
  sha256: string
  local_path?: string
  duration_s?: number | null
  notes?: string
}

/**
 * 把台账里**署名未知**的件挑出来（读出处页失败的、以及上一版把失败写成
 * 「Public domain」的历史记录）。
 *
 * 为什么要专门一条：署名是靠**读网页**得来的，而读网页会 429。读失败 ≠ 公有
 * 领域。这条把「还得再读一次」的件列出来，让续跑有的放矢，而不是把一份带
 * 假署名的台账当成品。
 */
export function needsAttribution(
  works: readonly SourcedWork[],
): SourcedWork[] {
  return works.filter((w) => {
    if (!w.recording) return false
    if (w.attributionError) return true
    const a = w.attribution ?? ''
    // 历史记录里那批被写成「Public domain」的：许可是 CC 就不是公有领域。
    return a === '' || (/^public domain/i.test(a) && !/^public domain$/i.test(w.license ?? ''))
  })
}

/** 今天的日期（YYYY-MM-DD）。 */
export function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/** 生成台账条目（sha256 未下载时留空串——交付前必须补上）。 */
export function toLedgerItem(
  c: AudioCandidate,
  id: string,
  opts: { sha256?: string; localPath?: string; performer?: string } = {},
): LedgerItem {
  return {
    id,
    kind: 'recording',
    title: c.title,
    performer: opts.performer,
    url: c.pageUrl,
    license: c.license,
    license_url: c.licenseUrl,
    attribution: c.attribution,
    attribution_error: c.attributionError ?? '',
    retrieved: today(),
    sha256: opts.sha256 ?? '',
    local_path: opts.localPath,
    duration_s: c.duration,
    notes: `直链 ${c.url}`,
  }
}

/**
 * 这条文件是**广播电台的节目引子**，不是该作品的录音。
 *
 * 判据：文件名以 `Inleiding ` 开头（荷兰语「引子」）。Commons 有一批这样的
 * 文件：它们是荷兰广播电台某期节目的开场音频，内容是**另一首**作品。
 * 实测：`Inleiding deFilharmonie - Edo de Waart (audio).mp3` 的正文写的是
 * 「deFilharmonie olv. Edo De Waart gaat de indrukwekkende Turangalîla
 * Symfonie van Olivier Messiaen te lijf」——这段音频是梅西安，不是它被挂到
 * 的那篇条目对应的作品；`Inleiding Cecil Taylor (audio).mp3` 同理。
 *
 * 为什么这条必须机器判：这类文件在 Commons 上有几十个，检索时会系统性地
 * 命中「作曲家名 + 作品名」的查询，因为它们被链接在那些作品的条目页上。
 * 106 件里中了 13 件——**逐条人眼看不过来，也不该由人眼看**。
 */
export function isRadioStub(fileTitle: string | undefined | null): boolean {
  return /^inleiding\s/i.test((fileTitle ?? '').trim())
}

/**
 * 这条文件是 **MIDI**（乐谱），不是录音。
 *
 * 音乐上「录音」与「乐谱」是两回事：成片要的是能听的声音。乐谱的
 * 价值在 Tier A 对拍（当 `score`），不当 `recording`。
 */
export function isScoreOnly(fileTitle: string | undefined | null): boolean {
  return /\.(mid|midi|musicxml|xml)$/i.test((fileTitle ?? '').trim())
}

/** 校验一个候选是否可以进成片（许可白名单）。 */
export function isUsableLicense(license: string): boolean {
  const l = license.toLowerCase()
  if (l.includes('unknown')) return false
  return (
    l.includes('public domain') || l.includes('cc0') || l.includes('cc by')
    || l.includes('cc-by') || l.includes('publicdomain')
  )
}

/** 工具探测（下载用 curl；ffprobe 用于时长复核）。 */
export function toolsAvailable(): { curl: boolean; ffprobe: boolean } {
  return {
    curl: platform.which('curl') !== null,
    ffprobe: platform.ffprobe() !== null,
  }
}

// ============================================================
//  CLI：feuille music source
// ============================================================

/**
 * `feuille music source <composer> <work> [--out-dir <dir>] [--id <src-XXX>] [--download]`
 *
 * 找一件录音，读它的出处页，登记许可与署名；`--download` 时下载并记 sha256。
 * 落盘：`<out-dir>/<id>.json`（台账条目）+ 可选 `<out-dir>/<id>.<ext>`（音频）。
 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const composer = args.positional[0]
  const work = args.positional[1]
  if (!composer || !work) {
    console.error('usage: feuille music source <composer> <work> [--out-dir <dir>] [--id <src-XXX>] [--download] [--limit 8]')
    return 2
  }
  const outDir = strOpt(args, 'out-dir', 'assets')
  const id = strOpt(args, 'id', 'src-001')
  const query = `${composer} ${work}`
  const cands = await searchAudio(query, { limit: numOpt(args, 'limit', 8) })
  if (!cands.length) {
    console.error(`source: ${query} → 没有命中音频文件`)
    return 1
  }
  await fillAttribution(cands)
  const usable = cands.filter((c) => isUsableLicense(c.license))
  const pick = usable[0] ?? cands[0]!

  let sha256 = ''
  let localPath: string | undefined
  if (args.flags.has('download')) {
    const ext = pick.url.split('?')[0]!.split('.').pop() || 'ogg'
    const dest = join(outDir, `${id}.${ext}`)
    const got = downloadAndHash(pick.url, dest)
    sha256 = got.sha256
    localPath = dest
  }

  const item = toLedgerItem(pick, id, { sha256, localPath })
  mkdirSync(outDir, { recursive: true })
  const outPath = join(outDir, `${id}.json`)
  writeFileSync(outPath, JSON.stringify(item, null, 1), 'utf8')

  console.log(`source: ${query}`)
  console.log(`  文件：${pick.title}`)
  console.log(`  许可：${pick.license}${pick.licenseUrl ? '  ' + pick.licenseUrl : ''}`)
  console.log(`  署名：${pick.attribution}`)
  console.log(`  时长：${pick.duration ?? '?'}s · ${(pick.size / 1048576).toFixed(1)} MB`)
  console.log(`  → ${outPath}`)
  if (!usable.length) console.error('  注意：没有许可白名单内的候选——别默认它可用。')
  return 0
}

// ============================================================
//  批量：整张作品表过一遍
// ============================================================

/** 极简 CSV 解析（RFC4180：双引号包字段、"" 转义、逗号或换行分隔）。 */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ }
        else inQuotes = false
      } else field += ch
      continue
    }
    if (ch === '"') { inQuotes = true; continue }
    if (ch === ',') { row.push(field); field = ''; continue }
    if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue }
    if (ch === '\r') continue
    field += ch
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row) }
  return rows
}

/** 一条批量结果。 */
export interface SourcedWork {
  entry: string
  composer: string
  work: string
  /** 命中的录音候选数。 */
  candidates: number
  /** 许可白名单内的候选数。 */
  usable: number
  /** 选中的录音（无则 null）。 */
  recording: LedgerItem | null
  /**
   * 选中项的**种类**：`recording`（是录音）/ `score`（是 MIDI 乐谱，不是
   * 录音）/ `stub`（是广播节目引子，内容是另一首作品）。
   * 后两种**不能当录音进成片**——这是实测出来的系统性问题，不是个别手滑。
   */
  pickKind?: 'recording' | 'score' | 'stub' | null
  /** 出处页（选中项）。 */
  pageUrl: string | null
  license: string | null
  attribution: string | null
  /** 读出处页失败的原因（`''` = 读成功）。 */
  attributionError: string
  durationS: number | null
  /** 文件名与作品名的契合度（0–1）——**建议**，不是判据：低分不代表错，高分不代表对。 */
  affinity?: number
  error?: string
}

/**
 * 整张作品表过一遍：检索 → 读出处页 → 登记。
 *
 * 串行 + 间隔（别把 Commons 打出 429）。单件失败不中断整批——失败要**记
 * 下来**（哪一件、什么错），不许静默跳过：漏掉的作品在生产时会变成
 * 「临时找不到录音」。
 */
export async function sourceBatch(
  csvPath: string,
  opts: SourceOptions & {
    idPrefix?: string
    /** 逐件落盘的台账路径。**必须给**：106 件要跑十几分钟，
     *  中途被打断时「跑完才写」等于零证据，「看起来像没做」。 */
    ledgerPath?: string
    /** 续跑：台账里已有且命中录音的件跳过。 */
    resume?: boolean
    /** 检索接缝（**给门禁用**）：默认走 Commons；注入时必须不打网络，
     *  否则门禁就变成了「今天 Commons 通不通」的可用性测试。 */
    searchFn?: (composer: string, work: string) => Promise<AudioCandidate[]>
    /** 署名接缝（同 `searchFn`，默认读出处页）。 */
    attributionFn?: (c: AudioCandidate[]) => Promise<AudioCandidate[]>
  } = {},
): Promise<SourcedWork[]> {
  const { readFileSync } = await import('node:fs')
  const rows = parseCsv(readFileSync(csvPath, 'utf8'))
  const head = rows[0] ?? []
  const col = (name: string): number => head.indexOf(name)
  const iEntry = col('entry')
  const iComp = col('composer_en')
  const iWork = col('work_en')
  if (iEntry < 0 || iComp < 0 || iWork < 0) {
    throw new FeuilleError(`作品表缺列：需要 entry / composer_en / work_en，表头是 ${head.join(',')}`)
  }
  const prefix = opts.idPrefix ?? 'src'
  const out: SourcedWork[] = []
  let n = 0

  // 续跑：读既有台账，把**已经有录音**的件原样带过来并跳过。
  const done = new Map<string, SourcedWork>()
  if (opts.resume && opts.ledgerPath) {
    try {
      const prev = JSON.parse(readFileSync(opts.ledgerPath, 'utf8')) as { works?: SourcedWork[] }
      for (const w of prev.works ?? []) {
        if (w.recording || (w.candidates ?? 0) > 0) done.set(w.entry, w)
      }
      process.stderr.write(`  续跑：台账里已有 ${done.size} 件，跳过它们\n`)
    } catch {
      process.stderr.write('  续跑：台账读不到，从头开始\n')
    }
  }

  /** 逐件落盘（原子替换：写 .tmp 再 rename，避免半截文件）。 */
  const flush = (): void => {
    if (!opts.ledgerPath) return
    const payload = {
      $schema: 'music-sources-batch/v1',
      generated_at: new Date().toISOString(),
      source: 'Wikimedia Commons',
      note: '署名取自 File: 页 wikitext（许可模板的 author 优先），不采信 extmetadata.Artist；许可与直链逐件登记，sha256 待下载时补。',
      works: out,
    }
    const tmp = `${opts.ledgerPath}.tmp`
    writeFileSync(tmp, JSON.stringify(payload, null, 1), 'utf8')
    renameSync(tmp, opts.ledgerPath)
  }

  for (const r of rows.slice(1)) {
    const entry = r[iEntry] ?? ''
    const composer = (r[iComp] ?? '').trim()
    const work = (r[iWork] ?? '').trim()
    n++
    let prev: SourcedWork | undefined = done.get(entry)
    if (prev) {
      // 台账里已有这条：**该跳过的跳过，但署名未知的要修**。
      //
      // 为什么要修：署名是**读网页**得来的，读网页会 429。读失败不等于公有
      // 领域——第一版把失败写成「Public domain」，于是台账里混进了 16 条伪造
      // 的许可声明。续跑时顺手把这些条目的出处页重读一遍（只读页，不重检索：
      // 检索贵、读页便宜），修好再落盘。
      // 旧的选中项若是**广播引子**或**MIDI 乐谱**，它不能当录音进成片：
      // 这一件要**重查**（不进「原样带过来」那一支）。
      const prevIsBad = !!prev.recording
        && (isRadioStub(prev.recording.title) || isScoreOnly(prev.recording.title))
      if (prevIsBad) {
        // 旧选中项不可用 → 这一件要**重查**：把它从「已完成」里摘掉，
        // **不落回台账**，直接掉到下面的检索分支（第一版在这里 `continue`
        // 了，于是这一件被整条丢掉——台账少了 19 件）。
        done.delete(entry)
        process.stderr.write(`  [${n}] ${entry} 旧选中项不可用（${
          isScoreOnly(prev.recording!.title) ? 'MIDI 乐谱' : '广播引子'
        }）→ 重查\n`)
        prev = undefined
      } else if (prev.recording && needsAttribution([prev]).length > 0) {
        try {
          // **不重检索**——检索贵（要走 Commons 全文搜索），而要修的只是
          // 出处页上的一行署名。直接拿台账里那条的标题重读出处页。
          const cand: AudioCandidate = {
            title: prev.recording.title,
            url: prev.recording.notes?.replace(/^直链 /, '') ?? '',
            pageUrl: prev.recording.url,
            size: 0, duration: prev.durationS, mime: 'audio/ogg',
            license: prev.license ?? '', licenseUrl: prev.recording.license_url,
            attribution: '',
          }
          const filled = await (opts.attributionFn ?? ((cs: AudioCandidate[]) => fillAttribution(cs, opts)))([cand])
          const c2 = filled[0] ?? cand
          const fixed: SourcedWork = {
            ...prev,
            attribution: c2.attribution || null,
            attributionError: c2.attributionError ?? '',
            recording: prev.recording
              ? { ...prev.recording, attribution: c2.attribution, attribution_error: c2.attributionError ?? '' }
              : null,
          }
          out.push(fixed)
          done.set(entry, fixed)
          process.stderr.write(`  [${n}] ${entry} 修署名：${fixed.attribution || '（仍失败）'}\n`)
          flush()
          continue
        } catch (e) {
          out.push(prev)
          process.stderr.write(`  [${n}] ${entry} 修署名失败：${String((e as Error).message ?? e).slice(0, 80)}\n`)
          continue
        }
      }
      if (prev) {
        out.push(prev)
        process.stderr.write(`  [${n}] ${entry} 跳过（台账已有）\n`)
        continue
      }
      // prev 为空 = 旧选中项不可用 → **落到下面重新检索**（不许 continue）。
    }
    if (!composer || !work) {
      out.push({ entry, composer, work, candidates: 0, usable: 0, recording: null, pageUrl: null, license: null, attribution: null, attributionError: '', durationS: null, error: '表里缺 composer_en / work_en' })
      flush()
      continue
    }
    const id = `${prefix}-${entry.padStart(3, '0')}`
    try {
      const cands = opts.searchFn
        ? await opts.searchFn(composer, work)
        : await searchAudioLadder(composer, work, { limit: opts.limit ?? 8, minDurationSec: opts.minDurationSec, intervalMs: opts.intervalMs })
      const usable = cands.filter((c) => isUsableLicense(c.license))
      // 只给**要选中的那一条**读出处页：逐个候选都读会让整批慢十倍，而
      // 台账只需要选中项的署名。
      // 选择顺序：可许用许可中**已取到署名**的优先——读出处页失败的候选不该
      // 压过能读到署名的（否则台账里会多一条署名未知的选中项）。
      const ranked = [
        ...usable.filter((x) => !x.attributionError),
        ...usable.filter((x) => x.attributionError),
      ]
      let pick = ranked[0] ?? cands[0] ?? null
      if (pick) {
        // 署名接缝可能返回**新对象**（纯函数式实现），所以要接住返回值，
        // 不能假定它原地改。
        const filled = await (opts.attributionFn ?? ((cs: AudioCandidate[]) => fillAttribution(cs, opts)))([pick])
        pick = filled[0] ?? pick
      }
      out.push({
        entry,
        composer,
        work,
        candidates: cands.length,
        usable: usable.length,
        recording: pick ? toLedgerItem(pick, id) : null,
        pickKind: pick ? (isScoreOnly(pick.title) ? 'score' : isRadioStub(pick.title) ? 'stub' : 'recording') : null,
        pageUrl: pick?.pageUrl ?? null,
        license: pick?.license ?? null,
        attribution: pick?.attribution ?? null,
        attributionError: pick?.attributionError ?? '',
        durationS: pick?.duration ?? null,
        affinity: pick ? Number(titleAffinity(pick.title, work).toFixed(2)) : 0,
        error: pick ? undefined : '没有命中音频文件',
      })
    } catch (e) {
      out.push({ entry, composer, work, candidates: 0, usable: 0, recording: null, pageUrl: null, license: null, attribution: null, attributionError: '', durationS: null, error: String((e as Error).message ?? e).slice(0, 200) })
    }
    process.stderr.write(`  [${n}] ${entry} ${composer} ${work} → ${out[out.length - 1]?.license ?? 'none'}\n`)
    flush()
  }
  flush()
  return out
}

/**
 * CLI：`feuille music source-batch <works.csv> [--out ledger.json] [--limit 8]`
 *
 * 产出：台账 JSON（每件作品的命中数、许可、署名、出处页、时长）。
 */
export async function batchMain(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const csvPath = args.positional[0]
  if (!csvPath) {
    console.error('usage: feuille music source-batch <works.csv> [--out ledger.json] [--limit 8] [--resume]')
    return 2
  }
  const outPath = strOpt(args, 'out', 'ledger.json')
  const res = await sourceBatch(csvPath, {
    limit: numOpt(args, 'limit', 8),
    idPrefix: strOpt(args, 'id-prefix', 'src'),
    intervalMs: numOpt(args, 'interval', 1200),
    ledgerPath: outPath,
    resume: args.flags.has('resume'),
  })
  const withRec = res.filter((w) => w.recording).length
  const usable = res.filter((w) => w.usable > 0).length
  const failed = res.filter((w) => w.error).length
  console.log(`source-batch: ${res.length} 件 · 有录音 ${withRec} · 许可白名单内 ${usable} · 失败 ${failed}`)
  console.log(`  → ${outPath}`)
  if (failed) {
    console.error('  有失败项——失败原因逐条写在台账的 error 字段里，别当「没有」读。')
  }
  return 0
}
