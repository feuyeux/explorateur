"""Smoke test for the run time budget and the context budget gate.

A self-evolution run that cannot be bounded in time cannot be iterated on.
Both recorded real waves burned roughly forty minutes each before an
INFRASTRUCTURE failure surfaced (401 auth, then `context window exceeds
limit`), because nothing in the loop had a ceiling: the seats were declared
with day-long ``wall_clock_secs`` and no seat declared a folding policy.

This smoke pins the two defences that make a run time-bounded, and it is
deliberately offline — it spends no token and starts no VM:

  * time_budget.plan_budget: the DEFAULT slice plan fits the DEFAULT 1500s
    ceiling (a default plan that does not fit would fail closed on every
    run — the budget module would be the thing that breaks the pipeline)
  * time_budget.plan_budget: an oversized or degenerate plan fails closed
    instead of silently running over its ceiling
  * time_budget.apply_slices: every seat's wall clock is clamped to its
    slice, and an already-TIGHTER seat budget is never loosened
  * time_budget.WaveDeadline: reports remaining/expired and produces a stop
    reason naming the ceiling
  * run_usine._context_budget_check: catches a seat whose own declarations
    contradict each other (output cap >= high water, inverted watermarks,
    a high-water mark with no folding policy, an output cap above the
    gateway maximum), and passes the real usine role configs

Usage (théâtre venv):
    cd <explorateur>\\théâtre
    Windows: .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_time_budget.py
    POSIX:   .venv/bin/python ../garage/smoke_time_budget.py

Exits 0 when every section passes.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]

PASSED = 0

# Worst-case gateway round trip measured on the fuyao endpoint (run
# bfs-20261019): an APITimeoutError plus retry came back at 121s.  Any seat
# slice below this is structurally guaranteed to abort before the model
# answers, which is how the first run under this budget produced zero memory.
WORST_CASE_ROUND_TRIP_SECS = 121


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Assert one thing.  Raises SystemExit on failure; returns True on pass.

    Returns the boolean rather than None so callers can branch on it without
    inverting a None into False (``if not check(...)`` is always True for a
    None-returning helper, which silently skipped whole sections).
    """
    global PASSED
    if not ok:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        raise SystemExit(1)
    PASSED += 1
    print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
    return True


def _seat(wall: int, *, high: int = 0, low: int = 0, out: int = 65536,
          pairs: int = 0, keep: int = 0) -> object:
    """A minimal stand-in for a loaded role config dataclass."""

    @dataclasses.dataclass
    class Seat:
        wall_clock_secs: int
        ctx_high_water: int
        ctx_low_water: int
        max_tokens: int
        history_keep_pairs: int
        keep_chars: int

    return Seat(wall, high, low, out, pairs, keep)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_plan_fits_default_ceiling(tb) -> None:
    plan = tb.plan_budget(ceiling_secs=tb.DEFAULT_RUN_CEILING_SECS, projects=1)
    check("default slice plan fits the default ceiling", plan.fits,
          f"planned {plan.planned_total_secs}s <= "
          f"{plan.ceiling_secs}s (slack {plan.slack_secs}s)")
    check("default ceiling is twenty-five minutes",
          tb.DEFAULT_RUN_CEILING_SECS == 1500,
          f"{tb.DEFAULT_RUN_CEILING_SECS}s")
    check("every seat has a positive slice",
          all(value > 0 for value in plan.slices.values()),
          str(plan.slices))
    check("slack is non-negative",
          plan.slack_secs >= 0, f"{plan.slack_secs}s")


def test_plan_rejects_bad_shapes(tb) -> None:
    for name, kwargs, why in (
        ("ceiling must be positive", {"ceiling_secs": 0}, "zero ceiling"),
        ("projects must be positive", {"projects": 0}, "empty wave"),
        ("slices must be positive", {"slices": {"actor": 0}}, "zero slice"),
    ):
        try:
            tb.plan_budget(**kwargs)
        except tb.BudgetError:
            check(name, True, why)
        else:
            check(name, False, f"{why} was accepted")

    tiny = tb.plan_budget(ceiling_secs=10, projects=1)
    check("an undersized ceiling is reported as not fitting", not tiny.fits,
          f"planned {tiny.planned_total_secs}s > ceiling 10s")


