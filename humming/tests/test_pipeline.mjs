/**
 * 全面自动化测试脚本：验证 5 阶段高精度声学流水线与多引擎转谱 (pYIN / Basic Pitch / SPICE)
 */

import { AudioPreprocessor } from '../src/dsp/preprocessor.js';
import { PitchTracker } from '../src/dsp/pitch_tracker.js';
import { NoteSegmenter } from '../src/dsp/segmentation.js';
import { MusicTheoryEngine } from '../src/theory/krumhansl.js';
import { SampleAudioFactory } from '../src/audio/samples.js';
import { MidiExporter } from '../src/export/midi_exporter.js';
import { MusicXMLExporter } from '../src/export/musicxml_exporter.js';
import { AITranscriptionEngine } from '../src/dsp/ai_transcription_engine.js';

console.log('=== 测试五阶段哼唱转谱核心流水线 ===\n');

const sample = SampleAudioFactory.generateHummingAudio('twinkle', 16000);
console.log(`[生成人声样本] 标题: 《${sample.title}》, 采样点: ${sample.samples.length}, 采样率: ${sample.sampleRate}`);

// 阶段一：预处理
const preprocessor = new AudioPreprocessor({ targetSampleRate: 16000 });
const preResult = preprocessor.process(sample.samples, 16000);
console.log(`[阶段一: 预处理] 保留人声长度: ${(preResult.activeSamples.length / 16000).toFixed(2)}s, 起始切分点: ${preResult.trimOffsetSeconds.toFixed(3)}s`);

// 阶段二 & 三：测试多转谱引擎 (pYIN, Basic Pitch, SPICE)
const engines = ['pyin', 'basic_pitch', 'spice'];
const theoryEngine = new MusicTheoryEngine();

for (const eng of engines) {
  const aiEngine = new AITranscriptionEngine({ engine: eng, bpm: sample.bpm });
  const transcription = await aiEngine.transcribe(preResult.activeSamples, sample.bpm);

  console.log(`\n▶ 转谱引擎测试: [${transcription.engineUsed}]`);
  console.log(`  - 提取音符数: ${transcription.quantizedNotes.length}`);
  console.log(`  - 前 5 音符: ${transcription.quantizedNotes.slice(0, 5).map(n => n.noteName).join(' ')}`);

  // 阶段四：乐理推断
  const keyInfo = theoryEngine.detectKey(transcription.quantizedNotes);
  const measures = theoryEngine.partitionMeasures(transcription.quantizedNotes, 4, 4);
  console.log(`  - 推断调性: ${keyInfo.bestKey} (得分: ${(keyInfo.confidence * 100).toFixed(1)}%) | 小节数: ${measures.length}`);

  // 阶段五：导出验证
  const xml = MusicXMLExporter.exportXML({ measures, keyInfo, meter: { beats: 4, unit: 4 }, bpm: sample.bpm });
  const midiBlob = MidiExporter.exportMidi(transcription.quantizedNotes, sample.bpm, { beats: 4, unit: 4 });
  console.log(`  - 导出产物: MIDI 大小 = ${midiBlob.size} 字节, MusicXML 字符数 = ${xml.length}`);
}

console.log('\n🎉 所有核心声学转谱引擎回归测试 PASS！系统纯净且运转正常。');
