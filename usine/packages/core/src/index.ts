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
