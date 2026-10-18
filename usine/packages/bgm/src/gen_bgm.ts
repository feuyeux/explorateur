// gen_bgm.ts — 生成成片用的纯器乐 BGM 床（Google Lyria）
// （promoted from skills/bgm-bed/scripts/gen_bgm.py，P5-7f 归流）
//
// 成片里的 BGM 是一条**独立资产**：先用本命令生成并实测，再把 `bgm` 块写进
// `video.json`（合成端只做「裁到画面网格 + 两端淡 + 定增益 + amix」，不会
// 凭空变出音乐来）。床的电平是**反推**出来的，不是抄模板常数：本命令量出
// 床的实际电平，配合 --narration-rms-db 直接给出该写进 video.json 的 gain。
//
// 出床线（本命令只管 Lyria）：GEMINI_API_KEY 或 ~/.gemini_api_key（免费层
// 走实时端点）。MCode 内置音乐（matrix，经 mcode-tools）是另一条**成品床
// 来源**：无 key、入参无时长、计费不公开——不经本命令，用法见 SKILL.md。
//
// 请求一律**纯器乐**——床要垫在旁白底下，人声床是配乐事故。时长由 lyria
// 实时后端的采集秒数控制，**床长判据（≥ 成片时长）照常验收**，短了就报。
//
// --list-providers 只做凭据探测不动网络，适合先看一眼 Lyria 的 key 在不在。
//
// Lyria 选哪个模型（2026-10 实测，免费层 key = 0 额度的那三个会被直接拒）：
//   lyria-realtime-exp（默认）：Live API WebSocket，免费层可用，$0，流式裸
//     PCM，采样率/声道由服务端定（模型卡：48 kHz / Stereo / Raw 16-bit PCM）。
//     按设计**不出人声**；提示词走加权短词（WeightedPrompt），多个 --prompt
//     按序降权，或直接 --text 给一段。
//   lyria-3.5 / lyria-3-pro-preview / lyria-3-clip-preview：POST /v1beta/
//     interactions，免费层 429「0 requests per day」，$0.04–0.08/首，一次
//     请求整首。
//
// 为什么 Lyria 实时后端不写死采样率：SDK 的 LiveMusicGenerationConfig 没有
// audio_format 字段，采样率是服务端定的。所以用**实测拍速反查**：请求 72
// BPM，若成品的自相关峰值落在 72 BPM 的 ±5%（含 ×2 / ÷2 折叠），说明按
// 48 kHz 解读是对的；否则 wav 头就是错的，整条片子会变调——这种情况必须
// 当场报错，不许把错的文件当成功交出去。其余后端自带容器，采样率由音频头
// 决定，无需反查。
//
// 外部可执行文件（量电平 / 解码容器用）走 @feuille/core platform 解析，
// 找不到显式失败。频段分布的 rfft 自写 radix-2 + Bluestein（不装依赖——
// bandShare 需要任意 N 的精确频谱，对齐 numpy.fft.rfft 的语义）。
//
// Usage: feuille bgm gen --out <wav> [--prompt 短词]… [--text 一段]
//        [--model lyria-realtime-exp] [--duration 62] [--bpm 72]
//        [--density 0.6] [--brightness 0.4]
//        [--narration-rms-db -21.4] [--target-under-db 16]
//        [--force] [--recheck] [--list-providers]
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'

import { FeuilleError, roundHalfEven, audio, platform } from '@feuille/core'

// 文档声明的流格式（Lyria RealTime 模型卡：48 kHz / Stereo / Raw 16-bit PCM）。
// 服务端没给协商字段，只能按文档解读——并用实测拍速反查，见 verifyRate。
export const RATE = 48000
export const CHANNELS = 2
export const WIDTH = 2
// 唯一值得考虑的另一种解读：48 k ↔ 44.1 k。差 8.9%，是采样率读错时唯一能解释的量。
export const RATE_RATIOS: readonly [number, number] = [RATE / 44100, 44100 / RATE]

/** Lyria 生成失败（配额 / 围栏 / 端点形状不符）。主流程捕获后以退出码 1 结束。 */
export class ProviderError extends Error {}

// Python round(x, d) 是银行家舍入——core roundHalfEven 是唯一实现，不自造第二份。
const pyRound = (x: number, d: number): number => roundHalfEven(x * 10 ** d) / 10 ** d

// Python str(float)：整数值也带 .0（168.0 不写成 168）——报错/报告文案逐字对齐。
function pyFloat(x: number | null): string {
  if (x === null) return 'None'
  if (!Number.isFinite(x)) return Number.isNaN(x) ? 'nan' : x > 0 ? 'inf' : '-inf'
  return Number.isInteger(x) ? x.toFixed(1) : String(x)
}

// Python f"{x:g}"：6 位有效数字去尾零。本命令里用于人读的实测值（62 / 71.3 / 1.15）。
function pyG(x: number): string {
  if (!Number.isFinite(x)) return Number.isNaN(x) ? 'nan' : x > 0 ? 'inf' : '-inf'
  if (x === 0) return '0'
  const a = Math.abs(x)
  if (a >= 1e21 || a < 1e-4) {
    return x.toExponential(5).replace(/(\.\d*?)0+e/, '$1e').replace(/\.e/, 'e')
  }
  return String(parseFloat(x.toPrecision(6)))
}

