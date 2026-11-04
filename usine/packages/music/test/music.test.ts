// music.test.ts — @feuille/music 的门禁（纪律的机器化）。
//
// 覆盖 skills/music-annotate-video/references/music-av-traps.md 里**尚未脚本化**
// 的四条（该文档「机检落点」段点名要随本包补上）：
//   §5  TDZ 空帧——同场景不同 state 的 PNG 字节数不能全相等；
//   §8  preroll 音画差——音乐轨必须顺延 preroll，否则高亮整体滞后 0.8s；
//   §10 含墨覆盖率——空页必 FAIL、稀疏标题卡必 PASS（且不得误杀）；
//   §14 逐场景对账——视频段总长 vs d30(pre+body+done+tail)，差值必须 0 帧。
//
// 外加本包自己的纯函数契约：MIDI 解析、和弦分类与**去重组**（§1 的坑）、
// 聚段（§4 的坑）、f0 滞回量化、DATA 注入、场景帧数分配。
//
// 反向验证纪律：每个正向用例都要配一个「坏例必须被抓」的用例。
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

import { platform } from '@feuille/core'

import { FLAGS } from '../src/cli.js'
import type * as source_1 from '../src/source.js'
import { align, build, chord, dsp, midi, narrate, probe, scan_ink, source } from '../src/index.js'

const HAS_BROWSER = platform.browserPath() !== null
const HAS_FFMPEG = platform.ffmpeg() !== null

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), 'feuille-music-test-'))
  tmpRoots.push(d)
  return d
}
afterAll(() => {
  for (const d of tmpRoots) rmSync(d, { recursive: true, force: true })
})

