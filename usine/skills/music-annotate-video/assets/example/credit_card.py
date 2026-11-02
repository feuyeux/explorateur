"""B3 工具：尾帧「制作信息页」生成器（PLAN §6 规格的落法）。

规矩（PLAN §6.2）：
  1. 所有数字必须实测，不得手抄——时长/渲染参数/开始结束时间由调用方注入实测值；
  2. 来源逐条列名，观众可自行复核；
  3. 与片头/片尾卡同源渲染（同一 HTML → Chrome headless 截图机制）；
  4. 时长按 30fps 网格吸附由装配脚本负责，本工具只出 1920×1080 PNG。

用法：python credit_card.py <facts.json> <out.png>
facts 字段见 main() 的样例（全部实测来源标注在注释）。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:1920px; height:1080px; overflow:hidden; background:#f7f2e6; color:#2c2620;
  font-family:Georgia,"Times New Roman","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif; }}
.frame {{ width:1920px; height:1080px; padding:80px 130px; display:flex; flex-direction:column; }}
.k {{ font-size:22px; letter-spacing:.4em; color:#b8860b; margin-bottom:14px; }}
h1 {{ font-size:54px; font-weight:700; letter-spacing:.03em; }}
.rule {{ width:200px; height:3px; background:#b8860b; margin:26px 0 34px; }}
table {{ border-collapse:collapse; font-size:25px; line-height:1.5; }}
td {{ padding:7px 0; vertical-align:top; }}
td.kk {{ color:#8a7e6c; width:190px; letter-spacing:.08em; }}
td.vv {{ color:#2c2620; }}
.sep {{ font-size:20px; letter-spacing:.3em; color:#a2967f; margin:26px 0 10px; }}
.foot {{ margin-top:auto; border-top:1px solid #d9cdb7; padding-top:16px;
  display:flex; justify-content:space-between; font-size:19px; color:#8a7e6c; }}
b {{ color:#b8860b; }}
</style></head><body><div class="frame">
<div class="k">PRODUCTION NOTES</div>
<h1>制作信息</h1>
<div class="rule"></div>
<table>
<tr><td class="kk">作　品</td><td class="vv">{work}</td></tr>
<tr><td class="kk">本片内容</td><td class="vv">{content}</td></tr>
<tr><td class="kk">旁　白</td><td class="vv">{narration}</td></tr>
<tr><td class="kk">画　幅</td><td class="vv">{format_}</td></tr>
<tr><td class="kk">时　长</td><td class="vv"><b>{duration}</b>（ffprobe 实测）</td></tr>
</table>
<div class="sep">—— 技术 ——</div>
<table>
<tr><td class="kk">旁白合成</td><td class="vv">{tts}</td></tr>
<tr><td class="kk">画面渲染</td><td class="vv">{render}</td></tr>
<tr><td class="kk">音画对齐</td><td class="vv">{align}</td></tr>
<tr><td class="kk">音频素材</td><td class="vv">{audio_src}</td></tr>
<tr><td class="kk">谱面素材</td><td class="vv">{score_src}</td></tr>
</table>
<div class="sep">—— 制作 ——</div>
<table>
<tr><td class="kk">产线</td><td class="vv">{platform}</td></tr>
<tr><td class="kk">开　始</td><td class="vv">{t_start}（构建日志实测）</td></tr>
<tr><td class="kk">结　束</td><td class="vv">{t_end}（成片完成时刻）</td></tr>
</table>
<div class="foot"><span>{left_foot}</span><span>{right_foot}</span></div>
</div></body></html>"""


def render(facts: dict, out_png: Path):
    html = HTML.format(**facts)
    with tempfile.TemporaryDirectory(prefix="credit-") as td:
        hp = Path(td) / "credit.html"
        hp.write_text(html, encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="chrome-credit-") as ud:
            cmd = [CHROME, "--headless=new", f"--screenshot={out_png}",
                   "--window-size=1920,1080", "--hide-scrollbars",
                   "--use-mock-keychain", "--password-store=basic",
                   "--disable-gpu", "--no-first-run", f"--user-data-dir={ud}",
                   hp.as_uri()]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if not out_png.exists() or out_png.stat().st_size < 4000:
        raise RuntimeError(f"credit card shot failed: {r.stdout[-300:]} {r.stderr[-300:]}")
    print(f"[CREDIT] {out_png}")


def main() -> int:
    facts_path, out_png = Path(sys.argv[1]), Path(sys.argv[2])
    render(json.loads(facts_path.read_text(encoding="utf-8")), out_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
