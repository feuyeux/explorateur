#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_docs.py — 文档不撒谎的反向验证（docs/*.md）

**它要证的那句话**：docs 里教的每条命令都能跑、指的每个脚本 / 模块 / 符号 / 链接都存在。
render-handbook.md 由旧「亮相卡管线」沉淀而来，2026-10 清账前带着 135 行死入口
（run.ps1 / 旧 usine-* console 脚本 / 旧 qa 验收脚本 / 已并入 feuille 的旧模块名），
教的全是跑不了的命令——「没验不许长得像验过了」的文档版。清账之后，这条纪律由
本套件机检兜底，防止死入口随「复制粘贴旧手册段落」回流。

判据（全部跑在 docs/*.md 全文上；豁免规则见各判据内注释）：
0. **好数据放行是第一条断言**（纪律 1）：现行 docs 全部通过。
1. **命令真实性**：`feuille <组> <命令>`（含 `uv run` 形式；`a|b|c` 管道写法每个都算一条）
   → (组, 命令) 必须在 `feuille.cli.COMMANDS`。同行带「未接入 / 预留 / 有意不设」
   标记的豁免——有意的规划位不是谎言，但不标记就是。
2. **死入口零容忍**：已知死管线的入口名 / 旧模块名（见 DEAD_PATTERNS）一律不得再出现
   ——考古看 git 历史，文档只留仍然成立的知识。
3. **脚本真实性**：提到的 `scripts/<名>.py` 必须真实存在（抓「教一个不存在的验收脚本」；
   与 verify_cli 的聚合器登记检查同源，这里管 docs 侧）。
4. **符号真实性**：反引号里的 `feuille.<模块>[.<符号>]` 必须 import 得到、属性真实存在
   （抓「指一个不存在的现址」——清账的主要工作就是把旧名改到现址，改错了这里当场红）。
5. **链接真实性**：相对链接目标必须存在（抓死链——render-handbook 曾带两条指向
   未随迁文件的死链）。
6. **反向验证**（纪律 2）：注入 ①未登记命令 ②死入口 ③幽灵脚本 ④幽灵符号 ⑤死链
   ——五类必须各自被对应判据抓到。注入只跑在本套件的内存文本上，不动真文件。
"""
from __future__ import annotations

import importlib
import pathlib
import re
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import cli                    # noqa: E402

DOCS = ROOT / "docs"
RULES = ("commands", "dead", "scripts", "symbols", "links")

# ---- 1. 命令豁免标记：有意的规划位（同一行出现即豁免命令真实性判据）----
PLANNED_MARKS = ("未接入", "预留", "有意不设")

# ---- 2. 已知死管线的字面入口 / 旧模块名（清账依据 = 2026-10 符号级核查）----
# 判据形状刻意收窄（\b / 明确前缀），不追泛词；新死的名字靠判据 1/3/4/5 抓。
DEAD_PATTERNS = [
    (r"run\.ps1", "run.ps1 旧统一入口"),
    (r"\busine-[a-z][a-z-]*", "旧 usine-* console 入口"),
    (r"python -m usine\b", "旧包名 python -m usine"),
    (r"USINE_[A-Z]+", "旧包前缀环境变量"),
    (r"\bintro_cards\b", "旧模块 intro_cards（现址 feuille.rig 等）"),
    (r"\bscene_video\b", "旧模块 scene_video（编排未接入）"),
    (r"\bchar_sheet\b", "旧体检台 char_sheet"),
    (r"\b_render_rest\b", "旧批量脚本 _render_rest"),
    (r"\bmovement\.[a-z_]", "旧模块 movement.*（现址 feuille.rig）"),
    (r"\bmedia\.(?:compose|karaoke|edge|band)[a-z_]*", "旧模块 media.*（现址 audio/timeline/textlayer）"),
    (r"\bbuild_lesson\b", "旧模块 build_lesson（教学文档管线未接入）"),
    (r"\bpublish_douyin\b", "旧模块 publish_douyin（现址 feuille.publish.douyin）"),
    (r"\bcmd_(?:tts|render|assets)\b", "旧编排命令 cmd_*（渲染线未接入）"),
    (r"\brender_card\b", "旧编排函数 render_card（渲染线未接入）"),
    (r"\bclose_dur_for\b", "旧编排函数 close_dur_for（渲染线未接入）"),
    (r"\bFONT_CSS\b", "旧字体表 FONT_CSS（现址 languages/<lc>/manifest.json）"),
    (r"\b(?:badge|pill|bubble|band_text|band)_html\b", "旧文字层 HTML builder（未接入）"),
    (r"\bband_(?:alpha|png)\b", "旧文字层装配（未接入）"),
    (r"\b(?:tight_on_bg|cell_box)\b", "旧渲染函数（未接入）"),
    (r"\bedge_(?:viewport|window)_h\b", "旧视口探测（现址 feuille.textlayer.viewport_deficit）"),
    (r"\bqa_[a-z][a-z_]*", "旧成片验收脚本 qa_*（依赖渲染线，未接入）"),
    (r"\bverify_(?:shape_fixes|text_contract|languages|polyglot|karaoke|scene_draft)\b"
     r"|\bverify_scene_schema\.py\b", "旧反向验证脚本（已并入现行套件）"),
    (r"self-introductions", "旧文案源 self-introductions.md"),
    (r"adr-character-tech", "未随迁的旧裁定记录 adr-character-tech.md"),
]

# `feuille <组> <命令>`（uv run 形式或裸形式；a|b|c 管道写法每个都算）
CMD_RE = re.compile(r"(?:uv run )?feuille ([a-z]+) ([a-z][a-z|-]*)")
# `scripts/<名>.py` 提及（链接或正文皆算）
SCRIPT_RE = re.compile(r"scripts/([A-Za-z0-9_-]+\.py)")
# 反引号里的 feuille.<模块>[.<符号>]（尾部 () 自动截断——[\w.] 不含括号）
SYMBOL_RE = re.compile(r"`feuille\.([A-Za-z_][\w.]*)`")
# markdown 行内链接（http/锚点跳过）
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def _resolve_symbol(parts: list[str]) -> str | None:
    """`feuille.a.b.c` → 逐级 import / getattr。全通返回 None，断链返回断点描述。"""
    try:
        obj = importlib.import_module("feuille." + parts[0])
    except ImportError:
        return f"feuille.{parts[0]} 不可导入"
    name = f"feuille.{parts[0]}"
    for p in parts[1:]:
        nxt = getattr(obj, p, None)
        if nxt is not None:
            obj, name = nxt, f"{name}.{p}"
            continue
        try:  # 中段可能是子模块（feuille.publish.douyin）
            importlib.import_module(f"{name}.{p}")
        except ImportError:
            return f"{name}.{p} 不存在"
        obj = importlib.import_module(f"{name}.{p}")
        name = f"{name}.{p}"
    return None


def scan_lines(lines: list[str], base: Path) -> dict[str, list[str]]:
    """一份文档（行列表）→ 各判据的违规清单（纯文本扫描，供反向注入复用）。"""
    v: dict[str, list[str]] = {r: [] for r in RULES}
    for ln in lines:
        exempt = any(m in ln for m in PLANNED_MARKS)
        if not exempt:
            for m in CMD_RE.finditer(ln):
                grp, cmds = m.group(1), m.group(2)
                for cmd in cmds.split("|"):
                    if (grp, cmd) not in cli.COMMANDS:
                        v["commands"].append(f"feuille {grp} {cmd}（未登记）：{ln.strip()[:60]}")
        for pat, why in DEAD_PATTERNS:
            if re.search(pat, ln):
                v["dead"].append(f"{why}：{ln.strip()[:60]}")
        for m in SCRIPT_RE.finditer(ln):
            if not (ROOT / "scripts" / m.group(1)).exists():
                v["scripts"].append(f"scripts/{m.group(1)} 不存在：{ln.strip()[:60]}")
        for m in SYMBOL_RE.finditer(ln):
            miss = _resolve_symbol(m.group(1).split("."))
            if miss:
                v["symbols"].append(f"`feuille.{m.group(1)}` 断链于 {miss}")
        for m in LINK_RE.finditer(ln):
            tgt = m.group(1)
            if tgt.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (base / tgt.split("#")[0]).exists():
                v["links"].append(f"死链 {tgt}：{ln.strip()[:60]}")
    return v


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：现行 docs 全绿（第一条——判据写反时这里会全红）----
    docs = sorted(DOCS.glob("*.md"))
    total: dict[str, list[str]] = {r: [] for r in RULES}
    for d in docs:
        got = scan_lines(d.read_text("utf-8").splitlines(), d.parent)
        for r in RULES:
            total[r] += got[r]
    n_v = sum(len(x) for x in total.values())
    rows.append((not n_v,
                 f"好数据放行：docs/ {len(docs)} 份现行文档零违规（手册清账基线）"
                 + (f"　**{n_v} 处**" if n_v else "")))

    # ---- 1–5. 各判据分行报（哪条防线坏了看得见）----
    labels = {
        "commands": "命令真实性：feuille <组> <命令> 全部在路由表",
        "dead": "死入口零容忍：旧管线字面名不回流",
        "scripts": "脚本真实性：提到的 scripts/*.py 全部存在",
        "symbols": "符号真实性：`feuille.*` 引用全部可 import / getattr",
        "links": "链接真实性：相对链接零死链",
    }
    for r in RULES:
        rows.append((not total[r], f"{labels[r]}：{len(total[r])} 处"
                     + (f"　**{total[r][:2]}**" if total[r] else "")))

    # ---- 6. 反向验证：注入必被抓（跑在内存文本上，不动真文件）----
    injections = [
        ("commands", "跑 `uv run feuille bogus cmd` 试试", "未登记命令"),
        ("dead", "./run.ps1 all 全链跑一遍", "死入口 run.ps1"),
        ("dead", "旧探针 qa_shape.py 还在吗", "死入口 qa_*"),
        ("scripts", "见 scripts/verify_ghost.py", "幽灵脚本"),
        ("symbols", "现址 `feuille.rig.ghost_sym`", "幽灵符号"),
        ("links", "细节见 [旧裁定](adr-character-tech.md)", "死链"),
    ]
    for rule, line, label in injections:
        got = scan_lines([line], DOCS)
        rows.append((bool(got[rule]), f"反向：注入「{label}」被「{rule}」判据抓到"
                     + ("" if got[rule] else "　**漏抓**")))

    # 豁免标记的对照断言：带标记的规划位不误伤（否则清账后的文档没法写「未接入」）
    got = scan_lines(["`uv run feuille scene render --scene x`（未接入：渲染线单独立项）"], DOCS)
    rows.append((not got["commands"], "豁免：带「未接入」标记的规划位不计违规（不误伤诚实标注）"))

    return rows


def main() -> int:
    print("=" * 72)
    print("docs 清账门禁（命令 / 脚本 / 符号 / 链接真实性 + 死入口零容忍）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：docs 门禁 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
