#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_all.py — 28 张亮相卡 + 4 个 RTL 女性观众版全量验收（self-intro §1.4）：
1) mp4 存在、时长=10.0s、含 aac 音轨
2) t=3.0s 抽帧做角色探针（mood/视线/眉形与本单元时间线同源推导）
3) 收尾帧探针（close 可为按序码列：取 9.4s 活跃码；跑出画族跳过身体探针）
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from . import qa_char
from usine import ROOT

HERE = ROOT
OUT = HERE / "build" / "intro"
doc = json.load(open(HERE / "personas" / "intro-cards.json", encoding="utf-8"))
personas = {p["id"]: p for p in json.load(open(HERE / "personas" / "personas.json", encoding="utf-8"))["personas"]}
RUN_FAMILY = ("run_out", "thumbs_run", "shoot_run")
CLOSE_DUR = {"mini_jump": 1.1, "turn_freeze": 0.9, "snap": 0.9, "camera_snap": 1.0}


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


def units():
    """(unit_id, persona_id, card)：变体共享人设/场景/收尾（intro_cards.card_units 同构）"""
    for c in doc["cards"]:
        yield c["id"], c["id"], c
        for v in c.get("variants", []):
            yield v["id"], c["id"], c


fails = []
n_units = 0
for pid, persona_id, card in units():
    n_units += 1
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
    # 说话中段探针：mood 从本单元时间线推导（与渲染同源）
    tl = json.loads((OUT / "audio" / f"{pid}.timeline.json").read_text("utf-8"))
    li = 0
    for i, line in enumerate(tl["lines"]):
        if 3.0 >= line["start"] - 0.18:
            li = i
    mood = tl["lines"][li]["mood"]
    f1 = grab(pid, 3.0, "m")
    n = qa_char.check(persona_id, f1, verbose=False, t=3.0, mood=mood)
    if n:
        fails.append(f"{pid}: mid-frame probe fails={n}")
        qa_char.check(persona_id, f1, verbose=True, t=3.0, mood=mood)
    # 收尾码列：9.4s 的活跃码；已结束则按末码静止姿态检查；跑出画族跳过
    close = card["close"]
    close_seq = close if isinstance(close, list) else [close]
    t0 = min(tl["speechEnd"] + 0.15, 9.1)
    active = None
    for cc in close_seq:
        dd = (10.0 - t0 - 0.1) if cc in RUN_FAMILY else CLOSE_DUR.get(cc, 1.3)
        if t0 <= 9.4 < t0 + dd:
            active = cc
        t0 += dd
    check_code = None
    if active is not None:
        check_code = None if active in RUN_FAMILY else active  # 9.4s 正在跑出画 → 不查躯干
    elif close_seq[-1] not in RUN_FAMILY:
        check_code = close_seq[-1]  # 码列已收完 → 按末码静止姿态检查
    if check_code is not None:
        f2 = grab(pid, 9.4, "c")
        # 收尾仅检查身体主色（动作带来的 squash/位移由扫描窗与探针容差吸收）
        p = personas[persona_id]
        im = Image.open(f2).convert("RGB")
        want = qa_char.hexc(p["palette"]["outfitTop"])

        def dist(px):
            return sum((a - b) ** 2 for a, b in zip(px, want)) ** 0.5
        found = any(dist(im.getpixel((x, y))) < 60
                    for x in range(360, 720, 12) for y in range(1300, 1560, 12))
        if not found:
            fails.append(f"{pid}: close-frame torso not found (close={check_code})")

print()
print("=" * 50)
if fails:
    print(f"FAILURES ({len(fails)}):")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print(f"ALL {n_units} UNITS PASS (28 cards + RTL female variants)")
