#!/usr/bin/env node
// make-project.mjs — 从 layout.json + 探针/对齐实测数据生成 project.json。
//
// 为什么是脚本而不是手写 project.json：装配契约里有十几个**必须实测**的量
// ——每个摘录的时长、旁白的落点（按 mp3 实测时长顺延）、状态帧的段数、
// 波形柱的参照值（vmaxRef）、和弦块与旋律线的数据。这些数一旦手抄，
// 就会和音频对不上，而对账只查帧数、不查内容——错位会静默进成片。
//
// 输入（都在项目根下）：
//   layout.json                    内容判断（哪些摘录、旁白放哪、文案）
//   notes/probe/<movement>.json    探针实测（RMS 包络 / 起音 / 候选边界）
//   notes/<movement>-align.json    对齐实测（Tier B 的和弦段与旋律段）
//   tts/narration-durations.json   旁白实测时长
//
// 输出：project.json（默认）/ project.<locale>.json
//
// 用法：
//   node make-project.mjs --layout layout.json [--locale zh-CN] [--out project.json]
//
// 退出码：0 = 成功；1 = 输入有问题；2 = 用法错误。
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

function usage(msg) {
  if (msg) console.error(msg)
  console.error(
    'usage: node make-project.mjs --layout <layout.json> [--root <项目根>] '
    + '[--locale zh-CN] [--out project.json]',
  )
  process.exit(2)
}

function parse(argv) {
  const out = { locale: 'zh-CN' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const take = () => {
      const v = argv[++i]
      if (v === undefined) usage(`missing value after ${a}`)
      return v
    }
    if (a === '--layout') out.layout = take()
    else if (a === '--root') out.root = take()
    else if (a === '--locale') out.locale = take()
    else if (a === '--out') out.out = take()
    else if (a === '-h' || a === '--help') usage()
    else usage(`unknown argument ${a}`)
  }
  if (!out.layout) usage('--layout is required')
  if (!out.out) out.out = 'project.json'
  return out
}

// ---------------------------------------------------------------------------
//  小工具
// ---------------------------------------------------------------------------

/** 秒 → 30fps 网格上的帧数（向上吸附，与 core.grid 同一口径）。 */
function framesFor(sec, fps) {
  return Math.ceil(sec * fps - 1e-9)
}

/** 读 JSON，缺文件就明确报错（不许静默用空对象——那会产出空画面）。 */
function readJson(path, what) {
  if (!existsSync(path)) {
    console.error(`找不到${what}：${path}`)
    process.exit(1)
  }
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch (e) {
    console.error(`${what} 解析失败：${path}\n${e.message}`)
    process.exit(1)
  }
}

/** 把一段连续时间按 bucket 秒切成若干桶。 */
function buckets(start, end, bucketSec) {
  const out = []
  let t = start
  while (t < end - 1e-6) {
    const t2 = Math.min(end, t + bucketSec)
    out.push([t, t2])
    t = t2
  }
  return out
}

// ---------------------------------------------------------------------------
//  主流程
// ---------------------------------------------------------------------------

const args = parse(process.argv.slice(2))
// 项目根 = layout.json 所在目录的**上一级**（layout 惯例放在 notes/ 下），
// 除非用 --root 显式指定。
const root = args.root
  ? resolve(args.root)
  : resolve(dirname(resolve(args.layout)), '..')
const layout = readJson(resolve(args.layout), 'layout.json')

const fps = layout.fps ?? 30
const durations = readJson(join(root, 'tts/narration-durations.json'), '旁白时长表').durations

/** 旁白 id → mp3 相对路径 + 实测时长。 */
function narr(id) {
  const key = `${id}.${args.locale}`
  const dur = durations[key]
  if (dur === undefined) {
    console.error(`旁白 ${key} 不在 tts/narration-durations.json 里——先跑 feuille music narrate`)
    process.exit(1)
  }
  return { file: `tts/${id}.${args.locale}.mp3`, dur }
}

/** 某个乐章的探针与对齐实测。 */
const movementCache = new Map()
function movement(key) {
  if (movementCache.has(key)) return movementCache.get(key)
  const probe = readJson(join(root, 'notes/probe', `${key}.json`), `探针数据 ${key}`)
  const align = readJson(join(root, 'notes', `${key}-align.json`), `对齐数据 ${key}`)
  const m = { probe, align }
  movementCache.set(key, m)
  return m
}

