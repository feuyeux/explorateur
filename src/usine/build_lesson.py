#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 lessons/<id>/scene.json（脚本/翻译/注音）+ lessons/<id>/analysis/<locale>.json（逐句解析）
合并成一份单文件 HTML 教学文档。

版式：左侧固定栏（视频 + 六色条 + meta，sticky 不随下拉移动）+ 右侧内容区，
14 个语种用顶部 tab 切换（视频与学习内容同步切换）。

事实源分工：
  - 原文 / 注音 / 中文翻译 / 气泡 / 手势 / 舞台 / 装置  → lessons/<id>/scene.json（解析自 lessons/<id>/scene.md，机器不改写）
  - 语法解析 / 词法解析 / 文化背景 / 家族·书写·舞台三段 → lessons/<id>/analysis/<locale>.json（人工产出）
本脚本只排版，不改写任何一侧文本。

用法：
    uv run usine-lesson --scene colors                  # 生成 build/lesson/colors/index.html
    uv run usine-lesson --scene colors --allow-missing   # 允许缺解析文件（占位并列出）
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:                                    # 装成包时走工厂约定
    from usine import ROOT
except ImportError:                     # pragma: no cover
    ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())

from .parse_scene import analysis_dir, find_scene_ids, scene_paths

SCENE_ID = "colors"                     # CLI --scene 覆盖


def _scene_json():
    return scene_paths(SCENE_ID)[1]


def _analysis_dir():
    return analysis_dir(SCENE_ID)


def _out_dir():
    return ROOT / "build" / "lesson" / SCENE_ID


SCENE_VIDEO_DIR = ROOT / "build" / "scene"

# 语系排序（9 组 / 14 语种）—— 文档唯一的排序事实源
FAMILY_ORDER: list[tuple[str, str, list[str]]] = [
    ("sinitic", "汉藏语系 › 汉语族", ["zh-CN", "zh-HK"]),
    ("germanic", "印欧语系 › 日耳曼语族", ["en-US", "de-DE"]),
    ("romance", "印欧语系 › 罗曼语族", ["fr-FR", "es-ES", "it-IT"]),
    ("slavic", "印欧语系 › 斯拉夫语族", ["ru-RU"]),
    ("hellenic", "印欧语系 › 希腊语族", ["el-GR"]),
    ("indoaryan", "印欧语系 › 印度-伊朗语族", ["hi-IN"]),
    ("semitic", "印欧语系 › 闪米特语族", ["ar-SA", "he-IL"]),
    ("japanese", "语系未定 › 日本语", ["ja-JP"]),
    ("koreanic", "语系未定 › 朝鲜语", ["ko-KR"]),
]

FAMILY_INTRO: dict[str, str] = {
    "sinitic": "汉语是世界上母语人口最多的语族。普通话与香港粤语同文不同音，最能说明「书写同源不等于语言相同」。",
    "germanic": "英语与德语同族，但一句普通问话就能看出分野——德语疑问句动词提前、名词一律大写、复合词不断拼接。",
    "romance": "法、西、意三语互通程度极高，但同一组颜色词摆在一起，阴阳性、单复数、形容词位置、冠词缩合的差异立刻现形。",
    "slavic": "俄语是六格、三性、三数的形态重镇——颜色词要跟着所指事物的性属变，这正是「问一句答一句」最吃语法的地方。",
    "hellenic": "希腊语独自成族，保留了自己的重音规则与 η/α 词尾交替，日常语里又大量借入外来词。",
    "indoaryan": "印地语用天城文书写，颜色词多以 -ā 后缀成形容词，颜色与「沾上这种颜色」的语法关系高度规整。",
    "semitic": "闪米特语族以三辅音词根构词、动词靠前缀变位、没有不定式。阿拉伯语与希伯来语同族，却分处两端。",
    "japanese": "日语语系未定。书写上汉字与假名分工：同形词读音可能完全不同，音节数直接决定词尾形态。",
    "koreanic": "朝鲜语形态高度黏着，助词承担了英语里介词、格标记、话题标记的活，颜色词一律带 -색 后缀。",
}

ROLE_CN = {"open": "开场", "reply": "接话", "round": "六色问答", "summary": "小结", "bye": "道别"}
FFPROBE_CANDIDATES = ["ffprobe", r"C:\ProgramData\chocolatey\bin\ffprobe.exe"]


def e(text) -> str:
    """HTML 转义：所有外来文本一律走这里，文档里没有裸插的原文。"""
    return html.escape(str(text if text is not None else ""), quote=True)


def find_ffprobe() -> str | None:
    for cand in FFPROBE_CANDIDATES:
        p = cand if Path(cand).is_absolute() and Path(cand).exists() else shutil.which(cand)
        if p:
            return p
    return None


