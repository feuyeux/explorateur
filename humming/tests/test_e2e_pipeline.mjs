/**
 * 端到端流水线测试 (End-to-End Pipeline Harness)
 *
 * 用最小 DOM + WebAudio 桩驱动**真实的 App 类**，验证：
 *   loadPresetSample() → executePipeline() → 按钮解锁 → toggleScorePlayback()
 *
 * 重点：「试听乐谱」按钮在 index.html 中是 disabled 的，只有当 executePipeline
 * 一路跑到底才会 removeAttribute('disabled')。若中途抛错，按钮永远禁用，
 * 表现为「点了没反应」且控制台无任何提示。本测试正是为了捕获这种静默中断。
 */
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const APP = path.join(ROOT, 'src');
let failures = 0;
const check = (label, cond, detail = '') => {
  if (cond) console.log(`✅ PASS: ${label}`);
  else { failures++; console.log(`❌ FAIL: ${label}${detail ? ` — ${detail}` : ''}`); }
};

// ---------------------------------------------------------------- DOM 桩
class StubClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...c) { c.forEach(x => this.set.add(x)); }
  remove(...c) { c.forEach(x => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, f) { f ? this.set.add(c) : this.set.delete(c); }
}
class StubElement {
  constructor(tag = 'div', id = '') {
    this.tagName = String(tag).toUpperCase();
    this.id = id;
    this.className = '';
    this.classList = new StubClassList(this);
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.children = [];
    this._text = '';
    this._html = '';
    this.disabled = false;
    this.value = '';
    this.clientWidth = 1180;
    this.clientHeight = 280;
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  getContext() { return new Proxy({}, { get: () => () => {} }); }
  querySelector() { return new StubElement(); }
  querySelectorAll() { return []; }
  addEventListener(type, fn) {
    if (!this._listeners) this._listeners = new Map();
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  /** 触发已注册的事件监听，模拟真实 DOM 事件流 */
  dispatch(type, event = {}) {
    const list = this._listeners?.get(type) || [];
    const e = { type, target: this, preventDefault() {}, ...event };
    for (const fn of list) fn(e);
    return list.length;
  }
  removeEventListener() {}
  blur() { return this.dispatch('blur'); }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'disabled') this.disabled = true;
  }
  getAttribute(k) { return this.attributes[k] ?? null; }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'disabled') this.disabled = false; }
  hasAttribute(k) { return k in this.attributes; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); }
  remove() {}
  insertBefore() {}
  cloneNode() { return new StubElement(); }
  getBoundingClientRect() { return { x: 0, y: 0, width: 100, height: 30, top: 0, left: 0, right: 100, bottom: 30 }; }
  focus() {}
  click() {}
  closest() { return null; }
  matches() { return false; }
  scrollIntoView() {}
}

const registry = new Map();
function makeElement(tag, id) {
  const el = new StubElement(tag, id);
  if (id) registry.set(id, el);
  return el;
}

globalThis.document = {
  getElementById: (id) => registry.get(id) || null,
  querySelector: () => new StubElement(),
  querySelectorAll: () => [],
  createElement: (t) => new StubElement(t),
  createElementNS: (ns, t) => new StubElement(t),
  body: new StubElement('body'),
  documentElement: new StubElement('html'),
  addEventListener() {},
  activeElement: null,
  createTextNode: () => new StubElement(),
  createDocumentFragment: () => new StubElement()
};

// 预注册 index.html 中真实存在的所有 id
const html = readFileSync(path.join(APP, 'index.html'), 'utf8');
for (const m of html.matchAll(/<[^>]*id="([^"]+)"[^>]*>/g)) {
  const [, id] = m;
  const el = makeElement('div', id);
  if (/\bdisabled\b/.test(m[0])) el.setAttribute('disabled', '');
}
for (const id of ['record-monitor-canvas', 'pianoroll-canvas']) makeElement('canvas', id);

