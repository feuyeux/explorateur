#!/usr/bin/env python3
"""smoke_dry_run_wave.py — one full usine wave, end to end, with a fake LLM.

This is the zero-quota seam proof for the usine adaptation layer: it
runs the REAL run_usine orchestrator, the REAL stock wave machinery
(explore/phase1_wave.py + practice_loop.py + core), the REAL guest VMs,
the REAL seeding/capture/replay transport, and the REAL offline gate
twice (once guest-side inside the acting branch, once host-side as the
merge gate) — but every LLM call is answered by a scripted fake, and
every endpoint credential is a dummy value.

What one scripted wave exercises (exactly 8 fake chat calls):
  1. Curriculum (fuyao-work) authors the wave fixture scaffold and the
     /home/user/phase1_wave.json handoff in one python program; the
     terminal probe accepts it inside the same segment.
  2. Actor (MiniMax-M3) runs the true offline gate inside the guest
     ("pnpm install" once, then "pnpm verify"), adds one note under
     docs/theatre-rsi/, and submits /home/user/actor_handoff.md.
     Prerequisite on the wave host: Node >= 24 + pnpm 11 on PATH, with
     a warm pnpm store or network access for the first install.
  3. Actor declares done (the done probe checks the handoff exists).
  4. Verifier (MiniMax-M3.1-Flash-Preview) publishes one
     verifier-report program with exactly one standalone VERDICT line.
  5.-8. Memory distillation and reconciliation (MiniMax-M3, dispatched
     by the charter discriminators) each write then declare done.

The completed wave triggers the real wave-merge event sink: the merge
gate runs from the fixture repo root, the candidate delta is applied,
committed ("theatre(wave-1): accept ep001 (...)"), and tagged
theatre/wave-1. The project budget (1) then ends the run as
budget_exhausted and run_usine exits 0.

Red lines honored here:
  * Zero live LLM quota: llm.client.chat is patched before any core
    module imports it, and the fake raises loudly on ANY call outside
    the scripted 8-step sequence (including continuation messages, so
    a transport seam bug fails the run instead of looping it).
  * Zero real credentials: run_usine._resolve_endpoints is patched to
    return dummy values, so the host credential store is never read
    and endpoints.json contains no real key material.
  * The real usine subtree is never touched: the merge target is a
    fixture repository built from "git archive HEAD -- usine/" (prefix
    stripped, tree at the repo root), and the harness asserts the
    explorateur HEAD and the real usine/ subtree are byte-identical
    before and after the run.

Layout (created fresh; the harness refuses to run over leftovers):
  D:/coding/personal/theatre-usine-dryrun/
    run/dry-run-wave-001/phase1/...   the run lineage (kept)
    fixture/                          the merge-target repository (kept)
    vm-scratch/                       guest VM scratch (cleaned by close())

Run it from the theatre checkout:
  .venv/Scripts/python.exe ../benchmarks/usine/smoke_dry_run_wave.py

Clean up afterwards with (single top-level rm command):
  rm -- "D:/coding/personal/theatre-usine-dryrun"
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EXPLORATEUR_ROOT = _HERE.parents[1]

DRYRUN_ROOT = Path(r"D:\coding\personal\theatre-usine-dryrun")
RUNS_PARENT = DRYRUN_ROOT / "run"
FIXTURE_DIR = DRYRUN_ROOT / "fixture"
VM_SCRATCH = DRYRUN_ROOT / "vm-scratch"
RUN_NAME = "dry-run-wave-001"

PROJECT_ID = "dry-run-wave-001"
NOTE_REL = "docs/theatre-rsi/dry-run-wave-001.md"
MEMORY_REL = "theatre-dry-run-001.md"
TAG_NAME = "theatre/wave-1"
COMMIT_SUBJECT = "theatre(wave-1): accept ep001 (dry-run-wave-001)"
EXECUTE_ACK = "RUN-USINE-PHASE1-WAVES"

FAKE_BASE_URL = "http://127.0.0.1:1/dry-run-unused"
FAKE_API_KEY = "dry-run-no-secret"

# ---------------------------------------------------------------- fake texts

SCAFFOLD_README = (
    "Dry-run fixture scaffold.\n"
    "\n"
    "This small tree exists so one branch can be staged, captured, seeded,\n"
    "verified, and merged without spending any model quota. The seed\n"
    "baseline merges over it; file collisions favor the seed.\n"
)

WAVE_INSTRUCTION = (
    "Working inside /home/user/evolution_project, run the offline "
    "verification gate exactly once - a one-time pnpm install from the "
    "project root, then pnpm verify as its own separate program - and "
    "record the outcome as one short plain-text note under "
    "docs/theatre-rsi/ and stop."
)

WAVE_RATIONALE = (
    "One tiny branch first: prove the transport, capture, verification, "
    "memory, and merge path end to end with a single offline gate run."
)

WAVE_HANDOFF_JSON = (
    "{\n"
    '  "decision": "WAVE",\n'
    '  "rationale": ' + json.dumps(WAVE_RATIONALE) + ",\n"
    '  "projects": [\n'
    "    {\n"
    '      "id": ' + json.dumps(PROJECT_ID) + ",\n"
    '      "instruction": ' + json.dumps(WAVE_INSTRUCTION) + "\n"
    "    }\n"
    "  ]\n"
    "}\n"
)

CURRICULUM_CODE = (
    "import pathlib\n"
    "\n"
    'wave_root = pathlib.Path("/home/user/evolution_wave/'
    + PROJECT_ID + '/evolution_project")\n'
    'readme = wave_root / "theatre-fixture" / "README.md"\n'
    "readme.parent.mkdir(parents=True, exist_ok=True)\n"
    "readme.write_text(\n"
    "    " + json.dumps(SCAFFOLD_README) + ",\n"
    '    encoding="utf-8")\n'
    'pathlib.Path("/home/user/phase1_wave.json").write_text(\n'
    "    " + json.dumps(WAVE_HANDOFF_JSON) + ",\n"
    '    encoding="utf-8")\n'
    'print("dry-run wave scaffold and handoff published")\n'
)

# The gate record the actor adds to the tree. Audit-clean by construction:
# no "feuille <grp> <cmd>" spelling, no USINE_ prefixed variable, no
# scripts/ mention, no backtick symbol, no link.
NOTE_TEXT = (
    "Offline gate record - dry run\n"
    "\n"
    "The verification gate ran once from this project root: a single pnpm\n"
    "install filled the store, then pnpm verify (typecheck plus every\n"
    "vitest suite) came back green or honestly skipped, and the command\n"
    "exited zero.\n"
    "This note is the only file this branch adds to the tree.\n"
)

ACTOR_HANDOFF_TEXT = (
    "STATUS: SUBMIT\n"
    "The offline verification gate ran once from the project root: pnpm\n"
    "install then pnpm verify, exit zero. One short plain-text record was\n"
    "added under docs/theatre-rsi/. Nothing else in the tree was touched.\n"
)

ACTOR_CODE = (
    "set -eu\n"
    'cd "$HOME/evolution_project"\n'
    "pnpm install\n"
    "pnpm verify\n"
    "mkdir -p docs/theatre-rsi\n"
    "cat > " + NOTE_REL + " <<'DRY_RUN_NOTE'\n"
    + NOTE_TEXT +
    "DRY_RUN_NOTE\n"
    'cat > "$HOME/actor_handoff.md" <<\'ACTOR_HANDOFF\'\n'
    + ACTOR_HANDOFF_TEXT +
    "ACTOR_HANDOFF\n"
    'echo "actor branch complete"\n'
)

# Exactly one standalone VERDICT line; no fenced or indented lines.
VERIFIER_REPORT = (
    "The candidate tree was inspected directly. The requested record "
    "exists\nat " + NOTE_REL + " as one short plain-text note.\n"
    "It states that the verification gate ran once from the project "
    "root\n(pnpm install then pnpm verify) and exited zero, and that "
    "the note is the only file the branch adds. The visible "
    "candidate\nsurface shows no other change against the "
    "seeded baseline.\n"
    "\n"
    "VERDICT: PASS\n"
)

DISTILL_NOTE_TEXT = (
    "Offline gate memory - dry run\n"
    "\n"
    "- The gate command for this tree: cd to the project root, run pnpm\n"
    "  install once, then run pnpm verify.\n"
    "- The first install fills the pnpm store from the host; the full\n"
    "  gate run finishes in about one minute.\n"
    "- Never edit anything under node_modules: it is installed material,\n"
    "  not work, and the wave machinery excludes it from merges.\n"
)

RECONCILE_APPEND_TEXT = (
    "\n"
    "## Reconciliation addendum\n"
    "\n"
    "- Nothing to reconcile against earlier notes: this was the first\n"
    "  branch of the first wave and the memory bank started empty.\n"
)

DISTILL_CODE = (
    "import pathlib\n"
    'memory = pathlib.Path("/home/user/.memory")\n'
    "memory.mkdir(parents=True, exist_ok=True)\n"
    "(memory / " + json.dumps(MEMORY_REL) + ").write_text(\n"
    "    " + json.dumps(DISTILL_NOTE_TEXT) + ",\n"
    '    encoding="utf-8")\n'
    'print("memory note written")\n'
)

RECONCILE_CODE = (
    "import pathlib\n"
    "note = pathlib.Path(\"/home/user/.memory/" + MEMORY_REL + "\")\n"
    'with note.open("a", encoding="utf-8") as handle:\n'
    "    handle.write(\n"
    "        " + json.dumps(RECONCILE_APPEND_TEXT) + ")\n"
    'print("memory reconciled")\n'
)

# The memory file is written inside the guest by its Windows Python in
# plain text mode (write_text / open("a") idioms a real model would use),
# so every "\n" lands as "\r\n" on this substrate. The pipeline must
# carry those exact bytes through pull -> journal -> install; if it ever
# normalizes line endings, this assertion fails loudly.
EXPECTED_MEMORY = ((DISTILL_NOTE_TEXT + RECONCILE_APPEND_TEXT)
                   .replace("\n", "\r\n").encode("utf-8"))


def _program_reply(lang: str, code: str) -> str:
    return json.dumps({"program": {"lang": lang, "code": code}})


DONE_REPLY = json.dumps({"done": {}})

REPLIES = {
    "curriculum": [_program_reply("python", CURRICULUM_CODE)],
    "actor": [_program_reply("bash", ACTOR_CODE), DONE_REPLY],
    "verifier": [_program_reply("verifier-report", VERIFIER_REPORT)],
    "distill": [_program_reply("python", DISTILL_CODE), DONE_REPLY],
    "reconcile": [_program_reply("python", RECONCILE_CODE), DONE_REPLY],
}

EXPECTED_SEQUENCE = [
    ("curriculum", 1), ("actor", 1), ("actor", 2), ("verifier", 1),
    ("distill", 1), ("distill", 2), ("reconcile", 1), ("reconcile", 2),
]

PRECHECK_TEXTS = (
    ("curriculum program", CURRICULUM_CODE),
    ("actor program", ACTOR_CODE),
    ("verifier report", VERIFIER_REPORT),
    ("distillation program", DISTILL_CODE),
    ("reconciliation program", RECONCILE_CODE),
)


# ------------------------------------------------------------------- plumbing

def _git(args, cwd, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): "
            + proc.stderr.decode("utf-8", "replace")[:300])
    return proc


def _git_text(args, cwd) -> str:
    return _git(args, cwd).stdout.decode("utf-8", "replace").strip()


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        _RESULTS.append((name, True, detail or ""))
        print(f"[PASS] {name}" + (f" -- {detail}" if detail else ""))
    except Exception as exc:                        # noqa: BLE001
        _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"[FAIL] {name} -- {type(exc).__name__}: {exc}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------- fixture repo

def build_fixture_repo() -> dict:
    """git-archive the real usine prefix into a fresh throwaway repo."""
    if FIXTURE_DIR.exists() and any(FIXTURE_DIR.iterdir()):
        raise RuntimeError(f"fixture directory is not empty: {FIXTURE_DIR}")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    argv = ["git", "-C", str(_EXPLORATEUR_ROOT), "archive",
            "--format=tar", "HEAD", "--", "usine/"]
    proc = subprocess.run(argv, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            "git archive of the usine prefix failed: "
            + proc.stderr.decode("utf-8", "replace")[:300])
    source_count = len([
        name for name in _git_text(
            ["ls-files", "-z", "--", "usine/"], _EXPLORATEUR_ROOT
        ).split("\0") if name])

    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tf:
        for member in tf:
            if member.isdir() or not member.isfile():
                continue
            name = member.name
            _require(name.startswith("usine/"),
                     f"archive member outside the prefix: {name!r}")
            rel = name[len("usine/"):]
            if not rel:
                continue
            target = FIXTURE_DIR.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tf.extractfile(member)
            target.write_bytes(handle.read())
            extracted += 1
    _require(extracted == source_count,
             f"extracted {extracted} file(s) but the prefix tracks "
             f"{source_count}")
    _require((FIXTURE_DIR / "package.json").is_file(),
             "fixture repo root has no package.json (gate would fail)")

    _git(["-c", "init.defaultBranch=main", "init"], FIXTURE_DIR)
    _git(["config", "core.autocrlf", "false"], FIXTURE_DIR)
    _git(["add", "-A"], FIXTURE_DIR)
    _git(["-c", "user.name=theatre-dry-run",
          "-c", "user.email=theatre-dry-run@explorateur.local",
          "commit", "-q", "-m",
          "fixture: usine baseline for the theatre dry run"], FIXTURE_DIR)
    head = _git_text(["rev-parse", "HEAD"], FIXTURE_DIR)
    print(f"fixture repo built: {extracted} file(s), HEAD {head[:10]}")
    return {"head": head, "files": extracted}


# ------------------------------------------------------------------ fake chat

class FakeChat:
    """Scripted chat stand-in. Any off-script call raises loudly."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, int] = {}
        self.log: list[dict] = []

    def __call__(self, model, system=None, user=None, **kwargs):
        text = user if isinstance(user, str) else ""
        if kwargs.get("image") is not None:
            raise RuntimeError(
                "dry run: unexpected image attachment; no scripted seat "
                "uses eyes")
        if "SAME-CONTEXT" in text:
            raise RuntimeError(
                "dry run: a continuation message reached the fake LLM "
                "(transport seam bug); text starts: " + text[:200])
        history = kwargs.get("history") or []

        def seat_of(content):
            if not isinstance(content, str):
                return None
            if "FINAL MEMORY DISTILLATION" in content:
                return "distill"
            if "TERMINAL MEMORY RECONCILIATION" in content:
                return "reconcile"
            if "ACTOR AGENT" in content and "NEW PROJECT" in content:
                return "actor"
            return None

        if model == "MiniMax-M3.1-Flash-Preview":
            seat = "verifier"
        elif model == "fuyao-work":
            seat = "curriculum"
        elif model == "MiniMax-M3":
            seat = seat_of(text)
            if seat is None and text.startswith("PROGRAM OUTPUT ("):
                # The loop hands each observation back as a fresh user
                # message while the owning charter stays in history. The
                # memory phases CONTINUE the actor session, so attribute
                # by the NEWEST charter in history, not the oldest one.
                for message in reversed(history):
                    seat = seat_of(message.get("content")
                                   if isinstance(message, dict)
                                   else message)
                    if seat is not None:
                        break
                if seat is None:
                    raise RuntimeError(
                        "dry run: an observation continuation carries no "
                        "owning charter in history; text starts: "
                        + text[:200])
            if seat is None:
                raise RuntimeError(
                    "dry run: unmapped MiniMax-M3 seat (escalation or "
                    "nudge leaked in); text starts: " + text[:200])
        else:
            raise RuntimeError(f"dry run: unexpected model {model!r}")

        with self._lock:
            index = self.counters.get(seat, 0)
            self.counters[seat] = index + 1
            self.log.append({
                "call": len(self.log) + 1, "seat": seat,
                "seat_index": index + 1, "model": model,
                "history_len": len(history), "user_len": len(text)})
        replies = REPLIES[seat]
        if index >= len(replies):
            raise RuntimeError(
                f"dry run: seat {seat!r} exhausted its scripted calls "
                f"({len(replies)}); caller wanted call {index + 1}")
        return replies[index]


