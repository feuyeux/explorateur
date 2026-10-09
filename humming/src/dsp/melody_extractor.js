/**
 * 主旋律提取器 (Melody Extraction for Full-Mix Recordings)
 *
 * 用于**完整歌曲混音**（原曲带伴奏）的转谱：Basic Pitch 是多音模型，
 * 会把贝斯、伴奏、人声全部转成音符事件（实测《无名指》1082 个事件里
 * 交叠率 25%、平均时长仅 110ms、事件质量重心在贝斯音区 C3 附近）。
 * 用户要的是一条能看能弹的**主旋律谱**，需要从多声部事件中抽出主导单音线。
 *
 * 为什么不是「最高声部」(skyline) 或「最响声部」(amplitude argmax)——
 * 实测《无名指》两者都被贝斯/合成器占据：贝斯既是最响的持续声部，
 * 碎片事件也让最高声部在声部间乱跳。
 *
 * 人声主旋律的真实特征（本提取器依据的三要素）：
 * 1. **音域先验**：流行乐人声几乎总在 E3~D5 (52~74)，低音区 (<C3) 是贝斯；
 * 2. **连续性**：旋律级进为主，相邻音跨度小、八度跳变罕见；
 * 3. **响度**：人声在混音中响度居前（同分同连续时偏向更响的声部）。
 *
 * 实现：帧级 Viterbi。每 10ms 帧以「覆盖事件的不同音高」为状态，
 * 发射分 = 响度 + 音域先验，转移分 = 跨度惩罚（级进免费、跳进递减、
 * 八度重罚）。全程解码出主导线，再压回音符段。
 */

/**
 * 人声主音域先验：E3(52)~D5(74) 内不罚，向外线性递减。
 * 斜率 0.13/半音为实测调参结果（《无名指》原曲：贝斯持续音事件响度高于人声，
 * 斜率 0.06 时低音残留 22%、0.13 降至 12% 且级进比例不受影响；
 * 残留集中在人声缺席的前奏/间奏段，属「跟随伴奏主奏」的合理行为）。
 */
function vocalRegisterPrior(midi) {
  if (midi >= 52 && midi <= 74) return 0;
  if (midi < 52) return -(52 - midi) * 0.13;
  return -(midi - 74) * 0.13;
}

/** 跨度转移惩罚：级进免费，3~7 半音轻罚，八度跳变重罚 */
function jumpPenalty(semitones) {
  const s = Math.abs(semitones);
  if (s <= 2) return 0;
  if (s <= 7) return -0.12;
  if (s < 12) return -0.3;
  return -0.45;
}

const UNVOICED = -1;

export class MelodyExtractor {
  /**
   * @param {Object} [options]
   * @param {number} [options.hopSec=0.01] - 帧步长 (秒)
   * @param {number} [options.unvoicedEmission=0.25] - 非发声态发射分
   *        （与响度+先验竞争：弱事件让位于静默，强事件维持旋律线）
   * @param {number} [options.unvoicedSwitchCost=-0.12] - 发声↔非发声切换惩罚
   * @param {number} [options.minSegmentSec=0.06] - 压回音符段的最短时长
   * @param {number} [options.gapBridgeSec=0.07] - 同音间隙桥接上限
   */
  constructor(options = {}) {
    this.hopSec = options.hopSec || 0.01;
    this.unvoicedEmission = options.unvoicedEmission || 0.25;
    this.unvoicedSwitchCost = options.unvoicedSwitchCost || -0.12;
    this.minSegmentSec = options.minSegmentSec || 0.12;
    this.gapBridgeSec = options.gapBridgeSec || 0.12;
  }

