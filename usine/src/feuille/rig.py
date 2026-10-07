# -*- coding: utf-8 -*-
"""rig.py — 人物 rig 本体（⑥ 视频：Pillow 绘制能力）

搬运自 explorateur/src/usine/intro_cards.py（函数体逐字节照搬，含全部坑注/准则注）：
- 46–108：THEME / SCENE / NECK_SHADE_F 常量色表（人物/道具与场景中性色的唯一事实源）
- 171–210：rnd / gaze / phys / jump_height（种子命名空间、视线漂移与挂件物理）
- 454–477：mix / hexc / ease_out_cubic / pop_scale（色彩插值与入场缓动）
- 1020–1110：MOOD_FACE / EYE_MOOD / FACE_SPECS / JAW / HAIR_CHEEK_KEEP / JAW_BELOW /
  BEARD_LEGACY / jaw_point / face_profile / sleeve_color（表情参数与下颌几何单一事实源）
- 1113–1208：SUNGLASS_HEAD / sunglasses_head_geo / face_geo（头身规格单一事实源）
- 1211–1900：draw_character（人物绘制主体；图层序纪律见函数内注释——衣不遮嘴）
- 1902–2059：POSE_CODES / pose_for（姿态库）
- 2070–2083：openness_at（词级时间轴驱动的口型开合）

终态说明（丢了什么、为什么）：

- 只搬「绘制能力」，不搬「管线」：tts / assets / render 三阶段编排、产物目录与缓存
  账本调用属 explorateur 的工厂形态，feuille 已有等价层，在此不重复实现。
- 不搬清单：load_data / card_units / find_card / synth_line / cmd_tts / cmd_assets /
  cmd_render / main（管线编排，含 TTS 阶段的 synth_line——feuille.tts.synth_line
  已含重试与内容寻址缓存）；parse_signed / clamp / effective_voice / content_hash
  （feuille.tts）；html_escape / band_html / badge_html / pill_html / bubble_html /
  matte_combine（feuille.textlayer）；require_browser（feuille.platform.browser）；
  load_timeline（explorateur AUDIO_DIR 路径耦合）；karaoke_points / frac_at
  （feuille.timeline）；render_card（intro 卡片编排，其通用 rawvideo→ffmpeg 管道
  已提取为 feuille.render.encode_frames）；AUDIO_DIR / TEXT_DIR / EDGE / FONT_CSS /
  BAND_H 等模块级路径常量，以及 FPS / DUR / FRAMES / BAND_Y / UI_INK / BAND_BG /
  BADGE_* / PILL_* / BUBBLE_* / PROG_* 等卡片编排布局常量。
  （W / H 保留：它们是 rig 的语义画布基准，见下方定义处注释。）
- 本模块无文件/路径耦合，签名与 ctx 契约未改：draw_character(img, d, p, t, ctx) /
  pose_for(code, u, t, p) / openness_at(lines, t, seed) 的全部输入由调用方注入
  （p = personas.json 人设 dict；ctx = 姿态上下文）。
  ctx 契约：scale / squash / xoff / yoff / head_dx / head_dy / pose / mood / blink /
  openness（可选 xscale / ss / brow_lift_extra）。pose_for 产出的顶层键
  （yoff / xoff / squash / xscale / head_dx / head_dy / brow_lift_extra）由调用方
  pop 进 ctx 后再传入——explorateur render_card 的用法（源 2246–2267 行）。

核心纪律不在此重复：图层序（衣不遮嘴）、种子命名空间幂等（不变量⑦）、下颌超椭圆
（坑㉓）、袖子色阶（坑⑱）、单一事实源（不变量①⑤）等判据全部随函数体原样保留在
代码注释里，与 explorateur 逐字节一致。
"""
import hashlib
import math

from .tts import clamp  # clamp 已在 feuille.tts（不搬清单），只引用不复制

# rig 语义画布基准：face_geo 的 cx=540 / ground=1700 / hy=1140 与 scenes 的全部场景坐标
# 都锚定在 1080×1920 上（几何事实，非路径常量）；目标画布不同时经 ctx["ss"] 等比缩放。
W, H = 1080, 1920


THEME = {  # 人物/道具常量色唯一事实源（plan §7.2-1：色值只存于 personas.json 与主题文件；qa_char 同源引用）
    "ink": (46, 42, 54),             # 瞳孔/眉毛/口型线（无描边人物的唯一深色）
    "mouth": (122, 54, 60), "tongue": (236, 120, 112), "blush": (247, 197, 185),
    "shoe": (56, 56, 64),
    "gold": (232, 194, 74), "pearl": (246, 242, 234), "beads": (162, 120, 70),
    "bracelet_leather": (122, 88, 58), "bracelet_woven": (204, 172, 120),
    "metal_dark": (44, 44, 52), "lens": (70, 76, 92), "camera_body": (70, 70, 78),
    "headphones": (60, 60, 70), "lens_blue": (152, 194, 214), "glint_blue": (206, 226, 238),
    "glint_soft": (226, 238, 246), "hairpin_clear": (206, 236, 246), "scarf_red": (196, 88, 74),
    "glasses_plastic": (58, 74, 44), "glasses_thin": (66, 66, 76), "glasses_dark": (56, 60, 72),
    "headband_red": (214, 69, 65),   # 红发带（意大利三色旗 wink 的红条）
    "it_flag": ((0, 146, 70), (255, 255, 255), (214, 69, 65)),
    "straw": (246, 240, 226), "apron": (238, 233, 221),
    "paper": (250, 246, 236), "paper_map": (242, 235, 216), "paper_tote": (250, 246, 238),
    "book_leather": (122, 94, 70), "pen_blue": (58, 72, 96), "satchel": (122, 92, 62),
    "bottle_blue": (122, 184, 202), "bottle_green": (152, 202, 172), "bottle_green_dark": (120, 160, 132),
    "ball": (232, 138, 66), "ball_line": (120, 60, 30),
    "skate_deck": (240, 156, 84), "skate_wheel": (70, 70, 78),
    "bag_canvas": (245, 240, 230), "bag_woven": (226, 200, 160), "bag_pouch": (238, 226, 208),
    "sparkle": (255, 208, 92),
    "shade_dark": (25, 25, 32),      # 服装体积影/袖口混入色
}
NECK_SHADE_F = 0.45                  # 颈部 skinShade 混入比（qa_char 同源）


# 场景中性色（单一事实源：场景原语只引用本表 / pal 令牌 / mix()，禁写字面 RGB——不变量⑤）
SCENE = {
    "white": (255, 255, 255),    # 蒸汽/粉笔/高光
    "lamp": (75, 75, 75),        # 灯杆/电线/护栏/路缘
    "night_blue": (43, 48, 70),  # 夜色楼体/招牌底
    "metal": (150, 150, 155),    # 卷帘门/金属构件
    "sun1": (255, 214, 150),     # 晨昏天光三层
    "sun2": (255, 205, 160),
    "sun3": (255, 190, 140),
    "lantern": (255, 214, 90),   # 灯笼/灯串暖黄
    "glow": (255, 230, 160),     # 灯箱/窗光
    "glow2": (255, 235, 190),    # 橱窗光
    "chalk": (255, 235, 180),    # 暖粉笔/卷帘门亮条
    "stem": (120, 150, 100),     # 花茎
    "grass": (120, 165, 110),    # 草地/松枝
    "grass2": (120, 160, 110),   # 远山绿
    "wood": (140, 115, 90),      # 树干/木杆
    "wood2": (230, 180, 90),     # 木牌/遮阳篷骨
    "sky": (180, 220, 240),      # 天光/水面
    "sky2": (200, 228, 245),     # 水族箱体
    "sky3": (150, 200, 225),     # 镜面水面
    "steam": (160, 210, 230),    # 蒸笼/蒸汽层
    "flower": (255, 170, 90),    # 花瓣/灯串
    "blossom": (255, 210, 110),  # 霓虹花瓣
    "peach": (255, 170, 120),    # 灯罩暖光
    "sign": (200, 90, 90),       # 招牌红
    "cyan": (90, 220, 240),      # 霓虹青
    "pink": (255, 170, 200),     # 霓虹粉
    "snow": (250, 250, 250),     # 山顶积雪
    "peach2": (255, 190, 120),   # 摊位灯罩暖光
}


def rnd(seed):
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def gaze(seed, t):
    """视线跟随镜头（requirement §3.2 / plan §4 gaze="camera"）：瞳孔绕镜头注视点做
    种子化微漂移＋短促扫视，确定性幂等。返回 (dx, dy)∈[-1,1]；
    像素幅度 = (巩膜−瞳孔) 余量 × 0.35（探针安全余量内，qa_char 同源引用）。"""
    ph = 2 * math.pi * rnd(f"{seed}:gaze")
    gx = 0.45 * math.sin(2 * math.pi * 0.19 * t + ph)
    gy = 0.30 * math.sin(2 * math.pi * 0.13 * t + ph * 1.7)
    cyc = 2.6
    t0 = rnd(f"{seed}:gaze:phase") * cyc
    k = int((t + t0) / cyc)
    tt = (t + t0) - k * cyc
    if tt < 0.22:  # 短促扫视：幅度/方向按扫视序号锁定
        amp = rnd(f"{seed}:sacc:{k}")
        gx += 0.55 * amp * math.sin(2 * math.pi * rnd(f"{seed}:sxa:{k}"))
        gy += 0.35 * amp * math.cos(2 * math.pi * rnd(f"{seed}:sya:{k}"))
    return clamp(gx, -1, 1), clamp(gy, -1, 1)


def phys(seed, code, kind, t):
    """挂件物理（requirement §3.4 / plan §7.3-4 四锚点分层）：相位频率种子化，确定性幂等。
    swing→(dx,dy) 摆动；bounce→(0,dy) 颠动；reflect→(dx,0) 高光位移。"""
    ph = 2 * math.pi * rnd(f"{seed}:phys:{code}")
    if kind == "swing":
        return (5.0 * math.sin(2 * math.pi * 0.85 * t + ph),
                1.6 * abs(math.cos(2 * math.pi * 0.85 * t + ph)))
    if kind == "bounce":
        return (0.0, -3.0 * abs(math.sin(2 * math.pi * 1.15 * t + ph)))
    if kind == "reflect":
        return (9.0 * math.sin(2 * math.pi * 0.55 * t + ph), 0.0)
    return (0.0, 0.0)


def jump_height(p):
    """mini_jump 起跳高度：movement.bounce 越小越弹（plan §4 个性参数；qa_char 同源引用）。"""
    return 60 + 28 * clamp(14.0 / p["movement"]["bounce"], 0.75, 1.6)


def mix(c1, c2, f):
    return tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))


