#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_all.py — 28 张亮相卡全量验收：
1) mp4 存在、时长=10.0s、含 aac 音轨
2) t=3.0s 抽帧做角色探针（对照 personas.json 调色板）
3) 收尾帧探针（起跳/走位/转身等收尾动作抽样）
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

import qa_char

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "intro"
doc = json.load(open(HERE / "personas" / "intro-cards.json", encoding="utf-8"))
personas = {p["id"]: p for p in json.load(open(HERE / "personas" / "personas.json", encoding="utf-8"))["personas"]}


def ffprobe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name", "-show_entries", "format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout)


def grab(pid, t, tag):
    png = OUT / f"qa_{pid}_{tag}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(OUT / f"{pid}.mp4"),
                    "-frames:v", "1", str(png)], check=True)
    return png


fails = []
for card in doc["cards"]:
    pid = card["id"]
    mp4 = OUT / f"{pid}.mp4"
    if not mp4.exists():
        fails.append(f"{pid}: mp4 MISSING")
        continue
    info = ffprobe(mp4)
    dur = float(info["format"]["duration"])
    codecs = {(s.get("codec_type"), s.get("codec_name")) for s in info["streams"]}
    if abs(dur - 10.0) > 0.05:
        fails.append(f"{pid}: duration={dur:.3f}s")
    if ("audio", "aac") not in codecs:
        fails.append(f"{pid}: no aac audio, streams={codecs}")
    # 说话中段探针
    f1 = grab(pid, 3.0, "m")
    n = qa_char.check(pid, f1, verbose=False)
    if n:
        fails.append(f"{pid}: mid-frame probe fails={n}")
        qa_char.check(pid, f1, verbose=True)
    # 收尾动作抽样：mini_jump 起跳者用 apex，run_out 出画不探
    close = card["close"]
    if close in ("mini_jump", "kick", "shrug", "come_along", "palm_open", "wave",
                 "thumbs_up", "point", "nod", "snap", "camera_snap", "turn_freeze"):
        f2 = grab(pid, 9.4, "c")
        # 收尾仅检查身体主色（动作带来的 squash 由探针容差吸收）
        p = personas[pid]
        im = Image.open(f2).convert("RGB")
        want = qa_char.hexc(p["palette"]["outfitTop"])

        def dist(px):
            return sum((a - b) ** 2 for a, b in zip(px, want)) ** 0.5
        found = any(dist(im.getpixel((x, y))) < 60
                    for x in range(360, 720, 12) for y in range(1300, 1560, 12))
        if close != "run_out" and not found:
            fails.append(f"{pid}: close-frame torso not found")

print()
print("=" * 50)
if fails:
    print(f"FAILURES ({len(fails)}):")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print(f"ALL {len(doc['cards'])} CARDS PASS")