def find_ffmpeg() -> str | None:
    p = shutil.which("ffmpeg")
    return p or (r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
                 if Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe").exists() else None)


def make_poster(mp4: Path, out: Path, at: float = 2.0) -> bool:
    """抽一帧做播放器封面：否则未播放时播放器是一块黑，看不出是哪支片。
    已存在且不旧于成片就复用；ffmpeg 不可用就返回 False（页面仍可用，只是没封面）。"""
    if not mp4.exists():
        return False
    if out.exists() and out.stat().st_mtime >= mp4.stat().st_mtime:
        return True
    exe = find_ffmpeg()
    if not exe:
        return False
    try:
        subprocess.run(
            [exe, "-v", "error", "-y", "-ss", str(at), "-i", str(mp4),
             "-frames:v", "1", "-vf", "scale=-2:600", "-q:v", "5", str(out)],
            capture_output=True, timeout=120, check=True)
        return out.exists()
    except Exception:                                     # noqa: BLE001
        return False


_PROBE: dict[str, dict] = {}


def probe_video(path: Path) -> dict:
    key = str(path)
    if key in _PROBE:
        return _PROBE[key]
    info = {"exists": path.exists(), "duration": None, "width": None, "height": None, "mb": None}
    if info["exists"]:
        info["mb"] = round(path.stat().st_size / (1024 * 1024), 1)
        exe = find_ffprobe()
        if exe:
            try:
                raw = subprocess.run(
                    [exe, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height",
                     "-show_entries", "format=duration", "-of", "json", str(path)],
                    capture_output=True, text=True, timeout=60, check=True).stdout
                d = json.loads(raw)
                st = (d.get("streams") or [{}])[0]
                info["width"], info["height"] = st.get("width"), st.get("height")
                if (d.get("format") or {}).get("duration"):
                    info["duration"] = round(float(d["format"]["duration"]), 1)
            except Exception as exc:                       # noqa: BLE001
                info["error"] = str(exc)
    _PROBE[key] = info
    return info


def fmt_dur(d) -> str:
    if d is None:
        return "—"
    m, s = divmod(float(d), 60)
    return f"{int(m)}:{s:04.1f}"


def token_order(scene: dict, locale: str) -> list[str]:
    """按该语种台词里颜色实际出现的先后取序（ar-SA / he-IL 的蓝色补写在末轮）。"""
    seen: list[str] = []
    for d in scene["locales"][locale]["dialogue"]:
        k = d.get("tokenKey")
        if k and k not in seen:
            seen.append(k)
    return seen or list(scene.get("tokenOrder", []))


# ---------------------------------------------------------------- 片段


def render_line(node: dict, ana: dict | None, idx: int, tokens: dict) -> str:
    d = node["dialogue"][idx]
    rtl = " rtl" if node["_rtl"] else ""
    sub = []
    if d.get("romanization"):
        sub.append(f'<span class="roman">{e(d["romanization"])}</span>')
    if d.get("gloss"):
        sub.append(f'<span class="gloss">译 {e(d["gloss"])}</span>')
    bub = d.get("bubble") or {}
    ges = d.get("gesture") or {}
    if bub.get("text"):
        sub.append(f'<span class="bub">气泡 {e(bub["text"])}</span>')
    if ges.get("word"):
        sub.append(f'<span class="ges">手势 {e(ges["word"])}</span>')

    o = [f'<article class="line" id="{e(node["locale"])}-l{idx}">']
    o.append('<div class="gut">')
    o.append(f'<span class="no">{idx:02d}</span>')
    o.append(f'<span class="role r-{e(d.get("role", ""))}">{e(ROLE_CN.get(d.get("role", ""), ""))}</span>')
    if d.get("speaker"):
        o.append(f'<span class="spk s-{e(d["speaker"])}">{e(d["speaker"])}</span>')
    if d.get("tokenKey"):
        chip = d.get("tokenChip") or tokens.get(d["tokenKey"], "")
        style = f' style="background:{e(chip)}"' if str(chip).startswith("#") else ""
        o.append(f'<span class="chip{rtl}"{style}>{e(d.get("tokenWord", ""))}</span>')
    o.append("</div>")

    o.append('<div class="body">')
    o.append(f'<p class="sp{rtl}" lang="{e(node["locale"])}">{e(d.get("text", ""))}</p>')
    if sub:
        o.append('<p class="sub">' + "<span>·</span>".join(sub) + "</p>")
    o.append("</div>")

    if ana:
        o.append('<div class="ana">')
        for cls, label, val in (("g", "语法", ana.get("grammar")),
                                ("m", "词法", ana.get("morph")),
                                ("c", "文化", ana.get("culture"))):
            o.append(f'<div class="ac {cls}"><b>{label}</b><span>{e(val) if val else "—"}</span></div>')
        o.append("</div>")
    else:
        o.append('<div class="ac miss"><b>解析</b><span>该语种解析文件缺失，尚未补齐。</span></div>')
    o.append("</article>")
    return "".join(o)


def render_locale(scene: dict, ana: dict | None, locale: str, ordinal: int, fam_idx: int) -> str:
    lc = scene["locales"][locale]
    prop = lc.get("prop", {}) or {}
    dev = prop.get("device", {}) or {}
    tokens = scene.get("tokens", {})
    node = {"dialogue": lc["dialogue"], "locale": locale, "_rtl": locale in scene.get("rtlLocales", [])}
    ana_map = {x["i"]: x for x in (ana or {}).get("lines", [])}

    o = [f'<section class="lc" id="lc-{e(locale)}" data-lc="{e(locale)}" hidden>']
    o.append('<header class="lhead">')
    o.append(f'<div class="lgrow"><span class="ord">{ordinal:02d}<i>/14</i></span>'
             f'<div><h2>{e(lc.get("langLabel", locale))}'
             f'{"<em>RTL</em>" if locale in scene.get("rtlLocales", []) else ""}</h2>'
             f'<p class="chain">{(ana or {}).get("family", "")}</p></div></div>')
    o.append(f'<p class="famtag"><b>{fam_idx:02d}</b>{e(dict((g[0], g[1]) for g in FAMILY_ORDER).get(
        next(k for k, _, v in FAMILY_ORDER if locale in v), ""))}</p>')
    o.append("</header>")

    o.append('<dl class="meta">')
    for k, v, r in (("A 活泼先问", lc.get("aName", ""), locale in scene.get("rtlLocales", [])),
                    ("B 沉稳后答", lc.get("bName", ""), locale in scene.get("rtlLocales", [])),
                    ("舞台", lc.get("stage", ""), False),
                    ("舞台装置", prop.get("label", ""), False),
                    ("装置样式", f"{dev.get('style', '')} / {dev.get('shape', '')}"
                                 f"　井位 {dev.get('cellW', '')}×{dev.get('cellH', '')}", False),
                    ("出场场景", "、".join(prop.get("scenes", [])), False)):
        o.append(f'<div><dt>{e(k)}</dt><dd class="{"rtl" if r and v else ""}">{e(v)}</dd></div>')
    o.append("</dl>")

    o.append('<div class="notes">')
    for k, key in (("家族背景", "familyNote"), ("书写特点", "scriptNote"), ("舞台文化", "stageCulture")):
        v = (ana or {}).get(key)
        o.append(f'<div class="note"><b>{k}</b><p>{e(v) if v else "—"}</p></div>')
    o.append("</div>")

    if prop.get("desc"):
        o.append(f'<p class="pdesc">{e(prop["desc"])}</p>')

    o.append('<div class="tokwrap"><h3>六色词表</h3><div class="tokgrid">')
    for k in token_order(scene, locale):
        t = next((x for x in scene.get("tokenWords", {}).get(locale, []) if x["key"] == k), {})
        forms = " / ".join(t.get("forms", [])) or "—"
        r = " rtl" if locale in scene.get("rtlLocales", []) else ""
        o.append(f'<div class="tok"><span class="sw" style="background:{e(tokens.get(k, ""))}"></span>'
                 f'<span class="tw{r}"><b>{e(t.get("word", ""))}</b><i>{e(t.get("romanization") or "")}</i>'
                 f'<u>{e(forms)}</u></span></div>')
    o.append("</div></div>")

    if lc.get("notes"):
        o.append(f'<div class="srcnote"><b>创作注记 · 源剧本原文</b><p>{e(lc["notes"])}</p></div>')

    o.append(f'<h3 class="lh">逐句脚本与解析<span>{len(lc["dialogue"])} 行　'
             f'开场 1 · 接话 1 · 六色问答 12 · 小结 1 · 道别 2</span></h3>')
    for i in range(len(lc["dialogue"])):
        o.append(render_line(node, ana_map.get(i), i, tokens))
    o.append("</section>")
    return "".join(o)


