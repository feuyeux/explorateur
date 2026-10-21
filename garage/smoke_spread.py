"""Smoke test for the spread gate (铺开闸) — the mechanical anti-local-optimum.

Why this smoke exists
---------------------
Three merged RSI waves have landed in the repository, and all three of them
landed in ``packages/dsh-plugin`` (the same function, the same four refusal
branches).  The production line itself — core, karaoke, poster, poetry,
storyteller, copy, bgm, publish — has zero merged changes.  That was not an
Agent being lazy: the Phase-1 curriculum seat's own brief said "in menu target
A, B or C ONLY", and the distribution file's "spread a wave across different
areas" sentence had no mechanical constraint behind it.

The spread gate is that sentence, made mechanical.  This smoke pins the five
things it must do, offline and without spending a token:

  A. the packages touched by an RSI-merged commit are extracted from the git
     history (the trailer ``X-Theatre-Wave`` / ``X-Theatre-Drs`` is the
     discriminator, not the subject line)
  B. two consecutive waves in the same package BAN that package for the next
     wave, and one wave elsewhere releases the ban
  C. the cold list is the never-touched packages, ordered by production-line
     importance
  D. with no RSI history at all the gate degrades gracefully: no constraint
     text, no crash
  E. the assembled curriculum seat really carries the ban and the cold list,
     and the Phase-1 brief no longer pins the seat to menu targets A, B or C

Usage (théâtre venv):
    cd <explorateur>\\théâtre
    Windows: .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_spread.py
    POSIX:   .venv/theatre-mac/bin/python ../garage/smoke_spread.py

Exits 0 when every section passes.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]

PASSED = 0

# The production line's packages, in the order the gate must print them.
# This mirrors config/spread.json's package_priority; the gate also reads it
# from there, and the smoke asserts the two agree.
PACKAGE_ORDER = [
    "core", "karaoke", "poster", "poetry", "storyteller",
    "copy", "bgm", "publish", "cli", "gate", "dsh-plugin",
]


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Assert one thing.  Raises SystemExit on failure."""
    global PASSED
    if not ok:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        raise SystemExit(1)
    PASSED += 1
    print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
    return True


def info(name: str, detail: str) -> None:
    print(f"INFO  {name} — {detail}")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise SystemExit(
            "git " + " ".join(args) + " failed in " + str(repo) + ": "
            + proc.stderr.decode("utf-8", "replace")[:400])
    return proc.stdout.decode("utf-8", "replace").strip()


def _commit(repo: Path, message: str, files: dict) -> str:
    """Write files, commit them with ``message``, return the new sha."""
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=spread smoke",
         "-c", "user.email=spread-smoke@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _wave_message(index: int, label: str = "Wave") -> str:
    return (f"theatre({label.lower()}-{index}): accept ep001 (smoke)\n"
            "\n"
            f"Candidate ep001 merged from {label.lower()} {index} "
            "(verifier PASS, usine gate green).\n"
            "\n"
            f"X-Theatre-{label}: {index}\n"
            "X-Theatre-Project: smoke\n")


def _new_repo(root: Path, packages: list) -> Path:
    """A fresh git repo with the given packages as tracked directories."""
    repo = root / "tree"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    for name in packages:
        package = repo / "packages" / name
        package.mkdir(parents=True, exist_ok=True)
        (package / "package.json").write_text(
            '{"name": "%s"}\n' % name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=spread smoke",
         "-c", "user.email=spread-smoke@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-q", "-m", "seed tree")
    return repo


# --------------------------------------------------- A: packages from history

def test_history_extracts_packages(spread) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-spread-smoke-a-") as tmp:
        repo = _new_repo(Path(tmp), PACKAGE_ORDER)
        sha = _commit(repo, _wave_message(1), {
            "packages/dsh-plugin/src/tools.ts": "export const x = 1;\n",
            "packages/dsh-plugin/test/plugin.test.ts": "test\n",
        })
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        check("history: exactly one RSI commit is recognised",
              state["history_commits"] == 1, str(state["history_commits"]))
        entry = state["recent"][0]
        check("history: the unit name comes from the trailer",
              entry["unit"] == "wave-1", entry["unit"])
        check("history: the commit sha is recorded",
              entry["commit"] == sha, entry["commit"])
        check("history: the touched package is extracted",
              entry["packages"] == ["dsh-plugin"], str(entry["packages"]))
        check("history: touched_counts counts the package",
              state["touched_counts"] == {"dsh-plugin": 1},
              str(state["touched_counts"]))
        # A commit WITHOUT the trailer is not an RSI merge and must be ignored.
        _commit(repo, "chore(usine): ordinary work\n", {
            "packages/core/src/index.ts": "export const y = 2;\n"})
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        check("history: a commit without the trailer is not an RSI merge",
              state["history_commits"] == 1, str(state["history_commits"]))
        # A DRS commit carries its own trailer and its own unit name.
        # 顶层文件的夹具名是**中性的**：这里只验「顶层文件被归成 other」，
        # 用一个像真报告的名字会留下 `WORDING_CHANGE_REPORT.md` 这种假产物
        # （曾经真的留下过，被当成真报告入库了一次）。
        _commit(repo, _wave_message(1, "Drs"), {
            "packages/karaoke/src/index.ts": "export const z = 3;\n",
            "NOTES.md": "one line\n",
            "skills/video-generation/SKILL.md": "howto\n",
        })
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        units = [entry["unit"] for entry in state["recent"]]
        check("history: the DRS trailer is recognised as its own unit",
              units == ["drs-1", "wave-1"], str(units))
        drs_packages = state["recent"][0]["packages"]
        check("history: a package path, a top-level file and a skill are "
              "classified apart",
              "karaoke" in drs_packages and "other" in drs_packages
              and "skills" in drs_packages, str(drs_packages))
        check("history: reading the history does not touch the working tree",
              _git(repo, "status", "--porcelain") == "",
              _git(repo, "status", "--porcelain"))


