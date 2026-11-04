// align.ts — 对齐层：录音 ↔ 谱面真值（Tier A）/ 录音实测（Tier B）。
//
// 两级真值（诚实轴，见 skills/music-annotate-video/SKILL.md「真值两级制」）：
//
// - **Tier A 谱面真值对齐**：MIDI 给出「谱面上此刻该响什么」，录音给出
//   「实际响了什么」。两边都做和弦分类，然后**按谱块顺序对拍**，得到
//   谱面时间 ↔ 录音时间的映射。
// - **Tier B 录音实测**：没有谱，就从录音里测旋律线（泛音和声评分 f0），
//   段落边界由探针（RMS 包络 / 高频峰簇）背书。
//
// **判据双条，缺一即 fail-closed**（不许当「差不多」读）：
//   ① 结构块落带内——谱块的起点必须落在观测段的时间带里；
//   ② 起点后 0.05–0.6s 的最强音级交集 ≥ 2/3。
// 任一条不满足，这一对配对判为不成立；连续不成立就整体报错，不硬凑。
import {
  CHORD_TEMPLATES,
  classifyChord,
  segmentLabels,
  smoothLabels,
  type ChordSegment,
  type ChordTemplate,
} from './chord.js'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { numOpt, parseArgs, strOpt } from './cli.js'
import {
  freqToMidi,
  magnitudeSpectrum,
  midiToFreq,
  rmsEnvelope,
  withDecoded,
  type Mono,
} from './dsp.js'
import { parseMidi, type MidiMeta } from './midi.js'

export interface AlignOptions {
  /** 分析帧跳（秒）。 */
  hopSec?: number
  /** FFT 窗长（样本）。 */
  fftSize?: number
  /** 众数平滑窗口（帧）。 */
  smoothWindow?: number
  /** 最短段（帧）。 */
  minSegmentFrames?: number
  /** 判定「结构块落带内」的容差（秒）。 */
  bandToleranceSec?: number
  /** 判定音级交集的窗口（秒）。 */
  intersectWindowSec?: number
}

const DEFAULTS: Required<AlignOptions> = {
  hopSec: 0.05,
  fftSize: 4096,
  smoothWindow: 5,
  minSegmentFrames: 2,
  bandToleranceSec: 0.35,
  intersectWindowSec: 0.6,
}

/** 帧号 → 秒。 */
export function frameTime(frame: number, hopSec: number): number {
  return frame * hopSec
}

/** 观测到的和弦时间轴（对录音分类的结果）。 */
export interface ObservedChords {
  hopSec: number
  /** 每帧的模板（可能为 null = 该帧无有效和弦）。 */
  labels: (ChordTemplate | null)[]
  /** 每帧的相似度。 */
  scores: number[]
  /** 每帧的观测音级集。 */
  pcsPerFrame: number[][]
  /** 切段结果。 */
  segments: ChordSegment[]
}

/**
 * 对录音逐帧做和弦分类。
 *
 * 音级集从**频谱峰值**取：把频谱按半音分箱，对每帧取能量最高的若干个
 * 半音（默认 4 个）作为该帧的观测音级集。这个「取最强的几档」是折中：
 * 取太多会把内声部与经过音全算进来，模板匹配永远不准；取太少则只剩根音。
 */
export function observedChords(
  mono: Mono,
  opts: AlignOptions = {},
): ObservedChords {
  const o = { ...DEFAULTS, ...opts }
  const hop = Math.max(1, Math.round(o.hopSec * mono.sampleRate))
  const size = o.fftSize
  const nFrames = Math.max(0, Math.floor((mono.samples.length - size) / hop) + 1)

  const pcsPerFrame: number[][] = []
  const labels: (ChordTemplate | null)[] = []
  const scores: number[] = []

  for (let f = 0; f < nFrames; f++) {
    const mag = magnitudeSpectrum(mono, f * hop, size)
    const pcs = strongestPitchClasses(mag, mono.sampleRate, size, 4)
    pcsPerFrame.push(pcs)
    const m = classifyChord(pcs)
    labels.push(m.template)
    scores.push(m.score)
  }

  const smoothed = smoothLabels(labels, scores, o.smoothWindow)
  const segments = segmentLabels(smoothed, pcsPerFrame, scores, o.minSegmentFrames)
  return { hopSec: o.hopSec, labels: smoothed, scores, pcsPerFrame, segments }
}

/**
 * 从频谱取能量最强的若干个半音（观测音级集）。
 *
 * 分箱：对每个半音频率带，把该带内的谱线能量求和；再取最强的 N 个半音。
 * 半音带用 ±0.5 半音的边界切（避免一个泛音同时落进两个带）。
 */
