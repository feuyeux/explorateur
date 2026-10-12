# -*- coding: utf-8 -*-
"""errors.py — feuille 库层错误通道

`FeuilleError` 是库层**显式报错**的唯一异常类型：库函数发现输入/环境不满足契约时
抛它（消息一律人话、带下一步），由 CLI 入口（feuille.cli.main）统一接住——
打印消息、退出码 1。库层从此**不再**用 `raise SystemExit` 伪装退出：SystemExit
是进程层的退出信号，库层直接抛它会把「调用方可以捕获并处置」变成「整个进程必须
陪葬」，doctor 这类要在同进程里把多个失败收进一张表的能力就是被它堵死的
（lesson._check_tier_data 因此同时接两种异常）。

判断标准：
- 库函数里发现坏数据/缺件 → `raise FeuilleError("…（下一步）")`
- `if __name__ == "__main__"` 的脚本尾巴、脚本自身的失败出口 → SystemExit 照旧
- CLI 可见的输出与退出码语义不变：SystemExit(msg) 原本由解释器打印到 stderr、
  退出码 1；现在由 cli.main 打印到 stderr、返回 1——同一口径。
"""


class FeuilleError(Exception):
    """feuille 库层的显式失败：坏数据、缺件、契约不满足。

    消息面向人：说清缺什么/错在哪，并给出下一步命令。
    调用方（CLI / doctor / verify 脚本）应捕获它而不是让进程直接退出。
    """
