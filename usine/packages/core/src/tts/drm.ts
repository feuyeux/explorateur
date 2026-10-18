// drm.ts — Sec-MS-GEC v2 令牌（edge-tts 7.3.1 drm.py 的逐段移植，BigInt 承载
// Python 的无限位整数语义；判定口径 = 与 Python 固定时间戳输出逐字节相等）。
//
// 2026-10-16 起服务端只认 v2 令牌（旧 v1 403）；v2 = CS64 摘要 + 魔改 SHA-256
// 摘要的 "16hex-64hex" 组合。算法刻意混淆（换第 14/29 轮常量、双状态注入），
// 不许"化简"——任何"看起来等价"的重写都可能碰掉隐藏的进位路径。

export const TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
export const BASE_URL =
  "speech.platform.bing.com/consumer/speech/synthesize/readaloud"
export const WSS_URL = `wss://${BASE_URL}/edge/v1?TrustedClientToken=${TRUSTED_CLIENT_TOKEN}`
export const DEFAULT_VOICE = "en-US-EmmaMultilingualNeural"
export const CHROMIUM_FULL_VERSION = "143.0.3650.75"
export const CHROMIUM_MAJOR_VERSION = CHROMIUM_FULL_VERSION.split(".")[0]!
export const SEC_MS_GEC_VERSION = `2-${CHROMIUM_FULL_VERSION}`
export const TICKS_PER_SECOND = 10_000_000
export const MP3_BITRATE_BPS = 48_000

export const BASE_HEADERS: Record<string, string> = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" +
    ` (KHTML, like Gecko) Chrome/${CHROMIUM_MAJOR_VERSION}.0.0.0 Safari/537.36` +
    ` Edg/${CHROMIUM_MAJOR_VERSION}.0.0.0`,
  "Accept-Encoding": "gzip, deflate, br, zstd",
  "Accept-Language": "en-US,en;q=0.9",
}
export const WSS_HEADERS: Record<string, string> = {
  Pragma: "no-cache",
  "Cache-Control": "no-cache",
  Origin: "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
  "Sec-WebSocket-Version": "13",
  ...BASE_HEADERS,
}

const WIN_EPOCH = 11644473600

const MASK32 = 0xffffffffn

const SHA256_INITIAL = [
  0x6a09e667n, 0xbb67ae85n, 0x3c6ef372n, 0xa54ff53an, 0x510e527fn,
  0x9b05688cn, 0x1f83d9abn, 0x5be0cd19n,
] as const
const SHA256_STATE = [
  0xfd9fbea2n, 0x91243ce7n, 0xbe499094n, 0xcd2e1e0an, 0x6c006f49n,
  0x04bd35abn, 0xfeb0a7e4n, 0x03effbd2n,
] as const
const SHA256_SCHEDULE = [
  0xeb24bf9en, 0x1558691fn, 0xa0c09ee2n, 0x0cfa32ban, 0xa622ee8cn,
  0xd1dd9491n, 0xc0dd25a0n, 0xf9e70ab6n, 0xf0c31573n, 0x7058ce4en,
  0x7188e606n, 0x00e5ab33n, 0xd258b060n, 0x72766564n,
] as const
const SHA256_ROUND_CONSTANTS = [
  0x428a2f98n, 0x71374491n, 0xb5c0fbcfn, 0xe9b5dba5n, 0x3956c25bn,
  0x59f111f1n, 0x923f82a4n, 0xab1c5ed5n, 0xd807aa98n, 0x12835b01n,
  0x243185ben, 0x550c7dc3n, 0x72be5d74n, 0x80deb1fen, 0x9bdc06a7n,
  0xc19bf174n, 0xe49b69c1n, 0xefbe4786n, 0x0fc19dc6n, 0x240ca1ccn,
  0x2de92c6fn, 0x4a7484aan, 0x5cb0a9dcn, 0x76f988dan, 0x983e5152n,
  0xa831c66dn, 0xb00327c8n, 0xbf597fc7n, 0xc6e00bf3n, 0xd5a79147n,
  0x06ca6351n, 0x14292967n, 0x27b70a85n, 0x2e1b2138n, 0x4d2c6dfcn,
  0x53380d13n, 0x650a7354n, 0x766a0abbn, 0x81c2c92en, 0x92722c85n,
  0xa2bfe8a1n, 0xa81a664bn, 0xc24b8b70n, 0xc76c51a3n, 0xd192e819n,
  0xd6990624n, 0xf40e3585n, 0x106aa070n, 0x19a4c116n, 0x1e376c08n,
  0x2748774cn, 0x34b0bcb5n, 0x391c0cb3n, 0x4ed8aa4an, 0x5b9cca4fn,
  0x682e6ff3n, 0x748f82een, 0x78a5636fn, 0x84c87814n, 0x8cc70208n,
  0x90befffan, 0xa4506cebn, 0xbef9a3f7n, 0xc67178f2n,
] as const
const SHA256_ADJUSTMENT = 0xc9dc06a7n
// 第 14 轮常量被替换为 ADJUSTMENT（混淆的一部分，别"订正"）
const SHA256_BLOCK_CONSTANTS = [
  ...SHA256_ROUND_CONSTANTS.slice(0, 14),
  SHA256_ADJUSTMENT,
  ...SHA256_ROUND_CONSTANTS.slice(15),
] as const
const SHA256_SIGMA0_ADJUSTMENT = 0x059c0b80n
const SHA256_SIGMA1_ADJUSTMENT = 0x000b92c0n

