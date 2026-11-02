#!/usr/bin/env node
// ink-scan.mjs — 含墨覆盖率扫描（本产线验收判据的可执行实现）。
//
// 为什么不用 `feuille karaoke scan-blank`：它判的是 min(R,G,B) >= 250 的
// near-pure-white。暖纸 #f7f2e6 的最小通道是 230、灰度 242——空纸渲染
// **永远**不会命中，112s 全片空纸而扫描全绿的事故就是这么来的
// （packages/karaoke/src/scan_blank.ts:25，references/music-av-traps.md §10）。
//
// 本脚本的口径：1 fps 采样 → 每帧转灰度 → 统计 gray < --gray 的像素占比。
// 任一采样帧低于 --min-pct 即退出 1（fail-closed）。
//
// 用法（路径必须显式给，不写死可执行名——AGENTS.md 跨平台硬约定 1）：
//   node ink-scan.mjs <video.mp4> [more.mp4 …] \
//     --ffmpeg <abs-path> --ffprobe <abs-path> [--fps 1] [--gray 200] [--min-pct 0.2]
//
// 反向自测（合成两帧：暖纸空页必须 FAIL、0.46% 墨量标题卡必须 PASS）：
//   node ink-scan.mjs --self-test --ffmpeg <abs-path> --ffprobe <abs-path>
//
// 退出码：0 = 全部帧达标；1 = 有坏帧或自测失败；2 = 用法/环境错误。
import { spawn, spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

function usage(msg) {
  if (msg) console.error(msg)
  console.error(
    'usage: node ink-scan.mjs <video…> --ffmpeg <path> --ffprobe <path>'
    + ' [--fps 1] [--gray 200] [--min-pct 0.2] [--json]\n'
    + '       node ink-scan.mjs --self-test --ffmpeg <path> --ffprobe <path>',
  )
  process.exit(2)
}

function parse(argv) {
  const out = { videos: [], fps: 1, gray: 200, minPct: 0.2, json: false, selfTest: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const take = () => {
      const v = argv[++i]
      if (v === undefined) usage(`missing value after ${a}`)
      return v
    }
    if (a === '--ffmpeg') out.encoder = take()
    else if (a === '--ffprobe') out.prober = take()
    else if (a === '--fps') out.fps = Number(take())
    else if (a === '--gray') out.gray = Number(take())
    else if (a === '--min-pct') out.minPct = Number(take())
    else if (a === '--json') out.json = true
    else if (a === '--self-test') out.selfTest = true
    else if (a === '-h' || a === '--help') usage()
    else if (a.startsWith('--')) usage(`unknown flag ${a}`)
    else out.videos.push(a)
  }
  if (!out.encoder || !out.prober) usage('--ffmpeg and --ffprobe are required (no defaults)')
  for (const [k, v] of [['fps', out.fps], ['gray', out.gray], ['min-pct', out.minPct]]) {
    if (!Number.isFinite(v) || v <= 0) usage(`--${k} must be a positive number`)
  }
  if (!out.selfTest && !out.videos.length) usage('no video given')
  return out
}

function run(bin, args) {
  const r = spawnSync(bin, args, { encoding: 'utf8', maxBuffer: 1 << 20 })
  if (r.error) throw new Error(`${bin}: ${r.error.message}`)
  if (r.status !== 0) throw new Error(`${bin} exited ${r.status}\n${(r.stderr ?? '').slice(-1000)}`)
  return r.stdout
}

function probeSize(prober, video) {
  const txt = run(prober, [
    '-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', video,
  ]).trim()
  const m = txt.match(/^(\d+)x(\d+)$/)
  if (!m) throw new Error(`cannot read dimensions of ${video}: ${JSON.stringify(txt)}`)
  return { w: Number(m[1]), h: Number(m[2]) }
}

/** 采样并逐帧统计含墨占比。返回 [{frame, pct}]。
 *
 * 用流式 spawn 而不是 spawnSync：全片 1fps 的 raw 灰度帧可达 GB 级，
 * spawnSync 的 maxBuffer 会直接 ENOBUFS。分帧只保留当前帧。
 */
function scanFile(opt, video) {
  return new Promise((resolve, reject) => {
    const { w, h } = probeSize(opt.prober, video)
    const frameBytes = w * h
    const args = [
      '-v', 'error', '-i', video,
      '-vf', `fps=${opt.fps},format=gray`,
      '-f', 'rawvideo', '-pix_fmt', 'gray', '-',
    ]
    const child = spawn(opt.encoder, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    const frames = []
    let pending = Buffer.alloc(0)
    let err = ''
    let idx = 0

    child.stderr.on('data', (d) => { err += d.toString() })
    child.stdout.on('data', (chunk) => {
      pending = pending.length ? Buffer.concat([pending, chunk]) : chunk
      let off = 0
      while (pending.length - off >= frameBytes) {
        let ink = 0
        for (let i = off; i < off + frameBytes; i++) if (pending[i] < opt.gray) ink++
        frames.push({ frame: ++idx, pct: (ink / frameBytes) * 100 })
        off += frameBytes
      }
      if (off) pending = pending.subarray(off)
    })
    child.on('error', reject)
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`${opt.encoder} exited ${code}\n${err.slice(-1000)}`))
        return
      }
      resolve(frames)
    })
  })
}

