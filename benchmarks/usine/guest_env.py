"""Windows git-bash guest substrate for the usine RSI adaptation.

Duck-types the OSWorld ``DesktopEnv`` surface ``env.vm.VM`` actually uses, on
top of a per-VM ``subst`` drive that hosts a POSIX-looking guest tree:

    <drive>:/home/user          guest home (~, $HOME)
    <drive>:/home/user/bin      python3 shim (PATH overlay beats WindowsApps)
    <drive>:/tmp                follows the MSYS usertemp mount (TEMP overlay)
    <drive>:/dev/shm            program staging + verifier scratch

Every building block here was validated by ``benchmarks/usine/probe_env.py``
(25 PASS / 0 FAIL against this host).  Key probe-validated facts the design
depends on:

* NON-login ``bash --noprofile --norc -c``: a login shell's
  /etc/bash.bash_logout injects clear-screen ANSI escapes into stdout and
  would pollute every /execute response.
* PATH overlay (Windows form, prepended): git ``usr\\bin`` + ``mingw64\\bin``
  put GNU coreutils ahead of the shadow binaries on this host's PATH (FPC
  rm/find/timeout/stat, System32 tar/find/timeout); the guest ``bin`` dir
  puts the python3 shim ahead of the WindowsApps alias.
* MSYS mounts ``/tmp`` at the Windows TEMP overlay, so ``/tmp`` needs no
  rewrite; ``/home/user`` and ``/dev/shm`` have no per-VM mount, so the
  execute server rewrites exactly those two tokens into the drive form
  ``/{d}/home/user`` / ``/{d}/dev/shm`` (boundary-sensitive), and restores
  the canonical guest spelling on all output, including inside the
  ``RSIAGENT_RUN_OUTPUT_BASE64:`` envelope (drive letters are per-VM and
  must never leak into agent-visible text or captured artifacts).
* Windows python resolves drive-relative embedded paths (``/home/user/x``)
  against the current drive, so python programs keep working unchanged.
  Literal ``/home/user`` inside *bash* programs still falls to the MSYS
  root; the charter steers bootstrap/agent programs to python3 or ``~``.
* GNU ``timeout --signal=TERM --kill-after`` kills whole child trees;
  ``rm -rf`` removes read-only git objects without a chmod pass.

Two Windows transport constraints that the Linux guest never sees, handled
here without changing stock behaviour:

* CreateProcess caps a command line at 32767 chars, below the stock 32 KiB
  inline base64 program envelope.  The server therefore runs every command
  from a temp script file sourced via a constant-size argv, keeping exit
  codes, stdin (DEVNULL), and ``$0`` identical to ``bash -c``.
* MAX_PATH: the guest disk lives under a short scratch root on the
  workspace drive (``<anchor>/.rsi-usine-vm``), never under a long %TEMP%
  prefix; guest-visible paths are drive-qualified and short.

This module imports ``env.vm`` from the théâtre checkout; the importing
process must put the théâtre root on ``sys.path`` first (run_usine.py does).
"""

from __future__ import annotations

import atexit
import base64
import json
import logging
import os
import re
import shutil
import stat
import string
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from env.vm import VM

try:  # keep the envelope marker in lockstep with the transport contract
    from env.vm import _RUN_OUTPUT_B64_PREFIX
except ImportError:  # pragma: no cover - defensive fallback
    _RUN_OUTPUT_B64_PREFIX = "RSIAGENT_RUN_OUTPUT_BASE64:"

log = logging.getLogger("rsiagent.usine.guest_env")

_EXPLORATEUR_ROOT = Path(__file__).resolve().parents[2]
_THEATRE_ROOT = _EXPLORATEUR_ROOT / "théâtre"
DEFAULT_SCRATCH_ROOT = Path(_EXPLORATEUR_ROOT.anchor) / ".rsi-usine-vm"

BASH_CANDIDATES = [
    r"d:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
]

_EXECUTE_HOST = "127.0.0.1"
_SKIP_DRIVE_LETTERS = {"A", "B"}          # historical floppy letters; never guest drives
_SERVER_KILL_GRACE_SECS = 30.0            # GNU timeout fires first; this is the backstop

