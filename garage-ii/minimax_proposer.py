#!/usr/bin/env python3
"""minimax_proposer.py —— harness2 的 proposer 通道：直接调模型改 harness 树。

**为什么不用 harness2 自带的两个通道**（`opencode` / `claude_cli`）：

- `opencode` 通道要 `dependencies/opencode` 的**源码检出**（本仓没 vendor，vendor 就会
  变成「为了跑一个通道而 vendor 半个第三方仓」），且它跑的是 opencode **源码**而不是
  PATH 上的二进制；
- `claude_cli` 通道把 `ANTHROPIC_*` 全清掉、强制走 **Vertex AI**（`CLAUDE_CODE_USE_VERTEX=1`），
  而本机没有 gcloud ADC，claude CLI 也没登录。

所以本层自己写一个通道。它满足 harness2 对 proposer 的**全部要求**：

- 入参 `(mission, context_dir, label)`，出参带 `workspace`（改完的 harness 树）；
- 失败抛 `ProposerError`（**不**被吞成空回复）；
- 编辑契约：**omitted-is-inherited**——只回报自己改了哪些文件；
- 引擎从 `reply.text` 里用 `<notes>…</notes>` 抠决策说明（`recursion._run_stage`），
  所以这里的 `text` 必须带这个标记。

**证据怎么送进去**：harness2 的 mission 是一句「证据在磁盘上 `context/`，去读」的
**指针**（上游的 proposer 是能读文件的 agent）。本通道没有文件系统工具，所以把证据
**内联**进提示——`task.md`、当前 harness 树、每条 rollout 的完整轨迹、候选池（别的改法
+ 它们各自跑出来的行为）、经验库、既往决策。轨迹按上限截断（截断是**我们的**渲染标记，
不是求解者的失败——这句也写进提示，免得模型把截断当成行为）。

**引擎接口**（`core/schedule.py::_selector_for` 会读 `prop.spec` / `prop.audit_dir`）：
本类带齐 `spec` / `audit_dir` / `attempts` / `project` / `region`，并且把每次会话的
任务、回复、耗时落成审计文件（`audit_dir/<label>.mission.md` 等）——改 harness 的每一笔
都要能事后翻账。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from harness2.core.proposer import ProposerError
from harness2.core.spec import ChannelSpec

#: 证据内联的上限（字符）。太大模型会稀释注意力，太小会丢关键行为。
MAX_TASK_CHARS = 4_000
MAX_HARNESS_CHARS = 60_000
#: **单条 rollout 的内联上限**——2026-10-20 从 20,000 提到 60,000：
#: 20,000 时头部是技能手册全文（14.5KB），**真正的动作全被切在门外**，
#: 提案者明说「内联证据没有展示后续生成、验证或交付动作」→ KEEP_BASE。
MAX_ROLLOUT_CHARS = 110_000
MAX_TOTAL_ROLLOUT_CHARS = 300_000
MAX_DECISIONS_CHARS = 20_000
MAX_POOL_CHARS = 80_000
MAX_LIBRARY_CHARS = 40_000
#: 选择型任务内联候选时的上限（每个候选 / 全部候选）。
MAX_CANDIDATE_CHARS = 20_000
MAX_CANDIDATES_CHARS = 80_000

#: 改完的 harness 树允许的最大字节数（护栏：一个「改」不是一次重写）。
MAX_OUTPUT_CHARS = 200_000

_FILE_BLOCK = re.compile(
    r"<<<FILE\s+([^\s<>]+)>?\s*\n(.*?)\n>>>FILE", re.S
)

#: 行首的 `<<<FILE …` 表头（用来发现**没被 `_FILE_BLOCK` 认下**的块）。
#:
#: 为什么需要它（2026-10-20 实测）：协议写的是 `<<<FILE context/harness/<相对路径>`
#: （不带 `>`），而 `dom1` 的提案把第一个块写成 `<<<FILE context/harness/systemprompt.md>`
#: ——多了一个 `>`。旧正则 `[^\s>]+\s*\n` 因此**整块不匹配**，`parse_edits` 静静跳过它，
#: 那一轮仍然记成 `ok: true`：**一条本来要改的纪律就这么没了，审计里看不出来。**
#: 现在两件事都做了：表头容许尾随 `>`；漏掉的块要数出来报警。
_HEADER_LINE = re.compile(r"(?m)^<<<FILE\b[^\n]*$")


def unparsed_headers(text: str) -> list[str]:
    """返回**看着像文件块表头、却没被解析成块**的那些行。"""
    losers: list[str] = []
    keep: list[tuple[int, int]] = [(m.start(), m.end()) for m in _FILE_BLOCK.finditer(text)]
    for m in _HEADER_LINE.finditer(text):
        if any(a <= m.start() < b for a, b in keep):
            continue
        losers.append(m.group(0).strip())
    return losers


@dataclass
class Reply:
    """与 harness2 `core.proposer.Reply` 同形（鸭子类型，不改引擎）。"""

    label: str
    text: str
    ok: bool
    cost_usd: float = 0.0
    wall_s: float = 0.0
    attempts: int = 0
    cached: bool = False
    channel: str = ""
    error: str = ""
    audit: Path | None = None
    workspace: Path | None = None


PROTOCOL = """# 你的输出格式（严格遵守，否则这一轮作废）

你只能通过**回报文件全文**来改 harness。格式：

<<<FILE context/harness/<相对路径>
<这个文件的完整新内容>
>>>FILE

