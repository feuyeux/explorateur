"""End-to-end smoke test for wave_merge.py.

Three sections, all host-driven:

  A. archive parsing and pure delta logic: inventory with prefix stripping,
     exclusions, sidecar/roots/special-member fail-closed paths, candidate
     delta, symlink changes, tri-state classification
  B. merge_wave against real throwaway git repositories shaped like the
     explorateur topology (repo root + usine/ subtree): green merge with
     subject/trailers/tag, byte-exact rollback on gate red, not_pass,
     drift, already-merged idempotency, serial candidates, overlap
     conflicts, mixed pre-applied, merged_noop, path policy (gitignored /
     Windows-reserved / trailing-dot), gate side effects, missing gate,
     re-merge no-op, preconditions, missing archives, baseline preference
  C. event sink forwarding order (merge after the event reached the inner
     sink) and merge_pending_waves catch-up (confirmed waves only)

Usage (théâtre venv; keep child argv ASCII on PowerShell 5.1):
    cd D:\\coding\\personal\\explorateur\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_wave_merge.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import subprocess
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

import wave_merge  # noqa: E402
from explore.provisioning import _symlink_digest  # noqa: E402

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


def expect_raise(name: str, callable_, *args, **kwargs) -> None:
    try:
        callable_(*args, **kwargs)
    except wave_merge.UsineMergeError as exc:
        check(name, True, str(exc)[:120])
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"wrong exception {type(exc).__name__}: {exc}")
    else:
        check(name, False, "no exception")


# --------------------------------------------------------------- materials I/O

PREFIX = "evolution_project/"


def write_materials(directory: pathlib.Path, files: dict, links=None,
                    modes=None) -> pathlib.Path:
    """Build a materials archive + sidecars byte-compatible with capture.

    ``modes`` maps rel -> tar member mode for entries that must carry the
    executable bit (the default 0644 matches a plain write)."""
    directory.mkdir(parents=True, exist_ok=True)
    links = links or {}
    modes = modes or {}
    manifest: dict[str, str] = {}
    link_map: dict[str, str] = {}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel in sorted(files):
            data = files[rel]
            info_ = tarfile.TarInfo(PREFIX + rel)
            info_.size = len(data)
            info_.mtime = 1700000000
            info_.mode = modes.get(rel, 0o644)
            tf.addfile(info_, io.BytesIO(data))
            manifest[PREFIX + rel] = hashlib.sha256(data).hexdigest()
        for rel in sorted(links):
            info_ = tarfile.TarInfo(PREFIX + rel)
            info_.type = tarfile.SYMTYPE
            info_.linkname = links[rel]
            info_.mtime = 1700000000
            tf.addfile(info_)
            manifest[PREFIX + rel] = _symlink_digest(links[rel])
            link_map[PREFIX + rel] = links[rel]
    (directory / "materials.tgz").write_bytes(buf.getvalue())
    with open(directory / "materials.MANIFEST.sha256", "w",
              encoding="utf-8") as handle:
        handle.write("# project: smoke dirs: evolution_project captured: smoke\n")
        for name in sorted(manifest):
            handle.write(f"{manifest[name]}  {name}\n")
    (directory / "materials.ROOTS.json").write_text(
        json.dumps({"schema_version": 1, "roots": ["evolution_project"]},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (directory / "materials.SYMLINKS.json").write_text(
        json.dumps({"schema_version": 1, "links": dict(sorted(link_map.items()))},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return directory


GATE_SOURCE = """\
import os
import sys


def _p(name):
    return os.path.join(os.getcwd(), name)


# newline="\\n" keeps the stub's writes byte-stable on Windows (a text-mode
# write would translate \\n to \\r\\n and the merge would treat the CRLF as a
# real candidate change).
def _write(name, text):
    with open(_p(name), "w", encoding="utf-8", newline="\\n") as handle:
        handle.write(text)


with open(_p("gate-ran-marker"), "a", encoding="utf-8", newline="\\n") as handle:
    handle.write("ran\\n")
if os.path.exists(_p("gate-side-effect")):
    _write("src/innocent.txt", "gate was here\\n")
if os.path.exists(_p("gate-revert")):
    _write("src/a.txt", "BASE-A\\n")
if os.path.exists(_p("gate-fail")):
    sys.exit(1)