const CS64_COEFFICIENTS = [
  [0xe82e91b1n, 0xb32700d0n],
  [0x44de24c6n, 0x88dff51dn],
  [0x3beb65bcn, 0x29514038n],
  [0xc89c5933n, 0xb328cbdfn],
  [0x8d1ec211n, 0xd405b4d5n],
  [0x314ef5d5n, 0x26e55f3cn],
  [0xe92491b1n, 0x607801c6n],
  [0xf0a5b9d5n, 0x82b2c1fbn],
  [0x06064cf3n, 0xfa51a3dan],
  [0xda79fa60n, 0x207cc464n],
  [0xbed20560n, 0x3c3c74f3n],
  [0x89f9c9f8n, 0xd2d14b61n],
  [0x35fa38c6n, 0xbb04a2c1n],
  [0xcb49e3c6n, 0xc5626167n],
] as const
const CS64_FACTOR = 0x82893933n
const CS64_ADJUSTMENT0 = 0xf2f90b1an
const CS64_ADJUSTMENT1 = 0x0b1a0000n

function rol16(value: bigint): bigint {
  const v = value & MASK32
  return ((v << 16n) | (v >> 16n)) & MASK32
}

/** 小端 32 位字，零垫到偶数个（Python `_words_le4_even`）。 */
function wordsLE4Even(data: Uint8Array): bigint[] {
  // Python (-len) % 4 恒非负；JS % 对负数给负余数，须归一
  const pad = (4 - (data.length % 4)) % 4
  const padded = new Uint8Array(data.length + pad)
  padded.set(data)
  const count = padded.length >> 2
  const words: bigint[] = []
  for (let i = 0; i < count; i++) {
    const o = i * 4
    words.push(
      BigInt(padded[o]! | (padded[o + 1]! << 8) | (padded[o + 2]! << 16) |
        (padded[o + 3]! << 24)),
    )
  }
  if (words.length % 2) words.push(0n)
  return words
}

function sigma0(value: bigint): bigint {
  return (value >> 7n ^ value << 25n ^ value >> 18n ^ value << 14n ^ value >> 3n) & MASK32
}

function sigma1(value: bigint): bigint {
  return (value >> 17n ^ value << 15n ^ value >> 19n ^ value << 13n ^ value >> 10n) & MASK32
}

type Big8 = readonly [
  bigint, bigint, bigint, bigint, bigint, bigint, bigint, bigint,
]

