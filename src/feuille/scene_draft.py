#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_draft.py — 教学创意 → `lessons/<id>/scene.md` 草稿生成环节（P2-1）

搬运自 explorateur/src/usine/scene_draft.py（407 行）。适配点（仅此四处，坑注/准则注
与函数体逐字节照搬）：
- 注册表现取改为 feuille 渲染线本体：`intro_cards` → `feuille.rig`、`scene_video` →
  `feuille.devices`（与 scene_schema 取**同一份**注册表——单一事实源，不抄名单）；
- 源模块顶部 `from usine import ROOT` + `LESSONS_DIR = ROOT / "lessons"` 是**从未被
  引用的残留常量**（输出路径由 --brief 的同目录推导），搬运时删除；
- 语种 / 班底数据可指目录：_langs 与 main 增加 languages / personas 目录参数
  （缺省 = feuille/languages 语种注册表与 feuille/personas 班底——能力数据）；
- 命令名 `usine-draft` / `usine-parse` → `uv run feuille scene draft` / `... parse`
  （含生成的草稿里写给作者看的「下一步」命令行）。

使用契约：`render(brief, personas, cards, langs, reg)` 纯函数生成全文（一个字的内容
都不生成，只填结构）；落盘前拒覆盖已定稿文件（frontmatter 无 `draft: true` 标记必须
--force）；`--gaps` 只数 TODO 欠账不生成。

**为什么有这个环节**：一课要 14 份原生剧本，结构部分全是机械劳动却极易出错——
每个语种都要写舞台句、选对引号对、填 A/B 姓名（班底里谁演 A？）、按骨架节拍排说话人、
算准 n-K 边界、列 §5 词表的每一格。过去这些全靠人手，一课 14×N 行；
而**结构写错时不会立刻报错**，只会渲染出一支骨架错乱的成片，或在 `apply_beats`
抛「某行未被任何节拍覆盖」这种看不出病因的错（手册坑㉗就是这么来的）。

**分工**：本模块只生成**结构**，一个字的内容都不生成。
- 它填：frontmatter、§0 全部机读字段、§2 每个语种的行数/说话人/情绪/姿态槽位、§5 词表格子、选角姓名、引号对
- 它不填：台词、词表词义、舞台描述 —— 那些留 `TODO` 给作者

**事实源全部现取，不硬编码**：引号对与语种名来自 `languages/<locale>/manifest.json`，
选角来自 `personas.json` × `intro-cards.json` 的 cast 表，情绪/姿态/装置样式的合法取值
来自渲染线的注册表。写一个注册表里没有的取值 = 造出「声明合法但渲不出来」的坑。

用法：
    uv run feuille scene draft --brief lessons/numbers/brief.json   # 生成草稿
    uv run feuille scene draft --brief ... --out ... --force         # 覆盖已有
    uv run feuille scene draft --brief ... --print-plan              # 只打印计划，不落盘
    uv run python -m feuille.scene_draft --brief ... --gaps          # 草稿还欠多少（不生成）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .parse_scene import _norm_pose

TODO = "TODO"

# 草稿落盘时必须带这个标记，否则下次运行会被 --force 拒掉。
DRAFT_MARK = "draft: true"


# ---------------------------------------------------------------- 语言 / 班底事实源

def _langs(languages_dir=None):
    from .data import language_manifests
    m = language_manifests(languages_dir)
    if not m:
        raise SystemExit("语种目录为空：先建 languages/<locale>/manifest.json（见 languages/README.md）")
    return m


def _registries():
    """情绪 / 姿态 / 装置样式的合法取值——从渲染线现取，避免本模块硬编码一份。

    姿态码先过 `parse_scene._norm_pose`：md 体例里写 `jump-celebrate`，解析器会归一成
    `jump_celebrate` 再查注册表。拿**未归一**的串去查注册表，好 brief 会被误判成非法——
    那是拿尺子量错了东西（坑㉛ 同源）。
    """
    from . import devices, rig
    from .parse_scene import _norm_pose
    return {
        "moods": set(rig.MOOD_FACE),
        "poses": {_norm_pose(p) for p in rig.POSE_CODES} | {"bounce_in"},
        "device_styles": set(devices.DEVICE_STYLES),
    }


