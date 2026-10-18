# Complex-script coloring on HTML posters — traps & recipes

How to two-color (warm red = vowels, cool blue = consonants, gray = tones/silent)
the actual glyphs of non-Latin scripts in Chrome. Everything here was verified
pixel-exact on a 12-language poster; the traps are Chrome/Windows-shaping facts,
not font quirks.

Table of contents:
1. [The cluster paint rule](#1-the-cluster-paint-rule)
2. [Two-layer overlay recipe](#2-two-layer-overlay-recipe)
3. [Devanagari: the full construction](#3-devanagari-the-full-construction)
4. [Measurement methodology (read before any pixel claim)](#4-measurement-methodology)
5. [Korean: in-glyph patches](#5-korean-in-glyph-patches)
6. [Other scripts, one line each](#6-other-scripts-one-line-each)
7. [Per-character column layout (readings inside slots)](#7-per-character-column-layout)
8. [Fonts: self-contained subsetting](#8-fonts-self-contained-subsetting)

## 1. The cluster paint rule

Chrome merges "base + attached marks" (nikkud, matras, Arabic harakat, kana
fusion, whole hangul syllables) into one paint cluster and paints the WHOLE
cluster with the color of the span containing the cluster's FIRST character.
A mark can never get its own color via its own span.

The rule is per **cluster**, not per element — verified with a probe:
put a unique color (e.g. green) on the mark's own span and count green pixels
in a single-layer render. Devanagari ि and ा both painted 0 green even though
each sat in its own span: spacing matras follow the base's span color,
`color:transparent` on them is silently ignored. Consequences:

- zero-advance marks (nikkud, harakat): must be **removed from the overlay
  top text** — making them transparent does nothing;
- independent full vowel letters (ए, า-less vowels like เ in Thai standalone
  letters): own cluster → transparency IS honored;
- reordering marks (Devanagari ि): painted by the base even though they
  visually move to the other side.

## 2. Two-layer overlay recipe

When a script cannot be colored with spans at all (Arabic, Hebrew, Devanagari):

- **bottom layer** `.lay`: the full text, all red (`aria-hidden` on it is fine;
  it's the visual source of vowel ink);
- **top layer** `.top`: base consonants only, blue; vowels either removed
  (zero-advance marks) or `.t` transparent (independent letters);
- **stack with `display:inline-grid`, both layers `grid-area:1/1`** — both
  rasters share one grid cell and land on the identical origin. Do NOT use
  `position:absolute` for the underlay: its containing-block origin rounds
  differently from the in-flow top layer and you get 1px fringes ("花了").
- **mirror the `.top` span structure inside `.lay`** (Windows raster fact,
  A-03): if `.top` is split into c/t spans while `.lay` is one text node,
  each box boundary quantizes the origin by up to ~+1/64px — A-03's Hindi
  word end drifted a cumulative +0.125px and the layers misregistered at
  subpixel scale. Put the SAME c/t spans (and spaces) in `.lay`, then
  neutralize the classes with `.stack .lay .c, .stack .lay .t { color:
  inherit; }` — the lay spans carry only the box-boundary duty, both layers
  quantize along the identical path, and every box verifies dx=0.
- mark removal must not change layout: compensate each removed mark's real
  advance with a spacer (see §3), or keep a zero-advance mark's absence as-is
  (nikkud/harakat take no width);
- keep `dir="rtl"` on BOTH layers for RTL scripts.

Acceptance: single-layer renders compared in the word rect → best integer
  shift (0,0), unmatched top-color 0.00% (`feuille poster check-overlay`; also inject
the §4 grayscale forcing on the check variants). On the
12-language poster: Arabic, Hebrew, Devanagari all pass at 0.00%.

Spacing matras (ा, ी …) in the top text — two constructions, both measured
on the delivered A-01/A-02 posters (2160×2880 composites):

- **keep the matra in `.top` inside a transparent `.t` span**: free layout
  parity — both layers carry the same text, no spacer to measure. But the
  cluster paint rule ignores that transparency: the matra paints with its
  base's color, i.e. the whole cluster comes out BLUE. Measured: A-01 धन्यवाद
  word rect = 0 red / 33163 blue px (whole word blue); A-02 माफ़ कीजिए = only
  the independent ए inked red (2499 red / 19815 blue). Independent letters
  (ए, ا/آ, ו/ה/י) are their own clusters — their `.t` transparency IS
  honored (A-02: Arabic 4375 red px from آ, Hebrew 8206 from י/ה).
- **delete the matra + compensate with a measured `.sp` spacer** (§3): the
  matra comes out red (only the bottom layer inks it), at the cost of
  probing every removed mark's in-cluster advance against its actual base.

Decide up front and state the choice in the report: keep-in-`.t` = zero
measurement work, matras blue; delete+`.sp` = red matras, per-mark advance
probing. A-01 and A-02 both shipped keep-in-`.t`.

## 3. Devanagari: the full construction

`एक किताब` (ek kitāb), red = ए ि ा, blue = क क त ब:

```html
<span class="stack f-deva">
  <span class="lay v" aria-hidden="true">एक किताब</span>
  <span class="top"><span class="t">ए</span><span class="c">क</span> <span class="sp"></span><span class="c">क</span><span class="c">त</span><span class="sp"></span><span class="c">ब</span></span>
</span>
```

```css
.sp { padding-left: .2691em; }   /* inline padding, NOT an inline-block */
```

Facts measured on Noto Sans Devanagari at 200px via canvas measureText:

- standalone ि/ा advance = 153.8px (0.769em), but **in-cluster** contribution
  is 51.8px (0.259em): `measureText("कि") = 204.2 = क(152.4) + 51.8`;
- `किताब = कि + ताब` advances add up — no cross-cluster kerning to worry about;
- ि reorders BEFORE क visually, so its advance slot is **before** the क —
  the spacer must be placed before that क in the top text (placing it after
  shifts everything by one matra width and the blue क lands on the red ि stem);
- word space = 0.25em, keep a real space in the top text;
- empirically the gap needs 0.2691em, not 0.2591em (0.01em pipeline residue
  of the empty-span padding; verified 0.00% at 200/100/87.3/70px and 82px);
- the spacer must be inline **padding** on an empty span — an inline-block box
  gets layout-snapped and shifts following text.

"Zero-advance marks can just be deleted" is FALSE in general — measure every
mark against the base it actually attaches to. In OBS Deva the ु below-matra
is zero-advance after क/प/य (कु=क, पु=प, यु=य) but रु is a SPECIAL LIGATURE
that is wider than र by 0.193em (56.22px vs 38.50px at 91.875px): deleting ु
after र without a .193em spacer shifted every following letter left and the
overlay check failed at 10% (the रु form also draws its headline over the full
width, so the top layer shows a headline gap where the spacer sits —
that missing headline segment is red-only by design, like the matra itself).

Measurement-methodology trap, hit twice in one round: advance probes render
with embedded base64 @font-face subsets, and Chrome's --virtual-time-budget
can run the dump JS before the font finishes DECODING — the probe then
measures the system fallback font (र=37.58px = Noto Sans Devanagari) instead
of the embedded subset (र=38.50px = OBS Deva), silently. Gate every probe on
document.fonts.ready + a setTimeout, dump the font status alongside the
numbers, and cross-check ONE isolated letter advance against the real poster
DOM (getBoundingClientRect of the top-layer span) before trusting any em
value. A spacer measured on the fallback font is wrong by ~2.5% per letter
and compounds across the word.

Generalize: measure each mark's in-cluster advance with measureText of
`base+mark` minus `base`, against the base letter actually in your word;
place the compensation BEFORE the base if the mark reorders ahead of it,
  after otherwise; tune ±0.005em until `feuille poster check-overlay` passes at (0,0).

## 4. Measurement methodology (read before any pixel claim)

You cannot trust your eyes here (and in this environment you may not be able
to see images at all — all verification is programmatic).

- **Never measure registration on the composite.** The top layer paints over
  the bottom: overlap pixels hide the bottom color, so "blue pixels not on
  red" ≈ 100% even when perfectly aligned, and red counts collapse. Compare
  SINGLE-LAYER renders: inject `.stack .top { visibility:hidden }` for the
  bottom render and `.stack .lay { visibility:hidden }` for the top render
  (same window size / scale as the poster), then diff masks in the word rect
  from the ?verify=1 diagnostics.
- **Force grayscale AA on the check variants** (A-03, Windows/Edge): ClearType
  LCD stripes are asymmetric across the two ink colors — red ink's blue
  channel sits Δ172 from the paper base, blue ink's only Δ72, so at equal
  stripe coverage the red mask loses pixels the blue mask keeps. Hindi and
  Arabic paints rasterize LCD-striped and the mask loss reads as
  misregistration (measured top-unmatched 9.65% Hindi / 6.94% Arabic);
  Hebrew happened to rasterize grayscale and read 0.00% unaided. Inject
  `.stack .lay, .stack .top { will-change: transform; }` in BOTH check
  variants to force composited grayscale AA — all three scripts then pass at
  0.00% (印地 9.65%→0.00%, 阿语 6.94%→0.00% on A-03). Inject on the check
  variants only; the delivered PNGs keep native AA.
- Pixel-set intersection has the same trap: `A & ~B` on one composite tells
  you nothing about registration.
- Read check_overlay's two mismatch counts directionally: **top-only** pixels
  (top-layer ink with no bottom ink under it) are the real error signal —
  misregistration, wrong spacer width, a base missing from `.top` — and must
  sit at the antialiasing floor (A-02: 0–1 px). **bottom-only** pixels are
  the design, not a leak: they are exactly the ink the top layer omits
  (removed marks, transparent independent letters), i.e. the visible
  bottom-color strokes in the composite — A-02 word rects measured 797 (ए),
  1109 (آ), 2126 (י/ה). Chase bottom-only ink only where the top layer
  should have laid a consonant (spacer on the wrong side of a reordered
  mark shows the red stem peeking past a blue base).
- Isolated-glyph comparisons must replicate real positions: placing a
  standalone क at the same origin as कि does NOT compare outlines (ि's
  advance pushes क right inside the cluster). Cross-correlate with a generous
  shift radius before concluding "different glyph".
- Tooling: `feuille poster check-overlay` (registration), `feuille poster
  verify-colors` (per-cell color presence), `feuille poster fit-diag`
  (per-cell font size/overflow), `feuille poster audit-charset` (tofu
  prevention) — all promoted into the @feuille/poster package.

## 5. Korean: in-glyph patches

Hangul syllables are single paint clusters (CJK logic), so spans can't split
ㅊㅐㄱ within 책. Direct in-glyph coloring instead:

- each syllable is an inline-block `.ksyl` with `color:transparent` +
  `-webkit-background-clip:text`;
- stack hard-edged `linear-gradient` background patches (one per color region)
  sized/positioned as fractions of the glyph box;
- geometry comes from `feuille poster measure-korean`: it renders each syllable at
  200px in the REAL subset font, flood-fills ink components, labels them from
  the syllable's NFD jamo decomposition (medial geometry decides the split:
  vertical medials sit in the right half, medials ㅗ ㅜ ㅡ and compounds also
  low — multi-component vowels like ㅝ, short verticals like the ㅣ in 일,
  and multi-component initials like ㅎ's arc+ring all come out right), covers
  the vowel ink with margin-safe rectangles, and SELF-VERIFIES by re-rendering
  the emitted CSS in headless Chrome and requiring every ink pixel to match
  (exit nonzero otherwise);
- the verify pass proves the CSS reproduces the LABELS — the jamo truth of the
  labels is the printed component table; sanity-check it against the jamo
  line, and override with `--vowel-comp` if a label is wrong. **Cluster finals**
  (ㄳ ㄵ ㄶ ㄺ ㄻ ㄼ ㄽ ㄾ ㄿ ㅀ ㅄ — TWO consonants in ONE jamo codepoint, U+11AA /
  0x11AC-0x11AD / U+11B0-0x11B6 / U+11B9) can AUTO-mislabel, because NFD emits
  the whole cluster as a single Extended-B jamo and the labeler's final-band
  test keys on that one codepoint: the final's ink can sit in the right
  half-band (vowel territory) instead of the bottom band, and comes out V. A-03
  많 (ᆭ U+11AD): comp3 x[77,167] y[144,173] was labeled V, giving 3 red rects
  where 1 is correct — fixed with `--vowel-comp 1` (only ㅏ's vertical red),
  verify PASS 0 wrong px. Note `len(NFD) > 3` does NOT detect this (NFD never
  splits a cluster final); the script checks the actual cluster-final codepoint
  set and prints a ⚠ line naming the final, so read that line before trusting
  any label. It also prints every syllable's `U+XXXX`, its Unicode name and its
  full NFD decomposition with codepoints — never take a syllable's identity
  from the glyph you read back (see below);
- hard limit: when vowel ink TOUCHES consonant ink (ㅓ's tick reaches the ㅇ
  in 어, ㅜ sits on the final ㄱ in 국 — in OBS KR), the syllable is ONE
  component and no labeling can split it; the script fails loudly — choose a
  wording that avoids merged syllables or treat that glyph whole. Two shipped
  treat-it-whole precedents: whole-syllable consonant blue by re-measuring
  with `--vowel-comp 0` (A-03 복/요, verify PASS), and the kana-style fusion
  gradient `.cv` over the whole glyph (A-04 얼 — chosen because 예's same-form
  ㅇ sits in the blue zone and painting ㅇ red there would contradict it).
  **The failure is a code invariant, not a hope:** a syllable always leaves
  ≥2 non-final components (initial + medial; ㅎ-style initials and ㅘ-style
  medials only add more), so exactly ONE non-final component means initial and
  medial are fused, and `classify()` returns an error instead of a rule. This
  guard exists because the silent alternative was worse than a crash: with
  `has_h` set, the lone fused blob *is* the "bottom group", so classify()
  labeled it V and emitted a real-looking rule that painted the CONSONANT red
  — and verify PASSED, since verify only checks that the CSS reproduces the
  labels. Measured A-03: 복 ㅂ+ㅗ came out 2 components (the ㅂ+ㅗ blob
  x[9,173] y[53,157] + the final ㄱ) → rule painted a full-width 67.2% red
  band over the whole blob; 요 ㅇ+ㅛ came out 1 component → rule painted 100%
  red, ㅇ included. Both "PASS". Both were already shipped as `--vowel-comp 0`
  whole-blue, which is why the poster was right while auto was wrong — and why
  the guard now makes auto refuse instead of quietly contradicting it;
- CSS percentage `background-position` resolves against (container − image)
  in EVERY form, including the 4-value `left X%` form (measured in Chrome:
  it is not a plain offset) — the script emits 2-value percentages computed
  through that formula;
- NEVER use the `font:` shorthand inside `.ksyl` — it resets line-height to
  normal, the box grows ~13%, and every fraction silently shifts. Use
  `font-family` + explicit `line-height` (must match the surrounding `.word`);
- accept intentional ~1px slivers where vowel strokes nearly touch consonant
  strokes (0.5px at poster scale) — chasing them breaks adjacent patches.

### Glyph identity is a codepoint, never a glyph you read back

Four rules that exist because A-03's Korean cell was misdiagnosed twice in a
row, both times from a glyph read off a screen or out of a file dump rather
than from a codepoint:

- **A rule's name IS its glyph's codepoint.** `.ksyl` patch rules are named
  `k%04X` from `ord(glyph)`; paste each rule under the class `measure-korean`
  printed for it. If one syllable wears another's rule, every pre-existing gate
  still passes — measure_korean verifies a rule against its OWN labels, and the
  subset audit only checks page chars ⊆ fonts.json. So
  `feuille poster audit-charset` now asserts the binding itself: class codepoint ==
  glyph codepoint, the rule exists, and no rule is orphaned — and it reports
  BOTH failure classes (subset + binding) in one run before exiting, because
  fixing one must not mask the other.
- **Never take a syllable's identity from the glyph you read.** ㅀ
  (rieul-hieuh) and ㄶ (nieun-hieuh) render near-identically, so `많`, a misread
  `만`, and the non-word `맗` are indistinguishable by eye. Anchor codepoints
  with facts that do not come from your eyes: the Unicode name, the Hangul
  syllable formula `(초성×21+중성)×28+종성`, a romanization (Revised
  Romanization *manhi* ⇒ final ㄶ, since ㄶ→nh and ㅀ→lh), or sound change (ㅀ
  assimilates to [ㄹ] before a vowel — 싫어 → [시러] — while ㄶ keeps its ㄴ, so
  많 reads [마니]). Same rule as any non-Latin codepoint: verify with a probe
  that passes codepoints.
- **fonts.json `text` comes from the words manifest**, the fact source — never
  from a character copied out of the poster you are editing, or the subset and
  the page end up validating each other.
- **Diagnostic scripts are read-only; repair is a separate step.** A one-shot
  "diagnose and fix" converts a wrong premise into a corrupted fact source (A-03:
  a wrong codepoint belief rewrote a correct `fonts.json`). Diagnose, anchor the
  judgement with an independent check, then repair behind before/after
  assertions, and keep a revert script.

## 6. Other scripts, one line each

- **Kana (あ)**: consonant+vowel fusion → diagonal two-color gradient
  `linear-gradient(135deg, blue 49.5%, red 50.5%)` + background-clip:text;
  pure vowels red, moraic ん/っ blue.
- **Chinese**: hanzi in ink; zhuyin/bopomofo annotation below, per-symbol
  colored (independent letters, spans work).
- **Latin scripts**: color letters directly; silent letters gray; the
  translit line can be IPA, kept gray so it doesn't fight the coding.
- **Tone marks** (Thai ่ etc.): if the mark shares a cluster with a vowel that
  must be red, the tone mark is forced red too — a known, documented
  compromise; pick constructions that avoid it where possible.
- **RTL**: set `dir` on the cell head, both overlay layers, and honor it in
  the .top construction order (rightmost consonant first).

## 7. Per-character column layout (readings inside slots)

When a word pairs each character with its reading (hanzi + zhuyin, kanji +
furigana), don't put all readings on one shared line — give EVERY character
its own column (隔断) and place the reading inside that column, so each
reading sits exactly under/over its own character:

```html
<div class="word f-sc" style="color:var(--ink)">
  <span class="zi"><span class="hz">一</span><span class="annot">ㄧ</span></span>
  <span class="zi"><span class="hz">本</span><span class="annot">ㄅㄣˇ</span></span>
  ...
</div>
```

```css
.zi { display:inline-flex; flex-direction:column; align-items:center;
      margin:0 .03em; vertical-align:top; }
.hz { display:block; }                    /* fills line 1, auto-fit scales it */
.annot { display:block; margin-top:.14em; text-align:center;
         font-size:34px;                  /* FIXED px — does NOT scale with fit */
         font-weight:600; letter-spacing:.08em;
         margin-left:.08em;               /* cancel trailing letter-spacing */
}
```

Rules learned the hard way:

- **Reading size is fixed in px**, not em: the fit binary search then spends
  all its budget on the characters. The search still accounts for the
  reading's width/height (it measures the whole `.word` rect), so an
  over-wide reading (e.g. 4-kana いっさつ) caps the character size — shrink
  the reading to give the characters room.
- **Centering is box-based**: `letter-spacing` adds its gap AFTER the last
  glyph, shifting ink left by spacing/2 inside the centered box. Compensate
  with `margin-left: <letter-spacing>` (same em units). Verify per column
  and expect residual 1–3 CSS px from glyph ink asymmetry — that's font
  design, not a bug.
- **Reading position differs by convention**: Chinese zhuyin goes BELOW
  (columns top-aligned, the default); Japanese furigana goes ABOVE — put
  the reading span first in the column and bottom-align the columns
  (`.wjp .zi { vertical-align:bottom }`) so all characters share one row
  even when a character has no reading (の needs no furigana; its column
  holds just the character, still on the same row).
- **Verification trap**: ink-band analysis (split each column's ink into
  top/bottom segments and compare centers) misreads glyphs whose ink doesn't
  fill the em box — 一's stroke sits mid-em, so its ink "bottom" is 60+
  device px above neighbours' and looks misaligned when the DOM is perfect.
  Check alignment with DOM rects instead: dump
  `.hz`/`.annot` `getBoundingClientRect()` per column; equal tops/bottoms
  across columns = aligned. Use ink analysis only for centering (x-axis),
  where it's valid.
- Fit consequences: per-character columns make the character size width-bound
  as `box_width / n_columns` — 3 characters reach ~106px, 4 characters ~77px
  in a 337px cell. Readings above cost the same vertical budget as below.

## 8. Fonts: self-contained subsetting

- Google Fonts css2 `&text=` per-character subsetting → download woff2 →
  base64 @font-face inline. A 12-script poster lands ~150KB total.
- Subset URLs come back as `/l/font?kit=...` without a .woff2 extension —
  still woff2 (UA header decides); `feuille poster fetch-fonts` handles it.
- Font stacks embed the subset family FIRST: rendering is identical with or
  without local fonts, and `document.fonts` status tells you what loaded.
- Every character the page may ever render with a family (copy, labels,
  legend, annotations) must be in that family's `text` list — enforce with
  `feuille poster audit-charset` after every copy edit.
- **A Google `&text=` subset is not the character list you asked for.** For
  scripts Google composes per jamo cluster (Hangul, Devanagari) the returned
  `unicode-range` lists the script's full codepoint closure, so it routinely
  contains syllables/jamo you never asked for. That is normal — never diagnose
  it as contamination, and never read "the subset lacks codepoint X" as proof
  about your intended text. Assert against `fonts.json` (the manifest), and
  when you do need to know whether a specific character is really renderable,
  ask the RENDERER (a codepoint-only probe that fails on no-ink/tofu) — not the
  unicode-range list.
- List EVERY class that sets its own `font-family` in that family's
  `classes` (`.annot`, `.jyut`, `.tagline` …): the audit sees families only
  through that list, and a font-family class WINS over DOM inheritance.
  Live case from the archived example: the Japanese furigana sat in the
  OBS JP `text` list while `.annot` rendered them with OBS SC — five kana
  (い っ ち ゃ ぱ) plus pinyin ē rode local-font fallback unnoticed until the
  stack-based audit flagged them; both `text` lists were then repaired.
