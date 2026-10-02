#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_char.py — 角色形象专项验收：对照调色板逐区域校验（多邻国风格要素）。
几何从 intro_cards.face_geo 导入（单一事实源，探针永不与渲染漂移）；
支持 hop（mini_jump 起跳）与 walk（走位横向偏移）；
懂帽子/发带/顶戴墨镜/眼镜/鞋饰/腮红（仅活泼型）等规格。"""
import json

from PIL import Image

from intro_cards import face_geo, hexc

P = json.load(open("personas/personas.json", encoding="utf-8"))
personas = {p["id"]: p for p in P["personas"]}


def check(pid, frame, hop=0.0, dx=0.0, verbose=True, probe_crown=True):
    p = personas[pid]
    pal = p["palette"]
    im = Image.open(frame).convert("RGB")
    G = face_geo(p["movement"]["face"])
    u = lambda f: f * G["H"]
    rx, ry = G["rx"], G["ry"]
    hy = G["hy"] - hop
    hx = G["cx"] + dx
    eye_y, eye_dx = G["eye_y"] - hop, G["eye_dx"]
    scl_rx, scl_ry, pup_r = G["scl_rx"], G["scl_ry"], G["pup_r"]
    brow_y = G["brow_y"] - hop
    lift = 7 if p["energy"] == "lively" else 3  # MOOD_FACE 基准抬眉幅度
    acc = {a["code"] for a in p.get("accessories", [])}
    ident = hexc(p["identity"])
    results = []

    def look(name, x, y, want, tol=40):
        px = im.getpixel((int(x), int(y)))
        ok = sum((a - b) ** 2 for a, b in zip(px, want)) ** 0.5 <= tol
        results.append((name, ok, px, want))

    ex = hx - eye_dx  # 左眼中心
    # 头顶采样：有帽/发带者探帽或发带，否则探发色。
    # 起跳顶点时头顶会撞进气泡图层（气泡在前属正常遮挡）→ probe_crown=False 跳过。
    if probe_crown:
        if "sun_hat" in acc:
            look("hat_brim", hx + rx * 0.90, hy - ry * 0.42, (246, 240, 226), 40)
        elif "knit_hat" in acc:
            look("knit_ident", hx, hy - ry * 0.78, ident, 40)
        elif "cap_backward" in acc:
            look("cap_ident", hx, hy - ry * 0.72, ident, 40)
        elif "headband_red" in acc:
            # 弧顶点在包围盒上缘（hy-0.68ry）+ 半描边宽 → 采在描边正中
            look("headband_ident", hx, hy - ry * 0.68 + u(0.022), ident, 46)
        elif "sunglasses_head" in acc:
            look("glasses_perch", hx - 52, hy - ry * 0.76, (44, 44, 52), 55)
            look("hair_top", hx - rx * 0.55, hy - ry * 0.42, hexc(pal["hair"]), 44)
        else:
            look("hair_top", hx, hy - ry * 0.55, hexc(pal["hair"]), 44)
    # 鼻梁：两眼之间（眼内缘 ±54px 之外无眼），嘴/腮红/胡子/耳全避开，全员通用
    look("face_skin", hx, hy + ry * 0.40, hexc(pal["skin"]), 48)
    # 躯干：取左胸点（右手道具常举在右侧/胸前中央）
    look("torso_top", G["cx"] + dx - G["torso_hw"] * 0.5, G["torso_top"] + G["torso_h"] * 0.45 - hop,
         hexc(pal["outfitTop"]), 48)
    look("leg_bottom", G["cx"] + dx - G["leg_cx"], G["torso_top"] + G["torso_h"] + u(0.16) - hop,
         hexc(pal["outfitBottom"]), 48)
    shoe_x = G["cx"] + dx - G["leg_cx"] - G["foot_splay"]
    if "shoe_accent" in acc:
        look("shoe_ident", shoe_x, G["foot_cy"] - hop, ident, 48)
    else:
        look("shoe_dark", shoe_x, G["foot_cy"] - hop, (56, 56, 64), 48)
    look("sclera_white", ex + scl_rx * 0.45, eye_y - scl_ry * 0.45, (255, 255, 255), 34)
    look("pupil_dark", ex, eye_y + pup_r * 0.30, (46, 42, 54), 60)
    look("glint_white", ex - pup_r * 0.47, eye_y - pup_r * 0.53, (255, 255, 255), 60)
    look("brow_charcoal", ex - u(0.02), brow_y - lift, (46, 42, 54), 70)
    if p["gender"] == "female" and p["energy"] == "lively":
        look("blush_pastel", hx - 0.42 * G["WH"], G["blush_y"] - hop, (247, 197, 185), 48)
    n_fail = sum(1 for r in results if not r[1])
    if verbose:
        print(f"== {pid} @ {frame} (hop={hop}, dx={dx}) ==")
        for name, ok, px, want in results:
            print(f"  {'OK ' if ok else '!!!'} {name:16s} px={px} want={want}")
    return n_fail


if __name__ == "__main__":
    import subprocess
    from pathlib import Path

    OUT = Path("build/intro")

    def grab(t, tag):
        png = OUT / f"qa_c_{tag}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(OUT / "xiaoman.mp4"),
                        "-frames:v", "1", str(png)], check=True)
        return str(png)

    f = 0
    f += check("xiaoman", grab(3.0, "3.0"))
    # mini_jump 真实顶点：close_start(=speechEnd+0.15) + 0.275，跳过会被气泡遮挡的头顶采样
    tl = json.loads((OUT / "audio" / "xiaoman.timeline.json").read_text("utf-8"))
    apex = min(tl["speechEnd"] + 0.15, 9.1) + 0.275
    f += check("xiaoman", grab(apex, "apex"), hop=88, probe_crown=False)
    print("TOTAL FAILS:", f)
