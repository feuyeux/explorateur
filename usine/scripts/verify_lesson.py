#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_lesson.py — 课件线校验层的反向验证（scene_schema + doctor 班底体检接线）

为什么需要：`validate_scene` 是 parse 与 render 之间的门禁（scene.json 会被手改、
也会被别的工具写出来），但在此之前**没有任何反向验证套件覆盖它**——门禁自己
没人验。本套件证三件事：

1. **好数据放行是第一条断言**（纪律 1）：一份**用遍全部注册值**的演习场景
   （每个 mood / 每个 pose / 每个 device_style 至少出现一次）零问题通过。
   这同时是注册表↔校验层的契约测试：rig / devices 改注册表，verify 阶段就炸，
   不用等下一门课渲染到一半。
2. **凿洞必被抓**（纪律 2）：坏 mood / 坏 pose / 坏装置样式 / 幽灵说话人 /
   token 表错位 / 空角色表 / 缺节拍表 / 行号重复 / 形态-同台表错配，
   定向破坏必须各自命中对应报错。
3. **doctor 班底体检接线**：坏班底（id 重复——原始清单才抓得到，{id: persona}
   索引会静默折叠）必须报 FAIL，好班底必须报 OK。判定本体
   （validate_persona / validate_roster）的反向验证在 verify_personas.py，
   这里验的是 lesson doctor 的接线。
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import devices, rig                    # noqa: E402
from feuille import lesson, scene_schema            # noqa: E402


def _drill_scene() -> dict:
    """用遍全部注册值的演习场景（合成数据，不落盘，personas=None 跳过选角检查）。

    locales 一台装置一岛（16 个 device_style 全用遍）；台词行轮转铺满
    6 个 mood 与 38 个姿态码（37 POSE_CODES + bounce_in）。
    """
    moods = sorted(rig.MOOD_FACE)
    poses = sorted(set(rig.POSE_CODES) | {scene_schema.ENTRY_POSE})
    styles = sorted(devices.DEVICE_STYLES)
    n = max(len(moods), len(poses), len(styles))
    scene = {
        "id": "registry-drill", "sceneId": "registry-drill",
        "title": "全注册表演习（合成，不落盘）",
        "tokenOrder": ["t0"], "tokens": {"t0": "#35486E"},
        "tokenWords": {},
        "roles": {"A": "lively", "B": "steady"},
        "beats": [{"beat": "b1", "ask": "-"}],
        "locales": {},
    }
    for li, st in enumerate(styles):
        lc = f"L{li}"
        scene["locales"][lc] = {
            "langLabel": f"语种{li}", "aName": f"甲{li}", "bName": f"乙{li}",
            "prop": {"device": {"style": st}},
            "dialogue": [],
        }
        scene["tokenWords"][lc] = [{"key": "t0"}]
    for i in range(n):
        lc = f"L{i % len(styles)}"
        scene["locales"][lc]["dialogue"].append({
            "i": i + 1,
            "speaker": "A" if i % 2 == 0 else "B",
            "mood": moods[i % len(moods)],
            "gesture": {"poses": [poses[i % len(poses)]]},
            "tokenKey": "t0",
            "text": f"演习行 {i + 1}",
        })
    return scene