def build_rail_data(scene: dict, vids: dict) -> str:
    """给前端切 tab 用的数据表：视频地址 + 六色 + meta。"""
    fam_of = {lc: fname for _, fname, locs in FAMILY_ORDER for lc in locs}
    data = {}
    for _, _, locs in FAMILY_ORDER:
        for lc in locs:
            node = scene["locales"][lc]
            vp = vids[lc]
            data[lc] = {
                "src": f"../../scene/scene-{SCENE_ID}_{lc}.mp4" if vp["exists"] else "",
                "poster": f"poster_{lc}.jpg" if vp.get("poster") else "",
                "label": node.get("langLabel", lc),
                "family": fam_of[lc],
                "dur": fmt_dur(vp.get("duration")),
                "spec": f"{vp.get('width')}×{vp.get('height')}　{vp.get('mb')} MB" if vp.get("width") else "—",
                "a": node.get("aName", ""),
                "b": node.get("bName", ""),
                "stage": node.get("stage", ""),
                "prop": (node.get("prop") or {}).get("label", ""),
                "rtl": lc in scene.get("rtlLocales", []),
                "tokens": [{"key": k, "hex": scene.get("tokens", {}).get(k, ""),
                            "word": next((x["word"] for x in scene.get("tokenWords", {}).get(lc, [])
                                          if x["key"] == k), "")}
                           for k in token_order(scene, lc)],
            }
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


# ---------------------------------------------------------------- 主体


