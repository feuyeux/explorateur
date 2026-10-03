#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_shape.py — 人物层「形状 / 连接 / 图层」几何探针

**为什么要有**：render-handbook §4 的既有探针（qa_char/qa_all）都在**成片**上跑，
而头/身/手臂的几何缺陷长在**人物层**上——成片里被气泡与名牌盖住，压在 mp4 里
只能靠肉眼逐卡看。坑⑪（肩点浮在躯干外）/ 坑⑮（袖子遮嘴）都是这类。
本模块把人物层**单独**渲一张（同一 `draw_character`、同一坐标空间 = 成片坐标），
再用几何探针把三类问题量化。

**探针纪律**（render-handbook §4）：
- 采样窗口全部从 `face_geo()` 派生，**永不手抄坐标**；
- **连接类只看 alpha**，不按颜色数像素——浅米裤压暖白底会被误判（坑⑰同源教训）；
- **图层类用哨兵色**：把 `outfitTop` 换成哨兵再渲，脸窗里出现哨兵 = 有衣层画在人脸之前。

探针分组：
  A 连接（alpha 空洞）  neck_hole / hip_hole
  B 形状（几何量纲）    arm_protrusion / head_hover
  C 图层（哨兵色）      sleeve_over_face

用法：
  uv run python -m usine.qa_shape              # 28 人全量
  uv run python -m usine.qa_shape --only xiaoman
  uv run python -m usine.qa_shape --json       # 机器可读
