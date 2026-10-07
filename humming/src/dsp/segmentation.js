/**
 * 阶段三：音符切分与量化模块 (Note Segmentation & Quantization)
 * 核心逻辑：音高转MIDI -> 中值滤波去颤音 -> 结合音高跳变与能量通量 (Onset) 切分 -> 滑音与瞬态合并 (120ms) -> 节拍网格量化
 */

export class NoteSegmenter {
  /**
   * @param {Object} options
   * @param {number} [options.bpm=100] - 预设或检测到的 BPM
   * @param {number} [options.minNoteDurationMs=120] - 最短音符时长门槛 (毫秒)，短于此值的碎音合并，防止滑音误判
   * @param {number} [options.quantizeGrid=0.5] - 量化网格细度 (0.25 = 十六分音符, 0.5 = 八分音符, 1.0 = 四分音符)
   * @param {number} [options.pitchTolerance=0.7] - 音符内部音高浮动容差 (半音)
   */
  constructor(options = {}) {
    this.bpm = options.bpm || 100;
    this.minNoteDurationMs = options.minNoteDurationMs || 120;
    this.quantizeGrid = options.quantizeGrid !== undefined ? options.quantizeGrid : 0.5;
    this.pitchTolerance = options.pitchTolerance || 0.75;
  }

  /**
   * 将基频帧序列切分为离散的结构化音符列表
   * @param {Array<Object>} frames - 来自 PitchTracker 的帧数据 [{time, freq, midi, voiced, confidence}]
   * @param {Float32Array} [audioSamples] - 音频样本用于能量包络起始点检测
   * @param {number} [sampleRate=16000]
   * @returns {Object} 包含原始提取音符 rawNotes 与量化后音符 quantizedNotes
   */
  segmentAndQuantize(frames, audioSamples, sampleRate = 16000) {
    if (!frames || frames.length === 0) {
      return { rawNotes: [], quantizedNotes: [] };
    }

    // 1. 中值滤波 (Median Filter)：去除微小揉弦颤音 (Vibrato) 与单帧噪声
    const smoothedMidis = this.applyMedianFilter(frames.map(f => f.voiced ? f.midi : 0), 5);

    // 2. 计算能量包络与音节起始点 (Onset Detection)
    // 用于分辨连续同音高哼唱（例如连哼两个相同的 1 1 或 5 5）
    const onsetFlags = this.detectOnsets(frames, audioSamples, sampleRate);

    // 3. 初始切分：基于音高跳变、能量起始点 (Onset) 与发声断点
    const initialSegments = [];
    let currentSegment = null;

    for (let i = 0; i < frames.length; i++) {
      const frame = frames[i];
      const midi = smoothedMidis[i];
      const isVoiced = frame.voiced && midi > 20 && midi < 110;
      const isOnset = onsetFlags[i];

      if (!isVoiced) {
        if (currentSegment) {
          initialSegments.push(currentSegment);
          currentSegment = null;
        }
        continue;
      }

      if (!currentSegment) {
        currentSegment = {
          startTime: frame.time,
          endTime: frame.time,
          midis: [midi],
          confidences: [frame.confidence]
        };
      } else {
        const avgMidi = currentSegment.midis.reduce((a, b) => a + b, 0) / currentSegment.midis.length;
        const diff = Math.abs(midi - avgMidi);

        // 如果音高出现显著阶跃，或者检测到新的同音哼唱起音 (Onset)，切为新音符
        const durationSoFar = frame.time - currentSegment.startTime;
        const shouldSplitOnset = isOnset && durationSoFar >= (this.minNoteDurationMs / 1000);

        if (diff > this.pitchTolerance || shouldSplitOnset) {
          initialSegments.push(currentSegment);
          currentSegment = {
            startTime: frame.time,
            endTime: frame.time,
            midis: [midi],
            confidences: [frame.confidence]
          };
        } else {
          currentSegment.endTime = frame.time;
          currentSegment.midis.push(midi);
          currentSegment.confidences.push(frame.confidence);
        }
      }
    }

    if (currentSegment) {
      initialSegments.push(currentSegment);
    }

    // 4. 统计各片段的核心音高与持续时间
    const rawNotes = initialSegments.map(seg => {
      const sorted = [...seg.midis].sort((a, b) => a - b);
      const medianMidi = sorted[Math.floor(sorted.length / 2)];
      const roundedMidi = Math.round(medianMidi);
      const duration = Math.max(0.01, seg.endTime - seg.startTime);

      return {
        startTime: seg.startTime,
        endTime: seg.endTime,
        duration: duration,
        midi: roundedMidi,
        exactMidi: medianMidi,
        noteName: this.midiToNoteName(roundedMidi),
        confidence: seg.confidences.reduce((a, b) => a + b, 0) / seg.confidences.length
      };
    });

    // 5. 滑音消除与碎片音符合并 (Consolidate glissando transitions < 120ms)
    const mergedNotes = this.consolidateTransients(rawNotes, this.minNoteDurationMs / 1000);

    // 6. 时间节拍量化 (Quantization to Grid)
    const quantizedNotes = this.quantizeNotes(mergedNotes, this.bpm, this.quantizeGrid);

    return {
      rawNotes: mergedNotes,
      quantizedNotes: quantizedNotes
    };
  }

