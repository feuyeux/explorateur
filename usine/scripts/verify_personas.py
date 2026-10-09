#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_personas.py — 人设契约校验器的反向验证

第 0 条好数据放行：**28 人班底全部通过**（validate_persona 逐人零问题 +
validate_roster 零问题）——判据写反时这条会全红。

反向：定向破坏必须被抓（每条对应一类真实退化）：
坏脸型（不在 FACE_SPECS）、坏姿态码（不在 POSE_CODES）、坏 hex、缺调色板键、
声线越安全域、locale 非法、档案字段缺失、moves 私加槽位、
班底撞 id、语种配对破坏（两人同 energy）。
夹具 = feuille/personas/personas.json（审计过的 28 人）。
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import persona, rig            # noqa: E402

PERSONAS = json.loads((ROOT / "personas" / "personas.json").read_text("utf-8"))["personas"]


def check():
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：28 人零问题 ----
    bad = []
    for p in PERSONAS:
        bad += persona.validate_persona(p)
    rows.append((not bad, "28 人班底逐人校验零问题" + (f"　**{bad[:2]}**" if bad else "")))
    roster = persona.validate_roster(PERSONAS)
    rows.append((not roster, "班底级不变量通过（14 语种配对齐全）"
                 + (f"　**{roster[:2]}**" if roster else "")))

    # ---- 1. 反向：定向破坏必须被抓 ----
    base = copy.deepcopy(PERSONAS[0])          # xiaoman

    def corrupt(mutate, expect_kw, what):
        p = copy.deepcopy(base)
        mutate(p)
        probs = persona.validate_persona(p)
        rows.append((any(expect_kw in s for s in probs),
                     f"{what} → 被抓" + ("" if any(expect_kw in s for s in probs)
                                          else f"　**漏了！问题列表：{probs[:2]}**")))

    corrupt(lambda p: p["movement"].__setitem__("face", "diamond"),
            "FACE_SPECS", "坏脸型 diamond")
    corrupt(lambda p: p["moves"].__setitem__("wave", "moonwalk"),
            "POSE_CODES", "moves.wave = 不存在的姿态码")
    corrupt(lambda p: p["palette"].__setitem__("skin", "#F5C9A"),
            "#RRGGBB", "调色板坏 hex")
    corrupt(lambda p: p["palette"].pop("outfitBottom"),
            "palette.outfitBottom", "缺调色板键")
    corrupt(lambda p: p["voice"].__setitem__("rate", "+99%"),
            "安全域", "rate 越安全域 +99%")
    corrupt(lambda p: p["voice"].__setitem__("pitch", "-40Hz"),
            "安全域", "pitch 越安全域 -40Hz")
    corrupt(lambda p: p.__setitem__("locale", "zh_CN"),
            "locale", "locale 分隔符非法")
    corrupt(lambda p: p.__setitem__("quirk", ""),
            "quirk", "档案字段 quirk 清空")
    corrupt(lambda p: p["moves"].__setitem__("backflip", "jump_celebrate"),
            "槽位", "moves 私加槽位 backflip")
    corrupt(lambda p: p["accessories"].append({"code": "watch", "physics": "explode"}),
            "physics", "挂件 physics 非法")
    corrupt(lambda p: p["movement"].__setitem__("blinkCycleSec", 0),
            "正数", "眨眼周期 0")
    corrupt(lambda p: p.__setitem__("energy", "chaotic"),
            "energy", "energy 非法")

    # ---- 2. 班底反向：撞 id / 配对破坏 ----
    roster = copy.deepcopy(PERSONAS)
    roster.append(copy.deepcopy(roster[0]))
    rows.append((any("重复" in s for s in persona.validate_roster(roster)),
                 "班底撞 id → 被抓"))
    roster2 = copy.deepcopy(PERSONAS)
    roster2[1]["energy"] = roster2[0]["energy"]        # 同语种两人同 energy
    rows.append((any("一活泼一沉稳" in s for s in persona.validate_roster(roster2)),
                 "同语种两人同 energy → 配对不变量被抓"))

    # ---- 3. 合法值现取注册表的活性证明（注册表变了校验跟着变，不会腐烂）----
    rows.append((sorted(rig.FACE_SPECS) == sorted(["round", "tall", "oval", "wide", "heart", "square"]),
                 f"FACE_SPECS 六型脸在位（{sorted(rig.FACE_SPECS)}——校验对着它查，不另抄）"))
    rows.append((len(rig.POSE_CODES) >= 30,
                 f"POSE_CODES {len(rig.POSE_CODES)} 码在位（moves 校验的现取来源）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("persona 契约校验器（validate_persona / validate_roster）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：persona 契约 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