"""
import argparse
import json
import math
import sys

from usine.intro_cards import (H as CANVAS_H, JAW, W as CANVAS_W, SS, face_geo, face_profile,
                               hexc, load_data, mix)

# 探针在**成片坐标系**（scale=1）上跑：数字可直接与成片/qa_all 对照
PROBE_SCALE = 1.0
ALPHA_THR = 24          # alpha 阈值：人物层是纯平涂，实心区=255（不透明边界由 BOX 降采样给出）
HOLE_MIN = 3            # 空洞最小宽度（px）：抗锯齿边缘的 1–2px 抖动不算缺陷
JAW_OPEN_MIN = 0.30     # D1：颏线上方可见肤色半宽下限（相对 rx）。旧心形 0.19 / 发帘夹脸 0.17

# 图层探针：抬臂姿态族（坑⑮ 的真实回归场景——袖子胶囊扫过嘴位）
RAISED_POSES = ("wave", "ciao_wave", "thumbs_up", "hand_shoot", "point", "both_hands")
SENTINEL = (255, 0, 255)    # 哨兵衣色：人设调色板里不可能出现的洋红


# ---------- 渲染与取样 ----------


def render_persona(p, card, mood="neutral", openness=0.9, blink=False, pose=None,
                   scale=PROBE_SCALE, sentinel_top=False):
    """渲一张人物层（RGBA，返回 1080x1920，与成片坐标一致）。"""
    from PIL import Image, ImageDraw
    from usine.intro_cards import draw_character
    pp = json.loads(json.dumps(p))          # 深拷贝：哨兵色只污染本次渲染
    if sentinel_top:
        pp["palette"]["outfitTop"] = "#%02x%02x%02x" % SENTINEL
    layer = Image.new("RGBA", (CANVAS_W * SS, CANVAS_H * SS), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ctx = dict(scale=scale, xoff=0.0, yoff=0.0, squash=0.0, xscale=1.0,
               head_dx=0, head_dy=0, brow_lift_extra=0, pose=dict(pose or {}),
               openness=openness, blink=blink, mood=mood, ss=SS)
    draw_character(layer, ld, pp, 0.0, ctx)
    return layer.resize((CANVAS_W, CANVAS_H), Image.Resampling.BOX)


def _np(img, mode):
    import numpy as np
    return np.asarray(img.convert(mode))


def np_abs(a):
    import numpy as np
    return np.abs(a)


def _flatnonzero(a):
    import numpy as np
    return np.flatnonzero(a)


ANNOT = (255, 0, 0)        # 标注框：探针判定的缺陷位置


def annotate(p, card, out_path):
    """把探针判定的缺陷**画出来**：红框 = 探针指的洞，绿框 = 脸窗（哨兵侵入区）。

    探针纪律的另一半：**先证明探针指对了地方，再照着改代码**——
    手上没有这张图就动手，等于在赌探针没假失败（坑⑨ 三次假失败的教训）。
    """
    from PIL import Image, ImageDraw
    from usine.intro_cards import pose_for
    G = face_geo(p["movement"]["face"])
    cx, Hh = G["cx"], G["H"]
    sh_y = G["torso_top"] + G["sh_dy"]
    tunic = (p.get("outfit") or {}).get("kind") == "tunic"
    torso_bot = G["torso_top"] + G["torso_h"] * (1.30 if tunic else 1.0)
    base = render_persona(p, card, mood="neutral", openness=0.0)
    mask = alpha_mask(base)
    fig = Image.new("RGB", base.size, (250, 248, 243))
    fig.paste(base, (0, 0), base)
    d = ImageDraw.Draw(fig)

    for (x0, x1, y) in holes_in_band(mask, int(G["chin"] - Hh * 0.10), int(sh_y + Hh * 0.04),
                                     int(cx - G["rx"] * 1.5), int(cx + G["rx"] * 1.5),
                                     skip_center=(int(cx), int(Hh * 0.115))):
        d.rectangle([x0 - 1, y - 1, x1 + 1, y + 1], outline=ANNOT)
    for (x0, x1, y) in holes_in_band(mask, int(torso_bot - Hh * 0.16), int(torso_bot + Hh * 0.10),
                                     int(cx - G["rx"] * 1.6), int(cx + G["rx"] * 1.6),
                                     skip_center=(int(cx), int(G["leg_cx"] - G["leg_w"] * 0.35))):
        d.rectangle([x0 - 1, y - 1, x1 + 1, y + 1], outline=ANNOT)
    # 脸窗（哨兵探针的判定区）——绿框，便于确认「袖子扫到的是不是这里」
    fw = face_windows(G)
    for w in fw["eyes"] + [fw["mouth"]]:
        d.rectangle([w[0], w[1], w[2], w[3]], outline=(0, 150, 0))
    fig.save(out_path)
    return out_path


def alpha_mask(layer):
    import numpy as np
    return np.asarray(layer.getchannel("A"))


def holes_in_band(mask, y0, y1, xlo, xhi, skip_center=None):
    """逐行找「夹在实心像素之间的透明游程」= 剪影空洞（不是轮廓外的背景）。

    skip_center=(cx, r)：跳过 |x−cx| < r 的列——胯部两腿之间是**合法**的空洞，
    不排除会把每个人都判 fail（这条是踩出来的：胯缝不是缺陷）。
    """
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
                    # 必须是「夹心」：两侧都要有实心像素，否则是轮廓外背景
                    if (run[0] - 1 >= 0 and row[run[0] - 1] > ALPHA_THR
                            and run[-1] + 1 < mask.shape[1] and row[run[-1] + 1] > ALPHA_THR):
                        out.append((int(run[0]), int(run[-1]), y))
                run = []
    return out


def face_windows(G):
    """五官窗口（判「五官是否还看得见」用），全部从 face_geo 派生。"""
    cx = G["cx"]
    mw = G["WH"] * 0.26
    mh = G["H"] * 0.115
    eyes = [(cx - G["eye_dx"] - G["scl_rx"] * 1.15, G["eye_y"] - G["scl_ry"] * 1.25,
             cx - G["eye_dx"] + G["scl_rx"] * 1.15, G["eye_y"] + G["scl_ry"] * 1.25),
            (cx + G["eye_dx"] - G["scl_rx"] * 1.15, G["eye_y"] - G["scl_ry"] * 1.25,
             cx + G["eye_dx"] + G["scl_rx"] * 1.15, G["eye_y"] + G["scl_ry"] * 1.25)]
    return {"mouth": (cx - mw, G["mouth_y"] - mh, cx + mw, G["mouth_y"] + mh), "eyes": eyes}


def _count_near(arr, ref, tol=18):
    """窗口内接近目标色的像素数（纯平涂 + BOX 降采样，内部是精确色，边缘有混色）。"""
    return int((np_abs(arr - ref).max(axis=2) <= tol).sum())


# ---------- 探针 ----------


def probe_persona(p, card, damage=None):
    """一个人物的全部探针结果。返回 (results, info)。

    damage={"A1": (x0,y0,x1,y1), ...}：在判定窗里**人为凿一个透明洞**，
    用于验证探针灵敏度（`scripts/verify_shape_fixes.py` 的反向测试）——
    把窗口收窄到失灵时，靠的就是这条。
    """
    from usine.intro_cards import pose_for
    G = face_geo(p["movement"]["face"])
    face = p["movement"]["face"]
    cx = G["cx"]
    Hh = G["H"]
    rx, ry, hy = G["rx"], G["ry"], G["hy"]
    mouth_y = G["mouth_y"]
    sh_y = G["torso_top"] + G["sh_dy"]
    # torso_bot 与 draw_character 同源复算（长衫下摆过臀，outfit.kind=tunic）
    tunic = (p.get("outfit") or {}).get("kind") == "tunic"
    torso_bot = G["torso_top"] + G["torso_h"] * (1.30 if tunic else 1.0)
    res = []

    # ---- 基准渲染（静止姿态，闭嘴，用于形状/连接） ----
    base = render_persona(p, card, mood="neutral", openness=0.0)
    if damage:
        base = base.copy()
        px = base.load()
        for box in damage.values():
            x0, y0, x1, y1 = (int(v) for v in box)
            for y in range(max(0, y0), min(base.height, y1)):
                for x in range(max(0, x0), min(base.width, x1)):
                    px[x, y] = (0, 0, 0, 0)
    mask = alpha_mask(base)
    arr = _np(base, "RGB").astype(int)      # A2/B1 都要取色，只解析一次

    # A1 颈肩接缝：判定窗精确落在**颏线正下方**这一小段（chin+0.005H … chin+0.06H）。
    #
    # 为什么不是「下巴到肩线整段」：下颌与肩之间天然有一道细楔形凹角（侧影上
    # 颏线处最宽 ≈sh_out、向上 0.04H 内收成尖），那是解剖不是缺陷——早期版本
    # 按「整段最大空洞宽度」判，把这道正常凹角和真缺陷混在一起，28 人全 FAIL，
    # 收容差又会放到真缺陷漏过去。
    # 真缺陷的位置是唯一的：旧肩楔外边斜率太缓，**颏线以下到臂根胶囊顶**之间
    # 露出一条背景缝（nikos 实测 y=1342–1352，即 chin+0.01H…chin+0.035H，宽 49px）。
    band = holes_in_band(mask, int(G["chin"] + Hh * 0.005), int(G["chin"] + Hh * 0.10),
                         int(cx - G["sh_out"] * 1.15), int(cx + G["sh_out"] * 1.15),
                         skip_center=(int(cx), int(Hh * 0.115)))
    worst = max((b - a + 1 for a, b, _ in band), default=0)
    res.append(dict(probe="A1 neck_shoulder_seam", ok=worst <= HOLE_MIN,
                    value=worst, need=HOLE_MIN,
                    detail=f"颏线下肩缝 {len(band)} 处，最宽 {worst}px（须 ≤{HOLE_MIN}）"))

    # A2 胯部：两条独立不变量
    #
    # (a) **胯块真的上在躯干下缘**：采样点取 (cx ± 0.80·torso_hw, torso_bot+0.12H)，须是下装色。
    #     旧版没有胯块，躯干底缘被 0.62·torso_hw 的大圆角收成 ±0.38·torso_hw，比腿的外缘还窄
    #     ——剪影上就是「裤子浮在空中」（初版总览图肉眼可见）。
    #     **别用「alpha 夹心洞」测这条**：圆角收窄造成的是外侧凹口不是夹心洞，判不出来
    #     （初版 A2 的 26 人 FAIL 绝大多数其实是「手与体侧的缝」）。
    #     也**别用「剪影够宽」测**：手比胯块更宽，注回旧 hip_hw 时仍然「够宽」，探针失灵
    #     （实测只命中 2/28）。
    #     **取样 x 绝不能用 hip_hw**：0.80·hip_hw 在注回旧值时跟着内缩到腿里，
    #     而腿与下装同色 → 探针恒真（实测只命中 1/28）。改用 0.80·torso_hw：
    #     它落在新胯块内（0.92·torso_hw）、旧胯块外（≈leg_cx+leg_w·0.62）、腿外缘外，
    #     是唯一能区分新旧的位置——实测现行 56/56 中、注回旧值只剩 14/56。
    # (b) **腿根不断**：躯干下缘到腿根之间不得有夹心洞。扫描窗用 torso_hw·0.72
    #     （同样**不依赖 hip_hw**，理由同上）。
    y_probe = int(torso_bot + Hh * 0.12)
    x_probe = int(cx + G["torso_hw"] * 0.80)
    want_bottom = hexc(p["palette"]["outfitBottom"])
    hit = _count_near(arr[max(0, y_probe - 3):y_probe + 3, max(0, x_probe - 3):x_probe + 3],
                      want_bottom, 40)
    ok_reach = hit >= 25
    hip_band = holes_in_band(mask, int(torso_bot - Hh * 0.16), int(torso_bot + Hh * 0.10),
                             int(cx - G["torso_hw"] * 0.72), int(cx + G["torso_hw"] * 0.72),
                             skip_center=(int(cx), int(G["leg_cx"] - G["leg_w"] * 0.35)))
    worst_hip = max((b - a + 1 for a, b, _ in hip_band), default=0)
    ok_hip = worst_hip <= HOLE_MIN
    res.append(dict(probe="A2 hip_connection", ok=ok_reach and ok_hip,
                    value=f"{hit}/25px/{worst_hip}px", need="≥25 / ≤3",
                    detail=(f"躯干下缘胯块上色 {hit}/36 像素（须 ≥25 = 下装色）"
                            + ("" if ok_hip else f"；腿根处 {len(hip_band)} 处空洞，最宽 {worst_hip}px"))))

    # B1 手臂可读性：光有剪影不够，纯平涂无描边（不变量⑤），叠在躯干上的那段
    #    必须靠**色阶**才读得出来。两条同时成立才算「看得出手臂」：
    #    (a) 剪影——上臂探出躯干轮廓 ≥0.22·arm_w（几何量，从 face_geo 解析算）
    #    (b) 色阶——躯干轮廓外侧那条采样带的颜色与衣色差 ≥10/通道
    rest_a1 = G["arm_rest"][0]
    arm_outer = G["sh_x"] + math.sin(math.radians(rest_a1)) * G["up_len"] * 0.85 + G["arm_w"] * 0.5
    protr = arm_outer - G["torso_hw"]
    need_protr = G["arm_w"] * 0.22
    ok_geo = protr >= need_protr
    top_c = hexc(p["palette"]["outfitTop"])
    y_s = int(sh_y + G["up_len"] * 0.55)
    xs = int(cx + G["torso_hw"] + G["arm_w"] * 0.14)
    patch = arr[max(0, y_s - 5):y_s + 5, max(0, xs - 3):xs + 3]
    tone = int(np_abs(patch - top_c).max()) if patch.size else 0
    ok_tone = tone >= 10
    res.append(dict(probe="B1 arm_readable", ok=ok_geo and ok_tone,
                    value=f"{protr:.1f}px/{tone}", need=f"≥{need_protr:.1f}px/≥10",
                    detail=(f"上臂探出躯干 {protr:.1f}px（需 ≥{need_protr:.1f}）"
                            f"{'；' if ok_geo else '；'}袖色与衣色差 {tone}/通道（需 ≥10）"
                            + ("" if ok_geo else " ← 剪影不足") + ("" if ok_tone else " ← 与衣同色，手臂读不出来"))))

    # B2 头身重叠：下颌线必须压在肩线之上（有重叠量 = 头坐在肩上而非浮空）
    overlap = sh_y - (G["chin"] - Hh * 0.02)
    res.append(dict(probe="B2 head_hover", ok=overlap >= Hh * 0.02,
                    value=round(float(overlap), 1), need=round(Hh * 0.02, 1),
                    detail=f"下颌压过肩线 {overlap:.1f}px"))

    # D1 下颌开口：颏线上方那一行的**肤色**半宽必须够（坑㉓「下巴太尖」的真实口径）
    #
    # 判「肤色」而不是「剪影」：尖下巴有两条成因，只看剪影只能抓到一条——
    #   (a) heart 型的下颌多边形在顶点折返成横向针尖；
    #   (b) 长发帘内缘跟着收窄的下颌走到中轴，把脸夹成尖楔（脸本身是正常椭圆）。
    # (b) 的剪影完全正常，只有量「可见肤色宽度」才抓得到。
    # 采样行取 hy+0.90·ry：足够低（尖下巴在这里已经收没了），又还在下颌范围内。
    # **大胡子角色跳过**：络腮本来就该盖住下颌，这条守的是「脸有没有被夹住」，胡子不算夹
    # （qa_char 的 neck_shade 探针同样按 beard 在场与否分流）。
    has_beard = "beard" in {a["code"] for a in p.get("accessories", [])}
    y_jaw = int(hy + ry * 0.90)
    skin_c = hexc(p["palette"]["skin"])
    row = arr[y_jaw, max(0, int(cx - rx * 1.3)):int(cx + rx * 1.3)]
    is_skin = np_abs(row - skin_c).max(axis=1) <= 26
    idx = _flatnonzero(is_skin)
    half_jaw = (float(idx.max() - idx.min()) / 2.0 / rx) if idx.size else 0.0
    ok_jaw = has_beard or half_jaw >= JAW_OPEN_MIN
    res.append(dict(probe="D1 jaw_open", ok=ok_jaw,
                    value=("skip(beard)" if has_beard else round(half_jaw, 3)), need=JAW_OPEN_MIN,
                    detail=("大胡子：络腮合法盖住下颌，跳过" if has_beard else
                            f"颏线上 {1 - 0.90:.2f}ry 处可见肤色半宽 {half_jaw:.2f}·rx"
                            f"（须 ≥{JAW_OPEN_MIN}）" + ("" if ok_jaw else " ← 下巴收成尖 / 被头发夹住"))))

    # D2 下颌单调：脸颊以下的**脸**半宽只能变窄，绝不能重新外扩（坑㉓「脸被拉两边」）
    #
    # 旧 square 下颌是一个六点多边形，顶点落在 ±0.92·rx —— 那个高度的椭圆只有 0.60·rx，
    # 于是脸从 0.80·rx 反弹到 0.92·rx，被「拉」出两个尖角。
    # **查几何函数而不是查像素**：`face_profile()` 与下颌绘制同源，天然免疫发量遮挡
    # （第一版拿「可见肤色」量，8 个长发角色被发量一挡就误判成下颌外扩）。
    worst_grow, at_v = 0.0, 0.0
    prev = face_profile(face, 0.0)
    for i in range(1, 61):
        v = i / 60.0
        cur = face_profile(face, v)
        if cur - prev > worst_grow:
            worst_grow, at_v = cur - prev, v
        prev = cur
    ok_mono = worst_grow <= 1e-6
    res.append(dict(probe="D2 jaw_monotone", ok=ok_mono,
                    value=round(float(worst_grow), 4), need=0.0,
                    detail=(f"face_profile 最大回涨 {worst_grow:.3f}·rx @v={at_v:.2f}（须 0）"
                            + ("" if ok_mono else " ← 下颌外扩，脸被拉宽"))))

    # D3 下颌内凹：轮廓斜率只能越来越陡，绝不能在下巴处「躺平」再折返（坑㉓ 横向针尖）
    #
    # 旧心形 x(t)=1−1.2t+0.2t² 的二阶导 **+0.4 > 0**（外凸）——曲线越往下越平，
    # 到顶点时切线水平，左右两支折返成一根横刺。
    # 注意 **D1 抓不到它**：旧形在 v=0.90 处还有 0.43·rx，够宽；针尖只存在于最后那 4px。
    # 超椭圆 m>1 的二阶导恒为负（内凹），底部切线竖直 → 光滑圆底。
    # 扫描上限取 `y1`（下颌真正的底缘）：再往下 face_profile 被钳成常数 0，
    # 那是「脸到此为止」的截断，不是形状，量它会造出一个假的斜率突变。
    v_end = JAW[face]["y1"] if face in JAW else 1.0
    prev_d, worst_curve = None, 0.0
    vals = [face_profile(face, v_end * i / 60.0) for i in range(61)]
    for i in range(len(vals) - 1):
        d = vals[i + 1] - vals[i]                      # 斜率
        if prev_d is not None:
            worst_curve = max(worst_curve, d - prev_d)  # 斜率增量：>0 = 斜率变缓 = 外凸
        prev_d = d
    ok_conc = worst_curve <= 1e-9
    res.append(dict(probe="D3 jaw_concave", ok=ok_conc,
                    value=round(float(worst_curve), 4), need=0.0,
                    detail=(f"face_profile 最大斜率增量 {worst_curve:.4f}（须 ≤0，越负越内凹）"
                            + ("" if ok_conc else " ← 斜率变缓 = 下巴外凸折返成横向针尖"))))

    # E1/E2 胡须（只对有 beard 配饰的人跑）
    #
    # 旧胡须是一个 PIE：顶边 0.82·ry 的一条水平直弦、底边伸到 1.30·ry（比下巴低 52px），
    # 整张脸从嘴以下糊成一条围兜一直糊到脖子上——「嘴像长在脖子上」（坑㉓）。
    #   E1 守「不许下过脖子」：胡须色在 chin+0.10·ry 以下必须为 0 像素。
    #   E2 守「八字胡存在」：胡须色必须出现在嘴**上方**（旧 PIE 顶边在嘴下面 0.19·ry，
    #      嘴上什么都没有，一眼就看出少了八字胡）。
    beard_c = mix(hexc(p["palette"]["hair"]), skin_c, 0.25)
    is_beard = lambda y: _count_near(arr[int(y) - 2:int(y) + 3,
                                              max(0, int(cx - rx * 1.3)):int(cx + rx * 1.3)], beard_c, 20)
    if has_beard:
        below = is_beard(G["chin"] + ry * 0.10)
        ok_e1 = below == 0
        res.append(dict(probe="E1 beard_not_on_neck", ok=ok_e1,
                        value=int(below), need=0,
                        detail=(f"颏线下 0.10·ry 处胡须色 {below}px（须 0）"
                                + ("" if ok_e1 else " ← 胡须糊到脖子上"))))
        above = is_beard(mouth_y - ry * 0.15)
        ok_e2 = above >= 25
        res.append(dict(probe="E2 mustache_above_mouth", ok=ok_e2,
                        value=int(above), need="≥25",
                        detail=(f"嘴上 0.15·ry 处胡须色 {above}px（须 ≥25 = 有八字胡）"
                                + ("" if ok_e2 else " ← 嘴上没胡子"))))

    # C1/C2 五官可见性（坑⑮ 的真实回归口径：袖子扫过嘴位 → 角色看着像哑巴）
    #
    # **不要写成「脸窗矩形内出现衣色」**：眼/嘴窗是矩形，抬起的袖子从窗口角上经过
    # 就会误判（第一版 28 人全员 FAIL，标注一看袖子只是贴着颊边走，眼球完整）。
    # 真正要守的不变量是**五官本身还在不在**——直接数五官自己的颜色。
    from usine.intro_cards import THEME
    fw = face_windows(G)
    mx0, my0, mx1, my1 = (int(v) for v in fw["mouth"])
    mouth_px = max(0.16 * (mx1 - mx0) * (my1 - my0), 24)     # 张嘴态的嘴：口型 + 舌 + 口线
    scl_px = 0.16 * (fw["eyes"][0][2] - fw["eyes"][0][0]) * (fw["eyes"][0][3] - fw["eyes"][0][1])
    worst_m, worst_e = None, None
    for code in RAISED_POSES:
        pose = dict(pose_for(code, 0.5, 0.0, p))
        lay = render_persona(p, card, mood="happy", openness=0.9, pose=pose)
        arr = _np(lay, "RGB").astype(int)
        sub_m = arr[my0:my1, mx0:mx1]
        m_cnt = max(_count_near(sub_m, THEME["mouth"]), _count_near(sub_m, THEME["tongue"]),
                    _count_near(sub_m, THEME["ink"]))
        e_cnt = 0
        for (ex0, ey0, ex1, ey1) in fw["eyes"]:
            e_cnt += _count_near(arr[int(ey0):int(ey1), int(ex0):int(ex1)], (255, 255, 255), 12)
        if m_cnt < mouth_px and (worst_m is None or m_cnt / mouth_px < worst_m[1]):
            worst_m = (code, m_cnt / mouth_px)
        if e_cnt < scl_px and (worst_e is None or e_cnt / scl_px < worst_e[1]):
            worst_e = (code, e_cnt / scl_px)
    res.append(dict(probe="C1 mouth_visible", ok=worst_m is None,
                    value=(round(worst_m[1] * 100) if worst_m else 100), need=100,
                    detail=(f"{worst_m[0]} 嘴部可见像素仅 {worst_m[1] * 100:.0f}%" if worst_m
                            else "抬臂姿态族嘴部均可见")))
    res.append(dict(probe="C2 eye_visible", ok=worst_e is None,
                    value=(round(worst_e[1] * 100) if worst_e else 100), need=100,
                    detail=(f"{worst_e[0]} 眼部可见像素仅 {worst_e[1] * 100:.0f}%" if worst_e
                            else "抬臂姿态族眼部均可见")))

    info = dict(id=p["id"], face=p["movement"]["face"], H=Hh,
                sh_hw=round(G["sh_hw"], 1), torso_hw=round(G["torso_hw"], 1),
                arm_w=round(G["arm_w"], 1))
    return res, info


# ---------- 主流程 ----------


def main(argv=None):
    ap = argparse.ArgumentParser(prog="usine.qa_shape",
                                 description="人物层形状/连接/图层几何探针（28 人）")
    ap.add_argument("--only", help="逗号分隔的人设 id")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--annotate", action="store_true",
                    help="把探针判定的缺陷框画到 build/chars/qa/<id>.png（改代码前先看这个）")
    a = ap.parse_args(argv)
    personas, doc = load_data()
    cards = {c["id"]: c for c in doc["cards"]}
    ids = list(personas) if not a.only else [s.strip() for s in a.only.split(",")]

    if a.annotate:
        from usine import ROOT
        qdir = ROOT / "build" / "chars" / "qa"
        qdir.mkdir(parents=True, exist_ok=True)
        for pid in ids:
            if pid in personas:
                annotate(personas[pid], cards.get(pid), qdir / f"{pid}.png")
        print(f"[annotate] {len(ids)} -> {qdir}/<id>.png")
        return 0

    all_res, fails = [], 0
    for pid in ids:
        if pid not in personas:
            continue
        res, info = probe_persona(personas[pid], cards.get(pid))
        all_res.append(dict(info=info, results=res))
        fails += sum(1 for r in res if not r["ok"])

    if a.json:
        print(json.dumps(dict(fails=fails, units=all_res), ensure_ascii=False, indent=1))
        return 1 if fails else 0

    print(f"{'persona':<10}{'face':<8}" + "".join(f"{r['probe'].split()[0]:<20}" for r in all_res[0]["results"]))
    for u in all_res:
        row = f"{u['info']['id']:<10}{u['info']['face']:<8}"
        for r in u["results"]:
            row += f"{('OK' if r['ok'] else 'FAIL'):<20}"
        print(row)
    print()
    for u in all_res:
        for r in u["results"]:
            if not r["ok"]:
                print(f"  [{u['info']['id']}] {r['probe']}: {r['detail']}")
    print(f"\nSHAPE QA {'PASS' if not fails else f'FAIL ({fails} 项)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

