#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_audio.py — 音轨合成的反向验证

核心是坑③那条顺序纪律：**apad 必须在 loudnorm 之前**（explorateur 实测的
非确定 EOF 冲刷竞态：后置时 10 连跑丢补尾 3 次）。顺序写错不会立刻炸，
只会随机出片——所以用断言钉住 filter_graph 的字符串顺序，不跑 ffmpeg 也能验。

真机 smoke（有 ffmpeg 时才跑）：两段正弦波混到恰好 3.0s，连跑 3 次时长
必须全部相等——这就是坑③的「确定性」验收。缺 ffmpeg/ffprobe 时如实 SKIP。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import audio, platform as pt    # noqa: E402


def check():
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：滤镜图可构建、要素齐全 ----
    g2 = audio.filter_graph(2, [0.0, 1.5], 10.0)
    rows.append((all(x in g2 for x in ("adelay=0|0", "adelay=1500|1500",
                                       "amix=inputs=2:normalize=0",
                                       "apad=whole_dur=10.0", "loudnorm=", "atrim=0:10.0")),
                 f"两行滤镜图要素齐全（{g2[:60]}…）"))
    g1 = audio.filter_graph(1, [0.0], 10.0)
    rows.append(("anull[m]" in g1 and "amix" not in g1,
                 "单行走 anull 直通（滤镜链形状统一，不分叉）"))
    rows.append(("loudnorm=I=-14" in audio.filter_graph(1, [0], 10, loudness_i=-14),
                 "loudness_i 可配（轨道级 -16 / 终混 -14 由调用方定）"))

    # ---- 1. 坑③顺序纪律：apad 必须在 loudnorm 之前 ----
    for g in (g1, g2):
        i_apad, i_loud = g.find("apad=whole_dur"), g.find("loudnorm")
        rows.append((0 <= i_apad < i_loud,
                     f"apad 在 loudnorm 之前（apad@{i_apad} < loudnorm@{i_loud}）"
                     "——后置是实测过的非确定竞态，10 连跑丢补尾 3 次"))

    # ---- 2. 真机 smoke：补齐到恰好 dur，且逐次确定 ----
    ffm, ffpr = pt.ffmpeg(), pt.ffprobe()
    if not (ffm and ffpr):
        rows.append((True, "[SKIP] 真机混音未验（缺 ffmpeg/ffprobe）"))
        return rows
    tmp = tempfile.TemporaryDirectory(prefix="feuille-audio-")
    d = pathlib.Path(tmp.name)
    a1, a2 = d / "a1.mp3", d / "a2.mp3"
    mk = subprocess.run([ffm, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                         "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
                         "-filter_complex", "[0:a][1:a]amix=inputs=2[a]",
                         "-map", "[a]", str(a1)], capture_output=True)
    a2.write_bytes(a1.read_bytes())
    if mk.returncode != 0:
        rows.append((True, "[SKIP] 真机混音未验（ffmpeg 造正弦样本失败）"))
        return rows
    durs = []
    for i in range(3):
        out = d / f"mix{i}.m4a"
        audio.compose_track([a1, a2], [0.0, 1.0], 3.0, out)
        durs.append(round(audio.probe_duration(out), 2))
    rows.append((all(abs(x - 3.0) <= 0.05 for x in durs),
                 f"两行混到恰好 3.0s（apad 补齐 + atrim 裁齐：{durs}）"))
    rows.append((len(set(durs)) == 1,
                 f"连跑 3 次时长逐次相等（坑③的确定性验收：{durs}）"))
    rows.append((abs(audio.probe_duration(a1) - 1.0) < 0.05,
                 "probe_duration 实测正确"))
    return rows


def main() -> int:
    print("=" * 72)
    print("音轨合成（compose_track / probe_duration）")
    print("=" * 72)
    rows = check()
    fails = skips = 0
    for ok, msg in rows:
        if msg.startswith("[SKIP]"):
            skips += 1
            print(f"  [SKIP] {msg[6:]}")
        else:
            fails += not ok
            print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：音轨 {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
