/**
 * 钢琴卷帘与音高轨迹对比可视化器 (Piano Roll & F0 Pitch Contour Visualizer)
 * 渲染：基频连续曲线 (F0 Track) 与 离散量化音符块 (Quantized Notes) 的空间重叠对照
 * 支持点击音符试听、高亮选定与时间轴走带（浅色现代风格）
 */

export class PianoRollRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {Object} [options]
   */
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onNoteSelected = options.onNoteSelected || null;
    this.onNoteAudition = options.onNoteAudition || null;
    this.selectedNoteIndex = null;
    this.activePlayNoteIndex = null;

    this.minMidi = 48; // C3
    this.maxMidi = 84; // C6
    this.noteNames = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

    this.bindEvents();
  }

  bindEvents() {
    this.canvas.addEventListener('click', (e) => {
      if (!this.notes || this.notes.length === 0) return;
      const rect = this.canvas.getBoundingClientRect();
      const clickX = (e.clientX - rect.left) * (this.canvas.width / rect.width);
      const clickY = (e.clientY - rect.top) * (this.canvas.height / rect.height);

      for (let i = 0; i < this.notes.length; i++) {
        const bbox = this.noteBBoxes[i];
        if (bbox && clickX >= bbox.x && clickX <= bbox.x + bbox.w && clickY >= bbox.y && clickY <= bbox.y + bbox.h) {
          this.selectedNoteIndex = i;
          if (this.onNoteSelected) this.onNoteSelected(i, this.notes[i]);
          if (this.onNoteAudition) this.onNoteAudition(this.notes[i].midi);
          this.draw();
          return;
        }
      }
    });
  }

  /**
   * 绘制钢琴卷帘
   * @param {Array<Object>} f0Frames - [{time, freq, midi, voiced}]
   * @param {Array<Object>} notes - [{midi, startTime, duration, noteName}]
   * @param {number} totalDuration - 总音频秒数
   */
  render(f0Frames, notes, totalDuration = 5) {
    this.f0Frames = f0Frames || [];
    this.notes = notes || [];
    this.totalDuration = Math.max(1, totalDuration);
    this.noteBBoxes = [];

    if (this.notes.length > 0) {
      let minN = 127, maxN = 0;
      this.notes.forEach(n => {
        if (n.midi < minN) minN = n.midi;
        if (n.midi > maxN) maxN = n.midi;
      });
      this.minMidi = Math.max(36, minN - 3);
      this.maxMidi = Math.min(96, maxN + 3);
    }

    this.draw();
  }

  draw() {
    const w = this.canvas.width;
    const h = this.canvas.height;
    const ctx = this.ctx;

    // 清屏（浅色背景）
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    const keyboardWidth = 46;
    const rollWidth = w - keyboardWidth;
    const numSemis = this.maxMidi - this.minMidi + 1;
    const rowHeight = h / numSemis;

    // 1. 绘制背景半音网格与琴键
    for (let m = this.minMidi; m <= this.maxMidi; m++) {
      const rowIdx = this.maxMidi - m;
      const y = rowIdx * rowHeight;
      const pc = m % 12;
      const isBlackKey = [1, 3, 6, 8, 10].includes(pc);

      // 网格行 (黑键行微灰，白键行纯白)
      ctx.fillStyle = isBlackKey ? '#f8fafc' : '#ffffff';
      ctx.fillRect(keyboardWidth, y, rollWidth, rowHeight);

      // 水平分割线
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();

      // 琴键侧栏
      ctx.fillStyle = isBlackKey ? '#cbd5e1' : '#ffffff';
      ctx.fillRect(0, y, keyboardWidth, rowHeight);
      ctx.strokeStyle = '#94a3b8';
      ctx.strokeRect(0, y, keyboardWidth, rowHeight);

      // 标注 C 音
      if (pc === 0) {
        ctx.fillStyle = '#0284c7';
        ctx.font = 'bold 10px monospace';
        ctx.fillText(`C${Math.floor(m / 12) - 1}`, 5, y + rowHeight - 2);
      }
    }

    // 2. 绘制连续 F0 提取曲线 (人声原始滑音与颤音，青蓝线条)
    if (this.f0Frames && this.f0Frames.length > 0) {
      ctx.strokeStyle = '#0284c7';
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      let isDrawing = false;

      this.f0Frames.forEach(frame => {
        if (frame.voiced && frame.midi >= this.minMidi && frame.midi <= this.maxMidi) {
          const x = keyboardWidth + (frame.time / this.totalDuration) * rollWidth;
          const y = (this.maxMidi - frame.midi) * rowHeight;

          if (!isDrawing) {
            ctx.moveTo(x, y);
            isDrawing = true;
          } else {
            ctx.lineTo(x, y);
          }
        } else {
          isDrawing = false;
        }
      });
      ctx.stroke();
    }

    // 3. 绘制量化切分后的 MIDI 音符块 (圆角半透明长条，翡翠绿/紫色)
    this.noteBBoxes = [];
    this.notes.forEach((note, idx) => {
      const x = keyboardWidth + (note.startTime / this.totalDuration) * rollWidth;
      const noteW = Math.max(8, (note.duration / this.totalDuration) * rollWidth);
      const y = (this.maxMidi - note.midi) * rowHeight;

      this.noteBBoxes[idx] = { x, y, w: noteW, h: rowHeight };

      const isSelected = this.selectedNoteIndex === idx;
      const isPlaying = this.activePlayNoteIndex === idx;

      if (isPlaying) {
        ctx.fillStyle = '#f59e0b'; // 播放中琥珀黄
      } else if (isSelected) {
        ctx.fillStyle = '#e11d48'; // 选中玫瑰红
      } else {
        ctx.fillStyle = '#10b981'; // 正常翡翠绿
      }

      ctx.beginPath();
      ctx.roundRect(x, y + 1, noteW, rowHeight - 2, 3);
      ctx.fill();

      // 边框
      ctx.strokeStyle = isSelected || isPlaying ? '#0f172a' : '#059669';
      ctx.lineWidth = isSelected ? 2 : 1;
      ctx.stroke();

      // 文本标注 (音名)
      if (noteW > 18) {
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 11px sans-serif';
        ctx.fillText(note.noteName || '', x + 4, y + rowHeight - 3);
      }
    });

    // 4. 走带光标线 (Playhead)
    if (this.playheadSeconds !== undefined && this.playheadSeconds !== null) {
      const playheadX = keyboardWidth + (this.playheadSeconds / this.totalDuration) * rollWidth;
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(playheadX, 0);
      ctx.lineTo(playheadX, h);
      ctx.stroke();
    }
  }

  setSelectedNote(noteIndex) {
    this.selectedNoteIndex = noteIndex;
    this.draw();
  }

  setPlayhead(noteIndex, seconds = null) {
    this.activePlayNoteIndex = noteIndex;
    this.playheadSeconds = seconds;
    this.draw();
  }

  clearPlayhead() {
    this.activePlayNoteIndex = null;
    this.playheadSeconds = null;
    this.draw();
  }
}
