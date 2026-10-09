# -*- coding: utf-8 -*-
"""cli.py — 统一入口 `uv run feuille <组> <命令>`（路由表是数据不是 if/elif）

路由表能被遍历、能被比对、能被机检：每个叶子都必须真的可达且**无参可调用**；
文档字符串里宣称的每个 `feuille <组> <命令>` 也都必须在 COMMANDS 里登记
（均由 verify_cli.py 机检——路由表不能说谎，文档也不能说谎）。

    uv run feuille scene  parse|validate|draft       场景数据
    uv run feuille lesson new|doctor                 新课开坑 / 就绪度体检
    uv run feuille persona validate                  人设契约体检（逐人 + 班底不变量）
    uv run feuille cover  make|check                 封面（整页 HTML 截图 / 尺寸底色检查）
    uv run feuille framehash save|check              逐帧像素基线（采基线 / 零漂移门禁）
    uv run feuille ledger status                     缓存账本（谁过期了、因为什么）
    uv run feuille publish login|douyin|xhs|bilibili 平台发布（Playwright）
    uv run feuille verify   [suite …]                反向验证聚合

模块 lazy import，CLI 启动零依赖。只登记真实存在、无参可调用的叶子：库函数
（如 publish / cover.make）挂 main_* / main 适配层再接线；吃带闭包契约的
build_manifest 只能从项目脚本调用，不设叶子。
"""
from __future__ import annotations

import sys


# (组, 命令) -> (模块, 函数)。模块 lazy import——CLI 启动零依赖。
# **只登记真实存在的叶子**——虚指不存在的函数 = 路由表说谎（verify_cli 会抓）。
COMMANDS: dict[tuple[str, str], tuple[str, str]] = {
    # ---- 场景数据（②③）----
    ("scene", "parse"):   ("feuille.parse_scene", "main"),
    ("scene", "validate"): ("feuille.scene_schema", "main"),
    ("scene", "draft"):   ("feuille.scene_draft", "main"),
    # ---- 新课（③）----
    ("lesson", "new"):    ("feuille.lesson", "main_new"),
    ("lesson", "doctor"): ("feuille.lesson", "main_doctor"),
    # ---- 人设契约（②③ 共用的班底体检；实现 = library.persona）----
    ("persona", "validate"): ("feuille.persona", "main"),
    # ---- 封面（⑦）----
    # make/check 本体是库函数（make(key, html, out_png) / check(png, key)），
    # 叶子挂 main_make/main_check 适配层——路由器以 fn()/fn(argv) 调用叶子，
    # 把无参不可调用的库函数直接登记 = 路由表说谎（verify_cli 会抓）。
    ("cover", "make"):  ("feuille.covers", "main_make"),
    ("cover", "check"): ("feuille.covers", "main_check"),
    # ---- 逐帧像素基线（⑬ 验收的像素判据；lesson doctor 的⑦层引用的就是这对叶子）----
    # save 采基线（回读自证内建）/ check 零漂移门禁。库判据全在 feuille.framehash，
    # 叶子只做「发现产物 → 调库 → 定退出码」的薄编排。
    ("framehash", "save"):  ("feuille.framehash", "main_save"),
    ("framehash", "check"): ("feuille.framehash", "main_check"),
    # ---- 缓存账本（产物新鲜度问答；report 薄适配层）----
    ("ledger", "status"):   ("feuille.ledger", "main_status"),
    # ---- 平台发布（⑨⑩⑪）----
    # ⚠️ 发布类叶子**要求 --group publish**（playwright 是可选依赖）。
    # 没装时 import 在函数内 lazy 失败，报的是「缺 playwright」而不是
    # 「未知命令」——这个区别很重要，前者告诉用户怎么修。
    # publish() 是库函数，douyin/xhs/bilibili 挂 main 适配层；login 无参
    # 可调用，直接登记。清单组装（build_manifest）**没有叶子**——它吃带
    # 闭包的 plans 契约，只能从项目脚本（plans.py 模式）调用。
    ("publish", "login"):    ("feuille.publish.login", "login"),
    ("publish", "douyin"):   ("feuille.publish.douyin", "main"),
    ("publish", "xhs"):      ("feuille.publish.xhs", "main"),
    ("publish", "bilibili"): ("feuille.publish.bilibili", "main"),
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
