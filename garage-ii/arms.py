#!/usr/bin/env python3
"""arms.py —— 同一棵树的重复 rollout：同树零分布与配对比较。

**为什么需要这个文件。** harness2 的引擎在 k≥2 时会跑 `base1..basek`（同一棵基准树的
k 次 rollout），所以「同树零分布」是引擎自带的。但演化出来的那棵树**只有一次**
rollout（`agg1`），没有自己的分布——于是「演化臂」和「基准臂」用的是两把不同刻度的
尺子，**臂间差异里混着重复抽样差异**。

2026-10-20 实测（同一棵基准树、同一道题、同一模型）：

| 臂 | 树 | 分数 |
|---|---|---|
| `base1` | 基准 | 80% |
| `inv1` | 基准（逐字相同） | 100% |
| `dom1` | 基准（逐字相同） | 100% |
| `agg1` | 基准（逐字相同） | 100% |

**33 分的差距，零 harness 改动。** 任何「演化带来 25 分提升」的说法，在没有同树零
分布的前提下都是不可判的。

**本文件提供的三样东西：**

1. **臂（arm）** = 一棵树 × 一个任务 × n 次 rollout，每次单独判分。执行器是可注入的
   接缝（`execute` 参数），所以离线自检可以用假执行器跑完整条链，不花钱。
2. **零分布** = 基准树的 n 次 rollout 的分数分布。
3. **配对比较** = 演化树 vs 零分布：均值位移、每条判据的失分率对比、以及一个
   **精确置换检验**（不依赖 numpy，小样本下最诚实的一个检验）。

**读数纪律**（本文件自己的结论，不是猜的）：

- **判定只看一件事**：精确置换检验的 p 值（≤ 0.1）**且** Δ > 0。零分布宽度、离散度、
  分离度**只报不判**——置换检验已经把臂内方差算进去了，再叠一道门槛会误杀真信号；
- 最小可达 p 值 = 1/C(n+m, n)：**两臂各 3 次**时是 1/20 = 0.05，所以 n=3 只能判
  「完全分离」这一种；**两臂各 2 次**时是 1/6 = 0.167，**p ≤ 0.1 根本达不到**。
  这就是「n 至少要 3」的来历；
- 每条判据的**失分率**比总分更有信息量：分数是若干条判据的平均，掩盖了「哪一条
  的行为真的变了」；
- **可编辑面内容逐字相同**（`same_surface`）的那一格是**构造上的零**：演化什么都没做，
  两臂必然同分布——它不承载「演化有没有用」的信息，不参与判决。
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

#: 引擎先上路径，再上本层——顺序不能反（harness2 的包要从 theatre-ii 根导入）。
#: 这个模块被 `run_usine_h2.py` 导入时路径已经就位；被**当脚本**直接跑
#: （`python3 garage-ii/arms.py …`）时得自己补上。
_HERE = Path(__file__).resolve().parent
_THEATRE_II = _HERE.parent / "theatre-ii"
for _p in (str(_THEATRE_II), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: 一次 rollout 的执行器签名：`(task_id, tree_dir, run_id) -> run_dir`。
#:
#: 注入点：离线自检（`smoke_dsh_bridge.py`）传一个假执行器，真跑传
#: `UsineAdapter.execute`。
Executor = Callable[[str, Path, str], Path]


# ── 树指纹 ────────────────────────────────────────────────────────────────────


def tree_fingerprint(tree_dir: Path) -> str:
    """这棵 harness 树的内容指纹。

    用来证明「这几臂用的是同一棵树」——**这是整个测量成立的前提**。没��指纹，
    臂间比较就退化成「我不知道它们是不是同一棵树」。
    """
    from harness2.core import runmark

    return runmark.fingerprint(Path(tree_dir))


def _criteria_stamp(adapter, task_id: str) -> str:
    """这一格用的判据的版本戳。

    判据一改，同一格的分就不能和旧的混着看。戳一样才说明是同一把尺子。
    """
    fn = getattr(adapter, "criteria_stamp", None)
    if callable(fn):
        try:
            return str(fn(task_id))
        except Exception:
            return ""
    return ""


def _surface_signature(adapter, tree_dir: Path) -> str:
    """**可编辑面**的内容签名——只算面内的文件。

    为什么另算一个：`runmark.fingerprint` 哈希的是目录里的**全部**文件，而引擎
    写回的树比基准树多两个 README 桩，于是「内容逐字相同」的两棵树指纹也不同。
    判断「演化到底动没动这一格」要比的是**面内内容**。

    adapter 不认识面（比如离线自检用的假 adapter）时退回目录指纹。
    """
    fn = getattr(adapter, "tree_signature", None)
    if callable(fn):
        try:
            return str(fn(tree_dir))
        except Exception:
            return tree_fingerprint(tree_dir)
    return tree_fingerprint(tree_dir)


# ── 臂 ────────────────────────────────────────────────────────────────────────


@dataclass
class Roll:
    """一次 rollout 的结果。"""

    run_id: str
    score: float | None
    n_passed: int = 0
    n_criteria: int = 0
    checks: list[dict] = field(default_factory=list)
    final_text: str = ""
    error: str = ""
    #: **这条 rollout 作废了**（证据自相矛盾，不是判据跑不成）。
    #:
    #: 两者的区别是硬的：
    #: - `error` 非空、`void_reason` 为空 → **工具故障**（判据跑不成、run 目录
    #:   找不到）——重判时必须报错退出，不能拿空臂覆盖原来那份；
    #: - `void_reason` 非空 → **这条 rollout 的证据失真**（例如 run 目录在
    #:   rollout 结束之后被重建，产物被后来的进程擦掉了）——它**不算零分**，
    #:   也不该算进分布，得从 n 里剔出去。
    void_reason: str = ""

    @property
    def graded(self) -> bool:
        """判据本身跑成了吗（`score=None` = 判据失败，不是零分）。"""
        return self.score is not None


@dataclass
class Arm:
    """一棵树在一个任务上的 n 次 rollout。"""

    tag: str
    task_id: str
    tree_fingerprint: str
    tree_label: str
    rolls: list[Roll] = field(default_factory=list)
    #: **可编辑面**的内容签名（只算面内文件，不算 README 桩）。
    #: 用来判断「演化到底动没动这一格」——面内内容逐字相同 = 演化没动，
    #: 那一格是**构造上的零**，不承载「演化有没有用」的信息。
    tree_signature: str = ""
    #: **判据版本戳**：这一格用的是哪一套判据。改了判据之后再 `--append`，
    #: 两套判据的分数会被拼成**一条**分布——那不是「多跑几次」，是「换个尺子量
    #: 半截旧数据、半截新数据」。戳不一样就该拒绝追加。
    criteria: str = ""
    #: **重判时去掉的重复 rollout**（同一条 run_id 落了两次）。留痕用：
    #: 去重**不许悄悄做**——n 从多少变成多少，得看得见。
    dropped_duplicates: list[str] = field(default_factory=list)

    # ── 分布 ──

    @property
    def scores(self) -> list[float]:
        """只取判成功的分数（判据失败的不能当成 0 分混进来）。"""
        return [r.score for r in self.rolls if r.graded and r.score is not None]

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def mean(self) -> float:
        s = self.scores
        return sum(s) / len(s) if s else 0.0

    @property
    def spread(self) -> float:
        """零分布自身的宽度（max - min）。效应必须大于它。"""
        s = self.scores
        return (max(s) - min(s)) if s else 0.0

    @property
    def stdev(self) -> float:
        s = self.scores
        if len(s) < 2:
            return 0.0
        m = sum(s) / len(s)
        return math.sqrt(sum((x - m) ** 2 for x in s) / (len(s) - 1))

    def failure_rate(self) -> dict[str, float]:
        """每条判据的失分率（判成功的 rollout 里，没过的比例）。

        **比总分有信息量**：分数是若干条判据的平均，掩盖了「哪一条的行为真的变了」。
        """
        graded = [r for r in self.rolls if r.graded]
        if not graded:
            return {}
        names: list[str] = []
        for r in graded:
            for c in r.checks:
                if c["name"] not in names:
                    names.append(c["name"])
        out: dict[str, float] = {}
        for name in names:
            relevant = [r for r in graded if any(c["name"] == name for c in r.checks)]
            if not relevant:
                continue
            bad = sum(
                1
                for r in relevant
                for c in r.checks
                if c["name"] == name and not c["passed"]
            )
            out[name] = bad / len(relevant)
        return out

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "task_id": self.task_id,
            "tree_fingerprint": self.tree_fingerprint,
            "tree_label": self.tree_label,
            # **零格规则靠它**：不落盘的话，CLI 路径（compare / report 读的就是
            # 落盘的臂）永远判不出「演化没动这一格」——2026-10-20 verifier 实测。
            "tree_signature": self.tree_signature,
            "criteria": self.criteria,
            "n": self.n,
            "scores": self.scores,
            # 去重留痕：n 从多少变成多少，得看得见。
            "dropped_duplicates": list(self.dropped_duplicates),
            "mean": round(self.mean, 4),
            "spread": round(self.spread, 4),
            "stdev": round(self.stdev, 4),
            "failure_rate": {k: round(v, 4) for k, v in self.failure_rate().items()},
            "rolls": [
                {
                    "run_id": r.run_id,
                    "score": r.score,
                    "n_passed": r.n_passed,
                    "n_criteria": r.n_criteria,
                    "checks": r.checks,
                    "final_text": r.final_text,
                    "error": r.error,
                    "void_reason": r.void_reason,
                }
                for r in self.rolls
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Arm":
        return cls(
            tag=d["tag"],
            task_id=d["task_id"],
            tree_fingerprint=d.get("tree_fingerprint", ""),
            tree_label=d.get("tree_label", ""),
            tree_signature=d.get("tree_signature", ""),
            criteria=d.get("criteria", ""),
            dropped_duplicates=list(d.get("dropped_duplicates", [])),
            rolls=[
                Roll(
                    run_id=r.get("run_id", ""),
                    score=r.get("score"),
                    n_passed=r.get("n_passed", 0),
                    n_criteria=r.get("n_criteria", 0),
                    checks=r.get("checks", []),
                    final_text=r.get("final_text", ""),
                    error=r.get("error", ""),
                    void_reason=r.get("void_reason", ""),
                )
                for r in d.get("rolls", [])
            ],
        )


# ── 跑一个臂 ──────────────────────────────────────────────────────────────────


def _integrity_reason(adapter, run_dir: Path) -> str:
    """这条 rollout 的证据自不自洽（不自洽 → 作废，不是零分）。"""
    checker = getattr(adapter, "rollout_integrity", None)
    if not callable(checker):
        return ""
    try:
        return checker(Path(run_dir)) or ""
    except Exception:  # noqa: BLE001 - 自检失败不能把读数判死
        return ""


def _void_roll(run_id: str, reason: str, prev_error: str = "") -> Roll:
    note = f"{reason}｜原记录：{prev_error}" if prev_error else reason
    return Roll(run_id=run_id, score=None, error=note, void_reason=reason)


def run_arm(
    adapter,
    tree_for_task: Callable[[str], Path | None],
    tasks: Sequence[str],
    n: int,
    *,
    tag: str,
    out_dir: Path,
    timeout: int | None = None,
    execute: Executor | None = None,
    append: bool = False,
    log=print,
    workers: int | None = None,
) -> list[Arm]:
    """跑一个臂：每棵任务树各 n 次 rollout，各自判分，落盘。

    `execute` 是可注入的执行器接缝——离线自检传假执行器，真跑传
    `adapter.execute`。**这条接缝是必须的**：否则「离线自检」会变成一次付费运行。

    `append=True` 时**接着已有臂往下加**（第 4、5、6…次），而不是覆盖：
    把 n=3 的零分布扩到 n=10 时，已跑的那 3 次不能重跑（浪费钱）也不能丢
    （它们是分布的一部分）。新 rollout 的编号从已有条数往后接，run id 不撞车。

    **n 次 rollout 默认并行跑**（`workers`，默认 `min(n, 4)`）。串行时一条臂的
    总耗时是 n 次 rollout 的**和**——实测单次 rollout 12–42 分钟，n=4 串行就是
    50 分钟到 3 小时。瓶颈在模型往返，不在机器（`usine_adapter` 的
    `_rollout_guard` 早就写明「别的格子各自独占工作区，并发跑是安全的」），
    所以一条臂的时间成本应该是**一次** rollout 的时长，不是 n 倍。
    落盘顺序仍按 run 序号（第 i 次就是 r{i}），与串行时一致。
    """
    ex = execute or (lambda t, tree, rid: adapter.execute(t, tree, rid, timeout=timeout))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    arms: list[Arm] = []

    for task_id in tasks:
        tree = tree_for_task(task_id)
        if tree is None:
            log(f"  [{task_id}] 没有树可用，跳过")
            continue
        tree = Path(tree)
        arm = Arm(
            tag=tag,
            task_id=task_id,
            tree_fingerprint=tree_fingerprint(tree),
            tree_label=str(tree),
            tree_signature=_surface_signature(adapter, tree),
            criteria=_criteria_stamp(adapter, task_id),
        )
        start = 1
        prefix: list[Roll] = []   # `--append` 时已跑过的那几条（最终记录要带上）
        saved = out_dir / f"{task_id}.json"
        if append and saved.is_file():
            try:
                old = Arm.from_dict(json.loads(saved.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                old = None
            if old is not None:
                arm.rolls = list(old.rolls)
                start = len(old.rolls) + 1
                # **追加的那几条必须留在最终记录里**：并行化时最终记录是
                # 「按 run 序号整份赋值」，不把前缀带上就会把已跑的那几条丢掉
                # （2026-10-20 实测：smoke 抓到「追加到 5 次」只剩 4 条）。
                prefix = list(old.rolls)
                if old.tree_fingerprint and old.tree_fingerprint != arm.tree_fingerprint:
                    log(
                        f"  [{task_id}] **树的指纹变了**（{old.tree_fingerprint[:12]} → "
                        f"{arm.tree_fingerprint[:12]}）——追加的是另一棵树，不能接在一起"
                    )
                    continue
                # **判据换了不能追加**：那是「用新尺子量旧数据」，
                # 拼出来的分布不是同一条。要换判据 → 先 `arms rescore` 重判整条臂。
                if old.criteria and arm.criteria and old.criteria != arm.criteria:
                    log(
                        f"  [{task_id}] **判据换了**（{old.criteria[:8]} → "
                        f"{arm.criteria[:8]}）——追加会把两套判据的分数拼成一条分布。"
                        "先跑 `arms.py rescore` 把整条臂重判一遍，再追加"
                    )
                    continue
        def one_roll(run_id: str) -> Roll:
            """跑一条 rollout 并判分，返回一条 Roll（**失败不是零分**）。"""
            try:
                try:
                    run_dir = ex(task_id, tree, run_id)
                except Exception as exc:  # noqa: BLE001
                    log(f"  [{task_id}] {run_id} 跑挂了：{type(exc).__name__}: {exc}")
                    return Roll(run_id=run_id, score=None, error=f"{type(exc).__name__}: {exc}")
                bad = _integrity_reason(adapter, Path(run_dir))
                if bad:
                    log(f"  [{task_id}] {run_id} **作废**（不是零分）：{bad}")
                    return _void_roll(run_id, bad)
                scored = adapter.score(Path(run_dir), task_id)
                if scored is None:
                    log(f"  [{task_id}] {run_id} 判据跑不成（不记零分）")
                    return Roll(run_id=run_id, score=None, error="判据跑不成（不是零分）")
                log(
                    f"  [{task_id}] {run_id} {scored['score']*100:.2f}%"
                    f" ({scored['n_passed']}/{scored['n_criteria']})"
                )
                return Roll(
                    run_id=run_id,
                    score=scored["score"],
                    n_passed=scored["n_passed"],
                    n_criteria=scored["n_criteria"],
                    checks=scored["checks"],
                    final_text=scored.get("final_text", ""),
                )
            except Exception as exc:  # noqa: BLE001
                return Roll(run_id=run_id, score=None, error=f"{type(exc).__name__}: {exc}")

        jobs = [(i, f"repeat-{tag}-{task_id}-r{i}") for i in range(start, start + n)]
        n_workers = max(1, min(int(workers if workers else len(jobs)), len(jobs)))
        results: dict[int, Roll] = {}

        def dump() -> None:
            """把**已跑完**的那几条按 run 序号落盘（并行时也必须增量落盘）。

            **写的是快照，不改 `arm.rolls`**：臂的最终记录由下面那次统一赋值
            写出。若这里也往 `arm.rolls` 里塞，最终就会**重复计数**
            （2026-10-20 实测：smoke 抓到「先跑出 3 次」变成 6 条）。
            """
            snapshot = Arm(
                tag=arm.tag,
                task_id=arm.task_id,
                tree_fingerprint=arm.tree_fingerprint,
                tree_label=arm.tree_label,
                tree_signature=arm.tree_signature,
                criteria=arm.criteria,
            )
            snapshot.rolls = prefix + [results[i] for i, _run_id in jobs if i in results]
            (out_dir / f"{task_id}.json").write_text(
                json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
            )

        if n_workers <= 1:
            for i, run_id in jobs:
                results[i] = one_roll(run_id)
                dump()
        else:
            log(f"  [{task_id}] {len(jobs)} 次 rollout 并行跑（{n_workers} 路）")
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = {pool.submit(one_roll, run_id): i for i, run_id in jobs}
                for fut in as_completed(futures):
                    results[futures[fut]] = fut.result()
                    # **每跑完一条就落盘一次**（并行时也必须）：一条臂是 n 次
                    # rollout，可能跑一两个小时；中途被杀就把已跑的证据全丢了，
                    # 等于白花钱。并行化最容易犯的错就是把落盘挪到「全部跑完」——
                    # 那时被杀就是**零证据**。落盘按 run 序号排序，与串行一致。
                    dump()
        arm.rolls = prefix + [
            results.get(i) or Roll(run_id=run_id, score=None, error="没跑起来")
            for i, run_id in jobs
        ]
        (out_dir / f"{task_id}.json").write_text(
            json.dumps(arm.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        arms.append(arm)
        (out_dir / f"{task_id}.json").write_text(
            json.dumps(arm.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return arms


# ── 配对比较 ──────────────────────────────────────────────────────────────────


def _exact_permutation_p(base: Sequence[float], evolved: Sequence[float]) -> float:
    """单侧精确置换检验：H0 = 两臂同分布，均值差来自抽样。

    做法：把两组数混起来，随机重分成同原大小两组，看有多少种分法的均值差
    ≥ 观测到的。**不依赖 numpy**（本仓不引额外依赖），小样本下最诚实。
    """
    a = list(base)
    b = list(evolved)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 1.0
    obs = sum(b) / m - sum(a) / n
    pool = a + b
    total = n + m
    # 枚举所有 n+m 选 n 的分法；n+m ≤ 12 时枚举量可接受，否则用随机抽样。
    hits = 0
    trials = 0
    if total <= 12:
        from itertools import combinations

        for idx in combinations(range(total), n):
            left = [pool[i] for i in idx]
            right = [pool[i] for i in range(total) if i not in set(idx)]
            diff = sum(right) / m - sum(left) / n
            trials += 1
            if diff >= obs - 1e-12:
                hits += 1
    else:
        rng = random.Random(20261020)
        for _ in range(20000):
            rng.shuffle(pool)
            left, right = pool[:n], pool[n:]
            diff = sum(right) / m - sum(left) / n
            trials += 1
            if diff >= obs - 1e-12:
                hits += 1
    return (hits / trials) if trials else 1.0


def _phi(x: float) -> float:
    """标准正态分布函数。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def required_n(
    base: Arm,
    target: str,
    *,
    n_max: int = 40,
    power_target: float = 0.8,
    alpha: float = 0.1,
) -> dict:
    """「要多大 n 才测得出来」——**如果演化恰好修好了 `target` 这条判据**。

    这是最后一个缺的东西：知道了零分布、知道了演化改了什么、也知道了当前 n 测不出
    结论之后，真正能用来做决策的数是「**再跑多少遍才够**」。

    模型（**正态近似，估算**）：每次 rollout 的分数 = C 条判据里过的条数 / C，每条
    判据独立地以该臂观测到的失分率失分。于是

    - 均值 = 1 − 平均失分率；
    - 方差 = Σ q(1−q) / C²（q 是每条判据的失分率）；
    - 演化臂的模型：把 `target` 这条的失分率置 0（假设它被修好了），其余照旧。

    功效用两样本单侧近似的正态公式：
    λ = Δ / sqrt((var_base + var_evo) / n)，power ≈ Φ(λ − z_α)。

    **这是估算，不是精确置换检验的功效**——精确检验在小样本上功效略低，
    所以这里给出的 n 是**乐观下界**，实跑时应该再乘 1.5 左右。
    """
    fr = base.failure_rate()
    if not fr or target not in fr:
        return {"ok": False, "reason": f"臂里没有判据 {target}"}
    c = len(fr)
    q = [fr[k] for k in sorted(fr)]
    q_evo = [0.0 if k == target else fr[k] for k in sorted(fr)]
    m_b = 1.0 - sum(q) / c
    m_e = 1.0 - sum(q_evo) / c
    var_b = sum(x * (1 - x) for x in q) / (c * c)
    var_e = sum(x * (1 - x) for x in q_evo) / (c * c)
    delta = m_e - m_b
    z_a = 1.2816 if alpha <= 0.1 else 1.6449  # 单侧 α=0.10 / 0.05
    need = None
    if delta <= 0:
        # 效应量为 0（或负）——**测不出来**，别报一个「n=2 就能测出来」的退化结论
        # （全通过臂的方差是 0，那个式子会算出 λ=∞、功效 100%）。
        return {
            "ok": True,
            "target": target,
            "n_criteria": c,
            "base_mean": round(m_b, 4),
            "evolved_mean_if_fixed": round(m_e, 4),
            "delta": round(delta, 4),
            "required_n": None,
            "power_target": power_target,
            "alpha": alpha,
            "note": "这条判据在基准臂上没失分过，没有可测的效应",
        }
    for n in range(2, n_max + 1):
        lam = delta / math.sqrt((var_b + var_e) / n) if (var_b + var_e) > 0 else float("inf")
        pw = _phi(lam - z_a) + _phi(-lam - z_a)
        if pw >= power_target:
            need = n
            break
    return {
        "ok": True,
        "target": target,
        "n_criteria": c,
        "base_mean": round(m_b, 4),
        "evolved_mean_if_fixed": round(m_e, 4),
        "delta": round(delta, 4),
        "required_n": need,
        "power_target": power_target,
        "alpha": alpha,
        "note": "正态近似估算（乐观下界）；精确置换检验的实际功效略低，实跑建议 ×1.5",
    }


