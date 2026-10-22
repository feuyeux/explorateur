"""从两段式产物直接读泛化判决：`generalization_reading.py`。

为什么单独一个入口
==================
`--split both` 把读数写成两段产物，但**判决要等人来读**：`_sweep_one` 只负责
跑与落盘，`generalization.py` 只负责判。中间的「把产物读成逐格比较」这一层
原来散在一次性脚本里，读一次就丢。

这个工具就是那一层，它只做三件事：

1. 从 `<root>/<task>/<stage>/<task>/` 读基准臂的 `base1..basek`，以及
   **被盲选中的那一个** final（`aggN` / `cN`，从引擎写的 `selection.json` 读）；
2. 调 `UsineAdapter.score()` 算分（**判据只在这一处跑**，和 sweep 用的是同一个入口）；
3. 把逐格比较按 `task_split` 的两侧喂给 `generalization.overfit_report()`。

判决逻辑一个字都不在这里重复——它只在 `generalization.py` 里。这里错一个字段名，
报告就会把「Δ=0、p=1」读成满屏「判不出」，而它打印出来的东西仍然很像样。
**2026-10-22 实测正踩过这个**：第一版传的是 `delta` 而 `_side()` 读 `delta_mean`，
于是 25 格的真实差异全被读成 0，报告却说「train 侧没有任何显著变化」。
所以字段名是照着 `_side()` 的源码逐个核的，不是凭记忆写的。

**2026-10-22 又修了两处同类静默错误**：

- 旧实现硬取 `agg1`。k≥2 时引擎跑 `agg1..aggk`，真正被采纳的是**盲选会话
  挑中的那一个**——硬取 agg1 = 拿一条没被采纳的树代表演化结果。现在读
  `selection/<aggN|cN>/selection.json`；没有选择记录且盘上不止一个 final 时，
  这一格记「判不出」，**不猜**（唯一候选时才用它，并标明 `single_final`）。
- 旧实现只读 `base1`、并把 `p_value` 固定成 `1.0`，却按 `--k` 报「判别能力
  够」。于是 k≥3 时报告会说「train 侧没有任何显著变化」——那句话读起来像
  「测了没差别」，实际是「这个读者根本没做检验」。现在收齐 `base1..basek`
  的真实分数，对被选中的那一次 rollout 做**精确置换检验**（11 次基准 vs
  1 次演化，完全分离时 p=1/12≈0.083，是有判别能力的）；p 不再硬编码。

用法
====
    python3 garage-ii/generalization_reading.py --root ../../garage-ii-result \\
        --train-ns usine-dsh-dsh-agg1-train --eval-ns usine-dsh-dsh-agg1-eval

拿不到分数（判据没跑成）的格子显示 `None`，**不是零分**——那是「不知道」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# `bench_usine` 依赖 `harness2`，它在旁的 vendored 树里。
_THEATRE_II = HERE.parent / "theatre-ii"
if str(_THEATRE_II) not in sys.path:
    sys.path.insert(0, str(_THEATRE_II))

import arms as A  # noqa: E402
import bench_usine as B  # noqa: E402
import generalization as G  # noqa: E402
import task_split as S  # noqa: E402
from usine_adapter import UsineAdapter  # noqa: E402

_BASE_RE = re.compile(r"base(\d+)$")
_FINAL_RE = re.compile(r"(?:agg|c)(\d+)$")


def _base_labels(task_run_dir: Path) -> list[str]:
    """盘上的 `base1..basek`，按数字排序（不是按字典序：`base10` 在 `base2` 后）。"""
    if not task_run_dir.is_dir():
        return []
    labels = [p.name for p in task_run_dir.iterdir()
              if p.is_dir() and _BASE_RE.fullmatch(p.name)]
    return sorted(labels, key=lambda name: int(_BASE_RE.fullmatch(name).group(1)))


def _final_labels(task_run_dir: Path) -> list[str]:
    """盘上的 final 候选（`aggN` / `cN`），按数字排序。"""
    if not task_run_dir.is_dir():
        return []
    labels = [p.name for p in task_run_dir.iterdir()
              if p.is_dir() and _FINAL_RE.fullmatch(p.name)]
    return sorted(labels, key=lambda name: int(_FINAL_RE.fullmatch(name).group(1)))


def _score(adapter: UsineAdapter, run_dir: Path, task: str) -> float | None:
    if not run_dir.is_dir():
        return None
    sc = adapter.score(run_dir, task)
    return None if sc is None else sc["score"]


def read_stage(adapter: UsineAdapter, root: Path, ns: str) -> dict[str, dict]:
    """一格 → 基准的所有 rollout 分数 + **被选中的** final 的分数。

    返回每格：

    - ``base_scores`` / ``base_labels``：`base1..basek` 里判成了的那些；
    - ``evolved_label`` / ``evolved_score``：盲选出来的标签及其分数；
    - ``selection``：``record``（有选择记录）/ ``single_final``（唯一候选）/
      ``missing_selection``（多个候选却没有记录，**不猜**）/ ``no_final``。
    """
    out: dict[str, dict] = {}
    d = root / "adapt" / ns
    if not d.is_dir():
        return out
    for td in sorted(d.glob("*")):
        if not td.is_dir() or td.name == "context":
            continue
        task = td.name
        run_task = root / task / ns / task
        labels = _base_labels(run_task)
        base_scores: list[float] = []
        base_missing: list[str] = []
        for label in labels:
            score = _score(adapter, run_task / label, task)
            if score is None:
                base_missing.append(label)
            else:
                base_scores.append(score)

        finals = _final_labels(run_task)
        chosen = A._selected_label_or_none(td)
        if chosen is not None:
            selection = "record"
        elif len(finals) == 1:
            chosen = finals[0]
            selection = "single_final"
        else:
            selection = "missing_selection" if finals else "no_final"
        evolved_score = _score(adapter, run_task / chosen, task) if chosen else None
        out[task] = {
            "base_scores": base_scores,
            "base_labels": labels,
            "base_missing": base_missing,
            "evolved_label": chosen,
            "evolved_score": evolved_score,
            "finals": finals,
            "selection": selection,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="读两段式产物的泛化判决")
    ap.add_argument("--root", required=True, help="run root（仓库外）")
    ap.add_argument("--train-ns", required=True, help="train 段的命名空间（目录名）")
    ap.add_argument("--eval-ns", required=True, help="eval 段的命名空间")
    ap.add_argument(
        "--k", type=int, default=0,
        help="可选的交叉检查：与盘上 base1..basek 的条数不一致时打印警告；"
             "0 = 完全按盘上产物自动数（推荐）。**不再用它假装有判别能力**："
             "判别能力由真实 rollout 数算。",
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

    train = read_stage(adapter, root, args.train_ns)
    test = read_stage(adapter, root, args.eval_ns)

    warnings: list[str] = []
    if args.k:
        for side, data in (("train", train), ("test", test)):
            for task, row in data.items():
                if len(row["base_labels"]) != args.k:
                    warnings.append(
                        f"{side}/{task}: --k={args.k} 但盘上有 "
                        f"{len(row['base_labels'])} 个 base rollout"
                        f"（{row['base_labels']}）——按盘上的数算")

    if not args.json:
        print(f"切分 {S.split_digest(B.TASKS)}：train {len(train_ids)} / eval {len(test_ids)}")
        print(f"读数：train {len(train)} 格 / eval {len(test)} 格")
        for warning in warnings:
            print(f"  警告：{warning}")
        multi = [row for data in (train, test) for row in data.values()
                 if len(row["finals"]) > 1]
        if multi:
            print("  注：演化侧是**盲选出来的那一次** rollout；k≥2 时选择本身"
                  "带选择偏差，p 只按「1 次演化 vs k 次基准」算，不校正选树。")
        print()

    comps: list[dict] = []
    missing: list[dict] = []
    for side, data in (("train", train), ("test", test)):
        for task, row in data.items():
            base_scores = row["base_scores"]
            evolved_score = row["evolved_score"]
            if not base_scores or evolved_score is None:
                missing.append({
                    "side": side,
                    "task": task,
                    "base_scores": base_scores,
                    "base_labels": row["base_labels"],
                    "evolved_label": row["evolved_label"],
                    "evolved_score": evolved_score,
                    "selection": row["selection"],
                })
                continue
            base_mean = sum(base_scores) / len(base_scores)
            delta = evolved_score - base_mean
            comps.append({
                "task_id": task,
                "side": side,
                "base_mean": base_mean,
                "evolved_mean": evolved_score,
                "base": base_mean,
                "evolved": evolved_score,
                "delta": delta,
                # **字段名必须与 generalization._side() 一致**。传错不会报错，
                # 它会取默认 (0.0, 1.0)，把每一格读成「Δ=0、p=1」。
                "delta_mean": delta,
                # 真检验：基准的 k 个 rollout vs 被选中的那一次演化 rollout。
                # 不再硬编码 p=1.0——那会让 k≥3 的报告说出「测了没差别」。
                "p_value": A._exact_permutation_p(base_scores, [evolved_score]),
                "base_n": len(base_scores),
                "evolved_n": 1,
                "evolved_label": row["evolved_label"],
                "selection": row["selection"],
            })

    if not args.json:
        print("=== 逐格读数 ===")
        print(f"  {'side':<6} {'task':<30} {'base':>6} {'agg':>6} {'Δ':>7} "
              f"{'p':>6}  label")
        for c in sorted(comps, key=lambda x: (x["side"], x["task_id"])):
            print(f"  {c['side']:<6} {c['task_id']:<30} {c['base']:>6.2f} "
                  f"{c['evolved']:>6.2f} {c['delta']:>+7.2f} "
                  f"{c['p_value']:>6.3f}  {c['evolved_label']}"
                  f"{'（唯一候选）' if c['selection'] == 'single_final' else ''}")
        if missing:
            print(f"\n=== 判不出（{len(missing)} 格）===")
            for item in missing:
                reason = item["selection"]
                if item["base_scores"] and item["evolved_score"] is None:
                    reason = f"evolved {item['evolved_label']} 没判成"
                elif not item["base_scores"]:
                    reason = "基准 rollout 一个都没判成"
                print(f"  {item['side']:<6} {item['task']:<30} "
                      f"base={item['base_scores']} "
                      f"evolved={item['evolved_label']}:{item['evolved_score']} "
                      f"（{reason}）")
            print("  注：None = 判据本身没跑成（未交付 / 环境失败），**不是零分**。")

    report = G.overfit_report(comps, train_ids=train_ids, test_ids=test_ids)

    if args.json:
        print(json.dumps({"report": report, "comparisons": comps,
                          "missing": missing, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    else:
        print()
        print(G.format_report(report))

    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"report": report, "comparisons": comps,
                        "missing": missing, "warnings": warnings},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not args.json:
            print(f"\n落盘：{out}")

    # **no_data / underpowered 都以非零退出**：让调用方无法把它们当成「有结论」。
    return 0 if report["verdict"] not in {"no_data", "underpowered"} else 1


if __name__ == "__main__":
    sys.exit(main())
