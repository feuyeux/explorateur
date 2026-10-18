// num.ts — 数值口径工具（Python round 的移植 + 通用数值原语）。
//
// 定位：**数值口径底座**——全仓数值 parity 与通用数值原语的唯一事实源。
// 任何模块要用 clamp / 夹取，都从这里引；不许在自己的模块里复制一份，
// 也不许为了一个 clamp 去 import tts / imaging 这种高层桶（那会把整条
// 依赖闭包拖进来：rig 曾为 clamp 引 tts/index，连带 ws 握手栈）。
//
// Python 的 round() 是「银行家舍入」（ties-to-even）：0.5 平手取偶
// （round(2.5)==2、round(3.5)==4）。JS 的 Math.round 是半远离零，
// 直接换用会让 adelay 毫秒与时间轴在平手值上系统性偏移——必须显式移植。
//
// 口径细节：Python round(x, d) 对 double 的**二进制精确值**做十进制正确舍入，
// 例如 round(2.675, 2) == 2.67（2.675 的二进制精确值是 2.674999…，够不到平手）。
// 不能用「x*10^d 后看 .5」判平手：浮点乘积会把 2.6749…×100 拉回精确的
// 267.5（实测翻车）——必须取精确十进制值。double 恒为 m·2^e 的二进分数，
// 其十进制展开**有限**：e<0 时值 = (m·5^s)/10^s（s=-e），用 BigInt 精确
// 展开后整除舍入，平手判定才可信。
const scratch = new DataView(new ArrayBuffer(8))

/** 数值夹取（与 Python feuille.tts.clamp 同语义、同实现）。 */
export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** Python round() 的移植：对二进制精确值做十进制舍入 + 平手取偶。 */
export function roundHalfEven(x: number, digits = 0): number {
  if (!Number.isFinite(x)) return x
  scratch.setFloat64(0, x)
  const hi = scratch.getUint32(0)
  const lo = scratch.getUint32(4)
  const expBits = (hi >>> 20) & 0x7ff
  let m: bigint
  let e: number
  if (expBits === 0) {
    m = BigInt(lo) // 次正规数（含 0）
    e = -1074
  } else {
    m = ((BigInt(hi & 0xfffff) << 32n) | BigInt(lo)) | (1n << 52n)
    e = expBits - 1075
  }
  const neg = hi >>> 31 === 1
  if (e >= 0) return x // 整值 double：任何 digits 下无需舍入
  const s = -e
  if (s <= digits) return x // 小数位本来就少于 digits，精确值直通
  // 值 = N / 10^s（N = m·5^s，精确整数；m 由位拆解恒非负）；在 digits 位上整除舍入
  const N = m * 5n ** BigInt(s)
  const div = 10n ** BigInt(s - digits)
  const q = N / div
  const r = N % div
  const half = div / 2n // div = 10^k，恒偶
  let rr: bigint
  if (r > half) rr = q + 1n
  else if (r < half) rr = q
  else rr = q % 2n === 0n ? q : q + 1n // 精确平手：取偶
  const out = neg ? -rr : rr
  return Number(out) / 10 ** digits
}
