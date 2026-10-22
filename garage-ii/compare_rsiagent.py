#!/usr/bin/env python3
"""compare_rsiagent.py —— 三臂对照：同一个 dsh 智能体，三种「进化沉淀物」。

**为什么必须是三臂而不是两臂。** 要回答的问题是「harness2 改 harness 与 RSIAgent 改
记忆，对这个 dsh 智能体哪个更管用」。只比这两个，比的是**两套方法各自的绝对分**——
而两套方法跑在不同的基线之上，这个差里混着「起点不同」。所以必须有第三个臂：
**原封不动的基线**。三臂同任务、同模型、同判据，两两之差才是「这个沉淀物值多少」。

| 臂 | 智能体拿到的额外东西 | 对应哪套引擎 |
|---|---|---|
| `base` | 无（基准 harness 本身） | 起点 |
| `h2` | 演化后的 harness 树（AGENTS.md 四节 + 技能 + 脚本） | harness2 / theatre-ii |
| `rsi` | 一份冻结的 Markdown 记忆语料（挂成 AGENTS.md 的一节） | RSIAgent / théâtre+garage |

**这一版测的是「通道」，不是「沉淀物质量」。** RSIAgent 那一臂的记忆语料要由
`garage/`（RSIAgent 引擎那侧）真的跑出来才有意义。那边**已经跑出过产物**
（`../docs/self-evolution.md` §7.1：三条合并提交 + DRS 的 `memory_changed: true`），
**但那份记忆树只活在仓库外的 run root 里，没有入库、也没有导出成可挂载的语料目录**——
2026-10-21 盘上复核时三棵树都还在、都可读（§7.1），只是**仍然没有导出成可挂载的语料目录**。
所以今天 rsi 臂仍然拿不到语料，原因是「没导出」，不是「没产出」。
本脚本因此：

- `--arms rsi --memory <dir>` 接受一份外部记忆语料（引擎那侧产出后喂进来）；
- 没给 `--memory` 时，rsi 臂**照跑**，但报告里那一栏标成「记忆语料缺席」——
  **不许拿一个空记忆的分数去说 RSIAgent 不行**。空记忆那一栏测的是「什么都没有」，
  不是「RSIAgent 的记忆没用」。

跑法：

    python3 garage-ii/compare_rsiagent.py --dry-run
    python3 garage-ii/compare_rsiagent.py --ack RUN-USINE-H2-COMPARE
    python3 garage-ii/compare_rsiagent.py --arms rsi --memory /path/to/frozen/memory \\
        --ack RUN-USINE-H2-COMPARE
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (str(REPO / "theatre-ii"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness2.core import tree as HT  # noqa: E402

from bench_usine import TASKS  # noqa: E402
from dsh_substrate import DSH_SURFACE, read_tree  # noqa: E402
from preflight import DEFAULT_ROOT, run_all  # noqa: E402
from usine_adapter import UsineAdapter  # noqa: E402

COMPARE_ACK = "RUN-USINE-H2-COMPARE"

ARMS = ("base", "h2", "rsi")


@dataclass
class ArmResult:
    arm: str
    task_id: str
    score: float | None = None
    n_passed: int | None = None
    n_criteria: int | None = None
    graded: bool = False
    error: str = ""
    #: 这一臂往智能体脸上放了什么（人话，报告里要显示）
    channels: list[str] = field(default_factory=list)


def _h2_harness_dir(runs_root: Path, k: int, seed: int | None) -> Path | None:
    """从 harness2 的产物里找**被选中**的 harness 树。

    两种布局都要认（2026-10-20 修：原来只认 `adapt/`，而实跑用的是 `sweep`）：

    - `--phase adapt`：`<root>/<ns>/<task>/summary.json` 里记着 `chosen_harness_dir`；
    - `--phase sweep`：`<root>/trees/<label>/<task>/`——引擎把被选中的树整棵抽出来落盘。

    只认第一种时，h2 臂会**静默退化成基线**，报告上看起来「h2 与 base 一样」——
    那测的是「没找到树」，不是「演化没用」。所以找不到也返回 None，但调用方必须
    在报告里写明取的是哪一份（`_report` 已经会写）。
    """
    from harness2.core import schedule as SCHED

    cands: list[Path] = []

    # (a) sweep 布局：trees/<label>/<task>/（树的根是带 systemprompt.md 的那层）
    trees_root = Path(runs_root) / "trees"
    if trees_root.is_dir():
        for tree_root in sorted(trees_root.iterdir()):
            if not tree_root.is_dir():
                continue
            for task_dir in sorted(tree_root.iterdir()):
                if task_dir.is_dir() and (task_dir / "systemprompt.md").is_file():
                    cands.append(task_dir)
                elif task_dir.is_dir():
                    for sub in sorted(task_dir.iterdir()):
                        if sub.is_dir() and (sub / "systemprompt.md").is_file():
                            cands.append(sub)

    # (b) adapt 布局：summary.json 的选择记录
    ns = SCHED.ns("usine-dsh", "dsh", "agg", k, seed=seed)
    ns_dir = Path(runs_root) / "adapt" / ns
    if ns_dir.is_dir():
        for summary_path in sorted(ns_dir.glob("*/summary.json")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for mode_sel in (summary.get("selections") or {}).values():
                if not isinstance(mode_sel, dict):
                    continue
                for key in ("chosen_harness_dir", "harness_dir", "chosen_dir"):
                    val = mode_sel.get(key)
                    if val:
                        p = Path(val)
                        if not p.is_absolute():
                            p = ns_dir / p
                        if p.is_dir():
                            cands.append(p)

    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _memory_section(memory_dir: Path) -> str:
    """把一份 Markdown 记忆语料读成 AGENTS.md 的一节。

    RSIAgent 的沉淀物是「无 schema 的 Markdown 语料库」（论文 §3.1），这里按它原本的
    形状读：一个目录里的 .md 文件，按路径排序拼进去。**不解析、不改写、不摘要**——
    记忆的形状是 RSIAgent 那一侧的决定，这一层只负责把它送到智能体面前。
    """
    parts: list[str] = []
    for md in sorted(memory_dir.rglob("*.md")):
        if md.is_file():
            parts.append(f"<!-- memory: {md.relative_to(memory_dir).as_posix()} -->\n"
                         f"{md.read_text(encoding='utf-8', errors='replace').strip()}")
    if not parts:
        return ""
    return "\n\n---\n\n".join(parts) + "\n"


def _arm_tree(arm: str, base: Path, h2_dir: Path | None, memory_dir: Path | None) -> tuple[dict, list[str]]:
    """造出这一臂的 harness 树。返回 (树, 这一臂用了哪些通道)。"""
    tree = read_tree(DSH_SURFACE, base)
    channels: list[str] = []

    if arm == "h2":
        if h2_dir is None:
            channels.append("（h2 臂退化：没找到被选中的 harness 树，等同基线）")
        else:
            tree = read_tree(DSH_SURFACE, h2_dir)
            channels.append("harness 树（AGENTS.md 四节 + 技能 + 脚本）")

    if arm == "rsi":
        if memory_dir is None:
            channels.append("（rsi 臂退化：**记忆语料缺席**——这一栏测的是「什么都没有」，"
                            "不是「RSIAgent 的记忆没用」）")
        else:
            section = _memory_section(memory_dir)
            if not section:
                channels.append("（rsi 臂退化：记忆目录里没有 .md）")
            else:
                tree = dict(tree)
                # 记忆挂成 AGENTS.md 的第五节：位置固定，内容由 RSIAgent 那边决定。
                tree["systemprompt.md"] = (
                    tree.get("systemprompt.md", "").rstrip()
                    + "\n\n---\n\n<!-- dsh-harness:memory -->\n<!-- 冻结记忆语料 -->\n"
                    + section
                )
                channels.append(f"冻结记忆语料（{len(list(memory_dir.rglob('*.md')))} 个 .md）")

    return tree, channels


def _run_arm(arm: str, args, base: Path, h2_dir: Path | None, memory_dir: Path | None) -> list[ArmResult]:
    out: list[ArmResult] = []
    for task in TASKS:
        tree, channels = _arm_tree(arm, base, h2_dir, memory_dir)
        with tempfile.TemporaryDirectory(prefix=f"cmp-{arm}-") as td:
            harness_dir = Path(td) / "harness"
            try:
                HT.write_tree(DSH_SURFACE, tree, harness_dir)
                adapter = UsineAdapter(runs_root=Path(td) / "runs", timeout=args.timeout)
                run_dir = adapter.execute(task.task_id, harness_dir, f"{arm}-0")
            except Exception as exc:
                out.append(
                    ArmResult(arm, task.task_id, error=f"{type(exc).__name__}: {exc}",
                              channels=channels)
                )
                continue
            got = adapter.score(run_dir, task.task_id)
        if not got:
            out.append(ArmResult(arm, task.task_id, error="judge returned nothing",
                                  channels=channels))
            continue
        out.append(
            ArmResult(
                arm=arm,
                task_id=task.task_id,
                score=float(got.get("score", 0.0)),
                n_passed=got.get("n_passed"),
                n_criteria=got.get("n_criteria"),
                graded=True,
                channels=channels,
            )
        )
    return out


def _report(results: list[ArmResult], args, h2_dir: Path | None, memory_dir: Path | None) -> str:
    lines: list[str] = []
    lines.append("# usine × dsh：三种沉淀物的对照")
    lines.append("")
    lines.append(
        f"生成：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}　"
        f"任务集：{len(TASKS)} 个　"
        f"h2 臂的 harness 树：{h2_dir if h2_dir else '**缺席**（退化成基线）'}　"
        f"rsi 臂的记忆语料：{memory_dir if memory_dir else '**缺席**（退化成空记忆）'}"
    )
    lines.append("")
    lines.append("## 逐任务")
    lines.append("")
    lines.append("| 任务 | " + " | ".join(ARMS) + " |")
    lines.append("|---|" + "---|" * len(ARMS))
    for task in TASKS:
        cells: list[str] = []
        for arm in ARMS:
            r = next((x for x in results if x.arm == arm and x.task_id == task.task_id), None)
            if r is None:
                cells.append("—")
            elif not r.graded:
                cells.append(f"未判（{r.error[:40]}）")
            else:
                cells.append(f"{r.score:.2f}（{r.n_passed}/{r.n_criteria}）")
        lines.append(f"| `{task.task_id}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## 汇总（只统计判成功的；判失败的不算零分）")
    lines.append("")
    lines.append("| 臂 | 判成功 | 平均分 | 通道 |")
    lines.append("|---|---|---|---|")
    for arm in ARMS:
        rows = [r for r in results if r.arm == arm and r.graded]
        ungraded = len([r for r in results if r.arm == arm and not r.graded])
        avg = sum(r.score for r in rows) / len(rows) if rows else float("nan")
        chan = "；".join(sorted({c for r in results if r.arm == arm for c in r.channels})) or "—"
        lines.append(f"| `{arm}` | {len(rows)}（未判 {ungraded}） | {avg:.3f} | {chan} |")
    lines.append("")

    if memory_dir is None:
        lines.append(
            "> **读这张表之前必须知道**：rsi 臂没有记忆语料。RSIAgent 引擎那侧（`garage/`）"
            "**已经跑出过产物**（`../docs/self-evolution.md` §7.1：三条合并提交、DRS 的 "
            "`memory_changed: true`），但那份记忆树只在仓库外的 run root 里，没入库、"
            "也没导出成可挂载的语料目录——2026-10-21 盘上复核时三棵树都还在、都可读，"
            "只是**仍然没有导出成语料目录**。所以 rsi 这一栏测的是「记忆缺席」，"
            "**不能**据此说 RSIAgent 对 dsh 智能体没用——它测的是另一个东西。"
            "要补这一栏：下一次 DRS 用 `--memory-seed <dir>` 把记忆树导出来，再 "
            "`--memory <dir>` 喂进来。"
        )
        lines.append("")

    lines.append("## 这张表测不到什么")
    lines.append("")
    lines.append(
        "- **不测内容质量**。任务集只覆盖路由、红线、诚实三件**只有读了 harness 才知道**的事；"
        "海报好不好、视频好不好看不在测纲里（那要整套媒体栈，量级完全不同）。"
    )
    lines.append(
        "- **不测记忆治理**。RSIAgent 的记忆沉淀靠 Verifier 隔离 + 蒸馏/调和双提示词，"
        "本对照不评估这套治理机制本身，只评估**一份记忆语料**放到 dsh 面前时的效果。"
    )
    lines.append(
        "- **不测收敛性**。每个臂只跑一遍任务集，没有多 seed 重复，"
        "所以臂间的小差距**不构成结论**——只有大差距值得追查。"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--ack", default="")
    ap.add_argument("--arms", default=",".join(ARMS), help=f"要跑哪些臂（{','.join(ARMS)}）")
    ap.add_argument("--memory", type=Path, default=None, help="RSIAgent 冻结记忆语料目录")
    ap.add_argument(
        "--h2-tree",
        type=Path,
        default=None,
        help="直接指定 h2 臂的 harness 树（例如 sweep 的 trees/evo/<task>）；不给就去 --root 里找",
    )
    ap.add_argument("--k", type=int, default=1, help="h2 臂取哪个 k 的被选中 harness")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    bad = [a for a in arms if a not in ARMS]
    if bad:
        print(f"未知臂：{bad}（可选 {ARMS}）", file=sys.stderr)
        return 1

    base = HERE / "harness_base"
    h2_dir = args.h2_tree if args.h2_tree else _h2_harness_dir(args.root, args.k, args.seed)
    if h2_dir is not None and not (Path(h2_dir) / "systemprompt.md").is_file():
        print(f"--h2-tree 不是一棵 harness 树（缺 systemprompt.md）：{h2_dir}", file=sys.stderr)
        return 1
    memory_dir = args.memory

    if args.dry_run:
        print(f"# 对照三臂：{', '.join(arms)}")
        print(f"# 任务：{len(TASKS)} 个（{', '.join(t.task_id for t in TASKS)}）")
        print(f"# base harness: {base}")
        print(f"# h2 harness:   {h2_dir or '**缺席**（退化成基线）'}")
        print(f"# rsi memory:   {memory_dir or '**缺席**（退化成空记忆）'}")
        print("# dry-run：没跑任何 rollout")
        return 0

    if args.ack != COMPARE_ACK:
        print(f"对照要花钱，先把确认口令给我：--ack {COMPARE_ACK}", file=sys.stderr)
        return 1

    errs, warns = run_all(args.root)
    for w in warns:
        print(f"warn: {w}")
    if errs:
        print("preflight 未通过，什么都没跑：")
        for e in errs:
            print(f"  - {e}")
        return 1

    from dsh_substrate import dsh_json_mode

    if not dsh_json_mode():
        # 软提醒：轨迹走的是 SDK 的**规范 SessionEvent 流**（`tool/call` / `tool/result`），
        # 不是 CLI 的 `--json` 投影。CLI 版本旧**不影响**工具调用序列的可见性——
        # 所以这条现在只提醒，不拦对照。
        print(
            "note: PATH 上的 dsh CLI 没有 --json 投影。这**不影响**本次对照——"
            "轨迹走 SDK 的规范 SessionEvent 流，工具调用序列照样可见。",
            file=sys.stderr,
        )

    results: list[ArmResult] = []
    for arm in arms:
        print(f"[{arm}] 跑 {len(TASKS)} 个任务…", flush=True)
        results += _run_arm(arm, args, base, h2_dir, memory_dir)

    text = _report(results, args, h2_dir, memory_dir)
    out = args.root / "compare" / f"usine-dsh-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    (out.with_suffix(".json")).write_text(
        json.dumps([r.__dict__ for r in results], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(text)
    print(f"record: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
