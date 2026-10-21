#!/usr/bin/env python3
"""smoke_transfer.py —— A 线「记忆跨项目迁移」读数的门禁。

为什么单独一条
==============

`transfer_check.py` 读的是**已有波次产物**，不跑模型、不花钱，所以它可以、也应该
进 smoke：它唯一的失败方式是**结论说错**，而结论说错在磁盘上看不出来。

机制前提（决定了这个 smoke 的形状）
====================================

`théâtre/explore/phase1_wave.py` 的真实形状是：

- `memory_dir = lineage / "memory"`（L584）——**跨波次累计**；
- 每波开始时打一份 `waves/wave_NNN/memory_snapshot`（L684）；
- 波内项目**并行**跑（L705），全部从**同一份快照**起步（L713）。

所以「继承」的单位是**波次**，不是波内项目。第一版 `transfer_check` 把单位写成
波内项目，于是同波并行会被误判成 `broken_lineage`——这个 smoke 里有一条专门盯着
这件事（「同波并行不算断链」）。

要防的三件事
============

1. **把「没测到」说成「测过了」**：只有 1 个项目时必须判 `single_project`，
   而不是 `all_pass`（后者会让人以为迁移被验证过）。
2. **把「记忆被删」说成正常**：删除是退化信号，而且**不能用净数量判**——
   删一个补一个，净数量不变，但那是两件事。
3. **把「跨波断链」当成能读**：本波快照里没有上一波写的记忆时，
   后面的表现方向不能用来判迁移。

这三条都是**样本合成就能测**的：不需要真波次。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from transfer_check import transfer_report  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))


def make_wave(
    root: Path,
    name: str,
    *,
    waves: list[tuple[int, list[str]]],
    projects: list[dict],
    final_memory: list[str] | None = None,
) -> Path:
    """合成一个波次根目录。

    `waves`    = [(每波派几个项目, 本波快照里的记忆文件), …]
    `projects` = [{"outcome":…, "deleted":[…], "after":[…]}, …]  按 episode 顺序
    `final_memory` = 波次结束时 `lineage/memory` 里的文件（跨波接续用它判）
    """
    p1 = root / name / "phase1"
    (p1 / "episodes").mkdir(parents=True)
    (p1 / "waves").mkdir(parents=True)

    for i, (n_decl, snap) in enumerate(waves, 1):
        wdir = p1 / "waves" / f"wave_{i:03d}"
        (wdir / "memory_snapshot").mkdir(parents=True)
        for f in snap:
            (wdir / "memory_snapshot" / f).write_text(f"content of {f}", encoding="utf-8")
        (wdir / "curriculum_decision.json").write_text(
            json.dumps({
                "decision": "CONTINUE",
                "rationale": "synthetic",
                "projects": [{"id": f"p{j}"} for j in range(n_decl)],
            }),
            encoding="utf-8",
        )

    for i, proj in enumerate(projects, 1):
        d = p1 / "episodes" / f"ep{i:03d}"
        d.mkdir()
        (d / "outcome.json").write_text(
            json.dumps({
                "terminal_outcome": proj.get("outcome", "PASS"),
                "verification_cycles": proj.get("cycles", 1),
                "memory_before": proj.get("before", []),
                "memory_changes": {
                    "created": proj.get("after", []),
                    "updated": [],
                    "deleted": proj.get("deleted", []),
                },
            }),
            encoding="utf-8",
        )
        if proj.get("after"):
            (d / "memory_after_commit").mkdir()
            for f in proj["after"]:
                (d / "memory_after_commit" / f).write_text("x", encoding="utf-8")

    mem = final_memory if final_memory is not None else (projects[-1].get("after", []) if projects else [])
    (p1 / "memory").mkdir()
    for f in mem:
        (p1 / "memory" / f).write_text("x", encoding="utf-8")

    (p1 / "result.json").write_text(
        json.dumps({
            "project_budget": len(projects),
            "projects": len(projects),
            "status": "budget_exhausted",
            "memory_files": len(mem),
        }),
        encoding="utf-8",
    )
    return p1


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-transfer-"))

    # ── 单项目：必须说「迁移从未被观测」，不许说通过 ────────────────────────
    make_wave(
        tmp, "one",
        waves=[(1, [])],
        projects=[{"outcome": "PASS", "after": ["a.md"]}],
    )
    rep = transfer_report(tmp / "one")
    check("单项目 → single_project", rep["verdict"] == "single_project", rep["verdict"])
    check("单项目时明说「从未被观测」", "从未被观测" in rep["why"], rep["why"][:60])
    check("单项目时给出可执行的点亮方式", "project-budget" in rep["why"], rep["why"][:60])

    # ── 三波各 1 个项目、记忆逐波累计：这才是真读数 ────────────────────────
    make_wave(
        tmp, "three",
        waves=[(1, []), (1, ["a.md"]), (1, ["a.md", "b.md"])],
        projects=[
            {"outcome": "PASS", "after": ["a.md"]},
            {"outcome": "PASS", "before": ["a.md"], "after": ["a.md", "b.md"]},
            {"outcome": "PASS", "before": ["a.md", "b.md"], "after": ["a.md", "b.md", "c.md"]},
        ],
    )
    rep = transfer_report(tmp / "three")
    check("三波全过 → all_pass", rep["verdict"] == "all_pass", rep["verdict"])
    check("三波全过时点出天花板效应", "天花板" in rep["why"], rep["why"][:60])
    check("波次数读对", rep["waves_observed"] == 3, str(rep["waves_observed"]))
    check("项目数读对", rep["episodes_observed"] == 3, str(rep["episodes_observed"]))
    check(
        "跨波接续逐波判对",
        [w["inherited_previous"] for w in rep["waves"]] == [None, True, True],
        str([w["inherited_previous"] for w in rep["waves"]]),
    )
    check(
        "每波派几个项目读得出来",
        [w["projects_declared"] for w in rep["waves"]] == [1, 1, 1],
        str([w["projects_declared"] for w in rep["waves"]]),
    )

    # ── 记忆被删：必须单独判决，且「删一个补一个」也要抓到 ──────────────────
    make_wave(
        tmp, "shrink",
        waves=[(1, []), (1, ["a.md", "b.md"])],
        projects=[
            {"outcome": "PASS", "after": ["a.md", "b.md"]},
            # 删了 b.md、加了 c.md：**净数量不变（2→2）**，但既有知识被抹掉。
            {"outcome": "PASS", "before": ["a.md", "b.md"], "after": ["a.md", "c.md"],
             "deleted": ["b.md"]},
        ],
    )
    rep = transfer_report(tmp / "shrink")
    check("删一个补一个 → memory_shrank", rep["verdict"] == "memory_shrank", rep["verdict"])
    check("memory_shrank 时点名删了什么", "b.md" in rep["why"], rep["why"][:70])

    # ── 跨波断链：第二波的快照里没有第一波写的记忆 ──────────────────────────
    make_wave(
        tmp, "broken",
        waves=[(1, []), (1, [])],   # 第二波快照是空的——上一波的 a.md 没传过来
        projects=[
            {"outcome": "PASS", "after": ["a.md"]},
            {"outcome": "PASS", "after": ["b.md"]},
        ],
    )
    rep = transfer_report(tmp / "broken")
    check("跨波断链 → broken_lineage", rep["verdict"] == "broken_lineage", rep["verdict"])
    check("断链时明说「不能用来判迁移」", "不能用来判迁移" in rep["why"], rep["why"][:60])

    # ── **同波并行不算断链**：第一版把这条判错的回归 ────────────────────────
    # 一波派 2 个项目，两者从同一份快照起步（快照为空），然后各自写记忆。
    # 旧逻辑按「项目 N 继承项目 N-1」判，会得出 broken_lineage——那是错的。
    make_wave(
        tmp, "parallel",
        waves=[(2, []), (2, ["a.md", "b.md"])],
        projects=[
            {"outcome": "PASS", "after": ["a.md"]},
            {"outcome": "PASS", "after": ["b.md"]},
            {"outcome": "PASS", "before": ["a.md", "b.md"], "after": ["a.md", "b.md", "c.md"]},
            {"outcome": "PASS", "before": ["a.md", "b.md"], "after": ["a.md", "b.md", "d.md"]},
        ],
    )
    rep = transfer_report(tmp / "parallel")
    check(
        "同波并行不被误判成断链",
        rep["verdict"] != "broken_lineage",
        f"误判成 {rep['verdict']}",
    )
    check(
        "同波派 2 个项目读得出来",
        [w["projects_declared"] for w in rep["waves"]] == [2, 2],
        str([w["projects_declared"] for w in rep["waves"]]),
    )

    # ── 方向混合：不许归因于记忆 ────────────────────────────────────────────
    make_wave(
        tmp, "mixed",
        waves=[(1, []), (1, ["a.md"])],
        projects=[
            {"outcome": "PASS", "after": ["a.md"]},
            {"outcome": "FAIL", "before": ["a.md"], "after": ["a.md", "b.md"]},
        ],
    )
    rep = transfer_report(tmp / "mixed")
    check("有项目没 PASS → mixed", rep["verdict"] == "mixed", rep["verdict"])
    check("mixed 时明说「不能直接归因于记忆」", "不能直接归因" in rep["why"], rep["why"][:60])

    # ── 零项目：不许当成「迁移没问题」 ──────────────────────────────────────
    empty = tmp / "empty" / "phase1"
    (empty / "waves").mkdir(parents=True)
    (empty / "result.json").write_text(json.dumps({"project_budget": 0}), encoding="utf-8")
    rep = transfer_report(tmp / "empty")
    check("零项目 → no_episodes", rep["verdict"] == "no_episodes", rep["verdict"])

    # ── 波次间接续：bfs16 → bfs17 那种形状 ──────────────────────────────────
    make_wave(tmp, "w1", waves=[(1, [])], projects=[{"outcome": "PASS", "after": ["a.md", "b.md"]}])
    make_wave(tmp, "w2", waves=[(1, ["a.md", "b.md"])], projects=[{"outcome": "PASS", "after": ["a.md", "b.md"]}])
    rep = transfer_report(tmp / "w2", roots=[tmp])
    check("波次间接续被认出来", rep["lineage"]["inherited"] is True, str(rep["lineage"]))
    check("接续来源指向上一波", "w1" in (rep["lineage"]["from"] or []), str(rep["lineage"]["from"]))

    n_pass = sum(1 for _l, ok, _d in RESULTS if ok)
    n_fail = len(RESULTS) - n_pass
    print("=" * 72)
    for label, ok, detail in RESULTS:
        line = f"  {'ok  ' if ok else 'FAIL'} {label}"
        if detail and not ok:
            line += f"\n       {detail}"
        print(line)
    print(f"\n=== SMOKE transfer: {n_pass} PASS / {n_fail} FAIL / {len(RESULTS)} total")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
