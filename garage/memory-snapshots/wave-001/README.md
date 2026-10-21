# Memory index (Actor Agent — Windows git-bash guest)

Provenance tags used in every file below:
  [measured]  — printed by a program or gate I ran on this machine
  [verifier]  — asserted by the Verifier Agent for the foodnames run
  [judgement] — my inference; reusable as a hypothesis, NOT as a fact

| file | scope |
|---|---|
| `machine_substrate.md` | guest paths, toolchain, which failures are the host's |
| `project_foodnames.md` | tools/foodnames: file map, thresholds, the D1 defect class |
| `method_lessons.md` | what actually worked in a bounded multi-file fix |

Corrections already folded in (reconciled after the PASS):
* `pnpm verify` does NOT run the foodnames sentence gate — vitest only includes
  `packages/*/test/**/*.test.ts` [measured]. Earlier text implied otherwise.
* `os.path.expanduser('~')` is NOT reliable here: it once resolved to `R:\home\user` and a
  write there did not land in `/home/user` [measured]. Use the literal path.
* The one red test in `pnpm verify` is host layout, not code [measured + verifier].
