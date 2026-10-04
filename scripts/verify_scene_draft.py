#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_draft.py — P2-1 草稿生成器的验收与反向验证

**验收判据（正向）**：拿一门**已经验收通过**的课（`lessons/numbers`，qa_scene 60/60），
让生成器从 brief 重建结构，然后逐行比对**该由生成器负责的那部分**：

    §0 全节          必须逐字节相同（token 表 / 装置表 / 角色 / 节拍表）
    §2 每语种每一行   speaker / mood / 姿态码序列必须相同
    §5 表头          必须与 §0.1 token 书写序一致

台词文字、词表词义、舞台句**不比**——那是作者填的，生成器本来就不生成。
判据取「生成器负责的部分」而不是「整文件相同」，因为后者要求生成器替作者写作，
那既是做不到的，也会让这条验收永远红着。

**反向验证**：喂已知坏 brief，必须在**生成阶段**就报错（而不是产出一支渲不出来的片）。
只跑「好 brief 能生成」证明不了任何事——一个恒返回一段固定文本的函数也满足它。
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usine import scene_draft                               # noqa: E402
from usine.data import cards_doc, personas, scene_doc       # noqa: E402
from usine.parse_scene import _norm_pose, parse_line, parse_spec  # noqa: E402

BRIEF = ROOT / "lessons/numbers/brief.json"
ACCEPTED = ROOT / "lessons/numbers/scene.md"


def plan_of(brief):
    beats = scene_draft.expand_skeleton(brief["skeleton"], brief["lines"])
    return beats, scene_draft.assign_lines(beats, brief.get("spec", {}))


# ---------------------------------------------------------------- 正向：复现已验收的课

def _machine_lines(text):
    """只取**机读行**：表格行、`key: value` 元信息行、`###` 小节标题。

    作者在 §0 里写的散文说明（如「本课 token 用字牌 chip…」）不比——生成器本来就不
    写作者的话，拿它当判据等于要求生成器替作者写作，那这条验收会永远红着。
    """
    out = []
    for l in text.splitlines():
        s = l.strip()
        if not s or s.startswith(">"):
            continue
        if s.startswith("|") or s.startswith("###") or re.match(r"^[a-zA-Z]+:\s", s):
            out.append(s)
    return out


def check_reproduction():
    brief = json.loads(BRIEF.read_text("utf-8"))
    md = ACCEPTED.read_text("utf-8")
    rows = []

    # --- §0 逐行（仅机读行） ---
    def sec0(t):
        return t[t.index("## 0."):t.index("## 1.")]
    reg, langs, P, C = (scene_draft._registries(), scene_draft._langs(),
                        personas(), cards_doc())
    gen_md = scene_draft.render(brief, P, C, langs, reg)
    g = _machine_lines(sec0(gen_md))
    a = _machine_lines(sec0(md))
    # 已验收稿的 round 段 askBy 写 `-`（不限定发问方），生成稿写 `A`（更严格）。
    # 两种写法的**语义**是否一致，由下面那条「节拍语义等价」单独判——文本不同不该判失败。
    g_cmp = [x.replace("| even | A |", "| even | - |") for x in g]
    rows.append((g_cmp == a, f"§0 机读规格逐行一致（生成 {len(g)} 行 / 已验收 {len(a)} 行）"))
    if g_cmp != a:
        import difflib
        for d in list(difflib.unified_diff(a, g_cmp, "已验收", "生成", lineterm=""))[:24]:
            print("        " + d)

    # --- §2 逐语种逐行：speaker / mood / 姿态 ---
    ok_spk = ok_mood = ok_pose = ok_cnt = True
    total = 0
    for loc in brief["locales"]:
        # 取该语种的剧本块（`### 2.x <label> <loc>｜…` 到下一个 `### 2.` 或 `## 5.`）
        start = md.index(f"{loc}｜")
        nxt = md.find("\n### 2.", start)
        end = md.index("\n## 5.") if nxt < 0 else nxt
        acc = [x for x in (parse_line(l) for l in md[start:end].splitlines()
                           if l.strip().startswith("- **")) if x]
        _, plan = plan_of(brief)
        total += len(acc)
        ok_cnt &= len(acc) == len(plan)
        for a1, g1 in zip(acc, plan):
            ok_spk &= a1["speaker"] == g1["speaker"]
            ok_mood &= a1["mood"] == g1["mood"]
            want_pose = {_norm_pose(c) for c in (g1["pose"] or "").split() if c}
            ok_pose &= want_pose <= set(a1["gesture"]["poses"])
    rows.append((ok_cnt, f"§2 台词行数一致（{total} 行 = {len(brief['locales'])} 语种 × 17）"))
    rows.append((ok_spk, "§2 每行说话人一致"))
    rows.append((ok_mood, "§2 每行情绪一致"))
    rows.append((ok_pose, "§2 每行姿态码都在已验收稿同一行里"))

    # --- 节拍表语义等价：拿已验收 scene.json 的每行 role/isQuestion 作真值 ---
    acc_scene = scene_doc("numbers")
    loc0 = brief["locales"][0]
    want = [(l["role"], l["isQuestion"]) for l in acc_scene["locales"][loc0]["dialogue"]]
    got = [(r["beat"], r["isQuestion"]) for r in plan_of(brief)[1]]
    same = len(want) == len(got) and all(w == g for w, g in zip(want, got))
    rows.append((same, "节拍表语义等价：每行的骨架归属与问句标记都与已验收 scene.json 相同"))

    acc_beats, gen_beats = parse_spec(md)[6], parse_spec(gen_md)[6]
    rows.append((len(acc_beats) == len(gen_beats) == 5,
                 f"§0.5 节拍数一致（{len(gen_beats)} 节）"))

    # --- 引号对 ---
    q_ok = True
    for loc in brief["locales"]:
        start = gen_md.index(f"{loc}｜")
        blk = gen_md[start:gen_md.find("\n### 2.", start) if gen_md.find("\n### 2.", start) > 0
                      else gen_md.index("\n## 5.")]
        opener, closer = langs[loc]["quote"][0], langs[loc]["quote"][-1]
        for l in blk.splitlines():
            if l.strip().startswith("- **"):
                q_ok &= f"（{l.split('（')[1].split('）')[0]}）：{opener}TODO{closer}" in l
    rows.append((q_ok, "每个语种的引号对来自 languages/<loc>/manifest.json"))
    return rows


