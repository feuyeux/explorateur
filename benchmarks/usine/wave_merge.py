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
import stat as stat_module
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import PurePosixPath

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
    gate_env: dict | None = None


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

def _tree_state(path: pathlib.Path) -> tuple[str, str | None]:
    """(kind, sha) for a working-tree path: file/missing/dir/special/error."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "error", None
    if stat_module.S_ISDIR(info.st_mode):
        return "dir", None
    if not stat_module.S_ISREG(info.st_mode):
        return "special", None
    return "file", hashlib.sha256(path.read_bytes()).hexdigest()


def classify_delta(delta: dict, fixture_files: dict, candidate_files: dict,
                   usine_dir) -> tuple[str, dict]:
    """Tri-state every delta path against the working tree.

    Returns ``(verdict, details)`` with verdict:

    * ``already_merged`` — every delta path already carries the candidate
      bytes (idempotent catch-up after a mid-wave crash);
    * ``fresh`` — every delta path carries the baseline bytes (or is absent,
      for additions); safe to apply, ``pre_applied`` counts candidate-state
      paths inside a mixed verdict;
    * ``drift`` — some path matches neither the baseline nor the candidate;
      the candidate is skipped whole.
    """
    root = pathlib.Path(usine_dir)
    states: dict[str, str] = {}
    for rel in delta["modified"]:
        kind, sha = _tree_state(root.joinpath(*PurePosixPath(rel).parts))
        if kind == "file" and sha == candidate_files[rel]:
            states[rel] = "candidate"
        elif kind == "file" and sha == fixture_files[rel]:
            states[rel] = "fixture"
        else:
            states[rel] = "other"
    for rel in delta["added"]:
        kind, sha = _tree_state(root.joinpath(*PurePosixPath(rel).parts))
        if kind == "missing":
            states[rel] = "fixture"
        elif kind == "file" and sha == candidate_files[rel]:
            states[rel] = "candidate"
        else:
            states[rel] = "other"
    for rel in delta["deleted"]:
        kind, sha = _tree_state(root.joinpath(*PurePosixPath(rel).parts))
        if kind == "missing":
            states[rel] = "candidate"
        elif kind == "file" and sha == fixture_files[rel]:
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
    return {"exit_code": proc.returncode,
            "seconds": round(time.time() - started, 1), "tail": tail}


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
    subject = (f"{config.commit_scope}(wave-{wave_index}): "
               f"accept ep{outcome['project_index']:03d} "
               f"({_clean_id(outcome['project_id'])})")
    body = (
        f"Candidate ep{outcome['project_index']:03d} merged from wave "
        f"{wave_index} (verifier PASS, usine gate green).\n"
        f"Delta: {len(delta['modified'])} modified, {len(delta['added'])} "
        f"added, {len(delta['deleted'])} deleted.\n"
        f"Gate exit {gate['exit_code']} in {gate['seconds']}s.\n\n"
        f"X-Theatre-Wave: {wave_index}\n"
        f"X-Theatre-Project: {_clean_id(outcome['project_id'])}\n"
        f"X-Theatre-Source: explorateur theatre phase1 usine wave merge")
    _git(["-c", f"user.name={config.identity[0]}",
          "-c", f"user.email={config.identity[1]}",
          "commit", "-m", subject, "-m", body], cwd=usine_dir)
    return _git(["rev-parse", "HEAD"], cwd=usine_dir) \
        .stdout.decode("utf-8", "replace").strip()


def _ensure_wave_tag(config: UsineMergeConfig, usine_dir, wave_index: int,
                     commits: list) -> dict:
    tag = f"{config.tag_prefix}-{wave_index}"
    probe = _git(["rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                 cwd=usine_dir, check=False)
    if probe.returncode == 0:
        return {"tag": tag, "tag_created": False}
    _git(["-c", f"user.name={config.identity[0]}",
          "-c", f"user.email={config.identity[1]}",
          "tag", "-a", tag, "-m",
          f"{config.commit_scope} wave {wave_index}: "
          f"{len(commits)} candidate(s) merged"], cwd=usine_dir)
    return {"tag": tag, "tag_created": True}


# --------------------------------------------------------------------- waves

def _read_outcomes(lineage: pathlib.Path) -> list[dict]:
    episodes = lineage / "episodes"
    if not episodes.is_dir():
        return []
    records = []
    for directory in sorted(episodes.iterdir()):
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


def _render_md(report: dict) -> str:
    lines = [f"# usine wave {report['wave_index']} merge report", "",
             f"- repository: `{report['repo_toplevel']}` "
             f"(prefix `{report['repo_prefix'] or '.'}`)",
             f"- base commit: `{report['base_commit']}`",
             f"- commits: {len(report['commits'])}"
             + (f", tag: `{report['tag']}`"
                f"{' (created)' if report['tag_created'] else ' (pre-existing)'}"
                if report["tag"] else ", tag: none"),
             f"- gate argv: `{' '.join(report['gate_argv'])}`"
             f" ({report['gate_seconds_total']}s total)", ""]
    if report.get("skipped"):
        lines.append(f"> skipped: {report['skipped']}")
        lines.append("")
    lines += ["| ep | project | outcome | decision | commit |",
              "|---|---|---|---|---|"]
    for entry in report["candidates"]:
        commit = entry.get("commit") or ""
        lines.append(
            f"| {entry['project_index']:03d} | {entry['project_id'][:24]} "
            f"| {entry['terminal_outcome']} | {entry['decision']} "
            f"| `{commit[:12]}` |")
    for entry in report["candidates"]:
        if entry.get("reason"):
            lines += ["", f"**ep{entry['project_index']:03d}** "
                          f"({entry['decision']}): {entry['reason']}"]
    return "\n".join(lines) + "\n"


def merge_wave(lineage_root, wave_index: int,
               config: UsineMergeConfig) -> dict:
    """Merge one fully closed wave; idempotent (a reported wave is a no-op)."""
    lineage = pathlib.Path(lineage_root)
    wave_dir = lineage / "waves" / f"wave_{wave_index:03d}"
    report_path = wave_dir / "merge_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["skipped"] = "report_exists"
        log.info("wave %s already carries a merge report", wave_index)
        return report
    outcomes = _wave_outcomes(lineage, wave_index)
    if not outcomes:
        raise UsineMergeError(
            f"wave {wave_index} has no closed episodes under {lineage}")
    usine = pathlib.Path(config.usine_dir)
    ctx = _repo_context(usine)
    base_commit = _assert_preconditions(ctx, usine)

    commits: list[str] = []
    gate_seconds = 0.0
    candidates: list[dict] = []
    log.info("wave %s merge start: %d episode(s), base %s",
             wave_index, len(outcomes), base_commit[:10])
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
        verdict, details = classify_delta(
            delta, fixture["files"], candidate["files"], usine)
        entry["pre_applied"] = details.get("pre_applied", 0)
        if verdict == "already_merged":
            entry["decision"] = "already_merged"
            entry["reason"] = "every delta path already carries the candidate bytes"
            continue
        if verdict == "drift":
            entry["decision"] = "drift_skipped"
            entry["reason"] = details["reason"]
            continue
        wanted = _extract_members(
            candidate_dir, [*delta["modified"], *delta["added"]],
            candidate["files"])
        executable = (_archive_exec_bits(
            candidate_dir, [*delta["modified"], *delta["added"]])
            | _tracked_exec_bits(
                ctx, [rel for rel in delta["modified"]
                      if rel not in delta["added"]]))
        snapshot = _snapshot_tree(usine, delta)
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
    tag_info = ({"tag": None, "tag_created": False} if not commits
                else _ensure_wave_tag(config, usine, wave_index, commits))
    report = {"schema_version": 1, "wave_index": wave_index,
              "usine_dir": str(usine), "repo_toplevel": ctx["toplevel"],
              "repo_prefix": ctx["prefix"], "base_commit": base_commit,
              "gate_argv": [str(a) for a in config.gate_argv],
              "commits": commits, "gate_seconds_total": round(gate_seconds, 1),
              "candidates": candidates,
              "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **tag_info}
    _atomic_json(report_path, report)
    _atomic_text(wave_dir / "merge_report.md", _render_md(report))
    log.info("wave %s merge done: %d commit(s), tag=%s",
             wave_index, len(commits), report["tag"])
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
