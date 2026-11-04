// grid.ts — 帧网格吸附（音画时间轴的唯一实现）。
//
// 为什么在 core：网格吸附是**跨产线的底座**——karaoke-video 的状态帧、
// music-annotate-video 的教学帧、storyteller 的幕帧都要把时长对齐到
// 「整帧」，口径必须唯一：ceil(d×fps−1e-9)/fps。把它放 core 是 library
// 层（≥2 个 skill 共用），不许在产线包里各写一份。
//
// 为什么要向上吸附而不是就近：时间轴是**累计**的——每一段都向上取整，
// 段与段之间才不会累积漂移；就近取整会让误差在长片里滚雪球。
//
// 为什么要减 1e-9：浮点表示误差会让「正好 30 帧」算成 30.000000000000004，
// ceil 后多出一帧。减掉这个微小量，边界值才落在正确的那一格。

/** 本工作区的默认帧率（30fps CFR）。 */
export const FPS_DEFAULT = 30

/** 时长吸附到帧网格（向上）。d=1.0@30 → 1.0；d=0.0334@30 → 2/30。 */
export function snapToGrid(d: number, fps: number = FPS_DEFAULT): number {
  return Math.ceil(d * fps - 1e-9) / fps
}

/** 时长对应的帧数（向上）。d=1.0@30 → 30；d=0.0334@30 → 2。
 *
 * d=0 时返回 0 而不是 -0：`Math.ceil(-1e-9)` 是 -0，`Object.is(-0, 0)` 是
 * false——别让一个零帧场景在断言里以「差一个负零」的形式炸掉。 */
export function framesFor(d: number, fps: number = FPS_DEFAULT): number {
  const n = Math.ceil(d * fps - 1e-9)
  return n === 0 ? 0 : n
}

/** 帧号 → 秒（帧号从 0 起）。 */
export function frameToSec(frame: number, fps: number = FPS_DEFAULT): number {
  return frame / fps
}
