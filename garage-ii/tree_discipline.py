#!/usr/bin/env python3
"""tree_discipline.py —— 树级「纪律留存」检查：演化有没有**动纪律**。

## 为什么要有这一条

`bench_usine.py` 的判据全是**产物级**的（产物在不在、工具面用没用、绕没绕行）。
它们**看不见** harness 自己被改成了什么样——于是有一条盲区：

> 演化器为了加一条知识，顺手把系统提示里的纪律条目**删掉或改写**了，
> 产物照样交得出来，判据照样全过。

2026-10-20 实测就是这样：`tree-dom1-v4` 把 `systemprompt.md` 的「工作方式」
从 5 条改写成 3 条，**「交付物写进当前工作区的项目目录，不写 Desktop/Downloads/
临时目录」整条没了**。同批 rollout 的分数一点没动（两臂都是 80%）。

## 这一条量的是什么

- `systemprompt.md` 里「工作方式」的编号条目（纪律）；
- `guardrails.md` 里的编号红线（纪律）。

**不是**「判据里过没过」，是「harness 还带不带这些纪律」。它给出的是
**树对树**的差异，不是 rollout 对 rollout 的分布——所以它**不参与置换检验**，
只作为「演化做了什么」的旁证。

## 口径

条目按「去掉序号后的正文」比：改个说法算**改写**（正文不一致），
删掉一条算**丢失**。空行、markdown 装饰、触发句不算纪律条目。

## 用法

```sh
python3 garage-ii/tree_discipline.py --base garage-ii/harness_base --tree <树目录>
```

退出码 0 = 纪律一条没少、没被改写；1 = 有丢失或改写。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: 编号条目：`1. …` / `2. …`（markdown 列表）。
_NUMBERED = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")
#: 「工作方式」这类小节标题（**不是**纪律条目本身）。
_SECTION_HEAD = re.compile(r"^\s*#{1,6}\s")
#: 触发句这类「加进来的一句话」不算纪律——判据只比「原来那几条还在不在、还一样吗」。
_TRIGGER = re.compile(r"(加载\s*`|`\w[\w-]*`\s*技能|触发句|skill)", re.I)


def _numbered_items(text: str) -> dict[str, str]:
    """抽出编号条目：{序号: 正文}。标题行与空行不算条目。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if _SECTION_HEAD.match(line):
            continue
        m = _NUMBERED.match(line)
        if not m:
            continue
        body = m.group(2).strip()
        if not body or _TRIGGER.search(body):
            continue
        out[m.group(1)] = body
    return out


def _guard_lines(text: str) -> list[str]:
    """红线条目：编号开头的整行（正文去掉序号）。"""
    out: list[str] = []
    for line in text.splitlines():
        m = _NUMBERED.match(line)
        if m and m.group(2).strip():
            out.append(m.group(2).strip())
    return out


def compare_trees(base: Path, tree: Path) -> dict[str, object]:
    """比两棵树的纪律留存。"""
    report: dict[str, object] = {"base": str(base), "tree": str(tree), "files": {}}
    for name, extract in (
        ("systemprompt.md", _numbered_items),
        ("guardrails.md", _guard_lines),
    ):
        b_file, t_file = base / name, tree / name
        if not b_file.exists():
            continue
        b_items = extract(b_file.read_text(encoding="utf-8"))
        t_items = extract(t_file.read_text(encoding="utf-8")) if t_file.exists() else {}
        if isinstance(b_items, dict):
            b_set = set(b_items.values())
            t_set = set(t_items.values())
            missing = sorted(x for x in b_set if x not in t_set)
            added = sorted(x for x in t_set if x not in b_set)
            changed = []
            for num, body in b_items.items():
                if body in t_set:
                    continue
                # 序号还在但正文换了 → 改写
                if num in t_items:
                    changed.append({"no": num, "base": body, "tree": t_items[num]})
        else:
            b_set = set(b_items)
            t_set = set(t_items)
            missing = sorted(x for x in b_set if x not in t_set)
            added = sorted(x for x in t_set if x not in b_set)
            changed = []
        report["files"][name] = {
            "n_base": len(b_set),
            "n_tree": len(t_set),
            "missing": missing,
            "rewritten": changed,
            "added": added,
            "ok": not missing and not changed,
        }
    files = report["files"]  # type: ignore[assignment]
    report["ok"] = all(bool(v.get("ok")) for v in files.values()) if files else False
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="树级纪律留存检查")
    ap.add_argument("--base", default="garage-ii/harness_base")
    ap.add_argument("--tree", action="append", required=True, help="树目录（可重复）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args(argv)

    base = Path(args.base).expanduser().resolve()
    reports = [compare_trees(base, Path(t).expanduser().resolve()) for t in args.tree]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=1))
        return 0 if all(r["ok"] for r in reports) else 1

    bad = False
    for rep in reports:
        print(f"== {rep['tree']}")
        for name, f in rep["files"].items():  # type: ignore[union-attr]
            if f["ok"]:
                print(f"   {name}: {f['n_base']} 条纪律全在，一条没改")
                continue
            bad = True
            print(f"   {name}: 基准 {f['n_base']} 条 → 树里 {f['n_tree']} 条")
            for m in f["missing"]:
                print(f"     ✗ 丢失：{m[:100]}")
            for c in f["rewritten"]:
                print(f"     ✗ 改写：{c['no']} {c['base'][:60]} → {c['tree'][:60]}")
            for a in f["added"]:
                print(f"     + 新增：{a[:100]}")
    print()
    print("纪律留存：全绿" if not bad else "纪律留存：**有丢失或改写**")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
