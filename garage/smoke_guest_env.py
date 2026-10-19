"""End-to-end smoke test for the guest_env.py worktree substrate.

Runs the REAL stock VM transport (env.vm.VM.run_command / run_script /
wait_for_controller / fetch_file / push_file) against a live WorktreeEnv and
asserts the seam properties the usine RSI adapter depends on:

  * guest illusion: canonical /home/user paths in harness commands; every
    agent-visible output restored to canonical spelling (no per-VM drive
    letters on Windows, no scratch paths on POSIX - including inside the
    base64 program-output envelope)
  * python3 shim, embedded paths (drive-relative spelling on Windows,
    ~ / $HOME on POSIX), UTF-8 round-trip
  * streamed (>32 KiB) program transport through /dev/shm
  * GNU timeout tree kills through the full server path
  * HTTP client-timeout marker + channel health afterwards
  * binary program output externalization (stock envelope contract)
  * fetch_file / push_file byte fidelity and stock failure contracts
  * the _reset_null_vm boundary: reset + scrubbed task attrs + RSI_CLEAN_RC
  * two concurrent guests with isolated disks (distinct subst drives on
    Windows, distinct scratch disks on POSIX), including the /tmp rewrite
    (on Windows the MSYS usertemp mount is sticky across concurrent
    guests; on POSIX a literal /tmp would hit the REAL host root - in both
    cases a literal /tmp in a command must land on each guest's own disk
    through the rewrite)
  * close(): subst drive released (Windows), scratch removed, idempotent

Usage (théâtre venv; keep child argv ASCII on PowerShell 5.1):
    cd <explorateur>\\théâtre
    Windows: .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_guest_env.py
    POSIX:   .venv/bin/python ../garage/smoke_guest_env.py
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]


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

import guest_env  # noqa: E402  (needs the théâtre root on sys.path first)

IS_WINDOWS = guest_env.IS_WINDOWS

RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    line = f"{status} {name}"
    if detail:
        line += f" | {detail}"
    print(line)


def check(name: str, ok: bool, detail: str = "") -> None:
    record("PASS" if ok else "FAIL", name, detail)


def info(name: str, detail: str) -> None:
    record("INFO", name, detail)


def leak_in(text: str, env) -> str:
    """Return a description of any per-VM leak found in text, else ''.

    Windows: the per-VM secret is the subst drive letter.  POSIX: it is
    the guest's scratch path (uuid-per-guest), which restore_text must
    never leave in agent-visible output.
    """
    low = str(text).lower()
    if IS_WINDOWS:
        d = env.drive_letter.lower()
        for marker in (f"{d}:", f"/{d}/"):
            if marker in low:
                return f"leaked {marker!r}"
        return ""
    scratch = str(env.scratch).lower()
    if scratch in low:
        return f"leaked scratch prefix {scratch!r}"
    return ""


def assert_clean(name: str, text: str, env, extra: str = "") -> None:
    leak = leak_in(text, env)
    check(name, not leak, (f"{leak} | text head={str(text)[:200]!r} {extra}").strip())


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    # POSIX prerequisite honesty: guest_env fails closed at WorktreeEnv
    # construction unless GNU coreutils resolve in the guest PATH
    # ("brew install coreutils"); SKIP is not PASS, so this smoke simply
    # runs its full battery on both substrates and lets construction fail
    # loudly where the dialect is missing.

    env1 = None
    env2 = None
    try:
        env1 = guest_env.WorktreeEnv()
        vm1 = guest_env.WorktreeVM(env1)
        d1 = env1.drive_letter
        disk1 = env1.disk_root

        # -- substrate ---------------------------------------------------
        if IS_WINDOWS:
            check("drive-allocated",
                  Path(f"{d1}:/").exists() and d1 not in "AB",
                  f"drive={d1}: scratch={env1.scratch}")
        else:
            check("scratch-allocated",
                  env1.p == env1.disk_root.as_posix()
                  and env1.p.startswith(str(env1.scratch))
                  and env1.drive_letter == "",
                  f"prefix={env1.p} scratch={env1.scratch}")
        check("guest-layout",
              env1.home_dir.is_dir() and env1.tmp_dir.is_dir()
              and env1.shm_dir.is_dir() and (env1.bin_dir / "python3").is_file(),
              f"home={env1.home_dir} tmp={env1.tmp_dir} shm={env1.shm_dir}")

        # -- the rm fallback must not be PATH-resolved ---------------------
        # rmtree_force's last resort is `rm -rf`, and its callers sometimes
        # depend on an immutable-flagged file SURVIVING so they can observe
        # the failure (the verifier rollback guard). A PATH-resolved `rm` may
        # be a wrapper that clears uchg without complaining, which silently
        # disarms the guard while every assertion still looks green.
        rm_path = guest_env.find_rm()
        check("rm-resolver-absolute-not-PATH",
              Path(rm_path).is_absolute()
              and Path(rm_path) != Path(shutil.which("rm") or ""),
              f"find_rm()={rm_path} (PATH rm={shutil.which('rm')})")

        # -- path mapping unit checks ------------------------------------
        try:
            ok_map = (
                env1.guest_to_host("/home/user/a/b.txt")
                == disk1 / "home" / "user" / "a" / "b.txt"
                and env1.guest_to_host("/tmp/x") == disk1 / "tmp" / "x"
                and env1.guest_to_host("/dev/shm/y") == disk1 / "dev" / "shm" / "y"
                and env1.guest_to_host(f"{env1.p}/home/user/z")
                == disk1 / "home" / "user" / "z"
                and env1.host_to_guest(disk1 / "home" / "user" / "a" / "b")
                == "/home/user/a/b"
                and env1.host_to_guest(disk1 / "tmp" / "x") == "/tmp/x"
                and env1.host_to_guest(disk1 / "dev" / "shm" / "q")
                == "/dev/shm/q")
            if IS_WINDOWS:
                ok_map = ok_map and (
                    env1.guest_to_host(f"{d1}:/home/user/w")
                    == disk1 / "home" / "user" / "w"
                    and env1.guest_to_host(f"{d1}:\\home\\user\\w")
                    == disk1 / "home" / "user" / "w")
            else:
                ok_map = ok_map and (
                    # the prefix form IS the absolute host path on POSIX
                    Path(env1.p + "/tmp/x") == disk1 / "tmp" / "x")
            try:
                env1.guest_to_host("/etc/passwd")
                outside_ok = False
            except ValueError:
                outside_ok = True
            check("path-mapping", ok_map and outside_ok,
                  f"ok_map={ok_map} outside_ok={outside_ok}")
        except Exception as exc:  # noqa: BLE001
            check("path-mapping", False, f"{type(exc).__name__}: {exc}")

        # -- stock command channel ---------------------------------------
        out = vm1.run_command("echo hello-worktree; uname -s")
        check("run-command", "hello-worktree" in out,
              f"out={out.strip()[:160]!r}")
        assert_clean("run-command-no-ansi-leak", out, env1)
        check("non-login-no-ansi", "\x1b" not in out, repr(out[:120]))

        out = vm1.run_command("echo $HOME")
        check("home-restored", out.strip() == "/home/user",
              f"$HOME echoed {out.strip()!r}")
        out = vm1.run_command("cd /home/user && pwd")
        check("canonical-path-command", out.strip().endswith("/home/user"),
              f"pwd={out.strip()!r}")
        out = vm1.run_command("test -d /home/user/bin && echo BIN_OK")
        check("rewrite-table", "BIN_OK" in out, repr(out.strip()))

        # -- python3 shim + embedded paths + envelope restore -----------
        # Windows: the canonical spelling inside program text resolves
        # drive-relative (lands on the guest disk).  POSIX: a literal
        # canonical path resolves against the REAL host root, so the
        # program uses ~ (HOME is pinned to the guest home on both).
        if IS_WINDOWS:
            py_prog = (
                "import os\n"
                "open('/home/user/py_out.txt', 'w').write('py-wrote\\n')\n"
                "print('cwd=' + os.getcwd())\n"
                "print('utf8-中文🎬')\n")
            embedded_name = "embedded-drive-relative"
        else:
            py_prog = (
                "import os\n"
                "open(os.path.expanduser('~/py_out.txt'), 'w')"
                ".write('py-wrote\\n')\n"
                "print('cwd=' + os.getcwd())\n"
                "print('utf8-中文🎬')\n")
            embedded_name = "embedded-home-relative"
        trace = vm1.run_script("py", py_prog)
        check("python3-shim-program",
              trace.exit_code == 0 and "utf8-中文🎬" in trace.stdout,
              f"exit={trace.exit_code} out={trace.stdout.strip()[:200]!r}")
        check(embedded_name,
              (disk1 / "home" / "user" / "py_out.txt").exists(),
              f"exit={trace.exit_code} err_head={trace.stdout[:160]!r}")
        check("envelope-restore-cwd",
              "cwd=/home/user" in trace.stdout and leak_in(trace.stdout, env1) == "",
              f"cwd line: {[l for l in trace.stdout.splitlines() if l.startswith('cwd=')]!r}")

        data, reason = vm1.fetch_file("/home/user/py_out.txt")
        if IS_WINDOWS:
            check("fetch-file", data in (b"py-wrote\n", b"py-wrote\r\n")
                  and not reason, f"data={data!r} reason={reason!r}")
            info("windows-python-crlf",
                 "guest python writes \\r\\n in text mode (Windows newline "
                 "translation; documented deviation - the stock Linux guest "
                 f"always writes \\n): {data!r}")
        else:
            check("fetch-file", data == b"py-wrote\n" and not reason,
                  f"data={data!r} reason={reason!r}")
        data, reason = vm1.fetch_file("/home/user/definitely_missing.bin")
        check("fetch-missing-fails", data is None and bool(reason),
              f"reason={reason!r}")
        (disk1 / "home" / "user" / "empty.txt").write_bytes(b"")
        data, reason = vm1.fetch_file("/home/user/empty.txt")
        check("fetch-empty-contract",
              data is None and "empty" in reason, f"reason={reason!r}")

        # -- bash programs: ~ works, literal /home/user documented deviation
        trace = vm1.run_script(
            "bash", "echo bash-prog-ok; ls ~ | tr '\\n' ' '")
        check("bash-program-tilde",
              trace.exit_code == 0 and "bash-prog-ok" in trace.stdout
              and "py_out.txt" in trace.stdout,
              f"exit={trace.exit_code} out={trace.stdout.strip()[:200]!r}")
        trace = vm1.run_script("bash", "ls /home/user 2>&1 | head -3")
        if IS_WINDOWS:
            info("bash-literal-home-user-deviation",
                 "literal /home/user inside bash programs resolves to the MSYS "
                 f"root, not the guest (charter steers to python3/~): {trace.stdout.strip()[:120]!r}")
        else:
            info("bash-literal-home-user-deviation",
                 "literal /home/user inside bash programs resolves against "
                 "the REAL host root (nonexistent here), not the guest "
                 "(charter steers to ~): "
                 f"{trace.stdout.strip()[:120]!r}")

        # -- binary output externalization (stock envelope contract) ------
        trace = vm1.run_script(
            "py",
            "import sys\n"
            "sys.stdout.buffer.write(bytes(range(256)) * 8)\n"
            "sys.stdout.flush()\n")
        check("binary-externalized",
              trace.exit_code == 0
              and "RSIAGENT NON-UTF8 PROGRAM OUTPUT" in trace.stdout
              and "PROGRAM OUTPUT EXTERNALIZED" in (trace.context_stdout or "")
              and "RSIAGENT_RUN_OUTPUT_BASE64:" not in trace.stdout,
              f"exit={trace.exit_code} archived_head={trace.stdout[:120]!r} "
              f"context_head={(trace.context_stdout or '')[:120]!r}")

        # -- streamed >32 KiB program through /dev/shm --------------------
        if IS_WINDOWS:
            big = ("# " + "A" * 40000 + "\n"
                   "open('/home/user/big.txt', 'w').write('big-wrote')\n"
                   "print('BIG_OK')\n")
        else:
            big = ("# " + "A" * 40000 + "\n"
                   "import os\n"
                   "open(os.path.expanduser('~/big.txt'), 'w')"
                   ".write('big-wrote')\n"
                   "print('BIG_OK')\n")
        trace = vm1.run_script("py", big, timeout=120)
        check("streamed-program",
              trace.exit_code == 0 and "BIG_OK" in trace.stdout
              and (disk1 / "home" / "user" / "big.txt").exists(),
              f"exit={trace.exit_code} out={trace.stdout.strip()[:160]!r}")
        check("streamed-no-shm-leftover",
              not any((disk1 / "dev" / "shm").iterdir()),
              f"shm contents={[p.name for p in (disk1 / 'dev' / 'shm').iterdir()]}")

        # -- GNU timeout tree kill through the server --------------------
        out = vm1.run_command(
            "timeout --signal=TERM --kill-after=1s 2 bash -c 'sleep 30; "
            f"echo done > {env1.p}/home/user/KILLED_MARKER'; echo rc=$?")
        check("gnu-timeout-tree-kill",
              "rc=124" in out and not (disk1 / "home" / "user" / "KILLED_MARKER").exists(),
              f"out={out.strip()[:120]!r}")

        # -- HTTP client timeout + channel health -------------------------
        started = time.monotonic()
        out = vm1.run_command("sleep 8", timeout=3)
        elapsed = time.monotonic() - started
        check("client-timeout-marker",
              out.startswith("[command timed out") and elapsed < 15,
              f"elapsed={elapsed:.1f}s out={out.strip()[:80]!r}")
        out = vm1.run_command("echo channel-back")
        check("channel-healthy-after-timeout", "channel-back" in out,
              repr(out.strip()))

        # -- push_file byte fidelity --------------------------------------
        payload = bytes(range(256)) * 512
        host_src = env1.scratch / "push_src.bin"
        host_src.write_bytes(payload)
        ok, reason = vm1.push_file(str(host_src), "/home/user/pushed.bin")
        data, fetch_reason = vm1.fetch_file("/home/user/pushed.bin")
        check("push-file-fidelity",
              ok and data == payload,
              f"ok={ok} reason={reason!r} fetched={len(data) if data else None}B")
        ok, reason = vm1.push_file(str(env1.scratch / "no_such_file.bin"), "/tmp/x")
        check("push-missing-fails", ok is False and "ordinary file" in reason,
              f"reason={reason!r}")

        # -- wait_for_controller ------------------------------------------
        recovered, report = vm1.wait_for_controller(
            timeout=30, probe_interval=1.0, stable_probes=2)
        check("wait-for-controller", recovered, report)

        # -- reset boundary (mirrors explore.practice_loop._reset_null_vm) -
        scrub = {
            "task_config": None, "instruction": None, "config": [],
            "user_simulator": None, "evaluator": None, "metric": None,
            "metric_conj": "and", "result_getter": None,
            "expected_getter": None, "metric_options": {}}
        env1.is_environment_used = True
        env1.reset(task_config=None)
        scrub_ok = True
        for name, value in scrub.items():
            try:
                setattr(env1, name, value)
            except Exception as exc:  # noqa: BLE001
                scrub_ok = False
                info("scrub-failure", f"{name}: {exc}")
                break
        out = vm1.run_command(
            "rm -rf /home/user/evolution_project /home/user/actor_handoff.md "
            "/home/user/.memory; echo RSI_CLEAN_RC=$?")
        check("reset-boundary",
              scrub_ok and "RSI_CLEAN_RC=0" in out
              and not (disk1 / "home" / "user" / "py_out.txt").exists()
              and not (disk1 / "home" / "user" / "pushed.bin").exists()
              and (disk1 / "home" / "user" / "bin" / "python3").is_file(),
              f"scrub_ok={scrub_ok} clean={out.strip()!r}")
        trace = vm1.run_script("py", "print('post-reset-python')")
        check("post-reset-python3",
              trace.exit_code == 0 and "post-reset-python" in trace.stdout,
              f"exit={trace.exit_code}")

        # -- concurrent guest isolation ------------------------------------
        env2 = guest_env.WorktreeEnv()
        vm2 = guest_env.WorktreeVM(env2)
        d2 = env2.drive_letter
        if IS_WINDOWS:
            check("second-drive-distinct",
                  d2 != d1 and Path(f"{d2}:/").exists(),
                  f"env1={d1}: env2={d2}:")
        else:
            check("second-scratch-distinct",
                  env2.scratch != env1.scratch
                  and env2.scratch.parent == env1.scratch.parent,
                  f"env1={env1.scratch} env2={env2.scratch}")
        out = vm2.run_command("echo two > /home/user/env2.txt; test -f /home/user/env2.txt && echo E2_OK")
        out1_view = vm1.run_command("test ! -e /home/user/env2.txt && echo ISOLATED")
        check("guest-disk-isolation",
              "E2_OK" in out and "ISOLATED" in out1_view,
              f"env2={out.strip()!r} env1_view={out1_view.strip()!r}")
        out = vm2.run_command("echo $HOME")
        check("env2-home-restored", out.strip() == "/home/user",
              f"$HOME={out.strip()!r}")

        # -- concurrent /tmp isolation (real-wave infra failure mode) -----
        # Windows: the MSYS usertemp /tmp mount is sticky across
        # concurrently spawned guests: a literal /tmp in a command string
        # MUST be rewritten into the per-guest drive form so each guest
        # reads and writes its own disk.  POSIX: a literal /tmp would hit
        # the REAL host root (shared by every process on the machine), so
        # the same rewrite is the only thing keeping guests contained.
        # Without the rewrite, vm2's write lands outside vm2's disk and
        # the isolation checks fail.
        out = vm2.run_command(
            "echo e2 > /tmp/e2_marker.txt; "
            "test -f /tmp/e2_marker.txt && echo E2_TMP_OK")
        e2_host = env2.disk_root / "tmp" / "e2_marker.txt"
        e1_cross = disk1 / "tmp" / "e2_marker.txt"
        out1_view = vm1.run_command(
            "test ! -e /tmp/e2_marker.txt && echo TMP_ISOLATED")
        if not IS_WINDOWS:
            # The rewrite must ALSO protect the real host /tmp: nothing may
            # ever be written to the machine's actual /tmp.
            check("host-tmp-untouched",
                  not Path("/tmp/e2_marker.txt").exists(),
                  f"/tmp/e2_marker.txt exists on the real host root: "
                  f"{Path('/tmp/e2_marker.txt').exists()}")
        check("concurrent-tmp-isolation",
              "E2_TMP_OK" in out and e2_host.exists()
              and not e1_cross.exists() and "TMP_ISOLATED" in out1_view,
              f"vm2={out.strip()!r} vm1_view={out1_view.strip()!r} "
              f"e2_host={e2_host.exists()} e1_cross={e1_cross.exists()}")

        # -- close lifecycle ------------------------------------------------
        vm1.client_password = env1.client_password  # insurance attr read paths
        env1.close()
        env1.close()  # idempotent
        env2.close()
        if IS_WINDOWS:
            check("drives-released",
                  not Path(f"{d1}:/").exists() and not Path(f"{d2}:/").exists(),
                  f"{d1}: exists={Path(f'{d1}:/').exists()} "
                  f"{d2}: exists={Path(f'{d2}:/').exists()}")
        check("scratch-removed",
              not env1.scratch.exists() and not env2.scratch.exists(),
              f"{env1.scratch} gone={not env1.scratch.exists()}; "
              f"{env2.scratch} gone={not env2.scratch.exists()}")
        env1 = None
        env2 = None
    finally:
        for env in (env1, env2, None):
            if env is None:
                continue
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass
        guest_env.close_all_live()

    print("-" * 72)
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    passes = [r for r in RESULTS if r[0] == "PASS"]
    infos = [r for r in RESULTS if r[0] == "INFO"]
    print(f"SUMMARY: {len(passes)} passed, {len(fails)} failed, {len(infos)} info")
    for status, name, detail in fails:
        print(f"  FAILED: {name} | {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
