#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_publish_copy.py — 发布词自检（零平台流量，零外部依赖）

写完 `publish/*.md` 之后、在交给 `multilingual-video-publishing` 之前必跑。
本脚本只读本地 markdown，**不碰任何平台**，所以可以随时跑、随便跑。

检查项（每项都有可观测判据，「机检门」与 SKILL.md `## 验收判据` 表一一对应
——纪律 6：不变量必须有机检；指不出脚本就不算判据）：

1. **必需 H2 段落齐全** — `check_required_sections`
2. **标题字数** — 小红书 ≤20 / 抖音 ≤30 / B站 ≤80（publish-playbook §2 同源）
3. **话题末尾尾随空格** — 抖音 + 小红书必带；B 站无 #tag 区免检
4. **互动钩短语** — 报数 / 点单 / 跟读 / 催更 / 评论区 / 弹幕 / 敢不敢
   （单字「敢」被否决——勇敢 / 不敢 / 哪里敢 都会撞，太松）
5. **置顶话术** — 发布贴士里同时出现「置顶」+ 引号示例（"..." 或 「...」）
6. **no-hard-wrap 零违规** — 与 `~/.agents/skills/markdown-no-hard-wrap/SKILL.md`
   §自查的判定逻辑对齐（drift 风险：本脚本是上游 heredoc 的内联副本，
   上游改判据时这里要同步改——见 _no_hard_wrap_violations 上方注释）
7. **AI 指纹零命中** — `check_ai_fingerprint`：只查**读者面**（标题 + 正文/文案/
   简介），发布贴士是写给操作者的（允许提规则本身），不在扫描面内。
   机检的是**可枚举签名**（字面词 / 句首「原来…」/ 连续感叹号 / 像 X 一样的 Y /
   一行 emoji 滥用）；语感判不了的部分仍归编辑走查（SKILL.md 失败模式末条）
8. **数字可溯源** — `check_fact_provenance`（`--facts facts.json` 给了才跑；
   没给就 SKIP，SKIP 不是 PASS）：读者面文字里出现的**每个数字**都要能在
   事实表里找到出处。「编造规格」是本 skill 最严重的失败模式——这一条把
   「事实 vs 成品」从编辑走查降级成机检

用法：
    python3 check_publish_copy.py <publish_dir>
    python3 check_publish_copy.py <publish_dir> --facts facts.json
    python3 check_publish_copy.py <publish_dir> --strict
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

# 平台硬约定（与 SKILL.md `## 各平台规格`、publish-playbook §2 同源）
PLATFORM = {
    "xiaohongshu": {
        "filename": "xiaohongshu.md",
        "title_max": 20,
        "required_h2": ["标题（20 字内）", "正文", "话题标签", "发布贴士"],
        "body_section": "正文",
        "tags_section": "话题标签",
        "tag_style": "hash",  # #xxx 风格；末尾必带尾随空格
    },
    "douyin": {
        "filename": "douyin.md",
        "title_max": 30,
        "required_h2": ["文案", "话题", "发布贴士"],
        "body_section": "文案",
        "tags_section": "话题",
        "tag_style": "hash",  # 同上
    },
    "bilibili": {
        "filename": "bilibili.md",
        "title_max": 80,
        "required_h2": ["标题", "简介", "标签", "发布贴士"],
        "body_section": "简介",
        "tags_section": "标签",
        "tag_style": "space",  # 空格分隔不带 #；无尾随空格问题
    },
}

# 互动钩短语（多字，避免单字「敢」误伤「勇敢 / 不敢」等无关上下文）
HOOK_PHRASES = ["报数", "点单", "跟读", "催更", "评论区", "弹幕", "敢不敢"]

# AI 指纹（与 SKILL.md `## 失败模式` 末条同源；drift 风险同 HOOK_PHRASES——
# 上游清单更新时这里要同步改）。「原来」只判**句首**形态：句中作叙事词的
# 「原来」不少见，全量禁会误伤；AI 的指纹是「原来 + 揭秘句式」的开头用法。
AI_FINGERPRINT_WORDS = ["yyds", "xswl", "绝绝子", "狠狠地", "藏了心机",
                        "宝藏", "把世界上好听的话"]
