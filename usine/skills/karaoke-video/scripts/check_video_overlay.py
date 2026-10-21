#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_video_overlay.py — 视频双层（lay/top）帧级对齐门（技能层，AGENTS.md 纪律 23）

事故回顾（nine-arts，2026-10-13）：视频一直**没有**海报侧的双层对齐门——
korean.css 杂行吞掉 `.stack{display:inline-grid}` 后视频红/蓝左右分家，
海报门却全绿假阴性。海报的 check_overlay 是技能层判据，但视频侧的
「渲染单层帧 → 比对」流程长在实例管线里，换项目即重现——本脚本把它
下沉为 karaoke-video 技能判据，任何实例直接调用。

方法（与海报门同源，勿在合成帧上量——顶层画在底层上，重叠像素全被盖住）：
  1. 把 video_src.html 注入 `.stack .top/.lay { visibility:hidden }` 出两张
     单层变体（只替换第一个 </style>，保持字体等相对路径不动）；
  2. 逐语言渲染 合成/lay/top 三帧（?lang=<L>&state=<S>，默认 state=99 全亮）；
  3. 从合成帧扫强色像素出大字 bbox（±40px 余量，坐标除回 CSS px）；
  4. 跑 one-page-poster 的 check_overlay.py（--scale/--dilate 透传）。

**门校准（勿回退，nine-arts 实测）**：视频每 token 各一个 stack，下层整
token 成形（"र्ति"）、上层拆开成形（"र्त"），ि 类重排使两层栅格化相位差
~1px 摊在每条笔画边上——1× 无膨胀时 2.5–2.7% 假 FAIL（repha 与主干完全
重合，失配全在笔边）。默认 DSF=2 + dilate=3 吸收相位差；真 8px 错位仍以
7.5% unmatched 被拦，分离度中间无灰色地带。

用法：
  check_video_overlay.py <video_dir> [--langs hi-IN,ar-SA,he-IL]
                         [--src video_src.html] [--state 99]
                         [--width 1920] [--height 1080]
                         [--dsf 2] [--dilate 3]
                         [--red c9403a] [--blue 2f5d9e]
                         [--band 100,200,1720,880]

退出码：0 = 全部对齐；1 = 有语言失配（stderr 列出）。单层变体 _lay.html /
_top.html 落在 video_dir（相对路径要同目录），结束即删。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys


def hx(s: str) -> tuple[int, int, int]:
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video_dir")
    ap.add_argument("--langs", default="hi-IN,ar-SA,he-IL",
                    help="要过门的双层语言（逗号分隔）")
    ap.add_argument("--src", default="video_src.html")
    ap.add_argument("--state", default="99", help="卡拉OK 状态参数（默认全亮）")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--dsf", type=int, default=2, help="device scale factor（门校准勿回退）")
    ap.add_argument("--dilate", type=int, default=3, help="check_overlay 底掩码膨胀（device px）")
    ap.add_argument("--red", default="c9403a")
    ap.add_argument("--blue", default="2f5d9e")
    ap.add_argument("--band", default=None,
                    help="合成帧强色扫描区 CSS px：x0,y0,x1,y1（默认 100,200,W-100,H-200）")
    return ap.parse_args()