/** SHA-256 轮函数，可从第 firstRound 轮续跑（BigInt 下无进位截断）。 */
function sha256Rounds(state: Big8, words: readonly bigint[], firstRound = 0): Big8 {
  let [a, b, c, d, e, f, g, h] = state
  const constants =
    firstRound === 14 ? SHA256_BLOCK_CONSTANTS : SHA256_ROUND_CONSTANTS
  const aligned = Math.min(64, Math.floor((firstRound + 7) / 8) * 8)
  for (let index = firstRound; index < aligned; index++) {
    const rotE = e * 0x100000001n
    const rotA = a * 0x100000001n
    const t1 =
      h + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (g ^ (e & (f ^ g))) + constants[index]! + words[index]!
    const t2 =
      ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) +
      ((a & b) | (c & (a | b)))
    const na = (t1 + t2) & MASK32
    ;[a, b, c, d, e, f, g, h] = [na, a, b, c, (d + t1) & MASK32, e, f, g]
  }
  for (let index = aligned; index < 64; index += 8) {
    let rotE = e * 0x100000001n
    let rotA = a * 0x100000001n
    let t1 =
      h + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (g ^ (e & (f ^ g))) + constants[index]! + words[index]!
    let t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((a & b) | (c & (a | b)))
    d = (d + t1) & MASK32
    h = (t1 + t2) & MASK32
    rotE = d * 0x100000001n
    rotA = h * 0x100000001n
    t1 =
      g + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (f ^ (d & (e ^ f))) + constants[index + 1]! + words[index + 1]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((h & a) | (b & (h | a)))
    c = (c + t1) & MASK32
    g = (t1 + t2) & MASK32
    rotE = c * 0x100000001n
    rotA = g * 0x100000001n
    t1 =
      f + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (e ^ (c & (d ^ e))) + constants[index + 2]! + words[index + 2]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((g & h) | (a & (g | h)))
    b = (b + t1) & MASK32
    f = (t1 + t2) & MASK32
    rotE = b * 0x100000001n
    rotA = f * 0x100000001n
    t1 =
      e + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (d ^ (b & (c ^ d))) + constants[index + 3]! + words[index + 3]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((f & g) | (h & (f | g)))
    a = (a + t1) & MASK32
    e = (t1 + t2) & MASK32
    rotE = a * 0x100000001n
    rotA = e * 0x100000001n
    t1 =
      d + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (c ^ (a & (b ^ c))) + constants[index + 4]! + words[index + 4]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((e & f) | (g & (e | f)))
    h = (h + t1) & MASK32
    d = (t1 + t2) & MASK32
    rotE = h * 0x100000001n
    rotA = d * 0x100000001n
    t1 =
      c + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (b ^ (h & (a ^ b))) + constants[index + 5]! + words[index + 5]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((d & e) | (f & (d | e)))
    g = (g + t1) & MASK32
    c = (t1 + t2) & MASK32
    rotE = g * 0x100000001n
    rotA = c * 0x100000001n
    t1 =
      b + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (a ^ (g & (h ^ a))) + constants[index + 6]! + words[index + 6]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((c & d) | (e & (c | d)))
    f = (f + t1) & MASK32
    b = (t1 + t2) & MASK32
    rotE = f * 0x100000001n
    rotA = b * 0x100000001n
    t1 =
      a + ((rotE >> 6n) ^ (rotE >> 11n) ^ (rotE >> 25n)) +
      (h ^ (f & (g ^ h))) + constants[index + 7]! + words[index + 7]!
    t2 = ((rotA >> 2n) ^ (rotA >> 13n) ^ (rotA >> 22n)) + ((b & c) | (d & (b | c)))
    e = (e + t1) & MASK32
    a = (t1 + t2) & MASK32
  }
  return [a, b, c, d, e, f, g, h]
}

/** 就地扩展消息表到 64 字（Python `_expand_sha256_schedule`）。 */
function expandSha256Schedule(words: bigint[], firstWord = 16): void {
  for (let index = firstWord; index < 64; index++) {
    const x = words[index - 2]!
    const y = words[index - 15]!
    const sigma1v = (x >> 17n) ^ (x << 15n) ^ (x >> 19n) ^ (x << 13n) ^ (x >> 10n)
    const sigma0v = (y >> 7n) ^ (y << 25n) ^ (y >> 18n) ^ (y << 14n) ^ (y >> 3n)
    words.push((sigma1v + words[index - 7]! + sigma0v + words[index - 16]!) & MASK32)
  }
}

function bytesToBigBE(b: Uint8Array): bigint {
  let v = 0n
  for (const x of b) v = (v << 8n) | BigInt(x)
  return v
}

