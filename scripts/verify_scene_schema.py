#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_schema.py — `scene_schema.validate_scene` 的反向验证

照抄 render-handbook §4 对探针的要求：「拿已知坏数据证明检查会 FAIL，再拿好数据证明放行」。
只跑「真实场景全绿」的测试等于没测——校验层完全可能因为规则写错而**恒真**，
那样 parse 阶段的自检就是一个永远点头的摆设。

做法：对真实 scene.json 做 12 种定向破坏，每次要求校验层报出**预期的具体问题**，
最后确认原数据仍判 PASS。

用法：uv run python scripts/verify_scene_schema.py [--scene colors]
"""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from usine.data import cards_doc, personas, scene_doc          # noqa: E402
from usine.scene_schema import validate_scene                  # noqa: E402


def mutations(scene, personas, cards):
    """[(名称, 破坏函数, 期望问题里必须出现的片段)]"""
    def drop_top(s):
        s.pop("tokenWords", None)

    def drop_token(s):
        s["tokenOrder"] = s["tokenOrder"][:-1]

    def bad_chip(s):
        """chip 以 # 开头却不是合法 #RRGGBB。（不带 # 的裸文本是**合法字牌**，
        parse_spec 会把 md 里的引号 strip 掉，`"1"` 与 `1` 落库后不可区分。）"""
        s["tokens"][s["tokenOrder"][0]] = "#GGGGGG"

    def ghost_rtl(s):
        s["rtlLocales"] = list(s.get("rtlLocales") or []) + ["xx-XX"]

    def bad_speaker(s):
        s["locales"]["zh-CN"]["dialogue"][0]["speaker"] = "C"

    def bad_mood(s):
        s["locales"]["zh-CN"]["dialogue"][0]["mood"] = "angry"

    def bad_pose(s):
        s["locales"]["zh-CN"]["dialogue"][0]["gesture"]["poses"] = ["fly"]

    def bad_style(s):
        s["locales"]["zh-CN"]["prop"]["device"]["style"] = "unknown_style"

    def blank_marker(s):
        for spec in (s.get("speechLevels") or {}).values():
            spec["marker"] = ""

    def wrong_name(s):
        s["locales"]["zh-CN"]["aName"] = "查无此人"

    def reversed_budget(s):
        s["durationBudget"] = [s["durationBudget"][1], s["durationBudget"][0]]

    def empty_dialogue(s):
        s["locales"]["zh-CN"]["dialogue"] = []

    def stale_egg(s):
        """彩蛋色值与被指认演员的色板脱钩（人设改色板后剧本没跟着改的典型）。"""
        for ln in s["locales"]["zh-CN"]["dialogue"]:
            if ln.get("easterEgg"):
                ln["easterEgg"]["hex"] = "#123456"
                return
        raise AssertionError("真实数据里没有彩蛋引用，用例失去意义")

    def ambiguous_egg(s):
        """让彩蛋标注同时匹配两位演员（追加标注里**尚未出现**的那位的全名）。"""
        for ln in s["locales"]["zh-CN"]["dialogue"]:
            egg = ln.get("easterEgg")
            if not egg:
                continue
            names = [p["name"]["native"] for p in personas.values() if p.get("locale") == "zh-CN"]
            absent = [n for n in names if n not in egg["label"]]
            if not absent:
                raise AssertionError(f"标注里已含全部演员名，无法构造歧义：{egg['label']!r}")
            egg["label"] += " " + absent[0]
            return
        raise AssertionError("真实数据里没有彩蛋引用，用例失去意义")

    def unknown_form(s):
        s["form"] = "monologue"

    def energy_mismatch(s):
        """§0.4 声明 A=lively；若把 A 声明成 steady 就会与实际选角对不上。"""
        s["roles"]["A"] = "steady"

    def ghost_askby(s):
        s["beats"][2]["askBy"] = "B"
        s["roles"].pop("B", None)

    def dup_beat(s):
        s["beats"].append(dict(s["beats"][0]))

    def bad_ask(s):
        s["beats"][2]["ask"] = "sometimes"

    return [
        ("删顶层 tokenWords",        drop_top,         "顶层字段缺失"),
        ("tokenOrder 少一个 key",    drop_token,      "tokenOrder 没有"),
        ("chip 是伪 hex",           bad_chip,        "chip 非法"),
        ("rtlLocales 指向不存在的语种", ghost_rtl,      "不存在的 locale"),
        ("speaker 越界",             bad_speaker,     "speaker="),
        ("mood 不在情绪表",          bad_mood,        "不在情绪表内"),
        ("手势码未注册",             bad_pose,        "不在 POSE_CODES"),
        ("装置 style 未注册",        bad_style,       "不在 DEVICE_STYLES"),
        ("§0.3 marker 被清空",      blank_marker,    "缺 marker"),
        ("A 角姓名与班底不符",       wrong_name,      "与剧本 §4 不符"),
        ("durationBudget 区间反了",  reversed_budget, "区间反了"),
        ("某语种 dialogue 为空",     empty_dialogue,  "dialogue 为空"),
        ("彩蛋色值与演员色板脱钩",    stale_egg,       "不在"),
        ("彩蛋指代不唯一",           ambiguous_egg,   "指代不唯一"),
        ("形态未实现",               unknown_form,    "尚未实现"),
        ("角色气质与选角不符",       energy_mismatch, "§0.4 声明不符"),
        ("askBy 指向未声明角色",     ghost_askby,     "未在 §0.4 roles 里声明"),
        ("节拍名重复",               dup_beat,        "节拍名有重复"),
        ("ask 取值非法",             bad_ask,         "只能是 even/odd/-"),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="colors")
    args = ap.parse_args()

    P, C = personas(), cards_doc()
    good = scene_doc(args.scene)

    print("=" * 70)
    print(f"反向验证：validate_scene 能否抓到 {args.scene} 的定向破坏")
    print("=" * 70)

    base_errs = validate_scene(good, P, C)
    if base_errs:
        print(f"  真实数据本应 PASS，却报了 {len(base_errs)} 项：")
        for e in base_errs[:5]:
            print(f"      {e}")
        print("\n  基线就不干净，后续用例无意义 ✗")
        return 1
    print("  [0] 真实数据 → PASS ✓（基线干净）")

    fails = 0
    for name, mutate, expect in mutations(good, P, C):
        s = copy.deepcopy(good)
        mutate(s)
        errs = validate_scene(s, P, C)
        caught = any(expect in e for e in errs)
        if caught:
            print(f"  ✓ {name:<26} → FAIL(抓到)")
        else:
            print(f"  ✗ {name:<26} → {'PASS 没抓到！' if not errs else 'FAIL 但不是预期项：' + str(errs[:2])}")
            fails += 1

    after = validate_scene(good, P, C)
    if after:
        print(f"  ✗ 破坏后原数据不再 PASS（测试自身污染了输入）")
        fails += 1
    else:
        print("  [n] 破坏后原数据仍 → PASS ✓（用例无副作用）")

    print("\n" + "=" * 70)
    print("SCENE SCHEMA VERIFY " + ("PASS" if not fails else f"FAIL ({fails})"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
