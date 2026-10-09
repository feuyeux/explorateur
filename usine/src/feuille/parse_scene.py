#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_scene.py — 通用教学场景解析器：lessons/<id>/scene.md → lessons/<id>/scene.json

lessons 目录参数化：scene_paths / find_scene_ids / analysis_dir / parse_scene 都带可选
lessons_dir（缺省 = feuille 仓库根 lessons/，data.py 锚定）——doctor 与内容项目要把
lessons 指到自己的目录。命令名 `uv run feuille scene parse`；入口 main(argv=None)
（统一入口以 `fn(argv)` 调用）。

使用契约：`parse_scene(scene_id, lessons_dir=None) -> (doc, out_path)`——解析 + 前置校验
（scene_schema.validate_scene）通过才返回，不产出半成品 scene.json；main 落盘后跑
token 零遗漏零重复 / 轮次气泡齐备自检。

剧本 md 是场景唯一事实源（台词 + 机器规格），本脚本只做**抽取**不做改写：§0 机读规格
（sceneId / title / rtlLocales / 教学 token 表 / 舞台装置规格表）、§2 各语种台词、§5
token 词表全部按体例取回，保证 md 与 JSON 两处同步（本脚本是该同步的构造性保证）。

**场景无关**：新教学场景 = 在 `lessons/<id>/` 新建 `scene.md` 照抄体例，本脚本与渲染线零改动：
    uv run feuille scene parse [--scene colors] [--lessons DIR]   # lessons/colors/scene.md → lessons/colors/scene.json

md 体例（见 lessons/colors/scene.md §0，照抄即可）：
  ## 0. 场景规格（机读）
    sceneId: <课程场景标识>
    title: <中文标题>
    rtlLocales: <逗号分隔，可省略>
    ### 0.x 教学 token 表    | key | chip |          chip = #hex 色片 或 "文本" 字牌
    ### 0.x 装置规格表       | locale | scenes | style | shape | cellW | cellH | well | label |
                             （locale 缺行 = 该语种无装置纯对话）
    durationBudget: 40-55   可选；给了 qa_scene 就按此卡时长，超时按 §1.4 回改文本
    ### 0.x 语种文本规范表  | locale | 语体 A | 语体 B | 区分标记 | 说明 |
                             （把「语体差即关系戏」这类注记承诺声明成可验收的数据；缺行 = 不检查）
  ## 2. 各语种剧本           ### <label>｜<aName> × <bName>（label 内含 locale 码）
    台词行：- **A**（happy）：「原文」（*注音*）——中文对照｜「手势词」处 `pose`
            （中文对照只认第一个 ｜ 之前的「——」；手势段/注记段里的「——」是行内批注，不是翻译）
            可选注记段：｜⚑需要特别说明的文化/语言现象（中文，一句话）——
            渲染成比中文对照更小一号的注记条；省略 = 该行无注记（注记内可自由用「——」）
            汉字圈用「」、法/俄/希/阿用 «»、en 用 ""；引号内单引号不影响取词
    **舞台**：…。**道具装置**：…。
  ## 5. token 词表           | locale | <token1 词> | … |（列序 = §0.1 token 书写序；
                            单元格 `词 = 别形`（注音）——全部书写形都可逐字命中台词）

输出 lessons/<id>/scene.json：{id, sceneId, title, source, rtlLocales, durationBudget,
 speechLevels, tokenOrder, tokens, tokenWords:{locale:[{key,word,forms,romanization}]},
 locales:{locale:{…,dialogue[]}}}。