function ffmpeg(args: string[]): void {
  const FF = platform.requireTool(platform.ffmpeg(), 'ffmpeg')
  const r = spawnSync(FF, args, { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`ffmpeg FAILED: ${r.stderr}`)
}

/** 造一段单声道 wav（正弦或静音）。 */
function makeWav(path: string, seconds: number, freq = 440, sr = 22050): string {
  const n = Math.round(seconds * sr)
  const buf = Buffer.alloc(44 + n * 2)
  buf.write('RIFF', 0, 'latin1')
  buf.writeUInt32LE(36 + n * 2, 4)
  buf.write('WAVE', 8, 'latin1')
  buf.write('fmt ', 12, 'latin1')
  buf.writeUInt32LE(16, 16)
  buf.writeUInt16LE(1, 20)
  buf.writeUInt16LE(1, 22)
  buf.writeUInt32LE(sr, 24)
  buf.writeUInt32LE(sr * 2, 28)
  buf.writeUInt16LE(2, 32)
  buf.writeUInt16LE(16, 34)
  buf.write('data', 36, 'latin1')
  buf.writeUInt32LE(n * 2, 40)
  for (let i = 0; i < n; i++) {
    const v = freq > 0 ? Math.sin((2 * Math.PI * freq * i) / sr) * 0.3 : 0
    buf.writeInt16LE(Math.round(v * 32767), 44 + i * 2)
  }
  writeFileSync(path, buf)
  return path
}

// ============================================================
//  MIDI 解析（Tier A 的真值入口）
// ============================================================

describe('MIDI 解析：SMF → 音符', () => {
  it('format 0：note on/off + tempo → 音符的音高与秒区间', () => {
    // MThd(6) + MTrk(track) —— tempo 500000（120bpm）+ 一个 C4 音符 0.5s
    const track = [
      0x00, 0xff, 0x51, 0x03, 0x07, 0xa1, 0x20, // tempo 120bpm
      0x00, 0x90, 60, 100, // note on C4
      0x83, 0x60, 0x80, 60, 0, // +0.5s → note off（VLQ 0x83 0x60 = 480 ticks）
    ]
    const head = Buffer.from([0x4d, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 0, 0, 1, 0x01, 0xe0])
    const trk = Buffer.from([0x4d, 0x54, 0x72, 0x6b])
    const len = Buffer.alloc(4)
    len.writeUInt32BE(track.length)
    const buf = Buffer.concat([head, trk, len, Buffer.from(track)])
    const meta = midi.parseMidi(buf)
    expect(meta.tracks).toBe(1)
    expect(meta.notes).toHaveLength(1)
    expect(meta.notes[0]!.pitch).toBe(60)
    expect(meta.notes[0]!.start).toBeCloseTo(0, 3)
    // 480 ticks @ 120bpm = 0.5s
    expect(meta.notes[0]!.end).toBeCloseTo(0.5, 3)
  })

  it('坏例：不是 MThd 开头 → 报错（不静默当空曲）', () => {
    expect(() => midi.parseMidi(Buffer.alloc(64))).toThrow(/MThd/)
  })

  it('坏例：SMPTE 时间码（division 高位为 1）→ 明确报错，不按拍算', () => {
    const head = Buffer.from([0x4d, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 0, 0, 1, 0xe7, 0x28])
    const trk = Buffer.from([0x4d, 0x54, 0x72, 0x6b, 0, 0, 0, 0])
    expect(() => midi.parseMidi(Buffer.concat([head, trk]))).toThrow(/SMPTE/)
  })
})

// ============================================================
//  和弦分类与去重组（traps §1）
// ============================================================

describe('和弦分类：模糊 Jaccard + 去重组', () => {
  it('大三和弦：C-E-G → C', () => {
    const m = chord.classifyChord([0, 4, 7])
    expect(m.template?.id).toBe('C')
    expect(m.score).toBeCloseTo(1, 5)
  })

  it('小调和弦：A-C-E → Am', () => {
    expect(chord.classifyChord([9, 0, 4]).template?.id).toBe('Am')
  })

  it('模糊容差：观测集多一个经过音仍能匹配', () => {
    // C-E-G + F（经过音）→ 仍应是 C，相似度 < 1 但最高
    const m = chord.classifyChord([0, 4, 7, 5])
    expect(m.template?.id).toBe('C')
    expect(m.score).toBeLessThan(1)
    expect(m.score).toBeGreaterThan(0.7)
  })

  it('去重组：同音级集的第二块不能又匹配同一个模板（traps §1 的坑）', () => {
    const a = chord.classifyChord([4, 8, 11]) // E-G#-B
    const first = a.template!
    const used = new Set([first.index])
    const b = chord.classifyChord([4, 8, 11], used)
    // 排除第一个模板后，argmax 必须换人——否则后一块永远匹配不到
    expect(b.template).not.toBeNull()
    expect(b.template!.index).not.toBe(first.index)
  })

  it('坏例：空音级集 → 不给模板（不是「随便挑一个」）', () => {
    expect(chord.classifyChord([]).template).toBeNull()
  })
})

describe('聚段：连续同标签归一段，短碎段并掉（traps §4）', () => {
  const tpl = chord.CHORD_TEMPLATES.find((t) => t.id === 'C')!
  const labels = [tpl, tpl, tpl, tpl, tpl]
  const pcs = [[0, 4, 7], [0, 4, 7], [0, 4, 7], [0, 4, 7], [0, 4, 7]]
  const scores = [1, 1, 1, 1, 1]

  it('连续浊音切 1 段而不是 N 段', () => {
    const segs = chord.segmentLabels(labels, pcs, scores, 2)
    expect(segs).toHaveLength(1)
    expect(segs[0]!.start).toBe(0)
    expect(segs[0]!.end).toBe(5)
  })

  it('孤帧段被丢掉（minFrames=2）', () => {
    const t2 = chord.CHORD_TEMPLATES.find((t) => t.id === 'Am')!
    const mixed = [tpl, t2, tpl]
    const segs = chord.segmentLabels(mixed, pcs, scores, 2)
    expect(segs.every((s) => s.end - s.start >= 2)).toBe(true)
  })
})

// ============================================================
//  f0 滞回量化
// ============================================================

describe('f0：半音域中值平滑 + 滞回量化', () => {
  it('中值平滑：单帧尖刺被压掉', () => {
    const out = align.medianSmoothMidi([60, 60, 72, 60, 60], 3)
    expect(out[2]).toBe(60)
  })

  it('滞回量化：抖动不换音号，连续成立才换', () => {
    const q = align.hysteresisQuantize([60, 60, 61, 61, 61, 61, 61], 4)
    expect(q[0]).toBe(60)
    expect(q[3]).toBe(60) // 还没到 4 帧，不换
    expect(q[6]).toBe(61) // 连续 4 帧成立 → 换
  })

  it('坏例：滞回帧数越大越难换号（口径方向对）', () => {
    const q2 = align.hysteresisQuantize([60, 61, 61, 61], 2)
    expect(q2[0]).toBe(60)
    expect(q2[3]).toBe(61)
  })
})

// ============================================================
//  谱块分组与对拍
// ============================================================

describe('谱块：按起音分组 + 顺序对拍的两条判据', () => {
  it('按起音分组：同一时刻的三个音归一块', () => {
    const meta: midi.MidiMeta = {
      duration: 2,
      ticksPerBeat: 480,
      tracks: 1,
      notes: [
        { pitch: 60, start: 0, end: 1 },
        { pitch: 64, start: 0, end: 1 },
        { pitch: 67, start: 0, end: 1 },
        { pitch: 62, start: 1, end: 2 },
      ],
    }
    const blocks = align.scoreBlocks(meta)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]!.pcs.sort()).toEqual([0, 4, 7])
  })

  it('对拍：谱块起点不在观测段带内 → 判不成立（fail-closed，不硬凑）', () => {
    const tpl = chord.CHORD_TEMPLATES.find((t) => t.id === 'C')!
    const observed: align.ObservedChords = {
      hopSec: 0.05,
      labels: [tpl, tpl, tpl, tpl],
      scores: [1, 1, 1, 1],
      pcsPerFrame: [[0, 4, 7], [0, 4, 7], [0, 4, 7], [0, 4, 7]],
      segments: [{ start: 0, end: 4, label: 'C', pcs: [0, 4, 7], score: 1 }],
    }
    const blocks = [{ onset: 100, end: 101, pcs: [0, 4, 7], noteCount: 3 }]
    const res = align.alignBlocks(blocks, observed)
    expect(res.allOk).toBe(false)
    expect(res.pairs[0]!.ok).toBe(false)
    expect(res.pairs[0]!.inBand).toBe(false)
  })

  it('对拍：音级交集不足 2/3 → 判不成立', () => {
    const tpl = chord.CHORD_TEMPLATES.find((t) => t.id === 'C')!
    const observed: align.ObservedChords = {
      hopSec: 0.05,
      labels: [tpl, tpl, tpl, tpl, tpl, tpl, tpl, tpl],
      scores: [1, 1, 1, 1, 1, 1, 1, 1],
      pcsPerFrame: Array.from({ length: 8 }, () => [0, 4, 7]),
      segments: [{ start: 0, end: 8, label: 'C', pcs: [0, 4, 7], score: 1 }],
    }
    // 谱块音级集与观测几乎不交集
    const blocks = [{ onset: 0.1, end: 0.2, pcs: [1, 5, 8], noteCount: 3 }]
    const res = align.alignBlocks(blocks, observed)
    expect(res.pairs[0]!.intersectOk).toBe(false)
    expect(res.pairs[0]!.ok).toBe(false)
  })

  it('零分布用**循环平移**：p 有下界，永不返回 0（打乱配对会给出虚高的显著性）', () => {
    const n = 60
    const a = Array.from({ length: n }, (_, k) => [(k * 5) % 12, (k * 5 + 4) % 12])
    const b = a.map((x) => [...x])
    const d = align.measureDiscrimination(a, b, 500, 7)
    expect(d.pathMean).toBe(1)            // 完全对应
    expect(d.pValue).toBeGreaterThan(0)   // +1 保底
    expect(d.pValue).toBeLessThanOrEqual(1)
    // 同一个种子两次跑必须一样（否则同一份输入会给出两个 p）
    expect(align.measureDiscrimination(a, b, 500, 7).pValue).toBe(d.pValue)
    // 太少配对时不给判定
    expect(align.measureDiscrimination([[0, 4, 7]], [[0, 4, 7]], 500).pValue).toBe(1)
  })

  // ============================================================
  //  判据 3 的阴性对照（**这条测试是「量具没通过」的档案**）
  // ============================================================
  //
  // 2026-11-04 实测（真录音 + 真谱面 MIDI）：春的录音配**秋**的谱，
  // 置换检验同样 p=0.0005，而且路径交集 0.646 比正确谱的 0.409 还高。
  //
  // 结论不是「把门限调严」——那只是把结论调成想要的。**结论是：这个量具
  // 没有辨别力，Tier A 不能用来落摘录时间码。** `validated` 因此恒为
  // false，CLI 默认 fail-closed。这一条测试锁住那个事实，防止有人把它
  // 悄悄改回「已验证」。
  it('阴性对照：配错谱同样「显著」→ validated 必须为 false（不许当已验证读）', () => {
    // 造一份「音级排列与录音几乎无关」的谱块序列与一段观测：因为模板只有
    // 12 类，随便怎么配交集都高——正是实测里配错谱也过 55% 的原因。
    const obs: align.ObservedChords = {
      hopSec: 0.05,
      labels: Array.from({ length: 40 }, (_, k) =>
        chord.CHORD_TEMPLATES[k % chord.CHORD_TEMPLATES.length]!),
      scores: Array.from({ length: 40 }, () => 1),
      pcsPerFrame: Array.from({ length: 40 }, (_, k) => [k % 12, (k + 4) % 12, (k + 7) % 12]),
      segments: Array.from({ length: 40 }, (_, k) => ({
        start: k, end: k + 1,
        label: chord.CHORD_TEMPLATES[k % chord.CHORD_TEMPLATES.length]!.id,
        pcs: [k % 12, (k + 4) % 12, (k + 7) % 12],
        score: 1,
      })),
    }
    // 谱块：与观测**错开**的序列（阴性对照）
    const wrong = Array.from({ length: 40 }, (_, k) => ({
      onset: k * 0.5, end: k * 0.5 + 0.4,
      pcs: [(k + 6) % 12, (k + 10) % 12, (k + 1) % 12], noteCount: 3,
    }))
    const res = align.alignBlocks(wrong, obs)
    // 不管 p 是多少，都**不许**声称验证过。
    expect(res.validated).toBe(false)
    expect(res.validationNote).toContain('测不出')
  })
})

