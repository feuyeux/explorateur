# -*- coding: utf-8 -*-
"""小红书封面：1080×1440（3:4，小红书推荐比例），每条视频一张。

**为什么走 Edge headless**：和字幕同因——本机 ffmpeg 无 libass，且 24 张封面的中文标题
要用宋体排版，浏览器一次截图就对（`textlayer.edge_screenshot`，不透明成图，
自带视口亏空补偿与裁齐）。

**封面取哪一帧**：不是随手抓帧，是**跟着每条文案的主题季走**——文案写秋就用秋那帧，
写冬就用冬那帧，图和文对得上。封面配错季是这类内容最常见也最扎眼的失误。

**帧的取样点**（四季窗口中点，取样时实测过画面内容）：
    春 2.6s · 夏 7.8s · 秋 11.9s · 冬 16.7s
"""
from __future__ import annotations

import json
import re
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
from 配文 import LANGS                                # noqa: E402
import 季节与译文 as meta                              # noqa: E402

W, H = 1080, 1440                                    # 3:4，小红书封面推荐比例
# B 站是 4:3（1080×810），比 3:4 **矮 43%**。实测：把 3:4 封面直接交给 B 站，
# 它按4:3 居中裁切后**标题整块消失**（文字底部锚定，裁切窗口落在上半部）。
# 所以 B 站**必须单独出一版 4:3**，不能靠平台裁。
WB, HB = 1080, 810                                   # 4:3，B 站封面原生比例
SHOT = {"春": 2.6, "夏": 7.8, "秋": 11.9, "冬": 16.7}
FRAMES = HERE / "cover_frames"
OUT = HERE / "封面"
OUT_BILI = HERE / "封面_bili"

# 每条文案对应的**主题季**（跟着标题走，不均分）
SEASON_OF = {
    1: "春", 2: "夏", 3: "秋", 4: "夏", 5: "秋", 6: "春", 7: "秋", 8: "秋",
    9: "秋", 10: "秋", 11: "秋", 12: "冬",
    13: "冬", 14: "冬", 15: "夏", 16: "冬", 17: "冬", 18: "秋", 19: "夏",
    20: "夏", 21: "春", 22: "冬", 23: "冬", 24: "秋",
}
# 标题里出现过该语种季词的一并标上（副信息，不抢标题）
NATIVE_SEASON = {
    "中文": "春", "英语": "Spring", "德语": "Herbst", "法语": "Automne",
    "西班牙语": "Otoño", "俄语": "Осень", "希腊语": "Φθινόπωρον",
    "阿拉伯语": "الخريف", "希伯来语": "סתיו", "印地语": "शरद",
    "日语": "紅葉", "韩语": "가을",
}

TITLE_FONT = "'Songti SC', 'STSong', 'Songti TC', serif"

# 底部锚定偏移 + 视口亏空补偿（见 COVER_BILI 里 .row 的注释）。
# 亏空量与 canvas_h 无关（实测 810 与 1440 都是 84），这里探一次缓存住，
# 不在每张封面里重复探——12 张 × 一次 headless 探测是几十秒的浪费。
BOTTOM = 56
_VP: list[int] = []


def deficit() -> int:
    """视口亏空（px）。实测 macOS headless Edge = 84，与 canvas_h 无关。"""
    if not _VP:
        d, _ = textlayer.viewport_deficit(1440, workdir=OUT_BILI)
        _VP.append(d)
        print(f"  ℹ️ 视口亏空实测 {d}px，已计入底部偏移")
    return _VP[0]

COVER = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:#0b0b0d;}}
.bg{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;}}
.bg img{{width:100%;height:100%;object-fit:cover;display:block;}}
/* 底部主压暗 + 顶部轻压暗：文字区落在暗部，画面中段留亮 */
.scrim{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;
background:linear-gradient(to top, rgba(6,7,9,.88) 0%, rgba(6,7,9,.70) 24%,
rgba(6,7,9,.26) 50%, rgba(6,7,9,0) 70%);}}
.cap{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;
background:linear-gradient(to bottom, rgba(6,7,9,.46) 0%, rgba(6,7,9,0) 20%);}}
.pill{{position:absolute;left:76px;top:76px;font-family:{tf};font-size:31px;font-weight:400;
letter-spacing:.24em;text-indent:.24em;color:rgba(255,255,255,.92);
padding:15px 30px;border:1px solid rgba(255,255,255,.40);border-radius:999px;}}
/* 文字块**底部锚定**并向上生长：标题 1 行 / 2 行时，季名—细线—标题的间距始终一致。
   逐个元素绝对定位做不到这点（第二行标题会顶到细线上）。 */