def test_apply_slices_clamps_and_preserves_tighter(tb) -> None:
    plan = tb.plan_budget(ceiling_secs=600, projects=1)
    configs = {
        "curriculum": _seat(86400),
        "actor": _seat(86400),
        "memory_actor": _seat(86400),
        "verifier": _seat(86400),
    }
    applied = tb.apply_slices(configs, plan)
    check("a day-long seat budget is clamped to its slice",
          configs["curriculum"].wall_clock_secs == plan.slices["curriculum"],
          f"86400 -> {configs['curriculum'].wall_clock_secs}")
    check("the memory actor shares the actor slice",
          configs["memory_actor"].wall_clock_secs
          == configs["actor"].wall_clock_secs,
          str(applied))
    # "no seat is left unbounded" means: every applied slice is clamped to its
    # plan, not left at the stock 86400s day budget.  Bound it by the plan
    # itself rather than a literal, so raising the ceiling does not silently
    # turn this guard into a no-op.
    check("no seat is left unbounded",
          all(0 < cfg.wall_clock_secs <= tb.DEFAULT_SLICES[seat]
              for seat, cfg in configs.items()
              if seat in tb.DEFAULT_SLICES),
          str({k: v.wall_clock_secs for k, v in configs.items()}))

    # Every seat slice must cover at least one worst-case gateway round trip.
    # Measured: 121s (APITimeoutError + retry) on the fuyao gateway, recorded
    # by run bfs-20261019 — which died at `safety_ceiling` with a Curriculum
    # slice of 80s, before the model had answered once. A slice below the
    # worst-case round trip is a guaranteed abort, not a budget.
    for seat in ("curriculum", "actor"):
        slice_secs = plan.slices.get("actor" if seat == "memory_actor" else seat)
        check(
            f"{seat} slice covers one worst-case round trip",
            slice_secs >= WORST_CASE_ROUND_TRIP_SECS,
            f"{slice_secs}s >= {WORST_CASE_ROUND_TRIP_SECS}s measured round trip",
        )

    # An already-tighter budget is a deliberate config decision; the slice
    # plan is a ceiling, never a floor.
    tight = {"actor": _seat(60), "curriculum": _seat(80)}
    tb.apply_slices(tight, plan)
    check("an already-tighter seat budget is not loosened",
          tight["actor"].wall_clock_secs == 60,
          f"60 stays 60, not raised to {plan.slices['actor']}")