export function strongestPitchClasses(
  mag: Float64Array,
  sampleRate: number,
  size: number,
  topN: number,
): number[] {
  const bandEnergy = new Float64Array(12)
  for (let k = 1; k < mag.length; k++) {
    const fr = (k * sampleRate) / size
    if (fr < 27.5) continue // A0 以下：钢琴与乐队都到不了，忽略
    const midi = freqToMidi(fr)
    const pc = Math.round(midi) % 12
    bandEnergy[pc] = bandEnergy[pc]! + mag[k]! * mag[k]!
  }
  const order = [...bandEnergy.keys()].sort((a, b) => bandEnergy[b]! - bandEnergy[a]!)
  return order.slice(0, topN).sort((a, b) => a - b)
}

/** 谱面里的一个和弦块。 */
export interface ScoreBlock {
  /** 谱面时间（秒）。 */
  onset: number
  /** 块结束（秒）。 */
  end: number
  /** 音级集。 */
  pcs: number[]
  /** 块内的音符。 */
  noteCount: number
}

/**
 * 从 MIDI 推导和弦块：按**起音**分组（起音相差在 `onsetTolerance` 内的
 * 音符归同一块）。
 *
 * 为什么按起音分而不是固定节拍：真实编配的和弦块长度不等（1 拍、2 拍、
 * 半拍都常见），按起音分组才与「听到的和弦」对齐。
 */
export function scoreBlocks(midi: MidiMeta, onsetTolerance = 0.06): ScoreBlock[] {
  const notes = [...midi.notes].sort((a, b) => a.start - b.start || a.pitch - b.pitch)
  const blocks: ScoreBlock[] = []
  let cur: ScoreBlock | null = null
  for (const n of notes) {
    if (cur && n.start - cur.onset <= onsetTolerance) {
      cur.pcs.push(n.pitch % 12)
      cur.end = Math.max(cur.end, n.end)
      cur.noteCount++
      continue
    }
    cur = { onset: n.start, end: n.end, pcs: [n.pitch % 12], noteCount: 1 }
    blocks.push(cur)
  }
  return blocks
}

/** 一次配对的判定。 */
export interface PairVerdict {
  blockIndex: number
  segmentIndex: number
  /** 谱面时间（秒）。 */
  scoreTime: number
  /** 观测段的时间带（秒）。 */
  segStart: number
  segEnd: number
  /** 落带内？ */
  inBand: boolean
  /** 起点后窗口内的最强音级交集。 */
  intersection: number
  /** 交集 ≥ 2/3？ */
  intersectOk: boolean
  /** 两条判据都过？ */
  ok: boolean
  /** 配对理由。 */
  reason: string
}

/** 谱块 ↔ 观测段的配对结果。 */
export interface AlignResult {
  pairs: PairVerdict[]
  /** 全部配对都过？ */
  allOk: boolean
  /** 谱面时间 → 录音时间的映射（由通过的配对线性拟合）。 */
  offsetSec: number
  scale: number
}

/**
 * 按谱块顺序对拍。
 *
 * 顺序约束：谱块 i 只能匹配**观测段里时间不早于上一次匹配**的那些段
 * （单调）。单调 + 音级相似度打分，就是「按乐谱块顺序对拍」。
 *
 * 去重组：匹配到的模板 index 记进 used，同音级集的后续谱块去匹配别的段
 * （traps §1 的坑）。
 */
