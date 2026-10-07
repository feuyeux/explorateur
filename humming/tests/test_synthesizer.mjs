/**
 * 合成器播放链路单元测试 (Synthesizer Playback Test)
 *
 * 用 Mock AudioContext 验证「试听乐谱」按钮的完整发声链路：
 *   playScore() → scoreGain 总线 → masterGain → destination
 *
 * 关注点：
 *  1. 振荡器是否被创建并 start()，且其输出最终连通到 destination
 *  2. 音频总线的增益是否被意外静音（历史上 stopScore() 会把 gain 置 0）
 *  3. 音符时序是否正确调度（noteDelay 按 startTime 递增）
 *  4. 播放结束后是否自动复位（onPlaybackEnd 触发）
 */
import { Synthesizer } from '../src/audio/synthesizer.js';

let failures = 0;
const check = (label, cond, detail = '') => {
  if (cond) console.log(`✅ PASS: ${label}`);
  else { failures++; console.log(`❌ FAIL: ${label}${detail ? ` — ${detail}` : ''}`); }
};

/** 记录拓扑连接的 Mock AudioContext */
class MockParam {
  constructor(v = 0) { this.value = v; this.events = []; }
  setValueAtTime(v, t) { this.events.push({ type: 'set', v, t }); this.value = v; return this; }
  linearRampToValueAtTime(v, t) { this.events.push({ type: 'linear', v, t }); return this; }
  exponentialRampToValueAtTime(v, t) { this.events.push({ type: 'exp', v, t }); return this; }
  cancelScheduledValues() { return this; }
}
class MockNode {
  constructor(ctx, kind) { this.ctx = ctx; this.kind = kind; this.connections = []; this.started = false; this.stopped = false; this.disconnected = false; }
  connect(dest) { this.connections.push(dest); return dest; }
  disconnect() { this.disconnected = true; this.connections = []; }
}
class MockGain extends MockNode {
  constructor(ctx) { super(ctx, 'gain'); this.gain = new MockParam(1); }
}
class MockOsc extends MockNode {
  constructor(ctx) { super(ctx, 'osc'); this.frequency = new MockParam(440); this.type = 'sine'; this.startTime = null; this.stopTime = null; }
  start(t) { this.started = true; this.startTime = t; this.ctx.startedOscillators.push(this); }
  stop(t) { this.stopped = true; this.stopTime = t; }
}
class MockCtx {
  constructor() {
    this.currentTime = 0;
    this.destination = new MockNode(this, 'destination');
    this.startedOscillators = [];
    this.createdGains = [];
    this.state = 'running';
  }
  createGain() { const g = new MockGain(this); this.createdGains.push(g); return g; }
  createOscillator() { return new MockOsc(this); }
  resume() { this.state = 'running'; return Promise.resolve(); }
}

const notes = [
  { midi: 60, startTime: 0.0, duration: 0.5 },
  { midi: 62, startTime: 0.5, duration: 0.5 },
  { midi: 64, startTime: 1.0, duration: 0.5 }
];

console.log('=== playScore 基本发声链路 ===');
const ctx = new MockCtx();
const synth = new Synthesizer(ctx);
await synth.playScore(notes);

check('创建了振荡器（5 个谐波 × 3 音符 = 15）',
  ctx.startedOscillators.length === 15, `实际 ${ctx.startedOscillators.length}`);
check('所有振荡器均已 start()', ctx.startedOscillators.every(o => o.started));
check('synth.isPlaying 为 true', synth.isPlaying === true);

console.log('\n=== 音频拓扑连通性（决定能否听见） ===');
const masterGain = synth.masterGain;
check('masterGain 连通到 destination',
  masterGain.connections.includes(ctx.destination),
  `masterGain.connections = ${masterGain.connections.length}`);
check('masterGain 未被断开', !masterGain.disconnected);
check('masterGain.gain 归一为有效值 (>0)',
  masterGain.gain.value > 0, `实际 ${masterGain.gain.value}`);

const scoreGain = synth.scoreGain;
check('scoreGain 连通到 masterGain', scoreGain.connections.includes(masterGain));
check('scoreGain 未被断开', !scoreGain.disconnected);
check('scoreGain.gain 归一为有效值 (>0)',
  scoreGain.gain.value > 0, `实际 ${scoreGain.gain.value}`);

console.log('\n=== 音符时序调度 ===');
const starts = [...new Set(ctx.startedOscillators.map(o => o.startTime))].sort((a, b) => a - b);
check('音符按 startTime 递增调度 (3 组)', starts.length === 3, `实际 ${starts.length}: ${starts}`);
const expected = [0.05, 0.55, 1.05];
check('首音延后 50ms 调度', Math.abs(starts[0] - expected[0]) < 1e-6, `实际 ${starts[0]}`);
check('第二音延后 550ms', Math.abs(starts[1] - expected[1]) < 1e-6, `实际 ${starts[1]}`);
check('第三音延后 1050ms', Math.abs(starts[2] - expected[2]) < 1e-6, `实际 ${starts[2]}`);

