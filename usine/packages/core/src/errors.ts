// errors.ts — feuille 库层错误通道（errors.py 的 TS 移植）
//
// `FeuilleError` 是库层**显式报错**的唯一错误类型：库函数发现输入/环境不满足
// 契约时抛它（消息一律人话、带下一步），由 CLI 入口统一接住——打印消息、
// 退出码 1。库层**不再**用 process.exit 伪装退出：进程级退出会把「调用方可以
// 捕获并处置」变成「整个进程必须陪葬」，doctor 这类要把多个失败收进一张表
// 的能力就是被它堵死的。
//
// 判断标准：
// - 库函数里发现坏数据/缺件 → `throw new FeuilleError('…（下一步）')`
// - CLI 入口自身 → 捕获后打印 stderr、返回退出码 1（同一口径）

/**
 * feuille 库层的显式失败：坏数据、缺件、契约不满足。
 * 消息面向人：说清缺什么/错在哪，并给出下一步命令。
 * 调用方（CLI / doctor / verify 套件）应捕获它而不是让进程直接退出。
 */
export class FeuilleError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'FeuilleError'
  }
}
