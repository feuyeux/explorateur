/**
 * 阶段一：音频预处理模块 (Audio Preprocessor)
 * 包含：单声道提取、峰值增益规整 (Peak Normalization)、高质量重采样 (16kHz)、带通滤波 (80Hz - 2000Hz)、自适应 VAD 静音检测
 */

export class AudioPreprocessor {
  /**
   * @param {Object} options
   * @param {number} [options.targetSampleRate=16000] - 目标采样率
   * @param {number} [options.lowCutoff=80] - 高通滤波下限频率 (Hz)
   * @param {number} [options.highCutoff=2000] - 低通滤波上限频率 (Hz)
   * @param {number} [options.vadEnergyThreshold=0.008] - VAD 短时能量门限
   * @param {number} [options.vadZcrThreshold=0.35] - VAD 过零率门限
   */
  constructor(options = {}) {
    this.targetSampleRate = options.targetSampleRate || 16000;
    this.lowCutoff = options.lowCutoff || 80;
    this.highCutoff = options.highCutoff || 2000;
    this.vadEnergyThreshold = options.vadEnergyThreshold || 0.008;
    this.vadZcrThreshold = options.vadZcrThreshold || 0.35;
  }

  /**
   * 将输入的 AudioBuffer 或 Float32Array 预处理为规整化的 16kHz 带通滤波人声音频
   * @param {Float32Array|Float32Array[]} audioData
   * @param {number} originalSampleRate
   * @returns {Object}
   */
  process(audioData, originalSampleRate) {
    // 1. 转为单声道 Float32Array
    let monoData;
    if (Array.isArray(audioData) || (audioData.numberOfChannels && audioData.numberOfChannels > 1)) {
      const ch0 = audioData[0] || audioData.getChannelData(0);
      const ch1 = audioData[1] || audioData.getChannelData(1);
      monoData = new Float32Array(ch0.length);
      for (let i = 0; i < ch0.length; i++) {
        monoData[i] = (ch0[i] + ch1[i]) * 0.5;
      }
    } else if (audioData.getChannelData) {
      monoData = new Float32Array(audioData.getChannelData(0));
    } else {
      monoData = new Float32Array(audioData);
    }

    // 2. 自动增益峰值规整化 (Peak Normalization)，解决麦克风录音音量过小导致被切断的问题
    let maxAbs = 0;
    for (let i = 0; i < monoData.length; i++) {
      const abs = Math.abs(monoData[i]);
      if (abs > maxAbs) maxAbs = abs;
    }
    if (maxAbs > 0.0001 && maxAbs < 0.85) {
      const gain = 0.85 / maxAbs;
      for (let i = 0; i < monoData.length; i++) {
        monoData[i] *= gain;
      }
    }

    // 3. 采样率重采样至 16kHz
    const resampledData = this.resample(monoData, originalSampleRate, this.targetSampleRate);

    // 4. 带通滤波 (80 Hz ~ 2000 Hz)
    const filteredData = this.bandpassFilter(resampledData, this.targetSampleRate, this.lowCutoff, this.highCutoff);

    // 5. 自适应 VAD 静音检测
    const vadResult = this.detectVoiceActivity(filteredData, this.targetSampleRate);

    return {
      sampleRate: this.targetSampleRate,
      originalDuration: monoData.length / originalSampleRate,
      rawSamples: resampledData,
      filteredSamples: filteredData,
      vadResult: vadResult,
      activeSamples: vadResult.trimmedSamples,
      trimOffsetSeconds: vadResult.startSeconds
    };
  }

  resample(inputSamples, fromRate, toRate) {
    if (fromRate === toRate) return new Float32Array(inputSamples);

    const ratio = fromRate / toRate;
    const outputLength = Math.round(inputSamples.length / ratio);
    const output = new Float32Array(outputLength);

    for (let i = 0; i < outputLength; i++) {
      const srcPos = i * ratio;
      const idx = Math.floor(srcPos);
      const frac = srcPos - idx;

      const y0 = idx > 0 ? inputSamples[idx - 1] : inputSamples[idx];
      const y1 = inputSamples[idx] || 0;
      const y2 = idx + 1 < inputSamples.length ? inputSamples[idx + 1] : y1;
      const y3 = idx + 2 < inputSamples.length ? inputSamples[idx + 2] : y2;

      const c0 = y1;
      const c1 = 0.5 * (y2 - y0);
      const c2 = y0 - 2.5 * y1 + 2 * y2 - 0.5 * y3;
      const c3 = 0.5 * (y3 - y0) + 1.5 * (y1 - y2);

      output[i] = ((c3 * frac + c2) * frac + c1) * frac + c0;
    }

    return output;
  }

  bandpassFilter(samples, sampleRate, lowCut, highCut) {
    const hpFiltered = this.applyBiquad(samples, sampleRate, lowCut, 'highpass');
    const bpFiltered = this.applyBiquad(hpFiltered, sampleRate, highCut, 'lowpass');
    return bpFiltered;
  }