.block{{position:absolute;left:76px;right:76px;bottom:118px;}}
.season{{font-family:{tf};font-size:38px;font-weight:400;letter-spacing:.42em;
text-indent:.42em;color:{sc};line-height:1;margin-bottom:26px;
text-shadow:0 2px 18px rgba(0,0,0,.75);}}
.rule{{width:104px;height:3px;background:{sc};opacity:.92;margin-bottom:34px;}}
.title{{font-family:{tf};font-size:74px;font-weight:600;line-height:1.30;color:#fff;letter-spacing:.01em;
text-shadow:0 4px 26px rgba(0,0,0,.78),0 1px 3px rgba(0,0,0,.5);}}
</style></head><body>
<div class="bg"><img src="{src}"></div>
<div class="scrim"></div><div class="cap"></div>
<div class="pill">{pill}</div>
<div class="block">
<div class="season">{season}</div><div class="rule"></div>
<div class="title">{title}</div>
</div>
</body></html>"""

# B 站 4:3 版式：文字块左下角**横向**排布，字号按 810px 高压小一档。
# 不用底部居中的窄版式——4:3 只有 1080 宽，窄版式会让长标题折成 3 行挤爆高度。
COVER_BILI = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:#0b0b0d;}}
.bg{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;}}
.bg img{{width:100%;height:100%;object-fit:cover;display:block;}}
.scrim{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;
background:linear-gradient(to top, rgba(6,7,9,.90) 0%, rgba(6,7,9,.72) 30%,
rgba(6,7,9,.26) 58%, rgba(6,7,9,0) 76%);}}
.cap{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;
background:linear-gradient(to bottom, rgba(6,7,9,.44) 0%, rgba(6,7,9,0) 22%);}}
.pill{{position:absolute;left:58px;top:50px;font-family:{tf};font-size:27px;font-weight:400;
letter-spacing:.22em;text-indent:.22em;color:rgba(255,255,255,.92);
padding:11px 24px;border:1px solid rgba(255,255,255,.40);border-radius:999px;}}
/* 横向行：季名 · 细线 · 标题 同一行，底部锚定。4:3 高度只够一行主标题。 */
/* ⚠️ 底部偏移必须加上 viewport 亏空（实测 macOS headless Edge 亏空 84px）：
   edge_screenshot 的窗口高 = canvas_h + 亏空，截图再裁回 canvas_h。
   视口比画布高 84px 时，`bottom:56px` 会把元素压到画布**外** 84px 处，
   裁完正好切掉底部文字。`{bo}` 已把亏空补进偏移量。
   这不是 B 站独有——3:4 那版能正常是因为字号大、底部留白够厚。 */
.row{{position:absolute;left:58px;right:58px;bottom:{bo}px;display:flex;
align-items:baseline;gap:24px;}}
.season{{font-family:{tf};font-size:34px;font-weight:400;letter-spacing:.34em;
text-indent:.34em;color:{sc};line-height:1;white-space:nowrap;
text-shadow:0 2px 16px rgba(0,0,0,.75);}}
.rule{{width:78px;height:3px;background:{sc};opacity:.92;flex:0 0 auto;
transform:translateY(-9px);}}
.title{{font-family:{tf};font-size:56px;font-weight:600;line-height:1.22;color:#fff;
letter-spacing:.01em;text-shadow:0 4px 24px rgba(0,0,0,.80),0 1px 3px rgba(0,0,0,.5);}}
</style></head><body>
<div class="bg"><img src="{src}"></div>
<div class="scrim"></div><div class="cap"></div>
<div class="pill">{pill}</div>
<div class="row">
<div class="season">{season}</div><div class="rule"></div>
<div class="title">{title}</div>
</div>
</body></html>"""


