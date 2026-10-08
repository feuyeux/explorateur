#!/usr/bin/env python3
"""TTS narration with token-level karaoke timings (edge-tts neural voices).

Usage:
    gen_tts.py voices.json [tts_out_dir]

voices.json: {"tts_dir": "tts", "langs": [{locale, voice, text, tokens, persona, latin, gender}, ...]}
  - `text`     — the exact TTS input phrase (spaces allowed)
  - `tokens`   — display tokens as CONSECUTIVE char ranges of `text`
                 (joined, spaces between tokens excluded from matching)

Produces per language:
  <tts_dir>/<locale>.mp3    spoken phrase (24 kHz mono mp3)
  <tts_dir>/<locale>.json   word boundaries + display-token timings (seconds)

Karaoke semantics: edge-tts WordBoundary events may span several display
tokens (zh "一本" covers 一+本). The boundary duration is split
proportionally by character position, so each token gets its own start/end
and the highlight can switch per character.
"""
import asyncio, json, pathlib, sys

try:
    import edge_tts
except ImportError:
    sys.exit("pip install edge-tts")


def token_timings(tokens, words):
    """Map word boundaries (which may span tokens) onto display tokens.

    Accumulates non-space chars of the token stream; each boundary covers
    len(word) chars. A token's start = boundary start + proportional offset
    of the chars consumed inside that boundary; its end = boundary end.
    """
    stream = "".join(tokens)
    spans = []  # (start_char, end_char, token_idx) in stream coords
    pos = 0
    for i, t in enumerate(tokens):
        spans.append((pos, pos + len(t), i))
        pos += len(t)
    assert pos == len(stream), "tokens must be consecutive char ranges of the input"

    tok_start = {i: None for i in range(len(tokens))}
    tok_end = {i: None for i in range(len(tokens))}
    cpos = 0
    for w in words:
        wl = max(1, len(w["w"]))
        while cpos < len(stream) and stream[cpos] == " ":
            cpos += 1
        cov = wl
        touched = []
        while cov > 0 and cpos < len(stream):
            if stream[cpos] == " ":
                cpos += 1
                continue
            idx = next(i for (a, b, i) in spans if a <= cpos < b)
            a, b, _ = spans[idx]
            take = min(cov, b - cpos)
            into = wl - cov  # chars of this boundary already consumed
            if tok_start[idx] is None:
                tok_start[idx] = w["t"] + w["d"] * (into / wl)
            touched.append(idx)
            cov -= take
            cpos += take
        for idx in touched:
            tok_end[idx] = w["t"] + w["d"]

    return [dict(text=t, start=tok_start[i], end=tok_end[i])
            for i, t in enumerate(tokens)]


async def gen(out_dir, lang):
    c = edge_tts.Communicate(lang["text"], lang["voice"], boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in c.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append(dict(w=chunk["text"], t=chunk["offset"] / 1e7,
                              d=chunk["duration"] / 1e7))
    (out_dir / f'{lang["locale"]}.mp3').write_bytes(bytes(audio))

    tk = token_timings(lang["tokens"], words)
    data = dict(locale=lang["locale"], persona=lang.get("persona"),
                latin=lang.get("latin"), gender=lang.get("gender"),
                text=lang["text"], words=words, tokens=tk)
    (out_dir / f'{lang["locale"]}.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=1))
    return data


async def main():
    cfg = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out_dir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else cfg.get("tts_dir", "tts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for lang in cfg["langs"]:
        d = await gen(out_dir, lang)
        toks = " | ".join(f'{t["text"]} {t["start"]:.2f}-{t["end"]:.2f}'
                          for t in d["tokens"])
        print(f'{lang["locale"]}: {toks}')

asyncio.run(main())