// Python f"{x:.nf}"：定点格式也是银行家舍入（161.5 → 162、162.5 → 162）。
function pyFixed(x: number, d: number): string {
  return (pyRound(x, d)).toFixed(d)
}

// Python str.splitlines() 逐位镜像：按通用换行边界切，结尾换行不产空段。
function splitLines(text: string): string[] {
  if (text === '') return []
  const parts = text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)
  if (parts[parts.length - 1] === '') parts.pop()
  return parts
}

function ffmpegBin(): string {
  const got = platform.ffmpeg()
  if (!got) throw new FeuilleError('找不到 ffmpeg（feuille.platform 解析）；装好后重跑')
  return got
}

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

/** 写 48 kHz / 立体声 / 16-bit PCM wav（RIFF 头手工拼，对应 Python wave 写模式）。 */
export function writeWav(path: string, pcm: Buffer): void {
  const h = Buffer.alloc(44)
  h.write('RIFF', 0, 'latin1')
  h.writeUInt32LE(36 + pcm.length, 4)
  h.write('WAVE', 8, 'latin1')
  h.write('fmt ', 12, 'latin1')
  h.writeUInt32LE(16, 16)
  h.writeUInt16LE(1, 20) // PCM
  h.writeUInt16LE(CHANNELS, 22)
  h.writeUInt32LE(RATE, 24)
  h.writeUInt32LE(RATE * CHANNELS * WIDTH, 28)
  h.writeUInt16LE(CHANNELS * WIDTH, 32)
  h.writeUInt16LE(WIDTH * 8, 34)
  h.write('data', 36, 'latin1')
  h.writeUInt32LE(pcm.length, 40)
  writeFileSync(path, Buffer.concat([h, pcm]))
}

// ============================================================
//  凭据探测（只看 key 在不在，不碰网络）
// ============================================================

/** 统一 key 文件：~/.config/feuille/bgm-bed.env（BGM_BED_ENV 可改指任意路径）。
 *
 * 放在 $HOME 下是刻意的——密钥永不进仓库（usine/AGENTS.md 纪律：key 走环境
 * 或用户目录，不落盘到 git 管辖范围）。样例见 references/keys.env.sample。
 */
export function keyFile(): string {
  return (process.env['BGM_BED_ENV'] ?? '').trim() || join(homedir(), '.config', 'feuille', 'bgm-bed.env')
}

/** 把 key 文件里的变量灌进环境——**不覆盖已有环境变量**（环境优先于文件）。
 *
 * 返回实际加载的文件（不存在/没可解析行返回 null），供探测报告显示来源；
 * 找不到不是错误（纯环境变量也能跑），只影响报告里那行提示。
 */
export function loadEnvFile(): string | null {
  const f = keyFile()
  if (!existsSync(f)) return null
  let got = false
  for (let line of splitLines(readFileSync(f, 'utf8'))) {
    line = line.trim()
    if (line === '' || line.startsWith('#') || !line.includes('=')) continue
    const eq = line.indexOf('=')
    const k = line.slice(0, eq).trim()
    // Python strip('"').strip("'")：先剥双引号、再剥单引号，两端逐字符
    let v = line.slice(eq + 1).trim()
      .replace(/^"+/, '').replace(/"+$/, '')
      .replace(/^'+/, '').replace(/'+$/, '')
    if (k && v && process.env[k] === undefined) {
      process.env[k] = v
      got = true
    }
  }
  return got ? f : null
}

function lyriaKey(): string | null {
  const env = (process.env['GEMINI_API_KEY'] ?? '').trim()
  if (env) return env
  const f = join(homedir(), '.gemini_api_key')
  if (existsSync(f)) {
    const key = readFileSync(f, 'utf8').trim()
    if (key) return key
  }
  return null
}

/** [(供应商, 凭据来源描述)]。只看凭据在不在，不碰网络。 */
export function detectProviders(): Array<[string, string]> {
  return lyriaKey() ? [['lyria', 'GEMINI_API_KEY / ~/.gemini_api_key']] : []
}

function loadLyriaKey(): string {
  const key = lyriaKey()
  if (!key) throw new FeuilleError('找不到 Lyria key：设 GEMINI_API_KEY 或写 ~/.gemini_api_key')
  return key
}

// ============================================================
//  lyria 后端（实时 WebSocket 结构性移植；HTTP 路径同 Python——从未在付费
//  key 上实测过，解不出容器就大声失败，绝不把「猜测的格式」当事实写盘）
// ============================================================

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

/** Python 只重试 OSError（建连类）；Node 的对应物是网络错误码 / fetch failed。 */
function isConnectError(e: unknown): boolean {
  const anyE = e as { cause?: { code?: string }, code?: string }
  const code = anyE?.cause?.code ?? anyE?.code ?? ''
  const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e)
  return code.startsWith('E') || code.startsWith('UND_ERR')
    || msg.includes('fetch failed') || msg.includes('socket')
    || msg.includes('ECONNRESET') || msg.includes('aborted')
}