_DRIVE_LOCK = threading.Lock()
_LIVE_LOCK = threading.Lock()
_LIVE: set = set()


# --------------------------------------------------------------------- host tools

def find_bash() -> str:
    """Locate git-bash. Known install dirs first; PATH is a last resort."""
    for candidate in BASH_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    which = shutil.which("bash.exe") or shutil.which("bash")
    if which and "git" in which.lower():
        return which
    raise RuntimeError(
        "git-bash bash.exe not found (looked in "
        + ", ".join(BASH_CANDIDATES)
        + " and on PATH)")


def _default_guest_python() -> Path:
    """Guest python3 target: the théâtre venv, else an explicit override,
    else the running interpreter (which under ``uv run --project théâtre``
    is the venv python anyway)."""
    venv = _THEATRE_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return venv
    override = os.environ.get("RSIAGENT_GUEST_PYTHON", "").strip()
    if override:
        return Path(override)
    import sys
    return Path(sys.executable)


def _claim_drive(target: Path) -> str:
    """subst-map a free drive letter (Z backwards) to the guest disk."""
    with _DRIVE_LOCK:
        for letter in reversed(string.ascii_uppercase):
            if letter in _SKIP_DRIVE_LETTERS:
                continue
            if Path(f"{letter}:/").exists():
                continue
            result = subprocess.run(
                ["subst", f"{letter}:", str(target)], capture_output=True)
            if result.returncode == 0 and Path(f"{letter}:/").exists():
                return letter
            log.warning(
                "subst %s: attempt failed (rc=%s out=%r err=%r)",
                letter, result.returncode,
                result.stdout[-120:], result.stderr[-120:])
        raise RuntimeError("no free drive letter available for the guest subst")


def _release_drive(letter: str) -> bool:
    for _ in range(3):
        result = subprocess.run(
            ["subst", f"{letter}:", "/D"], capture_output=True)
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False


def rmtree_force(path) -> None:
    """rmtree that also removes read-only files (git objects)."""
    target = Path(path)

    def _onerror(func, name, _exc):
        try:
            os.chmod(name, stat.S_IWRITE)
            func(name)
        except OSError:
            # Fall back to the GNU toolchain, which the probe showed removes
            # read-only git objects directly.
            bash = find_bash()
            posix = subprocess.run(
                [bash, "--noprofile", "--norc", "-c",
                 f"rm -rf -- {Path(name).as_posix()!r}"],
                capture_output=True)
            if posix.returncode != 0:
                raise

    shutil.rmtree(target, onerror=_onerror)


def copytree_force(src, dst) -> None:
    """copytree preserving attributes (incl. read-only git objects)."""
    shutil.copytree(Path(src), Path(dst), copy_function=shutil.copy2)


# --------------------------------------------------------------------- execute server

class _ExecuteHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        env = self.server.env
        try:
            if self.path.rstrip("/") != "/execute":
                self._send(404, {"status": "error",
                                 "message": "unknown endpoint"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._send(400, {"status": "error",
                                 "message": "malformed JSON body"})
                return
            command = payload.get("command")
            if not isinstance(command, str):
                self._send(200, {"status": "error",
                                 "message": "missing command"})
                return
            timeout = payload.get("timeout")
            timeout = int(timeout) if isinstance(timeout, (int, float)) \
                and timeout > 0 else 30
            output, error, returncode = env._execute(command, timeout)
            self._send(200, {
                "output": output, "error": error,
                "returncode": returncode, "status": "success"})
        except Exception as exc:  # noqa: BLE001 - transport-level failure
            try:
                self._send(200, {
                    "status": "error",
                    "message": f"{type(exc).__name__}: {exc}"[:240]})
            except Exception:  # noqa: BLE001 - client is gone
                pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=True).encode("ascii")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # silence per-request stderr noise
        pass


class _ExecuteServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, env):
        super().__init__((_EXECUTE_HOST, 0), _ExecuteHandler)
        self.env = env


# --------------------------------------------------------------------- guest environment

