// narrate.ts — 旁白分段的 TTS 生成（`feuille music narrate`）。
//
// 为什么单独一个叶子：
//
// 1. **一段一个 mp3**。`feuille karaoke tts` 一次只出一条长音频（词级高亮
//    用），而赏析产线的场景是「旁白 A → 长时间纯聆听 → 旁白 B」——旁白必须
//    拆成可单独摆放的片段，builder 才能把聆听窗口插在中间。
// 2. **不许依赖词边界**。karaoke 那条路要求 edge-tts 回 WordBoundary 事件，
//    缺词边界时 `gen_tts.ts` 的 `fmt2(null)` 会当场炸（`(null).toFixed`）。
//    旁白不需要词边界——只需要声音与时长。
// 3. **标点在源头剥**。旧路的纪律是「调用方剥标点」（SKILL.md 已把它记成
//    已知缺口），这里收口：TTS 输入一律把标点换成空格，字幕用的原文留在
//    narration.json 里不动。
// 4. **内容寻址缓存**。走 `@feuille/core` 的 `synthCached`：改一句只重合成
//    那一句，命中零请求；网络抖动不会进装配环节。
//
// 输入（narration.json）：
//
//   {
//     "voices": { "zh-CN": "zh-CN-XiaoxiaoNeural", "en-US": "en-US-JennyNeural" },
//     "segments": [
//       { "id": "s02-hook-a", "locale": "zh-CN", "text": "这一段不解释，先让你听。" }
//     ]
//   }
//
// 产物：
//   <out>/<id>.mp3                    旁白音频
//   <out>/narration-durations.json    { "<id>": 秒 }（实测，不是估算）
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { FeuilleError } from '@feuille/core'
import { synthCached } from '@feuille/core'

/** 一条旁白片段。 */
export interface NarrationSegment {
  /** 片段 id（同时是产出的文件名）。 */
  id: string
  /** 语种（zh-CN / en-US …）。 */
  locale: string
  /** 原文（**带标点**，给字幕用）。 */
  text: string
  /** 覆盖该语种的默认声线。 */
  voice?: string
}

/** narration.json 的顶层。 */
export interface NarrationSpec {
  /** 语种 → 声线 id。 */
  voices?: Record<string, string>
  /** 语种 → 语速调整（如 `-8%`）。 */
  rates?: Record<string, string>
  /** 语种 → 音高调整（如 `+0Hz`）。 */
  pitches?: Record<string, string>
  segments: NarrationSegment[]
}

/**
 * 剥掉全部标点（→ 空格），压掉多余空白。
 *
 * 为什么要剥：edge-tts 遇到密集标点时，词边界事件会变得稀疏且不规则；
 * 更要紧的是，句末标点会被读成停顿，把整段时长拉长。与其让每个调用方
 * 各剥一次（漏一处就崩），不如在源头收口。
 *
 * 保留：字母、数字、空格（含全角空格）、连字符与撇号（`L'homme` 的撇号
 * 是词内字符，剥掉会把它劈成两个词）。
 */
