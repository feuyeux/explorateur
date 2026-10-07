/**
 * 「对照原声」播放链路的功能测试：直接驱动真实 App 类。
 * 复用 tests/test_e2e_pipeline.mjs 的 DOM / AudioContext 桩件风格。
 */
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const APP = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (label, cond, detail = '') => {
  if (cond) console.log(`✅ PASS: ${label}`);
  else { fails++; console.log(`❌ FAIL: ${label}${detail ? ` — ${detail}` : ''}`); }
};

class StubElement {
  constructor(tag = 'div', id = '') {
    this.tagName = (tag || 'div').toUpperCase(); this.id = id;
    this.children = []; this.style = {}; this.classList = {
      _s: new Set(),
      add: (...c) => c.forEach(x => this.classList._s.add(x)),
      remove: (...c) => c.forEach(x => this.classList._s.delete(x)),
      contains: (c) => this.classList._s.has(c),
      toggle: (c, on) => { if (on === undefined) { this.classList._s.has(c) ? this.classList._s.delete(c) : this.classList._s.add(c); } else if (on) this.classList._s.add(c); else this.classList._s.delete(c); }
    };
    this.attributes = {}; this._listeners = new Map(); this.innerHTML = ''; this.textContent = '';
    this.disabled = false; this.value = ''; this.max = ''; this.canvas = { width: 800, height: 300, getContext: () => null };
  }
  addEventListener(t, f) { if (!this._listeners) this._listeners = new Map(); const a = this._listeners.get(t) || []; a.push(f); this._listeners.set(t, a); }
  dispatch(t, e = {}) { const a = this._listeners?.get(t) || []; a.forEach(f => f({ type: t, target: this, preventDefault() {}, stopPropagation() {}, currentTarget: this, ...e })); }
  removeEventListener() {} blur() {} focus() {} click() {} setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'disabled') this.disabled = true; }
  getAttribute(k) { return this.attributes[k] ?? null; } removeAttribute(k) { delete this.attributes[k]; if (k === 'disabled') this.disabled = false; }
  hasAttribute(k) { return k in this.attributes; } appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); } remove() {} insertBefore() {} cloneNode() { return new StubElement(); }
  getBoundingClientRect() { return { x: 0, y: 0, width: 100, height: 30, top: 0, left: 0, right: 100, bottom: 30 }; }
  closest() { return null; } matches() { return false; } scrollIntoView() {} getContext() { return null; }
}
const registry = new Map();
const makeElement = (tag, id) => { const e = new StubElement(tag, id); if (id) registry.set(id, e); return e; };
globalThis.document = {
  getElementById: (id) => registry.get(id) || null,
  querySelector: () => new StubElement(), querySelectorAll: () => [],
  createElement: (t) => new StubElement(t), createElementNS: (ns, t) => new StubElement(t),
  body: new StubElement('body'), documentElement: new StubElement('html'),
  addEventListener() {}, activeElement: null,
  createTextNode: () => new StubElement(), createDocumentFragment: () => new StubElement()
};
const html = readFileSync(path.join(APP, 'src', 'index.html'), 'utf8');
for (const m of html.matchAll(/<[^>]*id="([^"]+)"[^>]*>/g)) makeElement('div', m[1]);
// 桩件不会真解析 HTML，这里把按钮初始 innerHTML 按源码补齐，否则初始态断言无意义
{
  const m = html.match(/id="btn-play-original"[^>]*>([\s\S]*?)<\/button>/);
  if (m) registry.get('btn-play-original').innerHTML = m[1].trim();
}

// --- AudioContext 桩件，统计 start/stop ---
let starts = 0, stops = 0;
class Node2 {
  constructor() { this.connections = []; this.gain = { value: 1, setValueAtTime() {}, cancelScheduledValues() {} }; }
  connect(d) { this.connections.push(d); return d; } disconnect() {}
  start() { starts++; } stop() { stops++; }
}
class FakeAudioContext {
  constructor() { this.state = 'running'; this.currentTime = 0; this.sampleRate = 44100; this.destination = new Node2(); }
  createGain() { return new Node2(); } createOscillator() { return new Node2(); } createAnalyser() { return new Node2(); }
  createMediaStreamSource() { return new Node2(); } createBufferSource() { return new Node2(); }
  createBuffer(ch, len, rate) { const d = Array.from({ length: ch }, () => new Float32Array(len)); return { numberOfChannels: ch, length: len, sampleRate: rate, duration: len / rate, getChannelData: (i = 0) => d[i], copyToChannel() {} }; }
  resume() { this.state = 'running'; return Promise.resolve(); }
  decodeAudioData() { return Promise.resolve(this.createBuffer(1, 16000, 16000)); }
  close() { return Promise.resolve(); } destinationMaxChannelCount = 2;
}
globalThis.window = { AudioContext: FakeAudioContext, webkitAudioContext: FakeAudioContext, addEventListener() {}, requestAnimationFrame: () => 0, cancelAnimationFrame() {}, performance: globalThis.performance, devicePixelRatio: 1, location: { href: 'http://localhost/' }, navigator: { mediaDevices: { getUserMedia: () => Promise.reject(new Error('no mic')) } } };
globalThis.AudioContext = FakeAudioContext;
try { Object.defineProperty(globalThis, 'navigator', { value: globalThis.window.navigator, configurable: true, writable: true }); } catch {}

