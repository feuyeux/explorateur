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

from dsh_provider import MINIMAX_MODEL  # noqa: E402
from preflight import run_all  # noqa: E402
from usine_adapter import UsineAdapter  # noqa: E402

SWEEP_ACK = "RUN-USINE-H2-SWEEP"

DEFAULT_ROOT = Path(os.environ.get("GARAGE_II_RUNS_DIR", Path.home() / ".cache" / "usine-h2"))


def _csv(raw: str) -> tuple[str, ...]:
    """逗号列表 → 元组。harness2 的 `_csv` 是 cli/run_sweep.py 的模块私有函数，
    这里自己写一份，不去戳上游的私有面。"""
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _acquire_run_root_lock(root: Path):
    """给 run root 加一把锁：同一个 root 上不许同时跑两个 sweep。

    为什么需要：两个 sweep 共用一个 run root 时，**产物会互相覆盖**——
    第二个 sweep 的 `base1` 会盖掉第一个的 `base1`，轨迹、事件流、分数全对不上，
    而且**不报错**：读数看起来正常，数字是错的。

    2026-10-20 实测踩过：一次 `task_stop` 只杀了外层 shell，`python3` 子进程还活着，
    第二个 sweep 在同一个 root 上开跑，两边同时写 `adapt/<ns>/<task>/<label>/`。
    症状是「提案阶段 Connection refused」（一个 sweep 的中继被另一个的清理动作杀了）
    加「rollout 目录一会儿有文件一会儿空」。**这属于不报错的静默错误**，所以要有锁。

    锁是 run root 里的一个文件（`~/<root>/.sweep.lock`），内含 pid。
    进程已经不在了（stale lock）就自动接管。
    """
    import os

    lock_dir = Path(root)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = lock_dir / ".sweep.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        alive = False
        if pid > 0:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if alive:
            raise RuntimeError(
                f"run root {root} 上已经有一个 sweep 在跑（pid {pid}）。"
                f"两个 sweep 共用一个 run root 会互相覆盖产物，**而且不报错**。"
                f"先停掉那个，或换一个 --root。"
            )
        lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def _release_run_root_lock(lock: Path) -> None:
    try:
        lock.unlink(missing_ok=True)
    except OSError:
        pass


def _adapter(args) -> UsineAdapter:
    only = [t.strip() for t in args.only_tasks.split(",") if t.strip()] if args.only_tasks else None
    return UsineAdapter(
        runs_root=args.root, timeout=args.timeout, model=args.model, only_tasks=only
    )


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run_usine_h2", description=__doc__)
    ap.add_argument(
        "--phase",
        choices=("preflight", "sweep", "judge", "report"),
        default="preflight",
        help="preflight=自检（默认，不花钱）｜sweep=演化（花钱，要 ack）｜judge=机械判据｜report=汇总",
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
    ap.add_argument("--only-domains", default="", help="只跑这些产线层（逗号分隔）")
    ap.add_argument("--max-tasks", type=int, default=None, help="每层最多几个任务")
    ap.add_argument("--workers", type=int, default=1, help="并行跑几个产线层")
    ap.add_argument("--timeout", type=int, default=900, help="单次 rollout 的墙钟上限（秒）")
    ap.add_argument(
        "--model",
        default=MINIMAX_MODEL,
        help=f"solver 与 proposer 用的模型（{MINIMAX_MODEL}）",
    )
    ap.add_argument(
        "--proposer-timeout", type=int, default=600, help="单次改 harness 会话的墙钟上限（秒）"
    )
    ap.add_argument(
        "--only-tasks",
        default="",
        help="只跑这些任务（逗号分隔）；默认全跑 6 个",
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印任务流与命名空间，不开跑")
    return ap


def _print_stream(adapter, args, modes) -> int:
    by_domain = SCHED.task_stream(
        adapter,
        split="all",
        seed=args.seed,
        only_domains=_csv(args.only_domains),
        max_tasks=args.max_tasks,
    )
    ns = SCHED.ns(adapter.spec.name, adapter.substrate.name, "agg", args.k, seed=args.seed)
    print(f"# {adapter.spec.name}-{adapter.substrate.name} k={args.k} modes={','.join(modes)}")
    print(f"#   namespace: {ns}")
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
    from dsh_provider import ProviderError, Relay

    try:
        probe = Relay()
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

    lock = _acquire_run_root_lock(runs_root)
    try:
        return _run_sweep(args, adapter, modes, runs_root, library_root, summary_ns)
    finally:
        _release_run_root_lock(lock)


def _run_sweep(args, adapter, modes, runs_root, library_root, summary_ns) -> int:
    # proposer 通道：本层自带的直连通道（上游的 opencode 通道要 vendor 半个第三方仓，
    # claude_cli 通道强制走 Vertex 而本机没有 ADC）。它与 solver 共用同一个本机中继，
    # 所以 token 只在中继的内存里。
    from dsh_provider import Relay
    from minimax_proposer import MinimaxProposer

    relay = Relay()
    relay.start()
    try:
        adapter._relay = relay
        adapter._relay_started = True
        prop = MinimaxProposer(relay=relay, model=args.model, timeout=args.proposer_timeout)
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
            split="all",
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
            sel = blob.get("selection") or {}
            if sel.get("chosen_tree_is_base"):
                print(
                    f"  ! [{mode}] 最终被采纳的是**基准树**（没有任何改动被采纳）"
                )
    return out


def _phase_judge(args) -> int:
    adapter = _adapter(args)
    modes = C.parse_modes(args.modes)
    ns = SCHED.ns(adapter.spec.name, adapter.substrate.name, "agg", args.k, seed=args.seed)
    ns_dir = adapter.spec.runs_root / "adapt" / ns
    if not ns_dir.is_dir():
        print(f"没有这个命名空间的产物：{ns_dir}；先跑 sweep", file=sys.stderr)
        return 1

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
        print(f"没有可判的选择记录（modes={modes}）：{ns_dir}", file=sys.stderr)
        return 1

    rows = J.judge_selections(adapter, sels, parallel=4)
    out = adapter.spec.runs_root / "judge" / f"{ns}.json"
    J.write(rows, out)
    graded = sum(1 for r in rows if r.graded)
    print(f"判了 {len(rows)} 条，判成功 {graded} 条（判失败的**不算零分**，从分母里剔掉）")
    print(f"record: {out}")
    fell_back = _report_stage_fallbacks(adapter.spec.runs_root, ns)
    if fell_back:
        print(
            "\n注意：有阶段回退到基准树。上面的分数量的是**基准 harness** 的表现，"
            "不是演化后的——先修掉阶段错误再读分数。"
        )
        return 1
    return 0


def _phase_report(args) -> int:
    adapter = _adapter(args)
    modes = C.parse_modes(args.modes)
    ns = SCHED.ns(adapter.spec.name, adapter.substrate.name, "agg", args.k, seed=args.seed)
    jpath = adapter.spec.runs_root / "judge" / f"{ns}.json"
    if not jpath.is_file():
        print(f"没有判据结果：{jpath}；先跑 judge", file=sys.stderr)
        return 1
    rows = [J.Scored(**{k: v for k, v in r.items() if k not in ("frac", "graded")}) for r in
            json.loads(jpath.read_text(encoding="utf-8"))]
    summaries = R.summarise(rows)
    text = R.render(summaries, title="usine × dsh · harness 演化", bench=adapter.spec.name)
    print(text)
    out = adapter.spec.runs_root / "report" / f"{ns}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"record: {out}")
    return 0


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
        if args.phase == "judge":
            return _phase_judge(args)
        return _phase_report(args)
    except (H2CONFIG.ConfigError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