AI_REVEAL_RE = re.compile(r"(?:^|\n|(?<=[。！？!]))\s*原来")
AI_EXCLAIM_RUN_RE = re.compile(r"[!！]{2,}")            # ！！连刷（单个 ！ 合法）
AI_SIMILE_RE = re.compile(r"像[^，。！？\n“”\"']{1,12}一样的")   # 像 X 一样的 Y 模板句
EMOJI_PER_LINE_MAX = 3      # 一行 >3 个 emoji = 滥用（SKILL.md：一句三四个）


def _emoji_count(line: str) -> int:
    """emoji 粗计（0x1F000 起的 emoji 平面 + 2600–27BF 杂项符号/装饰符号，
    ✨ U+2728 在后者）。粗计够用：判的是「一行刷四五个」的滥用，不是精确字形学。"""
    return sum(1 for ch in line if 0x1F000 <= ord(ch) or 0x2600 <= ord(ch) <= 0x27BF)


# ============================================================
#  Markdown 段切分：把 ## H2 切成 (标题, 内容) 列表
# ============================================================

def split_h2_sections(text: str) -> list[tuple[str, list[str]]]:
    """Return list of (h2_title, body_lines). H1 (`# Title`) 不算段。"""
    sections: list[tuple[str, list[str]]] = []
    cur_title: str | None = None
    cur_body: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur_title is not None:
                sections.append((cur_title, cur_body))
            cur_title = m.group(1).strip()
            cur_body = []
        elif cur_title is not None:
            cur_body.append(line)
    if cur_title is not None:
        sections.append((cur_title, cur_body))
    return sections


def section_text(title: str, sections: list[tuple[str, list[str]]]) -> str | None:
    """Return the body text of a given H2 section, or None if not present."""
    for t, body in sections:
        if t.strip() == title:
            return "\n".join(body).strip()
    return None


def section_body_lines(title: str, sections: list[tuple[str, list[str]]]) -> list[str]:
    """Return non-empty body lines of a given H2 section."""
    for t, body in sections:
        if t.strip() == title:
            return [ln for ln in body if ln.strip()]
    return []


# ============================================================
#  Checks — 每条与 SKILL.md `## 验收判据` 表一一对应
# ============================================================

def check_required_sections(path: Path, platform: str) -> list[str]:
    """1. 必需 H2 段落齐全。"""
    text = path.read_text(encoding="utf-8")
    sections = split_h2_sections(text)
    present = {t.strip() for t, _ in sections}
    spec = PLATFORM[platform]
    return [f"缺必需 H2 段落「{h2}」"
            for h2 in spec["required_h2"] if h2 not in present]


def check_title_len(path: Path, platform: str) -> list[str]:
    """2. 标题字数：实测 `len()`（emoji / ASCII 都按 1 字，与用户所见一致）。

    取标题源的规则（与 `multilingual-video-publishing/scripts/check_plan.py`
    读 title 的方式同源——publishing 端从清单的 `title` 字段核，本 skill 从
    markdown 同位字段核，确保两边不漂移）：

    - 小红书：`## 标题（20 字内）` 段内容
    - B站：`## 标题` 段内容
    - 抖音：**没有 `## 标题` 段**——`## 文案` 段的第一行就是标题
      （抖音投稿表单的「标题」与「正文」共用一个输入框，文案开头即标题）
    """
    spec = PLATFORM[platform]
    text = path.read_text(encoding="utf-8")
    sections = split_h2_sections(text)
    if platform == "douyin":
        lines = section_body_lines("文案", sections)
        if not lines:
            return ["「文案」段为空——抖音的标题与正文都在这一段"]
        title = lines[0]
    else:
        title_h2 = "标题（20 字内）" if platform == "xiaohongshu" else "标题"
        lines = section_body_lines(title_h2, sections)
        if not lines:
            return [f"标题 H2「{title_h2}」内容为空"]
        title = " ".join(lines)
    n = len(title)
    if n > spec["title_max"]:
        return [f"标题 {n} 字 > 上限 {spec['title_max']}：{title!r}"]
    return []