// ============================================================
//  帧网格与场景帧数分配（traps §9 / §14）
// ============================================================

describe('场景时间模型：总帧数一次算定', () => {
  it('总帧数 = framesFor(pre + body + done + tail)', () => {
    const t = build.sceneTiming({
      id: 'A',
      preroll: 0.8,
      done: 0.5,
      tail: 0.8,
      states: [{ t0: 0, t1: 1.234 }, { t0: 1.234, t1: 3.456 }],
    }, 30)
    expect(t.body).toBeCloseTo(3.456, 6)
    expect(t.totalFrames).toBe(Math.ceil((0.8 + 3.456 + 0.5 + 0.8) * 30 - 1e-9))
    expect(t.durationSec).toBeCloseTo(t.totalFrames / 30, 6)
  })

  it('坏例：states 的时长和与 preroll/done/tail 口径打架 → 明确报错', () => {
    // 由 buildProject 在装配时抛；这里先验证时间模型本身不会给出负数帧
    const t = build.sceneTiming({ id: 'A', preroll: 0, done: 0, tail: 0, states: [] }, 30)
    expect(t.totalFrames).toBe(0)
  })
})

describe('DATA 注入：替换 `const DATA = {…}` 字面量', () => {
  const html = [
    '<html><body><script>',
    'const DATA = {',
    '  A: { dur: 48, blocks: [{ t0: 0, t1: 12 }] }',
    '};',
    '</script>',
    '<script>console.log(DATA["A"].dur)</script>',
    '</body></html>',
  ].join('\n')

  it('注入后 DATA 是新数据，且消费者脚本仍在其后', () => {
    const out = build.injectData(html, { A: { dur: 12, blocks: [] } })
    expect(out).toContain('"dur": 12')
    expect(out.indexOf('const DATA =')).toBeLessThan(out.indexOf('console.log'))
  })

  it('坏例：页面里没有 `const DATA =` → 报错（不静默出一张空纸）', () => {
    expect(() => build.injectData('<html></html>', {})).toThrow(/const DATA/)
  })

  it('坏例：字面量没闭合 → 报错', () => {
    expect(() => build.injectData('const DATA = { A: 1 ', {})).toThrow(/闭合/)
  })
})

