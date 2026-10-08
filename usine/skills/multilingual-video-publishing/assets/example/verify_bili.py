# -*- coding: utf-8 -*-
"""verify_bili.py — 回 B 站投稿管理页**只读**核验（不提交任何东西）

脚本自报 `ok=True` 不是证据（2026-10-08 抖音已出现过自报成功、
实际改错对象的案例）。这里一律以**管理页读到的标题**为准，
且用**归一化**比对——抖音/B站都对阿拉伯语/希伯来语做过码位归一，
逐字比对必然假阴性。

⚠️ 只读：只导航 + 滚屏 + 读文本 + 截图，不点任何提交/删除按钮。

用法：
    uv run --group publish python examples/sijijie/verify_bili.py
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

from feuille.publish import base, bilibili          # noqa: E402

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

    with base.launch(prof, viewport={"width": 1600, "height": 1000}) as (ctx, page):
        page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)
        try:
            page.screenshot(path=str(OUT / "vbili-01-list.png"))
        except Exception:
            pass
        chunks = []
        for _ in range(14):
            try:
                chunks.append(page.inner_text("body", timeout=8000))
            except Exception:
                pass
            page.mouse.wheel(0, 2000)
            time.sleep(1.4)
        try:
            page.screenshot(path=str(OUT / "vbili-02-scrolled.png"))
        except Exception:
            pass

    body = "\n".join(chunks)
    (OUT / "vbili-text.txt").write_text(body, "utf-8")
    nb = norm(body)
    print(f"管理页文本 {len(body)} 字（归一 {len(nb)}）")

    m = re.search(r"共\s*(\d+)\s*个稿件", body)
    if m:
        print(f"页面自报：共 {m.group(1)} 个稿件")

    inside, missing = [], []
    for t in tasks:
        nt = norm(t["title"])
        key = nt[:max(6, min(10, len(nt)))]
        hit = key in nb
        print(f"  {'✓' if hit else '✗'} [{t['no']:02d}] {t['lang']:<6} {t['title']}")
        (inside if hit else missing).append(t)
    print(f"\n实际可见 {len(inside)}/{len(tasks)}")
    if missing:
        print("未见于管理页：" + "、".join(
            f"[{t['no']:02d}]{t['lang']}" for t in missing))
        return 1
    print("✅ 12 条全部见于投稿管理页")
    return 0


if __name__ == "__main__":
    sys.exit(main())