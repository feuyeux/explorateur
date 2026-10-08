# -*- coding: utf-8 -*-
"""verify_collection.py — 合集**只读**核验：总数 + 收录了哪些（点击集数要少）

只读，不改任何东西。逐条读合集详情页里的作品标题，与清单比对。
用**归一化**比对（去元音符号 + 去空白 + 小写）——
抖音对阿拉伯语/希伯来语会做码位归一，逐字比对必然假阴性（2026-10-08 实测）。

用法：
    uv run --group publish python examples/sijijie/verify_collection.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille.publish import base                      # noqa: E402

OUT = ROOT / "build" / "douyin"
MANIFEST = ROOT / "build" / "publish-manifest.json"
MANAGE = "https://creator.douyin.com/creator-micro/content/manage?tab=collections"
TITLE = "十二种语言写四季"


def norm(s: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch):
            continue
        if unicodedata.category(ch).startswith(("L", "N")):
            out.append(ch)
    return "".join(out).lower()


def main() -> int:
    tasks = json.loads(MANIFEST.read_text("utf-8"))["douyin"]
    prof = base.profile_dir("douyin")

    with base.launch(prof, viewport={"width": 1700, "height": 1100}) as (ctx, page):
        page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)
        body = page.inner_text("body", timeout=10000)
        page.screenshot(path=str(OUT / "vcol-01-list.png"))

        print("=== 合集列表 ===")
        i = body.find("作品合集")
        print(body[i:i + 300].replace("\n", " | ") if i >= 0 else "（无）")

        if TITLE not in body:
            print(f"\n❌ 列表页找不到合集「{TITLE}」")
            return 1

        # 打开合集编辑页（点合集卡片）
        print(f"\n▶ 打开合集「{TITLE}」")
        card = page.get_by_text(TITLE, exact=False).first
        card.scroll_into_view_if_needed(); time.sleep(1.2)
        card.click()
        time.sleep(6)
        edit = page.inner_text("body", timeout=10000)
        page.screenshot(path=str(OUT / "vcol-02-edit.png"))

        # 合集详情是**懒加载表格**：首屏只有 7 条，必须滚到底再读。
        # ⚠️ 实测（2026-10-08）：只读首屏会得到「中文/希伯来语缺失」的假结论，
        # 而表头「总集数：11集」是对的。**以总集数为准，不以读到的条数为准**。
        chunks = [edit]
        for i in range(12):
            page.mouse.wheel(0, 1400)
            time.sleep(1.3)
            try:
                chunks.append(page.inner_text("body", timeout=8000))
            except Exception:
                pass
        edit = "\n".join(chunks)
        try:
            page.screenshot(path=str(OUT / "vcol-03-bottom.png"))
        except Exception:
            pass

    (OUT / "vcol-text.txt").write_text(edit, "utf-8")
    ne = norm(edit)

    # 权威判据：表头的「总集数：N 集」——它不受懒加载影响
    m = re.search(r"总集数[:：]\s*(\d+)\s*集", edit)
    total = int(m.group(1)) if m else None
    print(f"\n=== 总集数（表头）: {total if total is not None else '未读到'} ===")

    print("=== 合集内作品核验 ===")
    inside, missing = [], []
    for t in tasks:
        nt = norm(t["title"])
        key = nt[:max(6, min(10, len(nt)))]
        hit = key in ne
        print(f"  {'✓' if hit else '✗'} [{t['no']:02d}] {t['lang']:<6} {t['title']}")
        (inside if hit else missing).append(t)
    print(f"\n逐条读到 {len(inside)}/{len(tasks)}；表头总集数 {total}")
    if missing:
        print("未逐条读到：" + "、".join(f"{t['lang']}" for t in missing))
    if total is not None and total == len(tasks):
        print(f"✅ 总集数 {total} == 清单 {len(tasks)}，合集收录完整")
        return 0
    if total is not None:
        print(f"⚠️ 总集数 {total} ≠ 清单 {len(tasks)}，"
              f"确实缺 {len(tasks) - total} 支（以总集数为准）")
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())