#!/usr/bin/env python3
"""dsh_surface.py —— 给引擎注册 dsh 这一格的**提示面**（surface prompt）。

为什么需要它：harness2 的 `core/prompts.py` 有一张按 **surface 名**索引的提示表
（`_SURFACE_TEXTS`），只认 `codex` 与 `opencode`。dsh 不是这两个之一——不注册就直接
抛 `ValueError: no prompt surface for 'dsh'`，整个 sweep 一个任务都跑不动。

**引擎是零补丁 vendored 的**（见 `theatre-ii/PROVENANCE.md`），所以这里**不改引擎文件**，
而是在运行时往那张表里注册一条 dsh 自己的条目。vendored 文件保持逐字节不变。

**这张表必须写 dsh 的真实可编辑面**，不能拿 opencode 那份顶替：opencode 的面有
`sub_agents/` 与 `plugin/`，dsh 这两格**根本不存在**——照着 opencode 写，proposer 会
提出根本装不上去的组件，整个提案被丢掉（白跑一轮 proposer 会话）。

用法（本层任何入口都应先调 `register()`）：

    from dsh_surface import register
    register()
"""

from __future__ import annotations

import sys
from pathlib import Path

from harness2.core import prompts as P

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

#: 插件自带、**被冻结**的技能：改写它们会被 `usine_adapter.validate_tree` 拒掉
#: （dsh 的技能注册表按 rank 合并，项目根会静默盖掉插件那份，于是分不清是 harness
#: 变好还是技能被换掉了）。proposer 必须知道这件事，否则第一枪就浪费在改技能上。
#:
#: **从盘上派生，不手抄**：这份清单原本是手写的十项，2026-10 加了第 11 个技能之后
#: 它既漏了新人、又仍然声称"十份"，而 `validate_tree` 是按目录判的（现在 11 个）——
#: 于是**提示在骗 proposer**：它被告知新技能可自由改写，一改就被拒。
#: 与 `usine_adapter` 用同一个源（`usine/skills/*/SKILL.md`）。
def frozen_skills() -> tuple[str, ...]:
    skills_dir = REPO / "usine" / "skills"
    return tuple(sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md")))


_EN = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
}


def _frozen_paragraph() -> str:
    names = frozen_skills()
    # 提示面正文是**英文**的，所以份数也用英文数词（写「十一」会读成乱码）。
    count_en = _EN.get(len(names), str(len(names)))
    listed = ",\n".join(f"`{n}`" for n in names)
    return (
        f"The {count_en} skills that ship with the production-line plugin are FROZEN. "
        f"Rewriting one of\n{listed}\n"
        "is REJECTED: the skill registry merges by rank, the project root\n"
        "silently overrides the plugin's copy, and then nobody can tell whether the harness got\n"
        "better or the skill was swapped. If one of those workflows needs a new procedure, add a\n"
        "NEW skill with a NEW name instead."
    )


#: **这是历史手抄版的原文，故意留着**：`surface_md` 里若出现这段文字，说明有人把派生
#: 逻辑改回了手抄（或 `_frozen_paragraph()` 的替换没生效），`smoke_dsh_bridge.py` 的
#: 「冻结技能清单从盘上派生（不手抄）」那条断言会因此 FAIL。它里面的「ten skills」和
#: 十个名字**不是笔误，是那版手抄的真值**——不要跟着盘上的 11 个去改它，改了它就不再
#: 是「旧值」这个判据锚点了。
_FROZEN_PLACEHOLDER = (
    "The ten skills that ship with the production-line plugin are FROZEN. Rewriting one of\n"
    "`bgm-bed`, `character-rig`, `karaoke-video`, `lesson-scene`, `multilingual-video-poetry`,\n"
    "`multilingual-video-publishing`, `one-page-poster`, `publish-copy`, `storyteller-video`,\n"
    "`video-generation` is REJECTED: the skill registry merges by rank, the project root\n"
    "silently overrides the plugin's copy, and then nobody can tell whether the harness got\n"
    "better or the skill was swapped. If one of those workflows needs a new procedure, add a\n"
    "NEW skill with a NEW name instead."
)

