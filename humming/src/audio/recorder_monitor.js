/**
 * 实时录音与声音检测监控器 (Live Audio Sound Detection Monitor)
 * 在录音过程中提供 60FPS 实时动态画面（适配浅色现代主题）：
 * 1. 实时波形示波器 (Live Oscilloscope / Waveform)
 * 2. 实时频域能量分布 (Frequency Spectrum)
 * 3. 实时音高探测器 (Live Pitch Tuner: 识别当前正在哼唱的音名如 C4, G4 及频率 Hz)
 * 4. 实时音量分贝与 VU 电平表 (VU Level Meter: -60dB ~ 0dB)
 * 5. 实时人声活动指示 (Voice Activity Detection: 识别静音 vs 人声发音)
 */

export class AudioRecorderMonitor {
  /**
   * @param {AudioContext} audioCtx
   * @param {HTMLCanvasElement} canvas
   * @param {Object} uiElements
   */
  constructor(audioCtx, canvas, uiElements = {}) {
    this.audioCtx = audioCtx;
    this.canvas = canvas;
    this.ctx = canvas ? canvas.getContext('2d') : null;
    this.ui = uiElements;

    this.analyser = null;
    this.sourceNode = null;
    this.animFrameId = null;
    this.isMonitoring = false;

    this.fftSize = 2048;
    this.timeDomainBuffer = new Float32Array(this.fftSize);
    this.freqDomainBuffer = new Uint8Array(this.fftSize / 2);

    this.noteStrings = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  }

  start(mediaStream) {
    if (!this.audioCtx || !this.canvas) return;
    this.stop();

    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }

    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = this.fftSize;
    this.analyser.smoothingTimeConstant = 0.8;

    this.sourceNode = this.audioCtx.createMediaStreamSource(mediaStream);
    this.sourceNode.connect(this.analyser);

