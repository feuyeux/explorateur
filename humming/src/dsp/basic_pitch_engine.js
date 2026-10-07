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

function midiToNoteName(midi) {
  const name = NOTE_NAMES[((Math.round(midi) % 12) + 12) % 12];
  const octave = Math.floor(Math.round(midi) / 12) - 1;
  return `${name}${octave}`;
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

    const bp = new lib.BasicPitch(this.modelUrl());
    await bp.model; // 预加载 GraphModel

    const frames = [];
    const onsets = [];
    const contours = [];

    await bp.evaluateModel(
      samples16k,
      (f, o, c) => { frames.push(...f); onsets.push(...o); contours.push(...c); },
      (pct) => onProgress && onProgress(Math.round(pct * 100))
    );

    const rawNotes = lib.noteFramesToTime(
      lib.addPitchBendsToNoteEvents(contours, lib.outputToNotesPoly(frames, onsets, 0.25, 0.25, 5))
    );

    // NoteEventTime[] → 应用通用音符结构
    return (rawNotes || [])
      .filter((n) => n.durationSeconds > 0.05)
      .map((n) => {
        const midi = Math.round(n.pitchMidi);
        return {
          startTime: Math.max(0, Math.round(n.startTimeSeconds * 1000) / 1000),
          endTime: Math.round((n.startTimeSeconds + n.durationSeconds) * 1000) / 1000,
          duration: Math.round(n.durationSeconds * 1000) / 1000,
          midi,
          confidence: Math.round((n.amplitude || 0.8) * 100) / 100,
          noteName: midiToNoteName(midi)
        };
      });
  }
}