_SURFACE_DSH = """\
# WHAT YOU CAN CHANGE

The harness is a tree of components. Each has a different runtime cost and a different reach:

| path | what it is | when it is in context |
|---|---|---|
| `systemprompt.md` | role and procedure | ALWAYS ON -- every token competes with the agent's own output budget |
| `guardrails.md` | standing rules | ALWAYS ON -- same cost |
| `LongTermMEMORY.md` | durable domain facts | ALWAYS ON -- same cost |
| `tool_descriptions/tool_guidance.md` | how to use the tools | ALWAYS ON -- same cost |
| `skills/<name>/SKILL.md` | a reusable workflow | loaded ON DEMAND via the `skill` tool |
| `scripts/<name>.py` | a deterministic helper | run ON DEMAND via the host shell |

At run time these are installed into a dsh workspace like this:

- The FOUR always-on files are CONCATENATED, in the order above, into ONE `AGENTS.md`
  that is injected into EVERY turn. In the tree you edit they stay four separate files;
  they become one file only at run time. The four together are capped at 24000 chars.
- `skills/<name>/SKILL.md` is installed to `.dsh/skills/<name>/SKILL.md`.
- `scripts/<name>.py` is installed to `harness_scripts/<name>.py`. A helper that travels
  with a skill (`skills/<skill>/scripts/<file>.py`) is installed as
  `harness_scripts/<skill>_<file>.py`.

WHAT DOES NOT EXIST ON THIS SURFACE: there are no sub-agents and no plugins. A
`sub_agents/<name>/AGENT.md` or a `plugin/<name>.ts` is not on the editable surface at
all -- it is dropped before your work is used, and the whole proposal is rejected. Do not
propose them, and do not write prose that assumes a plugin or a delegated agent exists.

The ten skills that ship with the production-line plugin are FROZEN. Rewriting one of
`bgm-bed`, `character-rig`, `karaoke-video`, `lesson-scene`, `multilingual-video-poetry`,
`multilingual-video-publishing`, `one-page-poster`, `publish-copy`, `storyteller-video`,
`video-generation` is REJECTED: the skill registry merges by rank, the project root
silently overrides the plugin's copy, and then nobody can tell whether the harness got
better or the skill was swapped. If one of those workflows needs a new procedure, add a
NEW skill with a NEW name instead.

The host gives the agent general tools next to the production-line tools -- a shell, a
file reader, a directory lister. So the agent CAN reach outside the tool surface, and
reaching outside it is exactly what the production-line discipline forbids: a path with
no acceptance criteria is not a path that produced a deliverable. When a trajectory shows
the agent reaching outside the tool surface, the fix is a cheap entry point (a skill with
a trigger line, or a script) and a short guardrail line -- not a warning nobody reads.

Change only what a trajectory shows needs changing -- but WHERE you change something, the
FORM matters as much as the content, and the cheap form is not the obvious one.

ALWAYS-ON PROSE IS THE EXPENSIVE OPTION. Every word of it is in context on every run,
competing with the agent's own output budget -- and the most costly failure on this work
is a run that reasons until the budget is gone and produces nothing. Adding prose makes
that MORE likely, not less. An on-demand component costs nothing until the moment it is
invoked.

So prefer, in this order:
  - a SKILL for anything with a recognisable trigger -- a procedure for a document type, a
    format, a recurring situation. This is the default form for new instruction.
  - a SCRIPT for a deterministic operation the runs hand-rolled and got wrong, or did slowly.
  - ALWAYS-ON TEXT last, and only for a short rule that genuinely applies to every run. If
    you add always-on text, cut something else to pay for it.

THREE RULES THAT DISCARD THE WHOLE PROPOSAL. Validation runs before any rollout, and a
harness that fails it is thrown away entire.

1. EVERY SKILL NEEDS A TRIGGER LINE -- the most violated rule here by a wide margin. If you
   create or keep `skills/<name>/SKILL.md`, its directory name must appear VERBATIM in
   `systemprompt.md` or `guardrails.md`, in the SAME edit:

       When <the situation this skill handles>, load the `<name>` skill.

   An unnamed skill is never opened anyway: the line is what makes it exist. The name must
   be kebab-case (lowercase letters, digits, dashes) and its frontmatter must carry
   `name: <the directory name>` and a `description:` -- a mismatch is dropped SILENTLY.

2. NO TEMPLATE BRACES IN ALWAYS-ON TEXT. Those files are rendered through Jinja with
   StrictUndefined before the run: a doubled `{{` placeholder, or a brace-percent statement
   tag, kills the job before any work starts. Use a single brace, or words.

3. EVERY SCRIPT YOU NAME MUST EXIST. A `scripts/<file>.py` invoked from a SKILL.md or from
   always-on text must ship in the same proposal, a skill's own helper at
   `skills/<skill-name>/scripts/<file>.py`; one dropped loose in the skill directory is OFF
   THE EDITABLE SURFACE and silently discarded. The one exception is a script the RUNTIME
   already provides in the workspace.

THE DELIVERABLE'S SHAPE BELONGS TO THE REQUEST, NOT TO YOU. A harness changes HOW the agent
works; it must never change WHAT SHAPE it delivers. Where the task names fields, sections or
an order, that shape is part of what was asked for. Guidance that makes the agent's
reasoning visible belongs in the harness text or the trajectory, never in the deliverable.

# HOW TO MAKE A CHANGE

The harness is in `context/harness/`, and it is YOURS TO EDIT. **You have no file tools
here**: you cannot open and rewrite a file in place. Report the files you change in the
output format given at the END of this message, and nothing else in your reply changes the
harness.

- Report ONLY the files you change. Files you do not report are inherited unchanged. Do
  not restate a file to keep it the same.
- A file you report is reported in FULL (its complete new content), not as a diff.
- To remove a component, report it with empty content.
- If the evidence does not argue for any change, report nothing and say KEEP_BASE in your
  notes. That is a real answer, not a failure: adaptation the evidence does not support
  costs context and buys nothing.

Then reply with ONE `<notes>` block and nothing else: for each change, the moment in a
trajectory that motivated it. The notes are read by a person, not applied by a machine."""


