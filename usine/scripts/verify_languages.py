#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_languages.py — 语种注册表的反向验证

原 run.ps1 langs 门禁未随三项目重构迁入（languages/README.md「门禁」节有记录），
本套件是重建。第 0 条好数据放行：14 语种 manifest 全部零问题——判据写反时这条会全红。

判据（体例 = languages/README.md「体例」表）：
1. 字段契约逐目录：locale=目录名、label 非空、flag=locale 区码的区域指示符对
   （错旗比字母对更糟，判的是「这两个码位真的是那个国家」）、dir∈{ltr,rtl}、
   fontCss 以 sans-serif 兜底、order 正整数且全表唯一、tier∈{core,optional}、
   displayFontCss（若有）末尾整段接回 fontCss。
2. 档位不变量：core 的 order 全部小于 optional。
3. data.py 集成：language_manifests() 按 order 升序、core_locales() = core 档升序。
4. 反向：定向破坏必须被抓。注入只在内存 / 临时目录，不动真 languages/。
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import data                                # noqa: E402

LANGUAGES = ROOT / "languages"
TIERS = ("core", "optional")


def _regional_indicator_pair(subtag: str) -> str:
    """ISO 双字母区码 → 成对区域指示符（CN → 🇨🇳）。"""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in subtag.upper())


def manifest_problems(dirname: str, m: dict) -> list[str]:
    """单个 manifest 的契约问题清单（空 = 通过）。体例见 languages/README.md。"""
    probs: list[str] = []
    if m.get("locale") != dirname:
        probs.append(f"locale {m.get('locale')!r} ≠ 目录名 {dirname!r}")
    if not (m.get("label") or "").strip():
        probs.append(f"{dirname}: label 为空/缺失")
    subtag = dirname.split("-")[-1]
    flag = m.get("flag") or ""
    if (len(flag) != 2 or any(not (0x1F1E6 <= ord(c) <= 0x1F1FF) for c in flag)):
        probs.append(f"{dirname}: flag {flag!r} 不是成对区域指示符")
    elif flag != _regional_indicator_pair(subtag):
        probs.append(f"{dirname}: flag {flag!r} ≠ 区码 {subtag} 的指示符对"
                     f"（应为 {_regional_indicator_pair(subtag)}）——错旗比字母对更糟")
    if m.get("dir") not in ("ltr", "rtl"):
        probs.append(f"{dirname}: dir {m.get('dir')!r} ∉ ltr/rtl")
    if not str(m.get("fontCss", "")).rstrip().endswith("sans-serif"):
        probs.append(f"{dirname}: fontCss 没以 sans-serif 兜底")
    o = m.get("order")
    if not isinstance(o, int) or isinstance(o, bool) or o < 1:
        probs.append(f"{dirname}: order {o!r} 不是正整数")
    if m.get("tier") not in TIERS:
        probs.append(f"{dirname}: tier {m.get('tier')!r} ∉ {'/'.join(TIERS)}")
    dfc = m.get("displayFontCss")
    if dfc is not None and not dfc.rstrip().endswith(m.get("fontCss", "").rstrip()):
        probs.append(f"{dirname}: displayFontCss 末尾没整段接回 fontCss")
    return probs


