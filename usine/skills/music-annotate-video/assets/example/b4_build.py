"""B4 v2 工具：中文横版全片（欣赏版，9-10 分钟）。

v2 相对 v1 的扩充（用户反馈 2026-11-01：知识输入不够 / 聆听不持续 / 画面信息密度低）：
  1. 赏析知识：曲式（奏鸣曲式/三段式/谐谑曲）、《回家》填词史实（曲调在前、歌在后）、
     循环再现、E 大调收束（chroma 实测 G♯ 0.579 ≫ G 0.284）、升 c 小调中段（实测音高分布）。
  2. 持续聆听：每乐章 50-120s 连续录音，旁白只是插话（音乐 duck 到 0.25 不停）。
  3. 画面密度：波形/旋律场景改播放头推进态（波形 5s/态、旋律 2.5s/态，含时间码 +
     已播罩亮）；Largo 音符高亮扩到 120s（tracker 186-306 PASS：117 段、覆盖 76s）。

装配纪律与机器安全见 usine/skills/music-annotate-video/（SKILL.md + music-av-traps.md）。
"""
import json
import math
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
NOTES_OPEN = BASE / "notes" / "opening-notes.json"
NOTES_THEME = BASE / "notes" / "theme-notes.json"
A = BASE / "assets"
OUT = BASE / "build" / "b4"
VIDEO = OUT / "b4_full_zh_landscape.mp4"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FPS = 30
DUCK = 0.25
NARR_DIR = OUT / "tts"

NARR = {
    "bio1": "1893年，纽约。一位来自波希米亚的作曲家，站在美国国立音乐学院的讲台上。他叫德沃夏克。",
    "bio2": "那年夏天，他去了艾奥瓦州的捷克村。在那里，他动手写一部新的交响曲。他说，新大陆给了他新的声音：他听见了黑人的灵歌，也听见了印第安人的舞蹈。",
    "bio3": "这一年冬天，它在卡内基音乐厅首演，轰动全城。这部《自新世界》，是他对美洲的问候，也是他对故乡波希米亚的思念。",
    "map": "开始之前，先给你一张聆听地图。四个乐章，四种性格：第一乐章是风暴，第二乐章是乡愁，第三乐章是舞会，第四乐章是搏斗。每到一个乐章，我都会提醒你该听什么。现在，出发。",
    "mov1a": "第一乐章，e小调。开头半分钟，是黎明前的灰——弦乐低低地铺着，圆号远远地喊出一个号角般的动机。",
    "mov1b": "然后，风暴进来。快板像海浪，一波接着一波。记住这个动机——它会在整部交响曲里，一次一次地回来。",
    "mov1c": "奏鸣曲式，是古典音乐的盖楼法：先摆出主题和副题，再把它们拆开、发展、碰撞，最后回来一决高下。学会了这套规矩，你听到的就不只是声音，而是一座会呼吸的建筑。",
    "mov2a": "第二乐章，写的是乡愁。开头没有旋律，只有管乐铺出的九个和弦，像圣咏，也像一次深呼吸。",
    "mov2b": "现在，英国管开口了。这段旋律，你说不出它的名字，却好像在哪里听过很久。",
    "mov2c": "有人说它像黑人灵歌。德沃夏克自己不承认是引用——他说，这是把听过的东西，变成了自己的话。听它的音色：比双簧管更大，更暗，像一位年长的歌者。",
    "mov2d": "中段，音乐转到了升c小调，弦乐涌起波澜——乡愁到了最深的谷底。后来有人给这段旋律填上词，成了那首著名的歌《回家》。记住：曲调是德沃夏克写的，歌是后来才长出来的。",
    "mov3a": "第三乐章，谐谑曲——名字的意思就是玩笑。E小调，快得像不停蹄的马：弦乐踢踏，木管旋转，强与弱一句一换。",
    "mov3b": "现在走进中段：三角铁和钹来了，节奏一下子有了舞会的光。谐谑曲是三段式——外面的壳跑得飞快，中间的心，是村庄的宴席。",
    "mov4a": "末乐章，火一样的快板。铜管齐鸣，像号角，像风暴——新世界不只有田园，也有搏斗。",
    "mov4b": "注意听：第一乐章的号角动机回来了——四个乐章不是四首歌，是一座建筑的四根柱子，主题在彼此的门里进进出出。",
    "mov4c": "最后，风暴退去。e小调的黑色，化解成E大调的和弦，轻轻落定。这不是胜利的凯旋，更像一声长长的叹息，和一句晚安。",
    "chart": "为什么是英国管？看这张图。它的音域，正好坐在人声的位置——德沃夏克要的，就是一件像人在唱歌的乐器。长笛唱田园，圆号吹召唤，大提琴与它对唱，而打击乐撑起节日的骨架。",
    "closing": "这就是自新世界：一个波希米亚人写给美洲的情书，也是一封写给故乡的家书。下次再听见英国管开口，你会知道它的名字——乡愁。",
}