function report(opt, video, frames) {
  const bad = frames.filter((f) => f.pct < opt.minPct)
  // 0 帧 = 检查没跑起来，不是「没问题」——跑空必须 FAIL（同工作区纪律 12）。
  const empty = frames.length === 0
  const status = empty || bad.length ? 'FAIL' : 'ok'
  if (opt.json) {
    console.log(JSON.stringify({
      video, frames: frames.length, gray: opt.gray, minPct: opt.minPct,
      minObservedPct: frames.length ? Math.min(...frames.map((f) => f.pct)) : null,
      bad, status,
    }))
  } else {
    const min = frames.length ? Math.min(...frames.map((f) => f.pct)) : 0
    const worst = bad.slice(0, 6).map((f) => `#${f.frame}=${f.pct.toFixed(3)}%`).join(' ')
    console.log(
      `${video}: ${frames.length} frames sampled, min ink ${min.toFixed(3)}%`
      + ` (threshold ${opt.minPct}%, gray<${opt.gray})`
      + (empty ? '  no frames decoded' : '')
      + (bad.length ? `  bad: ${worst}` : '') + `  [${status}]`,
    )
  }
  return !empty && bad.length === 0
}

function makeVideo(opt, dir, name, extraFilter) {
  const out = join(dir, name)
  const vf = ['format=yuv420p', ...(extraFilter ? [extraFilter] : [])].join(',')
  run(opt.encoder, [
    '-v', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=0xf7f2e6:s=1920x1080:r=30',
    '-t', '1', '-vf', vf, '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', out,
  ])
  return out
}

async function selfTest(opt) {
  const dir = mkdtempSync(join(tmpdir(), 'ink-selftest-'))
  try {
    // 暖纸空页：0% 含墨 → 必须 FAIL。
    const blank = makeVideo(opt, dir, 'blank.mp4')
    const f1 = await scanFile(opt, blank)
    const blankFails = f1.length > 0 && f1.every((f) => f.pct < opt.minPct)

    // 标题卡：1920×5 的墨条 = 9600 / 2073600 = 0.463% → 必须 PASS（阈值 0.2%）。
    const card = makeVideo(opt, dir, 'card.mp4', 'drawbox=x=0:y=0:w=1920:h=5:color=0x2c2620:t=fill')
    const f2 = await scanFile(opt, card)
    const cardPasses = f2.length > 0 && f2.every((f) => f.pct >= opt.minPct)

    const ok = blankFails && cardPasses
    console.log(
      `self-test: blank=${blankFails ? 'caught' : 'MISSED'}` +
      ` card=${cardPasses ? 'passed' : 'FALSE-FAIL'}` +
      `  [${ok ? 'PASS' : 'FAIL'}]`,
    )
    return ok
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

const opt = parse(process.argv.slice(2))
if (opt.selfTest) process.exit(await selfTest(opt) ? 0 : 1)

let ok = true
for (const video of opt.videos) {
  const frames = await scanFile(opt, video)
  if (!report(opt, video, frames)) ok = false
}
process.exit(ok ? 0 : 1)
