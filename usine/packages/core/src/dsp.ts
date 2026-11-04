// dsp.ts — 自写 FFT 与 WAV 读写的**唯一实现**（library 层）。
//
// 为什么在 core：FFT 与 WAV 读取被两条产线共用——bgm-bed 的频段分布
// （bandShare）与 music-annotate-video 的探针/对齐（rfftMag / readWav）。
// 共用的底层原语属于 library（core），不许在 skill 专属包里各留一份。
//
// 内容原样搬自 @feuille/bgm 的 gen_bgm.ts（该处是最初的事实源），
// 口径不变：
// - radix-2 迭代 FFT（N 为 2 的幂）+ Bluestein chirp-z（任意 N 精确，
//   对齐 numpy.fft.rfft）；bandShare 需要任意 N 的精确 rfft——床长是
//   采集秒数决定的任意帧数，不能只伺候 2 的幂。Bluestein 的平方指数先
//   mod 2N，把 πn²/N 的参数压回 [0, 2π) 再取三角函数，大 N 下不丢精度。
// - WAV 只伺候 RIFF/PCM（Python wave 模块同款限制）：读到非 PCM 直接报错，
//   不静默当成别的格式。
import { readFileSync } from 'node:fs'

import { FeuilleError } from './errors.js'

// ============================================================
//  自写 FFT：radix-2 迭代（N 为 2 的幂）+ Bluestein chirp-z（任意 N）
// ============================================================
// bandShare 需要任意 N 的精确 rfft（对齐 numpy.fft.rfft）——床长是采集秒数
// 决定的任意帧数，不能只伺候 2 的幂。Bluestein 的平方指数先 mod 2N，把
// πn²/N 的参数压回 [0, 2π) 再取三角函数，大 N 下不丢精度。

function isPow2(n: number): boolean {
  return n > 0 && (n & (n - 1)) === 0
}

function nextPow2(n: number): number {
  let m = 1
  while (m < n) m <<= 1
  return m
}

/** 原地做 N 点复 DFT（N 为 2 的幂），re/im 等长输入输出。 */
export function fftPow2(re: Float64Array, im: Float64Array): void {
  const n = re.length
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1
    for (; j & bit; bit >>= 1) j ^= bit
    j |= bit
    if (i < j) {
      const tr = re[i]!; re[i] = re[j]!; re[j] = tr
      const ti = im[i]!; im[i] = im[j]!; im[j] = ti
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const half = len >> 1
    const ang = (-2 * Math.PI) / len
    const wr = Math.cos(ang), wi = Math.sin(ang)
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0
      for (let k = 0; k < half; k++) {
        const ar = re[i + k]!, ai = im[i + k]!
        const br = re[i + k + half]! * cr - im[i + k + half]! * ci
        const bi = re[i + k + half]! * ci + im[i + k + half]! * cr
        re[i + k] = ar + br; im[i + k] = ai + bi
        re[i + k + half] = ar - br; im[i + k + half] = ai - bi
        const ncr = cr * wr - ci * wi
        ci = cr * wi + ci * wr
        cr = ncr
      }
    }
  }
}

/** Bluestein chirp-z：任意 N 的复 DFT（原地）。平方指数 mod 2N 防精度漂移。 */
export function dftAny(re: Float64Array, im: Float64Array): void {
  const n = re.length
  const m = nextPow2(2 * n - 1)
  // a[k] = x[k]·exp(-iπk²/N)
  const are = new Float64Array(m), aim = new Float64Array(m)
  for (let k = 0; k < n; k++) {
    const s = (k * k) % (2 * n)
    const ang = (-Math.PI * s) / n
    const c = Math.cos(ang), sn = Math.sin(ang)
    are[k] = re[k]! * c - im[k]! * sn
    aim[k] = im[k]! * c + re[k]! * sn
  }
  // b[j] = exp(+iπj²/N)，负下标（卷积用的环绕项）按偶函数镜像到 m-j
  const bre = new Float64Array(m), bim = new Float64Array(m)
  bre[0] = 1
  for (let k = 1; k < n; k++) {
    const s = (k * k) % (2 * n)
    const ang = (Math.PI * s) / n
    bre[k] = bre[m - k]! = Math.cos(ang)
    bim[k] = bim[m - k]! = Math.sin(ang)
  }
  fftPow2(are, aim)
  fftPow2(bre, bim)
  for (let k = 0; k < m; k++) {
    const ar = are[k]!, ai = aim[k]!, br = bre[k]!, bi = bim[k]!
    are[k] = ar * br - ai * bi
    aim[k] = ar * bi + ai * br
  }
  // 逆 FFT：换位 → 正变换 → 换位 → ÷m（fftPow2(aim, are) 后实部在 are、虚部在 aim）
  fftPow2(aim, are)
  const invM = 1 / m
  for (let k = 0; k < n; k++) {
    const s = (k * k) % (2 * n)
    const ang = (-Math.PI * s) / n
    const c = Math.cos(ang), sn = Math.sin(ang)
    const vr = are[k]! * invM, vi = aim[k]! * invM
    re[k] = vr * c - vi * sn
    im[k] = vi * c + vr * sn
  }
}

/** rfft 幅度谱：|X[k]|，k = 0..⌊N/2⌋（numpy.fft.rfft + abs 的对应物）。 */
export function rfftMag(x: Float64Array): Float64Array {
  const n = x.length
  const re = Float64Array.from(x)
  const im = new Float64Array(n)
  if (isPow2(n)) fftPow2(re, im)
  else dftAny(re, im)
  const half = Math.floor(n / 2)
  const out = new Float64Array(half + 1)
  for (let k = 0; k <= half; k++) out[k] = Math.hypot(re[k]!, im[k]!)
  return out
}

// ============================================================
//  wav 读写（Python wave 模块的对应物：PCM s16le 之外不伺候）
// ============================================================

export interface WavInfo {
  sampleRate: number
  channels: number
  /** data 块字节流（帧数 = data.length / (channels×2)）。 */
  data: Buffer
}

/** 读 wav 头与 data 块。Python wave.open 只伺候 PCM——这里同样只认 RIFF/PCM。 */
export function readWav(path: string): WavInfo {
  const buf = readFileSync(path)
  if (buf.length < 44 || buf.toString('latin1', 0, 4) !== 'RIFF'
    || buf.toString('latin1', 8, 12) !== 'WAVE') {
    throw new FeuilleError(`${path} 不是 RIFF/WAVE 文件`)
  }
  let off = 12
  let sampleRate = 0, channels = 0
  let data: Buffer | null = null
  while (off + 8 <= buf.length) {
    const id = buf.toString('latin1', off, off + 4)
    const size = buf.readUInt32LE(off + 4)
    const body = buf.subarray(off + 8, off + 8 + size)
    if (id === 'fmt ') {
      if (body.readUInt16LE(0) !== 1) throw new FeuilleError(`${path} 不是 PCM wav（wave 模块同款限制）`)
      channels = body.readUInt16LE(2)
      sampleRate = body.readUInt32LE(4)
    } else if (id === 'data') {
      data = Buffer.from(body)
    }
    off += 8 + size + (size & 1) // chunk 按 2 字节对齐，尾随 padding 要跳过
  }
  if (sampleRate === 0 || channels === 0 || data === null) {
    throw new FeuilleError(`${path} 缺 fmt / data 块，读不出音频`)
  }
  return { sampleRate, channels, data }
}