console.log('\n=== 音高换算 ===');
const freqs = [...new Set(ctx.startedOscillators.map(o => o.frequency.value))].sort((a, b) => a - b);
check('C4 (MIDI 60) → 261.63 Hz', Math.abs(freqs[0] - 261.63) < 0.1, `实际 ${freqs[0]?.toFixed(2)}`);
check('D4 (MIDI 62) → 293.66 Hz', freqs.some(f => Math.abs(f - 293.66) < 0.1));
check('E4 (MIDI 64) → 329.63 Hz', freqs.some(f => Math.abs(f - 329.63) < 0.1));

console.log('\n=== 停止与复位 ===');
let endFired = 0;
synth.onPlaybackEnd = () => { endFired++; };
synth.stopScore();
check('stopScore 后 isPlaying=false', synth.isPlaying === false);
check('stopScore 触发 onPlaybackEnd', endFired === 1);
check('stopScore 后重建的 scoreGain 增益为 1（下次可听）',
  synth.scoreGain.gain.value === 1, `实际 ${synth.scoreGain.gain.value}`);
check('stopScore 后 scoreGain 重新连通 masterGain',
  synth.scoreGain.connections.includes(synth.masterGain));

console.log('\n=== 二次播放（停止后重新试听） ===');
const before = ctx.startedOscillators.length;
await synth.playScore(notes);
check('停止后可再次播放出音',
  ctx.startedOscillators.length > before, `${before} → ${ctx.startedOscillators.length}`);
check('二次播放后 scoreGain 仍连通',
  synth.scoreGain.connections.includes(synth.masterGain) && !synth.scoreGain.disconnected);

console.log('\n=== 边界情况 ===');
const ctx2 = new MockCtx();
const synth2 = new Synthesizer(ctx2);
await synth2.playScore([]);
check('空音符列表不产生声音', ctx2.startedOscillators.length === 0);
await synth2.playScore(null);
check('null 输入不抛错', true);


// ---------------------------------------------------------------------------
// 回归场景：AudioContext 处于 suspended（浏览器自动播放策略）时的播放行为
// ---------------------------------------------------------------------------
console.log('\n=== suspended 上下文场景（自动播放策略） ===');
{
  // 模拟：resume() 需要异步若干 tick 才真正生效
  class SuspendedCtx extends MockCtx {
    constructor() { super(); this.state = 'suspended'; this.resumeCalls = 0; this._pending = []; }
    resume() {
      this.resumeCalls++;
      const p = new Promise(r => this._pending.push(r));
      this._pendingPromise = p;
      return p;
    }
    settle() { this.state = 'running'; this._pending.forEach(r => r()); }
  }
  const sctx = new SuspendedCtx();
  const ssynth = new Synthesizer(sctx);
  const result = ssynth.playScore(notes);
  check('suspended 时仍会尝试 resume()', sctx.resumeCalls >= 1, `resumeCalls=${sctx.resumeCalls}`);
  const isPromise = result && typeof result.then === 'function';
  check('playScore 在 suspended 时返回 Promise（可等待 resume 完成）', isPromise,
    `返回类型: ${typeof result}`);
  sctx.settle();
  if (isPromise) {
    await result;
    check('resume 完成后确实产生了振荡器',
      sctx.startedOscillators.length === 15, `实际 ${sctx.startedOscillators.length}`);
    check('resume 后 scoreGain 连通到 masterGain',
      ssynth.scoreGain.connections.includes(ssynth.masterGain));
  }
}


