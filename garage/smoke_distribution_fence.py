"""Smoke test for run_usine's distribution fence (host-side only).

Four sections:

  A. the real distribution clears the real fence: every audited surface is
     enumerated (seeded usine tracked text + rewritten capture member names,
     the first-party prompt/infra packages, the adapter directory, the five
     role configs) and the result carries honest counts
  B. planted collisions raise fail-closed naming the right surface label:
     a seeded usine file's own 8-gram, a transport-note 8-gram (adapter
     code), a core/actor.py 8-gram (stock prompt template)
  C. a CJK-only distribution raises the empty-shingle error (the
     [a-z0-9]+ tokenizer yields zero shingles from CJK text, which would
     silently disable the leakage fence)
  D. unit control: a runtime-assembled 7-word transport-note echo stays
     clean - the stock leakage unit is 8 words, and span-grams across the
     fresh prefix words do not exist in the note

Planted texts are assembled at runtime, never quoted as literals: this
smoke file is itself an adapter fence source, so a verbatim quote would
collide with its own planted distribution (fine for the must-raise cases,
fatal for the must-clear control).

Usage (théâtre venv; keep child argv ASCII on PowerShell 5.1):
    cd D:\\coding\\personal\\explorateur\\théâtre
    .\\.venv\\Scripts\\python.exe ..\\garage\\smoke_distribution_fence.py
"""

from __future__ import annotations

import re
import sys
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

import run_usine    # noqa: E402
import usine_hooks  # noqa: E402

DISTRIBUTION = (HERE / "distribution-usine.md").read_text(
    encoding="utf-8").strip()
USINE_DIR = EXPLORATEUR / "usine"

RESULTS: list = []


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


def _fresh_stats() -> dict:
    return {"usine_binary_skipped": 0, "theatre_py": 0,
            "adapter_py": 0, "role_yaml": 0}


# ------------------------------------------------- A: the real distribution

def test_real_distribution() -> str | None:
    """Clear the real fence; also collect one seeded usine 8-gram to plant."""
    seeded_shingle = None
    try:
        fence = run_usine._check_distribution_fences(
            DISTRIBUTION, THEATRE, USINE_DIR)
        check("fence: the real distribution clears every audited surface",
              fence["status"] == "clear"
              and fence["distribution_shingles"] > 0
              and fence["audited_sources"] == (
                  2 * fence["usine_tracked"]
                  - fence["usine_binary_skipped"]
                  + fence["theatre_py"] + fence["adapter_py"]
                  + fence["role_yaml"]),
              fence)
        check("fence: honest counts (tracked usine, first-party, roles)",
              fence["usine_tracked"] > 10
              and fence["theatre_py"] > 30
              and fence["adapter_py"] >= 5
              and fence["role_yaml"] == 5,
              fence)
        info("fence: binary members skipped by content cost",
             f"{fence['usine_binary_skipped']} of {fence['usine_tracked']} "
             "tracked usine file(s) (names still fenced)")
    except RuntimeError as exc:
        check("fence: the real distribution clears every audited surface",
              False, exc)

    labels: set = set()
    stats = _fresh_stats()
    for label, text in run_usine._fence_texts(THEATRE, USINE_DIR, stats):
        labels.add(label)
        if seeded_shingle is None and label == "usine:seeded-text":
            grams = usine_hooks._shingles(text)
            if grams:
                seeded_shingle = sorted(grams)[0]
    check("fence: rewritten capture member names are fenced as text",
          "usine:capture-name" in labels, sorted(labels))
    check("fence: every first-party package is fenced",
          {"theatre:explore", "theatre:core", "theatre:env",
           "theatre:config", "theatre:llm"} <= labels, sorted(labels))
    check("fence: adapter code and role configs are fenced",
          {"adapter:code", "adapter:role-config"} <= labels, sorted(labels))
    check("fence: the seeded-gram probe found a planted candidate",
          seeded_shingle is not None, "no seeded usine text yielded shingles")
    return seeded_shingle


# ------------------------------------------------ B: planted collisions hit

def test_planted_collisions_raise(seeded_shingle: str | None) -> None:
    cases = []
    if seeded_shingle:
        cases.append(("usine:seeded-text",
                      "echo this verbatim from the baseline: "
                      + seeded_shingle))
    note_grams = sorted(usine_hooks._shingles(
        run_usine._USINE_TRANSPORT_NOTE))
    cases.append(("adapter:code",
                  "plant transport words: " + note_grams[0]))
    actor_grams = sorted(usine_hooks._shingles(
        (THEATRE / "core" / "actor.py").read_text(encoding="utf-8")))
    cases.append(("theatre:core", "plant system words: " + actor_grams[0]))
    for label, planted in cases:
        try:
            run_usine._check_distribution_fences(
                planted, THEATRE, USINE_DIR)
            check(f"fence: planted {label} collision raises",
                  False, "no exception")
        except RuntimeError as exc:
            check(f"fence: planted {label} collision raises",
                  "shares" in str(exc) and label in str(exc), exc)


# --------------------------------------------- C: CJK-only distribution

def test_cjk_distribution_rejected() -> None:
    planted = "这是一段纯中文的目标方向描述，用来验证分词器对中日韩文本零产出。"
    try:
        run_usine._check_distribution_fences(planted, THEATRE, USINE_DIR)
        check("fence: a CJK-only distribution raises", False, "no exception")
    except RuntimeError as exc:
        check("fence: a CJK-only distribution raises",
              "no word 8-grams" in str(exc), exc)


# ------------------------------------------- D: unit control (7-word echo)

def test_seven_word_echo_stays_clean() -> None:
    words = re.findall(r"[a-z0-9]+",
                       run_usine._USINE_TRANSPORT_NOTE.lower())
    note_grams = usine_hooks._shingles(run_usine._USINE_TRANSPORT_NOTE)
    planted = None
    for index in range(len(words) - 6):
        window = " ".join(words[index:index + 7])
        candidate = "echo now: " + window
        if not (usine_hooks._shingles(candidate) & note_grams):
            planted = candidate
            break
    check("fence: a clean 7-word note window was assembled",
          planted is not None, "every window collided (impossible?)")
    if planted is None:
        return
    try:
        fence = run_usine._check_distribution_fences(
            planted, THEATRE, USINE_DIR)
        check("fence: a 7-word echo stays clean (the unit is 8 words)",
              fence["status"] == "clear"
              and fence["distribution_shingles"] > 0, fence)
    except RuntimeError as exc:
        check("fence: a 7-word echo stays clean (the unit is 8 words)",
              False, exc)


def main() -> int:
    seeded_shingle = test_real_distribution()
    test_planted_collisions_raise(seeded_shingle)
    test_cjk_distribution_rejected()
    test_seven_word_echo_stays_clean()
    passes = sum(1 for status, _, _ in RESULTS if status == "PASS")
    fails = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    print(f"\n=== SMOKE distribution fence: {passes} PASS / {fails} FAIL "
          f"/ {len(RESULTS)} total")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
