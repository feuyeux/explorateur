# -*- coding: utf-8 -*-
"""audit.py — 格律计数审计（④ 内容审计）：计数器库 + 声称 vs 实测驱动

三套音节计数器（印地 Matra / 阿拉伯长短音节 / 希伯来音节）。阿拉伯语计数
按「一核一音节」：辅音+sukun 吞并音节的数法会多数（实测 الصَّبَا 曾被数成 4，
实际 3）。

**机制 / 内容分离**：每语言计数器是**机制**（本模块）；手写音节拆分 SPLITS、
声称表 CLAIMED、语种顺序是**内容**（归内容项目持有）。

**审计纪律（工作流 ④ 检查的三态）**：
1. **手写拆分供人眼复核 + 算法交叉验证，不一致以算法为准并告警**——
   审计结果本身必须可复核，不可复核的审计是装饰。
2. **声称必须可测**：声称与实测不符 = ❌；验证不了的体式声明**主动撤下**，
   「不作声称」是合法的第三态（既不算通过也不算待处理）——
   阿拉伯语古诗律无法自证、希伯来语 Parallelismus 的准则是意义对位不是拍数，
   这两处宁可留白，也不换一个同样验证不了的标签。
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 印地语 Matra
# 规则：辅音记 1，独立元音记 1，依附元音符号（ा ि ी …）记 0，
#       虚音 ् ं ँ ः ़ 与句读 । ॥ 记 0。
_DEV_CONS = set("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह") | set("ऱऴवऩ")
_DEV_IND_V = set("अआइईउऊऋएऐओऔऍऎएऐऑऒओऔ")
_DEV_DEP_V = set("ािीुूृॄॅॆेैॉॊोौॎॏ")
_DEV_IGNORE = set("् ं ँ ः ़ ‍ \n")


def count_hi_matras(text: str) -> int:
    n = 0
    for c in text:
        if c in _DEV_CONS or c in _DEV_IND_V:
            n += 1
        elif c in _DEV_DEP_V or c in _DEV_IGNORE:
            continue
        elif unicodedata.category(c).startswith("M"):
            continue
    return n


def hindi_split(text: str) -> tuple[int, int]:
    """按 । ॥ ，逗号切成前半/后半，返回两段 matra（Doha 13+11 的判定基础）。"""
    parts = [p for p in re.split(r"[।॥，,]", text) if p.strip()]
    if len(parts) >= 2:
        return count_hi_matras(parts[0]), count_hi_matras(parts[1])
    return count_hi_matras(text), 0


# ---------------------------------------------------------------- 阿拉伯语
# 一核一音节：每个「辅音(+元音)」或「ا/و/ي」算一个音节。
# 长 (–) = 长元音 / 带 shadda / 后面是 sukun（闭音节）；短 (⏑) = 短元音开口。
_AR_SHORT_V = set("\u064e\u064f\u0650")          # fatha damma kasra
_AR_LONG_V = set("\u0648\u064a\u0627\u0622\u0623\u0625\u0623\u0671\u0649")
_AR_SUKUN = set("\u0652")
_AR_SHADDA = set("\u0651")
_AR_TANWEEN = set("\u064b\u064c\u064d\u0650\u064b")
_AR_PUNCT = set("\u060c\u061b\u061f.,;:\u2014\u2013 ")
_AR_MARKS = _AR_SHORT_V | _AR_SUKUN | _AR_SHADDA | _AR_TANWEEN | set("\u0670\u0653\u0654\u0655")


def ar_syllables(text: str) -> list[tuple[str, str]]:
    """返回 [(kind, 音节字母串)]，kind ∈ {'-', '⏑'}。"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in _AR_PUNCT or c in _AR_MARKS:
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        syl, longv, step = c, False, 1
        if c in _AR_LONG_V and nxt not in _AR_SHORT_V:
            longv = True
        elif nxt in _AR_LONG_V:
            syl, longv, step = c + nxt, True, 2
        elif nxt in _AR_SHORT_V or nxt in _AR_TANWEEN:
            longv = False
            step = 2
        elif nxt in _AR_SHADDA:
            longv = True
            step = 2
        elif nxt in _AR_SUKUN or nxt == "" or nxt in _AR_PUNCT:
            longv = True
            step = 2
        else:
            longv = True
        out.append(("-" if longv else "⏑", syl))
        i += step
    return out


# ---------------------------------------------------------------- 希伯来语
_HE_MARKS = set("֑־׃׀")
_HE_STRESS = set("ֽֿׁׂׅ")
_HE_POINTS = {chr(c) for c in range(0x05B0, 0x05C8)} - {"־", "׀", "׃"}


def hebrew_syllables(text: str) -> list[str]:
    """希伯来语是「辅音 + 尼库德」拼写，**元音在符号上不在字母上**。
    闭音节优先：带元音的辅音开启音节，不带元音的辅音是前一音节的韵尾
    （`שַׁר` 是一个音节不是两个）。"""
    toks: list[tuple[str, bool]] = []
    for c in unicodedata.normalize("NFC", text):
        if c in _HE_POINTS:
            if toks:
                toks[-1] = (toks[-1][0] + c, True)
            continue
        if c.isspace() or c in _HE_MARKS or c in "—–.,;:׳״":
            toks.append(("|", False))
            continue
        toks.append((c, False))
    out, cur = [], ""
    for letters, has_v in toks:
        if letters == "|":
            if cur:
                out.append(cur)
            cur = ""
            continue
        if has_v:
            if cur:
                out.append(cur)
            cur = letters
        else:
            cur += letters
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- 其余计数器

