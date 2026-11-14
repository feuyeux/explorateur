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
  subset fonts and per-glyph coloring). Also covers running MANY of
  these at once — the acceptance gates must cover "is the element
  present at all" (not just "is it correct"), intermediates that
  acceptance depends on may only be cleaned after ALL acceptance has
  run, shared fixed-name intermediates make the victim the one that
  errors, and a full rebuild needs an explicit force flag. Not for
  general video editing or
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
| 2 | **TTS 文本与展示 token 的切分**（token 必须是 text 的连续字符区间）——且 **TTS 文本只能含旁白语音覆盖的脚本**（中文语音丢掉西里尔/阿语/天城/希伯来，见 `references/av-sync.md` §1a） | 词级时间轴对不上，高亮错位；后半段 token 拿不到边界 → `null` → 合片崩在 `fmt2(null)` |
| 3 | 每条目一个旁白人设（音色 + 人设字段） | 无法生成 TTS |
| 4 | 画幅（横版 / 竖版 / 都要） | 状态帧几何与 `?fmt=v` 分支无从校验 |
| 5 | 片头/片尾卡片（用 `one-page-poster` 的全屏封面变体） | 首尾帧不是满屏，出现色带 |

**上游是 `one-page-poster`**：本 skill 复用它的 `fonts.css`、封面变体与逐字着色 recipe。新增字符要回到 poster 的 `fonts.json` 加并重跑 `feuille poster fetch-fonts`，不要在本项目里另抄字体栈。

人设若有注册表（如 `usine/personas/personas.json`），**以它为准**。

## 边界

**本 skill 是「海报/卡片驱动的成片」的唯一事实源**：edge-tts 词级时间轴 → 逐词高亮状态帧 → 帧精确合片 → 像素级验收。画面是渲染出来的（海报/卡片帧），**不是实拍**。

BGM 在这里是**线性增益 `amix … normalize=0`**（床垫在旁白下 ~22 dB RMS）；需要旁白把底床**动态压住**的侧链方案在 `multilingual-video-poetry`，不要在这里实现第二份。床的生成与床位定标（Lyria / local / matrix 三条出床线、采样率解读、频段自检、`gain` 反推、「不刺耳」的音色口径）统一走 `bgm-bed`，本 skill 只负责把它裁到画面网格、两端淡出、定增益混进来。

**不做 / 转交**：

- 做海报本身、字体子集、逐字着色 → `one-page-poster`
- **多幕评书人物小传**（说书人立绘 + 每幕一景一镜一转场 + 醒木）→ `storyteller-video`（它复用本 skill 的时间轴与合片脚本，不复制）
- 实拍母版压字幕 → `multilingual-video-poetry`
- **生成 BGM 床 / 定床位** → `bgm-bed`
- **音乐欣赏 / 听辨教学**（真实录音是内容本体、乐谱-录音对齐出时间轴）→ `music-annotate-video`
- 写发布词 → `publish-copy`
- 真的点发布 → `multilingual-video-publishing`

## 代码归属

拥有模块：karaoke

海报驱动成片的合成内核（`tts` / `audio` / `timeline` / `compose` / `render`）全在 **library**，本 skill 与 `multilingual-video-poetry` 共用；本 skill 的产线编排（gen_tts / build_video / verify_sync / scan_blank）已升入 **@feuille/karaoke** 包（消费 library 的唯一实现，不自带第二份）。本 skill 不拥有任何 library 模块，跨用走 library 的实现，不要另写一份。事实源见 `usine/ownership.json`，由 @feuille/gate 的 vitest 门禁（`pnpm verify`）与本段双向机检。

## Requirements (fresh machine)

- Node + pnpm：本 skill 的四段产线（tts/build/verify-sync/scan-blank）已归流
  到 **@feuille/karaoke** 包，进程内直跑 `feuille karaoke <子命令>`
  （edge-tts 协议、ffprobe、浏览器解析全在 @feuille/core 的唯一实现里）；
- `ffmpeg` / `ffprobe` (encode, concat, astats measurements);
- **任意 Chromium 系浏览器**——Chrome 或 Edge 都行，经 @feuille/core 的
  `platform.browserPath()` 解析（`feuille karaoke build` 现走这一个事实源，
  不再写死可执行名；`$CHROME_BIN` 可显式覆盖）；
- network access for edge-tts (Microsoft neural voices);
- OPTIONAL, BGM only: a bed + its `gain`, produced beforehand with the
  `bgm-bed` skill (three bed lines: Lyria with a Gemini API key — its Live
  music endpoint is region-gated and its free quota fails *silently*;
  local synthesis needing no key or network; the MCode Matrix tool).
  `bgm.file` accepts any
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
  0.13），目标床位 **22 dB** RMS 低于旁白（不是 16 dB——那个间距床会分走
  注意力），写进来之后照数字核，别信常数。

