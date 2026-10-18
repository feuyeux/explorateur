// @feuille/core —— feuille 核心包入口（迁移目标位）
//
// P1 骨架：模块随 P2–P5 逐批迁入（platform / errors / ledger / framehash /
// tts / audio / timeline / textlayer / compose / render / covers / manifest /
// metrics / data / audit / rig / scenes / devices / persona）。
// 权威门禁在迁移期仍是 Python 21 套；本包每迁入一个模块即配 vitest
// 金样本 parity + 反向验证（纪律 2：加了新检查就要做反向验证）。

export const VERSION = '0.1.0'

// spike 1（edge-tts v2 客户端）——P3 tts 模块的种子
export * from './tts/index.js'

// spike 2（sharp + canvas 成像管线）——P3 textlayer / P4 rig·scenes 的种子
export * from './imaging/index.js'

// ---- P2 基础层（命名空间导出：ledger 自带 schema VERSION，与包 VERSION 同名不同义，
// 混在顶层会静默遮蔽）----
export * as platform from './platform.js'
export { FeuilleError } from './errors.js'
export * as errors from './errors.js'
export * as packaging from './packaging.js'
export * as ledger from './ledger.js'
export * as framehash from './framehash.js'

// ---- P3 音画内核（flat 导出：tts/imaging 已在顶层）----
export { roundHalfEven } from './num.js'
export * as audio from './audio.js'
export * as timeline from './timeline.js'
export * as textlayer from './textlayer.js'
export * as compose from './compose.js'
export * as render from './render.js'
export * as covers from './covers.js'

// ---- P4 数据与人物场景（命名空间导出）----
export * as data from './data.js'
export * as audit from './audit.js'
export * as manifest from './manifest.js'
export * as metrics from './metrics.js'
export * as rig from './rig.js'
export * as scenes from './scenes.js'
export * as devices from './devices.js'
export * as persona from './persona.js'
