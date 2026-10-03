#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intro_cards.py — 28 x 10s 班底亮相卡渲染管线（plan.md §8 契约的实现）
RTL 4 卡另渲女性观众版 <id>_f.mp4（self-intro §1.4：双性别版本各渲一遍，缓存键互不串扰）

数据：personas/personas.json + personas/intro-cards.json
产物：build/intro/<id>.mp4（1080x1920, 30fps, 10.0s, 含烘焙音频）

用法（uv 管理单一 .venv）：
  uv run usine-cards tts     [--only id1,id2]   # edge-tts 7.2.8：逐行合成 + 词级时间戳
  uv run usine-cards assets  [--only id1,id2]   # Edge headless 渲染文字层 PNG
  uv run usine-cards render  [--only id1,id2] [--workers 6]   # Pillow：帧渲染 + ffmpeg
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from usine import ROOT

HERE = ROOT                              # 仓库根（personas/ 与 build/ 的锚点，不依赖 cwd）
BUILD = HERE / "build" / "intro"
AUDIO_DIR = BUILD / "audio"
TEXT_DIR = BUILD / "text"
OUT_DIR = BUILD

W, H, FPS, DUR = 1080, 1920, 30, 10.0
FRAMES = int(FPS * DUR)
BAND_Y, BAND_H = 100, 300
UI_INK = "#23283D"  # 名牌/语言牌/气泡描边与投影（与文字带底色同族的墨色）
BAND_BG = (35, 40, 63)  # #23283F
# 帧内布局基准（qa 探针同源引用，永不手抄——不变量⑩）
BADGE_Y, BADGE_BOX_H = 470, 240        # 名牌：粘贴基准行
PILL_Y, PILL_BOX_H = 726, 96           # 语言牌：粘贴基准行
BUBBLE_CY, BUBBLE_CX = 915, 300        # 气泡：中心 y / LTR 中心 x（RTL 取 W−）
PROG_X0, PROG_Y0, PROG_X1, PROG_Y1 = 60, 40, 1020, 56  # 进度条外框

THEME = {  # 人物/道具常量色唯一事实源（plan §7.2-1：色值只存于 personas.json 与主题文件；qa_char 同源引用）
    "ink": (46, 42, 54),             # 瞳孔/眉毛/口型线（无描边人物的唯一深色）
    "mouth": (122, 54, 60), "tongue": (236, 120, 112), "blush": (247, 197, 185),
    "shoe": (56, 56, 64),
    "gold": (232, 194, 74), "pearl": (246, 242, 234), "beads": (162, 120, 70),
    "bracelet_leather": (122, 88, 58), "bracelet_woven": (204, 172, 120),
    "metal_dark": (44, 44, 52), "lens": (70, 76, 92), "camera_body": (70, 70, 78),
    "headphones": (60, 60, 70), "lens_blue": (152, 194, 214), "glint_blue": (206, 226, 238),
    "glint_soft": (226, 238, 246), "hairpin_clear": (206, 236, 246), "scarf_red": (196, 88, 74),
    "glasses_plastic": (58, 74, 44), "glasses_thin": (66, 66, 76), "glasses_dark": (56, 60, 72),
    "headband_red": (214, 69, 65),   # 红发带（意大利三色旗 wink 的红条）
    "it_flag": ((0, 146, 70), (255, 255, 255), (214, 69, 65)),
    "straw": (246, 240, 226), "apron": (238, 233, 221),
    "paper": (250, 246, 236), "paper_map": (242, 235, 216), "paper_tote": (250, 246, 238),
    "book_leather": (122, 94, 70), "pen_blue": (58, 72, 96), "satchel": (122, 92, 62),
    "bottle_blue": (122, 184, 202), "bottle_green": (152, 202, 172), "bottle_green_dark": (120, 160, 132),
    "ball": (232, 138, 66), "ball_line": (120, 60, 30),
    "skate_deck": (240, 156, 84), "skate_wheel": (70, 70, 78),
    "bag_canvas": (245, 240, 230), "bag_woven": (226, 200, 160), "bag_pouch": (238, 226, 208),
    "sparkle": (255, 208, 92),
    "shade_dark": (25, 25, 32),      # 服装体积影/袖口混入色
}
NECK_SHADE_F = 0.45                  # 颈部 skinShade 混入比（qa_char 同源）


# 场景中性色（单一事实源：场景原语只引用本表 / pal 令牌 / mix()，禁写字面 RGB——不变量⑤）
SCENE = {
    "white": (255, 255, 255),    # 蒸汽/粉笔/高光
    "lamp": (75, 75, 75),        # 灯杆/电线/护栏/路缘
    "night_blue": (43, 48, 70),  # 夜色楼体/招牌底
    "metal": (150, 150, 155),    # 卷帘门/金属构件
    "sun1": (255, 214, 150),     # 晨昏天光三层
    "sun2": (255, 205, 160),
    "sun3": (255, 190, 140),
    "lantern": (255, 214, 90),   # 灯笼/灯串暖黄
    "glow": (255, 230, 160),     # 灯箱/窗光
    "glow2": (255, 235, 190),    # 橱窗光
    "chalk": (255, 235, 180),    # 暖粉笔/卷帘门亮条
    "stem": (120, 150, 100),     # 花茎
    "grass": (120, 165, 110),    # 草地/松枝
    "grass2": (120, 160, 110),   # 远山绿
    "wood": (140, 115, 90),      # 树干/木杆
    "wood2": (230, 180, 90),     # 木牌/遮阳篷骨
    "sky": (180, 220, 240),      # 天光/水面
    "sky2": (200, 228, 245),     # 水族箱体
    "sky3": (150, 200, 225),     # 镜面水面
    "steam": (160, 210, 230),    # 蒸笼/蒸汽层
    "flower": (255, 170, 90),    # 花瓣/灯串
    "blossom": (255, 210, 110),  # 霓虹花瓣
    "peach": (255, 170, 120),    # 灯罩暖光
    "sign": (200, 90, 90),       # 招牌红
    "cyan": (90, 220, 240),      # 霓虹青
    "pink": (255, 170, 200),     # 霓虹粉
    "snow": (250, 250, 250),     # 山顶积雪
    "peach2": (255, 190, 120),   # 摊位灯罩暖光
}
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


# ---------- 数据 ----------

def load_data():
    personas = {p["id"]: p for p in json.loads((HERE / "personas" / "personas.json").read_text("utf-8"))["personas"]}
    cards_doc = json.loads((HERE / "personas" / "intro-cards.json").read_text("utf-8"))
    return personas, cards_doc


def card_units(doc):
    """渲染单元展开：主卡 + RTL 女性观众版变体（self-intro §1.4）。
    变体共享人设/场景/收尾/手势，仅 lines 不同（缓存键随文本自然独立）。"""
    units = []
    for c in doc["cards"]:
        units.append({"id": c["id"], "persona": c["id"], "card": c})
        for v in c.get("variants", []):
            units.append({"id": v["id"], "persona": c["id"], "card": c, "variant": v})
    return units


def find_card(doc, pid):
    for c in doc["cards"]:
        if c["id"] == pid:
            return c, None
        for v in c.get("variants", []):
            if v["id"] == pid:
                return c, v
    raise KeyError(pid)


def parse_signed(s, suffix):
    s = s.strip().rstrip(suffix)
    return int(float(s))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def effective_voice(persona, mood, mood_table):
    base_r = parse_signed(persona["voice"]["rate"], "%")
    base_p = parse_signed(persona["voice"]["pitch"], "Hz")
    dr, dp = mood_table[mood]
    r = clamp(base_r + dr, -20, 20)
    p = clamp(base_p + dp, -12, 12)
    return f"{r:+d}%", f"{p:+d}Hz"


def content_hash(*parts):
    return hashlib.sha256("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:16]


def rnd(seed):
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def gaze(seed, t):
    """视线跟随镜头（requirement §3.2 / plan §4 gaze="camera"）：瞳孔绕镜头注视点做
    种子化微漂移＋短促扫视，确定性幂等。返回 (dx, dy)∈[-1,1]；
    像素幅度 = (巩膜−瞳孔) 余量 × 0.35（探针安全余量内，qa_char 同源引用）。"""
    ph = 2 * math.pi * rnd(f"{seed}:gaze")
    gx = 0.45 * math.sin(2 * math.pi * 0.19 * t + ph)
    gy = 0.30 * math.sin(2 * math.pi * 0.13 * t + ph * 1.7)
    cyc = 2.6
    t0 = rnd(f"{seed}:gaze:phase") * cyc
    k = int((t + t0) / cyc)
    tt = (t + t0) - k * cyc
    if tt < 0.22:  # 短促扫视：幅度/方向按扫视序号锁定
        amp = rnd(f"{seed}:sacc:{k}")
        gx += 0.55 * amp * math.sin(2 * math.pi * rnd(f"{seed}:sxa:{k}"))
        gy += 0.35 * amp * math.cos(2 * math.pi * rnd(f"{seed}:sya:{k}"))
    return clamp(gx, -1, 1), clamp(gy, -1, 1)


def phys(seed, code, kind, t):
    """挂件物理（requirement §3.4 / plan §7.3-4 四锚点分层）：相位频率种子化，确定性幂等。
    swing→(dx,dy) 摆动；bounce→(0,dy) 颠动；reflect→(dx,0) 高光位移。"""
    ph = 2 * math.pi * rnd(f"{seed}:phys:{code}")
    if kind == "swing":
        return (5.0 * math.sin(2 * math.pi * 0.85 * t + ph),
                1.6 * abs(math.cos(2 * math.pi * 0.85 * t + ph)))
    if kind == "bounce":
        return (0.0, -3.0 * abs(math.sin(2 * math.pi * 1.15 * t + ph)))
    if kind == "reflect":
        return (9.0 * math.sin(2 * math.pi * 0.55 * t + ph), 0.0)
    return (0.0, 0.0)


def jump_height(p):
    """mini_jump 起跳高度：movement.bounce 越小越弹（plan §4 个性参数；qa_char 同源引用）。"""
    return 60 + 28 * clamp(14.0 / p["movement"]["bounce"], 0.75, 1.6)


# ---------- TTS 阶段（系统 Python + edge-tts） ----------

async def synth_line(text, voice, rate, pitch):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    mp3 = bytearray()
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "t": chunk["offset"] / 1e7,
                "d": chunk["duration"] / 1e7,
                "w": chunk["text"],
            })
    if not words:  # 兜底：整行一个伪词
        words = [{"t": 0.05, "d": 0.5, "w": text[:12]}]
    return bytes(mp3), words


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def compose_audio(card_id, line_files, starts, out_m4a):
    n = len(line_files)
    inputs = []
    for f in line_files:
        inputs += ["-i", str(f)]
    fc = []
    for i, s in enumerate(starts):
        ms = int(round(s * 1000))
        fc.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(n))
    if n > 1:
        fc.append(f"{mix}amix=inputs={n}:normalize=0[m]")
        mixed = "[m]"
    else:
        mixed = mix
    # apad 必须放在 loudnorm **之前**：loudnorm 后接 apad 是非确定的 EOF 冲刷竞态
    # （2026-10-03 实测 10 连跑 3 次丢补尾 → theo 9.469s；前置 apad 10/10 全 10.0s；
    #  loudnorm 为门控响度，补的静音不影响增益——手册坑③修正口径）
    fc.append(f"{mixed}apad=whole_dur={DUR},loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{DUR}[out]")
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]",
           "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out_m4a)]
    subprocess.run(cmd, check=True, capture_output=True)


def cmd_tts(only):
    personas, doc = load_data()
    moods = doc["moods"]
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for unit in card_units(doc):
        card, variant = unit["card"], unit.get("variant")
        pid = unit["id"]
        if only and unit["persona"] not in only:
            continue
        p = personas[unit["persona"]]
        card_lines = variant["lines"] if variant else card["lines"]
        entry = 0.8 if p["energy"] == "lively" else 1.2
        lines_out, files = [], []
        for idx, ln in enumerate(card_lines):
            rate, pitch = effective_voice(p, ln["mood"], moods)
            key = content_hash(p["voice"]["voiceId"], rate, pitch, ln["text"])
            mp3_path = AUDIO_DIR / f"{key}.mp3"
            words_path = AUDIO_DIR / f"{key}.json"
            if not mp3_path.exists() or not words_path.exists():
                data, words = asyncio.run(synth_line(ln["text"], p["voice"]["voiceId"], rate, pitch))
                mp3_path.write_bytes(data)
                words_path.write_text(json.dumps(words, ensure_ascii=False), "utf-8")
                print(f"[tts] synth {pid} line{idx} {rate} {pitch} key={key}")
            words = json.loads(words_path.read_text("utf-8"))
            dur = probe_duration(mp3_path)
            # 词级真值裁尾：edge-tts 的 mp3 尾部常有 0.5–1.5s 静音，
            # 用末词结束点 +0.2s 作为行时长（兜底伪词不裁，避免误伤）。
            if not (len(words) == 1 and words[0]["w"] == ln["text"][:12]):
                dur = min(dur, words[-1]["t"] + words[-1]["d"] + 0.20)
            lines_out.append({"key": key, "mood": ln["mood"], "dur": dur, "words": words})
            files.append(mp3_path)
        # 排时间线：入口 + 行间 0.18s；超 9.3s 则压到 0.12s，再超则提前入口
        gap = 0.18
        t = entry
        for lo in lines_out:
            lo["start"] = t
            t = lo["start"] + lo["dur"] + gap
        speech_end = t - gap
        if speech_end > 9.3:
            gap = 0.12
            t = entry
            for lo in lines_out:
                lo["start"] = t
                t = lo["start"] + lo["dur"] + gap
            speech_end = t - gap
        if speech_end > 9.55:
            entry = max(0.55, entry - 0.3)
            t = entry
            for lo in lines_out:
                lo["start"] = t
                t = lo["start"] + lo["dur"] + gap
            speech_end = t - gap
        if speech_end > 8.5:  # 时长预算（handbook §2）：超限回改文本，绝不调声线
            print(f"[tts] WARN {pid} speech_end={speech_end:.2f}s exceeds budget")
        # 绝对词时间
        for lo in lines_out:
            for w in lo["words"]:
                w["s"] = lo["start"] + w["t"]
                w["e"] = w["s"] + w["d"]
        m4a = AUDIO_DIR / f"{pid}.m4a"
        compose_audio(pid, files, [lo["start"] for lo in lines_out], m4a)
        tl = {"id": pid, "entry": entry, "speechEnd": speech_end, "lines": lines_out}
        (AUDIO_DIR / f"{pid}.timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), "utf-8")
        print(f"[tts] {pid} entry={entry} speech_end={speech_end:.2f}s lines={len(lines_out)}")


# ---------- 文字层（Edge headless） ----------

FONT_CSS = {
    "zh-CN": "'Microsoft YaHei', sans-serif", "zh-HK": "'Microsoft YaHei', sans-serif",
    "en-US": "'Segoe UI', Arial, sans-serif", "fr-FR": "'Segoe UI', Arial, sans-serif",
    "de-DE": "'Segoe UI', Arial, sans-serif", "es-ES": "'Segoe UI', Arial, sans-serif",
    "it-IT": "'Segoe UI', Arial, sans-serif", "ru-RU": "'Segoe UI', Arial, sans-serif",
    "el-GR": "'Segoe UI', Arial, sans-serif",
    "ja-JP": "'Yu Gothic UI', 'Meiryo', sans-serif", "ko-KR": "'Malgun Gothic', sans-serif",
    "hi-IN": "'Nirmala UI', sans-serif", "ar-SA": "'Segoe UI', 'Tahoma', sans-serif",
    "he-IL": "'Segoe UI', Arial, sans-serif",
}

FLAG = {  # plan §7.2-3：标识色永远与国旗 emoji＋语种文字双通道冗余（语言牌承载）。
    # Windows Segoe UI Emoji 无国旗字形 → 回退渲染为双字母对（CN/DE…，Windows 全平台一致行为）；
    # 国旗字形平台（macOS/移动端）渲染真旗。禁为"补旗"私画简化国旗（沙/港/印徽记不可简化，错旗比字母对更糟）。
    "zh-CN": "🇨🇳", "en-US": "🇺🇸", "fr-FR": "🇫🇷", "de-DE": "🇩🇪", "es-ES": "🇪🇸",
    "ru-RU": "🇷🇺", "el-GR": "🇬🇷", "ar-SA": "🇸🇦", "hi-IN": "🇮🇳", "ja-JP": "🇯🇵",
    "ko-KR": "🇰🇷", "it-IT": "🇮🇹", "he-IL": "🇮🇱", "zh-HK": "🇭🇰",
}

HTML_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg};
font-family:{font};-webkit-font-smoothing:antialiased;direction:{dir};}}
#wrap{{width:{w}px;height:{h}px;display:flex;align-items:center;justify-content:center;}}
</style></head><body>{body}<script>document.body.offsetHeight;</script></body></html>"""


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def band_html(text, locale, rtl, color):
    w, h = W, BAND_H
    body = f"""<div id="wrap"><div id="t"
      style="max-width:{w - 96}px;padding:0 20px;text-align:center;color:{color};
      font-size:64px;font-weight:600;line-height:1.3;">{html_escape(text)}</div></div>
    <script>
    var el=document.getElementById('t');var fs=64;
    while(fs>30&&el.scrollHeight>{h - 36}){{fs-=2;el.style.fontSize=fs+'px';}}
    </script>"""
    return HTML_HEAD.format(w=w, h=h, bg=f"rgb{BAND_BG}", font=FONT_CSS[locale],
                            dir="rtl" if rtl else "ltr", body=body)


def badge_html(p, bg="#FFFFFF"):
    """静态流式布局（本 Edge headless 构建的 position:absolute 子元素会破坏父盒高度）。
    药丸形名牌：身份色描边 + 悬浮投影（matte 双色抠像可精确还原半透明投影）。"""
    native = html_escape(p["name"]["native"])
    sub = html_escape(f"{p['name']['latin']} · {p['langLabel']}")
    rtl = "rtl" if p.get("rtl") else "ltr"
    body = f"""<div id="wrap"><div style="width:840px;height:200px;background:#FFFFFF;
      border:6px solid {p['identity']};border-radius:100px;text-align:center;padding:24px 0 0 0;
      box-shadow:0 16px 36px rgba(35,40,63,0.30);">
      <div style="font-size:84px;line-height:94px;font-weight:800;color:#23283D;direction:{rtl};">{native}</div>
      <div style="font-size:30px;line-height:40px;color:#6A6F82;margin-top:6px;letter-spacing:1px;font-weight:600;">{sub}</div>
    </div></div>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg,
                            font=f"{FONT_CSS[p['locale']]}, 'Microsoft YaHei', sans-serif",
                            dir="ltr", body=body)