async function oneSession(
  key: string, model: string,
  prompts: Array<readonly [string, number]>,
  cfg: { bpm: number; density: number; brightness: number },
  seconds: number,
): Promise<Buffer> {
  // 与 Python 一致：SDK 就地导入（没装 google-genai 也能 import 本包跑纯函数）。
  // Node SDK 与 Python SDK 形状不同：回调收流（onmessage），不是 async 迭代器。
  const mod = await import('@google/genai')
  const ai = new mod.GoogleGenAI({ apiKey: key, apiVersion: 'v1beta' })
  const chunks: Buffer[] = []
  const errs: unknown[] = []
  const session = await ai.live.music.connect({
    model: `models/${model}`,
    callbacks: {
      // 回调在 connect 时就登记——接收先于播放，流式会话不先抽水首段会被丢掉
      onmessage: (msg) => {
        const sc = msg.serverContent
        if (sc == null) return
        // Node SDK 的 audio chunk 是 base64 文本（Python SDK 是 bytes）——就地解回
        for (const ch of sc.audioChunks ?? []) {
          if (ch.data) chunks.push(Buffer.from(ch.data, 'base64'))
        }
      },
      onerror: (e) => {
        // 流中途出错要报出来，不能半首当成功
        errs.push(e)
      },
      // onclose 留空：正常收尾也走 close，不算错误
    },
  })
  const t0 = Date.now()
  try {
    await session.setWeightedPrompts({
      weightedPrompts: prompts.map(([text, weight]) => ({ text, weight })),
    })
    await session.setMusicGenerationConfig({
      musicGenerationConfig: {
        bpm: cfg.bpm, density: cfg.density, brightness: cfg.brightness,
        muteDrums: true,
        scale: mod.Scale.A_MAJOR_G_FLAT_MINOR,
        musicGenerationMode: mod.MusicGenerationMode.QUALITY,
      },
    })
    await sleep(1500) // 握手 + 生成器预热
    session.play()
    await sleep(seconds * 1000)
  } finally {
    session.close() // Node 无 task.cancel——关会话即断流
  }
  const got = chunks.reduce((s, c) => s + c.length, 0)
  if (errs.length > 0) {
    const elapsed = (Date.now() - t0) / 1000
    // 报错时必须能看出「断在哪、已经拿到多少」——否则只能盲重试
    let hint = ''
    if (got === 0 && elapsed < 20) {
      // 2026-10 实测：秒级断流 + 0 字节 = 地区围栏，不是配额也不是代码。
      // 服务端 close frame 写的是「User location is not supported」，
      // SDK 把它包成 1006/1007，所以要从「症状」认病因。
      hint = '\n↳ 0 字节秒断：**多半是地区围栏**，不是配额也不是本脚本。'
        + '\n  Live 音乐端点比普通 API 更严——同一把 key、同一出口 IP 下 `models.list` 能 200、'
        + '\n  `lyria-3.5` 能回 429 配额错，只有 `live.music` 会按出口 IP 判区。'
        + '\n  官方支持区（ai.google.dev/available_regions）里有日本 / 台湾 / 新加坡 / 美国，**没有香港**。'
        + '\n  → 换代理出口到上述任一区再跑；或换付费层 key 走 `--model lyria-3.5` 的 HTTP 后端。'
    }
    const e0 = errs[0] as { error?: unknown }
    const inner = e0?.error
    const subj = inner instanceof Error ? `${inner.name}: ${inner.message}`
      : e0 instanceof Error ? `${e0.name}: ${e0.message}` : String(e0)
    throw new ProviderError(
      `音乐流中断：${subj}｜已采集 ${got} 字节（${got / (RATE * CHANNELS * WIDTH)}s）/ `
      + `请求 ${pyG(seconds)}s，断在开流后 ${elapsed.toFixed(1)}s${hint}`,
    )
  }
  return Buffer.concat(chunks)
}

/** 建连抖动的退避重试。
 *
 * 只重试 **建连** 类错误（TLS 握手重置 / 连接被断开）——实测经代理跑 WebSocket
 * 时偶发。地区围栏、配额、流中断都不重试：那些再连一次还是同样的结果，
 * 无脑重试只会把一条有用的报错埋掉。
 */
async function captureRealtime(
  key: string, model: string,
  prompts: Array<readonly [string, number]>,
  cfg: { bpm: number; density: number; brightness: number },
  seconds: number, attempts = 3,
): Promise<Buffer> {
  let last: unknown = null
  for (let i = 0; i < attempts; i++) {
    try {
      return await oneSession(key, model, prompts, cfg, seconds)
    } catch (e) {
      if (!isConnectError(e)) throw e
      last = e
      console.log(`  建连失败（第 ${i + 1}/${attempts} 次）：${e instanceof Error ? e.name : String(e)}: ${e instanceof Error ? e.message : ''}`)
      await sleep(2 * (i + 1) * 1000)
    }
  }
  throw new ProviderError(`连续 ${attempts} 次连不上音乐流：${String(last)}`)
}