const { App } = await import(path.join(APP, 'src', 'main.js'));
const app = new App();

// 渲染层换成记录器（构造函数里的真实渲染器依赖 canvas，桩件下不可用）
const playheads = [];
const mk = (name) => ({ setPlayhead: (i) => playheads.push([name, i]), clearPlayhead() { playheads.push([name, 'clear']); } });
app.staffRenderer = mk('staff'); app.numberedRenderer = mk('numbered');
app.pianoRollRenderer = { setPlayhead: (i, t) => playheads.push(['pianoroll', i, t]), clearPlayhead: () => playheads.push(['pianoroll', 'clear']) };

// 故意打乱顺序：渲染层 data-note-index 是 quantizedNotes 的原始下标
app.quantizedNotes = [
  { startTime: 2.0, duration: 1, midi: 60 },
  { startTime: 0.0, duration: 1, midi: 62 },
  { startTime: 1.0, duration: 1, midi: 64 },
  { startTime: 1.0, duration: 1, midi: 65 },   // 与 idx2 同刻叠音
  { startTime: 3.0, duration: 1, midi: 67 }
];
app.ensureAudioContext();
const buffer = (app.audioCtx || new FakeAudioContext()).createBuffer(1, 44100, 44100);
app.setLoadedAudio(buffer, 'demo.m4a', 1024, 'm4a');

console.log('\n=== 症状一：对照原声无法停止 ===');
const btn = registry.get('btn-play-original');
check('初始按钮为「对照原声」', /对照原声/.test(btn.innerHTML), btn.innerHTML);

app.playOriginalAudio();
check('首次点击开始播放（start 被调用 1 次）', starts === 1, `starts=${starts}`);
check('按钮切换为停止态文案', /停止原声/.test(btn.innerHTML), btn.innerHTML);
check('按钮带 active 类', btn.classList.contains('active'));

app.playOriginalAudio();
check('再次点击真正停止（stop 被调用）', stops >= 1, `stops=${stops}`);
check('停止后不再重新播放（start 仍为 1 次）', starts === 1, `starts=${starts} ← 若为 2 就是「从头重播」的老 bug`);
check('按钮回到播放态文案', /对照原声/.test(btn.innerHTML), btn.innerHTML);
check('按钮 active 类已移除', !btn.classList.contains('active'));
check('originalAudioSource 已清空', app.originalAudioSource === null);
check('游标定时器已清理（无泄漏）', app.originalCursorTimer === null);

console.log('\n=== 症状二：原声不跟着乐谱走 ===');
playheads.length = 0;
app.playOriginalAudio();
check('播放后已建立游标跟随定时器', app.originalCursorTimer !== null);

const expect = [
  { t: 0.5, idx: 1, why: 't=0.5 命中 startTime=0.0 → 原始下标 1（排序下标会是 0）' },
  { t: 1.5, idx: 2, why: 't=1.5 命中 startTime=1.0 的叠音 → 取第一个原始下标 2' },
  { t: 2.5, idx: 0, why: 't=2.5 命中 startTime=2.0 → 原始下标 0（排序下标会是 3）' },
  { t: 3.5, idx: 4, why: 't=3.5 命中 startTime=3.0 → 原始下标 4' }
];
for (const e of expect) {
  playheads.length = 0;
  app.followScoreWithOriginal(e.t);
  const staff = playheads.find(p => p[0] === 'staff');
  check(`游标跟随 @${e.t}s → 下标 ${e.idx}`, staff && staff[1] === e.idx, `${e.why}；实测 ${JSON.stringify(staff)}`);
}

playheads.length = 0;
app.followScoreWithOriginal(-0.5);
check('播放位置为负（时钟未就绪）时不乱指', playheads.length === 0, JSON.stringify(playheads));
playheads.length = 0;
app.followScoreWithOriginal(0.0);
check('t=0.0 恰好命中首个音符起点即高亮（边界包含）',
  playheads.find(p => p[0] === 'staff')?.[1] === 1, JSON.stringify(playheads.find(p => p[0] === 'staff')));

app.stopOriginalAudio('stopped');
check('停止后清空游标高亮（三个视图）',
  playheads.filter(p => p[1] === 'clear').length === 3, JSON.stringify(playheads));

console.log(fails === 0 ? '\n🎉 「对照原声」播放链路功能测试全部 PASS！' : `\n❌ ${fails} 项功能验证失败`);
process.exit(fails === 0 ? 0 : 1);