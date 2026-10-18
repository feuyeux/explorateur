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
3. ~~**color_contrast.py**（multilingual-video-poetry）~~——已随 P5-7c 归流
   @feuille/poetry，gap_verdict 两行移植 packages/poetry/test/poetry.test.ts。
4. **audit_charset.py**（one-page-poster）：字符子集门（tofu 防线）。
   家族归属是栈式的（映射类压栈、无族类 span 继承外层族、闭合弹栈）——
   旧扁平实现在任何带 class 的标签上清空家族态，叠印层逐字母 span
   （.lay/.top/.t/.c）全是无族类标签，整个大词逃过 tofu 门（a01/a02 实锤：
   a01 的 OBS Deva 只查到 6 个字符＝语言名标签，धन्यवाद 整词漏网）。
   凿洞：只出现在叠印层的码位（ा）被删出子集必须当场 MISSING；
   弹栈纪律：族闭合后的文本不许被误归。
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
ac = _load("audit_charset", "skills/one-page-poster/scripts/audit_charset.py")


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

    # ---- 6. 事实表装载：--facts 的 JSON 键随意、值可核对 ----
    try:
        nums = cpc._fact_numbers({"a": 12, "b": "52.4", "c": "不是数字", "d": True})
        ok = nums == {12.0, 52.4}
    except Exception:                                        # noqa: BLE001
        ok = False
    rows.append((ok, "_fact_numbers：数值与可 parse 字符串收进、布尔/文本不收"))

    # ==================== audit_charset ====================
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        # 合成叠印源：.lay/.top/.c/.sp 全是「带 class 但无映射族」的标签，
        # 逐字母大词文本只活在这里——扁平重置的盲区本体
        (tdp / "poster_src.html").write_text(
            "<html><body>\n"
            '<div class="cell f-deva"><span class="stack f-deva">'
            '<span class="lay v" aria-hidden="true">बात</span>'
            '<span class="top"><span class="c">ब</span><span class="sp"></span>'
            '<span class="c">त</span></span></span></div>\n'
            '<div class="cell">Ω</div>\n'      # 族外文本：不许被误归
            "</body></html>\n", "utf-8")

        def _missing(subset_text: str) -> list:
            (tdp / "fonts.json").write_text(json.dumps([
                {"family": "OBS Deva", "google": "Noto+Sans+Devanagari:wght@500",
                 "text": subset_text, "classes": ["f-deva"]}]), "utf-8")
            return ac.check(tdp / "poster_src.html", tdp / "fonts.json")[0]

        # ---- 7. 好数据放行：叠印层逐字母文本进扫描面且全覆盖 ----
        miss = _missing("बात")
        rows.append((not miss,
                     "audit_charset 好数据放行：合成叠印源（.lay/.top 逐字母）全绿"
                     + (f"　**误报 {miss}**" if miss else "")))

        # ---- 8. 凿洞：只出现在叠印层的码位删出子集必须被抓 ----
        miss = _missing("बत")                 # ा 只活在 .lay/.top 的叠印文本里
        caught = any(ch == "ा" for _, ch, _ in miss)
        rows.append((caught,
                     "audit_charset 凿洞：叠印层专属码位 ा 删出子集 → MISSING"
                     + ("" if caught else "　**漏网：扁平重置的盲区复活了**")))

        # ---- 9. 弹栈纪律：族闭合后的文本不被误归 ----
        leaked = any(ch == "Ω" for _, ch, _ in miss)
        rows.append((not leaked,
                     "audit_charset 弹栈纪律：族外文本（Ω）不进任何族"))
    return rows


def main() -> int:
    print("=" * 72)
    print("skill 层脚本判据：publish-copy 指纹/溯源 + bgm 垫量/床长 + poster 字符门")
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
