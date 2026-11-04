// probe.ts — 探针：录音的结构测量（零额度、纯本地）。
//
// 纪律：**所有摘录起止必须由探针日志背书**。不许「听一遍凭感觉取 30 秒
// 到 1 分 30 秒」。探针给出可复核的候选边界（引子、爆发、主题进入、
// 高频段、衰减），日志里逐条写明依据与时间码。
//
// 三类测量：
//   ① RMS 包络——引子/渐强/衰减的骨架；
//   ② 频段占比——高频峰簇（三角铁/钹/打击乐段落）；
//   ③ 起音检测——能量上升沿（乐句起点）。
//
// 输出两件：机器可读的 `<name>.json` 与人可读的 `<name>.log`。
// **log 是「背书」本身**：交付时随片归档，出错时按它逐条复核。
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { FeuilleError } from '@feuille/core'

import { numOpt, parseArgs, strOpt } from './cli.js'
import { bandSharePct, magnitudeSpectrum, rmsEnvelope, withDecoded, type Mono } from './dsp.js'

export interface ProbeOptions {
  /** RMS 包络跳（秒）。 */
  hopSec?: number
  /** 频段窗长（秒）。 */
  windowSec?: number
  /** 起音检测：上升沿阈值（相对局部均值）。 */
  onsetRatio?: number
  /** 频段扫描的帧跳（秒）。 */
  bandHopSec?: number
  /** FFT 窗长。 */
  fftSize?: number
}

const DEFAULTS: Required<ProbeOptions> = {
  hopSec: 0.05,
  windowSec: 2.0,
  onsetRatio: 1.8,
  bandHopSec: 1.0,
  fftSize: 4096,
}

/** 一个频段窗口的测量。 */
export interface BandWindow {
  t0: number
  t1: number
  /** 该窗的 RMS。 */
  rms: number
  /** 高频（>3kHz）功率占比 %。 */
  hfPct: number
  /** 低频（<100Hz）功率占比 %。 */
  lfPct: number
  /** 中频（400–1k）功率占比 %。 */
  midPct: number
}

/** 一次起音。 */
export interface Onset {
  t: number
  /** 上升幅度（倍数）。 */
  strength: number
}

/** 探针结果。 */
export interface ProbeResult {
  source: string
  durationSec: number
  sampleRate: number
  hopSec: number
  rms: {
    max: number
    mean: number
    p95: number
    /** 全片 RMS 包络（每 hopSec 一格）。 */
    envelope: number[]
  }
  windows: BandWindow[]
  onsets: Onset[]
  /** 候选摘录边界（每条都带依据）。 */
  candidates: Array<{ startSec: number; endSec: number; reason: string }>
}

function percentile(sorted: readonly number[], p: number): number {
  if (!sorted.length) return 0
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * p)))
  return sorted[i]!
}

/**
 * 对录音跑探针。
 *
 * `maxOf` 给出**整段**的统一参照（RMS 最大值 / 高频占比峰值），
 * 候选边界按相对阈值（相对全段）来切——不是相对局部段，否则同一首录音
 * 的不同段落会得到互不可比的阈值（traps §15 同款病灶）。
 */