/** 首块（7 字节盐前缀）的注入状态；同盐只算一次。 */
const sha256InitCache = new Map<string, Big8>()
function sha256Init(data: Uint8Array): Big8 {
  const cacheKey = Buffer.from(data).toString("latin1")
  const hit = sha256InitCache.get(cacheKey)
  if (hit) return hit
  const words: bigint[] = [
    0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n, 0n,
    bytesToBigBE(data.slice(0, 3)),
    bytesToBigBE(data.slice(3, 7)),
  ]
  for (let index = 16; index < 30; index++) {
    let value = SHA256_SCHEDULE[index - 16]!
    if (index - 2 >= 14) {
      value +=
        index === 16
          ? sigma1(words[14]!) ^ SHA256_SIGMA1_ADJUSTMENT
          : sigma1(words[index - 2]!)
    }
    if (index - 7 >= 14) value += words[index - 7]!
    if (index - 15 >= 14) {
      value +=
        index === 29
          ? sigma0(words[index - 15]!) ^ SHA256_SIGMA0_ADJUSTMENT
          : sigma0(words[index - 15]!)
    }
    words.push(value & MASK32)
  }
  words.push(
    (sigma1(words[28]!) + words[23]! + sigma0(words[15]!) + words[14]! +
      SHA256_ADJUSTMENT - SHA256_ROUND_CONSTANTS[14]!) & MASK32,
  )
  expandSha256Schedule(words, 31)
  const working = sha256Rounds(SHA256_STATE, words, 14)
  // map 出来是 bigint[]；结构上恒为 8 元（SHA256_INITIAL 定长）
  const state = SHA256_INITIAL.map((x, i) => (x + working[i]!) & MASK32) as unknown as Big8
  sha256InitCache.set(cacheKey, state)
  return state
}

function sha256Digest(data: Uint8Array): Uint8Array {
  if (data.length < 7) throw new Error("Token salt must contain at least seven bytes")
  const length = 57 + data.length
  const padZeros = (((55 - length) % 64) + 64) % 64
  const tail = new Uint8Array(1 + padZeros + 8)
  tail[0] = 0x80
  // 64 位大端位长（length * 8 恒 < 2^53，经 BigInt 精确打包）
  const bits = BigInt(length) * 8n
  for (let i = 0; i < 8; i++) {
    tail[tail.length - 1 - i] = Number((bits >> BigInt(8 * i)) & 0xffn)
  }
  const padded = new Uint8Array(data.length - 7 + tail.length)
  padded.set(data.slice(7), 0)
  padded.set(tail, data.length - 7)
  let state = sha256Init(data.slice(0, 7))
  for (let offset = 0; offset < padded.length; offset += 64) {
    const words: bigint[] = []
    for (let i = 0; i < 16; i++) {
      words.push(bytesToBigBE(padded.slice(offset + i * 4, offset + i * 4 + 4)))
    }
    expandSha256Schedule(words)
    const working = sha256Rounds(state, words)
    state = state.map((x, i) => (x + working[i]!) & MASK32) as unknown as Big8
  }
  const out = Buffer.alloc(32)
  state.forEach((w, i) => out.writeUInt32BE(Number(w), i * 4))
  return new Uint8Array(out)
}

