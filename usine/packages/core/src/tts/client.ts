// client.ts — edge-tts WebSocket 客户端（edge-tts 7.3.1 Communicate 的 TS 移植）。
//
// 协议事实（2026-10-16 服务端换血后实测有效）：
// - 端点仍是 speech.platform.bing.com；403 的根因是令牌必须升 v2（drm.ts）。
// - 握手头必须带 Origin chrome-extension://… 与 Cookie muid=…。
// - 帧解析的切片口径与 Python 逐字节一致：文本帧 body 从首个 \r\n\r\n 后
//   headerLength+2 处起（前导 \r\n 是 JSON 合法空白）；二进制帧前 2 字节
//   大端长度 N 含长度字节自身、body 从 N+2 起（头部区以 \r\n 结尾故无损）。
//   不许按"看起来更对"的方式重切——以 Python 实测行为为准。
// - 403 带服务端 Date 头：读出时钟偏斜、修正后重试一次（drift 机器常见）。
// - NoAudioReceived：偶发瞬时抖动，同文本重试即成功；参数错误稳定复现——
//   只对它重试，其余异常第一次就抛。
// - **连接类错误（2026-11-04 实测新增）**：到 speech.platform.bing.com 的
//   TCP 连接受网络侧影响，只有一部分 SYN 会被应答。Node 的 `ws` 走
//   `autoSelectFamily`，每个地址只等 `autoSelectFamilyAttemptTimeout`
//   （默认 250ms）就换下一个地址，于是 4 个地址全被放弃 → 抛
//   AggregateError（内含 ETIMEDOUT / ENETUNREACH）。实测同一台机器上
//   6 次尝试只成 2 次；同机 `curl` 单地址长等待（0.8–18s）却 5/6 成。
//   结论：**这不是「端点不可达」，是「给每个地址的等待太短」**。修法两条：
//   ① 把 `autoSelectFamilyAttemptTimeout` 抬到秒级；
//   ② 连接类错误按线性退避**重试**（不是第一次就抛）。
//   注意 `speech.service.bing.com` 证书不匹配是**另一个主机**（本次问题
//   与它无关），别据此判断本产线的 TTS 不可用。
//
// 长文本分片（edge-tts 7.3.1 口径）：转义+清洗后按 4096 字节切（split.ts），
// 每段各开一条连接、各重置 chunkAudioBytes、各享一次 403 偏斜重试；段间
// 词级时间戳用 CBR 字节数精确折算补偿（见 turn.end 分支）。
import WebSocket, { type RawData } from "ws"

import {
  SEC_MS_GEC_VERSION,
  WSS_URL,
  adjustClockSkewSeconds,
  currentUnixTimestamp,
  generateSecMsGecV2,
  headersWithMuid,
} from "./drm.js"
import type { Word } from "./pure.js"
import { splitTextByByteLength } from "./split.js"

// 重试退避基数（秒，线性 × 尝试次数）。测试把它改 0，免得反向验证慢。
export let RETRY_BACKOFF = 1.2
export const RETRY_TRIES = 5
export function setRetryBackoffForTests(seconds: number): void {
  RETRY_BACKOFF = seconds
}

/** 连接类错误的 socket errno 集合（见文件头「连接类错误」段）。 */
const CONNECT_ERROR_CODES = new Set([
  "ETIMEDOUT",
  "ENETUNREACH",
  "ECONNREFUSED",
  "ECONNRESET",
  "EHOSTUNREACH",
  "EHOSTDOWN",
  "ENETDOWN",
  "EPIPE",
  "EAI_AGAIN",
  "EAI_FAIL",
])

/** `autoSelectFamily` 每个地址的等待（毫秒）。默认 250ms 太短——见文件头。 */
export const CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS = 2_000

/** 连接类错误的重试次数（线性退避）。环境变量可覆盖，给批量预生成留余量。 */
function connectRetryTries(): number {
  const raw = process.env["FEUILLE_TTS_CONNECT_TRIES"]
  const n = raw ? Number.parseInt(raw, 10) : Number.NaN
  return Number.isFinite(n) && n > 0 ? n : 6
}