class WorktreeEnv:
    """The duck-typed 'desktop' for one isolated Windows git-bash guest.

    Surface actually used by the harness (verified by grep over théâtre):

    * ``env.controller.http_server``  - stock VM.run_command POSTs here
    * ``env.controller.get_file``     - stock VM.fetch_file fallback
    * ``env.reset(task_config=None)`` + ``env.is_environment_used``
      (explore/practice_loop._reset_null_vm) and the ten scrubbed task attrs
    * ``env.client_password``         - core/verifier_runtime (getattr, but
      env/verifier_control reads it without a default)
    * ``env.provider_name``           - must not be "docker"
    * ``close()``                     - phase1_wave lifecycle owner
    """

    def __init__(self, *, bash: str = None, python_path=None,
                 scratch_root=None, keep_scratch: bool = None):
        self._closed = False
        self._bash = bash or find_bash()
        python_value = python_path or _default_guest_python()
        self._python = Path(python_value).resolve()
        if not self._python.exists():
            raise RuntimeError(f"guest python not found: {self._python}")
        base = Path(scratch_root) if scratch_root else Path(
            os.environ.get("USINE_VM_SCRATCH_ROOT", "")
            or DEFAULT_SCRATCH_ROOT)
        base.mkdir(parents=True, exist_ok=True)
        self.scratch = base / f"guest-{uuid.uuid4().hex[:12]}"
        self.disk_root = self.scratch / "guest"
        self._script_dir = self.scratch / "exec_scripts"
        for sub in ("home/user/bin", "home/user/work", "tmp", "dev/shm"):
            (self.disk_root / sub).mkdir(parents=True, exist_ok=True)
        self._script_dir.mkdir(parents=True, exist_ok=True)
        self.drive_letter = _claim_drive(self.disk_root)
        self.p = "/" + self.drive_letter.lower()
        self.guest_root = Path(self.drive_letter + ":/")
        self.home_dir = self.guest_root / "home" / "user"
        self.tmp_dir = self.guest_root / "tmp"
        self.shm_dir = self.guest_root / "dev" / "shm"
        self.bin_dir = self.home_dir / "bin"
        self.work_dir = self.home_dir / "work"
        self._write_python3_shim()
        self._bash_env = self._build_bash_env()
        self._build_rewrite_rules()
        try:
            self._server = _ExecuteServer(self)
        except Exception:
            # Never leak a subst mapping if the execute server cannot bind.
            _release_drive(self.drive_letter)
            raise
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"worktree-exec-{self.drive_letter}", daemon=True)
        self._server_thread.start()
        self.controller = SimpleNamespace(
            http_server=f"http://{_EXECUTE_HOST}:"
                        f"{self._server.server_address[1]}",
            get_file=self._controller_get_file)
        self.provider_name = "worktree"
        self.client_password = "worktree-loopback-noauth"
        self.is_environment_used = False
        if keep_scratch is None:
            keep_scratch = os.environ.get("USINE_VM_KEEP_SCRATCH") == "1"
        self._keep_scratch = bool(keep_scratch)
        with _LIVE_LOCK:
            _LIVE.add(self)
        log.info("worktree guest up: %s: -> %s (python=%s)",
                 self.drive_letter, self.scratch, self._python)

    def __repr__(self):
        return (f"<WorktreeEnv {self.drive_letter}: scratch={self.scratch} "
                f"closed={self._closed}>")

    # -- layout ----------------------------------------------------------

    def _write_python3_shim(self) -> None:
        shim = self.bin_dir / "python3"
        target = self._python.as_posix()
        # LF endings are mandatory: CRLF would put \r into the exec line.
        shim.write_text(
            f'#!/bin/sh\nexec "{target}" -X utf8 "$@"\n',
            encoding="utf-8", newline="\n")

    def _build_bash_env(self) -> dict:
        git_root = Path(self._bash).parents[2]
        env = dict(os.environ)
        home_drive, home_path = os.path.splitdrive(str(self.home_dir))
        env.update({
            "TMP": str(self.tmp_dir),
            "TEMP": str(self.tmp_dir),
            "HOME": str(self.home_dir),
            # Windows Python resolves ~ through USERPROFILE (HOME is ignored),
            # so pin it to the guest home too: expanduser('~') inside any
            # guest program must land on this sandbox disk, never on the real
            # host home (where live platform login profiles like
            # ~/*_creator_profile live).  APPDATA/LOCALAPPDATA stay host-side
            # so package caches keep working.
            "USERPROFILE": str(self.home_dir),
            "HOMEDRIVE": home_drive,
            "HOMEPATH": home_path,
            "PYTHONUTF8": "1",
            "PATH": os.pathsep.join([
                str(git_root / "usr" / "bin"),
                str(git_root / "mingw64" / "bin"),
                str(self.bin_dir),
                env.get("PATH", ""),
            ]),
        })
        return env

    def _build_rewrite_rules(self) -> None:
        drive = re.escape(self.drive_letter)
        posix_prefix = re.escape(self.p)
        win_root = rf"[{drive}{self.drive_letter.lower()}]:[/\\]"
        # Longest-first; POSIX forms get a word-character lookbehind so we
        # never touch e.g. "x/z/home/user" inside longer tokens.
        self._rewrite_rules = (
            (re.compile(r"(?<!\w)/home/user(?!\w)"),
             f"{self.p}/home/user"),
            (re.compile(r"(?<!\w)/dev/shm(?!\w)"),
             f"{self.p}/dev/shm"),
        )
        self._restore_rules = (
            (re.compile(posix_prefix + r"/home/user(?!\w)"), "/home/user"),
            (re.compile(posix_prefix + r"/tmp(?!\w)"), "/tmp"),
            (re.compile(posix_prefix + r"/dev/shm(?!\w)"), "/dev/shm"),
            (re.compile(posix_prefix + r"/home(?!\w)"), "/home"),
            (re.compile(posix_prefix + r"/dev(?!\w)"), "/dev"),
            (re.compile(win_root + r"home[/\\]user(?!\w)"), "/home/user"),
            (re.compile(win_root + r"tmp(?!\w)"), "/tmp"),
            (re.compile(win_root + r"dev[/\\]shm(?!\w)"), "/dev/shm"),
        )

    # -- path mapping ----------------------------------------------------

    def guest_to_host(self, path) -> Path:
        """Map a canonical guest path onto the host disk backing the drive."""
        text = str(path).strip()
        low = text.lower()
        posix_prefix = self.p + "/"
        windows_leads = tuple(
            f"{letter}:{sep}"
            for letter in (self.drive_letter.upper(),
                           self.drive_letter.lower())
            for sep in ("/", "\\"))
        canonical = (("/home/user", ("home", "user")),
                     ("/tmp", ("tmp",)),
                     ("/dev/shm", ("dev", "shm")))
        if low == "/" or low == self.p:
            return self.disk_root
        if low.startswith(posix_prefix):
            rest = text[len(posix_prefix):].replace("\\", "/")
            return self.disk_root.joinpath(*rest.split("/")) if rest \
                else self.disk_root
        for prefix, parts in canonical:
            if low == prefix:
                return self.disk_root.joinpath(*parts)
            if low.startswith(prefix + "/"):
                rest = text[len(prefix) + 1:].replace("\\", "/")
                return self.disk_root.joinpath(*parts, *rest.split("/"))
        for lead in windows_leads:
            if low.startswith(lead.lower()) or text.startswith(lead):
                rest = text[3:].replace("\\", "/").lstrip("/")
                return self.disk_root.joinpath(*rest.split("/")) if rest \
                    else self.disk_root
        raise ValueError(
            f"guest path is outside the worktree substrate: {path!r}")

    def host_to_guest(self, host_path) -> str:
        """Inverse of :meth:`guest_to_host` (canonical guest spelling)."""
        candidate = Path(host_path).resolve()
        disk = self.disk_root.resolve()
        rel = candidate.relative_to(disk)
        parts = rel.parts
        head = tuple(part.lower() for part in parts[:2])
        if head == ("home", "user"):
            return "/home/user/" + "/".join(parts[2:])
        if parts and parts[0].lower() == "tmp":
            return "/tmp/" + "/".join(parts[1:])
        if head == ("dev", "shm"):
            return "/dev/shm/" + "/".join(parts[2:])
        return "/" + "/".join(parts)

    # -- command transport -----------------------------------------------

    def rewrite_command(self, command: str) -> str:
        """Guest-canonical -> drive form, for exactly the two unmapped roots."""
        for pattern, replacement in self._rewrite_rules:
            command = pattern.sub(replacement, command)
        return command

    def _restore_line(self, line: str) -> str:
        for pattern, replacement in self._restore_rules:
            line = pattern.sub(replacement, line)
        return line

    def _restore_envelope_line(self, line: str) -> str:
        """Restore paths inside a b64 program-output envelope.

        The envelope is ASCII base64, so textual program output round-trips
        decode -> restore -> re-encode losslessly; non-UTF-8 (binary) output
        keeps its exact bytes untouched.
        """
        marker = _RUN_OUTPUT_B64_PREFIX
        payload = line[len(marker):]
        try:
            raw = base64.b64decode(payload, validate=True)
            text = raw.decode("utf-8")
        except Exception:  # noqa: BLE001 - binary or malformed: keep bytes
            return line
        restored = self._restore_line(text)
        if restored == text:
            return line
        return marker + base64.b64encode(
            restored.encode("utf-8")).decode("ascii")

    def restore_text(self, text: str) -> str:
        """Drive-form -> canonical guest spelling for ALL guest output.

        Per-VM drive letters must never reach agent context or captured
        artifacts: a candidate that baked ``/z/...`` into a file would break
        when replayed on another VM's drive.  Envelope lines are restored
        through their base64 payload (see :meth:`_restore_envelope_line`).
        """
        if not text:
            return text
        marker = _RUN_OUTPUT_B64_PREFIX
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if line.startswith(marker):
                lines[index] = self._restore_envelope_line(line)
            else:
                lines[index] = self._restore_line(line)
        return "\n".join(lines)

    def _execute(self, command: str, timeout: int):
        """Run one guest command; returns (stdout, stderr, returncode)."""
        if not command.strip():
            return "", "", 0
        rewritten = self.rewrite_command(command)
        script = self._script_dir / f"exec-{uuid.uuid4().hex}.sh"
        script.write_text(rewritten, encoding="utf-8", newline="\n")
        env = dict(self._bash_env)
        env["RSIAGENT_EXECUTE_SCRIPT"] = script.as_posix()
        # Constant-size argv: CreateProcess caps command lines at 32767
        # chars, below the stock 32 KiB inline base64 program envelope.
        # Sourcing keeps $0="bash", stdin free (DEVNULL, matching stock
        # server semantics) and exit codes exact.
        argv = [self._bash, "--noprofile", "--norc", "-c",
                '. "$RSIAGENT_EXECUTE_SCRIPT"']
        try:
            proc = subprocess.Popen(
                argv, env=env, cwd=str(self.home_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                out_b, err_b = proc.communicate(
                    timeout=max(1.0, float(timeout)) + _SERVER_KILL_GRACE_SECS)
            except subprocess.TimeoutExpired:
                # The guest's own GNU timeout fires first and returns a
                # partial trace; this backstop only reaps escaped trees.
                self._kill_tree(proc.pid)
                try:
                    out_b, err_b = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    out_b, err_b = b"", b""
            return (self.restore_text(out_b.decode("utf-8", "replace")),
                    self.restore_text(err_b.decode("utf-8", "replace")),
                    proc.returncode)
        finally:
            for _ in range(2):
                try:
                    script.unlink()
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.2)

    @staticmethod
    def _kill_tree(pid: int) -> None:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)

    def _controller_get_file(self, path, max_bytes=None):
        host = self.guest_to_host(path)
        data = host.read_bytes()
        if max_bytes is not None and len(data) > int(max_bytes):
            raise ValueError(
                f"file is {len(data)} bytes (limit {max_bytes})")
        return data

    # -- lifecycle ---------------------------------------------------------

    def reset(self, task_config=None) -> None:
        """Fresh null-task boundary: wipe the whole guest disk (snapshot
        semantics) and rebuild the substrate layout.  Fails closed: callers
        convert exceptions into PracticeInfrastructureError."""
        self.is_environment_used = True
        last_error = None
        for target in (self.home_dir, self.tmp_dir, self.shm_dir):
            for attempt in range(2):
                try:
                    if target.exists():
                        rmtree_force(target)
                    break
                except OSError as exc:
                    last_error = exc
                    time.sleep(1.0)
            else:
                if last_error is not None:
                    raise last_error
        for sub in ("home/user/bin", "home/user/work", "tmp", "dev/shm"):
            (self.disk_root / sub).mkdir(parents=True, exist_ok=True)
        self._write_python3_shim()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with _LIVE_LOCK:
            _LIVE.discard(self)
        try:
            self._server.shutdown()
            self._server.server_close()
            self._server_thread.join(timeout=10)
        except Exception as exc:  # noqa: BLE001
            log.warning("execute server shutdown issue (%s): %s",
                        self.drive_letter, exc)
        if not _release_drive(self.drive_letter):
            log.error("subst %s: could not release the guest drive; "
                      "run `subst %s: /D` manually", self.drive_letter,
                      self.drive_letter)
        if self._keep_scratch:
            log.info("keeping worktree scratch: %s", self.scratch)
            return
        shutil.rmtree(self.scratch, ignore_errors=True)
        if self.scratch.exists():
            log.warning("worktree scratch partially retained "
                        "(in-flight guest process?): %s", self.scratch)
        else:
            log.info("worktree guest down: %s:", self.drive_letter)


