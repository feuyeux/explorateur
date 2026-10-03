#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_grid.py — 亮相卡画面质检（无视觉模型也能读图）

把帧降采样为色块网格，每个格子匹配到人物色板/界面色后输出单字符矩阵：
S=肤色 H=头发 T=上衣 B=裤裙 I=标识色 #(=文字带底 W=白 G=地面 ~=其他 .=浅背景
色板从 personas.json 按人设读取（单一事实源，永不手抄；不变量①/⑧）。
用法：uv run python -m usine.qa_grid [--persona xiaoman] frame.png [frame2.png ...]
"""
import argparse
import json
from pathlib import Path

from PIL import Image

from usine import ROOT

HERE = ROOT
personas = {p["id"]: p for p in json.load(open(HERE / "personas" / "personas.json", encoding="utf-8"))["personas"]}


def hexc(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def load_palette(pid):
    """S/H/T/B/I 从人设色板读取；#/W/G/. 为界面与场景代表值（非人物色）"""
    pal = personas[pid]["palette"]
    return {
        "S": hexc(pal["skin"]),
        "H": hexc(pal["hair"]),
        "T": hexc(pal["outfitTop"]),
        "B": hexc(pal["outfitBottom"]),
        "I": hexc(personas[pid]["identity"]),
        "#": (35, 40, 63),      # 文字带底 #23283F
        "W": (255, 255, 255),
        "G": (228, 222, 210),   # 地面带（场景代表值）
        ".": (244, 240, 234),   # 页面浅背景（场景代表值）
    }


TOL = 42
GRID_W, GRID_H = 36, 64


def classify(px, palette):
    best, bd = "~", 1e9
    for ch, c in palette.items():
        d = sum((a - b) ** 2 for a, b in zip(px[:3], c)) ** 0.5
        if d < bd:
            best, bd = ch, d
    return best if bd < TOL else "~"


def grid(path, palette):
    im = Image.open(path).convert("RGB")
    cell_w, cell_h = im.width // GRID_W, im.height // GRID_H
    print(f"== {path} ({im.width}x{im.height}) ==")
    for gy in range(GRID_H):
        row = []
        for gx in range(GRID_W):
            x = gx * cell_w + cell_w // 2
            y = gy * cell_h + cell_h // 2
            row.append(classify(im.getpixel((x, y)), palette))
        print("".join(row))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="xiaoman", help="色板人设 id（默认 xiaoman）")
    ap.add_argument("frames", nargs="+")
    args = ap.parse_args()
    pal = load_palette(args.persona)
    for p in args.frames:
        grid(p, pal)