// ---------------------------------------------------------------- WebAudio 桩
let ctxCreated = 0;
class Param {
  constructor(v = 0) { this.value = v; }
  setValueAtTime() { return this; }
  linearRampToValueAtTime() { return this; }
  exponentialRampToValueAtTime() { return this; }
  cancelScheduledValues() { return this; }
}
class Node2 {
  constructor() { this.connections = []; this.gain = new Param(1); this.frequency = new Param(440); this.type = 'sine'; }
  connect(d) { this.connections.push(d); return d; }
  disconnect() {}
  start() {}
  stop() {}
}
class FakeAudioContext {
  constructor() {
    ctxCreated++;
    this.state = 'running';
    this.currentTime = 0;
    this.sampleRate = 44100;
    this.destination = new Node2();
    this.startedNodes = 0;
  }
  createGain() { return new Node2(); }
  createOscillator() { const n = new Node2(); const s = n.start.bind(n); n.start = () => { this.startedNodes++; s(); }; return n; }
  createAnalyser() { return new Node2(); }
  createMediaStreamSource() { return new Node2(); }
  createBufferSource() { return new Node2(); }
  createBuffer(ch, len, rate) {
    const data = Array.from({ length: ch }, () => new Float32Array(len));
    return {
      numberOfChannels: ch, length: len, sampleRate: rate,
      duration: len / rate,
      getChannelData: (i = 0) => data[i],
      copyToChannel: (src, i = 0) => { data[i].set(src.subarray ? src.subarray(0, len) : src.slice(0, len)); }
    };
  }
  resume() { this.state = 'running'; return Promise.resolve(); }
  decodeAudioData() { return Promise.resolve(this.createBuffer(1, 16000, 16000)); }
  close() { return Promise.resolve(); }
  destinationMaxChannelCount = 2;
}
globalThis.window = {
  AudioContext: FakeAudioContext,
  webkitAudioContext: FakeAudioContext,
  addEventListener() {},
  requestAnimationFrame: () => 0,
  cancelAnimationFrame() {},
  performance: globalThis.performance,
  devicePixelRatio: 1,
  location: { href: 'http://localhost/' },
  navigator: { mediaDevices: { getUserMedia: () => Promise.reject(new Error('no mic in test')) } }
};
globalThis.AudioContext = FakeAudioContext;
// Node 26 的 globalThis.navigator 只有 getter，改用 defineProperty
try {
  Object.defineProperty(globalThis, 'navigator', {
    value: globalThis.window.navigator, configurable: true, writable: true
  });
} catch { /* 已有 navigator 则忽略 */ }

// ---------------------------------------------------------------- 运行真实 App
const { App } = await import(path.join(APP, 'main.js'));

console.log('=== 启动 App ===');
let app;
try {
  app = new App();
  check('App 构造成功', !!app);
} catch (e) {
  check('App 构造成功', false, `${e.message}`);
  console.log('\n❌ 构造失败，后续测试中止');
  process.exit(1);
}

// 开机即应完成 BPM 控件初始化：以内部状态为准，滑杆与数字框同步
{
  const initNum = registry.get('input-bpm-num');
  const initSlider = registry.get('input-bpm');
  check('开机 BPM 数字框已按内部状态初始化',
    initNum && String(initNum.value) === String(app.segmenter.bpm),
    `数字框=${initNum?.value} segmenter=${app.segmenter.bpm}`);
  check('开机 BPM 滑杆已按内部状态初始化',
    initSlider && String(initSlider.value) === String(app.segmenter.bpm),
    `滑杆=${initSlider?.value} segmenter=${app.segmenter.bpm}`);
}

console.log('\n=== 预置样本 → 完整流水线 ===');
const playBtn = registry.get('btn-play-synth');
check('试听按钮初始为 disabled', playBtn.hasAttribute('disabled'));

let pipelineError = null;
try {
  await app.loadPresetSample('twinkle');
  // executePipeline 是 fire-and-forget，等待其完成
  await new Promise(r => setTimeout(r, 3000));
} catch (e) {
  pipelineError = e;
}
if (pipelineError) {
  console.log('\n--- 完整错误堆栈 ---');
  console.log(pipelineError.stack);
  console.log('--- end ---\n');
}
check('loadPresetSample 未抛出', !pipelineError, pipelineError?.message);
check('识别出音符', (app.quantizedNotes?.length || 0) > 0, `音符数=${app.quantizedNotes?.length}`);
check('调性已推断', !!app.keyInfo?.bestKey, `bestKey=${app.keyInfo?.bestKey}`);

console.log('\n=== 按钮解锁（点击无反应的第一嫌疑） ===');
check('试听按钮已解除 disabled', !playBtn.hasAttribute('disabled'),
  playBtn.hasAttribute('disabled') ? '仍是 disabled —— 流水线中途中断' : '');
check('MIDI 导出按钮已解锁', !registry.get('btn-export-midi').hasAttribute('disabled'));
check('MusicXML 导出按钮已解锁', !registry.get('btn-export-xml').hasAttribute('disabled'));

console.log('\n=== 点击试听（toggleScorePlayback） ===');
let toggleErr = null;
try {
  await app.toggleScorePlayback();
  await new Promise(r => setTimeout(r, 200));
} catch (e) {
  toggleErr = e;
}
check('toggleScorePlayback 未抛错', !toggleErr, toggleErr?.message);
check('synth 已创建', !!app.synth);
check('AudioContext 已创建', ctxCreated > 0, `ctxCreated=${ctxCreated}`);
check('进入播放状态 (isPlaying)', app.synth?.isPlaying === true, `isPlaying=${app.synth?.isPlaying}`);
check('产生了发声音符', app.synth?.ctx?.startedNodes > 0 || app.audioCtx?.startedNodes > 0,
  `startedNodes=${app.synth?.ctx?.startedNodes}`);
