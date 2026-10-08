# -*- coding: utf-8 -*-
"""cli.py — 统一入口 `uv run feuille <组> <命令>`（终态路由表，explorateur P2-3 体例）

**路由表是数据不是 if/elif**（与 explorateur.cli 同一条纪律）：能被遍历、
能被比对、能被机检「每个叶子都可达且**无参可调用**」。

    uv run feuille scene  parse|validate|draft       场景数据
    uv run feuille lesson new|doctor                 新课开坑 / 就绪度体检
    uv run feuille cover  make|check                 封面（整页 HTML 截图 / 尺寸底色检查）
    uv run feuille publish login|douyin|xhs|bilibili 平台发布（Playwright）
    uv run feuille verify   [suite …]                反向验证聚合

**文档字符串只列已登记的叶子**。历史教训：曾有一版文档列了 cover / manifest /
publish / framehash / audit / metrics / ledger 七组共 19 个子命令，而 COMMANDS
里一个都没有——当时这些入口全部返回「未知命令」。这是「路由表说谎」的镜像
形态：**文档说谎**，且当时的机检只查「已登记的叶子可达」，不查「文档宣称 ⊆
已登记」，所以一直没被抓出来。本表与 COMMANDS 现由 verify_cli.py 双向机检，
且机检升级为「叶子必须无参可调用」——只 import 得到、调不起来的叶子同样是
说谎（曾一次抓出 6 个这样的假叶子：库函数直接登记，真跑全是 TypeError）。

那 19 个宣称的去向分三类：

- cover（make/check）与 publish（login/douyin/xhs/bilibili）**补登记**——
  能力本来就有，只是没接线；库函数挂的是 main_* / main 适配层。
- framehash / audit / metrics / ledger 的宣称**删除**——相关能力一直只以
  `scripts/verify_*.py` 探针的形式存在，由 `feuille verify` 聚合，删宣称
  不算减功能。
- `manifest build` 的宣称**收回**——`build_manifest` 吃的是带闭包的 plans
  契约（video / cover 是函数不是路径），只能从项目脚本
  （`multilingual-video-publishing` 的 plans.py 模式）调用；CLI 化需要先把
  契约序列化，不硬做。

已登记的旧叶子一个没动——统一是**加法不是搬家**（explorateur 的教训：统一时
漏搬一个子命令，它就静默消失，直到有人在旧入口找不到功能才发现）。
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
    # ---- 封面（⑦）----
    # make/check 本体是库函数（make(key, html, out_png) / check(png, key)），
    # 叶子挂 main_make/main_check 适配层——路由器以 fn()/fn(argv) 调用叶子，
    # 把无参不可调用的库函数直接登记 = 路由表说谎（verify_cli 会抓）。
    ("cover", "make"):  ("feuille.covers", "main_make"),
    ("cover", "check"): ("feuille.covers", "main_check"),
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