def test_drs_plan_is_its_own_allocation(tb) -> None:
    """Phase 2 must not inherit Phase 1's per-seat allocation.

    Measured 2026-10-20 (bfs16 phase 2, the first DRS attempt): the DRS
    Actor seat burned its whole 580s Phase-1 slice and was killed one
    iteration before publishing, while the RUN ceiling was nowhere near
    exhausted (755s of 1500s).  The binding constraint is the per-seat wall
    clock, so the DRS needs its own plan — inside the same run ceiling.
    """
    plan = tb.plan_budget(ceiling_secs=tb.DRS_RUN_CEILING_SECS, projects=1,
                           slices=tb.DRS_SLICES)
    check("the DRS slice plan fits the DRS ceiling", plan.fits,
          f"planned {plan.planned_total_secs}s <= {plan.ceiling_secs}s")
    check("the DRS ceiling is its own, not Phase 1's",
          tb.DRS_RUN_CEILING_SECS != tb.DEFAULT_RUN_CEILING_SECS,
          f"DRS {tb.DRS_RUN_CEILING_SECS}s vs Phase-1 "
          f"{tb.DEFAULT_RUN_CEILING_SECS}s")
    check("the Phase-1 plan still fits the Phase-1 ceiling",
          tb.plan_budget(ceiling_secs=tb.DEFAULT_RUN_CEILING_SECS,
                         projects=1).fits,
          f"{tb.DEFAULT_RUN_CEILING_SECS}s")
    check("the DRS plan is not the Phase-1 plan",
          tb.DRS_SLICES is not tb.DEFAULT_SLICES
          and tb.DRS_SLICES["actor"] != tb.DEFAULT_SLICES["actor"],
          f"DRS actor {tb.DRS_SLICES['actor']}s vs Phase-1 "
          f"{tb.DEFAULT_SLICES['actor']}s")

    # The DRS actor's measured need: bfs16f ran 31 iterations, wrote the
    # handoff and captured the candidate in 805s; the 580s Phase-1 slice
    # killed the first attempt one iteration before it published.
    drs_actor_need = 805
    check("the DRS actor slice covers the measured DRS actor need",
          tb.DRS_SLICES["actor"] >= drs_actor_need,
          f"{tb.DRS_SLICES['actor']}s >= {drs_actor_need}s measured")
    check("the DRS memory phase has its own slice",
          "memory" in tb.DRS_SLICES
          and tb.DRS_SLICES["memory"] > tb.DRS_SLICES["merge"],
          str(tb.DRS_SLICES))

    # The curriculum's FIRST response has been measured at 50.6s / 108.2s /
    # 138.7s / 322s / >300s at the same effort, and a stalled request IS
    # charged to the seat's wall clock — bfs16d lost the curriculum seat that
    # way (344s spent on one timed-out first response against a 170s slice).
    check("the DRS curriculum slice covers the measured gateway tail",
          tb.DRS_SLICES["curriculum"] >= 322,
          f"{tb.DRS_SLICES['curriculum']}s >= 322s measured first response")

    # The four seats' MEASURED costs must fit the DRS seat budget, with room
    # left over: curriculum 152s, actor 805s, verifier 150s, memory 277s.
    measured = {"curriculum": 152, "actor": 805, "verifier": 150, "memory": 277}
    seat_budget = tb.DRS_RUN_CEILING_SECS - tb.OVERHEAD_RESERVE_SECS
    check("the DRS seat budget covers the measured seat costs",
          sum(measured.values()) <= seat_budget,
          f"{sum(measured.values())}s measured <= {seat_budget}s seat budget")

    # A plan that names the memory seat bounds the memory phase there; a plan
    # that does not keeps the historical contract (the memory actor shares
    # the actor slice).
    drs_configs = {"curriculum": _seat(86400), "actor": _seat(86400),
                   "memory_actor": _seat(86400), "verifier": _seat(86400)}
    tb.apply_slices(drs_configs, plan)
    check("the DRS memory actor is bounded by the memory slice",
          drs_configs["memory_actor"].wall_clock_secs
          == tb.DRS_SLICES["memory"],
          str(drs_configs["memory_actor"].wall_clock_secs))

    phase1 = tb.plan_budget(ceiling_secs=tb.DEFAULT_RUN_CEILING_SECS,
                             projects=1)
    phase1_configs = {"curriculum": _seat(86400), "actor": _seat(86400),
                      "memory_actor": _seat(86400), "verifier": _seat(86400)}
    tb.apply_slices(phase1_configs, phase1)
    check("the Phase-1 memory actor still shares the actor slice",
          phase1_configs["memory_actor"].wall_clock_secs
          == phase1_configs["actor"].wall_clock_secs,
          str(phase1_configs["memory_actor"].wall_clock_secs))


