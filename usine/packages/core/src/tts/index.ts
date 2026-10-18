// tts/ — edge-tts 语音合成内核（⑤ 音频）。spike 1 起家：drm（v2 令牌）+
// pure（纯函数口径）+ client（WebSocket 协议，4096 字节多段）+ split（分片）+
// synth（内容寻址缓存，命中零探测）。
export * from "./pure.js"
export * from "./client.js"
export * from "./drm.js"
export * from "./split.js"
export * from "./synth.js"