/** 付费层的一次成型路径（免费层会被 429 挡掉）。 */
async function captureHttp(key: string, model: string, prompt: string): Promise<Buffer> {
  const resp = await fetch('https://generativelanguage.googleapis.com/v1beta/interactions', {
    method: 'POST',
    headers: { 'x-goog-api-key': key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, input: prompt }),
    signal: AbortSignal.timeout(600_000),
  })
  const body = await resp.text()
  if (!resp.ok) {
    if (body.includes('Free Tier')) {
      throw new FeuilleError(`${model} 在这把 key 上是付费模型，免费层额度为 0：\n${body.slice(0, 300)}\n→ 换 --model lyria-realtime-exp（$0）`)
    }
    throw new ProviderError(`lyria HTTP ${resp.status}：${body.slice(0, 300)}`)
  }
  // outputs 里 type=="audio" 的 data 是 base64 音频（文档形状）。这条
  // HTTP 路径从未在付费 key 上实测过（免费层直接 429），所以下面解不出
  // 容器就大声失败，绝不把「猜测的格式」当事实写盘。
  const doc = JSON.parse(body) as { outputs?: Array<{ type?: string; data?: string }>, [k: string]: unknown }
  for (const out of doc.outputs ?? []) {
    if (out.type === 'audio' && out.data) return Buffer.from(out.data, 'base64')
  }
  throw new ProviderError(`lyria 响应里没有音频（顶层键：${Object.keys(doc).sort()}）`)
}

interface GenArgs {
  model: string
  prompt: string[]
  text?: string
  duration: number
  bpm: number
  density: number
  brightness: number
}

/** → (音频, is_raw_pcm)。raw PCM 只有实时后端；HTTP 后端自带容器。 */
async function genLyria(a: GenArgs): Promise<[Buffer, boolean]> {
  const key = loadLyriaKey()
  const realtime = a.model === 'lyria-realtime-exp'
  if (!realtime && !a.text) {
    throw new FeuilleError('--text 是 --model lyria-3.x 这条 HTTP 后端必需的')
  }
  if (realtime) {
    const prompts: Array<readonly [string, number]> = a.prompt.map((t, i) => [t, Math.max(0.1, pyRound(1.0 - 0.1 * i, 1))])
    if (prompts.length === 0) {
      throw new FeuilleError('至少给一个 --prompt（realtime 后端吃加权短词）')
    }
    console.log(`[lyria] ${a.model} 目标 ${pyG(a.duration)}s · 请求 ${pyG(padRequest(a.duration))}s（已垫 ${pyG(PAD_FACTOR)}×——实时后端短约 10% 是实测规律） · ${prompts.map(([t, w]) => `${t}(${w.toFixed(1)})`).join(' + ')}`)
    const pcm = await captureRealtime(key, a.model, prompts,
      { bpm: a.bpm, density: a.density, brightness: a.brightness },
      padRequest(a.duration))
    return [pcm, true]
  }
  console.log(`[lyria] ${a.model} 一次性生成`)
  return [await captureHttp(key, a.model, a.text!), false]
}

/** 自带容器的音频（lyria HTTP 后端）不能当裸 PCM 用。
 *
 * 统一先用 ffmpeg 解码到本命令的约定格式；解不动说明响应形状与假设
 * 不符，该响亮失败而不是静默出废文件。
 */
function toPcm(payload: Buffer): Buffer {
  const d = mkdtempSync(join(tmpdir(), 'bgm-'))
  try {
    const t = join(d, 'in.audio')
    writeFileSync(t, payload)
    const r = spawnSync(ffmpegBin(),
      ['-v', 'error', '-i', t, '-f', 's16le', '-ar', String(RATE), '-ac', String(CHANNELS), 'pipe:1'],
      { maxBuffer: 128 * 1024 * 1024, timeout: 300_000 })
    if (r.status !== 0 || r.stdout == null || r.stdout.length === 0) {
      throw new FeuilleError('供应商音频解码失败（端点形状与假设不符——lyria HTTP '
        + '这几条通路从未实测过，请把上面的报错留存）：\n'
        + (r.stderr ?? '').toString().slice(0, 300))
    }
    return r.stdout
  } finally {
    rmSync(d, { recursive: true, force: true })
  }
}

// ============================================================
//  解码与实测
// ============================================================

export interface Measure {
  duration_s: number
  rms_dbfs: number | null
  peak_dbfs: number | null
}

/** 时长 / RMS / 峰值。volumedetect 与 loudnorm 的输出都在 info 级，别加 -v error。 */
export function measure(path: string): Measure {
  const r = spawnSync(ffmpegBin(), ['-i', path, '-af', 'volumedetect', '-f', 'null', '-'],
    { maxBuffer: 16 * 1024 * 1024, timeout: 300_000 })
  const se = r.stderr?.toString() ?? ''
  const rms = /mean_volume: (-?[\d.inf]+) dB/.exec(se)
  const peak = /max_volume: (-?[\d.inf]+) dB/.exec(se)
  const dur = audio.probeDuration(path)
  const f = (m: RegExpExecArray | null): number | null => {
    if (!m) return null
    const s = m[1]!
    if (s === 'inf') return Number.POSITIVE_INFINITY
    if (s === '-inf') return Number.NEGATIVE_INFINITY
    return Number(s)
  }
  return { duration_s: pyRound(dur, 3), rms_dbfs: f(rms), peak_dbfs: f(peak) }
}

