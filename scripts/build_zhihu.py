#!/usr/bin/env python3
"""知乎专栏生成器：把颜色课的 14 语种 HTML 教学页改造为知乎原生 Markdown。

源页面 build/lesson/colors/index.html 依赖 tab 切换、TTS、侧栏索引等 JS 交互，
知乎编辑器不支持任何脚本。本脚本直接从单一事实源（lessons/colors/scene.json
+ lessons/colors/analysis/*.json）重建内容，产出：

  lessons/colors/publish/zhihu/00-主文-....md      导览：总表、语族地图、系列目录
  lessons/colors/publish/zhihu/01-汉语.md ... 14    每个语种一篇完整逐句解析
  lessons/colors/publish/zhihu/publish-plan.json    标题/字数/视频路径，供发布脚本消费

无损原则：网页版渲染的每一个字段都在这里落位；网页版漏渲染的 dialogue[].note
（每语种 3 条意象设计说明）在这里补回，不做任何抽取式精简。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "lessons" / "colors" / "scene.json"
ANALYSIS_DIR = ROOT / "lessons" / "colors" / "analysis"
OUT_DIR = ROOT / "lessons" / "colors" / "publish" / "zhihu"
AUDIO_DIR = ROOT / "build" / "scene" / "audio"
VIDEO_DIR = ROOT / "build" / "scene"

# 六色在网页版靠 CSS 色块呈现；知乎无 CSS，用 emoji 色点承载同一个语义。
COLOR_EMOJI = {
    "red": "🔴",
    "blue": "🔵",
    "green": "🟢",
    "yellow": "🟡",
    "black": "⚫",
    "white": "⚪",
}
COLOR_ZH = {
    "red": "红",
    "blue": "蓝",
    "green": "绿",
    "yellow": "黄",
    "black": "黑",
    "white": "白",
}
# 网页版 gut 栏的 role 标签
ROLE_ZH = {
    "open": "开场",
    "reply": "接话",
    "round": "六色问答",
    "summary": "小结",
    "bye": "道别",
}

# 声明式口吻修正表。源数据里的「本课」是编者自指的教师口吻，知乎文章要跟
# 读者平级，改成「本篇」——指代完全不变，只换人称。这不是删改内容：
# verify_zhihu_lossless.py 里有同一张表，验收时按表归一后再逐字段比对，
# 每次运行都会打印实际替换了多少处，可审计。
#
# 注意「上课」不在表里：ru-RU 文化注记的「学校这天不上课让孩子玩雪」是真实
# 文化事实，不是教师口吻，盲目替换会把内容改错。
DECLARED_SUBS = {
    "本课": "本篇",
}


def voice(s: str) -> str:
    for src, dst in DECLARED_SUBS.items():
        s = s.replace(src, dst)
    return s

# famtag 用的语系族分组（语系 › 语族），与网页版 .famtag 保持同一层级
FAMILY_LEVEL = 2


def load_scene() -> dict:
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


def load_analysis(locale: str) -> dict:
    return json.loads((ANALYSIS_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def family_tag(family: str) -> str:
    """截到「语系 › 语族」两级，与网页版 famtag 同层级。"""
    parts = [p.strip() for p in family.split("›") if p.strip()]
    return " › ".join(parts[:FAMILY_LEVEL])


def esc(text: str) -> str:
    """表格单元格里竖线会破表，替换成全角；同时套用声明式口吻修正。"""
    return voice((text or "").replace("|", "｜").strip())


def safe_name(label: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", label).strip()


# ---------------------------------------------------------------------------
# 知乎平台限制：服务端会剥掉整个阿拉伯 Unicode 区段（U+0600–U+06FF）
#
# 实测（2026-10-04，见 docs/zhihu-publish-playbook.md 坑 ⑰）：
# Markdown 导入编辑器时阿拉伯文完好，但**存草稿 / 发布时**整段被服务端过滤掉。
# 裸文本、行内代码、HTML 实体、加粗、引用块、表格单元格——全部无效；
# 相邻的希伯来文区段（U+0590–U+05FF）不受影响，可作对照。
#
# 因此受影响语种在正文顶部显式说明，把「原字去哪看」交代清楚，
# 正文其余部分照常输出（拉丁转写 / 译文 / 视频 都在）。
# ---------------------------------------------------------------------------
ARABIC_STRIPPED_LOCALES = {"ar-SA"}

ARABIC_STRIP_NOTE = (
    "> **排版说明**：知乎在保存时会过滤阿拉伯文字区段（U+0600–U+06FF），"
    "本页正文里的阿拉伯文原字会显示为空——这是平台限制，不是漏排。"
    "请以每行的**拉丁转写**与**译文**为准；阿拉伯文原字请看本篇的整段视频字幕，"
    "或项目内的交互版教学文档。"
)


def script_note(locale: str) -> str:
    """受平台字符过滤影响的语种返回顶部说明，其余返回空串。"""
    return ARABIC_STRIP_NOTE if locale in ARABIC_STRIPPED_LOCALES else ""


# ---------------------------------------------------------------------------
# 已发布文章的知乎 URL（声明式，生成器与验收脚本共用这一张表）
#
# 背景：Markdown 里的相对链接 `01-汉语.md` 粘到知乎后会被解析成
# `https://zhuanlan.zhihu.com/01-汉语.md` 这种必然 404 的地址。
# 文章发布后，草稿 ID 即文章 ID（发布 URL = 草稿 URL 去掉 /edit），
# 于是把真实地址登记进来，未登记的仍退回相对文件名。
# ---------------------------------------------------------------------------
INDEX_FILE = "00-主文-六个颜色词十四种语言.md"

PUBLISHED_URLS: dict[str, str] = {
    INDEX_FILE: "https://zhuanlan.zhihu.com/p/2089904878147598212",
    "01-汉语.md": "https://zhuanlan.zhihu.com/p/2089899068839539832",
    "02-粤语.md": "https://zhuanlan.zhihu.com/p/2089899526173749273",
    "03-英语.md": "https://zhuanlan.zhihu.com/p/2089899733133412306",
    "04-德语.md": "https://zhuanlan.zhihu.com/p/2089899958791050611",
    "05-法语.md": "https://zhuanlan.zhihu.com/p/2089900169722599335",
    "06-西班牙语.md": "https://zhuanlan.zhihu.com/p/2089900377936228772",
    "07-意大利语.md": "https://zhuanlan.zhihu.com/p/2089900584673530952",
    "08-俄语.md": "https://zhuanlan.zhihu.com/p/2089900801372206522",
    "09-希腊语.md": "https://zhuanlan.zhihu.com/p/2089901022126855041",
    "10-印地语.md": "https://zhuanlan.zhihu.com/p/2089901244609468401",
    "11-阿拉伯语.md": "https://zhuanlan.zhihu.com/p/2089901474784592319",
    "12-希伯来语.md": "https://zhuanlan.zhihu.com/p/2089901723724821080",
    "13-日语.md": "https://zhuanlan.zhihu.com/p/2089897158682195415",
    "14-韩语.md": "https://zhuanlan.zhihu.com/p/2089901976901493374",
}


def article_url(fname: str) -> str:
    """已登记真实 URL 就用它，否则退回相对文件名（未发布阶段的诚实占位）。"""
    return PUBLISHED_URLS.get(fname, fname)


def device_style(prop: dict) -> str:
    """网页版 .meta「装置样式」：style / shape　井位 WxH，shape 恒显示。"""
    d = prop.get("device") or {}
    label = " / ".join(b for b in (d.get("style", ""), d.get("shape", "")) if b)
    if d.get("cellW") and d.get("cellH"):
        label += f"　井位 {d['cellW']}×{d['cellH']}"
    return label


# ---------------------------------------------------------------------------
# 分语种篇
# ---------------------------------------------------------------------------


def render_locale(
    scene: dict,
    lc: str,
    scene_loc: dict,
    analysis: dict,
    order: int,
    total: int,
    family_no: int,
) -> str:
    dlg = scene_loc["dialogue"]
    out: list[str] = []
    a = out.append

    label = analysis["langLabel"]
    rtl = lc in scene.get("rtlLocales", [])
    a(f"# 颜色 · 第 {order} 话：{label}（{lc}）")
    a("")
    a(
        f"> **{scene['title']}** 系列 · {order}/{total}　"
        f"语族：{esc(analysis['family'])}　"
        f"6 色 × {len(dlg)} 行　整段音频约 {duration_of(lc):.1f} 秒"
        + ("　**RTL 从右往左书写**" if rtl else "")
    )
    a("")
    a(
        "这一篇是同一场对话在 "
        f"**{label}** 里的完整版本：{len(dlg)} 行逐句对照，"
        "每行给出原文、注音、译文、舞台提示，以及语法 / 词法 / 文化三栏解析。"
    )
    a("")
    note = script_note(lc)
    if note:
        a(note)
        a("")

    # --- 人物与舞台 ---
    a("## 人物与舞台")
    a("")
    a("| 项 | 内容 |")
    a("| --- | --- |")
    a(f"| 序号 | 第 {order} / {total} 话（语系族 {family_no}） |")
    a(f"| A 活泼先问 | {esc(scene_loc['aName'])} |")
    a(f"| B 沉稳后答 | {esc(scene_loc['bName'])} |")
    a(f"| 舞台 | {esc(scene_loc['stage'])} |")
    a(f"| 舞台装置 | {esc((scene_loc.get('prop') or {}).get('label', ''))} |")
    a(f"| 装置样式 | {esc(device_style(scene_loc.get('prop') or {}))} |")
    a(f"| 出场场景 | {esc('、'.join((scene_loc.get('prop') or {}).get('scenes', [])))} |")
    a(f"| 语族定位 | {esc(analysis['family'])} |")
    a("")

    # --- 三段背景 ---
    a("## 语族背景与舞台设定")
    a("")
    a(f"**家族背景**　{voice(analysis['familyNote'])}")
    a("")
    a(f"**书写特点**　{voice(analysis['scriptNote'])}")
    a("")
    a(f"**舞台文化**　{voice(analysis['stageCulture'])}")
    a("")
    desc = (scene_loc.get("prop") or {}).get("desc", "")
    if desc:
        a(f"**舞台画面**　{voice(desc)}")
        a("")

    # --- 六色词表 ---
    a("## 六色词表")
    a("")
    a("| 色 | 本篇用词 | 注音 | 语形 |")
    a("| --- | --- | --- | --- |")
    for w in scene["tokenWords"][lc]:
        forms = " / ".join(w.get("forms") or [w["word"]])
        a(
            f"| {COLOR_EMOJI[w['key']]} {COLOR_ZH[w['key']]} "
            f"| {esc(w['word'])} | {esc(w.get('romanization', '')) or '—'} | {esc(forms)} |"
        )
    a("")

    if scene_loc.get("notes"):
        a("**创作注记 · 源剧本原文**")
        a("")
        a(voice(scene_loc["notes"]))
        a("")

    # --- 视频 ---
    # 只留一句人话说明；mp4 由发布时嵌入正文，构建文件名留在 publish-plan.json，
    # 不写进正文，免得发布后读者看到一串工程路径。
    a("## 整段视频")
    a("")
    a(f"本篇 {len(dlg)} 行连读视频（{label}，约 {duration_of(lc):.1f} 秒）。")
    a("")

    # --- 逐句解析 ---
    counts: dict[str, int] = {}
    for d in dlg:
        counts[d["role"]] = counts.get(d["role"], 0) + 1
    breakdown = " · ".join(f"{ROLE_ZH[r]} {counts[r]}" for r in ROLE_ZH if r in counts)
    a(f"## 逐句脚本与解析（{len(dlg)} 行）")
    a("")
    a(f"{len(dlg)} 行　{breakdown}")
    a("")

    ana = {l["i"]: l for l in analysis["lines"]}
    for d in dlg:
        i = d["i"]
        who = scene_loc["aName"] if d["speaker"] == "A" else scene_loc["bName"]
        head = f"### {i:02d} ｜ {ROLE_ZH[d['role']]} ｜ {d['speaker']}（{esc(who)}）"
        if d.get("tokenKey"):
            head += f" {COLOR_EMOJI[d['tokenKey']]} {esc(d['tokenWord'] or COLOR_ZH[d['tokenKey']])}"
        a(head)
        a("")
        a(f"> {esc(d['text'])}")
        a("")

        bits = []
        if d.get("romanization"):
            bits.append(f"注音 `{voice(d['romanization'])}`")
        if d.get("gloss"):
            bits.append(f"译 {voice(d['gloss'])}")
        if (d.get("bubble") or {}).get("text"):
            bits.append(f"气泡 {voice(d['bubble']['text'])}")
        if (d.get("gesture") or {}).get("word"):
            bits.append(f"手势 {voice(d['gesture']['word'])}")
        if bits:
            a("　·　".join(bits))
            a("")

        if d.get("note"):
            a(f"> 🎬 **舞台提示**　{voice(d['note'])}")
            a("")

        al = ana.get(i, {})
        for label_txt, key in (("语法", "grammar"), ("词法", "morph"), ("文化", "culture")):
            if al.get(key):
                a(f"- **{label_txt}**　{voice(al[key])}")
        a("")

    if lc in scene.get("rtlLocales", []):
        a("---")
        a("")
        a(
            "> 排版说明：本篇原文为从右往左书写（RTL）。"
            "知乎编辑器不支持双向排版控制，读者若看到标点位置异常，属预期现象，"
            "以括号内的译文为准。"
        )
        a("")

    a("---")
    a("")
    a(f"← 返回[总目录]({article_url(INDEX_FILE)})")
    return "\n".join(out).rstrip() + "\n"


def duration_of(lc: str) -> float:
    p = AUDIO_DIR / f"scene-colors_{lc}.timeline.json"
    if not p.exists():
        return 0.0
    return float(json.loads(p.read_text(encoding="utf-8")).get("duration", 0.0))


# ---------------------------------------------------------------------------
# 主文导览
# ---------------------------------------------------------------------------


def render_index(
    scene: dict,
    analyses: dict[str, dict],
    order_of: dict[str, int],
    total: int,
) -> str:
    out: list[str] = []
    a = out.append
    total_dur = sum(duration_of(lc) for lc in order_of)

    a(f"# 六个颜色词，十四种语言：{scene['title']}")
    a("")
    a(
        f"> **一场对话，14 种语言，6 个颜色，{len(scene['locales']['zh-CN']['dialogue'])} 轮问答。**"
        f"全套整段朗读约 {int(total_dur // 60)} 分 {total_dur % 60:.1f} 秒。"
    )
    a("")
    a(
        "这套东西是怎么做出来的，写在这里。同一场「放学后的美术教室」对话，"
        "被写进 14 种语言，每种语言 17 行，每一行都配语法 / 词法 / 文化三栏解析。"
        "本篇是总览与索引，14 篇分语种正文见文末目录。"
    )
    a("")

    # --- 规模 ---
    a("## 一、这套内容有多大")
    a("")
    a("| 维度 | 数值 |")
    a("| --- | --- |")
    a(f"| 语种 | {total} |")
    a(f"| 颜色 | {len(scene['tokenOrder'])}（{'、'.join(COLOR_ZH[k] for k in scene['tokenOrder'])}） |")
    a(f"| 每语种行数 | {len(scene['locales']['zh-CN']['dialogue'])} |")
    a(f"| 解析条目 | {total * len(scene['locales']['zh-CN']['dialogue'])} 行 × 3 栏 |")
    a(f"| 整段朗读总时长 | 约 {int(total_dur // 60)} 分 {total_dur % 60:.1f} 秒 |")
    a("")

    # --- 为什么是颜色 ---
    a("## 二、为什么选「颜色」而不是别的词")
    a("")
    a(
        "颜色词是少数几个能同时踩中四条语言学考点的词类："
    )
    a("")
    a(
        "1. **语序敏感**。汉语靠「说到 X，你会想到什么」的话题结构，"
        "不写条件从句也能把问题抛出去；这在多数语言里必须换成从句。"
    )
    a(
        "2. **形态分化**。俄语的 красный 与 красивый 同根，"
        "希腊语的 μπλε 是法语 bleu 的借词而白色 άσπρο 是原生词——"
        "颜色词最能照出一种语言的借词层。"
    )
    a(
        "3. **语体分层**。意大利语必须在 blu 与 azzurro 之间选（国家队称 Gli Azzurri），"
        "日语的青信号让「あお」同时覆盖蓝绿两域。")
    a(
        "4. **文化负载**。同一杯茶，俄语叫 чёрный чай 而汉语叫红茶；"
        "韩语有 오방색 五方色；粤语把红包叫利是。"
    )
    a("")
    a(
        "再加上颜色天然有画面，"
        "所以舞台设定成美术教室、长桌上一只六格调色盘：每轮问答弹起一格颜料，"
        "六个格子刚好对应六个颜色词，抽象词被画笔激活成实物。"
    )
    a("")

    # --- 核心矩阵 ---
    a("## 三、六色词 × 十四语种总表")
    a("")
    a(
        "这张表是整套内容的骨架。同一列自上而下读，"
        "看的是同一个颜色在不同语言里的词形、注音和语源层次。"
    )
    a("")
    a("| # | 语种 | " + " | ".join(
        f"{COLOR_EMOJI[k]} {COLOR_ZH[k]}" for k in scene["tokenOrder"]
    ) + " |")
    a("| --- | --- |" + " --- |" * len(scene["tokenOrder"]))
    for lc in order_of:
        n = order_of[lc]
        cells = []
        words = {w["key"]: w for w in scene["tokenWords"][lc]}
        for k in scene["tokenOrder"]:
            w = words.get(k, {})
            r = (w.get("romanization") or "").strip()
            cells.append(esc(f"{w.get('word', '')} {r}".strip()))
        label = analyses[lc]["langLabel"]
        a(f"| {n:02d} | {esc(label)} | " + " | ".join(cells) + " |")
    a("")
    a(
        "> 注音体例因语言而异：日语、韩语用罗马字，阿拉伯语、希伯来语、"
        "俄语、希腊语、印地语按各自教学惯例转写，"
        "印欧语系各语言用国际音标或习惯拼写，粤语用 Jyutping。"
    )
    a("")
    a(
        "> ⚠️ **第 11 行（阿拉伯语）的阿拉伯文原字会显示为空**："
        "知乎在保存时会过滤阿拉伯文字区段（U+0600–U+06FF），"
        "该行只剩拉丁转写。阿拉伯文原字见[第 11 话正文]"
        f"({article_url('11-阿拉伯语.md')})的整段视频字幕，"
        "或项目内的交互版教学文档。希伯来文（第 12 行）不受此限制。"
    )
    a("")

    # --- 语族地图 ---
    a("## 四、语族地图")
    a("")
    a("14 个语种分属 9 个语系族。层级越深，语法的历史包袱越重。")
    a("")
    a("| 语系族 | 语种 | 语族细分 |")
    a("| --- | --- | --- |")
    fams: dict[str, list[str]] = {}
    for lc in order_of:
        fams.setdefault(family_tag(analyses[lc]["family"]), []).append(lc)
    for i, (fam, members) in enumerate(fams.items(), 1):
        names = "、".join(analyses[m]["langLabel"] for m in members)
        # 只列语系族之后的细分，语系族本身已经是第一列，避免整列重复前缀
        sub = "；".join(
            " › ".join(p.strip() for p in analyses[m]["family"].split("›")[2:] if p.strip())
            for m in members
        )
        a(f"| {i:02d} {fam} | {names} | {esc(sub) or '—'} |")
    a("")

    # --- 语体 ---
    a("## 五、语体设计：关系写在词尾里")
    a("")
    a(
        "A 是活泼先问的一方，B 是沉稳后答的一方。这组关系不靠剧情说明，"
        "而是直接写进每种语言的词尾与敬语系统里。"
    )
    a("")
    sl = scene.get("speechLevels", {})
    if sl:
        a("| 语种 | A 用 | B 用 | 说明 |")
        a("| --- | --- | --- | --- |")
        for lc, v in sl.items():
            a(
                f"| {esc(analyses[lc]['langLabel'])} "
                f"| {esc(v.get('levelA', ''))} | {esc(v.get('levelB', ''))} "
                f"| {esc(v.get('note', ''))} |"
            )
        a("")
    a(
        "韩语这一组是全套里最戏剧化的：도윤全程用反语体（반말），"
        "서연全程用敬语体（해요体），"
        "「语体差本身就是两人的关系戏」——"
        "这不是风格选择，是剧情。"
    )
    a("")
    a(
        "阿拉伯语与希伯来语则走了另一条路：问句必须按**听者性别**变位，"
        "所以脚本层要求每个颜色配双套问句（见第七节）。"
    )
    a("")

    # --- 剧本骨架 ---
    a("## 六、17 行的剧本骨架")
    a("")
    dlg = scene["locales"]["zh-CN"]["dialogue"]
    counts: dict[str, int] = {}
    for d in dlg:
        counts[d["role"]] = counts.get(d["role"], 0) + 1
    a("| 段落 | 行数 | 作用 |")
    a("| --- | --- | --- |")
    purpose = {
        "open": "A 抛出话题，把对方拦下",
        "reply": "B 接住话头，问规则",
        "round": "A 问 B 答，六色逐轮交替",
        "summary": "收束，把颜色拉回语言本身",
        "bye": "维持同伴口吻收尾",
    }
    for r in ROLE_ZH:
        if r in counts:
            a(f"| {ROLE_ZH[r]} | {counts[r]} | {purpose[r]} |")
    a(f"| **合计** | **{len(dlg)}** | |")
    a("")

    # --- 工程约束 ---
    a("## 七、两处非直觉的工程约束")
    a("")
    a(
        "这些对话不是先写中文再翻译，而是**14 种语言各自独立创作**，"
        "再由脚本层统一校验。校验里最硬的三条："
    )
    a("")
    a(
        "**① 脚本层强制规则。** 每个语种在 `scene.json` 里声明自己的语体与变位要求。"
        "韩语要求 B 全线해요体（`요` 标记），"
        "阿拉伯语要求按听者性别双套问句"
        "（对 ليلى 用 تفكرين、对 عمر 用 تفكر），"
        "希伯来语要求按说话者×听者双方性别各变位（אומרת/אומר、חושב/חושבת）。"
        "违反任一条，验收直接判 FAIL。"
    )
    a("")
    a("**② 补写的蓝色轮。** 阿拉伯语与希伯来语的原剧本缺蓝色，导致全片只演出 5 轮：")
    a("")
    for lc in ("ar-SA", "he-IL"):
        note = (scene["locales"][lc].get("notes") or "")
        if "补写" in note:
            tail = note.split("**蓝色一轮为补写**")[-1].strip()
            # 去掉补写段落自带的「（原剧本缺蓝色致全片只 5 轮）：」前缀——
            # 上一句已经交代过原因，留着就是同一句话说两遍
            tail = re.sub(r"^（[^）]*）[：:]?\s*", "", tail)
            a(f"- **{analyses[lc]['langLabel']}**：{tail.rstrip('。；;')}")
    a("")
    a(
        "补写后要求「六色零遗漏零重复、A 问三 / B 问三、一来一往逐幕交替成立」，"
        "出场次序定为 红-绿-黄-黑-白-蓝，蓝置于末轮以免打乱原有台词与问方。"
    )
    a("")
    a("**③ 时长预算。** 每个语种整段朗读必须落在 "
      f"{scene['durationBudget'][0]:g}–{scene['durationBudget'][1]:g} 秒区间内。")
    a("")

    # --- 目录 ---
    #
    # 这里刻意不用表格：实测知乎的 Markdown 导入器会丢掉**表格单元格里的链接**
    # （导入后编辑器内一个 <a> 都没有，链接连文字都只剩纯文本）。
    # 独立成行的段落链接才能变成真链接，所以目录改成表外列表。
    a("## 八、系列目录")
    a("")
    a("每篇都是完整的 17 行逐句解析，可独立阅读，点标题直达。")
    a("")
    for lc in order_of:
        an = analyses[lc]
        fname = f"{order_of[lc]:02d}-{safe_name(an['langLabel'])}.md"
        a(
            f"{order_of[lc]:02d}. "
            f"[颜色 · 第 {order_of[lc]} 话：{an['langLabel']}（{lc}）]"
            f"({article_url(fname)})"
            f"　{esc(family_tag(an['family']))}"
            f"　{duration_of(lc):.0f} 秒"
            f"　{len(scene['locales'][lc]['dialogue'])} 行 × 3 栏"
        )
        a("")
    a("---")
    a("")
    a(
        "交互版（语种切换、逐行朗读、侧栏索引）见项目内 "
        "`build/lesson/colors/index.html`。"
    )
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------


def render_readme(plan: list[dict]) -> str:
    out: list[str] = []
    a = out.append
    a("# 知乎发布交接说明")
    a("")
    a(
        "本目录是 `build/lesson/colors/index.html` 的知乎改造产物。"
        "内容从单一事实源重建，**逐字段无损**（见下方验收）。"
    )
    a("")
    a("## 为什么需要人工粘贴")
    a("")
    a(
        "知乎编辑器是 Draft.js 富文本，它把 Markdown 转成排版好的正文"
        "**只在真实粘贴（paste）事件时触发**。程序化写入文本不会触发这个转换，"
        "结果会是一屏字面的 `##`、`**`、`|` 符号，而不是标题、加粗和表格。"
    )
    a("")
    a("因此每篇的发布动作是：")
    a("")
    a("1. 复制该篇的 `.md` 全文（Ctrl+A / Ctrl+C）。")
    a("2. 知乎编辑器标题栏粘贴/输入标题，正文区 **Ctrl+V** 粘贴全文 → 自动转成排版。")
    a("3. 光标移到「## 整段视频」那一段下方，点工具栏「视频」上传对应 mp4。")
    a("4. 检查「添加封面」，再点「发布」。")
    a("")
    a("## 逐篇对照表")
    a("")
    a("| 序 | 标题（直接粘进标题栏） | 正文文件 | 视频文件 | 大小 |")
    a("| --- | --- | --- | --- | --- |")
    for p in plan:
        vid = p["video"] or "—"
        mb = f"{p['videoBytes'] / 1048576:.1f} MB" if p["videoBytes"] else "—"
        a(f"| {p['order']:02d} | {p['title']} | `{p['file']}` | `{vid}` | {mb} |")
    a("")
    a("视频源目录：`build/scene/`")
    a("")
    a("## 验收")
    a("")
    a("```powershell")
    a(".\\.venv\\Scripts\\python.exe .\\scripts\\verify_zhihu_lossless.py")
    a("```")
    a("")
    a(
        "该脚本把源 HTML 逐面板、逐行、逐字段拆成必须出现的字符串清单，"
        "再去产物里逐条比对；并先用**故意删改的坏产物**证明这个检查会 FAIL，"
        "避免检查空转。"
    )
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    scene = load_scene()
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # 网页版 tab 顺序（剧本创作顺序），不是 scene.json 的键序
    tab_order = [
        "zh-CN", "zh-HK", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT",
        "ru-RU", "el-GR", "hi-IN", "ar-SA", "he-IL", "ja-JP", "ko-KR",
    ]
    order_of = {lc: i + 1 for i, lc in enumerate(tab_order)}
    analyses = {lc: load_analysis(lc) for lc in tab_order}

    # 语系族编号：按首次出现顺序，和网页版 famtag 一致
    fam_order: dict[str, int] = {}
    fam_no: dict[str, int] = {}
    for lc in tab_order:
        fam = family_tag(analyses[lc]["family"])
        if fam not in fam_order:
            fam_order[fam] = len(fam_order) + 1
        fam_no[lc] = fam_order[fam]

    plan = []
    total = len(tab_order)

    for lc in tab_order:
        md = render_locale(
            scene, lc, scene["locales"][lc], analyses[lc], order_of[lc], total, fam_no[lc]
        )
        an = analyses[lc]
        fname = f"{order_of[lc]:02d}-{safe_name(an['langLabel'])}.md"
        (out_dir / fname).write_text(md, encoding="utf-8")
        video = VIDEO_DIR / f"scene-colors_{lc}.mp4"
        plan.append(
            {
                "order": order_of[lc],
                "locale": lc,
                "langLabel": an["langLabel"],
                "family": an["family"],
                "file": fname,
                "title": f"颜色 · 第 {order_of[lc]} 话：{an['langLabel']}（{lc}）"
                f"—— 17 行逐句语法词法文化解析",
                "chars": len(md),
                "lines": len(scene["locales"][lc]["dialogue"]),
                "duration": round(duration_of(lc), 2),
                "video": video.name if video.exists() else None,
                "videoBytes": video.stat().st_size if video.exists() else None,
                "rtl": lc in scene.get("rtlLocales", []),
            }
        )

    idx = render_index(scene, analyses, order_of, total)
    idx_name = "00-主文-六个颜色词十四种语言.md"
    (out_dir / idx_name).write_text(idx, encoding="utf-8")

    plan.insert(
        0,
        {
            "order": 0,
            "locale": None,
            "langLabel": "主文导览",
            "family": None,
            "file": idx_name,
            "title": "六个颜色词，十四种语言：一场放学后的美术教室对话"
                     "（6 色 × 17 行 × 14 语种全套解析）",
            "chars": len(idx),
            "lines": 0,
            "duration": None,
            "video": None,
            "videoBytes": None,
            "rtl": False,
        },
    )

    (out_dir / "publish-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "README-发布交接.md").write_text(render_readme(plan), encoding="utf-8")

    print(f"输出目录: {out_dir}")
    print(f"{'序':>3}  {'语种':<10} {'字数':>7}  {'时长':>7}  文件")
    for p in plan:
        dur = f"{p['duration']:.1f}s" if p["duration"] else "-"
        print(f"{p['order']:>3}  {p['langLabel']:<10} {p['chars']:>7}  {dur:>7}  {p['file']}")
    print(f"\n合计 {len(plan)} 篇，{sum(p['chars'] for p in plan):,} 字符")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