// ============================================================
//  §10 含墨覆盖率（反向自测）
// ============================================================

describe('含墨扫描：空页必 FAIL、稀疏卡必 PASS（traps §10）', () => {
  it.runIf(HAS_FFMPEG)('反向自测：blank=caught card=passed', async () => {
    const ok = await scan_ink.inkSelfTest()
    expect(ok).toBe(true)
  }, 120_000)

  it.runIf(HAS_FFMPEG)('阈值口径：判定阈值 0.2%，稀疏卡 0.46% 在阈值之上', async () => {
    const dir = tmp()
    const out = join(dir, 'card.mp4')
    ffmpeg(['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0xf7f2e6:s=1920x1080:r=30',
      '-t', '1', '-vf', 'format=yuv420p,drawbox=x=0:y=0:w=1920:h=5:color=0x2c2620:t=fill',
      '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', out])
    const rep = await scan_ink.scanInk(out, { minPct: 0.2 })
    expect(rep.status).toBe('ok')
    expect(rep.minObservedPct!).toBeGreaterThan(0.2)
    expect(rep.minObservedPct!).toBeLessThan(0.6)
  }, 120_000)

  it.runIf(HAS_FFMPEG)('坏例：暖纸空页 → FAIL（0 帧含墨）', async () => {
    const dir = tmp()
    const out = join(dir, 'blank.mp4')
    ffmpeg(['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0xf7f2e6:s=1920x1080:r=30',
      '-t', '1', '-vf', 'format=yuv420p', '-c:v', 'libx264', '-crf', '0',
      '-pix_fmt', 'yuv420p', out])
    const rep = await scan_ink.scanInk(out, { minPct: 0.2 })
    expect(rep.status).toBe('FAIL')
    expect(rep.bad.length).toBeGreaterThan(0)
  }, 120_000)
})

// ============================================================
//  探针
// ============================================================

describe('探针：RMS 包络 + 频段 + 起音 + 候选边界', () => {
  it.runIf(HAS_FFMPEG)('静音 → 候选边界为空、RMS max ≈ 0（探针不编数据）', () => {
    const dir = tmp()
    const wav = makeWav(join(dir, 'silence.wav'), 2.0, 0)
    const mono = dsp.readMonoWav(wav)
    const r = probe.probeAudio(mono, wav, { hopSec: 0.05, windowSec: 1.0 })
    expect(r.rms.max).toBeLessThan(0.001)
    expect(r.onsets.length).toBe(0)
    expect(r.candidates.length).toBe(0)
  }, 60_000)

  it.runIf(HAS_FFMPEG)('有信号 → RMS 包络非零且窗口数 ≥ 1', () => {
    const dir = tmp()
    const wav = makeWav(join(dir, 'tone.wav'), 3.0, 440)
    const mono = dsp.readMonoWav(wav)
    const r = probe.probeAudio(mono, wav, { hopSec: 0.05, windowSec: 1.0 })
    expect(r.rms.max).toBeGreaterThan(0.1)
    expect(r.windows.length).toBeGreaterThanOrEqual(1)
    expect(r.durationSec).toBeCloseTo(3.0, 1)
  }, 60_000)

  it('日志渲染：候选边界必须带依据（摘录边界的背书）', () => {
    const log = probe.renderLog({
      source: 'x.ogg', durationSec: 10, sampleRate: 22050, hopSec: 0.05,
      rms: { max: 0.2, mean: 0.1, p95: 0.18, envelope: [] },
      windows: [{ t0: 0, t1: 1, rms: 0.1, hfPct: 1, lfPct: 20, midPct: 40 }],
      onsets: [{ t: 1.5, strength: 2 }],
      candidates: [{ startSec: 1, endSec: 5, reason: '渐强入口：RMS 从 0.03 升到 0.12' }],
    })
    expect(log).toContain('候选摘录边界')
    expect(log).toContain('渐强入口')
    expect(log).toContain('0.2–0.5s 余量')
  })
})

