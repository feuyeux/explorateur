#!/usr/bin/env python3
"""run_usine.py — orchestrate RSI waves over the usine production line.

Phase-1 wave loop for the usine (feuille) multilingual video production line,
adapted onto the worktree substrate through garage/{guest_env,
verifier_adapter,usine_hooks,wave_merge}.py.  Two hosts can drive it: the
Windows wave host (git-bash + subst drives) and POSIX dev hosts such as this
Mac (bash + scratch-disk prefix; guest_env/verifier_adapter branch on
os.name with the Windows code path byte-identical).  The stock wave
machinery (explore/phase1_wave.py) is reused untouched; this orchestrator
only assembles the adaptation layer around it.

Assembly contract (order is load-bearing)
-----------------------------------------
1.  Locate the théâtre checkout and put it (plus this directory) on sys.path.
2.  install_verifier_adapter() BEFORE any core/explore import: production
    construction sites resolve the executor and system-prompt builder from
    core.verifier_runtime at call time.
3.  Patch core.actor.build_system / core.loop.build_system (dual-module, ALE
    precedent) with substrate-true replacements + a transport note.  The patch
    asserts every seam substring against BOTH stock variants (native/blind)
    at install time, so upstream template drift fails loudly instead of
    silently no-op'ing.
4.  Load the five usine role configs (config/roles-usine/*.yaml), normalize
    the deferred verifier-config paths against THIS directory, and validate
    the decided model lineup fail-closed (no model outside the approved
    slugs; escalated seats recomputed exactly like core.loop.escalation_cfg).
5.  Resolve LLM endpoints IN MEMORY from the host credential store
    (provider.* then custom_provider.*; apiKey/baseURL per provider options).
    Key values never enter logs, manifests, or errors.
6.  Preflight prints a readiness payload and writes NOTHING (no endpoints
    file, no run root, no corpus).  Execute requires the exact ack token.
7.  The run root lives OUTSIDE every repository; endpoints.json is generated
    there and pointed at via RSIAGENT_LLM_ENDPOINTS_FILE before any LLM call.
8.  Fresh runs build the instruction corpus from the distribution; resumes
    merge pending waves, then require the corpus to EQUAL a fresh rebuild
    from the distribution.  The corpus is FIXED for the whole run: stock
    Phase 1 feeds every prior project text verbatim back into later
    Curriculum prompts (previous_wave_outcomes -> _outcome_text) while
    _audit_prompt authorizes only the target direction, so any mid-run
    corpus growth would trip the boundary at the next wave's FIRST
    authoring segment.
9.  Before anything is written or spent, _check_distribution_fences proves
    the distribution's 8-gram shingles are DISJOINT from every text that
    can reach an audited surface: seeded usine tracked text and capture
    member names, the first-party prompt/infra modules
    (explore/core/env/config/llm), this adapter directory (the transport
    note), and the role configs' system_extra.  The stock audit exempts
    only the target direction (wave prompts) or the project instruction
    (captures) - never the distribution - so one shared shingle would trip
    audits on every wave.  Both entrypoints and every resume run the gate
    (resume re-runs it after pending merges, since HEAD moved); a
    collision means the distribution wording must change, never the fence.
10. Fixtures are seeded additively at the capture seam: the first
    ``phase1-project-*`` capture of each wave pushes a git-archive(HEAD) seed
    of the usine prefix into the guest and extracts it over /home/user
    (baseline wins collisions; the Curriculum scaffold is preserved), and the
    captured fixture — the merge baseline — becomes scaffold UNION baseline.
    Candidate captures (``phase1-candidate-*``) and blocked-draft captures
    are never seeded.  Every capture (fixture and candidate alike) prunes the
    regenerable heavy directories (node_modules, dist: _CAPTURE_EXCLUDE_PARTS
    -> provisioning exclude_parts, unanchored at any depth) — what capture
    never picks up, wave_merge.EXCLUDED_PARTS never tries to merge back, and
    the leakage audit never has to scan.
11. Every completed wave merges into the real usine repository through the
    wave-merge event sink (one commit per accepted candidate, one tag per
    wave).  Merged delta paths keep the executable bit when the candidate
    archive carried it or git already tracks the path as 100755
    (bin/feuille.js is the anchor).  The gate ("pnpm verify") runs BEFORE the
    commit; a green merge rebuilds the gitignored dsh-plugin dist/index.mjs,
    so an accepted improvement reaches the `dsh web --patch`-loaded agent
    surface without any extra plumbing.  Publishing stays impossible: the
    VM facade refuses publish-shaped programs before execution.
12. Gate-runnability preflight (gate_preflight) runs on BOTH entrypoints
    before a single token is spent: the gate command must resolve on PATH
    (a Windows .cmd/.bat shim is rejected — the merge spawns the gate with
    shell=False and CreateProcess cannot run shims; install standalone
    pnpm), pnpm-shaped gates need Node >= 24 and pnpm >= 11 plus a
    package.json and an installed tree (--gate-install opts into running
    `pnpm install --frozen-lockfile --prefer-offline`; the read-only
    --preflight report never installs).  A red gate at merge time is a
    data-level gate_rejected — silent total candidate loss — so an
    unrunnable gate must die here, before the wave.
13. The seeded guest is probed once for its toolchain (node/pnpm versions)
    fail-closed before waves spend anything on a guest that cannot even
    attempt the gate.

Improvement directions: the distribution sanctions BOTH the operator-facing
pipeline and the agent surface (the dsh plugin package: tool descriptions,
request schemas, discipline/refusal/approval wording, and the skills howtos
that teach the same surface) — with the guard machinery pinned: approval-gated
tools keep failing closed, publishing stays unreachable by default, and the
red-line/parity suites may be extended but never relaxed.

Wave-host readiness checklist (SKIP is not PASS — run the checklist on the
host that will drive the wave, before the first real wave there):

Both hosts additionally require the harness ``link:`` anchor: a
``deepseek-harness`` checkout five levels above the usine tree (what the
dsh-plugin ``link:`` devDependencies resolve against:
``vendor/cordis`` + ``packages/core/tools``).  The guest copy of the
tree is deeper, so the VM factory (``_harness_staging_vm_factory``)
stages the harness checkout root as a single symlink at every guest
disk root (a copy breaks the checkout's internal symlink closure; the
worktree guest is a path-REWRITE illusion, not an OS sandbox - guest
programs already resolve any absolute host path, and the publish/login
red lines are enforced by the VM facade and gates, not filesystem
isolation); without the real checkout to link to, guest creation fails
closed BEFORE any token is spent (every wave would be structurally
doomed to a gate-red typecheck).

Windows wave host:
  * toolchain: standalone pnpm.exe (NOT an npm shim) + Node >= 24 on PATH,
    warm pnpm store or network for the first install; GNU coreutils inside
    the guest (sha256sum/stat -c for capture replay).
  * smokes (theâtre venv, PowerShell): smoke_verifier_adapter.py,
    smoke_guest_env.py — plus re-running the POSIX-runnable set
    (wave_merge / usine_hooks / distribution_fence) and the provisioning
    engine tests, whose 3 broken-symlink replay cases need GNU coreutils.
    (smoke_dry_run_wave.py was retired 2026-10-19 by user decision:
    real waves only.)
  * probe_env.py for the guest-side node/pnpm probe.
  * first real wave: only on explicit user go ("喊跑才跑").

POSIX dev host (macOS), same loop through the POSIX substrate branch:
  * toolchain: brew coreutils (the guest PATH gets the gnubin overlay;
    guest_env fails closed without GNU stat/timeout) + the gnubin export
    in ~/.bash_profile for bash login shells (engine replay tests run
    bash -lc and macOS path_helper demotes a mere PATH prefix),
    standalone pnpm + Node >= 24 on PATH (pnpm must not be an npm shim).
  * smokes (théâtre venv): the two substrate smokes
    (smoke_guest_env / smoke_verifier_adapter) plus
    the POSIX-runnable set and the provisioning engine tests — with
    coreutils installed the 3 broken-symlink replay cases pass here too.
  * probe_env.py remains Windows-specific; the POSIX guest toolchain probe
    is the in-seed node/pnpm check run_usine does itself.
  * first real wave: only on explicit user go ("喊跑才跑").

Red lines: zero live platform publishing/login (three layers: VM facade,
guest-home USERPROFILE/HOME pin, offline-only gates); one commit per accepted
candidate; every wave tagged theatre/wave-N; no push; zero H3/mcode-tools
credit-spending calls outside an explicit per-call human approval.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import gzip
import hashlib
import io
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

log = logging.getLogger("rsiagent.usine.run")

_HERE = Path(__file__).resolve().parent
_EXPLORATEUR_ROOT = _HERE.parents[0]
DEFAULT_THEATRE = _EXPLORATEUR_ROOT / "théâtre"
DEFAULT_USINE_DIR = _EXPLORATEUR_ROOT / "usine"
DEFAULT_RUNS_ROOT = (_EXPLORATEUR_ROOT.parents[0]
                     / "theatre-usine-runs")
DEFAULT_LLM_CONFIG = _EXPLORATEUR_ROOT / "config" / ".env"
DEFAULT_DISTRIBUTION = _HERE / "distribution-usine.md"
# TS 迁移（usine P0-P8）后的门禁：pnpm verify（typecheck + vitest 全量）。
# 真 wave 跑之前须在驱动宿主（Windows wave host 或 POSIX 宿主）落实的前置条件：
# Node >= 24 + pnpm 11（Windows 上须 standalone 安装，.cmd shim 会被 merge 的
# 无 shell subprocess 拒掉）；首跑 pnpm install 需网络（或暖 pnpm store）；
# POSIX 宿主另需 brew coreutils（guest PATH 走 gnubin overlay）。node_modules/
# dist 落树内——capture 与合并两侧现已对称剪枝（provisioning.exclude_parts +
# wave_merge.EXCLUDED_PARTS），门禁可跑性由 gate_preflight 在花任何额度之前
# fail-closed 预检（真 wave 仍喊跑才跑）。
DEFAULT_GATE_ARGV = ("pnpm", "verify")

# ---------------------------------------------------------- gate preflight

def _posix_host_no_browser() -> None:
    """POSIX only: default this orchestrator to a browserless host policy.

    On macOS every Chromium launch writes a per-launch GUID-named keychain
    item and pops a keychain prompt on the user's screen (see
    guest_env._disable_in_guest_browser for the full measurement record) —
    no flag, shim, or pre-authorization suppresses it.  The guest already
    exports a no-browser sentinel; the host-side merge gate
    (wave_merge.run_gate inherits this process's environment) must not
    undo that policy by resolving the real Edge out of its candidate list.
    setdefault keeps an operator's explicit FEUILLE_BROWSER (a deliberate
    browserful run) authoritative.  Windows is untouched: its Chromium
    uses DPAPI, and the Windows wave host owns the real browser coverage.
    """
    if sys.platform == "win32":
        return
    os.environ.setdefault(
        "FEUILLE_BROWSER",
        str(_HERE / ".no-browser-on-this-posix-host"))


_NODE_MIN_MAJOR = 24
_PNPM_MIN_MAJOR = 11
_PNPM_NAMES = frozenset({"pnpm", "pnpm.exe", "pnpm.cmd", "pnpm.bat"})


def _command_version(argv0: str) -> str | None:
    """First line of ``<argv0> --version``, or None when it cannot run."""
    try:
        proc = subprocess.run(
            [argv0, "--version"], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    return text.splitlines()[0] if text else None


def _version_major(version: str | None) -> int | None:
    match = re.search(r"(\d+)", version or "")
    return int(match.group(1)) if match else None


def gate_preflight(usine_dir: Path, gate_argv: tuple,
                   *, allow_install: bool = False) -> dict:
    """Fail-closed gate-runnability preflight; {ok: bool, ...}.

    A red gate at merge time is a data-level ``gate_rejected`` — the whole
    candidate is lost with no retry.  A gate that cannot run AT ALL (missing
    toolchain, .cmd shim, uninstalled tree) must therefore be caught here,
    BEFORE a single token is spent, not after a wave's worth of Actor work.

    Pnpm-shaped gates additionally require Node >= 24 and pnpm >= 11 on
    PATH (the documented wave-host prerequisites), a package.json at the
    usine root, and an installed tree; ``allow_install`` opts into running
    ``pnpm install --frozen-lockfile --prefer-offline`` right here."""
    argv0 = str(gate_argv[0])
    errors: list[str] = []
    actions: list[str] = []
    info: dict = {"gate_argv": [str(a) for a in gate_argv]}
    resolved = shutil.which(argv0)
    if resolved is None:
        errors.append(f"gate command {argv0!r} was not found on PATH")
    elif os.path.basename(resolved).lower().endswith((".cmd", ".bat")):
        # Windows trap: the merge runs the gate with shell=False; CreateProcess
        # executes .exe, not .cmd shims — an npm-installed pnpm.cmd would die
        # as an unrunnable gate AFTER the wave, i.e. silent candidate loss.
        errors.append(
            f"{argv0!r} resolves to {resolved!r}: a .cmd/.bat shim cannot "
            "be spawned by the merge's shell-less subprocess — install the "
            "standalone pnpm (pnpm.exe) from the official installer")
    else:
        info["gate_resolved"] = resolved
        version = _command_version(argv0)
        info["gate_version"] = version
        if version is None:
            errors.append(
                f"gate command {argv0!r} was found but --version failed to run")
    if os.path.basename(argv0).lower() in _PNPM_NAMES:
        node_version = _command_version("node") if shutil.which("node") \
            else None
        info["node_version"] = node_version
        if node_version is None:
            errors.append(
                "node was not found on PATH: the pnpm gate needs "
                f"Node >= {_NODE_MIN_MAJOR} (wave-host prerequisite)")
        elif (_version_major(node_version) or 0) < _NODE_MIN_MAJOR:
            errors.append(
                f"node {node_version} is too old: the pnpm gate needs "
                f"Node >= {_NODE_MIN_MAJOR}")
        pnpm_version = info.get("gate_version")
        if pnpm_version is not None \
                and (_version_major(pnpm_version) or 0) < _PNPM_MIN_MAJOR:
            errors.append(
                f"pnpm {pnpm_version} is too old: pnpm >= {_PNPM_MIN_MAJOR} "
                "is required (workspace lockfile format)")
        if not (usine_dir / "package.json").is_file():
            errors.append(
                f"{usine_dir} has no package.json: --usine-dir must name the "
                "pnpm workspace root of the TS monorepo")
        else:
            installed = (usine_dir / "node_modules").is_dir()
            if not installed and allow_install:
                log.info("gate preflight: tree not installed; running "
                         "pnpm install --frozen-lockfile --prefer-offline")
                try:
                    proc = subprocess.run(
                        [argv0, "install", "--frozen-lockfile",
                         "--prefer-offline"], cwd=str(usine_dir),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=1800, check=False)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(f"pnpm install failed to start: {exc}")
                    proc = None
                if proc is not None:
                    tail = proc.stdout.decode("utf-8", "replace")[-800:]
                    info["install_exit"] = proc.returncode
                    if proc.returncode != 0:
                        errors.append(
                            f"pnpm install exited {proc.returncode}; tail: "
                            f"{tail!r}")
                    else:
                        actions.append(
                            "ran pnpm install --frozen-lockfile "
                            "--prefer-offline")
                        installed = (usine_dir / "node_modules").is_dir()
                        if not installed:
                            errors.append(
                                "pnpm install exited 0 but node_modules is "
                                "still absent")
            if not installed and not allow_install:
                errors.append(
                    "the usine tree is not installed (no node_modules): run "
                    "`pnpm install --frozen-lockfile --prefer-offline` from "
                    f"{usine_dir} — or pass --gate-install to let the "
                    "preflight install it")
    return {"ok": not errors, "errors": errors, "actions": actions, **info}



EXECUTE_ACK = "RUN-USINE-PHASE1-WAVES"
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]+\Z")
# The approved usine lineup.  Anything outside this set fails closed before a
# single token is spent (user constraint: the 2026-10-19 reseating moved every
# usine seat onto the fuyao pair; the MiniMax pair left the lineup).
ALLOWED_MODEL_SLUGS = frozenset({
    "fuyao-work",
    "fuyao-coding",
})

ROLE_FILES = {
    "actor": "actor-usine.yaml",
    "verifier": "verifier-usine.yaml",
    "verifier_control": "target-usine.yaml",
    "curriculum": "curriculum-usine.yaml",
    "memory_actor": "actor-usine.yaml",
}

signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))


# ---------------------------------------------------------------- io helpers

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    os.replace(temporary, path)


def _append_event(path: Path, event_type: str, *, status: str,
                  state: dict, payload: dict) -> None:
    record = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": event_type,
        "status": status,
        "state": state,
        "payload": payload,
    }
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True)
                     + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _parse_checkpoints(value: str, budget: int) -> tuple[int, ...]:
    try:
        checkpoints = tuple(sorted(set(
            int(item.strip()) for item in value.split(",") if item.strip())))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "checkpoints must be comma-separated integers") from exc
    if any(index < 0 or index > budget for index in checkpoints):
        raise argparse.ArgumentTypeError(
            "checkpoints must lie between zero and the project budget")
    return checkpoints


def _safe_phase_root(runs_root: str, name: str) -> Path:
    if not _SAFE_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError("--run-name must be one safe basename")
    base = Path(runs_root).expanduser().resolve(strict=False)
    root = (base / name / "phase1").resolve(strict=False)
    if root.parents[1] != base:
        raise ValueError("Phase-1 result root escapes the runs root")
    return root


def _resolve_input_file(value: str, *, repo_root: Path) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else repo_root / raw
    if candidate.is_symlink():
        raise RuntimeError(f"input path may not be a symlink: {candidate}")
    path = candidate.resolve(strict=True)
    if not path.is_file():
        raise RuntimeError(f"input path is not one file: {path}")
    return path


def _install_paths() -> Path:
    theatre = DEFAULT_THEATRE.resolve(strict=True)
    if not (theatre / "core" / "actor.py").is_file():
        raise RuntimeError(f"théâtre checkout is missing core/: {theatre}")
    for path in (str(theatre), str(_HERE)):
        if path not in sys.path:
            sys.path.insert(0, path)
    return theatre


# ------------------------------------------------- actor system-prompt patch

# Exact stock substrings (core/actor.py _SYSTEM_TEMPLATE + the two look
# bullets, backslash continuations already collapsed).  Shared seams occur
# once in BOTH stock variants; each look bullet is exclusive to its variant.
_TASK_LINE_OLD = ("You solve ONE task on a real Ubuntu machine by WRITING "
                  "PROGRAMS.")
# Substrate-true per host: the Windows wave host drives git-bash, POSIX
# dev hosts (macOS) drive plain bash.  The replacement text is
# platform-branched so the patched prompt never lies about the machine.
_TASK_LINE_NEW = (
    ("You solve ONE task on a real Windows machine driven "
     "through git-bash by WRITING PROGRAMS.")
    if os.name == "nt" else
    ("You solve ONE task on a real POSIX machine (macOS) driven "
     "through bash by WRITING PROGRAMS."))
_MACHINE_FACTS_OLD = ("MACHINE FACTS: Ubuntu with python3. You may install "
                      "tools you need (pip3 / apt-get).")
# Honest replacement: the théâtre venv has NO pip (probe-verified on both
# hosts), and installing packages is not part of this environment — brew
# exists on the POSIX host PATH but must not be used.
_MACHINE_FACTS_NEW = (
    ("MACHINE FACTS: Windows host driven through git-bash "
     "with python3. Installing packages is NOT available "
     "here (no pip3, no apt-get); work with the tools "
     "already on the machine. There is no systemd and no "
     "GUI desktop.")
    if os.name == "nt" else
    ("MACHINE FACTS: macOS host driven through bash "
     "with python3 (no pip). Installing packages is NOT available "
     "here; work with the tools already on the machine — brew exists "
     "but must not be used to install anything. There is no systemd "
     "and no GUI desktop."))
_NATIVE_LOOK_OLD = (
    'You may look directly at a DOCUMENT file (it is rendered to an image '
    'for you) and at the LIVE SCREEN with path "screen:" (the running '
    'desktop/GUI state).')
_BLIND_LOOK_OLD = (
    'You may look directly at a DOCUMENT file (it is rendered to an image '
    'for you \u2014 no need to convert it first) and at the LIVE SCREEN '
    'with path "screen:" (the running desktop/GUI state, when the result '
    'you must judge is on screen rather than in a file).')
# Substrate-true for both variants: image-file Looks still work (pixels are
# read host-side), but there is no document renderer and no live screen.
_LOOK_NEW = (
    'There is no rendered-document channel and no live screen on this '
    'machine: "screen:" is unavailable, and documents are not rendered to '
    'images. Read every file (documents included) by WRITING PROGRAMS that '
    'open and read it.')

_USINE_PROMPT_REPLACEMENTS = (
    (_TASK_LINE_OLD, _TASK_LINE_NEW),
    (_MACHINE_FACTS_OLD, _MACHINE_FACTS_NEW),
    (_NATIVE_LOOK_OLD, _LOOK_NEW),
    (_BLIND_LOOK_OLD, _LOOK_NEW),
)

if os.name == "nt":
    _USINE_TRANSPORT_NOTE = """