// ---------------------------------------------------------------------------
// 长乐谱压力测试：复现 815 个音符的场景
// ---------------------------------------------------------------------------
console.log('\n=== 长乐谱压力测试 (815 音符) ===');
{
  class StressCtx extends MockCtx {
    constructor() { super(); this.maxConcurrentOsc = 0; this.peakLiveNodes = 0; }
    createOscillator() {
      const o = super.createOscillator();
      const s = o.start.bind(o);
      o.start = () => { this.maxConcurrentOsc = Math.max(this.maxConcurrentOsc, this.startedOscillators.length); s(); };
      return o;
    }
  }
  const sctx = new StressCtx();
  const ssynth = new Synthesizer(sctx);
  const big = Array.from({ length: 815 }, (_, i) => ({
    midi: 60 + (i % 12), startTime: i * 0.3, duration: 0.25
  }));

  const t0 = Date.now();
  await ssynth.playScore(big);
  const elapsed = Date.now() - t0;

  check('长乐谱 playScore 立即返回（不再同步阻塞）', elapsed < 500, `耗时 ${elapsed}ms`);
  check('首次调度未一次性创建全部振荡器', sctx.startedOscillators.length < 815 * 5,
    `首轮仅创建 ${sctx.startedOscillators.length} 个 (全量需 ${815*5})`);
  check('首轮创建量受 MAX_VOICES 约束',
    sctx.startedOscillators.length <= ssynth.MAX_VOICES,
    `${sctx.startedOscillators.length} > ${ssynth.MAX_VOICES}`);
  check('调度定时器已启动（会继续滚动排期）', ssynth._schedulerTimer !== null);

  // 模拟音频时钟推进，验证滚动预调度会持续补充音符
  const before = sctx.startedOscillators.length;
  for (let t = 0; t < 8; t++) { sctx.currentTime += 0.5; ssynth._scheduleTick(); }
  check('时钟推进后持续排期新音符',
    sctx.startedOscillators.length > before,
    `${before} -> ${sctx.startedOscillators.length}`);

  // 验证并发上限被真正尊重
  let live = 0, maxLive = 0;
  for (const o of sctx.startedOscillators) {
    if (o._stopAt != null && sctx.currentTime <= o._stopAt) live++;
    maxLive = Math.max(maxLive, live);
  }
  check('并发振荡器始终不超过上限',
    maxLive <= ssynth.MAX_VOICES, `峰值 ${maxLive} > ${ssynth.MAX_VOICES}`);

  ssynth.stopScore();
  check('stopScore 关闭调度定时器', ssynth._schedulerTimer === null);
}


// ---------------------------------------------------------------------------
// 回归：密集乐段不得因复音上限而饿死
// MAX_VOICES 若取得比「预调度窗口内密集音符所需振荡器数」还小，排期会被
// 反复挡住，音符被迫迟到播放，声音糊成一团。
// 注意 activeOscillators 含尚未发声的预调度音符，占用按
// (SCHEDULE_AHEAD + 余音) 窗口内的音符数 × HARMONIC_COUNT 估算。
// 本应用最密配置 = 十六分网格 @180BPM = 0.0833s 一个音。
// ---------------------------------------------------------------------------
console.log('\n=== 密集乐段调度不饿死 (十六分网格 @180BPM + 4声部和弦) ===');
{
  const dctx = new MockCtx();
  const dsynth = new Synthesizer(dctx);
  const SPACING = 60 / 180 / 4;            // 0.0833s
  const CHORD = 4;                          // 4 声部和弦
  const dense = [];
  for (let i = 0; i < 120 / SPACING; i++) {
    for (let v = 0; v < CHORD; v++) {
      dense.push({ midi: 60 + v, startTime: i * SPACING, duration: SPACING * 0.9 });
    }
  }

  await dsynth.playScore(dense);

  // 排期永远比 ctx 时钟慢一个固定的起播余量(SCHEDULE 基准有 0.05s 偏移)，
  // 因此「单次 tick 零进展」不是饿死的判据。真正的饿死是**滞后量持续累积**：
  // 排期进度追不上时钟推进速度。这里测 lag 是否增长。
  const lagOf = () => dense.filter(
    n => n.startTime <= dctx.currentTime + dsynth.SCHEDULE_AHEAD).length - dsynth._scheduleCursor;
  let ticks = 0;
  let initialLag = null;
  let maxLag = 0;
  for (let step = 0; step < 400; step++) {
    dctx.currentTime += 0.05;
    dsynth._scheduleTick();
    ticks++;
    const lag = lagOf();
    if (initialLag === null) initialLag = lag;
    maxLag = Math.max(maxLag, lag);
  }
  const finalLag = lagOf();

  check('真实最密密度排期滞后量不随时间累积',
    finalLag <= initialLag + 8,
    `初始滞后 ${initialLag} → 最终滞后 ${finalLag}（峰值 ${maxLag}）`);
  check('真实最密密度全程零复音饿死',
    dsynth._starvedTicks === 0, `starvedTicks=${dsynth._starvedTicks}`);
  check('排期进度已追上时钟（滞后在起播余量量级内）',
    finalLag >= 0 && finalLag <= 16, `最终滞后 ${finalLag} 个音符`);
  // 并发数必须按存活窗口统计，不能用累计创建量（会随播放时长单调增长）
  let live = 0, maxLive = 0;
  for (const o of dctx.startedOscillators) {
    if (o._stopAt != null && dctx.currentTime <= o._stopAt) live++;
    else if (o._stopAt == null || dctx.currentTime <= o._stopAt + 0.2) live++;
    maxLive = Math.max(maxLive, live);
  }
  check('并发存活振荡器始终不超过 MAX_VOICES',
    maxLive <= dsynth.MAX_VOICES, `并发峰值 ${maxLive} > ${dsynth.MAX_VOICES}`);
  dsynth.stopScore();
}


