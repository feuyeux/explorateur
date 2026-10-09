#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_rig.py — 人物 rig 的几何探针反向验证

几何判据跑在 feuille.rig 上（28 项全绿），按其原公式：
A1 颈肩缝（判定窗精确落在颏线下 chin+0.005H…0.10H——正常解剖凹角不算缺陷）、
A2 胯块（取样 x 用 0.80·torso_hw，绝不用 hip_hw：判据 ∌ 被测字段）、
B1 手臂可读（剪影 + 袖色阶差）、B2 头身重叠、
C1/C2 五官可见（抬臂姿态族数五官自身颜色，不数衣色）、
D1/D2/D3 下颌（可见肤色宽 / face_profile 单调 / 斜率内凹）、
E1/E2 胡须（八字胡在场、不下脖子）。

探针自证（纪律 2）：在 A1 判定窗里**人为凿洞** → A1 必须 FAIL；
幂等（不变量⑦）：同参数两渲 PNG 逐字节一致。
第 0 条好数据放行：三名典型人设（心形/方脸/大胡子）全探针通过。

fixture：feuille/personas/personas.json（28 人班底）。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image, ImageDraw

from feuille import rig
from feuille.scenes import SS

ALPHA_THR = 24
HOLE_MIN = 3
JAW_OPEN_MIN = 0.30
RAISED_POSES = ("wave", "ciao_wave", "thumbs_up", "hand_shoot", "point", "both_hands")
W, H = rig.W, rig.H

PERSONAS = json.loads((ROOT / "personas" / "personas.json").read_text("utf-8"))["personas"]


def np_abs(a):
    return np.abs(a)


def render_persona(p, *, mood="neutral", openness=0.0, blink=False, pose=None):
    """渲一张人物层（RGBA，1080×1920，与成片坐标一致）——qa_shape 同款口径。"""
    layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ctx = dict(scale=1.0, xoff=0.0, yoff=0.0, squash=0.0, xscale=1.0,
               head_dx=0, head_dy=0, brow_lift_extra=0, pose=dict(pose or {}),
               openness=openness, blink=blink, mood=mood, ss=SS)
    rig.draw_character(layer, ld, p, 0.0, ctx)
    return layer.resize((W, H), Image.Resampling.BOX)


def holes_in_band(mask, y0, y1, xlo, xhi, skip_center=None):
    """逐行找「夹在实心像素之间的透明游程」＝剪影空洞（轮廓外背景不算）。
    skip_center：胯部两腿之间是合法空洞，不排除会全员误判。"""
    out = []
    for y in range(max(0, y0), min(mask.shape[0], y1)):
        row = mask[y]
        lo, hi = max(0, xlo), min(mask.shape[1] - 1, xhi)
        if skip_center:
            cx, r = skip_center
            seg_l = [i for i in range(lo, min(hi, cx - r)) if row[i] <= ALPHA_THR]
            seg_r = [i for i in range(max(lo, cx + r), hi) if row[i] <= ALPHA_THR]
        else:
            seg_l = [i for i in range(lo, hi) if row[i] <= ALPHA_THR]
            seg_r = seg_l
        for seg in (seg_l, seg_r):
            run = []
            for x in seg + [None]:
                if x is not None and (not run or x == run[-1] + 1):
                    run.append(x)
                    continue
                if len(run) >= HOLE_MIN:
                    if (run[0] - 1 >= 0 and row[run[0] - 1] > ALPHA_THR
                            and run[-1] + 1 < mask.shape[1] and row[run[-1] + 1] > ALPHA_THR):
                        out.append((int(run[0]), int(run[-1]), y))
                run = []
    return out


def count_near(arr, ref, tol=18):
    return int((np_abs(arr - ref).max(axis=2) <= tol).sum())


