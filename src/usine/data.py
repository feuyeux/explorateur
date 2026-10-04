#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data.py — 数据入口唯一事实源（personas / intro-cards / scene.json）

2026-10-04 收债新增。此前 `personas.json` 在 6 处被各自 `json.load` 打开
（intro_cards.load_data / scene_video.load_data / qa_all / qa_char / qa_grid / qa_motion），
路径各自手抄——改目录结构时必漏。本模块把「数据在哪、怎么读、读成什么形状」收成一处。

**不变量（新增）**：经本模块取回的人设/卡片数据是**只读**的。进程内缓存返回同一对象，
任何模块 mutate 它都会污染同进程内的其他读者（渲染线与探针线同进程时立刻串味）。
2026-10-04 已核：渲染线 `intro_cards.render_card` 里的 `P["armR"] = ...` 是渲染期
姿态局部量，与人设数据无关；`parse_scene` / `build_lesson` 的 mutate 也都作用在
自己 parse 出来的结构上——人设数据当前无人 mutate，此不变量成立。

用法：
    from usine.data import personas, cards_doc
    P = personas()              # {id: persona}
    doc = personas_doc()        # 原始 JSON（要顶层字段时用）
    cards = cards_doc()         # intro-cards.json 全文
"""
import json
from functools import lru_cache

from . import ROOT

PERSONAS_DIR = ROOT / "personas"
PERSONAS_PATH = PERSONAS_DIR / "personas.json"
CARDS_PATH = PERSONAS_DIR / "intro-cards.json"
LANGUAGES_DIR = ROOT / "languages"


def _read_json(path):
    return json.loads(path.read_text("utf-8"))


@lru_cache(maxsize=None)
def personas_doc():
    """personas.json 全文（含顶层字段）。只读。"""
    return _read_json(PERSONAS_PATH)


@lru_cache(maxsize=None)
def language_manifests():
    """{locale: languages/<locale>/manifest.json}。语种目录——**语种知识的事实源**。

    2026-10-04 收债新增（P1-4）。此前语种的东西散在三个地方：`intro_cards.FONT_CSS`（字体栈）、
    `intro_cards.FLAG`（国旗 emoji）、`personas[].langLabel`（语种文字）。加一个语种要同时改
    三处，漏一处不报错，只是静静渲出一个「没有旗的语言牌」——这类洞只能靠目录化 + 门禁堵。

    语种目录收的是**语种自身的属性**（文字、旗、书写方向、字体栈），不是某一课的剧本属性：
    `rtl` 同时也出现在剧本 §0 `rtlLocales`（那是 §0 声明体例的一部分，保留），两者必须一致。
    """
    out = {}
    if not LANGUAGES_DIR.is_dir():
        return out
    for d in sorted(LANGUAGES_DIR.iterdir()):
        f = d / "manifest.json"
        if d.is_dir() and f.exists():
            out[d.name] = _read_json(f)
    return out


@lru_cache(maxsize=None)
def fonts_css():
    """{locale: CSS font-family 栈}——供文字层渲染用。"""
    return {loc: m["fontCss"] for loc, m in language_manifests().items()}


@lru_cache(maxsize=None)
def flags():
    """{locale: 国旗 emoji}。Windows Segoe UI Emoji 无国旗字形 → 渲染为 ISO 双字母对
    （见手册坑⑬：禁为「补旗」私画简化国旗，错旗比字母对更糟）。"""
    return {loc: m["flag"] for loc, m in language_manifests().items()}


def lang_label(locale):
    """语种文字（语言牌上的「汉语」「希腊语」）。未知语种即报错，不静默回落成裸 locale。"""
    m = language_manifests().get(locale)
    if not m:
        raise KeyError(f"无此语种目录：languages/{locale}/manifest.json（新增语种=新建目录）")
    return m["label"]


@lru_cache(maxsize=None)
def personas():
    """{id: persona} 索引。渲染线、探针线、场景线统一取这里。"""
    return {p["id"]: p for p in personas_doc()["personas"]}


@lru_cache(maxsize=None)
def cards_doc():
    """intro-cards.json 全文（28 张卡的台词/情绪/手势/选角）。只读。"""
    return _read_json(CARDS_PATH)


def persona(pid):
    """按 id 取一个人设；不存在即报错（比 KeyError 好的失败信息）。"""
    P = personas()
    if pid not in P:
        raise KeyError(f"班底无此 id：{pid!r}（personas.json 共 {len(P)} 人）")
    return P[pid]


def locale_of(unit_or_pid):
    """人设 id 或渲染单元 id → locale（`_f` 变体自动回落到它的基础人设）。"""
    return persona(unit_persona(unit_or_pid))["locale"]


def unit_persona(unit_id):
    """渲染单元 id → 基础 persona id。

    主卡 id == persona id；RTL 女性观众版的单元 id 是 `<id>_f`，但共用基础人设
    （变体只换 lines，共享人设/场景/收尾/手势——见 `intro_cards.card_units` 与
    self-introductions §1.4）。personas.json 里**没有** variantOf 字段，变体关系
    只存在于 intro-cards.json 的 `variants[]`，所以必须走卡片文档解析。
    """
    if unit_id in personas():
        return unit_id
    for card in cards_doc()["cards"]:
        for v in card.get("variants", []):
            if v["id"] == unit_id:
                return card["id"]
    raise KeyError(f"既不是班底 id 也不是卡片单元 id：{unit_id!r}")


def scene_doc(scene_id):
    """lessons/<id>/scene.json 解析结果（不缓存：解析阶段可能刚重写文件）。"""
    from .parse_scene import scene_paths      # 延迟导入：避免与解析器形成加载期环
    _, js = scene_paths(scene_id)
    if not js.exists():
        raise SystemExit(f"场景数据不存在：{js.name}（先跑 `uv run usine-parse --scene {scene_id}`）")
    return _read_json(js)


def reload_all():
    """清空进程内缓存（测试/长驻进程改数据后用）。"""
    personas_doc.cache_clear()
    personas.cache_clear()
    cards_doc.cache_clear()
    language_manifests.cache_clear()
    fonts_css.cache_clear()
    flags.cache_clear()