def _surface_text() -> P._SurfaceText:
    """构造 dsh 的提示面条目。

    `inv` / `dom` 复用引擎自己的维度模板（只换掉里面的 `__LOOP_LEVER__` 与
    `__TRIGGER_SENTENCE__` 两处占位）——维度方法（怎么决定改什么）是 harness2 的
    通用资产，不该在这里重写一遍；只有**面**（能改哪些组件、装到哪去）是 dsh 自己的。
    """
    inv = P._INV_TEMPLATE.replace(
        "__LOOP_LEVER__",
        "a `scripts/<name>.py` helper the agent runs as a gate BEFORE it reports the "
        "{deliverable} -- for example, a checker that confirms the {deliverable} exists "
        "instead of the agent asserting it",
    )
    dom = P._DOM_TEMPLATE.replace(
        "__TRIGGER_SENTENCE__",
        "A skill exists only once its name appears in the always-on text "
        "(`systemprompt.md` or `guardrails.md`): write that trigger line in the same edit.",
    )
    return P._SurfaceText(
        surface_md=_SURFACE_DSH.replace(_FROZEN_PLACEHOLDER, _frozen_paragraph()),
        inv=inv,
        dom=dom,
        tts_surface=_SURFACE_DSH.replace(_FROZEN_PLACEHOLDER, _frozen_paragraph()),
    )


def register() -> None:
    """把 dsh 的提示面注册进引擎的表。幂等。"""
    P._SURFACE_TEXTS.setdefault("dsh", _surface_text())


__all__ = ["register", "frozen_skills"]