def test_drs_wiring_is_sound(ru) -> None:
    """The DRS path must hand the serial core the CONTROL profile.

    Measured 2026-10-20 (bfs16f): the DRS passed the Verifier AGENT profile
    where the serial core expects the Verifier CONTROL profile, so the core
    refused the inspection with "Phase-1 Agentic Verifier control config is
    missing" — after 1158s of budget and a produced candidate.  The wiring
    must be checkable without spending a token.
    """
    garage = HERE
    sys.path.insert(0, str(garage))
    theatre = [p for p in EXPLORATEUR.iterdir()
               if p.is_dir() and p.name.startswith("th")]
    if not theatre:
        check("théâtre checkout present", False, "no th* directory")
        return
    sys.path.insert(0, str(theatre[0]))
    from config.runtime_paths import normalize_verifier_config_paths
    from config.settings import load

    configs = {}
    for role, name in ru.ROLE_FILES.items():
        cfg = load(str(garage / "config" / "roles-usine" / name))
        normalize_verifier_config_paths(cfg, garage)
        configs[role] = cfg
    # The DRS wiring check runs on the seat set Phase 2 actually uses.
    configs, _ = ru._select_phase_seats(configs, {}, "2")

    try:
        ru._check_drs_wiring(configs)
        ok, why = True, "the committed roles satisfy the DRS wiring"
    except Exception as exc:  # noqa: BLE001 - the check reports its own failure
        ok, why = False, f"{type(exc).__name__}: {exc}"
    check("the committed roles satisfy the DRS verifier wiring", ok, why)

    # And the check must actually bite: the Agent profile alone (what the
    # DRS used to pass) has no agentic_verifier_config key.
    agent_only = {"verifier_control": configs["verifier"]}
    try:
        ru._check_drs_wiring(agent_only)
        check("the DRS wiring check rejects the Agent profile", False,
              "the Agent profile was accepted as the control profile")
    except RuntimeError:
        check("the DRS wiring check rejects the Agent profile", True,
              "the Agent profile is rejected as the control profile")

    # It must also bite on the DRS curriculum seat: running the DRS with
    # Phase 1's breadth brief is the unbounded-task failure.
    try:
        ru._check_drs_wiring(
            {**configs, "curriculum": _load_phase1_curriculum(ru, garage)})
        check("the DRS wiring check rejects the Phase-1 breadth brief", False,
              "the breadth brief was accepted as the DRS curriculum seat")
    except RuntimeError:
        check("the DRS wiring check rejects the Phase-1 breadth brief", True,
              "the breadth brief is rejected as the DRS curriculum seat")


def _load_phase1_curriculum(ru, garage):
    """Load the Phase-1 breadth curriculum seat on its own."""
    sys.path.insert(0, str(garage))
    theatre = [p for p in EXPLORATEUR.iterdir()
               if p.is_dir() and p.name.startswith("th")]
    if not theatre:
        return None
    sys.path.insert(0, str(theatre[0]))
    from config.runtime_paths import normalize_verifier_config_paths
    from config.settings import load
    cfg = load(str(garage / "config" / "roles-usine" / "curriculum-usine.yaml"))
    normalize_verifier_config_paths(cfg, garage)
    return cfg


def test_deadline(tb) -> None:
    plan = tb.plan_budget(ceiling_secs=600, projects=1)
    deadline = tb.WaveDeadline(plan)
    check("a fresh deadline is not expired", not deadline.expired)
    check("a fresh deadline has the full ceiling remaining",
          deadline.remaining_secs > 590, f"{deadline.remaining_secs:.0f}s")
    note = deadline.budget_note()
    check("the budget note names the ceiling",
          str(plan.ceiling_secs) in note, note)
    reason = deadline.stop_reason()
    check("the stop reason names the ceiling and the boundary",
          str(plan.ceiling_secs) in reason and "wave" in reason.lower(), reason)
    check("the stop status is a distinct outcome",
          tb.TIME_BUDGET_EXHAUSTED == "time_budget_exhausted",
          tb.TIME_BUDGET_EXHAUSTED)

    # Force expiry without sleeping.
    deadline.started -= plan.ceiling_secs + 1
    check("an overrun deadline reports expired", deadline.expired)
    check("an expired deadline has no remaining time",
          deadline.remaining_secs < 0, f"{deadline.remaining_secs:.0f}s")