/** 从错误（及其 AggregateError 内层）里收集 socket errno 码。 */
function collectErrorCodes(e: unknown, out: string[]): string[] {
  if (typeof e !== "object" || e === null) return out
  const code = (e as { code?: unknown }).code
  if (typeof code === "string") out.push(code)
  const errors = (e as { errors?: unknown }).errors
  if (Array.isArray(errors)) {
    for (const inner of errors) collectErrorCodes(inner, out)
  }
  return out
}

/** 这个错误是不是「连不上」类（可重试）？ */
export function isConnectError(e: unknown): boolean {
  const codes = collectErrorCodes(e, [])
  return codes.length > 0 && codes.every((c) => CONNECT_ERROR_CODES.has(c))
}

export class NoAudioReceived extends Error {
  constructor(message = "No audio was received. Please verify that your parameters are correct.") {
    super(message)
    this.name = "NoAudioReceived"
  }
}
export class UnexpectedResponse extends Error {
  constructor(message: string) {
    super(message)
    this.name = "UnexpectedResponse"
  }
}
export class UnknownResponse extends Error {
  constructor(message: string) {
    super(message)
    this.name = "UnknownResponse"
  }
}
/** 握手被服务端拒绝（含状态码与 Date 头，供 403 偏斜修正）。 */
export class HttpHandshakeError extends Error {
  constructor(
    readonly status: number,
    readonly serverDate: string | null,
  ) {
    super(`WebSocket handshake failed: HTTP ${status}`)
    this.name = "HttpHandshakeError"
  }
}

export type Chunk =
  | { type: "audio"; data: Uint8Array }
  | { type: "WordBoundary"; offset: number; duration: number; text: string }
  | { type: "SentenceBoundary"; offset: number; duration: number; text: string }

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const

/** JS 风格时间串（Python date_to_string 的口径，服务端只认这个形状）。 */
function dateToString(): string {
  const d = new Date()
  const wd = WEEKDAYS[d.getUTCDay()]!
  const mo = MONTHS[d.getUTCMonth()]!
  const dd = String(d.getUTCDate()).padStart(2, "0")
  const hh = String(d.getUTCHours()).padStart(2, "0")
  const mi = String(d.getUTCMinutes()).padStart(2, "0")
  const ss = String(d.getUTCSeconds()).padStart(2, "0")
  return `${wd} ${mo} ${dd} ${d.getUTCFullYear()} ${hh}:${mi}:${ss} GMT+0000 (Coordinated Universal Time)`
}

function connectId(): string {
  const buf = new Uint8Array(16)
  crypto.getRandomValues(buf)
  return Buffer.from(buf).toString("hex")
}

function escapeXml(s: string): string {
  return s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
}

function unescapeXml(s: string): string {
  return s.replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&")
}

/** 服务端不支持的控制字符（OCR 文本常见竖直制表符）→ 空格。 */
function removeIncompatibleCharacters(s: string): string {
  let out = ""
  for (const ch of s) {
    const code = ch.codePointAt(0)!
    out += (code <= 8) || (code >= 11 && code <= 12) || (code >= 14 && code <= 31)
      ? " "
      : ch
  }
  return out
}

export interface TTSRequest {
  text: string
  voice: string
  rate: string
  pitch: string
  volume?: string
}

function mkssml(req: TTSRequest, escapedText: string): string {
  const volume = req.volume ?? "+0%"
  return (
    "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
    `<voice name='${req.voice}'>` +
    `<prosody pitch='${req.pitch}' rate='${req.rate}' volume='${volume}'>` +
    `${escapedText}` +
    "</prosody>" +
    "</voice>" +
    "</speak>"
  )
}

/** 头区 + 起始偏移的解析（切片口径与 Python get_headers_and_data 一致）。 */
function getHeadersAndData(
  data: Buffer,
  headerLength: number,
): [Map<string, string>, Buffer] {
  const headers = new Map<string, string>()
  for (const line of data.subarray(0, headerLength).toString("latin1").split("\r\n")) {
    const i = line.indexOf(":")
    if (i >= 0) headers.set(line.slice(0, i), line.slice(i + 1))
  }
  return [headers, data.subarray(headerLength + 2)]
}

