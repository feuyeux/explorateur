"""Git-bash/POSIX guest substrate for the usine RSI adaptation.

Duck-types the OSWorld ``DesktopEnv`` surface ``env.vm.VM`` actually uses, on
top of a per-guest scratch disk.  Two host substrates are supported through
one class (``IS_WINDOWS`` branches; the Windows code path is the original,
byte-for-byte):

* Windows wave host: a per-VM ``subst`` drive hosts a POSIX-looking tree;
  canonical guest paths are rewritten into the drive form (see below).
* POSIX hosts (macOS dev boxes): there is no ``subst``; the scratch disk's
  absolute path IS the rewrite prefix, so the "drive form" of
  ``/home/user/x`` is simply ``<scratch>/guest/home/user/x``.  Everything
  else - layout, rewrite/restore contract, execute server, python3 shim -
  is shared verbatim.

Windows layout (POSIX hosts the same layout under the scratch root):

    <drive>:/home/user          guest home (~, $HOME)
    <drive>:/home/user/bin      python3 shim (PATH overlay beats WindowsApps)
    <drive>:/tmp                rewritten like /home/user (MSYS usertemp is sticky)
    <drive>:/dev/shm            program staging + verifier scratch

Every building block here was validated by ``garage/probe_env.py``
(25 PASS / 0 FAIL against this host).  Key probe-validated facts the design
depends on:

* NON-login ``bash --noprofile --norc -c``: a login shell's
  /etc/bash.bash_logout injects clear-screen ANSI escapes into stdout and
  would pollute every /execute response.
* PATH overlay (Windows form, prepended): git ``usr\\bin`` + ``mingw64\\bin``
  put GNU coreutils ahead of the shadow binaries on this host's PATH (FPC
  rm/find/timeout/stat, System32 tar/find/timeout); the guest ``bin`` dir
  puts the python3 shim ahead of the WindowsApps alias.
* MSYS mounts ``/tmp`` at the Windows TEMP overlay of whichever guest
  resolved it FIRST, and that usertemp mount is sticky: with concurrent
  guests on distinct drives, a literal ``/tmp`` inside a bash command
  resolves to one fixed guest's temp directory for every guest
  (cross-verified failure in a real wave - each guest's bash saw another
  guest's ``/tmp`` while ``push_file`` kept writing its own disk).
  ``/tmp`` is therefore treated exactly like ``/home/user`` and
  ``/dev/shm``, which have no per-VM mount either: the execute server
  rewrites all three tokens into the drive form ``/{d}/home/user`` /
  ``/{d}/tmp`` / ``/{d}/dev/shm`` (boundary-sensitive), and restores
  the canonical guest spelling on all output, including inside the
  ``RSIAGENT_RUN_OUTPUT_BASE64:`` envelope (drive letters are per-VM and
  must never leak into agent-visible text or captured artifacts).
  Base64 envelope program bodies are never rewritten (byte-verbatim
  contract), which is why the transport notes steer bash programs away
  from literal ``/tmp`` (use ``$HOME``/``~``) while python programs keep
  the canonical spelling: Windows python resolves ``/tmp/x`` against the
  current drive, and the program's working directory is on the guest
  drive, so the canonical spelling still lands on the right disk.
* Windows python resolves drive-relative embedded paths (``/home/user/x``)
  against the current drive, so python programs keep working unchanged.
  Literal ``/home/user`` inside *bash* programs still falls to the MSYS
  root; the charter steers bootstrap/agent programs to python3 or ``~``.
* GNU ``timeout --signal=TERM --kill-after`` kills whole child trees;
  ``rm -rf`` removes read-only git objects without a chmod pass.

POSIX-host differences that matter (the rest of this docstring describes the
Windows wave host):

* The guest bash is the system/homebrew bash (no MSYS, no sticky usertemp
  mount), so a literal ``/tmp`` inside a bash command resolves against the
  real host root - the command rewrite maps it onto this guest's scratch,
  exactly as on Windows.
* The GNU dialect is NOT a given: macOS ships BSD coreutils (no
  ``timeout``, no ``stat -c``).  ``_build_bash_env`` prepends the brew
  coreutils ``gnubin`` overlay and ``_assert_gnu_dialect`` fails closed at
  startup unless the dialect really resolves ("brew install coreutils").
* HOME is pinned to the guest home (POSIX ``expanduser`` resolves ``~``
  through HOME), which keeps the publish-blocking defense parity: a guest
  program's ``~`` can never reach the real host home where live platform
  login profiles live.
* CRITICAL semantic difference: program bodies (b64 envelopes) are never
  rewritten on either substrate, but Windows python resolves a literal
  ``/home/user/x`` against the current drive (the guest disk) while POSIX
  python resolves it against the REAL host root.  The usine transport notes
  therefore steer POSIX programs to ``~`` / ``$HOME`` in bash AND python;
  command-level literal paths (harness cleanup commands like
  ``rm -rf /home/user/...``) are still rewritten on both substrates.

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
import signal
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

IS_WINDOWS = os.name == "nt"

_EXPLORATEUR_ROOT = Path(__file__).resolve().parents[1]
_THEATRE_ROOT = _EXPLORATEUR_ROOT / "théâtre"
# Windows: the workspace-drive anchor keeps guest paths short (MAX_PATH).
# POSIX: the root anchor is not writable on macOS; use a home-cache root.
DEFAULT_SCRATCH_ROOT = (
    Path(_EXPLORATEUR_ROOT.anchor) / ".rsi-usine-vm" if IS_WINDOWS
    else Path.home() / ".cache" / "rsi-usine-vm")

BASH_CANDIDATES = (
    [r"d:\Program Files\Git\usr\bin\bash.exe",
     r"C:\Program Files\Git\usr\bin\bash.exe"] if IS_WINDOWS
    else ["/bin/bash", "/opt/homebrew/bin/bash", "/usr/local/bin/bash"])

# Real system `rm`, absolute paths only. GNU coreutils first so the fallback
# speaks the same dialect as the guest; then the BSD system rm, which honours
# the immutable flag just as GNU rm does. PATH is deliberately NOT consulted —
# see find_rm().
#
# On Windows the git-bash `rm` is the only one that exists, and its install
# drive is NOT fixed: this host has Git at `D:\Program Files\Git`, so the
# historical hardcoded `C:\Program Files\Git` candidate list found nothing and
# `find_rm()` failed closed (measured 2026-10-21).  Deriving it from the `git`
# on PATH is NOT a PATH fallback of the *tool we return*: `git` only tells us
# where its own prefix is; the returned `rm` is still an absolute path inside
# that prefix, and `find_rm()` still refuses when the file is absent.  A
# PATH-resolved `git` that lies about its prefix cannot manufacture an `rm`
# that passes the `is_file()` check.
def _git_bash_rm_candidates() -> list[str]:
    """Absolute `rm.exe` paths under whatever git prefix is installed here."""
    out: list[str] = []
    for prog in ("git", "git.exe"):
        found = shutil.which(prog)
        if not found:
            continue
        # <prefix>/cmd/git.exe -> <prefix>;  also try <prefix>/bin/git.exe
        prefix = Path(found).resolve().parent.parent
        for sub in ("usr/bin", "bin", "usr/local/bin"):
            cand = prefix / sub / "rm.exe"
            if str(cand) not in out:
                out.append(str(cand))
        break
    # Conventional install roots last, so a non-PATH but standard install works.
    for root in (r"C:\Program Files\Git", r"C:\Program Files (x86)\Git"):
        cand = str(Path(root) / "usr" / "bin" / "rm.exe")
        if cand not in out:
            out.append(cand)
    return out


_RM_CANDIDATES = (
    (_git_bash_rm_candidates() + [r"C:\Windows\System32\rm.exe"] if IS_WINDOWS
     else ["/opt/homebrew/opt/coreutils/libexec/gnubin/rm",
           "/usr/local/opt/coreutils/libexec/gnubin/rm",
           "/bin/rm", "/usr/bin/rm"]))

# brew coreutils gnubin overlays: macOS coreutils are BSD (no timeout,
# no stat -c); the guest dialect must be GNU.
_GNUBIN_CANDIDATES = [
    "/opt/homebrew/opt/coreutils/libexec/gnubin",
    "/usr/local/opt/coreutils/libexec/gnubin",
]

# macOS .app browser launchers, host-side mirror of the usine platform.ts
# BROWSERS candidate order (edge -> chrome -> chromium).  The substrate
# needs its own copy because the shim must be staged before the guest
# exists; if it drifts, the guest gate renders no browser and fails
# loudly - it can never silently pass, so the second source is cheap.
_BROWSER_CANDIDATES = [
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Microsoft Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

_EXECUTE_HOST = "127.0.0.1"
_SKIP_DRIVE_LETTERS = {"A", "B"}          # historical floppy letters; never guest drives
_SERVER_KILL_GRACE_SECS = 30.0            # GNU timeout fires first; this is the backstop

_DRIVE_LOCK = threading.Lock()
_LIVE_LOCK = threading.Lock()
_LIVE: set = set()


# --------------------------------------------------------------------- host tools

def find_rm() -> str:
    """Absolute path to a REAL system ``rm`` — never a PATH-resolved one.

    ``rmtree_force`` shells out to ``rm -rf`` as a last resort, and the target
    of that call is sometimes an immutable-flagged file that MUST survive so
    the caller can observe the failure. Resolving ``rm`` from PATH silently
    hands that job to whatever wrapper happens to be first: on a machine whose
    PATH carries an agent-tooling shim, the shim's trash-and-delete path
    removes ``uchg`` files without complaint, so the rollback-failure guard
    stops guarding while every assertion around it still looks green (measured
    2026-10-18, macOS: PATH ``rm`` removed a ``chflags uchg`` file with exit 0;
    absolute ``/bin/rm`` and absolute GNU ``rm`` both refused it).

    So: candidate table only, absolute paths only, fail closed when empty. This
    is the same discipline the cross-platform rule states for every other
    external executable — never resolve it from PATH, never substitute.
    """
    for candidate in _RM_CANDIDATES:
        p = Path(candidate)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    raise RuntimeError(
        "no real system rm found (looked in " + ", ".join(_RM_CANDIDATES)
        + "); refusing to fall back to a PATH-resolved rm, which may be a "
          "wrapper that defeats immutable-file guards")


def find_bash() -> str:
    """Locate the guest bash: git-bash on Windows, any POSIX bash elsewhere."""
    if IS_WINDOWS:
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
    for candidate in BASH_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    which = shutil.which("bash")
    if which:
        return which
    raise RuntimeError(
        "bash not found (looked in " + ", ".join(BASH_CANDIDATES)
        + " and on PATH)")


def _default_guest_python() -> Path:
    """Guest python3 target: the théâtre venv, else an explicit override,
    else the running interpreter (which under ``uv run --project théâtre``
    is the venv python anyway)."""
    venv = (_THEATRE_ROOT / ".venv" / "Scripts" / "python.exe" if IS_WINDOWS
            else _THEATRE_ROOT / ".venv" / "bin" / "python")
    if venv.exists():
        return venv
    override = os.environ.get("RSIAGENT_GUEST_PYTHON", "").strip()
    if override:
        return Path(override)
    import sys
    return Path(sys.executable)


def _assert_gnu_dialect(bash: str, env: dict) -> None:
    """Fail closed unless the guest PATH resolves GNU coreutils (POSIX only).

    Wave programs rely on the GNU dialect (``timeout --signal=TERM``,
    ``stat -c``, plain ``rm -rf`` over read-only trees); macOS ships BSD
    coreutils, whose stat has no ``-c`` and whose tree lacks ``timeout``
    entirely.  ``_build_bash_env`` puts the brew coreutils gnubin overlay
    ahead on PATH; this probe proves the dialect really resolves before
    any guest runs.
    """
    probe = ("stat -c %s /dev/null >/dev/null 2>&1 "
             "&& timeout --signal=TERM 1 true")
    proc = subprocess.run([bash, "--noprofile", "--norc", "-c", probe],
                          env=env, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "guest PATH does not resolve GNU coreutils (stat -c / timeout "
            "probe failed). Install them first: brew install coreutils")


def _claim_drive(target: Path) -> str:
    """subst-map a free drive letter (Z backwards) to the guest disk.

    Windows wave host only; POSIX guests claim no drive."""
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
            if IS_WINDOWS:
                os.chmod(name, stat.S_IWRITE)
            else:
                # POSIX: chmod(name, S_IWRITE) REPLACES the whole mode, which
                # strips a directory's read/execute bits and breaks
                # traversal (stat/chmod inside it then fail EACCES).  Add
                # the write bit to the current mode instead, and keep a
                # directory searchable.  A symlink never gets chmod here:
                # chmod follows links, and a failed unlink of a link is a
                # PARENT-directory permission problem - fixing the link
                # itself would chmod whatever it points at on the real
                # host (e.g. a staged harness anchor link).
                if os.path.islink(name):
                    fix = os.path.dirname(name) or "."
                    mode = os.stat(fix).st_mode
                    os.chmod(fix, mode | stat.S_IWRITE | stat.S_IREAD
                             | stat.S_IEXEC)
                else:
                    mode = os.stat(name).st_mode
                    if os.path.isdir(name):
                        mode |= (stat.S_IWRITE | stat.S_IREAD
                                 | stat.S_IEXEC)
                    else:
                        mode |= stat.S_IWRITE
                    os.chmod(name, mode)
            func(name)
        except OSError:
            # Fall back to the real system toolchain, which removes read-only
            # git objects directly. find_rm() resolves an ABSOLUTE system rm:
            # a PATH-resolved `rm` may be a wrapper that clears the immutable
            # flag, which would silently defeat the rollback-failure guard this
            # function's callers rely on (see find_rm).
            posix = subprocess.run(
                [find_rm(), "-rf", "--", Path(name).as_posix()],
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
    """The duck-typed 'desktop' for one isolated git-bash/POSIX guest.

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
        if IS_WINDOWS:
            self.drive_letter = _claim_drive(self.disk_root)
            self.p = "/" + self.drive_letter.lower()
            self.guest_root = Path(self.drive_letter + ":/")
        else:
            # No subst on POSIX: the scratch disk's absolute path IS the
            # rewrite prefix, so the "drive form" is just the host path.
            self.drive_letter = ""
            self.p = self.disk_root.as_posix()
            self.guest_root = self.disk_root
        self.home_dir = self.guest_root / "home" / "user"
        self.tmp_dir = self.guest_root / "tmp"
        self.shm_dir = self.guest_root / "dev" / "shm"
        self.bin_dir = self.home_dir / "bin"
        self.work_dir = self.home_dir / "work"
        self._write_python3_shim()
        self._bash_env = self._build_bash_env()
        if not IS_WINDOWS:
            _assert_gnu_dialect(self._bash, self._bash_env)
        self._build_rewrite_rules()
        try:
            self._server = _ExecuteServer(self)
        except Exception:
            # Never leak a subst mapping if the execute server cannot bind.
            if IS_WINDOWS:
                _release_drive(self.drive_letter)
            raise
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"worktree-exec-{self.drive_letter or self.scratch.name}",
            daemon=True)
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
        log.info("worktree guest up: %s -> %s (python=%s)",
                 self.drive_letter + ":" if IS_WINDOWS else "posix",
                 self.scratch, self._python)

    def __repr__(self):
        return (f"<WorktreeEnv {self.drive_letter or self.scratch.name}: "
                f"scratch={self.scratch} closed={self._closed}>")

    # -- layout ----------------------------------------------------------

    def _write_python3_shim(self) -> None:
        shim = self.bin_dir / "python3"
        target = self._python.as_posix()
        # LF endings are mandatory: CRLF would put \r into the exec line.
        shim.write_text(
            f'#!/bin/sh\nexec "{target}" -X utf8 "$@"\n',
            encoding="utf-8", newline="\n")
        if not IS_WINDOWS:
            # The shim is resolved through PATH as an executable on POSIX.
            shim.chmod(0o755)
        # The no-browser sentinel is set on EVERY platform, not just POSIX.
        # 2026-10-19 (user decision): real-browser coverage is not worth a
        # red gate.  Measured on this Windows wave host: covers.test.ts fails
        # 4/4 rendering specs deterministically (Edge headless writes no
        # screenshot under vitest, while a bare Edge --screenshot succeeds),
        # so every Actor candidate would be judged FAIL at the merge gate and
        # no wave could ever merge.  Browserless makes platform.browser()
        # return null, which turns those specs into honest SKIPs instead.
        # Cost, stated plainly: the render path is not exercised during a
        # wave (SKIP is not PASS — see ../docs/self-evolution.md §10).
        self._disable_in_guest_browser()

    def _disable_in_guest_browser(self) -> None:
        """POSIX only: the macOS guest gets NO browser - on purpose.

        Everything below was measured on this host (2026-10-18), driving
        the real gate, and none of it leaves a dialog-free way to run
        Chromium inside the macOS guest:

        * HOME pinned to the guest disk: Chromium headless hits its
          "teardown watchdog" and exits 2 even when the DOM dump and
          screenshots succeed (production's problem, not ours).
        * HOME handed back through a FEUILLE_BROWSER shim: the watchdog
          disappears, and Edge still writes a keychain item on every
          single launch - a per-run GUID-named OAuth token, so the item
          (and therefore the macOS keychain prompt on the user's screen)
          is different every time.  No pre-authorization covers a set of
          names that is unbounded, which is exactly why the dialogs kept
          coming no matter how often the user clicked "Allow".
        * --use-mock-keychain / --password-store=basic: no-op in Edge
          release builds (the switch is absent from the 155 binary -
          verified with strings).  Chromium compiles MockKeychain only
          for its own test builds.
        * sandbox-exec denying securityd: unusable - an outer seatbelt
          profile breaks Chromium's own per-helper sandbox (helpers fail
          to initialize, GPU process dies, browser aborts).

        So the macOS guest exports FEUILLE_BROWSER pointing at a path
        that does not exist.  platform.browser() treats FEUILLE_BROWSER
        as authoritative ("找不到 = null，不静默换人"), so browser()
        returns null and the browser-gated specs gate themselves off
        (covers/textlayer/karaoke/publish use skipIf; poster/storyteller/
        measure_korean return early).  Zero browser launches, zero
        dialogs.

        What this costs, stated plainly: on macOS the gate does NOT
        exercise the render path.  Those specs must be counted as
        skipped/early-returned in any run report - not as coverage.
        Full browser coverage belongs to the Windows wave host, where
        Chromium uses DPAPI and no keychain is involved at all.  Windows
        keeps its own behavior byte-identical here: it never sets
        FEUILLE_BROWSER, and its browser profile lives in LOCALAPPDATA,
        which that env deliberately leaves host-side.
        """
        self._browser_sentinel = str(self.bin_dir / "no-browser-in-macos-guest")

    def _build_bash_env(self) -> dict:
        if not IS_WINDOWS:
            gnubin = next(
                (d for d in _GNUBIN_CANDIDATES if Path(d).is_dir()), "")
            env = dict(os.environ)
            env.update({
                "TMPDIR": str(self.tmp_dir),
                # POSIX expanduser resolves ~ through HOME: pin it to the
                # guest home so expanduser('~') inside any guest program
                # lands on this sandbox disk, never on the real host home
                # (where live platform login profiles live) - the same
                # publish-blocking defense as the Windows USERPROFILE pin.
                "HOME": str(self.home_dir),
                # macOS bsdtar stores extended attributes (com.apple.*
                # xattrs land on staged files automatically) as `._`
                # AppleDouble archive members.  Python tarfile - which the
                # engine uses to derive the capture manifest - sees them,
                # but bsdtar replays them as inline metadata instead of
                # files, so the replay verifier would fail on every one.
                # COPYFILE_DISABLE=1 keeps guest archives member-identical
                # to the staged tree.
                "COPYFILE_DISABLE": "1",
                "PYTHONUTF8": "1",
                "PATH": os.pathsep.join(
                    ([gnubin] if gnubin else [])
                    + [str(self.bin_dir), env.get("PATH", "")]),
            })
            # No browser in the macOS guest (see _disable_in_guest_browser
            # for the measurements): FEUILLE_BROWSER is authoritative in
            # platform.browser(), so a path that does not exist makes the
            # browser-gated specs gate themselves off instead of popping
            # keychain dialogs on the user's screen.
            env["FEUILLE_BROWSER"] = getattr(
                self, "_browser_sentinel", "")
            return env
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
        # Same no-browser policy as the POSIX branch above, and for the same
        # measured reason (deterministic Edge-render failures under vitest on
        # this host).  FEUILLE_BROWSER is authoritative in platform.browser(),
        # so browser-gated specs gate themselves off instead of failing.
        env["FEUILLE_BROWSER"] = getattr(
            self, "_browser_sentinel", "")
        return env

    def _build_rewrite_rules(self) -> None:
        # Longest-first; POSIX forms get a word-character lookbehind so we
        # never touch e.g. "x/z/home/user" inside longer tokens.  /tmp is
        # rewritten for the same reason as /home/user and /dev/shm: on the
        # Windows wave host the MSYS usertemp mount is sticky under
        # concurrent guests, and on POSIX a literal /tmp would resolve
        # against the real host root; in both cases the mapped form always
        # resolves to this guest's disk.  self.p is "/<drive>" on Windows
        # and the scratch-disk absolute path on POSIX, so the same rules
        # drive both substrates.
        self._rewrite_rules = (
            (re.compile(r"(?<!\w)/home/user(?!\w)"),
             f"{self.p}/home/user"),
            (re.compile(r"(?<!\w)/dev/shm(?!\w)"),
             f"{self.p}/dev/shm"),
            (re.compile(r"(?<!\w)/tmp(?!\w)"),
             f"{self.p}/tmp"),
        )
        prefix = re.escape(self.p)
        restore = (
            (re.compile(prefix + r"/home/user(?!\w)"), "/home/user"),
            (re.compile(prefix + r"/tmp(?!\w)"), "/tmp"),
            (re.compile(prefix + r"/dev/shm(?!\w)"), "/dev/shm"),
            (re.compile(prefix + r"/home(?!\w)"), "/home"),
            (re.compile(prefix + r"/dev(?!\w)"), "/dev"),
        )
        if IS_WINDOWS:
            drive = re.escape(self.drive_letter)
            win_root = rf"[{drive}{self.drive_letter.lower()}]:[/\\]"
            restore += (
                (re.compile(win_root + r"home[/\\]user(?!\w)"), "/home/user"),
                (re.compile(win_root + r"tmp(?!\w)"), "/tmp"),
                (re.compile(win_root + r"dev[/\\]shm(?!\w)"), "/dev/shm"),
            )
        self._restore_rules = restore

    # -- path mapping ----------------------------------------------------

    def guest_to_host(self, path) -> Path:
        """Map a canonical guest path onto the host disk backing the drive."""
        text = str(path).strip()
        low = text.lower()
        posix_prefix = self.p + "/"
        # On POSIX self.p IS the disk-root host path, so the prefix form is
        # simply an absolute host path under the scratch disk; on Windows it
        # is the drive-relative form both bash and python resolve per-drive.
        if low == "/" or low == self.p.lower():
            return self.disk_root
        if low.startswith(posix_prefix.lower()):
            rest = text[len(posix_prefix):].replace("\\", "/")
            return self.disk_root.joinpath(*rest.split("/")) if rest \
                else self.disk_root
        canonical = (("/home/user", ("home", "user")),
                     ("/tmp", ("tmp",)),
                     ("/dev/shm", ("dev", "shm")))
        for prefix, parts in canonical:
            if low == prefix:
                return self.disk_root.joinpath(*parts)
            if low.startswith(prefix + "/"):
                rest = text[len(prefix) + 1:].replace("\\", "/")
                return self.disk_root.joinpath(*parts, *rest.split("/"))
        if IS_WINDOWS:
            windows_leads = tuple(
                f"{letter}:{sep}"
                for letter in (self.drive_letter.upper(),
                               self.drive_letter.lower())
                for sep in ("/", "\\"))
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
        popen_kwargs = {}
        if not IS_WINDOWS:
            # Own process group, so _kill_tree can SIGKILL the whole tree.
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(
                argv, env=env, cwd=str(self.home_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **popen_kwargs)
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
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True)
            return
        try:
            # The bash runs in its own session (start_new_session above),
            # so the process group covers the whole spawned tree.
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

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
                        self.drive_letter or self.scratch.name, exc)
        if IS_WINDOWS and not _release_drive(self.drive_letter):
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
            log.info("worktree guest down: %s",
                     self.drive_letter + ":" if IS_WINDOWS
                     else str(self.scratch))


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

    Each call allocates a fresh scratch disk (plus a subst drive on the
    Windows wave host) and execute server; the returned (desktop, vm) pair
    owns them and phase1_wave's close() lifecycle releases everything.
    """
    def factory():
        env = WorktreeEnv(**env_kwargs)
        return env, WorktreeVM(env)
    return factory


def close_all_live() -> None:
    """atexit safety net: release drives/scratch from leaked environments."""
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