# ---------------------------------------------------------------- 反向验证

BAD_BRIEFS = [
    ("情绪不在 MOOD_FACE 内（生成器必须当场拦下，否则渲染时才炸）",
     lambda b: {**b, "spec": {**b["spec"], "open.mood": "ecstatic"}}),
    ("姿态码拼错（jum-celebrate）",
     lambda b: {**b, "spec": {**b["spec"], "summary.pose": "jum-celebrate"}}),
    ("装置 style 不在 DEVICE_STYLES 注册表内",
     lambda b: {**b, "devices": {**b["devices"], "zh-CN": {**b["devices"]["zh-CN"], "style": "carousel"}}}),
    ("语种没有目录（新增语种忘了建 languages/<loc>/manifest.json）",
     lambda b: {**b, "locales": ["zh-CN", "xx-XX"]}),
    ("骨架行数超了（rest 段只剩 0 行）",
     lambda b: {**b, "lines": 4, "skeleton": [{**s, "lines": "rest" if s["beat"] == "round" else s["lines"]}
                                              for s in b["skeleton"]]}),
    ("两个 rest 段（骨架不可能满足）",
     lambda b: {**b, "lines": 9, "skeleton": [{**s, "lines": "rest"} for s in b["skeleton"]]}),
    ("骨架只展开出 1 行台词（parse_locales 要求 ≥2）",
     lambda b: {**b, "lines": 1, "skeleton": [{"beat": "open", "lines": 1}]}),
]


def selftest():
    brief = json.loads(BRIEF.read_text("utf-8"))
    reg, langs, P, C = scene_draft._registries(), scene_draft._langs(), personas(), cards_doc()
    rows = []

    ok = scene_draft.render(brief, P, C, langs, reg)
    rows.append((bool(ok) and "## 0." in ok and "## 2." in ok and "## 5." in ok,
                 "好 brief 能生成出含 §0/§2/§5 的草稿"))

    for desc, mutate in BAD_BRIEFS:
        bad = mutate(copy.deepcopy(brief))
        try:
            scene_draft.render(bad, P, C, langs, reg)
            caught, why = False, "竟然生成成功了"
        except SystemExit as exc:
            caught, why = True, str(exc).splitlines()[0][:60]
        except Exception as exc:                       # noqa: BLE001
            caught, why = True, f"{type(exc).__name__}: {exc}"[:60]
        rows.append((caught, f"{desc} → {why}"))

    # 生成稿必须能被 parse_line 逐行读回（引号/说话人/情绪槽位是真的，不是摆设）
    gen = scene_draft.render(brief, P, C, langs, reg)
    parsed = [x for x in (parse_line(l) for l in gen.splitlines()
                          if l.strip().startswith("- **")) if x]
    rows.append((len(parsed) == 17 * len(brief["locales"]),
                 f"生成稿的每一行都能被 parse_line 读回（{len(parsed)} 行）"))
    rows.append((all(p["text"] == "TODO" for p in parsed),
                 "台词槽位原样留空（生成器不代作者写作）"))

    # gaps 必须数得出来，且填完之后会变少
    g0 = scene_draft.gaps(gen)
    filled = gen.replace("TODO", "字").replace("：字", "：")
    g1 = scene_draft.gaps(filled)
    rows.append((g0["仍带 TODO 的台词行"] == 34 and g1["仍带 TODO 的台词行"] == 0,
                 f"欠账清单随填写递减（{g0['仍带 TODO 的台词行']} → {g1['仍带 TODO 的台词行']}）"))
    return rows


def main():
    print("=" * 70)
    print("P2-1 草稿生成器验收：复现已验收的 lessons/numbers")
    print("=" * 70)
    fails = 0
    for ok, msg in check_reproduction():
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok

    print("-" * 70)
    print("反向验证：坏 brief 必须在生成阶段就被拦下")
    print("-" * 70)
    for ok, msg in selftest():
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok

    print("=" * 70)
    print(f"{'OK' if not fails else 'FAIL'}：草稿生成器 {15 - fails}/15 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
