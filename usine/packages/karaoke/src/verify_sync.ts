// verify_sync.ts — 端到端 AV 同步验收（karaoke-video/scripts/verify_sync.py 的
// TS 归流）：在**计算可知**的时间点从成片抓帧，与期望状态帧做像素差。
//
// `feuille karaoke verify-sync --video out.mp4 --frames frames/ --tts tts/
//   --locales zh-CN,ja-JP,… [--preroll 0.8] [--done 0.5] [--intro 2.2]
//   [--threshold 40000]`
//
// 每语种三查（场景起点按 seg wav 时长累进——组装器用的同一组数字）：
//   pre   at scene_start + 0.4                    vs  <loc>-pre.png
//   word0 at scene_start + preroll + state0_dur/2  vs  <loc>-0.png
//         （state0_dur = token1.start − token0.start，从 tts 边界 json 读——
//          组装器在 token 的 **START** 切状态，英语短首词如 "a" 会比老的
//          固定 +0.15s 探针先结束、落进下一状态，所以探中点）
//   done  at scene_end - done/2                    vs  <loc>-done.png
//
// 全部差值低于阈值才退出 0。模型看不见视频——这个脚本是视觉门禁。
//
// 归流决定：ffprobe 时长 = core audio.probeDuration；抓帧 ffmpeg 经
// platform 解析；PIL 灰度直方图差 → sharp raw 逐像素口径（见 diff 注释）。
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import sharp from 'sharp'

import { FeuilleError, audio, platform } from '@feuille/core'

/** 灰度 L1 差（Python 口径的直译）。
 *
 * Python: ImageChops.difference(ia, ib).histogram()[12:] 求和——histogram
 * 第 k 格 = 差值恰为 k 的像素数，取 [12:] 求和 = **差值 ≥12 的像素数**
 * （≤11 的编码噪声整格丢弃）。 */
export async function diffGray(a: string, b: string): Promise<number> {
  const [ia, ib] = await Promise.all([
    sharp(a).grayscale().raw().toBuffer(),
    sharp(b).grayscale().raw().toBuffer(),
  ])
  const n = Math.min(ia.length, ib.length)
  let acc = 0
  for (let i = 0; i < n; i++) {
    const d = Math.abs(ia[i]! - ib[i]!)
    if (d >= 12) acc++
  }
  return acc
}

function ffmpegBin(): string {
  const got = platform.ffmpeg()
  if (!got) {
    throw new FeuilleError('找不到 ffmpeg（feuille.platform 解析；请安装后重跑）')
  }
  return got
}

/** 从视频 t 秒抓一帧。 */
function grab(video: string, t: number, out: string): string {
  const r = spawnSync(ffmpegBin(), ['-y', '-loglevel', 'error', '-ss', String(t),
    '-i', video, '-frames:v', '1', out], { encoding: 'utf8' })
  if (r.status !== 0) {
    throw new FeuilleError(`grab FAILED: ${video}@${t}\n${(r.stderr ?? '').toString().slice(-2000)}`)
  }
  return out
}

const USAGE = 'usage: feuille karaoke verify-sync --video out.mp4 --frames frames/ --tts tts/ --locales zh-CN,ja-JP [--preroll 0.8] [--done 0.5] [--intro 2.2] [--threshold 40000]'

/** argparse 同款取值（lesson.ts 口径）：`--k v` / `--k=v` 皆收，后者覆盖。 */
function argValue(argv: string[], flag: string): string | undefined {
  const i = argv.lastIndexOf(flag)
  if (i >= 0) return argv[i + 1]
  const p = `${flag}=`
  for (let j = argv.length - 1; j >= 0; j--) {
    if (argv[j]!.startsWith(p)) return argv[j]!.slice(p.length)
  }
  return undefined
}

/** CLI 入口。缺必填 → 2（argparse）；有失配 → FeuilleError（SYNC FAILURES → 1）。 */
export async function main(argv: string[]): Promise<number> {
  const need = ['--video', '--frames', '--tts', '--locales'] as const
  const vals: Record<string, string> = {}
  for (const f of need) {
    const v = argValue(argv, f)
    if (!v) {
      console.error(USAGE)
      return 2
    }
    vals[f] = v
  }
  const num = (f: string, def: number): number | null => {
    const v = argValue(argv, f)
    if (v === undefined) return def
    const n = Number(v)
    // argparse type=float/int：坏值当场退出码 2，不静默 NaN
    if (!Number.isFinite(n) || (f === '--threshold' && !Number.isInteger(n))) {
      console.error(USAGE)
      return null
    }
    return n
  }
  const preroll = num('--preroll', 0.8)
  const done = num('--done', 0.5)
  const intro = num('--intro', 2.2)
  const threshold = num('--threshold', 40000)
  if (preroll === null || done === null || intro === null || threshold === null) return 2
  const F = vals['--frames']!, T = vals['--tts']!

  const locales = vals['--locales']!.split(',')
  const starts: Record<string, number> = {}
  let t = intro
  for (const loc of locales) {
    starts[loc] = t
    t += audio.probeDuration(join(F, `${loc}-seg.wav`))
  }

  const fails: string[] = []
  for (const loc of locales) {
    const s = starts[loc]!
    const d = audio.probeDuration(join(F, `${loc}-seg.wav`))
    const toks = JSON.parse(readFileSync(join(T, `${loc}.json`), 'utf8'))['tokens'] as Array<{ start: number }>
    // state 0 跨 [preroll + t0.start, preroll + t1.start)；探中点。
    // 单 token 语种：探音频跨度的一半。
    const s0 = toks.length > 1 ? toks[1]!['start'] - toks[0]!['start'] : d - preroll - done
    const checks: Array<[string, number, string]> = [
      ['pre', s + 0.4, join(F, `${loc}-pre.png`)],
      ['word0', s + preroll + s0 / 2, join(F, `${loc}-0.png`)],
      ['done', s + d - done / 2, join(F, `${loc}-done.png`)],
    ]
    for (const [label, tt, want] of checks) {
      const dpx = await diffGray(grab(vals['--video']!, tt, join(F, '_vs.png')), want)
      const status = dpx < threshold ? 'OK' : 'MISMATCH'
      console.log(`${loc.padEnd(8)} ${label.padEnd(6)} t=${tt.toFixed(2).padStart(7)} `
        + `diff=${String(dpx).padStart(8)}  ${status}`)
      if (dpx >= threshold) fails.push(`${loc}/${label}`)
    }
  }

  if (fails.length) {
    throw new FeuilleError(`SYNC FAILURES: ${fails.join(', ')}`)
  }
  console.log('all scenes in sync')
  return 0
}
