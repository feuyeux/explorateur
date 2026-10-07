/**
 * 阶段五：简谱排版渲染器 (Numbered Musical Notation / Jianpu Renderer)
 * 实现：首调唱名法 (1=C/1=G)、高低音点、增时线与减时线 (下划线/双下划线)、休止符(0)、小节线(|)、和弦标记、歌词对位
 * 支持交互点击、试听与播放实时高亮
 */

export class NumberedRenderer {
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
  }

  /**
   * 渲染简谱 HTML 结构
   * @param {Object} scoreData - { measures, keyInfo, meter, bpm, chords }
   */
  render(scoreData) {
    if (!this.container) return;
    this.scoreData = scoreData;
    this.container.innerHTML = '';

    const measures = scoreData.measures || [];
    if (measures.length === 0) {
      this.container.innerHTML = '<div class="empty-score-tip">暂无简谱数据</div>';
      return;
    }

    const keyName = (scoreData.keyInfo && scoreData.keyInfo.tonic) || 'C';
    const beats = (scoreData.meter && scoreData.meter.beats) || 4;
    const unit = (scoreData.meter && scoreData.meter.unit) || 4;
    const bpm = scoreData.bpm || 100;

    // 创建简谱信息头部
    const headerEl = document.createElement('div');
    headerEl.className = 'jianpu-header';
    headerEl.innerHTML = `
      <div class="jianpu-meta-item"><strong>1 = ${keyName}</strong></div>
      <div class="jianpu-meta-item"><strong>${beats}/${unit} 拍</strong></div>
      <div class="jianpu-meta-item">♩ = ${bpm}</div>
    `;
    this.container.appendChild(headerEl);

    // 创建简谱小节排版容器
    const scoreBody = document.createElement('div');
    scoreBody.className = 'jianpu-body';

    let globalNoteCounter = 0;

    measures.forEach((measure, mIdx) => {
      const measureEl = document.createElement('div');
      measureEl.className = 'jianpu-measure';

      // 小节序号与和弦标记
      const topInfo = document.createElement('div');
      topInfo.className = 'jianpu-top-info';

      const numBadge = document.createElement('span');
      numBadge.className = 'jianpu-m-num';
      numBadge.textContent = `${measure.measureNumber}`;
      topInfo.appendChild(numBadge);

      const chord = measure.chord || (scoreData.chords && scoreData.chords[mIdx]?.chord);
      if (chord) {
        const chordBadge = document.createElement('span');
        chordBadge.className = 'jianpu-chord-badge';
        chordBadge.textContent = chord;
        topInfo.appendChild(chordBadge);
      }
      measureEl.appendChild(topInfo);

      // 音符排版行
      const notesRow = document.createElement('div');
      notesRow.className = 'jianpu-notes-row';

      measure.items.forEach(item => {
        if (item.isRest) {
          const restEl = this.createJianpuRestElement(item);
          notesRow.appendChild(restEl);
        } else {
          const noteIndex = item.originalIndex !== undefined ? item.originalIndex : globalNoteCounter++;
          const noteEl = this.createJianpuNoteElement(item, noteIndex, scoreData.keyInfo);
          notesRow.appendChild(noteEl);
        }
      });
      measureEl.appendChild(notesRow);

      // 小节线
      const barline = document.createElement('div');
      barline.className = mIdx === measures.length - 1 ? 'jianpu-barline-end' : 'jianpu-barline';
      measureEl.appendChild(barline);

      scoreBody.appendChild(measureEl);
    });

    this.container.appendChild(scoreBody);
  }

  /**
   * 生成单个简谱音符 DOM
   */
  createJianpuNoteElement(note, noteIndex, keyInfo) {
    const tonicIndex = (keyInfo && keyInfo.rootIndex) || 0;
    const jianpuInfo = this.midiToJianpuNumber(note.midi, tonicIndex, keyInfo && keyInfo.mode);

    const wrap = document.createElement('div');
    wrap.className = `jianpu-note-cell ${this.selectedNoteIndex === noteIndex ? 'selected' : ''} ${this.activePlayNoteIndex === noteIndex ? 'playing' : ''}`;
    wrap.setAttribute('data-note-index', noteIndex);

    // 1. 高音点
    const topDot = document.createElement('div');
    topDot.className = 'jianpu-octave-top';
    if (jianpuInfo.dotPosition === 'above') {
      topDot.textContent = '•'.repeat(jianpuInfo.octaveDots);
    }
    wrap.appendChild(topDot);

    // 2. 核心数字及升降号
    const core = document.createElement('div');
    core.className = 'jianpu-core-number';
    if (jianpuInfo.accidental) {
      const acc = document.createElement('span');
      acc.className = 'jianpu-accidental';
      acc.textContent = jianpuInfo.accidental;
      core.appendChild(acc);
    }

    const numSpan = document.createElement('span');
    numSpan.textContent = jianpuInfo.number;
    core.appendChild(numSpan);

    if (note.isDotted) {
      const dot = document.createElement('span');
      dot.className = 'jianpu-dot';
      dot.textContent = '·';
      core.appendChild(dot);
    }

    // 增时线
    if (note.durationBeats >= 3.5) {
      core.innerHTML += ' <span class="jianpu-dash">- - -</span>';
    } else if (note.durationBeats >= 2.5) {
      core.innerHTML += ' <span class="jianpu-dash">- -</span>';
    } else if (note.durationBeats >= 1.75) {
      core.innerHTML += ' <span class="jianpu-dash">-</span>';
    }

    wrap.appendChild(core);

    // 3. 低音点
    const bottomDot = document.createElement('div');
    bottomDot.className = 'jianpu-octave-bottom';
    if (jianpuInfo.dotPosition === 'below') {
      bottomDot.textContent = '•'.repeat(jianpuInfo.octaveDots);
    }
    wrap.appendChild(bottomDot);

    // 4. 减时线
    const underlineBox = document.createElement('div');
    underlineBox.className = 'jianpu-underlines';
    if (note.noteType === 'eighth') {
      underlineBox.innerHTML = '<div class="line"></div>';
    } else if (note.noteType === '16th') {
      underlineBox.innerHTML = '<div class="line"></div><div class="line"></div>';
    }
    wrap.appendChild(underlineBox);

    // 5. 歌词对位
    if (note.lyric) {
      const lyricDiv = document.createElement('div');
      lyricDiv.className = 'jianpu-lyric';
      lyricDiv.textContent = note.lyric;
      wrap.appendChild(lyricDiv);
    }

    // 交互点击
    wrap.addEventListener('click', (e) => {
      e.stopPropagation();
      this.selectedNoteIndex = noteIndex;
      if (this.onNoteSelected) this.onNoteSelected(noteIndex, note);
      if (this.onNoteAudition) this.onNoteAudition(note.midi);
      this.render(this.scoreData);
    });

    return wrap;
  }

  createJianpuRestElement(restItem) {
    const restKey = `${restItem.startBeat}`;
    const wrap = document.createElement('div');
    wrap.className = `jianpu-note-cell rest ${this.selectedRestKey === restKey ? 'selected' : ''}`;
    wrap.setAttribute('data-rest-key', restKey);
    wrap.setAttribute('title', `${restItem.typeLabel || '休止符'} (${restItem.durationBeats}拍) — 点击选中，可删除`);

    // 简谱的「0」可点击选中（随后可删除），与音符交互保持一致
    wrap.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.onRestSelected) this.onRestSelected(restItem);
    });

    const topDot = document.createElement('div');
    topDot.className = 'jianpu-octave-top';
    wrap.appendChild(topDot);

    const core = document.createElement('div');
    core.className = 'jianpu-core-number';
    if (restItem.durationBeats >= 3.5) {
      core.textContent = '0 0 0 0';
    } else if (restItem.durationBeats >= 1.75) {
      core.textContent = '0 0';
    } else {
      core.textContent = '0';
    }
    wrap.appendChild(core);

    const bottomDot = document.createElement('div');
    bottomDot.className = 'jianpu-octave-bottom';
    wrap.appendChild(bottomDot);

    return wrap;
  }

  midiToJianpuNumber(midi, tonicRootIndex, mode) {
    // 小调采用首调 la-based 记谱：以关系大调主音 (上方小三度) 为 1，
    // 否则自然小调的三级音会被错误标成 '#2'
    let baseRoot = tonicRootIndex;
    if (mode === 'Minor') {
      baseRoot = (tonicRootIndex + 3) % 12;
    }
    const semitoneOffset = (midi % 12 - baseRoot + 12) % 12;
    const mapping = {
      0: { number: '1', accidental: '' },
      1: { number: '1', accidental: '♯' },
      2: { number: '2', accidental: '' },
      3: { number: '2', accidental: '♯' },
      4: { number: '3', accidental: '' },
      5: { number: '4', accidental: '' },
      6: { number: '4', accidental: '♯' },
      7: { number: '5', accidental: '' },
      8: { number: '5', accidental: '♯' },
      9: { number: '6', accidental: '' },
      10: { number: '6', accidental: '♯' },
      11: { number: '7', accidental: '' }
    };

    const res = mapping[semitoneOffset] || { number: '1', accidental: '' };
    const baseOctaveMidi = 60 + baseRoot;
    const diff = Math.floor((midi - baseOctaveMidi) / 12);

    let octaveDots = 0;
    let dotPosition = 'none';
    if (diff > 0) {
      octaveDots = Math.min(2, diff);
      dotPosition = 'above';
    } else if (diff < 0) {
      octaveDots = Math.min(2, Math.abs(diff));
      dotPosition = 'below';
    }

    return {
      number: res.number,
      accidental: res.accidental,
      octaveDots,
      dotPosition
    };
  }

  setSelectedNote(noteIndex) {
    this.selectedNoteIndex = noteIndex;
    if (this.container) {
      const allCells = this.container.querySelectorAll('.jianpu-note-cell');
      allCells.forEach(el => {
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
      const allCells = this.container.querySelectorAll('.jianpu-note-cell');
      allCells.forEach(el => {
        const idx = parseInt(el.getAttribute('data-note-index'), 10);
        if (idx === noteIndex) {
          el.classList.add('playing');
          // 简谱随播放进度自动滚入视野（block:nearest 只在快出视野时微调，
          // 不会每次都跳动），保证「跟谱」体验
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
          el.classList.remove('playing');
        }
      });
    }
  }

  /** 选中/取消选中休止符（rest 为 null 时清除选中高亮） */
  setSelectedRest(rest) {
    this.selectedRestKey = rest ? `${rest.startBeat}` : null;
    if (!this.container) return;
    this.container.querySelectorAll('.jianpu-note-cell.rest').forEach(el => {
      el.classList.toggle('selected', el.getAttribute('data-rest-key') === this.selectedRestKey);
    });
  }

  clearPlayhead() {
    this.activePlayNoteIndex = null;
    if (this.container) {
      const allCells = this.container.querySelectorAll('.jianpu-note-cell');
      allCells.forEach(el => el.classList.remove('playing'));
    }
  }
}
