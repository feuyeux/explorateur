#!/usr/bin/env python3
"""Whole-video blank-page scan — the ONLY check that is independent of the
state frames. verify_sync.py diffs the video against same-run state frames,
so one bad render batch (e.g. a malformed file:// URL that made headless
Chrome capture the Google search page) poisons both sides identically and
passes. This scan samples the finished mp4 directly and flags frames that
are mostly pure white — a real design frame is paper-tinted, never white.

Usage:
    scan_blank.py video.mp4 [more.mp4 ...] [--fps 1] [--max-white 0.75]

Exit 1 if any video contains blank frames.
"""
import argparse, pathlib, subprocess, sys, tempfile


def _ensure_pil():
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        import os
        from pathlib import Path
        # portable re-exec: locate the usine uv project (pins Pillow)
        usine = None
        for anc in Path(__file__).resolve().parents:
            if (anc / "pyproject.toml").is_file() and (anc / "src" / "feuille").is_dir():
                usine = anc
                break
            if (anc / "usine" / "pyproject.toml").is_file():
                usine = anc / "usine"
                break
        if usine and subprocess.run(["uv", "--version"], capture_output=True).returncode == 0:
            os.execvp("uv", ["uv", "run", "--project", str(usine), "python",
                             str(Path(__file__).resolve()), *sys.argv[1:]])
        sys.exit("PIL not found — install uv and run via "
                 "`uv run --project usine python <script>`")


_ensure_pil()

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


def scan(video, fps, max_white):
    from PIL import Image
    d = tempfile.mkdtemp()
    subprocess.run([_bin("ffmpeg"), "-y", "-loglevel", "error", "-i", str(video),
                    "-vf", f"fps={fps}", f"{d}/f%03d.png"], check=True)
    frames = sorted(pathlib.Path(d).glob("f*.png"))
    bad = []
    for p in frames:
        im = Image.open(p).convert("RGB").resize((160, 90))
        white = sum(1 for px in im.getdata() if min(px) >= 250)
        if white > max_white * 160 * 90:
            bad.append((p.name, round(white / 14400, 2)))
    n = len(frames)
    status = "FAIL" if bad else "ok"
    print(f"{video}: {n} frames sampled, blank/white: {bad[:6] or 'none'}  [{status}]")
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--max-white", type=float, default=0.75)
    a = ap.parse_args()
    ok = all(scan(v, a.fps, a.max_white) for v in a.videos)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
