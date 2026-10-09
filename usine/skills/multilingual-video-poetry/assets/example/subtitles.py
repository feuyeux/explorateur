# -*- coding: utf-8 -*-
"""三层字幕渲染与烧录：季名（最大·上）／该语种配文（大）／中文译文（小·下）。

**为什么走 Edge headless 而不是 ffmpeg subtitles 滤镜**：本机 ffmpeg 未编 libass
（`ffmpeg -filters` 里没有 `subtitles`/`ass`）；且工作区铁律——Pillow `raqm=False`
无 HarfBuzz/FriBiDi，阿拉伯／希伯来／天城文会散字错向。Chromium 内核自带完整塑形，
一次截图就对。透明层用 `textlayer.shoot_matte`（白底/黑底双截 → 精确 alpha）。

**字体栈一律从 `languages/` 注册表现取**，不在本文件里另抄一份（纪律 7 / 10）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：HERE.parents[3] 才是 usine
# （examples/sijijie 原件里是 parent.parent）。uv run 下本行可省，留作无 uv 环境的引导。
USINE = HERE.parents[3]
sys.path.insert(0, str(USINE / "src"))
sys.path.insert(0, str(HERE))

from feuille import textlayer                          # noqa: E402
from 配文 import LANGS, LINES, SEASONS, TOTAL, WINDOWS  # noqa: E402
import 季节与译文 as meta                                # noqa: E402

ORIENTS = {"横版": (1280, 720), "竖版": (720, 1280)}


def lang_manifest(tag: str) -> dict:
    """字体栈 / 书写方向的**唯一事实源**是 languages/ 注册表。"""
    d = USINE / "languages" / tag
    for f in d.glob("*.json"):
        data = json.loads(f.read_text("utf-8"))
        if isinstance(data, dict) and "fontCss" in data:
            return data
    raise FileNotFoundError(f"languages/{tag} 无带 fontCss 的 manifest")


CARD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg};
-webkit-font-smoothing:antialiased;}}
.box{{position:absolute;left:0;right:0;text-align:center;direction:{dir};}}
/* 三层文字全部压在实拍画面上（亮天空 / 白雪），单层柔和阴影压不住，
   必须用「近距实边 + 中距晕开 + 远距散光」三层叠加才在任意底色上都读得出。 */
.season{{top:{sy}%;font-family:{sfont};font-size:{sfz}px;font-weight:300;letter-spacing:.34em;
text-indent:.34em; /* 抵消末位字距，否则整行看着偏左 */
color:{season_c};line-height:1;
text-shadow:0 2px 3px rgba(0,0,0,.45),0 3px 22px rgba(0,0,0,.55),0 10px 50px rgba(0,0,0,.4);}}
.line{{top:{ly}%;font-family:{lfont};font-size:{lfz}px;font-weight:400;color:{season_c};line-height:1.4;
padding:0 8%;letter-spacing:.04em;direction:{ldir};
text-shadow:0 2px 3px rgba(0,0,0,.5),0 3px 20px rgba(0,0,0,.6),0 8px 44px rgba(0,0,0,.42);}}
.zh{{top:{zy}%;font-family:{CJK};font-size:{zfz}px;font-weight:400;color:{zh_c};
line-height:1.4;direction:ltr;
text-shadow:0 1px 3px rgba(0,0,0,.55),0 2px 16px rgba(0,0,0,.6),0 6px 34px rgba(0,0,0,.45);}}
</style></head><body>
<div class="box season">{season}</div>
<div class="box line">{line}</div>
<div class="box zh">{zh}</div>
<script>document.body.offsetHeight;</script></body></html>"""


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_html(lang: str, season: str, w: int, h: int, bg: str) -> str:
    man = lang_manifest(meta.LANG_TAG[lang])
    portrait = h > w
    # 展示字体从注册表的 displayFontCss 取（末尾已接回原 fontCss 兜底）；
    # 季色从 季节与译文.SEASON_COLOR 取——两处都不是本文件另抄的副本。
    font = man.get("displayFontCss", man["fontCss"])
    season_c, zh_c = meta.SEASON_COLOR[season]
    return CARD.format(
        w=w, h=h, bg=bg, dir=man.get("dir", "ltr"),
        # 三层绝对定位：季名贴上，配文与译文落在下三分之一，避开树冠
        sfont=font, sfz=int(w * (0.086 if not portrait else 0.104)),
        sy=11,
        lfont=font, lfz=int(w * (0.046 if not portrait else 0.062)),
        ly=58 if not portrait else 62, ldir=man.get("dir", "ltr"),
        CJK="'Songti SC', 'STSong', 'Songti TC', serif", zfz=int(w * (0.027 if not portrait else 0.037)),
        zy=68 if not portrait else 73,
        season_c=season_c, zh_c=zh_c,
        season=esc(meta.SEASON_WORD[lang][season]),
        line=esc(LINES[lang][season]),
        zh=esc(meta.ZH[lang][season]),
    )


def render_cards(lang: str, orient: str) -> list[Path]:
    w, h = ORIENTS[orient]
    out_dir = HERE / "cards" / orient
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for season in SEASONS:
        png = out_dir / f"{lang}.{season}.png"
        if not png.exists():
            textlayer.shoot_matte(
                lambda bg, l=lang, s=season: build_html(l, s, w, h, bg),
                png, width=w, canvas_h=h, workdir=out_dir)
        paths.append(png)
    return paths


def burn(lang: str, orient: str, cards: list[Path]) -> Path:
    """把四张卡片按季窗口叠上去 —— **串行叠加同一条时间线**，不是拼接。

    踩过的坑：最早写成 `[0:v][c0]overlay...[v0]; ... [v3]concat=n=4:v=1:a=0`，
    可每个 `[v{i}]` 都是**完整 20 秒**的基础视频叠一张卡，concat 把它们首尾相接
    → 成片 4×20=80 秒、155 MB 起。正确做法是从 `[0:v]` 出发逐张串接：

        [0:v][c0]overlay=0:0:enable='between(t,s0,e0)'[v0]
        [v0][c1]overlay=0:0:enable='between(t,s1,e1)'[v1]
        [v1][c2]...[v2] [v2][c3]...[vout]

    `-t TOTAL` 是必需的：`-loop 1` 的卡片输入是无限流，不设上限 ffmpeg 不收尾。
    """
    src = HERE / f"{orient}四季_20s.mp4"
    dst = HERE / f"{orient}四季_{lang}.sub.mp4"
    w, h = ORIENTS[orient]
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    for p in cards:
        cmd += ["-loop", "1", "-i", str(p)]
    chains, prev = [], "0:v"
    for i, season in enumerate(SEASONS):
        w0, w1 = WINDOWS[season]
        s, e = max(0.0, w0), min(TOTAL, w1)
        chains.append(
            f"[{i + 1}:v]format=rgba,scale={w}:{h}[c{i}];"
            f"[{prev}][c{i}]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'"
            f":eof_action=pass[v{i}]")
        prev = f"v{i}"
    cmd += ["-filter_complex", ";".join(chains), "-map", f"[{prev}]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-t", f"{TOTAL:.3f}", "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 烧录失败 {dst.name}:\n{r.stderr[-2000:]}")
    return dst


def main() -> int:
    only = sys.argv[1:] or None
    langs = [l for l in LANGS if not only or l in only]
    n = 0
    for lang in langs:
        for orient in ORIENTS:
            cards = render_cards(lang, orient)
            out = burn(lang, orient, cards)
            print(f"  {lang:<6}{orient}  → {out.name}")
            n += 1
    print(f"\n已烧录 {n} 条（视频重编码 CRF 18，音轨 copy）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
