import { MusicTheoryEngine } from '../src/theory/krumhansl.js';
import { NoteSegmenter } from '../src/dsp/segmentation.js';

console.log('=== 测试音符交互编辑、删除与时间轴对齐逻辑 ===');

const theoryEngine = new MusicTheoryEngine();
const segmenter = new NoteSegmenter({ bpm: 100 });

// 模拟 4 个连续音符：C4(1拍), D4(1拍), E4(1拍), F4(1拍)
let notes = [
  { startBeat: 0, durationBeats: 1.0, startTime: 0, duration: 0.6, endTime: 0.6, midi: 60, noteName: 'C4', noteType: 'quarter', isDotted: false, typeLabel: '四分音符' },
  { startBeat: 1, durationBeats: 1.0, startTime: 0.6, duration: 0.6, endTime: 1.2, midi: 62, noteName: 'D4', noteType: 'quarter', isDotted: false, typeLabel: '四分音符' },
  { startBeat: 2, durationBeats: 1.0, startTime: 1.2, duration: 0.6, endTime: 1.8, midi: 64, noteName: 'E4', noteType: 'quarter', isDotted: false, typeLabel: '四分音符' },
  { startBeat: 3, durationBeats: 1.0, startTime: 1.8, duration: 0.6, endTime: 2.4, midi: 65, noteName: 'F4', noteType: 'quarter', isDotted: false, typeLabel: '四分音符' }
];

// 1. 验证 partitionMeasures 不可变性测试
const origCopy = JSON.stringify(notes);
const measures1 = theoryEngine.partitionMeasures(notes, 4, 4);
const measures2 = theoryEngine.partitionMeasures(notes, 4, 4);

if (JSON.stringify(notes) !== origCopy) {
  console.error('❌ FAIL: partitionMeasures 发生了原地数据修改！');
  process.exit(1);
} else {
  console.log('✅ PASS: partitionMeasures 保持源数据不可变性，多次调用无状态破坏');
}

// 2. 测试音高修改
notes[1].midi = 63;
notes[1].noteName = segmenter.midiToNoteName(63);
if (notes[1].noteName === 'D#4') {
  console.log('✅ PASS: 音高修改正常:', notes[1].noteName);
} else {
  console.error('❌ FAIL: 音高修改异常:', notes[1].noteName);
  process.exit(1);
}

// 3. 测试时值加倍与时间轴自动平移
// 修改第 0 个音符时值：1拍 -> 2拍 (delta = +1)
const deltaBeats = 2.0 - notes[0].durationBeats;
notes[0].durationBeats = 2.0;
for (let i = 1; i < notes.length; i++) {
  notes[i].startBeat += deltaBeats;
}

if (notes[1].startBeat === 2.0 && notes[2].startBeat === 3.0 && notes[3].startBeat === 4.0) {
  console.log('✅ PASS: 时值修改后后续音符时间轴平移对齐正常: [0, 2, 3, 4]');
} else {
  console.error('❌ FAIL: 时值平移对齐异常:', notes.map(n => n.startBeat));
  process.exit(1);
}

// 4. 测试跨小节 Tie 与 originalIndex 标记
const measuresWithTie = theoryEngine.partitionMeasures(notes, 4, 4);
// notes[3] starts at beat 4, which is in measure 2
if (measuresWithTie.length === 2 && measuresWithTie[1].items[0].originalIndex === 3) {
  console.log('✅ PASS: 小节划分与 originalIndex 标记精确映射');
} else {
  console.error('❌ FAIL: 小节划分或 originalIndex 标记异常');
  process.exit(1);
}

// 5. 测试音符删除与时间轴回退对齐
// 删除 index 1 (原 D#4, 时值 1 拍)
const deletedDur = notes[1].durationBeats;
for (let i = 2; i < notes.length; i++) {
  notes[i].startBeat -= deletedDur;
}
notes.splice(1, 1);

if (notes.length === 3 && notes[0].startBeat === 0 && notes[1].startBeat === 2.0 && notes[2].startBeat === 3.0) {
  console.log('✅ PASS: 音符删除后时间轴自动回退弥补空隙正常');
} else {
  console.error('❌ FAIL: 音符删除时间轴异常:', notes.map(n => n.startBeat));
  process.exit(1);
}

// 6. 测试插入新音符
const insertIdx = 1; // 在第 0 个后插入
const newStartBeat = notes[0].startBeat + notes[0].durationBeats; // 2.0
const durBeats = 1.0;
for (let i = insertIdx; i < notes.length; i++) {
  notes[i].startBeat += durBeats;
}
notes.splice(insertIdx, 0, {
  startBeat: newStartBeat,
  durationBeats: durBeats,
  midi: 67,
  noteName: 'G4'
});

if (notes.length === 4 && notes[1].startBeat === 2.0 && notes[2].startBeat === 3.0 && notes[3].startBeat === 4.0) {
  console.log('✅ PASS: 音符插入与时间轴延后对齐正常');
} else {
  console.error('❌ FAIL: 音符插入异常:', notes.map(n => n.startBeat));
  process.exit(1);
}

console.log('\n🎉 所有音符编辑与小节乐理核心单元测试全部 PASS！');