def _hole_rows() -> list[tuple[bool, str]]:
    """凿洞：定向破坏必须命中对应报错（每种破坏各打一枪，判据与被测分开）。"""
    rows: list[tuple[bool, str]] = []
    base = _drill_scene()

    def hit(mutate, expect, what):
        s = copy.deepcopy(base)
        mutate(s)
        errs = scene_schema.validate_scene(s)
        rows.append((any(expect in e for e in errs),
                     f"{what} → 被抓" + ("" if any(expect in e for e in errs)
                                         else f"　**漏了！问题列表：{errs[:2]}**")))

    hit(lambda s: s["locales"]["L0"]["dialogue"][0].__setitem__("mood", "__nope__"),
        "不在情绪表内", "坏 mood __nope__")
    hit(lambda s: s["locales"]["L0"]["dialogue"][0]["gesture"].__setitem__("poses", ["__nope__"]),
        "POSE_CODES", "坏姿态码 __nope__")
    hit(lambda s: s["locales"]["L0"]["prop"]["device"].__setitem__("style", "__nope__"),
        "DEVICE_STYLES", "坏装置样式 __nope__")
    hit(lambda s: s["locales"]["L0"]["dialogue"][0].__setitem__("speaker", "C"),
        "非法", "幽灵说话人 C（§0.4 未声明）")
    hit(lambda s: s["tokens"].__setitem__("ghost", "#000000"),
        "tokens 有、tokenOrder 没有", "token 表多出幽灵键")
    hit(lambda s: s.__setitem__("roles", {}),
        "§0.4 没声明任何角色", "空角色表")
    hit(lambda s: s.pop("beats"),
        "缺骨架节拍表", "缺节拍表")
    hit(lambda s: s["locales"]["L0"]["dialogue"][1].__setitem__(
            "i", s["locales"]["L0"]["dialogue"][0]["i"]),
        "台词行号重复", "台词行号重复")
    hit(lambda s: s.__setitem__("cast", [{"role": "A", "locale": "L0", "framing": "full"}]),
        "form=dialogue 不该有", "dialogue 形态带 §0.6 同台表")
    hit(lambda s: (s.__setitem__("form", "polyglot"), s.pop("cast", None)),
        "缺 §0.6 同台表", "polyglot 缺同台表")
    return rows


def _doctor_rows() -> list[tuple[bool, str]]:
    """lesson doctor 的班底体检接线：坏班底 FAIL / 好班底 OK。"""
    rows: list[tuple[bool, str]] = []
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        (tdp / "lessons" / "x").mkdir(parents=True)
        bad = tdp / "personas"
        bad.mkdir()
        # 重复 id 只有**原始清单**抓得到：{id: persona} 索引会把第二条静默折叠
        # ——这正是班底体检走 personas_doc() 而不是 personas() 的原因。
        (bad / "personas.json").write_text(json.dumps(
            {"personas": [
                {"id": "dup", "locale": "zh-CN", "gender": "female", "energy": "lively"},
                {"id": "dup", "locale": "zh-CN", "gender": "female", "energy": "lively"},
            ]}, ensure_ascii=False), "utf-8")

        rep = lesson._tier_report("x", str(tdp / "lessons"), str(bad))
        roster = [c for c in rep.checks if c.name == "班底体检"]
        ok = bool(roster) and roster[0].state == lesson.FAIL and "重复" in roster[0].detail
        rows.append((ok, "doctor 班底体检接线：坏班底（id 重复，原始清单）→ FAIL"
                     + ("" if ok else f"　**实得 {[(c.state, c.detail) for c in roster]}**")))

        rep = lesson._tier_report("x", str(tdp / "lessons"), None)   # 缺省 = feuille 28 人班底
        roster = [c for c in rep.checks if c.name == "班底体检"]
        ok = bool(roster) and roster[0].state == lesson.OK
        rows.append((ok, "doctor 班底体检接线：好班底（feuille 缺省班底）→ OK"
                     + ("" if ok else f"　**实得 {[(c.state, c.detail) for c in roster]}**")))
    return rows


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：全注册表演习零问题 ----
    base = _drill_scene()
    errs = scene_schema.validate_scene(base)
    n_mood, n_pose = len(rig.MOOD_FACE), len(rig.POSE_CODES) + 1
    n_style = len(devices.DEVICE_STYLES)
    rows.append((not errs,
                 f"全注册表演习零问题（{n_mood} mood × {n_pose} pose × "
                 f"{n_style} device_style 全用遍）"
                 + ("" if not errs else f"　**{errs[:2]}**")))

    rows += _hole_rows()
    rows += _doctor_rows()
    return rows


def main() -> int:
    print("=" * 72)
    print("课件校验层：scene_schema 全注册表演习 + doctor 班底体检接线")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, why in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {why}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：课件校验层 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
