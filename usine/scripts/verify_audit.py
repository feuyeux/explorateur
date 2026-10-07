#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_audit.py — 格律审计 / 节替换 / 打包的反向验证

第 0 条好数据放行（真实数据，最强口径）：示例项目 12 语种全量重跑 =
METER-AUDIT 定稿结论「实测通过 10 · 不作声称 2 · 需处理 0」；
各计数器对审计过的真实诗稿命中定稿值（印地 24+24 Matra、阿语 17+17、
希语 11+11、中 7+7、俄 8+8、希 12+12……）。

反向各防一种退化：
- 声称不符 → ❌；无声称 → ❌；**验证不了的声明主动撤下 → ○ 第三态**
  （既不算通过也不算待处理——「宁可留白」的诚实纪律）
- 手写拆分与算法都存在而不一致 → 以算法为准并告警
- 节替换：幂等（重复执行结果一致）、RTL 文本原样保留、找不到节当场报错
- 打包：非 ASCII 文件名必须置 UTF-8 flag（Info-ZIP 不置位的教训）
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import audit, packaging, section_patch as sp   # noqa: E402

HERE = ROOT / "examples" / "yiyezhiqiu"
CAST = json.loads((HERE / "data" / "poem-cast.json").read_text("utf-8"))


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-audit-")
    d = pathlib.Path(tmp.name)

    # ---- 0a. 计数器对真实诗稿命中定稿值 ----
    got = audit.count_hi(CAST["印地语"]["text"])
    rows.append((got == [24, 24], f"印地语 Matra = {got}（定稿 24+24）"))
    a, b = audit.hindi_split(CAST["印地语"]["text"][0])
    rows.append(((a, b) == (13, 11), f"Doha 前后半 = {a}+{b}（定稿 13+11）"))
    got = audit.count_ar(CAST["阿拉伯语"]["text"])
    rows.append((got == [17, 17], f"阿拉伯语音节 = {got}（定稿 17+17）"))
    got = audit.count_he(CAST["希伯来语"]["text"])
    rows.append((got == [11, 11], f"希伯来语音节 = {got}（定稿 11+11）"))
    rows.append((audit.count_zh_chars(CAST["中文"]["text"]) == [7, 7],
                 "中文按字数（逗号才是断句处）= 7+7"))
    rows.append((audit.count_ru_vowels(CAST["俄语"]["text"]) == [8, 8],
                 "俄语元音 = 8+8"))
    rows.append((audit.count_el_syllables(CAST["希腊语"]["text"]) == [12, 12],
                 "希腊语音节（双元音算一）= 12+12"))
    rows.append((audit.count_de_vowel_groups(CAST["德语"]["text"]) == [10, 10],
                 "德语元音组 = 10+10"))
    rows.append((audit.count_es_vowel_groups(CAST["西班牙语"]["text"]) == [11, 11],
                 "西语元音组 = 11+11"))
    rows.append((audit.count_ko_blocks(CAST["韩语"]["text"]) == [7, 7, 7, 7],
                 "韩语谚文方块 = 7×4"))

    # ---- 0b. 全量重跑 = 定稿结论 ----
    r = subprocess.run([sys.executable, str(HERE / "meter_audit.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    tail = [ln for ln in r.stdout.splitlines() if ln.startswith("实测通过")][0]
    rows.append((r.returncode == 0 and "通过 10" in tail and "不作声称 2" in tail
                 and "需处理 0" in tail,
                 f"示例全量重跑 = 定稿结论（{tail.strip()}）"))

    # ---- 1. 三态审计逻辑（纯函数定向验证）----
    ok = audit.audit_one("中文", ["霜柯初陨知天地，晴旭微倾值万金。"],
                         claim=[7, 7])
    rows.append((ok["status"].startswith("✅"), "声称与实测相符 → ✅"))
    bad = audit.audit_one("中文", ["一二三四五六七，一二三四五六七。"],
                         claim=[5, 5])
    rows.append((bad["status"].startswith("❌") and "实测 [7, 7]" in bad["status"],
                 f"声称不符 → ❌（{bad['status']}）"))
    nc = audit.audit_one("中文", ["一二三四五六七"], claim=None, no_claim=True)
    rows.append((nc["status"].startswith("○"), "主动不作声称 → ○ 第三态（不算失败）"))
    un = audit.audit_one("中文", ["一二三"], claim=None)
    rows.append((un["status"].startswith("❌") and "未登记" in un["status"],
                 "无声称且未声明不作声称 → ❌ 未登记"))

    # 手写拆分与算法不一致 → 以算法为准并告警
    mixed = audit.audit_one("俄语", ["Один листок"],
                            splits=[["О", "дин", "ли", "сток", "лишний"]],
                            claim=None)
    rows.append((bool(mixed["warn"]) and mixed["actual"] == mixed["algo"],
                 f"手写 ≠ 算法 → 以算法为准并告警（{mixed['warn'][:24]}…）"))

    # ---- 2. 节替换：幂等 / RTL / 找不到节 ----
    copy = d / "copy.md"
    ar_line = "نَزَلَ الْوَرَقُ وَهَبَّتِ الصَّبَا"
    copy.write_text(
        "# 标题\n\n### 01 · 中文 `zh-CN`\n**标题**（3 字）\n```\n旧标题\n```\n\n"
        f"### 02 · 阿拉伯语 `ar-SA` · 00:15\n```\n{ar_line}\n```\n", "utf-8")
    sp.replace(copy, {"01": "### 01 · 中文 `zh-CN`\n**标题**（3 字）\n```\n新标题\n```"})
    sp.replace(copy, {"01": "### 01 · 中文 `zh-CN`\n**标题**（3 字）\n```\n新标题\n```"})
    text = copy.read_text("utf-8")
    rows.append(("新标题" in text and "旧标题" not in text,
                 "节替换生效且幂等（重复执行结果一致）"))
    rows.append((ar_line in text and text.count(ar_line) == 1,
                 "RTL 阿语节原样保留（按节标题定位，不做字符串手术）"))
    rows.append((sp.split_sections(text)["02"].startswith("### 02"),
                 "节头带时长与不带时长两版体例都解析"))
    try:
        sp.replace(copy, {"99": "…"})
        rows.append((False, "找不到节必须报错——没报"))
    except SystemExit:
        rows.append((True, "找不到节 → 当场报错"))

    # ---- 3. 打包：非 ASCII 文件名置 UTF-8 flag ----
    src = d / "pack"
    (src / "子目录").mkdir(parents=True)
    (src / "子目录" / "中文_抖音封面.png").write_bytes(b"x")
    (src / "普通.txt").write_bytes(b"x")
    zp = packaging.zip_tree(src, d / "out.zip")
    rows.append((packaging.has_utf8_flag(zp, "子目录/中文_抖音封面.png"),
                 "非 ASCII 文件名置 UTF-8 flag 0x800（Info-ZIP 不置位的教训）"))
    import zipfile
    with zipfile.ZipFile(zp) as zf:
        rows.append((sorted(zf.namelist()) == ["子目录/中文_抖音封面.png", "普通.txt"],
                     "zip 条目与相对路径一致"))
    return rows


def main() -> int:
    print("=" * 72)
    print("格律审计 / 节替换 / 打包（audit / section_patch / packaging）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：格律审计 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
