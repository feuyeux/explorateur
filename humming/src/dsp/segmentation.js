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
   * @param {Object} [options]
   * @param {boolean} [options.useEnergyOnsets=true] - 是否用音频能量 onset 切分
   *        连续同音（如连哼两个「1 1」）。完整混音输入必须关掉：鼓点/打击乐
   *        会在每个重拍触发能量突变，把持续的长音切成碎片（实测原曲转谱
   *        84% 的音符被压成 0.5 拍）。此时音符边界只信任音高阶跃与静默间隙。
   * @returns {Object} 包含原始提取音符 rawNotes 与量化后音符 quantizedNotes
   */
  segmentAndQuantize(frames, audioSamples, sampleRate = 16000, options = {}) {
    const useEnergyOnsets = options.useEnergyOnsets !== false;

    if (!frames || frames.length === 0) {
      return { rawNotes: [], quantizedNotes: [] };
    }

    // 1. 中值滤波 (Median Filter)：去除微小揉弦颤音 (Vibrato) 与单帧噪声
    const smoothedMidis = this.applyMedianFilter(frames.map(f => f.voiced ? f.midi : 0), 5);

    // 2. 计算能量包络与音节起始点 (Onset Detection)
    // 用于分辨连续同音高哼唱（例如连哼两个相同的 1 1 或 5 5）
    const onsetFlags = useEnergyOnsets
      ? this.detectOnsets(frames, audioSamples, sampleRate)
      : new Uint8Array(frames.length);

    // 2b. 同音重唱切分 (Re-articulation Detection)。
    // 清唱连字重音在能量包络上表现为「谷后回弹」；主 onset 检测器的
    // 谷-峰比 1.35× 门槛是为干净哼唱设计的，混响会把谷填平到检测线之下
    // （实测《无名指》清唱 312 个重起音凹陷 186 个被漏切、连字并成长音）。
    // 此检测器放宽谷深至 ≤80%、要求回弹 ≥1.18×，并以「颤音周期过滤」
    // （谷间距 ≥150ms，颤音 AM 谷每 ~180ms 规律出现）排除颤音误切。
    const reartFlags = useEnergyOnsets
      ? this.detectRearticulations(frames, audioSamples, sampleRate)
      : new Uint8Array(frames.length);

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

        // 如果音高出现显著阶跃，或者检测到新的起音/同音重唱，切为新音符
        const durationSoFar = frame.time - currentSegment.startTime;
        const shouldSplitOnset = (isOnset || reartFlags[i]) && durationSoFar >= (this.minNoteDurationMs / 1000);

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
   * 同音重唱检测 (Re-articulation)：清唱连字（同一个音连唱多字）在能量包络上
   * 留下「谷后回弹」的痕迹。与主 onset 检测的分工：
   * - 主 onset 检测要求谷-峰比 1.35×，适合干净哼唱；
   * - 本检测器放宽到谷深 ≤80%、回弹 ≥1.18×，专为混响把谷填平的清唱设计；
   * - 颤音周期过滤：颤音的幅度调制谷每 ~180ms 规律出现且较浅，要求相邻谷
   *   间距 ≥150ms 并由回弹与谷深双门槛排除。
   * 只在发声帧上检测（静默帧本身就会切断音符段）。
   */
  detectRearticulations(frames, audioSamples, sampleRate) {
    const flags = new Uint8Array(frames.length);
    if (!audioSamples || audioSamples.length === 0 || frames.length === 0) return flags;

    const windowSize = Math.floor(sampleRate * 0.025);
    const energies = new Float32Array(frames.length);

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

    const W = 8;      // ±80ms 邻域
    const MIN_GAP = 15; // 相邻谷最小间距（帧，150ms）——颤音周期过滤
    let lastValley = -999;

    for (let f = 2; f < frames.length - 2; f++) {
      if (!frames[f].voiced) continue;

      const e = energies[f];
      if (e <= 0) continue;

      let prevPeak = 0;
      for (let j = Math.max(0, f - W); j < f; j++) prevPeak = Math.max(prevPeak, energies[j]);
      let nextPeak = 0;
      for (let j = f + 1; j <= Math.min(frames.length - 1, f + W); j++) nextPeak = Math.max(nextPeak, energies[j]);

      // 绝对能量地板：过低说明在静默边缘，静默本身会切段
      if (prevPeak < 0.02) continue;

      const isLocalMin = e < energies[f - 1] && e <= energies[f + 1];
      if (!isLocalMin) continue;
      if (e > prevPeak * 0.80) continue;   // 谷深不足（颤音 AM 通常浅于 80%）
      if (nextPeak < e * 1.18) continue;   // 回弹不足
      if (f - lastValley < MIN_GAP) continue; // 颤音周期内的重复谷

      flags[f] = 1;
      lastValley = f;
    }

    return flags;
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

  /**
   * 从未量化的原始音符序列估计哼唱速度 (BPM)
   *
   * 两步估计：
   * 1. 成对 IOI 中位数定锚。典型哼唱的「常见起始间隔」就是一拍，
   *    中位数天然消解附点/倍速歧义（均匀四分旋律在 100 与 75-BPM 附点
   *    网格下都完美对齐，只有中位数锚点能选中前者）；对均匀八分/十六分
   *    哼唱的 2/4 倍候选做折叠收敛到 50–180。
   * 2. 锚点 ±12% 窗口内做累计 onset 网格拟合精调：把每个音符起点吸附到
   *    候选拍长的最近 1/4 拍倍数，取相对误差最小者 —— 成对 IOI 对单个
   *    onset 的 ±30-60ms 抖动敏感（实测 95 → 101），累计拟合让抖动沿
   *    整条时间轴互相抵消（实测修正回 95）。
   *
   * 不用音符时长：发声包络 (attack/release) 把时长系统性缩短 ~15%，
   * 混入会拉高估值（实测 95 → 111）。
   *
   * @param {Array<{startTime:number}>} rawNotes - 时间域原始音符
   * @returns {number|null} 估计 BPM；样本不足时返回 null（宁可不校准也不错校准）
   */
  estimateTempo(rawNotes) {
    if (!rawNotes || rawNotes.length < 3) return null;

    const sorted = [...rawNotes].sort((a, b) => a.startTime - b.startTime);

    // 1) IOI 中位数锚点
    const iois = [];
    for (let i = 1; i < sorted.length; i++) {
      const ioi = sorted[i].startTime - sorted[i - 1].startTime;
      if (ioi >= 0.15 && ioi <= 1.6) iois.push(ioi);
    }
    if (iois.length < 3) return null;

    iois.sort((a, b) => a - b);
    let anchor = 60 / iois[Math.floor(iois.length / 2)];
    while (anchor < 50) anchor *= 2;
    while (anchor > 180) anchor /= 2;

    // 2) 锚点 ±6% 累计网格拟合精调。
    //    窗口必须窄：精调是对噪声敏感的精加工步，窗口一宽（曾用 ±12%），
    //    onset 抖动就能把「正确值 + 抖动」拟合得比「正确值」还好
    //    （实测 basic_pitch 抖动 onset 下 100 BPM 被精调成 107）。
    //    锚点本身已由中位数消歧，精调只需磨平 ±1-2 BPM 的中位数抖动。
    const t0 = sorted[0].startTime;
    const offsets = [];
    for (let i = 1; i < sorted.length; i++) {
      const o = sorted[i].startTime - t0;
      if (o >= 0.15) offsets.push(o);
    }
    if (offsets.length < 2) return Math.round(anchor);

    let bestBpm = Math.round(anchor);
    let bestErr = Infinity;

    const lo = Math.max(50, Math.floor(anchor * 0.94));
    const hi = Math.min(180, Math.ceil(anchor * 1.06));
    for (let bpm = lo; bpm <= hi; bpm++) {
      const beat = 60 / bpm;
      let errSum = 0;

      for (const o of offsets) {
        // 吸附到最近的 1/4 拍倍数（覆盖八分/十六分/附点组合）
        const k = Math.max(0.25, Math.round(o / (beat * 0.25)) * 0.25);
        errSum += Math.abs(o - k * beat) / (k * beat);
      }

      const err = errSum / offsets.length;
      if (err < bestErr) {
        bestErr = err;
        bestBpm = bpm;
      }
    }

    return bestBpm;
  }

  midiToNoteName(midi) {
    const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    const pitchClass = (midi % 12 + 12) % 12;
    const octave = Math.floor(midi / 12) - 1;
    return `${names[pitchClass]}${octave}`;
  }
}