def test_context_budget_gate(ru) -> None:
    check_fn = ru._context_budget_check

    ok = check_fn({"actor": _seat(270, high=900000, low=500000,
                                  pairs=80, keep=500000)})
    check("a consistent seat passes the context gate", ok["ok"],
          str(ok["findings"]))

    cases = (
        ("output cap leaves no room under the high-water mark",
         {"actor": _seat(270, high=1000, low=500, pairs=80, keep=500000,
                         out=65536)}),
        ("watermarks are inverted",
         {"actor": _seat(270, high=500000, low=900000, pairs=80,
                         keep=500000)}),
        ("a high-water mark with no folding policy",
         {"actor": _seat(270, high=900000)}),
        ("an output cap above the gateway maximum",
         {"actor": _seat(270, out=200000)}),
    )
    for why, configs in cases:
        verdict = check_fn(configs)
        check(f"the gate catches: {why}", not verdict["ok"],
              str(verdict["findings"]))


def test_real_usine_roles_pass(ru, tb) -> None:
    """The shipped role configs must satisfy both gates as committed."""
    garage = HERE
    sys.path.insert(0, str(garage))
    theatre = [p for p in EXPLORATEUR.iterdir()
               if p.is_dir() and p.name.startswith("th")]
    if not theatre:
        check("théâtre checkout present", False, "no th* directory")
        return
    sys.path.insert(0, str(theatre[0]))
    from config.runtime_paths import normalize_verifier_config_paths
    from config.settings import load

    configs = {}
    for role, name in ru.ROLE_FILES.items():
        path = garage / "config" / "roles-usine" / name
        cfg = load(str(path))
        normalize_verifier_config_paths(cfg, garage)
        configs[role] = cfg

    plan = tb.plan_budget(ceiling_secs=ru._DEFAULT_RUN_CEILING_SECS,
                          projects=1)
    tb.apply_slices(configs, plan)
    verdict = ru._context_budget_check(configs)
    check("the committed usine role configs pass the context gate",
          verdict["ok"], str(verdict["findings"]))

    for seat in ("curriculum", "actor", "memory_actor", "verifier"):
        wall = getattr(configs[seat], "wall_clock_secs", 0)
        check(f"{seat} is inside the run ceiling",
              0 < wall <= plan.ceiling_secs,
              f"{seat}: {wall}s of {plan.ceiling_secs}s")


def test_every_plan_slice_is_actually_effective(ru, tb) -> None:
    """A slice is a CEILING, never a floor: it can only tighten a seat.

    So a seat whose OWN role config declares a wall smaller than the plan's
    slice silently runs on the smaller number, and the plan's allocation is
    a lie.  Measured 2026-10-20: the DRS plan gave the curriculum 400s, but
    curriculum-usine.yaml declared 280s, so the seat ran on 280s and lost
    the DRS to a 344s timed-out first response.  The DRS plan is only real
    if every one of its slices is the EFFECTIVE wall on the committed role
    configs.
    """
    garage = HERE
    sys.path.insert(0, str(garage))
    theatre = [p for p in EXPLORATEUR.iterdir()
               if p.is_dir() and p.name.startswith("th")]
    if not theatre:
        check("théâtre checkout present", False, "no th* directory")
        return
    sys.path.insert(0, str(theatre[0]))
    from config.runtime_paths import normalize_verifier_config_paths
    from config.settings import load

    def load_roles(phase: str) -> dict:
        configs = {}
        paths = {}
        for role, name in ru.ROLE_FILES.items():
            path = garage / "config" / "roles-usine" / name
            cfg = load(str(path))
            normalize_verifier_config_paths(cfg, garage)
            configs[role] = cfg
            paths[role] = path
        # The seat set a phase actually runs — the DRS uses its own
        # curriculum seat, so the plan must be applied to THAT seat.
        configs, paths = ru._select_phase_seats(configs, paths, phase)
        return configs

    drs = tb.plan_budget(ceiling_secs=tb.DRS_RUN_CEILING_SECS, projects=1,
                          slices=tb.DRS_SLICES)
    drs_configs = load_roles("2")
    tb.apply_slices(drs_configs, drs)
    for seat, key in (("curriculum", "curriculum"), ("actor", "actor"),
                      ("verifier", "verifier"), ("memory_actor", "memory")):
        wall = getattr(drs_configs[seat], "wall_clock_secs", 0)
        check(f"the DRS {seat} seat really runs on the DRS slice",
              wall == tb.DRS_SLICES[key],
              f"{wall}s vs planned {tb.DRS_SLICES[key]}s")

    # Phase 1 must be untouched by the DRS plan: its own slices still bind.
    phase1 = tb.plan_budget(ceiling_secs=tb.DEFAULT_RUN_CEILING_SECS,
                             projects=1)
    p1_configs = load_roles("1")
    tb.apply_slices(p1_configs, phase1)
    for seat, key in (("curriculum", "curriculum"), ("actor", "actor"),
                      ("verifier", "verifier")):
        wall = getattr(p1_configs[seat], "wall_clock_secs", 0)
        check(f"Phase 1 still runs the {seat} seat on the Phase-1 slice",
              wall == tb.DEFAULT_SLICES[key],
              f"{wall}s vs planned {tb.DEFAULT_SLICES[key]}s")