# --------------------------------------------- B: repeat ban and its release

def test_repeat_ban(spread) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-spread-smoke-b-") as tmp:
        repo = _new_repo(Path(tmp), PACKAGE_ORDER)
        _commit(repo, _wave_message(1), {
            "packages/dsh-plugin/src/tools.ts": "export const x = 1;\n"})
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        check("ban: one wave in a package does not ban it yet",
              state["banned"] == [], str(state["banned"]))
        _commit(repo, _wave_message(2), {
            "packages/dsh-plugin/src/tools.ts": "export const x = 2;\n"})
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        check("ban: two consecutive waves in one package ban it",
              state["banned"] == ["dsh-plugin"], str(state["banned"]))
        check("ban: the streak is counted from the newest wave backwards",
              state["streaks"].get("dsh-plugin") == 2,
              str(state["streaks"]))
        _commit(repo, _wave_message(3), {
            "packages/core/src/index.ts": "export const y = 1;\n"})
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        check("ban: a wave elsewhere releases the ban",
              state["banned"] == [], str(state["banned"]))
        check("ban: the released package is now the one that is warm",
              state["streaks"].get("core") == 1
              and state["streaks"].get("dsh-plugin") == 0,
              str(state["streaks"]))


# ------------------------------------------------------ C: the cold list order

def test_cold_list(spread) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-spread-smoke-c-") as tmp:
        repo = _new_repo(Path(tmp), PACKAGE_ORDER)
        _commit(repo, _wave_message(1), {
            "packages/dsh-plugin/src/tools.ts": "export const x = 1;\n"})
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        expected = [name for name in PACKAGE_ORDER if name != "dsh-plugin"]
        check("cold: the never-touched packages are listed",
              state["cold"] == expected, str(state["cold"]))
        check("cold: the order is the production-line importance order",
              state["cold"] == sorted(
                  state["cold"],
                  key=lambda name: PACKAGE_ORDER.index(name)),
              str(state["cold"]))
        check("cold: the already-touched package is not cold",
              "dsh-plugin" not in state["cold"], str(state["cold"]))
        check("cold: the core package is the first cold target",
              state["cold"][0] == "core", str(state["cold"][:3]))


# ------------------------------------------------- D: graceful degradation

def test_no_history_degrades(spread) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-spread-smoke-d-") as tmp:
        repo = _new_repo(Path(tmp), PACKAGE_ORDER)
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        check("degrade: an empty history is not an error",
              state["history_error"] == "", state["history_error"])
        check("degrade: no RSI commit means no constraint text",
              spread.render_constraint(state, spread.SpreadConfig()) == "",
              "constraint text was produced")
        seat = _Seat("existing brief")
        result = spread.apply_to_seat(seat, state, spread.SpreadConfig())
        check("degrade: the seat is left untouched",
              not result["applied"] and seat.system_extra == "existing brief",
              str(result))
        # A repository that is not a git repository at all must degrade too.
        plain = Path(tmp) / "not-a-repo"
        (plain / "packages" / "core").mkdir(parents=True)
        broken = spread.build_spread_state(plain, spread.SpreadConfig())
        check("degrade: a non-git directory is reported, not crashed on",
              bool(broken["history_error"]), str(broken["history_error"]))
        check("degrade: a broken history still yields a usable state",
              broken["recent"] == [] and isinstance(broken["cold"], list),
              str(broken.get("recent")))


# ------------------------------------------- E: the seat really carries it

class _Seat:
    """A stand-in for the loaded role config dataclass."""

    def __init__(self, system_extra: str = ""):
        self.system_extra = system_extra


