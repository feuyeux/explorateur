"""B2 工具：中文横版样片（90-120s，第二乐章主题段）。

结构（PLAN §4.2 听辨式的落法）：
  intro 卡 → A 开场和弦（真实录音 0-22s + 和弦高亮）→ B 英国管主题
  （真实录音 186-246s + 逐音符高亮）→ C 乐器图谱 → outro 卡。

装配纪律（来自 karaoke-video/references/av-sync.md，全条遵守）：
  §2 每个状态段用精确帧数单独编码再 concat -c copy（杜绝 concat 漂移）；
  §3 所有时长先 d30 吸附 30fps 网格；§4 音频段含 preroll、-t 裁到场景总长；
  §5 状态帧无动画、file:// 绝对路径、独立 --user-data-dir、空白帧哨兵；
  §6 验收：ffprobe 双流时长 + 全片白页扫描 + 抽帧人眼复核。

音频：聆听段音乐全电平；旁白出声时音乐压到 0.25（约 -12dB）。
旁白：edge-tts zh-CN-XiaoxiaoNeural（PLAN 风险表候选音色，样片用其一）。
"""
import json
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
NOTES_OPEN = BASE / "notes" / "opening-notes.json"
NOTES_THEME = BASE / "notes" / "theme-notes.json"
OGG = BASE / "assets" / "largo.ogg"
OUT = BASE / "build" / "b2"
VIDEO = BASE / "build" / "b2" / "b2_sample_zh_landscape.mp4"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
FPS = 30
PREROLL = 0.8
TAIL = 0.8
DONE = 0.5
DUCK = 0.25

NARR = {
    "A": "乐曲的开始，没有旋律。管乐轻轻地，铺出九个和弦，像圣咏，也像一次深呼吸。记住这层降D大调的底色——三分钟以后，它会托起全曲最著名的一段旋律。",
    "B1": "现在，英国管开口了。这段旋律，你说不出它的名字，却好像在哪里听过很久。",
    "B2": "听它的音色。比双簧管更大，更暗，像一位年长的歌者，不急，也不躲。德沃夏克把全曲最温柔的这支歌，交给它。",
    "C": "在这部交响曲里，每件乐器都有自己的岗位。长笛唱田园，圆号吹召唤，大提琴与英国管对唱。而打击乐没有音高，却撑起节日的骨架。",
}

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:1920px; height:1080px; overflow:hidden; background:#f7f2e6; color:#2c2620;
  font-family:Georgia,"Times New Roman","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif; }
