# AV-Sync Traps (deterministic karaoke video)

Hard-won rules from building a 12-scene TTS karaoke video where every
highlight switch lands on a word-boundary timestamp. All durations are
frame-quantized; all verification is programmatic.

## 1. edge-tts word boundaries

- `edge_tts.Communicate(text, voice, boundary="WordBoundary")` — the default
  is `SentenceBoundary`, which yields NO word events.
- `stream()` yields `audio` chunks (mp3, 24 kHz mono) and `WordBoundary`
  events with `offset`/`duration` in **100-ns units** (divide by 1e7). The
  first word typically starts at t=0.1 s (service-side lead-in).
- A boundary word may span several display tokens (zh "一本" covers 一+本;
  ja "一冊" covers 一+冊). Map boundaries onto tokens by accumulating
  non-space characters of the input text and splitting the boundary duration
  proportionally by char position (see `/karaoke gen_tts.tokenTimings`).

### 1a. Coverage depends on the VOICE's language, not on the text's

A boundary event is emitted by the voice's front-end, so what gets a boundary is decided by **the voice's language**, not by what the text contains. Measured with a Chinese voice (`zh-CN-XiaoxiaoNeural`):

| script in the TTS text | boundaries returned |
|---|---|
| Chinese / Latin / Greek | covered, word by word |
| Cyrillic / Arabic / Devanagari / Hebrew | **dropped wholesale** |

Concretely: 「俄语叫 слон」 returned only 2 boundaries (俄语, 叫) and lost the 4 Cyrillic characters; 「阿语 حصان」 returned 1 and lost 4. The mapping in §1 accumulates characters of the input text, so missing boundaries shift the mapping left — the trailing tokens end up with no boundary at all, `tokenTimings` yields `null`, and the build dies in the formatter (`fmt2(null)`) with an error that names neither the episode, the locale, nor the token.

**Two rules follow, and they are not stylistic:**

1. **A narration line may only contain scripts the narration voice covers.** Foreign words belong on the display cards (each of the 12 language cards renders the word verbatim), never in the narration: say 「俄语和阿拉伯语里，它干脆直接叫大象」 in the voice's own language and let the cards show `слон` / `فيل`.
2. **Enforce it on both sides of synthesis.** Before any TTS call, check every narration string against the uncovered ranges and refuse it — the error must name the episode, the offending characters and what to do instead. After synthesis and before assembly, walk every token of every locale and require `start`/`end` to be non-null, reporting the locale and the offending token text. A `null` deep inside the timeline surfaces as `fmt2(null)` and names none of that; by then the cheap fix window is gone.

Measured on a 12-episode run: ep05 (narration contained `слон`/`فيل`) and ep07 (`конь`/`ίππος`/`حصان`) crashed outright, while ep09 (`צריח`) did **not** crash — its timeline was merely drifted, i.e. wrong in a way the crash would have been preferable to. The post-synthesis gate is what makes that class visible instead of shipping it.

Ranges that bit us (Chinese voice): `\u0400-\u04FF` Cyrillic, `\u0600-\u06FF` + `\u0750-\u077F` Arabic, `\u0590-\u05FF` Hebrew, `\u0900-\u097F` Devanagari. Re-measure for any other voice — do not extrapolate the table above.

### 1b. Punctuation must not reach the TTS text

Boundaries do not cover punctuation, so a punctuation character sitting in the TTS text occupies a character position that no boundary ever claims. Two failures follow: the accumulated mapping drifts from that point on, and the final token can end up with no boundary (same `null` crash as §1a).

- Keep punctuation **on screen only** (it belongs to the display tokens);
- strip it from the TTS text — trailing clause punctuation `，。！？：；、` at minimum;
- join clauses with spaces: §1's mapping skips whitespace, so spaces are free separators that cost nothing;
- split narration into clauses at punctuation before synthesis, so each clause is a clean boundary run.

### 1c. Strip attached marks from the TTS text too

Arabic harakat and Hebrew niqqud are separate codepoints that the voice may pronounce as part of the word, and they occupy character positions the mapping counts. Remove them from the TTS text (and from the display tokens, where they also cost a paint cluster — see `../../one-page-poster/references/script-coloring.md`). Keep the unmarked letters; the marks are optional orthography, not content.

