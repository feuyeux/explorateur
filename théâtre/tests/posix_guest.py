"""Host-side stand-in for the POSIX guest shell that the VM contract assumes.

Guest commands are POSIX-shaped: single-quoted arguments, ``$?`` exit probes,
``test``/``find``/``rm``. POSIX hosts run them unchanged. On Windows the
first ``bash`` on PATH is the WSL launcher, which lives on a *different*
filesystem: it silently no-ops on Windows paths (``rm -rf`` on a path it
cannot see succeeds, ``test ! -e`` is vacuously true), so probes report
fiction. The POSIX-capable Git-for-Windows bash — which shares the Windows
filesystem — is discovered instead, and a ``python3`` shim forwards guest
``python3`` invocations to the active interpreter (Git for Windows ships
no python3).
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def posix_bash() -> str | None:
    """Locate a POSIX-capable bash; ``None`` on POSIX (native semantics)."""
    if os.name != "nt":
        return None
    found = shutil.which("bash")
    if found and "system32" not in \
            Path(found).resolve().parent.as_posix().lower():
        return found
    git = shutil.which("git")
    if git:
        for base in Path(git).resolve().parents:
            candidate = base / "usr" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    roots = (
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    )
    for root in roots:
        if root:
            candidate = Path(root) / "Git" / "usr" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError(
        "no POSIX-capable bash found on this Windows host; "
        "install Git for Windows")


def bash_argv() -> list[str]:
    """``["bash"]`` on POSIX; the discovered Git-for-Windows bash on Windows."""
    bash = posix_bash()
    return [bash] if bash else ["bash"]


def guest_environment() -> dict[str, str] | None:
    """Environment for running POSIX-guest commands on this host.

    ``None`` on POSIX: inherit unchanged, exactly as before. On Windows the
    inherited PATH keeps System32 ahead of the MSYS ``/usr/bin``, so guest
    utilities resolve to Windows lookalikes (``find`` becomes
    ``find.exe`` "Parameter format not correct"). Prepend the discovered
    bash's own tool directories so guest commands mean POSIX commands.
    """
    bash = posix_bash()
    if bash is None:
        return None
    exe = Path(bash).resolve()
    front: list[str] = []
    for base in exe.parents:
        if (base / "usr" / "bin").is_dir():
            front = [str(base / "usr" / "bin"),
                      str(base / "mingw64" / "bin")]
            break
    if not front:
        front = [str(exe.parent)]
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(front + [env.get("PATH", "")])
    return env


_shim_dir: str | None = None


def _python3_shim_dir() -> str:
    global _shim_dir
    if _shim_dir is None:
        _shim_dir = tempfile.mkdtemp(prefix="rsiagent-guest-py3-")
        shim = Path(_shim_dir) / "python3"
        shim.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "$@"\n',
            encoding="utf-8", newline="\n")
        atexit.register(shutil.rmtree, _shim_dir, ignore_errors=True)
    return _shim_dir


def run_guest_command(command: str, timeout=None) -> str:
    """Run one POSIX-guest-shaped command string; return combined output."""
    bash = posix_bash()
    if bash is None:
        result = subprocess.run(
            command, shell=True, text=True, capture_output=True,
            timeout=timeout)
    else:
        env = guest_environment()
        env["PATH"] = _python3_shim_dir() + os.pathsep + env.get("PATH", "")
        # Guest paths are POSIX by contract; MSYS argument rewrites would
        # turn them into host paths before native binaries ever see them.
        env["MSYS_NO_PATHCONV"] = "1"
        result = subprocess.run(
            [bash, "-c", command], env=env, text=True,
            capture_output=True, timeout=timeout)
    return result.stdout + result.stderr


def run_guest_stdout(command: str, timeout=None) -> str:
    """VM ``run_command`` contract for stdout-only probes.

    POSIX behaviour matches the historical LocalWaveVM exactly:
    ``["bash", "-c", command]`` with ``check=True``, returning stdout.
    """
    result = subprocess.run(
        bash_argv() + ["-c", command], env=guest_environment(),
        capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout
