"""A/B the reasoning.effort knob on fuyao-work BEFORE burning a 10-minute wave run.

Question (2026-10-19): plan A assumes switching the Curriculum seat from
reasoning_effort "max" to "medium" shrinks its first wave-authoring response
into the 180s slice.  But the engine notes effort gradations are IGNORED by
MiniMax-M3 and honored only by some models (llm/client.py) — and no probe has
ever measured the knob on fuyao-work.  Recorded history under max: bfs2 first
response 322s; bfs6b (TARGET MENU prompt) exceeded 5 minutes and was stopped.
A wave budget sized against a guess burns the whole 600s ceiling per attempt.

This probe rebuilds the engine's EXACT first Curriculum wave-authoring call
from bfs5's recorded transcript — engine base system prompt + first TASK user
message — with the CURRENT curriculum-usine.yaml system_extra (TARGET MENU)
and the recorded PLAIN_JSON_TRANSPORT_NOTE spliced in: the bytes bfs7's
Curriculum will actually see on its first call.  Each requested effort sends
one non-streaming completion (model, max_tokens, temperature=1.0 primary
sampling point, top_p=1.0 pinned — exactly what core/loop.py sends) and
reports wall time, usage tokens, and an answer preview.

Credentials come from the unified explorateur config/.env exactly like
measure_llm_latency (group-level LLM_<GROUP>_{BASE_URL,API_KEY} pairs; key
values are never printed, logged, or written).

Usage:
    <theatre venv python> probe_curriculum_effort.py [--efforts medium,max]
        [--transcript <path>] [--timeout 240] [--dry-run]
Exits 0 when at least one effort answered within its timeout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from measure_llm_latency import ENV_PATH, load_env, resolve  # noqa: E402

EXPLORATEUR = HERE.parents[0]
CURRICULUM_YAML = (EXPLORATEUR / "garage" / "config" / "roles-usine"
                   / "curriculum-usine.yaml")
DEFAULT_TRANSCRIPT = (EXPLORATEUR.parents[0] / "theatre-usine-runs"
                      / "bfs5-20261019" / "phase1" / "curriculum"
                      / "wave_001" / "segment_000" / "transcript.json")
SLUG = "fuyao-work"
EXTRA_MARKER = "USINE PRODUCTION-LINE CONTEXT"
NOTE_MARKER = "TRANSPORT CLARIFICATION:"
# Same request shape core/loop.py sends for a primary turn: primary_temperature
# (1.0, the official K3 sampling point) and top_p pinned explicitly.
PAYLOAD_STATIC = {"max_tokens": 65536, "temperature": 1.0, "top_p": 1.0}


def build_probe_input(transcript_path: Path) -> tuple[str, str, dict]:
    """Rebuild the current-shape first Curriculum call from recorded bytes.

    Recorded system = engine base + yaml-era system_extra + "\\n\\n" + transport
    note (core/actor.py appends system_extra; explore/phase1_wave.py appends the
    note).  Only the system_extra slice is swapped for the current yaml value,
    so every other byte is the engine's own record.
    """
    data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    recorded = data["system"]
    user = data["messages"][0]["content"]
    extra_start = recorded.find(EXTRA_MARKER)
    note_start = recorded.find(NOTE_MARKER)
    if extra_start <= 0 or note_start <= extra_start:
        raise RuntimeError(
            f"transcript splice markers not found: extra@{extra_start} "
            f"note@{note_start} — wrong transcript?")
    base = recorded[:extra_start]
    note = recorded[note_start:]
    extra = str(yaml.safe_load(
        CURRICULUM_YAML.read_text(encoding="utf-8"))["system_extra"])
    system = base + extra + "\n\n" + note
    diagnostics = {
        "base_chars": len(base),
        "extra_chars": len(extra),
        "note_chars": len(note),
        "system_chars": len(system),
        "user_chars": len(user),
        "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
        "target_menu_present": "TARGET MENU" in system,
        "transport_note_present": note.startswith(NOTE_MARKER),
    }
    return system, user, diagnostics


def one_arm(base_url: str, api_key: str, effort: str, system: str, user: str,
            timeout: float) -> dict:
    reasoning = ({"enabled": False} if effort == "none"
                 else {"effort": effort})
    payload = dict(PAYLOAD_STATIC)
    payload.update({
        "model": SLUG,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "reasoning": reasoning,
    })
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200] if exc.fp else ""
        return {"ok": False, "effort": effort,
                "secs": round(time.monotonic() - started, 1),
                "note": f"HTTP {exc.code} {detail}"}
    except Exception as exc:  # noqa: BLE001 - probe reports every failure
        return {"ok": False, "effort": effort,
                "secs": round(time.monotonic() - started, 1),
                "note": f"{type(exc).__name__} (timeout {timeout}s)"}
    secs = time.monotonic() - started
    answer = (body.get("choices") or [{}])[0].get("message", {}).get("content")
    answer = "" if answer is None else str(answer)
    usage = body.get("usage", {}) or {}
    return {
        "ok": True,
        "effort": effort,
        "secs": round(secs, 1),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "usage_details": usage.get("completion_tokens_details")
                         or usage.get("completion_tokens_details", {}),
        "answer_chars": len(answer),
        "answer_head": ascii(answer[:160]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--efforts", default="medium,max",
                        help="comma list, run in order (none sends "
                             "reasoning.enabled=false)")
    parser.add_argument("--transcript", default=str(DEFAULT_TRANSCRIPT))
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="print splice diagnostics, send nothing")
    args = parser.parse_args()

    if not ENV_PATH.is_file():
        print(f"credential config not found: {ENV_PATH}")
        return 2
    if not CURRICULUM_YAML.is_file():
        print(f"curriculum yaml not found: {CURRICULUM_YAML}")
        return 2
    system, user, diag = build_probe_input(Path(args.transcript))
    print("=== SPLICE DIAGNOSTICS (no content printed) ===")
    for key, value in diag.items():
        print(f"{key}: {value}")
    if not diag["target_menu_present"]:
        print("FATAL: current yaml system_extra has no TARGET MENU")
        return 2
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
                         float(args.timeout))
        results.append(result)
        if result["ok"]:
            print(f"{effort}: answered in {result['secs']}s  "
                  f"prompt={result['prompt_tokens']} "
                  f"completion={result['completion_tokens']} "
                  f"details={result['usage_details']} "
                  f"answer_chars={result['answer_chars']}")
            print(f"answer head: {result['answer_head']}")
        else:
            print(f"{effort}: FAILED after {result['secs']}s  {result['note']}")

    print("\n=== VERDICT ===")
    answered = {r["effort"]: r["secs"] for r in results if r["ok"]}
    for result in results:
        if result["ok"]:
            print(f"{result['effort']}: fits" if result["secs"] <= 180
                  else f"{result['effort']}: answered but exceeds the 180s "
                       f"slice ({result['secs']}s)")
        else:
            print(f"{result['effort']}: no answer ({result['note']})")
    if not answered:
        print("no effort answered within its timeout")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
