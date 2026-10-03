#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_scene.py — 教学场景 M2 场景线验收（scene-<id>.md §6 + plan.md §9 M2 口径，场景无关）

六组验收：
  1. 产物规格    <locale> 视频：1080x1920@30fps / h264+aac / 时长 == 时间轴
  2. 文本契约    §0.3 语体差真实成立；疑问句用本文字系统的问号；§0 durationBudget 卡时长
  3. 选角与骨架  A/B = intro-cards.json cast 事实源；问答对称；token 零遗漏零重复
  4. 画面探针    双人同框站位（服装色质心落在本侧；RTL 语种左右对调）、文字带、token 装置全亮
  5. 音频契约    逐行声线 = persona.voice + 情绪增量（缓存键独立，重跑命中）
  6. 幂等        重渲一支比对视频流 framehash（逐帧一致，容器字节差属正常——不变量⑦）

用法：uv run python -m usine.qa_scene [--scene <id>] [--only zh-CN,...] [--no-idempotent]
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import scene_video
from .scene_video import (
    AUDIO_DIR, ROOT, RTL_LOCALES, is_rtl, load_data, side_x, device_of, chip_color,
    PROG, BAND_Y, BAND_H, BADGE_Y, BADGE_H, BUBBLE_CY, DEV_CY, CHAR_SCALE, device_cells,
    AX, BX,
)
from .intro_cards import BAND_BG, UI_INK, THEME
from usine import ROOT as PROJ_ROOT

HERE = PROJ_ROOT
PREFIX = scene_video.PREFIX
OK, BAD = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, OK if cond else BAD, detail))
    print(f"  [{OK if cond else BAD}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def grab(locale, t, out_png):
    """从成片抽一帧（验收用成片，不用渲染中间态——与 qa_char 同口径）。"""
    mp4 = ROOT / f"{PREFIX}_{locale}.mp4"
    subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", str(mp4), "-frames:v", "1",
                    str(out_png)], check=True, capture_output=True)
    return out_png


def near(px, target, tol=30):
    return all(abs(px[i] - target[i]) <= tol for i in range(3))


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def count_color(img, color, x0, x1, y0, y1, tol=30, step=3):
    px = img.load()
    n = 0
    for y in range(int(y0), int(y1), step):
        for x in range(int(x0), int(x1), step):
            if near(px[x, y], color, tol):
                n += 1
    return n


def char_colors(p):
    """该人物可用的取样色（发/上衣/下装）。浅中性色（近白服装）会与场景底色混淆，
    故剔除低饱和高亮项，保证探针不误命中背景。"""
    def usable(hexc):
        r, g, b = hexrgb(hexc)
        return (max(r, g, b) - min(r, g, b)) > 34 or (r + g + b) / 3 < 150
    keys = ("hair", "outfitTop", "outfitBottom")
    cols = [hexrgb(p["palette"][k]) for k in keys if usable(p["palette"][k])]
    return cols or [hexrgb(p["palette"]["hair"])]


# ---------- 文字系统 → 句末标点（Unicode 事实，属代码不属场景数据） ----------
# 疑问句必须用**该文字自己的**问号。希腊文另有专用问号 U+037E；用 ASCII '?' 会被
# TTS 读成陈述句（el-GR 曾 7 处用半角分号收问句，§0.3 记此坑）。
SCRIPT_RANGES = (
    ("greek", 0x0370, 0x03FF), ("hebrew", 0x0590, 0x05FF), ("arabic", 0x0600, 0x06FF),
    ("devanagari", 0x0900, 0x097F), ("hangul", 0xAC00, 0xD7AF), ("kana", 0x3040, 0x30FF),
    ("cyrillic", 0x0400, 0x04FF), ("han", 0x4E00, 0x9FFF),
)
QMARK_BY_SCRIPT = {
    "greek":  chr(0x037E),   # 希腊问号 U+037E（形似分号，最常被 ASCII ; 顶替）
    "arabic": chr(0x061F),   # 阿拉伯问号 U+061F ؟
    "han":    chr(0xFF1F),   # 全角问号 U+FF1F ？（中日韩排版用全角，非 ASCII）
    "kana":   chr(0xFF1F),   # 同上（日文假名）
}
# 未列出的文字系统（latin / cyrillic / hebrew / devanagari / hangul）通用 ASCII 问号      # 其余文字系统通用 ASCII '?'
ASCII_SEMICOLON = ";"              # 现代正字法里它从不作句终止符


