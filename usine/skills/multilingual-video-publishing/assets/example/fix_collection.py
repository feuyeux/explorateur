# -*- coding: utf-8 -*-
"""fix_collection.py — 抖音合集补挂（合集已建好，但首次创建时挂作品失败）

**为什么分两步**：`create_collection(want=12)` 建集时挂作品失败（面板返回空，
`待加=0`），合集建成但**是空的**。手册坑 1.2 记过这个：作品面板会被服务端
错误清空，**空列表 ≠ 做完**——所以必须回编辑页补挂并核对计数。

⚠️ `fix_collection` 计数不符就**不点保存**（修改类操作的保守默认，纪律 15/19），
所以「失败」是安全失败，不会把合集改成更糟的状态。

用法：
    uv run --group publish python examples/sijijie/fix_collection.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille.publish import base, collections      # noqa: E402

OUT = ROOT / "build" / "douyin"
TITLE = "十二种语言写四季"
# 传空串 = **清空搜索**、让面板列出全部作品。
# ⚠️ 原来传 "四季" 只搜到 3 条（12 条标题里只有 3 条含「四季」），
# 其余 9 条永远搜不出来——静默漏挂。现在靠 JS_PLUS 的「未添加即返回」
# + 数量核对来保证 12 条都挂上。
SEARCH_KW = ""
WANT = 12


def main() -> int:
    prof = base.profile_dir("douyin")
    with base.launch(prof, viewport={"width": 1700, "height": 1100}) as (ctx, page):
        log = collections.fix_collection(
            page, title=TITLE, want=WANT, search_kw=SEARCH_KW, out_dir=OUT)
    ok = log.get("ok_count")
    print(f"\n合集「{TITLE}」内作品 = {ok}（预期 {WANT}）")
    if ok != WANT:
        print("⚠️计数不符，脚本未点保存。现场截图留在 build/douyin/，请人工核对。")
        return 1
    print("✅ 计数达标，已保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())