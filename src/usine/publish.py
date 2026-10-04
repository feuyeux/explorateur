#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish.py — 发布侧台账 + 指标回流分析（P2-5）

**它解决什么**：发布侧此前完全是散文——`docs/publish-playbook.md` §8 手写「已发布台账」，
`lessons/colors/publish/zhihu/_draft-log.json` 另记一份知乎的。两份格式不同、互不校验，
而且**没有任何平台效果数据**，所以「哪支文案有效」这件事在项目里根本没有事实基础。

本模块把发布侧变成一条可被门禁判定的链：

```
lessons/<id>/publish/<platform>-copy.md   文案事实源（散文，人写的）
                │  parse_copy()  机械抽取，不改写
                ▼
publish/ledger.json                       ★ 机器可读台账（属性自动派生 + 平台结果 + 指标）
                │  check()       判据（引用完整性 / 指标取值域 / 悬空挂载 / 标题上限）
                ▼
             analyze()         按维度分组排序 → 结论
```

**属性一律派生，绝不手抄。** 字数、话题数、钩子形态、视频时长、书写系统、装置形态
全部从既有的事实源算出来。理由是实测过的（坑㉲）：小红书 copy 里手标的正文字数
**三支全错**（+4 / +4 / −11 字），抄它就是把错的当真的。

**没有平台数据时，台账里的 `metrics` 就是 null，分析器必须明说「无数据」而不是
输出一个空洞的排名。** 本项目在 2026-10-05 写这个模块时手里一个真实数字都没有——
不编。编出来的数据比没有数据更坏：它会让后续每一次「结论」都建立在虚构的样本上。

**样本量纪律**：`MIN_GROUP = 5`。分组样本不足时只报「样本不足」，不排名。
一条数据排出来的第一名是最容易骗人的结论形态。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from usine import ROOT

LEDGER_PATH = ROOT / "publish" / "ledger.json"

# 台账 schema 版本。**字段是 schema 的一部分**：键格式从 `lesson/locale/platform`
# 变过（见坑㉳），升版本让旧文件显式失效，不靠猜。
VERSION = 1

# ---------------------------------------------------------------- 平台约束
# 来自 `docs/publish-playbook.md` §2「硬性限制对照」，**机器可读的那部分**。
# 写成数据而不是 if/else：下一个平台就是加一行，不是改一段逻辑。
PLATFORMS = {
    "douyin": {
        "label": "抖音",
        "copy": "douyin-copy.md",
        "titleMax": 30,
        "bodyMax": 1000,
    },
    "xiaohongshu": {
        "label": "小红书",
        "copy": "xiaohongshu-copy.md",
        "titleMax": 20,
        "bodyMax": 1000,
    },
    "zhihu": {
        "label": "知乎",
        "copy": None,                       # 知乎是「一课一篇长文」，不走 14 支模板
        "titleMax": 100,
        "bodyMax": None,
    },
}

# 平台后台能直接给出的**计数型**指标：非负整数，平台不会给出负的播放量。
COUNT_METRICS = ("views", "likes", "comments", "collects", "shares", "follows")
# **比率型**指标：平台可能给「12.3%」或「0.123」，入库一律折成 0–1。
# 判据取「这数是不是个比率」的真实目的，不取「字段存不存在」。
RATE_METRICS = ("completionRate", "interactionRate")
ALL_METRICS = COUNT_METRICS + RATE_METRICS

# 分组样本不足这个数 → 不下结论。5 是「至少能看出方向、还看不出全部由个别值决定」的
# 最小规模；低于它就只报样本数与原始值。
MIN_GROUP = 5


# ---------------------------------------------------------------- 文案解析
_SEC = re.compile(r"^###\s+(\d\d)\s*·\s*(\S+)\s*`([^`]+)`\s*·\s*(\d\d):(\d\d)(.*)$")
_FENCE = re.compile(r"\*\*(标题|正文|话题)\*\*[^\n]*\n```\n(.*?)\n```", re.S)
_TOPICS = re.compile(r"(?:^|\s)#([^\s#]+)", re.M)


