"""End-to-end smoke test for usine_hooks.py.

Three sections, all host-driven:

  A. corpus (pure host-side): build/extend/load, UsineAudit growth tolerance
     (one instance adopts sanctioned between-wave growth at the funnels and
     refuses shrink or rewrite), text/transcripts/captured/memory leakage
     audits (captured skips binary member content, names stay audited),
     hooks_for wiring keeps every other PracticeHooks seam stock
  B. publish boundary (stub VM, no guest): scan patterns hit only
     execution-shaped spellings (a path slash or an interleaved "verify" word
     stays clean), the refusal is a normal 126 trace that never reaches the
     wrapped VM, run_command stays unscanned by design, attribute proxy and
     the (desktop, vm) factory composition
  C. live WorktreeEnv: the guest-home USERPROFILE pin (expanduser lands on
     the sandbox disk in guest python), the platform-profile backstop
     (~/*_creator_profile does not resolve), and the boundary working through
     the real actor channel - clean programs run, publish programs are
     refused - for both a wrapped VM and the composed vm_factory

Usage (théâtre venv; keep child argv ASCII on PowerShell 5.1):
    cd D:\\coding\\personal\\explorateur\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_usine_hooks.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import tarfile
import tempfile
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

import guest_env  # noqa: E402
import usine_hooks  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    line = f"{status} {name}"
    if detail:
        line += f" | {detail}"
    print(line)


def check(name: str, ok, detail: str = "") -> None:
    record("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:400])


def info(name: str, detail: str) -> None:
    record("INFO", name, detail)


# ------------------------------------------------------------------ A: corpus

INSTRUCTION = ("Rewrite the scene parser so every lesson manifest "
               "validates offline before any rendering starts.")
OTHER_INSTRUCTION = ("Fix the karaoke subtitle drift so audio and text "
                     "stay in sync across the whole timeline.")


def test_corpus() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="usine-hooks-smoke-")
    root = pathlib.Path(tmp.name)
    try:
        corpus = root / "corpus.json"
        built = usine_hooks.build_corpus(corpus, [INSTRUCTION])
        grams = usine_hooks.load_corpus(corpus)
        check("corpus: build writes sorted shingles",
              built.get("benchmark") == "usine"
              and built.get("shingles") == len(grams) > 0
              and json.loads(corpus.read_text(encoding="utf-8"))
              == sorted(grams), built)

        try:
            usine_hooks.build_corpus(root / "empty.json", [""])
            check("corpus: build rejects an empty instruction set",
                  False, "no exception")
        except RuntimeError as exc:
            check("corpus: build rejects an empty instruction set",
                  "empty" in str(exc), exc)

        try:
            usine_hooks.UsineAudit(root / "missing.json")
            check("corpus: audit rejects a missing corpus", False, "no exception")
        except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
            check("corpus: audit rejects a missing corpus", True,
                  type(exc).__name__)

        grown = usine_hooks.extend_corpus(corpus, [OTHER_INSTRUCTION])
        merged = usine_hooks.load_corpus(corpus)
        check("corpus: extend is append-only growth",
              grown.get("added", 0) > 0
              and merged >= grams
              and len(merged) == len(grams) + grown.get("added", 0),
              grown)
        # The precise union check: rebuild both and compare exactly.
        from explore.commit import _shingles
        check("corpus: extend equals the exact shingle union",
              merged == _shingles(INSTRUCTION) | _shingles(OTHER_INSTRUCTION),
              f"{len(merged)} grams")
        noop = usine_hooks.extend_corpus(corpus, [INSTRUCTION])
        check("corpus: re-extending with known text adds nothing",
              noop.get("added") == 0 and noop.get("shingles") == len(merged),
              noop)

        audit = usine_hooks.UsineAudit(corpus)
        check("audit: validate accepts the pinned corpus",
              audit.validate(str(corpus))
              == {"benchmark": "usine", "shingles": len(merged)})
        try:
            audit.validate(str(root / "elsewhere.json"))
            check("audit: validate rejects a different path", False, "no exception")
        except RuntimeError:
            check("audit: validate rejects a different path", True)
        NOVEL = "add one completely novel wave project text right here"
        usine_hooks.extend_corpus(corpus, [NOVEL])
        grown = audit.validate(str(corpus))
        check("audit: the same instance accepts sanctioned growth",
              grown["shingles"] > len(merged), grown)

        corpus2 = root / "corpus2.json"
        usine_hooks.build_corpus(corpus2, [INSTRUCTION])
        lazy = usine_hooks.UsineAudit(corpus2)
        check("audit: a stale instance does not flag pre-growth text",
              lazy.text(NOVEL) == [])
        usine_hooks.extend_corpus(corpus2, [NOVEL])
        check("audit: text() refreshes to the grown corpus",
              lazy.text(NOVEL) != []
              and lazy.text(NOVEL)[0]["kind"] == "other-task-instruction",
              lazy.text(NOVEL))

        fresh = usine_hooks.UsineAudit(corpus)
        check("audit: a fresh audit accepts the between-waves growth",
              fresh.validate(str(corpus))["shingles"] > len(merged))

        check("audit: text flags instruction leakage",
              fresh.text(INSTRUCTION) != []
              and fresh.text(INSTRUCTION)[0]["kind"]
              == "other-task-instruction",
              fresh.text(INSTRUCTION))
        check("audit: short innocent text stays clean",
              fresh.text("tea and biscuits") == [])
        check("audit: authorized instruction is exempt",
              fresh.text(INSTRUCTION,
                         authorized_instruction=INSTRUCTION) == [])
        check("audit: other instruction still leaks when only one is authorized",
              fresh.text(OTHER_INSTRUCTION,
                         authorized_instruction=INSTRUCTION) != [])

        transcripts = root / "transcripts"
        (transcripts / "sub").mkdir(parents=True)
        (transcripts / "sub" / "transcript.json").write_text(
            json.dumps({"stdout": "note: " + INSTRUCTION}),
            encoding="utf-8")
        check("audit: transcripts walk transcript.json files",
              fresh.transcripts(str(transcripts),
                                authorized_instruction=INSTRUCTION) == []
              and fresh.transcripts(str(transcripts)) != [])

        captured = root / "capture"
        captured.mkdir()
        with tarfile.open(captured / "materials.tgz", "w:gz") as tf:
            clean = "innocent capture notes with no task text at all"
            data = clean.encode("utf-8")
            member = tarfile.TarInfo("notes.md")
            member.size = len(data)
            tf.addfile(member, __import__("io").BytesIO(data))
            leak = INSTRUCTION.encode("utf-8")
            member = tarfile.TarInfo("leak/task.md")
            member.size = len(leak)
            tf.addfile(member, __import__("io").BytesIO(leak))
        check("audit: captured reads materials.tgz members",
              fresh.captured(str(captured)) != []
              and fresh.captured(str(captured),
                                 authorized_instruction=INSTRUCTION) == [])

        bin_clean = root / "capture_bin"
        bin_clean.mkdir()
        with tarfile.open(bin_clean / "materials.tgz", "w:gz") as tf:
            blob = (b"\x00\x89\x50\x4e\x47\r\n\x1a\n"
                    + INSTRUCTION.encode("utf-8"))
            member = tarfile.TarInfo("assets/blob.bin")
            member.size = len(blob)
            tf.addfile(member, __import__("io").BytesIO(blob))
        check("audit: captured skips binary content with a clean name",
              fresh.captured(str(bin_clean)) == [])
        info("audit: the binary skip is cost-only",
             "the blob embeds the full instruction (a content audit would "
             "flag it); 32MB zip / 4.3MB mp4 baselines carry no 8-gram "
             "fence value")

        bin_named = root / "capture_bin_named"
        bin_named.mkdir()
        with tarfile.open(bin_named / "materials.tgz", "w:gz") as tf:
            payload = b"\x00" + INSTRUCTION.encode("utf-8")
            member = tarfile.TarInfo("leak/" + INSTRUCTION + ".bin")
            member.size = len(payload)
            tf.addfile(member, __import__("io").BytesIO(payload))
        named_findings = fresh.captured(str(bin_named))
        check("audit: captured still audits binary member names",
              len(named_findings) == 1
              and named_findings[0]["kind"] == "other-task-instruction",
              named_findings)

        # Excluded members never reach the audit face: node_modules and
        # dist are pruned at capture time (run_usine._CAPTURE_EXCLUDE_PARTS
        # flows into provisioning's exclude_parts), so uncontrolled
        # third-party tree content can neither trip nor bloat the leakage
        # audit.  The pair pins the whole contract: a pruned capture stays
        # clean, and a capture that regressed pruning trips LOUDLY instead
        # of silently widening the audited surface.
        pruned = root / "capture_pruned"
        pruned.mkdir()
        with tarfile.open(pruned / "materials.tgz", "w:gz") as tf:
            data = b"tracked source bytes that carry no task text at all"
            member = tarfile.TarInfo("packages/core/src/notes.ts")
            member.size = len(data)
            tf.addfile(member, __import__("io").BytesIO(data))
        check("audit: a pruned capture (no excluded members) stays clean",
              fresh.captured(str(pruned)) == [])
        info("audit: pruning is symmetric",
             "capture-side exclude_parts (node_modules, dist, build) and "
             "merge-side EXCLUDED_PARTS share one convention - what never "
             "enters the archive never enters the audit face or the merge")

        unpruned = root / "capture_unpruned"
        unpruned.mkdir()
        with tarfile.open(unpruned / "materials.tgz", "w:gz") as tf:
            leak = INSTRUCTION.encode("utf-8")
            member = tarfile.TarInfo("node_modules/dep-xyz/lib/vendor.js")
            member.size = len(leak)
            tf.addfile(member, __import__("io").BytesIO(leak))
        check("audit: a pruning regression trips the captured audit loudly",
              fresh.captured(str(unpruned)) != [])

        reject_log = root / "rejects.jsonl"
        files = {
            "clean.md": b"innocent memory bytes",
            "leak.md": INSTRUCTION.encode("utf-8"),
        }
        accepted = fresh.memory(files, str(corpus), str(reject_log),
                                authorized_instruction=OTHER_INSTRUCTION)
        logged = [json.loads(line)
                  for line in reject_log.read_text(
                      encoding="utf-8").splitlines()]
        check("audit: memory keeps clean files and rejects leakage",
              set(accepted) == {"clean.md"}
              and [entry["file"] for entry in logged] == ["leak.md"],
              f"accepted={sorted(accepted)} logged={logged}")

        hooks = usine_hooks.hooks_for(str(corpus))
        from explore.practice_loop import PracticeHooks
        baseline = PracticeHooks()
        check("hooks: PracticeHooks with usine seams wired",
              isinstance(hooks, PracticeHooks)
              and hooks.validate_corpus(str(corpus))
              == {"benchmark": "usine", "shingles": len(fresh.grams)}
              and hooks.audit_text is not None)
        check("hooks: every other seam stays stock",
              hooks.run_attempt is baseline.run_attempt
              and hooks.journal_memory is baseline.journal_memory
              and hooks.install_memory is baseline.install_memory
              and hooks.push_dir is baseline.push_dir)

        grown_grams = usine_hooks.load_corpus(corpus)
        corpus.write_text(json.dumps(sorted(grown_grams)[:10]),
                          encoding="utf-8")
        try:
            audit.validate(str(corpus))
            check("audit: the same instance refuses a shrunk corpus",
                  False, "no exception")
        except RuntimeError as exc:
            check("audit: the same instance refuses a shrunk corpus",
                  "drift" in str(exc), exc)
        corpus.write_text(
            json.dumps(["zz-tamper-%04d" % i
                        for i in range(len(grown_grams))]),
            encoding="utf-8")
        try:
            audit.text("anything at all")
            check("audit: the same instance refuses a rewritten corpus",
                  False, "no exception")
        except RuntimeError as exc:
            check("audit: the same instance refuses a rewritten corpus",
                  "drift" in str(exc), exc)
    finally:
        tmp.cleanup()


# -------------------------------------------------------- B: publish boundary


class _FakeVM:
    def __init__(self):
        self.calls = []

    def run_script(self, lang, code, *args, **kwargs):
        self.calls.append(("script", lang, code))
        from env.vm import Trace
        return Trace(stdout=f"ran {lang} program\n[exit 0]", exit_code=0)

    def run_command(self, command, timeout=30, cap=4000):
        self.calls.append(("command", command))
        return f"ran: {command}"

    @property
    def marker(self):
        return "proxied"


def test_publish_boundary() -> None:
    scan = usine_hooks.scan_publish_boundary
    check("scan: publish CLI invocation hits",
          scan("pnpm exec feuille publish xhs")
          == [("publish-cli", "feuille publish")])
    check("scan: publish login leaf hits",
          scan("feuille publish login") != [])
    check("scan: path spellings stay clean",
          scan("tar -cf out.tar packages/publish/src/xhs.ts") == []
          and scan("grep -rn feuille packages/publish/src") == [])
    check("scan: the offline gate stays clean",
          scan("pnpm verify") == []
          and scan("feuille verify") == [])
    check("scan: hand-rolled persistent-profile launch hits",
          scan("ctx = pw.chromium.launch_persistent_context("
               "user_data_dir=profile)") != [])
    hits = scan("feuille publish douyin")
    refusal = usine_hooks._publish_refusal(hits)
    check("refusal: names the boundary, the evidence, and the offline path",
          "[PUBLISH BOUNDARY" in refusal
          and "'feuille publish'" in refusal
          and "packages/publish/test/publish.test.ts" in refusal
          and "feuille[ ]publish" in refusal, refusal[:200])

    fake = _FakeVM()
    wrapped = usine_hooks.wrap_publish_blacklist(fake)
    trace = wrapped.run_script("bash", "pnpm verify")
    check("facade: clean programs pass through to the VM",
          trace.exit_code == 0 and "ran bash program" in trace.stdout
          and fake.calls[-1] == ("script", "bash", "pnpm verify"),
          trace.stdout)

    before = len(fake.calls)
    trace = wrapped.run_script("bash", "feuille publish xhs")
    check("facade: publish programs are refused before execution",
          trace.exit_code == usine_hooks.PUBLISH_BOUNDARY_EXIT_CODE == 126
          and trace.stdout.rstrip().endswith("[exit 126]")
          and "[PUBLISH BOUNDARY" in trace.stdout
          and trace.infra_fail is False
          and trace.context_stdout is None
          and len(fake.calls) == before,
          f"exit={trace.exit_code} out={trace.stdout[:160]!r}")

    out = wrapped.run_command("grep -rn 'feuille publish' src")
    check("facade: run_command stays unscanned by design",
          out == "ran: grep -rn 'feuille publish' src"
          and fake.calls[-1] == ("command",
                                 "grep -rn 'feuille publish' src"),
          out)
    info("facade: run_command is the harness-authored channel",
         "its commands legitimately carry project file names; documented "
         "in the module docstring")

    check("facade: attributes proxy to the wrapped VM",
          wrapped.marker == "proxied" and wrapped.run_script.__self__
          is wrapped)

    fake2 = _FakeVM()
    factory = usine_hooks.publish_blacklist_vm_factory(
        lambda: ("DESKTOP", fake2))
    desktop, vm = factory()
    check("factory: (desktop, vm) contract with only the VM wrapped",
          desktop == "DESKTOP"
          and isinstance(vm, usine_hooks.PublishBlacklistVM)
          and vm.run_script("bash", "printf ok").exit_code == 0
          and vm.run_script("bash", "feuille publish login").exit_code == 126)


# ------------------------------------------------------------- C: live guest


def test_live_guest() -> None:
    if sys.platform != "win32":
        # The WorktreeEnv substrate is the Windows wave host itself
        # (git-bash bash.exe + guest-home USERPROFILE pin); SKIP is not
        # PASS - this section runs only there and is honestly skipped
        # everywhere else.
        info("live guest section: wave host 待跑",
             "test_live_guest needs the Windows wave host (git-bash "
             "WorktreeEnv); run the full smoke there")
        return
    env = guest_env.WorktreeEnv()
    vm = guest_env.WorktreeVM(env)
    try:
        trace = vm.run_script(
            "py",
            "import os\n"
            "print('EXP=' + os.path.expanduser('~'))\n"
            "print('UP=' + os.environ.get('USERPROFILE', ''))\n")
        lines = {line.split("=", 1)[0]: line.split("=", 1)[1]
                 for line in trace.stdout.splitlines()
                 if "=" in line and line.split("=", 1)[0] in ("EXP", "UP")}
        check("pin: guest python expands ~ onto the sandbox disk",
              trace.exit_code == 0
              and lines.get("EXP") == "/home/user"
              and lines.get("UP") == "/home/user"
              and env.drive_letter not in trace.stdout
              and (os_environ_userprofile() or "").lower()
              != str(env.home_dir).lower(),
              f"exit={trace.exit_code} lines={lines} "
              f"host-home={os_environ_userprofile()!r}")

        trace = vm.run_script(
            "py",
            "import os, pathlib\n"
            "p = os.path.expanduser('~/.xhs_creator_profile')\n"
            "print('P=' + p)\n"
            "print('EXISTS=' + str(pathlib.Path(p).exists()))\n")
        body = dict(
            line.split("=", 1)
            for line in trace.stdout.splitlines()
            if line.startswith(("P=", "EXISTS=")))
        check("backstop: platform login profiles do not resolve",
              trace.exit_code == 0
              and body.get("P") == "/home/user/.xhs_creator_profile"
              and body.get("EXISTS") == "False"
              and env.drive_letter not in trace.stdout,
              f"exit={trace.exit_code} body={body}")

        wrapped = usine_hooks.wrap_publish_blacklist(vm)
        trace = wrapped.run_script("bash", "printf actor-ok; pwd")
        check("live: clean actor programs still run",
              trace.exit_code == 0 and "actor-ok" in trace.stdout,
              f"exit={trace.exit_code} out={trace.stdout[:200]!r}")
        trace = wrapped.run_script(
            "bash", "cd ~ && pnpm exec feuille publish xhs")
        check("live: publish programs are refused on the real channel",
              trace.exit_code == 126
              and "[PUBLISH BOUNDARY" in trace.stdout
              and trace.infra_fail is False,
              f"exit={trace.exit_code} out={trace.stdout[:160]!r}")
    finally:
        env.close()

    factory = usine_hooks.publish_blacklist_vm_factory(
        guest_env.worktree_vm_factory())
    desktop, vm = factory()
    try:
        check("live factory: desktop is a WorktreeEnv, VM is wrapped",
              isinstance(desktop, guest_env.WorktreeEnv)
              and isinstance(vm, usine_hooks.PublishBlacklistVM))
        trace = vm.run_script("bash", "printf factory-ok")
        check("live factory: clean programs run through the composition",
              trace.exit_code == 0 and "factory-ok" in trace.stdout,
              f"exit={trace.exit_code}")
        trace = vm.run_script("py", "import os\n"
                                  "print('HOME-PIN=' "
                                  "+ os.path.expanduser('~'))\n")
        check("live factory: the guest-home pin survives composition",
              trace.exit_code == 0
              and "HOME-PIN=/home/user" in trace.stdout
              and desktop.drive_letter not in trace.stdout,
              trace.stdout[:200])
        trace = vm.run_script("bash", "feuille publish bilibili")
        check("live factory: publish programs refused through the factory",
              trace.exit_code == 126
              and "[PUBLISH BOUNDARY" in trace.stdout)
    finally:
        desktop.close()


def os_environ_userprofile() -> str:
    import os
    return os.environ.get("USERPROFILE", "")


def main() -> int:
    test_corpus()
    test_publish_boundary()
    test_live_guest()
    passes = sum(1 for status, _, _ in RESULTS if status == "PASS")
    fails = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    infos = sum(1 for status, _, _ in RESULTS if status == "INFO")
    print(f"\nsmoke_usine_hooks: {passes} PASS / {fails} FAIL / {infos} INFO")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