.scene { display:none; width:1920px; height:1080px; padding:64px 90px; flex-direction:column; }
.scene.on { display:flex; }
.head { border-bottom:2px solid #d9cdb7; padding-bottom:20px; margin-bottom:30px; }
.kicker { font-size:22px; letter-spacing:.35em; color:#b8860b; margin-bottom:10px; }
h1 { font-size:50px; font-weight:600; }
h1 .sub { font-size:25px; color:#8a7e6c; font-style:italic; margin-left:22px; }
.caption { font-size:24px; line-height:1.55; margin-top:20px; color:#5a5142; }
.caption b { color:#b8860b; }
.foot { margin-top:auto; border-top:1px solid #d9cdb7; padding-top:14px;
  display:flex; justify-content:space-between; font-size:19px; color:#8a7e6c; }
svg text { font-family:inherit; }
/* 卡片 */
.card { display:none; width:1920px; height:1080px; background:#f7f2e6; }
.card.on { display:flex; flex-direction:column; justify-content:center; align-items:center; }
.card .k { font-size:26px; letter-spacing:.5em; color:#b8860b; margin-bottom:36px; }
.card .t { font-size:96px; font-weight:700; letter-spacing:.06em; }
.card .s { font-size:34px; color:#8a7e6c; margin-top:30px; font-style:italic; }
.card .r { font-size:22px; color:#a2967f; margin-top:60px; letter-spacing:.2em; }
.card .rule { width:220px; height:3px; background:#b8860b; margin:44px 0 0; }
"""

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="card" id="card-intro"><div class="k">古典音乐开门 · 样片</div>
  <div class="t">德沃夏克《自新世界》</div><div class="rule"></div>
  <div class="s">第二乐章 Largo · 英国管的歌</div>
  <div class="r">B2 PROTOTYPE · 中文 · 16:9</div></div>
<div class="scene" id="scene-A">
  <div class="head"><div class="kicker">德沃夏克 · 自新世界 · 第二乐章 LARGO</div>
  <h1>开场的和弦铺底<span class="sub">Cor Anglais 之前，管乐先铺好路</span></h1></div>
  <div id="viz-A"></div>
  <div class="caption">九个弱奏和弦像圣咏一样铺满开头的 22 秒——先记住这层<b>降 D 大调</b>的底色。</div>
  <div class="foot"><span>谱面真值：CC0 MIDI → 自动对齐到录音</span><span>降 D 大调</span></div></div>
<div class="scene" id="scene-B">
  <div class="head"><div class="kicker">德沃夏克 · 自新世界 · 第二乐章 LARGO</div>
  <h1>英国管的旋律线<span class="sub">听音高自己走</span></h1></div>
  <div id="viz-B"></div>
  <div class="foot"><span>自相关泛音和声评分逐帧 f0 → 半音量化</span><span>图上 0s = 录音 186s</span></div></div>
<div class="scene" id="scene-C">
  <div class="head"><div class="kicker">德沃夏克 · 自新世界 · 交响曲编制</div>
  <h1>谁在什么音区唱歌<span class="sub">Instrumental Ranges</span></h1></div>
  <div id="viz-C"></div>
  <div class="caption">红框圈出<b>主题段的实测音域</b>（含双簧管的应答句）——正好坐在人声女中音的位置。</div>
  <div class="foot"><span>音域带：标准编制参考值 · 主题落点：录音实测</span><span>Op. 95 · E 小调</span></div></div>
<div class="card" id="card-outro"><div class="k">样片验收</div>
  <div class="t">音画同步 · 旁白电平 · 逐音符高亮</div><div class="rule"></div>
  <div class="s">B2 prototype · explorateur/usine</div></div>
<script>const DATA = {data};</script>
<script>{js}</script>
</body></html>"""

JS = """
function qs(k){ return new URLSearchParams(location.search).get(k); }
const scene = qs("scene"), state = parseInt(qs("state") || "-1", 10);
function show(id){ const el = document.getElementById(id); if (el) el.classList.add("on"); }
if (scene === "intro" || scene === "card-intro") show("card-intro");
else if (scene === "outro" || scene === "card-outro") show("card-outro");
else {
  show("scene-" + scene);
  const viz = document.getElementById("viz-" + scene);
  viz.innerHTML = DATA[scene].svg;
  const cur = DATA[scene].current || [];   // state -> 当前元素下标（-1 全暗，N=done）
  const activeIdx = (state >= 0 && state < cur.length) ? cur[state] : -1;
  const done = state >= cur.length;
  document.querySelectorAll("#viz-" + scene + " [data-i]").forEach(el => {
    const i = parseInt(el.getAttribute("data-i"), 10);
    el.classList.remove("cur", "past", "future", "done");
    if (done || i < activeIdx) el.classList.add("past");
    else if (i === activeIdx) el.classList.add("cur");
    else el.classList.add("future");
  });
  if (done) document.querySelectorAll("#viz-" + scene + " [data-i]").forEach(el => el.classList.add("done"));
}
"""

# 状态样式：当前 = 金色 + 实线金框；已过 = 墨色 55%；未来 = 30%；done 全部墨色 85%
STATE_CSS = """
[data-i].cur { opacity:1 !important; }
[data-i].past { opacity:.55 !important; }
[data-i].future { opacity:.30 !important; }
[data-i].done { opacity:.85 !important; }
.hl-gold { transition:none; }
[data-i].cur .hl-gold { fill:#b8860b !important; stroke:#b8860b !important; }
[data-i].cur .hl-line { stroke:#b8860b !important; stroke-width:10 !important; }
[data-i].cur .hl-box { stroke:#c9403a !important; stroke-width:4 !important; }
[data-i].cur .hl-note-name { fill:#b8860b !important; opacity:1 !important; font-weight:bold !important; }
"""


def d30(t):
    """吸附到 30fps 网格（av-sync §3）。"""
    import math
    return math.ceil(t * FPS - 1e-9) / FPS


def frames_of(sec):
    return int(round(sec * FPS))


def sh(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(map(str, args))}\n{r.stdout[-600:]}\n{r.stderr[-600:]}")
    return r


def probe_dur(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


def render_svg_a(blocks):
    """场景 A：和弦时间轴。data-i = 和弦块号。"""
    x0, x1, y_top, y_bot = 70, 1740, 30, 620
    tmax = 23.0
    lo, hi = 40, 71

    def X(t):
        return x0 + t / tmax * (x1 - x0)

    def Y(m):
        return y_bot - (m - lo) / (hi - lo) * (y_bot - y_top)

    from_name = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
                 "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    out = [f'<svg width="1780" height="700" viewBox="0 0 1780 700" xmlns="http://www.w3.org/2000/svg">']
    for m in range(lo, hi):
        if m % 12 == 4:
            out.append(f'<line x1="{x0}" y1="{Y(m):.0f}" x2="{x1}" y2="{Y(m):.0f}" stroke="#d9cdb7"/>')
            out.append(f'<text x="{x0-14}" y="{Y(m)+7:.0f}" font-size="17" fill="#8a7e6c" text-anchor="end">E{m//12-1}</text>')
    for t in range(0, 24, 2):
        out.append(f'<text x="{X(t):.0f}" y="{y_bot+30}" font-size="18" fill="#8a7e6c" text-anchor="middle">{t}s</text>')
    for i, b in enumerate(blocks):
        ta, tb = min(b["t_start"], tmax), min(b["t_end"], tmax)
        out.append(f'<g data-i="{i}"><rect class="hl-gold" x="{X(ta):.0f}" y="{y_top}" width="{X(tb)-X(ta):.0f}" '
                   f'height="{y_bot-y_top}" fill="rgba(44,38,32,.07)" stroke="#2c2620" stroke-width="1"/>')
        for nm in b["names"]:
            midi = from_name[nm[:-1]] + (int(nm[-1]) + 1) * 12
            if lo <= midi <= hi:
                out.append(f'<circle class="hl-gold" cx="{(X(ta)+X(tb))/2:.0f}" cy="{Y(midi):.0f}" r="11" fill="#2c2620"/>')
        out.append('</g>')
    out.append(f'<text x="{X(12.42)+16:.0f}" y="{y_top+26}" font-size="22" fill="#b8860b" font-weight="bold">№5</text>')
    out.append('</svg>')
    return "".join(out)


def render_svg_b(notes):
    """场景 B：旋律线。data-i = 音符号。x 轴 = 场景本地秒（0 = 录音 186s）。"""
    t0, t1 = 0.0, 60.0
    x0, x1, y_top, y_bot = 10, 1740, 20, 660
    lo, hi = 50, 88

    def X(t):
        return x0 + (t - t0) / (t1 - t0) * (x1 - x0)

    def Y(m):
        return y_bot - (m - lo) / (hi - lo) * (y_bot - y_top)

    out = ['<svg width="1780" height="700" viewBox="0 0 1780 700" xmlns="http://www.w3.org/2000/svg">']
    for m in range(lo, hi + 1):
        if m % 12 in (4, 9):
            nm = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12]
            out.append(f'<line x1="{x0}" y1="{Y(m):.0f}" x2="{x1}" y2="{Y(m):.0f}" stroke="#d9cdb7"/>')
            out.append(f'<text x="{x0-4}" y="{Y(m)+7:.0f}" font-size="17" fill="#8a7e6c" text-anchor="start">{nm}{m//12-1}</text>')
    prev = None
    for i, nt in enumerate(notes):
        ta, tb, m = nt["start"] - 186.0, nt["end"] - 186.0, nt["midi"]
        if not (lo <= m <= hi) or tb < 0 or ta > t1:
            prev = None
            continue
        ta, tb = max(ta, 0), min(tb, t1)
        if prev is not None and ta - prev[0] < 0.5 and abs(m - prev[1]) <= 5:
            out.append(f'<line x1="{X(prev[0]):.0f}" y1="{Y(prev[1]):.0f}" x2="{X(ta):.0f}" y2="{Y(m):.0f}" stroke="#8a7e6c" stroke-width="2" opacity=".5"/>')
        out.append(f'<g data-i="{i}"><line class="hl-line" x1="{X(ta):.0f}" y1="{Y(m):.0f}" x2="{X(tb):.0f}" y2="{Y(m):.0f}" '
                   f'stroke="#2c2620" stroke-width="7" stroke-linecap="round"/>')
        if tb - ta >= 1.2:
            out.append(f'<text class="hl-note-name" x="{(X(ta)+X(tb))/2:.0f}" y="{Y(m)-14:.0f}" font-size="20" '
                       f'fill="#2c2620" text-anchor="middle" opacity=".55">{nt["name"].replace("#", chr(0x266F))}</text>')
        out.append('</g>')
        prev = (tb, m)
    out.append('</svg>')
    return "".join(out)


def render_svg_c(theme_notes):
    """场景 C：乐器音域图。data-i：0 = 全图，1 = 英国管行强调。简化：单状态。"""
    instruments = [
        ("长笛 Flute", 60, 96), ("双簧管 Oboe", 56, 93), ("英国管 Cor Anglais", 52, 84),
        ("单簧管 Clarinet", 50, 94), ("大管 Bassoon", 34, 75), ("圆号 Horn", 35, 77),
        ("小号 Trumpet", 52, 84), ("长号 Trombone", 40, 77), ("大号 Tuba", 26, 55),
        ("小提琴 Violin", 55, 103), ("大提琴 Cello", 36, 84),
    ]
    tmin = min(n["midi"] for n in theme_notes)
    tmax = max(n["midi"] for n in theme_notes)
    lo, hi = 24, 104
    x0, x1, row_h, y0 = 470, 1560, 52, 50

    def X(m):
        return x0 + (m - lo) / (hi - lo) * (x1 - x0)

    out = ['<svg width="1780" height="640" viewBox="0 0 1780 640" xmlns="http://www.w3.org/2000/svg">']
    for m in range(lo, hi + 1):
        if m % 12 in (4, 9):
            nm = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12]
            out.append(f'<line x1="{X(m):.0f}" y1="36" x2="{X(m):.0f}" y2="{y0+len(instruments)*row_h+6}" stroke="#d9cdb7"/>')
            out.append(f'<text x="{X(m):.0f}" y="26" font-size="17" fill="#8a7e6c" text-anchor="middle">{nm}{m//12-1}</text>')
    for i, (name, a, b) in enumerate(instruments):
        yy = y0 + i * row_h
        star = "英国管" in name
        fw = 'font-weight="bold"' if star else ""
        fg = "#b8860b" if star else "#2c2620"
        out.append(f'<text x="450" y="{yy+13:.0f}" font-size="24" fill="{fg}" text-anchor="end" {fw}>{name}</text>')
        h = 22 if star else 16
        fill = "#b8860b" if star else "#2c2620"
        op = "1" if star else ".42"
        out.append(f'<rect x="{X(a):.0f}" y="{yy-h/2:.0f}" width="{X(b)-X(a):.0f}" height="{h}" rx="{h/2}" fill="{fill}" opacity="{op}"/>')
        if star:
            out.append(f'<g><rect class="hl-box" x="{X(tmin)-3:.0f}" y="{yy-h/2-7:.0f}" '
                       f'width="{X(tmax)-X(tmin)+6:.0f}" height="{h+14}" rx="10" fill="none" stroke="#c9403a" stroke-width="3"/>'
                       f'<text class="hl-note-name" x="{(X(tmin)+X(tmax))/2:.0f}" y="{yy-h/2-16:.0f}" font-size="19" '
                       f'fill="#c9403a" text-anchor="middle" font-weight="bold">主题段实测音域</text></g>')
    out.append('</svg>')
    return "".join(out)


def chrome_shot(url, png):
    with tempfile.TemporaryDirectory(prefix="chrome-b2-") as ud:
        cmd = [CHROME, "--headless=new", f"--screenshot={png}", "--window-size=1920,1080",
               "--hide-scrollbars", "--use-mock-keychain", "--password-store=basic",
               "--disable-gpu", "--no-first-run", f"--user-data-dir={ud}", url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if not Path(png).exists() or Path(png).stat().st_size < 4000:
        raise RuntimeError(f"shot failed: {url}\n{r.stdout[-400:]}\n{r.stderr[-400:]}")


def ink_ratio(png):
    """可见标记占比（<200 灰度）。空纸 ≈0；全暗 preroll（30% 透明墨，混色后
    灰度≈183）≈1%+；内容帧更高。单规则覆盖三种状态。"""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf",
                        "scale=192:108,format=gray",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return 0.0
    px = r.stdout
    return sum(1 for v in px if v < 200) / len(px)


def blank_sentinel(png):
    """空白帧哨兵（av-sync §5 的落法）：含墨 < 0.5% = 渲染失败。
    不用「近白占比」——纸色 #f7f2e6 灰度≈242，会躲过白色阈值。"""
    return ink_ratio(png) < 0.003  # 标题卡 0.46%+、全暗帧 ~1%（<200 口径）、空纸 ≈0%


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    d1 = json.loads(NOTES_OPEN.read_text(encoding="utf-8"))
    d2 = json.loads(NOTES_THEME.read_text(encoding="utf-8"))
    blocks = d1["blocks"]
    theme = [n for n in d2["notes"] if 186 <= n["start"] < 246]

    # ── 1. 写场景 HTML（数据内嵌）──
    # current[state] → 当前高亮的 data-i（-1 全暗；末态=done 由 JS 判 state ≥ len(current)）
    data = {"A": {"svg": render_svg_a(blocks),
                  "current": list(range(len(blocks)))},
            "B": {"svg": render_svg_b(theme),
                  "current": list(range(len(theme)))},
            "C": {"svg": render_svg_c(theme), "current": [-1]}}
    html = HTML.format(css=CSS + STATE_CSS, js=JS, data=json.dumps(data, ensure_ascii=False))
    hp = OUT / "b2_scenes.html"
    hp.write_text(html, encoding="utf-8")
    print(f"[HTML] {hp}")

    # ── 2. 旁白 TTS（feuille karaoke tts 已生成 build/b2/tts/narr-*.mp3，
    #        见 README 工艺记录；标点剥除纪律 av-sync §1b）──
    tts_dir = OUT / "tts"
    tts_dir.mkdir(exist_ok=True)
    narr_dur = {}
    for k in NARR:
        mp3 = tts_dir / f"narr-{k}.mp3"
        if not mp3.exists():
            raise RuntimeError(f"缺 {mp3}——先跑 feuille karaoke tts（见 README）")
        narr_dur[k] = probe_dur(mp3)
        print(f"[TTS] {k}: {narr_dur[k]:.2f}s")

    # ── 3. 时间轴（全部 d30 吸附）──
    # 场景 A：body = 开场 0-22.4s；旁白 A 在 1.6s 进入
    a_body = d30(22.4)
    a_narr_at = d30(1.6)
    a_narr_end = a_narr_at + narr_dur["A"]
    # 场景 B：body = 60s（录音 186-246s）；B1 在 1.0s，B2 在 40s
    b_body = d30(60.0)
    b1_at = d30(1.0)
    b2_at = d30(40.0)
    # 场景 C：body = 旁白 C + 3s
    c_body = d30(narr_dur["C"] + 3.0)
    intro_len, outro_len = d30(4.0), d30(4.0)

    scene_a_total = d30(PREROLL + a_body + DONE + TAIL)
    scene_b_total = d30(PREROLL + b_body + DONE + TAIL)
    scene_c_total = d30(PREROLL + c_body + DONE + TAIL)
    grand_total = intro_len + scene_a_total + scene_b_total + scene_c_total + outro_len
    print(f"[TL] intro={intro_len:.2f} A={scene_a_total:.2f} B={scene_b_total:.2f} "
          f"C={scene_c_total:.2f} outro={outro_len:.2f} 总长={grand_total:.2f}s")

    # ── 4. 状态帧渲染 ──
    frames_dir = OUT / "frames"
    frames_dir.mkdir(exist_ok=True)
    base_url = hp.as_uri()
    shots = []
    shots.append(("card-intro", -1, frames_dir / "intro.png"))
    # A: state -1 全暗；0..8 当前和弦 i；9 done
    for s in range(-1, 11):
        shots.append(("A", s, frames_dir / f"A_{s+1:02d}.png"))
    # B: state -1; 0..len(theme)-1; len(theme) done —— state = 音符下标+1
    nB = len(theme)
    for s in range(-1, nB + 1):
        shots.append(("B", s, frames_dir / f"B_{s+1:02d}.png"))
    shots.append(("card-outro", -1, frames_dir / "outro.png"))
    # C: 纯静态图（无状态动画），单张
    shots.append(("C", -1, frames_dir / "C_static.png"))

    n_done = 0
    for scene, state, png in shots:
        if png.exists():
            n_done += 1
            continue
        url = f"{base_url}?scene={scene}&state={state}"
        chrome_shot(url, png)
        if blank_sentinel(png):
            raise RuntimeError(f"空白帧哨兵触发: {png.name} url={url}")
        n_done += 1
    print(f"[FRAMES] {n_done}/{len(shots)} 张就绪")

    # ── 5. 视频段编码（精确帧数）→ concat ──
    segs_dir = OUT / "segs"
    segs_dir.mkdir(exist_ok=True)
    list_path = OUT / "concat.txt"
    entries = []   # (png, frames)

    def add(png, dur):
        entries.append((png, frames_of(dur)))

    def addspan(png, t_start, t_end):
        """[t_start, t_end) → 至少 1 帧（帧级钳制，不是 1 秒！）。"""
        fe = int(round(d30(t_end) * FPS))
        fs = int(round(d30(t_start) * FPS))
        entries.append((png, max(1, fe - fs)))

    add(frames_dir / "intro.png", intro_len)
    # A 状态帧时长：preroll → 和弦切换 → tail+done
    a_local = [b["t_start"] for b in blocks] + [a_body]
    # 段 [a_local[i-1], a_local[i) 显示 state i-1（块 i-1 活跃）；i=0 的 [0,0.37) 归 state -1
    addspan(frames_dir / "A_00.png", 0.0, PREROLL + a_local[0])   # state -1
    for i in range(1, 10):                                       # state 0..8
        addspan(frames_dir / f"A_{i:02d}.png", PREROLL + a_local[i - 1], PREROLL + a_local[i])
    add(frames_dir / "A_11.png", d30(TAIL + DONE))              # done 帧（state 10 全亮）
    # B 状态帧时长：音符切换（本地秒 = start-186+PREROLL）
    b_local = [(n["start"] - 186.0) for n in theme] + [b_body]
    addspan(frames_dir / "B_00.png", 0.0, PREROLL + b_local[0])   # state -1
    for i in range(1, nB + 1):                                    # state 0..nB-1
        addspan(frames_dir / f"B_{i:02d}.png", PREROLL + b_local[i - 1], PREROLL + b_local[i])
    add(frames_dir / f"B_{nB+1:02d}.png", d30(TAIL + DONE))       # done 帧
    # C：preroll → 旁白段 → done（同一静态图）
    add(frames_dir / "C_static.png", PREROLL)
    add(frames_dir / "C_static.png", d30(c_body))
    add(frames_dir / "C_static.png", d30(DONE + TAIL))
    add(frames_dir / "outro.png", outro_len)

    design_total = sum(fr for _, fr in entries) / FPS
    print(f"[SEG] {len(entries)} 段 设计总帧 {sum(fr for _, fr in entries)} = {design_total:.2f}s")
    (OUT / "entries.json").write_text(json.dumps(
        [{"png": png.name, "frames": fr, "sec": fr / FPS} for png, fr in entries],
        ensure_ascii=False, indent=1), encoding="utf-8")

    for k, (png, fr) in enumerate(entries):
        seg = segs_dir / f"seg_{k:03d}.mp4"
        if not seg.exists():
            sh(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS),
                "-i", str(png), "-frames:v", str(fr), "-c:v", "libx264",
                "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(seg)])
    list_path.write_text("".join(f"file '{segs_dir / f'seg_{k:03d}.mp4'}'\n"
                                 for k in range(len(entries))), encoding="utf-8")
    silent_v = OUT / "video_only.mp4"
    if not silent_v.exists():
        sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", str(list_path), "-c", "copy", str(silent_v)])
    v_dur = probe_dur(silent_v)
    print(f"[VIDEO] {v_dur:.3f}s (设计 {design_total:.3f}s, Δ={v_dur - design_total:+.3f}s)")

    # ── 6. 音轨：音乐摘录 + 旁白（ducking）→ 场景内混音 → 拼接 ──
    a_mix = OUT / "audio_A.wav"
    # 音乐电平包络：旁白窗口 0.25，其余 1.0
    duck_a = f"volume='if(between(t,{a_narr_at},{a_narr_end:.3f}),{DUCK},1.0)':eval=frame"
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(OGG),
        "-i", str(tts_dir / "narr-A.mp3"),
        "-filter_complex",
        f"[0:a]atrim=0:{a_body},asetpts=PTS-STARTPTS,adelay={int(PREROLL*1000)}:all=1,{duck_a}[m];"
        f"[1:a]adelay={int(a_narr_at*1000)}:all=1,apad[n];"
        f"[m][n]amix=inputs=2:duration=first:normalize=0,apad[a]",
        "-map", "[a]", "-t", f"{scene_a_total:.3f}", "-ar", "48000", "-ac", "2",
        str(a_mix)])
    b_mix = OUT / "audio_B.wav"
    duck_b = (f"volume='if(between(t,{b1_at},{b1_at + narr_dur['B1']:.3f})"
              f"+between(t,{b2_at},{b2_at + narr_dur['B2']:.3f}),{DUCK},1.0)':eval=frame")
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(OGG),
        "-i", str(tts_dir / "narr-B1.mp3"), "-i", str(tts_dir / "narr-B2.mp3"),
        "-filter_complex",
        f"[0:a]atrim=186:{186 + b_body},asetpts=PTS-STARTPTS,adelay={int(PREROLL*1000)}:all=1,{duck_b}[m];"
        f"[1:a]adelay={int(b1_at*1000)}:all=1,apad[n1];"
        f"[2:a]adelay={int(b2_at*1000)}:all=1,apad[n2];"
        f"[m][n1][n2]amix=inputs=3:duration=first:normalize=0,apad[a]",
        "-map", "[a]", "-t", f"{scene_b_total:.3f}", "-ar", "48000", "-ac", "2",
        str(b_mix)])
    c_mix = OUT / "audio_C.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(tts_dir / "narr-C.mp3"),
        "-filter_complex",
        f"[0:a]adelay={int(PREROLL*1000)}:all=1,apad,atrim=0:{scene_c_total:.3f},asetpts=PTS-STARTPTS[a]",
        "-map", "[a]", "-ar", "48000", "-ac", "2", str(c_mix)])
    silence_i = OUT / "silence.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{intro_len:.3f}", str(silence_i)])

    alist = OUT / "audio_concat.txt"
    alist.write_text(
        f"file '{silence_i}'\nfile '{a_mix}'\nfile '{b_mix}'\nfile '{c_mix}'\n"
        f"file '{silence_i}'\n", encoding="utf-8")
    a_cat = OUT / "audio_cat.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(alist), "-c", "copy", str(a_cat)])
    a_dur = probe_dur(a_cat)
    print(f"[AUDIO] {a_dur:.3f}s vs video {v_dur:.3f}s (Δ={a_dur - v_dur:+.3f}s)")
    if abs(a_dur - v_dur) > 0.05:
        # 音频按视频长度补齐/裁齐（apad + -t），保住帧精确画面
        sh(["ffmpeg", "-y", "-v", "error", "-i", str(a_cat),
            "-af", "apad", "-t", f"{v_dur:.3f}", str(OUT / "audio_pad.wav")])
        a_cat = OUT / "audio_pad.wav"
        print("[AUDIO] 已按视频长度补齐")

    # ── 7. 成片 ──
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(silent_v), "-i", str(a_cat),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(VIDEO)])
    print(f"[OUT] {VIDEO}  {probe_dur(VIDEO):.3f}s")

    # ── 8. 程序验收 ──
    print("[VERIFY]")
    vp = probe_dur(VIDEO)
    ap = probe_dur(VIDEO)   # 同一容器；流级检查：
    r = sh(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
            "-of", "json", str(VIDEO)])
    streams = {s["codec_type"]: float(s["duration"]) for s in json.loads(r.stdout)["streams"]}
    dv = abs(streams["video"] - streams["audio"])
    # AAC 封装含 priming samples，实测 ~18-40ms 属正常；>50ms 才算失配
    print(f"  双流时长差 {dv*1000:.1f}ms {'✓' if dv < 0.05 else '✗'}")
    # 含墨扫描（1fps 采样；每个采样帧必须 ≥0.3% 暗像素——空纸/空页渲染必挂）
    r = subprocess.run(["ffmpeg", "-i", str(VIDEO), "-vf",
                        "fps=1,scale=192:108,format=gray",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    px = r.stdout
    FW = 192 * 108
    total = len(px) // FW
    noink = 0
    for f in range(total):
        frm = px[f * FW:(f + 1) * FW]
        if sum(1 for v in frm if v < 200) / FW < 0.002:
            noink += 1
    print(f"  含墨扫描 {noink}/{total} 帧无墨 {'✓' if noink == 0 else '✗'}")
    print("[VERDICT] 程序验收完成——抽帧人眼复核见 README")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
