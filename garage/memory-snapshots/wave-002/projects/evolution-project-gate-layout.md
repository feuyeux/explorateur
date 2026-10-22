# Project: evolution_project — packages/gate (layout placement gate) + root locator fix

Status: PASS, generation 1, verified. Two waves touched this same gate; wave 2 is the fix wave 1 reported.

## The tree as observed
- Repo root `~/evolution_project` **is** the pnpm workspace root: `pnpm-workspace.yaml` (`packages/*`) and
  `ownership.json` sit there, next to `AGENTS.md`, `docs/`, `skills/`, `lessons/`, `personas/`, `themes/`,
  `tools/`, `packages/`, `node_modules`, `build`. Home is `~` = `.memory, bin, evolution_project, work` — note
  those sibling names, they are exactly what a one-level-too-high locator reports as violations, and `~/.git`
  does **not** exist (so a parent level is not a repo root here).
- `packages/gate/package.json` exists (`@feuille/gate`, private, no dependencies) but the package originally had
  **no `src/` at all**: the gate was two vitest files — `test/layout.test.ts` (placement) and
  `test/skills.test.ts` (skills + `ownership.json` three-way reconciliation, ~4 tests, walks
  `packages/*/src/**` for module IDs, excludes `index.ts` and `*.d.ts`).
  reconciliation, ~4 tests, walks `packages/*/src/**` for module IDs, excludes `index.ts` and `*.d.ts`).
- Allowed-entry policy (unchanged by the fix, now exported from `src/index.ts`):
  workspace level = `packages skills examples docs languages personas themes lessons tools node_modules build`;
  repo-root level = `usine garage garage-ii theatre-ii théâtre config docs`. Dot-dirs are always skipped.
  `build/` is whitelisted *only* as publish-test run evidence — pin that distinction, don't drop it.

## Wave 1 vs wave 2 (same defect, two roles)
- Wave 1 (foodnames five-defect project) ran `pnpm verify`, saw
  `仓库根没有第三处放内容的地方` flagging `AppData/ bin/ evolution_project/ work`, proved it pre-existing
  (mtimes, isolation, names the project never creates) and **correctly reported it as an out-of-scope
  follow-up** without editing the file.
- Wave 2 (this project) was that follow-up: root discovery replaced by a marker walk-up; whitelists untouched;
  offline synthetic controls added; `pnpm verify` exit 0 — the full run printed **47 test files passed,
  598 passed | 9 skipped**, the gate suite alone being `layout.test.ts` 16 tests + `skills.test.ts` 4 tests.
  Read the summary, not the raw stdout: the karaoke file prints `xx  word0  t=…  MISMATCH` lines **inside a
  passing** test (it is the negative half of its own two-state check). Grepping `MISMATCH` would fake a red gate.
  Gate economy that actually held: `pnpm install` (7 s) → edits → targeted `vitest run packages/gate` (~1 s, caught
  my own broken fixture) → full `pnpm verify` once (38 s). The targeted run is not the gate; it is cheap feedback
  that keeps the single mandatory verify run meaningful.
  Causal claim I can defend: the locator `join(USINE,'..')` is *sufficient* to produce the wave-1 failure on this
  host shape (probe reproduced it); the delivered fix makes that same tree pass. Not claimed: that no other
  hidden host dependence existed — only that this one was found, reproduced and closed.

## What the fix looks like (for anyone touching it again)
`packages/gate/src/index.ts` exports `ROOT_MARKERS = ['pnpm-workspace.yaml','ownership.json']`,
`discoverRoot(start)` (walk up, require BOTH markers, stop at `dirname(dir) === dir`, return ok/message +
`searched`), `enclosingRepoRoot(ws)` (parent judged **only** if it contains `.git`), `layoutReport(start)`
({ ok, workspaceRoot, enclosingRoot, searched, findings[{level,dir,stray}], message }), the two whitelist sets,
`strayRootDirs`, `strayUsineDirs`, `dirNames`, `strayEngineRepos`. The test file keeps the real-repo assertions
and adds tmpdir trees: deep checkout (home-shaped siblings), markerless (negative control), dirty root
(positive control), outer-root with/without `.git` (`afterAll` `rmSync`).
Unverified/left open: the semantic rename to `layout.ts` (needs `ownership.json`), and whether the grader would
prefer that name.

## Reconciled against live state (2026-10-22, after the PASS verdict)
Re-checked the load-bearing claims of this file against the checkout instead of trusting the notes: root holds
`pnpm-workspace.yaml` + `ownership.json`; `~/.git` absent (so no enclosing level is judged here); `src/index.ts`
present with `ROOT_MARKERS` exactly those two names; no `USINE`/`REPO` const left in the test file; both
allow-lists entry-identical to the list above; **114 non-barrel modules under `packages/*/src`, all declared,
`unclaimed` empty** (which is why adding `src/index.ts` was free); gate suite = `layout.test.ts` +
`skills.test.ts` (+ `_fixture_note.txt`); `tools/foodnames/data` = 12 episodes; `layout_rules.mjs` still carries
0.12 / 0.30 / 0.15 / 0.45. All 14 checks passed — so these numbers are observations of today, not memories of
yesterday; re-run the same checks before relying on them in a later checkout.