def _fake_resolve_endpoints(llm_config_path, needed):
    return {slug: {"base_url": FAKE_BASE_URL, "api_key": FAKE_API_KEY}
            for slug in set(needed)}


# -------------------------------------------------------------------- precheck

def precheck_fake_texts() -> str:
    """Every scripted text must be 8-gram-disjoint from the distribution."""
    import run_usine
    import usine_hooks

    distribution = run_usine.DEFAULT_DISTRIBUTION.read_text(
        encoding="utf-8").strip()
    grams = usine_hooks._shingles(distribution)
    _require(bool(grams), "the distribution yields no shingles")
    for label, text in PRECHECK_TEXTS:
        overlap = usine_hooks._shingles(text) & grams
        _require(not overlap,
                 f"{label} shares instruction shingle(s) with the "
                 f"distribution: {sorted(overlap)[:3]}")
    return f"{len(PRECHECK_TEXTS)} text(s) clear {len(grams)} shingle(s)"


# ------------------------------------------------------------------- the run

def run_fake_wave(fixture_head: str) -> int:
    os.environ["USINE_VM_SCRATCH_ROOT"] = str(VM_SCRATCH)
    VM_SCRATCH.mkdir(parents=True, exist_ok=True)

    import run_usine
    run_usine._install_paths()
    import llm.client as llm_client
    fake = FakeChat()
    llm_client.chat = fake
    run_usine._resolve_endpoints = _fake_resolve_endpoints

    argv = [
        "--run-name", RUN_NAME,
        "--root", str(RUNS_PARENT),
        "--usine-dir", str(FIXTURE_DIR),
        "--project-budget", "1",
        "--checkpoints", "0",
        "--max-parallel", "1",
        # The fixture is a git archive: tracked files only, no node_modules.
        # Let the gate preflight install it (needs a warm pnpm store or
        # network on the wave host) so the merge gate can really run
        # "pnpm verify" - this also exercises the --gate-install path.
        "--gate-install",
        "--execute", EXECUTE_ACK,
    ]
    t0 = time.time()
    try:
        rc = run_usine.main(argv)
    except BaseException:
        print("\n--- fake chat call log (on failure) ---")
        for item in fake.log:
            print("  " + json.dumps(item))
        raise
    elapsed = time.time() - t0
    print(f"run_usine.main returned {rc} in {elapsed:.0f}s "
          f"({len(fake.log)} fake chat call(s))")
    globals()["_FAKE"] = fake
    globals()["_RUN_SECONDS"] = elapsed
    globals()["_FIXTURE_HEAD"] = fixture_head
    return rc