export function stripPunctuation(text: string): string {
  return text
    .replace(/[^\p{L}\p{N}\s'’\-]/gu, ' ')
    .replace(/[\s　]+/g, ' ')
    .trim()
}

/** 读 narration.json 并做基本校验。 */
export function parseNarrationSpec(raw: string): NarrationSpec {
  const spec = JSON.parse(raw) as NarrationSpec
  if (!spec || !Array.isArray(spec.segments) || spec.segments.length === 0) {
    throw new FeuilleError('narration.json 没有 segments（或不是数组）')
  }
  const seen = new Set<string>()
  for (const s of spec.segments) {
    if (!s.id) throw new FeuilleError('narration 片段缺 id')
    if (seen.has(s.id)) throw new FeuilleError(`narration 片段 id 重复：${s.id}`)
    seen.add(s.id)
    if (!s.locale) throw new FeuilleError(`narration 片段 ${s.id} 缺 locale`)
    if (!s.text || !s.text.trim()) throw new FeuilleError(`narration 片段 ${s.id} 的 text 是空的`)
  }
  return spec
}

/** 一条旁白的生成结果。 */
export interface NarratedSegment {
  id: string
  locale: string
  /** 产出的 mp3 路径。 */
  file: string
  /** 实测时长（秒）。 */
  duration: number
  /** 缓存命中还是新合成。 */
  state: 'HIT' | 'NEW'
  /** 送去合成的文本（已剥标点）——落盘备查，便于复核。 */
  ttsText: string
}

/**
 * 逐段生成旁白。
 *
 * 全部落盘后再返回——**中途失败不留半套产物**：成品是「一堆 mp3 + 一张
 * 时长表」，缺一段就会让 builder 的时长对账变成玄学。
 */
export async function narrateSegments(
  spec: NarrationSpec,
  opts: { outDir: string; cacheDir?: string },
): Promise<NarratedSegment[]> {
  const outDir = opts.outDir
  const cacheDir = opts.cacheDir ?? join(outDir, '.cache')
  mkdirSync(outDir, { recursive: true })
  mkdirSync(cacheDir, { recursive: true })

  const results: NarratedSegment[] = []
  for (const seg of spec.segments) {
    const voice = seg.voice ?? spec.voices?.[seg.locale]
    if (!voice) {
      throw new FeuilleError(
        `旁白 ${seg.id}（${seg.locale}）没有声线：在片段里给 voice，`
        + '或在 narration.json 的 voices 里给该语种配一个',
      )
    }
    const rate = spec.rates?.[seg.locale] ?? '+0%'
    const pitch = spec.pitches?.[seg.locale] ?? '+0Hz'
    const ttsText = stripPunctuation(seg.text)
    if (!ttsText) {
      throw new FeuilleError(`旁白 ${seg.id} 剥掉标点后没有可念的内容`)
    }
    const hit = await synthCached(ttsText, voice, rate, pitch, cacheDir)
    const dest = join(outDir, `${seg.id}.mp3`)
    // 缓存命中时 mp3 已在缓存目录里；复制一份到 outDir，让 project.json
    // 引用的是**项目内**的路径（缓存目录不进交付）。
    if (hit.mp3 !== dest) copyFileSync(hit.mp3, dest)
    results.push({
      id: seg.id, locale: seg.locale, file: dest,
      duration: hit.duration, state: hit.state, ttsText,
    })
  }

  const durations: Record<string, number> = {}
  const detail: Record<string, { locale: string; duration: number; state: string; ttsText: string }> = {}
  for (const r of results) {
    durations[r.id] = Number(r.duration.toFixed(3))
    detail[r.id] = {
      locale: r.locale, duration: Number(r.duration.toFixed(3)),
      state: r.state, ttsText: r.ttsText,
    }
  }
  writeFileSync(
    join(outDir, 'narration-durations.json'),
    JSON.stringify({ durations, detail }, null, 1),
    'utf8',
  )
  return results
}

/** CLI 入口：`feuille music narrate <narration.json> [--out <dir>] [--cache <dir>]`。 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const specPath = args.positional[0]
  if (!specPath) {
    console.error('usage: feuille music narrate <narration.json> [--out <dir>] [--cache <dir>]')
    return 2
  }
  if (!existsSync(specPath)) {
    console.error(`narration.json 读不到：${specPath}`)
    return 2
  }
  const outDir = args.opts['out'] ?? 'tts'
  const cacheDir = args.opts['cache']
  const spec = parseNarrationSpec(readFileSync(specPath, 'utf8'))
  const res = await narrateSegments(spec, { outDir, cacheDir })
  const hits = res.filter((r) => r.state === 'HIT').length
  const total = res.reduce((a, r) => a + r.duration, 0)
  console.log(`narrate: ${res.length} 段 · 命中缓存 ${hits} · 新合成 ${res.length - hits}`
    + ` · 合计 ${total.toFixed(1)}s`)
  console.log(`  → ${outDir}/narration-durations.json`)
  return 0
}

// ---- 极简旗标解析（与本包其它叶子同一口径：旗标显式，不猜） ----

interface ParsedArgs {
  positional: string[]
  opts: Record<string, string>
  flags: Set<string>
}

function parseArgs(argv: readonly string[]): ParsedArgs {
  const positional: string[] = []
  const opts: Record<string, string> = {}
  const flags = new Set<string>()
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (!a.startsWith('--')) {
      positional.push(a)
      continue
    }
    const body = a.slice(2)
    const eq = body.indexOf('=')
    if (eq >= 0) {
      opts[body.slice(0, eq)] = body.slice(eq + 1)
      continue
    }
    const next = argv[i + 1]
    if (next !== undefined && !next.startsWith('--')) {
      opts[body] = next
      i++
    } else {
      flags.add(body)
    }
  }
  return { positional, opts, flags }
}
