#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data.py — 数据入口唯一事实源（personas / intro-cards / languages / scene.json）

搬运自 explorateur/src/usine/data.py（142 行；函数体逐字节照搬，含全部坑注/准则注）。

**为什么需要**（源文件 2026-10-04 收债新增，动机照搬）：此前 `personas.json` 在 6 处被
各自 `json.load` 打开，路径各自手抄——改目录结构时必漏。本模块把「数据在哪、怎么读、
读成什么形状」收成一处。

适配点（仅此四处，其余逐字节照搬）：
- ROOT 锚定从 `usine/__init__.py`（pyproject 上溯）挪进本模块，feuille 包 `__init__.py`
  不动；默认目录 = feuille 仓库根下 `personas/` `languages/` `lessons/`。
- **目录路径参数化**：`personas_doc` / `language_manifests` / `cards_doc` / `scene_doc`
  增加可选目录参数（缺省 None = feuille 默认）。personas/ 与 languages/ 是**能力数据**
  （班底 + 语种注册表，渲染文字层与校验层共用），缺省就是 feuille 下的这份；lessons/
  是内容项目数据，内容项目把自己的目录指进来。`lru_cache` 按实参分键，不同目录互不串味。
- 只搬场景机制（②③）用到的入口；`persona()` / `locale_of()` / `unit_persona()`
  服务于 explorateur 的亮相卡变体解析（intro-cards `variants[]`），feuille 未搬该管线，
  随它走（不搬清单见 rig.py / scenes.py 同款终态说明）。
- 错误提示里的命令名 `usine-parse` → `uv run feuille scene parse`。

**不变量（源文件新增，照搬）**：经本模块取回的人设/卡片数据是**只读**的。进程内缓存返回
同一对象，任何模块 mutate 它都会污染同进程内的其他读者（渲染线与探针线同进程时立刻串味）。

使用契约：
    from feuille.data import personas, cards_doc, language_manifests, scene_doc
    P = personas()                     # {id: persona}（缺省 = feuille/personas/）
    doc = personas_doc()               # 原始 JSON（要顶层字段时用）
    cards = cards_doc()                # intro-cards.json 全文
    langs = language_manifests()       # {locale: languages/<locale>/manifest.json}
    scene = scene_doc("colors", lessons_dir=Path(".../lessons"))
"""
import json
from functools import lru_cache
from pathlib import Path

# ROOT 由本文件位置向上定位仓库根（pyproject.toml 所在层）——usine 同款锚定法，
# 包内默认路径（personas/ languages/ lessons/）不依赖 cwd。
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())

PERSONAS_DIR = ROOT / "personas"
PERSONAS_PATH = PERSONAS_DIR / "personas.json"
CARDS_PATH = PERSONAS_DIR / "intro-cards.json"
LANGUAGES_DIR = ROOT / "languages"
LESSONS_DIR = ROOT / "lessons"


def _read_json(path):
    return json.loads(path.read_text("utf-8"))


def _dir(given, default):
    """可选目录参数 → Path：None / 空 = 缺省目录（参数化后各函数的第一行，非源代码）。"""
    return Path(given) if given else default


@lru_cache(maxsize=None)
def personas_doc(personas_dir=None):
    """personas.json 全文（含顶层字段）。只读。"""
    return _read_json(_dir(personas_dir, PERSONAS_DIR) / "personas.json")


@lru_cache(maxsize=None)
def language_manifests(languages_dir=None):
    """{locale: languages/<locale>/manifest.json}。语种目录——**语种知识的事实源**。

    2026-10-04 收债新增（P1-4）。此前语种的东西散在三个地方：`intro_cards.FONT_CSS`（字体栈）、
    `intro_cards.FLAG`（国旗 emoji）、`personas[].langLabel`（语种文字）。加一个语种要同时改
    三处，漏一处不报错，只是静静渲出一个「没有旗的语言牌」——这类洞只能靠目录化 + 门禁堵。

    语种目录收的是**语种自身的属性**（文字、旗、书写方向、字体栈），不是某一门课的剧本属性：
    `rtl` 同时也出现在剧本 §0 `rtlLocales`（那是 §0 声明体例的一部分，保留），两者必须一致。
    """
    base = _dir(languages_dir, LANGUAGES_DIR)
    out = {}
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        f = d / "manifest.json"
        if d.is_dir() and f.exists():
            out[d.name] = _read_json(f)
    return out


@lru_cache(maxsize=None)
def fonts_css(languages_dir=None):
    """{locale: CSS font-family 栈}——供文字层渲染用。"""
    return {loc: m["fontCss"] for loc, m in language_manifests(languages_dir).items()}


@lru_cache(maxsize=None)
def flags(languages_dir=None):
    """{locale: 国旗 emoji}。Windows Segoe UI Emoji 无国旗字形 → 渲染为 ISO 双字母对
    （见手册坑⑬：禁为「补旗」私画简化国旗，错旗比字母对更糟）。"""
    return {loc: m["flag"] for loc, m in language_manifests(languages_dir).items()}


def lang_label(locale, languages_dir=None):
    """语种文字（语言牌上的「汉语」「希腊语」）。未知语种即报错，不静默回落成裸 locale。"""
    m = language_manifests(languages_dir).get(locale)
    if not m:
        raise KeyError(f"无此语种目录：languages/{locale}/manifest.json（新增语种=新建目录）")
    return m["label"]


@lru_cache(maxsize=None)
def personas(personas_dir=None):
    """{id: persona} 索引。渲染线、探针线、场景线统一取这里。"""
    return {p["id"]: p for p in personas_doc(personas_dir)["personas"]}


@lru_cache(maxsize=None)
def cards_doc(personas_dir=None):
    """intro-cards.json 全文（28 张卡的台词/情绪/手势/选角）。只读。"""
    return _read_json(_dir(personas_dir, PERSONAS_DIR) / "intro-cards.json")


def scene_doc(scene_id, lessons_dir=None):
    """lessons/<id>/scene.json 解析结果（不缓存：解析阶段可能刚重写文件）。"""
    from .parse_scene import scene_paths      # 延迟导入：避免与解析器形成加载期环
    _, js = scene_paths(scene_id, lessons_dir)
    if not js.exists():
        raise SystemExit(f"场景数据不存在：{js.name}（先跑 `uv run feuille scene parse --scene {scene_id}`）")
    return _read_json(js)


def reload_all():
    """清空进程内缓存（测试/长驻进程改数据后用）。"""
    personas_doc.cache_clear()
    personas.cache_clear()
    cards_doc.cache_clear()
    language_manifests.cache_clear()
    fonts_css.cache_clear()
    flags.cache_clear()