def main() -> None:
    a = parse_args()
    # 浏览器解析走 library 的 feuille.platform（唯一事实源），$CHROME_BIN 优先；
    # 不做 sys.path 兜底导入（uv run 下 feuille 本就可导入，兜底只会吞错）。
    import os
    browser = os.environ.get("CHROME_BIN") or ""
    if not browser:
        try:
            from feuille import platform
            browser = platform.browser_path() or ""
        except Exception:
            browser = ""
    if not browser:
        sys.exit("找不到 Chromium 系浏览器：请用 `uv run --project usine python …` 运行"
                 "（feuille.platform 解析浏览器），或装 Chrome / Edge，或设 $CHROME_BIN")
    # headless 截图纪律（AGENTS.md）：--headless=new 且不带 --user-data-dir，
    # URL 一律绝对路径；虚拟时钟走满让 JS（字号自适应等）跑完。
    def shot(url: str, out: str) -> None:
        subprocess.run([browser, "--headless=new", "--disable-gpu",
                        "--virtual-time-budget=10000",
                        f"--window-size={a.width},{a.height}",
                        f"--force-device-scale-factor={a.dsf}", "--hide-scrollbars",
                        f"--screenshot={out}", url], check=True, timeout=180,
                       capture_output=True)

    V = pathlib.Path(a.video_dir).resolve()
    usine = pathlib.Path(__file__).resolve().parents[3]
    overlay = usine / "skills" / "one-page-poster" / "scripts" / "check_overlay.py"
    if not overlay.is_file():
        sys.exit(f"check_overlay.py 不在预期位置：{overlay}")
    src_path = V / a.src
    src = src_path.read_text(encoding="utf-8")
    for marker in ("</style>", ):
        if marker not in src:
            sys.exit(f"{src_path} 里没有 {marker!r}——单层注入点缺失")
    # PIL 导入与 hex/band 解析都在写变体**之前**：从这里到 finally 清理之间
    # 的任何异常路径都不会把 _lay/_top.html 留在 video_dir 毒化下次运行。
    from PIL import Image
    red, blue = hx(a.red), hx(a.blue)
    x0, y0, x1, y1 = (tuple(int(v) for v in a.band.split(","))
                      if a.band else (100, 200, a.width - 100, a.height - 200))
    (V / "_lay.html").write_text(
        src.replace("</style>", ".stack .top { visibility: hidden; }</style>", 1),
        encoding="utf-8")
    (V / "_top.html").write_text(
        src.replace("</style>", ".stack .lay { visibility: hidden; }</style>", 1),
        encoding="utf-8")

    def bbox_strong(f: str) -> tuple[int, int, int, int]:
        """合成帧强色 bbox（CSS px，±40 余量）。红蓝都在的大字区域。"""
        im = Image.open(f).convert("RGB")
        px = im.load()
        xs: list[int] = []
        ys: list[int] = []
        tr, tg, tb = red[0], red[1], red[2]
        ur, ug, ub = blue[0], blue[1], blue[2]
        for y in range(y0 * a.dsf, y1 * a.dsf, 2 * a.dsf):
            for x in range(x0 * a.dsf, x1 * a.dsf, 2 * a.dsf):
                r, g, b = px[x, y]
                if ((abs(r - tr) < 60 and abs(g - tg) < 60 and abs(b - tb) < 60 and r > g + 50)
                        or (abs(r - ur) < 60 and abs(g - ug) < 60 and abs(b - ub) < 60 and b > g)):
                    xs.append(x)
                    ys.append(y)
        if not xs:
            sys.exit(f"{f}: 合成帧扫描区里找不到大字强色像素（band={x0},{y0},{x1},{y1}）")
        return (min(xs) // a.dsf - 40, min(ys) // a.dsf - 40,
                (max(xs) - min(xs)) // a.dsf + 80, (max(ys) - min(ys)) // a.dsf + 80)

    langs = [s.strip() for s in re.split(r"[,\s]+", a.langs) if s.strip()]
    fails: list[str] = []
    try:
        for lang in langs:
            frames: dict[str, str] = {}
            for page, tag in ((a.src, "full"), ("_lay", "lay"), ("_top", "top")):
                out = f"/tmp/vgate_{tag}_{lang}.png"
                shot(f"file://{V}/{page}.html?lang={lang}&state={a.state}", out)
                frames[tag] = out
            x, y, w, h = bbox_strong(frames["full"])
            # check_overlay 一律经 uv run 调（AGENTS.md uv 统一；它自身在缺
            # numpy 时也会 execvp 到 uv 重跑，这里直接给足环境省一次重入）
            r = subprocess.run(
                ["uv", "run", "--project", str(usine), "python", str(overlay),
                 frames["lay"], frames["top"], str(x), str(y), str(w), str(h),
                 "--scale", str(a.dsf), "--dilate", str(a.dilate),
                 "--red", a.red, "--blue", a.blue], capture_output=True, text=True)
            lines = (r.stdout or "").strip().splitlines()
            last = lines[-1] if lines else f"check_overlay 无输出（{r.stderr.strip()[:80]}）"
            print(f"{lang}: {last}")
            if "PASS" not in (r.stdout or "") or r.returncode != 0:
                fails.append(lang)
    finally:
        (V / "_lay.html").unlink(missing_ok=True)
        (V / "_top.html").unlink(missing_ok=True)
    if fails:
        sys.exit(f"视频双层对齐 FAIL: {fails} —— .stack 规则多半被样式块里的杂行吞了"
                 f"（看 korean.css），或双层结构数据有错")
    print(f"视频双层对齐: {len(langs)}/{len(langs)} PASS")


if __name__ == "__main__":
    main()
