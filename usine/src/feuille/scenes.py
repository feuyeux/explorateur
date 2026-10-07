# -*- coding: utf-8 -*-
"""scenes.py — 场景原语（⑥ 视频：背景装置的 Pillow 绘制）

搬运自 explorateur/src/usine/intro_cards.py 479–1019（场景原语全段，函数体逐字节
照搬，含全部坑注/准则注）：DrawScaled 超采样代理 / SS 全局超采样倍率 / prerender_bg
渐变背景与场景装配 / _sun / @scene 注册表（SCENES）与全部 s_* 场景函数
（62 个函数、65 个注册名——arch / lantern / boardn 三件双名注册）。

终态说明（丢了什么、为什么）：

- 本段自洽无路径耦合：prerender_bg(p, card) 只读 p["identity"] 与 card["scene"]，
  其余全靠参数注入；搬运零适配。
- 色表与画布基准来自 rig：SCENE（场景中性色）、W / H（语义画布 1080×1920）、
  mix / hexc 由 .rig 提供——不变量⑤（场景原语禁写字面 RGB）与不变量①（坐标锚定
  画布基准）的判据已在源码注释里，此处不重复。
- 不搬：无。intro 卡片编排（进度条 / 文字带 / 名牌粘贴等）在 render_card 里，
  随 feuille.render 的不搬清单处理。
"""

from .rig import H, SCENE, W, hexc, mix


# ---- 场景原语 ----

class DrawScaled:
    """坐标等比缩放的 ImageDraw 代理：1x 语义坐标 → kx 画布，
    配合 LANCZOS 缩回实现全形状抗锯齿（超采样）。"""

    def __init__(self, base, k):
        self._b, self._k = base, k

    def _box(self, bbox):
        return [v * self._k for v in bbox]

    def ellipse(self, bbox, **kw):
        self._b.ellipse(self._box(bbox), **kw)

    def rectangle(self, bbox, **kw):
        self._b.rectangle(self._box(bbox), **kw)

    def rounded_rectangle(self, bbox, rad, **kw):
        self._b.rounded_rectangle(self._box(bbox), max(2, rad * self._k), **kw)

    def line(self, pts, width=1, **kw):
        if pts and isinstance(pts[0], (int, float)):  # PIL 也接受扁平坐标序列
            pts = list(zip(pts[::2], pts[1::2]))
        self._b.line([(x * self._k, y * self._k) for x, y in pts],
                     width=max(1, int(width * self._k)), **kw)

    def arc(self, bbox, a0, a1, width=1, **kw):
        self._b.arc(self._box(bbox), a0, a1, width=max(1, int(width * self._k)), **kw)

    def pieslice(self, bbox, a0, a1, **kw):
        self._b.pieslice(self._box(bbox), a0, a1, **kw)

    def chord(self, bbox, a0, a1, **kw):
        self._b.chord(self._box(bbox), a0, a1, **kw)

    def polygon(self, pts, **kw):
        self._b.polygon([(x * self._k, y * self._k) for x, y in pts], **kw)


SS = 2  # 全局超采样倍率（人物层/场景层）


def prerender_bg(p, card):
    import numpy as np
    from PIL import Image, ImageDraw
    ident = hexc(p["identity"])
    top = mix((246, 243, 238), ident, 0.10)
    bottom = mix((236, 232, 224), ident, 0.20)
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):
        arr[y, :, :] = mix(top, bottom, y / (H - 1))
    img = Image.fromarray(arr).resize((W * SS, H * SS), Image.BILINEAR)
    d = DrawScaled(ImageDraw.Draw(img), SS)
    ground = mix((230, 226, 216), ident, 0.18)
    d.rectangle([0, 1700, W, H], fill=ground)
    d.ellipse([310, 1682, 770, 1758], fill=mix(ground, (50, 45, 40), 0.14))  # 站位阴影
    pal = {
        "ink": (188, 182, 170),
        "soft": mix((214, 208, 196), ident, 0.22),
        "soft2": mix((196, 189, 176), ident, 0.34),
        "tint": mix((255, 255, 255), ident, 0.30),
        "tint2": mix((255, 255, 255), ident, 0.16),
        "accent": ident,
        "paper": (245, 241, 232),
    }
    for name in card.get("scene", []):
        fn = SCENES.get(name)
        if fn:
            fn(d, pal)
    return img.resize((W, H), Image.LANCZOS)


def _sun(d, pal, x=810, y=520, r=95, color=None):
    d.ellipse([x - r, y - r, x + r, y + r], fill=color or pal["tint"])


