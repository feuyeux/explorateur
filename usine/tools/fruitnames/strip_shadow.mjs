// strip_shadow.mjs — 从奶油底插画里剥掉软投影（泛洪替换为纸色）+ 残影判据
//
// 为什么存在：image-01 的家法是「物体 + 产品照式软影」，提示词压不住
// （2026-11-07 两批实测 16+ 张全卡在投影轴，10+ 轮措辞探针无效）。
// 参考海报明确无投影 → 用程序剥，不让模型拖后腿。
//
// 原理：奶油底上的软影 = 从画布边缘向物体的**平滑暗坡**；主体描边是
// **陡沿**（近黑 vs 奶油，单步差 >100）。从四边出发 BFS，入口查「近底色」，
// 续行只查**局部步进平缓**（阴影坡再深也是平滑的）+ 距纸色的总深度上限
// （不闯进描边核心）。走过的像素整体替换成纸色。
//
// 残影判据（确定性，替代 VLM 的「有没有影子」）：剥完后统计「未泛洪、
// 距纸色 14~130、与泛洪区连通、连通域填充率高（紧凑斑块）」的像素量。
// 三类干扰都被几何条件排掉：轮廓抗锯齿沿（细长，填充率低）、果内奶油
// 高光（被描边核心包住，不与泛洪区连通）、果内彩色体色（同上）。
// 真投影是贴着背景的紧凑软斑，一抓一个准。
//
// 阈值（对 mmx 素材实测调的，改前先跑探针）：
//   T_NEAR  = 110 —— 种子（四边）与底色众数的最大通道差上限
//   T_STEP  = 12  —— BFS 相邻像素的最大通道差（软坡 1~3，描边 >100）
//   D_CAP   = 200 —— 续行像素距纸色的总深度上限（挡描边核心与深色主体）
//   SHADOW_MAX（在 gen_art.mjs）= 400 —— residue 超过即门禁不过
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const require2 = createRequire(join(resolve(here, '..', '..'), 'packages', 'karaoke', 'package.json'))
const sharp = require2('sharp')

const T_NEAR = 110
const T_STEP = 12
const D_CAP = 200

/**
 * 把 src 里从画布边缘连通的「底色 + 软影」区域替换成 paper 色，写出 out。
 * 返回 shadowResidue = 剥完后仍贴着背景的紧凑暗斑像素量（0 = 干净）。
 * 幂等：对已剥过的图再跑一次 = 无操作（底色区直接命中）。
 */
export async function stripShadow(srcPath, outPath, paper = '#fffcf5') {
  const { data, info } = await sharp(srcPath).removeAlpha().raw().toBuffer({ resolveWithObject: true })
  const W = info.width
  const H = info.height

  // 底色众数（4 级量化，同 normalize_bg 的口径）
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
  for (const [k, c] of counts) if (c > best) { best = c; bk = k }
  const bg = [((bk >> 12) & 63) << 2, ((bk >> 6) & 63) << 2, (bk & 63) << 2]

  const t = paper.startsWith('#') ? [1, 3, 5].map((i) => parseInt(paper.slice(i, i + 2), 16)) : paper.split(',').map(Number)
  const distPaper = (i) => Math.max(Math.abs(data[i] - t[0]), Math.abs(data[i + 1] - t[1]), Math.abs(data[i + 2] - t[2]))
  const distBg = (i) => Math.max(Math.abs(data[i] - bg[0]), Math.abs(data[i + 1] - bg[1]), Math.abs(data[i + 2] - bg[2]))

  // ---- Phase A：泛洪。种子查近底色；续行只查步进 + 深度上限
  const mask = new Uint8Array(W * H)
  const stack = []
  const seed = (q) => {
    if (mask[q]) return
    if (distBg(q * 3) > T_NEAR) return
    mask[q] = 1
    stack.push(q)
  }
  const walk = (q, from) => {
    if (mask[q]) return
    const i = q * 3
    const j = from * 3
    const step = Math.max(Math.abs(data[i] - data[j]), Math.abs(data[i + 1] - data[j + 1]), Math.abs(data[i + 2] - data[j + 2]))
    if (step > T_STEP) return
    if (distPaper(i) > D_CAP) return
    mask[q] = 1
    stack.push(q)
  }
  for (let x = 0; x < W; x++) { seed(x); seed((H - 1) * W + x) }
  for (let y = 0; y < H; y++) { seed(y * W); seed(y * W + W - 1) }
  while (stack.length) {
    const q = stack.pop()
    const x = q % W
    const y = (q / W) | 0
    if (x > 0) walk(q - 1, q)
    if (x < W - 1) walk(q + 1, q)
    if (y > 0) walk(q - W, q)
    if (y < H - 1) walk(q + W, q)
  }

  // ---- Phase B：走过区域 → 纸色
  let touched = 0
  for (let q = 0; q < W * H; q++) {
    if (!mask[q]) continue
    const i = q * 3
    data[i] = t[0]; data[i + 1] = t[1]; data[i + 2] = t[2]
    touched++
  }

  // ---- Phase C：残影判据（连通域几何，见文件头注）
  const cand = new Uint8Array(W * H)
  for (let q = 0; q < W * H; q++) {
    if (mask[q]) continue
    if (distPaper(q * 3) <= 14 || distPaper(q * 3) > 130) continue
    cand[q] = 1
  }
  const comp = new Int32Array(W * H).fill(-1)
  let shadowResidue = 0
  const compStack = []
  for (let s = 0; s < W * H; s++) {
    if (!cand[s] || comp[s] >= 0) continue
    const id = s
    compStack.length = 0
    compStack.push(s)
    comp[s] = id
    let area = 0
    let minX = W, maxX = 0, minY = H, maxY = 0
    let touchesBg = false
    while (compStack.length) {
      const q = compStack.pop()
      area++
      const x = q % W
      const y = (q / W) | 0
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx
          const ny = y + dy
          if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue
          const nq = ny * W + nx
          if (mask[nq]) touchesBg = true // 邻居是泛洪区 = 这个斑块贴着背景
          if (!cand[nq] || comp[nq] >= 0) continue
          comp[nq] = id
          compStack.push(nq)
        }
      }
    }
    const bw = maxX - minX + 1
    const bh = maxY - minY + 1
    const fill = area / (bw * bh)
    if (touchesBg && fill >= 0.45 && area >= 300) shadowResidue += area
  }

  await sharp(data, { raw: { width: W, height: H, channels: 3 } }).png({ compressionLevel: 9 }).toFile(outPath)
  return { bg, touched, ratio: +(touched / (W * H)).toFixed(3), shadowResidue, size: `${W}x${H}` }
}

if (process.argv[1] && process.argv[1].endsWith('strip_shadow.mjs')) {
  const [, , src, dst, tgt] = process.argv
  if (!src || !dst) {
    console.error('usage: node tools/fruitnames/strip_shadow.mjs <in> <out> [#hex]')
    process.exit(2)
  }
  const r = await stripShadow(src, dst, tgt ?? '#fffcf5')
  console.log(`去影：${src} → ${dst}（底色 rgb(${r.bg.join(',')})，替换 ${r.touched} 像素 = ${(r.ratio * 100).toFixed(1)}%，残影 ${r.shadowResidue}）`)
}