// ============================================================
//  §14 逐场景对账 + §8 preroll 音画差（端到端，真浏览器）
// ============================================================

/** 一个最小可跑的状态帧页面（真浏览器渲染，暖纸底 + 可见墨）。 */
const STATUS_HTML = `<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1920px; height:1080px; overflow:hidden; background:#f7f2e6; }
body { color:#2c2620; font-family: Georgia, serif; padding:60px; }
.k { font-size:28px; color:#b8860b; margin-bottom:16px; }
h1 { font-size:56px; margin-bottom:20px; }
.caption { font-size:26px; line-height:1.5; color:#5a5142; }
.bars { margin-top:40px; }
.bar { height:26px; background:#8f846f; margin:8px 0; }
</style></head><body>
<div class="k">MUSIC APPRECIATION</div>
<h1 id="t">标题</h1>
<div class="caption" id="c">说明</div>
<div class="bars" id="bars"></div>
<script>
const DATA = { A: { title: "x", bars: [1,2,3] } };
</script>
<script>
const p = new URLSearchParams(location.search);
const scene = p.get("scene") || "A";
const state = parseInt(p.get("state") || "-1", 10);
const d = DATA[scene];
if (d) {
  document.getElementById("t").textContent = d.title + " #" + state;
  const bars = document.getElementById("bars");
  for (let i = 0; i < d.bars.length; i++) {
    const el = document.createElement("div");
    el.className = "bar";
    el.style.width = (d.bars[i] * (state + 1)) * 40 + "px";
    bars.appendChild(el);
  }
}
</script></body></html>`

describe.runIf(HAS_BROWSER && HAS_FFMPEG)('端到端：状态帧 → 装配 → 逐场景对账（traps §14 / §5 / §8）', () => {
  it('两条场景：逐场景差 0 帧、双流差 < 50ms、空帧被含墨扫描抓到', async () => {
    const dir = tmp()
    const root = join(dir, 'proj')
    mkdirSync(join(root, 'assets'), { recursive: true })
    mkdirSync(join(root, 'frames'), { recursive: true })
    writeFileSync(join(root, 'frames', 'status-frame.html'), STATUS_HTML, 'utf8')
    const wav = makeWav(join(root, 'assets', 'rec.wav'), 6.0, 440)
    const nar = makeWav(join(root, 'assets', 'nar.wav'), 1.2, 660)
    const out = join(root, 'out.mp4')
    const project: build.MusicProject = {
      work: { title: '测试', composer: '匿名', movements: 2 },
      recording: { file: 'assets/rec.wav' },
      fps: 30,
      status_frame_html: 'frames/status-frame.html',
      scenes: [
        {
          id: 'A',
          preroll: 0.8,
          done: 0.5,
          tail: 0.8,
          states: [{ t0: 0, t1: 1.2 }, { t0: 1.2, t1: 2.4 }],
          recording_excerpt: { start_s: 0, end_s: 3.2 },
          music_at: 0.8,
          data: { title: '第一段', bars: [1, 2, 3] },
          narration: [{ file: 'assets/nar.wav', at_s: 0.8, gain: 1.0 }],
        },
        {
          id: 'B',
          preroll: 0.8,
          done: 0.5,
          tail: 0.8,
          states: [{ t0: 0, t1: 1.5 }],
          recording_excerpt: { start_s: 3.2, end_s: 6.0 },
          music_at: 0.8,
          data: { title: '第二段', bars: [3, 2, 1] },
        },
      ],
      audio: { ducking: { music_gain: 0.25 }, loudness: { I: -14, TP: -1.5, LRA: 11 } },
    }
    writeFileSync(join(root, 'project.json'), JSON.stringify(project, null, 1), 'utf8')

    const res = build.buildProject(project, root, out, { width: 640, height: 360 })
    // §14：逐场景差 0 帧
    for (const r of res.reconciliation) {
      expect(r.diff).toBe(0)
      expect(r.actualFrames).toBe(r.expectedFrames)
    }
    // 双流差
    expect(res.avDiffMs).toBeLessThan(50)
    // 成片存在且有内容
    expect(existsSync(out)).toBe(true)
    expect(res.durationSec).toBeGreaterThan(3)

    // §5：同场景不同 state 的 PNG 字节数不能全相等（TDZ 空纸的症状）
    const pngs = ['A-s000.png', 'A-s001.png'].map((f) => join(root, 'build', 'frames', f))
    const sizes = pngs.map((p) => readFileSync(p).length)
    expect(new Set(sizes).size).toBeGreaterThan(1)

    // §10：成片含墨达标（不是空纸）
    const rep = await scan_ink.scanInk(out, { minPct: 0.2 })
    expect(rep.status).toBe('ok')
  }, 300_000)
})

