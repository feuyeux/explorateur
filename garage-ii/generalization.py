"""泛化报告：把 **train 侧与 eval 侧的 Δ 并排读**，显式判出过拟合。

为什么必须有这个模块
====================

在它之前，`arms.compare_arms()` 只回答一个问题：**「演化臂在这批任务上的均值，
与基准臂的均值，差不差得多」**。它不知道「这批任务」是哪一批。于是最坏的那种结果
读数上完全隐形：

    演化在训练题上把分从 0.6 拉到 0.9，在没见过的题上从 0.6 掉到 0.5。
    合并均值 = 0.7 > 0.6 ⇒ 报告写「有信号：演化臂显著优于基准」。

**这就是「一些 case 很好、另一些变坏」被均值和掉的机制**。它不是一个可以靠
「多跑几次」「看得更仔细」解决的问题——它需要**两个分离的测量**，而在此之前
第二个测量根本不存在（`split` 参数被忽略，见 `task_split.py` 的说明）。

判定口径（与 `compare_arms` 的分工）
====================================

- `compare_arms` 管**单格**：Δ > 0 且精确置换 p ≤ 0.1 才算有信号。
- 本模块管**两侧的对照关系**，用同一把尺子，但读的是**符号一致性**：

| train | eval | 判读 | 含义 |
|---|---|---|---|
| 涨且显著 | 涨且显著 | `generalizes` | 真的学到了泛化的东西 |
| 涨且显著 | 不显著 | `train_only` | **过拟合**：只在见过的题上变好 |
| 涨且显著 | **显著下降** | `harmful` | **负迁移**：学到的规矩在别处是错的 |
| 不显著 | 任意 | `no_train_signal` | 训练侧都没动，无从谈泛化 |

**「eval 不显著」不等于「eval 没变差」。** 这两种必须分开：`train_only` 说的是
「没有证据表明它变好」，`harmful` 说的是「有证据表明它变坏」。后者更严重，
报告里必须能一眼分开。

一条硬约束：**eval 侧显著下降时，无论 train 侧涨多少，结论都不能是「有信号」。**
这是本模块存在的全部理由——防止合并均值把方向相反的两种效应加成一个正数。
"""

from __future__ import annotations

from dataclasses import dataclass, field


#: 判定用的 p 阈值，与 `arms.compare_arms` 保持一致（不另造一把尺子）。
P_THRESHOLD = 0.1

#: 「显著下降」也算信号——判 Δ 的正负时用同一套显著性与容差。
_ZERO = 1e-9


@dataclass
class SideReading:
    """一侧（train 或 eval）的汇总读数。"""

    name: str
    n_tasks: int = 0
    #: 逐任务的 (task_id, delta_mean, p_value)。**保留逐条**，报告要能指到具体哪一格。
    rows: list[tuple[str, float, float]] = field(default_factory=list)

    @property
    def deltas(self) -> list[float]:
        return [d for _t, d, _p in self.rows]

    @property
    def mean_delta(self) -> float:
        ds = self.deltas
        return sum(ds) / len(ds) if ds else 0.0

    def significant_positive(self) -> list[str]:
        return [
            t for t, d, p in self.rows
            if d > _ZERO and p <= P_THRESHOLD
        ]

    def significant_negative(self) -> list[str]:
        return [
            t for t, d, p in self.rows
            if d < -_ZERO and p <= P_THRESHOLD
        ]

    def unchanged(self) -> list[str]:
        """既没显著涨也没显著跌——**不是「没变」**，是「这点 n 判不出来」。"""
        sp, sn = set(self.significant_positive()), set(self.significant_negative())
        return [t for t, _d, _p in self.rows if t not in sp and t not in sn]


def _side(comparisons: list[dict], task_ids: set[str], name: str) -> SideReading:
    side = SideReading(name=name)
    for r in comparisons:
        tid = r.get("task_id")
        if tid not in task_ids:
            continue
        # **没数据的格子不进统计**：`no_data` 是「判据没跑成」，不是「Δ=0」。
        # 把它当 0 会让「一条都没跑成」看起来像「两臂相同」。
        if r.get("no_data"):
            continue
        side.rows.append((tid, float(r.get("delta_mean") or 0.0), float(r.get("p_value") or 1.0)))
    side.n_tasks = len(side.rows)
    return side


