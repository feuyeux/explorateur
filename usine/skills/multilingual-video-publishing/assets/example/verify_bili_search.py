# -*- coding: utf-8 -*-
"""verify_bili_search.py — 用**搜索框**逐条核验（比滚屏可靠得多）

**为什么要换方法**：管理页是懒加载 + 分页，靠滚屏读全文会**漏**——
实测两次核验分别报「缺中文/日语」和「缺中文/德语」，而同一批稿件
时间戳是连续的（说明稿件都在，是读取边界在飘）。

搜索框是**服务端过滤**，输入标题片段就只返回匹配项，
不依赖客户端渲染完整——这是这里唯一可靠的判据。

⚠️ 只读：只往搜索框打字，不点任何提交/删除。

用法：
    uv run --group publish python examples/sijijie/verify_bili_search.py
"""
from __future__ import annotations

import json
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

OUT = ROOT / "build" / "bilibili"
MANIFEST = ROOT / "build" / "publish-manifest.json"
MANAGE = "https://member.bilibili.com/platform/upload-manager/article"


def norm(s: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch):
            continue
        if unicodedata.category(ch).startswith(("L", "N")):
            out.append(ch)
    return "".join(out).lower()


def main() -> int:
    tasks = json.loads(MANIFEST.read_text("utf-8"))["bilibili"]
    OUT.mkdir(parents=True, exist_ok=True)
    prof = base.profile_dir("bilibili")
    missing = []

    with base.launch(prof, viewport={"width": 1600, "height": 1000}) as (ctx, page):
        page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(9)
        box = page.locator("input[placeholder*='搜索稿件'], input[type='search']").first
        box.click()

        for t in tasks:
            # 用标题里最稳的一段：去掉标点后取前 6 个字母/汉字
            key = norm(t["title"])[:6]
            try:
                box.fill(key)
                box.press("Enter")
            except Exception:
                box.fill(key)
                page.keyboard.press("Enter")
            time.sleep(3.6)
            txt = page.inner_text("body", timeout=8000)
            hit = key in norm(txt)
            mark = "✓" if hit else "✗"
            print(f"  {mark} [{t['no']:02d}] {t['lang']:<6} {t['title']}")
            if not hit:
                missing.append(t)
            page.screenshot(path=str(OUT / f"vsearch-{t['no']:02d}.png"))

    print(f"\n搜索命中 {len(tasks) - len(missing)}/{len(tasks)}")
    if missing:
        print("搜索不到：" + "、".join(f"[{t['no']:02d}]{t['lang']}" for t in missing))
        return 1
    print("✅ 12 条全部能用搜索命中 → 稿件确实都在后台")
    return 0


if __name__ == "__main__":
    sys.exit(main())