export function probeAudio(
  mono: Mono,
  source: string,
  opts: ProbeOptions = {},
): ProbeResult {
  const o = { ...DEFAULTS, ...opts }
  const env = rmsEnvelope(mono, o.hopSec, o.hopSec)
  if (env.length === 0) throw new FeuilleError(`探针：${source} 解不出音频帧`)

  const durationSec = mono.samples.length / mono.sampleRate
  const sorted = [...env].sort((a, b) => a - b)
  const rmsMax = sorted[sorted.length - 1]!
  const rmsMean = env.reduce((a, b) => a + b, 0) / env.length
  const rmsP95 = percentile(sorted, 0.95)

  // ---- 频段窗口 ----
  const winFrames = Math.max(1, Math.round(o.windowSec / o.hopSec))
  const windows: BandWindow[] = []
  for (let i = 0; i + winFrames <= env.length; i += Math.max(1, winFrames)) {
    let acc = 0
    for (let j = 0; j < winFrames; j++) acc += env[i + j]!
    const t0 = i * o.hopSec
    const t1 = (i + winFrames) * o.hopSec
    const mid = Math.floor((t0 * mono.sampleRate + (t1 * t0) * 0) ) || 0
    void mid
    const offset = Math.round(((t0 + t1) / 2) * mono.sampleRate)
    const mag = magnitudeSpectrum(mono, Math.max(0, offset), o.fftSize)
    windows.push({
      t0,
      t1,
      rms: acc / winFrames,
      hfPct: bandSharePct(mag, mono.sampleRate, o.fftSize, 3000, mono.sampleRate / 2),
      lfPct: bandSharePct(mag, mono.sampleRate, o.fftSize, 0, 100),
      midPct: bandSharePct(mag, mono.sampleRate, o.fftSize, 400, 1000),
    })
  }

  // ---- 起音检测：能量上升沿 ----
  const onsets: Onset[] = []
  const lookback = Math.max(1, Math.round(0.35 / o.hopSec))
  for (let i = lookback; i < env.length; i++) {
    const cur = env[i]!
    if (cur < rmsMean * 1.2) continue
    let localMax = 0
    for (let j = Math.max(0, i - lookback); j < i; j++) localMax = Math.max(localMax, env[j]!)
    if (localMax <= 0) continue
    const strength = cur / localMax
    if (strength >= o.onsetRatio) {
      const t = i * o.hopSec
      if (onsets.length === 0 || t - onsets[onsets.length - 1]!.t >= 0.25) {
        onsets.push({ t, strength })
      }
    }
  }

  // ---- 候选摘录边界 ----
  const candidates = pickCandidates(windows, onsets, rmsMax, rmsMean, durationSec)

  return {
    source,
    durationSec,
    sampleRate: mono.sampleRate,
    hopSec: o.hopSec,
    rms: { max: rmsMax, mean: rmsMean, p95: rmsP95, envelope: [...env] },
    windows,
    onsets,
    candidates,
  }
}

/**
 * 候选边界的三条规则（全部相对**全段**参照）：
 *
 *  ① 「渐强入口」：RMS 从低于均值 60% 升到高于均值 90% 的第一个位置；
 *  ② 「段落收口」：RMS 从高于均值 80% 回落到低于均值 60% 的位置；
 *  ③ 「高频峰簇」：高频占比超过全段峰值 80% 的窗口起点（打击乐段）。
 *
 * 只给候选，不替人做决定——摘录的取舍是内容判断（见 SKILL.md「摘录选择
 * 原则」：每乐章至少一段、A–B–A 必须带 B、边界留 0.2–0.5s 余量）。
 */
function pickCandidates(
  windows: readonly BandWindow[],
  onsets: readonly Onset[],
  rmsMax: number,
  rmsMean: number,
  durationSec: number,
): Array<{ startSec: number; endSec: number; reason: string }> {
  const out: Array<{ startSec: number; endSec: number; reason: string }> = []
  const lo = rmsMean * 0.6
  const hi = rmsMean * 0.9
  const loEnd = rmsMean * 0.8
  const loExit = rmsMean * 0.6

  let prev = windows[0]?.rms ?? 0
  for (let i = 1; i < windows.length; i++) {
    const w = windows[i]!
    if (prev <= lo && w.rms >= hi) {
      out.push({
        startSec: w.t0,
        endSec: Math.min(durationSec, w.t0 + 20),
        reason: `渐强入口：RMS 从 ${prev.toFixed(3)}（≤均值的 60%）升到 ${w.rms.toFixed(3)}`,
      })
    }
    if (prev >= loEnd && w.rms <= loExit) {
      out.push({
        startSec: Math.max(0, w.t0 - 2),
        endSec: w.t1,
        reason: `段落收口：RMS 从 ${prev.toFixed(3)} 回落到 ${w.rms.toFixed(3)}`,
      })
    }
    prev = w.rms
  }

  const hfPeak = windows.reduce((m, w) => Math.max(m, w.hfPct), 0)
  if (hfPeak > 0) {
    for (const w of windows) {
      if (w.hfPct >= hfPeak * 0.8) {
        out.push({
          startSec: w.t0,
          endSec: w.t1,
          reason: `高频峰簇：高频占比 ${w.hfPct.toFixed(2)}%（全段峰值 ${hfPeak.toFixed(2)}%）`,
        })
      }
    }
  }

  if (onsets.length) {
    const first = onsets[0]!
    out.push({
      startSec: first.t,
      endSec: Math.min(durationSec, first.t + 15),
      reason: `首个能量上升沿（起音检测，强度 ${first.strength.toFixed(2)}×）`,
    })
  }
  void rmsMax
  return out
}

