"""从两段式产物直接读泛化判决：`generalization_reading.py`。

为什么单独一个入口
==================

`--split both` 把读数写成两段产物，但**判决要等人来读**：`_sweep_one` 只负责
跑与落盘，`generalization.py` 只负责判。中间的「把产物读成逐格比较」这一层
原来散在一次性脚本里，读一次就丢。

这个工具就是那一层，它只做三件事：

1. 从 `<root>/<task>/<stage>/<task>/<arm>/` 读 `base1` 与 `agg1` 的产物路径；
2. 调 `UsineAdapter.score()` 算分（**判据只在这一处跑**，和 sweep 用的是同一个入口）；
3. 把逐格比较按 `task_split` 的两侧喂给 `generalization.overfit_report()`。

判决逻辑一个字都不在这里重复——它只在 `generalization.py` 里。这里错一个字段名，
报告就会把「Δ=0、p=1」读成满屏「判不出」，而它打印出来的东西仍然很像样。
**2026-10-22 实测正踩过这个**：第一版传的是 `delta` 而 `_side()` 读 `delta_mean`，
于是 25 格的真实差异全被读成 0，报告却说「train 侧没有任何显著变化」。
所以字段名是照着 `_side()` 的源码逐个核的，不是凭记忆写的。

用法
====

    python3 garage-ii/generalization_reading.py --root ../../garage-ii-result \\
        --train-ns usine-dsh-dsh-agg1-train --eval-ns usine-dsh-dsh-agg1-eval

拿不到分数（判据没跑成）的格子显示 `None`，**不是零分**——那是「不知道」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# `bench_usine` 依赖 `harness2`，它在旁的 vendored 树里。
_THEATRE_II = HERE.parent / "theatre-ii"
if str(_THEATRE_II) not in sys.path:
    sys.path.insert(0, str(_THEATRE_II))

import bench_usine as B  # noqa: E402
import generalization as G  # noqa: E402
import task_split as S  # noqa: E402
from usine_adapter import UsineAdapter  # noqa: E402


def read_stage(adapter: UsineAdapter, root: Path, ns: str, *, k: int) -> dict[str, dict]:
    """一格 → `{base1: 分数|None, agg1: 分数|None, k: rollout 数}`。"""
    out: dict[str, dict] = {}
    d = root / "adapt" / ns
    if not d.is_dir():
        return out
    for td in sorted(d.glob("*")):
        if not td.is_dir() or td.name == "context":
            continue
        task = td.name
        row: dict = {"k": k}
        for arm in ("base1", "agg1"):
            run_dir = root / task / ns / task / arm
            sc = adapter.score(run_dir, task) if run_dir.is_dir() else None
            row[arm] = None if sc is None else sc["score"]
        out[task] = row
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="读两段式产物的泛化判决")
    ap.add_argument("--root", required=True, help="run root（仓库外）")
    ap.add_argument("--train-ns", required=True, help="train 段的命名空间（目录名）")
    ap.add_argument("--eval-ns", required=True, help="eval 段的命名空间")
    ap.add_argument(
        "--k", type=int, default=1,
        help="每臂每格的 rollout 数。**影响判决**：k<3 时置换检验没有判别能力，"
             "会判 underpowered。默认按 1（保守）。",
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", default="", help="把读数与判决落盘到这个路径")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        ap.error(f"--root 不是目录：{root}")
    adapter = UsineAdapter(runs_root=root)

    split = S.make_split(B.TASKS)
    train_ids, test_ids = set(split["train"]), set(split["test"])

    train = read_stage(adapter, root, args.train_ns, k=args.k)
    test = read_stage(adapter, root, args.eval_ns, k=args.k)

    if not args.json:
        print(f"切分 {S.split_digest(B.TASKS)}：train {len(train_ids)} / eval {len(test_ids)}")
        print(f"读数：train {len(train)} 格 / eval {len(test)} 格")
        print()

    comps: list[dict] = []
    missing: list[tuple[str, str, object, object]] = []
    for side, data in (("train", train), ("test", test)):
        for task, row in data.items():
            b, e = row.get("base1"), row.get("agg1")
            if b is None or e is None:
                missing.append((side, task, b, e))
                continue
            comps.append({
                "task_id": task,
                "side": side,
                "base": b,
                "evolved": e,
                "delta": e - b,
                # **字段名必须与 generalization._side() 一致**。传错不会报错，
                # 它会取默认 (0.0, 1.0)，把每一格读成「Δ=0、p=1」。
                "delta_mean": e - b,
                # k=1 时每格一个点，做不了置换检验 → p=1.0（判不出）。
                # 这是「测了但没有重复」，不是「测了没差别」。
                "p_value": 1.0,
                "n_rollouts": args.k,
            })

    if not args.json:
        print("=== 逐格读数 ===")
        print(f"  {'side':<6} {'task':<30} {'base':>6} {'agg':>6} {'Δ':>7}")
        for c in sorted(comps, key=lambda x: (x["side"], x["task_id"])):
            print(f"  {c['side']:<6} {c['task_id']:<30} {c['base']:>6.2f} "
                  f"{c['evolved']:>6.2f} {c['delta']:>+7.2f}")
        if missing:
            print(f"\n=== 判不出（分数 None，{len(missing)} 格）===")
            for side, task, b, e in missing:
                print(f"  {side:<6} {task:<30} base={b} agg={e}")
            print("  注：None = 判据本身没跑成（未交付 / 环境失败），**不是零分**。")

    report = G.overfit_report(comps, train_ids=train_ids, test_ids=test_ids)

    if args.json:
        print(json.dumps({"report": report, "comparisons": comps}, ensure_ascii=False, indent=2))
    else:
        print()
        print(G.format_report(report))

    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"report": report, "comparisons": comps, "missing": missing},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not args.json:
            print(f"\n落盘：{out}")

    # **no_data / underpowered 都以非零退出**：让调用方无法把它们当成「有结论」。
    return 0 if report["verdict"] not in {"no_data", "underpowered"} else 1


if __name__ == "__main__":
    sys.exit(main())
