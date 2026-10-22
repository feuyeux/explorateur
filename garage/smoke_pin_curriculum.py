#!/usr/bin/env python3
"""smoke_pin_curriculum.py —— 「钉住题目」这道接缝的门禁。

为什么单独一条
==============

`pin_curriculum.py` 存在的理由是让**两条臂拿到同一道题**。这件事一旦静默失败，
后果不是报错，而是**一个看起来很有说服力的错误结论**：

    2026-10-22 实测：两臂没钉题，有记忆臂抽到重的视频线（0 个项目）、
    无记忆臂抽到轻的包任务（3 个全 PASS）。一张成绩表摆出来就是「记忆有害」。
    真相是题不同。

所以门禁要盯的是**四种「静默失效」**：

1. 接缝漂移后 patch 变成 no-op —— 两臂又自由选题，而人以为钉住了；
2. 钉住的文件本身不合法（引擎解析器不接受）—— 跑到一半才炸；
3. 连 `SATURATED` / `STALLED` 也被盖掉 —— 把终止条件藏起来了；
4. `install()` 被调两次 —— 第二层 patch 让漂移检测失真。

第 3 条最隐蔽：`SATURATED` 是「题目池用完了」的信号，盖掉它会让一轮跑不完的
实验看起来像「还在正常出题」。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# `théâtre/` 在旁，引擎模块从那里 import。
_THEATRE = HERE.parent / "théâtre"
if str(_THEATRE) not in sys.path:
    sys.path.insert(0, str(_THEATRE))

from explore.phase1_wave import (  # noqa: E402
    PROJECT_ROOT,
    WaveDecision,
    WaveProject,
    parse_wave_handoff,
)

import pin_curriculum  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))


# **instruction 必须包含 PROJECT_ROOT**：引擎的解析器要它（`phase1_wave.py:140`），
# 因为项目题面必须指向那个工作仓库。写测试数据时漏了这条，会被解析器正确拒掉——
# 那不是解析器太严，是测试数据不合规。
DECISION = {
    "decision": "WAVE",
    "rationale": "钉住的两道题，用来做记忆对照",
    "projects": [
        {"id": "pin-a",
         "instruction": f"You are working in the repository at {PROJECT_ROOT} (a "
                        f"TypeScript pnpm monorepo). 把 foo 包里的 bar 改名并补测试"},
        {"id": "pin-b",
         "instruction": f"You are working in the repository at {PROJECT_ROOT} (a "
                        f"TypeScript pnpm monorepo). 给 baz 包加一个覆盖 80% 的回归测试"},
    ],
}


def write_json(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-pin-"))

    # ── [1] 合法文件能读进来，且字段不被改写 ────────────────────────────────
    good = write_json(tmp / "good.json", DECISION)
    pinned = pin_curriculum.load_pinned(good)
    check("合法文件能读", pinned["decision"] == "WAVE", str(pinned.get("decision")))
    check("项目数与 id 都对",
          [p["id"] for p in pinned["projects"]] == ["pin-a", "pin-b"],
          str([p["id"] for p in pinned["projects"]]))

    # **引擎自己的解析器必须也认得它**：这是「我不靠自己的判断」那条。
    engine_view = parse_wave_handoff(json.dumps(pinned, ensure_ascii=False))
    check(
        "钉住的文件过得了引擎解析器",
        engine_view is not None and len(engine_view.projects) == 2,
        "引擎解析器拒了它",
    )

    # **这一条专治「自己拼 dict 不调引擎解析器」**：
    # 造一份**JSON 语法正确、字段也齐、但只有引擎解析器会拒**的文件——
    # `instruction` 里不含 `PROJECT_ROOT`（`phase1_wave.py:140` 的硬条件）。
    # 若 `load_pinned` 绕过引擎解析器而自己判断，它会**通过**；
    # 只有真调了 `parse_wave_handoff()` 才会拒。
    sneaky = write_json(tmp / "no_root.json", {
        "decision": "WAVE",
        "rationale": "字段都齐，但 instruction 里没有 PROJECT_ROOT",
        "projects": [{"id": "pin-a", "instruction": "把 foo 包里的 bar 改名并补测试"}],
    })
    try:
        pin_curriculum.load_pinned(sneaky)
        check(
            "不含 PROJECT_ROOT 的 instruction 被拒（证明真调了引擎解析器）",
            False,
            "**通过了**——说明 load_pinned 没走引擎解析器，只是自己看字段齐不齐",
        )
    except RuntimeError as exc:
        check(
            "不含 PROJECT_ROOT 的 instruction 被拒（证明真调了引擎解析器）",
            "解析器" in str(exc),
            str(exc)[:80],
        )

    # ── [2] 不合法文件必须被拒，且说清是哪一种不合法 ────────────────────────
    for label, bad, needle in [
        ("空文件", write_json(tmp / "empty.json", {}), "解析器"),
        ("decision 拼错", write_json(tmp / "typo.json", {**DECISION, "decision": "WAWE"}),
         "解析器"),
        ("projects 为空", write_json(tmp / "noprog.json", {**DECISION, "projects": []}),
         "解析器"),
        ("rationale 空", write_json(tmp / "norat.json", {**DECISION, "rationale": "  "}),
         "解析器"),
    ]:
        try:
            pin_curriculum.load_pinned(bad)
            check(f"拒掉{label}", False, "**静默通过**")
        except RuntimeError as exc:
            check(f"拒掉{label}", needle in str(exc), str(exc)[:70])

    # ── [3] SATURATED / STALLED 不许被钉住的文件盖掉 ────────────────────────
    #
    # 这是最隐蔽的一条：SATURATED 是「题目池用完了」的终止信号。
    # 若允许钉住，实验会「继续出题」，而实际上池子已经空了。
    sat = write_json(tmp / "sat.json",
                     {"decision": "SATURATED", "rationale": "池子空了", "projects": []})
    try:
        pin_curriculum.load_pinned(sat)
        check("拒掉 SATURATED 文件", False, "**被接受了**——终止条件会被藏起来")
    except RuntimeError as exc:
        check("拒掉 SATURATED 文件", "只有 WAVE" in str(exc), str(exc)[:70])

    # ── [4] install 的行为：真跑一遍 patch ──────────────────────────────────
    import explore.phase1_wave as wave_mod

    stock_author = wave_mod._author_wave

    pin_curriculum.install(pinned)
    patched = wave_mod._author_wave
    check("装之后 _author_wave 换了", patched is not stock_author)

    # **真调一次**，看它把「自由选题」换成钉住的没有。
    # 注意 `pinned_author_wave` 闭包捕获的是**装的时候那个 stock**，所以这里不能
    # 靠替换 `wave_mod._author_wave` 来伪造输入——那改的是名字，不是闭包。
    # 改为直接验证：patch 调真引擎会真跑，所以只验它能正确**拒绝/放行**的静态面。
    check("describe 列出项目 id", "pin-a" in pin_curriculum.describe(pinned),
          pin_curriculum.describe(pinned))

    # ── [5] 重复 install 必须报错 ────────────────────────────────────────────
    try:
        pin_curriculum.install(pinned)
        check("重复 install 被拒", False, "**静默通过**——会套两层 patch，漂移检测失真")
    except RuntimeError as exc:
        check("重复 install 被拒", "两次" in str(exc), str(exc)[:60])

    # ── [6] 漂移检测：签名不符必须 raise，不是 no-op ────────────────────────
    #
    # 这一条用**另起一个进程**来测：`install()` 有全局单次守卫，同进程里没法
    # 再装一次。所以起子进程，那里先把 `_author_wave` 换成签名不对的假函数，
    # 再看 `install()` 是不是 raise 了。
    import subprocess

    drift_script = tmp / "drift.py"
    drift_script.write_text(
        "\n".join([
            "import sys",
            f"sys.path.insert(0, {str(HERE)!r})",
            f"sys.path.insert(0, {str(_THEATRE)!r})",
            "import explore.phase1_wave as w",
            "def broken(target_direction):",  # 少了一堆参数
            "    return None",
            "w._author_wave = broken",
            "import pin_curriculum",
            "try:",
            "    pin_curriculum.install({'decision':'WAVE','rationale':'x',"
            "'projects':[{'id':'a','instruction':'b'}]})",
            "    print('NO_RAISE')",
            "except RuntimeError as e:",
            "    print('RAISED:', '漂移' in str(e))",
        ]),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, str(drift_script)],
        capture_output=True, text=True, timeout=120,
    )
    check(
        "签名漂移时 install 会 raise（不是 no-op）",
        "RAISED: True" in out.stdout,
        f"stdout={out.stdout.strip()[:60]!r} stderr={out.stderr.strip()[-90:]!r}",
    )

    # ── [7] patch 真的把自由选题换掉了（行为断言，不只是「函数变了」）──────
    #
    # 同样起子进程：把 `_author_wave` 换成一个返回「自由选题」的假函数，
    # install() 之后调它，看返回 projects 是不是钉住的那两个。
    behav_script = tmp / "behav.py"
    behav_script.write_text(
        "\n".join([
            "import json, sys",
            f"sys.path.insert(0, {str(HERE)!r})",
            f"sys.path.insert(0, {str(_THEATRE)!r})",
            "import explore.phase1_wave as w",
            f"_INSTR = 'You are working in the repository at {PROJECT_ROOT} (a TS pnpm monorepo). 自由选题'",
            "def fake(hooks=None, vm=None, cfg=None, target_direction='',",
            "         previous_wave_outcomes='', history=None, sink_root=None,",
            "         target_query_conditioned=False):",
            "    free = w.WaveDecision(",
            "        decision='WAVE', rationale='我自己选的',",
            "        projects=(w.WaveProject('free-1', _INSTR),),",
            "        raw=json.dumps({'decision':'WAVE','rationale':'我自己选的',",
            "                        'projects':[{'id':'free-1','instruction':_INSTR}]}))",
            "    return free, []",
            "w._author_wave = fake",
            "import pin_curriculum",
            f"pinned = pin_curriculum.load_pinned(r'{good}')",
            "pin_curriculum.install(pinned)",
            "d, _ = w._author_wave()",
            "print('IDS:', [p.project_id for p in d.projects])",
            "print('DECISION:', d.decision)",
            # raw 必须能被引擎解析器吃回去 —— 否则落盘的 decision 文件是坏 JSON / 坏内容
            "print('RAW_OK:', json.loads(d.raw)['projects'][0]['id'])",
            # **落盘的 raw 也要过引擎解析器**：这是「写出去的能被读回来」那条
            "print('RAW_PARSES:', w.parse_wave_handoff(d.raw) is not None)",
        ]),
        encoding="utf-8",
    )
    out2 = subprocess.run(
        [sys.executable, str(behav_script)],
        capture_output=True, text=True, timeout=120,
    )
    check(
        "patch 把自由选题换成钉住的项目",
        "IDS: ['pin-a', 'pin-b']" in out2.stdout,
        f"stdout={out2.stdout.strip()[:120]!r} stderr={out2.stderr.strip()[-120:]!r}",
    )
    check(
        "被替换的决策仍是 WAVE",
        "DECISION: WAVE" in out2.stdout,
        out2.stdout.strip()[:80],
    )
    check(
        "替换后的 raw 是能被解析的 JSON（落盘不会坏）",
        "RAW_OK: pin-a" in out2.stdout,
        out2.stdout.strip()[:120],
    )
    check(
        "替换后的 raw 过得了引擎解析器（写出去的能被读回来）",
        "RAW_PARSES: True" in out2.stdout,
        out2.stdout.strip()[:120],
    )

    n_pass = sum(1 for _l, ok, _d in RESULTS if ok)
    n_fail = len(RESULTS) - n_pass
    print("=" * 72)
    for label, ok, detail in RESULTS:
        line = f"  {'ok  ' if ok else 'FAIL'} {label}"
        if detail and not ok:
            line += f"\n       {detail}"
        print(line)
    print(f"\n=== SMOKE pin-curriculum: {n_pass} PASS / {n_fail} FAIL / {len(RESULTS)} total")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
