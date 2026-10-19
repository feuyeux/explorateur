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

Proven end-to-end on 12-language posters ("one book", then "a cup of tea").
A complete worked 12-language source (every script family's cell markup)
lives in `assets/example/` — scaffold from it, not from past project
directories.

## 前置输入契约

开工前必须拿到这 5 条。**缺哪条先问哪条，不要拿占位值往下跑**——占位值会让后面每一道机检都失去意义。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | 页面尺寸（默认 1240×1754） | 网格几何无从校验 |
| 2 | 网格行列数 | `feuille poster verify-colors --cols/--rows` 判据不成立 |
| 3 | **完整内容清单**（哪些语种/条目，一个不许少） | 漏项要到最后渲染才发现 |
| 4 | 配色与高亮规则 | 逐字着色无判据 |
| 5 | 是不是**当视频封面**用 | 决定要不要出 `feuille poster make-covers` 的全屏变体 |

内容清单若已有事实源（如 `languages/*/manifest.json` 这样的注册表），**以它为准**，不要另抄一份。

## 边界

**本 skill 是「多语种排版」的唯一事实源**：字体子集、逐字着色（Arabic/Hebrew/Devanagari 叠层、Korean 垫片、kana 渐变、注音/振假名）、字形测量。视频类 skill 需要新字形时，往本 skill 的 `fonts.json` 加字符并重跑 `feuille poster fetch-fonts`，**不要在视频脚本里另抄字体栈**。

12 语种规范顺序也只在这里定义，其他 skill 引用。

**不做 / 转交**：

- 组装成片 → `karaoke-video`（单卡片）或 `storyteller-video`（多幕评书人物小传）
- 实拍画面上烧字幕 → `multilingual-video-poetry`
- 写发布词 → `publish-copy`
- 真的点发布 → `multilingual-video-publishing`
- 多页文档 → docx / pptx / pdf 相关 skill

## 代码归属

拥有模块：poster

多语种排版的实现——`textlayer`（Edge headless 渲字）与 `covers`（封面机制）——在 **library**，本 skill 与 `multilingual-video-poetry` 共用；本 skill 的十条产线脚本（fetch_fonts / assemble / render_poster / render_page / audit_charset / fit_diag / verify_colors / check_overlay / make_covers / measure_korean）已归流 **@feuille/poster** 包（promoted from 本 skill 的 `scripts/`，消费 library 的唯一实现，不自带第二份）。本 skill 不拥有任何 library 模块，跨用走 library 的实现，不要另写一份。事实源见 `usine/ownership.json`，由 @feuille/gate 的 vitest 门禁（`pnpm verify`）与本段双向机检。

其余模块不属于本 skill：基础设施在 `ownership.json` 的 `infrastructure`，其他业务模块归各自 skill。

## Requirements (fresh machine)

- Node + pnpm：本 skill 的十条产线脚本已归流到 **@feuille/poster** 包，进程内
  直跑 `feuille poster <子命令>`（浏览器解析、像素管线全在 @feuille/core 的
  唯一实现里；never hardcode a machine-specific interpreter path in docs or
  configs）；
- **任意 Chromium 系浏览器**——Chrome 或 Edge 都行。渲染器经
  `feuille poster render` 解析，走 @feuille/core 的 `platform.browserPath()`
  这一个事实源；`$CHROME_BIN` 可显式覆盖。环境自查是 @feuille/core
  `platform` 的库函数（`describe()`），没有 CLI 路由——别在文档里写成命令；
- network access for `feuille poster fetch-fonts` (Google Fonts css2 subsetting)。

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
  `feuille poster make-covers` derives `cover_src.html` from `poster_src.html`
  (variant CSS + `?fmt=P` switch — tune its override block per project);
  render with `feuille poster render cover_src.html?fmt=P cover_portrait.png
  1080 1920 1` (the command honors a query suffix; WITHOUT `?fmt=P` the boot
  script silently renders the LANDSCAPE geometry inside the portrait window
  and every downstream check misfires). Two traps: the grid is a flex
  child, so give it `min-height: 0` or the initial oversized words stretch
  the rows past the page bottom; verify each variant's grid with
  `feuille poster verify-colors --cols 4 --rows 3` / `--cols 3 --rows 4`.
- **竖版平台的信息流封面是 3:4，不是 9:16**：小红书/抖音的信息流把竖版封面按
  3:4（1080×1440）居中裁切，9:16 那张上下各掉 12.5%——标题在顶部就会被切掉。
  `make-covers` 另备了第三个变体 `?fmt=T`（1080×1440，3×4 网格），
  竖版平台投它；**视频本体仍是 9:16 全屏**，两者不是一回事。
  `feuille publish check-plan` 的 `COVER_RATIO` 也是按 3/4 判的：
  投 9:16 会留下一条「封面与平台原生差 25%，确认裁切框内文字是否在安全区」的提示。

## Workflow

1. **Confirm the spec.** The 前置输入契约 items, from the user: page size,
   grid, the exact content set (never invent or drop entries; a registry
   such as a `languages/` directory of manifests is the source of truth),
   palette, and what gets highlighted how — plus whether it doubles as a
   video cover. Two-color schemes are the norm: warm red vs cool blue,
   neutral gray for tones/silent marks.
2. **Scaffold a project dir** from the template:
   copy `assets/template/poster_src.html` and `assets/template/fonts.json`,
   then fill in title, legend, grid dims, and one cell per item. For each
   script family's worked cell markup, copy the matching cell from
   `assets/example/poster_src.html` (template = skeleton only).
3. **fonts.json**: one entry per font family — `family` (the @font-face
   name, embed this stack FIRST in CSS), `google` (css2 spec),
   `text` (every char that family will ever render), `classes` (CSS classes
   rendering with it, for the audit). Run `feuille poster fetch-fonts fonts.json`.
4. **Build**: `feuille poster assemble` injects fonts.css at `/*__FONTS__*/`.
5. **Render**: `feuille poster render index.html poster.png 1240 1754 2`.
6. **Verify** (the model usually cannot see the image — all checks are
   programmatic; run after every revision, not just at the end):
   - `feuille poster audit-charset poster_src.html fonts.json` — page chars ⊆
     subsets, no tofu. Family attribution is a stack mirroring CSS
     inheritance (text under the per-letter wrappers `.lay/.top/.t/.c/.ksyl/
     .zi` inherits its cell's family), so overlay words ARE in scope; every
     class that sets its own `font-family` (`.annot`, `.jyut`, `.tagline`…)
     must be listed in that family's fonts.json `classes`, or its text
     escapes the audit. The same run also asserts **patch-rule binding**: a
     `.ksyl` rule is named `k%04X` from `ord(glyph)`, so check that each
     glyph wears the rule of its OWN codepoint, that the rule exists, and that
     no rule is orphaned (a rule pasted under the wrong name still passes every
     other gate — measure_korean verifies a rule against its own labels, and
     the subset check never looks at rule names). Both failure classes are
     reported in one pass; fix neither in isolation;
   - `google-chrome --headless --dump-dom "file://...index.html?verify=1"`
     piped to `feuille poster fit-diag` — per-cell font size, word rects, overflow;
   - `feuille poster verify-colors poster.png --cols 3 --rows 4 --langs …` —
     grid found, every cell has its expected colors;
   - for overlay cells (mark scripts): see step 7.
7. **Overlay registration check** for two-layer cells: render each layer
   alone (inject `.stack .top { visibility:hidden }` for the bottom render,
   `.stack .lay { visibility:hidden }` for the top — plus
   `.stack .lay, .stack .top { will-change: transform; }` in BOTH variants
   to force grayscale AA, or ClearType LCD stripes read as misregistration)
   and run `feuille poster check-overlay lay.png top.png X Y W H` with the word
   rect from fit_diag. Accept only best-shift (0,0) and unmatched ≈ 0%.
   Full rules and the composite-measurement trap:
   `references/script-coloring.md` §4.
8. Iterate on user feedback, re-run the whole verify suite, and keep the
   project dir clean: only `index.html`, `poster.png`, `README.md`, and the
   build/verify pipeline survive; delete diagnostic scratch files. **Before
   deleting anything, carry the measurement provenance into the README** —
   which syllable got which treatment (auto split / `--vowel-comp N` override /
   whole-glyph fallback) and what the verify pass reported. A skill reference
   that cites a measurement as fact cannot cite a scratch dir you deleted: A-03
   shipped with the gate green and the prose citing a `k_measure/` that no
   longer existed, so nobody could re-check the claim and a wrong belief stood
   unchallenged through two re-diagnoses. Provenance in the README, scratch
   deletable.

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
- Korean: `.ksyl` inline-block + measured background patches — patch
  geometry is GLYPH-SPECIFIC, so measure the project's own syllables with
  `feuille poster measure-korean <syllables> --family … --css fonts.css`
  (renders the real subset font, labels each ink component from the
  syllable's NFD jamo decomposition — medial geometry decides vowel vs
  consonant, covering multi-component vowels like ㅝ, short verticals like
  the ㅣ in 일, and multi-component initials like ㅎ's arc+ring — and
  self-verifies by re-rendering the emitted CSS in headless Chrome,
  exiting nonzero unless every ink pixel matches). It cannot split a
  syllable whose vowel ink TOUCHES consonant ink (어 국 render as one
  component in OBS KR — it fails loudly; choose wording that avoids merged
  syllables, or treat the glyph whole: `--vowel-comp 0` whole-blue as in
  A-03 복/요, or the `.cv` fusion gradient as in A-04 얼), and cannot judge
  the labels themselves (sanity-check the component table against the jamo
  line — complex finals like 많's ㄶ auto-mislabel; override with
  --vowel-comp if wrong). Never copy patch fractions from another theme —
  they do not transfer;
- per-character readings (hanzi+zhuyin, kanji+furigana): `.zi` columns —
  one column per character, reading fixed-size inside its own column
  (below for Chinese, above for Japanese via `.wjp` bottom-alignment);
- kana: diagonal gradient `background-clip:text`; hanzi: ink + colored
  annotation; silent letters: gray (`.n`).

## Resources

- `theme-tokens.css` (in `skills/`) — extracted global multi-theme CSS variables supporting 5 teaching video domain palettes (`warm-paper` 国学古文, `clean-paper` 现代外语, `dark-ink` 哲学考据, `desert-sand` 丝路阿语, `botanical-tea` 自然博物)
- `feuille theme match` (@feuille/core `themes`) — automatic theme matcher based on content topic keywords and language (promoted from `skills/match_theme.py`)
- `typography-base.css` (in `skills/`) — shared multilingual typography & component rules (coloring classes, `.stack`, `.ksyl`, `.zi`, `.compound`, `.verdict`)
- `assets/template/` — `poster_src.html` (skeleton with fit JS + ?verify=1
  diagnostics + overlay/ksyl CSS recipes) and `fonts.json` (example)
- `assets/example/` — complete worked 12-language source pair
  (`poster_src.html` + `fonts.json`, the validated "a cup of tea" project):
  the markup reference for every script family's cell
- `feuille poster fetch-fonts|assemble|render|render-page|audit-charset|
  fit-diag|verify-colors|check-overlay|make-covers|measure-korean`
  （@feuille/poster 包）——本 skill 原十条 scripts/ 产线脚本的唯一实现
  （`make-covers` fullscreen cover variants、`measure-korean`
  per-syllable vowel-patch measurement, prints paste-ready CSS）
- `references/script-coloring.md` — cluster paint rule, overlay recipe,
  Devanagari construction, Korean patches, measurement methodology

