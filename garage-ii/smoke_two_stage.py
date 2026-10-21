#!/usr/bin/env python3
"""smoke_two_stage.py —— 两段式 sweep 的「library 不被 eval 段污染」门禁。

为什么单独一条
==============

`--split both` 的整个可信度压在一件事上：**eval 段不许往 library 里写东西**。

引擎的 `run_sweep` 每次都会在 `reflect_adoption` 里写 library。如果 eval 段也写，
那么「train 学、eval 测」就变成「train 学、eval 也学了一遍」——泛化读数当场失效，
而**磁盘上看起来一切正常**：两段都跑完了、都有产物、都有分数。这类失效是静默的，
所以必须有独立门禁盯着。

它测什么
========

`_trim_library(root, before)` 是接缝。这里用**真目录**验证三件事：

1. eval 段新长的文件被删掉（library 回到 train 段结束时的样子）；
2. **旧文件一个都不动**——哪怕它被 eval 段改写过（那一半不做，但要确认「不删」）；
3. 删空的目录也一起清（否则 `entries()` 会看见空目录）。

外加一条**反向验证**：把 `_trim_library` 换成空实现（`return []` 早返回），
这个 smoke 必须红——那是证明它真的在守门的唯一方式。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run_usine_h2 import _library_entries, _trim_library  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-2stage-"))
    lib = tmp / "library"

    # train 段结束时的样子：两棵树，各一个经验文件。
    (lib / "usine-dsh" / "k1-dsh" / "tree-a").mkdir(parents=True)
    (lib / "usine-dsh" / "k1-dsh" / "tree-a" / "cue.md").write_text("A", encoding="utf-8")
    (lib / "usine-dsh" / "k1-dsh" / "tree-b").mkdir(parents=True)
    (lib / "usine-dsh" / "k1-dsh" / "tree-b" / "cue.md").write_text("B", encoding="utf-8")

    before = _library_entries(lib)
    check("起点条目数读对", len(before) == 2, str(sorted(before)))

    # 模拟 eval 段：新增一棵树、新增一个文件、**并改写了一个旧文件**。
    (lib / "usine-dsh" / "k1-dsh" / "tree-c").mkdir(parents=True)
    (lib / "usine-dsh" / "k1-dsh" / "tree-c" / "cue.md").write_text("C", encoding="utf-8")
    (lib / "usine-dsh" / "k1-dsh" / "tree-a" / "extra.md").write_text("X", encoding="utf-8")
    (lib / "usine-dsh" / "k1-dsh" / "tree-a" / "cue.md").write_text("A-改过", encoding="utf-8")

    now = _library_entries(lib)
    check("eval 段的写入被看见", len(now) == 4, f"{len(now)} 条：{sorted(now)}")

    removed = _trim_library(lib, before)
    after = _library_entries(lib)

    # ── 1. 新增的被删掉 ────────────────────────────────────────────────────
    check("eval 新增的文件被删", len(removed) == 2, f"删了 {removed}")
    check(
        "tree-c/cue.md 被删",
        "usine-dsh/k1-dsh/tree-c/cue.md" in removed,
        str(removed),
    )
    check(
        "tree-a/extra.md 被删",
        "usine-dsh/k1-dsh/tree-a/extra.md" in removed,
        str(removed),
    )

    # ── 2. library 回到起点 ─────────────────────────────────────────────────
    check("library 的条目集合回到起点", after == before, f"{sorted(after)} vs {sorted(before)}")
    check("eval 新建的目录也被清掉", not (lib / "usine-dsh" / "k1-dsh" / "tree-c").exists())

    # ── 3. 旧文件一个都没删（但内容可能被改过——那一半不做）────────────────
    check(
        "旧文件仍在盘上",
        (lib / "usine-dsh" / "k1-dsh" / "tree-a" / "cue.md").is_file()
        and (lib / "usine-dsh" / "k1-dsh" / "tree-b" / "cue.md").is_file(),
    )
    # **这条要明说它是「已知不做」的一半**：内容被改了，trim 不回滚。
    # 断言写成「内容确实被改了」——这样将来若有人实现了内容回滚，
    # 这条会红，逼他回来更新这条注释，而不是让一个过时的说明留在文档里。
    check(
        "旧文件的内容修改不被回滚（已知限制，非缺陷）",
        (lib / "usine-dsh" / "k1-dsh" / "tree-a" / "cue.md").read_text(encoding="utf-8")
        == "A-改过",
        "内容被回滚了？那要更新 _trim_library 的 docstring 与本节说明",
    )

    # ── 4. 幂等：再 trim 一次什么都不删 ─────────────────────────────────────
    again = _trim_library(lib, before)
    check("trim 幂等（再调不删东西）", again == [], f"又删了 {again}")

    n_pass = sum(1 for _l, ok, _d in RESULTS if ok)
    n_fail = len(RESULTS) - n_pass
    print("=" * 72)
    for label, ok, detail in RESULTS:
        line = f"  {'ok  ' if ok else 'FAIL'} {label}"
        if detail and not ok:
            line += f"\n       {detail}"
        print(line)
    print(f"\n=== SMOKE two-stage: {n_pass} PASS / {n_fail} FAIL / {len(RESULTS)} total")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
