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
  adapters (Playwright), the CLI router, the dsh plugin (the
  AI-operator tool surface: tool descriptions, request schemas,
  discipline wording, refusal and approval cards), and the gate
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

The gate command ("pnpm verify", run from the project root once a
one-time "pnpm install" has filled the store; requires Node 24+ and
pnpm 11 on PATH) drives
typecheck and every acceptance suite and must exit 0. Any accepted improvement keeps the gate green; a
red gate rejects the candidate at merge time regardless of what the
verifier said. Live platform operations - login, publishing, profile
handling - are out of scope here: this environment refuses them before
execution, so an improvement that touches them must be validated offline
(mock pages, local files) instead.

## What Phase-1 waves should explore

Author projects that make the line measurably better for its real
operators. Two families count as improvement:

- the operator-facing pipeline itself: correctness and edge cases in
  one module (scene parsing, timeline math, audio composition, manifest
  building), with the probe suites extended to pin the fixed behavior;
  new offline checks that catch real failure modes the current suites
  miss; data-layer improvements (lesson definitions, persona contracts,
  language metadata) with their validators strengthened accordingly;
  operator ergonomics: clearer CLI errors, faster iteration on a single
  lesson, smaller recomputation when one scene input changes;
  cross-cutting robustness: stronger determinism, clearer logging, safer
  handling of long filesystem paths.
- the agent surface: packages/dsh-plugin ships the tool layer an AI
  operator loads into the web host - one tool per pipeline capability,
  the request schemas those tools accept, the discipline rules that keep
  dangerous operations behind explicit approval, and the refusal and
  approval wording shown to the operator; the packaging howtos under
  skills/ teach the same surface. Improvements there - clearer tool
  descriptions, tighter request schemas, sharper refusal and approval
  cards, more accurate howtos, safer-by-default discipline wording -
  reach the AI operator directly and are first-class targets, not
  documentation afterthoughts.

Every agent-surface project must keep the guard machinery intact and
pinned: a tool that requires approval keeps requiring it and still
fails closed when the approval is missing; the publishing tools stay
unreachable by default; the deliberate red-line suites (a refusal that
becomes reachable, a safe default that flips) must stay green and may
be extended, never relaxed. Numbers written in a howto table must
match the code they describe - extend the pinning suites when you touch
either side, so drift fails the gate instead of the operator. Safe
first projects for a wave: reword one confusing refusal message and
extend its suite; document one common operator mistake in the relevant
howto; tighten one request schema and add boundary cases to its suite.

Spread a wave across different areas of the line; prefer projects whose
success is checkable offline and mechanically. Do not attempt the
platform-publishing side beyond its offline skeleton.

## Saturation

SATURATED means you judge that further waves would not yield improvements
worth their cost; name the evidence (recent outcomes, repeated failures,
exhausted directions) in the rationale. Otherwise publish another WAVE.
