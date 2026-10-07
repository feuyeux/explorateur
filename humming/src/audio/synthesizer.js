/**
 * 乐谱合成器与播放引擎 (Score Synthesizer & Playback Engine)
 * 实现：模拟原声钢琴加性谐波音色合成、乐谱序列播放、实时光标进度跟随、硬件级即时静音停止
 */

export class Synthesizer {
  /**
   * @param {AudioContext} audioCtx
   */
  constructor(audioCtx) {
    this.ctx = audioCtx;
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = 0.7;
    this.masterGain.connect(this.ctx.destination);

    // 专属乐谱播放总线，用于支持毫秒级一键切断停止
    this.scoreGain = this.ctx.createGain();
    this.scoreGain.gain.value = 1.0;
    this.scoreGain.connect(this.masterGain);

    this.isPlaying = false;
    this.currentTimeoutIds = [];
    this.activeOscillators = [];
    this.onNotePlay = null; // (noteIndex, note) 回调
    this.onPlaybackEnd = null;

    // 滚动预调度参数（见 _scheduleTick 注释）
    this.LOOKAHEAD_MS = 200;        // 调度定时器间隔
    this.SCHEDULE_AHEAD = 1.5;      // 每次提前排期的时长窗口（秒）
    // 同时存活振荡器上限。这是**兜底安全网**，不是日常约束：
    // 取值必须大于「预调度窗口内最密集乐段所需的振荡器数」，否则排期会被
    // 上限反复挡住，音符被迫迟到播放、糊成一片。
    // 注意 activeOscillators 含**尚未发声的预调度音符**，不只正在发声的，
    // 因此实际占用 ≈ (SCHEDULE_AHEAD 1.5s + 余音 0.35s) 窗口内的音符数 × 5。
    // 按本应用最密配置估：十六分网格 @180BPM(0.083s) + 4 声部和弦
    // ≈ 1.85s / 0.083 × 4 × 5 ≈ 442，取 512 留余量；
    // 相比旧的一次性全量排期 (815 音符 = 4075 个振荡器) 仍低一个数量级。
    this.MAX_VOICES = 512;
    this.HARMONIC_COUNT = 5;        // 每音符的谐波数，需与 renderPianoTone 保持一致
    // 排期被复音上限挡住的次数，用于诊断「声音发闷/迟到」是否源于调度跟不上
    this._starvedTicks = 0;
    this._schedulerTimer = null;
    this._scheduleNotes = null;
    this._scheduleCursor = 0;
    this._scheduleBaseNoteTime = 0;
    this._scheduleStartOffset = 0;
    this._scheduleBaseCtxTime = 0;
  }

  setVolume(vol) {
    this.masterGain.gain.setValueAtTime(Math.max(0, Math.min(1, vol)), this.ctx.currentTime);
  }

  /**
   * 采集音频链路诊断信息，用于在界面上明确告知用户「为什么没有声音」。
   * 播放按钮静默失败是最难排查的问题，这里把关键状态暴露出来。
   */
  getDiagnostics() {
    return {
      hasContext: !!this.ctx,
      state: this.ctx ? this.ctx.state : 'none',
      sampleRate: this.ctx ? this.ctx.sampleRate : 0,
      baseLatency: this.ctx && this.ctx.baseLatency != null ? this.ctx.baseLatency : null,
      masterGain: this.masterGain ? this.masterGain.gain.value : null,
      scoreGain: this.scoreGain ? this.scoreGain.gain.value : null,
      activeOscillators: this.activeOscillators.length,
      maxVoices: this.MAX_VOICES,
      starvedTicks: this._starvedTicks,
      isPlaying: this.isPlaying
    };
  }

  /**
   * 确保 AudioContext 处于 running 状态。
   *
   * 关键点：浏览器的自动播放策略会让未经用户手势创建的 AudioContext 停留在 suspended，
   * 此时 ctx.currentTime 被冻结。在冻结的时钟上调度振荡器，resume() 生效后
   * 这些已排期的事件可能不再触发，表现为「点了试听完全没有声音」。
   * 因此必须**等待 resume() 真正完成**后再调度音符。
   *
   * @returns {Promise<boolean>} 上下文是否可用
   */
  async ensureRunning() {
    if (!this.ctx) return false;
    if (this.ctx.state === 'running') return true;
    try {
      await this.ctx.resume();
    } catch (e) {
      return false;
    }
    return this.ctx.state !== 'suspended';
  }

  /**
   * 试听单个音符 (如点击乐谱或钢琴键)
   * @param {number} midi - MIDI 音高编号 (如 60 为中央 C)
   * @param {number} [duration=0.5] - 发声时长 (秒)
   */
  async playNote(midi, duration = 0.5) {
    if (!(await this.ensureRunning())) return;
    const freq = 440 * Math.pow(2, (midi - 69) / 12);
    this.renderPianoTone(freq, this.ctx.currentTime + 0.01, duration, this.masterGain, false);
  }

