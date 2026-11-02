"""B1 工具 3：三种画面形态的静帧样张（1920×1080，Chrome headless 截图）。

frame1 谱面高亮：开场合弦时间轴，t=12.5s 的状态帧（当前和弦高亮）
frame2 音高轨迹：英国管主题旋律线（f0 量化段），t=207s 的当前音高亮
frame3 乐器图谱：本作编制各乐器的音域带 + 主题实际落点

数据源：notes/opening-notes.json（工具 1）、notes/theme-notes.json（工具 2）。
渲染走真实产线路径：HTML 状态帧 + Chrome headless（mock-keychain 旗标）。
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
N1 = BASE / "notes" / "opening-notes.json"
N2 = BASE / "notes" / "theme-notes.json"
OUT = BASE / "build" / "b1"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W, H = 1920, 1080

CSS = """
:root { --paper:#f7f2e6; --card:#fcfaf5; --rule:#d9cdb7; --ink:#2c2620;
  --sub:#8a7e6c; --gold:#b8860b; --blue:#2f5d9e; --red:#c9403a;
  --lit:rgba(154,111,24,.16); --dim:.18; --mute:.34; }
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:1920px; height:1080px; overflow:hidden;
  background:var(--paper); color:var(--ink);
  font-family:Georgia,"Times New Roman","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif; }
.frame { width:1920px; height:1080px; padding:64px 90px; display:flex; flex-direction:column; }
.head { border-bottom:2px solid var(--rule); padding-bottom:20px; margin-bottom:36px; }
.kicker { font-size:22px; letter-spacing:.35em; color:var(--gold); margin-bottom:10px; }
h1 { font-size:52px; font-weight:600; letter-spacing:.02em; }
h1 .sub { font-size:26px; color:var(--sub); font-style:italic; margin-left:24px; }
.foot { margin-top:auto; border-top:1px solid var(--rule); padding-top:16px;
  display:flex; justify-content:space-between; font-size:20px; color:var(--sub); }
.caption { font-size:26px; line-height:1.6; margin-top:26px; }
.caption b { color:var(--gold); }
"""

HTML_SHELL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head>
<body>{body}</body></html>"""


def wrap(body):
    return HTML_SHELL.format(css=CSS, body=body)


def svg(w, h, inner):
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">{inner}</svg>'


