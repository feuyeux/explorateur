#!/usr/bin/env python3
"""make_covers.py — 赛事集锦的双平台首页图：B站横版 16:9 + 抖音竖版 3:4。

**为什么一张成片要出两张首页图**：同一条横版成片投两个平台，首页图必须各按
平台原生比例出。B站编辑器有 4:3（首页推荐）与 16:9（个人空间）两个裁切框，
两边都得有文字；抖音的竖封面槽实为 3:4，传 9:16 会被居中裁掉上下各 240px。

**数字不许编**：比分、进球数一律对着 fact pack（`resolve_match.py` 的产出）校，
对不上退出码 1——封面上的比分与事实源打架，比没有封面更糟。

**文字不许落在安全区外**：B站 16:9 传上去会被平台裁成中央 4:3（左右各切 240），
文字三要素必须整体落在 x240–1680 内。版式是**数据**（`LAYOUTS`），selftest 直接
断言这一点——版式一旦被改成越界，机检当场报红。

**底图不许带字幕**：从**无字幕母版**抽帧；成片已经烧了三层字幕卡，再叠封面标题
就是两层字打架。`--backdrop-image` 传的帧同样必须来自母版。

**转播比分牌必须盖住**：母版画面里烧着转播方的比分牌，它显示的是**中间态**比分
（巴萨那场是 BAR 3 ALA 0 @44:47，巴黎那场是 HAC 1 PSG 4 @68:35），与封面上的
终场比分打架。顶部实心带盖掉它——半透明压暗实测压不住（白底比分牌在 93% 压暗
下仍读得出分数），所以是**实心**段 + 羽化段。

用法：
    python3 scripts/make_covers.py --pack packs/barcelona.json \\
        --facts cover_facts.json --master master.mp4 --backdrop-time 42.5 \\
        --out build/cover --name barcelona-alaves
    python3 scripts/make_covers.py --pack p.json --facts f.json \\
        --master m.mp4 --backdrop-window w05 --windows windows.json --out out/
    python3 scripts/make_covers.py selftest

退出码：0 = 过了；1 = 判据失败（数字与事实源不一致 / 成品尺寸不对）；2 = 输入
契约不满足（缺字段、文件不在盘、参数错、版式越界）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
USINE = HERE.parents[2]

# 外部可执行文件（引号里的名字不算硬编码——解析口径见 _need）
FFMPEG = "ffmpeg"

# ---------------------------------------------------------------------------
# 版式（数据，不是代码）：文字块用显式坐标落位，**一律不用 bottom 锚定**。
#
# 为什么不用 bottom：`edge_screenshot` 的窗口高 = 画布高 + 视口亏空（实测值随
# 浏览器版本与机器变），截图后再裁回画布。视口比画布高亏空那截时，`bottom:56px`
# 的元素被压到画布**外**，裁完正好切掉底部文字（另一条产线踩过：4:3 封面尺寸对
# 但底部标题被切没）。显式 top 坐标不受亏空影响——多出来那截空在画布下面，裁掉
# 即可。安全区断言也因此能纯数据地判。
# ---------------------------------------------------------------------------

LAYOUTS: dict[str, dict] = {
    "bilibili": {
        "key": "bilibili",
        "label": "B站 · 横版 16:9（首页推荐按中央 4:3 裁）",
        "w": 1920,
        "h": 1080,
        # 与 core.covers 的 SPECS.bilibili.safe 同口径：平台把 16:9 传图裁成
        # 中央 4:3（左右各切 240px），文字必须整体落在 x240–1680 内。
        "safe": (240, 0, 1680, 1080),
        "mode": "full",
        # 顶部实心带：转播比分牌烧在母版画面里，显示的是**中间态**比分
        # （巴萨那场是 BAR 3 ALA 0 @44:47，巴黎那场是 HAC 1 PSG 4 @68:35，
        # 都与封面终场比分打架）——这条带子把它盖住。
        # **必须实心**：半透明压暗实测压不住（白底比分牌在 93% 压暗下仍然
        # 读得出 "BAR 3 / ALA 0"），中间态比分出现在封面上比没有封面更糟。
        # 实心 192px（比分牌底边最高 ~180）＋ 64px 羽化过渡。
        "topband": 256,
        "topband_solid": 192,
        "blocks": {
            "kicker": {"box": (300, 84, 1320, 52), "font": 34, "weight": 400, "lh": 1.2,
                       "ls": 0.30, "color": "accent"},
            "headline": {"box": (300, 600, 1320, 232), "font": 96, "weight": 700, "lh": 1.2,
                         "ls": 0.01, "color": "#FFFFFF", "max_lines": 2},
            "scoreline": {"box": (300, 852, 1320, 88), "font": 62, "weight": 700, "lh": 1.2,
                          "ls": 0.02, "color": "#FFFFFF"},
            "tagline": {"box": (300, 952, 1320, 52), "font": 36, "weight": 400, "lh": 1.2,
                        "ls": 0.04, "color": "rgba(255,255,255,.86)"},
        },
    },
    "douyin": {
        "key": "douyin34",
        "label": "抖音 · 竖版 3:4（竖封面槽原生，零裁切）",
        "w": 1080,
        "h": 1440,
        # SPECS.douyin34.safe = null（上传即展示）⇒ 安全区就是整张画布。
        "safe": (0, 0, 1080, 1440),
        "mode": "inset",
        # 3:4 里塞 16:9 画面：整幅内嵌（不裁主体，比中心裁切多留 58% 宽度），
        # 上下用同一帧的模糊铺底填满。内嵌画面里也烧着转播比分牌——同样用
        # 实心带盖住（带子落在内嵌框内部，跟着画面一起缩放）。
        "inset": (0, 150, 1080, 608),
        "inset_band": 112,
        "blocks": {
            "kicker": {"box": (90, 840, 900, 48), "font": 30, "weight": 400, "lh": 1.2,
                       "ls": 0.28, "color": "accent"},
            "headline": {"box": (90, 900, 900, 176), "font": 72, "weight": 700, "lh": 1.2,
                         "ls": 0.01, "color": "#FFFFFF", "max_lines": 2},
            "scoreline": {"box": (90, 1100, 900, 76), "font": 50, "weight": 700, "lh": 1.2,
                          "ls": 0.02, "color": "#FFFFFF"},
            "tagline": {"box": (90, 1200, 900, 48), "font": 30, "weight": 400, "lh": 1.2,
                        "ls": 0.04, "color": "rgba(255,255,255,.86)"},
        },
    },
}

BLOCK_ORDER = ("kicker", "headline", "scoreline", "tagline")
REQUIRED_FIELDS = ("kicker", "headline", "scoreline", "tagline", "home", "away")

# 顶部实心带的颜色（内联渐变用：实心段用不透明色，羽化段用同色 0 透明）
BAND_COLOR = "#07080c"
BAND_RGB = "7,8,12"

FONT_STACK = ("'Microsoft YaHei','PingFang SC','Hiragino Sans GB','Source Han Sans SC',"
              "'Noto Sans CJK SC','WenQuanYi Micro Hei',sans-serif")

# 比分形态：两端都是「像比分」的数（≤20）才算比分声明；日期（10-31）不算。
SCORE_RE = re.compile(r"(\d{1,2})-(\d{1,2})")


class ContractError(Exception):
    """输入契约不满足（缺字段 / 文件不在盘 / 参数错 / 版式越界）→ 退出码 2。"""


class FactError(Exception):
    """判据失败（数字与事实源不一致）→ 退出码 1。"""


# ---------------------------------------------------------------------------
# 事实面
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        raise ContractError(f"文件不存在：{path}")
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"JSON 读不动：{path}（{exc}）") from exc


def pack_score(pack: dict) -> str:
    """fact pack 里的比分（`latest_pick.score`，形如 "6-1"）。"""
    pick = pack.get("latest_pick") or {}
    score = pick.get("score")
    if not isinstance(score, str) or not score.strip():
        raise ContractError(
            "fact pack 里没有 `latest_pick.score`——封面上的比分无从校准。"
            "未解析出比赛的 pack 不许出封面（先跑 resolve_match.py）。")
    return score.strip()


def pack_counts(pack: dict) -> dict:
    counts = pack.get("event_counts")
    return counts if isinstance(counts, dict) else {}


def split_scoreline(text: str, score: str) -> tuple[str, str, str]:
    """按比分把比分条切成（主队, 比分, 客队）。比分不在条里 → 判据失败。"""
    idx = text.find(score)
    if idx < 0:
        raise FactError(f"比分条里没有事实源的比分「{score}」：{text!r}")
    return text[:idx].strip(), score, text[idx + len(score):].strip()


def text_em(s: str) -> float:
    """文本宽度（em）：全角 1.0、半角 0.5、空格 0.3。用于行宽估算。"""
    total = 0.0
    for ch in s:
        if ch == " ":
            total += 0.3
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 1.0
        else:
            total += 0.5
    return total


def assert_layout(plat: str) -> None:
    """版式自检：文字块 ⊆ 安全区、互不重叠、底边在画布内。越界 → 输入契约错。"""
    L = LAYOUTS[plat]
    sx0, sy0, sx1, sy1 = L["safe"]
    if not (0 <= sx0 < sx1 <= L["w"] and 0 <= sy0 < sy1 <= L["h"]):
        raise ContractError(f"{plat} 版式的安全区本身超出画布：{L['safe']}")
    prev_bottom = -1
    for name in BLOCK_ORDER:
        blk = L["blocks"][name]
        x, y, w, h = blk["box"]
        if x < sx0 or x + w > sx1 or y < sy0 or y + h > sy1:
            raise ContractError(
                f"{plat} 的「{name}」块 {(x, y, w, h)} 越出安全区 {L['safe']}"
                f"——平台二次裁切后这块字会不见")
        if y < prev_bottom:
            raise ContractError(f"{plat} 的「{name}」块与上一块重叠")
        if y + h > L["h"]:
            raise ContractError(f"{plat} 的「{name}」块底边超出画布")
        prev_bottom = y + h


def resolve_texts(facts: dict, plat: str) -> dict[str, str]:
    """取该平台的一套文案（平台覆写 > 通用字段）。缺字段 → 输入契约错。"""
    merged = dict(facts)
    over = facts.get(plat)
    if isinstance(over, dict):
        merged.update(over)
    out: dict[str, str] = {}
    for key in REQUIRED_FIELDS:
        val = merged.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ContractError(f"封面事实源缺字段「{key}」——每个平台四行文案都是必填")
        out[key] = val.strip()
    return out


def validate_facts(facts: dict, pack: dict, plat: str = "bilibili") -> dict:
    """封面事实源 × fact pack 的对账。返回对账结果，判不过抛异常。"""
    texts = resolve_texts(facts, plat)
    score = pack_score(pack)

    # ① 比分条必须含事实源的比分
    split_scoreline(texts["scoreline"], score)

    # ② 主客顺序：主队名要在客队名前面（防主客颠倒）
    home, away = texts["home"], texts["away"]
    if home in texts["scoreline"] and away in texts["scoreline"]:
        if texts["scoreline"].index(home) > texts["scoreline"].index(away):
            raise FactError(
                f"比分条里主客颠倒：主队「{home}」出现在客队「{away}」之后"
                f"（{texts['scoreline']!r}）")

    # ③ 文案里的比分声明必须与事实源一致（两端 ≤20 才算比分，日期不算）
    for key in ("headline", "scoreline", "tagline"):
        for a, b in SCORE_RE.findall(texts[key]):
            if int(a) <= 20 and int(b) <= 20 and f"{a}-{b}" != score:
                raise FactError(
                    f"「{key}」里写着比分 {a}-{b}，事实源是 {score}——封面数字不许编")

    # ④ 声明了进球数就必须与事件计数一致
    counts = pack_counts(pack)
    goals = facts.get("goal_count")
    if goals is not None:
        want = counts.get("goal")
        if want is None:
            raise ContractError("事实源里声明了 goal_count，但 fact pack 没有事件计数——无从校")
        if int(goals) != int(want):
            raise FactError(f"声明 {goals} 粒进球，fact pack 记的是 {want}")

    # ⑤ 主标题行宽：超行 → 输入契约错（不许靠 CSS 裁字）
    blk = LAYOUTS[plat]["blocks"]["headline"]
    x, y, w, h = blk["box"]
    font = blk["font"]
    max_lines = blk.get("max_lines", 1)
    per_line = w / font
    if text_em(texts["headline"]) > per_line * max_lines:
        raise ContractError(
            f"「headline」{texts['headline']!r} 在 {plat} 版式里超过 {max_lines} 行"
            f"（每行约 {per_line:.1f} 个全角字）——改短或换版式，不许靠裁字过关")

    return {"score": score, "texts": texts, "counts": counts}


# ---------------------------------------------------------------------------
# HTML（版式 → 整页 HTML；渲染由 core.covers 的 cover make 承担）
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _style(blk: dict, extra: str = "") -> str:
    x, y, w, h = blk["box"]
    return (f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
            f"font-size:{blk['font']}px;font-weight:{blk['weight']};"
            f"line-height:{blk['lh']};letter-spacing:{blk['ls']}em;text-indent:{blk['ls']}em;"
            f"{extra}")


def _band_div(height: int, solid: int) -> str:
    """顶部实心带（盖转播比分牌）。

    实心段 + 羽化段：`solid` 高度内完全不透明（比分牌烧在母版画面里，
    半透明压暗实测压不住），其后线性羽化到透明，免得出现一条硬边。
    """
    pct = max(0.0, min(100.0, solid / height * 100.0))
    return (f'<div class="band" style="height:{height}px;'
            f'background:linear-gradient(180deg, {BAND_COLOR} 0%, {BAND_COLOR} {pct:.1f}%,'
            f'rgba({BAND_RGB},0) 100%);"></div>')


def build_html(plat: str, texts: dict[str, str], accent: str, backdrop: Path) -> str:
    L = LAYOUTS[plat]
    w, h = L["w"], L["h"]
    src = backdrop.resolve().as_uri()
    blocks = L["blocks"]

    band = L.get("topband")
    solid = L.get("topband_solid")
    if L["mode"] == "full":
        bg = (f'<div class="bg"><img src="{esc(src)}"></div>'
              '<div class="scrim"></div><div class="cap"></div>')
        if band:
            bg += _band_div(int(band), int(solid or band))
    else:
        ix, iy, iw, ih = L["inset"]
        inner_band = L.get("inset_band")
        inner = f'<img src="{esc(src)}">'
        if inner_band:
            inner += _band_div(int(inner_band), int(inner_band * 0.82))
        bg = (f'<div class="bg blur"><img src="{esc(src)}"></div>'
              f'<div class="inset" style="left:{ix}px;top:{iy}px;width:{iw}px;height:{ih}px">'
              f'{inner}</div>'
              '<div class="scrim"></div>')

    body: list[str] = [bg]
    for name in BLOCK_ORDER:
        blk = blocks[name]
        text = texts[name]
        color = accent if blk.get("color") == "accent" else blk.get("color", "#FFFFFF")
        if name == "scoreline":
            home, score, away = split_scoreline(text, _score_of(texts))
            inner = (f'<span class="team">{esc(home)}</span>'
                     f'<span class="score" style="color:{accent}">{esc(score)}</span>'
                     f'<span class="team">{esc(away)}</span>')
        else:
            inner = esc(text)
        extra = "overflow:hidden;" if name == "headline" else ""
        body.append(f'<div class="blk" style="{_style(blk, extra)}color:{color};">{inner}</div>')

    css = f"""
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:#0a0a0c;}}
*{{box-sizing:border-box;}}
.bg{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;overflow:hidden;}}
.bg img{{width:100%;height:100%;object-fit:cover;display:block;}}
.bg.blur img{{filter:blur(46px) saturate(1.15) brightness(.5);transform:scale(1.12);}}
.inset{{position:absolute;overflow:hidden;box-shadow:0 18px 60px rgba(0,0,0,.55);}}
.inset img{{width:100%;height:100%;object-fit:cover;display:block;}}
.scrim{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;
background:linear-gradient(to top, rgba(6,7,10,.92) 0%, rgba(6,7,10,.74) 26%,
rgba(6,7,10,.22) 56%, rgba(6,7,10,0) 78%);}}
.cap{{position:absolute;left:0;top:0;width:{w}px;height:{h}px;
background:linear-gradient(to bottom, rgba(6,7,10,.42) 0%, rgba(6,7,10,0) 18%);}}
/* 顶部实心带：样式在 _band_div 里内联（实心段 + 羽化段的长度随版式变）*/
.band{{position:absolute;left:0;top:0;width:{w}px;}}
.inset .band{{width:100%;}}
.blk{{position:absolute;font-family:{FONT_STACK};-webkit-font-smoothing:antialiased;
text-shadow:0 4px 24px rgba(0,0,0,.72),0 1px 3px rgba(0,0,0,.55);}}
.scoreline .team{{font-weight:400;}}
.scoreline .score{{font-weight:800;padding:0 .22em;}}
"""
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body>{"".join(body)}</body></html>')


def _score_of(texts: dict[str, str]) -> str:
    """从比分条里取出比分 token（形如 6-1）。取不出 → 输入契约错。"""
    m = SCORE_RE.search(texts["scoreline"])
    if not m:
        raise ContractError(f"比分条里没有「x-y」形态的比分：{texts['scoreline']!r}")
    return m.group(0)


# ---------------------------------------------------------------------------
# 底图与渲染
# ---------------------------------------------------------------------------

def png_size(path: Path) -> tuple[int, int]:
    """PNG 头里的宽高（纯字节解析，不引第三方依赖）。"""
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ContractError(f"不是 PNG：{path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _need(binary: str) -> str:
    """解析外部可执行文件。

    优先环境变量覆盖（`FEUILLE_FFMPEG`），否则在 PATH 里找。全仓的跨平台解析
    事实源是 @feuille/core 的 platform resolver；这个脚本是 skill 内的独立
    Python 脚本，用同样的「可覆盖 + 找不到就报错」口径，**不静默拿别的同名
    程序顶替**（口径与同族的 probe_scoreboard.py 一致）。
    """
    env = os.environ.get(f"FEUILLE_{binary.upper()}")
    if env:
        if not Path(env).exists():
            raise ContractError(f"环境变量 FEUILLE_{binary.upper()} 指向的文件不存在：{env}")
        return env
    path = shutil.which(binary)
    if not path:
        raise ContractError(f"找不到 {binary}——装好它，或用 FEUILLE_{binary.upper()} 指定路径。")
    return path


def extract_frame(master: Path, t: float, out_png: Path) -> None:
    """从**无字幕母版**抽帧，预裁成 16:9（1920×1080）。"""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_need(FFMPEG), "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(master),
           "-frames:v", "1",
           "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
           str(out_png)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_png.exists():
        raise ContractError(f"抽帧失败（t={t:.3f}s）：{proc.stderr.strip()[:400]}")


def prepare_image(src: Path, out_png: Path) -> None:
    """把已有帧也预裁成 16:9（与抽帧同一口径）。"""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_need(FFMPEG), "-y", "-v", "error", "-i", str(src), "-frames:v", "1",
           "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
           str(out_png)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_png.exists():
        raise ContractError(f"底图预裁失败：{proc.stderr.strip()[:400]}")


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """跑 feuille CLI（pnpm exec）。Windows 上 pnpm 可能是 .cmd/.exe 两种形态。"""
    exe = shutil.which("pnpm") or shutil.which("pnpm.cmd")
    if exe is None:
        raise ContractError("PATH 上找不到 pnpm——封面渲染要走 `pnpm exec feuille cover make`")
    cmd = [exe, "exec", "feuille", *args]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *cmd]
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def render_cover(key: str, html: Path, png: Path, workdir: Path) -> None:
    """渲封面：整页 HTML → 平台规格整图（尺寸/裁齐由 core.covers 保证）。"""
    png.parent.mkdir(parents=True, exist_ok=True)
    proc = run_cli(["cover", "make", key, str(html), str(png)], USINE)
    if proc.returncode != 0 or not png.exists():
        raise ContractError(
            f"封面渲染失败（{key}）：{(proc.stderr or proc.stdout).strip()[:600]}")
    # cover make 会把 HTML 副本与视口探针落在 cwd（=USINE）——跑批不留副作用。
    for stray in (USINE / f"{png.stem}.html", USINE / "_vp_probe.html"):
        if stray.exists():
            stray.unlink()


def crop_preview(png: Path, plat: str, out_png: Path) -> None:
    """模拟平台信息流的真实展示裁切（B站 16:9 → 中央 4:3；抖音 3:4 无裁切）。"""
    L = LAYOUTS[plat]
    sx0, sy0, sx1, sy1 = L["safe"]
    if (sx0, sy0, sx1, sy1) == (0, 0, L["w"], L["h"]):
        shutil.copyfile(png, out_png)
        return
    cmd = [_need(FFMPEG), "-y", "-v", "error", "-i", str(png),
           "-vf", f"crop={sx1 - sx0}:{sy1 - sy0}:{sx0}:{sy0}", str(out_png)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_png.exists():
        raise ContractError(f"裁切预览失败：{proc.stderr.strip()[:400]}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def window_midpoint(windows: list[dict], key: str) -> float:
    for w in windows:
        if w.get("key") == key:
            t0, t1 = w.get("t0"), w.get("t1")
            if t0 is None and isinstance(w.get("src"), str):
                m = re.match(r"^([\d.]+)-([\d.]+)$", w["src"])
                if m:
                    t0, t1 = float(m.group(1)), float(m.group(2))
            if t0 is None or t1 is None:
                raise ContractError(f"窗口 {key} 没有时间区间（t0/t1 或 src）")
            return (float(t0) + float(t1)) / 2
    raise ContractError(f"窗口表里没有 {key} 这一窗")


def team_zh_name(team_key: str) -> str:
    teams = load_json(SKILL / "assets" / "teams.json")
    entry = (teams.get("teams") or {}).get(team_key)
    if not entry:
        raise ContractError(f"teams.json 里没有队伍 {team_key}")
    return entry.get("zh", "")


def build(args: argparse.Namespace) -> int:
    pack = load_json(Path(args.pack))
    facts = load_json(Path(args.facts))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    plats = ["bilibili", "douyin"] if args.only == "both" else [args.only]
    for plat in plats:
        assert_layout(plat)

    # 底图：母版抽帧 / 已有帧
    backdrop = out_dir / "backdrop_16x9.png"
    if args.backdrop_image:
        prepare_image(Path(args.backdrop_image), backdrop)
    else:
        if not args.master:
            raise ContractError("要抽帧就得给 --master（无字幕母版）")
        master = Path(args.master)
        if not master.exists():
            raise ContractError(f"母版不在盘：{master}")
        if args.backdrop_window:
            if not args.windows:
                raise ContractError("--backdrop-window 要配 --windows 窗口表")
            windows = load_json(Path(args.windows))
            if isinstance(windows, dict):
                windows = windows.get("windows", [])
            t = window_midpoint(windows, args.backdrop_window)
        elif args.backdrop_time is not None:
            t = float(args.backdrop_time)
        else:
            raise ContractError("底图三选一：--backdrop-window / --backdrop-time / --backdrop-image")
        extract_frame(master, t, backdrop)

    accent = "#F2C14E"
    colors = facts.get("colors")
    if isinstance(colors, dict) and isinstance(colors.get("accent"), str):
        accent = colors["accent"].strip() or accent

    report: dict = {"facts_source": str(args.facts), "pack_source": str(args.pack),
                    "backdrop": str(backdrop), "covers": {}}
    for plat in plats:
        L = LAYOUTS[plat]
        checked = validate_facts(facts, pack, plat)
        texts = checked["texts"]
        if args.team_key:
            zh = team_zh_name(args.team_key)
            if zh and zh not in texts["scoreline"]:
                raise FactError(
                    f"比分条里没有队伍 {args.team_key} 的中文名「{zh}」——队伍张冠李戴")
        html = build_html(plat, texts, accent, backdrop)
        html_path = out_dir / f"cover_{plat}.html"
        html_path.write_text(html, "utf-8")
        png = out_dir / f"{args.name}_{L['key']}_{L['w']}x{L['h']}.png"
        render_cover(L["key"], html_path, png, out_dir)
        got = png_size(png)
        if got != (L["w"], L["h"]):
            raise FactError(f"{plat} 封面尺寸 {got[0]}×{got[1]} ≠ 规格 {L['w']}×{L['h']}")
        preview = out_dir / f"preview_{plat}.png"
        crop_preview(png, plat, preview)
        report["covers"][plat] = {
            "png": str(png), "preview": str(preview), "html": str(html_path),
            "size": [got[0], got[1]], "score": checked["score"],
            "safe": list(L["safe"]),
        }
        print(f"  ✅ {plat:<9} {got[0]}×{got[1]}  {png.name}")

    (out_dir / "covers.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n首页图 {len(report['covers'])} 张 → {out_dir}")
    print("下一步：按 references/publishing-and-covers.md 写两份发布描述，"
          "再用 `feuille copy check` 过机检。")
    return 0


# ---------------------------------------------------------------------------
# selftest（离线：纯函数 + 反向验证）
# ---------------------------------------------------------------------------

def _good_facts() -> dict:
    return {
        "kicker": "西甲 · 第 11 轮",
        "headline": "莱万梅开二度",
        "scoreline": "巴塞罗那 6-1 阿拉维斯",
        "tagline": "7 粒进球 · 10 次换人",
        "home": "巴塞罗那",
        "away": "阿拉维斯",
        "colors": {"accent": "#EDBB00"},
    }


def _good_pack() -> dict:
    return {
        "latest_pick": {"score": "6-1", "home": "FC Barcelona", "away": "Deportivo Alaves"},
        "event_counts": {"goal": 7, "substitution": 10, "card": 5, "var": 1},
    }


def selftest() -> int:
    passed = 0
    failed: list[str] = []

    def case(name: str, fn) -> None:
        nonlocal passed
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except AssertionError as exc:
            failed.append(name)
            print(f"  ❌ {name}：{exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  ❌ {name}：{type(exc).__name__} {exc}")

    def expect_raises(exc_type, fn) -> None:
        try:
            fn()
        except exc_type:
            return
        raise AssertionError(f"应当抛 {exc_type.__name__}，却没抛")

    # 1. 版式：文字块 ⊆ 安全区、不重叠、底边在画布内
    def t_layout():
        for plat in LAYOUTS:
            assert_layout(plat)
    case("版式自检：两版式的文字块都在安全区内", t_layout)

    # 2. 反向：块挪出安全区 → 必须报错
    def t_layout_bad():
        saved = LAYOUTS["bilibili"]["blocks"]["headline"]["box"]
        LAYOUTS["bilibili"]["blocks"]["headline"]["box"] = (40, 600, 1320, 232)
        try:
            expect_raises(ContractError, lambda: assert_layout("bilibili"))
        finally:
            LAYOUTS["bilibili"]["blocks"]["headline"]["box"] = saved
    case("反向：文字块挪出 B 站安全区 → 报红", t_layout_bad)

    # 3. 好例过
    def t_good():
        out = validate_facts(_good_facts(), _good_pack(), "bilibili")
        assert out["score"] == "6-1", out
    case("好例：封面事实源 × fact pack 对账通过", t_good)

    # 4. 比分不符 → FactError
    def t_bad_score():
        f = _good_facts()
        f["scoreline"] = "巴塞罗那 3-0 阿拉维斯"
        expect_raises(FactError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：比分条与事实源不符 → 报红", t_bad_score)

    # 5. headline 里另写一个比分 → FactError
    def t_bad_headline_score():
        f = _good_facts()
        f["headline"] = "3-0 完胜"
        expect_raises(FactError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：主标题里编比分 → 报红", t_bad_headline_score)

    # 5b. 比分条里夹第二个比分 → FactError
    def t_bad_scoreline_extra():
        f = _good_facts()
        f["scoreline"] = "巴塞罗那 6-1 阿拉维斯（此前 3-0）"
        expect_raises(FactError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：比分条里夹第二个比分 → 报红", t_bad_scoreline_extra)

    # 6. 日期不是比分（10-31 不该被当成比分声明）
    def t_date_ok():
        f = _good_facts()
        f["tagline"] = "10-31 主场 · 7 粒进球"
        validate_facts(f, _good_pack(), "bilibili")
    case("反向：日期 10-31 不被误判成比分", t_date_ok)

    # 7. 主客颠倒 → FactError
    def t_swap():
        f = _good_facts()
        f["scoreline"] = "阿拉维斯 6-1 巴塞罗那"
        expect_raises(FactError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：比分条主客颠倒 → 报红", t_swap)

    # 8. 进球数与事件计数不符 → FactError
    def t_goal_count():
        f = _good_facts()
        f["goal_count"] = 5
        expect_raises(FactError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：声明进球数与事件计数不符 → 报红", t_goal_count)

    # 9. 缺字段 → ContractError
    def t_missing():
        f = _good_facts()
        del f["headline"]
        expect_raises(ContractError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：缺 headline 字段 → 输入契约错", t_missing)

    # 10. pack 没解析出比赛 → ContractError
    def t_unresolved_pack():
        expect_raises(ContractError,
                      lambda: validate_facts(_good_facts(), {"latest_pick": {}}, "bilibili"))
    case("反向：fact pack 未解析出比赛 → 拒出封面", t_unresolved_pack)

    # 11. 主标题超行 → ContractError
    def t_too_long():
        f = _good_facts()
        # B站 16:9 的 headline 每行约 13.7 个全角字 × 2 行 ≈ 27 字 → 40 字必超行
        f["headline"] = "莱万梅开二度之后是巴萨全场压制式的控球与逼抢以及登贝莱的连续突破"
        expect_raises(ContractError, lambda: validate_facts(f, _good_pack(), "bilibili"))
    case("反向：主标题超行 → 报红（不许靠裁字过关）", t_too_long)

    # 12. HTML：尺寸、块数、文字转义
    def t_html():
        html = build_html("bilibili", resolve_texts(_good_facts(), "bilibili"),
                          "#EDBB00", Path("x.png"))
        assert "width:1920px;height:1080px" in html, "画布尺寸没进 CSS"
        assert html.count('class="blk"') == 4, "文字块数不对"
        assert "巴塞罗那" in html and "6-1" in html, "比分条没进 HTML"
        esc_html = build_html("bilibili",
                              {**resolve_texts(_good_facts(), "bilibili"),
                               "headline": "A&B<C>"},
                              "#EDBB00", Path("x.png"))
        assert "A&amp;B&lt;C&gt;" in esc_html, "文字没转义"
    case("HTML：画布尺寸 / 块数 / 文字转义", t_html)

    # 13. 抖音版式：内嵌画面 + 文字块
    def t_html_douyin():
        html = build_html("douyin", resolve_texts(_good_facts(), "douyin"),
                          "#EDBB00", Path("x.png"))
        assert "width:1080px;height:1440px" in html, "抖音画布尺寸不对"
        assert 'class="inset"' in html, "抖音内嵌画面缺失"
    case("HTML：抖音 3:4 内嵌画面", t_html_douyin)

    # 13b. 顶部实心带：必须不透明（半透明压不住转播比分牌）
    def t_band_opaque():
        html = build_html("bilibili", resolve_texts(_good_facts(), "bilibili"),
                          "#EDBB00", Path("x.png"))
        assert 'class="band"' in html, "B站封面没有顶部带"
        assert BAND_COLOR in html, "顶部带不是实心色（半透明压不住比分牌）"
        assert f"rgba({BAND_RGB},0)" in html, "顶部带没有羽化段"
        dy = build_html("douyin", resolve_texts(_good_facts(), "douyin"),
                        "#EDBB00", Path("x.png"))
        assert 'class="band' in dy, "抖音内嵌画面没有顶部带"
    case("顶部实心带：两版式都盖住转播比分牌", t_band_opaque)

    # 14. PNG 头解析
    def t_png():
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
                          + (1920).to_bytes(4, "big") + (1080).to_bytes(4, "big") + b"\x00" * 8)
            assert png_size(p) == (1920, 1080), png_size(p)
    case("PNG 头解析：宽高读得出", t_png)

    # 15. 窗口中点
    def t_window():
        wins = [{"key": "w05", "t0": 36, "t1": 42}]
        assert window_midpoint(wins, "w05") == 39.0
        wins2 = [{"key": "w06", "src": "42.0-48.0"}]
        assert window_midpoint(wins2, "w06") == 45.0
        expect_raises(ContractError, lambda: window_midpoint(wins, "w99"))
    case("窗口中点：t0/t1 与 src 两种写法都认", t_window)

    print(f"\n{'通过' if not failed else '未通过'}：{passed}/{passed + len(failed)}")
    if failed:
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()

    ap = argparse.ArgumentParser(description="赛事集锦双平台首页图（B站 16:9 + 抖音 3:4）")
    ap.add_argument("--pack", help="fact pack JSON（resolve_match.py 的产出）")
    ap.add_argument("--facts", help="封面事实源 JSON（内容面：四行文案 + 队名 + 配色）")
    ap.add_argument("--master", help="无字幕母版（抽帧用）")
    ap.add_argument("--windows", help="窗口表 JSON（配合 --backdrop-window）")
    ap.add_argument("--backdrop-window", help="取哪一窗的中点帧作底图")
    ap.add_argument("--backdrop-time", type=float, help="母版秒数")
    ap.add_argument("--backdrop-image", help="已有帧（必须来自无字幕母版）")
    ap.add_argument("--out", default="build/cover", help="输出目录")
    ap.add_argument("--name", default="match", help="文件名前缀（赛事 slug）")
    ap.add_argument("--team-key", help="队伍 key（查 teams.json 校中文名）")
    ap.add_argument("--only", choices=["both", "bilibili", "douyin"], default="both")
    args = ap.parse_args(argv)

    try:
        return build(args)
    except FactError as exc:
        print(f"❌ 判据失败：{exc}", file=sys.stderr)
        return 1
    except ContractError as exc:
        print(f"❌ 输入契约不满足：{exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"❌ 外部命令失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
