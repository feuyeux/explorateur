#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_audit.py — 格律审计 / 节替换 / 打包的反向验证

第 0 条好数据放行（自包含合成夹具，不依赖任何 examples 项目数据）：
合成多语诗稿的每个计数器都命中**手工独立数出**的期望值（防循环
验证——期望值不用被测算法反推）；audit_all 全批跑 = 三态汇总
「通过 3 · 不作声称 1 · 需处理 0」。

反向各防一种退化：
- 声称不符 → ❌；无声称 → ❌；**验证不了的声明主动撤下 → ○ 第三态**
  （既不算通过也不算待处理——「宁可留白」的诚实纪律）
- 手写拆分与算法都存在而不一致 → 以算法为准并告警
- 节替换：幂等（重复执行结果一致）、RTL 文本原样保留、找不到节当场报错
- 打包：非 ASCII 文件名必须置 UTF-8 flag（Info-ZIP 不置位的教训）
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import audit, packaging, section_patch as sp   # noqa: E402
from feuille.errors import FeuilleError   # noqa: E402

# 合成多语诗稿（自包含夹具）。每行期望值都是手工独立数出的，不用被测
# 算法反推（防循环验证）：
# - 印地 Doha：辅音/独立元音记 1 matra，依附元音符号（ा ि ी…）与虚音
#   （् ं ़）记 0；逗号前半 13 + 后半 11 = 整行 24；
# - 阿语一核一音节（辅音+短元音=⏑；长元音字母/闭音节/叠音=-）；
# - 希语闭音节优先（带 nikkud 的辅音开新音节，不带的并进前一音节韵尾）；
# - 中文句读不计、逗号分半句按字数；俄语数 аеёиоуыэюя（大小写都数）；
# - 希腊去变音符后小写、双元音（αι αυ ευ ει οι ου υι ηυ）算一；
# - 德语 sch/ch/ph/th→X 后数元音组（ie/ö 当一）；西语数元音组；
# - 韩语谚文方块一音节、组合型 jamo 双写收一。
POEM = {
    "中文": ["秋风吹尽满山金，一叶知秋天地心。"],                      # [7, 7]
    "印地语": ["एक पत्ता गिरा शीतकाल आया, पेड़ नंगे हुए धरती ठंडी।",  # 24 = 13+11
              "ठंडी हवा चली सूखे पत्ते झड़े, धरती ठंडी पेड़ नंगे खड़े।"],
    "阿拉伯语": ["الرِّيحُ تَهُبُّ وَالوَرَقُ يَسْقُطُ",                 # 17
                "القَمَرُ يَشْرَقُ عَلى الوُرُودِ"],                    # 16
    "希伯来语": ["סְתָיו בָּא, הָרוּחַ קָרָה",                       # 8
                "עָלֶה נוֹפֵל עַל הָאָרֶץ"],                           # 9
    "俄语": ["Лист одинок, но лес богат.",                          # 8
            "Осень идёт, и лист летит."],                           # 8
    "希腊语": ["Ένα φύλλο πέφτει σιγά.", "Ο ουρανός αλλάζει χρώμα."],  # [8, 9]
    "德语": ["Das Blatt fällt auf den stillen See.",                # 8
            "Still schweigt die Welt, wie sie will."],              # 7
    "西班牙语": ["La hoja cae, el viento la lleva.", "El otoño canta."],  # [10, 6]
    "韩语": ["단풍 드는 가을밤", "바람 불면 낙엽도",
            "높은 하늘 구름도", "모두 가을 길 따라"],                  # 7×4
}


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-audit-")
    d = pathlib.Path(tmp.name)

    # ---- 0a. 计数器对合成诗稿命中手数期望值 ----
    got = audit.count_hi(POEM["印地语"])
    rows.append((got == [24, 24], f"印地语 Matra = {got}（Doha 24 = 13+11）"))
    a, b = audit.hindi_split(POEM["印地语"][0])
    rows.append(((a, b) == (13, 11), f"Doha 前后半 = {a}+{b}（13+11）"))
    got = audit.count_ar(POEM["阿拉伯语"])
    rows.append((got == [17, 16], f"阿拉伯语音节 = {got}（一核一音节 17+16）"))
    got = audit.count_he(POEM["希伯来语"])
    rows.append((got == [8, 9], f"希伯来语音节 = {got}（闭音节优先 8+9）"))
    rows.append((audit.count_zh_chars(POEM["中文"]) == [7, 7],
                 "中文按字数（逗号才是断句处）= 7+7"))
    rows.append((audit.count_ru_vowels(POEM["俄语"]) == [8, 8],
                 "俄语元音 = 8+8"))
    rows.append((audit.count_el_syllables(POEM["希腊语"]) == [8, 9],
                 "希腊语音节（双元音算一；句首大写元音也数）= 8+9"))
    rows.append((audit.count_de_vowel_groups(POEM["德语"]) == [8, 7],
                 "德语元音组（sch→X、ie/ee 算一）= 8+7"))
    rows.append((audit.count_es_vowel_groups(POEM["西班牙语"]) == [10, 6],
                 "西语元音组 = 10+6"))
    rows.append((audit.count_ko_blocks(POEM["韩语"]) == [7, 7, 7, 7],
                 "韩语谚文方块 = 7×4"))
    rows.append((audit.count_ko_blocks(["ㄱㅏㄴ"]) == [1],
                 "韩语组合型字母双写收一（ㄱㅏㄴ = 1）"))

    # ---- 0b. audit_all 全批跑：三态汇总 ----
    items = [
        {"lang": "中文", "lines": POEM["中文"], "claim": [7, 7]},
        {"lang": "俄语", "lines": POEM["俄语"], "claim": [8, 8]},
        {"lang": "希腊语", "lines": POEM["希腊语"], "claim": [8, 9]},
        {"lang": "阿拉伯语", "lines": POEM["阿拉伯语"], "no_claim": True},
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = audit.audit_all(items)
    tail = [ln for ln in buf.getvalue().splitlines() if ln.startswith("实测通过")][0]
    rows.append((all(r["status"].startswith("✅") for r in res[:3])
                 and res[3]["status"].startswith("○")
                 and "通过 3" in tail and "不作声称 1" in tail and "需处理 0" in tail,
                 f"全批跑 = 三态齐（{tail.strip()}）"))

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
    except FeuilleError:
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
