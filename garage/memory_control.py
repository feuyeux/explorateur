"""记忆对照：把「记忆的因果效果」从「题目难度」里拆出来。

为什么必须有这个东西
====================

`transfer_check.py` 读的是**单条谱系**的表现方向，它有一个绕不过去的弱点：
不同波次干的是**不同的活**，难度不受控。所以「后一波更差」既可能是记忆有害，
也可能只是那道题更难。那个工具把这条限制写进了自己的 docstring，并且**拒绝**
从单谱系的方向得出「负迁移」的结论。

要判负迁移只有一条正路：**同一个项目、同一道题，有记忆 vs 无记忆**。

- 「有记忆」臂：`--memory-seed <目录>`，把上一轮学到的记忆注进去；
- 「无记忆」臂：不带 `--memory-seed`，同样的题、同样的配置。

两臂的差就是记忆的因果效果。`garage/run_usine.py` 已经支持 `--memory-seed`
（L1983/L2047），缺的只是**把两臂配起来读**的那一层。

它读什么、判什么
================

输入是两个（或更多）已完成波次的产物目录，每个目录带一个标签（`seed` / `plain`
之类）。工具从 `<wave>/phase1/result.json` 与 `episodes/*/outcome.json` 取读数，
然后：

1. **先验前提**：两臂必须是**同一批项目**。判据是两侧的项目题面摘要（`project.md`
   的 sha256）能对上——题不一样就没有可比性，直接拒判。
2. **再验对照是否干净**：`seed` 臂必须真的带着记忆起跑（第一波快照非空），
   `plain` 臂必须真的空着起跑。有一侧不干净，差就不是记忆的差。
3. **最后比表现**：`terminal_outcome`（PASS 记 1）、`verification_cycles`。

判决词：

| 判决 | 含义 |
|---|---|
| `no_control` | 一侧缺失，或两侧是同一个目录——**没有对照** |
| `not_paired` | 两臂的题面对不上——**不可比** |
| `dirty_control` | 有一臂没按设计起跑（记忆该有/该空）——**差不是记忆的** |
| `harmful` | 有记忆臂**显著更差**——这才是负迁移 |
| `helpful` | 有记忆臂更好 |
| `no_effect` | 两侧一样——记忆没起作用（可能是天花板，也可能是没读懂） |
| `inconclusive` | 样本太小，方向有但判不出 |

**`harmful` 的判据要比「平均分低」严**：必须有至少一个项目从 PASS 掉到非 PASS，
或者验证轮次在多数项目上变多。只是分数小幅下滑、方向混杂时，判 `inconclusive`
——那是「看不出来」，不是「有害」。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# 判决集合：前三个是「对照本身不成立」，中间三个是「有读数」，最后一个是「判不出」。
_NO_CONTROL = {"no_control", "not_paired", "dirty_control"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _memory_files(d: Path) -> list[str]:
    d = Path(d)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file())


def _episodes(phase1: Path) -> list[Path]:
    edir = phase1 / "episodes"
    if not edir.is_dir():
        return []
    return [p for p in sorted(edir.iterdir()) if p.is_dir()]


def _wave_dirs(phase1: Path) -> list[Path]:
    wdir = phase1 / "waves"
    if not wdir.is_dir():
        return []
    return [p for p in sorted(wdir.iterdir()) if p.is_dir()]


def _task_digest(ep: Path) -> str:
    """一个项目的题面指纹。**判「两臂是不是同一道题」只能看题面本身。**

    取 `project.md`（题面）的 sha256 前 12 位。产物名在不同轮次可能不同
    （`ep001` vs `ep002`），题面才是可比的那一层。
    """
    for name in ("project.md", "project.txt", "prompt.md"):
        f = ep / name
        if f.is_file():
            return hashlib.sha256(f.read_bytes()).hexdigest()[:12]
    return ""


def _arm_reading(path: Path) -> dict:
    """一条臂的读数。"""
    p1 = Path(path) if Path(path).name == "phase1" else Path(path) / "phase1"
    result = _read_json(p1 / "result.json")
    eps = _episodes(p1)

    projects = []
    for i, ep in enumerate(eps, 1):
        out = _read_json(ep / "outcome.json") or _read_json(ep / "result.json")
        projects.append({
            "index": i,
            "task_digest": _task_digest(ep),
            "terminal_outcome": out.get("terminal_outcome"),
            "verification_cycles": out.get("verification_cycles"),
            "passed": 1 if out.get("terminal_outcome") == "PASS" else 0,
        })

    # 起跑时记忆是不是空的——`seed` 臂该非空，`plain` 臂该空。
    waves = _wave_dirs(p1)
    first_snapshot = _memory_files(waves[0] / "memory_snapshot") if waves else []

    return {
        "path": str(path),
        "status": result.get("status"),
        "project_budget": result.get("project_budget"),
        "projects_done": result.get("projects"),
        "started_with_memory": bool(first_snapshot),
        "started_memory_files": first_snapshot,
        "projects": projects,
        "n_pass": sum(p["passed"] for p in projects),
        "n_projects": len(projects),
    }


def compare_arms(arms: dict[str, Path]) -> dict:
    """比两条臂。`arms` 形如 `{"seed": <dir>, "plain": <dir>}`。

    顺序不重要——工具自己按「起跑时有没有记忆」归类，不信标签。
    这样即使调用方把标签写反，结论也不会跟着反。
    """
    readings = {label: _arm_reading(p) for label, p in arms.items()}

    if len(readings) < 2:
        return {
            "verdict": "no_control",
            "why": f"只给了 {len(readings)} 条臂——对照需要至少两条",
            "arms": readings,
        }

    # **按实际起跑状态归类，不按标签**：标签写反是人的错，不该污染结论。
    with_mem = [lbl for lbl, r in readings.items() if r["started_with_memory"] and r["n_projects"]]
    no_mem = [lbl for lbl, r in readings.items() if not r["started_with_memory"] and r["n_projects"]]

    if not with_mem or not no_mem:
        return {
            "verdict": "no_control",
            "why": (
                "找不到一对「有记忆 / 无记忆」的起跑状态："
                f"带记忆起跑的臂={with_mem or '无'}，空记忆起跑的臂={no_mem or '无'}。"
                "两臂起点一样的话，差里没有记忆这个变量"
            ),
            "arms": readings,
        }

    a, b = with_mem[0], no_mem[0]
    ra, rb = readings[a], readings[b]

    # 题面必须对得上：按位置比题面指纹。
    pairs = list(zip(ra["projects"], rb["projects"]))
    mismatched = [
        (x["index"], x["task_digest"], y["task_digest"])
        for x, y in pairs
        if x["task_digest"] and y["task_digest"] and x["task_digest"] != y["task_digest"]
    ]
    if not pairs:
        return {
            "verdict": "no_control",
            "why": f"臂 {a} / {b} 里至少一侧没有 episode 产物",
            "arms": readings,
        }
    if mismatched:
        return {
            "verdict": "not_paired",
            "why": (
                f"两臂的题面对不上（{len(mismatched)} 处，例如第 {mismatched[0][0]} 个："
                f"{mismatched[0][1]} vs {mismatched[0][2]}）——"
                "题不一样就没有可比性。「后一个更差」在那种情形下什么都说明不了"
            ),
            "arms": readings,
            "pairs": [{"seed": x, "plain": y} for x, y in pairs],
        }

    # 逐项目配对差：+1 表示「有记忆」从非 PASS 变成 PASS，−1 是反过来。
    deltas = []
    for x, y in pairs:
        deltas.append({
            "index": x["index"],
            "delta_pass": x["passed"] - y["passed"],
            "delta_cycles": (
                None if x["verification_cycles"] is None or y["verification_cycles"] is None
                else x["verification_cycles"] - y["verification_cycles"]
            ),
        })

    n = len(deltas)
    n_better = sum(1 for d in deltas if d["delta_pass"] > 0)
    n_worse = sum(1 for d in deltas if d["delta_pass"] < 0)
    n_same = n - n_better - n_worse
    mean_delta = sum(d["delta_pass"] for d in deltas) / n
    cycles_worse = sum(
        1 for d in deltas if d["delta_cycles"] is not None and d["delta_cycles"] > 0
    )

    # **负迁移要比「平均分低」严**：至少一个项目真的从 PASS 掉下来。
    # 只看均值的话，一次 3 项目里「1 个掉、2 个不变」和「3 个都微降」会混在一起，
    # 而前者才是「记忆让某个项目变坏了」的形态。
    if n_worse > n_better:
        verdict = "harmful"
        why = (
            f"带记忆起跑的 {a} 有 {n_worse} 个项目比 {b} 差、{n_better} 个更好"
            f"（{n_same} 个相同）——**这是负迁移**：同一道题上，带着上一轮学到的"
            f"记忆反而做得更差"
        )
    elif n_better > n_worse:
        verdict = "helpful"
        why = (
            f"带记忆起跑的 {a} 有 {n_better} 个项目比 {b} 好、{n_worse} 个更差"
            f"（{n_same} 个相同）——记忆在这一次是有用的"
        )
    elif n_better == 0 and n_worse == 0:
        verdict = "no_effect"
        why = (
            f"{n} 个项目两臂完全相同（平均差 {mean_delta:+.2f}）——"
            f"记忆没起作用。两种可能：这题本来就都会做（天花板），"
            f"或者写下的记忆没被读懂。**分不开这两者**时别急着说「记忆无用」"
        )
    else:
        verdict = "inconclusive"
        why = (
            f"方向混合（好 {n_better} / 差 {n_worse} / 同 {n_same}，平均差 "
            f"{mean_delta:+.2f}）——{n} 个项目太少，判不出方向"
        )

    return {
        "verdict": verdict,
        "why": why,
        "with_memory_arm": a,
        "without_memory_arm": b,
        "n_projects": n,
        "n_better": n_better,
        "n_worse": n_worse,
        "n_same": n_same,
        "mean_delta_pass": mean_delta,
        "cycles_worse": cycles_worse,
        "per_project": deltas,
        "arms": readings,
    }


def format_report(rep: dict) -> str:
    out = [f"记忆对照：{rep['verdict']}", f"  {rep['why']}", ""]
    for label, r in rep["arms"].items():
        mem = "有记忆起跑" if r["started_with_memory"] else "空记忆起跑"
        out.append(
            f"  臂 {label}：{mem}（{len(r['started_memory_files'])} 份）  "
            f"PASS {r['n_pass']}/{r['n_projects']}  status={r['status']}"
        )
    if "per_project" in rep:
        out.append("")
        out.append("  | # | 差（PASS） | 差（验证轮次） |")
        out.append("  |---|---|---|")
        for d in rep["per_project"]:
            dc = "—" if d["delta_cycles"] is None else f"{d['delta_cycles']:+d}"
            out.append(f"  | {d['index']} | {d['delta_pass']:+d} | {dc} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="记忆对照：同一批题，有记忆 vs 无记忆")
    ap.add_argument(
        "--arm", action="append", default=[], metavar="LABEL=DIR",
        help="一条臂，形如 seed=../../garage-result/<名>（可重复）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    if not args.arm:
        ap.error("至少给一条 --arm")
    arms: dict[str, Path] = {}
    for spec in args.arm:
        if "=" not in spec:
            ap.error(f"--arm 要写成 LABEL=DIR，收到 {spec!r}")
        label, _, d = spec.partition("=")
        arms[label.strip()] = Path(d.strip())

    rep = compare_arms(arms)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json
          else format_report(rep))
    # 对照本身不成立时非零退出：让调用方无法把它当成「有结论」。
    return 0 if rep["verdict"] not in _NO_CONTROL else 1


if __name__ == "__main__":
    sys.exit(main())