def pill_html(p, bg="#FFFFFF"):
    """语言牌（plan §8.3）：国旗 emoji ＋ 语种文字双通道（plan §7.2-3），字体随语种走 FONT_CSS。
    本机 Windows 无国旗字形：emoji 回退为 ISO 双字母对（CN 汉语）——见 FLAG 表注与手册坑⑬。"""
    label = f"{FLAG[p['locale']]} {p['langLabel']}"
    body = f"""<div id="wrap"><div style="width:340px;height:88px;background:#FFFFFF;
      border:5px solid {UI_INK};border-radius:44px;text-align:center;line-height:80px;
      font-size:40px;font-weight:700;color:#23283D;box-shadow:0 8px 20px rgba(35,40,63,0.22);">{html_escape(label)}</div></div>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg,
                            font=f"{FONT_CSS[p['locale']]}, 'Segoe UI Emoji', 'Microsoft YaHei', sans-serif",
                            dir="ltr", body=body)


def bubble_html(text, tail_right, font="'Microsoft YaHei', 'Segoe UI Emoji', sans-serif", bg="#FFFFFF"):
    """尾巴不用 CSS 画（transform 会破坏布局），由渲染端 PIL 补画（2x 层）。
    A 型气泡内嵌各语 native 名：字体栈由调用方传 locale 字体（勿只靠 Edge 回退）"""
    body = f"""<div id="wrap"><div style="width:460px;background:#FFFFFF;
      border:5px solid {UI_INK};border-radius:46px;padding:20px 32px;text-align:center;
      box-shadow:0 12px 28px rgba(35,40,63,0.25);">
      <span style="font-size:40px;line-height:1.3;font-weight:700;color:#23283D;">{html_escape(text)}</span>
    </div></div>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg, font=font, dir="ltr", body=body)


def matte_combine(png_w, png_b, out):
    """双 matte 抠像：白底/黑底两次截图 → 精确 alpha（C_w - C_b = (1-a)·255）。
    保留整幅 1080x300（内容在画布中心），渲染端按 alpha bbox 裁紧后以中心点粘贴。"""
    import numpy as np
    from PIL import Image
    w = np.asarray(Image.open(png_w).convert("RGB"), dtype=float)
    b = np.asarray(Image.open(png_b).convert("RGB"), dtype=float)
    alpha = np.clip(255.0 - (w - b).max(axis=2), 0, 255)
    a = np.maximum(alpha / 255.0, 1e-4)[..., None]
    rgb = np.clip(b / a, 0, 255)
    Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA").save(out)


def cmd_assets(only):
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    personas, doc = load_data()
    jobs = []  # (name, kind, [(suffix, html), ...]；单 shot=不透明直出，双 shot=matte 抠像)

    def lighten(hexcolor, f):
        c = tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02X%02X%02X" % tuple(int(v + (255 - v) * f) for v in c)

    def matte_pair(name, kind, html_fn, *args):
        return (name, kind, [("_w", html_fn(*args, bg="#FFFFFF")), ("_b", html_fn(*args, bg="#000000"))])

    for unit in card_units(doc):
        card, variant = unit["card"], unit.get("variant")
        pid, base_pid = unit["id"], unit["persona"]
        if only and base_pid not in only:
            continue
        p = personas[base_pid]
        rtl = bool(p.get("rtl"))
        card_lines = variant["lines"] if variant else card["lines"]
        for i, ln in enumerate(card_lines):
            jobs.append((f"band_{pid}_{i}_base", "band",
                         [("_s", band_html(ln["text"], p["locale"], rtl, "#FFFFFF"))]))
            jobs.append((f"band_{pid}_{i}_hl", "band",
                         [("_s", band_html(ln["text"], p["locale"], rtl, lighten(p["identity"], 0.45)))]))
        if not variant:
            jobs.append(matte_pair(f"badge_{pid}", "badge", badge_html, p))
            if doc["cast"][pid] == "A":
                jobs.append(matte_pair(f"bubble_a_{pid}", "bubble", bubble_html,
                                       f"跟我读：{p['name']['native']}", not rtl,
                                       f"{FONT_CSS[p['locale']]}, 'Microsoft YaHei', 'Segoe UI Emoji', sans-serif"))
    for locale in sorted({p["locale"] for p in personas.values()}):  # 语言牌按语种共享（14 语）
        q = next(p for p in personas.values() if p["locale"] == locale)
        jobs.append(matte_pair(f"pill_{locale}", "pill", pill_html, q))
    jobs.append(matte_pair("bubble_b_r", "bubble", bubble_html, "问路找我 🗺", True))
    jobs.append(matte_pair("bubble_b_l", "bubble", bubble_html, "问路找我 🗺", False))

    # Edge headless 视口补偿：部分 Edge 版本 --window-size 含浏览器 UI 高度，
    # 截图视口 = window-size − chrome_px（本机实测 300→206）。先探一次差值，
    # 之后所有截图用补偿后的窗口高度，保证 300px 画布完整入镜（坑⑩）。
    probe_html = TEXT_DIR / "_vp_probe.html"
    probe_html.write_text(HTML_HEAD.format(w=100, h=BAND_H, bg="#FFFFFF",
                                           font="sans-serif", dir="ltr",
                                           body="<div style='height:100vh'></div>"
                                                "<script>document.title=window.innerHeight;</script>"),
                          "utf-8")

    def edge_viewport_h():
        dom = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--window-size=1080,300",
                              "--virtual-time-budget=800", "--dump-dom", probe_html.as_uri()],
                             check=True, capture_output=True, timeout=60).stdout.decode("utf-8", "ignore")
        # 用 innerHeight 差值反推：无法直接读 title，改用固定探测页面高度差
        import re
        m = re.search(r"<title>(\d+)</title>", dom)
        return int(m.group(1)) if m else BAND_H

    chrome_px = 300 - edge_viewport_h()
    edge_win_h = BAND_H + max(0, chrome_px)
    print(f"[assets] Edge viewport deficit: {chrome_px}px -> window-size=1080,{edge_win_h}")

    def run(job):
        name, kind, shots = job
        pngs = []
        for suffix, html in shots:
            tmp = TEXT_DIR / f"{name}{suffix}.html"
            tmp.write_text(html, "utf-8")
            png = TEXT_DIR / f"{name}{suffix}.png"
            cmd = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                   "--force-device-scale-factor=1", f"--window-size=1080,{edge_win_h}",
                   f"--screenshot={png}", "--virtual-time-budget=1500", tmp.as_uri()]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if not png.exists():
                raise RuntimeError(f"edge shot failed: {name}{suffix}")
            pngs.append(png)
        out = TEXT_DIR / f"{name}.png"
        if len(pngs) == 1:
            os.replace(pngs[0], out)
        else:
            matte_combine(pngs[0], pngs[1], out)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(run, jobs))
    print(f"[assets] done: {len(jobs)} assets -> {TEXT_DIR}")


# ---------- 渲染阶段（捆绑 Python + Pillow + ffmpeg） ----------

def mix(c1, c2, f):
    return tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))


def hexc(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_cubic(u):
    return 1 - (1 - u) ** 3


def pop_scale(t, t0, dur, overshoot=True, damp=None):
    """damp=movement.bounce：越小越弹（入场弹跳按个性参数缩放，plan §4）"""
    if t <= t0:
        return 0.0
    u = (t - t0) / dur
    if u >= 1:
        return 1.0
    if overshoot:
        k = clamp(14.0 / damp, 0.75, 1.6) if damp else 1.0
        return 1 - math.exp(-6.0 * k * u) * math.cos(9.0 * k * u)
    return 1 - math.exp(-5.0 * u) * (1 + 5.0 * u)


# ---- 场景原语 ----

class DrawScaled:
    """坐标等比缩放的 ImageDraw 代理：1x 语义坐标 → kx 画布，
    配合 LANCZOS 缩回实现全形状抗锯齿（超采样）。"""

    def __init__(self, base, k):
        self._b, self._k = base, k

    def _box(self, bbox):
        return [v * self._k for v in bbox]

    def ellipse(self, bbox, **kw):
        self._b.ellipse(self._box(bbox), **kw)

    def rectangle(self, bbox, **kw):
        self._b.rectangle(self._box(bbox), **kw)

    def rounded_rectangle(self, bbox, rad, **kw):
        self._b.rounded_rectangle(self._box(bbox), max(2, rad * self._k), **kw)

    def line(self, pts, width=1, **kw):
        if pts and isinstance(pts[0], (int, float)):  # PIL 也接受扁平坐标序列
            pts = list(zip(pts[::2], pts[1::2]))
        self._b.line([(x * self._k, y * self._k) for x, y in pts],
                     width=max(1, int(width * self._k)), **kw)

    def arc(self, bbox, a0, a1, width=1, **kw):
        self._b.arc(self._box(bbox), a0, a1, width=max(1, int(width * self._k)), **kw)

    def pieslice(self, bbox, a0, a1, **kw):
        self._b.pieslice(self._box(bbox), a0, a1, **kw)

    def chord(self, bbox, a0, a1, **kw):
        self._b.chord(self._box(bbox), a0, a1, **kw)

    def polygon(self, pts, **kw):
        self._b.polygon([(x * self._k, y * self._k) for x, y in pts], **kw)


SS = 2  # 全局超采样倍率（人物层/场景层）


def prerender_bg(p, card):
    import numpy as np
    from PIL import Image, ImageDraw
    ident = hexc(p["identity"])
    top = mix((246, 243, 238), ident, 0.10)
    bottom = mix((236, 232, 224), ident, 0.20)
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):
        arr[y, :, :] = mix(top, bottom, y / (H - 1))
    img = Image.fromarray(arr).resize((W * SS, H * SS), Image.BILINEAR)
    d = DrawScaled(ImageDraw.Draw(img), SS)
    ground = mix((230, 226, 216), ident, 0.18)
    d.rectangle([0, 1700, W, H], fill=ground)
    d.ellipse([310, 1682, 770, 1758], fill=mix(ground, (50, 45, 40), 0.14))  # 站位阴影
    pal = {
        "ink": (188, 182, 170),
        "soft": mix((214, 208, 196), ident, 0.22),
        "soft2": mix((196, 189, 176), ident, 0.34),
        "tint": mix((255, 255, 255), ident, 0.30),
        "tint2": mix((255, 255, 255), ident, 0.16),
        "accent": ident,
        "paper": (245, 241, 232),
    }
    for name in card.get("scene", []):
        fn = SCENES.get(name)
        if fn:
            fn(d, pal)
    return img.resize((W, H), Image.LANCZOS)


def _sun(d, pal, x=810, y=520, r=95, color=None):
    d.ellipse([x - r, y - r, x + r, y + r], fill=color or pal["tint"])


SCENES = {}


def scene(name):
    def deco(fn):
        SCENES[name] = fn
        return fn
    return deco


@scene("sun")
def s_sun(d, pal):
    _sun(d, pal, x=780, y=480, color=pal["tint"])
    for i, r in enumerate((46, 66, 86)):
        d.arc([780 - r - 40, 480 - r - 40, 780 + r + 40, 480 + r + 40], 200, 340,
              fill=mix(pal["tint"], SCENE["white"], 0.4 - i * 0.15), width=6)


@scene("sun_low")
def s_sunlow(d, pal):
    _sun(d, pal, x=820, y=1020, r=120, color=mix(SCENE["sun1"], pal["accent"], 0.25))


@scene("sky_dusk")
def s_dusk(d, pal):
    for i in range(5):
        d.ellipse([120 + i * 190, 380 + (i % 2) * 40, 168 + i * 190, 428 + (i % 2) * 40],
                  fill=mix(SCENE["sun2"], pal["accent"], 0.18))


@scene("sky_sunset")
def s_sunset(d, pal):
    d.ellipse([700, 940, 1060, 1300], fill=mix(SCENE["sun3"], pal["accent"], 0.22))
    d.line([0, 1010, 1080, 1010], fill=mix(SCENE["white"], pal["accent"], 0.30), width=8)


@scene("mountains")
def s_mountains(d, pal):
    d.polygon([(0, 1500), (260, 1060), (520, 1500)], fill=pal["soft2"])
    d.polygon([(300, 1500), (620, 980), (940, 1500)], fill=pal["soft"])
    d.polygon([(556, 1078), (620, 980), (684, 1078)], fill=SCENE["snow"])


@scene("gate_arch")
@scene("arch")
def s_arch(d, pal):
    d.rounded_rectangle([140, 700, 220, 1500], 30, fill=pal["soft2"])
    d.rounded_rectangle([860, 700, 940, 1500], 30, fill=pal["soft2"])
    d.arc([140, 560, 940, 1120], 180, 360, fill=pal["soft2"], width=70)


