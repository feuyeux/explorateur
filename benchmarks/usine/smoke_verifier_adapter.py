"""End-to-end smoke test for verifier_adapter.py.

Runs the REAL stock program transport (inherited ``_run_harness_script`` ->
``VM.run_script``) against a live WorktreeEnv + WorktreeVM and asserts every
seam the usine RSI adapter depends on:

  * install_verifier_adapter(): executor class patched into
    core.verifier_runtime, idempotent, verifier system prompt carries
    substrate-true facts (no Ubuntu/QEMU/tmpfs claims), drive-qualified Look
    paths validate like canonical ones while host paths stay rejected
  * rollback_mirror enforcement + WorktreeEnv-backed VM requirement
  * ready-token contract: token present before model output and stripped;
    VERIFIER_SCRATCH exported, usable from BOTH bash and python, restored to
    canonical spelling in all agent-visible output
  * host-side quarantine: Actor-private paths vanish from the guest while
    the verifier runs and are restored by rollback
  * scratch persistence: export_scratch tar -> close -> fresh executor with
    scratch_archive -> restored files readable through VERIFIER_SCRATCH
  * rollback fidelity: candidate mutations gone, private paths back,
    workspace gone, quarantine dropped; close idempotent; close without
    initialization is a no-op rollback
  * rollback failure semantics: a host-side file lock makes close() raise
    AgenticVerifierInfrastructureError, the checkpoint AND quarantine are
    retained for recovery, and the module's own helpers can restore manually
  * process sweep: a guest background process holding a file open (drive
    path in its command line) is killed so rollback still succeeds
  * transport contracts through the verifier channel: binary output
    externalization (archived envelope decodes to the exact bytes) and
    >32KiB programs stream losslessly

Usage (théâtre venv; keep child argv ASCII on PowerShell 5.1):
    cd D:\\coding\\personal\\explorateur\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\benchmarks\\usine\\smoke_verifier_adapter.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[1]


def _find_theatre() -> Path:
    for candidate in sorted(EXPLORATEUR.iterdir()):
        if ((candidate / "env" / "vm.py").is_file()
                and (candidate / "explore" / "practice_loop.py").is_file()):
            return candidate
    raise SystemExit("the théâtre checkout (env/vm.py + explore/practice_loop.py) "
                     "was not found under " + str(EXPLORATEUR))


THEATRE = _find_theatre()
sys.path.insert(0, str(THEATRE))
sys.path.insert(0, str(HERE))

import verifier_adapter  # noqa: E402  (imports guest_env + core.verifier_runtime)
import guest_env  # noqa: E402
from core import verifier_runtime  # noqa: E402
from core.verifier_runtime import AgenticVerifierInfrastructureError  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    line = f"{status} {name}"
    if detail:
        line += f" | {detail}"
    print(line)


def check(name: str, ok, detail: str = "") -> None:
    record("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:400])


def _kill_sleeper_leak() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { "
         "$_.ProcessId -ne $PID -and $_.CommandLine -match 'sleeper' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        capture_output=True, timeout=60)


# ----------------------------------------------------------------- A: install


def test_install_and_prompts() -> None:
    info = verifier_adapter.install_verifier_adapter()
    check("install: reports fresh install",
          info.get("already_installed") is False, info)
    check("install: executor patched into verifier_runtime",
          verifier_runtime.AgenticVerifierExecutor
          is verifier_adapter.WorktreeVerifierExecutor)
    check("install: idempotent",
          verifier_adapter.install_verifier_adapter()
          .get("already_installed") is True)

    system = verifier_runtime.agentic_verifier_system_for("rollback_mirror")
    check("prompt: no stock false claims",
          "Ubuntu" not in system and "QEMU" not in system
          and "tmpfs" not in system and "GUI,\nand IPC" not in system)
    check("prompt: substrate-true facts present",
          "worktree guest" in system and "file-level" in system
          and "private writable directory" in system
          and "screen Looks are unavailable" in system
          and "$VERIFIER_SCRATCH" in system)
    oriented = verifier_runtime.agentic_verifier_system_for(
        "rollback_mirror", orienting=True)
    check("prompt: orientation variant patched",
          "Ubuntu" not in oriented and "worktree guest" in oriented
          and "ORIENTATION_READY" in oriented)

    validate = verifier_runtime.validate_verifier_look_path
    check("look: canonical path accepted",
          validate("/home/user/work/x.png") == (True, ""))
    check("look: drive-qualified accepted",
          validate("Z:/home/user/work/x.png") == (True, ""))
    check("look: drive backslash accepted",
          validate("z:\\home\\user\\work\\x.png")[0] is True)
    check("look: private rejected in drive form",
          validate("Z:/home/user/.memory/x",
                   hide_actor_memory=True)[0] is False)
    check("look: private rejected canonically",
          validate("/home/user/.memory/x",
                   hide_actor_memory=True)[0] is False)
    check("look: host path rejected", validate("C:/Windows/System32/x.png")[0]
          is False)
    check("look: screen still allowed", validate("screen:")[0] is True)
    check("look: relative still rejected", validate("rel/x.png")[0] is False)
    check("look: url scheme still rejected",
          validate("file:///home/user/report.pptx")[0] is False)


# -------------------------------------------------------------- B: lifecycle


def test_executor_lifecycle() -> None:
    env = guest_env.WorktreeEnv()
    vm = guest_env.WorktreeVM(env)
    sleeper_may_leak = False
    try:
        vm.run_command(
            "mkdir -p ~/work; printf candidate-body > ~/work/candidate.txt")
        vm.run_command(
            "mkdir -p ~/.memory; printf private-body > ~/.memory/secret.md")

        # -- construction guards --------------------------------------
        try:
            verifier_adapter.WorktreeVerifierExecutor(
                vm, execution_mode="effect_isolated")
            check("executor: rejects non-mirror mode", False, "no exception")
        except AgenticVerifierInfrastructureError as exc:
            check("executor: rejects non-mirror mode",
                  "rollback_mirror" in str(exc), exc)

        # -- first program: init + checkpoint + quarantine -----------
        executor = verifier_adapter.WorktreeVerifierExecutor(
            vm, execution_mode="rollback_mirror", hide_actor_memory=True)
        trace = executor(
            "bash",
            'printf hello-from-verifier'
            '; printf " SCRATCH=%s" "$VERIFIER_SCRATCH"'
            "; pwd")
        check("program: bash exit 0", trace.exit_code == 0,
              f"exit={trace.exit_code} out={trace.stdout[-160:]!r}")
        check("program: ready token stripped, output present",
              "hello-from-verifier" in trace.stdout
              and "__RSIAGENT_VERIFIER_MIRROR_READY_"
              not in trace.stdout)
        check("program: VERIFIER_SCRATCH canonical in output",
              " SCRATCH=/home/user/.verifier/rsiagent-verifier-"
              in trace.stdout and env.drive_letter not in trace.stdout,
              trace.stdout[-200:])
        check("program: cwd restored to /home/user",
              "/home/user\n[exit 0]" in trace.stdout, trace.stdout[-120:])
        check("workspace: created on the guest drive",
              executor._workspace.startswith("/home/user/.verifier/")
              and executor._workspace_host().is_dir())
        listing = vm.run_command("ls -a ~")
        check("quarantine: .memory absent from the live guest",
              ".memory" not in listing and "work" in listing, listing)
        check("quarantine: host-side isolation dir exists",
              executor._quarantine_dir is not None
              and executor._quarantine_dir.is_dir())
        record("INFO", "workspace parent .verifier is guest-visible "
              "during the verifier turn (rollback wipes it; recorded "
              "deviation)", "accepted")

        # -- scratch usable from both languages ------------------------
        trace = executor(
            "python",
            "import os\n"
            "p = os.path.join(os.environ['VERIFIER_SCRATCH'], 'note.txt')\n"
            "open(p, 'w').write('verifier-scratch-note\\n')\n"
            "p2 = os.path.join(os.environ['VERIFIER_SCRATCH'], "
            "'scratch-shot.png')\n"
            "open(p2, 'wb').write(b'\\x89PNG-scratch')\n")
        check("program: python writes via VERIFIER_SCRATCH",
              trace.exit_code == 0, trace.stdout[-200:])
        check("scratch: file landed in the workspace host-side",
              (executor._workspace_host() / "note.txt")
              .read_text(encoding="utf-8").strip() == "verifier-scratch-note")
        trace = executor(
            "bash",
            'printf bash-note > "$VERIFIER_SCRATCH/note2.txt"'
            '; cat "$VERIFIER_SCRATCH/note.txt"')
        check("program: bash uses VERIFIER_SCRATCH",
              trace.exit_code == 0 and "verifier-scratch-note" in trace.stdout,
              trace.stdout[-160:])

        # -- candidate mutation + looks --------------------------------
        trace = executor(
            "python",
            "open('/home/user/work/marker.txt', 'w').write('mutation\\n')\n"
            "open('/home/user/work/shot.png', 'wb')"
            ".write(bytes([0x89]) + b'PNG-fake-bytes')\n")
        check("program: python canonical guest paths work",
              trace.exit_code == 0, trace.stdout[-200:])
        data, error = executor.fetch_look_image("/home/user/work/shot.png")
        check("look: candidate image fetched host-side",
              data is not None
              and data == bytes([0x89]) + b"PNG-fake-bytes"
              and not error, str(error))
        data, error = executor.fetch_look_image(
            executor._workspace + "/scratch-shot.png")
        check("look: private scratch file readable",
              data is not None and data == b"\x89PNG-scratch" and not error,
              str(error))
        drive_look = (f"{env.drive_letter}:{executor._workspace}"
                      "/scratch-shot.png")
        allowed, reason = verifier_runtime.validate_verifier_look_path(
            drive_look)
        data, error = executor.fetch_look_image(drive_look)
        check("look: drive-qualified scratch path works",
              allowed and data is not None and not error,
              f"allowed={allowed} reason={reason} error={error}")
        data, error = executor.fetch_look_image("/home/user/.memory/secret.md")
        check("look: private path refused",
              data is None and "private" in (error or ""), str(error))
        data, error = executor.fetch_look_image("screen:")
        check("look: screen unavailable honestly",
              data is None and "unavailable" in (error or ""), str(error))
        data, error = executor.fetch_look_image("/home/user/work/missing.png")
        check("look: missing file errors", data is None and bool(error))

        # -- export + rollback ------------------------------------------
        archive = executor.export_scratch()
        names = []
        if archive:
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                names = tar.getnames()
        check("export: lossless tar of the workspace",
              bool(archive) and "note.txt" in names and "note2.txt" in names
              and "scratch-shot.png" in names, str(names))
        executor.close()
        listing = vm.run_command(
            "ls -a ~; ls ~/work; cat ~/.memory/secret.md")
        check("rollback: candidate restored, mutation gone",
              "marker.txt" not in listing and "candidate.txt" in listing,
              listing)
        check("rollback: private path restored with contents",
              "private-body" in listing, listing)
        check("rollback: workspace wiped from the guest",
              ".verifier" not in listing, listing)
        check("rollback: quarantine dropped after success",
              executor._quarantine_dir is None
              or not executor._quarantine_dir.exists())
        executor.close()
        check("close: idempotent", True)

        # -- scratch archive restore chain -------------------------------
        executor2 = verifier_adapter.WorktreeVerifierExecutor(
            vm, execution_mode="rollback_mirror", hide_actor_memory=True,
            scratch_archive=archive)
        trace = executor2(
            "python",
            "import os\n"
            "p = os.path.join(os.environ['VERIFIER_SCRATCH'], 'note.txt')\n"
            "print(open(p).read().strip())\n")
        check("scratch restore: archive lands in the new workspace",
              trace.exit_code == 0 and "verifier-scratch-note" in trace.stdout,
              trace.stdout[-200:])
        executor2.close()

        # -- close without initialization --------------------------------
        executor3 = verifier_adapter.WorktreeVerifierExecutor(
            vm, execution_mode="rollback_mirror")
        executor3.close()
        listing = vm.run_command("cat ~/work/candidate.txt")
        check("close without init: no-op rollback, guest intact",
              "candidate-body" in listing, listing)

        # -- rollback failure semantics (host-side file lock) ------------
        vm.run_command(
            "mkdir -p ~/work/lockdir; printf locked > ~/work/lockdir/locked.txt")
        executor4 = verifier_adapter.WorktreeVerifierExecutor(
            vm, execution_mode="rollback_mirror", hide_actor_memory=True)
        trace = executor4("bash", "printf probe")
        check("locked-file run: program executed", trace.exit_code == 0,
              trace.stdout[-120:])
        lock_host = env.guest_to_host("/home/user/work/lockdir/locked.txt")
        handle = open(lock_host, "r")
        try:
            try:
                executor4.close()
                check("rollback failure: raises infra error", False,
                      "no exception")
            except AgenticVerifierInfrastructureError as exc:
                check("rollback failure: raises infra error",
                      "not safe to grade" in str(exc), str(exc)[:200])
            checkpoint = executor4._rollback_transaction._snapshot
            check("rollback failure: checkpoint retained for recovery",
                  checkpoint is not None and checkpoint.is_dir())
            check("rollback failure: quarantine retained",
                  executor4._quarantine_dir is not None
                  and executor4._quarantine_dir.is_dir())
        finally:
            handle.close()
        for entry in list(env.disk_root.iterdir()):
            verifier_adapter._remove_entry(entry)
        for entry in list(checkpoint.iterdir()):
            verifier_adapter._copy_entry(
                entry, env.disk_root / entry.name)
        listing = vm.run_command("cat ~/work/candidate.txt; ls ~/.memory")
        check("recovery: manual restore from the retained checkpoint",
              "candidate-body" in listing, listing)
        verifier_adapter.rmtree_force(checkpoint)
        if executor4._quarantine_dir is not None:
            verifier_adapter.rmtree_force(executor4._quarantine_dir)

        # -- process sweep before rollback --------------------------------
        sleeper_local = HERE / "_smoke_sleeper_tmp.py"
        sleeper_local.write_text(
            "import time\n"
            "f = open('/home/user/work/sleeper-held.txt', 'w')\n"
            "time.sleep(600)\n",
            encoding="utf-8", newline="\n")
        ok, why = vm.push_file(
            str(sleeper_local), "/home/user/work/sleeper.py")
        sleeper_local.unlink()
        check("sweep: sleeper script pushed", ok, str(why))
        vm.run_command(
            "nohup python3 /home/user/work/sleeper.py >/dev/null 2>&1 "
            "& echo bg-started")
        sleeper_may_leak = True
        held = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            held = vm.run_command(
                "test -f /home/user/work/sleeper-held.txt "
                "&& echo held || echo missing")
            if "held" in held:
                break
            time.sleep(0.5)
        check("sweep: background sleeper holds a guest file",
              "held" in held, held)
        executor5 = verifier_adapter.WorktreeVerifierExecutor(
            vm, execution_mode="rollback_mirror")
        trace = executor5("bash", "printf probe2")
        check("sweep: verifier program ran", trace.exit_code == 0,
              trace.stdout[-120:])
        try:
            executor5.close()
            check("sweep: rollback succeeds despite the held file", True)
        except AgenticVerifierInfrastructureError as exc:
            check("sweep: rollback succeeds despite the held file", False,
                  str(exc)[:200])
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { "
             "$_.ProcessId -ne $PID -and $_.CommandLine -match 'sleeper' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=60)
        check("sweep: sleeper process killed by the rollback sweep",
              result.returncode == 0
              and not (result.stdout or "").strip(),
              (result.stdout or "")[:120])
        record("INFO", "rollback sweep matches command lines only; a guest "
              "process with no guest path in argv but cwd on the drive may "
              "survive (documented residual)", "accepted")
        listing = vm.run_command("cat ~/work/candidate.txt")
        check("sweep: guest restored after the sweep rollback",
              "candidate-body" in listing, listing)
        sleeper_may_leak = False

        # -- transport contracts through the verifier channel --------------
        executor6 = verifier_adapter.WorktreeVerifierExecutor(
            vm, execution_mode="rollback_mirror")
        raw_tail = bytes([0xff, 0xfe, 0x00]) + b"TAIL-MARK"
        trace = executor6(
            "python",
            "import sys\n"
            "sys.stdout.buffer.write(bytes([0xff, 0xfe, 0x00]) "
            "+ b'TAIL-MARK')\n")
        # Stock contract (tests/test_guest_transport.py): the host decodes the
        # transport envelope; archived stdout keeps the exact bytes as base64
        # inside the NON-UTF8 block (with a matching bytes=/sha256= line),
        # while the model context receives only the externalization notice.
        lines = trace.stdout.splitlines()
        hidx = next((i for i, l in enumerate(lines)
                     if "EXACT BASE64" in l), -1)
        encoded = lines[hidx + 1] if hidx >= 0 else ""
        payload = (base64.b64decode(encoded) if encoded else b"")
        token_line, sep, tail = payload.partition(b"\n")
        context = getattr(trace, "context_stdout", None)
        check("transport: binary output archived exactly",
              trace.exit_code == 0
              and hidx >= 0
              and token_line.startswith(b"__RSIAGENT_VERIFIER_MIRROR_READY_")
              and token_line.endswith(b"__")
              and sep == b"\n"
              and tail == raw_tail
              and ("bytes=%d sha256=%s" % (len(payload),
                                            hashlib.sha256(payload).hexdigest())
                   ) in trace.stdout,
              f"hidx={hidx} payload={len(payload)}B "
              f"head={payload[:16]!r} tail={tail[:16]!r}")
        check("transport: binary externalized from model context",
              context is not None
              and encoded not in context
              and "PROGRAM OUTPUT EXTERNALIZED" in context
              and "__RSIAGENT_VERIFIER_MIRROR_READY_" not in context,
              repr(context)[:120])
        big_code = ("print('BIG-START')\n"
                    + "print('x' * 40000)\n"
                    + "print('BIG-END')\n")
        trace = executor6("python", big_code)
        check("transport: >32KiB program streamed losslessly",
              trace.exit_code == 0 and "BIG-END" in trace.stdout
              and len(trace.stdout) > 40000,
              f"exit={trace.exit_code} len={len(trace.stdout)}")
        executor6.close()
    finally:
        if sleeper_may_leak:
            _kill_sleeper_leak()
        env.close()
    check("env: close released drive and scratch",
          not Path(f"{env.drive_letter}:/").exists()
          and not env.scratch.exists())


def main() -> None:
    test_install_and_prompts()
    test_executor_lifecycle()
    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    failed = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    infos = sum(1 for s, _, _ in RESULTS if s == "INFO")
    print()
    print(f"smoke_verifier_adapter: {passed} PASS / {failed} FAIL / "
          f"{infos} INFO")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
