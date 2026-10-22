#!/usr/bin/env python3
"""preflight.py —— garage-ii 的开跑前自检（dsh 这一格）。

**纪律：自检不花钱。** 所有检查都在任何模型调用之前跑完；任何一条硬检查不过，
这一轮就不许开跑。harness2 上游的 `harness2.preflight` 是给 jb/lab/wb 三格写的
（它硬依赖 opencode 检出与那三格的 runner），对 dsh 这一格不适用——所以这里自己写一套。

七条硬检查，每条都对应一个**真会烧钱或真会静默出错**的坑：

1. **基准 harness 在位且没漂移** —— 漂了就是拿一份过期基准去比，数字没有意义。
2. **执行器就位**（SDK 客户端可解析 + 插件产物已构建）—— 缺一样就是**零工具面**，
   智能体会对着空工具面发 shell，而流程一路绿。
3. **node 在 PATH 上** —— dsh 是 Node 宿主。
4. **run root 在仓库外** —— 这条最隐蔽：dsh 的 project root 是「最近的含 .git 的祖先，
   没有就用 cwd」。run root 要是落在本仓库里，`.dsh/skills` 会被判到**仓库根**去，
   于是候选技能一个都扫不到——**跑得动、跑得对、跑的是错的**。这类故障不报错，
   只会让分数静默塌到基线。
5. **装出来的工作区里技能资源在位**（2026-10-20 加）—— 手册写着
   「copy `assets/template/poster_src.html`」，那一行只有在文件在盘上时才可执行。
   少了它，智能体会（正确地）判定「不可验收」而停手——那一格量的是**工作区完整
   与否**，不是 harness 的好坏。
6. **`feuille` CLI 在位**（2026-10-20 加）—— 手册通篇写 `feuille poster …`；
   PATH 上找不到它，智能体会判定「工具面没有包」而停手。真实产线里它在 PATH 上。
7. **引擎 summary 写入的 flock 在本平台可跑**（2026-10-21 加）—— 引擎写
   `summary.json` 用 `fcntl.flock`（POSIX 专属）。Windows 上没有这层垫的话，
   rollout 真跑完了也**落不了盘**：12 格白烧约两小时才暴露（2026-10-21 实测）。

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

#: 默认 run root：**仓库外**、且与 RSIAgent 线路分开（AGENTS.md「运行产物落位」）。
#:   RSIAgent（théâtre + garage）      → <explorateur 的同级>/garage-result
#:   harness2（theatre-ii + garage-ii） → <explorateur 的同级>/garage-ii-result
#: 仓库外是硬约束（见模块 docstring 第 4 条）；分线落位是硬约束——两线的读数
#: 必须能分开翻账。`GARAGE_II_RUNS_DIR` 可覆盖（同一台机器上分线跑批时用）。
DEFAULT_ROOT = Path(os.environ.get(
    "GARAGE_II_RUNS_DIR", str(REPO.parent / "garage-ii-result")))

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
            f"把 run root 放到仓库外，例如 {DEFAULT_ROOT}"
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

    # **两条分支的类型必须一致**。`os.environ.get(...)` 返回 `str | None`，而
    # `Path.home() / ".dsh"` 是 `Path`——写成一个 `or` 表达式时，只要环境变量被设置，
    # 整个表达式就是 `str`，后面那句 `.exists()` 当场 `AttributeError`。
    #
    # 2026-10-21 实测：`DSH_HOME` 一旦设在环境里，**整个 preflight 崩掉**。
    # 这不是「警告没打出来」，是门禁本身挂死——而 preflight 是开跑前的唯一一道闸，
    # 它崩了等于没有闸。所以这里先统一成 Path 再判。
    dsh_home = Path(os.environ["DSH_HOME"]) if os.environ.get("DSH_HOME") else (Path.home() / ".dsh")
    if not dsh_home.exists():
        warns.append(
            f"没找到 dsh home（$DSH_HOME 或 ~/.dsh）：profile 会自动初始化，"
            f"首次开跑前先确认 provider 已配好"
        )

    return errs, warns


def check_workspace_assets() -> list[str]:
    """**装出来的工作区**里，技能手册引用的资源必须真的在盘上。

    为什么单独一条：2026-10-20 实测，基准树只搬了 `SKILL.md`，`assets/` 与
    `references/` 全丢。工作区里的手册指向不存在的模板，智能体于是（正确地）判定
    「工具面之外没有验收口径」而停手——那一格的分数量的是**工作区完整与否**，
    不是 harness 的好坏。源在不在（`check_base_harness`）与装得对不对是两回事。

    这一条**只装配、不跑模型**：装配是本地文件操作，不花钱。
    """
    errs: list[str] = []
    try:
        sys.path.insert(0, str(HERE))
        if str(THEATRE_II) not in sys.path:
            sys.path.insert(0, str(THEATRE_II))
        from dsh_substrate import DshSubstrate, SKILL_ASSET_DIR, DSH_SKILL_SUBDIR
        import dsh_surface

        dsh_surface.register()
        base = HERE / "harness_base"
        if not base.is_dir():
            return [f"基准 harness 树不在 {base}"]

        class _Spec:
            runs_root = Path("/nonexistent")

        inst = DshSubstrate().materialise(base, _Spec(), {})
        try:
            staged = inst.staging_dir
            for name in sorted(p.name for p in SKILL_ASSET_DIR.iterdir() if p.is_dir()):
                src = SKILL_ASSET_DIR / name
                if not (src / "SKILL.md").is_file():
                    continue
                dst = staged / DSH_SKILL_SUBDIR / name
                if not dst.is_dir():
                    errs.append(f"技能 `{name}` 没装进 {DSH_SKILL_SUBDIR}/")
                    continue
                for asset in sorted(src.rglob("*")):
                    if not asset.is_file():
                        continue
                    rel = asset.relative_to(src)
                    if rel.name == "SKILL.md" or "__pycache__" in rel.parts:
                        continue
                    if rel.name == ".DS_Store":
                        continue
                    if not (dst / rel).is_file():
                        errs.append(f"技能 `{name}` 的资源 `{rel}` 没装进工作区")
        finally:
            shutil.rmtree(inst.staging_dir, ignore_errors=True)
    except Exception as exc:  # pragma: no cover - 装配失败是环境问题
        errs.append(f"工作区装配自检跑不起来：{type(exc).__name__}: {exc}")
    return errs


def check_feuille_cli() -> list[str]:
    """`feuille` 必须在工作区的 PATH 上。

    技能手册通篇写的是 `feuille poster fetch-fonts …`；PATH 上找不到它，智能体就会
    判定「工具面没有包」而停手（2026-10-20 实测）。真实产线里它在 PATH 上
    （pnpm workspace），基准工作区不该比真实产线更差。
    """
    cli = REPO / "usine" / "packages" / "cli" / "bin" / "feuille.js"
    if not cli.is_file():
        return [f"feuille CLI 不在 {cli}：工作区里技能手册写的产线命令跑不通"]
    if shutil.which("node") is None:
        return []  # node 缺失由 check_executor 报
    return []


def check_platform_compat() -> list[str]:
    """引擎写 `summary.json` 用的 `fcntl.flock` 在本平台必须真的能跑。

    为什么单独一条：2026-10-21 实测，Windows 宿主上 `--split both` 的 train 段
    12 格 rollout **真跑了约两小时**（base1/agg1/inv1/dom1 全部完成、事件流全程
    落盘），每一格最后死在 `_write_summary` 的 `import fcntl` 上——fcntl 是
    POSIX 专属模块。12 格全部作废、token 白烧，而当时 preflight 是绿的：这条
    检查不存在。引擎是零补丁 vendored fork，平台差由桥接层垫
    （`garage-ii/posix_compat.py`；POSIX 上恒不装、不顶 stdlib）。

    **走真实路径**：不是只 `import fcntl`，而是真锁一个临时文件再解锁——
    与 `_write_summary` 的调用形状一致（同一个文件对象、LOCK_EX → LOCK_UN）。
    """
    errs: list[str] = []
    try:
        sys.path.insert(0, str(HERE))
        import posix_compat

        posix_compat.install()
        import fcntl
        import tempfile

        probe = Path(tempfile.mkdtemp(prefix="fcntl-probe-")) / "summary.lock"
        with open(probe, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            fcntl.flock(lf, fcntl.LOCK_UN)
        shutil.rmtree(probe.parent, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001 - 平台差是环境问题，报出来让人修
        errs.append(
            f"引擎 summary 写入的 flock 在本平台跑不起来：{type(exc).__name__}: {exc}。"
            "Windows 上由 garage-ii/posix_compat.py 垫（import posix_compat 后调 install()）；"
            "POSIX 上 fcntl 是 stdlib，跑不起来说明 Python 安装有问题"
        )
    return errs


def run_all(run_root: Path) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []
    errs += check_engine()
    errs += check_base_harness()
    errs += check_workspace_assets()
    errs += check_feuille_cli()
    errs += check_platform_compat()
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
    ap.add_argument("--root", type=Path, default=None,
                    help=f"run root（默认 {DEFAULT_ROOT}）")
    args = ap.parse_args(argv)
    run_root = args.root or DEFAULT_ROOT
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