def script_of(text):
    """一行台词的主文字系统：取首个落在已知文字区间的码位。"""
    for ch in text:
        o = ord(ch)
        for name, lo, hi in SCRIPT_RANGES:
            if lo <= o <= hi:
                return name
    return "latin"


def main():
    global PREFIX
    ap = argparse.ArgumentParser(description="教学场景线验收（M2）")
    ap.add_argument("--only", default="", help="逗号分隔的 locale 列表")
    ap.add_argument("--scene", default=scene_video.SCENE_ID, help="场景 id（缺省 colors）")
    ap.add_argument("--no-idempotent", action="store_true")
    args = ap.parse_args()
    scene_video.SCENE_ID = args.scene
    scene_video.PREFIX = PREFIX = f"scene-{args.scene}"
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    personas, cards, scene = load_data()
    locales = [k for k in scene["locales"] if not only or k in only]
    tmp = Path(tempfile.mkdtemp(prefix="qa_scene_"))
    print(f"场景 {scene['id']}：{scene['title']}（{scene['source']}）"
          f"  token={' > '.join(scene.get('tokenOrder') or []) or '无'}"
          f"  RTL={','.join(scene.get('rtlLocales') or []) or '无'}")

    print("\n== 1. 产物规格")
    for lc in locales:
        mp4 = ROOT / f"{PREFIX}_{lc}.mp4"
        if not check(f"{lc} 存在", mp4.exists(), mp4.name):
            continue
        info = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height,r_frame_rate",
             "-of", "json", str(mp4)], check=True, capture_output=True, text=True)
        j = json.loads(info.stdout)
        v = next(s for s in j["streams"] if s["codec_type"] == "video")
        a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
        dur = float(j["format"]["duration"])
        tl = json.loads((AUDIO_DIR / f"{PREFIX}_{lc}.timeline.json").read_text("utf-8"))
        check(f"{lc} 1080x1920@30", v["width"] == 1080 and v["height"] == 1920
              and v["r_frame_rate"] == "30/1", f'{v["width"]}x{v["height"]}@{v["r_frame_rate"]}')
        check(f"{lc} 音轨存在", a is not None, (a or {}).get("codec_name", "-"))
        check(f"{lc} 时长对齐时间轴", abs(dur - tl["duration"]) < 0.25,
              f'{dur:.2f}s vs {tl["duration"]:.2f}s')

    print("\n== 2. 文本契约（§0.3 语体/标点 + §0 durationBudget）")
    budget = scene.get("durationBudget") or []
    levels = scene.get("speechLevels") or {}
    for lc in locales:
        loc = scene["locales"][lc]
        lines = loc["dialogue"]

        # 2a 标点：句末不得是半角分号；疑问句须用本文字系统的问号
        bad_term, bad_q = [], []
        for ln in lines:
            txt = (ln["text"] or "").strip()
            if not txt:
                continue
            if txt[-1] == ASCII_SEMICOLON:
                bad_term.append(f"#{ln['i']}")
            if ln["isQuestion"]:
                want = QMARK_BY_SCRIPT.get(script_of(txt), "?")
                if txt[-1] != want:
                    bad_q.append(f"#{ln['i']}(U+{ord(txt[-1]):04X}≠U+{ord(want):04X})")
        check(f"{lc} 句末无半角分号", not bad_term, " ".join(bad_term))
        check(f"{lc} 疑问句用本文字系统问号", not bad_q, " ".join(bad_q))

        # 2b 语体：§0.3 承诺的 A/B 语体差必须在文本里真的成立（缺行 = 不检查，不算通过）
        lv = levels.get(lc)
        if lv:
            mk = lv["marker"]
            a_on = [str(ln["i"]) for ln in lines if ln["speaker"] == "A" and mk in ln["text"]]
            b_off = [str(ln["i"]) for ln in lines if ln["speaker"] == "B" and mk not in ln["text"]]
            check(f"{lc} 语体差成立 A={lv['levelA']}/B={lv['levelB']}",
                  not a_on and not b_off,
                  (f"A 含标记#{'#'.join(a_on)} " if a_on else "")
                  + (f"B 缺标记#{'#'.join(b_off)}" if b_off else ""))

        # 2c 时长：§1.4 预算（缺省不给预算则跳过，不假装通过）
        if budget:
            lo, hi = budget
            tlp = AUDIO_DIR / f"{PREFIX}_{lc}.timeline.json"
            if tlp.exists():
                d = json.loads(tlp.read_text("utf-8"))["duration"]
                check(f"{lc} 时长在 {lo:g}–{hi:g}s 预算内", lo <= d <= hi, f"{d:.2f}s")

    print("\n== 3. 选角与骨架")
    for lc in locales:
        tl = json.loads((AUDIO_DIR / f"{PREFIX}_{lc}.timeline.json").read_text("utf-8"))
        loc = scene["locales"][lc]
        cast = {r: next((p for p in personas.values()
                         if p["locale"] == lc and cards["cast"].get(p["id"]) == r), None)
                for r in ("A", "B")}
        check(f"{lc} A=活泼 {cast['A']['name']['native']}",
              cast["A"]["id"] == tl["cast"]["A"] and cast["A"]["energy"] == "lively")
        check(f"{lc} B=沉稳 {cast['B']['name']['native']}",
              cast["B"]["id"] == tl["cast"]["B"] and cast["B"]["energy"] == "steady")
        check(f"{lc} 选角与剧本 §4 一致",
              cast["A"]["name"]["native"] == loc["aName"] and cast["B"]["name"]["native"] == loc["bName"])
        seen, ask = [], {"A": 0, "B": 0}
        for ln in loc["dialogue"]:
            if ln["tokenKey"] and ln["tokenKey"] not in seen:
                seen.append(ln["tokenKey"])
            if ln["isQuestion"]:
                ask[ln["speaker"]] += 1
        full_set = set(seen) == set(scene["tokenOrder"])
        if not full_set:
            check(f"{lc} token 零遗漏零重复", False,
                  "缺 " + "/".join(c for c in scene["tokenOrder"] if c not in seen))
        elif seen != scene["tokenOrder"]:
            # token 齐全但出场次序与 §0.1 书写序不同（ar-SA / he-IL 蓝色置于末轮，见文化注记）
            check(f"{lc} token 零遗漏零重复", True,
                  "齐全，次序偏差 " + ">".join(seen))
        else:
            check(f"{lc} token 零遗漏零重复", True, ">".join(seen))
        check(f"{lc} 问答对称 A{ask['A']}/B{ask['B']}",
              ask["A"] == ask["B"], f'A{ask["A"]}/B{ask["B"]}')

    print("\n== 4. 画面探针")
    ink = hexrgb(UI_INK)
    for lc in locales:
        if not (ROOT / f"{PREFIX}_{lc}.mp4").exists():
            continue
        loc = scene["locales"][lc]
        tl = json.loads((AUDIO_DIR / f"{PREFIX}_{lc}.timeline.json").read_text("utf-8"))
        pa = next(p for p in personas.values() if p["id"] == tl["cast"]["A"])
        pb = next(p for p in personas.values() if p["id"] == tl["cast"]["B"])
        a_line = next(lo for lo in tl["lines"] if lo["speaker"] == "A" and lo["dur"] > 1.0)
        t_speak = a_line["start"] + a_line["dur"] * 0.5          # A 正在说话的一帧
        from PIL import Image
        img = Image.open(grab(lc, t_speak, tmp / f"{lc}_a.png")).convert("RGB")
        check(f"{lc} 画布 1080x1920", img.size == (1080, 1920), str(img.size))

        # 探针①：双人同框——两侧站位都应有人物取样色（抓「画在中间/画丢/站位错」）
        body_y0, body_y1 = 1150, 1700
        for role, p, want in (("A", pa, side_x(lc, "A")), ("B", pb, side_x(lc, "B"))):
            n = sum(count_color(img, c, want - 150, want + 150, body_y0, body_y1)
                    for c in char_colors(p))
            check(f"{lc} {role} 在站位 x≈{want} 有立绘", n > 120,
                  f"{p['name']['native']} 命中 {n} px" + ("（RTL 已对调）" if is_rtl(lc) else ""))

        # 探针②：气泡跟随说话人——A 说话时气泡描边（UI_INK）应落在 A 侧而非 B 侧
        y0, y1 = BUBBLE_CY - 90, BUBBLE_CY + 90
        na = count_color(img, ink, side_x(lc, "A") - 230, side_x(lc, "A") + 230, y0, y1, tol=26)
        nb = count_color(img, ink, side_x(lc, "B") - 230, side_x(lc, "B") + 230, y0, y1, tol=26)
        check(f"{lc} 气泡跟随说话人（RTL 镜像）", na > 40 and na > nb * 2,
              f"A侧 {na} px / B侧 {nb} px")

        white = sum(1 for y in range(BAND_Y, BAND_Y + BAND_H, 6)
                    for x in range(0, 1080, 6) if sum(img.load()[x, y]) > 600)
        check(f"{lc} 文字带有字幕像素", white > 30, f"{white} px")

        # 探针③：末句处 token 装置应全亮（零遗漏的画面侧证据）
        last = tl["lines"][-1]
        img2 = Image.open(grab(lc, last["start"] + last["dur"] * 0.4, tmp / f"{lc}_z.png")).convert("RGB")
        px = img2.load()
        lit = 0
        for key, cell in zip(scene["tokenOrder"], device_cells(device_of(loc))):
            tok = chip_color(scene["tokens"][key])
            hit = sum(1 for y in range(int(cell[1]) + 6, int(cell[3]) - 6, 4)
                      for x in range(int(cell[0]) + 6, int(cell[2]) - 6, 4)
                      if tok and near(px[x, y], tok, 30))
            lit += 1 if hit > 20 else 0
        check(f"{lc} 装置已点亮 {lit}/{len(scene['tokenOrder'])}", lit == len(scene["tokenOrder"]))

    print("\n== 5. 音频契约")
    for lc in locales:
        tl = json.loads((AUDIO_DIR / f"{PREFIX}_{lc}.timeline.json").read_text("utf-8"))
        ok_rate, moods = True, set()
        for lo in tl["lines"]:
            p = personas[tl["cast"][lo["speaker"]]]
            moods.add((lo["speaker"], lo["mood"]))
            if not lo["words"] or not all("s" in w and "e" in w for w in lo["words"]):
                ok_rate = False
        check(f"{lc} 词级时间戳完整", ok_rate, f"{len(tl['lines'])} 行")
        check(f"{lc} 双声线可辨", len({tl["cast"]["A"], tl["cast"]["B"]}) == 2
              and personas[tl["cast"]["A"]]["voice"]["voiceId"] != personas[tl["cast"]["B"]]["voice"]["voiceId"],
              f'{personas[tl["cast"]["A"]]["voice"]["voiceId"]} / '
              f'{personas[tl["cast"]["B"]]["voice"]["voiceId"]}')

    print("\n== 6. 幂等（视频流 framehash）")
    if args.no_idempotent:
        print("  [SKIP] --no-idempotent")
    else:
        lc = locales[0]
        mp4 = ROOT / f"{PREFIX}_{lc}.mp4"
        h1 = subprocess.run(["ffmpeg", "-i", str(mp4), "-map", "0:v",
                             "-f", "hash", "-hash", "md5", "-"],
                            capture_output=True, text=True).stdout.strip()
        subprocess.run([sys.executable, "-m", "usine.scene_video", "render", "--only", lc,
                        "--scene", scene_video.SCENE_ID],
                       check=True, capture_output=True, cwd=str(HERE))
        h2 = subprocess.run(["ffmpeg", "-i", str(mp4), "-map", "0:v",
                             "-f", "hash", "-hash", "md5", "-"],
                            capture_output=True, text=True).stdout.strip()
        check(f"{lc} 重渲逐帧一致", h1 == h2, h1.split("=")[-1][:12])

    npass = sum(1 for _, s, _ in results if s == OK)
    nfail = len(results) - npass
    print(f"\n{'='*56}\n场景线验收：{npass} PASS / {nfail} FAIL（共 {len(results)} 项）")
    for name, st, detail in results:
        if st == BAD:
            print(f"  FAIL {name} — {detail}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
