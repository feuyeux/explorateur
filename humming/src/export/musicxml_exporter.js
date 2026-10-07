/**
 * 阶段五：MusicXML 乐谱文件导出器 (MusicXML 3.1 Exporter)
 * 生成标准 MusicXML 规范文本，兼容 Sibelius、Finale、MuseScore、Dorico、OpenSheetMusicDisplay (OSMD)
 */

export class MusicXMLExporter {
  /**
   * 将结构化小节与音符数据导出为标准 MusicXML 字符串
   * @param {Object} scoreData - { measures, keyInfo, meter, bpm }
   * @returns {string} XML 字符串
   */
  static exportXML(scoreData) {
    const measures = scoreData.measures || [];
    const bpm = scoreData.bpm || 100;
    const meterBeats = (scoreData.meter && scoreData.meter.beats) || 4;
    const meterUnit = (scoreData.meter && scoreData.meter.unit) || 4;

    // 调号 fifths 计数 (升号为正，降号为负)
    let fifths = 0;
    let mode = 'major';
    if (scoreData.keyInfo) {
      mode = scoreData.keyInfo.mode === 'Minor' ? 'minor' : 'major';
      if (scoreData.keyInfo.signature) {
        fifths = scoreData.keyInfo.signature.sharps || -scoreData.keyInfo.signature.flats || 0;
      }
    }

    const divisions = 4; // 每个四分音符 4 divisions (即十六分音符为 1 division)

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <work>
    <work-title>Humming Transcription (哼唱转谱)</work-title>
  </work>
  <identification>
    <creator type="composer">Humming-to-Score Studio</creator>
    <encoding>
      <software>Humming-to-Score Web DSP Engine</software>
    </encoding>
  </identification>
  <part-list>
    <score-part id="P1">
      <part-name>Vocal / Melodic Lead</part-name>
      <score-instrument id="P1-I1">
        <instrument-name>Voice</instrument-name>
      </score-instrument>
      <midi-instrument id="P1-I1">
        <midi-program>1</midi-program>
      </midi-instrument>
    </score-part>
  </part-list>
  <part id="P1">\n`;

    measures.forEach((measure, mIdx) => {
      xml += `    <measure number="${measure.measureNumber}">\n`;

      // 第 1 小节定义全局属性
      if (mIdx === 0) {
        xml += `      <attributes>
        <divisions>${divisions}</divisions>
        <key>
          <fifths>${fifths}</fifths>
          <mode>${mode}</mode>
        </key>
        <time>
          <beats>${meterBeats}</beats>
          <beat-type>${meterUnit}</beat-type>
        </time>
        <clef>
          <sign>G</sign>
          <line>2</line>
        </clef>
      </attributes>
      <direction placement="above">
        <direction-type>
          <metronome>
            <beat-unit>quarter</beat-unit>
            <per-minute>${bpm}</per-minute>
          </metronome>
        </direction-type>
        <sound tempo="${bpm}"/>
      </direction>\n`;
      }

      // 遍历小节内的音符与休止符
      measure.items.forEach((item, itemIdx) => {
        const itemBeats = item.spanBeats || item.durationBeats || 1;
        const dur = Math.max(1, Math.round(itemBeats * divisions));
        const xmlType = MusicXMLExporter.beatsToXmlType(itemBeats);
        // 附点判定必须基于本片段实际时值 (跨小节切片后原 isDotted 不再可靠)：
        // 1.5 / 3 / 6 拍等 x1.5 时值才是附点音符
        const isDotted = [0.75, 1.5, 3.0, 6.0].some(b => Math.abs(itemBeats - b) < 0.06);

        if (item.isRest) {
          xml += `      <note>
        <rest/>
        <duration>${dur}</duration>
        <type>${xmlType}</type>
        ${isDotted ? '<dot/>' : ''}
      </note>\n`;
        } else {
          const stepInfo = MusicXMLExporter.midiToXmlStep(item.midi);
          // 跨小节音符被小节划分器切成了两个片段 (isTieContinuation)：接上延音线，
          // 否则导出的乐谱会把延音重新断开成两次发声
          const tieStart = itemIdx < measure.items.length - 1 &&
            measure.items[itemIdx + 1].midi === item.midi &&
            !measure.items[itemIdx + 1].isRest;
          const tieStop = item.isTieContinuation;
          xml += `      <note>
        <pitch>
          <step>${stepInfo.step}</step>
          ${stepInfo.alter !== 0 ? `<alter>${stepInfo.alter}</alter>` : ''}
          <octave>${stepInfo.octave}</octave>
        </pitch>
        <duration>${dur}</duration>
        ${tieStop ? '<tie type="stop"/>\n        <notations><tied type="stop"/></notations>\n        ' : ''}
        ${tieStart ? '<tie type="start"/>\n        <notations><tied type="start"/></notations>\n        ' : ''}<type>${xmlType}</type>
        ${isDotted ? '<dot/>' : ''}
        ${!isDotted && stepInfo.accidental ? `<accidental>${stepInfo.accidental}</accidental>` : ''}
      </note>\n`;
        }
      });

      xml += `    </measure>\n`;
    });

    xml += `  </part>
</score-partwise>\n`;

    return xml;
  }

  static beatsToXmlType(beats) {
    if (beats >= 3.5) return 'whole';
    if (beats >= 1.75) return 'half';
    if (beats >= 0.75) return 'quarter';
    if (beats >= 0.35) return 'eighth';
    return '16th';
  }

  static midiToXmlStep(midi) {
    const names = [
      { step: 'C', alter: 0, acc: null },
      { step: 'C', alter: 1, acc: 'sharp' },
      { step: 'D', alter: 0, acc: null },
      { step: 'D', alter: 1, acc: 'sharp' },
      { step: 'E', alter: 0, acc: null },
      { step: 'F', alter: 0, acc: null },
      { step: 'F', alter: 1, acc: 'sharp' },
      { step: 'G', alter: 0, acc: null },
      { step: 'G', alter: 1, acc: 'sharp' },
      { step: 'A', alter: 0, acc: null },
      { step: 'A', alter: 1, acc: 'sharp' },
      { step: 'B', alter: 0, acc: null }
    ];

    const pc = (midi % 12 + 12) % 12;
    const octave = Math.floor(midi / 12) - 1;
    const info = names[pc];

    return {
      step: info.step,
      alter: info.alter,
      accidental: info.acc,
      octave: octave
    };
  }

  /**
   * 触发浏览器一键下载 MusicXML 文件
   */
  static download(scoreData, filename = 'humming_score.musicxml') {
    const xml = MusicXMLExporter.exportXML(scoreData);
    const blob = new Blob([xml], { type: 'application/vnd.recordare.musicxml+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
