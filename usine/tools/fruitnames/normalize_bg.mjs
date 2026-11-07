// normalize_bg.mjs — 一次性诊断/工具：把生成图的底色归一化到目标纸色
//
// 为什么走「归一化」而不是「抠透明」：
//   2026-11-06 实测，Matrix 出的 jpg 底色带**JPEG 4:2:0 色度块伪影**——
//   平坦底区在 RGB 距离下呈 1/62/65 的规律跳变（实测），任何基于
//   「与底色距离」的阈值都会被伪影打穿：硬连通只填到全图的 0.1%。
//   抠透明这条路在这条素材上不可靠。
//
//   但**归一化可靠**：底色本来就是一块平色，问题是它的**实际颜色**
//   随位置漂移。做法 = 把整幅图的底色区域整体拉向目标纸色，主体颜色
//   保持不变（只对「接近底色」的像素做偏移）。
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(join(resolve(here, '..', '..'), 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

/**
 * 把 src 的底色归一化到 target（hex 或 rgb），写出到 out。
 * 主体像素（明显不像底色的）保持原样；底色像素按「最近底色样点」的偏移整体平移。
 */
export async function normalizeBg(srcPath, outPath, target = '#fffcf5') {
  const meta = await sharp(srcPath).metadata()
  const W = meta.width
  const H = meta.height
  const { data } = await sharp(srcPath).removeAlpha().raw().toBuffer({ resolveWithObject: true })

  // 目标色
  const t = target.startsWith('#')
    ? [1, 3, 5].map((i) => parseInt(target.slice(i, i + 2), 16))
    : target.split(',').map(Number)

  // 底色众数（4 级量化，抗 JPEG 噪声）
  const counts = new Map()
  for (let y = 0; y < H; y += 2) {
    for (let x = 0; x < W; x += 2) {
      const o = (y * W + x) * 3
      const k = ((data[o] >> 2) << 12) | ((data[o + 1] >> 2) << 6) | (data[o + 2] >> 2)
      counts.set(k, (counts.get(k) ?? 0) + 1)
    }
  }
  let best = -1
  let bk = 0
  for (const [k, c] of counts) {
    if (c > best) { best = c; bk = k }
  }
  const bg = [((bk >> 12) & 63) << 2, ((bk >> 6) & 63) << 2, (bk & 63) << 2]

  // 底色区 = 与众数色距离小的像素；用**亮度加权**距离（色度块伪影主要在
  // 色度通道，亮度通道稳得多），阈值放宽以覆盖整块底。
  const out = Buffer.alloc(W * H * 3)
  let touched = 0
  for (let q = 0; q < W * H; q++) {
    const i = q * 3
    const dr = data[i] - bg[0], dg = data[i + 1] - bg[1], db = data[i + 2] - bg[2]
    // 亮度距离权重最大（3 倍），色度各 1 倍
    const dl = 0.299 * dr + 0.587 * dg + 0.114 * db
    const dist = Math.abs(dl) * 3 + Math.abs(dr - dl) + Math.abs(dg - dl) + Math.abs(db - dl)
    if (dist <= 90) {
      // 平移到目标色（底色区整体偏移，色块伪影同时被抹平）
      out[i] = Math.max(0, Math.min(255, data[i] + (t[0] - bg[0])))
      out[i + 1] = Math.max(0, Math.min(255, data[i + 1] + (t[1] - bg[1])))
      out[i + 2] = Math.max(0, Math.min(255, data[i + 2] + (t[2] - bg[2])))
      touched++
    } else {
      out[i] = data[i]; out[i + 1] = data[i + 1]; out[i + 2] = data[i + 2]
    }
  }
  await sharp(out, { raw: { width: W, height: H, channels: 3 } })
    .png({ compressionLevel: 9 })
    .toFile(outPath)
  return { bg, target: t, touched, size: `${W}x${H}` }
}

if (process.argv[1] && process.argv[1].endsWith('normalize_bg.mjs')) {
  const [, , src, dst, tgt] = process.argv
  if (!src || !dst) {
    console.error('usage: node --import tsx tools/fruitnames/normalize_bg.mjs <in> <out> [#hex]')
    process.exit(2)
  }
  const r = await normalizeBg(src, dst, tgt ?? '#fffcf5')
  console.log(`归一化：${src} → ${dst} 底色 rgb(${r.bg.join(',')}) → rgb(${r.target.join(',')})，${r.touched} 像素`)
}