def cast_for(locale, personas, cards):
    """locale → {role: native 姓名}。班底里该语种的 A/B 各一人（scene_schema 第 7 组在守这条）。

    选角事实源 = `personas.json` 的 locale × `intro-cards.json` 的 cast 表，不是剧本里手写——
    手写过一次「A/B 选反」的错，而剧本只写姓名，看不出谁活泼谁沉稳。
    """
    out = {}
    for role in ("A", "B"):
        ids = [pid for pid, p in personas.items()
               if p.get("locale") == locale and (cards.get("cast") or {}).get(pid) == role]
        if len(ids) != 1:
            raise SystemExit(f"{locale} {role} 角选派异常：{ids or '班底里没有该 locale 的人'}"
                             f"——先补 personas.json / intro-cards.json")
        out[role] = personas[ids[0]]["name"]["native"]
    return out


# ---------------------------------------------------------------- 骨架展开

def expand_skeleton(skeleton, n):
    """骨架行数规格 → [(beat, from, to, ask, askBy)]，边界用 `n-K` 记法。

    `lines: "rest"` = 吸收其余全部行。这样作者只写「开场 1 行、来回 N 轮、收 3 行」，
    n 由骨架算出来，**不必手算 n-K 边界**——那正是坑㉗的来源。
    """
    rest = [s for s in skeleton if s.get("lines") == "rest"]
    if len(rest) > 1:
        raise SystemExit(f"骨架里只能有一个 rest，实得 {[s['beat'] for s in rest]}")
    fixed = sum(int(s["lines"]) for s in skeleton if s.get("lines") != "rest")
    if not rest and n is None:
        raise SystemExit("骨架没有 rest 项，必须给出总行数 n")
    total = n if n is not None else None
    if rest:
        if total is None:
            raise SystemExit("骨架含 rest 项时不需要再给 n")
        rest_n = total - fixed
        if rest_n < 1:
            raise SystemExit(f"骨架行数超了：rest 只剩 {rest_n} 行（总 {total} - 固定 {fixed}）")
        plan = [(s["beat"], None, int(s["lines"]) if s.get("lines") != "rest" else rest_n, s)
                for s in skeleton]
    else:
        if total is not None and total != fixed:
            raise SystemExit(f"n={total} 与骨架各节之和 {fixed} 不一致")
        plan = [(s["beat"], None, int(s["lines"]), s) for s in skeleton]

    out, i = [], 0
    rest_at = next((k for k, s in enumerate(skeleton) if s.get("lines") == "rest"), None)
    for k, (beat, _, count, s) in enumerate(plan):
        # 边界要不要写成 `n-K`，看它**依不依赖各语种的台词行数 n**：
        #   · `rest` 之前各节行数固定 → 起止都写死
        #   · `rest` 本身     → 起点写死、终点写 n-K（它吸收剩余）
        #   · `rest` 之后各节 → **起止都写 n-K**（整节位置被 rest 段的长度推着走）
        # 反例：summary 起点写死 14，某语种多写一行台词 n 变 18，第 14 行就成了 summary，
        # 而 17 行没人认领——`apply_beats` 会抛「有 1 行未被任何节拍覆盖」，病因在几百行外。
        rel_to = (rest_at is not None and k >= rest_at)
        rel_from = (rest_at is not None and k > rest_at)
        out.append({"beat": beat, "from": i, "to": i + count - 1, "count": count,
                    "ask": s.get("ask", "-"), "askBy": s.get("askBy", "-"),
                    "rel_from": rel_from, "rel_to": rel_to})
        i += count
    return out


def beat_table_md(beats, n):
    """§0.5 节拍表：随 n 变化的边界一律用 `n-K`（判据见 expand_skeleton 里的注释）。"""
    rows = ["| beat | from | to | ask | askBy |", "| --- | --- | --- | --- | --- |"]
    for b in beats:
        frm = f"n-{n - b['from']}" if b.get("rel_from") else str(b["from"])
        to = f"n-{n - b['to']}" if b.get("rel_to") else str(b["to"])
        rows.append(f"| {b['beat']} | {frm} | {to} | {b['ask']} | {b['askBy']} |")
    return "\n".join(rows)


def _at(spec, offset, default=None):
    """节拍内取值：字符串 = 整节同一个；列表 = 按行偏移逐行给。

    为什么允许列表：`bye` 这种收尾节天然是「A 收 → B 祝福 → A 走」的固定三拍，
    用一个值表达不了；而把说话人和情绪按行写死在校验里又太重。
    """
    if spec is None:
        return default
    if isinstance(spec, (list, tuple)):
        return spec[offset] if offset < len(spec) else default
    return spec


