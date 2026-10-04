#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_char.py — 角色形象专项验收：对照调色板逐区域校验（多邻国风格要素）。
几何从 intro_cards.face_geo 导入（单一事实源，探针永不与渲染漂移）；
眉形/眼形/视线/颈影/主题色全部与渲染同源（MOOD_FACE/EYE_MOOD/gaze/THEME/mix）；
支持 hop（mini_jump 起跳，jump_height 同源）与 walk（走位横向偏移）；
懂帽子/发带/顶戴墨镜/眼镜/鞋饰/腮红/织带/滑板贴纸/书袋挂饰/膝盖补丁/三色旗（不变量⑩）。

`results_out` 只给 `scripts/verify_shape_fixes.py` 的反向验证用：默认返回失败条数，
反向测试需要逐条结果来确认「失败的到底是哪一条探针」。"""
import json

from PIL import Image

from .intro_cards import (EYE_MOOD, JAW, MOOD_FACE, NECK_SHADE_F, THEME, face_geo, gaze,
                          hexc, jaw_point, jump_height, mix, sunglasses_head_geo)

from .data import personas as _read_personas

personas = _read_personas()   # {id: persona}，经 data.py 统一入口
P = personas                  # 旧别名：本文件历史用法只把它当索引用


def check(pid, frame, hop=0.0, dx=0.0, verbose=True, probe_crown=True, t=None, mood="neutral",
          results_out=None):
    p = personas[pid]
    pal = p["palette"]
    im = Image.open(frame).convert("RGB")
    face = p["movement"]["face"]
    G = face_geo(face)
    u = lambda f: f * G["H"]
    rx, ry = G["rx"], G["ry"]
    hy = G["hy"] - hop
    hx = G["cx"] + dx
    eye_y, eye_dx = G["eye_y"] - hop, G["eye_dx"]
    scl_rx, scl_ry, pup_r = G["scl_rx"], G["scl_ry"], G["pup_r"]
    brow_y = G["brow_y"] - hop
    lift = MOOD_FACE[mood]["lift"]  # 眉形与渲染同源（MOOD_FACE 单一事实源）
    acc = {a["code"] for a in p.get("accessories", [])}
    accf = {a["code"]: a for a in p.get("accessories", [])}
    out = p.get("outfit", {})  # 服装轮廓槽（渲染同源：skirt/tunic/pinafore/vest/buttons）
    skirt = out.get("bottom") == "skirt"
    tunic = out.get("kind") == "tunic"
    pinafore = out.get("kind") == "pinafore"
    vest = out.get("kind") == "vest"
    ident = hexc(p["identity"])
    skin = hexc(pal["skin"])
    eye_k = EYE_MOOD[mood]
    # 视线跟随镜头：瞳孔/高光探针随 gaze 同源偏移（t 缺省＝镜头正中）
    gpx = gaze(pid, t)[0] * (scl_rx - pup_r) * 0.35 if t is not None else 0.0
    gpy = gaze(pid, t)[1] * (scl_ry - pup_r * 1.2) * 0.35 if t is not None else 0.0
    results = []

    def look(name, x, y, want, tol=40):
        px = im.getpixel((int(x), int(y)))
        ok = sum((a - b) ** 2 for a, b in zip(px, want)) ** 0.5 <= tol
        results.append((name, ok, px, want))

    def look_step(name, x, y_in, y_out, want_in, tol=12, min_step=6):
        """阶跃探针（坑㉑）：`y_in` 处的像素既要接近 `want_in`，又要与紧邻的 `y_out` 明显不同。

        存在的理由：深发角色的发色与 metal_dark 镜框的欧氏距离可以小到 8.1
        （omar 发 (43,37,48) vs 镜框 (44,44,52)）——**任何单点颜色比较都恒真**，
        采到纯头发也会 PASS。镜框压在发顶上会造出一条真实的颜色边界，所以改成断言
        这条**边界存在**：框内是金属、框外紧邻处是头发（实测阶跃 8.1）。
        框没画 / 被头发或气泡吞掉 → 两点同色、阶跃 0 → 必定 FAIL。
        min_step 取 6：既低于实测 8.1（留 AA 余量），又远高于「没画」时的 0。
        """
        a = im.getpixel((int(x), int(y_in)))
        b = im.getpixel((int(x), int(y_out)))
        d_in = sum((p - q) ** 2 for p, q in zip(a, want_in)) ** 0.5
        d_step = sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5
        ok = d_in <= tol and d_step >= min_step
        results.append((name, ok, a, f"{want_in} d_in={d_in:.0f}<={tol} d_step={d_step:.0f}>={min_step}"))

    ex = hx - eye_dx  # 左眼中心
    # 头顶采样：有帽/发带者探帽或发带，否则探发色。
    # 起跳顶点时头顶会撞进气泡图层（气泡在前属正常遮挡）→ probe_crown=False 跳过。
    if probe_crown:
        if "sun_hat" in acc:
            look("hat_brim", hx + rx * 0.90, hy - ry * 0.42, THEME["straw"], 40)
        elif "knit_hat" in acc:
            look("knit_ident", hx, hy - ry * 0.78, ident, 40)
        elif "cap_backward" in acc:
            look("cap_ident", hx, hy - ry * 0.72, ident, 40)
        elif "headband_red" in acc:
            # 弧顶点在包围盒上缘（hy-0.68ry）+ 半描边宽 → 采在描边正中；红发带走主题红
            look("headband_red", hx, hy - ry * 0.68 + u(0.022), THEME["headband_red"], 46)
            look("it_flag_green", hx + rx * 0.86 + 3, hy - ry * 0.38, THEME["it_flag"][0], 50)
        elif "sunglasses_head" in acc:
            # 取样点来自 intro_cards.sunglasses_head_geo（与 draw_character 同一份参数）。
            # 旧取样点 `hy - ry*0.76` 落在镜片正中却比 metal_dark → 永远 FAIL（坑㉑）。
            sg = sunglasses_head_geo(G)
            bx, by = sg["probe_band_in"]
            ox, oy = sg["probe_band_out"]
            look_step("glasses_frame", bx, by - hop, oy - hop, THEME["metal_dark"], 12, 6)
            lx, ly = sg["probe_lens"]
            look("glasses_lens", lx, ly - hop, THEME["lens"], 12)
            look("hair_top", hx - rx * 0.55, hy - ry * 0.42, hexc(pal["hair"]), 44)
        else:
            look("hair_top", hx, hy - ry * 0.55, hexc(pal["hair"]), 44)
    # 鼻梁：两眼之间，嘴/腮红/胡子/耳全避开，全员通用
    look("face_skin", hx, hy + ry * 0.40, skin, 48)
    # ---- 脸型轮廓探针（采样点从 intro_cards.jaw_point 派生，与下颌绘制同源） ----
    # 旧的 chin_tip / jaw_square 是手抄的魔数（hy+ry*1.02 / −rx*0.70），
    # 下颌轮廓换成超椭圆后必然漂移——魔数不共享，探针与渲染就会各说各话（坑㉓）。
    if face in JAW:
        jw, jv = jaw_point(face, 0.93)          # 下颌靠底那一段，两种脸型都还是肤色
        look("jaw_low", hx, hy + ry * jv, skin, 48)
        if face == "heart":                     # 圆下巴：同一行两侧也要是肤色（不是针尖）
            look("chin_wide", hx - rx * jw * 0.55, hy + ry * jv, skin, 48)
        else:                                    # 方颌：下颌角内侧必须是肤色（没被外扩削掉）
            look("jaw_corner", hx - rx * jw * 0.80, hy + ry * jv, skin, 48)
    if "beard" not in acc:  # 大胡子遮颈（坑⑨ 遮挡感知：仅 misha 有 beard 配饰，络腮盖住颈前）
        # 颈部：skinShade 压深（NECK_SHADE_F 与渲染同源）；下移 0.03H 避开头底缘/下颌影
        # heart 尖下巴垂到颈前中轴 → 采样点外移至颈侧（尖下巴半宽之外）
        look("neck_shade", hx + (u(0.078) if face == "heart" else 0), G["chin"] + u(0.03) - hop,
             mix(skin, hexc(pal["skinShade"]), NECK_SHADE_F), 48)
    # 躯干：取左胸点（右手道具常举在右侧/胸前中央）；马甲中开缝 → 采中缝露白处
    if vest:
        look("torso_top", G["cx"] + dx, G["torso_top"] + G["torso_h"] * 0.45 - hop,
             hexc(pal["outfitTop"]), 48)
        look("vest_panel", G["cx"] + dx - G["torso_hw"] * 0.44, G["torso_top"] + G["torso_h"] * 0.45 - hop,
             hexc(pal["outfitBottom"]), 48)
    elif pinafore:  # 背带裙护胸盖左胸 → 采护胸与垂臂之间露出的白 T
        look("torso_top", G["cx"] + dx - G["torso_hw"] * 0.64, G["torso_top"] + G["torso_h"] * 0.45 - hop,
             hexc(pal["outfitTop"]), 48)
    else:
        look("torso_top", G["cx"] + dx - G["torso_hw"] * 0.5, G["torso_top"] + G["torso_h"] * 0.45 - hop,
             hexc(pal["outfitTop"]), 48)
    # ---- 下装探针（outfit 槽感知；tunic 下摆过臀 → 腿采样下移） ----
    leg_top_g = G["torso_top"] + G["torso_h"] - u(0.10)
    leg_bot_g = G["foot_cy"] - G["foot_h"] * 0.30
    if skirt:  # A 字裙：裙色在腰下、肤色露腿在摆下
        look("skirt_bottom", G["cx"] + dx, G["torso_top"] + G["torso_h"] + u(0.16) - hop,
             hexc(pal["outfitBottom"]), 48)
        look("leg_skin", G["cx"] + dx - G["leg_cx"],
             leg_top_g + (leg_bot_g - leg_top_g) * 0.85 - hop, skin, 52)
    elif tunic:
        look("tunic_hem", G["cx"] + dx - G["torso_hw"] * 0.5,
             G["torso_top"] + G["torso_h"] * 1.15 - hop, hexc(pal["outfitTop"]), 48)
        look("leg_bottom", G["cx"] + dx - G["leg_cx"],
             G["torso_top"] + G["torso_h"] * 1.30 + u(0.06) - hop, hexc(pal["outfitBottom"]), 48)
    else:
        look("leg_bottom", G["cx"] + dx - G["leg_cx"], G["torso_top"] + G["torso_h"] + u(0.16) - hop,
             hexc(pal["outfitBottom"]), 48)
    shoe_x = G["cx"] + dx - G["leg_cx"] - G["foot_splay"]
    if "shoe_accent" in acc:
        look("shoe_ident", shoe_x, G["foot_cy"] - hop, ident, 48)
    else:
        look("shoe_dark", shoe_x, G["foot_cy"] - hop, THEME["shoe"], 48)
    # 巩膜白：区域采样计数（坑⑨ 遮挡感知——单点会撞镜框边缘/瞳孔位移/镜片反光）
    sbx0, sbx1 = int(ex - scl_rx * 0.78), int(ex + scl_rx * 0.78)
    sby0, sby1 = int(eye_y - scl_ry * eye_k * 0.82), int(eye_y + scl_ry * eye_k * 0.82)
    n_white = sum(1 for yy in range(sby0, sby1, 3) for xx in range(sbx0, sbx1, 3)
                  if im.getpixel((xx, yy)) >= (235, 235, 235))
    results.append(("sclera_white", n_white >= 60, f"{n_white}px", ">=60 开眼白px"))
    look("pupil_dark", ex + gpx, eye_y + gpy + pup_r * 0.30, THEME["ink"], 60)
    look("glint_white", ex + gpx - pup_r * 0.47, eye_y + gpy - pup_r * 0.53, (255, 255, 255), 60)
    look("brow_charcoal", ex - u(0.02), brow_y - lift, THEME["ink"], 70)
    if p["gender"] == "female" and p["energy"] == "lively":
        look("blush_pastel", hx - 0.42 * G["WH"], G["blush_y"] - hop, THEME["blush"], 48)
    # ---- 新视觉特征探针（不变量⑩：新视觉特征 ⇒ 配套探针，采样点从 face_geo 推导）----
    if out.get("buttons"):  # 前襟扣排：采顶扣（胸前置物如手账/墨镜会遮住下扣）
        bcol = mix(hexc(pal["outfitTop"]), THEME["shade_dark"], 0.38)
        look("button_row", G["cx"] + dx, G["torso_top"] + G["torso_h"] * 0.22 - hop, bcol, 55)
    if pinafore:  # 背带裙：护胸＋金色背带扣
        look("pinafore_bib", G["cx"] + dx, G["torso_top"] + G["torso_h"] * 0.35 - hop,
             hexc(pal["outfitBottom"]), 48)
        look("pinafore_buckle", G["cx"] + dx - u(0.115), G["torso_top"] + u(0.096) - hop, THEME["gold"], 50)
    if "zipper" in acc:  # 拉链头（标识色坠）
        look("zipper_pull", G["cx"] + dx, G["torso_top"] + u(0.17) - hop, ident, 55)
    if "clipboard" in acc:  # 胸前夹板：板纸
        look("clip_paper", G["cx"] + dx + G["torso_hw"] * 0.42, G["torso_top"] + u(0.25) - hop,
             THEME["paper"], 50)
    if "towel_shoulder" in acc:  # 肩搭白毛巾
        look("towel_white", G["cx"] + dx - G["torso_hw"], G["torso_top"] - u(0.02) - hop,
             (246, 246, 240), 45)
    if p["hairStyle"] == "short_neat":  # 平直刘海边
        look("fringe_flat", hx - rx * 0.60, hy - ry * 0.42, hexc(pal["hair"]), 44)
    if p["hairStyle"] == "short_part":  # 侧分斜扫刘海
        look("fringe_sweep", hx + rx * 0.10, hy - ry * 0.56, hexc(pal["hair"]), 44)
    for code in ("backpack", "hikingpack", "canvas_backpack"):
        if code in acc and accf[code].get("accent"):  # 标识色织带（挂件行）
            look("strap_ident", G["cx"] - 76, G["torso_top"] + 22 - hop,
                 mix(ident, hexc(pal["outfitTop"]), 0.25), 50)
    if "skateboard" in acc and accf["skateboard"].get("accent"):  # 滑板贴纸（卡05 分镜）
        look("skate_sticker", G["cx"], 1742, ident, 55)
    if "book_tote" in acc and accf["book_tote"].get("accent"):  # 书袋挂饰（卡17 分镜）
        look("tote_charm", G["cx"] + 152, G["torso_top"] + 76 + 92 + 27 - hop, ident, 55)
    sk = p.get("skin", {})
    for pd in sk.get("patches", []):  # 膝盖补丁（皮肤层；位置从腿几何推导）
        if pd.get("on") == "bottom":
            sgn = -1 if pd.get("where") == "knee_L" else 1
            knee_y = (G["torso_top"] + G["torso_h"] - u(0.10) + G["foot_cy"] - G["foot_h"] * 0.30) / 2
            look(f"patch_{pd['where']}", G["cx"] + sgn * G["leg_cx"], knee_y - hop, hexc(pd["color"]), 48)
    n_fail = sum(1 for r in results if not r[1])
    if results_out is not None:      # 反向验证用：让调用方拿到逐条结果
        results_out.extend(results)
    if verbose:
        print(f"== {pid} @ {frame} (hop={hop}, dx={dx}, t={t}, mood={mood}) ==")
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
    f += check("xiaoman", grab(3.0, "3.0"), t=3.0, mood="happy")
    # mini_jump 真实顶点：close_start(=speechEnd+0.15) + 0.275，跳过会被气泡遮挡的头顶采样
    tl = json.loads((OUT / "audio" / "xiaoman.timeline.json").read_text("utf-8"))
    apex = min(tl["speechEnd"] + 0.15, 9.1) + 0.275
    f += check("xiaoman", grab(apex, "apex"), hop=jump_height(personas["xiaoman"]), probe_crown=False)
    print("TOTAL FAILS:", f)
