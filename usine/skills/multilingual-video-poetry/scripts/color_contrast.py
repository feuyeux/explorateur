#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文字压实拍画面：量背景亮度，不靠眼睛挑颜色。

## 为什么不能靠色

配色是看着挑的就会漏。实测教训：冬季冰蓝初版 `#69B4E8` 叠在白雪上几乎看不见，
因为「冷色配雪」在直觉上成立。而**量化之后原因很清楚**——四季文字区的背景亮度：

| 季 | 紧邻背景 p50 | p90 |
|---|---|---|
| 春 | 0.103 | 0.168 |
| 夏 | 0.135 | 0.236 |
| 秋 | 0.110 | 0.328 |
| **冬** | **0.486** | **0.601** |

**冬季背景亮度是其余三季的 3.6 倍。** 同一套配色、同样的阴影强度，在冬季就失效——
这不是「颜色没选好」，是底色根本不在一个量级。目视只能看出「看不见」，
量能量出「差多少倍」，从而知道该压到什么档。

## ⚠️ WCAG 对比度**不适用**于彩字压实拍

脚本会顺带算出 WCAG 亮度对比，但**不要拿它判定合格**。实测：四季全部「不达标」
（1.3–2.5），而这些成片是逐帧目视验收过的、可读。原因：

- WCAG 为 **UI 文字压平底色**设计，那里没有阴影光晕、没有纯色相区分；
- 彩字在实拍上靠的是**亮度差 + 色相差 + 阴影光晕**三者叠加，
  WCAG 只看第一项，会系统性低估彩字的可读性。

所以本脚本**不以 WCAG 判定退出码**，只报背景亮度与原始比值。
真正的验收是**目视复核渲染后的合成帧**——但**先量背景亮度**，
才知道该重点盯哪一季、该往哪个方向调。

## `--gate`：把「该季可读」降级成二值判据（阈值自标定，不内置）

`--gate <min_gap>` 给出后，脚本对每个已合成字幕的季算
`|字芯亮度 − 环带背景 p90|`，任一季低于阈值 → 逐季 PASS/FAIL + 退出码 1；
全过 → 退出码 0。**阈值没有默认值，必须由项目自己标定**——在已目视验收
过的成片帧上跑本脚本，取各季实测亮度差的最低档再留余量。为什么不内置：
四季归档实测（0.168–0.601）只覆盖一个项目，拿它当普适阈值就是编数据
（纪律 8）；WCAG 更不能用（见上）。`--gap-ref p50|p90` 选参照环带（默认 p90）。

## 用法

