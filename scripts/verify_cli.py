#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_cli.py — 统一入口路由表的反向验证（explorateur verify_cli.py 体例）

**它要证的那句话**：「路由表里的每个叶子都真的可达。」
统一时漏搬一个子命令，它就静默消失——直到有人在旧入口找不到功能。

判据：
1. 每个路由条目的目标模块可 import、目标函数存在（叶子可达）
2. 未知命令 → 退出码 2（不静默）
3. --help → 退出码 0
4. verify 桥：`feuille verify --list` → 退出码 0（子进程链路通）
"""
from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import cli                        # noqa: E402


def check():
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：每个叶子可达 ----
    missing = []
    for (grp, cmd), (module_name, func) in sorted(cli.COMMANDS.items()):
        try:
            mod = importlib.import_module(module_name)
            if not hasattr(mod, func):
                missing.append(f"{grp} {cmd} → {module_name}.{func} 函数不存在")
        except ImportError as e:
            missing.append(f"{grp} {cmd} → {module_name} 不可导入（{type(e).__name__}）")
    rows.append((not missing,
                 f"路由表 {len(cli.COMMANDS)} 个叶子全部可达"
                 + (f"　**{missing[:2]}**" if missing else "")))

    # ---- 1. CLI 可执行：--help / 未知命令 / verify 桥 ----
    r = subprocess.run(["uv", "run", "feuille", "--help"],
                       capture_output=True, text=True, cwd=str(ROOT))
    rows.append((r.returncode == 0 and "可用命令" in r.stdout,
                 "--help → 退出码 0 且打印命令表"))

    r = subprocess.run(["uv", "run", "feuille", "bogus", "bogus"],
                       capture_output=True, text=True, cwd=str(ROOT))
    rows.append((r.returncode == 2 and "未知命令" in r.stdout,
                 "未知命令 → 退出码 2（不静默）"))

    r = subprocess.run(["uv", "run", "feuille", "verify", "--list"],
                       capture_output=True, text=True, cwd=str(ROOT))
    rows.append((r.returncode == 0 and "platform" in r.stdout,
                 "verify 桥 → --list 退出码 0（子进程链路通）"))

    r = subprocess.run(["uv", "run", "feuille", "verify", "--only", "platform"],
                       capture_output=True, text=True, cwd=str(ROOT))
    rows.append((r.returncode == 0 and "OK" in r.stdout,
                 "verify 桥 → --only 一套 → 退出码 0"))

    # ---- 2. verify_probes 的 SUITES 与实际脚本一致 ----
    sys.path.insert(0, str(ROOT / "scripts"))
    import verify_probes as vp
    gone = [name for name, (script, _) in vp.SUITES.items()
            if not (ROOT / "scripts" / script).exists()]
    rows.append((not gone,
                 f"聚合器 {len(vp.SUITES)} 套全部对应真实脚本"
                 + (f"　**缺 {gone}**" if gone else "")))
    orphan = [p.name for p in (ROOT / "scripts").glob("verify_*.py")
              if p.name != "verify_probes.py"
              and not any(s == p.name for s, _ in vp.SUITES.values())]
    rows.append((not orphan,
                 f"scripts/ 下没有游离的 verify_*.py（全部被聚合器管住）"
                 + (f"　**游离 {orphan}**" if orphan else "")))
    return rows


def main() -> int:
    print("=" * 72)
    print("统一入口路由表 + 反向验证聚合器")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：CLI 路由 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
