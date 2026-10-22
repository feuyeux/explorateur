"""A/B the reasoning.effort knob on the ACTOR seat (fuyao-coding).

Why (2026-10-19, bfs10): the Curriculum seat's A/B lives in
probe_curriculum_effort.py.  The Actor seat showed the SAME knob doing the
opposite of what the intuition says.  bfs10's recorded actor turns:

    iter 1: out=16135  reasoning=14538   -> answered after a timeout + retry
    iter 2: out=1957   reasoning=997     -> fast
    iter 3: out=11485  reasoning=10674   -> answered after a timeout + retry

The turns that carry ~10-15k reasoning tokens take 119-149s and collide with
the SDK timeout; the turn that reasons 997 tokens takes 75s.  So on this seat
the reasoning budget IS the time cost — but the curriculum A/B proved
that "lower effort is cheaper" is not a safe assumption on this gateway, so
the Actor knob gets measured, not guessed.

This probe rebuilds the engine's EXACT first Actor call from bfs10's
recorded transcript: the engine base system prompt (recorded) plus the
CURRENT actor-usine.yaml system_extra (the OUTPUT BUDGET text, which did not
exist in the recorded run).  The engine assembles the system as
``base + system_extra`` (core/actor.py build_system), and the recorded
system carried an EMPTY system_extra, so base + current extra reproduces the
new configuration byte for byte.  The first TASK user message is taken from
the same recording, so the workload is the real published project.

Usage:
    <theatre venv python> probe_actor_effort.py [--efforts medium,max]
        [--timeout 240] [--dry-run]
Exits 0 when at least one effort answered within its timeout.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from measure_llm_latency import ENV_PATH, load_env, resolve  # noqa: E402
from probe_curriculum_effort import one_arm  # noqa: E402

EXPLORATEUR = HERE.parents[0]
ACTOR_YAML = (EXPLORATEUR / "garage" / "config" / "roles-usine"
              / "actor-usine.yaml")
DEFAULT_TRANSCRIPT = (EXPLORATEUR.parents[0] / "garage-result"
                      / "bfs10-20261019" / "phase1" / "episodes" / "ep003"
                      / "actor" / "attempt_001" / "segment_000"
                      / "transcript.json")
# bfs10's run directory is the date-stamped one; fall back to the plain name.
if not DEFAULT_TRANSCRIPT.is_file():
    DEFAULT_TRANSCRIPT = (EXPLORATEUR.parents[0] / "garage-result"
                          / "bfs10" / "phase1" / "episodes" / "ep003"
                          / "actor" / "attempt_001" / "segment_000"
                          / "transcript.json")
SLUG = "fuyao-coding"


def build_probe_input(transcript_path: Path, *, last_turn: bool = False) -> tuple[str, str, dict]:
    """Rebuild the current-shape first Actor call from recorded bytes.

    The engine assembles the system prompt as ``base + cfg.system_extra``
    (core/actor.py: build_system).  The recording was made when
    actor-usine.yaml carried an EMPTY system_extra, so the recorded system
    IS the base; the current yaml's extra is appended to reproduce the
    configuration the next wave will actually run.

    ``last_turn=True`` rebuilds the request for the LAST recorded turn
    instead of the first: the system prompt plus the whole accumulated
    conversation minus the final assistant reply.  That is the heavy-context
    regime where the real cost lives — bfs14's actor spent 60-85s per call
    with 9-12k reasoning tokens at a 22k prompt, while the same task in
    bfs13 ran at 19s per call.  The first-turn probe cannot see that.
    """
    data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    recorded = data["system"]
    messages = list(data.get("messages") or [])
    if last_turn:
        if len(messages) < 2:
            raise RuntimeError("transcript has too few messages for a last-turn probe")
        history = messages[:-1]
        user = ""
    else:
        history = []
        user = messages[0]["content"]
    extra = str(yaml.safe_load(
        ACTOR_YAML.read_text(encoding="utf-8"))["system_extra"])
    # The recorded system already carries the CURRENT extra when the recording
    # was made with this yaml (bfs14+); older recordings carry an empty one.
    # Appending blindly would double the text, so detect and adapt.
    marker = extra.strip().splitlines()[0].strip()
    already = bool(marker) and marker in recorded
    system = recorded if already else recorded + extra
    diagnostics = {
        "recorded_base_chars": len(recorded),
        "extra_chars": len(extra),
        "system_chars": len(system),
        "user_chars": len(user),
        "history_messages": len(history),
        "output_budget_present": "OUTPUT BUDGET" in system,
        "recorded_already_had_extra": already,
    }
    return system, user, diagnostics, history


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--efforts", default="medium,max",
                        help="comma list, run in order")
    parser.add_argument("--transcript", default=str(DEFAULT_TRANSCRIPT))
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--last-turn", action="store_true",
                        help="rebuild the LAST recorded turn (heavy context) "
                             "instead of the first")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not ENV_PATH.is_file():
        print(f"credential config not found: {ENV_PATH}")
        return 2
    if not ACTOR_YAML.is_file():
        print(f"actor yaml not found: {ACTOR_YAML}")
        return 2
    transcript = Path(args.transcript)
    if not transcript.is_file():
        print(f"transcript not found: {transcript}")
        return 2
    system, user, diag, history = build_probe_input(
        transcript, last_turn=args.last_turn)
    print("=== SPLICE DIAGNOSTICS (no content printed) ===")
    for key, value in diag.items():
        print(f"{key}: {value}")
    print(f"slug: {SLUG}")
    if diag["recorded_already_had_extra"]:
        print("note: the recording already carries the current system_extra; "
              "the probe uses it verbatim (no double append)")
    else:
        print("note: the recording predates the current system_extra; the "
              "probe appends it (as the engine would)")
    if args.dry_run:
        return 0

    resolved = resolve(SLUG, load_env(ENV_PATH))
    if resolved is None:
        print(f"{SLUG}: NO CREDENTIAL PAIR")
        return 2
    base_url, api_key = resolved

    results: list[dict] = []
    for effort in [item.strip() for item in args.efforts.split(",")
                   if item.strip()]:
        print(f"\n=== EFFORT {effort} (sending, timeout {args.timeout}s) ===",
              flush=True)
        result = one_arm(base_url, api_key, effort, system, user,
                         float(args.timeout), history=history, slug=SLUG)
        results.append(result)
        if result["ok"]:
            print(f"{effort}: answered in {result['secs']}s  "
                  f"prompt={result['prompt_tokens']} "
                  f"completion={result['completion_tokens']} "
                  f"details={result['usage_details']} "
                  f"answer_chars={result['answer_chars']}")
        else:
            print(f"{effort}: FAILED after {result['secs']}s  {result['note']}")

    print("\n=== VERDICT ===")
    for result in results:
        if result["ok"]:
            verdict = "fits" if result["secs"] <= 180 else "answered but over 180s"
            print(f"{result['effort']}: {verdict} ({result['secs']}s)")
        else:
            print(f"{result['effort']}: no answer ({result['note']})")
    if not any(r["ok"] for r in results):
        print("no effort answered within its timeout")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
