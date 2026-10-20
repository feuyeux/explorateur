#!/usr/bin/env python3
"""build_base_harness.py —— 从真实 dsh 插件派生 harness2 的基准 harness 树（c1..c8）。

为什么要有这个脚本：基准 harness 必须**与被改进对象同源**。手抄一份纪律文本，
下一次 `usine/packages/dsh-plugin/src/discipline.ts` 改动就会静默过期——而 harness2
的方法层（Propose–Probe–Compose）吃的就是这棵树，基准漂移会让所有对比数字失去意义。

所以基准树是**派生**的，不是抄的：
- c2 护栏 ← discipline.ts 的 DISCIPLINE_TEXT（逐字搬运，不改一个字）
- c4 工具指引 ← tools.ts 的 17 个工具面（名字 + description）
- c6 技能 ← usine/skills/<name>/SKILL.md（真实资产，逐字）
- c1 系统提示 / c3 记忆通道 ← 本文件内的固定文案（dsh 侧没有对应原生文件）

派生带**漂移闸**：工具表与 tools.ts 双向核对（少一个、多一个都报错），
纪律段与 discipline.ts 逐字核对。漂了就红，不许悄悄过期。

用法：
    python3 garage-ii/build_base_harness.py            # 重新生成 harness_base/
    python3 garage-ii/build_base_harness.py --check    # 只核对，不写盘（CI 用）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
USINE = REPO / "usine"
PLUGIN_SRC = USINE / "packages" / "dsh-plugin" / "src"
SKILLS_DIR = USINE / "skills"
BASE = HERE / "harness_base"

# c4 工具指引里除了「有哪些工具」，还要写「怎么选」。这张表是路由层：
# 十个技能各自负责哪一段产线，模型据此决定先看哪个技能、调用哪个工具。
# 路由写错比工具描述写错更致命——工具描述模型能自己读，路由要人教。
TOOL_ROUTING: dict[str, str] = {
    "usine_version": "只读自检：@feuille/core 版本号。无副作用，可随时调。",
    "usine_lesson": "开新课件 / 体检已有课件（①–⑦ 七层，每条未完成带下一条命令）。开工第一步。",
    "usine_scene": "场景课产线：创意交接 → 解析 → 校验 → 成稿 → TTS 音频。",
    "usine_persona": "人设契约体检：28 人班底逐人校验 + 班底不变量。",
    "usine_theme": "主题自动匹配：话题/语种 → 5 套垂域主题推荐。",
    "usine_poster": "海报产线：字体子集 → 组装 → 截图 → 字符子集门 → 四色验收 → 叠印对齐。",
    "usine_cover": "封面产线：整页 HTML → 平台规格整图截图 + 尺寸/底色验收。",
    "usine_karaoke": "词级卡拉OK成片：TTS 词级时间线 → 状态帧渲染 → 组装 → AV 同步验收。",
    "usine_poetry": "实拍母版成片诊断：人声段/空档段 LUFS 对比 + 文字压实拍量化。",
    "usine_storyteller": "评书成片：幕帧渲染（舞台 + 人物 + 卡拉OK字卡）→ 叠化转场 → 醒木混音。",
    "usine_bgm": "纯器乐 BGM 床生成（Lyria 免费层）+ 拍速反查/频段分布/床长实测判据。",
    "usine_copy": "发布词自检：三平台字数/钩子/置顶话术/no-hard-wrap/AI 指纹 + 数字溯源。零平台流量。",
    "usine_ledger": "产物缓存账本：谁过期了、因为什么。",
    "usine_framehash": "逐帧像素基线：save 采集分桶落盘，check 零漂移门禁。",
    "usine_quota": "查套餐额度（只读不烧额度）。**提交视频生成前必查**。",
    "usine_verify": "跑 usine 全量门禁（typecheck + vitest，约 1 分钟，别并发跑）。",
    "usine_video_generation": "视频生成母版。三条线（Hailuo-2.3 走套餐额度 / H3、H3-Max 扣积分）。**每次执行强制人工审批**。",
}

# tools.ts 里声明但默认不注册的工具（config.publish === true 才挂）。
# 它在工具面上「不可达」，所以工具指引必须写清：模型看不到它，也不许用 shell 绕。
UNREGISTERED_TOOLS = ("usine_publish",)

SYSTEM_PROMPT = """# feuille usine 产线智能体（dsh）

你运行的是 feuille usine 的视频产线工具面，工作区是当前目录。你有两条产线资产：

- **技能（skills）**：十份可复用的工序手册（`one-page-poster` / `karaoke-video` / `multilingual-video-poetry` / `bgm-bed` / `lesson-scene` / `character-rig` / `publish-copy` / `multilingual-video-publishing` / `storyteller-video` / `video-generation`）。用 `skill` 工具按需加载，**不要凭记忆复述工序**——手册里有精确的子命令、门禁判据和验收口径。
- **工具（tools）**：产线的机器可执行面，全部是进程内直调，退出码与 `feuille` CLI 同口径（0=过，1=不过/出错，2=用法错误）。

工作方式：