def frame1(d):
    blocks = d["blocks"]
    t_axis_max = 23.0
    x0, x1 = 70, 1740          # 绘图区（左留 70px 给音名标签）
    y_top, y_bot = 40, 560
    t_now = 12.5
    # 块高：按音分数分格（音域 E2..A4 → midi 40..70）
    lo, hi = 40, 71
    def x(t): return x0 + t / t_axis_max * (x1 - x0)
    def ym(m): return y_bot - (m - lo) / (hi - lo) * (y_bot - y_top)

    inner = []
    # 纵网格：每个八度一条淡线 + 音名
    for m in range(lo, hi):
        if m % 12 == 4:  # E
            yy = ym(m)
            inner.append(f'<line x1="{x0}" y1="{yy:.0f}" x2="{x1}" y2="{yy:.0f}" stroke="#d9cdb7" stroke-width="1"/>')
            inner.append(f'<text x="{x0-14}" y="{yy+7:.0f}" font-size="17" fill="#8a7e6c" text-anchor="end">E{m//12-1}</text>')
    # 时间刻度：每 2s
    for t in range(0, 24, 2):
        xx = x(t)
        inner.append(f'<line x1="{xx:.0f}" y1="{y_bot}" x2="{xx:.0f}" y2="{y_bot+8}" stroke="#8a7e6c" stroke-width="1"/>')
        inner.append(f'<text x="{xx:.0f}" y="{y_bot+34}" font-size="18" fill="#8a7e6c" text-anchor="middle">{t}s</text>')
    # 和弦块
    from_name = {"C":0,"C#":1,"D":2,"D#":3,"E":4,"F":5,"F#":6,"G":7,"G#":8,"A":9,"A#":10,"B":11}
    for i, b in enumerate(blocks):
        ta, tb = b["t_start"], min(b["t_end"], t_axis_max)
        active = ta <= t_now < tb
        past = tb <= t_now
        op = 1.0 if active else (0.55 if past else 0.30)
        col = "#b8860b" if active else "#2c2620"
        fill = "rgba(154,111,24,.30)" if active else "rgba(44,38,32,.08)"
        inner.append(f'<rect x="{x(ta):.0f}" y="{y_top}" width="{x(tb)-x(ta):.0f}" height="{y_bot-y_top}" fill="{fill}" stroke="{col}" stroke-width="{2 if active else 1}" opacity="{op}"/>')
        for nm in b["names"]:
            midi = from_name[nm[:-1]] + (int(nm[-1]) + 1) * 12
            if lo <= midi <= hi:
                yy = ym(midi)
                inner.append(f'<circle cx="{(x(ta)+x(tb))/2:.0f}" cy="{yy:.0f}" r="11" fill="{col}" opacity="{op}"/>')
                if active:
                    inner.append(f'<text x="{(x(ta)+x(tb))/2:.0f}" y="{yy+7:.0f}" font-size="18" fill="#fcfaf5" text-anchor="middle" font-weight="bold">{nm[0]}{chr(0x266F) if "#" in nm else ""}</text>')
        if active:
            inner.append(f'<text x="{x(ta)+16:.0f}" y="{y_top+30}" font-size="23" fill="#b8860b" font-weight="bold">№{i+1}</text>')
    # 当前时刻指针
    inner.append(f'<line x1="{x(t_now):.0f}" y1="{y_top-16}" x2="{x(t_now):.0f}" y2="{y_bot+44}" stroke="#c9403a" stroke-width="2.5"/>')
    inner.append(f'<text x="{x(t_now)+10:.0f}" y="{y_top-18}" font-size="21" fill="#c9403a">t = 12.5s</text>')

    body = f"""<div class="frame"><div class="head"><div class="kicker">德沃夏克 · 自新世界 · 第二乐章 LARGO</div>
<h1>开场的和弦铺底<span class="sub">Cor Anglais 之前，管乐先铺好路</span></h1></div>
{svg(1780, 660, "".join(inner))}
<div class="caption">此刻响着的是 <b>№5 号和弦：A – C♯ – E</b>。九个弱奏和弦像圣咏一样铺满开头的
22 秒——英国管要到 3 分钟后才开口，先记住这层降 D 大调的底色。</div>
<div class="foot"><span>谱面真值：CC0 MIDI（Wikimedia Commons）→ 自动对齐到录音</span><span>II. Largo · 降 D 大调</span></div></div>"""
    return wrap(body)


