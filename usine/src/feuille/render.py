# -*- coding: utf-8 -*-
"""render.py — 帧编码基座（⑥ 视频：rawvideo → ffmpeg 管道）

encode_frames 只管视频帧；音频合成与终混在 feuille.audio / feuille.compose，
卡片级编排由调用方组合 rig + scenes + timeline + textlayer 完成。

口径：`-f rawvideo -pix_fmt rgb24 -s WxH -r FPS` 管道输入；libx264 / yuv420p /
`+faststart` 输出；时长控制 = 显式 `-t dur`（与 compose.mux 同口径）。

硬约定：
- 不用 `-shortest`——它是时机性丢帧开关（高并发下丢 pts 帧、单渲不丢，
  framehash 幂等必挂），详见 encode_frames 内注释。
- ffmpeg 经 resolver（feuille.platform.ffmpeg()），找不到显式报缺。
- rc 非零显式抛错，坏产物不静默留盘（纪律 19）。
- 帧数契约：调用方须供足 ⌈dur×fps⌉ 帧；帧不足时 rawvideo 流先尽、
  产物短于 dur 且无提示——不做静默补帧。
- preset 默认 slow（单件质量口径，与 compose.mux 对齐；调用方可覆盖）。
"""

import subprocess

from . import platform as _pt


def encode_frames(frame_iter, out_mp4, *, w, h, fps, dur, crf=18, preset="slow") -> int:
    """逐帧喂 PIL Image 的 rawvideo→ffmpeg 编码器。

    frame_iter 产出尺寸 (w, h) 的 PIL Image；非 RGB（如 RGBA 图层）自动 convert，
    防御直喂导致字节流错位。返回实际喂入的帧数；ffmpeg 非零退出抛 RuntimeError。
    """
    ffmpeg = _pt.ffmpeg()
    if ffmpeg is None:
        raise SystemExit("缺 ffmpeg（resolver 未找到；缺件清单见 feuille.platform.missing()）")
    # 禁用 -shortest：EOF 冲刷时按已入队包随时机丢视频帧（实测高并发批量下
    # 丢帧、单渲不丢 → framehash 幂等必挂）。纯视频管道，-t dur 是唯一时长开关。
    cmd = [ffmpeg, "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-t", str(dur), "-movflags", "+faststart", str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n = 0
    for img in frame_iter:
        if img.mode != "RGB":
            img = img.convert("RGB")
        proc.stdin.write(img.tobytes())
        n += 1
    proc.stdin.close()
    rc = proc.wait()
    if rc:
        raise RuntimeError(f"ffmpeg 退出码 {rc}（已喂 {n} 帧）→ {out_mp4}")
    return n
