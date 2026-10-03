#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_video.py — 教学场景 A/B 对话渲染线（M2，场景无关）

数据：lessons/<id>/scene.md ──parse_scene.py --scene <id>──▶ lessons/<id>/scene.json + personas/personas.json
产物：build/scene/scene-<id>_<locale>.mp4（1080x1920 @ 30fps，每语种一支）

人物 rig（face_geo / draw_character / pose_for / gaze / phys / 挂件物理 / 场景原语 / 文字层
抠像 / 情绪增量表）全部 import 自 intro_cards.py，本文件只写「场景层」：选角、双人同框站位、
token 装置（`#hex` 色片 / `"文本"` 字牌，可选）、道具高亮、气泡与 RTL 镜像
（不变量①：不复制人物代码；不变量⑦：随机全走种子）。
场景是数据不是代码：token / RTL / 装置几何全部来自剧本 §0 机读规格，
新教学场景 = 在 `lessons/<id>/` 新建 `scene.md` 照抄体例，本文件零改动。

三段管线（uv 管理单一 .venv，入口见 run.ps1）：
    uv run usine-scene tts     --scene <id> [--only zh-CN,...]   # edge-tts：逐行合成 + 词级时间戳
    uv run usine-scene assets  --scene <id> [--only ...]         # Edge headless 文字层
    uv run usine-scene render  --scene <id> [--only ...] [--workers 6]   # Pillow+numpy 帧渲染

用法：.\run.ps1 scene -Scene <id>    # = parse → tts → assets → render
      uv run usine-scene list --scene <id>   # 场景概览（token / RTL / 装置 / 时长）