def frame2(d):
    notes = d["notes"]
    t0, t1 = 186.0, 252.0
    x0, x1 = 0, 1740
    y_top, y_bot = 40, 620
    lo, hi = 50, 88   # E3(52) .. E6(88)
    t_now = 207.0
    def x(t): return x0 + (t - t0) / (t1 - t0) * (x1 - x0)
    def ym(m): return y_bot - (m - lo) / (hi - lo) * (y_bot - y_top)

    inner = []
    for m in range(lo, hi + 1):
        if m % 12 in (4, 9):  # E, A
            yy = ym(m)
            nm = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"][m % 12]
            inner.append(f'<line x1="{x0}" y1="{yy:.0f}" x2="{x1}" y2="{yy:.0f}" stroke="#d9cdb7" stroke-width="1"/>')
            inner.append(f'<text x="{x0-14}" y="{yy+7:.0f}" font-size="17" fill="#8a7e6c" text-anchor="end">{nm}{m//12-1}</text>')
    for t in range(186, 253, 8):
        xx = x(t)
        inner.append(f'<text x="{xx:.0f}" y="{y_bot+34}" font-size="18" fill="#8a7e6c" text-anchor="middle">{t-186}s</text>')
    # 线段：每音符一段（缺 ≥0.6s 处虚连线）
    prev_end = None
    for nt in notes:
        ta, tb, m = nt["start"], nt["end"], nt["midi"]
        if not (lo <= m <= hi):
            continue
        active = ta <= t_now < tb
        past = tb <= t_now
        col = "#b8860b" if active else "#2c2620"
        lw = 9 if active else 6
        op = 1.0 if (active or past) else 0.30
        if prev_end is not None and ta - prev_end < 0.5 and abs(m - prev_m) <= 5:
            inner.append(f'<line x1="{x(prev_end):.0f}" y1="{ym(prev_m):.0f}" x2="{x(ta):.0f}" y2="{ym(m):.0f}" stroke="#8a7e6c" stroke-width="2" opacity=".5"/>')
        inner.append(f'<line x1="{x(ta):.0f}" y1="{ym(m):.0f}" x2="{x(tb):.0f}" y2="{ym(m):.0f}" stroke="{col}" stroke-width="{lw}" opacity="{op}" stroke-linecap="round"/>')
        if active or tb - ta >= 1.2:
            nm_ = nt["name"].replace("#", chr(0x266F))
            inner.append(f'<text x="{(x(ta)+x(tb))/2:.0f}" y="{ym(m)-14:.0f}" font-size="21" fill="{col}" text-anchor="middle" opacity="{op}" font-weight="{"bold" if active else "normal"}">{nm_}</text>')
        prev_end, prev_m = tb, m
    xx = x(t_now)
    inner.append(f'<line x1="{xx:.0f}" y1="{y_top-16}" x2="{xx:.0f}" y2="{y_bot+44}" stroke="#c9403a" stroke-width="2.5"/>')
    inner.append(f'<text x="{xx+10:.0f}" y="{y_top-18}" font-size="21" fill="#c9403a">t = 207s</text>')

    body = f"""<div class="frame"><div class="head"><div class="kicker">德沃夏克 · 自新世界 · 第二乐章 LARGO</div>
<h1>英国管的旋律线<span class="sub">听音高自己走</span></h1></div>
{svg(1780, 720, "".join(inner))}
<div class="caption">此刻在唱的是 <b>G♯4</b>——主题里最长的那个音。英国管的声音像一位年长的歌者：
<b>音域不宽、几乎级进</b>，正是这种克制让这段旋律人人记得住。</div>
<div class="foot"><span>自相关泛音和声评分逐帧 f0 → 半音量化（录音实测，非谱面推算）</span><span>II. Largo · 图上 0s = 录音 186s</span></div></div>"""
    return wrap(body)


