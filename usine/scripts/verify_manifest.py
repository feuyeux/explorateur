#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_manifest.py — 发布清单机制的反向验证

第 0 条好数据放行（自包含合成夹具，不依赖任何 examples 项目数据）：
合成 12 语种 × 三平台文案稿全部解析正确——12 条齐、字段全、
派生属性对得上、钩子符合各平台约定、check_copy 全过。

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
from feuille.errors import FeuilleError   # noqa: E402

# 12 语种 × 三平台（合成夹具，自包含——通用能力的验证不依赖 examples 内容）
LANGS = [("中文", "zh-CN"), ("英语", "en-US"), ("日语", "ja-JP"),
         ("韩语", "ko-KR"), ("法语", "fr-FR"), ("德语", "de-DE"),
         ("西班牙语", "es-ES"), ("俄语", "ru-RU"), ("阿拉伯语", "ar-SA"),
         ("印地语", "hi-IN"), ("葡萄牙语", "pt-BR"), ("意大利语", "it-IT")]


def make_platform_copy(path, plat: str):
    """按平台约定合成 12 语种文案稿：抖音 = 问句钩子 + 话题块、
    小红书 = emoji+问句钩子 + 话题在正文末行（无话题块）、B 站 = 陈述 + 话题块。"""
    secs = []
    for no, (lang, locale) in enumerate(LANGS, 1):
        if plat == "douyin":
            secs.append((no, lang, locale, f"一叶知秋·{lang}·第{no:02d}话",
                         f"秋天来了，{lang}里怎么形容它？第{no:02d}话带你看。",
                         f"#秋日 #{lang}"))
        elif plat == "xiaohongshu":
            secs.append((no, lang, locale, f"一叶知秋{no:02d}·{lang}",
                         f"🍂 秋天的{lang}你会说吗？第{no:02d}话干货来啦。\n#秋日 #{lang}",
                         None))
        else:   # bilibili
            secs.append((no, lang, locale, f"【一叶知秋】第{no:02d}话·{lang}·完整版",
                         f"这一话用{lang}聊聊秋天。欢迎三连。",
                         f"#秋日 #{lang}"))
    make_copy(path, with_duration=False, sections=secs)


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

    # ---- 0. 好数据放行：合成 12 语种 × 三平台文案稿 ----
    for plat, fname, want_hooks in (("douyin", "douyin-copy.md", {"question"}),
                                    ("xiaohongshu", "xiaohongshu-copy.md", {"emoji+question"}),
                                    ("bilibili", "bilibili-copy.md", {"statement"})):
        make_platform_copy(d / fname, plat)
        recs = mf.parse_copy(d / fname)
        rows.append(([r["order"] for r in recs] == list(range(1, 13)),
                     f"{fname}: 12 条齐且顺序对（得 {len(recs)} 条）"))
        hooks = {r["hook"] for r in recs}
        rows.append((hooks == want_hooks,
                     f"{fname}: 钩子全为 {sorted(want_hooks)}（实得 {hooks}）"))
        rows.append((all(r["title"] and r["body"] and r["topics"] and r["locale"]
                         and r["title_chars"] == len(r["title"])
                         and r["body_chars"] == len(r["body"])
                         and r["topic_count"] == len(r["topics"]) for r in recs),
                     f"{fname}: 字段齐全，派生属性全部现算自 len()"))
        probs = mf.check_copy(d / fname, plat, expect=12)
        rows.append((not probs, f"{fname}: 平台检查全过"
                     + (f"　**{probs[:2]}**" if probs else "")))

    # 小红书话题在正文末行：解析进 topics（无独立话题块的体例）
    xhs = mf.parse_copy(d / "xiaohongshu-copy.md")
    rows.append((all(r["topics"] and r["topics"][0] == "秋日" for r in xhs),
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
    except FeuilleError as e:
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
