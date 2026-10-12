/**
 * 全面自动化测试：验证 5 阶段声学流水线与多引擎转谱 (pYIN / pYIN 人声优化档 / Basic Pitch)
 *
 * 真断言结构（参照 test_e2e_pipeline.mjs 的 check / exit(1) 约定）：
 * - 每个引擎跑完后断言 transcription.engineUsed 是该引擎的真实名称（防谎报来源）
 * - basic_pitch 在 Node（无 window/document 桩）下推理不可用会回退 pYIN：
 *   回退发生时如实标注 SKIP（与 PASS 分列），绝不计为假 PASS
 * - MusicXML 延音线（tie）成对性专项验证（小节内重复音不出 tie / 跨界延音出成对 tie）
 */

import { AudioPreprocessor } from '../src/dsp/preprocessor.js';
import { NoteSegmenter } from '../src/dsp/segmentation.js';
import { MusicTheoryEngine } from '../src/theory/krumhansl.js';
import { SampleAudioFactory } from '../src/audio/samples.js';
import { MidiExporter } from '../src/export/midi_exporter.js';
import { MusicXMLExporter } from '../src/export/musicxml_exporter.js';
import { AITranscriptionEngine } from '../src/dsp/ai_transcription_engine.js';

let failures = 0;
let skips = 0;
const check = (label, cond, detail = '') => {
  if (cond) console.log(`✅ PASS: ${label}`);
  else { failures++; console.error(`❌ FAIL: ${label}${detail ? ` — ${detail}` : ''}`); }
};
const skip = (label, detail = '') => {
  skips++;
  console.log(`⏭️ SKIP: ${label}${detail ? ` — ${detail}` : ''}`);
};

console.log('=== 测试五阶段哼唱转谱核心流水线 ===\n');

const sample = SampleAudioFactory.generateHummingAudio('twinkle', 16000);
check('人声样本生成非空', sample.samples.length > 0,
  `samples=${sample.samples.length}`);

// ── 阶段一：预处理 ─────────────────────────────────────────────
const preprocessor = new AudioPreprocessor({ targetSampleRate: 16000 });
const preResult = preprocessor.process(sample.samples, 16000);
check('阶段一: 预处理保留非空人声段', preResult.activeSamples.length > 0,
  `activeSamples=${preResult.activeSamples.length}`);
check('阶段一: 预处理输出无 NaN', !preResult.activeSamples.some(v => !Number.isFinite(v)));

// 预处理单元素数组（单声道按声道数组传入）不得产出 NaN（ch1 缺省回归）
{
  const ch0 = sample.samples;
  const monoArrResult = preprocessor.process([ch0], 16000);
  check('阶段一: 单元素声道数组按单声道处理无 NaN',
    monoArrResult.activeSamples.length > 0 && !monoArrResult.activeSamples.some(v => !Number.isFinite(v)));
}

// ── 阶段二 & 三：多转谱引擎 (pYIN / pYIN 人声优化档 / Basic Pitch) ──
// 引擎名断言表：engineUsed 必须如实反映实际执行的引擎，绝不谎报来源
const EXPECTED_ENGINE_NAMES = {
  pyin: 'pYIN + Viterbi (本地高保真 DSP 引擎)',
  pyin_voice: 'pYIN (voice-optimized) 人声优化档'
};
const engines = ['pyin', 'pyin_voice', 'basic_pitch'];
const theoryEngine = new MusicTheoryEngine();

function countTies(xml) {
  return {
    start: (xml.match(/<tie type="start"\/>/g) || []).length,
    stop: (xml.match(/<tie type="stop"\/>/g) || []).length,
    tiedStart: (xml.match(/<tied type="start"\/>/g) || []).length,
    tiedStop: (xml.match(/<tied type="stop"\/>/g) || []).length
  };
}