sys.exit(0)
"""

BASE_FILES = {"src/a.txt": b"BASE-A\n", "src/b.txt": b"BASE-B\n",
              "docs/readme.md": b"README\n"}


def make_repo(base: pathlib.Path, files=None) -> pathlib.Path:
    """A throwaway git repo with the usine project as a tracked subtree.

    The repository root is ``base/repo`` and the project files live under
    ``base/repo/usine`` — the explorateur topology (usine is a subtree of a
    larger repository), so the prefix-aware git paths stay covered.
    """
    files = dict(files or BASE_FILES)
    repo = base / "repo"
    usine = repo / "usine"
    usine.mkdir(parents=True)
    for rel, data in files.items():
        target = usine.joinpath(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (usine / "gate.py").write_text(GATE_SOURCE, encoding="utf-8")

    def git(*args):
        proc = subprocess.run(["git", *args], cwd=str(repo),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"git {args} failed: "
                               f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
        return proc.stdout.decode("utf-8", "replace")

    git("init", "-q")
    git("config", "core.autocrlf", "false")
    git("add", "-A")
    git("-c", "user.name=smoke", "-c", "user.email=smoke@local",
        "commit", "-q", "-m", "base")
    return usine


from pathlib import PurePosixPath  # noqa: E402


def make_episode(lineage: pathlib.Path, name: str, wave: int,
                 project_index: int, project_id: str, outcome: str,
                 fixture_files: dict, candidate_files=None,
                 candidate_links=None, candidate_modes=None) -> pathlib.Path:
    episode = lineage / "episodes" / name
    write_materials(episode / "fixtures", fixture_files)
    if candidate_files is not None or candidate_links is not None:
        write_materials(
            episode / "candidates" / "cycle_001",
            fixture_files if candidate_files is None else candidate_files,
            candidate_links or {}, candidate_modes)
    (episode / "outcome.json").write_text(json.dumps({
        "schema_version": 2, "wave_index": wave,
        "project_index": project_index, "project_id": project_id,
        "project": "smoke instruction text",
        "terminal_outcome": outcome}), encoding="utf-8")
    return episode


def config_for(usine: pathlib.Path, gate_argv=None) -> wave_merge.UsineMergeConfig:
    return wave_merge.UsineMergeConfig(
        usine_dir=str(usine),
        gate_argv=tuple(gate_argv) if gate_argv else (sys.executable, "gate.py"))


def git_read(usine: pathlib.Path, *args) -> str:
    proc = subprocess.run(["git", *args], cwd=str(usine),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout.decode("utf-8", "replace")


def commit_all(usine: pathlib.Path, message: str) -> None:
    """Commit the current tree so it stays clean for merge preconditions."""
    for args in (("add", "-A"),
                 ("-c", "user.name=smoke", "-c", "user.email=smoke@local",
                  "commit", "-q", "-m", message)):
        proc = subprocess.run(["git", *args], cwd=str(usine),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: "
                               f"{proc.stderr.decode('utf-8', 'replace')[:300]}")


def gate_runs(usine: pathlib.Path) -> int:
    marker = usine / "gate-ran-marker"
    if not marker.is_file():
        return 0
    return len(marker.read_text(encoding="utf-8").splitlines())


def tree_sha(usine: pathlib.Path, rel: str):
    path = usine.joinpath(*PurePosixPath(rel).parts)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


# ------------------------------------------------------- A: archives and delta

def test_archives() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-a-") as tmp:
        root = pathlib.Path(tmp)

        materials = write_materials(root / "inv", {
            "src/a.txt": b"AAA\n", "junk/__pycache__/m.pyc": b"\x00\x01",
            "skipped/.venv/lib.py": b"venv", ".DS_Store": b"junk",
        }, links={"lnk": "src/a.txt"})
        inv = wave_merge.load_archive_inventory(materials, "inv")
        check("inventory: prefix stripped, files partitioned",
              inv["files"] == {"src/a.txt": hashlib.sha256(b"AAA\n").hexdigest()}
              and inv["symlinks"] == {"lnk": "src/a.txt"}
              and len(inv["excluded"]) == 3 and inv["members"] == 5, inv)

        corrupt = write_materials(root / "corrupt", {"src/a.txt": b"AAA\n"})
        with open(corrupt / "materials.MANIFEST.sha256", "a",
                  encoding="utf-8") as handle:
            handle.write(f"{'0' * 64}  {PREFIX}src/a.txt\n")
        expect_raise("inventory: sidecar divergence fails closed",
                     wave_merge.load_archive_inventory, corrupt, "corrupt")

        wrongroots = write_materials(root / "wrongroots", {"src/a.txt": b"AAA\n"})
        (wrongroots / "materials.ROOTS.json").write_text(
            json.dumps({"schema_version": 1, "roots": ["raw"]}),
            encoding="utf-8")
        expect_raise("inventory: non-project roots fail closed",
                     wave_merge.load_archive_inventory, wrongroots, "wrongroots")

        special = root / "special"
        special.mkdir()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            member = tarfile.TarInfo(PREFIX + "pipe")
            member.type = tarfile.FIFOTYPE
            tf.addfile(member)
        (special / "materials.tgz").write_bytes(buf.getvalue())
        (special / "materials.ROOTS.json").write_text(
            json.dumps({"schema_version": 1, "roots": ["evolution_project"]}),
            encoding="utf-8")
        expect_raise("inventory: special archive member fails closed",
                     wave_merge.load_archive_inventory, special, "special")

        expect_raise("inventory: missing archive fails closed",
                     wave_merge.load_archive_inventory, root / "absent", "absent")

        fixture = {"src/a.txt": b"A\n", "src/b.txt": b"B\n", "old.txt": b"O\n"}
        candidate = {"src/a.txt": b"A2\n", "src/b.txt": b"B\n", "new.txt": b"N\n"}
        delta = wave_merge.candidate_delta(
            wave_merge.load_archive_inventory(
                write_materials(root / "fx", fixture), "fx")["files"],
            wave_merge.load_archive_inventory(
                write_materials(root / "cd", candidate), "cd")["files"])
        check("delta: modified/added/deleted",
              delta == {"modified": ["src/a.txt"], "added": ["new.txt"],
                        "deleted": ["old.txt"]}, delta)

        noise_fx = {"src/a.txt": b"A\n", ".venv/lib.py": b"V1\n",
                    "__pycache__/m.pyc": b"P1\n",
                    "node_modules/x/y.js": b"N1\n",
                    "dist/index.mjs": b"D1\n",
                    "packages/core/dist/index.mjs": b"D2\n",
                    "packages/core/node_modules/x/y.js": b"N2\n",
                    "tsconfig.tsbuildinfo": b"T1\n",
                    "build/publish-verify/mock-events.json": b"E1\n"}
        noise_cd = {"src/a.txt": b"A\n", ".venv/lib.py": b"V2\n",
                    "__pycache__/m.pyc": b"P2\n",
                    "node_modules/x/y.js": b"N3\n",
                    "dist/index.mjs": b"D3\n",
                    "packages/core/dist/index.mjs": b"D4\n",
                    "packages/core/node_modules/x/y.js": b"N4\n",
                    "tsconfig.tsbuildinfo": b"T2\n",
                    "build/publish-verify/mock-events.json": b"E2\n"}
        delta = wave_merge.candidate_delta(
            wave_merge.load_archive_inventory(
                write_materials(root / "nfx", noise_fx), "nfx")["files"],
            wave_merge.load_archive_inventory(
                write_materials(root / "ncd", noise_cd), "ncd")["files"])
        check("delta: symmetric exclusions never enter the delta",
              delta == {"modified": [], "added": [], "deleted": []}, delta)
        inv_cd = wave_merge.load_archive_inventory(
            write_materials(root / "ncd2", noise_cd), "ncd2")
        check("delta: TS regenerables are partitioned into excluded "
              "(node_modules/dist/build at any depth, *.tsbuildinfo)",
              sorted(inv_cd["excluded"]) == [
                  ".venv/lib.py", "__pycache__/m.pyc",
                  "build/publish-verify/mock-events.json",
                  "dist/index.mjs", "node_modules/x/y.js",
                  "packages/core/dist/index.mjs",
                  "packages/core/node_modules/x/y.js",
                  "tsconfig.tsbuildinfo"], inv_cd["excluded"])

        links_same = wave_merge.symlink_changes({"l": "a"}, {"l": "a"})
        links_diff = wave_merge.symlink_changes({"l": "a", "g": "b"},
                                                {"l": "z", "n": "c"})
        check("symlinks: unchanged tolerated, changes flagged",
              links_same["unchanged"] == 1 and not links_same["changed"]
              and links_diff["changed"] == ["l"]
              and links_diff["added"] == ["n"]
              and links_diff["removed"] == ["g"], (links_same, links_diff))

        tree = root / "tree"
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "a.txt").write_bytes(b"A\n")
        (tree / "src" / "b.txt").write_bytes(b"B\n")
        fx = {"src/a.txt": hashlib.sha256(b"A\n").hexdigest(),
              "src/b.txt": hashlib.sha256(b"B\n").hexdigest()}
        cd = {"src/a.txt": hashlib.sha256(b"A2\n").hexdigest(),
              "src/b.txt": hashlib.sha256(b"B2\n").hexdigest()}
        delta = {"modified": ["src/a.txt", "src/b.txt"], "added": [],
                 "deleted": []}
        verdict, details = wave_merge.classify_delta(delta, fx, cd, tree)
        check("classify: fresh verdict on a matching tree",
              verdict == "fresh" and details["pre_applied"] == 0, details)
        (tree / "src" / "a.txt").write_bytes(b"A2\n")
        (tree / "src" / "b.txt").write_bytes(b"B2\n")
        verdict, details = wave_merge.classify_delta(delta, fx, cd, tree)
        check("classify: fully pre-applied tree is already_merged",
              verdict == "already_merged", (verdict, details))
        (tree / "src" / "a.txt").write_bytes(b"OTHER\n")
        verdict, details = wave_merge.classify_delta(delta, fx, cd, tree)
        check("classify: foreign bytes are drift",
              verdict == "drift" and "src/a.txt" in details["reason"], details)


# ------------------------------------------------------------- B: merge_wave

def _green_candidate_files() -> dict:
    files = dict(BASE_FILES)
    files["src/a.txt"] = b"NEW-A\n"
    files["src/newdir/new.txt"] = b"NEW\n"
    del files["docs/readme.md"]
    return files


def test_merge_green() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-b1-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-alpha", "PASS",
                     BASE_FILES, _green_candidate_files())
        base = git_read(usine, "rev-parse", "HEAD").strip()

        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))

        check("merge: green candidate commits",
              len(report["commits"]) == 1 and report["candidates"][0]["decision"] == "merged",
              report)
        check("merge: report records topology and tag",
              report["repo_prefix"] == "usine/"
              and report["tag"] == "theatre/wave-1"
              and report["tag_created"] is True
              and report["base_commit"] == base, report.get("repo_prefix"))
        subject = git_read(usine, "log", "-1", "--format=%s").strip()
        body = git_read(usine, "log", "-1", "--format=%B")
        check("merge: subject and trailers",
              subject == "theatre(wave-1): accept ep001 (p-alpha)"
              and "X-Theatre-Project: p-alpha" in body
              and "X-Theatre-Wave: 1" in body, subject)
        check("merge: tree carries candidate bytes",
              (usine / "src/a.txt").read_bytes() == b"NEW-A\n"
              and (usine / "src/newdir/new.txt").read_bytes() == b"NEW\n"
              and not (usine / "docs/readme.md").exists())
        check("merge: tag exists and repo is clean",
              "theatre/wave-1" in git_read(usine, "tag", "-l").split()
              and git_read(usine, "status", "--porcelain", "-uno").strip() == ""
              and git_read(usine, "diff", "--cached", "--name-only").strip() == "")
        check("merge: report files written",
              (lineage / "waves/wave_001/merge_report.json").is_file()
              and "usine wave 1 merge report" in
              (lineage / "waves/wave_001/merge_report.md").read_text(
                  encoding="utf-8"))

        again = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        heads = git_read(usine, "rev-list", "--count", "HEAD").strip()
        check("merge: re-merging a reported wave is a no-op",
              again.get("skipped") == "report_exists" and heads == "2",
              (again.get("skipped"), heads))


def test_merge_exec_bits() -> None:
    """bin/feuille.js is committed 100755: byte-only apply must not flip it.

    The byte-replace (staged temp + os.replace) lands with default bits, so
    the merge restores the executable bit from the tracked index mode (for
    modified paths) or from the archive member mode (for added paths), and
    rollback restores the exact pre-apply mode.  These are POSIX filesystem
    facts; on Windows git keeps the index mode untouched by the working
    tree and os.chmod is a near no-op, so the checks run POSIX-only."""
    if os.name != "posix":
        info("merge: exec bits", "POSIX-only checks; on Windows the index "
             "mode is authoritative and chmod is a no-op — skipped")
        return
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-b7-") as tmp:
        root = pathlib.Path(tmp)
        base_files = dict(BASE_FILES)
        base_files["bin/feuille.js"] = b"#!/usr/bin/env node\nconsole.log(1)\n"
        cand = dict(base_files)
        cand["bin/feuille.js"] = b"#!/usr/bin/env node\nconsole.log(2)\n"
        cand["scripts/deploy.sh"] = b"#!/bin/sh\necho deploy\n"

        usine = make_repo(root, base_files)
        os.chmod(usine / "bin/feuille.js", 0o755)
        commit_all(usine, "baseline carries 100755")
        check("merge: baseline fixture is tracked 100755",
              git_read(usine, "ls-files", "-s", "--", "bin/feuille.js"
                       ).split()[0] == "100755",
              git_read(usine, "ls-files", "-s", "--", "bin/feuille.js"))

        lineage = root / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-exec", "PASS", base_files,
                     cand, candidate_modes={"scripts/deploy.sh": 0o755})
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        entry = report["candidates"][0]
        check("merge: green candidate with exec paths commits",
              entry["decision"] == "merged" and len(report["commits"]) == 1,
              entry)
        exec_file = usine / "bin/feuille.js"
        added = usine / "scripts/deploy.sh"
        check("merge: modified 100755 keeps the exec bit through byte change",
              exec_file.read_bytes() == b"#!/usr/bin/env node\nconsole.log(2)\n"
              and exec_file.stat().st_mode & 0o111
              and git_read(usine, "ls-files", "-s", "--",
                           "bin/feuille.js").split()[0] == "100755",
              git_read(usine, "ls-files", "-s", "--", "bin/feuille.js"))
        check("merge: archive exec bit lands for added paths",
              added.read_bytes() == b"#!/bin/sh\necho deploy\n"
              and added.stat().st_mode & 0o111)

        red = make_repo(root / "red", base_files)
        os.chmod(red / "bin/feuille.js", 0o755)
        commit_all(red, "baseline carries 100755")
        (red / "gate-fail").write_text("1", encoding="utf-8")
        lineage_red = root / "red" / "lineage"
        make_episode(lineage_red, "ep001", 1, 1, "p-exec2", "PASS",
                     base_files, cand,
                     candidate_modes={"scripts/deploy.sh": 0o755})
        report_red = wave_merge.merge_wave(
            str(lineage_red), 1, config_for(red))
        entry_red = report_red["candidates"][0]
        check("merge: gate red rolls back bytes AND mode",
              entry_red["decision"] == "gate_rejected"
              and (red / "bin/feuille.js").read_bytes()
              == b"#!/usr/bin/env node\nconsole.log(1)\n"
              and (red / "bin/feuille.js").stat().st_mode & 0o111
              and not (red / "scripts/deploy.sh").exists(),
              entry_red)


def test_merge_rejections() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-b2-") as tmp:
        root = pathlib.Path(tmp)

        # gate red -> byte-exact rollback
        usine = make_repo(root / "red")
        lineage = root / "red" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-alpha", "PASS",
                     BASE_FILES, _green_candidate_files())
        (usine / "gate-fail").write_text("1", encoding="utf-8")
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        entry = report["candidates"][0]
        check("merge: gate red rejects and rolls back byte-exactly",
              entry["decision"] == "gate_rejected"
              and entry["gate"]["exit_code"] == 1
              and (usine / "src/a.txt").read_bytes() == b"BASE-A\n"
              and not (usine / "src/newdir/new.txt").exists()
              and (usine / "docs/readme.md").read_bytes() == b"README\n"
              and git_read(usine, "status", "--porcelain", "-uno").strip() == ""
              and report["commits"] == [] and report["tag"] is None
              and gate_runs(usine) == 1, entry)

        # FAIL episode -> never gated
        usine = make_repo(root / "fail")
        lineage = root / "fail" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-beta", "FAIL",
                     BASE_FILES, _green_candidate_files())
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: FAIL episode recorded, never gated",
              report["candidates"][0]["decision"] == "not_pass"
              and gate_runs(usine) == 0 and report["commits"] == [],
              report["candidates"][0])

        # drift -> whole-candidate skip (the foreign change is committed, so
        # the tree is clean but no longer matches this candidate's baseline)
        usine = make_repo(root / "drift")
        lineage = root / "drift" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-gamma", "PASS",
                     BASE_FILES, _green_candidate_files())
        (usine / "src/a.txt").write_bytes(b"FOREIGN\n")
        commit_all(usine, "foreign baseline change")
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: drift skips the whole candidate",
              report["candidates"][0]["decision"] == "drift_skipped"
              and (usine / "src/a.txt").read_bytes() == b"FOREIGN\n"
              and gate_runs(usine) == 0, report["candidates"][0])

        # already merged -> idempotent no-op (the candidate's bytes were
        # committed by an earlier crashed run, tree stays clean)
        usine = make_repo(root / "pre")
        lineage = root / "pre" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-delta", "PASS",
                     BASE_FILES, _green_candidate_files())
        for rel, data in _green_candidate_files().items():
            target = usine.joinpath(*PurePosixPath(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (usine / "docs/readme.md").unlink()
        commit_all(usine, "candidate pre-landed")
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: already-merged candidate is an idempotent no-op",
              report["candidates"][0]["decision"] == "already_merged"
              and gate_runs(usine) == 0 and report["commits"] == [],
              report["candidates"][0])

        # candidate byte-identical to baseline -> merged_noop, never gated
        usine = make_repo(root / "noop")
        lineage = root / "noop" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-eps", "PASS",
                     BASE_FILES, dict(BASE_FILES))
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: byte-identical candidate is merged_noop",
              report["candidates"][0]["decision"] == "merged_noop"
              and gate_runs(usine) == 0, report["candidates"][0])


def test_merge_serial() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-b3-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        first_files = dict(BASE_FILES)
        first_files["src/a.txt"] = b"FIRST\n"
        second_files = dict(BASE_FILES)
        second_files["src/b.txt"] = b"SECOND\n"
        make_episode(lineage, "ep001", 1, 1, "p-first", "PASS",
                     BASE_FILES, first_files)
        make_episode(lineage, "ep002", 1, 2, "p-second", "PASS",
                     BASE_FILES, second_files)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        decisions = [entry["decision"] for entry in report["candidates"]]
        check("merge: two disjoint candidates merge serially",
              decisions == ["merged", "merged"] and len(report["commits"]) == 2,
              decisions)
        parent = git_read(usine, "rev-parse", "HEAD^").strip()
        check("merge: second commit sits on the first",
              parent == report["commits"][0]
              and (usine / "src/a.txt").read_bytes() == b"FIRST\n"
              and (usine / "src/b.txt").read_bytes() == b"SECOND\n",
              parent)
        check("merge: one tag for the whole wave",
              git_read(usine, "tag", "-l").split().count("theatre/wave-1") == 1)

        # overlap: second candidate touches a file the first already merged
        usine = make_repo(root / "overlap")
        lineage = root / "overlap" / "lineage"
        clash_files = dict(BASE_FILES)
        clash_files["src/a.txt"] = b"CLASH\n"
        make_episode(lineage, "ep001", 1, 1, "p-one", "PASS",
                     BASE_FILES, first_files)
        make_episode(lineage, "ep002", 1, 2, "p-two", "PASS",
                     BASE_FILES, clash_files)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: overlapping file drift-skips the later candidate",
              [entry["decision"] for entry in report["candidates"]]
              == ["merged", "drift_skipped"]
              and (usine / "src/a.txt").read_bytes() == b"FIRST\n",
              [e["decision"] for e in report["candidates"]])

        # mixed pre-applied: one file already carries the candidate bytes
        mixed_prior = dict(BASE_FILES)
        mixed_prior["src/c.txt"] = b"SHARED\n"  # what both candidates produce
        usine = make_repo(root / "mixed", files=mixed_prior)
        lineage = root / "mixed" / "lineage"
        mixed_fixture = dict(BASE_FILES)
        mixed_fixture["src/c.txt"] = b"BASE-C\n"
        first_mixed = dict(mixed_fixture)
        first_mixed["src/c.txt"] = b"SHARED\n"
        second_mixed = dict(mixed_fixture)
        second_mixed["src/c.txt"] = b"SHARED\n"
        second_mixed["src/b.txt"] = b"MIXED-B\n"
        make_episode(lineage, "ep001", 1, 1, "p-m1", "PASS",
                     mixed_fixture, first_mixed)
        make_episode(lineage, "ep002", 1, 2, "p-m2", "PASS",
                     mixed_fixture, second_mixed)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        second = report["candidates"][1]
        check("merge: mixed pre-applied still merges with a count",
              second["decision"] == "merged" and second["pre_applied"] == 1
              and (usine / "src/b.txt").read_bytes() == b"MIXED-B\n",
              second)


def test_merge_policy_and_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-b4-") as tmp:
        root = pathlib.Path(tmp)

        # gitignored added path -> whole-candidate path-policy skip.
        # ``build/`` no longer fits this role: it is a symmetric capture/merge
        # exclusion now (a guest gate's untracked publish-verify evidence
        # must not skip a whole candidate) - pinned separately one block below.
        usine = make_repo(root / "ignored")
        (usine / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=str(usine),
                       check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=smoke",
                        "-c", "user.email=smoke@local",
                        "commit", "-q", "-m", "gitignore"],
                       cwd=str(usine), check=True, capture_output=True)
        lineage = root / "ignored" / "lineage"
        fixture = dict(BASE_FILES)
        fixture[".gitignore"] = b"ignored.bin\n"
        candidate = _green_candidate_files()
        candidate["ignored.bin"] = b"BIN\n"
        make_episode(lineage, "ep001", 1, 1, "p-ign", "PASS",
                     fixture, candidate)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: gitignored added path skips the candidate",
              report["candidates"][0]["decision"] == "path_policy_skipped"
              and "ignore rules" in report["candidates"][0]["reason"]
              and gate_runs(usine) == 0, report["candidates"][0])

        # build/ added path: symmetric exclusion, NOT a path-policy skip -
        # publish 测试的 build/ publish-verify 证据副本是 guest 门禁的
        # 未跟踪副作用，不许它拖死整案.
        usine = make_repo(root / "bnoise")
        lineage = root / "bnoise" / "lineage"
        candidate = _green_candidate_files()
        candidate["build/publish-verify/mock-events.json"] = b"E\n"
        make_episode(lineage, "ep001", 1, 1, "p-bnoise", "PASS",
                     BASE_FILES, candidate)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        entry = report["candidates"][0]
        check("merge: build/ noise is excluded, candidate still merges",
              entry["decision"] == "merged"
              and "build/publish-verify/mock-events.json"
              not in entry["delta"]["added"]
              and entry["excluded"] >= 1,
              entry)

        # Windows reserved + trailing-dot names
        usine = make_repo(root / "reserved")
        lineage = root / "reserved" / "lineage"
        candidate = _green_candidate_files()
        candidate["aux.py"] = b"print('aux')\n"
        candidate["notes."] = b"dotted\n"
        make_episode(lineage, "ep001", 1, 1, "p-res", "PASS",
                     BASE_FILES, candidate)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        reason = report["candidates"][0]["reason"]
        check("merge: Windows-reserved and trailing-dot names skip",
              report["candidates"][0]["decision"] == "path_policy_skipped"
              and "aux.py" in reason and "notes." in reason, reason)

        # gate side effects outside the delta are reverted and recorded
        usine = make_repo(root / "side")
        (usine / "src/innocent.txt").write_bytes(b"INNOCENT\n")
        subprocess.run(["git", "add", "-A"], cwd=str(usine), check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=smoke",
                        "-c", "user.email=smoke@local",
                        "commit", "-q", "-m", "innocent"],
                       cwd=str(usine), check=True, capture_output=True)
        fixture = dict(BASE_FILES)
        fixture["src/innocent.txt"] = b"INNOCENT\n"
        lineage = root / "side" / "lineage"
        (usine / "gate-side-effect").write_text("1", encoding="utf-8")
        candidate = _green_candidate_files()
        candidate["src/innocent.txt"] = b"INNOCENT\n"
        make_episode(lineage, "ep001", 1, 1, "p-side", "PASS",
                     fixture, candidate)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        names = git_read(usine, "show", "--name-only", "--format=", "HEAD")
        check("merge: tracked gate side effects reverted, commit stays pure",
              report["candidates"][0]["decision"] == "merged"
              and report["candidates"][0].get("gate_side_effects")
              == ["src/innocent.txt"]
              and (usine / "src/innocent.txt").read_bytes() == b"INNOCENT\n"
              and "src/innocent.txt" not in names.split(),
              report["candidates"][0].get("gate_side_effects"))

        # gate reverts the applied delta -> nothing to commit
        usine = make_repo(root / "revert")
        lineage = root / "revert" / "lineage"
        (usine / "gate-revert").write_text("1", encoding="utf-8")
        candidate = dict(BASE_FILES)
        candidate["src/a.txt"] = b"NEW-A\n"
        make_episode(lineage, "ep001", 1, 1, "p-rev", "PASS",
                     BASE_FILES, candidate)
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: gate reverting the delta records merged_noop",
              report["candidates"][0]["decision"] == "merged_noop"
              and report["commits"] == []
              and (usine / "src/a.txt").read_bytes() == b"BASE-A\n",
              report["candidates"][0])

        # missing gate command -> infra raise with the tree restored
        usine = make_repo(root / "nogate")
        lineage = root / "nogate" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-nogate", "PASS",
                     BASE_FILES, _green_candidate_files())
        expect_raise("merge: missing gate command raises and restores",
                     wave_merge.merge_wave, str(lineage), 1,
                     config_for(usine, ["definitely-missing-gate-cmd"]))
        check("merge: tree restored after the gate infra failure",
              (usine / "src/a.txt").read_bytes() == b"BASE-A\n"
              and not (usine / "src/newdir/new.txt").exists()
              and git_read(usine, "status", "--porcelain", "-uno").strip() == "")


def test_merge_preconditions() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-b5-") as tmp:
        root = pathlib.Path(tmp)

        usine = make_repo(root / "dirty")
        lineage = root / "dirty" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-dirty", "PASS",
                     BASE_FILES, _green_candidate_files())
        (usine / "src/b.txt").write_bytes(b"DIRTY\n")
        expect_raise("merge: dirty tracked tree fails closed",
                     wave_merge.merge_wave, str(lineage), 1, config_for(usine))

        usine = make_repo(root / "staged")
        lineage = root / "staged" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-staged", "PASS",
                     BASE_FILES, _green_candidate_files())
        (usine.parent / "other.txt").write_bytes(b"OTHER\n")
        subprocess.run(["git", "add", "other.txt"], cwd=str(usine.parent),
                       check=True, capture_output=True)
        expect_raise("merge: staged repo state fails closed",
                     wave_merge.merge_wave, str(lineage), 1, config_for(usine))

        usine = make_repo(root / "noarc")
        lineage = root / "noarc" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-noarc", "PASS",
                     BASE_FILES, None)
        expect_raise("merge: PASS episode without archives fails closed",
                     wave_merge.merge_wave, str(lineage), 1, config_for(usine))

        usine = make_repo(root / "nowave")
        expect_raise("merge: wave without episodes fails closed",
                     wave_merge.merge_wave, str(root / "nowave" / "lineage"),
                     7, config_for(usine))

        # baselines/wave_NNN is preferred over the episode fixture
        usine = make_repo(root / "baseline", files={"src/a.txt": b"REAL-A\n"})
        lineage = root / "baseline" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-base", "PASS",
                     {"src/a.txt": b"OLD-A\n"},
                     {"src/a.txt": b"NEW-A\n"})
        write_materials(lineage / "baselines" / "wave_001",
                        {"src/a.txt": b"REAL-A\n"})
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("merge: recorded baseline wins over the episode fixture",
              report["candidates"][0]["decision"] == "merged"
              and (usine / "src/a.txt").read_bytes() == b"NEW-A\n",
              report["candidates"][0])


# ----------------------------------------------- C: event sink and catch-up

def test_sink_and_catchup() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-c-") as tmp:
        root = pathlib.Path(tmp)

        usine = make_repo(root / "sink")
        lineage = root / "sink" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-sink", "PASS",
                     BASE_FILES, _green_candidate_files())
        events: list[tuple] = []

        def inner(event_type, status="in_progress", state=None, payload=None,
                  **kwargs):
            events.append((event_type, status, payload))

        sink = wave_merge.wave_merge_event_sink(
            str(lineage), config_for(usine), inner)
        sink("PHASE1_WAVE_STARTED", status="in_progress",
             payload={"wave": 1, "projects": 1})
        sink("PHASE1_BRANCH_VERIFIED", status="in_progress",
             payload={"wave": 1, "project": 1})
        check("sink: non-terminal events never merge",
              len(events) == 2 and gate_runs(usine) == 0, events)
        sink("PHASE1_WAVE_COMPLETED", status="completed",
             payload={"wave": 1, "projects": 1, "total_projects": 1})
        kinds = [event[0] for event in events]
        check("sink: completed wave merges after the event is forwarded",
              kinds == ["PHASE1_WAVE_STARTED", "PHASE1_BRANCH_VERIFIED",
                        "PHASE1_WAVE_COMPLETED", "USINE_WAVE_MERGED"]
              and events[-1][2]["commits"] and events[-1][2]["tag"],
              kinds)
        check("sink: merged tree state",
              (usine / "src/a.txt").read_bytes() == b"NEW-A\n"
              and "theatre/wave-1" in git_read(usine, "tag", "-l").split())

        # merge failure propagates AFTER the inner sink saw the event
        usine = make_repo(root / "raise")
        lineage = root / "raise" / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-raise", "PASS",
                     BASE_FILES, None)  # no candidate archive
        events = []

        def inner2(event_type, status="in_progress", state=None,
                   payload=None, **kwargs):
            events.append((event_type, status))

        sink = wave_merge.wave_merge_event_sink(
            str(lineage), config_for(usine), inner2)
        try:
            sink("PHASE1_WAVE_COMPLETED", status="completed",
                 payload={"wave": 1, "total_projects": 1})
            check("sink: merge failure propagates", False, "no exception")
        except wave_merge.UsineMergeError:
            check("sink: merge failure propagates", True)
        check("sink: the inner sink saw the event before the failure",
              events == [("PHASE1_WAVE_COMPLETED", "completed")], events)

        # catch-up: only confirmed unreported waves merge, in order
        usine = make_repo(root / "catchup")
        lineage = root / "catchup" / "lineage"
        first_files = dict(BASE_FILES)
        first_files["src/a.txt"] = b"CATCH1\n"
        make_episode(lineage, "ep001", 1, 1, "p-c1", "PASS",
                     BASE_FILES, first_files)
        (lineage / "waves/wave_001").mkdir(parents=True)
        (lineage / "waves/wave_001/merge_report.json").write_text(
            json.dumps({"schema_version": 1, "wave_index": 1}), encoding="utf-8")
        second_files = dict(BASE_FILES)
        second_files["src/b.txt"] = b"CATCH2\n"
        make_episode(lineage, "ep002", 2, 2, "p-c2", "PASS",
                     BASE_FILES, second_files)
        third_files = dict(BASE_FILES)
        third_files["src/b.txt"] = b"NEVER\n"
        make_episode(lineage, "ep003", 3, 3, "p-c3", "PASS",
                     BASE_FILES, third_files)
        (lineage / "events.jsonl").write_text(
            json.dumps({"event_type": "PHASE1_WAVE_COMPLETED",
                        "payload": {"wave": 1, "total_projects": 1}}) + "\n"
            + json.dumps({"event_type": "PHASE1_WAVE_COMPLETED",
                          "payload": {"wave": 2, "total_projects": 2}}) + "\n",
            encoding="utf-8")
        reports = wave_merge.merge_pending_waves(str(lineage), config_for(usine))
        check("catch-up: merges only the confirmed unreported wave",
              [report["wave_index"] for report in reports] == [2]
              and (usine / "src/b.txt").read_bytes() == b"CATCH2\n"
              and (usine / "src/a.txt").read_bytes() == b"BASE-A\n"
              and "theatre/wave-2" in git_read(usine, "tag", "-l").split()
              and not (lineage / "waves/wave_003/merge_report.json").is_file(),
              [r["wave_index"] for r in reports])

        with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-c2-") as tmp2:
            root2 = pathlib.Path(tmp2)
            usine = make_repo(root2 / "empty")
            lineage = root2 / "empty" / "lineage"
            check("catch-up: nothing pending returns empty",
                  wave_merge.merge_pending_waves(str(lineage),
                                                 config_for(usine)) == [])
            make_episode(lineage, "ep001", 1, 1, "p-nolog", "PASS",
                         BASE_FILES, _green_candidate_files())
            expect_raise("catch-up: pending without an event log fails closed",
                         wave_merge.merge_pending_waves, str(lineage),
                         config_for(usine))


def main() -> int:
    test_archives()
    test_merge_green()
    test_merge_exec_bits()
    test_merge_rejections()
    test_merge_serial()
    test_merge_policy_and_gate()
    test_merge_preconditions()
    test_sink_and_catchup()
    passed = sum(1 for status, _, _ in RESULTS if status == "PASS")
    failed = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    infos = sum(1 for status, _, _ in RESULTS if status == "INFO")
    print(f"\nsmoke_wave_merge: {passed} PASS / {failed} FAIL / {infos} INFO")
    if failed:
        for status, name, detail in RESULTS:
            if status == "FAIL":
                print(f"  FAIL {name} | {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