"""
import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
from pathlib import Path

from .intro_cards import (
    W, H, FPS, SS, THEME, SCENES, UI_INK, BAND_BG, BAND_Y, BAND_H, EDGE, FONT_CSS, FLAG,
    HTML_HEAD, DrawScaled, clamp, content_hash, effective_voice, ease_out_cubic,
    hexc, html_escape, matte_combine, mix, openness_at, pop_scale, pose_for, probe_duration,
    draw_character, synth_line, rnd, POSE_CODES,
)
from .parse_scene import scene_paths    # lessons/<id>/scene.md / scene.json 命名约定的唯一事实源
from usine import ROOT as HERE          # 仓库根（lessons/ / personas / build 的锚点）

SCENE_ID = "colors"                      # CLI --scene 覆盖
PREFIX = f"scene-{SCENE_ID}"            # 产物/缓存名前缀：scene-colors_<locale>.mp4
RTL_LOCALES = set()                     # 由 load_data() 从剧本 §0 rtlLocales 填充
SCENE_TOKENS = []                       # 由 load_data() 从剧本 §0.1 token 书写序填充

ROOT = HERE / "build" / "scene"
AUDIO_DIR = ROOT / "audio"
TEXT_DIR = ROOT / "text"

# ---- 场景层布局（1x 语义坐标；与亮相卡的 BAND_*/BADGE_* 各自独立，互不影响）----
PROG = (60, 40, 1020, 56)               # 进度条外框
BADGE_Y, BADGE_W, BADGE_H = 424, 400, 180
BUBBLE_CY = 700                         # 气泡中心 y
DEV_CY = 966                            # token 装置行中心 y
CHAR_SCALE = 0.76                       # 双人同框：人物缩放（源几何 900→1710 ≈ 810px 高）
PILL_Y, PILL_H = 1782, 88
DEV_SPAN = 812                          # 装置井行总宽（6 井均分）
DEV_X0 = 134                            # 装置井行左缘

AX, BX = 322, 758                       # A / B 站位中心 x（RTL 时左右对调）

# 装置几何（井宽/井高/井形/空井色）全部由剧本 §0.2 装置规格表给定（parse_scene.py 落 data），
# 代码里只留**样式库**：style → 外框画法。shape: round 圆角矩形 / circle 椭圆 / rect 矩形 / poly 三角
DEVICE_STYLES = ("palette", "chalkboard", "bookspine", "signpost", "fruit_basket", "chalk_stone",
                 "doorframe", "lanterns", "rangoli", "traffic_lamp", "cone", "gelato",
                 "dyed_cloth", "neon", "tray")
# 姿态码走 intro_cards.POSE_CODES 注册表（bounce_in 属入场动画，单独处理）
ENTRY_GAP = 0.55        # 句间呼吸（§1.4 句尾 0.6–0.8s 的对话化取值）
ENTRY_IN = 1.0         # 双人入场
TAIL = 2.0             # 收束：挥手/出画 + 落幅
POSE_DUR = 1.15        # 手势时长（pose_for 的 u∈[0,1]）


# ---------- 数据 ----------

def load_data():
    personas = {p["id"]: p for p in
                json.loads((HERE / "personas" / "personas.json").read_text("utf-8"))["personas"]}
    cards = json.loads((HERE / "personas" / "intro-cards.json").read_text("utf-8"))
    _, scene_json = scene_paths(SCENE_ID)
    if not scene_json.exists():
        raise SystemExit(f"场景数据不存在：{scene_json.name}（先跑 parse_scene.py --scene {SCENE_ID}）")
    scene = json.loads(scene_json.read_text("utf-8"))
    RTL_LOCALES.clear()
    RTL_LOCALES.update(scene.get("rtlLocales") or [])
    global SCENE_TOKENS
    SCENE_TOKENS = list(scene.get("tokenOrder") or [])
    return personas, cards, scene


def casting(locale, personas, cards, scene):
    """A = 活泼者（先问方）/ B = 沉稳者（plan §6.1）。选角走 intro-cards.json 的 cast 事实源，
    并与剧本 §4 casting 表的姓名交叉核对（不一致即报错，绝不静默换角）。"""
    loc = scene["locales"][locale]
    picked = {}
    for role in ("A", "B"):
        ids = [pid for pid, p in personas.items()
               if p["locale"] == locale and cards["cast"].get(pid) == role]
        if len(ids) != 1:
            raise ValueError(f"{locale} {role} 角选派异常：{ids}")
        picked[role] = ids[0]
    for role, want in (("A", loc["aName"]), ("B", loc["bName"])):
        got = personas[picked[role]]["name"]["native"]
        if got != want:
            raise ValueError(f"{locale} {role} 角与剧本 §4 不符：档案 {got} ≠ 剧本 {want}")
    return picked


def locales_of(only):
    _, _, scene = load_data()
    keys = list(scene["locales"].keys())
    return [k for k in keys if not only or k in only]


def is_rtl(locale):
    """RTL 语种由剧本 §0 `rtlLocales` 给定（lessons/colors/scene.md §1.5：文字区右起、站位对调）。"""
    return locale in RTL_LOCALES


def device_of(loc):
    """该语种的舞台装置规格（剧本 §0.2）；缺行 = 纯对话无装置。"""
    return (loc.get("prop") or {}).get("device")


def well_color(device, pal):
    """空井底色：§0.2 `well` 显式给色则用之，否则由场景中性色推导
    （浅色 token 落在同色底上会看不见——手册场景线配方）。"""
    w = (device or {}).get("well") or ""
    return hexc(w) if w.startswith("#") else mix(pal["soft"], (255, 255, 255), 0.55)


def chip_color(chip):
    """教学 token chip 两型：`#hex` 色片 → RGB；`"文本"` 字牌 → None（走文字层贴图）。"""
    return hexc(chip) if isinstance(chip, str) and chip.startswith("#") else None


def side_x(locale, role):
    """站位 x：RTL 语种左右对调（§1.5 站位对调）；文字带/名牌/气泡随之镜像。"""
    rtl = is_rtl(locale)
    if role == "A":
        return BX if rtl else AX
    return AX if rtl else BX


# ---------- TTS（系统 Python + edge-tts）----------

def compose_scene_audio(files, starts, dur, out_m4a):
    n = len(files)
    inputs = []
    for f in files:
        inputs += ["-i", str(f)]
    fc = [f"[{i}:a]adelay={int(round(s*1000))}|{int(round(s*1000))}[a{i}]" for i, s in enumerate(starts)]
    mixin = "".join(f"[a{i}]" for i in range(n))
    fc.append(f"{mixin}amix=inputs={n}:normalize=0[m]" if n > 1 else f"{mixin}anull[m]")
    # apad 必须前置 loudnorm（手册坑③）：否则补尾的 EOF 冲刷非确定
    fc.append(f"[m]apad=whole_dur={dur},loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{dur}[out]")
    subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out_m4a)],
                   check=True, capture_output=True)


def pick_pose(ln):
    """该行手势码：取剧本标注的最后一个可用姿态码（bounce_in 归入场动画）。"""
    for code in reversed(ln["gesture"]["poses"]):
        if code in POSE_CODES:
            return code
    return None


def cmd_tts(only):
    personas, cards, scene = load_data()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for locale in locales_of(only):
        loc = scene["locales"][locale]
        cast = casting(locale, personas, cards, scene)
        lines_out, files = [], []
        for ln in loc["dialogue"]:
            p = personas[cast[ln["speaker"]]]
            rate, pitch = effective_voice(p, ln["mood"], cards["moods"])
            key = content_hash(p["voice"]["voiceId"], rate, pitch, ln["text"])
            mp3, wjs = AUDIO_DIR / f"{key}.mp3", AUDIO_DIR / f"{key}.json"
            if not (mp3.exists() and wjs.exists()):
                data, words = asyncio.run(synth_line(ln["text"], p["voice"]["voiceId"], rate, pitch))
                mp3.write_bytes(data)
                wjs.write_text(json.dumps(words, ensure_ascii=False), "utf-8")
                print(f"[tts] synth {locale}#{ln['i']} {ln['speaker']} {rate} {pitch} key={key}")
            words = json.loads(wjs.read_text("utf-8"))
            dur = probe_duration(mp3)
            # 词级真值裁尾：mp3 尾部静音按末词结束点 +0.2s 收（与亮相卡同一口径）
            if not (len(words) == 1 and words[0]["w"] == ln["text"][:12]):
                dur = min(dur, words[-1]["t"] + words[-1]["d"] + 0.20)
            lines_out.append({"key": key, "dur": dur, "words": words})
            files.append(mp3)

        t = ENTRY_IN
        for lo in lines_out:
            lo["start"] = t
            t += lo["dur"] + ENTRY_GAP
        speech_end = t - ENTRY_GAP
        dur = round(speech_end + TAIL, 2)

        for lo, ln in zip(lines_out, loc["dialogue"]):
            for w in lo["words"]:
                w["s"] = round(lo["start"] + w["t"], 3)
                w["e"] = round(w["s"] + w["d"], 3)
            pose = pick_pose(ln)
            anchor = ln["gesture"]["word"] if pose else ""
            hit = next((w for w in lo["words"] if anchor and anchor in w["w"]), None)
            lo.update({
                "i": ln["i"], "speaker": ln["speaker"], "mood": ln["mood"],
                "text": ln["text"], "tokenKey": ln["tokenKey"],
                "bubble": ln["bubble"], "exits": ln["exits"],
                "pose": pose, "poseWord": anchor,
                "poseT": (hit["s"] if hit else lo["start"]),   # 手势词未逐字命中 → 回退行首（§6）
            })

        ask, seen = [], set()
        for lo in lines_out:
            if lo["tokenKey"] and lo["tokenKey"] not in seen:
                seen.add(lo["tokenKey"])
                ask.append({"t": lo["start"], "key": lo["tokenKey"]})

        compose_scene_audio(files, [lo["start"] for lo in lines_out], dur,
                            AUDIO_DIR / f"{PREFIX}_{locale}.m4a")
        tl = {"locale": locale, "duration": dur, "entry": ENTRY_IN, "speechEnd": speech_end,
              "cast": cast, "rtl": is_rtl(locale), "ask": ask, "lines": lines_out}
        (AUDIO_DIR / f"{PREFIX}_{locale}.timeline.json").write_text(
            json.dumps(tl, ensure_ascii=False, indent=1), "utf-8")
        print(f"[tts] {locale} lines={len(lines_out)} speech_end={speech_end:.2f}s duration={dur:.2f}s")


# ---------- 文字层（Edge headless）----------

def hl_hex(chip):
    """卡拉OK高亮色 = 当前 token 的色片 chip 提亮；浅色 chip 在深带上无对比 → 落主题金。
    深色 chip（如黑）22% 提亮距带底仅 ~73 → 逐档加白直到 ≥120（qa_scene §4 有对比探针）。
    字牌 chip（`"文本"`）无色相 → 落白色。"""
    c = chip_color(chip)
    if c is None:
        return "#FFFFFF"
    if 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 170:
        return "#%02X%02X%02X" % THEME["gold"]
    for k in (0.22, 0.30, 0.38, 0.46, 0.54, 0.62, 0.70, 0.78):
        c2 = mix(c, (255, 255, 255), k)
        d2 = sum((c2[i] - BAND_BG[i]) ** 2 for i in range(3))
        if d2 >= 120 ** 2:
            return "#%02X%02X%02X" % c2
    return "#%02X%02X%02X" % mix(c, (255, 255, 255), 0.78)


BAND_GLOSS = "#AEB6DC"   # 中文翻译（比原文小一号，柔浅紫灰——与深带底对比 ≥ 150）
BAND_NOTE = "#E8C24A"    # 文化/语言注记（比翻译再小一号，主题金）


def band_text_html(text, gloss, note, locale, rtl, color):
    """文字带（三层堆叠，布局不变量：全部内容收在 BAND_H 内）：
    原文（64px 自动缩排）→ 中文翻译（30px，比原文小）→ ⚑ 文化/语言注记（22px，比翻译再小）。
    注记仅「特别需要说明的」行才有（剧本 ⚑ 段），翻译每行必有（——中文对照）。"""
    gl = (f'<div id="g" dir="ltr" style="max-width:{W-120}px;font-size:30px;line-height:1.35;'
          f'font-weight:500;color:{BAND_GLOSS};text-align:center;">{html_escape(gloss)}</div>'
          if gloss else "")
    nt = (f'<div id="n" dir="ltr" style="max-width:{W-120}px;font-size:22px;line-height:1.4;'
          f'font-weight:600;color:{BAND_NOTE};text-align:center;">⚑ {html_escape(note)}</div>'
          if note else "")
    body = f"""<div id="wrap" style="flex-direction:column;justify-content:center;
      gap:10px;"><div id="t"
      style="max-width:{W-96}px;padding:0 20px;text-align:center;color:{color};
      font-size:64px;font-weight:600;line-height:1.3;">{html_escape(text)}</div>{gl}{nt}</div>
    <script>
    var el=document.getElementById('t');var fs=64;
    while(fs>30&&el.parentElement.scrollHeight>{BAND_H-30}){{fs-=2;el.style.fontSize=fs+'px';}}
    </script>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=f"rgb{BAND_BG}", font=FONT_CSS[locale] + ", 'Microsoft YaHei', sans-serif",
                            dir="rtl" if rtl else "ltr", body=body)