def count_zh_chars(lines: list[str]) -> list[int]:
    """汉字按字数；七言律句是一整句里两半，逗号才是断句处。"""
    return [len(re.sub(r"[，。；、,.!?]", "", h))
            for ln in lines for h in ln.split("，") if h]


def count_ru_vowels(lines: list[str]) -> list[int]:
    return [sum(1 for c in ln if c in "аеёиоуыэюяАЕЁИОУЫЭЮЯ") for ln in lines]


def count_el_syllables(lines: list[str]) -> list[int]:
    """希腊语：双元音（αι αυ ευ ει οι ου υι ηυ）只算一音节。"""
    diph = {"αι", "αυ", "ευ", "ει", "οι", "ου", "υι", "ηυ"}
    out = []
    for ln in lines:
        s = "".join(c for c in unicodedata.normalize("NFD", ln)
                    if not unicodedata.category(c).startswith("M"))
        n, i = 0, 0
        while i < len(s):
            if s[i] in "αειουηω":
                if s[i:i + 2] in diph:
                    i += 2
                else:
                    i += 1
                n += 1
            else:
                i += 1
        out.append(n)
    return out


def count_de_vowel_groups(lines: list[str]) -> list[int]:
    """德语按元音组；ie/ö 等当一个单元音（die=1、Jahreswende=4）。"""
    de_v = "aeiouäöüy"
    out = []
    for ln in lines:
        s = unicodedata.normalize("NFC", ln).lower()
        s = re.sub(r"sch|ch|ph|th", "X", s)
        n, prev = 0, False
        for c in s:
            if c in de_v:
                if not prev:
                    n += 1
                prev = True
            else:
                prev = False
        out.append(n)
    return out


def count_es_vowel_groups(lines: list[str]) -> list[int]:
    """西语按元音组；元音间的 y 当辅音断。"""
    es_v = "aeiouáéíóúü"
    out = []
    for ln in lines:
        s = unicodedata.normalize("NFC", ln).lower()
        n, prev = 0, False
        for c in s:
            if c in es_v:
                if not prev:
                    n += 1
                prev = True
            else:
                prev = False
        out.append(n)
    return out


def count_ko_blocks(lines: list[str]) -> list[int]:
    """谚文方块一个一音节；组合型字母双写收一个音节。"""
    out = []
    for ln in lines:
        n, jamo = 0, 0
        for c in ln:
            o = ord(c)
            if 0xAC00 <= o <= 0xD7A3:
                n += 1
                jamo = 0
            elif 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
                jamo += 1
                if jamo == 2:
                    n += 1
                    jamo = 0
        out.append(n)
    return out


def count_ar(lines: list[str]) -> list[int]:
    return [len(ar_syllables(ln)) for ln in lines]


def count_he(lines: list[str]) -> list[int]:
    return [len(hebrew_syllables(ln)) for ln in lines]


def count_hi(lines: list[str]) -> list[int]:
    return [count_hi_matras(ln) for ln in lines]


# 计数器注册表：语种 → 函数。**新语种 = 加一行**，不是改逻辑。
COUNTERS = {
    "中文": count_zh_chars, "俄语": count_ru_vowels, "希腊语": count_el_syllables,
    "德语": count_de_vowel_groups, "西班牙语": count_es_vowel_groups,
    "印地语": count_hi, "阿拉伯语": count_ar, "希伯来语": count_he,
    "韩语": count_ko_blocks,
}


def audit_one(lang: str, lines: list[str], *, splits: list[list[str]] | None = None,
              claim: list[int] | None = None, no_claim: bool = False) -> dict:
    """一个语种的审计（纯函数）。

    splits：手写音节拆分（人眼复核用）；claim：声称的数字表；
    no_claim：验证不了的体式声明已主动撤下（合法第三态）。
    返回 {lang, hand, algo, actual, status, warn}——status ∈
    ✅ 相符 / ❌ 声称不符 / ❌ 未登记声称 / ○ 不作声称。
    手写拆分与算法都有且逐行结构一致而数值不同 → 以算法为准并告警。
    """
    hand = [len(p) for p in splits] if splits else None
    algo = COUNTERS[lang](lines) if lang in COUNTERS else None
    actual = algo or hand
    warn = ""
    if hand and algo and len(hand) == len(algo) and hand != algo:
        warn = f"手写拆分 {hand} ≠ 算法 {algo}，以算法为准"
    if no_claim:
        status = "○ 不作声称（主动）"
    elif claim is None:
        status = "❌ 未登记声称值"
    elif actual == claim:
        status = "✅ 相符"
    else:
        status = f"❌ 声称 {claim} 实测 {actual}"
    return {"lang": lang, "hand": hand, "algo": algo, "actual": actual,
            "claim": claim, "status": status, "warn": warn}


def audit_all(items: list[dict]) -> list[dict]:
    """跑一批语种。items: [{lang, lines, splits?, claim?, no_claim?}]。
    bad = ❌ + 有告警的条数（供退出码）。"""
    rows = [audit_one(**it) for it in items]
    for r in rows:
        print(f"{r['lang']:<6} {r['status']:<24} 实测 {r['actual']}"
              + (f"　⚠ {r['warn']}" if r["warn"] else ""))
    passed = sum(r["status"].startswith("✅") for r in rows)
    no_claims = sum(r["status"].startswith("○") for r in rows)
    bad = sum(r["status"].startswith("❌") for r in rows) + sum(bool(r["warn"]) for r in rows)
    print(f"\n实测通过 {passed} · 不作声称 {no_claims} · 需处理 {bad} / 共 {len(rows)} 语种")
    return rows