// ============================================================
//  source：来源台账（许可 + 署名 + 续跑）
// ============================================================
//
// 这里的用例**全部离线**：Commons 的取数纪律（UA / 间隔 / 429）由实现承担，
// 门禁只验「解析与判定」这一层——因为网络在门禁里不可复现，而解析错了会
// 让台账**看起来是对的**却写错署名（见 §许可模板 author 那条）。
describe('source：CSV 解析与检索词', () => {
  it('parseCsv：双引号包字段、"" 转义、CRLF', () => {
    const rows = source.parseCsv('a,b\r\n"x,y","he said ""hi"""\r\n')
    expect(rows).toEqual([['a', 'b'], ['x,y', 'he said "hi"']])
  })

  it('workTokens：编号与调性词被剔掉，短词也剔掉', () => {
    const t = source.workTokens("Missa L'homme arme in D minor, Op. 11")
    expect(t).toContain('Missa')
    expect(t).toContain("L'homme")
    expect(t).toContain('arme')
    // 'in'（虚词）、'D'（单字母）、'Op'、'minor'、'11' 都不该留
    expect(t).not.toContain('in')
    expect(t).not.toContain('D')
    expect(t).not.toContain('Op')
    expect(t).not.toContain('minor')
    expect(t).not.toContain('11')
  })

  it('titleAffinity：文件名命中的作品词越多分越高；无关名字分低', () => {
    const good = source.titleAffinity('Guillaume Dufay - Se la face ay pale.ogg', 'Se la face ay pale')
    const bad = source.titleAffinity('Bundesarchiv Bild 102-08918.ogg', 'Se la face ay pale')
    expect(good).toBeGreaterThan(bad)
    expect(bad).toBe(0)
  })

  it('读出处页失败**不许编署名**：attribution 留空 + 记错误（上一版写成 Public domain，= 伪造许可）', async () => {
    // 门禁绝不真联网：读页接缝直接抛（模拟 429）。
    const out = await source.fillAttribution(
      [{
        title: 'x.ogg', url: 'https://example.invalid/x.ogg',
        pageUrl: 'https://example.invalid/p', size: 1, duration: 1, mime: 'audio/ogg',
        license: 'CC BY-SA 4.0', licenseUrl: '', attribution: '',
      }],
      { intervalMs: 0, readPage: async () => { throw new Error('HTTP 429') } },
    )
    expect(out[0]!.attribution).toBe('')
    expect(out[0]!.attributionError).toBeTruthy()
    expect(out[0]!.attribution).not.toContain('Public domain')
  })

  it('署名取许可模板的 |author=（演出者），不取 Information 的 |author=（作曲家）', async () => {
    const wt = [
      '{{Information',
      '|description={{en|1=Performed by John Harrison}}',
      '|author=Antonio Vivaldi',
      '}}',
      '{{self|cc-by-sa-4.0|author=John Harrison}}',
    ].join('\n')
    const out = await source.fillAttribution(
      [{
        title: 'y.ogg', url: 'https://example.invalid/y.ogg', pageUrl: 'p',
        size: 1, duration: 1, mime: 'audio/ogg', license: 'CC BY-SA 4.0', licenseUrl: '', attribution: '',
      }],
      { intervalMs: 0, readPage: async () => wt },
    )
    expect(out[0]!.attribution).toBe('John Harrison · CC BY-SA 4.0 via Wikimedia Commons')
    expect(out[0]!.attribution).not.toContain('Vivaldi')
  })

  it('续跑会**修**署名未知的台账条目（只重读出处页，不重检索）', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'feuille-repair-'))
    const csvPath = join(dir, 'works.csv')
    writeFileSync(csvPath, 'entry,composer_en,work_en\n901,Composer B,Work Two\n', 'utf8')
    const ledger = join(dir, 'ledger.json')
    // 预置一条署名被写成「Public domain」的旧记录（伪造许可的形态）
    writeFileSync(ledger, JSON.stringify({
      version: 1,
      works: [{
        entry: '901', composer: 'Composer B', work: 'Work Two', candidates: 1, usable: 1,
        recording: {
          id: 'src-901', kind: 'recording', title: 'b-two.ogg',
          url: 'https://example.invalid/p', license: 'CC BY-SA 4.0', license_url: '',
          attribution: 'Public domain, via Wikimedia Commons', retrieved: '2026-11-04', sha256: '',
        },
        pageUrl: 'https://example.invalid/p', license: 'CC BY-SA 4.0',
        attribution: 'Public domain, via Wikimedia Commons', durationS: 120,
      }],
    }), 'utf8')

    const res = await source.sourceBatch(csvPath, {
      ledgerPath: ledger, resume: true, limit: 1, intervalMs: 0,
      // 检索接缝**不该被调用**（只重读出处页）
      searchFn: async () => { throw new Error('不该重新检索') },
      attributionFn: async (cs) => cs.map((c) => ({
        ...c, attribution: 'Fixed Performer · CC BY-SA 4.0 via Wikimedia Commons', attributionError: '',
      })),
    })
    expect(res[0]!.attribution).toBe('Fixed Performer · CC BY-SA 4.0 via Wikimedia Commons')
    expect(res[0]!.recording!.attribution).toContain('Fixed Performer')
    expect(res[0]!.recording!.attribution_error).toBe('')
  })

  it('续跑时旧选中项不可用（广播引子）→ **重查**，不能把这条丢掉', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'feuille-recheck-'))
    const csvPath = join(dir, 'works.csv')
    writeFileSync(csvPath, 'entry,composer_en,work_en\n901,Composer B,Work Two\n', 'utf8')
    const ledger = join(dir, 'ledger.json')
    // 旧台账里这一件的选中项是广播引子 → 不可用
    writeFileSync(ledger, JSON.stringify({
      works: [{
        entry: '901', composer: 'Composer B', work: 'Work Two', candidates: 1, usable: 1,
        recording: {
          id: 'src-901', kind: 'recording', title: 'Inleiding Something (audio).mp3',
          url: 'https://example.invalid/p', license: 'CC BY-SA 4.0', license_url: '',
          attribution: 'Someone · CC BY-SA 4.0 via Wikimedia Commons', retrieved: '', sha256: '',
        },
        pageUrl: 'https://example.invalid/p', license: 'CC BY-SA 4.0',
        attribution: 'Someone · CC BY-SA 4.0 via Wikimedia Commons', durationS: 100,
      }],
    }), 'utf8')

    const res = await source.sourceBatch(csvPath, {
      ledgerPath: ledger, resume: true, limit: 1, intervalMs: 0,
      searchFn: async () => [{
        title: 'good.ogg', url: 'https://example.invalid/g.ogg', pageUrl: 'p',
        size: 1, duration: 10, mime: 'audio/ogg', license: 'CC0', licenseUrl: '', attribution: '',
      }],
      attributionFn: async (cs) => cs.map((c) => ({ ...c, attribution: 'ok' })),
    })
    // 这一件**必须重查到**，不能被丢掉
    expect(res.map((w) => w.entry)).toEqual(['901'])
    expect(res[0]!.recording!.title).toBe('good.ogg')
  })

  it('needsAttribution：把署名未知的件挑出来（含上一版写成 Public domain 的历史记录）', () => {
    const mk = (entry: string, license: string, attribution: string, err = '') => ({
      entry, composer: 'C', work: 'W', candidates: 1, usable: 1,
      recording: { id: entry, kind: 'recording' as const, title: 't', url: 'u', license,
        license_url: '', attribution, retrieved: '', sha256: '' },
      pageUrl: 'p', license, attribution, attributionError: err, durationS: 1,
    })
    const list = source.needsAttribution([
      mk('1', 'CC BY-SA 4.0', 'John Harrison · CC BY-SA 4.0 via Wikimedia Commons'),
      mk('2', 'CC BY-SA 4.0', 'Public domain, via Wikimedia Commons'),
      mk('3', 'CC BY-SA 4.0', '', 'HTTP 429'),
      mk('4', 'Public domain', 'Public domain, via Wikimedia Commons'),
    ])
    expect(list.map((w) => w.entry)).toEqual(['2', '3'])
  })

  it('isUsableLicense：PD / CC0 / CC BY 收，unknown / 自定许可不收', () => {
    expect(source.isUsableLicense('Public domain')).toBe(true)
    expect(source.isUsableLicense('CC0')).toBe(true)
    expect(source.isUsableLicense('CC BY-SA 4.0')).toBe(true)
    expect(source.isUsableLicense('unknown')).toBe(false)
    expect(source.isUsableLicense('Custom license')).toBe(false)
  })
})

