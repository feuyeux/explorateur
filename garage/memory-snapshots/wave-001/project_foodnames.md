# Project: tools/foodnames — "food names in twelve languages" (12 episodes)

## Shape [measured by reading]
* `data/epNN-<slug>.json` x12 — content, do not edit. 12 `words` in fixed locale order
  (zh-CN,en-US,de-DE,fr-FR,es-ES,ru-RU,el-GR,hi-IN,ar-SA,he-IL,ja-JP,ko-KR) with
  `word`/`inline`/`sentence`/`tokens`/`script`/`zhuyin|ko_syllables|ko_fused_syllables|word_html`/
  `foot_html`/`persona`.
* `build_episode.mjs` -> `poster_src.html`, `video_src.html`, `voices.json`, `fonts.json`.
* `templates/{poster_style.css,poster_fit.js,video_style.css,video_script.js}`; `run_episode.mjs`
  replaces only the FIRST `{{KO_CSS}}` placeholder in a template (a second one silently swallows
  the next CSS rule).

## Doors
* `check_sentence_matches.mjs --all` — pure text, builds every episode and compares the visible
  text of `<div class="stage">` (skipping `.annot` and `.stack > .top`) with `w.sentence`,
  whitespace+punctuation stripped. [measured] It is NOT part of `pnpm verify` (vitest includes
  only `packages/*/test/**/*.test.ts`), so it must be run explicitly — at most twice per brief.
* `check_video_layout.mjs --out <episode dir>` — needs Chromium + rendered PNG frames; absent
  here. Thresholds live in it [measured by reading]: `hero_height_ratio 0.12`,
  `hero_width_ratio 0.30`, `max_empty_band 0.15`, `other_token_opacity 0.45`, brand colours
  `c9403a / 2f5d9e / b8860b`. Its probe finds the hero as the element whose *visible text* equals
  the word form and measures **leaf ink**, not the element box — so make the fit box the glyph
  box (`width: max-content`) or a width-bound fit can overflow 1080 px and clip the ink.

## The D1 defect class (generalises to any karaoke sentence line)
Old builder did `tokens.map((t,i)=> i===0 ? inlineWord : t)`: whenever token 0 was an article or
particle (Le/El/Το/카레는/カレーは) that token was eaten and the word duplicated -> screen sentence
no longer matches the audio sentence.
Fix that passed [measured: gate exit 0, 144/144; own replica 144/144]: locate the word INSIDE the
list and colour only that sub-span.
* whole-token match on a folded form (case/diacritic-insensitive) first;
* else a per-character stream carrying token indices — **fold per character**, because normalising
  one Korean syllable or one Devanagari cluster expands to several code points;
* let the word continue inside a later token for sc/jp/ko; require a token boundary at the end for
  latin/cyrillic/greek/ar/he/deva; tolerate the Arabic definite article `ال`;
* add a build-time `throw` when `visibleText(html) !== tokens.join(' ')` — the invariant then rides
  along with every gate that builds an episode.

## Census beats the brief's quoted count
[measured] The brief said 54 affected locale-episodes; my data census (word not standing alone at
  token 0) gave **53/144**: fr-FR 11, es-ES 11, el-GR 12, ko-KR 9, ar-SA 6, ja-JP 3, de-DE 1.
  The nearest 54th is ep03 ja-JP (`茶は…`), whose old token-0 ruby form was text-preserving.
  ep03 ja-JP also stays the one uncoloured word token after the fix (its `word_html` ruby is not
  spliced into a partial token); its hero element still renders ruby.

## Delivered shape for D2–D5 in the video line [measured on the delivered files]
* D2 — word is its own element: `<div class="hero word …" id="hero-<locale>">` above the
  sentence; `.hero { display:block; width:max-content; margin:0 auto; line-height:1.08 }`;
  `video_script.js` binary-searches the font size into 960x700 CSS px (portrait) /
  1700x420 (landscape). [judgement] With line-height 1.08 the ink is ~0.72x font size, so the
  height-bound word lands near 24% of 1920 and a width-bound word near 89% of 1080 — above the
  12% / 30% thresholds, but this is arithmetic, not a render measurement.
* D3 — portrait only: `body.vert .scene { padding:66px 60px 60px; justify-content: space-between }`
  plus zeroed portrait inter-block margins and `.stage { flex:0 0 auto; padding:0 }`.
* D4 — `.tok.dim { opacity: 0.45 }` (was 0.18); `.sung` / `.cur` stay 1.
* D5 — highlight per token kind: `.tok.cur.kv { background: rgba(201,64,58,0.18) }`,
  `.tok.cur.kc { background: rgba(47,93,158,0.18) }`, `.tok.cur.kt { background: rgba(184,134,11,0.18) }`;
  `tokKind()` labels every token kv|kc|kt from its own markup with `.annot` stripped first.
* Two traps met on the way: the template had `{{KO_CSS}}` twice while `run_episode.mjs` replaces only
  the first; and the poster's Korean `.k####` patches are pixel rectangles measured at the poster
  font size, so the fitted video word uses the fused `.cv` gradient instead.
