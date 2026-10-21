"""Smoke test for the endpoint latency preflight (端点时延预检).

Why this smoke exists
---------------------
The gateway's first-response latency on the SAME effort and the SAME input has
been measured at 50.6s / 108.2s / 138.7s / 322s / over 300s, while the
curriculum seat's slice is 280s.  A slice absorbs variance only so far: one
worst-case round trip can eat it, the verifier never publishes a report, and
the engine's semantics say "no verdict = the whole wave failed".  So a wave
must not be started on luck alone — the preflight reads the per-seat wall
clock the engine ALREADY recorded in past runs and refuses a wave whose
history says the slices will not hold.

The four things this smoke pins, offline and without spending a token:

  A. an empty history degrades gracefully: no refusal, ``latency_history`` is
     honestly "none"
  B. a constructed high-latency history triggers the refusal, and the reason
     names the seat, its historical max and the planned slice
  C. --allow-high-latency lets the wave through AND the risk is recorded in
     the manifest (an allowed risk is never a silent one)
  D. a damaged history (bad JSON, missing field) is handled fail-closed and
     is never silently read as "0 seconds", which would read as "no risk"

Usage (théâtre venv):
    cd <explorateur>\\théâtre
    Windows: .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_latency_budget.py
    POSIX:   .venv/theatre-mac/bin/python ../garage/smoke_latency_budget.py

Exits 0 when every section passes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

PASSED = 0

# The Phase-1 slice plan (time_budget.DEFAULT_SLICES).  2026-10-21: curriculum
# 280 → 400 (the seat's own declared wall), actor 580 → 950 (same reason).
PHASE1_SLICES = {"curriculum": 400, "actor": 950, "verifier": 420, "merge": 120}
PHASE1_APPLIED = {"curriculum": 400, "actor": 950, "verifier": 420}


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Assert one thing.  Raises SystemExit on failure."""
    global PASSED
    if not ok:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        raise SystemExit(1)
    PASSED += 1
    print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
    return True


