#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_probes.py — 探针反向验证统一入口（2026-10-04 新增）

把十套反向验证脚本合成一条命令，并统一非零退出码语义：

  verify_shape_fixes.py    坑⑱⑲⑳㉑㉒ 几何修复——猴补丁回旧取值，探针必须 FAIL
  verify_text_contract.py  文本契约——喂修复前的坏数据，检查必须 FAIL
  verify_scene_schema.py   场景 schema——12 种定向破坏必须被抓
  verify_languages.py      语种目录——错旗/半旗/缺目录必须被抓（--selftest）
  framehash.py             逐帧像素基线——改 1 帧/改色相/抽帧必须被判漂移（--selftest）
  verify_publish.py        发布台账——悬空路径/越界指标/裸「已发布」必须被抓（--selftest）

**为什么必须统一入口**：这些是「探针会不会恒真」的唯一防线。原先它们散在
`scripts/` 下、且 `run.ps1` 根本没把它们接进主流程（`qa-shape-verify` 那个 case 因为
ValidateSet 漏列而是死代码，见 run.ps1 注释）——防线存在但没人会跑到。

只做进程级聚合，不改各脚本内部：它们各自 monkeypatch 模块属性、或在内存副本上造坏数据
来注入旧取值/错误数据，聚合层碰这些会引入耦合。

用法：
    uv run python scripts/verify_probes.py              # 跑全部
    uv run python scripts/verify_probes.py --only text  # 只跑文本契约
    .\\run.ps1 verify                                   # 等价（经 run.ps1）
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SUITES = {
    "shape": ("verify_shape_fixes.py", "形状探针（坑⑱⑲⑳㉑㉒ 几何接缝/下颌/墨镜/胡须）", []),
    "text": ("verify_text_contract.py", "文本契约（句末标点/语体差/时长预算）", []),
    "schema": ("verify_scene_schema.py", "场景 schema 校验层（12 种定向破坏必须被抓）", []),
    "lang": ("verify_languages.py", "语种目录（错旗/半旗/缺目录必须被抓）", ["--selftest"]),
    "langmap": ("verify_lang_migration.py", "语种取值等价性（重构前后逐字节相同 + 缺目录必须报错）", []),
    "draft": ("verify_scene_draft.py", "草稿生成器（复现已验收的 numbers + 7 类坏 brief 必须被拦）", []),
    "ledger": ("verify_ledger.py", "缓存账本（它会不会在不该跳的时候跳：改输入/删产物/坏账本）", []),
    "cli": ("verify_cli.py", "统一 CLI（旧入口的每个子命令都还在吗：路由表↔源码 choices 机检）", []),
    "framehash": ("framehash.py", "逐帧像素基线（改 1 帧/改色相/抽帧必须被判漂移）", ["--selftest"]),
    "publish": ("verify_publish.py", "发布台账（引用完整性/指标取值域/已发布凭据 + 分析侧样本量纪律）", ["--selftest"]),
}
ORDER = ["shape", "text", "schema", "lang", "langmap", "draft", "ledger", "cli",
         "framehash", "publish"]


def run_one(key, quiet=False):
    script, title, extra = SUITES[key]
    path = HERE / script
    if not path.exists():
        print(f"[{key}] 缺失脚本 {script}", file=sys.stderr)
        return 2
    if not quiet:
        print("\n" + "=" * 70)
        print(f"[{key}] {title}")
        print("=" * 70)
    proc = subprocess.run([sys.executable, str(path), *extra],
                          capture_output=quiet, text=True, encoding="utf-8", errors="replace")
    if quiet:
        print(proc.stdout or "", end="")
    if proc.returncode != 0 and proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


def main():
    ap = argparse.ArgumentParser(description="探针反向验证统一入口")
    ap.add_argument("--only", choices=sorted(SUITES), help="只跑指定套件")
    ap.add_argument("--quiet", action="store_true", help="不打印各套件的分隔标题（仍透传其输出）")
    args = ap.parse_args()

    keys = [args.only] if args.only else ORDER
    results = {}
    for k in keys:
        results[k] = run_one(k, quiet=args.quiet)

    print("\n" + "=" * 70)
    for k in keys:
        rc = results[k]
        mark = "PASS" if rc == 0 else f"FAIL(rc={rc})"
        print(f"  {k:<6} {mark}")
    failed = [k for k in keys if results[k] != 0]
    print("=" * 70)
    print("PROBE VERIFY " + ("PASS" if not failed else f"FAIL ({', '.join(failed)})"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
