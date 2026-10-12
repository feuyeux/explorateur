# -*- coding: utf-8 -*-
"""_run_verify_probes.py — CLI 桥：`uv run feuille verify` → scripts/verify_probes.py

聚合器是脚本不是包模块（它子进程驱动各套件、捕获 stdout 统计 PASS/FAIL/SKIP），
CLI 只做转发。参数透传（`feuille verify --only tts` → `verify_probes.py --only tts`）。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "verify_probes.py"


def run(argv: list[str] | None = None) -> int:
    # CLI 已消化了组/命令两层，这里收到的是残余参数。
    # `feuille verify --only tts` → argv=['--only', 'tts']
    # `feuille verify` → argv=[]
    # 显式 argv 优先：调用方给了参数就照用——sys.argv 兜底整个收进 `if argv is None:`，
    # 此前兜底分支无条件执行，显式传入的 argv 会被本进程的命令行静默覆盖。
    if argv is None:
        argv = sys.argv[3:]   # 跳过 <组=verify> <命令=空> 后的残余
        # 命令行入口时 sys.argv[1]=verify, sys.argv[2]=空串/第一个参数
        if len(sys.argv) > 2 and sys.argv[1] == "verify":
            argv = sys.argv[2:]
            # 空串命令时跳过它
            if argv and argv[0] == "":
                argv = argv[1:]
    return subprocess.run([sys.executable, str(_SCRIPT), *argv]).returncode
