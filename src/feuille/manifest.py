# -*- coding: utf-8 -*-
"""manifest.py — 发布清单（⑧）：文案稿解析 / 平台限制检查 / 标注回填 / 清单构建

合并自 explorateur/src/usine/publish.py（parse_copy / hook_shape / PLATFORMS）
与 yiyezhiqiu 的 build_publish_manifest.py + check_copy.py（素材存在性前置 /
len() 实测回填 / B 站上限）。两项目**独立收敛到同一文案体例**（T2），但解析器
各写一份、已经漂移（explorateur 的节头带 `· MM:SS`，yiyezhiqiu 不带）——
终态合成一份，**时长字段可选**，两边都吃。

体例（机器可解析，人写可 diff）：

    ### 01 · 英语 `en-US` · 00:52 [· ✅ 已发布]      ← 时长与已发布标记可选
    **标题**（20 字）                                  ← 括号标注会被 fill_annotations
    ```                                                  按 len() 实测回填
    四种语言聊颜色｜第01话 …
    ```
    **正文**（154 / 1000）
    ```
    …（小红书的末行是话题，会被解析进 topics）
    ```
    **话题**
    ```
    #语言学习 #多语言对比
    ```
    源文件：`build/scene/scene-colors_en-US.mp4`

铁律（纪律 7 的机制化）：
- **属性一律派生**：title_chars / body_chars / topic_count / hook 全部现算
  （explorateur 坑㉲：手标字数实测三支全错）。
- **素材存在性前置**：视频 / 封面**真实在盘**才算清单齐（发到一半发现文件缺失
  是最贵的失败方式；yiyezhiqiu 把它卡在 build 阶段）。
- hook 分类**可判定、可复现**，不做语义猜测：emoji × question 两个特征交叉
  （抖音=question、小红书=emoji+question——压成一维会把两个变量混进一个结论）。
"""
from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------- 平台约束
# 写成数据不是 if/else：加平台 = 加一行。B 站 80 是 yiyezhiqiu 手测口径。
PLATFORMS = {
    "douyin":      {"label": "抖音", "titleMax": 30, "bodyMax": 1000, "hook": "question"},
    "xiaohongshu": {"label": "小红书", "titleMax": 20, "bodyMax": 1000, "hook": "emoji+question"},
    "bilibili":    {"label": "哔哩哔哩", "titleMax": 80, "bodyMax": None, "hook": None},
    "zhihu":       {"label": "知乎", "titleMax": 100, "bodyMax": None, "hook": None,
                    "copy": None},          # 知乎是长文一篇，不走逐支模板
}

# ---------------------------------------------------------------- 文案解析

# 时长字段可选：explorateur 体例带 `· MM:SS [· ✅ 已发布]`，yiyezhiqiu 只到 `locale`。
_SEC = re.compile(r"^###\s+(\d+)\s*·\s*(\S+)\s*`([^`]+)`"
                  r"(?:\s*·\s*(\d\d):(\d\d))?(.*)$")
_FENCE = re.compile(r"\*\*(标题|正文|话题)\*\*[^\n]*\n```\n(.*?)\n```", re.S)
_TOPICS = re.compile(r"(?:^|\s)#([^\s#]+)", re.M)
_ANN = re.compile(r"^\*\*(标题|正文)\*\*（([^）]*)）$")
_SENT_END = re.compile(r"[。！？!?]")
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                 (0x2190, 0x21FF), (0xFE0F, 0xFE0F))


def _is_emoji(ch: str) -> bool:
    """码位区间判定。**不能写成 `ch in "🎰-🫿…"`**——那是「这个字符是不是字符串里
    某一个字」的成员测试，`🎨` 不等于任何单个字符，于是永远 False（坑㉲）。"""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _first_sentence(body: str) -> str:
    """首句（到第一个句读为止）。取首句不取首行：抖音正文一整行三句话，
    按行切会把问句钩子判成陈述句——判据必须对齐钩子的定义。"""
    text = next((ln.strip() for ln in body.split("\n") if ln.strip()), "")
    m = _SENT_END.search(text)
    return text[:m.end()] if m else text


def hook_shape(body: str) -> str:
    """正文首句形态：emoji × question 两特征交叉，可判定、可复现，不做语义猜测。"""
    first = _first_sentence(body)
    if not first:
        return "empty"
    emoji = _is_emoji(first[0])
    question = first.endswith(("？", "?"))
    if emoji and question:
        return "emoji+question"
    if question:
        return "question"
    if emoji:
        return "emoji"
    return "statement"


def taglist(tags: str) -> list[str]:
    return [t.strip() for t in re.split(r"\s+", (tags or "").replace("\n", " ")) if t.strip()]


