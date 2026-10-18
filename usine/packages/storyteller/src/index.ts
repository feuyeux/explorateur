// index.ts — @feuille/storyteller — storyteller-video 评书产线
// （render_act_frames / assemble_storyteller 的 TS 归流）。
//
// 使用契约：
//
// 1. 人物 / 舞台绘制消费 @feuille/core 唯一实现（rig.drawCharacter /
//    poseFor / POSE_CODES / SCENE / mix / hexc、scenes.prerenderBg / DrawScaled、
//    data.storytellers）——本包零重复。
// 2. ffprobe 时长 = core audio.probeDuration；Python round() 银行家舍入 =
//    core roundHalfEven；ffmpeg 只剩醒木合成 + 成片组装（platform 唯一解析）。
// 3. 字卡文字一律 Edge headless 截图 + matte 分解（raqm=False 纪律：
//    成像库不画字）；字卡页黑底纯实色，dim 态用实色暗字而不用 CSS opacity。
// 4. 帧数口径与 karaoke build 一致（preroll + Σ词段 + tail + done）；
//    幕段编码用 image2 序列输入，不用 concat demuxer（DTS 事故）。
// 5. 不碰发布、不碰 H3——本包零平台流量、零额度。
//
// 反向验证：packages/storyteller/test/storyteller.test.ts

export * as render_act_frames from './render_act_frames.js'
export * as assemble_storyteller from './assemble_storyteller.js'