def parse_copy(path: Path) -> list[dict]:
    """`*-copy.md` → 每支一条记录。**只抽取，不改写。**

    体例（两份文件同构，机器可解析）：
        ### 01 · 英语 `en-US` · 00:52 [· ✅ 已发布]
        **标题**（20 字）
        ```
        …标题…
        ```
        **正文**（154 / 1000）
        ```
        …正文…（末行是话题）
        ```
        源文件：`build/scene/scene-colors_en-US.mp4`
    """
    if not path.exists():
        raise SystemExit(f"文案事实源不存在：{path}")
    text = path.read_text("utf-8")
    lines = text.split("\n")

    out: list[dict] = []
    cur: dict | None = None
    i = 0
    while i < len(lines):
        m = _SEC.match(lines[i])
        if not m:
            i += 1
            continue
        order, lang, locale, mm, ss, tail = m.groups()
        cur = {
            "order": int(order),
            "lang": lang,
            "locale": locale,
            "durationSec": int(mm) * 60 + int(ss),
            "publishedMark": ("已发布" in tail),
            "source": None,
        }
        # 往后吃到下一个 ### 为止，抽三个代码块 + 源文件行
        j = i + 1
        chunks: dict[str, str] = {}
        while j < len(lines) and not lines[j].startswith("### "):
            fm = _FENCE.match("\n".join(lines[j:]) + "\n")
            if fm and fm.group(1) not in chunks:
                chunks[fm.group(1)] = fm.group(2)
                # 代码块结束于 ```，从其后继续
                j += fm.group(0).count("\n") + 1
                continue
            if lines[j].startswith("源文件："):
                cur["source"] = lines[j].split("`")[1] if "`" in lines[j] else None
            j += 1
        cur["title"] = chunks.get("标题")
        cur["body"] = chunks.get("正文")
        # 话题：小红书版把话题放在正文末行，抖音版是独立的 **话题** 块
        topics_src = chunks.get("话题") or cur["body"] or ""
        cur["topics"] = _TOPICS.findall(topics_src)
        if cur["title"] is None or cur["body"] is None:
            raise SystemExit(f"{path.name} 第 {order} 支缺标题或正文块（体例被改了？）")
        out.append(cur)
        i = j
    return out


_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                 (0x2190, 0x21FF), (0xFE0F, 0xFE0F))
_SENT_END = re.compile(r"[。！？!?]")


def _is_emoji(ch: str) -> bool:
    """码位区间判定。**不能写成 `ch in "🎰-🫿…"`**——那是「这个字符是不是字符串里
    某一个字」的成员测试，`🎨` 不等于任何单个字符，于是永远 False（坑㉲）。
    """
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _first_sentence(body: str) -> str:
    """首句（到第一个句读为止，含句读）。

    取**首句**而不是首行：抖音正文是一整行三句话（「说到颜色，你会想到什么？……
    从红色一路问到白色（00:52）。」），按行切会把一个问句钩子判成陈述句。
    钩子的定义就是开头那一句，判据必须对齐这个定义。
    """
    text = next((ln.strip() for ln in body.split("\n") if ln.strip()), "")
    m = _SENT_END.search(text)
    return text[:m.end()] if m else text


def hook_shape(body: str) -> str:
    """正文首句的形态。**可判定、可复现的分类，不做语义猜测。**

    两个可观察特征交叉：`emoji`（首字是不是 emoji）与 `question`（首句是不是问句）。
    交叉而非二选一，因为两种特征组合都是真实存在的文案风格：
    抖音是「问句、无 emoji」，小红书是「问句 + emoji 开场」——把后者压成 `emoji`
    就丢掉了「它同时是问句」这条信息，分析时会得出「emoji 钩子更好」这种
    混着两个变量的结论。
    """
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


