#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_cli.py — 统一 CLI 的验收与反向验证（P2-3）

**这个统一最危险的失败模式是「漏搬」**：把 8 个入口收成一棵树时，某个子命令没被接进
路由表，症状是**那个功能静默消失**——命令敲下去报「未知命令」，而文档里还写着它。
所以判据是机检的，不靠人眼对齐：

1. `pyproject.toml` 里**每一个** `[project.scripts]` 入口都必须在 `LEGACY_EQUIV` 里有归属；
2. `LEGACY_EQUIV` 的每个等价命令都必须在 `COMMANDS` 路由表里；
3. 路由到的模块必须真的能 import 且有 `main`；
4. **各模块 argparse 里那个位置参数的 `choices` 字面量**必须与路由表声明的子命令集合一致
   （正则抓源码——和 run.ps1 的 ValidateSet↔case 机检同一条纪律）；
5. 错误输入必须非零退出**并说清怎么改**，不能静默成功。

第 4 条是这里最关键的：它是「统一前有什么，统一后就还得有什么」的机械证明。
"""
from __future__ import annotations

import importlib
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usine import cli  # noqa: E402

# 每个模块里「位置参数」的 choices 字面量 → 该模块在新树里对应的 (组, 命令) 集合
POSITIONAL_CHOICES = {
    "usine/intro_cards.py": ("card", "phase", {"tts", "assets", "render"}),
    "usine/char_sheet.py": ("chars", "cmd", {"solo", "sheet", "html", "all"}),
    "usine/scene_video.py": ("scene", "phase", {"tts", "assets", "render", "all", "list"}),
}


def _choices_from_source(rel: str, argname: str) -> set[str] | None:
    """从源码里抓 `add_argument("phase", choices=[...])` 的字面量集合。抓不到返回 None。"""
    src = (ROOT / "src" / rel).read_text("utf-8")
    m = re.search(r'add_argument\(\s*"' + re.escape(argname) + r'"\s*,\s*choices=\[([^\]]*)\]', src)
    if not m:
        return None
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# 统一入口本身；它不是「旧入口」，不该出现在 LEGACY_EQUIV 里
UNIFIED = "usine"

# **分母不许写死**。曾经这里是 `TOTAL = 16`，于是加检查之后「16/16」就成了
# 一句与实际条数无关的话——多加的检查不出现在分母里，少删的检查也不会让它变小。
# 一个会撒谎的分母比没有分母更坏：读的人会以为每条都过了。
def _total(rows) -> int:
    return len(rows)


def check_coverage():
    rows = []
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["scripts"]

    # 统一入口必须真的指向 cli:main，且它自己是唯一的例外
    rows.append((scripts.get(UNIFIED) == "usine.cli:main",
                 f"[project.scripts] 的 `{UNIFIED}` 指向 usine.cli:main"
                 f"（实为 {scripts.get(UNIFIED)!r}）"))
    legacy = {k: v for k, v in scripts.items() if k != UNIFIED}
    missing = sorted(set(legacy) - set(cli.LEGACY_EQUIV))
    rows.append((not missing,
                 f"pyproject 的 {len(legacy)} 个旧 console script 全部有统一树归属"
                 + (f"（漏：{missing}）" if missing else "")))
    stale = sorted(set(cli.LEGACY_EQUIV) - set(legacy))
    rows.append((not stale,
                 f"LEGACY_EQUIV 没有指向已不存在的入口"
                 + (f"（多：{stale}）" if stale else "")))

    orphan = sorted(f"{g} {c}" for pairs in cli.LEGACY_EQUIV.values() for g, c in pairs
                    if (g, c) not in cli.COMMANDS)
    rows.append((not orphan, "LEGACY_EQUIV 的每个等价命令都在路由表里"
                 + (f"（漏：{orphan}）" if orphan else "")))

    bad = []
    for (g, c), (mod, _pre) in sorted(cli.COMMANDS.items()):
        try:
            m = importlib.import_module(mod)
        except Exception as exc:                            # noqa: BLE001
            bad.append(f"{g} {c}:{mod} import 失败 {exc}")
            continue
        if not callable(getattr(m, "main", None)):
            bad.append(f"{g} {c}:{mod} 没有 main()")
    rows.append((not bad, f"{len(cli.COMMANDS)} 个叶子都能路由到可调用的 main()"
                 + (f"（{bad[:2]}）" if bad else "")))

    # 第 4 条：模块里位置参数的 choices 必须与路由表声明的一致
    for rel, (group, _arg, declared) in POSITIONAL_CHOICES.items():
        got = _choices_from_source(rel, _arg)
        routed = {c for (g, c) in cli.COMMANDS if g == group and c in declared}
        ok = got == declared and routed == declared
        rows.append((ok, f"{rel} 的 {group} 子命令集合 = 源码 choices {sorted(got or [])}"
                         f" = 路由表 {sorted(routed)}"))

    # 路由表里不该有「组内声明了集合之外的命令」
    extra = sorted(f"{g} {c}" for (g, c) in cli.COMMANDS
                   if g in {v[0] for v in POSITIONAL_CHOICES.values()}
                   and c not in POSITIONAL_CHOICES[
                       next(rel for rel, v in POSITIONAL_CHOICES.items() if v[0] == g)][2]
                   and c not in ("parse", "validate", "draft"))
    rows.append((not extra, "路由表没有多出源码里不存在的子命令"
                 + (f"（多：{extra}）" if extra else "")))
    return rows


def check_behaviour():
    rows = []

    def run(args, env=None):
        return subprocess.run([sys.executable, "-m", "usine.cli", *args],
                              capture_output=True, text=True, cwd=str(ROOT),
                              env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src"), **(env or {})})

    cases = [
        ("无参数 → 打印用法并非零退出", [], False),
        ("未知组 → 报错并列出可用组", ["nope", "x"], False),
        ("组缺命令 → 报错并列出该组命令", ["card"], False),
        ("未知命令 → 报错并列出该组命令", ["card", "explode"], False),
    ]
    for desc, args, _ in cases:
        r = run(args)
        rows.append((r.returncode != 0 and ("用法" in r.stdout + r.stderr
                                            or "可用" in r.stdout + r.stderr),
                     f"{desc}（rc={r.returncode}）"))

    # 端到端：两个真命令必须真的跑通
    r1 = run(["scene", "validate", "--scene", "numbers"])
    rows.append((r1.returncode == 0 and "PASS" in r1.stdout,
                 f"usine scene validate --scene numbers 跑通（rc={r1.returncode}）"))
    r2 = run(["ledger", "status"])
    rows.append((r2.returncode in (0, 1) and "缓存账本" in r2.stdout,
                 f"usine ledger status 跑通（rc={r2.returncode}）"))
    r3 = run(["scene", "parse", "--list"])
    rows.append((r3.returncode == 0 and "numbers" in r3.stdout,
                 f"usine scene parse --list 跑通且列出新课（rc={r3.returncode}）"))
    # publish 组的 build 会覆写台账，测试里只跑只读的 check/analyze
    r4 = run(["publish", "analyze"])
    rows.append((r4.returncode == 0 and "发布回流分析" in r4.stdout,
                 f"usine publish analyze 跑通（rc={r4.returncode}，只读，不覆写台账）"))
    return rows


def main():
    print("=" * 70)
    print("P2-3 统一 CLI：旧入口的每个子命令都还在吗？")
    print("=" * 70)
    fails = 0
    rows = check_coverage() + check_behaviour()
    for ok, msg in rows:
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok
    print("=" * 70)
    print(f"{'OK' if not fails else 'FAIL'}：统一 CLI {len(rows) - fails}/{_total(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
