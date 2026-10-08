---
name: karaoke-video
description: >
  Produce a TTS-narrated karaoke video where on-screen text highlights in
  sync with the spoken words (word-level timestamps from edge-tts neural
  voices, deterministic state frames rendered by headless Chrome, ffmpeg
  assembly with frame-exact durations). Use when the user asks for a video
  of text being "read aloud with karaoke highlighting", narrated slides of
  words/phrases with personas doing the TTS, or a talking poster —
  typically paired with the one-page-poster skill (the scenes reuse its
  subset fonts and per-glyph coloring). Not for general video editing or
  generation from scratch (use video-generation).
---

# Karaoke Video

Deterministic pipeline: edge-tts audio + word-boundary JSON → per-token
timeline → Chrome-rendered state frames (?lang=&state=) → ffmpeg assembly
where every duration is snapped to the 30 fps grid and encoded with an
exact frame count → frame-grab + pixel-diff acceptance.

Proven end-to-end on 12-language videos ("one book", then "a cup of tea";
landscape 1920×1080 + portrait 1080×1920), each language a persona from a
registry speaking the phrase while its tokens light up one by one. A complete
worked three-file source (all 12 scene markups, voices, config) lives in
`assets/example/` — scaffold from it, not from past project directories.

## Requirements (fresh machine)

- Python 3.12 + edge-tts + Pillow + numpy — e.g.
  `uv run --project usine python <script>` (usine pyproject pins all three;
  never hardcode a machine-specific interpreter path in docs or configs);
- `ffmpeg` / `ffprobe` (encode, concat, astats measurements);
- `google-chrome` (headless state-frame render);
- network access for edge-tts (Microsoft neural voices);
- OPTIONAL, BGM only: a music-generation capability (Google Lyria) — this
  lives OUTSIDE this repo. `bgm.file` accepts any instrumental wav, so on a
  machine without that capability either drop the `bgm` block or point it at
  an existing track. Bed level target ~15–18 dB RMS under the narration.

## Conventions

- **Canonical item order** (same as the one-page-poster skill — keep the
  poster, the voices config and the scenes in ONE order):
  中 zh, 英 en, 德 de, 法 fr, 西 es, 俄 ru, 希腊 el, 印地 hi,
  阿拉伯 ar, 希伯来 he, 日 ja, 韩 ko.
- **Intro/outro cover**: use the poster skill's fullscreen cover variants
  (cover_landscape.png 1920×1080, cover_portrait.png 1080×1920) as
  per-format `intro_image` with a no-op `poster_filter` (`scale=1920:1080`
  / `scale=1080:1920`) — full-bleed first/last frame, no desk-color bands.
  A padded A4 poster is NOT fullscreen. The cover's gold title (top-left
  hanzi, `--gold: #b8860b`, used nowhere else) is the video's thumbnail
  face; the scene brand repeats that accent on its hanzi only.
- **BGM (optional)**: a `bgm` object in video.json —
  `{"file": "bgm_raw.wav", "gain": 0.1, "fade_in": 1.5, "fade_out": 3.0}`
  — mixes an instrumental bed under the narration: trimmed to the video
  grid, faded at both ends, fixed linear gain, `amix … normalize=0` so the
  voice level is untouched. Aim the music ~15–18 dB RMS below the
  narration (measure both with ffmpeg `astats`). Generate the bed with
  the music-generation skill (Google Lyria — instrumental-only output;
  request no drums/percussion and an "underscore for narration" mood).
  **Cost facts (verified 2026-10)**: use the `lyria-realtime-exp` model on
  a free-tier Gemini API key — free tier calls it at $0, and paid-only
  models (Lyria 3.5 / 3 Clip / 3 Pro, $0.04–0.08 per song, no free tier)
  are simply REJECTED on a free-tier project (no billing account = no
  accidental charges, they fail loudly instead). Google publishes no
  numeric free quota for lyria-realtime-exp; check the per-model limit in
  AI Studio, or probe with a `--duration 5` generation (429 = daily quota
  spent, still $0). Caveats: free-tier output may be used by Google for
  product improvement (fine for instrumental beds); a machine with a
  configured gcloud project makes lyria.py prefer the Vertex backend,
  which bills that GCP project — unset `GOOGLE_CLOUD_PROJECT` to stay on
  the free AI Studio path.