def face_windows(G):
    cx = G["cx"]
    mw, mh = G["WH"] * 0.26, G["H"] * 0.115
    eyes = [(cx - G["eye_dx"] - G["scl_rx"] * 1.15, G["eye_y"] - G["scl_ry"] * 1.25,
             cx - G["eye_dx"] + G["scl_rx"] * 1.15, G["eye_y"] + G["scl_ry"] * 1.25),
            (cx + G["eye_dx"] - G["scl_rx"] * 1.15, G["eye_y"] - G["scl_ry"] * 1.25,
             cx + G["eye_dx"] + G["scl_rx"] * 1.15, G["eye_y"] + G["scl_ry"] * 1.25)]
    return {"mouth": (cx - mw, G["mouth_y"] - mh, cx + mw, G["mouth_y"] + mh), "eyes": eyes}


def probe_a1(mask, G) -> int:
    band = holes_in_band(mask, int(G["chin"] + G["H"] * 0.005), int(G["chin"] + G["H"] * 0.10),
                         int(G["cx"] - G["sh_out"] * 1.15), int(G["cx"] + G["sh_out"] * 1.15),
                         skip_center=(int(G["cx"]), int(G["H"] * 0.115)))
    return max((b - a + 1 for a, b, _ in band), default=0)


def probe_person(p) -> list[tuple[bool, str]]:
    """一名人物的全部探针（qa_shape 公式）。"""
    res = []
    face = p["movement"]["face"]
    G = rig.face_geo(face)
    has_beard = "beard" in {a["code"] for a in p.get("accessories", [])}
    tunic = (p.get("outfit") or {}).get("kind") == "tunic"
    torso_bot = G["torso_top"] + G["torso_h"] * (1.30 if tunic else 1.0)
    sh_y = G["torso_top"] + G["sh_dy"]

    base = render_persona(p, openness=0.0)
    mask = np.asarray(base.getchannel("A"))
    arr = np.asarray(base.convert("RGB")).astype(int)

    # A1 颈肩缝
    worst = probe_a1(mask, G)
    res.append((worst <= HOLE_MIN, f"{p['id']} A1 颈肩缝最宽 {worst}px（须 ≤{HOLE_MIN}）"))

    # A2 胯块：上色 + 腿根不断
    y_probe = int(torso_bot + G["H"] * 0.12)
    x_probe = int(G["cx"] + G["torso_hw"] * 0.80)
    hit = count_near(arr[max(0, y_probe - 3):y_probe + 3, max(0, x_probe - 3):x_probe + 3],
                     rig.hexc(p["palette"]["outfitBottom"]), 40)
    hip_band = holes_in_band(mask, int(torso_bot - G["H"] * 0.16), int(torso_bot + G["H"] * 0.10),
                             int(G["cx"] - G["torso_hw"] * 0.72), int(G["cx"] + G["torso_hw"] * 0.72),
                             skip_center=(int(G["cx"]), int(G["leg_cx"] - G["leg_w"] * 0.35)))
    worst_hip = max((b - a + 1 for a, b, _ in hip_band), default=0)
    res.append((hit >= 25 and worst_hip <= HOLE_MIN,
                f"{p['id']} A2 胯块 {hit}/36px 且腿根缝 {worst_hip}px（须 ≥25 且 ≤{HOLE_MIN}）"))

    # B1 手臂可读
    rest_a1 = G["arm_rest"][0]
    arm_outer = G["sh_x"] + math.sin(math.radians(rest_a1)) * G["up_len"] * 0.85 + G["arm_w"] * 0.5
    protr = arm_outer - G["torso_hw"]
    y_s = int(sh_y + G["up_len"] * 0.55)
    xs = int(G["cx"] + G["torso_hw"] + G["arm_w"] * 0.14)
    patch = arr[max(0, y_s - 5):y_s + 5, max(0, xs - 3):xs + 3]
    tone = int(np_abs(patch - rig.hexc(p["palette"]["outfitTop"])).max()) if patch.size else 0
    res.append((protr >= G["arm_w"] * 0.22 and tone >= 10,
                f"{p['id']} B1 手臂探出 {protr:.1f}px、袖色阶差 {tone}（须 ≥{G['arm_w'] * 0.22:.1f}px 且 ≥10）"))

    # B2 头身重叠
    overlap = sh_y - (G["chin"] - G["H"] * 0.02)
    res.append((overlap >= G["H"] * 0.02,
                f"{p['id']} B2 下颌压过肩线 {overlap:.1f}px（须 ≥{G['H'] * 0.02:.1f}）"))

    # D1 下颌开口（大胡子合法盖住，跳过）
    y_jaw = int(G["hy"] + G["ry"] * 0.90)
    row = arr[y_jaw, max(0, int(G["cx"] - G["rx"] * 1.3)):int(G["cx"] + G["rx"] * 1.3)]
    is_skin = np_abs(row - rig.hexc(p["palette"]["skin"])).max(axis=1) <= 26
    idx = np.flatnonzero(is_skin)
    half_jaw = (float(idx.max() - idx.min()) / 2.0 / G["rx"]) if idx.size else 0.0
    res.append((has_beard or half_jaw >= JAW_OPEN_MIN,
                f"{p['id']} D1 可见肤色半宽 {half_jaw:.2f}·rx"
                + ("（skip：大胡子合法盖住）" if has_beard else f"（须 ≥{JAW_OPEN_MIN}）")))

    # D2/D3 下颌单调与内凹（查几何函数，免疫发量遮挡）
    face = p["movement"]["face"]
    worst_grow = 0.0
    prev = rig.face_profile(face, 0.0)
    for i in range(1, 61):
        cur = rig.face_profile(face, i / 60.0)
        worst_grow = max(worst_grow, cur - prev)
        prev = cur
    res.append((worst_grow <= 1e-6, f"{p['id']} D2 face_profile 回涨 {worst_grow:.4f}（须 0）"))
    v_end = rig.JAW[face]["y1"] if face in rig.JAW else 1.0
    vals = [rig.face_profile(face, v_end * i / 60.0) for i in range(61)]
    prev_d, worst_curve = None, 0.0
    for i in range(len(vals) - 1):
        dcur = vals[i + 1] - vals[i]
        if prev_d is not None:
            worst_curve = max(worst_curve, dcur - prev_d)
        prev_d = dcur
    res.append((worst_curve <= 1e-9, f"{p['id']} D3 斜率增量 {worst_curve:.4f}（须 ≤0）"))

    # E1/E2 胡须
    if has_beard:
        beard_c = rig.mix(rig.hexc(p["palette"]["hair"]), rig.hexc(p["palette"]["skin"]), 0.25)
        is_beard = lambda y: count_near(arr[int(y) - 2:int(y) + 3,
                                            max(0, int(G["cx"] - G["rx"] * 1.3)):int(G["cx"] + G["rx"] * 1.3)],
                                       tuple(int(v) for v in beard_c), 20)
        below = is_beard(G["chin"] + G["ry"] * 0.10)
        above = is_beard(G["mouth_y"] - G["ry"] * 0.15)
        res.append((below == 0, f"{p['id']} E1 颏线下胡须色 {below}px（须 0——不下脖子）"))
        res.append((above >= 25, f"{p['id']} E2 嘴上八字胡 {above}px（须 ≥25）"))
    return res


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []

    def pick(pred, what):
        for p in PERSONAS:
            if pred(p):
                return p
        raise SystemExit(f"夹具里找不到{what}")

    p_heart = pick(lambda p: p["movement"]["face"] == "heart"
                   and "beard" not in {a["code"] for a in p.get("accessories", [])}, "心形脸")
    p_beard = pick(lambda p: "beard" in {a["code"] for a in p.get("accessories", [])}, "大胡子")
    p_square = pick(lambda p: p["movement"]["face"] == "square", "方脸")

    # ---- 0. 好数据放行：三名典型人设全探针 ----
    for p in (p_heart, p_beard, p_square):
        rows.extend(probe_person(p))

    # ---- 1. C1/C2 五官可见（抬臂姿态族，qa_shape 口径：数五官自己的颜色）----
    G = rig.face_geo(p_heart["movement"]["face"])
    fw = face_windows(G)
    mx0, my0, mx1, my1 = (int(v) for v in fw["mouth"])
    mouth_px = max(0.16 * (mx1 - mx0) * (my1 - my0), 24)
    scl_px = 0.16 * (fw["eyes"][0][2] - fw["eyes"][0][0]) * (fw["eyes"][0][3] - fw["eyes"][0][1])
    worst_m, worst_e = None, None
    for code in RAISED_POSES:
        pose = dict(rig.pose_for(code, 0.5, 0.0, p_heart))
        lay = render_persona(p_heart, mood="happy", openness=0.9, pose=pose)
        arr = np.asarray(lay.convert("RGB")).astype(int)
        sub_m = arr[my0:my1, mx0:mx1]
        m_cnt = max(count_near(sub_m, rig.THEME["mouth"]), count_near(sub_m, rig.THEME["tongue"]),
                    count_near(sub_m, rig.THEME["ink"]))
        e_cnt = sum(count_near(arr[int(ey0):int(ey1), int(ex0):int(ex1)], (255, 255, 255), 12)
                    for (ex0, ey0, ex1, ey1) in fw["eyes"])
        if m_cnt < mouth_px and (worst_m is None or m_cnt / mouth_px < worst_m[1]):
            worst_m = (code, m_cnt / mouth_px)
        if e_cnt < scl_px and (worst_e is None or e_cnt / scl_px < worst_e[1]):
            worst_e = (code, e_cnt / scl_px)
    rows.append((worst_m is None,
                 f"C1 抬臂姿态族嘴部可见（最差 "
                 f"{worst_m[0]} {worst_m[1] * 100:.0f}% ← 遮嘴" if worst_m else
                 "C1 抬臂姿态族（6 姿态）嘴部均可见"))
    rows.append((worst_e is None,
                 f"C2 抬臂姿态族眼部可见（最差 "
                 f"{worst_e[0]} {worst_e[1] * 100:.0f}% ← 遮眼" if worst_e else
                 "C2 抬臂姿态族（6 姿态）眼部均可见"))

    # ---- 2. 探针自证：A1 判定窗凿洞 → A1 必须 FAIL ----
    G1 = rig.face_geo(p_heart["movement"]["face"])
    base = render_persona(p_heart)
    damaged = base.copy()
    hole_y0 = int(G1["chin"] + G1["H"] * 0.01)
    hole_y1 = int(G1["chin"] + G1["H"] * 0.035)
    hole_x0 = int(G1["cx"] + G1["sh_out"] * 0.4)
    hole_x1 = hole_x0 + 12
    px = damaged.load()
    for y in range(hole_y0, hole_y1):
        for x in range(hole_x0, hole_x1):
            px[x, y] = (0, 0, 0, 0)
    worst = probe_a1(np.asarray(damaged.getchannel("A")), G1)
    rows.append((worst >= HOLE_MIN,
                 f"探针自证：颏线下凿 12px 洞 → A1 报 {worst}px（须 ≥{HOLE_MIN}——探针不瞎）"))

    # ---- 3. 幂等：同参数两渲逐字节一致 ----
    a = render_persona(p_heart, pose=dict(rig.pose_for("wave", 0.5, 0.0, p_heart)))
    b = render_persona(p_heart, pose=dict(rig.pose_for("wave", 0.5, 0.0, p_heart)))
    import io
    ba = io.BytesIO(); bb = io.BytesIO()
    a.save(ba, "PNG"); b.save(bb, "PNG")
    rows.append((ba.getvalue() == bb.getvalue(),
                 "幂等：同参数两渲 PNG 逐字节一致（不变量⑦）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("人物 rig 几何探针（A1/A2/B1/B2/C/D/E + 探针自证 + 幂等）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：rig 探针 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
