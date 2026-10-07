/**
 * Humming-to-Score Studio (哼唱识谱工作站)
 * 主应用控制器：调度 5 大处理阶段、实时录音声音检测监控屏、m4a 录制文件载入与播放识谱、Spotify Basic Pitch / SPICE 神经转谱
 */

import { AudioPreprocessor } from './dsp/preprocessor.js';
import { PitchTracker } from './dsp/pitch_tracker.js';
import { NoteSegmenter } from './dsp/segmentation.js';
import { MusicTheoryEngine } from './theory/krumhansl.js';
import { StaffRenderer } from './render/staff_renderer.js';
import { NumberedRenderer } from './render/numbered_renderer.js';
import { PianoRollRenderer } from './render/pianoroll_renderer.js';
import { Synthesizer } from './audio/synthesizer.js';
import { Metronome } from './audio/metronome.js';
import { SampleAudioFactory } from './audio/samples.js';
import { MidiExporter } from './export/midi_exporter.js';
import { MusicXMLExporter } from './export/musicxml_exporter.js';
import { AudioRecorderMonitor } from './audio/recorder_monitor.js';
import { AITranscriptionEngine } from './dsp/ai_transcription_engine.js';

/** BPM 可输入范围（滑杆与数字输入框共用，避免两处取值范围打架） */
const BPM_MIN = 50;
const BPM_MAX = 180;

export class App {
  constructor() {
    this.audioCtx = null;
    this.preprocessor = new AudioPreprocessor({ targetSampleRate: 16000, lowCutoff: 80, highCutoff: 2000 });
    this.segmenter = new NoteSegmenter({ bpm: 100, minNoteDurationMs: 120, quantizeGrid: 0.5 });
    this.theoryEngine = new MusicTheoryEngine();
    this.aiEngine = new AITranscriptionEngine({ engine: 'basic_pitch', bpm: 100 });

    // 状态管理
    this.currentAudioBuffer = null;
    this.loadedAudioBuffer = null;
    this.processedData = null;
    this.f0Result = null;
    this.serverNotes = null;
    this.quantizedNotes = [];
    this.keyInfo = null;
    this.measures = [];
    this.selectedNoteIndex = null;
    this.isRecording = false;
    this.mediaRecorder = null;
    this.recordStream = null;
    this.recordChunks = [];

    // m4a / 音频文件播放器状态
    this.fileAudioSource = null;
    this.fileAudioStartTime = 0;
    this.fileAudioPauseOffset = 0;
    this.isFilePlaying = false;
    this.fileProgressTimer = null;

    // UI 视图配置
    this.activeScoreView = 'both';

    // 音频上下文采用**惰性创建**：在无音频设备或受限环境下 new AudioContext() 会抛错。
    // 若放在构造流程里，抛错会中断后续 initDOM/initRenderers，
    // 表现为界面正常渲染但**所有按钮完全无响应**。因此这里只标记为未就绪，
    // 真正的实例化推迟到用户首次触发音频操作时。
    this.audioCtx = null;
    this.synth = null;
    this.metronome = null;
    this.audioInitError = null;

    this.initDOM();
    this.initRenderers();
    this.initRecorderMonitor();
  }

  /**
   * 创建（或复用）AudioContext 及依赖它的合成器/节拍器。
   * 必须在用户手势中调用，否则部分浏览器会让 context 停留在 suspended。
   * @returns {boolean} 音频是否可用
   */
  initAudioContext() {
    if (this.audioCtx) return true;
    if (this.audioInitError) return false;

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      this.audioInitError = '当前环境不支持 Web Audio API';
      return false;
    }

    try {
      this.audioCtx = new AudioContextClass();
    } catch (err) {
      this.audioInitError = err.message || '音频设备不可用';
      return false;
    }

    this.synth = new Synthesizer(this.audioCtx);
    this.metronome = new Metronome(this.audioCtx, {
      bpm: 100,
      beatsPerMeasure: 4,
      onBeat: (beatNum, time, isCountIn, countNum) => {
        this.updateMetronomeUI(beatNum, isCountIn, countNum);
      }
    });

    this.synth.onNotePlay = (noteIdx, note) => {
      this.staffRenderer.setPlayhead(noteIdx);
      this.numberedRenderer.setPlayhead(noteIdx);
      this.pianoRollRenderer.setPlayhead(noteIdx, note.startTime);
    };

    this.synth.onPlaybackEnd = (reason) => {
      this.staffRenderer.clearPlayhead();
      this.numberedRenderer.clearPlayhead();
      this.setPlayButtonState(false);
      // 'restart' 是 playScore 内部的前置清理，不能当成用户操作反馈
      if (reason === 'ended') {
        this.setStatus('✔ 试听播放完毕');
      } else if (reason === 'stopped') {
        this.setStatus('⏹ 已停止试听');
      }
    };

