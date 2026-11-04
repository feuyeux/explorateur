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

interface RawNote {
  pitch: number
  startTick: number
  endTick: number
}

interface TempoEvent {
  tick: number
  usPerBeat: number
  order: number
}

interface RawTrack {
  notes: RawNote[]
  tempos: TempoEvent[]
  endTick: number
}

/** 为一条时间轴构造分段恒定 tempo 的 tick→秒换算。 */
function tickConverter(events: TempoEvent[], ticksPerBeat: number): (tick: number) => number {
  const sorted = [...events].sort((a, b) => a.tick - b.tick || a.order - b.order)
  const changes: Array<{ tick: number; sec: number; usPerBeat: number }> = []
  let sec = 0
  let lastTick = 0
  let usPerBeat = 500000
  for (const event of sorted) {
    sec += ((event.tick - lastTick) / ticksPerBeat) * (usPerBeat / 1e6)
    lastTick = event.tick
    usPerBeat = event.usPerBeat
    changes.push({ tick: lastTick, sec, usPerBeat })
  }
  return (tick: number): number => {
    let baseSec = 0
    let baseTick = 0
    let currentUs = 500000
    for (const change of changes) {
      if (tick <= change.tick) break
      baseSec = change.sec
      baseTick = change.tick
      currentUs = change.usPerBeat
    }
    return baseSec + ((tick - baseTick) / ticksPerBeat) * (currentUs / 1e6)
  }
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
  let tempoOrder = 0
  const rawTracks: RawTrack[] = []

  for (let tr = 0; tr < nTracks && pos + 8 <= buf.length; tr++) {
    const id = buf.toString("latin1", pos, pos + 4)
    const len = buf.readUInt32BE(pos + 4)
    const body = buf.subarray(pos + 8, pos + 8 + len)
    pos += 8 + len
    if (id !== "MTrk") continue

    let tick = 0
    const raw: RawTrack = { notes: [], tempos: [], endTick: 0 }
    const open = new Map<number, { pitch: number; startTick: number }>()
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
        const type = body[p]!
        p++
        const { value: mlen, next: p2 } = readVarLen(body, p)
        p = p2
        if (type === 0x51 && mlen === 3) {
          const usPerBeat = (body[p]! << 16) | (body[p + 1]! << 8) | body[p + 2]!
          raw.tempos.push({ tick, usPerBeat, order: tempoOrder++ })
        }
        p += mlen
        continue
      }
      if (status === 0xf0 || status === 0xf7) {
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
        const key = (channel << 8) | pitch
        if (kind === 0x90 && vel > 0) {
          open.set(key, { pitch, startTick: tick })
        } else {
          const on = open.get(key)
          if (on) {
            raw.notes.push({ pitch: on.pitch, startTick: on.startTick, endTick: Math.max(on.startTick, tick) })
            open.delete(key)
          }
        }
        continue
      }
      if (kind === 0xc0 || kind === 0xd0) {
        p += 1
        continue
      }
      p += 2
    }
    // 轨尾仍未关闭的音符按该轨结束 tick 收口。
    for (const on of open.values()) {
      raw.notes.push({ pitch: on.pitch, startTick: on.startTick, endTick: Math.max(on.startTick, tick) })
    }
    raw.endTick = tick
    rawTracks.push(raw)
  }

  // Format 1 的 tempo 属于整张文件的 conductor 时间轴，常见于独立第 0 轨。
  const sharedTempos = rawTracks.flatMap((track) => track.tempos)
  const notes: MidiNote[] = []
  let duration = 0
  for (const raw of rawTracks) {
    const toSec = tickConverter(format === 1 ? sharedTempos : raw.tempos, ticksPerBeat)
    for (const note of raw.notes) {
      const start = toSec(note.startTick)
      const end = Math.max(start, toSec(note.endTick))
      notes.push({ pitch: note.pitch, start, end })
      duration = Math.max(duration, end)
    }
    duration = Math.max(duration, toSec(raw.endTick))
  }
  notes.sort((a, b) => a.start - b.start || a.pitch - b.pitch)
  return { duration, notes, tracks: nTracks, ticksPerBeat }
}
