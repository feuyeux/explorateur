// gen_tts.ts — 词级卡拉OK时间线的 TTS 生成（karaoke-video/scripts/gen_tts.py 的 TS 归流）。
//
// voices.json: {"tts_dir": "tts", "langs": [{locale, voice, text, tokens, persona, latin, gender}, …]}
//   - `text`   — 精确的 TTS 输入短语（允许空格）
//   - `tokens` — 显示 token，是 `text` 的**连续字符区间**（token 间的空格不参与匹配）
//
// 每语种产出：
//   <tts_dir>/<locale>.mp3    语音（24 kHz 单声道 mp3）
//   <tts_dir>/<locale>.json   词边界 + 显示 token 时间（秒）
//
// 卡拉OK语义：edge-tts 的 WordBoundary 事件可能横跨多个显示 token
// （zh「一本」盖住 一+本）。边界时长按字符位置**按比例切分**，每个 token
// 得到自己的 start/end，高亮可以逐字切换。
//
// 归流决定：edge-tts 协议（握手/令牌/403 偏斜重试）消费 @feuille/core tts
// 的唯一实现——这里直接吃裸 `stream()`（音频块 + WordBoundary 事件），
// **不带** synthOnce 的无词兜底（原版 gen_tts.py 也没有：某语种真没有
// 词边界事件时 words 为空、token 时间为 null，与 Python 行为一致）。
// 原版没有缓存（poetry/publishing 侧的平行缓存是另一族，不在 karaoke），
// 照原样不引入。
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { stream } from '@feuille/core'

/** Python len()/下标按码点计——用码点数组镜像。 */
type Word = { w: string; t: number; d: number }
export type TokenTiming = { text: string; start: number | null; end: number | null }

/** 把（可能横跨多个 token 的）词边界映射到显示 token 上。
 *
 * 累积 token 流的非空格字符；每个边界盖住 len(word) 个字符。某 token 的
 * start = 边界 start + 该边界内已消费字符的按比例偏移；end = 边界 end。 */
export function tokenTimings(tokens: readonly string[], words: readonly Word[]): TokenTiming[] {
  const stream = [...tokens.join('')]
  const spans: Array<[number, number, number]> = [] // [start_char, end_char, token_idx) 流坐标
  let pos = 0
  for (let i = 0; i < tokens.length; i++) {
    const t = [...tokens[i]!]
    spans.push([pos, pos + t.length, i])
    pos += t.length
  }
  // tokens 必须是输入的连续字符区间（Python assert 同款：违反直接炸）
  if (pos !== stream.length) {
    throw new Error('tokens must be consecutive char ranges of the input')
  }

  const tokStart: Array<number | null> = new Array(tokens.length).fill(null)
  const tokEnd: Array<number | null> = new Array(tokens.length).fill(null)
  let cpos = 0
  for (const w of words) {
    const wl = Math.max(1, [...w['w']].length)
    while (cpos < stream.length && stream[cpos] === ' ') cpos++
    let cov = wl
    const touched: number[] = []
    while (cov > 0 && cpos < stream.length) {
      if (stream[cpos] === ' ') {
        cpos++
        continue
      }
      const hit = spans.find(([a, b]) => a! <= cpos && cpos < b!)
      // 命中不了 = words 覆盖的字符超出 token 流（边界词与显示 token 错位）；
      // Python next() 在这里 StopIteration 炸掉——同款直接炸。
      if (!hit) throw new Error('word boundary falls outside the token stream')
      const [a, b, idx] = hit as [number, number, number]
      const take = Math.min(cov, b - cpos)
      const into = wl - cov // 该边界已消费的字符数
      if (tokStart[idx] === null) {
        tokStart[idx] = w['t'] + w['d'] * (into / wl)
      }
      touched.push(idx)
      cov -= take
      cpos += take
    }
    for (const idx of touched) tokEnd[idx] = w['t'] + w['d']
  }

  return tokens.map((t, i) => ({ text: t, start: tokStart[i] ?? null, end: tokEnd[i] ?? null }))
}

async function gen(outDir: string, lang: Record<string, unknown>): Promise<Record<string, unknown>> {
  const req = {
    text: lang['text'] as string,
    voice: lang['voice'] as string,
    // 原版 edge_tts.Communicate(text, voice) 不带 rate/pitch → 缺省 +0%
    rate: '+0%',
    pitch: '+0%',
  }
  const chunks: Uint8Array[] = []
  const words: Word[] = []
  for await (const chunk of stream(req)) {
    if (chunk.type === 'audio') {
      chunks.push(chunk.data)
    } else if (chunk.type === 'WordBoundary') {
      words.push({ w: chunk.text, t: chunk.offset / 1e7, d: chunk.duration / 1e7 })
    }
  }
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const mp3 = new Uint8Array(total)
  let o = 0
  for (const c of chunks) {
    mp3.set(c, o)
    o += c.length
  }
  writeFileSync(join(outDir, `${lang['locale']}.mp3`), mp3)

  const tk = tokenTimings(lang['tokens'] as string[], words)
  // 键序 = Python dict 插入序（JSON 落盘逐键对齐）
  const data: Record<string, unknown> = {
    locale: lang['locale'],
    persona: lang['persona'] ?? null,
    latin: lang['latin'] ?? null,
    gender: lang['gender'] ?? null,
    text: lang['text'],
    words,
    tokens: tk,
  }
  writeFileSync(join(outDir, `${lang['locale']}.json`),
    JSON.stringify(data, null, 1), 'utf8')
  return data
}

/** `python .2f`：null 会当场 TypeError（Python f'{None:.2f}' 同款炸法）。 */
function fmt2(v: number | null): string {
  return (v as number).toFixed(2)
}

/** CLI 入口：`feuille karaoke tts <voices.json> [tts_out_dir]`。
 * 原版直接吃 sys.argv[1]/[2]（无 argparse、无 -h）——镜像之；缺 cfg 在
 * Python 是 IndexError 裸炸，这里按叶子统一口径报 usage + 2。 */
export async function main(argv: string[]): Promise<number> {
  if (argv.length < 1) {
    console.error('usage: feuille karaoke tts <voices.json> [tts_out_dir]')
    return 2
  }
  const cfg = JSON.parse(readFileSync(argv[0]!, 'utf8')) as Record<string, unknown>
  const outDir = argv[1] ?? (cfg['tts_dir'] as string | undefined) ?? 'tts'
  mkdirSync(outDir, { recursive: true })
  for (const lang of cfg['langs'] as Array<Record<string, unknown>>) {
    const d = await gen(outDir, lang)
    const toks = (d['tokens'] as TokenTiming[])
      .map((t) => `${t['text']} ${fmt2(t['start'])}-${fmt2(t['end'])}`)
      .join(' | ')
    console.log(`${lang['locale']}: ${toks}`)
  }
  return 0
}
