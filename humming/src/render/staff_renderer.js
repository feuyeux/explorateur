/**
 * 阶段五：五线谱矢量渲染器 (Vector SVG Staff Notation Renderer)
 * 纯矢量 SVG 呈现：高音谱号、调号、拍号、和弦标记、歌词对位、小节线、音符、符头/符干/符尾、临时升降号、加线、休止符
 * 支持音符点击交互、试听、高亮跟随、音高/时值手动微调修改
 */

export class StaffRenderer {
  /**
   * @param {HTMLElement} container
   * @param {Object} [options]
   */
  constructor(container, options = {}) {
    this.container = container;
    this.onNoteSelected = options.onNoteSelected || null;
    this.onNoteAudition = options.onNoteAudition || null;
    this.onRestSelected = options.onRestSelected || null;
    this.selectedNoteIndex = null;
    this.activePlayNoteIndex = null;
    // 休止符选中标识：以 startBeat 作为 key（休止符互不重叠，键唯一）
    this.selectedRestKey = null;

    // 五线谱几何参数
    this.lineSpacing = 10;
    this.noteWidth = 40;
  }

  /**
   * 渲染完整五线谱
   * @param {Object} scoreData - { measures, keyInfo, meter: { beats: 4, unit: 4 }, bpm, chords }
   */
  render(scoreData) {
    if (!this.container) return;
    this.scoreData = scoreData;
    this.container.innerHTML = '';

    const measures = scoreData.measures || [];
    if (measures.length === 0) {
      this.container.innerHTML = '<div class="empty-score-tip">暂无乐谱数据，请先哼唱录音或加载预置示例</div>';
      return;
    }

    // 计算总宽度
    const headerWidth = 110;
    let totalScoreWidth = headerWidth;
    measures.forEach(m => {
      totalScoreWidth += Math.max(140, m.items.length * this.noteWidth + 30);
    });

    const svgWidth = Math.max(800, totalScoreWidth + 40);
    const hasLyrics = measures.some(m => m.items.some(it => it.lyric));
    const svgHeight = hasLyrics ? 250 : 220;
    const staffTop = 75;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${svgWidth} ${svgHeight}`);
    // 显式声明自然尺寸：配合 CSS (.staff-svg width:auto) 让长谱保持原始大小，
    // 由 staff-box 的 overflow-x 横向滚动查看。
    // 此前只设 viewBox 而被 CSS width:100% 压进容器宽度，整份谱被等比缩成
    // 一条几十像素高的细线，视觉上等于「五线谱没有展示出来」。
    svg.setAttribute('width', svgWidth);
    svg.setAttribute('height', svgHeight);
    svg.setAttribute('class', 'staff-svg');

    // 1. 绘制五条主谱线
    for (let l = 0; l < 5; l++) {
      const lineY = staffTop + l * this.lineSpacing;
      const line = this.createSvgElement('line', {
        x1: 20,
        y1: lineY,
        x2: svgWidth - 20,
        y2: lineY,
        class: 'staff-line'
      });
      svg.appendChild(line);
    }

    // 2. 绘制高音谱号 (Treble Clef G)
    svg.appendChild(this.drawTrebleClef(30, staffTop + 30));

    // 3. 绘制拍号 (Time Signature)
    const beats = (scoreData.meter && scoreData.meter.beats) || 4;
    const unit = (scoreData.meter && scoreData.meter.unit) || 4;
    svg.appendChild(this.drawTimeSignature(80, staffTop, beats, unit));

    // 4. 遍历渲染小节与音符
    let currentX = headerWidth;
    let globalNoteCounter = 0;

    measures.forEach((measure, mIdx) => {
      const measureWidth = Math.max(140, measure.items.length * this.noteWidth + 30);
      const measureEndX = currentX + measureWidth;

      // 绘制小节序号
      const numText = this.createSvgElement('text', {
        x: currentX + 6,
        y: staffTop - 12,
        class: 'measure-number'
      });
      numText.textContent = `${measure.measureNumber}`;
      svg.appendChild(numText);

      // 绘制和弦标记 (Chord Symbol - 支持 LLM / 乐理自动生成)
      const chord = measure.chord || (scoreData.chords && scoreData.chords[mIdx]?.chord);
      if (chord) {
        const chordText = this.createSvgElement('text', {
          x: currentX + 22,
          y: staffTop - 26,
          class: 'measure-chord'
        });
        chordText.textContent = chord;
        svg.appendChild(chordText);
      }

      // 绘制小节内部元素
      const itemSpacing = (measureWidth - 30) / Math.max(1, measure.items.length);

      measure.items.forEach((item, itemIdx) => {
        const itemX = currentX + 15 + itemIdx * itemSpacing;

        if (item.isRest) {
          svg.appendChild(this.drawRest(itemX, staffTop, item));
        } else {
          const noteIndex = item.originalIndex !== undefined ? item.originalIndex : globalNoteCounter++;
          const noteG = this.drawNote(itemX, staffTop, item, noteIndex);
          svg.appendChild(noteG);
        }
      });

      // 绘制小节线 (Barline)
      const isLastMeasure = mIdx === measures.length - 1;
      if (isLastMeasure) {
        const bar1 = this.createSvgElement('line', {
          x1: measureEndX - 5,
          y1: staffTop,
          x2: measureEndX - 5,
          y2: staffTop + 4 * this.lineSpacing,
          class: 'bar-line thin'
        });
        const bar2 = this.createSvgElement('line', {
          x1: measureEndX,
          y1: staffTop,
          x2: measureEndX,
          y2: staffTop + 4 * this.lineSpacing,
          class: 'bar-line thick'
        });
        svg.appendChild(bar1);
        svg.appendChild(bar2);
      } else {
        const bar = this.createSvgElement('line', {
          x1: measureEndX,
          y1: staffTop,
          x2: measureEndX,
          y2: staffTop + 4 * this.lineSpacing,
          class: 'bar-line'
        });
        svg.appendChild(bar);
      }

      currentX = measureEndX;
    });

    this.container.appendChild(svg);
  }

  /**
   * 绘制音符 (符头、符干、符尾、升降号、加线、歌词)
   */
  drawNote(x, staffTop, note, noteIndex) {
    const g = this.createSvgElement('g', {
      class: `staff-note ${this.selectedNoteIndex === noteIndex ? 'selected' : ''} ${this.activePlayNoteIndex === noteIndex ? 'playing' : ''}`,
      'data-note-index': noteIndex
    });

    const diatonicStep = this.midiToDiatonicStep(note.midi);
    const stepDiffFromF5 = 10 - diatonicStep;
    const noteY = staffTop + stepDiffFromF5 * (this.lineSpacing / 2);

    // 1. 临时升降号
    const isSharp = this.isMidiAccidentalSharp(note.midi);
    if (isSharp) {
      const sharpText = this.createSvgElement('text', {
        x: x - 13,
        y: noteY + 5,
        class: 'accidental-sharp'
      });
      sharpText.textContent = '♯';
      g.appendChild(sharpText);
    }

    // 2. 加线
    if (stepDiffFromF5 >= 10) {
      for (let s = 10; s <= stepDiffFromF5; s += 2) {
        const lineY = staffTop + s * (this.lineSpacing / 2);
        const ledgerLine = this.createSvgElement('line', {
          x1: x - 9,
          y1: lineY,
          x2: x + 15,
          y2: lineY,
          class: 'ledger-line'
        });
        g.appendChild(ledgerLine);
      }
    } else if (stepDiffFromF5 <= -2) {
      for (let s = -2; s >= stepDiffFromF5; s -= 2) {
        const lineY = staffTop + s * (this.lineSpacing / 2);
        const ledgerLine = this.createSvgElement('line', {
          x1: x - 9,
          y1: lineY,
          x2: x + 15,
          y2: lineY,
          class: 'ledger-line'
        });
        g.appendChild(ledgerLine);
      }
    }

    // 3. 符头
    const isHollow = note.noteType === 'whole' || note.noteType === 'half';
    const notehead = this.createSvgElement('ellipse', {
      cx: x + 3,
      cy: noteY,
      rx: 5.8,
      ry: 4.2,
      transform: `rotate(-20, ${x + 3}, ${noteY})`,
      class: `notehead ${isHollow ? 'hollow' : 'filled'}`
    });
    g.appendChild(notehead);

    // 4. 符干
    if (note.noteType !== 'whole') {
      const stemUp = stepDiffFromF5 > 4;
      const stemX = stemUp ? x + 8.2 : x - 2.2;
      const stemLength = 32;
      const stemEndY = stemUp ? noteY - stemLength : noteY + stemLength;

      const stem = this.createSvgElement('line', {
        x1: stemX,
        y1: noteY,
        x2: stemX,
        y2: stemEndY,
        class: 'note-stem'
      });
      g.appendChild(stem);

      // 5. 符尾
      if (note.noteType === 'eighth' || note.noteType === '16th') {
        const flag = this.createSvgElement('path', {
          d: stemUp
            ? `M ${stemX} ${stemEndY} Q ${stemX + 10} ${stemEndY + 12} ${stemX + 6} ${stemEndY + 22}`
            : `M ${stemX} ${stemEndY} Q ${stemX + 10} ${stemEndY - 12} ${stemX + 6} ${stemEndY - 22}`,
          class: 'note-flag'
        });
        g.appendChild(flag);

        if (note.noteType === '16th') {
          const flag2 = this.createSvgElement('path', {
            d: stemUp
              ? `M ${stemX} ${stemEndY + 6} Q ${stemX + 10} ${stemEndY + 18} ${stemX + 6} ${stemEndY + 28}`
              : `M ${stemX} ${stemEndY - 6} Q ${stemX + 10} ${stemEndY - 18} ${stemX + 6} ${stemEndY - 28}`,
            class: 'note-flag'
          });
          g.appendChild(flag2);
        }
      }
    }

    // 6. 附点
    if (note.isDotted) {
      const dot = this.createSvgElement('circle', {
        cx: x + 13,
        cy: (stepDiffFromF5 % 2 === 0) ? noteY - 3 : noteY,
        r: 2,
        class: 'note-dot'
      });
      g.appendChild(dot);
    }

    // 7. 音名标签 (如 C4, E4)
    const noteText = this.createSvgElement('text', {
      x: x + 3,
      y: staffTop + 5 * this.lineSpacing + 28,
      class: 'note-label'
    });
    noteText.textContent = note.noteName || '';
    g.appendChild(noteText);

    // 8. 歌词对位 (AI Generated Lyrics)
    if (note.lyric) {
      const lyricText = this.createSvgElement('text', {
        x: x + 3,
        y: staffTop + 5 * this.lineSpacing + 48,
        class: 'note-lyric'
      });
      lyricText.textContent = note.lyric;
      g.appendChild(lyricText);
    }

    // 交互点击
    g.addEventListener('click', (e) => {
      e.stopPropagation();
      this.selectedNoteIndex = noteIndex;
      if (this.onNoteSelected) this.onNoteSelected(noteIndex, note);
      if (this.onNoteAudition) this.onNoteAudition(note.midi);
      this.render(this.scoreData);
    });

    return g;
  }

  drawRest(x, staffTop, restItem) {
    const restKey = `${restItem.startBeat}`;
    const g = this.createSvgElement('g', {
      class: `staff-rest ${this.selectedRestKey === restKey ? 'selected' : ''}`,
      'data-rest-key': restKey
    });

    // 休止符可点击选中（随后可删除），与音符交互保持一致
    g.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.onRestSelected) this.onRestSelected(restItem);
    });

    if (restItem.durationBeats >= 3.5) {
      const rect = this.createSvgElement('rect', {
        x: x,
        y: staffTop + this.lineSpacing,
        width: 12,
        height: 5,
        class: 'rest-rect'
      });
      g.appendChild(rect);
    } else if (restItem.durationBeats >= 1.75) {
      const rect = this.createSvgElement('rect', {
        x: x,
        y: staffTop + 2 * this.lineSpacing - 5,
        width: 12,
        height: 5,
        class: 'rest-rect'
      });
      g.appendChild(rect);
    } else {
      const text = this.createSvgElement('text', {
        x: x,
        y: staffTop + 2.5 * this.lineSpacing + 5,
        class: 'rest-symbol'
      });
      text.textContent = '𝄽';
      g.appendChild(text);
    }

    return g;
  }

  drawTrebleClef(x, y) {
    const text = this.createSvgElement('text', {
      x: x,
      y: y + 10,
      class: 'clef-symbol'
    });
    text.textContent = '𝄞';
    return text;
  }

  drawTimeSignature(x, staffTop, beats, unit) {
    const g = this.createSvgElement('g', { class: 'time-signature' });
    const topText = this.createSvgElement('text', {
      x: x,
      y: staffTop + 1.8 * this.lineSpacing,
      class: 'time-sig-num'
    });
    topText.textContent = `${beats}`;

    const bottomText = this.createSvgElement('text', {
      x: x,
      y: staffTop + 3.8 * this.lineSpacing,
      class: 'time-sig-num'
    });
    bottomText.textContent = `${unit}`;

    g.appendChild(topText);
    g.appendChild(bottomText);
    return g;
  }

  midiToDiatonicStep(midi) {
    const semitonesFromC4 = midi - 60;
    const octave = Math.floor(semitonesFromC4 / 12);
    const pitchClass = (semitonesFromC4 % 12 + 12) % 12;
    const naturalSteps = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6];
    return octave * 7 + naturalSteps[pitchClass];
  }

  isMidiAccidentalSharp(midi) {
    const pc = (midi % 12 + 12) % 12;
    return [1, 3, 6, 8, 10].includes(pc);
  }

  setSelectedNote(noteIndex) {
    this.selectedNoteIndex = noteIndex;
    if (this.container) {
      const allNotes = this.container.querySelectorAll('.staff-note');
      allNotes.forEach(el => {
        const idx = parseInt(el.getAttribute('data-note-index'), 10);
        if (idx === noteIndex) {
          el.classList.add('selected');
        } else {
          el.classList.remove('selected');
        }
      });
    }
  }

  setPlayhead(noteIndex) {
    this.activePlayNoteIndex = noteIndex;
    if (this.container) {
      const allNotes = this.container.querySelectorAll('.staff-note');
      allNotes.forEach(el => {
        const idx = parseInt(el.getAttribute('data-note-index'), 10);
        if (idx === noteIndex) {
          el.classList.add('playing');
          // 谱面按自然尺寸渲染后远宽于可视区，必须横向滚动跟随，
          // 否则播放游标跑出屏幕，看起来像「五线谱停在开头不动」
          this.scrollNoteIntoView(el);
        } else {
          el.classList.remove('playing');
        }
      });
    }
  }

  /**
   * 把正在播放的音符横向滚动到谱箱可视区中央。
   * 用 getBoundingClientRect 相对换算而非 getBBox：
   * 后者是未缩放的 viewBox 坐标，元素一旦被 CSS 拉伸（min-width）就会算错。
   */
  scrollNoteIntoView(el) {
    const box = this.container;
    if (!box || !el) return;
    const boxRect = box.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const elLeftInContent = box.scrollLeft + (elRect.left - boxRect.left);
    const target = elLeftInContent - (box.clientWidth / 2);
    const clamped = Math.max(0, Math.min(target, box.scrollWidth - box.clientWidth));
    // 位移很小就不动，避免每个音符都触发一次无意义的平滑滚动动画
    if (Math.abs(clamped - box.scrollLeft) > 6) {
      box.scrollTo({ left: clamped, behavior: 'smooth' });
    }
  }

  /** 选中/取消选中休止符（rest 为 null 时清除选中高亮） */
  setSelectedRest(rest) {
    this.selectedRestKey = rest ? `${rest.startBeat}` : null;
    if (!this.container) return;
    this.container.querySelectorAll('.staff-rest').forEach(el => {
      el.classList.toggle('selected', el.getAttribute('data-rest-key') === this.selectedRestKey);
    });
  }

  clearPlayhead() {
    this.activePlayNoteIndex = null;
    if (this.container) {
      const allNotes = this.container.querySelectorAll('.staff-note');
      allNotes.forEach(el => el.classList.remove('playing'));
    }
  }

  createSvgElement(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) {
      el.setAttribute(k, v);
    }
    return el;
  }
}
