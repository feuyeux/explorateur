# -*- coding: utf-8 -*-
"""go_douyin.py — 抖音发布 + 建合集 + 补挂（⑨⑩）

顺序**不能换**（手册 §4.1）：

    1. 先发 12 条视频（合集创建页只列「已发布作品」，空的时候没法挂）
    2. 再建合集并挂这 12 条

`collections.create_collection(want=12)` 一次做完建集 + 挂作品——
所以不是「先建空集再逐条勾」，而是发完后建集时直接选中这 12 支。

⚠️ 登录与风控一律人工（纪律 21）：本脚本只等待、绝不代填扫码/验证码。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille.publish import base, collections, douyin   # noqa: E402

OUT = ROOT / "build" / "douyin"
MANIFEST = ROOT / "build" / "publish-manifest.json"

COLLECTION_TITLE = "十二种语言写四季"
COLLECTION_DESC = (
    "同一个四季，十二种语言各写一遍。中文七字、俄语一个动词、法语一颗星，"
    "希伯来语来自诗篇，印地语把大地写成了要盖被子的地方。"
    "每支 20 秒，竖屏，配音是该语言自己的声音。"
)
# 搜索合集时要匹配的关键词（合集内作品选择面板用）
SEARCH_KW = "四季"


def main() -> int:
    tasks = json.loads(MANIFEST.read_text("utf-8"))["douyin"]
    OUT.mkdir(parents=True, exist_ok=True)
    prof = base.profile_dir("douyin")
    print(f"抖音任务 {len(tasks)} 条 · profile {prof}")

    with base.launch(prof, viewport={"width": 1440, "height": 900}) as (ctx, page):
        if not douyin.ensure_login(page):
            print("❌ 未登录/未就绪，停止")
            return 1
        print("✅ 抖音创作者后台就绪\n")

        # ---- 1. 发布 12 条 ----
        results = base.run_tasks(
            page, tasks, douyin.publish_one,
            upload_url=douyin.UPLOAD_URL, log_dir=OUT, between_s=3,
            result_json="publish-douyin-result.json")
        rc = base.summarize(results, "抖音")
        print(f"\n发布阶段退出码 {rc}")

        # ---- 2. 建合集并挂作品 ----
        print("\n▶ 建合集 + 挂作品")
        collections.create_collection(
            page, title=COLLECTION_TITLE, desc=COLLECTION_DESC,
            cover=str(ROOT / "封面" / "13_竖版_中文.png"),
            want=len(tasks), search_kw=SEARCH_KW, out_dir=OUT)
    return rc


if __name__ == "__main__":
    sys.exit(main())