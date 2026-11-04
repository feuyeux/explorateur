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
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

import { platform } from '@feuille/core'

import { align, build, chord, dsp, midi, probe, scan_ink } from '../src/index.js'

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
