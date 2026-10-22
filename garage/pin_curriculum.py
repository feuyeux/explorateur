"""把波次的题目钉死：`pin_curriculum.py`。

为什么必须有这个东西
====================

A 线想做「记忆有没有害」的对照，就得比**同一道题**在有记忆 / 无记忆下的表现。
2026-10-22 真跑了两臂，结果做不成对照：

    有记忆臂：抽到 food names 十二语种视频线（要碰渲染，重）→ 950s 上限里 0 个项目
    无记忆臂：抽到常规包任务（轻）→ 1578s 做完 3 个全 PASS

只看成绩表（0 个项目 vs 3 个全 PASS）很容易写成「记忆有害，这是负迁移」。真相是
**两臂抽到的题不一样**，`memory_control.py` 判 `not_paired` 正是为了挡住这一句。

根因在引擎：Curriculum 从 `TARGET MENU` 自由选题（`curriculum-usine.yaml`），
没有确定性开关，`--memory-seed` 也不参与出题。`phase1_wave.py:670` 调
`_author_wave()` 拿决策、`:676` 写盘——**中间没有「读入既定决策」的入口**。

它怎么工作
==========

`théâtre/` 是 vendored fork，补丁必须逐字节不变（PROVENANCE 纪律），所以不在
引擎里开洞，而是在 `garage/` 这一层 **wrap** `_author_wave`：

    第一次跑（不 pin）：把 wave_001 的 curriculum_decision.json 存下来
    第二次跑（--pin-projects <那份 json>）：Curriculum 的决策被替换成它

替换**不是伪造**：`raw` 字段仍然走引擎自己的 `parse_wave_handoff()` 解析路径，
所以校验逻辑一条没绕过（`decision == WAVE`、projects 非空、字段齐全）。被换掉的
只有「抽哪道题」这一个自由度——那正是要控制的变量。

fail-closed 的三条
==================

1. **接缝漂移就报错，不静默降级**：`_author_wave` 的签名或 `WaveDecision` 的字段
   变了，这里 raise，而不是让 patch 变成 no-op（那样两臂又会抽到不同的题，而人
   以为已经钉住了）。
2. **钉住的文件必须能被引擎自己的解析器接受**：用 `parse_wave_handoff()` 验一遍，
   不过就 raise——不能靠「我拼的 dict 应该对」。
3. **只替换 `WAVE` 决策**：若引擎算出 `SATURATED` / `STALLED`，那是「题目池用完了」
   或「卡住了」的信号，**不许**被钉住的文件盖掉——那不是选题自由度，那是终止条件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 已经装过的标记：重复安装会套两层 patch，第二层拿到的 `stock` 是第一层的产物，
# 于是「接缝漂移检测」比的是打过补丁的字符串——那条检查就失真了。
_INSTALLED = False


def load_pinned(path: Path) -> dict[str, Any]:
    """读入要钉住的 curriculum 决策，并**用引擎自己的解析器验一遍**。

    直接 `json.loads` 之后不验就塞进 `WaveDecision` 是危险的：引擎的
    `parse_wave_handoff()` 有一整套字段约束（`decision` 三选一、`rationale`
    非空、`projects` 是 list、`WAVE` 时非空）。绕过它等于绕过校验。
    """
    from explore.phase1_wave import parse_wave_handoff

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"--pin-projects 读不了 {path}: {exc}") from exc

    decision = parse_wave_handoff(text)
    if decision is None:
        raise RuntimeError(
            f"--pin-projects 的文件过不了引擎自己的解析器：{path}。"
            f"它必须是一份 curriculum_decision.json（含 decision/rationale/projects）")
    if decision.decision != "WAVE":
        raise RuntimeError(
            f"--pin-projects 钉住的是 {decision.decision}，只有 WAVE 能被钉。"
            f"SATURATED / STALLED 是「题目池用完了 / 卡住了」，盖掉它等于藏起终止条件")
    if not decision.projects:
        raise RuntimeError(f"--pin-projects 的文件里一个项目都没有：{path}")
    return {
        "decision": decision.decision,
        "rationale": decision.rationale,
        "projects": [
            {"id": p.project_id, "instruction": p.instruction}
            for p in decision.projects
        ],
    }


def install(pinned: dict[str, Any]) -> None:
    """wrap `explore.phase1_wave._author_wave`，让每一波都用钉住的项目。"""
    global _INSTALLED
    if _INSTALLED:
        raise RuntimeError("pin_curriculum.install() 被调了两次")

    import explore.phase1_wave as wave_mod

    stock = wave_mod._author_wave

    # ── 接缝漂移检测：签名一变就停，别让 patch 变成静默 no-op ──────────────
    expected_params = {
        "hooks", "vm", "cfg", "target_direction", "previous_wave_outcomes",
        "history", "sink_root", "target_query_conditioned",
    }
    import inspect

    actual = set(inspect.signature(stock).parameters)
    missing = expected_params - actual
    if missing:
        raise RuntimeError(
            f"pin_curriculum 接缝漂移：_author_wave 少了参数 {sorted(missing)}。"
            f"现在它是 {sorted(actual)}")
    if not hasattr(wave_mod, "WaveDecision") or not hasattr(wave_mod, "WaveProject"):
        raise RuntimeError("pin_curriculum 接缝漂移：WaveDecision / WaveProject 不见了")

    def pinned_author_wave(**kwargs: Any):
        decision, history = stock(**kwargs)
        # **只替换 WAVE**：SATURATED / STALLED 是终止信号，不是选题自由度。
        if decision.decision != "WAVE":
            return decision, history
        raw = json.dumps(pinned, ensure_ascii=False)
        replaced = wave_mod.WaveDecision(
            decision="WAVE",
            rationale=(
                f"[pinned] {pinned['rationale']}"
            ),
            projects=tuple(
                wave_mod.WaveProject(project_id=p["id"], instruction=p["instruction"])
                for p in pinned["projects"]
            ),
            raw=raw,
        )
        return replaced, history

    wave_mod._author_wave = pinned_author_wave
    _INSTALLED = True


def describe(pinned: dict[str, Any]) -> str:
    """人读的一行摘要，写进日志让「这次是被钉住的」有据可查。"""
    ids = ", ".join(p["id"] for p in pinned["projects"])
    return f"题目已钉住（{len(pinned['projects'])} 个）：{ids}"