function cs64Digest(data: Uint8Array, digest: Uint8Array): [bigint, bigint] {
  const keyA = (BigInt(digest[0]!) | (BigInt(digest[1]!) << 8n) |
    (BigInt(digest[2]!) << 16n) | (BigInt(digest[3]!) << 24n)) | 1n
  const keyB = (BigInt(digest[4]!) | (BigInt(digest[5]!) << 8n) |
    (BigInt(digest[6]!) << 16n) | (BigInt(digest[7]!) << 24n)) | 1n
  const factors = [(keyA * CS64_FACTOR) & MASK32, (keyB * CS64_FACTOR) & MASK32]
  const terms: bigint[] = CS64_COEFFICIENTS.map(
    ([coefficient], index) => (coefficient * factors[index % 2]!) & MASK32,
  )
  const offsets: bigint[] = CS64_COEFFICIENTS.map(([, offset]) => offset)
  const dataWords = wordsLE4Even(
    new Uint8Array([0, ...data]),
  )
  dataWords.forEach((word, index) => {
    const term = word * (index % 2 === 0 ? keyA : keyB)
    const offset = rol16(word) * (index % 2 === 0 ? 0xef0569fbn : 0xc31713dbn)
    const adjustedTerm = index === 0 ? term + CS64_ADJUSTMENT0 * factors[0]! : term
    const adjustedOffset = index === 0 ? offset + CS64_ADJUSTMENT1 : offset
    terms.push(adjustedTerm & MASK32)
    offsets.push(adjustedOffset & MASK32)
  })
  let swapAcc = 0n
  let swapLast = 0n
  let state = 0n
  let acc = 0n
  for (let index = 0; index < terms.length; index += 2) {
    const x = terms[index]!
    const y = terms[index + 1]!
    let t = rol16((offsets[index]! + x) & MASK32)
    let q = (t * 0x76f50f34n) & MASK32
    swapAcc += (rol16(q) * 0xc3efea97n + q) & MASK32
    t = rol16((offsets[index + 1]! + y) & MASK32)
    q = (t * 0x1881ce3cn) & MASK32
    swapLast = (rol16(q) * 0x35bd1ec9n + q) & MASK32
    swapAcc = (swapAcc + swapLast) & MASK32

    state = (state * keyA + x) & MASK32
    state = (rol16(state) * 0xcf98b111n) & MASK32
    state = (rol16(state) * 0x87085b9fn) & MASK32
    state = (rol16(state) * 0x12ceb96dn) & MASK32
    state = (rol16(state) * 0x257e1d83n) & MASK32
    acc += state
    t = (state * keyB + y) & MASK32
    t = (rol16(t) * 0xa27416f5n) & MASK32
    t = (rol16(t) * 0xd38396ffn) & MASK32
    state = (rol16((rol16(t) * 0x7c932b89n) & MASK32) * 0xbfa49f69n) & MASK32
    acc = (acc + state) & MASK32
  }
  return [swapLast ^ state, swapAcc ^ acc]
}

const tokenHashCache = new Map<string, [string, string]>()
function tokenHash(data: Uint8Array): [string, string] {
  const cacheKey = Buffer.from(data).toString("latin1")
  const hit = tokenHashCache.get(cacheKey)
  if (hit) return hit
  const digest = sha256Digest(data)
  const [cs64A, cs64B] = cs64Digest(data, digest)
  // struct.pack("<II", …) → 两个 u32 小端字节序再拼 hex
  const buf = Buffer.alloc(8)
  buf.writeUInt32LE(Number(cs64A), 0)
  buf.writeUInt32LE(Number(cs64B), 4)
  const result: [string, string] = [
    buf.toString("hex").toUpperCase(),
    Buffer.from(digest).toString("hex").toUpperCase(),
  ] as const
  tokenHashCache.set(cacheKey, result)
  return result
}

/** 时钟偏斜修正（服务端 Date 头 − 本地时钟），403 时由客户端回写。 */
let clockSkewSeconds = 0
export function adjustClockSkewSeconds(delta: number): void {
  clockSkewSeconds += delta
}
export function currentUnixTimestamp(): number {
  return Date.now() / 1000 + clockSkewSeconds
}

/** Python f"{x:.0f}"：对 double 精确值四舍五入，.5 平局取偶。 */
function fmt0(x: number): string {
  const fl = Math.floor(x)
  const diff = x - fl
  let n: number
  if (diff > 0.5) n = fl + 1
  else if (diff < 0.5) n = fl
  else n = fl % 2 === 0 ? fl : fl + 1
  return String(n)
}

/** 生成 Sec-MS-GEC v2 令牌（"<16hex>-<64hex>"）。固定时间戳供测试注入。 */
export function generateSecMsGecV2(unixTimestamp?: number): string {
  let ticks = unixTimestamp ?? currentUnixTimestamp()
  ticks += WIN_EPOCH
  ticks -= ticks - Math.floor(ticks / 300) * 300 // Python %：结果非负
  ticks *= 1e9 / 100
  const strToHash = `${fmt0(ticks)}${TRUSTED_CLIENT_TOKEN}`
  const [cs64, sha256] = tokenHash(Buffer.from(strToHash, "ascii"))
  return `${cs64}-${sha256}`
}

/** 随机 MUID（32 位大写 hex），握手 Cookie 用。 */
export function generateMuid(): string {
  const buf = new Uint8Array(16)
  crypto.getRandomValues(buf)
  return Buffer.from(buf).toString("hex").toUpperCase()
}

/** 握手头（WSS_HEADERS + Cookie: muid=…）。 */
export function headersWithMuid(): Record<string, string> {
  return { ...WSS_HEADERS, Cookie: `muid=${generateMuid()};` }
}