def bubble_text_html(text, swatch, locale, rtl, bg="#FFFFFF"):
    """场景气泡：思考气泡带当前色小方块（色名预览），提示气泡只给联想物。
    流式布局（position:absolute 会破坏父盒高度——不变量⑥）。"""
    sw = (f'<span style="display:inline-block;width:40px;height:40px;border-radius:12px;'
          f'background:{swatch};border:3px solid {UI_INK};vertical-align:-4px;'
          f'margin-{"left" if rtl else "right"}:18px;"></span>') if swatch else ""
    body = f"""<div id="wrap"><div id="b" style="max-width:840px;background:#FFFFFF;
      border:5px solid {UI_INK};border-radius:48px;padding:22px 36px;text-align:center;
      box-shadow:0 12px 28px rgba(35,40,63,0.25);">
      <span id="s" style="font-size:46px;line-height:1.35;font-weight:700;color:#23283D;
      direction:{"rtl" if rtl else "ltr"};">{sw}{html_escape(text)}</span></div></div>
    <script>
    var el=document.getElementById('s');var fs=46;
    while(fs>24&&el.scrollWidth>820){{fs-=2;el.style.fontSize=fs+'px';}}
    </script>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg, font=FONT_CSS[locale], dir="ltr", body=body)


def token_plaque_html(text, locale, rtl, bg):
    """字牌 chip 的井内文字层：token 词（该语种字形）居中，底色 = 装置空井色。"""
    body = f"""<div id="wrap"><div id="t"
      style="width:600px;height:240px;display:flex;align-items:center;justify-content:center;
      background:{bg};border-radius:24px;direction:{"rtl" if rtl else "ltr"};">
      <span id="s" style="font-size:76px;font-weight:800;color:#23283D;line-height:1.2;
      text-align:center;">{html_escape(text)}</span></div></div>
    <script>
    var el=document.getElementById('s');var fs=76;
    while(fs>22&&el.scrollWidth>560){{fs-=2;el.style.fontSize=fs+'px';}}
    </script>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg, font=FONT_CSS[locale], dir="ltr", body=body)