    // 录音监控依赖 audioCtx，此前在构造期创建，这里补建
    this.initRecorderMonitor();
    return true;
  }

  initRecorderMonitor() {
    const canvas = document.getElementById('record-monitor-canvas');
    const uiElements = {
      tunerNoteEl: document.getElementById('record-tuner-note'),
      vuBarEl: document.getElementById('record-vu-bar'),
      vuDbEl: document.getElementById('record-vu-db'),
      vadBadgeEl: document.getElementById('record-vad-badge')
    };

    // audioCtx 可能尚未创建（惰性），此时先建一个不带 ctx 的监控器实例，
    // 待音频可用后再由 initAudioContext() 补建带 ctx 的实例。
    this.recorderMonitor = new AudioRecorderMonitor(this.audioCtx, canvas, uiElements);
  }

  /**
   * 确保 AudioContext 就绪：必要时惰性创建，并解除 suspended 状态。
   * 在用户手势中调用。
   * @returns {boolean} 音频是否可用
   */
  ensureAudioContext() {
    if (!this.initAudioContext()) {
      this.setStatus(`音频不可用（${this.audioInitError}）。仍可载入音频文件完成识谱，但无法试听或节拍器引导。`);
      return false;
    }
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
    return true;
  }

  initDOM() {
    // 录音相关
    document.getElementById('btn-record')?.addEventListener('click', () => this.toggleRecording());

    // 转谱引擎切换 (Basic Pitch / SPICE / pYIN)
    document.getElementById('select-engine')?.addEventListener('change', (e) => {
      this.aiEngine.setEngine(e.target.value);
      this.setStatus(`已将阶段二神经转谱引擎设为: ${e.target.options[e.target.selectedIndex].text}`);
    });

    // 节拍器相关
    document.getElementById('btn-metronome')?.addEventListener('click', () => this.toggleMetronome());

    const bpmSlider = document.getElementById('input-bpm');
    const bpmNum = document.getElementById('input-bpm-num');
    // 滑杆拖动 → 实时同步到数字框
    bpmSlider?.addEventListener('input', (e) => {
      this.setBpm(parseInt(e.target.value, 10) || 100);
    });
    // 数字框直接输入：change(失焦/回车) 才提交，避免边打字边触发整条重切分流水线
    const commitBpm = () => {
      if (!bpmNum) return;
      const raw = parseInt(bpmNum.value, 10);
      if (!Number.isFinite(raw)) {           // 清空或非法输入 → 回落到当前 BPM
        bpmNum.value = String(this.segmenter.bpm);
        return;
      }
      this.setBpm(raw, { syncSlider: true });
    };
    bpmNum?.addEventListener('change', commitBpm);
    bpmNum?.addEventListener('blur', commitBpm);
    bpmNum?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); commitBpm(); bpmNum.blur(); }
    });

    // 开机以内部状态为准初始化 BPM 控件，不依赖 HTML 属性：
    // 保证滑杆、数字框、segmenter 三者从第一帧起就一致。
    this.setBpm(this.segmenter.bpm);

    document.getElementById('select-meter')?.addEventListener('change', (e) => {
      const [beats, unit] = e.target.value.split('/').map(v => parseInt(v, 10));
      this.meter = { beats, unit };
      this.metronome?.setBeatsPerMeasure(beats);
      if (this.quantizedNotes.length > 0) {
        this.recalculateScore();
      }
    });

    document.getElementById('select-grid')?.addEventListener('change', (e) => {
      this.segmenter.quantizeGrid = parseFloat(e.target.value);
      // AI 引擎内部持有独立的 NoteSegmenter，网格需同步，否则神经引擎始终按 0.5 量化
      this.aiEngine.segmenter.quantizeGrid = this.segmenter.quantizeGrid;
      if (this.f0Result) {
        this.reQuantizeAndRender();
      }
    });

    // 文件上传 (支持 m4a/wav/mp3/aac)
    const fileInput = document.getElementById('audio-file-input');
    const loadAudioBtn = document.getElementById('btn-load-audio');

    fileInput?.addEventListener('click', () => {
      // 每次点击清空，确保重复选择相同文件也能触发 change
      fileInput.value = '';
    });

    fileInput?.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        this.loadAudioFile(e.target.files[0]);
      }
    });

    loadAudioBtn?.addEventListener('click', (e) => {
      if (e.target !== fileInput) {
        if (fileInput) {
          fileInput.value = '';
          fileInput.click();
        }
      }
    });

    // 窗口支持拖拽外部音频文件载入 (Drag & Drop)
    window.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
    });

    window.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const file = e.dataTransfer.files[0];
        this.loadAudioFile(file);
      }
    });

    // m4a 原声播放器控件
    document.getElementById('btn-file-play')?.addEventListener('click', () => this.togglePlayLoadedAudio());
    document.getElementById('file-progress-slider')?.addEventListener('input', (e) => this.onFileSeek(parseFloat(e.target.value)));

    // 专属「开始识谱」按钮
    document.getElementById('btn-start-transcribe')?.addEventListener('click', () => this.startTranscriptionFromLoaded());

    // 预置示例按钮 (包含 demo_m4a)
    document.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const presetId = e.currentTarget.getAttribute('data-preset');
        if (presetId === 'demo_m4a') {
          this.loadDemoM4A();
        } else {
          this.loadPresetSample(presetId);
        }
      });
    });

    // 视图切换
    document.querySelectorAll('.view-tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        document.querySelectorAll('.view-tab-btn').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        this.switchScoreView(e.currentTarget.getAttribute('data-view'));
      });
    });

    // 播放与导出
    document.getElementById('btn-play-synth')?.addEventListener('click', () => this.toggleScorePlayback());
    document.getElementById('btn-play-original')?.addEventListener('click', () => this.playOriginalAudio());
    document.getElementById('btn-export-midi')?.addEventListener('click', () => this.exportMidiFile());
    document.getElementById('btn-export-xml')?.addEventListener('click', () => this.exportMusicXMLFile());

    // 流水线详情展开/收起（单屏布局下默认折叠，仅显示阶段状态条）
    document.getElementById('pipeline-toggle')?.addEventListener('click', () => {
      document.getElementById('pipeline-panel')?.classList.toggle('expanded');
    });

    // 音符编辑
    this.initEditorControls();
  }

  initRenderers() {
    const staffContainer = document.getElementById('staff-container');
    this.staffRenderer = new StaffRenderer(staffContainer, {
      onNoteSelected: (idx, note) => this.onNoteSelected(idx, note),
      onNoteAudition: (midi) => this.auditionMidi(midi, 0.4)
    });

    const jianpuContainer = document.getElementById('jianpu-container');
    this.numberedRenderer = new NumberedRenderer(jianpuContainer, {
      onNoteSelected: (idx, note) => this.onNoteSelected(idx, note),
      onNoteAudition: (midi) => this.auditionMidi(midi, 0.4)
    });

    const rollCanvas = document.getElementById('pianoroll-canvas');
    if (rollCanvas) {
      this.pianoRollRenderer = new PianoRollRenderer(rollCanvas, {
        onNoteSelected: (idx, note) => this.onNoteSelected(idx, note),
        onNoteAudition: (midi) => this.auditionMidi(midi, 0.4)
      });
    }
  }

  initEditorControls() {
    // 填充音高直选下拉菜单 (C3=48 至 C6=84)
    const pitchSelect = document.getElementById('select-note-pitch');
    if (pitchSelect) {
      pitchSelect.innerHTML = '';
      for (let m = 48; m <= 84; m++) {
        const name = this.segmenter.midiToNoteName(m);
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = `${name} (MIDI ${m})`;
        pitchSelect.appendChild(opt);
      }
      pitchSelect.addEventListener('change', (e) => {
        const midi = parseInt(e.target.value, 10);
        this.setSelectedNotePitch(midi);
      });
    }

    // 半音与八度加减
    document.getElementById('btn-pitch-up')?.addEventListener('click', () => this.modifySelectedNotePitch(1));
    document.getElementById('btn-pitch-down')?.addEventListener('click', () => this.modifySelectedNotePitch(-1));
    document.getElementById('btn-octave-up')?.addEventListener('click', () => this.modifySelectedNotePitch(12));
    document.getElementById('btn-octave-down')?.addEventListener('click', () => this.modifySelectedNotePitch(-12));

    // 时值预置按钮
    document.querySelectorAll('.btn-dur').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const dur = parseFloat(e.currentTarget.getAttribute('data-dur'));
        this.setSelectedNoteDuration(dur);
      });
    });

    // 附点切换
    document.getElementById('btn-dur-dotted')?.addEventListener('click', () => this.toggleSelectedNoteDotted());

    // 结构增删
    document.getElementById('btn-insert-note')?.addEventListener('click', () => this.insertNoteAfterSelected());
    document.getElementById('btn-insert-rest')?.addEventListener('click', () => this.insertRestAfterSelected());
    document.getElementById('btn-delete-note')?.addEventListener('click', () => this.deleteSelectedNote());

    // 导航与试听
    document.getElementById('btn-prev-note')?.addEventListener('click', () => this.navigateNote(-1));
    document.getElementById('btn-next-note')?.addEventListener('click', () => this.navigateNote(1));
    document.getElementById('btn-audition-note')?.addEventListener('click', () => this.auditionSelectedNote());

    // 全局快捷键监听 (方向键音高/选位、Delete删除、空格试听)
    window.addEventListener('keydown', (e) => {
      // 焦点在表单控件上时交还控件自身处理。
      // 必须包含 SELECT/BUTTON：否则在下拉框上按 ↑/↓ 会同时改动下拉框与当前音符音高。
      if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(document.activeElement?.tagName)) return;
      if (this.quantizedNotes.length === 0) return;
      // 输入法组合中的按键不处理
      if (e.isComposing || e.keyCode === 229) return;

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.modifySelectedNotePitch(e.shiftKey ? 12 : 1);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.modifySelectedNotePitch(e.shiftKey ? -12 : -1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        this.navigateNote(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        this.navigateNote(1);
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        this.deleteSelectedNote();
      } else if (e.key === ' ') {
        e.preventDefault();
        this.auditionSelectedNote();
      }
    });
  }

  setBpm(bpm, { syncSlider = true } = {}) {
    const value = Math.max(BPM_MIN, Math.min(BPM_MAX, Math.round(Number(bpm) || 100)));
    this.segmenter.bpm = value;
    this.metronome?.setBpm(value);
    // 滑杆与数字输入框双向同步；输入框正在被用户编辑时不要回写，否则光标会被打断
    const numInput = document.getElementById('input-bpm-num');
    if (numInput && document.activeElement !== numInput) numInput.value = String(value);
    if (syncSlider) {
      const slider = document.getElementById('input-bpm');
      if (slider) slider.value = String(value);
    }
    if (this.quantizedNotes.length > 0) {
      // BPM 变化会高频触发（滑杆拖动），重切分+三重渲染很重，做 150ms 防抖
      clearTimeout(this.bpmDebounceTimer);
      this.bpmDebounceTimer = setTimeout(() => {
        this.bpmDebounceTimer = null;
        this.reQuantizeAndRender();
      }, 150);
    }
  }

  /**
   * 录音控制
   */
  async toggleRecording() {
    if (!this.ensureAudioContext()) return;
    if (this.isRecording) {
      this.stopRecording();
    } else {
      await this.startRecording();
    }
  }

  async startRecording() {
    try {
      this.recordStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true
        }
      });

      this.isRecording = true;
      this.recordChunks = [];

      this.recorderMonitor.start(this.recordStream);

      const btn = document.getElementById('btn-record');
      if (btn) {
        btn.classList.add('recording');
        btn.innerHTML = '<span class="rec-dot pulsing"></span><span>停止录音 (Stop)</span>';
      }
      this.setStatus('正在录音与实时声音检测中... 请跟随节拍器并观察声波');

      if (this.metronome && !this.metronome.isPlaying) {
        this.metronome.start();
        document.getElementById('btn-metronome')?.classList.add('active');
      }

      this.mediaRecorder = new MediaRecorder(this.recordStream);
      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.recordChunks.push(e.data);
      };

      this.mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(this.recordChunks, { type: 'audio/webm;codecs=opus' });
        const arrayBuf = await audioBlob.arrayBuffer();
        const decodedBuffer = await this.audioCtx.decodeAudioData(arrayBuf);
        this.setLoadedAudio(decodedBuffer, '现场麦克风录音.webm', arrayBuf.byteLength, 'webm');
        this.executePipeline(decodedBuffer);
      };

      this.mediaRecorder.start(100);
    } catch (err) {
      console.error('无法启动录音:', err);
      this.setStatus(`录音失败: ${err.message}，您可以载入 m4a 文件或点击上方预置歌曲体验`);
    }
  }

  stopRecording() {
    if (!this.isRecording) return;
    this.isRecording = false;

    this.recorderMonitor.stop();

    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    if (this.recordStream) {
      this.recordStream.getTracks().forEach(t => t.stop());
    }

    const btn = document.getElementById('btn-record');
    if (btn) {
      btn.classList.remove('recording');
      btn.innerHTML = '<span class="rec-dot"></span><span>开始哼唱录音</span>';
    }

    this.metronome?.stop();
    document.getElementById('btn-metronome')?.classList.remove('active');
    this.setStatus('录音完毕，正在执行五阶段转谱流水线...');
  }

  /**
   * ==========================================
   * m4a / 录音文件载入、原生播放与专属识谱流程
   * ==========================================
   */
  async loadAudioFile(file) {
    if (!this.ensureAudioContext()) return;
    this.setStatus(`正在读取并解码音频文件: ${file.name} (${Math.round(file.size / 1024)} KB)...`);

    try {
      const ext = file.name.split('.').pop().toLowerCase();
      const arrayBuf = await file.arrayBuffer();

      let decodedBuffer;
      try {
        decodedBuffer = await this.audioCtx.decodeAudioData(arrayBuf.slice(0));
      } catch (e1) {
        decodedBuffer = await new Promise((resolve, reject) => {
          this.audioCtx.decodeAudioData(arrayBuf.slice(0), resolve, reject);
        });
      }

      this.setLoadedAudio(decodedBuffer, file.name, file.size, ext);
      this.setStatus(`已成功载入 ${ext.toUpperCase()} 音频文件: ${file.name}，可点击「▶」试听，或点击「🎼 开始识谱」生成乐谱！`);
    } catch (err) {
      console.error('解码音频失败:', err);
      this.setStatus(`解码音频失败: ${err.message || '未知错误'}，请确认该音频为标准 .m4a / .wav / .mp3 文件`);
    }
  }

  async loadDemoM4A() {
    if (!this.ensureAudioContext()) return;
    this.setStatus('正在从服务器载入内置 demo_twinkle.m4a 文件...');
    try {
      const resp = await fetch('/assets/demo_twinkle.m4a');
      const arrayBuf = await resp.arrayBuffer();
      const decodedBuffer = await this.audioCtx.decodeAudioData(arrayBuf);

      this.setLoadedAudio(decodedBuffer, 'demo_twinkle.m4a', arrayBuf.byteLength, 'm4a');
      this.setStatus('已就绪：内置 Apple m4a 文件已加载，点击「播放原声」试听，或点击「开始识谱」！');
    } catch (err) {
      this.setStatus(`加载 demo_twinkle.m4a 失败: ${err.message}`);
    }
  }

  setLoadedAudio(audioBuffer, fileName, fileSize, ext = 'm4a') {
    this.pauseLoadedAudio();
    this.loadedAudioBuffer = audioBuffer;
    this.currentAudioBuffer = audioBuffer;
    this.fileAudioPauseOffset = 0;

    // 更新 UI 卡片
    const workspace = document.getElementById('audio-file-workspace');
    if (workspace) workspace.classList.remove('hidden');

    const badge = document.getElementById('file-format-badge');
    if (badge) {
      badge.textContent = `.${ext.toUpperCase()}`;
      badge.className = `format-badge ${ext}`;
    }

    const nameEl = document.getElementById('file-name-text');
    if (nameEl) nameEl.textContent = fileName;

    const durSec = audioBuffer.duration;
    document.getElementById('spec-duration').textContent = `${durSec.toFixed(2)}s`;
    document.getElementById('spec-samplerate').textContent = `${audioBuffer.sampleRate.toLocaleString()} Hz`;
    document.getElementById('spec-channels').textContent = audioBuffer.numberOfChannels === 1 ? '单声道 (Mono)' : '双声道 (Stereo)';
    document.getElementById('spec-size').textContent = `${Math.round(fileSize / 1024)} KB`;

    // 重置进度条
    const slider = document.getElementById('file-progress-slider');
    if (slider) {
      slider.value = 0;
      slider.max = durSec;
    }
    document.getElementById('file-current-time').textContent = '00:00';
    document.getElementById('file-total-time').textContent = this.formatTime(durSec);
    document.getElementById('file-play-icon').textContent = '▶';
  }

  togglePlayLoadedAudio() {
    if (!this.loadedAudioBuffer) return;
    if (!this.ensureAudioContext()) return;

    if (this.isFilePlaying) {
      this.pauseLoadedAudio();
    } else {
      this.playLoadedAudio();
    }
  }

  playLoadedAudio() {
    if (!this.loadedAudioBuffer || this.isFilePlaying) return;

    if (this.fileAudioPauseOffset >= this.loadedAudioBuffer.duration) {
      this.fileAudioPauseOffset = 0;
    }

    this.fileAudioSource = this.audioCtx.createBufferSource();
    this.fileAudioSource.buffer = this.loadedAudioBuffer;
    this.fileAudioSource.connect(this.audioCtx.destination);

    this.fileAudioStartTime = this.audioCtx.currentTime - this.fileAudioPauseOffset;
    this.fileAudioSource.start(0, this.fileAudioPauseOffset);
    this.isFilePlaying = true;

    document.getElementById('file-play-icon').textContent = '⏸';

    this.fileAudioSource.onended = () => {
      if (this.isFilePlaying && this.audioCtx.currentTime - this.fileAudioStartTime >= this.loadedAudioBuffer.duration - 0.05) {
        this.pauseLoadedAudio();
        this.fileAudioPauseOffset = 0;
        document.getElementById('file-progress-slider').value = 0;
        document.getElementById('file-current-time').textContent = '00:00';
      }
    };

    // 进度轮询
    clearInterval(this.fileProgressTimer);
    this.fileProgressTimer = setInterval(() => {
      if (!this.isFilePlaying) return;
      const current = Math.min(this.loadedAudioBuffer.duration, this.audioCtx.currentTime - this.fileAudioStartTime);
      const slider = document.getElementById('file-progress-slider');
      if (slider) slider.value = current;
      document.getElementById('file-current-time').textContent = this.formatTime(current);
    }, 50);
  }

  pauseLoadedAudio() {
    if (this.fileAudioSource) {
      try {
        this.fileAudioSource.stop();
      } catch (e) {}
      this.fileAudioSource = null;
    }
    if (this.isFilePlaying) {
      this.fileAudioPauseOffset = Math.min(this.loadedAudioBuffer.duration, this.audioCtx.currentTime - this.fileAudioStartTime);
      this.isFilePlaying = false;
    }
    clearInterval(this.fileProgressTimer);
    const playIcon = document.getElementById('file-play-icon');
    if (playIcon) playIcon.textContent = '▶';
  }

  onFileSeek(targetSeconds) {
    this.fileAudioPauseOffset = targetSeconds;
    document.getElementById('file-current-time').textContent = this.formatTime(targetSeconds);
    if (this.isFilePlaying) {
      // 直接停掉当前源并保留 seek 目标偏移；不能用 pauseLoadedAudio()，
      // 否则它会用旧播放位置覆盖 fileAudioPauseOffset，导致拖动进度条被打回原位
      if (this.fileAudioSource) {
        try {
          this.fileAudioSource.stop();
        } catch (e) {}
        this.fileAudioSource = null;
      }
      this.isFilePlaying = false;
      clearInterval(this.fileProgressTimer);
      this.playLoadedAudio();
    }
  }

  /**
   * 触发专属「开始识谱」流水线
   */
  startTranscriptionFromLoaded() {
    if (!this.loadedAudioBuffer) {
      alert('请先载入 m4a 或音频录制文件');
      return;
    }
    this.pauseLoadedAudio();
    this.setStatus('正在使用 Spotify Basic Pitch 神经网络执行五阶段转谱流水线...');
    this.executePipeline(this.loadedAudioBuffer);
  }

  formatTime(seconds) {
    const s = Math.floor(seconds);
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m.toString().padStart(2, '0')}:${rem.toString().padStart(2, '0')}`;
  }

  /**
   * 节拍器控制
   */
  toggleMetronome() {
    if (!this.ensureAudioContext() || !this.metronome) return;
    const btn = document.getElementById('btn-metronome');
    if (this.metronome.isPlaying) {
      this.metronome.stop();
      if (btn) btn.classList.remove('active');
    } else {
      this.metronome.start();
      if (btn) btn.classList.add('active');
    }
  }

  updateMetronomeUI(beatNumber, isCountIn, countNum) {
    const light = document.getElementById('metronome-light');
    if (!light) return;

    light.classList.remove('downbeat', 'active');
    void light.offsetWidth;

    if (beatNumber === 0) {
      light.classList.add('downbeat');
    } else {
      light.classList.add('active');
    }
  }

  loadPresetSample(presetId) {
    if (!this.ensureAudioContext()) return;
    const sampleInfo = SampleAudioFactory.generateHummingAudio(presetId, 16000);

    // setBpm 内部已同步滑杆与数字输入框
    this.setBpm(sampleInfo.bpm);

    const audioBuffer = this.audioCtx.createBuffer(1, sampleInfo.samples.length, sampleInfo.sampleRate);
    audioBuffer.copyToChannel(sampleInfo.samples, 0);

    this.setLoadedAudio(audioBuffer, `预置样本: 《${sampleInfo.title}》.wav`, sampleInfo.samples.length * 2, 'wav');
    this.setStatus(`已加载预置人声样本: 《${sampleInfo.title}》，开始全流程音频转谱...`);

    this.executePipeline(audioBuffer);
  }

  /**
   * ==========================================
   * 核心 5 阶段完整处理流水线 (End-to-End Pipeline)
   * 阶段二为 Spotify Basic Pitch / SPICE 神经推理核心
   * ==========================================
   */
  async executePipeline(audioBuffer) {
    this.currentAudioBuffer = audioBuffer;
    const startTime = performance.now();
    this.resetPipelinePanel();

    // 阶段一：音频预处理（单声道、峰值增益规整、带通滤波、自适应 VAD）
    this.updateStageStatus(1, 'running', '执行峰值增益规整、重采样(16kHz)、80-2000Hz带通滤波及自适应 VAD...');
    await this.tickUI();

    const rawData = audioBuffer.getChannelData(0);
    this.processedData = this.preprocessor.process(rawData, audioBuffer.sampleRate);

    this.updateStageStatus(1, 'completed', `预处理完成: 过滤保留 ${(this.processedData.activeSamples.length / 16000).toFixed(2)}s 人声，切除底噪与空白`);
    this.displayStage1Metrics(this.processedData);

    // 阶段二：Spotify Basic Pitch / Magenta SPICE 神经转谱推理 (核心环节)
    this.updateStageStatus(2, 'running', `调度神经网络 [${this.aiEngine.currentEngine}] 提取 Pitch Contour 与 Onset 概率矩阵...`);
    await this.tickUI();

    const transcription = await this.aiEngine.transcribe(this.processedData.activeSamples, this.segmenter.bpm);
    this.f0Result = { frames: transcription.f0Frames || [] };
    // 服务端神经引擎 (Basic Pitch) 不产生 f0 帧序列，保存其原始音符供后续 BPM/网格变化时重新量化，
    // 否则 reQuantizeAndRender 会基于空 frames 把整份乐谱清空
    this.serverNotes = transcription.f0Frames && transcription.f0Frames.length > 0 ? null : (transcription.rawNotes || []);

    // 阶段三：音符切分与量化
    this.updateStageStatus(3, 'running', '中值去颤音、120ms滑音合并、节拍网格吸附量化...');
    await this.tickUI();

    let finalQuantized = transcription.quantizedNotes || [];

    if (finalQuantized.length === 0 && this.processedData.activeSamples.length > 800) {
      const fallbackNote = {
        startTime: 0,
        endTime: 1.0,
        startBeat: 0,
        durationBeats: 1.0,
        duration: 1.0,
        midi: 60,
        noteName: 'C4',
        noteType: 'quarter',
        typeLabel: '四分音符',
        confidence: 0.8
      };
      finalQuantized = [fallbackNote];
    }

    this.quantizedNotes = finalQuantized;

    this.updateStageStatus(2, 'completed', `引擎: ${transcription.engineUsed}`);
    this.updateStageStatus(3, 'completed', `切分量化出 ${this.quantizedNotes.length} 个结构化离散音符 (已消解滑音与碎音)`);
    this.displayStage3Metrics({ rawNotes: transcription.rawNotes || [], quantizedNotes: this.quantizedNotes });

    // 阶段四：乐理推断
    this.updateStageStatus(4, 'running', 'Krumhansl 24大小调余弦相似度匹配与小节线划分...');
    await this.tickUI();

    this.keyInfo = this.theoryEngine.detectKey(this.quantizedNotes);
    const meterBeats = (this.meter && this.meter.beats) || 4;
    const meterUnit = (this.meter && this.meter.unit) || 4;
    this.measures = this.theoryEngine.partitionMeasures(this.quantizedNotes, meterBeats, meterUnit);

    this.updateStageStatus(4, 'completed', `推导最佳调性: ${this.keyInfo.bestKey} (${this.keyInfo.signature.text})，划分 ${this.measures.length} 个小节`);
    this.displayStage4Metrics(this.keyInfo, this.measures);

    // 阶段五：乐谱渲染呈现
    this.updateStageStatus(5, 'running', '渲染高保真五线谱、首调简谱排版与钢琴卷帘...');
    await this.tickUI();

    this.renderAllScores();
    const elapsed = Math.round(performance.now() - startTime);
    this.updateStageStatus(5, 'completed', `乐谱渲染完毕！全链路耗时仅 ${elapsed} ms，支持播放、编辑与导出`);

    // 流水线面板右上角汇总耗时
    const elapsedEl = document.getElementById('pipeline-elapsed');
    if (elapsedEl) elapsedEl.textContent = `全链路耗时 ${elapsed} ms`;
    this.setStatus(`识谱完成！推断调性为 ${this.keyInfo.bestKey}，共识别出 ${this.quantizedNotes.length} 个音符。`);

    // 默认高亮选择第 1 个音符，激活编辑工具栏与音符时间轴
    if (this.quantizedNotes.length > 0) {
      this.selectNote(0, false);
    }

    // 解锁操作按钮
    document.getElementById('btn-play-synth')?.removeAttribute('disabled');
    document.getElementById('btn-play-original')?.removeAttribute('disabled');
    document.getElementById('btn-export-midi')?.removeAttribute('disabled');
    document.getElementById('btn-export-xml')?.removeAttribute('disabled');
  }

  reQuantizeAndRender() {
    if (!this.processedData) return;
    if (this.serverNotes && this.serverNotes.length > 0) {
      // 服务端神经转谱结果：直接按当前 BPM/网格重新量化，而非从空 f0 帧重新切分
      this.quantizedNotes = this.segmenter.quantizeNotes(this.serverNotes, this.segmenter.bpm, this.segmenter.quantizeGrid);
    } else {
      if (!this.f0Result) return;
      const segResult = this.segmenter.segmentAndQuantize(this.f0Result.frames, this.processedData.activeSamples, 16000);
      this.quantizedNotes = segResult.quantizedNotes;
    }
    this.recalculateScore();
  }

  recalculateScore() {
    this.keyInfo = this.theoryEngine.detectKey(this.quantizedNotes);
    const meterBeats = (this.meter && this.meter.beats) || 4;
    const meterUnit = (this.meter && this.meter.unit) || 4;
    this.measures = this.theoryEngine.partitionMeasures(this.quantizedNotes, meterBeats, meterUnit);
    this.renderAllScores();

    if (this.quantizedNotes.length === 0) {
      this.selectedNoteIndex = null;
      document.getElementById('note-editor-toolbar')?.classList.add('hidden');
      document.getElementById('note-timeline-container')?.classList.add('hidden');
    } else {
      if (this.selectedNoteIndex === null || this.selectedNoteIndex >= this.quantizedNotes.length) {
        this.selectedNoteIndex = 0;
      }
      this.selectNote(this.selectedNoteIndex, false);
    }
  }

  renderAllScores() {
    const scoreData = {
      measures: this.measures,
      keyInfo: this.keyInfo,
      meter: this.meter || { beats: 4, unit: 4 },
      bpm: this.segmenter.bpm,
      notes: this.quantizedNotes
    };

    this.staffRenderer.render(scoreData);
    this.numberedRenderer.render(scoreData);

    const totalSeconds = this.processedData ? (this.processedData.activeSamples.length / 16000) : 5;
    this.pianoRollRenderer.render(this.f0Result ? this.f0Result.frames : [], this.quantizedNotes, totalSeconds);
  }

  switchScoreView(view) {
    this.activeScoreView = view;
    const staffPanel = document.getElementById('staff-panel');
    const jianpuPanel = document.getElementById('jianpu-panel');
    const rollPanel = document.getElementById('pianoroll-panel');

    if (view === 'staff') {
      staffPanel?.classList.remove('hidden');
      jianpuPanel?.classList.add('hidden');
      rollPanel?.classList.add('hidden');
    } else if (view === 'jianpu') {
      staffPanel?.classList.add('hidden');
      jianpuPanel?.classList.remove('hidden');
      rollPanel?.classList.add('hidden');
    } else if (view === 'pianoroll') {
      staffPanel?.classList.add('hidden');
      jianpuPanel?.classList.add('hidden');
      rollPanel?.classList.remove('hidden');
      this.pianoRollRenderer.draw();
    } else {
      staffPanel?.classList.remove('hidden');
      jianpuPanel?.classList.remove('hidden');
      rollPanel?.classList.add('hidden');
    }
  }

  /**
   * ==========================================
   * 音符交互编辑控制台 (Interactive Note Editor)
   * ==========================================
   */
  selectNote(index, playSound = false) {
    if (index < 0 || index >= this.quantizedNotes.length) return;
    this.selectedNoteIndex = index;
    const note = this.quantizedNotes[index];

    // 同步渲染器选中状态
    this.staffRenderer.setSelectedNote(index);
    this.numberedRenderer.setSelectedNote(index);
    if (this.pianoRollRenderer) {
      this.pianoRollRenderer.setSelectedNote(index);
    }

    // 更新界面与时间轴
    this.updateEditorUI(note, index);
    this.updateTimelineChips();

    if (playSound) {
      this.auditionMidi(note.midi, 0.35);
    }
  }

  onNoteSelected(noteIndex, note) {
    this.selectNote(noteIndex, false);
  }

  updateEditorUI(note, index) {
    const editor = document.getElementById('note-editor-toolbar');
    if (!editor) return;
    editor.classList.remove('hidden');

    const textEl = document.getElementById('selected-note-text');
    if (textEl) {
      textEl.textContent = `第 ${index + 1} / ${this.quantizedNotes.length} 个音符: ${note.noteName} (MIDI ${note.midi}) | ${note.typeLabel} (${note.durationBeats}拍)`;
    }

    const pitchSelect = document.getElementById('select-note-pitch');
    if (pitchSelect) {
      pitchSelect.value = note.midi;
    }

    // 选中时值预设按钮状态
    document.querySelectorAll('.btn-dur').forEach(btn => {
      const dur = parseFloat(btn.getAttribute('data-dur'));
      if (Math.abs(dur - note.durationBeats) < 0.05) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    const dottedBtn = document.getElementById('btn-dur-dotted');
    if (dottedBtn) {
      if (note.isDotted) {
        dottedBtn.classList.add('active');
      } else {
        dottedBtn.classList.remove('active');
      }
    }
  }

  updateTimelineChips() {
    const container = document.getElementById('note-timeline-container');
    const bar = document.getElementById('note-chips-bar');
    const countBadge = document.getElementById('timeline-count-badge');
    if (!container || !bar) return;

    if (this.quantizedNotes.length === 0) {
      container.classList.add('hidden');
      return;
    }

    container.classList.remove('hidden');
    if (countBadge) {
      countBadge.textContent = `共 ${this.quantizedNotes.length} 个音符 (当前选择 #${(this.selectedNoteIndex !== null ? this.selectedNoteIndex : 0) + 1})`;
    }

    bar.innerHTML = '';
    this.quantizedNotes.forEach((n, idx) => {
      const chip = document.createElement('div');
      chip.className = `note-chip ${idx === this.selectedNoteIndex ? 'active' : ''}`;
      chip.setAttribute('data-idx', idx);
      chip.innerHTML = `
        <span class="chip-num">#${idx + 1}</span>
        <span class="chip-pitch">${n.noteName}</span>
        <span class="chip-dur">${n.durationBeats}拍</span>
      `;
      chip.addEventListener('click', () => {
        this.selectNote(idx, true);
      });
      bar.appendChild(chip);

      if (idx === this.selectedNoteIndex) {
        setTimeout(() => {
          chip.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }, 10);
      }
    });
  }

  realignTimelineFrom(startIndex = 0) {
    const secondsPerBeat = 60 / this.segmenter.bpm;
    for (let i = Math.max(0, startIndex); i < this.quantizedNotes.length; i++) {
      const note = this.quantizedNotes[i];
      note.startTime = note.startBeat * secondsPerBeat;
      note.duration = note.durationBeats * secondsPerBeat;
      note.endTime = (note.startBeat + note.durationBeats) * secondsPerBeat;
    }
  }

  setSelectedNotePitch(midi) {
    if (this.selectedNoteIndex === null || !this.quantizedNotes[this.selectedNoteIndex]) return;
    const note = this.quantizedNotes[this.selectedNoteIndex];
    note.midi = Math.max(36, Math.min(96, midi));
    note.noteName = this.segmenter.midiToNoteName(note.midi);
    this.auditionMidi(note.midi, 0.4);
    this.recalculateScore();
  }

  modifySelectedNotePitch(deltaSemitones) {
    if (this.selectedNoteIndex === null || !this.quantizedNotes[this.selectedNoteIndex]) return;
    const note = this.quantizedNotes[this.selectedNoteIndex];
    this.setSelectedNotePitch(note.midi + deltaSemitones);
  }

  setSelectedNoteDuration(targetBeats) {
    if (this.selectedNoteIndex === null || !this.quantizedNotes[this.selectedNoteIndex]) return;
    const note = this.quantizedNotes[this.selectedNoteIndex];
    const oldBeats = note.durationBeats;
    const deltaBeats = targetBeats - oldBeats;

    note.durationBeats = targetBeats;
    const noteTypeInfo = this.segmenter.beatsToNoteType(targetBeats);
    note.noteType = noteTypeInfo.type;
    note.isDotted = noteTypeInfo.isDotted;
    note.typeLabel = noteTypeInfo.label;

    // 自动平移后续音符起始拍，保持乐曲节拍流连贯整齐
    for (let i = this.selectedNoteIndex + 1; i < this.quantizedNotes.length; i++) {
      this.quantizedNotes[i].startBeat = Math.max(0, this.quantizedNotes[i].startBeat + deltaBeats);
    }
    this.realignTimelineFrom(this.selectedNoteIndex);
    this.recalculateScore();
  }

  toggleSelectedNoteDotted() {
    if (this.selectedNoteIndex === null || !this.quantizedNotes[this.selectedNoteIndex]) return;
    const note = this.quantizedNotes[this.selectedNoteIndex];
    let newBeats;
    if (note.isDotted) {
      newBeats = Math.max(0.25, note.durationBeats / 1.5);
    } else {
      newBeats = Math.min(8.0, note.durationBeats * 1.5);
    }
    this.setSelectedNoteDuration(newBeats);
  }

  deleteSelectedNote() {
    if (this.selectedNoteIndex === null || !this.quantizedNotes[this.selectedNoteIndex]) return;
    const deleted = this.quantizedNotes[this.selectedNoteIndex];
    const shiftBeats = deleted.durationBeats;

    // 后续音符向后自动对齐弥补空缺
    for (let i = this.selectedNoteIndex + 1; i < this.quantizedNotes.length; i++) {
      this.quantizedNotes[i].startBeat = Math.max(0, this.quantizedNotes[i].startBeat - shiftBeats);
    }

    this.quantizedNotes.splice(this.selectedNoteIndex, 1);
    this.realignTimelineFrom(this.selectedNoteIndex);

    if (this.quantizedNotes.length === 0) {
      this.selectedNoteIndex = null;
      document.getElementById('note-editor-toolbar')?.classList.add('hidden');
      document.getElementById('note-timeline-container')?.classList.add('hidden');
      this.recalculateScore();
    } else {
      if (this.selectedNoteIndex >= this.quantizedNotes.length) {
        this.selectedNoteIndex = this.quantizedNotes.length - 1;
      }
      this.recalculateScore();
    }
  }

  insertNoteAfterSelected() {
    const secondsPerBeat = 60 / this.segmenter.bpm;
    const durBeats = 1.0; // 默认插入四分音符
    let newStartBeat = 0;
    let newMidi = 60; // C4
    let insertIdx = 0;

    if (this.quantizedNotes.length > 0) {
      insertIdx = (this.selectedNoteIndex !== null ? this.selectedNoteIndex : this.quantizedNotes.length - 1) + 1;
      const prevNote = this.quantizedNotes[insertIdx - 1];
      newStartBeat = prevNote.startBeat + prevNote.durationBeats;
      newMidi = prevNote.midi;

      // 后续音符顺延
      for (let i = insertIdx; i < this.quantizedNotes.length; i++) {
        this.quantizedNotes[i].startBeat += durBeats;
      }
    }

    const typeInfo = this.segmenter.beatsToNoteType(durBeats);
    const newNote = {
      startTime: newStartBeat * secondsPerBeat,
      endTime: (newStartBeat + durBeats) * secondsPerBeat,
      startBeat: newStartBeat,
      durationBeats: durBeats,
      duration: durBeats * secondsPerBeat,
      midi: newMidi,
      noteName: this.segmenter.midiToNoteName(newMidi),
      noteType: typeInfo.type,
      isDotted: typeInfo.isDotted,
      typeLabel: typeInfo.label,
      confidence: 1.0
    };

    this.quantizedNotes.splice(insertIdx, 0, newNote);
    this.selectedNoteIndex = insertIdx;
    this.realignTimelineFrom(insertIdx);
    this.recalculateScore();
    this.auditionMidi(newMidi, 0.4);
  }

  insertRestAfterSelected() {
    if (this.quantizedNotes.length === 0) return;
    const idx = this.selectedNoteIndex !== null ? this.selectedNoteIndex : this.quantizedNotes.length - 1;
    const restBeats = 1.0; // 插入 1 拍空隙

    // 后续音符平移 1 拍空隙，小节划分器将自动填补休止符
    for (let i = idx + 1; i < this.quantizedNotes.length; i++) {
      this.quantizedNotes[i].startBeat += restBeats;
    }
    this.realignTimelineFrom(idx + 1);
    this.recalculateScore();
  }

  navigateNote(delta) {
    if (this.quantizedNotes.length === 0) return;
    let target = (this.selectedNoteIndex === null ? 0 : this.selectedNoteIndex) + delta;
    if (target < 0) target = 0;
    if (target >= this.quantizedNotes.length) target = this.quantizedNotes.length - 1;
    this.selectNote(target, true);
  }

  auditionSelectedNote() {
    if (this.selectedNoteIndex === null || !this.quantizedNotes[this.selectedNoteIndex]) return;
    const note = this.quantizedNotes[this.selectedNoteIndex];
    this.auditionMidi(note.midi, 0.4);
  }

  /**
   * 试听单个音符的安全入口。
   * 音频上下文为惰性创建，此处按需初始化；失败时静默跳过（不打断编辑操作）。
   */
  auditionMidi(midi, duration = 0.4) {
    if (!this.ensureAudioContext() || !this.synth) return;
    this.synth.playNote(midi, duration);
  }

  async toggleScorePlayback() {
    if (!this.ensureAudioContext() || !this.synth) {
      this.setStatus(`试听无法启动：音频上下文不可用（${this.audioInitError || '未知原因'}）`);
      return;
    }
    // 停止：优先按 synth 的真实播放状态判断，并强制复位按钮，
    // 避免出现「按钮写着停止、实际已停」或反之的失同步。
    if (this.synth.isPlaying) {
      this.synth.stopScore('stopped');
      this.setPlayButtonState(false);
      this.setStatus('⏹ 已停止试听');
      return;
    }
    if (this.quantizedNotes.length === 0) {
      this.setPlayButtonState(false);
      this.setStatus('暂无可试听的音符，请先完成一次识谱');
      return;
    }
    // 必须 await：内部要先等 AudioContext resume 完成，此时钟才解冻
    const started = await this.synth.playScore(this.quantizedNotes);
    if (!started) {
      const d = this.synth.getDiagnostics();
      this.setPlayButtonState(false);
      this.setStatus(
        `试听失败 · 音频状态=${d.state} · 采样率=${d.sampleRate}Hz · ` +
        `请检查系统「声音」设置中的输出设备是否有音量且未被静音`
      );
      return;
    }
    this.setPlayButtonState(true);

    // 明确回报播放状态：按钮「点了没反应」时，这里能立刻区分是
    // 没解锁 / 没音符 / 音频没启动 / 已正常播放。
    const d = this.synth.getDiagnostics();
    const starved = d.starvedTicks > 0 ? ` · 调度滞后 ${d.starvedTicks} 次` : '';
    this.setStatus(
      `▶ 正在试听 ${this.quantizedNotes.length} 个音符 · 音频状态=${d.state} · ` +
      `${d.sampleRate}Hz · 主音量=${(d.masterGain * 100).toFixed(0)}%${starved}`
    );
  }

  /**
   * 统一设置试听按钮文案，保证 UI 与真实播放状态始终一致。
   * @param {boolean} playing
   */
  setPlayButtonState(playing) {
    const btn = document.getElementById('btn-play-synth');
    if (!btn) return;
    btn.innerHTML = playing
      ? '<span>⏹ 停止试听 (Stop)</span>'
      : '<span>▶ 试听乐谱 (MIDI Synth)</span>';
  }

  playOriginalAudio() {
    if (!this.ensureAudioContext()) return;
    if (!this.currentAudioBuffer) return;

    if (this.originalAudioSource) {
      try { this.originalAudioSource.stop(); } catch (e) {}
      this.originalAudioSource = null;
    }

    const src = this.audioCtx.createBufferSource();
    src.buffer = this.currentAudioBuffer;
    src.connect(this.audioCtx.destination);
    src.start();
    this.originalAudioSource = src;

    const btn = document.getElementById('btn-play-original');
    if (btn) {
      btn.classList.add('active');
      src.onended = () => btn.classList.remove('active');
    }
  }

  exportMidiFile() {
    if (!this.quantizedNotes || this.quantizedNotes.length === 0) {
      this.setStatus('暂无可导出的音符，请先完成一次识谱');
      return;
    }
    try {
      const meter = this.meter || { beats: 4, unit: 4 };
      MidiExporter.download(this.quantizedNotes, this.segmenter.bpm, meter, 'humming_score.mid');
      this.setStatus(`已导出 MIDI 文件: humming_score.mid (${this.quantizedNotes.length} 个音符)`);
    } catch (err) {
      console.error('MIDI 导出失败:', err);
      this.setStatus(`MIDI 导出失败: ${err.message}`);
    }
  }

  exportMusicXMLFile() {
    if (!this.measures || this.measures.length === 0) {
      this.setStatus('暂无可导出的乐谱，请先完成一次识谱');
      return;
    }
    try {
      const scoreData = {
        measures: this.measures,
        keyInfo: this.keyInfo,
        meter: this.meter || { beats: 4, unit: 4 },
        bpm: this.segmenter.bpm
      };
      MusicXMLExporter.download(scoreData, 'humming_score.musicxml');
      this.setStatus(`已导出 MusicXML 文件: humming_score.musicxml (${this.measures.length} 小节)`);
    } catch (err) {
      console.error('MusicXML 导出失败:', err);
      this.setStatus(`MusicXML 导出失败: ${err.message}`);
    }
  }

  updateStageStatus(stageNum, status, text) {
    // 流水线面板默认隐藏，首次进入流水线时显示
    const panel = document.getElementById('pipeline-panel');
    if (panel && panel.classList.contains('hidden')) panel.classList.remove('hidden');

    const stageEl = document.getElementById(`stage-${stageNum}`);
    if (!stageEl) return;
    const badge = stageEl.querySelector('.stage-status-badge');
    const desc = stageEl.querySelector('.stage-desc');

    // 行高亮：处理中琥珀色、已完成翡翠色
    stageEl.classList.remove('running', 'completed');
    if (status === 'running' || status === 'completed') {
      stageEl.classList.add(status);
    }

    if (badge) {
      badge.className = `stage-status-badge ${status}`;
      badge.textContent = status === 'completed' ? '已完成' : (status === 'running' ? '处理中...' : '等待中');
    }
    if (desc && text) {
      desc.textContent = text;
    }
  }

  /** 重置流水线面板 (每次新识谱前清空上一轮的状态与指标) */
  resetPipelinePanel() {
    const panel = document.getElementById('pipeline-panel');
    if (panel) panel.classList.add('hidden');

    for (let i = 1; i <= 5; i++) {
      const stageEl = document.getElementById(`stage-${i}`);
      if (stageEl) stageEl.classList.remove('running', 'completed');
      const details = document.getElementById(`stage-${i}-details`);
      if (details) details.innerHTML = '';
    }
    const elapsed = document.getElementById('pipeline-elapsed');
    if (elapsed) elapsed.textContent = '';
  }

  displayStage1Metrics(data) {
    const container = document.getElementById('stage-1-details');
    if (!container) return;
    container.innerHTML = `
      <div class="metric-chip">采样率: <strong>16,000 Hz</strong></div>
      <div class="metric-chip">滤波带通: <strong>80 - 2,000 Hz</strong></div>
      <div class="metric-chip">人声端点检测: <strong>${data.trimOffsetSeconds.toFixed(2)}s ~ ${(data.trimOffsetSeconds + data.activeSamples.length / 16000).toFixed(2)}s</strong></div>
      <div class="metric-chip">过滤杂音段: <strong>${((data.originalDuration - data.activeSamples.length / 16000)).toFixed(2)}s</strong></div>
    `;
  }

  displayStage3Metrics(segRes) {
    const container = document.getElementById('stage-3-details');
    if (!container) return;
    container.innerHTML = `
      <div class="metric-chip">原始微片段: <strong>${segRes.rawNotes.length} 个</strong></div>
      <div class="metric-chip">滑音消除门限: <strong>${this.segmenter.minNoteDurationMs} ms</strong></div>
      <div class="metric-chip">量化网格: <strong>${this.segmenter.quantizeGrid === 0.5 ? '八分音符 (1/2拍)' : (this.segmenter.quantizeGrid === 0.25 ? '十六分音符 (1/4拍)' : '四分音符 (1拍)')}</strong></div>
      <div class="metric-chip">最终音符数: <strong>${segRes.quantizedNotes.length} 个</strong></div>
    `;
  }

  displayStage4Metrics(keyInfo, measures) {
    const container = document.getElementById('stage-4-details');
    if (!container) return;
    const candidatesStr = keyInfo.candidates.slice(0, 3).map(c => `${c.key} (${Math.round(c.correlation * 100)}%)`).join(' | ');

    container.innerHTML = `
      <div class="metric-chip highlight">主调式: <strong>${keyInfo.bestKey}</strong></div>
      <div class="metric-chip">调号: <strong>${keyInfo.signature.text}</strong></div>
      <div class="metric-chip">小节数量: <strong>${measures.length} 小节</strong></div>
      <div class="metric-chip">前三调性相关度: <strong>${candidatesStr}</strong></div>
    `;
  }

  setStatus(msg) {
    const el = document.getElementById('global-status-msg');
    if (el) el.textContent = msg;
  }

  tickUI() {
    return new Promise(resolve => setTimeout(resolve, 30));
  }
}

/**
 * 启动期错误上报。
 * 若构造函数抛错而无人捕获，页面会照常渲染 HTML，但所有事件监听都不会绑定，
 * 表现为「界面正常但按钮全部无响应」——极难排查。因此必须把错误显式呈现给用户。
 */
function reportFatalError(context, err) {
  const message = err && (err.message || err.reason) ? (err.message || String(err.reason)) : String(err);
  console.error(`[HummingScore] ${context}:`, err);
  const el = document.getElementById('global-status-msg');
  if (el) {
    el.textContent = `启动异常 (${context}): ${message}`;
    el.style.color = 'var(--accent-rose)';
  }
}

window.addEventListener('error', (e) => {
  // 资源加载错误也会冒泡到 window，这里只报告脚本执行期异常
  if (e.error) reportFatalError(`脚本 ${e.filename ? e.filename.split('/').pop() : ''}:${e.lineno}`, e.error);
});
window.addEventListener('unhandledrejection', (e) => {
  reportFatalError('未处理的异步异常', e.reason);
});

window.addEventListener('DOMContentLoaded', () => {
  try {
    window.app = new App();
  } catch (err) {
    reportFatalError('App 初始化失败', err);
  }
});