def test_drs_seat_selection_is_phase_scoped(ru) -> None:
    """Phase 2 must run the DRS curriculum seat; Phase 1 must not.

    The DRS needs a brief with a CLOSED scope — one source file, one test
    file, at most two deliverables, a table-shaped report, an existing memory
    record to deepen.  Phase 1's breadth brief has no such bound, and an
    open-set brief is what killed five DRS runs (bfs16g, 2026-10-20: the
    Actor spent seventeen rounds searching for the open set and the run
    ended with an unchanged memory tree).

    A seat-selection bug here is silent and expensive: the run would start,
    the brief would be unbounded, and the failure would only surface after
    the Actor's whole wall clock.  So both directions are pinned.
    """
    garage = HERE
    sys.path.insert(0, str(garage))
    theatre = [p for p in EXPLORATEUR.iterdir()
               if p.is_dir() and p.name.startswith("th")]
    if not theatre:
        check("théâtre checkout present", False, "no th* directory")
        return
    sys.path.insert(0, str(theatre[0]))
    from config.runtime_paths import normalize_verifier_config_paths
    from config.settings import load

    configs = {}
    paths = {}
    for role, name in ru.ROLE_FILES.items():
        path = garage / "config" / "roles-usine" / name
        cfg = load(str(path))
        normalize_verifier_config_paths(cfg, garage)
        configs[role] = cfg
        paths[role] = path
    check("the DRS curriculum seat is a declared role",
          "curriculum_drs" in ru.ROLE_FILES)
    check("the DRS curriculum seat file exists",
          paths.get("curriculum_drs", Path(".")).is_file(),
          str(paths.get("curriculum_drs")))

    drs_configs, drs_paths = ru._select_phase_seats(
        dict(configs), dict(paths), "2")
    check("Phase 2 selects the DRS curriculum seat",
          drs_paths["curriculum"].name == "curriculum-drs.yaml",
          drs_paths["curriculum"].name)
    check("Phase 2 runs the DRS seat's own brief",
          drs_configs["curriculum"] is configs["curriculum_drs"])

    p1_configs, p1_paths = ru._select_phase_seats(
        dict(configs), dict(paths), "1")
    check("Phase 1 keeps the breadth curriculum seat",
          p1_paths["curriculum"].name == "curriculum-usine.yaml",
          p1_paths["curriculum"].name)
    check("Phase 1 runs the breadth seat's own brief",
          p1_configs["curriculum"] is configs["curriculum"])


