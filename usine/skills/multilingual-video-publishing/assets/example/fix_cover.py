# -*- coding: utf-8 -*-
"""fix_cover.py — 抖音补封面（发布后的编辑流程）

**为什么不一次性补 12 条**：抖音每个作品**最多修改 5 次**，补封面算 1 次。
所以先只筛 1 条验证真的落库（缩略图有文字），确认有效再批量——
额度有限，**不在没验证的路径上烧 12 次**。

用法：
    uv run --group publish python examples/sijijie/fix_cover.py --only 1   # 先验证 1 条
    uv run --group publish python examples/sijijie/fix_cover.py             # 确认有效后补全部
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

from feuille.publish import douyin   # noqa: E402

OUT = ROOT / "build" / "douyin"
MANIFEST = ROOT / "build" / "publish-manifest.json"
# 清空搜索 = 列出全部作品。传 "四季" 搜不到东西——12 条标题里没有一条含它
# （合集面板那轮已实测：传 "四季" 只匹配到 3 条，其余 9 条静默漏掉）。
SEARCH_KW = ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只补这些序号，逗号分隔（如 1,2）")
    ap.add_argument("--lang", help="只补这个语种")
    args = ap.parse_args()

    tasks = json.loads(MANIFEST.read_text("utf-8"))["douyin"]
    if args.only:
        ids = {int(x) for x in args.only.split(",")}
        tasks = [t for t in tasks if t["no"] in ids]
        print(f"只补 {len(tasks)} 条：{sorted(ids)}")
    elif not args.lang:
        print("⚠️ 未指定 --only/--lang，将消耗 12 次修改额度。"
              "建议先 --only 1 验证落库。")

    return douyin.fix_covers(
        tasks, search_kw=SEARCH_KW, log_dir=str(OUT),
        only=args.only, lang=args.lang)


if __name__ == "__main__":
    sys.exit(main())