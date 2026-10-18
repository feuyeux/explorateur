// check_overlay.ts — 双层叠印的层间配准检查（详见 references/script-coloring.md）。
// （promoted from skills/one-page-poster/scripts/check_overlay.py，P5-7e 归流）
//
// 比较**单层**渲染：
//
//   lay render = 整词底层单独渲（如红）
//   top render = 声母层单独渲（如蓝）
//
// 在词框内量：top 掩膜的最优整数位移、该位移下的未匹配 top 色占比、红独/蓝独
// 计数。验收：best shift (0,0) 且 unmatched ≈ 0 %（残余 = 抗锯齿）。
//
// Usage:
//   check-overlay <lay.png> <top.png> <x> <y> <w> <h> [--scale 2]
//                 [--red c9403a] [--blue 2f5d9e] [--radius 4]
//
// x/y/w/h 是 CSS px（乘 --scale 换算到设备像素 PNG）。单层渲染的做法：往成品
// HTML 里注入 `.stack .top { visibility:hidden }`（→ lay 渲）或
// `.stack .lay { visibility:hidden }`（→ top 渲）。
//
// IMPORTANT: 绝不在合成图（两层同时可见）上量配准——顶层盖住底层，重叠像素被
// 藏起来、每个指标都在说谎。只量单层渲染。
import { FeuilleError } from '@feuille/core'
import { hex6, rgbRaw } from './pixels.js'

interface Args {
  layPng: string
  topPng: string
  x: number
  y: number
  w: number
  h: number
  scale: number
  red: string
  blue: string
  radius: number
}

const USAGE = 'usage: feuille poster check-overlay <lay.png> <top.png> <x> <y> <w> <h>\n' +
  '                            [--scale 2] [--red c9403a] [--blue 2f5d9e] [--radius 4]'

function parseArgs(argv: string[]): { a: Args } | { code: number } {
  const pos: string[] = []
  let scale = 2
  let red = 'c9403a'
  let blue = '2f5d9e'
  let radius = 4
  const intArg = (v: string): number => {
    const n = Number(v)
    if (!Number.isInteger(n)) throw new FeuilleError(`${v} 不是整数`)
    return n
  }
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i]!
    const take = (): string => {
      const v = argv[++i]
      if (v === undefined) throw new FeuilleError(`${t} 缺值`)
      return v
    }
    if (t === '--scale') scale = intArg(take())
    else if (t === '--red') red = take()
    else if (t === '--blue') blue = take()
    else if (t === '--radius') radius = intArg(take()) // 位移搜索半径（设备 px）
    else if (t.startsWith('--')) throw new FeuilleError(`未知旗标：${t}`)
    else pos.push(t)
  }
  if (pos.length < 6) return { code: 2 }
  return {
    a: {
      layPng: pos[0]!, topPng: pos[1]!,
      x: intArg(pos[2]!), y: intArg(pos[3]!), w: intArg(pos[4]!), h: intArg(pos[5]!),
      scale, red, blue, radius,
    },
  }
}

interface Mask {
  d: Uint8Array
  w: number
  h: number
}

/** 词框内 |px - 目标色| 各通道 ≤45 的掩膜（numpy 切片越界静默收边——镜像）。 */
async function mask(path: string, a: Args, t: [number, number, number]): Promise<Mask> {
  const im = await rgbRaw(path)
  const x0 = a.x * a.scale
  const y0 = a.y * a.scale
  const ww = Math.min(a.w * a.scale, im.width - x0)
  const hh = Math.min(a.h * a.scale, im.height - y0)
  const d = new Uint8Array(Math.max(0, ww) * Math.max(0, hh))
  const { data, width: W } = im
  let i = 0
  for (let yy = 0; yy < hh; yy++) {
    const row = ((y0 + yy) * W + x0) * 3
    for (let xx = 0; xx < ww; xx++, i++) {
      const o = row + xx * 3
      const m = Math.max(
        Math.abs(data[o]! - t[0]),
        Math.abs(data[o + 1]! - t[1]),
        Math.abs(data[o + 2]! - t[2]),
      )
      d[i] = m <= 45 ? 1 : 0
    }
  }
  return { d, w: ww, h: hh }
}

export async function main(argv: string[]): Promise<number> {
  const parsed = parseArgs(argv)
  if ('code' in parsed) {
    console.error(USAGE)
    return parsed.code
  }
  const a = parsed.a
  const R = await mask(a.layPng, a, hex6(a.red))
  const B = await mask(a.topPng, a, hex6(a.blue))
  const count = (m: Mask): number => {
    let n = 0
    for (let i = 0; i < m.d.length; i++) if (m.d[i]) n++
    return n
  }
  const bSum = count(B)
  console.log(`bottom ink ${count(R)}  top ink ${bSum}`)

  // np.roll 是**环绕**移位（出界行卷到对面）——这是 Python 原版语义，逐位镜像：
  // 非零位移时卷出词框的 top 墨落在 R 稀疏区、记入未匹配，天然压低它们的得分。
  let best: [number, number, number] | null = null // [unmatched, dx, dy]
  for (let dx = -a.radius; dx <= a.radius; dx++) {
    for (let dy = -a.radius; dy <= a.radius; dy++) {
      let un = 0
      for (let y = 0; y < B.h; y++) {
        const sy = (((y - dy) % B.h) + B.h) % B.h
        for (let x = 0; x < B.w; x++) {
          if (!B.d[sy * B.w + ((((x - dx) % B.w) + B.w) % B.w)]) continue
          if (!R.d[y * B.w + x]) un++
        }
      }
      if (best === null || un < best[0]
        || (un === best[0] && (dx < best[1] || (dx === best[1] && dy < best[2])))) {
        best = [un, dx, dy]
      }
    }
  }
  const [un, dx, dy] = best!
  const frac = (100 * un) / Math.max(bSum, 1)
  console.log(`best shift dx=${dx} dy=${dy}  unmatched_top=${un}/${bSum} (${frac.toFixed(2)}%)`)
  let rOnly = 0
  let bOnly = 0
  for (let i = 0; i < R.d.length; i++) {
    if (R.d[i] && !B.d[i]) rOnly++
    else if (B.d[i] && !R.d[i]) bOnly++
  }
  console.log(`bottom-only (vowel glyphs expected): ${rOnly}   top-only (misregistration+aa): ${bOnly}`)
  const ok = dx === 0 && dy === 0 && frac < 2.0
  console.log(ok ? 'PASS' : 'FAIL — layers misregistered')
  return ok ? 0 : 1
}