def test_drs_fixture_capture_seeds_the_guest(ru) -> None:
    """The DRS's fixture capture MUST seed the guest — it is the only seam.

    The serial core (Phase 2) resets the guest between seats.  That reset
    restores the guest from its snapshot and takes the seeded tree with it,
    so the seed pushed at VM creation is GONE by the time the Actor starts —
    unless the capture seam re-seeds it.  The DRS's fixture capture key is
    ``ep<N>-fixtures``; Phase 1's is ``phase1-project-<n>``; candidate
    captures must never be seeded (they capture the Actor's tree, which
    already carries the baseline).

    Measured 2026-10-20 (bfs16h): the DRS Actor's owned root held ONLY the
    Curriculum's two fixture files — no package.json, no packages/, no
    source — and the Actor spent its wall clock hunting for a repository
    that was not there.  Every DRS run before this died the same way, with
    an unchanged memory tree.
    """
    seeded: list = []
    original = ru._seed_guest
    ru._seed_guest = lambda vm, state: seeded.append(vm)
    try:
        captured: list = []

        def inner(vm, key, host_dir, *args, **kwargs):
            captured.append((key, kwargs.get("exclude_parts")))
            return {"ok": True}

        wrapped = ru._seeded_capture(inner, {"cache": {}})
        wrapped("VM", "phase1-project-001", "host")
        check("Phase 1's fixture capture seeds the guest", len(seeded) == 1,
              f"{len(seeded)} seed call(s)")
        wrapped("VM", "ep001-fixtures", "host")
        check("the DRS's fixture capture seeds the guest", len(seeded) == 2,
              f"{len(seeded)} seed call(s)")
        wrapped("VM", "ep001-candidate-001", "host")
        check("a candidate capture never seeds the guest", len(seeded) == 2,
              f"{len(seeded)} seed call(s)")
        wrapped("VM", "unpublished-curriculum-wave", "host")
        check("a blocked draft never seeds the guest", len(seeded) == 2,
              f"{len(seeded)} seed call(s)")
        check("every capture prunes the regenerable heavy directories",
              all(part == ru._CAPTURE_EXCLUDE_PARTS for _, part in captured),
              str(captured))
    finally:
        ru._seed_guest = original

    for marker in ("package.json", "packages/dsh-plugin/src/tools.ts"):
        check(f"the baseline marker exists in the real tree: {marker}",
              (EXPLORATEUR / "usine" / marker).is_file())


def test_replay_guard_fails_closed_without_a_baseline(ru) -> None:
    """The replay seam must PROVE the Actor gets a repository.

    A missing baseline is a wiring gap, and a wiring gap must cost seconds,
    not a thirty-minute run: the Actor would otherwise burn its whole wall
    clock looking for code that is not there.  The guard fails closed.
    """
    class FakeVM:
        def __init__(self, present: bool):
            self.present = present

        def run_command(self, command, timeout=None):
            if self.present:
                return "BASELINE_OK"
            return "BASELINE_MISSING:evolution_project/package.json"

    def inner(vm, host_dir, *args, **kwargs):
        return {"ok": True}

    guarded = ru._baseline_guarded_replay(inner, {})
    result = guarded(FakeVM(True), "host")
    check("the replay guard passes when the baseline is present",
          bool(result.get("ok")))
    try:
        guarded(FakeVM(False), "host")
        check("the replay guard fails closed without a baseline", False,
              "no error was raised")
    except RuntimeError as exc:
        check("the replay guard fails closed without a baseline", True,
              str(exc)[:120])


