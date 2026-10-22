#!/usr/bin/env python3
"""run_usine_h2.py —— garage-ii 的运行手册入口：usine 产线 × dsh 执行器的 harness 演化。

**这一层是桥，不是新引擎。** 演化方法、提案、组合、选择、经验库，全部是 harness2
（`theatre-ii/`）自己的；本文件只做三件事：

1. 把 `--bench jb|wb|lab --substrate oc|cx` 那一格换成 `--bench usine --substrate dsh`；
2. 装上 dsh 的 preflight（上游那份是给另外三格写的，硬依赖 opencode 检出）；
3. 把**花钱的那一步**（sweep）锁在 ack token 后面。

纪律与 `garage/run_usine.py` 对齐：**自检先行，执行需 ack，发布永不自动**。
harness2 的 sweep 每个任务是 R=4k 次 rollout + P=3k 次改 harness 的会话——没有 ack
就开跑，等于把「用户喊跑才跑」这条纪律扔了。

    python3 garage-ii/run_usine_h2.py --phase preflight
    python3 garage-ii/run_usine_h2.py --phase sweep --dry-run
    python3 garage-ii/run_usine_h2.py --phase sweep --ack RUN-USINE-H2-SWEEP --k 1
    python3 garage-ii/run_usine_h2.py --phase judge
    python3 garage-ii/run_usine_h2.py --phase report
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
THEATRE_II = REPO / "theatre-ii"

# 引擎先上路径，再上本层——顺序不能反（harness2 的包要从 theatre-ii 根导入）。
for p in (str(THEATRE_II), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness2 import config as H2CONFIG  # noqa: E402
from harness2.cli import _common as C  # noqa: E402
from harness2.core import judge as J  # noqa: E402
from harness2.core import report as R  # noqa: E402
from harness2.core import schedule as SCHED  # noqa: E402
from harness2.core.proposer import Proposer  # noqa: E402

# Windows 宿主上垫上引擎 `_write_summary` 要用的 fcntl（POSIX 专属模块）。
# 2026-10-21 实测：不垫的话 sweep 的 12 格 rollout 真跑约两小时后，全死在
# 写 summary.json 的 `import fcntl` 上（token 全白烧，而 preflight 当时是绿的）。
# POSIX 上 install() 恒不装，stdlib 的 fcntl 不受影响。
import posix_compat  # noqa: E402

posix_compat.install()

from dsh_provider import (  # noqa: E402
    ENV_CONTEXT_WINDOW,
    ENV_MAX_TOKENS,
    LLM_CONFIG,
    MINIMAX_MODEL,
    Relay,
    resolve_llm_endpoint,
)
from preflight import DEFAULT_ROOT, run_all  # noqa: E402
from usine_adapter import UsineAdapter  # noqa: E402

SWEEP_ACK = "RUN-USINE-H2-SWEEP"


def _csv(raw: str) -> tuple[str, ...]:
    """逗号列表 → 元组。harness2 的 `_csv` 是 cli/run_sweep.py 的模块私有函数，
    这里自己写一份，不去戳上游的私有面。"""
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _pid_alive(pid: int) -> bool:
    """这个 pid 还活着吗？**不许用会杀人的办法问。**

    2026-10-21 实测（Windows）：`os.kill(pid, 0)` 在 Windows 上**不是**存在性检查——
    CPython 的 `win32_kill` 对除 CTRL_C_EVENT / CTRL_BREAK_EVENT 以外的信号一律走
    `TerminateProcess(handle, sig)`，**sig=0 也会杀**（退出码 0）。于是原来的锁：

    - 第二个进程来抢锁 → 探活 → **把持锁的那个进程杀了** → 自己再拿锁；
    - 自检里探自己的 pid → **把自己杀了**（离线自检在第 [9] 节当场死掉）。

    POSIX 上 `kill(pid, 0)` 是安全的探活，Windows 上必须另走一条：
    `OpenProcess` + `GetExitCodeProcess`（ STILL_ACTIVE == 259）。
    """
    if pid <= 0:
        return False
    import os

    if os.name == "nt":  # pragma: no cover - 平台分支
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except ProcessLookupError:
        return False
    return True


def _acquire_run_root_lock(root: Path, key: str = ""):
    """给 run root 加一把锁：**同一个命名空间**上不许同时跑两个 sweep。

    为什么需要：两个 sweep 共用一个 run root 时，**产物会互相覆盖**——
    第二个 sweep 的 `base1` 会盖掉第一个的 `base1`，轨迹、事件流、分数全对不上，
    而且**不报错**：读数看起来正常，数字是错的。

    2026-10-20 实测踩过：一次 `task_stop` 只杀了外层 shell，`python3` 子进程还活着，
    第二个 sweep 在同一个 root 上开跑，两边同时写 `adapt/<ns>/<task>/<label>/`。
    症状是「提案阶段 Connection refused」（一个 sweep 的中继被另一个的清理动作杀了）
    加「rollout 目录一会儿有文件一会儿空」。**这属于不报错的静默错误**，所以要有锁。

    **锁的粒度 = 碰撞的单位（2026-10-21 改）**。原来锁的是整个 run root
    （`adapt/.sweep.lock`），比真正的碰撞单位粗：产物落在
    `adapt/<ns>/<task>/<label>/`，而 ns 由 (bench, substrate, mode, k, seed, tag)
    决定——**不同 tag 的两条实验各写各的目录，本来就不会互相覆盖**。
    粗锁的代价是：两条**文件互不相干**的实验（同一台机器、同一台 B 线）也被挡在
    门外，只能排队。粗锁还漏了一种碰撞：repeat 相位锁的是
    `<root>/.sweep.lock`，跟 sweep 的锁**不是同一个文件**——两个相位各锁各的，
    等于没锁到同一件事上。

    现在锁文件带上 key（命名空间名 / 臂名）：同 key 互斥，不同 key 各跑各的。
    锁是 run root 里的一个文件（`~/<root>/adapt/.sweep.<key>.lock`），内含 pid。
    进程已经不在了（stale lock）就自动接管。
    """
    import os

    lock_dir = Path(root)
    lock_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if (ch.isalnum() or ch in "-._") else "_" for ch in (key or ""))
    lock = lock_dir / (f".sweep.{safe}.lock" if safe else ".sweep.lock")
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        alive = _pid_alive(pid)
        if alive:
            raise RuntimeError(
                f"run root {root} 的命名空间 {key or '(默认)'} 上已经有一个 sweep 在跑"
                f"（pid {pid}）。两个 sweep 共用一个命名空间会互相覆盖产物，"
                f"**而且不报错**。先停掉那个，或换一个 --tag/--seed。"
            )
        lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def _release_run_root_lock(lock: Path) -> None:
    try:
        lock.unlink(missing_ok=True)
    except OSError:
        pass


def _make_relay(choice: dict):
    """按 LLM 选择造中继：走统一配置时用 `llm_relay.mjs` + slug。"""
    if choice.get("script") is None:
        return Relay()
    return Relay(script=choice["script"], extra_args=choice["extra"])


def _llm_choice(args) -> dict:
    """这次跑批用哪个模型、哪个中继、窗口多大。

    两条路：
    - **默认**：MiniMax 运行时（OAuth token + `~/.minimax/config.yaml` 的端点）；
    - **`--llm <slug>`**：统一配置（`config/.env`）里的网关（`fuyao-coding` 等），
      端点与凭据按 slug 解析，**凭据只活在中继进程内存里**。

    给了 `--llm` 就**以它为准**（`--model` 只是默认的 MiniMax 型号）。
    """
    if not getattr(args, "llm", "").strip():
        return {
            "model": args.model,
            "script": None,
            "extra": [],
            "context_window": 0,
            "max_tokens": 0,
            "api": "anthropic-messages",
        }
    slug = args.llm.strip()
    cfg = Path(args.llm_config) if getattr(args, "llm_config", "") else LLM_CONFIG
    # **fail-closed**：端点对缺了就当场报错，不静默退回 MiniMax。
    resolve_llm_endpoint(slug, cfg)
    return {
        "model": slug,
        "script": HERE / "llm_relay.mjs",
        "extra": ["--slug", slug, "--config", str(cfg)],
        "context_window": ENV_CONTEXT_WINDOW,
        "max_tokens": ENV_MAX_TOKENS,
        # 网关这一路走 **OpenAI 风格的线上协议**：同一个网关、同一个模型，
        # `/chat/completions` 默认**不推理**，`/messages` 默认推理 1.1 万–2.6 万字符
        # （实测 36–47s vs 56–116s，整条 rollout 的实际耗时大头就砸在那个块上）。
        "api": (getattr(args, "llm_api", "") or "openai-completions").strip(),
    }


def _adapter(args) -> UsineAdapter:
    only = [t.strip() for t in args.only_tasks.split(",") if t.strip()] if args.only_tasks else None
    choice = _llm_choice(args)
    relay = None
    if choice["script"] is not None:
        relay = Relay(script=choice["script"], extra_args=choice["extra"])
    # **provider 名字跟着协议走**：pi-ai 会按 provider id 猜这个端点的默认行为
    # （`catalog.ts`：私有网关的 URL 说明不了自己，只能靠 provider id 推断）。
    # 协议是 OpenAI 风格却挂个叫 `anthropic` 的 provider id，等于让它拿
    # Anthropic 的默认去发 OpenAI 的请求——compat 开关我们虽然显式钉了几个，
    # 但没钉的那些仍可能按 id 猜错。
    provider = "openai" if choice.get("api") == "openai-completions" else "anthropic"
    return UsineAdapter(
        runs_root=args.root,
        timeout=args.timeout,
        model=choice["model"],
        provider=provider,
        only_tasks=only,
        relay=relay,
        context_window=choice["context_window"],
        max_tokens=choice["max_tokens"],
        api=choice.get("api", "anthropic-messages"),
    )


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run_usine_h2", description=__doc__)
    ap.add_argument(
        "--phase",
        choices=("preflight", "sweep", "judge", "report", "repeat", "compare", "reselect"),
        default="preflight",
        help=(
            "preflight=自检（默认，不花钱）｜sweep=演化（花钱，要 ack）｜judge=机械判据｜"
            "report=汇总｜repeat=同一棵树重复 rollout（量零分布，花钱）｜compare=并排读两个臂｜"
            "reselect=只重跑选择这一步（不重跑 rollout，花钱）"
        ),
    )
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="run root（必须在仓库外）")
    ap.add_argument("--ack", default="", help=f"执行 sweep 的确认口令（{SWEEP_ACK}）")
    ap.add_argument("--k", type=int, default=1, help="任务级递归预算：每个任务 R=4k 次 rollout")
    ap.add_argument(
        "--mode",
        "--modes",
        dest="modes",
        default="parallel",
        help="parallel（宽）| sequential（深），逗号列表",
    )
    ap.add_argument("--seed", type=int, default=None, help="任务流顺序种子")
    ap.add_argument(
        "--split",
        default="all",
        choices=("all", "train", "test", "both"),
        help=(
            "任务切分。all=全部一起（**提案与测量同一批题，量不出泛化**）；"
            "train=只跑训练侧；test=只跑 eval 侧；"
            "both=两段式（先 train 学、再用同一份 library 跑 eval）——泛化读数走这个"
        ),
    )
    ap.add_argument("--only-domains", default="", help="只跑这些产线层（逗号分隔）")
    ap.add_argument("--max-tasks", type=int, default=None, help="每层最多几个任务")
    ap.add_argument("--workers", type=int, default=1, help="并行跑几个产线层")
    ap.add_argument("--timeout", type=int, default=900, help="单次 rollout 的时间上限（秒）")
    ap.add_argument(
        "--model",
        default=MINIMAX_MODEL,
        help=f"solver 与 proposer 用的模型（{MINIMAX_MODEL}）",
    )
    ap.add_argument(
        "--llm",
        default="",
        help=(
            "走**统一配置**的模型 slug（如 fuyao-coding）：端点与凭据从 "
            "`config/.env` 按 slug 解析（最长前缀优先，组级兜底），"
            "凭据只活在中继进程内存里。给了它，--model 就由 slug 决定。"
        ),
    )
    ap.add_argument(
        "--llm-config",
        default="",
        help="统一配置路径（默认 `config/.env`）",
    )
    ap.add_argument(
        "--llm-api",
        default="",
        help=(
            "线上协议（默认 `openai-completions`）：同一个网关、同一个模型，"
            "`/chat/completions` 默认不推理，`/messages` 默认推理 1 万+ 字符"
            "（实测耗时 36–47s vs 56–116s）"
        ),
    )
    ap.add_argument(
        "--proposer-timeout", type=int, default=600, help="单次改 harness 会话的时间上限（秒）"
    )
    ap.add_argument(
        "--only-tasks",
        default="",
        help="只跑这些任务（逗号分隔）；默认全跑（现在 7 个，见 bench_usine.TASKS）",
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印任务流与命名空间，不开跑")
    ap.add_argument(
        "--tree",
        default="base",
        help=(
            "repeat 阶段用哪棵树：`base`（基准 harness）或一个目录"
            "（子目录名当任务名；`arms.extract_adopted_trees` 抽出来的就是这个形状）"
        ),
    )
    ap.add_argument("--repeats", type=int, default=3, help="repeat 阶段每题跑几次（默认 3）")
    ap.add_argument(
        "--arm-workers",
        type=int,
        default=0,
        help=(
            "一条臂里同时跑几次 rollout（0=自动，取 min(n,4)）。"
            "瓶颈在模型往返不在机器，并行后一条臂的总耗时≈一次 rollout 的时长"
        ),
    )
    ap.add_argument(
        "--append",
        action="store_true",
        help="repeat 阶段**接着已有臂往下加**（把 n=3 的零分布扩到 n=10 时用它）",
    )
    ap.add_argument("--tag", default="", help="repeat 阶段的臂名（默认按树推）")
    ap.add_argument("--base-arm", default="", help="compare 阶段当零分布的臂")
    ap.add_argument("--evolved-arm", default="", help="compare 阶段当演化臂的臂")
    return ap


def _print_stream(adapter, args, modes) -> int:
    # **dry-run 也要按 split 分流**。2026-10-21 之前这里硬写 `split="all"`，
    # 于是 `--split train --dry-run` 打印的是全部任务——dry-run 的全部意义就是
    # 「先说清楚要跑什么」，而它说的和真跑的不一样。这类「参数收下却忽略」
    # 在 `usine_adapter.tasks()` 里也有一处（已修）；同一种错犯两次，说明
    # 该查的是**每条取值路径**，不是单点。
    split = getattr(args, "split", "all")
    if split == "both":
        # 两段式在 dry-run 里把两侧都列出来，并标明哪边先跑。
        total = 0
        for stage in ("train", "test"):
            by_domain = SCHED.task_stream(
                adapter,
                split=stage,
                seed=args.seed,
                only_domains=_csv(args.only_domains),
                max_tasks=args.max_tasks,
            )
            n_stage = sum(len(v) for v in by_domain.values())
            total += n_stage
            print(f"\n# === 第{'一' if stage == 'train' else '二'}段 {stage}（{n_stage} 个任务）===")
            print(f"# {adapter.spec.name}-{adapter.substrate.name} k={args.k} modes={','.join(modes)}")
            print(f"#   library: {C.library_root_for(adapter, args.k, seed=args.seed)}（两段共享）")
            n = 0
            for domain, tasks in by_domain.items():
                for task in tasks:
                    n += 1
                    print(f"{n:>4}  {domain:<20} {task}")
        if not total:
            print("# 零个任务被排上——拒绝报成功")
            return 1
        cov = adapter.split_coverage()
        print(
            f"\n# 两段式共 {total} 个任务，切分指纹 {cov['digest']}"
            f"（train {len(cov['train'])} / eval {len(cov['test'])}）"
        )
        print("# 读法：eval 段读到 train 段写进 library 的经验 ⇒ 这是**迁移**读数")
        return 0

    by_domain = SCHED.task_stream(
        adapter,
        split=split,
        seed=args.seed,
        only_domains=_csv(args.only_domains),
        max_tasks=args.max_tasks,
    )
    ns = SCHED.ns(adapter.spec.name, adapter.substrate.name, "agg", args.k, seed=args.seed)
    tag = _stage_tag(split)
    stage_ns = f"{ns}-{tag}" if tag else ns
    print(f"# {adapter.spec.name}-{adapter.substrate.name} k={args.k} modes={','.join(modes)} split={split}")
    print(f"#   namespace: {stage_ns}")
    print(f"#   runs root: {adapter.spec.runs_root}")
    print(f"#   library:   {C.library_root_for(adapter, args.k, seed=args.seed)}")
    n = 0
    for domain, tasks in by_domain.items():
        for task in tasks:
            n += 1
            print(f"{n:>4}  {domain:<20} {task}")
    if not n:
        print("# 零个任务被排上——拒绝报成功")
        return 1
    print(f"# 共 {n} 个任务，{len(by_domain)} 个产线层")
    if split == "all":
        print(
            "# 注意：split=all 时**提案与测量是同一批题**——"
            "这一轮量不出泛化（要泛化读数用 --split both）"
        )
    return 0


def _phase_sweep(args) -> int:
    adapter = _adapter(args)
    modes = C.parse_modes(args.modes)

    # dry-run 不花钱，所以**不**要 ack——ack 锁的是「真跑」，不是「看一眼要跑什么」。
    if args.dry_run:
        return _print_stream(adapter, args, modes)

    if args.ack != SWEEP_ACK:
        print(
            f"sweep 要花钱，先把确认口令给我：--ack {SWEEP_ACK}",
            file=sys.stderr,
        )
        return 1

    errs, warns = run_all(args.root)
    for w in warns:
        print(f"warn: {w}")
    if errs:
        print("preflight 未通过，什么都没跑：")
        for e in errs:
            print(f"  - {e}")
        return 1

    # 执行器就绪闸：轨迹走的是 **SDK 客户端的规范事件流**（`dsh_run.mjs`），
    # 不是 `--json` 投影——所以这里查的是「桥能不能跑」，不是「dsh 有没有 --json」。
    from dsh_provider import ProviderError

    try:
        probe = _make_relay(_llm_choice(args))
        probe.start()
        probe.close()
    except (ProviderError, OSError) as exc:
        print(
            f"执行器桥起不来：{exc}\n"
            f"  补救：确认 node 可用、~/.minimax 运行时已登录、"
            f"且 usine/packages/dsh-plugin/dist/index.mjs 已构建"
            f"（pnpm --filter @feuille/dsh-plugin build）",
            file=sys.stderr,
        )
        return 1

    if not args.model or not args.model.strip():
        print(
            "改 harness 的那个模型没指定（--model）。"
            "（dsh 是**执行器**，不是改 harness 的模型——后者走本层自带的 proposer 通道。）",
            file=sys.stderr,
        )
        return 1

    runs_root = C.runs_root_for(adapter)
    library_root = C.library_root_for(adapter, args.k, seed=args.seed)
    summary_ns = C.summary_namespace(adapter, args.k, seed=args.seed)

    # 锁的 key = **命名空间**（碰撞单位）：同 ns 的两个 sweep 互斥，
    # 不同 ns（不同 --tag/--seed）的两条实验文件各写各的，可以并存。
    lock = _acquire_run_root_lock(runs_root, summary_ns)
    try:
        return _run_sweep(args, adapter, modes, runs_root, library_root, summary_ns)
    finally:
        _release_run_root_lock(lock)


def _run_two_stage(args, adapter, modes, runs_root, library_root, summary_ns) -> int:
    """两段式 sweep：**train 学，eval 测**。泛化测量的全部接缝都在这里。

    两条段之间的三个接缝
    --------------------

    1. **共享 library**：两段用同一个 `library_root`（由 `--split both` 时的
       `tag` 保证 `root_for` 落到同一目录）。train 段写进去的 `EXPERIENCE.md`
       与采纳的树，eval 段的提案器读得到——`schedule._run_one_mode` 里的
       `lib_dir = mode_lib.context_dir()` 就是那条通路。
    2. **不同 namespace**：两段经 `_stage_tag` 各拿 `train` / `eval` 的引擎 tag，
       于是 run 目录（`adapt/<ns>-train/`、`adapt/<ns>-eval/`）、`_sweeps/*.json`
       记录互不覆盖（否则 eval 段会把 train 段的读数盖掉，两边就只剩一份），
       且 `_report_stage_fallbacks` 找的就是这两个目录——**阶段回退闸在两段式下
       必须活着**：找不到目录时它不报错，只是恒空返回，那是最隐蔽的假绿。
       tag 与目录名必须从同一个函数派生（`_stage_tag`），两处各写一遍必漂移。
    3. **eval 段不写 library**：这条**必须由代码保证，不靠自觉**——因为引擎每次
       `run_sweep` 都会在 `reflect_adoption` 里写 library。所以 eval 段跑完之后
       要把 library 里 eval 任务新长出来的条目**摘掉**，只留 train 阶段的。
       不摘的话，「第二次跑」就等于「eval 也学了一遍」，泛化读数立刻失效。

    为什么不能只改一个参数
    ----------------------

    引擎的 `run_sweep(split=…)` 是**单 split 全流程**：同一个 split 上既提案、
    又测量、又采纳。「在同一批题上学、在同一批题上考」这个形状，改一个参数改不出来。

    一条要明说的边界
    ----------------

    train 段与 eval 段**各跑一次 sweep**，所以 eval 段里的提案器**仍然会改树**——
    它拿到 train 的经验、在 eval 题上继续演化。这**不是**纯「学到的树直接考试」，
    而是「学到的经验能不能让下一次演化更快更好」。后者也是一种泛化（迁移），
    但它比「冻结树直接考」弱。这两种读法必须分开说，报告里按 `transfer` 记，
    **不许混称「泛化」**。
    """
    print(
        f"两段式 sweep（train → eval）：\n"
        f"  train 段：{len(adapter.tasks('train'))} 个任务，产出写进 library\n"
        f"  eval  段：{len(adapter.tasks('test'))} 个任务，**读同一份 library**\n"
        f"  library：{library_root}",
        flush=True,
    )

    # ── 第一段：train ───────────────────────────────────────────────────────
    print(f"\n=== 第一段 train（{len(adapter.tasks('train'))} 格）===", flush=True)
    rc_train = _sweep_one(
        args,
        adapter,
        modes,
        runs_root,
        library_root,
        summary_ns,
        split="train",
        # 两段式的门只拦**测量无效**（exception / 域死掉）。partial（演化跑了、
        # 候选没交付）是完成的负读数——拦它等于要求「train 每格候选必须交付」
        # 才许测泛化，k=1 的 rollout 随机性下 eval 段永远进不去。理由全文见
        # `_sweep_one` 的 docstring。
        partial_blocks=False,
    )
    if rc_train != 0:
        print(
            "\ntrain 段有**测量无效**的格子（exception / 域死掉）——**不要**接着跑"
            " eval 段：eval 侧要量的正是 train 段学到的东西，train 段本身错了，"
            "那个读数没有意义。（partial 不拦——那是完成的负读数，上面已逐格列出。）",
            file=sys.stderr,
        )
        return rc_train

    # train 段写进 library 的条目，先记下来（eval 段之后要把**新长出来的**摘掉）。
    before = _library_entries(library_root)

    # ── 第二段：eval ────────────────────────────────────────────────────────
    print(f"\n=== 第二段 eval（{len(adapter.tasks('test'))} 格）===", flush=True)
    rc_eval = _sweep_one(
        args,
        adapter,
        modes,
        runs_root,
        library_root,
        summary_ns,
        split="test",
        partial_blocks=False,
    )

    # **摘掉 eval 段新写进 library 的条目**：库必须停在 train 段结束时的样子。
    removed = _trim_library(library_root, before)
    if removed:
        print(
            f"\n已从 library 摘掉 eval 段新长的 {len(removed)} 项（{', '.join(removed[:4])}…）——"
            f"库停在 train 段结束时的状态。理由见 `_run_two_stage` 的 docstring："
            f"eval 也写库的话，「第二次跑」就变成「eval 也学了一遍」，泛化读数失效。",
            flush=True,
        )

    rec = {
        "two_stage": True,
        "train_ns": f"{summary_ns}-train",
        "eval_ns": f"{summary_ns}-eval",
        "train_tasks": adapter.tasks("train"),
        "eval_tasks": adapter.tasks("test"),
        "split": adapter.split_coverage(),
        "library_root": str(library_root),
        "rc_train": rc_train,
        "rc_eval": rc_eval,
        "library_trimmed": removed,
        "reading": "transfer",
        "reading_note": (
            "这是**迁移**读数（train 的经验被 eval 段的演化用上），"
            "不是「冻结树直接考」的纯泛化读数。两者不许混称。"
        ),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec_path = runs_root / "_sweeps" / f"{summary_ns}-two-stage-{stamp}.json"
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    print(f"\n两段式记录：{rec_path}")
    print(f"next:   python3 {Path(__file__).name} --phase compare --root {args.root}")
    return rc_eval


def _stage_tag(split: str) -> str:
    """split → 引擎 tag：**非 all 的 split 各自落带后缀的命名空间**。

    引擎的 run 目录（`adapt/<ns>/<task>/`）由 `run_sweep(tag=…)` 里的 tag 决定。
    2026-10-21 之前 `_sweep_one` 硬写 `tag=""`，于是 `--split both` 的 train 段与
    eval 段**写进同一个** `adapt/<ns>/`——而 `_report_stage_fallbacks` 拿着带
    `-train` / `-eval` 后缀的目录名去找，**永远找不到**：阶段回退闸在两段式下
    静默失效（这类「账面绿」正是 §12.2 那种静默失败）。tag 与后缀必须从同一个
    函数派生，两处各写一遍就会再漂移一次。
    """
    if split == "all":
        return ""
    if split == "train":
        return "train"
    if split == "test":
        # 任务面的词是 test（引擎词汇表：all/train/test），读数侧的习惯词是 eval
        # （`_run_two_stage` 的 `-eval` 后缀）。这里跟读数侧，保持记录一致。
        return "eval"
    raise ValueError(f"未知 split：{split!r}（只认 all / train / test / both）")


def _stage_sides(adapter, args) -> list[tuple[str, str]]:
    """judge / report / reselect 该看哪几侧：`(命名空间, 侧标签)` 列表。

    命名空间与 sweep 落盘的目录**同一套派生**（`_stage_tag`）——`--split train`
    的 sweep 落在 `adapt/<ns>-train/`，judge 就去那里找；`--split both` 两段都判，
    **两侧分别出判据记录**（train 侧与 eval 侧不许合并成一个均值：合并正是
    §6.8 里「过拟合在读数上隐形」的那条通路）。
    """
    base = SCHED.ns(adapter.spec.name, adapter.substrate.name, "agg", args.k, seed=args.seed)
    split = getattr(args, "split", "all")
    if split == "both":
        return [(f"{base}-train", "train"), (f"{base}-eval", "eval")]
    tag = _stage_tag(split)
    side = {"": "all", "train": "train", "eval": "eval"}[tag]
    return [(f"{base}-{tag}" if tag else base, side)]


def _sweep_one(
    args, adapter, modes, runs_root, library_root, summary_ns, *, split: str,
    partial_blocks: bool = True,
) -> int:
    """跑一段 sweep。抽出来是为了让两段走**完全相同**的代码路径——
    两段各写一遍的话，「eval 段少跑一个步骤」这种错永远测不出来。

    `summary_ns` 是**不带段后缀**的基础命名空间；段后缀（`-train` / `-eval`）由
    `split` 经 `_stage_tag` 派生，引擎 tag、记录文件、审计目录、回退闸全部用它。

    **partial 与 exception 是两种东西**（2026-10-22 从实测里定下的口径）：

    - `exception` = 这一格的测量**无效**（域死掉 / 任务级异常）——读数作废，
      什么时候都必须拦；
    - `partial` = 演化**跑完了**但候选没交付产物（选择失败）——那是**完成的负读数**，
      不是无效测量。把 partial 也当「没跑干净」拦下 eval 段，等于要求
      「train 侧每一格的候选都必须交付」才许测泛化——k=1 下候选交付本身有
      rollout 随机性（2026-10-22 实测：同一条命令重跑，7 格 partial 里 3 格转 ok），
      再叠上网关 502 的抖动，eval 段会**几乎永远进不去**。partial 不拦，但要
      **说清楚**：它不进采纳库，train 侧读数里它就是「演化没交付」那一格。
      `partial_blocks=True` 保留单段模式的旧行为（退出码 1 提醒人去看）。
    """
    from dsh_provider import Relay  # noqa: F401  (保持与调用方同一导入面)
    from minimax_proposer import MinimaxProposer

    tag = _stage_tag(split)
    stage_ns = f"{summary_ns}-{tag}" if tag else summary_ns
    relay = _make_relay(_llm_choice(args))
    relay.start()
    try:
        adapter._relay = relay
        adapter._relay_started = True
        prop = MinimaxProposer(
            relay=relay,
            model=_llm_choice(args)['model'],
            timeout=args.proposer_timeout,
            api=_llm_choice(args).get('api', 'anthropic-messages'),
        )
        prop.audit_dir = runs_root / "_audit" / stage_ns
        rep = SCHED.run_sweep(
            args.k,
            adapter=adapter,
            prop=prop,
            selector_prop=prop,
            runs_root=runs_root,
            library_root=library_root,
            split=split,
            modes=modes,
            seed=args.seed,
            tag=tag,
            domain_parallel=args.workers,
            only_domains=_csv(args.only_domains),
            max_tasks=args.max_tasks,
            pool_policy="finals",
        )
    finally:
        relay.close()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec = runs_root / "_sweeps" / f"{stage_ns}-{stamp}.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    done = sum(int(d.get("done", 0)) for d in rep.get("domains", []))
    failed = sum(int(d.get("failed", 0)) for d in rep.get("domains", []))
    dead = [d["domain"] for d in rep.get("domains", []) if d.get("error")]
    # 引擎的 `failed` 把 partial 和 exception 混在一起数；两段式的门只认
    # exception（测量无效），partial 单独数出来说清楚。
    statuses = [
        (t.get("task"), t.get("status"))
        for d in rep.get("domains", [])
        for t in d.get("tasks", [])
    ]
    exceptions = sorted(t for t, st in statuses if st == "exception")
    partials = sorted(t for t, st in statuses if st == "partial")
    print(f"\nsweep[{split}] {stage_ns}: {done} 个任务完成，{failed} 个失败（partial {len(partials)} / exception {len(exceptions)}）")
    if dead:
        print(f"  死掉的产线层：{', '.join(dead)}")
    if exceptions:
        print(f"  exception（测量无效，必须拦）：{', '.join(exceptions)}")
    if partials:
        print(
            f"  partial（演化跑了、候选没交付——**实质读数**，不进采纳库）：{', '.join(partials)}"
        )
    print(f"record: {rec}")

    fell_back = _report_stage_fallbacks(runs_root, stage_ns)
    # **测量无效的必须拦**：域死掉或任务级 exception，这一段没有可用的读数。
    if dead or exceptions:
        return 1
    if partials and partial_blocks:
        return 1
    if fell_back:
        print(
            "\n注意：有阶段回退到基准树（上面的 error 是原因）。"
            "这些任务量到的是**基准 harness** 的表现，不是演化后的——"
            "先修掉阶段错误再读分数。"
        )
        if partial_blocks:
            return 1
    return 0


def _library_entries(library_root: Path) -> set[str]:
    """library 里现有的条目路径（相对路径）。用来比对「eval 段新长出来什么」。"""
    root = Path(library_root)
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _trim_library(library_root: Path, before: set[str]) -> list[str]:
    """把 library 恢复成 `before` 的样子，只删新长的文件；返回删掉的那些。

    **只删新增的文件，不动任何旧文件**——旧文件可能被 eval 段改写过，
    但「改写了什么」无法从文件集合上看出来，所以这里只做保守的那一半。
    这个限制要明说：**eval 段对已有文件的修改不会被回滚**，读数时要记住这一点。
    """
    root = Path(library_root)
    now = _library_entries(library_root)
    extra = sorted(now - before)
    removed: list[str] = []
    for rel in extra:
        p = root / rel
        try:
            if p.is_file():
                p.unlink()
                removed.append(rel)
        except OSError:
            continue
    # 删空的目录也清掉（否则 library 的 entries() 会看见空目录）。
    for d in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            continue
    return removed


def _run_sweep(args, adapter, modes, runs_root, library_root, summary_ns) -> int:
    """跑 sweep。**`--split both` 时走两段：先 train 学、再 eval 测。**

    为什么是两段而不是一段
    ----------------------

    引擎的 `run_sweep(split=…)` 是**单 split 全流程**：它在同一个 split 上既提案、
    又测量、又采纳。所以「在同一批题上学、在同一批题上考」这个形状，**改一个参数
    是改不出来的**——必须跑两次，且第二次要能读到第一次的成果。

    两段的接缝是 `library_root`：两次 sweep 拿到**同一个** `library_root`
    （`_phase_sweep` 只算一次、两段共用），train 段把学到的树与 `EXPERIENCE.md`
    写进 library；eval 段的提案器读同一份 library，所以摆在 eval 题面前的是
    train 学到的成果。

    一条要明说的边界：eval 段的提案器**仍然会改树**——它拿着 train 的经验、
    在 eval 题上继续演化。所以两段式给的是**迁移**读数，不是「冻结树直接考」的
    纯泛化读数，两者不许混称（docs/self-evolution.md §6.8）。

    一条硬约束：**eval 段结束后 library 必须停在 train 段结束时的样子**。
    引擎每次 `run_sweep` 都会在 `reflect_adoption` 里写 library——不摘掉的话，
    「第二次跑」就变成「eval 也学了一遍」，泛化读数立刻失效。这条由
    `_trim_library` 在代码里保证，不靠自觉。
    """
    if getattr(args, "split", "all") == "both":
        return _run_two_stage(args, adapter, modes, runs_root, library_root, summary_ns)

    # proposer 通道：本层自带的直连通道（上游的 opencode 通道要 vendor 半个第三方仓，
    # claude_cli 通道强制走 Vertex 而本机没有 ADC）。它与 solver 共用同一个本机中继，
    # 所以 token 只在中继的内存里。
    from dsh_provider import Relay
    from minimax_proposer import MinimaxProposer

    relay = _make_relay(_llm_choice(args))
    relay.start()
    try:
        adapter._relay = relay
        adapter._relay_started = True
        prop = MinimaxProposer(
            relay=relay,
            model=_llm_choice(args)['model'],
            timeout=args.proposer_timeout,
            api=_llm_choice(args).get('api', 'anthropic-messages'),
        )
        # 审计目录：改 harness 的每一笔都要能事后翻账（任务、回复、耗时）。
        prop.audit_dir = runs_root / "_audit" / summary_ns
        print(
            f"sweep {summary_ns}: {args.workers} 个产线层并行，层内按流序串行；"
            f"每个任务 R={4 * args.k} 次 rollout + P={3 * args.k} 次改 harness 会话",
            flush=True,
        )
        rep = SCHED.run_sweep(
            args.k,
            adapter=adapter,
            prop=prop,
            # selector 也走本通道：引擎默认的 selector 是上游的 opencode 通道
            # （要 vendor 半个第三方仓、且本机没有它），不指过去就会在
            # `_selector_for` 里构造出一个**空模型**的上游 Proposer 而当场炸掉。
            selector_prop=prop,
            runs_root=runs_root,
            library_root=library_root,
            split=getattr(args, "split", "all"),
            modes=modes,
            seed=args.seed,
            tag="",
            domain_parallel=args.workers,
            only_domains=_csv(args.only_domains),
            max_tasks=args.max_tasks,
            pool_policy="finals",
        )
    finally:
        relay.close()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec = runs_root / "_sweeps" / f"{summary_ns}-{stamp}.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    done = sum(int(d.get("done", 0)) for d in rep.get("domains", []))
    failed = sum(int(d.get("failed", 0)) for d in rep.get("domains", []))
    dead = [d["domain"] for d in rep.get("domains", []) if d.get("error")]
    print(f"\nsweep {summary_ns}: {done} 个任务完成，{failed} 个失败")
    if dead:
        print(f"  死掉的产线层：{', '.join(dead)}")
    print(f"record: {rec}")

    # 阶段回退必须**说出口**：proposer 那一段失败时，引擎会退回基准树继续跑，
    # 于是这一轮「看起来跑完了」，而最终被采纳的其实是**没改过的基准**。
    # 2026-10-20 实测：合成阶段撞上一次 401（OAuth token 轮换窗口），
    # 报告照样给出一个分数——那个分数量的其实是基准树。
    fell_back = _report_stage_fallbacks(runs_root, summary_ns)
    print(f"next:   python3 {Path(__file__).name} --phase judge --root {args.root}")
    if dead or failed:
        return 1
    if fell_back:
        print(
            "\n注意：有阶段回退到基准树（上面的 error 是原因）。"
            "这些任务量到的是**基准 harness** 的表现，不是演化后的——"
            "先修掉阶段错误再读分数。"
        )
        return 1
    return 0


def _report_stage_fallbacks(runs_root: Path, summary_ns: str) -> list[str]:
    """把「阶段回退」挑出来说清楚。返回回退了的阶段标签。"""
    ns_dir = Path(runs_root) / "adapt" / summary_ns
    if not ns_dir.is_dir():
        return []
    out: list[str] = []
    for summary_path in sorted(ns_dir.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for mode, blob in (summary.get("modes") or {}).items():
            for stage in blob.get("stages", []):
                if not stage.get("fell_back"):
                    continue
                label = stage.get("label", "?")
                err = (stage.get("error") or "").strip()
                out.append(label)
                print(f"  ! 阶段回退 [{mode}] {label}：{err[:200] or '(没有原因)'}")
        # **采纳树是不是基准树**：引擎把它写在 `summary["selections"][mode]` 里
        # （`core/schedule.py` 的 `res.selections[mode] = d`），
        # **不是** `summary["modes"][mode]["selection"]`——读错地方的话，
        # 「这一轮其实什么都没采纳」这条警告**永远不会触发**，
        # 于是「回退到基准」可以悄悄通过 judge（2026-10-20 verifier 实测）。
        for mode, sel in (summary.get("selections") or {}).items():
            if sel.get("chosen_tree_is_base"):
                print(
                    f"  ! [{mode}] 最终被采纳的是**基准树**（没有任何改动被采纳）"
                )
                out.append(f"{mode}:chosen_tree_is_base")
    return out


def _phase_judge(args) -> int:
    adapter = _adapter(args)
    modes = C.parse_modes(args.modes)
    sides = _stage_sides(adapter, args)
    judged = 0
    missing: list[tuple[str, str]] = []
    any_fell_back = False
    for ns, side in sides:
        ns_dir = adapter.spec.runs_root / "adapt" / ns
        if not ns_dir.is_dir():
            missing.append((side, ns))
            continue

        sels: list[dict] = []
        for summary_path in sorted(ns_dir.glob("*/summary.json")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"  ! 跳过读不动的 {summary_path}：{exc}")
                continue
            for mode in modes:
                sel = (summary.get("selections") or {}).get(mode)
                if sel:
                    sels.append(sel)
        if not sels:
            print(f"[{side}] 没有可判的选择记录（modes={modes}）：{ns_dir}", file=sys.stderr)
            continue

        rows = J.judge_selections(adapter, sels, parallel=4)
        out = adapter.spec.runs_root / "judge" / f"{ns}.json"
        J.write(rows, out)
        graded = sum(1 for r in rows if r.graded)
        print(
            f"[{side}] 判了 {len(rows)} 条，判成功 {graded} 条"
            "（判失败的**不算零分**，从分母里剔掉）"
        )
        print(f"record: {out}")
        judged += 1
        fell_back = _report_stage_fallbacks(adapter.spec.runs_root, ns)
        if fell_back:
            print(
                f"[{side}] 注意：有阶段回退到基准树。上面的分数量的是**基准 harness** 的表现，"
                "不是演化后的——先修掉阶段错误再读分数。"
            )
            any_fell_back = True
    for side, ns in missing:
        print(
            f"[{side}] 没有这个命名空间的产物：{adapter.spec.runs_root / 'adapt' / ns}；"
            f"先跑 sweep（judge 与 sweep 要带同一个 --split）",
            file=sys.stderr,
        )
    # **`--split both` 缺一侧就不是完整的泛化读数**：只判到 train 侧时，
    # 没有任何证据表明它在没见过的题上不变差——这和 generalization.py 的
    # `no_eval` 判决同一条纪律：缺测量不许当测量过了。
    if missing or not judged or any_fell_back:
        return 1
    return 0


def _phase_report(args) -> int:
    adapter = _adapter(args)
    modes = C.parse_modes(args.modes)
    sides = _stage_sides(adapter, args)
    rendered = 0
    for ns, side in sides:
        jpath = adapter.spec.runs_root / "judge" / f"{ns}.json"
        if not jpath.is_file():
            print(f"[{side}] 没有判据结果：{jpath}；先跑 judge（--split {getattr(args, 'split', 'all')}）", file=sys.stderr)
            continue
        rows = [J.Scored(**{k: v for k, v in r.items() if k not in ("frac", "graded")}) for r in
                json.loads(jpath.read_text(encoding="utf-8"))]
        summaries = R.summarise(rows)
        # **侧别写进标题**：train 侧与 eval 侧是两个分离的测量，报告不许长得像同一个。
        title = "usine × dsh · harness 演化" + (f"（{side} 侧）" if side != "all" else "")
        text = R.render(summaries, title=title, bench=adapter.spec.name)
        print(text)
        out = adapter.spec.runs_root / "report" / f"{ns}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"record: {out}")
        rendered += 1
    return 0 if rendered == len(sides) else 1


def _phase_repeat(args) -> int:
    """重复跑一棵树 N 次，量出**同树零分布**。

    这是「演化有没有用」这个问题缺的那把尺子：引擎在 k≥2 时会给基准树跑
    `base1..basek`，但**演化出来的那棵树只有一次 rollout**（`agg1`）——两臂用的
    不是同一把刻度尺，臂间差异里混着重复抽样差异。

    `--tree` 两种来源：
    - `base` —— 基准 harness（`garage-ii/harness_base/`）；
    - 别的路径 —— 一棵具体的树；如果是**目录**，按子目录名当任务名取树
      （`extract_adopted_trees` 就是按这个形状抽出来的）。
    """
    import arms as ARMS

    adapter = _adapter(args)
    tasks = list(adapter.tasks("all"))
    if args.only_tasks:
        wanted = set(_csv(args.only_tasks))
        tasks = [t for t in tasks if t in wanted]
    if not tasks:
        print("没有任务可跑", file=sys.stderr)
        return 1

    tree_arg = args.tree.strip()
    if tree_arg == "base":
        base_dir = adapter.base_harness()

        def tree_for_task(_t: str) -> Path | None:
            return base_dir

        label = f"base:{base_dir}"
    else:
        root = Path(tree_arg).expanduser()
        if not root.is_dir():
            print(f"树目录不存在：{root}", file=sys.stderr)
            return 1

        def tree_for_task(t: str) -> Path | None:
            cand = root / t
            if cand.is_dir():
                return cand
            # 目录里只有一棵树时，就把它当所有任务通用的树。
            trees = sorted(p for p in root.iterdir() if p.is_dir())
            return trees[0] if len(trees) == 1 else None

        label = str(root)

    tag = args.tag.strip() or ("base" if tree_arg == "base" else root.name)
    out_dir = adapter.spec.runs_root / "arms" / tag
    print(f"# 臂 {tag}：树 {label}")
    print(f"# 任务 {len(tasks)} 个，每题 {args.repeats} 次 rollout → 落盘 {out_dir}")
    print(f"# 命名空间 {tag}-r1..r{args.repeats}；判据在跑完后立刻判（不重跑模型）")

    # 臂的碰撞单位是**臂名**（`arms/<tag>/` + `<root>/<task>/repeat-<tag>-*`）：
    # 同 tag 的两个 repeat 互斥，不同 tag 各写各的。
    lock = _acquire_run_root_lock(adapter.spec.runs_root, tag)
    try:
        with adapter:
            ARMS.run_arm(
                adapter,
                tree_for_task,
                tasks,
                args.repeats,
                tag=tag,
                out_dir=out_dir,
                timeout=args.timeout,
                append=args.append,
                workers=args.arm_workers,
            )
    finally:
        _release_run_root_lock(lock)
    print(f"record: {out_dir}")
    return 0


def _phase_compare(args) -> int:
    """把两个臂并排读：零分布 vs 演化臂。"""
    import arms as ARMS

    adapter = _adapter(args)
    loaded = ARMS.load_arms(adapter.spec.runs_root / "arms")
    if not loaded:
        print(f"没有臂的落盘产物：{adapter.spec.runs_root / 'arms'}；先跑 repeat", file=sys.stderr)
        return 1
    tags = list(loaded.keys())
    if len(tags) < 2:
        print(f"至少要两个臂才能比：现在只有 {tags}", file=sys.stderr)
        return 1
    base_tag = args.base_arm.strip() or tags[0]
    evo_tag = args.evolved_arm.strip() or next((t for t in tags if t != base_tag), tags[0])
    if base_tag not in loaded or evo_tag not in loaded:
        print(f"臂不存在：{base_tag} / {evo_tag}；现在有 {tags}", file=sys.stderr)
        return 1

    rows = []
    base_tasks = set(loaded[base_tag])
    evo_tasks = set(loaded[evo_tag])
    # **缺格必须说出口**：两臂的任务集不一样时，只比**交集**会悄悄少掉一格，
    # 而那一格可能正是「演化翻了车」的那一格。2026-10-20 verifier 实测：
    # 少一格照样判「全部显著」并退出 0——**假绿灯**。
    missing = (base_tasks - evo_tasks) | (evo_tasks - base_tasks)
    if missing:
        print(
            f"⚠️ 两臂的格不一致：{sorted(missing)}"
            f"（只有 base 有：{sorted(base_tasks - evo_tasks)}；"
            f"只有 evolved 有：{sorted(evo_tasks - base_tasks)}）——"
            "**缺的那一格不参与比较，但不能当它没事**。"
        )
    for task_id in sorted(base_tasks & evo_tasks):
        rows.append(ARMS.compare_arms(loaded[base_tag][task_id], loaded[evo_tag][task_id]))

    print(f"零分布 = {base_tag}　演化臂 = {evo_tag}")
    print()
    print(ARMS.format_comparison(rows))
    print()
    print(ARMS.format_failure_rate(rows))
    print()
    print(ARMS.format_required_n(rows))
    out = adapter.spec.runs_root / "arms" / f"compare-{base_tag}-vs-{evo_tag}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nrecord: {out}")

    # 判定纪律：只要有**一格**判不出来，整体就不能说「演化有效」。
    #
    # **但「演化没动这一格」的零格除外**：演化在那一格什么都没做（可编辑面内容
    # 逐字相同），两臂必然同分布——那格**不承载**「演化有没有用」的信息。
    # 把它算进「判不出提升」是冤枉演化。
    null_cells = [r for r in rows if r.get("same_surface")]
    # **没有有效样本的格单列**：它不是零格（演化动了、只是判据没跑成），
    # 也不是「有演化」——它不承载任何方向的证据。混进 informative 会把
    # 「没测到」说成「测了但分不开」，那是不该下的结论。
    nodata_cells = [r for r in rows if r.get("no_data") and not r.get("same_surface")]
    informative = [
        r for r in rows if not r.get("same_surface") and not r.get("no_data")
    ]
    if null_cells:
        print(
            "\n零格（演化没动这一格，可编辑面内容逐字相同，**不参与判决**）："
            + "、".join(r["task_id"] for r in null_cells)
        )
    if nodata_cells:
        print(
            "\n没有有效样本（判据没跑成，score=None）："
            + "、".join(r["task_id"] for r in nodata_cells)
            + "——这些格**比不了**，不构成任何方向的证据。"
        )
    if not informative and not nodata_cells:
        print("\n注意：**每一格演化都没动**——没有可判的演化效果。")
        return 1
    if not informative:
        print("\n注意：**没有一格拿到可比的样本**——这次比较什么都没测到。")
        return 1
    undecided = [r for r in informative if not (r["significant"] and r["delta_mean"] > 0)]
    if undecided:
        print(
            f"\n注意：{len(undecided)}/{len(informative)} 格**有演化但分不开**"
            "（不显著或方向不对）——**不能**据此说演化带来了提升："
            + "、".join(r["task_id"] for r in undecided)
        )
        return 1
    if missing:
        print(
            f"\n注意：另有 {len(missing)} 格**两臂不一致**（上面列了）——"
            "判决只覆盖了**两臂都有**的那些格，缺的那几格**没有**被判过。"
        )
        return 1
    print(
        f"\n判决：{len(informative)} 格**有演化**的格全部显著且方向为正"
        f"（零格 {len(null_cells)} 格不参与）。"
    )
    return 0


def _phase_reselect(args) -> int:
    """重跑**选择**这一步——**不重跑任何 rollout**。

    为什么需要：选择通道修好之后（`minimax_proposer._contract_of`——选择任务有自己的
    输出契约，不能再用「改文件」的协议盖上去），已有的跑批产物**仍然有效**，
    只需要把「选哪棵」重做一遍。

    2026-10-20 实测：这个 bug 让 k=3 的**盲选从来没真跑过**——`selection.json` 里
    `fallback: true`、`error: 证据目录里没有 harness/，无法回报「不改动」`。
    引擎于是回退到「第一个 final」，而那不是盲选的结果。
    """
    from dsh_provider import Relay
    from harness2.core import selection as HSEL
    from minimax_proposer import MinimaxProposer

    adapter = _adapter(args)
    sides = _stage_sides(adapter, args)
    if len(sides) > 1:
        print(
            "reselect 不支持 --split both：两段的选择各有各的候选池，"
            "请对每段分别跑 --split train / --split test",
            file=sys.stderr,
        )
        return 1
    ns, _side = sides[0]
    ns_dir = adapter.spec.runs_root / "adapt" / ns
    if not ns_dir.is_dir():
        print(
            f"没有这个命名空间的产物：{ns_dir}；先跑 sweep"
            f"（reselect 与 sweep 要带同一个 --split）",
            file=sys.stderr,
        )
        return 1
    tasks = [t for t in adapter.tasks("all") if (ns_dir / t).is_dir()]
    if args.only_tasks:
        wanted = set(_csv(args.only_tasks))
        tasks = [t for t in tasks if t in wanted]
    if not tasks:
        print("没有可重选的任务", file=sys.stderr)
        return 1

    # 锁跟 sweep 锁**同一个命名空间**——否则两个进程能在同一个命名空间里
    # 各写各的，静默覆盖。key 用命名空间名：同 ns 互斥，不同 ns 各跑各的。
    lock = _acquire_run_root_lock(adapter.spec.runs_root / "adapt", ns)
    relay = _make_relay(_llm_choice(args))
    relay.start()
    try:
        adapter._relay = relay
        adapter._relay_started = True
        prop = MinimaxProposer(
            relay=relay,
            model=_llm_choice(args)['model'],
            timeout=args.proposer_timeout,
            api=_llm_choice(args).get('api', 'anthropic-messages'),
        )
        prop.audit_dir = adapter.spec.runs_root / "adapt" / "_audit" / ns
        bad = 0
        for task_id in tasks:
            work_dir = ns_dir / task_id
            labels = [f"base{i}" for i in range(1, args.k + 1)] + [
                f"agg{i}" for i in range(1, args.k + 1)
            ]
            rollouts = {}
            for lbl in labels:
                rv = adapter.run_view(task_id, f"{ns}/{task_id}/{lbl}")
                if rv.ok:
                    rollouts[lbl] = rv
            candidates = HSEL.selection_pool("agg", args.k, rollouts, [])
            if not candidates:
                print(f"  [{task_id}] 没有可选的 final")
                bad += 1
                continue
            # 旧的（回退的）选择记录留一份——它是「这个 bug 存在过」的证据。
            # **备份必须放在 `selection/agg3/` 外面**：`run_selection` 会
            # `shutil.rmtree(selection/agg3)`，放在里面会被一起删掉。
            old = work_dir / "selection" / f"agg{args.k}" / "selection.json"
            if old.is_file():
                keep = work_dir / "selection" / f"agg{args.k}.before-reselect"
                keep.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, keep / "selection.json")
            sel = HSEL.run_selection(
                task_id,
                args.k,
                "agg",
                candidates,
                adapter=adapter,
                prop=prop,
                work_dir=work_dir,
                pool_kind="finals",
            )
            print(
                f"  [{task_id}] 选中 {sel.chosen_label}（id={sel.chosen_id}）"
                f" ok={sel.ok} fallback={sel.fallback} 候选 {sorted(candidates)}"
            )
            if sel.error:
                print(f"      错误：{sel.error[:200]}")
                bad += 1
            # **必须同步 summary.json**：引擎写的是 `res.selections[mode]`，
            # 而 `judge` 读的是 `summary["selections"][mode]`。不更新的话，
            # judge 还在判**重选之前**那条（回退的）记录——2026-10-20 实测。
            _merge_selection_into_summary(work_dir, sel)
            if sel.why:
                print(f"      理由：{sel.why[:200]}")
        if bad:
            print(f"\n有 {bad} 个任务的选择没成功", file=sys.stderr)
            return 1
    finally:
        _release_run_root_lock(lock)
        relay.close()
    return 0


def _merge_selection_into_summary(work_dir: Path, sel) -> None:
    """把重选出来的选择写回 `summary.json` 的 `selections[mode]`。

    引擎的 `core/schedule.py` 是这么记的（`res.selections[mode] = d`），
    本层照它做——否则 `judge` 与 `arms extract` 读到的会是两条不同的选择。
    """
    summary_path = Path(work_dir) / "summary.json"
    if not summary_path.is_file():
        print(f"      （没有 summary.json，跳过同步：{summary_path}）")
        return
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"      （summary.json 读不动，跳过同步：{exc}）")
        return
    d = sel.to_dict()
    sels = summary.setdefault("selections", {})
    sels[sel.mode] = d
    tmp = summary_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, summary_path)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.phase == "preflight":
            errs, warns = run_all(args.root)
            for w in warns:
                print(f"warn: {w}")
            if errs:
                print("preflight 未通过（这一轮不许开跑）：")
                for e in errs:
                    print(f"  - {e}")
                return 1
            print(f"preflight 全绿：{args.root}")
            return 0
        if args.phase == "sweep":
            return _phase_sweep(args)
        if args.phase == "repeat":
            return _phase_repeat(args)
        if args.phase == "compare":
            return _phase_compare(args)
        if args.phase == "reselect":
            return _phase_reselect(args)
        if args.phase == "judge":
            return _phase_judge(args)
        return _phase_report(args)
    except (H2CONFIG.ConfigError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
