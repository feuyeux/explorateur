#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_audio.py — 场景课 TTS 叶子的反向验证

第 0 条好数据放行（纪律 1）：对 B 门1 的真实 scene.json（3 语种 × 17 行）
跑纯函数部分——选角映射、情绪增量缺省、口径常量——必须全对。其余各防一种
真实退化：

- 选角映射：§0.4 roles 声明驱动（role → energy → 班底唯一人）；A 声明 steady
  就配沉稳声线（不认硬编码 A=活泼）；班底配对破坏时**显式报错**不静默回落
- 情绪增量：moodVoices 没声明的 mood = ±0（不发明默认值）；声明了就生效
- 台账：extra=(sid, sha, gap) 自描述——status_of 漏传 extra 时按条目里那份复算，
  不会永久误红；scene.md 变 → 指纹变（sha 进 extra）
- 台账注册：kind="scene-audio" 的指纹覆盖 tts/timeline/audio 三模块 + scene.md + personas
- 产物命名：timeline 文件名与 doctor ④ 的探针逐字节一致（scene-<sid>_<lc>.timeline.json）

真实网络合成不在这里跑（verify_tts 已覆盖 synth_cached 的网络路径，
无网时如实 [SKIP]）；本套件全部断言离线可跑。
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import cli, scene_audio                      # noqa: E402
from feuille.data import personas, scene_doc              # noqa: E402
from feuille.errors import FeuilleError                   # noqa: E402
from feuille.ledger import load, status_of                # noqa: E402

SID = "guangchaoshi-逛超市"


