# -*- coding: utf-8 -*-
"""go_bilibili.py — B 站批量投稿 12 条横版

**本批不建合集**：B 站合集需创作中心 Lv2，等级不够时编辑页是灰字、
无可点控件，合集管理页 404 或重定向（`collections.py` 头注）。
**做不到就如实说，不绕。**

分区与创作声明沿用用户在2026-10-06 拍板的值（`bilibili.BILI_ZONE` /
`BILI_STMT_REQUIRED`），本脚本不私自改——那是责任项。

用法：
    uv run --group publish python examples/sijijie/go_bilibili.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille.publish import bilibili      # noqa: E402

OUT = ROOT / "build" / "bilibili"
MANIFEST = ROOT / "build" / "publish-manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只发这些序号，逗号分隔（如 11）")
    args = ap.parse_args()

    tasks = json.loads(MANIFEST.read_text("utf-8"))["bilibili"]
    if args.only:
        ids = {int(x) for x in args.only.split(",")}
        tasks = [t for t in tasks if t["no"] in ids]
        print(f"只发 {len(tasks)} 条：{sorted(ids)}")
        if not tasks:
            print("❌ 筛选后为空，停止（不静默跑 0 条）")
            return 2

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"B 站任务 {len(tasks)} 条")
    print(f"  分区={bilibili.BILI_ZONE}  创作声明={bilibili.BILI_STMT_REQUIRED[0]}")
    print(f"  封面用 4:3 专用版（封面_bili/）——3:4 会被平台裁掉标题\n")
    # subs_dir 指向本项目 subtitles/；不存在就如实跳过，不编路径
    subs = ROOT / "subtitles"
    rc = bilibili.publish(
        tasks, log_dir=str(OUT), subs_dir=str(subs) if subs.exists() else None)
    if rc == 0:
        print("\n⚠️ 脚本自报成功不是证据——跑只读核验：")
        print("   uv run --group publish python examples/sijijie/verify_bili.py")
    return rc


if __name__ == "__main__":
    sys.exit(main())