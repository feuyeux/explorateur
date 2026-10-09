/**
 * 转谱准确率基准 (Transcription Accuracy Benchmark)
 *
 * 用 SampleAudioFactory 的 4 首内置示例（自带 ground truth 音符序列）跑完整
 * 「预处理 → 引擎转谱 → 量化」流水线，量化输出与期望音符序列的差异：
 *
 *   - fragmentation  检出/期望音符数比值（≈1 最好；>>1 = 颤音/滑音碎片化）
 *   - precision      检出音符中正确命中的比例（低 = 幽灵音符/碎片）
 *   - recall         期望音符中被检出的比例（低 = 漏音）
 *   - f1             综合指标
 *   - octaveErrors   八度错误数（哼唱识别的头号音高错误）
 *   - onsetHitRate   起拍命中（±0.3 拍）比例（节奏准确性）
 *
 * 用法：
 *   node scripts/benchmark_accuracy.mjs                # pYIN 引擎（Node 内直接跑）
 *   node scripts/benchmark_accuracy.mjs --dump a.json  # 追加评估浏览器导出的
 *                                                     # basic_pitch 结果（格式见
 *                                                     # dump 内 {preset, expected, quantized}[]）
 *
 * 退出码 0 = 跑完（本脚本不做阈值断言，只出数字；调参前后对比看数字说话）。
 */
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const { SampleAudioFactory } = await import(path.join(ROOT, 'src/audio/samples.js'));
const { AudioPreprocessor } = await import(path.join(ROOT, 'src/dsp/preprocessor.js'));
const { AITranscriptionEngine } = await import(path.join(ROOT, 'src/dsp/ai_transcription_engine.js'));

/**
 * 评估量化音符与期望旋律的差异（时间容差 ±0.3 拍，音高容差 ±0.5 半音）
 * @param {Array<{midi:number,beats:number}>} expected - 时间顺序的期望音符
 * @param {Array<{midi:number,startBeat:number}>} quantized - 量化后的检出音符
 */
export function evaluateAccuracy(expected, quantized) {
  const sortedQ = [...(quantized || [])].sort((a, b) => a.startBeat - b.startBeat || a.midi - b.midi);

  let acc = 0;
  const exp = (expected || []).map(n => {
    const e = { midi: n.midi, startBeat: acc, beats: n.beats };
    acc += n.beats;
    return e;
  });

  const ONSET_TOL = 0.3;
  let matchedExp = 0;
  let octaveErr = 0;
  let onsetHits = 0;
  let onsetDevSum = 0;

  for (const e of exp) {
    let best = null;
    for (const q of sortedQ) {
      const dev = Math.abs(q.startBeat - e.startBeat);
      if (dev <= ONSET_TOL && (!best || dev < Math.abs(best.startBeat - e.startBeat))) {
        best = q;
      }
    }
    if (best) {
      onsetHits++;
      onsetDevSum += Math.abs(best.startBeat - e.startBeat);
      const d = Math.abs(best.midi - e.midi);
      if (d <= 0.5) matchedExp++;
      else if (Math.abs(d - 12) <= 0.5) octaveErr++;
    }
  }

  let matchedQ = 0;
  for (const q of sortedQ) {
    if (exp.some(e => Math.abs(e.midi - q.midi) <= 0.5 && Math.abs(e.startBeat - q.startBeat) <= ONSET_TOL)) {
      matchedQ++;
    }
  }

  const precision = sortedQ.length ? matchedQ / sortedQ.length : 0;
  const recall = exp.length ? matchedExp / exp.length : 0;
  const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;

  return {
    expected: exp.length,
    detected: sortedQ.length,
    fragmentation: exp.length ? +(sortedQ.length / exp.length).toFixed(2) : 0,
    precision: +precision.toFixed(2),
    recall: +recall.toFixed(2),
    f1: +f1.toFixed(2),
    octaveErrors: octaveErr,
    onsetHitRate: exp.length ? +(onsetHits / exp.length).toFixed(2) : 0,
    meanOnsetDevBeats: onsetHits ? +(onsetDevSum / onsetHits).toFixed(2) : null
  };
}

function printRow(name, m) {
  const frag = m.fragmentation.toFixed(2).padStart(4);
  const p = m.precision.toFixed(2).padStart(4);
  const r = m.recall.toFixed(2).padStart(4);
  const f1 = m.f1.toFixed(2).padStart(4);
  const oct = String(m.octaveErrors).padStart(3);
  const onset = m.onsetHitRate.toFixed(2).padStart(4);
  const dev = m.meanOnsetDevBeats == null ? '  --' : m.meanOnsetDevBeats.toFixed(2).padStart(4);
  console.log(
    `${name.padEnd(14)} 期望${String(m.expected).padStart(3)}/检出${String(m.detected).padStart(3)} ` +
    `碎片比${frag} P${p} R${r} F1${f1} 八度错${oct} 起拍命中${onset} 平均起拍偏差${dev}`
  );
}