def compare_arms(base: Arm, evolved: Arm) -> dict:
    """零分布 vs 演化臂：效应、检验、逐条判据的失分率对比。

    **判定只靠一件事：精确置换检验的 p 值。**

    早先的版本还叠了一条「Δ > 零分布宽度」的硬门槛，**那是错的**——置换检验
    本身已经把臂内方差算进去了（它在混池重分），再叠一次会误杀真信号：

    | 零分布 | 演化臂 | Δ | 置换 p | 结论 |
    |---|---|---|---|---|
    | 67, 67, 100 | 100, 100, 100 | +22 | 0.05 | **真信号**（完全分离），但 Δ(22) < 零分布宽度(33) → 旧规则会误判成「噪声」 |
    | 100, 100, 80 | 100, 100, 100 | +6.7 | 0.15 | 真噪声，p > 0.1 正确判掉 |

    所以：**p ≤ 0.1 且 Δ > 0** 就算有信号；零分布宽度、离散度、分离度**只报不判**
    （它们是让人看懂这个数怎么来的，不是额外的门槛）。
    """
    delta = evolved.mean - base.mean
    p = _exact_permutation_p(base.scores, evolved.scores)
    fr_base = base.failure_rate()
    fr_evo = evolved.failure_rate()
    per_check = {}
    for name in sorted(set(fr_base) | set(fr_evo)):
        # **未观测 ≠ 0 失分**。臂里没有判成功的 rollout（判据全跑挂了），
        # 或者这一条判据在那条臂里压根没被观测到——这两种情况都是「不知道」，
        # 写成 0 会让报告说出「演化臂这条从没失分」，那是把**没有数据**说成
        # **全过**：2026-10-20 实测踩过（演化臂 6 条全 score=None，逐判据表
        # 却显示「演化臂失分 0.0%、Δ=-100、← 变了」）。所以用 None 承载「未知」。
        b = fr_base.get(name)
        e = fr_evo.get(name)
        per_check[name] = {
            "base_fail_rate": round(b, 4) if b is not None else None,
            "evolved_fail_rate": round(e, 4) if e is not None else None,
            "delta": round(e - b, 4) if (b is not None and e is not None) else None,
        }
    significant = p <= 0.1
    separation = (min(evolved.scores) - max(base.scores)) if (base.scores and evolved.scores) else 0.0
    # 「演化臂最差的一次也不低于基准均值」——**按容差判**，不用裸 `>=`。
    # 均值是浮点和相除出来的：`[0.8,0.8,0.8]` 的 mean 可能是 `0.8000000000000001`，
    # 于是 `0.8 >= 0.8000000000000001` 为假，两臂**逐条相同**却记成「分得不干净」。
    # 2026-10-20 实测踩到（v5 两臂都是 [0.8,0.8,0.8]，reliable 却是 False）。
    reliable = bool(
        base.scores and evolved.scores and min(evolved.scores) >= base.mean - 1e-9
    )

    # 「再跑多少遍才够」：对每一条**基准臂失分过**的判据，假设演化修好了它，算所需 n。
    need: dict[str, dict] = {}
    for name, rate in sorted(fr_base.items()):
        if rate <= 0:
            continue
        need[name] = required_n(base, name)

    # 「方向」按**容差**判零，不用 `delta == 0`。均值是浮点和相除出来的
    # （`0.8×4/4` 与 `0.8×3/3` 的尾数可能差 1e-16），用精确相等判零时，
    # 一个**零效应**会掉进「方向为正」那一支，报告上就变成
    # 「方向为正但不显著」——**把没有方向说成有方向**。2026-10-20 实测踩过：
    # `routing-poster` 两臂都是 0.800…，而 verdict 写的是「方向为正」。
    _ZERO = 1e-9
    if abs(delta) < _ZERO:
        verdict = "两臂均值相同——这一格看不出演化的作用"
    elif delta > 0 and significant:
        verdict = "有信号：演化臂显著优于同树零分布"
    elif delta > 0:
        verdict = "方向为正但不显著（n 太小或分离不干净）——**仍可能是噪声**"
    else:
        verdict = "演化臂**更差**"
    # **没数据不是「更差」**。`Arm.mean` 在空样本上返回 0.0，于是演化臂
    # 一条都没判成功时 delta = −基准均值，判决会写成「演化臂更差」——
    # 那是把**没测到**说成**测坏了**。空样本一律走单独的判决。
    no_data = not base.scores or not evolved.scores
    if no_data:
        which = []
        if not base.scores:
            which.append("基准臂")
        if not evolved.scores:
            which.append("演化臂")
        verdict = (
            f"{'、'.join(which)}没有有效样本（判据没跑成，score=None）——"
            "**这一格比不了**，不是「演化更差」"
        )

    # **演化到底动没动这一格**：面内内容逐字相同 = 演化没动。
    # 那一格是**构造上的零**——它不承载「演化有没有用」的信息（演化在那一格
    # 什么都没做，两臂必然同分布），把它算进「判不出提升」会冤枉演化。
    same_surface = bool(
        base.tree_signature
        and evolved.tree_signature
        and base.tree_signature == evolved.tree_signature
    )
    if same_surface:
        verdict = "演化**没动这一格**（可编辑面内容逐字相同）——这一格是构造上的零"

    return {
        "task_id": base.task_id,
        "base_tag": base.tag,
        "evolved_tag": evolved.tag,
        "base_n": base.n,
        "evolved_n": evolved.n,
        "base_scores": base.scores,
        "evolved_scores": evolved.scores,
        "base_mean": round(base.mean, 4),
        "evolved_mean": round(evolved.mean, 4),
        "delta_mean": round(delta, 4),
        "base_spread": round(base.spread, 4),
        "base_stdev": round(base.stdev, 4),
        "p_value": round(p, 4),
        "significant": significant,
        "separation": round(separation, 4),
        "reliable": reliable,
        "same_tree": base.tree_fingerprint == evolved.tree_fingerprint,
        "same_surface": same_surface,
        "no_data": no_data,
        "verdict": verdict,
        "per_check": per_check,
        "required_n_if_fixed": need,
    }


