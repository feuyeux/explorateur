# une_usine_avec_des_machines_rugissantes

A pipeline that renders **28 × 10-second character "intro cards"** — one per persona in a 14-language teaching-video character cast. Each card is a vertical short (`build/intro/<id>.mp4`, 1080×1920 @ 30fps, h264+aac): TTS audio + Edge-headless text layers + Pillow frame rendering, composited by ffmpeg.

> "A factory with roaring machines" — characters are data (personas), not code.

---

## What's in here

| File | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Project rules, invariants, and "where to change what" map |
| [requirement.md](requirement.md) | Original spec: layout (text/bubble/character zones) + character axes (voice/movement/color/accessories) |
| [plan.md](plan.md) | Full plan: 28-person cast, persona schema, casting rules, idempotency guarantees, staging |
| [render-handbook.md](render-handbook.md) | Engineering handbook — read this before changing the pipeline. §3 is the parameter map; §5 lists real bugs and their fixes |
| [self-introductions.md](self-introductions.md) | Content seeds — lines, phonetics, translations, scene/gesture triggers for each card |
| [adr-character-tech.md](adr-character-tech.md) | Tech decision: migrating character generation from Pillow to MiniMax-H3 + Remotion |
| `personas/personas.json` | 28 persona dossiers — voice/palette/hair/accessories/RTL (single source of truth) |
| `personas/intro-cards.json` | 28 cards — lines, moods, gestures, scene, close-move, A/B cast |
| `intro_cards.py` | The pipeline (tts / assets / render subcommands) |
| `qa_*.py` | Acceptance suite — grid probe, palette probe, full 28-card check, motion check |

---

## Quickstart

Everything goes through [`run.ps1`](run.ps1):

```powershell
.\run.ps1 all                                     # tts → assets → render → qa → qa-motion (~5 min)
.\run.ps1 tts                                     # TTS + word-level timestamps
.\run.ps1 assets                                  # text-layer PNGs via Edge headless
.\run.ps1 render -Only xiaoman,layla -Workers 7   # frames + ffmpeg
.\run.ps1 qa                                      # full acceptance (28/28)
.\run.ps1 qa-motion                               # karaoke / lip-sync / blink / bubble-mirror
```

### Two interpreters (enforced by `run.ps1`)

- **tts** runs on **system `python`** — the only one with `edge-tts` installed.
- **assets / render / qa** run on the **bundled DSH Python** at `C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe` (has Pillow + numpy).

Direct equivalents:

```powershell
python intro_cards.py tts|assets|render [--only id1,id2] [--workers 7]
```

### Acceptance baseline

After any change: **qa_all 28/28 PASS + qa_motion PASS**.

---

## How it works

```
personas/personas.json       (28 persona dossiers)
personas/intro-cards.json    (28 cards: lines/moods/gestures/scene/cast)
        └→ ① tts → ② assets → ③ render → build/intro/<id>.mp4
```

1. **tts** — synthesizes each line per mood, captures word-level timestamps, mixes to a 10.0 s `.m4a` + `timeline.json`. Line audio is cached by `sha256(voiceId|rate|pitch|text)[:16]`, so editing one line only re-synthesizes that line.
2. **assets** — renders each HTML text layer twice via Edge headless (white + black background), then `matte_combine` extracts precise alpha — even semi-transparent shadows.
3. **render** — per frame: 2× background → 2× RGBA character layer (`draw_character`) with BOX downsample AA → karaoke-clipped text band → badge/pill/bubble → piped raw to ffmpeg.

See [render-handbook.md §1](render-handbook.md) for the full architecture diagram and caching model.

---

## Design principles

A short version of [CLAUDE.md](CLAUDE.md) and [plan.md §3](plan.md):

- **Persona is data, not code.** `personas.json` drives the rig; never hardcode RGB, mouth shapes, or blink timing per-character in scenes.
- **Word timestamps drive three things at once:** lip openness, karaoke highlight, gesture triggers. One axis, three consumers.
- **Idempotency is enforced.** All randomness seeded (`rnd(seed:...)`); same inputs → byte-identical output (hash-checked).
- **No outlines on characters** (flat Duolingo-style fill); scenes may outline only with `pal["ink"]`.
- **Mood and gesture are data, not freelancing.** A shared mood table (`neutral / happy / puzzled / encouraging / emphatic / teach`) plus per-line baseline yields the synthesis parameters.

---

## The cast

14 languages × male/female = 28 personas. Each language has one *lively* and one *steady* partner — natural conversational tension, and acoustic diversity within one language.

| Locale | Female | Male | Locale | Female | Male |
|---|---|---|---|---|---|
| zh-CN | 林小满 | 江远 | ja-JP | ハルカ | リク |
| en-US | Ruby | Miles | ko-KR | 서연 | 도윤 |
| fr-FR | Chloé | Théo | it-IT | Giulia | Luca |
| de-DE | Lena | Felix | he-IL | נועה | יובל |
| es-ES | Lucía | Mateo | zh-HK | 阿晴 | 阿豪 |
| ru-RU | Аня | Миша | | | |
| el-GR | Ελένη | Νίκος | hi-IN | प्रिया | अर्जुन |
| ar-SA | ليلى | عمر | | | |

Full dossiers (voice id, palette, signature moves, accessories, relationship) — [plan.md §5](plan.md).

---

## Where to change what

| You want to change | Edit |
|---|---|
| Lines / phonetics / translations | `self-introductions.md` + `intro-cards.json` `lines[].text` (sync both), then `tts` and check `speech_end ≤ 8.5s` |
| Moods / gesture triggers | `intro-cards.json` `lines[].mood`, `gestures[]` |
| Closing signature move | `intro-cards.json` `close` (pose codes in `pose_for`) |
| Persona (name/voice/palette/hair/accessories) | `personas/personas.json` (qa_char cross-checks palette) |
| Head-body proportions / feature positions | `face_geo()` ratio table only; everything follows automatically |
| Scene backgrounds | `@scene(...)` primitives registry in `intro_cards.py` + card `scene[]` |
| Badge / pill / bubble styles | `badge_html` / `pill_html` / `bubble_html` |
| Tech stack (currently migrating) | see [adr-character-tech.md](adr-character-tech.md) |

**Invariants** — see [render-handbook.md §2](render-handbook.md) and [CLAUDE.md](CLAUDE.md). Each was learned from a real bug; breaking them is a regression.
