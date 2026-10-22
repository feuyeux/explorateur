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
import time
from pathlib import Path

from checks import bootstrap, check, info, record, summarise  # noqa: E402

THEATRE, HERE = bootstrap(__file__)

import wave_merge  # noqa: E402
from explore.provisioning import _symlink_digest  # noqa: E402


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
if os.path.exists(_p("gate-counts")):
    # 让桩门禁能吐 vitest 风格的汇总行，好让合并器把「跳过几项」记进报告。
    with open(_p("gate-counts"), "r", encoding="utf-8") as handle:
        sys.stdout.write(handle.read())
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


def make_repo(base: pathlib.Path, files=None,
              autocrlf: str = "false") -> pathlib.Path:
    """A throwaway git repo with the usine project as a tracked subtree.

    The repository root is ``base/repo`` and the project files live under
    ``base/repo/usine`` — the explorateur topology (usine is a subtree of a
    larger repository), so the prefix-aware git paths stay covered.

    ``autocrlf`` is the repository's line-ending policy AT COMMIT TIME,
    and it has to be: git caches the "convert to git" filter in the INDEX
    ENTRY when a file is added, so a file committed under
    ``autocrlf=false`` is still compared byte-for-byte afterwards even if
    the config is changed later.  The real repository commits under
    ``autocrlf=input``, which is why a CRLF working-tree file there is
    still "clean" to git.
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
    git("config", "core.autocrlf", autocrlf)
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
        gate_argv=tuple(gate_argv) if gate_argv else (sys.executable, "gate.py"),
        # The throwaway repo has no adaptation layer inside it, so the memory
        # snapshot is told where to land — same knob the real deployment uses
        # when the layer sits outside the repository.
        memory_snapshot_dir="garage")


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


def refresh_index(usine: pathlib.Path) -> None:
    """Re-stage the tree so git's index stat cache matches the worktree.

    This is what makes a CRLF working-tree file "clean" to git: the index
    entry keeps the folded LF blob and picks up the CRLF file's stat, so
    git no longer sees a difference.  No commit happens — the content did
    not change, only its on-disk spelling.
    """
    proc = subprocess.run(["git", "add", "-A"], cwd=str(usine),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("git add failed: "
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


# ------------------------------------------- D: line endings and the DRS merge

def test_crlf_worktree_is_not_drift() -> None:
    """A CRLF working tree is NOT a content change.

    On this host the repository's canonical form is the LF blob
    (``core.autocrlf=input``: git folds CRLF on the way IN and never expands
    LF on checkout), so a working-tree file may carry CRLF while git still
    calls the file clean.  The merge's drift check compares the working tree
    against the baseline and the candidate; a raw-bytes-only comparison
    called that "drift" and dropped the candidate WHOLE — a
    verifier-PASSed, gate-green improvement lost over line endings.  The
    comparison is raw AND line-ending-folded, so the fold decides here.
    """
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-d1-") as tmp:
        root = pathlib.Path(tmp)
        # The host's real setting, in force FROM THE COMMIT: fold CRLF on
        # the way in, never expand on checkout.
        usine = make_repo(root, autocrlf="input")
        # Reproduce the real situation: the file was edited with CRLF and
        # then added, so git folded it into an LF blob while its index stat
        # still describes the CRLF working-tree file.  The tree therefore
        # reads as CLEAN to git, while the worktree bytes differ from the
        # baseline archive byte-for-byte.
        (usine / "src/a.txt").write_bytes(b"BASE-A\r\n")
        refresh_index(usine)
        check("crlf: git still calls the tree clean",
              git_read(usine, "status", "--porcelain", "-uno").strip() == "",
              git_read(usine, "status", "--porcelain", "-uno"))
        check("crlf: the blob is still the folded LF one",
              git_read(usine, "cat-file", "-s",
                       git_read(usine, "rev-parse", ":usine/src/a.txt").strip()
                       ).strip() == str(len(b"BASE-A\n")),
              git_read(usine, "rev-parse", ":usine/src/a.txt"))

        lineage = root / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-crlf", "PASS",
                     BASE_FILES, _green_candidate_files())
        report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("crlf: the candidate merges instead of drift-skipping",
              report["candidates"][0]["decision"] == "merged"
              and report["candidates"][0]["pre_applied"] == 0,
              report["candidates"][0])
        check("crlf: the tree carries the candidate bytes",
              (usine / "src/a.txt").read_bytes() == b"NEW-A\n",
              (usine / "src/a.txt").read_bytes())

        # A working tree that matches NEITHER side is still drift: the fold
        # only forgives line endings, not content.  The realistic drift case
        # is a tree that MOVED ON after the wave was captured — HEAD's blob
        # is neither the baseline nor the candidate, and the tree is clean.
        other = make_repo(root / "other", autocrlf="input")
        (other / "src/a.txt").write_bytes(b"UNRELATED\n")
        commit_all(other, "unrelated change")
        lineage2 = root / "other" / "lineage"
        make_episode(lineage2, "ep001", 1, 1, "p-drift", "PASS",
                     BASE_FILES, _green_candidate_files())
        report2 = wave_merge.merge_wave(str(lineage2), 1, config_for(other))
        check("crlf: unrelated content is still drift",
              report2["candidates"][0]["decision"] == "drift_skipped",
              report2["candidates"][0])


def make_drs_episode(lineage: pathlib.Path, name: str, outcome: str,
                     fixture_files: dict, candidate_files: dict) -> pathlib.Path:
    """An episode in the ENGINE's DRS shape.

    A DRS episode's ``outcome.json`` carries ``terminal_outcome`` but no
    ``wave_index`` / ``project_id``: it closed with PROJECT_CLOSED, not
    PHASE1_WAVE_COMPLETED.  The merge writes its own Phase-1-shaped record
    BESIDE it and never rewrites the engine's file.
    """
    episode = lineage / "episodes" / name
    write_materials(episode / "fixtures", fixture_files)
    write_materials(episode / "candidates" / "cycle_001", candidate_files)
    (episode / "outcome.json").write_text(json.dumps({
        "schema_version": 1,
        "project_index": 1,
        "project": "a deep drill about the wording of one message",
        "terminal_outcome": outcome,
        "verification_cycles": 1,
    }), encoding="utf-8")
    return episode


def test_drs_merge() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-d2-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        episode = make_drs_episode(lineage, "ep001", "PASS", BASE_FILES,
                                   _green_candidate_files())
        engine_outcome = (episode / "outcome.json").read_bytes()

        report = wave_merge.merge_drs_run(str(lineage), config_for(usine))
        check("drs: the engine's outcome.json is left byte-for-byte alone",
              (episode / "outcome.json").read_bytes() == engine_outcome)
        record = json.loads(
            (episode / "merge_outcome.json").read_text(encoding="utf-8"))
        check("drs: the merge record carries the wave shape",
              record["wave_index"] == 1 and record["project_index"] == 1
              and record["project_id"].startswith("drs-")
              and record["terminal_outcome"] == "PASS", record)
        check("drs: the candidate merges",
              report["candidates"][0]["decision"] == "merged",
              report["candidates"][0])
        subject = git_read(usine, "log", "-1", "--format=%s").strip()
        body = git_read(usine, "log", "-1", "--format=%B")
        check("drs: the commit never calls itself a wave",
              subject.startswith("theatre-drs(drs-1): accept ep001 (drs-")
              and "X-Theatre-Drs: 1" in body
              and "X-Theatre-Wave" not in body, subject)
        tags = git_read(usine, "tag", "-l").split()
        check("drs: the tag is the DRS one, not a wave tag",
              report["tag"] == "theatre/drs-1" and "theatre/drs-1" in tags
              and "theatre/wave-1" not in tags, tags)
        check("drs: the tree carries the candidate bytes",
              (usine / "src/a.txt").read_bytes() == b"NEW-A\n"
              and (usine / "src/newdir/new.txt").read_bytes() == b"NEW\n")


def test_drs_fail_and_plan() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-d3-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        make_drs_episode(lineage, "ep001", "FAIL", BASE_FILES,
                         _green_candidate_files())
        report = wave_merge.merge_drs_run(str(lineage), config_for(usine))
        check("drs: a FAIL episode is not merged",
              report["candidates"][0]["decision"] == "not_pass"
              and not report["commits"], report["candidates"][0])

    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-d4-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        make_drs_episode(lineage, "ep001", "PASS", BASE_FILES,
                         _green_candidate_files())
        head = git_read(usine, "rev-parse", "HEAD").strip()
        plan = wave_merge.plan_drs_run(str(lineage), config_for(usine))
        check("drs plan: the delta and the verdict are reported",
              plan["episodes"][0]["verdict"] == "fresh"
              and plan["episodes"][0]["delta"]["modified"] == ["src/a.txt"]
              and plan["episodes"][0]["delta"]["added"] == ["src/newdir/new.txt"]
              and plan["would_merge"] is True, plan)
        check("drs plan: the tag it would create is the DRS one",
              plan["tag"] == "theatre/drs-1", plan.get("tag"))
        check("drs plan: nothing was applied, committed or gated",
              git_read(usine, "rev-parse", "HEAD").strip() == head
              and git_read(usine, "tag", "-l").strip() == ""
              and git_read(usine, "status", "--porcelain", "-uno").strip() == ""
              and gate_runs(usine) == 0)

    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-d5-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        empty = root / "empty"
        (empty / "episodes").mkdir(parents=True)
        expect_raise("drs merge: no closed episode fails closed",
                     wave_merge.merge_drs_run, str(empty), config_for(usine))


def _sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _spec_registry(base: pathlib.Path, docs: list[str]) -> pathlib.Path:
    """Write a spec-sync registry for the throwaway repo and point the gate at it."""
    path = base / "spec-sync.json"
    path.write_text(json.dumps({"spec_docs": docs}), encoding="utf-8")
    os.environ["GARAGE_SPEC_SYNC_REGISTRY"] = str(path)
    return path


def _spec_doc(anchors: str, prose: str = "spec") -> bytes:
    body = f"# spec\n\n{prose}\n\n```anchors\n{anchors}\n```\n"
    return body.encode("utf-8")


def test_spec_sync_and_memory() -> None:
    """Spec sync gate + memory snapshot + honest gate counts.

    The spec-sync rule exists because a stale spec is worse than a stale
    comment: the next wave reads the spec as the truth about the code, and
    re-does work that was already done.  These cases pin the four outcomes:
    drift without a spec update is rejected, a same-batch spec update is
    accepted, a candidate whose OWN spec lies is rejected, and an untouched
    spec needs no update at all.
    """
    saved_registry = os.environ.get("GARAGE_SPEC_SYNC_REGISTRY")
    try:
        # 1. The spec claims a literal that the code still has: touching an
        #    unrelated file must NOT force a spec update.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            files = dict(BASE_FILES)
            files["docs/spec.md"] = _spec_doc(
                "src/a.txt BASE-A")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "unrelated", "PASS",
                         files, dict(files, **{"src/b.txt": b"CHANGED-B\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            entry = report["candidates"][0]
            check("spec sync: an unrelated change needs no spec update",
                  entry["decision"] == "merged", entry.get("reason", ""))

        # 2. The spec's anchor is gone from the code and the spec was NOT
        #    updated: the candidate must be skipped whole.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            files = dict(BASE_FILES)
            files["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "drift", "PASS",
                         files, dict(files, **{"src/a.txt": b"REWRITTEN\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            entry = report["candidates"][0]
            check("spec sync: a stale spec rejects the candidate",
                  entry["decision"] == "spec_sync_rejected", entry.get("reason", ""))
            check("spec sync: the rejection names the spec and the code",
                  "docs/spec.md" in (entry.get("reason") or "")
                  and "src/a.txt" in (entry.get("reason") or ""),
                  entry.get("reason", ""))
            check("spec sync: the rejected candidate was never applied",
                  tree_sha(usine, "src/a.txt") != _sha_of(b"REWRITTEN\n"), "")

        # 3. The same code change WITH the spec updated in the same candidate
        #    is accepted: that is the escape hatch the rule is designed for.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            files = dict(BASE_FILES)
            files["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            candidate = dict(files, **{"src/a.txt": b"REWRITTEN\n"})
            candidate["docs/spec.md"] = _spec_doc("src/a.txt REWRITTEN")
            make_episode(lineage, "ep001", 1, 1, "updated", "PASS",
                         files, candidate)
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            entry = report["candidates"][0]
            check("spec sync: a same-batch spec update is accepted",
                  entry["decision"] == "merged", entry.get("reason", ""))
            check("spec sync: the accepted candidate carries the new bytes",
                  tree_sha(usine, "src/a.txt") == _sha_of(b"REWRITTEN\n"), "")

        # 4. The candidate updates the spec but the spec now lies: rejected.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            files = dict(BASE_FILES)
            files["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            candidate = dict(files, **{"src/a.txt": b"REWRITTEN\n"})
            candidate["docs/spec.md"] = _spec_doc("src/a.txt NEVER-EXISTED")
            make_episode(lineage, "ep001", 1, 1, "lying", "PASS",
                         files, candidate)
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            entry = report["candidates"][0]
            check("spec sync: a candidate whose own spec lies is rejected",
                  entry["decision"] == "spec_sync_rejected", entry.get("reason", ""))

        # 5. A tree that does not carry the spec at all: the gate cannot
        #    apply, and it says so instead of vanishing.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            usine = make_repo(base)
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "nospec", "PASS",
                         BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"CHANGED-B\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            entry = report["candidates"][0]
            check("spec sync: a missing spec does not block the merge",
                  entry["decision"] == "merged", entry.get("reason", ""))
            check("spec sync: a missing spec is reported as a notice",
                  bool(entry.get("spec_sync_notices")), "")

        # 6. The memory tree lands in the repository, with the engine's own
        #    tree hash, in a commit of its own.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            files = dict(BASE_FILES)
            files["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            memory = lineage / "memory"
            memory.mkdir(parents=True, exist_ok=True)
            (memory / "notes.md").write_text("记住：产线口径\n", encoding="utf-8")
            make_episode(lineage, "ep001", 1, 1, "withmemory", "PASS",
                         files, dict(files, **{"src/b.txt": b"CHANGED-B\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            snapshot = report.get("memory_snapshot") or {}
            check("memory: the snapshot is written", snapshot.get("written") is True,
                  str(snapshot.get("reason", "")))
            check("memory: the snapshot carries a tree hash",
                  bool(snapshot.get("tree_sha256")), "")
            check("memory: the snapshot is committed on its own",
                  bool(snapshot.get("commit")), "")
            log = git_read(usine, "log", "--format=%s%n%b", "-2")
            check("memory: the commit says which unit it belongs to",
                  "X-Theatre-Memory" in log, log[-200:])

        # 7. The gate's skipped count is visible in the report: a skip is not
        #    a pass, and a report that cannot see it overstates coverage.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            usine = make_repo(base)
            (usine / "gate-counts").write_text(
                " Test Files  42 passed (42)\n"
                "      Tests  528 passed | 8 skipped (536)\n", encoding="utf-8")
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "counts", "PASS",
                         BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"CHANGED-B\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            gate = report["candidates"][0].get("gate") or {}
            counts = gate.get("counts") or {}
            check("gate: the skipped count is recorded", counts.get("skipped") == 8,
                  str(counts))
            check("gate: the passed count is recorded", counts.get("passed") == 528,
                  str(counts))
            body = git_read(usine, "log", "--format=%b", "-1")
            check("gate: the commit body admits the skips",
                  "skipped" in body and "NOT passed" in body, body[-200:])

        # 8. A pre-existing drift must not be blamed on the candidate.  A
        #    baseline whose spec is already out of sync must not block every
        #    later candidate — that is how a gate goes silently dead.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            files = dict(BASE_FILES)
            # The spec already claims a literal the code never had.
            files["docs/spec.md"] = _spec_doc("src/a.txt NEVER-EXISTED")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "preexisting", "PASS",
                         files, dict(files, **{"src/b.txt": b"CHANGED-B\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            entry = report["candidates"][0]
            check("spec sync: a pre-existing drift does not block a candidate",
                  entry["decision"] == "merged", entry.get("reason", ""))
            check("spec sync: a pre-existing drift is reported as a notice",
                  bool(entry.get("spec_sync_notices")), "")

        # 9. A gate whose output carries no parsable counts reports null, not
        #    zero: "we could not see it" and "there was none" are different.
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            usine = make_repo(base)
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "nocounts", "PASS",
                         BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"CHANGED-B\n"}))
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            gate = report["candidates"][0].get("gate") or {}
            counts = gate.get("counts") or {}
            check("gate: unparsable counts stay null, not zero",
                  counts.get("skipped") is None, str(counts))
    finally:
        if saved_registry is None:
            os.environ.pop("GARAGE_SPEC_SYNC_REGISTRY", None)
        else:
            os.environ["GARAGE_SPEC_SYNC_REGISTRY"] = saved_registry


FAKE_HEALTH = '''#!/usr/bin/env python3
"""A stand-in for the offline health score, with the same CLI contract.