def test_seat_assembly(spread, run_usine) -> None:
    with tempfile.TemporaryDirectory(prefix="usine-spread-smoke-e-") as tmp:
        repo = _new_repo(Path(tmp), PACKAGE_ORDER)
        _commit(repo, _wave_message(1), {
            "packages/dsh-plugin/src/tools.ts": "export const x = 1;\n"})
        _commit(repo, _wave_message(2), {
            "packages/dsh-plugin/src/tools.ts": "export const x = 2;\n"})
        state = spread.build_spread_state(repo, spread.SpreadConfig())
        seat = _Seat("ORIGINAL BRIEF")
        configs = {"curriculum": seat, "curriculum_drs": _Seat("DRS BRIEF")}
        result = run_usine._apply_spread_constraint(
            configs, phase="1", state=state, config=spread.SpreadConfig())
        check("assembly: the constraint is applied to the Phase-1 seat",
              result["applied"], str(result))
        text = seat.system_extra
        check("assembly: the original brief is preserved",
              text.startswith("ORIGINAL BRIEF"), text[:60])
        check("assembly: the ban names the banned package",
              "BANNED FOR THIS WAVE: packages/dsh-plugin" in text,
              "the ban clause names packages/dsh-plugin")
        check("assembly: the cold list is in the seat's brief",
              "packages/core" in text and "packages/karaoke" in text,
              "the cold clause names packages/core and packages/karaoke")
        check("assembly: the DRS seat is never touched",
              configs["curriculum_drs"].system_extra == "DRS BRIEF",
              configs["curriculum_drs"].system_extra)
        # Phase 2 swaps the seat (see _select_phase_seats): the DRS brief must
        # not receive the breadth gate.
        phase2 = {"curriculum": configs["curriculum_drs"],
                  "curriculum_drs": configs["curriculum_drs"]}
        result2 = run_usine._apply_spread_constraint(
            phase2, phase="2", state=state, config=spread.SpreadConfig())
        check("assembly: phase 2 leaves the DRS seat alone",
              not result2["applied"]
              and phase2["curriculum"].system_extra == "DRS BRIEF",
              str(result2))
        # The brief is a closed set: it must not leave an open-ended tail.
        check("assembly: the constraint carries no open-set wording",
              "and others" not in text and "any other" not in text
              and "every other" not in text, "open-set wording found")


# ------------------------------------------------- F: the real tree and brief

def test_real_tree(spread, run_usine) -> None:
    config = spread.load_config()
    check("config: the shipped policy loads",
          config.cold_window == 3 and config.repeat_ban == 2
          and config.cold_priority == "required", str(config.to_dict()))
    check("config: the shipped priority list matches the smoke's order",
          list(config.package_priority) == PACKAGE_ORDER,
          str(config.package_priority))
    check("config: the policy file is really the one that was read",
          config.source.endswith("spread.json"), config.source)
    broken = spread.load_config(HERE / "config" / "does-not-exist.json")
    check("config: a missing policy file falls back to the built-in defaults",
          broken.source == "builtin_defaults" and broken.repeat_ban == 2,
          broken.source)

    usine = EXPLORATEUR / "usine"
    if not (usine / "packages").is_dir():
        info("real tree: the usine tree is not here; skipped")
        return
    state = spread.build_spread_state(usine, config)
    check("real tree: the history is readable and the RSI merges are found",
          state["history_commits"] >= 1, str(state["history_commits"]))
    check("real tree: the already-worked package is not cold",
          "dsh-plugin" not in state["cold"], str(state["cold"]))
    check("real tree: the cold list is ordered by importance",
          state["cold"] == sorted(
              state["cold"], key=lambda name: config.package_priority.index(name)
              if name in config.package_priority else len(config.package_priority)),
          str(state["cold"]))
    info("real tree: cold packages", ", ".join(state["cold"]) or "(none)")
    info("real tree: banned this wave", ", ".join(state["banned"]) or "(none)")
    info("real tree: touched counts", str(state["touched_counts"]))

    brief = (HERE / "config" / "roles-usine"
             / "curriculum-usine.yaml").read_text(encoding="utf-8")
    check("brief: the menu-target lock is gone from the Phase-1 seat",
          "A, B or C ONLY" not in brief,
          "the menu-target lock is gone from the Phase-1 brief")
    check("brief: the Phase-1 seat defers to the spread gate",
          "SPREAD GATE" in brief, "the Phase-1 brief names the spread gate as the target decider")
    drs_brief = (HERE / "config" / "roles-usine"
                 / "curriculum-drs.yaml").read_text(encoding="utf-8")
    check("brief: the DRS seat is untouched by this work",
          "SPREAD GATE" not in drs_brief
          and "THE DRILL HAS A HARD UPPER BOUND" in drs_brief,
          "the DRS brief still carries its own bound and no spread clause")


def main() -> int:
    if shutil.which("git") is None:
        print("FAIL  git is not on PATH — the spread gate reads the git history")
        return 1
    spread = _load("smoke_spread_module", HERE / "spread.py")
    run_usine = _load("smoke_run_usine_module", HERE / "run_usine.py")
    test_history_extracts_packages(spread)
    test_repeat_ban(spread)
    test_cold_list(spread)
    test_no_history_degrades(spread)
    test_seat_assembly(spread, run_usine)
    test_real_tree(spread, run_usine)
    print(f"\nALL {PASSED} SPREAD GATE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
