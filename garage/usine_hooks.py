"""usine corpus + publish-boundary hooks for the théâtre RSI loop.

Two host-side seam sets, both consumed by run_usine.py:

1.  Instruction corpus (self-built, ALE-style).  ``build_corpus`` writes the
    8-gram shingles of the run's instruction texts (the stock leakage unit
    from ``explore.commit``); the phase-1 orchestrator keeps that corpus
    FIXED for the whole run (stock Phase-1 feedback replays prior project
    texts verbatim into later Curriculum prompts, so growing the corpus
    mid-run would trip the prompt boundary at the next wave), while
    ``extend_corpus`` stays available for operator-driven append-only
    growth; ``UsineAudit`` mirrors the ALE audit surface
    (``validate``/``text``/``transcripts``/``captured``/``memory``) and
    ``hooks_for`` wires it into a stock ``PracticeHooks``.  ONE audit
    instance serves the whole multi-wave run: every funnel lazily adopts
    sanctioned growth (a superset reload, fingerprinted by
    ``(mtime_ns, size)``) while shrink, rewrite or corruption raise
    ``RuntimeError("usine instruction corpus drift")``; ``captured`` also
    skips the content audit of binary members (NUL in the first 8 KiB -
    the usine baseline ships a 32 MB zip and a 4.3 MB mp4, where word
    8-grams are pure cost with zero fence value; names stay audited).
    Within a wave, the authorized target direction is exempt through the
    stock ``authorized_instruction`` mechanism, exactly as in ALE/OSWorld.

2.  Publish-verb boundary (red line: live publishing never runs here).
    ``wrap_publish_blacklist`` facades a VM and refuses, BEFORE execution,
    model-authored programs that name live platform-publishing flows: the
    ``feuille publish`` CLI group (login/douyin/xhs/bilibili) and hand-rolled
    persistent-profile browser launches.  A refusal is a normal program
    outcome (exit 126 + an explanatory message), never an infra failure, so
    the model sees the boundary and adapts.  The structural backstop is the
    guest-home pin in guest_env.py: ``USERPROFILE`` (Windows) / ``HOME``
    (POSIX) resolves inside the
    sandbox disk, so live platform login profiles (``~/*_creator_profile``)
    do not exist for guest programs and every stock publish/login path stops
    at its own login wall.  Residuals (documented in ADAPTATION.md): the
    tripwire matches program text only, so merely quoting source that
    contains these names can trip it - the refusal message teaches the
    character-class workaround - and the harness-authored ``run_command``
    channel is intentionally unscanned (its commands legitimately carry
    project file names like ``packages/publish/src/xhs.ts``).

This module lazily imports ``explore.commit`` and ``explore.practice_loop``
(they pull the practice fence); the importing process must put the théâtre
root on ``sys.path`` first (run_usine.py and the smoke tests do).
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import time

log = logging.getLogger("rsiagent.usine.hooks")


# ------------------------------------------------------------------- corpus

def _shingles(text: str) -> set:
    """The stock 8-gram leakage unit (imported where the fence lives)."""
    from explore.commit import _shingles

    return _shingles(text)


def load_corpus(corpus_path) -> set:
    """Read and shape-check a usine instruction corpus (host-side ONLY)."""
    grams = json.loads(pathlib.Path(corpus_path).read_text(encoding="utf-8"))
    if (not isinstance(grams, list) or not grams
            or any(not isinstance(g, str) or not g for g in grams)):
        raise RuntimeError("usine instruction corpus is missing or malformed")
    return set(grams)


def build_corpus(corpus_path, texts) -> dict:
    """Write a fresh corpus: 8-gram shingles of all instruction texts.

    Host-side ONLY (grader-diagnostic class, same as the stock corpus): the
    shingle list must never enter any agent context.  An empty instruction
    set is rejected because an empty corpus silently disables the leakage
    tripwire that ``require_corpus=True`` audits depend on.
    """
    grams: set = set()
    for text in texts:
        grams |= _shingles(text)
    if not grams:
        raise RuntimeError("usine instruction corpus would be empty")
    pathlib.Path(corpus_path).write_text(
        json.dumps(sorted(grams)), encoding="utf-8")
    log.info("usine corpus built: %d shingles from %d text(s) -> %s",
             len(grams), len(texts), corpus_path)
    return {"benchmark": "usine", "shingles": len(grams)}


def extend_corpus(corpus_path, texts) -> dict:
    """Grow the corpus append-only (operator-driven; never inside a wave).

    Kept for ALE-style flows.  The phase-1 orchestrator never calls this
    mid-run: prior-wave project texts are replayed verbatim into later
    Curriculum prompts (stock feedback), so shingling them mid-run would
    trip the prompt boundary at the next wave's first authoring segment.
    Existing shingles are never removed: by construction the merged set is
    a superset of the file it replaces.
    """
    current = load_corpus(corpus_path)
    added: set = set()
    for text in texts:
        added |= _shingles(text) - current
    merged = current | added
    pathlib.Path(corpus_path).write_text(
        json.dumps(sorted(merged)), encoding="utf-8")
    log.info("usine corpus extended: +%d shingles -> %d total",
             len(added), len(merged))
    return {"benchmark": "usine", "added": len(added), "shingles": len(merged)}


class UsineAudit:
    """Host-only instruction-leakage audit for the usine RSI run.

    Mirrors the ALE ``Audit`` surface (benchmarks/ale/practice.py) minus the
    ALE-only benchmark-private-source and public-task binding checks: usine
    has no hidden grader constants, so the 8-gram instruction tripwire is
    the whole fence.

    One instance lives for the whole multi-wave run: the phase-1 corpus is
    fixed, so every funnel refreshes lazily (``_refresh``) and adopts
    superset growth (an operator-driven ``extend_corpus``) while refusing
    shrink, rewrite or corruption with ``RuntimeError("usine
    instruction corpus drift")``.  ``captured`` additionally skips the
    content audit of binary members (NUL within the first 8 KiB; the usine
    baseline ships a 32 MB zip and a 4.3 MB mp4, where word 8-grams are
    pure cost with zero fence value); member names stay audited either way.
    """

    def __init__(self, corpus_path):
        self.path = pathlib.Path(corpus_path)
        self.grams = load_corpus(self.path)
        self._fingerprint = self._stat_fingerprint()

    def _stat_fingerprint(self):
        stat = self.path.stat()
        return (stat.st_mtime_ns, stat.st_size)

    def _refresh(self):
        """Adopt sanctioned corpus growth; refuse anything else.

        Host-side only.  The ``(mtime_ns, size)`` fingerprint makes the
        steady state a no-op stat; a changed file is reloaded and accepted
        only as a superset - exactly and only what ``extend_corpus`` writes
        between waves.  Shrink, rewrite, corruption and deletion are drift.
        """
        try:
            fingerprint = self._stat_fingerprint()
        except OSError as exc:
            raise RuntimeError("usine instruction corpus drift") from exc
        if fingerprint == self._fingerprint:
            return
        grown = load_corpus(self.path)
        if not grown >= self.grams:
            raise RuntimeError("usine instruction corpus drift")
        if len(grown) != len(self.grams):
            log.info("usine audit adopted corpus growth: %d -> %d shingles",
                     len(self.grams), len(grown))
        self.grams = grown
        self._fingerprint = fingerprint

    def validate(self, path):
        if pathlib.Path(path).resolve() != self.path.resolve():
            raise RuntimeError("usine instruction corpus drift")
        self._refresh()
        return {"benchmark": "usine", "shingles": len(self.grams)}

    def text(self, text, mode="practice", authorized_instruction="", **kwargs):
        self._refresh()
        if not isinstance(text, str) or not text:
            return []
        allowed = (_shingles(authorized_instruction)
                   if authorized_instruction else set())
        suspect = (_shingles(text) & self.grams) - allowed
        if suspect:
            return [{"kind": "other-task-instruction",
                     "shingles": sorted(suspect)[:3]}]
        return []

    def transcripts(self, root, mode="practice",
                    authorized_instruction="", **kwargs):
        findings = []

        def inspect(value):
            if isinstance(value, str):
                findings.extend(
                    self.text(value, mode, authorized_instruction))
            elif isinstance(value, dict):
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        for path in pathlib.Path(root).rglob("transcript.json"):
            inspect(json.loads(path.read_text(encoding="utf-8")))
        return findings

    def captured(self, root, authorized_instruction=""):
        findings = []
        skipped_binary = 0
        import tarfile

        with tarfile.open(pathlib.Path(root) / "materials.tgz", "r:gz") as tf:
            for member in tf:
                findings.extend(self.text(
                    member.name, authorized_instruction=authorized_instruction))
                if member.isfile():
                    handle = tf.extractfile(member)
                    head = handle.read(8192)
                    if b"\x00" in head:
                        # Binary member (NUL within the first 8 KiB): word
                        # 8-grams over e.g. the 32 MB zip / 4.3 MB mp4 in
                        # the usine baseline are pure cost with zero fence
                        # value, so only the member name is audited.
                        skipped_binary += 1
                        continue
                    findings.extend(self.text(
                        (head + handle.read()).decode("utf-8", "ignore"),
                        authorized_instruction=authorized_instruction))
        if skipped_binary:
            log.info("usine audit skipped %d binary member(s) under %s "
                     "(names still audited)", skipped_binary, root)
        return findings

    def memory(self, files, corpus_path, reject_log,
               authorized_instruction="", require_corpus=False):
        self.validate(corpus_path)
        if require_corpus and not self.grams:
            raise RuntimeError(
                "target-aware memory audit requires a non-empty usine corpus")
        accepted = {}
        for rel, data in files.items():
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:                     # noqa: BLE001
                accepted[rel] = data
                continue
            hits = self.text(text, authorized_instruction=authorized_instruction)
            if hits:
                with open(reject_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "file": rel,
                        "hits": hits[0]["shingles"],
                        "ts": time.strftime("%H:%M:%S")}) + "\n")
                log.warning("usine audit rejected %s (instruction shingles)",
                            rel)
                continue
            accepted[rel] = data
        return accepted


def hooks_for(corpus_path):
    """PracticeHooks with the usine audit seams wired (everything else stock)."""
    from explore.practice_loop import PracticeHooks

    audit = UsineAudit(corpus_path)
    return PracticeHooks(
        validate_corpus=audit.validate,
        audit_text=audit.text,
        audit_transcripts=audit.transcripts,
        audit_captured=audit.captured,
        audit_memory=audit.memory,
    )


# ------------------------------------------------------- publish boundary

# Execution-shaped patterns only.  A bare "publish" would false-positive on
# the project's own file names (packages/publish/src/xhs.ts in tar lists and
# grep output), so the CLI pattern requires the exact "feuille <whitespace>
# publish" command spelling - a path slash does not match - and the launch
# pattern names the one Playwright call that reaches persistent login
# profiles.  Running the offline gate stays clean: the gate is "pnpm verify"
# now (no "feuille publish" spelling anywhere).
_PUBLISH_BOUNDARY_PATTERNS = (
    ("publish-cli", re.compile(r"\bfeuille\s+publish\b")),
    ("persistent-profile-launch", re.compile(r"\blaunch_persistent_context\b")),
)

PUBLISH_BOUNDARY_EXIT_CODE = 126


def scan_publish_boundary(code) -> list:
    """Return (pattern-name, matched-text) hits for one program's source."""
    hits = []
    for name, pattern in _PUBLISH_BOUNDARY_PATTERNS:
        match = pattern.search(code or "")
        if match:
            hits.append((name, match.group(0)))
    return hits


def _publish_refusal(hits) -> str:
    evidence = "\n".join(
        f"  - {name}: matched {snippet!r}" for name, snippet in hits)
    return (
        "[PUBLISH BOUNDARY - this program was refused before execution]\n"
        "\n"
        "This program names a live platform-publishing flow. Live platform\n"
        "operations never execute in this environment: no publishing, no\n"
        "login, no platform profile or cookie access. Matched names:\n"
        "\n"
        f"{evidence}\n"
        "\n"
        "What this means for your work:\n"
        "- Platform login profiles do not resolve inside this environment,\n"
        "  so every stock publish or login path would stop at its own login\n"
        "  wall; there is nothing real to test against here.\n"
        "- Develop and test publish code offline only, exactly like the\n"
        "  publish vitest suite (packages/publish/test/publish.test.ts):\n"
        "  mock pages over file:// URLs with a throwaway profile directory,\n"
        "  never a real platform domain.\n"
        "- The refusal is textual: if you were only inspecting or quoting\n"
        "  source that merely mentions these names, avoid the exact literal\n"
        "  spelling in your next command (for example a character class like\n"
        "  'feuille[ ]publish'). Do not echo this refusal verbatim into a\n"
        "  later program - it would trip the same boundary again.\n"
    )


class PublishBlacklistVM:
    """VM facade refusing model-authored programs that name live publishing.

    Only ``run_script`` (the model-authored program channel: Actor programs
    and Verifier programs) is scanned.  ``run_command`` and every other
    attribute pass through untouched - those are harness-authored channels
    whose commands legitimately carry project file names.  A refusal is a
    normal program trace (exit 126, explanatory stdout, ``infra_fail``
    False): the boundary is evidence for the model, not a transport fault.
    """

    def __init__(self, vm):
        self._vm = vm

    def run_script(self, lang, code, *args, **kwargs):
        hits = scan_publish_boundary(code)
        if hits:
            log.warning("publish boundary refused a %s program: %s",
                        lang, ", ".join(name for name, _ in hits))
            from env.vm import Trace

            return Trace(
                stdout=_publish_refusal(hits)
                + f"\n[exit {PUBLISH_BOUNDARY_EXIT_CODE}]",
                exit_code=PUBLISH_BOUNDARY_EXIT_CODE,
                secs=0.0,
                timed_out=False,
                infra_fail=False,
                context_stdout=None)
        return self._vm.run_script(lang, code, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._vm, name)


def wrap_publish_blacklist(vm):
    """Facade one VM instance (both Actor and Verifier programs cross it)."""
    return PublishBlacklistVM(vm)


def publish_blacklist_vm_factory(inner_factory):
    """Compose the boundary into a vm_factory for evolve_parallel_phase1.

    The factory contract is ``(desktop, vm)``: the desktop (WorktreeEnv,
    owning the subst drive and execute server) passes through unchanged and
    only the VM gets the boundary facade, so phase1_wave's close() lifecycle
    and harness channels stay stock.
    """

    def factory():
        desktop, vm = inner_factory()
        return desktop, wrap_publish_blacklist(vm)

    return factory


__all__ = [
    "PUBLISH_BOUNDARY_EXIT_CODE",
    "PublishBlacklistVM",
    "UsineAudit",
    "build_corpus",
    "extend_corpus",
    "hooks_for",
    "load_corpus",
    "publish_blacklist_vm_factory",
    "scan_publish_boundary",
    "wrap_publish_blacklist",
]
