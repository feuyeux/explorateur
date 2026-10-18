// render.ts — 帧编码基座（render.py 的 TS 移植：rawvideo → ffmpeg 管道）。
//
// encodeFrames 只管视频帧；音频合成与终混在 audio / compose，
// 卡片级编排由调用方组合 rig + scenes + timeline + textlayer 完成。
//
// 口径：`-f rawvideo -pix_fmt rgb24 -s WxH -r FPS` 管道输入；libx264 / yuv420p /
// `+faststart` 输出；时长控制 = 显式 `-t dur`（与 compose.mux 同口径）。
//
// 硬约定：
// - 不用 `-shortest`——它是时机性丢帧开关（高并发下丢 pts 帧、单渲不丢，
//   framehash 幂等必挂）。
// - ffmpeg 经 resolver，找不到显式报缺。
// - 非零退出显式抛错，坏产物不静默留盘（纪律 19）。
// - 帧数契约：调用方须供足 ⌈dur×fps⌉ 帧；帧不足时 rawvideo 流先尽、
//   产物短于 dur 且无提示——不做静默补帧。
// - preset 默认 slow（单件质量口径，与 compose.mux 对齐；调用方可覆盖）。
import { spawn } from "node:child_process"
import { once } from "node:events"

import sharp from "sharp"

import { FeuilleError } from "./errors.js"
import { ffmpeg as resolveFfmpeg } from "./platform.js"

/** 帧源：raw rgb24 字节（恰好 w×h×3），或 sharp 实例（非 RGB 自动转——
 * removeAlpha 对齐 PIL convert("RGB") 的「丢 alpha 不合成」口径）。 */
export type Frame = Buffer | Uint8Array | ReturnType<typeof sharp>

async function frameToRgb(frame: Frame, w: number, h: number): Promise<Buffer> {
  const bytes =
    Buffer.isBuffer(frame) || frame instanceof Uint8Array
      ? Buffer.from(frame.buffer, frame.byteOffset, frame.byteLength)
      : await frame.removeAlpha().toColorspace("srgb").raw().toBuffer()
  if (bytes.length !== w * h * 3) {
    throw new FeuilleError(
      `帧字节长度 ${bytes.length} ≠ ${w}×${h}×3（rawvideo 流会错位——检查帧尺寸与像素格式）`,
    )
  }
  return bytes
}

/** 逐帧喂 raw rgb24 的 rawvideo→ffmpeg 编码器；返回实际喂入的帧数。
 *
 * 防御直喂错位：非 Buffer 帧（sharp 图层）自动转 RGB；字节数不符显式抛错。
 * ffmpeg 非零退出抛错（消息含已喂帧数）。
 */
export async function encodeFrames(
  frames: AsyncIterable<Frame>,
  outMp4: string,
  opts: { w: number; h: number; fps: number; dur: number; crf?: number; preset?: string },
): Promise<number> {
  const ffmpeg = resolveFfmpeg()
  if (ffmpeg === null) {
    throw new FeuilleError("缺 ffmpeg（resolver 未找到；缺件清单见 platform.missing()）")
  }
  const { w, h, fps, dur } = opts
  const crf = opts.crf ?? 18
  const preset = opts.preset ?? "slow"
  // 禁用 -shortest：EOF 冲刷时按已入队包随时机丢视频帧（实测高并发批量下
  // 丢帧、单渲不丢 → framehash 幂等必挂）。纯视频管道，-t dur 是唯一时长开关。
  const proc = spawn(
    ffmpeg,
    [
      "-y",
      "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", `${w}x${h}`, "-r", String(fps), "-i", "-",
      "-c:v", "libx264", "-preset", preset, "-crf", String(crf), "-pix_fmt", "yuv420p",
      "-t", String(dur), "-movflags", "+faststart", outMp4,
    ],
    { stdio: ["pipe", "ignore", "ignore"] },
  )
  // ffmpeg 中途退出时 stdin 写入抛 EPIPE——close 的非零退出码才是正式报错通道
  proc.stdin.on("error", () => {})
  let n = 0
  let frameErr: unknown = null
  try {
    for await (const frame of frames) {
      const bytes = await frameToRgb(frame, w, h)
      if (!proc.stdin.write(bytes)) await once(proc.stdin, "drain")
      n++
    }
  } catch (e) {
    // 坏帧先记下，stdin 照常收尾让 ffmpeg 干净退出（不留悬垂进程）
    frameErr = e
  }
  proc.stdin.end()
  const [rc] = (await once(proc, "close")) as [number | null, NodeJS.Signals | null]
  if (frameErr !== null) throw frameErr
  if (rc !== 0) {
    throw new Error(`ffmpeg 退出码 ${rc}（已喂 ${n} 帧）→ ${outMp4}`)
  }
  return n
}
