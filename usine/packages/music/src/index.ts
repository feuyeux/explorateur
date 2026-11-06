// index.ts — @feuille/music — music-annotate-video 的 TS 归流包。
//
// 使用契约：
//
// 1. **不引入 librosa / pyin / DTW**。pyin 走 numba JIT：实测 CPU 471s +
//    提交内存 154GB，系统三次冻结全复现；子序列 DTW 的代价模型结构性把
//    19s 参考压进 2.1s（假阳性）。替代路径是和弦模板逐帧分类 + 手写泛音
//    和声评分 f0（见 align.ts）。
// 2. FFT / WAV 读取消费 @feuille/bgm 的唯一实现（rfftMag / readWav）；
//    帧网格吸附消费 @feuille/core 的唯一实现（snapToGrid / framesFor）；
//    ffprobe 时长 / 平台工具解析一律走 @feuille/core 的 platform.* 与
//    audio.probeDuration——本包零重复。
// 3. 本包**不碰发布、不碰生成式视频**：产物是「真实录音 + 程序化教学标注」
//    的赏析片，画面不是生成影像，发布走 multilingual-video-publishing。
// 4. 判据与纪律的事实源是 skills/music-annotate-video/SKILL.md 与
//    references/music-av-traps.md；代码与文档冲突时以 traps 为准（它是
//    实测踩坑的现场）。
//
// 四个叶子（SKILL.md 早已许诺但此前没有 CLI）：
//   probe    —— 录音的结构测量；摘录边界的唯一背书（notes/probe/*.log）
//   align    —— Tier A 谱面真值对拍 / Tier B 录音实测旋律线
//   build    —— 状态帧渲染 + 帧精确装配 + ducking 音频
//   scan-ink —— 含墨覆盖率扫描（空帧闸；不要用 karaoke scan-blank 当验收）

export * as dsp from './dsp.js'
export * as midi from './midi.js'
export * as chord from './chord.js'
export * as probe from './probe.js'
export * as align from './align.js'
export * as build from './build.js'
export * as scan_ink from './scan_ink.js'
export * as source from './source.js'
export * as score from './score.js'
export * as narrate from './narrate.js'