def frame3(theme_d):
    notes = theme_d["notes"]
    tmin = min(n["midi"] for n in notes)
    tmax = max(n["midi"] for n in notes)
    instruments = [
        ("长笛 Flute", "第一乐章田园副题", 60, 96, False),
        ("双簧管 Oboe", "铺底木管", 56, 93, False),
        ("英国管 Cor Anglais", "第二乐章主题的独奏者", 52, 84, True),
        ("单簧管 Clarinet", "铺底木管", 50, 94, False),
        ("大管 Bassoon", "低音木管", 34, 75, False),
        ("圆号 Horn", "开场和弦 · 末乐章召唤", 35, 77, False),
        ("小号 Trumpet", "末乐章进行式铜管", 52, 84, False),
        ("长号 Trombone", "末乐章进行式铜管", 40, 77, False),
        ("大号 Tuba", "第二乐章首尾的和弦底座", 26, 55, False),
        ("小提琴 Violin", "弦乐歌唱的主体", 55, 103, False),
        ("大提琴 Cello", "第二乐章的对唱声部", 36, 84, False),
    ]
    lo, hi = 24, 104
    x0, x1 = 470, 1560
    row_h = 52
    y0 = 60
    def x(m): return x0 + (m - lo) / (hi - lo) * (x1 - x0)

    inner = []
    for m in range(lo, hi + 1):
        if m % 12 in (4, 9):
            nm = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"][m % 12]
            inner.append(f'<line x1="{x(m):.0f}" y1="40" x2="{x(m):.0f}" y2="{y0+len(instruments)*row_h+10}" stroke="#d9cdb7" stroke-width="1"/>')
            inner.append(f'<text x="{x(m):.0f}" y="28" font-size="17" fill="#8a7e6c" text-anchor="middle">{nm}{m//12-1}</text>')
    for i, (name, role, a, b, star) in enumerate(instruments):
        yy = y0 + i * row_h
        fw = "bold" if star else "normal"
        fg = "#b8860b" if star else "#2c2620"
        inner.append(f'<text x="450" y="{yy+14:.0f}" font-size="24" fill="{fg}" text-anchor="end" font-weight="{fw}">{name}</text>')
        inner.append(f'<text x="{x1+24:.0f}" y="{yy+8:.0f}" font-size="19" fill="#8a7e6c">{role}</text>')
        h = 22 if star else 16
        fill = "#b8860b" if star else "#2c2620"
        op = 1.0 if star else 0.42
        inner.append(f'<rect x="{x(a):.0f}" y="{yy-h/2:.0f}" width="{x(b)-x(a):.0f}" height="{h}" rx="{h/2}" fill="{fill}" opacity="{op}"/>')
        if star:
            # 主题实际落点（金色带）
            inner.append(f'<rect x="{x(tmin)-3:.0f}" y="{yy-h/2-7:.0f}" width="{x(tmax)-x(tmin)+6:.0f}" height="{h+14}" rx="10" fill="none" stroke="#c9403a" stroke-width="3"/>')
            inner.append(f'<text x="{(x(tmin)+x(tmax))/2:.0f}" y="{yy-h/2-16:.0f}" font-size="19" fill="#c9403a" text-anchor="middle" font-weight="bold">主题段实测音域</text>')
    body_extra = svg(1780, 660, "".join(inner))

    body = f"""<div class="frame"><div class="head"><div class="kicker">德沃夏克 · 自新世界 · 交响曲编制</div>
<h1>谁在什么音区唱歌<span class="sub">Instrumental Ranges</span></h1></div>
{body_extra}
<div class="caption">红框圈出<b>主题段的实测音域</b>（含双簧管的应答句）——它正好坐在人声女中音的位置。这不是巧合：
德沃夏克想要的正是一件<b>「像人在说话的乐器」</b>。打击乐（定音鼓、三角铁、钹）没有固定音高，画不进这张图。</div>
<div class="foot"><span>音域带：标准管弦乐编制参考值 · 主题落点：录音实测</span><span>Op. 95 · E 小调</span></div></div>"""
    return wrap(body)


def shoot(html_path, png_path):
    cmd = [CHROME, "--headless=new", f"--screenshot={png_path}",
           f"--window-size={W},{H}", "--hide-scrollbars",
           "--use-mock-keychain", "--password-store=basic",
           "--disable-gpu", "--no-first-run",
           html_path.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    ok = png_path.exists() and png_path.stat().st_size > 10000
    print(f"[SHOT] {png_path.name}: {'ok' if ok else 'FAIL'} ({png_path.stat().st_size if png_path.exists() else 0} bytes)")
    if not ok:
        print(r.stdout[-800:], r.stderr[-800:])
    return ok


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    d1, d2 = json.loads(N1.read_text(encoding="utf-8")), json.loads(N2.read_text(encoding="utf-8"))
    frames = [("frame1-score-highlight", frame1(d1)),
              ("frame2-f0-trajectory", frame2(d2)),
              ("frame3-instrument-chart", frame3(d2))]
    ok = True
    for name, html in frames:
        hp = OUT / f"{name}.html"
        hp.write_text(html, encoding="utf-8")
        ok &= shoot(hp, OUT / f"{name}.png")
    print(f"[VERDICT] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