# ----------------------------------------------------------------- assertions

def _run_root() -> Path:
    return RUNS_PARENT / RUN_NAME / "phase1"


def _events() -> list[dict]:
    path = _run_root() / "events.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def check_exit_code(rc_holder: dict) -> None:
    def fn():
        _require(rc_holder["rc"] == 0,
                 f"run_usine exited {rc_holder['rc']} (expected 0)")
        return f"exit 0 in {globals().get('_RUN_SECONDS', 0):.0f}s"
    check("run exit code is 0", fn)


def check_call_sequence() -> None:
    def fn():
        fake = globals()["_FAKE"]
        got = [(item["seat"], item["seat_index"]) for item in fake.log]
        _require(got == EXPECTED_SEQUENCE,
                 f"call sequence drifted: {got}")
        fresh = {("curriculum", 1), ("actor", 1), ("verifier", 1)}
        for seat, index, item in [
                (i["seat"], i["seat_index"], i) for i in fake.log]:
            if (seat, index) in fresh:
                _require(item["history_len"] == 0,
                         f"{seat} call 1 carried history "
                         f"({item['history_len']} turn(s))")
        for seat in ("distill", "reconcile"):
            first = next(i for i in fake.log
                         if i["seat"] == seat and i["seat_index"] == 1)
            _require(first["history_len"] > 0,
                     f"{seat} call 1 continued an empty context")
        return f"{len(got)} call(s), same-context continuation verified"
    check("fake chat call sequence is exactly the scripted 8", fn)


