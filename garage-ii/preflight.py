#!/usr/bin/env python3
"""preflight.py —— garage-ii 的开跑前自检（dsh 这一格）。

**纪律：自检不花钱。** 所有检查都在任何模型调用之前跑完；任何一条硬检查不过，
这一轮就不许开跑。harness2 上游的 `harness2.preflight` 是给 jb/lab/wb 三格写的
（它硬依赖 opencode 检出与那三格的 runner），对 dsh 这一格不适用——所以这里自己写一套。

五条硬检查，每条都对应一个**真会烧钱或真会静默出错**的坑：

1. **基准 harness 在位且没漂移** —— 漂了就是拿一份过期基准去比，数字没有意义。
2. **执行器就位**（SDK 客户端可解析 + 插件产物已构建）—— 缺一样就是**零工具面**，
   智能体会对着空工具面发 shell，而流程一路绿。
3. **node 在 PATH 上** —— dsh 是 Node 宿主。
4. **run root 在仓库外** —— 这条最隐蔽：dsh 的 project root 是「最近的含 .git 的祖先，
   没有就用 cwd」。run root 要是落在本仓库里，`.dsh/skills` 会被判到**仓库根**去，
   于是候选技能一个都扫不到——**跑得动、跑得对、跑的是错的**。这类故障不报错，
   只会让分数静默塌到基线。

PATH 上的 `dsh` CLI 只做**软**检查：真跑的路径是 SDK 客户端（`dsh_run.mjs`），
CLI 已经不在执行路径上，为它拦下一轮是白花钱。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
THEATRE_II = REPO / "theatre-ii"

#: run root 必须在仓库外。见模块 docstring 的第 4 条。
def _inside_repo(p: Path) -> bool:
    try:
        p.resolve().relative_to(REPO.resolve())
    except ValueError:
        return False
    return True


def check_run_root(run_root: Path) -> list[str]:
    errs: list[str] = []
    try:
        resolved = run_root.resolve()
    except OSError as exc:
        return [f"run root 解析不了：{exc}"]
    if _inside_repo(resolved):
        errs.append(
            f"run root {resolved} 在本仓库内：dsh 的 project root 是「最近的含 .git 的祖先，"
            f"没有就用 cwd」，仓库内的 run root 会让 .dsh/skills 被判到仓库根，"
            f"候选技能一个都扫不到（不报错，只是分数静默塌到基线）。"
            f"把 run root 放到仓库外，例如 {Path.home() / '.cache' / 'usine-h2'}"
        )
    return errs


def check_base_harness() -> list[str]:
    errs: list[str] = []
    script = HERE / "build_base_harness.py"
    if not script.is_file():
        return [f"基准 harness 构建脚本不在 {script}"]
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        errs.append(
            "基准 harness 漂了（它必须与真实 dsh 插件同源）："
            + (proc.stderr or proc.stdout).strip().replace("\n", " / ")
            + f"；修法：python3 {script}"
        )
    return errs


def check_engine() -> list[str]:
    errs: list[str] = []
    if not (THEATRE_II / "harness2" / "__init__.py").is_file():
        errs.append(f"harness2 引擎不在 {THEATRE_II / 'harness2'}")
    if str(THEATRE_II) not in sys.path:
        sys.path.insert(0, str(THEATRE_II))
    try:
        import harness2  # noqa: F401
    except Exception as exc:  # pragma: no cover - 引擎装不上是环境问题
        errs.append(f"harness2 引擎导入失败：{type(exc).__name__}: {exc}")
    return errs


def check_executor() -> tuple[list[str], list[str]]:
    """真正的执行器就位吗。返回 (硬错误, 软警告)。

    **执行器是 SDK 客户端**（`dsh_run.mjs` → `@deepseek-ai/dsh-sdk-client`），
    不是 PATH 上的 `dsh` CLI。这三样缺一样就是**零工具面**——智能体会对着空工具面
    发 shell，而流程一路绿（2026-10-18 真宿主首测实录）。
    """
    errs: list[str] = []
    warns: list[str] = []

    node = shutil.which("node")
    if node is None:
        errs.append("node 不在 PATH 上：dsh 是 Node 宿主，装 Node ≥24（或 ≥22.19）后重试")
        return errs, warns

    sdk = _find_sdk_client()
    if sdk is None:
        errs.append(
            "解析不到 dsh SDK 客户端（@deepseek-ai/dsh-sdk-client）："
            "它住在插件包里，先在 usine 里 `pnpm install`"
        )

    dist = REPO / "usine" / "packages" / "dsh-plugin" / "dist" / "index.mjs"
    if not dist.is_file():
        errs.append(
            f"插件产物不在 {dist}：工具面挂不上去就是零工具面。"
            f"先跑 pnpm --filter @feuille/dsh-plugin build"
        )

    return errs, warns


def _find_sdk_client() -> Path | None:
    """从插件包里解析 SDK 客户端的目录（**不 import**——preflight 不许起任何东西）。"""
    pkg = REPO / "usine" / "packages" / "dsh-plugin" / "package.json"
    if not pkg.is_file():
        return None
    for base in (pkg.parent, pkg.parent / "node_modules"):
        cand = base / "node_modules" / "@deepseek-ai" / "dsh-sdk-client"
        if cand.is_dir():
            return cand
    return None


def check_dsh() -> tuple[list[str], list[str]]:
    """PATH 上的 dsh CLI 还在吗。返回 (硬错误, 软警告)。

    **软检查**：CLI 不再是执行器（真跑走 SDK 客户端）。它在只在手工调试时有用，
    所以它不在就降级成一条提醒，不拦这一轮——拦下来的代价（白跑一轮）比它能防的
    故障大。而真正会烧钱的那几样（插件产物、SDK、provider、模型）都在
    `check_executor()` 与执行器就绪闸里。
    """
    errs: list[str] = []
    warns: list[str] = []
    try:
        from dsh_substrate import dsh_bin
    except Exception as exc:
        return [], [f"dsh_substrate 导入失败：{type(exc).__name__}: {exc}"]

    try:
        argv, source = dsh_bin()
    except RuntimeError as exc:
        return [], [f"PATH 上没有 dsh CLI（不影响开跑，执行器是 SDK 客户端）：{exc}"]

    try:
        proc = subprocess.run(  # noqa: S603
            [*argv, "--help"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warns.append(f"dsh --help 跑不起来（{source}，不影响开跑）：{exc}")
        return errs, warns
    if proc.returncode != 0:
        warns.append(
            f"dsh --help 退出码 {proc.returncode}（{source}，不影响开跑）："
            f"{(proc.stderr or proc.stdout).strip()[:200]}"
        )
    elif "headless" not in (proc.stdout + proc.stderr):
        warns.append(
            f"PATH 上的 dsh（{source}）没有 headless 模式：不影响开跑，"
            f"但它跟你真跑的 SDK 不是同一个版本"
        )

    if not (os.environ.get("DSH_HOME") or (Path.home() / ".dsh")).exists():
        warns.append(
            f"没找到 dsh home（$DSH_HOME 或 ~/.dsh）：profile 会自动初始化，"
            f"首次开跑前先确认 provider 已配好"
        )

    return errs, warns


def run_all(run_root: Path) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []
    errs += check_engine()
    errs += check_base_harness()
    errs += check_run_root(run_root)
    x_errs, x_warns = check_executor()
    errs += x_errs
    warns += x_warns
    d_errs, d_warns = check_dsh()
    errs += d_errs
    warns += d_warns
    return errs, warns


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="run root（默认 ~/.cache/usine-h2）")
    args = ap.parse_args(argv)
    run_root = args.root or Path(os.environ.get("GARAGE_II_RUNS_DIR", Path.home() / ".cache" / "usine-h2"))
    errs, warns = run_all(run_root)
    for w in warns:
        print(f"warn: {w}")
    if errs:
        print("preflight 未通过（这一轮不许开跑）：")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"preflight 全绿：{run_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