    this.isMonitoring = true;
    this.loop();
  }

  stop() {
    this.isMonitoring = false;
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
    if (this.sourceNode) {
      try { this.sourceNode.disconnect(); } catch (e) {}
      this.sourceNode = null;
    }
    this.analyser = null;

    this.clearUI();
  }

  loop() {
    if (!this.isMonitoring || !this.analyser) return;

    this.analyser.getFloatTimeDomainData(this.timeDomainBuffer);
    this.analyser.getByteFrequencyData(this.freqDomainBuffer);

    let sumSq = 0;
    for (let i = 0; i < this.timeDomainBuffer.length; i++) {
      const v = this.timeDomainBuffer[i];
      sumSq += v * v;
    }
    const rms = Math.sqrt(sumSq / this.timeDomainBuffer.length);
    const db = 20 * Math.log10(Math.max(1e-4, rms));
    const level = Math.max(0, Math.min(1, (db + 50) / 50));

    const livePitch = this.detectLivePitch(this.timeDomainBuffer, this.audioCtx.sampleRate);

    this.updateUIMeters(rms, db, level, livePitch);
    this.drawVisualizer(this.timeDomainBuffer, this.freqDomainBuffer, level, livePitch);

    this.animFrameId = requestAnimationFrame(() => this.loop());
  }

  detectLivePitch(buf, sampleRate) {
    let rms = 0;
    for (let i = 0; i < buf.length; i++) rms += buf[i] * buf[i];
    rms = Math.sqrt(rms / buf.length);
    if (rms < 0.012) return null;

    const minPeriod = Math.floor(sampleRate / 800);
    const maxPeriod = Math.ceil(sampleRate / 80);

    let bestR = 0;
    let bestPeriod = -1;

    for (let tau = minPeriod; tau < maxPeriod; tau++) {
      let r = 0;
      for (let i = 0; i < 512; i++) {
        r += buf[i] * buf[i + tau];
      }
      if (r > bestR) {
        bestR = r;
        bestPeriod = tau;
      }
    }

    if (bestPeriod > 0 && bestR > 0.42) {
      const freq = sampleRate / bestPeriod;
      const midi = 69 + 12 * Math.log2(freq / 440);
      const roundedMidi = Math.round(midi);
      const noteName = `${this.noteStrings[roundedMidi % 12]}${Math.floor(roundedMidi / 12) - 1}`;
      const detuneCents = Math.round((midi - roundedMidi) * 100);

      return {
        freq: Math.round(freq * 10) / 10,
        midi: roundedMidi,
        noteName: noteName,
        cents: detuneCents
      };
    }

    return null;
  }

  updateUIMeters(rms, db, level, livePitch) {
    if (this.ui.vuBarEl) {
      this.ui.vuBarEl.style.width = `${Math.round(level * 100)}%`;
      if (level > 0.8) {
        this.ui.vuBarEl.style.backgroundColor = '#ef4444';
      } else if (level > 0.5) {
        this.ui.vuBarEl.style.backgroundColor = '#f59e0b';
      } else {
        this.ui.vuBarEl.style.backgroundColor = '#10b981';
      }
    }

    if (this.ui.vuDbEl) {
      this.ui.vuDbEl.textContent = `${Math.round(db)} dB`;
    }

    if (this.ui.vadBadgeEl) {
      if (rms > 0.015) {
        this.ui.vadBadgeEl.className = 'vad-badge active';
        this.ui.vadBadgeEl.innerHTML = '<span class="vad-dot"></span><span>🎙️ 正在捕获人声信号</span>';
      } else {
        this.ui.vadBadgeEl.className = 'vad-badge silence';
        this.ui.vadBadgeEl.innerHTML = '<span class="vad-dot"></span><span>⏸️ 环境静音 / 待哼唱</span>';
      }
    }

    if (this.ui.tunerNoteEl) {
      if (livePitch) {
        const centsStr = livePitch.cents > 0 ? `+${livePitch.cents}` : `${livePitch.cents}`;
        this.ui.tunerNoteEl.innerHTML = `<strong>${livePitch.noteName}</strong> <span style="font-size:13px; color:#0284c7;">(${livePitch.freq} Hz, ${centsStr}音分)</span>`;
      } else {
        this.ui.tunerNoteEl.innerHTML = `<span style="color:#94a3b8;">-- (请哼唱发出声音)</span>`;
      }
    }
  }

  drawVisualizer(timeBuf, freqBuf, level, livePitch) {
    if (!this.ctx || !this.canvas) return;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const ctx = this.ctx;

    // 清屏（浅色画布）
    ctx.fillStyle = 'rgba(248, 250, 252, 0.55)';
    ctx.fillRect(0, 0, w, h);

    // 1. 背景频谱微光柱 (Spectrum Bars)
    const numBars = 48;
    const barWidth = w / numBars;
    for (let i = 0; i < numBars; i++) {
      const idx = Math.floor(i * (freqBuf.length / numBars) * 0.5);
      const val = freqBuf[idx] / 255.0;
      const barHeight = val * (h * 0.7);

      const grad = ctx.createLinearGradient(0, h, 0, h - barHeight);
      grad.addColorStop(0, 'rgba(2, 132, 199, 0.08)');
      grad.addColorStop(1, 'rgba(99, 102, 241, 0.25)');

      ctx.fillStyle = grad;
      ctx.fillRect(i * barWidth, h - barHeight, barWidth - 2, barHeight);
    }

    // 2. 实时主波形示波器 (Oscilloscope Line)
    ctx.lineWidth = livePitch ? 2.5 : 1.8;
    ctx.strokeStyle = livePitch ? '#059669' : '#0284c7'; // 发声时翡翠绿，平时深天蓝
    ctx.shadowBlur = livePitch ? 6 : 2;
    ctx.shadowColor = livePitch ? '#10b981' : '#0284c7';

    ctx.beginPath();
    const sliceWidth = w / timeBuf.length;
    let x = 0;

    for (let i = 0; i < timeBuf.length; i++) {
      const v = timeBuf[i];
      const y = (h / 2) + v * (h * 0.45);

      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      x += sliceWidth;
    }
    ctx.stroke();
    ctx.shadowBlur = 0;

    // 3. 中心基线
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.stroke();
  }

  clearUI() {
    if (this.ctx && this.canvas) {
      this.ctx.fillStyle = '#f8fafc';
      this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
    if (this.ui.vuBarEl) this.ui.vuBarEl.style.width = '0%';
    if (this.ui.vuDbEl) this.ui.vuDbEl.textContent = '-∞ dB';
    if (this.ui.vadBadgeEl) {
      this.ui.vadBadgeEl.className = 'vad-badge';
      this.ui.vadBadgeEl.innerHTML = '<span class="vad-dot"></span><span>未在录音</span>';
    }
    if (this.ui.tunerNoteEl) {
      this.ui.tunerNoteEl.innerHTML = '<span style="color:#94a3b8;">-- (未开始录音)</span>';
    }
  }
}
