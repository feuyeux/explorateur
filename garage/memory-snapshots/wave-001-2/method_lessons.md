# Method lessons — foodnames D1–D5 run (terminal verdict: PASS)

1. **Recon in <=2 programs, then edit.** ~7 reading turns still fit, but the tail was tight;
   one listing plus one bounded grep of the regions to patch is enough to start.
2. **Write the invariant into the producer, not only into a test.** `sentenceHtml` throwing on
   `visibleText(html) !== tokens.join(' ')` made every build self-checking. [judgement] This is
   the cheapest durable guard for "markup must preserve a token sequence"; it demonstrably fired
   (it caught my own broken first version) and then stayed silent on correct output.
3. **Re-derive the gate's extraction literally when self-checking.** My python replica disagreed
   with the build twice, both times because the replica was wrong (a greedy HTML regex, then a
   list-membership test where a substring test was needed on the class stack). Copy the gate's
   algorithm; a stricter-or-different self-check produces false alarms that cost whole turns.
4. **Census, don't quote.** Counting the affected set from the data (53/144) instead of repeating
   the brief's 54 made the report defensible, and the Verifier accepted the discrepancy.
5. **Run every probe before submitting it.** The `done` probes were executed first as greps over
   real files; none was invented at declaration time. [judgement/caveat] Those probes prove the
   *surface* (rule present, hero element present, scope = 3 files), not the render; the render-time
   door (`check_video_layout.mjs`) cannot run here, and it must be said so rather than implied.
6. **Budget arithmetic:** install and verify are separate programs; `pnpm verify` is a one-shot.
   With one provably-substrate red test, the right move was to attribute it with evidence and
   submit — the Verifier confirmed the attribution and passed the work.
7. **Deliver a render-number claim as "the CSS that produces it" plus the number**, never as a
   verified render. D2/D3 were accepted on that framing.
8. Cheap and correct: deleting my own scratch dirs before handoff; noting the duplicate
   `{{KO_CSS}}`; switching the video word's Korean syllables to the fused `.cv` gradient because
   the poster's `.k####` patches are pixel rectangles measured at the poster font size.
9. **Path discipline (learned the hard way):** write final artifacts to literal `/home/user/...`.
   One handoff write went through `os.path.expanduser('~')` -> `R:\home\user` and was invisible
   at the literal path; it had to be rewritten. That is a real failure mode, not a typo.
