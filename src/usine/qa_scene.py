#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_scene.py — 教学场景 M2 场景线验收（scene-<id>.md §6 + plan.md §9 M2 口径，场景无关）

六组验收：
  1. 产物规格    <locale> 视频：1080x1920@30fps / h264+aac / 时长 == 时间轴
  2. 文本契约    §0.3 语体差真实成立；疑问句用本文字系统的问号；§0 durationBudget 卡时长
  3. 选角与骨架  A/B = intro-cards.json cast 事实源；问答对称；token 零遗漏零重复；
                 moves 排他动作表（单射合法 + 同台 A/B 动作词汇零交集）
  4. 画面探针    双人同框站位（RTL 语种左右对调）、文字带三层（翻译/金色注记，注记更小更靠下）、
                 立绘↔背景不靠色（本列纯背景最小欧氏距离）、token 装置全亮
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
    AX, BX, TEXT_DIR, BAND_GLOSS, BAND_NOTE, persona_pose, prerender_scene_bg, hl_hex,
    cast_colors,
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


def dist(c1, c2):
    return sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])) ** 0.5


def count_color(img, color, x0, x1, y0, y1, tol=30, step=3):
    px = img.load()
    n = 0
    for y in range(int(y0), int(y1), step):
        for x in range(int(x0), int(x1), step):
            if near(px[x, y], color, tol):
                n += 1
    return n


