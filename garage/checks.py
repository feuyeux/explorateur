"""checks.py —— garage 那批 `smoke_*.py` 共用的骨架。

## 为什么有这个文件

这些 smoke 原本各自抄了一遍同样的三件事：找 `théâtre` 检出、`record/check/info`
三件套、以及「汇总 + 退出码」的收尾。2026-10-21 清点：`_find_theatre()` **6 份
逐字相同**、`record()` **6 份**、`info()` **7 份**，而三个收尾段各写各的
（一个 `return 1 if fails else 0`、一个 `sys.exit(...)`、一个打印 FAILED 明细）。

抄写的代价不是行数，是**漂移时没人知道**：`_find_theatre()` 的判据是
`env/vm.py` + `explore/practice_loop.py` 两个文件同时存在，这是「这确实是
théâtre 检出」的机器判据；六份里改了一份，另外五份还在用旧判据，而它们都会绿
——因为都找得到目录。同理 `SUMMARY` 的行格式一改，读日志的人就得记两种格式。

**所以这里只抽「逐字相同」的部分**，不强行统一差异：

- `find_theatre()` / `bootstrap()` —— 六份原本逐字相同。
- `record()` / `check()` / `info()` —— 同上（`check` 的 `detail` 截断长度也相同）。
- `summarise()` —— 收尾**语义**相同（统计三档、有 FAIL 则退出码 1），
  但**行格式各脚本自带**，所以由调用方传 `label`，本函数只负责数字与退出码。

**没有并进来的**：`smoke_agent_surface.py`。它的 `check()` 返回 `bool` 且被
调用方拿去做控制流（`if not check(...)`、`all(results)` 决定退出码），
是**另一种契约**，不是同一份代码的副本。把它并进来会让它的六节失去
「只打印不判决等于没有闸」那条修好的性质（见该文件 `main()` 末的注释）。
一个同名函数有两种契约时，正确的收敛是**分开**，不是折中。

## 用法

```python
from checks import bootstrap, check, info, summarise

THEATRE, HERE = bootstrap(__file__)   # 已把两个目录插进 sys.path
...
def main() -> int:
    test_a()
    return summarise("smoke_xxx")     # 打印 SUMMARY 行并返回 0/1
```

`bootstrap()` **必须在 import 任何 garage/theatre 模块之前调用**——`guest_env`
之类的模块在 import 期就要 `env.vm` 可导入，这正是原来那六份 `_find_theatre()`
都要写在文件顶部的原因。
"""

from __future__ import annotations

import sys
from pathlib import Path

#: 一份 `théâtre` 检出的机器判据：这两个文件同时存在才算。
#: 换判据要六处一起换——收进这里之后只剩一处。
THEATRE_MARKERS = (("env", "vm.py"), ("explore", "practice_loop.py"))

#: 每条断言的结果：(status, name, detail)，status ∈ {PASS, FAIL, INFO}。
RESULTS: list[tuple[str, str, str]] = []

#: `detail` 在 FAIL 行里的截断长度：轨迹/异常文本可能几千字，全打会淹掉汇总。
DETAIL_CAP = 400


def find_theatre(explorateur: Path) -> Path:
    """在 `explorateur` 下找 théâtre 检出；找不到就**停**，不猜。

    fail-closed 在这里是必要的：猜错目录的后果不是崩溃，而是「跑了一套
    陈旧的引擎并得出一片绿」——那比找不到更坏。
    """
    for candidate in sorted(Path(explorateur).iterdir()):
        if all((candidate.joinpath(*parts)).is_file() for parts in THEATRE_MARKERS):
            return candidate
    raise SystemExit(
        "the théâtre checkout (env/vm.py + explore/practice_loop.py) "
        "was not found under " + str(explorateur))


def bootstrap(dunder_file: str, extra: tuple[Path, ...] = ()) -> tuple[Path, Path]:
    """定位仓库根与 `garage/`，插进 `sys.path`，返回 `(THEATRE, HERE)`。

    `sys.path` **先插 théâtre 再插 garage**：两个目录里都有 `run_usine.py`
    的同名邻居逻辑，顺序反了会拿到另一份。原始六份都是这个顺序。
    """
    here = Path(dunder_file).resolve().parent
    explorateur = here.parent
    theatre = find_theatre(explorateur)
    for p in (str(here), *(str(x) for x in extra)):
        if p not in sys.path:
            sys.path.insert(0, p)
    if str(theatre) not in sys.path:
        sys.path.insert(0, str(theatre))
    return theatre, here


def record(status: str, name: str, detail: str = "") -> None:
    """追加一条结果并立刻打印——不攒到最后，因为脚本可能中途被超时杀掉。"""
    RESULTS.append((status, name, detail))
    line = f"{status} {name}"
    if detail:
        line += f" | {detail}"
    print(line)


def check(name: str, ok, detail: str = "") -> None:
    """一条断言。`detail` 只在失败时打印，且截到 `DETAIL_CAP`。"""
    record("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:DETAIL_CAP])


def info(name: str, detail: str) -> None:
    """不是断言：记录一条「没验 / 不适用」的事实。SKIP 不是 PASS。"""
    record("INFO", name, detail)


def counts() -> tuple[int, int, int]:
    """`(passed, failed, infos)`。"""
    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    failed = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    infos = sum(1 for s, _, _ in RESULTS if s == "INFO")
    return passed, failed, infos


def summarise(label: str, *, list_failures: bool = False) -> int:
    """打印汇总行，返回退出码（有 FAIL 即 1）。

    `list_failures=True` 时把每条 FAIL 的 name/detail 再打一遍：断言分散在
    几千行输出里时，重跑一次只为翻上去找那一行是很贵的。
    """
    passed, failed, infos = counts()
    print()
    print(f"{label}: {passed} PASS / {failed} FAIL / {infos} INFO")
    if failed and list_failures:
        for status, name, detail in RESULTS:
            if status == "FAIL":
                print(f"  FAIL {name} | {detail}")
    return 1 if failed else 0


def mutter(label: str) -> None:
    """`summarise()` 的「只打印不退出」变体，给自管退出码的脚本用。

    存在的理由：几个老脚本的收尾行格式不同（有的带前导换行、有的用 `SUMMARY:`
    前缀），换格式会让读日志的人以为读数变了。格式归调用方，数字归这里。
    """
    passed, failed, infos = counts()
    print(f"{label}: {passed} PASS / {failed} FAIL / {infos} INFO")