SCENES = [
    {"id": "intro", "kind": "card", "dur": 4.0},
    {"id": "bio", "kind": "timeline", "dur_narr": ["bio1", "bio2", "bio3"], "tail": 2.5},
    {"id": "map", "kind": "map", "dur_narr": ["map"], "tail": 2.0},
    {"id": "mov1", "kind": "waveform", "audio": ("mov1.ogg", 0.0, 95.0),
     "narr": [("mov1a", 1.6), ("mov1b", 24.8), ("mov1c", 70.0)], "events": [(25.0, "快板")],
     "label": "I. Adagio – Allegro molto · E 小调"},
    {"id": "mov2chords", "kind": "chords", "audio": ("largo.ogg", 0.0, 22.4),
     "narr": [("mov2a", 1.6)]},
    {"id": "mov2theme", "kind": "melody", "audio": ("largo.ogg", 186.0, 120.0),
     "narr": [("mov2b", 1.0), ("mov2c", 32.0), ("mov2d", 95.0)], "events": [(60.0, "中段 升c小调")],
     "label": "II. Largo · 降 D 大调 → 升 c 小调 → 回归"},
    {"id": "mov3a", "kind": "waveform", "audio": ("mov3.ogg", 0.0, 50.0),
     "narr": [("mov3a", 1.6)], "events": [],
     "label": "III. Molto vivace · 谐谑曲外壳 · E 小调"},
    {"id": "mov3b", "kind": "waveform", "audio": ("mov3.ogg", 150.0, 50.0),
     "narr": [("mov3b", 2.0)], "events": [(7.0, "三角铁与钹")],
     "label": "III. 中段 · 三声部 · 村庄的宴席", "preroll": 0.3, "tail": 0.4, "done": 0.3},
    {"id": "mov4", "kind": "waveform", "audio": ("mov4.ogg", 0.0, 90.0),
     "narr": [("mov4a", 1.6), ("mov4b", 55.0), ("mov4c", 76.0)], "events": [(3.0, "主题"), (85.0, "E 大调收束")],
     "label": "IV. Allegro con fuoco · E 小调 → E 大调收束"},
    {"id": "chart", "kind": "chart", "narr": [("chart", 1.2), ("closing", 16.0)], "tail": 2.5},
    {"id": "credit", "kind": "card", "dur": 8.0},
]

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:1920px; height:1080px; overflow:hidden; background:#f7f2e6; color:#2c2620;
  font-family:Georgia,"Times New Roman","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif; }
