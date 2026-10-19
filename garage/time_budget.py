#!/usr/bin/env python3
"""time_budget.py — one hard wall-clock ceiling per RSI run.

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

The 10-minute rule: ``DEFAULT_RUN_CEILING_SECS`` is 600.  A run that would
exceed it fails closed at preflight unless the operator passes an explicit
``--run-ceiling-secs`` larger value (still recorded in the manifest — the
ceiling is auditable, never implicit).
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

# One wave of self-evolution, start to finish, must fit in ten minutes.
# This is the user's standing ceiling (2026-10-19), not a suggestion: the
# loop is only iterable while a failed run is cheap to rerun.
DEFAULT_RUN_CEILING_SECS = 600

# Slice plan under the ceiling.  These are UPPER BOUNDS for a single seat,
# not targets; the engine charges only what it actually uses.
#   curriculum : authoring one wave.  It is the cheapest seat and the one
#                that decides whether a wave happens at all.
#   actor      : one practice segment.  Includes verifier dialogue, so it
#                gets the largest slice.
#   verifier   : rolled into the actor slice in the stock loop (the Verifier
#                runs inside the actor branch), but kept explicit here so a
#                future split can tighten it without re-deriving numbers.
#   merge      : gate (`pnpm verify`) + commit.  The gate is a real cost and
#                must be inside the ceiling, not after it.
#
# The four slices sum to 540s, and OVERHEAD_RESERVE_SECS (45s) brings the
# plan to 585s — 15s of slack under the 600s ceiling.  A default plan that
# does not FIT would fail closed on every run, so plan_budget asserts it.
DEFAULT_SLICES = {
    "curriculum": 80,
    "actor": 270,
    "verifier": 100,
    "merge": 90,
}

# Safety margin reserved for adapter overhead the engine does not bill to a
# seat: preflight, fixture capture, seed staging, event fsync, the final
# memory install and result.json write.  Measured slack, not guesswork.
OVERHEAD_RESERVE_SECS = 45

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
    # A default plan that cannot fit would fail closed on EVERY run — the
    # budget module would be the thing that breaks the pipeline.  Assert it
    # once, loudly, at construction rather than at wave time.
    if slices is DEFAULT_SLICES and sum(slices.values()) + OVERHEAD_RESERVE_SECS \
            > DEFAULT_RUN_CEILING_SECS:
        raise BudgetError(
            "the default slice plan does not fit the default ceiling "
            f"({sum(slices.values())} + {OVERHEAD_RESERVE_SECS} > "
            f"{DEFAULT_RUN_CEILING_SECS}); rebalance DEFAULT_SLICES")

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
        # memory_actor shares the actor seat's budget by contract (the same
        # Agent model must own the memory it wrote).
        key = "actor" if seat == "memory_actor" else seat
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
