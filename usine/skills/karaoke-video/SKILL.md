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
  generation from scratch (use video-generation), and not for subtitles over
  live-action footage (that is multilingual-video-poetry).
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

## 前置输入契约

开工前必须拿到这 5 条。**缺哪条先问哪条**。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | 每个条目的**展示标记**（通常直接复用海报 cell markup） | 无场景可渲染 |
| 2 | **TTS 文本与展示 token 的切分**（token 必须是 text 的连续字符区间） | 词级时间轴对不上，高亮错位 |
| 3 | 每条目一个旁白人设（音色 + 人设字段） | 无法生成 TTS |
| 4 | 画幅（横版 / 竖版 / 都要） | 状态帧几何与 `?fmt=v` 分支无从校验 |
| 5 | 片头/片尾卡片（用 `one-page-poster` 的全屏封面变体） | 首尾帧不是满屏，出现色带 |

**上游是 `one-page-poster`**：本 skill 复用它的 `fonts.css`、封面变体与逐字着色 recipe。新增字符要回到 poster 的 `fonts.json` 加并重跑 `fetch_fonts.py`，不要在本项目里另抄字体栈。

人设若有注册表（如 `usine/personas/personas.json`），**以它为准**。

## 边界

**本 skill 是「海报/卡片驱动的成片」的唯一事实源**：edge-tts 词级时间轴 → 逐词高亮状态帧 → 帧精确合片 → 像素级验收。画面是渲染出来的（海报/卡片帧），**不是实拍**。

BGM 在这里是**线性增益 `amix … normalize=0`**（床垫在旁白下 ~15–18 dB RMS）；需要旁白把底床**动态压住**的侧链方案在 `multilingual-video-poetry`，不要在这里实现第二份。床的生成与床位定标（Lyria 调用、采样率解读、频段自检、`gain` 反推）统一走 `bgm-bed`，本 skill 只负责把它裁到画面网格、两端淡出、定增益混进来。

**不做 / 转交**：

- 做海报本身、字体子集、逐字着色 → `one-page-poster`
- **多幕评书人物小传**（说书人立绘 + 每幕一景一镜一转场 + 醒木）→ `storyteller-video`（它复用本 skill 的时间轴与合片脚本，不复制）
- 实拍母版压字幕 → `multilingual-video-poetry`
- **生成 BGM 床 / 定床位** → `bgm-bed`
- 写发布词 → `publish-copy`
- 真的点发布 → `multilingual-video-publishing`

## 代码归属

拥有模块：（无）

海报驱动成片的合成内核（`tts` / `audio` / `timeline` / `compose` / `render`）全在 **library**，本 skill 与 `multilingual-video-poetry` 共用；本 skill 不拥有任何模块，跨用走 library 的实现，不要另写一份。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

## Requirements (fresh machine)

- Python 3.12 + edge-tts + Pillow + numpy — e.g.
  `uv run --project usine python <script>` (usine pyproject pins all three;
  never hardcode a machine-specific interpreter path in docs or configs);
- `ffmpeg` / `ffprobe` (encode, concat, astats measurements);
- **任意 Chromium 系浏览器**——Chrome 或 Edge 都行，经 library 的
  `feuille.platform.browser_path()` 解析（`build_video.py` 现走这一个事实源，
  不再写死可执行名；`$CHROME_BIN` 可显式覆盖）；
- network access for edge-tts (Microsoft neural voices);
- OPTIONAL, BGM only: a bed + its `gain`, produced beforehand with the
  `bgm-bed` skill (`uv sync --group music` + a Gemini API key; its Live
  music endpoint is region-gated — see that skill). `bgm.file` accepts any
  instrumental wav — with no such capability either drop the `bgm` block or
  point it at an existing track.

## Conventions

- **Canonical item order**: defined **only** in the `one-page-poster` skill
  (§Conventions). Keep the poster, the voices config and the scenes in ONE
  order — but do NOT restate the list here; read it from that skill, so the
  two cannot drift apart.
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
  voice level is untouched. **gain 是派生值，不是抄来的常数**——`bgm-bed`
  从实测旁白与实测床算出该写多少（两条已归档项目的床各落在 0.10 与
  0.13），目标床位 ~15–18 dB RMS 低于旁白，写进来之后照数字核，别信常数。

**不要在本 skill 里重建 Lyria 那套知识**（可用模型 / 免费层配额 / 出口地区判区 /
采样率反查 / 频段自检的阈值）——全部在 `bgm-bed`
（[references/lyria-field-notes.md](../bgm-bed/references/lyria-field-notes.md)）。
同一事实存两处必然漂移，而漂移的那份没人会去核对。

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
   The bed is a **separate asset produced before this step** by `bgm-bed`;
   this script only cuts, fades and applies the fixed `gain` — it never
   invents music.
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
  `scan_blank.py`（底床生成在 `bgm-bed/scripts/gen_bgm.py`，不在这里）
- `references/av-sync.md` — edge-tts WordBoundary semantics, concat drift
  and the exact-frame-count fix, fps snapping, verification methodology