/** 起始包络自相关估拍。用来反查「按 48 kHz 解读」这个假设（见文件头）。 */
export function estBpm(pcm: Buffer, rate: number): number | null {
  // 尾巴上不完整的帧丢掉（奇数字节、或奇数个样点都过不了声道 reshape）
  const usable = Math.floor(Math.floor(pcm.length / 2) / CHANNELS) * CHANNELS * 2
  const nFrames = usable / (2 * CHANNELS)
  if (nFrames < rate) return null // 不到 1 秒，谈不上拍
  const hop = 512
  const n = Math.floor(nFrames / hop)
  const env = new Float64Array(n)
  for (let i = 0; i < n; i++) {
    let s = 0
    for (let j = 0; j < hop; j++) {
      const f = i * hop + j
      const l = pcm.readInt16LE(f * 4)
      const r = pcm.readInt16LE(f * 4 + 2)
      const m = (l + r) / 2
      s += m * m
    }
    env[i] = Math.sqrt(s / hop)
  }
  const onset = new Float64Array(n)
  onset[0] = 0 // np.diff(env, prepend=env[0]) → env[0]−env[0]
  for (let i = 1; i < n; i++) onset[i] = Math.max(0, env[i]! - env[i - 1]!)
  let mean = 0
  for (let i = 0; i < n; i++) mean += onset[i]!
  mean /= n
  for (let i = 0; i < n; i++) onset[i] = onset[i]! - mean
  let any = false
  for (let i = 0; i < n; i++) {
    if (onset[i]! !== 0) { any = true; break }
  }
  if (!any) return null
  const fps = rate / hop
  const lo = Math.trunc((fps * 60) / 200), hi = Math.trunc((fps * 60) / 50) // 只看 50–200 BPM
  if (hi >= n) return null
  // np.correlate(onset, onset, 'full')[N-1:] 的可用段 = 自相关 r[k]（k=0..N-1）；
  // argmax 只扫 [lo, hi)，np.argmax 取首个最大——`>` 严格比较同款语义
  let bestK = -1, bestV = -Infinity
  for (let k = lo; k < hi; k++) {
    let r = 0
    for (let i = 0; i + k < n; i++) r += onset[i]! * onset[i + k]!
    if (r > bestV) { bestV = r; bestK = k }
  }
  return pyRound((60.0 * fps) / bestK, 1)
}

/** 用拍速反查「按 48 kHz 解读」这个假设。
 *
 * 两种病因必须分开：**采样率读错**（文件整体变调，致命）和**模型没照 bpm 走**
 * （Lyria RealTime 把 bpm 当软提示，音乐本身没毛病）。混为一谈就会把好曲子
 * 当坏文件扔掉。所以先认「按文档的 48 kHz 直读」，直读对不上才去问
 * 「有没有某个采样率误读的换算比能解释它」——顺序反过来会误杀
 * （实测踩过：175.8 BPM 同时落进「直接 168±5%」和「÷1.0884 后 161.5≈168」
 * 两个分支）。
 */
export function verifyRate(measuredBpm: number | null, wantBpm: number): string {
  if (measuredBpm === null) {
    return 'inconclusive（起始包络过弱，测不出拍速）——请人耳确认音高正常'
  }
  const folds = [wantBpm, wantBpm * 2, wantBpm / 2]
  // 先认直接解读：48 kHz 是模型卡声明、且 L≠R（真立体声）佐证过的格式。
  for (const cand of folds) {
    if (Math.abs(measuredBpm - cand) <= cand * 0.05) {
      return `ok（实测 ${pyFloat(measuredBpm)} BPM 命中请求 ${pyG(wantBpm)} 的 ${pyG(cand / wantBpm)} 倍，48 kHz 解读可信）`
    }
  }
  for (const ratio of RATE_RATIOS) { // 48k↔44.1k 之间读错
    for (const got of [measuredBpm / ratio, measuredBpm * ratio]) {
      for (const cand of folds) {
        if (Math.abs(got - cand) <= cand * 0.05) {
          return `MISMATCH：实测 ${pyFloat(measuredBpm)} BPM 对不上 ${pyG(wantBpm)}，`
            + `但换算比 ${pyFixed(ratio, 4)} 后 ≈ ${pyFixed(got, 0)} BPM —— `
            + '采样率解读很可能错了，**不要用这个文件**'
        }
      }
    }
  }
  return `inconclusive：实测 ${pyFloat(measuredBpm)} BPM 离请求 ${pyG(wantBpm)} 远，`
    + '也套不上 48k↔44.1k 的换算比——更像模型没照 bpm 走'
    + '（Lyria RealTime 把 bpm 当软提示）；拍速法判不了采样率，请人耳确认音高。'
}