@scene("flowers")
def s_flowers(d, pal):
    for x, y, c in [(180, 1560, pal["accent"]), (250, 1620, SCENE["lantern"]), (900, 1580, pal["accent"]),
                    (840, 1640, SCENE["white"])]:
        d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=c)
        d.line([x, y + 16, x, y + 52], fill=SCENE["stem"], width=6)


@scene("lamp")
def s_lamp(d, pal):
    d.line([200, 980, 200, 1500], fill=pal["soft2"], width=14)
    d.ellipse([160, 920, 240, 1000], fill=mix(SCENE["glow"], pal["accent"], 0.3))


@scene("bus_sign")
def s_bus(d, pal):
    d.rounded_rectangle([830, 1180, 920, 1500], 16, fill=pal["soft2"])
    d.rounded_rectangle([780, 1060, 970, 1200], 16, fill=pal["accent"], outline=pal["ink"], width=6)
    d.rectangle([800, 1090, 950, 1114], fill=SCENE["white"])
    d.rectangle([800, 1130, 920, 1154], fill=SCENE["white"])


@scene("bench")
def s_bench(d, pal):
    d.rounded_rectangle([740, 1460, 1000, 1500], 14, fill=pal["soft2"])
    d.rounded_rectangle([740, 1360, 1000, 1396], 14, fill=pal["soft2"])
    d.rectangle([770, 1400, 786, 1560], fill=pal["soft2"])
    d.rectangle([954, 1400, 970, 1560], fill=pal["soft2"])


@scene("awning")
def s_awning(d, pal):
    d.rounded_rectangle([60, 700, 560, 1240], 30, fill=pal["tint2"], outline=pal["ink"], width=6)
    for i in range(6):
        c = pal["accent"] if i % 2 == 0 else SCENE["white"]
        d.polygon([(60 + i * 84, 700), (60 + (i + 1) * 84, 700), (60 + (i + 1) * 84 - 6, 780), (60 + i * 84 - 6, 780)], fill=c)


@scene("counter")
def s_counter(d, pal):
    d.rounded_rectangle([120, 1300, 480, 1560], 20, fill=pal["soft2"])
    d.rectangle([120, 1300, 480, 1330], fill=pal["soft"])


@scene("steam")
def s_steam(d, pal):
    for x, y0 in [(240, 1120), (330, 1080)]:
        d.arc([x - 30, y0, x + 30, y0 + 90], 180, 360, fill=SCENE["white"], width=10)
        d.arc([x - 30, y0 - 70, x + 30, y0 + 20], 0, 180, fill=SCENE["white"], width=10)


@scene("windows_big")
def s_windows(d, pal):
    d.rectangle([80, 640, 520, 1220], fill=pal["tint2"], outline=pal["ink"], width=6)
    d.line([300, 640, 300, 1220], fill=SCENE["lamp"], width=6)
    d.line([80, 930, 520, 930], fill=SCENE["lamp"], width=6)


@scene("board_timetable")
def s_board(d, pal):
    d.rounded_rectangle([640, 620, 1040, 1000], 24, fill=SCENE["night_blue"], outline=pal["ink"], width=6)
    for r in range(4):
        d.rectangle([670, 660 + r * 80, 940, 700 + r * 80], fill=mix(SCENE["night_blue"], pal["accent"], 0.5))


@scene("luggage")
def s_luggage(d, pal):
    d.rounded_rectangle([880, 1380, 1040, 1580], 24, fill=pal["accent"], outline=pal["ink"], width=6)
    d.rounded_rectangle([840, 1420, 900, 1580], 18, fill=pal["soft2"], outline=pal["ink"], width=6)


