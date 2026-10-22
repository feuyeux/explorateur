#!/usr/bin/env python3
"""dsh_substrate.py —— 把 dsh（DeepSeek Harness）接成 harness2 的 solver substrate。

harness2 的接缝是三层：method（core/ 的 Propose–Probe–Compose）/ substrate（跑 rollout 的
智能体框架）/ benchmark（任务与判据）。本文件只做**第二层**：把 dsh 的可编辑面翻译成
harness2 的 c1..c8 树，再把 c1..c8 树装回 dsh 原生文件，最后把 dsh 的事件流渲染成
harness2 的共享轨迹文法。

**为什么 dsh 的可编辑面和 opencode 的不一样**（这是本文件存在的全部理由）：

| harness2 组件 | dsh 原生落点 | 状态 |
|---|---|---|
| c1 system prompt | `AGENTS.md`（agent-instructions 读同名候选） | 原生 |
| c2 guardrails | `AGENTS.md` 的一节 | 拼进去（dsh 的 guard 是代码插件，不是文本） |
| c3 memory | `AGENTS.md` 的一节 | 拼进去（dsh 默认没有工作区记忆文件） |
| c4 tool guidance | `AGENTS.md` 的一节 | 拼进去（dsh 的工具描述在插件代码里） |
| c5 subagents | dsh 的子智能体是**插件 provider**（in-process / ACP / Codex） | v1 不落文件 |
| c6 skills | `<projectRoot>/.dsh/skills/<name>/SKILL.md` | 原生 |
| c7 scripts | 工作区里的确定性帮手 | 原生（dsh 的 shell 工具能跑） |
| c8 plugins | cordis 插件，装在 profile 里 | v1 不落文件（工作区里的 .ts 装不进去） |

dsh 只有三个**原生**可编辑通道：`AGENTS.md`、`.dsh/skills/`、工作区脚本。其余四类组件
（护栏 / 记忆 / 工具指引 / 子智能体）要靠「拼装」或干脆不支持。拼装的代价是：
**一个文件坏了，全盘坏**——所以 `compose_agents_md` 是本文件里唯一有实质逻辑的地方，
其余全是薄壳。

c5/c8 为什么不做：dsh 的子智能体与插件都是 **profile 里的插件**，不是工作区里的文件。
一个装在 `<workspace>/plugin/foo.ts` 的文件既不会被 dsh 加载，也无法在本轮里被
proposer 改完就生效——那是个假接口。宁可标「不支持」，也不给一个看起来能用、实际不
生效的面。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from harness2.core import runmark as RM
from harness2.core import tree as HT
from harness2.core.tree import SurfaceSpec
from harness2.substrate.base import Install, Launcher, RunRequest

import dsh_surface

#: 引擎的提示表按 surface 名索引，只认 `codex` / `opencode`。dsh 要有自己的一条——
#: 写的是 dsh 真实的可编辑面（引擎文件零补丁，这条在运行时注册）。
dsh_surface.register()

#: 插件包与它的构建产物——**真正的执行器**装在插件包里（SDK 客户端从这儿解析）。
REPO = Path(__file__).resolve().parent.parent
PLUGIN_PKG = REPO / "usine" / "packages" / "dsh-plugin" / "package.json"
PLUGIN_DIST = REPO / "usine" / "packages" / "dsh-plugin" / "dist" / "index.mjs"

# ── dsh 的可编辑面 ────────────────────────────────────────────────────────────
#
# always_on 是四个「会被拼进 AGENTS.md」的文件。harness2 的 tree.always_on_text 把它们
# 首尾相接，所以 c1/c2/c3/c4 在**方法层**是四个独立可编辑组件，在**安装层**才合成一个
# dsh 原生文件。这样 proposer 看到的是「护栏」这一类语义，而不是「AGENTS.md 第 40 行」。
DSH_SURFACE = SurfaceSpec(
    name="dsh",
    always_on=(
        "systemprompt.md",
        "guardrails.md",
        "LongTermMEMORY.md",
        "tool_descriptions/tool_guidance.md",
    ),
    always_on_max=24_000,
    always_on_cap_reason=(
        "AGENTS.md 每一步都进上下文，这段预算抢的是智能体自己的输出余量"
    ),
    skill_dir="skills",
    skill_name_rule="must_match",
    trigger_hint=(
        "在 systemprompt.md 或 guardrails.md 里加一行点名 `{name}` 的触发句，"
        '例如「当要做 <这个技能负责的事> 时，加载 `{name}` 技能。」'
    ),
    autotrigger_file="systemprompt.md",
    # 自动触发句的兜底模板。**刻意不引用 `{desc}`**（2026-10-20 实测）：引擎的
    # `autotrigger()` 用 `^description:\s*(.+)$` 抓技能描述的第一行，而 YAML 折叠块
    # 写作 `description: >` 时，抓到的就是那个 `>` —— 于是兜底句变成
    # 「- 当>时，加载 `poster-print-delivery` 技能。」：一句读不通的话被写进
    # 每步都进上下文的 always-on 文本，且**没有任何判据会红**（v5 的 dom1/agg1 树
    # 逐字如此）。引擎层零补丁，所以在这里避开 `{desc}`：宁可写一句通用但通顺的，
    # 也不写一句「看起来带条件」的坏话。
    trigger_line="- 要做 `{name}` 管的那件事时，加载 `{name}` 技能。\n",
    subagent_requires_mode=True,
    plugin_dir=None,
    hooks_file=None,
    stubs=(
        (
            "skills/README.md",
            "<!-- c6：可复用工序手册，用 `skill` 工具按需加载。加一个就是 "
            "skills/<name>/SKILL.md，frontmatter 的 `name:` 要与目录名一致、"
            "且带 `description:`。 -->\n",
        ),
        (
            "scripts/README.md",
            "<!-- c7：确定性帮手，跑法是 `python3 harness_scripts/<name>.py`。"
            "加一个就是 scripts/<name>.py。 -->\n",
        ),
    ),
)

# 拼装 AGENTS.md 时的节标题。dsh 的 agent-instructions 读同名文件全文，不解析标题；
# 标题只是给人看的定位信息，也是 proposer 改写时的「改了哪一节」的锚。
_SECTION_TITLES = {
    "systemprompt.md": "系统提示",
    "guardrails.md": "红线护栏",
    "LongTermMEMORY.md": "长期记忆",
    "tool_descriptions/tool_guidance.md": "工具指引",
}

# dsh 的技能根（rank 100：project-dsh）。它比插件自带的 custom 根（rank 300）优先，
# 所以基准树里改写的同名技能会**盖掉**插件里那份，而不是与之并存。
#: 渲染整条轨迹时的**总长上限**。
#:
#: 引擎的证据契约明写「`context/rollouts/<label>.md` 是完整轨迹，不做
#: prompt 预算截断」（`theatre-ii/harness2/core/context.py`）。本层原来在
#: adapter 里硬砍 200k 字符，于是提案者只看到 24 条 ACTION（真实约 180 条），
#: 判据只看到 18 条（真实 108 条）——**判据的假信号**。
#: 观测正文的长度由 `obs_trunc` 单独管；整条轨迹的总长不设上限。
TRAJECTORY_MAX_CHARS = 50_000_000

DSH_SKILL_SUBDIR = Path(".dsh") / "skills"
DSH_SCRIPTS_SUBDIR = Path("harness_scripts")

#: 技能资产的**真实来源**：`usine/skills/` 正是插件注册给 dsh 的那个目录
#: （`usine/packages/dsh-plugin/src/index.ts`：
#: `customSkillDirs: [resolve(usineRoot(), 'skills')]`）。
#: 手册引用的 `assets/template/poster_src.html`、`references/script-coloring.md`
#: **只在这里**——工作区里没有它们，工序第一步就断了。
SKILL_ASSET_DIR = REPO / "usine" / "skills"

#: 装技能时跳过的：构建产物与系统垃圾，不是资产。
_SKILL_JUNK = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "SKILL.md")


def _install_skill_assets(dst_root: Path, names: list[str] | None = None) -> list[str]:
    """把真实资产源里的技能**资源**装到某个技能根（不含 SKILL.md）。

    装的是**整个目录**（含 `assets/`、`references/`），不是只有 SKILL.md。
    SKILL.md 由调用方从 harness 树覆盖——资产是源，手册是被改进对象。

    装两处，因为智能体两条路都可能走：`skill` 工具读 `.dsh/skills/`，
    而手册里「copy `assets/…`」这种相对路径通常是相对工作区里的技能目录。

    `names` 给定时**只装这些技能**——**树说了算**：演化删掉一个技能，工作区里
    就该没有它（否则「树与工作区不一致」，改动成了运行时空操作，
    却还会被当成「演化动了这一格」）。
    """
    installed: list[str] = []
    if not SKILL_ASSET_DIR.is_dir():
        return installed
    dst_root = Path(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    wanted = set(names) if names is not None else None
    for item in sorted(SKILL_ASSET_DIR.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            if not (item / "SKILL.md").is_file():
                continue  # 不是技能目录（例如 __pycache__）
            if wanted is not None and item.name not in wanted:
                continue
            shutil.copytree(item, dst_root / item.name, dirs_exist_ok=True, ignore=_SKILL_JUNK)
            installed.append(item.name)
        else:
            # 技能根上的共享资产（`theme-tokens.css` / `typography-base.css`）——
            # **不受 `names` 限制**：它们不是技能，是技能们引用的共享文件
            # （手册写着「`theme-tokens.css` (in `skills/`)」）。
            shutil.copy2(item, dst_root / item.name)
            installed.append(item.name)
    return installed


def compose_agents_md(staged: Path) -> str:
    """把 always_on 的四个文件拼成 dsh 原生的 AGENTS.md。

    拼装顺序 = SurfaceSpec.always_on 的顺序（c1 系统提示 → c2 护栏 → c3 记忆 →
    c4 工具指引）。空文件不占位（免得 AGENTS.md 里出现一节空标题），但**位置保留**：
    少了护栏这一节，模型就知道这里本来该有护栏，比护栏变成空白更危险。
    """
    parts: list[str] = []
    for rel in DSH_SURFACE.always_on:
        p = staged / rel
        body = p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""
        title = _SECTION_TITLES.get(rel, rel)
        if body:
            parts.append(f"<!-- dsh-harness:{rel} -->\n<!-- {title} -->\n{body}")
        else:
            parts.append(f"<!-- dsh-harness:{rel} -->\n<!-- {title}：空 -->")
    return "\n\n---\n\n".join(parts) + "\n"


def _frontmatter_desc(body: str) -> str:
    m = re.search(r"^description:\s*(.+)$", body[:600], re.M)
    return m.group(1).strip() if m else "(no description)"


def _component_index(staged: Path, pattern: str) -> str:
    """一行一条「- `name`: description」，供 AGENTS.md 之外的技能目录用。"""
    found = sorted(staged.glob(pattern), key=lambda p: p.parent.name)
    return "\n".join(
        f"- `{p.parent.name}`: {_frontmatter_desc(p.read_text(errors='replace'))}" for p in found
    )


def read_tree(surface, path) -> dict[str, str]:
    """`HT.read_tree` 的唯一入口——**读完之后把键统一成正斜杠**。

    为什么必须包一层：引擎的 `read_tree` 用 `str(p.relative_to(d))` 算相对路径，
    **Windows 上得到的是反斜杠**（`skills\\bgm-bed\\SKILL.md`）；而技能正则只认正斜杠
    （`skills/(...)/SKILL\\.md`）。于是 `HT.skill_names()` 在 Windows 上**恒返回空列表**，
    而 `is_allowed` 因为内部先走 `normalize_rel` 不会拦住——**树读得进来，名字一个都数不出**。
    影响面不是一条 smoke：提案提示里的技能清单、`validate_tree` 的同名技能核对、
    「每个技能都被 always-on 点名」全都拿不到名字。（`../docs/self-evolution.md` §3.2 的坑记的
    就是这个缺口，本节补的正是它写下的修法。）

    **修在本层，不改上游**：`theatre-ii/` 是零补丁的 vendored fork。
    """
    tree = HT.read_tree(surface, Path(path))
    return {HT.normalize_rel(k): v for k, v in tree.items()}


def dsh_skill_names(tree: Mapping[str, str]) -> list[str]:
    return HT.skill_names(DSH_SURFACE, dict(tree))


def dsh_bin() -> tuple[list[str], str]:
    """找出跑 dsh 的命令。返回 (argv 前缀, 来源说明)。

    优先级：`DSH_BIN`（显式）→ PATH 上的 `dsh` → 源码仓的 `pnpm dsh`。
    找不到就抛 RuntimeError，消息里带补救命令（harness2 的 preflight 契约：
    报错要说人话，且**不许**启动任何模型调用）。
    """
    explicit = os.environ.get("DSH_BIN", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise RuntimeError(
                f"DSH_BIN 指向 {p} 但该路径不存在：改 DSH_BIN，或装 dsh "
                f"（npx @deepseek-ai/dsh），或把源码仓路径给 DSH_SRC"
            )
        return [str(p)], f"DSH_BIN={p}"

    on_path = shutil.which("dsh")
    if on_path:
        return [on_path], "PATH 上的 dsh"

    src = os.environ.get("DSH_SRC", "").strip()
    if src and (Path(src) / "package.json").is_file():
        pnpm = shutil.which("pnpm")
        if not pnpm:
            raise RuntimeError(
                f"DSH_SRC={src} 需要 pnpm 来跑源码仓，但 pnpm 不在 PATH 上："
                f"装 pnpm，或改用 DSH_BIN / PATH 上的 dsh"
            )
        return [pnpm, "dsh"], f"源码仓 DSH_SRC={src}"

    raise RuntimeError(
        "找不到 dsh 可执行文件。补救三选一："
        "(1) 装发布版：npx @deepseek-ai/dsh；"
        "(2) 装到 PATH 上并让 `dsh` 可见；"
        "(3) 指源码仓：export DSH_SRC=/path/to/deepseek-harness"
    )


_JSON_MODE: bool | None = None


def dsh_json_mode() -> bool:
    """这个 dsh 的 headless profile 支不支持 `--json`（**旧** CLI 投影）。

    **已经不在关键路径上了**：真跑的轨迹来自 SDK 的**规范 SessionEvent 流**
    （`dsh_run.mjs` 落的 `events.jsonl`），那个在所有版本上都有，而且更全
    （`tool/call` / `tool/result` 带 `isError`）。`--json` 是 CLI 后来加的投影，
    PATH 上的旧版 dsh（实测 0.1.5-rc.3）没有。

    这个函数留着，是因为**降级判据**要区分「工具面真的没调」与「事件流没接上」：
    轨迹里没有 `[ACTION]` 行、而执行器又报告过事件流缺失，这两件事必须能被分开看。
    """
    global _JSON_MODE
    if _JSON_MODE is not None:
        return _JSON_MODE
    try:
        argv, _source = dsh_bin()
        proc = subprocess.run(  # noqa: S603
            [*argv, "--profile", "headless", "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        blob = (proc.stdout or "") + (proc.stderr or "")
        _JSON_MODE = "--json" in blob
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        _JSON_MODE = False
    return _JSON_MODE


class DshSubstrate:
    """dsh 作为一个 Substrate：可编辑面 + 装配 + 轨迹渲染 + preflight。

    启动体（launcher）由 benchmark adapter 提供——这是 harness2 的接缝约定：
    substrate 负责「装成什么样」，adapter 负责「怎么跑、跑在哪、读回哪儿」。
    """

    name = "dsh"

    def __init__(self, launcher: Launcher | None = None):
        self._launcher = launcher

    def surface(self) -> SurfaceSpec:
        return DSH_SURFACE

    def materialise(self, tree_dir: Path, spec, ctx: Mapping[str, str]) -> Install:
        """把 c1..c8 树装成 dsh 原生文件。

        装出来的东西就是一个**可运行的工作区**：
          - `AGENTS.md`               ← always_on 四节拼装
          - `.dsh/skills/<n>/SKILL.md` ← c6 技能（dsh 的 project-dsh 根）
          - `harness_scripts/<n>.py`  ← c7 脚本
        装完的目录同时也是 rollout 的工作目录——dsh 的 project root 判定是「最近的
        含 .git 的祖先，没有就用 cwd」，而 run root 约定在仓库外，所以这个目录
        天然就是 project root，`.dsh/skills` 一定被扫到。
        """
        tree_dir = Path(tree_dir)
        if not HT.is_tree(DSH_SURFACE, tree_dir):
            raise ValueError(
                f"{tree_dir} 不是一个 dsh harness 树（没有 always-on 文件）："
                f"至少要有 {DSH_SURFACE.always_on[0]}"
            )
        staged = Path(tempfile.mkdtemp(prefix="adapt-dsh-"))
        try:
            shutil.copytree(tree_dir, staged, dirs_exist_ok=True)

            # 技能 → dsh 的 project-dsh 根
            #
            # **技能自带的资源必须一起装。** 手册里写着「copy `assets/template/poster_src.html`」，
            # 这一行只有在 `assets/` 真的在盘上时才可执行；少了它，工序第一步就断了，
            # 智能体会（**正确地**）判定「工具面之外没有验收口径」而停手——那测的就不是
            # harness 的好坏，而是工作区完整与否。
            #
            # 2026-10-20 实测踩过：只装 SKILL.md 时，`routing-poster` 的基准臂在 50% 与 100%
            # 之间跳，跳的是「要不要放弃」；而 k=3 候选树里那条「资源缺失先如实报告」的规则
            # 正是被这个缺陷**逼出来的**——拿它去量演化，等于拿一个假信号当真信号。
            #
            # 资源从**真实资产源**（`usine/skills/`，也就是插件注册给 dsh 的那个目录）搬，
            # 不塞进 harness 树：树是**可编辑面**（引擎 `core/tree.py` 按正则定义，只认
            # `SKILL.md` 与 `scripts/`），把 347KB 资产放进去会撑爆每一次提案提示。
            # 技能自带的资源必须一起装。
            # （理由见 `_install_skill_assets` 的 docstring；「装哪些技能」由**树**决定。）
            tree_skills = [
                p.parent.name for p in sorted(tree_dir.glob(f"{DSH_SURFACE.skill_dir}/*/SKILL.md"))
            ]
            _install_skill_assets(staged / DSH_SKILL_SUBDIR, tree_skills)
            _install_skill_assets(staged / DSH_SURFACE.skill_dir, tree_skills)

            # 树里的 SKILL.md 覆盖同名那份——**树里那份可能已被演化改过**，
            # 资产是源，SKILL.md 是被改进对象。
            for rel in sorted(tree_dir.glob(f"{DSH_SURFACE.skill_dir}/*/SKILL.md")):
                name = rel.parent.name
                for root in (staged / DSH_SKILL_SUBDIR, staged / DSH_SURFACE.skill_dir):
                    dst = root / name / "SKILL.md"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(rel, dst)

            # 脚本 → 工作区帮手目录
            for rel in sorted(tree_dir.glob(f"{DSH_SURFACE.skill_dir}/*/scripts/*")):
                if not rel.is_file():
                    continue
                name = rel.parent.parent.name
                dst = staged / DSH_SCRIPTS_SUBDIR / f"{name}_{rel.name}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(rel, dst)
            for rel in sorted(tree_dir.glob("scripts/*.py")):
                dst = staged / DSH_SCRIPTS_SUBDIR / rel.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(rel, dst)

            # 拼装 AGENTS.md
            (staged / "AGENTS.md").write_text(compose_agents_md(staged), encoding="utf-8")

            # benchmark 自带的附带文件（`file:<rel>` 槽位）
            for key, body in ctx.items():
                if key.startswith("file:"):
                    rel = HT.normalize_rel(key[len("file:") :])
                    p = staged / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(body, encoding="utf-8")
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise

        return Install(
            staging_dir=staged,
            fingerprint=RM.fingerprint(tree_dir),
            extras={"substrate": "dsh", "project_root": str(staged)},
        )

    def execute(
        self, task_ref: str, install: Install, run_ids: list[str], timeout: int
    ) -> list[Path]:
        if self._launcher is None:
            raise RuntimeError(
                "DshSubstrate 构造时没给 launcher 体；benchmark adapter 必须提供"
                "（它拥有跑法、环境变量接线和回读位置）"
            )
        return self._launcher(
            RunRequest(task_ref=task_ref, run_ids=tuple(run_ids), timeout=int(timeout)), install
        )

    def read_trajectory(
        self, stream_path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400
    ) -> str:
        return render_events(
            Path(stream_path), obs_trunc=obs_trunc, max_chars=max_chars, args_trunc=args_trunc
        )

    def preflight(self) -> None:
        """开工前的健康检查。**不启动任何模型调用**——只验「能不能跑」。

        三件事：**node** 在 PATH 上（dsh 是 Node 宿主）；**SDK 客户端**能从插件包里解析
        出来（这才是真正的执行器）；**插件产物**已经构建（工具面挂不上去就是零工具面）。

        注意这里**不**查 PATH 上的 `dsh` CLI：真跑的路径是 SDK 客户端
        （`dsh_run.mjs`），CLI 只在手工调试时用得上。查它会得到一个**无关**的结论
        （PATH 上的 CLI 版本与 SDK 版本可以差好几个 release），而这条闸一旦误报，
        就会把一轮能跑的 sweep 拦下来。
        """
        node = shutil.which("node")
        if node is None:
            raise RuntimeError(
                "node 不在 PATH 上：dsh 是 Node 宿主，装 Node ≥24（或 ≥22.19）后重试"
            )
        sdk = self._sdk_entry()
        if sdk is None:
            raise RuntimeError(
                f"解析不到 dsh SDK 客户端（从 {PLUGIN_PKG} 找 @deepseek-ai/dsh-sdk-client）："
                "先在 usine 里 `pnpm install`"
            )
        dist = PLUGIN_DIST
        if not dist.is_file():
            raise RuntimeError(
                f"插件产物不在 {dist}：先跑 pnpm --filter @feuille/dsh-plugin build"
            )

    @staticmethod
    def _sdk_entry() -> Path | None:
        """从插件包里解析 SDK 客户端的入口。**不 import**，只解析路径——
        preflight 必须在任何模型调用之前跑完。"""
        pkg = REPO / "usine" / "packages" / "dsh-plugin" / "package.json"
        if not pkg.is_file():
            return None
        for base in (pkg.parent, pkg.parent / "node_modules"):
            cand = base / "node_modules" / "@deepseek-ai" / "dsh-sdk-client"
            if cand.is_dir():
                return cand
        return None


# ── 轨迹渲染：dsh JSON 事件流 → harness2 共享文法 ────────────────────────────
#
# dsh 的事件 schema（见 dsh `packages/bundle/headless/src/json-stream.ts`）：
#   {type:"session", sessionId, cwd}
#   {type:"status", phase, turn, step, reason?, usage?}
#   {type:"thinking", text} / {type:"text", text}
#   {type:"tool_call", callId, tool, input}
#   {type:"tool_result", callId, status:"completed"|"error", result}
#   {type:"final", text} / {type:"error", ...}
#
# harness2 的共享文法（见 substrate/opencode.py 的 render_events）：[ACTION] / [OBSERVATION]
# / [ERROR]，加 [ASSISTANT] / [THINKING] 两种文本。
_TRUNC_FMT = "…(+{n} chars — render truncation)"


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\x00", "")
    if n <= 0 or len(s) <= n:
        return s
    return s[:n] + _TRUNC_FMT.format(n=len(s) - n)


def render_events(path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400) -> str:
    """把 dsh 的 `--json` 事件流渲染成 harness2 的共享轨迹文法。

    解析是防御式的：dsh 的事件 schema 会随版本变，一条不认识的事件跳过而不是炸掉
    （整条轨迹没了，proposer 就失去了「行为对比」的另一半材料）。
    """
    args_cap = int(args_trunc)
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(failed to read trajectory: {e})"

    lines: list[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "text":
            txt = ev.get("text")
            if isinstance(txt, str) and txt.strip():
                lines.append(f"[ASSISTANT] {_clip(txt, obs_trunc)}")
        elif etype == "thinking":
            txt = ev.get("text")
            if isinstance(txt, str) and txt.strip():
                lines.append(f"[THINKING] {_clip(txt, obs_trunc)}")
        elif etype == "tool_call":
            name = ev.get("tool") or "tool"
            tin = ev.get("input")
            args = json.dumps(tin, default=str, ensure_ascii=False) if tin is not None else ""
            lines.append(f"[ACTION] {name}({_clip(args, args_cap)})")
        elif etype == "tool_result":
            status = ev.get("status")
            body = ev.get("result")
            if status == "error":
                lines.append(f"[OBSERVATION ERROR] {_clip(body, obs_trunc)}")
            else:
                lines.append(f"[OBSERVATION] {_clip(body, obs_trunc)}")
        elif etype == "error":
            msg = ev.get("message") or ev.get("error") or json.dumps(ev, ensure_ascii=False)
            lines.append(f"[ERROR] {_clip(msg, 300)}")
        elif etype == "final":
            txt = ev.get("text")
            if isinstance(txt, str) and txt.strip():
                lines.append(f"[FINAL] {_clip(txt, obs_trunc)}")

    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        dropped = len(rendered) - max_chars
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=dropped)
    return rendered


# ── 规范事件流（SDK 通知那条路）─────────────────────────────────────────────
#
# dsh 的 **规范** SessionEvent 流（SDK 的 `session.event` 通知与落盘的
# `session.v4.jsonl` 都是这个形状）。它比 `--json` 投影更底层、也更全：
# `--json` 是后加的投影，规范事件流在所有版本上都有。
#
#   {"type":"tool/call",       "data":{"name":"usine_verify","arguments":"{}","callId":…}}
#   {"type":"tool/result",     "data":{"message":{"content":[{"type":"text","text":…}],"isError":false}}}
#   {"type":"assistant/message","data":{"message":{"content":[{"type":"reasoning"|"text","text":…}]}}}
#   {"type":"turn/end",        "data":{"reason":{"kind":"error","error":{"message":…}}}}
#   {"type":"assistant/attempt","data":{"stream":[… {"chunk":{"reason":{"kind":"error","failure":{…}}}}]}}


def _tool_text(message: dict) -> str:
    """工具结果里的模型可见文本（拼起所有 text 块）。"""
    blocks = message.get("content") or []
    parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    return "".join(p for p in parts if isinstance(p, str))


def render_canonical_events(
    path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400
) -> str:
    """把规范 SessionEvent 流渲染成 harness2 的共享轨迹文法。"""
    args_cap = int(args_trunc)
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(failed to read trajectory: {e})"

    lines: list[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}

        if etype == "tool/call":
            name = data.get("name") or "tool"
            raw_args = data.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.dumps(json.loads(raw_args or "{}"), ensure_ascii=False)
                except json.JSONDecodeError:
                    args = raw_args
            else:
                args = json.dumps(raw_args, default=str, ensure_ascii=False) if raw_args else ""
            lines.append(f"[ACTION] {name}({_clip(args, args_cap)})")

        elif etype == "tool/result":
            msg = data.get("message") if isinstance(data.get("message"), dict) else {}
            body = _tool_text(msg)
            if msg.get("isError") is True:
                lines.append(f"[OBSERVATION ERROR] {_clip(body, obs_trunc)}")
            else:
                lines.append(f"[OBSERVATION] {_clip(body, obs_trunc)}")

        elif etype == "assistant/message":
            msg = data.get("message") if isinstance(data.get("message"), dict) else {}
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                txt = block.get("text")
                if not isinstance(txt, str) or not txt.strip():
                    continue
                if block.get("type") == "reasoning":
                    lines.append(f"[THINKING] {_clip(txt, obs_trunc)}")
                elif block.get("type") == "text":
                    lines.append(f"[ASSISTANT] {_clip(txt, obs_trunc)}")

        elif etype == "assistant/attempt":
            for chunk in data.get("stream") or []:
                reason = (chunk.get("chunk") or {}).get("reason") or {}
                failure = reason.get("failure")
                if isinstance(failure, dict) and failure.get("message"):
                    lines.append(f"[ERROR] {_clip(failure['message'], 300)}")

        elif etype == "turn/end":
            reason = data.get("reason") or {}
            err = reason.get("error")
            if isinstance(err, dict) and err.get("message"):
                lines.append(f"[ERROR] {_clip(err['message'], 300)}")

    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        dropped = len(rendered) - max_chars
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=dropped)
    return rendered