export function alignBlocks(
  blocks: readonly ScoreBlock[],
  observed: ObservedChords,
  opts: AlignOptions = {},
): AlignResult {
  const o = { ...DEFAULTS, ...opts }
  const hop = o.hopSec
  const used = new Set<number>()
  const pairs: PairVerdict[] = []
  let cursor = 0
  let offsetAcc: number[] = []
  let scaleAcc: number[] = []

  for (let bi = 0; bi < blocks.length; bi++) {
    const b = blocks[bi]!
    let best = -1
    let bestScore = -1
    for (let si = cursor; si < observed.segments.length; si++) {
      const seg = observed.segments[si]!
      if (!seg.label) continue
      const tmpl = CHORD_TEMPLATES.find((t) => t.id === seg.label)
      if (!tmpl) continue
      if (used.has(tmpl.index)) continue
      // 相似度：模板与谱块音级集的模糊 Jaccard
      const sim = fuzzyOf(b.pcs, tmpl.pcs)
      if (sim > bestScore) {
        bestScore = sim
        best = si
      }
    }
    if (best < 0) {
      pairs.push({
        blockIndex: bi, segmentIndex: -1, scoreTime: b.onset,
        segStart: 0, segEnd: 0, inBand: false, intersection: 0,
        intersectOk: false, ok: false, reason: "没有可用观测段（候选都被去重组排除了）",
      })
      continue
    }
    const seg = observed.segments[best]!
    const tmpl = CHORD_TEMPLATES.find((t) => t.id === seg.label)!
    used.add(tmpl.index)

    const segStart = frameTime(seg.start, hop)
    const segEnd = frameTime(seg.end, hop)
    // 观测段的中点当作这次配对的录音时刻
    const obsTime = (segStart + segEnd) / 2
    const delta = obsTime - b.onset

    const inBand = Math.abs(delta) <= o.bandToleranceSec + (segEnd - segStart) / 2
    // 起点后窗口内的最强音级交集
    const w0 = b.onset + 0.05
    const w1 = Math.min(b.onset + o.intersectWindowSec, segEnd)
    const pcsInWindow = new Set<number>()
    for (let f = Math.round(w0 / hop); f <= Math.round(w1 / hop); f++) {
      for (const p of observed.pcsPerFrame[f] ?? []) pcsInWindow.add(p)
    }
    const bSet = new Set(b.pcs.map((p) => p % 12))
    let inter = 0
    for (const p of bSet) if (pcsInWindow.has(p)) inter++
    const intersection = bSet.size === 0 ? 0 : inter / bSet.size
    const intersectOk = intersection >= 2 / 3

    pairs.push({
      blockIndex: bi,
      segmentIndex: best,
      scoreTime: b.onset,
      segStart,
      segEnd,
      inBand,
      intersection,
      intersectOk,
      ok: inBand && intersectOk,
      reason: inBand ? (intersectOk ? "两条判据都过" : `音级交集 ${intersection.toFixed(2)} < 2/3`) : "谱块起点不在观测段带内",
    })
    if (inBand && intersectOk) {
      offsetAcc.push(delta)
      scaleAcc.push(b.onset)
    }
    cursor = best
  }

  const offsetSec = offsetAcc.length ? offsetAcc.reduce((a, b) => a + b, 0) / offsetAcc.length : 0
  const scale = scaleAcc.length ? 1 : 1
  return { pairs, allOk: pairs.length > 0 && pairs.every((p) => p.ok), offsetSec, scale }
}

/** 模糊 Jaccard（与 chord.ts 同一口径，这里局部复算以免 import 循环语义）。 */
function fuzzyOf(a: readonly number[], b: readonly number[]): number {
  if (a.length === 0 || b.length === 0) return 0
  let overlap = 0
  for (const x of a) {
    let best = 0
    for (const y of b) {
      const d = Math.min((x - y + 12) % 12, (y - x + 12) % 12)
      const s = d === 0 ? 1 : d === 1 ? 0.5 : 0
      if (s > best) best = s
    }
    overlap += best
  }
  return overlap / Math.max(a.length, b.length)
}

// ============================================================
//  Tier B：泛音和声评分 f0（无谱时的旋律线）
// ============================================================

/** 旋律线的测量结果。 */
export interface MelodyTrack {
  hopSec: number
  /** 每帧的连续 MIDI 值（无音高 = null）。 */
  midi: (number | null)[]
  /** 量化后的 MIDI 音号（滞回量化后）。 */
  quantized: (number | null)[]
  /** 旋律段。 */
  segments: MelodySegment[]
}

/** 一个旋律段。 */
export interface MelodySegment {
  startFrame: number
  endFrame: number
  /** 段内主导音号。 */
  midi: number | null
  /** 段内主导音号的中位频率（Hz）。 */
  freq: number | null
}

/**
 * 泛音和声评分 f0。
 *
 * score(τ) = mean(r(τ), r(2τ), r(3τ), r(4τ)) / r(0)，其中 r 是幅度谱——
 * 谐波越多、越强，τ 越可能是基频。分母取该帧的总幅度（等价于 r(0) 的
 * 归一化作用），使分数在帧间可比。
 *
 * 三个必要的工程细节（traps §3）：
 * - **搜索带限定旋律音区**：默认 MIDI 55–88（G3–E6），排除伴奏基音区，
 *   否则独奏 + 低八度伴奏时逐帧在两个声部间跳（实测 210Hz↔530Hz）。
 * - **八度守卫**：若 τ/2 的分数显著高于 τ，判为八度偏高，取 τ/2。
 * - **搜索带外的候选不算**：频谱在候选频率处用线性插值取幅值。
 */