The real one lives in the target project (packages/eval).  This fake keeps
the contract — "health --out FILE" writes a report, "compare --baseline A
--candidate B" exits 1 when a metric got worse — so the merge's gate wiring
can be tested without the real project in the tree.
"""
import json
import os
import sys

args = sys.argv[1:]


def flag(name):
    return args[args.index(name) + 1] if name in args else None


if args and args[0] == "health":
    out = flag("--out")
    state = "good"
    marker = os.path.join(os.getcwd(), "health-state.txt")
    if os.path.exists(marker):
        with open(marker, encoding="utf-8") as handle:
            state = handle.read().strip()
    value = 1.0 if state == "good" else 0.0
    report = {
        "schema_version": 1,
        "inputs_sha256": state,
        "metrics": {"locale_matrix": {
            "value": value, "unit": "rate", "samples": 14,
            "direction": "higher_is_better"}},
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    sys.exit(0)

if args and args[0] == "compare":
    with open(flag("--baseline"), encoding="utf-8") as handle:
        base = json.load(handle)
    with open(flag("--candidate"), encoding="utf-8") as handle:
        cand = json.load(handle)
    before = base["metrics"]["locale_matrix"]["value"]
    after = cand["metrics"]["locale_matrix"]["value"]
    regressed = after < before
    print(json.dumps({
        "schema_version": 1, "metrics": [],
        "improved": [] if regressed else ["locale_matrix"],
        "regressed": ["locale_matrix"] if regressed else [],
        "unchanged": [], "not_comparable": []}))
    sys.exit(1 if regressed else 0)

sys.exit(2)
'''

FAKE_L3_OK = '''#!/usr/bin/env python3
import sys
sys.exit(0)
'''

FAKE_L3_RED = '''#!/usr/bin/env python3
import sys
sys.exit(1)
'''


def _write_script(path: pathlib.Path, source: str) -> str:
    path.write_text(source, encoding="utf-8")
    return str(path)


def test_health_and_l3_gates() -> None:
    """The health gate and the L3 agent-surface gate.

    The gate says "nothing broke"; the health score says "it got better";
    L3 says "the improvement actually reached the agent surface".  A merge
    needs all three, and each one has to be able to say no.
    """
    saved_registry = os.environ.get("GARAGE_SPEC_SYNC_REGISTRY")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            _spec_registry(base, ["docs/spec.md"])
            health = _write_script(base / "fake-health.py", FAKE_HEALTH)
            l3_ok = _write_script(base / "fake-l3-ok.py", FAKE_L3_OK)
            l3_red = _write_script(base / "fake-l3-red.py", FAKE_L3_RED)

            # 1. A candidate that makes the health score worse is rejected.
            files = dict(BASE_FILES)
            files["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
            usine = make_repo(base, files)
            lineage = base / "lineage"
            make_episode(lineage, "ep001", 1, 1, "worse", "PASS",
                         files, dict(files, **{"health-state.txt": b"bad\n"}))
            config = wave_merge.UsineMergeConfig(
                usine_dir=str(usine), gate_argv=(sys.executable, "gate.py"),
                memory_snapshot_dir="garage",
                health_argv=(sys.executable, health),
                l3_smoke_argv=(sys.executable, l3_ok))
            report = wave_merge.merge_wave(str(lineage), 1, config)
            entry = report["candidates"][0]
            check("health: a worse score rejects the candidate",
                  entry["decision"] == "health_rejected", entry.get("reason", ""))
            check("health: the rejection names the metric",
                  "locale_matrix" in (entry.get("reason") or ""),
                  entry.get("reason", ""))
            check("health: the rejected candidate was rolled back",
                  not (usine / "health-state.txt").exists(), "")

            # 2. A candidate that makes it better is accepted, and the report
            #    says which metrics moved.
            with tempfile.TemporaryDirectory() as tmp2:
                base2 = pathlib.Path(tmp2)
                _spec_registry(base2, ["docs/spec.md"])
                health2 = _write_script(base2 / "fake-health.py", FAKE_HEALTH)
                l3_ok2 = _write_script(base2 / "fake-l3-ok.py", FAKE_L3_OK)
                files2 = dict(BASE_FILES)
                files2["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
                usine2 = make_repo(base2, files2)
                lineage2 = base2 / "lineage"
                make_episode(lineage2, "ep001", 1, 1, "better", "PASS",
                             files2, dict(files2, **{"health-state.txt": b"good\n"}))
                config2 = wave_merge.UsineMergeConfig(
                    usine_dir=str(usine2), gate_argv=(sys.executable, "gate.py"),
                    memory_snapshot_dir="garage",
                    health_argv=(sys.executable, health2),
                    l3_smoke_argv=(sys.executable, l3_ok2))
                report2 = wave_merge.merge_wave(str(lineage2), 1, config2)
                entry2 = report2["candidates"][0]
                check("health: a better score is accepted",
                      entry2["decision"] == "merged", entry2.get("reason", ""))
                check("health: the report says what improved",
                      (entry2.get("health") or {}).get("improved") == ["locale_matrix"],
                      str(entry2.get("health")))

            # 3. L3 red: the improvement never reached the agent surface.
            with tempfile.TemporaryDirectory() as tmp3:
                base3 = pathlib.Path(tmp3)
                _spec_registry(base3, ["docs/spec.md"])
                health3 = _write_script(base3 / "fake-health.py", FAKE_HEALTH)
                l3_red3 = _write_script(base3 / "fake-l3-red.py", FAKE_L3_RED)
                files3 = dict(BASE_FILES)
                files3["docs/spec.md"] = _spec_doc("src/a.txt BASE-A")
                usine3 = make_repo(base3, files3)
                lineage3 = base3 / "lineage"
                make_episode(lineage3, "ep001", 1, 1, "l3red", "PASS",
                             files3, dict(files3, **{"src/b.txt": b"CHANGED-B\n"}))
                config3 = wave_merge.UsineMergeConfig(
                    usine_dir=str(usine3), gate_argv=(sys.executable, "gate.py"),
                    memory_snapshot_dir="garage",
                    health_argv=(sys.executable, health3),
                    l3_smoke_argv=(sys.executable, l3_red3))
                report3 = wave_merge.merge_wave(str(lineage3), 1, config3)
                entry3 = report3["candidates"][0]
                check("l3: a red agent-surface smoke rejects the candidate",
                      entry3["decision"] == "l3_rejected", entry3.get("reason", ""))
                check("l3: the rejection is recorded with its exit code",
                      (entry3.get("l3") or {}).get("exit_code") == 1,
                      str(entry3.get("l3")))
    finally:
        if saved_registry is None:
            os.environ.pop("GARAGE_SPEC_SYNC_REGISTRY", None)
        else:
            os.environ["GARAGE_SPEC_SYNC_REGISTRY"] = saved_registry


def test_collisions_and_snapshot_audit() -> None:
    """两个 run root 都从 wave 1 开始时，不许静默共用 tag 或快照目录。

    2026-10-22 实测的两处静默缺陷（docs/self-evolution.md §5.3(c)）：

    * ``_ensure_wave_tag`` 探测到 ``theatre/wave-1`` 已存在就直接返回，
      于是第二波合进来了却没有指向自己的 tag；
    * 记忆快照目录名只有「单位 + 波次」，两棵 run root 的 wave 1 写进同一个
      ``wave-001/``，盘上 8 个文件而 manifest 只描述 3 个。

    这些断言在旧实现下会挂：旧 tag 路径拿到的是 ``theatre/wave-1`` 且
    ``tag_created`` 为 False；旧快照路径会覆盖 ``wave-001/notes.md``。
    """
    # 1. tag 撞名：第二条 run 的 wave 1 拿到自己的后缀 tag。
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-tags-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        first = root / "run-a" / "lineage"
        second = root / "run-b" / "lineage"
        make_episode(first, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
        make_episode(second, "ep001", 1, 1, "p-b", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/a.txt": b"B-SIDE\n"}))
        report_a = wave_merge.merge_wave(str(first), 1, config_for(usine))
        report_b = wave_merge.merge_wave(str(second), 1, config_for(usine))
        tags = git_read(usine, "tag", "-l").split()
        check("collision: the first wave owns the base tag",
              report_a["tag"] == "theatre/wave-1"
              and report_a["tag_created"] is True, report_a.get("tag"))
        check("collision: the second wave gets a suffix instead of reusing it",
              report_b["tag"] == "theatre/wave-1-2"
              and report_b["tag_created"] is True
              and report_b.get("tag_base") == "theatre/wave-1", report_b.get("tag"))
        check("collision: the report names the tag it collided with",
              (report_b.get("tag_collisions") or [{}])[0].get("tag")
              == "theatre/wave-1"
              and (report_b.get("tag_collisions") or [{}])[0].get("points_at")
              == report_a["commits"][-1], report_b.get("tag_collisions"))
        check("collision: both tags exist and point at their own wave",
              "theatre/wave-1" in tags and "theatre/wave-1-2" in tags
              and git_read(usine, "rev-parse", "theatre/wave-1-2^{commit}").strip()
              == report_b["commits"][-1], tags)

        # 幂等重跑：tag 已经指向本波最后一个提交时，复用而不是再造一个。
        config = config_for(usine)
        reused = wave_merge._ensure_wave_tag(
            config, usine, 1, [report_a["commits"][-1]])
        check("collision: a tag already on this wave's commit is reused",
              reused["tag"] == "theatre/wave-1"
              and reused["tag_created"] is False
              and reused.get("tag_reused") is True, reused)

        # plan 也要报「真正会创建的那个名字」，而不是 base 名。
        git_read(usine, "-c", "user.name=smoke", "-c", "user.email=smoke@local",
                 "tag", "-a", "theatre/drs-1", "-m", "taken")
        plan = wave_merge.plan_drs_run(str(second), config_for(usine))
        check("collision: the DRS plan skips a taken tag name",
              plan["tag"] == "theatre/drs-1-2", plan.get("tag"))

    # 2. 记忆快照撞名：两份都保留，谁也不覆盖谁；审计能把旧式损坏抓出来。
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-snap-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        first = root / "run-a" / "lineage"
        second = root / "run-b" / "lineage"
        (first / "memory").mkdir(parents=True)
        (first / "memory" / "notes.md").write_text("A\n", encoding="utf-8")
        (second / "memory").mkdir(parents=True)
        (second / "memory" / "notes.md").write_text("B\n", encoding="utf-8")
        (second / "memory" / "craft").mkdir()
        (second / "memory" / "craft" / "x.md").write_text(
            "B-craft\n", encoding="utf-8")
        make_episode(first, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
        make_episode(second, "ep001", 1, 1, "p-b", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/a.txt": b"B-SIDE\n"}))
        report_a = wave_merge.merge_wave(str(first), 1, config_for(usine))
        report_b = wave_merge.merge_wave(str(second), 1, config_for(usine))
        snap_root = usine.parent / "garage" / "memory-snapshots"
        snap_a = report_a["memory_snapshot"]
        snap_b = report_b["memory_snapshot"]
        first_dir = snap_root / "wave-001"
        second_dir = snap_root / "wave-001-2"
        check("snapshot: the first run writes wave-001",
              snap_a.get("written") is True and first_dir.is_dir()
              and (first_dir / "notes.md").read_text(encoding="utf-8") == "A\n",
              snap_a)
        check("snapshot: the second run gets a suffix, not an overwrite",
              snap_b.get("written") is True
              and (snap_b.get("collision") or {}).get("base")
              == "garage/memory-snapshots/wave-001"
              and second_dir.is_dir()
              and (second_dir / "notes.md").read_text(encoding="utf-8") == "B\n",
              snap_b)
        check("snapshot: the first run's bytes were left alone",
              (first_dir / "notes.md").read_text(encoding="utf-8") == "A\n"
              and not (first_dir / "craft").exists(), "")
        manifest_b = json.loads((second_dir / "manifest.json").read_text(
            encoding="utf-8"))
        check("snapshot: the suffixed manifest names itself and the collision",
              manifest_b["unit"] == "wave-001-2"
              and manifest_b["collision"]["base"].endswith("wave-001")
              and manifest_b["files"] == ["craft/x.md", "notes.md"], manifest_b)
        audit = wave_merge.verify_memory_snapshots(snap_root)
        check("snapshot audit: two coherent snapshots, no problems",
              len(audit["snapshots"]) == 2 and not audit["problems"],
              audit)
        check("snapshot audit: the engine hash was actually checked",
              audit["hash_checked"] is True, audit)

        # 旧式损坏：目录里多出 manifest 没描述的文件（wave-001 的实测形状）。
        (first_dir / "leftover.md").write_text("stale\n", encoding="utf-8")
        audit = wave_merge.verify_memory_snapshots(snap_root)
        kinds = {(p["path"], p["kind"]) for p in audit["problems"]}
        check("snapshot audit: an undescribed leftover file is a FAIL",
              ("wave-001", "file_set_mismatch") in kinds, audit["problems"])
        (first_dir / "leftover.md").unlink()

        # 同源异内容：同一个 run root 对同一波产出两棵不同记忆树 → fail-closed。
        ctx = wave_merge._repo_context(usine)
        (first / "memory" / "notes.md").write_text("A2\n", encoding="utf-8")
        head_before = git_read(usine, "rev-parse", "HEAD").strip()
        expect_raise(
            "snapshot: same run root + different tree fails closed",
            wave_merge._snapshot_memory_into_repo,
            ctx, first, "wave", 1, "garage")
        check("snapshot: the fail-closed path did not overwrite the snapshot",
              (first_dir / "notes.md").read_text(encoding="utf-8") == "A\n"
              and git_read(usine, "rev-parse", "HEAD").strip() == head_before,
              "")

        # 内容没变就是幂等：不写第二份、不再提交一次。
        (first / "memory" / "notes.md").write_text("A\n", encoding="utf-8")
        again = wave_merge._snapshot_memory_into_repo(
            ctx, first, "wave", 1, "garage")
        check("snapshot: re-snapshotting the same tree is a no-op",
              again.get("written") is False
              and again.get("idempotent") is True
              and again.get("path", "").endswith("wave-001")
              and git_read(usine, "rev-parse", "HEAD").strip() == head_before,
              again)

        # 另一个 run root 产出**逐字相同**的记忆树：不写第二份，但别把
        # 「是两条 run」这件事抹掉——报告里要能看见已有快照来自谁。
        third = root / "run-c" / "lineage"
        (third / "memory").mkdir(parents=True)
        (third / "memory" / "notes.md").write_text("A\n", encoding="utf-8")
        make_episode(third, "ep001", 1, 1, "p-c", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/c.txt": b"C-SIDE\n"}))
        report_c = wave_merge.merge_wave(str(third), 1, config_for(usine))
        snap_c = report_c["memory_snapshot"]
        check("snapshot: byte-identical tree from another run root is reused",
              snap_c.get("written") is False
              and snap_c.get("idempotent") is True
              and snap_c.get("existing_source") == str(first / "memory")
              and not (snap_root / "wave-001-3").exists(), snap_c)


    # 3. 崩溃重跑：候选字节已在树里（merged_noop），记忆仍要能进仓库。
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-resume-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        (lineage / "memory").mkdir(parents=True)
        (lineage / "memory" / "notes.md").write_text("A\n", encoding="utf-8")
        make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
        first = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        check("resume: the first attempt snapshots the memory",
              (first.get("memory_snapshot") or {}).get("written") is True,
              first.get("memory_snapshot"))
        head = git_read(usine, "rev-parse", "HEAD").strip()
        # 模拟「快照提交之后、报告落盘之前」崩溃：报告没了，代码与快照都在。
        (lineage / "waves/wave_001/merge_report.json").unlink()
        (lineage / "waves/wave_001/merge_report.md").unlink()
        again = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        snap = again.get("memory_snapshot") or {}
        check("resume: already-applied candidates are already_merged",
              [e["decision"] for e in again["candidates"]]
              == ["already_merged"] and again["commits"] == [],
              again.get("candidates"))
        check("resume: memory is still snapshotted (or found identical)",
              snap.get("written") is True or snap.get("idempotent") is True,
              snap)
        check("resume: no second commit was made just to redo the snapshot",
              git_read(usine, "rev-parse", "HEAD").strip() == head, head)


def test_crash_recovery() -> None:
    """提交已落、tag/快照未落时，下一次必须从进度日志把这一波收完。

    这三条覆盖旧实现的三个洞：

    * tag 步骤失败后，提交已经在仓库里，但**没有 tag、没有报告**——旧实现
      下一次会把候选判成 `already_merged`，然后 `commits=[]`，tag 永远不补；
    * 快照步骤失败后同理，记忆永远进不了仓库；
    * 进度日志必须证明它指向的提交仍在当前历史里——rebase/reset 之后拿旧
      日志补 tag，会把 tag 打到一条不存在的提交上。
    """
    original_tag = wave_merge._ensure_wave_tag
    original_snapshot = wave_merge._snapshot_memory_into_repo

    def fail(*_args, **_kwargs):
        raise wave_merge.UsineMergeError("injected failure")

    # A. 提交之后、tag 之前崩溃 → 下一次从日志补 tag。
    try:
        with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-crash-tag-") as tmp:
            root = pathlib.Path(tmp)
            usine = make_repo(root)
            lineage = root / "lineage"
            (lineage / "memory").mkdir(parents=True)
            (lineage / "memory" / "notes.md").write_text("A\n", encoding="utf-8")
            make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
            progress_path = lineage / "waves/wave_001/merge_progress.json"
            report_path = lineage / "waves/wave_001/merge_report.json"

            wave_merge._ensure_wave_tag = fail
            expect_raise("crash: the tag-step failure propagates",
                         wave_merge.merge_wave, str(lineage), 1,
                         config_for(usine))
            journal = json.loads(progress_path.read_text(encoding="utf-8"))
            check("crash: the commit is in the journal",
                  len(journal["commits"]) == 1
                  and journal["status"] == "committing", journal)
            check("crash: no report and no tag were written yet",
                  not report_path.exists()
                  and git_read(usine, "tag", "-l").strip() == "", "")

            wave_merge._ensure_wave_tag = original_tag
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            check("crash: the retry says it resumed",
                  report.get("resumed_from_progress") is True
                  and report.get("commits_made_this_run") == 0
                  and report["commits"] == journal["commits"], report)
            check("crash: the tag is recovered at the recorded commit",
                  git_read(usine, "rev-parse",
                           "theatre/wave-1^{commit}").strip()
                  == journal["commits"][0], git_read(usine, "tag", "-l"))
            check("crash: the journal is cleared after the report",
                  not progress_path.exists() and report_path.is_file(), "")
            check("crash: the memory snapshot runs on the recovered wave",
                  (report.get("memory_snapshot") or {}).get("written") is True,
                  report.get("memory_snapshot"))
    finally:
        wave_merge._ensure_wave_tag = original_tag

    # B. tag 之后、快照之前崩溃 → 下一次复用 tag 并补快照。
    try:
        with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-crash-snap-") as tmp:
            root = pathlib.Path(tmp)
            usine = make_repo(root)
            lineage = root / "lineage"
            (lineage / "memory").mkdir(parents=True)
            (lineage / "memory" / "notes.md").write_text("A\n", encoding="utf-8")
            make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
            progress_path = lineage / "waves/wave_001/merge_progress.json"
            report_path = lineage / "waves/wave_001/merge_report.json"

            wave_merge._snapshot_memory_into_repo = fail
            expect_raise("crash: the snapshot-step failure propagates",
                         wave_merge.merge_wave, str(lineage), 1,
                         config_for(usine))
            journal = json.loads(progress_path.read_text(encoding="utf-8"))
            check("crash: the journal records that the tag landed",
                  journal["status"] == "tagged"
                  and (journal.get("tag") or {}).get("tag") == "theatre/wave-1",
                  journal)
            check("crash: the tag exists before the snapshot is retried",
                  git_read(usine, "rev-parse",
                           "theatre/wave-1^{commit}").strip()
                  == journal["commits"][-1], "")

            wave_merge._snapshot_memory_into_repo = original_snapshot
            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            snap = report.get("memory_snapshot") or {}
            check("crash: the retry reuses the tag instead of making a new one",
                  report.get("resumed_from_progress") is True
                  and report.get("tag_created") is False
                  and report.get("tag_reused") is True, report.get("tag"))
            check("crash: the snapshot is completed on retry",
                  snap.get("written") is True, snap)
            check("crash: the journal is cleared after the snapshot retry",
                  not progress_path.exists() and report_path.is_file(), "")
    finally:
        wave_merge._snapshot_memory_into_repo = original_snapshot

    # C. 日志指向的提交不在当前历史里 → fail-closed，不许猜。
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-crash-bad-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
        progress_path = lineage / "waves/wave_001/merge_progress.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps({
            "schema_version": 1, "wave_index": 1, "unit_label": "wave",
            "base_commit": git_read(usine, "rev-parse", "HEAD").strip(),
            "commits": ["0" * 40], "status": "committing",
        }), encoding="utf-8")
        expect_raise("crash: a journal pointing at a missing commit fails closed",
                     wave_merge.merge_wave, str(lineage), 1,
                     config_for(usine))
        check("crash: the bad journal did not produce a report",
              not (lineage / "waves/wave_001/merge_report.json").exists(), "")

        base = {"schema_version": 1, "wave_index": 1, "unit_label": "wave",
                "base_commit": git_read(usine, "rev-parse", "HEAD").strip(),
                "commits": [], "status": "started"}
        progress_path.write_text(json.dumps(
            dict(base, tag_prefix="other/wave")), encoding="utf-8")
        expect_raise("crash: changing the tag prefix mid-wave fails closed",
                     wave_merge.merge_wave, str(lineage), 1,
                     config_for(usine))
        progress_path.write_text(json.dumps(
            dict(base, tag_prefix="theatre/wave", unit_label="drs")),
            encoding="utf-8")
        expect_raise("crash: a wave merge refuses a DRS journal",
                     wave_merge.merge_wave, str(lineage), 1,
                     config_for(usine))

        # 日志里记的是**另一波**的提交：tag 会打到错的 commit 上，必须拦住。
        git_read(usine, "-c", "user.name=smoke", "-c", "user.email=smoke@local",
                 "commit", "--allow-empty", "-m", "other wave", "-m",
                 "X-Theatre-Wave: 2\nX-Theatre-Project: p-other")
        other = git_read(usine, "rev-parse", "HEAD").strip()
        progress_path.write_text(json.dumps(
            dict(base, tag_prefix="theatre/wave", commits=[other])),
            encoding="utf-8")
        expect_raise("crash: a journal recording another wave's commit fails closed",
                     wave_merge.merge_wave, str(lineage), 1,
                     config_for(usine))

    # D. 提交已落、进度日志没来得及记：重跑按 trailer 从 git 历史反查。
    original_atomic = wave_merge._atomic_json
    try:
        with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-window-") as tmp:
            root = pathlib.Path(tmp)
            usine = make_repo(root)
            lineage = root / "lineage"
            make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
            make_episode(lineage, "ep002", 1, 2, "p-b", "PASS", BASE_FILES,
                         dict(BASE_FILES, **{"src/c.txt": b"B-SIDE\n"}))
            progress_path = lineage / "waves/wave_001/merge_progress.json"

            def flaky_atomic(path, payload):
                # 模拟「commit 返回之后、进度日志写之前」进程死掉：
                # 只跳过 status=committing 的日志写入，起点的日志仍落盘。
                if (str(path).endswith("merge_progress.json")
                        and payload.get("status") == "committing"):
                    return
                original_atomic(path, payload)

            wave_merge._atomic_json = flaky_atomic
            wave_merge._ensure_wave_tag = fail
            try:
                expect_raise("window: the tag-step failure propagates",
                             wave_merge.merge_wave, str(lineage), 1,
                             config_for(usine))
            finally:
                wave_merge._ensure_wave_tag = original_tag
                wave_merge._atomic_json = original_atomic
            journal = json.loads(progress_path.read_text(encoding="utf-8"))
            check("window: both commits landed but the journal has none",
                  journal["commits"] == [], journal)
            check("window: both commits are in git history",
                  git_read(usine, "rev-list", "--count", "HEAD").strip() == "3",
                  git_read(usine, "rev-list", "--count", "HEAD"))

            report = wave_merge.merge_wave(str(lineage), 1, config_for(usine))
            recovered = report.get("recovered_commits") or []
            check("window: the retry recovers both commits from history",
                  len(recovered) == 2 and len(report["commits"]) == 2
                  and report.get("commits_made_this_run") == 0, recovered)
            check("window: the recovered commits keep history order",
                  [item["project_index"] for item in recovered] == [1, 2]
                  and report["commits"]
                  == [item["commit"] for item in recovered], recovered)
            check("window: the tag points at the last recovered commit",
                  git_read(usine, "rev-parse",
                           "theatre/wave-1^{commit}").strip()
                  == report["commits"][-1], report["commits"])
            check("window: the journal is cleared after the report",
                  not progress_path.exists(), "")
    finally:
        wave_merge._atomic_json = original_atomic

    # E. 同一 wave/project 的重复提交分不清是哪一条 → fail-closed。
    with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-ambig-") as tmp:
        root = pathlib.Path(tmp)
        usine = make_repo(root)
        lineage = root / "lineage"
        make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                     dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
        base = git_read(usine, "rev-parse", "HEAD").strip()
        wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        # 抹掉报告，制造「需要从历史反查」的重跑场景。
        (lineage / "waves/wave_001/merge_report.json").unlink()
        (lineage / "waves/wave_001/merge_report.md").unlink()
        # 再加一条 trailer 完全相同的空提交：两条都能匹配，无法判断哪条是
        # 这一轮真正产出的。
        git_read(usine, "-c", "user.name=smoke", "-c", "user.email=smoke@local",
                 "commit", "--allow-empty", "-m",
                 "theatre(wave-1): accept ep001 (p-a) duplicate", "-m",
                 "X-Theatre-Wave: 1\nX-Theatre-Project: p-a")
        check("window: the duplicate commit was created",
              git_read(usine, "rev-list", "--count", "HEAD").strip() == "3",
              git_read(usine, "rev-list", "--count", "HEAD"))
        progress_path = lineage / "waves/wave_001/merge_progress.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps({
            "schema_version": 1, "wave_index": 1, "unit_label": "wave",
            "tag_prefix": "theatre/wave", "base_commit": base,
            "commits": [], "status": "committing",
        }), encoding="utf-8")
        try:
            wave_merge.merge_wave(str(lineage), 1, config_for(usine))
        except wave_merge.UsineMergeError as exc:
            ambiguous = "same wave/project trailers" in str(exc)
            detail = str(exc)
        except Exception as exc:  # noqa: BLE001
            ambiguous = False
            detail = f"wrong exception {type(exc).__name__}: {exc}"
        else:
            ambiguous = False
            detail = "recovery guessed among duplicate commits"
        check("window: duplicate trailer commits fail closed", ambiguous,
              detail[:240])


def test_merge_lock() -> None:
    """仓库级合并锁：跨进程互斥，且等锁期间报告出现后不许重复提交。

    两个 run root 同时把 wave 合进同一个仓库时，旧实现没有互斥：两边都通过
    前置检查、各自提交，提交/tag/快照会交错，账面还都能写出报告。锁放在 git
    common dir，用 OS 排他锁——进程崩溃时由内核释放，不会留下要人手清的
    stale lock。
    """
    saved_timeout = os.environ.get("RSIAGENT_MERGE_LOCK_TIMEOUT")
    try:
        # A. 直接锁：另一个进程持有时，等待超时报错并带上持有者信息。
        with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-lock-") as tmp:
            root = pathlib.Path(tmp)
            usine = make_repo(root)
            lineage = root / "lineage"
            lock_path = wave_merge._merge_lock_path(usine)
            check("lock: the lock lives in the git dir, not the worktree",
                  ".git" in lock_path.parts
                  and lock_path.name == "rsiagent-usine-merge.lock",
                  str(lock_path))

            env = dict(os.environ)
            env["PYTHONPATH"] = str(THEATRE) + os.pathsep + env.get("PYTHONPATH", "")
            env["RSIAGENT_MERGE_LOCK_TIMEOUT"] = "5"
            code = (
                "import sys, time\n"
                f"sys.path.insert(0, {str(HERE)!r})\n"
                "import wave_merge as W\n"
                "lock = W._acquire_merge_lock(sys.argv[1], "
                "__import__('pathlib').Path(sys.argv[2]), 1)\n"
                "print('locked', flush=True)\n"
                "time.sleep(3)\n"
                "lock.release()\n"
            )
            child = subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", code, str(usine), str(lineage)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=env)
            try:
                line = child.stdout.readline().strip()
                check("lock: the child process took the repository lock",
                      line == "locked", line or child.stderr.read()[:200])
                os.environ["RSIAGENT_MERGE_LOCK_TIMEOUT"] = "0.2"
                try:
                    wave_merge._acquire_merge_lock(usine, lineage, 1)
                except wave_merge.UsineMergeError as exc:
                    held = "holds the usine merge lock" in str(exc)
                    detail = str(exc)
                except Exception as exc:  # noqa: BLE001
                    held = False
                    detail = f"wrong exception {type(exc).__name__}: {exc}"
                else:
                    held = False
                    detail = "acquired a held lock"
                check("lock: a held lock times out with the holder's metadata",
                      held and "pid" in detail, detail[:240])
            finally:
                child.wait(timeout=15)
                if child.stdout:
                    child.stdout.close()
                if child.stderr:
                    child.stderr.close()
            os.environ["RSIAGENT_MERGE_LOCK_TIMEOUT"] = "1"
            lock = wave_merge._acquire_merge_lock(usine, lineage, 1)
            lock.release()
            check("lock: after the holder exits the lock is acquirable",
                  True, "")

            # 元数据写失败（磁盘满/权限）时必须**先释放锁**再抛错：否则长驻
            # 进程会一直持有 fd，后面所有合并都等这把锁。
            original_write = wave_merge._MergeLock._write_metadata
            leaked = None

            def broken_write(self):
                raise OSError("injected metadata failure")

            wave_merge._MergeLock._write_metadata = broken_write
            try:
                try:
                    leaked = wave_merge._acquire_merge_lock(usine, lineage, 1)
                except OSError as exc:
                    failed = "injected" in str(exc)
                else:
                    failed = False
            finally:
                wave_merge._MergeLock._write_metadata = original_write
                if leaked is not None:
                    leaked.release()
            os.environ["RSIAGENT_MERGE_LOCK_TIMEOUT"] = "0.5"
            probe = wave_merge._acquire_merge_lock(usine, lineage, 1)
            probe.release()
            check("lock: a metadata-write failure releases the lock", failed, "")

        # B. 两个真合并并发：一个提交，另一个等锁后看到报告，不重复提交。
        with tempfile.TemporaryDirectory(prefix="usine-wave-smoke-lock2-") as tmp:
            root = pathlib.Path(tmp)
            usine = make_repo(root)
            (usine / "slowgate.py").write_text(
                "import time\n"
                "time.sleep(1.5)\n"
                "open('gate-ran-marker', 'a').write('ran\\n')\n",
                encoding="utf-8")
            lineage = root / "lineage"
            make_episode(lineage, "ep001", 1, 1, "p-a", "PASS", BASE_FILES,
                         dict(BASE_FILES, **{"src/b.txt": b"A-SIDE\n"}))
            runner = root / "runner.py"
            runner.write_text(
                "import json, sys\n"
                f"sys.path.insert(0, {str(HERE)!r})\n"
                "import wave_merge as W\n"
                "spec = json.loads(sys.argv[1])\n"
                "cfg = W.UsineMergeConfig(usine_dir=spec['usine'], "
                "gate_argv=tuple(spec['gate']), memory_snapshot_dir='garage')\n"
                "r = W.merge_wave(spec['lineage'], 1, cfg)\n"
                "print(json.dumps({'skipped': r.get('skipped'), "
                "'commits': len(r.get('commits') or []), "
                "'tag': r.get('tag')}))\n",
                encoding="utf-8")
            spec = json.dumps({"usine": str(usine), "lineage": str(lineage),
                               "gate": [sys.executable, "slowgate.py"]})
            env = dict(os.environ)
            env["PYTHONPATH"] = str(THEATRE) + os.pathsep + env.get("PYTHONPATH", "")
            env["RSIAGENT_MERGE_LOCK_TIMEOUT"] = "20"
            first = subprocess.Popen(  # noqa: S603
                [sys.executable, str(runner), spec],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=env)
            lock_path = wave_merge._merge_lock_path(usine)
            deadline = time.monotonic() + 10
            while not lock_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            second = subprocess.Popen(  # noqa: S603
                [sys.executable, str(runner), spec],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=env)
            out_a, err_a = first.communicate(timeout=60)
            out_b, err_b = second.communicate(timeout=60)
            results = []
            for out, err in ((out_a, err_a), (out_b, err_b)):
                try:
                    results.append(json.loads(out.strip().splitlines()[-1]))
                except (IndexError, ValueError):
                    results.append({"error": (err or out)[-300:]})
            committed = [r for r in results
                         if not r.get("skipped") and r.get("commits") == 1]
            skipped = [r for r in results if r.get("skipped") == "report_exists"]
            check("lock: concurrent merges commit exactly once",
                  len(committed) == 1 and len(skipped) == 1, results)
            heads = git_read(usine, "rev-list", "--count", "HEAD").strip()
            tags = git_read(usine, "tag", "-l").split()
            check("lock: no duplicate commit or tag from the second merge",
                  heads == "2" and tags == ["theatre/wave-1"], (heads, tags))
    finally:
        if saved_timeout is None:
            os.environ.pop("RSIAGENT_MERGE_LOCK_TIMEOUT", None)
        else:
            os.environ["RSIAGENT_MERGE_LOCK_TIMEOUT"] = saved_timeout


def main() -> int:
    test_archives()
    test_merge_green()
    test_merge_exec_bits()
    test_merge_rejections()
    test_merge_serial()
    test_merge_policy_and_gate()
    test_merge_preconditions()
    test_sink_and_catchup()
    test_crlf_worktree_is_not_drift()
    test_drs_merge()
    test_drs_fail_and_plan()
    test_spec_sync_and_memory()
    test_health_and_l3_gates()
    test_collisions_and_snapshot_audit()
    test_crash_recovery()
    test_merge_lock()
    print()
    return summarise("smoke_wave_merge", list_failures=True)


if __name__ == "__main__":
    raise SystemExit(main())