## Workflow

1. **Confirm the spec.** Get from the user: the items/phrases and their
   display markup (usually an existing poster — reuse its cell markup),
   one narrator persona per item (if a persona registry exists, e.g.
   `usine/personas/personas.json`, treat it as the source of truth and
   alternate gender), aspect ratios (landscape and/or portrait), and the
   intro/outro card — the one-page-poster skill's fullscreen cover variants
   (see Conventions), one per aspect ratio.
2. **Scaffold** a project dir: copy `assets/template/scenes.html`,
   `voices.json`, `video.json`; point `fonts_css` at the subset css built
   by the one-page-poster skill (add any NEW chars — persona names, digits —
   to `fonts.json` and re-run its `fetch_fonts.py`, then audit). The
   template has ONE worked scene; for every script family's scene markup
   copy from `assets/example/video_src.html`.
3. **voices.json**: one entry per item — `locale`, `voice` (edge-tts neural
   id), `text` (exact TTS input), `tokens` (display tokens as consecutive
   char ranges of `text`), persona fields. Run
   `scripts/gen_tts.py voices.json`; it writes `<tts>/<locale>.mp3` +
   `.json` (word boundaries + per-token timings). A boundary word may span
   several display tokens (zh "一本") — the script splits it by char share.
   Geminate merges can NEST boundaries (ja お茶一杯 → いっぱい: 一
   0.38–0.84 contains 杯 0.61–0.84) — harmless: the builder switches states
   at each token's START, so nesting never yields a zero-length state.
4. **scenes.html**: one `<section class="scene" data-lang=…>` per item;
   wrap each karaoke token in `.tok` in spoken order (see the recipe
   comment in the template; token markup variants = the poster's cell
   recipes). `?fmt=v` switches the portrait layout; adjust its CSS block if
   the aspect differs.
5. **Build**: `scripts/build_video.py video.json` (add `--only landscape`
   to iterate on one format first). Renders all state frames, assembles
   audio, mixes the optional `bgm` bed, and writes the mp4 per format.
6. **Verify** (the model cannot watch the video — the gate is programmatic;
   run after every revision):
   - `ffprobe` both streams: durations within ~1 ms;
   - `scripts/scan_blank.py out.mp4 …` — whole-video white-page scan,
     the ONLY check independent of the state frames (a malformed `file://`
     URL makes headless Chrome capture the Google page; white-vs-white
     passes every self-consistent check — see references §5–6);
   - `scripts/verify_sync.py --video out.mp4 --frames frames/ --tts tts/ \
     --locales <comma list in video order>` — grabs frames at computed
     times and pixel-diffs against the state frames;
   - color-presence / edge-overflow checks on the state frames
     (blank-render and overflow detectors).
   Full failure modes and the ffmpeg traps they exist to catch:
   [references/av-sync.md](references/av-sync.md) — READ IT before touching
   the timeline (concat duration drift, 30fps snapping, preroll in the
   audio segment, done-frame grab timing, the Google-page incident).
7. Iterate on feedback, re-run the verify suite, and clean intermediates
   (`_sil*.wav`, `_vseg*.mp4`, seg wavs are all regenerable).

## Timeline model

Per scene: `preroll` (all dim) → one frame per token, switching at the next
token's start (interpolated within TTS word boundaries) → last word holds
to audio end + `tail` → `done` frame (all sung). Scenes are concatenated
after an intro card and before an outro card. Keep 0.8/0.8/0.5 s defaults
unless the pacing feels wrong — every change re-quantizes through the same
pipeline.

## Resources

- `assets/template/` — `scenes.html` (karaoke CSS/JS + portrait variant +
  token recipes; ONE worked scene), `voices.json`, `video.json` (two-format
  example)
- `assets/example/` — complete worked three-file source from the validated
  "a cup of tea" project (`video_src.html` with all 12 scenes' token
  markup, `voices.json`, `video.json`): the per-script scene markup
  reference
- `scripts/` — `gen_tts.py`, `build_video.py`, `verify_sync.py`,
  `scan_blank.py`
- `references/av-sync.md` — edge-tts WordBoundary semantics, concat drift
  and the exact-frame-count fix, fps snapping, verification methodology