def parse_copy(path) -> list[dict]:
    """`{plat}-copy.md` → 每支一条记录。**只抽取，不改写。**

    缺标题或正文块 = 体例被改了 → 当场报错（宁可拒解析，不做静默降级）。
    属性全派生：title_chars / body_chars / topics / hook 现算，不信任何手标。
    """
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"文案事实源不存在：{path}")
    lines = path.read_text("utf-8").split("\n")
    out: list[dict] = []
    i = 0
    while i < len(lines):
        m = _SEC.match(lines[i])
        if not m:
            i += 1
            continue
        order, lang, locale, mm, ss, tail = m.groups()
        cur = {
            "order": int(order), "lang": lang, "locale": locale,
            "durationSec": (int(mm) * 60 + int(ss)) if mm else None,
            "publishedMark": ("已发布" in (tail or "")),
            "source": None,
        }
        chunks: dict[str, str] = {}
        j = i + 1
        while j < len(lines) and not lines[j].startswith("### "):
            fm = _FENCE.match("\n".join(lines[j:]) + "\n")
            if fm and fm.group(1) not in chunks:
                chunks[fm.group(1)] = fm.group(2)
                j += fm.group(0).count("\n") + 1
                continue
            if lines[j].startswith("源文件："):
                cur["source"] = lines[j].split("`")[1] if "`" in lines[j] else None
            j += 1
        cur["title"] = chunks.get("标题")
        cur["body"] = chunks.get("正文")
        # 话题：小红书把话题放正文末行，抖音是独立 **话题** 块——同一真实目的
        #（发出去得有话题），两种来源都收进 topics。
        topics_src = chunks.get("话题") or cur["body"] or ""
        cur["topics"] = _TOPICS.findall(topics_src)
        if cur["title"] is None or cur["body"] is None:
            raise SystemExit(f"{path.name} 第 {order} 支缺标题或正文块（体例被改了？）")
        # 派生属性（纪律 7：一律现算）
        cur["title_chars"] = len(cur["title"])
        cur["body_chars"] = len(cur["body"])
        cur["topic_count"] = len(cur["topics"])
        cur["hook"] = hook_shape(cur["body"])
        out.append(cur)
        i = j
    return out


def check_copy(path, platform: str, *, expect: int | None = None) -> list[str]:
    """平台限制检查（问题列表；空 = 通过）。

    expect：该平台应有条数（缺支/多支都报——「12 条齐」本身是发布一致性的一部分）。
    """
    recs = parse_copy(path)
    meta = PLATFORMS[platform]
    problems: list[str] = []
    where = Path(path).name
    if expect is not None and len(recs) != expect:
        problems.append(f"{where}: 条数 {len(recs)} ≠ {expect}")
    for r in recs:
        tag = f"{where} {r['order']:02d} {r['lang']}"
        if r["title_chars"] > meta["titleMax"]:
            problems.append(f"{tag}: 标题 {r['title_chars']} > {meta['titleMax']} 字（会被截断）")
        if meta["bodyMax"] and r["body_chars"] > meta["bodyMax"]:
            problems.append(f"{tag}: 正文 {r['body_chars']} > {meta['bodyMax']}")
        if not r["topics"]:
            problems.append(f"{tag}: 无话题")
        if meta["hook"] and r["hook"] != meta["hook"]:
            problems.append(f"{tag}: 钩子 {r['hook']} ≠ 约定 {meta['hook']}")
    return problems


def fill_annotations(path, recs: list[dict]) -> int:
    """把 `**标题**（N 字）` / `**正文**（N / 1000）` 标注改成 len() 实测值。

    字数必须来自解析出的整块 `len()`——数代码块首行是错的（首行只是一句话，
    --fix 早期版本标过 17 而实际正文 117）。返回改写处数。
    """
    path = Path(path)
    by_order = {r["order"]: r for r in recs}
    lines = path.read_text("utf-8").split("\n")
    changed = 0
    cur = None
    for i, ln in enumerate(lines):
        m = _SEC.match(ln)
        if m:
            cur = by_order.get(int(m.group(1)))
            continue
        m = _ANN.match(ln)
        if not m or cur is None:
            continue
        kind = m.group(1)
        want = (f"**{kind}**（{cur['title_chars']} 字）" if kind == "标题"
                else f"**{kind}**（{cur['body_chars']} / 1000）")
        if ln != want:
            lines[i] = want
            changed += 1
    if changed:
        path.write_text("\n".join(lines), "utf-8")
    return changed


def build_manifest(plans: dict, out_path=None) -> tuple[dict, list[str]]:
    """文案 + 素材 → 结构化发布清单（素材存在性前置校验）。

    plans: {platform: {"copy": 路径, "entries": 解析记录或 None(现解析),
                       "video": fn(entry)->Path, "cover": fn(entry)->Path,
                       "tags": fn(entry)->list 或 None(用 topics)}}
    返回 (manifest, problems)。**素材不存在 = 清单不齐**：宁可现在报，
    不发到一半才发现文件缺失。out_path 给了就落盘（ensure_ascii=False, indent=1）。
    """
    manifest: dict[str, list] = {}
    problems: list[str] = []
    for plat, cfg in plans.items():
        recs = cfg.get("entries") or parse_copy(cfg["copy"])
        tasks = []
        for r in recs:
            video = Path(cfg["video"](r))
            cover = Path(cfg["cover"](r))
            tags = (cfg["tags"](r) if cfg.get("tags") else r["topics"])
            t = {"no": r["order"], "lang": r["lang"], "locale": r["locale"],
                 "title": r["title"], "body": r["body"], "tags": tags,
                 "video": str(video), "cover": str(cover)}
            if not r["title"]:
                problems.append(f"{plat} {r['lang']}: 标题为空")
            if not r["body"]:
                problems.append(f"{plat} {r['lang']}: 正文为空")
            if not tags:
                problems.append(f"{plat} {r['lang']}: 话题为空")
            if not video.exists():
                problems.append(f"{plat} {r['lang']}: 视频缺失 {video}")
            if not cover.exists():
                problems.append(f"{plat} {r['lang']}: 封面缺失 {cover}")
            tasks.append(t)
        manifest[plat] = tasks
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(__import__("json").dumps(
            manifest, ensure_ascii=False, indent=1), "utf-8")
    return manifest, problems
