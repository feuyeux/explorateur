#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_scene.py — 通用教学场景解析器：scene-<id>.md → scene_<id>.json

剧本 md 是场景唯一事实源（台词 + 机器规格），本脚本只做**抽取**不做改写：§0 机读规格
（sceneId / title / rtlLocales / 教学 token 表 / 舞台装置规格表）、§2 各语种台词、§5
token 词表全部按体例取回，保证 md 与 JSON 两处同步（CLAUDE.md 不变量③——本脚本是该
同步的构造性保证）。

**场景无关**：新教学场景 = 在 `scenes/` 新建 `scene-<id>.md` 照抄体例，本脚本与渲染线零改动：
    uv run usine-parse [--scene colors]           # scenes/scene-colors.md → scene_colors.json

md 体例（见 scenes/scene-colors.md §0，照抄即可）：
  ## 0. 场景规格（机读）
    sceneId: <课程场景标识>
    title: <中文标题>
    rtlLocales: <逗号分隔，可省略>
    ### 0.x 教学 token 表    | key | chip |          chip = #hex 色片 或 "文本" 字牌
    ### 0.x 装置规格表       | locale | scenes | style | shape | cellW | cellH | well | label |
                             （locale 缺行 = 该语种无装置纯对话）
  ## 2. 各语种剧本           ### <label>｜<aName> × <bName>（label 内含 locale 码）
    台词行：- **A**（happy）：「原文」（*注音*）——中文对照｜「手势词」处 `pose`
            汉字圈用「」、法/俄/希/阿用 «»、en 用 ""；引号内单引号不影响取词
    **舞台**：…。**道具装置**：…。
  ## 5. token 词表           | locale | <token1 词> | … |（列序 = §0.1 token 书写序；
                            单元格 `词 = 别形`（注音）——全部书写形都可逐字命中台词）

输出 scene_<id>.json：{id, sceneId, title, source, rtlLocales, tokenOrder, tokens,
 tokenWords:{locale:[{key,word,forms,romanization}]}, locales:{locale:{…,dialogue[]}}}。
