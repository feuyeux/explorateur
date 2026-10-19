"""Measure real round-trip latency per LLM slug before re-sizing the wave budget.

Two recorded runs (bfs-20261019, bfs2-20261019) both died at the Curriculum
seat: fuyao-work returned APITimeoutError on 3 of 4 round trips, once after
322s.  A wave budget cannot be sized against a guess — it has to be sized
against a measured latency distribution, otherwise every run either aborts
early (slice too small) or blows the ceiling (slice too large).

This probe issues a MINIMAL request per slug (a few output tokens, no tools,
no reasoning) three times, and reports each round trip.  Minimal prompt on
purpose: it measures transport + queueing, not model intelligence.

Credentials come from the unified explorateur config/.env, exactly like
run_usine._resolve_endpoints: group-level LLM_<GROUP>_{BASE_URL,API_KEY}
pairs, never per-slug overrides of a different group.  Key values are never
printed, logged, or written.

Usage:
    python <theatre venv> measure_llm_latency.py
Exits 0 when at least one slug answered at least once.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]
ENV_PATH = EXPLORATEUR / "config" / ".env"

# Slugs the wave lineup actually seats.  minimax is measured for comparison
# only: garage's ALLOWED_MODEL_SLUGS fail-closed on it today, so a win here
# would be evidence for a lineup decision, not a silent swap.
SLUGS = ("fuyao-work", "fuyao-coding", "minimax-3.1")
ROUNDS = 3
TIMEOUT_SECS = 240
PROMPT = "Reply with exactly: ok"


def load_env(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name and value:
            entries[name] = value
    return entries


def stems(slug: str) -> list[str]:
    parts = re.sub(r"[^A-Za-z0-9]", "_", slug).upper().split("_")
    return ["_".join(parts[:i]) for i in range(len(parts), 0, -1)]


def resolve(slug: str, entries: dict[str, str]) -> tuple[str, str] | None:
    for stem in stems(slug):
        base = entries.get(f"LLM_{stem}_BASE_URL", "")
        key = entries.get(f"LLM_{stem}_API_KEY", "")
        if base and key:
            return base, key
    return None


def one_call(base_url: str, api_key: str, slug: str) -> tuple[float, str]:
    payload = json.dumps({
        "model": slug,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 8,
        "temperature": 0.0,
    }).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECS) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
        elapsed = time.monotonic() - started
        usage = body.get("usage", {}) or {}
        return elapsed, (f"ok in={usage.get('prompt_tokens')} "
                         f"out={usage.get('completion_tokens')}")
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - started
        return elapsed, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - probe reports every failure
        elapsed = time.monotonic() - started
        return elapsed, f"{type(exc).__name__}"


def main() -> int:
    if not ENV_PATH.is_file():
        print(f"credential config not found: {ENV_PATH}")
        return 2
    entries = load_env(ENV_PATH)

    report: dict[str, dict] = {}
    for slug in SLUGS:
        resolved = resolve(slug, entries)
        if resolved is None:
            print(f"{slug:16} NO CREDENTIAL PAIR")
            report[slug] = {"ok": False, "why": "no credential pair"}
            continue
        base_url, api_key = resolved
        samples: list[float] = []
        notes: list[str] = []
        for index in range(ROUNDS):
            elapsed, note = one_call(base_url, api_key, slug)
            samples.append(elapsed)
            notes.append(note)
            print(f"{slug:16} round {index + 1}: {elapsed:7.1f}s  {note}",
                  flush=True)
        successes = [value for value, note in zip(samples, notes)
                     if note.startswith("ok")]
        report[slug] = {
            "ok": bool(successes),
            "samples": [round(value, 1) for value in samples],
            "success_count": len(successes),
            "median_success": round(statistics.median(successes), 1)
            if successes else None,
            "notes": notes,
        }

    print("\n=== SUMMARY (successful round trips only) ===")
    ranked = sorted(
        ((slug, data) for slug, data in report.items()
         if data.get("median_success") is not None),
        key=lambda item: item[1]["median_success"])
    if not ranked:
        print("no slug completed a single round trip")
        return 1
    for slug, data in ranked:
        print(f"{slug:16} median {data['median_success']:7.1f}s   "
              f"success {data['success_count']}/{ROUNDS}   "
              f"all {data['samples']}")

    fastest = ranked[0]
    print(f"\nFASTEST: {fastest[0]} @ {fastest[1]['median_success']}s median")
    print("Note: garage ALLOWED_MODEL_SLUGS fail-closed on any slug outside "
          "{fuyao-work, fuyao-coding}; swapping the lineup is an explicit "
          "decision, not something this probe changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