def sbadge_html(p, bg="#FFFFFF"):
    """场景名牌（半宽 400px，A/B 各一块）：身份色描边 + native 名 + 拉丁名。"""
    rtl = "rtl" if p.get("rtl") else "ltr"
    body = f"""<div id="wrap"><div style="width:{BADGE_W}px;height:{BADGE_H}px;background:#FFFFFF;
      border:6px solid {p['identity']};border-radius:{BADGE_H//2}px;text-align:center;padding:20px 0 0 0;
      box-shadow:0 14px 30px rgba(35,40,63,0.28);">
      <div style="font-size:66px;line-height:80px;font-weight:800;color:#23283D;
        direction:{rtl};">{html_escape(p['name']['native'])}</div>
      <div style="font-size:26px;line-height:36px;color:#6A6F82;margin-top:4px;
        letter-spacing:1px;font-weight:600;">{html_escape(p['name']['latin'])}</div>
    </div></div>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg,
                            font=f"{FONT_CSS[p['locale']]}, 'Microsoft YaHei', sans-serif",
                            dir="ltr", body=body)


def spill_html(locale, lang_label, bg="#FFFFFF"):
    """语言牌（plan §8.3）：标识色永远与国旗 emoji＋语种文字双通道冗余（§7.2-3）。"""
    body = f"""<div id="wrap"><div style="width:360px;height:84px;background:#FFFFFF;
      border:5px solid {UI_INK};border-radius:42px;text-align:center;line-height:76px;
      font-size:40px;font-weight:700;color:#23283D;box-shadow:0 8px 20px rgba(35,40,63,0.22);">
      {FLAG.get(locale, "")} {html_escape(lang_label)}</div></div>"""
    return HTML_HEAD.format(w=W, h=BAND_H, bg=bg,
                            font=f"{FONT_CSS[locale]}, 'Segoe UI Emoji', 'Microsoft YaHei', sans-serif",
                            dir="ltr", body=body)


def edge_viewport_h(TEXT_DIR):
    probe = TEXT_DIR / "_vp_probe.html"
    import re
    probe.write_text(HTML_HEAD.format(w=100, h=BAND_H, bg="#FFFFFF", font="sans-serif", dir="ltr",
                                      body="<div style='height:100vh'></div>"
                                           "<script>document.title=window.innerHeight;</script>"), "utf-8")
    dom = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--window-size=1080,300",
                          "--virtual-time-budget=800", "--dump-dom", probe.as_uri()],
                         check=True, capture_output=True, timeout=60).stdout.decode("utf-8", "ignore")
    m = re.search(r"<title>(\d+)</title>", dom)
    return int(m.group(1)) if m else BAND_H


def cmd_assets(only):
    personas, cards, scene = load_data()
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []                                  # (out_name, matte?, [(suffix, html), ...])

    def opaque(name, html):
        jobs.append((name, False, [("_s", html())]))

    def matte(name, html):
        jobs.append((name, True, [("_w", html("#FFFFFF")), ("_b", html("#000000"))]))

    for locale in locales_of(only):
        loc = scene["locales"][locale]
        rtl = is_rtl(locale)
        cast = casting(locale, personas, cards, scene)
        # 字牌 chip（`"文本"` 型）：井内贴 token 词的文字层，底色 = 该装置的空井色
        plaque_words = {e["key"]: e["word"] for e in (scene.get("tokenWords", {}).get(locale) or [])}
        well_bg = None
        dev = device_of(loc)
        if dev:
            well_bg = (dev.get("well") or "") if str(dev.get("well") or "").startswith("#") else None
        for key, chip in scene["tokens"].items():
            if chip_color(chip) is None and plaque_words.get(key):
                opaque(f"tok_{PREFIX}_{locale}_{key}",
                       lambda w=plaque_words[key], lc=locale, r=rtl:
                       token_plaque_html(w, lc, r, well_bg or "#EDE9E0"))
        for ln in loc["dialogue"]:
            opaque(f"band_{PREFIX}_{locale}_{ln['i']}_base",
                   lambda t=ln["text"], g=ln.get("gloss"), n=ln.get("note"), lc=locale, r=rtl:
                   band_text_html(t, g, n, lc, r, "#D6DCEE"))
            opaque(f"band_{PREFIX}_{locale}_{ln['i']}_hl",
                   lambda t=ln["text"], g=ln.get("gloss"), n=ln.get("note"), lc=locale, r=rtl,
                   h=hl_hex(ln["tokenChip"]):
                   band_text_html(t, g, n, lc, r, h))
            if ln["bubble"]:
                matte(f"bub_{PREFIX}_{locale}_{ln['i']}",
                      lambda bg, b=ln["bubble"], tok=ln["tokenChip"], lc=locale, r=rtl:
                      bubble_text_html(b["text"], tok if chip_color(tok) else None, lc, r, bg))
        for role in ("A", "B"):
            matte(f"badge_{cast[role]}", lambda bg, p=personas[cast[role]]: sbadge_html(p, bg))
        matte(f"pill_{PREFIX}_{locale}",
              lambda bg, lc=locale, lb=loc["langLabel"]: spill_html(lc, lb, bg))

    chrome_px = BAND_H - edge_viewport_h(TEXT_DIR)          # 坑⑩：Edge 视口 ≠ window-size
    win_h = BAND_H + max(0, chrome_px)
    print(f"[assets] Edge viewport deficit: {chrome_px}px -> window-size=1080,{win_h}")

    def run(job):
        name, is_matte, shots = job
        pngs = []
        for suffix, html in shots:
            tmp = TEXT_DIR / f"{name}{suffix}.html"
            tmp.write_text(html, "utf-8")
            png = TEXT_DIR / f"{name}{suffix}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1", f"--window-size=1080,{win_h}",
                            f"--screenshot={png}", "--virtual-time-budget=1500", tmp.as_uri()],
                           check=True, capture_output=True, timeout=120)
            if not png.exists():
                raise RuntimeError(f"edge shot failed: {name}{suffix}")
            pngs.append(png)
        out = TEXT_DIR / f"{name}.png"
        if is_matte:
            matte_combine(pngs[0], pngs[1], out)             # 双 matte 抠像（半透明投影可还原）
        else:
            os.replace(pngs[0], out)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(run, jobs))
    print(f"[assets] done: {len(jobs)} assets -> {TEXT_DIR}")


# ---------- 色卡装置（每语种独立装置，§1.2 原则4；色卡填充逐帧，六色边问边亮）----------

def device_cells(device):
    """装置井位：井宽/井高/井形全部取自剧本 §0.2 装置规格表（场景是数据不是代码）。"""
    if not device:
        return []
    cw = float(device.get("cellW") or 112)
    ch = float(device.get("cellH") or 112)
    shape = device.get("shape") or "round"
    n = len(SCENE_TOKENS) or 6
    step = DEV_SPAN / n
    cells = []
    for i in range(n):
        cx = DEV_X0 + step * (i + 0.5)
        cells.append((round(cx - cw / 2, 1), round(DEV_CY - ch / 2, 1),
                      round(cx + cw / 2, 1), round(DEV_CY + ch / 2, 1), shape))
    return cells


def scene_pal(ident_a, ident_b):
    """场景中性色：与 prerender_bg 同族的 pal 约定（ink 为道具描边唯一色——不变量⑤）。"""
    ident = mix(ident_a, ident_b, 0.5)
    return {
        "ink": (150, 144, 134),
        "soft": mix((214, 208, 196), ident, 0.20),
        "soft2": mix((190, 183, 170), ident, 0.30),
        "tint": mix((255, 255, 255), ident, 0.30),
        "tint2": mix((255, 255, 255), ident, 0.16),
        "accent": ident,
        "paper": (245, 241, 232),
    }


def draw_device(d, device, cells, pal):
    """装置外框（井内 token 由逐帧填充层画）：style 决定外框画法，井位/井形/空井色来自
    剧本 §0.2。§1.2 原则4「舞台原生」：每语种独立装置，不共用布景。"""
    kind = (device or {}).get("style") or "tray"
    if kind not in DEVICE_STYLES:
        raise ValueError(f"未知装置 style：{kind}（可用 {DEVICE_STYLES}）")
    ink, soft, soft2, tint = pal["ink"], pal["soft"], pal["soft2"], pal["tint"]
    x0 = min(c[0] for c in cells) - 26
    x1 = max(c[2] for c in cells) + 26
    y0 = min(c[1] for c in cells) - 26
    y1 = max(c[3] for c in cells) + 26

    if kind == "palette":                                   # 美术教室·调色盘
        d.rounded_rectangle([x0, y0, x1, y1], 40, fill=soft2, outline=ink, width=5)
    elif kind == "chalkboard":                              # 咖啡馆·小黑板
        d.rounded_rectangle([x0, y0 - 6, x1, y1 + 10], 18, fill=(58, 66, 62), outline=ink, width=6)
        d.rectangle([x0 - 10, y1 + 10, x1 + 10, y1 + 30], fill=(146, 116, 82), outline=ink, width=4)
    elif kind == "bookspine":                               # 书店·橱窗书脊
        d.rectangle([x0, y0 - 10, x1, y0 + 14], fill=(132, 100, 72), outline=ink, width=4)
        d.rectangle([x0 - 8, y1, x1 + 8, y1 + 22], fill=(132, 100, 72), outline=ink, width=4)
    elif kind == "signpost":                                # 徒步·指路牌柱
        d.rectangle([(x0 + x1) / 2 - 16, y0, (x0 + x1) / 2 + 16, y1 + 54], fill=(140, 115, 90),
                    outline=ink, width=4)
    elif kind == "fruit_basket":                            # 果摊·果筐
        for c in cells:
            d.polygon([(c[0] - 4, c[1] + 6), (c[2] + 4, c[1] + 6), (c[2] - 6, c[3] + 16),
                       (c[0] + 6, c[3] + 16)], fill=(178, 138, 92), outline=ink, width=4)
    elif kind == "chalk_stone":                             # 庭院·石板粉笔
        d.rectangle([x0 - 40, y1 + 4, x1 + 40, y1 + 30], fill=soft2, outline=ink, width=4)
    elif kind == "doorframe":                               # 港口·漆色门框
        d.rectangle([x0 - 16, y0 - 14, x1 + 16, y1 + 12], fill=soft2, outline=ink, width=5)
    elif kind == "lanterns":                                # 咖啡座·灯笼
        d.line([(x0, y0 - 30), (x1, y0 - 30)], width=6, fill=ink)
        for c in cells:
            d.line([((c[0] + c[2]) / 2, y0 - 30), ((c[0] + c[2]) / 2, c[1] - 2)], width=3, fill=ink)
    elif kind == "rangoli":                                 # 走廊·rangoli
        for c in cells:
            for k in range(8):
                a = k * math.pi / 4
                d.line([((c[0] + c[2]) / 2 + 16 * math.cos(a), (c[1] + c[3]) / 2 + 16 * math.sin(a)),
                        ((c[0] + c[2]) / 2 + 30 * math.cos(a), (c[1] + c[3]) / 2 + 30 * math.sin(a))],
                       width=4, fill=soft2)
    elif kind == "traffic_lamp":                            # 商店街·街灯
        d.rectangle([x0 - 20, y1 + 6, x1 + 20, y1 + 22], fill=soft2, outline=ink, width=4)
        for c in cells:
            d.line([((c[0] + c[2]) / 2, c[3]), ((c[0] + c[2]) / 2, y1 + 8)], width=6, fill=ink)
    elif kind == "cone":                                    # 街球场·训练锥
        d.rectangle([x0 - 30, y1 + 2, x1 + 30, y1 + 20], fill=soft, outline=ink, width=4)
    elif kind == "gelato":                                  # 广场·gelato 柜
        d.rounded_rectangle([x0 - 30, y0 - 6, x1 + 30, y1 + 26], 22, fill=pal["paper"],
                            outline=ink, width=5)
        d.line([(x0 - 20, y0 + 6), (x1 + 20, y0 + 6)], width=5, fill=soft2)
    elif kind == "dyed_cloth":                              # 天台·晾绳染布
        d.line([(x0 - 60, y0 - 24), (x1 + 60, y0 - 24)], width=6, fill=ink)
    elif kind == "neon":                                    # 街市·neon 招牌
        d.rectangle([x0 - 24, y1 + 2, x1 + 24, y1 + 24], fill=(64, 58, 66), outline=ink, width=4)

    # 空井：先铺底色，逐帧 token 填充压在其上——白/浅色 chip 才有对比
    well = well_color(device, pal)
    for c in cells:
        if c[4] == "circle":
            d.ellipse(list(c[:4]), fill=well)
        elif c[4] == "poly":
            d.polygon([((c[0] + c[2]) / 2, c[1]), (c[0], c[3]), (c[2], c[3])], fill=well)
        elif c[4] == "rect":
            d.rectangle(list(c[:4]), fill=well)
        else:
            d.rounded_rectangle(list(c[:4]), 18, fill=well)
    return (x0, y0, x1, y1)


def fill_cell(d, cell, color, scale=1.0):
    """井内填充：色片 chip 实心（描边由 ring_cell 单独用 pal['ink'] 画——不变量⑤）。"""
    x0, y0, x1, y1, shape = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if scale != 1.0:
        hw, hh = (x1 - x0) / 2 * scale, (y1 - y0) / 2 * scale
        x0, y0, x1, y1 = cx - hw, cy - hh, cx + hw, cy + hh
    if shape == "circle":
        d.ellipse([x0, y0, x1, y1], fill=color)
    elif shape == "poly":
        d.polygon([(cx, y0), (x0, y1), (x1, y1)], fill=color)
    elif shape == "rect":
        d.rectangle([x0, y0, x1, y1], fill=color)
    else:
        d.rounded_rectangle([x0, y0, x1, y1], 18, fill=color)


def cell_box(cell, scale=1.0):
    """井的 1x 包围盒（缩放后）——字牌 chip 贴图按此居中。"""
    x0, y0, x1, y1 = cell[:4]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2 * scale, (y1 - y0) / 2 * scale
    return cx - hw, cy - hh, cx + hw, cy + hh


def ring_cell(d, cell, ink, w=6):
    x0, y0, x1, y1, shape = cell
    if shape == "circle":
        d.ellipse([x0 - 6, y0 - 6, x1 + 6, y1 + 6], outline=ink, width=w)
    elif shape == "poly":
        d.polygon([((x0 + x1) / 2, y0 - 6), (x0 - 6, y1 + 6), (x1 + 6, y1 + 6)], outline=ink, width=w)
    else:
        d.rounded_rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], 20, outline=ink, width=w)


# ---------- 渲染阶段 ----------

def cast_colors(p):
    """该人物可上镜的取样色（发/上衣/下装），qa_scene 立绘↔背景探针同用。
    近白的低饱和服装与米色底天然混淆、探针会误命中背景，剔除；一个都没有则退回发色。"""
    def usable(hexs):
        r, g, b = hexc(hexs)
        return (max(r, g, b) - min(r, g, b)) > 34 or (r + g + b) / 3 < 150
    keys = ("hair", "outfitTop", "outfitBottom")
    cols = [hexc(p["palette"][k]) for k in keys if usable(p["palette"][k])]
    return cols or [hexc(p["palette"]["hair"])]


def prerender_scene_bg(loc, ident_a, ident_b, cast_cols=()):
    from PIL import Image, ImageDraw
    import numpy as np
    ident = mix(ident_a, ident_b, 0.5)
    top, bottom = mix((246, 243, 238), ident, 0.10), mix((236, 232, 224), ident, 0.20)

    def smoothstep(v):
        v = min(1.0, max(0.0, v))
        return v * v * (3 - 2 * v)

    # 舞台背板带：人物站位区的渐变底整体压暗 ~26%（上下缘 smoothstep 软过渡）。
    # 米色/奶白上装、浅肤色 vs 米色渐变实测只差 11-19，不压暗必靠色（需求③）。
    band_dark = mix((64, 56, 48), ident, 0.12)

    def band_alpha(y):
        return smoothstep((y - 760) / 130) * (1 - smoothstep((y - 1620) / 100))

    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):
        a = 0.26 * band_alpha(y)
        arr[y, :, :] = mix(mix(top, bottom, y / (H - 1)), band_dark, a)
    img = Image.fromarray(arr).resize((W * SS, H * SS), Image.BILINEAR)
    d = DrawScaled(ImageDraw.Draw(img), SS)
    ground = mix((230, 226, 216), ident, .18)
    d.rectangle([0, 1700, W, H], fill=ground)
    pal = scene_pal(ident_a, ident_b)
    for name in (loc.get("prop") or {}).get("scenes") or []:   # 复用 intro_cards 的场景原语
        fn = SCENES.get(name)
        if fn:
            fn(d, pal)
    for cx in (AX, BX):                                     # 双人站位阴影
        d.ellipse([cx - 150, 1680, cx + 150, 1742], fill=mix(ground, (50, 45, 40), 0.16))
    # 原语靠色规避（需求③）：压暗整幅合成会把中间调原语推到服装色上（de-DE 压暗后的
    # trail 与 Felix 卡其裤实测 4.1），故背板带只压渐变，原语改走「推开」——人物区背景中
    # 距任一方取样色 <96 的像素，若在「band_dark 一侧」的投影 <48，则沿该方向补足到 48
    # （投影 ≥48 ⇒ 欧氏距离 ≥48；LANCZOS 负瓣与阴影缘的 AA 混色最多回落 ~11，仍 ≥36 探针线）。推成半空间性质而非双向推开：LANCZOS 降采样是线性的，
    # 双向推开会把两侧像素的平均值拉回取样色上（he-IL 衣夹线两侧像素实测 15.0）；
    # 后画的站位阴影同理会与被推开的原语平均回服装色（de-DE 阴影缘实测 13.4）——
    # 故阴影先画、推开最后跑，让带内全部像素共处同一半空间，平均（降采样）后性质不丢；
    # 推移量在阈值处收敛为 0，无接缝。装置是教学 UI，画在推开之后不动（qa_scene §4 有对比探针）。
    if cast_cols:
        K, R = 48.0, 96.0
        y0, y1 = 760 * SS, min(1800 * SS, H * SS)
        a2 = np.asarray(img).astype(np.float32)
        sub = a2[y0:y1]
        dark = np.array(band_dark, np.float32)
        ys = np.arange(y0, y1, dtype=np.float32) / SS
        fy = np.array([smoothstep((v - 760) / 130) * (1 - smoothstep((v - 1700) / 100))
                       for v in ys], np.float32)
        fade = np.repeat(fy[:, None], sub.shape[1], axis=1)
        act = fade > 0.02
        for _ in range(3):
            moved = False
            for c in cast_cols:
                cv = np.array(c, np.float32)
                dv = dark - cv
                dn = float(np.sqrt((dv ** 2).sum()))
                dirv = dv / dn if dn > 1.0 else np.array([0.577, 0.577, 0.577], np.float32)
                near = np.sqrt(((sub - cv) ** 2).sum(-1)) < R
                proj = ((sub - cv) * dirv).sum(-1)
                need = act & near & (proj < K)
                if need.any():
                    sub += need[..., None] * ((K - proj) * fade)[..., None] * dirv
                    moved = True
            if not moved:
                break
        np.clip(sub, 0, 255, out=sub)
        a2[y0:y1] = sub
        img = Image.fromarray(a2.astype(np.uint8))
        d = DrawScaled(ImageDraw.Draw(img), SS)
    device = device_of(loc)
    cells = device_cells(device)                            # 井位/井形来自剧本 §0.2
    if cells:
        draw_device(d, device, cells, pal)                  # 装置外框（井内 token 逐帧填）
    return img.resize((W, H), Image.LANCZOS), cells


def persona_pose(p, slot):
    """排他动作：剧本标注的是**语义槽位**（point/nod/wave…，全语种共享骨架），
    实现走 persona.moves 逐人专属姿态码（personas.json 数据槽）——同台 A/B 词汇表
    互不相交（活泼/沉稳两个能量池全局不交叉），同一人跨课动作一致。槽位缺映射 → 回退槽位本身。"""
    code = (p.get("moves") or {}).get(slot, slot)
    if code not in POSE_CODES:
        raise ValueError(f"{p['id']} moves.{slot}={code!r} 不在 POSE_CODES")
    return code


def karaoke_points(line):
    """[(t, frac)] 词首/词尾字符进度点（与亮相卡同一实现，词级时间戳一轴三用之卡拉OK轴）。"""
    words = line["words"]
    total = sum(len(w["w"]) for w in words) + max(0, len(words) - 1)
    pts, c = [(line["start"], 0.0)], 0.0
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
            return f1 if t1 <= t0 else f0 + (f1 - f0) * (t - t0) / (t1 - t0)
    return 1.0


def render_scene(locale, scene_id=None):
    from PIL import Image, ImageDraw
    if scene_id:  # Windows spawn：Pool 子进程重新 import 本模块，CLI 绑定的场景回退缺省——显式传参
        global SCENE_ID, PREFIX
        SCENE_ID = scene_id
        PREFIX = f"scene-{scene_id}"
    personas, cards, scene = load_data()
    loc = scene["locales"][locale]
    tl = json.loads((AUDIO_DIR / f"{PREFIX}_{locale}.timeline.json").read_text("utf-8"))
    lines, rtl = tl["lines"], tl["rtl"]
    dur, speech_end, entry = tl["duration"], tl["speechEnd"], tl["entry"]
    frames = int(round(FPS * dur))
    pa, pb = personas[tl["cast"]["A"]], personas[tl["cast"]["B"]]
    by_role = {"A": pa, "B": pb}
    ident_a, ident_b = hexc(pa["identity"]), hexc(pb["identity"])

    bg, cells = prerender_scene_bg(loc, ident_a, ident_b, cast_colors(pa) + cast_colors(pb))
    tokens = dict(scene["tokens"])
    order = scene["tokenOrder"]

    def band_png(p):
        # 坑⑩ 补偿使 Edge 截图比 BAND_H 高一截（视口差），带底以下的那截深色不得贴进成片
        return Image.open(p).convert("RGB").crop((0, 0, W, BAND_H))

    bands = [(band_png(TEXT_DIR / f"band_{PREFIX}_{locale}_{lo['i']}_base.png"),
              band_png(TEXT_DIR / f"band_{PREFIX}_{locale}_{lo['i']}_hl.png"),
              karaoke_points(lo)) for lo in lines]
    badges = {r: Image.open(TEXT_DIR / f"badge_{tl['cast'][r]}.png").convert("RGBA")
              for r in ("A", "B")}

    def tight(im):
        a = im.getchannel("A").point(lambda v: 255 if v > 8 else 0)
        box = a.getbbox()
        return im.crop(box) if box else im

    badges = {r: tight(b) for r, b in badges.items()}
    pill = tight(Image.open(TEXT_DIR / f"pill_{PREFIX}_{locale}.png").convert("RGBA"))
    bubbles = {lo["i"]: tight(Image.open(TEXT_DIR / f"bub_{PREFIX}_{locale}_{lo['i']}.png").convert("RGBA"))
               for lo in lines if lo["bubble"]}
    # 字牌 chip（`"文本"` 型）：token 词由 Edge 渲成文字层，按井位贴入
    plaques = {}
    for key in order:
        p = TEXT_DIR / f"tok_{PREFIX}_{locale}_{key}.png"
        if chip_color(tokens.get(key)) is None and p.exists():
            plaques[key] = Image.open(p).convert("RGBA")

    out_path = ROOT / f"{PREFIX}_{locale}.mp4"
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(AUDIO_DIR / f"{PREFIX}_{locale}.m4a"),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-shortest", "-t", str(dur), "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    ink = scene_pal(ident_a, ident_b)["ink"]
    prev_li, band_prev, band_prev_until = None, None, -1.0
    lines_by_role = {r: [lo for lo in lines if lo["speaker"] == r] for r in ("A", "B")}

    for f in range(frames):
        t = f / FPS
        layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        lds = DrawScaled(ld, SS)

        # 当前行 + 卡拉OK高亮（行间交叉淡化）
        li = 0
        for i, lo in enumerate(lines):
            if t >= lo["start"] - 0.18:
                li = i
        if prev_li is not None and prev_li != li:
            band_prev, band_prev_until = bands[prev_li][1], t + 0.22
        prev_li = li
        cur = lines[li]
        band = bands[li][0].copy()
        frac = frac_at(bands[li][2], t)
        if frac > 0.01:
            bw = int(W * frac)
            if rtl:
                band.paste(bands[li][1].crop((W - bw, 0, W, BAND_H)), (W - bw, 0))
            else:
                band.paste(bands[li][1].crop((0, 0, bw, BAND_H)), (0, 0))
        if band_prev is not None and t < band_prev_until:
            band = Image.blend(band, band_prev, min(1.0, (band_prev_until - t) / 0.22))

        # 进度条（RTL 右起）
        lds.rounded_rectangle(list(PROG), 8, fill=mix((255, 255, 255), ident_a, 0.25))
        fw = PROG[0] + (PROG[2] - PROG[0]) * (t / dur)
        if rtl:
            lds.rounded_rectangle([PROG[2] - (fw - PROG[0]), PROG[1], PROG[2], PROG[3]], 8, fill=ident_a)
        else:
            lds.rounded_rectangle([PROG[0], PROG[1], fw, PROG[3]], 8, fill=ident_a)

        # 装置逐帧填充：已问过的 token 点亮；当前 token 弹起 + 呼吸描边（边问边亮）
        asked = {a["key"] for a in tl["ask"] if t >= a["t"]}
        for key, cell in zip(order, cells):
            if key not in asked:
                ring_cell(lds, cell, ink, 4)
                continue
            since = next((t - a["t"] for a in tl["ask"] if a["key"] == key), 9.9)
            sc = 1.0 + 0.16 * (1 - pop_scale(since, 0.0, 0.5, True)) if since < 0.5 else 1.0
            rgb = chip_color(tokens.get(key))
            if rgb:
                fill_cell(lds, cell, rgb, sc)
            elif key in plaques:                              # 字牌 chip：贴 token 词文字层
                bx0, by0, bx1, by1 = cell_box(cell, sc)
                pl = plaques[key]
                k = min((bx1 - bx0) / pl.width, (by1 - by0) / pl.height, 1.0)
                pw, ph = max(1, int(pl.width * k)), max(1, int(pl.height * k))
                if (pw, ph) != pl.size:
                    pl = pl.resize((pw, ph), Image.Resampling.LANCZOS)
                layer.alpha_composite(pl, (int((bx0 + bx1) / 2 - pw / 2),
                                           int((by0 + by1) / 2 - ph / 2)))
            ring_cell(lds, cell, ink, 4)
            if key == cur["tokenKey"] and cur["tokenKey"]:
                ccx, ccy = (cell[0] + cell[2]) / 2, (cell[1] + cell[3]) / 2
                k = 1.0 + 0.022 * math.sin(2 * math.pi * 2.2 * t)   # 呼吸描边
                hw, hh = (cell[2] - cell[0]) / 2 * k + 5, (cell[3] - cell[1]) / 2 * k + 5
                lds.rounded_rectangle([ccx - hw, ccy - hh, ccx + hw, ccy + hh], 24,
                                      outline=ink, width=4)

        # 双人立绘：站位/口型/表情/手势/入场/出画，全部由词级时间戳与情绪驱动
        onstage = {}
        for role in ("A", "B"):
            p = by_role[role]
            own = lines_by_role[role]
            lo = cur if cur["speaker"] == role else None
            base_x = side_x(locale, role) - 540
            xoff, yoff, sc, squash = base_x, 0.0, CHAR_SCALE, 0.0
            if t < entry:                                    # 入场：活泼方弹入，沉稳方侧移入
                if p["energy"] == "lively":
                    sc *= max(0.02, pop_scale(t, 0.0, entry * 0.6, True, damp=p["movement"]["bounce"]))
                else:
                    u = min(1.0, t / entry)
                    xoff += (300 if not rtl else -300) * (1 - ease_out_cubic(u))
            pose = {}
            if lo and lo["pose"] and lo["poseT"] <= t < lo["poseT"] + POSE_DUR:
                pose.update(pose_for(persona_pose(p, lo["pose"]), (t - lo["poseT"]) / POSE_DUR, t, p))
            elif lo and lo["exits"] and speech_end <= t < speech_end + TAIL - 0.4:
                pose.update(pose_for(persona_pose(p, "wave"), (t - speech_end) / (TAIL - 0.4), t, p))
            op = openness_at(own, t, p["id"]) if lo else 0.0
            if t < entry or t >= speech_end + 0.05:
                op = 0.0
            if not pose and op > 0.05:                       # 说话时轻摆
                pose.setdefault("armR", (16 - 5 * math.sin(2 * math.pi * t * 0.9), 12, "open"))
            yoff += pose.pop("yoff", 0)
            xoff += pose.pop("xoff", 0)
            if lo and lo["exits"] and t >= speech_end:       # 出画
                u = clamp((t - speech_end) / max(0.4, TAIL - 0.4), 0, 1)
                xoff += (1500 if not rtl else -1500) * ease_out_cubic(u)
            squash = pose.pop("squash", 0) + p["movement"]["breathAmp"] * (
                0.5 - 0.5 * math.cos(2 * math.pi * t * 0.42))
            if p["energy"] == "lively":
                kb = clamp(14.0 / p["movement"]["bounce"], 0.75, 1.6)
                yoff += -4 * kb * abs(math.sin(2 * math.pi * t * 0.85))
            else:
                yoff += -3 * abs(math.sin(2 * math.pi * t * 0.6))
            n = int(t / p["movement"]["blinkCycleSec"])
            ph = (t / p["movement"]["blinkCycleSec"]) - n
            blink = (0.15 + 0.65 * rnd(f"{p['id']}:blink:{n}")) <= ph <= (
                0.15 + 0.65 * rnd(f"{p['id']}:blink:{n}")) + 0.05
            ctx = dict(scale=sc, xoff=xoff, yoff=yoff, squash=squash,
                       xscale=pose.pop("xscale", 1.0),
                       head_dx=pose.pop("head_dx", 0), head_dy=pose.pop("head_dy", 0),
                       brow_lift_extra=pose.pop("brow_lift_extra", 0), pose=pose,
                       openness=op, blink=blink, mood=(lo["mood"] if lo else "neutral"), ss=SS)
            draw_character(layer, ld, p, t, ctx)
            onstage[role] = abs(xoff - base_x) < 400      # 出画后名牌随之退场

        # 气泡尾（A/B 交替镜像，画进 2x 层抗锯齿）
        bub = bubbles.get(cur["i"])
        if bub:
            bxc = side_x(locale, cur["speaker"])
            bub_t = cur["start"] - 0.05
            if t >= bub_t and pop_scale(t, bub_t, 0.45, True) > 0.98:
                by0 = BUBBLE_CY - bub.height // 2
                yb = by0 + bub.height - 2
                inner = (1 if (cur["i"] % 2 == 0) else -1) * (-1 if rtl else 1)  # A/B 交替镜像
                xa = bxc + int(bub.width * 0.18 * inner)
                p0, p1, p2 = (xa - 26, yb - 36), (xa + 26, yb - 36), (xa + 10 * inner, yb + 4)
                lds.polygon([p0, p1, p2], fill=(255, 255, 255))
                lds.line([p0, p2], fill=hexc(UI_INK), width=5)
                lds.line([p1, p2], fill=hexc(UI_INK), width=5)

        layer = layer.resize((W, H), Image.Resampling.BOX)
        img = bg.copy()
        img.paste(layer, (0, 0), layer)
        img.paste(band, (0, BAND_Y))

        for role in ("A", "B"):                              # 名牌（0.6s 弹出，镜像站位）
            bs = pop_scale(t, 0.6, 0.55, True) if onstage[role] else 0.0
            if bs > 0.02:
                b = badges[role]
                if bs < 0.995:
                    b = b.resize((max(2, int(b.width * bs)), max(2, int(b.height * bs))),
                                 Image.Resampling.LANCZOS)
                img.paste(b, (side_x(locale, role) - b.width // 2,
                              BADGE_Y + (BADGE_H - b.height) // 2), b)
        if t >= entry - 0.3:                                # 语言牌（plan §8.3）
            ps = pop_scale(t, entry - 0.3, 0.4, True)
            if ps > 0.02:
                pl = pill
                if ps < 0.995:
                    pl = pill.resize((max(2, int(pill.width * ps)), max(2, int(pill.height * ps))),
                                     Image.Resampling.LANCZOS)
                img.paste(pl, (540 - pl.width // 2, PILL_Y + (PILL_H - pl.height) // 2), pl)
        if bub and t >= cur["start"] - 0.05:
            us = pop_scale(t, cur["start"] - 0.05, 0.45, True)
            if us > 0.02:
                bb = bub
                if us < 0.995:
                    bb = bub.resize((max(2, int(bub.width * us)), max(2, int(bub.height * us))),
                                    Image.Resampling.LANCZOS)
                img.paste(bb, (side_x(locale, cur["speaker"]) - bb.width // 2,
                               BUBBLE_CY - bb.height // 2), bb)

        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()
    print(f"[render] {locale} -> {out_path.name} frames={frames} dur={dur:.2f}s rc={proc.returncode}")


def cmd_render(only, workers):
    ids = locales_of(only)
    ROOT.mkdir(parents=True, exist_ok=True)
    with Pool(min(workers, len(ids))) as pool:
        pool.starmap(render_scene, [(lc, SCENE_ID) for lc in ids])


def cmd_list():
    _, _, scene = load_data()
    print(f"场景 {scene['id']}：{scene['title']}（{scene['source']}）")
    print(f"token（出场序）：{' > '.join(scene.get('tokenOrder') or []) or '无'}"
          f"   RTL：{', '.join(scene.get('rtlLocales') or []) or '无'}")
    print(f"{'locale':8} {'lines':>5} {'duration':>8}  A / B  · 装置")
    for locale, loc in scene["locales"].items():
        tlp = AUDIO_DIR / f"{PREFIX}_{locale}.timeline.json"
        d = f"{json.loads(tlp.read_text('utf-8'))['duration']:.1f}s" if tlp.exists() else "-"
        dev = device_of(loc)
        prop = f"{loc['prop']['label']}（{dev['style']}/{dev['shape']}）" if dev else "纯对话"
        print(f"{locale:8} {len(loc['dialogue']):>5} {d:>8}  "
              f"{loc['aName']} / {loc['bName']}  · {prop}")


def main():
    global SCENE_ID, PREFIX
    ap = argparse.ArgumentParser(description="教学场景 A/B 对话场景渲染（M2）")
    ap.add_argument("phase", choices=["tts", "assets", "render", "all", "list"])
    ap.add_argument("--scene", default=SCENE_ID,
                    help="场景 id（对应 lessons/<id>/scene.md / scene.json，缺省 colors）")
    ap.add_argument("--only", default="", help="逗号分隔的 locale 列表，如 zh-CN,ja-JP")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    SCENE_ID = args.scene
    PREFIX = f"scene-{SCENE_ID}"
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if args.phase == "list":
        cmd_list()
    elif args.phase == "tts":
        cmd_tts(only)
    elif args.phase == "assets":
        cmd_assets(only)
    elif args.phase == "render":
        cmd_render(only, args.workers)
    else:
        cmd_tts(only)
        cmd_assets(only)
        cmd_render(only, args.workers)


if __name__ == "__main__":
    main()
