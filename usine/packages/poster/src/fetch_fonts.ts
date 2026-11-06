// fetch_fonts.ts — Google Fonts 逐字符子集抓取 → fonts.css（base64 woff2 内嵌）。
// （promoted from skills/one-page-poster/scripts/fetch_fonts.py，P5-7e 归流）
//
// 由 fonts.json 驱动（path = argv[0] 或缺省 ./fonts.json）：
// [
//   {"family": "OBS Deva", "google": "Noto+Sans+Devanagari:wght@500",
//    "text": "एक किताब हिन्दी", "classes": ["f-deva"]}
// ]
// - "family"：海报 CSS 里的 @font-face 名（字体栈先嵌这套）
// - "google"：css2 family spec（空格写 +，字重 ;wght@）
// - "text"：该 family 会渲染到的每一个字符（页面正文 + 标注 + 图例；空格隐含）
// - "classes"：可选——用该 family 渲字的 CSS 类（audit_charset 的家族归属用）
//
// 输出：fonts.css 写到 fonts.json 旁。
import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36'

/** Python `"".join(sorted(set(s) - {" ", "\n"})) + " "`：去空格/换行、去重、按码点排序 + 尾随空格。 */
export function uniq(s: string): string {
  return (
    [...new Set([...s])]
      .filter((c) => c !== ' ' && c !== '\n')
      .sort((a, b) => a.codePointAt(0)! - b.codePointAt(0)!)
      .join('') + ' '
  )
}

/** Python urllib.parse.quote(s)（safe='/'）：字母数字与 `_.~/` 之外全转义（大写十六进制）。 */
export function pyQuote(s: string): string {
  let out = ''
  for (const ch of s) {
    if (/[A-Za-z0-9_.\-~/]/.test(ch)) out += ch
    else {
      for (const b of Buffer.from(ch, 'utf8')) out += '%' + b.toString(16).toUpperCase().padStart(2, '0')
    }
  }
  return out
}

interface FontSpec {
  family: string
  google: string
  text: string
}

/**
 * 网络接缝（给门禁用）。默认走真 `fetch`。
 *
 * 为什么要这个接缝：`pnpm verify` 里有两处真联网取 Google Fonts 的用例，
 * 结果门禁的健康度取决于「今天 fonts.googleapis.com 通不通」——2026-11-06
 * 实测同一个提交在 10 秒超时下直接 ConnectTimeout，整条 verify 变红，而代码
 * 一行没改。那是纪律 12 明写禁止的「让验收长得像环境可用性测试」。
 *
 * 接缝的用法是**双向**的：
 * - 门禁跑注入的假 fetch（离线、确定性），仍然覆盖 url 构造 / 解析 / base64
 *   内嵌 / family 改名这些真逻辑；
 * - `FEUILLE_LIVE=1` 时跑真网络，作为独立的 LIVE 面。
 *
 * 注入的是 `fetch` 而不是「返回 css 的桩」，因为要覆盖的正是**两次 HTTP 往返
 * 的顺序**（先 css2 拿 @font-face，再逐个 woff2 直链）。
 */
export type FetchLike = (url: string, init: { headers: Record<string, string>; signal: AbortSignal }) => Promise<{
  ok: boolean
  status: number
  statusText: string
  text: () => Promise<string>
  arrayBuffer: () => Promise<ArrayBuffer>
}>

let fetchOverride: FetchLike | null = null

/** 测试专用：注入 fetch 接缝；传 null 还原。 */
export function setFetchForTests(f: FetchLike | null): void {
  fetchOverride = f
}

export async function main(argv: string[]): Promise<number> {
  const specPath = argv[0] !== undefined ? argv[0]! : 'fonts.json'
  const spec = JSON.parse(readFileSync(specPath, 'utf8')) as FontSpec[]
  const doFetch: FetchLike = fetchOverride ?? (fetch as unknown as FetchLike)
  const cssOut: string[] = []
  for (const ent of spec) {
    const fam = ent['family']!
    const text = ent['text']!
    const url = `https://fonts.googleapis.com/css2?family=${ent['google']}&text=${pyQuote(uniq(text))}&display=swap`
    const res = await doFetch(url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(30000) })
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}: ${url}`)
    const css = await res.text()
    const blocks = css.match(/@font-face\s*\{[^}]+\}/g) ?? []
    if (blocks.length === 0) {
      console.log(`!! no face for ${fam}`)
      continue
    }
    for (const b of blocks) {
      const m = b.match(/url\((https:\/\/[^)]+)\)\s*format\('woff2'\)/)!
      const wght = b.match(/font-weight:\s*(\d+)/)![1]
      const dataRes = await doFetch(m[1]!, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(30000) })
      if (!dataRes.ok) throw new Error(`HTTP ${dataRes.status} ${dataRes.statusText}: ${m[1]}`)
      const data = Buffer.from(await dataRes.arrayBuffer())
      const b64 = data.toString('base64')
      const block = b
        .replace(/url\([^)]+\)\s*format\('woff2'\)/g, `url(data:font/woff2;base64,${b64}) format('woff2')`)
        .replace(/font-family:\s*'[^']+'/g, `font-family: '${fam}'`)
      cssOut.push(block)
      console.log(`${fam} w${wght}: ${Math.floor(data.length / 1024)} KB`)
    }
  }

  const out = join(dirname(specPath), 'fonts.css')
  writeFileSync(out, cssOut.join('\n'), 'utf-8')
  console.log(`\nwrote ${out} (${Math.floor(statSync(out).size / 1024)} KB)`)
  return 0
}