  /**
   * 起始点 (Onset) 与音节重音检测
   */
  detectOnsets(frames, audioSamples, sampleRate) {
    const onsets = new Uint8Array(frames.length);
    if (!audioSamples || audioSamples.length === 0) return onsets;

    const hopSize = Math.floor(sampleRate * 0.010); // 10ms
    const windowSize = Math.floor(sampleRate * 0.025);
    const energies = new Float32Array(frames.length);

    // 计算各帧能量
    for (let f = 0; f < frames.length; f++) {
      const start = Math.floor(frames[f].time * sampleRate) - Math.floor(windowSize / 2);
      if (start < 0 || start + windowSize >= audioSamples.length) continue;

      let sumSq = 0;
      for (let s = 0; s < windowSize; s += 2) {
        const val = audioSamples[start + s];
        sumSq += val * val;
      }
      energies[f] = Math.sqrt(sumSq / (windowSize / 2));
    }

    // 计算能量一阶差分与局部谷峰
    for (let f = 3; f < frames.length - 3; f++) {
      const prevMin = Math.min(energies[f - 1], energies[f - 2], energies[f - 3]);
      const curr = energies[f];
      const nextMax = Math.max(energies[f + 1], energies[f + 2]);

      // 能量低谷后突增 (Valley-to-Peak ratio > 1.35) 且具有发声能量
      if (curr > 0.015 && curr > prevMin * 1.35 && curr >= nextMax * 0.9) {
        onsets[f] = 1;
      }
    }

    return onsets;
  }

  /**
   * 中值滤波算法
   */
  applyMedianFilter(array, windowSize = 5) {
    const half = Math.floor(windowSize / 2);
    const result = new Float32Array(array.length);

    for (let i = 0; i < array.length; i++) {
      const windowVals = [];
      for (let j = -half; j <= half; j++) {
        const idx = i + j;
        if (idx >= 0 && idx < array.length) {
          windowVals.push(array[idx]);
        }
      }
      windowVals.sort((a, b) => a - b);
      result[i] = windowVals[Math.floor(windowVals.length / 2)];
    }

    return result;
  }

  /**
   * 瞬态过渡音与滑音碎片合并
   */
  consolidateTransients(notes, minDurationSec) {
    if (notes.length <= 1) return notes;

    const consolidated = [];
    let i = 0;

    while (i < notes.length) {
      const note = notes[i];

      // 若当前音符过短
      if (note.duration < minDurationSec) {
        if (consolidated.length > 0) {
          const prev = consolidated[consolidated.length - 1];
          if (Math.abs(note.midi - prev.midi) <= 2) {
            prev.endTime = note.endTime;
            prev.duration = prev.endTime - prev.startTime;
            i++;
            continue;
          }
        }

        if (i + 1 < notes.length) {
          const next = notes[i + 1];
          if (Math.abs(note.midi - next.midi) <= 2) {
            next.startTime = note.startTime;
            next.duration = next.endTime - next.startTime;
            i++;
            continue;
          }
        }

        // 极短杂音忽略
        if (note.duration < 0.08) {
          i++;
          continue;
        }
      }

      consolidated.push({ ...note });
      i++;
    }

    return consolidated;
  }

  /**
   * 节拍网格量化
   */
  quantizeNotes(notes, bpm, gridFraction = 0.5) {
    const secondsPerBeat = 60 / bpm;
    const gridSeconds = secondsPerBeat * gridFraction;

    return notes.map(note => {
      const rawStartBeats = note.startTime / secondsPerBeat;
      const quantStartBeats = Math.round(rawStartBeats / gridFraction) * gridFraction;

      const rawDurationBeats = note.duration / secondsPerBeat;
      let quantDurationBeats = Math.max(gridFraction, Math.round(rawDurationBeats / gridFraction) * gridFraction);

      const noteType = this.beatsToNoteType(quantDurationBeats);

      return {
        ...note,
        noteName: note.noteName || this.midiToNoteName(note.midi),
        startBeat: quantStartBeats,
        durationBeats: quantDurationBeats,
        startTime: quantStartBeats * secondsPerBeat,
        duration: quantDurationBeats * secondsPerBeat,
        endTime: (quantStartBeats + quantDurationBeats) * secondsPerBeat,
        noteType: noteType.type,
        isDotted: noteType.isDotted,
        typeLabel: noteType.label
      };
    });
  }

  beatsToNoteType(beats) {
    const eps = 0.06;
    if (Math.abs(beats - 4.0) < eps) return { type: 'whole', isDotted: false, label: '全音符' };
    if (Math.abs(beats - 3.0) < eps) return { type: 'half', isDotted: true, label: '附点二分音符' };
    if (Math.abs(beats - 2.0) < eps) return { type: 'half', isDotted: false, label: '二分音符' };
    if (Math.abs(beats - 1.5) < eps) return { type: 'quarter', isDotted: true, label: '附点四分音符' };
    if (Math.abs(beats - 1.0) < eps) return { type: 'quarter', isDotted: false, label: '四分音符' };
    if (Math.abs(beats - 0.75) < eps) return { type: 'eighth', isDotted: true, label: '附点八分音符' };
    if (Math.abs(beats - 0.5) < eps) return { type: 'eighth', isDotted: false, label: '八分音符' };
    if (Math.abs(beats - 0.25) < eps) return { type: '16th', isDotted: false, label: '十六分音符' };

    if (beats > 3.0) return { type: 'whole', isDotted: false, label: '全音符' };
    if (beats > 1.5) return { type: 'half', isDotted: false, label: '二分音符' };
    if (beats > 0.75) return { type: 'quarter', isDotted: false, label: '四分音符' };
    if (beats > 0.35) return { type: 'eighth', isDotted: false, label: '八分音符' };
    return { type: '16th', isDotted: false, label: '十六分音符' };
  }

  midiToNoteName(midi) {
    const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    const pitchClass = (midi % 12 + 12) % 12;
    const octave = Math.floor(midi / 12) - 1;
    return `${names[pitchClass]}${octave}`;
  }
}
