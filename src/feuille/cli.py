# -*- coding: utf-8 -*-
"""cli.py — 统一入口 `uv run feuille <组> <命令>`（终态路由表，explorateur P2-3 体例）

**路由表是数据不是 if/elif**（与 explorateur.cli 同一条纪律）：能被遍历、
能被比对、能被机检「每个叶子都可达」。

    uv run feuille scene  parse|validate|draft       场景数据
    uv run feuille lesson new|doctor                 新课开坑 / 就绪度体检
    uv run feuille ledger status                     产物缓存账本
    uv run feuille cover  make|check                 封面
    uv run feuille manifest build|check|fix          发布清单
    uv run feuille publish login|douyin|xhs|bilibili|collection|verify  发布
    uv run feuille framehash save|compare|locate     逐帧像素基线
    uv run feuille audit   run                       格律审计
    uv run feuille metrics build|check|analyze       指标回流
    uv run feuille verify   [suite …]                反向验证聚合

旧入口全部等价保留——统一是**加法不是搬家**（explorateur 的教训：统一时漏搬
一个子命令，它就静默消失，直到有人在旧入口找不到功能才发现）。
"""
from __future__ import annotations

import sys


# (组, 命令) -> (模块, 函数)。模块 lazy import——CLI 启动零依赖。
# **只登记真实存在的叶子**——虚指不存在的函数 = 路由表说谎（verify_cli 会抓）。
# ②③ scene/lesson 的入口待子代理搬运完成后追加。
COMMANDS: dict[tuple[str, str], tuple[str, str]] = {
    # ---- 场景数据（②③）----
    ("scene", "parse"):   ("feuille.parse_scene", "main"),
    ("scene", "validate"): ("feuille.scene_schema", "main"),
    ("scene", "draft"):   ("feuille.scene_draft", "main"),
    # ---- 新课（③）----
    ("lesson", "new"):    ("feuille.lesson", "main_new"),
    ("lesson", "doctor"): ("feuille.lesson", "main_doctor"),
    # ---- 反向验证聚合（唯一实装入口）----
    ("verify", ""):       ("feuille._run_verify_probes", "run"),
}


def usage() -> None:
    print(__doc__)
    print("可用命令：")
    for (grp, cmd) in sorted(COMMANDS):
        print(f"  feuille {grp} {cmd}".rstrip())


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0
    grp = argv.pop(0)
    cmd = argv.pop(0) if argv else ""
    target = COMMANDS.get((grp, cmd))
    if target is None:
        # verify 组允许省略命令（跑全部套件）
        target = COMMANDS.get((grp, ""))
        if target is None:
            print(f"未知命令：feuille {grp} {cmd}")
            usage()
            return 2
    module_name, func = target
    import importlib
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func, None)
    if fn is None:
        print(f"{module_name} 里没有 {func}——叶子不可达（路由表与模块失配，这是 bug）")
        return 2
    return fn(argv) if argv else fn()
