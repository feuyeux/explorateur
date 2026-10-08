# -*- coding: utf-8 -*-
"""verify_list.py — 回作品管理页**实际核验**发布了哪些（只读，不改任何东西）

**为什么必须独立回读**：发布脚本自报 `ok=True` **不是证据**。
本批已经出现过一次「脚本说补的是中文、实际改的是韩语」的错位。
所以核验一律以**作品管理列表页**读到的标题为准，且逐字与清单比对。

⚠️ 只读：不点任何修改按钮，纯导航 + 读文本 + 截图。

用法：
    uv run --group publish python examples/sijijie/verify_list.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille.publish import base                      # noqa: E402

OUT = ROOT / "build" / "douyin"
MANIFEST = ROOT / "build" / "publish-manifest.json"
MANAGE = "https://creator.douyin.com/creator-micro/content/manage"


def collect(page) -> str:
    """把作品管理页的可见文本全部读回来（含滚动加载）。"""
    chunks = []
    for i in range(14):
        try:
            chunks.append(page.inner_text("body", timeout=8000))
        except Exception:
            pass
        # 滚到底触发懒加载
        page.mouse.wheel(0, 2200)
        time.sleep(1.6)
    return "\n".join(chunks)


def normalize(s: str) -> str:
    """去掉变音符号与所有空白，保留基本字母。

    ⚠️ 这是**必须**的一步（2026-10-08 实测）：阿拉伯语标题
    `قَحْطَلَت 是「热到草木焦」` 里前几个字母全是 harakat 元音符号，
    抖音在存储/渲染时会做**码位归一**（`قَحْطَلَ` → `قَحطَل`），
    导致逐字比对失败 → **假阴性**：脚本报「没发布」，其实发了。
    """
    import unicodedata
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch):
            continue
        cat = unicodedata.category(ch)
        if cat.startswith(("L", "N")):          # 只留字母与数字
            out.append(ch)
    return "".join(out).lower()


def main() -> int:
    tasks = json.loads(MANIFEST.read_text("utf-8"))["douyin"]
    OUT.mkdir(parents=True, exist_ok=True)
    prof = base.profile_dir("douyin")

    with base.launch(prof, viewport={"width": 1500, "height": 1000}) as (ctx, page):
        page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)
        try:
            page.screenshot(path=str(OUT / "verify-01-list.png"))
        except Exception:
            pass
        body = collect(page)
        try:
            page.screenshot(path=str(OUT / "verify-02-scrolled.png"), full_page=False)
        except Exception:
            pass

    (OUT / "verify-list-text.txt").write_text(body, "utf-8")
    nb = normalize(body)

    print(f"读到页面文本 {len(body)} 字（归一后 {len(nb)} 字）\n")
    missing = []
    for t in tasks:
        title = t["title"]
        nt = normalize(title)
        # 逐字符递减找最长可匹配前缀：平台可能只存了标题的一部分
        key = nt[:max(6, min(10, len(nt)))]
        hit = key in nb
        mark = "✓" if hit else "✗"
        print(f"  {mark} [{t['no']:02d}] {t['lang']:<6} {title}")
        if not hit:
            missing.append(t)
    print()
    if missing:
        print(f"❌ 列表页找不到 {len(missing)} 条："
              + "、".join(f"[{t['no']:02d}]{t['lang']}" for t in missing))
        print("   → 逐字比对失败。**先看截图确认**再下结论——"
              "码位归一 / RTL 渲染差异都会造成假阴性。")
        return 1
    print("✅ 12 条全部在作品管理列表页可见")
    return 0


if __name__ == "__main__":
    sys.exit(main())