规则：
1. **只回报你真的改了的文件**。没改的文件不要回报——没回报的文件会被原样继承。
2. 每个文件回报**完整新内容**（不是 diff、不是片段）。
3. 路径必须相对 `context/harness/`，且只能是已经存在的文件的路径。
4. **如果证据不支持任何改动，就一个文件都不回报**，然后在 notes 里写 `KEEP_BASE`。
   **这是一个正当的答案，不是失败**——「证据不支持」是一个需要如实说出来的结论。
   证据里没有可追溯到某个时刻的失败时，**不要编一个**：你编出来的改动会被下一道
   校验挡掉，而更糟的是它会把一个本来没问题的 harness 改坏。
4b. **如果你想改的东西不在可编辑面**（被冻结的技能、插件自带的东西、证据里根本不
   存在的路径），**同样一个文件都不回报**，notes 里写 `KEEP_BASE OUT_OF_SCOPE`，并写清
   「你想改什么、为什么改不动」。**这同样是正当的答案**：交回原树就算完成，这一轮
   不作废。宁可如实说「改不动」，也不要硬改一个面外的东西——硬改会被校验挡掉，
   而更糟的是它会把一个本来没问题的 harness 改坏。
4c. **长文件请用紧凑形式回报，不要回写全文**（2026-10-20 实测：回写 5KB 的
   `tool_descriptions/tool_guidance.md` 时，回复**在 5830 字节处被网关截断**，
   文件块没闭合 → 解析失败 → 那一轮白跑）。紧凑形式有三种：

    <<<FILE context/harness/<相对路径>
    @@APPEND
    <追加到文件末尾的内容>
    >>>FILE

    <<<FILE context/harness/<相对路径>
    @@PREPEND
    <插到文件开头的内容>
    >>>FILE

    <<<FILE context/harness/<相对路径>
    @@REPLACE
    <原文里**逐字存在**的那一段>
    ---8<---
    <替换成的新内容>
    >>>FILE

   `@@REPLACE` 的原文段必须在文件里**逐字**存在（否则这一轮作废）；拿不准就用
   `@@APPEND`/`@@PREPEND`。**短文件（几百字以内）照旧回写全文也完全可以。**
5. 不要回报 `<notes>`、解释或寒暄。改完之后，在最后另起一段写：
   <<<NOTES
   一段话：这次改了什么、依据轨迹里的哪一刻
   >>>NOTES
6. 你的输出里**不许**出现分数、评分、判据、grader 之类的词——那些是评测的东西，
   不是 harness 的知识。
"""

#: 放在**最前面**的协议摘要。
#:
#: 为什么要有两份：证据是内联进来的（本通道没有文件工具），一次会话的提示能到
#: 8 万字符以上。协议只在末尾出现时，模型会先写一长段分析再忘了格式——
#: 2026-10-20 实测：inv1 维度的提案吐了 4130 字节纯分析，**一个文件块都没有**，
#: 那一轮等于白跑。把摘要提到最前面，是最便宜的一道保险。
PROTOCOL_HEAD = """# 你要做什么（一句话）

读下面的证据，找出**一条**轨迹里可追溯的失败，然后改 `context/harness/` 里的文件
把它修掉。改动用这个格式回报（完整文件内容，不是 diff）：

    <<<FILE context/harness/<相对路径>
    <这个文件的完整新内容>
    >>>FILE

**长文件不要回写全文**（回写途中回复可能被截断），改用紧凑形式：

    <<<FILE context/harness/<相对路径>
    @@APPEND
    <追加到文件末尾的内容>
    >>>FILE

    <<<FILE context/harness/<相对路径>
    @@REPLACE
    <原文里逐字存在的那一段>
    ---8<---
    <替换成的新内容>
    >>>FILE