  applyBiquad(input, sampleRate, freq, type) {
    const output = new Float32Array(input.length);
    const omega = 2 * Math.PI * freq / sampleRate;
    const cosOmega = Math.cos(omega);
    const sinOmega = Math.sin(omega);
    const Q = 0.7071;
    const alpha = sinOmega / (2 * Q);

    let b0, b1, b2, a0, a1, a2;

    if (type === 'highpass') {
      b0 = (1 + cosOmega) / 2;
      b1 = -(1 + cosOmega);
      b2 = (1 + cosOmega) / 2;
      a0 = 1 + alpha;
      a1 = -2 * cosOmega;
      a2 = 1 - alpha;
    } else {
      b0 = (1 - cosOmega) / 2;
      b1 = 1 - cosOmega;
      b2 = (1 - cosOmega) / 2;
      a0 = 1 + alpha;
      a1 = -2 * cosOmega;
      a2 = 1 - alpha;
    }

    const normB0 = b0 / a0;
    const normB1 = b1 / a0;
    const normB2 = b2 / a0;
    const normA1 = a1 / a0;
    const normA2 = a2 / a0;

    let z1 = 0;
    let z2 = 0;

    for (let i = 0; i < input.length; i++) {
      const x = input[i];
      const y = normB0 * x + z1;
      z1 = normB1 * x - normA1 * y + z2;
      z2 = normB2 * x - normA2 * y;
      output[i] = y;
    }

    return output;
  }

  detectVoiceActivity(samples, sampleRate) {
    const frameSize = Math.floor(sampleRate * 0.025);
    const hopSize = Math.floor(sampleRate * 0.010);
    const numFrames = Math.max(1, Math.floor((samples.length - frameSize) / hopSize));

    const energies = new Float32Array(numFrames);
    const isSpeech = new Uint8Array(numFrames);

    let maxEnergy = 0.0001;

    for (let f = 0; f < numFrames; f++) {
      const offset = f * hopSize;
      let sumSq = 0;

      for (let i = 0; i < frameSize; i++) {
        const val = samples[offset + i];
        sumSq += val * val;
      }

      const rms = Math.sqrt(sumSq / frameSize);
      energies[f] = rms;
      if (rms > maxEnergy) maxEnergy = rms;
    }

    // 自适应底噪估算与相对门限
    const sortedEnergies = Array.from(energies).sort((a, b) => a - b);
    const noiseFloor = sortedEnergies[Math.floor(sortedEnergies.length * 0.15)] || 0.001;
    const adaptiveThreshold = Math.max(this.vadEnergyThreshold, noiseFloor * 1.8, maxEnergy * 0.05);

    let speechFrameCount = 0;
    for (let f = 0; f < numFrames; f++) {
      if (energies[f] >= adaptiveThreshold) {
        isSpeech[f] = 1;
        speechFrameCount++;
      }
    }

    // 如果检测到的人声帧极少（可能是非常安静的清唱），直接全段保留，绝不错杀
    if (speechFrameCount < 10) {
      return {
        isSpeechFrames: Array.from(isSpeech),
        frameEnergies: Array.from(energies),
        adaptiveThreshold,
        startFrame: 0,
        endFrame: numFrames - 1,
        startSeconds: 0,
        endSeconds: samples.length / sampleRate,
        trimmedSamples: samples
      };
    }

    // 平滑延音
    const hangoverFrames = Math.floor(0.15 / (hopSize / sampleRate));
    let hangoverCounter = 0;
    for (let f = 0; f < numFrames; f++) {
      if (isSpeech[f] === 1) {
        hangoverCounter = hangoverFrames;
      } else if (hangoverCounter > 0) {
        isSpeech[f] = 1;
        hangoverCounter--;
      }
    }

    let firstSpeechFrame = 0;
    while (firstSpeechFrame < numFrames && isSpeech[firstSpeechFrame] === 0) {
      firstSpeechFrame++;
    }

    let lastSpeechFrame = numFrames - 1;
    while (lastSpeechFrame > firstSpeechFrame && isSpeech[lastSpeechFrame] === 0) {
      lastSpeechFrame--;
    }

    const marginFrames = Math.floor(0.06 / (hopSize / sampleRate));
    const startFrame = Math.max(0, firstSpeechFrame - marginFrames);
    const endFrame = Math.min(numFrames - 1, lastSpeechFrame + marginFrames);

    const startSample = startFrame * hopSize;
    const endSample = Math.min(samples.length, (endFrame * hopSize) + frameSize);
    const trimmedSamples = samples.slice(startSample, endSample);

    return {
      isSpeechFrames: Array.from(isSpeech),
      frameEnergies: Array.from(energies),
      adaptiveThreshold,
      startFrame,
      endFrame,
      startSeconds: startSample / sampleRate,
      endSeconds: endSample / sampleRate,
      trimmedSamples: trimmedSamples.length > 0 ? trimmedSamples : samples
    };
  }
}