def check_trailing_space(path: Path, platform: str) -> list[str]:
    """3. 话题末尾尾随空格（仅抖音 + 小红书；B站无 #tag 区）。"""
    spec = PLATFORM[platform]
    if spec["tag_style"] != "hash":
        return []
    text = path.read_text(encoding="utf-8")
    sections = split_h2_sections(text)
    lines = section_body_lines(spec["tags_section"], sections)
    if not lines:
        # 段落缺失由 check_required_sections 报；这里不重复
        return []
    last = lines[-1]
    if not last.endswith(" "):
        return [f"「{spec['tags_section']}」末尾缺尾随空格"
                f"（publish-playbook 坑 ①：Slate 联想面板会吃掉末段话题）"
                f"，当前末行：{last!r}"]
    return []


def check_hook_phrase(path: Path, platform: str) -> list[str]:
    """4. 互动钩短语至少出现一个。"""
    spec = PLATFORM[platform]
    text = path.read_text(encoding="utf-8")
    sections = split_h2_sections(text)
    body = section_text(spec["body_section"], sections) or ""
    if not any(phrase in body for phrase in HOOK_PHRASES):
        return [f"「{spec['body_section']}」缺互动钩短语"
                f"（{HOOK_PHRASES} 至少一个）——评论区会冷场"]
    return []


def check_pinned_quote(path: Path, platform: str) -> list[str]:
    """5. 发布贴士含「置顶」+ 引号示例。"""
    text = path.read_text(encoding="utf-8")
    sections = split_h2_sections(text)
    tip = section_text("发布贴士", sections) or ""
    if "置顶" not in tip:
        return ["「发布贴士」缺「置顶」——发布后自己置顶是拉新的硬动作"]
    # 引号示例：英文双引号 / 中文「」/ 中文“” 都算
    has_quote = bool(re.search(r'["“”「」][^"“”「」]+["“”「」]', tip))
    if not has_quote:
        return ["「发布贴士」含「置顶」但缺引号示例（\"…\" 或 「…」）"
                "——话术必须落到具体字面，临时编的钩子弱"]
    return []


def _no_hard_wrap_violations(text: str) -> list[int]:
    """6. no-hard-wrap 检查。

    源码：~/.agents/skills/markdown-no-hard-wrap/SKILL.md §自查。
    内联副本而非导入——上游是 bash heredoc，没有 Python 模块。
    ⚠️ drift 风险：上游改判据时这里要同步改。
    """
    lines = text.splitlines()

    def fence_line(l: str) -> bool:
        return re.match(r"^\s*```", l) is not None

    def structural(l: str) -> bool:
        st = l.lstrip()
        if not st:
            return True
        if st.startswith(("#", "|", ">")) or st.startswith("```"):
            return True
        if re.match(r"^(\d+\.\s|[-*+]\s)", st):
            return True
        return False

    # 剥掉前置元数据（frontmatter）——与上游 heredoc 同
    if lines and lines[0].strip() == "---":
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
            lines = lines[:1] + lines[end + 1:]
        except StopIteration:
            pass

    bad: list[int] = []
    in_code = False
    for i, l in enumerate(lines):
        if fence_line(l):
            in_code = not in_code
            continue
        if in_code or structural(l):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if nxt.strip() and not fence_line(nxt) and not structural(nxt):
            bad.append(i + 1)
    return bad


def check_no_hard_wrap(path: Path, platform: str) -> list[str]:
    """6. no-hard-wrap 零违规。"""
    text = path.read_text(encoding="utf-8")
    bad = _no_hard_wrap_violations(text)
    if bad:
        return [f"段内硬换行违规于第 {bad} 行（合并为单行）"]
    return []


# ============================================================
#  读者面文字（AI 指纹与数字溯源的扫描面）
# ============================================================