1. 先判断任务落在哪条产线上、哪一层（①–⑨），加载对应技能，再动手。
2. 需要新的产线判断、新的规格、新的验收口径时，读技能里的 `references/`，不要猜。
3. 工具返回的退出码就是判据。SKIP 不是 PASS。
4. 交付物写进当前工作区的项目目录，不写 Desktop/Downloads/临时目录。
5. 拿不准就查工具面或技能，不要用 shell 绕开工具——工具面外的路径没有验收口径。
"""

MEMORY_CHANNEL = """# 长期记忆

这里放**跨会话沉淀**的东西：已经确认过的产线事实、踩过的坑、某条产线的实际验收口径。

纪律：

1. 只写**被验证过**的内容。工具退出码非 0 的结论不许写成「已通过」。
2. 每条写清成立的前提（哪条产线、哪个版本、什么素材条件下成立）。没有前提的结论会过期。
3. 被后来的事实推翻的旧结论，要么收窄、要么加限定、要么删。**不许把被推翻的旧建议留在当事实**。
4. 这一节是**记忆通道**，不是工具手册。工序知识属于技能文件，产线事实属于这里。
5. 正式评分、评测器输出、榜单数字**不进这里**——评测隔离，官方评测是 host 产物，不是可学知识。
"""


def read_discipline() -> str:
    """把 discipline.ts 里的 DISCIPLINE_TEXT 逐字取出来。"""
    src = (PLUGIN_SRC / "discipline.ts").read_text(encoding="utf-8")
    m = re.search(r"export const DISCIPLINE_TEXT = `(.*?)`\s*$", src, re.S | re.M)
    if not m:
        raise SystemExit("build_base_harness: discipline.ts 里找不到 DISCIPLINE_TEXT（模板变了？）")
    return m.group(1).rstrip() + "\n"


def tool_names_in_source() -> set[str]:
    """tools.ts 里声明的全部工具名。"""
    src = (PLUGIN_SRC / "tools.ts").read_text(encoding="utf-8")
    return set(re.findall(r"name:\s*'(usine_[a-z_]+)'", src))


def render_tool_guidance() -> str:
    lines = [
        "# 工具指引（dsh 工具面）",
        "",
        "工具面是产线的机器可执行面。**退出码就是判据**：0=过，1=检查不过/出错，2=用法错误。",
        "SKIP 不是 PASS——把 SKIP 当 PASS 汇报就是造假。",
        "",
        "## 选工具（按产线层）",
        "",
    ]
    for name, routing in TOOL_ROUTING.items():
        lines.append(f"- `{name}` — {routing}")
    lines += [
        "",
        "## 工具面外的工具",
        "",
    ]
    for name in UNREGISTERED_TOOLS:
        lines.append(
            f"- `{name}` — **默认不注册**，工具面里根本没有它（config 显式开启才挂）。"
            "不要建议用户开启，不要用 shell 命令绕。"
        )
    lines += [
        "",
        "## 通用口径",
        "",
        "- 工具都是进程内直调 @feuille/* 包，没有 subprocess 桥。",
        "- `usine_verify` 跑全量门禁，约 1 分钟，**不要并发跑多个**。",
        "- 工具外的路径没有验收口径。绕开工具面做出来的东西，验收时一律不算过。",
    ]
    return "\n".join(lines) + "\n"


def skill_names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))


def build() -> dict[str, str]:
    """返回 rel -> content 的完整基准树。"""
    tree: dict[str, str] = {}
    tree["systemprompt.md"] = SYSTEM_PROMPT
    tree["guardrails.md"] = read_discipline()
    tree["LongTermMEMORY.md"] = MEMORY_CHANNEL
    tree["tool_descriptions/tool_guidance.md"] = render_tool_guidance()
    for name in skill_names():
        src = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        tree[f"skills/{name}/SKILL.md"] = src
    return tree


def check(tree: dict[str, str]) -> list[str]:
    """漂移闸：工具表与 tools.ts 双向核对。"""
    errs: list[str] = []
    declared = tool_names_in_source()
    covered = set(TOOL_ROUTING) | set(UNREGISTERED_TOOLS)
    missing = sorted(declared - covered)
    extra = sorted(covered - declared)
    if missing:
        errs.append(f"工具表漏了 tools.ts 里的工具：{missing}")
    if extra:
        errs.append(f"工具表写了 tools.ts 里没有的工具：{extra}")
    for name in skill_names():
        if f"skills/{name}/SKILL.md" not in tree:
            errs.append(f"基准树缺技能：{name}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="只核对，不写盘")
    args = ap.parse_args()

    tree = build()
    errs = check(tree)
    if errs:
        for e in errs:
            print(f"DRIFT: {e}", file=sys.stderr)
        return 1

    if args.check:
        for rel, content in sorted(tree.items()):
            p = BASE / rel
            if not p.is_file():
                print(f"MISSING: {rel}", file=sys.stderr)
                return 1
            if p.read_text(encoding="utf-8") != content:
                print(f"STALE: {rel}", file=sys.stderr)
                return 1
        print(f"base harness OK: {len(tree)} files, no drift")
        return 0

    for rel, content in tree.items():
        p = BASE / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print(f"base harness written: {len(tree)} files -> {BASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
