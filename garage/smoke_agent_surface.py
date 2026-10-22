#!/usr/bin/env python3
"""smoke_agent_surface.py — L3「智能体面真验」的固化版。

论文 §5 的判据是「改进是否真到达下游执行」。../docs/self-evolution.md §5.5 把这件事
定义成人工程序（dist 时间戳 → require 垫片 → 零成本 preflight → 真跑首任务 →
机械核对 run-log），但它当时只以 2026-10-18 那次首测的**一次性脚本**存在
（``runs/dsh-sdk-first-task-20261018/``），且路径硬编码到当时的 macOS 家目录，
换个 host 就跑不了——所以它已经漏过一次（inject 漏 ``approval``，17 个工具全丢
而宿主毫无感知）。

本 smoke 把其中**不需要 dsh 宿主、不烧 token** 的部分固化下来，并全部改成
相对 ``HERE`` 自解析路径：

  1. dist 产物存在且不比 src 旧（否则「改进已到达智能体面」这句话不成立）
  2. dist 导出的 inject 与 src 声明逐字一致（dist 是 dsh 真正加载的东西），
     且 ``inject`` **只含硬依赖 tools**——approval / skills / systemPrompt 是
     可选服务，声明进去会让宿主一缺就整插件失效（见 ``index.ts`` 第 1 条）
  3. 工具族可枚举，且 ``apply`` 期真的注册工具
  4. 垫片契约：dist 是 ESM 且内联了 ``__require`` shim —— 这正是需要
     require 互操作垫片的根因；若 esbuild 改了产物形状，这里当场变红
  5. 仓库里现存的 loader/patch 产物仍指向本仓（路径漂移 = 红的宿主加载）

**不覆盖的部分（诚实声明）**：真正的 dsh 宿主 boot 与首任务真跑需要
deepseek-harness checkout + LLM 端点，仍是人工工序（README §二.3 第 3-5 步）。
SKIP 不是 PASS。

用法（théâtre venv）:
    cd <explorateur>\\théâtre
    Windows: .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_agent_surface.py
    POSIX:   .venv/bin/python ../garage/smoke_agent_surface.py

退出码 0 = 六节全过；非 0 = 有节红，细节打印在 stdout。**每一节的返回值都必须
回传给 main**：本脚本是 ``wave_merge`` 的 L3 闸（红即候选作废），只打印不返回的
节等于没有闸——它红了，退出码照样是 0（2026-10-21 修：此前 6 节里 3 节如此）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]
PLUGIN_DIR = EXPLORATEUR / "usine" / "packages" / "dsh-plugin"
SRC_INDEX = PLUGIN_DIR / "src" / "index.ts"
DIST_INDEX = PLUGIN_DIR / "dist" / "index.mjs"
RUNS = HERE / "runs" / "dsh-sdk-first-task-20261018"

PASSED = 0
SKIPPED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASSED
    if not ok:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        return False
    PASSED += 1
    print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
    return True


def skip(name: str, why: str) -> None:
    SKIPPED.append(name)
    print(f"SKIP  {name} — {why}")


def test_dist_exists_and_fresher() -> bool:
    if not SRC_INDEX.is_file():
        return check("src/index.ts 存在", False, str(SRC_INDEX))
    if not DIST_INDEX.is_file():
        skip("dist 新鲜度", f"{DIST_INDEX} 不存在——先跑 pnpm build")
        return False
    src_mtime = SRC_INDEX.stat().st_mtime
    dist_mtime = DIST_INDEX.stat().st_mtime
    ok = dist_mtime >= src_mtime
    check(
        "dist 不比 src 旧（否则 dsh 加载的是上一次的插件面）",
        ok,
        f"src={int(src_mtime)} dist={int(dist_mtime)}",
    )
    return ok


def test_inject_parity() -> bool:
    src = SRC_INDEX.read_text(encoding="utf-8")
    dist = DIST_INDEX.read_text(encoding="utf-8")

    m = re.search(r"export const inject\s*=\s*\[([^\]]*)\]", src)
    if not m:
        return check("src 声明 inject", False, "找不到 export const inject")
    declared = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))

    # dist 里的 inject：esbuild 保留同名导出（可能是双引号或压缩后的单数组）。
    d = re.search(r"inject\s*=\s*\[([^\]]*)\]", dist)
    if not d:
        return check("dist 导出 inject", False, "dist/index.mjs 里找不到 inject")
    dist_inject = re.findall(r"['\"]([^'\"]+)['\"]", d.group(1))

    ok = declared == dist_inject
    hard = check(
        "dist 的 inject 与 src 逐字一致（dsh 真正加载的是 dist）",
        ok,
        f"src={declared} dist={dist_inject}",
    )
    # 2026-10-20 架构评审的决定（`usine/packages/dsh-plugin/src/index.ts` 第 1 条）：
    # **inject 只留硬依赖 tools**。approval / skills / systemPrompt 是**可选**服务，
    # 声明进 inject 等于「宿主必须提供」，宿主一缺整个插件永不生效、工具面全空且不报错。
    # 所以 `approval` **出现在 inject 里才是缺陷**——反过来判，并说明后果。
    guards = check(
        "dist inject 含 tools（工具面注册的硬依赖）",
        "tools" in dist_inject,
        str(dist_inject),
    )
    optional = check(
        "dist inject 不含 approval（可选服务，进了 inject 会让宿主一缺就整插件失效）",
        "approval" not in dist_inject,
        str(dist_inject),
    )
    return ok and guards and optional


def test_plugin_name_exported() -> bool:
    dist = DIST_INDEX.read_text(encoding="utf-8")
    # esbuild 产物里顶层声明是 `var name = "feuille-usine";`（带缩进、
    # var 而非 const/export）。必须要求行首空白 + 声明关键字，否则会命中
    # dist 内嵌依赖的模板字符串（第一版就误匹配到 `${req.voice}`）。
    m = re.search(r'(?m)^[ \t]*(?:export\s+)?(?:var|const|let)\s+name\s*=\s*'
                  r'["\']([a-z-]+)["\']', dist)
    ok = bool(m) and m.group(1) == "feuille-usine"
    check(
        "dist 导出插件名 feuille-usine（patch 条目按名字插入的就是它）",
        ok,
        m.group(1) if m else "未找到顶层 name 导出",
    )
    return ok


def test_require_shim_shape() -> bool:
    """dist 内联 __require shim —— 需要 require 互操作垫片的根因。

    2026-10-18 首测踩过的坑：vitest 有 CJS interop 所以一直是绿的，只有真
    宿主（Node 原生 ESM）首次加载才暴露 "Dynamic require ... is not
    supported"。若哪天 esbuild 改了产物形状（不再内联 shim），这个断言会先
    变红，提醒同步更新垫片的必要性判断。

    **返回值必须回传给 main**：本文件是 `wave_merge` 的 L3 闸（红即候选作废），
    一个只打印不返回的节等于没有闸——它红了，退出码照样是 0。
    """
    if not DIST_INDEX.is_file():
        skip("dist 形状", f"{DIST_INDEX} 不存在——先跑 pnpm build")
        return False
    dist = DIST_INDEX.read_text(encoding="utf-8")
    has_shim = "__require" in dist
    shim_ok = check(
        "dist 仍内联 __require shim（垫片的必要性依据）",
        has_shim,
        "若消失：宿主可能不再需要 require 垫片，重新评估 loader",
    )
    is_esm = "import" in dist[:2000] or "export" in dist[:2000]
    return check("dist 是 ESM 产物", is_esm) and shim_ok


def test_tool_surface_size() -> bool:
    """工具族规模 —— 缺 inject 时会「整面静默消失」，规模是它的哨兵。"""
    src = SRC_INDEX.read_text(encoding="utf-8")
    tools_src = (PLUGIN_DIR / "src" / "tools.ts")
    if not tools_src.is_file():
        skip("工具面规模", "src/tools.ts 不存在")
        return False
    tools_text = tools_src.read_text(encoding="utf-8")
    # familyTools() 里注册的工具以 `name: "usine_` 形状出现。
    names = set(re.findall(r"name:\s*[\"'](usine_[a-z_]+)[\"']", tools_text))
    enumerable = check("familyTools 暴露的工具可枚举", len(names) > 0, f"{len(names)} 个 usine_*")
    if names:
        print(f"      工具清单: {', '.join(sorted(names))}")
    # inject 里出现 ctx.tools 是工具面注册的前提。
    injected = check(
        "src apply 期注册工具（inject 含 tools 是前提）",
        "inject" in src and "ctx.tools.register" in src,
    )
    return enumerable and injected


def test_run_artifacts_not_drifted() -> bool:
    """首测现场的 loader/patch 不该还钉在别人的家目录上。"""
    if not RUNS.is_dir():
        skip("首测现场产物", f"{RUNS} 不存在")
        return False
    here_str = str(HERE).replace("\\", "/")
    drift: list[str] = []
    for name in ("feuille-usine-loader.mjs", "feuille-usine.patch.yml"):
        path = RUNS / name
        if not path.is_file():
            drift.append(f"{name} 缺失")
            continue
        text = path.read_text(encoding="utf-8")
        if here_str not in text and "personal/feuille" not in text:
            drift.append(f"{name} 既不指向本仓也不指向历史路径")
    return check(
        "首测现场 loader/patch 路径未漂移到未知位置",
        not drift,
        "; ".join(drift) if drift else "指向可识别路径",
    )


def main() -> int:
    print("=== L3 智能体面（离线可验部分）===\n")
    if not check("dsh-plugin 目录存在", PLUGIN_DIR.is_dir(), str(PLUGIN_DIR)):
        return 1

    results = [
        test_dist_exists_and_fresher(),
        test_inject_parity(),
        test_plugin_name_exported(),
        test_require_shim_shape(),
        test_tool_surface_size(),
        test_run_artifacts_not_drifted(),
    ]

    print()
    print(f"通过 {PASSED} 节")
    if SKIPPED:
        print(f"跳过 {len(SKIPPED)} 节（SKIP 不是 PASS）: {', '.join(SKIPPED)}")
    print("\n注意：dsh 宿主 boot 与首任务真跑仍需人工执行（../docs/self-evolution.md §5.5 的 L3 层第 3-5 步），")
    print("      本 smoke 只覆盖不烧 token 且不需要宿主的部分。")
    # 六节全部参与退出码：本脚本是 wave_merge 的 L3 闸，只打印不判决的节等于没有闸。
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
