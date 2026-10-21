// audio.ts — ffmpeg 音轨合成与时长探测（audio.py 的 TS 移植）。
//
// 滤镜图是纯函数，顺序纪律可被反向验证直接断言。此逻辑全仓只有一份：
// 两条管线各写一份时，修复只落一侧，另一侧继续随机出片。
//
// **apad 必须在 loudnorm 之前，顺序不许动**（实测的非确定竞态）：loudnorm
// 内部升采样到 192k，之后接 apad 是非确定的 EOF 冲刷竞态——同命令 10 连跑
// 丢补尾 3 次（9.469s），前置后 10/10 全 10.0s。loudnorm 是门控响度，补的
// 静音不改变增益；对已 ≥dur 的流是 no-op。
//
// `atrim` 只裁不补：amix 的输出止于最长行的**原始 mp3 尾**（非裁尾时长）。
import { execFileSync } from "node:child_process"

import { pyFloat, roundHalfEven } from "./num.js"
import { ffmpeg as resolveFfmpeg, ffprobe as resolveFfprobe, requireTool } from "./platform.js"

/** 构建 filter_complex 字符串（纯函数，供 composeTrack 与反向验证共用）。
 *
 * n==1 也过一层 anull：PCM 不变（anull 直通），但滤镜链形状统一、不必分支
 * （否则 mix 直连与 anull 两条分支的实现容易就此漂移）。
 */
export function filterGraph(
  n: number,
  starts: readonly number[],
  dur: number,
  loudnessI = -16,
): string {
  const fc: string[] = []
  starts.forEach((s, i) => {
    const ms = roundHalfEven(s * 1000)
    fc.push(`[${i}:a]adelay=${ms}|${ms}[a${i}]`)
  })
  let mixin = ""
  for (let i = 0; i < n; i++) mixin += `[a${i}]`
  fc.push(n > 1 ? `${mixin}amix=inputs=${n}:normalize=0[m]` : `${mixin}anull[m]`)
  const durS = pyFloat(dur)
  // 坑③：apad 必须在 loudnorm 之前（见模块头）——顺序是纪律，不许动
  fc.push(`[m]apad=whole_dur=${durS},loudnorm=I=${loudnessI}:TP=-1.5:LRA=11,atrim=0:${durS}[out]`)
  return fc.join(";")
}

/** 把逐行音频按 starts 延迟叠加、归一化响度、补齐到恰好 dur 秒。 */
export function composeTrack(
  lineFiles: readonly string[],
  starts: readonly number[],
  dur: number,
  outM4a: string,
  loudnessI = -16,
): void {
  const ffmpeg = requireTool(resolveFfmpeg(), "ffmpeg")
  const inputs: string[] = []
  for (const f of lineFiles) {
    inputs.push("-i", f)
  }
  const fc = filterGraph(lineFiles.length, starts, dur, loudnessI)
  execFileSync(
    ffmpeg,
    ["-y", ...inputs, "-filter_complex", fc, "-map", "[out]",
      "-c:a", "aac", "-b:a", "192k", "-ar", "44100", outM4a],
    { stdio: ["ignore", "pipe", "pipe"] },
  )
}

/** ffprobe 取容器时长（秒）。edge-tts 的 mp3 尾部垫了静音，
 * 词级真值裁尾（见 tts effectiveDur）要用它做上限。 */
export function probeDuration(path: string): number {
  const ffprobe = requireTool(resolveFfprobe(), "ffprobe")
  const out = execFileSync(
    ffprobe,
    ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  )
  return Number.parseFloat(out.trim())
}