@scene("cobble_arcs")
def s_cobble(d, pal):
    for r in (190, 320, 450):
        d.arc([540 - r, 1700 - r // 2, 540 + r, 1700 + r // 2], 180, 360, fill=pal["soft"], width=10)


@scene("fountain")
def s_fountain(d, pal):
    d.ellipse([120, 1360, 460, 1500], fill=mix(SCENE["sky"], pal["accent"], 0.25))
    d.ellipse([200, 1390, 380, 1470], fill=SCENE["white"])


@scene("pigeons")
def s_pigeons(d, pal):
    for x, y in [(200, 1620), (280, 1660), (860, 1600)]:
        d.ellipse([x - 18, y - 12, x + 18, y + 12], fill=pal["soft2"])
        d.ellipse([x + 10, y - 22, x + 30, y - 4], fill=pal["soft2"])


@scene("pigeons_on_wire")
def s_powire(d, pal):
    d.line([0, 700, 1080, 760], fill=SCENE["lamp"], width=5)
    for x in (260, 460, 700):
        y = 700 + (760 - 700) * x / 1080
        d.ellipse([x - 14, y - 26, x + 14, y + 2], fill=pal["soft2"])


@scene("shopfront")
def s_shopfront(d, pal):
    d.rounded_rectangle([620, 760, 1020, 1500], 26, fill=pal["tint2"], outline=pal["ink"], width=6)
    d.rectangle([660, 900, 980, 1200], fill=mix(SCENE["glow2"], pal["accent"], 0.25))


@scene("books_stack")
def s_books(d, pal):
    for i, c in enumerate([pal["accent"], pal["soft2"], pal["soft"]]):
        d.rounded_rectangle([140, 1520 - i * 34, 360, 1550 - i * 34], 8, fill=c)


@scene("desk_lamp")
def s_desklamp(d, pal):
    d.rounded_rectangle([700, 1240, 1010, 1290], 16, fill=pal["soft2"])
    d.line([960, 1250, 900, 1060], fill=pal["soft2"], width=16)
    d.polygon([(830, 1060), (970, 1060), (940, 990), (860, 990)], fill=pal["accent"])


@scene("window")
def s_window(d, pal):
    d.rounded_rectangle([700, 620, 1000, 1060], 40, fill=mix(SCENE["sky2"], pal["accent"], 0.15),
                        outline=pal["ink"], width=6)
    d.line([850, 620, 850, 1060], fill=SCENE["lamp"], width=5)
    d.line([700, 840, 1000, 840], fill=SCENE["lamp"], width=5)


@scene("shelf")
def s_shelf(d, pal):
    for r in range(3):
        y = 980 + r * 160
        d.rectangle([80, y, 460, y + 16], fill=pal["soft2"])
        for b in range(4):
            c = [pal["accent"], pal["soft"], pal["soft2"]][(r + b) % 3]
            d.rounded_rectangle([100 + b * 90, y - 90, 168 + b * 90, y], 6, fill=c)


@scene("signpost")
def s_signpost(d, pal):
    d.line([840, 950, 840, 1520], fill=pal["soft2"], width=16)
    d.rounded_rectangle([760, 980, 1000, 1060], 12, fill=pal["accent"])
    d.polygon([(860, 1080), (1000, 1120), (860, 1160)], fill=pal["accent"])


@scene("trail")
def s_trail(d, pal):
    d.polygon([(0, 1920), (380, 1400), (760, 1920)], fill=pal["soft"])
    d.polygon([(540, 1920), (900, 1480), (1080, 1700), (1080, 1920)], fill=pal["soft2"])


@scene("awning_market")
def s_mawning(d, pal):
    for i in range(5):
        c = pal["accent"] if i % 2 == 0 else SCENE["white"]
        d.polygon([(620 + i * 90, 820), (620 + (i + 1) * 90, 820), (614 + (i + 1) * 90, 900), (614 + i * 90, 900)], fill=c)
    d.rectangle([620, 820, 1070, 838], fill=SCENE["lamp"])


@scene("crates")
def s_crates(d, pal):
    d.rounded_rectangle([130, 1360, 330, 1540], 14, fill=pal["soft2"], outline=pal["ink"], width=6)
    d.rounded_rectangle([200, 1210, 400, 1360], 14, fill=pal["soft"], outline=pal["ink"], width=6)


@scene("fruit_balls")
def s_fruit(d, pal):
    for x, y, c in [(180, 1300, SCENE["flower"]), (240, 1330, SCENE["blossom"]), (300, 1300, pal["accent"])]:
        d.ellipse([x - 34, y - 34, x + 34, y + 34], fill=c)


@scene("umbrella")
def s_umbrella(d, pal):
    d.chord([700, 760, 1080, 1100], 180, 360, fill=pal["accent"])
    d.line([890, 930, 890, 1400], fill=SCENE["lamp"], width=12)


@scene("table")
def s_table(d, pal):
    d.rounded_rectangle([700, 1420, 1000, 1470], 12, fill=pal["soft2"])
    d.rectangle([730, 1470, 750, 1620], fill=pal["soft2"])
    d.rectangle([950, 1470, 970, 1620], fill=pal["soft2"])
    d.ellipse([770, 1360, 830, 1420], fill=SCENE["white"])


@scene("plant")
def s_plant(d, pal):
    d.polygon([(180, 1600), (260, 1380), (340, 1600)], fill=mix(SCENE["grass2"], pal["accent"], 0.3))
    d.rounded_rectangle([200, 1600, 320, 1690], 14, fill=pal["soft2"])


@scene("arch_windows")
def s_archwin(d, pal):
    d.rounded_rectangle([90, 760, 250, 1200], 60, fill=pal["tint2"], outline=pal["ink"], width=6)
    d.rounded_rectangle([90, 1260, 250, 1560], 60, fill=pal["soft2"], outline=pal["ink"], width=6)


@scene("fence_low")
def s_fence(d, pal):
    for x in range(700, 1040, 80):
        d.rectangle([x, 1480, x + 22, 1620], fill=pal["soft2"])
    d.rectangle([700, 1520, 1020, 1544], fill=pal["soft2"])


@scene("tree")
def s_tree(d, pal):
    d.rectangle([880, 1250, 916, 1600], fill=SCENE["wood"])
    d.ellipse([770, 1000, 1030, 1300], fill=mix(SCENE["grass"], pal["accent"], 0.25))


@scene("domes")
def s_domes(d, pal):
    d.chord([120, 900, 400, 1240], 180, 360, fill=pal["accent"])
    d.chord([330, 960, 560, 1220], 180, 360, fill=pal["soft2"])
    d.rectangle([240, 1070, 280, 1100], fill=SCENE["white"])


@scene("water")
def s_water(d, pal):
    d.rectangle([0, 1480, 560, 1700], fill=mix(SCENE["sky3"], pal["accent"], 0.30))
    for y in (1540, 1620):
        d.arc([100, y, 300, y + 60], 180, 360, fill=SCENE["white"], width=8)


@scene("bunting")
def s_bunting(d, pal):
    d.line([0, 640, 1080, 700], fill=SCENE["lamp"], width=4)
    for i in range(9):
        x = 40 + i * 120
        y = 640 + (700 - 640) * x / 1080
        c = [pal["accent"], SCENE["lantern"], SCENE["white"]][i % 3]
        d.polygon([(x, y), (x + 56, y + 4), (x + 28, y + 64)], fill=c)


@scene("masts")
def s_masts(d, pal):
    for x in (180, 360):
        d.line([x, 940, x, 1480], fill=SCENE["lamp"], width=8)
        d.polygon([(x, 960), (x, 1200), (x - 90, 1120)], fill=SCENE["white"])


@scene("tree_shadow")
def s_tshadow(d, pal):
    d.ellipse([140, 800, 520, 1160], fill=mix(SCENE["grass"], pal["accent"], 0.20))
    d.arc([120, 1120, 540, 1420], 180, 360, fill=pal["soft"], width=12)


@scene("lantern")
@scene("lanterns")
def s_lantern(d, pal):
    d.rounded_rectangle([140, 700, 210, 830], 20, fill=pal["accent"])
    d.rectangle([150, 830, 200, 850], fill=SCENE["lamp"])
    d.rounded_rectangle([860, 730, 930, 860], 20, fill=mix(SCENE["peach2"], pal["accent"], 0.4))


@scene("pot_brass")
def s_pot(d, pal):
    d.chord([720, 1180, 1000, 1480], 180, 360, fill=mix(SCENE["wood2"], pal["accent"], 0.3))
    d.rectangle([840, 1140, 880, 1190], fill=SCENE["wood2"])


@scene("carpet")
def s_carpet(d, pal):
    d.rounded_rectangle([100, 1500, 420, 1620], 16, fill=mix(SCENE["sign"], pal["accent"], 0.4))
    d.rectangle([130, 1530, 390, 1590], fill=SCENE["white"])


@scene("brick_arches")
def s_bricks(d, pal):
    for i, x in enumerate((100, 330)):
        d.rounded_rectangle([x, 820, x + 200, 1420], 70, fill=pal["soft2"])
        d.rounded_rectangle([x + 40, 980, x + 160, 1420], 50, fill=pal["tint2"])


@scene("board_notice")
@scene("board")
def s_boardn(d, pal):
    d.rounded_rectangle([740, 1000, 1020, 1300], 18, fill=pal["paper"], outline=pal["ink"], width=6)
    for r in range(4):
        d.rectangle([770, 1050 + r * 60, 990, 1070 + r * 60], fill=pal["soft"])


@scene("palm")
def s_palm(d, pal):
    d.rectangle([170, 1150, 200, 1500], fill=SCENE["wood"])
    for dx, dy in [(-120, -60), (120, -60), (-80, -130), (80, -130), (0, -160)]:
        d.ellipse([185 + dx - 70, 1150 + dy - 26, 185 + dx + 70, 1150 + dy + 26],
                  fill=mix(SCENE["grass"], pal["accent"], 0.25))


@scene("mapwall")
def s_mapwall(d, pal):
    d.rectangle([700, 700, 1020, 1150], fill=pal["paper"], outline=pal["ink"], width=6)
    d.line([720, 780, 1000, 900], fill=pal["accent"], width=8)
    d.line([860, 760, 780, 1120], fill=pal["soft2"], width=8)
    d.ellipse([840, 880, 880, 920], fill=pal["accent"])


@scene("columns")
def s_columns(d, pal):
    for x in (110, 250):
        d.rectangle([x, 780, x + 60, 1420], fill=pal["tint2"], outline=pal["ink"], width=5)
        d.rectangle([x - 16, 740, x + 76, 790], fill=pal["soft2"])


@scene("lantern_row")
def s_lrow(d, pal):
    for i, x in enumerate((120, 320, 900)):
        d.line([x, 620, x, 700], fill=SCENE["lamp"], width=6)
        d.ellipse([x - 34, 700, x + 34, 810], fill=mix(SCENE["peach"], pal["accent"], 0.35 - i * 0.08))


@scene("wires")
def s_wires(d, pal):
    d.line([0, 620, 1080, 680], fill=SCENE["lamp"], width=5)
    d.line([0, 700, 1080, 650], fill=SCENE["lamp"], width=4)


@scene("hoop")
def s_hoop(d, pal):
    d.rectangle([820, 900, 852, 1500], outline=pal["ink"], width=8)
    d.ellipse([740, 800, 940, 1000], outline=pal["ink"], width=14)
    d.line([740, 950, 940, 950], fill=SCENE["white"], width=10)


@scene("fence")
def s_fenceH(d, pal):
    for x in range(80, 480, 90):
        d.rectangle([x, 1180, x + 26, 1500], fill=SCENE["metal"])
    for y in (1240, 1380):
        d.rectangle([80, y, 460, y + 20], fill=SCENE["metal"])


@scene("skyline")
def s_skyline(d, pal):
    for x, w, h in [(60, 120, 300), (220, 90, 420), (740, 140, 360), (920, 100, 260)]:
        d.rectangle([x, 1500 - h, x + w, 1500], fill=pal["soft2"])
        d.rectangle([x + 20, 1500 - h + 30, x + 40, 1500 - h + 60], fill=SCENE["chalk"])


@scene("clothesline")
def s_cline(d, pal):
    d.line([60, 860, 520, 900], fill=SCENE["lamp"], width=5)
    for i, c in enumerate([SCENE["white"], pal["accent"], SCENE["lantern"]]):
        x = 120 + i * 130
        y = 860 + (900 - 860) * x / 520
        d.rounded_rectangle([x, y, x + 70, y + 90], 12, fill=c)


@scene("stairs")
def s_stairs(d, pal):
    for i in range(4):
        d.rectangle([680 + i * 60, 1660 - i * 90, 1080, 1680 - i * 90], fill=mix(pal["soft"], SCENE["white"], i * 0.12))


@scene("shrubs")
def s_shrubs(d, pal):
    for x, y in [(180, 1560), (300, 1600)]:
        d.ellipse([x - 60, y - 50, x + 60, y + 50], fill=mix(SCENE["grass"], pal["accent"], 0.2))


@scene("neon_sign")
def s_neon(d, pal):
    d.rounded_rectangle([720, 760, 1020, 940], 26, outline=mix(SCENE["cyan"], pal["accent"], 0.4), width=10)
    d.rectangle([780, 800, 960, 830], fill=mix(SCENE["cyan"], pal["accent"], 0.4))
    d.rectangle([780, 860, 900, 890], fill=mix(SCENE["pink"], pal["accent"], 0.4))


@scene("window_grid")
def s_wgrid(d, pal):
    for r in range(3):
        for c in range(2):
            x, y = 110 + c * 150, 820 + r * 180
            d.rounded_rectangle([x, y, x + 110, y + 130], 18, fill=SCENE["steam"], outline=pal["ink"], width=5)


@scene("stall")
def s_stall(d, pal):
    d.rounded_rectangle([640, 1280, 1020, 1500], 20, fill=pal["soft2"], outline=pal["ink"], width=6)
    d.rectangle([640, 1280, 1020, 1310], fill=pal["soft"])


@scene("steamers")
def s_steamers(d, pal):
    for i, x in enumerate((160, 260)):
        d.ellipse([x, 1280, x + 90, 1350], fill=pal["soft2"], outline=pal["ink"], width=5)
        for k in range(3):
            d.arc([x + 10 + k * 26, 1240, x + 36 + k * 26, 1290], 180, 360, fill=SCENE["white"], width=6)


# ---- 人物 ----

MOOD_FACE = {
    "neutral": dict(lift=0, tilt=0, smile=0.6),
    "happy": dict(lift=7, tilt=0, smile=1.0),
    "puzzled": dict(lift=2, tilt=11, smile=0.15),
    "encouraging": dict(lift=4, tilt=0, smile=0.8),
    "emphatic": dict(lift=2, tilt=-6, smile=0.5),
    "teach": dict(lift=2, tilt=0, smile=0.55),
}
EYE_MOOD = {"neutral": 1.0, "happy": 0.94, "puzzled": 1.05, "encouraging": 0.98, "emphatic": 0.97, "teach": 1.0}
# 眼形缩放（巩膜 ry 系数）：happy 微闭笑眼 / puzzled 睁大（plan §4 眼神变化）


# 脸型规格表（plan §8.3；2026-10-03 人物形象打磨：2 型 → 6 型，按人设分配）。
# 元组 = (头高 H, 头宽系数 WH/H)。heart＝上圆下圆收下巴（draw_character 组合绘制，
# 贝塞尔弧收底、无尖角——尖下巴观感像鬼，禁用）、square＝方颌（椭圆底缘两侧补平）
# ——下颌轮廓只由这两个键驱动，其余型为纯椭圆。
FACE_SPECS = {
    "round":  (356.0, 0.955),   # 婴儿圆：宽圆头
    "tall":   (396.0, 0.78),    # 窄长：清瘦长头
    "oval":   (386.0, 0.84),    # 端正椭圆：利落匀称
    "wide":   (348.0, 1.02),    # 宽和：扁宽大头
    "heart":  (372.0, 0.90),    # 心形尖下巴
    "square": (392.0, 0.88),    # 方颌硬朗
}


def face_geo(face):
    """头身规格（单一事实源，渲染与 qa 探针共用）。单位 = 头高 H。
    对标多邻国人形：头占全身 ~46%；躯干含肩与头等宽（剪影连续，无缝衔接）；
    低位大眼（头顶下 0.615H）、宽瞳距 ±0.30×头宽、大巩膜 0.28×头宽；
    眉贴眼上（巩膜顶 + 0.035H）；嘴位头顶下 0.815H；粗短胶囊四肢贴躯干。"""
    H_h, wfac = FACE_SPECS.get(face, FACE_SPECS["round"])
    WH = H_h * wfac
    u = lambda f: f * H_h
    hy = 1140.0
    eye_y = hy - H_h / 2 + u(0.615)
    return dict(
        H=H_h, WH=WH, rx=WH / 2, ry=H_h / 2, hy=hy, cx=540.0, ground=1700.0,
        eye_dx=0.300 * WH, scl_rx=0.140 * WH, scl_ry=0.170 * WH, pup_r=0.078 * WH,
        eye_y=eye_y, brow_y=eye_y - 0.170 * WH - u(0.035),
        mouth_y=hy - H_h / 2 + u(0.815), blush_y=hy - H_h / 2 + u(0.700),
        chin=hy + H_h / 2,
        torso_top=hy + H_h / 2 + u(0.02), torso_h=u(0.52), torso_hw=0.435 * WH,
        sh_dy=u(0.07), sh_hw=0.435 * WH,
        leg_cx=u(0.145), leg_w=u(0.185), foot_splay=u(0.085),
        foot_cy=1700.0 + u(0.006), foot_l=u(0.335), foot_h=u(0.145),
        up_len=u(0.27), lo_len=u(0.24), arm_w=u(0.155), hand_r=u(0.105),
    )


def draw_character(img, d, p, t, ctx):
    """多邻国风格角色：无描边纯平涂、头身规格见 face_geo()、大眼白+瞳孔双高光、
    胶囊眉、粗短四肢、圆润有机发型（双色高光）、耳朵/衣领/袖口细节。"""
    pal = p["palette"]
    hair_c, hl_c = hexc(pal["hair"]), hexc(pal["hairHighlight"])
    skin = hexc(pal["skin"])
    top, bottom = hexc(pal["outfitTop"]), hexc(pal["outfitBottom"])
    ident = hexc(p["identity"])
    face = p["movement"]["face"]
    female = p["gender"] == "female"
    seed = p["id"]  # 一切随机走人设 id 命名空间（不变量⑦；qa 探针同源可复算）
    skin_sh = hexc(pal["skinShade"])
    sk = p.get("skin", {})  # 皮肤层叠加槽（plan §1/§3 原则五：做旧/补丁，不改基型配色）
    # ---- 头身规格（face_geo 单一事实源；cx/ground 永不手抄——不变量①）----
    G = face_geo(face)
    cx, ground = G["cx"], G["ground"]
    sc = ctx["scale"]
    q = ctx["squash"]
    sx, sy = sc * (1 + q * 0.6) * ctx.get("xscale", 1.0), sc * (1 - q)
    bx, by = ctx["xoff"], ctx["yoff"]
    hdx, hdy = ctx["head_dx"], ctx["head_dy"]
    pose = ctx["pose"]
    acc = {a["code"]: a for a in p.get("accessories", [])}
    has = lambda c: c in acc
    ss = ctx.get("ss", 1.0)
    out = p.get("outfit", {})  # 服装轮廓槽（plan §4：bottom=skirt 长裙装 / kind=tunic|pinafore|vest；缺省=长裤）
    skirt = out.get("bottom") == "skirt"
    tunic = out.get("kind") == "tunic"
    pinafore = out.get("kind") == "pinafore"
    vest = out.get("kind") == "vest"

    def pfy(code, kind):
        """挂件物理偏移：数据声明了对应 physics 才生效（plan §4 accessories.physics）"""
        return phys(seed, code, kind, t) if has(code) and acc[code].get("physics") == kind else (0.0, 0.0)

    u = lambda f: f * G["H"]
    rx, ry = G["rx"], G["ry"]
    hx, hy = cx + hdx, G["hy"] + hdy
    eye_y = G["eye_y"] + hdy
    brow_y0 = G["brow_y"] + hdy
    mouth_y = G["mouth_y"] + hdy
    blush_y = G["blush_y"] + hdy
    eye_dx, scl_rx, scl_ry, pup_r = G["eye_dx"], G["scl_rx"], G["scl_ry"], G["pup_r"]
    torso_top = G["torso_top"]
    torso_bot = torso_top + G["torso_h"] * (1.30 if tunic else 1.0)  # 长衫：下摆过臀（outfit.kind=tunic）
    torso_hw = G["torso_hw"]
    sh_y = torso_top + G["sh_dy"]
    sh_hw = G["sh_hw"]
    leg_cx, leg_w = G["leg_cx"], G["leg_w"]
    foot_cy, foot_l, foot_h = G["foot_cy"], G["foot_l"], G["foot_h"]
    up_len, lo_len, arm_w, hand_r = G["up_len"], G["lo_len"], G["arm_w"], G["hand_r"]
    style = p["hairStyle"]

    def T(pt):
        x, y = pt
        return ((cx + bx + sx * (x - cx)) * ss, (ground + by + sy * (y - ground)) * ss)

    def TB(x0, y0, x1, y1):
        a, b = T((x0, y0))
        c, dd = T((x1, y1))
        return [a, b, c, dd]

    def E(x0, y0, x1, y1, **kw):
        d.ellipse(TB(x0, y0, x1, y1), **kw)

    def RR(x0, y0, x1, y1, rad, **kw):
        d.rounded_rectangle(TB(x0, y0, x1, y1), max(2, rad * sc * ss), **kw)

    def LN(pts, width, **kw):
        d.line([T(pt) for pt in pts], width=max(1, int(width * sc * ss)), joint="curve", **kw)

    def CAP(p0, p1, width, **kw):  # 胶囊：粗线 + 两端圆头
        LN([p0, p1], width, **kw)
        r = width / 2
        E(p0[0] - r, p0[1] - r, p0[0] + r, p0[1] + r, **kw)
        E(p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r, **kw)

    def ARC(x0, y0, x1, y1, a0, a1, width, **kw):
        d.arc(TB(x0, y0, x1, y1), a0, a1, width=max(1, int(width * sc * ss)), **kw)

    def PIE(x0, y0, x1, y1, a0, a1, **kw):
        d.pieslice(TB(x0, y0, x1, y1), a0, a1, **kw)

    # ================= 背发层（头后体积） =================
    if style in ("ponytail_high", "curly_ponytail"):
        for fx, fy, r in ((0.78, -0.52, 40), (0.92, -0.10, 34), (0.98, 0.30, 27)):
            E(hx + rx * fx - r, hy + ry * fy - r, hx + rx * fx + r, hy + ry * fy + r, fill=hair_c)
        if style == "curly_ponytail":
            for fx, fy in ((1.02, 0.62), (0.84, 0.78)):
                E(hx + rx * fx - 22, hy + ry * fy - 22, hx + rx * fx + 22, hy + ry * fy + 22, fill=hair_c)
    if style == "ponytail_low":
        for fx, fy, r in ((-0.95, 0.12, 36), (-1.05, 0.54, 30), (-1.08, 0.94, 24)):
            E(hx + rx * fx - r, hy + ry * fy - r, hx + rx * fx + r, hy + ry * fy + r, fill=hair_c)
    if style in ("braid", "braid_long"):
        n = 4 if style == "braid" else 6
        br_ph = 2 * math.pi * rnd(f"{seed}:braid")
        for i in range(n):
            fy = -0.02 + i * (0.52 if style == "braid" else 0.40)
            fx = -1.00 + (0.10 if i % 2 else -0.10) - i * 0.02
            r = 30 - i * 3
            sw = 4.0 * math.sin(2 * math.pi * 0.7 * t + br_ph + i * 0.7) * i / n  # 辫子摆动（种子相位）
            E(hx + rx * fx + sw - r, hy + ry * fy - r, hx + rx * fx + sw + r, hy + ry * fy + r, fill=hair_c)
    if style in ("wavy_lob", "wavy_long", "long_straight", "long_bangs"):
        y_end = 0.85 if style == "wavy_lob" else 1.45
        RR(hx - rx - 46, hy - ry * 0.55, hx - rx + 30, hy + ry * y_end, 60, fill=hair_c)
        RR(hx + rx - 30, hy - ry * 0.55, hx + rx + 46, hy + ry * y_end, 60, fill=hair_c)
        if style in ("wavy_lob", "wavy_long"):
            for sgn in (-1, 1):
                for k in range(2):
                    yy = hy + ry * y_end - 24 + k * 34
                    E(hx + sgn * (rx + 38) - 26, yy, hx + sgn * (rx + 38) + 26, yy + 52, fill=hair_c)

    # ================= 腿与脚 =================
    legL_ang, legR_ang = pose.get("legL", 0), pose.get("legR", 0)
    leg_top = torso_bot - u(0.10)
    leg_bot = foot_cy - foot_h * 0.30
    worn_bottom = not skirt and "bottom" in sk.get("worn", [])  # 做旧：裤腿下半段轻微磨白（plan §1 皮肤层）
    leg_col = skin if skirt else bottom  # 裙装露腿：腿画肤色（裙身在躯干段画）
    for s, ang in ((-1, legL_ang), (1, legR_ang)):
        lx = cx + s * leg_cx
        RR(lx - leg_w / 2, leg_top, lx + leg_w / 2, leg_bot, leg_w / 2, fill=leg_col)
        if worn_bottom:
            wy = leg_top + (leg_bot - leg_top) * 0.42
            RR(lx - leg_w / 2, wy, lx + leg_w / 2, leg_bot, leg_w / 2, fill=mix(leg_col, (255, 255, 255), 0.10))
        RR(lx - leg_w / 2, leg_bot - u(0.05), lx + leg_w / 2, leg_bot, 10, fill=mix(leg_col, THEME["shade_dark"], 0.16))
        for pd in sk.get("patches", []):  # 膝盖补丁：位置从 face_geo 腿几何推导（不变量①）
            if pd.get("on") == "bottom" and pd.get("where") == ("knee_L" if s < 0 else "knee_R"):
                pc = hexc(pd["color"])
                ky = (leg_top + leg_bot) / 2
                RR(lx - leg_w * 0.62, ky - leg_w * 0.40, lx + leg_w * 0.62, ky + leg_w * 0.40, 10, fill=pc)
                for dyy in (-leg_w * 0.50, leg_w * 0.50):  # 补丁缝线
                    LN([(lx - leg_w * 0.52, ky + dyy), (lx + leg_w * 0.52, ky + dyy)], 3,
                       fill=mix(pc, THEME["shade_dark"], 0.35))
        fxp = lx + s * G["foot_splay"] + math.sin(math.radians(ang)) * 72
        RR(fxp - foot_l / 2, foot_cy - foot_h / 2, fxp + foot_l / 2, foot_cy + foot_h / 2,
           foot_h * 0.46, fill=THEME["shoe"])
        E(fxp + s * foot_l * 0.16 - u(0.05), foot_cy - foot_h * 0.36,
          fxp + s * foot_l * 0.16 + u(0.05), foot_cy - foot_h * 0.04,
          fill=mix(THEME["shoe"], (255, 255, 255), 0.30))  # 鞋头高光
        if has("shoe_accent"):
            E(fxp - foot_l * 0.24, foot_cy - foot_h * 0.06, fxp + foot_l * 0.24, foot_cy + foot_h * 0.24,
              fill=ident)
    if has("skateboard"):
        kick = pose.get("skate_kick", 0)
        yy = 1746 - kick * 60 + pfy("skateboard", "bounce")[1]
        E(540 - 128, yy - 16, 540 + 128, yy + 16, fill=THEME["skate_deck"])
        if acc["skateboard"].get("accent"):  # 标识色贴纸（分镜 卡05：玫瑰点缀——滑板贴纸）
            RR(540 - 92, yy - 10, 540 + 92, yy + 2, 8, fill=ident)
        for wx in (540 - 78, 540 + 78):
            E(wx - 14, yy + 12, wx + 14, yy + 30, fill=THEME["skate_wheel"])
    if has("basketball"):
        bax, bay = pfy("basketball", "bounce")
        E(540 + 196 + bax, 1618 + bay, 540 + 302 + bax, 1724 + bay, fill=THEME["ball"])
        ARC(540 + 196 + bax, 1618 + bay, 540 + 302 + bax, 1724 + bay, 100, 250, 4, fill=THEME["ball_line"])

    # ================= 躯干与背带/挂件 =================
    RR(cx - torso_hw, torso_top, cx + torso_hw, torso_bot, torso_hw * 0.62, fill=top)
    # 肩楔：从颈部两侧到肩峰的三角过渡（填平头-肩之间的露底缺口，剪影连续）
    for s in (-1, 1):
        d.polygon([T((cx + s * u(0.10), torso_top - u(0.02))),
                   T((cx + s * (torso_hw + u(0.02)), sh_y + u(0.06))),
                   T((cx + s * u(0.10), sh_y + u(0.10)))], fill=top)
    RR(cx + torso_hw - u(0.11), torso_top + u(0.06), cx + torso_hw - u(0.025), torso_bot - u(0.05),
       u(0.08), fill=mix(top, THEME["shade_dark"], 0.10))  # 右侧体积影
    ARC(cx - 0.20 * G["WH"], torso_top - u(0.055), cx + 0.20 * G["WH"], torso_top + u(0.075),
        180, 360, u(0.032), fill=mix(top, THEME["shade_dark"], 0.20))  # 领口
    # ---- 服装轮廓（outfit 槽；缺省=长裤，零改动兼容） ----
    if skirt:  # A 字裙：腰线起、大腿中段圆摆（outfit.bottom=skirt；腿已画肤色）
        waist = torso_top + G["torso_h"] - u(0.04)
        hem = torso_top + G["torso_h"] + u(0.26)
        flare = torso_hw * 1.55
        d.polygon([T((cx - torso_hw - u(0.02), waist)), T((cx - flare, hem)),
                   T((cx + flare, hem)), T((cx + torso_hw + u(0.02), waist))], fill=bottom)
        RR(cx - flare, hem - u(0.08), cx + flare, hem + u(0.02), u(0.08), fill=bottom)  # 圆摆
        RR(cx - torso_hw - u(0.02), waist - u(0.06), cx + torso_hw + u(0.02), waist + u(0.04),
           u(0.05), fill=mix(bottom, THEME["shade_dark"], 0.14))  # 腰带
    if pinafore:  # 背带裙：护胸＋双背带＋金色背带扣（outfit.kind=pinafore）
        bib_w = torso_hw * 0.56
        RR(cx - bib_w, torso_top + u(0.10), cx + bib_w, torso_top + G["torso_h"] * 0.62, 14, fill=bottom)
        CAP((cx - bib_w + u(0.01), torso_top + u(0.14)), (cx - u(0.115), torso_top - u(0.07)),
            u(0.055), fill=bottom)
        CAP((cx + bib_w - u(0.01), torso_top + u(0.14)), (cx + u(0.115), torso_top - u(0.07)),
            u(0.055), fill=bottom)
        for s2 in (-1, 1):
            E(cx + s2 * u(0.115) - u(0.016), torso_top + u(0.08), cx + s2 * u(0.115) + u(0.016),
              torso_top + u(0.112), fill=THEME["gold"])
    if vest:  # 马甲：两侧前襟片，中开白衬衫（outfit.kind=vest；面板收在内侧——外缘被垂臂遮挡）
        vp_in, vp_out = torso_hw * 0.16, torso_hw * 0.72
        RR(cx - vp_out, torso_top + u(0.03), cx - vp_in, torso_bot - u(0.06), u(0.05), fill=bottom)
        RR(cx + vp_in, torso_top + u(0.03), cx + vp_out, torso_bot - u(0.06), u(0.05), fill=bottom)
    if out.get("buttons"):  # 前襟扣排（outfit.buttons；衬衫通勤感。胸前置物如手账/墨镜会自然遮住下扣）
        bcol = mix(top, THEME["shade_dark"], 0.38)
        for fy2 in (0.22, 0.44, 0.66):
            E(cx - u(0.020), torso_top + G["torso_h"] * fy2 - u(0.020),
              cx + u(0.020), torso_top + G["torso_h"] * fy2 + u(0.020), fill=bcol)
    if has("apron"):
        RR(540 - 128, torso_top + 46, 540 + 128, torso_bot - 4, 44, fill=THEME["apron"])
        CAP((540 - 88, torso_top + 16), (540 - 62, torso_top + 52), 14, fill=THEME["apron"])
        CAP((540 + 88, torso_top + 16), (540 + 62, torso_top + 52), 14, fill=THEME["apron"])
    if has("cardigan_accent"):
        RR(cx - torso_hw - u(0.03), torso_top, cx - torso_hw + u(0.09), torso_bot, u(0.05), fill=mix(ident, top, 0.45))
        RR(cx + torso_hw - u(0.09), torso_top, cx + torso_hw + u(0.03), torso_bot, u(0.05), fill=mix(ident, top, 0.45))
    for code in ("backpack", "hikingpack", "canvas_backpack"):
        if has(code):
            dark = mix(top, (30, 30, 30), 0.30)
            web = mix(ident, top, 0.25) if acc[code].get("accent") else dark  # 标识色织带（挂件行）
            CAP((540 - 96, torso_top + 4), (540 - 56, torso_top + 40), 20, fill=web)
            CAP((540 + 96, torso_top + 4), (540 + 56, torso_top + 40), 20, fill=web)
            bx_p, by_p = pfy(code, "bounce")
            RR(540 + 150 + bx_p, torso_top + 130 + by_p, 540 + 220 + bx_p, torso_top + 214 + by_p, 20, fill=dark)
            if has("bottle"):
                bo_x, bo_y = pfy("bottle", "swing")
                RR(540 + 160 + bo_x, torso_top + 104 + bo_y, 540 + 192 + bo_x, torso_top + 152 + bo_y, 12,
                   fill=THEME["bottle_blue"])
    if has("satchel"):
        CAP((540 - 116, torso_top + 8), (540 + 98, torso_bot - 46), 16, fill=THEME["satchel"])
        RR(540 + 66, torso_bot - 84, 540 + 152, torso_bot + 2, 18, fill=THEME["satchel"])
    for code, (bc, bw) in {"tote": (THEME["bag_canvas"], 92), "woven_bag": (THEME["bag_woven"], 92),
                           "book_tote": (THEME["paper_tote"], 92), "minibag": (THEME["bag_canvas"], 66),
                           "pouch": (THEME["bag_pouch"], 58)}.items():
        if has(code):
            bxr = 540 + 152
            kind = acc[code].get("physics")  # 挎包物理：swing 摆 / bounce 颠（plan §7.3-4）
            sx_p, sy_p = phys(seed, code, kind, t) if kind else (0.0, 0.0)
            ARC(bxr - bw // 2 + 14 + sx_p, torso_top + 40 + sy_p * 0.4, bxr + bw // 2 - 14 + sx_p,
                torso_top + 128 + sy_p * 0.4, 180, 360, 8, fill=bc)
            RR(bxr - bw // 2 + sx_p * 1.3, torso_top + 76 + sy_p, bxr + bw // 2 + sx_p * 1.3,
               torso_top + 76 + bw + 22 + sy_p, 20, fill=bc)
            if acc[code].get("accent"):  # 书袋挂饰（分镜 卡17：藏红花橙点缀——书袋挂饰）
                E(bxr + sx_p * 1.3 - 10, torso_top + 76 + bw + 22 + sy_p, bxr + sx_p * 1.3 + 10,
                  torso_top + 76 + bw + 32 + sy_p, fill=ident)
    if has("scarf"):
        col = ident if acc["scarf"].get("accent") else THEME["scarf_red"]
        sc_x, sc_y = pfy("scarf", "swing")
        RR(540 - 104, torso_top - 30, 540 + 104, torso_top + 34, 30, fill=col)
        RR(540 + 18 + sc_x, torso_top + 18 + sc_y * 0.5, 540 + 66 + sc_x, torso_top + 128 + sc_y * 0.5, 18,
           fill=col)  # 围巾垂尾随风摆
    if has("necklace"):
        nx, ny = pfy("necklace", "swing")
        ARC(540 - 58 + nx * 0.3, torso_top - 10, 540 + 58 + nx * 0.3, torso_top + 96, 15, 165, 5, fill=THEME["gold"])
        E(532 + nx, torso_top + 64 + ny, 548 + nx, torso_top + 80 + ny, fill=THEME["gold"])  # 吊坠摆动
    if has("lanyard"):
        CAP((540 - 52, torso_top - 2), (540 - 12, torso_top + 74), 9, fill=ident)
        CAP((540 + 52, torso_top - 2), (540 + 12, torso_top + 74), 9, fill=ident)
        lx_p, ly_p = pfy("lanyard", "swing")
        RR(540 - 28 + lx_p, torso_top + 70 + ly_p, 540 + 28 + lx_p, torso_top + 130 + ly_p, 12, fill=(255, 255, 255))
        RR(540 - 28 + lx_p, torso_top + 70 + ly_p, 540 + 28 + lx_p, torso_top + 84 + ly_p, 6, fill=ident)
    if has("pin_badge"):
        E(540 - 104, torso_top + 60, 540 - 72, torso_top + 92, fill=ident)
    if has("pen"):
        CAP((540 + 92, torso_top + 62), (540 + 104, torso_top + 100), 9, fill=THEME["pen_blue"])
    if has("zipper"):  # 外套拉链：前襟拉链线＋拉链头（Миша/热心大哥；标识色拉链头）
        LN([(cx, torso_top + u(0.04)), (cx, torso_top + G["torso_h"] * 0.88)], u(0.016),
           fill=mix(top, THEME["shade_dark"], 0.22))
        zc = ident if acc["zipper"].get("accent") else THEME["metal_dark"]
        CAP((cx, torso_top + u(0.10)), (cx, torso_top + u(0.24)), u(0.026), fill=zc)
        E(cx - u(0.016), torso_top + u(0.24), cx + u(0.016), torso_top + u(0.272), fill=zc)  # 拉链头坠
    if has("clipboard"):  # 胸前笔记夹板：板＋纸＋标识色夹扣（अर्जुन/笔记狂人）
        cbx = cx + torso_hw * 0.42
        RR(cbx - u(0.085), torso_top + u(0.09), cbx + u(0.085), torso_top + u(0.40), 8, fill=THEME["bag_woven"])
        RR(cbx - u(0.062), torso_top + u(0.135), cbx + u(0.062), torso_top + u(0.365), 4, fill=THEME["paper"])
        cbc = ident if acc["clipboard"].get("accent") else THEME["metal_dark"]
        RR(cbx - u(0.050), torso_top + u(0.105), cbx + u(0.050), torso_top + u(0.135), 5, fill=cbc)
        LN([(cbx - u(0.040), torso_top + u(0.19)), (cbx + u(0.040), torso_top + u(0.19))], 3, fill=THEME["pen_blue"])
    if has("towel_shoulder"):  # 肩搭白毛巾＋标识色毛巾条（阿豪/茶档街坊）
        twx = cx - torso_hw
        CAP((twx - u(0.03), torso_top - u(0.10)), (twx + u(0.04), torso_top + u(0.30)), u(0.10), fill=(246, 246, 240))
        twc = ident if acc["towel_shoulder"].get("accent") else mix((246, 246, 240), THEME["shade_dark"], 0.25)
        RR(twx + u(0.005), torso_top + u(0.20), twx + u(0.075), torso_top + u(0.30), 5, fill=twc)
    if has("camera") or has("camera_neck"):
        s2 = ident if has("strap_accent") else THEME["camera_body"]
        ccode = "camera" if has("camera") else "camera_neck"
        cx_p, cy_p = pfy(ccode, "swing")
        CAP((540 - 74, torso_top - 4), (540 - 30 + cx_p * 0.4, torso_top + 66), 9, fill=s2)
        CAP((540 + 74, torso_top - 4), (540 + 30 + cx_p * 0.4, torso_top + 66), 9, fill=s2)
        RR(540 - 48 + cx_p, torso_top + 52 + cy_p, 540 + 48 + cx_p, torso_top + 132 + cy_p, 16, fill=THEME["camera_body"])
        E(540 - 18 + cx_p, torso_top + 76 + cy_p, 540 + 18 + cx_p, torso_top + 112 + cy_p, fill=THEME["lens_blue"])
    if has("sunglasses_neck"):
        gx_n, _ = pfy("sunglasses_neck", "swing")
        RR(540 - 44 + gx_n, torso_top + 58, 540 + 44 + gx_n, torso_top + 94, 14, fill=THEME["metal_dark"])
        CAP((540 - 40 + gx_n, torso_top + 68), (540 + 40 + gx_n, torso_top + 68), 6, fill=THEME["metal_dark"])
        E(540 - 34 + gx_n * 1.4, torso_top + 62, 540 - 12 + gx_n * 1.4, torso_top + 74,
          fill=THEME["glint_blue"])  # 镜片反光（qa_motion 探针）
    if has("map"):
        RR(540 - 178, torso_top + 118, 540 - 92, torso_top + 182, 10, fill=THEME["paper_map"])
        CAP((540 - 166, torso_top + 136), (540 - 104, torso_top + 162), 5, fill=ident)
    if has("planner"):
        RR(540 - 70, torso_top + 96, 540 + 20, torso_top + 168, 12, fill=THEME["paper"])
        CAP((540 - 70, torso_top + 120), (540 + 20, torso_top + 120), 4, fill=ident)
    if has("pocketbook"):
        RR(540 - 174, torso_top + 108, 540 - 82, torso_top + 178, 12, fill=THEME["book_leather"])
    if has("beads") and pose.get("hand_prop") != "beads":
        bx_b, by_b = pfy("beads", "swing")
        for k in range(5):
            ak = k * 1.15
            cxx = 540 + 162 + bx_b + math.cos(ak) * 16
            cyy = torso_top + 140 + by_b * 0.6 + math.sin(ak) * 16
            E(cxx - 6, cyy - 6, cxx + 6, cyy + 6, fill=THEME["beads"])
    if has("bottle_big") and pose.get("hand_prop") != "bottle":
        bx_g, by_g = pfy("bottle_big", "swing")
        RR(540 + 144 + bx_g, torso_top + 100 + by_g * 0.5, 540 + 182 + bx_g, torso_top + 180 + by_g * 0.5, 16,
           fill=THEME["bottle_green"])

    # ================= 手臂（胶囊袖 + 圆手 + 袖口） =================
    # 画在躯干之后、颈与头之前：袖子是「衣服层」，抬臂姿态（wave/thumbs_up/hand_shoot…）
    # 会把袖子胶囊扫过人脸——衣层在脸前会遮嘴（2026-10-03 用户反馈），故脸/嘴永远画在手臂之上；
    # 各姿态的手都落在脸轮廓之外（肩点外展），移到脸后不丢姿态可读性。face_cam 是举到脸前的
    # 道具相机，仍留在表情之后画（要的就是遮脸）。

    def arm(side, a1, a2, hand="open", prop=None):
        s = side
        # 肩点内收：肩关节落在躯干轮廓上（arm_w/2 内嵌），胶囊与躯干无缝衔接
        sh = (cx + s * (sh_hw - arm_w * 0.30), sh_y)
        a1r, a2r = math.radians(a1), math.radians(a2)
        el = (sh[0] + s * math.sin(a1r) * up_len, sh[1] + math.cos(a1r) * up_len)
        ha = (el[0] + s * math.sin(a1r + a2r) * lo_len, el[1] + math.cos(a1r + a2r) * lo_len)
        wr = (el[0] + (ha[0] - el[0]) * 0.82, el[1] + (ha[1] - el[1]) * 0.82)
        CAP(sh, el, arm_w, fill=top)
        CAP(el, ha, arm_w * 0.88, fill=top)
        c0 = (el[0] + (ha[0] - el[0]) * 0.72, el[1] + (ha[1] - el[1]) * 0.72)
        c1 = (el[0] + (ha[0] - el[0]) * 0.88, el[1] + (ha[1] - el[1]) * 0.88)
        CAP(c0, c1, arm_w * 0.90, fill=mix(top, THEME["shade_dark"], 0.16))  # 袖口
        hr = hand_r
        E(ha[0] - hr, ha[1] - hr, ha[0] + hr, ha[1] + hr, fill=skin)
        if hand == "thumb":
            CAP((ha[0] + s * hand_r * 0.2, ha[1] - hr - u(0.018)), (ha[0] + s * hand_r * 0.66, ha[1] - hr - u(0.088)),
                u(0.044), fill=skin)
        if hand == "index":
            ai = a1r + a2r
            tip = (ha[0] + s * math.sin(ai) * u(0.13), ha[1] + math.cos(ai) * u(0.13))
            CAP((ha[0] + s * u(0.018), ha[1] - u(0.018)), tip, u(0.036), fill=skin)
        if prop == "bottle":
            RR(ha[0] - u(0.055), ha[1] - u(0.197), ha[0] + u(0.055), ha[1] - u(0.028), u(0.04), fill=THEME["bottle_green"])
            RR(ha[0] - u(0.028), ha[1] - u(0.242), ha[0] + u(0.028), ha[1] - u(0.186), u(0.018), fill=THEME["bottle_green_dark"])
        if prop == "beads":
            for k in range(6):
                ak = k * 1.05
                cxx, cyy = ha[0] + math.cos(ak) * u(0.062), ha[1] + u(0.017) + math.sin(ak) * u(0.062)
                E(cxx - u(0.02), cyy - u(0.02), cxx + u(0.02), cyy + u(0.02), fill=THEME["beads"])
        if prop == "camera":
            RR(ha[0] - u(0.096), ha[1] - u(0.073), ha[0] + u(0.096), ha[1] + u(0.073), u(0.034), fill=THEME["camera_body"])
            E(ha[0] - u(0.039), ha[1] - u(0.039), ha[0] + u(0.039), ha[1] + u(0.039), fill=THEME["lens_blue"])
        return ha, wr

    aL = pose.get("armL") or (7 + 5 * math.sin(2 * math.pi * t * 0.55), 8, "open", None)
    aR = pose.get("armR") or (7 - 5 * math.sin(2 * math.pi * t * 0.55), 8, "open", None)
    arm(-1, aL[0], aL[1], aL[2], aL[3] if len(aL) > 3 else None)
    ha_pos, wr_pos = arm(1, aR[0], aR[1], aR[2], aR[3] if len(aR) > 3 else None)
    for code, bc in (("watch", ident), ("bracelet", THEME["gold"]),
                     ("bracelet_leather", THEME["bracelet_leather"]), ("bracelet_woven", THEME["bracelet_woven"])):
        if has(code):
            CAP((wr_pos[0] - u(0.05), wr_pos[1] - u(0.022)), (wr_pos[0] + u(0.05), wr_pos[1] - u(0.022)),
                u(0.042), fill=bc)
    if pose.get("hand_prop") == "sparkle":
        for ang3 in (210, 270, 330):
            r0, r1 = hand_r * 0.85, hand_r * 1.52
            CAP((ha_pos[0] + math.cos(math.radians(ang3)) * r0, ha_pos[1] + math.sin(math.radians(ang3)) * r0),
                (ha_pos[0] + math.cos(math.radians(ang3)) * r1, ha_pos[1] + math.sin(math.radians(ang3)) * r1),
                u(0.02), fill=THEME["sparkle"])
    if pose.get("hand_prop") == "flash":
        E(ha_pos[0] - u(0.18), ha_pos[1] - u(0.18), ha_pos[0] + u(0.18), ha_pos[1] + u(0.18), fill=(255, 250, 214))

    # ================= 颈与头 =================
    neck_c = mix(skin, skin_sh, NECK_SHADE_F)  # 颈部受光少：skinShade 压深（qa_char 探针同源）
    RR(cx - u(0.105), G["chin"] - u(0.06), cx + u(0.105), torso_top + u(0.03), u(0.05), fill=neck_c)
    RR(cx - u(0.105), G["chin"] - u(0.06), cx + u(0.105), G["chin"] - u(0.06) + u(0.022), u(0.02),
       fill=mix(skin_sh, skin, 0.30))  # 下颌阴影
    if face == "heart":  # 心形脸：上半椭圆 + 直边 + 圆收下巴（底缘走二次贝塞尔弧，平滑无尖角——
        # 尖下巴观感像鬼，2026-10-03 用户反馈禁用；圆收下巴最低点仍过 chin 线，qa 探针面型感知）
        PIE(hx - rx, hy - ry, hx + rx, hy + ry, 180, 360, fill=skin)
        d.rectangle(TB(hx - rx, hy, hx + rx, hy + ry * 0.42), fill=skin)
        jaw = []
        for sg in (-1, 1):
            ks = range(11) if sg < 0 else range(10, -1, -1)
            jaw += [T((hx + sg * rx * ((1 - tk) ** 2 + 0.80 * tk * (1 - tk)),
                       hy + ry * (0.42 * (1 - tk) ** 2 + 2.10 * tk * (1 - tk) + 1.04 * tk * tk)))
                     for tk in (k / 10 for k in ks)]
        d.polygon(jaw, fill=skin)
    else:
        E(hx - rx, hy - ry, hx + rx, hy + ry, fill=skin)
    if face == "square":  # 方颌：椭圆底缘两侧外扩补平，下巴宽而钝
        d.polygon([T((hx - rx * 0.60, hy + ry * 0.55)), T((hx - rx * 0.92, hy + ry * 0.80)),
                   T((hx - rx * 0.80, hy + ry * 0.985)), T((hx + rx * 0.80, hy + ry * 0.985)),
                   T((hx + rx * 0.92, hy + ry * 0.80)), T((hx + rx * 0.60, hy + ry * 0.55))], fill=skin)
    for s in (-1, 1):  # 耳朵（多数发型被侧发覆盖，露出即增加真实感）
        eax = hx + s * rx * 0.94
        E(eax - u(0.045), eye_y - u(0.085), eax + u(0.045), eye_y + u(0.045), fill=skin)
        E(eax + s * u(0.005) - u(0.022), eye_y - u(0.058), eax + s * u(0.005) + u(0.022), eye_y - u(0.010),
          fill=mix(skin, skin_sh, 0.30))  # 耳窝影走 skinShade（不再写死）

    # ================= 前发（有机圆润 + 高光） =================
    cap_lo = hy + ry * 0.45
    PIE(hx - rx - 10, hy - ry - 10, hx + rx + 10, cap_lo, 182, 358, fill=hair_c)
    ARC(hx - rx * 0.60, hy - ry * 0.94, hx + rx * 0.28, hy - ry * 0.34, 220, 310, 12, fill=hl_c)
    if style in ("bob_bangs", "long_bangs"):
        for fx, fr in ((-0.62, 0.13), (-0.02, 0.16), (0.58, 0.13)):
            E(hx + rx * fx - rx * fr, hy - ry * 0.26 - rx * fr,
              hx + rx * fx + rx * fr, hy - ry * 0.26 + rx * fr, fill=hair_c)
    if style in ("bob", "bob_bangs", "wavy_lob", "wavy_long", "long_straight", "long_bangs"):
        yl = 0.55 if style in ("bob", "bob_bangs") else (0.95 if style == "wavy_lob" else 1.25)
        E(hx - rx - 34, hy - ry * 0.45, hx - rx + 26, hy + ry * yl, fill=hair_c)
        E(hx + rx - 26, hy - ry * 0.45, hx + rx + 34, hy + ry * yl, fill=hair_c)
    if style in ("short", "short_messy", "short_gray", "short_stubble", "crop", "crop_ahoge"):
        for fx, fy, fr in ((-0.45, -1.02, 22), (0.05, -1.08, 24), (0.52, -1.00, 20)):
            E(hx + rx * fx - fr, hy + ry * fy - fr, hx + rx * fx + fr, hy + ry * fy + fr, fill=hair_c)
        if style == "short_messy":
            E(hx + rx * 0.72, hy - ry * 1.04, hx + rx * 0.98 + 16, hy - ry * 0.84, fill=hair_c)
        if style == "short_stubble":
            ARC(hx - rx * 0.60, hy + ry * 0.50, hx + rx * 0.60, hy + ry * 1.05, 30, 150, 10,
                fill=mix(hair_c, skin, 0.55))
    if style in ("short_ahoge", "crop_ahoge"):  # 呆毛随晚风一颤（分镜 卡20 彩蛋；qa_motion 探针）
        ax = 5.0 * math.sin(2 * math.pi * 0.9 * t + 2 * math.pi * rnd(f"{seed}:ahoge"))
        CAP((hx + 10, hy - ry * 0.92), (hx + 52 + ax, hy - ry * 1.28 - abs(ax) * 0.35), 12, fill=hair_c)
        CAP((hx + 52 + ax, hy - ry * 1.28 - abs(ax) * 0.35), (hx + 88 + ax * 1.5, hy - ry * 1.08 - abs(ax) * 0.15),
            12, fill=hair_c)
    if style == "short_part":  # 侧分头：斜扫刘海＋分缝高光（江远/人形路标）
        for fx, fy, fr in ((-0.46, -0.62, 0.40), (0.10, -0.56, 0.42), (0.58, -0.64, 0.32)):
            E(hx + rx * fx - rx * fr, hy + ry * fy - rx * fr, hx + rx * fx + rx * fr,
              hy + ry * fy + rx * fr, fill=hair_c)
        CAP((hx - rx * 0.58, hy - ry * 0.74), (hx - rx * 0.28, hy - ry * 1.00), u(0.026), fill=hl_c)
    if style == "short_neat":  # 一丝不苟短发：平直刘海边（Théo/慢先生）
        RR(hx - rx * 0.82, hy - ry * 0.60, hx + rx * 0.82, hy - ry * 0.34, 10, fill=hair_c)
        CAP((hx - rx * 0.66, hy - ry * 0.70), (hx - rx * 0.20, hy - ry * 0.94), u(0.024), fill=hl_c)
    if style in ("short_wavy", "short_curly", "curly_short", "curly_volume", "undercut_curly"):
        a_lo, a_hi = (232, 308) if style == "undercut_curly" else (198, 342)
        n = 5 if style == "undercut_curly" else 7
        rr2 = 34 if style == "curly_volume" else 26
        for i in range(n):
            ang2 = math.radians(a_lo + i * (a_hi - a_lo) / (n - 1))
            cxx = hx + (rx + 4) * math.cos(ang2)
            cyy = hy + (ry + 4) * math.sin(ang2)
            E(cxx - rr2, cyy - rr2, cxx + rr2, cyy + rr2, fill=hair_c)
    if style == "bun":
        E(hx - 44, hy - ry - 86, hx + 44, hy - ry + 2, fill=hair_c)
        E(hx - 30, hy - ry - 72, hx + 30, hy - ry - 16, fill=hl_c)
    if style in ("ponytail_high", "curly_ponytail"):
        E(hx + rx * 0.70 - 26, hy - ry * 0.66 - 26, hx + rx * 0.70 + 26, hy - ry * 0.66 + 26,
          fill=ident if has("hair_tie") else mix(hair_c, (255, 255, 255), 0.25))
    if style == "ponytail_low":
        E(hx - rx * 0.90 - 22, hy + ry * 0.14 - 22, hx - rx * 0.90 + 22, hy + ry * 0.14 + 22,
          fill=ident if has("hair_tie") else mix(hair_c, (255, 255, 255), 0.25))
    if style in ("braid", "braid_long"):
        n2 = 4 if style == "braid" else 6
        fy_end = -0.02 + n2 * (0.52 if style == "braid" else 0.40)
        E(hx - rx * 1.00 - 18, hy + ry * fy_end - 14, hx - rx * 1.00 + 18, hy + ry * fy_end + 16, fill=ident)

    if has("beard"):  # 表情之前画：嘴要盖在胡子上
        PIE(hx - rx * 0.70, hy + ry * 0.34, hx + rx * 0.70, hy + ry * 1.30, 25, 155,
            fill=mix(hair_c, skin, 0.25))

    # ================= 表情 =================
    mood = MOOD_FACE[ctx["mood"]]
    lift = mood["lift"] + ctx.get("brow_lift_extra", 0)
    tilt = mood["tilt"]
    eye_k = EYE_MOOD[ctx["mood"]]  # 眼形：happy 微闭笑眼 / puzzled 睁大（plan §4 眼神变化）
    gdx, gdy = gaze(seed, t)  # 视线跟随镜头：漂移 ≤ (巩膜−瞳孔) 余量 × 0.35（探针安全）
    gpx = gdx * (scl_rx - pup_r) * 0.35
    gpy = gdy * (scl_ry - pup_r * 1.2) * 0.35
    for s in (-1, 1):
        ex = hx + s * eye_dx
        if ctx["blink"]:
            ARC(ex - scl_rx * 0.92, eye_y - scl_ry * 0.45, ex + scl_rx * 0.92, eye_y + scl_ry * 0.55,
                15, 165, u(0.024), fill=THEME["ink"])
        else:
            E(ex - scl_rx, eye_y - scl_ry * eye_k, ex + scl_rx, eye_y + scl_ry * eye_k, fill=(255, 255, 255))
            px, py = ex + gpx, eye_y + gpy
            E(px - pup_r, py - pup_r * 1.15, px + pup_r, py + pup_r * 1.25, fill=THEME["ink"])
            E(px - pup_r * 0.78, py - pup_r * 0.90, px - pup_r * 0.16, py - pup_r * 0.16,
              fill=(255, 255, 255))
            E(px + pup_r * 0.25, py + pup_r * 0.35, px + pup_r * 0.70, py + pup_r * 0.80,
              fill=(255, 255, 255))
            if female:
                CAP((ex + s * (scl_rx - u(0.008)), eye_y - scl_ry * eye_k * 0.82),
                    (ex + s * (scl_rx + u(0.040)), eye_y - scl_ry * eye_k - u(0.040)), u(0.020), fill=THEME["ink"])
        brow_y = brow_y0 - lift
        CAP((ex - s * u(0.062), brow_y - tilt), (ex + s * u(0.078), brow_y + tilt * 0.4), u(0.036),
            fill=THEME["ink"])
    mcx, mcy = hx, mouth_y
    op = ctx["openness"]
    WH = G["WH"]
    if op > 0.07:
        mw, mo = WH * (0.155 + 0.05 * op), u(0.035) + u(0.10) * op
        PIE(mcx - mw, mcy - mo, mcx + mw, mcy + mo, 0, 180, fill=THEME["mouth"])
        mt = mo * 0.45
        PIE(mcx - mw * 0.60, mcy + mo * 0.35 - mt, mcx + mw * 0.60, mcy + mo * 0.35 + mt, 0, 180,
            fill=THEME["tongue"])
    else:
        sw = WH * (0.155 + 0.05 * mood["smile"])
        if mood["smile"] > 0.4:
            ARC(mcx - sw, mcy - sw * 0.55, mcx + sw, mcy + sw * 0.80, 28, 152, u(0.026), fill=THEME["ink"])
        else:
            CAP((mcx - u(0.055), mcy), (mcx + u(0.055), mcy + (4 if tilt else 0)), u(0.022), fill=THEME["ink"])
    if p["energy"] == "lively":
        for s in (-1, 1):
            E(hx + s * 0.42 * WH - u(0.05), blush_y - u(0.028), hx + s * 0.42 * WH + u(0.05), blush_y + u(0.028),
              fill=THEME["blush"])

    # ================= 头部配饰 =================
    for code in ("glasses_round", "glasses_thin", "glasses_square", "glasses_plastic"):
        if has(code):
            col = {"glasses_plastic": THEME["glasses_plastic"],
                   "glasses_thin": THEME["glasses_thin"]}.get(code, THEME["glasses_dark"])
            wd = u(0.016) if code == "glasses_thin" else u(0.024)
            for s in (-1, 1):
                ex = hx + s * eye_dx
                if code == "glasses_round":
                    d.ellipse(TB(ex - scl_rx * 0.88, eye_y - scl_ry * 0.88, ex + scl_rx * 0.88, eye_y + scl_ry * 0.88),
                              outline=col, width=max(1, int(wd * sc * ss)))
                else:
                    d.rounded_rectangle(TB(ex - scl_rx * 0.92, eye_y - scl_ry * 0.78, ex + scl_rx * 0.92, eye_y + scl_ry * 0.78),
                                        u(0.035) * sc * ss, outline=col, width=max(1, int(wd * sc * ss)))
                eax = hx + s * rx * 0.94
                CAP((ex + s * scl_rx * 0.92, eye_y - scl_ry * 0.40), (eax + s * u(0.02), eye_y - scl_ry * 0.55),
                    wd * 0.7, fill=col)  # 镜腿
            CAP((hx - eye_dx + scl_rx * 0.85, eye_y - scl_ry * 0.38), (hx + eye_dx - scl_rx * 0.85, eye_y - scl_ry * 0.38),
                wd * 0.8, fill=col)  # 鼻梁
            if acc[code].get("physics") == "reflect":  # 镜片反光随时间滑动（qa_motion 探针）
                ggx = phys(seed, code, "reflect", t)[0]
                for s2 in (-1, 1):
                    ex2 = hx + s2 * eye_dx
                    E(ex2 - scl_rx * 0.62 + ggx, eye_y - scl_ry * 0.58,
                      ex2 - scl_rx * 0.30 + ggx, eye_y - scl_ry * 0.34, fill=THEME["glint_soft"])
    if has("sunglasses_head"):  # 顶戴：镜架倒扣在发顶，不遮眼
        sy0 = hy - ry * 0.80
        ggx_h = pfy("sunglasses_head", "reflect")[0]
        for s in (-1, 1):
            RR(hx + s * 52 - 32, sy0 - 22, hx + s * 52 + 32, sy0 + 14, 14, fill=THEME["metal_dark"])
            E(hx + s * 52 - 24, sy0 - 16, hx + s * 52 + 24, sy0 + 10, fill=THEME["lens"])
            E(hx + s * 52 - 20 + ggx_h, sy0 - 14, hx + s * 52 - 4 + ggx_h, sy0 - 4, fill=THEME["glint_blue"])
        CAP((hx - 28, sy0 - 14), (hx + 28, sy0 - 18), 7, fill=THEME["metal_dark"])
    hbdy = pfy("knit_hat", "bounce")[1]  # 帽子随步伐/点头轻弹（挂件物理；分镜 卡11）
    cbdy = pfy("cap_backward", "bounce")[1]
    shdy = pfy("sun_hat", "bounce")[1]
    if has("knit_hat"):
        PIE(hx - rx - 6, hy - ry - 16 + hbdy, hx + rx + 6, hy + ry * 0.17, 182, 358, fill=ident)
        RR(hx - rx - 10, hy - ry * 0.46 + hbdy, hx + rx + 10, hy - ry * 0.24 + hbdy, 16, fill=(255, 255, 255))
        E(hx - 26, hy - ry - 66 + hbdy, hx + 26, hy - ry - 14 + hbdy, fill=(255, 255, 255))
    if has("cap_backward"):
        PIE(hx - rx - 2, hy - ry - 8 + cbdy, hx + rx + 2, hy - ry * 0.10, 182, 358, fill=ident)
        E(hx - rx * 1.42, hy - ry * 0.74 + cbdy, hx - rx * 0.20, hy - ry * 0.36 + cbdy, fill=ident)
    if has("sun_hat"):
        E(hx - rx - 52, hy - ry * 0.78 + shdy, hx + rx + 52, hy - ry * 0.32 + shdy, fill=THEME["straw"])
        PIE(hx - rx * 0.78, hy - ry - 24 + shdy, hx + rx * 0.78, hy + ry * 0.02, 182, 358, fill=THEME["straw"])
        E(hx - rx * 0.78, hy - ry * 0.54 + shdy, hx + rx * 0.78, hy - ry * 0.36 + shdy, fill=ident)
    if has("headband_red"):  # 红发带＋意大利三色旗 wink（分镜 卡23：红发带飘起）
        gbdy = pfy("headband_red", "bounce")[1]
        ARC(hx - rx, hy - ry * 0.68 + gbdy, hx + rx, hy - ry * 0.14 + gbdy, 195, 345, 16, fill=THEME["headband_red"])
        for i, c in enumerate(THEME["it_flag"]):  # 右鬓角三色小条（绿白红；qa_char 探针）
            RR(hx + rx * 0.86 + i * 9, hy - ry * 0.52 + gbdy, hx + rx * 0.86 + i * 9 + 7, hy - ry * 0.24 + gbdy,
               2, fill=c)
    if has("hairpin"):
        CAP((hx + rx * 0.36, hy - ry * 0.80), (hx + rx * 0.64, hy - ry * 0.58), 12, fill=ident)
    if has("hairpin_clear"):
        CAP((hx + rx * 0.38, hy - ry * 0.74), (hx + rx * 0.68, hy - ry * 0.54), 10, fill=THEME["hairpin_clear"])
        if acc["hairpin_clear"].get("physics") == "reflect":  # 透明发夹一闪（分镜 卡27；qa_motion 探针）
            hgx = phys(seed, "hairpin_clear", "reflect", t)[0]
            E(hx + rx * 0.50 - 4 + hgx * 0.6, hy - ry * 0.68, hx + rx * 0.50 + 4 + hgx * 0.6, hy - ry * 0.60,
              fill=(255, 255, 255))
    if has("earrings_hoop"):
        hox, hoy = pfy("earrings_hoop", "swing")
        for s in (-1, 1):
            ARC(hx + s * rx * 0.96 - 14 + hox, hy + ry * 0.38 + hoy, hx + s * rx * 0.96 + 14 + hox,
                hy + ry * 0.38 + 28 + hoy, 0, 360, 5, fill=THEME["gold"])
    if has("jhumki"):
        jhx, jhy = pfy("jhumki", "swing")
        for s in (-1, 1):
            ex2 = hx + s * rx * 0.97
            E(ex2 - 9 + jhx, hy + ry * 0.36 + jhy, ex2 + 9 + jhx, hy + ry * 0.36 + jhy + 18, fill=THEME["gold"])
    if has("earrings_pearl"):
        for s in (-1, 1):
            E(hx + s * rx * 0.97 - 9, hy + ry * 0.36, hx + s * rx * 0.97 + 9, hy + ry * 0.36 + 18,
              fill=THEME["pearl"])
            E(hx + s * rx * 0.97 - 4, hy + ry * 0.36 + 4, hx + s * rx * 0.97 + 1, hy + ry * 0.36 + 9,
              fill=(255, 255, 255))  # 珍珠高光
    if has("headphones_neck") or has("headphones_one_ear"):
        hpc = "headphones_one_ear" if has("headphones_one_ear") else "headphones_neck"
        hdy2 = pfy(hpc, "bounce")[1]
        ARC(hx - rx * 0.90, hy + ry * 0.52, hx + rx * 0.90, hy + ry * 1.35, 15, 165, 13, fill=THEME["headphones"])
        sides = (-1,) if has("headphones_one_ear") else (-1, 1)
        for s in sides:
            E(hx + s * rx * 0.95 - 24, hy + ry * 0.88 + hdy2, hx + s * rx * 0.95 + 24, hy + ry * 0.88 + 52 + hdy2,
              fill=THEME["headphones"])
            E(hx + s * rx * 0.95 - 12, hy + ry * 0.88 + 14 + hdy2, hx + s * rx * 0.95 + 12, hy + ry * 0.88 + 38 + hdy2,
              fill=ident)

    # 手臂层已移至「颈与头」之前（衣服不得在人脸前面遮嘴）；face_cam 是举到脸前的道具相机，
    # 要的就是遮脸，故留在表情之后画。
    if pose.get("face_cam"):
        RR(hx - u(0.20), hy - u(0.11), hx + u(0.20), hy + u(0.11), u(0.05), fill=THEME["camera_body"])
        E(hx - u(0.062), hy - u(0.056), hx + u(0.062), hy + u(0.056), fill=THEME["lens_blue"])


# ---- 姿态库 ----

# pose_for 已实现的姿态码全集（场景线据此校验剧本标注，勿与 pose_for 实现脱节）
POSE_CODES = frozenset({
    "wave", "ciao_wave", "thumbs_up", "palm_open", "point", "nod", "shrug", "mini_jump",
    "jump_celebrate", "run_out", "turn_freeze", "come_along", "kick", "snap", "camera_snap",
    "chest_pat", "index_wait", "finger_count", "both_hands", "beads_ponder", "cap_tap",
    "scratch_head", "hand_shoot", "brow_raise", "head_tilt", "breath", "planner_snap",
    "clap", "fist", "bottle_raise", "deadpan_nod", "twirl", "lean_in", "pocket_sway",
    "head_tilt_smile", "thumbs_run", "shoot_run",
})


def pose_for(code, u, t, p):
    """返回姿态参数：armL/armR=(a1,a2,hand), legL/legR, head_dx/dy, squash, yoff, extras"""
    P = {}
    if code == "wave" or code == "ciao_wave":
        a1 = 138 if code == "wave" else 146
        P["armR"] = (a1, 26 + 26 * math.sin(t * 11), "open")
    elif code == "thumbs_up":
        P["armR"] = (150, 18, "thumb")
    elif code == "palm_open":
        P["armR"] = (78, 28, "open")
    elif code == "point":
        P["armR"] = (96, 6, "index")
    elif code == "nod":
        P["head_dy"] = 12 * math.sin(min(u, 1) * math.pi * 3) * (1 - min(u, 1))
    elif code == "shrug":
        P["armL"] = (52, 66, "open")
        P["armR"] = (52, 66, "open")
        P["yoff"] = -10
        P["head_dy"] = -4
    elif code == "mini_jump":
        hop = -abs(math.sin(u * math.pi * 2)) * jump_height(p)  # 起跳高度随 movement.bounce（plan §4）
        P["yoff"] = hop
        P["squash"] = 0.05 * math.sin(u * math.pi * 4)
        P["armL"] = (96, 30, "open")
        P["armR"] = (96, 30, "open")
    elif code == "jump_celebrate":  # 跳跃庆祝（plan §4.2 原语；示范场景二幕八专用）
        # squash-stretch：起跳蓄力下压 → 腾空纵向拉伸 → 落地压扁回弹
        air = abs(math.sin(u * math.pi * 2))
        P["yoff"] = -air * jump_height(p) * 1.15
        P["squash"] = 0.085 * math.cos(u * math.pi * 4) * (1 - 0.45 * air)
        P["armL"] = (152 - 14 * air, 18, "open")
        P["armR"] = (152 - 14 * air, 18, "open")
        P["head_dy"] = -5 * air
    elif code == "run_out":
        P["xoff"] = 1500 * ease_out_cubic(u)
        P["legL"] = 28 * math.sin(t * 16)
        P["legR"] = -28 * math.sin(t * 16)
        P["armL"] = (40 + 20 * math.sin(t * 16), 40, "open")
        P["armR"] = (40 - 20 * math.sin(t * 16), 40, "open")
        P["yoff"] = -6 * abs(math.sin(t * 16))
    elif code == "turn_freeze":
        P["xoff"] = -34 * u
        P["head_dx"] = -12 * u
        P["armR"] = (58, 122, "open")
    elif code == "come_along":
        P["armR"] = (86, 24 + 14 * math.sin(t * 7), "open")
        P["head_dx"] = 4
    elif code == "kick":
        P["legR"] = 38 * math.sin(min(u * 1.4, 1) * math.pi)
        P["skate_kick"] = math.sin(min(u * 1.4, 1) * math.pi)
        P["armL"] = (120, 30, "open")
    elif code == "snap":
        P["armR"] = (42, 112, "fist")
        if 0.3 < u < 0.75:
            P["hand_prop"] = "sparkle"
    elif code == "camera_snap":
        P["armL"] = (118, 62, "open")
        P["armR"] = (118, 62, "open")
        P["face_cam"] = True
        if 0.35 < u < 0.7:
            P["hand_prop"] = "flash"
    elif code == "chest_pat":
        P["armR"] = (32, 116 + 14 * math.sin(t * 8), "open")
    elif code == "index_wait":
        P["armR"] = (142, 22, "index")
    elif code == "finger_count":
        P["armR"] = (122, 32, "index")
    elif code == "both_hands":
        P["armL"] = (104, 18, "open")
        P["armR"] = (104, 18, "open")
    elif code == "beads_ponder":
        P["armR"] = (46, 100, "open", "beads")
        P["hand_prop"] = None
        P["head_dx"] = 7
        P["head_dy"] = 4
    elif code == "cap_tap":
        P["armR"] = (148, 40 + 12 * math.sin(t * 10), "open")
    elif code == "scratch_head":
        P["armR"] = (132, 74 + 12 * math.sin(t * 9), "open")
    elif code == "hand_shoot":
        P["armR"] = (176, 2, "open")
    elif code == "brow_raise":
        P["brow_lift_extra"] = 10 * math.sin(min(u, 1) * math.pi)
    elif code == "head_tilt":
        P["head_dx"] = 8
    elif code == "breath":
        P["squash"] = 0.035 * math.sin(min(u, 1) * math.pi)
        P["yoff"] = -8 * math.sin(min(u, 1) * math.pi)
        P["armL"] = (24, 14, "open")
        P["armR"] = (24, 14, "open")
    elif code == "planner_snap":
        P["armL"] = (36, 108, "open")
        P["armR"] = (36, 108, "open")
        if 0.25 < u < 0.6:
            P["hand_prop"] = "sparkle"
    elif code == "clap":
        P["armL"] = (44, 96, "open")
        P["armR"] = (44, 96, "open")
    elif code == "fist":
        P["armR"] = (46, 114, "fist")
    elif code == "bottle_raise":
        P["armR"] = (64, 92, "open", "bottle")
    elif code == "deadpan_nod":  # 卡20：面无表情点头（数据触发两次＝分镜"只两次"）
        P["head_dy"] = 10 * math.sin(min(u, 1) * math.pi * 2) * (1 - 0.4 * min(u, 1))
    elif code == "twirl":  # 卡05/09 入场旋转：水平压缩翻转读作转身
        P["xscale"] = 0.16 + 0.84 * abs(math.cos(min(u, 1) * math.pi * 2))
        P["yoff"] = -14 * abs(math.sin(min(u, 1) * math.pi * 2))
        P["armL"] = (96, 26, "open")
        P["armR"] = (96, 26, "open")
    elif code == "lean_in":  # 卡25：探身取景
        P["head_dx"] = 8
        P["head_dy"] = 5
        P["armR"] = (104, 38, "open")
    elif code == "pocket_sway":  # 卡24：插兜晃身
        P["armL"] = (14, 10, "open")
        P["armR"] = (14, 10, "open")
        P["head_dx"] = 6 * math.sin(min(u, 1) * math.pi * 2)
    elif code == "head_tilt_smile":  # 卡27：侧头一笑定格
        P["head_dx"] = 13
        P["head_dy"] = 2
        P["armR"] = (58, 30, "open")
    elif code == "thumbs_run":  # 卡28：thumbs-up 后招手小跑出画
        if u < 0.45:
            P["armR"] = (150, 18, "thumb")
            P["armL"] = (60, 30, "open")
        else:
            P["xoff"] = 1500 * ease_out_cubic((u - 0.45) / 0.55)
            P["legL"] = 28 * math.sin(t * 16)
            P["legR"] = -28 * math.sin(t * 16)
            P["armL"] = (40 + 20 * math.sin(t * 16), 40, "open")
            P["armR"] = (140, 26 + 26 * math.sin(t * 11), "open")
            P["yoff"] = -6 * abs(math.sin(t * 16))
    elif code == "shoot_run":  # 卡22：投篮手势后追球跑出画
        if u < 0.5:
            P["armL"] = (128, 60, "open")
            P["armR"] = (128, 60, "open")
            P["squash"] = 0.04 * math.sin(min(u / 0.5, 1) * math.pi)
        else:
            P["xoff"] = 1500 * ease_out_cubic((u - 0.5) / 0.5)
            P["legL"] = 28 * math.sin(t * 16)
            P["legR"] = -28 * math.sin(t * 16)
            P["armL"] = (40 + 20 * math.sin(t * 16), 40, "open")
            P["armR"] = (40 - 20 * math.sin(t * 16), 40, "open")
            P["yoff"] = -6 * abs(math.sin(t * 16))
    return P


# ---- 卡片渲染 ----

def load_timeline(pid):
    return json.loads((AUDIO_DIR / f"{pid}.timeline.json").read_text("utf-8"))


def karaoke_points(line):
    """[(t, frac)] 词首/词尾的字符进度点"""
    words = line["words"]
    total = sum(len(w["w"]) for w in words) + max(0, len(words) - 1)
    pts = [(line["start"], 0.0)]
    c = 0.0
    for i, w in enumerate(words):
        c += len(w["w"])
        pts.append((max(w["s"], line["start"]), c / total))
        c += 1 if i < len(words) - 1 else 0
        pts.append((w["e"], c / total))
    pts.append((line["start"] + line["dur"] + 0.15, 1.0))
    return pts


def frac_at(pts, t):
    if t <= pts[0][0]:
        return 0.0
    for i in range(1, len(pts)):
        if t <= pts[i][0]:
            t0, f0 = pts[i - 1]
            t1, f1 = pts[i]
            if t1 <= t0:
                return f1
            return f0 + (f1 - f0) * (t - t0) / (t1 - t0)
    return 1.0


def openness_at(lines, t, seed=""):
    op = 0.0
    for line in lines:
        if t < line["start"] - 0.05 or t > line["start"] + line["dur"] + 0.2:
            continue
        for w in line["words"]:
            amp = 0.55 + 0.45 * rnd(f"{seed}:open:{w['w']}:{round(w['s'], 2)}")  # 种子命名空间（不变量⑦）
            if w["s"] <= t <= w["e"]:
                op = max(op, amp)
            elif w["e"] < t < w["e"] + 0.13:
                op = max(op, amp * (1 - (t - w["e"]) / 0.13))
            elif t < w["s"] < t + 0.05:
                op = max(op, amp * 0.7)
    return op


def render_card(pid, personas, doc):
    from PIL import Image, ImageDraw
    card, variant = find_card(doc, pid)
    base_pid = card["id"]
    p = personas[base_pid]  # 变体共享人设/场景/收尾/手势，仅 lines 不同（self-intro §1.4）
    tl = load_timeline(pid)
    lines = tl["lines"]
    rtl = bool(p.get("rtl"))
    seed = base_pid  # 角色级随机（眨眼/张口/视线）走人设命名空间：变体与主卡同相位，qa 可复算
    blink_cyc = p["movement"]["blinkCycleSec"]
    breath = p["movement"]["breathAmp"]
    cast = doc["cast"][base_pid]

    bg = prerender_bg(p, card)
    bands = []
    for i in range(len(lines)):
        base = Image.open(TEXT_DIR / f"band_{pid}_{i}_base.png").convert("RGB")
        hl = Image.open(TEXT_DIR / f"band_{pid}_{i}_hl.png").convert("RGB")
        bands.append((base, hl, karaoke_points(lines[i])))
    def tight(im):
        """matte 资产按 alpha bbox 裁紧（内容在 1080x300 画布中心，裁紧后以中心点粘贴）"""
        a = im.getchannel("A").point(lambda v: 255 if v > 8 else 0)
        box = a.getbbox()
        return im.crop(box) if box else im

    badge = tight(Image.open(TEXT_DIR / f"badge_{base_pid}.png").convert("RGBA"))
    pill = tight(Image.open(TEXT_DIR / f"pill_{p['locale']}.png").convert("RGBA"))  # 语言牌（plan §8.3）
    if cast == "A":
        bubble = tight(Image.open(TEXT_DIR / f"bubble_a_{base_pid}.png").convert("RGBA"))
    else:
        bubble = tight(Image.open(TEXT_DIR / ("bubble_b_l.png" if rtl else "bubble_b_r.png")).convert("RGBA"))

    # 手势触发时间
    triggers = []
    all_words = [(w, li) for li, line in enumerate(lines) for w in line["words"]]
    for g in card.get("gestures", []):
        hit = next((w for w, li in all_words if g["at"] in w["w"]), None)
        t0 = hit["s"] if hit else lines[0]["start"]
        triggers.append((t0, g["do"], g["dur"]))

    speech_end = tl["speechEnd"]
    entry = tl["entry"]
    ident = hexc(p["identity"])
    # 收尾码列（分镜：单码或按序码列；跑出画族占满剩余时长）
    close_seq = card["close"]
    close_seq = close_seq if isinstance(close_seq, list) else [close_seq]
    close_start = min(speech_end + 0.15, DUR - 0.9)

    def close_dur_for(cc, t0):
        if cc in ("run_out", "thumbs_run", "shoot_run"):
            return DUR - t0 - 0.1
        return {"mini_jump": 1.1, "turn_freeze": 0.9, "snap": 0.9, "camera_snap": 1.0}.get(cc, 1.3)

    close_list = []
    tt = close_start
    for cc in close_seq:
        dd = close_dur_for(cc, tt)
        close_list.append((tt, dd, cc))
        tt += dd
    # 入场姿态（分镜 entry_pose；取代旧的"活泼统一挥手"硬编码）
    ep_codes = card.get("entry_pose") or []
    ep_codes = [ep_codes] if isinstance(ep_codes, str) else list(ep_codes)
    ep_end = min(entry, 1.2)
    ep_list = ([(0.05 + (ep_end - 0.05) * k / len(ep_codes),
                 0.05 + (ep_end - 0.05) * (k + 1) / len(ep_codes), c)
                for k, c in enumerate(ep_codes)]) if ep_codes else []
    bubble_t = (max(lines[-1]["start"] + 0.6, speech_end - 2.6)) if cast == "A" else max(speech_end - 2.3, lines[-1]["start"] + 0.5)

    out_path = OUT_DIR / f"{pid}.mp4"
    cmd = ["ffmpeg", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(AUDIO_DIR / f"{pid}.m4a"),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-shortest", "-t", str(DUR), "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    band_prev_img = None
    band_prev_until = -1.0
    prev_li = None
    bub_w, bub_h = bubble.size
    tail_col = hexc(UI_INK)
    for f in range(FRAMES):
        t = f / FPS
        layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        lds = DrawScaled(ld, SS)

        # 进度条
        lds.rounded_rectangle([PROG_X0, PROG_Y0, PROG_X1, PROG_Y1], 8, fill=mix((255, 255, 255), ident, 0.25))
        fw = PROG_X0 + (PROG_X1 - PROG_X0) * (t / DUR)
        lds.rounded_rectangle([PROG_X0, PROG_Y0, fw, PROG_Y1], 8, fill=ident)

        # 文字带（卡拉OK高亮 + 行间交叉淡化）
        li = 0
        for i, line in enumerate(lines):
            if t >= line["start"] - 0.18:
                li = i
        if prev_li is not None and prev_li != li:
            band_prev_img = bands[prev_li][1]  # 上一行收尾态（全高亮）
            band_prev_until = t + 0.22
        prev_li = li
        base, hl, pts = bands[li]
        band_img = base.copy()
        frac = frac_at(pts, t)
        if frac > 0.01:
            bw = int(W * frac)
            if rtl:
                crop = hl.crop((W - bw, 0, W, BAND_H))
                band_img.paste(crop, (W - bw, 0))
            else:
                crop = hl.crop((0, 0, bw, BAND_H))
                band_img.paste(crop, (0, 0))
        if band_prev_img is not None and t < band_prev_until:
            k = (band_prev_until - t) / 0.22
            band_img = Image.blend(band_img, band_prev_img, min(1.0, k))

        # 人物上下文
        mood = lines[li]["mood"]
        pose = {}
        scale, xoff, yoff, squash = 1.0, 0.0, 0.0, 0.0
        if p["energy"] == "lively":
            scale = max(0.02, pop_scale(t, 0.0, entry, True, damp=p["movement"]["bounce"]))
        else:
            u = min(1.0, t / entry)
            xoff = -300 * (1 - ease_out_cubic(u))
            yoff = -5 * abs(math.sin(u * math.pi * 3))
        # 词触发手势
        g_active = None
        for t0, gcode, gdur in triggers:
            if t0 <= t < t0 + gdur:
                g_active = (gcode, (t - t0) / gdur)
                break
        # 入场姿态（分镜 entry_pose）
        e_active = None
        for d0, d1, ecode in ep_list:
            if d0 <= t < d1:
                e_active = (ecode, (t - d0) / (d1 - d0))
                break
        # 收尾招牌（码列按序衔接）
        c_active = None
        for t0, cdur, ccode in close_list:
            if t0 <= t < t0 + cdur:
                c_active = (ccode, (t - t0) / cdur)
                break
        src = None
        if c_active:
            src = c_active
        elif g_active:
            src = g_active
        elif e_active:
            src = e_active
        if src:
            pose.update(pose_for(src[0], src[1], t, p))
        # 说话时轻摆
        if not src and openness_at(lines, t, seed) > 0.05:
            pose.setdefault("armR", (16 - 5 * math.sin(2 * math.pi * t * 0.9), 12, "open"))

        yoff += pose.pop("yoff", 0)
        xoff += pose.pop("xoff", 0)
        squash = pose.pop("squash", 0) + breath * (0.5 - 0.5 * math.cos(2 * math.pi * t * 0.42))
        if p["energy"] == "lively":
            kb = clamp(14.0 / p["movement"]["bounce"], 0.75, 1.6)  # 呼吸起伏随 bounce 缩放
            yoff += -4 * kb * abs(math.sin(2 * math.pi * t * 0.85))

        # 眨眼
        n = int(t / blink_cyc)
        ph = (t / blink_cyc) - n
        jit = 0.15 + 0.65 * rnd(f"{seed}:blink:{n}")
        blink = jit <= ph <= jit + 0.05

        op = openness_at(lines, t, seed)
        if t >= speech_end + 0.05 or t < entry:
            op = 0.0

        ctx = dict(scale=scale, xoff=xoff, yoff=yoff, squash=squash,
                   xscale=pose.pop("xscale", 1.0),
                   head_dx=pose.pop("head_dx", 0), head_dy=pose.pop("head_dy", 0),
                   brow_lift_extra=pose.pop("brow_lift_extra", 0),
                   pose=pose, openness=op, blink=blink, mood=mood, ss=SS)
        draw_character(layer, ld, p, t, ctx)

        # 气泡尾（画进 2x 层 → 抗锯齿；本体粘贴时盖住尾根）
        cx_t = BUBBLE_CX if not rtl else W - BUBBLE_CX
        if t >= bubble_t and pop_scale(t, bubble_t, 0.5, True) > 0.98:
            by0 = BUBBLE_CY - bub_h // 2
            yb = by0 + bub_h - 2
            xa = cx_t + int(bub_w * (0.20 if not rtl else -0.20))
            p0 = (xa - 24, yb - 34)
            p1 = (xa + 24, yb - 34)
            p2 = (xa + (8 if not rtl else -8), yb + 4)
            lds.polygon([p0, p1, p2], fill=(255, 255, 255))
            lds.line([p0, p2], fill=tail_col, width=5)
            lds.line([p1, p2], fill=tail_col, width=5)

        # 合成：2x 层 BOX 精确降采样（2x 整数倍 = 面积平均抗锯齿）→ 背景 → 文字带
        layer = layer.resize((W, H), Image.Resampling.BOX)
        img = bg.copy()
        img.paste(layer, (0, 0), layer)
        img.paste(band_img, (0, BAND_Y))

        # 名牌（0.6s 弹出）
        bs = pop_scale(t, 0.6, 0.55, True)
        if bs > 0.02:
            b = badge
            if bs < 0.995:
                b = badge.resize((max(2, int(badge.width * bs)), max(2, int(badge.height * bs))), Image.Resampling.LANCZOS)
            img.paste(b, (540 - b.width // 2, BADGE_Y + (BADGE_BOX_H - b.height) // 2), b)

        # 语言牌（入场前 0.3s 弹出；国旗 emoji＋语种文字，plan §8.3）
        if t >= entry - 0.3:
            ps = pop_scale(t, entry - 0.3, 0.4, True)
            if ps > 0.02:
                pl = pill
                if ps < 0.995:
                    pl = pill.resize((max(2, int(pill.width * ps)), max(2, int(pill.height * ps))), Image.Resampling.LANCZOS)
                img.paste(pl, (540 - pl.width // 2, PILL_Y + (PILL_BOX_H - pl.height) // 2), pl)

        # 气泡（尾巴已在 2x 层画好；中心点定位）
        if t >= bubble_t:
            us = pop_scale(t, bubble_t, 0.5, True)
            if us > 0.02:
                bb = bubble
                if us < 0.995:
                    bb = bubble.resize((max(2, int(bubble.width * us)), max(2, int(bubble.height * us))), Image.Resampling.LANCZOS)
                bx0 = cx_t - bb.width // 2
                by0 = BUBBLE_CY - bb.height // 2
                img.paste(bb, (bx0, by0), bb)

        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()
    print(f"[render] {pid} -> {out_path.name} rc={proc.returncode}")


def cmd_render(only, workers):
    from multiprocessing import Pool
    personas, doc = load_data()
    ids = [u["id"] for u in card_units(doc) if not only or u["persona"] in only]
    with Pool(min(workers, len(ids))) as pool:
        pool.starmap(render_card, [(pid, personas, doc) for pid in ids])


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["tts", "assets", "render"])
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if args.phase == "tts":
        cmd_tts(only)
    elif args.phase == "assets":
        cmd_assets(only)
    else:
        cmd_render(only, args.workers)


if __name__ == "__main__":
    main()