def check_result_json() -> None:
    def fn():
        payload = json.loads(
            (_run_root() / "result.json").read_text(encoding="utf-8"))
        _require(payload["status"] == "budget_exhausted",
                 f"status {payload['status']!r}")
        _require(payload["projects"] == 1, f"projects {payload['projects']}")
        _require(payload["memory_files"] == 1,
                 f"memory_files {payload['memory_files']}")
        return (f"status=budget_exhausted, 1 project, "
                f"{payload['memory_bytes']} memory byte(s)")
    check("result.json reports one budgeted project", fn)


def check_endpoints_file() -> None:
    def fn():
        payload = json.loads(
            (_run_root() / "endpoints.json").read_text(encoding="utf-8"))
        expected_slugs = {"MiniMax-M3", "MiniMax-M3.1-Flash-Preview",
                          "fuyao-work"}
        _require(set(payload) == expected_slugs,
                 f"endpoint slugs drifted: {sorted(payload)}")
        for slug, spec in payload.items():
            _require(spec == {"base_url": FAKE_BASE_URL,
                              "api_key": FAKE_API_KEY},
                     f"endpoint {slug} carries non-dummy credentials")
        return f"{len(payload)} dummy endpoint(s), zero real credentials"
    check("endpoints.json holds only dummy credentials", fn)


