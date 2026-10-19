"""Capability probe for the Windows git-bash guest substrate used by the usine RSI adapter.

Verifies, end to end, the environment assumptions `guest_env.py` depends on:

  * subst drive letter maps the guest root; `/z/...` cygdrive prefix works
  * MSYS `/tmp` follows the Windows TEMP overlay for a lone guest, but the
    usertemp mount is STICKY across concurrent guests - which is why
    guest_env.py rewrites `/tmp` into the drive form instead of trusting it
  * MSYS argv path conversion for native exes (`/z/...`, `/tmp/...`, `/dev/null`)
  * drive-relative embedded paths resolve inside the guest drive
  * login shell puts GNU coreutils (/usr/bin) ahead of Windows PATH junk
    (D:\\FPC rm/find/timeout/stat and System32 tar/find/timeout shadow them otherwise)
  * PATH overlay lets a guest `python3` shim beat the WindowsApps alias
  * `timeout --signal=TERM --kill-after` kills child trees
  * `rm -rf` removes read-only git objects (or the chmod fallback)
  * `ln -s` behavior, UTF-8 round-trips, stdout/stderr split, exit-code fidelity
  * HOME handling for `~` expansion

Usage (host):
    python garage/probe_env.py

Exits 0 when every PASS/FAIL probe passes; INFO findings never fail the run.
Cleans up its subst drive and scratch directory on exit.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import string
import subprocess
import sys
import time
import uuid
from pathlib import Path

BASH_CANDIDATES = [
    r"d:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
]

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


def find_bash() -> str:
    for cand in BASH_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise SystemExit("git-bash bash.exe not found in known locations")


def find_free_drive() -> str:
    for letter in reversed(string.ascii_uppercase):
        if not Path(f"{letter}:/").exists():
            return letter
    raise SystemExit("no free drive letter available for subst")


class GuestBash:
    """Runs commands inside the guest exactly the way guest_env.py will.

    * NON-login shell (``bash --noprofile --norc -c``): login shells source
      /etc/profile (env churn) and -- critically -- /etc/bash.bash_logout
      emits clear-screen ANSI escapes into stdout on exit, polluting every
      /execute response.  Startup-file-less non-login bash avoids both.
    * PATH overlay (Windows form, prepended): git ``usr\\bin`` + ``mingw64\\bin``
      put GNU coreutils ahead of the Windows PATH shadow binaries (FPC rm/find/
      timeout/stat, System32 tar/find/timeout); guest ``bin`` dir puts the
      python3 shim ahead of the WindowsApps alias.
    * ``p`` is the in-guest POSIX drive prefix (e.g. "/z").
    """

    def __init__(self, bash: str, drive: str, login: bool = False):
        self.bash = bash
        self.login = login
        self.drive_letter = drive
        self.p = "/" + drive.lower()
        self.guest_root = Path(drive + ":/")
        self.tmp = f"{drive}:\\tmp"
        self.home = f"{drive}:\\home\\user"
        self.bin = f"{drive}:\\home\\user\\bin"
        git_root = Path(bash).parents[2]  # ...\Git\usr\bin\bash.exe -> ...\Git
        env = dict(os.environ)
        env.update(
            {
                "TMP": self.tmp,
                "TEMP": self.tmp,
                "HOME": self.home,
                "PYTHONUTF8": "1",
                "RSI_PROBE_ENV": "xyz-probe",
                "PATH": os.pathsep.join(
                    [
                        str(git_root / "usr" / "bin"),
                        str(git_root / "mingw64" / "bin"),
                        self.bin,
                        env.get("PATH", ""),
                    ]
                ),
            }
        )
        self.env = env
        self.cwd = self.home

    def run(self, cmd: str, login: bool | None = None, timeout: int = 60):
        use_login = self.login if login is None else login
        args = [self.bash, "--noprofile", "--norc"]
        if use_login:
            args.append("-l")
        args += ["-c", cmd]
        p = subprocess.run(
            args, env=self.env, cwd=self.cwd, capture_output=True, timeout=timeout
        )
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        return p.returncode, out, err


def py_posix() -> str:
    return Path(sys.executable).as_posix()


def norm(p: str) -> str:
    return p.replace("/", "\\").lower().rstrip("\\")


def probe_sanity(gb: GuestBash) -> None:
    rc, out, err = gb.run("echo bash-ok; uname -s; echo MSYSTEM=$MSYSTEM")
    check("bash-sanity", rc == 0 and "bash-ok" in out, f"rc={rc} out={out.strip()!r} err={err.strip()!r}")
    rc, out, _ = gb.run("echo $RSI_PROBE_ENV")
    check("env-overlay", rc == 0 and out.strip() == "xyz-probe", f"got {out.strip()!r}")
    rc, out, err = gb.run("echo CLEAN-MARKER; exit 0")
    check(
        "no-ansi-pollution",
        rc == 0 and "CLEAN-MARKER" in out and "\x1b" not in out,
        f"non-login shell stdout polluted: {out!r}",
    )
    rc, out, err = gb.run("echo LOGIN-MARKER; exit 0", login=True)
    info(
        "login-shell-pollutes",
        f"login shell stdout: {out!r} (this is why guest_env uses non-login shells)",
    )


def probe_tool_resolution(gb: GuestBash) -> None:
    tools = ["rm", "find", "stat", "timeout", "tar", "base64", "sha256sum", "cmp", "cp", "mkdir", "chmod", "diff"]
    rc, out, err = gb.run("for t in " + " ".join(tools) + "; do echo $t=$(command -v $t); done")
    lines = dict(ln.split("=", 1) for ln in out.strip().splitlines() if "=" in ln)
    bad = {k: v for k, v in lines.items() if not v.startswith("/usr/bin/")}
    check(
        "gnu-tools-first",
        rc == 0 and not bad,
        f"non-/usr/bin resolutions: {bad}; err={err.strip()[:200]!r}",
    )
    info("tool-versions", gb.run("tar --version | head -1")[1].strip()[:80])
    rc, out, _ = gb.run("echo $PATH | tr ':' '\\n' | head -6")
    info("path-head", " | ".join(out.strip().splitlines()))


def probe_cygdrive(gb: GuestBash) -> None:
    rc, out, err = gb.run(
        f"test -d {gb.p}/home/user && test -d {gb.p}/tmp && test -d {gb.p}/dev/shm && echo cygdrive-ok"
    )
    check("cygdrive-guest-dirs", rc == 0 and "cygdrive-ok" in out, err.strip())
    rc, out, _ = gb.run(f"cygpath -w {gb.p}/home/user")
    want = str(gb.guest_root / "home" / "user")
    check("cygpath-drive", rc == 0 and norm(out.strip()) == norm(want), f"cygpath said {out.strip()!r} want {want!r}")
    rc, out, _ = gb.run(f"cd {gb.p}/home/user && pwd")
    check("pwd-on-drive", rc == 0 and out.strip().endswith("/home/user"), f"pwd={out.strip()!r}")


def probe_home(gb: GuestBash) -> None:
    rc, out, _ = gb.run('echo "HOME=$HOME"; cd ~ && echo "TILDE=$(pwd)"')
    home_posix = f"{gb.p}/home/user"
    ok = rc == 0 and home_posix in out and f"TILDE={home_posix}" in out
    check("home-and-tilde", ok, f"HOME line: {out.strip()!r}")
    rc, out, _ = gb.run(f'test -d "$HOME/.memory" -o ! -e "$HOME/.memory" && echo home-tilde-mkdir-ok')
    check("home-tilde-compose", rc == 0, out.strip())


def probe_msys_tmp(gb: GuestBash) -> None:
    """INFO-grade: with a lone guest, MSYS still mounts ``/tmp`` at this
    guest's TEMP overlay - but the usertemp mount is sticky, so under
    concurrent guests every bash resolves literal ``/tmp`` through ONE
    guest's TEMP (cross-verified in a real wave).  guest_env.py therefore
    rewrites ``/tmp`` into the per-guest drive form instead of trusting the
    mount; the concurrent isolation regression lives in
    ``smoke_guest_env.py`` (``concurrent-tmp-isolation``)."""
    rc, out, err = gb.run("cygpath -w /tmp && echo probe > /tmp/msys_tmp_probe.txt && cat /tmp/msys_tmp_probe.txt")
    want = str(gb.guest_root / "tmp")
    host_file = gb.guest_root / "tmp" / "msys_tmp_probe.txt"
    info(
        "msys-tmp-follows-temp-lone-guest",
        f"cygpath -w /tmp -> {out.splitlines()[0] if out else ''!r} "
        f"(want {want!r}); host file exists={host_file.exists()}; "
        f"STICKY under concurrent guests - guest_env rewrites /tmp",
    )


def probe_native_argv(gb: GuestBash) -> None:
    rc, out, err = gb.run(
        f'{py_posix()} -c "import sys,json; print(json.dumps(sys.argv[1:]))" '
        f"{gb.p}/home/user/work /tmp/native_conv_probe.txt /dev/null"
    )
    try:
        import json

        argv = json.loads(out.strip())
    except Exception:
        check("native-argv-conversion", False, f"unparsable output {out.strip()[:200]!r} err={err.strip()[:200]!r}")
        return
    want_home = str(gb.guest_root / "home" / "user" / "work")
    want_tmp = str(gb.guest_root / "tmp" / "native_conv_probe.txt")
    ok_home = bool(argv) and norm(argv[0]) == norm(want_home)
    ok_tmp = len(argv) > 1 and norm(argv[1]) == norm(want_tmp)
    check("native-argv-drive-path", ok_home, f"argv[0]={argv[0] if argv else None!r} want {want_home!r}")
    check("native-argv-tmp-path", ok_tmp, f"argv[1]={argv[1] if len(argv) > 1 else None!r} want {want_tmp!r}")
    info("native-argv-devnull", f"/dev/null converted to {argv[2] if len(argv) > 2 else None!r}")


def probe_embedded_paths(gb: GuestBash) -> None:
    rc, out, err = gb.run(
        f'{py_posix()} -c "'
        "import os;"
        "open('/tmp/dr1.txt','w').write('1');"
        "open('/home/user/dr2.txt','w').write('2');"
        "open('/dev/shm/dr3.txt','w').write('3');"
        'print(os.getcwd())"'
    )
    f1 = gb.guest_root / "tmp" / "dr1.txt"
    f2 = gb.guest_root / "home" / "user" / "dr2.txt"
    f3 = gb.guest_root / "dev" / "shm" / "dr3.txt"
    ok = rc == 0 and f1.exists() and f2.exists() and f3.exists()
    check(
        "embedded-drive-relative-paths",
        ok,
        f"rc={rc} cwd={out.strip()!r} tmp={f1.exists()} home={f2.exists()} shm={f3.exists()} err={err.strip()[:200]!r}",
    )


def probe_python3_shim(gb: GuestBash) -> None:
    shim = gb.guest_root / "home" / "user" / "bin" / "python3"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(
        "#!/bin/sh\n"
        "exec " + py_posix() + ' -X utf8 "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    rc, out, err = gb.run("command -v python3")
    resolved = out.strip()
    want = f"{gb.p}/home/user/bin/python3"
    check("python3-shim-resolves", rc == 0 and norm(resolved) == norm(want), f"resolved {resolved!r} want {want!r}")
    rc, out, err = gb.run("python3 -c 'import sys; print(sys.version.split()[0]); print(sys.argv[1])' shimarg")
    ok = rc == 0 and "shimarg" in out
    check("python3-shim-runs", ok, f"rc={rc} out={out.strip()!r} err={err.strip()[:200]!r}")
    rc, out, _ = gb.run("command -v uv || echo NO_UV")
    info("uv-visible", f"uv resolution: {out.strip()!r}")
    # TS-tree gate prerequisite (usine is a pnpm monorepo since P0-P8):
    # the offline gate "pnpm verify" needs Node 24+ and pnpm 11 in PATH.
    rc, out, _ = gb.run("node --version 2>/dev/null || echo NO_NODE")
    info("node-visible", f"node resolution: {out.strip()!r}")
    rc, out, _ = gb.run("command -v pnpm 2>/dev/null && pnpm --version || echo NO_PNPM")
    info("pnpm-visible", f"pnpm resolution: {out.strip()!r}")


def probe_timeout_kill(gb: GuestBash) -> None:
    marker = f"{gb.p}/home/user/work/DONE_MARKER"
    start = time.time()
    rc, out, err = gb.run(
        f"timeout --signal=TERM --kill-after=1s 2 bash -c 'sleep 30; echo done > {marker}' ; echo rc=$?"
    )
    elapsed = time.time() - start
    marker_exists = (gb.guest_root / "home" / "user" / "work" / "DONE_MARKER").exists()
    check(
        "timeout-kills-children",
        rc == 0 and "rc=124" in out and elapsed < 15 and not marker_exists,
        f"rc={rc} out={out.strip()!r} elapsed={elapsed:.1f}s marker={marker_exists} err={err.strip()[:150]!r}",
    )
    start = time.time()
    rc, out, err = gb.run(
        f"timeout --signal=TERM --kill-after=1s 2 bash -c '{py_posix()} -c \"import time; time.sleep(30)\"'; echo rc=$?"
    )
    elapsed = time.time() - start
    check(
        "timeout-kills-native-child",
        "rc=124" in out and elapsed < 15,
        f"rc={rc} elapsed={elapsed:.1f}s out={out.strip()[:80]!r} err={err.strip()[:150]!r}",
    )


def probe_rm_readonly_git(gb: GuestBash) -> None:
    repo = gb.guest_root / "home" / "user" / "gitprobe"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "file.txt").write_text("probe content\n", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(gb.guest_root / "tmp" / "probe-gitconfig")
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=probe", "-c", "user.email=probe@example.com", "commit", "-qm", "probe"],
        cwd=repo, env=env, check=True, capture_output=True,
    )
    objs = list((repo / ".git" / "objects").rglob("*"))
    readonly = [o for o in objs if o.is_file() and not os.access(o, os.W_OK)]
    rc, out, err = gb.run(
        f"git -C {gb.p}/home/user/gitprobe status --porcelain; git -C {gb.p}/home/user/gitprobe log --oneline"
    )
    check("git-works-on-subst", rc == 0 and "probe" in out, f"rc={rc} err={err.strip()[:200]!r}")
    rc, out, err = gb.run(f"rm -rf {gb.p}/home/user/gitprobe; echo rc=$?")
    gone = not repo.exists()
    check(
        "rm-rf-readonly-git-objects",
        rc == 0 and "rc=0" in out and gone and bool(readonly),
        f"rc={rc} out={out.strip()[:100]!r} gone={gone} readonly_objects={len(readonly)} err={err.strip()[:250]!r}",
    )
    if not gone:
        rc, out, _ = gb.run(f"chmod -R u+w {gb.p}/home/user/gitprobe && rm -rf {gb.p}/home/user/gitprobe; echo rc=$?")
        check("rm-rf-chmod-fallback", "rc=0" in out and not repo.exists(), out.strip()[:150])


def probe_ln_s(gb: GuestBash) -> None:
    rc, out, err = gb.run(
        f"cd {gb.p}/home/user/work && echo data > linksrc.txt && ln -s linksrc.txt linkdst.link && ls -l linkdst.link && cat linkdst.link; "
        f"rc=$?; rm -f linksrc.txt linkdst.link; exit $rc"
    )
    if rc != 0:
        info("ln-s-behavior", f"ln -s FAILED rc={rc} err={err.strip()[:200]!r}")
        return
    if "->" in out:
        info("ln-s-behavior", "real symlink created")
    elif "data" in out:
        info("ln-s-behavior", "ln -s created a COPY (git-bash default); capture/replay must tolerate it")


def probe_tar_roundtrip(gb: GuestBash) -> None:
    src = gb.guest_root / "home" / "user" / "rt_src"
    nested = src / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (src / "a.txt").write_bytes(b"alpha\n")
    (src / "数据 电影.md").write_bytes("中文内容🎬\n".encode("utf-8"))
    blob = bytes(range(256)) * 64
    (nested / "x.bin").write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    rc, out, err = gb.run(
        f"tar czf {gb.p}/tmp/rt.tgz -C {gb.p}/home/user rt_src && "
        f"rm -rf {gb.p}/home/user/rt_out && mkdir -p {gb.p}/home/user/rt_out && "
        f"tar xzf {gb.p}/tmp/rt.tgz -C {gb.p}/home/user/rt_out && "
        f"sha256sum {gb.p}/home/user/rt_out/rt_src/nested/x.bin && "
        f"find {gb.p}/home/user/rt_out -type f | sort"
    )
    lines = out.splitlines()
    sha_ok = any(ln.startswith(sha) for ln in lines)
    names = sorted(ln.rsplit("/", 2)[-1] for ln in lines if ln.startswith("/"))
    want_names = ["a.txt", "x.bin", "数据 电影.md"]
    check(
        "tar-roundtrip",
        rc == 0 and sha_ok and names == want_names,
        f"rc={rc} sha_ok={sha_ok} names={names} err={err.strip()[:200]!r}",
    )
    rc, out, _ = gb.run(
        f"cp -a {gb.p}/home/user/rt_src {gb.p}/home/user/rt_copy && "
        f"cmp {gb.p}/home/user/rt_src/nested/x.bin {gb.p}/home/user/rt_copy/nested/x.bin && "
        f"cmp '{gb.p}/home/user/rt_src/数据 电影.md' '{gb.p}/home/user/rt_copy/数据 电影.md' && echo cp-ok"
    )
    check("cp-a-roundtrip", rc == 0 and "cp-ok" in out, f"rc={rc}")
    rc, out, _ = gb.run(f"stat -c %s {gb.p}/home/user/rt_src/a.txt")
    check("stat-size", rc == 0 and out.strip() == "6", f"stat said {out.strip()!r}")


def probe_b64_roundtrip(gb: GuestBash) -> None:
    payload = bytes(range(256)) + "中文🎬'quote\"dquote".encode("utf-8")
    src = gb.guest_root / "home" / "user" / "work" / "b64src.bin"
    src.write_bytes(payload)
    rc, out, err = gb.run(
        f"base64 -w0 {gb.p}/home/user/work/b64src.bin > {gb.p}/home/user/work/b64.b64 && "
        f"base64 -d {gb.p}/home/user/work/b64.b64 > {gb.p}/home/user/work/b64out.bin && "
        f"cmp {gb.p}/home/user/work/b64src.bin {gb.p}/home/user/work/b64out.bin && echo b64-ok"
    )
    check("base64-roundtrip", rc == 0 and "b64-ok" in out, f"rc={rc} err={err.strip()[:200]!r}")


def probe_utf8_stdout(gb: GuestBash) -> None:
    rc, out, err = gb.run(f'{py_posix()} -c "print(\'中文测试🎬\')"')
    check("utf8-stdout", rc == 0 and "中文测试🎬" in out, f"out={out.strip()!r} err={err.strip()[:120]!r}")


def probe_exit_stderr(gb: GuestBash) -> None:
    rc, out, err = gb.run("echo OUT; echo ERR >&2; exit 7")
    check(
        "exit-stderr-split",
        rc == 7 and "OUT" in out and "ERR" not in out and "ERR" in err,
        f"rc={rc} out={out.strip()!r} err={err.strip()!r}",
    )


def probe_case_sensitivity(gb: GuestBash) -> None:
    work = gb.guest_root / "home" / "user" / "work"
    (work / "Case.txt").write_text("x", encoding="utf-8")
    rc, out, _ = gb.run(f"test -f {gb.p}/home/user/work/CASE.TXT && echo same-file")
    info(
        "fs-case-insensitive",
        f"case-insensitive lookup: {out.strip()!r} (POSIX fidelity deviation; document in ADAPTATION.md)",
    )


def probe_cygpath_map(gb: GuestBash) -> None:
    rc, out, _ = gb.run(
        "cygpath -w / ; cygpath -w /home/user ; mount | head -6"
    )
    info("msys-path-map", " | ".join(out.strip().splitlines())[:400])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    bash = find_bash()
    drive = find_free_drive()
    scratch = Path(os.environ.get("TMP", ".")) / f"rsi-probe-{uuid.uuid4().hex[:8]}"
    guest_disk_root = scratch / "guest"
    for sub in ("home/user", "home/user/work", "home/user/bin", "tmp", "dev/shm"):
        (guest_disk_root / sub).mkdir(parents=True, exist_ok=True)

    print(f"bash={bash}")
    print(f"drive={drive}: -> {guest_disk_root}")
    print(f"host_python={sys.executable}")
    print(f"scratch={scratch}")
    print("-" * 72)

    rc_subst = subprocess.run(["subst", f"{drive}:", str(guest_disk_root)], capture_output=True)
    if rc_subst.returncode != 0:
        print("subst failed:", rc_subst.stdout, rc_subst.stderr)
        return 2
    try:
        gb = GuestBash(bash=bash, drive=drive)
        probe_sanity(gb)
        probe_tool_resolution(gb)
        probe_cygdrive(gb)
        probe_home(gb)
        probe_msys_tmp(gb)
        probe_native_argv(gb)
        probe_embedded_paths(gb)
        probe_python3_shim(gb)
        probe_timeout_kill(gb)
        probe_rm_readonly_git(gb)
        probe_ln_s(gb)
        probe_tar_roundtrip(gb)
        probe_b64_roundtrip(gb)
        probe_utf8_stdout(gb)
        probe_exit_stderr(gb)
        probe_case_sensitivity(gb)
        probe_cygpath_map(gb)
    finally:
        for _ in range(3):
            r = subprocess.run(["subst", f"{drive}:", "/D"], capture_output=True)
            if r.returncode == 0:
                break
            time.sleep(1)
        shutil.rmtree(scratch, ignore_errors=True)
        if scratch.exists():
            print(f"WARN could not fully remove scratch: {scratch}")

    print("-" * 72)
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    infos = [r for r in RESULTS if r[0] == "INFO"]
    passes = [r for r in RESULTS if r[0] == "PASS"]
    print(f"SUMMARY: {len(passes)} passed, {len(fails)} failed, {len(infos)} info")
    for status, name, detail in fails:
        print(f"  FAILED: {name} | {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
