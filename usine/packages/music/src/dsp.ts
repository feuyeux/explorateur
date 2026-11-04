// dsp.ts — 音频解码与分析原语（探针与对齐共用的底座）。
//
// 纪律（来自 skills/music-annotate-video/references/music-av-traps.md）：
//
// - **不引入 librosa / pyin / DTW**。pyin 走 numba JIT：实测 CPU 471s +
//   提交内存 154GB，系统三次冻结全复现在这个调用点。子序列 DTW 的代价
//   模型每步累加，结构性把 19s 参考压进 2.1s（假阳性）。替代方案是
//   和弦模板逐帧分类（chord.ts）与手写泛音和声评分 f0（align.ts）。
// - FFT 原语用 @feuille/bgm 的 rfftMag（radix-2 + Bluestein，任意 N 精确）。
//   本包只做**分块**调用与后处理，不另写一份 FFT。
// - 一次只跑一个重分析：Node 单进程，分块控内存。
//
// 音频一律经 ffmpeg 解成**单声道 PCM wav**再分析：录音来源杂（ogg /
// flac / mp3 / m4a），只有 wav 的 s16le 读法是确定的（@feuille/bgm 的
// readWav 只伺候 PCM）。
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { FeuilleError, platform } from '@feuille/core'
import { rfftMag, readWav } from '@feuille/core'

/** 分析采样率。22050 Hz 覆盖到 10.9 kHz——足够做 RMS 包络、频段占比与
 * 旋律音区（最高约 C7 = 2093 Hz）的 f0 估计。 */
export const ANALYSIS_SR = 22050

/** 单声道 float 波形。 */
export interface Mono {
  sampleRate: number
  /** 取值 [-1, 1]。 */
  samples: Float64Array
}

function sh(args: Array<string | number>, timeout?: number): void {
  const strs = args.map(String)
  const r = spawnSync(strs[0]!, strs.slice(1), {
    encoding: 'utf8',
    timeout: timeout == null ? undefined : timeout * 1000,
    maxBuffer: 1 << 26,
  })
  if (r.error) throw new FeuilleError(`FAILED: ${strs.join(' ')}\n${r.error.message}`)
  if (r.status !== 0) {
    throw new FeuilleError(`FAILED: ${strs.join(' ')}\n${(r.stderr ?? '').slice(-2000)}`)
  }
}

/** 把任意可解码音频解成单声道 wav（PCM s16le），返回临时 wav 路径。
 *
 * 调用方负责清理（配 `withDecoded`）。
 */
export function decodeToWav(src: string, sampleRate = ANALYSIS_SR): string {
  const ff = platform.requireTool(platform.ffmpeg(), 'ffmpeg')
  const dir = mkdtempSync(join(tmpdir(), 'feuille-music-'))
  const out = join(dir, 'decoded.wav')
  sh([ff, '-y', '-loglevel', 'error', '-i', src,
    '-ac', '1', '-ar', String(sampleRate), '-c:a', 'pcm_s16le', out], 600)
  return out
}

/** 解码 → 单声道 float 波形；用完自动清临时目录。 */
export function withDecoded<T>(src: string, fn: (m: Mono) => T, sampleRate = ANALYSIS_SR): T {
  const wav = decodeToWav(src, sampleRate)
  try {
    return fn(readMonoWav(wav))
  } finally {
    rmSync(join(wav, '..'), { recursive: true, force: true })
  }
}

/** 读 PCM wav → 单声道 float（多声道按声道平均）。 */
export function readMonoWav(path: string): Mono {
  const w = readWav(path)
  const frames = Math.floor(w.data.length / (w.channels * 2))
  const out = new Float64Array(frames)
  for (let f = 0; f < frames; f++) {
    let s = 0
    for (let c = 0; c < w.channels; c++) s += w.data.readInt16LE((f * w.channels + c) * 2)
    out[f] = s / w.channels / 32768
  }
  return { sampleRate: w.sampleRate, samples: out }
}

/** RMS 包络：每 hop 秒一格，值是那一格的均方根。 */
export function rmsEnvelope(mono: Mono, hopSec = 0.05, frameSec = 0.05): Float64Array {
  const hop = Math.max(1, Math.round(hopSec * mono.sampleRate))
  const win = Math.max(1, Math.round(frameSec * mono.sampleRate))
  const n = Math.max(0, Math.floor((mono.samples.length - win) / hop) + 1)
  const out = new Float64Array(n)
  for (let i = 0; i < n; i++) {
    let acc = 0
    const base = i * hop
    for (let j = 0; j < win; j++) {
      const v = mono.samples[base + j] ?? 0
      acc += v * v
    }
    out[i] = Math.sqrt(acc / win)
  }
  return out
}

/** Hann 窗（与 @feuille/bgm 的 bandShare 同一口径：0.5·(1−cos(2πn/(M−1))））。 */
export function hann(n: number): Float64Array {
  const w = new Float64Array(n)
  for (let i = 0; i < n; i++) w[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (n - 1)))
  return w
}

/** 一帧的幅度谱（rfftMag 的窗口化输入）。 */
export function magnitudeSpectrum(mono: Mono, offset: number, size: number): Float64Array {
  const x = new Float64Array(size)
  const win = hann(size)
  for (let i = 0; i < size; i++) {
    const s = mono.samples[offset + i]
    x[i] = (s === undefined ? 0 : s) * win[i]!
  }
  return rfftMag(x)
}

/** 频段能量占比（%）：[lo, hi) 的功率 / 全带功率。 */
export function bandSharePct(
  mag: Float64Array,
  sampleRate: number,
  size: number,
  lo: number,
  hi: number,
): number {
  let total = 0
  const p = new Float64Array(mag.length)
  for (let k = 0; k < mag.length; k++) {
    p[k] = mag[k]! * mag[k]!
    total += p[k]!
  }
  if (total <= 0) return 0
  let s = 0
  for (let k = 0; k < mag.length; k++) {
    const fr = (k * sampleRate) / size
    if (fr >= lo && fr < hi) s += p[k]!
  }
  return (s / total) * 100
}

/** 频率 → MIDI 音号（可带小数）。 */
export function freqToMidi(f: number): number {
  return 69 + 12 * Math.log2(f / 440)
}

/** MIDI 音号 → 频率。 */
export function midiToFreq(m: number): number {
  return 440 * Math.pow(2, (m - 69) / 12)
}

/** 音级名（拼写）。0 = C。 */
export const PITCH_NAMES = [
  'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B',
] as const

/** 音级集合 → 规范字符串（升序、去重）。 */
export function pcsToKey(pcs: readonly number[]): string {
  const u = [...new Set(pcs.map((p) => ((p % 12) + 12) % 12))].sort((a, b) => a - b)
  return u.map((p) => PITCH_NAMES[p]!).join('')
}
