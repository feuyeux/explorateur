// check_fused_glyph.mjs — **韩语融合音节渲染门**（`.ksyl.cv`）
//
// 背景（2026-10-20 实测事故）：海报模板的 `.ksyl.cv` 用了 `background:` 简写。
// 简写会把 `background-clip` 重置回 `border-box`；而 `.ksyl.cv` 的选择器权重
// (0,2,0) 高于 `.cv`/`.ksyl` 的 `background-clip: text` (0,1,0) → 渐变不再被
// 裁到字形里，而是画满整个 inline-block 盒子 → 融合音节渲染成**实心色块**
// （ep04「토」、ep11「버」中招）。
// 视频侧 `video_style.css` 没有 `.ksyl.cv` 规则，所以**成片正常、只有海报/封面坏**——
// 这类 bug 必须靠像素门抓，肉眼只盯一格很容易漏。
//
// 判据（在海报像素上自己算，不靠人工坐标）：
//   坏渲染 = 一整块**实心矩形**（红蓝渐变填满盒子，盒内无纸色）。
//   好渲染 = 逐笔画上色，最大实心块是**细长条**（笔画本身），笔画之间有纸色。
// 所以：量「彩色像素的最大实心轴对齐矩形」。
//   实测 12 期（2x 渲染，本系列自己的韩语子集字体）：
//     正常各期  38x337 / 38x336 / 40x351 / 203x20 / 303x31 / 304x31 / 19x167
//     坏色块    134x134（ep04 토）/ 135x134（ep11 버）
//   判据：短边 ≥ 60px 且长宽比 < 3 → 失败。
//   （「实心块」本身不是病——正常横/竖笔画就是实心的；**又大又方正**才是病。
//     韩文假名的横向笔画长、纵向笔画窄，都呈细长条，不会误判。）
//
// Usage: node --import tsx tools/foodnames/check_fused_glyph.mjs --out <期目录>
//        [--poster poster.png] [--scale 2]
// 退出码：0 通过；1 检出色块（响亮失败）。
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { hex6, rgbRaw } from '../../packages/poster/src/pixels.ts'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}
const OUT = resolve(arg('out'))
const SCALE = Number(arg('scale', '2'))
const RED = hex6('c9403a')
const BLUE = hex6('2f5d9e')
const TOL = 40

// 尺寸门：短边 ≥ 60px 且长宽比 < 3 → 判为「色块」
const MIN_SHORT = 60
const MAX_ASPECT = 3

const close = (p, t) =>
  Math.abs(p[0] - t[0]) <= TOL && Math.abs(p[1] - t[1]) <= TOL && Math.abs(p[2] - t[2]) <= TOL

// —— 1 韩语格词框（CSS px，来自 fit-diag 的 DIAG dump）——
const diagTxt = readFileSync(join(OUT, 'diag.txt'), 'utf8')
const dm = /<title>DIAG (\{.*?\})<\/title>/s.exec(diagTxt)
if (!dm) {
  console.error('✖ diag.txt 里没有 DIAG 诊断（先跑 fit-diag）')
  process.exit(1)
}
const cells = JSON.parse(dm[1]).cells
const koCell = cells.find((c) => c.lang === '韩语')
if (!koCell) {
  console.error('✖ diag 里没有「韩语」格')
  process.exit(1)
}
const [kx, ky, kw, kh] = koCell.word.map(Number)

// —— 2 读海报像素 ——
const posterPath = join(OUT, arg('poster', 'poster.png'))
const { data, width: W, height: H } = await rgbRaw(posterPath)
const px = (x, y) => {
  const o = (y * W + x) * 3
  return [data[o], data[o + 1], data[o + 2]]
}

// CSS px → 设备 px
const x0 = Math.max(0, Math.round(kx * SCALE))
const y0 = Math.max(0, Math.round(ky * SCALE))
const x1 = Math.min(W, Math.round((kx + kw) * SCALE))
const y1 = Math.min(H, Math.round((ky + kh) * SCALE))

const cw = x1 - x0
const ch = y1 - y0
const mask = new Uint8Array(cw * ch)
for (let y = 0; y < ch; y++) {
  for (let x = 0; x < cw; x++) {
    const p = px(x0 + x, y0 + y)
    if (close(p, RED) || close(p, BLUE)) mask[y * cw + x] = 1
  }
}

// —— 3 最大实心轴对齐矩形（直方图栈，与 measure_korean.largestRect 同法）——
function largestSolidRect(m) {
  const h = new Array(cw + 1).fill(0)
  let best = { area: 0, w: 0, h: 0 }
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) h[x] = m[y * cw + x] ? h[x] + 1 : 0
    const stack = []
    for (let x = 0; x <= cw; x++) {
      const cur = x < cw ? h[x] : 0
      let start = x
      while (stack.length > 0 && stack[stack.length - 1][1] > cur) {
        const [sx, sh] = stack.pop()
        const area = sh * (x - sx)
        if (area > best.area) best = { area, w: x - sx, h: sh }
        start = sx
      }
      if (stack.length === 0 || stack[stack.length - 1][1] < cur) stack.push([start, cur])
    }
  }
  return best
}

const best = largestSolidRect(mask)
const shortSide = Math.min(best.w, best.h)
const aspect = shortSide > 0 ? Math.max(best.w, best.h) / shortSide : Infinity

console.log(`韩语格词框 (CSS px): ${kx},${ky},${kw},${kh} → 设备 px ${x0},${y0},${x1},${y1}`)
console.log(`彩色最大实心矩形: ${best.w}x${best.h}（短边 ${shortSide}，长宽比 ${aspect.toFixed(2)}）`)

if (best.area > 0 && shortSide >= MIN_SHORT && aspect < MAX_ASPECT) {
  console.error('')
  console.error('✖ 检出实心色块：韩语融合音节的渐变没有裁到字形里。')
  console.error(`  ${best.w}x${best.h} 实心块（短边 ${shortSide} ≥ ${MIN_SHORT}，长宽比 ${aspect.toFixed(2)} < ${MAX_ASPECT}）`)
  console.error('  典型原因：CSS 规则用了 `background:` 简写 —— 简写会把')
  console.error('  `background-clip` 重置回 border-box，导致渐变画满整个盒子。')
  console.error('  修法：用 `background-image:` 长写，并在同一条规则里自带')
  console.error('  `-webkit-background-clip: text; background-clip: text; color: transparent;`')
  process.exit(1)
}
console.log('✓ 无实心色块 —— 融合音节渲成渐变字形')