USINE TRANSPORT FACTS (Windows git-bash guest):
- Your programs are delivered through a base64 envelope and executed with
  "python3 -u" (python) or "bash" (bash); nothing rewrites paths inside your
  program text.
- PYTHON programs: the canonical paths work as-is - /home/user (your home),
  /home/user/evolution_project (the project root), /tmp, /dev/shm.
- BASH programs: literal /home/user and /dev/shm resolve to the bash
  installation's own directories, NOT to your guest tree - use $HOME or ~
  (your home directory) instead. For scratch space in bash use $HOME too
  (e.g. "$HOME/scratch"); a literal /tmp in bash resolves through a mount
  shared by other processes and is NOT reliable in your guest.
"""
else:
    # POSIX twin: the Windows note's PYTHON paragraph is FALSE here - a
    # literal canonical path inside program text resolves against the REAL
    # host root (no per-drive resolution), so both languages must use
    # $HOME/~.  The gate/pnpm/node_modules paragraphs are shared verbatim.
    _USINE_TRANSPORT_NOTE = """
USINE TRANSPORT FACTS (POSIX bash guest on a macOS host):
- Your programs are delivered through a base64 envelope and executed with
  "python3 -u" (python) or "bash" (bash); nothing rewrites paths inside your
  program text.
- Program paths: a LITERAL /home/user, /tmp or /dev/shm inside your program
  text resolves against the REAL host root, NOT against your guest tree -
  in Bash AND in Python alike. Reach your files through $HOME or ~ (your
  home directory; Python: os.path.expanduser), so $HOME/evolution_project
  is the project root and "$HOME/scratch" is scratch space; /dev/shm exists
  in your guest.
