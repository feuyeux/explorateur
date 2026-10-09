/**
 * Spotify Basic Pitch 浏览器内置推理引擎适配器
 *
 * 架构决策 (实测得出, 见 scripts/ 备注): 使用 **主线程** 推理，不使用 Web Worker。
 * 原因: tfjs 的 WebGL 计算在 Worker 上下文中会挂起 —— 实测 Chrome 中 worker 以 WebGL
 * 就绪后，对 0.3s 音频推理卡死 >60s，而同一份代码在主线程 0.6s 完成。且 WebGL in Worker
 * 在 macOS WKWebView (Tauri 的 macOS 目标) 中基本不受支持，会导致应用永久挂起。
 * tfjs 的 GPU 调用均为 async (await tensor.data())，主线程在 GPU 操作之间会让出，
 * 因此推理期间界面仍可重绘 (会有卡顿，不会冻结)。
 *
 * 后端: 优先 WebGL，不可用时回退 CPU。
 * 不用 WASM 后端: tfjs 3.21 的 wasm 后端缺少 tf.signal.frame 算子支持，
 * 而 Basic Pitch 的 prepareData 依赖它，会抛 "Unknown dtype undefined"。
 *
 * 输出为通用音符结构 (startTime/endTime/duration/midi/confidence/noteName)，
 * 供上层量化、渲染与导出直接消费。
 */

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** 模型要求的输入采样率（bundle 内只对 AudioBuffer 输入校验，Float32Array 会被静默跳过，
 *  因此本适配器必须自己保证采样率正确 —— 否则 16kHz 数据被按 22050Hz 解释，
 *  全部音高系统性偏高 12·log2(22050/16000) ≈ +5.56 半音，时间轴压缩 0.725×） */
const MODEL_SAMPLE_RATE = 22050;

function midiToNoteName(midi) {
  const name = NOTE_NAMES[((Math.round(midi) % 12) + 12) % 12];
  const octave = Math.floor(Math.round(midi) / 12) - 1;
  return `${name}${octave}`;
}

/** 三次 Hermite 重采样（与 AudioPreprocessor.resample 同算法，避免引擎间耦合） */
function resample(input, fromRate, toRate) {
  if (fromRate === toRate) return new Float32Array(input);

  const ratio = fromRate / toRate;
  const outputLength = Math.round(input.length / ratio);
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i++) {
    const srcPos = i * ratio;
    const idx = Math.floor(srcPos);
    const frac = srcPos - idx;

    const y0 = idx > 0 ? input[idx - 1] : input[idx];
    const y1 = input[idx] || 0;
    const y2 = idx + 1 < input.length ? input[idx + 1] : y1;
    const y3 = idx + 2 < input.length ? input[idx + 2] : y2;

    const c0 = y1;
    const c1 = 0.5 * (y2 - y0);
    const c2 = y0 - 2.5 * y1 + 2 * y2 - 0.5 * y3;
    const c3 = 0.5 * (y3 - y0) + 1.5 * (y1 - y2);

    output[i] = ((c3 * frac + c2) * frac + c1) * frac + c0;
  }

  return output;
}

export class BasicPitchEngine {
  constructor() {
    this.lib = null;          // window.BasicPitchLib
    this.initPromise = null;
    this.backend = null;
  }

  modelUrl() {
    return new URL('../vendor/basic-pitch-model/model.json', import.meta.url).href;
  }

  /**
   * 懒加载 vendor bundle 并选定推理后端 (WebGL 优先, CPU 兜底)
   * @returns {Promise<Object>} window.BasicPitchLib
   */
  async ensureLib() {
    if (this.lib) return this.lib;
    if (this.initPromise) return this.initPromise;

    this.initPromise = (async () => {
      if (!window.BasicPitchLib) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = new URL('../vendor/basic-pitch.bundle.js', import.meta.url).href;
          script.onload = resolve;
          script.onerror = () => reject(new Error('basic-pitch.bundle.js 加载失败，请先运行 npm run build:vendor'));
          document.head.appendChild(script);
        });
      }
      const lib = window.BasicPitchLib;
      if (!lib) throw new Error('BasicPitchLib unavailable');

      try {
        await lib.tf.setBackend('webgl');
        await lib.tf.ready();
        if (lib.tf.getBackend() !== 'webgl') await lib.tf.setBackend('cpu');
      } catch (e) {
        console.warn('WebGL 后端不可用，回退默认后端:', e);
      }
      this.backend = lib.tf.getBackend();
      this.lib = lib;
      return lib;
    })();

    return this.initPromise;
  }

  /**
   * @param {Float32Array} samples16k - 16kHz 单声道 PCM
   * @param {Object} [options]
   * @param {(pct:number)=>void} [options.onProgress] - 0-100 推理进度
   * @returns {Promise<Array<{startTime,endTime,duration,midi,confidence,noteName}>>}
   */
  async transcribe(samples16k, options = {}) {
    const onProgress = options.onProgress || null;
    const lib = await this.ensureLib();

    // 模型按 22050Hz 训练：喂入前必须重采样（见 MODEL_SAMPLE_RATE 注释）
    const modelSamples = resample(samples16k, 16000, MODEL_SAMPLE_RATE);

    const bp = new lib.BasicPitch(this.modelUrl());
    await bp.model; // 预加载 GraphModel

    const frames = [];
    const onsets = [];
    const contours = [];

    await bp.evaluateModel(
      modelSamples,
      (f, o, c) => { frames.push(...f); onsets.push(...o); contours.push(...c); },
      (pct) => onProgress && onProgress(Math.round(pct * 100))
    );

    const rawNotes = lib.noteFramesToTime(
      lib.addPitchBendsToNoteEvents(contours, lib.outputToNotesPoly(frames, onsets, 0.25, 0.25, 5))
    );

    // NoteEventTime[] → 应用通用音符结构。
    // 按开始时间排序（noteFramesToTime 的输出不保证时序，实测常为倒序，
    // 上层编辑器与展示都假定时间序）；保留浮点 exactMidi 供单音精炼取中值。
    return (rawNotes || [])
      .filter((n) => n.durationSeconds > 0.05)
      .sort((a, b) => a.startTimeSeconds - b.startTimeSeconds)
      .map((n) => {
        const midi = Math.round(n.pitchMidi);
        return {
          startTime: Math.max(0, Math.round(n.startTimeSeconds * 1000) / 1000),
          endTime: Math.round((n.startTimeSeconds + n.durationSeconds) * 1000) / 1000,
          duration: Math.round(n.durationSeconds * 1000) / 1000,
          midi,
          exactMidi: n.pitchMidi,
          confidence: Math.round((n.amplitude || 0.8) * 100) / 100,
          noteName: midiToNoteName(midi)
        };
      });
  }
}