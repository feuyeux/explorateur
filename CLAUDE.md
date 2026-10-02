# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that renders 28 × 10-second character "intro cards" (`build/intro/<id>.mp4`, 1080×1920 @ 30fps, h264+aac) — one per persona in a 14-language teaching-video character cast. Each card = TTS audio + Edge-headless text layers + Pillow frame rendering, composited by ffmpeg. Project docs and code comments are written in Chinese.

**Authoritative docs** — details live there, not here; this file only holds the rules:

- [render-handbook.md](render-handbook.md) — ★ the engineering manual: commands (§0), architecture (§1), invariants (§2), parameter map (§3), QA system (§4), pitfalls (§5), recipes (§6). **Read §3 before changing anything.**
- [plan.md](plan.md) — the plan: persona schema (§4), 28-person cast (§5), demo scene (§6), idempotency rules (§7), pipeline routes (§8).
- [adr-character-tech.md](adr-character-tech.md) — tech-route decision: Pillow pipeline is current; H3+Remotion migration deferred (blueprint).
- [self-introductions.md](self-introductions.md) — content seeds (lines/phonetics/translations per card).
- [README.md](README.md) — newcomer entry.

## Commands

Everything goes through `run.ps1` — see handbook §0 for the full command table. Acceptance baseline after any change: **qa_all 28/28 PASS + qa_motion PASS**.

Two-interpreter split (enforced by run.ps1): **tts** on system `python` (only one with edge-tts); **assets/render/qa** on the bundled DSH Python `C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe` (Pillow + numpy).

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
- Character-generation tech route → see [adr-character-tech.md](adr-character-tech.md) before touching `draw_character`
