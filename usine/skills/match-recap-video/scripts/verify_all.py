#!/usr/bin/env python3
"""verify_all.py — match-recap-video 的一条命令全验收。

SKILL.md 的「每一步的验收判据」有多行，能离线机检的是十二个 selftest；验收靠
agent 逐条记得跑，缺一环就是静默半成品。本脚本把十二个 selftest 聚合成一个
退出码（任何一环非零 = 整体非零），可选 `--windows` 连窗口表判决一起跑。

用法：
    python3 scripts/verify_all.py                     # 十二个 selftest（全离线，不联网）
    python3 scripts/verify_all.py --windows win.json  # 加判一次窗口表（FAIL → 退出码 1）

各 selftest 只需要 python3 与外部工具解析器能找到的工具（探针的合成视频用
lavfi 生成，不需要真集锦）；OCR 依赖不需要（read_scoreboard 的 selftest 是
纯函数回归）。首页图与事实表的 selftest 也是纯函数回归——**不碰浏览器、不渲图**
（渲染链路由 `make_covers.py` 的实跑路径负责）。双语卡的 selftest 同理：纯函数
回归，**不启浏览器**（真渲染走 `render_cards.py` 的实跑路径）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (名字, 命令) —— 全部离线；名字只进报告，不进判定
SELFTESTS: list[tuple[str, list[str]]] = [
    ("resolve_match（解析夹具 + 判别逻辑负例）",
     [sys.executable, str(HERE / "resolve_match.py"), "selftest"]),
    ("check_windows（四个坏例 + 输入契约 + anchor/align）",
     [sys.executable, str(HERE / "check_windows.py"), "selftest"]),
    ("place_voice（绝对锚点落点 + 早/晚/叠音/缺段反例）",
     [sys.executable, str(HERE / "place_voice.py"), "selftest"]),
    ("check_roster（球衣印字 ≠ 解说称呼 + 缺字段/重名反例 + CLI 真路径）",
     [sys.executable, str(HERE / "check_roster.py"), "selftest"]),
    ("find_master（排序判据回归）",
     [sys.executable, str(HERE / "find_master.py"), "--selftest"]),
    ("probe_scoreboard（合成视频探针回归）",
     [sys.executable, str(HERE / "probe_scoreboard.py"), "selftest"]),
    ("read_scoreboard（读数纯函数回归）",
     [sys.executable, str(HERE / "read_scoreboard.py"), "selftest"]),
    ("make_covers（版式安全区 + 事实对账 + 反向用例）",
     [sys.executable, str(HERE / "make_covers.py"), "selftest"]),
    ("build_publish_facts（数字溯源表回归）",
     [sys.executable, str(HERE / "build_publish_facts.py"), "selftest"]),
    ("render_cards（双语卡版式 + 实测层盒判据 + 反向用例）",
     [sys.executable, str(HERE / "render_cards.py"), "--selftest"]),
    ("uefa_facts（欧战接口事件归一 + 未识别子键不静默丢弃）",
     [sys.executable, str(HERE / "uefa_facts.py"), "--selftest"]),
    ("resolve_week（本周已完赛判定 + 默认阵容 + 俱乐部赛程兜底）",
     [sys.executable, str(HERE / "resolve_week.py"), "--selftest"]),
]


def run(name: str, cmd: list[str]) -> int:
    print(f"== {name}")
    proc = subprocess.run(cmd)
    print()
    return proc.returncode


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="match-recap-video 全验收聚合（十二个 selftest + 可选窗口表）")
    ap.add_argument("--windows", help="窗口表 JSON 路径；给了就连 check_windows 判决一起跑")
    args = ap.parse_args(argv)

    jobs: list[tuple[str, list[str]]] = list(SELFTESTS)
    if args.windows:
        jobs.append(("check_windows 窗口表判决",
                     [sys.executable, str(HERE / "check_windows.py"), args.windows]))

    failed: list[str] = []
    for name, cmd in jobs:
        if run(name, cmd) != 0:
            failed.append(name)

    if failed:
        print(f"全验收：**未过** —— {len(failed)}/{len(jobs)} 环失败：")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"全验收：{len(jobs)}/{len(jobs)} 环通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