只回报你**真的改了**的文件；一个都不改就回 `KEEP_BASE`（这是**正当的答案**，
不是失败——证据不支持改动时如实说出来，比编一个改动有用得多）。
想改的东西不在可编辑面时（冻结的技能、插件自带的东西），也是不回报文件，
回 `KEEP_BASE OUT_OF_SCOPE` 并写清为什么改不动——**这同样不作废**。
改完在最后写一段 `<<<NOTES … >>>NOTES` 说明依据。**不要写分析、解释或寒暄**——
你的输出就是文件本身。完整格式在最后。
"""


def _read(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…(+{len(text) - limit} chars — 证据内联截断，不是求解者的行为)\n"


def _job_of(mission: str) -> str:
    """把上游的「指针式 mission」拆出**任务指令**那一段。

    上游 mission 的结构是：`job` + `# YOUR EVIDENCE`（后面全是「去磁盘上读」的指针）。
    本通道没有文件工具，所以只取 job 那一段，证据由本模块内联。
    """
    head, sep, _tail = mission.partition("# YOUR EVIDENCE")
    return (head if sep else mission).strip()


#: 单个 harness 文件内联的上限。
#:
#: 为什么要有：基准树里那批插件技能是**冻结**的（改写同名技能会被
#: `usine_adapter.validate_tree` 拒掉），却占了提示的一大半。整份塞进来既费上下文，
#: 又让「你可以改这些文件」这句话变成假的。按文件截断，模型看到的是骨架，
#: 而它真正要改的是那四个 always-on 文件。
MAX_HARNESS_FILE_CHARS = 3_000
#: **always-on 文件**（模型真正要改的那几个）给足——它们本来就短。
MAX_ALWAYSON_FILE_CHARS = 12_000
#: 冻结技能的**工序行摘要**留多少字符。
#:
#: 为什么要有：冻结技能的前 3,000 字符里**没有工序**（海报格的手册 14,514
#: 字符，第 6 步「`google-chrome --headless --dump-dom` 喂 `fit-diag`」在
#: 第 7,430 字符处）。而「手册教了什么」正是判断「该不该改手册/该不该加新技能」
#: 的依据——看不见它，提案者就只能说「冻结技能已包含所需知识」。
MAX_FROZEN_DIGEST_CHARS = 2_600
#: 工序行 = 含**反引号命令**的行。
_COMMAND_LINE = re.compile(r"`[^`\n]{6,}`")


def _procedure_digest(text: str, budget: int) -> str:
    """冻结技能的**工序行摘要**：含命令的那些行（带行号）。

    它替不掉全文，但能让提案者看见「这份手册让智能体去跑哪些命令」——
    这正是判断「智能体是不是被手册教着绕开工具面」的依据。
    """
    picked: list[str] = []
    used = 0
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or not _COMMAND_LINE.search(s):
            continue
        piece = f"  {n}: {s[:220]}"
        if used + len(piece) > budget:
            break
        picked.append(piece)
        used += len(piece)
    if not picked:
        return ""
    return "（工序行：手册让智能体跑的命令/口径）\n" + "\n".join(picked)


def _harness_block(harness_dir: Path) -> str:
    parts: list[str] = []
    budget = MAX_HARNESS_CHARS
    for p in sorted(harness_dir.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(harness_dir).as_posix()
        raw = p.read_text(encoding="utf-8", errors="replace")
        frozen = rel.startswith("skills/") and "/SKILL.md" in rel
        if frozen:
            body = _read(p, MAX_HARNESS_FILE_CHARS)
            digest = _procedure_digest(raw, MAX_FROZEN_DIGEST_CHARS)
            if digest:
                body = body.rstrip() + "\n" + digest
            tag = "（冻结：改写同名技能会被拒，要改就换新名字）"
        else:
            body = _read(p, MAX_ALWAYSON_FILE_CHARS)
            tag = ""
        if not body:
            continue
        block = f"--- FILE: context/harness/{rel}{tag} ---\n{body}\n"
        parts.append(block)
        budget -= len(block)
        if budget <= 0:
            parts.append("…(harness 文件已截断)\n")
            break
    return "".join(parts)


#: **轨迹摘要里各类块保留多少字符**。
#:
#: 为什么要有摘要：轨迹的**头部是技能手册全文**（海报格 14,514 字符），而内联
#: 上限是 20,000——于是**真正的动作全被切在门外**。2026-10-20 实测：提案者
#: 明确说「内联证据没有展示后续生成、验证或交付动作」，于是判「没有可追溯的失败」
#: → KEEP_BASE。**它量的是证据被截断，不是 harness 有没有问题。**
#:
#: 实测一条海报轨迹的构成（200,034 字符）：手册/文件正文 57%、动作 24%（48KB）、
#: 观察 10%、推理 4%。**动作才是行为**，所以摘要保全部动作与推理，观察只留头。
#:
#: - 推理（`[ASSISTANT]`）：全留——它是「智能体为什么这么做」的证据；
#: - 动作（`[ACTION]`）：留前 N 字符——命令的前缀已经能看出「跑了什么」；
#: - 观察（`[OBSERVATION]`）：留前 N 字符；**长文档**（技能手册、文件全文）留更多，
#:   因为「手册教了什么」正是判断「该不该改手册」的依据；
#: - 最终回答（`[FINAL]`）：全留。
_DIGEST_KEEP = {"[ASSISTANT]": 4000, "[ACTION]": 420, "[OBSERVATION]": 120, "[FINAL]": 8000}
#: 长文档型观察保留更多（技能手册正文在它里面）。
_DIGEST_LONG_OBS = 2400
#: 摘要的头部原样保留多少字符（任务 + 最初几步 + 技能加载）。
_DIGEST_HEAD = 1500


#: 轨迹里的块标签（`[ACTION]` / `[OBSERVATION]` / …）。
_BLOCK_TAG = re.compile(r"^\[([A-Z][A-Z ]*)\]")


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """把轨迹拆成「块」：一行 `[TAG] …` 加它后面的续行。"""
    blocks: list[tuple[str, str]] = []
    tag = ""
    buf: list[str] = []
    for line in text.splitlines():
        m = _BLOCK_TAG.match(line)
        if m:
            if tag:
                blocks.append((tag, "\n".join(buf)))
            tag, buf = f"[{m.group(1)}]", [line]
        else:
            buf.append(line)
    if tag:
        blocks.append((tag, "\n".join(buf)))
    return blocks


def _digest_rollout(text: str, budget: int) -> str:
    """把一条轨迹压成**行为摘要**（见 `_DIGEST_KEEP` 的说明）。"""
    if len(text) <= budget:
        return text
    out: list[str] = [
        text[:_DIGEST_HEAD].rstrip(),
        "…(以下为行为摘要：全部推理与动作，观察只留头部；被省略的是观察的正文)…",
    ]
    used = len(out[0]) + len(out[1])
    for tag, block in _split_blocks(text):
        keep = _DIGEST_KEEP.get(tag)
        if keep is None:
            continue
        if tag == "[OBSERVATION]" and len(block) > _DIGEST_LONG_OBS:
            keep = _DIGEST_LONG_OBS
        piece = block[:keep]
        if len(block) > keep:
            piece += f" …(+{len(block) - keep} chars)"
        used += len(piece) + 1
        if used > budget:
            out.append(f"…(摘要到此，上限 {budget} 字符)")
            break
        out.append(piece)
    return "\n".join(out)


def _rollout_block(context_dir: Path) -> str:
    rollouts = context_dir / "rollouts"
    if not rollouts.is_dir():
        return "(没有 rollout 证据)"
    parts: list[str] = []
    total = 0
    for p in sorted(rollouts.glob("*.md")):
        if total >= MAX_TOTAL_ROLLOUT_CHARS:
            parts.append("…(更多 rollout 已省略)\n")
            break
        body = _digest_rollout(
            p.read_text(encoding="utf-8", errors="replace"), MAX_ROLLOUT_CHARS
        )
        parts.append(f"--- ROLLOUT: context/rollouts/{p.name}（行为摘要）---\n{body}\n")
        total += len(body)
    return "".join(parts)


def _pool_block(context_dir: Path) -> str:
    """候选池：别的改法 + 它们各自跑出来的行为。

    **AGG 阶段必须看到这些**——它的工作就是「比较几个候选再合成一个」，
    看不到候选的轨迹就只能凭空合成。
    """
    pool = context_dir / "pool"
    if not pool.is_dir():
        return ""
    parts: list[str] = []
    for d in sorted(p for p in pool.iterdir() if p.is_dir()):
        parts.append(f"--- CANDIDATE: {d.name} ---")
        diff = d / "harness.diff"
        if diff.is_file():
            parts.append(
                f"--- 相对基线的改动：context/pool/{d.name}/harness.diff ---\n"
                + _read(diff, 20_000)
            )
        roll = d / "rollout.md"
        if roll.is_file():
            parts.append(
                f"--- 这个候选跑出来的行为：context/pool/{d.name}/rollout.md ---\n"
                + _read(roll, MAX_ROLLOUT_CHARS)
            )
        produced = d / "produced.md"
        if produced.is_file():
            parts.append(
                f"--- 它交付了什么：context/pool/{d.name}/produced.md ---\n"
                + _read(produced, 8_000)
            )
    return "\n".join(parts)[:MAX_POOL_CHARS]


def _library_block(context_dir: Path) -> str:
    lib = context_dir / "library"
    if not lib.is_dir():
        return ""
    parts: list[str] = []
    idx = lib / "INDEX.md"
    if idx.is_file():
        parts.append(_read(idx, 8_000))
    for p in sorted(lib.rglob("*")):
        if not p.is_file() or p.name == "INDEX.md":
            continue
        rel = p.relative_to(lib).as_posix()
        parts.append(f"--- 经验库条目：context/library/{rel} ---\n{_read(p, 8_000)}")
    return "\n".join(parts)[:MAX_LIBRARY_CHARS]


def _decisions_block(context_dir: Path) -> str:
    d = context_dir / "decisions"
    if not d.is_dir():
        return ""
    parts = [f"--- DECISION: {p.name} ---\n{_read(p, 4000)}\n" for p in sorted(d.glob("*.md"))]
    return "".join(parts)[:MAX_DECISIONS_CHARS]


def _contract_of(mission: str, label: str) -> str:
    """这个 mission 要的**输出契约**是什么。

    引擎的这条通道被用在**两种性质完全不同**的任务上：

    - `edit` —— 改 harness（INV / DOM / AGG 三个提案阶段）。输出契约是
      `<<<FILE … >>>FILE` 文件块 + `<<<NOTES … >>>NOTES`。
    - `choice` —— 选一个输出（k≥2 的盲选会话）。输出契约是引擎自己的
      `<why>…</why>` + ` ```choice ` 块（`core/selection.py` 的 `_CHOICE`/`_WHY`）。
    - `experience` —— 蒸馏经验。输出契约是 `<experience>…</experience>` 块。

    **2026-10-20 实测踩过这个坑**：通道不分任务，一律把「改文件的协议」盖在最前面，
    于是选择任务的模型被告知「一个都不改就回 KEEP_BASE」→ 它回了 KEEP_BASE →
    通道去交回原树 → **选择上下文里根本没有 `harness/` 目录** → 报错 → 引擎回退。
    **结果是：k=3 的盲选从来没真正跑过**（`selection.json` 里 `fallback: true`）。
    """
    if label.startswith("select.") or "```choice" in mission:
        return "choice"
    if label.startswith("experience.") or "<experience>" in mission:
        return "experience"
    return "edit"