class AsyncQueue<T> {
  private items: T[] = []
  private waiters: ((r: IteratorResult<T>) => void)[] = []
  private done = false
  push(item: T): void {
    const w = this.waiters.shift()
    if (w) w({ value: item, done: false })
    else this.items.push(item)
  }
  finish(): void {
    this.done = true
    for (const w of this.waiters) w({ value: undefined, done: true })
    this.waiters = []
  }
  [Symbol.asyncIterator](): AsyncIterator<T> {
    return {
      next: (): Promise<IteratorResult<T>> => {
        const it = this.items.shift()
        if (it !== undefined) return Promise.resolve({ value: it, done: false })
        if (this.done) return Promise.resolve({ value: undefined, done: true })
        return new Promise((resolve) => this.waiters.push(resolve))
      },
    }
  }
}

interface StreamState {
  offsetCompensation: number
  lastDurationOffset: number
  chunkAudioBytes: number
  cumulativeAudioBytes: number
}

async function* streamOnce(
  req: TTSRequest,
  segment: Buffer,
  state: StreamState,
): AsyncGenerator<Chunk> {
  const connectionId = connectId()
  const url =
    `${WSS_URL}&ConnectionId=${connectionId}` +
    `&Sec-MS-GEC=${generateSecMsGecV2()}` +
    `&Sec-MS-GEC-Version=${SEC_MS_GEC_VERSION}`
  const ws = new WebSocket(url, {
    headers: headersWithMuid(),
    handshakeTimeout: 10_000,
    // 见文件头：默认 250ms 会把慢应答的地址全放弃掉。
    // 这个键住在 net.TcpSocketConnectOpts（@types/node net.d.ts:68），
    // ws 的 ClientOptions 类型没收它，但 ws 把整个 options 透传给
    // http.request → net.connect，运行时有效——所以这里带一道窄 cast。
    autoSelectFamilyAttemptTimeout: CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS,
  } as WebSocket.ClientOptions & { autoSelectFamilyAttemptTimeout: number })

  const queue = new AsyncQueue<{ data: Buffer; isBinary: boolean }>()
  let openError: Error | undefined
  let socketError: Error | undefined
  const opened = new Promise<void>((resolve, reject) => {
    ws.on("open", () => resolve())
    ws.on("unexpected-response", (_req, res) => {
      const err = new HttpHandshakeError(res.statusCode ?? 0, res.headers.date ?? null)
      openError = err
      queue.finish()
      reject(err)
    })
    ws.on("error", (err: Error) => {
      if (!openError) {
        openError = err
        socketError = err
      }
      queue.finish()
      reject(openError)
    })
  })
  ws.on("message", (data: RawData, isBinary: boolean) =>
    queue.push({ data: Buffer.isBuffer(data) ? data : Buffer.from(data as ArrayBuffer), isBinary }),
  )
  ws.on("close", () => queue.finish())

  try {
    await opened
  } catch (e) {
    // 握手失败时必须自己收尾：下面的 finally 只覆盖「已连上」的流，
    // 连不上时它根本不执行 → 每次失败漏一个 socket。
    ws.terminate()
    throw e
  }
  const wordBoundary = true
  ws.send(
    `X-Timestamp:${dateToString()}\r\n` +
      "Content-Type:application/json; charset=utf-8\r\n" +
      "Path:speech.config\r\n\r\n" +
      '{"context":{"synthesis":{"audio":{"metadataoptions":{' +
      `"sentenceBoundaryEnabled":"${wordBoundary ? "false" : "true"}",` +
      `"wordBoundaryEnabled":"${wordBoundary ? "true" : "false"}"` +
      '},' +
      '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"' +
      "}}}}\r\n",
  )
  ws.send(
    `X-RequestId:${connectId()}\r\n` +
      "Content-Type:application/ssml+xml\r\n" +
      `X-Timestamp:${dateToString()}Z\r\n` + // 尾部 Z 不是笔误——微软的 bug，Python 侧注释同源
      "Path:ssml\r\n\r\n" +
      mkssml(req, segment.toString("utf8")),
  )

  let audioWasReceived = false
  let completed = false
  try {
    for await (const msg of queue) {
      const data = msg.data
      if (!msg.isBinary) {
        const encoded = data.toString("utf8")
        const sep = encoded.indexOf("\r\n\r\n")
        if (sep < 0) throw new UnexpectedResponse("Text frame without header separator")
        const [headers, body] = getHeadersAndData(data, sep)
        const path = headers.get("Path") ?? ""
        if (path === "audio.metadata") {
          const parsed = parseMetadata(body.toString("utf8"), state)
          yield parsed
          state.lastDurationOffset = parsed.offset + parsed.duration
        } else if (path === "turn.end") {
          // 跨段偏移按 CBR 字节数精确折算（长文本元数据会漂，见 Python 侧注释）
          state.cumulativeAudioBytes += state.chunkAudioBytes
          state.offsetCompensation = Number(
            (BigInt(state.cumulativeAudioBytes) * 8n * 10_000_000n) / 48_000n,
          )
          state.chunkAudioBytes = 0
          completed = true
          break
        } else if (path !== "response" && path !== "turn.start") {
          throw new UnknownResponse(`Unknown path received: ${path}`)
        }
      } else {
        if (data.length < 2) {
          throw new UnexpectedResponse("Binary message missing the header length")
        }
        const headerLength = data.readUInt16BE(0)
        if (headerLength > data.length) {
          throw new UnexpectedResponse("Header length greater than the data length")
        }
        const [headers, body] = getHeadersAndData(data, headerLength)
        if (headers.get("Path") !== "audio") {
          throw new UnexpectedResponse("Binary message with non-audio path")
        }
        const contentType = headers.get("Content-Type") ?? ""
        if (contentType === "") {
          // 流终止帧：无 Content-Type 且无数据 → 正常；有数据 → 异常
          if (body.length === 0) continue
          throw new UnexpectedResponse("Binary message without Content-Type but with data")
        }
        if (contentType !== "audio/mpeg") {
          throw new UnexpectedResponse(`Unexpected Content-Type: ${contentType}`)
        }
        if (body.length === 0) {
          throw new UnexpectedResponse("Binary message missing the audio data")
        }
        audioWasReceived = true
        state.chunkAudioBytes += body.length
        yield { type: "audio", data: new Uint8Array(body) }
      }
    }
  } finally {
    ws.terminate()
  }
  if (socketError && !completed) throw socketError
  if (!audioWasReceived) throw new NoAudioReceived()
}