**不要在本 skill 里重建 Lyria 那套知识**（可用模型 / 免费层配额 / 出口地区判区 /
采样率反查 / 频段自检的阈值）——全部在 `bgm-bed`
（[references/lyria-field-notes.md](../bgm-bed/references/lyria-field-notes.md)）。
同一事实存两处必然漂移，而漂移的那份没人会去核对。

### 场景版式泛化（1 个词 / 一组词 都要自适应）

- **主角框必须是定尺寸元素**：build_video 截图的是 `?lang=&state=` 状态页，页内脚本把主角词二分拟合到舞台框——**舞台框若跟随文字收缩（内容自适应宽），拟合量到的就是「当前字号的自身宽度」**，循环依赖把字号压到 ~12px（2026-11-07 水果系列 ep01 实测，用户圈词打回）。修法：词框 `width: 100%`（或定 px），拟合才有稳定目标。
- **N 个词的场景**（一组水果 / 一组单词）：不加「另一份大字」——**把原有词直接放大**，当前项用卡片框 + 词的品牌底色高亮，其余项 dim ≥ 0.45。横版一行 N 卡、竖版 2×2；卡宽按「N×卡宽 + (N−1)×gap ≤ 画幅−2×padding」预算（fruit-vocab-series 的 build_episode 是参考实现）。
- **视口亏空**：build_video 已双向补偿（窗口 = W+亏空.w / H+亏空.h，截图后裁回 W×H）——Edge 实测右 24 / 底 93 CSS px 不补的话场景右/底被切、露出 body 底色带（「画面溢出」的体感来源）。场景页是**定宽定高精确画幅**，两个方向都必须补（与 poster 渲染「只补高度」的差异见 build_video 头注）。
- **成片验收加一道 `feuille karaoke check-edges`**（帧边缘溢出门）：状态帧 4px 边缘带出现非纸色像素 = 元素出画，退出码 1。intro/outro 封面卡自带平台契约彩色边框，`--skip intro.png,outro.png` 不进门。

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
   to `fonts.json` and re-run its `feuille poster fetch-fonts`, then audit). The
   template has ONE worked scene; for every script family's scene markup
   copy from `assets/example/video_src.html`.
3. **voices.json**: one entry per item — `locale`, `voice` (edge-tts neural
   id), `text` (exact TTS input), `tokens` (display tokens as consecutive
   char ranges of `text`), persona fields. Run
   `feuille karaoke tts <voices.json> [tts_out_dir]`; it writes `<tts>/<locale>.mp3` +
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
5. **Build**: `feuille karaoke build <video.json>` (add `--only landscape`
   to iterate on one format first). Renders all state frames, assembles
   audio, mixes the optional `bgm` bed, and writes the mp4 per format.
   The bed is a **separate asset produced before this step** by `bgm-bed`;
   this script only cuts, fades and applies the fixed `gain` — it never
   invents music.
6. **Verify** — 两件事，缺一不可。**门禁全绿 ≠ 做对了**（见下）。
   - **A. 程序化验收**（机器能判的部分，每次改完都跑）：
   - `ffprobe` both streams: durations within ~1 ms;
   - `feuille karaoke scan-blank <out.mp4> …` — whole-video white-page scan;
     ⚠ 它**只判「接近纯白」**：抓得住 `file://` URL 写错导致 Chrome 落 Google 页，
     **抓不出内容缩成一个点**。它是唯一独立于状态帧的检查，但视野很窄；
   - `feuille karaoke verify-sync --video out.mp4 --frames frames/ \
     --tts tts/ --locales <comma list in video order>` — grabs frames at
     computed times and pixel-diffs against the state frames;
   - color-presence / edge-overflow checks on the state frames
     (blank-render and overflow detectors).
   Full failure modes and the ffmpeg traps they exist to catch:
   [references/av-sync.md](references/av-sync.md) — READ IT before touching
   the timeline (concat duration drift, 30fps snapping, preroll in the
   audio segment, done-frame grab timing, the Google-page incident).
   - **B. 亲手看**（机器判不了的部分，**不可省**）：用 ffmpeg 从成片里抽帧
     （每一镜一帧 + 每个该点亮的时刻 + 首帧/尾帧），再用 `read` 把图看进眼里。

   > ⚠ **A 全绿只证明"我检查的那件事成立"，不证明"画面是对的"。**
   > 本流程上一版这里写着 *"the model cannot watch the video — the gate is
   > programmatic"*，那句话直接导致连续 4 轮返工：封面塌成一个点、中文注解颜色
   > 不对、台词没删干净、"卡拉OK"做成了台词条——**每一次都发生在全绿之后**。
   > 完整根因、模糊指令的处理规则（取最小字面解释是最贵的默认）、
   > 逐项交付前清单和本轮踩到的具体陷阱，见
   > [references/delivery-check.md](references/delivery-check.md)。
7. Iterate on feedback, re-run the verify suite, and clean intermediates
   (`_sil*.wav`, `_vseg*.mp4`, seg wavs are all regenerable).