def _candidates_block(context_dir: Path) -> str:
    """把候选文件内联进来（选择任务说「打开每个候选再选」，本通道没有文件工具）。"""
    d = Path(context_dir) / "candidates"
    if not d.is_dir():
        return ""
    parts = []
    for p in sorted(d.glob("*.md")):
        parts.append(f"--- CANDIDATE {p.stem} ---\n{_read(p, MAX_CANDIDATE_CHARS)}\n")
    return "".join(parts)[:MAX_CANDIDATES_CHARS]


#: **always-on 文本里的纪律行**——这是 proposer 做「纪律自查」时唯一该看的清单。
#:
#: 为什么要在提示里单列：引擎的两个维度分工是「DOM 管领域知识 / INV 管怎么干活」，
#: 而 INV 的目录里明明有一条 **IGNORED INVARIANT**——「只有反复无视同一条纪律的证据
#: 才能推出防御性 helper」。2026-10-20 实测：海报格 5/5 条轨迹都手搓了浏览器，
#: 而 always-on 文本**明文写着**「不要用 shell 绕开工具」——纪律被反复跳过了，
#: 但两个维度都没把它当成失败：
#:
#: - DOM 维度被 mission 明令「Do not diagnose commands… A parallel candidate owns
#:   procedure」，不许碰工序；
#: - INV 维度读到的却是「always-on 已经写明不要绕工具，规则已存在 ⇒ 不用改」。
#:
#: 也就是说：**规则在、轨迹违反它、这件事没人把它摆到提案者面前**。把「always-on
#: 的纪律行」和「轨迹里实际执行的动作」摆在一起，让模型自己判「守没守」，是这一层
#: 能补的最诚实的一块——**清单是 harness 自己的文字，不是评分口径**。
_PROHIBITION_MARKERS = re.compile(
    r"(不要|禁止|别|不得|必须|务必|不许|never|must not|should not|don't)", re.I
)


