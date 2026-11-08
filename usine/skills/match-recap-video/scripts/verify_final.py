# -*- coding: utf-8 -*-
"""verify_final.py — 成片验收：时长读数 + 对账 + 抽帧存档 + 电平。

「渲染被中断的 mp4 是半成品」：渲染进程中途被杀（会话结束、断电）留下没有
moov atom 的文件，时长读数直接报 Invalid data——判定口径只有「读得动读不动」，
**不看文件大小**（270 MB 的「大文件」照样是废片）。

时长口径：成片时长 = **装配所用的母版**时长。母版带采访/片尾卡时应先裁剪
（见 SKILL.md「母版结构」），拿原始母版来对账会差出一截——那是裁剪问题，
不是成片问题。

抽帧只是**存档**，人必须真的看：烧录链的 overlay 参数错（eof_action=pass）
会让全部字幕卡静默消失，机检与电平全绿、画面上却一张卡都没有
（2026-11-08 实拍坑，assemble.py selftest 已把参数钉死）。

用法：
    python3 scripts/verify_final.py --final <final.mp4> --master <母版.mp4> \
        [--frames-dir DIR] [--out report.json] [--skip-loudness]

退出码：0 = 时长读数可读且对得上；1 = 废片 / 时长差过大；2 = 输入坏了。
"""
from __future__ import annotations

import argparse
import json
import re
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


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="ignore")


def probe(path: Path) -> dict:
    r = run([_need("ffprobe"), "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(path)])
    if r.returncode != 0:
        return {"error": (r.stderr or "").strip()[-300:]}
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"error": f"JSON 解析失败：{exc}"}


def summarize(probe_doc: dict) -> dict:
    if "error" in probe_doc:
        return probe_doc
    v = next((s for s in probe_doc.get("streams", [])
              if s.get("codec_type") == "video"), None)
    a = next((s for s in probe_doc.get("streams", [])
              if s.get("codec_type") == "audio"), None)
    fps = None
    if v and v.get("r_frame_rate"):
        num, _, den = v["r_frame_rate"].partition("/")
        try:
            fps = round(float(num) / float(den or 1), 3)
        except (ValueError, ZeroDivisionError):
            fps = None
    return {
        "duration": round(float((probe_doc.get("format") or {}).get("duration") or 0), 3),
        "size_mb": round(int((probe_doc.get("format") or {}).get("size") or 0) / 1048576, 2),
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
        "fps": fps,
        "vcodec": (v or {}).get("codec_name"),
        "acodec": (a or {}).get("codec_name"),
        "astreams": sum(1 for s in probe_doc.get("streams", [])
                        if s.get("codec_type") == "audio"),
    }


def loudness(path: Path) -> str:
    r = run([_need("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path),
             "-af", "ebur128=peak=true", "-f", "null", "-"])
    m = re.findall(r"I:\s*(-?\d+\.?\d*)\s*LUFS", r.stderr)
    peak = re.findall(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", r.stderr)
    return f"I={m[-1] if m else '?'} LUFS  peak={peak[-1] if peak else '?'} dBFS"


def extract_frames(final: Path, duration: float, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    outs = []
    for tag, frac in (("head", 0.04), ("mid", 0.5), ("tail", 0.97)):
        # 定位在最后一帧之后会抽空（fps 粒度），钳到 duration−0.1s 内
        t = round(min(duration * frac, max(0.0, duration - 0.1)), 2)
        out = outdir / f"{tag}.jpg"
        r = run([_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t),
                 "-i", str(final), "-frames:v", "1", "-q:v", "3", str(out)])
        if r.returncode == 0 and out.exists():
            outs.append(out)
    return outs


def selftest() -> int:
    """离线回归：lavfi 合成 2s 视频当「成片」→ 读数/抽帧/时长对账全链。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        final = td_path / "fake-final.mp4"
        r = run([_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-shortest", "-pix_fmt", "yuv420p", str(final)])
        if r.returncode != 0:
            print(f"selftest：lavfi 合成失败 {r.stderr[:200]}")
            return 1
        frames = extract_frames(final, 2.0, td_path / "verify")
        ok = len(frames) == 3
        print(f"  [{'PASS' if len(frames) == 3 else 'FAIL'}] 抽帧 3/3")
        # 时长对账：母版 = 成片（2s）→ 0；母版 3s → 差 −1s 报警
        master = td_path / "fake-master.mp4"
        run([_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
             "-pix_fmt", "yuv420p", str(master)])
        rc = main(["--final", str(final), "--master", str(master),
                   "--frames-dir", str(td_path / "v2"), "--out", str(td_path / "r1.json"),
                   "--skip-loudness"])
        print(f"  [{'PASS' if rc == 0 else 'FAIL'}] 时长一致判 0（got {rc}）")
        ok = ok and rc == 0
        master2 = td_path / "fake-master3.mp4"
        run([_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=3",
             "-pix_fmt", "yuv420p", str(master2)])
        rc2 = main(["--final", str(final), "--master", str(master2),
                    "--frames-dir", str(td_path / "v3"), "--out", str(td_path / "r2.json"),
                    "--skip-loudness"])
        print(f"  [{'PASS' if rc2 == 1 else 'FAIL'}] 时长差 >0.5s 判 1（got {rc2}）")
        ok = ok and rc2 == 1
        print("selftest：" + ("全部通过" if ok else "有用例失败"))
        return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description="成片验收（ffprobe + 时长对账 + 抽帧 + 电平）")
    ap.add_argument("--final", required=True, help="成片 mp4")
    ap.add_argument("--master", required=True, help="装配所用母版 mp4")
    ap.add_argument("--frames-dir", help="抽帧存档目录（默认 <成片目录>/verify）")
    ap.add_argument("--out", help="报告 JSON（默认不落盘只打印）")
    ap.add_argument("--skip-loudness", action="store_true",
                    help="跳过 ebur128 全片电平（长片省时间）")
    ap.add_argument("--max-duration-diff", type=float, default=0.5,
                    help="成片与母版时长允许差（秒，默认 0.5）")
    args = ap.parse_args(argv)

    final = Path(args.final)
    if not final.exists():
        print(f"成片不存在：{final}")
        return 2
    fs = summarize(probe(final))
    if "error" in fs:
        print(f"✗ ffprobe 读不出来（moov atom 缺失 = 渲染被杀，重跑，不要当产物用）：{fs['error']}")
        return 1
    print(f"成片: {json.dumps(fs, ensure_ascii=False)}")
    if not fs.get("astreams"):
        print("✗ 没有音轨（旁白混丢了）")
        return 1

    master = Path(args.master)
    ms = summarize(probe(master)) if master.exists() else {}
    if ms.get("duration"):
        diff = round(fs["duration"] - ms["duration"], 2)
        print(f"母版: {json.dumps(ms, ensure_ascii=False)}")
        print(f"时长差（成片 − 母版）= {diff:+.2f}s")
        if abs(diff) > args.max_duration_diff:
            print(f"✗ 时长差超过 {args.max_duration_diff}s——确认装配用的是**裁剪后**的母版")
            return 1

    if not args.skip_loudness:
        print("电平:", loudness(final))

    frames_dir = Path(args.frames_dir) if args.frames_dir else final.parent / "verify"
    frames = extract_frames(final, fs["duration"], frames_dir)
    print("抽帧（人眼必须复核：卡片在位、不遮比分牌、不越界）:",
          ", ".join(p.name for p in frames) if frames else "（失败）")
    if not frames:
        print("✗ 一帧都抽不出来")
        return 1

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"final": fs, "master": ms, "frames": [str(p) for p in frames]},
            ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
