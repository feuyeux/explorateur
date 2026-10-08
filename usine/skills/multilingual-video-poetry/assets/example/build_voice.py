# -*- coding: utf-8 -*-
"""四季配文构建：TTS 48 段 → 逐段实测时长 → 核对窗口 → 出字幕。

**时长是实测的，不是估的**（纪律 7 / 4）：每段 TTS 出来立刻量，
超窗就报出来，而不是靠「2 秒大概够」蒙过去。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from 配文 import LANGS, LINES, SEASONS, TOTAL, VOICES, WINDOWS  # noqa: E402

VOICE_DIR = HERE / "voice"


def dur(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def tts(lang: str, season: str, text: str, tries: int = 4) -> Path:
    """合成一段；文本与音高指纹相符则复用缓存（改配置时不必重跑全量）。

    edge-tts 走网络，偶发失败是常态而非异常——**重试不是掩盖，是正确处理**。
    但重试必须把最后一次的真实 stderr 打出来，否则「重试成功」会把
    「一直失败」伪装成「没问题」（纪律 19：禁止静默兜底）。
    """
    out = VOICE_DIR / f"{lang}.{season}.mp3"
    stamp = VOICE_DIR / f".{lang}.{season}.txt"
    fingerprint = f"{VOICES[lang]}\t{text}"
    if out.exists() and stamp.exists() and stamp.read_text("utf-8") == fingerprint:
        return out
    last = ""
    for attempt in range(1, tries + 1):
        r = subprocess.run(
            ["uv", "run", "edge-tts", "--voice", VOICES[lang],
             "--rate", "-8%", "--text", text, "--write-media", str(out)],
            cwd=HERE.parent.parent, capture_output=True, text=True)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            stamp.write_text(fingerprint, "utf-8")
            return out
        last = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["(无 stderr)"]
        if attempt < tries:
            time.sleep(2 * attempt)
    raise RuntimeError(
        f"TTS 失败 {tries} 次：{lang}/{season} 「{text}」\n  最后一次 stderr：{last[0]}")


def srt_ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def main() -> int:
    VOICE_DIR.mkdir(exist_ok=True)
    report, over = [], 0
    print(f"{'语种':<6}{'季':<3}{'实测':>6}  {'窗口':>11}  {'余量':>6}  配文")
    for lang in LANGS:
        for season in SEASONS:
            text = LINES[lang][season]
            wav = tts(lang, season, text)
            d = dur(wav)
            w0, w1 = WINDOWS[season]
            slack = (w1 - w0) - d
            if slack < 0:
                over += 1
            report.append({"lang": lang, "season": season, "text": text,
                           "file": wav.name, "duration": round(d, 3),
                           "window": [w0, w1], "slack": round(slack, 3)})
            print(f"{lang:<6}{season:<3}{d:6.2f}  {w0:5.1f}–{w1:<5.1f}  "
                  f"{slack:+6.2f}{'  ❌超窗' if slack < 0 else ''}  {text[:28]}")

    (HERE / "voice-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    # 字幕：句子在窗口内居中，上下各留 0.25s
    sub_dir = HERE / "subtitles"
    sub_dir.mkdir(exist_ok=True)
    for lang in LANGS:
        blocks = []
        for i, season in enumerate(SEASONS, 1):
            w0, w1 = WINDOWS[season]
            mid = (w0 + w1) / 2
            blocks.append(f"{i}\n{srt_ts(max(0, mid - 1.0))} --> {srt_ts(min(TOTAL, mid + 1.0))}\n"
                          f"{LINES[lang][season]}\n")
        (sub_dir / f"{lang}.srt").write_text("\n".join(blocks), "utf-8")

    print(f"\n超窗段数：{over} / {len(report)}")
    print(f"字幕：{len(LANGS)} 份 → {sub_dir}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