for (const eng of engines) {
  const aiEngine = new AITranscriptionEngine({ engine: eng, bpm: sample.bpm });
  const transcription = await aiEngine.transcribe(preResult.activeSamples, sample.bpm);

  console.log(`\n▶ 转谱引擎测试: [${transcription.engineUsed}]`);

  // 引擎名如实性断言
  if (eng in EXPECTED_ENGINE_NAMES) {
    check(`[${eng}] engineUsed 为真实引擎名`,
      transcription.engineUsed === EXPECTED_ENGINE_NAMES[eng],
      `实际 "${transcription.engineUsed}"，期望 "${EXPECTED_ENGINE_NAMES[eng]}"`);
    check(`[${eng}] engineUsed 不得谎报为第三方模型`,
      !/SPICE|Magenta/i.test(transcription.engineUsed),
      `实际 "${transcription.engineUsed}"`);
  } else if (eng === 'basic_pitch') {
    // 只认「Spotify Basic Pitch」开头的名称为内置推理成功；
    // 回退标签（如 "...（Basic Pitch 不可用，已本地回退）"）也含
    // "Basic Pitch" 字样，不能误判为成功
    if (/Spotify Basic Pitch/.test(transcription.engineUsed)) {
      check('[basic_pitch] 内置推理成功且如实命名', true);
    } else if (/Basic Pitch 协同测速/.test(transcription.engineUsed)) {
      // 清唱/哼唱输入会智能路由到 pYIN 单音线，Basic Pitch 只参与协同测速——
      // 能给出该标签说明模型已加载并跑完，同样是内置推理成功，不算 SKIP
      check('[basic_pitch] 内置推理成功（清唱输入走 pYIN 单音路由，Basic Pitch 协同测速）', true);
    } else {
      // 回退发生时如实 SKIP，不假 PASS
      skip('[basic_pitch] 内置神经网络推理（当前环境不可用，已回退 pYIN）',
        `engineUsed="${transcription.engineUsed}"`);
    }
  }

  check(`[${eng}] 识别出音符`, transcription.quantizedNotes.length > 0,
    `quantizedNotes=${transcription.quantizedNotes.length}`);

  // ── 阶段四：乐理推断 ──
  const keyInfo = theoryEngine.detectKey(transcription.quantizedNotes);
  const measures = theoryEngine.partitionMeasures(transcription.quantizedNotes, 4, 4);
  check(`[${eng}] 推断出调性`, typeof keyInfo.bestKey === 'string' && keyInfo.bestKey.length > 0,
    `bestKey=${keyInfo.bestKey}`);
  check(`[${eng}] 划分出小节`, measures.length > 0, `measures=${measures.length}`);

  // ── 阶段五：导出验证 ──
  const xml = MusicXMLExporter.exportXML({ measures, keyInfo, meter: { beats: 4, unit: 4 }, bpm: sample.bpm });
  const midiBlob = MidiExporter.exportMidi(transcription.quantizedNotes, sample.bpm, { beats: 4, unit: 4 });

  check(`[${eng}] MIDI 导出非空`, midiBlob.size > 0, `size=${midiBlob.size}`);
  check(`[${eng}] MusicXML 导出非空`, xml.length > 0 && xml.includes('<score-partwise'), `chars=${xml.length}`);

  // 延音线成对性：每个 <tie type="start"/> 必须有对应的 stop（非法 MusicXML 防回归）
  const ties = countTies(xml);
  check(`[${eng}] MusicXML tie start/stop 成对`,
    ties.start === ties.stop && ties.tiedStart === ties.tiedStop,
    `start=${ties.start} stop=${ties.stop} tiedStart=${ties.tiedStart} tiedStop=${ties.tiedStop}`);
}

// ── MusicXML 延音线专项：小节内重复音 vs 跨小节延音 ─────────────
console.log('\n=== MusicXML 延音线（tie）专项验证 ===');

function makeNote(startBeat, durationBeats, midi) {
  return {
    startBeat, durationBeats, midi,
    startTime: startBeat * 0.6, endTime: (startBeat + durationBeats) * 0.6,
    duration: durationBeats * 0.6, noteName: 'C4'
  };
}

function exportForNotes(notes) {
  const measures = theoryEngine.partitionMeasures(notes, 4, 4);
  return MusicXMLExporter.exportXML({
    measures, keyInfo: null, meter: { beats: 4, unit: 4 }, bpm: 100
  });
}

// 案例 1：小节内相邻同音（《小星星》「1 1」两个 C4 重新咬字）→ 不得出 tie
{
  const xml = exportForNotes([makeNote(0, 1, 60), makeNote(1, 1, 60), makeNote(2, 1, 62), makeNote(3, 1, 62)]);
  const ties = countTies(xml);
  check('小节内相邻同音不出 tie（无配对 start 防回归）',
    ties.start === 0 && ties.stop === 0, JSON.stringify(ties));
}

// 案例 2：跨界延音（C4@beat2 时值 2.5 拍跨界，第 2 小节续段 0.5 拍）→ 成对 tie
{
  const xml = exportForNotes([makeNote(0, 1, 60), makeNote(1, 1, 60), makeNote(2, 2.5, 60), makeNote(4.5, 1.5, 64)]);
  const ties = countTies(xml);
  check('跨界延音出成对 tie', ties.start === 1 && ties.stop === 1, JSON.stringify(ties));
  check('跨界延音 tied 成对', ties.tiedStart === 1 && ties.tiedStop === 1, JSON.stringify(ties));
  const m1 = xml.split('<measure number="2"')[0];
  const m2 = xml.split('<measure number="2"')[1] || '';
  const m1Ties = countTies(m1);
  const m2Ties = countTies(m2);
  check('跨界片段在第 1 小节出 tie start、无 stop',
    m1Ties.start === 1 && m1Ties.stop === 0, JSON.stringify(m1Ties));
  check('续段在第 2 小节出 tie stop、无 start',
    m2Ties.stop === 1 && m2Ties.start === 0, JSON.stringify(m2Ties));
}

// 案例 3：超小节长音（10 拍跨 2 条小节线）→ 链式 tie，中段同时 stop+start
{
  const xml = exportForNotes([makeNote(0, 10, 60)]);
  const ties = countTies(xml);
  check('10 拍长音切三段出 tie start x2 / stop x2', ties.start === 2 && ties.stop === 2, JSON.stringify(ties));
  const m2 = (xml.split('<measure number="2"')[1] || '').split('<measure number="3"')[0] || '';
  const m2Ties = countTies(m2);
  check('长音中段同时 stop+start', m2Ties.stop === 1 && m2Ties.start === 1, JSON.stringify(m2Ties));
}

// 案例 4：跨小节线相邻同音（末拍 C4 + 下小节首拍重新咬字 C4）→ 不出 tie
{
  const xml = exportForNotes([makeNote(3, 1, 60), makeNote(4, 1, 60)]);
  const ties = countTies(xml);
  check('跨小节线重咬字同音不出 tie', ties.start === 0 && ties.stop === 0, JSON.stringify(ties));
}

// ── 汇总 ────────────────────────────────────────────────────────
console.log(failures === 0
  ? `\n🎉 流水线测试全部 PASS！${skips > 0 ? `（另有 ${skips} 项 SKIP，环境能力所限，非失败）` : ''}`
  : `\n❌ ${failures} 项流水线测试失败`);
process.exit(failures === 0 ? 0 : 1);
