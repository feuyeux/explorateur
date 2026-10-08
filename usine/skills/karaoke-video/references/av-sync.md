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
  proportionally by char position (see `gen_tts.py token_timings`).

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

Defenses (all in build_video.py):
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

The model cannot watch the video. The acceptance gate:

1. `ffprobe` stream durations: video vs audio within ~1 ms;
2. `verify_sync.py` — grab frames at computationally known times and
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
