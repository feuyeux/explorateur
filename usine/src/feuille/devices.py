#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""devices.py — 装置外框样式注册表（②③ 校验层的判据源 + ⑥ 渲染线的外框画法）

LAST_WELL_RGB（draw_device 铺下的井底实色，浅色 chip 判对比用）/
device_of · well_color · chip_color（装置规格读取 + chip 两型契约）/
scene_pal（场景中性色 pal 约定，ink 为道具描边唯一色）/
DEVICE_STYLES 注册表 + device_style 装饰器 + dv_* 外框画法 + GROUND_Y 地面线 +
draw_device——装置是数据不是代码：加样式 = 加一个装饰函数（现 16 样式）。

本模块只画外框与井底色；井内 token 的逐帧填充层属场景渲染管线。
井位几何由调用方算好经 cells 传入，本模块不持井位常量；RTL 名单在剧本
数据里，由场景线持有。

使用契约：
- **校验层只取键集**：scene_schema / scene_draft / lesson 判「装置 style 合法」的唯一
  事实源是 `set(DEVICE_STYLES)`，不抄第二份名单（纪律 7：手抄名单必腐烂，
  造出「声明合法但渲不出来」的坑）。
- **chip 两型契约**：以 `#` 开头 = 色片（须 #RRGGBB，`chip_color()` 返回 RGB）；
  其余非空字符串 = 字牌（`chip_color()` 返回 None，走文字层贴图）。
  parse 落库后 `"1"` 与 `1` 不可区分——引号只是书写习惯，不是判据。
- **渲染线调用**：`scene_pal(ident_a, ident_b)` 造 pal → `draw_device(d, device, cells, pal)`
  画外框与空井（井内 token 由逐帧填充层压在井底色之上）。