# ── 树来源 ────────────────────────────────────────────────────────────────────


def _selected_label(task_dir: Path) -> str:
    """这一格**被选中**的臂标签。

    k=1 时只有 `agg1`；k≥2 时引擎跑 `agg1..aggk`，由**盲选会话**挑一个。
    硬取 agg1 会抽错树——**抽错树 = 拿一条没被采纳的候选去代表演化结果**，
    那比不测更糟。读不到选择记录就退回 agg1，并说明。

    只认 `selection/<aggN|cN>/selection.json` 这种**引擎写的**路径；备份目录
    （`agg3.before-reselect/`）不算——它是「重选之前长什么样」的证据。
    """
    sel_dir = task_dir / "selection"
    if sel_dir.is_dir():
        for sel_json in sorted(sel_dir.glob("*/selection.json")):
            if not _SELECTION_DIR_RE.fullmatch(sel_json.parent.name):
                continue
            try:
                d = json.loads(sel_json.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            label = d.get("chosen_label") or ""
            if label:
                return label
    return "agg1"


_SELECTION_DIR_RE = re.compile(r"(?:agg|c)\d+")


def extract_adopted_trees(sweep_root: Path, ns: str, out_dir: Path) -> dict[str, Path]:
    """从一次跑批里把**被采纳的树**抽出来，按任务分目录。

    被采纳的树在 `<sweep_root>/adapt/<ns>/<task>/harnesses/<被选中的标签>/`。
    抽出来是为了能对它做重复 rollout——引擎只给它跑了一次。

    **选哪个标签要看选择记录**（k≥2 时是盲选的结果，不是固定 agg1）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    adapt = Path(sweep_root) / "adapt" / ns
    if not adapt.is_dir():
        return found
    for task_dir in sorted(p for p in adapt.iterdir() if p.is_dir()):
        harnesses = task_dir / "harnesses"
        if not harnesses.is_dir():
            continue
        label = _selected_label(task_dir)
        picked = harnesses / label
        if not picked.is_dir():
            # 读不到选择记录时**不能随便拿一棵**：按名字排序的最后一个可能是
            # `base3`（**没改过的基准**）或 `c3`。把基准当成「被采纳的演化树」，
            # 那一格就成了假的「构造上的零」——比不测更糟。
            # 只在 final（agg* / c*）里挑，挑不到就**跳过这一格并说明**。
            cands = sorted(
                p for p in harnesses.iterdir() if p.is_dir() and re.fullmatch(r"(?:agg|c)\d+", p.name)
            )
            if not cands:
                print(f"  [{task_dir.name}] 没有可采纳的 final（跳过这一格）")
                continue
            picked = cands[-1]
            print(f"  [{task_dir.name}] 读不到选择记录，退回 {picked.name}")
        dest = out_dir / task_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(picked, dest)
        found[task_dir.name] = dest
    return found


def load_arms(arms_dir: Path) -> dict[str, dict[str, Arm]]:
    """读回落盘的臂：`{tag: {task_id: Arm}}`。"""
    arms_dir = Path(arms_dir)
    out: dict[str, dict[str, Arm]] = {}
    if not arms_dir.is_dir():
        return out
    for tag_dir in sorted(p for p in arms_dir.iterdir() if p.is_dir()):
        per_task: dict[str, Arm] = {}
        for f in sorted(tag_dir.glob("*.json")):
            arm = Arm.from_dict(json.loads(f.read_text(encoding="utf-8")))
            per_task[arm.task_id] = arm
        if per_task:
            out[tag_dir.name] = per_task
    return out


def format_required_n(rows: Sequence[dict]) -> str:
    """「要多大 n 才测得出来」——把功效估算摆出来。"""
    lines: list[str] = []
    for r in rows:
        need = r.get("required_n_if_fixed") or {}
        if not need:
            continue
        lines.append(f"\n【{r['task_id']}】基准臂失分过的判据，各自要多大 n 才测得出来")
        for name, d in need.items():
            if not d.get("ok"):
                continue
            n = d.get("required_n")
            lines.append(
                f"  {name:<34s} 假设演化修好了它：Δ={d['delta']*100:>+5.1f} 分  "
                f"需要 n={n if n else '>40（这个效应量在 40 以内测不出来）'}"
            )
        if lines and "估算" not in lines[-1]:
            lines.append("  （正态近似估算，乐观下界；实跑建议 ×1.5）")
    return "\n".join(lines) if lines else "（基准臂没有失分项——这一格没有可测的效应）"


def format_comparison(rows: Sequence[dict]) -> str:
    """把比较结果排成一张能直接读的表。"""
    if not rows:
        return "（没有可比的臂）"
    lines = [
        f"{'任务':<20s} {'零分布(base)':<16s} {'演化臂(evolved)':<17s} {'Δ均值':>7s} {'p':>5s}  结论",
        "-" * 112,
    ]
    for r in rows:
        base_s = ",".join(f"{x*100:.0f}" for x in r["base_scores"]) or "-"
        evo_s = ",".join(f"{x*100:.0f}" for x in r["evolved_scores"]) or "-"
        if r.get("no_data"):
            # 空样本：Δ 和 p 都**没有**——打出来会让人以为「测了，差 100 分」。
            lines.append(
                f"{r['task_id']:<20s} {base_s:<16s} {evo_s:<17s} "
                f"{'—':>7s} {'—':>5s}  {r['verdict']}"
            )
            continue
        lines.append(
            f"{r['task_id']:<20s} {base_s:<16s} {evo_s:<17s} "
            f"{r['delta_mean']*100:>+6.2f} {r['p_value']:>5.2f}  {r['verdict']}"
        )
    return "\n".join(lines)


def format_failure_rate(rows: Sequence[dict]) -> str:
    """逐条判据的失分率对比——**哪一条的行为真的变了**。

    「未知」和「0%」是两回事：那一侧没数据时打「—」，不打 0%。
    """
    lines: list[str] = []
    for r in rows:
        lines.append(f"\n【{r['task_id']}】")
        for name, d in r["per_check"].items():
            b, e, dl = d["base_fail_rate"], d["evolved_fail_rate"], d["delta"]
            flag = "  ← 变了" if (dl is not None and abs(dl) > 1e-9) else ""
            b_txt = f"{b*100:>5.1f}%" if b is not None else "    —"
            e_txt = f"{e*100:>5.1f}%" if e is not None else "    —"
            d_txt = f"{dl*100:>+6.1f}" if dl is not None else "     —"
            if dl is None:
                flag = "  （有一侧没数据——比不了）"
            lines.append(
                f"  {name:<34s} base 失分 {b_txt}  "
                f"evolved 失分 {e_txt}  "
                f"Δ {d_txt}{flag}"
            )
    return "\n".join(lines) if lines else "（没有逐条判据的对比）"


def collect_corpus(arms: Iterable[Arm]) -> dict[str, list[str]]:
    """从一个臂里收集**失败语料**：哪些判据失分、失分时的最终回答长什么样。

    这是「新判据怎么来」的唯一合法路径——**先看见真实的失败，再写针**，
    然后拿这份语料验证针不误伤。凭空写的判据只能测噪声。

    返回值分两块：`fail` 是失分的最终回答，`pass` 是通过的最终回答。
    **两块都要**——新判据的验证是「在 fail 上命中、在 pass 上沉默」，
    只看 fail 会写出只会误伤的正则。
    """
    corpus: dict[str, dict[str, list[str]]] = {}
    for arm in arms:
        for r in arm.rolls:
            if not r.graded:
                continue
            for c in r.checks:
                bucket = corpus.setdefault(c["name"], {"fail": [], "pass": []})
                bucket["fail" if not c["passed"] else "pass"].append(
                    f"[{arm.task_id}/{r.run_id}] {r.final_text}"
                )
    return corpus


def validate_needle(needle: str, corpus: dict[str, dict[str, list[str]]]) -> dict[str, dict]:
    """拿一份语料验证候选正则：**在 fail 上命中、在 pass 上沉默**。

    这是判据改动的验收口径。判据一改，数字就变——所以每一条新针都得先过这一关，
    否则历史上那批分数全部作废（而且是「静默」地作废）。

    `needle` 是**判据语义**（命中即违规），所以：
    - 在 `fail` 上命中越多越好（要抓住真失败）；
    - 在 `pass` 上必须**一条都不命中**（否则是误伤）。
    """
    import re

    rx = re.compile(needle)
    out: dict[str, dict] = {}
    for name, buckets in sorted(corpus.items()):
        fail_hits = sum(1 for t in buckets["fail"] if rx.search(t))
        pass_hits = sum(1 for t in buckets["pass"] if rx.search(t))
        out[name] = {
            "n_fail": len(buckets["fail"]),
            "n_pass": len(buckets["pass"]),
            "fail_hits": fail_hits,
            "pass_hits": pass_hits,
            "recall": round(fail_hits / len(buckets["fail"]), 3) if buckets["fail"] else None,
            "false_positive": pass_hits,
        }
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────


def render_generalization(rows: Sequence[dict]) -> str:
    """把 train / eval 两侧拆开读，挂在配对比较报告后面。

    **为什么这个函数必须存在。** `compare_arms` 只看「这批任务的合并均值」，
    它不知道这批任务分两批。于是最坏的结果读数上完全隐形：

        训练题 0.6→0.9，没见过的题 0.6→0.5，合并均值 0.7 > 0.6 ⇒ 报告写「有提升」。

    `generalization.overfit_report` 负责判，这里只负责渲染。**切分不可用时明确说
    出来**，不能因为读不到切分就当泛化没问题。
    """
    try:
        import task_split
        from bench_usine import TASKS

        from generalization import format_report, overfit_report
    except Exception as exc:  # noqa: BLE001 - 报告层不该因为依赖缺失而崩
        return f"\n> **泛化报告不可用**（{type(exc).__name__}: {exc}）——两侧没有拆开读。\n"

    data = task_split.make_split(TASKS)
    tr, te = set(data["train"]), set(data["test"])
    # **只把两侧真有的格子送进去**：报告不许替没跑的任务编一个 0。
    present = {r["task_id"] for r in rows}
    rep = overfit_report(rows, train_ids=tr & present, test_ids=te & present)
    digest = task_split.split_digest(TASKS, split_data=data)
    return (
        "\n### 泛化读法：train / eval 拆开\n\n"
        f"切分指纹 `{digest}`（种子 {data['seed']}，"
        f"train {len(tr)} / eval {len(te)} 格"
        + (f"，未切分层 {data['unsplit_domains']}" if data["unsplit_domains"] else "")
        + "）\n\n"
        "```\n"
        + format_report(rep)
        + "\n```\n"
    )


def render_markdown_report(rows: Sequence[dict], *, base_tag: str, evolved_tag: str) -> str:
    """把比较结果渲染成 markdown（最终文档的数字由它产出，不手抄）。"""
    out: list[str] = []
    null_cells = [r for r in rows if r.get("same_surface")]
    # **空样本格单列**：它既不是零格（演化动了、只是没测出来），
    # 也不是「有演化」——它**不承载任何方向的证据**，混进 undecided
    # 会把「没测到」说成「测了但分不开」。
    nodata_cells = [r for r in rows if r.get("no_data") and not r.get("same_surface")]
    informative = [
        r for r in rows if not r.get("same_surface") and not r.get("no_data")
    ]
    undecided = [r for r in informative if not (r["significant"] and r["delta_mean"] > 0)]
    out.append(f"### 配对比较：零分布 `{base_tag}` vs 演化臂 `{evolved_tag}`\n")
    if null_cells:
        out.append(
            "> **零格**（演化没动这一格，可编辑面内容逐字相同，**不参与判决**）："
            + "、".join(f"`{r['task_id']}`" for r in null_cells)
            + "\n"
        )
    if nodata_cells:
        out.append(
            "> **没有有效样本**（判据没跑成，score=None）："
            + "、".join(f"`{r['task_id']}`" for r in nodata_cells)
            + "——这些格**比不了**，不构成任何方向的证据。\n"
        )
    if not informative and not nodata_cells:
        out.append("> **判决：每一格演化都没动——没有可判的演化效果。**\n")
    elif not informative:
        out.append("> **判决：没有一格拿到可比的样本——这次比较什么都没测到。**\n")
    elif undecided:
        out.append(
            "> **判决：有演化但分不开**（"
            + "、".join(f"`{r['task_id']}`" for r in undecided)
            + "）——**不能**据此说演化带来了提升。\n"
        )
    else:
        out.append(
            f"> **判决：{len(informative)} 格「有演化」的格全部显著且方向为正"
            f"（零格 {len(null_cells)} 格不参与）。**\n"
        )
    out.append("| 任务 | 零分布分数 | 演化臂分数 | Δ均值 | p 值 | 结论 |")
    out.append("|---|---|---|---|---|---|")
    for r in rows:
        b = ", ".join(f"{x*100:.0f}%" for x in r["base_scores"]) or "—"
        e = ", ".join(f"{x*100:.0f}%" for x in r["evolved_scores"]) or "—"
        if r.get("no_data"):
            out.append(
                f"| `{r['task_id']}` | {b} | {e} | — | — | {r['verdict']} |"
            )
            continue
        out.append(
            f"| `{r['task_id']}` | {b} | {e} | {r['delta_mean']*100:+.1f} | "
            f"{r['p_value']:.2f} | {r['verdict']} |"
        )
    out.append("")
    out.append("**逐条判据的失分率**（哪一条的行为真的变了）：\n")
    out.append("| 任务 | 判据 | 零分布失分率 | 演化臂失分率 | Δ |")
    out.append("|---|---|---|---|---|")
    for r in rows:
        for name, d in r["per_check"].items():
            b, e, dl = d["base_fail_rate"], d["evolved_fail_rate"], d["delta"]
            if dl is None:
                # 有一侧没数据：这一条**比不了**。不写 0%——「没观测到」
                # 和「没失分」不是一回事。
                out.append(
                    f"| `{r['task_id']}` | `{name}` | "
                    f"{f'{b*100:.0f}%' if b is not None else '—'} | "
                    f"{f'{e*100:.0f}%' if e is not None else '—'} | — |"
                )
                continue
            if abs(dl) < 1e-9 and b == 0:
                continue
            out.append(
                f"| `{r['task_id']}` | `{name}` | {b*100:.0f}% | "
                f"{e*100:.0f}% | {dl*100:+.0f} |"
            )
    out.append("")
    out.append("**要多大 n 才测得出来**（假设演化修好了对应判据）：\n")
    out.append("| 任务 | 判据 | Δ | 所需 n（每臂） |")
    out.append("|---|---|---|---|")
    any_need = False
    for r in rows:
        for name, d in (r.get("required_n_if_fixed") or {}).items():
            if not d.get("ok") or d.get("required_n") is None:
                continue
            any_need = True
            out.append(
                f"| `{r['task_id']}` | `{name}` | {d['delta']*100:+.1f} | {d['required_n']} |"
            )
    if not any_need:
        out.append("| — | — | — | 基准臂没有失分项 |")
    out.append("")
    out.append("> 判定：Δ > 0 **且** 单侧精确置换检验 p ≤ 0.1。零分布宽度只报不判。")
    out.append("> 所需 n 是正态近似的**乐观下界**（精确置换检验功效略低，实跑建议 ×1.5）。")
    return "\n".join(out)


def rescore_arm(adapter, arm: Arm, runs_root: Path) -> Arm:
    """用**当前**的判据重判一个臂已有的 rollout——**不重跑模型**。

    为什么需要：判据一改，历史上那批分数就作废了。但轨迹、事件流、最终回答
    **全都还在磁盘上**，重新判一遍是秒级的事。**判据改动不该逼你重跑模型**
    （重跑模型 = 重花钱 + 重新引入 rollout 方差，两头都亏）。

    重判后臂里的 `n` 与分布都会更新——**这正是改判据后必须做的事**，
    否则同一个臂里前半段用旧判据、后半段用新判据，分布是拼出来的，没意义。
    """
    # **取绝对路径**：适配器构造时也解析了一次，两边必须指向同一个目录，
    # 否则重判会去别处找 run 目录（2026-10-21 实测：相对路径会让整臂判成空）。
    runs_root = Path(runs_root).resolve()
    out = Arm(
        tag=arm.tag,
        task_id=arm.task_id,
        tree_fingerprint=arm.tree_fingerprint,
        tree_label=arm.tree_label,
        # **重判时重算面内容签名**：判据改了、树没改，但零格规则要能判。
        # （臂 JSON 是旧版代码写的、没带这个字段时，只能从树目录重算。）
        tree_signature=arm.tree_signature or _surface_signature(adapter, Path(arm.tree_label)),
        # **判据戳要跟着当前判据走**：重判用的就是**当前**的判据，落盘的戳
        # 必须也是当前的——留旧戳等于给这份臂贴错标签（2026-10-20 实测踩过：
        # 判据改过之后重判，戳还是旧的，于是「这套分数是哪套判据打的」无从判断）。
        criteria=_criteria_stamp(adapter, arm.task_id),
    )
    seen: set[str] = set()
    dropped_dupes: list[str] = []
    for roll in arm.rolls:
        # **同一条 rollout 只算一次**。臂的增量落盘曾经把「已跑过的前缀」和
        # 「这一轮新跑的」拼在一起，于是同一条 run_id 出现两次——分布里就多出
        # 一份一模一样的样本，n 虚高、置换检验的分母跟着虚高。
        # 2026-10-20 实测踩到：`dom1` 臂落盘 n=6，其实只有 3 条 rollout。
        # 去重**要留痕**（`dropped_duplicates` 记在臂上），不许悄悄吞掉。
        if roll.run_id in seen:
            dropped_dupes.append(roll.run_id)
            continue
        seen.add(roll.run_id)
        run_dir = runs_root / arm.task_id / roll.run_id
        bad = _integrity_reason(adapter, run_dir)
        if bad:
            # **作废 ≠ 零分**：这条 rollout 的证据自相矛盾（产物被后来的进程
            # 擦掉了），它不进分布、不进 n，但要**记下理由**。
            out.rolls.append(_void_roll(roll.run_id, bad, roll.error))
            continue
        scored = adapter.score(run_dir, arm.task_id)
        if scored is None:
            out.rolls.append(
                Roll(run_id=roll.run_id, score=None, error=roll.error or "判据跑不成")
            )
            continue
        out.rolls.append(
            Roll(
                run_id=roll.run_id,
                score=scored["score"],
                n_passed=scored["n_passed"],
                n_criteria=scored["n_criteria"],
                checks=scored["checks"],
                final_text=scored.get("final_text", ""),
            )
        )
    # 去重留痕落盘：n 从多少变成多少，得看得见。
    out.dropped_duplicates = dropped_dupes
    return out


def rescore_arms(adapter, arms_root: Path, runs_root: Path, tag: str) -> dict[str, Arm]:
    """重判落盘的一个臂，并把结果写回去。

    **不静默毁数据**：重判前先备份原 JSON；任何一条 rollout 重判不成（判据跑不
    成 / run 目录找不到）就**报错退出**，不拿一个空臂覆盖原来那份。
    2026-10-20 verifier 实测：`--runs-root` 指错时，重判把 `[0.8,0.8,0.8]` 变成
    `[]`，退出码还是 0——**看起来成功，其实把数据擦了**。

    **但「作废」不算「工具故障」**：一条 rollout 的证据自相矛盾（run 目录在
    rollout 之后被重建、产物被擦掉）时，它该**从分布里剔出去并记下理由**，
    而不是让整条臂重判失败、留下一份带假分数的旧 JSON。2026-10-20 实测踩过：
    基准臂 r1/r2 就是这么被污染的（判成 0.6，实际交付了），而重判因为
    「少了两条」直接报错退出——**污染被原样留在读数里**。
    """
    loaded = load_arms(arms_root)
    if tag not in loaded:
        return {}
    out: dict[str, Arm] = {}
    failed: list[str] = []
    voided: list[str] = []
    for task_id, arm in loaded[tag].items():
        rescored = rescore_arm(adapter, arm, runs_root)
        if rescored.n < arm.n:
            # 分清两种「少一条」：**工具故障**（必须报错退出）vs **作废**
            # （证据失真，如实剔出分布并记账）。
            broken = [
                r.run_id for r in rescored.rolls if not r.graded and not r.void_reason
            ]
            void_runs = [r for r in rescored.rolls if r.void_reason]
            if void_runs:
                voided.append(
                    f"{task_id}：{len(void_runs)} 条 rollout **作废**（证据失真，不计入 n）"
                    + "；".join(f"{r.run_id}（{r.void_reason}）" for r in void_runs)
                )
            if broken:
                failed.append(
                    f"{task_id}：{arm.n} 条里只有 {rescored.n} 条重判得出来"
                    f"（run 目录找不到，或判据跑不成）"
                )
        out[task_id] = rescored
    if failed:
        raise ValueError(
            "重判失败，以下格没有写回（原来的 JSON 原样保留）：" + "；".join(failed)
        )
    for line in voided:
        print(f"  ⚠️ {line}")
    for task_id, rescored in out.items():
        dest = Path(arms_root) / tag / f"{task_id}.json"
        if dest.is_file():
            shutil.copy2(dest, dest.with_suffix(".json.before-rescore"))
        dest.write_text(
            json.dumps(rescored.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return out


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="arms", description="臂：同树零分布与配对比较")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("extract", help="从一次跑批里抽出被采纳的树")
    p_ex.add_argument("--sweep-root", type=Path, required=True)
    p_ex.add_argument("--ns", required=True, help="命名空间（如 usine-dsh-dsh-agg3）")
    p_ex.add_argument("--out", type=Path, required=True)

    p_co = sub.add_parser("corpus", help="从落盘的臂里收集失败语料")
    p_co.add_argument("--arms-root", type=Path, required=True)
    p_co.add_argument("--tag", required=True)
    p_co.add_argument("--out", type=Path, default=None)

    p_x = sub.add_parser("crosscheck", help="引擎自跑的 base* vs repeat 路径的 base 臂")
    p_x.add_argument("--sweep-root", type=Path, required=True)
    p_x.add_argument("--ns", required=True)
    p_x.add_argument("--arms-root", type=Path, required=True)
    p_x.add_argument("--tag", required=True)

    p_r = sub.add_parser("report", help="把两个臂的比较结果渲染成 markdown")
    p_r.add_argument("--arms-root", type=Path, required=True)
    p_r.add_argument("--base-arm", required=True)
    p_r.add_argument("--evolved-arm", required=True)
    p_r.add_argument("--out", type=Path, default=None)

    p_rs = sub.add_parser("rescore", help="用当前判据重判一个臂（不重跑模型）")
    p_rs.add_argument("--arms-root", type=Path, required=True)
    p_rs.add_argument("--runs-root", type=Path, required=True, help="rollout 落盘的那个 run root")
    p_rs.add_argument("--tag", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "extract":
        found = extract_adopted_trees(args.sweep_root, args.ns, args.out)
        if not found:
            print(f"没抽到任何树：{args.sweep_root}/adapt/{args.ns}")
            return 1
        for task, path in sorted(found.items()):
            print(f"  {task:<18s} -> {path}")
        print(f"抽出 {len(found)} 棵被采纳的树 -> {args.out}")
        print(
            "（标签取自 selection.json 的 chosen_label——k≥2 时是盲选的结果，不是固定 agg1）"
        )
        return 0

    # crosscheck：引擎自己跑的 base1..basek vs repeat 路径跑的 base 臂。
    #
    # **这是对新测量路径的独立验证**：两边跑的是同一棵树、同一道题、同一批判据，
    # 只是执行路径不同（引擎的 schedule vs 臂的执行器）。两个分布应当一致——
    # 不一致就说明 repeat 路径有问题（或者两次跑批之间环境漂了），**那这一轮
    # 所有的臂间比较都不可信**。
    if args.cmd == "crosscheck":
        from bench_usine import run_checks, task_by_id
        from dsh_substrate import (
            DSH_SURFACE,
            TRAJECTORY_MAX_CHARS,
            render_canonical_events,
        )

        loaded = load_arms(args.arms_root)
        if args.tag not in loaded:
            print(f"没有这个臂：{args.tag}（现在有 {list(loaded)}）")
            return 1
        rows = []
        sweep = Path(args.sweep_root)
        for d in sorted(sweep.glob("*/*/*/base*")):
            task_id = d.parent.name
            arm = loaded[args.tag].get(task_id)
            if arm is None:
                continue
            ev = d / "events.jsonl"
            if not ev.is_file():
                continue
            traj = render_canonical_events(
                ev, obs_trunc=50_000, max_chars=TRAJECTORY_MAX_CHARS
            )
            fin = (d / "final.txt").read_text(encoding="utf-8") if (d / "final.txt").is_file() else ""
            try:
                # **run_dir 要传进去**：「产物存在」那类判据要真的去看磁盘，
                # 不给就判失败（2026-10-20 verifier 实测：不传 → 系统性偏低，
                # 报出来的「不一致」是假的）。
                score, outs = run_checks(task_by_id(task_id), traj, fin, run_dir=d)
            except Exception:
                continue
            rows.append(
                {
                    "task_id": task_id,
                    "engine_label": d.name,
                    "engine_score": round(score, 4),
                    "engine_failed": [o.name for o in outs if not o.passed],
                    "arm_scores": arm.scores,
                    "arm_mean": round(arm.mean, 4),
                }
            )
        if not rows:
            print("没有可交叉校验的样本")
            return 1
        print(f"{'任务':<20s} {'引擎的 base*':<14s} {'repeat 臂':<22s} {'臂均值':>8s}")
        print("-" * 72)
        agree = 0
        for r in rows:
            arm_s = ",".join(f"{x*100:.0f}" for x in r["arm_scores"]) or "-"
            print(
                f"{r['task_id']:<20s} {r['engine_label']+'='+format(r['engine_score']*100,'.0f')+'%':<14s} "
                f"{arm_s:<22s} {r['arm_mean']*100:>7.1f}%"
            )
            if abs(r["engine_score"] - r["arm_mean"]) <= max(0.001, r["arm_mean"] * 0.5):
                agree += 1
        print()
        print(f"引擎分数落在 repeat 臂的分布附近：{agree}/{len(rows)}")
        return 0

    if args.cmd == "rescore":
        from usine_adapter import UsineAdapter

        adapter = UsineAdapter(runs_root=args.runs_root)
        try:
            out = rescore_arms(adapter, args.arms_root, args.runs_root, args.tag)
        finally:
            adapter.close()
        if not out:
            print(f"没有这个臂：{args.tag}")
            return 1
        for task_id, arm in sorted(out.items()):
            print(
                f"  {task_id:<18s} n={arm.n}  "
                f"{[f'{s*100:.0f}' for s in arm.scores]}  均值 {arm.mean*100:.1f}%"
            )
        return 0

    if args.cmd == "report":
        loaded = load_arms(args.arms_root)
        for tag in (args.base_arm, args.evolved_arm):
            if tag not in loaded:
                print(f"没有这个臂：{tag}（现在有 {list(loaded)}）")
                return 1
        # **不许只比交集**。2026-10-20 实测踩到：两臂任务集不同时，`&` 让少掉的那几格
        # 静默不参与比较，报告照样绿灯——那是把「有一格没测」说成「两臂一致」。
        # 现在把差集单独列出来，并让退出码为 1（不完整就不许当结论）。
        base_ids = set(loaded[args.base_arm])
        evolved_ids = set(loaded[args.evolved_arm])
        only_base = sorted(base_ids - evolved_ids)
        only_evolved = sorted(evolved_ids - base_ids)
        rows = []
        for task_id in sorted(base_ids & evolved_ids):
            rows.append(compare_arms(loaded[args.base_arm][task_id], loaded[args.evolved_arm][task_id]))
        if only_base or only_evolved:
            print(
                "**两臂任务集不同，比较不完整**："
                + (f"只有基准臂有 {only_base}；" if only_base else "")
                + (f"只有演化臂有 {only_evolved}" if only_evolved else "")
            )
        if not rows:
            print("两个臂没有共同的任务")
            return 1
        md = render_markdown_report(rows, base_tag=args.base_arm, evolved_tag=args.evolved_arm)
        # **泛化报告紧跟其后**：合并均值会掩盖「train 涨、eval 跌」，
        # 所以只要切分可用就一定要把两侧拆开读（见 generalization.py 的说明）。
        md += render_generalization(rows)
        print(md)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(md, encoding="utf-8")
            print(f"record: {args.out}")
        return 1 if (only_base or only_evolved) else 0

    # corpus
    loaded = load_arms(args.arms_root)
    if args.tag not in loaded:
        print(f"没有这个臂：{args.tag}（现在有 {list(loaded)}）")
        return 1
    corpus = collect_corpus(loaded[args.tag].values())
    total = sum(len(v["fail"]) for v in corpus.values())
    print(f"臂 {args.tag}：{len(loaded[args.tag])} 个任务，失败 {total} 条")
    for name, buckets in sorted(corpus.items(), key=lambda kv: -len(kv[1]["fail"])):
        if not buckets["fail"]:
            continue
        print(f"\n=== {name}（{len(buckets['fail'])} 次失分 / {len(buckets['pass'])} 次通过）")
        for t in buckets["fail"][:3]:
            print(f"  - {t[:400]}")
    if args.out:
        args.out.write_text(
            json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nrecord: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