export type BoundaryChunk = Extract<Chunk, { type: "WordBoundary" } | { type: "SentenceBoundary" }>

function parseMetadata(raw: string, state: StreamState): BoundaryChunk {
  const doc = JSON.parse(raw) as {
    Metadata: { Type: string; Data?: { Offset: number; Duration: number; text: { Text: string } } }[]
  }
  for (const meta of doc.Metadata) {
    const type = meta.Type
    if (type === "WordBoundary" || type === "SentenceBoundary") {
      const d = meta.Data!
      const offset = d.Offset + state.offsetCompensation
      return { type, offset, duration: d.Duration, text: unescapeXml(d.text.Text) }
    }
    if (type === "SessionEnd") continue
    throw new UnknownResponse(`Unknown metadata type: ${type}`)
  }
  throw new UnexpectedResponse("No WordBoundary metadata found")
}

/** 403 → 按 Date 头修偏斜重试一次（Python stream() 的口径；逐段各享一次）。
 *
 * 导出供 karaoke 词级时间线直接消费（gen_tts 原版就是裸吃
 * edge_tts.Communicate.stream() 的音频块 + WordBoundary 事件，不带
 * synthOnce 的无词兜底——那是行合成语义，不是 karaoke 语义）。 */
export async function* stream(req: TTSRequest): AsyncGenerator<Chunk> {
  const state: StreamState = {
    offsetCompensation: 0,
    lastDurationOffset: 0,
    chunkAudioBytes: 0,
    cumulativeAudioBytes: 0,
  }
  const segments = splitTextByByteLength(
    escapeXml(removeIncompatibleCharacters(req.text)),
    4096,
  )
  for (const segment of segments) {
    state.chunkAudioBytes = 0
    yield* streamSegment(req, segment, state)
  }
}

