# Memory index

- `craft/evidence-and-verification.md` — how to establish and defend truth on this Windows/git-bash guest:
  which channel proves which claim; attributing (and, when in scope, fixing) a failing gate; whose directories a
  gate may scan and where to put probes; gate economy (install → targeted run → one full verify, and read the
  summary not the stdout); pins that can fail; designing the deliverable when the brief names a path that does not
  exist; before/after probes; fixture semantics; escaping and path traps; report shape.
- `projects/evolution-project-gate-layout.md` — `packages/gate`: the placement/ownership gates, the exact
  allow-lists, `ownership.json`'s module universe (why `src/index.ts` beats `src/layout.ts` under a file budget),
  and the root-locator fix (`discoverRoot` marker walk-up) that closed the wave-1 out-of-scope report.
- `projects/foodnames-video-line.md` — the `tools/foodnames/` video line (12 languages x 12 episodes): gates,
  layout thresholds, the five defects and the accepted fixes, gotchas of that tree. Its gate gotcha is marked as
  since-fixed (see above).

Status: distilled from two PASS runs on 2026-10-22 (foodnames five-defect candidate; gate root-locator fix) and
reconciled against both Verifier reports plus the later wave's project state, and every structural claim
(paths, allow-lists, the 114-module ownership universe, foodnames thresholds) re-checked against the live
checkout on 2026-10-22 (14/14) — overlapping claims were narrowed to
what each wave actually observed rather than appended side by side. Memory is experience, not authority: re-verify
structural claims (paths, thresholds, who-scans-what) against the live machine before acting on them.