# ---------------------------------------------------------------- 台账组装
def _locale_unit(scene_id: str, locale: str) -> dict:
    """`lessons/<id>/scene.json` 里该语种的块。读不到 → 空 dict（不抛）。

    这里刻意**不抛**：派生不出来就留 None，让门禁去报「属性缺了」，
    而不是让建账整个失败——派生是锦上添花，账本本身不该因为它崩。
    """
    f = ROOT / "lessons" / scene_id / "scene.json"
    if not f.exists():
        return {}
    try:
        doc = json.loads(f.read_text("utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}
    unit = (doc.get("locales") or {}).get(locale)
    return unit if isinstance(unit, dict) else {}


def _dir_of(locale: str) -> str | None:
    """书写方向，取自语种目录（`ltr` / `rtl`）——不是猜的，是 `languages/` 里的声明。"""
    f = ROOT / "languages" / locale / "manifest.json"
    if not f.exists():
        return None
    return json.loads(f.read_text("utf-8")).get("dir")


def _device_of(scene_id: str, locale: str) -> str | None:
    """该课该语种的舞台装置样式（`chalkboard` / `lanterns` …），来自 §0.2 声明。

    这正是「创意」的可量化维度之一：同一句话，用小黑板还是灯笼拍，
    是两门课在平台上最可能被观众感知到的差别。
    """
    return (((_locale_unit(scene_id, locale).get("prop") or {}).get("device")) or {}).get("style")


def _chip_of(scene_id: str) -> str | None:
    """token 两型：`色片`（`#hex`）/ `字牌`（`"文本"`）——chip 是填色块还是贴文字。

    colors 用色片、numbers 用字牌，这是 P1 新课验收刻意压出的差异，
    也是「同一套渲染管线、换一种教学装置」的可对照变量。
    """
    f = ROOT / "lessons" / scene_id / "scene.json"
    if not f.exists():
        return None
    try:
        tokens = json.loads(f.read_text("utf-8")).get("tokens") or {}
    except Exception:                                       # noqa: BLE001
        return None
    vals = [str(v) for v in tokens.values() if isinstance(v, str) and v]
    if not vals:
        return None
    hexes = sum(v.startswith("#") for v in vals)
    if hexes == len(vals):
        return "色片"
    if hexes == 0:
        return "字牌"
    return f"混合({hexes}/{len(vals)})"


def _lines_of(scene_id: str, locale: str) -> int | None:
    """台词行数（分析维度：同样的时长塞多少行，节奏完全不同）。"""
    d = _locale_unit(scene_id, locale).get("dialogue")
    return len(d) if isinstance(d, list) else None


def build(lessons=("colors",)) -> dict:
    """从各课的 copy 事实源组装台账。**产物属性全部派生，不手抄。**

    平台结果（url / postId / publishedAt）**不在这里编**——它们来自真实发布，
    由人手写进 `publish/results.json`（见 `merge_results`）。本函数只负责「该有哪些
    记录、每条记录该有哪些属性」。
    """
    entries: dict[str, dict] = {}
    for scene_id in lessons:
        for pid, meta in PLATFORMS.items():
            if not meta["copy"]:
                continue
            src = ROOT / "lessons" / scene_id / "publish" / meta["copy"]
            if not src.exists():
                continue
            for rec in parse_copy(src):
                key = f"{scene_id}/{rec['locale']}/{pid}"
                body = rec["body"]
                entries[key] = {
                    "key": key,
                    "lesson": scene_id,
                    "locale": rec["locale"],
                    "platform": pid,
                    "order": rec["order"],
                    # ── 素材与教学属性（引用既有事实源，不复制）
                    "video": rec["source"],
                    "durationSec": rec["durationSec"],
                    "lineCount": _lines_of(scene_id, rec["locale"]),
                    "device": _device_of(scene_id, rec["locale"]),
                    "chip": _chip_of(scene_id),
                    # ── 文案属性（**派生**）
                    "title": rec["title"],
                    "titleChars": len(rec["title"]),
                    "bodyChars": len(body),
                    "topicCount": len(rec["topics"]),
                    "hook": hook_shape(body),
                    # ── 语种属性（来自 languages/ 目录）
                    "dir": _dir_of(rec["locale"]),
                    # ── 平台结果（人工/发布流程写入；此处只带出处标记）
                    "published": rec["publishedMark"] or None,
                    "url": None,
                    "postId": None,
                    "publishedAt": None,
                    # ── 核验凭据。**已发布声明的证据链分两级**：
                    #    url/postId（可点开，强）/ verifiedBy+verifiedAt（playbook 记的核验方式+日期，次）。
                    #    两者都没有 = 「已发布」这三个字只是一句散文里的自述，无法核验（坑㉳）。
                    "verifiedBy": None,
                    "verifiedAt": None,
                    # ── 效果指标。**没有就是 null，绝不填 0**——
                    # 0 是「播放 0 次」，null 是「不知道」。把不知道写成 0
                    # 会让分析器把「没数据」当成「效果极差」参与排名。
                    "metrics": None,
                }
    return {
        "version": VERSION,
        "updatedAt": None,
        "note": ("发布台账。文案属性全部从 lessons/<id>/publish/*-copy.md 派生；"
                 "平台结果与效果指标由 publish/results.json 合并进来。"
                 "metrics 为 null 表示尚未回填平台数据（不是 0）。"),
        "entries": entries,
    }


def merge_results(doc: dict, results_path: Path) -> int:
    """把 `publish/results.json` 里的平台结果/指标合并进台账。返回合并条数。"""
    if not results_path.exists():
        return 0
    res = json.loads(results_path.read_text("utf-8"))
    n = 0
    for key, patch in (res.get("results") or {}).items():
        e = doc["entries"].get(key)
        if e is None:
            raise SystemExit(
                f"results.json 里的 {key!r} 在台账里没有对应记录——"
                f"这条发布对应的课/copy 源被删了或改名了（悬空引用必须先修）")
        for field in ("published", "url", "postId", "publishedAt",
                      "verifiedBy", "verifiedAt"):
            if field in patch:
                e[field] = patch[field]
        if patch.get("metrics"):
            e["metrics"] = patch["metrics"]
        n += 1
    return n


def load() -> dict:
    if not LEDGER_PATH.exists():
        raise SystemExit(f"台账不存在：{LEDGER_PATH.relative_to(ROOT)}（先跑 `usine publish build`）")
    doc = json.loads(LEDGER_PATH.read_text("utf-8"))
    if doc.get("version") != VERSION:
        raise SystemExit(f"台账 schema 版本 {doc.get('version')} != {VERSION}，请重建"
                         f"（字段是 schema 的一部分，旧文件不作猜读）")
    return doc


def save(doc: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, LEDGER_PATH)


# ---------------------------------------------------------------- 门禁判据
def check(doc: dict) -> list[str]:
    """返回问题列表；空列表 = 全部通过。

    判据全部取**真实目的**，不取代理量：
    - 「这条发布对应的视频真的在磁盘上」而不是「video 字段非空」；
    - 「这数是不是个比率」而不是「比率字段有没有」；
    - 「指标挂在一条真实发布过的记录上」而不是「指标条目数对得上」。
    """
    problems: list[str] = []
    entries = doc.get("entries") or {}
    if not entries:
        return ["台账一条记录都没有（`usine publish build` 没跑到？）"]

    for key in sorted(entries):
        e = entries[key]

        # ① 键与字段自洽：键就是 `lesson/locale/platform`，不一致说明有人手改过键
        want = f"{e.get('lesson')}/{e.get('locale')}/{e.get('platform')}"
        if key != want:
            problems.append(f"{key}: 键与字段不自洽（字段拼出来是 {want}）")

        # ② 素材真在磁盘上。copy 源写了 `源文件：\`build/scene/xxx.mp4\``，
        #    路径手抄错一位就发布了一支不存在的东西——**引用完整性是这里唯一的硬事实**。
        v = e.get("video")
        if not v:
            problems.append(f"{key}: 没有视频路径（copy 源缺「源文件」行？）")
        elif not (ROOT / v).exists():
            problems.append(f"{key}: 视频不在磁盘上：{v}")

        # ③ 标题上限。平台超限会**红字计数/截断**，是发布前的硬约束。
        meta = PLATFORMS.get(e.get("platform") or "")
        if meta and meta.get("titleMax") and e.get("titleChars", 0) > meta["titleMax"]:
            problems.append(f"{key}: 标题 {e['titleChars']} 字 > {meta['label']}上限 "
                            f"{meta['titleMax']} 字（会被截断）")

        # ④ 语种属性要有出处。`dir` 缺失 = languages/ 目录没这个语种，
        #    意味着台账里少了一维可分析的属性（静默降级，必须报出来）。
        if not e.get("dir"):
            problems.append(f"{key}: 无书写方向（languages/{e.get('locale')}/manifest.json 缺失）")

        # ⑤ 已发布声明必须有可核验凭据。
        #    判据取**真实目的**——「这句话有据可查」——而不是代理量「必须有 url」：
        #    抖音/小红书的后台列表页不给永久链接，playbook 记的是另一种同样可复核的凭据
        #    （核验方式 + 核验日期）。两个都不给，才是「已发布」三个字裸奔。
        #    两级凭据**分开判，别合成一个布尔再 else**：合成后
        #    `weak = verifiedBy and verifiedAt` 在「有方式没日期」时为假，
        #    会掉进「无任何凭据」那句（措辞还是错的，方式明明有），
        #    而真正的「缺核验日期」分支永远走不到。2026-10-05 反向验证第 5 条抓出。
        if e.get("published"):
            strong = bool(e.get("url") or e.get("postId"))
            if e.get("verifiedBy"):
                if not e.get("verifiedAt"):
                    problems.append(
                        f"{key}: 凭据有 verifiedBy 但缺 verifiedAt"
                        f"（核验是哪天做的？半截凭据无法复核）")
            elif not strong:
                problems.append(
                    f"{key}: 标了已发布但无任何凭据"
                    f"（要 url/postId，或 verifiedBy+verifiedAt）")

        # ⑥ 指标取值域
        m = e.get("metrics")
        if m:
            for k, val in m.items():
                if k in COUNT_METRICS:
                    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                        problems.append(f"{key}: 指标 {k}={val!r} 不是非负整数")
                elif k in RATE_METRICS:
                    if not isinstance(val, (int, float)) or isinstance(val, bool) \
                            or not (0.0 <= float(val) <= 1.0):
                        problems.append(f"{key}: 指标 {k}={val!r} 不在 0–1 之间")
                else:
                    problems.append(f"{key}: 未知指标 {k!r}（{ALL_METRICS}）")

        # ⑦ 指标只可能挂在**真发布过**的记录上。没发出去的条目有播放量，
        #    只有一个来源：手工填错了一行。判据取「这条发布存在吗」，
        #    而不是代理量「published 字段是 true 吗」。
        #    这条判据 2026-10-05 是先写进 docstring、忘了落成代码的——
        #    坑㉝（不变量无人把关）在自家新代码上重演了一次。
        if e.get("metrics") and not e.get("published"):
            problems.append(
                f"{key}: 有效果指标但没标已发布——没发出去的作品不会有平台数据，"
                f"多半是 metrics 挂错了行")
    return problems


# ---------------------------------------------------------------- 回流分析
DIMENSIONS = {
    "hook": "钩子形态",
    "device": "装置样式",
    "chip": "教学装置两型",
    "dir": "书写方向",
    "locale": "语种",
    "platform": "平台",
    "lesson": "课程",
    "topicCount": "话题数",
    "bodyChars": "正文字数",
    "titleChars": "标题字数",
    "durationSec": "视频时长",
    "lineCount": "台词行数",
}
# 连续值分箱的维度。标量维度（语种/平台）照原样分组，14 条会分成 14 组，
# 那不是「粒度太细」，那是这个维度本来就该逐条看。
BUCKETED = ("bodyChars", "titleChars", "durationSec", "topicCount", "lineCount")


def _bucket(val) -> str:
    """把连续值分箱，否则「正文字数」会分成 14 个各 1 条的组、一条都排不出。"""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return str(val) if val is not None else "(缺)"
    for lo, hi, name in ((0, 100, "0-100"), (100, 150, "100-150"),
                         (150, 200, "150-200"), (200, 300, "200-300"),
                         (300, 10**9, "300+")):
        if lo <= val < hi:
            return name
    return str(val)


def analyze(doc: dict, metric: str = "views", min_group: int = MIN_GROUP) -> int:
    """按维度分组比表现。**样本不足不排名**。

    返回码：0 = 出了结论或如实报告了「无数据」；1 = 传进来的指标名不合法。
    """
    if metric not in ALL_METRICS:
        print(f"未知指标 {metric!r}；可用：{'/'.join(ALL_METRICS)}")
        return 1

    # 筛选必须落在**这一项指标**上，不是「有没有 metrics」。
    # 只回填了 likes 就去查 views，按 `if e.get("metrics")` 筛会在
    # `e["metrics"][metric]` 处 KeyError——而 platforms 的后台导出
    # 往往只给一部分指标，**部分回填是常态而不是异常**（2026-10-05 修）。
    rows = [e for e in (doc.get("entries") or {}).values()
            if (e.get("metrics") or {}).get(metric) is not None]
    have = len(doc.get("entries") or {})
    print("=" * 70)
    print(f"发布回流分析 · 指标 {metric} · 有指标 {len(rows)}/{have} 条记录")
    print("=" * 70)
    if not rows:
        print("平台数据尚未回填。台账里 metrics 全是 null——这不是「效果为零」，是「不知道」。")
        print("回填方式：把 `usine publish build` 的输出与平台后台数字写进 publish/results.json，")
        print("          然后 `uv run usine-publish check` + `analyze`。")
        return 0

    for dim, dim_label in DIMENSIONS.items():
        groups: dict[str, list] = {}
        for e in rows:
            v = e.get(dim)
            key = _bucket(v) if dim in BUCKETED else str(v)
            groups.setdefault(key, []).append(e["metrics"][metric])
        sized = {k: v for k, v in groups.items() if len(v) >= min_group}
        thin = {k: len(v) for k, v in groups.items() if len(v) < min_group}
        if not sized:
            print(f"\n【{dim_label}】无任何分组达到样本量 {min_group}（"
                  f"各组 n：{sorted(thin.values(), reverse=True)[:6]}）→ 不下结论")
            continue
        ranked = sorted(sized.items(), key=lambda kv: statistics.median(kv[1]), reverse=True)
        print(f"\n【{dim_label}】按 {metric} 中位数（n≥{min_group}）")
        for k, vals in ranked:
            xs = sorted(vals)
            print(f"  {k:<14} n={len(vals):<3} 中位 {statistics.median(xs):>10.1f}  "
                  f"范围 {xs[0]}–{xs[-1]}")
        if thin:
            print(f"  样本不足未排：{dict(sorted(thin.items(), key=lambda kv: -kv[1]))}")
    print()
    return 0


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="发布台账与指标回流（P2-5）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="从 copy 事实源重建台账（合并 publish/results.json）")
    b.add_argument("--lesson", action="append", default=None, help="限定某几课（默认全部）")

    c = sub.add_parser("check", help="门禁：引用完整性 / 指标取值域 / 标题上限")
    a = sub.add_parser("analyze", help="按维度分组比表现（样本不足不下结论）")
    a.add_argument("--metric", default="views", choices=list(ALL_METRICS))
    a.add_argument("--min-group", type=int, default=MIN_GROUP)

    args = ap.parse_args(argv)

    if args.cmd == "build":
        lessons = tuple(args.lesson) if args.lesson else tuple(
            sorted(p.name for p in (ROOT / "lessons").iterdir() if p.is_dir()))
        doc = build(lessons)
        n = merge_results(doc, ROOT / "publish" / "results.json")
        save(doc)
        print(f"台账已写：{LEDGER_PATH.relative_to(ROOT)} · {len(doc['entries'])} 条记录"
              f"（合并 results.json {n} 条）")
        return 0

    doc = load()
    if args.cmd == "check":
        problems = check(doc)
        print("=" * 68)
        if problems:
            print(f"发布台账门禁：{len(problems)} 个问题")
            print("=" * 68)
            for p in problems:
                print(f"  [FAIL] {p}")
            return 1
        print(f"发布台账门禁：{len(doc['entries'])} 条全部通过")
        print("=" * 68)
        return 0
    if args.cmd == "analyze":
        return analyze(doc, args.metric, args.min_group)
    return 0


if __name__ == "__main__":
    sys.exit(main())
