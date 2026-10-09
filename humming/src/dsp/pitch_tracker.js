/**
 * 阶段二：基频估计模块 (Pitch Tracker / F0 提取)
 * 实现：工业级 YIN 算法 + pYIN 概率候选与 Viterbi 平滑，适配真实人声哼唱
 */

export class PitchTracker {
  /**
   * @param {Object} options
   * @param {number} [options.sampleRate=16000] - 采样率
   * @param {number} [options.minFreq=80] - 人声基频下限 (Hz, 约 E2)
   * @param {number} [options.maxFreq=800] - 人声基频上限 (Hz, 约 G5)
   * @param {number} [options.threshold=0.28] - YIN 累积均值归一化阈值 (适合人声清唱与哼唱)
   * @param {number} [options.frameLengthMs=32] - 分析窗长 (ms)
   * @param {number} [options.hopLengthMs=10] - 步长 (ms)
   */
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 16000;
    this.minFreq = options.minFreq || 80;
    this.maxFreq = options.maxFreq || 800;
    this.threshold = options.threshold || 0.28;
    this.frameLength = Math.floor(this.sampleRate * ((options.frameLengthMs || 32) / 1000));
    this.hopLength = Math.floor(this.sampleRate * ((options.hopLengthMs || 10) / 1000));

    this.minLag = Math.floor(this.sampleRate / this.maxFreq);
    this.maxLag = Math.ceil(this.sampleRate / this.minFreq);
  }

  /**
   * 对音频序列提取连续基频曲线 (Hz) 及置信度
   * @param {Float32Array} audioData
   * @returns {Object}
   */
  track(audioData) {
    const numFrames = Math.max(1, Math.floor((audioData.length - this.frameLength) / this.hopLength));
    const rawFrames = [];

    for (let f = 0; f < numFrames; f++) {
      const start = f * this.hopLength;
      const windowSamples = audioData.subarray(start, start + this.frameLength);
      const timeSeconds = (start + this.frameLength / 2) / this.sampleRate;

      const candidates = this.extractCandidatesYIN(windowSamples);
      rawFrames.push({
        frameIndex: f,
        timeSeconds: timeSeconds,
        candidates: candidates
      });
    }

    const smoothedFrames = this.viterbiSmoothing(rawFrames);

    return {
      hopLengthSeconds: this.hopLength / this.sampleRate,
      frames: smoothedFrames
    };
  }

  extractCandidatesYIN(windowSamples) {
    const halfLen = Math.floor(this.frameLength / 2);
    const maxTau = Math.min(this.maxLag, halfLen - 1);
    const minTau = Math.max(2, this.minLag);

    if (maxTau <= minTau) {
      return [{ freq: 0, probability: 0, aperiodicity: 1 }];
    }

    // 1. 差分函数
    const diff = new Float32Array(maxTau + 1);
    for (let tau = 1; tau <= maxTau; tau++) {
      let sum = 0;
      for (let j = 0; j < halfLen; j++) {
        const delta = windowSamples[j] - windowSamples[j + tau];
        sum += delta * delta;
      }
      diff[tau] = sum;
    }

    // 2. 累积均值归一化差分函数
    const cmndf = new Float32Array(maxTau + 1);
    cmndf[0] = 1;
    let runningSum = 0;
    for (let tau = 1; tau <= maxTau; tau++) {
      runningSum += diff[tau];
      if (runningSum === 0) {
        cmndf[tau] = 1;
      } else {
        cmndf[tau] = diff[tau] / (runningSum / tau);
      }
    }

    // 3. 寻找低于阈值的局部极小值
    const candidates = [];
    candidates.push({
      freq: 0,
      probability: 0.1,
      aperiodicity: 1.0,
      tau: 0
    });

    for (let tau = minTau; tau < maxTau; tau++) {
      if (cmndf[tau] < this.threshold) {
        if (cmndf[tau] <= cmndf[tau - 1] && cmndf[tau] <= cmndf[tau + 1]) {
          const betterTau = this.parabolicInterpolation(cmndf, tau);
          const freq = this.sampleRate / betterTau;

          if (freq >= this.minFreq && freq <= this.maxFreq) {
            const aperiodicity = cmndf[tau];
            const prob = Math.max(0.05, 1 - aperiodicity);
            candidates.push({
              freq: freq,
              probability: prob,
              aperiodicity: aperiodicity,
              tau: betterTau
            });
          }
        }
      }
    }

    // 全局极小值兜底
    if (candidates.length === 1) {
      let globalMinTau = minTau;
      let minVal = cmndf[minTau];
      for (let tau = minTau + 1; tau < maxTau; tau++) {
        if (cmndf[tau] < minVal) {
          minVal = cmndf[tau];
          globalMinTau = tau;
        }
      }

      if (minVal < 0.65) {
        const betterTau = this.parabolicInterpolation(cmndf, globalMinTau);
        const freq = this.sampleRate / betterTau;
        if (freq >= this.minFreq && freq <= this.maxFreq) {
          candidates.push({
            freq: freq,
            probability: Math.max(0.08, 1 - minVal),
            aperiodicity: minVal,
            tau: betterTau
          });
        }
      }
    }

    return candidates;
  }

  parabolicInterpolation(array, x) {
    if (x <= 0 || x >= array.length - 1) return x;
    const alpha = array[x - 1];
    const beta = array[x];
    const gamma = array[x + 1];
    const denom = 2 * (alpha - 2 * beta + gamma);
    if (Math.abs(denom) < 1e-7) return x;
    const delta = (alpha - gamma) / denom;
    return x + delta;
  }

  viterbiSmoothing(rawFrames) {
    const N = rawFrames.length;
    if (N === 0) return [];

    const V = [];
    const backpointers = [];

    V[0] = rawFrames[0].candidates.map(c => Math.log(Math.max(1e-6, c.probability)));
    backpointers[0] = rawFrames[0].candidates.map(() => 0);

    for (let t = 1; t < N; t++) {
      const prevCandidates = rawFrames[t - 1].candidates;
      const currCandidates = rawFrames[t].candidates;
      V[t] = new Float64Array(currCandidates.length);
      backpointers[t] = new Int32Array(currCandidates.length);

      for (let j = 0; j < currCandidates.length; j++) {
        const curr = currCandidates[j];
        let maxProb = -Infinity;
        let bestPrev = 0;

        for (let i = 0; i < prevCandidates.length; i++) {
          const prev = prevCandidates[i];
          const transCost = this.transitionLogProb(prev, curr);
          const totalLogProb = V[t - 1][i] + transCost;

          if (totalLogProb > maxProb) {
            maxProb = totalLogProb;
            bestPrev = i;
          }
        }

        const emissionLogProb = Math.log(Math.max(1e-6, curr.probability));
        V[t][j] = maxProb + emissionLogProb;
        backpointers[t][j] = bestPrev;
      }
    }

    let bestFinalIdx = 0;
    let bestFinalVal = -Infinity;
    const lastFrameVals = V[N - 1];
    for (let j = 0; j < lastFrameVals.length; j++) {
      if (lastFrameVals[j] > bestFinalVal) {
        bestFinalVal = lastFrameVals[j];
        bestFinalIdx = j;
      }
    }

    const smoothedPath = new Array(N);
    let currIdx = bestFinalIdx;
    for (let t = N - 1; t >= 0; t--) {
      smoothedPath[t] = rawFrames[t].candidates[currIdx];
      currIdx = backpointers[t][currIdx];
    }

    return rawFrames.map((frame, idx) => {
      const chosen = smoothedPath[idx];
      const freq = chosen.freq;
      const midi = freq > 0 ? 69 + 12 * Math.log2(freq / 440) : 0;
      return {
        time: frame.timeSeconds,
        freq: Math.round(freq * 100) / 100,
        midi: Math.round(midi * 100) / 100,
        voiced: freq > 0 && chosen.probability > 0.18,
        confidence: chosen.probability
      };
    });
  }

  /**
   * Viterbi 转移概率。
   *
   * 惩罚曲线按真实清唱旋律的音程统计设计：级进为主，三~七度跳进少见但真实，
   * 八度跳进/次谐波错误需要强发射分支撑。
   * 旧曲线对 5~7 半音跳进罚 exp(-3.5~-4.9)，导致「突然的高音」整段跟不上
   * （实测《无名指》37 个跳进点 22 个停在了跳进前的旧音高，偏差恰为跳进音程）。
   */
  transitionLogProb(fromCandidate, toCandidate) {
    if (fromCandidate.freq === 0 && toCandidate.freq === 0) {
      return Math.log(0.9);
    }
    if (fromCandidate.freq === 0 || toCandidate.freq === 0) {
      return Math.log(0.2);
    }

    const semitoneDiff = Math.abs(12 * Math.log2(toCandidate.freq / fromCandidate.freq));

    if (semitoneDiff < 0.8) {
      return Math.log(0.95);  // 同音持续
    } else if (semitoneDiff < 2.5) {
      return Math.log(0.70);  // 级进（大二度内）
    } else if (semitoneDiff < 5) {
      return Math.log(0.35);  // 三度/四度跳进
    } else if (semitoneDiff < 9) {
      return Math.log(0.15);  // 五~七度跳进：少见但真实
    } else if (Math.abs(semitoneDiff - 12) < 1.0) {
      return Math.log(0.04);  // 八度：真八度跳或次谐波错误，靠发射分辨
    } else {
      return Math.log(0.01);  // 超过八度：基本只可能是错误
    }
  }
}
