// index.ts — @feuille/poetry — multilingual-video-poetry 的诊断产线
// （audio_profile / color_contrast 的 TS 归流）。
//
// 使用契约：
//
// 1. ffmpeg 解析走 @feuille/core platform 唯一实现——本包不带第二份
//    _bin 拷贝（Python 侧 skill 脚本的平行实现不迁移即天然消除）。
// 2. 成像走 sharp（PIL LANCZOS → lanczos3 同族核）；WCAG 比值只报不判
//    （彩字压实拍靠亮度差+色相差+阴影光晕叠加，WCAG 只看第一项）。
// 3. 季色默认值读归档 季节与译文.py 的 SEASON_COLOR 字面量
//    （assets/example 是数据资产，清场也不删）；别的事实源都归 --colors。
// 4. 门禁全绿 ≠ 做对了：程序化验收只是下限，交付前目视复核不可省
//    （见 karaoke-video/references/delivery-check.md 的返工实录）。
// 5. 不碰发布、不碰 H3——本包零平台流量、零额度。
//
// 反向验证：packages/poetry/test/poetry.test.ts
// （gap_verdict 两态从 scripts/verify_skill_scripts.py 随本包归流移植）。

export * as audio_profile from './audio_profile.js'
export * as color_contrast from './color_contrast.js'
