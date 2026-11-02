#!/usr/bin/env python3
"""read_scoreboard.py — 用本地 OCR 读比分牌，建立「视频时间 ↔ 比赛时钟」。

为什么需要它：`probe_scoreboard.py` 只给候选裁窗；读数原本要靠人眼逐帧看
竖拼长图。当运行环境没有视觉输入（模型不能读图、视觉代理不可用）时，
人眼这一步就断了。本脚本把「读数」变成可复跑的 OCR，输出可直接回填窗口表的
锚点、比分变化（进球）与跳切候选。

用法：
    # 1) 先用探针拿候选裁窗
    python3 probe_scoreboard.py master.mp4 --out probe.json
    # 2) 用排名第一的候选读数（或手动 --crop）
    python3 read_scoreboard.py master.mp4 --from-probe probe.json --out sb.json
    python3 read_scoreboard.py master.mp4 --crop 480:110:1440:0 --out sb.json

crop 的格式是 `w:h:x:y`（编码器裁窗参数）。不同转播的比分牌几何不同，**不要抄别人的数字**。

依赖：`pip install rapidocr_onnxruntime`（CPU 即可）。没装就退出非零，不静默跳过。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MINUTE_RE = re.compile(r"(?<!\d)(\d{1,3})\s*'")
CLOCK_RE = re.compile(r"(?<!\d)(\d{1,3}):(\d{2})(?!\d)")
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)")
TEAMS_RE = re.compile(r"\b([A-Z]{1,4})\s*[:.]\s*([A-Z]{1,4})\b")


class ReadError(RuntimeError):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ReadError(f"找不到 {name}——装好 ffmpeg 并放进 PATH。")
    return path


def _crop_from_probe(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []
    if not cands:
        raise ReadError(f"{path} 里没有 candidates")
    return str(cands[0]["crop"])


def _extract(master: Path, crop: str, fps: float, out_dir: Path) -> list[Path]:
    """按 fps 采样裁窗帧。fps=1 时 t≈帧号-1。"""
    ff = _tool("ffmpeg")
    pattern = out_dir / "%05d.png"
    cmd = [ff, "-y", "-v", "error", "-i", str(master),
           "-vf", f"crop={crop},fps={fps}", str(pattern)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReadError(f"ffmpeg 抽帧失败：\n{proc.stderr[-1500:]}")
    frames = sorted(out_dir.glob("*.png"))
    if not frames:
        raise ReadError("抽帧结果为空——检查 crop 是否越界。")
    return frames


def _parse(texts: list[str]) -> dict:
    joined = " | ".join(texts)
    mc = CLOCK_RE.search(joined)
    mm = MINUTE_RE.search(joined)
    ms = SCORE_RE.search(joined)
    mt = TEAMS_RE.search(joined)
    minute = second = None
    clock = None
    if mc:
        minute, second = int(mc.group(1)), int(mc.group(2))
        clock = f"{minute:02d}:{second:02d}"
    elif mm:
        minute = int(mm.group(1))
        clock = f"{minute}'"
    score = None
    if ms:
        # MM:SS 时钟本身也能被 SCORE_RE 命中（07:52 → 7-52）；同一段文本是时钟就跳过。
        same_as_clock = mc is not None and ms.group(0) == mc.group(0)
        if not same_as_clock:
            score = f"{ms.group(1)}-{ms.group(2)}"
    return {
        "minute": minute,
        "second": second,
        "clock": clock,
        "score": score,
        "teams": f"{mt.group(1)}:{mt.group(2)}" if mt else None,
    }


def _fill(rows: list[dict]) -> None:
    """给每一行补 minute_est（线性插值）与 score_est（前向填充）。

    插值只用于**粗定位**；它不改变原始读数。跳切段的斜率会明显异常，
    所以同时输出 `minute_slope` 供人复核。
    """
    pts = [(r["t"], r["minute"] + (r.get("second") or 0) / 60.0)
           for r in rows if r["minute"] is not None]
    pts.sort()
    for r in rows:
        if r["minute"] is not None:
            r["minute_est"] = round(r["minute"] + (r.get("second") or 0) / 60.0, 2)
            r["minute_interpolated"] = False
            continue
        t = r["t"]
        if not pts:
            r["minute_est"] = None
            r["minute_interpolated"] = True
            continue
        if t <= pts[0][0]:
            r["minute_est"] = float(pts[0][1])
        elif t >= pts[-1][0]:
            r["minute_est"] = float(pts[-1][1])
        else:
            for (t0, m0), (t1, m1) in zip(pts, pts[1:]):
                if t0 <= t <= t1:
                    span = max(t1 - t0, 1e-9)
                    r["minute_est"] = round(m0 + (m1 - m0) * (t - t0) / span, 1)
                    break
        r["minute_interpolated"] = True

    # 前向填充比分；第一个读数之前保持 None
    last = None
    for r in rows:
        if r["score"] is not None:
            last = r["score"]
        r["score_est"] = last


def _anchors(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    score_changes: list[dict] = []
    last_score = None
    for r in rows:
        s = r["score"]
        if s is None:
            continue
        if last_score is not None and s != last_score:
            score_changes.append({
                "t": r["t"], "from": last_score, "to": s,
                "minute": r["minute"], "teams": r["teams"], "raw": r["texts"],
            })
        last_score = s

    jumps: list[dict] = []
    known = [(r["t"], r["minute"] + (r.get("second") or 0) / 60.0)
             for r in rows if r["minute"] is not None]
    for (t0, m0), (t1, m1) in zip(known, known[1:]):
        dt = t1 - t0
        dm = m1 - m0
        if dt > 0 and dm / dt > 1.5:
            jumps.append({"t0": t0, "t1": t1, "minute0": m0, "minute1": m1,
                          "video_dt": dt, "match_dm": dm,
                          "slope": round(dm / dt, 3)})
    return score_changes, jumps


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="比分牌 OCR：视频时间 ↔ 比赛时钟")
    ap.add_argument("master", help="母版视频")
    ap.add_argument("--crop", help="裁窗 w:h:x:y（与 --from-probe 二选一）")
    ap.add_argument("--from-probe", help="probe_scoreboard.py 的输出；取 rank 1 的 crop")
    ap.add_argument("--fps", type=float, default=1.0, help="采样帧率（默认 1）")
    ap.add_argument("--out", help="输出 JSON（默认 stdout）")
    args = ap.parse_args(argv)

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        print("缺 rapidocr_onnxruntime：pip install rapidocr_onnxruntime", file=sys.stderr)
        return 2

    crop = args.crop or (_crop_from_probe(Path(args.from_probe)) if args.from_probe else None)
    if not crop:
        print("需要 --crop w:h:x:y 或 --from-probe probe.json", file=sys.stderr)
        return 2

    master = Path(args.master)
    if not master.exists():
        print(f"母版不存在：{master}", file=sys.stderr)
        return 2

    engine = RapidOCR()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            frames = _extract(master, crop, args.fps, Path(tmp))
            rows = []
            for i, f in enumerate(frames):
                res, _ = engine(str(f))
                texts = [str(t) for _, t, _ in (res or [])]
                row = {"t": round(i / args.fps, 3), "frame": i + 1,
                       "texts": texts, **_parse(texts)}
                rows.append(row)
    except ReadError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _fill(rows)
    score_changes, jumps = _anchors(rows)
    first_score = next((r["score"] for r in rows if r["score"]), None)
    last_score = next((r["score"] for r in reversed(rows) if r["score"]), None)
    out = {
        "master": str(master),
        "crop": crop,
        "fps": args.fps,
        "reads": rows,
        "first_score": first_score,
        "last_score": last_score,
        "score_changes": score_changes,
        "jumps": jumps,
        "notes": [
            "minute_est 是已知读数之间的线性插值，只用于粗定位；跳切段看 jumps。",
            "score_est 是前向填充；比分变化以 score_changes 为准。",
            "OCR 会把 8/6、1/7 认混；比分变化要和官方事件分钟互相印证。",
        ],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"比分牌读数 → {args.out}")
    else:
        print(text)
    print(f"有效分钟读数 {sum(1 for r in rows if r['minute'] is not None)} / {len(rows)} 帧"
          f" · 比分变化 {len(score_changes)} 次 · 跳切候选 {len(jumps)} 处",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
