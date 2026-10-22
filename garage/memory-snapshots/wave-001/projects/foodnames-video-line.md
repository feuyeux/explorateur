# Project line: `tools/foodnames/` — "food names in twelve languages" video series

State as of 2026-10-22, verified PASS (generation 1). 12 episodes `data/ep01-sushi.json` … `ep12-fries.json`,
each with 12 locales in fixed order `zh-CN, en-US, de-DE, fr-FR, es-ES, ru-RU, el-GR, hi-IN, ar-SA, he-IL, ja-JP, ko-KR`.
`build_episode.mjs --data <json> --out <dir>` writes `poster_src.html`, `video_src.html`, `voices.json`,
`episode.json`, `fonts.json`; `templates/{poster_style.css, poster_fit.js, video_style.css, video_script.js}` are
inlined into the HTML. Editing scope for this line is `tools/foodnames/` only; the task capped it at three files.

## Gates and thresholds (read these first; they are the acceptance criteria)
- `check_sentence_matches.mjs --all` — the authoritative D1 gate. Builds every episode and compares the **visible
text** of each `.sentence` against `data.words[].sentence` after stripping whitespace+punctuation; skips `.annot` and
`.stack > .top`. Exit 0 = 144/144 consistent. Needs `pnpm install` first (spawns `node --import tsx`); ~16 s.
- `check_video_layout.mjs` — needs rendered frames + Chromium (hero ink ratio, empty band, token opacity, highlight
brand colour, annotation alignment). Not runnable on this guest: D2–D3 had to be argued from construction.
- `check_scene_tokens.mjs` — DOM-only variant (browser), same thresholds.
- `layout_rules.mjs` — **single source of truth**: `hero_height_ratio 0.12`, `hero_width_ratio 0.30`,
`max_empty_band 0.15`, `other_token_opacity 0.45`, `annot_offset_px 3`, `BRAND = ['c9403a','2f5d9e','b8860b']`.
- vitest picks up `tools/foodnames/test/**/*.test.ts` (project `unit`, 30 s per-test timeout).

## The five defects and the fixes that were verified
- **D1** — builder replaced the sentence's first token with the bare word form: articles/particles eaten, word
duplicated when it also occurred later, karaoke highlight off by one word; 54/144 combinations affected.
Fix: `wordSpan(tokens, forms, script)` — folded exact token match first, then a folded character-stream scan tolerant
of NFD expansion; CJK (sc/jp/kr) may end inside a token, Latin/Cyrillic/Greek/Arabic/Hebrew/Deva must end on a token
boundary; Arabic definite-article prefix tolerated — and wrap only that span. Tokens are emitted verbatim via
`tokens.map(...).join(' ')` with a self-check `visibleText(html) === tokens.join(' ')`. If no span is found: colour
nothing and keep the tokens intact. Fused tokens (카레는 / カレーは) get their sub-span coloured **inside** the token;
the sequence is still untouched (this reading passed the Verifier).
- **D2** — the word must be its own element: `.hero` outside `.stage`, fitted by `video_script.js` binary search into a
portrait box 800x700 CSS px with `.hero{line-height:1.08}` → ≈648 px font, ≈0.70 em ink ≈ 454 px = 23.6 % of 1920 px
(need 12 % = 230 px); width-bound words reach 74 % of 1080 px (need 30 % = 324 px).
- **D3** — portrait `body.vert .scene{padding:66px 60px 60px; justify-content:space-between}`, old stacking margins
(130/44/40/30 px) zeroed and `.stage` no longer a flex filler → max gap ≈165 px = 8.6 % of 1920 (limit 15 % = 288 px).
- **D4** — `.tok.dim{opacity:.45}` (was .18).
- **D5** — `.tok.cur.kv/.kc/.kt` = `rgba(201,64,58,.18)`, `rgba(47,93,158,.18)`, `rgba(184,134,11,.18)`;
builder `tokKind()` assigns the class; no neutral grey `rgba(44,38,32,…)` may remain in that stylesheet.
- `templates/video_script.js` is the karaoke/fit state machine — **do not edit it**; it consumes `.scene/.hero/.tok`
with `dim/sung/cur` and walks `.tok` in document order, which is exactly what D1 makes correct.

## Gotchas specific to this tree
- `packages/gate/test/layout.test.ts` asserts the directory **above** `usine` holds no stray project dirs. On this host
the checkout is nested at `$HOME/evolution_project`, so it flags `AppData/bin/work/<project root>`: pre-existing,
environment-hostile on this host, out of scope. The Verifier confirmed this attribution.
- `tools/foodnames/test/sentence_gate.test.ts` (pre-existing) covers only 3 episodes (ep01/ep04/ep06) to keep the merge
gate fast (~6 s); my added `video_style_pins.test.ts` (15 tests, ~3 s alone) pins D1 token sequences plus the D2–D5
numbers by construction.
- `data/*.json` and `check_sentence_matches.mjs` are the comparison basis: never edit them.