/** 把探针结果写成机器可读 JSON + 人可读 log。 */
export function writeProbe(
  dir: string,
  name: string,
  result: ProbeResult,
): { json: string; log: string } {
  mkdirSync(dir, { recursive: true })
  const jsonPath = join(dir, `${name}.json`)
  const logPath = join(dir, `${name}.log`)
  writeFileSync(jsonPath, JSON.stringify(result, null, 1), 'utf8')
  writeFileSync(logPath, renderLog(result), 'utf8')
  return { json: jsonPath, log: logPath }
}

/** 人可读的探针日志——摘录边界的「背书」。 */
export function renderLog(r: ProbeResult): string {
  const L: string[] = []
  L.push(`# 探针日志 · ${r.source}`)
  L.push('')
  L.push(`- 时长：${r.durationSec.toFixed(3)}s（采样率 ${r.sampleRate}）`)
  L.push(`- RMS：max ${r.rms.max.toFixed(4)} / mean ${r.rms.mean.toFixed(4)} / p95 ${r.rms.p95.toFixed(4)}（hop ${r.hopSec}s）`)
  L.push('')
  L.push('## 频段窗口')
  L.push('')
  L.push('| t0 | t1 | RMS | >3k% | <100Hz% | 400-1k% |')
  L.push('|---|---|---|---|---|---|')
  for (const w of r.windows) {
    L.push(`| ${w.t0.toFixed(2)} | ${w.t1.toFixed(2)} | ${w.rms.toFixed(4)} | ${w.hfPct.toFixed(2)} | ${w.lfPct.toFixed(2)} | ${w.midPct.toFixed(2)} |`)
  }
  L.push('')
  L.push(`## 起音（${r.onsets.length} 个）`)
  L.push('')
  for (const o of r.onsets.slice(0, 80)) {
    L.push(`- ${o.t.toFixed(2)}s  强度 ${o.strength.toFixed(2)}×`)
  }
  if (r.onsets.length > 80) L.push(`- …（另有 ${r.onsets.length - 80} 个未列）`)
  L.push('')
  L.push('## 候选摘录边界（每条都有依据；最终取舍是内容判断）')
  L.push('')
  for (const c of r.candidates) {
    L.push(`- ${c.startSec.toFixed(2)}s → ${c.endSec.toFixed(2)}s  ← ${c.reason}`)
  }
  L.push('')
  L.push('> 取用时留 0.2–0.5s 余量（别切在混响中间）；每乐章至少一段，'
    + 'A–B–A 结构必须带一点 B；片内要有「选段 · 第 N 乐章」角标。')
  return L.join('\n') + '\n'
}

// ============================================================
//  CLI：feuille music probe
// ============================================================

/**
 * `feuille music probe <recording> [--out <dir>] [--name <n>] [--hop 0.05] [--window 2]`
 *
 * 产出：`<out>/<name>.json`（机器读）+ `<out>/<name>.log`（人读，摘录边界的背书）。
 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const src = args.positional[0]
  if (!src) {
    console.error('usage: feuille music probe <recording> [--out <dir>] [--name <n>] [--hop 0.05] [--window 2]')
    return 2
  }
  const outDir = strOpt(args, 'out', 'notes/probe')
  const name = strOpt(args, 'name', src.replace(/^.*[/\\]/, '').replace(/\.[^.]+$/, ''))
  const hop = numOpt(args, 'hop', 0.05)
  const windowSec = numOpt(args, 'window', 2.0)

  const result = withDecoded(src, (mono) => probeAudio(mono, src, { hopSec: hop, windowSec }))
  const { json, log } = writeProbe(outDir, name, result)
  console.log(`probe: ${src}`)
  console.log(`  时长 ${result.durationSec.toFixed(2)}s · RMS max ${result.rms.max.toFixed(4)} `
    + `· 起音 ${result.onsets.length} · 候选边界 ${result.candidates.length}`)
  console.log(`  → ${json}`)
  console.log(`  → ${log}`)
  return 0
}