// 上限必须是**兜底**：面对病态输入（时值极短的巨量音符）仍要能兜住，
// 不能无限膨胀节点数把音频线程压垮。
console.log('\n=== 病态密度仍受上限兜底保护 ===');
{
  const pctx = new MockCtx();
  const psynth = new Synthesizer(pctx);
  const patho = Array.from({ length: 2000 }, (_, i) => ({
    midi: 60 + (i % 12), startTime: i * 0.01, duration: 0.005
  }));
  await psynth.playScore(patho);
  const peak = pctx.startedOscillators.length;
  check('病态输入首轮创建量受 MAX_VOICES 约束',
    peak <= psynth.MAX_VOICES, `首轮 ${peak} > ${psynth.MAX_VOICES}`);
  check('病态输入远小于全量创建 (2000×5=10000)',
    peak < 10000, `实际 ${peak}`);
  check('病态输入下记录到饿死信号（证明上限确实在兜底）',
    psynth._starvedTicks > 0, `starvedTicks=${psynth._starvedTicks}`);
  psynth.stopScore();
}


// ---------------------------------------------------------------------------
// 回归：乱序音符输入
// 滚动调度是游标顺序推进的，若入参未按 startTime 排序会导致播放顺序错乱，
// 且「总时长按数组最后一个音符计算」会算错，表现为播放中途被截断。
// ---------------------------------------------------------------------------
console.log('\n=== 乱序音符输入 ===');
{
  const uctx = new MockCtx();
  const usynth = new Synthesizer(uctx);
  const shuffled = [
    { midi: 64, startTime: 1.0, duration: 0.5 },
    { midi: 60, startTime: 0.0, duration: 0.5 },
    { midi: 62, startTime: 0.5, duration: 0.5 }
  ];
  await usynth.playScore(shuffled);
  const starts = [...new Set(uctx.startedOscillators.map(o => o.startTime))].sort((a, b) => a - b);
  check('乱序输入被自动按 startTime 排序（3 个音符均已排期）',
    starts.length === 3, `实际 ${starts.length}: ${starts}`);
  check('排序后调度时间递增', starts.every((v, i) => i === 0 || v > starts[i - 1]), `${starts}`);
  check('首个音符基准为最早 startTime', Math.abs(starts[0] - 0.05) < 1e-6, `实际 ${starts[0]}`);
  usynth.stopScore();
}


// ---------------------------------------------------------------------------
// 停止语义：区分「自然播完」与「用户主动停止」
// playScore 内部会先调用一次 stopScore 做前置清理，若不区分原因，
// 会在开始播放的瞬间闪出一条「已停止」的误导提示。
// ---------------------------------------------------------------------------
console.log('\n=== 停止语义 (reason) ===');
{
  const rctx = new MockCtx();
  const rsynth = new Synthesizer(rctx);
  const reasons = [];
  rsynth.onPlaybackEnd = (reason) => reasons.push(reason);

  await rsynth.playScore(notes);
  check('playScore 前置清理使用 restart 原因',
    reasons[0] === 'restart', `实际 ${reasons[0]}`);

  rsynth.stopScore('stopped');
  check('用户主动停止使用 stopped 原因',
    reasons[reasons.length - 1] === 'stopped', `实际 ${reasons[reasons.length - 1]}`);

  rsynth.stopScore('ended');
  check('自然播完使用 ended 原因',
    reasons[reasons.length - 1] === 'ended', `实际 ${reasons[reasons.length - 1]}`);

  check('停止后 isPlaying=false', rsynth.isPlaying === false);
  check('停止后诊断不残留播放态', rsynth.getDiagnostics().isPlaying === false);
  // 停止后必须能立刻重新开始（scoreGain 已重建）
  const cnt = rctx.startedOscillators.length;
  await rsynth.playScore(notes);
  check('停止后可立即重新播放', rctx.startedOscillators.length > cnt,
    `${cnt} -> ${rctx.startedOscillators.length}`);
  check('重播后 scoreGain 仍连通 masterGain',
    rsynth.scoreGain.connections.includes(rsynth.masterGain));
  rsynth.stopScore();
}

console.log(failures === 0
  ? '\n🎉 合成器播放链路测试全部 PASS！'
  : `\n❌ ${failures} 项合成器测试失败`);
process.exit(failures === 0 ? 0 : 1);