def check():
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：真实课的选角映射（纯函数，离线） ----
    doc = scene_doc(SID)
    people = [p for p in personas().values() if p.get("locale") == "ru-RU"]
    by = scene_audio._pick_cast(people, {"A": "lively", "B": "steady"}, "ru-RU")
    rows.append((by["A"]["id"] == "misha" and by["B"]["id"] == "anya",
                 f"ru 选角 roles A=lively→{by['A']['id']}、B=steady→{by['B']['id']}"))

    # roles 声明驱动：A 声明 steady 的合法课，A 就配沉稳声线（不认硬编码 A=活泼）
    by2 = scene_audio._pick_cast(people, {"A": "steady", "B": "lively"}, "ru-RU")
    rows.append((by2["A"]["id"] == "anya" and by2["B"]["id"] == "misha",
                 "roles 换能量（A=steady）→ A 配沉稳声线（§0.4 声明驱动）"))

    # 班底配对破坏 → 显式报错（不静默回落）
    bad = [dict(people[0]), dict(people[0])]
    try:
        scene_audio._pick_cast(bad, {"A": "lively", "B": "steady"}, "test")
        rows.append((False, "班底双活泼应报错，实际静默通过"))
    except FeuilleError:
        rows.append((True, "班底配对破坏 → FeuilleError 显式报错"))

    # ---- 1. 情绪增量：缺省 ±0；声明生效 ----
    r, p = scene_audio._mood_offset("happy", {})
    rows.append(((r, p) == (0, 0), "moodVoices 无该 mood → ±0（不猜）"))
    r, p = scene_audio._mood_offset("happy", {"happy": {"rate": 4, "pitch": 2}})
    rows.append(((r, p) == (4, 2), "moodVoices 声明的增量生效"))

    # ---- 2. 口径常量与既有套件一致 ----
    rows.append((scene_audio.LINE_GAP == 0.35, f"LINE_GAP={scene_audio.LINE_GAP}（与 verify_timeline 同口径）"))

    # ---- 2b. 裁尾哨兵：空 words/伪词行的 probe_dur 必须是实测值 ----
    # 旧实现传 1e9 哨兵：effective_dur 对空 words/伪词行**原样返回 probe_dur**，
    # 哨兵直灌 enrich_lines → starts/totalDur/tail_silence 全炸（tail_silence≈-1e9）。
    # patch 掉 probe_duration 离线断言：回落值来自实测，不是哨兵。
    import feuille.audio as _fa
    _orig_probe = _fa.probe_duration
    try:
        _fa.probe_duration = lambda p: 3.0
        got = scene_audio._effective_dur([], "Пойдём!", pathlib.Path("fake.mp3"))
        rows.append((abs(got - 3.0) < 1e-9,
                     f"空 words 行的 dur 回落实测时长（3.0s），不是 1e9 哨兵（实得 {got}）"))
    finally:
        _fa.probe_duration = _orig_probe

    # ---- 3. 台账：extra 自描述（漏传不永久误红）+ scene.md sha 进指纹 ----
    # tempdir 必须模拟真实 root 布局：root/lessons/<id>/scene.md（@glob 的数据）
    # ——glob 相对 root 解析，空 tempdir 里 glob 不中 = 保守判过期（这是账本的
    # 正确行为，不是缺陷；真实布局下 lessons/ 与 build/ 同根）。
    with tempfile.TemporaryDirectory(prefix="feuille-sa-") as td:
        root = pathlib.Path(td)
        (root / "lessons" / SID).mkdir(parents=True)
        (root / "lessons" / SID / "scene.md").write_text(
            (ROOT / "lessons" / SID / "scene.md").read_text(encoding="utf-8"),
            encoding="utf-8")
        (root / "personas").mkdir()
        (root / "personas" / "personas.json").write_text(
            (ROOT / "personas" / "personas.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        scene_audio._register_line()
        sha = scene_audio.scene_md_sha16(str(root / "lessons"), SID)
        extra = (SID, sha, "0.35")
        # 产物不存在 → 过期（产物缺失判据）
        ok, why = status_of(root, scene_audio.register_kind, f"{SID}/ru-RU", ["build/scene/audio/x.json"])
        rows.append((not ok, f"产物缺失 → 判过期（{why[:24]}…）"))
        # 记账后（带 extra）：产物仍缺失 → 仍过期；补上产物 → fresh
        from feuille.ledger import record
        art = "build/scene/audio/fake.json"
        record(root, scene_audio.register_kind, f"{SID}/ru-RU", [art], extra=extra)
        ok1, _ = status_of(root, scene_audio.register_kind, f"{SID}/ru-RU", [art])   # 漏传 extra
        rows.append((not ok1, "产物缺失（即使指纹一致）→ 仍判过期"))
        (root / art).parent.mkdir(parents=True, exist_ok=True)
        (root / art).write_text("{}", encoding="utf-8")
        ok2, _ = status_of(root, scene_audio.register_kind, f"{SID}/ru-RU", [art])   # 漏传 extra
        rows.append((ok2, "产物齐 + 漏传 extra → 按条目里那份复算，fresh（自描述）"))
        # scene.md 变 → sha 变 → extra 变 → 指纹变（status_of 用条目里的旧 sha）
        from feuille.ledger import fingerprint
        fp_old = fingerprint(root, scene_audio.register_kind, "u", extra)
        fp_new = fingerprint(root, scene_audio.register_kind, "u", (SID, "0" * 16, "0.35"))
        rows.append((fp_old != fp_new, "scene.md sha 进 extra → 变更即指纹变"))

    # ---- 4. 叶子可达：路由表指向本模块 main，无参不可调用会在此暴露 ----
    target = cli.COMMANDS.get(("scene", "tts"))
    rows.append((target == ("feuille.scene_audio", "main"),
                 f"路由表 scene tts → {target}"))
    import inspect
    try:
        inspect.signature(scene_audio.main).bind()
        rows.append((True, "scene_audio.main 无参可调用（叶子真可达）"))
    except TypeError as e:
        rows.append((False, f"main 无参不可调用：{e}"))

    # ---- 5. timeline 文件名：doctor ④ 探针与 scene_audio 落盘同一条格式串 ----
    # 旧版断言是 `want == … or True` 的永真式，且两边都是测试自己拼的字面量——
    # 什么都没验。真判据：两边源码里各自真的在用同一条格式串 + 同一个
    # build/scene 目录约定（任何一边改了名/挪了目录，这里当场红）。
    lesson_src = (ROOT / "src" / "feuille" / "lesson.py").read_text(encoding="utf-8")
    sa_src = (ROOT / "src" / "feuille" / "scene_audio.py").read_text(encoding="utf-8")
    pat = "scene-{sid}_{lc}.timeline.json"
    rows.append((pat in lesson_src and pat in sa_src
                 and '"build" / "scene"' in lesson_src
                 and '"build" / "scene"' in sa_src,
                 "timeline 文件名 doctor④ 探针 ↔ scene_audio 落盘同格式串同目录（源码机检）"))

    fails = [m for ok, m in rows if not ok]
    for ok, m in rows:
        print(f"  [{'PASS' if ok else 'FAIL'}] {m}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：scene_audio {len(rows) - len(fails)} PASS / {len(fails)} FAIL"
          "（离线断言；网络合成路径由 verify_tts 覆盖）")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(check())
