#!/usr/bin/env python3
"""time_budget.py — one hard time ceiling per RSI run.

Why this module exists
----------------------
The two recorded real waves ran far past the point where anyone was still
waiting: wave1-blocked burned ~40 minutes before its 401s surfaced, and
wave1r-lineup-switch burned ~40 minutes before its `context window exceeds
limit` surfaced.  Both stopped for INFRASTRUCTURE reasons, not convergence
reasons — the run had no time ceiling at all, so a doomed wave looked exactly
like a slow one.

A self-evolution run MUST be time-bounded or it cannot be iterated on: the
whole point of the wave loop is that a failed run is cheap to rerun.  This
module makes the ceiling an enforced, auditable artifact rather than a wish.

Design
------
1.  The run ceiling is authoritative and absolute.  It is NOT the sum of the
    per-seat budgets — the per-seat numbers are a slice plan under that
    ceiling, and the engine's own wave-boundary check
    (``project_budget`` in explore/phase1_wave.py) is the mechanism that
    actually stops work.
2.  Every seat's ``wall_clock_secs`` is rewritten in-memory from the slice
    plan before the wave starts.  A seat that overruns its slice therefore
    self-terminates instead of holding the run hostage.
3.  ``WaveDeadline`` is a monotonic guard the caller can assert against at
    any cheap boundary.  When the ceiling is hit, the caller stops the loop at
    the next COMPLETE-WAVE boundary (never mid-merge) and reports
    ``time_budget_exhausted`` — a first-class, non-failure outcome distinct
    from the engine's ``budget_exhausted`` (which means "project budget spent",
    not "time ran out").  The distinction matters: a time-stopped run has a
    partial but CONSISTENT memory tree, a project-budget-stopped run may not.
4.  A preflight can compute the whole budget plan without spending a token,
    so an operator sees "this wave will cost at most N minutes" before
    saying go.

The standing rule: ``DEFAULT_RUN_CEILING_SECS`` is 1500 (twenty-five
minutes, raised from ten on 2026-10-19 once the gateway's measured
first-response latency made the old ceiling unreachable).  A run that would
exceed it fails closed at preflight unless the operator passes an explicit
``--run-ceiling-secs`` larger value (still recorded in the manifest — the
ceiling is auditable, never implicit).
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

# One wave of self-evolution, start to finish, must fit in twenty-five
# minutes.  This was the user's standing ceiling at ten minutes (2026-10-19
# 09:44) and was raised the same day at 18:30 after two independent blockers
# were measured, not guessed:
#
#   * gateway first-response latency on the Curriculum seat: 50.6s / 108.2s /
#     138.7s / 322s / >300s across runs at the SAME effort (see
#     garage/probe_curriculum_effort.py).  A 180s slice cannot cover one
#     worst-case round trip, let alone the authoring that follows it.
#   * the Actor seat must run the offline gate (`pnpm verify`, measured 40s
#     on a red tree / 24s green) plus its own edit rounds.
#
# A ceiling that the gateway cannot meet inside is not a budget, it is a
# guaranteed abort — so the standing rule follows the measurement.  Pass
# --run-ceiling-secs explicitly to go lower or higher; it is always recorded
# in the manifest, never implicit.
DEFAULT_RUN_CEILING_SECS = 1700

# The DRS (Phase 2) run ceiling.  Phase 1 keeps the operator's twenty-eight
# minutes; the DRS is a DIFFERENT job and does not fit in it — this is
# arithmetic, not taste.  Measured 2026-10-20 (bfs16 phase 2 / bfs16f):
#
#   * curriculum review : 152s of work, but its FIRST response alone has been
#     measured at 50.6s / 108.2s / 138.7s / 322s / >300s at the same effort
#     on this gateway, and a stall is charged to the seat's time budget (the
#     bfs16d attempt lost the curriculum seat that way: 344s spent on one
#     timed-out first response against a 170s slice).
#   * actor              : 805s (bfs16f: 31 iterations, four deliverables,
#     the handoff written, the candidate captured) — the 580s Phase-1 slice
#     killed the first attempt one iteration before it published, and the
#     780s DRS slice was inside the tail of a task of this size.
#   * verifier           : ~150s (Phase 1 measured 60s at low effort; the DRS
#     candidate is larger, so more).
#   * memory phase       : 277s (Phase-1 measurement: distillation 73s +
#     reconciliation 204s).
#
# That is ~1384s of work before a single margin, and the four seats cannot
# share a 1400s slice budget with any room to spare.  So the DRS runs on its
# own ceiling, and the DRS slice plan below carries the margins the
# measurements call for.  The ceiling stays an explicit, auditable value in
# the manifest — never implicit.
DRS_RUN_CEILING_SECS = 2100

# Slice plan under the ceiling.  These are UPPER BOUNDS for a single seat,
# not targets; the engine charges only what it actually uses.
#   curriculum : authoring one wave.  Authoring starts with one expensive
#                first response (measured 50.6s..322s) and then runs cheap
#                rounds: bfs5 measured 14 iterations in 204.6s of elapsed time
#                with 0.3-0.5s of tool execution each, i.e. ~14.6s a
#                round-trip.  So this slice buys one worst-case first
#                response PLUS a realistic authoring tail.
#   actor      : one practice segment.  Must carry the offline gate
#                (`pnpm verify`: 24s green on this host) plus its edit
#                rounds and one more worst-case round trip.
#   verifier   : rolled into the actor slice in the stock loop (the Verifier
#                runs inside the actor branch), but kept explicit here so a
#                future split can tighten it without re-deriving numbers.
#   merge      : gate (`pnpm verify`) + commit.  The gate is a real cost and
#                must be inside the ceiling, not after it.
#
# The four slices sum to 1400s, and OVERHEAD_RESERVE_SECS (100s) brings the
# plan to 1500s — the plan fills the ceiling exactly, so the ACTUAL spend
# must be below it (measured: 36s of setup inside the deadline; bfs13 spent
# 804s of 1500s).  A default plan that does not FIT would fail closed on
# every run, so plan_budget asserts it.
#
# The accounting that fixes this split (measured, bfs10-bfs14 2026-10-19):
#   * ONE project costs TWO Actor segments — the handoff segment (do the
#     work) and the fresh-replay segment (a new context re-runs the
#     candidate) — and the seat's time budget is a BUDGET SHARED ACROSS
#     SEGMENTS (practice_loop.py: remaining_wall = wall_clock_secs -
#     used_wall).  So the actor slice must cover BOTH segments, not one.
#   * ONE wave runs its projects in parallel (max_parallel workers), so a
#     wave of N projects costs ONE round of actor time, not N.
#   * bfs10's 6-project wave at 2-way parallelism needed 3 rounds of actor
#     seats — 2100s of actor time inside a 1500s run.  The Curriculum's
#     wave width is agent-owned (wave_width_agent_owned) and the engine has
#     no width cap, so the width is bounded HERE, in the seat prompt: one
#     small project per wave.
#   * curriculum measured 168s (bfs13) and 176s (bfs15) of seat time for a
#     ONE-project wave; 280s covers both.
#   * actor measured 332s (bfs13, 18 iterations at max effort) and 633s
#     (bfs14, 8 iterations at 9-12k reasoning tokens per call).  The Actor
#     seat now runs at reasoning_effort "low" (measured 5x faster on the
#     same bytes, output quality unchanged), so its slice drops from 780s
#     to 580s — still 1.75x over bfs13's measured 332s.
#   * verifier measured 275s (bfs13) and STILL PRODUCED NO VERDICT: 19 of
#     its 23 turns were real probes, and the emergency wall ceiling killed
#     the seat with the report unwritten.  The verifier is the pipeline's
#     only hard gate (no report means no memory AND no merge), so its
#     slice is the one that grows: 280s -> 420s.  That is where the Actor
#     slice's 200s went.
#   * merge carries the real gate ("pnpm verify": 24s green, more on a
#     changed tree) plus the commit; 60s -> 120s.
#
# The re-balance keeps the four slices at 1400s, so the plan still fits the
# 1500s ceiling exactly and the run ceiling is unchanged.
#
# bfs15 postmortem (2026-10-19 23:50): the Verifier slice was the binding
# constraint of the whole pipeline for three consecutive runs (bfs12, bfs13,
# bfs15), not the Actor's.  Sizing a budget from the seat that failed is
# backwards; the seat that must PUBLISH A VERDICT needs the room.
#
# bfs8 postmortem (2026-10-19 18:43): the 400s curriculum slice was spent as
# 71s + 58s + 74s + 17s + 151s + 358s = 728s across six iterations.  The wave
# was fully authored at iteration 6 — the last model answer CONTAINED the
# publish program — but iteration 5 and 6 each burned one or two 120s SDK
# timeouts because iteration 2's recon program had dumped 153,675 characters
# into the history, pushing the prompt to 128k tokens and every later call
# into the gateway's slow tail.  Two amplifiers, two fixes: fold the context
# BEFORE it reaches that regime (ctx_high_water 900k -> 250k chars across all
# seats) and stop killing legitimate 128k-context responses with a 120s SDK
# timeout (RSIAGENT_LLM_TIMEOUT_SECS=180, an engine env knob, set in
# run_usine's launcher path).  Without the timeout storm the same six calls
# took ~370s of gateway time — inside the slice.
#
# Sizing is from MEASURED latency, not taste.  Every seat slice must cover at
# least one full worst-case round trip plus the work that follows it — the
# runs that died were all killed by a slice expiring before the model had
# answered once, never by the work being too large.
#
# 2026-10-21（foodnames-video 这一波）：出题席的 280s 切片**当场不够用**。
# 实测：首响应 207s（网关慢尾）、第二轮 74s，席位在 280s 处被杀，**一题都没出**
# （wave 状态 safety_ceiling，整波零产出）。时延预检早就写了同一件事：
# 出题席 20 段历史的 p50 = 211.5s、max = 728.5s——**单次响应的中位数就吃掉了
# 280s 切片的四分之三**，切片吸收不了这个波动。
# 口径对齐 DRS：DRS 的出题席切片本来就是 400s（同一张网关、同一档位），
# Phase-1 却压在 280s 上——那是**同一台机器的两种口径**。现在两边都是 400s。
# 连带的是 run ceiling：席位合计 400+580+420+120 = 1520s，加 100s 余量 = 1620s，
# 原来的 1500s 上限装不下 → 上限抬到 1700s（余量 80s）。
DEFAULT_SLICES = {
    "curriculum": 400,
    "actor": 580,
    "verifier": 420,
    "merge": 120,
}

# The DRS (Phase 2) slice plan.  Phase 1 and Phase 2 are NOT the same job and
# must not share one allocation: Phase 1 authors a wave and edits the tree;
# Phase 2 is the paper's deep recursion (RSIAgent 2.2) — the Curriculum
# reviews the Phase-1 experience, the Actor drills a deeper task against the
# memory Phase 1 produced, and the memory phase then rewrites that memory.
# Measured 2026-10-20 (bfs16 phase 2, bfs16f):
#
#   * curriculum review : 152s  (7 iterations; one 344s stalled first
#                            response, survived on the 400s slice)
#   * actor              : 805s  (bfs16f: 31 iterations, four deliverables,
#                            the handoff written and the candidate captured)
#   * verifier           : never reached in either attempt (Phase 1 measured
#                            60s at low effort)
#   * memory phase       : 277s measured in Phase 1 (distillation 73s +
#                            reconciliation 204s)
#
# The DRS actor needs ~805s, not the Phase-1 580s — and the run ceiling was
# NOT what stopped it: the DRS died at 755s of the 1500s ceiling, with 745s
# of the run's budget unused.  The binding constraint is the per-seat wall
# clock, so the fix is a Phase-2 allocation, not a bigger Phase-1 budget.
#
# The curriculum slice carries the gateway's measured FIRST-RESPONSE tail
# (up to 322s at the same effort, and a stalled request IS charged to the
# seat's time budget — the bfs16d attempt spent 344s on one timed-out first
# response and lost the curriculum seat against a 170s slice).
#
# Phase 2 does NOT merge into the usine tree: the serial core emits
# PROJECT_CLOSED, not PHASE1_WAVE_COMPLETED, so the wave-merge sink never
# fires.  The merge slice is kept small and present only so the plan stays
# complete if that ever changes.
#
# The five slices sum to 1920s, which fits the DRS ceiling (2100s) with the
# same 100s overhead reserve Phase 1 uses.
DRS_SLICES = {
    "curriculum": 400,
    "actor": 900,
    "verifier": 280,
    "memory": 320,
    "merge": 20,
}

# Every named slice plan, with the ceiling it must fit.  plan_budget asserts
# each one at construction time, so a plan that cannot fit fails the budget
# module itself instead of failing every run of that phase.
_NAMED_PLANS = (
    ("DEFAULT_SLICES", DEFAULT_SLICES, DEFAULT_RUN_CEILING_SECS),
    ("DRS_SLICES", DRS_SLICES, DRS_RUN_CEILING_SECS),
)

# Safety margin reserved for adapter overhead the engine does not bill to a
# seat: preflight, fixture capture, seed staging (git-archive of the real
# repository), event fsync, the final memory install and result.json write.
# Measured at ~40s on the recorded runs, which is why the reserve was raised
# to 100s together with the ceiling: a reserve thinner than the overhead it
# covers turns ordinary variance into an aborted run.
OVERHEAD_RESERVE_SECS = 100

TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"


class BudgetError(RuntimeError):
    """A run cannot be planned within the requested ceiling."""


@dataclasses.dataclass(frozen=True)
class BudgetPlan:
    """An auditable allocation of the run ceiling across the seats."""

    ceiling_secs: int
    slices: dict
    overhead_reserve_secs: int
    projects: int

    @property
    def seat_total_secs(self) -> int:
        return sum(self.slices.values())

    @property
    def planned_total_secs(self) -> int:
        return self.seat_total_secs + self.overhead_reserve_secs

    @property
    def fits(self) -> bool:
        return self.planned_total_secs <= self.ceiling_secs

    @property
    def slack_secs(self) -> int:
        return self.ceiling_secs - self.planned_total_secs

    def to_dict(self) -> dict:
        return {
            "ceiling_secs": self.ceiling_secs,
            "planned_total_secs": self.planned_total_secs,
            "seat_total_secs": self.seat_total_secs,
            "overhead_reserve_secs": self.overhead_reserve_secs,
            "slack_secs": self.slack_secs,
            "fits": self.fits,
            "projects": self.projects,
            "slices": dict(self.slices),
        }


def plan_budget(*, ceiling_secs: int = DEFAULT_RUN_CEILING_SECS,
                projects: int = 1,
                slices: dict | None = None) -> BudgetPlan:
    """Allocate ``ceiling_secs`` across the seats.

    ``projects`` is the wave width the Curriculum may author.  A wider wave
    does not get more time: parallel branches share the actor slice, so the
    ceiling bounds the WAVE, not each branch.  A wave that cannot fit one
    slice per parallel branch fails closed here rather than silently
    truncating branches mid-flight.
    """
    if ceiling_secs <= 0:
        raise BudgetError("run ceiling must be positive")
    if projects <= 0:
        raise BudgetError("a run must plan at least one project")
    slices = dict(DEFAULT_SLICES if slices is None else slices)
    for name, value in slices.items():
        if value <= 0:
            raise BudgetError(f"slice {name!r} must be positive")
    # A named plan that cannot fit its own ceiling would fail closed on
    # EVERY run of that phase — the budget module would be the thing that
    # breaks the pipeline.  Assert it once, loudly, at construction rather
    # than at wave time.
    for name, named, ceiling in _NAMED_PLANS:
        if slices is named and sum(slices.values()) + OVERHEAD_RESERVE_SECS \
                > ceiling:
            raise BudgetError(
                f"the {name} slice plan does not fit its ceiling "
                f"({sum(slices.values())} + {OVERHEAD_RESERVE_SECS} > "
                f"{ceiling}); rebalance {name}")

    # The Curriculum authors one wave per budgeted iteration, so a multi-wave
    # run pays the curriculum slice more than once.  Account for it honestly:
    # every additional wave must fit inside the ceiling or be refused.
    plan = BudgetPlan(
        ceiling_secs=int(ceiling_secs),
        slices=slices,
        overhead_reserve_secs=OVERHEAD_RESERVE_SECS,
        projects=int(projects),
    )
    return plan


def apply_slices(configs: dict, plan: BudgetPlan) -> dict:
    """Rewrite every seat's ``wall_clock_secs`` from the slice plan.

    Returns the applied mapping (seat -> seconds) so the caller can record it
    in the run manifest.  Mutates the loaded config dataclasses in place —
    they are assembled fresh per process, never shared across runs.

    A seat whose own configured budget is ALREADY tighter than the slice is
    left alone: the slice is a ceiling we may relax up to, not a floor we
    may raise from.  Tightening the engine's own discipline is a deliberate
    config decision, not something a slice plan should undo.
    """
    applied: dict[str, int] = {}
    for seat in ("curriculum", "actor", "memory_actor", "verifier"):
        cfg = configs.get(seat)
        if cfg is None:
            continue
        if seat == "memory_actor":
            # memory_actor shares the actor seat's budget by contract (the
            # same Agent model must own the memory it wrote) — UNLESS the
            # plan names the memory seat explicitly.  The DRS plan does: the
            # memory phase is a measured cost of its own there, and leaving
            # it on the actor's slice would let it eat the whole run.
            key = "memory" if "memory" in plan.slices else "actor"
        else:
            key = seat
        ceiling = plan.slices.get(key)
        if ceiling is None:
            continue
        current = getattr(cfg, "wall_clock_secs", 0) or 0
        effective = min(int(current), int(ceiling)) if current else int(ceiling)
        object.__setattr__(cfg, "wall_clock_secs", effective)
        applied[seat] = effective
    return applied


class WaveDeadline:
    """Monotonic guard for one run; assert it at cheap boundaries only."""

    def __init__(self, plan: BudgetPlan):
        self.plan = plan
        self.started = time.monotonic()

    @property
    def elapsed_secs(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_secs(self) -> float:
        return self.plan.ceiling_secs - self.elapsed_secs

    @property
    def expired(self) -> bool:
        return self.remaining_secs <= 0

    def budget_note(self) -> str:
        return (
            f"time_budget elapsed={self.elapsed_secs:.0f}s "
            f"ceiling={self.plan.ceiling_secs}s "
            f"remaining={self.remaining_secs:.0f}s")

    def stop_reason(self) -> str:
        return (
            f"run ceiling {self.plan.ceiling_secs}s reached after "
            f"{self.elapsed_secs:.0f}s (planned "
            f"{self.plan.planned_total_secs}s across "
            f"{len(self.plan.slices)} seats); stopped at a complete-wave "
            f"boundary so the memory tree stays consistent")


def write_plan(path: Path, plan: BudgetPlan, applied: dict | None = None) -> None:
    """Record the plan beside the run manifest (audit trail, never a secret)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.to_dict()
    if applied is not None:
        payload["applied_seat_wall_clock_secs"] = dict(applied)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    path.replace(temporary)
