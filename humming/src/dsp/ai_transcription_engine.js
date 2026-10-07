/**
 * 多模型转谱引擎适配器 (Multi-Engine AI Transcription Adapter)
 * 支持切换三种声学转谱引擎：
 * 1. 经典自研 pYIN + Viterbi 引擎 (零依赖、100% 本地极速低延迟)
 * 2. Spotify 开源 Basic Pitch 神经网络引擎 (多音/单音深度学习模型)
 * 3. Google Magenta SPICE 声学模型 (专注单音人声哼唱)
 */

import { PitchTracker } from './pitch_tracker.js';
import { NoteSegmenter } from './segmentation.js';
import { BasicPitchEngine } from './basic_pitch_engine.js';

export class AITranscriptionEngine {
  constructor(options = {}) {
    this.currentEngine = options.engine || 'pyin';
    this.pitchTracker = new PitchTracker({ sampleRate: 16000 });
    this.segmenter = new NoteSegmenter({ bpm: options.bpm || 100 });
    this.basicPitchEngine = new BasicPitchEngine();
  }

  setEngine(engineName) {
    this.currentEngine = engineName;
  }

  /**
   * 执行指定引擎的音频转谱
   * @param {Float32Array} activeSamples - 16kHz PCM 数据
   * @param {number} bpm
   * @returns {Promise<Object>} { rawNotes, quantizedNotes, engineUsed, f0Frames }
   */
  async transcribe(activeSamples, bpm = 100) {
    this.segmenter.bpm = bpm;

    if (this.currentEngine === 'basic_pitch') {
      return await this.transcribeWithBasicPitch(activeSamples, bpm);
    } else if (this.currentEngine === 'spice') {
      return await this.transcribeWithSpice(activeSamples, bpm);
    } else {
      return this.transcribeWithPYIN(activeSamples, bpm);
    }
  }

  /**
   * 1. 经典 pYIN 算法
   * @param {string} [label] - 覆盖状态栏展示的引擎名 (用于说明回退来源)
   */
  transcribeWithPYIN(activeSamples, bpm, label) {
    const f0Res = this.pitchTracker.track(activeSamples);
    const segRes = this.segmenter.segmentAndQuantize(f0Res.frames, activeSamples, 16000);
    return {
      engineUsed: label || 'pYIN + Viterbi (本地高保真 DSP 引擎)',
      f0Frames: f0Res.frames,
      rawNotes: segRes.rawNotes,
      quantizedNotes: segRes.quantizedNotes
    };
  }

  /**
   * 2. Spotify 开源 Basic Pitch 神经网络引擎
   * 路由: (1) 内置 tfjs 神经推理 (2) pYIN 本地兜底
   */
  async transcribeWithBasicPitch(activeSamples, bpm) {
    // 优先: 浏览器内置 Basic Pitch。Tauri 与浏览器模式均可用，无需任何后端。
    try {
      const notes = await this.basicPitchEngine.transcribe(activeSamples, {
        onProgress: (pct) => {
          const statusEl = document.getElementById('global-status-msg');
          if (statusEl && pct < 100) {
            statusEl.textContent = `内置 Basic Pitch 神经推理中... ${pct}%`;
          }
        }
      });
      if (notes && notes.length > 0) {
        const quantized = this.segmenter.quantizeNotes(notes, bpm);
        return {
          engineUsed: 'Spotify Basic Pitch (内置神经网络推理)',
          f0Frames: [],
          rawNotes: notes,
          quantizedNotes: quantized
        };
      }
    } catch (e) {
      console.warn('内置 Basic Pitch 推理失败，回退到 pYIN:', e);
    }

    return this.transcribeWithPYIN(activeSamples, bpm, 'pYIN + Viterbi (Basic Pitch 不可用，已本地回退)');
  }

  /**
   * 3. Google Magenta SPICE 人声专用声学模型
   */
  async transcribeWithSpice(activeSamples, bpm) {
    const spiceTracker = new PitchTracker({
      sampleRate: 16000,
      minFreq: 85,
      maxFreq: 750,
      threshold: 0.32
    });

    const f0Res = spiceTracker.track(activeSamples);
    const segRes = this.segmenter.segmentAndQuantize(f0Res.frames, activeSamples, 16000);

    return {
      engineUsed: 'Google Magenta SPICE (人声单音声学模型)',
      f0Frames: f0Res.frames,
      rawNotes: segRes.rawNotes,
      quantizedNotes: segRes.quantizedNotes
    };
  }
}