SCENES = {}


def scene(name):
    def deco(fn):
        SCENES[name] = fn
        return fn
    return deco


@scene("sun")
def s_sun(d, pal):
    _sun(d, pal, x=780, y=480, color=pal["tint"])
    for i, r in enumerate((46, 66, 86)):
        d.arc([780 - r - 40, 480 - r - 40, 780 + r + 40, 480 + r + 40], 200, 340,
              fill=mix(pal["tint"], SCENE["white"], 0.4 - i * 0.15), width=6)


@scene("sun_low")
def s_sunlow(d, pal):
    _sun(d, pal, x=820, y=1020, r=120, color=mix(SCENE["sun1"], pal["accent"], 0.25))


@scene("sky_dusk")
def s_dusk(d, pal):
    for i in range(5):
        d.ellipse([120 + i * 190, 380 + (i % 2) * 40, 168 + i * 190, 428 + (i % 2) * 40],
                  fill=mix(SCENE["sun2"], pal["accent"], 0.18))


@scene("sky_sunset")
def s_sunset(d, pal):
    d.ellipse([700, 940, 1060, 1300], fill=mix(SCENE["sun3"], pal["accent"], 0.22))
    d.line([0, 1010, 1080, 1010], fill=mix(SCENE["white"], pal["accent"], 0.30), width=8)


@scene("mountains")
def s_mountains(d, pal):
    d.polygon([(0, 1500), (260, 1060), (520, 1500)], fill=pal["soft2"])
    d.polygon([(300, 1500), (620, 980), (940, 1500)], fill=pal["soft"])
    d.polygon([(556, 1078), (620, 980), (684, 1078)], fill=SCENE["snow"])


@scene("gate_arch")
@scene("arch")
def s_arch(d, pal):
    d.rounded_rectangle([140, 700, 220, 1500], 30, fill=pal["soft2"])
    d.rounded_rectangle([860, 700, 940, 1500], 30, fill=pal["soft2"])
    d.arc([140, 560, 940, 1120], 180, 360, fill=pal["soft2"], width=70)


@scene("flowers")
def s_flowers(d, pal):
    for x, y, c in [(180, 1560, pal["accent"]), (250, 1620, SCENE["lantern"]), (900, 1580, pal["accent"]),
                    (840, 1640, SCENE["white"])]:
        d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=c)
        d.line([x, y + 16, x, y + 52], fill=SCENE["stem"], width=6)


@scene("studio_set")
def s_studio_set(d, pal):
    """演播室景（锵锵三人行那种围坐圆桌的棚）：两侧对称弧形墙板 + 落地灯 + 圆地毯。

    **对称是这个景的全部意义**——镜头正对圆桌，画面左右必须镜像；偏心一边，
    整张画就读成「这课是在别的地方顺手拍的」。左右两个方向用同一个循环画，
    以后加装饰也只能照这个循环加，否则对称一破这里就废了。

    墙板只能占**背屏两侧**：装置背屏画在 y≈900-1100，墙板画在 y≈980-1520 时
    两者重叠，成片里背屏像浮在半空、墙板被切成两截露在下面。
    """
    ink = pal["ink"]
    for s in (-1, 1):                                   # 对称墙板：上缘与背屏齐平，下缘到地毯
        x0, x1 = sorted((540 + s * 300, 540 + s * 580))
        d.rounded_rectangle([x0, 1000, x1, 1560], 40, fill=pal["soft"], outline=ink, width=5)
    for s in (-1, 1):                                   # 落地灯：灯罩要小，杆要深
        # 灯罩画大了就是一只飘在背屏旁的气球——早期版本 120px 直径就是这么
        # 变成气球的；灯杆不加深的话，整组读起来像没画完。
        # **灯杆必须落在背屏左右两侧之外**（|dx| > 340）：压在背屏正下方时，
        # 背屏一画完就把杆的上半截盖住，只剩两截从屏底垂下来，读成「背屏被吊着」。
        lx = 540 + s * 498
        d.line([lx, 1150, lx, 1664], fill=mix(pal["soft2"], (90, 84, 74), 0.35), width=9)
        d.ellipse([lx - 26, 1092, lx + 26, 1144],
                  fill=mix(SCENE["glow"], pal["accent"], 0.30))
    d.ellipse([236, 1568, 844, 1792], fill=pal["soft2"])   # 圆地毯