"""
import argparse
import json
import re
from pathlib import Path

from usine import ROOT

HERE = ROOT                              # 仓库根（scene_<id>.json 的锚点，不依赖 cwd）
SCENES_DIR = ROOT / "scenes"             # 场景剧本 md 统一放这里（scene-<id>.md）
LOC_RE = r"(?:[a-z]{2,3}-[A-Z]{2})"
HEAD_RE = re.compile(r"^### (?:\d+\.\d+\s+)?([^｜\n]+)｜([^×\n]+)×\s*([^\n（]+)", re.M)
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$", re.M)


def scene_paths(scene_id):
    """id → (md 路径, json 路径)：约定 scenes/scene-<id>.md / 根下 scene_<id>.json（照抄即接入）。"""
    return SCENES_DIR / f"scene-{scene_id}.md", HERE / f"scene_{scene_id}.json"


def find_scene_ids():
    """仓库内已有的场景 id（scenes/scene-<id>.md 存在即算），供缺省选择与报错提示。"""
    return sorted(p.stem[len("scene-"):] for p in SCENES_DIR.glob("scene-*.md"))


def _split_md(md):
    """按一级节切分：{节号或 '': 文本}。§0 机读规格只在本节内找，避免与 §5 词表混淆。"""
    parts = {}
    marks = list(re.finditer(r"^## (\S*)[^\n]*$", md, re.M))
    for idx, m in enumerate(marks):
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(md)
        parts[m.group(1).rstrip(".:：")] = md[m.end():end]
    return parts


def _tables(text):
    """文本内所有 markdown 表 → [(header_cells, [row_cells…])]，跳过分隔行。"""
    rows = []
    for m in TABLE_ROW_RE.finditer(text):
        cells = [c.strip() for c in m.group(1).split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    out, i = [], 0
    while i < len(rows):
        header = rows[i]
        body = []
        i += 1
        while i < len(rows) and len(rows[i]) == len(header):
            body.append(rows[i])
            i += 1
        out.append((header, body))
    return out


def parse_spec(md):
    """§0 机读规格 → (meta{sceneId,title,rtlLocales}, tokenOrder, tokens, devices)。

    tokens: {key: chip}；chip 以 # 开头 = 色片，否则 = 字牌文本。
    devices: {locale: {scenes,style,shape,cellW,cellH,well,label}}；缺行语种不在表内。
    """
    sec0 = _split_md(md).get("0", "")
    if not sec0.strip():
        raise ValueError("缺 §0 场景规格节（机读体例，见 scenes/scene-colors.md §0）")

    def meta_val(key):
        m = re.search(rf"^{key}:\s*(.+)$", sec0, re.M)
        return m.group(1).strip() if m else ""

    meta = {
        "sceneId": meta_val("sceneId"),
        "title": meta_val("title"),
        "rtlLocales": [x.strip() for x in meta_val("rtlLocales").split(",") if x.strip()],
    }
    if not meta["sceneId"] or not meta["title"]:
        raise ValueError("§0 缺 sceneId / title")

    token_order, tokens = [], {}
    for header, body in _tables(sec0):
        if header[:2] == ["key", "chip"]:
            for row in body:
                if len(row) < 2 or not row[0]:
                    continue
                key, chip = row[0], row[1].strip().strip('"')
                if key in tokens:
                    raise ValueError(f"§0 token 重复：{key}")
                token_order.append(key)
                tokens[key] = chip
    if not tokens:
        raise ValueError("§0 缺教学 token 表（| key | chip |）；纯对话场景省略本表即可，"
                         "但当前体例要求至少给出表格标题行")

    devices = {}
    for header, body in _tables(sec0):
        if len(header) >= 2 and header[0] == "locale" and header[1] == "scenes":
            for row in body:
                loc = row[0]
                devices[loc] = {
                    "scenes": [s.strip() for s in row[1].split(",") if s.strip()],
                    "style": row[2] if len(row) > 2 else "tray",
                    "shape": row[3] if len(row) > 3 else "round",
                    "cellW": int(row[4]) if len(row) > 4 and row[4] else 112,
                    "cellH": int(row[5]) if len(row) > 5 and row[5] else 112,
                    "well": row[6] if len(row) > 6 and row[6] else "",
                    "label": row[7] if len(row) > 7 else "",
                }
    return meta, token_order, tokens, devices


QUOTE_PAIRS = [("「", "」"), ("«", "»"), ("“", "”"), ('"', '"')]


def _match_quote(rest):
    """取行首引号对内的正文（优先级：汉字圈「」→ «»→ 直角"）。
    只认**位于 rest 开头**的引号：否则会误取中文对照里的「夜」这类嵌套引号
    （ar-SA「…跟你一样，ليلى！」行尾注记含「夜」）。"""
    rest = rest.lstrip()
    for op, cl in QUOTE_PAIRS:
        if not rest.startswith(op):
            continue
        j = rest.find(cl, len(op))
        if j < 0:
            continue
        return rest[len(op):j], rest[j + len(cl):]
    return None, rest


def _norm_pose(code):
    return code.strip().strip("`").replace("-", "_").lower()


def parse_line(line):
    """一行台词 → {speaker, mood, text, romanization, gloss, gesture:{word,poses}, exits}"""
    m = re.match(r"^[ \t]*(?:→)?- \*\*([AB])\*\*（(\w+)）：(.*)$", line.strip())
    if not m:
        return None
    speaker, mood, rest = m.group(1), m.group(2), m.group(3).strip()

    text, tail = _match_quote(rest)
    if text is None:
        raise ValueError(f"引号解析失败: {line[:60]}")

    rom_m = re.match(r"^\s*（\*([^*]+)\*）", tail)     # 注音：永不入音，仅 display 参考
    romanization = rom_m.group(1).strip() if rom_m else ""
    if rom_m:
        tail = tail[rom_m.end():]

    gl_m = re.search(r"——(.*?)(?:｜|$)", tail)       # 中文对照（到 ｜ 或行尾）
    gloss = gl_m.group(1).strip() if gl_m else ""

    seg = tail.split("｜", 1)[1] if "｜" in tail else ""          # 手势段
    poses = [_norm_pose(x) for x in re.findall(r"`([a-zA-Z][a-zA-Z0-9_-]*)`", seg)]
    wm = re.search(r"(?:「([^」]+)」|“([^”]+)”|«([^»]+)»|\"([^\"]+)\")\s*处", seg)
    word = next((g.strip() for g in (wm.groups() if wm else ()) if g), "") if wm else ""

    return {
        "speaker": speaker,
        "mood": mood,
        "text": text.strip(),
        "romanization": romanization,
        "gloss": gloss,
        "gesture": {"word": word, "poses": poses},
        "exits": "出画" in seg,
    }


def parse_locales(md, devices):
    """各语种剧本节 → {locale: {...}}；同时按位置骨架标注每行 role/isQuestion。"""
    locales = {}
    heads = list(HEAD_RE.finditer(md))
    for idx, h in enumerate(heads):
        loc_m = re.search(LOC_RE, h.group(0))
        if not loc_m:
            continue
        locale = loc_m.group(0)
        a_name, b_name = h.group(2).strip(), h.group(3).strip()
        label = h.group(1).replace(locale, "").strip().rstrip("★").strip()

        end = heads[idx + 1].start() if idx + 1 < len(heads) else md.find("\n## ", h.end())
        block = md[h.end():end if end > 0 else len(md)]

        st_m = re.search(r"\*\*舞台\*\*：(.+?)。\*\*道具装置\*\*：(.+)", block)
        note_m = re.search(r"\*\*文化注记\*\*：(.+)", block)

        dialogue = [ln for ln in (parse_line(l) for l in block.split("\n")) if ln]
        if len(dialogue) < 2:
            raise ValueError(f"{locale} 台词仅 {len(dialogue)} 行，疑似解析漏行")

        # 位置骨架（scene-colors.md §1.1 体例）：0 开场提议 / 1 应答 / 2..n-4 一来一往
        # （偶数行=问句）/ n-3 收束总结 / n-2 与 n-1 再会。台词行数由剧本自定，骨架只按位置。
        n = len(dialogue)
        for i, ln in enumerate(dialogue):
            ln["i"] = i
            ln["role"] = ("open" if i == 0 else "reply" if i == 1 else
                          "round" if 2 <= i <= n - 4 else
                          "summary" if i == n - 3 else "bye")
            ln["isQuestion"] = ln["role"] == "round" and (i % 2 == 0)

        dev = devices.get(locale)
        prop = {"scenes": (dev["scenes"] if dev else []),
                "device": (dict(dev) if dev else None),
                "label": (dev["label"] if dev else ""),
                "desc": (st_m.group(2).strip() if st_m else "")}
        locales[locale] = {
            "locale": locale,
            "langLabel": label,
            "aName": a_name,
            "bName": b_name,
            "stage": st_m.group(1).strip() if st_m else "",
            "prop": prop,
            "notes": note_m.group(1).strip() if note_m else "",
            "dialogue": dialogue,
        }
    if devices and (extra := set(devices) - set(locales)):
        raise ValueError(f"§0.2 装置规格表含无剧本语种：{sorted(extra)}")
    return locales


def parse_token_words(md, token_order):
    """token 词表 → {locale: [{key, word, forms, romanization}]}（§0 外的 locale 表，
    列序 = token 书写序）。单元格 `词 = 别形`（注音）：全部书写形都用于台词命中。"""
    n = len(token_order)
    out = {}
    for header, body in _tables(md):
        if header[0] != "locale" or len(header) != n + 1:
            continue
        if len(header) > 1 and header[1] in ("chip", "scenes"):
            continue                                    # §0 内的规格表，不是词表
        for row in body:
            if not re.fullmatch(LOC_RE, row[0]):
                continue
            entries = []
            for key, cell in zip(token_order, row[1:]):
                rom = ""
                rm = re.search(r"(?:\(\*([^*]+)\*\)|\*([^*]+)\*)\s*$", cell)
                if rm:
                    rom = (rm.group(1) or rm.group(2)).strip()
                    cell = cell[:rm.start()].strip()
                forms = [f.strip() for f in re.split(r"\s*[=＝]\s*", cell) if f.strip()]
                entries.append({"key": key, "word": forms[0] if forms else "",
                                "forms": forms, "romanization": rom})
            out[row[0]] = entries
    return out


def annotate(locales, token_words, token_order, tokens):
    """标注当前 token 与气泡：按书写形（含别形，大小写不敏感）命中台词，按出场序推进。
    问句→思考气泡给 token 词预览（色片 chip 时带小色块）；答句→提示气泡给联想物
    （＝该行手势词）。无 token 场景：只有提示气泡，纯对话。"""
    for locale, loc in locales.items():
        words = token_words.get(locale, [])
        cur = None
        for ln in loc["dialogue"]:
            low = ln["text"].casefold()
            hit = next((e for e in words
                        if any(f and f.casefold() in low for f in e["forms"])), None)
            if hit and hit["key"] != cur:
                cur = hit["key"]              # 首次提到该 token 即点亮；后续行沿用
            ln["tokenKey"] = cur
            ln["tokenChip"] = tokens.get(cur) if cur else None
            ln["tokenWord"] = next((e["word"] for e in words if e["key"] == cur), "")
            if ln["isQuestion"] and ln["tokenWord"]:
                ln["bubble"] = {"kind": "think", "text": ln["tokenWord"]}
            elif ln["gesture"]["word"]:
                ln["bubble"] = {"kind": "hint", "text": ln["gesture"]["word"]}
            else:
                ln["bubble"] = None
    return locales


def parse_scene(scene_id):
    md_path, out_path = scene_paths(scene_id)
    if not md_path.exists():
        raise SystemExit(f"剧本不存在：{md_path}（已有场景：{', '.join(find_scene_ids()) or '无'}）")
    md = md_path.read_text("utf-8")
    meta, token_order, tokens, devices = parse_spec(md)
    token_words = parse_token_words(md, token_order)
    locales = parse_locales(md, devices)
    if token_order:
        missing = [lc for lc in locales if not token_words.get(lc)]
        if missing:
            raise ValueError(f"token 词表缺语种：{missing}（§5 词表列序 = §0.1 书写序）")
    locales = annotate(locales, token_words, token_order, tokens)

    doc = {
        "id": scene_id,
        "sceneId": meta["sceneId"],
        "title": meta["title"],
        "source": md_path.name,
        "rtlLocales": meta["rtlLocales"],
        "tokenOrder": token_order,
        "tokens": tokens,
        "tokenWords": token_words,
        "locales": locales,
    }
    return doc, out_path


def main():
    ap = argparse.ArgumentParser(description="通用教学场景解析：scene-<id>.md → scene_<id>.json")
    ap.add_argument("--scene", default="colors",
                    help="场景 id（对应 scenes/scene-<id>.md；缺省 colors；可运行 --list 查看已有）")
    ap.add_argument("--list", action="store_true", help="列出已有场景 id")
    args = ap.parse_args()
    if args.list:
        for sid in find_scene_ids():
            print(sid)
        return

    doc, out_path = parse_scene(args.scene)
    locales, token_order = doc["locales"], doc["tokenOrder"]
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")

    # ---- 自检：token 零遗漏零重复 / 轮次气泡齐备（各场景通用口径；骨架对称等
    # 场景专属验收仍以该场景 md §6 为准）----
    gaps, order_dev = [], []
    print(f"{'locale':8} {'rows':>4} {'rounds':>6}  token 序")
    for locale, loc in locales.items():
        qs = [ln for ln in loc["dialogue"] if ln["isQuestion"]]
        seen = []
        for ln in loc["dialogue"]:
            if ln["tokenKey"] and ln["tokenKey"] not in seen:
                seen.append(ln["tokenKey"])
        missing_bubble = [ln["i"] for ln in loc["dialogue"]
                          if ln["role"] == "round" and not ln["bubble"]]
        if token_order and missing_bubble:
            raise ValueError(f"{locale} 轮次行缺气泡：行 {missing_bubble}")
        if token_order:
            if set(seen) != set(token_order):
                gaps.append((locale, seen, len(loc["dialogue"])))
            elif seen != token_order:
                order_dev.append((locale, seen))       # token 齐全，仅出场次序与 §0.1 不同
        print(f"{locale:8} {len(loc['dialogue']):>4} {len(qs):>6}"
              f"  {'>'.join(seen) if seen else '-'}")
    print(f"\n[parse] {doc['sceneId']}（{doc['title']}）：{len(locales)} 语种"
          f" · {len(token_order)} token · 装置 {sum(1 for l in locales.values() if l['prop']['device'])}"
          f" -> {out_path.name}")
    if gaps:
        print("[parse] !! token 有缺（与 §0.1 出场序冲突，需补写轮次）：")
        for locale, seen, rows in gaps:
            print(f"        {locale}: 缺 {'/'.join(k for k in token_order if k not in seen)}"
                  f"  原文 {rows} 行")
    else:
        print(f"[parse] 自检通过：{len(locales)} 语种 token 零遗漏零重复、轮次气泡齐备")
    if order_dev:
        print("[parse] · 次序偏差（token 齐全，出场次序与 §0.1 不同）：")
        for locale, seen in order_dev:
            print(f"        {locale}: {'>'.join(seen)}")


if __name__ == "__main__":
    main()