## 成批产线：多支成片时的纪律（单支流程不管这些）

一支片的流程跑通了，**不代表跑第二支、第三支也成立**——批量会引入单支没有的
问题：共享的中间产物名、组内串行、批与批之间的时间边界。九条纪律与每条的实测
证据在 **[references/batch-production.md](references/batch-production.md)**，
动手跑多支前先读它。要点：

1. **验收门要覆盖「产物里某个要素在不在」，而不只是「产物对不对」**——漏掉的
   那一维在缺失时不报错而是走降级分支 ⇒ 全部门通过、产物却是残的。对每道门
   问一句「它缺了会怎样」，答案是「跳过这条判据」就改成**缺输入直接判死**。
2. **清理「验收依赖的中间产物」必须放在全部验收之后**——先跑的那批会把它删光，
   后跑的同组用例必然假红（红的不是产物坏了，是依赖被自己删了）。
3. **固定名中间产物被两个进程共用时，报错的是受害者**——症状不是「冲突」而是
   「我要读的文件不存在」。识破点：中间产物的 **mtime 交错**（单进程只能严格串行）。
4. **改底床/场景后要整批重渲**——驱动器会按「产物已存在」跳过，需要显式的强制
   重排开关（`-Force`）；配一个按组过滤（`-OnlyGroup`）以支持单组重做。
5. **状态文件要能扛住残缺**（手工清空成 `{}`、旧批次遗留别的结构）——否则
   `report.jobs[name] = …` 抛 TypeError，整批刚跑一支就崩。
6. **别让两处写同一个日志文件**——`Start-Process` 重定向与内部 `Tee-Object`
   会互相锁死；stdout 也别写到逐门详细日志的同一路径（会把实测值覆盖成一行摘要）。
7. **渲染队列跑着时不要并行跑验收**——正在构建的组帧目录不完整 ⇒ 假红。
8. **别把子进程输出接进 `Select-Object -First N`**——它会关闭上游管道、杀掉子进程。
9. **旧批次的遗留结论要清掉**——按「期望文件名集合 ∩ 磁盘实际」求差，别用通配符。

## Timeline model

Per scene: `preroll` (all dim) → one frame per token, switching at the next
token's start (interpolated within TTS word boundaries) → last word holds
to audio end + `tail` → `done` frame (all sung). Scenes are concatenated
after an intro card and before an outro card. Keep 0.8/0.8/0.5 s defaults
unless the pacing feels wrong — every change re-quantizes through the same
pipeline.

## Resources

- `theme-tokens.css` (in `skills/`) — extracted global multi-theme CSS variables supporting 5 teaching video domain palettes (`warm-paper` 国学古文, `clean-paper` 现代外语, `dark-ink` 哲学考据, `desert-sand` 丝路阿语, `botanical-tea` 自然博物)
- `feuille theme match` (@feuille/core `themes`) — automatic theme matcher based on content topic keywords and language (promoted from `skills/match_theme.py`)
- `typography-base.css` (in `skills/`) — shared multilingual typography & karaoke state rules (`.tok`, `[data-say]`, `.compound`, `.verdict`)
- `assets/template/` — `scenes.html` (karaoke CSS/JS + portrait variant +
  token recipes; ONE worked scene), `voices.json`, `video.json` (two-format
  example)
- `assets/example/` — complete worked three-file source from the validated
  "a cup of tea" project (`video_src.html` with all 12 scenes' token
  markup, `voices.json`, `video.json`): the per-script scene markup
  reference
- `feuille karaoke tts|build|verify-sync|scan-blank`（@feuille/karaoke 包）
  — 四段产线入口（promoted from `scripts/gen_tts.py` / `build_video.py` /
  `verify_sync.py` / `scan_blank.py`；底床生成在 `bgm-bed`，不在这里）
- `references/av-sync.md` — edge-tts WordBoundary semantics, **boundary coverage gated by the voice's language** (a zh voice drops Cyrillic/Arabic/Devanagari/Hebrew → `null` token times), punctuation and attached marks must not reach the TTS text, concat drift and the exact-frame-count fix, fps snapping, verification methodology
- `references/delivery-check.md` — **交付前自检**：为什么门禁全绿仍然要返工、
  歧义指令的处理规则、必须亲手看的时刻清单、封面 `vw` / `scan_blank` 盲区 /
  `preroll` 下限 / 一镜一场景 / 拼接前裁尾、已确认的画面语义约定
- `references/batch-production.md` — **成批产线纪律**（跑多支前必读）：验收门要覆盖
  「要素在不在」（含底床门的完整设计：量法 / 期望值反推 / 判别力实测 / 无边降级
  分支判死）、清理中间产物必须放在全部验收之后、固定名中间产物共用时**报错的是
  受害者**（mtime 交错识破）、整批重渲的强制开关与按组过滤、状态文件残缺兜底、
  日志落点禁忌、并行验收假红、PowerShell 管道截断、遗留结论清理