check('按钮文案切换为停止', /停止/.test(playBtn.innerHTML), playBtn.innerHTML.slice(0, 40));
const statusEl = registry.get('global-status-msg');
check('状态栏回报播放详情（诊断无声问题）',
  /正在试听/.test(statusEl.textContent) && /音频状态=/.test(statusEl.textContent),
  `status="${statusEl.textContent}"`);

console.log('\n=== 再次点击应停止 ===');
await app.toggleScorePlayback();
await new Promise(r => setTimeout(r, 100));
check('停止后 isPlaying=false', app.synth?.isPlaying === false);
check('停止后状态栏有反馈', /已停止试听/.test(statusEl.textContent), statusEl.textContent);
check('按钮文案恢复为试听', /试听/.test(playBtn.innerHTML), playBtn.innerHTML.slice(0, 40));

console.log('\n=== 单音符试听（点击乐谱音符） ===');
app.selectNote(0, true);
await new Promise(r => setTimeout(r, 100));
check('单音符试听未抛错', true);

// ---------------------------------------------------------------------------
// BPM 数值输入：滑杆与数字框必须双向同步，且越界值被夹紧
// ---------------------------------------------------------------------------
console.log('\n=== BPM 数值输入双向同步 ===');
{
  const slider = registry.get('input-bpm');
  const num = registry.get('input-bpm-num');
  check('滑杆与数字输入框均已绑定事件',
    (slider?._listeners?.get('input')?.length || 0) > 0 &&
    (num?._listeners?.get('change')?.length || 0) > 0,
    `slider.input=${slider?._listeners?.get('input')?.length || 0} num.change=${num?._listeners?.get('change')?.length || 0}`);

  // 数字框输入 → 滑杆同步
  num.value = '132';
  num.dispatch('change');
  check('数字框输入后 segmenter.bpm 已更新', app.segmenter.bpm === 132, `实际 ${app.segmenter.bpm}`);
  check('数字框输入后滑杆同步', String(slider.value) === '132', `滑杆=${slider.value}`);
  check('节拍器 BPM 同步', app.metronome?.bpm === 132 || app.metronome?.bpm == null, `节拍器=${app.metronome?.bpm}`);

  // 滑杆拖动 → 数字框同步
  slider.value = '77';
  slider.dispatch('input');
  check('滑杆拖动后 segmenter.bpm 已更新', app.segmenter.bpm === 77, `实际 ${app.segmenter.bpm}`);
  check('滑杆拖动后数字框同步', String(num.value) === '77', `数字框=${num.value}`);

  // 越界夹紧
  num.value = '9999';
  num.dispatch('change');
  check('超上限输入被夹紧到 180', app.segmenter.bpm === 180, `实际 ${app.segmenter.bpm}`);
  num.value = '1';
  num.dispatch('change');
  check('低于下限输入被夹紧到 50', app.segmenter.bpm === 50, `实际 ${app.segmenter.bpm}`);

  // 非法输入回落，不应把 BPM 变成 NaN
  num.value = 'abc';
  num.dispatch('change');
  check('非法输入不产生 NaN',
    Number.isFinite(app.segmenter.bpm), `实际 ${app.segmenter.bpm}`);

  num.value = '100';
  num.dispatch('change');
  check('恢复 100 BPM 正常', app.segmenter.bpm === 100, `实际 ${app.segmenter.bpm}`);
}

// ---------------------------------------------------------------------------
// 试听按钮状态与真实播放状态不得失同步
// ---------------------------------------------------------------------------
console.log('\n=== 试听按钮状态同步 ===');
{
  const playBtn = registry.get('btn-play-synth');
  await app.toggleScorePlayback();
  check('播放中按钮显示停止', /停止/.test(playBtn.innerHTML), `实际 "${playBtn.innerHTML}"`);
  check('播放中 synth.isPlaying=true', app.synth.isPlaying === true);

  await app.toggleScorePlayback();
  check('停止后按钮恢复试听', /试听乐谱/.test(playBtn.innerHTML), `实际 "${playBtn.innerHTML}"`);
  check('停止后 synth.isPlaying=false', app.synth.isPlaying === false);
  check('停止后无残留振荡器', app.synth.activeOscillators.length === 0,
    `残留 ${app.synth.activeOscillators.length}`);

  // 停止 → 再播放必须仍然能出声（scoreGain 已重建、上下文仍 running）
  const before = app.synth.activeOscillators.length;
  await app.toggleScorePlayback();
  check('停止后重新试听仍能播放', app.synth.isPlaying === true);
  check('重新试听产生了振荡器', app.synth.activeOscillators.length > before,
    `${before} -> ${app.synth.activeOscillators.length}`);
  app.synth.stopScore('stopped');
  check('最终已停止', app.synth.isPlaying === false);
}

console.log(failures === 0
  ? '\n🎉 端到端流水线测试全部 PASS！'
  : `\n❌ ${failures} 项端到端测试失败`);
process.exit(failures === 0 ? 0 : 1);
