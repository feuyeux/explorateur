/**
 * 节拍器模块 (Metronome Engine)
 * 基于 Web Audio API 高精度定时器，提供稳定的节奏声与录音伴奏引导
 */

export class Metronome {
  /**
   * @param {AudioContext} audioCtx
   * @param {Object} [options]
   */
  constructor(audioCtx, options = {}) {
    this.ctx = audioCtx;
    this.bpm = options.bpm || 100;
    this.beatsPerMeasure = options.beatsPerMeasure || 4;
    this.isPlaying = false;
    this.currentBeat = 0;
    this.nextNoteTime = 0.0;
    this.timerID = null;
    this.lookahead = 25.0; // 调度轮询周期 (ms)
    this.scheduleAheadTime = 0.1; // 提前预载时长 (s)
    this.onBeat = options.onBeat || null; // 节拍回调函数
  }

  setBpm(newBpm) {
    this.bpm = Math.max(30, Math.min(260, newBpm));
  }

  setBeatsPerMeasure(beats) {
    this.beatsPerMeasure = beats;
  }

  start(countIn = false, onCountInFinished = null) {
    if (this.isPlaying) return;

    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }

    this.isPlaying = true;
    this.currentBeat = 0;
    this.nextNoteTime = this.ctx.currentTime + 0.05;

    if (countIn) {
      let count = 0;
      const countInBeats = this.beatsPerMeasure;
      const originalOnBeat = this.onBeat;

      this.onBeat = (beat, time) => {
        count++;
        if (originalOnBeat) originalOnBeat(beat, time, true, count);
        if (count >= countInBeats) {
          this.onBeat = originalOnBeat;
          if (onCountInFinished) onCountInFinished();
        }
      };
    }

    this.scheduler();
  }

  stop() {
    this.isPlaying = false;
    if (this.timerID) {
      clearTimeout(this.timerID);
      this.timerID = null;
    }
  }

  scheduler() {
    if (!this.isPlaying) return;

    while (this.nextNoteTime < this.ctx.currentTime + this.scheduleAheadTime) {
      this.scheduleNote(this.currentBeat, this.nextNoteTime);
      this.nextNote();
    }

    this.timerID = setTimeout(() => this.scheduler(), this.lookahead);
  }

  nextNote() {
    const secondsPerBeat = 60.0 / this.bpm;
    this.nextNoteTime += secondsPerBeat;
    this.currentBeat = (this.currentBeat + 1) % this.beatsPerMeasure;
  }

  scheduleNote(beatNumber, time) {
    const isFirstBeat = beatNumber === 0;

    // 创建高品质双木鱼/响棒点击音色
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'sine';
    // 第一拍高音 (1200Hz)，后续拍重音 (800Hz)
    osc.frequency.setValueAtTime(isFirstBeat ? 1200 : 800, time);
    osc.frequency.exponentialRampToValueAtTime(isFirstBeat ? 300 : 200, time + 0.04);

    gain.gain.setValueAtTime(isFirstBeat ? 0.8 : 0.45, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.045);

    osc.connect(gain);
    gain.connect(this.ctx.destination);

    osc.start(time);
    osc.stop(time + 0.05);

    if (this.onBeat) {
      // 触发 UI 节拍灯闪烁
      const delay = Math.max(0, (time - this.ctx.currentTime) * 1000);
      setTimeout(() => {
        if (this.isPlaying && this.onBeat) {
          this.onBeat(beatNumber, time, false);
        }
      }, delay);
    }
  }
}
