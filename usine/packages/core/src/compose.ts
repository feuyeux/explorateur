// compose.ts — 母版叠加合成（compose.py 的 TS 移植：H3 母版 + 文字层 + 人声轨 → 成片）。
//
// ffmpeg 走 resolver；滤镜图是纯函数，可被反向验证直接断言。
//
// **两声道与两次响度**：
// - 人声轨先经 audio.composeTrack（轨道级 loudnorm −16、apad 前置）；
// - 终混在**长度已锁死**的混合流上再过一次 loudnorm（社媒目标 −14 LUFS——
//   直送只有 −20，太轻）。此时流内没有 apad，「apad 必须在 loudnorm 前」
//   不被违反：所有 apad 都在 loudnorm 之前完成。
//
// **禁用 `-shortest`**：在 rawvideo 管道 + 并发场景下它是**时机性丢帧**开关
// （批量渲丢 pts 帧、单渲不丢，幂等必挂）。裁到目标时长的真实功能交给显式
// `-t dur`——**封装命令里不许有依赖 I/O 时序的取舍开关**。
//
// `line_spans` 的口径：每行字幕多留 HOLD 拍，行间不重叠（min(尾拍, 下一行起点)）。
import { spawnSync } from "node:child_process"

import { FeuilleError } from "./errors.js"
import { roundHalfEven } from "./num.js"
import { ffmpeg as resolveFfmpeg } from "./platform.js"

/** 每行的上屏区间 [t0, t1]：t0 = 起点，t1 = min(本行末 + hold, 下一行起点)。
 *
 * 末行以 total 收尾。行间永不重叠——下一行的起点就是本行的硬上限。
 */
export function lineSpans(
  starts: readonly number[],
  durs: readonly number[],
  opts: { total: number; hold?: number },
): [number, number][] {
  const hold = opts.hold ?? 0.3
  const spans: [number, number][] = []
  for (let i = 0; i < starts.length; i++) {
    const t0 = starts[i]!
    const t1 = t0 + durs[i]!
    const nxt = i + 1 < starts.length ? starts[i + 1]! : null
    const end = nxt !== null ? Math.min(t1 + hold, nxt) : Math.min(t1 + hold, opts.total)
    spans.push([roundHalfEven(t0, 3), roundHalfEven(end, 3)])
  }
  return spans
}

/** 构建终混滤镜图（纯函数，供 mux 与反向验证共用）。
 *
 * 输入布局：0=母版（视频+配乐），1=人声，2..n=文字层 PNG。
 * overlay 的 {y} / {between} 是留给 mux 按层填的槽；dur 直接内插。
 * 返回 [滤镜图, 视频末段标签]。
 */
export function filterGraph(
  w: number,
  h: number,
  nOverlays: number,
  dur: number,
  opts: { musicVol?: number; loudnessI?: number; fps?: number } = {},
): [string, string] {
  const musicVol = opts.musicVol ?? 0.3
  const loudnessI = opts.loudnessI ?? -14
  const fps = opts.fps ?? 24
  const fc: string[] = [`[0:v]scale=${w}:${h}:flags=lanczos,fps=${fps}[base]`]
  let cur = "base"
  for (let i = 0; i < nOverlays; i++) {
    const nxt = `v${i}`
    fc.push(`[${cur}][${i + 2}:v]overlay=0:{y}:enable='between(t,{between})'[${nxt}]`)
    cur = nxt
  }
  fc.push(`[0:a]volume=${musicVol}[bg]`)
  fc.push(`[1:a]apad=whole_dur=${dur.toFixed(3)},atrim=0:${dur.toFixed(3)}[vo]`)
  // 终混 loudnorm：流长已锁死（见模块头），apad 全部在它之前——坑③不被违反
  fc.push(
    `[bg][vo]amix=inputs=2:normalize=0,loudnorm=I=${loudnessI}:TP=-1.5:LRA=11[aout]`,
  )
  return [fc.join(";"), cur]
}

/** 文字层：PNG 路径 + y 偏移 + 上屏时间窗（enable='between(t,t0,t1)'）。 */
export interface Overlay {
  png: string
  y: number
  t0: number
  t1: number
}

/** 母版 + 文字层叠加 + 双声道终混 → 成片。
 *
 * overlays 的索引别和 ffmpeg 输入序号混（0=母版 1=人声 2..=文字层）。
 */
export function mux(
  master: string,
  voice: string,
  overlays: readonly Overlay[],
  out: string,
  opts: {
    w: number
    h: number
    dur: number
    musicVol?: number
    loudnessI?: number
    fps?: number
    preset?: string
    crf?: number
  },
): string {
  const ffmpeg = resolveFfmpeg()
  if (ffmpeg === null) {
    throw new FeuilleError("缺 ffmpeg（resolver 未找到；缺件清单见 platform.missing()）")
  }
  const [graph, vlabel] = filterGraph(opts.w, opts.h, overlays.length, opts.dur, {
    musicVol: opts.musicVol,
    loudnessI: opts.loudnessI,
    fps: opts.fps,
  })
  // 把每层 overlay 的 y / 时间窗填回图里（纯函数留槽，这里按序填值）
  let filled = graph
  for (const { y, t0, t1 } of overlays) {
    filled = filled.replace("{y}", String(y)).replace("{between}", `${t0.toFixed(3)},${t1.toFixed(3)}`)
  }
  const cmd: string[] = [ffmpeg, "-y", "-i", master, "-i", voice]
  for (const { png } of overlays) cmd.push("-i", png)
  cmd.push(
    "-filter_complex", filled,
    "-map", `[${vlabel}]`, "-map", "[aout]",
    "-c:v", "libx264", "-preset", opts.preset ?? "slow", "-crf", String(opts.crf ?? 18),
    "-pix_fmt", "yuv420p", "-profile:v", "high",
    "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
    "-movflags", "+faststart",
    // -shortest 已废（坑⑯，见模块头）：时长控制显式交给 -t
    "-t", opts.dur.toFixed(3), out,
  )
  const p = spawnSync(ffmpeg, cmd.slice(1), { encoding: "utf8" })
  if (p.status !== 0) {
    throw new Error(`ffmpeg 失败：\n${(p.stderr ?? "").slice(-2500)}`)
  }
  return out
}
