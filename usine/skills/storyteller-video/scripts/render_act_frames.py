#!/usr/bin/env python3
"""render_act_frames.py — 评书幕帧渲染器（storyteller-video 的导演层实现）。

舞台模型（茶馆书场，一个连贯空间，不是图层拼贴）：
  墙面（prerender_bg 渐变 + 幕 scene 注册表道具，identity 调色）
    → 挂木匾（幕名：章 + 回目）
    → 说书人立绘半身近景（rig.draw_character，幕 pose/mood；可见身高
      ≈53%，是画面主角）站在案后，双手搭案沿
    → 说书案（案沿遮住腰下；台上摆醒木与折扇），台口护墙板挡掉
      低处背景道具
    → 案上摊开的唱词书卷（卡拉OK文字长在卷面上，卷在人物身前）
    → 镜头变换最后作用于整幅合成（文字随画面一起动）。
  姿态约束：近景下手臂展开 ±370 原生像素，唱词只能放前景案面
  （竖挂幡会被 point / palm_open 手势扫到）；拍案手用 fist
  （clap 在近景下双手出框）。

每幕渲染三类帧（帧名 = karaoke-video build 的探针契约）：
  <act>-pre.png   幕首（全暗，preroll）
  <act>-<k>.png   词状态帧（第 k 个 token 点亮）
  <act>-done.png  幕尾（全亮）

字卡页由本脚本从 TTS meta（text/tokens）+ 幕表（chapter/subtitle/quote）
自生成（黑底纯文字层，Edge headless 截图渲染，Pillow 只合成——
raqm=False 纪律：Pillow 不画字；?lang=zh-<act>&state=<n> 契约不变）。

确定性：镜头插值与人物 t 全部由帧序号驱动（同参数重渲逐字节一致）。
醒木音（gavel.wav）由本脚本 synth_gavel() 生成，assemble_storyteller.py 混入。

用法：
  uv run --project usine python render_act_frames.py acts.json out_frames_dir \
      [--act a1] [--fps 30]
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _resolve(name):
    """外部可执行文件经 library 的 platform resolver（AGENTS.md 硬约定 1）。"""
    from feuille import platform
    got = getattr(platform, name)() or ""
    if not got:
        sys.exit(f"找不到 {name}（feuille.platform 解析）")
    return got


FFMPEG = None   # main() 里懒解析（import 期零依赖）
FFPROBE = None

# ---- 舞台几何（单一事实源：Pillow 绘制与字卡 HTML 坐标由同一份常量注入）----
GEO = {
    "beam":   (0, 0, 1080, 90),        # 顶梁
    "plaque": (330, 300, 750, 470),    # 木匾（幕名）
    "ptext":  (340, 312, 740, 462),    # 匾内文字区（HTML 同源）
    "panel":  (0, 1450, 1080, 1540),   # 台口护墙板（挡低处道具）
    "slab":   (0, 1540, 1080, 1630),   # 案沿（说书人双手搭在案沿上）
    "skirt":  (0, 1630, 1080, 1920),   # 案身前脸（书卷后面）
    "roll_l": (30, 1620, 78, 1915),    # 书卷左卷尾
    "roll_r": (1002, 1620, 1050, 1915),# 书卷右卷尾
    "paper":  (60, 1630, 1020, 1905),  # 案上摊开的唱词书卷
    "ktext":  (90, 1645, 990, 1872),   # 卷面唱词文字区（HTML 同源）
    "quote":  (100, 1878, 980, 1900),  # 卷面原文摘录行（有 quote 才有）
}
# 说书人站位：face_geo 原生 ground=1700、头顶≈962（wide 脸型）。
# scale 1.75 + yoff 180 + xoff −135（中轴 405）→ 头顶（含发）≈521、
# 双手≈1567 恰在案沿 1540 之上；可见身高 521→1540 ≈ 53%（>45%）。
# 姿态手臂展开上限 ±370 原生像素（point 最长）：135+1.75·370≈1056 < 1080，
# 左手 405−1.75·224≈13 > 0——所有姿态都留在画框内。
ACTOR_X, ACTOR_Y, ACTOR_S = -135.0, 180.0, 1.75

# 字卡文字实色（与 matte_unpremultiply 色表一致，勿单边改）。
# dim 态用实色暗字而不用 CSS opacity：字卡页是纯黑底，半透明墨字会被
# 黑底压暗（obs = a·墨），matte 无法与"深色文字"区分——dim 与 sung 分不清。
INK, GOLD, MUT, DIM, VOWEL = ((44, 36, 24), (184, 134, 11), (138, 124, 98),
                              (196, 188, 170), (176, 85, 46))
PAPER = (242, 234, 216)


def shot_transform(shot, n_frames, fps, w=1080):
    """帧序 → (scale, xoff, yoff)。kind ∈ push|pull|pan_l|pan_r|static。

    ease = smoothstep：两端一阶导 0（与 rig 的 smoothstep 同式，Ken Burns
    不抖）。pan 的位移量 = 画布宽 4% 的行程，方向由 kind 定。
    """
    kind = (shot or {}).get("kind", "static")
    s0 = float((shot or {}).get("start", 1.0))
    s1 = float((shot or {}).get("end", 1.0))
    if kind == "pull":
        s0, s1 = s1, s0
    if kind == "static":
        s0 = s1 = 1.0
    # 画布满幅纪律：行程 <1 的端点镜像到 ≥1（zoom-out 语义 = 主体变小，画布不露底）
    if s0 < 1.0 or s1 < 1.0:
        lo = min(s0, s1)
        s0, s1 = s0 + (1 - lo) * 2, s1 + (1 - lo) * 2
    out = []
    for k in range(n_frames):
        u = k / max(1, n_frames - 1)
        e = u * u * (3 - 2 * u)
        scale = s0 + (s1 - s0) * e
        xoff = 0.0
        if kind == "pan_l":
            xoff = 0.04 * w * (1 - 2 * e)
        elif kind == "pan_r":
            xoff = -0.04 * w * (1 - 2 * e)
        out.append((scale, xoff, 0.0))
    return out


def synth_gavel(path: pathlib.Path, fps: int):
    """醒木声：60ms 低频正弦（150Hz→70Hz 扫频）× 指数衰减 + 3ms 噪声瞬态。

    纯库内合成器（sine/anoisesrc 滤波组，无额度、无外部依赖）。峰值 ≈ −3 dBFS。
    """
    flt = (
        "sine=frequency=150:duration=0.06[s1];"
        "sine=frequency=70:duration=0.06[s2];"
        "[s1][s2]amix=inputs=2:normalize=0[drone];"
        "anoisesrc=color=brown:duration=0.004:amplitude=0.9[nz];"
        "[nz]adelay=0|0,apad=whole_dur=0.06[trans];"
        "[drone][trans]amix=inputs=2:normalize=0,"
        "afade=t=out:st=0.004:d=0.056:curve=exp,"
        "volume=0.7,apad=whole_dur=0.25"
    )
    subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                    "-filter_complex", flt, "-ar", "48000", "-ac", "1",
                    str(path)], check=True)


def render_word_card(html_path: pathlib.Path, png: pathlib.Path, w: int, h: int,
                     query: str, browser: str):
    """字卡层截图（Edge headless，library 参数组：不带 user-data-dir）。"""
    url = f"file://{html_path.resolve()}{query}"
    subprocess.run([browser, "--headless=new", "--disable-gpu",
                    "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={w},{h}", "--screenshot=" + str(png),
                    "--virtual-time-budget=10000", url],
                   check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not png.exists():
        sys.exit(f"字卡渲染失败：{png}")


def matte_unpremultiply(png: pathlib.Path):
    """黑底字卡 → RGBA 文字层（字卡页全部实色已知，按色表分解 matte）。

    headless screenshot 永远输出不透明图（transparent body 会被填底），
    所以字卡页用纯黑底渲染：文字全部实色（含 dim 态——opacity 会与黑底
    混色、matte 分不清深浅），每像素必是色表色（墨/金/灰/暗字）之一，
    距色表色过远（≈黑底）视为透明，其余 alpha=255 取最近色表色。
    """
    from PIL import Image
    import numpy as np
    im = np.asarray(Image.open(png).convert("RGB"), dtype=np.float64)
    pal = np.array([INK, GOLD, MUT, DIM, VOWEL, PAPER], dtype=np.float64)
    d = np.linalg.norm(im[:, :, None, :] - pal[None, None, :, :], axis=3)
    nearest = d.argmin(axis=2)
    ndist = d.min(axis=2)
    alpha = np.clip(255.0 - ndist, 0, 255)
    alpha[im.max(axis=2) < 20] = 0        # 纯黑基底 = 透明
    color = pal[nearest]
    return Image.fromarray(
        np.dstack([color.astype(np.uint8), alpha.astype(np.uint8)]), "RGBA")


def build_card_html(card_acts, fonts_css: str) -> str:
    """自生成字卡页：黑底 + 每幕一节（匾文 + 卷面唱词），绝对定位坐标与
    Pillow 舞台几何同源（GEO 注入）。card_acts = [(act, text, toks), …]。

    按词序切开正文 text：与 token 文本逐段匹配，token 之间的字符
    （标点/空白）一律 .pun（常暗，充当分隔）。

    状态契约不变：?lang=zh-<act>&state=N
      state<0 → 全 dim；0<N<len → 前 N 个 token 亮（最新一个金色 .cur）；
      N≥len → 全亮。字卡只出文字层，匾/卷/案等形状由 Pillow 画。
    字体用系统楷体（Kaiti SC）——项目 fonts.css 的 OBS SC 子集是旧字卡页
    的字体（用户判为难看），楷体才是评书面相；fonts.css 仍注入（字符集
    子集化的门留着），但 font-family 不再引用 OBS SC。
    """
    tmpl = """<!doctype html><html><head><meta charset="utf-8"><style>
