---
name: one-page-poster
description: >
  Build self-contained single-page HTML information posters ("一页纸"/one-pager,
  fixed A4-ratio page such as 1240×1754, CSS grid cells, per-cell font
  auto-fit, embedded subset fonts, PNG render + pixel verification). Use when
  the user asks for a one-page poster/infographic/cheat-sheet, a single-file
  printable page, or anything that lays out multiple items in a fixed grid
  with per-cell content — including multilingual/multi-script typography with
  per-glyph coloring (vowels vs consonants, mark scripts like Arabic/Hebrew/
  Devanagari, Korean in-glyph patches, kana gradients). Not for multi-page
  documents (use docx/pptx/pdf skills), not for assembling video (poster-driven
  narration is karaoke-video), and not for text burned over live-action footage
  (that is multilingual-video-poetry).
---

# One Page Poster

Single-file HTML poster on a fixed page (default 1240×1754 = A4 @150dpi),
content in a CSS grid, every cell auto-fits its font size, all fonts
subset-embedded (base64) so the file is offline-portable and printable,
then rendered to PNG with headless Chrome and verified **programmatically**
(grid detection, per-cell color stats, layer registration).

Proven end-to-end on 12-language posters ("one book", then "a cup of tea") with
per-glyph vowel/consonant coloring across 12 scripts. A complete worked
12-language source (every cell's markup for every script family) lives in
`assets/example/` — do NOT go hunting past projects for worked markup; that
is what the example is for.

## 前置输入契约

开工前必须拿到这 5 条。**缺哪条先问哪条，不要拿占位值往下跑**——占位值会让后面每一道机检都失去意义。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | 页面尺寸（默认 1240×1754） | 网格几何无从校验 |
| 2 | 网格行列数 | `verify_colors.py --cols/--rows` 判据不成立 |
| 3 | **完整内容清单**（哪些语种/条目，一个不许少） | 漏项要到最后渲染才发现 |
| 4 | 配色与高亮规则 | 逐字着色无判据 |
| 5 | 是不是**当视频封面**用 | 决定要不要出 `make_covers.py` 的全屏变体 |

内容清单若已有事实源（如 `languages/*/manifest.json` 这样的注册表），**以它为准**，不要另抄一份。

## 边界

**本 skill 是「多语种排版」的唯一事实源**：字体子集、逐字着色（Arabic/Hebrew/Devanagari 叠层、Korean 垫片、kana 渐变、注音/振假名）、字形测量。视频类 skill 需要新字形时，往本 skill 的 `fonts.json` 加字符并重跑 `fetch_fonts.py`，**不要在视频脚本里另抄字体栈**。

12 语种规范顺序也只在这里定义，其他 skill 引用。

**不做 / 转交**：

- 组装成片 → `karaoke-video`
- 实拍画面上烧字幕 → `multilingual-video-poetry`
- 写发布词 → `publish-copy`
- 真的点发布 → `multilingual-video-publishing`
- 多页文档 → docx / pptx / pdf 相关 skill

## 代码归属

拥有模块：（无）

多语种排版的实现——`textlayer`（Edge headless 渲字）与 `covers`（封面机制）——在 **library**，本 skill 与 `multilingual-video-poetry` 共用；本 skill 不拥有任何模块。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

其余模块不属于本 skill：基础设施在 `ownership.json` 的 `infrastructure`，其他业务模块归各自 skill。

## Requirements (fresh machine)

- Python 3.12 + Pillow + numpy — e.g. `uv run --project usine python <script>`
  (the usine pyproject pins both; never hardcode a machine-specific
  interpreter path in docs or configs);
- **任意 Chromium 系浏览器**——`google-chrome` 或 Edge 都行。渲染器经
  `scripts/render_poster.sh` 解析，走 library 的 `feuille.platform.browser_path()`
  这一个事实源；`$CHROME_BIN` 可显式覆盖。用 `uv run --project usine python -c
  "from feuille import platform; print(platform.describe())"` 自查缺什么
  （原版在此硬编码 `google-chrome`，在只有 Edge 的机器上直接失败）；
- network access for `fetch_fonts.py` (Google Fonts css2 subsetting)。

## Conventions

- **Canonical item order** (established on the "one book" project — use it
  for any 12-language artifact unless the user says otherwise):
  中 zh, 英 en, 德 de, 法 fr, 西 es, 俄 ru, 希腊 el, 印地 hi,
  阿拉伯 ar, 希伯来 he, 日 ja, 韩 ko.
- **Title accent**: the top-left display title uses `--gold: #b8860b` — a
  color tier of its own, shared with nothing else on the page (red/blue/
  gray/ink are all taken by the legend). Keep it exclusive.
- **Fullscreen cover variants**: when the poster doubles as a video cover,
  do NOT rotate or pad one orientation into the other (rotation leaves dead
  bands that never fill the screen). Lay out each orientation natively:
  1920×1080 with a 4×3 grid and 1080×1920 with a 3×4 grid, same cells.
  `scripts/make_covers.py` derives `cover_src.html` from `poster_src.html`
  (variant CSS + `?fmt=P` switch — tune its override block per project);
  render with `render_poster.sh cover_src.html?fmt=P cover_portrait.png
  1080 1920 1` (the script honors a query suffix; WITHOUT `?fmt=P` the boot
  script silently renders the LANDSCAPE geometry inside the portrait window
  and every downstream check misfires). Two traps: the grid is a flex
  child, so give it `min-height: 0` or the initial oversized words stretch
  the rows past the page bottom; verify each variant's grid with
  `verify_colors.py --cols 4 --rows 3` / `--cols 3 --rows 4`.

## Workflow

1. **Confirm the spec.** Get from the user: page size (default 1240×1754),
   grid (rows × cols), the exact content set (e.g. which languages — never
   invent or drop entries; if a registry exists, e.g. a `languages/`
   directory of manifests, treat it as the source of truth), palette, and
   what gets highlighted how. Two-color schemes are the norm: warm red vs
   cool blue, neutral gray for tones/silent marks.
2. **Scaffold a project dir** from the template:
   copy `assets/template/poster_src.html` and `assets/template/fonts.json`,
   then fill in title, legend, grid dims, and one cell per item. For each
   script family's worked cell markup, copy the matching cell from
   `assets/example/poster_src.html` (template = skeleton only).
3. **fonts.json**: one entry per font family — `family` (the @font-face
   name, embed this stack FIRST in CSS), `google` (css2 spec),
   `text` (every char that family will ever render), `classes` (CSS classes
   rendering with it, for the audit). Run `scripts/fetch_fonts.py fonts.json`.
4. **Build**: `scripts/assemble.py` injects fonts.css at `/*__FONTS__*/`.
5. **Render**: `scripts/render_poster.sh index.html poster.png 1240 1754 2`.
6. **Verify** (the model usually cannot see the image — all checks are
   programmatic; run after every revision, not just at the end):
   - `scripts/audit_charset.py poster_src.html fonts.json` — page chars ⊆
     subsets, no tofu;
   - `google-chrome --headless --dump-dom "file://...index.html?verify=1"`
     piped to `scripts/fit_diag.py` — per-cell font size, word rects, overflow;
   - `scripts/verify_colors.py poster.png --cols 3 --rows 4 --langs …` —
     grid found, every cell has its expected colors;
   - for overlay cells (mark scripts): see step 7.
7. **Overlay registration check** for two-layer cells: render each layer
   alone (inject `.stack .top { visibility:hidden }` for the bottom render,
   `.stack .lay { visibility:hidden }` for the top) and run
   `scripts/check_overlay.py lay.png top.png X Y W H` with the word rect from
   fit_diag. Accept only best-shift (0,0) and unmatched ≈ 0%. Full rules and
   the composite-measurement trap: `references/script-coloring.md` §4.
8. Iterate on user feedback, re-run the whole verify suite, and keep the
   project dir clean: only `index.html`, `poster.png`, `README.md`, and the
   build/verify pipeline survive; delete diagnostic scratch files.

## Complex-script coloring

Do NOT hand-roll coloring for mark scripts. Read
[references/script-coloring.md](references/script-coloring.md) first — it
carries the Chrome cluster paint rule (marks take the base's span color, even
through reordering and ignored transparency), the two-layer overlay recipe
(inline-grid, never absolute), the full Devanagari construction (spacer
0.2691em BEFORE the reordered base; never assume a matra is zero-advance —
रु is 0.193em wider than र in OBS Deva), the Korean background-patch method,
and the measurement methodology (including the probe-font-decode race:
verify the embedded subset actually loaded before trusting any em value). Quick cell-body variants:

- simple scripts (Latin/Cyrillic/Greek): colored spans directly;
- mark scripts (Arabic/Hebrew/Devanagari): `.stack` two-layer overlay;
- Korean: `.ksyl` inline-block + measured background patches — the patch
  geometry is GLYPH-SPECIFIC, so measure the project's own syllables with
  `scripts/measure_korean.py <syllables> --family … --css fonts.css`
  (it renders the real subset font, labels each ink component from the
  syllable's NFD jamo decomposition — medial geometry decides vowel vs
  consonant, covering multi-component vowels like ㅝ and short verticals
  like the ㅣ in 일, and multi-component initials like ㅎ's arc+ring —
  covers the vowel ink with margin-safe rectangles, and self-verifies by
  re-rendering the emitted CSS in headless Chrome: it exits nonzero unless
  every ink pixel matches). Two things it cannot do: split a syllable whose
  vowel ink TOUCHES consonant ink (어 국 in OBS KR render as one component —
  it fails loudly; choose wording that avoids merged syllables), and judge
  the labels themselves (verify is against the printed component table —
  sanity-check it against the jamo line, and override with --vowel-comp if
  wrong). Never copy patch fractions from another theme — they do not
  transfer;
- per-character readings (hanzi+zhuyin, kanji+furigana): `.zi` columns —
  one column per character, reading fixed-size inside its own column
  (below for Chinese, above for Japanese via `.wjp` bottom-alignment);
- kana: diagonal gradient `background-clip:text`; hanzi: ink + colored
  annotation; silent letters: gray (`.n`).

## Resources

- `assets/template/` — `poster_src.html` (skeleton with fit JS + ?verify=1
  diagnostics + overlay/ksyl CSS recipes) and `fonts.json` (example)
- `assets/example/` — complete worked 12-language source pair
  (`poster_src.html` + `fonts.json`, the validated "a cup of tea" project):
  the markup reference for every script family's cell
- `scripts/` — `fetch_fonts.py`, `assemble.py`, `render_poster.sh`,
  `audit_charset.py`, `fit_diag.py`, `verify_colors.py`, `check_overlay.py`,
  `make_covers.py` (fullscreen cover variants), `measure_korean.py`
  (per-syllable vowel-patch measurement, prints paste-ready CSS)
- `references/script-coloring.md` — cluster paint rule, overlay recipe,
  Devanagari construction, Korean patches, measurement methodology
