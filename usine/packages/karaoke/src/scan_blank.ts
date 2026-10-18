// scan_blank.ts — 全片白页扫描（karaoke-video/scripts/scan_blank.py 的 TS 归流）。
//
// **唯一独立于状态帧的检查**：verify_sync 拿成片与同一批状态帧做差——
// 一次坏渲染（如 file:// URL 写错让 headless Chrome 抓了 Google 搜索页）
// 会把两侧一起下毒、照样通过。这个扫描直接对成片采样，标记「大面积近纯白」
// 的帧——真实设计帧是纸色，永远不会是纯白。
//
// `feuille karaoke scan-blank <video.mp4> [more.mp4 …] [--fps 1] [--max-white 0.75]`
//
// 任何视频含白帧 → 退出码 1。
//
// 归流决定：ffmpeg 经 platform 解析（消掉 _bin 拷贝）；PIL 白帧判定 →
// sharp raw 逐像素（min(R,G,B) >= 250 口径不变）。PIL 环境自举（_ensure_pil
// re-exec）是 Python 生态特有的搬运，TS 侧 sharp 随包走，整段不迁。
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import sharp from 'sharp'

import { FeuilleError, platform } from '@feuille/core'

/** 近纯白像素占比（resize 160×90 = 14400 px，min(R,G,B) >= 250）。 */
export async function whiteRatio(png: string): Promise<number> {
  const { data } = await sharp(png).removeAlpha().resize(160, 90).raw()
    .toBuffer({ resolveWithObject: true })
  let white = 0
  for (let i = 0; i < data.length; i += 3) {
    if (data[i]! >= 250 && data[i + 1]! >= 250 && data[i + 2]! >= 250) white++
  }
  return white / 14400
}

/** 采一串帧，报白帧。返回 true = 无白帧。 */
export async function scan(video: string, fps: number, maxWhite: number): Promise<boolean> {
  const ffmpeg = platform.ffmpeg()
  if (!ffmpeg) {
    throw new FeuilleError('找不到 ffmpeg（feuille.platform 解析；请安装后重跑）')
  }
  // 原版 mkdtemp 后不清理（采样帧是一次性证物，落在系统临时目录）——按原样镜像
  const d = mkdtempSync(join(tmpdir(), 'karaoke-scan-'))
  const r = spawnSync(ffmpeg, ['-y', '-loglevel', 'error', '-i', video,
    '-vf', `fps=${fps}`, join(d, 'f%03d.png')], { encoding: 'utf8' })
  if (r.status !== 0) {
    throw new FeuilleError(`scan FAILED: ${video}\n${(r.stderr ?? '').toString().slice(-2000)}`)
  }
  const frames = readdirSync(d).filter((f) => f.startsWith('f') && f.endsWith('.png')).sort()
  const bad: Array<[string, number]> = []
  for (const p of frames) {
    const wr = await whiteRatio(join(d, p))
    if (wr > maxWhite) bad.push([p, Math.round(wr * 100) / 100])
  }
  const status = bad.length ? 'FAIL' : 'ok'
  // bad[:6] or 'none' —— Python repr 形态（元组列表 / 'none'）
  const badRepr = bad.length
    ? `[${bad.slice(0, 6).map(([n, x]) => `('${n}', ${x})`).join(', ')}]`
    : 'none'
  console.log(`${video}: ${frames.length} frames sampled, blank/white: ${badRepr}  [${status}]`)
  return bad.length === 0
}

const USAGE = 'usage: feuille karaoke scan-blank <video.mp4> [more.mp4 …] [--fps 1] [--max-white 0.75]'

/** CLI 入口：nargs="+" 位置参数（至少一个视频）；旗标坏值 → 2（argparse）。 */
export async function main(argv: string[]): Promise<number> {
  const pos: string[] = []
  let fps = 1.0, maxWhite = 0.75
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (a === '-h' || a === '--help') {
      console.log(USAGE)
      return 0
    } else if (a.startsWith('--fps')) {
      const v = a.includes('=') ? a.slice('--fps='.length) : argv[++i]
      const n = Number(v)
      if (v === undefined || !Number.isFinite(n)) {
        console.error(USAGE)
        return 2
      }
      fps = n
    } else if (a.startsWith('--max-white')) {
      const v = a.includes('=') ? a.slice('--max-white='.length) : argv[++i]
      const n = Number(v)
      if (v === undefined || !Number.isFinite(n)) {
        console.error(USAGE)
        return 2
      }
      maxWhite = n
    } else if (a.startsWith('--')) {
      console.error(USAGE)
      return 2
    } else {
      pos.push(a)
    }
  }
  if (!pos.length) {
    console.error(USAGE)
    return 2
  }
  let ok = true
  for (const v of pos) {
    if (!(await scan(v, fps, maxWhite))) ok = false
  }
  return ok ? 0 : 1
}
