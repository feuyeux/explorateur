# usine Phase-1 target direction

## The production line

The asset under recursive self-improvement is a TypeScript pnpm monorepo
("usine") that turns lesson material into short vertical videos for
Chinese short-video platforms, across many languages. One pipeline pass
takes a lesson scene - script lines, speaker personas, a language roster
- and renders on-screen text per language, synthesizes narration audio
with word-level timing, composes frames and audio tracks into a master
clip, draws a cover image, and emits the publication manifest each
platform expects. Quality baselines are enforced mechanically: cached
artifact hashes, frame-level pixel comparisons, lesson schema validation,
and per-package vitest suites that include deliberate-failure
(reverse-validation) probes.

## Repository layout (what lives where)

- packages/ - the TypeScript packages: core (scene parsing, the lesson
  model, TTS, audio composition, timeline math, text rendering layers,
  covers, manifests, metrics, personas, data), the pipeline packages
  (karaoke, poster, poetry, storyteller, copy, bgm), the publish
  adapters (Playwright), the CLI router, the dsh plugin, and the gate
  package (ownership accounting over skills).
- packages/*/test/ - the vitest suites; "pnpm verify" (typecheck plus
  every suite) is the project's gate.
- lessons/, languages/, personas/, themes/ - data: lesson definitions,
  language metadata, persona rosters, visual themes.
- docs/, skills/, examples/ - operator documentation, packaging howtos,
  worked examples.
- ownership.json, package.json, pnpm-lock.yaml, pnpm-workspace.yaml -
  provenance and environment pinning.

## How the repository protects itself

The gate command ("pnpm verify", run at the project root after a
one-time "pnpm install"; requires Node 24+ and pnpm 11 on PATH) drives
typecheck and every acceptance suite and must exit 0. Any accepted improvement keeps the gate green; a
red gate rejects the candidate at merge time regardless of what the
verifier said. Live platform operations - login, publishing, profile
handling - are out of scope here: this environment refuses them before
execution, so an improvement that touches them must be validated offline
(mock pages, local files) instead.

## What Phase-1 waves should explore

Author projects that make the line measurably better for its real
operators, for example:

- correctness and edge cases in one module (scene parsing, timeline
  math, audio composition, manifest building), with the probe suites
  extended to pin the fixed behavior;
- new offline checks that catch real failure modes the current suites
  miss;
- data-layer improvements (lesson definitions, persona contracts,
  language metadata) with their validators strengthened accordingly;
- operator ergonomics: clearer CLI errors, faster iteration on a single
  lesson, smaller recomputation when one scene input changes;
- cross-cutting robustness: stronger determinism, clearer logging, safer
  handling of long filesystem paths.

Spread a wave across different areas of the line; prefer projects whose
success is checkable offline and mechanically. Do not attempt the
platform-publishing side beyond its offline skeleton.

## Saturation

SATURATED means you judge that further waves would not yield improvements
worth their cost; name the evidence (recent outcomes, repeated failures,
exhausted directions) in the rationale. Otherwise publish another WAVE.