```bash
# 四季一次量完（推荐：会报出背景亮度排名，告诉你哪季最危险）
uv run python scripts/color_contrast.py --seasons examples/sijijie/横版四季_20s.mp4 \
    --cards examples/sijijie/cards/横版

# 同上 + 二值判据：阈值在已验收帧上标定后交给 CI / 验收官
uv run python scripts/color_contrast.py --seasons … --cards … \
    --gate 0.30 --gap-ref p90

# 只看某张原始帧的背景亮度分布
uv run python scripts/color_contrast.py 帧.png --band bottom

# 给一个色，输出保留色相的深浅几档供挑选
uv run python scripts/color_contrast.py 帧.png --band bottom --suggest '#2E7CB8'
```
"""
from __future__ import annotations

import argparse
import colorsys
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

_BIN: dict[str, str] = {}


def _bin(name: str) -> str:
    """外部可执行文件经 `feuille.platform` 解析（AGENTS.md 跨平台硬约定 1）。"""
    if name not in _BIN:
        try:
            from feuille import platform
            got = getattr(platform, name)() or ""
        except ImportError:
            got = ""
        if not got:
            sys.exit(f"找不到 {name}：请用 `uv run --project usine python …` 运行"
                     f"（feuille.platform 解析），或安装后重跑")
        _BIN[name] = got
    return _BIN[name]

SEASON_SHOT = {"春": 2.6, "夏": 7.8, "秋": 11.9, "冬": 16.7}   # 只对四季节项目母版成立，别的母版用 --shots 给
BANDS = {"top": (0.00, 0.22), "bottom": (0.50, 1.00)}
GLYPH_HUE_TOL, GLYPH_V_MIN, GLYPH_S_MIN = 0.03, 0.5, 0.25
RING_PX = 14


def _load_json(text, flag):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"{flag} 不是合法 JSON：{e}")


def srgb_to_lin(c):
    c = np.asarray(c, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lum_of(arr):
    a = srgb_to_lin(arr)
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def lum_hex(h):
    a = srgb_to_lin(np.array(hex2rgb(h), dtype=float))
    return float(0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2])


def wcag_ratio(hex_a, lum_b):
    la, lb = lum_hex(hex_a), lum_b
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def band(arr, name):
    lo, hi = BANDS[name]
    h = arr.shape[0]
    return arr[int(h * lo):int(h * hi)]


def glyph_mask(reg, color):
    """字形掩膜。参数是**标定**出来的，不是拍的：色相容差 0.09 会把夏天的天空与
    草地一并抓进来（占区域 68.5%）；0.03 + v>0.5 才精准命中字芯——此时字形亮度
    p75 与该色实算亮度一致（实测 0.635 vs 0.636）。"""
    hue_t = colorsys.rgb_to_hls(*(c / 255 for c in hex2rgb(color)))[0]
    mxf, mnf = reg.max(axis=2), reg.min(axis=2)
    v = mxf / 255.0
    s = np.where(mxf > 0, (mxf - mnf) / np.maximum(mxf, 1e-6), 0.0)
    # 色相向量化算（逐像素 colorsys 要跑 ~20 万次，慢约两个量级）。
    # 分支优先级 r>g>b 与 colorsys.rgb_to_hsv 一致（灰像素 r 分支给出 0，
    # 两通道并列最大时结果也一致），标定注释里的实测数字不受影响。
    r, g, b = (reg[..., i].reshape(-1) / 255.0 for i in range(3))
    mx = np.maximum(np.maximum(r, g), b)
    c = mx - np.minimum(np.minimum(r, g), b)
    safe_c = np.where(c > 0, c, 1.0)
    hue = np.where(mx == r, ((g - b) / safe_c) % 6.0,
                   np.where(mx == g, (b - r) / safe_c + 2.0,
                            (r - g) / safe_c + 4.0))
    hsv = (hue / 6.0).reshape(reg.shape[:2])
    dh = np.minimum(np.abs(hsv - hue_t), 1 - np.abs(hsv - hue_t))
    return (dh < GLYPH_HUE_TOL) & (s > GLYPH_S_MIN) & (v > GLYPH_V_MIN)


def dilate(m, n):
    out = m.copy()
    for _ in range(n):
        d = out.copy()
        d[1:, :] |= out[:-1, :]
        d[:-1, :] |= out[1:, :]
        d[:, 1:] |= out[:, :-1]
        d[:, :-1] |= out[:, 1:]
        out = d
    return out


def measure(frame, card, color, band_name):
    """返回 (字芯亮度, 紧邻背景 p50/p90, 字形像素数)。card=None 则只量背景。"""
    img = frame.convert("RGBA")
    if card is not None:
        img = Image.alpha_composite(
            img, card.convert("RGBA").resize(img.size, Image.LANCZOS))
    reg = band(np.asarray(img.convert("RGB"), dtype=float), band_name)
    lums = lum_of(reg)
    if card is None:
        return None, float(np.percentile(lums, 50)), float(np.percentile(lums, 90)), 0
    g = glyph_mask(reg, color)
    if g.sum() < 60:
        return None, float("nan"), float("nan"), int(g.sum())
    ring = dilate(g, RING_PX) & ~g
    if ring.sum() < 60:
        return None, float("nan"), float("nan"), int(g.sum())
    return (float(np.percentile(lums[g], 75)),
            float(np.percentile(lums[ring], 50)),
            float(np.percentile(lums[ring], 90)),
            int(g.sum()))


def suggest(hex_col):
    r, g, b = (c / 255 for c in hex2rgb(hex_col))
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    out = []
    for L in (0.90, 0.72, 0.50, 0.28):
        rr, gg, bb = colorsys.hls_to_rgb(h, L, min(1.0, s * 1.2))
        out.append("#%02X%02X%02X" % (round(rr * 255), round(gg * 255), round(bb * 255)))
    return out


def gap_verdict(gap: float, min_gap: float, season: str) -> str:
    """`--gate` 的二值判据（纯函数，反向验证在 scripts/verify_skill_scripts.py）。

    判的是「字芯与紧邻背景的亮度差 ≥ 项目标定阈值」。阈值**必须外部给**：
    在已目视验收的成片帧上实测后标定，不内置默认（四季归档只覆盖一个项目，
    编普适阈值违反纪律 8）。
    """
    if gap >= min_gap:
        return f"PASS {season}：亮度差 {gap:.3f} ≥ 阈值 {min_gap:g}"
    return (f"FAIL {season}：亮度差 {gap:.3f} < 阈值 {min_gap:g}"
            f"——该季彩字会先失效，压深字色或压暗底色后再量")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?")
    ap.add_argument("--band", default="bottom", choices=list(BANDS))
    ap.add_argument("--seasons", help="母版 mp4：四季一次量完")
    ap.add_argument("--cards", help="字幕层目录，如 cards/横版")
    ap.add_argument("--colors", help='季色 JSON，如 {"春":["#F0568C","#C9889E"]}')
    ap.add_argument("--shots", help='各季取帧秒点 JSON，如 {"春":2.6,"夏":7.8}；'
                                    '默认值是四季节项目母版的标定值，别的母版必须给')
    ap.add_argument("--suggest", help="给一个色，返回保留色相的深浅几档")
    ap.add_argument("--gate", type=float, default=None,
                    help="二值判据阈值：|字芯亮度 − 环带背景| 低于它的季 FAIL、"
                         "退出码 1。没有默认值——在已目视验收的成片帧上标定后"
                         "再给（编普适阈值违反纪律 8）")
    ap.add_argument("--gap-ref", default="p90", choices=["p50", "p90"],
                    help="gate 参照的环带分位（默认 p90）")
    a = ap.parse_args()

    if a.seasons:
        vid = Path(a.seasons)
        if not vid.exists():
            print(f"找不到 {vid}")
            return 2
        colors = _load_json(a.colors, "--colors") if a.colors else None
        if colors is None:
            # 季色默认值先取**入库的归档副本**（assets/example），再退到本机
            # 工作目录（examples/sijijie，不入库）——fresh clone 上只有前者。
            here = Path(__file__).resolve().parent
            for cand in (here.parent / "assets" / "example",
                         here.parents[2] / "examples" / "sijijie"):
                if not (cand / "季节与译文.py").exists():
                    continue
                sys.path.insert(0, str(cand))
                try:
                    import 季节与译文 as meta            # noqa: E402
                    colors = {s: list(v) for s, v in meta.SEASON_COLOR.items()}
                finally:
                    sys.path.remove(str(cand))
                if colors is not None:
                    break
        if colors is None:
            print("未给 --colors，也找不到 季节与译文.py。"
                  "用例：--colors '{\"春\":[\"#F0568C\",\"#C9889E\"]}'")
            return 2
        print(f"母版 {vid.name} · 文字区 {a.band} · 已合成字幕层\n")
        print(f"{'季':<4}{'主色':>10}{'字芯':>8}{'环带p50':>10}{'环带p90':>10}"
              f"{'WCAG比值':>10}  备注")
        rows = []
        gaps: dict[str, float] = {}
        shots = _load_json(a.shots, "--shots") if a.shots else SEASON_SHOT
        with tempfile.TemporaryDirectory() as td:
            for s, sec in shots.items():
                if s not in colors:
                    continue
                fr = Path(td) / f"{s}.png"
                subprocess.run([_bin("ffmpeg"), "-y", "-v", "error", "-ss", str(sec),
                                "-i", str(vid), "-frames:v", "1", str(fr)],
                               check=True, timeout=120)
                card = None
                if a.cards:
                    cands = sorted(Path(a.cards).glob(f"*.{s}.png"))
                    if not cands:
                        print(f"  ✗ {a.cards} 下找不到 *.{s}.png，跳过 {s}")
                        continue
                    card = Image.open(cands[0])
                main_c = colors[s][0]
                gl, p50, p90, npx = measure(Image.open(fr), card, main_c, a.band)
                if card is None:
                    print(f"{s:<4}{main_c:>10}{'—':>8}{p50:>10.3f}{p90:>10.3f}{'—':>10}  未合成")
                    rows.append((s, p90))
                    continue
                if gl is None:
                    # 字形没抓到：量出来的 p50/p90 是 NaN，硬印会 TypeError，
                    # 进 rows 又会污染最亮/最暗季的排名——跳过并说原因
                    print(f"{s:<4}{main_c:>10}{'—':>8}{'—':>10}{'—':>10}{'—':>10}  "
                          f"字形命中不足（{npx}px）——查 --colors 是否对、卡片是否这季、"
                          f"--band 区里有没有字")
                    continue
                rows.append((s, p90))
                note = f"字形{npx}px"
                if a.gate is not None:
                    gaps[s] = abs(gl - (p90 if a.gap_ref == "p90" else p50))
                    note += f"  亮度差 {gaps[s]:.3f}"
                print(f"{s:<4}{main_c:>10}{gl:>8.3f}{p50:>10.3f}{p90:>10.3f}"
                      f"{wcag_ratio(main_c, p90):>10.2f}  {note}")
        if len(rows) > 1:
            hi = max(rows, key=lambda x: x[1])
            lo = min(rows, key=lambda x: x[1])
            print(f"\n最亮季：{hi[0]}（p90={hi[1]:.3f}）；最暗季：{lo[0]}"
                  f"（p90={lo[1]:.3f}）——相差 {hi[1] / lo[1]:.1f}×")
            if hi[1] / lo[1] > 2:
                print(f"→ {hi[0]}的底色量级远高于其他季，同一套配色与阴影强度在它上面"
                      f"最先失效，**目视复核优先盯这一季**。")
        print("\n注：WCAG 比值仅供参考、不作判定（见文件头说明）。"
              "验收靠目视复核渲染后的合成帧。")
        if a.gate is None:
            return 0
        # --gate：把「该季彩字可读」降成二值判据。没量到的季不许静默混过
        # （纪律 12：SKIP 不是 PASS——未合成 / 字形命中不足在 gate 下就是 FAIL）。
        bad = 0
        for s in shots:
            if s not in colors:
                continue
            if s not in gaps:
                print(f"FAIL {s}：未量到（未合成 / 字形命中不足）——gate 模式下没验不许当过")
                bad += 1
                continue
            v = gap_verdict(gaps[s], a.gate, s)
            print(v)
            bad += v.startswith("FAIL")
        print(f"\nGATE {'FAIL' if bad else 'PASS'}：阈值 {a.gate:g}"
              f"（gap-ref {a.gap_ref}；阈值由项目在已验收帧上标定，不内置默认）")
        return 1 if bad else 0

    if not a.image:
        ap.print_help()
        return 2
    img = Image.open(a.image).convert("RGB")
    if a.suggest:
        _, p50, p90, _ = measure(img, None, a.suggest, a.band)
        print(f"该区域背景 p50={p50:.3f} p90={p90:.3f}；{a.suggest} 的深浅几档：")
        for c in suggest(a.suggest):
            print(f"  {c}  亮度={lum_hex(c):.3f}  WCAG比值(仅供参考)={wcag_ratio(c, p90):.2f}")
        return 0
    _, p50, p90, _ = measure(img, None, "#FFFFFF", a.band)
    print(f"{Path(a.image).name} 区域={a.band}  背景亮度 p50={p50:.3f}  p90={p90:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())