// scan_ink.ts — 含墨覆盖率扫描（本产线的「空帧」验收闸）。
//
// 为什么不能复用 `feuille karaoke scan-blank`：它判的是
// `min(R,G,B) >= 250` 的近纯白。暖纸 #f7f2e6 的最小通道是 230、灰度
// 242——空纸渲染**永远**不会命中，112s 全片空纸而扫描全绿的事故就是这么
// 来的（traps §10）。
//
// 本模块的口径：1 fps 采样 → 每帧转灰度 → 统计 gray < --gray 的像素占比。
// 任一采样帧低于 --min-pct 即判失败（fail-closed）。
//
// 阈值只有一张表（别处不再写第二套）：
//   判定阈值 0.2%；暖纸空页 0% 必 FAIL；稀疏合法标题卡 0.46% PASS；
//   正常教学帧 / preroll 设计上 ≥ 0.3%。
//
// **反向自测**必须同时证明两件事：抓到坏帧 **且** 没误杀好帧
// （`blank=caught card=passed`）。只证明抓到坏帧不够。
import { spawn, spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { FeuilleError, platform } from '@feuille/core'

import { numOpt, parseArgs } from './cli.js'

export interface InkOptions {
  /** 采样帧率（默认 1）。 */
  fps?: number
  /** 灰度阈值（默认 200）：低于此值算「有墨」。 */
  gray?: number
  /** 含墨占比下限（%，默认 0.2）。 */
  minPct?: number
}

export interface InkFrame {
  frame: number
  pct: number
}

export interface InkReport {
  video: string
  frames: number
  gray: number
  minPct: number
  minObservedPct: number | null
  bad: InkFrame[]
  status: 'ok' | 'FAIL'
}

function run(bin: string, args: string[]): string {
  const r = spawnSync(bin, args, { encoding: 'utf8', maxBuffer: 1 << 24 })
  if (r.error) throw new FeuilleError(`${bin}: ${r.error.message}`)
  if (r.status !== 0) {
    throw new FeuilleError(`${bin} exited ${r.status}\n${(r.stderr ?? '').slice(-1000)}`)
  }
  return r.stdout
}

function probeSize(prober: string, video: string): { w: number; h: number } {
  const txt = run(prober, [
    '-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', video,
  ]).trim()
  const m = txt.match(/^(\d+)x(\d+)$/)
  if (!m) throw new FeuilleError(`读不出画面尺寸：${video} → ${JSON.stringify(txt)}`)
  return { w: Number(m[1]), h: Number(m[2]) }
}

/**
 * 采样并逐帧统计含墨占比。
 *
 * 用流式 spawn 而不是 spawnSync：全片 1fps 的 raw 灰度帧可达 GB 级，
 * spawnSync 的 maxBuffer 会直接 ENOBUFS。分帧只保留当前帧。
 */
export function scanInk(
  video: string,
  opts: InkOptions = {},
): Promise<InkReport> {
  const fps = opts.fps ?? 1
  const gray = opts.gray ?? 200
  const minPct = opts.minPct ?? 0.2
  const encoder = platform.requireTool(platform.ffmpeg(), 'ffmpeg')
  const prober = platform.requireTool(platform.ffprobe(), 'ffprobe')

  return new Promise((resolve, reject) => {
    let size: { w: number; h: number }
    try {
      size = probeSize(prober, video)
    } catch (e) {
      reject(e)
      return
    }
    const frameBytes = size.w * size.h
    const args = [
      '-v', 'error', '-i', video,
      '-vf', `fps=${fps},format=gray`,
      '-f', 'rawvideo', '-pix_fmt', 'gray', '-',
    ]
    const child = spawn(encoder, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    const frames: InkFrame[] = []
    let pending: Buffer = Buffer.alloc(0)
    let err = ''
    let idx = 0

    child.stderr.on('data', (d: Buffer) => { err += d.toString() })
    child.stdout.on('data', (chunk: Buffer) => {
      pending = pending.length ? Buffer.concat([pending, chunk as Buffer<ArrayBuffer>]) : (chunk as Buffer<ArrayBuffer>)
      let off = 0
      while (pending.length - off >= frameBytes) {
        let ink = 0
        for (let i = off; i < off + frameBytes; i++) if (pending[i]! < gray) ink++
        frames.push({ frame: ++idx, pct: (ink / frameBytes) * 100 })
        off += frameBytes
      }
      if (off) pending = pending.subarray(off)
    })
    child.on('error', reject)
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new FeuilleError(`${encoder} exited ${code}\n${err.slice(-1000)}`))
        return
      }
      const bad = frames.filter((f) => f.pct < minPct)
      // 0 帧 = 检查没跑起来，不是「没问题」——跑空必须 FAIL。
      const empty = frames.length === 0
      resolve({
        video,
        frames: frames.length,
        gray,
        minPct,
        minObservedPct: frames.length ? Math.min(...frames.map((f) => f.pct)) : null,
        bad,
        status: empty || bad.length ? 'FAIL' : 'ok',
      })
    })
  })
}