__FONTS__
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1080px; height:1920px; background:#000;
  font-family:'Kaiti SC','STKaiti','Songti SC',serif; }
section.act { display:none; }
section.act.on { display:block; }
.plaque { position:absolute; left:{ptx}px; top:{pty}px; width:{ptw}px; height:{pth}px;
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; }
.plaque .ch { font-size:52px; font-weight:700; color:#2c2418; letter-spacing:10px; }
.plaque .sub { font-size:28px; color:#b8860b; letter-spacing:12px; }
.sheet { position:absolute; left:{ktx}px; top:{kty}px; width:{ktw}px; height:{kth}px;
  overflow:hidden; }
.ktext { font-size:36px; line-height:1.6; color:#2c2418;
  text-align:justify; text-justify:inter-ideograph; }
.ktext .tok.dim, .ktext .pun { color:#c4bcaa; }
.ktext .tok.sung { color:#2c2418; }
.ktext .tok.vow.sung { color:#b0552e; }
.ktext .tok.cur, .ktext .tok.vow.cur { color:#b8860b; }
.quote { position:absolute; left:{qtx}px; top:{qty}px; width:{qtw}px; height:{qth}px;
  font-size:20px; color:#8a7c62; text-align:center; }
</style></head><body>
__SECTIONS__
<script>
(function () {
  var q = new URLSearchParams(location.search);
  var lang = q.get('lang') || '';
  var state = parseInt(q.get('state') || '-1', 10);
  var sec = document.getElementById('s-' + lang);
  if (!sec) return;
  sec.classList.add('on');
  var kt = sec.querySelector('.ktext');
  // 自适应：正文超长时逐 2px 缩字号装进卷面（只依赖文本，逐状态确定）
  for (var fs = 36; fs > 22 && kt.scrollHeight > kt.clientHeight; fs -= 2)
    kt.style.fontSize = fs + 'px';
  var n = parseInt(sec.dataset.n || '0', 10);
  sec.querySelectorAll('.tok').forEach(function (el) {
    var i = parseInt(el.dataset.i || '0', 10);
    el.classList.remove('dim', 'sung', 'cur');
    if (isNaN(state) || state < 0) el.classList.add('dim');
    else if (state >= n) el.classList.add('sung');
    else if (i < state) el.classList.add(i === state - 1 ? 'cur' : 'sung');
  });
})();
</script></body></html>
"""

    def px(k):
        x0, y0, x1, y1 = GEO[k]
        return str(x0), str(y0), str(x1 - x0), str(y1 - y0)

    ptx, pty, ptw, pth = px("ptext")
    ktx, kty, ktw, kth = px("ktext")
    qtx, qty, qtw, qth = px("quote")

    body_secs = []
    for act, text, toks in card_acts:
        vow = set(act.get("vowel") or [])
        spans, i, pos = [], 0, 0
        while pos < len(text):
            if i < len(toks) and text.startswith(toks[i]["text"], pos):
                cls = "tok dim vow" if toks[i]["text"] in vow else "tok dim"
                spans.append(f'<span class="{cls}" data-i="{i}">'
                             f'{html_mod.escape(toks[i]["text"])}</span>')
                pos += len(toks[i]["text"])
                i += 1
            else:
                spans.append(f'<span class="pun">{html_mod.escape(text[pos])}</span>')
                pos += 1
        ch = html_mod.escape(act.get("chapter") or "评书")
        sub = html_mod.escape(act.get("subtitle") or "")
        quote = html_mod.escape(act.get("quote") or "")
        qdiv = f'<div class="quote">{quote}</div>' if quote else ""
        body_secs.append(
            f'<section class="act" id="s-zh-{act["id"]}" data-n="{len(toks)}">\n'
            f'<div class="plaque"><div class="ch">{ch}</div>'
            f'<div class="sub">{sub}</div></div>\n'
            f'<div class="sheet"><div class="ktext">{"".join(spans)}</div></div>\n'
            f'{qdiv}\n</section>')
    return (tmpl
            .replace("__FONTS__", fonts_css or "")
            .replace("__SECTIONS__", "\n".join(body_secs))
            .replace("{ptx}", ptx).replace("{pty}", pty)
            .replace("{ptw}", ptw).replace("{pth}", pth)
            .replace("{ktx}", ktx).replace("{kty}", kty)
            .replace("{ktw}", ktw).replace("{kth}", kth)
            .replace("{qtx}", qtx).replace("{qty}", qty)
            .replace("{qtw}", qtw).replace("{qth}", qth))


def draw_stage_back(d, mix, SCENE, ident):
    """墙侧舞台层（人物身后）：顶梁 / 台口护墙板 / 木匾。"""
    beam, panel = GEO["beam"], GEO["panel"]
    beam_w = mix(SCENE["wood"], (40, 30, 20), 0.45)
    d.rectangle(list(beam), fill=beam_w)
    d.rectangle([beam[0], beam[3] - 12, beam[2], beam[3]], fill=mix(beam_w, (0, 0, 0), 0.25))

    # 台口护墙板：顶亮条（横枋）+ 板缝
    x0, y0, x1, y1 = panel
    panel_c = mix(SCENE["wood"], (52, 38, 26), 0.35)
    d.rectangle([x0, y0, x1, y1], fill=panel_c)
    d.rectangle([x0, y0, x1, y0 + 34], fill=mix(SCENE["wood2"], panel_c, 0.35))
    for yy in range(y0 + 90, y1, 68):
        d.line([x0, yy, x1, yy], fill=mix(panel_c, (0, 0, 0), 0.18), width=3)

    # 木匾（幕名）：吊索 + 匾板 + 右下投影
    px0, py0, px1, py1 = GEO["plaque"]
    for cx in (px0 + 40, px1 - 40):
        d.line([cx, beam[3], cx, py0 + 14], fill=SCENE["lamp"], width=4)
    d.rounded_rectangle([px0 + 6, py0 + 10, px1 + 6, py1 + 10], 14, fill=(0, 0, 0, 60))
    d.rounded_rectangle([px0, py0, px1, py1], 14, fill=mix(PAPER, ident, 0.08))
    d.rounded_rectangle([px0, py0, px1, py1], 14,
                        outline=mix(SCENE["wood"], (0, 0, 0), 0.25), width=8)

    # 卷轴幡已下台：唱词改躺在案面书卷上（见 draw_stage_front），
    # 墙侧到此为止——半身近景下墙面只留匾，干净不抢戏。


def draw_stage_front(d, mix, SCENE, ident):
    """台前层（人物身前）：案沿窄条（双手搭上面）+ 案身 + 案上摊开的
    唱词书卷（卷尾圆柱 + 卷面纸）+ 醒木 + 折扇。"""
    slab, skirt = GEO["slab"], GEO["skirt"]
    sx0, sy0, sx1, sy1 = slab
    slab_c = mix(SCENE["wood2"], (150, 110, 70), 0.55)
    d.rectangle([sx0, sy0, sx1, sy1], fill=slab_c)
    d.rectangle([sx0, sy0, sx1, sy0 + 12], fill=mix(slab_c, (0, 0, 0), 0.22))  # 案沿暗线
    # 说书人双手落在案沿：条面上一道柔和接触影，把人和案锁在一起
    d.ellipse([180, sy0 + 4, 640, sy0 + 26], fill=(0, 0, 0, 26))
    # 案身前脸：竖板缝（两侧从书卷后露出）
    kx0, ky0, kx1, ky1 = skirt
    skirt_c = mix(SCENE["wood"], (34, 24, 16), 0.42)
    d.rectangle([kx0, ky0, kx1, ky1], fill=skirt_c)
    for xx in range(kx0 + 90, kx1, 150):
        d.line([xx, ky0, xx, ky1], fill=mix(skirt_c, (0, 0, 0), 0.20), width=4)
    # 书卷卷尾（左右两根立着的卷轴圆柱，比卷面高出一线）
    rod_c = mix(SCENE["wood"], (28, 20, 14), 0.4)
    for (rx0, ry0, rx1, ry1) in (GEO["roll_l"], GEO["roll_r"]):
        d.rounded_rectangle([rx0 + 5, ry0 + 10, rx1 + 5, ry1 + 10], 16, fill=(0, 0, 0, 46))
        d.rounded_rectangle([rx0, ry0, rx1, ry1], 16, fill=rod_c)
        d.line([(rx0 + rx1) // 2 - 4, ry0 + 16, (rx0 + rx1) // 2 - 4, ry1 - 6],
               fill=mix(rod_c, (120, 90, 55), 0.30), width=6)
        d.ellipse([rx0 + 2, ry0 - 8, rx1 - 2, ry0 + 30],
                  fill=mix(rod_c, (200, 170, 130), 0.22))          # 卷口螺旋端面
    # 卷面（摊开的宣纸）：卷口顶缘阴影 + 右下投影感（底缘暗线）
    px0, py0, px1, py1 = GEO["paper"]
    d.rectangle([px0, py0, px1, py1], fill=mix(PAPER, ident, 0.05))
    d.rectangle([px0, py0, px1, py0 + 8], fill=mix(PAPER, (0, 0, 0), 0.10))
    d.rectangle([px0, py1 - 6, px1, py1], fill=mix(PAPER, (0, 0, 0), 0.07))
    # 醒木（案沿条上左）：底影 + 木块 + 顶面亮
    d.ellipse([146, 1598, 252, 1614], fill=(0, 0, 0, 40))
    d.rounded_rectangle([150, 1562, 242, 1600], 8, fill=mix(SCENE["wood"], (20, 14, 10), 0.30))
    d.rounded_rectangle([154, 1566, 238, 1580], 6, fill=mix(SCENE["wood2"], (60, 45, 30), 0.2))
    # 折扇（案沿条上右）：扇柄 + 纸面 + 细骨线
    d.ellipse([838, 1602, 964, 1620], fill=(0, 0, 0, 40))
    d.rounded_rectangle([840, 1574, 862, 1594], 6, fill=mix(SCENE["wood"], (20, 14, 10), 0.30))
    d.rounded_rectangle([846, 1565, 950, 1602], 10, fill=mix(PAPER, (200, 190, 170), 0.35))
    for xx in range(866, 946, 12):
        d.line([xx, 1570, xx, 1598], fill=mix(MUT, (0, 0, 0), 0.05), width=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acts_json")
    ap.add_argument("out_dir")
    ap.add_argument("--act", default=None, help="只渲这一幕（迭代用）")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    from feuille import rig, scenes
    from feuille.data import storytellers
    from PIL import Image, ImageDraw
    from feuille.rig import SCENE, hexc, mix

    cfg = json.loads(pathlib.Path(args.acts_json).read_text())
    st = storytellers().get(cfg.get("storyteller_id", "changlianke"))
    if not st:
        sys.exit("storyteller.json 里没有这个说书人 id")
    ident = hexc(st["identity"])
    fps = args.fps
    W, H = cfg["formats"][0]["w"], cfg["formats"][0]["h"]
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    from feuille import platform
    browser = platform.browser_path()
    global FFMPEG, FFPROBE
    FFMPEG, FFPROBE = _resolve("ffmpeg"), _resolve("ffprobe")
    if not browser:
        sys.exit("找不到 Chromium 系浏览器（feuille.platform）")

    # 醒木音（一次）
    gavel_path = out / "gavel.wav"
    if not gavel_path.exists():
        synth_gavel(gavel_path, fps)
        print("  gavel.wav 合成完毕")

    acts = cfg["acts"]
    if args.act:
        acts = [a for a in acts if a["id"] == args.act]
        if not acts:
            sys.exit(f"--act {args.act}: 幕表里没有")

    here = pathlib.Path(args.acts_json).resolve().parent
    timing = cfg.get("timing", {})
    preroll = float(timing.get("preroll", 0.8))
    tts_dir = here / "tts"
    import subprocess as sp

    # ---- 字卡页（一次生成：TTS meta 的 text/tokens + 幕表章回）----
    card_acts = []
    for act in acts:
        cand = [tts_dir / f"{act['id']}.json", tts_dir / f"zh-{act['id']}.json"]
        meta_p = next((c for c in cand if c.exists()), None)
        if not meta_p:
            sys.exit(f"缺 TTS 产物 {cand[0]}（先跑 karaoke-video 的 gen_tts.py）")
        meta = json.loads(meta_p.read_text())
        card_acts.append((act, meta["text"], meta["tokens"]))
    fonts_p = here / "fonts.css"
    fonts_css = fonts_p.read_text() if fonts_p.exists() else ""
    cards_dir = out / "_cards"
    cards_dir.mkdir(exist_ok=True)
    build_html = cards_dir / "src.html"
    build_html.write_text(build_card_html(card_acts, fonts_css))
    print(f"  字卡页自生成：{build_html}")

    for act, text, toks in card_acts:
        act_id = act["id"]
        locale = "zh-" + act_id
        mp3_p = tts_dir / f"{locale}.mp3"
        adur = float(sp.run([FFPROBE, "-v", "quiet", "-show_entries",
                             "format=duration", "-of", "csv=p=0", str(mp3_p)],
                            capture_output=True, text=True).stdout.strip())
        # 帧数口径与 karaoke build 一致：preroll + Σ词段 + tail + done
        durs = [preroll]
        for i in range(len(toks)):
            d = (toks[i + 1]["start"] - toks[i]["start"] if i < len(toks) - 1
                 else (adur - toks[i]["start"]) + float(timing.get("tail", 0.8)))
            durs.append(math.ceil(d * fps - 1e-9) / fps)
        durs.append(float(timing.get("done", 0.5)))
        n_frames = sum(round(d * fps) for d in durs)

        # 背景墙面（每幕一次，按 identity 调色；低处道具由台口护墙板遮挡）
        bg = scenes.prerender_bg(st, {"scene": act["scene"]}).convert("RGBA")

        # 舞台静态层（墙侧/台前各一张，帧循环外缓存；SS=2 超采样抗锯齿）
        back = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
        draw_stage_back(scenes.DrawScaled(ImageDraw.Draw(back), 2), mix, SCENE, ident)
        back = back.resize((W, H), Image.Resampling.LANCZOS)
        front = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
        draw_stage_front(scenes.DrawScaled(ImageDraw.Draw(front), 2), mix, SCENE, ident)
        front = front.resize((W, H), Image.Resampling.LANCZOS)

        # 人物层（幕 pose/mood；blink 由帧序驱动——确定性）。
        # 站位见模块头注释：半身近景，双手搭案沿，唱词在身前卷面上。
        def actor_frame(t_sec, pose_override=None):
            pose_code = pose_override or act.get("pose", "both_hands")
            pose = {}
            if pose_code and pose_code in rig.POSE_CODES:
                u = (t_sec % 2.0) / 2.0
                pose = rig.pose_for(pose_code, u, t_sec, st)
                pose = {k: v for k, v in pose.items() if k in ("armL", "armR", "legL", "legR")}
            blink = (t_sec % st["movement"]["blinkCycleSec"]) < 0.12
            layer = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            ctx = dict(scale=ACTOR_S, xoff=ACTOR_X, yoff=ACTOR_Y, squash=0.0, xscale=1.0,
                       head_dx=0, head_dy=0, brow_lift_extra=0, pose=pose,
                       openness=0.0, blink=blink, mood=act.get("mood", "neutral"),
                       ss=2)
            rig.draw_character(layer, d, st, t_sec, ctx)
            return layer.resize((W, H), Image.Resampling.BOX)

        shot_frames = shot_transform(act.get("shot"), n_frames, fps, W)

        # 词边界 → 每帧该亮的 token 数
        boundaries = [round(preroll * fps)]
        acc = round(preroll * fps)
        for i, d in enumerate(durs[1:-1], 1):
            acc += round(d * fps)
            boundaries.append(acc)
        done_start = acc

        print(f"  {act_id}: {n_frames} 帧 ({n_frames/fps:.1f}s), scene={act['scene']}, "
              f"shot={act.get('shot', {}).get('kind', 'static')}")

        # 合成循环：墙 → 匾 → 人物 → 案+卷 → 卷面/匾内文字 → 镜头（整帧）
        for k in range(n_frames):
            scale, sx, sy = shot_frames[k]
            t_sec = k / fps
            state = -1 if k < boundaries[0] else (
                len(toks) if k >= done_start else
                max(i for i, b in enumerate(boundaries) if k >= b))
            frame = bg.copy()
            frame.alpha_composite(back)
            # 人物（拍案手 pose 在幕首 1.2s 内用 gavel 拍案 pose）
            pose_code = act.get("pose", "both_hands")
            if act.get("gavel") and k < round(1.2 * fps) and state < 1:
                pose_code = "fist"   # 拍案手（clap 近景下双手出框，fist 不出）
            frame.alpha_composite(actor_frame(t_sec, pose_code))
            frame.alpha_composite(front)
            # 卷面/匾内文字：按 state 取缓存截图（?lang&state 契约），matte 后
            # 合成——文字长在人物身前的卷面/匾面上，与舞台一体
            key = f"{act_id}-{state if state >= 0 else 'pre'}"
            card_cache = cards_dir / f"{key}.png"
            if not card_cache.exists():
                q = f"?lang={locale}&state={state}"
                render_word_card(build_html, card_cache, W, H, q, browser)
            frame.alpha_composite(matte_unpremultiply(card_cache))
            # 镜头最后作用于整幅合成（文字长在卷面上，随画面一起动）。
            # 行程一律锁 ≥1.0：画布满幅不露底（zoom-out 语义 = 主体变小）。
            if abs(scale - 1.0) > 1e-3 or abs(sx) > 1e-3:
                eff = max(scale, 1.0)
                sw, sh = int(W * eff), int(H * eff)
                big = frame.resize((sw, sh), Image.Resampling.LANCZOS)
                ox = int((sw - W) / 2 + sx)
                oy = int((sh - H) / 2 + sy)
                ox = max(0, min(sw - W, ox)); oy = max(0, min(sh - H, oy))
                frame = big.crop((ox, oy, ox + W, oy + H))
            frame.convert("RGB").save(out / f"f{act_id}-{k:04d}.png")
        print(f"  {act_id}: 帧序列写完")


if __name__ == "__main__":
    main()