"""

_USINE_TRANSPORT_NOTE += """
- The offline verification gate is "pnpm verify" (a TypeScript pnpm
  monorepo: typecheck plus every vitest suite), run from the project root
  after a one-time "pnpm install":
    bash:   cd "$HOME/evolution_project" && pnpm install && pnpm verify
  Node 24+ and pnpm 11 must be on PATH. The first install fills the pnpm
  store (needs network once); later runs reuse it. Never edit anything
  under node_modules - it is installed material, not work.
  EACH of your programs is limited to 600 seconds (the in-guest kill fires
  30 seconds earlier and the partial output survives): run the one-time
  "pnpm install" and the later "pnpm verify" as SEPARATE programs, never
  as one chained command - an install-then-verify chain risks the kill in
  the middle of the suite.
  node_modules and dist are NOT part of your captured work: the capture
  prunes them by name at any depth, and the merge side prunes them too.
  They are fully regenerable (pnpm install / build) and are rebuilt
  automatically after a green merge - spend your turns on tracked source,
  never on them.
  "pnpm vitest run packages/<pkg>" runs one package's suite. Live platform
  publishing and platform login never run in this environment: those
  programs are refused before execution, so develop and verify offline only."""


def _install_actor_prompt_patch() -> None:
    """Wrap core.actor/core.loop build_system with substrate-true text.

    Fail-closed at install time: every seam substring is pinned against both
    stock variants (native build_system(None) and a blind probe cfg), and the
    patched products must carry each replacement exactly once.  Upstream
    template drift therefore raises instead of silently no-op'ing.
    """
    import core.actor as actor_mod
    import core.loop as loop_mod

    stock = actor_mod.build_system
    blind_probe = SimpleNamespace(
        vision_model="usine-seam-probe", system_extra="", action_discipline=False)
    native = stock(None)
    blind = stock(blind_probe)
    for old, _new in _USINE_PROMPT_REPLACEMENTS[:2]:
        if native.count(old) != 1 or blind.count(old) != 1:
            raise RuntimeError(
                "usine actor-prompt seam drifted (shared): " + old[:48])
    if (native.count(_NATIVE_LOOK_OLD) != 1
            or _NATIVE_LOOK_OLD in blind):
        raise RuntimeError("usine actor-prompt seam drifted (native look)")
    if (blind.count(_BLIND_LOOK_OLD) != 1
            or _BLIND_LOOK_OLD in native):
        raise RuntimeError("usine actor-prompt seam drifted (blind look)")

    def usine_system(cfg=None, *, ask_enabled: bool = False) -> str:
        text = stock(cfg, ask_enabled=ask_enabled)
        for old, new in _USINE_PROMPT_REPLACEMENTS:
            text = text.replace(old, new)
        return text + _USINE_TRANSPORT_NOTE

    patched_native = usine_system(None)
    patched_blind = usine_system(blind_probe)
    if (patched_native.count(_TASK_LINE_NEW) != 1
            or patched_native.count(_MACHINE_FACTS_NEW) != 1
            or patched_native.count(_LOOK_NEW) != 1
            or patched_native.count(_TASK_LINE_OLD)
            or patched_native.count(_MACHINE_FACTS_OLD)
            or patched_native.count(_NATIVE_LOOK_OLD)):
        raise RuntimeError("usine native actor patch did not apply cleanly")
    if (patched_blind.count(_LOOK_NEW) != 1
            or patched_blind.count(_BLIND_LOOK_OLD)
            or patched_blind.count(_TASK_LINE_OLD)
            or patched_blind.count(_MACHINE_FACTS_OLD)):
        raise RuntimeError("usine blind actor patch did not apply cleanly")

    actor_mod.build_system = usine_system
    loop_mod.build_system = usine_system
    log.info("actor system prompt patched for the usine substrate "
             "(core.actor + core.loop)")


# ---------------------------------------------------------------- role configs

def _load_roles():
    """Load the five usine role configs and validate the decided lineup."""
    from config.runtime_paths import normalize_verifier_config_paths, resolve_path
    from config.settings import load

    paths, configs = {}, {}
    for role, name in ROLE_FILES.items():
        path = resolve_path(
            Path("config") / "roles-usine" / name, repo_root=_HERE)
        if not path.is_file():
            raise RuntimeError(f"usine role config is missing: {path}")
        cfg = load(str(path))
        normalize_verifier_config_paths(cfg, _HERE)
        paths[role] = path
        configs[role] = cfg

    # Stock Phase-1 practice invariants for the four agent seats.
    for role in ("actor", "verifier", "curriculum", "memory_actor"):
        cfg = configs[role]
        if (not cfg.agent_decided_stop or not cfg.practice_mode
                or cfg.independent_verify or cfg.max_resumes != 0):
            raise RuntimeError(
                f"usine Phase-1 {role} must use Agent-owned practice mode")
    if configs["memory_actor"].model != configs["actor"].model:
        raise RuntimeError(
            "memory writing must continue with the same Actor Agent model")

    control = configs["verifier_control"]
    for attribute in ("agentic_verifier_config",
                      "escalation_agentic_verifier_config"):
        value = getattr(control, attribute, "")
        if not value or not Path(value).is_file():
            raise RuntimeError(
                f"control.{attribute} does not resolve to a file: {value!r}")
    escalation_cfg = load(str(control.escalation_agentic_verifier_config))
    if (not escalation_cfg.practice_mode or escalation_cfg.independent_verify
            or escalation_cfg.max_resumes != 0):
        raise RuntimeError(
            "escalated verifier seat must use Agent-owned practice mode")
    return configs, paths, escalation_cfg


def _check_lineup(configs: dict, escalation_cfg) -> dict:
    """Fail closed on any drift from the decided usine model lineup."""
    actor = configs["actor"]
    curriculum = configs["curriculum"]
    verifier = configs["verifier"]
    control = configs["verifier_control"]

    # 2026-10-18 lineup switch (user decision): M3 actor thrashed on wave-1r
    # (220+ iters, one 570s timeout with 25 MB stdout); the Actor and its
    # memory twin move to fuyao-coding.  2026-10-19 reseating (user decision):
    # the control seat moves to fuyao-coding as well and the MiniMax pair
    # leaves the lineup entirely; the control seat remains the
    # escalated-verifier fallback and the vision / cross-model invariants
    # below are pinned to the fuyao pair.
    if actor.model != "fuyao-coding":
        raise RuntimeError("usine Actor Agent must be fuyao-coding")
    if actor.vision_model != "":
        raise RuntimeError("usine Actor Agent must use native vision")
    if curriculum.model != "fuyao-work":
        raise RuntimeError("usine Curriculum Agent must be fuyao-work")
    if curriculum.vision_model != "fuyao-coding":
        raise RuntimeError("usine Curriculum eyes must be fuyao-coding")
    if verifier.model != "fuyao-work":
        raise RuntimeError(
            "usine Agentic Verifier must be fuyao-work")
    if verifier.vision_model != "":
        raise RuntimeError("usine Agentic Verifier must use native vision")
    if control.model != "fuyao-coding":
        raise RuntimeError("usine control Actor seat must be fuyao-coding "
                           "(the escalated verifier falls back to it)")
    if control.verifier_model != "fuyao-work":
        raise RuntimeError("usine control verifier_model drifted")
    if control.escalation_model != "fuyao-work":
        raise RuntimeError("usine control escalation_model drifted")
    if control.vision_model != control.escalation_model:
        raise RuntimeError(
            "control.vision_model must equal escalation_model so the "
            "escalated Actor keeps native vision")
    if not control.escalation_verifier_cross_model:
        raise RuntimeError("control.escalation_verifier_cross_model must be "
                           "true (xverify: no escalated self-review)")
    if not control.independent_verify or control.verifier_stage_lifecycle:
        raise RuntimeError("usine candidate-only control profile drifted")
    if control.verifier_execution_mode != "rollback_mirror":
        raise RuntimeError("usine control must use the rollback_mirror "
                           "execution boundary")
    if not control.verifier_hide_actor_memory:
        raise RuntimeError("usine control must hide Actor memory")

    # Mirror core.loop.escalation_cfg math exactly and pin the result.
    esc_verifier = control.verifier_model or control.model
    if (control.escalation_verifier_cross_model
            and esc_verifier == control.escalation_model):
        esc_verifier = control.model
    esc_vision = ("" if (control.vision_model
                         and control.escalation_model == control.vision_model)
                  else control.vision_model or control.model)
    if esc_verifier != "fuyao-coding" or esc_vision != "":
        raise RuntimeError(
            f"escalated seats drifted: verifier={esc_verifier!r} "
            f"vision={esc_vision!r}")
    if escalation_cfg.model != esc_verifier:
        raise RuntimeError(
            "escalation verifier config must seat the computed cross-model "
            f"verifier ({esc_verifier})")
    if escalation_cfg.vision_model != "":
        raise RuntimeError("escalated verifier seat must use native vision")

    used = {
        value for value in (
            configs["actor"].model, configs["actor"].vision_model,
            configs["memory_actor"].model, configs["memory_actor"].vision_model,
            curriculum.model, curriculum.vision_model,
            verifier.model, verifier.vision_model,
            control.model, control.verifier_model,
            control.escalation_model, control.vision_model,
            escalation_cfg.model, escalation_cfg.vision_model,
            esc_verifier, esc_vision)
        if value}
    unknown = sorted(value for value in used
                     if value not in ALLOWED_MODEL_SLUGS)
    if unknown:
        raise RuntimeError(
            f"model outside the approved usine lineup: {unknown}")
    return {"esc_actor": control.escalation_model,
            "esc_verifier": esc_verifier,
            "esc_vision": esc_vision,
            "used_models": sorted(used)}


# ---------------------------------------------------------------- credentials

def _resolve_endpoints(llm_config_path: Path, needed: set) -> dict:
    """Map every needed model slug to its provider credentials, in memory.

    Reads the unified explorateur ``config/.env`` (flat KEY=VALUE lines).
    Variable names are the slug uppercased with non-alphanumerics replaced by
    ``_``.  Slugs sharing one gateway collapse onto a **group pair**: the
    longest sanitized-stem prefix that has both fields wins, so
    ``LLM_FUYAO_*`` alone serves ``fuyao-work`` / ``fuyao-coding`` /
    ``fuyao-data``, and ``LLM_MINIMAX_*`` alone serves every MiniMax slug;
    a per-slug pair (``LLM_FUYAO_WORK_*``) overrides its group.  A prefix
    level registers only when both fields are non-empty (no mixing levels).
    Fail-closed on any needed slug with no complete pair — the error names
    the exact variables to fill.  Key values never enter logs, errors, or
    the preflight payload.
    """
    path = Path(llm_config_path).expanduser()
    if not path.is_file():
        raise RuntimeError(f"LLM credential config not found: {path}")
    entries: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and value:
            entries[name] = value

    def _slug_var(slug: str, field: str) -> str:
        stem = re.sub(r"[^A-Za-z0-9]", "_", slug).upper()
        return f"LLM_{stem}_{field}"

    def _slug_stems(slug: str) -> list[str]:
        # Longest sanitized-stem prefix first; the full stem (per-slug pair)
        # outranks every group prefix (LLM_FUYAO_WORK_* over LLM_FUYAO_*).
        parts = re.sub(r"[^A-Za-z0-9]", "_", slug).upper().split("_")
        return ["_".join(parts[:i]) for i in range(len(parts), 0, -1)]

    needed = set(needed)
    found: dict[str, dict[str, str]] = {}
    for slug in needed:
        for stem in _slug_stems(slug):
            base_url = entries.get(f"LLM_{stem}_BASE_URL", "")
            api_key = entries.get(f"LLM_{stem}_API_KEY", "")
            if base_url and api_key:
                found[slug] = {"base_url": base_url, "api_key": api_key}
                break
    missing = sorted(needed - found.keys())
    if missing:
        def _hint(slug: str) -> str:
            stem = re.sub(r"[^A-Za-z0-9]", "_", slug).upper()
            pair = f"LLM_{stem}_BASE_URL + LLM_{stem}_API_KEY"
            group = stem.split("_")[0]
            if group == stem:
                return f"{slug} (fill {pair})"
            return (f"{slug} (fill {pair}, or group pair "
                    f"LLM_{group}_BASE_URL + LLM_{group}_API_KEY)")
        raise RuntimeError(
            "no credentials found for model(s): "
            + ", ".join(_hint(slug) for slug in missing)
            + f" in {path}")
    log.info("resolved LLM endpoints for %d model slug(s)", len(found))
    return found


# ------------------------------------------------------------------- seeding

def _lfs_smudge_overlay(usine_dir) -> dict[str, Path]:
    """LFS-tracked files under the usine prefix -> smudged working-tree
    paths, keyed by prefix-relative posix path.

    ``git archive`` carries LFS-tracked binaries as POINTER text, but the
    usine gate probes its gold assets with real ffprobe/sharp - a pointer
    file is not a valid mp3/png and the gate goes red for a seeding
    reason on EVERY host.  Seed and fixture builders overlay the real
    bytes for exactly these members (the tree is asserted clean, so the
    smudged working-tree bytes ARE the committed content).  Fails closed
    when the local checkout still holds pointer text (a clone without
    ``git lfs pull``): the gold-dependent gate cannot honestly pass
    there, and a seeding that silently ships pointers would be
    fabricating a green-looking red.
    """
    import wave_merge

    ctx = wave_merge._repo_context(Path(usine_dir))
    prefix = str(ctx["prefix"])
    base = prefix if prefix.endswith("/") else prefix + "/"
    ls_argv = ["git", "-C", ctx["toplevel"], "ls-files", "-z"]
    if prefix:
        ls_argv += ["--", base]
    ls = subprocess.run(ls_argv, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=300)
    if ls.returncode != 0:
        raise RuntimeError("git ls-files for the LFS overlay failed: "
                           + ls.stderr.decode("utf-8", "replace")[:300])
    paths = [p for p in ls.stdout.split(b"\0") if p]
    if not paths:
        return {}
    ca = subprocess.run(
        ["git", "-C", ctx["toplevel"], "check-attr", "-z", "--stdin",
         "filter"],
        input=b"\0".join(paths), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=300)
    if ca.returncode != 0:
        raise RuntimeError("git check-attr for the LFS overlay failed: "
                           + ca.stderr.decode("utf-8", "replace")[:300])
    overlay: dict[str, Path] = {}
    fields = ca.stdout.split(b"\0")
    for i in range(0, len(fields) - 2, 3):
        path_b, attr, value = fields[i], fields[i + 1], fields[i + 2]
        if attr != b"filter" or value != b"lfs":
            continue
        rel = path_b.decode("utf-8", "surrogateescape")
        key = rel[len(base):] if prefix else rel
        worktree = Path(ctx["toplevel"]).joinpath(*PurePosixPath(rel).parts)
        if not worktree.is_file():
            raise RuntimeError(
                f"LFS-tracked gold file is missing from the working tree: "
                f"{rel}")
        with worktree.open("rb") as handle:
            if handle.read(64).startswith(b"version https://git-lfs"):
                raise RuntimeError(
                    f"LFS-tracked gold file is un-smudged pointer text: "
                    f"{rel}; run `git lfs pull` before driving a wave "
                    "(the gate probes these assets with real "
                    "ffprobe/sharp)")
        overlay[key] = worktree
    if overlay:
        log.info("LFS gold overlay: %d file(s) smudged from the working "
                 "tree", len(overlay))
    return overlay


def _build_seed(usine_dir: Path, write_to: Path | None) -> dict:
    """git-archive the committed usine prefix into an evolution_project seed.

    The seed is the honest baseline: ``git archive HEAD -- <prefix>`` of the
    real usine repository (tracked content only, committed state only).
    Member names are rewritten ``<prefix>/<rel>`` -> ``evolution_project/
    <rel>``; directory members are dropped (extraction creates parents) and
    non-regular members are skipped and counted (symlinks have no faithful
    Windows guest semantics).  LFS-tracked members are overlaid with their
    smudged working-tree bytes (git archive ships pointer text, the gate
    probes the gold assets for real).  With ``write_to`` the compressed
    seed is written atomically next to a manifest; without it nothing is
    written (preflight preview).
    """
    import wave_merge

    usine_dir = Path(usine_dir)
    ctx = wave_merge._repo_context(usine_dir)
    head = wave_merge._assert_preconditions(ctx, usine_dir)
    prefix = str(ctx["prefix"])
    base = prefix if prefix.endswith("/") else prefix + "/"
    argv = ["git", "-C", ctx["toplevel"], "archive", "--format=tar", "HEAD"]
    if prefix:
        argv += ["--", base]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git archive could not run: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            "git archive HEAD failed (exit "
            f"{proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:300]}")

    out = io.BytesIO()
    files = 0
    skipped = 0
    lfs_files = _lfs_smudge_overlay(usine_dir)
    lfs_overlaid = 0
    with (tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as src,
          tarfile.open(fileobj=out, mode="w",
                       format=tarfile.GNU_FORMAT) as dst):
        for member in src:
            if member.isdir():
                # git archive also emits the pathspec directory itself
                # ("usine/"); extraction creates parents, so skip all dirs.
                continue
            name = PurePosixPath(member.name).as_posix()
            if prefix:
                if not name.startswith(base):
                    raise RuntimeError(
                        f"seed archive member outside the prefix: {member.name!r}")
                rel = name[len(base):]
            else:
                rel = name
            if not rel or rel.endswith("/"):
                continue
            if not member.isfile():
                skipped += 1
                continue
            fresh = copy.copy(member)
            fresh.name = "evolution_project/" + rel
            overlay_path = lfs_files.get(rel)
            if overlay_path is not None:
                payload = overlay_path.read_bytes()
                fresh.size = len(payload)
                dst.addfile(fresh, io.BytesIO(payload))
                lfs_overlaid += 1
            else:
                dst.addfile(fresh, src.extractfile(member))
            files += 1
    if not files:
        raise RuntimeError("the usine seed would be empty")
    data = gzip.compress(out.getvalue(), compresslevel=1, mtime=0)
    sha = hashlib.sha256(data).hexdigest()
    info = {
        "head": head,
        "prefix": prefix or "(repo root)",
        "members": files,
        "skipped_non_regular": skipped,
        "lfs_overlaid": lfs_overlaid,
        "bytes": len(data),
        "sha256": sha,
        "written": False,
        "path": None,
    }
    if write_to is not None:
        seed_dir = Path(write_to) / "baselines"
        seed_dir.mkdir(parents=True, exist_ok=True)
        seed_path = seed_dir / "seed.tgz"
        temporary = seed_path.with_name(seed_path.name + ".rsiagent-part")
        temporary.write_bytes(data)
        os.replace(temporary, seed_path)
        info["written"] = True
        info["path"] = str(seed_path)
        _write_json_atomic(seed_dir / "seed_manifest.json", info)
        log.info("usine seed rebuilt at HEAD %s: %d member(s), %d bytes",
                 head[:10], files, len(data))
    return info


def _stage_harness_link_targets(env, usine_dir) -> None:
    """Stage the out-of-tree ``link:`` devDependencies where the guest tree
    resolves them.

    ``packages/dsh-plugin`` typechecks against two harness packages that
    live OUTSIDE the usine checkout (``link:../../../../../deepseek-harness/
    ...`` devDependencies).  The seeded guest tree sits deeper than the
    real checkout (disk_root/home/user/evolution_project/...), and the
    ``..`` walk from there anchors at the guest disk root on both
    substrates (POSIX: the scratch disk path; Windows: the subst drive
    root) - so the shared harness checkout root must exist there.  It is
    staged as a single symlink (POSIX) to the real checkout, not copied:
    the harness' internal per-package ``node_modules`` are relative
    symlinks into sibling packages, so only the intact checkout resolves
    the full type closure.  This grants no new reach: the worktree guest
    is a path-REWRITE illusion, not an OS sandbox - guest programs
    already resolve any absolute host path, and the publish/login red
    lines are enforced by the VM facade and gates, not by filesystem
    isolation.  Scratch release stays safe: rmtree never follows the
    link (rmtree_force chmods a link's PARENT, never through the link).
    Fail-closed before any token is spent: an unresolvable harness
    checkout means every wave on this host is structurally doomed to a
    gate-red typecheck.
    """
    dsh_dir = Path(usine_dir) / "packages" / "dsh-plugin"
    manifest_path = dsh_dir / "package.json"
    try:
        dev_deps = json.loads(manifest_path.read_text(
            encoding="utf-8")).get("devDependencies", {})
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"cannot read {manifest_path} to resolve the harness link "
            f"dependencies: {exc}") from exc
    disk_root = Path(str(getattr(env, "disk_root", "")))
    if not disk_root.is_dir():
        raise RuntimeError("usine seeding VM has no disk_root to stage "
                           "harness link targets into")
    links = []
    for name, spec in sorted(dev_deps.items()):
        spec = str(spec)
        if not spec.startswith("link:"):
            continue
        rel = PurePosixPath(spec[len("link:"):])
        rel_parts = list(rel.parts)
        anchor_at = next(
            (i for i, p in enumerate(rel_parts) if p != ".."), None)
        if anchor_at is None:
            raise RuntimeError(
                f"harness link dependency {name} has a bare relative "
                f"specifier: {spec!r}")
        if ".." in rel_parts[anchor_at + 1:]:
            raise RuntimeError(
                f"harness link dependency {name} has an unanchored "
                f"relative specifier: {spec!r}")
        # Leading ``..``s are the walk up to the shared checkout parent;
        # everything after them must descend from a single anchor name
        # (the one directory staged at the guest disk root).
        parts = rel_parts[anchor_at:]
        source = (dsh_dir / spec[len("link:"):]).resolve()
        if not (source / "package.json").is_file():
            raise RuntimeError(
                f"harness link dependency {name} does not resolve to a "
                f"package (specifier {spec!r} -> {source}); the guest-side "
                "pnpm gate would be structurally red - stage the harness "
                "checkout the usine tree links against")
        root_source = source
        for _ in parts[1:]:
            root_source = root_source.parent
        links.append((name, parts, root_source))
    staged_roots = 0
    roots_done = set()
    for name, parts, root_source in links:
        dest = disk_root.joinpath(*parts)
        if (dest / "package.json").is_file():
            continue
        root_name = parts[0]
        dest_root = disk_root / root_name
        if root_name not in roots_done:
            roots_done.add(root_name)
            if dest_root.is_symlink() or dest_root.exists():
                raise RuntimeError(
                    f"harness anchor {dest_root} already exists on the "
                    "guest disk but is not the staged link layout")
            if os.name == "nt":
                raise RuntimeError(
                    "harness link-anchor staging needs a directory "
                    "junction on Windows (os.symlink requires elevated "
                    "privileges; _winapi.CreateJunction is the port) - "
                    "port it on the wave host before the first real wave "
                    "there (the guest gate is structurally red without "
                    "the anchor)")
            os.symlink(root_source, dest_root, target_is_directory=True)
            staged_roots += 1
        if not (dest / "package.json").is_file():
            raise RuntimeError(
                f"harness link dependency {name} does not resolve "
                f"through the staged anchor {dest_root} -> {root_source}"
                "; the guest-side pnpm gate would be structurally red")
    if staged_roots:
        log.info("usine harness link anchor staged into the guest disk "
                 "root: %d root(s)", staged_roots)


def _harness_staging_vm_factory(inner_factory, state: dict):
    """Wrap the VM factory: stage the harness ``link:`` anchor for EVERY
    guest, not just the seed-time one.  Later nights (Actor, Verifier,
    memory) replay the captured tree through the engine's provisioning
    stage path, which never passes through ``_seed_guest`` - but every
    guest that replays the usine tree and might run the pnpm gate needs
    the anchor at its own disk root.  Staging is idempotent and skipped
    for non-Worktree VMs (no scratch)."""
    def factory():
        pair = inner_factory()
        vm = pair[1] if isinstance(pair, tuple) else pair
        env = getattr(vm, "env", None)
        scratch = str(getattr(env, "scratch", "")) if env is not None else ""
        if scratch:
            _stage_harness_link_targets(env, state["usine_dir"])
        return pair
    return factory


def _seed_guest(vm, state: dict) -> None:
    """Push + extract the seed into one guest (idempotent per wave VM)."""
    env = getattr(vm, "env", None)
    scratch = str(getattr(env, "scratch", "")) if env is not None else ""
    if not scratch:
        raise RuntimeError(
            "usine seeding requires a WorktreeEnv-backed VM (no scratch)")
    info = state["cache"].get(scratch)
    if info is None:
        info = _build_seed(state["usine_dir"], Path(state["run_root"]))
        state["cache"][scratch] = info
    ok, error = vm.push_file(info["path"], "/dev/shm/usine-seed.tgz")
    if not ok:
        raise RuntimeError(f"usine seed push failed: {error}")
    out = vm.run_command(
        "stat -c %s /dev/shm/usine-seed.tgz; "
        "sha256sum /dev/shm/usine-seed.tgz | cut -d' ' -f1",
        timeout=120) or ""
    lines = [line.strip() for line in out.strip().splitlines()
             if line.strip()]
    if (len(lines) < 2 or lines[0] != str(info["bytes"])
            or lines[1] != info["sha256"]):
        raise RuntimeError("usine seed failed guest size/digest verification")
    # Extract over /home/user WITHOUT wiping: the Curriculum scaffold keeps
    # its task-specific extras and the baseline wins file collisions.
    out = vm.run_command(
        "tar xzf /dev/shm/usine-seed.tgz -C /home/user && "
        "rm -f /dev/shm/usine-seed.tgz; echo USINE_SEED_RC=$?",
        timeout=900) or ""
    if "USINE_SEED_RC=0" not in out:
        raise RuntimeError(f"usine seed extraction failed: {out[-400:]}")
    # Guest toolchain probe: the Actor reaches node only through bash-wrapped
    # pnpm/node programs, so a guest without the toolchain cannot even
    # attempt the gate — probe once per seeded guest, fail-closed BEFORE any
    # token is spent on waves that are structurally doomed to gate-red.
    out = vm.run_command(
        "node --version; pnpm --version; echo USINE_TOOLCHAIN_RC=$?",
        timeout=300) or ""
    lines = [line.strip() for line in out.strip().splitlines()
             if line.strip()]
    if (len(lines) < 3 or lines[-1] != "USINE_TOOLCHAIN_RC=0"):
        raise RuntimeError(
            "guest toolchain probe failed: node/pnpm are not runnable in "
            "the seeded guest (waves need Node >= "
            f"{_NODE_MIN_MAJOR} and pnpm >= {_PNPM_MIN_MAJOR} inside the "
            "guest image); probe tail: " + out[-300:])
    node_major = _version_major(lines[0])
    pnpm_major = _version_major(lines[1])
    if node_major is None or node_major < _NODE_MIN_MAJOR:
        raise RuntimeError(
            f"guest node too old for the pnpm gate: {lines[0]!r} (need "
            f">= {_NODE_MIN_MAJOR})")
    if pnpm_major is None or pnpm_major < _PNPM_MIN_MAJOR:
        raise RuntimeError(
            f"guest pnpm too old for the workspace gate: {lines[1]!r} "
            f"(need >= {_PNPM_MIN_MAJOR})")


# capture 剪枝：guest 工作树里可再生重物不入 capture。usine 是 pnpm TS
# monorepo：node_modules（根 + 每包嵌套，万级符号链接）与 dist（`pnpm test`
# 重建 dsh-plugin 的构建产物）由 install/build 完全再生，不是工作成果；
# build（gitignored 证据/再生输出根，如 publish 测试的 build/publish-verify
# 证据副本）同理——无栏杆时 guest 门禁的未跟踪副作用会混进候选 delta。
# 不剪枝会炸 120s tar 超时/无界 fetch/回放逐文件校验，且未设栏的第三方
# 内容会撑爆 UsineAudit 审计面。与 wave_merge.EXCLUDED_PARTS 同一约定，
# 两头对称：capture 进不来的东西，合并侧也不会试图捡回去。
_CAPTURE_EXCLUDE_PARTS = ("node_modules", "dist", "build")


def _seeded_capture(inner, state: dict):
    """Wrap hooks.capture_project: seed the guest at fixture-capture time only.

    ``phase1-project-*`` captures stage the Curriculum fixture and then
    capture the merge baseline, so the seed merges into the tree right
    here — the captured fixture (and every branch VM replaying it) becomes
    scaffold UNION baseline.  Candidate captures (``phase1-candidate-*``)
    and blocked-draft captures are forwarded untouched.  Every capture —
    fixture and candidate alike — prunes the regenerable heavy directories
    declared in ``_CAPTURE_EXCLUDE_PARTS`` (the engine seam is a no-op when
    the tree carries no such directories, so the pruned fixture and the
    pruned candidate stay symmetric).
    """
    def capture_project(vm, key, host_dir, *args, **kwargs):
        if isinstance(key, str) and key.startswith("phase1-project-"):
            _seed_guest(vm, state)
        kwargs.setdefault("exclude_parts", _CAPTURE_EXCLUDE_PARTS)
        return inner(vm, key, host_dir, *args, **kwargs)
    return capture_project


# -------------------------------------------------------------------- corpus

# The corpus is FIXED for the whole run (distribution shingles only, never
# extended mid-run): stock Phase 1 feeds every prior project text verbatim
# back into later Curriculum prompts while _audit_prompt authorizes only the
# target direction, so per-wave corpus growth would quarantine the next
# wave's first authoring segment.  extend_corpus stays available in
# usine_hooks for operator-driven flows, but this orchestrator never grows
# the corpus between waves.


# ------------------------------------------------------ distribution fence

# First-party packages this run can import: every string literal in them can
# reach an audited surface (system prompts, wave-authoring and verifier
# templates, infra strings replayed into transcripts).  tests/ tools/
# benchmarks/ are never imported by the wave loop and stay out of the fence.
_FENCE_PY_PACKAGES = ("explore", "core", "env", "config", "llm")
_FENCE_BINARY_HEAD = 8192      # mirrors UsineAudit.captured's binary cutoff


def _fence_texts(theatre: Path, usine_dir: Path, stats: dict):
    """Yield (label, text) for every source the fence must clear.

    Mirrors the audit's decode rules exactly: content is decoded
    utf-8/ignore, and a NUL within the first 8 KiB marks a binary member
    whose CONTENT the capture audit skips.  Names stay audited, so the
    rewritten capture member name is yielded for every tracked file.
    """
    import wave_merge

    ctx = wave_merge._repo_context(usine_dir)
    prefix = str(ctx["prefix"])
    base = prefix if prefix.endswith("/") else prefix + "/"
    argv = ["git", "-C", ctx["toplevel"], "ls-files", "-z"]
    if prefix:
        argv += ["--", base]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git ls-files could not run: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            "git ls-files failed (exit "
            f"{proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:300]}")
    tracked = [name for name in
               proc.stdout.decode("utf-8", "surrogateescape").split("\0")
               if name]
    if not tracked:
        raise RuntimeError("the usine prefix has no tracked files to fence")
    stats["usine_tracked"] = len(tracked)
    for name in tracked:
        if prefix:
            if not name.startswith(base):
                raise RuntimeError(
                    f"tracked usine path outside the prefix: {name!r}")
            rel = name[len(base):]
        else:
            rel = name
        # The seed strips the prefix (members are evolution_project/<rel>)
        # and capture member names are audited as text.
        yield "usine:capture-name", "evolution_project/" + rel
        path = Path(ctx["toplevel"]) / name
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"tracked usine file is unreadable: {name}") from exc
        if b"\x00" in data[:_FENCE_BINARY_HEAD]:
            stats["usine_binary_skipped"] += 1
            continue
        yield "usine:seeded-text", data.decode("utf-8", "ignore")
    for package in _FENCE_PY_PACKAGES:
        for path in sorted((theatre / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            stats["theatre_py"] += 1
            yield f"theatre:{package}", path.read_text(
                encoding="utf-8", errors="ignore")
    for path in sorted(_HERE.glob("*.py")):
        stats["adapter_py"] += 1
        yield "adapter:code", path.read_text(encoding="utf-8", errors="ignore")
    for path in sorted((_HERE / "config" / "roles-usine").glob("*.yaml")):
        stats["role_yaml"] += 1
        yield "adapter:role-config", path.read_text(
            encoding="utf-8", errors="ignore")


def _check_distribution_fences(distribution: str, theatre: Path,
                               usine_dir: Path) -> dict:
    """Fail closed unless the distribution is 8-gram-disjoint from every
    text that flows into audited surfaces.

    The corpus IS the distribution's shingles, and the stock audit exempts
    only the target direction (wave prompts) or the project instruction
    (captures) - never the distribution itself: one shared 8-gram with
    seeded usine text, a capture member name, a stock/adapted prompt
    template, a role system_extra, or the transport note would trip audits
    on every wave.  Both entrypoints and every resume run this gate BEFORE
    anything is written or spent; resume re-runs it after pending merges
    too (merged candidates move HEAD, and the next wave captures from the
    new tree).
    """
    import usine_hooks

    grams = usine_hooks._shingles(distribution)
    if not grams:
        raise RuntimeError(
            "the distribution yields no word 8-grams (write it as English "
            "prose: the [a-z0-9]+ tokenizer produces zero shingles from CJK "
            "text, which would silently disable the leakage fence)")
    stats = {"usine_binary_skipped": 0, "theatre_py": 0,
             "adapter_py": 0, "role_yaml": 0}
    collisions: dict = {}
    sources = 0
    for label, text in _fence_texts(theatre, usine_dir, stats):
        sources += 1
        for hit in usine_hooks._shingles(text) & grams:
            collisions.setdefault(hit, set()).add(label)
    if collisions:
        detail = "; ".join(
            f"{sorted(labels)}: {shingle!r}"
            for shingle, labels in sorted(collisions.items())[:5])
        raise RuntimeError(
            f"distribution shares {len(collisions)} instruction shingle(s) "
            f"with audited surfaces - reword the distribution: {detail}")
    result = {"status": "clear", "distribution_shingles": len(grams),
              "audited_sources": sources, **stats}
    log.info("distribution fence clear: %d shingle(s) disjoint from %d "
             "audited source(s) (%d tracked usine file(s), %d binary "
             "skipped)", len(grams), sources, stats["usine_tracked"],
             stats["usine_binary_skipped"])
    return result


# ----------------------------------------------------------------------- CLI

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument(
        "--distribution-file", default=str(DEFAULT_DISTRIBUTION),
        help=("UTF-8 target-direction/distribution description; seeds the "
              "instruction corpus and steers the Curriculum"))
    parser.add_argument(
        "--target-query-conditioned", action="store_true",
        help=("derive diverse Phase-1 exploration from the supplied exact "
              "query; the unchanged target itself remains reserved for "
              "Phase 2"))
    parser.add_argument("--project-budget", type=int, default=8)
    parser.add_argument("--checkpoints", default="0,2,4,8")
    parser.add_argument(
        "--max-parallel", type=int, default=4,
        help=("host scheduling capacity for a Curriculum-authored wave; "
              "this does not prescribe or truncate the wave width"))
    parser.add_argument(
        "--root", default=str(DEFAULT_RUNS_ROOT),
        help=("run-lineage root, OUTSIDE every repository (endpoints.json "
              "with live credentials is generated there)"))
    parser.add_argument("--usine-dir", default=str(DEFAULT_USINE_DIR))
    parser.add_argument(
        "--gate-argv", nargs="+", default=list(DEFAULT_GATE_ARGV),
        help=("the offline verification gate executed from the usine "
              "directory before every merge commit"))
    parser.add_argument("--gate-timeout", type=float, default=1800.0)
    parser.add_argument(
        "--gate-install", action="store_true",
        help=("let the gate preflight run `pnpm install --frozen-lockfile "
              "--prefer-offline` inside the usine tree when node_modules is "
              "missing (default: fail closed and print the fix command; "
              "ignored by the read-only --preflight report)"))
    parser.add_argument(
        "--llm-config", default=str(DEFAULT_LLM_CONFIG),
        help=("unified explorateur config/.env (LLM_<SLUG>_BASE_URL / "
              "LLM_<SLUG>_API_KEY pairs; see config/env.sample)"))
    parser.add_argument(
        "--resume-completed-boundary", action="store_true",
        help=("resume an infrastructure-stopped lineage only when every "
              "accepted project is durably closed and the persistent "
              "Curriculum transcript is intact"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--preflight", action="store_true",
        help=("print the readiness payload and exit without writing "
              "anything (no endpoints file, no run root, no corpus)"))
    action.add_argument("--execute", default="", help=EXECUTE_ACK)
    return parser


def main(argv: list | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.project_budget < 0:
        raise RuntimeError("--project-budget must be nonnegative")
    if args.max_parallel < 1:
        raise RuntimeError("--max-parallel must be positive")
    if not args.gate_argv:
        raise RuntimeError("--gate-argv must name the offline gate command")
    checkpoints = _parse_checkpoints(args.checkpoints, args.project_budget)

    theatre = _install_paths()
    import verifier_adapter
    verifier_adapter.install_verifier_adapter()
    import guest_env            # noqa: F401  (substrate; registers atexit net)
    import usine_hooks
    import wave_merge
    _install_actor_prompt_patch()
    _posix_host_no_browser()

    distribution_path = _resolve_input_file(
        args.distribution_file, repo_root=_HERE)
    distribution = distribution_path.read_text(encoding="utf-8").strip()
    if not distribution:
        raise RuntimeError("distribution description is empty")
    usine_dir = Path(args.usine_dir).expanduser().resolve(strict=True)
    if not usine_dir.is_dir():
        raise RuntimeError(f"usine directory is missing: {usine_dir}")
    run_root = _safe_phase_root(args.root, args.run_name)

    configs, role_paths, escalation_cfg = _load_roles()
    lineup = _check_lineup(configs, escalation_cfg)
    endpoints = _resolve_endpoints(
        Path(args.llm_config), set(lineup["used_models"]))
    # The engine's default-endpoint fallback (used only for a slug with no
    # per-slug mapping — waves map every needed slug fail-closed) must also
    # read the unified config, never théâtre/.env or any other source.
    os.environ.setdefault("RSIAGENT_ENV_FILE", str(Path(args.llm_config)))

    gate_argv = tuple(str(item) for item in args.gate_argv)
    merge_config = wave_merge.UsineMergeConfig(
        usine_dir=str(usine_dir), gate_argv=gate_argv,
        gate_timeout=float(args.gate_timeout))
    # Fail closed on a dirty/foreign usine repository before anything else.
    ctx = wave_merge._repo_context(usine_dir)
    wave_merge._assert_preconditions(ctx, usine_dir)

    # The distribution must be 8-gram-disjoint from every audited surface
    # BEFORE anything is written or spent (fail-closed on both entrypoints;
    # no endpoints file, no run root, no corpus has been touched yet).
    fence = _check_distribution_fences(distribution, theatre, usine_dir)

    # Gate-runnability preflight, same fail-closed logic on both
    # entrypoints: a gate that cannot run AT ALL must die here, before a
    # single token is spent — a red gate at merge time is a data-level
    # gate_rejected (silent total candidate loss).  The read-only
    # --preflight report never installs; --execute fails closed on the
    # same section and may auto-install only with explicit --gate-install.
    gate_pre = gate_preflight(
        usine_dir, gate_argv,
        allow_install=bool(args.gate_install) and not args.preflight)

    corpus_path = run_root / "corpus_shingles.json"
    corpus_mode = "resume" if args.resume_completed_boundary else "fresh"

    if args.preflight:
        seed_preview = _build_seed(usine_dir, write_to=None)
        payload = {
            "status": "ready" if gate_pre["ok"] else "gate_preflight_failed",
            "phase": "usine_production_line_rsi_waves",
            "study_design": (
                "target_conditioned_adaptation"
                if args.target_query_conditioned
                else "held_out_generalization"),
            "result_root": str(run_root),
            "project_budget": args.project_budget,
            "memory_checkpoints": list(checkpoints),
            "parallel_waves": True,
            "max_parallel": args.max_parallel,
            "wave_width_agent_owned": True,
            "branch_memory_snapshot_isolated": True,
            "memory_writes_serialized": True,
            "curriculum_may_stop_early": True,
            "curriculum_terminal_token": "SATURATED",
            "actor_agent": configs["actor"].model,
            "memory_actor_agent": configs["memory_actor"].model,
            "verifier_agent": configs["verifier_control"].verifier_model,
            "escalated_actor": lineup["esc_actor"],
            "escalated_verifier": lineup["esc_verifier"],
            "curriculum_agent": configs["curriculum"].model,
            "curriculum_eyes": configs["curriculum"].vision_model,
            "verifier_execution_mode":
                configs["verifier_control"].verifier_execution_mode,
            "verifier_candidate_surface":
                "actual_candidate_with_actor_private_artifacts_hidden",
            "verifier_pre_actor_orientation": False,
            "official_evaluator_imported": False,
            "official_evaluator_calls": 0,
            "distribution_path": str(distribution_path),
            "distribution_sha256": _sha256(distribution_path),
            "distribution_fence": fence,
            "corpus_mode": corpus_mode,
            "corpus_path": str(corpus_path),
            "corpus_lifetime": (
                "fixed: distribution shingles only; never extended mid-run "
                "(stock Phase-1 feedback replays prior project texts "
                "verbatim into later Curriculum prompts)"),
            "usine_dir": str(usine_dir),
            "usine_repo_toplevel": ctx["toplevel"],
            "usine_repo_prefix": ctx["prefix"] or "(repo root)",
            "seed_preview": seed_preview,
            "gate": {"argv": list(gate_argv),
                     "timeout": float(args.gate_timeout)},
            "gate_preflight": gate_pre,
            "llm_endpoints": {
                "config": str(Path(args.llm_config).expanduser()),
                "resolved": {slug: {"base_url": True, "api_key": True}
                             for slug in sorted(endpoints)},
            },
            "publish_boundary": [
                "vm facade refuses publish-shaped programs before execution",
                "guest-home USERPROFILE pin (no live platform profiles)",
                "offline-only gate; corpus leakage audits",
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if gate_pre["ok"] else 1

    if args.execute != EXECUTE_ACK:
        raise RuntimeError(f"--execute must equal {EXECUTE_ACK}")
    if not gate_pre["ok"]:
        raise RuntimeError(
            "gate preflight failed — a gate that cannot run would silently "
            "destroy every merged candidate at verify time (fix the "
            "toolchain, or pass --gate-install for a missing tree): "
            + "; ".join(gate_pre["errors"]))

    if (run_root.exists() and any(run_root.iterdir())
            and not args.resume_completed_boundary):
        raise RuntimeError(
            "usine Phase-1 root is nonempty; preserve it and use a new name")
    if args.resume_completed_boundary and not run_root.is_dir():
        raise RuntimeError("usine Phase-1 resume root does not exist")
    run_root.mkdir(parents=True, exist_ok=True)
    events_path = run_root / "events.jsonl"

    # Credentials: generated OUTSIDE every repository, before any LLM call.
    endpoints_path = run_root / "endpoints.json"
    _write_json_atomic(endpoints_path, endpoints)
    os.environ["RSIAGENT_LLM_ENDPOINTS_FILE"] = str(endpoints_path)
    log.info("endpoints map written for %d model slug(s) (values never "
             "logged)", len(endpoints))

    # Corpus: fresh builds from the distribution; resume merges pending
    # waves first, then requires the corpus to equal a fresh rebuild from
    # the distribution (the corpus is fixed for the whole run).
    if args.resume_completed_boundary:
        grams = usine_hooks.load_corpus(corpus_path)
        if grams != usine_hooks._shingles(distribution):
            raise RuntimeError(
                "resumed usine corpus does not equal a fresh rebuild from "
                "the distribution (corpus rewrite or distribution drift)")
        reports = wave_merge.merge_pending_waves(str(run_root), merge_config)
        if reports:
            log.info("resume merged %d pending wave(s)", len(reports))
            # Merged candidates moved HEAD: re-clear the fence against the
            # new tree before the next wave captures from it.
            _check_distribution_fences(distribution, theatre, usine_dir)
    else:
        usine_hooks.build_corpus(corpus_path, [distribution])

    manifest = {
        "schema_version": 1,
        "kind": "usine_production_line_rsi_phase1",
        "phase": "usine_production_line_rsi_waves",
        "study_design": (
            "target_conditioned_adaptation"
            if args.target_query_conditioned else "held_out_generalization"),
        "result_root": str(run_root),
        "project_budget": args.project_budget,
        "memory_checkpoints": list(checkpoints),
        "parallel_waves": True,
        "max_parallel": args.max_parallel,
        "wave_width_agent_owned": True,
        "branch_memory_snapshot_isolated": True,
        "memory_writes_serialized": True,
        "curriculum_may_stop_early": True,
        "curriculum_terminal_token": "SATURATED",
        "usine_dir": str(usine_dir),
        "gate_argv": list(gate_argv),
        "gate_timeout": float(args.gate_timeout),
        "merge_tag_prefix": merge_config.tag_prefix,
        "merge_commit_scope": merge_config.commit_scope,
        "distribution_path": str(distribution_path),
        "distribution_sha256": _sha256(distribution_path),
        "corpus_path": str(corpus_path),
        "corpus_sha256": _sha256(corpus_path),
        "corpus_resume_check": "equal_to_distribution_rebuild",
        "seed_source": "git_archive_head_prefix",
        "seed_cache_key": "guest_scratch",
        "configs": {
            role: {
                "path": str(role_paths[role]),
                "sha256": _sha256(role_paths[role]),
                "effective": dataclasses.asdict(configs[role]),
            }
            for role in sorted(configs)
        },
    }
    manifest = json.loads(json.dumps(
        manifest, ensure_ascii=False, sort_keys=True))
    manifest_path = run_root / "manifest.json"
    if args.resume_completed_boundary:
        try:
            existing = json.loads(
                manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise RuntimeError(
                "usine resume manifest is unreadable") from exc
        if existing != manifest:
            raise RuntimeError(
                "usine resume protocol/config manifest drifted")
    else:
        _write_json_atomic(manifest_path, manifest)

    hooks = usine_hooks.hooks_for(corpus_path)
    seed_state = {"usine_dir": str(usine_dir), "run_root": str(run_root),
                  "cache": {}}
    hooks.capture_project = _seeded_capture(hooks.capture_project, seed_state)
    vm_factory = usine_hooks.publish_blacklist_vm_factory(
        guest_env.worktree_vm_factory())
    vm_factory = _harness_staging_vm_factory(vm_factory, seed_state)

    def logger(event_type, **kwargs):
        _append_event(events_path, event_type, **kwargs)

    sink = wave_merge.wave_merge_event_sink(
        str(run_root), merge_config, inner=logger)

    from explore.phase1_wave import evolve_parallel_phase1
    result = evolve_parallel_phase1(
        root=str(run_root), target_direction=distribution,
        actor_cfg=configs["actor"],
        curriculum_cfg=configs["curriculum"],
        memory_cfg=configs["memory_actor"],
        verifier_control_cfg=configs["verifier_control"],
        vm_factory=vm_factory, corpus_path=str(corpus_path), hooks=hooks,
        event_sink=sink,
        project_budget=args.project_budget,
        checkpoint_projects=checkpoints,
        max_parallel=args.max_parallel,
        target_query_conditioned=args.target_query_conditioned,
        resume_completed_boundary=args.resume_completed_boundary,
        park_verified_branches=False)

    from explore.practice_loop import (
        _atomic_install_memory,
        _manifest,
        _read_memory_tree,
    )
    from explore.target_learning import _memory_tree_sha256

    memory = _read_memory_tree(result.memory_dir)
    frozen = run_root / "memory_frozen"
    _atomic_install_memory(str(frozen), memory)
    payload = {
        "schema_version": 1,
        "phase": "usine_production_line_rsi_waves",
        "study_design": (
            "target_conditioned_adaptation"
            if args.target_query_conditioned else "held_out_generalization"),
        "status": result.status,
        "projects": result.projects,
        "stop_reason": result.reason,
        "project_budget": args.project_budget,
        "checkpoints": list(checkpoints),
        "parallel_waves": True,
        "max_parallel": args.max_parallel,
        "memory_files": len(memory),
        "memory_bytes": sum(len(data) for data in memory.values()),
        "memory_manifest": _manifest(memory),
        "memory_tree_sha256": _memory_tree_sha256(memory),
        "memory_frozen_path": str(frozen),
        "official_evaluator_calls": 0,
    }
    _write_json_atomic(run_root / "result.json", payload)
    print("\n=== USINE PHASE 1 RESULT " + json.dumps(payload, sort_keys=True))
    return 0 if result.status in {"saturated", "budget_exhausted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