/** 合成一段测试视频（暖纸底 / 暖纸底 + 墨条）。 */
function makeVideo(dir: string, name: string, extraFilter?: string): string {
  const out = join(dir, name)
  const vf = ['format=yuv420p', ...(extraFilter ? [extraFilter] : [])].join(',')
  run(platform.requireTool(platform.ffmpeg(), 'ffmpeg'), [
    '-v', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=0xf7f2e6:s=1920x1080:r=30',
    '-t', '1', '-vf', vf, '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', out,
  ])
  return out
}

/**
 * 反向自测：暖纸空页必须 FAIL、0.46% 墨量标题卡必须 PASS。
 *
 * 两件事都要证：抓到坏帧 **且** 没误杀好帧。只证明前者不够——
 * 一个「永远 FAIL」的扫描器也能满足它。
 */
export async function inkSelfTest(opts: InkOptions = {}): Promise<boolean> {
  const dir = mkdtempSync(join(tmpdir(), 'ink-selftest-'))
  try {
    const blank = makeVideo(dir, 'blank.mp4')
    const f1 = await scanInk(blank, opts)
    const blankFails = f1.frames > 0 && f1.bad.length === f1.frames

    // 1920×5 的墨条 = 9600 / 2073600 = 0.463%
    const card = makeVideo(dir, 'card.mp4', 'drawbox=x=0:y=0:w=1920:h=5:color=0x2c2620:t=fill')
    const f2 = await scanInk(card, opts)
    const cardPasses = f2.frames > 0 && f2.bad.length === 0

    const ok = blankFails && cardPasses
    console.log(
      `self-test: blank=${blankFails ? 'caught' : 'MISSED'}`
      + ` card=${cardPasses ? 'passed' : 'FALSE-FAIL'}`
      + `  [${ok ? 'PASS' : 'FAIL'}]`,
    )
    return ok
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

// ============================================================
//  CLI：feuille music scan-ink
// ============================================================

/**
 * `feuille music scan-ink <video…> [--fps 1] [--gray 200] [--min-pct 0.2] [--json]`
 * `feuille music scan-ink --self-test`
 *
 * 退出码：0 = 全部帧达标；1 = 有坏帧（或自测失败）；2 = 用法错误。
 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const opts: InkOptions = {
    fps: numOpt(args, 'fps', 1),
    gray: numOpt(args, 'gray', 200),
    minPct: numOpt(args, 'min-pct', 0.2),
  }
  if (args.flags.has('self-test')) {
    return (await inkSelfTest(opts)) ? 0 : 1
  }
  if (!args.positional.length) {
    console.error('usage: feuille music scan-ink <video…> [--fps 1] [--gray 200] [--min-pct 0.2] [--json]')
    return 2
  }
  let ok = true
  for (const video of args.positional) {
    const rep = await scanInk(video, opts)
    if (args.flags.has('json')) {
      console.log(JSON.stringify(rep))
    } else {
      const worst = rep.bad.slice(0, 6).map((f) => `#${f.frame}=${f.pct.toFixed(3)}%`).join(' ')
      console.log(
        `${video}: ${rep.frames} frames sampled, min ink `
        + `${(rep.minObservedPct ?? 0).toFixed(3)}% (threshold ${rep.minPct}%, gray<${rep.gray})`
        + (rep.frames === 0 ? '  no frames decoded' : '')
        + (rep.bad.length ? `  bad: ${worst}` : '')
        + `  [${rep.status}]`,
      )
    }
    if (rep.status !== 'ok') ok = false
  }
  return ok ? 0 : 1
}
