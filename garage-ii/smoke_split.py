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

    # 未切分层（任务数 < MIN_PER_DOMAIN 的层）按设计整层归 train——这是
    # `task_split` 自己的规矩（切了每边剩 1 个，噪声大于信号）。2026-10-21 起
    # 任务集里有 `foodnames` 这种 1 题的夹具层，所以「未切分层为空」不再是
    # 任务集的性质；**读数侧真正要的硬性质**是：未切分层的任务一个都不许
    # 出现在 eval 侧——eval 侧出现没有 train/eval 对照的层，那一格的
    # 「泛化」读数就是编的。
    unsplit = data["unsplit_domains"]
    leaked = sorted({
        t.task_id for t in B.TASKS
        if t.domain in unsplit and t.task_id in te
    })
    check(
        "未切分层整层归 train（eval 侧不得出现未切分层的任务）",
        not leaked,
        f"eval 侧混进了未切分层：{leaked}（未切分层：{unsplit}）",
    )
    info(
        "未切分层（整层 train，不参与泛化对照）",
        f"{unsplit or '无'}",
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
def _c(tid: str, d: float, p: float, *, nodata: bool = False, k: int = 4) -> dict:
    """一条逐格比较。

    `k` 默认 4：这些用例测的是**判决逻辑**（train_only / harmful / generalizes），
    前提是样本量够判——功效不足会先被 `underpowered` 截走，把判决逻辑挡在后面。
    k=4 时完全分离的最小 p≈0.014，够用。要测功效本身另有专门用例（见下）。
    """
    return {"task_id": tid, "delta_mean": d, "p_value": p, "no_data": nodata,
            "n_rollouts": k}


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

    # ── 判别能力：k=1 时不许把「测不出」说成「没差别」──────────────────────
    #
    # 2026-10-22 实测踩到的：`--k` 默认 1，每臂每格只有 1 次 rollout。置换检验在
    # 完全分离时最小 p = 1/C(2,1) = 0.5，**永远越不过 p ≤ 0.1**。此时若判
    # `no_train_signal`，读报告的人会以为「演化确实没用」，而真相是「这次跑法在
    # 数学上没有判别能力」。这两句的差别是「没效果」与「没测出来」。
    flat_k1 = verdict([
        _c("t1", 0.0, 1.0, k=1), _c("t2", 0.0, 1.0, k=1),
        _c("e1", 0.0, 1.0, k=1), _c("e2", 0.0, 1.0, k=1),
    ])
    check(
        "k=1 且无显著变化 → underpowered（不是 no_train_signal）",
        flat_k1["verdict"] == "underpowered",
        f"判成 {flat_k1['verdict']}——把「没能力判」说成了「没差别」",
    )
    check(
        "underpowered 说明最小 p 与门槛",
        "0.5" in flat_k1["why"] and "0.1" in flat_k1["why"],
        flat_k1["why"][:80],
    )
    check(
        "underpowered 给出修法（k≥3）",
        "k≥3" in flat_k1["why"],
        flat_k1["why"][:80],
    )
    check(
        "报告里带 power 字段",
        flat_k1.get("power", {}).get("k") == 1
        and flat_k1["power"]["adequate"] is False,
        str(flat_k1.get("power")),
    )

    # k=3 时最小 p=0.05，够判；同样的数据就该给出 no_train_signal。
    flat_k3 = verdict([
        _c("t1", 0.0, 1.0, k=3), _c("t2", 0.0, 1.0, k=3),
        _c("e1", 0.0, 1.0, k=3), _c("e2", 0.0, 1.0, k=3),
    ])
    check(
        "k=3 且无显著变化 → no_train_signal（有能力判，确实没差别）",
        flat_k3["verdict"] == "no_train_signal",
        f"判成 {flat_k3['verdict']}",
    )
    check(
        "k=3 时 power.adequate 为真",
        flat_k3.get("power", {}).get("adequate") is True,
        str(flat_k3.get("power")),
    )

    # **缺 n_rollouts 时按 k=1 保守处理**：宁可说「判不出」，也不要假装判得出。
    no_k = verdict([{"task_id": "t1", "delta_mean": 0.0, "p_value": 1.0},
                    {"task_id": "e1", "delta_mean": 0.0, "p_value": 1.0}])
    check(
        "缺 n_rollouts → 按 k=1 保守判 underpowered",
        no_k["verdict"] == "underpowered",
        f"判成 {no_k['verdict']}",
    )

    # 功效不足**不覆盖**已有显著证据：真涨了就该说涨了，别说「判不出」。
    strong_k1 = verdict([_c("t1", 0.5, 0.05, k=1), _c("e1", 0.5, 0.05, k=1)])
    check(
        "显著证据优先于功效不足",
        strong_k1["verdict"] == "generalizes",
        f"判成 {strong_k1['verdict']}——功效闸把真信号吞了",
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


# ── [5] 两段式的命名空间与回退闸 ──────────────────────────────────────────────
def section_stage_ns() -> None:
    """`--split both` 的两侧必须各落各的目录，且回退闸找得到那些目录。

    2026-10-21 实测的缺陷形态：`_sweep_one` 硬写 `tag=""`，train 段与 eval 段
    共写 `adapt/<ns>/`；而 `_report_stage_fallbacks` 拿 `-train` / `-eval`
    后缀的目录名去找——**永远找不到**，且它对不存在的目录恒空返回、不报错。
    于是「阶段回退必须说出口」那条硬规则在两段式下**静默失效**（§12.2 的假绿）。
    修法是把 tag 与目录名收敛到 `_stage_tag` 一个派生点；这里反向验证那一格。
    """
    import json
    import tempfile

    import run_usine_h2 as RUN

    check("stage_tag: all → 空后缀（与旧读数兼容）", RUN._stage_tag("all") == "")
    check("stage_tag: train → train", RUN._stage_tag("train") == "train")
    check("stage_tag: test → eval（读数侧的词）", RUN._stage_tag("test") == "eval")
    try:
        RUN._stage_tag("both")
        check("stage_tag: both 不认（只在段循环里展开）", False, "**静默通过**")
    except ValueError:
        check("stage_tag: both 不认（只在段循环里展开）", True)

    # judge / report 看的侧，必须与 sweep 落盘的目录**同一个派生点**。
    class _A:
        spec = type("S", (), {"name": "usine-dsh"})()
        substrate = type("T", (), {"name": "dsh"})()

    class _Args:
        k = 1
        seed = None
        split = "both"

    sides = RUN._stage_sides(_A(), _Args())
    check(
        "both → 两侧分开（train 与 eval 两个命名空间）",
        [s[1] for s in sides] == ["train", "eval"] and len({s[0] for s in sides}) == 2,
        str(sides),
    )
    _Args.split = "train"
    check(
        "train → 单侧带 -train 后缀",
        RUN._stage_sides(_A(), _Args())[0][0].endswith("-train"),
    )
    _Args.split = "all"
    check(
        "all → 不带后缀",
        not RUN._stage_sides(_A(), _Args())[0][0].endswith("-"),
    )

    # 反向验证：带后缀的目录里真有阶段回退时，闸必须抓得到。
    root = Path(tempfile.mkdtemp(prefix="smoke-split-gate-"))
    ns = "usine-dsh-dsh-agg1-eval"
    d = root / "adapt" / ns / "verify-honesty"
    d.mkdir(parents=True)
    (d / "summary.json").write_text(
        json.dumps({
            "modes": {"agg": {"stages": [
                {"label": "compose", "fell_back": True, "error": "401"},
            ]}},
            "selections": {"agg": {"chosen_tree_is_base": True}},
        }),
        encoding="utf-8",
    )
    fell = RUN._report_stage_fallbacks(root, ns)
    check(
        "回退闸在带后缀目录上抓得到回退",
        bool(fell),
        f"抓到 {fell}——缺陷形态正是「拿后缀目录名去找，恒空返回」",
    )
    # 这条不是「好行为」的断言，是把闸的静默面**写进读数**：它对不存在的目录
    # 永远返回空。凡是给它传目录名的地方，都必须传 sweep 真落盘的那个。
    check(
        "回退闸对不存在的目录恒空（静默面：传错目录名 = 闸死）",
        RUN._report_stage_fallbacks(root, "no-such-ns") == [],
    )


def main() -> int:
    for fn in (section_split, section_select, section_generalization, section_wiring, section_stage_ns):
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