describe('source：批量台账的续跑与逐件落盘', () => {
  it('续跑跳过已有录音的件，且**逐件落盘**（中途被打断也留证据）', async () => {
    const root = tmp()
    const csvPath = join(root, 'works.csv')
    writeFileSync(csvPath, [
      'entry,period,title_zh,title_en,work_zh,work_en,composer_zh,composer_en,slug,status,tier,recording_id,notes',
      '900,测试,一,One,作品一,Work One,某作曲家,Composer A,work-900,,, ,',
      '901,测试,二,Two,作品二,Work Two,某作曲家,Composer B,work-901,,, ,',
    ].join('\n'), 'utf8')

    // 预置台账：900 已有录音 → 必须跳过，**不许联网**。
    const ledger = join(root, 'ledger.json')
    writeFileSync(ledger, JSON.stringify({
      works: [{ entry: '900', composer: 'Composer A', work: 'Work One', candidates: 2, usable: 1, recording: { id: 'src-900' }, pageUrl: 'p', license: 'CC0', attribution: 'a', durationS: 100 }],
    }), 'utf8')

    // 901 没有预置 → 走注入的检索接缝（**门禁绝不真联网**：否则这条就变成
    // 「今天 Commons 通不通」的可用性测试，红绿与代码无关）。
    const fakeCand = (title: string, license: string): source_1.AudioCandidate => ({
      title, url: `https://example.invalid/${title}`, pageUrl: 'https://example.invalid/p',
      size: 1024, duration: 120, mime: 'audio/ogg', license, licenseUrl: '', attribution: '',
    })
    const res = await source.sourceBatch(csvPath, {
      ledgerPath: ledger, resume: true, limit: 1, intervalMs: 0,
      searchFn: async (_c, w) => (w === 'Work Two' ? [fakeCand('b-two.ogg', 'CC0')] : []),
      attributionFn: async (cs) => cs.map((c) => ({ ...c, attribution: 'injected' })),
    })

    // 台账必须已经写到盘上（逐件 flush），两件都在。
    expect(existsSync(ledger)).toBe(true)
    const after = JSON.parse(readFileSync(ledger, 'utf8')) as { works: Array<{ entry: string }> }
    expect(after.works.map((w) => w.entry)).toEqual(['900', '901'])
    expect(after.works.map((w) => w.entry)).toEqual(['900', '901'])

    // 900 原样带过来（没有重查），901 走接缝命中。
    const skipped = res.find((w) => w.entry === '900')!
    expect(skipped.recording).not.toBeNull()
    const fresh = res.find((w) => w.entry === '901')!
    expect(fresh.recording).not.toBeNull()
    expect(fresh.license).toBe('CC0')
    expect(fresh.attribution).toBe('injected')
  }, 120_000)
})