def test_drs_brief_has_a_closed_scope() -> None:
    """The DRS brief must state the bounds, and the Actor must have the
    matching fallback.

    Both are prompt-level contracts, and prompt-level contracts are exactly
    the kind that rot silently: a later edit that drops one clause reopens
    the unbounded-task failure without breaking a single test.  So the
    clauses that carry the bound are pinned here, by name.
    """
    import yaml

    drs_path = HERE / "config" / "roles-usine" / "curriculum-drs.yaml"
    data = yaml.safe_load(drs_path.read_text(encoding="utf-8"))
    extra = str(data.get("system_extra", ""))
    for clause in ("DRILL HAS A HARD UPPER BOUND", "ONE MESSAGE FAMILY",
                   "THE REPORT IS A TABLE", "DEEPEN AN EXISTING MEMORY RECORD",
                   "NAME THE FILE AND THE INSTANCE"):
        check(f"the DRS brief states: {clause}", clause in extra)
    check("the DRS brief bans the open-set phrasing that killed bfs16g",
          "every message in this category" in extra
          and "BANNED" in extra)

    actor = yaml.safe_load(
        (HERE / "config" / "roles-usine" / "actor-usine.yaml")
        .read_text(encoding="utf-8"))
    actor_extra = str(actor.get("system_extra", ""))
    check("the Actor seat has the scope-down fallback",
          "SCOPE DOWN, DO NOT SEARCH" in actor_extra)


def test_curriculum_target_menu_is_honest() -> None:
    """The Curriculum TARGET MENU must quote real files at real sizes.

    The menu exists to stop the Curriculum from sweeping a 456 KB package
    inside a 180s slice (measured: iteration 14, 74k tokens, no wave ever
    published).  A menu that names a moved file, or quotes a size that has
    drifted, is worse than no menu — the model trusts it, reads nothing, and
    authors against a fiction.  So the numbers are pinned here.
    """
    import yaml

    config = HERE / "config" / "roles-usine" / "curriculum-usine.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    extra = str(data.get("system_extra", ""))
    check("curriculum carries a TARGET MENU", "TARGET MENU" in extra)
    if "TARGET MENU" not in extra:
        return

    menu_targets = {
        "packages/dsh-plugin/src/tools.ts": 24_000,
        "packages/dsh-plugin/src/index.ts": 3_000,
        "packages/dsh-plugin/src/discipline.ts": 1_500,
        "packages/dsh-plugin/test/plugin-parity.test.ts": 9_000,
        "packages/dsh-plugin/test/plugin.test.ts": 15_000,
    }
    for relative, floor in sorted(menu_targets.items()):
        path = EXPLORATEUR / "usine" / relative
        if not path.is_file():
            check(f"menu target exists: {relative}", False, "file missing")
            continue
        size = path.stat().st_size
        check(f"menu target exists: {relative}", True, f"{size} bytes")
        # A band, not an exact byte count: ordinary edits must not churn this
        # config, but a file that vanished or grew 5x must fail — quoting a
        # stale size is the failure mode the menu cannot afford.
        check(
            f"menu size band still honest: {relative}",
            floor <= size <= floor * 4,
            f"{size} bytes, expected within [{floor}, {floor * 4}]",
        )

    skills = EXPLORATEUR / "usine" / "skills"
    count = (len([p for p in skills.iterdir() if p.is_dir()])
             if skills.is_dir() else 0)
    check("menu names a plausible skill count", count >= 10,
          f"{count} skill directories")


def main() -> int:
    tb = _load("smoke_time_budget_module", HERE / "time_budget.py")
    ru = _load("smoke_run_usine_module", HERE / "run_usine.py")

    test_plan_fits_default_ceiling(tb)
    test_plan_rejects_bad_shapes(tb)
    test_apply_slices_clamps_and_preserves_tighter(tb)
    test_drs_plan_is_its_own_allocation(tb)
    test_drs_wiring_is_sound(ru)
    test_deadline(tb)
    test_context_budget_gate(ru)
    test_real_usine_roles_pass(ru, tb)
    test_every_plan_slice_is_actually_effective(ru, tb)
    test_drs_seat_selection_is_phase_scoped(ru)
    test_drs_fixture_capture_seeds_the_guest(ru)
    test_replay_guard_fails_closed_without_a_baseline(ru)
    test_drs_brief_has_a_closed_scope()
    test_curriculum_target_menu_is_honest()

    print(f"\nALL {PASSED} TIME/CONTEXT BUDGET CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
