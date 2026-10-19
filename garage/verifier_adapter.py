"""Worktree Verifier executor for the usine RSI adaptation.

Replaces the stock QEMU rollback-mirror boundary with a host-side file-level
transaction on the worktree substrate (garage/guest_env.py), keeping
every stock role contract:

* ``AgenticVerifierExecutor`` construction, the ``verifier-report`` channel,
  report validation, and the ready-token Program contract
  (``__RSIAGENT_VERIFIER_MIRROR_READY_<token>__`` must appear before model
  output; its absence is infra 125) are inherited unchanged.
* The stock constructor builds a ``QemuRollbackTransaction`` without touching
  the VM; this subclass swaps it for :class:`FileLevelRollbackTransaction`:
  ``begin()`` snapshots the whole guest disk host-side, ``rollback()`` wipes
  and restores it.  ``begin()`` only reads the guest and writes the snapshot,
  so a failed begin leaves the guest untouched and ``rollback()`` is a safe
  no-op when nothing began (model code never ran).
* The stock private mount namespace, sudo/nsenter/setpriv wrapper, and keeper
  process do not exist on this substrate.  ``_ensure_workspace`` therefore
  checkpoints, quarantines Actor-private paths HOST-SIDE (moved out of the
  guest disk entirely - stronger than the stock root-only quarantine, which
  stays inside the VM), and creates the workspace directory directly on the
  host mapping of the guest drive.
* Programs run through the inherited ``_run_harness_script`` -> stock
  ``VM.run_script`` transport (b64 inline or streamed, GNU timeout tree kill,
  lossless cap=0) with ``USER``/``LOGNAME``/``VERIFIER_SCRATCH`` exported.
  ``VERIFIER_SCRATCH`` and the staged program file use the substrate
  spelling that bash and the guest python resolve identically: the
  drive-qualified forward-slash form (``Z:/home/user/...``) on the Windows
  wave host, the scratch-absolute host form on POSIX
  (``_substrate_path``).  Guest
  output is restored to the canonical ``/home/user/...`` spelling by the
  execute server, so the substrate form never reaches agent-visible text.
  On Windows the canonical spelling still works in Python programs
  (drive-relative resolution, probe-validated) and in Look paths; on POSIX
  it works in Look paths only - inside program text it resolves against
  the real host root, so the substrate note steers programs there to
  ``$VERIFIER_SCRATCH`` / ``$HOME`` / ``~``.
* ``export_scratch``/scratch restore are host-side tars of the workspace;
  member safety mirrors the stock restore (reject absolute/traversal/non
  regular members before extracting anything).
* ``close()`` rolls back and, on success, drops the quarantine copies; a
  rollback failure raises ``AgenticVerifierInfrastructureError`` so grading
  stays blocked exactly as stock.  Before restoring, a best-effort sweep
  kills guest processes whose command line references this guest's drive or
  scratch path (Windows file locks would otherwise doom the restore); the
  sweep never touches this interpreter or the sweep itself, and anything it
  misses surfaces as a rollback failure, never as silent state mixture.

Prompt honesty: ``install_verifier_adapter()`` replaces the Ubuntu/QEMU/tmpfs
claims in the verifier system text with substrate-true ones and appends a
short substrate-facts note; it also accepts the drive-qualified spelling in
``validate_verifier_look_path`` (canonicalized first, then the stock checks
run unchanged).  Every production construction site resolves
``AgenticVerifierExecutor``, ``agentic_verifier_system_for``, and
``validate_verifier_look_path`` from ``core.verifier_runtime`` at call time
(core/verifier.py imports them lazily inside the calling functions), so
replacing the module attributes is complete.

This module imports ``core.verifier_runtime`` and ``guest_env``; the importing
process must put the théâtre root on ``sys.path`` first (run_usine.py and the
smoke tests do).
"""

from __future__ import annotations

import base64
import io
import logging
import os
import pathlib
import posixpath
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import guest_env  # noqa: E402  (the théâtre root must be importable first)
from guest_env import copytree_force, rmtree_force  # noqa: E402

