// split.ts — edge-tts 7.3.1 `split_text_by_byte_length` 的字节级移植。
//
// 作用在**转义后**的 UTF-8 字节上（client.stream 先过 escape + 清洗再切），
// 优先级：限长内的换行 > 空格 > 最大合法 UTF-8 前缀 > 回避未闭合的 & 实体。
//
// 上游 quirk（按行为钉住，不"顺手修"）：无分隔符长文本的安全切点在**整段
// 剩余文本**上求最大合法 UTF-8 前缀——可能给出超过限长的单块（实测
// "a"*9000 / 4096 → 一个 9000 字节的块）。TS 侧逐字节复刻同一行为。
const AMP = 0x26 // &
const SEMI = 0x3b // ;
const NEWLINE = 0x0a
const SPACE = 0x20
// Python bytes.strip() 的 ASCII 空白集
const ASCII_WS = new Set([0x20, 0x09, 0x0a, 0x0d, 0x0b, 0x0c])

function findLastNewlineOrSpaceWithinLimit(text: Buffer, limit: number): number {
  // rfind(needle, 0, limit) 即在 [0, limit) 内找最后出现；limit ≥ 1（外层已保证）
  let splitAt = text.lastIndexOf(NEWLINE, limit - 1)
  if (splitAt < 0) splitAt = text.lastIndexOf(SPACE, limit - 1)
  return splitAt
}

function findSafeUtf8SplitPoint(text: Buffer): number {
  // 从整段长度向下找最大合法 UTF-8 前缀（含上游 quirk，见文件头）
  const dec = new TextDecoder("utf-8", { fatal: true })
  let splitAt = text.length
  while (splitAt > 0) {
    try {
      dec.decode(text.subarray(0, splitAt))
      return splitAt
    } catch {
      splitAt -= 1
    }
  }
  return splitAt
}

function adjustSplitPointForXmlEntity(text: Buffer, splitAt: number): number {
  while (splitAt > 0 && text.subarray(0, splitAt).includes(AMP)) {
    const ampersandIndex = text.lastIndexOf(AMP, splitAt - 1)
    // [& , splitAt) 内有无 ';'——有则实体已闭合，可安全停在原切点
    let terminated = false
    for (let i = ampersandIndex + 1; i < splitAt; i++) {
      if (text[i] === SEMI) {
        terminated = true
        break
      }
    }
    if (terminated) break
    splitAt = ampersandIndex
  }
  return splitAt
}

function stripAsciiWhitespace(buf: Buffer): Buffer {
  let s = 0
  let e = buf.length
  while (s < e && ASCII_WS.has(buf[s]!)) s++
  while (e > s && ASCII_WS.has(buf[e - 1]!)) e--
  return buf.subarray(s, e)
}

/** 按 UTF-8 字节限长切块（优先换行/空格，保 UTF-8 完整，回避切断 & 实体）。 */
export function splitTextByByteLength(text: string | Buffer, byteLength: number): Buffer[] {
  if (byteLength <= 0) throw new Error("byte_length must be greater than 0")
  const buf = Buffer.isBuffer(text) ? text : Buffer.from(text, "utf8")
  const chunks: Buffer[] = []
  let rest = buf
  while (rest.length > byteLength) {
    let splitAt = findLastNewlineOrSpaceWithinLimit(rest, byteLength)
    if (splitAt < 0) splitAt = findSafeUtf8SplitPoint(rest)
    splitAt = adjustSplitPointForXmlEntity(rest, splitAt)
    if (splitAt < 0) {
      throw new Error(
        "Maximum byte length is too small or invalid text structure near '&' or invalid UTF-8",
      )
    }
    const chunk = stripAsciiWhitespace(rest.subarray(0, splitAt))
    if (chunk.length > 0) chunks.push(chunk)
    // 调整后切点为 0 时前进 1 字节，避免死循环
    rest = rest.subarray(splitAt > 0 ? splitAt : 1)
  }
  const remaining = stripAsciiWhitespace(rest)
  if (remaining.length > 0) chunks.push(remaining)
  return chunks
}