def reader_text(path: Path, platform: str) -> str:
    """读者会看到的文字：标题 + 正文/文案/简介。

    **发布贴士不在扫描面**——它是写给操作者的内部说明，允许提规则本身
    （「别用绝绝子」「标题 20 字内」这类话在贴士里合法，进了正文才是 AI 味）。
    话题标签另查（尾随空格），不在这里重复。
    """
    spec = PLATFORM[platform]
    text = path.read_text(encoding="utf-8")
    sections = split_h2_sections(text)
    if platform == "douyin":
        # 抖音的标题与正文共用 `## 文案`（投稿表单只有一个输入框）
        return section_text("文案", sections) or ""
    title_h2 = "标题（20 字内）" if platform == "xiaohongshu" else "标题"
    parts = [section_text(title_h2, sections) or "",
             section_text(spec["body_section"], sections) or ""]
    return "\n".join(parts)


def check_ai_fingerprint(path: Path, platform: str) -> list[str]:
    """7. AI 指纹零命中（机检部分——枚举得出的签名）。

    语感（节奏 / 模板感 / 脊柱一致）判不了，仍归编辑走查；这里拦的是
    能写成规则的硬签名。清单与 SKILL.md 失败模式末条同源。
    """
    raw = reader_text(path, platform)
    low = raw.lower()
    problems = []
    for w in AI_FINGERPRINT_WORDS:
        if w in low:
            problems.append(f"AI 指纹「{w}」命中——读一遍全砍（见失败模式末条）")
    if AI_REVEAL_RE.search(raw):
        problems.append("句首「原来…」揭秘句式命中——AI 指纹，用自己的话说")
    if AI_EXCLAIM_RUN_RE.search(raw):
        problems.append("连续感叹号（！！+）命中——句末感叹号刷屏")
    if AI_SIMILE_RE.search(raw):
        problems.append("「像 X 一样的 Y」模板句命中")
    for ln in raw.splitlines():
        if _emoji_count(ln) > EMOJI_PER_LINE_MAX:
            problems.append(f"一行内 emoji {_emoji_count(ln)} 个 > {EMOJI_PER_LINE_MAX}"
                            "——emoji 滥用")
            break
    return problems


def _fact_numbers(facts) -> set:
    """事实表里全部可作数字出处的值（数值直接收；字符串能 parse 成数字的也收）。"""
    out = set()
    for v in (facts or {}).values():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.add(float(v))
            continue
        try:
            out.add(float(str(v).strip()))
        except ValueError:
            pass
    return out


def check_fact_provenance(path: Path, platform: str, facts) -> list[str]:
    """8. 数字可溯源：读者面文字里出现的每个数字都能在事实表里找到出处。

    事实表 = `--facts facts.json`（键随便起，值是可核对的数：实测时长、
    语种/条目数、bgm 边车的 gain_basis 数字等——数字从哪来见 SKILL.md
    Workflow 第 4 步）。对账规则：声称值 n 匹配事实值 f
    当且仅当 n == f 或 round(f) == n 或 round(f, 1) == n（「52 秒」对实测
    52.4s 合法——四舍五入是写作，不是编造）。话题标签（#xxx）先剥掉——
    标签不是数字载体。
    """
    raw = reader_text(path, platform)
    raw = re.sub(r"#[^\s#]+", " ", raw)
    claimed = sorted(set(re.findall(r"\d+(?:\.\d+)?", raw)))
    if not claimed:
        return []
    nums = _fact_numbers(facts)
    untraced = [c for c in claimed
                if not any(float(c) == f or round(f) == float(c)
                           or round(f, 1) == float(c) for f in nums)]
    if untraced:
        return [f"数字 {untraced} 在 --facts 事实表里找不到出处——"
                "编造规格是本 skill 最严重的失败模式；要么删，"
                "要么把真实数字写进事实表（实测时长 / 条目数 / 边车数字）"]
    return []