def overfit_report(
    comparisons: list[dict],
    *,
    train_ids: set[str],
    test_ids: set[str],
) -> dict:
    """把逐任务比较按 sides 汇总，判出泛化 / 过拟合 / 负迁移。

    `comparisons` 是 `arms.compare_arms()` 的返回值列表（每格一个 dict）。
    两边的任务 id 集合由 `task_split` 给出——**这里不重新切分**，切分只在一个地方做。
    """
    tr = _side(comparisons, train_ids, "train")
    te = _side(comparisons, test_ids, "eval")

    tr_pos, tr_neg = tr.significant_positive(), tr.significant_negative()
    te_pos, te_neg = te.significant_positive(), te.significant_negative()

    if not tr.n_tasks and not te.n_tasks:
        verdict, why = "no_data", "两侧都没有有效样本（判据没跑成，不是「没提升」）"
    elif not tr.n_tasks:
        verdict, why = "no_data", "train 侧没有有效样本——无从判断学到了什么"
    elif not te.n_tasks:
        # **这一条是防呆**：只有 train 没有 eval 时，任何「有信号」都是过拟合的前兆，
        # 不能因为「没测 eval」就默认泛化了。
        verdict, why = "no_eval", "eval 侧没有有效样本——**不能声称泛化**，这只是 train 侧读数"
    elif te_neg:
        verdict = "harmful"
        why = (
            f"**负迁移**：eval 侧有 {len(te_neg)} 格显著下降（{', '.join(te_neg[:3])}）——"
            f"演化学到的东西在没见过的题上把分拉低了。"
            f"train 侧涨多少都不能抵消这一条。"
        )
    elif tr_pos and te_pos:
        verdict = "generalizes"
        why = (
            f"两侧都显著上涨（train {len(tr_pos)} 格、eval {len(te_pos)} 格）——"
            f"这是「学到了可迁移的东西」的形态。"
        )
    elif tr_pos and not te_pos:
        verdict = "train_only"
        why = (
            f"**过拟合**：train 侧 {len(tr_pos)} 格显著上涨，"
            f"但 eval 侧一格都没显著上涨（{len(te.unchanged())} 格判不出、"
            f"{len(te_neg)} 格下降）。"
            f"这正是「一些 case 很好、另一些没变好」的形态。"
        )
    elif tr_neg:
        verdict = "train_harmful"
        why = f"train 侧就有 {len(tr_neg)} 格显著下降——演化在训练题上都没帮上忙"
    else:
        verdict = "no_train_signal"
        why = "train 侧没有任何显著变化——这一轮无从谈泛化（不是「泛化失败」）"

    # **合并均值必须在这里算一次**，因为它是那个会骗人的数：报告要能让人看到
    # 「合并看是正的、拆开看是负的」这件事。
    pooled = sorted(tr.deltas + te.deltas)
    pooled_mean = sum(pooled) / len(pooled) if pooled else 0.0

    return {
        "verdict": verdict,
        "why": why,
        "train": {
            "n_tasks": tr.n_tasks,
            "mean_delta": round(tr.mean_delta, 4),
            "significant_positive": tr_pos,
            "significant_negative": tr_neg,
            "undecided": tr.unchanged(),
        },
        "eval": {
            "n_tasks": te.n_tasks,
            "mean_delta": round(te.mean_delta, 4),
            "significant_positive": te_pos,
            "significant_negative": te_neg,
            "undecided": te.unchanged(),
        },
        # 「合并均值」单独列出来，是因为它正是那个会掩盖过拟合的数。
        "pooled_mean_delta": round(pooled_mean, 4),
        "generalization_gap": round(tr.mean_delta - te.mean_delta, 4),
        "p_threshold": P_THRESHOLD,
    }


def format_report(rep: dict) -> str:
    """人读的短报告。**先给判决，再给两侧，最后给那个会骗人的合并均值。**"""
    lines = [f"泛化判决：{rep['verdict']}", f"  {rep['why']}", ""]
    for side in ("train", "eval"):
        s = rep[side]
        lines.append(
            f"  {side:<5} n={s['n_tasks']:<3} Δ均值={s['mean_delta']:+.4f}  "
            f"显著涨={len(s['significant_positive'])}  "
            f"显著跌={len(s['significant_negative'])}  "
            f"判不出={len(s['undecided'])}"
        )
        for tid in s["significant_positive"]:
            lines.append(f"      ↑ {tid}")
        for tid in s["significant_negative"]:
            lines.append(f"      ↓ {tid}")
    lines.append("")
    lines.append(
        f"  合并均值 Δ={rep['pooled_mean_delta']:+.4f}（**这个数会掩盖过拟合**："
        f"两侧拆开的差 = {rep['generalization_gap']:+.4f}）"
    )
    return "\n".join(lines)