def check_events() -> None:
    def fn():
        events = _events()
        by_type: dict[str, list[dict]] = {}
        for record in events:
            by_type.setdefault(record["event_type"], []).append(record)
        _require("PHASE1_BRANCH_EXCEPTION" not in by_type,
                 "a branch exception was recorded")
        started = by_type.get("PHASE1_WAVE_STARTED", [])
        _require(len(started) == 1 and started[0]["payload"]["wave"] == 1,
                 f"PHASE1_WAVE_STARTED drifted: {started}")
        verified = by_type.get("PHASE1_BRANCH_VERIFIED", [])
        _require(
            len(verified) == 1
            and verified[0]["payload"]["terminal_outcome"] == "PASS",
            f"PHASE1_BRANCH_VERIFIED drifted: {verified}")
        committed = by_type.get("PHASE1_BRANCH_MEMORY_COMMITTED", [])
        _require(
            len(committed) == 1
            and committed[0]["status"] == "completed",
            f"PHASE1_BRANCH_MEMORY_COMMITTED drifted: {committed}")
        completed = by_type.get("PHASE1_WAVE_COMPLETED", [])
        _require(
            len(completed) == 1 and completed[0]["status"] == "completed"
            and completed[0]["payload"]["wave"] == 1,
            f"PHASE1_WAVE_COMPLETED drifted: {completed}")
        merged = by_type.get("USINE_WAVE_MERGED", [])
        _require(
            len(merged) == 1 and merged[0]["payload"]["tag"] == TAG_NAME
            and merged[0]["payload"]["decisions"] == {"1": "merged"},
            f"USINE_WAVE_MERGED drifted: {merged}")
        return f"{len(events)} event(s), 5 wave milestone(s) verified"
    check("events.jsonl records the full wave lifecycle", fn)