def main() -> int:
    global SCENE_ID
    ap = argparse.ArgumentParser(description="lessons/<id>/scene.json + analysis → 单文件教学文档 HTML")
    ap.add_argument("--scene", default="colors", choices=find_scene_ids(),
                    help="课程 id（对应 lessons/<id>/；缺省 colors）")
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()
    SCENE_ID = args.scene

    scene_json = _scene_json()
    if not scene_json.exists():
        print(f"缺少 {scene_json.relative_to(ROOT).as_posix()}", file=sys.stderr)
        return 1
    scene = json.loads(scene_json.read_text(encoding="utf-8"))

    wanted = [lc for _, _, locs in FAMILY_ORDER for lc in locs]
    unknown = [lc for lc in wanted if lc not in scene["locales"]]
    if unknown:
        print(f"排序表里的语种不存在：{', '.join(unknown)}", file=sys.stderr)
        return 1

    analyses, missing = {}, []
    for lc in wanted:
        p = _analysis_dir() / f"{lc}.json"
        if not p.exists():
            missing.append(lc)
            continue
        raw = p.read_text(encoding="utf-8")
        try:
            a = json.loads(raw)
        except json.JSONDecodeError:
            try:
                a = json.loads(raw, strict=False)
                print(f"⚠ {p.name}: 含未转义控制字符，已按字面量容错解析", file=sys.stderr)
            except json.JSONDecodeError as ex:
                print(f"✗ {p.name} 不是合法 JSON：{ex}", file=sys.stderr)
                if not args.allow_missing:
                    return 1
                missing.append(lc)
                continue
        if a.get("locale") != lc:
            print(f"⚠ {p.name}: locale 字段为 {a.get('locale')!r}，与文件名不符", file=sys.stderr)
        idxs = [x.get("i") for x in a.get("lines", [])]
        if sorted(idxs) != list(range(17)):
            print(f"⚠ {p.name}: lines 的 i 不是 0..16 齐全（实得 {len(idxs)} 项）", file=sys.stderr)
        for x in a.get("lines", []):
            for k in ("grammar", "morph", "culture"):
                if not x.get(k):
                    print(f"⚠ {p.name}: 第 {x.get('i')} 行 {k} 为空", file=sys.stderr)
        analyses[lc] = a

    if missing and not args.allow_missing:
        print("缺少解析文件：" + ", ".join(missing), file=sys.stderr)
        return 1

    vids = {lc: probe_video(SCENE_VIDEO_DIR / f"scene-{SCENE_ID}_{lc}.mp4") for lc in wanted}
    out_dir = _out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    for lc in wanted:                       # 封面帧：随成片一起生成/复用
        if vids[lc]["exists"]:
            vids[lc]["poster"] = make_poster(SCENE_VIDEO_DIR / f"scene-{SCENE_ID}_{lc}.mp4",
                                             out_dir / f"poster_{lc}.jpg")

    ordinal, sections, tabs = 0, [], []
    for fi, (fid, fname, locs) in enumerate(FAMILY_ORDER, start=1):
        for lc in locs:
            ordinal += 1
            node = scene["locales"][lc]
            active = " is-on" if ordinal == 1 else ""
            rtl = " is-rtl" if lc in scene.get("rtlLocales", []) else ""
            tabs.append(
                f'<button class="tab{active}{rtl}" data-lc="{e(lc)}" role="tab" '
                f'aria-selected="{"true" if ordinal == 1 else "false"}">'
                f'<i>{ordinal:02d}</i><span>{e(node.get("langLabel", lc))}</span></button>')
            sections.append(render_locale(scene, analyses.get(lc), lc, ordinal, fi))

    total = sum(v["duration"] or 0 for v in vids.values())
    ready = sum(1 for v in vids.values() if v["exists"])

    H: list[str] = []
    H.append("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    H.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    H.append("<title>颜色 · 十四语种教学</title>")
    H.append("<style>" + CSS + "</style></head><body>")

    # ---- 顶栏：标题 + tab
    H.append('<header class="bar">')
    H.append('<div class="brand"><b>颜色</b><span>十四语种教学　6 色 × 17 行 × 14 种语言</span></div>')
    H.append(f'<div class="tog"><button type="button" data-t="ana" class="on">解析</button>'
             f'<button type="button" data-t="note" class="on">背景</button></div>')
    H.append('<nav class="tabs" role="tablist">' + "".join(tabs) + "</nav>")
    H.append(f'<div class="stat">{ready}/14 出片　总时长 {int(total // 60)} 分 {total % 60:04.1f} 秒</div>')
    H.append("</header>")

    # ---- 主体：左固定栏（视频）+ 右内容区
    H.append('<div class="wrap">')
    H.append('<aside class="rail">')
    H.append('<div class="player"><video id="pv" controls playsinline preload="metadata"></video></div>')
    H.append('<div class="strip" id="strip"></div>')
    H.append('<div class="rmeta" id="rmeta"></div>')
    H.append('<p class="rn">按 <kbd>←</kbd> <kbd>→</kbd> 切换语种　按 <kbd>1</kbd>–<kbd>9</kbd> 直达</p>')
    H.append("</aside>")
    H.append('<main class="content">' + "".join(sections) + "</main>")
    H.append("</div>")

    # ---- 页尾：总表 + 说明
    H.append("<footer>")
    H.append("<h3>十四语种总表</h3><div class=\"tw\"><table class=\"idx\"><thead><tr>"
             "<th>#</th><th>语种</th><th>语系</th><th>A / B</th><th>舞台</th><th>舞台装置</th>"
             "<th>时长</th><th>解析</th></tr></thead><tbody>")
    n = 0
    for _, _, locs in FAMILY_ORDER:
        for lc in locs:
            n += 1
            node = scene["locales"][lc]
            mark = '<em>RTL</em>' if lc in scene.get("rtlLocales", []) else ""
            parsed = "14/14" if analyses.get(lc) else "缺"
            H.append(f'<tr><td class="num">{n:02d}</td>'
                     f'<td><button class="jump" data-lc="{e(lc)}">{e(node.get("langLabel", lc))}</button> {mark}'
                     f'<br><code>{e(lc)}</code></td>'
                     f'<td class="fam">{(analyses.get(lc) or {}).get("family", "—")}</td>'
                     f'<td>{e(node.get("aName", ""))} / {e(node.get("bName", ""))}</td>'
                     f'<td>{e(node.get("stage", ""))}</td>'
                     f'<td>{e((node.get("prop") or {}).get("label", ""))}</td>'
                     f'<td class="num">{fmt_dur(vids[lc].get("duration")) if vids[lc]["exists"] else "—"}</td>'
                     f'<td class="num">{parsed}</td></tr>')
    H.append("</tbody></table></div>")
    H.append('<p class="src">脚本原文、注音、中文翻译、气泡与舞台规格来自 '
             f'<code>lessons/{SCENE_ID}/scene.json</code>（由 <code>lessons/{SCENE_ID}/scene.md</code> 经 '
             '<code>parse_scene.py</code> 机械抽取，渲染与本文档共用同一份事实源）；逐句语法／词法／文化解析来自 '
             f'<code>lessons/{SCENE_ID}/analysis/&lt;locale&gt;.json</code>；成片来自 '
             f'<code>build/scene/scene-{SCENE_ID}_&lt;locale&gt;.mp4</code>。'
             '本文件由 <code>build_lesson.py</code> 生成，文本与视频分离——视频按相对路径引用，'
             '移动 <code>build/</code> 目录时请保持 <code>lesson/</code> 与 <code>scene/</code> 的相对位置。</p>')
    H.append("</footer>")

    H.append("<script>var DATA=" + build_rail_data(scene, vids) + ";" + JS + "</script>")
    H.append("</body></html>")

    text = "\n".join(H)
    # 标签配平只查 HTML 部分：<script> 里的 JS 字符串字面量（如 '<dd'+...）不是标签
    markup = re.sub(r"<script\b.*?</script>", "", text, flags=re.S | re.I)
    bad = []
    for tag in ("html", "head", "body", "div", "section", "article", "main", "aside", "header",
                "footer", "nav", "p", "h2", "h3", "span", "b", "i", "em", "u", "a", "dl", "dt",
                "dd", "table", "thead", "tbody", "tr", "td", "th", "button", "video", "kbd"):
        op = len(re.findall(r"<%s[ >]" % tag, markup))
        cl = markup.count("</%s>" % tag)
        if op != cl:
            bad.append(f"{tag} +{op}/-{cl}")
    if bad:
        print("✗ 标签未配平：" + "，".join(bad), file=sys.stderr)
        return 1

    out_html = _out_dir() / "index.html"
    out_html.write_text(text, encoding="utf-8")
    print(f"✓ {out_html.relative_to(ROOT).as_posix()}  {len(text.encode('utf-8')) / 1024:.0f} KB  "
          f"9 个语系段 / 14 个语种 / {sum(len(scene['locales'][lc]['dialogue']) for lc in wanted)} 句  "
          f"解析 {len(analyses)}/14")
    if missing:
        print("⚠ 缺解析：" + ", ".join(missing))
    return 0


CSS = r"""
:root{
  --paper:#F1EDE2; --card:#FFFDF6; --card2:#E7E1D0; --line:#CBC3AD; --line2:#B3A98F;
  --ink:#1C1810; --ink2:#5D5646; --ink3:#8A8271;
  --hot:#C2410C; --cool:#1F4E5F; --gold:#96700F;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Songti SC","Noto Serif CJK SC","Source Han Serif SC",serif;
  --sans:"Inter","Helvetica Neue","PingFang SC","Microsoft YaHei","Noto Sans CJK SC",system-ui,sans-serif;
  --mono:ui-monospace,"Cascadia Code",Consolas,"SF Mono",monospace;
  --bar:64px; --gut:3px;
}
*{box-sizing:border-box}
html{scroll-padding-top:var(--bar)}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.7}
a{color:var(--hot);text-decoration:none}
a:hover{text-decoration:underline}
code{font-family:var(--mono);font-size:.84em;color:var(--ink2)}

/* ---------- 顶栏 ---------- */
.bar{position:sticky;top:0;z-index:40;background:var(--paper);
  border-bottom:2px solid var(--ink);padding:0 var(--gut) 4px}
.brand{display:flex;align-items:baseline;gap:10px;padding:4px 0 2px}
.brand b{font-family:var(--serif);font-size:20px;letter-spacing:.22em;color:var(--hot)}
.brand span{font-size:11.5px;color:var(--ink3);letter-spacing:.14em}
.stat{margin-left:auto;font:400 11px var(--mono);color:var(--ink3);letter-spacing:.06em}
.brand{position:relative}
.tog{position:absolute;right:0;bottom:2px}
.tog button{background:var(--card);color:var(--ink2);border:1px solid var(--line2);
  border-radius:0;padding:1px 9px;margin-left:4px;font:inherit;font-size:11.5px;cursor:pointer;letter-spacing:.1em}
.tog button.on{background:var(--ink);border-color:var(--ink);color:var(--paper);font-weight:600}
.tabs{display:flex;flex-wrap:wrap;gap:2px;margin-top:2px}
.tab{display:flex;align-items:baseline;gap:5px;background:var(--card);border:1px solid var(--line2);
  border-bottom:none;padding:2px 9px;cursor:pointer;font:inherit;color:var(--ink2);letter-spacing:.04em;
  direction:ltr}                          /* 编号必须在名字左边：容器强制 LTR，只有语种名自己内嵌 RTL */
.tab i{font:700 10px var(--mono);color:var(--ink3);font-style:normal}
.tab span{font-size:13px}
.tab:hover{background:var(--card2);color:var(--ink)}
.tab.is-on{background:var(--hot);border-color:var(--hot);color:#fff;font-weight:600}
.tab.is-on i{color:rgba(255,255,255,.75)}
/* 类名刻意用 is-rtl 而不是 rtl：内容区有一个通用工具类 .rtl{direction:rtl}，
   同名同特异性且写在后面，会把整个 tab 翻成 RTL、编号跑到名字右边。 */
.tab.is-rtl span{direction:rtl;unicode-bidi:embed}

/* ---------- 两栏 ---------- */
.wrap{display:grid;grid-template-columns:330px minmax(0,1fr);gap:0;align-items:start;max-width:2600px;margin:0 auto}
.rail{position:sticky;top:var(--bar);align-self:start;max-height:calc(100vh - var(--bar));
  overflow-y:auto;padding:6px var(--gut) 12px 6px;border-right:1px solid var(--line2);background:var(--paper)}
.player{background:#0d0b08;border:1px solid var(--line2);display:flex;align-items:center;justify-content:center}
.player video{height:min(46vh,470px);width:auto;max-width:100%;display:block}
.strip{display:grid;grid-template-columns:repeat(6,1fr);height:26px;margin-top:6px;border:1px solid var(--line2)}
.strip span{position:relative;border-right:1px solid rgba(0,0,0,.12)}
.strip span:last-child{border-right:none}
.strip b{position:absolute;left:2px;bottom:1px;font:700 8.5px var(--mono);color:rgba(0,0,0,.5)}
.strip span.on b{color:#fff;text-shadow:0 0 3px rgba(0,0,0,.5)}
.rmeta{margin-top:7px;border-top:1px solid var(--line2);padding-top:5px}
.rmeta h3{margin:0 0 2px;font-family:var(--serif);font-size:21px;letter-spacing:.02em}
.rmeta h3 em{font:600 9.5px var(--sans);font-style:normal;background:var(--cool);color:#fff;
  padding:1px 5px;letter-spacing:.12em;vertical-align:middle}
.rmeta .fam{font:400 10.5px var(--mono);color:var(--hot);letter-spacing:.06em;margin:0 0 5px}
.rmeta dl{margin:0;display:grid;grid-template-columns:52px 1fr;gap:1px 8px;font-size:12px}
.rmeta dt{color:var(--ink3);font-size:10.5px;letter-spacing:.06em;padding-top:1px}
.rmeta dd{margin:0}
.rmeta .rtl{direction:rtl;text-align:right}
.rmeta .vstat{font:400 10.5px var(--mono);color:var(--ink3);margin:5px 0 0}
.rmeta .vstat a{color:var(--hot)}
.rn{margin:7px 0 0;font-size:10.5px;color:var(--ink3);line-height:1.6}
kbd{font:600 10px var(--mono);border:1px solid var(--line2);background:var(--card);
  padding:0 3px;border-radius:2px}

/* ---------- 内容区 ---------- */
.content{min-width:0;padding:0 6px}
.lc[hidden]{display:none}
.lhead{display:flex;align-items:flex-end;gap:10px;border-bottom:2px solid var(--ink);
  padding:8px 0 4px;margin-bottom:8px}
.lgrow{display:flex;align-items:baseline;gap:9px}
.ord{font:700 26px var(--mono);color:var(--line2);line-height:1}
.ord i{font:400 11px var(--mono);font-style:normal;color:var(--ink3)}
.lhead h2{margin:0;font-family:var(--serif);font-size:34px;letter-spacing:.02em;line-height:1.05}
.lhead h2 em{font:600 9.5px var(--sans);font-style:normal;background:var(--cool);color:#fff;
  padding:1px 5px;letter-spacing:.12em;vertical-align:middle;margin-left:6px}
.chain{margin:1px 0 0;font:400 11px var(--mono);color:var(--hot);letter-spacing:.05em}
.famtag{margin:0 0 0 auto;text-align:right;font-size:12px;color:var(--ink2)}
.famtag b{display:block;font:700 20px var(--mono);color:var(--line2);line-height:1}

.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line2);margin:0 0 8px}
.meta>div{background:var(--card);padding:3px 8px}
.meta dt{font-size:10px;color:var(--ink3);letter-spacing:.1em}
.meta dd{margin:0;font-size:13px}
.rtl{direction:rtl;unicode-bidi:embed;text-align:right}

.notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:6px}
.note{background:var(--card);border:1px solid var(--line2);border-top:3px solid var(--hot);padding:6px 9px}
.note b{display:block;font-size:11px;letter-spacing:.16em;color:var(--hot);margin-bottom:2px}
.note p{margin:0;font-size:12.5px;line-height:1.72}
body.hide-note .notes,body.hide-note .srcnote,body.hide-note .tokwrap{display:none}
.pdesc{margin:6px 0 0;padding:5px 9px;background:rgba(194,65,12,.06);
  border:1px dashed rgba(194,65,12,.4);font-size:12.5px}

.tokwrap{margin:8px 0 0}
.tokwrap h3{margin:0 0 4px;font-size:11px;letter-spacing:.16em;color:var(--ink3)}
.tokgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(124px,1fr));gap:4px}
.tok{display:flex;align-items:center;gap:7px;background:var(--card);border:1px solid var(--line2);padding:3px 7px}
.sw{width:18px;height:18px;border:1px solid rgba(0,0,0,.2);flex:0 0 auto}
.tw{display:flex;flex-direction:column;line-height:1.28}
.tw b{font-size:14.5px}
.tw i{font:400 10.5px var(--mono);font-style:normal;color:var(--ink3)}
.tw u{text-decoration:none;font-size:9.5px;color:var(--ink3)}

.srcnote{margin:7px 0 0;background:var(--card2);border-left:3px solid var(--cool);padding:5px 9px}
.srcnote b{display:block;font-size:10.5px;letter-spacing:.12em;color:var(--cool);margin-bottom:2px}
.srcnote p{margin:0;font-size:12px;color:var(--ink2);line-height:1.7}

.lh{display:flex;align-items:baseline;gap:9px;margin:11px 0 4px;font-size:12px;letter-spacing:.16em;
  color:var(--ink);border-top:2px solid var(--ink);padding-top:6px}
.lh span{font:400 10.5px var(--sans);color:var(--ink3);letter-spacing:.02em}

.line{display:grid;grid-template-columns:92px minmax(0,1fr);gap:0 9px;padding:6px 0;
  border-bottom:1px solid var(--line)}
.line:last-child{border-bottom:none}
.gut{display:flex;flex-wrap:wrap;align-content:flex-start;gap:3px;padding-top:1px}
.no{font:700 13px var(--mono);color:var(--ink3);width:20px}
.role{font-size:9.5px;padding:0 4px;background:var(--card2);color:var(--ink2);
  border:1px solid var(--line2);white-space:nowrap}
.r-round{color:var(--hot);border-color:var(--hot);background:rgba(194,65,12,.07)}
.r-summary{color:var(--cool);border-color:var(--cool);background:rgba(31,78,95,.07)}
.spk{font:700 10px var(--sans);width:16px;height:16px;display:inline-flex;align-items:center;
  justify-content:center;color:#fff}
.s-A{background:var(--hot)} .s-B{background:var(--cool)}
.chip{font:600 10px var(--sans);padding:0 5px;color:#1C1810;background:#CFC7B2;white-space:nowrap}
.body{min-width:0}
.sp{margin:0;font-family:var(--serif);font-size:18px;line-height:1.55;color:var(--ink);word-break:break-word}
.sp.rtl{direction:rtl;unicode-bidi:embed;text-align:right}
.sub{margin:2px 0 0;font-size:11.5px;color:var(--ink2);line-height:1.7}
.sub span{margin:0 4px;color:var(--line2)}
.roman{font-family:var(--mono);letter-spacing:.01em}
.gloss{color:var(--ink)}
.bub{color:var(--hot)} .ges{color:var(--cool)}
.ana{grid-column:1 / -1;display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:4px}
.ac{background:var(--card);border:1px solid var(--line2);padding:4px 7px;font-size:12px;line-height:1.68}
.ac b{display:block;font-size:9.5px;letter-spacing:.16em;margin-bottom:1px}
.ac.g b{color:var(--hot)} .ac.m b{color:var(--cool)} .ac.c b{color:var(--gold)}
.ac.miss{grid-column:1 / -1;border-color:var(--hot)}
.ac.miss b{color:var(--hot)}
body.hide-ana .ana{display:none}

/* ---------- 页尾 ---------- */
footer{padding:10px var(--gut) 26px;max-width:2600px;margin:0 auto;border-top:2px solid var(--ink)}
footer h3{margin:8px 0 5px;font-family:var(--serif);font-size:18px;letter-spacing:.1em}
.tw{overflow-x:auto;border:1px solid var(--line2)}
table.idx{width:100%;border-collapse:collapse;font-size:12px;min-width:880px;background:var(--card)}
table.idx th,table.idx td{border-bottom:1px solid var(--line);padding:3px 8px;text-align:left;vertical-align:top}
table.idx th{background:var(--ink);color:var(--paper);font-weight:600;font-size:11px;letter-spacing:.1em;white-space:nowrap}
table.idx tr:nth-child(even) td{background:rgba(0,0,0,.02)}
td.num{white-space:nowrap;font-family:var(--mono);color:var(--ink2)}
td.fam{color:var(--ink2)}
td em{font:600 8.5px var(--sans);font-style:normal;background:var(--cool);color:#fff;padding:0 4px;letter-spacing:.1em}
.jump{background:none;border:none;padding:0;font:inherit;font-size:13px;color:var(--ink);
  cursor:pointer;text-decoration:underline;text-underline-offset:2px;text-decoration-color:var(--line2)}
.jump:hover{color:var(--hot);text-decoration-color:var(--hot)}
.src{margin:8px 0 0;font-size:11.5px;color:var(--ink2);line-height:1.75}

@media (max-width:900px){
  .wrap{grid-template-columns:1fr}
  .rail{position:static;max-height:none;border-right:none;border-bottom:2px solid var(--ink);
    display:grid;grid-template-columns:minmax(0,1fr);gap:0}
  .player video{height:auto;width:100%;max-height:52vh}
  .line{grid-template-columns:1fr}
  .ana{grid-template-columns:1fr}
  :root{--gut:2px}
}
"""

JS = r"""
var DATA = DATA || {};
var pv = document.getElementById('pv');
var strip = document.getElementById('strip');
var rmeta = document.getElementById('rmeta');
var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
var secs = Array.prototype.slice.call(document.querySelectorAll('.lc'));
var ORDER = tabs.map(function(t){ return t.dataset.lc; });

function esc(s){ return String(s==null?'':s); }

function paint(lc){
  var d = DATA[lc] || {};
  pv.src = d.src || '';
  if (d.poster) { pv.setAttribute('poster', d.poster); } else { pv.removeAttribute('poster'); }
  if (d.rtl) { pv.setAttribute('dir','rtl'); } else { pv.removeAttribute('dir'); }

  strip.innerHTML = (d.tokens||[]).map(function(t){
    return '<span style="background:'+t.hex+'" title="'+esc(t.word)+'"><b>'+esc(t.word)+'</b></span>';
  }).join('');

  rmeta.innerHTML =
    '<h3>'+esc(d.label)+(d.rtl?' <em>RTL</em>':'')+'</h3>'+
    '<p class="fam">'+esc(d.family)+'</p>'+
    '<dl>'+
      '<dt>A</dt><dd'+(d.rtl?' class="rtl"':'')+'>'+esc(d.a)+'</dd>'+
      '<dt>B</dt><dd'+(d.rtl?' class="rtl"':'')+'>'+esc(d.b)+'</dd>'+
      '<dt>舞台</dt><dd>'+esc(d.stage)+'</dd>'+
      '<dt>装置</dt><dd>'+esc(d.prop)+'</dd>'+
    '</dl>'+
    '<p class="vstat">'+esc(d.dur)+'　'+esc(d.spec)+
      (d.src?'　<a href="'+d.src+'" target="_blank" rel="noopener">单独打开</a>':'')+'</p>';
}

function show(lc, push){
  if (ORDER.indexOf(lc) < 0) { lc = ORDER[0]; }
  show.cur = lc;
  tabs.forEach(function(t){ var on = t.dataset.lc === lc; t.classList.toggle('is-on', on);
                             t.setAttribute('aria-selected', on ? 'true' : 'false'); });
  secs.forEach(function(s){ s.hidden = (s.dataset.lc !== lc); });
  paint(lc);
  if (push !== false) { history.replaceState(null, '', '#' + lc); }
  window.scrollTo({ top: 0, behavior: 'auto' });
}

tabs.forEach(function(t){ t.addEventListener('click', function(){ show(t.dataset.lc); }); });
document.querySelectorAll('.jump').forEach(function(b){
  b.addEventListener('click', function(){
    show(b.dataset.lc);
    document.querySelector('.bar').scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
});
document.querySelectorAll('.tog button').forEach(function(b){
  b.addEventListener('click', function(){
    var on = b.classList.toggle('on');
    document.body.classList.toggle('hide-' + b.dataset.t, !on);
  });
});
document.addEventListener('keydown', function(ev){
  if (ev.target && /^(INPUT|TEXTAREA)$/.test(ev.target.tagName)) { return; }
  var i = ORDER.indexOf(show.cur || ORDER[0]);
  if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') { show(ORDER[(i+1) % ORDER.length]); ev.preventDefault(); }
  else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') { show(ORDER[(i-1+ORDER.length) % ORDER.length]); ev.preventDefault(); }
  else if (/^[1-9]$/.test(ev.key)) { var j = parseInt(ev.key,10)-1; if (j < ORDER.length) { show(ORDER[j]); ev.preventDefault(); } }
});
[location.hash || ''].forEach(function(h){
  if (h.length > 1 && ORDER.indexOf(h.slice(1)) >= 0) { show.cur = h.slice(1); }
});
show(show.cur || ORDER[0], false);
"""


if __name__ == "__main__":
    raise SystemExit(main())