/** 前若干秒的能量频段分布。 */
export function bandShare(path: string, seconds = 15.0): Record<string, number> {
  const w = readWav(path)
  const sr = w.sampleRate, ch = w.channels
  const frames = Math.min(Math.floor(w.data.length / (ch * 2)), Math.trunc(sr * seconds))
  const n = frames
  const x = new Float64Array(n)
  for (let f = 0; f < n; f++) {
    let s = 0
    for (let c = 0; c < ch; c++) s += w.data.readInt16LE((f * ch + c) * 2)
    x[f] = s / ch / 32768
  }
  if (n < sr) return {}
  // np.hanning(M) = 0.5·(1−cos(2πn/(M−1)))
  const win = new Float64Array(n)
  for (let i = 0; i < n; i++) win[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (n - 1)))
  const xw = new Float64Array(n)
  for (let i = 0; i < n; i++) xw[i] = x[i]! * win[i]!
  const S = rfftMag(xw)
  const p = new Float64Array(S.length)
  let tot = 0
  for (let k = 0; k < S.length; k++) {
    p[k] = S[k]! * S[k]!
    tot += p[k]!
  }
  if (tot === 0) tot = 1.0
  const bands: Record<string, readonly [number, number]> = {
    '<100': [0, 100], '100-400': [100, 400], '400-1k': [400, 1000],
    '1k-3k': [1000, 3000], '>3k': [3000, sr / 2],
  }
  const out: Record<string, number> = {}
  for (const [k, [lo, hi]] of Object.entries(bands)) {
    let s = 0
    for (let b = 0; b < S.length; b++) {
      const fr = (b * sr) / n // np.fft.rfftfreq(N, 1/sr)
      if (fr >= lo && fr < hi) s += p[b]!
    }
    out[k] = pyRound((s / tot) * 100, 2)
  }
  return out
}

/** 床的「亮不亮」判据。
 *
 * 实测踩过的坑：稀疏提示词 + brightness 0.4 会让 Lyria RealTime 吐一条
 * **低频嗡鸣**——>3 kHz 只剩 0.1%、70% 能量压在 60–100 Hz，戴着耳机也听不出来
 * （旁白盖住了），但混音后床等于没有。配器不对要靠频段占比判，不能靠「听」。
 */
export function tonalVerdict(bands: Record<string, number>): string {
  if (Object.keys(bands).length === 0) return 'inconclusive（不足 1 秒，测不了）'
  const body = bands['400-1k']! + bands['1k-3k']!
  if (bands['>3k']! < 1.0 && bands['<100']! > 45) {
    return `⚠ 太暗：>3 kHz 仅 ${pyFloat(bands['>3k']!)}%、<100 Hz 占 ${pyFloat(bands['<100']!)}%——多半提示词把模型带成了低音嗡鸣；调高 brightness/密度后重生成`
  }
  if (body < 3.0) {
    return `⚠ 中高频偏少（400 Hz–3 kHz 共 ${pyFixed(body, 1)}%），床会听着发闷`
  }
  return `ok（400 Hz–3 kHz 共 ${pyFixed(body, 1)}%，>3 kHz ${pyFloat(bands['>3k']!)}%）`
}

/** 只有 Lyria 实时后端回裸 PCM；HTTP 后端自带容器。 */
export function isRealtimePcm(model: string | null): boolean {
  return model === 'lyria-realtime-exp'
}

// ============================================================
//  床长判据（纯函数，供反向验证）
// ============================================================

export const PAD_FACTOR = 1.15
// 实时后端「请求 80s 实得 78.0s、请求 62s 实得 54.0s」——短约 10% 是实测规律
// （SKILL.md 坑 1），不是偶发。请求端垫 15% 让「床 ≥ 目标」成为结构保证而非运气。

/** 实时后端的请求垫量：目标床长 → 实际请求秒数。纯函数，反向验证在
 * packages/bgm/test/gen_bgm.test.ts（凿洞：目标 80 → 请求 92，不是 80）。 */
export function padRequest(targetS: number): number {
  return pyRound(targetS * PAD_FACTOR, 3)
}

/** 床长判据（SKILL.md 判据表「床 ≥ 成片时长」的机器形态）。
 *
 * 目标 = --duration（床要盖多长）；实测短于目标 − 1s 容差即 ⚠。
 * ⚠ 会进 blocked（退出码 2）——判据不通过要让退出码说话，打印警告却返回 0
 * 就是假绿灯。反向验证同上（凿洞：实测 78 < 目标 80 → ⚠）。
 */
export function bedLenVerdict(measuredS: number, targetS: number): string {
  if (measuredS + 1.0 < targetS) {
    return `⚠ 成曲 ${pyG(measuredS)}s < 目标 ${pyG(targetS)}s（超出 1s 容差）——床短于成片，尾部会裸奔，不要挂床`
  }
  return `ok（${pyG(measuredS)}s ≥ 目标 ${pyG(targetS)}s）`
}

/** 低于 2 秒的数据一律当失败——省得把半截断流当成功交出去。 */
export function rateGuardBytes(): number {
  return RATE * CHANNELS * WIDTH * 2
}

// ============================================================
//  主流程
// ============================================================

/** 按现有边车重算判据并回写。
 *
 * 判据会演进（实测踩坑就会改），但音乐不必为改判据重生成一次——Lyria
 * RealTime 不接受 seed，重生成拿到的也是另一首。边车里的结论是**推出来的**，
 * 推论的前提变了就该重推，不该手改。
 */
