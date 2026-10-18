// pixels.ts — sharp 原始像素的统一入口（包内 verify_colors / check_overlay /
// measure_korean / render_page 共用；每个 skill 脚本各带一份 hx/读图的时代随
// 归流结束）。
//
// ⚠ sharp 的 `raw()` 以 info.channels 为准（实测 ensureAlpha+removeAlpha 会被
// 优化掉、照样回 4 通道——poetry 包同结论）：一律 resolveWithObject + 按通道数
// 抽 RGB，不能假设 3 通道布局。
//
// 灰度不用 sharp().grayscale()（libvips 系数与 PIL convert("L") 不同，AA 边缘
// 像素会漂）：用 PIL 的整数公式 (R*19595+G*38470+B*7471+0x8000)>>16 逐像素算。
import sharp from 'sharp'

export interface Rgb {
  data: Uint8Array
  width: number
  height: number
}

/** 任意 PNG → 3 通道 raw（PIL `convert("RGB")` 语义：丢 alpha 通道，不混合）。 */
export async function rgbRaw(path: string): Promise<Rgb> {
  const { data, info } = await sharp(path).raw().toBuffer({ resolveWithObject: true })
  const n = info.channels
  const px = info.width * info.height
  const out = new Uint8Array(px * 3)
  if (n === 3) {
    out.set(data.subarray(0, px * 3))
  } else {
    for (let i = 0; i < px; i++) {
      out[i * 3] = data[i * n]!
      out[i * 3 + 1] = data[i * n + 1]!
      out[i * 3 + 2] = data[i * n + 2]!
    }
  }
  return { data: out, width: info.width, height: info.height }
}

/** PIL convert("L") 的整数舍入公式（RGB → 8bit 灰度）。 */
export function pilL(r: number, g: number, b: number): number {
  return (r * 19595 + g * 38470 + b * 7471 + 0x8000) >> 16
}

/** `#rrggbb` → [r, g, b]（Python `tuple(int(s[i:i+2], 16) for i in range(0, 6, 2))`）。 */
export function hex6(s: string): [number, number, number] {
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)]
}
