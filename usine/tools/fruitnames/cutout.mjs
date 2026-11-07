// cutout.mjs — 本地抠底：奶油底图 → 透明 PNG（软边，不留色边）
//
// 为什么需要它：Matrix 的服务端去背（remove_image_background）要 5 积分且
// 账号未开自动消耗 → 402（2026-11-06 实测）。开自动消耗是**付费设置**，
// 不能擅自替用户点，所以走本地抠。
//
// 为什么不能按「近白」抠：第一版用「接近白 → 背景」判据，把**彩色苹果**
// 整个判成了背景（实测输出是一排黑白线稿的透明图）。教训：
//   ① 判据必须是**底色**（本线是奶油底），不是「白」；
//   ② 且必须与**边界连通**——主体内部的浅色高光颜色与底色相近但不连通。
//
// 为什么硬阈值连通会失败（JPEG 伪影）：2026-11-06 实测，生成图是 JPEG，
// 平坦奶油底上被压缩器切成**块状伪影**，按颜色距离做的 near 掩膜在顶行
// 呈 `100100100…` 规律间断 ⇒ 四邻洪水填充只能扩散到边界上 702 个像素
// （占全图 0.1%），底色根本抠不掉。
//   ⇒ 对策：**先降噪再判定**。用 blur(σ=1.2) 把 JPEG 块效应抹平，
//     在**平滑后**的图上判连通；阈值同时放宽（底色带噪声，L1 距离可到 60+）。
import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// sharp 是 @feuille/karaoke 的依赖（状态帧渲染用），pnpm 隔离布局下只在那个包
// 里有实体——工具层用 createRequire 指定解析根，不改依赖布局。
const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(join(resolve(here, '..', '..'), 'packages', 'karaoke', 'package.json'))
const sharp = require('sharp')

/** 底色：取**整图众数色**。
 *  不能用四角取样——2026-11-06 实测：水果插画常常顶到边角（叶子/果身
 *  画到画框上），四角取样拿到的是叶子绿或果红，于是底色判错。
 */
function dominantColor(data, width, height) {
  const counts = new Map()
  for (let y = 0; y < height; y += 2) {
    for (let x = 0; x < width; x += 2) {
      const o = (y * width + x) * 3
      const k = ((data[o] >> 2) << 12) | ((data[o + 1] >> 2) << 6) | (data[o + 2] >> 2)
      counts.set(k, (counts.get(k) ?? 0) + 1)
    }
  }
  let best = -1
  let bestK = 0
  for (const [k, c] of counts) {
    if (c > best) { best = c; bestK = k }
  }
  return [((bestK >> 12) & 63) << 2, ((bestK >> 6) & 63) << 2, (bestK & 63) << 2]
}

/**
 * 抠底。
 * @param {string} srcPath 源图（jpg）
 * @param {string} outPath 输出透明 PNG
 */
export async function cutout(srcPath, outPath) {
  const meta = await sharp(srcPath).metadata()
  const W = meta.width
  const H = meta.height
  const { data } = await sharp(srcPath).removeAlpha().raw().toBuffer({ resolveWithObject: true })

  // ① 平滑图：抹掉 JPEG 块效应，后续判定在它上面做
  const smoothed = await sharp(srcPath)
    .removeAlpha()
    .blur(1.2)
    .raw()
    .toBuffer({ resolveWithObject: true })

  const bg = dominantColor(smoothed.data, W, H)
  const dist = (buf, i) => Math.abs(buf[i] - bg[0]) + Math.abs(buf[i + 1] - bg[1]) + Math.abs(buf[i + 2] - bg[2])

  // ② 近底色掩膜（判据用平滑图，容忍 JPEG 噪声）
  const TOL = 60
  const near = new Uint8Array(W * H)
  for (let q = 0; q < W * H; q++) {
    if (dist(smoothed.data, q * 4) <= TOL) near[q] = 1
  }

  // ③ 从四边洪水填充 → 只保留与边界连通的底色（主体内部高光不受影响）
  const mask = new Uint8Array(W * H)
  const stack = []
  const push = (x, y) => {
    if (x < 0 || y < 0 || x >= W || y >= H) return
    const q = y * W + x
    if (mask[q] || !near[q]) return
    mask[q] = 1
    stack.push(q)
  }
  for (let x = 0; x < W; x++) { push(x, 0); push(x, H - 1) }
  for (let y = 0; y < H; y++) { push(0, y); push(W - 1, y) }
  while (stack.length) {
    const q = stack.pop()
    const x = q % W, y = (q / W) | 0
    push(x + 1, y); push(x - 1, y); push(x, y + 1); push(x, y - 1)
  }

  // ④ 输出：连通背景 → 全透明；其余按「离底色多远」给软 alpha（抗锯齿不留色边）
  const out = Buffer.alloc(W * H * 4)
  let transparent = 0
  const SOFT = 110
  for (let q = 0; q < W * H; q++) {
    const i = q * 4
    const r = data[i], g = data[i + 1], b = data[i + 2]
    if (mask[q]) {
      out[i] = r; out[i + 1] = g; out[i + 2] = b; out[i + 3] = 0
      transparent++
      continue
    }
    const d = dist(data, i)
    let a = 1
    if (d < SOFT) {
      const t = d / SOFT
      a = t * t * (3 - 2 * t)
    }
    out[i] = r; out[i + 1] = g; out[i + 2] = b
    out[i + 3] = Math.round(a * 255)
  }
  await sharp(out, { raw: { width: W, height: H, channels: 4 } })
    .png({ compressionLevel: 9 })
    .toFile(outPath)
  return { transparent, bg, size: `${W}x${H}` }
}

// 直接运行时：node --import tsx tools/fruitnames/cutout.mjs <in> <out>
if (process.argv[1] && process.argv[1].endsWith('cutout.mjs')) {
  const [, , src, dst] = process.argv
  if (!src || !dst) {
    console.error('usage: node --import tsx tools/fruitnames/cutout.mjs <in.jpg> <out.png>')
    process.exit(2)
  }
  const r = await cutout(src, dst)
  console.log(`抠底完成：${src} → ${dst}（底色 rgb(${r.bg.join(',')})，${r.transparent} 像素转透明）`)
}
