# -*- coding: utf-8 -*-
"""textlayer.py — Edge headless 渲字：视口探测 / 截图 / 双 matte 抠像

**为什么文字必须走 Edge 截图而不是 Pillow 画字**：本机 Pillow `raqm=False`
（无 HarfBuzz/FriBiDi），阿拉伯语 / 希伯来语 / 天城文会渲染成散字、错向、缺 matra；
Chromium 内核自带完整塑形，一次截图就对。这是铁律级的经验（workspace AGENTS.md）。

**视口亏空**：Edge 的 `--window-size` 高度 ≠ 实际视口高度（实测 300 → 206，
差值随版本/机器变）。**先探一次差值**、之后所有截图用补偿后的窗口高度——
不写死差值，换机器自动重测。探法：`--dump-dom` 读 `window.innerHeight`。

**双 matte 抠像的数学**：白底/黑底各截一次，`C_w - C_b = (1-a)·255` →
`alpha = 255 - max(C_w - C_b)`；去预乘 `rgb = C_b / a`。半透明投影可精确还原。
不透明整图（封面）**不需要**这套，单次截图即可。双底截图后**载入前裁齐画布**：
补高后的 opaque 截图比画布高一截，不裁会把画布外的深色像素贴进成片。

**Edge 截图一律串行**：4 线程并发曾被系统 SIGKILL——并发收益是分钟级，
炸掉是整批重做，不赌。

浏览器一律经 `feuille.platform` 解析，绝不写死路径（跨平台约定 1）。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import platform as _pt

HTML_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg};
font-family:{font};-webkit-font-smoothing:antialiased;direction:{dir};}}
*{{box-sizing:border-box}}
</style></head><body>{body}<script>document.body.offsetHeight;</script></body></html>"""


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def page(w: int, h: int, body: str, *, bg: str = "#FFFFFF", font: str = "sans-serif",
         dir_: str = "ltr") -> str:
    """整页 HTML（尺寸/底色/字体栈/书写方向全部参数化；流式布局，别用 absolute）。"""
    return HTML_HEAD.format(w=w, h=h, bg=bg, font=font, dir=dir_, body=body)


def _require_browser():
    b = _pt.browser()
    if b is None:
        raise SystemExit("缺 Chromium 内核浏览器（渲字必需；resolver 未找到，"
                         "缺件清单见 feuille.platform.missing()）")
    return b[1]


def _shot_args(browser: str, width: int, win_h: int, png: Path, html: Path,
               budget_ms: int) -> list[str]:
    # --force-device-scale-factor=1：保证 png 尺寸 == 窗口尺寸，不随系统缩放漂
    return [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=1", f"--window-size={width},{win_h}",
            f"--screenshot={png}", f"--virtual-time-budget={budget_ms}",
            html.as_uri()]


def viewport_deficit(canvas_h: int, browser: str | None = None,
                     nominal: int = 300, workdir=None) -> tuple[int, int]:
    """探一次视口亏空（坑⑩）。返回 (亏空 px, 补偿后的窗口高度)。

    补偿后的 opaque 截图会比 canvas_h 高一截——**调用方载入前必须裁到
    (0, 0, W, canvas_h)**（本模块的 shoot_* 已内置裁齐，直接用它们即可）。
    """
    browser = browser or _require_browser()
    probe_dir = Path(workdir) if workdir else Path.cwd()
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_dir / "_vp_probe.html"
    probe.write_text(HTML_HEAD.format(w=100, h=canvas_h, bg="#FFFFFF",
                                      font="sans-serif", dir="ltr",
                                      body="<div style='height:100vh'></div>"
                                           "<script>document.title=window.innerHeight;</script>"),
                     "utf-8")
    dom = subprocess.run([browser, "--headless=new", "--disable-gpu",
                          f"--window-size=1080,{nominal}", "--virtual-time-budget=800",
                          "--dump-dom", probe.as_uri()],
                         check=True, capture_output=True, timeout=60).stdout.decode("utf-8", "ignore")
    m = re.search(r"<title>(\d+)</title>", dom)
    viewport = int(m.group(1)) if m else canvas_h
    chrome_px = nominal - viewport
    return chrome_px, canvas_h + max(0, chrome_px)