def hexc(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_cubic(u):
    return 1 - (1 - u) ** 3


def pop_scale(t, t0, dur, overshoot=True, damp=None):
    """damp=movement.bounce：越小越弹（入场弹跳按个性参数缩放，plan §4）"""
    if t <= t0:
        return 0.0
    u = (t - t0) / dur
    if u >= 1:
        return 1.0
    if overshoot:
        k = clamp(14.0 / damp, 0.75, 1.6) if damp else 1.0
        return 1 - math.exp(-6.0 * k * u) * math.cos(9.0 * k * u)
    return 1 - math.exp(-5.0 * u) * (1 + 5.0 * u)


# ---- 人物 ----

MOOD_FACE = {
    "neutral": dict(lift=0, tilt=0, smile=0.6),
    "happy": dict(lift=7, tilt=0, smile=1.0),
    "puzzled": dict(lift=2, tilt=11, smile=0.15),
    "encouraging": dict(lift=4, tilt=0, smile=0.8),
    "emphatic": dict(lift=2, tilt=-6, smile=0.5),
    "teach": dict(lift=2, tilt=0, smile=0.55),
}
EYE_MOOD = {"neutral": 1.0, "happy": 0.94, "puzzled": 1.05, "encouraging": 0.98, "emphatic": 0.97, "teach": 1.0}
# 眼形缩放（巩膜 ry 系数）：happy 微闭笑眼 / puzzled 睁大（plan §4 眼神变化）


# 脸型规格表（plan §8.3；2026-10-03 人物形象打磨：2 型 → 6 型，按人设分配）。
# 元组 = (头高 H, 头宽系数 WH/H)。heart＝上圆下圆收下巴（draw_character 组合绘制，
# 贝塞尔弧收底、无尖角——尖下巴观感像鬼，禁用）、square＝方颌（椭圆底缘两侧补平）
# ——下颌轮廓只由这两个键驱动，其余型为纯椭圆。
FACE_SPECS = {
    "round":  (356.0, 0.955),   # 婴儿圆：宽圆头
    "tall":   (396.0, 0.78),    # 窄长：清瘦长头
    "oval":   (386.0, 0.84),    # 端正椭圆：利落匀称
    "wide":   (348.0, 1.02),    # 宽和：扁宽大头
    "heart":  (372.0, 0.90),    # 心形尖下巴
    "square": (392.0, 0.88),    # 方颌硬朗
}

# 下颌轮廓参数（单一事实源）——heart / square 两种非椭圆下颌都走 jaw_point()。
# 轮廓 = **超椭圆** f(s) = (1 − s^m)^(1/m)，s ∈ [0,1] 从颊部走到下巴底，半宽相对 rx。
#
# 为什么不能用随手一条二次曲线（坑㉓，2026-10-03 用户反馈「下巴太尖」）：
#   旧心形用 x(t) = (1−t)² + 0.80t(1−t)、y(t) = 0.42 + 1.26t − 0.64t²。求导得
#   x'(1) = −0.80·rx、y'(1) = −0.02·ry —— 顶点切线几乎**水平**。左右两支在同一个
#   (hx, y) 折返，polygon 边界不是圆底而是**一根横着的针**（xiaoman/giulia 实测：
#   颏线处一根约 0.8px 高、27px 宽的横向尖刺）。
#   超椭圆 m>1 时 f'(s) → −∞（s→1），底缘切线**竖直**，两支镜像后合成光滑圆底。
# m 的含义：1.7 = 上圆下收（心形·圆下巴）；3.2 = 侧廓接近竖直、底缘宽平（方颌）。
# y1 略小于 1 时底缘是一条短平边而不是收成一点——方颌要的就是这个。
JAW = {
    "heart":  dict(y0=0.42, y1=1.04, m=1.70, n=30),
    "square": dict(y0=0.00, y1=0.985, m=3.20, n=30),
}

# 前发/侧发帘内缘下限（相对 rx）：脸颊高度以下不再向中轴收。
# 头在颏线附近半宽趋 0，固定 in_w 会把内缘一路拉到脸的中轴上，两侧发帘一夹，
# 可见的下巴就收成尖楔（用户反馈「下巴太尖」：layla / aaching 实测可见皮肤半宽
# 只剩 0.17rx，而同尺寸的圆脸本该有 0.44rx）。
HAIR_CHEEK_KEEP = 0.72

# 颏线以下「头宽 → 肩宽」的过渡带高度（相对头高 H）。旧 body_edge 在颏线处直接
# 从 0 跳到 sh_out（实测 ~90px 台阶），发帘外缘在那里折出一个台阶。
JAW_BELOW = 0.16

# 胡须反向验证接缝：True = 退回坑㉓ 之前的 PIE 形胡须（糊到脖子、嘴上没八字胡）。
# 生产渲染恒为 False；`scripts/verify_shape_fixes.py` 用它证明 E1/E2 不是恒真的。
BEARD_LEGACY = False


def jaw_point(face, s):
    """下颌轮廓上参数 s∈[0,1] 处的 (半宽/rx, 相对 hy 的高度/ry)。绘制与 qa 探针同源。"""
    p = JAW[face]
    return (1.0 - s ** p["m"]) ** (1.0 / p["m"]), p["y0"] + (p["y1"] - p["y0"]) * s


def face_profile(face, v):
    """脸颊以下（v = 相对 hy 的高度/ry，v ∈ [0,1]）的**脸**半宽系数，相对 rx。

    与下颌绘制同源：JAW 型走 jaw_point()，其余型是纯椭圆。
    qa_shape 的 D2 探针直接查这个函数的单调性——**几何不变量就该用几何查**：
    拿像素量会被发量遮挡污染（第一版 8 个长发角色被误判成「下颌外扩」）。
    """
    if face in JAW:
        y0, y1 = JAW[face]["y0"], JAW[face]["y1"]
        if v <= y0:
            return 1.0
        if v >= y1:
            return 0.0
        return jaw_point(face, (v - y0) / (y1 - y0))[0]
    return math.sqrt(max(0.0, 1.0 - v * v))


def sleeve_color(base, f=0.13):
    """袖子相对衣身的一档色阶（坑⑱）。

    纯平涂、禁描边（不变量⑤）——叠在躯干上的手臂只能靠**色阶**读出来。
    旧实现袖子直接用 outfitTop，与躯干同色：上臂除探出躯干轮廓那一小段以外
    完全不可见，剪影里根本没有手臂。浅衣压深、深衣提亮，任意衣色都拉开一档。
    独立成模块级函数是为了给 `scripts/verify_shape_fixes.py` 一个可猴补丁的接缝。
    """
    lum = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
    return mix(base, (255, 255, 255) if lum < 128 else THEME["shade_dark"], f)


# 顶戴墨镜（accessories: sunglasses_head）几何参数——单一事实源（坑㉑）。
# 旧实现在 draw_character 里散落 52/32/22/14/24/16/10 一串魔数，qa_char 探针只能自己
# 再猜一个 `hy - ry*0.76`：该点落在**镜片**（THEME["lens"]）正中而不是镜框，
# 于是 omar / omar_f 报 `glasses_perch` 失败。魔数不共享 → 探针与渲染必然漂移。
# 绘制与探针现在都从这里取数，且 probe 只能取「结构上必然是金属」的两处点。
SUNGLASS_HEAD = {
    "top": 0.80,    # 镜架顶沿 = hy - ry*top（倒扣在发顶，不遮眼）
    "dx": 52,       # 左右镜片中心距头心轴
    "out_rx": 32,   # 镜框外接圆角矩形：半宽
    "out_up": 22,   # 镜框上沿相对 sy0（向上）
    "out_dn": 14,   # 镜框下沿相对 sy0（向下）
    "rad": 14,      # 镜框圆角半径
    "lens_rx": 24,  # 镜片椭圆：半宽
    "lens_up": 16,  # 镜片上沿相对 sy0（向上）——与 out_up 之间是纯金属带
    "lens_dn": 10,  # 镜片下沿相对 sy0（向下）
}


def sunglasses_head_geo(G, hdx=0.0, hdy=0.0):
    """顶戴墨镜左镜片的几何 + 探针取样点（渲染与 qa_char 同源）。

    `hdx/hdy` = draw_character 的头部横/纵偏移（点头/走位/hop）——墨镜随头动，
    漏掉就会在头部弹跳时与发顶脱开。探针侧传 0 并自行把 hop 减在 y 上。

    探针点位（坑㉑）：
    - `probe_band_in`  镜框上沿带中点——结构上必然是 metal_dark（上沿与镜片上沿之间）。
    - `probe_band_out` 紧贴镜框上沿外侧的那一点——结构上必然是头发。
      两者构成一条**颜色阶跃**：镜框没画 / 被头发或气泡吞掉时它们同色，探针立刻 FAIL。
      单点颜色比较做不到这点——深发角色的发色与 metal_dark 欧氏距离可小到 8（omar 8.1）。
    - `probe_lens`      镜片正中——`THEME["lens"]` 与任何发色/肤色都差 50 以上，最不易混。
    旧探针取的是镜片正中却拿 metal_dark 去比，怎么画都不可能通过。
    """
    S = SUNGLASS_HEAD
    hx, hy, ry = G["cx"] + hdx, G["hy"] + hdy, G["ry"]
    sy0 = hy - ry * S["top"]
    c = hx - S["dx"]                      # 左镜片中心
    return {
        "sy0": sy0,
        "cx_left": c,
        "frame": (c - S["out_rx"], sy0 - S["out_up"], c + S["out_rx"], sy0 + S["out_dn"]),
        "lens": (c - S["lens_rx"], sy0 - S["lens_up"], c + S["lens_rx"], sy0 + S["lens_dn"]),
        "probe_band_in": (c, sy0 - (S["out_up"] + S["lens_up"]) * 0.5),
        "probe_band_out": (c, sy0 - S["out_up"] - 4),
        "probe_lens": (c, sy0 - (S["lens_up"] - S["lens_dn"]) * 0.5),
    }



def face_geo(face):
    """头身规格（单一事实源，渲染与 qa 探针共用）。单位 = 头高 H。
    对标多邻国人形：头占全身 ~46%；躯干含肩与头等宽（剪影连续，无缝衔接）；
    低位大眼（头顶下 0.615H）、宽瞳距 ±0.30×头宽、大巩膜 0.28×头宽；
    眉贴眼上（巩膜顶 + 0.035H）；嘴位头顶下 0.815H；粗短胶囊四肢贴躯干。

    2026-10-03 头/身/臂几何重设计（坑⑱，qa_shape.py 探针驱动）：
    - `neck_*`：颈侧 x 半径与上下缘。肩部体块从**颈缘**起坡（旧版从 0.10H 起，
      比颈缘窄 0.005H，颈侧到臂根之间露出一条背景楔形缝）。
    - `sh_x`：肩点外移量（arm_w·0.30 → 0.18）。旧肩点内收过多 + 静止角 7°，
      上臂整条埋进躯干、剪影里读不出手臂，只剩两只浮球手。
    - `hip_hw`：胯块半宽（覆盖双腿外缘）。旧版没有胯块，躯干圆角收进去之后
      与内收的双腿之间留出空洞，裤子看着像浮在空中。
    - `arm_rest`：静止姿态角（14°/10°，旧 7°/8°）。
    """
    H_h, wfac = FACE_SPECS.get(face, FACE_SPECS["round"])
    WH = H_h * wfac
    u = lambda f: f * H_h
    hy = 1140.0
    eye_y = hy - H_h / 2 + u(0.615)
    chin = hy + H_h / 2
    torso_top = chin + u(0.02)
    torso_h = u(0.52)
    torso_hw = 0.435 * WH
    sh_dy = u(0.07)
    sh_hw = 0.435 * WH
    arm_w = u(0.155)
    leg_cx, leg_w = u(0.145), u(0.185)
    return dict(
        H=H_h, WH=WH, rx=WH / 2, ry=H_h / 2, hy=hy, cx=540.0, ground=1700.0,
        eye_dx=0.300 * WH, scl_rx=0.140 * WH, scl_ry=0.170 * WH, pup_r=0.078 * WH,
        eye_y=eye_y, brow_y=eye_y - 0.170 * WH - u(0.035),
        mouth_y=hy - H_h / 2 + u(0.815), blush_y=hy - H_h / 2 + u(0.700),
        chin=chin,
        torso_top=torso_top, torso_h=torso_h, torso_hw=torso_hw,
        sh_dy=sh_dy, sh_hw=sh_hw,
        neck_hw=u(0.105), neck_top=chin - u(0.06), neck_bot=torso_top + u(0.03),
        sh_x=sh_hw - arm_w * 0.18,          # 肩点内收量（落在躯干轮廓上）
        sh_out=min(sh_hw + arm_w * 0.45, WH / 2 * 0.99),  # 肩部体块外缘（不得超过头宽）
        leg_cx=leg_cx, leg_w=leg_w, foot_splay=u(0.085),
        # 胯块半宽：取躯干的 0.92 而非腿外缘——身体是**连续柱体**，肩→胯同宽。
        # 只按腿外缘（u(0.2597)）铺胯块时，躯干下缘圆角收进去、手又挂在体外，
        # 身体与手之间会露出一条背景缝（qa_shape.py A2）。
        hip_hw=torso_hw * 0.92,
        foot_cy=1700.0 + u(0.006), foot_l=u(0.335), foot_h=u(0.145),
        up_len=u(0.27), lo_len=u(0.24), arm_w=arm_w, hand_r=u(0.105),
        arm_rest=(7.0, 5.0),                # 静止姿态角（上臂/小臂）：手要搭在胯上
    )


def draw_character(img, d, p, t, ctx):
    """多邻国风格角色：无描边纯平涂、头身规格见 face_geo()、大眼白+瞳孔双高光、
    胶囊眉、粗短四肢、圆润有机发型（双色高光）、耳朵/衣领/袖口细节。"""
    pal = p["palette"]
    hair_c, hl_c = hexc(pal["hair"]), hexc(pal["hairHighlight"])
    skin = hexc(pal["skin"])
    top, bottom = hexc(pal["outfitTop"]), hexc(pal["outfitBottom"])
    ident = hexc(p["identity"])
    face = p["movement"]["face"]
    female = p["gender"] == "female"
    seed = p["id"]  # 一切随机走人设 id 命名空间（不变量⑦；qa 探针同源可复算）
    skin_sh = hexc(pal["skinShade"])
    sk = p.get("skin", {})  # 皮肤层叠加槽（plan §1/§3 原则五：做旧/补丁，不改基型配色）
    # ---- 头身规格（face_geo 单一事实源；cx/ground 永不手抄——不变量①）----
    G = face_geo(face)
    cx, ground = G["cx"], G["ground"]
    sc = ctx["scale"]
    q = ctx["squash"]
    sx, sy = sc * (1 + q * 0.6) * ctx.get("xscale", 1.0), sc * (1 - q)
    bx, by = ctx["xoff"], ctx["yoff"]
    hdx, hdy = ctx["head_dx"], ctx["head_dy"]
    pose = ctx["pose"]
    acc = {a["code"]: a for a in p.get("accessories", [])}
    has = lambda c: c in acc
    ss = ctx.get("ss", 1.0)
    out = p.get("outfit", {})  # 服装轮廓槽（plan §4：bottom=skirt 长裙装 / kind=tunic|pinafore|vest；缺省=长裤）
    skirt = out.get("bottom") == "skirt"
    tunic = out.get("kind") == "tunic"
    pinafore = out.get("kind") == "pinafore"
    vest = out.get("kind") == "vest"

    def pfy(code, kind):
        """挂件物理偏移：数据声明了对应 physics 才生效（plan §4 accessories.physics）"""
        return phys(seed, code, kind, t) if has(code) and acc[code].get("physics") == kind else (0.0, 0.0)

    u = lambda f: f * G["H"]
    rx, ry = G["rx"], G["ry"]
    hx, hy = cx + hdx, G["hy"] + hdy
    eye_y = G["eye_y"] + hdy
    brow_y0 = G["brow_y"] + hdy
    mouth_y = G["mouth_y"] + hdy
    blush_y = G["blush_y"] + hdy
    eye_dx, scl_rx, scl_ry, pup_r = G["eye_dx"], G["scl_rx"], G["scl_ry"], G["pup_r"]
    torso_top = G["torso_top"]
    torso_bot = torso_top + G["torso_h"] * (1.30 if tunic else 1.0)  # 长衫：下摆过臀（outfit.kind=tunic）
    torso_hw = G["torso_hw"]
    sh_y = torso_top + G["sh_dy"]
    sh_hw = G["sh_hw"]
    sh_x, sh_out, neck_hw = G["sh_x"], G["sh_out"], G["neck_hw"]
    leg_cx, leg_w = G["leg_cx"], G["leg_w"]
    foot_cy, foot_l, foot_h = G["foot_cy"], G["foot_l"], G["foot_h"]
    up_len, lo_len, arm_w, hand_r = G["up_len"], G["lo_len"], G["arm_w"], G["hand_r"]
    style = p["hairStyle"]

    def T(pt):
        x, y = pt
        return ((cx + bx + sx * (x - cx)) * ss, (ground + by + sy * (y - ground)) * ss)

    def TB(x0, y0, x1, y1):
        a, b = T((x0, y0))
        c, dd = T((x1, y1))
        return [a, b, c, dd]

    def E(x0, y0, x1, y1, **kw):
        d.ellipse(TB(x0, y0, x1, y1), **kw)

    def RR(x0, y0, x1, y1, rad, **kw):
        d.rounded_rectangle(TB(x0, y0, x1, y1), max(2, rad * sc * ss), **kw)

    def LN(pts, width, **kw):
        d.line([T(pt) for pt in pts], width=max(1, int(width * sc * ss)), joint="curve", **kw)

    def CAP(p0, p1, width, **kw):  # 胶囊：粗线 + 两端圆头
        LN([p0, p1], width, **kw)
        r = width / 2
        E(p0[0] - r, p0[1] - r, p0[0] + r, p0[1] + r, **kw)
        E(p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r, **kw)

    def ARC(x0, y0, x1, y1, a0, a1, width, **kw):
        d.arc(TB(x0, y0, x1, y1), a0, a1, width=max(1, int(width * sc * ss)), **kw)

    def PIE(x0, y0, x1, y1, a0, a1, **kw):
        d.pieslice(TB(x0, y0, x1, y1), a0, a1, **kw)

    def body_edge(s, y):
        """人物剪影在高度 y、方向 s（−1 左 / +1 右）的边缘 x（带符号）。

        头发里凡是「挂在身上」的部件（辫子、低马尾、长发帘）都靠它定位：
        钉死在头宽 ±rx 上会浮在下颌与肩之间的空档里（坑⑱）。
        颏线以下是**平滑过渡**到肩宽 sh_out：旧实现在 `y < chin−0.03H` 的判定失败后
        直接返回 sh_out，切换点上有 ~90px 跳变（圆脸实测：颏线上方头半宽 58px、
        下方直接 148px），发帘外缘在那里折出一个台阶（坑㉓）。
        """
        t = (y - hy) / ry
        w = rx * math.sqrt(max(0.0, 1.0 - t * t)) if abs(t) <= 1.0 else 0.0
        k = min(1.0, max(0.0, (y - G["chin"]) / u(JAW_BELOW)))
        return cx + s * (w + (sh_out - w) * k * k * (3 - 2 * k))   # smoothstep，两端一阶导为 0

    def side_curtain(s, y0, y1, out_w=46.0, in_w=16.0, n=18, col=None):
        """侧发帘：内缘压在头/身上 in_w、外缘外挂 out_w，轮廓跟随剪影。

        旧实现是两个固定位置的圆/圆角矩形（内缘钉在 hx±rx−30），到颏线附近
        头已经收窄，发帘就整条离开下颌浮在体侧（aaching 69px / seoyeon 74px）。
        采样数要够密：颏线附近头缘曲率最大，n=10 的弦线会切进圆弧里，
        又在内缘留出 10px 缺口（故 n=18）。

        **内缘下限 `HAIR_CHEEK_KEEP`**（坑㉓）：内缘不能一路跟着收窄的下颌走——
        颏线附近头半宽趋 0，固定 in_w 会把两侧内缘拉到中轴上，把脸夹成尖楔。
        所以内缘取 max(剪影半宽 − in_w, 下限)：颏线以上下限恒为 `HAIR_CHEEK_KEEP·rx`
        （头发挂在脸两侧不压下颌），颏线以下再平滑收到颈半宽 `neck_hw`
        （长发本来就该落在脖子两边，而不是端在身体两侧形成两条直板）。
        """
        chin = G["chin"]
        keep_hi = rx * HAIR_CHEEK_KEEP
        pts_o, pts_i = [], []
        for k in range(n + 1):
            yy = y0 + (y1 - y0) * k / n
            e = body_edge(s, yy)
            fk = min(1.0, max(0.0, (yy - chin) / u(JAW_BELOW)))
            keep = keep_hi + (neck_hw - keep_hi) * fk * fk * (3 - 2 * fk)
            pts_o.append((e + s * out_w, yy))
            pts_i.append((cx + s * max(abs(e - cx) - in_w, keep), yy))
        d.polygon([T(p) for p in (pts_o + pts_i[::-1])], fill=col or hair_c)

    # ================= 背发层（头后体积） =================
    if style in ("ponytail_high", "curly_ponytail"):
        for fx, fy, r in ((0.78, -0.52, 40), (0.92, -0.10, 34), (0.98, 0.30, 27)):
            E(hx + rx * fx - r, hy + ry * fy - r, hx + rx * fx + r, hy + ry * fy + r, fill=hair_c)
        if style == "curly_ponytail":
            for fx, fy in ((1.02, 0.62), (0.84, 0.78)):
                E(hx + rx * fx - 22, hy + ry * fy - 22, hx + rx * fx + 22, hy + ry * fy + 22, fill=hair_c)
    if style == "ponytail_low":
        for fy, r in ((0.12, 36), (0.54, 30), (0.94, 24)):
            # 坑⑱：低马尾沿体侧走，别钉死在头宽上（原来三颗全浮在下颌外侧空档里）
            E(body_edge(-1, hy + ry * fy) - r * 0.45, hy + ry * fy - r,
              body_edge(-1, hy + ry * fy) + r * 0.55, hy + ry * fy + r, fill=hair_c)
    if style in ("braid", "braid_long"):
        n = 4 if style == "braid" else 6
        br_ph = 2 * math.pi * rnd(f"{seed}:braid")
        dy = 0.52 if style == "braid" else 0.40
        for i in range(n):
            fy = -0.02 + i * dy
            r = 30 - i * 3
            sw = 4.0 * math.sin(2 * math.pi * 0.7 * t + br_ph + i * 0.7) * i / n  # 辫子摆动（种子相位）
            # 坑⑱：辫子原来钉在 hx−rx 的固定 x 上，逐颗都落在「下颌与肩之间的空档」里，
            # 下半身直接变成一串浮在体侧的圆点（priya 实测 4 颗全悬空）。
            # 改成**沿身体左缘走**：圆心 = 该高度的体侧边缘 + r·0.55，
            # 每颗都压在头/肩上——身前部分被躯干盖住，身外部分才是可见的辫子。
            bxx = body_edge(-1, hy + ry * fy) + r * 0.55 + sw
            E(bxx - r, hy + ry * fy - r, bxx + r, hy + ry * fy + r, fill=hair_c)
    if style in ("wavy_lob", "wavy_long", "long_straight", "long_bangs"):
        y_end = 0.85 if style == "wavy_lob" else 1.45
        for s in (-1, 1):   # 侧发帘跟随剪影（坑⑱），不再是两个固定位置的圆角矩形
            side_curtain(s, hy - ry * 0.55, hy + ry * y_end, out_w=46.0, in_w=24.0)
        if style in ("wavy_lob", "wavy_long"):
            for sgn in (-1, 1):
                for k in range(2):
                    yy = hy + ry * y_end - 24 + k * 34
                    E(body_edge(sgn, yy) + sgn * 38 - 26, yy, body_edge(sgn, yy) + sgn * 38 + 26,
                      yy + 52, fill=hair_c)

    # ================= 腿与脚 =================
    legL_ang, legR_ang = pose.get("legL", 0), pose.get("legR", 0)
    leg_top = torso_bot - u(0.10)
    leg_bot = foot_cy - foot_h * 0.30
    worn_bottom = not skirt and "bottom" in sk.get("worn", [])  # 做旧：裤腿下半段轻微磨白（plan §1 皮肤层）
    leg_col = skin if skirt else bottom  # 裙装露腿：腿画肤色（裙身在躯干段画）
    # 胯块（坑⑱）：躯干下缘 0.62·torso_hw 的大圆角往里收，而双腿内收在 leg_cx，
    # 两者之间留下一个背景空洞——裤子看着浮在空中（qa_shape.py A2，28 人 26 人中）。
    # 半宽取 torso_hw·0.92（face_geo.hip_hw）：身体成为连续柱体，手也能搭在胯上。
    RR(cx - G["hip_hw"], torso_bot - u(0.10), cx + G["hip_hw"], torso_bot + u(0.19),
       G["hip_hw"] * 0.30, fill=bottom if not skirt else leg_col)
    for s, ang in ((-1, legL_ang), (1, legR_ang)):
        lx = cx + s * leg_cx
        RR(lx - leg_w / 2, leg_top, lx + leg_w / 2, leg_bot, leg_w / 2, fill=leg_col)
        if worn_bottom:
            wy = leg_top + (leg_bot - leg_top) * 0.42
            RR(lx - leg_w / 2, wy, lx + leg_w / 2, leg_bot, leg_w / 2, fill=mix(leg_col, (255, 255, 255), 0.10))
        RR(lx - leg_w / 2, leg_bot - u(0.05), lx + leg_w / 2, leg_bot, 10, fill=mix(leg_col, THEME["shade_dark"], 0.16))
        for pd in sk.get("patches", []):  # 膝盖补丁：位置从 face_geo 腿几何推导（不变量①）
            if pd.get("on") == "bottom" and pd.get("where") == ("knee_L" if s < 0 else "knee_R"):
                pc = hexc(pd["color"])
                ky = (leg_top + leg_bot) / 2
                RR(lx - leg_w * 0.62, ky - leg_w * 0.40, lx + leg_w * 0.62, ky + leg_w * 0.40, 10, fill=pc)
                for dyy in (-leg_w * 0.50, leg_w * 0.50):  # 补丁缝线
                    LN([(lx - leg_w * 0.52, ky + dyy), (lx + leg_w * 0.52, ky + dyy)], 3,
                       fill=mix(pc, THEME["shade_dark"], 0.35))
        fxp = lx + s * G["foot_splay"] + math.sin(math.radians(ang)) * 72
        RR(fxp - foot_l / 2, foot_cy - foot_h / 2, fxp + foot_l / 2, foot_cy + foot_h / 2,
           foot_h * 0.46, fill=THEME["shoe"])
        E(fxp + s * foot_l * 0.16 - u(0.05), foot_cy - foot_h * 0.36,
          fxp + s * foot_l * 0.16 + u(0.05), foot_cy - foot_h * 0.04,
          fill=mix(THEME["shoe"], (255, 255, 255), 0.30))  # 鞋头高光
        if has("shoe_accent"):
            E(fxp - foot_l * 0.24, foot_cy - foot_h * 0.06, fxp + foot_l * 0.24, foot_cy + foot_h * 0.24,
              fill=ident)
    if has("skateboard"):
        kick = pose.get("skate_kick", 0)
        yy = 1746 - kick * 60 + pfy("skateboard", "bounce")[1]
        E(540 - 128, yy - 16, 540 + 128, yy + 16, fill=THEME["skate_deck"])
        if acc["skateboard"].get("accent"):  # 标识色贴纸（分镜 卡05：玫瑰点缀——滑板贴纸）
            RR(540 - 92, yy - 10, 540 + 92, yy + 2, 8, fill=ident)
        for wx in (540 - 78, 540 + 78):
            E(wx - 14, yy + 12, wx + 14, yy + 30, fill=THEME["skate_wheel"])
    if has("basketball"):
        bax, bay = pfy("basketball", "bounce")
        E(540 + 196 + bax, 1618 + bay, 540 + 302 + bax, 1724 + bay, fill=THEME["ball"])
        ARC(540 + 196 + bax, 1618 + bay, 540 + 302 + bax, 1724 + bay, 100, 250, 4, fill=THEME["ball_line"])

    # ================= 躯干与背带/挂件 =================
    RR(cx - torso_hw, torso_top, cx + torso_hw, torso_bot, torso_hw * 0.62, fill=top)
    # 肩部体块（坑⑱ 重设计）：从**颈缘**起坡，经斜方肌到肩峰，与臂根胶囊连续。
    # 旧版是「从 0.10H 起、到 sh_y 为止」的三角色块 + 躯干 0.62·torso_hw 的大圆角，
    # 结果颈侧到臂根之间露出一条背景楔形缝（28 人全中，见 qa_shape.py A1）。
    # 四边形：内上贴颈缘（略高于下颌线），**外侧顶点落在颏线上**。
    # 这是「夹心空洞」的唯一解法：肩体块只要高过颏线，它的外上角就会和头侧缘
    # 围出一个被实心像素夹住的背景凹坑（上一版把外顶点提到 sh_y−0.55·up_len，
    # 洞反而上移到 y=1314，宽 78px）。肩线压回颏线 → 颏线以上只有头，凹角自然不成立；
    # 颏线以下肩体块已是全宽，直接顶住臂根胶囊。肩宽取 sh_out（≤头宽 0.99）。
    for s in (-1, 1):
        nx2 = cx + s * (neck_hw + u(0.004))
        ox2 = cx + s * sh_out
        d.polygon([T((nx2, G["chin"] - u(0.03))),
                   T((ox2, G["chin"] + u(0.01))),
                   T((ox2, sh_y + u(0.15))),
                   T((nx2, G["chin"] + u(0.14)))], fill=top)
    RR(cx + torso_hw - u(0.11), torso_top + u(0.06), cx + torso_hw - u(0.025), torso_bot - u(0.05),
       u(0.08), fill=mix(top, THEME["shade_dark"], 0.10))  # 右侧体积影
    ARC(cx - 0.20 * G["WH"], torso_top - u(0.055), cx + 0.20 * G["WH"], torso_top + u(0.075),
        180, 360, u(0.032), fill=mix(top, THEME["shade_dark"], 0.20))  # 领口
    # ---- 服装轮廓（outfit 槽；缺省=长裤，零改动兼容） ----
    if skirt:  # A 字裙：腰线起、大腿中段圆摆（outfit.bottom=skirt；腿已画肤色）
        waist = torso_top + G["torso_h"] - u(0.04)
        hem = torso_top + G["torso_h"] + u(0.26)
        flare = torso_hw * 1.55
        d.polygon([T((cx - torso_hw - u(0.02), waist)), T((cx - flare, hem)),
                   T((cx + flare, hem)), T((cx + torso_hw + u(0.02), waist))], fill=bottom)
        RR(cx - flare, hem - u(0.08), cx + flare, hem + u(0.02), u(0.08), fill=bottom)  # 圆摆
        RR(cx - torso_hw - u(0.02), waist - u(0.06), cx + torso_hw + u(0.02), waist + u(0.04),
           u(0.05), fill=mix(bottom, THEME["shade_dark"], 0.14))  # 腰带
    if pinafore:  # 背带裙：护胸＋双背带＋金色背带扣（outfit.kind=pinafore）
        bib_w = torso_hw * 0.56
        RR(cx - bib_w, torso_top + u(0.10), cx + bib_w, torso_top + G["torso_h"] * 0.62, 14, fill=bottom)
        CAP((cx - bib_w + u(0.01), torso_top + u(0.14)), (cx - u(0.115), torso_top - u(0.07)),
            u(0.055), fill=bottom)
        CAP((cx + bib_w - u(0.01), torso_top + u(0.14)), (cx + u(0.115), torso_top - u(0.07)),
            u(0.055), fill=bottom)
        for s2 in (-1, 1):
            E(cx + s2 * u(0.115) - u(0.016), torso_top + u(0.08), cx + s2 * u(0.115) + u(0.016),
              torso_top + u(0.112), fill=THEME["gold"])
    if vest:  # 马甲：两侧前襟片，中开白衬衫（outfit.kind=vest；面板收在内侧——外缘被垂臂遮挡）
        vp_in, vp_out = torso_hw * 0.16, torso_hw * 0.72
        RR(cx - vp_out, torso_top + u(0.03), cx - vp_in, torso_bot - u(0.06), u(0.05), fill=bottom)
        RR(cx + vp_in, torso_top + u(0.03), cx + vp_out, torso_bot - u(0.06), u(0.05), fill=bottom)
    if out.get("buttons"):  # 前襟扣排（outfit.buttons；衬衫通勤感。胸前置物如手账/墨镜会自然遮住下扣）
        bcol = mix(top, THEME["shade_dark"], 0.38)
        for fy2 in (0.22, 0.44, 0.66):
            E(cx - u(0.020), torso_top + G["torso_h"] * fy2 - u(0.020),
              cx + u(0.020), torso_top + G["torso_h"] * fy2 + u(0.020), fill=bcol)
    if has("apron"):
        RR(540 - 128, torso_top + 46, 540 + 128, torso_bot - 4, 44, fill=THEME["apron"])
        CAP((540 - 88, torso_top + 16), (540 - 62, torso_top + 52), 14, fill=THEME["apron"])
        CAP((540 + 88, torso_top + 16), (540 + 62, torso_top + 52), 14, fill=THEME["apron"])
    if has("cardigan_accent"):
        RR(cx - torso_hw - u(0.03), torso_top, cx - torso_hw + u(0.09), torso_bot, u(0.05), fill=mix(ident, top, 0.45))
        RR(cx + torso_hw - u(0.09), torso_top, cx + torso_hw + u(0.03), torso_bot, u(0.05), fill=mix(ident, top, 0.45))
    for code in ("backpack", "hikingpack", "canvas_backpack"):
        if has(code):
            dark = mix(top, (30, 30, 30), 0.30)
            web = mix(ident, top, 0.25) if acc[code].get("accent") else dark  # 标识色织带（挂件行）
            CAP((540 - 96, torso_top + 4), (540 - 56, torso_top + 40), 20, fill=web)
            CAP((540 + 96, torso_top + 4), (540 + 56, torso_top + 40), 20, fill=web)
            bx_p, by_p = pfy(code, "bounce")
            RR(540 + 150 + bx_p, torso_top + 130 + by_p, 540 + 220 + bx_p, torso_top + 214 + by_p, 20, fill=dark)
            if has("bottle"):
                bo_x, bo_y = pfy("bottle", "swing")
                RR(540 + 160 + bo_x, torso_top + 104 + bo_y, 540 + 192 + bo_x, torso_top + 152 + bo_y, 12,
                   fill=THEME["bottle_blue"])
    if has("satchel"):
        CAP((540 - 116, torso_top + 8), (540 + 98, torso_bot - 46), 16, fill=THEME["satchel"])
        RR(540 + 66, torso_bot - 84, 540 + 152, torso_bot + 2, 18, fill=THEME["satchel"])
    for code, (bc, bw) in {"tote": (THEME["bag_canvas"], 92), "woven_bag": (THEME["bag_woven"], 92),
                           "book_tote": (THEME["paper_tote"], 92), "minibag": (THEME["bag_canvas"], 66),
                           "pouch": (THEME["bag_pouch"], 58)}.items():
        if has(code):
            bxr = 540 + 152
            kind = acc[code].get("physics")  # 挎包物理：swing 摆 / bounce 颠（plan §7.3-4）
            sx_p, sy_p = phys(seed, code, kind, t) if kind else (0.0, 0.0)
            ARC(bxr - bw // 2 + 14 + sx_p, torso_top + 40 + sy_p * 0.4, bxr + bw // 2 - 14 + sx_p,
                torso_top + 128 + sy_p * 0.4, 180, 360, 8, fill=bc)
            RR(bxr - bw // 2 + sx_p * 1.3, torso_top + 76 + sy_p, bxr + bw // 2 + sx_p * 1.3,
               torso_top + 76 + bw + 22 + sy_p, 20, fill=bc)
            if acc[code].get("accent"):  # 书袋挂饰（分镜 卡17：藏红花橙点缀——书袋挂饰）
                E(bxr + sx_p * 1.3 - 10, torso_top + 76 + bw + 22 + sy_p, bxr + sx_p * 1.3 + 10,
                  torso_top + 76 + bw + 32 + sy_p, fill=ident)
    if has("scarf"):
        col = ident if acc["scarf"].get("accent") else THEME["scarf_red"]
        sc_x, sc_y = pfy("scarf", "swing")
        RR(540 - 104, torso_top - 30, 540 + 104, torso_top + 34, 30, fill=col)
        RR(540 + 18 + sc_x, torso_top + 18 + sc_y * 0.5, 540 + 66 + sc_x, torso_top + 128 + sc_y * 0.5, 18,
           fill=col)  # 围巾垂尾随风摆
    if has("necklace"):
        nx, ny = pfy("necklace", "swing")
        ARC(540 - 58 + nx * 0.3, torso_top - 10, 540 + 58 + nx * 0.3, torso_top + 96, 15, 165, 5, fill=THEME["gold"])
        E(532 + nx, torso_top + 64 + ny, 548 + nx, torso_top + 80 + ny, fill=THEME["gold"])  # 吊坠摆动
    if has("lanyard"):
        CAP((540 - 52, torso_top - 2), (540 - 12, torso_top + 74), 9, fill=ident)
        CAP((540 + 52, torso_top - 2), (540 + 12, torso_top + 74), 9, fill=ident)
        lx_p, ly_p = pfy("lanyard", "swing")
        RR(540 - 28 + lx_p, torso_top + 70 + ly_p, 540 + 28 + lx_p, torso_top + 130 + ly_p, 12, fill=(255, 255, 255))
        RR(540 - 28 + lx_p, torso_top + 70 + ly_p, 540 + 28 + lx_p, torso_top + 84 + ly_p, 6, fill=ident)
    if has("pin_badge"):
        E(540 - 104, torso_top + 60, 540 - 72, torso_top + 92, fill=ident)
    if has("pen"):
        CAP((540 + 92, torso_top + 62), (540 + 104, torso_top + 100), 9, fill=THEME["pen_blue"])
    if has("zipper"):  # 外套拉链：前襟拉链线＋拉链头（Миша/热心大哥；标识色拉链头）
        LN([(cx, torso_top + u(0.04)), (cx, torso_top + G["torso_h"] * 0.88)], u(0.016),
           fill=mix(top, THEME["shade_dark"], 0.22))
        zc = ident if acc["zipper"].get("accent") else THEME["metal_dark"]
        CAP((cx, torso_top + u(0.10)), (cx, torso_top + u(0.24)), u(0.026), fill=zc)
        E(cx - u(0.016), torso_top + u(0.24), cx + u(0.016), torso_top + u(0.272), fill=zc)  # 拉链头坠
    if has("clipboard"):  # 胸前笔记夹板：板＋纸＋标识色夹扣（अर्जुन/笔记狂人）
        cbx = cx + torso_hw * 0.42
        RR(cbx - u(0.085), torso_top + u(0.09), cbx + u(0.085), torso_top + u(0.40), 8, fill=THEME["bag_woven"])
        RR(cbx - u(0.062), torso_top + u(0.135), cbx + u(0.062), torso_top + u(0.365), 4, fill=THEME["paper"])
        cbc = ident if acc["clipboard"].get("accent") else THEME["metal_dark"]
        RR(cbx - u(0.050), torso_top + u(0.105), cbx + u(0.050), torso_top + u(0.135), 5, fill=cbc)
        LN([(cbx - u(0.040), torso_top + u(0.19)), (cbx + u(0.040), torso_top + u(0.19))], 3, fill=THEME["pen_blue"])
    if has("towel_shoulder"):  # 肩搭白毛巾＋标识色毛巾条（阿豪/茶档街坊）
        twx = cx - torso_hw
        CAP((twx - u(0.03), torso_top - u(0.10)), (twx + u(0.04), torso_top + u(0.30)), u(0.10), fill=(246, 246, 240))
        twc = ident if acc["towel_shoulder"].get("accent") else mix((246, 246, 240), THEME["shade_dark"], 0.25)
        RR(twx + u(0.005), torso_top + u(0.20), twx + u(0.075), torso_top + u(0.30), 5, fill=twc)
    if has("camera") or has("camera_neck"):
        s2 = ident if has("strap_accent") else THEME["camera_body"]
        ccode = "camera" if has("camera") else "camera_neck"
        cx_p, cy_p = pfy(ccode, "swing")
        CAP((540 - 74, torso_top - 4), (540 - 30 + cx_p * 0.4, torso_top + 66), 9, fill=s2)
        CAP((540 + 74, torso_top - 4), (540 + 30 + cx_p * 0.4, torso_top + 66), 9, fill=s2)
        RR(540 - 48 + cx_p, torso_top + 52 + cy_p, 540 + 48 + cx_p, torso_top + 132 + cy_p, 16, fill=THEME["camera_body"])
        E(540 - 18 + cx_p, torso_top + 76 + cy_p, 540 + 18 + cx_p, torso_top + 112 + cy_p, fill=THEME["lens_blue"])
    if has("sunglasses_neck"):
        gx_n, _ = pfy("sunglasses_neck", "swing")
        RR(540 - 44 + gx_n, torso_top + 58, 540 + 44 + gx_n, torso_top + 94, 14, fill=THEME["metal_dark"])
        CAP((540 - 40 + gx_n, torso_top + 68), (540 + 40 + gx_n, torso_top + 68), 6, fill=THEME["metal_dark"])
        E(540 - 34 + gx_n * 1.4, torso_top + 62, 540 - 12 + gx_n * 1.4, torso_top + 74,
          fill=THEME["glint_blue"])  # 镜片反光（qa_motion 探针）
    if has("map"):
        RR(540 - 178, torso_top + 118, 540 - 92, torso_top + 182, 10, fill=THEME["paper_map"])
        CAP((540 - 166, torso_top + 136), (540 - 104, torso_top + 162), 5, fill=ident)
    if has("planner"):
        RR(540 - 70, torso_top + 96, 540 + 20, torso_top + 168, 12, fill=THEME["paper"])
        CAP((540 - 70, torso_top + 120), (540 + 20, torso_top + 120), 4, fill=ident)
    if has("pocketbook"):
        RR(540 - 174, torso_top + 108, 540 - 82, torso_top + 178, 12, fill=THEME["book_leather"])
    if has("beads") and pose.get("hand_prop") != "beads":
        bx_b, by_b = pfy("beads", "swing")
        for k in range(5):
            ak = k * 1.15
            cxx = 540 + 162 + bx_b + math.cos(ak) * 16
            cyy = torso_top + 140 + by_b * 0.6 + math.sin(ak) * 16
            E(cxx - 6, cyy - 6, cxx + 6, cyy + 6, fill=THEME["beads"])
    if has("bottle_big") and pose.get("hand_prop") != "bottle":
        bx_g, by_g = pfy("bottle_big", "swing")
        RR(540 + 144 + bx_g, torso_top + 100 + by_g * 0.5, 540 + 182 + bx_g, torso_top + 180 + by_g * 0.5, 16,
           fill=THEME["bottle_green"])

    # ================= 手臂（胶囊袖 + 圆手 + 袖口） =================
    # 画在躯干之后、颈与头之前：袖子是「衣服层」，抬臂姿态（wave/thumbs_up/hand_shoot…）
    # 会把袖子胶囊扫过人脸——衣层在脸前会遮嘴（2026-10-03 用户反馈），故脸/嘴永远画在手臂之上；
    # 各姿态的手都落在脸轮廓之外（肩点外展），移到脸后不丢姿态可读性。face_cam 是举到脸前的
    # 道具相机，仍留在表情之后画（要的就是遮脸）。

    # 袖子色阶（坑⑱）：纯平涂无描边，叠在躯干上的手臂只能靠色阶读出来
    sleeve = sleeve_color(top)

    def arm(side, a1, a2, hand="open", prop=None):
        s = side
        # 肩点内收（坑⑱）：落在躯干轮廓上（sh_x = sh_hw − arm_w·0.18）。
        # 旧值 arm_w·0.30 加上 7° 静止角，上臂整条埋进躯干——剪影里没有手臂，
        # 只剩两只贴在身侧的浮球手；现在肩点外移 + 静止角 14°，手臂读得出来。
        sh = (cx + s * sh_x, sh_y)
        a1r, a2r = math.radians(a1), math.radians(a2)
        el = (sh[0] + s * math.sin(a1r) * up_len, sh[1] + math.cos(a1r) * up_len)
        ha = (el[0] + s * math.sin(a1r + a2r) * lo_len, el[1] + math.cos(a1r + a2r) * lo_len)
        wr = (el[0] + (ha[0] - el[0]) * 0.82, el[1] + (ha[1] - el[1]) * 0.82)
        CAP(sh, el, arm_w, fill=sleeve)
        CAP(el, ha, arm_w * 0.88, fill=sleeve)
        c0 = (el[0] + (ha[0] - el[0]) * 0.72, el[1] + (ha[1] - el[1]) * 0.72)
        c1 = (el[0] + (ha[0] - el[0]) * 0.88, el[1] + (ha[1] - el[1]) * 0.88)
        CAP(c0, c1, arm_w * 0.90, fill=mix(sleeve, THEME["shade_dark"], 0.16))  # 袖口
        hr = hand_r
        E(ha[0] - hr, ha[1] - hr, ha[0] + hr, ha[1] + hr, fill=skin)
        if hand == "thumb":
            CAP((ha[0] + s * hand_r * 0.2, ha[1] - hr - u(0.018)), (ha[0] + s * hand_r * 0.66, ha[1] - hr - u(0.088)),
                u(0.044), fill=skin)
        if hand == "index":
            ai = a1r + a2r
            tip = (ha[0] + s * math.sin(ai) * u(0.13), ha[1] + math.cos(ai) * u(0.13))
            CAP((ha[0] + s * u(0.018), ha[1] - u(0.018)), tip, u(0.036), fill=skin)
        if prop == "bottle":
            RR(ha[0] - u(0.055), ha[1] - u(0.197), ha[0] + u(0.055), ha[1] - u(0.028), u(0.04), fill=THEME["bottle_green"])
            RR(ha[0] - u(0.028), ha[1] - u(0.242), ha[0] + u(0.028), ha[1] - u(0.186), u(0.018), fill=THEME["bottle_green_dark"])
        if prop == "beads":
            for k in range(6):
                ak = k * 1.05
                cxx, cyy = ha[0] + math.cos(ak) * u(0.062), ha[1] + u(0.017) + math.sin(ak) * u(0.062)
                E(cxx - u(0.02), cyy - u(0.02), cxx + u(0.02), cyy + u(0.02), fill=THEME["beads"])
        if prop == "camera":
            RR(ha[0] - u(0.096), ha[1] - u(0.073), ha[0] + u(0.096), ha[1] + u(0.073), u(0.034), fill=THEME["camera_body"])
            E(ha[0] - u(0.039), ha[1] - u(0.039), ha[0] + u(0.039), ha[1] + u(0.039), fill=THEME["lens_blue"])
        return ha, wr

    rest_a1, rest_a2 = G["arm_rest"]   # 静止姿态角（face_geo 单一事实源，探针同源）
    aL = pose.get("armL") or (rest_a1 + 5 * math.sin(2 * math.pi * t * 0.55), rest_a2, "open", None)
    aR = pose.get("armR") or (rest_a1 - 5 * math.sin(2 * math.pi * t * 0.55), rest_a2, "open", None)
    arm(-1, aL[0], aL[1], aL[2], aL[3] if len(aL) > 3 else None)
    ha_pos, wr_pos = arm(1, aR[0], aR[1], aR[2], aR[3] if len(aR) > 3 else None)
    for code, bc in (("watch", ident), ("bracelet", THEME["gold"]),
                     ("bracelet_leather", THEME["bracelet_leather"]), ("bracelet_woven", THEME["bracelet_woven"])):
        if has(code):
            CAP((wr_pos[0] - u(0.05), wr_pos[1] - u(0.022)), (wr_pos[0] + u(0.05), wr_pos[1] - u(0.022)),
                u(0.042), fill=bc)
    if pose.get("hand_prop") == "sparkle":
        for ang3 in (210, 270, 330):
            r0, r1 = hand_r * 0.85, hand_r * 1.52
            CAP((ha_pos[0] + math.cos(math.radians(ang3)) * r0, ha_pos[1] + math.sin(math.radians(ang3)) * r0),
                (ha_pos[0] + math.cos(math.radians(ang3)) * r1, ha_pos[1] + math.sin(math.radians(ang3)) * r1),
                u(0.02), fill=THEME["sparkle"])
    if pose.get("hand_prop") == "flash":
        E(ha_pos[0] - u(0.18), ha_pos[1] - u(0.18), ha_pos[0] + u(0.18), ha_pos[1] + u(0.18), fill=(255, 250, 214))

    # ================= 颈与头 =================
    neck_c = mix(skin, skin_sh, NECK_SHADE_F)  # 颈部受光少：skinShade 压深（qa_char 探针同源）
    RR(cx - neck_hw, G["neck_top"], cx + neck_hw, G["neck_bot"], u(0.05), fill=neck_c)
    RR(cx - neck_hw, G["neck_top"], cx + neck_hw, G["neck_top"] + u(0.022), u(0.02),
       fill=mix(skin_sh, skin, 0.30))  # 下颌阴影
    if face in JAW:  # heart / square：上半椭圆 + 直边 + 超椭圆下颌（参数见 JAW）
        jp = JAW[face]
        PIE(hx - rx, hy - ry, hx + rx, hy + ry, 180, 360, fill=skin)
        if jp["y0"] > 0:      # 颊部到下颌起点之间补直边（square 从 y=0 起，无需补）
            d.rectangle(TB(hx - rx, hy, hx + rx, hy + ry * jp["y0"]), fill=skin)
        jaw = []
        for sg in (-1, 1):
            ks = range(jp["n"] + 1) if sg < 0 else range(jp["n"] - 1, -1, -1)  # 顶点只出一次
            for k in ks:
                jw, jv = jaw_point(face, k / jp["n"])
                jaw.append(T((hx + sg * rx * jw, hy + ry * jv)))
        d.polygon(jaw, fill=skin)
    else:
        E(hx - rx, hy - ry, hx + rx, hy + ry, fill=skin)
    for s in (-1, 1):  # 耳朵（多数发型被侧发覆盖，露出即增加真实感）
        eax = hx + s * rx * 0.94
        E(eax - u(0.045), eye_y - u(0.085), eax + u(0.045), eye_y + u(0.045), fill=skin)
        E(eax + s * u(0.005) - u(0.022), eye_y - u(0.058), eax + s * u(0.005) + u(0.022), eye_y - u(0.010),
          fill=mix(skin, skin_sh, 0.30))  # 耳窝影走 skinShade（不再写死）

    # ================= 前发（有机圆润 + 高光） =================
    cap_lo = hy + ry * 0.45
    PIE(hx - rx - 10, hy - ry - 10, hx + rx + 10, cap_lo, 182, 358, fill=hair_c)
    ARC(hx - rx * 0.60, hy - ry * 0.94, hx + rx * 0.28, hy - ry * 0.34, 220, 310, 12, fill=hl_c)
    if style in ("bob_bangs", "long_bangs"):
        for fx, fr in ((-0.62, 0.13), (-0.02, 0.16), (0.58, 0.13)):
            E(hx + rx * fx - rx * fr, hy - ry * 0.26 - rx * fr,
              hx + rx * fx + rx * fr, hy - ry * 0.26 + rx * fr, fill=hair_c)
    if style in ("bob", "bob_bangs", "wavy_lob", "wavy_long", "long_straight", "long_bangs"):
        yl = 0.55 if style in ("bob", "bob_bangs") else (0.95 if style == "wavy_lob" else 1.25)
        for s in (-1, 1):
            side_curtain(s, hy - ry * 0.45, hy + ry * yl, out_w=34.0, in_w=22.0)
    if style in ("short", "short_messy", "short_gray", "short_stubble", "crop", "crop_ahoge"):
        for fx, fy, fr in ((-0.45, -1.02, 22), (0.05, -1.08, 24), (0.52, -1.00, 20)):
            E(hx + rx * fx - fr, hy + ry * fy - fr, hx + rx * fx + fr, hy + ry * fy + fr, fill=hair_c)
        if style == "short_messy":
            E(hx + rx * 0.72, hy - ry * 1.04, hx + rx * 0.98 + 16, hy - ry * 0.84, fill=hair_c)
        if style == "short_stubble":
            ARC(hx - rx * 0.60, hy + ry * 0.50, hx + rx * 0.60, hy + ry * 1.05, 30, 150, 10,
                fill=mix(hair_c, skin, 0.55))
    if style in ("short_ahoge", "crop_ahoge"):  # 呆毛随晚风一颤（分镜 卡20 彩蛋；qa_motion 探针）
        ax = 5.0 * math.sin(2 * math.pi * 0.9 * t + 2 * math.pi * rnd(f"{seed}:ahoge"))
        CAP((hx + 10, hy - ry * 0.92), (hx + 52 + ax, hy - ry * 1.28 - abs(ax) * 0.35), 12, fill=hair_c)
        CAP((hx + 52 + ax, hy - ry * 1.28 - abs(ax) * 0.35), (hx + 88 + ax * 1.5, hy - ry * 1.08 - abs(ax) * 0.15),
            12, fill=hair_c)
    if style == "short_part":  # 侧分头：斜扫刘海＋分缝高光（江远/人形路标）
        for fx, fy, fr in ((-0.46, -0.62, 0.40), (0.10, -0.56, 0.42), (0.58, -0.64, 0.32)):
            E(hx + rx * fx - rx * fr, hy + ry * fy - rx * fr, hx + rx * fx + rx * fr,
              hy + ry * fy + rx * fr, fill=hair_c)
        CAP((hx - rx * 0.58, hy - ry * 0.74), (hx - rx * 0.28, hy - ry * 1.00), u(0.026), fill=hl_c)
    if style == "short_neat":  # 一丝不苟短发：平直刘海边（Théo/慢先生）
        RR(hx - rx * 0.82, hy - ry * 0.60, hx + rx * 0.82, hy - ry * 0.34, 10, fill=hair_c)
        CAP((hx - rx * 0.66, hy - ry * 0.70), (hx - rx * 0.20, hy - ry * 0.94), u(0.024), fill=hl_c)
    if style in ("short_wavy", "short_curly", "curly_short", "curly_volume", "undercut_curly"):
        a_lo, a_hi = (232, 308) if style == "undercut_curly" else (198, 342)
        n = 5 if style == "undercut_curly" else 7
        rr2 = 34 if style == "curly_volume" else 26
        for i in range(n):
            ang2 = math.radians(a_lo + i * (a_hi - a_lo) / (n - 1))
            cxx = hx + (rx + 4) * math.cos(ang2)
            cyy = hy + (ry + 4) * math.sin(ang2)
            E(cxx - rr2, cyy - rr2, cxx + rr2, cyy + rr2, fill=hair_c)
    if style == "bun":
        E(hx - 44, hy - ry - 86, hx + 44, hy - ry + 2, fill=hair_c)
        E(hx - 30, hy - ry - 72, hx + 30, hy - ry - 16, fill=hl_c)
    if style in ("ponytail_high", "curly_ponytail"):
        E(hx + rx * 0.70 - 26, hy - ry * 0.66 - 26, hx + rx * 0.70 + 26, hy - ry * 0.66 + 26,
          fill=ident if has("hair_tie") else mix(hair_c, (255, 255, 255), 0.25))
    if style == "ponytail_low":
        E(hx - rx * 0.90 - 22, hy + ry * 0.14 - 22, hx - rx * 0.90 + 22, hy + ry * 0.14 + 22,
          fill=ident if has("hair_tie") else mix(hair_c, (255, 255, 255), 0.25))
    if style in ("braid", "braid_long"):
        n2 = 4 if style == "braid" else 6
        fy_end = -0.02 + n2 * (0.52 if style == "braid" else 0.40)
        E(hx - rx * 1.00 - 18, hy + ry * fy_end - 14, hx - rx * 1.00 + 18, hy + ry * fy_end + 16, fill=ident)

    if has("beard") and not BEARD_LEGACY:  # 表情之前画：嘴要盖在胡子上面
        # 旧实现是一个 PIE（顶边 0.82·ry 的水平直弦、底边伸到 1.30·ry），整张脸从嘴以下
        # 糊成一条围兜一直糊到脖子上——「嘴像长在脖子上」（坑㉓，2026-10-03 用户反馈）。
        # 拆成两件：**八字胡**（压在嘴上、两端挑出胡须线）+ **络腮**（实心块：上缘一条
        # 胡须线、下缘沿脸廓 face_profile 走、圆胡尖只探出下巴 0.03·ry）。
        # 注意不能把络腮画成「内外两条同起点的曲线」——那会在鬓角收成零厚度、只剩一个人字形。
        bc = mix(hair_c, skin, 0.25)
        v_side, v_top = 0.42, 0.54           # 鬓角起点 / 胡须线
        w_side = face_profile(face, v_side)
        w_top = face_profile(face, v_top) * 0.90
        top = [(hx - w_side * rx, hy + ry * v_side), (hx - w_top * rx, hy + ry * v_top),
               (hx, hy + ry * v_top),
               (hx + w_top * rx, hy + ry * v_top), (hx + w_side * rx, hy + ry * v_side)]
        nb = 26
        lower = []                            # 右鬓角 → 下巴 → 左鬓角，严格沿脸廓
        for k in range(2 * nb + 1):
            uu = k / (2 * nb)
            v = v_side + (1.0 - v_side) * (1 - abs(2 * uu - 1))
            lower.append((hx + face_profile(face, min(v, 1.0)) * rx * (2 * uu - 1), hy + v * ry))
        d.polygon([T(p) for p in (top + lower[::-1])], fill=bc)
        E(hx - rx * 0.18, hy + ry * 0.93, hx + rx * 0.18, hy + ry * 1.03, fill=bc)   # 圆胡尖
        # 八字胡：贴上唇一小片，两端**挑到胡须线以上**（这就是「八字」的形状来源）
        d.polygon([T(p) for p in (
            (hx - rx * 0.32, mouth_y - ry * 0.17), (hx - rx * 0.20, mouth_y - ry * 0.13),
            (hx, mouth_y - ry * 0.09),
            (hx + rx * 0.20, mouth_y - ry * 0.13), (hx + rx * 0.32, mouth_y - ry * 0.17),
            (hx + rx * 0.20, mouth_y + ry * 0.02), (hx, mouth_y + ry * 0.04),
            (hx - rx * 0.20, mouth_y + ry * 0.02))], fill=bc)
    elif has("beard"):  # BEARD_LEGACY：坑㉓ 之前的 PIE 形胡须，**只给反向验证用**
        PIE(hx - rx * 0.70, hy + ry * 0.34, hx + rx * 0.70, hy + ry * 1.30, 25, 155,
            fill=mix(hair_c, skin, 0.25))

    # ================= 表情 =================
    mood = MOOD_FACE[ctx["mood"]]
    lift = mood["lift"] + ctx.get("brow_lift_extra", 0)
    tilt = mood["tilt"]
    eye_k = EYE_MOOD[ctx["mood"]]  # 眼形：happy 微闭笑眼 / puzzled 睁大（plan §4 眼神变化）
    gdx, gdy = gaze(seed, t)  # 视线跟随镜头：漂移 ≤ (巩膜−瞳孔) 余量 × 0.35（探针安全）
    gpx = gdx * (scl_rx - pup_r) * 0.35
    gpy = gdy * (scl_ry - pup_r * 1.2) * 0.35
    for s in (-1, 1):
        ex = hx + s * eye_dx
        if ctx["blink"]:
            ARC(ex - scl_rx * 0.92, eye_y - scl_ry * 0.45, ex + scl_rx * 0.92, eye_y + scl_ry * 0.55,
                15, 165, u(0.024), fill=THEME["ink"])
        else:
            E(ex - scl_rx, eye_y - scl_ry * eye_k, ex + scl_rx, eye_y + scl_ry * eye_k, fill=(255, 255, 255))
            px, py = ex + gpx, eye_y + gpy
            E(px - pup_r, py - pup_r * 1.15, px + pup_r, py + pup_r * 1.25, fill=THEME["ink"])
            E(px - pup_r * 0.78, py - pup_r * 0.90, px - pup_r * 0.16, py - pup_r * 0.16,
              fill=(255, 255, 255))
            E(px + pup_r * 0.25, py + pup_r * 0.35, px + pup_r * 0.70, py + pup_r * 0.80,
              fill=(255, 255, 255))
            if female:
                CAP((ex + s * (scl_rx - u(0.008)), eye_y - scl_ry * eye_k * 0.82),
                    (ex + s * (scl_rx + u(0.040)), eye_y - scl_ry * eye_k - u(0.040)), u(0.020), fill=THEME["ink"])
        brow_y = brow_y0 - lift
        CAP((ex - s * u(0.062), brow_y - tilt), (ex + s * u(0.078), brow_y + tilt * 0.4), u(0.036),
            fill=THEME["ink"])
    mcx, mcy = hx, mouth_y
    op = ctx["openness"]
    WH = G["WH"]
    if op > 0.07:
        mw, mo = WH * (0.155 + 0.05 * op), u(0.035) + u(0.10) * op
        PIE(mcx - mw, mcy - mo, mcx + mw, mcy + mo, 0, 180, fill=THEME["mouth"])
        mt = mo * 0.45
        PIE(mcx - mw * 0.60, mcy + mo * 0.35 - mt, mcx + mw * 0.60, mcy + mo * 0.35 + mt, 0, 180,
            fill=THEME["tongue"])
    else:
        sw = WH * (0.155 + 0.05 * mood["smile"])
        if mood["smile"] > 0.4:
            ARC(mcx - sw, mcy - sw * 0.55, mcx + sw, mcy + sw * 0.80, 28, 152, u(0.026), fill=THEME["ink"])
        else:
            CAP((mcx - u(0.055), mcy), (mcx + u(0.055), mcy + (4 if tilt else 0)), u(0.022), fill=THEME["ink"])
    if p["energy"] == "lively":
        for s in (-1, 1):
            E(hx + s * 0.42 * WH - u(0.05), blush_y - u(0.028), hx + s * 0.42 * WH + u(0.05), blush_y + u(0.028),
              fill=THEME["blush"])

    # ================= 头部配饰 =================
    for code in ("glasses_round", "glasses_thin", "glasses_square", "glasses_plastic"):
        if has(code):
            col = {"glasses_plastic": THEME["glasses_plastic"],
                   "glasses_thin": THEME["glasses_thin"]}.get(code, THEME["glasses_dark"])
            wd = u(0.016) if code == "glasses_thin" else u(0.024)
            for s in (-1, 1):
                ex = hx + s * eye_dx
                if code == "glasses_round":
                    d.ellipse(TB(ex - scl_rx * 0.88, eye_y - scl_ry * 0.88, ex + scl_rx * 0.88, eye_y + scl_ry * 0.88),
                              outline=col, width=max(1, int(wd * sc * ss)))
                else:
                    d.rounded_rectangle(TB(ex - scl_rx * 0.92, eye_y - scl_ry * 0.78, ex + scl_rx * 0.92, eye_y + scl_ry * 0.78),
                                        u(0.035) * sc * ss, outline=col, width=max(1, int(wd * sc * ss)))
                eax = hx + s * rx * 0.94
                CAP((ex + s * scl_rx * 0.92, eye_y - scl_ry * 0.40), (eax + s * u(0.02), eye_y - scl_ry * 0.55),
                    wd * 0.7, fill=col)  # 镜腿
            CAP((hx - eye_dx + scl_rx * 0.85, eye_y - scl_ry * 0.38), (hx + eye_dx - scl_rx * 0.85, eye_y - scl_ry * 0.38),
                wd * 0.8, fill=col)  # 鼻梁
            if acc[code].get("physics") == "reflect":  # 镜片反光随时间滑动（qa_motion 探针）
                ggx = phys(seed, code, "reflect", t)[0]
                for s2 in (-1, 1):
                    ex2 = hx + s2 * eye_dx
                    E(ex2 - scl_rx * 0.62 + ggx, eye_y - scl_ry * 0.58,
                      ex2 - scl_rx * 0.30 + ggx, eye_y - scl_ry * 0.34, fill=THEME["glint_soft"])
    if has("sunglasses_head"):  # 顶戴：镜架倒扣在发顶，不遮眼（几何见 SUNGLASS_HEAD）
        S = SUNGLASS_HEAD
        sg = sunglasses_head_geo(G, hdx, hdy)
        sy0 = sg["sy0"]
        ggx_h = pfy("sunglasses_head", "reflect")[0]
        for s in (-1, 1):
            c = hx + s * S["dx"]
            RR(c - S["out_rx"], sy0 - S["out_up"], c + S["out_rx"], sy0 + S["out_dn"],
               S["rad"], fill=THEME["metal_dark"])
            E(c - S["lens_rx"], sy0 - S["lens_up"], c + S["lens_rx"], sy0 + S["lens_dn"],
              fill=THEME["lens"])
            E(c - 20 + ggx_h, sy0 - 14, c - 4 + ggx_h, sy0 - 4, fill=THEME["glint_blue"])
        CAP((hx - 28, sy0 - 14), (hx + 28, sy0 - 18), 7, fill=THEME["metal_dark"])
    hbdy = pfy("knit_hat", "bounce")[1]  # 帽子随步伐/点头轻弹（挂件物理；分镜 卡11）
    cbdy = pfy("cap_backward", "bounce")[1]
    shdy = pfy("sun_hat", "bounce")[1]
    if has("knit_hat"):
        PIE(hx - rx - 6, hy - ry - 16 + hbdy, hx + rx + 6, hy + ry * 0.17, 182, 358, fill=ident)
        RR(hx - rx - 10, hy - ry * 0.46 + hbdy, hx + rx + 10, hy - ry * 0.24 + hbdy, 16, fill=(255, 255, 255))
        E(hx - 26, hy - ry - 66 + hbdy, hx + 26, hy - ry - 14 + hbdy, fill=(255, 255, 255))
    if has("cap_backward"):
        PIE(hx - rx - 2, hy - ry - 8 + cbdy, hx + rx + 2, hy - ry * 0.10, 182, 358, fill=ident)
        E(hx - rx * 1.42, hy - ry * 0.74 + cbdy, hx - rx * 0.20, hy - ry * 0.36 + cbdy, fill=ident)
    if has("sun_hat"):
        E(hx - rx - 52, hy - ry * 0.78 + shdy, hx + rx + 52, hy - ry * 0.32 + shdy, fill=THEME["straw"])
        PIE(hx - rx * 0.78, hy - ry - 24 + shdy, hx + rx * 0.78, hy + ry * 0.02, 182, 358, fill=THEME["straw"])
        E(hx - rx * 0.78, hy - ry * 0.54 + shdy, hx + rx * 0.78, hy - ry * 0.36 + shdy, fill=ident)
    if has("headband_red"):  # 红发带＋意大利三色旗 wink（分镜 卡23：红发带飘起）
        gbdy = pfy("headband_red", "bounce")[1]
        ARC(hx - rx, hy - ry * 0.68 + gbdy, hx + rx, hy - ry * 0.14 + gbdy, 195, 345, 16, fill=THEME["headband_red"])
        for i, c in enumerate(THEME["it_flag"]):  # 右鬓角三色小条（绿白红；qa_char 探针）
            RR(hx + rx * 0.86 + i * 9, hy - ry * 0.52 + gbdy, hx + rx * 0.86 + i * 9 + 7, hy - ry * 0.24 + gbdy,
               2, fill=c)
    if has("hairpin"):
        CAP((hx + rx * 0.36, hy - ry * 0.80), (hx + rx * 0.64, hy - ry * 0.58), 12, fill=ident)
    if has("hairpin_clear"):
        CAP((hx + rx * 0.38, hy - ry * 0.74), (hx + rx * 0.68, hy - ry * 0.54), 10, fill=THEME["hairpin_clear"])
        if acc["hairpin_clear"].get("physics") == "reflect":  # 透明发夹一闪（分镜 卡27；qa_motion 探针）
            hgx = phys(seed, "hairpin_clear", "reflect", t)[0]
            E(hx + rx * 0.50 - 4 + hgx * 0.6, hy - ry * 0.68, hx + rx * 0.50 + 4 + hgx * 0.6, hy - ry * 0.60,
              fill=(255, 255, 255))
    if has("earrings_hoop"):
        hox, hoy = pfy("earrings_hoop", "swing")
        for s in (-1, 1):
            ARC(hx + s * rx * 0.96 - 14 + hox, hy + ry * 0.38 + hoy, hx + s * rx * 0.96 + 14 + hox,
                hy + ry * 0.38 + 28 + hoy, 0, 360, 5, fill=THEME["gold"])
    if has("jhumki"):
        jhx, jhy = pfy("jhumki", "swing")
        for s in (-1, 1):
            ex2 = hx + s * rx * 0.97
            E(ex2 - 9 + jhx, hy + ry * 0.36 + jhy, ex2 + 9 + jhx, hy + ry * 0.36 + jhy + 18, fill=THEME["gold"])
    if has("earrings_pearl"):
        for s in (-1, 1):
            E(hx + s * rx * 0.97 - 9, hy + ry * 0.36, hx + s * rx * 0.97 + 9, hy + ry * 0.36 + 18,
              fill=THEME["pearl"])
            E(hx + s * rx * 0.97 - 4, hy + ry * 0.36 + 4, hx + s * rx * 0.97 + 1, hy + ry * 0.36 + 9,
              fill=(255, 255, 255))  # 珍珠高光
    if has("headphones_neck") or has("headphones_one_ear"):
        hpc = "headphones_one_ear" if has("headphones_one_ear") else "headphones_neck"
        hdy2 = pfy(hpc, "bounce")[1]
        ARC(hx - rx * 0.90, hy + ry * 0.52, hx + rx * 0.90, hy + ry * 1.35, 15, 165, 13, fill=THEME["headphones"])
        sides = (-1,) if has("headphones_one_ear") else (-1, 1)
        for s in sides:
            E(hx + s * rx * 0.95 - 24, hy + ry * 0.88 + hdy2, hx + s * rx * 0.95 + 24, hy + ry * 0.88 + 52 + hdy2,
              fill=THEME["headphones"])
            E(hx + s * rx * 0.95 - 12, hy + ry * 0.88 + 14 + hdy2, hx + s * rx * 0.95 + 12, hy + ry * 0.88 + 38 + hdy2,
              fill=ident)

    # 手臂层已移至「颈与头」之前（衣服不得在人脸前面遮嘴）；face_cam 是举到脸前的道具相机，
    # 要的就是遮脸，故留在表情之后画。
    if pose.get("face_cam"):
        RR(hx - u(0.20), hy - u(0.11), hx + u(0.20), hy + u(0.11), u(0.05), fill=THEME["camera_body"])
        E(hx - u(0.062), hy - u(0.056), hx + u(0.062), hy + u(0.056), fill=THEME["lens_blue"])

# ---- 姿态库 ----

# pose_for 已实现的姿态码全集（场景线据此校验剧本标注，勿与 pose_for 实现脱节）
POSE_CODES = frozenset({
    "wave", "ciao_wave", "thumbs_up", "palm_open", "point", "nod", "shrug", "mini_jump",
    "jump_celebrate", "run_out", "turn_freeze", "come_along", "kick", "snap", "camera_snap",
    "chest_pat", "index_wait", "finger_count", "both_hands", "beads_ponder", "cap_tap",
    "scratch_head", "hand_shoot", "brow_raise", "head_tilt", "breath", "planner_snap",
    "clap", "fist", "bottle_raise", "deadpan_nod", "twirl", "lean_in", "pocket_sway",
    "head_tilt_smile", "thumbs_run", "shoot_run",
})


def pose_for(code, u, t, p):
    """返回姿态参数：armL/armR=(a1,a2,hand), legL/legR, head_dx/dy, squash, yoff, extras"""
    P = {}
    if code == "wave" or code == "ciao_wave":
        a1 = 138 if code == "wave" else 146
        P["armR"] = (a1, 26 + 26 * math.sin(t * 11), "open")
    elif code == "thumbs_up":
        P["armR"] = (150, 18, "thumb")
    elif code == "palm_open":
        P["armR"] = (78, 28, "open")
    elif code == "point":
        P["armR"] = (96, 6, "index")
    elif code == "nod":
        P["head_dy"] = 12 * math.sin(min(u, 1) * math.pi * 3) * (1 - min(u, 1))
    elif code == "shrug":
        P["armL"] = (52, 66, "open")
        P["armR"] = (52, 66, "open")
        P["yoff"] = -10
        P["head_dy"] = -4
    elif code == "mini_jump":
        hop = -abs(math.sin(u * math.pi * 2)) * jump_height(p)  # 起跳高度随 movement.bounce（plan §4）
        P["yoff"] = hop
        P["squash"] = 0.05 * math.sin(u * math.pi * 4)
        P["armL"] = (96, 30, "open")
        P["armR"] = (96, 30, "open")
    elif code == "jump_celebrate":  # 跳跃庆祝（plan §4.2 原语；示范场景二幕八专用）
        # squash-stretch：起跳蓄力下压 → 腾空纵向拉伸 → 落地压扁回弹
        air = abs(math.sin(u * math.pi * 2))
        P["yoff"] = -air * jump_height(p) * 1.15
        P["squash"] = 0.085 * math.cos(u * math.pi * 4) * (1 - 0.45 * air)
        P["armL"] = (152 - 14 * air, 18, "open")
        P["armR"] = (152 - 14 * air, 18, "open")
        P["head_dy"] = -5 * air
    elif code == "run_out":
        P["xoff"] = 1500 * ease_out_cubic(u)
        P["legL"] = 28 * math.sin(t * 16)
        P["legR"] = -28 * math.sin(t * 16)
        P["armL"] = (40 + 20 * math.sin(t * 16), 40, "open")
        P["armR"] = (40 - 20 * math.sin(t * 16), 40, "open")
        P["yoff"] = -6 * abs(math.sin(t * 16))
    elif code == "turn_freeze":
        P["xoff"] = -34 * u
        P["head_dx"] = -12 * u
        P["armR"] = (58, 122, "open")
    elif code == "come_along":
        P["armR"] = (86, 24 + 14 * math.sin(t * 7), "open")
        P["head_dx"] = 4
    elif code == "kick":
        P["legR"] = 38 * math.sin(min(u * 1.4, 1) * math.pi)
        P["skate_kick"] = math.sin(min(u * 1.4, 1) * math.pi)
        P["armL"] = (120, 30, "open")
    elif code == "snap":
        P["armR"] = (42, 112, "fist")
        if 0.3 < u < 0.75:
            P["hand_prop"] = "sparkle"
    elif code == "camera_snap":
        P["armL"] = (118, 62, "open")
        P["armR"] = (118, 62, "open")
        P["face_cam"] = True
        if 0.35 < u < 0.7:
            P["hand_prop"] = "flash"
    elif code == "chest_pat":
        P["armR"] = (32, 116 + 14 * math.sin(t * 8), "open")
    elif code == "index_wait":
        P["armR"] = (142, 22, "index")
    elif code == "finger_count":
        P["armR"] = (122, 32, "index")
    elif code == "both_hands":
        P["armL"] = (104, 18, "open")
        P["armR"] = (104, 18, "open")
    elif code == "beads_ponder":
        P["armR"] = (46, 100, "open", "beads")
        P["hand_prop"] = None
        P["head_dx"] = 7
        P["head_dy"] = 4
    elif code == "cap_tap":
        P["armR"] = (148, 40 + 12 * math.sin(t * 10), "open")
    elif code == "scratch_head":
        P["armR"] = (132, 74 + 12 * math.sin(t * 9), "open")
    elif code == "hand_shoot":
        P["armR"] = (176, 2, "open")
    elif code == "brow_raise":
        P["brow_lift_extra"] = 10 * math.sin(min(u, 1) * math.pi)
    elif code == "head_tilt":
        P["head_dx"] = 8
    elif code == "breath":
        P["squash"] = 0.035 * math.sin(min(u, 1) * math.pi)
        P["yoff"] = -8 * math.sin(min(u, 1) * math.pi)
        P["armL"] = (24, 14, "open")
        P["armR"] = (24, 14, "open")
    elif code == "planner_snap":
        P["armL"] = (36, 108, "open")
        P["armR"] = (36, 108, "open")
        if 0.25 < u < 0.6:
            P["hand_prop"] = "sparkle"
    elif code == "clap":
        P["armL"] = (44, 96, "open")
        P["armR"] = (44, 96, "open")
    elif code == "fist":
        P["armR"] = (46, 114, "fist")
    elif code == "bottle_raise":
        P["armR"] = (64, 92, "open", "bottle")
    elif code == "deadpan_nod":  # 卡20：面无表情点头（数据触发两次＝分镜"只两次"）
        P["head_dy"] = 10 * math.sin(min(u, 1) * math.pi * 2) * (1 - 0.4 * min(u, 1))
    elif code == "twirl":  # 卡05/09 入场旋转：水平压缩翻转读作转身
        P["xscale"] = 0.16 + 0.84 * abs(math.cos(min(u, 1) * math.pi * 2))
        P["yoff"] = -14 * abs(math.sin(min(u, 1) * math.pi * 2))
        P["armL"] = (96, 26, "open")
        P["armR"] = (96, 26, "open")
    elif code == "lean_in":  # 卡25：探身取景
        P["head_dx"] = 8
        P["head_dy"] = 5
        P["armR"] = (104, 38, "open")
    elif code == "pocket_sway":  # 卡24：插兜晃身
        P["armL"] = (14, 10, "open")
        P["armR"] = (14, 10, "open")
        P["head_dx"] = 6 * math.sin(min(u, 1) * math.pi * 2)
    elif code == "head_tilt_smile":  # 卡27：侧头一笑定格
        P["head_dx"] = 13
        P["head_dy"] = 2
        P["armR"] = (58, 30, "open")
    elif code == "thumbs_run":  # 卡28：thumbs-up 后招手小跑出画
        if u < 0.45:
            P["armR"] = (150, 18, "thumb")
            P["armL"] = (60, 30, "open")
        else:
            P["xoff"] = 1500 * ease_out_cubic((u - 0.45) / 0.55)
            P["legL"] = 28 * math.sin(t * 16)
            P["legR"] = -28 * math.sin(t * 16)
            P["armL"] = (40 + 20 * math.sin(t * 16), 40, "open")
            P["armR"] = (140, 26 + 26 * math.sin(t * 11), "open")
            P["yoff"] = -6 * abs(math.sin(t * 16))
    elif code == "shoot_run":  # 卡22：投篮手势后追球跑出画
        if u < 0.5:
            P["armL"] = (128, 60, "open")
            P["armR"] = (128, 60, "open")
            P["squash"] = 0.04 * math.sin(min(u / 0.5, 1) * math.pi)
        else:
            P["xoff"] = 1500 * ease_out_cubic((u - 0.5) / 0.5)
            P["legL"] = 28 * math.sin(t * 16)
            P["legR"] = -28 * math.sin(t * 16)
            P["armL"] = (40 + 20 * math.sin(t * 16), 40, "open")
            P["armR"] = (40 - 20 * math.sin(t * 16), 40, "open")
            P["yoff"] = -6 * abs(math.sin(t * 16))
    return P


# karaoke_points / frac_at 见 feuille.timeline（2026-10-04 从本文件与 scene_video 双份收敛为一处）


def openness_at(lines, t, seed=""):
    op = 0.0
    for line in lines:
        if t < line["start"] - 0.05 or t > line["start"] + line["dur"] + 0.2:
            continue
        for w in line["words"]:
            amp = 0.55 + 0.45 * rnd(f"{seed}:open:{w['w']}:{round(w['s'], 2)}")  # 种子命名空间（不变量⑦）
            if w["s"] <= t <= w["e"]:
                op = max(op, amp)
            elif w["e"] < t < w["e"] + 0.13:
                op = max(op, amp * (1 - (t - w["e"]) / 0.13))
            elif t < w["s"] < t + 0.05:
                op = max(op, amp * 0.7)
    return op