def titles() -> list[tuple[str, str]]:
    """从 小红书文案.md 里读标题与语种，避免两处各抄一份。"""
    md = (HERE / "小红书文案.md").read_text("utf-8")
    out, cur = [], None
    for line in md.splitlines():
        m = re.match(r"^## \d+ · (.+)$", line)
        if m:
            cur = m.group(1).strip()
        elif cur and line.startswith("**标题**："):
            out.append((cur, line.split("：", 1)[1].strip()))
            cur = None
    if len(out) != 24:
        raise RuntimeError(f"文案标题数应为 24，实读 {len(out)}")
    return out


def frame(lang: str, orient: str, season: str, *, size=(W, H)) -> Path:
    """从**无字幕母版**里抽该季代表帧（已按目标比例裁好，浏览器只管 object-fit）。

    ⚠️ 这里必须用 `_20s.mp4` 而不是成片 `_中文.mp4`：成片已经烧了季名、配文、译文三层字，
    再叠封面标题就成了两层字打架（踩过——第一版抽帧抽自成片，封面上一屏挤了四行文字）。
    封面要的是干净画面 + 重新排版的标题。

    缓存文件名带尺寸，避免 4:3 与 3:4 共用一个缓存文件导致拿到错的裁切。
    """
    fw, fh = size
    FRAMES.mkdir(exist_ok=True)
    png = FRAMES / f"{orient}.{season}.{fw}x{fh}.png"
    if not png.exists():
        src = HERE / f"{orient}四季_20s.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", str(SHOT[season]), "-i", str(src),
             "-frames:v", "1",
             "-vf", f"scale={fw}:{fh}:force_original_aspect_ratio=increase,"
                    f"crop={fw}:{fh}", str(png)],
            check=True, capture_output=True, text=True)
    return png


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(i: int, lang: str, orient: str, title: str) -> Path:
    season = SEASON_OF[i]
    sc = meta.SEASON_COLOR[season][0]
    html = COVER.format(
        w=W, h=H, tf=TITLE_FONT, sc=sc,
        src=frame(lang, orient, season).as_uri(),
        pill=esc(f"{lang} · {NATIVE_SEASON[lang]}"),
        season=esc(f"{season}"),
        title=esc(title),
    )
    png = OUT / f"{i:02d}_{orient}_{lang}.png"
    textlayer.edge_screenshot(html, png, width=W, canvas_h=H, workdir=OUT)
    return png


def build_bili(i: int, lang: str, title: str) -> Path:
    """B 站 4:3（1080×810）封面。只做**横版**（B 站投的就是横版成片）。"""
    orient = "横版"
    season = SEASON_OF[i]
    sc = meta.SEASON_COLOR[season][0]
    html = COVER_BILI.format(
        w=WB, h=HB, tf=TITLE_FONT, sc=sc,
        bo=BOTTOM + deficit(),
        src=frame(lang, orient, season, size=(WB, HB)).as_uri(),
        pill=esc(f"{lang} · {NATIVE_SEASON[lang]}"),
        season=esc(f"{season}"),
        title=esc(title),
    )
    png = OUT_BILI / f"{i:02d}_{orient}_{lang}.png"
    textlayer.edge_screenshot(html, png, width=WB, canvas_h=HB, workdir=OUT_BILI)
    return png


def main() -> int:
    only = {int(x) for x in sys.argv[1:] if x.isdigit()}
    ts = titles()
    # --bili 只出 B 站 4:3 的横版封面（1–12 条）
    if "--bili" in sys.argv:
        OUT_BILI.mkdir(exist_ok=True)
        n = 0
        for i, (lang, title) in enumerate(ts, start=1):
            if i > 12:
                continue
            if only and i not in only:
                continue
            p = build_bili(i, lang, title)
            print(f"  {i:2d} 4:3 {lang:<6}{p.name}")
            n += 1
        print(f"\n共 {n} 张 B 站封面 · {WB}×{HB}（4:3）· 目录 {OUT_BILI.name}/")
        return 0

    OUT.mkdir(exist_ok=True)
    for i, (lang, title) in enumerate(ts, start=1):
        if only and i not in only:
            continue
        orient = "横版" if i <= 12 else "竖版"
        p = build(i, lang, orient, title)
        print(f"  {i:2d} {orient} {lang:<6}{p.name}")
    print(f"\n共 {len(ts)} 张封面 · {W}×{H}（3:4）· 目录 {OUT.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())