@scene("lamp")
def s_lamp(d, pal):
    d.line([200, 980, 200, 1500], fill=pal["soft2"], width=14)
    d.ellipse([160, 920, 240, 1000], fill=mix(SCENE["glow"], pal["accent"], 0.3))


@scene("bus_sign")
def s_bus(d, pal):
    d.rounded_rectangle([830, 1180, 920, 1500], 16, fill=pal["soft2"])
    d.rounded_rectangle([780, 1060, 970, 1200], 16, fill=pal["accent"], outline=pal["ink"], width=6)
    d.rectangle([800, 1090, 950, 1114], fill=SCENE["white"])
    d.rectangle([800, 1130, 920, 1154], fill=SCENE["white"])


@scene("bench")
def s_bench(d, pal):
    d.rounded_rectangle([740, 1460, 1000, 1500], 14, fill=pal["soft2"])
    d.rounded_rectangle([740, 1360, 1000, 1396], 14, fill=pal["soft2"])
    d.rectangle([770, 1400, 786, 1560], fill=pal["soft2"])
    d.rectangle([954, 1400, 970, 1560], fill=pal["soft2"])


@scene("awning")
def s_awning(d, pal):
    d.rounded_rectangle([60, 700, 560, 1240], 30, fill=pal["tint2"], outline=pal["ink"], width=6)
    for i in range(6):
        c = pal["accent"] if i % 2 == 0 else SCENE["white"]
        d.polygon([(60 + i * 84, 700), (60 + (i + 1) * 84, 700), (60 + (i + 1) * 84 - 6, 780), (60 + i * 84 - 6, 780)], fill=c)


@scene("counter")
def s_counter(d, pal):
    d.rounded_rectangle([120, 1300, 480, 1560], 20, fill=pal["soft2"])
    d.rectangle([120, 1300, 480, 1330], fill=pal["soft"])


@scene("steam")
def s_steam(d, pal):
    for x, y0 in [(240, 1120), (330, 1080)]:
        d.arc([x - 30, y0, x + 30, y0 + 90], 180, 360, fill=SCENE["white"], width=10)
        d.arc([x - 30, y0 - 70, x + 30, y0 + 20], 0, 180, fill=SCENE["white"], width=10)


@scene("windows_big")
def s_windows(d, pal):
    d.rectangle([80, 640, 520, 1220], fill=pal["tint2"], outline=pal["ink"], width=6)
    d.line([300, 640, 300, 1220], fill=SCENE["lamp"], width=6)
    d.line([80, 930, 520, 930], fill=SCENE["lamp"], width=6)


@scene("board_timetable")
def s_board(d, pal):
    d.rounded_rectangle([640, 620, 1040, 1000], 24, fill=SCENE["night_blue"], outline=pal["ink"], width=6)
    for r in range(4):
        d.rectangle([670, 660 + r * 80, 940, 700 + r * 80], fill=mix(SCENE["night_blue"], pal["accent"], 0.5))


@scene("luggage")
def s_luggage(d, pal):
    d.rounded_rectangle([880, 1380, 1040, 1580], 24, fill=pal["accent"], outline=pal["ink"], width=6)
    d.rounded_rectangle([840, 1420, 900, 1580], 18, fill=pal["soft2"], outline=pal["ink"], width=6)


