#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_timeline.py — 时间轴与词级进度轴的反向验证

第 0 条好数据放行：compute_starts 的累进口径与已验收的 24 支成片一致
（start[i] = start[i-1] + speech_dur[i-1] + gap）。其余各防一种退化：

- 空行表 / 单行 / 多行的起点累进全部正确
- enrich_lines 的 file_dur 一律 ffprobe 实测、tail_silence = file_dur - speech
- 卡拉OK进度点：时刻单调、进度落在 [0,1]、首点 0、末点 1
- frac_at：区间外夹 0/1、区间内线性插值
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import platform as pt, timeline as tl    # noqa: E402


def check():
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：累进口径 ----
    got = tl.compute_starts([1.0, 2.0, 0.5], 0.35)
    rows.append((got == [0.0, 1.35, 3.70],
                 f"三行累进正确（gap=0.35：{got}，应 [0, 1.35, 3.7]）"))
    rows.append((tl.compute_starts([], 0.35) == [], "空行表 → 空起点"))
    rows.append((tl.compute_starts([1.2], 0.35) == [0.0], "单行 → 起点为 0"))

    # ---- 1. 卡拉OK进度轴 ----
    line = {"start": 1.0, "dur": 2.0,
            "words": [{"w": "ab", "s": 1.0, "e": 1.5},
                      {"w": "cd", "s": 1.6, "e": 2.2}]}
    pts = tl.karaoke_points(line)
    ts = [t for t, _ in pts]
    fs = [f for _, f in pts]
    rows.append((ts == sorted(ts), "进度点时刻单调不减"))
    rows.append((all(0.0 <= f <= 1.0 for f in fs), "进度落在 [0,1]"))
    rows.append((pts[0] == (1.0, 0.0) and abs(pts[-1][0] - 3.15) < 1e-9 and pts[-1][1] == 1.0,
                 f"首点 (start,0)、末点 (start+dur+0.15, 1.0)（末点 {pts[-1]}）"))
    rows.append((abs(pts[1][1] - 2 / 5) < 1e-9,
                 f"字符进度口径：词面 2/5（得 {pts[1][1]}）"))
    rows.append((tl.frac_at(pts, 0.5) == 0.0 and tl.frac_at(pts, 99.0) == 1.0,
                 "frac_at 区间外夹 0/1"))
    mid = tl.frac_at(pts, 1.25)  # (1.0,0.4)→(1.5,0.6) 的中点 1.25 → 0.5
    rows.append((abs(mid - 0.5) < 1e-9, f"frac_at 线性插值（t=1.25 → {mid}，应 0.5）"))

    # ---- 2. enrich_lines（真机：ffprobe 实测口径）----
    ffm, ffpr = pt.ffmpeg(), pt.ffprobe()
    if not (ffm and ffpr):
        rows.append((True, "[SKIP] enrich_lines 实测未验（缺 ffmpeg/ffprobe）"))
        return rows
    tmp = tempfile.TemporaryDirectory(prefix="feuille-timeline-")
    audio_dir = pathlib.Path(tmp.name)
    mk = subprocess.run([ffm, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                         str(audio_dir / "k1.mp3")], capture_output=True)
    (audio_dir / "k2.mp3").write_bytes((audio_dir / "k1.mp3").read_bytes())
    if mk.returncode != 0:
        rows.append((True, "[SKIP] enrich_lines 实测未验（造样本失败）"))
        return rows
    lines = [{"key": "k1", "dur": 0.5, "text": "行一"},
             {"key": "k2", "dur": 0.5, "text": "行二"}]
    total, span = tl.enrich_lines(lines, 0.35, audio_dir)
    rows.append((abs(lines[0]["file_dur"] - 1.0) < 0.05,
                 f"file_dur 由 ffprobe 实测（{lines[0]['file_dur']}）"))
    rows.append((abs(lines[0]["tail_silence"] - (lines[0]["file_dur"] - 0.5)) < 1e-6,
                 f"tail_silence = file_dur - speech（{lines[0]['tail_silence']}）"))
    rows.append((lines[0]["start"] == 0.0 and abs(lines[1]["start"] - 0.85) < 1e-6,
                 f"enrich 后起点累进正确（{[l['start'] for l in lines]}）"))
    rows.append((abs(total - 1.0) < 1e-6 and abs(span - 1.35) < 1e-6,
                 f"total/span 正确（{total} / {span}）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("时间轴与词级进度轴（compute_starts / enrich_lines / karaoke）")
    print("=" * 72)
    rows = check()
    fails = skips = 0
    for ok, msg in rows:
        if msg.startswith("[SKIP]"):
            skips += 1
            print(f"  [SKIP] {msg[6:]}")
        else:
            fails += not ok
            print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：时间轴 {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