from core.verifier_runtime import (  # noqa: E402
    AgenticVerifierExecutor,
    AgenticVerifierInfrastructureError,
    VerifierTrace,
    _is_private_path,
    _trace,
)

log = logging.getLogger("rsiagent.usine.verifier_adapter")

WORKTREE_WORKSPACE_PARENT = "/home/user/.verifier"
_CANONICAL_ROOTS = ("/home/user", "/tmp", "/dev/shm")


# --------------------------------------------------------------------- paths


def _drive_form(drive_letter: str, canonical: str) -> str:
    """Drive-qualified forward-slash spelling (``Z:/home/user/...``).

    The only path form bash (MSYS) and the guest's Windows Python both
    resolve identically; used for ``$VERIFIER_SCRATCH`` and staged program
    files.  The execute server restores this form to canonical spelling in
    all guest output.
    """
    text = posixpath.normpath(str(canonical))
    for prefix in _CANONICAL_ROOTS:
        if text == prefix or text.startswith(prefix + "/"):
            return drive_letter + ":" + text
    raise ValueError(
        f"canonical path is outside the worktree roots: {canonical!r}")


def _substrate_path(env, canonical: str) -> str:
    """The one path form bash and the guest python resolve identically.

    Windows wave host: the drive-qualified form (``Z:/home/user/...``).
    POSIX hosts: the scratch-absolute host form (the rewritten drive form,
    ``<scratch>/guest/home/user/...``) - both bash and the guest python
    resolve it against the real root, and the execute server restores it
    to canonical spelling in all guest output.
    """
    if guest_env.IS_WINDOWS:
        return _drive_form(env.drive_letter, canonical)
    text = posixpath.normpath(str(canonical))
    for prefix in _CANONICAL_ROOTS:
        if text == prefix or text.startswith(prefix + "/"):
            return env.p + text
    raise ValueError(
        f"canonical path is outside the worktree roots: {canonical!r}")


def _canonicalize_look_path(path):
    """Map a substrate-form guest spelling onto its canonical form.

    ``$VERIFIER_SCRATCH`` and ``$HOME`` carry substrate-form values inside
    the guest, so Look paths copied from them must validate like the
    canonical spelling.  Anything that is not a recognized substrate form
    is returned unchanged, so the stock validator still rejects host paths
    such as ``C:/Windows/...`` (Windows) or ``/etc/...`` (POSIX).
    """
    if not isinstance(path, str):
        return path
    if guest_env.IS_WINDOWS:
        match = re.fullmatch(r"([A-Za-z]):[/\\]+(.*)", path)
        if match is None:
            return path
        rest = match.group(2).replace("\\", "/")
        if rest == "home/user" or rest.startswith("home/user/"):
            return "/" + rest
        if rest == "tmp" or rest.startswith("tmp/"):
            return "/" + rest
        if rest == "dev/shm" or rest.startswith("dev/shm/"):
            return "/" + rest
        return path
    # POSIX: scratch-absolute spellings copied out of $VERIFIER_SCRATCH or
    # $HOME re-root from the LAST canonical-root marker; the stock
    # validator then re-checks roots and traversal on the canonical form.
    # URL schemes are left untouched (they never start with "/" at the
    # marker, and "file:///home/user/..." must stay rejected by stock).
    if "://" in path:
        return path
    for marker in ("/home/user/", "/dev/shm/", "/tmp/"):
        index = path.rfind(marker)
        if index >= 0:
            return path[index:]
    return path


# ------------------------------------------------------------- host file ops


def _remove_entry(target: pathlib.Path) -> None:
    """Remove one filesystem entry, tolerating read-only files."""
    if target.is_dir() and not target.is_symlink():
        rmtree_force(target)
        return
    try:
        target.unlink()
    except OSError:
        os.chmod(target, stat.S_IWRITE)
        target.unlink()


