#!/usr/bin/env python3
"""merge_drs.py — merge a finished DRS (Phase 2) run into the usine tree.

Why this exists
---------------
The DRS closes its episode with ``PROJECT_CLOSED``, not
``PHASE1_WAVE_COMPLETED``, so the wave-merge event sink never fires: the
episode's candidate — verifier PASS, offline gate green — stays in the run
root and the repository never changes.  A DRS that improved the repository
is therefore invisible, which is the worst possible outcome for a run
whose whole point is to be seen.

This is the operator-facing door for that merge.  It runs the SAME
machinery a breadth wave goes through — delta, drift check, the offline
gate against the REAL tree, commit, tag — so a DRS improvement lands under
the same rules as everything else, and it is re-gated on the way in rather
than trusted from the guest.  ``run_usine.py --merge-drs`` does the same
thing at the end of a DRS run; this script exists for the case where the
run already happened (or the merge has to be redone).

``--plan`` is the preview: it touches nothing in the repository and
reports the delta and the verdict the merge would reach, so "what would
land here" is a fact before the gate is paid for.

Usage (théâtre venv):
    cd <explorateur>\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\garage\\merge_drs.py --plan \\
        --run-root D:\\coding\\personal\\theatre-usine-runs\\bfs16i\\phase2
    .\\.venv\\Scripts\\python.exe ..\\garage\\merge_drs.py \\
        --run-root D:\\coding\\personal\\theatre-usine-runs\\bfs16i\\phase2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parent
sys.path.insert(0, str(HERE))


def _install_paths() -> None:
    """Put the théâtre checkout on sys.path (the engine lives there)."""
    candidates = [path for path in EXPLORATEUR.iterdir()
                  if path.is_dir() and path.name.startswith("th")]
    if not candidates:
        raise RuntimeError(
            f"no th* directory (the theatre checkout) beside {EXPLORATEUR}")
    sys.path.insert(0, str(candidates[0]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="merge a DRS run's candidate into the usine tree")
    parser.add_argument(
        "--run-root", required=True,
        help="the DRS run root (the directory holding episodes/ and memory/)")
    parser.add_argument(
        "--usine-dir", default=str(EXPLORATEUR / "usine"),
        help="the usine checkout to merge into (default: <explorateur>/usine)")
    parser.add_argument(
        "--gate-argv", default="pnpm verify",
        help="the offline gate command, space separated (default: 'pnpm verify')")
    parser.add_argument(
        "--gate-timeout", type=float, default=1800.0,
        help="seconds the gate may take (default: 1800)")
    parser.add_argument(
        "--gate-env", action="append", default=[], metavar="KEY=VALUE",
        help=("extra environment for the gate, repeatable (e.g. "
              "FEUILLE_BROWSER=C:\\nope\\chrome.exe to make the browser "
              "suites SKIP instead of failing on a desktop browser that "
              "holds the rendering singleton)"))
    parser.add_argument(
        "--plan", action="store_true",
        help="preview only: report the delta and the verdict, change nothing")
    return parser


def _gate_env(pairs: list[str]) -> dict:
    env: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"--gate-env expects KEY=VALUE, got {item!r}")
        key, _, value = item.partition("=")
        env[key.strip()] = value
    return env


def main(argv: list | None = None) -> int:
    args = _parser().parse_args(argv)
    _install_paths()
    # The house policy for the merge gate, identical to a wave's: a
    # standalone pnpm.exe in front of the PATH (the npm shim resolves to
    # pnpm 10, the workspace needs >= 11), and a browserless host so the
    # rendering suites SKIP instead of failing on a desktop browser that
    # holds the rendering singleton.  Both are setdefaults: an operator's
    # explicit value stays authoritative.
    import run_usine
    run_usine._prepend_standalone_pnpm()
    run_usine._wave_host_no_browser()
    import wave_merge

    run_root = Path(args.run_root).expanduser().resolve(strict=True)
    usine_dir = Path(args.usine_dir).expanduser().resolve(strict=True)
    config = wave_merge.UsineMergeConfig(
        usine_dir=str(usine_dir),
        gate_argv=tuple(str(item) for item in args.gate_argv.split()),
        gate_timeout=float(args.gate_timeout),
        gate_env=_gate_env(args.gate_env) or None)
    try:
        if args.plan:
            report = wave_merge.plan_drs_run(str(run_root), config)
        else:
            report = wave_merge.merge_drs_run(str(run_root), config)
    except wave_merge.UsineMergeError as exc:
        print(f"DRS merge failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    if args.plan:
        return 0
    decisions = [entry.get("decision") for entry in report.get("candidates", [])]
    return 0 if "merged" in decisions else 1


if __name__ == "__main__":
    raise SystemExit(main())
