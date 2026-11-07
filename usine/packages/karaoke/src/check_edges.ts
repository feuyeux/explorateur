// check_edges.ts — 帧边缘溢出门（状态帧的确定性版式门）。
//
// **量什么**：场景设计的所有元素离帧缘都有留白（≥36px 量级）；任何状态帧的
// 边缘带里出现「非纸色」像素 = 有元素顶到边 = 溢出。这是**确定性像素判据**，
// 不依赖 VLM，也不依赖 DOM——量的是渲染后的事实。
//
// 为什么要有它（2026-11-07 水果系列 ep01 两桩实测）：
// 1. 竖版卡超宽时卡片贴出右缘——布局者以为算对了像素，渲染才知道没有；
// 2. Edge 的视口亏空（窗口 1080×1920，实际视口 1056×1827）让场景底部露出
//    body 底色带——「画面溢出」的体感来源（已在 build_video 双向补偿根治）。
// 这道门是最后一道防线：谁再破版式，成片前当场红。
//
// `feuille karaoke check-edges <frames-dir> [more-dirs …]
//    [--margin 4] [--paper 255,252,245] [--max-hit 12] [--skip intro.png,outro.png]`
//
// - `<frames-dir>` 里所有 *.png（跳过 --skip 名单与 `_` 开头的中间产物）逐帧检查；
// - 边缘带 = 距任一边 ≤ --margin 的像素环，采样步长 3（1024² 帧毫秒级）；
// - 「墨迹」= 与 --paper 的通道差总和 > 60（纸色场景页的口径；封面卡等
//   自带彩色边框的**不进**这道门——平台契约边框是设计，见 fruit-vocab-series）；
// - 命中像素 ≥ --max-hit 判该帧溢出；任何一帧溢出 → 退出码 1（逐帧列名）。
//
// 门禁不覆盖的：帧内**元素之间**的重叠（那是 fit-diag/verify-colors 的地盘）、
// 文字可读性（那是版式门 D2–D5 的地盘）。本门只管「出画」。
import { readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

import sharp from 'sharp'

import { FeuilleError } from '@feuille/core'

export interface CheckEdgesOptions {
  /** 边缘带宽度（px）。默认 4。 */
  margin?: number
  /** 纸色（场景页背景）。默认 255,252,245。 */
  paper?: [number, number, number]
  /** 边缘带内异色像素命中阈值（采样步长 3 下）。默认 12。 */
  maxHit?: number
  /** 跳过的文件名（intro.png/outro.png 这类平台契约边框帧）。 */
  skip?: string[]
}

export interface EdgeVerdict {
  dir: string
  checked: number
  bad: string[]
}

/** 检查一个帧目录：返回溢出帧名单。帧读不动 = 门跑不成 = 抛（不是零分）。 */
export async function checkFrames(dir: string, opts: CheckEdgesOptions = {}): Promise<EdgeVerdict> {
  const margin = opts.margin ?? 4
  const paper = opts.paper ?? [255, 252, 245]
  const maxHit = opts.maxHit ?? 12
  const skip = new Set(opts.skip ?? [])

  let names: string[]
  try {
    names = readdirSync(dir)
  } catch (e) {
    throw new FeuilleError(`帧目录读不到：${dir}\n${String(e).slice(0, 200)}`)
  }
  const files = names.filter((n) => n.endsWith('.png') && !n.startsWith('_') && !skip.has(n))
  if (files.length === 0) {
    throw new FeuilleError(`帧目录里没有可检查的 PNG（跳过名单后为空）：${dir}`)
  }

  const bad: string[] = []
  for (const name of files) {
    const p = join(dir, name)
    const { data, info } = await sharp(p).removeAlpha().raw().toBuffer({ resolveWithObject: true })
    const W = info.width
    const H = info.height
    let hit = 0
    for (let y = 0; y < H && hit < maxHit; y += 3) {
      const edgeRow = y < margin || y >= H - margin
      for (let x = 0; x < W; x += 3) {
        const edgeCol = x < margin || x >= W - margin
        if (!edgeRow && !edgeCol) continue
        const i = (y * W + x) * 3
        const d = Math.abs(data[i]! - paper[0]) + Math.abs(data[i + 1]! - paper[1]) + Math.abs(data[i + 2]! - paper[2])
        if (d > 60) hit++
      }
    }
    if (hit >= maxHit) bad.push(name)
  }
  return { dir, checked: files.length, bad }
}

/** CLI 入口：`feuille karaoke check-edges <frames-dir> [more…] [flags]`。 */
export async function main(argv: string[]): Promise<number> {
  const FLAGS_WITH_VALUE = ['--margin', '--paper', '--max-hit', '--skip']
  const dirList: string[] = []
  const opts: CheckEdgesOptions = {}
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!
    if (FLAGS_WITH_VALUE.includes(a)) {
      const v = argv[i + 1]
      if (v === undefined) {
        console.error(`usage: feuille karaoke check-edges <frames-dir> [more-dirs…] [--margin 4] [--paper 255,252,245] [--max-hit 12] [--skip intro.png,outro.png]\n（${a} 缺值）`)
        return 2
      }
      if (a === '--margin') opts.margin = Number(v)
      if (a === '--max-hit') opts.maxHit = Number(v)
      if (a === '--paper') opts.paper = v.split(',').map(Number) as [number, number, number]
      if (a === '--skip') opts.skip = v.split(',').filter(Boolean)
      i++
      continue
    }
    if (!a.startsWith('--')) dirList.push(resolve(a))
  }
  if (dirList.length === 0) {
    console.error('usage: feuille karaoke check-edges <frames-dir> [more-dirs…] [--margin 4] [--paper 255,252,245] [--max-hit 12] [--skip intro.png,outro.png]')
    return 2
  }
  const failures: string[] = []
  for (const dir of dirList) {
    const v = await checkFrames(dir, opts)
    if (v.bad.length) {
      failures.push(`${dir}（${v.checked} 帧里 ${v.bad.length} 帧溢出）：${v.bad.slice(0, 12).join(', ')}`)
    } else {
      console.log(`${dir}：${v.checked} 帧边缘干净`)
    }
  }
  if (failures.length) {
    console.error(`✖ 帧边缘溢出：\n  ${failures.join('\n  ')}`)
    return 1
  }
  return 0
}