function aggregate(results) {
  const n = results.length || 1;
  return {
    expected: results.reduce((s, r) => s + r.m.expected, 0),
    detected: results.reduce((s, r) => s + r.m.detected, 0),
    fragmentation: +(results.reduce((s, r) => s + r.m.fragmentation, 0) / n).toFixed(2),
    precision: +(results.reduce((s, r) => s + r.m.precision, 0) / n).toFixed(2),
    recall: +(results.reduce((s, r) => s + r.m.recall, 0) / n).toFixed(2),
    f1: +(results.reduce((s, r) => s + r.m.f1, 0) / n).toFixed(2),
    octaveErrors: results.reduce((s, r) => s + r.m.octaveErrors, 0),
    onsetHitRate: +(results.reduce((s, r) => s + r.m.onsetHitRate, 0) / n).toFixed(2),
    meanOnsetDevBeats: +(results.reduce((s, r) => s + (r.m.meanOnsetDevBeats || 0), 0) / n).toFixed(2)
  };
}

// ---------------- pYIN 引擎（Node 直接跑） ----------------
async function runPyin() {
  const preprocessor = new AudioPreprocessor();
  const results = [];

  for (const preset of SampleAudioFactory.getPresetList()) {
    const { samples, bpm, expectedNotes } = SampleAudioFactory.generateHummingAudio(preset.id, 16000);
    const processed = preprocessor.process(samples, 16000);
    const engine = new AITranscriptionEngine({ engine: 'pyin', bpm });
    const res = engine.transcribeWithPYIN(processed.activeSamples, bpm);
    results.push({ name: preset.title, m: evaluateAccuracy(expectedNotes, res.quantizedNotes) });
  }
  return results;
}

// ---------------- 浏览器导出的引擎结果评估 ----------------
async function runDump(dumpPath) {
  const { readFileSync } = await import('fs');
  const dump = JSON.parse(readFileSync(dumpPath, 'utf-8'));
  return dump.map(entry => ({
    name: entry.name || entry.preset,
    m: evaluateAccuracy(entry.expected, entry.quantized)
  }));
}

// ---------------- 自动测速校准验证（模拟用户哼速 ≠ BPM 滑杆） ----------------
async function runTempoCalibration() {
  const preprocessor = new AudioPreprocessor();
  const engine = new AITranscriptionEngine({ engine: 'pyin', bpm: 100 });
  const results = [];

  for (const preset of SampleAudioFactory.getPresetList()) {
    const { samples, bpm, expectedNotes } = SampleAudioFactory.generateHummingAudio(preset.id, 16000);
    const processed = preprocessor.process(samples, 16000);
    // 故意用错误 BPM（比真实慢/快 25-30%）量化，模拟滑杆没对准哼唱速度
    const wrongBpm = Math.round(preset.id === 'happy_birthday' ? bpm * 1.3 : bpm * 0.75);
    engine.segmenter.bpm = wrongBpm;
    const res = engine.transcribeWithPYIN(processed.activeSamples, wrongBpm);

    const before = evaluateAccuracy(expectedNotes, res.quantizedNotes);

    // 自动校准：从时间域 rawNotes 估速 → 重量化
    const est = engine.segmenter.estimateTempo(res.rawNotes);
    const after = est
      ? evaluateAccuracy(expectedNotes, engine.segmenter.quantizeNotes(res.rawNotes, est, 0.5))
      : before;

    results.push({ preset: preset.title, trueBpm: bpm, wrongBpm, est, before, after });
  }
  return results;
}

const args = process.argv.slice(2);
const dumpIdx = args.indexOf('--dump');

console.log('=== 转谱准确率基准 (内置 4 例 · 音高容差±0.5半音 · 起拍容差±0.3拍) ===\n');

console.log('--- pYIN + Viterbi 引擎 ---');
const pyin = await runPyin();
pyin.forEach(r => printRow(r.name, r.m));
printRow('【均值】', aggregate(pyin));

if (dumpIdx >= 0 && args[dumpIdx + 1]) {
  console.log('\n--- 浏览器导出引擎结果 ---');
  const dumped = await runDump(args[dumpIdx + 1]);
  dumped.forEach(r => printRow(r.name, r.m));
  printRow('【均值】', aggregate(dumped));
}

console.log('\n--- 自动测速校准 (故意用错误 BPM 量化 → 估速恢复) ---');
const calib = await runTempoCalibration();
for (const c of calib) {
  const estStr = c.est ? `${c.est}` : '--';
  console.log(
    `${c.preset.padEnd(14)} 真实${String(c.trueBpm).padStart(3)}BPM · 错设${String(c.wrongBpm).padStart(3)} · 估出${estStr.padStart(3)} | ` +
    `校准前 F1 ${c.before.f1.toFixed(2)} 起拍命中 ${c.before.onsetHitRate.toFixed(2)} → ` +
    `校准后 F1 ${c.after.f1.toFixed(2)} 起拍命中 ${c.after.onsetHitRate.toFixed(2)}`
  );
}
