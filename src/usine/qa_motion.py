#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_motion.py — 动态验收：卡拉OK推进（LTR/RTL）、口型同步、RTL 气泡、眨眼、
进度条推进、名牌/语言牌弹出、视线漂移、挂件物理（项链吊坠摆动/镜片反光位移）、
呆毛彩蛋颤动、幂等性抽检（重渲一卡，视频流 framehash 须一致——不变量⑦/坑⑫）。
所有采样框从 intro_cards.face_geo 与布局常量推导（不变量①/⑩，永不手抄坐标）。"""
import json
import subprocess
import sys

from PIL import Image

from .intro_cards import (BADGE_BOX_H, BADGE_Y, BUBBLE_CX, BUBBLE_CY, PILL_BOX_H, PILL_Y,
                          PROG_X0, PROG_X1, PROG_Y0, PROG_Y1, THEME, W, face_geo, hexc)
from .data import personas as _read_personas
from usine import ROOT

HERE = ROOT
OUT = HERE / "build" / "intro"
personas = _read_personas()
G = face_geo(personas["xiaoman"]["movement"]["face"])  # 探针几何单一事实源（不变量①）


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
# 嘴线 y = 头顶下 0.815H（face_geo.mouth_y）；采样窗从 face_geo 推导，绝不手抄
def mouth_dark(pid, t):
    g = face_geo(personas[pid]["movement"]["face"])
    u = lambda f: f * g["H"]
    im = Image.open(grab(pid, t, "mo")).convert("RGB")
    n = 0
    for y in range(int(g["mouth_y"] - u(0.06)), int(g["mouth_y"] + u(0.17)), 3):
        for x in range(int(g["cx"] - 40), int(g["cx"] + 41), 3):
            r, gg, b = im.getpixel((x, y))
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

# ---- 4) RTL 气泡镜像（layla 气泡在右侧；jiangyuan LTR 在左侧；中心=BUBBLE 常量）----
def bubble_white(pid, t, rtl):
    cx = W - BUBBLE_CX if rtl else BUBBLE_CX
    im = Image.open(grab(pid, t, "bu")).convert("RGB")
    n = 0
    for y in range(BUBBLE_CY - 48, BUBBLE_CY + 48, 5):
        for x in range(cx - 120, cx + 120, 5):
            r, g, b = im.getpixel((x, y))
            if r > 235 and g > 235 and b > 235:
                n += 1
    return n

nb_rtl = bubble_white("layla", 7.6, True)
nb_ltr = bubble_white("jiangyuan", 6.5, False)
print(f"[bubble] layla RTL 右侧白px={nb_rtl}  jiangyuan LTR 左侧白px={nb_ltr}")
if nb_rtl < 60:
    fails.append(f"RTL 气泡未出现在右侧: {nb_rtl}")
if nb_ltr < 60:
    fails.append(f"LTR 气泡未出现在左侧: {nb_ltr}")

# ---- 5) 眨眼（xiaoman 巩膜白像素应有短时跌落；采样框从 face_geo 推导）----
ex = G["cx"] - G["eye_dx"]
BX0, BX1 = int(ex - G["scl_rx"] * 0.80), int(ex + G["scl_rx"] * 0.80)
BY0, BY1 = int(G["eye_y"] - G["scl_ry"] * 0.85), int(G["eye_y"] + G["scl_ry"] * 0.85)


def sclera_white(t):
    im = Image.open(grab("xiaoman", t, "bl")).convert("RGB")
    n = 0
    for y in range(BY0, BY1, 4):
        for x in range(BX0, BX1, 4):
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

# ---- 6) 进度条推进（外框常量同源；填充随时间增长）----
def prog_fill(pid, t):
    im = Image.open(grab(pid, t, "pg")).convert("RGB")
    ident = hexc(personas[pid]["identity"])
    y = (PROG_Y0 + PROG_Y1) // 2
    n = 0
    for x in range(PROG_X0 + 8, PROG_X1 - 8, 4):
        px = im.getpixel((x, y))
        if sum((a - b) ** 2 for a, b in zip(px, ident)) ** 0.5 < 40:
            n += 1
    return n

pg_e, pg_l = prog_fill("xiaoman", 1.0), prog_fill("xiaoman", 8.5)
print(f"[progress xiaoman] t=1.0 fill_px={pg_e}  t=8.5 fill_px={pg_l}")
if not (pg_e > 5 and pg_l > pg_e * 2.5):
    fails.append(f"progress: fill 未随时间增长 early={pg_e} late={pg_l}")

# ---- 7) 名牌弹出（0.6s 弹出：0.35s 缺席 vs 1.2s 在场）----
def badge_white(pid, t):
    im = Image.open(grab(pid, t, "bd")).convert("RGB")
    n = 0
    for y in range(BADGE_Y, BADGE_Y + BADGE_BOX_H, 8):
        for x in range(240, 840, 8):
            r, g, b = im.getpixel((x, y))
            if r > 235 and g > 235 and b > 235:
                n += 1
    return n

bd_early, bd_late = badge_white("xiaoman", 0.35), badge_white("xiaoman", 1.2)
print(f"[badge xiaoman] t=0.35 白px={bd_early}  t=1.2 白px={bd_late}")
if not (bd_late > 1200 and bd_early < bd_late * 0.35):
    fails.append(f"badge: 弹出异常 early={bd_early} late={bd_late}")

# ---- 8) 语言牌在场（入场前 0.3s 弹出；zh-CN: 🇨🇳 汉语）----
def pill_white(pid, t):
    im = Image.open(grab(pid, t, "pl")).convert("RGB")
    n = 0
    for y in range(PILL_Y, PILL_Y + PILL_BOX_H, 6):
        for x in range(400, 680, 6):
            r, g, b = im.getpixel((x, y))
            if r > 225 and g > 225 and b > 225:
                n += 1
    return n

pi_early, pi_late = pill_white("xiaoman", 0.2), pill_white("xiaoman", 2.0)
print(f"[pill xiaoman] t=0.2 白px={pi_early}  t=2.0 白px={pi_late}")
if not (pi_late > 300 and pi_early < pi_late * 0.35):
    fails.append(f"语言牌: 弹出异常 early={pi_early} late={pi_late}")

# ---- 9) 挂件物理：layla 金吊坠摆动（swing；金像素质心位移）----
def gold_centroid(pid, t, box, want):
    im = Image.open(grab(pid, t, "gw")).convert("RGB")
    xs = []
    x0, y0, x1, y1 = box
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            px = im.getpixel((x, y))
            if sum((a - b) ** 2 for a, b in zip(px, want)) ** 0.5 < 40:
                xs.append(x)
    return (sum(xs) / len(xs)) if xs else None

layla_g = face_geo(personas["layla"]["movement"]["face"])
neck_box = (500, int(layla_g["torso_top"] + 50), 580, int(layla_g["torso_top"] + 95))
cents = [gold_centroid("layla", t, neck_box, THEME["gold"]) for t in (3.0, 3.3, 3.6, 3.9)]
ok_c = [c for c in cents if c is not None]
swing_rng = (max(ok_c) - min(ok_c)) if len(ok_c) >= 3 else -1
print(f"[necklace layla] 金质心 x={ [round(c, 1) if c else None for c in cents] } range={swing_rng:.1f}px")
if swing_rng < 1.2:
    fails.append(f"necklace swing: 吊坠未摆动 range={swing_rng:.1f}px {cents}")

# ---- 10) 镜片反光位移（mateo 挂领太阳镜 glint_blue 质心随时间移动）----
mateo_g = face_geo(personas["mateo"]["movement"]["face"])
glint_box = (495, int(mateo_g["torso_top"] + 56), 548, int(mateo_g["torso_top"] + 80))
cents = [gold_centroid("mateo", t, glint_box, THEME["glint_blue"]) for t in (3.0, 3.45, 3.9, 4.35)]
ok_c = [c for c in cents if c is not None]
glint_rng = (max(ok_c) - min(ok_c)) if len(ok_c) >= 3 else -1
print(f"[glint mateo] 反光质心 x={[round(c, 1) if c else None for c in cents]} range={glint_rng:.1f}px")
if glint_rng < 1.0:
    fails.append(f"lens glint: 反光未移动 range={glint_rng:.1f}px {cents}")

# ---- 11) 视线漂移（xiaoman 瞳孔质心随 gaze 移动；跳过眨眼帧）----
def pupil_centroid(t):
    im = Image.open(grab("xiaoman", t, "gz")).convert("RGB")
    sx = sy = n = 0
    white = 0
    for y in range(BY0, BY1, 3):
        for x in range(BX0, BX1, 3):
            r, g, b = im.getpixel((x, y))
            if r > 235 and g > 235 and b > 235:
                white += 1
            elif sum((a - c) ** 2 for a, c in zip((r, g, b), THEME["ink"])) ** 0.5 < 60:
                sx, sy, n = sx + x, sy + y, n + 1
    return (sx / n, sy / n, white) if n else (None, None, white)

samples = [(t, *pupil_centroid(t)) for t in (2.2, 2.5, 2.8, 3.1, 3.4, 3.7)]
valid = [(cx, cy) for _, cx, cy, w in samples if cx is not None and w > 40]
if len(valid) >= 3:
    gx_rng = max(v[0] for v in valid) - min(v[0] for v in valid)
    gy_rng = max(v[1] for v in valid) - min(v[1] for v in valid)
    print(f"[gaze xiaoman] 瞳孔质心 x_range={gx_rng:.1f}px y_range={gy_rng:.1f}px ({len(valid)} 有效帧)")
    if max(gx_rng, gy_rng) < 1.0:
        fails.append(f"gaze: 瞳孔未漂移 x={gx_rng:.1f} y={gy_rng:.1f}")
else:
    fails.append(f"gaze: 有效采样帧不足 {len(valid)}")

# ---- 12) 呆毛彩蛋（riku 呆毛发丝质心随晚风颤动）----
riku = personas["riku"]
rg = face_geo(riku["movement"]["face"])
hair_c = hexc(riku["palette"]["hair"])
# 呆毛几何（draw_character 同源）：CAP 段尾 x=hx+88+ax·1.5（ax±5 → 尾端 x 摆 ±7.5），
# y≈hy−ry·1.08；取样框取段尾摆动区（hx+62..hx+104），避开左侧静态发团（止于 hx+51）
ahoge_box = (int(rg["cx"] + 62), int(rg["hy"] - rg["ry"] * 1.34),
             int(rg["cx"] + 104), int(rg["hy"] - rg["ry"] * 0.98))
cents = [gold_centroid("riku", t, ahoge_box, hair_c) for t in (2.2, 2.5, 2.8, 3.1)]
ok_c = [c for c in cents if c is not None]
ahoge_rng = (max(ok_c) - min(ok_c)) if len(ok_c) >= 3 else -1
print(f"[ahoge riku] 呆毛质心 x={[round(c, 1) if c else None for c in cents]} range={ahoge_rng:.1f}px")
if ahoge_rng < 1.0:
    fails.append(f"ahoge: 呆毛未颤动 range={ahoge_rng:.1f}px {cents}")

# ---- 13) 幂等性抽检（不变量⑦/坑⑫：重渲一卡，视频流 framehash 须一致）----
def video_md5(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v",
                        "-f", "hash", "-hash", "md5", "-"], capture_output=True, text=True, check=True)
    return r.stdout.strip()

md5_before = video_md5(OUT / "xiaoman.mp4")
subprocess.run([sys.executable, "-m", "usine.intro_cards", "render", "--only", "xiaoman",
                "--workers", "1"], check=True)
md5_after = video_md5(OUT / "xiaoman.mp4")
print(f"[idempotent xiaoman] framehash before={md5_before[:19]}… after={md5_after[:19]}…")
if md5_before != md5_after:
    fails.append(f"idempotency: 重渲 framehash 不一致 {md5_before} vs {md5_after}")

print()
print("=" * 50)
if fails:
    print("MOTION FAILURES:")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("MOTION QA PASS")
