/**
 * 阶段四：乐理推断模块 (Music Theory Inference)
 * 实现：Krumhansl-Schmuckler 调式识别算法 (24个大小调)、音高类分布 (PCP/Chroma)、拍号与小节划分
 */

export class MusicTheoryEngine {
  constructor() {
    // 12 个半音名称
    this.pitchClassNames = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

    // Krumhansl-Kessler 标准大调与小调调性特征权重向量 (Key Profiles)
    this.majorProfile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88];
    this.minorProfile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17];

    // 各大调对应的调号升降号数量 (正数为升号 #，负数为降号 b)
    // C=0, G=1, D=2, A=3, E=4, B=5, F#=6, C#=7, F=-1, Bb=-2, Eb=-3, Ab=-4
    this.keySignatures = {
      'C Major': { sharps: 0, flats: 0, text: '无升降号 (1=C)' },
      'G Major': { sharps: 1, flats: 0, text: '1个升号 (#F)' },
      'D Major': { sharps: 2, flats: 0, text: '2个升号 (#F, #C)' },
      'A Major': { sharps: 3, flats: 0, text: '3个升号 (#F, #C, #G)' },
      'E Major': { sharps: 4, flats: 0, text: '4个升号 (#F, #C, #G, #D)' },
      'B Major': { sharps: 5, flats: 0, text: '5个升号' },
      'F# Major': { sharps: 6, flats: 0, text: '6个升号' },
      'C# Major': { sharps: 7, flats: 0, text: '7个升号' },
      'F Major': { sharps: 0, flats: 1, text: '1个降号 (bB)' },
      'Bb Major': { sharps: 0, flats: 2, text: '2个降号 (bB, bE)' },
      'Eb Major': { sharps: 0, flats: 3, text: '3个降号 (bB, bE, bA)' },
      'Ab Major': { sharps: 0, flats: 4, text: '4个降号' },
      'A Minor': { sharps: 0, flats: 0, text: '关系小调 (无升降号)' },
      'E Minor': { sharps: 1, flats: 0, text: '1个升号 (#F)' },
      'B Minor': { sharps: 2, flats: 0, text: '2个升号' },
      'F# Minor': { sharps: 3, flats: 0, text: '3个升号' },
      'C# Minor': { sharps: 4, flats: 0, text: '4个升号' },
      'D Minor': { sharps: 0, flats: 1, text: '1个降号 (bB)' },
      'G Minor': { sharps: 0, flats: 2, text: '2个降号' },
      'C Minor': { sharps: 0, flats: 3, text: '3个降号' },
      'F Minor': { sharps: 0, flats: 4, text: '4个降号' },
      'Bb Minor': { sharps: 0, flats: 5, text: '5个降号' },
      'Eb Minor': { sharps: 0, flats: 6, text: '6个降号' },
      'Ab Minor': { sharps: 0, flats: 7, text: '7个降号' }
    };
  }

  /**
   * 推断调性 (Key Finding)
   * @param {Array<Object>} notes - 音符序列 [{midi, duration}]
   * @returns {Object} 最佳调性、各调候选得分及音高类分布 (Chroma)
   */
  detectKey(notes) {
    if (!notes || notes.length === 0) {
      return {
        bestKey: 'C Major',
        tonic: 'C',
        mode: 'Major',
        confidence: 1.0,
        candidates: [],
        chroma: new Array(12).fill(0),
        signature: this.keySignatures['C Major']
      };
    }

    // 1. 计算以音符时长为权重的 12 维音高类向量 (Pitch Class Profile / Chroma)
    const chroma = new Float64Array(12);
    let totalDuration = 0;

    for (const note of notes) {
      const pc = (note.midi % 12 + 12) % 12;
      const weight = note.durationBeats || note.duration || 1;
      chroma[pc] += weight;
      totalDuration += weight;
    }

    // 归一化
    if (totalDuration > 0) {
      for (let i = 0; i < 12; i++) {
        chroma[i] /= totalDuration;
      }
    }

    // 2. 遍历 24 个大小调，计算皮尔逊相关系数 (Pearson Correlation)
    const results = [];

    // 计算大调
    for (let root = 0; root < 12; root++) {
      const shiftedProfile = this.rotate(this.majorProfile, root);
      const r = this.pearsonCorrelation(chroma, shiftedProfile);
      const rootName = this.pitchClassNames[root];
      const keyName = `${rootName} Major`;
      results.push({
        key: keyName,
        tonic: rootName,
        rootIndex: root,
        mode: 'Major',
        correlation: r,
        score: Math.max(0, (r + 1) / 2) // 映射至 0~1
      });
    }

    // 计算小调
    for (let root = 0; root < 12; root++) {
      const shiftedProfile = this.rotate(this.minorProfile, root);
      const r = this.pearsonCorrelation(chroma, shiftedProfile);
      const rootName = this.pitchClassNames[root];
      const keyName = `${rootName} Minor`;
      results.push({
        key: keyName,
        tonic: rootName,
        rootIndex: root,
        mode: 'Minor',
        correlation: r,
        score: Math.max(0, (r + 1) / 2)
      });
    }

    // 降序排序，取最高相关度
    results.sort((a, b) => b.correlation - a.correlation);
    const best = results[0];

    const keySig = this.keySignatures[best.key] || {
      sharps: 0,
      flats: 0,
      text: `${best.key}`
    };

    return {
      bestKey: best.key,
      tonic: best.tonic,
      rootIndex: best.rootIndex,
      mode: best.mode,
      confidence: Math.round(best.score * 100) / 100,
      candidates: results.slice(0, 5),
      chroma: Array.from(chroma).map(v => Math.round(v * 1000) / 1000),
      signature: keySig
    };
  }

  /**
   * 旋转数组
   */
  rotate(array, shift) {
    const result = new Array(array.length);
    for (let i = 0; i < array.length; i++) {
      result[(i + shift) % array.length] = array[i];
    }
    return result;
  }

  /**
   * 皮尔逊积矩相关系数计算
   */
  pearsonCorrelation(x, y) {
    const n = x.length;
    let sumX = 0, sumY = 0;
    for (let i = 0; i < n; i++) {
      sumX += x[i];
      sumY += y[i];
    }
    const meanX = sumX / n;
    const meanY = sumY / n;

    let numerator = 0;
    let sumSqX = 0;
    let sumSqY = 0;

    for (let i = 0; i < n; i++) {
      const dx = x[i] - meanX;
      const dy = y[i] - meanY;
      numerator += dx * dy;
      sumSqX += dx * dx;
      sumSqY += dy * dy;
    }

    const denominator = Math.sqrt(sumSqX * sumSqY);
    if (denominator === 0) return 0;
    return numerator / denominator;
  }

  /**
   * 小节线与拍号划分 (Measure & Meter Partitioning)
   * 采用克隆机制，保护 quantizedNotes 原始时序不被小节线截断破坏
   * @param {Array<Object>} quantizedNotes - 已完成节拍量化的音符
   * @param {number} [beatsPerMeasure=4] - 每小节拍数 (如 4/4 拍为 4，3/4 拍为 3)
   * @param {number} [beatUnit=4] - 拍子单位 (如 4 表示以四分音符为一拍)
   * @param {number|null} [endBeat=null] - 乐谱显示终点（拍）。默认 null 表示
   *        排到最后一个音符的自然结束拍、末尾小节照常补全休止符；传入后最后的
   *        小节只排到该拍为止。用于「删除末尾补位休止符」—— 否则划分器会按
   *        小节网格把刚删掉的休止符立即补回来，删除形同虚设。
   */
  partitionMeasures(quantizedNotes, beatsPerMeasure = 4, beatUnit = 4, endBeat = null) {
    if (!quantizedNotes || quantizedNotes.length === 0) {
      return [];
    }

    // 深度克隆音符列表并记录其在原始 quantizedNotes 中的索引 originalIndex
    // 杜绝原地直接修改 note.startBeat 导致二次重排计算错乱的问题
    const workingNotes = quantizedNotes.map((n, idx) => ({
      ...n,
      originalIndex: idx
    }));

    // 网格量化可能把相邻音符吸附到同一 startBeat，甚至产生乱序；
    // 稳定排序保证分小节顺序遍历时 currentBeat 不回退、不出现交叠伪休止符
    workingNotes.sort((a, b) => a.startBeat - b.startBeat);

    // 确定总拍数跨度
    const lastNote = workingNotes[workingNotes.length - 1];
    const naturalEndBeats = lastNote.startBeat + lastNote.durationBeats;
    const totalEndBeats = endBeat != null ? endBeat : naturalEndBeats;
    const totalMeasures = Math.max(1, Math.ceil(totalEndBeats / beatsPerMeasure));

    const measures = [];
    let noteIdx = 0;

    for (let m = 0; m < totalMeasures; m++) {
      const measureStartBeat = m * beatsPerMeasure;
      const gridEndBeat = measureStartBeat + beatsPerMeasure;
      // 仅在显式传入显示终点时裁剪末尾小节（删除尾部补位休止符后的排谱终点）；
      // 默认必须保持完整小节网格，否则末尾补位休止符永远不再生成
      const measureEndBeat = endBeat != null ? Math.min(gridEndBeat, totalEndBeats) : gridEndBeat;
      const measureNotes = [];

      let currentBeat = measureStartBeat;

      // 处理本小节范围内的所有音符及可能存在的休止符
      while (noteIdx < workingNotes.length) {
        const note = workingNotes[noteIdx];

        if (note.startBeat >= measureEndBeat) {
          // 超出当前小节
          break;
        }

        // 检查音符开始前是否有休止空隙
        if (note.startBeat > currentBeat + 0.05) {
          const restDuration = note.startBeat - currentBeat;
          measureNotes.push({
            isRest: true,
            startBeat: currentBeat,
            durationBeats: restDuration,
            typeLabel: this.beatsToRestLabel(restDuration)
          });
          currentBeat = note.startBeat;
        }

        // 计算当前音符在本小节内的持续拍数
        const noteEndBeat = note.startBeat + note.durationBeats;
        const noteSpanInMeasure = Math.min(noteEndBeat, measureEndBeat) - note.startBeat;

        // 同拍位重复/零时长量化产物不产生任何片段，避免负跨度休止与重叠音符
        if (noteSpanInMeasure <= 0.001) {
          noteIdx++;
          continue;
        }

        measureNotes.push({
          ...note,
          isRest: false,
          inMeasureBeat: note.startBeat - measureStartBeat,
          spanBeats: noteSpanInMeasure
        });

        currentBeat = Math.min(measureEndBeat, noteEndBeat);

        // 如果音符未跨越小节线，指向下一个
        if (noteEndBeat <= measureEndBeat) {
          noteIdx++;
        } else {
          // 音符跨越小节线（延音线 Tie）
          // 仅在工作副本中截断延音，下一小节继续使用，绝不污染全局源数据
          workingNotes[noteIdx] = {
            ...note,
            startBeat: measureEndBeat,
            durationBeats: noteEndBeat - measureEndBeat,
            isTieContinuation: true
          };
          break;
        }
      }

      // 如果小节末尾还有剩余拍数，补全小节休止符
      if (currentBeat < measureEndBeat - 0.05) {
        const restDuration = measureEndBeat - currentBeat;
        measureNotes.push({
          isRest: true,
          startBeat: currentBeat,
          durationBeats: restDuration,
          typeLabel: this.beatsToRestLabel(restDuration)
        });
      }

      measures.push({
        measureNumber: m + 1,
        startBeat: measureStartBeat,
        endBeat: measureEndBeat,
        items: measureNotes
      });
    }

    return measures;
  }

  beatsToRestLabel(beats) {
    if (beats >= 3.5) return '全休止符';
    if (beats >= 1.75) return '二分休止符';
    if (beats >= 0.75) return '四分休止符';
    if (beats >= 0.35) return '八分休止符';
    return '十六分休止符';
  }

  /**
   * 将 MIDI 音高转换为简谱唱名 (1 2 3 4 5 6 7) 及高低音点
   * @param {number} midi
   * @param {number} tonicRootIndex - 0=C, 2=D, 4=E, 5=F, 7=G, 9=A, 11=B
   */
  midiToJianpu(midi, tonicRootIndex = 0) {
    // 相对大调主音的半音偏置
    const semitoneOffset = (midi % 12 - tonicRootIndex + 12) % 12;

    // 大调自然音阶映射: 0->1, 2->2, 4->3, 5->4, 7->5, 9->6, 11->7
    const scaleMap = {
      0: { number: '1', accidental: '' },
      1: { number: '1', accidental: '#' },
      2: { number: '2', accidental: '' },
      3: { number: '2', accidental: '#' },
      4: { number: '3', accidental: '' },
      5: { number: '4', accidental: '' },
      6: { number: '4', accidental: '#' },
      7: { number: '5', accidental: '' },
      8: { number: '5', accidental: '#' },
      9: { number: '6', accidental: '' },
      10: { number: '6', accidental: '#' },
      11: { number: '7', accidental: '' }
    };

    const info = scaleMap[semitoneOffset] || { number: '1', accidental: '' };

    // 计算八度点：以中央 C (MIDI 60) 为基准中音区
    // 60-71 为中音，72-83 为高音 (1个高音点)，84+ (2个高音点)；48-59 为低音 (1个低音点)
    const baseOctaveMidi = 60 + tonicRootIndex;
    const diffOctaves = Math.floor((midi - baseOctaveMidi) / 12);

    let octaveDots = 0;
    let dotPosition = 'none'; // 'above', 'below'
    if (diffOctaves > 0) {
      octaveDots = Math.min(2, diffOctaves);
      dotPosition = 'above';
    } else if (diffOctaves < 0) {
      octaveDots = Math.min(2, Math.abs(diffOctaves));
      dotPosition = 'below';
    }

    return {
      number: info.number,
      accidental: info.accidental,
      octaveDots: octaveDots,
      dotPosition: dotPosition,
      rawMidi: midi
    };
  }
}
