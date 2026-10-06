#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_covers.py — 封面机制的反向验证

第 0 条好数据放行：五个平台规格各出一张演示封面（文字落在安全区内），
尺寸/底色/命名/展示裁切全部正确。反向各防一种真实退化：

- 尺寸不符 → check 必须报（错版上传平台会二次裁切，画面/文字全乱）
- 底色不符 → check 必须报（外圈众数取样——平均值会被照片出血带偏）
- **文字放错安全区 → display_crop 的预览里墨迹消失**（两次学费的教训
  做成可执行判据：小红书 y240 带、B 站 x240 带的文字发出去就被切）
- 对照图 sheet 可产出（人眼判定的载体）

真机（有浏览器）才渲演示封面；缺浏览器时渲字相关行如实 [SKIP]，
纯函数行（规格表/命名/裁切几何/check）仍然全跑。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image

from feuille import covers, platform as pt, textlayer    # noqa: E402


def demo_html(w, h, bg, text_y, text="一叶知秋 · 演示", ink="#111111"):
    """演示版式：纯色底 + 一行字，字块的纵坐标由调用方控制（安全区实验用）。"""
    return textlayer.page(
        w, h,
        f'<div style="position:absolute;left:0;right:0;top:{text_y}px;'
        f'text-align:center;font-size:64px;font-weight:600;color:{ink}">'
        f'{text}</div>', bg=bg)


def ink_count(img, bg) -> int:
    """纯色底演示封面里的墨迹像素数（生产照片底图不适用——人眼看 sheet）。"""
    arr = np.asarray(img.convert("RGB")).astype(int)
    bg_rgb = np.array(tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5)))
    return int((np.abs(arr - bg_rgb).max(axis=2) > 60).sum())


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-covers-")
    d = pathlib.Path(tmp.name)

    # ---- 0. 好数据放行：规格表 / 命名 / 裁切几何（纯函数，任何机器可跑）----
    rows.append((covers.SPECS["xiaohongshu"]["safe"] == (0, 240, 1080, 1680)
                 and covers.SPECS["bilibili"]["safe"] == (240, 0, 1680, 1080)
                 and covers.SPECS["douyin34"]["safe"] is None,
                 "展示裁切框正确（小红书 3:4 y240–1680 / B 站 4:3 x240–1680 / 抖音3:4 无裁切）"))
    rows.append((covers.filename("中文", "douyin34") == "中文_douyin34_1080x1440.png",
                 f"命名口径（{covers.filename('中文', 'douyin34')}）"))

    # 合成夹具：纯色 PNG 直接 PIL 画（不依赖浏览器）——check/display_crop 可先全跑
    def solid(path, w, h, bg):
        Image.new("RGB", (w, h), tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))).save(path)

    good = d / "good_xhs.png"
    solid(good, 1080, 1920, "#FFFFFF")
    rows.append((covers.check(good, "xiaohongshu") == [],
                 "好数据：白底 1080×1920 过 xiaohongshu 检查"))

    # ---- 1. 反向：尺寸错 / 底色错 ----
    wrong_size = d / "wrong_size.png"
    solid(wrong_size, 1080, 1920, "#000000")
    probs = covers.check(wrong_size, "douyin34")
    rows.append((any("尺寸" in s for s in probs),
                 f"1080×1920 传 douyin34 规格 → check 报尺寸（{probs[0][:42]}…）"))
    wrong_bg = d / "wrong_bg.png"
    solid(wrong_bg, 1080, 1440, "#FFFFFF")
    probs = covers.check(wrong_bg, "douyin34")
    rows.append((any("底色" in s for s in probs),
                 f"白底传抖音黑底规格 → check 报底色（众数取样 {probs[0][:42]}…）"))

    # ---- 2. 展示裁切：文字进/出安全区（两次学费的可执行判据）----
    if pt.browser() is None:
        rows.append((True, "[SKIP] 演示封面渲字未验（无 Chromium 内核浏览器）"))
        return rows
    for key, text_y, expect_survive in (
            ("xiaohongshu", 100, False),   # y=100 在 240 裁切带内 → 发出去就没了
            ("xiaohongshu", 900, True),    # y=900 在安全区 y240–1680 内
            ("bilibili", 0, True)):
        s = covers.SPECS[key]
        ink = "#14171E" if key == "xiaohongshu" else "#FFFFFF"
        png = d / f"demo_{key}_{text_y}.png"
        covers.make(key, demo_html(s["w"], s["h"], s["bg"], text_y, ink=ink), png,
                    workdir=d / "html")
        orig_ink = ink_count(Image.open(png), s["bg"])
        prev = covers.display_crop(png, key)
        prev_ink = ink_count(prev, s["bg"])
        if expect_survive:
            rows.append((prev_ink >= orig_ink * 0.8,
                         f"{key} 文字 y={text_y} 在安全区 → 展示裁切后保留"
                         f"（墨 {orig_ink}→{prev_ink}）"))
        else:
            rows.append((prev_ink <= orig_ink * 0.2,
                         f"{key} 文字 y={text_y} 落在裁切带 → **预览里墨迹消失**"
                         f"（墨 {orig_ink}→{prev_ink}——这正是小红书标签整行被切的事故）"))

    # ---- 3. 对照图 sheet（真实用法：拼的是展示裁切后的预览）----
    prev1, prev2 = d / "prev_xhs.png", d / "prev_bili.png"
    covers.display_crop(d / "demo_xiaohongshu_900.png", "xiaohongshu").save(prev1)
    covers.display_crop(d / "demo_bilibili_0.png", "bilibili").save(prev2)
    out = covers.sheet([prev1, prev2], d / "sheet.png")
    with Image.open(out) as im:
        h_expect = 1440 + 1080 + 2          # xhs 预览 3:4 + bili 预览 4:3 + 间隔
        w_expect = 1440                       # 宽 = 最宽预览（1080×1440 与 1440×1080）
        rows.append((im.size == (w_expect, h_expect),
                     f"对照图纵向拼接（{im.size}，应 ({w_expect}, {h_expect})）"))
    # ---- 4. 真机封面也过尺寸/底色检查 ----
    png = d / "demo_douyin34.png"
    covers.make("douyin34", demo_html(1080, 1440, "#000000", 600, ink="#FFFFFF"), png,
                workdir=d / "html")
    rows.append((covers.check(png, "douyin34") == [],
                 "Edge 渲出的演示封面过 check（尺寸/底色/裁齐）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("封面机制（规格表 / 预裁 / 展示裁切 / 检查）")
    print("=" * 72)
    rows = check()
    fails = skips = 0
    for ok, msg in rows:
        if msg.startswith("[SKIP]"):
            skips += 1
            print(f"  [SKIP] {msg[6:]}")
        else:
            fails += not ok
            print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：封面 {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