# 注册表：机检名 → check 函数（与 SKILL.md `## 验收判据` 表的实现列对齐）
CHECKS: list[tuple[str, Callable[[Path, str], list[str]]]] = [
    ("必需 H2 段落齐全", check_required_sections),
    ("标题字数", check_title_len),
    ("话题末尾尾随空格", check_trailing_space),
    ("互动钩短语", check_hook_phrase),
    ("置顶话术", check_pinned_quote),
    ("no-hard-wrap 零违规", check_no_hard_wrap),
    ("AI 指纹零命中", check_ai_fingerprint),
]


# ============================================================
#  Top-level orchestrator
# ============================================================

def check_publish_dir(publish_dir: Path, facts=None) -> int:
    """检查 publish_dir 下的所有平台文件。返回非零退出码当存在 FAIL。

    缺失的 `xiaohongshu.md` / `douyin.md` / `bilibili.md` 是真实投诉
    （写者没交齐），不是静默 SKIP。
    facts：`--facts` 事实表（给了才跑数字溯源；没给 = SKIP，SKIP 不是 PASS）。
    """
    rc = 0
    any_file = False
    for platform, spec in PLATFORM.items():
        path = publish_dir / spec["filename"]
        print(f"\n=== {platform}（{spec['filename']}）===")
        if not path.exists():
            print(f"  ❌ 文件缺失——publishing 端取不到字段")
            rc = 1
            continue
        any_file = True
        file_ok = True
        for label, fn in CHECKS:
            fails = fn(path, platform)
            if fails:
                file_ok = False
                rc = 1
                for msg in fails:
                    print(f"  ❌ {label}：{msg}")
            else:
                print(f"  ✅ {label}")
        # 数字溯源：--facts 给了才跑；没给 = SKIP（纪律 12：SKIP 与 PASS 分列，
        # 把 SKIP 显示成 PASS 就是假绿灯）
        if facts is None:
            print("  ⏭️  数字溯源：SKIP（未给 --facts——没验，不是 PASS）")
        else:
            fails = check_fact_provenance(path, platform, facts)
            if fails:
                file_ok = False
                rc = 1
                for msg in fails:
                    print(f"  ❌ 数字溯源：{msg}")
            else:
                print("  ✅ 数字溯源（读者面数字全部对上事实表）")
        # 副信息：标题字数实测
        text = path.read_text(encoding="utf-8")
        sections = split_h2_sections(text)
        if platform == "douyin":
            tlines = section_body_lines("文案", sections)
            title = tlines[0] if tlines else ""
        else:
            title_h2 = "标题（20 字内）" if platform == "xiaohongshu" else "标题"
            tlines = section_body_lines(title_h2, sections)
            title = " ".join(tlines) if tlines else ""
        if title:
            print(f"  ℹ️  标题实测 {len(title)}/{spec['title_max']} 字")

    # 其它 *.md 文件：WARN（不 FAIL——可能用户加了其它平台，留个口子）
    extras = sorted(p for p in publish_dir.glob("*.md")
                    if p.name not in {s["filename"] for s in PLATFORM.values()})
    if extras:
        print(f"\n=== 其它文件（WARN：不在三平台硬约定里）===")
        for p in extras:
            print(f"  ⚠️  {p.name}")

    if not any_file:
        print(f"\n❌ publish_dir={publish_dir} 下没有任何已知平台文件")
        return 1
    print(f"\n{'✅ 全部通过' if rc == 0 else '❌ 存在 FAIL，见上'}")
    return rc


def main() -> int:
    import json
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0]
                                            if __doc__ else "")
    ap.add_argument("publish_dir", help="publish/*.md 所在目录")
    ap.add_argument("--facts", default=None,
                    help="事实表 JSON（键随意、值是可核对数字：ffprobe 时长 / 语种数 / "
                         "bgm 边车数字……）。给了才跑数字溯源；没给 = SKIP")
    ap.add_argument("--strict", action="store_true",
                    help="（预留）把 WARN 也升级为 FAIL")
    args = ap.parse_args()
    facts = None
    if args.facts:
        import pathlib as _pl
        facts = json.loads(_pl.Path(args.facts).read_text("utf-8"))
    return check_publish_dir(Path(args.publish_dir), facts)


if __name__ == "__main__":
    sys.exit(main())