export function recheck(out: string, side: string, narrationDb: number | null, targetDb: number): number {
  if (!(existsSync(out) && existsSync(side))) {
    throw new FeuilleError(`${out} 或边车不存在，没什么可复核的`)
  }
  const rec = JSON.parse(readFileSync(side, 'utf8')) as Record<string, unknown>
  if (!('bpm_requested' in rec) || !('model' in rec)) {
    throw new FeuilleError(`${side} 缺 bpm_requested/model——它可能不是本脚本写的，或是旧版边车；没有这两个前提判据推不出来`)
  }
  let narr = narrationDb
  if (narr === null) {
    const env = process.env['NARRATION_RMS_DB'] ?? ''
    narr = env ? Number(env) : null
  }
  const m = measure(out)
  rec['measured'] = m
  rec['bpm_detected'] = estBpm(readWav(out).data, RATE)
  rec['rate_check'] = isRealtimePcm(rec['model'] as string)
    ? verifyRate(rec['bpm_detected'] as number | null, rec['bpm_requested'] as number)
    : 'n/a（自带容器，采样率由音频头决定）'
  const bands = bandShare(out)
  rec['band_share_pct'] = bands
  rec['tonal_check'] = tonalVerdict(bands)
  // 床长判据随判据演进重推：目标取边车（新边车 duration_target_s；旧边车只有
  // duration_requested_s，退化取它——旧床未垫量，请求即目标）。
  const t = rec['duration_target_s'] !== undefined ? rec['duration_target_s'] : rec['duration_requested_s']
  if (t !== undefined && t !== null) {
    rec['bed_len_check'] = bedLenVerdict(m.duration_s, Number(t))
  }
  if (narr !== null) {
    const rms = m.rms_dbfs as number // 纯静音/解析失败在 measure 处就炸，这里不再判空
    rec['suggested_gain'] = pyRound(10 ** ((narr - targetDb - rms) / 20), 4)
    rec['gain_basis'] = `旁白 ${pyG(narr)} dBFS − 目标 ${pyG(targetDb)} dB − 床 ${pyFloat(rms)} dBFS`
  }
  writeFileSync(side, JSON.stringify(rec, null, 2) + '\n', 'utf8')
  console.log(`\n  ${basename(out)}  ${pyFloat(m.duration_s)}s  RMS ${pyFloat(m.rms_dbfs)} dBFS`)
  console.log(`  拍速反查：${rec['rate_check']}`)
  console.log(`  配器判据：${rec['tonal_check']}`)
  if ('bed_len_check' in rec) console.log(`  床长判据：${rec['bed_len_check']}`)
  if ('suggested_gain' in rec) {
    console.log(`  → gain ${pyFloat(rec['suggested_gain'] as number)}（${rec['gain_basis']}）`)
  }
  const blocked = String(rec['rate_check']).startsWith('MISMATCH')
    || String(rec['tonal_check']).includes('⚠')
    || String(rec['bed_len_check'] ?? '').startsWith('⚠')
  return blocked ? 2 : 0
}

/** 只做凭据探测，不动网络——生成前先看一眼 Lyria 的 key 在不在。 */
function listProviders(envFile: string | null): number {
  const got = detectProviders()
  for (const [name, src] of got) console.log(`  ${name.padEnd(8)} ✓ ${src}`)
  if (envFile) {
    console.log(`  key 文件已加载：${envFile}`)
  } else {
    console.log(`  key 文件：${keyFile()}（不存在或没可解析行；样例见 skills/bgm-bed/references/keys.env.sample）`)
  }
  if (got.length === 0) {
    console.log(`\nLyria 没有可用凭据：\n`
      + '  lyria    GEMINI_API_KEY（或 ~/.gemini_api_key）——实测过，免费层可用\n'
      + `统一配置：把 key 写进 ${keyFile()}（环境变量优先于该文件）\n`
      + '（MCode 内置音乐线无需 key，不经本脚本，见 SKILL.md）')
    return 1
  }
  console.log('\nLyria 线凭据就绪，可以生成。')
  return 0
}

const USAGE = 'usage: feuille bgm gen --out <wav> [--prompt 短词]… [--text 一段] [--model lyria-realtime-exp] '
  + '[--duration 62] [--bpm 72] [--density 0.6] [--brightness 0.4] '
  + '[--narration-rms-db -21.4] [--target-under-db 16] [--force] [--recheck] [--list-providers]'