/** 单次尝试先收完再发布：中途断流时，失败尝试的前缀不能进入最终音频。 */
async function* bufferedStreamOnce(
  req: TTSRequest,
  segment: Buffer,
  state: StreamState,
): AsyncGenerator<Chunk> {
  const pending: Chunk[] = []
  for await (const chunk of streamOnceImpl(req, segment, state)) pending.push(chunk)
  yield* pending
}

/** 一段的完整重试语义：403 偏斜修一次；连不上则线性退避重试。 */
async function* streamSegment(
  req: TTSRequest,
  segment: Buffer,
  state: StreamState,
): AsyncGenerator<Chunk> {
  const tries = connectRetryTries()
  for (let attempt = 1; ; attempt++) {
    try {
      yield* bufferedStreamOnce(req, segment, state)
      return
    } catch (e) {
      if (e instanceof HttpHandshakeError && e.status === 403) {
        if (!e.serverDate) throw new Error("No server date in headers.")
        const serverTs = Date.parse(e.serverDate) / 1000
        if (!Number.isFinite(serverTs)) {
          throw new Error(`Failed to parse server date: ${e.serverDate}`)
        }
        adjustClockSkewSeconds(serverTs - currentUnixTimestamp())
        state.chunkAudioBytes = 0
        yield* bufferedStreamOnce(req, segment, state)
        return
      }
      if (!isConnectError(e) || attempt >= tries) throw e
      state.chunkAudioBytes = 0
      await new Promise((r) => setTimeout(r, RETRY_BACKOFF * attempt * 1000))
    }
  }
}

/** 合成一段：收集 mp3 字节流与词级时间戳（offset/duration 为 100ns tick）。 */
export async function synthOnce(req: TTSRequest): Promise<{ mp3: Uint8Array; words: Word[] }> {
  const chunks: Uint8Array[] = []
  const words: Word[] = []
  for await (const chunk of stream(req)) {
    if (chunk.type === "audio") {
      chunks.push(chunk.data)
    } else if (chunk.type === "WordBoundary") {
      words.push({
        t: chunk.offset / 1e7,
        d: chunk.duration / 1e7,
        w: chunk.text,
      })
    }
  }
  if (words.length === 0) {
    // 无词边界事件的语言：整行一个伪词兜底（effective_dur 的绕开逻辑见 pure.ts）
    words.push({ t: 0.05, d: 0.5, w: req.text.slice(0, 12) })
  }
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const mp3 = new Uint8Array(total)
  let o = 0
  for (const c of chunks) {
    mp3.set(c, o)
    o += c.length
  }
  return { mp3, words }
}

/** 合成一行，只对 NoAudioReceived 重试（线性退避），其余异常第一次就抛。 */
export async function synthLine(
  req: TTSRequest,
  tries: number = RETRY_TRIES,
): Promise<{ mp3: Uint8Array; words: Word[] }> {
  const once = synthOnceOverride ?? synthOnce
  let last: unknown
  for (let attempt = 1; attempt <= tries; attempt++) {
    try {
      return await once(req)
    } catch (e) {
      if (!(e instanceof NoAudioReceived)) throw e
      last = e
      if (attempt < tries) {
        await new Promise((r) => setTimeout(r, RETRY_BACKOFF * attempt * 1000))
      }
    }
  }
  throw last
}

// 反向验证的测试接缝（ESM 导出绑定不可外部改写，故显式开口）。生产代码不碰。
type StreamOnceFn = (req: TTSRequest, segment: Buffer, state: StreamState) => AsyncGenerator<Chunk>
let streamOnceImpl: StreamOnceFn = streamOnce
export function overrideStreamOnceForTests(fn: StreamOnceFn | null): void {
  streamOnceImpl = fn ?? streamOnce
}

type SynthOnceFn = (req: TTSRequest) => Promise<{ mp3: Uint8Array; words: Word[] }>
let synthOnceOverride: SynthOnceFn | null = null
export function overrideSynthOnceForTests(fn: SynthOnceFn | null): void {
  synthOnceOverride = fn
}
