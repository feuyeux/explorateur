#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语种目录门禁：languages/<locale>/manifest.json 是否自洽且覆盖全部在用语种。

**为什么要有门禁**：P1-4 之前，语种的知识散在三处——`intro_cards.FONT_CSS`（字体栈）、
`intro_cards.FLAG`（国旗 emoji）、`personas[].langLabel`（语种文字）。加语种要同时改三个地方，
漏一处不会报错，只会静静渲染出一个「没有旗的语言牌」。这类洞的特点就是**静默**，所以必须有门禁。

**判据取真实目的，不取代理量**：手册坑⑬的原话是「错旗比字母对更糟」。所以判据不是
「flag 字段存在」，而是「这两个码位真的是该 locale 的 ISO 区码」——错旗是最坏结果，
必须判死。反向验证第 2 条专门用错旗证明这一点。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usine.data import personas  # noqa: E402
from usine.parse_scene import QUOTE_PAIRS as _QP  # noqa: E402

LANGS_DIR = ROOT / "languages"
REGIONAL_A, REGIONAL_Z = 0x1F1E6, 0x1F1FF
# 引号对必须落在解析器真正认的那四对里——写第五对会「声明合法但解析不了」，
# 而解析不了的表现是台词被整段丢弃（静默）。取值直接引 parse_scene，不另抄一份。
QUOTE_PAIRS = {"".join(pair) for pair in _QP}
REQUIRED = ("locale", "label", "flag", "dir", "fontCss", "quote")


def _manifest(path: pathlib.Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _region_ok(locale: str, flag: str) -> bool:
    """国旗 = locale 的 ISO 区码（如 zh-CN → CN）编成的区域指示符对。

    区域指示符 U+1F1E6 对应字母 A，每往后一个码位走一个字母；反解就是减回偏移再落回
    ASCII 大写。（写反了就成了「拿原字符比 'CN'」，好数据全红——反向验证第 0 条先抓到的就是它。）
    """
    region = locale.rsplit("-", 1)[-1]
    if len(flag) != 2 or not all(REGIONAL_A <= ord(c) <= REGIONAL_Z for c in flag):
        return False
    decoded = "".join(chr(ord(c) - REGIONAL_A + ord("A")) for c in flag)
    return decoded == region


def load_manifests() -> dict:
    """{locale: manifest}——门禁与反向验证共用这一个入口，反向验证只需换掉它。"""
    out = {}
    for d in sorted(LANGS_DIR.iterdir()):
        if d.is_dir() and (d / "manifest.json").exists():
            out[d.name] = _manifest(d / "manifest.json")
    return out


def check(locales_in_use, manifests=None):
    """返回 [(ok, msg)]。

    `locales_in_use` 与 `manifests` 都留成入参：反向验证靠注入**已知坏数据**证明
    这道门禁真的会 FAIL——只跑「现状全绿」等于没测，探针完全可能恒真。
    """
    out = []
    if manifests is None:
        manifests = load_manifests()

    out.append((bool(manifests), f"语种目录非空（{len(manifests)} 个）"))

    for loc, m in sorted(manifests.items()):
        if not isinstance(m, dict):
            out.append((False, f"{loc} manifest 不是对象（实为 {type(m).__name__}）"))
            continue
        missing = [k for k in REQUIRED if k not in m or not str(m[k]).strip()]
        out.append((not missing, f"{loc} 字段齐备" + (f"（缺 {missing}）" if missing else "")))
        if missing:
            continue
        out.append((m["locale"] == loc, f"{loc} 目录名与 locale 字段一致（实为 {m['locale']}）"))
        out.append((m["dir"] in ("ltr", "rtl"), f"{loc} dir 合法（{m['dir']}）"))
        out.append(("sans-serif" in m["fontCss"],
                    f"{loc} 字体栈带通用兜底（{m['fontCss']}）"))
        ok = _region_ok(loc, m["flag"])
        out.append((ok, f"{loc} 国旗 = ISO 区码 {loc.rsplit('-', 1)[-1]}（{m['flag']}）"))
        out.append((m["quote"] in QUOTE_PAIRS,
                    f"{loc} 引号对在解析器认的四对内（{[hex(ord(c)) for c in m['quote']]}）"))

    for loc in sorted(set(locales_in_use) - set(manifests)):
        out.append((False, f"在用语种 {loc} 没有 languages/{loc}/manifest.json"))
    return out


def main() -> int:
    in_use = {p["locale"] for p in personas().values()}
    rows = check(in_use)

    print("=" * 64)
    print("语种目录门禁：languages/<locale>/manifest.json")
    print("=" * 64)
    fails = 0
    for ok, msg in rows:
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok
    print(f"\n{'OK' if not fails else 'FAIL'}：{len(rows) - fails} PASS / {fails} FAIL")
    return 1 if fails else 0


# ---------- 反向验证：拿已知坏数据证明门禁真的会红 ----------
# 只跑「现状全绿」等于没测——下面每一条探针都可能是恒真的。这里逐条注入坏数据，
# 要求对应判据必须 FAIL；注入好数据则必须放行。两条合起来才说明判据真的在判那件事。

SELFTESTS = [
    # (说明, 造坏数据, 相关判据关键词, 期望 FAIL)
    ("错旗：把 zh-CN 的旗换成 🇯🇵（结构合法、只是国家不对）",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "flag": "\U0001F1EF\U0001F1F5"}}, "国旗"),
    ("半个旗：只留一个码位",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "flag": "\U0001F1E8"}}, "国旗"),
    ("目录名与 locale 字段打架",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "locale": "zh-HK"}}, "一致"),
    ("dir 写成 top（会静默当成 ltr 之外的怪值）",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "dir": "top"}}, "dir 合法"),
    ("字体栈没有通用兜底（机器没装该字体就掉进系统默认）",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "fontCss": "'Yu Gothic UI'"}}, "兜底"),
    ("label 清空（语言牌只剩一个旗）",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "label": "  "}}, "字段齐备"),
    ("少一个语种目录（在用人设还在）",
     lambda m: {k: v for k, v in m.items() if k != "he-IL"}, "没有 languages/"),
    ("引号对用了书名号《》（作者很容易顺手拿它当对白——解析器不认，台词会被整段丢弃且不报错）",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "quote": "《》"}}, "引号对"),
    ("引号对只剩开口（半截引号连不成对）",
     lambda m: {**m, "zh-CN": {**m["zh-CN"], "quote": "\u300c"}}, "引号对"),
]


def selftest() -> int:
    good = load_manifests()
    in_use = {p["locale"] for p in personas().values()}
    print("=" * 64)
    print("反向验证：注入已知坏数据，门禁必须 FAIL")
    print("=" * 64)

    base_fails = [m for ok, m in check(in_use, good) if not ok]
    print(f"  [{'PASS' if not base_fails else 'FAIL'}] 好数据放行（现状 {len(base_fails)} 项 FAIL）")
    bad = 0
    for desc, mutate, kw in SELFTESTS:
        rows = check(in_use, mutate(good))
        hit = [m for ok, m in rows if not ok and kw in m]
        # 还要确认判据**是被这一条杀掉的**，而不是被别的连带项——否则换个坏法就"通过"了
        alone = len([1 for ok, m in rows if not ok]) == len(hit)
        ok = bool(hit) and alone
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}"
              + (f" → {hit[0]}" if hit else " → 门禁竟然放行了"))
        bad += not ok
    print(f"\n{'OK' if not bad else 'FAIL'}：反向验证 {len(SELFTESTS) - bad}/{len(SELFTESTS)} 条生效")
    return 1 if (bad or base_fails) else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