@scene("cobble_arcs")
def s_cobble(d, pal):
    for r in (190, 320, 450):
        d.arc([540 - r, 1700 - r // 2, 540 + r, 1700 + r // 2], 180, 360, fill=pal["soft"], width=10)


@scene("fountain")
def s_fountain(d, pal):
    d.ellipse([120, 1360, 460, 1500], fill=mix(SCENE["sky"], pal["accent"], 0.25))
    d.ellipse([200, 1390, 380, 1470], fill=SCENE["white"])


@scene("pigeons")
def s_pigeons(d, pal):
    for x, y in [(200, 1620), (280, 1660), (860, 1600)]:
        d.ellipse([x - 18, y - 12, x + 18, y + 12], fill=pal["soft2"])
        d.ellipse([x + 10, y - 22, x + 30, y - 4], fill=pal["soft2"])


@scene("pigeons_on_wire")
def s_powire(d, pal):
    d.line([0, 700, 1080, 760], fill=SCENE["lamp"], width=5)
    for x in (260, 460, 700):
        y = 700 + (760 - 700) * x / 1080
        d.ellipse([x - 14, y - 26, x + 14, y + 2], fill=pal["soft2"])


@scene("shopfront")
def s_shopfront(d, pal):
    d.rounded_rectangle([620, 760, 1020, 1500], 26, fill=pal["tint2"], outline=pal["ink"], width=6)
    d.rectangle([660, 900, 980, 1200], fill=mix(SCENE["glow2"], pal["accent"], 0.25))


@scene("books_stack")
def s_books(d, pal):
    for i, c in enumerate([pal["accent"], pal["soft2"], pal["soft"]]):
        d.rounded_rectangle([140, 1520 - i * 34, 360, 1550 - i * 34], 8, fill=c)


@scene("desk_lamp")
def s_desklamp(d, pal):
    d.rounded_rectangle([700, 1240, 1010, 1290], 16, fill=pal["soft2"])
    d.line([960, 1250, 900, 1060], fill=pal["soft2"], width=16)
    d.polygon([(830, 1060), (970, 1060), (940, 990), (860, 990)], fill=pal["accent"])


@scene("window")
def s_window(d, pal):
    d.rounded_rectangle([700, 620, 1000, 1060], 40, fill=mix(SCENE["sky2"], pal["accent"], 0.15),
                        outline=pal["ink"], width=6)
    d.line([850, 620, 850, 1060], fill=SCENE["lamp"], width=5)
    d.line([700, 840, 1000, 840], fill=SCENE["lamp"], width=5)


@scene("shelf")
def s_shelf(d, pal):
    for r in range(3):
        y = 980 + r * 160
        d.rectangle([80, y, 460, y + 16], fill=pal["soft2"])
        for b in range(4):
            c = [pal["accent"], pal["soft"], pal["soft2"]][(r + b) % 3]
            d.rounded_rectangle([100 + b * 90, y - 90, 168 + b * 90, y], 6, fill=c)


@scene("signpost")
def s_signpost(d, pal):
    d.line([840, 950, 840, 1520], fill=pal["soft2"], width=16)
    d.rounded_rectangle([760, 980, 1000, 1060], 12, fill=pal["accent"])
    d.polygon([(860, 1080), (1000, 1120), (860, 1160)], fill=pal["accent"])


@scene("trail")
def s_trail(d, pal):
    d.polygon([(0, 1920), (380, 1400), (760, 1920)], fill=pal["soft"])
    d.polygon([(540, 1920), (900, 1480), (1080, 1700), (1080, 1920)], fill=pal["soft2"])


@scene("awning_market")
def s_mawning(d, pal):
    for i in range(5):
        c = pal["accent"] if i % 2 == 0 else SCENE["white"]
        d.polygon([(620 + i * 90, 820), (620 + (i + 1) * 90, 820), (614 + (i + 1) * 90, 900), (614 + i * 90, 900)], fill=c)
    d.rectangle([620, 820, 1070, 838], fill=SCENE["lamp"])


@scene("crates")
def s_crates(d, pal):
    d.rounded_rectangle([130, 1360, 330, 1540], 14, fill=pal["soft2"], outline=pal["ink"], width=6)
    d.rounded_rectangle([200, 1210, 400, 1360], 14, fill=pal["soft"], outline=pal["ink"], width=6)


@scene("fruit_balls")
def s_fruit(d, pal):
    for x, y, c in [(180, 1300, SCENE["flower"]), (240, 1330, SCENE["blossom"]), (300, 1300, pal["accent"])]:
        d.ellipse([x - 34, y - 34, x + 34, y + 34], fill=c)


@scene("umbrella")
def s_umbrella(d, pal):
    d.chord([700, 760, 1080, 1100], 180, 360, fill=pal["accent"])
    d.line([890, 930, 890, 1400], fill=SCENE["lamp"], width=12)


@scene("table")
def s_table(d, pal):
    d.rounded_rectangle([700, 1420, 1000, 1470], 12, fill=pal["soft2"])
    d.rectangle([730, 1470, 750, 1620], fill=pal["soft2"])
    d.rectangle([950, 1470, 970, 1620], fill=pal["soft2"])
    d.ellipse([770, 1360, 830, 1420], fill=SCENE["white"])


@scene("plant")
def s_plant(d, pal):
    d.polygon([(180, 1600), (260, 1380), (340, 1600)], fill=mix(SCENE["grass2"], pal["accent"], 0.3))
    d.rounded_rectangle([200, 1600, 320, 1690], 14, fill=pal["soft2"])


@scene("arch_windows")
def s_archwin(d, pal):
    d.rounded_rectangle([90, 760, 250, 1200], 60, fill=pal["tint2"], outline=pal["ink"], width=6)
    d.rounded_rectangle([90, 1260, 250, 1560], 60, fill=pal["soft2"], outline=pal["ink"], width=6)


@scene("fence_low")
def s_fence(d, pal):
    for x in range(700, 1040, 80):
        d.rectangle([x, 1480, x + 22, 1620], fill=pal["soft2"])
    d.rectangle([700, 1520, 1020, 1544], fill=pal["soft2"])


@scene("tree")
def s_tree(d, pal):
    d.rectangle([880, 1250, 916, 1600], fill=SCENE["wood"])
    d.ellipse([770, 1000, 1030, 1300], fill=mix(SCENE["grass"], pal["accent"], 0.25))


@scene("domes")
def s_domes(d, pal):
    d.chord([120, 900, 400, 1240], 180, 360, fill=pal["accent"])
    d.chord([330, 960, 560, 1220], 180, 360, fill=pal["soft2"])
    d.rectangle([240, 1070, 280, 1100], fill=SCENE["white"])


@scene("water")
def s_water(d, pal):
    d.rectangle([0, 1480, 560, 1700], fill=mix(SCENE["sky3"], pal["accent"], 0.30))
    for y in (1540, 1620):
        d.arc([100, y, 300, y + 60], 180, 360, fill=SCENE["white"], width=8)


@scene("bunting")
def s_bunting(d, pal):
    d.line([0, 640, 1080, 700], fill=SCENE["lamp"], width=4)
    for i in range(9):
        x = 40 + i * 120
        y = 640 + (700 - 640) * x / 1080
        c = [pal["accent"], SCENE["lantern"], SCENE["white"]][i % 3]
        d.polygon([(x, y), (x + 56, y + 4), (x + 28, y + 64)], fill=c)


@scene("masts")
def s_masts(d, pal):
    for x in (180, 360):
        d.line([x, 940, x, 1480], fill=SCENE["lamp"], width=8)
        d.polygon([(x, 960), (x, 1200), (x - 90, 1120)], fill=SCENE["white"])


@scene("tree_shadow")
def s_tshadow(d, pal):
    d.ellipse([140, 800, 520, 1160], fill=mix(SCENE["grass"], pal["accent"], 0.20))
    d.arc([120, 1120, 540, 1420], 180, 360, fill=pal["soft"], width=12)


@scene("lantern")
@scene("lanterns")
def s_lantern(d, pal):
    d.rounded_rectangle([140, 700, 210, 830], 20, fill=pal["accent"])
    d.rectangle([150, 830, 200, 850], fill=SCENE["lamp"])
    d.rounded_rectangle([860, 730, 930, 860], 20, fill=mix(SCENE["peach2"], pal["accent"], 0.4))


@scene("pot_brass")
def s_pot(d, pal):
    d.chord([720, 1180, 1000, 1480], 180, 360, fill=mix(SCENE["wood2"], pal["accent"], 0.3))
    d.rectangle([840, 1140, 880, 1190], fill=SCENE["wood2"])


@scene("carpet")
def s_carpet(d, pal):
    d.rounded_rectangle([100, 1500, 420, 1620], 16, fill=mix(SCENE["sign"], pal["accent"], 0.4))
    d.rectangle([130, 1530, 390, 1590], fill=SCENE["white"])


@scene("brick_arches")
def s_bricks(d, pal):
    for i, x in enumerate((100, 330)):
        d.rounded_rectangle([x, 820, x + 200, 1420], 70, fill=pal["soft2"])
        d.rounded_rectangle([x + 40, 980, x + 160, 1420], 50, fill=pal["tint2"])


@scene("board_notice")
@scene("board")
def s_boardn(d, pal):
    d.rounded_rectangle([740, 1000, 1020, 1300], 18, fill=pal["paper"], outline=pal["ink"], width=6)
    for r in range(4):
        d.rectangle([770, 1050 + r * 60, 990, 1070 + r * 60], fill=pal["soft"])


@scene("palm")
def s_palm(d, pal):
    d.rectangle([170, 1150, 200, 1500], fill=SCENE["wood"])
    for dx, dy in [(-120, -60), (120, -60), (-80, -130), (80, -130), (0, -160)]:
        d.ellipse([185 + dx - 70, 1150 + dy - 26, 185 + dx + 70, 1150 + dy + 26],
                  fill=mix(SCENE["grass"], pal["accent"], 0.25))


@scene("mapwall")
def s_mapwall(d, pal):
    d.rectangle([700, 700, 1020, 1150], fill=pal["paper"], outline=pal["ink"], width=6)
    d.line([720, 780, 1000, 900], fill=pal["accent"], width=8)
    d.line([860, 760, 780, 1120], fill=pal["soft2"], width=8)
    d.ellipse([840, 880, 880, 920], fill=pal["accent"])


@scene("columns")
def s_columns(d, pal):
    for x in (110, 250):
        d.rectangle([x, 780, x + 60, 1420], fill=pal["tint2"], outline=pal["ink"], width=5)
        d.rectangle([x - 16, 740, x + 76, 790], fill=pal["soft2"])


@scene("lantern_row")
def s_lrow(d, pal):
    for i, x in enumerate((120, 320, 900)):
        d.line([x, 620, x, 700], fill=SCENE["lamp"], width=6)
        d.ellipse([x - 34, 700, x + 34, 810], fill=mix(SCENE["peach"], pal["accent"], 0.35 - i * 0.08))


@scene("wires")
def s_wires(d, pal):
    d.line([0, 620, 1080, 680], fill=SCENE["lamp"], width=5)
    d.line([0, 700, 1080, 650], fill=SCENE["lamp"], width=4)


@scene("hoop")
def s_hoop(d, pal):
    d.rectangle([820, 900, 852, 1500], outline=pal["ink"], width=8)
    d.ellipse([740, 800, 940, 1000], outline=pal["ink"], width=14)
    d.line([740, 950, 940, 950], fill=SCENE["white"], width=10)


@scene("fence")
def s_fenceH(d, pal):
    for x in range(80, 480, 90):
        d.rectangle([x, 1180, x + 26, 1500], fill=SCENE["metal"])
    for y in (1240, 1380):
        d.rectangle([80, y, 460, y + 20], fill=SCENE["metal"])


@scene("skyline")
def s_skyline(d, pal):
    for x, w, h in [(60, 120, 300), (220, 90, 420), (740, 140, 360), (920, 100, 260)]:
        d.rectangle([x, 1500 - h, x + w, 1500], fill=pal["soft2"])
        d.rectangle([x + 20, 1500 - h + 30, x + 40, 1500 - h + 60], fill=SCENE["chalk"])


@scene("clothesline")
def s_cline(d, pal):
    d.line([60, 860, 520, 900], fill=SCENE["lamp"], width=5)
    for i, c in enumerate([SCENE["white"], pal["accent"], SCENE["lantern"]]):
        x = 120 + i * 130
        y = 860 + (900 - 860) * x / 520
        d.rounded_rectangle([x, y, x + 70, y + 90], 12, fill=c)


@scene("stairs")
def s_stairs(d, pal):
    for i in range(4):
        d.rectangle([680 + i * 60, 1660 - i * 90, 1080, 1680 - i * 90], fill=mix(pal["soft"], SCENE["white"], i * 0.12))


@scene("shrubs")
def s_shrubs(d, pal):
    for x, y in [(180, 1560), (300, 1600)]:
        d.ellipse([x - 60, y - 50, x + 60, y + 50], fill=mix(SCENE["grass"], pal["accent"], 0.2))


@scene("neon_sign")
def s_neon(d, pal):
    d.rounded_rectangle([720, 760, 1020, 940], 26, outline=mix(SCENE["cyan"], pal["accent"], 0.4), width=10)
    d.rectangle([780, 800, 960, 830], fill=mix(SCENE["cyan"], pal["accent"], 0.4))
    d.rectangle([780, 860, 900, 890], fill=mix(SCENE["pink"], pal["accent"], 0.4))


@scene("window_grid")
def s_wgrid(d, pal):
    for r in range(3):
        for c in range(2):
            x, y = 110 + c * 150, 820 + r * 180
            d.rounded_rectangle([x, y, x + 110, y + 130], 18, fill=SCENE["steam"], outline=pal["ink"], width=5)


@scene("stall")
def s_stall(d, pal):
    d.rounded_rectangle([640, 1280, 1020, 1500], 20, fill=pal["soft2"], outline=pal["ink"], width=6)
    d.rectangle([640, 1280, 1020, 1310], fill=pal["soft"])


@scene("steamers")
def s_steamers(d, pal):
    for i, x in enumerate((160, 260)):
        d.ellipse([x, 1280, x + 90, 1350], fill=pal["soft2"], outline=pal["ink"], width=5)
        for k in range(3):
            d.arc([x + 10 + k * 26, 1240, x + 36 + k * 26, 1290], 180, 360, fill=SCENE["white"], width=6)
