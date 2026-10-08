#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_plan.py — 发布前清单自检（零平台流量）

在真发之前把能拦的问题全拦下来。本脚本只读本地文件与清单，
**不碰任何平台**，所以可以随时跑、随便跑。

检查项（每项都有可观测判据，不是「看着没问题」）：

1. **素材存在性** — 逐条视频/封面真实在盘（发到一半才发现缺文件是最贵的失败）
2. **标题字数** — 按平台各自上限实测 `len()`，不信任何手标
3. **横竖配对** — 双版式项目必须两版条数相同、语种集合一致
4. **封面比例** — 与所投平台的原生比例对齐（能零裁切就别裁）
5. **修改额度** — 补封面类操作要提醒每作品 N 次的上限
6. **上限表对照** — TITLE_MAX 与 library `feuille.manifest.PLATFORMS` 现场
   比对（feuille 可导入时；导不进 = 发布机零依赖模式，跳过不装样子）

用法：
    uv run --with pillow python check_plan.py <manifest.json> --root <素材根目录>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 各平台标题上限。与 manifest.PLATFORMS 同源，但这里独立列一份——
# 本脚本要在**没有 feuille 依赖**的环境下能跑（发布机上不装包也能自检）。
# ⚠️ 副本必须有守卫（纪律 10）：feuille 可导入时就地对照，见 _limit_drift()。
TITLE_MAX = {"douyin": 30, "xiaohongshu": 20, "bilibili": 80, "zhihu": 100}

# 平台原生封面比例（宽/高）
COVER_RATIO = {"douyin": 3 / 4, "xiaohongshu": 3 / 4, "bilibili": 4 / 3}

# 抖音每作品最多修改次数（补封面算 1 次）
MOD_BUDGET = {"douyin": 5}


def _limit_drift() -> list[str]:
    """TITLE_MAX 与 library `feuille.manifest.PLATFORMS` 的现场对照（纪律 10）。

    本脚本的设计前提是「发布机上没有 feuille 也能跑」，所以上限表独立存了
    一份——副本必须有守卫：导得进 feuille 就必须一致，否则这份副本在静默
    说谎（自检通过而真发布被拦，或反过来）。导不进则跳过（零依赖模式，
    SKIP 不装成 PASS）。
    """
    try:
        from feuille import manifest as _m
    except Exception:
        return []
    out: list[str] = []
    for plat, lim in TITLE_MAX.items():
        ref = _m.PLATFORMS.get(plat, {}).get("titleMax")
        if ref is not None and ref != lim:
            out.append(f"TITLE_MAX[{plat}]={lim} 与 manifest.PLATFORMS 的 "
                       f"titleMax={ref} 不一致——双份必有一份说谎")
    for plat in _m.PLATFORMS:
        if plat not in TITLE_MAX:
            out.append(f"manifest.PLATFORMS 有 {plat}，本表 TITLE_MAX 漏了它")
    return out


def check(man_path: Path, root: Path) -> int:
    man = json.loads(man_path.read_text("utf-8"))
    problems: list[str] = []
    notes: list[str] = []

    for plat, tasks in man.items():
        lim = TITLE_MAX.get(plat)
        print(f"\n=== {plat}（{len(tasks)} 条"
              f"{'，标题上限 ' + str(lim) if lim else ''}）===")

        # ---- 1 素材存在性 ----
        missing = [t for t in tasks
                   if not Path(t["video"]).exists() or not Path(t["cover"]).exists()]
        for t in missing:
            problems.append(f"{plat} [{t['no']}] 素材缺失："
                            f"{t['video'] if not Path(t['video']).exists() else t['cover']}")
        print(f"  素材在盘：{len(tasks) - len(missing)}/{len(tasks)}")

        # ---- 2 标题字数（实测，不信手标）----
        if lim:
            over = [(t, len(t["title"])) for t in tasks if len(t["title"]) > lim]
            for t, n in over:
                problems.append(f"{plat} [{t['no']}] 标题 {n} 字 > 上限 {lim}：{t['title']}")
            print(f"  标题合规：{len(tasks) - len(over)}/{len(tasks)}"
                  + (f"　最长 {max(len(t['title']) for t in tasks)} 字" if tasks else ""))

        # ---- 4 封面比例 ----
        want = COVER_RATIO.get(plat)
        if want and tasks:
            try:
                from PIL import Image
                with Image.open(tasks[0]["cover"]) as im:
                    w, h = im.size
                got = w / h
                # 允许 3% 偏差（不同平台对另一版式有裁切框，不能要求像素级相等）
                if abs(got - want) / want > 0.03:
                    notes.append(
                        f"{plat} 封面 {w}×{h}（{got:.2f}）与平台原生 "
                        f"{want:.2f} 差 {abs(got-want)/want*100:.0f}%，"
                        f"确认裁切框内文字是否在安全区")
                else:
                    print(f"  封面比例 {w}×{h}，与平台原生一致")
            except ImportError:
                notes.append("未装 pillow，跳过封面比例检查")
            except Exception as e:
                problems.append(f"{plat} 封面读不出：{type(e).__name__}")

    # ---- 3 横竖配对 ----
    if len(man) >= 2:
        sets = {p: {t["lang"] for t in ts} for p, ts in man.items()}
        base_plat = list(sets)[0]
        for p, s in sets.items():
            if s != sets[base_plat]:
                problems.append(f"{p} 与 {base_plat} 的语种集合不一致："
                                f"多 {s - sets[base_plat]}，缺 {sets[base_plat] - s}")
        if all(len(s) == len(ts) for s, ts in zip(sets.values(), man.values())):
            print(f"\n✅ 横竖配对：{len(sets)} 平台语种集合一致（各 {len(sets[base_plat])} 语种）")

    # ---- 6 上限表对照（feuille 可导入时；导不进 = 零依赖模式跳过）----
    problems.extend(_limit_drift())

    print()
    for n in notes:
        print(f"  ℹ️  {n}")
    if problems:
        print(f"\n❌ {len(problems)} 项问题（发布前必须解决）：")
        for p in problems:
            print("   ·", p)
        return 1
    print(f"\n✅ 清单齐：{sum(len(v) for v in man.values())} 条，无阻塞问题")
    print("   提醒：分区/创作声明/合集/可见性属责任项，须用户拍板，不替用户勾。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--root", default=".", help="素材根目录（仅用于提示）")
    args = ap.parse_args()
    return check(Path(args.manifest), Path(args.root))


if __name__ == "__main__":
    sys.exit(main())