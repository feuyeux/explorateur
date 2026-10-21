#!/usr/bin/env python3
"""smoke_split.py —— 切分与泛化读数的门禁。

为什么单独一条
==============

`task_split.py` 与 `generalization.py` 是「能不能测出过拟合」的全部依赖：

- 切分错了（重叠 / 漏任务 / 未知 split 静默放行）⇒ **训练题与考题是同一批**，
  于是「泛化」这个词在报告里出现，而它量的仍是同一批题；
- 泛化判读错了（把「eval 没显著涨」说成「泛化」）⇒ 报告给出一个安慰性的结论。

这两类错误的共同点是**不会自己暴露**：读数看起来正常，只是悄悄失去了意义。
所以它们的门禁必须是**反向验证**——不是「跑一遍不崩」，而是「注入缺陷必须红」。

纪律（照抄仓库那三条）
======================

- 好数据放行是第一条断言：合法切分必须先证明全部通过；
- 加了新检查就要做反向验证：每种缺陷都要有一条断言因它而红；
- 判据不许依赖被测字段：断言只读「切分结果」与「判读结果」，不读内部实现。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parent / "theatre-ii")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bench_usine as B  # noqa: E402
import task_split as S  # noqa: E402
from generalization import overfit_report  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))


def info(label: str, detail: str = "") -> None:
    RESULTS.append((label, True, detail))


# ── [1] 切分本身 ──────────────────────────────────────────────────────────────
def section_split() -> None:
    data = S.make_split(B.TASKS)
    ids = {t.task_id for t in B.TASKS}
    tr, te = set(data["train"]), set(data["test"])

    check(
        "train ∪ test == 全部任务",
        (tr | te) == ids,
        f"缺 {sorted(ids - (tr | te))[:3]}",
    )
    check("train ∩ eval 不重叠", not (tr & te), f"重叠 {sorted(tr & te)[:3]}")
    check("两侧都非空", bool(tr) and bool(te), f"train {len(tr)} / eval {len(te)}")
    check(
        "每个任务恰好在一侧",
        len(tr) + len(te) == len(ids),
        f"{len(tr)}+{len(te)} vs {len(ids)}",
    )

    # 分层：每个可切的层，两侧都要有任务。切分不按层分的话，某一层会整个落进
    # train，eval 侧就少了一整类能力——量的不是泛化，是「少测了一层」。
    by_domain: dict[str, list[str]] = {}
    for t in B.TASKS:
        by_domain.setdefault(t.domain, []).append(t.task_id)
    unbalanced = [
        d for d, ts in by_domain.items()
        if len(ts) >= S.MIN_PER_DOMAIN and not (set(ts) & tr and set(ts) & te)
    ]
    check("每层两侧都有任务（分层切分）", not unbalanced, f"偏在一边：{unbalanced}")

    check(
        "未切分层为空（每层都够切）",
        not data["unsplit_domains"],
        f"未切：{data['unsplit_domains']}",
    )

    # 切分必须**可复现**：同一个种子两次结果一致。种子不稳的话，两次读数量的是
    # 不同题库，delta 里混着换题的效应。
    again = S.make_split(B.TASKS)
    check(
        "同种子切分可复现",
        again["train"] == data["train"] and again["test"] == data["test"],
    )

    # 指纹：任务集或切分一变，指纹必须变。
    d1 = S.split_digest(B.TASKS)
    d2 = S.split_digest(B.TASKS, split_data={**data, "test": data["test"][1:]})
    check("切分变了指纹就变", d1 != d2, f"{d1} vs {d2}")


# ── [2] select() 的防线 ───────────────────────────────────────────────────────
def section_select() -> None:
    ok_all = S.select(B.TASKS, "all")
    check("split=all 返回全部", set(ok_all) == {t.task_id for t in B.TASKS})
    check("split=train 是真子集", set(S.select(B.TASKS, "train")) < set(ok_all))
    check("split=test 是真子集", set(S.select(B.TASKS, "test")) < set(ok_all))

    data = S.make_split(B.TASKS)

    # 反向验证 A：train/test 重叠必须炸。
    bad = {**data, "test": data["test"] + data["train"][:2]}
    try:
        S.select(B.TASKS, "test", split_data=bad)
        check("重叠的切分被拒", False, "**静默通过**")
    except ValueError as exc:
        check("重叠的切分被拒", "重叠" in str(exc), str(exc)[:60])

    # 反向验证 B：切分里有不存在任务必须炸（任务集改了而切分没重生成）。
    bad = {**data, "test": data["test"] + ["no-such-task"]}
    try:
        S.select(B.TASKS, "test", split_data=bad)
        check("未知任务的切分被拒", False, "**静默通过**")
    except ValueError as exc:
        check("未知任务的切分被拒", "不存在" in str(exc), str(exc)[:60])

    # 反向验证 C：有任务哪边都没进必须炸（悄悄少跑几个是最危险的）。
    bad = {**data, "test": data["test"][1:]}
    try:
        S.select(B.TASKS, "test", split_data=bad)
        check("有任务没进任何一侧被拒", False, "**静默通过**")
    except ValueError as exc:
        check("有任务没进任何一侧被拒", "哪一边都没进" in str(exc), str(exc)[:60])

    # 反向验证 D：不认识的 split 名必须炸，不许静默当 all。
    try:
        S.select(B.TASKS, "eval")
        check("未知 split 名被拒", False, "**静默通过**（旧代码就认 'eval' 且忽略它）")
    except ValueError as exc:
        check("未知 split 名被拒", "未知 split" in str(exc), str(exc)[:60])


# ── [3] 泛化判读 ──────────────────────────────────────────────────────────────
def _c(tid: str, d: float, p: float, *, nodata: bool = False) -> dict:
    return {"task_id": tid, "delta_mean": d, "p_value": p, "no_data": nodata}


def section_generalization() -> None:
    TR, TE = {"t1", "t2"}, {"e1", "e2"}

    def verdict(comps: list[dict]) -> dict:
        return overfit_report(comps, train_ids=TR, test_ids=TE)

    good = verdict([
        _c("t1", 0.3, 0.05), _c("t2", 0.2, 0.08),
        _c("e1", 0.25, 0.05), _c("e2", 0.15, 0.09),
    ])
    check("两侧都涨 → generalizes", good["verdict"] == "generalizes", good["verdict"])

    # **这一条是这个文件存在的理由**：train 涨、eval 不动，必须判成过拟合，
    # 不能因为合并均值是正的就说「有提升」。
    overfit = verdict([
        _c("t1", 0.3, 0.05), _c("t2", 0.2, 0.08),
        _c("e1", 0.05, 0.6), _c("e2", 0.01, 0.9),
    ])
    check("train 涨 eval 不动 → train_only（过拟合）", overfit["verdict"] == "train_only", overfit["verdict"])
    check(
        "过拟合时合并均值是正的（正是它会骗人）",
        overfit["pooled_mean_delta"] > 0,
        f"pooled={overfit['pooled_mean_delta']:+.4f}",
    )

    # **负迁移**：eval 显著下降时，train 涨多少都不能抵消。
    harm = verdict([
        _c("t1", 0.3, 0.05), _c("t2", 0.2, 0.08),
        _c("e1", -0.3, 0.05), _c("e2", 0.0, 0.9),
    ])
    check("eval 显著下跌 → harmful（负迁移）", harm["verdict"] == "harmful", harm["verdict"])
    check(
        "负迁移时合并均值仍可能是正的（掩盖的实证）",
        harm["pooled_mean_delta"] > 0,
        f"pooled={harm['pooled_mean_delta']:+.4f}",
    )

    # **没有 eval 数据时不许说泛化**——这是最容易被糊过去的一格。
    no_eval = verdict([_c("t1", 0.3, 0.05), _c("e1", 0, 1, nodata=True), _c("e2", 0, 1, nodata=True)])
    check("没有 eval 样本 → no_eval（不许说泛化）", no_eval["verdict"] == "no_eval", no_eval["verdict"])

    # train 侧没信号时，不能得出任何关于泛化的结论。
    flat = verdict([_c("t1", 0.01, 0.9), _c("e1", 0.01, 0.9)])
    check("train 侧无信号 → no_train_signal", flat["verdict"] == "no_train_signal", flat["verdict"])

    both_empty = verdict([_c("e1", 0, 1, nodata=True)])
    check("两侧都空 → no_data", both_empty["verdict"] == "no_data", both_empty["verdict"])

    # **no_data 的格子不许当 0 进统计**：把它算成 Δ=0 会让「一条都没跑成」
    # 看起来像「两臂相同」。
    mixed = verdict([
        _c("t1", 0.3, 0.05), _c("t2", 0, 1, nodata=True),
        _c("e1", 0.2, 0.05), _c("e2", 0, 1, nodata=True),
    ])
    check(
        "no_data 的格子不进统计",
        mixed["train"]["n_tasks"] == 1 and mixed["eval"]["n_tasks"] == 1,
        f"train {mixed['train']['n_tasks']} / eval {mixed['eval']['n_tasks']}",
    )


# ── [4] 与报告接线 ────────────────────────────────────────────────────────────
def section_wiring() -> None:
    """报告层真的把两侧拆开读了吗——**走真实调用**，不是只看函数在不在。"""
    import arms

    check("arms 暴露 render_generalization", hasattr(arms, "render_generalization"))
    row = {
        "task_id": "routing-poster", "delta_mean": 0.3, "p_value": 0.05,
        "no_data": False, "same_surface": False, "significant": True,
        "base_scores": [0.6], "evolved_scores": [0.9], "base_mean": 0.6,
        "evolved_mean": 0.9, "base_spread": 0.0, "base_stdev": 0.0,
        "separation": 0.0, "reliable": True, "same_tree": False, "verdict": "x",
        "per_check": {}, "required_n_if_fixed": {}, "base_tag": "b",
        "evolved_tag": "e", "base_n": 1, "evolved_n": 1,
    }
    text = arms.render_generalization([row])
    check("泛化报告有切分指纹", "切分指纹" in text, text[:40].replace("\n", " "))
    check("泛化报告给出判决", "泛化判决" in text)
    check("泛化报告点出合并均值会掩盖", "掩盖" in text)
    # 报告必须用**真实切分**：任务不在 eval 侧时不许编一个 0 进来。
    check(
        "报告只认切分里真有的任务",
        "eval  n=0" in text,
        "routing-poster 在 train 侧，eval 侧应为 0 格",
    )


def main() -> int:
    for fn in (section_split, section_select, section_generalization, section_wiring):
        fn()

    n_pass = sum(1 for _l, ok, _d in RESULTS if ok)
    n_fail = len(RESULTS) - n_pass
    print("=" * 72)
    for label, ok, detail in RESULTS:
        mark = "ok  " if ok else "FAIL"
        line = f"  {mark} {label}"
        if detail and not ok:
            line += f"\n       {detail}"
        print(line)
    print(f"\n=== SMOKE split: {n_pass} PASS / {n_fail} FAIL / {len(RESULTS)} total")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
