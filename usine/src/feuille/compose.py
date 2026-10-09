# -*- coding: utf-8 -*-
"""compose.py — 母版叠加合成（⑥ 视频：H3 母版 + 文字层 + 人声轨 → 成片）

ffmpeg 走 resolver；滤镜图是纯函数，可被反向验证直接断言。

**两声道与两次响度**：
- 人声轨先经 `audio.compose_track`（轨道级 loudnorm −16、apad 前置）；
- 终混在**长度已锁死**的混合流上再过一次 loudnorm（社媒目标 −14 LUFS——
  直送只有 −20，太轻）。此时流内没有 apad，「apad 必须在 loudnorm 前」
  不被违反：所有 apad 都在 loudnorm 之前完成。

**禁用 `-shortest`**：在 rawvideo 管道 + 并发场景下它是**时机性丢帧**开关
（批量渲丢 pts 帧、单渲不丢，幂等必挂）。裁到目标时长的真实功能交给显式
`-t dur`——**封装命令里不许有依赖 I/O 时序的取舍开关**。

`subtitle_spans` 的口径：每行字幕多留 HOLD 拍，行间不重叠（min(尾拍, 下一行起点)）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from . import platform as _pt


def line_spans(starts: Sequence[float], durs: Sequence[float], *, total: float,
               hold: float = 0.30) -> list[tuple[float, float]]:
    """每行的上屏区间 (t0, t1)：t0 = 起点，t1 = min(本行末 + hold, 下一行起点)。

    末行以 total 收尾。行间永不重叠——下一行的起点就是本行的硬上限。
    """
    spans = []
    for i, (s, d) in enumerate(zip(starts, durs)):
        t0 = s
        t1 = t0 + d
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        end = min(t1 + hold, nxt) if nxt is not None else min(t1 + hold, total)
        spans.append((round(t0, 3), round(end, 3)))
    return spans


def filter_graph(w: int, h: int, n_overlays: int, dur: float, *, music_vol: float = 0.30,
                 loudness_i: int = -14, fps: int = 24) -> tuple[str, str]:
    """构建终混滤镜图（纯函数，供 mux 与反向验证共用）。返回 (滤镜图, 视频末段标签)。

    输入布局：0=母版（视频+配乐），1=人声，2..n=文字层 PNG。
    overlay 的 {y} / {between} 是留给 mux 按层填的槽；dur 直接内插。
    """
    fc = [f"[0:v]scale={w}:{h}:flags=lanczos,fps={fps}[base]"]
    cur = "base"
    for i in range(n_overlays):
        nxt = f"v{i}"
        fc.append(f"[{cur}][{i + 2}:v]overlay=0:{{y}}:enable='between(t,{{between}})'[{nxt}]")
        cur = nxt
    fc.append(f"[0:a]volume={music_vol}[bg]")
    fc.append(f"[1:a]apad=whole_dur={dur:.3f},atrim=0:{dur:.3f}[vo]")
    # 终混 loudnorm：流长已锁死（见模块头），apad 全部在它之前——坑③不被违反
    fc.append(f"[bg][vo]amix=inputs=2:normalize=0,"
              f"loudnorm=I={loudness_i}:TP=-1.5:LRA=11[aout]")
    return ";".join(fc), cur


def mux(master, voice, overlays, out, *, w: int, h: int, dur: float,
        music_vol: float = 0.30, loudness_i: int = -14, fps: int = 24,
        preset: str = "slow", crf: int = 18) -> Path:
    """母版 + 文字层叠加 + 双声道终混 → 成片。

    overlays: [(png 路径, y 偏移, t0, t1), ...]——文字层按 enable='between(t,t0,t1)'
    上屏；索引别和 ffmpeg 输入序号混（0=母版 1=人声 2..=文字层）。
    """
    ffmpeg = _pt.ffmpeg()
    if ffmpeg is None:
        raise SystemExit("缺 ffmpeg（resolver 未找到；缺件清单见 feuille.platform.missing()）")
    graph, vlabel = filter_graph(w, h, len(overlays), dur, music_vol=music_vol,
                                 loudness_i=loudness_i, fps=fps)
    # 把每层 overlay 的 y / 时间窗填回图里（纯函数留槽，这里按序填值）
    for png, y, t0, t1 in overlays:
        graph = graph.replace("{y}", str(y), 1).replace(
            "{between}", f"{t0:.3f},{t1:.3f}", 1)
    cmd = [ffmpeg, "-y", "-i", str(master), "-i", str(voice)]
    for png, *_ in overlays:
        cmd += ["-i", str(png)]
    cmd += ["-filter_complex", graph,
            "-map", f"[{vlabel}]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart",
            # -shortest 已废（坑⑯，见模块头）：时长控制显式交给 -t
            "-t", f"{dur:.3f}", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError("ffmpeg 失败：\n" + p.stderr[-2500:])
    return Path(out)