def edge_screenshot(html: str, out_png, *, width: int, canvas_h: int,
                     browser: str | None = None, workdir=None,
                     budget_ms: int = 1600) -> Path:
    """不透明整图**单次**截图（封面等用这个；透明叠加层用 shoot_matte）。

    视口亏空自动补偿 + **裁齐到 canvas_h**（坑⑩ + 残留尾巴一次处理完）。
    """
    browser = browser or _require_browser()
    workdir = Path(workdir) if workdir else Path.cwd()
    workdir.mkdir(parents=True, exist_ok=True)
    _, win_h = viewport_deficit(canvas_h, browser=browser, workdir=workdir)
    h_path = workdir / f"{Path(out_png).stem}.html"
    h_path.write_text(html, "utf-8")
    png = Path(out_png)
    if png.exists():
        png.unlink()
    subprocess.run(_shot_args(browser, width, win_h, png, h_path, budget_ms),
                   check=True, capture_output=True, timeout=180)
    if not png.exists():
        raise RuntimeError(f"edge shot failed: {png}")
    _crop(png, width, canvas_h)
    return png


def shoot_matte(html_fn, out_png, *, width: int, canvas_h: int,
                browser: str | None = None, workdir=None,
                budget_ms: int = 1600) -> Path:
    """透明文字层：同一 HTML 在白底 / 黑底各截一次 → matte_combine 出精确 alpha。

    html_fn(bg_color) 返回该底色下的整页 HTML（除底色外两份 HTML 必须逐字节同构，
    否则 matte 数学不成立）。输出已裁齐 canvas_h。
    """
    browser = browser or _require_browser()
    workdir = Path(workdir) if workdir else Path.cwd()
    workdir.mkdir(parents=True, exist_ok=True)
    _, win_h = viewport_deficit(canvas_h, browser=browser, workdir=workdir)
    shots = []
    for tag, bg in (("_w", "#FFFFFF"), ("_b", "#000000")):
        h_path = workdir / f"{Path(out_png).stem}{tag}.html"
        h_path.write_text(html_fn(bg), "utf-8")
        png = workdir / f"{Path(out_png).stem}{tag}.png"
        if png.exists():
            png.unlink()
        subprocess.run(_shot_args(browser, width, win_h, png, h_path, budget_ms),
                       check=True, capture_output=True, timeout=180)
        if not png.exists():
            raise RuntimeError(f"edge shot failed: {png}")
        _crop(png, width, canvas_h)
        shots.append(png)
    out = Path(out_png)
    matte_combine(shots[0], shots[1], out)
    return out


def _crop(png: Path, w: int, h: int) -> None:
    """补高后的截图裁回画布尺寸（viewport_deficit 的残留尾巴，就地裁。"""
    from PIL import Image
    with Image.open(png) as im:
        if im.size != (w, h):
            im.crop((0, 0, w, h)).save(png)


def matte_combine(png_w, png_b, out) -> None:
    """双 matte 抠像：白底/黑底两次截图 → 精确 alpha。

    `C_w - C_b = (1-a)·255` → `alpha = 255 - max(C_w - C_b, 通道维)`；
    去预乘 `rgb = C_b / a`（alpha 下限 1e-4 防除零）。半透明投影可精确还原。
    """
    import numpy as np
    from PIL import Image
    w = np.asarray(Image.open(png_w).convert("RGB"), dtype=float)
    b = np.asarray(Image.open(png_b).convert("RGB"), dtype=float)
    alpha = np.clip(255.0 - (w - b).max(axis=2), 0, 255)
    a = np.maximum(alpha / 255.0, 1e-4)[..., None]
    rgb = np.clip(b / a, 0, 255)
    Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA").save(out)
