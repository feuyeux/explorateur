# -*- coding: utf-8 -*-
"""render.py — 帧编码基座（⑥ 视频：rawvideo → ffmpeg 管道）

搬运自 explorateur/src/usine/intro_cards.py 2086–2320（render_card 的编码管道，
提取为通用的 encode_frames）。render_card 本身**不搬**：intro 卡片编排
（文字带 / 名牌 / 语言牌 / 气泡 / 手势与收尾时间线 / TEXT_DIR 资产读取 /
load_timeline）属 explorateur 的卡片形态，feuille 侧由调用方组合
rig + scenes + timeline + textlayer 完成同等编排。

不搬清单（render_card 内）：load_timeline（AUDIO_DIR 路径耦合）、
karaoke_points / frac_at 的调用（feuille.timeline）、文字带与卡拉OK高亮、
badge / pill / bubble 粘贴与弹出动画、进度条、手势触发 / 入场姿态 / 收尾码列
编排（render_card 专属分镜形态）、`-i m4a + -c:a copy`（音频轨）。

口径（与原实现一致）：`-f rawvideo -pix_fmt rgb24 -s WxH -r FPS` 管道输入；
libx264 / yuv420p / `+faststart` 输出；时长控制 = 显式 `-t dur`
（与 feuille.compose.mux 同口径）。

适配点（逐条，均为终态裁定）：

- **-shortest 不存在**：原 render_card 已删，坑⑯ 注释原样保留在 encode_frames
  内——它是时机性丢帧开关（批量 7 并发下丢 pts 帧、单渲不丢，framehash 幂等必挂）。
- **纯视频管道**：音频合成与终混在 feuille.audio.compose_track / compose.mux，
  编码器只管视频帧。
- **ffmpeg 经 resolver**（feuille.platform.ffmpeg()）：原实现裸写 "ffmpeg" 依赖
  PATH，违反跨平台约定 1（外部件不写死路径、找不到显式失败）；报错与 compose.mux
  同款。
- **preset 默认 veryfast → slow**：veryfast 是 explorateur 28 卡 × 7 并发批量渲的
  取舍；feuille 单件质量口径与 compose.mux 对齐（调用方可参数覆盖）。
- **rc 非零显式抛错**：原实现只打印返回码，坏产物会静默留在盘上；纪律 19
  （宁可不做完，也不带病交产物）要求显式失败。
- **帧数契约**：调用方须供足 ⌈dur×fps⌉ 帧（坑⑯ 注释的「帧数恒为 FRAMES，qa
  可复算」）；帧不足时 rawvideo 流先尽、产物短于 dur 且无提示——不做静默补帧。
"""

import subprocess

from . import platform as _pt


def encode_frames(frame_iter, out_mp4, *, w, h, fps, dur, crf=18, preset="slow") -> int:
    """逐帧喂 PIL Image 的 rawvideo→ffmpeg 编码器（render_card 管道的通用提取）。

    frame_iter 产出尺寸 (w, h) 的 PIL Image；非 RGB（如 RGBA 图层）自动 convert，
    防御直喂导致字节流错位。返回实际喂入的帧数；ffmpeg 非零退出抛 RuntimeError。
    """
    ffmpeg = _pt.ffmpeg()
    if ffmpeg is None:
        raise SystemExit("缺 ffmpeg（resolver 未找到；缺件清单见 feuille.platform.missing()）")
    # 禁用 -shortest（坑⑯）：音频已 apad/atrim 到恰好 DUR、-t DUR 封顶双流，-shortest 纯属冗余；
    # 且它在 EOF 冲刷时按当时已入队的包随时机丢内部视频帧（实测批量渲染 7 并发下 xiaoman 丢
    # pts=9.9333 一帧，单渲不丢 → framehash 幂等必挂）。帧数恒为 FRAMES，qa 可复算。
    # 终态注：本函数为纯视频管道（音频由 compose.mux 终混），-t dur 是唯一的时长开关。
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
