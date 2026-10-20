"""Smoke test for the memory seed: the next wave must stand on what the last one learned.

The claim under test is the one that makes "run it again and it gets better"
mean anything: **the second run starts from the first run's memory**, not
from zero.  That claim has one linchpin — the engine reads the run's
``memory/`` directory as its starting tree, so seeding that directory is
the whole mechanism, with no engine change involved.

Sections:

  A. the seed reaches the engine's own reader: ``_install_seed_memory`` puts
     the records where ``explore.practice_loop._read_memory_tree`` looks, and
     that reader returns exactly them
  B. the seed is a COPY: the source tree stays authoritative and re-readable
     (Phase 1's manifest and tree hash are measured against it), and the
     destination is a plain copy rather than a link or a move
  C. the guardrails: an empty or missing seed directory is refused before a
     single token is spent, and --merge-drs is refused on Phase 1

Usage (théâtre venv):
    cd D:\\coding\\personal\\explorateur\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_memory_seed.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPLORATEUR = HERE.parents[0]
sys.path.insert(0, str(HERE))


def _find_theatre() -> Path:
    for candidate in sorted(EXPLORATEUR.iterdir()):
        if ((candidate / "env" / "vm.py").is_file()
                and (candidate / "explore" / "practice_loop.py").is_file()):
            return candidate
    raise SystemExit("the théâtre checkout (env/vm.py + explore/practice_loop.py) "
                     "was not found under " + str(EXPLORATEUR))


THEATRE = _find_theatre()
sys.path.insert(0, str(THEATRE))

import run_usine  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, ok, detail: str = "") -> None:
    RESULTS.append(("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:400]))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" | {detail}"))


def expect_raise(name: str, callable_, *args, **kwargs) -> None:
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        check(name, True, f"{type(exc).__name__}: {str(exc)[:120]}")
    else:
        check(name, False, "no exception")


SEED = {
    "environment-quirks.md": b"# environment quirks\n\n- guest reset drops the seed\n",
    "usine-monorepo.md": b"# usine monorepo\n\n- publish lives in index.ts\n",
    "verification-discipline.md": b"# verification discipline\n\n- probes classify first\n",
}


def _seed_dir(root: pathlib.Path, files: dict = SEED) -> pathlib.Path:
    source = root / "seed"
    source.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (source / name).write_bytes(data)
    return source


# ------------------------------------------------- A: the seed reaches the engine

def test_engine_reads_the_seed() -> None:
    from explore.practice_loop import _read_memory_tree

    with tempfile.TemporaryDirectory(prefix="usine-seed-a-") as tmp:
        root = pathlib.Path(tmp)
        source = _seed_dir(root)
        destination = root / "run" / "memory"
        installed = run_usine._install_seed_memory(source, destination)

        tree = _read_memory_tree(str(destination))
        check("seed: the engine's reader sees exactly the seeded records",
              installed == len(SEED)
              and tree == SEED, (installed, sorted(tree)))
        check("seed: the reader reports the same bytes the seed holds",
              all(tree[name] == data for name, data in SEED.items())
              and len(tree) == len(SEED), sorted(tree))


# --------------------------------------------------------- B: the seed is a copy

def test_seed_is_a_copy() -> None:
    with tempfile.TemporaryDirectory(prefix="usine-seed-b-") as tmp:
        root = pathlib.Path(tmp)
        source = _seed_dir(root)
        destination = root / "run" / "memory"
        run_usine._install_seed_memory(source, destination)

        (destination / "usine-monorepo.md").write_bytes(b"rewritten\n")
        check("seed: the source tree is untouched by the destination",
              (source / "usine-monorepo.md").read_bytes()
              == SEED["usine-monorepo.md"],
              (source / "usine-monorepo.md").read_bytes())
        check("seed: the destination is a plain file, not a link",
              not (destination / "usine-monorepo.md").is_symlink()
              and (source / "usine-monorepo.md").is_file(),
              "symlink")

        # Re-seeding replaces the destination rather than merging into it —
        # a stale record from a previous seed must not survive.
        stale = destination / "stale.md"
        stale.write_bytes(b"stale\n")
        run_usine._install_seed_memory(source, destination)
        check("seed: re-seeding replaces the tree instead of merging into it",
              not stale.exists()
              and sorted(p.name for p in destination.iterdir()) == sorted(SEED),
              sorted(p.name for p in destination.iterdir()))

        info = run_usine._inspect_memory_seed(source)
        check("seed: the inspection reports the tree honestly",
              info["files"] == len(SEED)
              and info["bytes"] == sum(len(data) for data in SEED.values())
              and sorted(info["names"]) == sorted(SEED), info)


# ------------------------------------------------------------- C: the guardrails

def test_guardrails() -> None:
    base = ["--run-name", "smoke-seed", "--phase", "1", "--project-budget", "1",
            "--max-parallel", "1", "--gate-argv", "pnpm", "verify", "--preflight"]
    with tempfile.TemporaryDirectory(prefix="usine-seed-c-") as tmp:
        root = pathlib.Path(tmp)
        empty = root / "empty"
        empty.mkdir()
        expect_raise("guard: an empty seed directory is refused",
                     run_usine.main, base + ["--memory-seed", str(empty)])
        expect_raise("guard: a missing seed directory is refused",
                     run_usine.main, base + ["--memory-seed", str(root / "nope")])
        expect_raise("guard: --merge-drs is refused on Phase 1",
                     run_usine.main, base + ["--merge-drs"])


def main() -> int:
    test_engine_reads_the_seed()
    test_seed_is_a_copy()
    test_guardrails()
    passed = sum(1 for status, _, _ in RESULTS if status == "PASS")
    failed = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    print(f"\nsmoke_memory_seed: {passed} PASS / {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