export async function main(argv: string[]): Promise<number> {
  let out: string | null = null
  const prompt: string[] = []
  let text: string | undefined
  let model = 'lyria-realtime-exp'
  let duration = 62.0
  let bpm = 72
  let density = 0.6
  let brightness = 0.4
  let narrationRmsDb: number | undefined
  let targetUnderDb = 16.0
  let force = false
  let recheckFlag = false
  let listProvidersFlag = false
  const num = (flag: string, s: string): number => {
    const v = Number(s)
    if (Number.isNaN(v)) throw new FeuilleError(`${flag} 要数值：${s}`)
    return v
  }
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i]!
    const take = (): string => {
      if (i + 1 >= argv.length) throw new FeuilleError(`${t} 缺值`)
      return argv[++i]!
    }
    if (t === '--out') out = take()
    else if (t === '--prompt') prompt.push(take())
    else if (t === '--text') text = take()
    else if (t === '--model') model = take()
    else if (t === '--duration') duration = num(t, take())
    else if (t === '--bpm') {
      const v = num(t, take())
      if (!Number.isInteger(v)) throw new FeuilleError(`--bpm 要整数：${v}`)
      bpm = v
    } else if (t === '--density') density = num(t, take())
    else if (t === '--brightness') brightness = num(t, take())
    else if (t === '--narration-rms-db') narrationRmsDb = num(t, take())
    else if (t === '--target-under-db') targetUnderDb = num(t, take())
    else if (t === '--force') force = true
    else if (t === '--recheck') recheckFlag = true
    else if (t === '--list-providers') listProvidersFlag = true
    else if (t.startsWith('--')) throw new FeuilleError(`未知旗标：${t}`)
    else {
      console.error(USAGE) // argparse 同款：多余位置参数 → usage + 退出码 2
      return 2
    }
  }

  if (listProvidersFlag) return listProviders(loadEnvFile())
  if (out === null) throw new FeuilleError('--out 必填（--list-providers 除外）')
  loadEnvFile()

  const outPath = resolve(out.replace(/^~(?=\/|$)/, homedir()))
  const side = `${outPath}.json`
  if (recheckFlag) return recheck(outPath, side, narrationRmsDb ?? null, targetUnderDb)
  for (const p of [outPath, side]) {
    if (existsSync(p) && !force) {
      throw new FeuilleError(`${p} 已存在；生成类命令默认不覆盖（纪律 13）。确要覆盖加 --force`)
    }
  }
  if (prompt.length === 0 && !text) {
    throw new FeuilleError('至少给一个 --prompt 或一段 --text——lyria 要提示词')
  }

  let got: [Buffer, boolean]
  try {
    got = await genLyria({ model, prompt, text, duration, bpm, density, brightness })
  } catch (e) {
    if (e instanceof ProviderError) {
      console.log(`FAIL：[lyria] ${(e as Error).message}`)
      return 1
    }
    throw e
  }
  const pcm = got[1] ? got[0] : toPcm(got[0])

  if (pcm.length < rateGuardBytes()) {
    throw new FeuilleError(`收到的音频只有 ${pcm.length} 字节（不足 2 秒），不成曲——多半是配额/网络问题，重试`)
  }
  writeWav(outPath, pcm)

  const m = measure(outPath)
  const bpmSeen = estBpm(pcm, RATE)
  const realtime = isRealtimePcm(model)
  const verdict = realtime
    ? verifyRate(bpmSeen, bpm)
    : 'n/a（自带容器，采样率由音频头决定）'
  const bands = bandShare(outPath)
  const tonal = tonalVerdict(bands)
  const bedCheck = bedLenVerdict(m.duration_s, duration)
  console.log(`  床长判据：${bedCheck}`)

  const rec: Record<string, unknown> = {
    provider: 'lyria', model, prompts: prompt, text: text ?? null,
    bpm_requested: bpm,
    duration_target_s: duration,
    duration_requested_s: realtime ? padRequest(duration) : duration,
    pad_factor: realtime ? PAD_FACTOR : null,
    format: { rate: RATE, channels: CHANNELS, bit_depth: WIDTH * 8 },
    measured: m, bpm_detected: bpmSeen, rate_check: verdict,
    band_share_pct: bands, tonal_check: tonal,
    bed_len_check: bedCheck,
  }
  if (m.rms_dbfs !== null && narrationRmsDb !== undefined) {
    const gain = 10 ** ((narrationRmsDb - targetUnderDb - m.rms_dbfs) / 20)
    rec['suggested_gain'] = pyRound(gain, 4)
    rec['gain_basis'] = `旁白 ${pyG(narrationRmsDb)} dBFS − 目标 ${pyG(targetUnderDb)} dB − 床 ${pyG(m.rms_dbfs)} dBFS`
  }
  writeFileSync(side, JSON.stringify(rec, null, 2) + '\n', 'utf8')

  console.log(`\n  ${basename(outPath)}  [lyria]  ${pyFloat(m.duration_s)}s  RMS ${pyFloat(m.rms_dbfs)} dBFS  峰值 ${pyFloat(m.peak_dbfs)} dBFS`)
  console.log(`  拍速反查：${verdict}`)
  console.log(`  频段分布：${Object.entries(bands).map(([k, v]) => `${k} ${pyFloat(v)}%`).join('  ') || 'n/a'}`)
  console.log(`  配器判据：${tonal}`)
  console.log(`  床长判据：${bedCheck}`)
  if ('suggested_gain' in rec) {
    console.log(`  → video.json 写 "gain": ${pyFloat(rec['suggested_gain'] as number)}（${rec['gain_basis']}）`)
  }
  console.log(`  边车：${side}`)
  // 判据不通过要让**退出码**说话。文件照样落盘供排查，但「打印了警告却返回 0」
  // 就是纪律 12 说的那种假绿灯——上层脚本会把它当成功继续往下走。
  const blocked = verdict.startsWith('MISMATCH') || tonal.startsWith('⚠') || bedCheck.startsWith('⚠')
  if (blocked) {
    console.log(`\nFAIL：${[verdict, tonal, bedCheck].filter((x) => x.includes('⚠') || x.startsWith('MISMATCH')).join('；')}`)
    console.log('      文件已落盘供排查（改名利落归档进 rejected/，别删——阈值回溯要用），但**不要**把它挂进 video.json。')
    return 2
  }
  return 0
}