## 2. The concat duration drift (the big one)

Feeding stills to the concat demuxer with `duration N` entries is NOT exact:

- with `-r 30` (CFR): ffmpeg pads gaps on the image2 demuxer's default 25fps
  grid — a 50.6 s timeline came out 52.7 s (+2.1 s of pure drift);
- with `-fps_mode vfr`: still off by ~1 frame per few entries (51.1 designed
  → 50.84 actual).

**Fix:** encode every entry separately with an exact frame count, then
concat with `-c copy`:

    ffmpeg -loop 1 -framerate 30 -i frame.png -t N/30 -frames:v N ... seg.mp4
    ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp4

Frame counts are integers, so the timeline is exact by construction.

## 3. Snap everything to the fps grid

Design durations in seconds, then `d = ceil(d*30 - 1e-9)/30` before use —
both the video entries AND the audio segment lengths. The audio for scene k
must be `-t`-trimmed to the sum of that scene's snapped frame durations, or
audio/video scene boundaries diverge by up to a frame per scene.

## 4. Audio segment must include the preroll

Scene audio = `adelay=<preroll*1000>:all=1,apad` then `-t <scene total>`.
The scene total is `d30(preroll) + Σ(word frames) + d30(done)` — forgetting
the preroll term shifts every highlight 0.8 s early (silent, easy to miss;
the sync check catches it).

## 5. Deterministic state frames

Render each visual state as a still (`?lang=X&state=N`):
`state=-1` all dim, `0..K-1` token i current (earlier sung, later dim),
`K` all sung. No CSS transitions/animations — the page must be identical
for every render of the same state. Karaoke "smoothness" comes from the
frame-switch rate at token boundaries, not from tweening.

**Headless Chrome silently renders the Google search page when the file
URL is malformed.** The real incident: the build script derived its base
dir from a RELATIVE config path (`HERE = Path("video.json").parent` =
`.`), so the render URL became `file://video_build.html?lang=…` —
`video_build.html` parsed as a HOST name, Chrome failed to resolve it and
fell back to a Google search page. Every scene frame came back as
white + #4285f4/#d3e3fd; the build "passed" because the sync check
compares against the same-run state frames (white vs white diffs to zero)
— the videos shipped showing Google until a user watched one.

Defenses (all in `feuille karaoke build`, @feuille/karaoke):
1. **Absolute paths only** for anything that goes into a `file://` URL —
   `HERE = cfgp.resolve().parent`, never a cwd-relative parent;
2. **isolated `--user-data-dir`** per render — also guards against a
   running desktop Chrome hijacking the headless launch (URL opens as a
   tab there and the screenshot is its new-tab page);
3. **blank-frame sentinel** after every render: >90% near-pure-white
   pixels → hard fail with the URL echoed. This is the only reliable
   gate — it proved the fix by catching the still-broken relative-path
   build on its first frame.

## 6. Verify programmatically

The acceptance gate. **Programmatic checks are necessary but never sufficient** — each one proves only that the thing it checks holds; none of them asks whether the picture is *right*. The corrected position (this file used to claim the model cannot watch the video, and that sentence authorised four rounds of rework) is in [delivery-check.md](delivery-check.md): after the gate is green, extract frames from the finished mp4 and look at them.

1. `ffprobe` stream durations: video vs audio within ~1 ms;
2. `feuille karaoke verify-sync` — grab frames at computationally known times and
   pixel-diff against the source state frames (threshold ~40k on L1 gray
   over 1080p; clean runs give ≤ ~500, real mismatches ≥ 50k);
3. remember the done-frame window is only the last `done` seconds — grabbing
   "done" too early lands in the last word frame and false-alarms;
4. color-presence checks on the state frames (red/blue/ink counts) double as
   a tofu/blank-render detector; also check nothing inks within a few px of
   the frame edges (overflow detector);
5. **whole-video scan, independent of the state frames**: sample the
   finished mp4 at 1 fps and flag frames that are >75% pure white — this is
   what catches a Google-page render, because checks 2 and 4 are
   self-consistent with a bad render batch (they diff the video against
   frames produced in the SAME run). One bad `file://` URL poisons both
   sides identically.

Note: dimmed tokens (opacity 0.18) wash out below any color threshold —
count colors only in "current/sung" states or expect near-zero counts.
