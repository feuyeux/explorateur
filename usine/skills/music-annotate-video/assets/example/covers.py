"""平台封面生成：B站横版 1920×1080 + 小红书竖版 1080×1440。

视觉家族与成片一致（warm-paper + 赤金点缀）；装饰母题 = Largo 主题的
**录音实测旋律线**（theme-notes.json，非手绘）——封面即内容自证。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
THEME = BASE / "notes" / "theme-notes.json"
OUT = BASE / "build" / "publish"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
html,body { overflow:hidden; background:#f7f2e6; color:#2c2620;
  font-family:Georgia,"Times New Roman","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif; }
.kicker { letter-spacing:.42em; color:#b8860b; }
.rule { background:#b8860b; }
"""


def melody_band(w, y0, h, t0=188.0, t1=214.0, gold_note="G#4", lw=10):
    """实测旋律线装饰带：data 真值，非手绘。返回 SVG 片段。"""
    notes = [n for n in json.loads(THEME.read_text(encoding="utf-8"))["notes"]
             if t0 <= n["start"] < t1]
    pitches = [n["midi"] for n in notes]
    lo, hi = min(pitches) - 2, max(pitches) + 2
    x0, x1 = 30, w - 30

    def X(t):
        return x0 + (t - t0) / (t1 - t0) * (x1 - x0)

    def Y(m):
        return y0 + h - (m - lo) / (hi - lo) * h

    out = [f'<svg width="{w}" height="{h+40}" viewBox="0 0 {w} {h+40}" xmlns="http://www.w3.org/2000/svg">']
    prev = None
    for nt in notes:
        ta, tb, m = nt["start"], nt["end"], nt["midi"]
        col = "#b8860b" if nt["name"] == gold_note else "#2c2620"
        op = "1" if nt["name"] == gold_note else "0.82"
        if prev is not None and ta - prev[0] < 0.6 and abs(m - prev[1]) <= 5:
            out.append(f'<line x1="{X(prev[0]):.0f}" y1="{Y(prev[1]):.0f}" x2="{X(ta):.0f}" y2="{Y(m):.0f}" '
                       f'stroke="#8a7e6c" stroke-width="3" opacity=".55"/>')
        out.append(f'<line x1="{X(ta):.0f}" y1="{Y(m):.0f}" x2="{X(tb):.0f}" y2="{Y(m):.0f}" '
                   f'stroke="{col}" stroke-width="{lw if col == "#b8860b" else lw-2}" stroke-linecap="round" opacity="{op}"/>')
        prev = (tb, m)
    out.append('</svg>')
    return "".join(out)


def shot(html_str, w, h, png):
    with tempfile.TemporaryDirectory(prefix="cover-") as td:
        hp = Path(td) / "cover.html"
        hp.write_text(html_str, encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="chrome-cover-") as ud:
            cmd = [CHROME, "--headless=new", f"--screenshot={png}",
                   f"--window-size={w},{h}", "--hide-scrollbars",
                   "--use-mock-keychain", "--password-store=basic",
                   "--disable-gpu", "--no-first-run", f"--user-data-dir={ud}",
                   hp.as_uri()]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    ok = Path(png).exists() and Path(png).stat().st_size > 20000
    print(f"[COVER] {Path(png).name}: {'ok' if ok else 'FAIL'}")
    if not ok:
        print(r.stdout[-300:], r.stderr[-300:])
    return ok


def bilibili():
    W, H = 1920, 1080
    band = melody_band(1500, 0, 210, 188.0, 216.0, lw=9)
    body = f"""<div style="width:{W}px;height:{H}px;padding:80px 100px;position:relative;">
  <div class="kicker" style="font-size:26px;">古 典 音 乐 开 门 · 01</div>
  <div style="margin-top:46px;font-size:112px;font-weight:700;letter-spacing:.02em;line-height:1.16;">
    德沃夏克<br>《自新世界》</div>
  <div class="rule" style="width:170px;height:4px;margin:36px 0;"></div>
  <div style="font-size:44px;color:#b8860b;font-weight:600;">你说不出名字的那段旋律，叫乡愁</div>
  <div style="position:absolute;left:100px;bottom:60px;">{band}</div>
  <div style="position:absolute;right:100px;top:86px;font-size:28px;color:#8a7e6c;letter-spacing:.1em;">
    9 分钟 · 四个乐章 · 持续聆听</div>
</div>"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{body}</body></html>"""


def xiaohongshu():
    W, H = 1080, 1440
    band = melody_band(920, 0, 190, 188.0, 214.0, lw=8)
    body = f"""<div style="width:{W}px;height:{H}px;padding:90px 80px;position:relative;">
  <div class="kicker" style="font-size:24px;">古 典 音 乐 开 门 · 01</div>
  <div style="margin-top:120px;font-size:96px;font-weight:700;line-height:1.3;">
    你说不出名字的<br>旋律，叫乡愁</div>
  <div class="rule" style="width:150px;height:4px;margin:52px 0;"></div>
  <div style="font-size:36px;color:#8a7e6c;line-height:1.6;">德沃夏克《自新世界》<br>9 分钟，四个乐章，持续聆听</div>
  <div style="position:absolute;left:80px;bottom:170px;">{band}</div>
  <div style="position:absolute;left:80px;bottom:80px;font-size:28px;color:#b8860b;letter-spacing:.28em;">
    英 国 管 · 乡 愁</div>
</div>"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{body}</body></html>"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    ok &= shot(bilibili(), 1920, 1080, OUT / "cover_bilibili.png")
    ok &= shot(xiaohongshu(), 1080, 1440, OUT / "cover_xiaohongshu.png")
    print(f"[VERDICT] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
