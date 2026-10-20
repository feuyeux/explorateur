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
MAX_ROLLOUT_CHARS = 20_000
MAX_TOTAL_ROLLOUT_CHARS = 120_000
MAX_DECISIONS_CHARS = 20_000
MAX_POOL_CHARS = 80_000
MAX_LIBRARY_CHARS = 40_000

#: 改完的 harness 树允许的最大字节数（护栏：一个「改」不是一次重写）。
MAX_OUTPUT_CHARS = 200_000

_FILE_BLOCK = re.compile(
    r"<<<FILE\s+([^\s>]+)\s*\n(.*?)\n>>>FILE", re.S
)


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

只回报你**真的改了**的文件；一个都不改就回 `KEEP_BASE`（这是**正当的答案**，
不是失败——证据不支持改动时如实说出来，比编一个改动有用得多）。
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
#: 为什么要有：基准树里那十份插件技能是**冻结**的（改写同名技能会被
#: `usine_adapter.validate_tree` 拒掉），却占了提示的一大半。整份塞进来既费上下文，
#: 又让「你可以改这些文件」这句话变成假的。按文件截断，模型看到的是骨架，
#: 而它真正要改的是那四个 always-on 文件。
MAX_HARNESS_FILE_CHARS = 3_000


def _harness_block(harness_dir: Path) -> str:
    parts: list[str] = []
    budget = MAX_HARNESS_CHARS
    for p in sorted(harness_dir.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(harness_dir).as_posix()
        body = _read(p, MAX_HARNESS_FILE_CHARS)
        if not body:
            continue
        frozen = rel.startswith("skills/") and "/SKILL.md" in rel
        tag = "（冻结：改写同名技能会被拒，要改就换新名字）" if frozen else ""
        block = f"--- FILE: context/harness/{rel}{tag} ---\n{body}\n"
        parts.append(block)
        budget -= len(block)
        if budget <= 0:
            parts.append("…(harness 文件已截断)\n")
            break
    return "".join(parts)


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
        body = _read(p, MAX_ROLLOUT_CHARS)
        parts.append(f"--- ROLLOUT: context/rollouts/{p.name} ---\n{body}\n")
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


def build_prompt(mission: str, context_dir: Path) -> str:
    """把「指针式 mission」改写成「内联式证据 + 输出契约」。"""
    context_dir = Path(context_dir)
    task = _read(context_dir / "task.md", MAX_TASK_CHARS)
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


def _says_keep_base(text: str) -> bool:
    """模型是不是明说「不用改」。

    只认**明确**的 KEEP_BASE 标记，不认「看起来没有改动」——后者是格式没跟上，
    该重试而不是当成正当答案。
    """
    return bool(re.search(r"\bKEEP_BASE\b", text or ""))


@dataclass
class MinimaxProposer:
    """直接调模型改 harness 树的 proposer 通道。

    `relay` 是 `dsh_provider.Relay`——本机中继，token 只在它内存里。
    """

    relay: object
    model: str
    timeout: int = 600
    max_tokens: int = 32_000
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
        prompt = build_prompt(mission, ctx)
        tries = max(1, int(max_attempts or self.attempts))
        last = ""
        last_text = ""
        t0 = time.time()
        for attempt in range(1, tries + 1):
            try:
                text, _out_tokens = self._post(prompt)
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
            edits, notes = parse_edits(text)
            if not edits:
                # **「没有文件块」有两种含义，不能一律当错误**：
                #
                # (a) 模型明说 KEEP_BASE —— 证据不支持任何改动，这是**正当的答案**；
                #     上游的 proposer 改的就是磁盘上的文件，不改 = 交回原树，
                #     引擎会把它记成 kept_base。
                # (b) 模型没按协议输出（先写一长段分析就断了）—— 这才是**格式错误**，
                #     该重试。
                #
                # 2026-10-20 实测：分不清这两者时，模型在**饱和任务**上会去**编造**
                # 一个失败（它凭空描述了一���轨迹里没发生过的动作），
                # 而「不改动」这个选项当时在协议里**根本不存在**。
                if _says_keep_base(text):
                    harness = ctx / "harness"
                    if not harness.is_dir():
                        last = "证据目录里没有 harness/，无法回报「不改动」"
                        continue
                    r = Reply(
                        label=label,
                        text=f"<notes>\n{notes or 'KEEP_BASE：证据不支持任何改动。'}\n</notes>",
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
                continue
            if sum(len(v) for v in edits.values()) > MAX_OUTPUT_CHARS:
                last = "回报的内容太大，疑似整树重写"
                continue
            harness = ctx / "harness"
            harness.mkdir(parents=True, exist_ok=True)
            for rel, body in edits.items():
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