def assign_lines(beats, spec):
    """骨架 → 每行的 {speaker, mood, pose, isQuestion}。

    规则只有两条，且都与 `parse_scene.apply_beats` 对齐（否则草稿自己就和解析器打架）：
      - 非问句节：整节同一说话人（`spec[beat]` 的 `.speakers` / `.moods` / `.poses`）
      - 问句节：按 `ask` 指定的奇偶，命中的一行给 `askBy`（发问方），另一行给对方；
        该节可另给 `.moodAsk/.moodReply`、`.poseAsk/.poseReply` 覆盖（round 节几乎总要）

    每个取值都可以是「字符串（整节同值）」或「列表（按节内行偏移逐行给）」。
    """
    def pick(beat, kind, q, default=None):
        # 问句节优先取 ask/reply 变体；没给就退回整节取值
        key = f"{beat}.{kind}Ask" if q else f"{beat}.{kind}Reply"
        v = spec.get(key)
        if v is None:
            v = spec.get(f"{beat}.{kind}")
        return v

    lines = []
    for b in beats:
        ask = b["ask"]
        is_ask = ask in ("even", "odd")
        for i in range(b["from"], b["to"] + 1):
            off = i - b["from"]
            if is_ask:
                q = (i % 2 == 0) == (ask == "even")
                sp = b["askBy"] if q else ("B" if b["askBy"] == "A" else "A")
                mood = _at(pick(b["beat"], "mood", q), off, "neutral")
                pose = _at(pick(b["beat"], "pose", q), off, "")
            else:
                sp = _at(spec.get(f"{b['beat']}.speakers"), off, "A")
                mood = _at(spec.get(f"{b['beat']}.mood"), off, "neutral")
                pose = _at(spec.get(f"{b['beat']}.pose"), off, "")
            lines.append({"i": i, "beat": b["beat"], "speaker": sp, "mood": mood,
                          "pose": pose or "",
                          "isQuestion": is_ask and ((i % 2 == 0) == (ask == "even"))})
    return lines


# ---------------------------------------------------------------- 各节渲染