  /**
   * 判断是否为「完整混音」输入（需要主旋律提取）。
   *
   * 判别信号：**持续异音并发**。按 50ms 帧扫描事件流，统计
   * 「同时存在 ≥2 个相距 ≥5 半音的事件」的帧占比：
   * - 清唱/哼唱（含带混响的）重叠来自同音余响尾，几乎不构成异音并发
   *   （实测《无名指》清唱+混响：复音帧仅 5%，无任何 ≥400ms 持续段）；
   * - 完整混音的贝斯/人声/伴奏长时并发，占比远高（>20%）。
   *
   * 此前用的「事件交叠率」会被混响误触发（25%），导致清唱被当成混音、
   * 人声被音域先验压制 —— 实测用户反馈「音高完全对不上」。
   *
   * @param {Array<{startTime:number,endTime:number,midi:number}>} notes
   * @returns {boolean}
   */
  static shouldExtract(notes) {
    if (!notes || notes.length < 8) return false;

    const sorted = [...notes].sort((a, b) => a.startTime - b.startTime);
    const tEnd = Math.max(...sorted.map(n => n.endTime));
    const HOP = 0.05;
    const PITCH_GAP = 5;

    let total = 0;
    let polyFrames = 0;

    for (let t = sorted[0].startTime; t < tEnd; t += HOP) {
      total++;
      // 收集本帧并发的「相距 ≥5 半音」的事件簇
      const clusters = [];
      for (const ev of sorted) {
        if (ev.startTime > t) break;
        if (t < ev.endTime) {
          let isolated = true;
          for (const c of clusters) {
            if (Math.abs(c - ev.midi) < PITCH_GAP) { isolated = false; break; }
          }
          if (isolated) clusters.push(ev.midi);
        }
      }
      if (clusters.length > 1) polyFrames++;
    }

    return total > 0 && polyFrames / total > 0.2;
  }

  /**
   * 从多声部音符事件中提取主旋律单音线
   * @param {Array<{startTime:number,endTime:number,midi:number,exactMidi?:number,confidence?:number}>} notes
   * @returns {Array} 旋律音符事件 {startTime, endTime, midi, exactMidi, confidence}
   */
  extract(notes) {
    if (!notes || notes.length === 0) return [];

    const hop = this.hopSec;
    const tEnd = Math.max(...notes.map(n => n.endTime));
    const numFrames = Math.ceil(tEnd / hop);

    // 1. 帧化：每帧收集候选音高（同音高取最响事件的响度与浮点音高）
    const frameStates = new Array(numFrames);
    const frameEmit = new Array(numFrames);

    const sorted = [...notes].sort((a, b) => a.startTime - b.startTime);
    let cursor = 0;

    for (let f = 0; f < numFrames; f++) {
      const t = f * hop;
      while (cursor < sorted.length && sorted[cursor].endTime <= t) cursor++;

      const byPitch = new Map();
      for (let i = cursor; i < sorted.length; i++) {
        const ev = sorted[i];
        if (ev.startTime > t) break;
        if (t >= ev.endTime) continue;
        const pitch = Math.round(ev.exactMidi != null ? ev.exactMidi : ev.midi);
        const amp = ev.confidence != null ? ev.confidence : 0.6;
        const prev = byPitch.get(pitch);
        if (!prev || amp > prev.amp) {
          byPitch.set(pitch, { amp, exact: ev.exactMidi != null ? ev.exactMidi : ev.midi });
        }
      }

      const states = [UNVOICED];
      const emits = [this.unvoicedEmission];
      for (const [pitch, info] of byPitch) {
        states.push(pitch);
        emits.push(info.amp + vocalRegisterPrior(pitch));
      }
      frameStates[f] = states;
      frameEmit[f] = emits;
    }

    // 2. Viterbi 解码主导线
    const path = this.viterbi(frameStates, frameEmit);

    // 人声颤音 (~5-7Hz) 会让解码路径在相邻音高 bin 间来回振荡，
    // 压段前先做 70ms 中值平滑，否则一个音被颤音打碎成多个短段
    const half = Math.floor(0.07 / this.hopSec / 2);
    if (half >= 1) {
      const smoothed = new Array(path.length);
      for (let i = 0; i < path.length; i++) {
        const win = [];
        for (let j = i - half; j <= i + half; j++) {
          if (j >= 0 && j < path.length) win.push(path[j]);
        }
        win.sort((a, b) => a - b);
        smoothed[i] = win[Math.floor(win.length / 2)];
      }
      for (let i = 0; i < path.length; i++) path[i] = smoothed[i];
    }

    // 3. 压回音符段：连续同音高成段，短促异音被两侧同音吸收
    return this.compressToSegments(path, sorted);
  }

