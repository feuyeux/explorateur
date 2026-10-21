#!/usr/bin/env python3
"""usine_adapter.py —— harness2 的 BenchmarkAdapter：usine 产线 × dsh 执行器。

harness2 的 benchmark 接缝是一组纯值/纯函数：`tasks` / `task_prompt` / `execute` /
`delivered` / `trajectory` / `deliverable_*` / `base_harness` / `validate_tree` / `score`。
本文件把这些接缝接到两件真东西上：

- **dsh**（执行器）——`DshSubstrate` 提供可编辑面与装配；本文件提供**启动体**：
  把装配好的工作区交给 `dsh --profile headless --json`，把事件流落盘。
- **usine 的 11 份技能与十八个工具面**（被改进对象；份数以 `usine/skills/*/SKILL.md` 为准，本句不手抄）——基准 harness 树由
  `build_base_harness.py` 从真实插件派生，不手抄。

关于**评测隔离**（RSIAgent §4.2 的那条纪律，harness2 侧同名同义）：本文件的
`score()` 只在**裁判阶段**被 `core.judge` 调用，方法层（proposer / composer）在
提案时拿不到任何分数——`core/context.py` 另有 `assert_tree_has_no_grader_verdicts`
盯着这一条。判据里写的 `usine_publish` 之类词是**判据的代码**，不是给智能体看的题面；
题面在 `bench_usine.py` 的 `Task.prompt` 里，那里面没有判据。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Mapping

from harness2.core import tree as HT
from harness2.core.spec import BenchmarkAdapter, RunView
from harness2.substrate.base import Install, RunRequest

from bench_usine import TASKS, Task, task_by_id
from browser_shim import BrowserShim
from dsh_provider import MINIMAX_CONTEXT_WINDOW, MINIMAX_MAX_TOKENS, MINIMAX_MODEL, Relay, make_patch
from dsh_substrate import (
    DSH_SURFACE,
    TRAJECTORY_MAX_CHARS,
    DshSubstrate,
    dsh_skill_names,
    read_tree,
    render_canonical_events,
)
import task_split

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BASE_HARNESS = HERE / "harness_base"

#: 插件里那批技能名——**这是一份冻结的名单，不是从盘上派生的**（2026-10-21 核实）。
#:
#: 它只列到 10 个，缺第 11 个 `vocab-infographic`；而 `validate_tree` 判「同名技能」时
#: 走的是 `_PLUGIN_SKILLS_DIR`（`usine/skills/` 的真实目录），**不读这个元组**，
#: 所以这个缺口目前不影响那道闸。这个常量除 `__all__` 导出外没有调用点。
#:
#: 之所以留着不改：它记录的是**插件下发那一批**的历史名单，与「盘上现在有几个」是两件事。
#: 但**别拿它当权威清单**——要枚举技能一律 `usine/skills/*/SKILL.md`（`frozen_skills()`
#: 与 `build_base_harness` 都是这么做的）。真要让它与盘上同源，得先确认所有调用点都
#: 接受"多出一个会自由改写的新技能"这个语义变化，而不是直接把第 11 个名字补进来。
PLUGIN_SKILL_NAMES = (
    "bgm-bed",
    "character-rig",
    "karaoke-video",
    "lesson-scene",
    "multilingual-video-poetry",
    "multilingual-video-publishing",
    "one-page-poster",
    "publish-copy",
    "storyteller-video",
    "video-generation",
)

#: 插件那批技能的真实位置——同名技能的内容比对就是拿它当基准。
_PLUGIN_SKILLS_DIR = REPO / "usine" / "skills"

#: `feuille` CLI 的真实位置。真实产线里它在 PATH 上（pnpm workspace），
#: 技能手册通篇写的是 `feuille poster fetch-fonts …`。
#: 基准工作区是仓库外的裸目录，PATH 上没有它——智能体于是 `which feuille` 落空，
#: 判定「工具面没有包」而停手。**那测的是工作区完整与否，不是 harness 的好坏。**
_FEUILLE_CLI = REPO / "usine" / "packages" / "cli" / "bin" / "feuille.js"


def _serial_tasks_needed() -> set[str]:
    """哪些任务**必须**串行跑 rollout。

    判据：这一格会调 `usine_verify`——它跑的是 **usine 仓里的全量门禁**
    （typecheck + vitest），同一个仓里并发跑两遍会互相踩
    （纪律原文：「`usine_verify` 跑全量门禁，约 1 分钟，**不要并发跑**」）。

    其它格子不需要串行：每个 rollout 有**自己独占**的工作区与 run 目录
    （`_launch_one` 里各拷一份），互不干扰。
    """
    from bench_usine import TASKS

    out: set[str] = set()
    for t in TASKS:
        if any(c.needle == "usine_verify" for c in t.checks):
            out.add(t.task_id)
    return out


def _feuille_shim_dir() -> Path:
    """造一个只含 `feuille` 的小 bin 目录（PATH 用的垫片）。

    垫片只是一行 `exec node <真实 cli> "$@"`——**不复制、不改写 CLI 本身**，
    它只是把真实产线里本来就有的那条命令接回工作区。
    """
    d = Path(tempfile.mkdtemp(prefix="usine-feuille-bin-"))
    shim = d / "feuille"
    shim.write_text(
        "#!/bin/sh\n"
        f'exec node "{_FEUILLE_CLI}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return d

#: dsh 的技能名必须是 kebab-case（dsh 的 skill-filesystem 明确要求，违反会被丢弃）。
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: **决定「过/不过」的那些函数**——判据戳要把它们的源码一起哈希。
#:
#: 只列「匹配器」，不列题面、不列整个模块：改注释不该作废一批读数。
_MATCHER_FUNCS = (
    "_cli_invokes",
    "_feuille_vars",
    "_browser_bypass_reason",
    "_is_browser_exec",
    "_is_readonly",
    "_real_tool_actions",
    "_shell_commands",
    "_split_shell_segments",
    "_strip_heredocs",
    "_program_word",
    "_is_skill_asset",
    "_skill_names_in_trajectory",
    "_trajectory_text",
)


def _matcher_impl_digest() -> str:
    """判据**匹配实现**的摘要——判据戳必须含它。

    没有它就会出现这种账面：判据的 name/kind/needle/weight 一动不动、匹配逻辑
    改了，戳照旧，于是两批用不同尺子量出来的分数被当成同一条分布。2026-10-20
    实测踩到（`_cli_invokes` 修好前/后的 v5 读数共用一个戳）。

    函数被改名/删掉也应当让戳变——所以取不到源码时喂函数名本身。
    """
    import inspect

    import bench_usine

    h = hashlib.sha1()
    for name in _MATCHER_FUNCS:
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        fn = getattr(bench_usine, name, None)
        if fn is None:
            h.update(b"<missing>")
        else:
            try:
                src = inspect.getsource(fn)
            except (OSError, TypeError):
                src = f"<no-source:{id(fn)}>"
            # 去掉行尾空白与注释行，免得「只改注释」也作废读数。
            body = "\n".join(
                line.rstrip()
                for line in src.splitlines()
                if not line.lstrip().startswith("#")
            )
            h.update(body.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:12]


class UsineAdapter:
    """usine 产线在 dsh 上的 benchmark 适配器。"""

    def __init__(
        self,
        runs_root: Path,
        *,
        timeout: int = 900,
        model: str = "",
        provider: str = "anthropic",
        relay=None,
        only_tasks: list[str] | None = None,
        context_window: int = 0,
        max_tokens: int = 0,
        api: str = "anthropic-messages",
    ):
        self.runs_root = Path(runs_root)
        self.timeout = int(timeout)
        self.model = model or MINIMAX_MODEL
        self.provider = provider
        #: 线上协议（`anthropic-messages` / `openai-completions`）。同一个网关、
        #: 同一个模型，两种协议下**实际耗时差一倍多**——见 `make_patch` 的实测表。
        self.api = api
        self.only_tasks = list(only_tasks) if only_tasks else None
        # rollout 串行锁。harness2 的 agg 模式会并行跑 2 个候选 rollout，而
        # `usine_verify` 跑的是 **usine 仓里的全量门禁**（typecheck + vitest）——
        # 同一个仓里并发跑两遍门禁会互相踩（纪律里明写「不要并发跑」）。
        # 这里把它从「文本纪律」变成「机制约束」：文本管知道，机制管做到。
        #
        # **只有会跑全量门禁的那一格需要串行**（2026-10-20 实测改的）：一律串行时，
        # 海报格那种 45 次工具调用的 rollout 要 13 分钟 × 12 次 ≈ 2.6 小时，
        # 而机器 CPU **76% 空闲**——瓶颈是模型 API 的往返，不是机器。
        # 锁到「该串行的那一格」上，剩下的格子并发跑，实际耗时从 2.6 小时降到 ~1 小时。
        self._rollout_lock = threading.Lock()
        self._serial_tasks = _serial_tasks_needed()
        #: 中继只该起一个：并行 rollout 会同时调 `_ensure_relay`。
        self._relay_lock = threading.Lock()
        # 中继：把 dsh 的 anthropic 请求转成 MiniMax 运行时认的那一路（摘 x-api-key、
        # 换 Authorization: Bearer）。**token 只活在中继的内存里**，不进磁盘。
        self._relay = relay if relay is not None else Relay()
        #: 写进 dsh patch 的窗口/输出上限（不同网关不一样；0 = 用 provider 默认）。
        self.context_window = int(context_window) or MINIMAX_CONTEXT_WINDOW
        self.max_tokens = int(max_tokens) or MINIMAX_MAX_TOKENS
        self._relay_started = False
        # 只有**自己起的中继**才归自己关。注入进来的中继是整个 sweep 共享的——
        # adapter 被回收时把它关掉，会把还在跑的中继杀掉（症状是别的阶段
        # 突然 `Connection refused`）。
        self._owns_relay = relay is None
        self._substrate = DshSubstrate(launcher=self._launch)
        #: `feuille` 垫片目录（PATH 用）。第一次跑 rollout 时才造。
        self._shim_dir: Path | None = None
        #: 浏览器垫片（mock keychain）。第一次跑 rollout 时才造——它让 headless
        #: 渲染不碰用户钥匙串（否则每轮 rollout 都在弹窗，2026-10-20 实测）。
        self._browser_shim: BrowserShim | None = None

    def _ensure_relay(self) -> None:
        """起中继（**线程安全**：并行 rollout 会同时调到这里）。

        没有锁的话，两个线程可能各起一个中继——端口不同，两个进程各拿一份
        凭据在内存里（不落盘，所以不泄密），但**收尾时只关一个**，
        另一个变孤儿，端口还占着。
        """
        with self._relay_lock:
            if not self._relay_started:
                self._relay.start()
                self._relay_started = True
                self._owns_relay = True

    def close(self) -> None:
        if self._relay_started and self._owns_relay:
            self._relay.close()
            self._relay_started = False
        if self._shim_dir is not None:
            shutil.rmtree(self._shim_dir, ignore_errors=True)
            self._shim_dir = None
        if self._browser_shim is not None:
            self._browser_shim.close()
            self._browser_shim = None

    def __enter__(self) -> "UsineAdapter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        # 中继是个**子进程**：不收它就会变成孤儿，还攥着继承来的 stdout/stderr 管道
        # 不放——调用方（比如把输出接进管道的 smoke）会等不到 EOF 而挂死。
        try:
            self.close()
        except Exception:
            pass

    # ── substrate ─────────────────────────────────────────────────────────────
    @property
    def substrate(self):
        return self._substrate

    @property
    def spec(self):
        from bench_usine import make_bench_spec

        return make_bench_spec(self.runs_root)

    # ── BenchmarkAdapter：任务面 ──────────────────────────────────────────────

    def tasks(self, split: str = "all") -> list[str]:
        """按 split 取任务 id。**`train` / `test` 是真切分，不是空转。**

        2026-10-21 之前这里写着「v1 没有 train/eval 切分：任务集小到一次性跑完，
        切了反而让样本更小」——那句话作为**当时的判断**是诚实的，但它有两个后果：

        1. `run_usine_h2.py` 传的 `split="all"` 让**提案者读到的失败轨迹与最终判分
           的任务是同一批**。这是过拟合的定义，而且读数上不可见：两臂都在同一批题上，
           你只会看到「分高」或「分低」，看不到「只在训练题上高」。
        2. `split` 参数**收下了却完全忽略**（`all`/`train`/`eval` 返回同一批），
           于是任何调用方以为切了，实际没切——静默的假承诺。

        现在任务集扩到 24 个（6 层 × 4），每层 50/50 分层切分后每边每层 2 个，
        切分才有统计意义（见 `task_split.py`）。切分**按领域分层、固定种子、只看
        `Task.domain`**——不看任务内容、不看判据、不看历史分数（看分数就是按已知
        结果挑题，那是有偏的）。

        引擎侧的校验是齐的（`harness2/benchmarks/tasks.py:62` 的 `select()`），
        这里直接复用它认得的格式，不另造一套。
        """
        all_ids = [t.task_id for t in TASKS]
        ids = task_split.select(TASKS, split)
        if self.only_tasks:
            wanted = set(self.only_tasks)
            unknown = wanted - set(all_ids)
            if unknown:
                raise ValueError(f"未知任务：{sorted(unknown)}")
            # **只按本 split 过滤**：`only_tasks` 指到别的 split 的任务时，
            # 结果是空——那是对的（这个 split 里确实没有它），不是错误。
            ids = [t for t in ids if t in wanted]
        return ids

    def split_coverage(self) -> dict:
        """切分的可读摘要 + 指纹，进报告用。"""
        data = task_split.make_split(TASKS)
        return {
            "seed": data["seed"],
            "train": data["train"],
            "test": data["test"],
            "unsplit_domains": data["unsplit_domains"],
            "digest": task_split.split_digest(TASKS, split_data=data),
        }

    def domain_of(self, task_id: str) -> str:
        return task_by_id(task_id).domain

    def task_prompt(self, task_id: str) -> str:
        return task_by_id(task_id).prompt

    def task_files(self, task_id: str) -> Path | None:
        return None

    # ── BenchmarkAdapter：执行面 ──────────────────────────────────────────────

    def base_harness(self) -> Path:
        if not (BASE_HARNESS / "systemprompt.md").is_file():
            raise FileNotFoundError(
                f"基准 harness 树不在 {BASE_HARNESS}：先跑 "
                f"`python3 garage-ii/build_base_harness.py` 生成"
            )
        return BASE_HARNESS

    def tree_signature(self, tree_dir: Path) -> str:
        """**可编辑面**的内容签名（只算面内的文件，不算 README 桩）。

        判断「演化到底动没动这一格」要比的是**面内内容**：
        `runmark.fingerprint` 哈希目录里的全部文件，而引擎写回的树比基准树多
        两个 README 桩，于是内容逐字相同的两棵树目录指纹也不同。
        """
        tree = read_tree(DSH_SURFACE, Path(tree_dir))
        h = hashlib.sha1()
        for rel in sorted(tree):
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(tree[rel].encode("utf-8", "replace"))
            h.update(b"\0")
        return h.hexdigest()[:16]

    def criteria_stamp(self, task_id: str) -> str:
        """这一格的**判据版本戳**。

        判据一改，同一格的分就不能和旧的混着看。臂的 `--append` 会拿它当闸：
        戳不一样就拒绝追加（那是「用新尺子量旧数据」，拼出来的不是同一条分布）。

        **必须连匹配实现一起哈希**，不能只哈希判据的声明。2026-10-20 实测：
        我改了 `_cli_invokes`（让 `$FEUILLE poster …` 与绝对路径也认），判据的
        name/kind/needle/weight 一个字没动，于是戳**不变**——旧读数（v4、以及
        v5 修好前那批）和新读数共用一个戳，`--append` 会把两把尺子量出来的
        分数拼成一条分布，而账面完全看不出来。

        **只哈希「决定过/不过」的那些函数**，不哈希整个模块：注释和文档改动
        不该让一批读数作废（那会逼着人为了「不丢数据」而不写注释）。
        """
        from bench_usine import task_by_id

        task = task_by_id(task_id)
        h = hashlib.sha1()
        for c in task.checks:
            h.update(c.name.encode("utf-8"))
            h.update(b"\0")
            h.update(c.kind.encode("utf-8"))
            h.update(b"\0")
            h.update((c.needle or "").encode("utf-8"))
            h.update(b"\0")
            h.update(str(c.weight).encode("utf-8"))
            h.update(b"\0")
        h.update(_matcher_impl_digest().encode("utf-8"))
        return h.hexdigest()[:12]

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        """跑一次 rollout，返回 run 目录。

        `harness_dir=None` 表示**未经修改的基准 harness**（harness2 的对照臂）。
        """
        src = Path(harness_dir) if harness_dir else self.base_harness()
        tree = read_tree(DSH_SURFACE, src)
        if not tree:
            raise ValueError(f"{src} 读出来是空树：基准 harness 树坏了")
        self._ensure_relay()
        install = self._substrate.materialise(src, self.spec, {})
        try:
            return self._launch_one(task_id, run_id, install, timeout=timeout)
        finally:
            shutil.rmtree(install.staging_dir, ignore_errors=True)

    def _launch(self, request: RunRequest, install: Install) -> list[Path]:
        out: list[Path] = []
        for run_id in request.run_ids:
            out.append(
                self._launch_one(
                    request.task_ref, run_id, install, timeout=request.timeout
                )
            )
        return out

    def _launch_one(
        self, task_id: str, run_id: str, install: Install, *, timeout: int | None = None
    ) -> Path:
        """跑一次 rollout：装配好的工作区 → dsh（SDK 客户端）→ 证据落盘。"""
        run_dir = self.runs_root / task_id / run_id
        # **整个 run 目录清掉，不只是 workspace**。
        #
        # 同一个 run_id 被重跑一次（进程被杀后重启、换了臂又跑回来）时，
        # 旧的那次留下的 `exit_code` / `final.txt` / `events.jsonl` 会**留在原地**，
        # 而工作区被重建成一份全新的、什么都没有的目录——于是磁盘上呈现出
        # 一副自相矛盾的样子：「最终回答说交付了 poster.png，工作区里没有
        # poster.png」。判据读的就是这两处，它会判成「没交付」。
        #
        # 2026-10-20 实测踩过：基准臂 r1/r2 就是这么被污染的（rollout 本身
        # 成功交付了，14:42:59 有个进程重建了它们的工作区），而读数里
        # 「没交付 PNG」被当成了智能体的行为——那是**我自己的进程管理**
        # 造出来的假缺陷。整目录清掉，这个状态就再也出现不了。
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        workspace = run_dir / "workspace"
        # 每个 rollout 一份独立工作区：装配目录是共用的，但工作区必须是每次 rollout 独占的，
        # 否则并行 rollout 会互相改对方的 AGENTS.md。
        shutil.copytree(install.staging_dir, workspace)

        task_file = run_dir / "task.txt"
        task_file.write_text(self.task_prompt(task_id), encoding="utf-8")

        try:
            with self._rollout_guard(task_id):
                stdout, stderr, code, argv = self._run_agent(
                    run_dir, workspace, task_file, timeout=timeout
                )
        except BaseException as exc:
            # **异常必须留下证据**：引擎的 `_roll_bases` 会把异常收成一句
            # 「no base rollout produced anything」，而 run 目录里若只有
            # workspace 与 task.txt，**没人知道出了什么事**（2026-10-20 实测踩过：
            # 改错一行代码，整批跑批 1 秒内「失败」，日志里什么都没有）。
            import traceback

            tb = traceback.format_exc()
            (run_dir / "error.txt").write_text(
                f"{type(exc).__name__}: {exc}\n\n{tb}", encoding="utf-8"
            )
            raise
        (run_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        (run_dir / "exit_code").write_text(str(code), encoding="utf-8")
        (run_dir / "argv.json").write_text(
            json.dumps(argv, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return run_dir

    def _rollout_guard(self, task_id: str):
        """这一格的 rollout 要不要排队。

        要排队的只有**会跑全量门禁**的那一格（`usine_verify`）；别的格子
        各自独占工作区，并发跑是安全的——而且**快得多**（瓶颈是模型 API 的
        往返，不是机器）。
        """
        if task_id in self._serial_tasks:
            return self._rollout_lock
        return contextlib.nullcontext()

    def _run_agent(
        self, run_dir: Path, workspace: Path, task_file: Path, *, timeout: int | None = None
    ) -> tuple[str, str, int, list[str]]:
        """跑一次智能体会话，返回 (stdout, stderr, 退出码, argv)。

        **这是整条链上唯一会花钱、唯一会调模型的一步。** 它被单独切成一个接缝，
        是为了让离线自检（`smoke_dsh_bridge.py`）能把它替换成假执行器——离线自检
        必须**不调任何模型**，否则「自检」本身就变成一次付费运行，而且没人敢跑。

        默认实现走 **SDK 客户端**（`dsh_run.mjs`），不是 `dsh --profile headless`：
        headless 剖面不带 feuille-usine 插件（智能体会对着零工具面发 shell），
        而且 `--json` 事件流是后加的（PATH 上的 dsh 0.1.5-rc.3 就没有）。
        SDK 的 `session.event` 通知在所有版本上都有，且带 `tool/call` 与 `tool/result`
        ——这正是 harness2 的行为对比要的材料。
        """
        patch_file = run_dir / "dsh-patch.yml"
        make_patch(
            patch_file,
            provider=self.provider,
            model=self.model,
            base_url=self._relay.base_url(),
            context_window=self.context_window,
            max_tokens=self.max_tokens,
            api=self.api,
        )

        argv = [
            "node",
            str(HERE / "dsh_run.mjs"),
            "--cwd",
            str(workspace),
            "--task-file",
            str(task_file),
            "--out",
            str(run_dir),
            "--patch",
            str(patch_file),
            "--provider",
            self.provider,
            "--model",
            self.model,
        ]
        env = dict(os.environ)
        env.setdefault("ANTHROPIC_API_KEY", "relay-placeholder")
        # openai-completions 那一路的占位 key（真凭据只在中继进程内存里）。
        env.setdefault("OPENAI_API_KEY", "relay-placeholder")
        # `feuille` 必须在 PATH 上：技能手册通篇写 `feuille poster …`，
        # `which feuille` 落空会让智能体判定「工具面没有包」而停手（2026-10-20 实测）。
        if self._shim_dir is None:
            self._shim_dir = _feuille_shim_dir()
        env["PATH"] = f"{self._shim_dir}{os.pathsep}{env.get('PATH', '')}"
        # 浏览器垫片：headless 渲染**不碰用户钥匙串**。
        # 基准智能体会手搓浏览器（冻结手册第 6 步就教 `google-chrome --headless
        # --dump-dom`），而那条命令行里没有 `--use-mock-keychain`——于是它给
        # Chrome 换新 profile 时，macOS 每轮 rollout 都弹一次钥匙串授权框
        # （2026-10-20 实测：弹窗 + 有时退出码 2）。垫片把每一次浏览器启动都包上
        # 那对旗标，并让「智能体找浏览器」先撞到垫片。
        # **它不改工具面的浏览器**（垫片指向 platform.browserPath() 解析出的同一个
        # 二进制），也不改被测行为——智能体照样手搓、照样绕开工具面，判据照样命中。
        if self._browser_shim is None:
            self._browser_shim = BrowserShim()
        env["PATH"] = f"{self._browser_shim.path_prefix()}{os.pathsep}{env['PATH']}"
        env.update(self._browser_shim.env_patch())
        # 证据：垫片解析出哪个二进制、加了哪些旗标（不含任何凭据）。
        (run_dir / "browser-shim.json").write_text(
            json.dumps(self._browser_shim.manifest(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        try:
            proc = subprocess.run(  # noqa: S603
                    argv,
                    cwd=str(workspace),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout or self.timeout,
                    check=False,
                )
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) + (
                f"\n[timeout after {timeout or self.timeout}s]"
            )
            code = 124
        except OSError as exc:
            stdout, stderr, code = "", f"failed to launch dsh: {exc}", 127
        return stdout, stderr, code, argv

    # ── BenchmarkAdapter：读回面 ──────────────────────────────────────────────

    def _events_path(self, run_dir: Path) -> Path:
        return Path(run_dir) / "events.jsonl"

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        """轨迹 = 规范 SessionEvent 流渲染成的共享文法。

        规范流来自 SDK 的 `session.event` 通知（`dsh_run.mjs` 落盘），
        **不是** `--json` 投影——后者是后加的，PATH 上的 dsh 0.1.5-rc.3 就没有。

        **整条轨迹不许截断**（`max_chars` 给到很大）：引擎的证据契约明写
        「`context/rollouts/<label>.md` 是**完整**轨迹，不做 prompt 预算截断」
        （`theatre-ii/harness2/core/context.py`）。本层原来在这里硬砍 200k 字符，
        后果是**两个都错**（2026-10-20 实测，新协议下更明显）：

        - 提案者看到的证据只剩 227KB / **24 条 ACTION**（真实约 180 条）——
          它在拿一副骨架做判断；
        - 判据看到的轨迹只剩 **18 条 ACTION**（真实 108 条），于是
          `tool_called:usine_poster` 被判成 **100% 失分**——**判据的假信号**
          （实际有 3 次 MCP 调用 + 22 次 CLI 调用）。

        观测正文的长度由 `obs_trunc` 单独管（每条观测的上限），那是引擎的
        `spec.obs_trunc` 语义；**整条轨迹的总长没有上限**。
        """
        p = self._events_path(run_dir)
        if not p.is_file():
            return "(no events file)"
        return render_canonical_events(p, obs_trunc=obs_trunc, max_chars=TRAJECTORY_MAX_CHARS)

    def final_text(self, run_dir: Path) -> str:
        """终局答案：`dsh_run.mjs` 落的 `final.txt`（SDK 的 finalResponse）。"""
        p = Path(run_dir) / "final.txt"
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        return ""

    def delivered(self, run_dir: Path) -> bool:
        """这一格没有产物文件，「交付」= 智能体给了终局答案。"""
        return bool(self.final_text(run_dir).strip())

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        text = self.final_text(run_dir)
        return {"final.txt": text} if text.strip() else {}

    def deliverable_text(self, run_dir: Path) -> str:
        return self.final_text(run_dir)

    # ── BenchmarkAdapter：判据面 ──────────────────────────────────────────────

    def validate_tree(self, tree: dict[str, str]) -> None:
        """dsh 侧的树不变量。抛 ValueError，消息会被原样喂回 proposer 当重试反馈。

        这里只放**dsh 特有**的规则。harness2 自己的通用规则（always-on 上限、技能必须有
        description、技能必须被点名、脚本必须存在……）由 `core/tree.py` 的 validate 负责，
        不在这里重复实现两套真相。

        关于同名技能：基准树里带着插件那批技能（基准 harness 必须与被改进对象同源），
        所以「同名」本身不违规——**同名且内容不同**才违规。dsh 的技能注册表按 rank 合并，
        项目根（rank 100）会盖掉插件的 custom 根（rank 300）：一份被改写的同名技能会
        **静默顶掉**插件里那份，于是分不清是 harness 变好还是技能被换掉了。这条闸把
        「改插件自己的技能」这件事挡在门外。
        """
        errs: list[str] = []

        for name in dsh_skill_names(tree):
            if not _KEBAB.match(name):
                errs.append(
                    f"技能名 `{name}` 不是 kebab-case：dsh 的 skill-filesystem 要求 "
                    f"kebab-case，违反会被静默丢弃"
                )
                continue
            plugin_skill = _PLUGIN_SKILLS_DIR / name / "SKILL.md"
            if not plugin_skill.is_file():
                continue
            same = tree[f"skills/{name}/SKILL.md"] == plugin_skill.read_text(encoding="utf-8")
            if not same:
                errs.append(
                    f"技能 `{name}` 与插件自带的那份不同：dsh 的技能注册表按 rank 合并，"
                    f"项目根（rank 100）会**静默盖掉**插件的 custom 根（rank 300），"
                    f"于是分不清是 harness 变好还是技能被换掉了。改写 plugin 自己的技能"
                    f"不在本轮范围内——要改就换一个新名字"
                )

        for rel, body in tree.items():
            if rel == DSH_SURFACE.always_on[0] and not body.strip():
                errs.append(f"{rel} 是空的：它承载系统提示，空了等于没有系统提示")

        # c5 / c8 的座位在这个宿主上根本没开（`allow_subagents=False`、
        # `plugin_dir=None`）。提案阶段已经把这两个前缀的文件挡掉了
        # （`harness2/core/recursion.py:212-224`：`read_tree` 收 `rejected`
        # 列表，非空就整份提案 `continue` 掉）。**但那是单点防御**：
        # 这里（适配层的树不变量）此前不查这两个前缀，于是 2026-10-21 实测
        # 塞一个 `plugin/evil.ts` 进树会**静默通过** `validate_tree`——
        # 提案阶段的闸一旦被绕过（换执行器、手搓树、`--tree` 直接指过去），
        # 就没有第二道闸了。提示面对 proposer 说的是「整份提案被拒」，
        # 那句话在提案阶段是真的；这里补的是同一个事实在适配层的机械形态。
        for rel in tree:
            head = rel.split("/", 1)[0]
            if head in ("sub_agents", "subagents") or (
                    head == "plugin" or head == "plugins"):
                errs.append(
                    f"`{rel}` 不在这个宿主的可编辑面上：c5 子智能体与 c8 插件在 dsh "
                    f"上被宿主关掉了（`allow_subagents=False` / `plugin_dir=None`），"
                    f"写进去也不会生效。要复用就用技能（`skills/<name>/SKILL.md`）"
                    f"或脚本（`scripts/<name>.py`）"
                )

        if errs:
            raise ValueError(" | ".join(errs))

    def rollout_integrity(self, run_dir: Path) -> str:
        """这条 rollout 的证据**自不自洽**。返回空串 = 自洽；非空 = 作废理由。

        为什么需要这一条：**产物在不在**是判据的一大部分（「交付了 poster.png
        吗」），而产物住在工作区里。工作区是会被后来的进程重建的——被杀的
        跑批重启、换了臂又跑回来、别的工具扫过这个目录——重建之后，
        `final.txt` 还在说「交付了 poster.png」，工作区里却什么都没有了。

        那一刻磁盘上是一副**自相矛盾**的样子，而判据正是拿这两处对着看的。
        照直判出来的结论（「没交付」）量的是**我自己的进程管理**，不是智能体
        的行为——2026-10-20 实测踩过：基准臂 r1/r2 因此被记成 0.6，而它们
        自己其实交付了（`final.txt` 与事件流都在）。

        所以这里只认一条硬不变量：**任务文件必须写在 rollout 结束之前**。
        `task.txt` 在 launch 时写、`exit_code` 在收尾时写；任务文件比收尾还
        新，就说明这个 run 目录在 rollout 之后被重建过——这条 rollout 作废
        （**不是零分**：它是「没测到」）。
        """
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            return "run 目录不存在"
        exit_file = run_dir / "exit_code"
        if not exit_file.is_file():
            return "rollout 没跑完（没有 exit_code）"
        task_file = run_dir / "task.txt"
        if not task_file.is_file():
            return "rollout 没有任务文件"
        workspace = run_dir / "workspace"
        if not workspace.is_dir():
            return "工作区不见了"
        try:
            t_task = task_file.stat().st_mtime
            t_exit = exit_file.stat().st_mtime
        except OSError as exc:  # pragma: no cover - 竞态
            return f"读不了 run 目录的时间戳：{exc}"
        if t_task > t_exit + 1.0:
            return (
                "run 目录在 rollout 结束之后被重建过"
                "（任务文件比收尾还新）——产物已被后来的进程擦掉，这条 rollout 作废"
            )
        return ""

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        """机械判据。`None` = 判据本身失败（不是零分，也绝不被缓存成零分）。

        这条正是 RSIAgent 论文 §4.2 的「评测隔离」在 harness2 侧的对应物：
        判据只在这一步跑，方法层拿不到它。
        """
        from bench_usine import run_checks

        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            return None
        events = self._events_path(run_dir)
        if not events.is_file():
            return None
        task = task_by_id(task_id)
        traj = self.trajectory(run_dir, obs_trunc=50_000)
        final = self.final_text(run_dir)
        try:
            # `run_dir` 传进去：「产物存在」那类判据要真的去看磁盘。
            score, outcomes = run_checks(task, traj, final, run_dir=run_dir)
        except Exception:
            return None
        n_passed = sum(1 for o in outcomes if o.passed)
        return {
            "task_id": task_id,
            "score": round(score, 4),
            # harness2 的 judge/report 读这三个键（core/judge.py 的 judge_one），
            # 所以机械判据的分数要投影成「过了几条 / 共几条」——报告层才认得。
            "n_passed": n_passed,
            "n_criteria": len(outcomes),
            "all_pass": bool(outcomes) and n_passed == len(outcomes),
            "judge": "mechanical",
            "checks": [
                {"name": o.name, "passed": o.passed, "evidence": o.evidence} for o in outcomes
            ],
            "final_text": final,
        }

    # ── 诊断 ──────────────────────────────────────────────────────────────────

    def run_view(self, task_id: str, run_id: str) -> RunView:
        run_dir = self.runs_root / task_id / run_id
        ok = run_dir.is_dir()
        return RunView(
            label=run_id,
            run_id=run_id,
            run_dir=run_dir,
            ok=ok,
            delivered=ok and self.delivered(run_dir),
            error="" if ok else "missing run dir",
        )


__all__ = ["UsineAdapter", "BASE_HARNESS", "PLUGIN_SKILL_NAMES"]
