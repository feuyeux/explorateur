#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""char_sheet.py — 人物形象体检台（28 人立绘大图 · 几何缺陷的落盘目检面）

为什么要有这个模块：`draw_character` 的几何缺陷（头/身脱节、臂躯露底缝、袖子遮嘴、
头饰压眉…）长在 **人物层** 上，成片里被气泡/文字带/名牌盖住、又压在 mp4 里，
靠肉眼看视频既慢又不可复现。本模块把人物层**单独**渲成大图落盘（build/chars/），
配套 `qa_shape.py` 把「形状 / 连接 / 图层」三类问题量化——对齐 render-handbook §4
的探针纪律：**新视觉特性 = 同时加探针**，采样窗口全部从 `face_geo()` 派生，永不手抄坐标。

**不新增绘制逻辑**：直接 `from usine.intro_cards import draw_character`，
所以形象图与成片逐像素同源（同一 ctx 字段集、同一 SS=2 超采样、同一 BOX 降采样）。

用法（uv 管理单一 .venv）：
  uv run usine-chars solo                 # 28 人全身立绘 + 头肩特写
  uv run usine-chars solo --only xiaoman  # 单人
  uv run usine-chars sheet                # 28 人总览图（一张 PNG）
  uv run usine-chars html                 # 可浏览索引页（点开看原图）
  uv run usine-chars solo --openness 0.9  # 张嘴态（验「袖子遮嘴」图层序）
  uv run usine-chars solo --pose wave     # 指定姿态码（走 pose_for）
