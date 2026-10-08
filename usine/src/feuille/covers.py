# -*- coding: utf-8 -*-
"""covers.py — 封面机制（⑦）：平台规格表 / 预裁底图 / 截图 / 展示裁切模拟 / 检查

搬运自 yiyezhiqiu 的 make_covers.py + verify_covers.py + verify_crop_safety.py
（终态视角重构：机制与版式分离——**版式是内容**，去 examples/yiyezhiqiu/cover_layouts.py；
本模块只留平台规格、预裁、截图、裁切模拟与检查）。

**铁律（PUBLISH-RULES 规则 1 的机制化）**：
- 封面永远是**预生成带文字图**，不是平台默认帧；纯画面首帧 = 未完成。
- **上传比例 ≠ 展示比例**：平台会在信息流里二次裁切，贴边的文字会被切掉。
  SPECS 的 `safe` 就是各平台真实展示裁切框——文字三要素（片名/首句/标签）
  必须整体落在 safe 内。两次学费：小红书文字块排到 y1790 诗体标签整行被切；
  B 站左图右文版式 4:3 中央裁切后只剩窄边（→ 改居中卡片）。
- **底图预裁，不靠 CSS cover**：取景框写死（crop_backdrop 的 box 参数），
  CSS cover 的裁切时机不可控，会把主体切到面板底下。
- 文字标签**从单一事实源取**（调用方传入）：yiyezhiqiu 曾在封面代码里硬编码
  METER 字典，改诗后阿拉伯语封面一直印着已废弃的「بحر الكامل」。

**判定证据**：尺寸/底色可程序判（check）；**文字有没有被展示裁切换掉，
最终以 display_crop 出的预览对照图 + 人眼为准**（照片底图无法程序判墨迹）。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import textlayer

# 平台规格（唯一事实源：尺寸 / 底色 / 展示裁切安全区）。
# safe = (x0, y0, x1, y1)：平台信息流实际展示的区域；None = 上传即展示、无裁切。
#   - 抖音竖封面槽实为 3:4：9:16 传上去会被居中裁掉上下各 240px（标题带正好被切没）
#   - 小红书信息流 3:4：1080×1920 上下各切 240 → 只保留 y 240–1680
#   - B 站首页推荐 4:3：1920×1080 左右各切 240 → 只保留 x 240–1680（个人空间 16:9 无裁切）
SPECS = {
    "douyin":      {"name": "抖音",    "w": 1080, "h": 1920, "bg": "#000000", "safe": None},
    "douyin34":    {"name": "抖音3:4", "w": 1080, "h": 1440, "bg": "#000000", "safe": None},
    "xiaohongshu": {"name": "小红书",  "w": 1080, "h": 1920, "bg": "#FFFFFF",
                    "safe": (0, 240, 1080, 1680)},
    "bilibili":    {"name": "哔哩哔哩", "w": 1920, "h": 1080, "bg": "#FB7299",
                    "safe": (240, 0, 1680, 1080)},
    "zhihu":       {"name": "知乎",    "w": 1920, "h": 1080, "bg": "#0084FF", "safe": None},
}


def filename(name: str, key: str) -> str:
    """封面文件名（唯一命名口径，发布清单与检查同源）。"""
    s = SPECS[key]
    return f"{name}_{key}_{s['w']}x{s['h']}.png"


def spec(key: str) -> dict:
    try:
        return SPECS[key]
    except KeyError:
        raise SystemExit(f"未知封面规格 {key!r}（合法：{sorted(SPECS)}）") from None


def crop_backdrop(src, box, out, quality: int = 92) -> Path:
    """按写死的取景框从源图裁底图（**预裁**，不靠 CSS cover——裁切时机不可控）。

    box 的坐标空间跟调用方约定（示例项目用母版像素空间）；预裁后底图比例
    与画面区一致，叠版式时 CSS 不再做二次裁切。
    """
    from PIL import Image
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(src).convert("RGB").crop(box).save(out, quality=quality)
    return out


def make(key: str, html: str, out_png, *, workdir=None) -> Path:
    """整页封面 HTML → 不透明整图**单次**截图（文字一律 Edge 渲，不透明不需要双 matte）。

    html 由版式方（内容）产出；尺寸/裁齐由本机制按 SPECS 保证。
    """
    s = spec(key)
    return textlayer.edge_screenshot(html, out_png, width=s["w"], canvas_h=s["h"],
                                     workdir=workdir, budget_ms=2200)


def display_crop(png, key: str):
    """模拟平台信息流的**真实展示裁切**（safe=None 原样返回）。

    判定文字是否被切，以这个预览为准——上传图好看不等于发出去好看。
    """
    from PIL import Image
    s = spec(key)
    im = Image.open(png)
    if s["safe"] is None:
        return im.convert("RGB")
    return im.convert("RGB").crop(s["safe"])


def sheet(pngs, out) -> Path:
    """把若干预览纵向拼成对照图（发布后核对 / 裁切安全的人眼判据载体）。"""
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in pngs]
    wmax = max(im.width for im in ims)
    total_h = sum(im.height for im in ims) + 2 * (len(ims) - 1)
    canvas = Image.new("RGB", (wmax, total_h), (51, 51, 51))
    y = 0
    for im in ims:
        canvas.paste(im, (0, y))
        y += im.height + 2
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def check(png, key: str) -> list[str]:
    """尺寸 + 底色检查（问题列表；空 = 通过）。

    底色按**外圈众数**取样：平均值会被照片出血带偏（实测知乎蓝被算成 (7,67,128)）。
    版式带边框/半幅面板时，外圈的主导色仍是契约底色——众数取的是「出现最多的」，
    照片色散、契约色聚，众数天然站得住。
    """
    from PIL import Image
    s = spec(key)
    problems: list[str] = []
    im = Image.open(png).convert("RGB")
    if im.size != (s["w"], s["h"]):
        problems.append(f"{Path(png).name}: 尺寸 {im.size} ≠ 规格 {s['w']}×{s['h']}（{key}）")
        return problems
    want = tuple(int(s["bg"][i:i + 2], 16) for i in (1, 3, 5))
    px = im.load()
    ring = []
    d = 2
    for x in range(im.width):
        for y in (0, 1, im.height - d, im.height - 1):
            ring.append(px[x, y])
    for y in range(d, im.height - d):
        for x in (0, 1, im.width - d, im.width - 1):
            ring.append(px[x, y])
    (mode_c, _n) = Counter(ring).most_common(1)[0]
    if max(abs(a - b) for a, b in zip(mode_c, want)) > 8:
        problems.append(f"{Path(png).name}: 外圈众数色 {mode_c} ≠ 契约底色 {s['bg']}"
                        f"（通道差 >8）")
    return problems


# ── CLI 适配层（cli.py 路由叶子；业务在上面，这里只接线） ───────────────


def main_make(argv=None) -> int:
    """cli.py 路由入口：`feuille cover make <key> <html> <out.png>`。

    key 从 SPECS 注册表现取（不猜）；html 是**整页封面 HTML 文件路径**
    （内容，不是 URL——渲染在 textlayer.edge_screenshot）。
    """
    import argparse
    ap = argparse.ArgumentParser(prog="feuille cover make")
    ap.add_argument("key", help=f"规格键（注册表现取）：{' / '.join(SPECS)}")
    ap.add_argument("html", help="整页封面 HTML 文件（内容，非 URL）")
    ap.add_argument("out_png", help="输出 PNG 路径")
    a = ap.parse_args(argv)
    out = make(a.key, Path(a.html).read_text("utf-8"), a.out_png)
    print(f"wrote {out}")
    return 0


def main_check(argv=None) -> int:
    """cli.py 路由入口：`feuille cover check <png> <key>`（问题列表空 = 通过）。"""
    import argparse
    ap = argparse.ArgumentParser(prog="feuille cover check")
    ap.add_argument("png", help="待检封面 PNG")
    ap.add_argument("key", help=f"规格键（注册表现取）：{' / '.join(SPECS)}")
    a = ap.parse_args(argv)
    problems = check(a.png, a.key)
    for p in problems:
        print("  -", p)
    print("OK" if not problems else f"FAIL：{len(problems)} 项问题")
    return 1 if problems else 0