def _discipline_lines(harness_dir: Path) -> list[str]:
    """从 always-on 文本里摘出**纪律行**（原文，一行一条）。

    只取 always-on 那些**始终加载**的文件（`systemprompt.md` / `guardrails.md` /
    `LongTermMEMORY.md` / `tool_descriptions/tool_guidance.md`）——它们才是每条轨迹
    都在的纪律来源。冻结技能里的句子**不算**：技能是按需加载的，而且改不动。
    """
    out: list[str] = []
    for rel in (
        "systemprompt.md",
        "guardrails.md",
        "LongTermMEMORY.md",
        "tool_descriptions/tool_guidance.md",
    ):
        p = Path(harness_dir) / rel
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if _PROHIBITION_MARKERS.search(s):
                out.append(f"{rel}: {s}")
    return out


def _discipline_block(harness_dir: Path) -> str:
    """纪律自查段——**只含 harness 自己的文字**。"""
    lines = _discipline_lines(harness_dir)
    if not lines:
        return ""
    body = "\n".join(f"- {l}" for l in lines)
    return (
        "# 先做一次纪律自查（然后再决定改不改）\n\n"
        "下面这些是 **always-on 文本里的纪律**（逐条原文；always-on 每条轨迹都在）。\n"
        "对每一条，去轨迹里**智能体实际执行的动作**（不是它说的话）里找：\n"
        "守住了吗？没守住的话，是哪一步没守住？\n\n"
        f"{body}\n\n"
        "**反复违反同一条纪律**（比如三条以上轨迹都违反了同一句）意味着：光有文字纪律\n"
        "不够。按 IGNORED INVARIANT 那一路走——用 `scripts/<name>.py` 做一道**闸**，\n"
        "让智能体在汇报交付物之前自己跑一遍；闸不能挡住正当的完成。\n\n"
        "**自查结论要写进 notes**：守住了就写守住了，没守住就写清楚是哪一条、哪一步。\n"
        "纪律已经写在 always-on 里、而且智能体确实照做了的，**不要**再抄一遍——那不是改动。"
    )


def build_prompt(mission: str, context_dir: Path, contract: str = "edit") -> str:
    """把「指针式 mission」改写成「内联式证据 + 输出契约」。

    `contract="edit"` 时用本通道自己的文件块协议；其余契约（选择 / 经验）**原样保留
    引擎的输出契约**——只把证据内联进去，**不覆盖它要什么格式**。
    """
    context_dir = Path(context_dir)
    task = _read(context_dir / "task.md", MAX_TASK_CHARS)

    if contract != "edit":
        # 选择/经验型任务：证据内联，但**输出契约一个字都不改**。
        parts = [
            mission,
            "",
            "# 证据（已内联在下面）",
            "",
            "你没有文件工具，所以证据不是「在磁盘上」——它就在这条消息里。",
            "",
            "## 任务（智能体收到的原话）",
            "",
            task,
        ]
        cands = _candidates_block(context_dir)
        if cands:
            parts += ["", "## 候选（每个候选的实际产出）", "", cands]
        rollouts = _rollout_block(context_dir)
        if rollouts:
            parts += ["", "## 轨迹（行为证据）", "", rollouts]
        library = _library_block(context_dir)
        if library:
            parts += ["", "## 经验库", "", library]
        return "\n".join(parts)

    parts = [
        PROTOCOL_HEAD,
        "",
        _job_of(mission),
        "",
        "# 证据（已内联在下面）",
        "",
        "你没有文件工具，所以证据不是「在磁盘上」——它就在这条消息里。",
        "",
        "## 任务（智能体收到的原话）",
        "",
        task,
        "",
        "## 当前 harness（你要改的就是这些文件）",
        "",
        _harness_block(context_dir / "harness"),
        "",
        "## 轨迹（行为证据：智能体实际做了什么）",
        "",
        _rollout_block(context_dir),
    ]
    discipline = _discipline_block(context_dir / "harness")
    if discipline:
        parts += ["", discipline]
    pool = _pool_block(context_dir)
    if pool:
        parts += ["", "## 候选（别的改法，以及它们各自跑出来的行为）", "", pool]
    library = _library_block(context_dir)
    if library:
        parts += ["", "## 经验库（这个产线层早先任务里已经采纳的改法）", "", library]
    decisions = _decisions_block(context_dir)
    if decisions:
        parts += ["", "## 既往决策", "", decisions]
    parts += ["", PROTOCOL]
    return "\n".join(parts)


def parse_edits(text: str) -> tuple[dict[str, str], str]:
    """解析 `<<<FILE … >>>FILE` 块与 `<<<NOTES … >>>NOTES`。"""
    edits: dict[str, str] = {}
    for m in _FILE_BLOCK.finditer(text):
        rel = m.group(1).strip()
        body = m.group(2)
        if rel.startswith("context/harness/"):
            rel = rel[len("context/harness/") :]
        rel = rel.strip().lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        edits[rel] = body
    notes = ""
    mn = re.search(r"<<<NOTES\s*\n(.*?)\n?>>>NOTES", text, re.S)
    if mn:
        notes = mn.group(1).strip()
    return edits, notes


#: 紧凑形式的指令头（`@@APPEND` / `@@PREPEND` / `@@REPLACE`）。
_DIRECTIVE_RE = re.compile(r"^@@(APPEND|PREPEND|REPLACE)\s*\n(.*)$", re.S)


