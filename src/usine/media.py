#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media.py — 媒体内核：ffmpeg 音轨合成 / 词级时间戳→卡拉OK进度 / Edge 视口探测

2026-10-04 收债新增。此前这些逻辑在两条管线里各写一份，已经漂移：

| 能力 | 旧双份位置 | 漂移证据 |
|---|---|---|
| ffmpeg 混音 | `intro_cards.compose_audio` / `scene_video.compose_scene_audio` | 坑③（apad 必须前置 loudnorm）的修法写了两遍；n==1 分支一边走 `mix` 直连、一边走 `anull[m]` |
| 卡拉OK进度 | 两份 `karaoke_points` / `frac_at`（scene 版 docstring 自称"与亮相卡同一实现"） | `frac_at` 末尾一边隐式 `None`、一边显式 `1.0` |
| Edge 视口探针 | 两份 `edge_viewport_h`（坑⑩） | 注释口径不同（`300−206` vs `BAND_H−probe`），探针 html 一个写在函数内一个写在外 |

**为什么必须合并而不是「同步注释」**：坑③是实测出的非确定竞态（同命令 10 连跑丢补尾 3 次），
修法只落一侧 = 另一侧继续随机出片。共用内核让修复只有一处。
"""
import re
import subprocess


# ---------------------------------------------------------------- 音频

def compose_track(line_files, starts, dur, out_m4a):
    """把逐行 m4a/mp3 按 starts 延迟叠加、归一化响度、补齐到恰好 dur 秒。

    **坑③（render-handbook §5-3，必须保持此顺序）**：`apad=whole_dur=` 必须放在
    `loudnorm` **之前**。loudnorm 内部升采样到 192k，之后接 apad 是非确定的 EOF 冲刷
    竞态——2026-10-03 同命令 10 连跑丢补尾 3 次（theo 9.469s），前置后 10/10 全 10.0s。
    loudnorm 是门控响度，补的静音不改变增益；对已 ≥dur 的流是 no-op。

    `atrim` 只裁不补：amix 的输出止于最长行的**原始 mp3 尾**（非裁尾时长）。

    Args:
        line_files: 逐行音频路径（顺序即输入序号）
        starts: 每行起始秒（对应 line_files 同序）
        dur: 成片时长秒；补齐 + 裁齐都用它
        out_m4a: 输出 m4a 路径
    """
    n = len(line_files)
    inputs = []
    for f in line_files:
        inputs += ["-i", str(f)]
    fc = []
    for i, s in enumerate(starts):
        ms = int(round(s * 1000))
        fc.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]")
    mixin = "".join(f"[a{i}]" for i in range(n))
    # n==1 也过一层 anull：与旧 scene 侧写法一致，PCM 不变（anull 是直通），
    # 但让下游滤镜链形状统一，不必分支。
    fc.append(f"{mixin}amix=inputs={n}:normalize=0[m]" if n > 1 else f"{mixin}anull[m]")
    fc.append(f"[m]apad=whole_dur={dur},loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{dur}[out]")
    subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out_m4a)],
                   check=True, capture_output=True)


def probe_duration(path):
    """ffprobe 取容器时长（秒）。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


# ---------------------------------------------------------------- 卡拉OK进度轴

def karaoke_points(line):
    """一行台词的 [(t, frac)] 词首/词尾字符进度点。

    这是「词级时间戳一轴三用」里卡拉OK那一轴的唯一实现（另两轴：口型开合、手势触发）。
    换台词自动重对齐，不需要新数据。
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


def frac_at(pts, t):
    """在进度点上线性插值取 t 时刻的字符进度 [0,1]。"""
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


# ---------------------------------------------------------------- Edge 文字层视口探测

def edge_window_h(text_dir, band_h, html_head, edge_exe, nominal=300):
    """探一次 Edge headless 的视口亏空，返回 (chrome_px, win_h)。

    **坑⑩（render-handbook §5-10）**：Edge 的 `--window-size` 高度 ≠ 实际视口高度
    （本机实测 300 → 206，差 94px；不同 Edge 版本/机器会变）。先探一次差值，之后所有
    截图用补偿后的窗口高度，保证 band_h 画布完整入镜。不写死 94，换机器自动重测。

    残留尾巴：补高后的 opaque 截图会比 band_h 高一截，调用方载入时必须裁到
    `(0, 0, W, BAND_H)`（见 scene_video.band_png）。
    """
    text_dir.mkdir(parents=True, exist_ok=True)
    probe = text_dir / "_vp_probe.html"
    probe.write_text(html_head.format(w=100, h=band_h, bg="#FFFFFF", font="sans-serif", dir="ltr",
                                      body="<div style='height:100vh'></div>"
                                           "<script>document.title=window.innerHeight;</script>"),
                     "utf-8")
    dom = subprocess.run([edge_exe, "--headless=new", "--disable-gpu",
                          f"--window-size=1080,{nominal}", "--virtual-time-budget=800",
                          "--dump-dom", probe.as_uri()],
                         check=True, capture_output=True, timeout=60).stdout.decode("utf-8", "ignore")
    m = re.search(r"<title>(\d+)</title>", dom)
    viewport = int(m.group(1)) if m else band_h
    chrome_px = nominal - viewport
    return chrome_px, band_h + max(0, chrome_px)