def _copy_entry(source: pathlib.Path, destination: pathlib.Path) -> None:
    if source.is_dir() and not source.is_symlink():
        copytree_force(source, destination)
    else:
        shutil.copy2(source, destination)


def _stop_guest_processes(env) -> None:
    """Best-effort sweep of guest processes before the file-level restore.

    The stock QEMU rollback discards the whole VM; here a leftover guest
    process holding a file open would fail the restore, and one still running
    could keep writing into the restored tree.  Kill every process whose
    command line references this guest's drive or scratch path.  The sweep
    excludes itself and this interpreter.  Anything the sweep misses (for
    example a process whose command line carries no guest path but whose
    working directory is the guest drive) surfaces as a rollback failure -
    grading stays blocked - never as silent state mixture; that residual is
    recorded in ADAPTATION.md.
    """
    drive = env.drive_letter
    if not guest_env.IS_WINDOWS:
        # POSIX twin: match this guest's scratch path in process command
        # lines.  Windows file locks are not a POSIX concern, but a running
        # guest process could keep writing into the restored tree, so the
        # same best-effort sweep applies (its residuals are recorded in
        # ADAPTATION.md identically).
        needle = str(env.scratch)
        try:
            result = subprocess.run(
                ["ps", "-axo", "pid=,command="],
                capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.SubprocessError):
            return
        if result.returncode != 0:
            return
        mine = os.getpid()
        for line in (result.stdout or "").splitlines():
            stripped = line.strip()
            if not stripped or needle not in stripped:
                continue
            pid_text = stripped.split(None, 1)[0]
            if not pid_text.isdigit() or int(pid_text) == mine:
                continue
            try:
                os.kill(int(pid_text), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                continue
            log.info("rollback sweep killed pid %s", pid_text)
        return
    lower = drive.lower()
    needles = (
        str(env.scratch),
        drive + ":/",
        drive + ":\\",
        "/" + lower + "/home",
        "/" + lower + "/tmp",
        "/" + lower + "/dev",
    )
    needle = "(?i)(" + "|".join(re.escape(n) for n in needles) + ")"
    if "'" in needle:  # PowerShell single-quote safety; paths never contain '
        log.warning("rollback sweep skipped: unsafe needle %r", needle)
        return
    query = (
        "Get-CimInstance Win32_Process | "
        "Where-Object {"
        " $_.ProcessId -ne $PID"
        f" -and $_.ProcessId -ne {os.getpid()}"
        f" -and $_.CommandLine -match '{needle}'"
        " } | ForEach-Object { $_.ProcessId }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             query],
            capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError):
        return
    if result.returncode != 0:
        return
    for chunk in (result.stdout or "").split():
        if not chunk.isdigit():
            continue
        killed = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", chunk], capture_output=True)
        log.info("rollback sweep killed pid %s (rc=%s)",
                 chunk, killed.returncode)


# ------------------------------------------------------------- transaction


class FileLevelRollbackTransaction:
    """Host-side file-level stand-in for the stock QEMU disk checkpoint.

    ``begin()`` copies the whole guest disk (``disk_root``: home + tmp +
    dev/shm) into the environment's scratch area; ``rollback()`` stops guest
    processes, wipes the disk contents (never the root directory itself, so
    the subst mapping stays valid), and restores the copy byte-for-byte.
    """

    def __init__(self, env):
        self._env = env
        self._snapshot = None
        self._begun = False
        self._finished = False

    @property
    def begun(self) -> bool:
        return self._begun

    def begin(self):
        if self._finished:
            raise RuntimeError("rollback transaction is already finished")
        if self._begun:
            return
        snapshot = self._env.scratch / (
            "verifier-checkpoint-" + secrets.token_hex(8))
        try:
            copytree_force(self._env.disk_root, snapshot)
        except Exception:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        self._snapshot = snapshot
        self._begun = True
        log.info("file-level checkpoint saved: %s", snapshot)

    def rollback(self):
        if self._finished:
            return
        self._finished = True
        if not self._begun:
            # Nothing was checkpointed, so no model-authored code ran and the
            # guest was never mutated: restoring nothing is exact.
            return
        _stop_guest_processes(self._env)
        root = self._env.disk_root
        try:
            for entry in list(root.iterdir()):
                _remove_entry(entry)
            for entry in list(self._snapshot.iterdir()):
                _copy_entry(entry, root / entry.name)
        except Exception:
            # Keep the checkpoint (and any quarantine copies) for manual
            # recovery; the caller blocks grading on this failure.
            log.exception("file-level rollback failed; checkpoint kept: %s",
                          self._snapshot)
            raise
        log.info("file-level checkpoint restored: %s -> %s",
                 self._snapshot, root)
        shutil.rmtree(self._snapshot, ignore_errors=True)
        if self._snapshot.exists():
            log.warning("checkpoint partially retained: %s", self._snapshot)
        self._snapshot = None


# ---------------------------------------------------------------- executor


class WorktreeVerifierExecutor(AgenticVerifierExecutor):
    """Rollback-mirror executor over one worktree guest drive.

    Constructed with ``execution_mode="rollback_mirror"`` only; every other
    mode has no substrate equivalent and fails closed.
    """

    def __init__(self, vm, **kwargs):
        super().__init__(vm, **kwargs)
        if self._execution_mode != "rollback_mirror":
            raise AgenticVerifierInfrastructureError(
                "the worktree substrate requires the rollback_mirror "
                f"boundary (got {self._execution_mode!r})")
        env = getattr(vm, "env", None)
        if not isinstance(env, guest_env.WorktreeEnv):
            raise AgenticVerifierInfrastructureError(
                "WorktreeVerifierExecutor needs a WorktreeEnv-backed VM "
                f"(got {type(env).__name__})")
        self._env = env
        # The stock constructor built a QemuRollbackTransaction without
        # touching the VM; replace it with the file-level transaction.
        self._rollback_transaction = FileLevelRollbackTransaction(env)
        self._workspace = (WORKTREE_WORKSPACE_PARENT
                           + "/rsiagent-verifier-" + secrets.token_hex(16))
        self._quarantine_dir = None

    # -- workspace lifecycle --------------------------------------------

    def _workspace_host(self) -> pathlib.Path:
        return self._env.guest_to_host(self._workspace)

    def _ensure_workspace(self, timeout):
        if self._closed:
            return _trace(
                "Verifier isolation workspace is already closed.", 125,
                infra_fail=True)
        if getattr(self._env, "_closed", False):
            return _trace(
                "Verifier workspace is on a released guest drive.", 125,
                infra_fail=True)
        if self._initialized:
            # A plain directory replaces the stock mount-namespace keeper:
            # revalidation is one host-side existence check.  Recreate the
            # directory if a Program removed its own scratch root; the stock
            # tmpfs mountpoint cannot be removed, a directory can.
            try:
                self._workspace_host().mkdir(parents=True, exist_ok=True)
                self._last_namespace_check = time.monotonic()
                return None
            except OSError as exc:
                return _trace(
                    "Verifier workspace became unavailable on the guest "
                    "drive; model-authored code was not executed. "
                    f"{type(exc).__name__}: {exc}", 125, infra_fail=True)
        if self._init_reason:
            return _trace(self._init_reason, 125, infra_fail=True)
        try:
            self._rollback_transaction.begin()
            self._quarantine_private_paths_host_side()
            self._workspace_host().mkdir(parents=True, exist_ok=True)
            self._workspace_attempted = True
            if self._scratch_archive is not None:
                self._restore_scratch_archive()
                self._scratch_archive = None
            self._initialized = True
            self._rollback_private_paths_hidden = True
            self._last_namespace_check = time.monotonic()
            return None
        except Exception as exc:  # noqa: BLE001 - trusted boundary failure
            self._initialized = False
            self._init_reason = (
                "Verifier rollback-mirror preflight failed; model-authored "
                f"code was not executed. {type(exc).__name__}: {exc}")
            return _trace(self._init_reason, 125, infra_fail=True)

    def _quarantine_private_paths_host_side(self):
        """Move Actor-private paths out of the guest disk entirely.

        The stock mirror moves them into a root-only directory inside the VM
        and relies on the checkpoint to restore them; here the host-side move
        is strictly stronger (no guest process can reach the bytes at all)
        and the same checkpoint restores them on rollback.
        """
        if self._rollback_private_paths_hidden or not self._private_paths:
            self._rollback_private_paths_hidden = True
            return
        quarantine = self._env.scratch / (
            "verifier-hidden-" + secrets.token_hex(8))
        quarantine.mkdir(parents=True)
        for index, guest_path in enumerate(self._private_paths):
            host = self._env.guest_to_host(guest_path)
            if host.exists() or host.is_symlink():
                shutil.move(str(host),
                            str(quarantine / f"hidden-{index:03d}"))
        self._quarantine_dir = quarantine
        self._rollback_private_paths_hidden = True
        log.info("quarantined %d Actor-private path(s) host-side",
                 len(self._private_paths))

    def _restore_scratch_archive(self):
        """Extract the preserved scratch archive into the new workspace.

        Member safety mirrors the stock restore: only ordinary relative
        files/directories below the workspace root, no links, devices,
        absolute names, or traversal, checked before anything is written.
        """
        import tempfile

        local = tempfile.NamedTemporaryFile(
            prefix="rsiagent-verifier-scratch-", suffix=".tar", delete=False)
        try:
            local.write(self._scratch_archive)
            local.flush()
            os.fsync(local.fileno())
            local.close()
            root = self._workspace_host().resolve()
            with tarfile.open(local.name, "r:") as archive:
                members = archive.getmembers()
                for member in members:
                    name = member.name
                    target = (root / name).resolve()
                    if (name.startswith(("/", "\\"))
                            or ".." in pathlib.PurePosixPath(name).parts
                            or not (member.isdir() or member.isfile())
                            or root not in target.parents):
                        raise RuntimeError(
                            "unsafe Verifier scratch archive member: "
                            + name)
                archive.extractall(root, members=members, filter="data")
        finally:
            try:
                os.unlink(local.name)
            except OSError:
                pass

    # -- program execution ----------------------------------------------

    def _run_isolated(self, interpreter, extension, code, timeout):
        action_token = secrets.token_hex(12)
        ready_token = "__RSIAGENT_VERIFIER_MIRROR_READY_" + action_token + "__"
        program_path = (
            self._workspace + f"/program_{action_token}.{extension}")
        scratch_drive = _substrate_path(self._env, self._workspace)
        program_drive = _substrate_path(self._env, program_path)
        encoded = base64.b64encode(
            (code or "").encode("utf-8")).decode("ascii")
        # All interpolated values are harness tokens or base64 data; the
        # model program is decoded to a file and never parsed as wrapper
        # source.  The substrate spelling works from bash and from the
        # guest python identically (drive-qualified on the Windows wave
        # host, scratch-absolute on POSIX); the server restores the
        # canonical spelling in all output.
        wrapper = f"""\
set -eu
scratch_path={scratch_drive!r}
program_path={program_drive!r}
payload={encoded!r}
export USER=user LOGNAME=user
export VERIFIER_SCRATCH="$scratch_path"
mkdir -p -- "$scratch_path"
printf '%s\n' {ready_token!r}
printf %s "$payload" | base64 -d > "$program_path"
chmod 0600 "$program_path"
set +e
{shlex.quote(interpreter)} "$program_path"
program_rc=$?
set -e
rm -f -- "$program_path"
exit "$program_rc"
"""
        result = self._run_harness_script(
            "bash", wrapper, timeout=timeout, cap=0)
        visible_output = (getattr(result, "context_stdout", None)
                          or result.stdout or "")
        if ready_token not in visible_output:
            return VerifierTrace(
                stdout=(
                    "[verifier rollback-mirror readiness was not confirmed; "
                    "program execution is unknown; output may be "
                    "incomplete]\n"
                    + (result.stdout or "(no diagnostic output)")),
                exit_code=125,
                secs=result.secs,
                timed_out=result.timed_out,
                infra_fail=True,
            )
        self._last_namespace_check = time.monotonic()
        for channel_name in ("stdout", "context_stdout"):
            channel = getattr(result, channel_name, None)
            if isinstance(channel, str):
                setattr(result, channel_name, channel
                        .replace(ready_token + "\n", "", 1)
                        .replace(ready_token, "", 1))
        return result

    # -- scratch persistence --------------------------------------------

    def export_scratch(self):
        """Return a lossless host-side tar of the private workspace.

        No candidate path is included, no semantic selection is performed,
        and no size ceiling is imposed.  Symlinks and special files are
        intentionally omitted (matching the stock export) so a
        model-influenced archive cannot escape the next private root.
        """
        if not self._initialized or self._closed:
            return self._scratch_archive
        root = self._workspace_host()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for current, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = sorted(
                    d for d in dirs
                    if not (pathlib.Path(current) / d).is_symlink())
                for name in dirs + sorted(files):
                    item = pathlib.Path(current) / name
                    if (item.is_symlink()
                            or not (item.is_file() or item.is_dir())):
                        continue
                    archive.add(
                        item,
                        arcname=item.relative_to(root).as_posix(),
                        recursive=False)
        return buffer.getvalue()

    def _fetch_private_file(self, path, max_bytes=None):
        """Bridge one regular scratch file to the host, host-side.

        The stock implementation stages through the private mount namespace;
        on this substrate the workspace is a plain directory on the host
        mapping, so the bridge is a direct read with the same safety checks:
        resolved, below the private root, not a symlink, regular file.
        """
        requested = posixpath.normpath(_canonicalize_look_path(str(path)))
        root = posixpath.normpath(self._workspace)
        if not (requested == root or requested.startswith(root + "/")):
            return None, "private Verifier fetch path escaped its workspace"
        try:
            host = self._env.guest_to_host(requested)
        except ValueError:
            return None, "private Verifier fetch path escaped its workspace"
        if host.is_symlink():
            return None, "Verifier Look source may not be a symbolic link"
        resolved = host.resolve()
        root_host = self._workspace_host().resolve()
        try:
            resolved.relative_to(root_host)
        except ValueError:
            return None, "Verifier Look source escaped private scratch"
        if not resolved.is_file():
            return None, "Verifier Look source is not a regular file"
        try:
            data = resolved.read_bytes()
        except OSError as exc:
            return None, ("could not read the private Verifier pixels: "
                          f"{type(exc).__name__}")
        if max_bytes is not None and len(data) > int(max_bytes):
            return None, (f"file is {len(data)} bytes (limit {int(max_bytes)}); "
                          "downscale or crop it with a program first")
        return data, None

    # -- looks -----------------------------------------------------------

    def fetch_look_image(self, path):
        ready = self._ensure_workspace(timeout=180)
        if ready is not None:
            raise AgenticVerifierInfrastructureError(ready.stdout)
        text = path if isinstance(path, str) else str(path)
        if any(c in text for c in ("\x00", "\n", "\r")):
            return None, "Malformed Look path"
        if text.lower().startswith("screen:"):
            return None, (
                "Screen Looks are unavailable in this headless worktree "
                "guest; inspect evidence with program output or file Looks.")
        normalized = posixpath.normpath(_canonicalize_look_path(text))
        root = posixpath.normpath(self._workspace)
        look_is_private_scratch = (
            normalized == root or normalized.startswith(root + "/"))
        if self._private_paths and not look_is_private_scratch:
            try:
                resolved_host = self._env.guest_to_host(normalized).resolve()
                resolved_guest = self._env.host_to_guest(resolved_host)
            except (ValueError, OSError):
                return None, "Verifier Look path could not be resolved safely."
            if _is_private_path(resolved_guest, self._private_paths):
                return None, "That path is private to the Actor Agent."
        executor = self
        render_dir = _substrate_path(
            self._env, self._workspace + "/look_render")

        class _VerifierLookVM:
            # Document rendering on this substrate has no soffice/pdftoppm,
            # so renderer commands fail honestly through the isolated
            # channel; direct image reads and scratch reads work host-side.
            def run_command(self, command, timeout=30, cap=4000):
                isolated = command.replace("/tmp/rsiagent_render", render_dir)
                trace = executor("bash", isolated, timeout=timeout, cap=0)
                return trace.stdout

            def fetch_file(self, target, max_bytes=None):
                target_norm = posixpath.normpath(
                    _canonicalize_look_path(str(target)))
                if (target_norm == root
                        or target_norm.startswith(root + "/")):
                    return executor._fetch_private_file(
                        target_norm, max_bytes=max_bytes)
                return executor._vm.fetch_file(
                    str(target), max_bytes=max_bytes)

        from core import imagery
        return imagery.fetch_look_image(_VerifierLookVM(), text)

    # -- teardown ---------------------------------------------------------

    def close(self):
        """Roll back the checkpoint; a failure blocks grading as in stock."""
        if self._closed:
            return
        self._closed = True
        rollback_ok = False
        try:
            if self._rollback_transaction is not None:
                self._rollback_transaction.rollback()
            rollback_ok = True
        except Exception as exc:  # noqa: BLE001 - trusted boundary failure
            raise AgenticVerifierInfrastructureError(
                "Verifier rollback failed; the candidate is not safe to "
                f"grade. {type(exc).__name__}: {exc}") from exc
        finally:
            quarantine = self._quarantine_dir
            if rollback_ok and quarantine is not None:
                # The restored checkpoint already contains these bytes.
                try:
                    rmtree_force(quarantine)
                except OSError:
                    log.warning("quarantine partially retained: %s", quarantine)
                self._quarantine_dir = None


# ------------------------------------------------------------------ install

_INSTALLED = False

# Exact stock substrings -> substrate-true replacements.  Applied to whatever
# agentic_verifier_system_for returns; strings that are absent (for example
# the effect-isolation text in mirror mode) are harmless no-ops.
_SUBSTRATE_REPLACEMENTS = (
    ("on a real\nUbuntu machine.", "in a real POSIX\nworktree guest."),
    ("saved a complete QEMU\ncheckpoint.",
     "saved a complete file-level\ncheckpoint."),
    ("network, GUI,\nand IPC and may run arbitrary tests.",
     "network, and may run arbitrary tests."),
    ("VERIFIER_SCRATCH is a private writable tmpfs that persists",
     "VERIFIER_SCRATCH is a private writable directory that persists"),
    ("State in an external service outside this QEMU guest cannot be\n"
     "rolled back",
     "State in an external service outside this guest cannot be\n"
     "rolled back"),
    ("names your private writable tmpfs",
     "names your private writable directory"),
)

_CANDIDATE_TREE_FACTS = (
    "Candidate-tree facts: the candidate is a TypeScript pnpm monorepo. "
    "node_modules and dist are PRUNED from every capture by design (they "
    "are regenerable install/build output, symmetric on both the capture "
    "and the merge side) - their absence in the candidate tree is expected "
    "substrate behavior, not tampering or lost work. To run the project's "
    "tests yourself, install first and keep install and test in separate "
    "programs (each program gets 600 seconds): `pnpm install "
    "--frozen-lockfile` (needs network once, fills the shared pnpm store), "
    "then `pnpm verify` (typecheck plus every vitest suite) or `pnpm vitest "
    "run packages/<pkg>` for one package. Node 24+ and pnpm 11 are on PATH."
)

if guest_env.IS_WINDOWS:
    _SUBSTRATE_NOTE = (
        "\n\nSubstrate facts: this is a POSIX worktree guest on a Windows "
        "host. Use $VERIFIER_SCRATCH directly from both Bash and Python. "
        "Python programs may also use canonical /home/user/... and /tmp/... "
        "paths (including in Looks); in Bash programs prefer $VERIFIER_SCRATCH "
        "and $HOME over literal /home/user and /tmp paths - a literal /tmp "
        "in Bash resolves through a mount shared by other processes and is "
        "not reliable in this guest. There is no apt-get, no systemd, and "
        "no GUI; screen Looks are unavailable - inspect evidence with "
        "program output and file Looks.\n"
        + _CANDIDATE_TREE_FACTS)
else:
    # POSIX twin: the Windows note's Python guidance is FALSE here - a
    # literal canonical path inside program text resolves against the real
    # host root, not the guest tree (there is no per-drive resolution).
    _SUBSTRATE_NOTE = (
        "\n\nSubstrate facts: this is a POSIX worktree guest on a macOS "
        "host. Use $VERIFIER_SCRATCH directly from both Bash and Python "
        "programs. LITERAL /home/user/... and /tmp/... paths in your program "
        "text resolve against the REAL host root, not your guest tree - "
        "reach your files through $VERIFIER_SCRATCH, $HOME, or ~ in both "
        "Bash and Python (os.path.expanduser). Canonical /home/user/... and "
        "/tmp/... spellings still work in Look paths (the host maps them "
        "for you). There is no apt-get, no systemd, and no GUI; screen "
        "Looks are unavailable - inspect evidence with program output and "
        "file Looks.\n"
        + _CANDIDATE_TREE_FACTS)


def _substrate_system_prompt(base: str) -> str:
    for old, new in _SUBSTRATE_REPLACEMENTS:
        base = base.replace(old, new)
    return base + _SUBSTRATE_NOTE


def install_verifier_adapter() -> dict:
    """Wire the worktree substrate into the lazily-imported verifier runtime.

    Run this before ``core.verifier`` / ``core.loop`` / ``explore.*`` are
    imported or used: every production construction and lookup site resolves
    ``AgenticVerifierExecutor``, ``agentic_verifier_system_for``, and
    ``validate_verifier_look_path`` from ``core.verifier_runtime`` at call
    time, so replacing the module attributes is complete.  Idempotent.
    """
    global _INSTALLED
    if _INSTALLED:
        return {"already_installed": True}
    import core.verifier_runtime as verifier_runtime

    verifier_runtime.AgenticVerifierExecutor = WorktreeVerifierExecutor

    original_validate = verifier_runtime.validate_verifier_look_path

    def validate_look(path, hide_actor_memory=False, private_paths=()):
        return original_validate(
            _canonicalize_look_path(path),
            hide_actor_memory=hide_actor_memory,
            private_paths=private_paths)

    verifier_runtime.validate_verifier_look_path = validate_look

    original_system = verifier_runtime.agentic_verifier_system_for

    def verifier_system(*args, **kwargs):
        return _substrate_system_prompt(original_system(*args, **kwargs))

    verifier_runtime.agentic_verifier_system_for = verifier_system

    existing = sys.modules.get("core.verifier")
    if existing is not None:
        for name, value in (
                ("AgenticVerifierExecutor", WorktreeVerifierExecutor),
                ("validate_verifier_look_path", validate_look),
                ("agentic_verifier_system_for", verifier_system)):
            if hasattr(existing, name):
                setattr(existing, name, value)

    _INSTALLED = True
    log.info("verifier adapter installed: WorktreeVerifierExecutor + "
             "substrate-true verifier system prompt")
    return {
        "already_installed": False,
        "executor": "WorktreeVerifierExecutor",
        "system_wrapped": True,
        "look_validator_wrapped": True,
    }


__all__ = [
    "FileLevelRollbackTransaction",
    "WorktreeVerifierExecutor",
    "WORKTREE_WORKSPACE_PARENT",
    "install_verifier_adapter",
]
