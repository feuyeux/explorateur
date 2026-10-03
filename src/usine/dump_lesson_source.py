#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 lessons/<id>/scene.json 导成人可读 / agent 可读的逐语种源文本，供逐句解析委派使用。

事实源是 lessons/<id>/scene.json（由 parse_scene.py 从 lessons/<id>/scene.md 抽取），本脚本只排版不改写。
输出：lessons/<id>/analysis/_source/<locale>.md，14 个语种各一份。

用法：
    uv run usine-dump-lesson                                # colors 课全部语种
    uv run usine-dump-lesson --scene colors --only ja-JP    # 指定课程/语种
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from usine import ROOT
from .parse_scene import analysis_dir, find_scene_ids, scene_paths

ROLE_CN = {
    "open": "开场",
    "reply": "接话",
    "round": "六色问答",
    "summary": "小结",
    "bye": "道别",
}


def dump(locale: str, data: dict, scene: dict) -> str:
    node = data["locales"][locale]
    dlg = node["dialogue"]
    prop = node.get("prop", {}) or {}
    dev = prop.get("device", {}) or {}

    L: list[str] = []
    L.append(f"# {locale}　{node.get('langLabel', '')}")
    L.append("")
    L.append(f"- A（活泼先问）：{node.get('aName', '')}")
    L.append(f"- B（沉稳后答）：{node.get('bName', '')}")
    L.append(f"- 舞台：{node.get('stage', '')}")
    L.append(f"- 舞台装置：{prop.get('label', '')}")
    L.append(f"- 装置描述：{prop.get('desc', '')}")
    L.append(f"- 装置样式：style={dev.get('style', '')}　shape={dev.get('shape', '')}"
             f"　井={dev.get('cellW', '')}×{dev.get('cellH', '')}")
    L.append(f"- 出场场景：{', '.join(prop.get('scenes', []))}")
    if node.get("notes"):
        L.append(f"- 创作注记（源文档原文）：{node['notes']}")
    if locale in scene.get("rtlLocales", []):
        L.append("- 版式：RTL（文字右起、名牌镜像、A/B 站位对调）")
    L.append("")

    L.append("## 六色词表")
    L.append("")
    L.append("| 色 | 原词 | 其他形式 | 注音 |")
    L.append("| --- | --- | --- | --- |")
    for t in scene.get("tokenWords", {}).get(locale, []):
        hexc = scene.get("tokens", {}).get(t["key"], "")
        forms = " / ".join(t.get("forms", [])) or "—"
        L.append(f"| {t['key']} {hexc} | {t['word']} | {forms} | {t.get('romanization') or '—'} |")
    L.append("")

    L.append("## 逐句原文（17 行）")
    L.append("")
    for d in dlg:
        chip = d.get("tokenChip") or ""
        chip_s = f"　chip={chip}" if chip and str(chip).startswith("#") else ""
        L.append(
            f"### 第 {d['i']} 行　{ROLE_CN.get(d.get('role', ''), d.get('role', ''))}"
            f"　说话人={d.get('speaker', '—')}"
            f"　情绪={d.get('mood', '—')}"
            f"　类型={'问句' if d.get('isQuestion') else '答句'}"
        )
        if d.get("tokenKey"):
            L.append(f"- 对应色：{d['tokenKey']}（色词 {d.get('tokenWord', '')}）{chip_s}")
        if d.get("bubble"):
            L.append(f"- 气泡：{d['bubble'].get('kind', '')} / {d['bubble'].get('text', '')}")
        if d.get("gesture"):
            L.append(f"- 手势词：{d['gesture'].get('word') or '—'}"
                     f"　姿态={'/'.join(d['gesture'].get('poses', []))}")
        if d.get("exits"):
            L.append("- A 出画")
        L.append(f"- **原文**：{d.get('text', '')}")
        L.append(f"- **注音**：{d.get('romanization') or '—'}")
        L.append(f"- **中文翻译**：{d.get('gloss', '')}")
        if d.get("note"):
            L.append(f"- **文化/语言注记**：{d['note']}")
        L.append("")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="lessons/<id>/scene.json → 逐语种解析源文本（只排版不改写）")
    ap.add_argument("--scene", default="colors", choices=find_scene_ids(),
                    help="课程 id（对应 lessons/<id>/；缺省 colors）")
    ap.add_argument("--only", default="", help="逗号分隔的 locale 列表，如 zh-CN,ja-JP")
    args, extra = ap.parse_known_args()
    _, scene_json = scene_paths(args.scene)
    if not scene_json.exists():
        print(f"缺少 {scene_json.relative_to(ROOT)}，先跑：uv run usine-parse --scene {args.scene}",
              file=sys.stderr)
        return 1
    scene = json.loads(scene_json.read_text(encoding="utf-8"))
    locales = ([x.strip() for x in args.only.split(",") if x.strip()] or extra
               or list(scene["locales"].keys()))
    out_dir = analysis_dir(args.scene) / "_source"
    out_dir.mkdir(parents=True, exist_ok=True)
    for lc in locales:
        if lc not in scene["locales"]:
            print(f"跳过未知语种 {lc}", file=sys.stderr)
            continue
        out = out_dir / f"{lc}.md"
        out.write_text(dump(lc, scene, scene), encoding="utf-8")
        print(f"{out.relative_to(ROOT)}  ({len(scene['locales'][lc]['dialogue'])} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
