"""posix_compat.py —— Windows 宿主上的 fcntl 兼容层（桥接层职责，不动引擎）。

为什么必须有这个模块
====================

引擎（`theatre-ii/harness2/core/schedule.py` 的 `_write_summary`）在写
`summary.json` 时用 `fcntl.flock` 互斥——`fcntl` 是 POSIX 专属模块，Windows
上没有。2026-10-21 实测代价：`--split both` 两段式的 train 段 12 格在
Windows 宿主上**真跑了约两小时**（base1/agg1/inv1/dom1 全部完成、事件流
全程落盘），每一格最后死在 `import fcntl` 上——12 格全部作废，token 白烧，
而 preflight 是绿的（这条后来才补成硬检查）。

为什么修在桥接层而不是引擎
==========================

`theatre-ii/` 是**零补丁**的 vendored fork（PROVENANCE 明写：上游自己的
跨平台处理「留在它自己的代码里，不在本 fork 的职责范围内」）。平台差垫在
`garage-ii` 桥接层正好是这套架构的分工——就像 `feuille` 的 PATH 垫片一样：
**不复制、不改写被垫的对象，只把真实环境里本来就有的那条通路接上**。

装法与边界
==========

- `install()` 只在 `sys.platform == "win32"` 且 `fcntl` 尚未存在时，把本模块
  的兼容实现放进 `sys.modules["fcntl"]`——POSIX 上**恒不装**（stdlib 的
  fcntl 永远优先），所以它不会污染 POSIX 宿主的运行。
- 只有显式调过 `install()` 的入口才有这层垫（`run_usine_h2.py` 与
  `preflight.py` 在启动时调）。不靠 `sys.path` 阴影——那会在 POSIX 上把
  stdlib fcntl 顶掉。
- 只实现引擎用到的面：`flock(fd, LOCK_EX / LOCK_UN)`（加 `LOCK_NB` 的
  语义供完整性）。引擎没有别的调用点（全仓 grep 只有一处）。
"""

from __future__ import annotations

import os
import sys
import time
import types

#: 与 Linux `<fcntl.h>` 的常量对齐（引擎只用 LOCK_EX / LOCK_UN）。
LOCK_SH = 1
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def _lock_file_object(lf) -> None:
    """把 `lf` 的文件位置归零——`msvcrt.locking` 锁的是**当前位置**起的字节。

    `_write_summary` 打开锁文件后从不写它，位置本来就在 0；显式归零是防
    「锁文件在锁与解锁之间被 seek 过」的将来情形——那时锁的就不是同一段
    字节，互斥会静默失效。
    """
    if hasattr(lf, "seek"):
        lf.seek(0)
    else:
        os.lseek(lf, 0, os.SEEK_SET)


def _flock(fd, op: int) -> None:
    import msvcrt

    handle = fd.fileno() if hasattr(fd, "fileno") else fd
    if op & LOCK_UN:
        _lock_file_object(fd)
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        return
    # `flock(LOCK_EX)` 无 NB 时**阻塞到拿到为止**；`LK_NBLCK` 拿不到立刻抛。
    # 所以这里自己循环——语义跟 POSIX 对齐，而不是拿 `LK_LOCK`（它重试
    # 10 次后放弃）将就。
    while True:
        try:
            _lock_file_object(fd)
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if op & LOCK_NB:
                raise
            time.sleep(0.1)


def install() -> bool:
    """把兼容层装进 `sys.modules["fcntl"]`。返回是否真的装了。

    已有 `fcntl`（POSIX 的 stdlib，或先一步装过的本模块）时**恒不覆盖**。
    """
    if sys.platform != "win32" or "fcntl" in sys.modules:
        return False
    mod = types.ModuleType("fcntl", "garage-ii 桥接层为 Windows 垫的 fcntl（见 posix_compat.py）")
    mod.LOCK_SH, mod.LOCK_EX, mod.LOCK_NB, mod.LOCK_UN = LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN
    mod.flock = _flock
    sys.modules["fcntl"] = mod
    return True
