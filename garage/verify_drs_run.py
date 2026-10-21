#!/usr/bin/env python3
"""verify_drs_run.py — mechanically verify one DRS (Phase 2) run.

Why this exists
---------------
The DRS has no merge step, so there is no ``merge_report.json`` to check and
no commit to diff.  Its only honest success signal is the memory delta the
result payload carries — and that payload is written by the same process
that ran the seats, so reading it proves nothing on its own.  This script
recomputes the delta from the run's own artefacts:

  * the memory tree on disk AFTER the run, hashed with the ENGINE's own
    ``_memory_tree_sha256`` (not a re-implementation of it);
  * the Phase-1 baseline tree it claims to have deepened, hashed the same
    way;
  * the per-file manifest the result payload claims, recomputed;
  * the brief the Curriculum actually published — the drill's scope, read
    out of the authoring program, so "the brief was bounded" is a fact and
    not a hope.

Exit code 0 means every check passed; 1 means at least one failed and the
run did NOT achieve what it claims.  Nothing here spends a token or starts
a VM: it is a reader.

Usage (théâtre venv):
    cd <explorateur>\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\garage\\verify_drs_run.py \
        --run-root D:\\coding\\personal\\garage-result\\bfs16i
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]

PASSED = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
    return ok


def _engine_hash(memory_dir: Path):
    """Hash a memory tree with the ENGINE's own function."""
    theatre = [p for p in EXPLORATEUR.iterdir()
               if p.is_dir() and p.name.startswith("th")]
    if not theatre:
        raise RuntimeError("no th* directory (the théâtre checkout) beside us")
    sys.path.insert(0, str(theatre[0]))
    from explore.target_learning import _memory_tree_sha256
    files = {path.name: path.read_bytes() for path in sorted(memory_dir.iterdir())
             if path.is_file()}
    return _memory_tree_sha256(files), files


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True,
                        help="the lineage root (…/garage-result/<name>)")
    args = parser.parse_args()
    root = Path(args.run_root)
    phase2 = root / "phase2"

    result_path = phase2 / "result.json"
    if not result_path.is_file():
        check("the run wrote a result.json", False,
              f"missing: {result_path}")
        return 1
    result = _read_json(result_path)
    check("the run wrote a result.json", True, str(result_path))
    check("the run reached a terminal status",
          bool(result.get("status")), f"status={result.get('status')!r}")

    delta = result.get("drs_delta") or {}
    check("the result carries a DRS delta", bool(delta),
          f"keys={sorted(delta)}")
    check("the run reached the memory phase",
          result.get("status") not in {"infra", "failed"},
          f"status={result.get('status')!r} stop={result.get('stop_reason')!r}")

    # --- the delta, recomputed from the trees on disk --------------------
    after_dir = phase2 / "memory"
    baseline_dir = root / "phase1" / "memory"
    if after_dir.is_dir() and baseline_dir.is_dir():
        after_hash, after_files = _engine_hash(after_dir)
        before_hash, before_files = _engine_hash(baseline_dir)
        claimed = delta.get("after_tree_sha256")
        check("the recomputed final tree hash matches the payload",
              claimed == after_hash, f"claimed={claimed} actual={after_hash}")
        check("the recomputed baseline tree hash matches the payload",
              delta.get("baseline_tree_sha256") == before_hash,
              f"claimed={delta.get('baseline_tree_sha256')} "
              f"actual={before_hash}")
        check("the memory tree actually CHANGED (the DRS signal)",
              after_hash != before_hash,
              f"before={before_hash[:12]} after={after_hash[:12]}")
        check("the payload's memory_changed flag is honest",
              bool(delta.get("memory_changed")) == (after_hash != before_hash),
              f"memory_changed={delta.get('memory_changed')!r}")
        added = sorted(set(after_files) - set(before_files))
        removed = sorted(set(before_files) - set(after_files))
        changed = sorted(name for name in set(after_files) & set(before_files)
                         if after_files[name] != before_files[name])
        check("the payload's added-file count is honest",
              delta.get("files_added") == len(added),
              f"claimed={delta.get('files_added')} actual={len(added)} "
              f"{added}")
        print(f"      added   : {added}")
        print(f"      changed : {changed}")
        print(f"      removed : {removed}")
        for name in sorted(after_files):
            print(f"      {len(after_files[name]):6d}B  {name}")
    else:
        check("both the baseline and the final memory tree exist", False,
              f"baseline={baseline_dir.is_dir()} after={after_dir.is_dir()}")

    # --- the manifest the payload claims --------------------------------
    manifest = delta.get("memory_manifest") or {}
    if manifest and after_dir.is_dir():
        mismatched = []
        for name, claimed in manifest.items():
            path = after_dir / name
            if not path.is_file():
                mismatched.append(f"{name}: missing")
            elif path.stat().st_size != claimed.get("bytes"):
                mismatched.append(
                    f"{name}: {path.stat().st_size}B vs "
                    f"claimed {claimed.get('bytes')}B")
        check("every file in the payload's manifest matches the tree on disk",
              not mismatched, "; ".join(mismatched))

    # --- the brief the Curriculum actually published ---------------------
    brief_programs = []
    curriculum_root = phase2 / "curriculum"
    if curriculum_root.is_dir():
        for path in sorted(curriculum_root.rglob("program.*")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "DECISION: PROJECT" in text:
                brief_programs.append((path, text))
    check("the Curriculum published a brief", bool(brief_programs),
          f"{len(brief_programs)} authoring program(s)")
    if brief_programs:
        path, text = brief_programs[-1]
        open_set = ("every message in this category",
                    "every refusal path",
                    "adapt any other suite",
                    "each message you changed")
        hits = [phrase for phrase in open_set if phrase.lower() in text.lower()]
        check("the published brief carries no open-set scope", not hits,
              f"found: {hits}" if hits else f"{path.name}")
        check("the published brief caps the report",
              "at most 12 lines" in text)
        # The bound is EXACTLY one source file and one test file — not a
        # specific pair: each drill may legitimately pick a different test
        # file, and a verifier that hard-codes the Phase-1 pair would call a
        # good drill a bad one.  The boundary clause is excluded from the
        # count: it names the files the drill must NOT touch.
        import re
        scope = text
        for marker in ("Create or modify nothing outside", "no changes to",
                       "Boundaries"):
            cut = scope.find(marker)
            if cut > 0:
                scope = scope[:cut]
                break
        sources = set(re.findall(
            r"packages/dsh-plugin/src/[A-Za-z0-9_.-]+\.ts", scope))
        tests = set(re.findall(
            r"packages/dsh-plugin/test/[A-Za-z0-9_.-]+\.ts", scope))
        check("the published brief names exactly ONE source file",
              len(sources) == 1, f"{sorted(sources)}")
        check("the published brief names exactly ONE test file",
              len(tests) == 1, f"{sorted(tests)}")

    print(f"\nDRS VERIFY: {PASSED} passed / {FAILED} failed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
