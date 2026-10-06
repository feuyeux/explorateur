# -*- coding: utf-8 -*-
"""timeline.py — 行时间轴与词级进度轴（⑤ 补齐 + ⑥ 渲染共用）

合并自 yiyezhiqiu.rebuild_timeline（start 累进口径）与 explorateur.media 的
卡拉OK进度轴（karaoke_points / frac_at——「词级时间戳一轴多用」里的渲染轴：
换台词自动重对齐，不需要新数据）。

口径（与已验收的 24 支成片一致）：

    start[0]     = 0
    start[i]     = start[i-1] + speech_dur[i-1] + line_gap
    tail_silence = file_dur - speech_dur        # edge-tts 垫的尾静音，行距吸收它

`speech_dur` 取词级时间戳的行时长（tts.effective_dur），`file_dur` 由
ffprobe 实测 mp3——**一律实测，不用清单里手抄的值**。
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .audio import probe_duration


def compute_starts(speech_durs: Sequence[float], gap: float) -> list[float]:
    """纯函数：行起始秒累进。start[0]=0，其后 = 前一起点 + 前一行语音长 + 行距。"""
    starts: list[float] = []
    t = 0.0
    for d in speech_durs:
        starts.append(round(t, 3))
        t = t + d + gap
    return starts


def enrich_lines(lines: list[dict], gap: float, audio_dir) -> tuple[float, float]:
    """就地补齐每行的 speech_dur / file_dur / tail_silence / start，
    返回 (total_dur, span_dur)。

    lines 每项需带 `key`（缓存文件名）与 `dur`（词级真值行时长）；
    mp3 路径 = audio_dir/{key}.mp3。
    """
    audio_dir = Path(audio_dir)
    speech_durs = [round(float(ln["dur"]), 3) for ln in lines]
    starts = compute_starts(speech_durs, gap)
    for ln, s, speech in zip(lines, starts, speech_durs):
        file_dur = round(probe_duration(audio_dir / f"{ln['key']}.mp3"), 3)
        ln["speech_dur"] = speech
        ln["file_dur"] = file_dur
        ln["tail_silence"] = round(file_dur - speech, 3)
        ln["start"] = s
    total = round(sum(speech_durs), 3)
    span = round(sum(speech_durs) + gap * max(0, len(lines) - 1), 3)
    return total, span


# ---------------------------------------------------------------- 词级进度轴

def karaoke_points(line: dict) -> list[tuple[float, float]]:
    """一行台词的 [(t, frac)] 词首/词尾字符进度点。

    词级时间戳一轴多用（口型开合 / 逐词高亮 / 手势触发）里卡拉OK那轴的唯一实现。
    line 需带 `words`（**绝对**时间戳：每词 s/e 秒）、`start`、`dur`——
    相对词表（tts 输出的 t/d）要先加 start 转成绝对时间。
    """
    words = line["words"]
    total = sum(len(w["w"]) for w in words) + max(0, len(words) - 1)
    pts = [(line["start"], 0.0)]
    c = 0.0
    for i, w in enumerate(words):
        c += len(w["w"])
        pts.append((max(w["s"], line["start"]), c / total))
        c += 1 if i < len(words) - 1 else 0
        pts.append((w["e"], c / total))
    pts.append((line["start"] + line["dur"] + 0.15, 1.0))
    return pts


def frac_at(pts: list[tuple[float, float]], t: float) -> float:
    """在进度点上线性插值取 t 时刻的字符进度 [0,1]。区间外夹到 0 / 1。"""
    if t <= pts[0][0]:
        return 0.0
    for i in range(1, len(pts)):
        if t <= pts[i][0]:
            t0, f0 = pts[i - 1]
            t1, f1 = pts[i]
            if t1 <= t0:
                return f1
            return f0 + (f1 - f0) * (t - t0) / (t1 - t0)
    return 1.0