def info(name: str, detail: str) -> None:
    print(f"INFO  {name} — {detail}")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_result(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_history(runs_root: Path, *, curriculum=393.0, actor=620.0,
                  verifier=100.0, memory=None) -> None:
    """Build a historical run root with the engine's own per-segment layout."""
    phase1 = runs_root / "bfs16i" / "phase1"
    _write_result(phase1 / "curriculum" / "wave_001" / "segment_000"
                  / "result.json",
                  {"status": "done", "iters": 4, "wall_secs": curriculum})
    _write_result(phase1 / "episodes" / "ep001" / "actor" / "attempt_001"
                  / "segment_000" / "result.json",
                  {"status": "done", "iters": 26, "wall_secs": actor})
    _write_result(phase1 / "episodes" / "ep001" / "verifier" / "cycle_001"
                  / "segment_000" / "result.json",
                  {"status": "done", "iters": 14, "wall_secs": verifier})
    if memory is not None:
        _write_result(phase1 / "episodes" / "ep001" / "memory_distillation"
                      / "segment_000" / "result.json",
                      {"status": "done", "iters": 5, "wall_secs": memory})


# --------------------------------------------------------- A: no history yet

def test_empty_history(latency) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-latency-smoke-a-") as tmp:
        runs_root = Path(tmp) / "runs"
        runs_root.mkdir()
        report = latency.assess(runs_root=runs_root, slices=PHASE1_SLICES,
                                applied=PHASE1_APPLIED)
        check("empty: the history is honestly reported as none",
              report["latency_history"] == "none", report["latency_history"])
        check("empty: an empty history does not refuse the wave",
              report["risk"] == "none", report["risk"])
        check("empty: the reason says there is no evidence",
              "no latency history" in report["reason"], report["reason"][:120])
        check("empty: the seats carry no measurement",
              all(seat["history"] == "none"
                  for seat in report["seats"].values()),
              str(report["seats"]))
        # A runs root that does not exist at all is the same case.
        report = latency.assess(runs_root=Path(tmp) / "nowhere",
                                slices=PHASE1_SLICES)
        check("empty: a missing runs root does not refuse the wave",
              report["latency_history"] == "none" and report["risk"] == "none",
              str(report["risk"]))


# --------------------------------------------- B: a high-latency history

def test_high_latency_refuses(latency, run_usine) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-latency-smoke-b-") as tmp:
        runs_root = Path(tmp) / "runs"
        runs_root.mkdir()
        _seed_history(runs_root)
        report = latency.assess(runs_root=runs_root, slices=PHASE1_SLICES,
                                applied=PHASE1_APPLIED)
        check("risk: the history is reported as measured",
              report["latency_history"] == "measured", report["latency_history"])
        check("risk: the source says measured, not inferred",
              report["source"].startswith("engine per-segment wall_secs (measured")
              and report["source"].endswith("not inferred)"),
              report["source"])
        check("risk: a seat over its slice triggers the high-latency verdict",
              report["risk"] == "high", report["risk"])
        curriculum = report["seats"]["curriculum"]
        check("risk: the curriculum seat is the one judged",
              curriculum["verdict"] == "risk", str(curriculum))
        check("risk: the historical max is reported",
              curriculum["max_secs"] == 393.0, str(curriculum))
        check("risk: the p50 is reported",
              curriculum["p50_secs"] == 393.0, str(curriculum))
        check("risk: the planned slice and the threshold are reported",
              curriculum["planned_slice_secs"] == PHASE1_SLICES["curriculum"]
              and curriculum["threshold_secs"]
              == 0.6 * PHASE1_SLICES["curriculum"], str(curriculum))
        check("risk: the actor seat is judged on its own total",
              report["seats"]["actor"]["verdict"] == "risk"
              and report["seats"]["actor"]["max_total_secs"] == 620.0,
              str(report["seats"]["actor"]))
        check("risk: a seat inside its slice is not judged",
              report["seats"]["verifier"]["verdict"] == "ok",
              str(report["seats"]["verifier"]))
        check("risk: the reason names the seat, the max and the slice",
              "curriculum" in report["reason"]
              and "393.0s" in report["reason"]
              and f"{PHASE1_SLICES['curriculum']}s" in report["reason"],
              report["reason"][:200])
        check("risk: the reason says what to do",
              "reasoning_effort" in report["reason"]
              and "--run-ceiling-secs" in report["reason"]
              and "--allow-high-latency" in report["reason"],
              report["reason"][-200:])
        check("risk: the preflight refuses the wave by default",
              run_usine._latency_blocks(report), "the run was not blocked")
        # The preflight is READ ONLY: it must not create or touch anything.
        before = sorted(str(path) for path in runs_root.rglob("*"))
        latency.assess(runs_root=runs_root, slices=PHASE1_SLICES)
        after = sorted(str(path) for path in runs_root.rglob("*"))
        check("read only: the assessment wrote nothing",
              before == after,
              "the runs root changed under the assessment")


# ------------------------------------------- C: the explicit override

def test_allow_high_latency(latency, run_usine) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-latency-smoke-c-") as tmp:
        runs_root = Path(tmp) / "runs"
        runs_root.mkdir()
        _seed_history(runs_root)
        report = latency.assess(runs_root=runs_root, slices=PHASE1_SLICES,
                                applied=PHASE1_APPLIED,
                                allow_high_latency=True)
        check("allow: the risk is still reported as high",
              report["risk"] == "high", report["risk"])
        check("allow: the wave is not blocked any more",
              not run_usine._latency_blocks(report), "the run was blocked")
        check("allow: the report says the risk was allowed",
              report["allowed"] is True, str(report["allowed"]))
        entry = run_usine._latency_manifest_entry(report)
        marker = entry["latency_preflight"]
        check("allow: the manifest carries the risk marker",
              marker["risk"] == "high" and marker["allowed"] is True,
              str(marker))
        check("allow: the manifest marker keeps the reason",
              "curriculum" in marker["reason"], marker["reason"][:120])
        check("allow: the manifest marker keeps the per-seat verdict",
              marker["seats"]["curriculum"]["verdict"] == "risk",
              str(marker["seats"]["curriculum"]))
        # A resume compares the manifest byte for byte; the observation of the
        # runs root is not a protocol decision and must not block a resume.
        manifest = {"latency_preflight": marker, "schema_version": 1}
        check("allow: the observation is excluded from the resume gate",
              run_usine._resume_manifest_key(manifest) == {"schema_version": 1},
              str(run_usine._resume_manifest_key(manifest)))
        check("allow: everything else stays in the resume gate",
              run_usine._resume_manifest_key(
                  {"latency_preflight": marker, "configs": {"a": 1}})
              == {"configs": {"a": 1}},
              "the resume key dropped more than the observation")


# ------------------------------------------- D: a damaged history

def test_damaged_history_fails_closed(latency) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-latency-smoke-d-") as tmp:
        runs_root = Path(tmp) / "runs"
        runs_root.mkdir()
        phase1 = runs_root / "bfs16i" / "phase1"
        _write_result(phase1 / "curriculum" / "wave_001" / "segment_000"
                      / "result.json", "{not json at all")
        _write_result(phase1 / "episodes" / "ep001" / "actor" / "attempt_001"
                      / "segment_000" / "result.json",
                      {"status": "done", "iters": 3})
        _write_result(phase1 / "episodes" / "ep001" / "verifier" / "cycle_001"
                      / "segment_000" / "result.json",
                      {"status": "done", "wall_secs": "not a number"})
        report = latency.assess(runs_root=runs_root, slices=PHASE1_SLICES,
                                applied=PHASE1_APPLIED)
        check("damaged: a damaged history refuses the wave",
              report["risk"] == "high", report["risk"])
        check("damaged: the damaged files are named",
              len(report["corrupt"]) == 3, str(report["corrupt"]))
        check("damaged: the reason says the history is damaged",
              "corrupt latency history" in report["reason"],
              report["reason"][:200])
        check("damaged: a damaged record is never read as zero seconds",
              all(seat["max_secs"] is None
                  for seat in report["seats"].values()),
              str(report["seats"]))
        check("damaged: the verdict is conservative on purpose",
              "deliberately conservative" in report["reason"],
              report["reason"][-160:])
        # A single healthy sample plus a damaged one is still fail-closed.
        with tempfile.TemporaryDirectory(prefix="usine-latency-smoke-d2-") as tmp2:
            other = Path(tmp2) / "runs"
            other.mkdir()
            phase = other / "lineage" / "phase1"
            _write_result(phase / "curriculum" / "wave_001" / "segment_000"
                          / "result.json", {"wall_secs": 10.0})
            _write_result(phase / "episodes" / "ep001" / "actor"
                          / "attempt_001" / "segment_000" / "result.json",
                          {"wall_secs": None})
            report = latency.assess(runs_root=other, slices=PHASE1_SLICES)
            check("damaged: one damaged record is enough to fail closed",
                  report["risk"] == "high", report["risk"])


# ---------------------------------- E: the preflight stays free of tokens

def test_preflight_is_free(latency) -> None:
    source = (HERE / "latency_budget.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "import urllib",
                      "import socket", "openai", "anthropic", "api_key"):
        check(f"free: the latency module never pulls in {forbidden!r}",
              forbidden not in source,
              "the module source is free of " + forbidden)
    check("free: the module only reads files (no write helpers)",
          ".write_text(" not in source and "open(" not in source,
          "the module only reads; it never writes")


def main() -> int:
    latency = _load("smoke_latency_budget_module", HERE / "latency_budget.py")
    run_usine = _load("smoke_run_usine_module", HERE / "run_usine.py")
    test_empty_history(latency)
    test_high_latency_refuses(latency, run_usine)
    test_allow_high_latency(latency, run_usine)
    test_damaged_history_fails_closed(latency)
    test_preflight_is_free(latency)
    print(f"\nALL {PASSED} LATENCY PREFLIGHT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
