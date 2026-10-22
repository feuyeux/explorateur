"""wave_merge.py — serial wave-end merge of accepted usine candidates (host side).

The stock phase-1 wave loop verifies every branch in an isolated VM and then
commits only *memory*; the accepted code candidates stay as byte-exact
``materials.tgz`` archives under ``episodes/epNNN/candidates/cycle_001``.
This module adds the usine-specific second half: after a wave fully closes,
merge every PASS candidate into the real usine working tree, serially, behind
the project's own verification gate, and record one explicit-path commit per
accepted candidate plus one wave tag.

Merge contract (v1)
-------------------
* Trigger. ``wave_merge_event_sink`` merges on ``PHASE1_WAVE_COMPLETED``
  (all branches closed, memory committed, no VM held by the loop). The event
  is forwarded to the inner sink BEFORE merging so the completed-wave event
  log stays valid for ``phase1_boundary_recovery.validate_boundary`` even
  when the merge raises (the wave loop then finishes ``infra`` and
  ``merge_pending_waves`` re-merges that wave on the next run start).
* Baseline. Each candidate is diffed against the byte-exact baseline it was
  authored on: ``<lineage>/baselines/wave_NNN/`` when run_usine records one,
  else the stock episode fixture ``episodes/epNNN/fixtures`` (identical under
  the capture-seam fixture strategy, where the usine baseline IS the fixture).
* Delta. Full-tree sha256 inventories (stock ``_inventory_from_tgz``), member
  prefix ``evolution_project/`` stripped, with symmetric exclusions
  (``.git``, ``__pycache__``, ``.venv``/``venv``, ``node_modules``, ``dist``,
  caches, ``*.pyc``/``*.pyo``, ``*.tsbuildinfo``, ``.DS_Store``).
  Content deltas carry the executable bit by convention: a delta path is
  staged executable when the candidate archive carried the bit OR the path
  is already tracked with git mode ``100755`` (bin/feuille.js is the anchor).
  Everything else about modes stays HEAD's (v1).
* Per-file tri-state against the working tree: bytes already equal to the
  candidate -> pre-applied (idempotent catch-up); bytes equal to the baseline
  -> fresh; anything else -> the whole candidate is drift-skipped, never
  partially applied.
* Apply is surgical (write/delete only delta paths, snapshot-based rollback,
  never ``git clean``). The gate then runs (config argv, cwd=usine_dir,
  timeout). Tracked gate side effects outside the delta are reverted to HEAD
  and recorded; untracked gate scratch (``__pycache__`` etc.) is tolerated
  and never staged.
* Commit stages exactly the delta paths (``--pathspec-from-file``), so a wave
  commit can never absorb foreign staged or dirty state. Preconditions:
  repo-wide index clean and tracked files under usine_dir clean. usine_dir
  may be a whole repository or a subtree (explorateur hosts usine/ inside a
  larger repo; the prefix comes from ``git rev-parse --show-prefix``).
* Repo topology policy: a candidate that adds an untracked path matched by
  the repository's ignore rules, or a Windows-reserved/trailing-dot name, is
  skipped whole (``path_policy_skipped``) — partial merges would diverge the
  committed tree from the verified candidate. Symlink changes are likewise
  skipped whole (``symlink_unsupported``).
* Fail-closed: a PASS episode without archives, a malformed/diverged archive
  sidecar, or a gate that cannot run raises ``UsineMergeError`` (infra — the
  wave loop halts). Data-level rejections (gate red, drift, path policy,
  symlinks) never raise; they are recorded in the per-candidate report.
* Spec sync.  A candidate that changes code governed by a spec document must
  update that spec document in the SAME candidate, or it is skipped whole
  (``spec_sync_rejected``).  The spec document declares what it pins in its own
  anchors block, so the rule keeps a single source of truth; see
  ``spec_sync.py`` for why a stale spec is worse than a stale comment.
* Honest coverage.  The gate's skipped-test count is parsed out of its output
  and recorded per candidate.  A skip is not a pass, and a report that cannot
  see it is a report that will quietly overstate what was covered.
* Memory in the repository.  After a wave merges, the terminal memory tree is
  copied into ``garage/memory-snapshots/`` and committed, so the knowledge a
  wave produced is diffable and reviewable in the repository instead of living
  only in a run root outside it.
* Collision-safe names.  Tag and snapshot names carry only ``unit + wave``,
  while every run root starts at wave 1 — so two run roots WILL collide.  A
  tag that already points at this wave's last commit is reused (idempotent); a
  tag that points elsewhere gets the next free suffix (``theatre/wave-1-2``).
  A snapshot directory is reused only when its files are byte-identical; a
  different tree from another run root gets ``wave-001-2`` and both are kept;
  a different tree from the SAME run root raises (it must be inspected, not
  papered over).  Collisions are recorded in the report and the manifest, and
  ``verify_memory_snapshots`` is the machine check.
* Crash recovery.  A wave can die between its candidate commit and its tag, or
  between the tag and the memory snapshot.  ``waves/wave_NNN/merge_progress.json``
  records the base, every commit that landed, the tag and the snapshot as each
  step completes.  The next invocation validates that every recorded commit
  still exists and is an ancestor of HEAD, then finishes the tag and snapshot;
  the report says ``resumed_from_progress`` and separates the whole wave's
  ``commits`` from ``commits_made_this_run``.  A rewritten history, a changed
  unit label or a changed tag prefix makes the journal unusable (fail-closed)
  instead of tagging a commit that no longer belongs to this wave.
* Serialized merges.  Two run roots can finish a wave at the same time against
  the same repository.  The whole merge runs under an exclusive OS lock in the
  git common dir (worktrees share the main repository's lock), so commits,
  tags and snapshots cannot interleave.  The lock is released by the kernel
  when a process dies, so there is no stale lock to clean by hand.  A second
  merge waits up to ``RSIAGENT_MERGE_LOCK_TIMEOUT`` seconds (default 300; 0 =
  try once) and then fails with the holder's pid/host; it re-checks the wave
  report AFTER acquiring the lock, so a merge that finished while it waited is
  a no-op rather than a duplicate commit.

Notable limitation: merge rejections are not fed back into Curriculum's next
wave rationale (stock renders outcome.md before the merge point); they are
reported to the operator and archived in ``waves/wave_NNN/merge_report.json``.

This module lazily imports ``explore.provisioning``; the importing process
must put the théâtre root on ``sys.path`` first (run_usine.py and the smoke
tests do).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import re
import socket
import stat as stat_module
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

import spec_sync

log = logging.getLogger("rsiagent.usine.wave_merge")

PROJECT_ROOT_PREFIX = "evolution_project/"
PROJECT_ROOT_NAME = "evolution_project"

# Symmetric fixture/candidate exclusions: never part of a merge delta.
# ``node_modules`` and ``dist`` are the TS-era regenerables (pnpm install /
# pnpm test rebuild them); unpruned they would not just bloat archives but
# also trip path_policy (``git check-ignore``) and drop whole candidates.
# ``build`` is the gitignored evidence/regenerable output root (e.g. publish
# 测试的 build/publish-verify 证据副本——注释里就写着「不入库」): untracked
# gate side effects landing there must not ride into a candidate delta.
# ``*.tsbuildinfo`` is the tsc incremental cache, same story.
EXCLUDED_PARTS = frozenset({
    ".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox",
    ".ipynb_checkpoints", ".eggs",
})
EXCLUDED_NAMES = frozenset({".DS_Store"})
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".egg-info", ".tsbuildinfo")

_RESERVED_BASENAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)
_ADD_BATCH = 100                  # staged paths per git add call
_GATE_TAIL = 4000                 # gate stdout tail kept in the report
_GIT_TIMEOUT = 300
_HEALTH_TIMEOUT = 300             # the offline health score is sub-second
_L3_TIMEOUT = 300                 # the agent-surface smoke is a local check


class UsineMergeError(RuntimeError):
    """Merge infrastructure failed; the wave loop must halt (fail-closed)."""


@dataclass(frozen=True)
class UsineMergeConfig:
    """Merge knobs. ``gate_argv`` is mandatory — the gate is never guessed."""

    usine_dir: str
    gate_argv: tuple[str, ...]
    gate_timeout: float = 1800.0
    identity: tuple[str, str] = ("theatre-rsi", "theatre-rsi@explorateur.local")
    tag_prefix: str = "theatre/wave"
    commit_scope: str = "theatre"
    # What ONE merged unit is called in the commit subject, the commit body
    # and the trailers: "wave" for a breadth wave, "drs" for a deep-
    # recursion episode.  A DRS episode is NOT a wave — it is one serial
    # project — so a commit that calls it "wave-1" states something false
    # about where the change came from.  The TAG name is built from
    # ``tag_prefix`` + the wave index, not from this label.
    unit_label: str = "wave"
    gate_env: dict | None = None
    # 产线健康分命令（离线「比合并前更好没有」的判据）。空 = 自动找
    # <usine>/packages/eval/bin/feuille-eval.js；找不到就没有这道闸。
    health_argv: tuple[str, ...] = ()
    # L3「智能体面真验」的冒烟命令。None = 自动发现（且要求适配层与被改进的
    # 仓在同一个仓库里）；空元组 = 显式关闭。
    l3_smoke_argv: tuple[str, ...] | None = None
    # Where the per-wave memory snapshot lands, relative to the repository
    # toplevel.  Empty = derive it from where this adaptation layer sits (the
    # real explorateur layout: <repo>/garage/memory-snapshots/).  A deployment
    # where the layer lives outside the repository — or a test with a
    # throwaway repo — sets it explicitly; without that the snapshot is
    # skipped and the report says so.
    memory_snapshot_dir: str = ""


# ------------------------------------------------------------------ archives

def _excluded(rel: str) -> bool:
    path = PurePosixPath(rel)
    return (any(part in EXCLUDED_PARTS for part in path.parts)
            or path.name in EXCLUDED_NAMES
            or path.name.endswith(EXCLUDED_SUFFIXES))


def _provisioning():
    from explore import provisioning
    return provisioning


def load_archive_inventory(host_dir, label: str) -> dict:
    """Parse a captured materials archive into repo-relative inventories.

    Returns ``{"files": {rel: sha256}, "symlinks": {rel: target},
    "excluded": [rel], "members": N}`` where ``rel`` is relative to the
    usine project root (the ``evolution_project/`` member prefix stripped)
    and exclusions are already partitioned out. Raises ``UsineMergeError``
    on a missing archive, unsafe members, or a sidecar that diverged from
    the archived bytes.
    """
    prov = _provisioning()
    directory = pathlib.Path(host_dir)
    tgz = directory / "materials.tgz"
    if not tgz.is_file():
        raise UsineMergeError(f"{label}: materials.tgz is missing ({tgz})")
    roots = prov.read_roots(str(directory))
    if roots != [PROJECT_ROOT_NAME]:
        raise UsineMergeError(
            f"{label}: owned roots {roots!r} do not match the usine project root")
    data = tgz.read_bytes()
    try:
        manifest, symlinks = prov._inventory_from_tgz(data)
    except ValueError as exc:
        raise UsineMergeError(
            f"{label}: project archive failed the safety/digest inventory: "
            f"{exc}") from exc
    if not manifest:
        raise UsineMergeError(f"{label}: project archive is empty")
    sidecar = prov.read_manifest(str(directory))
    if sidecar != manifest:
        raise UsineMergeError(
            f"{label}: manifest sidecar diverged from the archived bytes "
            f"(sidecar={len(sidecar)} entries, archive={len(manifest)})")
    files: dict[str, str] = {}
    links: dict[str, str] = {}
    excluded: list[str] = []
    for member, digest in manifest.items():
        if (not member.startswith(PROJECT_ROOT_PREFIX)
                or len(member) <= len(PROJECT_ROOT_PREFIX)):
            raise UsineMergeError(
                f"{label}: archive member {member!r} is outside the project root")
        rel = member[len(PROJECT_ROOT_PREFIX):]
        if _excluded(rel):
            excluded.append(rel)
        elif member in symlinks:
            links[rel] = symlinks[member]
        else:
            files[rel] = digest
    return {"files": dict(sorted(files.items())),
            "symlinks": dict(sorted(links.items())),
            "excluded": sorted(excluded),
            "members": len(manifest)}


def candidate_delta(fixture_files: dict, candidate_files: dict) -> dict:
    """Pure content delta: paths whose bytes differ between the inventories."""
    modified = sorted(rel for rel in fixture_files.keys() & candidate_files.keys()
                      if fixture_files[rel] != candidate_files[rel])
    return {"modified": modified,
            "added": sorted(candidate_files.keys() - fixture_files.keys()),
            "deleted": sorted(fixture_files.keys() - candidate_files.keys())}


def symlink_changes(fixture_links: dict, candidate_links: dict) -> dict:
    """Symlink delta. Any non-empty field blocks the candidate (v1)."""
    common = fixture_links.keys() & candidate_links.keys()
    changed = sorted(rel for rel in common
                     if fixture_links[rel] != candidate_links[rel])
    return {"changed": changed,
            "added": sorted(candidate_links.keys() - fixture_links.keys()),
            "removed": sorted(fixture_links.keys() - candidate_links.keys()),
            "unchanged": len(common) - len(changed)}


def _extract_members(host_dir, rels, inventory_files: dict) -> dict:
    """{rel: bytes} for the wanted repo-relative paths, digest-verified."""
    wanted = {PROJECT_ROOT_PREFIX + rel: rel for rel in rels}
    out: dict[str, bytes] = {}
    with tarfile.open(pathlib.Path(host_dir) / "materials.tgz", "r:gz") as tf:
        for member in tf:
            name = PurePosixPath(member.name).as_posix()
            rel = wanted.get(name)
            if rel is None or not (member.isfile() or member.islnk()):
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            if hashlib.sha256(data).hexdigest() != inventory_files[rel]:
                raise UsineMergeError(
                    f"candidate bytes for {rel} failed the archive digest")
            out[rel] = data
    missing = sorted(set(rels) - out.keys())
    if missing:
        raise UsineMergeError(f"candidate archive lost members: {missing[:3]}")
    return out


# ------------------------------------------------------------ classification

def _normalized_sha(data: bytes) -> str:
    """sha256 of the bytes with CRLF folded to LF.

    Line endings are NOT a content change on this host.  The repository's
    canonical form is the LF blob (``core.autocrlf=input``: git folds
    CRLF on the way IN and never expands LF on checkout), so a working-tree
    file may carry CRLF because an editor, a formatter, or a stash
    round-trip rewrote it — and git still calls that file clean.  The
    merge's drift check must call it unchanged too, or the candidate is
    skipped whole for a difference that is not a difference.

    Measured 2026-10-20: the DRS candidate's ``tools.ts`` was byte-identical
    to HEAD's blob after folding, and the raw bytes differed by exactly 558
    CRLFs.  The raw comparison called that "drift", which would have
    silently dropped a verifier-PASSed, gate-green candidate.
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _tree_state(path: pathlib.Path) -> tuple[str, str | None, str | None]:
    """(kind, raw sha, normalized sha) for a working-tree path."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing", None, None
    except OSError:
        return "error", None, None
    if stat_module.S_ISDIR(info.st_mode):
        return "dir", None, None
    if not stat_module.S_ISREG(info.st_mode):
        return "special", None, None
    data = path.read_bytes()
    return "file", hashlib.sha256(data).hexdigest(), _normalized_sha(data)


def classify_delta(delta: dict, fixture_files: dict, candidate_files: dict,
                   usine_dir, fixture_normalized: dict | None = None,
                   candidate_normalized: dict | None = None) -> tuple[str, dict]:
    """Tri-state every delta path against the working tree.

    Returns ``(verdict, details)`` with verdict:

    * ``already_merged`` — every delta path already carries the candidate
      bytes (idempotent catch-up after a mid-wave crash);
    * ``fresh`` — every delta path carries the baseline bytes (or is absent,
      for additions); safe to apply, ``pre_applied`` counts candidate-state
      paths inside a mixed verdict;
    * ``drift`` — some path matches neither the baseline nor the candidate;
      the candidate is skipped whole.

    Each side is compared BOTH raw and line-ending-folded (see
    ``_normalized_sha``): a working-tree copy that carries CRLF where the
    archives carry LF is the same content, and calling it drift would drop
    a candidate over an invisible difference.
    """
    root = pathlib.Path(usine_dir)
    fixture_norm = fixture_normalized or {}
    candidate_norm = candidate_normalized or {}
    states: dict[str, str] = {}
    for rel in delta["modified"]:
        kind, sha, norm = _tree_state(root.joinpath(*PurePosixPath(rel).parts))
        if kind == "file" and (sha == candidate_files[rel]
                               or norm == candidate_norm.get(rel)):
            states[rel] = "candidate"
        elif kind == "file" and (sha == fixture_files[rel]
                                 or norm == fixture_norm.get(rel)):
            states[rel] = "fixture"
        else:
            states[rel] = "other"
    for rel in delta["added"]:
        kind, sha, norm = _tree_state(root.joinpath(*PurePosixPath(rel).parts))
        if kind == "missing":
            states[rel] = "fixture"
        elif kind == "file" and (sha == candidate_files[rel]
                                 or norm == candidate_norm.get(rel)):
            states[rel] = "candidate"
        else:
            states[rel] = "other"
    for rel in delta["deleted"]:
        kind, sha, norm = _tree_state(root.joinpath(*PurePosixPath(rel).parts))
        if kind == "missing":
            states[rel] = "candidate"
        elif kind == "file" and (sha == fixture_files[rel]
                                 or norm == fixture_norm.get(rel)):
            states[rel] = "fixture"
        else:
            states[rel] = "other"
    others = sorted(rel for rel, state in states.items() if state == "other")
    if others:
        rel = others[0]
        return "drift", {"reason": f"working tree matches neither baseline "
                          f"nor candidate at {rel!r} "
                          f"({_tree_state(root.joinpath(*PurePosixPath(rel).parts))[0]})",
                          "drift_paths": others}
    pre_applied = sum(1 for state in states.values() if state == "candidate")
    if pre_applied == len(states):
        return "already_merged", {"pre_applied": pre_applied}
    return "fresh", {"pre_applied": pre_applied}


# ----------------------------------------------------------------- git plumbing

def _git(args, cwd, *, check: bool = True, input_bytes: bytes | None = None,
         timeout: float = _GIT_TIMEOUT, env: dict | None = None):
    argv = ["git", *[str(a) for a in args]]
    try:
        proc = subprocess.run(argv, cwd=str(cwd), input=input_bytes,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UsineMergeError(f"git {argv[:3]} could not run: {exc}") from exc
    if check and proc.returncode != 0:
        raise UsineMergeError(
            f"git {' '.join(argv[1:4])} failed (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')[:400]}")
    return proc


def _repo_context(usine_dir) -> dict:
    top = _git(["rev-parse", "--show-toplevel"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()
    prefix = _git(["rev-parse", "--show-prefix"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()
    if not top:
        raise UsineMergeError(f"{usine_dir} is not inside a git repository")
    return {"toplevel": top, "prefix": prefix}


def _porcelain_tracked(usine_dir) -> list[str]:
    """Root-relative paths of tracked changes under usine_dir (porcelain -z)."""
    out = _git(["status", "--porcelain", "-z", "-uno", "--", "."], cwd=usine_dir)
    return [entry[3:] for entry in out.stdout.decode("utf-8", "replace")
            .split("\0") if entry]


def _pathspec_file(paths) -> str:
    fd, name = tempfile.mkstemp(prefix="usine-merge-pathspec-")
    with os.fdopen(fd, "wb") as handle:
        if paths:
            handle.write(b"\0".join(p.encode("utf-8") for p in paths) + b"\0")
    return name


def _run_pathspec(args, cwd, paths) -> None:
    spec = _pathspec_file(paths)
    try:
        _git([*args, f"--pathspec-from-file={spec}", "--pathspec-file-nul"],
             cwd=cwd)
    finally:
        try:
            os.remove(spec)
        except OSError:
            pass


def _check_ignore(ctx, usine_dir, rels) -> list[str]:
    """Candidate-added paths matched by the repository ignore rules.

    Runs from the repo toplevel so the stdin paths (root-relative) and the
    rule patterns share one coordinate system; from a subtree cwd the same
    strings would resolve to different files.
    """
    if not rels:
        return []
    prefix = ctx["prefix"]
    root_rels = [prefix + rel for rel in rels]
    proc = _git(["check-ignore", "--stdin", "-z"], cwd=ctx["toplevel"],
                check=False,
                input_bytes=b"\0".join(p.encode("utf-8") for p in root_rels)
                + b"\0")
    if proc.returncode not in (0, 1):
        raise UsineMergeError(
            f"git check-ignore failed (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')[:200]}")
    ignored = [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]
    return sorted(p[len(prefix):] if prefix and p.startswith(prefix) else p
                  for p in ignored)


def _tracked_paths(ctx, usine_dir, rels) -> set:
    """Which of the given repo-relative paths are already tracked.

    ``git ls-files`` has no ``--pathspec-from-file``; literal pathspecs via
    ``GIT_LITERAL_PATHSPECS`` keep glob metacharacters in filenames inert,
    and batching bounds argv length on Windows.
    """
    if not rels:
        return set()
    prefix = ctx["prefix"]
    env = dict(os.environ)
    env["GIT_LITERAL_PATHSPECS"] = "1"
    tracked: set[str] = set()
    for i in range(0, len(rels), _ADD_BATCH):
        batch = [prefix + rel for rel in rels[i:i + _ADD_BATCH]]
        out = _git(["ls-files", "-z", "--", *batch],
                   cwd=ctx["toplevel"], env=env).stdout
        for path in out.decode("utf-8", "replace").split("\0"):
            if path:
                tracked.add(path[len(prefix):]
                            if prefix and path.startswith(prefix) else path)
    return tracked


def path_policy_violations(added, ctx, usine_dir) -> dict:
    """{rel: reason} for added paths the repository/OS could not commit.

    Windows reserved device names and trailing dot/space components could
    not be written reliably; untracked paths matched by the repository's
    ignore rules could not be staged without ``-f`` (and forcing them would
    silently redefine what the repository tracks).
    """
    reasons: dict[str, str] = {}
    for rel in added:
        parts = PurePosixPath(rel).parts
        if any(part.endswith(" ") or part.endswith(".") for part in parts):
            reasons[rel] = "Windows-forbidden component (trailing space/dot)"
        elif any(_RESERVED_BASENAME.match(part) for part in parts):
            reasons[rel] = "Windows reserved device name"
    rest = [rel for rel in added if rel not in reasons]
    ignored = _check_ignore(ctx, usine_dir, rest)
    tracked = _tracked_paths(ctx, usine_dir, ignored)
    for rel in sorted(set(ignored) - tracked):
        reasons.setdefault(rel, "untracked path matched by repository ignore rules")
    return reasons


# ------------------------------------------------------------------ apply/rollback

def _file_mode(root: pathlib.Path, rel: str):
    """Current permission bits of a delta path (None = absent/unreadable)."""
    try:
        return stat_module.S_IMODE(
            root.joinpath(*PurePosixPath(rel).parts).stat().st_mode)
    except OSError:
        return None


def _archive_exec_bits(host_dir, rels) -> set[str]:
    """Wanted archive members that carry any executable bit."""
    wanted = {PROJECT_ROOT_PREFIX + rel: rel for rel in rels}
    out: set[str] = set()
    with tarfile.open(pathlib.Path(host_dir) / "materials.tgz", "r:gz") as tf:
        for member in tf:
            rel = wanted.get(PurePosixPath(member.name).as_posix())
            if rel is not None and (member.isfile() or member.islnk()) \
                    and member.mode & 0o111:
                out.add(rel)
    return out


def _tracked_exec_bits(ctx, rels) -> set[str]:
    """Wanted paths already tracked with git mode 100755 in the index.

    Byte replacement (staged temp + os.replace) lands with default bits, so
    without this look-up every merged edit of bin/feuille.js would silently
    flip the tracked mode to 100644 on POSIX.  On Windows git never probes
    the filesystem for the bit and keeps the index mode anyway; the chmod
    downstream is a no-op there.
    """
    prefix = ctx["prefix"]
    env = dict(os.environ)
    env["GIT_LITERAL_PATHSPECS"] = "1"
    rels = list(rels)
    out: set[str] = set()
    for i in range(0, len(rels), _ADD_BATCH):
        batch = [prefix + rel for rel in rels[i:i + _ADD_BATCH]]
        text = _git(["ls-files", "-s", "--", *batch],
                     cwd=ctx["toplevel"], env=env).stdout.decode(
                         "utf-8", "replace")
        for line in text.splitlines():
            meta, sep, path = line.partition("\t")
            if sep and meta.split()[:1] == ["100755"] and path:
                out.add(path[len(prefix):]
                        if prefix and path.startswith(prefix) else path)
    return out


def _snapshot_tree(usine_dir, delta: dict) -> dict:
    """Current bytes and modes of every delta path (None = absent) for
    byte-and-mode rollback."""
    root = pathlib.Path(usine_dir)
    snapshot: dict[str, tuple[bytes | None, int | None]] = {}
    for rel in (*delta["modified"], *delta["added"], *delta["deleted"]):
        try:
            data = root.joinpath(
                *PurePosixPath(rel).parts).read_bytes()
        except OSError:
            data = None
        snapshot[rel] = (data, _file_mode(root, rel))
    return snapshot


def _apply_delta(usine_dir, delta: dict, wanted: dict,
                 executable: set[str] | None = None) -> None:
    root = pathlib.Path(usine_dir)
    for rel in (*delta["modified"], *delta["added"]):
        target = root.joinpath(*PurePosixPath(rel).parts)
        if target.is_dir():
            raise UsineMergeError(
                f"apply refused: {rel} is a directory in the working tree")
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.name + ".rsiagent-merge-part")
        staged.write_bytes(wanted[rel])
        os.replace(staged, target)
        if executable and rel in executable:
            os.chmod(target, _file_mode(root, rel) | 0o111)
    for rel in delta["deleted"]:
        target = root.joinpath(*PurePosixPath(rel).parts)
        if target.is_file():
            target.unlink()
        parent = target.parent
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


def _rollback_delta(usine_dir, delta: dict, snapshot: dict) -> None:
    root = pathlib.Path(usine_dir)
    for rel, (data, mode) in snapshot.items():
        target = root.joinpath(*PurePosixPath(rel).parts)
        try:
            if data is None:
                if target.is_file():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                staged = target.with_name(target.name + ".rsiagent-merge-part")
                staged.write_bytes(data)
                os.replace(staged, target)
                if mode is not None:
                    # restore the exact pre-apply bits: byte replacement
                    # alone would leave a rejected candidate's mode drift
                    os.chmod(target, mode)
        except OSError as exc:
            raise UsineMergeError(f"rollback failed for {rel}: {exc}") from exc


def _gate_side_effects(ctx, usine_dir, delta: dict, entry: dict) -> list[str]:
    """Revert tracked gate side effects outside the delta; record them."""
    prefix = ctx["prefix"]
    expected = set(delta["modified"]) | set(delta["added"]) | set(delta["deleted"])
    extras = []
    for path in _porcelain_tracked(usine_dir):
        rel = path[len(prefix):] if prefix and path.startswith(prefix) else path
        if rel not in expected:
            extras.append(rel)
    if extras:
        _run_pathspec(["checkout", "HEAD"], usine_dir, sorted(set(extras)))
        entry["gate_side_effects"] = sorted(set(extras))
        log.warning("gate touched %d tracked path(s) outside the delta; "
                    "reverted to HEAD: %s", len(extras), sorted(set(extras))[:3])
    return extras


# ----------------------------------------------------------------------- gate

# vitest 的汇总行：``Tests  528 passed | 8 skipped (536)``（也可能是
# ``Tests  1 failed | 528 passed | 8 skipped (537)``，或没有 skipped 段）。
# 跳过数必须被看见：SKIP 不是 PASS，一份看不见跳过数的报告会悄悄夸大覆盖。
_GATE_TESTS_LINE = re.compile(r"^\s*Tests\s+(?P<body>[^\n(]*)\(\s*(?P<total>\d+)\s*\)",
                              re.MULTILINE)


def _parse_gate_counts(tail: str) -> dict:
    """从门禁输出里解析 vitest 的计数。解析不出来就留 None——不猜 0。

    ``skipped`` 为 None 表示「门禁没吐可解析的计数」；这与「跳过 0 个」是
    两回事，报告里必须分得开。
    """
    match = _GATE_TESTS_LINE.search(tail)
    if match is None:
        return {"passed": None, "failed": None, "skipped": None, "total": None}
    body = match.group("body")
    counts = {}
    for label in ("passed", "failed", "skipped", "todo"):
        found = re.search(rf"(\d+)\s+{label}", body)
        counts[label] = int(found.group(1)) if found else 0
    return {"passed": counts["passed"], "failed": counts["failed"],
            "skipped": counts["skipped"], "total": int(match.group("total"))}


def run_gate(config: UsineMergeConfig, usine_dir) -> dict:
    """Run the usine verification gate on the applied working tree."""
    argv = [str(a) for a in config.gate_argv]
    env = None
    if config.gate_env:
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in config.gate_env.items()})
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=str(usine_dir),
                              timeout=config.gate_timeout,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, env=env)
    except FileNotFoundError as exc:
        raise UsineMergeError(
            f"usine gate command {argv[:1]} was not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise UsineMergeError(
            f"usine gate exceeded {config.gate_timeout:.0f}s and was killed") \
            from exc
    tail = (proc.stdout or b"")[-_GATE_TAIL:].decode("utf-8", "replace")
    counts = _parse_gate_counts(tail)
    return {"exit_code": proc.returncode,
            "seconds": round(time.time() - started, 1),
            "counts": counts,
            "tail": tail}


# ------------------------------------------------------------- commit and tag

def _clean_id(value) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:48] if text else "unnamed"


def _stage_delta(usine_dir, delta: dict) -> None:
    paths = [*delta["modified"], *delta["added"], *delta["deleted"]]
    for i in range(0, len(paths), _ADD_BATCH):
        _run_pathspec(["add", "-A"], usine_dir, paths[i:i + _ADD_BATCH])


def _commit_candidate(config: UsineMergeConfig, usine_dir, wave_index: int,
                      outcome: dict, delta: dict, gate: dict) -> str:
    label = config.unit_label
    subject = (f"{config.commit_scope}({label}-{wave_index}): "
               f"accept ep{outcome['project_index']:03d} "
               f"({_clean_id(outcome['project_id'])})")
    counts = (gate.get("counts") or {})
    skipped = counts.get("skipped")
    coverage = ""
    if counts.get("passed") is not None:
        coverage = (f"{counts['passed']} passed"
                    + (f", {skipped} skipped" if skipped else ""))
        if skipped:
            # SKIP 不是 PASS：提交信息里也得如实写，别让「门禁绿」被读成
            # 「全都验过了」。
            coverage += " (skipped are NOT passed)"
    body = (
        f"Candidate ep{outcome['project_index']:03d} merged from {label} "
        f"{wave_index} (verifier PASS, usine gate green).\n"
        f"Delta: {len(delta['modified'])} modified, {len(delta['added'])} "
        f"added, {len(delta['deleted'])} deleted.\n"
        f"Gate exit {gate['exit_code']} in {gate['seconds']}s"
        + (f" — {coverage}" if coverage else "") + ".\n\n"
        f"X-Theatre-{label.title()}: {wave_index}\n"
        f"X-Theatre-Project: {_clean_id(outcome['project_id'])}\n"
        f"X-Theatre-Source: explorateur theatre phase1 usine wave merge")
    _git(["-c", f"user.name={config.identity[0]}",
          "-c", f"user.email={config.identity[1]}",
          "commit", "-m", subject, "-m", body], cwd=usine_dir)
    return _git(["rev-parse", "HEAD"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()


#: 撞名时最多试多少个后缀（``<base>-2``、``-3``…）。给上限不是怕撞名，
#: 是让「这个 clone 里已经有 1000 个同名 wave」变成一条明确的错误，而不是死循环。
_TAG_SUFFIX_LIMIT = 1000


def _tag_commit(usine_dir, tag: str) -> str | None:
    """``tag`` 指向的提交；tag 不存在时返回 None（不抛，调用方要区分两者）。"""
    probe = _git(["rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
                 cwd=usine_dir, check=False)
    if probe.returncode != 0:
        return None
    return probe.stdout.decode("utf-8", "replace").strip() or None


def _create_annotated_tag(config: UsineMergeConfig, usine_dir, tag: str,
                          wave_index: int, commit_count: int) -> None:
    _git(["-c", f"user.name={config.identity[0]}",
          "-c", f"user.email={config.identity[1]}",
          "tag", "-a", tag, "-m",
          f"{config.commit_scope} {config.unit_label} {wave_index}: "
          f"{commit_count} candidate(s) merged"], cwd=usine_dir)


def _next_free_tag(config: UsineMergeConfig, usine_dir,
                   wave_index: int) -> str:
    """只读地算「这一波会创建哪个 tag 名」（plan 用，不建 tag）。"""
    base = f"{config.tag_prefix}-{wave_index}"
    for suffix in range(1, _TAG_SUFFIX_LIMIT + 1):
        tag = base if suffix == 1 else f"{base}-{suffix}"
        if _tag_commit(usine_dir, tag) is None:
            return tag
    raise UsineMergeError(
        f"no free tag name under {base!r} after {_TAG_SUFFIX_LIMIT} suffixes")


def _ensure_wave_tag(config: UsineMergeConfig, usine_dir, wave_index: int,
                     commits: list) -> dict:
    """给这一波打 tag——**绝不静默复用别的 run 的同名 tag**。

    2026-10-22 实测的缺陷：两个 run root 的波次编号都从 1 开始，第二个 run
    的 wave 1 会撞上已经存在、且指向另一条提交的 ``theatre/wave-1``。旧实现
    探测到 tag 存在就直接返回 ``tag_created: False``，于是这一波合进来了却
    **没有指向自己的 tag**，报告上还写着那个属于别人的 tag 名。

    现在的判据分三种，全部写进报告：

    * tag 不存在 → 创建，``tag_created: True``；
    * tag 已存在且指向本波最后一个提交 → 幂等重跑，``tag_reused: True``；
    * tag 已存在但指向别的提交 → 试 ``<base>-2``、``<base>-3``…，取第一个
      空闲的，并把撞名对象记进 ``tag_collisions``。

    tag 只活在创建它的 clone 里（见 ``_report_anchors``），所以换后缀不会
    改写任何历史提交，也不会让两条 run 的账混在一起。
    """
    base = f"{config.tag_prefix}-{wave_index}"
    collisions: list[dict] = []
    for suffix in range(1, _TAG_SUFFIX_LIMIT + 1):
        tag = base if suffix == 1 else f"{base}-{suffix}"
        target = _tag_commit(usine_dir, tag)
        if target is None:
            try:
                _create_annotated_tag(config, usine_dir, tag, wave_index,
                                      len(commits))
            except UsineMergeError:
                # 探测与创建之间被另一个进程抢先：重新看一次，别把竞态
                # 报成「git 坏了」。
                target = _tag_commit(usine_dir, tag)
                if target is None:
                    raise
                if commits and target == commits[-1]:
                    info = {"tag": tag, "tag_created": False,
                            "tag_reused": True, "tag_points_at": target}
                    if suffix > 1:
                        info["tag_base"] = base
                        info["tag_collisions"] = collisions
                    return info
                collisions.append({"tag": tag, "points_at": target})
                continue
            info = {"tag": tag, "tag_created": True}
            if suffix > 1:
                info["tag_base"] = base
                info["tag_collisions"] = collisions
            return info
        if commits and target == commits[-1]:
            info = {"tag": tag, "tag_created": False,
                    "tag_reused": True, "tag_points_at": target}
            if suffix > 1:
                info["tag_base"] = base
                info["tag_collisions"] = collisions
            return info
        collisions.append({"tag": tag, "points_at": target})
    raise UsineMergeError(
        f"no free tag name under {base!r} after {_TAG_SUFFIX_LIMIT} suffixes; "
        f"the clone already carries {len(collisions)} tag(s) for this wave "
        f"index ({[c['tag'] for c in collisions[:3]]} …). Delete stale local "
        f"tags or bump the wave index — do not reuse another run's tag")


# --------------------------------------------------------------------- waves

def _read_outcomes(lineage: pathlib.Path) -> list[dict]:
    episodes = lineage / "episodes"
    if not episodes.is_dir():
        return []
    records = []
    for directory in sorted(episodes.iterdir()):
        # A DRS episode carries the ENGINE's outcome.json, which has no
        # wave_index/project_id — it closed with PROJECT_CLOSED, not
        # PHASE1_WAVE_COMPLETED.  The DRS merge writes a Phase-1-shaped
        # record beside it; when that sibling exists it is the record the
        # merge reads, and the engine's file is left byte-for-byte alone.
        path = directory / "merge_outcome.json"
        if not path.is_file():
            path = directory / "outcome.json"
        if not path.is_file():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsineMergeError(
                f"{directory.name}: outcome.json is unreadable: {exc}") from exc
        if (not isinstance(record, dict)
                or type(record.get("wave_index")) is not int
                or type(record.get("project_index")) is not int
                or not str(record.get("project_id") or "").strip()
                or record.get("terminal_outcome") not in {"PASS", "FAIL"}):
            raise UsineMergeError(
                f"{directory.name}: outcome.json is not a closed phase-1 record")
        records.append({"episode": directory.name,
                        "wave_index": record["wave_index"],
                        "project_index": record["project_index"],
                        "project_id": str(record["project_id"]),
                        "terminal_outcome": record["terminal_outcome"]})
    return records


def _wave_outcomes(lineage: pathlib.Path, wave_index: int) -> list[dict]:
    return sorted((r for r in _read_outcomes(lineage)
                   if r["wave_index"] == wave_index),
                  key=lambda r: r["project_index"])


def _baseline_dir(lineage: pathlib.Path, wave_index: int,
                  episode_dir: pathlib.Path) -> pathlib.Path:
    recorded = lineage / "baselines" / f"wave_{wave_index:03d}"
    if (recorded / "materials.tgz").is_file():
        return recorded
    return episode_dir / "fixtures"


def _assert_preconditions(ctx: dict, usine_dir) -> str:
    staged = _git(["diff", "--cached", "--quiet"], cwd=ctx["toplevel"],
                  check=False)
    if staged.returncode != 0:
        raise UsineMergeError(
            "the repository index has staged changes; a wave commit could "
            "absorb them — commit or reset them before merging")
    dirty = _porcelain_tracked(usine_dir)
    if dirty:
        raise UsineMergeError(
            f"tracked files under {usine_dir} are dirty before the merge: "
            f"{dirty[:3]}")
    head = _git(["rev-parse", "HEAD"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()
    if not head:
        raise UsineMergeError(f"{usine_dir} has no commits to merge onto")
    return head


def _assert_seedable(ctx: dict, usine_dir) -> dict:
    """The preconditions a SEED needs — not the ones a MERGE needs.

    ``_assert_preconditions`` is a merge-safety gate: a wave commit could
    absorb staged or dirty work, so it refuses to merge into a tree that
    carries either.  The DRS (Phase 2) never merges — the serial core
    emits PROJECT_CLOSED, not PHASE1_WAVE_COMPLETED, so the wave-merge
    sink never fires.  Requiring a pristine worktree there gates a job that
    cannot be damaged by it, and it blocks a legitimate run for no reason:
    an operator with uncommitted editor scratch in the real tree still
    gets the exact COMMITTED seed, because the seed is a ``git archive
    HEAD`` of the prefix and never reads the worktree.

    So the DRS asks for what it actually needs — a resolvable HEAD — and
    RECORDS the worktree state instead of refusing on it.  The record goes
    into the run manifest, so "the DRS ran against commit X while the
    worktree carried N dirty files" is auditable rather than invisible.
    Phase 1 keeps the strict gate: a real merge follows it.
    """
    head = _git(["rev-parse", "HEAD"], cwd=ctx["toplevel"]) \
        .stdout.decode("utf-8", "replace").strip()
    if not head:
        raise UsineMergeError(f"{usine_dir} has no commits to seed from")
    dirty = _porcelain_tracked(usine_dir)
    staged = _git(["diff", "--cached", "--quiet"], cwd=ctx["toplevel"],
                  check=False)
    return {
        "head": head,
        "worktree_dirty_tracked": dirty,
        "index_has_staged_changes": staged.returncode != 0,
        "note": "the DRS seeds from the committed HEAD (git archive); the "
                "worktree state is recorded, not merged against",
    }


def _atomic_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".rsiagent-merge-part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _atomic_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".rsiagent-merge-part")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _report_anchors(commits: list[str], tag_info: dict) -> dict:
    """这一波的**可搬运锚点**。

    tag 只活在创建它的那个 clone 里。本工程的规矩是「永不 push」，代码靠人工
    同步到另一台 host——而同步带的是提交，不是 tag。2026-10-20 实测：macOS 那
    个 clone 的 ``git tag -l`` 是**空的**，三条 RSI 合并的 tag 全在 wave host
    那个 clone 上。把 tag 当回滚锚点在这里是靠不住的。

    真正能跟着代码走的锚点是 commit sha 与 commit body 里的 trailer
    （``X-Theatre-Wave`` / ``X-Theatre-Drs``）——它们在提交里，而提交会被同步。
    所以报告把两者分清：primary 是 commit，tag 明确标成 local-only。
    """
    return {
        "primary": {"kind": "commit", "value": commits[0] if commits else None},
        "commits": list(commits),
        "portable_trailer": "X-Theatre-Wave / X-Theatre-Drs (in the commit body)",
        "tag": {"name": tag_info.get("tag"),
                "created": tag_info.get("tag_created"),
                "reused": tag_info.get("tag_reused", False),
                "base": tag_info.get("tag_base"),
                "collisions": tag_info.get("tag_collisions", []),
                "portable": False,
                "note": "the tag lives only in the clone that created it; code "
                        "sync does not carry tags — roll back by commit sha"},
    }


def _render_md(report: dict) -> str:
    lines = [f"# usine wave {report['wave_index']} merge report", "",
             f"- repository: `{report['repo_toplevel']}` "
             f"(prefix `{report['repo_prefix'] or '.'}`)",
             f"- base commit: `{report['base_commit']}`",
             f"- commits: {len(report['commits'])}"
             + (f" ({report['commits_made_this_run']} made this run; "
                f"**resumed from merge_progress.json**)"
                if report.get("resumed_from_progress") else "")
             + (f", tag: `{report['tag']}`"
                f"{' (created)' if report['tag_created'] else ' (pre-existing)'}"
                f" [local only — roll back by commit sha]"
                if report["tag"] else ", tag: none"),
             f"- gate argv: `{' '.join(report['gate_argv'])}`"
             f" ({report['gate_seconds_total']}s total)", ""]
    if report.get("tag_collisions"):
        lines.append(
            f"> tag collision: `{report.get('tag_base')}` was already taken; "
            f"this wave got `{report['tag']}`. Previous: "
            + "、".join(f"`{item['tag']}` → `{item['points_at'][:12]}`"
                       for item in report["tag_collisions"]))
        lines.append("")
    if report.get("already_in_tree"):
        lines.append(
            f"> already in the tree from an earlier attempt (no new commit): "
            + "、".join(f"ep{index:03d}" for index in report["already_in_tree"]))
        lines.append("")
    if report.get("skipped"):
        lines.append(f"> skipped: {report['skipped']}")
        lines.append("")
    snapshot = report.get("memory_snapshot") or {}
    if snapshot.get("written"):
        lines.append(f"- memory snapshot: `{snapshot['path']}` "
                     f"({snapshot['file_count']} record(s), "
                     f"{snapshot['bytes']}B, tree `{snapshot.get('tree_sha256')}`)")
    elif snapshot.get("idempotent"):
        lines.append(f"- memory snapshot: already present at `{snapshot['path']}` "
                     f"(byte-identical; no second commit)")
        if snapshot.get("existing_source"):
            lines.append(f"  (that snapshot came from another run root: "
                         f"`{snapshot['existing_source']}`)")
    elif snapshot.get("reason"):
        lines.append(f"- memory snapshot: none — {snapshot['reason']}")
    if snapshot.get("collision"):
        coll = snapshot["collision"]
        lines.append(
            f"- memory snapshot collision: `{coll['base']}` was already taken; "
            f"this wave wrote `{snapshot['path']}` (suffix {coll['suffix']}). "
            f"Skipped: "
            + "、".join(f"`{item['path']}`" for item in coll["skipped"]))
    lines += ["| ep | project | outcome | decision | commit |",
              "|---|---|---|---|---|"]
    for entry in report["candidates"]:
        commit = entry.get("commit") or ""
        gate = entry.get("gate") or {}
        counts = gate.get("counts") or {}
        skipped = counts.get("skipped")
        suffix = (f"（门禁跳过 {skipped} 项——SKIP 不是 PASS）"
                  if skipped else "")
        lines.append(
            f"| {entry['project_index']:03d} | {entry['project_id'][:24]} "
            f"| {entry['terminal_outcome']} | {entry['decision']}{suffix} "
            f"| `{commit[:12]}` |")
    for entry in report["candidates"]:
        if entry.get("reason"):
            lines += ["", f"**ep{entry['project_index']:03d}** "
                          f"({entry['decision']}): {entry['reason']}"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------- spec sync and memory in git

def _health_argv(config: UsineMergeConfig, usine) -> tuple[str, ...]:
    """产线健康分的命令；本仓没有这个包时返回空元组。

    默认自动找 ``packages/eval/bin/feuille-eval.js``（usine 侧的离线健康分
    包）。找不到就**没有**这道闸——但那会被记成 notice，不是静默消失：闸缺席
    与闸失效是两回事，后者才危险。
    """
    if config.health_argv:
        return tuple(str(a) for a in config.health_argv)
    candidate = pathlib.Path(usine) / "packages" / "eval" / "bin" / "feuille-eval.js"
    if candidate.is_file():
        return ("node", str(candidate))
    return ()


def _run_health(argv: tuple[str, ...], cwd, out_path: pathlib.Path) -> dict:
    """跑一次健康分，把报告写到 ``out_path``。

    返回 ``{"ok": bool, "exit_code": int, "tail": str}``。健康分工具自己坏了
    **不拦**合并——真门禁与验证席还在，别让一个辅助工具把整条流水线卡死；
    但它坏了会被记成 notice，一眼看得见。
    """
    proc = subprocess.run([*argv, "health", "--out", str(out_path)], cwd=str(cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=_HEALTH_TIMEOUT)
    tail = (proc.stdout or b"")[-2000:].decode("utf-8", "replace")
    return {"ok": proc.returncode == 0 and out_path.is_file(),
            "exit_code": proc.returncode, "tail": tail}


def _compare_health(argv: tuple[str, ...], cwd, baseline: pathlib.Path,
                    candidate: pathlib.Path) -> dict:
    """比两份健康分报告。退出码 1 = 有指标变坏（这就是合并闸要的判据）。"""
    proc = subprocess.run(
        [*argv, "compare", "--baseline", str(baseline),
         "--candidate", str(candidate), "--json"],
        cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=_HEALTH_TIMEOUT)
    tail = (proc.stdout or b"")[-4000:].decode("utf-8", "replace")
    payload = {}
    try:
        payload = json.loads(tail) if tail.strip().startswith("{") else {}
    except ValueError:
        payload = {}
    return {"exit_code": proc.returncode,
            "regressed": payload.get("regressed") or [],
            "improved": payload.get("improved") or [],
            "not_comparable": payload.get("not_comparable") or [],
            "tail": tail}


def _l3_smoke_argv(config: UsineMergeConfig, ctx: dict) -> tuple[str, ...]:
    """L3「智能体面真验」的冒烟命令；不适用时返回空元组。

    自动发现：冒烟脚本就在本模块旁边（适配层目录）。**但它只在本适配层与被
    改进的仓在同一个仓库里时适用**——那个冒烟检查的是真的 dist 产物，对着
    一个临时仓库跑会检查错树。测试仓与这种部署形态都返回空元组。
    """
    if config.l3_smoke_argv is not None:
        return tuple(str(a) for a in config.l3_smoke_argv)
    here = pathlib.Path(__file__).resolve().parent
    toplevel = pathlib.Path(ctx["toplevel"])
    try:
        here.relative_to(toplevel)
    except ValueError:
        return ()
    script = here / "smoke_agent_surface.py"
    if script.is_file():
        return (sys.executable, str(script))
    return ()


def _run_l3_smoke(argv: tuple[str, ...], cwd) -> dict:
    """跑一次 L3 冒烟。它验的是「改进有没有真到达智能体面」。"""
    proc = subprocess.run(list(argv), cwd=str(cwd), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=_L3_TIMEOUT)
    tail = (proc.stdout or b"")[-4000:].decode("utf-8", "replace")
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
            "tail": tail}


def _spec_sync_violations(usine, delta, candidate_bytes) -> tuple[list[dict], list[dict]]:
    """规范同步闸：改了被规范的代码，规范必须同批更新。

    返回 (违规, 通知)。违规非空 → 候选被拒；通知非空 → 闸没约束到东西或本仓
    不承载那份规范，**不拦但必须被看见**（一道静默失效的闸比没有闸更坏）。

    闸的配置坏了 = 闸静默失效 = 漂移重新变成不可见，所以这里 fail-closed：
    注册表读不出来就抛 ``UsineMergeError``（infra），绝不降级成「没有受管辖
    的文档」。
    """
    try:
        docs = spec_sync.load_registry()
    except spec_sync.SpecSyncError as exc:
        raise UsineMergeError(f"spec-sync registry is broken: {exc}") from exc
    if not docs:
        return [], []

    def read_text(rel):
        try:
            return (pathlib.Path(usine) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    try:
        result = spec_sync.check(docs, delta, candidate_bytes, read_text)
    except spec_sync.SpecSyncError as exc:
        raise UsineMergeError(f"spec-sync check failed: {exc}") from exc
    return result["violations"], result["notices"]


def _memory_tree_hash(files: dict[str, bytes]) -> str | None:
    """用**引擎自己的**树哈希口径算记忆树的摘要。

    不用本地重算：两份口径会分叉，而记忆树的摘要要被拿来和引擎写在事件里的
    ``memory_tree_sha256`` 对账（README §二）。口径的归属模块是
    ``explore.memory_hash``——它只依赖标准库，所以**在没装齐依赖的机器上也能
    导入**；``explore.target_learning._memory_tree_sha256`` 只是它的一层薄包装
    （逐文件 sha256 之后调同一个 ``tree_sha256``），而那个模块要 import openai，
    在纯标准库环境里导不进来。两个都拿不到时返回 None 并如实记为「没算出来」，
    不猜。
    """
    try:
        from explore.memory_hash import tree_sha256
    except ImportError:
        try:
            from explore.target_learning import _memory_tree_sha256
        except ImportError:
            return None
        return _memory_tree_sha256(files)
    hashes = {name: hashlib.sha256(data).hexdigest()
              for name, data in sorted(files.items())}
    return tree_sha256(hashes)


def _read_memory_tree_files(source: pathlib.Path) -> dict[str, bytes]:
    """记忆树目录 → {相对名: 字节}。软链跳过（种子安装器本身就拒绝软链）。"""
    files: dict[str, bytes] = {}
    if not source.is_dir():
        return files
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(source).as_posix()
        files[rel] = path.read_bytes()
    return files


#: 记忆快照目录撞名时最多试多少个后缀（``wave-001-2``、``-3``…）。
_SNAPSHOT_SUFFIX_LIMIT = 1000


def _snapshot_garage_rel(toplevel, snapshot_dir: str) -> str | None:
    """``memory-snapshots/`` 的父目录（相对仓库根）；适配层不在仓库里时 None。"""
    if snapshot_dir:
        return snapshot_dir.strip("/")
    garage_rel = os.path.relpath(str(pathlib.Path(__file__).resolve().parent),
                                  str(toplevel))
    return None if garage_rel.startswith("..") else garage_rel


def memory_snapshot_root(ctx: dict, config: "UsineMergeConfig"
                         ) -> pathlib.Path | None:
    """这次运行会写进哪个 ``memory-snapshots/`` 根（只读，不建目录）。"""
    garage_rel = _snapshot_garage_rel(ctx["toplevel"],
                                      config.memory_snapshot_dir)
    if garage_rel is None:
        return None
    return pathlib.Path(ctx["toplevel"]) / garage_rel / "memory-snapshots"


def _snapshot_state(dest: pathlib.Path, files: dict[str, bytes],
                    tree_hash: str | None) -> tuple[str, dict]:
    """一个快照目录当前是什么状态：``absent`` / ``identical`` / ``different``。

    ``identical`` 的判据是**文件集与字节都一致**，manifest 的哈希只是旁证：
    只比 manifest 会漏掉「目录里有上一轮 run 留下的多余文件」这种形状
    （2026-10-22 实测的 ``wave-001`` 就是 8 个文件、manifest 只描述 3 个）。
    """
    if not dest.exists():
        return "absent", {}
    if not dest.is_dir():
        return "different", {"reason": "path exists but is not a directory"}
    manifest_path = dest / "manifest.json"
    on_disk = _read_memory_tree_files(dest)
    on_disk.pop("manifest.json", None)
    extra = sorted(set(on_disk) - set(files))
    missing = sorted(set(files) - set(on_disk))
    changed = sorted(name for name in set(on_disk) & set(files)
                     if on_disk[name] != files[name])
    detail: dict = {"extra": extra, "missing": missing, "changed": changed}
    if not manifest_path.is_file():
        detail["reason"] = "the directory carries no manifest.json"
        return "different", detail
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        detail["reason"] = f"manifest.json is unreadable: {exc}"
        return "different", detail
    if not isinstance(manifest, dict):
        detail["reason"] = "manifest.json is not an object"
        return "different", detail
    detail["manifest_source"] = str(manifest.get("source") or "")
    detail["manifest_tree_sha256"] = manifest.get("tree_sha256")
    same_bytes = not extra and not missing and not changed
    same_hash = (tree_hash is None
                 or manifest.get("tree_sha256") in (None, tree_hash))
    if same_bytes and same_hash:
        return "identical", detail
    detail["reason"] = "the directory describes a different memory tree"
    return "different", detail


def _snapshot_memory_into_repo(ctx: dict, lineage: pathlib.Path,
                                unit_label: str, index: int,
                                snapshot_dir: str = "") -> dict:
    """把这一波产出的记忆树快照进仓库并单独提交。

    **为什么**：记忆是唯一跨波次传递的东西。它只住在仓库外的 run root 里时
    有一串坏处——评审看不见（改了什么都发现不了）、run root 一清就没了、
    变更不可 diff（记忆被悄悄改过也没人能审）。放进 ``garage/memory-snapshots/``
    之后，记忆的变更和它产出的代码落在同一条提交流里，可以逐条 review。

    提交是**单独一个**（``X-Theatre-Memory`` trailer），不混进候选提交——
    「一候选一 commit」那条规矩管的是代码候选，记忆快照不是候选。

    **撞名纪律**（2026-10-22 修的静默缺陷）：快照名只有「单位 + 波次」，
    而每个 run root 的波次编号都从 1 开始，于是两棵不同 run root 的记忆树
    会写进同一个 ``wave-001/``——盘上 8 个文件，manifest 只描述 3 个，没有
    任何一层会报。现在分四种处置：

    * 目录不存在 → 正常写入；
    * 目录已在且**文件集与字节完全一致** → 幂等重跑，不写、不提交；
    * 目录已在但内容不同，且 manifest 记录的 ``source`` 不是本次 run root
      → 换一个后缀（``wave-001-2``），两份都留着，撞名写进报告与 manifest；
    * 内容不同但 ``source`` 相同 → **fail-closed**：同一个 run root 对同一波
      产出了两棵不同记忆树，这必须先由人看清楚，不能靠加后缀掩盖。
    """
    source = lineage / "memory"
    files = _read_memory_tree_files(source)
    if not files:
        return {"written": False,
                "reason": "the lineage has no memory tree to snapshot yet"}
    toplevel = pathlib.Path(ctx["toplevel"])
    garage_rel = _snapshot_garage_rel(toplevel, snapshot_dir)
    if garage_rel is None:
        # 适配层不在这个仓库里（另一种部署形态）——记下来，不硬塞。
        return {"written": False,
                "reason": f"the adaptation layer is outside the repository "
                          f"({os.path.relpath(str(pathlib.Path(__file__).parent), str(toplevel))})"}
    tree_hash = _memory_tree_hash(files)
    base_rel = f"{garage_rel}/memory-snapshots/{unit_label}-{index:03d}"
    collisions: list[dict] = []
    rel = base_rel
    dest = toplevel / rel
    for suffix in range(1, _SNAPSHOT_SUFFIX_LIMIT + 1):
        rel = base_rel if suffix == 1 else f"{base_rel}-{suffix}"
        dest = toplevel / rel
        state, detail = _snapshot_state(dest, files, tree_hash)
        if state == "absent":
            break
        if state == "identical":
            out = {"written": False,
                   "reason": "already snapshotted: the memory tree on disk is "
                             "byte-identical to this wave's",
                   "idempotent": True,
                   "path": rel,
                   "source": str(source),
                   "tree_sha256": tree_hash,
                   "file_count": len(files),
                   "bytes": sum(len(data) for data in files.values())}
            existing_source = detail.get("manifest_source")
            if existing_source and existing_source != str(source):
                # 另一个 run root 产出了**逐字相同**的记忆树：不写第二份，
                # 但把它的来源标出来，别让「复用」把两条 run 的存在抹掉。
                out["existing_source"] = existing_source
            return out
        if detail.get("manifest_source") == str(source):
            raise UsineMergeError(
                f"memory snapshot {rel} already carries a DIFFERENT tree from "
                f"the same run root ({source}): "
                f"manifest={detail.get('manifest_tree_sha256')}, "
                f"now={tree_hash}, extra={detail.get('extra')}, "
                f"missing={detail.get('missing')}, changed={detail.get('changed')}. "
                f"The same run root produced two memory trees for one wave — "
                f"inspect before merging; do not let a suffix hide it. "
                f"Any candidate commits already landed, but the merge report "
                f"was NOT written: after resolving this, re-running sees "
                f"already_merged candidates and retries the snapshot")
        collisions.append({"path": rel, "state": state,
                           "reason": detail.get("reason"),
                           "manifest_source": detail.get("manifest_source")})
    else:
        raise UsineMergeError(
            f"no free memory-snapshot name under {base_rel!r} after "
            f"{_SNAPSHOT_SUFFIX_LIMIT} suffixes; the repository already "
            f"carries {len(collisions)} colliding snapshot(s) "
            f"({[c['path'] for c in collisions[:3]]} …)")

    unit = pathlib.Path(rel).name
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in files.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(name)
    manifest = {
        "schema_version": 1,
        "unit": unit,
        "source": str(source),
        "files": sorted(written),
        "file_count": len(written),
        "bytes": sum(len(data) for data in files.values()),
        "tree_sha256": tree_hash,
        "tree_sha256_note": (
            "the engine's own tree hash (explore.memory_hash.tree_sha256, the "
            "same口径 explore.target_learning._memory_tree_sha256 uses); null "
            "means the engine was not importable here, so nothing was invented"),
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if suffix > 1:
        manifest["collision"] = {
            "base": base_rel,
            "suffix": suffix,
            "skipped": collisions,
            "note": ("snapshot names carry only unit+wave; a second run root "
                     "starting at wave 1 collides with this one — the suffix "
                     "keeps both trees instead of overwriting either"),
        }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    rel_paths = [f"{rel}/{name}" for name in sorted(written)]
    rel_paths.append(f"{rel}/manifest.json")
    _run_pathspec(["add", "-A"], toplevel, rel_paths)
    _git(["-c", "user.name=theatre-rsi",
          "-c", "user.email=theatre-rsi@explorateur.local",
          "commit", "-m",
          f"theatre-memory({unit_label}-{index}): snapshot the wave's memory tree",
          "-m",
          f"Memory tree snapshot for {unit_label} {index} "
          f"({len(written)} record(s), {manifest['bytes']} bytes).\n"
          f"Tree sha256: {tree_hash}\n\n"
          f"X-Theatre-Memory: {unit_label}-{index}"], cwd=toplevel)
    sha = _git(["rev-parse", "HEAD"], cwd=toplevel) \
        .stdout.decode("utf-8", "replace").strip()
    out = {"written": True,
           "path": rel,
           "tree_sha256": tree_hash,
           "file_count": len(written),
           "bytes": manifest["bytes"],
           "commit": sha}
    if suffix > 1:
        out["collision"] = {"base": base_rel, "suffix": suffix,
                            "skipped": collisions}
    return out


def verify_memory_snapshots(snapshot_root) -> dict:
    """审计一个 ``memory-snapshots/`` 根：manifest 与盘上文件必须对得上。

    这是撞名缺陷的机检版本。2026-10-22 的 ``wave-001`` 有 8 个文件、manifest
    只描述 3 个（两条 run 写进了同一个目录），而当时的任何一层都不报。

    返回 ``{"root", "snapshots", "problems", "hash_checked"}``；``problems``
    每条是 ``{"path", "kind", "detail"}``。``hash_checked`` 为 False 表示这台
    机器导不进引擎的哈希口径（此时**不做**哈希判定，也不假装通过）。
    """
    root = pathlib.Path(snapshot_root)
    out = {"root": str(root), "snapshots": [], "problems": [],
           "hash_checked": True}
    if not root.is_dir():
        return out
    seen_units: dict[str, str] = {}
    for dest in sorted(root.iterdir()):
        if not dest.is_dir():
            continue
        rel = dest.relative_to(root).as_posix()
        manifest_path = dest / "manifest.json"
        on_disk = _read_memory_tree_files(dest)
        on_disk.pop("manifest.json", None)
        entry = {"path": rel, "files": len(on_disk)}
        out["snapshots"].append(entry)
        if not manifest_path.is_file():
            out["problems"].append({
                "path": rel, "kind": "missing_manifest",
                "detail": "a snapshot directory must carry manifest.json"})
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["problems"].append({
                "path": rel, "kind": "unreadable_manifest", "detail": str(exc)})
            continue
        if not isinstance(manifest, dict):
            out["problems"].append({
                "path": rel, "kind": "unreadable_manifest",
                "detail": "manifest.json is not an object"})
            continue
        unit = manifest.get("unit")
        if unit != dest.name:
            out["problems"].append({
                "path": rel, "kind": "unit_name_mismatch",
                "detail": f"manifest unit={unit!r}, directory={dest.name!r}"})
        if isinstance(unit, str):
            if unit in seen_units:
                out["problems"].append({
                    "path": rel, "kind": "duplicate_unit",
                    "detail": f"also claimed by {seen_units[unit]}"})
            else:
                seen_units[unit] = rel
        listed = manifest.get("files")
        if not isinstance(listed, list) or not all(
                isinstance(name, str) for name in listed):
            out["problems"].append({
                "path": rel, "kind": "unreadable_manifest",
                "detail": "manifest.files is not a list of strings"})
            continue
        extra = sorted(set(on_disk) - set(listed))
        missing = sorted(set(listed) - set(on_disk))
        if extra or missing:
            out["problems"].append({
                "path": rel, "kind": "file_set_mismatch",
                "detail": f"extra={extra}, missing={missing}"})
        if manifest.get("file_count") != len(listed):
            out["problems"].append({
                "path": rel, "kind": "manifest_count_mismatch",
                "detail": f"file_count={manifest.get('file_count')!r}, "
                          f"listed={len(listed)}"})
        actual_bytes = {name: on_disk[name] for name in listed
                        if name in on_disk}
        if manifest.get("bytes") != sum(len(b) for b in actual_bytes.values()):
            out["problems"].append({
                "path": rel, "kind": "manifest_bytes_mismatch",
                "detail": f"bytes={manifest.get('bytes')!r}, "
                          f"on_disk={sum(len(b) for b in actual_bytes.values())}"})
        actual_hash = _memory_tree_hash(actual_bytes) if actual_bytes else None
        if actual_hash is None:
            out["hash_checked"] = False
        elif manifest.get("tree_sha256") != actual_hash:
            out["problems"].append({
                "path": rel, "kind": "tree_hash_mismatch",
                "detail": f"manifest={manifest.get('tree_sha256')}, "
                          f"recomputed={actual_hash}"})
    return out


def _merge_progress_path(lineage: pathlib.Path, wave_index: int) -> pathlib.Path:
    return lineage / "waves" / f"wave_{wave_index:03d}" / "merge_progress.json"


def _load_merge_progress(path: pathlib.Path, wave_index: int,
                         config: "UsineMergeConfig", usine_dir) -> dict:
    """读回一次未完成的合并进度；**不自洽就 fail-closed**。

    进度日志存在的唯一理由是覆盖「提交已经落进仓库、tag 或记忆快照还没落」
    的崩溃窗口。它必须由代码证明自己仍然指向这条历史：每个记录的提交都要
    存在，且是当前 HEAD 的祖先；base 提交也一样。历史被改写（rebase/reset）
    之后拿旧日志去补 tag，会把 tag 打到一条不存在的提交上。
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsineMergeError(
            f"{path}: merge progress is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise UsineMergeError(f"{path}: merge progress is not an object")
    if payload.get("schema_version") != 1:
        raise UsineMergeError(
            f"{path}: unsupported merge-progress schema "
            f"{payload.get('schema_version')!r}")
    if payload.get("wave_index") != wave_index:
        raise UsineMergeError(
            f"{path}: progress is for wave {payload.get('wave_index')!r}, "
            f"not {wave_index}")
    if payload.get("unit_label") != config.unit_label:
        raise UsineMergeError(
            f"{path}: progress was written for unit "
            f"{payload.get('unit_label')!r}, this merge is "
            f"{config.unit_label!r}; refusing to mix a wave and a DRS run")
    recorded_prefix = payload.get("tag_prefix")
    if recorded_prefix and recorded_prefix != config.tag_prefix:
        raise UsineMergeError(
            f"{path}: progress was written with tag prefix "
            f"{recorded_prefix!r}, this merge uses {config.tag_prefix!r}; "
            f"changing the prefix mid-wave would tag the same commits twice")
    commits = payload.get("commits")
    if not isinstance(commits, list) or not all(
            isinstance(sha, str) and sha for sha in commits):
        raise UsineMergeError(f"{path}: progress.commits is not a list of shas")
    head = _git(["rev-parse", "HEAD"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()
    for sha in commits:
        exists = _git(["cat-file", "-e", f"{sha}^{{commit}}"],
                      cwd=usine_dir, check=False)
        if exists.returncode != 0:
            raise UsineMergeError(
                f"{path}: recorded commit {sha} no longer exists; the history "
                f"this progress refers to was rewritten")
        ancestor = _git(["merge-base", "--is-ancestor", sha, head],
                        cwd=usine_dir, check=False)
        if ancestor.returncode != 0:
            raise UsineMergeError(
                f"{path}: recorded commit {sha} is not an ancestor of HEAD "
                f"({head[:12]}); refusing to recover a tag across a rewritten "
                f"history")
    base = payload.get("base_commit")
    if base:
        ancestor = _git(["merge-base", "--is-ancestor", base, head],
                        cwd=usine_dir, check=False)
        if ancestor.returncode != 0:
            raise UsineMergeError(
                f"{path}: recorded base {base} is not an ancestor of HEAD; "
                f"the repository history was rewritten mid-wave")
    return payload


#: 合并是**仓库级**临界区：两个 run root 同时合并会把提交、tag 与快照交错在
#: 一起。锁文件放在 git common dir（`--git-common-dir`，worktree 也指向主仓的
#: .git），不进工作树；用 OS 排他锁，进程退出时自动释放——不会有需要人手清的
#: stale lock。等待上限由环境变量控制；0 = 只试一次。
_MERGE_LOCK_ENV = "RSIAGENT_MERGE_LOCK_TIMEOUT"
_MERGE_LOCK_DEFAULT_TIMEOUT = 300.0
_MERGE_LOCK_POLL_SECS = 0.25
_MERGE_LOCK_NAME = "rsiagent-usine-merge.lock"


def _merge_lock_timeout() -> float:
    raw = os.environ.get(_MERGE_LOCK_ENV, "").strip()
    if not raw:
        return _MERGE_LOCK_DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError as exc:
        raise UsineMergeError(
            f"{_MERGE_LOCK_ENV} must be a number of seconds, got {raw!r}") from exc
    if value < 0:
        raise UsineMergeError(f"{_MERGE_LOCK_ENV} must be >= 0, got {value}")
    return value


def _merge_lock_path(usine_dir) -> pathlib.Path:
    """仓库级合并锁的路径（git common dir 下，不进工作树）。"""
    out = _git(["rev-parse", "--git-common-dir"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()
    if not out:
        raise UsineMergeError(
            f"cannot resolve the git common dir of {usine_dir}")
    path = pathlib.Path(out)
    if not path.is_absolute():
        # 在 usine 子树里 `--git-common-dir` 返回 `../.git`，相对的是 cwd。
        path = pathlib.Path(usine_dir) / path
    return path.resolve() / _MERGE_LOCK_NAME


def _lock_fd_exclusive(fd: int) -> None:
    """尝试拿排他锁；被占用时抛 `BlockingIOError`（跨平台）。"""
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt

        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, 0)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError("merge lock is held") from exc
        return
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt

        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(fd, fcntl.LOCK_UN)


def _read_lock_metadata(path: pathlib.Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "(unreadable)"
    return raw[:400] or "(empty)"


class _MergeLock:
    """仓库级合并锁：OS 排他锁 + 一段用于诊断的持有者元数据。"""

    def __init__(self, path: pathlib.Path, timeout: float, metadata: dict):
        self.path = path
        self.timeout = timeout
        self.metadata = metadata
        self.fd: int | None = None

    def acquire(self) -> "_MergeLock":
        deadline = time.monotonic() + self.timeout
        while True:
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
            try:
                _lock_fd_exclusive(fd)
            except BlockingIOError:
                os.close(fd)
                if time.monotonic() >= deadline:
                    raise UsineMergeError(
                        f"another run holds the usine merge lock at "
                        f"{self.path} (waited {self.timeout:g}s). Holder: "
                        f"{_read_lock_metadata(self.path)}. Two run roots "
                        f"merging into the same repository would interleave "
                        f"commits/tags — wait for it, or set "
                        f"{_MERGE_LOCK_ENV} and retry; merge_pending_waves "
                        f"will pick this wave up on the next start")
                time.sleep(_MERGE_LOCK_POLL_SECS)
                continue
            except OSError as exc:
                os.close(fd)
                raise UsineMergeError(
                    f"could not lock the usine merge lock {self.path}: "
                    f"{exc}") from exc
            self.fd = fd
            try:
                self._write_metadata()
            except BaseException:
                # 元数据写失败（磁盘满、权限）时**必须先把锁放掉**：否则
                # 长驻的 wave 循环会一直持有 fd，后面所有合并都等这把锁。
                self.release()
                raise
            return self

    def _write_metadata(self) -> None:
        blob = (json.dumps(self.metadata, ensure_ascii=False, sort_keys=True)
                + "\n").encode("utf-8")
        os.lseek(self.fd, 0, 0)
        if os.name == "nt":
            # Windows 的字节锁锁的是第 0 个字节；truncate 到 0 会动到锁区，
            # 所以用定长填充覆盖，读的一方 strip 掉尾部空格。
            os.write(self.fd, blob.ljust(1024, b" ")[:1024])
        else:
            os.ftruncate(self.fd, 0)
            os.write(self.fd, blob)
        try:
            os.fsync(self.fd)
        except OSError:
            pass

    def release(self) -> None:
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            _unlock_fd(fd)
        except OSError as exc:
            # 解锁失败不该掩盖调用方的异常；close 本身也会释放 OS 锁。
            log.warning("could not unlock %s (%s); closing the fd releases it",
                        self.path, exc)
        finally:
            os.close(fd)

    def __enter__(self) -> "_MergeLock":
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.release()


def _acquire_merge_lock(usine_dir, lineage: pathlib.Path,
                        wave_index: int) -> _MergeLock:
    metadata = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "acquired_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "lineage": str(lineage),
        "wave_index": wave_index,
        "usine_dir": str(usine_dir),
    }
    lock = _MergeLock(_merge_lock_path(usine_dir), _merge_lock_timeout(),
                      metadata)
    return lock.acquire()


def _reported_wave(report_path: pathlib.Path, progress_path: pathlib.Path,
                   wave_index: int) -> dict | None:
    """这一波已经有报告了吗；有就返回它（并清掉残留的进度日志）。"""
    if not report_path.is_file():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["skipped"] = "report_exists"
    if progress_path.is_file():
        # 报告是权威记录；上一次写完之后没来得及清掉的进度日志是残留。
        progress_path.unlink(missing_ok=True)
    log.info("wave %s already carries a merge report", wave_index)
    return report


def merge_wave(lineage_root, wave_index: int,
               config: UsineMergeConfig) -> dict:
    """Merge one fully closed wave; idempotent (a reported wave is a no-op).

    The whole merge (preconditions -> commits -> tag -> snapshot -> report) runs
    under a **repository-level** exclusive lock, so two run roots cannot
    interleave commits and tags in the same repository.  The lock lives in the
    git common dir and is an OS lock: a crashed process releases it
    automatically (no stale lock to clean by hand).  A second merge waits up to
    ``RSIAGENT_MERGE_LOCK_TIMEOUT`` seconds (default 300; 0 = try once), then
    fails with the holder's metadata.
    """
    lineage = pathlib.Path(lineage_root)
    wave_dir = lineage / "waves" / f"wave_{wave_index:03d}"
    report_path = wave_dir / "merge_report.json"
    progress_path = _merge_progress_path(lineage, wave_index)
    report = _reported_wave(report_path, progress_path, wave_index)
    if report is not None:
        return report
    usine = pathlib.Path(config.usine_dir)
    ctx = _repo_context(usine)
    lock = _acquire_merge_lock(usine, lineage, wave_index)
    try:
        # 等锁期间另一个进程可能已经把这一波做完了：必须在**锁内**重查，
        # 否则我们会拿一份过期的「报告不存在」去重复提交。
        report = _reported_wave(report_path, progress_path, wave_index)
        if report is not None:
            return report
        return _merge_wave_locked(lineage, wave_index, config, ctx, usine,
                                  report_path, progress_path)
    finally:
        lock.release()


def _merge_wave_locked(lineage: pathlib.Path, wave_index: int,
                       config: UsineMergeConfig, ctx: dict, usine: pathlib.Path,
                       report_path: pathlib.Path,
                       progress_path: pathlib.Path) -> dict:
    """`merge_wave` 的临界区；调用方必须已经持有仓库级合并锁。"""
    wave_dir = lineage / "waves" / f"wave_{wave_index:03d}"
    outcomes = _wave_outcomes(lineage, wave_index)
    if not outcomes:
        raise UsineMergeError(
            f"wave {wave_index} has no closed episodes under {lineage}")
    base_commit = _assert_preconditions(ctx, usine)

    resumed = (_load_merge_progress(progress_path, wave_index,
                                    config, usine)
               if progress_path.is_file() else None)
    prior_commits = list((resumed or {}).get("commits") or [])
    progress = {
        "schema_version": 1,
        "wave_index": wave_index,
        "unit_label": config.unit_label,
        "commit_scope": config.commit_scope,
        "tag_prefix": config.tag_prefix,
        "base_commit": (resumed or {}).get("base_commit") or base_commit,
        "status": "started",
        "commits": prior_commits,
        "tag": (resumed or {}).get("tag"),
        "memory_snapshot": (resumed or {}).get("memory_snapshot"),
        "started_at": (resumed or {}).get("started_at")
                      or time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _atomic_json(progress_path, progress)

    commits: list[str] = []
    gate_seconds = 0.0
    candidates: list[dict] = []
    log.info("wave %s merge start: %d episode(s), base %s%s",
             wave_index, len(outcomes), base_commit[:10],
             f", resuming {len(prior_commits)} recorded commit(s)"
             if prior_commits else "")
    for outcome in outcomes:
        entry = {"project_index": outcome["project_index"],
                 "project_id": outcome["project_id"],
                 "episode": outcome["episode"],
                 "terminal_outcome": outcome["terminal_outcome"],
                 "decision": "", "reason": "", "commit": None, "gate": None,
                 "delta": None, "pre_applied": 0, "excluded": 0,
                 "symlinks_unchanged": 0}
        candidates.append(entry)
        if outcome["terminal_outcome"] != "PASS":
            entry["decision"] = "not_pass"
            continue
        episode_dir = lineage / "episodes" / outcome["episode"]
        candidate_dir = episode_dir / "candidates" / "cycle_001"
        if not (candidate_dir / "materials.tgz").is_file():
            raise UsineMergeError(
                f"{outcome['episode']}: PASS episode lost its candidate archive")
        fixture = load_archive_inventory(
            _baseline_dir(lineage, wave_index, episode_dir),
            f"{outcome['episode']} baseline")
        candidate = load_archive_inventory(candidate_dir,
                                           f"{outcome['episode']} candidate")
        delta = candidate_delta(fixture["files"], candidate["files"])
        entry["delta"] = {key: delta[key] for key in
                          ("modified", "added", "deleted")}
        entry["excluded"] = len(candidate["excluded"])
        links = symlink_changes(fixture["symlinks"], candidate["symlinks"])
        entry["symlinks_unchanged"] = links["unchanged"]
        if links["changed"] or links["added"] or links["removed"]:
            entry["decision"] = "symlink_unsupported"
            entry["reason"] = ("symlink changes are not merged: "
                               f"{len(links['changed'])} changed, "
                               f"{len(links['added'])} added, "
                               f"{len(links['removed'])} removed")
            continue
        if not (delta["modified"] or delta["added"] or delta["deleted"]):
            entry["decision"] = "merged_noop"
            entry["reason"] = "candidate is byte-identical to its baseline"
            continue
        violations = path_policy_violations(delta["added"], ctx, usine)
        if violations:
            entry["decision"] = "path_policy_skipped"
            entry["reason"] = "; ".join(
                f"{rel}: {why}" for rel, why in sorted(violations.items())[:3])
            continue
        # The baseline and candidate bytes for the delta paths are needed
        # BEFORE the verdict: the drift check compares the working tree
        # against them both raw and line-ending-folded, and the apply step
        # reuses the candidate bytes.
        #
        # Each archive is asked only for the paths it can hold: an ADDED
        # path is absent from the baseline archive and a DELETED path is
        # absent from the candidate archive.  Asking either archive for a
        # path it does not have is a hard error ("candidate archive lost
        # members"), not a shrug.
        baseline_bytes = _extract_members(
            _baseline_dir(lineage, wave_index, episode_dir),
            [*delta["modified"], *delta["deleted"]], fixture["files"])
        wanted = _extract_members(
            candidate_dir, [*delta["modified"], *delta["added"]],
            candidate["files"])
        verdict, details = classify_delta(
            delta, fixture["files"], candidate["files"], usine,
            {rel: _normalized_sha(data) for rel, data in baseline_bytes.items()},
            {rel: _normalized_sha(data) for rel, data in wanted.items()})
        entry["pre_applied"] = details.get("pre_applied", 0)
        if verdict == "already_merged":
            entry["decision"] = "already_merged"
            entry["reason"] = "every delta path already carries the candidate bytes"
            continue
        if verdict == "drift":
            entry["decision"] = "drift_skipped"
            entry["reason"] = details["reason"]
            continue
        # 规范同步闸：改了被规范的代码而没同批更新规范 → 整条候选跳过。
        # 放在 apply 之前是为了不白花门禁时间——这道闸是二值判定，读文件就够。
        sync_violations, sync_notices = _spec_sync_violations(usine, delta, wanted)
        if sync_notices:
            entry["spec_sync_notices"] = sync_notices
            log.info("ep%03d spec-sync notice: %s", outcome["project_index"],
                     spec_sync.describe_notices(sync_notices))
        if sync_violations:
            entry["decision"] = "spec_sync_rejected"
            entry["reason"] = spec_sync.describe(sync_violations)
            entry["spec_sync"] = sync_violations
            log.warning("ep%03d rejected by the spec-sync gate: %s",
                        outcome["project_index"], entry["reason"])
            continue
        executable = (_archive_exec_bits(
            candidate_dir, [*delta["modified"], *delta["added"]])
            | _tracked_exec_bits(
                ctx, [rel for rel in delta["modified"]
                      if rel not in delta["added"]]))
        snapshot = _snapshot_tree(usine, delta)
        # 健康分的**基线**：在应用候选之前量一次工作树。这是「比合并前更好
        # 没有」的那条判据的起点——门禁只防退化，健康分才谈变好。
        health_argv = _health_argv(config, usine)
        health_baseline = None
        if health_argv:
            fd, base_path = tempfile.mkstemp(prefix="usine-health-base-",
                                             suffix=".json")
            os.close(fd)
            baseline_report = _run_health(health_argv, usine,
                                          pathlib.Path(base_path))
            if baseline_report["ok"]:
                health_baseline = pathlib.Path(base_path)
            else:
                os.unlink(base_path)
                entry["health_notice"] = (
                    "产线健康分跑不起来，这道闸本次没有生效："
                    + baseline_report["tail"].strip()[-200:])
                log.warning("ep%03d health baseline failed: %s",
                            outcome["project_index"],
                            baseline_report["tail"].strip()[-200:])
        try:
            _apply_delta(usine, delta, wanted, executable)
            gate = run_gate(config, usine)
            entry["gate"] = gate
            gate_seconds += gate["seconds"]
            _gate_side_effects(ctx, usine, delta, entry)
            if gate["exit_code"] != 0:
                _rollback_delta(usine, delta, snapshot)
                entry["decision"] = "gate_rejected"
                entry["reason"] = f"usine gate exit {gate['exit_code']}"
                log.warning("ep%03d rejected by the usine gate (exit %s)",
                            outcome["project_index"], gate["exit_code"])
                continue
            # L3「改进有没有真到达智能体面」：门禁跑完 dist 已经重建，这时
            # 验它比在门禁之前验更准。失败即整条候选作废——改进没到达智能体
            # 面，就不算改进。
            l3_argv = _l3_smoke_argv(config, ctx)
            if l3_argv:
                l3 = _run_l3_smoke(l3_argv, ctx["toplevel"])
                entry["l3"] = {"exit_code": l3["exit_code"],
                               "ok": l3["ok"], "tail": l3["tail"][-800:]}
                if not l3["ok"]:
                    _rollback_delta(usine, delta, snapshot)
                    entry["decision"] = "l3_rejected"
                    entry["reason"] = ("改进没有到达智能体面（L3 冒烟红）："
                                       + l3["tail"].strip()[-300:])
                    log.warning("ep%03d rejected by the L3 agent-surface smoke",
                                outcome["project_index"])
                    continue
            # 健康分：候选落地后的那一份，与基线逐指标比。有指标变坏 → 作废。
            if health_argv and health_baseline is not None:
                fd, cand_path = tempfile.mkstemp(prefix="usine-health-cand-",
                                                 suffix=".json")
                os.close(fd)
                candidate_report = _run_health(health_argv, usine,
                                               pathlib.Path(cand_path))
                if candidate_report["ok"]:
                    comparison = _compare_health(health_argv, usine,
                                                 health_baseline,
                                                 pathlib.Path(cand_path))
                    entry["health"] = {
                        "baseline": str(health_baseline),
                        "candidate": cand_path,
                        "regressed": comparison["regressed"],
                        "improved": comparison["improved"],
                        "not_comparable": comparison["not_comparable"],
                        "exit_code": comparison["exit_code"],
                    }
                    if comparison["exit_code"] != 0:
                        _rollback_delta(usine, delta, snapshot)
                        entry["decision"] = "health_rejected"
                        entry["reason"] = (
                            "产线健康分变坏："
                            + "、".join(comparison["regressed"])
                            + "（门禁只防退化，这道闸才问「更好了没有」）")
                        log.warning("ep%03d rejected by the health gate: %s",
                                    outcome["project_index"],
                                    "、".join(comparison["regressed"]))
                        os.unlink(cand_path)
                        continue
                else:
                    entry["health_notice"] = (
                        "候选侧的健康分跑不起来，本次没有比较："
                        + candidate_report["tail"].strip()[-200:])
                os.unlink(cand_path)
            if health_baseline is not None:
                try:
                    os.unlink(health_baseline)
                except OSError:
                    pass
            _stage_delta(usine, delta)
            quiet = _git(["diff", "--cached", "--quiet"], cwd=usine,
                         check=False)
            if quiet.returncode == 0:
                entry["decision"] = "merged_noop"
                entry["reason"] = ("gate left the delta byte-identical to "
                                   "HEAD; nothing to commit")
                continue
            sha = _commit_candidate(config, usine, wave_index, outcome,
                                    delta, gate)
            commits.append(sha)
            progress["commits"] = prior_commits + commits
            progress["status"] = "committing"
            progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _atomic_json(progress_path, progress)
            entry["decision"] = "merged"
            entry["commit"] = sha
            log.info("ep%03d merged as %s", outcome["project_index"],
                     sha[:10])
        except BaseException:
            try:
                _rollback_delta(usine, delta, snapshot)
            except UsineMergeError:
                log.exception("rollback also failed; the usine tree is dirty")
            raise
    all_commits = prior_commits + commits
    tag_info = ({"tag": None, "tag_created": False} if not all_commits
                else _ensure_wave_tag(config, usine, wave_index, all_commits))
    progress["tag"] = tag_info
    progress["status"] = "tagged"
    progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _atomic_json(progress_path, progress)
    # 记忆快照进仓库：记忆是唯一跨波次传递的东西，它必须在同一条提交流里
    # 可 review、可 diff。放在所有候选提交之后——树在那一刻是干净的。
    #
    # **`already_merged` / `merged_noop` 也算「候选已经在树里」**：崩溃重跑时
    # 候选的字节已由上一次尝试提交，这一次没有新提交（`commits` 为空）。旧条件
    # `if not commits` 会跳过快照，并在报告里写「no candidate was merged」——
    # 那句话是假的，这一波的记忆于是永远进不了仓库。真正没进树的只有
    # drift / gate 拒绝。
    already_in_tree = [entry["project_index"] for entry in candidates
                       if entry.get("decision") in {"merged_noop",
                                                    "already_merged"}]
    if not all_commits and not already_in_tree:
        memory_snapshot = {"written": False,
                           "reason": "no candidate reached the tree"}
    else:
        memory_snapshot = _snapshot_memory_into_repo(
            ctx, lineage, config.unit_label, wave_index,
            config.memory_snapshot_dir)
    progress["memory_snapshot"] = memory_snapshot
    progress["status"] = "done"
    progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _atomic_json(progress_path, progress)
    report = {"schema_version": 1, "wave_index": wave_index,
              "usine_dir": str(usine), "repo_toplevel": ctx["toplevel"],
              "repo_prefix": ctx["prefix"], "base_commit": base_commit,
              "gate_argv": [str(a) for a in config.gate_argv],
              "commits": all_commits,
              "commits_made_this_run": len(commits),
              "resumed_from_progress": resumed is not None,
              "gate_seconds_total": round(gate_seconds, 1),
              "already_in_tree": already_in_tree,
              "candidates": candidates,
              "anchors": _report_anchors(all_commits, tag_info),
              "memory_snapshot": memory_snapshot,
              "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **tag_info}
    _atomic_json(report_path, report)
    _atomic_text(wave_dir / "merge_report.md", _render_md(report))
    # 报告落盘之后进度日志就只是残留了；留着会让下一次误以为还有未完成的事。
    progress_path.unlink(missing_ok=True)
    log.info("wave %s merge done: %d commit(s) total (%d this run), tag=%s",
             wave_index, len(all_commits), len(commits), report["tag"])
    return report


def _drs_merge_outcomes(lineage: pathlib.Path) -> list[str]:
    """Write the Phase-1-shaped record beside every closed DRS episode.

    The engine's ``outcome.json`` for a DRS episode carries
    ``terminal_outcome`` but no ``wave_index`` / ``project_id``: it closed
    with ``PROJECT_CLOSED``, not ``PHASE1_WAVE_COMPLETED``.  The wave
    reader needs those two fields, so the merge writes a SIBLING record,
    ``merge_outcome.json``, and leaves the engine's file byte-for-byte
    alone.  The project id is derived from the project text, so it is
    stable across runs of the same drill.
    """
    episodes_dir = lineage / "episodes"
    if not episodes_dir.is_dir():
        raise UsineMergeError(f"no episodes under {lineage}")
    recorded: list[str] = []
    for directory in sorted(episodes_dir.iterdir()):
        outcome_path = directory / "outcome.json"
        if not outcome_path.is_file():
            continue
        try:
            record = json.loads(outcome_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsineMergeError(
                f"{directory.name}: outcome.json is unreadable: {exc}") from exc
        if not isinstance(record, dict):
            continue
        if record.get("terminal_outcome") not in {"PASS", "FAIL"}:
            continue
        project_text = str(record.get("project") or "")
        project_id = "drs-" + hashlib.sha256(
            project_text.encode("utf-8")).hexdigest()[:12]
        _atomic_json(directory / "merge_outcome.json", {
            "wave_index": 1,
            "project_index": int(record.get("project_index") or 1),
            "project_id": project_id,
            "terminal_outcome": record["terminal_outcome"],
            "source": "drs_phase2_episode",
            "engine_outcome": str(outcome_path),
        })
        recorded.append(directory.name)
    return recorded


def _drs_config(config: UsineMergeConfig) -> UsineMergeConfig:
    """The DRS flavour of a merge config: its own tag, scope and unit label.

    The DRS tag is ``theatre/drs-1``, not ``theatre/wave/drs-1``: the
    default prefix is "theatre/wave" (a breadth wave), and the DRS keeps
    the namespace root it shares with Phase 1.  The commit scope says
    "drs" and the unit label says "drs", so no part of the commit claims
    this was a wave.
    """
    prefix = config.tag_prefix
    if prefix.endswith("/wave"):
        prefix = prefix[: -len("/wave")]
    return replace(config, tag_prefix=f"{prefix}/drs",
                   commit_scope=f"{config.commit_scope}-drs",
                   unit_label="drs")


def plan_drs_run(lineage_root, config: UsineMergeConfig) -> dict:
    """Preview a DRS merge: what would land, and would it be allowed to.

    Read-only with respect to the REPOSITORY: nothing is applied, no gate
    runs, no commit and no tag are created.  (It does write the same
    ``merge_outcome.json`` the merge writes, inside the RUN ROOT — the
    wave reader needs it, and the run root is the DRS's own scratch space.)

    The verdict per episode is the same one the merge would reach:
    ``fresh`` (the delta may be applied), ``already_merged`` (the working
    tree already carries the candidate bytes) or ``drift`` (the working
    tree matches neither the baseline nor the candidate — the merge would
    skip the candidate whole).
    """
    lineage = pathlib.Path(lineage_root)
    recorded = _drs_merge_outcomes(lineage)
    if not recorded:
        raise UsineMergeError(
            f"no closed DRS episode under {lineage / 'episodes'} to merge")
    drs_config = _drs_config(config)
    usine = pathlib.Path(config.usine_dir)
    episodes = []
    for name in recorded:
        episode_dir = lineage / "episodes" / name
        candidate_dir = episode_dir / "candidates" / "cycle_001"
        fixture = load_archive_inventory(
            _baseline_dir(lineage, 1, episode_dir), f"{name} baseline")
        candidate = load_archive_inventory(candidate_dir, f"{name} candidate")
        delta = candidate_delta(fixture["files"], candidate["files"])
        baseline_bytes = _extract_members(
            _baseline_dir(lineage, 1, episode_dir),
            [*delta["modified"], *delta["deleted"]], fixture["files"])
        wanted = _extract_members(
            candidate_dir, [*delta["modified"], *delta["added"]],
            candidate["files"])
        verdict, details = classify_delta(
            delta, fixture["files"], candidate["files"], usine,
            {rel: _normalized_sha(data) for rel, data in baseline_bytes.items()},
            {rel: _normalized_sha(data) for rel, data in wanted.items()})
        episodes.append({
            "episode": name,
            "verdict": verdict,
            "reason": details.get("reason", ""),
            "pre_applied": details.get("pre_applied", 0),
            "delta": {key: delta[key] for key in
                      ("modified", "added", "deleted")},
        })
    return {
        "schema_version": 1,
        "usine_dir": str(usine),
        # 只读预览：撞名时这里是**会真正创建的那个后缀 tag**，不是 base 名。
        "tag": _next_free_tag(drs_config, usine, 1),
        "commit_scope": drs_config.commit_scope,
        "gate_argv": [str(a) for a in config.gate_argv],
        "episodes": episodes,
        "would_merge": any(entry["verdict"] == "fresh" for entry in episodes),
    }


def merge_drs_run(lineage_root, config: UsineMergeConfig) -> dict:
    """Merge a DRS (Phase 2) episode's candidate into the usine tree.

    The DRS's serial core closes an episode with ``PROJECT_CLOSED``, not
    ``PHASE1_WAVE_COMPLETED``, so the wave-merge event sink never fires and
    the DRS's candidate — verifier PASS, offline gate green — stays in the
    run root, where nobody can see it in the repository.  A DRS episode's
    archives are shaped exactly like a Phase-1 episode's (the candidate at
    ``episodes/<ep>/candidates/cycle_001``, the baseline at
    ``episodes/<ep>/fixtures``), so the SAME merge machinery applies: the
    delta, the drift check, the offline gate, the commit and the tag.

    What this adds is the Phase-1-shaped record the reader expects
    (``wave_index`` / ``project_id``) and a distinct tag prefix, so a DRS
    merge is never mistaken for a breadth wave.  The engine's own
    ``outcome.json`` is never rewritten: the merge record is a sibling
    file, ``merge_outcome.json``.

    The gate runs here too.  A DRS candidate is not "already merged" just
    because it passed in the guest — it is re-gated against the REAL tree
    before it lands there, which is the only proof that it does not break
    the repository it is about to enter.
    """
    lineage = pathlib.Path(lineage_root)
    recorded = _drs_merge_outcomes(lineage)
    if not recorded:
        raise UsineMergeError(
            f"no closed DRS episode under {lineage / 'episodes'} to merge")
    drs_config = _drs_config(config)
    report = merge_wave(lineage_root, 1, drs_config)
    report["drs_episodes"] = recorded
    return report


def _completed_waves(lineage: pathlib.Path) -> set:
    """Wave indexes confirmed closed by the PHASE1_WAVE_COMPLETED event log."""
    path = lineage / "events.jsonl"
    if not path.is_file():
        raise UsineMergeError(
            "lineage has unmerged waves but no events.jsonl "
            "completed-wave log")
    waves = set()
    for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise UsineMergeError(
                f"events.jsonl line {number} is malformed") from exc
        if record.get("event_type") == "PHASE1_WAVE_COMPLETED":
            wave = (record.get("payload") or {}).get("wave")
            if type(wave) is not int:
                raise UsineMergeError(
                    "events.jsonl PHASE1_WAVE_COMPLETED without a wave index")
            waves.add(wave)
    return waves


def merge_pending_waves(lineage_root, config: UsineMergeConfig) -> list:
    """Catch-up merge for waves that closed but never merged (crash resume).

    Only waves confirmed by a ``PHASE1_WAVE_COMPLETED`` event are merged, so
    a wave that died mid-branch (some episodes without outcome.json) is
    never partially merged. Waves are merged in ascending order; each merge
    is idempotent through its report file.
    """
    lineage = pathlib.Path(lineage_root)
    waves = sorted({record["wave_index"] for record in _read_outcomes(lineage)})
    pending = [wave for wave in waves
               if not (lineage / "waves" / f"wave_{wave:03d}"
                       / "merge_report.json").is_file()]
    if not pending:
        return []
    completed = _completed_waves(lineage)
    reports = []
    for wave in pending:
        if wave not in completed:
            log.warning("wave %s has closed episodes but no "
                        "PHASE1_WAVE_COMPLETED event; leaving it unmerged",
                        wave)
            continue
        reports.append(merge_wave(str(lineage), wave, config))
    return reports


def wave_merge_event_sink(lineage_root, config: UsineMergeConfig,
                          inner=None):
    """Event sink that merges each completed wave into the usine tree.

    Every event is forwarded to ``inner`` first (run_usine passes the
    events.jsonl logger; ``validate_boundary`` depends on the completed-wave
    record surviving a merge crash). Only ``PHASE1_WAVE_COMPLETED`` with
    status ``completed`` triggers a merge; a merge failure propagates as
    ``UsineMergeError`` so the wave loop halts fail-closed and the wave is
    re-merged by ``merge_pending_waves`` on the next run.
    """
    def sink(event_type, status="in_progress", state=None, payload=None,
             **kwargs):
        if inner is not None:
            inner(event_type, status=status, state=state, payload=payload,
                  **kwargs)
        if event_type != "PHASE1_WAVE_COMPLETED" or status != "completed":
            return
        wave = (payload or {}).get("wave")
        if type(wave) is not int:
            raise UsineMergeError(
                f"PHASE1_WAVE_COMPLETED without a wave index: {payload!r}")
        report = merge_wave(lineage_root, wave, config)
        if inner is not None:
            inner("USINE_WAVE_MERGED", status="completed",
                  state={"project_open": False, "memory_phase_open": False,
                         "recovery_open": False},
                  payload={"wave": report["wave_index"],
                           "commits": report.get("commits", []),
                           "tag": report.get("tag"),
                           "skipped": report.get("skipped"),
                           "decisions": {
                               entry["project_index"]: entry["decision"]
                               for entry in report.get("candidates", [])}})
    return sink


# ----------------------------------------------------------------------- CLI

def _main(argv: list[str] | None = None) -> int:
    """`python3 garage/wave_merge.py verify-memory-snapshots [ROOT]`。

    这是撞名缺陷的**机检入口**：manifest 与盘上文件对不上就退出 1。
    默认根是适配层旁边的 ``memory-snapshots/``（真实布局），也给显式路径。
    """
    import argparse

    ap = argparse.ArgumentParser(description="usine wave merge helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    verify = sub.add_parser(
        "verify-memory-snapshots",
        help="审计 memory-snapshots/：manifest 与盘上文件必须对得上")
    verify.add_argument(
        "root", nargs="?", default=None,
        help="快照根目录（默认是 garage/memory-snapshots/）")
    verify.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)
    if args.cmd == "verify-memory-snapshots":
        root = (pathlib.Path(args.root) if args.root
                else pathlib.Path(__file__).resolve().parent / "memory-snapshots")
        audit = verify_memory_snapshots(root)
        if args.json:
            print(json.dumps(audit, ensure_ascii=False, indent=2))
        else:
            print(f"memory snapshots: {len(audit['snapshots'])} under {audit['root']}")
            if not audit["hash_checked"]:
                print("  hash: NOT checked (the engine's memory_hash was not importable)")
            for problem in audit["problems"]:
                print(f"  FAIL {problem['path']}: {problem['kind']} — "
                      f"{problem['detail']}")
            if not audit["problems"]:
                print("  all snapshots match their manifests")
        return 1 if audit["problems"] else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