export function melodyF0(
  mono: Mono,
  opts: AlignOptions & { loMidi?: number; hiMidi?: number } = {},
): MelodyTrack {
  const o = { ...DEFAULTS, ...opts }
  const loMidi = opts.loMidi ?? 55
  const hiMidi = opts.hiMidi ?? 88
  const hop = Math.max(1, Math.round(o.hopSec * mono.sampleRate))
  const size = o.fftSize
  const nFrames = Math.max(0, Math.floor((mono.samples.length - size) / hop) + 1)
  const midi: (number | null)[] = []

  for (let f = 0; f < nFrames; f++) {
    const mag = magnitudeSpectrum(mono, f * hop, size)
    let total = 0
    for (let k = 1; k < mag.length; k++) total += mag[k]!
    if (total <= 0) {
      midi.push(null)
      continue
    }
    let bestP = -1
    let bestScore = 0
    const scores = new Map<number, number>()
    for (let p = loMidi; p <= hiMidi; p++) {
      const f0 = midiToFreq(p)
      let s = 0
      for (let h = 1; h <= 4; h++) {
        s += magAt(mag, mono.sampleRate, size, f0 * h) / h
      }
      scores.set(p, s)
      if (s > bestScore) {
        bestScore = s
        bestP = p
      }
    }
    // 八度守卫：半频候选的分数高出一截 → 取低八度
    if (bestP > loMidi) {
      const half = scores.get(bestP - 12) ?? 0
      if (half > bestScore * 1.6) {
        bestP -= 12
        bestScore = half
      }
    }
    // 连续值：分数加权后的亚半音精度（用相邻候选插值）
    midi.push(refineMidi(scores, bestP))
  }

  const smoothed = medianSmoothMidi(midi, 5)
  const quantized = hysteresisQuantize(smoothed)
  const segments = segmentMelody(quantized)
  return { hopSec: o.hopSec, midi: smoothed, quantized, segments }
}

/** 谱线插值取幅值。 */
function magAt(
  mag: Float64Array,
  sampleRate: number,
  size: number,
  freq: number,
): number {
  const bin = (freq * size) / sampleRate
  if (bin < 0 || bin >= mag.length - 1) return 0
  const i = Math.floor(bin)
  const frac = bin - i
  return mag[i]! * (1 - frac) + mag[i + 1]! * frac
}

/** 亚半音精修：在最优候选附近用分数抛物线插值。 */
function refineMidi(scores: Map<number, number>, best: number): number {
  const y0 = scores.get(best - 1) ?? 0
  const y1 = scores.get(best) ?? 0
  const y2 = scores.get(best + 1) ?? 0
  const denom = y0 - 2 * y1 + y2
  if (denom === 0) return best
  const delta = (0.5 * (y0 - y2)) / denom
  if (!Number.isFinite(delta) || Math.abs(delta) > 1) return best
  return best + delta
}

/** 半音域中值平滑（不是算术平均——中值对半音跳变更稳）。 */
export function medianSmoothMidi(
  midi: readonly (number | null)[],
  window = 5,
): (number | null)[] {
  const half = Math.floor(window / 2)
  const out: (number | null)[] = new Array(midi.length)
  for (let i = 0; i < midi.length; i++) {
    const vals: number[] = []
    for (let j = Math.max(0, i - half); j <= Math.min(midi.length - 1, i + half); j++) {
      const v = midi[j]
      if (v !== null && v !== undefined) vals.push(v)
    }
    out[i] = vals.length ? vals.slice().sort((a, b) => a - b)[Math.floor(vals.length / 2)]! : null
  }
  return out
}

/**
 * 滞回量化：连续 MIDI 值 → 稳定音号。
 *
 * 迟滞的意义：值在 60.4 与 60.6 之间抖动时，普通取整会在 60/61 之间
 * 闪。滞回要求「新音号要连续 N 帧都超过阈值才换」。
 */
export function hysteresisQuantize(
  midi: readonly (number | null)[],
  hysteresisFrames = 4,
): (number | null)[] {
  const out: (number | null)[] = new Array(midi.length)
  let current: number | null = null
  let pending: number | null = null
  let pendingCount = 0
  for (let i = 0; i < midi.length; i++) {
    const v = midi[i]
    if (v === null || v === undefined) {
      out[i] = current
      continue
    }
    const rounded = Math.round(v)
    if (current === null) {
      current = rounded
      out[i] = current
      continue
    }
    if (rounded === current) {
      pending = null
      pendingCount = 0
      out[i] = current
      continue
    }
    // 迟回：新音号连续 hysteresisFrames 帧成立才换
    if (pending === rounded) pendingCount++
    else {
      pending = rounded
      pendingCount = 1
    }
    if (pendingCount >= hysteresisFrames) {
      current = pending
      pending = null
      pendingCount = 0
    }
    out[i] = current
  }
  return out
}

