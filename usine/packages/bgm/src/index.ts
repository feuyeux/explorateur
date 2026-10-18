// index.ts — @feuille/bgm — bgm-bed 的 TS 归流包
// （gen_bgm 的 TS 归流）。
//
// 使用契约：
//
// 1. ffprobe 时长 / Python round() 银行家舍入 / 平台工具解析全部消费
//    @feuille/core 的唯一实现（audio.probeDuration / roundHalfEven /
//    platform.ffmpeg / platform.ffprobe）——本包零重复。
// 2. 频段分布的 rfft 自写 radix-2 + Bluestein（任意 N 精确频谱，对齐
//    numpy.fft.rfft 语义），不装 DSP 依赖。
// 3. Lyria key 走环境或 ~/.config/feuille/bgm-bed.env / ~/.gemini_api_key——
//    密钥永不进仓库（BGM_BED_ENV 可改指任意路径）。
// 4. 测试零真 API 调用：实时后端结构性移植（同 Python 的 HTTP 路径——
//    未实测的通路解不出容器就大声失败）；Lyria 免费层 $0 但区围栏严，
//    测试一律纯函数面 + 本地 ffmpeg 合成音频。
// 5. 不碰发布、不碰 H3——本包零平台流量、零额度。
//
// 反向验证：packages/bgm/test/gen_bgm.test.ts

export * as gen_bgm from './gen_bgm.js'
