#!/usr/bin/env python3
"""End-to-end AV-sync acceptance: grab frames from the finished video at
computationally known times and pixel-diff them against the expected state
frames.

Usage:
    verify_sync.py --video out.mp4 --frames frames/ --tts tts/ \
        --locales zh-CN,ja-JP,... [--preroll 0.8] [--done 0.5] [--intro 2.2]
        [--threshold 40000]

Checks per locale (scene starts are accumulated from the seg wav durations,
the same numbers the builder used):
  pre   at scene_start + 0.4        vs  <loc>-pre.png
  word0 at scene_start + preroll + state0_dur/2   vs  <loc>-0.png
        (state0_dur = start of token 1 − start of token 0, read from the
        tts boundary json — the builder switches states at token STARTS, so
        a short first word like English "a" can end before the old fixed
        +0.15s probe landed in the NEXT state)
  done  at scene_end - done/2       vs  <loc>-done.png

Exit 0 only if every diff is under the threshold. The model cannot see the
video — this script is the visual gate.
"""
import argparse, json, pathlib, subprocess, sys
from PIL import Image, ImageChops

_BIN: dict[str, str] = {}


def _bin(name: str) -> str:
    """外部可执行文件经 `feuille.platform` 解析（AGENTS.md 跨平台硬约定 1）。"""
    if name not in _BIN:
        try:
            from feuille import platform
            got = getattr(platform, name)() or ""
        except ImportError:
            got = ""
        if not got:
            sys.exit(f"找不到 {name}：请用 `uv run --project usine python …` 运行"
                     f"（feuille.platform 解析），或安装后重跑")
        _BIN[name] = got
    return _BIN[name]


def diff(a, b):
    ia, ib = Image.open(a).convert("L"), Image.open(b).convert("L")
    return sum(ImageChops.difference(ia, ib).histogram()[12:])


def dur(p):
    return float(subprocess.run(
        [_bin("ffprobe"), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip())


def grab(video, t, out):
    subprocess.run([_bin("ffmpeg"), "-y", "-loglevel", "error", "-ss", str(t),
                    "-i", str(video), "-frames:v", "1", out], check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--tts", required=True)
    ap.add_argument("--locales", required=True, help="comma-separated, in video order")
    ap.add_argument("--preroll", type=float, default=0.8)
    ap.add_argument("--done", type=float, default=0.5)
    ap.add_argument("--intro", type=float, default=2.2)
    ap.add_argument("--threshold", type=int, default=40000,
                    help="max L1 gray diff per grabbed frame (encoding noise)")
    a = ap.parse_args()
    F = pathlib.Path(a.frames)
    T = pathlib.Path(a.tts)

    starts = {}
    t = a.intro
    for loc in a.locales.split(","):
        starts[loc] = t
        t += dur(F / f"{loc}-seg.wav")

    fails = []
    for loc in a.locales.split(","):
        s = starts[loc]
        d = dur(F / f"{loc}-seg.wav")
        toks = json.loads((T / f"{loc}.json").read_text())["tokens"]
        # state 0 runs [preroll + t0.start, preroll + t1.start); probe mid-way.
        # Single-token locales: probe at half the audio span instead.
        if len(toks) > 1:
            s0 = toks[1]["start"] - toks[0]["start"]
        else:
            s0 = d - a.preroll - a.done
        checks = [
            ("pre", s + 0.4, F / f"{loc}-pre.png"),
            ("word0", s + a.preroll + s0 / 2, F / f"{loc}-0.png"),
            ("done", s + d - a.done / 2, F / f"{loc}-done.png"),
        ]
        for label, tt, want in checks:
            dpx = diff(grab(a.video, tt, "/tmp/_vs.png"), want)
            status = "OK" if dpx < a.threshold else "MISMATCH"
            print(f"{loc:8s} {label:6s} t={tt:7.2f} diff={dpx:8d}  {status}")
            if dpx >= a.threshold:
                fails.append(f"{loc}/{label}")

    if fails:
        raise SystemExit(f"SYNC FAILURES: {', '.join(fails)}")
    print("all scenes in sync")


if __name__ == "__main__":
    main()