.scene { display:none; width:1920px; height:1080px; padding:56px 90px; flex-direction:column; }
.scene.on { display:flex; }
.head { border-bottom:2px solid #d9cdb7; padding-bottom:16px; margin-bottom:22px; }
.kicker { font-size:21px; letter-spacing:.35em; color:#b8860b; margin-bottom:8px; }
h1 { font-size:46px; font-weight:600; }
h1 .sub { font-size:23px; color:#8a7e6c; font-style:italic; margin-left:20px; }
.caption { font-size:22px; line-height:1.5; margin-top:14px; color:#5a5142; width:1740px; }
.caption b { color:#b8860b; }
.foot { margin-top:auto; border-top:1px solid #d9cdb7; padding-top:12px;
  display:flex; justify-content:space-between; font-size:17px; color:#8a7e6c; }
svg text { font-family:inherit; }
.card { display:none; width:1920px; height:1080px; background:#f7f2e6; }
.card.on { display:flex; }
.card .inner { margin:auto; text-align:center; max-width:1500px; }
.card .k { font-size:24px; letter-spacing:.5em; color:#b8860b; margin-bottom:32px; }
.card .t { font-size:88px; font-weight:700; letter-spacing:.05em; }
.card .s { font-size:32px; color:#8a7e6c; margin-top:26px; font-style:italic; }
.card img { margin:auto; }
[data-i].cur { opacity:1 !important; }
[data-i].past { opacity:.55 !important; }
[data-i].future { opacity:.30 !important; }
[data-i].done { opacity:.85 !important; }
[data-i].cur .hl-gold { fill:#b8860b !important; stroke:#b8860b !important; }
[data-i].cur .hl-line { stroke:#b8860b !important; stroke-width:10 !important; }
[data-i].cur .hl-note-name { fill:#b8860b !important; opacity:1 !important; font-weight:bold !important; }
.ev { opacity:.85; }
"""

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="card" id="card-intro"><div class="inner">
  <div class="k">古 典 音 乐 开 门</div>
  <div class="t">德沃夏克《自新世界》</div>
  <div class="s">一部交响曲，两种乡愁 · 全片欣赏版（中文 · 16:9）</div></div></div>
{scenes}
<div class="card" id="card-credit"><div class="inner"><img src="credit_card.png" width="1780"></div></div>
<script>const DATA = {data};</script>
<script>
function qs(k){{ return new URLSearchParams(location.search).get(k); }}
const scene = qs("scene"), state = parseInt(qs("state") || "-1", 10);
function show(id){{ const el = document.getElementById(id); if (el) el.classList.add("on"); }}
if (scene === "intro") show("card-intro");
else if (scene === "credit") show("card-credit");
else {{
  show("scene-" + scene);
  const viz = document.getElementById("viz-" + scene);
  viz.innerHTML = DATA[scene].svg;
  const cur = DATA[scene].current || [];
  const done = state >= cur.length;
  const activeIdx = (state >= 0 && state < cur.length) ? cur[state] : -1;
  document.querySelectorAll("#viz-" + scene + " [data-i]").forEach(el => {{
    const i = parseInt(el.getAttribute("data-i"), 10);
    el.classList.remove("cur", "past", "future", "done");
    if (done || i < activeIdx) el.classList.add("past");
    else if (i === activeIdx) el.classList.add("cur");
    else el.classList.add("future");
  }});
  const ph = qs("ph");
  if (ph !== null && DATA[scene].dur) {{
    const t = parseFloat(ph), D = DATA[scene].dur;
    const svg = viz.querySelector("svg");
    const NS = "http://www.w3.org/2000/svg";
    const mk = (tag, attrs) => {{ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }};
    const X0 = DATA[scene].x0, X1 = DATA[scene].x1, yT = DATA[scene].yTop, yB = DATA[scene].yBot;
    const px = X0 + t / D * (X1 - X0);
    svg.appendChild(mk("rect", {{x: X0, y: yT, width: px - X0, height: yB - yT, fill: "#b8860b", opacity: "0.07"}}));
    svg.appendChild(mk("line", {{x1: px, y1: yT - 14, x2: px, y2: yB + 12, stroke: "#b8860b", "stroke-width": 3.5}}));
    const tx = mk("text", {{x: X1 - 190, y: yT - 12, "font-size": 24, fill: "#b8860b", "font-weight": "bold"}});
    tx.textContent = Math.round(t) + "s / " + Math.round(D) + "s";
    svg.appendChild(tx);
  }}
}}
</script>
</body></html>"""


def d30(t):
    return math.ceil(t * FPS - 1e-9) / FPS


def frange(a, b, step):
    out = []
    t = a
    while t < b - 1e-9:
        out.append(round(t, 1))
        t += step
    return out


def sh(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(map(str, args))}\n{r.stdout[-500:]}\n{r.stderr[-500:]}")
    return r


def probe_dur(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


# 播放头几何（与 svg_waveform / svg_melody 的绘图坐标一致）
PH_GEO = {"waveform": {"x0": 10, "x1": 1740, "yTop": 46, "yBot": 560},
          "melody": {"x0": 10, "x1": 1740, "yTop": 30, "yBot": 580}}


def svg_timeline():
    nodes = [
        ("1841", "波希米亚 · 安东宁·德沃夏克出生（布拉格附近，肉铺之子）"),
        ("1892", "应邀赴美 · 出任纽约国立音乐学院院长（年薪 1.5 万美元）"),
        ("1893", "《自新世界》完成 · 12 月 16 日卡内基音乐厅首演"),
        ("1904", "布拉格去世 · 国葬。这部交响曲从此走向全世界"),
    ]
    x0, x1, yline = 160, 1740, 330
    out = ['<svg width="1740" height="560" viewBox="0 0 1740 560" xmlns="http://www.w3.org/2000/svg">']
    out.append(f'<line x1="{x0}" y1="{yline}" x2="{x1}" y2="{yline}" stroke="#8a7e6c" stroke-width="3"/>')
    for i, (yr, txt) in enumerate(nodes):
        x = x0 + (i + 0.5) * (x1 - x0) / len(nodes)
        out.append(f'<g data-i="{i}"><circle class="hl-gold" cx="{x}" cy="{yline}" r="14" fill="#2c2620"/>'
                   f'<text x="{x}" y="{yline-40}" font-size="44" fill="#2c2620" text-anchor="middle" font-weight="bold">{yr}</text>'
                   f'<foreignObject x="{x-170}" y="{yline+34}" width="340" height="180">'
                   f'<div xmlns="http://www.w3.org/1999/xhtml" style="font:22px Georgia,\'Noto Serif CJK SC\',serif;color:#5a5142;text-align:center;line-height:1.45">{txt}</div>'
                   f'</foreignObject></g>')
    out.append('</svg>')
    return "".join(out)


def svg_map():
    movs = [
        ("I", "风暴", "e 小调 · 快板", "听：号角般的动机"),
        ("II", "乡愁", "降 D 大调 · 慢板", "听：英国管的歌"),
        ("III", "舞会", "e 小调 · 谐谑曲", "听：三角铁与钹"),
        ("IV", "搏斗", "e 小调 · 火快板", "听：铜管与再现"),
    ]
    out = ['<svg width="1740" height="560" viewBox="0 0 1740 560" xmlns="http://www.w3.org/2000/svg">']
    for i, (no, name, tempo, listen) in enumerate(movs):
        x = 40 + i * 430
        out.append(f'<g data-i="{i}"><rect x="{x}" y="60" width="390" height="380" rx="14" '
                   f'fill="rgba(44,38,32,.06)" stroke="#2c2620" stroke-width="1.5"/>'
                   f'<text x="{x+30}" y="130" font-size="30" fill="#b8860b" font-weight="bold">{no}. {name}</text>'
                   f'<text x="{x+30}" y="185" font-size="23" fill="#8a7e6c">{tempo}</text>'
                   f'<text x="{x+30}" y="245" font-size="24" fill="#2c2620">{listen}</text></g>')
    out.append('</svg>')
    return "".join(out)


def svg_waveform(ogg, offset, dur, events, playhead=None):
    import librosa
    import numpy as np
    y, sr = librosa.load(str(ogg), sr=11025, mono=True, offset=offset, duration=dur)
    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    t = librosa.times_like(rms, sr=sr, hop_length=hop)
    x0, x1, ytop, ybot = 10, 1740, 46, 560
    W = 68

    def X(tt):
        return x0 + tt / dur * (x1 - x0)

    out = ['<svg width="1780" height="620" viewBox="0 0 1780 620" xmlns="http://www.w3.org/2000/svg">']
    for wi in range(int(math.ceil(dur / W))):
        m = (t >= wi * W) & (t < (wi + 1) * W)
        if not m.any():
            continue
        seg = rms[m]
        out.append(f'<g data-i="{wi}">')
        bars = np.array_split(seg, 56)
        vmax = float(seg.max()) or 1.0
        for bi, bseg in enumerate(bars):
            v = float(bseg.max()) if len(bseg) else 0.0
            # sqrt 压缩：响度感知近似线性，最响=满高，安静段仍可读
            h = max(2.0, (ybot - ytop) / 2 - 4) * math.sqrt(v / vmax)
            xx = X(wi * W + (bi + 0.5) * W / 56)
            out.append(f'<rect x="{xx:.1f}" y="{(ytop+ybot)/2-h:.1f}" width="{(x1-x0)/56*0.72:.1f}" '
                       f'height="{2*h:.1f}" fill="#2c2620" opacity=".55"/>')
        out.append('</g>')
    for et, elabel in events:
        out.append(f'<g class="ev"><line class="ev-line" x1="{X(et):.0f}" y1="{ytop-24}" x2="{X(et):.0f}" y2="{ybot+8}" '
                   f'stroke="#c9403a" stroke-width="2.5" stroke-dasharray="7 5"/>'
                   f'<text class="ev-label" x="{X(et)+10:.0f}" y="{ytop-6}" font-size="22" fill="#c9403a">{elabel}</text></g>')
    if playhead is not None:
        px_ = X(playhead)
        out.append(f'<rect x="{x0}" y="{ytop}" width="{px_-x0:.1f}" height="{ybot-ytop}" fill="#b8860b" opacity=".08"/>')
        out.append(f'<line x1="{px_:.0f}" y1="{ytop-14}" x2="{px_:.0f}" y2="{ybot+12}" stroke="#b8860b" stroke-width="3.5"/>')
        out.append(f'<text x="{x1-180:.0f}" y="{ytop-16}" font-size="24" fill="#b8860b" font-weight="bold">'
                   f'{playhead:.0f}s / {dur:.0f}s</text>')
    for tt in range(0, int(dur) + 1, 10):
        out.append(f'<text x="{X(tt):.0f}" y="{ybot+32}" font-size="17" fill="#8a7e6c" text-anchor="middle">{tt}s</text>')
    out.append('</svg>')
    return "".join(out)


def svg_chords(blocks):
    from_name = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
                 "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    x0, x1, y_top, y_bot = 70, 1740, 30, 560
    tmax = 23.0
    lo, hi = 40, 71

    def X(t):
        return x0 + t / tmax * (x1 - x0)

    def Y(m):
        return y_bot - (m - lo) / (hi - lo) * (y_bot - y_top)

    out = ['<svg width="1780" height="620" viewBox="0 0 1780 620" xmlns="http://www.w3.org/2000/svg">']
    for m in range(lo, hi):
        if m % 12 == 4:
            out.append(f'<line x1="{x0}" y1="{Y(m):.0f}" x2="{x1}" y2="{Y(m):.0f}" stroke="#d9cdb7"/>')
            out.append(f'<text x="{x0-14}" y="{Y(m)+7:.0f}" font-size="16" fill="#8a7e6c" text-anchor="end">E{m//12-1}</text>')
    for t in range(0, 24, 4):
        out.append(f'<text x="{X(t):.0f}" y="{y_bot+28}" font-size="17" fill="#8a7e6c" text-anchor="middle">{t}s</text>')
    for i, b in enumerate(blocks):
        ta, tb = min(b["t_start"], tmax), min(b["t_end"], tmax)
        out.append(f'<g data-i="{i}"><rect class="hl-gold" x="{X(ta):.0f}" y="{y_top}" width="{X(tb)-X(ta):.0f}" '
                   f'height="{y_bot-y_top}" fill="rgba(44,38,32,.07)" stroke="#2c2620" stroke-width="1"/>')
        for nm in b["names"]:
            midi = from_name[nm[:-1]] + (int(nm[-1]) + 1) * 12
            if lo <= midi <= hi:
                out.append(f'<circle class="hl-gold" cx="{(X(ta)+X(tb))/2:.0f}" cy="{Y(midi):.0f}" r="10" fill="#2c2620"/>')
        out.append('</g>')
    out.append('</svg>')
    return "".join(out)


def svg_melody(theme, events=(), playhead=None):
    t0, t1 = 0.0, 120.0
    x0, x1, y_top, y_bot = 10, 1740, 30, 580
    lo, hi = 50, 88

    def X(t):
        return x0 + (t - t0) / (t1 - t0) * (x1 - x0)

    def Y(m):
        return y_bot - (m - lo) / (hi - lo) * (y_bot - y_top)

    out = ['<svg width="1780" height="620" viewBox="0 0 1780 620" xmlns="http://www.w3.org/2000/svg">']
    for m in range(lo, hi + 1):
        if m % 12 in (4, 9):
            nm = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12]
            out.append(f'<line x1="{x0}" y1="{Y(m):.0f}" x2="{x1}" y2="{Y(m):.0f}" stroke="#d9cdb7"/>')
            out.append(f'<text x="{x0-4}" y="{Y(m)+6:.0f}" font-size="16" fill="#8a7e6c">{nm}{m//12-1}</text>')
    prev = None
    for i, nt in enumerate(theme):
        ta, tb, m = nt["start"] - 186.0, nt["end"] - 186.0, nt["midi"]
        if not (lo <= m <= hi) or tb < 0 or ta > t1:
            prev = None
            continue
        ta, tb = max(ta, 0), min(tb, t1)
        if prev is not None and ta - prev[0] < 0.5 and abs(m - prev[1]) <= 5:
            out.append(f'<line x1="{X(prev[0]):.0f}" y1="{Y(prev[1]):.0f}" x2="{X(ta):.0f}" y2="{Y(m):.0f}" '
                       f'stroke="#8a7e6c" stroke-width="2" opacity=".5"/>')
        out.append(f'<g data-i="{i}"><line class="hl-line" x1="{X(ta):.0f}" y1="{Y(m):.0f}" x2="{X(tb):.0f}" y2="{Y(m):.0f}" '
                   f'stroke="#2c2620" stroke-width="7" stroke-linecap="round"/>')
        if tb - ta >= 1.2:
            out.append(f'<text class="hl-note-name" x="{(X(ta)+X(tb))/2:.0f}" y="{Y(m)-13:.0f}" font-size="19" '
                       f'fill="#2c2620" text-anchor="middle" opacity=".55">{nt["name"].replace("#", chr(0x266F))}</text>')
        out.append('</g>')
        prev = (tb, m)
    for et, elabel in events:
        out.append(f'<g class="ev"><line class="ev-line" x1="{X(et):.0f}" y1="{y_top-8}" x2="{X(et):.0f}" y2="{y_bot+8}" '
                   f'stroke="#c9403a" stroke-width="2.5" stroke-dasharray="7 5"/>'
                   f'<text class="ev-label" x="{X(et)+10:.0f}" y="{y_top+14}" font-size="21" fill="#c9403a">{elabel}</text></g>')
    if playhead is not None:
        px_ = X(playhead)
        out.append(f'<rect x="{x0}" y="{y_top}" width="{px_-x0:.1f}" height="{y_bot-y_top}" fill="#b8860b" opacity=".06"/>')
        out.append(f'<line x1="{px_:.0f}" y1="{y_top-10}" x2="{px_:.0f}" y2="{y_bot+12}" stroke="#b8860b" stroke-width="3.5"/>')
        out.append(f'<text x="{x1-180:.0f}" y="{y_top-12}" font-size="24" fill="#b8860b" font-weight="bold">'
                   f'{playhead:.0f}s / {t1:.0f}s</text>')
    for tt in range(0, int(t1) + 1, 20):
        out.append(f'<text x="{X(tt):.0f}" y="{y_bot+32}" font-size="17" fill="#8a7e6c" text-anchor="middle">{tt}s</text>')
    out.append('</svg>')
    return "".join(out)


def svg_chart(theme_notes):
    instruments = [
        ("长笛 Flute", 60, 96), ("双簧管 Oboe", 56, 93), ("英国管 Cor Anglais", 52, 84),
        ("单簧管 Clarinet", 50, 94), ("大管 Bassoon", 34, 75), ("圆号 Horn", 35, 77),
        ("小号 Trumpet", 52, 84), ("长号 Trombone", 40, 77), ("大号 Tuba", 26, 55),
        ("小提琴 Violin", 55, 103), ("大提琴 Cello", 36, 84),
    ]
    tmin = min(n["midi"] for n in theme_notes)
    tmax = max(n["midi"] for n in theme_notes)
    lo, hi = 24, 104
    x0, x1, row_h, y0 = 470, 1560, 50, 46

    def X(m):
        return x0 + (m - lo) / (hi - lo) * (x1 - x0)

    out = ['<svg width="1780" height="620" viewBox="0 0 1780 620" xmlns="http://www.w3.org/2000/svg">']
    for m in range(lo, hi + 1):
        if m % 12 in (4, 9):
            nm = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12]
            out.append(f'<line x1="{X(m):.0f}" y1="32" x2="{X(m):.0f}" y2="{y0+len(instruments)*row_h+6}" stroke="#d9cdb7"/>')
            out.append(f'<text x="{X(m):.0f}" y="22" font-size="16" fill="#8a7e6c" text-anchor="middle">{nm}{m//12-1}</text>')
    for i, (name, a, b) in enumerate(instruments):
        yy = y0 + i * row_h
        star = "英国管" in name
        fw = 'font-weight="bold"' if star else ""
        fg = "#b8860b" if star else "#2c2620"
        out.append(f'<text x="450" y="{yy+12:.0f}" font-size="23" fill="{fg}" text-anchor="end" {fw}>{name}</text>')
        h = 21 if star else 15
        fill = "#b8860b" if star else "#2c2620"
        op = "1" if star else ".42"
        out.append(f'<rect x="{X(a):.0f}" y="{yy-h/2:.0f}" width="{X(b)-X(a):.0f}" height="{h}" rx="{h/2}" fill="{fill}" opacity="{op}"/>')
        if star:
            out.append(f'<rect x="{X(tmin)-3:.0f}" y="{yy-h/2-7:.0f}" width="{X(tmax)-X(tmin)+6:.0f}" height="{h+14}" '
                       f'rx="10" fill="none" stroke="#c9403a" stroke-width="3"/>')
    out.append('</svg>')
    return "".join(out)


TITLES = {
    "bio": ("作曲家 · 在新大陆的波希米亚人", "1841 – 1904"),
    "map": ("聆听地图", "四个乐章，四种性格"),
    "mov1": ("第一乐章 · 黎明前，然后是风暴", "Adagio – Allegro molto · E 小调"),
    "mov2chords": ("第二乐章 · 九个和弦的深呼吸", "Largo · 降 D 大调"),
    "mov2theme": ("英国管的旋律线", "Largo · 主题 → 升 c 小调中段 → 回归"),
    "mov3a": ("第三乐章 · 谐谑曲外壳", "Molto vivace · E 小调"),
    "mov3b": ("第三乐章 · 村庄的宴席", "Molto vivace · 中段三声部"),
    "mov4": ("第四乐章 · 火与风暴", "Allegro con fuoco · E 小调 → E 大调收束"),
    "chart": ("谁在什么音区唱歌", "Instrumental Ranges"),
}
FOOTS = {
    "mov1": "音频：Musopen（Public domain）· 摘录 0-95s · 快板进入 25s（RMS 实测）",
    "mov2chords": "谱面真值：CC0 MIDI → 和弦模板对拍（9/9 过判据）",
    "mov2theme": "f0 泛音和声评分（117 段）· 图上 0s = 录音 186s · 中段升 c 小调（实测音高分布）",
    "mov3a": "音频摘录 0-50s · 谐谑曲主部",
    "mov3b": "音频摘录 150-200s · 三角铁/钹 = 高频峰簇 157-176s（实测）",
    "mov4": "音频摘录 0-90s · 结尾 E 大调（chroma 实测 G♯≫G）",
    "chart": "音域带：标准编制参考值 · 红框：主题段实测音域",
    "bio": "生卒、任职、首演日期为公认传记史料",
    "map": "音频：全片 · Musopen 演奏（Public domain）",
}
CAPS = {
    "mov1": "波形越高越响。红虚线 = <b>实测事件</b>；金色播放头告诉你现在听到第几秒。",
    "mov2chords": "九个弱奏和弦像圣咏一样铺满开头的 22 秒——先记住这层<b>降 D 大调</b>的底色。",
    "mov2theme": "金色 = 此刻在唱的音。60 秒后进入<b>升 c 小调</b>中段——乡愁的谷底，然后旋律回家。",
    "mov3a": "注意强弱的一句一换——这是谐谑曲的呼吸。",
    "mov3b": "高频的亮点就是<b>三角铁与钹</b>——舞会从这里开始。",
    "mov4": "85 秒后的和弦：<b>E 大调收束</b>（实测 G♯≫G）。风暴的终点是明亮，不是凯旋。",
    "bio": "他在美国写下的是一部<b>关于思念</b>的交响曲。",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    frames = OUT / "frames"
    frames.mkdir(exist_ok=True)
    d1 = json.loads(NOTES_OPEN.read_text(encoding="utf-8"))
    d2 = json.loads(NOTES_THEME.read_text(encoding="utf-8"))
    blocks = d1["blocks"]
    theme = [n for n in d2["notes"] if 186 <= n["start"] < 306]
    nB = len(theme)

    # ── 1. TTS（存在即复用）──
    NARR_DIR.mkdir(parents=True, exist_ok=True)
    import re
    if not (NARR_DIR / "n-bio1.mp3").exists():
        langs = []
        for k, text in NARR.items():
            ct = re.sub(r"[，。！？：；、——…《》「」（）·]", " ", text)
            ct = re.sub(r"\s+", " ", ct).strip()
            langs.append({"locale": f"n-{k}", "persona": "narrator", "latin": "narrator",
                          "gender": "f", "voice": "zh-CN-XiaoxiaoNeural", "text": ct,
                          "tokens": [c for c in ct if not c.isspace()]})
        (OUT / "voices.json").write_text(json.dumps({"tts_dir": "tts", "langs": langs},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
        raise RuntimeError(f"缺 TTS：先跑 feuille karaoke tts {OUT / 'voices.json'} {NARR_DIR}")
    narr_dur = {k: probe_dur(NARR_DIR / f"n-{k}.mp3") for k in NARR}
    SEQ_AT = {}
    for key_list in (["bio1", "bio2", "bio3"], ["map"]):
        t = 1.2
        for k in key_list:
            SEQ_AT[k] = round(t, 2)
            t += narr_dur[k] + 0.9
    print("[TTS] " + " ".join(f"{k}={v:.1f}" for k, v in narr_dur.items()))

    # ── 2. 时间轴规划 ──
    timeline = []
    shots = []          # (scene, url_state, png_name)

    def reg(sid, url_state, name):
        shots.append((sid, url_state, name))
        return name

    scene_of = {sc["id"]: sc for sc in SCENES}
    timeline.append(("intro.png", d30(4.0)))
    reg("intro", None, "intro.png")

    for sc in SCENES:
        sid = sc["id"]
        if sc["kind"] == "card":
            continue
        pre = sc.get("preroll", 0.8)
        tail = sc.get("tail", 0.8)
        done = sc.get("done", 0.5)
        if sc.get("narr"):
            narr = sc["narr"]
        else:
            narr = [(k, SEQ_AT[k]) for k in sc.get("dur_narr", [])]
        music_dur = sc["audio"][2] if sc.get("audio") else 0.0
        narr_end = max((at + narr_dur[k] for k, at in narr), default=0.0)
        body = d30(max(music_dur, narr_end + (2.0 if sc["kind"] in ("timeline", "map", "chart") else 1.0)))
        sc["body"] = body

        if sc["kind"] == "waveform":
            states = frange(0.0, body, 5.0)
        elif sc["kind"] == "melody":
            states = frange(0.0, body, 2.5)
        elif sc["kind"] == "chords":
            states = list(range(len(blocks)))
        elif sc["kind"] in ("timeline", "map"):
            states = list(range(4))
        else:
            states = [0]

        reg(sid, -1, f"{sid}_s-1.png")
        for idx, st in enumerate(states):
            reg(sid, st, f"{sid}_s{idx:02d}.png")
        reg(sid, len(states), f"{sid}_done.png")

        # 时间轴段：-1 帧（pre + 首事件前）→ 各态段 → done
        # 首事件：chords/timeline/map 用首个 marks；时间态用 states[0]；
        # chart 无 -1 段（单一静态已含 preroll，否则重复计）
        if sc["kind"] == "chords":
            first_t = blocks[0]["t_start"]
        elif sc["kind"] in ("timeline", "map"):
            first_t = [at for k, at in narr][0]
        elif sc["kind"] in ("waveform", "melody"):
            first_t = states[0]
        else:
            first_t = None
        if first_t is not None:
            timeline.append((f"{sid}_s-1.png", d30(pre + first_t)))
        if states and isinstance(states[0], float):
            for i in range(len(states)):
                end_t = states[i + 1] if i + 1 < len(states) else body
                start_t = states[i]
                timeline.append((f"{sid}_s{i:02d}.png",
                                 max(1 / FPS, d30(pre + end_t) - d30(pre + start_t))))
        elif sc["kind"] == "chords":
            marks = [b["t_start"] for b in blocks]
            for i in range(len(marks)):
                end_t = marks[i + 1] if i + 1 < len(marks) else body
                start_t = marks[i]
                timeline.append((f"{sid}_s{i:02d}.png",
                                 max(1 / FPS, d30(pre + end_t) - d30(pre + start_t))))
        elif sc["kind"] in ("timeline", "map"):
            marks = [at for k, at in narr]
            for i in range(len(marks)):
                end_t = marks[i + 1] if i + 1 < len(marks) else body
                start_t = marks[i]
                timeline.append((f"{sid}_s{i:02d}.png",
                                 max(1 / FPS, d30(pre + end_t) - d30(pre + start_t))))
        else:
            timeline.append((f"{sid}_s00.png", d30(pre + body)))
        timeline.append((f"{sid}_done.png", d30(done + tail)))

    timeline.append(("credit.png", d30(8.0)))
    total = sum(dd for _, dd in timeline)
    print(f"[TL] {len(timeline)} 段 总长 {total:.1f}s = {total/60:.2f}min")

    # ── 3. 场景 HTML（DATA 含 dur/x0/x1/yTop/yBot 供播放头 overlay）──
    scene_html, data = [], {}
    for sc in SCENES:
        sid = sc["id"]
        if sc["kind"] == "card":
            continue
        title, sub = TITLES[sid]
        if sc["kind"] == "waveform":
            ogg, off, dur = sc["audio"]
            base_svg = svg_waveform(A / ogg, off, dur, sc["events"])
            cur = frange(0.0, sc["audio"][2], 5.0)
        elif sc["kind"] == "melody":
            base_svg = svg_melody(theme, sc["events"])
            cur = frange(0.0, sc["audio"][2], 2.5)
        elif sc["kind"] == "chords":
            base_svg = svg_chords(blocks)
            cur = list(range(len(blocks)))
        elif sc["kind"] == "timeline":
            base_svg = svg_timeline()
            cur = list(range(4))
        elif sc["kind"] == "map":
            base_svg = svg_map()
            cur = list(range(4))
        else:
            base_svg = svg_chart(theme)
            cur = [0]
        entry = {"svg": base_svg, "current": cur}
        if sc["kind"] in PH_GEO:
            entry.update({"dur": sc["audio"][2], **PH_GEO[sc["kind"]]})
        data[sid] = entry
        scene_html.append(f'''<div class="scene" id="scene-{sid}">
  <div class="head"><div class="kicker">德沃夏克 · 自新世界 · OP. 95</div>
  <h1>{title}<span class="sub">{sub}</span></h1></div>
  <div id="viz-{sid}"></div>
  <div class="caption">{CAPS.get(sid, "")}</div>
  <div class="foot"><span>{FOOTS.get(sid, "")}</span><span>{sub}</span></div></div>''')
    hp = OUT / "b4_scenes.html"
    hp.write_text(HTML.format(css=CSS, scenes="".join(scene_html),
                              data=json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    print(f"[HTML] {hp}")

    # ── 4. 渲染状态帧（waveform/melody 浮点态带 ph=）──
    base_uri = hp.as_uri()
    scene_of_id = {sc["id"]: sc for sc in SCENES}
    n_done = 0
    for sid, st, name in shots:
        png = frames / name
        if png.exists():
            n_done += 1
            continue
        url = f"{base_uri}?scene={sid}&state={st}"
        sc = scene_of_id.get(sid)
        if sc and sc["kind"] in ("waveform", "melody") and isinstance(st, float):
            url += f"&ph={st}"
        with tempfile.TemporaryDirectory(prefix="chrome-b4-") as ud:
            cmd = [CHROME, "--headless=new", f"--screenshot={png}", "--window-size=1920,1080",
                   "--hide-scrollbars", "--use-mock-keychain", "--password-store=basic",
                   "--disable-gpu", "--no-first-run", f"--user-data-dir={ud}", url]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        rr = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf",
                             "scale=192:108,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                            capture_output=True)
        px = rr.stdout
        vis = sum(1 for v in px if v < 200) / len(px) if px else 0.0
        if vis < 0.002:
            raise RuntimeError(f"空白帧哨兵: {name} vis={vis:.4f} url={url}")
        n_done += 1
    print(f"[FRAMES] {n_done}/{len(shots)}")

    # ── 5. credit 卡（占位 → 成片后回填）──
    import datetime
    import shutil
    credit_png = OUT / "credit_card.png"
    if not credit_png.exists():
        facts = {
            "work": "德沃夏克《自新世界》Op. 95",
            "content": "全片欣赏版：作曲家生平 + 曲式导览 + 四乐章持续聆听 + 乐器图谱",
            "narration": "中文（zh-CN-XiaoxiaoNeural）",
            "format_": "1920×1080（16:9 · 横版）",
            "duration": "占位（成片后回填）",
            "tts": "edge-tts 神经音色（@feuille/core 协议实现）",
            "render": "Chrome headless 状态帧 + ffmpeg 帧精确合片（30fps 网格）",
            "align": "CC0 MIDI 和弦模板对拍 + 泛音和声评分 f0 + RMS/chroma 实测",
            "audio_src": "Wikimedia Commons · Musopen 演奏（Public domain）",
            "score_src": "Wikimedia Commons · Largo 前 5 小节 MIDI（CC0）",
            "platform": "explorateur/usine · feuille（B4 v2 欣赏版产线）",
            "t_start": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "t_end": "（渲染完成后回填）",
            "left_foot": "古典音乐开门 · 首支样板",
            "right_foot": "本卡数字全部实测，溯源见 README",
        }
        (OUT / "credit_facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
        subprocess.run([sys.executable, str(BASE / "tools" / "credit_card.py"),
                        str(OUT / "credit_facts.json"), str(credit_png)], check=True)
    shutil.copyfile(credit_png, frames / "credit.png")

    # ── 6. 段编码 + concat ──
    segs = OUT / "segs"
    segs.mkdir(exist_ok=True)
    for k, (name, dur) in enumerate(timeline):
        seg = segs / f"seg_{k:03d}.mp4"
        if not seg.exists():
            fr = int(round(dur * FPS))
            sh(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS),
                "-i", str(frames / name), "-frames:v", str(fr), "-c:v", "libx264",
                "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(seg)])
    list_path = OUT / "concat.txt"
    list_path.write_text("".join(f"file '{segs / f'seg_{k:03d}.mp4'}'\n"
                                 for k in range(len(timeline))), encoding="utf-8")
    v_only = OUT / "video_only.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(list_path), "-c", "copy", str(v_only)])
    v_dur = probe_dur(v_only)
    design = sum(dd for _, dd in timeline)
    print(f"[VIDEO] {v_dur:.3f}s (设计 {design:.3f}s Δ={v_dur - design:+.3f}s)")

    # ── 7. 音轨 ──
    audio_files = [OUT / "a_sil.wav"]
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", f"{d30(4.0):.3f}", str(audio_files[0])])
    for sc in SCENES:
        sid = sc["id"]
        if sc["kind"] == "card":
            if sid == "credit":
                f = OUT / f"a_{sid}.wav"
                sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{d30(8.0):.3f}", str(f)])
                audio_files.append(f)
            continue
        pre = sc.get("preroll", 0.8)
        tail = sc.get("tail", 0.8)
        done = sc.get("done", 0.5)
        narr = sc.get("narr") or [(k, SEQ_AT[k]) for k in sc.get("dur_narr", [])]
        body = sc["body"]
        total = d30(pre + body + done + tail)
        f = OUT / f"a_{sid}.wav"
        inputs, chains = [], []
        if sc.get("audio"):
            ogg, off, dur = sc["audio"]
            inputs += ["-i", str(A / ogg)]
            duck_t = "+".join(f"between(t,{at},{at + narr_dur[k]:.3f})" for k, at in narr) or "0"
            chains.append(f"[0:a]atrim={off}:{off + dur},asetpts=PTS-STARTPTS,"
                          f"adelay={int(pre*1000)}:all=1,"
                          f"volume='if({duck_t},{DUCK},1.0)':eval=frame[m]")
        else:
            chains.append("anullsrc=r=48000:cl=stereo,atrim=0:0.05,apad[m]")
        base_in = 1 if sc.get("audio") else 0
        for j, (k, at) in enumerate(narr):
            inputs += ["-i", str(NARR_DIR / f"n-{k}.mp3")]
            chains.append(f"[{base_in + j}:a]adelay={int((pre + at)*1000)}:all=1,apad[n{j}]")
        mix_in = "".join(f"[n{j}]" for j in range(len(narr)))
        sh(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
            ";".join(chains) + f";[m]{mix_in}amix=inputs={1 + len(narr)}:duration=first:normalize=0,apad[a]",
            "-map", "[a]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(f)])
        audio_files.append(f)
    alist = OUT / "audio_concat.txt"
    alist.write_text("".join(f"file '{f}'\n" for f in audio_files), encoding="utf-8")
    a_cat = OUT / "audio_cat.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(alist), "-c", "copy", str(a_cat)])
    a_dur = probe_dur(a_cat)
    print(f"[AUDIO] {a_dur:.3f}s vs video {v_dur:.3f}s (Δ={a_dur - v_dur:+.3f}s)")
    if abs(a_dur - v_dur) > 0.02:
        sh(["ffmpeg", "-y", "-v", "error", "-i", str(a_cat), "-af", "apad",
            "-t", f"{v_dur:.3f}", str(OUT / "audio_pad.wav")])
        a_cat = OUT / "audio_pad.wav"
        print("[AUDIO] 补齐至视频长度")

    # ── 8. 成片 ──
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(v_only), "-i", str(a_cat),
        "-af", "apad", "-t", f"{v_dur:.3f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(VIDEO)])
    print(f"[OUT] {VIDEO} {probe_dur(VIDEO):.3f}s")

    # ── 9. 验收 ──
    r = sh(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
            "-of", "json", str(VIDEO)])
    streams = {s["codec_type"]: float(s["duration"]) for s in json.loads(r.stdout)["streams"]}
    dv = abs(streams["video"] - streams["audio"])
    print(f"  双流时长差 {dv*1000:.1f}ms {'✓' if dv < 0.05 else '✗'}")
    r = subprocess.run(["ffmpeg", "-i", str(VIDEO), "-vf", "fps=1,scale=192:108,format=gray",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    px = r.stdout
    FW = 192 * 108
    total_f = len(px) // FW
    noink = sum(1 for fi in range(total_f)
                if sum(1 for v in px[fi * FW:(fi + 1) * FW] if v < 200) / FW < 0.002)
    print(f"  含墨扫描 {noink}/{total_f} {'✓' if noink == 0 else '✗'}")
    print("[VERDICT] 程序验收完成——抽帧人眼复核必做")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