# --------------------------------------------------------------------- VM adapter

class WorktreeVM(VM):
    """Stock VM over the worktree substrate; only file transport is replaced.

    run_command / run_script / wait_for_controller are reused byte-identical:
    they POST to the local execute server, whose command transport, timeout
    semantics, and output envelope match the OSWorld guest contract.
    """

    def __init__(self, env: WorktreeEnv):
        super().__init__(env)
        # Insurance for code paths that read the password off the VM handle.
        self.client_password = env.client_password

    def fetch_file(self, path: str, max_bytes: int | None = None):
        """Pull guest bytes host-side; stock return contract."""
        try:
            host = self.env.guest_to_host(path)
            data = host.read_bytes()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch_file(%s) failed: %s", path, exc)
            return None, f"error reading the file ({type(exc).__name__})"
        if not data:
            return None, "file not found or empty"
        if max_bytes is not None and len(data) > max_bytes:
            return None, (f"file is {len(data)} bytes (limit {max_bytes}) — "
                          "downscale or crop it with a program first")
        return data, ""

    def push_file(self, local_path: str, guest_path: str,
                  attempts: int = 3, timeout: int = 3600):
        """Stream a host artifact into the guest; stock return contract."""
        if (not isinstance(local_path, str) or not local_path
                or os.path.islink(local_path) or not os.path.isfile(local_path)):
            return False, "host artifact is not an ordinary file"
        if not isinstance(guest_path, str) or not guest_path:
            return False, "guest artifact path is empty"
        try:
            host = self.env.guest_to_host(guest_path)
            host.parent.mkdir(parents=True, exist_ok=True)
            staged = host.with_name(
                host.name + ".rsiagent-part-" + uuid.uuid4().hex[:8])
            shutil.copyfile(local_path, staged)
            os.replace(staged, host)
        except Exception as exc:  # noqa: BLE001
            log.warning("push_file(%s -> %s) failed: %s",
                        local_path, guest_path, exc)
            return False, f"worktree push failed ({type(exc).__name__}: {exc})"
        return True, ""


# --------------------------------------------------------------------- factory

def worktree_vm_factory(**env_kwargs):
    """Build the vm_factory evolve_parallel_phase1 expects.

    Each call allocates a fresh subst drive, scratch disk, and execute
    server; the returned (desktop, vm) pair owns them and phase1_wave's
    close() lifecycle releases everything.
    """
    def factory():
        env = WorktreeEnv(**env_kwargs)
        return env, WorktreeVM(env)
    return factory


def close_all_live() -> None:
    """atexit safety net: release subst drives from leaked environments."""
    with _LIVE_LOCK:
        envs = list(_LIVE)
    for env in envs:
        try:
            env.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


atexit.register(close_all_live)


__all__ = [
    "BASH_CANDIDATES",
    "DEFAULT_SCRATCH_ROOT",
    "WorktreeEnv",
    "WorktreeVM",
    "copytree_force",
    "find_bash",
    "rmtree_force",
    "worktree_vm_factory",
]