/** 摘录窗口内的波形柱（每桶一个 RMS 最大值）。 */
function waveFor(probe, start, end, bucketSec) {
  const env = probe.rms.envelope
  const hop = probe.hopSec
  return buckets(start, end, bucketSec).map(([t0, t1]) => {
    const i0 = Math.max(0, Math.floor(t0 / hop))
    const i1 = Math.min(env.length - 1, Math.ceil(t1 / hop))
    let mx = 0
    for (let i = i0; i <= i1; i++) mx = Math.max(mx, env[i] ?? 0)
    return Number(mx.toFixed(4))
  })
}

/** 摘录窗口内的和弦块（每桶取该桶里最常见的模板标签）。 */
function chordBlocksFor(align, start, end, bucketSec) {
  const chords = align.chords ?? []
  return buckets(start, end, bucketSec).map(([t0, t1]) => {
    const inBucket = chords.filter((c) => c.start_s < t1 && c.end_s > t0)
    const count = new Map()
    for (const c of inBucket) count.set(c.label, (count.get(c.label) ?? 0) + 1)
    let best = '', bestN = 0
    for (const [k, n] of count) if (n > bestN) { best = k; bestN = n }
    return { start_s: t0, end_s: t1, label: best || '—' }
  })
}

/** 摘录窗口内的旋律段（把绝对时间平移到场景内的 0 起）。 */
function melodyFor(align, start, end) {
  return (align.melody ?? [])
    .filter((m) => m.start_s < end && m.end_s > start)
    .map((m) => ({
      start_s: Number(Math.max(0, m.start_s - start).toFixed(3)),
      end_s: Number(Math.min(end, m.end_s) - start).toFixed(3),
      midi: m.midi,
    }))
}

const scenes = []
let sceneIndex = 0

for (const s of layout.scenes) {
  sceneIndex++
  const id = s.id

  // ---- 片头卡 / 制作信息页：不带旁白，卡长写死 ----
  if (s.kind === 'card') {
    scenes.push({
      id,
      kind: s.card === 'credit' ? 'credit' : 'intro',
      credit: s.card === 'credit',
      preroll: 0, tail: 0, done: 0,
      states: [{ t0: 0, t1: s.duration_s }],
      data: s.data ?? {},
    })
    continue
  }

  // ---- 旁白场景（纯文字）----
  if (s.kind === 'text') {
    const nars = (s.narration ?? []).map((n) => narr(n))
    const body = nars.reduce((a, n) => a + n.dur, 0)
    // 状态 = 要点；每点的时长按旁白长度均分（实测，不是估的）
    const pts = s.data?.points ?? []
    const total = Math.max(1, pts.length)
    const per = body / total
    // 状态从 preroll 起**铺满**整个 body：装配的时间模型是
    // 「preroll → state0 → … → done」，状态的 t0/t1 只决定时长与播放头，
    // 所以第一段必须从 preroll 开始，否则播放头会整体早一个 preroll。
    const PREROLL = 0.8
    const states = pts.map((_, i) => ({
      t0: Number((PREROLL + i * per).toFixed(3)),
      t1: Number((PREROLL + (i + 1) * per).toFixed(3)),
    }))
    scenes.push({
      id,
      kind: 'text',
      preroll: 0.8, tail: 0.5, done: 0,
      states,
      narration: nars.map((n, i) => ({ file: n.file, at_s: Number((0.8 + nars.slice(0, i).reduce((a, x) => a + x.dur, 0)).toFixed(3)), gain: 1.0 })),
      // **kind 必须放进 DATA**：状态帧页面读的是 `DATA[scene].kind`。
      // 只写在 scene 对象上，页面会走错分支——第一版就是这样，文字场景
      // 渲染成了一片空白（标题还在，因为两个分支读同一批字段）。
      data: { ...(s.data ?? {}), kind: 'text', current: pts.map((_, i) => i) },
    })
    continue
  }

  // ---- 摘录场景（和弦块 + 旋律线 + 波形）----
  if (s.kind === 'music') {
    const { probe, align } = movement(s.movement)
    const [start, end] = s.excerpt
    const bucketSec = s.bucket_sec ?? 4
    const nars = (s.narration ?? []).map((n) => narr(n.id))

    // 旁白 A 在场景开头；旁白 B 在聆听之后（"after_listening"）
    let cursor = 0.8
    const narration = []
    let musicAt = null
    nars.forEach((n) => {
      if (n.at === 'after_listening') {
        if (musicAt === null) musicAt = cursor
        narration.push({ file: n.file, at_s: Number(cursor.toFixed(3)), gain: 1.0 })
        cursor += n.dur + 0.3
      } else {
        narration.push({ file: n.file, at_s: Number(cursor.toFixed(3)), gain: 1.0 })
        cursor += n.dur + 0.3
      }
    })
    if (musicAt === null) musicAt = cursor   // 没有「聆听后」的旁白：音乐接在旁白后

    const listenSec = end - start
    const listenEnd = musicAt + listenSec
    // 场景尾部：最后一段旁白讲完 + 0.5s 余量
    const bodyEnd = Math.max(listenEnd, cursor)
    const PREROLL = 0.8
    const TAIL = 0.5

    const blocks = chordBlocksFor(align, start, end, bucketSec)
    // 状态必须**铺满**整个 body：装配的时间模型是
    // 「preroll → state0 → … → done」，body = 各 state 时长之和。
    // 少了引子段（旁白 A 说话、音乐还没进）那一段空隙，整段就没了——
    // 第一版就是这样：生成器算 903s，装配出来 659s。
    const states = []
    // 引子：音乐还没进，播放头停在 0（画面不说假话）
    if (musicAt - PREROLL > 0.01) {
      states.push({
        t0: PREROLL,
        t1: Number(musicAt.toFixed(3)),
        playhead_s: 0,
      })
    }
    blocks.forEach((b) => {
      states.push({
        t0: Number((musicAt + (b.start_s - start)).toFixed(3)),
        t1: Number((musicAt + (b.end_s - start)).toFixed(3)),
      })
    })
    // 收尾：摘录放完了、最后一段旁白在讲
    if (bodyEnd - listenEnd > 0.01) {
      states.push({
        t0: Number(listenEnd.toFixed(3)),
        t1: Number(bodyEnd.toFixed(3)),
        playhead_s: Number(listenSec.toFixed(3)),
      })
    }

    const data = {
      ...(s.data ?? {}),
      kind: 'music',
      x0: s.data?.x0 ?? 40, x1: s.data?.x1 ?? 1820,
      dur: Number(listenSec.toFixed(3)),
      // 跨段可比较的参照：**整个乐章**的最响 RMS（不是本场景的局部最大）
      vmaxRef: Number(probe.rms.max.toFixed(4)),
      chords: blocks,
      melody: melodyFor(align, start, end),
      wave: waveFor(probe, start, end, bucketSec),
      // 引子段（音乐还没进）**不高亮任何块**：current 的第一项给 null。
      // null 的语义由状态帧页面负责（null = 这一段不高亮）。
      current: [
        ...(states[0] && states[0].playhead_s === 0 ? [null] : []),
        ...blocks.map((_, i) => i),
      ],
    }
    // 事件线的时间也要平移到场景内
    if (data.events) {
      data.events = data.events.map((e) => ({
        ...e,
        t: Number((e.t - start).toFixed(3)),
      }))
    }

    // 录音文件：按乐章取（一部作品常有多个分乐章录音）
    const rec = layout.recordings?.[s.movement]
    if (!rec) {
      console.error(`layout.recordings 里没有 ${s.movement}（场景 ${id}）`)
      process.exit(1)
    }
    scenes.push({
      id,
      kind: 'music',
      recording_file: rec.file,
      recording_excerpt: { start_s: start, end_s: end },
      music_at: Number(musicAt.toFixed(3)),
      preroll: PREROLL, tail: TAIL, done: 0,
      states,
      narration,
      data,
    })
    continue
  }

  console.error(`未知场景类型：${s.kind}（${id}）`)
  process.exit(1)
}