"""
import argparse
import json
import re
from pathlib import Path
from typing import NamedTuple

from .data import LESSONS_DIR           # 课程统一目录：lessons/<id>/scene.md + scene.json + analysis/
                                        # （data.py 锚定 feuille 仓库根，不依赖 cwd）


def _lessons(lessons_dir=None):
    """lessons 目录参数 → Path：None / 空 = 缺省目录。源模块是模块常量，此处参数化——
    doctor / 内容项目要能把 lessons 指到自己的目录（含临时夹具）。"""
    return Path(lessons_dir) if lessons_dir else LESSONS_DIR
LOC_RE = r"(?:[a-z]{2,3}-[A-Z]{2})"
HEAD_RE = re.compile(r"^### (?:\d+\.\d+\s+)?([^｜\n]+)｜([^×\n]+)×\s*([^\n（]+)", re.M)
# polyglot 的小节头没有 `×` 分隔符：三个人都演，标题后是一串名字
HEAD_RE_SHARED = re.compile(r"^### (?:\d+\.\d+\s+)?([^｜\n]+)｜([^\n（]+)", re.M)
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$", re.M)


def scene_paths(scene_id, lessons_dir=None):
    """id → (md 路径, json 路径)：约定 lessons/<id>/scene.md / lessons/<id>/scene.json（照抄即接入）。"""
    d = _lessons(lessons_dir) / scene_id
    return d / "scene.md", d / "scene.json"


def find_scene_ids(lessons_dir=None):
    """仓库内已有的场景 id（lessons/<id>/scene.md 存在即算），供缺省选择与报错提示。"""
    return sorted(p.parent.name for p in _lessons(lessons_dir).glob("*/scene.md"))


def analysis_dir(scene_id, lessons_dir=None):
    """id → lessons/<id>/analysis/（逐句解析 <locale>.json + _source/<locale>.md 的家）。"""
    return _lessons(lessons_dir) / scene_id / "analysis"


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


class Spec(NamedTuple):
    """§0 机读规格的返回值。**给字段起名是为了让外部脚本按名字取**。

    此前它是个裸元组，调用方只能靠下标：§0.6 同台表加进来那天，`beats` 从下标 6
    挪到了 7，`scripts/verify_scene_draft.py` 里的 `parse_spec(md)[6]` 静默取到了
    `cast`——**报「0 节」而不是崩**，门禁看起来是绿的，判据其实已经取错了东西。
    NamedTuple 保持可解包（既有调用零改动），同时把下标这条路堵上。
    """
    meta: dict
    tokenOrder: list
    tokens: dict
    devices: dict
    levels: dict
    roles: dict
    cast: list
    beats: list


def parse_spec(md):
    """§0 机读规格 → Spec(meta, tokenOrder, tokens, devices, levels, roles, cast, beats)。

    tokens: {key: chip}；chip 以 # 开头 = 色片，否则 = 字牌文本。
    devices: {locale: {scenes,style,shape,cellW,cellH,well,label}}；缺行语种不在表内。
    levels:  {locale: {levelA,levelB,marker,note}}（§0.3 语种文本规范；缺行 = 该语种不做语体检查）。
    roles:   {role: energy}（§0.4 角色声明；**合法说话人就是这张表的键**，没有第二份名单）。
    cast:    [{role, locale, framing, note}]（§0.6 同台表；仅 form: polyglot 填，
             dialogue 课留空——那形态的角色按语种各配各的，见 scene_schema §8）。
    beats:   [{beat, from, to, ask, askBy}]（§0.5 骨架节拍；from/to 支持 `n-K` 记法，n = 该语种
             台词行数。**取代旧版按行号硬推的 open/reply/round/summary/bye**）。
    """
    sec0 = _split_md(md).get("0", "")
    if not sec0.strip():
        raise ValueError("缺 §0 场景规格节（机读体例，见 lessons/colors/scene.md §0）")

    def meta_val(key):
        # 分隔处用 `[^\S\n]*` 而不是 `\s*`：`\s` 吃换行，于是留空的 `rtlLocales:`
        # 会把**下一行**（`### 0.1 …`）当成本键的值。既有课都有 rtlLocales 值，
        # 这条路径从来没被走到过——本课三语皆 LTR，第一次留空就炸了出来。
        m = re.search(rf"^{key}:[^\S\n]*(.+)$", sec0, re.M)
        return m.group(1).strip() if m else ""

    meta = {
        "sceneId": meta_val("sceneId"),
        "title": meta_val("title"),
        "form": meta_val("form") or "dialogue",
        "rtlLocales": [x.strip() for x in meta_val("rtlLocales").split(",") if x.strip()],
    }
    if not meta["sceneId"] or not meta["title"]:
        raise ValueError("§0 缺 sceneId / title")

    # durationBudget: "40-55" → [40.0, 55.0]；缺省不设预算（验收跳过时长检查而非判过）
    budget = meta_val("durationBudget")
    if budget:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*", budget)
        if not m:
            raise ValueError(f"§0 durationBudget 格式应为 40-55，实得：{budget!r}")
        meta["durationBudget"] = [float(m.group(1)), float(m.group(2))]

    # askBalance: 该课对「问句在 A/B 之间的分布」的要求。
    #   symmetric = 必须 A 问次数 == B 问次数（colors 课的设计承诺）
    #   any       = 不要求（缺省）。**不能默认替所有课定一种戏剧结构**——A 主导的
    #               计数游戏、单人讲解都同样合理，判失败等于把一种写法当规范。
    ab = meta_val("askBalance")
    if ab and ab not in ("symmetric", "any"):
        raise ValueError(f"§0 askBalance 只能是 symmetric / any，实得：{ab!r}")
    meta["askBalance"] = ab or "any"

    # noteFloor: 该课对 ⚑ 注记行的**自己声明**下限（缺省 0 = 不要求）。
    # 注记按设计是可选的（体例：仅特别需要说明的才有），所以下限必须由课自己说，
    # 不能在通用探针里替所有课定一个数。
    nf = meta_val("noteFloor")
    if nf:
        if not nf.isdigit():
            raise ValueError(f"§0 noteFloor 应为非负整数，实得：{nf!r}")
        meta["noteFloor"] = int(nf)

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
    levels = {}
    for header, body in _tables(sec0):
        if len(header) >= 4 and header[0] == "locale" and "区分标记" in header:
            for row in body:
                if not row[0]:
                    continue
                levels[row[0]] = {
                    "levelA": row[1], "levelB": row[2],
                    "marker": row[3], "note": row[4] if len(row) > 4 else "",
                }

    roles = {}
    for header, body in _tables(sec0):
        if len(header) >= 2 and header[0] == "role" and "energy" in header[1]:
            for row in body:
                if row[0]:
                    roles[row[0]] = row[1]

    # §0.6 同台表（仅 form: polyglot 需要）：角色 ↔ 语种 ↔ 取景的绑定。
    # **为什么另起一张表而不塞进 §0.4 roles**：roles 是 `{角色: energy}`，两门既有的
    # dialogue 课就是这一个形状；往里加列就得改它们的 scene.json，等于凭空动既有课的数据。
    # 另起一表，既有课的 scene.json 逐字节不变。
    cast = []
    for header, body in _tables(sec0):
        if len(header) >= 2 and header[0] == "role" and "locale" in header[1]:
            for row in body:
                if row[0]:
                    cast.append({
                        "role": row[0],
                        "locale": row[1].strip(),
                        "framing": (row[2].strip() if len(row) > 2 and row[2] else "full"),
                        "note": row[3] if len(row) > 3 else "",
                    })

    beats = []
    for header, body in _tables(sec0):
        if len(header) >= 3 and header[0] == "beat" and "from" in header[1] and "to" in header[2]:
            for row in body:
                if not row[0]:
                    continue
                beats.append({
                    "beat": row[0],
                    "from": row[1].strip(),
                    "to": row[2].strip(),
                    "ask": (row[3].strip() if len(row) > 3 else "-") or "-",
                    "askBy": (row[4].strip() if len(row) > 4 else "-") or "-",
                })
    if not beats:
        raise ValueError("§0 缺骨架节拍表（| beat | from | to | ask | askBy |）——"
                         "台词行的角色/问句归属由它决定，不按行号硬推")

    return Spec(meta, token_order, tokens, devices, levels, roles, cast, beats)


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


EGG_HEX = re.compile(r"#([0-9A-Fa-f]{6})")


def _parse_easter_egg(seg):
    """行内「班底彩蛋」批注 → {label, hex}（无则 None）。

    这类批注此前只活在 md 散文里（`——班底彩蛋：江远夹克 `#35486E``），解析时被整段丢弃，
    于是**没有任何东西能校验它**：人设换了色板、md 里手抄错一位，都不会有人发现——
    而剧本自己的验收清单写着「换角即失效」。抽成数据后由 scene_schema 校验。
    """
    m = EGG_HEX.search(seg)
    if not m:
        return None
    pre = seg[:m.start()]
    # 标注文字 = 紧邻 hex 之前、最后一个全/半角冒号之后的那段（「班底彩蛋：」/「面瘫自指：」）
    tail = re.split(r"[：:]", pre)[-1] if re.search(r"[：:]", pre) else pre
    label = tail.strip().strip("—-").strip().strip("`").strip()
    return {"label": label, "hex": "#" + m.group(1).upper()}


def parse_line(line):
    """一行台词 → {speaker, lang, mood, text, romanization, gloss, note, gesture, exits}

    体例 `- **<角色>**（<情绪>）：「原文」`；**角色名不写死 A/B**——`- **C**（happy）` 与
    `- **主持人**（happy）` 一样能解析，合法性由 §0.4 roles 决定（见 scene_schema）。

    polyglot 形态多一段 `· <locale>`：`- **A · en-US**（happy）："..."`。
    这一段是**该行台词用什么语言说**——同台上三个人各说各的语种，一份剧本里混着走。
    缺省（`·` 后面没有）= 沿用该语种块自己的语言，也就是既有 dialogue 课的写法，
    两门既有的 scene.md 一个字都不用改。
    """
    m = re.match(r"^[ \t]*(?:→)?- \*\*([^*]+)\*\*（(\w+)）：(.*)$", line.strip())
    if not m:
        return None
    who, mood, rest = m.group(1).strip(), m.group(2), m.group(3).strip()
    # `·`（U+00B7）分隔角色与语种：角色名里不会出现这个符号
    bits = [b.strip() for b in who.split("·")]
    speaker, lang = (bits[0], bits[1]) if len(bits) > 1 and bits[1] else (bits[0], "")

    text, tail = _match_quote(rest)
    if text is None:
        raise ValueError(f"引号解析失败: {line[:60]}")

    rom_m = re.match(r"^\s*（\*([^*]+)\*）", tail)     # 注音：永不入音，仅 display 参考
    romanization = rom_m.group(1).strip() if rom_m else ""
    if rom_m:
        tail = tail[rom_m.end():]

    # 注记段（⚑）先剥离：注记文字里允许出现「——」，不得被下面的对照解析吃掉
    parts = tail.split("｜")[1:]                                 # ｜ 后的段（注记 + 手势）
    note_parts = [x for x in parts if x.strip().startswith("⚑")]
    note = re.sub(r"^\s*⚑\s*", "", note_parts[0]).strip() if note_parts else ""
    seg = "｜".join(x for x in parts if not x.strip().startswith("⚑"))

    # 中文对照只认首段（第一个 ｜ 之前）的「——」：手势段/注记段的「——」是行内批注，不是翻译
    gl_m = re.search(r"——(.*?)(?:｜|$)", tail.split("｜")[0])
    gloss = gl_m.group(1).strip() if gl_m else ""
    poses = [_norm_pose(x) for x in re.findall(r"`([a-zA-Z][a-zA-Z0-9_-]*)`", seg)]
    wm = re.search(r"(?:「([^」]+)」|“([^”]+)”|«([^»]+)»|\"([^\"]+)\")\s*处", seg)
    word = next((g.strip() for g in (wm.groups() if wm else ()) if g), "") if wm else ""

    line_obj = {
        "speaker": speaker,
        "mood": mood,
        "text": text.strip(),
        "romanization": romanization,
        "gloss": gloss,
        "note": note,
        "gesture": {"word": word, "poses": poses},
        "easterEgg": _parse_easter_egg(seg),
        "exits": "出画" in seg,
    }
    # `lang` 只在真写了语种时才落库：既有 dialogue 课的 scene.json 必须逐字节不变，
    # 多一个恒为空的键就是「既有课被改过」的铁证（实测：colors/numbers 17 行全带上了它）。
    if lang:
        line_obj["lang"] = lang
    return line_obj


def _resolve_index(expr, n):
    """节拍边界求值：支持 `0` / `5` / `n` / `n-4`（n = 该语种台词行数）。"""
    e = expr.strip()
    m = re.fullmatch(r"n\s*-\s*(\d+)", e)
    if m:
        return n - int(m.group(1))
    if e == "n":
        return n
    return int(e)


def apply_beats(dialogue, beats, locale):
    """按 §0.5 声明的骨架节拍标注每行的 role / isQuestion（**不按行号硬推**）。

    旧实现在 `parse_locales` 里写死 open/reply/round/summary/bye 四个偏移与「偶数行=问句」，
    那是 dialogue 这一种形态的骨架，却长在通用解析器里——换个教学形态就得改 Python。
    现在骨架是数据：新增形态只加节拍表，解析器与渲染线零改动。

    节拍必须**完整覆盖** [0, n-1] 且不重叠：留白会让某行既无角色也无问句归属，
    而那正是「为什么这一行没有思考气泡」这类问题的根因。
    """
    n = len(dialogue)
    cover = {}
    for b in beats:
        i0, i1 = _resolve_index(b["from"], n), _resolve_index(b["to"], n)
        if i0 > i1:
            raise ValueError(f"{locale} 节拍 {b['beat']!r} 区间反了：{b['from']} > {b['to']}")
        for i in range(i0, i1 + 1):
            if not (0 <= i < n):
                raise ValueError(f"{locale} 节拍 {b['beat']!r} 覆盖到台词范围外：i={i}（共 {n} 行）")
            if i in cover:
                raise ValueError(f"{locale} 第 {i} 行被两个节拍覆盖：{cover[i]!r} 与 {b['beat']!r}")
            cover[i] = b["beat"]
    gap = [i for i in range(n) if i not in cover]
    if gap:
        raise ValueError(f"{locale} 有 {len(gap)} 行未被任何节拍覆盖：{gap[:8]}（骨架声明必须完整）")

    for i, ln in enumerate(dialogue):
        ln["i"] = i
        b = next(x for x in beats if cover[i] == x["beat"])
        ln["role"] = b["beat"]
        want_parity = b["ask"]
        is_q = False
        if want_parity in ("even", "odd"):
            if (i % 2 == 0) == (want_parity == "even"):
                is_q = (b["askBy"] == "-") or (ln["speaker"] == b["askBy"])
        elif want_parity not in ("-", "none", ""):
            raise ValueError(f"{locale} 节拍 {b['beat']!r} 的 ask 只能是 even/odd/-，"
                             f"实得 {want_parity!r}")
        ln["isQuestion"] = is_q
    # 声明了问句、却一条问句都没产生 —— 静默放过等于交出一支「该有思考气泡的轮次
    # 悄悄没了气泡」的片子，而症状要到看片才发现。**最常见的原因是 even/odd 选错**：
    # 奇偶按**绝对行号**算，不是节拍内偏移，节拍起点落在哪一侧就写哪一侧。
    n_rows = len(dialogue)
    for b in beats:
        if b["ask"] not in ("even", "odd"):
            continue
        i0, i1 = _resolve_index(b["from"], n_rows), _resolve_index(b["to"], n_rows)
        if not any(dialogue[i]["isQuestion"] for i in range(i0, i1 + 1)):
            raise ValueError(
                f"{locale} 节拍 {b['beat']!r}（第 {i0}–{i1} 行）声明了 ask={b['ask']}，"
                f"但这一节没有一行被判为问句——多半是 even/odd 写反了："
                f"奇偶按绝对行号算，起点第 {i0} 行是{'偶' if i0 % 2 == 0 else '奇'}数。")
    return dialogue


def parse_locales(md, devices, beats):
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

        # 位置骨架由 §0.5 声明驱动（apply_beats）：台词行数由剧本自定，骨架是数据不是代码。
        apply_beats(dialogue, beats, locale)

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


def _lang_labels():
    """locale → 母语名（languages/<lc>/manifest.json）。取不到就退回 locale 码本身。

    延迟导入：parse_scene 是链路上最底的一层，模块顶层拉 data 会把加载期环固化下来。
    """
    try:
        from .data import language_manifests
        return {lc: (m.get("label") or lc) for lc, m in language_manifests().items()}
    except Exception:                                   # noqa: BLE001 —— 目录缺失不该拦住解析
        return {}


def parse_shared_stage(md, devices, beats):
    """polyglot：一份**共享**剧本 → (stage_info, {locale: 薄壳}, dialogue)。

    与 dialogue 的根本差别：台词只有一份，三个人轮流在上面说各的语种，
    所以 `scene["dialogue"]` 是**顶层**列表，而 `locales[lc]["dialogue"]` 是空的——
    每个 locale 在这里只是一份「词表 + 装置 + 名字」的壳，供渲染层查 token 词与背景。
    这条分界让校验层（`scene_schema.units_of`）能把两种形态走同一套判据。
    """
    heads = list(HEAD_RE_SHARED.finditer(md))
    if not heads:
        raise ValueError("form=polyglot 需要一个 §2 小节：`### 2.1 <标题>｜<演员A> · <演员B> · …`")
    h = heads[0]
    names = [x.strip() for x in h.group(2).split("·") if x.strip()]
    end = md.find("\n## ", h.end())
    block = md[h.end():end if end > 0 else len(md)]

    st_m = re.search(r"\*\*舞台\*\*：(.+?)。\*\*道具装置\*\*：(.+)", block)
    note_m = re.search(r"\*\*文化注记\*\*：(.+)", block)
    dialogue = [ln for ln in (parse_line(l) for l in block.split("\n")) if ln]
    if len(dialogue) < 2:
        raise ValueError(f"共享剧本台词仅 {len(dialogue)} 行，疑似解析漏行")

    apply_beats(dialogue, beats, "polyglot")

    labels = _lang_labels()
    locales, stage = {}, {"title": h.group(1).strip(), "cast": names,
                           "stage": st_m.group(1).strip() if st_m else "",
                           "notes": note_m.group(1).strip() if note_m else ""}
    seen_lc = []
    for ln in dialogue:
        lc = ln.get("lang")
        if not lc:
            raise ValueError(f"第 {ln['i']} 行没标语种：同台形态每行都要写 `**角色 · locale**`")
        if lc not in seen_lc:
            seen_lc.append(lc)
    for lc in seen_lc:
        dev = devices.get(lc)
        locales[lc] = {
            "locale": lc,
            "langLabel": labels.get(lc, lc),
            "aName": names[seen_lc.index(lc)] if seen_lc.index(lc) < len(names) else "",
            "prop": {"scenes": (dev["scenes"] if dev else []),
                     "device": (dict(dev) if dev else None),
                     "label": (dev["label"] if dev else ""),
                     "desc": stage["stage"]},
            "stage": stage["stage"],
            "notes": stage["notes"],
            "dialogue": [],
        }
    if devices and (extra := set(devices) - set(locales)):
        raise ValueError(f"§0.2 装置规格表含不在共享剧本里的语种：{sorted(extra)}")
    return stage, locales, dialogue


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


def _match_token(words, text):
    """这一行命中哪个 token：取**命中的词里最长的那个**，同长时按 §0.1 序取。

    为什么不能「按序第一个命中」：多语种词表里存在**互为子串**的词。
    法语 `ouest` 里含着 `est`（o-u-**e-s-t**），而 est 的出场序在 ouest 前面——
    说到「西」那一轮，按序命中会点亮「东」的卡片，token 游标从 west 倒退回 east。
    这不是理论问题，是这课第三轮的原文里真实存在的词。

    为什么不改成「按词边界匹配」：CJK 没有词边界，只能子串；而俄/希/阿/印地等语言的
    词表写的是词干，台词里是变格形（красный → красного），一加边界就把它们全打瞎。
    「取最长」只在一行命中 ≥2 个 token 时才与旧行为不同——那种行在旧规则下本来就是错的，
    只命中一个词时行为逐字不变，既有课不受影响。
    """
    low = text.casefold()
    hits = [e for e in words if any(f and f.casefold() in low for f in e["forms"])]
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    order = {e["key"]: i for i, e in enumerate(words)}
    return max(hits, key=lambda e: (max((len(f) for f in e["forms"] if f and f.casefold() in low),
                                       default=0), -order.get(e["key"], 0)))


def annotate(locales, token_words, token_order, tokens, shared=None):
    """标注当前 token 与气泡：按书写形（含别形，大小写不敏感）命中台词，按出场序推进。
    问句→思考气泡给 token 词预览（色片 chip 时带小色块）；答句→提示气泡给联想物
    （＝该行手势词）。无 token 场景：只有提示气泡，纯对话。

    `shared` = polyglot 的那份顶层台词：此时每行**按自己的语种**取词表
    （一份剧本混着三种语言，用哪张词表取决于这行是谁在说），而游标仍跨全剧单调推进。
    """
    def sweep(dialogue, lang_of):
        cur = None
        for ln in dialogue:
            words = token_words.get(lang_of(ln), []) or []
            hit = _match_token(words, ln["text"])
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

    if shared is not None:
        sweep(shared, lambda ln: ln.get("lang") or "")
    else:
        for lc, loc in locales.items():
            sweep(loc["dialogue"], lambda ln, lc=lc: lc)
    return locales


def parse_scene(scene_id, lessons_dir=None):
    md_path, out_path = scene_paths(scene_id, lessons_dir)
    if not md_path.exists():
        raise SystemExit(f"剧本不存在：{md_path}（已有场景：{', '.join(find_scene_ids(lessons_dir)) or '无'}）")
    md = md_path.read_text("utf-8")
    meta, token_order, tokens, devices, levels, roles, cast, beats = parse_spec(md)
    token_words = parse_token_words(md, token_order)
    form = meta.get("form") or "dialogue"
    shared = None
    stage = None
    if form == "polyglot":
        stage, locales, shared = parse_shared_stage(md, devices, beats)
    else:
        locales = parse_locales(md, devices, beats)
    if token_order:
        missing = [lc for lc in locales if not token_words.get(lc)]
        if missing:
            raise ValueError(f"token 词表缺语种：{missing}（§5 词表列序 = §0.1 书写序）")
    locales = annotate(locales, token_words, token_order, tokens, shared)

    doc = {
        "id": scene_id,
        "sceneId": meta["sceneId"],
        "title": meta["title"],
        "form": form,
        "source": md_path.name,
        "noteFloor": meta.get("noteFloor", 0),
        "askBalance": meta.get("askBalance", "any"),
        "rtlLocales": meta["rtlLocales"],
        "durationBudget": meta.get("durationBudget", []),
        "roles": roles,
        "beats": beats,
        "speechLevels": levels,
        "tokenOrder": token_order,
        "tokens": tokens,
        "tokenWords": token_words,
        "locales": locales,
    }
    # cast/stage/dialogue 只在 polyglot 落库：dialogue 课的 scene.json 必须逐字节不变，
    # 多一个空键就是「既有课被改过」的证据。
    if shared is not None:
        doc["cast"] = cast
        doc["stage"] = stage
        doc["dialogue"] = shared

    # 前置校验：解析完立刻对账，不合规就地失败，不产出半成品 scene.json。
    # 校验层本身经 scripts/verify_scene_schema.py 反向验证（12 种定向破坏必须被抓）。
    from .scene_schema import validate_scene
    errs = validate_scene(doc)
    if errs:
        raise ValueError("场景数据不合规（parse 自检）：\n  - " + "\n  - ".join(errs))
    return doc, out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="通用教学场景解析：lessons/<id>/scene.md → lessons/<id>/scene.json")
    ap.add_argument("--scene", default="colors",
                    help="场景 id（对应 lessons/<id>/scene.md；缺省 colors；可运行 --list 查看已有）")
    ap.add_argument("--lessons", default=None,
                    help="lessons 目录（缺省 = feuille 仓库根 lessons/；内容项目指自己的目录）")
    ap.add_argument("--list", action="store_true", help="列出已有场景 id")
    args = ap.parse_args(argv)
    if args.list:
        for sid in find_scene_ids(args.lessons):
            print(sid)
        return

    doc, out_path = parse_scene(args.scene, args.lessons)
    locales, token_order = doc["locales"], doc["tokenOrder"]
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")

    # ---- 自检：token 零遗漏零重复 / 轮次气泡齐备（各场景通用口径；骨架对称等
    # 场景专属验收仍以该场景 md §6 为准）----
    # polyglot 只有一份共享台词，游标跨全剧推进，所以按「台词在哪儿」而不是
    # 「哪个语种」来列——否则同台那一支永远显示 0 行，看不出是漏了还是没台词。
    scripts = ([("stage", doc.get("dialogue") or [])] if "dialogue" in doc
               else [(lc, loc["dialogue"]) for lc, loc in locales.items()])
    gaps, order_dev = [], []
    print(f"{'locale':8} {'rows':>4} {'rounds':>6}  token 序")
    for locale, dialogue in scripts:
        qs = [ln for ln in dialogue if ln["isQuestion"]]
        seen = []
        for ln in dialogue:
            if ln["tokenKey"] and ln["tokenKey"] not in seen:
                seen.append(ln["tokenKey"])
        missing_bubble = [ln["i"] for ln in dialogue
                          if ln["role"] == "round" and not ln["bubble"]]
        if token_order and missing_bubble:
            raise ValueError(f"{locale} 轮次行缺气泡：行 {missing_bubble}")
        if token_order:
            if set(seen) != set(token_order):
                gaps.append((locale, seen, len(dialogue)))
            elif seen != token_order:
                order_dev.append((locale, seen))       # token 齐全，仅出场次序与 §0.1 不同
        print(f"{locale:8} {len(dialogue):>4} {len(qs):>6}"
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