  /**
   * 滚动预调度：把「还没轮到」的音符留给后续 tick，只调度时间窗内的音符。
   *
   * 为什么必须这样做：一次性的「全量排期」在长乐谱上会瞬间创建
   * 音符数 × 11 个 Web Audio 节点（每音符 1 个 noteGain + 5 个振荡器 + 5 个谐波增益）。
   * 例如 815 个音符 = 4075 个振荡器 / 8965 个节点，同步创建既会卡死主线程，
   * 又会超出音频渲染线程的处理能力，表现为**完全静音**且不报错。
   *
   * 采用经典的 lookahead 模式：定时器只提前 SCHEDULE_AHEAD 秒排期，
   * 并限制同时存活的振荡器数量 MAX_VOICES，从而对任意长度乐谱都能稳定播放。
   */
  _scheduleTick() {
    if (!this.isPlaying) return;

    this._pruneFinishedOscillators();

    const horizon = this.ctx.currentTime + this.SCHEDULE_AHEAD;
    const notes = this._scheduleNotes;
    if (!notes) return;

    while (this._scheduleCursor < notes.length) {
      const note = notes[this._scheduleCursor];
      const delay = note.startTime - this._scheduleBaseNoteTime - this._scheduleStartOffset;
      if (delay < 0) {
        this._scheduleCursor++;
        continue;
      }

      const scheduleTime = this._scheduleBaseCtxTime + delay;
      // 先判时域窗口：还没到预调度时刻的音符交给下次 tick。
      if (scheduleTime > horizon) break;

      // 再判复音上限：每个音符会创建 HARMONIC_COUNT 个振荡器，判定时必须预留出来。
      // 保留 cursor 不前进，等振荡器被回收后下一轮再排——音符仍会发声，只是稍晚，
      // 不会丢失。若把这条判定放在时域判定之前，撞上限时连「此刻该响」的音符都不排。
      if (this.activeOscillators.length + this.HARMONIC_COUNT > this.MAX_VOICES) {
        this._starvedTicks++;
        break;
      }

      const index = this._scheduleCursor;
      const freq = 440 * Math.pow(2, (note.midi - 69) / 12);
      this.renderPianoTone(freq, scheduleTime, Math.max(0.1, note.duration), this.scoreGain, true);

      const uiDelay = Math.max(0, (scheduleTime - this.ctx.currentTime) * 1000);
      const tid = setTimeout(() => {
        if (this.isPlaying && this.onNotePlay) this.onNotePlay(index, note);
      }, uiDelay);
      this.currentTimeoutIds.push(tid);

      this._scheduleCursor++;
    }

    // 全部排期完毕 → 关闭定时器，等播放自然结束
    if (this._scheduleCursor >= notes.length && this._schedulerTimer) {
      clearInterval(this._schedulerTimer);
      this._schedulerTimer = null;
    }
  }

  /** 回收已经停止的振荡器，避免 activeOscillators 无限增长导致误判「已达上限」 */
  _pruneFinishedOscillators() {
    const now = this.ctx.currentTime;
    this.activeOscillators = this.activeOscillators.filter(osc => {
      if (osc._stopAt != null && now > osc._stopAt + 0.2) {
        try { osc.disconnect(); } catch { /* 已断开 */ }
        return false;
      }
      return true;
    });
  }

  /**
   * 播放整段识别出的结构化乐谱
   * @param {Array<Object>} notes - [{midi, startTime, duration}]
   * @param {number} [startOffset=0]
   * @returns {Promise<boolean>} 是否成功开始播放
   */
  async playScore(notes, startOffset = 0) {
    if (!notes || notes.length === 0) return false;
    this.stopScore('restart');

    // 必须先等 resume 完成：否则会在被冻结的时钟上排期，导致完全无声
    if (!(await this.ensureRunning())) {
      this.isPlaying = false;
      return false;
    }

    this.isPlaying = true;
    this._starvedTicks = 0;

    // 按开始时间排序：滚动调度是游标顺序推进的，若入参乱序会导致音符先后错乱，
    // 且总时长会按「数组最后一个」算错、播放中途被截断。
    const ordered = [...notes].sort((a, b) => (a.startTime || 0) - (b.startTime || 0));

    // 确保乐谱输出总线开启
    if (!this.scoreGain) {
      this.scoreGain = this.ctx.createGain();
      this.scoreGain.connect(this.masterGain);
    }
    this.scoreGain.gain.cancelScheduledValues(this.ctx.currentTime);
    this.scoreGain.gain.setValueAtTime(1.0, this.ctx.currentTime);

    this._scheduleNotes = ordered;
    this._scheduleCursor = 0;
    this._scheduleBaseNoteTime = ordered[0].startTime;
    this._scheduleStartOffset = startOffset;
    this._scheduleBaseCtxTime = this.ctx.currentTime + 0.05;

    // 先同步排期一批（保证短乐谱立即发声），其余交给定时器滚动预排
    this._scheduleTick();
    if (this.isPlaying && this._scheduleCursor < ordered.length) {
      this._schedulerTimer = setInterval(() => this._scheduleTick(), this.LOOKAHEAD_MS);
    }

    // 调度播放正常结束：总时长取最晚结束的音符，不依赖数组顺序
    let endTime = 0;
    for (const n of ordered) {
      endTime = Math.max(endTime, (n.startTime || 0) + (n.duration || 0));
    }
    const totalDuration = (endTime - this._scheduleBaseNoteTime) - startOffset;
    const endTid = setTimeout(() => {
      this.stopScore('ended');
    }, (Math.max(0, totalDuration) + 0.2) * 1000);
    this.currentTimeoutIds.push(endTid);

    return true;
  }