def check_authoring_state() -> None:
    def fn():
        state = json.loads((
            _run_root() / "curriculum" / "wave_001" / "authoring_state.json"
        ).read_text(encoding="utf-8"))
        _require(state["status"] == "published",
                 f"authoring status {state['status']!r}")
        _require(state.get("decision") == "WAVE",
                 f"authoring decision {state.get('decision')!r}")
        _require(state["segments"] == 1, f"{state['segments']} segment(s)")
        decision = json.loads((
            _run_root() / "waves" / "wave_001" / "curriculum_decision.json"
        ).read_text(encoding="utf-8"))
        _require(decision["decision"] == "WAVE"
                 and len(decision["projects"]) == 1
                 and decision["projects"][0]["id"] == PROJECT_ID,
                 "curriculum decision drifted")
        return "published in one segment, one project declared"
    check("Curriculum wave authored and published in one segment", fn)


def check_episode() -> None:
    def fn():
        episode = _run_root() / "episodes" / "ep001"
        instruction = (episode / "project.md").read_text(encoding="utf-8")
        _require(instruction == WAVE_INSTRUCTION,
                 "episode project.md is not the declared instruction")
        actor_handoff = (episode / "handoffs" / "actor_001.md").read_text(
            encoding="utf-8")
        _require(actor_handoff.splitlines()[0].strip() == "STATUS: SUBMIT",
                 "actor handoff lost its SUBMIT token")
        verifier_text = (episode / "handoffs" / "verifier_001.md").read_text(
            encoding="utf-8")
        _require("VERDICT: PASS" in verifier_text,
                 "verifier handoff lost its verdict")
        outcome = json.loads(
            (episode / "outcome.json").read_text(encoding="utf-8"))
        _require(outcome["terminal_outcome"] == "PASS",
                 f"outcome {outcome['terminal_outcome']!r}")
        _require(outcome["project_id"] == PROJECT_ID,
                 "outcome project id drifted")
        return "instruction, SUBMIT handoff, PASS verdict, outcome all match"
    check("episode ep001 artifacts match the script", fn)


