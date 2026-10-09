#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_probes.py — 反向验证聚合器（feuille 版，搬运自 explorateur 同名脚本）

**SUITES 登记 + ORDER 执行，两处必须逐项一致**：登记了却没进执行名单的门禁
= 没有。聚合器对此当场 exit 2（explorateur 坑㊇：套件登记在 SUITES、
实际跑的是另一份 ORDER，门禁存在但从未执行——防线看着在，不在）。

**PASS 与 SKIP 分开报**：需要成片/浏览器的断言在没条件的机器上标 [SKIP]，
把 SKIP 显示成 PASS 就是假绿灯——门禁可以在任何机器跑，但结论必须诚实到
「哪些没验」都写在脸上。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (脚本名, 描述)。**顺序即执行序**——后面的套件依赖前面已验证的基座。
SUITES = {
    "platform":  ("verify_platform.py",  "跨平台解析（浏览器/ffmpeg/ffprobe/magick resolver）"),
    "ledger":    ("verify_ledger.py",    "产物缓存账本（注册制 + root 参数化）"),
    "tts":       ("verify_tts.py",       "TTS 内核（缓存键/词级时间戳/裁尾/重试）"),
    "audio":     ("verify_audio.py",    "音轨合成（compose_track 坑③顺序）"),
    "timeline":  ("verify_timeline.py",  "时间轴与词级进度轴"),
    "textlayer": ("verify_textlayer.py", "Edge 渲字层（视口探测/双 matte）"),
    "compose":   ("verify_compose.py",  "母版叠加合成（-shortest→-t）"),
    "rig":       ("verify_rig.py",      "人物 rig 几何探针（A1-E2 + 幂等）"),
    "personas":  ("verify_personas.py",  "persona 契约校验器（28 人班底）"),
    "covers":    ("verify_covers.py",   "封面机制（规格/裁切/众数底色）"),
    "manifest":  ("verify_manifest.py",  "发布清单（parse_copy/check/build）"),
    "audit":     ("verify_audit.py",    "格律审计/节替换/打包"),
    "framehash": ("verify_framehash.py", "逐帧像素基线（-map 0:v/分桶/定位）"),
    "metrics":   ("verify_metrics.py",  "指标回流（null≠0/两级凭据）"),
    "publish":   ("verify_publish.py",  "发布器骨架（mock 页/三缺陷修复）"),
    "cli":       ("verify_cli.py",      "CLI 路由表可达性 + 聚合器一致性"),
    "skills":    ("verify_skills.py",   "skills 去歧义（前置契约/边界/转交/事实源唯一）"),
}

SCRIPTS_DIR = ROOT / "scripts"


def run_suite(name: str) -> tuple[int, str]:
    script, desc = SUITES[name]
    p = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script)],
        capture_output=True, text=True, cwd=str(ROOT))
    return p.returncode, p.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="反向验证聚合器")
    ap.add_argument("--only", default=None, help=f"只跑某套（{'/'.join(SUITES)}）")
    ap.add_argument("--list", action="store_true", help="列出全部套件")
    args = ap.parse_args(argv)

    if args.list:
        for name, (script, desc) in SUITES.items():
            print(f"  {name:<12} {script:<24} {desc}")
        return 0

    todo = [args.only] if args.only else list(SUITES)
    for name in todo:
        if name not in SUITES:
            print(f"未知套件 {name!r}；可用：{'/'.join(SUITES)}")
            return 2
    # SUITES 与 todo 一致性已由「todo ⊆ SUITES 且默认 = list(SUITES)」保证；
    # 聚合器自身的防线：每个脚本必须真实存在。
    for name in todo:
        script, _ = SUITES[name]
        if not (SCRIPTS_DIR / script).exists():
            print(f"SUITES 登记了 {name}（{script}）但脚本不存在——登记了 = 必须在")
            return 2

    fails, skips_total = [], 0
    for name in todo:
        script, desc = SUITES[name]
        rc, out = run_suite(name)
        n_pass = out.count("[PASS]") + out.count("✅ PASS")
        n_fail = out.count("[FAIL]")
        n_skip = out.count("[SKIP]")        # "SKIP]" 是 "[SKIP]" 的子串，加一遍会双计
        skips_total += n_skip
        tag = "PASS" if rc == 0 else "FAIL"
        print(f"  [{tag}] {name:<12} {n_pass} PASS / {n_fail} FAIL / {n_skip} SKIP  {desc}")
        if rc != 0:
            fails.append(name)
            # 打印该套件的 FAIL 行
            for ln in out.splitlines():
                if "[FAIL]" in ln:
                    print(f"         ↳ {ln.strip()}")

    print("=" * 72)
    if fails:
        print(f"FAIL：{len(fails)} 套不过 ({', '.join(fails)})")
        return 1
    print(f"OK：全部 {len(todo)} 套反向验证通过"
          + (f"（{skips_total} 项 SKIP 诚实列出——不是 PASS）" if skips_total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