"""
import math

from .rig import hexc, mix

# ---------------------------------------------------------------- 井底实色（跨调用副作用）
LAST_WELL_RGB = None      # 上一轮 draw_device 铺下的井底实色（浅色 chip 判对比用）


def device_of(loc):
    """该语种的舞台装置规格（剧本 §0.2）；缺行 = 纯对话无装置。"""
    return (loc.get("prop") or {}).get("device")


def well_color(device, pal):
    """空井底色：§0.2 `well` 显式给色则用之，否则由场景中性色推导
    （浅色 token 落在同色底上会看不见——手册场景线配方）。"""
    w = (device or {}).get("well") or ""
    return hexc(w) if w.startswith("#") else mix(pal["soft"], (255, 255, 255), 0.55)


def chip_color(chip):
    """教学 token chip 两型：`#hex` 色片 → RGB；`"文本"` 字牌 → None（走文字层贴图）。"""
    return hexc(chip) if isinstance(chip, str) and chip.startswith("#") else None


def scene_pal(ident_a, ident_b):
    """场景中性色：与 prerender_bg 同族的 pal 约定（ink 为道具描边唯一色——不变量⑤）。"""
    ident = mix(ident_a, ident_b, 0.5)
    return {
        "ink": (150, 144, 134),
        "soft": mix((214, 208, 196), ident, 0.20),
        "soft2": mix((190, 183, 170), ident, 0.30),
        "tint": mix((255, 255, 255), ident, 0.30),
        "tint2": mix((255, 255, 255), ident, 0.16),
        "accent": ident,
        "paper": (245, 241, 232),
    }


# 装置外框样式注册表（与 scenes.SCENES 的 `@scene` 同构）。
# 此前是 `draw_device` 里一条 15 分支 if/elif 链 + 一个裸元组闭集：加一种装置样式必须
# 改函数体，改名/漏改闭集则等到渲染时才报错。注册后「有哪些样式」由装饰器自己声明，
# 装置是数据不是代码这条原则在场景线也成立。
DEVICE_STYLES = {}

# 装置样式的「地面线」：立柱/底座类装置撑到这里。`None` = 不画落地支撑（封面用——
# 封面没有人物也没有地面，立柱只会变成两根悬空竖线）。成片恒为 1700，既有课不变。
GROUND_Y = 1700


def device_style(name):
    def deco(fn):
        DEVICE_STYLES[name] = fn
        return fn
    return deco


# 装置几何（井宽/井高/井形/空井色）全部由剧本 §0.2 装置规格表给定（parse_scene.py 落 data），
# 注册函数只负责**外框画法**：井位/井形/空井色都不在这里（井内 token 由逐帧填充层画）。
# box = (x0, y0, x1, y1) 由 draw_device 按 cells 算好后传入。


@device_style("palette")                                     # 美术教室·调色盘
def dv_palette(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0, y0, x1, y1], 40, fill=pal["soft2"], outline=pal["ink"], width=5)


@device_style("chalkboard")                                  # 咖啡馆·小黑板
def dv_chalkboard(d, cells, box, pal):
    x0, y0, x1, y1 = box
    ink = pal["ink"]
    d.rounded_rectangle([x0, y0 - 6, x1, y1 + 10], 18, fill=(58, 66, 62), outline=ink, width=6)
    d.rectangle([x0 - 10, y1 + 10, x1 + 10, y1 + 30], fill=(146, 116, 82), outline=ink, width=4)


@device_style("bookspine")                                   # 书店·橱窗书脊
def dv_bookspine(d, cells, box, pal):
    x0, y0, x1, y1 = box
    ink = pal["ink"]
    d.rectangle([x0, y0 - 10, x1, y0 + 14], fill=(132, 100, 72), outline=ink, width=4)
    d.rectangle([x0 - 8, y1, x1 + 8, y1 + 22], fill=(132, 100, 72), outline=ink, width=4)


@device_style("signpost")                                    # 徒步·指路牌柱
def dv_signpost(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.rectangle([(x0 + x1) / 2 - 16, y0, (x0 + x1) / 2 + 16, y1 + 54], fill=(140, 115, 90),
                outline=pal["ink"], width=4)


@device_style("fruit_basket")                                # 果摊·果筐
def dv_fruit_basket(d, cells, box, pal):
    ink = pal["ink"]
    for c in cells:
        d.polygon([(c[0] - 4, c[1] + 6), (c[2] + 4, c[1] + 6), (c[2] - 6, c[3] + 16),
                   (c[0] + 6, c[3] + 16)], fill=(178, 138, 92), outline=ink, width=4)


@device_style("chalk_stone")                                 # 庭院·石板粉笔
def dv_chalk_stone(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.rectangle([x0 - 40, y1 + 4, x1 + 40, y1 + 30], fill=pal["soft2"], outline=pal["ink"], width=4)


@device_style("doorframe")                                   # 港口·漆色门框
def dv_doorframe(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.rectangle([x0 - 16, y0 - 14, x1 + 16, y1 + 12], fill=pal["soft2"], outline=pal["ink"], width=5)


@device_style("lanterns")                                    # 咖啡座·灯笼
def dv_lanterns(d, cells, box, pal):
    x0, y0, x1, y1 = box
    ink = pal["ink"]
    d.line([(x0, y0 - 30), (x1, y0 - 30)], width=6, fill=ink)
    for c in cells:
        d.line([((c[0] + c[2]) / 2, y0 - 30), ((c[0] + c[2]) / 2, c[1] - 2)], width=3, fill=ink)


@device_style("rangoli")                                     # 走廊·rangoli
def dv_rangoli(d, cells, box, pal):
    for c in cells:
        for k in range(8):
            a = k * math.pi / 4
            d.line([((c[0] + c[2]) / 2 + 16 * math.cos(a), (c[1] + c[3]) / 2 + 16 * math.sin(a)),
                    ((c[0] + c[2]) / 2 + 30 * math.cos(a), (c[1] + c[3]) / 2 + 30 * math.sin(a))],
                   width=4, fill=pal["soft2"])


@device_style("traffic_lamp")                                # 商店街·街灯
def dv_traffic_lamp(d, cells, box, pal):
    x0, y0, x1, y1 = box
    ink = pal["ink"]
    d.rectangle([x0 - 20, y1 + 6, x1 + 20, y1 + 22], fill=pal["soft2"], outline=ink, width=4)
    for c in cells:
        d.line([((c[0] + c[2]) / 2, c[3]), ((c[0] + c[2]) / 2, y1 + 8)], width=6, fill=ink)


@device_style("cone")                                        # 街球场·训练锥
def dv_cone(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.rectangle([x0 - 30, y1 + 2, x1 + 30, y1 + 20], fill=pal["soft"], outline=pal["ink"], width=4)


@device_style("gelato")                                      # 广场·gelato 柜
def dv_gelato(d, cells, box, pal):
    x0, y0, x1, y1 = box
    ink = pal["ink"]
    d.rounded_rectangle([x0 - 30, y0 - 6, x1 + 30, y1 + 26], 22, fill=pal["paper"],
                        outline=ink, width=5)
    d.line([(x0 - 20, y0 + 6), (x1 + 20, y0 + 6)], width=5, fill=pal["soft2"])


@device_style("dyed_cloth")                                  # 天台·晾绳染布
def dv_dyed_cloth(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.line([(x0 - 60, y0 - 24), (x1 + 60, y0 - 24)], width=6, fill=pal["ink"])


@device_style("neon")                                        # 街市·neon 招牌
def dv_neon(d, cells, box, pal):
    x0, y0, x1, y1 = box
    d.rectangle([x0 - 24, y1 + 2, x1 + 24, y1 + 24], fill=(64, 58, 66), outline=pal["ink"], width=4)


@device_style("panel")                                     # 演播室·背屏
def dv_panel(d, cells, box, pal):
    """人物身后的一块宽背屏：落地底座 + 外框 + 一层比井底更亮的屏面。

    屏面画在**井底色铺好之前**——屏面被井盖住才是「卡片贴在屏上」，
    反过来就成了「屏贴在卡片后面」。

    **背屏必须有落地底座**：只画屏框时它悬在半空，画面上没有任何东西解释它
    为什么待在那儿，墙板的边线又正好从屏底两侧垂下来，成片读成「屏被吊在半空」。
    两条立柱把屏撑到地面，墙板边线被立柱挡住，悬空感消失。
    """
    x0, y0, x1, y1 = box
    # 立柱落在**屏框外缘之外**：放在框内（x0-6 / x1-18）时，柱身正好从三个人的
    # 身体中间穿过去，成片是三根柱子把人隔成三段。屏框本身已经画到 x0-34/x1+34，
    # 柱心必须再外推 30 以上，才落在屏框轮廓外侧的空墙上。
    # `GROUND_Y=None` 时不画立柱：立柱的作用是「把屏撑到**成片的地面**」，
    # 封面既没有人物也没有地面，画出来就是两根悬空的竖线（实测如此）。
    if GROUND_Y is not None:
        for lx in (x0 - 62, x1 + 14):                    # 落地立柱：屏宽内缩，两侧各一根
            d.rectangle([lx, y1 + 34, lx + 24, GROUND_Y], fill=pal["soft2"])
    d.rounded_rectangle([x0 - 34, y0 - 30, x1 + 34, y1 + 34], 26,
                        fill=pal["soft2"], outline=pal["ink"], width=6)
    d.rounded_rectangle([x0 - 14, y0 - 10, x1 + 14, y1 + 10], 18, fill=pal["tint"])


@device_style("tray")                                        # 裸托盘·只画井（默认值）
def dv_tray(d, cells, box, pal):
    """故意不画外框：纯对话场景的默认样式，井由下方 well 铺底。"""
    return None


def draw_device(d, device, cells, pal):
    """装置外框（井内 token 由逐帧填充层画）：style 决定外框画法，井位/井形/空井色来自
    剧本 §0.2。§1.2 原则4「舞台原生」：每语种独立装置，不共用布景。"""
    kind = (device or {}).get("style") or "tray"
    fn = DEVICE_STYLES.get(kind)
    if fn is None:
        raise ValueError(f"未知装置 style：{kind}（可用 {sorted(DEVICE_STYLES)}）")
    box = (min(c[0] for c in cells) - 26, min(c[1] for c in cells) - 26,
           max(c[2] for c in cells) + 26, max(c[3] for c in cells) + 26)
    x0, y0, x1, y1 = box
    fn(d, cells, box, pal)

    # 空井：先铺底色，逐帧 token 填充压在其上——白/浅色 chip 才有对比
    well = well_color(device, pal)
    # 记下「token 点亮后紧贴在它背后的那层实色」：浅色 chip 靠它决定要不要加深边。
    # 这里取的是**井底色**而不是屏面色——井铺在屏面之上，chip 落在井里，
    # 观众看到 chip 的直接背景是井底。取错一层，判据就量不到观众看到的东西。
    global LAST_WELL_RGB
    LAST_WELL_RGB = well
    for c in cells:
        if c[4] == "circle":
            d.ellipse(list(c[:4]), fill=well)
        elif c[4] == "poly":
            d.polygon([((c[0] + c[2]) / 2, c[1]), (c[0], c[3]), (c[2], c[3])], fill=well)
        elif c[4] == "rect":
            d.rectangle(list(c[:4]), fill=well)
        else:
            d.rounded_rectangle(list(c[:4]), 18, fill=well)
    return box
