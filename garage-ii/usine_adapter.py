#!/usr/bin/env python3
"""usine_adapter.py —— harness2 的 BenchmarkAdapter：usine 产线 × dsh 执行器。

harness2 的 benchmark 接缝是一组纯值/纯函数：`tasks` / `task_prompt` / `execute` /
`delivered` / `trajectory` / `deliverable_*` / `base_harness` / `validate_tree` / `score`。
本文件把这些接缝接到两件真东西上：

- **dsh**（执行器）——`DshSubstrate` 提供可编辑面与装配；本文件提供**启动体**：
  把装配好的工作区交给 `dsh --profile headless --json`，把事件流落盘。
- **usine 的十份技能与十八个工具面**（被改进对象）——基准 harness 树由
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
from dsh_provider import MINIMAX_MODEL, Relay, make_patch
from dsh_substrate import (
    DSH_SURFACE,
    DshSubstrate,
    dsh_skill_names,
    render_canonical_events,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BASE_HARNESS = HERE / "harness_base"

#: 插件里那十份技能名——基准树里带着它们（基准 harness 必须与被改进对象同源），
#: 所以「同名」本身不违规，**同名且内容不同**才违规（见 validate_tree）。
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

#: 插件那十份技能的真实位置——同名技能的内容比对就是拿它当基准。
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
    ):
        self.runs_root = Path(runs_root)
        self.timeout = int(timeout)
        self.model = model or MINIMAX_MODEL
        self.provider = provider
        self.only_tasks = list(only_tasks) if only_tasks else None
        # rollout 串行锁。harness2 的 agg 模式会并行跑 2 个候选 rollout，而
        # `usine_verify` 跑的是 **usine 仓里的全量门禁**（typecheck + vitest）——
        # 同一个仓里并发跑两遍门禁会互相踩（纪律里明写「不要并发跑」）。
        # 这里把它从「文本纪律」变成「机制约束」：文本管知道，机制管做到。
        #
        # **只有会跑全量门禁的那一格需要串行**（2026-10-20 实测改的）：一律串行时，
        # 海报格那种 45 次工具调用的 rollout 要 13 分钟 × 12 次 ≈ 2.6 小时，
        # 而机器 CPU **76% 空闲**——瓶颈是模型 API 的往返，不是机器。
        # 锁到「该串行的那一格」上，剩下的格子并发跑，墙钟从 2.6 小时降到 ~1 小时。
        self._rollout_lock = threading.Lock()
        self._serial_tasks = _serial_tasks_needed()
        # 中继：把 dsh 的 anthropic 请求转成 MiniMax 运行时认的那一路（摘 x-api-key、
        # 换 Authorization: Bearer）。**token 只活在中继的内存里**，不进磁盘。
        self._relay = relay if relay is not None else Relay()
        self._relay_started = False
        # 只有**自己起的中继**才归自己关。注入进来的中继是整个 sweep 共享的——
        # adapter 被回收时把它关掉，会把还在跑的中继杀掉（症状是别的阶段
        # 突然 `Connection refused`）。
        self._owns_relay = relay is None
        self._substrate = DshSubstrate(launcher=self._launch)
        #: `feuille` 垫片目录（PATH 用）。第一次跑 rollout 时才造。
        self._shim_dir: Path | None = None

    def _ensure_relay(self) -> None:
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
        if split not in ("all", "train", "eval"):
            raise ValueError(f"未知 split：{split}")
        # v1 没有 train/eval 切分：任务集小到一次性跑完，切了反而让样本更小。
        ids = [t.task_id for t in TASKS]
        if self.only_tasks:
            wanted = set(self.only_tasks)
            unknown = wanted - set(ids)
            if unknown:
                raise ValueError(f"未知任务：{sorted(unknown)}")
            ids = [t for t in ids if t in wanted]
        return ids

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
        tree = HT.read_tree(DSH_SURFACE, Path(tree_dir))
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
        return h.hexdigest()[:12]

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        """跑一次 rollout，返回 run 目录。

        `harness_dir=None` 表示**未经修改的基准 harness**（harness2 的对照臂）。
        """
        src = Path(harness_dir) if harness_dir else self.base_harness()
        tree = HT.read_tree(DSH_SURFACE, src)
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
        # `feuille` 必须在 PATH 上：技能手册通篇写 `feuille poster …`，
        # `which feuille` 落空会让智能体判定「工具面没有包」而停手（2026-10-20 实测）。
        if self._shim_dir is None:
            self._shim_dir = _feuille_shim_dir()
        env["PATH"] = f"{self._shim_dir}{os.pathsep}{env.get('PATH', '')}"

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
        """
        p = self._events_path(run_dir)
        if not p.is_file():
            return "(no events file)"
        return render_canonical_events(p, obs_trunc=obs_trunc, max_chars=200_000)

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

        关于同名技能：基准树里带着插件那十份技能（基准 harness 必须与被改进对象同源），
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
