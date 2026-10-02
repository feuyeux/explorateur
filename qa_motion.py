#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_motion.py — 动态验收：卡拉OK推进（LTR/RTL 方向）、口型同步、RTL 气泡位置、眨眼、幂等性抽检"""
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "intro"
personas = {p["id"]: p for p in json.load(open(HERE / "personas" / "personas.json", encoding="utf-8"))["personas"]}


def hexc(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def grab(pid, t, tag):
    png = OUT / f"qa_{pid}_{tag}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(OUT / f"{pid}.mp4"),
                    "-frames:v", "1", str(png)], check=True)
    return png


def hl_color(pid):
    c = hexc(personas[pid]["identity"])
    return tuple(int(v + (255 - v) * 0.45) for v in c)


def band_stats(pid, t):
    import statistics
    im = Image.open(grab(pid, t, "kb")).convert("RGB")
    hl = hl_color(pid)
    xs = []
    for y in range(110, 390, 6):
        for x in range(60, 1020, 6):
            px = im.getpixel((x, y))
            if sum((a - b) ** 2 for a, b in zip(px, hl)) ** 0.5 < 55:
                xs.append(x)
    n = len(xs)
    med = statistics.median(xs) if xs else None
    return n, med, (min(xs) if xs else None)


fails = []

# ---- 1) 卡拉OK逐词推进：LTR（xiaoman 覆盖率随时间增长）----
tl = json.load(open(OUT / "audio" / "xiaoman.timeline.json", encoding="utf-8"))
L0 = tl["lines"][0]
t_early, t_late = L0["start"] + L0["dur"] * 0.35, L0["start"] + L0["dur"] - 0.6
n_e, _, _ = band_stats("xiaoman", t_early)
n_l, _, _ = band_stats("xiaoman", t_late)
print(f"[karaoke LTR xiaoman] t={t_early:.1f}s hl_px={n_e}  t={t_late:.1f}s hl_px={n_l}")
if not (n_e > 150 and n_l > n_e * 1.5):
    fails.append(f"karaoke LTR: early={n_e} late={n_l} 未递增")

# ---- 2) 卡拉OK RTL（layla 右起：高亮中位 x 随时间左移）----
tl = json.load(open(OUT / "audio" / "layla.timeline.json", encoding="utf-8"))
L0 = tl["lines"][0]
t_e, t_l = L0["start"] + L0["dur"] * 0.42, L0["start"] + L0["dur"] - 0.4
n_e, med_e, _ = band_stats("layla", t_e)
n_l, med_l, _ = band_stats("layla", t_l)
print(f"[karaoke RTL layla] t={t_e:.1f}s hl_px={n_e} med_x={med_e}  t={t_l:.1f}s hl_px={n_l} med_x={med_l}")
if not (n_e > 100 and med_e is not None and med_e > 620):
    fails.append(f"karaoke RTL early: med_x={med_e} 未靠右（LTR 早段应≈458）")
if not (med_l is not None and med_l < med_e - 90 and n_l > n_e * 1.2):
    fails.append(f"karaoke RTL late: med_x={med_l} vs early {med_e} 未左移推进")

# ---- 3) 口型同步（xiaoman 说话中开合变化，收尾后闭合）----
# 嘴线 = 头顶下 0.815H（face_geo）：round → y 1252，张嘴区间 ~1204..1300
def mouth_dark(pid, t):
    im = Image.open(grab(pid, t, "mo")).convert("RGB")
    n = 0
    for y in range(1230, 1312, 3):
        for x in range(500, 581, 3):
            r, g, b = im.getpixel((x, y))
            if r < 160:
                n += 1
    return n

seq = [mouth_dark("xiaoman", t) for t in (2.0, 2.6, 3.2, 3.8, 4.4, 5.0, 5.6, 6.2)]
closed = [mouth_dark("xiaoman", t) for t in (8.6, 9.0, 9.4)]
print(f"[mouth xiaoman] 说话中 {seq} 收尾后 {closed}")
if max(seq) < 40 or min(seq) > max(seq) * 0.45:
    fails.append(f"mouth: 说话中未开合变化 {seq}")
if max(closed) > max(seq) * 0.55:
    fails.append(f"mouth: 收尾后未闭合 {closed} vs 说话中峰值 {max(seq)}")

# ---- 4) RTL 气泡镜像（layla 气泡在右侧 x≈780；jiangyuan LTR 在左侧 x≈300）----
def bubble_white(pid, t, cx):
    im = Image.open(grab(pid, t, "bu")).convert("RGB")
    n = 0
    for y in range(870, 965, 5):
        for x in range(cx - 120, cx + 120, 5):
            r, g, b = im.getpixel((x, y))
            if r > 235 and g > 235 and b > 235:
                n += 1
    return n

nb_rtl = bubble_white("layla", 7.6, 780)
nb_ltr = bubble_white("jiangyuan", 6.5, 300)
print(f"[bubble] layla RTL 右侧白px={nb_rtl}  jiangyuan LTR 左侧白px={nb_ltr}")
if nb_rtl < 60:
    fails.append(f"RTL 气泡未出现在右侧: {nb_rtl}")
if nb_ltr < 60:
    fails.append(f"LTR 气泡未出现在左侧: {nb_ltr}")

# ---- 5) 眨眼（xiaoman 巩膜白像素应有短时跌落）----
# 左眼中心 x = 540-0.30×头宽 = 438，巩膜 ±47.6×±58
def sclera_white(t):
    im = Image.open(grab("xiaoman", t, "bl")).convert("RGB")
    n = 0
    for y in range(1132, 1228, 4):
        for x in range(400, 477, 4):
            r, g, b = im.getpixel((x, y))
            if r > 235 and g > 235 and b > 235:
                n += 1
    return n

vals = [(t, sclera_white(t)) for t in [i * 0.1 for i in range(8, 100)]]
opens = [v for _, v in vals if v > 40]
dips = [t for t, v in vals if v < 12 and v < 0.3 * max(opens)]
print(f"[blink xiaoman] open_min={min(opens)} dips={len(dips)} @{[round(t,1) for t in dips[:6]]}")
if len(dips) < 1:
    fails.append("blink: 未见眨眼帧")

print()
print("=" * 50)
if fails:
    print("MOTION FAILURES:")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("MOTION QA PASS")
