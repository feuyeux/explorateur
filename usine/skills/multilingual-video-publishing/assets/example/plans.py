# -*- coding: utf-8 -*-
"""plans.py — 《四季》多语种发布清单（抖音竖版 / B站横版）

把 `小红书文案.md`（文案单一事实源）+ `voice/` 的语种表组装成
`feuille.manifest.build_manifest` 认得的 plans 契约。

**为什么竖版发抖音、横版发 B 站**（2026-10-08 用户拍板）：
- 抖音信息流吃竖版，封面 3:4 与本项目 1080×1440 封面原生一致；
- B 站是横屏观感，横版 1280×720 不浪费两侧。

**平台分工的实测边界**（不要照搬到别的平台）：
- 抖音合集：`collections.py` 全流程支持，本批建集收12 条；
- B 站合集：**需创作中心 Lv2**，等级不够时 UI 是灰字、无可点控件，无法绕过
  （`collections.py` 头注第 18-19 行），所以本批 B 站**只裸投稿、不建集**。

**标题按平台字数倒推**（手册铁律，不要把抖音标题搬去 B 站再修）：
- 抖音 ≤30 字 / B 站 ≤80 字；
- 源文案标题本来是按小红书 ≤20 字写的，所以两边都够用；
- 但**每批都要实测 len()**，不信任何手标字数。

用法：
    uv run python examples/sijijie/plans.py            # 只校验，不发布
    uv run --group publish python examples/sijijie/plans.py --go
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille import manifest as M          # noqa: E402

COPY = ROOT / "小红书文案.md"
OUT = ROOT / "build" / "publish-manifest.json"

# 文案里的 12 语种 → 成片文件名前缀。与 配文.py 的 WINDOWS 同源，
# 顺序按成片实际存在的语种，不按文案顺序。
# ⚠️ 这里的 locale 是 **edge-tts 声音的语言标记**（配文.py 的 VOICES 用
# ar-EG-SalmaNeural，故阿拉伯语记 ar-EG），不是 languages/ 注册表的键
# （注册表只有 ar-SA——那边按「新增语种=新建目录」管理）。build_manifest
# 对 locale 只透传不解析，不会拿它查注册表；真要按注册表取字体/引号时，
# 别用这个字段。
LOCALES = {
    "中文": "zh-CN", "英语": "en-US", "德语": "de-DE", "法语": "fr-FR",
    "西班牙语": "es-ES", "俄语": "ru-RU", "阿拉伯语": "ar-EG",
    "希伯来语": "he-IL", "印地语": "hi-IN", "希腊语": "el-GR",
    "日语": "ja-JP", "韩语": "ko-KR",
}

# 版式 → 成片名前缀 / 封面名前缀（**用中文语种名，不用 locale**）。
# 实测：本项目的成片叫 `竖版四季_俄语.mp4`、封面叫 `01_横版_中文.png`，
# 两者命名体系不同（成片无序号、封面有序号），不能拼同一个 key。
# ⚠️ 这里第一版写成了 locale（`竖版四季_ru-RU.mp4`），被素材存在性前置校验
# 全批拦下——那道闸门就是为「猜错命名」准备的，宁可现在报。
LAYOUTS = {
    "douyin":  {"video": "竖版四季_", "cover": "竖版", "offset": 12,
                "zone": "竖版", "label": "竖版"},
    "bilibili": {"video": "横版四季_", "cover": "横版", "offset": 0,
                 "zone": "横版", "label": "横版"},
}

_SEC = re.compile(r"^##\s+(\d+)\s*·\s*(\S+)\s*$")
# ⚠️ 封口条件：**任何标题行都封口**，不只是同级的二级标题。
# 文案尾部有 `## 附：可以直接抄的标签池`（二级但不是 `## N · 语言`）和
# `## 附：24 条对应关系`，还有一级 `# 横版（1280×720）` 版式分隔。
# 只认 `_SEC` 会让**最后一节**（12 · 韩语）一路吞到文件末尾——
# 实测后果：标签池里 19 个标签被当成韩语那条的话题（6 → 25），已发出去了。
_ANY_HEAD = re.compile(r"^#{1,3}\s+\S")
# 版式分区标题：`# 横版（1280×720）` / `# 竖版（720×1280）`
_ZONE = re.compile(r"^#\s+(横版|竖版)")
_TITLE = re.compile(r"^\*\*标题\*\*：(.+)$", re.M)
_TOPIC = re.compile(r"(?:^|\s)#([^\s#]+)", re.M)


def parse_copy(path: Path) -> dict[tuple[str, str], dict]:
    """`小红书文案.md` → `{(版式, 语种): {title, body, topics}}`。

    **键必须带版式**：文案里横竖两版各有 12 节、**语种名完全相同**。
    只按语种存 dict 会让后一版覆盖前一版——实测两个平台都拿到了竖版文案，
    而它们要投的成片是不同版式，文案与成片对不上。

    **不复用 manifest.parse_copy**：那份要求 `### NN · 语言 `locale`` + 三段
    fence 体例，本项目是 `## N · 语言` + `**标题**：…`。宁可各写各的解析器，
    也不要为了「统一」去改文案事实源。
    """
    text = Path(path).read_text("utf-8")
    out: dict[tuple[str, str], dict] = {}
    zone = ""
    cur_lang = None
    body: list[str] = []

    def seal():
        nonlocal cur_lang, body
        if cur_lang:
            out[(zone, cur_lang)] = _seal(cur_lang, body)
        cur_lang, body = None, []

    for line in text.split("\n"):
        mz = _ZONE.match(line)
        if mz:
            seal()
            zone = mz.group(1)
            continue
        m = _SEC.match(line)
        if m:
            seal()
            cur_lang, body = m.group(2), []
            continue
        # 任何其它标题行（附录等）都封口——否则最后一节会吞掉整个文件尾
        if _ANY_HEAD.match(line):
            seal()
            continue
        if cur_lang is not None:
            body.append(line)
    seal()

    miss = [z for z in ("横版", "竖版") if not any(k[0] == z for k in out)]
    if miss:
        raise SystemExit(f"文案缺版式分区 {miss}——体例被改了 → 拒解析")
    return out


def _seal(lang: str, lines: list[str]) -> dict:
    blob = "\n".join(lines)
    mt = _TITLE.search(blob)
    if not mt:
        raise SystemExit(f"{lang}: 缺「**标题**：」，体例被改了 → 拒解析")
    title = mt.group(1).strip()
    rest = blob[: mt.start()] + blob[mt.end():]
    topics = _TOPIC.findall(rest)
    # 正文 = 去掉话题行、去掉分隔线后的全部文字
    paras = [p.strip() for p in rest.split("\n\n")]
    body = "\n".join(
        p for p in paras
        if p and not p.startswith("---") and not p.lstrip().startswith("#")
    ).strip()
    return {"title": title, "body": body, "topics": topics}


def build() -> tuple[dict, list[str]]:
    recs = parse_copy(COPY)
    plans = {}
    for plat, cfg in LAYOUTS.items():
        # 每个平台取**与成片同版式**的文案：抖音投竖版就用竖版文案。
        zone = cfg["zone"]
        picked = [(lang, r) for (z, lang), r in recs.items() if z == zone]
        if not picked:
            raise SystemExit(f"{plat}: 文案里没有「{zone}」分区")

        def video(r, _c=cfg):
            return ROOT / f"{_c['video']}{r['lang']}.mp4"

        def cover(r, _c=cfg):
            # 封面序号是**全局**的：01–12 横版、13–24 竖版，不是各版式从 01 重开。
            return ROOT / "封面" / f"{r['order'] + _c['offset']:02d}_{_c['cover']}_{r['lang']}.png"

        def cover_bili(r, _c=cfg):
            # B 站必须用**独立出的 4:3 封面**：3:4 封面被 B 站按 4:3 居中裁切后
            # 底部标题整块消失（实测）。见 references/platform-capabilities.md §3。
            return ROOT / "封面_bili" / f"{r['order']:02d}_横版_{r['lang']}.png"

        entries = []
        for i, (lang, r) in enumerate(picked, 1):
            entries.append({
                "order": i, "lang": lang, "locale": LOCALES[lang],
                "title": r["title"], "body": r["body"], "topics": r["topics"],
            })
        plans[plat] = {"copy": COPY, "entries": entries, "video": video,
                       "cover": cover_bili if plat == "bilibili" else cover}
    return M.build_manifest(plans, out_path=OUT)


def report(man: dict, problems: list[str]) -> int:
    for plat, tasks in man.items():
        lim = M.PLATFORMS[plat]["titleMax"]
        print(f"\n=== {M.PLATFORMS[plat]['label']}（{len(tasks)} 条 · 标题上限 {lim}）===")
        for t in tasks:
            v, c = Path(t["video"]), Path(t["cover"])
            flag = "✓" if (v.exists() and c.exists()) else "✗"
            over = "  ⚠超限" if len(t["title"]) > lim else ""
            print(f"  {flag} [{t['no']:02d}] {t['lang']:<5} {t['title']}"
                  f"  ({len(t['title'])}字){over}")
    print()
    if problems:
        print(f"❌ {len(problems)} 项问题：")
        for p in problems:
            print("   ·", p)
        return 1
    print(f"✅ 清单齐：{sum(len(v) for v in man.values())} 条，素材全部在盘")
    print(f"   落盘：{OUT}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true",
                    help="校验通过后立即发布（不加则只校验）")
    args = ap.parse_args()

    man, problems = build()
    rc = report(man, problems)
    if rc or not args.go:
        return rc

    from feuille.publish import bilibili, douyin
    # 顺序：先抖音（要建集）→ 再 B 站（裸投稿）
    print("\n▶ 抖音 12 条竖版")
    rc |= douyin.publish(man["douyin"], log_dir=str(ROOT / "build" / "douyin"))
    print("\n▶ B站 12 条横版")
    rc |= bilibili.publish(man["bilibili"], log_dir=str(ROOT / "build" / "bilibili"))
    return rc


if __name__ == "__main__":
    sys.exit(main())