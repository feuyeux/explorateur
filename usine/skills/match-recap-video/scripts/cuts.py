# -*- coding: utf-8 -*-
"""cuts.py — 母版镜头切点检测（按镜头状态切窗的客观依据）。

为什么需要它：官方集锦的一「窗」必须=一个镜头状态（同一机位、同一画面内容）。
按「事件」切会把开场推进、logo 动画、扑救慢放混进同一窗，旁白就必然有一部分
对不上画面。切点是场景分（scene score）给出的客观边界，不靠人猜。

用法：
    python3 scripts/cuts.py <母版.mp4> [--out-dir DIR] [--threshold 0.15]
产物：
    <out-dir>/cuts.json  切点列表（time + scene 分）+ 合并后的有效段

合并规则：相邻切点 <0.6s 的段丢弃（转场抖动），首尾补齐成连续段。
阈值经验：0.12–0.16；硬切都抓得到，软切（同机位淡变）本来就抓不到——
时间轴上真正的跳变还要靠比分牌时钟读数补（见 plan_windows.py）。

退出码：0 = 正常；2 = 输入坏了（母版时长读不动）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

def _need(binary: str) -> str:
    """解析外部可执行文件：优先 FEUILLE_<NAME> 环境变量覆盖，否则 PATH 里找。

    全仓的跨平台解析事实源是 @feuille/core 的 platform resolver；本脚本是
    skill 内的独立 Python，用同样的「可覆盖 + 找不到就报错」口径，
    不静默拿别的同名程序顶替。
    """
    import os
    import shutil
    env = os.environ.get(f"FEUILLE_{binary.upper()}")
    if env:
        if not Path(env).exists():
            raise RuntimeError(f"环境变量 FEUILLE_{binary.upper()} 指向的文件不存在：{env}")
        return env
    found = shutil.which(binary)
    if not found:
        raise RuntimeError(f"找不到 {binary}——请装好它，或用 FEUILLE_{binary.upper()} 指定路径。")
    return found


def detect(master: Path, threshold: float) -> list[tuple[float, float]]:
    """跑场景分，返回 [(time, scene_score), ...]。"""
    cmd = [
        _need("ffmpeg"), "-hide_banner", "-nostats", "-i", str(master),
        "-filter_complex",
        f"select='gt(scene,{threshold})',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="ignore")
    out: list[tuple[float, float]] = []
    for line in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines():
        line = line.strip()
        if not line.startswith("frame:") or "pts_time:" not in line:
            continue
        try:
            _head, rest = line.split("pts_time:", 1)
            t = float(rest.split()[0])
            score = 1.0
            for tok in line.split():
                if tok.startswith("lavfi.scene_score="):
                    score = float(tok.split("=", 1)[1])
            out.append((round(t, 3), round(score, 4)))
        except (ValueError, IndexError):
            continue
    return out


def merge_segments(cuts: list[tuple[float, float]], total: float,
                   min_len: float = 0.6) -> list[dict]:
    """切点 → 连续有效段（<min_len 的段丢弃，尾段补到 total）。

    每个有效段是**两个边界之间的一整块**——不是把相邻块粘起来；
    自检曾抓到过「把连续段误并成一段」的回归，这里以测试钉死。
    """
    bounds = [0.0] + [c[0] for c in cuts if 0.0 < c[0] < total] + [total]
    segs: list[dict] = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a < min_len:
            continue
        segs.append({"i": len(segs), "t0": round(a, 2), "t1": round(b, 2),
                     "len": round(b - a, 2)})
    return segs


def selftest() -> int:
    """离线回归：lavfi 合成 3 段纯色硬切视频，切点必须 ≥2、段连续。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        master = Path(td) / "fake.mp4"
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=black:size=320x180:rate=10:duration=1",
             "-f", "lavfi", "-i", "color=red:size=320x180:rate=10:duration=1",
             "-f", "lavfi", "-i", "color=blue:size=320x180:rate=10:duration=1",
             "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
             "-map", "[v]", "-pix_fmt", "yuv420p", str(master)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"selftest：lavfi 合成失败 {r.stderr[:200]}")
            return 1
        cuts = detect(master, 0.15)
        segs = merge_segments(cuts, 3.0)
        ok = len(cuts) >= 2 and len(segs) >= 2 and abs(segs[-1]["t1"] - 3.0) < 0.05
        print(f"selftest：合成 3 段硬切 → 切点 {len(cuts)}、有效段 {len(segs)}"
              f"（{'通过' if ok else '不通过'}）")
        return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description="母版镜头切点检测")
    ap.add_argument("master", help="母版 mp4")
    ap.add_argument("--out-dir", help="产物目录（默认母版同目录）")
    ap.add_argument("--threshold", type=float, default=0.15,
                    help="场景分阈值（默认 0.15；0.12–0.16 都常用）")
    args = ap.parse_args(argv)

    master = Path(args.master)
    if not master.exists():
        print(f"母版不存在：{master}", file=sys.stderr)
        return 2
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(master)], capture_output=True, text=True)
    try:
        total = float(dur.stdout.strip() or 0)
    except ValueError:
        total = 0.0
    if total <= 0:
        print(f"母版时长读不出来（moov atom 缺失或不是视频）：{master}", file=sys.stderr)
        return 2

    outdir = Path(args.out_dir) if args.out_dir else master.parent
    outdir.mkdir(parents=True, exist_ok=True)
    cuts = detect(master, args.threshold)
    segs = merge_segments(cuts, total)
    (outdir / "cuts.json").write_text(
        json.dumps({"master": str(master), "total": round(total, 2),
                    "threshold": args.threshold, "cuts": cuts, "segments": segs},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"总长 {total:.2f}s  切点 {len(cuts)} 个  有效段 {len(segs)} 段 → {outdir / 'cuts.json'}")
    for s in segs:
        print(f"  seg{s['i']:>2}  {s['t0']:7.2f}–{s['t1']:7.2f}  ({s['len']:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