"""
import argparse
import json
import sys
from pathlib import Path

from usine import ROOT
from usine.intro_cards import (SS, W, H, SCENES, draw_character, face_geo,
                                load_data, pose_for)

CHARS = ROOT / "build" / "chars"

# 体检台纸底：暖白纸感（人眼对「露底缝」最敏感的底色，且与人物中色调色板整体拉开）
PAPER = (246, 243, 236)
PAPER_EDGE = (226, 220, 208)
INK = (38, 34, 27)          # #26221B 近墨
ACCENT = (154, 111, 24)     # #9A6F18 青铜金
GRID = (232, 227, 216)

# 全身立绘的取景倍率：人物层在 1080x1920 里以 scale=1 占下 60%，
# scale=2 把人物顶到 hy−ry 之上、脚下留白，细节（头身比/臂长）看得清
FIG_SCALE = 2.0
FIG_SS = 2                  # 与成片同一超采样倍率（成片 SS=2）


# ---------- 字体（标签只写拉丁转写，避免一套字体背 8 个文字系统） ----------
def _font(size):
    from PIL import ImageFont
    for name in ("segoeui.ttf", "segoeuib.ttf", "msyh.ttc", "arial.ttf"):
        p = Path("C:/Windows/Fonts") / name
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def label_of(p):
    """名牌文本：拉丁名优先，退回 id（Han/Hangul/Arab/Hebr/Deva 原字在多数字体里缺字形）。"""
    nat = (p.get("name") or {}).get("latin") or ""
    return f'{nat} · {p["id"]}' if nat else p["id"]


def mood_of(p, card):
    """形象图的定格情绪：取该卡台词的情绪分支（数据不是发挥——与成片同源）。"""
    if card:
        for ln in card.get("lines", []):
            if ln.get("mood"):
                return ln["mood"]
    return "happy" if p["energy"] == "lively" else "neutral"


# ---------- 渲染 ----------


def figure(p, card, openness=0.0, blink=False, pose=None, scale=FIG_SCALE,
           ss=FIG_SS, mood=None, t=0.0):
    """渲一个人物层（RGBA，透明底），坐标系与成片完全一致。"""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ctx = dict(scale=scale, xoff=0.0, yoff=0.0, squash=0.0, xscale=1.0,
               head_dx=0, head_dy=0, brow_lift_extra=0,
               pose=dict(pose or {}), openness=openness, blink=blink,
               mood=mood or mood_of(p, card), ss=ss)
    draw_character(layer, ld, p, t, ctx)
    return layer.resize((W, H), Image.Resampling.BOX)   # 与成片同一降采样


def flatten(layer, bg=PAPER):
    """透明人物层压到纸底上：露底缝/漏色一眼可见（= 体检台的关键）。"""
    from PIL import Image
    base = Image.new("RGBA", layer.size, bg + (255,))
    base.alpha_composite(layer)
    return base.convert("RGB")


def crop_to_figure(img, layer, pad=12):
    """按人物层 alpha bbox 裁紧（背景/场景不参与取景，只看人）。"""
    box = layer.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        box = (0, 0, img.width, img.height)
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.width, x1 + pad), min(img.height, y1 + pad)
    return img.crop((x0, y0, x1, y1))


def head_shoulder_window(p):
    """头肩特写窗口——头/身/手臂三类缺陷的公共现场。

    窗口从 `face_geo` 派生：横向覆盖「头宽 + 两侧臂外缘」，纵向从头顶到肘部中段，
    内含下颌/颈/肩楔/肩点/臂根——坑⑪（肩点浮在躯干外）与坑⑮（袖子遮嘴）都发生在这里。
    """
    G = face_geo(p["movement"]["face"])
    cx = G["cx"]
    sh_y = G["torso_top"] + G["sh_dy"]
    half = G["rx"] + G["arm_w"] * 1.9
    y0 = G["hy"] - G["ry"] * 1.06
    y1 = sh_y + G["up_len"] * 1.15
    return (int(cx - half), int(y0), int(cx + half), int(y1))


def xform(win, scale, ss=1):
    """把 face_geo 空间的矩形过一遍 draw_character 的 T()（含 SS 超采样倍率）。

    形象图按 FIG_SCALE 放大取景，而几何窗口是 scale=1 的坐标系——
    不过变换就会取错地方（第一版就取到了滑板而不是头肩）。
    """
    G = None
    cx, ground = face_geo("round")["cx"], face_geo("round")["ground"]
    x0, y0, x1, y1 = win
    def T(x, y):
        return ((cx + scale * (x - cx)) * ss, (ground + scale * (y - ground)) * ss)
    a, b = T(x0, y0)
    c, d = T(x1, y1)
    return (int(min(a, c)), int(min(b, d)), int(max(a, c)), int(max(b, d)))


def silhouette(layer, ss=FIG_SS):
    """alpha 剪影：人物实心区纯黑，**空洞露白**。

    连接类缺陷（头/身脱节、臂躯露底缝）的判定只能看 alpha——
    压到纸底上时浅色服装与纸底撞色，肉眼会漏判（浅米裤 vs 暖白纸底）。
    """
    from PIL import Image
    small = layer.resize((W, H), Image.Resampling.BOX)
    a = small.getchannel("A").point(lambda v: 255 if v > 24 else 0)
    return Image.merge("RGB", (a, a, a))


def render_solo(only=None, openness=0.0, pose_code=None, blink=False):
    """28 人（或指定几人）的全身立绘 + 头肩特写 + alpha 剪影。"""
    from PIL import Image
    personas, doc = load_data()
    cards = {c["id"]: c for c in doc["cards"]}
    ids = list(personas) if not only else [i for i in only if i in personas]
    if not ids:
        print(f"[chars] no persona matched {only}", file=sys.stderr)
        return 1
    (CHARS / "detail").mkdir(parents=True, exist_ok=True)
    (CHARS / "sil").mkdir(parents=True, exist_ok=True)
    for pid in ids:
        p = personas[pid]
        card = cards.get(pid)
        pose = dict(pose_for(pose_code, 0.5, 0.0, p)) if pose_code else {}
        layer = figure(p, card, openness=openness, blink=blink, pose=pose)
        img = flatten(layer)
        img.save(CHARS / f"{pid}.png")
        sil = silhouette(layer)
        sil.save(CHARS / "sil" / f"{pid}.png")
        # 特写：头肩窗口（过 T() 变换）放大 2x —— 缺口/层序在这里看得见
        w = xform(head_shoulder_window(p), FIG_SCALE)
        detail = img.crop(w)
        detail.resize((detail.width * 2, detail.height * 2), Image.Resampling.NEAREST)\
               .save(CHARS / "detail" / f"{pid}.png")
        sil.crop(w).resize((w[2] - w[0], w[3] - w[1]), Image.Resampling.NEAREST)\
            .save(CHARS / "detail" / f"{pid}_sil.png")
    print(f"[chars] solo {len(ids)} -> {CHARS}/<id>.png · detail/ · sil/")
    return 0


# ---------- 总览 ----------


def render_sheet(only=None, openness=0.0, pose_code=None):
    """28 人总览：一张 PNG，一眼扫全员的剪影连续性与图层。"""
    from PIL import Image, ImageDraw
    personas, doc = load_data()
    cards = {c["id"]: c for c in doc["cards"]}
    ids = list(personas) if not only else [i for i in only if i in personas]
    cols = 7
    tw, th, lab = 340, 470, 62
    rows = (len(ids) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + lab)), PAPER)
    d = ImageDraw.Draw(sheet)
    fnt = _font(23)
    fnt_s = _font(19)
    for k, pid in enumerate(ids):
        p = personas[pid]
        pose = dict(pose_for(pose_code, 0.5, 0.0, p)) if pose_code else {}
        layer = figure(p, cards.get(pid), openness=openness, pose=pose)
        tile = crop_to_figure(flatten(layer), layer, pad=6)
        tile.thumbnail((tw - 12, th - 8), Image.Resampling.LANCZOS)
        cx0 = (k % cols) * tw
        cy0 = (k // cols) * (th + lab)
        d.rectangle([cx0 + 2, cy0 + 2, cx0 + tw - 2, cy0 + th - 2], outline=GRID)
        sheet.paste(tile, (cx0 + (tw - tile.width) // 2, cy0 + 6 + (th - 8 - tile.height) // 2))
        d.rectangle([cx0 + 2, cy0 + th, cx0 + tw - 2, cy0 + th + lab], fill=(250, 248, 243))
        d.line([cx0 + 2, cy0 + th, cx0 + tw - 2, cy0 + th], fill=GRID)
        d.text((cx0 + 10, cy0 + th + 8), label_of(p), font=fnt, fill=INK)
        d.text((cx0 + 10, cy0 + th + 33), f'{p["locale"]} · {p["movement"]["face"]}',
               font=fnt_s, fill=ACCENT)
    sheet.save(CHARS / "sheet.png")
    print(f"[chars] sheet {sheet.width}x{sheet.height} ({len(ids)} 人) -> {CHARS}/sheet.png")
    return 0


# ---------- 浏览器索引 ----------


def render_html(only=None, openness=0.0, pose_code=None):
    """轻色纸感索引页：页边距最小化，版面全让给人物（与教学页同款观感）。"""
    personas, doc = load_data()
    ids = list(personas) if not only else [i for i in only if i in personas]
    cells = []
    for pid in ids:
        p = personas[pid]
        cells.append(
            f'<figure><a href="{pid}.png"><img src="{pid}.png" loading="lazy" alt="{pid}"></a>'
            f'<figcaption><b>{label_of(p)}</b>'
            f'<span>{p["locale"]} · {p["movement"]["face"]} · {p["hairStyle"]}</span></figcaption></figure>'
        )
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>班底形象体检台 · {len(ids)} 人</title><style>
:root{{--paper:#F6F3EC;--card:#FCFAF6;--ink:#26221B;--gold:#9A6F18;--line:#E4DFD4}}
*{{box-sizing:border-box}}
body{{margin:0;padding:4px 6px;background:var(--paper);color:#26221B;
 font:14px/1.45 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}}
header{{padding:2px 4px 6px;border-bottom:1px solid var(--line);margin-bottom:4px}}
h1{{margin:0;font-size:17px;font-weight:650}}
header p{{margin:2px 0 0;color:var(--gold);font-size:12.5px}}
main{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);padding:3px}}
img{{width:100%;display:block;background:var(--paper)}}
figcaption{{display:flex;justify-content:space-between;gap:4px;padding:3px 2px 1px;font-size:11.5px}}
figcaption span{{color:var(--gold);font-size:10.5px;white-space:nowrap}}
a{{display:block}}
</style><header><h1>班底形象体检台</h1>
<p>几何单一事实源 face_geo() · 与成片同源渲染（SS={FIG_SS} BOX 降采样）· 点图看原图，特写在 detail/</p></header>
<main>{''.join(cells)}</main></html>"""
    (CHARS / "index.html").write_text(html, encoding="utf-8")
    print(f"[chars] html -> {CHARS}/index.html")
    return 0


# ---------- CLI ----------


def main(argv=None):
    ap = argparse.ArgumentParser(prog="usine-chars",
                                 description="人物形象体检台：28 人立绘大图 + 总览 + 索引页")
    ap.add_argument("cmd", choices=["solo", "sheet", "html", "all"], default="solo", nargs="?")
    ap.add_argument("--only", help="逗号分隔的人设 id")
    ap.add_argument("--openness", type=float, default=0.0, help="口型开度 0–1（验袖子遮嘴用 0.9）")
    ap.add_argument("--pose", help="姿态码（走 pose_for，如 wave/thumbs_up）")
    ap.add_argument("--blink", action="store_true", help="眨眼帧")
    a = ap.parse_args(argv)
    only = [s.strip() for s in a.only.split(",")] if a.only else None
    CHARS.mkdir(parents=True, exist_ok=True)
    rc = 0
    if a.cmd in ("solo", "all"):
        rc |= render_solo(only, a.openness, a.pose, a.blink)
    if a.cmd in ("sheet", "all"):
        rc |= render_sheet(only, a.openness, a.pose)
    if a.cmd in ("html", "all"):
        rc |= render_html(only, a.openness, a.pose)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
