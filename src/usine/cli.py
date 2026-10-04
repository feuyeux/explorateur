#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py — 统一入口 `usine <组> <命令>`（P2-3）

**为什么统一**：8 个 console script 各记一套参数，用户要记住「卡片走 cards、场景走 scene、
校验走 validate」，而它们背后其实是**同一条流水线的不同阶段**。统一后命令按**领域**分组，
参数透传给原来的 `main()`——**不重写任何逻辑，只加一层路由**。

```
usine card   tts|assets|render                     亮相卡管线
usine chars  solo|sheet|html|all                    人物形象体检台
usine scene  tts|assets|render|list                教学场景管线
usine scene  parse|validate|draft                   场景数据（parse / 前置校验 / 草稿）
usine lesson build|dump                             教学文档
usine ledger status                                 产物缓存账本
usine publish build|check|analyze                   发布台账 + 指标回流
```

**旧入口全部保留**（pyproject 里 8 个 `usine-*` 一个都没删），run.ps1 与手册照旧可用——
统一是**加法不是搬家**。`verify_cli.py` 会机检「新树的每个叶子都可达」且
「旧入口的每个子命令都能从新树到达」，所以「统一时漏搬了一个功能」不可能静默发生。

路由表是**数据**（`COMMANDS`）而不是一串 if/elif：这样它能被遍历、能被比对，
和 P1-3 把 15 分支装置 if/elif 收进 `@device_style` 注册表是同一条纪律。
"""
from __future__ import annotations

import sys

# (组, 命令) -> (模块名, 传给该模块 main() 的位置参数前缀)
COMMANDS = {
    ("card", "tts"):     ("usine.intro_cards", ["tts"]),
    ("card", "assets"):  ("usine.intro_cards", ["assets"]),
    ("card", "render"):  ("usine.intro_cards", ["render"]),

    ("chars", "solo"):   ("usine.char_sheet", ["solo"]),
    ("chars", "sheet"):  ("usine.char_sheet", ["sheet"]),
    ("chars", "html"):   ("usine.char_sheet", ["html"]),
    ("chars", "all"):    ("usine.char_sheet", ["all"]),

    ("scene", "tts"):      ("usine.scene_video", ["tts"]),
    ("scene", "assets"):   ("usine.scene_video", ["assets"]),
    ("scene", "render"):   ("usine.scene_video", ["render"]),
    ("scene", "all"):      ("usine.scene_video", ["all"]),
    ("scene", "list"):     ("usine.scene_video", ["list"]),
    ("scene", "parse"):    ("usine.parse_scene", []),
    ("scene", "validate"): ("usine.scene_schema", []),
    ("scene", "draft"):    ("usine.scene_draft", []),

    ("lesson", "build"): ("usine.build_lesson", []),
    ("lesson", "dump"):  ("usine.dump_lesson_source", []),

    ("ledger", "status"): ("usine.ledger", ["status"]),

    ("publish", "build"):   ("usine.publish", ["build"]),
    ("publish", "check"):   ("usine.publish", ["check"]),
    ("publish", "analyze"): ("usine.publish", ["analyze"]),
}

GROUPS: dict[str, list[str]] = {}
for _g, _c in COMMANDS:
    GROUPS.setdefault(_g, []).append(_c)

# 旧 console script → 它在统一树里的等价命令（`usine-ledger status` 这类无相位的直接映射）。
# 这张表是 verify_cli 的判据来源：旧入口少一个映射，就是「统一时漏搬了功能」。
LEGACY_EQUIV = {
    "usine-cards":       [("card", c) for c in ("tts", "assets", "render")],
    "usine-chars":       [("chars", c) for c in ("solo", "sheet", "html", "all")],
    "usine-scene":       [("scene", c) for c in ("tts", "assets", "render", "all", "list")],
    "usine-parse":       [("scene", "parse")],
    "usine-validate":    [("scene", "validate")],
    "usine-draft":       [("scene", "draft")],
    "usine-lesson":      [("lesson", "build")],
    "usine-dump-lesson": [("lesson", "dump")],
    "usine-ledger":      [("ledger", "status")],
    "usine-publish":     [("publish", c) for c in ("build", "check", "analyze")],
}

USAGE = """用法：usine <组> <命令> [选项]

""" + "\n".join(
    f"  {g:<7} {', '.join(sorted(cs))}" for g, cs in sorted(GROUPS.items())
) + """

例：
  usine card render --workers 7          渲亮相卡
  usine scene render --scene colors      渲教学场景
  usine scene validate --scene numbers   场景数据前置校验
  usine scene draft --brief lessons/<id>/brief.json
  usine ledger status                    哪些产物过期了
  usine publish analyze --metric views   平台数据回流到创意/文案有效性

旧入口（usine-cards / usine-scene / ...）全部保留，等价命令见 scripts/verify_cli.py。
"""


def resolve(argv: list[str]) -> tuple[str, list[str]]:
    """('card render --only x') → (('card','render'), ['--only','x'])

    注意 `rest` 从 **argv[2]** 起：argv[1] 是命令名，它由 `COMMANDS[...][1]` 的
    「位置参数前缀」负责传给下游模块。透传命令名会让下游 argparse 报
    `unrecognized arguments: render`——而那是个只有真跑一遍才会暴露的错误。
    """
    if not argv or argv[0] in ("-h", "--help", "help"):
        raise SystemExit(USAGE)
    group = argv[0]
    if group not in GROUPS:
        raise SystemExit(f"未知组 {group!r}。可用：{', '.join(sorted(GROUPS))}\n\n{USAGE}")
    if len(argv) < 2:
        raise SystemExit(f"组 {group!r} 缺命令。可用：{', '.join(sorted(GROUPS[group]))}\n\n{USAGE}")
    cmd = argv[1]
    if cmd not in GROUPS[group]:
        raise SystemExit(f"未知命令 {group} {cmd!r}。可用：{', '.join(sorted(GROUPS[group]))}")
    return (group, cmd), argv[2:]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    key, rest = resolve(argv)
    group, cmd = key
    module, prefix = COMMANDS[key]
    import importlib
    m = importlib.import_module(module)
    # 走 `sys.argv` 而不是 `m.main(args)`：各模块的 `main()` 签名不统一
    # （有的收 `argv=None`，有的根本不收），逐个改成一致属于无收益的改动。
    # 顺带的好处：argparse 的 usage 行会显示**用户真正敲的命令**（`usine card render`）
    # 而不是 `cli.py`，报错信息直接可复制。
    sys.argv = [f"usine {group} {cmd}"] + prefix + rest
    return m.main() or 0


if __name__ == "__main__":
    sys.exit(main())
