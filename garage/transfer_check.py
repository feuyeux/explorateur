"""跨波次迁移检查：A 线（RSIAgent）的记忆**有没有在项目之间起作用**。

先说清机制，因为第一版这个文件把机制写错了
==========================================

A 线的记忆挂在一个**跨波次累计的目录**上（`explore/phase1_wave.py:584`）：

```python
memory_dir = lineage / "memory"          # 整个 lineage 共享，跨波次累积
...
wave_memory_dir = wave_dir / "memory_snapshot"   # 每波开始时打一份快照
hooks.install_memory(str(wave_memory_dir), wave_memory)
```

波内所有项目通过 `ThreadPoolExecutor` **并行**跑（`phase1_wave.py:705`），而且每个
分支启动时读的都是**同一份 `wave_memory_dir` 快照**（`:713`）。所以：

- **波内项目互不可见**——项目 A 不可能读到同波项目 B 在这一波里写的记忆，
  因为它们同时在跑，B 那时还没写完。
- **继承发生在波次之间**——`wave_002` 的快照里含有 `wave_001` 结束时的记忆。

第一版这个文件假设「项目 N 继承项目 N-1」，那是错的：它会把**同波并行**误判成
`broken_lineage`。2026-10-21 读代码时抓到，当场改。

所以读数的单位是**波次**，不是波内项目。

为什么必须有这个文件
====================

机制存在 ≠ 效果被测量。2026-10-21 之前的真实账：

| 波次 | project_budget | projects | memory_files |
|---|---|---|---|
| bfs16 | 1 | 1 | 3 |
| bfs17 | 1 | 1 | 3 |
| 其余 12 个 | 2 或 1 | **0** | 0 |

14 个波次里只有 2 个真的跑出了项目，而且**每个都只跑 1 个**。于是「记忆帮了下一个
项目」和「记忆害了下一个项目」这两件事**都没有被观测过**。`result.json` 里那个
`study_design: "held_out_generalization"` 只是一个**字符串标签**
（`garage/run_usine.py` 三处字面量），背后没有切分逻辑。

这个文件补的是**读数那一半**：给定多波次的产物，把「上一波的记忆」与「这一波的
表现」对上，产出可判定的结论。它不改机制——机制是对的，缺的是尺子。

判据（都不做语义猜测）
======================

1. **波次间记忆是否接续**：第 N 波的 `memory_snapshot` 是否等于第 N-1 波结束时
   的 `memory` 目录。直接读盘上两份文件列表比。
2. **记忆是否被删**：任一项目/波次的 `memory_changes.deleted` 非空就是退化信号。
   **不能用净数量判**——删一个补一个，净数量不变，但那是两件事（2026-10-21 自检
   抓到过这个缺陷）。
3. **表现方向**：`terminal_outcome` 与 `verification_cycles` 跨波次的方向。

**第 3 条必须明说它弱**：不同波次干的是不同的活，难度不受控，「后一波更差」不能
直接归因于记忆。要真正判负迁移，得有**同一道题、有记忆 vs 无记忆**的对照
（`--memory-seed` 那条路）。这个文件只负责把已有证据整理成能读的形状，并在证据
不足时**明确说不足**。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 判决词。前四个是「证据不足」，后两个是「有读数」。
_INSUFFICIENT = {"no_episodes", "single_project", "broken_lineage", "memory_shrank"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _memory_files(d: Path) -> list[str]:
    """一个记忆目录里的文件名（按名字排序）。目录不在 → 空。

    只读顶层：记忆是若干 `.md` 文件，不做递归——递归会把 `memory_distillation/`
    之类的中间产物算进来，那会虚高「记忆增长」。
    """
    d = Path(d)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file())


def _memory_bytes(d: Path) -> int:
    d = Path(d)
    if not d.is_dir():
        return 0
    return sum(p.stat().st_size for p in d.iterdir() if p.is_file())


def _waves(phase1: Path) -> list[tuple[str, Path]]:
    """`waves/wave_NNN` 目录，按名字排序。没有就返回空。"""
    wdir = phase1 / "waves"
    if not wdir.is_dir():
        return []
    return [(p.name, p) for p in sorted(wdir.iterdir()) if p.is_dir()]


def _episodes(phase1: Path) -> list[Path]:
    edir = phase1 / "episodes"
    if not edir.is_dir():
        return []
    return [p for p in sorted(edir.iterdir()) if p.is_dir()]


def _episode_outcome(ep: Path) -> dict:
    """一个 episode 的读数。优先 `outcome.json`，退到 `result.json`。"""
    for name in ("outcome.json", "result.json"):
        doc = _read_json(ep / name)
        if doc:
            return doc
    return {}


def transfer_report(wave_dir: Path, *, roots: list[Path] | None = None) -> dict:
    """读一个波次根目录，产出「记忆在波次之间怎么走」的读数。

    `wave_dir` 指向 `<root>/<wave>`（含 `phase1/`），或直接指向 `phase1/`。

    `roots` 是**波次之间的接续**要扫的父目录。给了一律扫，因为「这一波带着哪些
    记忆进来的」只有跨波次才看得出来。2026-10-21 实测 bfs17 的 `memory_before`
    带着 bfs16 那三份记忆的 sha256——**跨波次继承是真的**。
    """
    wave_dir = Path(wave_dir)
    phase1 = wave_dir if wave_dir.name == "phase1" else wave_dir / "phase1"
    result = _read_json(phase1 / "result.json")
    waves = _waves(phase1)
    episodes = _episodes(phase1)

    # 每波的读数：这一波开始时的快照、这一波派了几个项目。
    wave_rows = []
    for name, wdir in waves:
        snap = wdir / "memory_snapshot"
        # 项目数是 curriculum 的**决定**，落在 `curriculum_decision.json`
        # （顶层 `decision` / `rationale` / `projects`）。
        decision = _read_json(wdir / "curriculum_decision.json")
        wave_rows.append({
            "wave": name,
            "memory_snapshot": _memory_files(snap),
            "memory_snapshot_bytes": _memory_bytes(snap),
            # 这一波派了几个项目。curriculum 硬要求「一波最多 1 个项目」
            # （`curriculum-usine.yaml:107`），所以这个数通常是 1，而
            # **1 个/波 正是「跨项目迁移测不到」的机制原因**：预算数的是项目，
            # 一波只派一个，记忆就只在波次之间接续，永远不会在「同一波的两个
            # 项目」之间被试。读数里必须能看见这个数。
            "projects_declared": len(decision.get("projects") or []),
            "curriculum_decision": decision.get("decision"),
            # 这一波跑完后，项目在 `memory_after_commit` 里写下的记忆。
            # 它是**下一波快照的来源**——跨波接续要拿它比，不能拿上一波快照比。
            "produced": [],
        })

    # 把 episode 按波次归位。产物布局是 `episodes/epNNN`（单调编号），
    # 第 N 波派了几个项目就从编号里切几个出来。这样即使某一波的项目中途失败
    # （episode 目录缺 `outcome.json`），归位仍然按顺序对得上。
    eps = _episodes(phase1)
    cursor = 0
    for row in wave_rows:
        n = row["projects_declared"] or 0
        for ep in eps[cursor:cursor + n]:
            row["produced"].extend(_memory_files(ep / "memory_after_commit"))
        row["produced"] = sorted(set(row["produced"]))
        cursor += n

    # 跨波接续：第 N 波的快照，是否装下了第 N-1 波跑完之后写下的记忆。
    #
    # **这里的第一版判错了**：它把「本波快照」与「上一波快照」比。但上一波快照
    # 是上一波**开始时**的记忆，而本波快照应当在上一波**结束后**的记忆之上——
    # 拿两个快照比，等于要求「记忆不变」，而那正好是「没有学到东西」。
    # 2026-10-21 自检抓到（8 条断言同时红），改成与上一波的 `produced` 比。
    for i, row in enumerate(wave_rows):
        if i == 0:
            row["inherited_previous"] = None
            continue
        prev_produced = set(wave_rows[i - 1]["produced"])
        if not prev_produced:
            # 上一波没产出记忆 → 没有可继承的东西，这一格不判「断链」。
            row["inherited_previous"] = None
        else:
            # 继承 = 上一波的产出 **全都**在本波快照里（允许本波快照还带着更早的）。
            row["inherited_previous"] = prev_produced.issubset(set(row["memory_snapshot"]))

    # 每个项目一行（用于看表现方向与删除记录）。
    project_rows = []
    for i, ep in enumerate(episodes):
        out = _episode_outcome(ep)
        changes = out.get("memory_changes") or {}
        project_rows.append({
            "project": i + 1,
            "episode": ep.name,
            "terminal_outcome": out.get("terminal_outcome"),
            "verification_cycles": out.get("verification_cycles"),
            "memory_before": sorted(out.get("memory_before") or []),
            "memory_after": _memory_files(ep / "memory_after_commit"),
            "memory_deleted": [str(x) for x in (changes.get("deleted") or [])],
        })

    lineage = _lineage(phase1, wave_dir, roots or [])
    verdict, why = _verdict(wave_rows, project_rows, result)
    return {
        "wave": wave_dir.name,
        "project_budget": result.get("project_budget"),
        "projects_done": result.get("projects"),
        "status": result.get("status"),
        "memory_files_final": result.get("memory_files"),
        "memory_bytes": _memory_bytes(phase1 / "memory"),
        "waves_observed": len(wave_rows),
        "episodes_observed": len(project_rows),
        "waves": wave_rows,
        "projects": project_rows,
        "lineage": lineage,
        "verdict": verdict,
        "why": why,
    }


def _lineage(phase1: Path, wave_dir: Path, roots: list[Path]) -> dict:
    """**本波开始前**这个 lineage 里已经有哪些记忆、由哪些波次写下。

    判据只有一条、且是机检的：本波第一份 `memory_snapshot` 的文件名集合，
    是否等于另一个波次结束时的记忆集合。
    """
    waves = _waves(phase1)
    first = waves[0][1] / "memory_snapshot" if waves else None
    before = _memory_files(first) if first else []
    if not before:
        return {"inherited": False, "from": [], "note": "这一波开始时记忆是空的（首波）"}

    sources: list[str] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for other in sorted(root.iterdir()):
            if not other.is_dir() or other.name == wave_dir.name:
                continue
            ofirst = _waves(other / "phase1")
            if not ofirst:
                continue
            # 上一波结束时 = 它最后一波跑完后写进 lineage/memory 的那套文件。
            oend = set(_memory_files(other / "phase1" / "memory"))
            if oend and oend == set(before):
                sources.append(other.name)
    return {
        "inherited": bool(sources),
        "from": sources,
        "note": (
            f"带进来的记忆：{', '.join(before)}（来自 {'、'.join(sources)}）"
            if sources
            else f"带着 {len(before)} 份记忆，但在扫描的父目录里没找到写它们的波次"
        ),
    }


def _verdict(wave_rows: list[dict], project_rows: list[dict], result: dict) -> tuple[str, str]:
    """判决。**证据不足时明说不足，不硬凑结论。**

    顺序有讲究：先判「有没有跑出东西」，再判「记忆链完不完整」，最后才谈表现方向。
    反过来的话，一个只跑了 1 个项目的波次会先被「表现正常」吞掉。
    """
    n_proj = len(project_rows)
    n_wave = len(wave_rows)

    if n_proj == 0:
        return (
            "no_episodes",
            "波次里没有 episode 产物——这一轮没有项目跑起来，谈不上跨项目迁移",
        )

    # **单项目**：即使跨波次继承是真的，也没在第二个项目上试过。
    if n_proj == 1:
        return (
            "single_project",
            "**只有一个项目**：记忆写了但没在第二个项目上被试过。"
            "这不是「迁移失败」，是**迁移从未被观测**——"
            "要让这一格有读数，把 `--project-budget` 调大即可："
            "预算数的是**项目**，而 curriculum 每波派 1 个"
            "（`curriculum-usine.yaml:107`），所以 `--project-budget 3` 会跑出"
            "3 个波次、每波 1 个 episode（ep001…ep003），"
            "而 `lineage/memory` 跨波次累计——ep002 起跑时读到的就是 ep001 写下的记忆。"
            "这正是可观测的跨项目迁移，机制不需要任何改动",
        )

    # 记忆被删：退化信号，且不看净数量。
    deleted = [r for r in project_rows if r.get("memory_deleted")]
    if deleted:
        which = "、".join(
            f"{r['episode']}（删 {'、'.join(r['memory_deleted'])}）" for r in deleted
        )
        return (
            "memory_shrank",
            f"有 {len(deleted)} 个项目删了既有记忆：{which}——"
            f"删记忆是退化信号（可能是「为通过某一格把碍事的规矩删了」，"
            f"那种改动在产物判据上完全看不出来）。先查为什么删，再谈迁移",
        )

    # 跨波次继承断了：本波快照里没有上一波写的记忆。
    broken = [r for r in wave_rows[1:] if r.get("inherited_previous") is False]
    if broken:
        return (
            "broken_lineage",
            f"**记忆没有跨波接续**：{len(broken)} 个波次的快照与上一波结束时的记忆"
            f"不同（{'、'.join(r['wave'] for r in broken)}）——"
            f"迁移链断了，后面的表现方向不能用来判迁移",
        )

    outcomes = [r["terminal_outcome"] for r in project_rows]
    n_pass = sum(1 for o in outcomes if o == "PASS")
    if n_pass == n_proj:
        return (
            "all_pass",
            f"{n_proj} 个项目全部 PASS，记忆逐波增长且接续——"
            f"这是**正向但不充分**的证据：全过意味着天花板效应，"
            f"看不出记忆有没有帮上忙（要做对照得跑同题无记忆臂）",
        )
    return (
        "mixed",
        f"{n_proj} 个项目里 {n_pass} 个 PASS、{n_proj - n_pass} 个不是——"
        f"**方向混合**。项目难度不受控，所以「后一个更差」不能直接归因于记忆；"
        f"要判负迁移得有「同题、有记忆 vs 无记忆」的对照（`--memory-seed`）",
    )


def format_report(rep: dict) -> str:
    """人读的形状。**每一行都要能追到盘上的一个文件。**"""
    out = [
        f"波次 {rep['wave']}：{rep['verdict']}",
        f"  {rep['why']}",
        "",
        f"  project_budget={rep['project_budget']}  projects={rep['projects_done']}  "
        f"status={rep['status']}  波次={rep['waves_observed']}  "
        f"记忆={rep['memory_files_final']} 文件 / {rep['memory_bytes']} B",
    ]
    if rep["lineage"].get("note"):
        out.append(f"  接续：{rep['lineage']['note']}")
    if rep["waves"]:
        out.append("")
        out.append("  | 波次 | 快照文件 | 继承上一波 | 派了几个项目 |")
        out.append("  |---|---|---|---|")
        for w in rep["waves"]:
            inh = "—" if w["inherited_previous"] is None else ("是" if w["inherited_previous"] else "**否**")
            out.append(
                f"  | {w['wave']} | {len(w['memory_snapshot'])} | {inh} | {w['projects_declared']} |"
            )
    if rep["projects"]:
        out.append("")
        out.append("  | # | episode | outcome | cycles | 记忆文件 | 删了什么 |")
        out.append("  |---|---|---|---|---|---|")
        for r in rep["projects"]:
            dele = "、".join(r["memory_deleted"]) if r["memory_deleted"] else "—"
            out.append(
                f"  | {r['project']} | {r['episode']} | {r['terminal_outcome']} | "
                f"{r['verification_cycles']} | {len(r['memory_after'])} | {dele} |"
            )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A 线跨项目迁移读数")
    ap.add_argument("wave", type=Path, help="波次目录（含 phase1/）")
    ap.add_argument(
        "--roots",
        default="",
        help="逗号分隔的父目录（扫波次之间的接续；默认用波次的上一级）",
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是表格")
    args = ap.parse_args(argv)

    roots = [Path(p) for p in args.roots.split(",") if p.strip()] if args.roots else []
    if not roots:
        roots = [args.wave.resolve().parent]
    rep = transfer_report(args.wave, roots=roots)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(format_report(rep))
    # 证据不足时非零退出：让调用方（脚本 / CI / 人）无法把它当成「通过」。
    return 0 if rep["verdict"] not in _INSUFFICIENT else 1


if __name__ == "__main__":
    sys.exit(main())