def _md_table(header, rows):
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def render(brief, personas, cards, langs, reg):
    """brief → scene.md 全文。"""
    sid = brief["sceneId"]
    locales = brief["locales"]
    unknown = [l for l in locales if l not in langs]
    if unknown:
        raise SystemExit(f"没有语种目录：{unknown}（先建 languages/<loc>/manifest.json）")

    n = brief.get("lines")
    beats = expand_skeleton(brief["skeleton"], n)
    n_lines = sum(b["count"] for b in beats)
    if n_lines < 2:
        raise SystemExit(f"骨架只展开出 {n_lines} 行台词，parse_locales 要求 ≥2")

    spec = brief.get("spec", {})
    plan = assign_lines(beats, spec)

    codes = {_norm_pose(c) for l in plan for c in (l["pose"] or "").split() if c}
    bad = sorted(codes - reg["poses"])
    if bad:
        raise SystemExit(f"brief 里的姿态 {bad} 不在 POSE_CODES 注册表内（渲染会炸）")
    bad = sorted({l["mood"] for l in plan} - reg["moods"])
    if bad:
        raise SystemExit(f"brief 里的情绪 {bad} 不在 MOOD_FACE 内（渲染会炸）")
    styles = {d.get("style") for d in (brief.get("devices") or {}).values() if d}
    bad = sorted(styles - reg["device_styles"])
    if bad:
        raise SystemExit(f"brief 里的装置 style {bad} 不在 DEVICE_STYLES 注册表内")

    L = []
    L.append("---")
    L.append('type: "Content"')
    L.append(f'title: "{brief["title"]}"')
    L.append(f'description: "{brief.get("description", "")}"')
    L.append("tags: [content, scene, teaching-video]")
    L.append(f"generated: {{ by: scene_draft, {DRAFT_MARK} }}")
    L.append("---")
    L.append("")
    L.append(f"# {brief['title']}")
    L.append("")
    L.append(f"> **学习目标**：{brief.get('goal', TODO)}")
    L.append(f"> **结构**：{brief.get('structure', TODO)}")
    L.append(f"> **待办**：本文件是 {brief['sceneId']} 的**结构草稿**，由 `feuille scene draft` 从 "
             f"`lessons/{sid}/brief.json` 生成。所有 `{TODO}` 都是待填槽位。")
    L.append(f"> 填完跑 `uv run feuille scene parse --scene {sid}` + `feuille scene draft --brief ... --gaps` 查欠账。")
    L.append("")
    L.append("## 0. 场景规格（机读体例——parse_scene.py 只认本节 + §2 台词体例 + §5 词表）")
    L.append("")
    L.append(f"sceneId: {brief['sceneId']}")
    L.append(f"title: {brief['title']}")
    L.append(f"form: {brief.get('form', 'dialogue')}")
    if brief.get("rtlLocales"):
        L.append(f"rtlLocales: {', '.join(brief['rtlLocales'])}")
    if brief.get("durationBudget"):
        L.append(f"durationBudget: {brief['durationBudget']}")
    if brief.get("noteFloor"):
        L.append(f"noteFloor: {brief['noteFloor']}")
    if brief.get("askBalance"):
        L.append(f"askBalance: {brief['askBalance']}")
    L.append("")
    L.append("### 0.1 教学 token（书写序 = 出场序）")
    L.append("")
    L.append(_md_table(["key", "chip"],
                       [[t["key"], t["chip"]] for t in brief["tokens"]]))
    L.append("")
    L.append("### 0.2 舞台装置规格（style = devices 的 `@device_style` 注册表；well = 空井底色）")
    L.append("")
    dev_rows = []
    for loc in locales:
        d = (brief.get("devices") or {}).get(loc) or {}
        sc = d.get("scenes")
        scenes = sc if isinstance(sc, str) else ", ".join(sc or [])
        dev_rows.append([loc, scenes or TODO,
                         d.get("style", "tray"), d.get("shape", "round"),
                         d.get("cellW", 112), d.get("cellH", 112),
                         d.get("well", ""), d.get("label", TODO)])
    L.append(_md_table(["locale", "scenes", "style", "shape", "cellW", "cellH", "well", "label"],
                       dev_rows))
    L.append("")
    if brief.get("levels"):
        L.append("### 0.3 语种文本规范")
        L.append("")
        L.append(_md_table(["locale", "语体 A", "语体 B", "区分标记", "说明"],
                           [[k, v.get("a", TODO), v.get("b", TODO), v.get("marker", TODO), v.get("note", "")]
                            for k, v in brief["levels"].items()]))
        L.append("")
    L.append("### 0.4 角色声明（选角纪律的可验收形式——plan §6.1）")
    L.append("")
    L.append(_md_table(["role", "energy", "说明"],
                       [[r, brief["roles"][r].get("energy", "lively"), brief["roles"][r].get("note", "")]
                        for r in ("A", "B") if r in brief["roles"]]))
    L.append("")
    L.append("### 0.5 骨架节拍（台词行的角色与问句归属由本表决定，不按行号硬推）")
    L.append("")
    L.append(f"`n` = 该语种台词行数（本课 n={n_lines}）。节拍须完整覆盖 `[0, n-1]` 且不重叠。")
    L.append("")
    L.append(beat_table_md(beats, n_lines))
    L.append("")
    L.append("## 1. 规格总则")
    L.append("")
    L.append(f"### 1.1 骨架（全语种共享）\n\n{brief.get('structure', TODO)}\n")
    L.append("### 1.2 独立创作原则（承 colors 课 §1.2）\n\n"
             "一骨架、每语种独立剧本：说法、语气、舞台道具全部在语种内自洽，不从中文直译。\n")
    L.append("## 2. 剧本\n")
    L.append("体例：台词 = 原文（*注音*）——中文对照。罗马注音永不入音；对照仅供阅读理解。\n")

    for loc in locales:
        m = langs[loc]
        cast = cast_for(loc, personas, cards)
        qo, qc = m["quote"][0], m["quote"][-1]      # manifest 存的是「一对」，这里拆开用
        beat_from = {b["beat"]: b["from"] for b in beats}   # noteOn 逐行取值要节内偏移
        L.append(f"### 2.{locales.index(loc) + 1} {m['label']} {loc}｜{cast['A']} × {cast['B']}\n")
        L.append(f"**舞台**：{(brief.get('stage') or {}).get(loc, TODO)}"
                 f"　**道具装置**：{(brief.get('devices') or {}).get(loc, {}).get('label', TODO)}\n")
        for ln in plan:
            # 一行可以有多个姿态码（`bounce-in` 入场，… 处 `both-hands`）：用空格分隔书写，
            # 全部反引号化。解析器逐个取，scene_schema 也逐个查注册表。
            codes = " ".join(f"`{c}`" for c in (ln["pose"] or "").split())
            # 手势锚词槽必须是**带引号**的 `「TODO」处`，不是裸 `TODO 处`：
            # `parse_line` 认锚词的正则只匹配 `「…」`/`“…”`/`«…»`/`"…"` 四种带引号形式，
            # 裸 TODO 既填不出锚词、也过不了 `parse` 的气泡检查——作者只能照着
            # 已验收稿（colors/numbers 的 `「数」处`）反推格式。把占位符写成最终形状，
            # 「填词」才真的只是填词。引号对取自 languages/<loc>/manifest.json。
            seg = f"｜{qo}{TODO}{qc} 处 {codes}" if codes else ""
            # noteOn 按**节内行偏移**取值（同 `spec` 的字符串/列表两型）：
            # 收尾节常常只有最后一行动作（例如「B 祝福 → A 蹦跳出画」），
            # 写成字符串会把 `exit` 铺满整节，于是 A、B 一起跑出画。
            # 字符串 = 整节同值（numbers 旧 brief 的写法，仍然支持）；列表 = 逐行给。
            b0 = beat_from.get(ln["beat"], 0)
            mark = _at((brief.get("noteOn") or {}).get(ln["beat"]),
                       ln["i"] - b0, "") or ""
            if TODO in mark:
                seg += f"｜⚑{TODO}"
            if "exit" in mark:
                seg = (seg if seg else "｜") + "＋蹦跳出画"
            L.append(f"- **{ln['speaker']}**（{ln['mood']}）：{qo}{TODO}{qc}{seg}")
        L.append("")

    L.append("## 5. token 词表（对照参考——列序 = §0.1 token 书写序，机读按位置对位）\n")
    keys = [t["key"] for t in brief["tokens"]]
    L.append(_md_table(["locale"] + [t.get("head", t["key"]) for t in brief["tokens"]],
                       [[loc] + [TODO] * len(keys) for loc in locales]))
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 欠账清单

