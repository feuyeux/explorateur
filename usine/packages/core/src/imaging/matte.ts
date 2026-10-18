// matte.ts — 双 matte 抠像（textlayer.matte_combine 的 TS 移植，sharp 承载）。
//
// 数学（与 Python 逐式一致）：
//   C_w - C_b = (1-a)·255 → alpha = 255 - max(C_w - C_b, 通道维)
//   去预乘 rgb = C_b / a（alpha 下限 1e-4 防除零）
// 半透明投影可精确还原；astype(uint8) 是**截断**不是四舍五入（Python 侧口径）。
//
// 同一输入 PNG 下与 Python 输出应逐像素相等（纯浮点同序运算）；栅格化差异
// 只存在于截图生成侧（Edge），不在本函数——它只做解码后的纯数学。
import sharp from "sharp"

export interface AlphaStats {
  size: [number, number]
  coverage: number
  alphaMeanNonzero: number
  alphaMax: number
  bbox: [number, number, number, number]
}

/**
 * 白底/黑底两次截图 → 精确 alpha 的 RGBA PNG Buffer。
 * （sharp 解码是异步的，无法同步包成实例流——统一走 Buffer 入口。）
 */
export async function matteCombineBuffer(pngW: string | Buffer, pngB: string | Buffer): Promise<Buffer> {
  const [w, b, meta] = await Promise.all([
    sharp(pngW).removeAlpha().raw().toBuffer({ resolveWithObject: true }),
    sharp(pngB).removeAlpha().raw().toBuffer({ resolveWithObject: true }),
    sharp(pngW).metadata(),
  ])
  const { width, height } = meta
  if (!width || !height) throw new Error("matte: 无法读取图像尺寸")
  const n = width * height
  const out = Buffer.alloc(n * 4)
  for (let i = 0; i < n; i++) {
    const p3 = i * 3, p4 = i * 4
    let dmax = -Infinity
    for (let c = 0; c < 3; c++) {
      const d = w.data[p3 + c]! - b.data[p3 + c]!
      if (d > dmax) dmax = d
    }
    const alpha = Math.min(255, Math.max(0, 255 - dmax))
    const a = Math.max(alpha / 255, 1e-4)
    for (let c = 0; c < 3; c++) {
      out[p4 + c] = Math.trunc(Math.min(255, Math.max(0, b.data[p3 + c]! / a)))
    }
    out[p4 + 3] = alpha
  }
  return sharp(out, { raw: { width, height, channels: 4 } }).png().toBuffer()
}

/** alpha 通道结构统计（金样本纪律：比 coverage / 均值 / 包围盒，不比像素）。 */
export async function alphaStats(png: string | Buffer): Promise<AlphaStats> {
  const { data, info } = await sharp(png)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  const n = info.width * info.height
  let nonzero = 0, sum = 0, max = 0
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1
  for (let i = 0; i < n; i++) {
    const a = data[i * 4 + 3]!
    if (a > 0) {
      nonzero++
      sum += a
      if (a > max) max = a
      const x = i % info.width, y = Math.floor(i / info.width)
      if (x < x0) x0 = x
      if (x > x1) x1 = x
      if (y < y0) y0 = y
      if (y > y1) y1 = y
    }
  }
  return {
    size: [info.width, info.height],
    coverage: nonzero / n,
    alphaMeanNonzero: nonzero ? sum / nonzero : 0,
    alphaMax: max,
    bbox: nonzero ? [x0, y0, x1, y1] : [0, 0, -1, -1],
  }
}
