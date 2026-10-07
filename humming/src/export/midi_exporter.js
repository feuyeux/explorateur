/**
 * 阶段五：标准 MIDI 文件导出器 (Standard MIDI File 0 Binary Exporter)
 * 纯二进制位操作生成标准 .mid 文件，支持导入 Logic Pro、GarageBand、Cubase、FL Studio、MuseScore
 */

export class MidiExporter {
  /**
   * 将量化音符列表转换为标准 MIDI 文件 Blob
   * @param {Array<Object>} notes - [{midi, startBeat, durationBeats}]
   * @param {number} bpm - 速度
   * @param {Object} [meter={beats:4, unit:4}] - 拍号
   * @returns {Blob}
   */
  static exportMidi(notes, bpm = 100, meter = { beats: 4, unit: 4 }) {
    const ticksPerBeat = 480; // 标准四分音符 Tick 细度

    // 收集所有 Note On 与 Note Off 事件并按时间排序
    const rawEvents = [];

    notes.forEach(note => {
      const onTick = Math.round(note.startBeat * ticksPerBeat);
      const offTick = Math.round((note.startBeat + note.durationBeats) * ticksPerBeat);

      rawEvents.push({
        tick: onTick,
        type: 'on',
        midi: Math.max(0, Math.min(127, note.midi)),
        velocity: 96
      });

      rawEvents.push({
        tick: offTick,
        type: 'off',
        midi: Math.max(0, Math.min(127, note.midi)),
        velocity: 0
      });
    });

    // 稳定排序：按 tick 升序，相同时 off 优先于 on
    rawEvents.sort((a, b) => {
      if (a.tick !== b.tick) return a.tick - b.tick;
      if (a.type === 'off' && b.type === 'on') return -1;
      if (a.type === 'on' && b.type === 'off') return 1;
      return 0;
    });

    // 构建音轨字节流 (Track Bytes)
    const trackBytes = [];

    // 1. Meta: Set Tempo
    // microseconds per quarter note = 60,000,000 / BPM
    const usPerBeat = Math.round(60000000 / bpm);
    trackBytes.push(0x00); // delta-time = 0
    trackBytes.push(0xFF, 0x51, 0x03);
    trackBytes.push((usPerBeat >> 16) & 0xFF);
    trackBytes.push((usPerBeat >> 8) & 0xFF);
    trackBytes.push(usPerBeat & 0xFF);

    // 2. Meta: Time Signature (nn, dd, cc, bb)
    trackBytes.push(0x00); // delta-time = 0
    trackBytes.push(0xFF, 0x58, 0x04);
    trackBytes.push(meter.beats & 0xFF);
    trackBytes.push(Math.round(Math.log2(meter.unit)) & 0xFF); // 2^dd = unit
    trackBytes.push(24); // MIDI clocks per metronome click
    trackBytes.push(8);  // 32nd notes in MIDI quarter note

    // 3. Meta: Track Name
    const trackName = 'Humming Vocal Transcription';
    const nameBytes = new TextEncoder().encode(trackName);
    trackBytes.push(0x00); // delta-time = 0
    trackBytes.push(0xFF, 0x03, nameBytes.length, ...nameBytes);

    // 4. MIDI 乐器设定: Acoustic Grand Piano (0x00)
    trackBytes.push(0x00);
    trackBytes.push(0xC0, 0x00);

    // 5. 编码所有音符事件（转换为变长 Delta-time）
    let lastTick = 0;
    rawEvents.forEach(evt => {
      const deltaTick = Math.max(0, evt.tick - lastTick);
      lastTick = evt.tick;

      // 写入变长 Delta Time
      MidiExporter.writeVarInt(trackBytes, deltaTick);

      if (evt.type === 'on') {
        trackBytes.push(0x90, evt.midi, evt.velocity);
      } else {
        trackBytes.push(0x80, evt.midi, evt.velocity);
      }
    });

    // 6. Meta: End of Track (FF 2F 00)
    trackBytes.push(0x00);
    trackBytes.push(0xFF, 0x2F, 0x00);

    // 构建完整 MIDI 文件结构
    const midiBytes = [];

    // Header Chunk: 'MThd' (0x4D 54 68 64)
    midiBytes.push(0x4D, 0x54, 0x68, 0x64);
    midiBytes.push(0x00, 0x00, 0x00, 0x06); // Header length = 6
    midiBytes.push(0x00, 0x00);             // Format 0 (single track)
    midiBytes.push(0x00, 0x01);             // 1 track
    midiBytes.push((ticksPerBeat >> 8) & 0xFF, ticksPerBeat & 0xFF); // Division

    // Track Chunk: 'MTrk' (0x4D 54 72 6B)
    midiBytes.push(0x4D, 0x54, 0x72, 0x6B);
    const trackLen = trackBytes.length;
    midiBytes.push((trackLen >> 24) & 0xFF);
    midiBytes.push((trackLen >> 16) & 0xFF);
    midiBytes.push((trackLen >> 8) & 0xFF);
    midiBytes.push(trackLen & 0xFF);
    midiBytes.push(...trackBytes);

    return new Blob([new Uint8Array(midiBytes)], { type: 'audio/midi' });
  }

  /**
   * MIDI 变长数量编码 (Variable-Length Quantity)
   */
  static writeVarInt(targetArray, value) {
    let buffer = value & 0x7F;
    const bytes = [];
    while ((value >>= 7) > 0) {
      buffer <<= 8;
      buffer |= 0x80;
      buffer += (value & 0x7F);
    }
    while (true) {
      bytes.push(buffer & 0xFF);
      if (buffer & 0x80) {
        buffer >>= 8;
      } else {
        break;
      }
    }
    targetArray.push(...bytes);
  }

  /**
   * 触发浏览器一键下载 MIDI 文件
   */
  static download(notes, bpm = 100, meter = { beats: 4, unit: 4 }, filename = 'humming_score.mid') {
    const blob = MidiExporter.exportMidi(notes, bpm, meter);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