def gaps(md):
    """数出草稿里还剩多少 TODO —— 草稿的价值就在这张单子，它决定了「还要写多少字」。"""
    n_line = len([l for l in md.splitlines() if l.strip().startswith("- **")])
    n_todo_line = len([l for l in md.splitlines() if l.strip().startswith("- **") and TODO in l])
    n_cell = sum(1 for l in md.splitlines()
                 if l.startswith("|") and l.count(TODO))
    stages = md.count(f"**舞台**：{TODO}")
    return {"台词行": n_line, "仍带 TODO 的台词行": n_todo_line,
            "词表/表格里的 TODO 格": n_cell, "待写舞台的语种": stages}


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="教学创意 → lessons/<id>/scene.md 结构草稿")
    ap.add_argument("--brief", required=True, help="brief JSON 路径，如 lessons/numbers/brief.json")
    ap.add_argument("--out", default=None, help="输出 md（缺省 = brief 同目录 scene.md）")
    ap.add_argument("--languages", default=None,
                    help="languages 目录（缺省 = feuille/languages 语种注册表）")
    ap.add_argument("--personas", default=None,
                    help="personas 目录（personas.json + intro-cards.json；缺省 = feuille/personas）")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的 scene.md")
    ap.add_argument("--print-plan", action="store_true", help="只打印结构计划，不落盘")
    ap.add_argument("--gaps", action="store_true", help="只统计现有 md 的欠账，不生成")
    args = ap.parse_args(argv)

    brief_path = Path(args.brief)
    brief = json.loads(brief_path.read_text("utf-8"))
    out = Path(args.out) if args.out else brief_path.parent / "scene.md"

    if args.gaps:
        if not out.exists():
            raise SystemExit(f"没有 {out}")
        g = gaps(out.read_text("utf-8"))
        print("欠账清单：" + "　".join(f"{k}={v}" for k, v in g.items()))
        return 0

    from .data import cards_doc, personas
    md = render(brief, personas(args.personas), cards_doc(args.personas),
                _langs(args.languages), _registries())

    if args.print_plan:
        print(md)
        return 0

    if out.exists() and not args.force:
        head = out.read_text("utf-8")[:2000]
        if DRAFT_MARK not in head:
            raise SystemExit(
                f"{out} 存在且不是草稿（缺 `{DRAFT_MARK}` 标记）——拒绝覆盖。\n"
                f"确实要重写请加 --force，或换个 --out。")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, "utf-8")

    g = gaps(md)
    print(f"已生成草稿 → {out}")
    print("欠账清单：" + "　".join(f"{k}={v}" for k, v in g.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