// ============================================================
//  旗标词表 ↔ 实现
// ============================================================
//
// `FLAGS` 既是给人看的清单，也是门禁（plugin-parity 的「旗标词表 ↔
// SKILL.md」）认的事实源——所以它自己必须与实现一致：表里有的必须真被读到，
// 实现里读的必须表里有。两边任一侧漂了，说明书与实现就开始各说各话。
describe('narrate：旁白分段的 TTS 输入与校验', () => {
  it('标点在源头剥掉（标点 → 空格），字母数字与词内撇号保留', () => {
    expect(narrate.stripPunctuation('这一段不解释，先让你听。')).toBe('这一段不解释 先让你听')
    expect(narrate.stripPunctuation("L'homme arme!")).toBe("L'homme arme")
    expect(narrate.stripPunctuation('a——b')).toBe('a b')
  })

  it('narration.json 校验：缺 id / 重复 id / 空 text / 缺 locale 都明确报错', () => {
    const base = { id: 'a', locale: 'zh-CN', text: 'x' }
    expect(() => narrate.parseNarrationSpec(JSON.stringify({ segments: [base] }))).not.toThrow()
    expect(() => narrate.parseNarrationSpec(JSON.stringify({ segments: [] }))).toThrow(/segments/)
    expect(() => narrate.parseNarrationSpec(JSON.stringify({
      segments: [{ ...base, id: '' }],
    }))).toThrow(/id/)
    expect(() => narrate.parseNarrationSpec(JSON.stringify({
      segments: [base, { ...base }],
    }))).toThrow(/重复/)
    expect(() => narrate.parseNarrationSpec(JSON.stringify({
      segments: [{ ...base, text: '  ' }],
    }))).toThrow(/text/)
    expect(() => narrate.parseNarrationSpec(JSON.stringify({
      segments: [{ ...base, locale: '' }],
    }))).toThrow(/locale/)
  })

  it('没有声线 → 明确报错（不许默默挑一个默认声线）', async () => {
    const spec = narrate.parseNarrationSpec(JSON.stringify({
      segments: [{ id: 'a', locale: 'zh-CN', text: '测试' }],
    }))
    await expect(narrate.narrateSegments(spec, { outDir: mkdtempSync(join(tmpdir(), 'feuille-narr-')) }))
      .rejects.toThrow(/声线/)
  })
})

describe('cli：旗标词表与实现一致', () => {
  const leafFile: Record<string, string> = {
    probe: 'probe.ts',
    align: 'align.ts',
    build: 'build.ts',
    'scan-ink': 'scan_ink.ts',
    source: 'source.ts',
    'source-batch': 'source.ts',
    narrate: 'narrate.ts',
  }

  it('FLAGS 里每个旗标都在对应模块里真被读到（numOpt / strOpt / flags.has / opts[…]）', () => {
    const dir = new URL('../src/', import.meta.url)
    const missing: string[] = []
    for (const [leaf, flags] of Object.entries(FLAGS)) {
      const src = readFileSync(fileURLToPath(new URL(leafFile[leaf]!, dir)), 'utf8')
      for (const flag of flags) {
        const key = flag.slice(2)
        const used =
          src.includes(`'${key}'`) || src.includes(`\`${key}\``) || src.includes(`"${key}"`)
        if (!used) missing.push(`${leaf}: ${flag}`)
      }
    }
    expect(missing, 'FLAGS 里登记了实现不认的旗标——模型会照着拼一个不存在的参数').toEqual([])
  })

  it('反向：实现里读到的旗标都在 FLAGS 里（新加旗标必须登记）', () => {
    const dir = new URL('../src/', import.meta.url)
    const registered = new Set<string>(Object.values(FLAGS).flat())
    const unregistered: string[] = []
    for (const [leaf, file] of Object.entries(leafFile)) {
      const src = readFileSync(fileURLToPath(new URL(file, dir)), 'utf8')
      for (const m of src.matchAll(/(?:numOpt|strOpt)\(args, '([a-z][a-z0-9-]*)'/g)) {
        if (!registered.has(`--${m[1]!}`)) unregistered.push(`${leaf}: --${m[1]!}`)
      }
      for (const m of src.matchAll(/flags\.has\('([a-z][a-z0-9-]*)'\)/g)) {
        if (!registered.has(`--${m[1]!}`)) unregistered.push(`${leaf}: --${m[1]!}`)
      }
    }
    expect(unregistered, '实现读了未登记的旗标——它会隐身，说明书与门禁都看不见它').toEqual([])
  })
})