  viterbi(frameStates, frameEmit) {
    const N = frameStates.length;
    if (N === 0) return [];

    let prevScores = new Map();   // state -> score
    let prevStates = null;
    const back = new Array(N);    // frame -> Map(state -> prev state)

    for (let f = 0; f < N; f++) {
      const states = frameStates[f];
      const emits = frameEmit[f];
      const scores = new Map();
      back[f] = new Map();

      for (let j = 0; j < states.length; j++) {
        const s = states[j];
        let best = -Infinity;
        let bestPrev = null;

        if (f === 0) {
          // 首帧：非发声态起手最稳（旋律从有内容处开始）
          best = emits[j] + (s === UNVOICED ? 0 : -0.1);
          bestPrev = s;
        } else {
          for (const [ps, pScore] of prevScores) {
            let trans = 0;
            if (ps === UNVOICED && s === UNVOICED) trans = 0;
            else if (ps === UNVOICED || s === UNVOICED) trans = this.unvoicedSwitchCost;
            else trans = jumpPenalty(s - ps);
            const total = pScore + trans;
            if (total > best) { best = total; bestPrev = ps; }
          }
        }

        scores.set(s, best + emits[j]);
        back[f].set(s, bestPrev);
      }

      prevScores = scores;
      prevStates = states;
    }

    // 回溯
    let bestState = null;
    let bestVal = -Infinity;
    for (const [s, v] of prevScores) {
      if (v > bestVal) { bestVal = v; bestState = s; }
    }

    const path = new Array(N);
    for (let f = N - 1; f >= 0; f--) {
      path[f] = bestState;
      bestState = back[f].get(bestState);
      if (bestState == null) break;
    }
    return path;
  }

  /**
   * 把帧级主导线压回音符段：
   * - 连续同音高帧合并为一段（时长 ≥ minSegmentSec）
   * - 段内 <80ms 的异音瞬态被前后同音吸收（鼓点/装饰音碎片）
   * - 相邻同音段间隙 ≤ gapBridgeSec 时桥接合并
   */
  compressToSegments(path, allEvents) {
    const hop = this.hopSec;
    const segments = [];
    let i = 0;

    while (i < path.length) {
      if (path[i] === UNVOICED) { i++; continue; }

      const pitch = path[i];
      const startFrame = i;
      let endFrame = i;

      while (endFrame + 1 < path.length) {
        const next = path[endFrame + 1];
        if (next === pitch) { endFrame++; continue; }
        // 短促异音瞬态：向前看，若 80ms 内回到同音则吸收
        let j = endFrame + 1;
        while (j < path.length && path[j] !== pitch && path[j] !== UNVOICED && (j - endFrame) * hop <= 0.08) j++;
        if (j < path.length && path[j] === pitch && (j - endFrame) * hop <= 0.08) {
          endFrame = j;
        } else {
          break;
        }
      }

      const durSec = (endFrame - startFrame + 1) * hop;
      if (durSec >= this.minSegmentSec) {
        segments.push({
          startTime: startFrame * hop,
          endTime: (endFrame + 1) * hop,
          midi: pitch,
          exactMidi: pitch,
          confidence: 0.7
        });
      }
      i = endFrame + 1;
    }

    // 同音相邻段桥接
    const merged = [];
    for (const seg of segments) {
      const prev = merged[merged.length - 1];
      if (prev && prev.midi === seg.midi && seg.startTime - prev.endTime <= this.gapBridgeSec) {
        prev.endTime = seg.endTime;
      } else {
        merged.push(seg);
      }
    }

    return merged;
  }
}
