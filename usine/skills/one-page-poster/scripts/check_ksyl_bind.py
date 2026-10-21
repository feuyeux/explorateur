#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_ksyl_bind.py — 韩语色块类名/选择器咬合门（技能层，AGENTS.md 纪律 23）

事故回顾（nine-arts，2026-10-13）：生成器出的小写 `k%04x` 类名与
measure_korean.py 的大写 `k%04X` 选择器整批失配——CSS 类名大小写敏感，
韩语大字从第一版起就没着色；而 measure 自带的 verify 在自己的 build 里
大小写一致（0 错像素假阴性），verify_colors 只查格内颜色存在性（图例 ■
就能喂饱它）。这类「生成端 ↔ 实测端」的字面咬合，产线各环节自己都测不出
——本脚本把这道门做成技能层判据，任何实例管线直接调用。

判据（全部二值，违反即非零退出）：
  1. CSS 里至少有一个 `.k…` 选择器（空 CSS = 实测没跑，直接 FAIL）；
  2. 每个 HTML 文件里每个 `class="ksyl X"` 的 X，必须在 CSS 里有**同大小写**
     的选择器；
  3. `class="ksyl"` 后面必须跟色块类名（裸 ksyl = 生成器没打类，FAIL）。

用法：
  check_ksyl_bind.py <korean.css> <html> [<html> ...]

退出码：0 = 咬合；1 = 失配（stderr 列出全部问题）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def selectors_of(css_text: str) -> set[str]:
    """CSS 里全部选择器名（`^\\.NAME {` 行首规则块；与 awk 过滤同一口径）。"""
    return set(re.findall(r"(?m)^\.(\S+?)\s*\{", css_text))


def ksyl_classes_of(html_text: str) -> list[tuple[str, str | None]]:
    """HTML 里逐个 ksyl 用点：返回 [(文件内序号或类名, 色块类名或 None)]。
    ksyl 后面的 token 是它的色块类名（生成端约定：class="ksyl kXXXX"）。
    """
    out = []
    for m in re.finditer(r'class="([^"]*)"', html_text):
        toks = m.group(1).split()
        for i, t in enumerate(toks):
            if t == "ksyl":
                out.append((m.group(1), toks[i + 1] if i + 1 < len(toks) else None))
    return out


def check(css: Path, htmls: list[Path]) -> list[str]:
    problems: list[str] = []
    sels = selectors_of(css.read_text(encoding="utf-8"))
    if not sels:
        problems.append(f"{css}: 没有任何 ^\\.k 选择器——韩语实测没跑或 CSS 为空")
        return problems
    for h in htmls:
        text = h.read_text(encoding="utf-8")
        uses = ksyl_classes_of(text)
        if not uses:
            continue  # 本文件没有韩语色块（如只有视频不含 ko 场景），不算错
        for attr, cls in uses:
            if cls is None:
                problems.append(f'{h}: class="{attr}" —— ksyl 裸用，生成器没打色块类名')
            elif cls not in sels:
                problems.append(f"{h}: class {cls!r} 在 {css.name} 里无同大小写选择器"
                                 f"（大小写敏感；检查生成端 k%04X 与实测端 k%04X）")
    return problems


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    css, htmls = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
    problems = check(css, htmls)
    if problems:
        print("韩语色块类名/选择器咬合 FAIL：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    n = sum(len(ksyl_classes_of(h.read_text(encoding="utf-8"))) for h in htmls)
    print(f"韩语色块类名/选择器咬合 OK（{len(selectors_of(css.read_text(encoding='utf-8'))) }"
          f" selectors / {n} ksyl 用点）")


if __name__ == "__main__":
    main()
