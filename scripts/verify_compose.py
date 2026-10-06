#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_compose.py — 母版叠加合成的反向验证

纯函数层：滤镜图要素（缩放/逐层 overlay enable/配乐压低/人声补齐/终混 loudnorm）、
坑③口径（所有 apad 都在 loudnorm 之前）、坑⑯口径（命令里没有 -shortest，
时长控制显式交给 -t）。

真机 smoke（有 ffmpeg 时）：3s 灰底「母版」+ 1s 人声 + 一块红色文字层
（enable 1.0–2.0s）→ 成片恰好 dur；t=0.5s 的帧无红、t=1.5s 的帧是红
——enable='between' 真生效，不是只看命令拼对。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import audio, compose, platform as pt    # noqa: E402


def check():
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：line_spans 口径 ----
    spans = compose.line_spans([0.0, 1.0, 2.5], [0.8, 0.8, 0.8], total=4.0, hold=0.3)
    want = [(0.0, 1.0), (1.0, 2.1), (2.5, 3.6)]
    rows.append((spans == want, f"行区间：不重叠、尾行留 hold（{spans}）"))

    # ---- 1. 滤镜图要素 ----
    graph, vlabel = compose.filter_graph(1080, 1920, 2, 15.0)
    rows.append((vlabel == "v1", f"视频末段标签正确（{vlabel}）"))
    rows.append((all(x in graph for x in ("[0:v]scale=1080:1920:flags=lanczos,fps=24[base]",
                                          "overlay=0:{y}:enable='between(t,{between})'", "[v0]",
                                          "[0:a]volume=0.3[bg]",
                                          "apad=whole_dur=15.000,atrim=0:15.000",
                                          "amix=inputs=2:normalize=0,loudnorm=I=-14")),
                 "两层层级齐全（缩放→逐层 overlay→配乐压低→人声补齐→终混）"))
    _, v0 = compose.filter_graph(100, 100, 0, 10.0)
    rows.append((v0 == "base", "零 overlay 时末段是 [base]"))

    # ---- 2. 坑③口径：所有 apad 都在 loudnorm 之前 ----
    rows.append((graph.find("apad=whole_dur") < graph.find("loudnorm"),
                 "apad 在 loudnorm 之前（坑③：后置是非确定竞态）"))

    # ---- 3. 坑⑯口径：没有 -shortest，时长显式交给 -t ----
    import inspect
    src = inspect.getsource(compose.mux)
    rows.append(("-shortest" not in src.replace("# -shortest 已废", "").replace("（坑⑯，见模块头）", ""),
                 "mux 命令不含 -shortest（坑⑯：时机性丢帧开关已废）"))
    rows.append(('"-t", f"{dur:.3f}"' in src, "时长控制显式 -t dur"))

    # ---- 4. 真机 smoke：红块 overlay 的 enable 生效 ----
    ffm, ffpr = pt.ffmpeg(), pt.ffprobe()
    if not (ffm and ffpr):
        rows.append((True, "[SKIP] 真机合成未验（缺 ffmpeg/ffprobe）"))
        return rows
    import numpy as np
    from PIL import Image

    tmp = tempfile.TemporaryDirectory(prefix="feuille-compose-")
    d = pathlib.Path(tmp.name)
    master = d / "master.mp4"
    r = subprocess.run([ffm, "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=320x240:d=3.0",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3.0",
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(master)], capture_output=True)
    if r.returncode != 0:
        rows.append((True, "[SKIP] 真机合成未验（造母版失败）"))
        return rows
    # 人声轨：1s 正弦 → compose_track 补齐到 3.0s（坑③口径的轨道级处理）
    voice_in = d / "v.mp3"
    subprocess.run([ffm, "-y", "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
                    str(voice_in)], capture_output=True, check=True)
    voice = d / "voice.m4a"
    audio.compose_track([str(voice_in)], [0.0], 3.0, voice)
    # 红块文字层（全幅红，y=0）
    ov = d / "ov.png"
    Image.new("RGBA", (320, 240), (255, 0, 0, 255)).save(ov)
    out = d / "out.mp4"
    compose.mux(master, voice, [(ov, 0, 1.0, 2.0)], out, w=320, h=240, dur=3.0,
                preset="veryfast")

    from feuille.audio import probe_duration
    dur = probe_duration(out)
    rows.append((abs(dur - 3.0) <= 0.12,
                 f"成片时长 ≈3.0s（-t 显式裁齐：{dur:.2f}s）"))

    def frame_pixel(t, tag):
        png = d / f"f_{tag}.png"
        subprocess.run([ffm, "-y", "-ss", f"{t}", "-i", str(out),
                        "-frames:v", "1", str(png)], capture_output=True, check=True)
        return np.asarray(Image.open(png).convert("RGB"))

    off = frame_pixel(0.5, "off")
    on = frame_pixel(1.5, "on")
    rows.append((abs(float(on[..., 0].mean()) - 255) < 20 and float(on[..., 1].mean()) < 60,
                 f"t=1.5 帧是红（R {on[..., 0].mean():.0f} G {on[..., 1].mean():.0f}）"
                 "——enable='between' 真生效"))
    rows.append((abs(float(off[..., 0].mean()) - 128) < 12,
                 f"t=0.5 帧无红（R {off[..., 0].mean():.0f}，灰底 128）"))
    # 音频流存在（双声道终混）
    probe = subprocess.run([ffpr, "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    rows.append((probe.startswith("aac"), f"音轨存在且为 aac（{probe}）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("母版叠加合成（filter_graph / line_spans / mux）")
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
    print(f"{'OK' if not fails else 'FAIL'}：合成 {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