def _resolve_body(rel: str, body: str, harness: Path) -> str:
    """把紧凑形式回报还原成**完整文件内容**；不是紧凑形式就原样返回。

    为什么要有紧凑形式（2026-10-20 实测）：协议要求「回报文件全文」，而
    `tool_descriptions/tool_guidance.md` 有 5KB——回写它时回复**在 5830 字节处被
    网关截断**，文件块没闭合 → 解析失败 → INV 维度的提案两次都白跑。
    紧凑形式让模型只回「要改的那几行」，长文件不再被截断。

    还原失败一律抛 `ValueError`（调用方当格式错误重试）：宁可这一轮作废，
    也不能把半截内容写进 harness。
    """
    m = _DIRECTIVE_RE.match(body)
    if not m:
        return body
    kind, rest = m.group(1), m.group(2)
    src = Path(harness) / rel
    if not src.is_file():
        raise ValueError(f"紧凑形式指向的文件不存在：{rel}")
    base = src.read_text(encoding="utf-8")
    if kind == "APPEND":
        add = rest.strip("\n")
        if not add.strip():
            raise ValueError(f"@@APPEND 后面没有内容：{rel}")
        return base.rstrip("\n") + "\n" + add + "\n"
    if kind == "PREPEND":
        add = rest.strip("\n")
        if not add.strip():
            raise ValueError(f"@@PREPEND 后面没有内容：{rel}")
        return add + "\n\n" + base
    # @@REPLACE：原文段必须逐字存在
    if "\n---8<---\n" not in rest:
        raise ValueError(f"@@REPLACE 缺少分隔行 `---8<---`：{rel}")
    old, new = rest.split("\n---8<---\n", 1)
    old = old.strip("\n")
    if not old:
        raise ValueError(f"@@REPLACE 的原文段是空的：{rel}")
    if old not in base:
        raise ValueError(f"@@REPLACE 的原文段在 {rel} 里不逐字存在")
    return base.replace(old, new.strip("\n"), 1)


def _says_keep_base(text: str) -> bool:
    """模型是不是明说「不用改」。

    只认**明确**的 KEEP_BASE 标记，不认「看起来没有改动」——后者是格式没跟上，
    该重试而不是当成正当答案。
    """
    return bool(re.search(r"\bKEEP_BASE\b", text or ""))


def _is_out_of_scope(text: str) -> bool:
    """模型是不是明说「想改，但改不动（不在可编辑面）」。

    这是与 KEEP_BASE 并列的**第二种**正当「不改动」答案：证据支持一个改动，
    但那个东西不在可编辑面里。两种答案都交回原树，区别只在 notes 里写清的是
    「没有证据」还是「改不动」——读数时要分得开这两者，因为前者说明这一格饱和，
    后者说明这一格碰到的障碍在 harness 之外。

    2026-10-20 实测：poster 维度的提案想改**冻结的** `one-page-poster` 技能，
    模型自己认出越界并拒绝动手——但当时协议里只有「证据不支持」这一种正当答案，
    它只能解释一句就交白卷，引擎判成格式错误 → 阶段回退 → judge 退出码 1。
    补上这个标记后，同样的情况会走 KEEP_BASE 路径：交回原树，如实记账。
    """
    return bool(re.search(r"\bOUT_OF_SCOPE\b", text or ""))


def _parse_sse_chat(text: str) -> tuple[str, int]:
    """把 OpenAI 风格的 SSE 流拼回 `(完整文本, 输出 token 数)`。

    判据是**流有没有正常收尾**：收到 `[DONE]`、或某一 chunk 带了非空
    `finish_reason`，都算收齐了。两样都没有 → 抛 `ProposerError("truncated")`，
    交给 `call()` 的重试，而不是把半截文本当成模型答案去解析。

    为什么要这条：2026-10-20 的 `inv1` 回复在 **5830 字节处静默截断**，
    半截 `<<<FILE` 块解析出来是「格式错误」，账面上像模型没按协议写，
    实际是链路断了。**静默截断是最贵的一种失败——它把链路的错记在模型头上。**
    """
    parts: list[str] = []
    tokens = 0
    done = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            done = True
            break
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("error"):
            raise ProposerError(f"upstream error: {str(payload['error'])[:300]}")
        usage = (payload or {}).get("usage") or {}
        if usage.get("completion_tokens"):
            tokens = int(usage["completion_tokens"])
        for choice in (payload or {}).get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                parts.append(piece)
            if choice.get("finish_reason"):
                done = True
    if not done:
        raise ProposerError(
            f"truncated stream: {len(''.join(parts))} chars, no finish_reason/[DONE]"
        )
    return "".join(parts), tokens


