// tts/ — edge-tts 语音合成内核（⑤ 音频）。spike 1 起家：drm（v2 令牌）+
// pure（纯函数口径）+ client（WebSocket 协议）。缓存合成（synthCached）属 P3。
export * from "./pure.js"
export * from "./client.js"
export * from "./drm.js"
