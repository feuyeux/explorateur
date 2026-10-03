# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that renders 28 × 10-second character "intro cards" (`build/intro/<id>.mp4`, 1080×1920 @ 30fps, h264+aac) — one per persona in a 14-language teaching-video character cast, plus 4 gender-adapted RTL "female viewer" variants (`<id>_f.mp4`, self-intro §1.4). Each card = TTS audio + Edge-headless text layers + Pillow frame rendering, composited by ffmpeg. A second line renders teaching scenes (scene-agnostic): `scenes/scene-<id>.md` → `build/scene/scene-<id>_<locale>.mp4` (A/B dialogue, 40–55s per locale) via `parse_scene.py --scene <id>` + `scene_video.py`, reusing the same character rig. A new teaching scene = a new `scenes/scene-<id>.md` following the documented §0 machine-readable spec — zero pipeline-code changes. Project docs and code comments are written in Chinese.

**Authoritative docs** — details live there, not here; this file only holds the rules:

- [render-handbook.md](docs/render-handbook.md) — ★ the engineering manual: commands (§0), architecture (§1), invariants (§2), parameter map (§3), QA system (§4), pitfalls (§5), recipes (§6). **Read §3 before changing anything.**
- [plan.md](docs/plan.md) — the plan: persona schema (§4), 28-person cast (§5), demo scene (§6), idempotency rules (§7), pipeline routes (§8).
- [adr-character-tech.md](docs/adr-character-tech.md) — tech-route decision: Pillow pipeline is current; H3+Remotion migration deferred (blueprint).
- [benchmark-duolingo.md](docs/benchmark-duolingo.md) — Duolingo-KB benchmark ledger: per-item verdicts (adopted / added / deferred / rejected) + quirk governance rules (§4.2).
- [self-introductions.md](docs/self-introductions.md) — content seeds (lines/phonetics/translations per card).
- [scene-colors.md](scenes/scene-colors.md) — demo scene 2 seed: six-color Q&A dialogue. Shared skeleton only; scripts are **natively authored per locale** (idiomatic question patterns, culture-native associations, per-locale props) — never translated from any master (§1.2 independence rules).
- [README.md](README.md) — newcomer entry.

## Commands

Everything goes through `run.ps1` — see handbook §0 for the full command table. Acceptance baseline after any change: **qa_all 32/32 PASS（28 卡 + 4 个 RTL 女性观众版）+ qa_motion PASS**; scene line: **qa_scene.py PASS**.

**uv-managed single environment** — the project is a standard uv project (`pyproject.toml`, src layout): pipeline/QA/lesson code lives in `src/usine/` (import as `from usine import ROOT`), standalone douyin tools in `scripts/`, and one `.venv` (uv-managed CPython 3.12) serves all phases — run.ps1 wraps everything in `uv run`, console scripts `usine-cards` / `usine-parse` / `usine-scene` / `usine-lesson` / `usine-dump-lesson` are installed as entry points. Dependencies are exact-pinned (`edge-tts==7.2.8`, `pillow==12.3.0`, `numpy==2.3.5`); Pillow 12.3.0 is the pixel baseline — never upgrade it without re-verifying the framehash baselines. If `.venv` is missing, `uv sync` (run.ps1 does this automatically).

## Invariants (full table: handbook §2; each was learned from a real bug, handbook §5)

1. **`face_geo()` is the single source of character geometry** — never hand-copy coordinates (hand-copied probes caused three false failures, pit ⑨).
2. **Voice params are frozen** — if a line runs over time, shorten the text (cache key includes voice params; changing them re-synthesizes everything).
3. **Dialogue text lives in two places** — `self-introductions.md` + `intro-cards.json` `lines[].text` — keep in sync.
4. **Word timestamps drive three consumers** (lip openness, karaoke highlight, gesture triggers) — don't add parallel data.
5. **No outlines on characters**; scene props outline only with `pal["ink"]`; never hardcode RGB in scenes.
6. **Text layers use flow layout only** — `position:absolute`/`transform` break parent-box height under Edge headless (pit ⑦).
7. **All randomness seeded** via `rnd(f"{seed}:...")`; idempotency is verified by **video-stream framehash** (`ffmpeg -map 0:v -f hash -hash md5`), not whole-file bytes (pit ⑫).
8. **Layer order**: background → character (2x) → text band → badge → pill → bubble.
9. **Edge headless window-size ≠ viewport** on this machine (−94px); `cmd_assets` auto-compensates via a probe — never hardcode a window height (pit ⑩).
10. **New visual feature ⇒ add a matching probe** to `qa_char.py`/`qa_motion.py`; probe sample points must derive from `face_geo`.

## Where to change what

Full map: handbook §3. The most-used rows:

- Lines / moods / gestures / close moves → `intro-cards.json` (+ sync `self-introductions.md`), then `tts` / `render -Only <id>`
- Persona (name/voice/palette/hair/accessories) → `personas/personas.json` (qa_char cross-checks palette)
- Head-body proportions → `face_geo()` ratio table only; everything follows automatically
- Character-generation tech route → see [adr-character-tech.md](docs/adr-character-tech.md) before touching `draw_character`
- **New teaching scene** (numbers / food / greetings …) → new `scenes/scene-<id>.md` copying the §0 machine-readable spec (token table + device table) + §2 dialogue + §5 word table, then `.\run.ps1 scene -Scene <id>` — **zero pipeline changes**
- Scene script text / tokens / RTL locales / device geometry → `scenes/scene-<id>.md` **only** (never hand-edit `scene_<id>.json`; re-run `parse_scene.py --scene <id>`, then `scene -Scene <id> -Only <locale>`)
- Scene casting A/B, layout constants, device style library → `scene_video.py`; casting is *derived* from `intro-cards.json` `cast`, never hardcoded; device geometry (well/shape/cell size) comes from the scene md §0.2, never code
- New pose primitive → `pose_for()` in `intro_cards.py` (shared by both lines) + a probe in the matching qa script
