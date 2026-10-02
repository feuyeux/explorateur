#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_grid.py — 亮相卡画面质检（无视觉模型也能读图）

把帧降采样为色块网格，每个格子匹配到人物色板/界面色后输出单字符矩阵：
S=肤色 H=头发 T=上衣 B=裤裙 I=标识色 #(=文字带底 W=白 G=地面 ~=其他 .=浅背景
用法：python qa_grid.py frame.png [frame2.png ...]
"""
import sys

from PIL import Image

PALETTE = {
    "S": (245, 201, 162),   # skin 代表值（容差匹配）
    "H": (51, 46, 56),      # hair 代表值
    "T": (242, 237, 228),   # outfitTop 代表值
    "B": (74, 99, 152),     # outfitBottom 代表值
    "I": (216, 69, 59),     # identity 朱砂红
    "#": (35, 40, 63),      # 文字带底 #23283F
    "W": (255, 255, 255),
    "G": (228, 222, 210),   # 地面带
    ".": (244, 240, 234),   # 页面浅背景
}
TOL = 42
GRID_W, GRID_H = 36, 64


def classify(px):
    best, bd = "~", 1e9
    for ch, c in PALETTE.items():
        d = sum((a - b) ** 2 for a, b in zip(px[:3], c)) ** 0.5
        if d < bd:
            best, bd = ch, d
    return best if bd < TOL else "~"


def grid(path):
    im = Image.open(path).convert("RGB")
    cell_w, cell_h = im.width // GRID_W, im.height // GRID_H
    print(f"== {path} ({im.width}x{im.height}) ==")
    for gy in range(GRID_H):
        row = []
        for gx in range(GRID_W):
            x = gx * cell_w + cell_w // 2
            y = gy * cell_h + cell_h // 2
            row.append(classify(im.getpixel((x, y))))
        print("".join(row))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        grid(p)
