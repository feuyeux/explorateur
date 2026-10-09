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

用法：
    python3 check_publish_copy.py <publish_dir>
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


# 注册表：机检名 → check 函数（与 SKILL.md `## 验收判据` 表的实现列对齐）
CHECKS: list[tuple[str, Callable[[Path, str], list[str]]]] = [
    ("必需 H2 段落齐全", check_required_sections),
    ("标题字数", check_title_len),
    ("话题末尾尾随空格", check_trailing_space),
    ("互动钩短语", check_hook_phrase),
    ("置顶话术", check_pinned_quote),
    ("no-hard-wrap 零违规", check_no_hard_wrap),
]


# ============================================================
#  Top-level orchestrator
# ============================================================

def check_publish_dir(publish_dir: Path) -> int:
    """检查 publish_dir 下的所有平台文件。返回非零退出码当存在 FAIL。

    缺失的 `xiaohongshu.md` / `douyin.md` / `bilibili.md` 是真实投诉
    （写者没交齐），不是静默 SKIP。
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0]
                                            if __doc__ else "")
    ap.add_argument("publish_dir", help="publish/*.md 所在目录")
    ap.add_argument("--strict", action="store_true",
                    help="（预留）把 WARN 也升级为 FAIL")
    args = ap.parse_args()
    return check_publish_dir(Path(args.publish_dir))


if __name__ == "__main__":
    sys.exit(main())