const project = {
  $schema: 'music-project/v1',
  $comment: '由 make-project.mjs 从 layout.json + 实测数据生成；数字不许手抄。',
  work: layout.work,
  recording: layout.recording,
  fps,
  grid: `d${fps}(t) = ceil(t * ${fps} - 1e-9) / ${fps}`,
  status_frame_html: layout.status_frame_html ?? 'assets/status-frame.html',
  credit_html: layout.credit_html ?? 'assets/credit.html',
  scenes,
  audio: layout.audio,
  credit: layout.credit,
  acceptance: layout.acceptance,
}

const outPath = resolve(root, args.out)
writeFileSync(outPath, JSON.stringify(project, null, 1), 'utf8')

// 摘要：逐场景时长与帧数，便于人眼核对
let total = 0
for (const sc of scenes) {
  // body = 各 state 时长之**和**（与装配的时间模型同一口径；取最后一个
  // state 的 t1 会把 preroll 算重，把 tail 漏掉）
  const body = sc.states.reduce((a, st) => a + Math.max(0, st.t1 - st.t0), 0)
  const dur = (sc.preroll ?? 0) + body + (sc.done ?? 0) + (sc.tail ?? 0)
  total += dur
  console.log(`  ${sc.id.padEnd(12)} ${dur.toFixed(1)}s  ${framesFor(dur, fps)} 帧  状态 ${sc.states.length}`)
}
console.log(`合计 ${total.toFixed(1)}s（${framesFor(total, fps)} 帧）· ${args.locale} → ${outPath}`)
