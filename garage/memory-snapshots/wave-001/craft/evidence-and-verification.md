# Craft: evidence, gates and traps on this guest (Windows + git-bash, python3, no browser)

Environment observed 2026-10-22 (re-check before relying on it): node v26.8.1, pnpm 11.8.0 on PATH;
`pnpm install` works from a warm store (~8 s, `--frozen-lockfile` also fine); `pnpm verify` ≈ 39 s
(typecheck + 47 vitest files); there is no browser and no GUI. Home dir at that time:
`.memory, bin, evolution_project, work`.

## 1. Which channel proves which claim
- **Structural / numeric claims** (token sequences, CSS numbers, file mtimes, exit codes): read and write with a
  program. Prefer the repo's own threshold file over prose — on this project every "visual" defect had a numeric
  criterion in-repo (`tools/foodnames/layout_rules.mjs`, `check_video_layout.mjs`, `check_sentence_matches.mjs`).
- **Rendered claims**: nothing renders here. When there is no render available, meet the numbers **by construction**
  (arithmetic read straight off the CSS/markup you wrote) and say which number each change satisfies and how you
  computed it. On this project the Verifier accepted exactly that instead of a render, and the task had explicitly
  forbidden building a renderer.
- Do not build a renderer/headless-Chrome pipeline to self-check layout numbers in this environment: it was
  forbidden by the task and unnecessary, since the numbers were derivable from the source.

## 2. Attribute a failing gate BEFORE touching anything (this decided the verdict)
Example that mattered: `pnpm verify` came back 590 passed / 1 failed. The failure was
`packages/gate/test/layout.test.ts > 仓库根没有第三处放内容的地方`, flagging `AppData/ bin/ evolution_project/ work`
in "the repo root". Cause: that test computes `REPO = join(USINE,'..')`; on this host the project root *is*
`$HOME/evolution_project`, so it scans the user's home and flags the harness's own directories.
Evidence that made "not my defect" defensible (the Verifier later confirmed it independently):
  a) mtimes — flagging test and data files carried the pre-session capture time, not session time;
  b) the flagged names are directories the project never creates, one of them being the mandated project root;
  c) reproduce in isolation: `pnpm exec vitest run <that one file>` fails the same way with no candidate code involved;
  d) the only fixes (edit that test, or rename harness dirs) are outside the permitted scope → report as follow-up.
General rule: a gate failure outside your edit scope is evidence to be attributed and reported, never edited or hidden.

## 3. Scratch space: `$HOME` may itself be what a gate scans
**Trap I hit:** I used `$HOME/scratch` for diagnostics. Because `$HOME` is the directory the whitelist test scans on
this host, my own path appeared as an extra stray entry in that failing assertion. It did not break anything after
removal, but it muddied the evidence. Rule: put disposable probes **outside** the project tree and outside any
directory the gates scan (python `/tmp` is fine; on this guest `$HOME` is not guaranteed safe). Before the final gate
run, prove the tree is clean: `find tools/foodnames -newer <baseline> -type f` should list only intended edits.

## 4. Gate economy: install first, then spend the allowed gate runs
`node --import tsx tools/foodnames/check_sentence_matches.mjs --all` died instantly with `ERR_MODULE_NOT_FOUND: tsx`
because `pnpm install` had not run yet — that burnt one of only two permitted runs of that gate. Order that works:
`pnpm install` (own program) → first (diagnostic) gate run → edits → second (post) gate run → `pnpm verify` once.

## 5. Recon can turn "write the fix" into "verify the fix"
I planned to write the D1 fix. Recon showed the delivered `build_episode.mjs` already contained the token-locating
repair (`wordSpan()` plus a self-check `visibleText(html) === tokens.join(' ')`) and the CSS already carried the new
numbers; their mtimes equalled the capture baseline, and I never edited them. Running the acceptance gate
(144/144 consistent) converted the job into "verify + add the missing pin test". Observed fact: the fixes were present
in the delivered tree. Unproven: how they got there (earlier wave, or delivered that way) — irrelevant to the outcome.
Lesson, stated at the right strength: **run the acceptance gate before writing the fix it checks**, and re-read the
files before rewriting them.

## 6. Pins must be able to fail (negative controls)
A regression pin only counts if it can fail. What the Verifier explicitly credited:
  - the pin rebuilds real episodes through the **real builder** and independently parses the built HTML for the
    top-level `.tok` sequence, comparing to `data.words[].tokens` (count, order, characters) — not a re-implementation
    of the builder's own logic (that would only prove self-consistency);
  - a recorded **negative control**: feeding the old buggy shape (`sushi est un plat japonais`) to the same parser
    yields "not equal" for fr and el, proving the assertion discriminates bug from fix;
  - each CSS requirement turned into arithmetic read off the stylesheet itself (fit box from the script, line-height,
    space-between gap bound, opacity, rgba→hex for brand colours).
Putting these in the **one permitted extra test file** was the right budget call: it left the acceptance gate untouched
and made the render-less defects falsifiable.

## 7. Escaping and path traps when a program generates code or deliverables
- Generating a TypeScript test from a python triple-quoted string produced **doubled backslashes** in regex literals
  (silently wrong patterns). Detected only by reading the file back. Writing TypeScript from a bash heredoc
  (`<<'TS'`, quoted delimiter) preserved escapes literally; then run the file at once for real feedback.
- **Path trap:** bash `cat > /home/user/actor_handoff.md` did **not** land in the guest tree (in bash, `/home/user`
  resolves to the bash installation's own directory); the harness reported the deliverable missing. Rewriting with
  python3 to `/home/user/actor_handoff.md` worked (verified by existence, size, first line).
  Rule: create deliverables with **python3** at canonical paths; in bash use `$HOME`.
- Always confirm a written deliverable: exists, non-empty, first line as intended.

## 8. Report shape that passed
Handoff with `STATUS: SUBMIT` on line 1, then: what recon found; a **defect table** (defect → file/change → the number
it now satisfies); gate runs with exit codes and counts; and an explicit **uncertainty / follow-ups** section
(out-of-scope gate failure; which requirements are met by construction rather than by render). Naming the residual
failure and proving it pre-existing was accepted; the report was also the place where the not-edited state machine
and the "no fourth file" bound were stated so the Verifier could check them.