@dataclass
class MinimaxProposer:
    """直接调模型改 harness 树的 proposer 通道。

    `relay` 是 `dsh_provider.Relay`——本机中继，token 只在它内存里。
    """

    relay: object
    model: str
    timeout: int = 600
    max_tokens: int = 32_000
    # `anthropic-messages` | `openai-completions`。**必须与执行器同一个值**：
    # 两边走不同协议时，提案那一路会留在慢且会断的 `/messages` 上（见 `_post`）。
    api: str = "anthropic-messages"
    calls: list[Reply] = field(default_factory=list)

    # ── 引擎接口（`core/schedule.py::_selector_for` 读这几个属性）─────────────
    # `spec.kind` 只能用引擎枚举里的两个通道名（`ChannelSpec.__post_init__` 硬校验），
    # 而本通道既不是 opencode 也不是 claude_cli。这里借 `claude_cli` 这个**名字**过
    # 校验，但 `model` 写的是本通道真正用的模型——`spec` 在这里只当**记录**用，
    # 引擎走的是 `selector_prop=prop` 那条路（本类自己就是 proposer 与 selector）。
    spec: ChannelSpec = field(
        default_factory=lambda: ChannelSpec("claude_cli", "", timeout=600)
    )
    audit_dir: Path | None = None
    attempts: int = 2
    project: str = ""
    region: str = ""

    def __post_init__(self) -> None:
        self.spec = ChannelSpec("claude_cli", self.model, timeout=self.timeout)

    def _post(self, prompt: str) -> tuple[str, int]:
        """一次提案调用。`api` 决定走哪种线上协议（2026-10-20 实测后加的）。

        两条路打的是**同一个网关、同一个模型**，差的只是协议：
        - `anthropic-messages`（旧的唯一路径）：`/v1/messages`，每次都吐
          1.1 万–2.6 万字符的 reasoning 块；
        - `openai-completions`：`/v1/chat/completions`，默认不推理，墙钟约 1/3。

        两个真实的失败都发生在旧那一路（2026-10-20 19:5x 的 sweep）：
        `inv1` 的回复**在 5830 字节处截断**（传输层，重试两次都一样），
        `agg1` 的 183k 字符 prompt **HTTP 502**。所以提案通道必须跟着
        执行器换到同一个协议上——**执行器走 openai 而提案者走 anthropic，
        等于让最贵的那一步留在慢/断的那条路上**。
        """
        if self.api == "openai-completions":
            return self._post_openai(prompt)
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.relay.base_url()}/v1/messages",
            data=body,
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            payload = json.loads(r.read())
        parts = [
            b.get("text", "")
            for b in payload.get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        usage = payload.get("usage") or {}
        return "".join(parts), int(usage.get("output_tokens") or 0)

    def _post_openai(self, prompt: str) -> tuple[str, int]:
        """OpenAI 风格的一次调用（SSE 流，整段读完再拼）。

        为什么显式 `stream: true`：网关这一路**只在流式下才是常规表现**——
        执行器（dsh）走的就是流式，实测 36–47s；非流式那条没测过，不能假设
        它等价。所以这里跟着流式走，再把 SSE 增量拼回完整文本。

        截断检测：流里既没有 `finish_reason` 也没有 `[DONE]` 就当**传输层截断**
        抛出去，交给 `call()` 的重试。旧那一路的 `inv1` 正是**静默截断**——
        回了半截文件块，解析出来是「格式错误」，看起来像模型的错，其实是链路。
        """
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "stream": True,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.relay.base_url()}/v1/chat/completions",
            data=body,
            headers={
                "content-type": "application/json",
                "accept": "text/event-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            ctype = (r.headers.get("content-type") or "").lower()
            raw = r.read()
        text = raw.decode("utf-8", "replace")
        if "text/event-stream" in ctype or text.lstrip().startswith("data:"):
            return _parse_sse_chat(text)
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("error"):
            raise ProposerError(f"upstream error: {str(payload['error'])[:300]}")
        choices = (payload or {}).get("choices") or []
        if not choices:
            raise ProposerError(f"no choices in reply: {text[:300]}")
        msg = choices[0].get("message") or {}
        usage = payload.get("usage") or {}
        return str(msg.get("content") or ""), int(usage.get("completion_tokens") or 0)

    def _audit_paths(self, label: str) -> dict[str, Path] | None:
        if not self.audit_dir:
            return None
        d = Path(self.audit_dir)
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
        return {k: d / f"{safe}.{k}.md" for k in ("mission", "response")} | {
            "meta": d / f"{safe}.meta.json"
        }

    def _write_audit(
        self, label: str, mission: str, prompt: str, reply: Reply
    ) -> None:
        paths = self._audit_paths(label)
        if not paths:
            return
        paths["mission"].write_text(mission, encoding="utf-8")
        paths["response"].write_text(reply.text, encoding="utf-8")
        paths["meta"].write_text(
            json.dumps(
                {
                    "label": label,
                    "ok": reply.ok,
                    "channel": "minimax",
                    "model": self.model,
                    "attempts": reply.attempts,
                    "wall_s": reply.wall_s,
                    "prompt_chars": len(prompt),
                    "error": reply.error,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        reply.audit = paths["response"]

    def call(
        self,
        mission: str,
        context_dir: Path | str | None,
        label: str,
        *,
        system: str = "",
        timeout: int | None = None,
        max_attempts: int | None = None,
        harvest: str | None = None,
    ) -> Reply:
        """一次改 harness 的会话。失败抛 `ProposerError`（不吞成空回复）。"""
        import time

        if context_dir is None or not Path(context_dir).is_dir():
            raise ProposerError(f"[{label}] 没有证据目录：{context_dir}")
        ctx = Path(context_dir)
        contract = _contract_of(mission, label)
        prompt = build_prompt(mission, ctx, contract)
        tries = max(1, int(max_attempts or self.attempts))
        last = ""
        last_text = ""
        repair = ""
        t0 = time.time()
        for attempt in range(1, tries + 1):
            try:
                text, _out_tokens = self._post(prompt + repair)
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
                continue
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                continue
            if not text.strip():
                last = "empty reply"
                continue
            # 失败也要留原文：不然「没输出文件块」这种失败**没法诊断**
            # （0 字节的审计文件等于什么都没说）。
            last_text = text

            # **选择 / 经验型任务：原样把模型回复交回给引擎**，由引擎按它自己的
            # 契约解析（` ```choice ` 块 / `<experience>` 块）。**这里一个字都不加工**——
            # 加工就是 bug（2026-10-20 实测：把「改文件」的协议盖在选择任务上，
            # 模型回了 KEEP_BASE，通道去交回原树，而选择上下文里没有 harness/
            # → 报错 → 引擎回退 → k=3 的盲选从来没真跑过）。
            if contract != "edit":
                r = Reply(
                    label=label,
                    text=text,
                    ok=True,
                    wall_s=round(time.time() - t0, 1),
                    attempts=attempt,
                    channel="minimax",
                )
                self.calls.append(r)
                self._write_audit(label, mission, prompt, r)
                return r

            edits, notes = parse_edits(text)
            # **漏掉的块不许静静丢掉**（2026-10-20 实测）：`dom1` 把第一个表头写成
            # `<<<FILE …/systemprompt.md>`（多一个 `>`），整块没被认下，而这一轮
            # 仍然 `ok: true`、第二个块照常生效 —— 于是「要改的那条纪律」凭空消失，
            # 引擎随后用自动触发句把空档糊上（那一句还是坏的 `- 当>时`）。
            # 宁可多问一轮，也不接受「一部分改动没落地而且没人知道」。
            losers = unparsed_headers(text)
            if losers:
                last = (
                    f"有 {len(losers)} 个文件块没被解析（表头不合法）：{losers[:2]}"
                )
                repair = (
                    "\n\n# 上一轮有文件块的表头不合法，那一块被整块丢弃了。\n"
                    "表头必须**逐字**是 `<<<FILE context/harness/<相对路径>`，"
                    "行尾**不要多写 `>`**，下一行直接是内容；块尾是 `>>>FILE`。\n"
                )
                continue
            if not edits:
                # **「没有文件块」有三种含义，不能一律当错误**：
                #
                # (a) 模型明说 KEEP_BASE —— 证据不支持任何改动，这是**正当的答案**；
                #     上游的 proposer 改的就是磁盘上的文件，不改 = 交回原树，
                #     引擎会把它记成 kept_base。
                # (a') 模型明说 KEEP_BASE OUT_OF_SCOPE —— 想改，但那个东西不在可
                #      可编辑面（冻结的技能、插件自带的东西）。**同样交回原树**，
                #      同样算正当答案，只是 notes 要写得出来「改不动」这件事。
                # (b) 模型没按协议输出（先写一长段分析就断了）—— 这才是**格式错误**，
                #     该重试。
                #
                # 2026-10-20 实测：分不清 (a) 和 (b) 时，模型在**饱和任务**上会去
                # **编造**一个失败（它凭空描述了一条轨迹里没发生过的动作），
                # 而「不改动」这个选项当时在协议里**根本不存在**。
                if _says_keep_base(text):
                    harness = ctx / "harness"
                    if not harness.is_dir():
                        last = "证据目录里没有 harness/，无法回报「不改动」"
                        continue
                    oos = _is_out_of_scope(text)
                    r = Reply(
                        label=label,
                        text=(
                            "<notes>\n"
                            + (
                                "KEEP_BASE OUT_OF_SCOPE —— "
                                if oos
                                else "KEEP_BASE —— "
                            )
                            + (
                                notes.strip()
                                or (
                                    "想改的东西不在可编辑面。"
                                    if oos
                                    else "证据不支持任何改动。"
                                )
                            )
                            + "\n</notes>"
                        ),
                        ok=True,
                        wall_s=round(time.time() - t0, 1),
                        attempts=attempt,
                        channel="minimax",
                        workspace=harness,
                    )
                    self.calls.append(r)
                    self._write_audit(label, mission, prompt, r)
                    return r
                last = (
                    "回复里没有可解析的文件块（`<<<FILE … >>>FILE`）——"
                    "这一轮没有改动，等于白跑"
                )
                # **被截断的回复要区别对待**：有 `<<<FILE` 开头却没有闭合，说明
                # 这次输出**没写完**（2026-10-20 实测：回写 5KB 的
                # `tool_descriptions/tool_guidance.md` 时，回复在 5830 字节处被网关
                # 截断）。这时**重发同一份提示只会再截一次**——下一轮必须带上
                # 「用紧凑形式」的修复指令。
                if "<<<FILE" in text and ">>>FILE" not in text:
                    last = (
                        "回复被截断（有 `<<<FILE` 开头但没有闭合的 `>>>FILE`）——"
                        "输出没写完，这一轮等于白跑"
                    )
                    repair = (
                        "\n\n# 上一轮你的回复被截断了（没有写完 `>>>FILE`）。\n"
                        "**这一轮请用紧凑形式回报**（`@@APPEND` / `@@PREPEND` / "
                        "`@@REPLACE`），不要回写整份长文件；短文件照旧回写全文。\n"
                        "回复要短：只写要改的那几行 + 一段 `<<<NOTES … >>>NOTES`。\n"
                    )
                continue
            if sum(len(v) for v in edits.values()) > MAX_OUTPUT_CHARS:
                last = "回报的内容太大，疑似整树重写"
                continue
            harness = ctx / "harness"
            harness.mkdir(parents=True, exist_ok=True)
            # **紧凑形式要先还原成完整内容再落盘**（`@@APPEND` / `@@PREPEND` /
            # `@@REPLACE`）。还原失败（原文段不逐字存在、文件不存在）算格式错误，
            # 重试——不能把半截内容写进 harness。
            resolved: dict[str, str] = {}
            for rel, body in edits.items():
                try:
                    resolved[rel] = _resolve_body(rel, body, harness)
                except ValueError as exc:
                    last = f"紧凑形式还原失败：{exc}"
                    repair = (
                        "\n\n# 上一轮的紧凑形式还原失败（见上一轮回复）。\n"
                        "`@@REPLACE` 的原文段必须在文件里**逐字存在**；"
                        "拿不准就用 `@@APPEND` / `@@PREPEND`。\n"
                    )
                    resolved = {}
                    break
            if not resolved:
                continue
            for rel, body in resolved.items():
                p = harness / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
            # 引擎用 `<notes>…</notes>` 抠决策说明（`recursion._run_stage`），
            # 所以 text 里必须带这个标记。
            body = f"<notes>\n{notes}\n</notes>" if notes else text[:2000]
            r = Reply(
                label=label,
                text=body,
                ok=True,
                wall_s=round(time.time() - t0, 1),
                attempts=attempt,
                channel="minimax",
                workspace=harness,
            )
            self.calls.append(r)
            self._write_audit(label, mission, prompt, r)
            return r
        r = Reply(
            label=label,
            text=last_text[:4000],
            ok=False,
            wall_s=round(time.time() - t0, 1),
            attempts=tries,
            channel="minimax",
            error=last,
        )
        self.calls.append(r)
        self._write_audit(label, mission, prompt, r)
        raise ProposerError(f"[{label}] minimax/{self.model}: {last}", attempts=tries)


__all__ = ["MinimaxProposer", "Reply", "build_prompt", "parse_edits"]
