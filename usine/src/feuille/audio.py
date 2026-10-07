# -*- coding: utf-8 -*-
"""audio.py — ffmpeg 音轨合成与时长探测

搬运自 explorateur/src/usine/media.py 的音频半边（终态视角重构：ffmpeg/ffprobe
改走 `feuille.platform` 解析；滤镜图提成纯函数，让顺序纪律可被反向验证直接断言）。

**坑③（explorateur 2026-10-03 实测的非确定竞态，顺序不许动）**：`apad=whole_dur=`
必须放在 `loudnorm` **之前**。loudnorm 内部升采样到 192k，之后接 apad 是非确定的
EOF 冲刷竞态——同命令 10 连跑丢补尾 3 次（9.469s），前置后 10/10 全 10.0s。
loudnorm 是门控响度，补的静音不改变增益；对已 ≥dur 的流是 no-op。

**为什么必须只有一份**（explorateur 收债时的教训）：此逻辑曾在两条管线各写一份，
坑③的修法写了两遍，`frac_at` 一边隐式 None 一边显式 1.0——坑③只修一侧 =
另一侧继续随机出片。共用内核让修复只有一处。

`atrim` 只裁不补：amix 的输出止于最长行的**原始 mp3 尾**（非裁尾时长）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from . import platform as _pt


def _require(tool: str | None, what: str) -> str:
    """resolver 拿不到就显式报缺，绝不退化「用系统默认」。"""
    if tool is None:
        raise SystemExit(f"缺 {what}（resolver 未找到；缺件清单见 feuille.platform.missing()）")
    return tool


def filter_graph(n: int, starts: Sequence[float], dur: float, loudness_i: int = -16) -> str:
    """构建 filter_complex 字符串（纯函数，供 compose_track 与反向验证共用）。

    n==1 也过一层 anull：PCM 不变（anull 直通），但滤镜链形状统一、不必分支
    （explorateur 曾一边 mix 直连、一边 anull[m]，两份实现就此漂移）。
    """
    fc = []
    for i, s in enumerate(starts):
        ms = int(round(s * 1000))
        fc.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]")
    mixin = "".join(f"[a{i}]" for i in range(n))
    fc.append(f"{mixin}amix=inputs={n}:normalize=0[m]" if n > 1 else f"{mixin}anull[m]")
    # 坑③：apad 必须在 loudnorm 之前（见模块头）——顺序是纪律，不许动
    fc.append(f"[m]apad=whole_dur={dur},loudnorm=I={loudness_i}:TP=-1.5:LRA=11,"
              f"atrim=0:{dur}[out]")
    return ";".join(fc)


def compose_track(line_files, starts, dur, out_m4a, loudness_i: int = -16) -> None:
    """把逐行 m4a/mp3 按 starts 延迟叠加、归一化响度、补齐到恰好 dur 秒。

    Args:
        line_files: 逐行音频路径（顺序即输入序号）
        starts: 每行起始秒（与 line_files 同序）
        dur: 目标时长秒；补齐（apad）与裁齐（atrim）都用它
        out_m4a: 输出 m4a 路径
        loudness_i: loudnorm 目标响度（explorateur 轨道级 -16；
                    终混社媒惯例 -14 由调用方在封装时传入）
    """
    ffmpeg = _require(_pt.ffmpeg(), "ffmpeg")
    inputs: list[str] = []
    for f in line_files:
        inputs += ["-i", str(f)]
    fc = filter_graph(len(line_files), starts, dur, loudness_i)
    subprocess.run([ffmpeg, "-y", *inputs, "-filter_complex", fc, "-map", "[out]",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out_m4a)],
                   check=True, capture_output=True)


def probe_duration(path) -> float:
    """ffprobe 取容器时长（秒）。edge-tts 的 mp3 尾部垫了静音，
    词级真值裁尾（见 tts.effective_dur）要用它做上限。"""
    ffprobe = _require(_pt.ffprobe(), "ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)
