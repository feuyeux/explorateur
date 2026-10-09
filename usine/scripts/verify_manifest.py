#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_manifest.py — 发布清单机制的反向验证

第 0 条好数据放行（真实数据）：《一叶知秋》三平台文案稿（examples/yiyezhiqiu/publish/，
已发布批次的原始事实源）全部解析正确——12 条齐、字段全、派生属性对得上。

反向各防一种退化：
- 体例被改（缺标题块）→ 拒解析，不静默降级
- 标题/正文超上限 → 抓；钩子不符约定 → 抓；无话题 → 抓；条数不齐 → 抓
- 手标字数错 → fill_annotations 按 len() 回填（回填后再解析，标注与实测一致）
- 坑㉲：emoji 判定必须是码位区间（`ch in "🎰"` 成员测试恒 False）
- 素材缺失 → build_manifest 报「清单不齐」，存在时才放行
- 两版体例（带/不带时长字段）都能解析
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import manifest as mf          # noqa: E402

PUB = ROOT / "examples" / "yiyezhiqiu" / "publish"


def make_copy(path, *, with_duration: bool, sections):
    """合成一份文案稿夹具。sections: [(no, lang, locale, title, body, topics)]"""
    out = []
    for no, lang, locale, title, body, topics in sections:
        head = f"### {no:02d} · {lang} `{locale}`"
        if with_duration:
            head += " · 00:52 · ✅ 已发布"
        out += [head, "**标题**（99 字）", "```", title, "```",
                "**正文**（99 / 1000）", "```", body, "```"]
        if topics is not None:
            out += ["**话题**", "```", topics, "```"]
        out += [f"源文件：`build/video/{lang}_1080x1920.mp4`", ""]
    path.write_text("\n".join(out), "utf-8")


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-manifest-")
    d = pathlib.Path(tmp.name)

    # ---- 0. 好数据放行：真实文案稿（已发布批次的原始事实源）----
    for fname, plat, expect_hook in (("douyin-copy.md", "douyin", "question"),
                                     ("xiaohongshu-copy.md", "xiaohongshu", "emoji+question"),
                                     ("bilibili-copy.md", "bilibili", None)):
        recs = mf.parse_copy(PUB / fname)
        rows.append((len(recs) == 12, f"{fname}: 解析出 12 条（得 {len(recs)}）"))
        hooks = {r["hook"] for r in recs}
        rows.append((hooks == {expect_hook} if expect_hook else bool(hooks),
                     f"{fname}: 钩子全为 {expect_hook or '（无约定）'}（实得 {hooks}）"))
        rows.append((all(r["title"] and r["body"] and r["topics"] and r["locale"]
                         and r["title_chars"] == len(r["title"]) for r in recs),
                     f"{fname}: 字段齐全，title_chars 派生自 len()"))
    probs = mf.check_copy(PUB / "douyin-copy.md", "douyin", expect=12)
    rows.append((not probs, "真实抖音文案过平台检查" + (f"　**{probs[:2]}**" if probs else "")))

    # 小红书话题在正文末行：解析进 topics
    xhs = mf.parse_copy(PUB / "xiaohongshu-copy.md")
    rows.append((all(r["topics"] for r in xhs),
                 "小红书话题从正文末行提取（无独立话题块的体例）"))

    # ---- 1. 两版体例（带/不带时长）都解析 ----
    secs = [(1, "中文", "zh-CN", "标题甲", "说到颜色，你会想到什么？正文一。", "#语言学习"),
            (2, "英语", "en-US", "标题乙", "🎨 秋天来了？正文二。\n#秋日", None)]   # 无话题块 → 从正文末行提取
    p1, p2 = d / "a.md", d / "b.md"
    make_copy(p1, with_duration=True, sections=secs)
    make_copy(p2, with_duration=False, sections=secs)
    ra, rb = mf.parse_copy(p1), mf.parse_copy(p2)
    rows.append((len(ra) == 2 and len(rb) == 2
                 and ra[0]["durationSec"] == 52 and rb[0]["durationSec"] is None
                 and ra[0]["publishedMark"] and not rb[0]["publishedMark"],
                 "带时长/不带时长两版体例都解析（时长与已发布标记可选）"))
    rows.append((rb[0]["source"].endswith("中文_1080x1920.mp4"), "源文件行解析"))
    rows.append((rb[0]["hook"] == "question" and rb[1]["hook"] == "emoji+question",
                 f"钩子分类（{rb[0]['hook']} / {rb[1]['hook']}）"))

    # ---- 2. 体例被改 → 拒解析 ----
    broken = d / "broken.md"
    broken.write_text("### 01 · 中文 `zh-CN`\n**正文**\n```\n只有正文没标题。\n```\n", "utf-8")
    try:
        mf.parse_copy(broken)
        rows.append((False, "缺标题块必须拒解析——没拒"))
    except SystemExit as e:
        rows.append((True, f"缺标题块 → 拒解析（{str(e)[:30]}…）"))

    # ---- 3. 平台检查：超限/无话题/钩子/条数 ----
    bad_secs = [(1, "中文", "zh-CN", "这是一个特别特别特别特别特别长的标题超过二十个字了",
                 "🎨 有 emoji 开场？但约定要 question。", "#话题"),
                (2, "英语", "en-US", "好标题", "没有话题符号的话题块省略。", None)]
    make_copy(d / "bad.md", with_duration=False, sections=bad_secs)
    probs = mf.check_copy(d / "bad.md", "xiaohongshu", expect=3)
    rows.append((any("标题" in p for p in probs)
                 and any("钩子" in p for p in probs)
                 and any("话题" in p for p in probs)
                 and any("条数" in p for p in probs),
                 f"超限/钩子/无话题/条数不齐全被抓（{len(probs)} 条问题）"))

    # ---- 4. 坑㉲：emoji 判定走码位区间 ----
    rows.append((mf._is_emoji("🎨") and not mf._is_emoji("标")
                 and not ("🎨" in "🎰-🫿"),      # 成员测试恒 False 的坑本身
                 "emoji 码位区间判定（`ch in '🎰-🫿'` 成员测试恒 False——坑㉲）"))

    # ---- 5. fill_annotations：手标错 → len() 实测回填（往返一致）----
    recs = mf.parse_copy(p2)
    n = mf.fill_annotations(p2, recs)
    recs2 = mf.parse_copy(p2)
    rows.append((n == 4, f"手标字数 4 处全被回填（得 {n}）"))
    rows.append((all(r["title_chars"] == len(r["title"]) for r in recs2),
                 "回填后重解析：标注 = len() 实测"))
    text = p2.read_text("utf-8")
    rows.append(("（3 字）" in text, "标注已改成实测字数（标题甲 = 3 字）"))

    # ---- 6. build_manifest：素材存在性前置 ----
    vid = d / "video" / "中文_1080x1920.mp4"
    cov = d / "covers" / "中文_douyin34_1080x1440.png"
    vid.parent.mkdir(parents=True)
    vid.write_bytes(b"x")
    plans = {"douyin": {"copy": p2,
                        "video": lambda r: vid,
                        "cover": lambda r: cov}}
    man, probs = mf.build_manifest(plans)
    rows.append((any("封面缺失" in p for p in probs),
                 "封面不存在 → 清单不齐（素材存在性前置）"))
    cov.parent.mkdir(parents=True)
    cov.write_bytes(b"x")
    man, probs = mf.build_manifest(plans, out_path=d / "manifest.json")
    rows.append((not probs and len(man["douyin"]) == 2
                 and man["douyin"][0]["video"].endswith(".mp4")
                 and man["douyin"][0]["tags"] == ["语言学习"]
                 and man["douyin"][1]["tags"] == ["秋日"],
                 "素材齐 → 清单 2 条、话题成列表（块内 #语言学习 + 正文提取 #秋日）"))
    rows.append((json.loads((d / "manifest.json").read_text("utf-8"))["douyin"]
                 == man["douyin"], "清单落盘可回读"))
    return rows


def main() -> int:
    print("=" * 72)
    print("发布清单（parse_copy / check_copy / fill_annotations / build_manifest）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：发布清单 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
