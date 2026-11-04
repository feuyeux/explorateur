// midi.ts — 标准 MIDI 文件（SMF）的最小解析器。
//
// 为什么自己写：谱面真值是本产线 Tier A 对齐的**唯一真值来源**，但工作区
// 不允许为一个解析器引入外部依赖（且外部 MIDI 库的解析口径各不相同，
// 换库就换读数）。SMF 的结构本身很简单：MThd 头 + 若干 MTrk 轨，每轨是
// 变长 delta-time 的事件流。
//
// 只取本产线需要的东西：
// - note on / note off（→ 音符的音高与起止）
// - set tempo（→ tick→秒的换算；没有它就无法把谱面对到录音的秒轴）
// 其余事件（控制器、节目变化、轨名…）跳过但要**正确跳过**——变长参数的
// 长度读错会让整条轨错位。
//
// 口径：tick→秒按**分段恒定 tempo** 累进（tempo 变化点重新起算），与
// 真实播放器的行为一致。

export interface MidiNote {
  /** MIDI 音号（60 = 中央 C）。 */
  pitch: number
  /** 秒（从文件起点算）。 */
  start: number
  /** 秒。 */
  end: number
}

export interface MidiMeta {
  /** 总时长（秒）。 */
  duration: number
  /** 每轨的音符。 */
  notes: MidiNote[]
  /** 轨道数。 */
  tracks: number
  /** tick/拍 与 每拍 tick 数（用于把拍换算成小节位置）。 */
  ticksPerBeat: number
}

/** 变长整数（VLQ）：7 位一组，高位为续。 */
function readVarLen(buf: Buffer, pos: number): { value: number; next: number } {
  let value = 0
  let byte = 0
  let p = pos
  do {
    if (p >= buf.length) throw new Error("MIDI: VLQ 越界")
    byte = buf[p]!
    p++
    value = (value << 7) | (byte & 0x7f)
  } while (byte & 0x80)
  return { value, next: p }
}

/** 解析 SMF 字节。 */
export function parseMidi(buf: Buffer): MidiMeta {
  if (buf.length < 14 || buf.toString("latin1", 0, 4) !== "MThd") {
    throw new Error("MIDI: 不是 MThd 开头（不是标准 MIDI 文件？）")
  }
  const headerLen = buf.readUInt32BE(4)
  const format = buf.readUInt16BE(8)
  const nTracks = buf.readUInt16BE(10)
  const division = buf.readUInt16BE(12)
  // division 高位为 1 = SMPTE 时间码（每秒帧数 + 帧数/秒），本解析器不支持。
  if (division & 0x8000) throw new Error("MIDI: SMPTE 时间码不支持（division 高位为 1）")
  const ticksPerBeat = division

  let pos = 8 + headerLen
  const notes: MidiNote[] = []
  let duration = 0
  let tick = 0
  let tempoUsPerBeat = 500000
  let secAtTick = 0
  let lastTick = 0

  const tempoAt = (t: number, usPerBeat: number): void => {
    // tick→秒的分段恒定 tempo： tempo 变化点重新起算。
    secAtTick = secAtTick + ((t - lastTick) / ticksPerBeat) * (tempoUsPerBeat / 1e6)
    lastTick = t
    tempoUsPerBeat = usPerBeat
  }

  for (let tr = 0; tr < nTracks && pos + 8 <= buf.length; tr++) {
    const id = buf.toString("latin1", pos, pos + 4)
    const len = buf.readUInt32BE(pos + 4)
    const body = buf.subarray(pos + 8, pos + 8 + len)
    pos += 8 + len
    if (id !== "MTrk") continue

    tick = 0
    secAtTick = 0
    lastTick = 0
    tempoUsPerBeat = 500000
    const open = new Map<number, { pitch: number; sec: number }>()

    let p = 0
    let runningStatus = -1
    while (p < body.length) {
      const { value: delta, next } = readVarLen(body, p)
      p = next
      tick += delta
      let status = body[p]!
      if (status & 0x80) {
        p++
        if (status < 0xf0) runningStatus = status
      } else {
        if (runningStatus < 0) throw new Error("MIDI: 运行状态无前导")
        status = runningStatus
      }

      if (status === 0xff) {
        // meta 事件
        const type = body[p]!
        p++
        const { value: mlen, next: p2 } = readVarLen(body, p)
        p = p2
        if (type === 0x51 && mlen === 3) {
          const us = (body[p]! << 16) | (body[p + 1]! << 8) | body[p + 2]!
          tempoAt(tick, us)
        }
        p += mlen
        continue
      }
      if (status === 0xf0 || status === 0xf7) {
        // sysex：变长长度
        const { value: slen, next: p2 } = readVarLen(body, p)
        p = p2 + slen
        continue
      }

      const kind = status & 0xf0
      const channel = status & 0x0f
      if (kind === 0x90 || kind === 0x80) {
        const pitch = body[p]!
        const vel = body[p + 1]!
        p += 2
        const sec = secAtTick + ((tick - lastTick) / ticksPerBeat) * (tempoUsPerBeat / 1e6)
        if (kind === 0x90 && vel > 0) {
          open.set((channel << 8) | pitch, { pitch, sec })
        } else {
          const key = (channel << 8) | pitch
          const on = open.get(key)
          if (on) {
            notes.push({ pitch: on.pitch, start: on.sec, end: Math.max(on.sec, sec) })
            open.delete(key)
          }
        }
        continue
      }
      if (kind === 0xc0 || kind === 0xd0) {
        p += 1
        continue
      }
      // 其余控制类事件（0xa0/0xb0/0xe0）：2 字节数据
      p += 2
    }
    // 轨尾仍未关闭的音符：按该轨结束时刻收口（谱面里没写 note-off 的常见写法）
    const endSec = secAtTick + ((tick - lastTick) / ticksPerBeat) * (tempoUsPerBeat / 1e6)
    for (const on of open.values()) {
      notes.push({ pitch: on.pitch, start: on.sec, end: Math.max(on.sec, endSec) })
    }
    duration = Math.max(duration, endSec)
  }

  for (const n of notes) duration = Math.max(duration, n.end)
  notes.sort((a, b) => a.start - b.start || a.pitch - b.pitch)
  return { duration, notes, tracks: nTracks, ticksPerBeat }
}