def check_memory() -> None:
    def fn():
        path = _run_root() / "memory" / MEMORY_REL
        data = path.read_bytes()
        _require(data == EXPECTED_MEMORY,
                 f"memory file drifted ({len(data)} byte(s), expected "
                 f"{len(EXPECTED_MEMORY)})")
        journal = _run_root() / "memory_journal"
        _require(any(journal.iterdir()), "memory journal is empty")
        return (f"{MEMORY_REL} = distillation + addendum "
                f"({len(data)} byte(s))")
    check("terminal memory equals distillation plus addendum", fn)


def check_merge_report() -> None:
    def fn():
        report = json.loads((
            _run_root() / "waves" / "wave_001" / "merge_report.json"
        ).read_text(encoding="utf-8"))
        _require(len(report["candidates"]) == 1,
                 "merge report does not cover exactly one candidate")
        entry = report["candidates"][0]
        _require(entry["decision"] == "merged",
                 f"merge decision {entry['decision']!r}: {entry['reason']}")
        _require(entry["terminal_outcome"] == "PASS",
                 "merge report lost the PASS outcome")
        delta = entry["delta"]
        _require(delta["added"] == [NOTE_REL],
                 f"delta.added drifted: {delta['added']}")
        _require(delta["modified"] == [],
                 f"delta.modified drifted: {delta['modified']}")
        _require(delta["deleted"] == [],
                 f"delta.deleted drifted: {delta['deleted']}")
        gate = entry["gate"] or {}
        _require(gate.get("exit_code") == 0,
                 f"merge gate exit {gate.get('exit_code')}")
        _require(report["tag"] == TAG_NAME and report["tag_created"],
                 f"tag info drifted: {report.get('tag')}")
        _require(len(report["commits"]) == 1,
                 f"{len(report['commits'])} commit(s)")
        _require(report["base_commit"] == globals()["_FIXTURE_HEAD"],
                 "merge base commit is not the fixture init commit")
        return (f"merged in {gate.get('seconds')}s gate time, "
                f"delta adds exactly {NOTE_REL}")
    check("merge report: one accepted candidate, clean delta, gate green",
          fn)


