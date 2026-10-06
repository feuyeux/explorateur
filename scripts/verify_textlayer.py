#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_textlayer.py — Edge 渲字层的反向验证

第 0 条好数据放行：html_escape / page / matte 数学在合成夹具上全对。
matte 用纯 Pillow 造双底夹具（不依赖浏览器）：在白/黑底上画同一块半透明色，
alpha 必须按 `255 - max(C_w - C_b)` 精确还原——这正是「双底 HTML 除底色外
逐字节同构」这条使用契约的数学验收。

真机（有浏览器时）：视口亏空探测 + 截图裁齐 + 中文渲字一例。
缺浏览器时如实 [SKIP]。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import platform as pt, textlayer as tl    # noqa: E402


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-textlayer-")
    d = pathlib.Path(tmp.name)

    # ---- 0. 好数据放行 ----
    rows.append((tl.html_escape("a<b>&c") == "a&lt;b&gt;&amp;c",
                 "html_escape 转义 & < >"))
    pg = tl.page(1080, 300, "<p>你好</p>", bg="#000123", font="'PingFang SC',sans-serif",
                 dir_="rtl")
    rows.append((all(x in pg for x in ("width:1080px", "height:300px", "#000123",
                                      "'PingFang SC',sans-serif", "direction:rtl")),
                 "page() 五参数全部落进 HTML"))
    rows.append(("document.body.offsetHeight" in pg, "page() 带布局就绪探针 script"))

    # ---- 1. matte 数学：合成夹具精确还原 alpha 与去预乘色 ----
    import numpy as np
    from PIL import Image

    def shot(bg_rgb, out_png, rect=(100, 60, 300, 160), color=(200, 50, 50), alpha=128):
        im = Image.new("RGB", (400, 220), bg_rgb)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        from PIL import ImageDraw
        ImageDraw.Draw(ov).rectangle(rect, fill=(*color, alpha))
        im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        im.save(out_png)

    pw, pb, out = d / "w.png", d / "b.png", d / "m.png"
    shot((255, 255, 255), pw)          # 白底：C_w = 255·(1-a) + C·a
    shot((0, 0, 0), pb)                # 黑底：C_b = C·a
    tl.matte_combine(pw, pb, out)
    m = np.asarray(Image.open(out))
    rect = m[80:140, 120:280]           # 覆盖区内采样（避开边缘 20px 抗锯齿带）
    alphas = rect[..., 3].astype(float)
    rows.append((abs(alphas.mean() - 128) <= 2.0,
                 f"matte 还原 alpha（区均值 {alphas.mean():.1f}，应 ≈128）"))
    rows.append((alphas.std() <= 1.5,
                 f"matte alpha 区内均匀（std {alphas.std():.2f}——不均说明双底不同构）"))
    rgb = rect[..., :3].astype(float)[..., 0]      # R 通道：去预乘应 ≈200
    rows.append((abs(rgb.mean() - 200) <= 4.0,
                 f"去预乘色还原（R 均值 {rgb.mean():.1f}，应 ≈200）"))
    corner = m[5, 5]
    rows.append((corner[3] == 0, f"底区全透明（alpha=0，得 {tuple(corner)}）"))

    # 不透明像素：C_w == C_b → alpha 255
    shot((255, 255, 255), pw, alpha=255)
    shot((0, 0, 0), pb, alpha=255)
    tl.matte_combine(pw, pb, out)
    m2 = np.asarray(Image.open(out))
    rows.append((m2[100, 200][3] >= 253, "全不透明区 → alpha ≈255"))

    # ---- 2. 真机：视口亏空 + 截图裁齐 + 渲字一例 ----
    if pt.browser() is None:
        rows.append((True, "[SKIP] 真机渲字未验（无 Chromium 内核浏览器）"))
        return rows
    deficit, win_h = tl.viewport_deficit(300, workdir=d)
    rows.append((win_h >= 300 and deficit >= 0,
                 f"视口亏空探测（亏空 {deficit}px → 窗口高 {win_h}；坑⑩：不写死 94）"))
    body = ('<div style="display:flex;align-items:center;justify-content:center;'
            'height:300px;font-size:64px;color:#333">一叶知秋</div>')
    png = tl.edge_screenshot(tl.page(400, 300, body), d / "opaque.png",
                             width=400, canvas_h=300, workdir=d / "html")
    from PIL import Image as _I
    with _I.open(png) as im:
        rows.append((im.size == (400, 300),
                     f"单次截图裁齐画布（尺寸 {im.size}，应 (400,300)——补偿尾巴已裁）"))
    mp = tl.shoot_matte(lambda bg: tl.page(400, 300, body, bg=bg), d / "matte.png",
                        width=400, canvas_h=300, workdir=d / "html")
    arr = np.asarray(_I.open(mp))
    ink = (arr[..., 3] > 10)
    rows.append((ink.any() and arr[..., 3].max() >= 200,
                 f"渲字 matte 有墨（非透明像素 {int(ink.sum())}，"
                 f"峰值 alpha {int(arr[..., 3].max())})"))
    rows.append((arr.shape == (300, 400, 4), f"matte 输出 RGBA 且裁齐（{arr.shape}）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("Edge 渲字层（视口探测 / 截图 / 双 matte）")
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
    print(f"{'OK' if not fails else 'FAIL'}：渲字层 {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