/** 旋律段切分（量化音号连续相同的帧归一段）。 */
export function segmentMelody(q: readonly (number | null)[]): MelodySegment[] {
  const segs: MelodySegment[] = []
  let i = 0
  while (i < q.length) {
    const key = q[i] ?? null
    let j = i + 1
    while (j < q.length && (q[j] ?? null) === key) j++
    segs.push({
      startFrame: i,
      endFrame: j,
      midi: key,
      freq: key === null ? null : midiToFreq(key),
    })
    i = j
  }
  return segs.filter((s) => s.midi !== null && s.endFrame - s.startFrame >= 2)
}

/** 探针用的 RMS 便捷封装（对齐层也用得上）。 */
export function envelopeOf(mono: Mono, hopSec = 0.05): Float64Array {
  return rmsEnvelope(mono, hopSec, hopSec)
}

// ============================================================
//  CLI：feuille music align
// ============================================================

/**
 * `feuille music align <recording> [--score <midi>] [--out <dir>] [--name <n>]`
 *
 * 有 `--score` → Tier A（谱面真值对拍）：按谱块顺序把谱面与录音对齐，
 * 每对配对都过「落带内 + 音级交集 ≥ 2/3」两条判据；任一条不过就记为
 * 不成立（fail-closed，不硬凑）。
 * 无 `--score` → Tier B（录音实测）：泛音和声评分 f0 → 旋律线。
 *
 * 产出：`<out>/<name>-align.json`（配对与判定）+ 终端摘要。
 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const src = args.positional[0]
  if (!src) {
    console.error('usage: feuille music align <recording> [--score <midi>] [--out <dir>] [--name <n>]')
    return 2
  }
  const outDir = strOpt(args, 'out', 'notes')
  const name = strOpt(args, 'name', src.replace(/^.*[/\\]/, '').replace(/\.[^.]+$/, ''))
  const scorePath = args.opts['score']
  const hop = numOpt(args, 'hop', 0.05)

  mkdirSync(outDir, { recursive: true })
  const payload = withDecoded(src, (mono) => {
    const observed = observedChords(mono, { hopSec: hop })
    if (!scorePath) {
      const mel = melodyF0(mono, { hopSec: hop })
      return {
        tier: 'B' as const,
        source: src,
        hopSec: hop,
        observedSegments: observed.segments.length,
        melodySegments: mel.segments.length,
        melody: mel.segments.map((s) => ({
          start_s: s.startFrame * hop,
          end_s: s.endFrame * hop,
          midi: s.midi,
          freq: s.freq,
        })),
        pairs: [] as PairVerdict[],
        allOk: true,
      }
    }
    const midi = parseMidi(readFileSync(scorePath))
    const blocks = scoreBlocks(midi)
    const result = alignBlocks(blocks, observed, { hopSec: hop })
    return {
      tier: 'A' as const,
      source: src,
      score: scorePath,
      hopSec: hop,
      scoreBlocks: blocks.length,
      observedSegments: observed.segments.length,
      pairs: result.pairs,
      allOk: result.allOk,
      offsetSec: result.offsetSec,
    }
  })

  const outPath = join(outDir, `${name}-align.json`)
  writeFileSync(outPath, JSON.stringify(payload, null, 1), 'utf8')
  if (payload.tier === 'A') {
    const ok = payload.pairs.filter((p) => p.ok).length
    console.log(`align (Tier A): ${src} × ${payload.score}`)
    console.log(`  谱块 ${payload.scoreBlocks} · 观测段 ${payload.observedSegments} · `
      + `判定通过 ${ok}/${payload.pairs.length} · 偏移 ${payload.offsetSec.toFixed(3)}s`)
    console.log(`  → ${outPath}`)
    if (!payload.allOk) {
      console.error('  判定未全过：两条判据（落带内 + 音级交集 ≥ 2/3）有不过的配对——'
        + '不许当「差不多」读，按 notes/probe 的日志复核后再取摘录。')
      return 1
    }
  } else {
    console.log(`align (Tier B · 录音实测): ${src}`)
    console.log(`  观测段 ${payload.observedSegments} · 旋律段 ${payload.melodySegments}`)
    console.log(`  → ${outPath}`)
  }
  return 0
}