  /**
   * 停止乐谱播放 (硬件级全线即时静音与节点释放)
   * @param {string} [reason='stopped'] - 'ended' 自然播完 / 'stopped' 主动停止 / 'restart' 重新开始
   */
  stopScore(reason = 'stopped') {
    this.isPlaying = false;

    // 0. 停止滚动预调度定时器
    if (this._schedulerTimer) {
      clearInterval(this._schedulerTimer);
      this._schedulerTimer = null;
    }
    this._scheduleNotes = null;
    this._scheduleCursor = 0;

    // 1. 清除所有未执行的走带与结束定时器
    for (const tid of this.currentTimeoutIds) {
      clearTimeout(tid);
    }
    this.currentTimeoutIds = [];

    // 2. 硬件层立即切断 scoreGain 输出
    if (this.scoreGain) {
      try {
        this.scoreGain.gain.cancelScheduledValues(this.ctx.currentTime);
        this.scoreGain.gain.setValueAtTime(0, this.ctx.currentTime);
        this.scoreGain.disconnect();
      } catch (e) {}
    }

    // 3. 强制终止并注销所有预定发声的振荡器
    for (const osc of this.activeOscillators) {
      try {
        osc.stop();
        osc.disconnect();
      } catch (e) {}
    }
    this.activeOscillators = [];

    // 4. 重建就绪的 scoreGain 节点备用
    try {
      this.scoreGain = this.ctx.createGain();
      this.scoreGain.gain.value = 1.0;
      this.scoreGain.connect(this.masterGain);
    } catch (e) {}

    // 5. 触发 UI 走带复位
    if (this.onPlaybackEnd) {
      this.onPlaybackEnd(reason);
    }
  }

  /**
   * 拟真钢琴加性谐波音色生成算法 (Additive Harmonics + Exponential Decay)
   * @param {number} freq - 基频
   * @param {number} startTime - 开始时间戳
   * @param {number} duration - 时值
   * @param {GainNode} targetGain - 输出目标总线
   * @param {boolean} isScorePlayback - 是否归属于当前乐谱播放流
   */
  renderPianoTone(freq, startTime, duration, targetGain = this.masterGain, isScorePlayback = false) {
    const harmonics = [
      { ratio: 1.0, gain: 1.0, decay: 1.0 },
      { ratio: 2.0, gain: 0.45, decay: 1.3 },
      { ratio: 3.0, gain: 0.22, decay: 1.7 },
      { ratio: 4.0, gain: 0.12, decay: 2.2 },
      { ratio: 5.0, gain: 0.05, decay: 2.8 }
    ];

    const noteGain = this.ctx.createGain();
    noteGain.gain.setValueAtTime(0.001, startTime);
    noteGain.gain.linearRampToValueAtTime(0.35, startTime + 0.006);
    const releaseTime = Math.min(duration * 1.2, duration + 0.3);
    noteGain.gain.exponentialRampToValueAtTime(0.0001, startTime + releaseTime);
    noteGain.connect(targetGain);

    harmonics.forEach(h => {
      const osc = this.ctx.createOscillator();
      const hGain = this.ctx.createGain();

      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq * h.ratio, startTime);

      hGain.gain.setValueAtTime(h.gain, startTime);
      hGain.gain.exponentialRampToValueAtTime(0.001, startTime + Math.min(duration / h.decay, releaseTime));

      osc.connect(hGain);
      hGain.connect(noteGain);

      osc.start(startTime);
      osc.stop(startTime + releaseTime + 0.05);
      osc._stopAt = startTime + releaseTime + 0.05;

      if (isScorePlayback) {
        this.activeOscillators.push(osc);
      }
    });
  }
}