def check_fixture_repo() -> None:
    def fn():
        count = _git_text(["rev-list", "--count", "HEAD"], FIXTURE_DIR)
        _require(count == "2", f"fixture repo has {count} commit(s)")
        tags = _git_text(["tag", "-l"], FIXTURE_DIR)
        _require(tags == TAG_NAME, f"tags drifted: {tags!r}")
        tag_target = _git_text(
            ["rev-parse", f"refs/tags/{TAG_NAME}^{{commit}}"], FIXTURE_DIR)
        head = _git_text(["rev-parse", "HEAD"], FIXTURE_DIR)
        _require(tag_target == head, "the wave tag does not point at HEAD")
        subject = _git_text(["log", "-1", "--format=%s"], FIXTURE_DIR)
        _require(subject == COMMIT_SUBJECT, f"commit subject {subject!r}")
        body = _git_text(["log", "-1", "--format=%b"], FIXTURE_DIR)
        _require("X-Theatre-Wave: 1" in body, "commit trailers missing")
        changed = sorted(_git_text(
            ["diff", "--name-only", "HEAD~1", "HEAD"],
            FIXTURE_DIR).splitlines())
        _require(changed == [NOTE_REL], f"merge commit touched {changed}")
        note = (FIXTURE_DIR.joinpath(*NOTE_REL.split("/"))).read_bytes()
        _require(note == NOTE_TEXT.encode("utf-8"),
                 "the merged note bytes drifted")
        porcelain = _git(["status", "--porcelain", "-uno"],
                         FIXTURE_DIR).stdout.decode("utf-8", "replace")
        _require(not porcelain.strip(),
                 f"fixture repo is dirty: {porcelain.strip()[:200]}")
        return (f"2 commits, tag {TAG_NAME} at HEAD, merge touches only "
                f"{NOTE_REL}")
    check("fixture repo: one merge commit and one wave tag", fn)


def check_real_usine_untouched(before: dict) -> None:
    def fn():
        head = _git_text(["rev-parse", "HEAD"], _EXPLORATEUR_ROOT)
        _require(head == before["head"],
                 f"explorateur HEAD moved: {before['head'][:10]} -> "
                 f"{head[:10]}")
        porcelain = _git(["status", "--porcelain", "--untracked-files=all",
                          "--", "usine/"],
                         _EXPLORATEUR_ROOT).stdout.decode("utf-8",
                                                          "replace")
        _require(not porcelain.strip(),
                 f"real usine subtree changed: {porcelain.strip()[:200]}")
        return "HEAD unchanged, real usine/ subtree byte-identical"
    check("real usine subtree untouched", fn)


# ----------------------------------------------------------------------- main

def main() -> int:
    t0 = time.time()
    print("== usine dry run: one scripted wave with a fake LLM ==")

    for path, label in ((RUNS_PARENT / RUN_NAME, "run root"),
                        (FIXTURE_DIR, "fixture repo"),
                        (VM_SCRATCH, "vm scratch")):
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(
                f"{label} already exists and is not empty: {path}\n"
                "clean it first with a single top-level rm command")

    fixture = build_fixture_repo()
    before = {"head": _git_text(["rev-parse", "HEAD"], _EXPLORATEUR_ROOT)}

    import run_usine
    run_usine._install_paths()
    check("scripted texts are 8-gram-disjoint from the distribution",
          lambda: precheck_fake_texts())

    rc_holder: dict = {}
    try:
        rc_holder["rc"] = run_fake_wave(fixture["head"])
    except BaseException:
        raise

    check_exit_code(rc_holder)
    if rc_holder["rc"] != 0:
        print("\nrun_usine did not exit 0; skipping artifact assertions")
    else:
        check_call_sequence()
        check_result_json()
        check_endpoints_file()
        check_events()
        check_authoring_state()
        check_episode()
        check_memory()
        check_merge_report()
        check_fixture_repo()
    check_real_usine_untouched(before)

    failed = [name for name, ok, _ in _RESULTS if not ok]
    print("\n== dry run summary ==")
    print(f"{len(_RESULTS) - len(failed)}/{len(_RESULTS)} check(s) passed"
          + ("" if not failed else f"; FAILED: {failed}"))
    print(f"wall time: {time.time() - t0:.0f}s")
    print(f"artifacts kept under: {DRYRUN_ROOT}")
    print('clean up with: rm -- "%s"' % DRYRUN_ROOT)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
