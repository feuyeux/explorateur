#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_skill_scripts.py — skill 层持久脚本判据的反向验证

覆盖三处 skill 层脚本新加的检查（纪律 2：加了新检查就要做反向验证；
这些脚本不在 src/feuille 包里，不受其它套件覆盖，按文件路径装载）：

1. **check_publish_copy.py**（publish-copy）：AI 指纹门 + 数字溯源门。
   - 好数据放行：归档验收稿《落叶》（assets/example）全部机检门零违规
     ——新门在已验收成果上误伤就是签名太凶，这条就是校准锚；
   - 凿洞：指纹签名逐条命中；数字溯源——数字对上事实表 PASS、对不上 FAIL、
     无数字直通、中文数字不算数字载体。
2. **gen_bgm.py**（bgm-bed）：pad_request（目标床长 → 实时后端请求垫量）与
   bed_len_verdict（床长判据）两个纯函数。凿洞用实测事故数字：
   请求 80s 实得 78.0s、请求 62s 实得 54.0s（SKILL.md 坑 1）→ 都必须 ⚠。
3. **color_contrast.py**（multilingual-video-poetry）：gap_verdict——
   阈值是项目自标定值（不内置默认），判据只判「字芯-背景亮度差 ≥ 阈值」。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    p = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cpc = _load("check_publish_copy", "skills/publish-copy/scripts/check_publish_copy.py")
gbm = _load("gen_bgm", "skills/bgm-bed/scripts/gen_bgm.py")
cc = _load("color_contrast", "skills/multilingual-video-poetry/scripts/color_contrast.py")


def _xhs_file(td: pathlib.Path, body: str, title: str = "十二种语言说落叶") -> pathlib.Path:
    """合成一份只够目标检查吃的 xiaohongshu 稿（目标检查只读读者面文字）。"""
    text = (f"## 标题（20 字内）\n{title}\n\n## 正文\n{body}\n\n"
            "## 话题标签\n#落叶 #秋天 \n\n"
            "## 发布贴士\n发布后自己置顶一条（\"评论区报数：你最想说哪种语言的秋天\"）\n")
    p = td / "xiaohongshu.md"
    p.write_text(text, "utf-8")
    return p


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []

    # ==================== check_publish_copy ====================
    # ---- 0. 好数据放行：归档验收稿全部门零违规（含新门）----
    example = ROOT / "skills" / "publish-copy" / "assets" / "example"
    bad = []
    for plat, spec in cpc.PLATFORM.items():
        p = example / spec["filename"]
        for label, fn in cpc.CHECKS:
            if fn(p, plat):
                bad.append(f"{plat}/{label}")
    rows.append((not bad,
                 "归稿《落叶》全部机检门零违规（AI 指纹门不误伤已验收成果）"
                 + (f"　**{bad}**" if bad else "")))

    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)

        def fp_hits(body: str) -> list[str]:
            return cpc.check_ai_fingerprint(_xhs_file(tdp, body), "xiaohongshu")

        # ---- 1. 凿洞：AI 指纹逐条命中 ----
        holes = [
            ("这视频真的绝绝子。", "绝绝子"),
            ("看到最后我只想说 yyds。", "yyds"),
            ("这是藏了心机的作品！！", "藏了心机"),
            ("！!连续感叹号刷屏！！", "连续感叹号"),
            ("原来雪花也有自己的名字。", "句首「原来…」"),
            ("这份心意像家一样的温暖。", "模板句"),
            ("🍂✨🪶👇 一行四个 emoji。", "emoji"),
        ]
        miss = [w for body, w in holes
                if not any(w in m for m in fp_hits(body))]
        rows.append((not miss, "AI 指纹凿洞：7 类签名逐条命中"
                     + (f"　**漏了 {miss}**" if miss else "")))

        # ---- 1b. 反向的反向：句中「原来」不误伤（全量禁会砍掉合法叙事）----
        hits = fp_hits("我看见原来的颜色，还是那片林子。")
        rows.append((not hits, "句中「原来」不误伤（只判句首揭秘形态）"
                     + (f"　**误伤 {hits}**" if hits else "")))

        # ---- 2. 数字溯源：对上=过 / 对不上=拦 / 无数字=直通 ----
        facts = {"duration_s": 52.4, "languages": 12}
        p = _xhs_file(tdp, "52 秒看完十二种语言——不对，是 12 种语言。")
        rows.append((not cpc.check_fact_provenance(p, "xiaohongshu", facts),
                     "数字溯源：52 对实测 52.4、12 对语种数 → 全部放行（四舍五入是写作不是编造）"))
        p = _xhs_file(tdp, "61 秒看完。")
        rows.append((bool(cpc.check_fact_provenance(p, "xiaohongshu", facts)),
                     "数字溯源凿洞：61 在事实表里找不到出处 → 被拦"))
        p = _xhs_file(tdp, "十二种语言说落叶，评论区报数。")
        rows.append((not cpc.check_fact_provenance(p, "xiaohongshu", facts),
                     "数字溯源：中文数字不是数字载体，无数字化稿直通"))
        rows.append((not cpc.check_fact_provenance(
            _xhs_file(tdp, "增益 0.1012。"), "xiaohongshu",
            {"gain": "0.1012"}),
            "数字溯源：字符串形式的事实值（边车里的 \"0.1012\"）也算出处"))

    # ==================== gen_bgm ====================
    # ---- 3. 垫量：目标 → 请求（纯函数）----
    pad_ok = (gbm.pad_request(80) == 92.0 and gbm.pad_request(62) == 71.3)
    rows.append((pad_ok, f"pad_request：目标 80→{gbm.pad_request(80):g}s、62→{gbm.pad_request(62):g}s"
                 f"（×{gbm.PAD_FACTOR:g} 垫量，不是原值）"))

    # ---- 4. 床长判据：实测事故数字必须 ⚠（SKILL.md 坑 1 的机器形态）----
    warn = gbm.bed_len_verdict(78.0, 80).startswith("⚠") and \
        gbm.bed_len_verdict(54.0, 62).startswith("⚠")
    rows.append((warn, "床长判据凿洞：实得 78.0<80、54.0<62（两次实测事故）→ ⚠"))
    ok = gbm.bed_len_verdict(92.0, 80).startswith("ok") and \
        gbm.bed_len_verdict(79.0, 80).startswith("ok")
    rows.append((ok, "床长判据放行：垫量后 92≥80 过；79 在 1s 容差内过（容差边界）"))

    # ==================== color_contrast ====================
    # ---- 5. gap_verdict：阈值外部标定，判据只判「差值 ≥ 阈值」----
    g_ok = cc.gap_verdict(0.35, 0.30, "春").startswith("PASS")
    g_bad = cc.gap_verdict(0.25, 0.30, "冬").startswith("FAIL")
    rows.append((g_ok and g_bad,
                 "color_contrast gate：差 0.35≥阈值 0.30 → PASS；差 0.25<0.30 → FAIL"
                 "（阈值自标定，不内置默认）"))

    # ---- 6. 事实表装载：--facts 的 JSON 键随意、值可核对 ----
    try:
        nums = cpc._fact_numbers({"a": 12, "b": "52.4", "c": "不是数字", "d": True})
        ok = nums == {12.0, 52.4}
    except Exception:                                        # noqa: BLE001
        ok = False
    rows.append((ok, "_fact_numbers：数值与可 parse 字符串收进、布尔/文本不收"))
    return rows


def main() -> int:
    print("=" * 72)
    print("skill 层脚本判据：publish-copy 指纹/溯源 + bgm 垫量/床长 + poetry gate")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, why in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {why}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：skill 层脚本判据 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
