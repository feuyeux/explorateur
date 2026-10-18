// @feuille/karaoke — karaoke-video 产线归流包（skills/karaoke-video/scripts/*.py 的 TS 唯一实现）。
//
// 使用契约：
// 1. edge-tts 协议、ffprobe 时长探测、浏览器/ffmpeg 解析一律消费
//    @feuille/core 的唯一实现（tts.stream / audio.probeDuration /
//    platform.*），包内零重复——这是 P5-7 归流纪律，不是风格偏好。
// 2. verify_sync 与 scan_blank 是**验收门禁**：门禁全绿 ≠ 做对了
//    （见 skills/karaoke-video/references/delivery-check.md），后者列了
//    必须亲手看的时刻。
// 3. 本包不碰发布、不碰 H3/Hailuo——产线边界见 SKILL.md 的归属表。
export * as gen_tts from './gen_tts.js'
export * as build_video from './build_video.js'
export * as verify_sync from './verify_sync.js'
export * as scan_blank from './scan_blank.js'