def _order_dups(manifests: dict) -> list[int]:
    """全表 order 撞号清单（0b 与反向注入共用同一份判据，不是各写各的）。"""
    orders = [m["order"] for m in manifests.values() if isinstance(m.get("order"), int)]
    return sorted({o for o in orders if orders.count(o) > 1})


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []
    manifests = {d.name: json.loads((d / "manifest.json").read_text("utf-8"))
                 for d in sorted(LANGUAGES.iterdir())
                 if d.is_dir() and (d / "manifest.json").exists()}

    # ---- 0. 好数据放行：全部 manifest 逐目录零问题 ----
    probs = [p for dn, m in manifests.items() for p in manifest_problems(dn, m)]
    rows.append((not probs, f"{len(manifests)} 语种 manifest 字段契约零问题"
                 + (f"　**{probs[:2]}**" if probs else "")))

    # ---- 0b. order 全表唯一 ----
    dup = _order_dups(manifests)
    rows.append((not dup, f"order 全表唯一（{len(manifests)} 个正整数在位）"
                 + (f"　**撞号：{dup}**" if dup else "")))

    # ---- 0c. 档位不变量：core 全部排在 optional 前 ----
    core_max = max((m["order"] for m in manifests.values() if m.get("tier") == "core"), default=0)
    opt_min = min((m["order"] for m in manifests.values() if m.get("tier") == "optional"),
                  default=10**9)
    rows.append((core_max < opt_min,
                 "档位不变量：core 的 order 全部 < optional（核心在前、可选垫后）"
                 + ("" if core_max < opt_min else f"　**core max={core_max} ≥ optional min={opt_min}**")))

    # ---- 0d. data.py 集成：返回序 = order 升序；core_locales = core 档升序列表 ----
    got = list(data.language_manifests())
    want = sorted(manifests, key=lambda dn: manifests[dn]["order"])
    rows.append((got == want, "language_manifests() 按 order 升序返回"
                 + ("" if got == want else f"　**实得 {got[:4]}…，应得 {want[:4]}…**")))
    core = data.core_locales()
    core_want = [dn for dn in want if manifests[dn].get("tier") == "core"]
    rows.append((core == core_want, f"core_locales() = core 档 order 升序（{len(core)} 种，{core[:2]} 打头）"
                 + ("" if core == core_want else f"　**实得 {core[:4]}…，应得 {core_want[:4]}…**")))

    # ---- 1. 反向：定向破坏必须被抓 ----
    base = json.loads((LANGUAGES / "zh-CN" / "manifest.json").read_text("utf-8"))

    def corrupt(mutate, expect_kw, what):
        m = json.loads(json.dumps(base))
        mutate(m)
        probs = manifest_problems("zh-CN", m)
        hit = any(expect_kw in p for p in probs)
        rows.append((hit, f"{what} → 被抓" + ("" if hit else f"　**漏了！问题清单：{probs[:2]}**")))

    corrupt(lambda m: m.update(locale="zh-TW"), "目录名", "locale ≠ 目录名")
    corrupt(lambda m: m.update(flag="🇺🇸"), "错旗", "flag 配了别国旗（zh-CN 配 US 旗）")
    corrupt(lambda m: m.update(flag="🇨"), "成对区域指示符", "flag 只有一个码位")
    corrupt(lambda m: m.update(dir="ttb"), "ltr/rtl", "dir 越界（ttb）")
    corrupt(lambda m: m.update(fontCss="'Microsoft YaHei'"), "sans-serif", "fontCss 无 sans-serif 兜底")
    corrupt(lambda m: m.update(order="1"), "正整数", "order 是字符串")
    corrupt(lambda m: m.update(tier="Core"), "core/optional", "tier 大小写错（Core）")
    corrupt(lambda m: m.update(displayFontCss="'Songti SC', serif"),
            "接回", "displayFontCss 没接回 fontCss")

    # 撞 order：两个目录同号，必须被 0b 同一份唯一性判据抓到
    injected = {}
    for dn in ("xx-XX", "yy-YY"):
        m = json.loads(json.dumps(base))
        m.update(locale=dn, order=1, tier="core", label=dn)
        injected[dn] = m
    dup = _order_dups(injected)
    rows.append((dup == [1], "撞 order（两目录同号 1）→ 被 0b 同一份判据抓"
                 + ("" if dup == [1] else f"　**漏了！实得撞号 {dup}**")))

    # ---- 2. 活性证明：注册表真变了，data.py 跟着变（不抄名单——名单必腐烂） ----
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for dn, order in (("aa-AA", 2), ("bb-BB", 1)):
            m = json.loads(json.dumps(base))
            m.update(locale=dn, order=order, tier="core" if order == 1 else "optional", label=dn)
            (tmp / dn).mkdir()
            (tmp / dn / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), "utf-8")
        got = list(data.language_manifests(str(tmp)))
        core = data.core_locales(str(tmp))
        rows.append((got == ["bb-BB", "aa-AA"] and core == ["bb-BB"],
                     "临时注册表（bb-BB=1/core, aa-AA=2/optional）→ 排序与 core 过滤跟着 manifest 走"))

    return rows


def main() -> int:
    print("=" * 72)
    print("语种注册表（languages/<locale>/manifest.json + data.py 顺序）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：语种注册表 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