def char_colors(p):
    return cast_colors(p)


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
        # 问答对称是**该课自己声明**的（§0 `askBalance`，缺省 `any` = 不要求）。
        # 旧写法无条件判 `ask["A"] == ask["B"]` —— 那是 colors 课 §1.1 的设计承诺
        # （A 问三色、B 问三色），被当成通用规则后，「A 主导的计数游戏」这类
        # 同样合理的课会被判失败。缺省 `any` 是有意的：不能默认替所有课定一种戏剧结构。
        _ab = (scene.get("askBalance") or "any")
        if _ab == "symmetric":
            check(f"{lc} 问答对称（§0 askBalance: symmetric 声明）",
                  ask["A"] == ask["B"], f'A{ask["A"]}/B{ask["B"]}')
        else:
            check(f"{lc} 问答分布 A{ask['A']}/B{ask['B']}（§0 askBalance: any，不判对称）", True)

        # 3d 排他动作（需求①）：moves 槽位表逐人专属——单射 + 合法码 + 同台 A/B 零交集
        def vocab(p, slots):
            out = []
            for s in slots:
                try:
                    out.append(persona_pose(p, s))
                except ValueError as e:
                    check(f"{lc} {p['id']} moves 映射非法", False, str(e))
            return set(out)

        slots_by = {r: {lo["pose"] for lo in tl["lines"] if lo["speaker"] == r and lo.get("pose")}
                    for r in ("A", "B")}
        slots_by["A"].add("wave")          # 出画挥手也走各自 moves 表
        slots_by["B"].add("wave")
        va, vb = vocab(cast["A"], slots_by["A"]), vocab(cast["B"], slots_by["B"])
        check(f"{lc} 同台动作零交集（排他）", not (va & vb),
              f"A {len(va)} 招 / B {len(vb)} 招 / 交集 {len(va & vb)}"
              + (f"：{va & vb}" if va & vb else ""))
        for role, p in (("A", cast["A"]), ("B", cast["B"])):
            vals = list((p.get("moves") or {}).values())
            check(f"{lc} {p['name']['native']} moves 单射且合法",
                  len(set(vals)) == len(vals) and len(vals) >= 9, f"{len(set(vals))}/{len(vals)} 槽位")

    print("\n== 4. 画面探针")
    ink = hexrgb(UI_INK)
    # 注记行下限由该课自己声明（§0 `noteFloor`；缺省 0 = 不要求）。
    note_floor = int(scene.get("noteFloor") or 0)
    # 探针⓪（静态）：三层带的文字色 ↔ 带底、卡拉OK高亮色 ↔ 带底，均不得靠色（需求②③）
    for nm, col in (("翻译层", BAND_GLOSS), ("注记层", BAND_NOTE), ("带底原文", "#D6DCEE")):
        d = dist(hexrgb(col), tuple(BAND_BG))
        check(f"文字带 {nm}↔带底对比 ≥100", d >= 100, f"{d:.0f}")
    for key, chip in scene["tokens"].items():
        if chip_color(chip):
            d = dist(hexrgb(hl_hex(chip)), tuple(BAND_BG))
            check(f"卡拉OK高亮 {key}↔带底对比 ≥100", d >= 100,
                  f"{hl_hex(chip)} {d:.0f}")
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

        # 探针②：气泡跟随说话人——按渲染端几何（tight 气泡资产 + side_x + BUBBLE_CY）定位
        # 上描边行：说话侧该行应命中 UI_INK 长横边（≥60%），镜像侧同 y 不应命中（<20%）。
        # （旧探针数窗口内 UI_INK/白像素：near() 是逐通道容差，庭院深色阴影、浅色布景均会
        # 污染计数——2026-10-03 版式重调后气泡缩小，深背景入窗，旧探针误报，废弃。）
        bub_line = next((lo for lo in tl["lines"] if lo["speaker"] == "A" and lo["dur"] > 1.0
                         and (TEXT_DIR / f"bub_{PREFIX}_{lc}_{lo['i']}.png").exists()), None)
        if bub_line:
            img_b = Image.open(grab(lc, bub_line["start"] + bub_line["dur"] * 0.5,
                                    tmp / f"{lc}_bub.png")).convert("RGB")
            bim = Image.open(TEXT_DIR / f"bub_{PREFIX}_{lc}_{bub_line['i']}.png")
            ab = bim.getchannel("A").point(lambda v: 255 if v > 8 else 0)
            bx0, by0, bx1, by1 = ab.getbbox()
            bw_ = bx1 - bx0
            ytop = BUBBLE_CY - (by1 - by0) // 2
            n_span = len(range(-int(bw_ * 0.35), int(bw_ * 0.35) + 1, 4))

            # 采样取**行带内最佳行**（说话侧命中最多、镜像侧最少的那一行），不用单个魔数行。
            # 旧写法钉死 `ytop+3`：colors 气泡宽 158，+3 落在 5px 描边里得 71%；
            # numbers 气泡宽 120，同一个 +3 恰好落在描边**上方 1px**，掉到 45% → 误判失败。
            # 气泡越窄、圆角在采样跨度里占比越高，单行越脆。行带搜索后 colors 82% / numbers 64%，
            # 阈值 60% 一个字没动，判据仍是「说话侧有长横边、镜像侧没有」。
            def ink_hits(cx0, y):
                return sum(1 for x in range(cx0 - int(bw_ * 0.35), cx0 + int(bw_ * 0.35) + 1, 4)
                           if near(img_b.load()[x, y], ink))
            xa, xb = side_x(lc, "A"), side_x(lc, "B")
            band = [(y, ink_hits(xa, y), ink_hits(xb, y)) for y in range(ytop - 4, ytop + 9)]
            by, na2, nb2 = max(band, key=lambda r: r[1] - r[2])
            check(f"{lc} 气泡跟随说话人（RTL 镜像）",
                  na2 >= n_span * 0.6 and nb2 < n_span * 0.2,
                  f"说话侧 {na2}/{n_span} 对侧 {nb2}/{n_span}（y={by}）")
        else:
            check(f"{lc} 气泡跟随说话人（RTL 镜像）", False, "无 A 方气泡资产")

        white = sum(1 for y in range(BAND_Y, BAND_Y + BAND_H, 6)
                    for x in range(0, 1080, 6) if sum(img.load()[x, y]) > 600)
        check(f"{lc} 文字带有字幕像素", white > 30, f"{white} px")

        # 探针④：人物↔背景不靠色（需求③）——立绘取样色 vs 本列纯背景像素最小欧氏距离。
        # cast_cols 与 render_scene 同参：渲染时的「推开」规避也在此生效，探针与成片同口径。
        bg_img, _ = prerender_scene_bg(loc, hexrgb(pa["identity"]), hexrgb(pb["identity"]),
                                       cast_colors(pa) + cast_colors(pb))
        bgpx = bg_img.load()
        for role, p in (("A", pa), ("B", pb)):
            cx = side_x(lc, role)
            samples = [bgpx[x, y] for y in range(1150, 1700, 12)
                       for x in range(cx - 160, cx + 160, 12)]
            worst = min(dist(c, s) for c in char_colors(p) for s in samples)
            check(f"{lc} {role} 立绘↔背景不靠色 ≥36", worst >= 36, f"最小距离 {worst:.0f}")

        # 探针⑤：三层带（需求②）——底版 band 资产：翻译层（30px 连续行块）与金色注记层。
        # 白色原文的抗锯齿会路过翻译色容差，故按「连续行块」判层：真翻译层（哪怕只有
        # 「绿茶。」三个字）也有 ≥6 个连续的 ≥8 命中行；zh-CN（无翻译层）实测零命中行。
        want_gloss = any(ln.get("gloss") for ln in loc["dialogue"])
        noted = [ln for ln in loc["dialogue"] if ln.get("note")]
        # 注记行下限由该课自己声明（§0 `noteFloor`，默认 0 = 不要求）。
        # 旧写法在这里硬编码 ≥3 —— 那是 colors 课的质量线，却被写进了通用探针：
        # 于是「注记按设计是可选的」（剧本体例：仅特别需要说明的才有）这条规则，
        # 在验收层被反转成「每课必须 ≥3」，新课程只要不写注记就被判失败。
        # 注记层的其他探针（翻译层/金色层/层序）照跑——有注记就必须渲对。
        if note_floor:
            check(f"{lc} 注记行 ≥{note_floor}（⚑ 体例，§0 noteFloor 声明）",
                  len(noted) >= note_floor, f"{len(noted)} 行")
        gl_lines, nt_n, ys_gl, ys_nt = 0, 0, [], []
        for ln in noted:
            bp = TEXT_DIR / f"band_{PREFIX}_{lc}_{ln['i']}_base.png"
            if not bp.exists():
                continue
            bimg = Image.open(bp).convert("RGB").crop((0, 0, 1080, BAND_H))
            bpx = bimg.load()
            run = best = 0
            for y in range(BAND_H // 2, BAND_H):               # 原文层永不进下半带
                g_here = sum(1 for x in range(0, 1080, 2)
                             if near(bpx[x, y], hexrgb(BAND_GLOSS), 16))
                n_here = sum(1 for x in range(0, 1080, 2)
                             if near(bpx[x, y], hexrgb(BAND_NOTE), 16))
                nt_n += n_here
                if n_here:
                    ys_nt.append(y)
                if g_here >= 8:
                    ys_gl.append(y)
                    run += 1
                    best = max(best, run)
                else:
                    run = 0
            gl_lines += 1 if best >= 6 else 0
        if want_gloss:
            check(f"{lc} 翻译层在带内呈现", gl_lines == len(noted),
                  f"{gl_lines}/{len(noted)} 注记行有翻译层")
        else:
            check(f"{lc} 原文即中文，无翻译层", gl_lines == 0, f"{gl_lines} 行误报")
        check(f"{lc} 注记层在带内呈现（金色）", nt_n > 15 * len(noted), f"{nt_n} px")
        if want_gloss and ys_gl and ys_nt:
            check(f"{lc} 注记层比翻译层更靠下（更小一号）",
                  sum(ys_nt) / len(ys_nt) > sum(ys_gl) / len(ys_gl),
                  f"翻译均 y={sum(ys_gl) / len(ys_gl):.0f} / 注记均 y={sum(ys_nt) / len(ys_nt):.0f}")

        # 探针⑥：成片帧——注记行说到一半时，翻译层像素应出现在成片文字带内
        #（注记金色与卡拉OK高亮同色 #E8C24A，帧上不可分辨，故注记层以底版资产探针⑤为准）
        if want_gloss and noted:
            nl = next(lo for lo in tl["lines"] if lo["i"] == noted[0]["i"])
            img3 = Image.open(grab(lc, nl["start"] + nl["dur"] * 0.5, tmp / f"{lc}_n.png")).convert("RGB")
            g_in_frame = count_color(img3, hexrgb(BAND_GLOSS), 0, 1080,
                                     BAND_Y, BAND_Y + BAND_H, tol=16, step=2)
            check(f"{lc} 翻译层出现在成片帧", g_in_frame > 25, f"{g_in_frame} px")

        # 探针③：末句处 token 装置应全亮（零遗漏的画面侧证据）
        #
        # 判据取**真实目的**——「这个井有没有被点亮」——而不是代理量「有没有出现某个颜色」。
        # 2026-10-04 新课 numbers（字牌 chip）暴露了旧写法的洞：`chip_color()` 对字牌返回
        # None，`tok and near(...)` 恒假 → 字牌这类 token **根本无法验收**，渲坏了也没人知道。
        # 现在两条判据并存：
        #   色片：井内出现该 chip 色（更强，能抓「亮了但颜色错了」）
        #   字牌：**点亮前后两帧该井区域像素差**（与 chip 类型无关；井内从空井底变成
        #         「空井底 + 数字文字层」一定产生显著差异）
        last = tl["lines"][-1]
        img2 = Image.open(grab(lc, last["start"] + last["dur"] * 0.4, tmp / f"{lc}_z.png")).convert("RGB")
        first_ask = tl["ask"][0]["t"] if tl.get("ask") else 0.0
        img0 = Image.open(grab(lc, max(0.0, first_ask - 0.6),
                                tmp / f"{lc}_a.png")).convert("RGB")
        px, px0 = img2.load(), img0.load()
        lit = 0
        for key, cell in zip(scene["tokenOrder"], device_cells(device_of(loc))):
            x0, y0, x1, y1 = int(cell[0]) + 6, int(cell[1]) + 6, int(cell[2]) - 6, int(cell[3]) - 6
            tok = chip_color(scene["tokens"][key])
            hit = sum(1 for y in range(y0, y1, 4) for x in range(x0, x1, 4)
                      if tok and near(px[x, y], tok, 30))
            if hit > 20:
                lit += 1
                continue
            delta = sum(1 for y in range(y0, y1, 4) for x in range(x0, x1, 4)
                        if not near(px[x, y], px0[x, y], 12))
            if delta > 20:
                lit += 1
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
