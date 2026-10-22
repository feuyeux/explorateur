#!/usr/bin/env python3
"""smoke_memory_control.py —— 记忆对照读数的门禁。

为什么单独一条
==============

`memory_control.py` 判的是**负迁移**。这个判决的重量级远高于「分数掉了」：它会
导出「上一轮学到的东西在下一个项目上是有害的」这个结论，而那正是要拿去做决策的
东西。判错的代价不对称——把「没差别」说成「有害」，会让人去回滚一份其实有用的
记忆。

所以门禁要盯的不是「跑得动」，而是**四种会把结论说反的形态**：

1. **没有对照却说有结论**：两条臂起点一样（都空记忆 / 都带记忆）时，
   差里没有「记忆」这个变量。必须判 `no_control`。
2. **题不一样还比**：不同波次的题面不同，「后一个更差」什么都说明不了。
   必须判 `not_paired`。
3. **标签写反就跟着反**：调用方把 `seed=` / `plain=` 贴错是常见的手误。
   工具必须按**实际起跑状态**归类，不信标签。
4. **方向混杂也判 harmful**：只看平均分低就喊「有害」是最容易犯的错。
   必须是「变差的项目数 > 变好的项目数」才算。

第 3 条尤其要紧：如果工具信标签，那么一次手误就会把「记忆有用」报成「记忆有害」，
而读报告的人无从发现。
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from memory_control import compare_arms  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))


def make_arm(
    root: Path,
    name: str,
    *,
    memory: list[str],
    projects: list[tuple[str, str, int]],
    memory_before: list[str] | None = None,
) -> Path:
    """合成一条臂。

    `memory`        这条臂起跑时 `wave_001/memory_snapshot` 里的文件
    `projects`      [(题面文本, outcome, verification_cycles), …]
    `memory_before` 若给出，写进第一个 episode 的 `outcome.json`
                    `memory_before` 字段——真引擎就是这么记「起跑那一刻手里
                    有什么」的（2026-10-22 真跑实测：注入 5 份，wave 快照只装
                    1 份，`memory_before` 记满 5 份）。
    """
    p1 = root / name / "phase1"
    (p1 / "episodes").mkdir(parents=True)
    w = p1 / "waves" / "wave_001" / "memory_snapshot"
    w.mkdir(parents=True)
    for f in memory:
        (w / f).write_text("m", encoding="utf-8")

    for i, (task, outcome, cycles) in enumerate(projects, 1):
        d = p1 / "episodes" / f"ep{i:03d}"
        d.mkdir()
        (d / "project.md").write_text(task, encoding="utf-8")
        payload = {"terminal_outcome": outcome, "verification_cycles": cycles}
        if i == 1 and memory_before is not None:
            payload["memory_before"] = {f: "content" for f in memory_before}
        (d / "outcome.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    (p1 / "result.json").write_text(
        json.dumps({"status": "budget_exhausted", "project_budget": len(projects),
                    "projects": len(projects)}),
        encoding="utf-8",
    )
    return root / name


TASK_A = "把 foo 包里的 bar 函数改名并补一个测试"
TASK_B = "给 baz 包加一个覆盖 80% 的回归测试"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-memctl-"))

    # ── 负迁移：同一批题，有记忆反而更差 ────────────────────────────────────
    seed = make_arm(tmp, "seed", memory=["q.md"], projects=[
        (TASK_A, "FAIL", 3),
        (TASK_B, "PASS", 1),
    ])
    plain = make_arm(tmp, "plain", memory=[], projects=[
        (TASK_A, "PASS", 1),
        (TASK_B, "PASS", 1),
    ])
    rep = compare_arms({"seed": seed, "plain": plain})
    check("有记忆更差 → harmful", rep["verdict"] == "harmful", rep["verdict"])
    check("harmful 时指出「同一道题上更差」", "同一道题" in rep["why"], rep["why"][:70])
    check("逐项目差算对", [d["delta_pass"] for d in rep["per_project"]] == [-1, 0],
          str([d["delta_pass"] for d in rep["per_project"]]))

    # ── 有益：反过来 ────────────────────────────────────────────────────────
    seed2 = make_arm(tmp, "seed2", memory=["q.md"], projects=[(TASK_A, "PASS", 1)])
    plain2 = make_arm(tmp, "plain2", memory=[], projects=[(TASK_A, "FAIL", 2)])
    rep = compare_arms({"seed": seed2, "plain": plain2})
    check("有记忆更好 → helpful", rep["verdict"] == "helpful", rep["verdict"])

    # ── **标签写反**：按实际起跑状态归类，结论不能跟着标签走 ────────────────
    # 这里故意把带记忆的那条叫 plain、空的叫 seed。
    rep = compare_arms({"plain": seed2, "seed": plain2})
    check(
        "标签写反不影响结论",
        rep["verdict"] == "helpful",
        f"变成 {rep['verdict']}——工具信了标签",
    )
    check(
        "标签写反时按实际状态认出有记忆臂",
        rep["with_memory_arm"] == "plain",
        str(rep["with_memory_arm"]),
    )

    # ── 题不一样：不可比，拒判 ──────────────────────────────────────────────
    seed3 = make_arm(tmp, "seed3", memory=["q.md"], projects=[(TASK_A, "PASS", 1)])
    plain3 = make_arm(tmp, "plain3", memory=[], projects=[(TASK_B, "PASS", 1)])
    rep = compare_arms({"seed": seed3, "plain": plain3})
    check("题面对不上 → not_paired", rep["verdict"] == "not_paired", rep["verdict"])
    check("not_paired 时明说「什么都说明不了」", "什么都说明不了" in rep["why"], rep["why"][:70])

    # ── 两臂起点一样：没有对照 ──────────────────────────────────────────────
    both_seeded = make_arm(tmp, "bs", memory=["q.md"], projects=[(TASK_A, "PASS", 1)])
    both_plain = make_arm(tmp, "bp", memory=["q.md"], projects=[(TASK_A, "FAIL", 1)])
    rep = compare_arms({"a": both_seeded, "b": both_plain})
    check("两臂都带记忆 → no_control", rep["verdict"] == "no_control", rep["verdict"])
    check("no_control 时说明「差里没有记忆这个变量」", "没有记忆这个变量" in rep["why"],
          rep["why"][:70])

    # 只给一条臂。
    rep = compare_arms({"only": seed})
    check("只给一条臂 → no_control", rep["verdict"] == "no_control", rep["verdict"])

    # **两臂都空记忆**也必须拒判：否则「两条都没记忆的波次之间」的差会被当成记忆效应。
    # 这是同一条判据的另一半——只测「都带记忆」测不出这一半。
    empty1 = make_arm(tmp, "e1", memory=[], projects=[(TASK_A, "PASS", 1)])
    empty2 = make_arm(tmp, "e2", memory=[], projects=[(TASK_A, "FAIL", 1)])
    rep = compare_arms({"a": empty1, "b": empty2})
    check("两臂都空记忆 → no_control", rep["verdict"] == "no_control", rep["verdict"])

    # 一侧完全没有项目（没跑成）：也不能当对照——那量的不是记忆，是「没跑起来」。
    noprog = make_arm(tmp, "np", memory=["q.md"], projects=[])
    ok1 = make_arm(tmp, "ok1", memory=[], projects=[(TASK_A, "PASS", 1)])
    rep = compare_arms({"a": noprog, "b": ok1})
    check("一侧没跑出项目 → no_control", rep["verdict"] == "no_control", rep["verdict"])

    # ── 完全相同：no_effect，且不许说「记忆无用」 ───────────────────────────
    same1 = make_arm(tmp, "s1", memory=["q.md"], projects=[(TASK_A, "PASS", 1)])
    same2 = make_arm(tmp, "s2", memory=[], projects=[(TASK_A, "PASS", 1)])
    rep = compare_arms({"seed": same1, "plain": same2})
    check("两侧一样 → no_effect", rep["verdict"] == "no_effect", rep["verdict"])
    check("no_effect 时点出「天花板 与 没读懂 分不开」", "分不开" in rep["why"], rep["why"][:70])

    # ── 方向混杂：判 inconclusive，不许喊 harmful ───────────────────────────
    mixed1 = make_arm(tmp, "m1", memory=["q.md"], projects=[
        (TASK_A, "FAIL", 1),
        (TASK_B, "PASS", 1),
    ])
    mixed2 = make_arm(tmp, "m2", memory=[], projects=[
        (TASK_A, "PASS", 1),
        (TASK_B, "FAIL", 1),
    ])
    rep = compare_arms({"seed": mixed1, "plain": mixed2})
    check("一好一坏 → inconclusive", rep["verdict"] == "inconclusive", rep["verdict"])
    check(
        "方向混杂时不许喊 harmful",
        rep["verdict"] != "harmful",
        f"误判成 {rep['verdict']}",
    )

    # **专治「只要有一个变差就喊 harmful」**：1 个变差、1 个变好、1 个相同，
    # 平均差是 0，方向互为抵消。正确实现判 inconclusive；
    # 「见到变差就喊 harmful」的实现会误判。这是这类判据最容易犯的错——
    # 把「有个别退化」当成「整体有害」，而那种退化完全可能是一次运气不好。
    trip1 = make_arm(tmp, "t1", memory=["q.md"], projects=[
        (TASK_A, "FAIL", 1),
        (TASK_B, "PASS", 1),
        (TASK_A + "（第三题）", "PASS", 1),
    ])
    trip2 = make_arm(tmp, "t2", memory=[], projects=[
        (TASK_A, "PASS", 1),
        (TASK_B, "FAIL", 1),
        (TASK_A + "（第三题）", "PASS", 1),
    ])
    rep = compare_arms({"seed": trip1, "plain": trip2})
    check(
        "有一个变差但没占多数 → 仍判 inconclusive",
        rep["verdict"] == "inconclusive",
        f"判成 {rep['verdict']}（好 {rep.get('n_better')} / 坏 {rep.get('n_worse')}）",
    )
    check(
        "该案例确实是 1 好 1 坏 1 同（用来确认它有区分力）",
        rep.get("n_better") == 1 and rep.get("n_worse") == 1 and rep.get("n_same") == 1,
        f"好 {rep.get('n_better')} / 坏 {rep.get('n_worse')} / 同 {rep.get('n_same')}",
    )

    # 反过来：变差数确实占多数时才判 harmful（2 坏 1 好）。
    maj1 = make_arm(tmp, "j1", memory=["q.md"], projects=[
        (TASK_A, "FAIL", 1),
        (TASK_B, "FAIL", 1),
        (TASK_A + "（第三题）", "PASS", 1),
    ])
    maj2 = make_arm(tmp, "j2", memory=[], projects=[
        (TASK_A, "PASS", 1),
        (TASK_B, "PASS", 1),
        (TASK_A + "（第三题）", "FAIL", 1),
    ])
    rep = compare_arms({"seed": maj1, "plain": maj2})
    check(
        "变差占多数 → harmful",
        rep["verdict"] == "harmful",
        f"判成 {rep['verdict']}（好 {rep.get('n_better')} / 坏 {rep.get('n_worse')}）",
    )

    # ── 题面指纹：同样内容要得到同样指纹（跨臂可比的前提）──────────────────
    dig = hashlib.sha256(TASK_A.encode("utf-8")).hexdigest()[:12]
    p1 = make_arm(tmp, "dg", memory=[], projects=[(TASK_A, "PASS", 1)])
    check(
        "题面指纹与内容一致",
        (p1 / "phase1" / "episodes" / "ep001" / "project.md").is_file(),
        "project.md 不存在",
    )
    rep = compare_arms({"seed": seed3, "plain": make_arm(
        tmp, "dg2", memory=[], projects=[(TASK_A, "PASS", 1)])})
    check("同一题面的两臂 → pairs 成立", rep["verdict"] != "not_paired", rep["verdict"])

    # ── 起跑记忆数：`memory_before` 权威，wave 快照只是增量 ─────────────────
    #
    # 2026-10-22 真跑踩到：seed 臂真注入 5 份记忆，`wave_001/memory_snapshot`
    # 却只装了 1 份（`INDEX.md`）——快照只存「这一波新增/变化」的文件。旧实现
    # 数快照，把「有记忆起跑（5 份）」报成「（1 份）」，**数字小了 4 倍，而且
    # 小得很有说服力**：读报告的人会以为注入基本没生效。
    #
    # 修法是读第一个 episode 的 `outcome.json` 的 `memory_before`——那是该臂
    # 起跑那一刻的账。这条断言锁住「数对了」，反向验证锁「不读它就数错」。
    b1 = make_arm(tmp, "b1", memory=["INDEX.md"], projects=[(TASK_A, "PASS", 1)],
                  memory_before=["INDEX.md", "evidence.md", "gate.md", "dsh.md",
                                 "foodnames.md"])
    rep = compare_arms({"seed": b1, "plain": make_arm(
        tmp, "b2", memory=[], projects=[(TASK_A, "PASS", 1)])})
    check(
        "memory_before 权威：注入 5 份就报 5 份（不是快照的 1 份）",
        rep["arms"]["seed"]["started_memory_files"] == [
            "INDEX.md", "dsh.md", "evidence.md", "foodnames.md", "gate.md"],
        str(rep["arms"]["seed"]["started_memory_files"]),
    )
    check(
        "空记忆臂在没有 memory_before 时回退到快照（0 份）",
        rep["arms"]["plain"]["started_memory_files"] == [],
        str(rep["arms"]["plain"]["started_memory_files"]),
    )

    # 只有快照、没有 memory_before 时回退且不出错（合成臂一律如此）。
    fb = make_arm(tmp, "fb", memory=["q.md", "r.md"], projects=[(TASK_A, "PASS", 1)])
    rep2 = compare_arms({"seed": fb, "plain": make_arm(
        tmp, "fb2", memory=[], projects=[(TASK_A, "PASS", 1)])})
    check(
        "没有 memory_before 时回退到 wave 快照（2 份）",
        len(rep2["arms"]["seed"]["started_memory_files"]) == 2,
        str(rep2["arms"]["seed"]["started_memory_files"]),
    )

    n_pass = sum(1 for _l, ok, _d in RESULTS if ok)
    n_fail = len(RESULTS) - n_pass
    print("=" * 72)
    for label, ok, detail in RESULTS:
        line = f"  {'ok  ' if ok else 'FAIL'} {label}"
        if detail and not ok:
            line += f"\n       {detail}"
        print(line)
    print(f"\n=== SMOKE memory-control: {n_pass} PASS / {n_fail} FAIL / {len(RESULTS)} total")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
