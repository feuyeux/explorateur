# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that renders 28 × 10-second character "intro cards" (`build/intro/<id>.mp4`, 1080×1920 @ 30fps, h264+aac) — one per persona in a 14-language teaching-video character cast. Each card = TTS audio + Edge-headless text layers + Pillow frame rendering, composited by ffmpeg. Project docs and code comments are written in Chinese.

**Authoritative docs** — read before changing anything:
- [render-handbook.md](render-handbook.md) — engineering & tuning manual. Its §3 is a "want to change X → edit Y" parameter map; §2 lists invariants; §5 lists pitfalls.
- [plan.md](plan.md) — overall plan (§8.2 audio contract, §8.3 drawing spec).
- [self-introductions.md](self-introductions.md) — content seeds (lines/phonetics/translations per card).

## Commands

Everything goes through `run.ps1` (PowerShell):

```powershell
.\run.ps1 all                                     # tts → assets → render → qa → qa-motion (~5 min)
.\run.ps1 tts                                     # TTS + word timestamps (system Python, edge-tts)
.\run.ps1 assets                                  # text-layer PNGs via Edge headless (~122 files)
.\run.ps1 render -Only xiaoman,layla -Workers 7   # frames + ffmpeg
.\run.ps1 qa                                      # qa_all.py — full acceptance, all 28 cards
.\run.ps1 qa-motion                               # qa_motion.py — karaoke/lip-sync/blink/bubble-mirror
```

Two-interpreter split (enforced by run.ps1, see handbook §1):
- **tts** runs on **system `python`** — the only one with edge-tts installed.
- **assets / render / qa** run on the **bundled DSH Python** `C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe` (has Pillow + numpy).

Direct equivalent: `intro_cards.py tts|assets|render [--only id1,id2] [--workers 7]`.
Acceptance baseline after any change: **qa_all 28/28 PASS + qa_motion PASS**.

## Architecture

```
personas/personas.json   (28 persona dossiers: voice/palette/hair/accessories/RTL)
personas/intro-cards.json (28 cards: lines/moods/gestures/scene/close/cast)
        └→ ① tts → ② assets → ③ render → build/intro/<id>.mp4
```

- **① tts** (`cmd_tts`): synthesizes each line per mood, captures word-level timestamps (`boundary="WordBoundary"` — edge-tts defaults to sentence boundaries, a known pitfall), mixes to exactly 10.0s `.m4a` + `timeline.json`. Line audio is cached by `sha256(voiceId|rate|pitch|text)[:16]` — editing one line's text re-synthesizes only that line.
- **② assets** (`cmd_assets`): renders each HTML text layer twice via Edge headless (white + black background), then `matte_combine` derives alpha (`alpha = 255 − (C_w − C_b)`), so even semi-transparent shadows are extracted precisely.
- **③ render** (`render_card`): per frame — 2x pre-rendered background → 2x RGBA character layer (`draw_character`) with BOX downsample AA → karaoke-clipped text band → badge/pill/bubble → piped raw to ffmpeg. ~36s/card; audio mixing is the only cached stage.

## Invariants (breaking any of these = regression)

From handbook §2/§5 — these were each learned from a real bug:

- **`face_geo()` is the single source of character geometry.** All derived sizes (eyes/mouth/torso/limbs/accessories) and every QA probe sample point derive from it — never hand-copy coordinates (hand-copied probes caused three false failures).
- **Voice params are frozen.** If a line runs over time, shorten the text. Changing rate/pitch invalidates the whole audio cache and breaks voice consistency. `speech_end` must be ≤ 8.5s (tts prints it).
- **Dialogue text lives in two places** — `self-introductions.md` and `intro-cards.json` `lines[].text` — keep them in sync.
- **Word timestamps drive three consumers**: lip openness, karaoke highlight, gesture triggers. Changing lines re-aligns all three automatically; don't add parallel data.
- **No outlines on characters** (flat Duolingo-style fill); scene props may outline only with `pal["ink"]`. Never hardcode RGB in scenes — use the persona palette.
- **Text layers use flow layout only** — `position:absolute`/`transform` break parent-box height under Edge headless. Bubble tails are drawn by PIL on the render side.
- **All randomness must be seeded** via `rnd(f"{seed}:...")` (blink phase, scene jitter). Renders must be byte-identical across runs — idempotency is hash-checked.
- **Layer order**: background → character (2x) → text band → badge → pill → bubble.
- New visual feature ⇒ add a matching probe to `qa_char.py`/`qa_motion.py`.

## Where to change what

- Lines / phonetics / translations → `self-introductions.md` + `intro-cards.json` `lines[].text` (sync both), then `tts` and check `speech_end ≤ 8.5s`
- Moods / gesture triggers → `intro-cards.json` `lines[].mood`, `gestures[]` (gesture keyword must literally exist in the line text, else falls back to line start)
- Closing signature move → `intro-cards.json` `close` (pose codes in `pose_for`, durations in `render_card`)
- Persona (name/voice/palette/hair/accessories) → `personas/personas.json` (qa_char cross-checks palette; run qa_all after color changes)
- Head-body proportions / feature positions → `face_geo()` ratio table only; everything follows automatically, then qa_all + qa_motion
- Scene backgrounds → `@scene(...)` primitives registry in `intro_cards.py` + card `scene[]`
- Badge/pill/bubble styles → `badge_html`/`pill_html`/`bubble_html`, then `run.ps1 assets`; tail color must stay in sync with `UI_INK`
- Adding a language/persona → follow handbook §6.5 checklist
