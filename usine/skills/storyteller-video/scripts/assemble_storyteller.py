#!/usr/bin/env python3
"""assemble_storyteller.py — 评书成片组装（幕帧 → 叠化转场 → 醒木混音）。

输入：render_act_frames.py 的帧序列（f<act>-<k>.png）+ 逐幕 TTS mp3。
输出：单画幅 mp4。

帧序：片头卡(cover) → 幕1帧…[叠化0.5s]…幕2帧… → 片尾卡。
音频：逐幕 mp3 以 preroll 偏移拼接（与 karaoke build 同口径）+ 醒木在每幕
开口帧对齐插入（音量 0.7，淡出已烘焙在音效里）。

用法：
  uv run --project usine python assemble_storyteller.py acts.json frames_dir out.mp4
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys


def _resolve(name):
    """外部可执行文件经 library 的 platform resolver（AGENTS.md 硬约定 1）。"""
    from feuille import platform
    got = getattr(platform, name)() or ""
    if not got:
        sys.exit(f"找不到 {name}（feuille.platform 解析）")
    return got


def sh(*args, timeout=None):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(map(str, args))}\n{r.stderr[-2000:]}")
    return r


def dur_of(p, FFPROBE):
    return float(sh(FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
                    "-of", "csv=p=0", str(p)).stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acts_json")
    ap.add_argument("frames_dir")
    ap.add_argument("out_mp4")
    ap.add_argument("--cover", default="cover_portrait.png")
    ap.add_argument("--outro-card", default="outro_card.png")
    args = ap.parse_args()

    cfg = json.loads(pathlib.Path(args.acts_json).read_text())
    F = pathlib.Path(args.frames_dir)
    FFMPEG, FFPROBE = _resolve("ffmpeg"), _resolve("ffprobe")
    timing = cfg.get("timing", {})
    fps = int(timing.get("fps", 30))
    intro_d = float(timing.get("intro", 3.0))
    outro_d = float(timing.get("outro", 3.4))
    trans_d = float(timing.get("transition", 0.5))
    preroll = float(timing.get("preroll", 0.8))

    here = pathlib.Path(args.acts_json).resolve().parent
    W, H = cfg["formats"][0]["w"], cfg["formats"][0]["h"]

    # ---- 每幕：音频段（mp3 + preroll 偏移）与帧清单 ----
    act_audio = []
    act_frame_groups = []
    for act in cfg["acts"]:
        aid = act["id"]
        # gen_tts 按 locale 键落盘（zh-<act>）；先试裸 id 再试带前缀（与 render 同口径）
        mp3 = next((c for c in (here / "tts" / f"{aid}.mp3",
                                here / "tts" / f"zh-{aid}.mp3") if c.exists()), None)
        if mp3 is None:
            sys.exit(f"缺 TTS 产物 {here / 'tts' / f'{aid}.mp3'}")
        tts_key = mp3.stem               # TTS 落盘键（zh-<act>）
        frame_prefix = aid               # 帧名前缀 = render 的 act id（fa1…）
        adur = dur_of(mp3, FFPROBE)
        # 幕时长 = preroll + 词段（由词表尾推）+ done —— 与 render 口径一致
        meta = json.loads((here / "tts" / f"{tts_key}.json").read_text())
        toks = meta["tokens"]
        n_tok = len(toks)
        # 帧数（render_act_frames 的口径复算）
        durs = [preroll]
        tail = float(timing.get("tail", 0.8))
        for i in range(n_tok):
            d = (toks[i + 1]["start"] - toks[i]["start"] if i < n_tok - 1
                 else (adur - toks[i]["start"]) + tail)
            durs.append(math.ceil(d * fps - 1e-9) / fps)
        durs.append(float(timing.get("done", 0.5)))
        n_frames = sum(round(d * fps) for d in durs)
        act_frame_groups.append((aid, frame_prefix, n_frames))
        act_audio.append((aid, mp3, adur))

    # ---- 视频段：cover / acts / outro ----
    seg_files = []
    total_frames = 0
    cover_img = here / "video" / args.cover
    n = round(intro_d * fps)
    p1 = F / "_seg_cover.mp4"
    sh(FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps),
       "-i", str(cover_img), "-t", f"{n/fps:.6f}", "-frames:v", str(n),
       "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
       str(p1), timeout=600)
    seg_files.append(p1); total_frames += n

    for gi, (aid, fpref, n_frames) in enumerate(act_frame_groups):
        if gi > 0:
            # 叠化转场：前幕末帧 + 本幕首帧 混合若干中间帧
            prev_last = F / f"f{act_frame_groups[gi-1][1]}-{act_frame_groups[gi-1][2]-1:04d}.png"
            cur_first = F / f"f{fpref}-0000.png"
            nt = round(trans_d * fps)
            from PIL import Image
            a = Image.open(prev_last).convert("RGB")
            b = Image.open(cur_first).convert("RGB")
            tpaths = []
            for k in range(1, nt + 1):
                al = k / (nt + 1)
                m = Image.blend(a, b, al)
                tp = F / f"_trans-{gi}-{k:03d}.png"
                m.save(tp); tpaths.append(tp)
            for tp in tpaths:
                p_t = F / f"_seg_t{gi}-{tp.stem[-3:]}.mp4"
                sh(FFMPEG, "-y", "-loglevel", "error",
                   "-framerate", str(fps), "-loop", "1", "-i", str(tp),
                   "-frames:v", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                   "-preset", "medium", "-crf", "18", str(p_t), timeout=300)
                seg_files.append(p_t); total_frames += 1
                tp.unlink()
        p = F / f"_seg_{aid}.mp4"
        # 帧序列 concat（同尺寸 png 序列）
        # image2 序列输入：帧名连续（f<act>-0000..NNNN），一条 -i 直读；
        # 不用 concat demuxer——它对图片清单每项只给 1 帧时长（DTS 崩，
        # 每段只有 1-2 帧的实测事故）。-framerate 驱动时间轴。
        sh(FFMPEG, "-y", "-loglevel", "error",
           "-framerate", str(fps), "-start_number", "0",
           "-i", str(F / f"f{fpref}-%04d.png"),
           "-frames:v", str(n_frames), "-pix_fmt", "yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(p),
           timeout=1800)
        seg_files.append(p); total_frames += n_frames

    outro_img = here / "video" / args.outro_card
    n = round(outro_d * fps)
    p2 = F / "_seg_outro.mp4"
    sh(FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps),
       "-i", str(outro_img), "-t", f"{n/fps:.6f}", "-frames:v", str(n),
       "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
       str(p2), timeout=600)
    seg_files.append(p2); total_frames += n

    with open(F / "_concat.txt", "w") as fh:
        for s in seg_files:
            fh.write(f"file '{s.resolve()}'\n")
    video_noaudio = F / "_video_noaudio.mp4"
    sh(FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
       "-i", str(F / "_concat.txt"), "-c", "copy", str(video_noaudio))

    # ---- 音频轨：逐幕（偏移累加）+ 醒木对齐幕开口 ----
    video_dur = dur_of(video_noaudio, FFPROBE)
    inputs, filters, ordered = [], [], []
    n_in = 0                      # 输入计数器（len(inputs) 会把 flag+路径都数进去——28 事故）
    scene_start = intro_d
    for gi, (aid, mp3, adur) in enumerate(act_audio):
        inputs += ["-i", str(mp3)]
        filters.append(
            f"[{n_in}:a]adelay={int(scene_start*1000)}:all=1,"
            f"apad=whole_dur={video_dur:.3f},atrim=0:{video_dur:.3f}[a{gi}]")
        ordered.append(f"[a{gi}]"); n_in += 1
        if cfg["acts"][gi].get("gavel", True):
            gavel = F / "gavel.wav"
            gdelay = scene_start + 0.15   # 幕开口 0.15s 处拍下
            inputs += ["-i", str(gavel)]
            filters.append(
                f"[{n_in}:a]adelay={int(gdelay*1000)}:all=1,"
                f"apad=whole_dur={video_dur:.3f},atrim=0:{video_dur:.3f}[g{gi}]")
            ordered.append(f"[g{gi}]"); n_in += 1
        # 幕时长（含转场帧的公共时间）——按帧数口径推进
        n_frames = act_frame_groups[gi][2]
        scene_start += n_frames / fps + (trans_d if gi > 0 else 0.0)

    filters.append(f"{''.join(ordered)}amix=inputs={len(ordered)}:duration=longest:normalize=0[aout]")
    fc = ";".join(filters)
    sh(FFMPEG, "-y", "-loglevel", "error", *inputs,
       "-i", str(video_noaudio),
       "-filter_complex", fc,
       "-map", f"{n_in}:v", "-map", "[aout]",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
       "-movflags", "+faststart", str(args.out_mp4), timeout=1200)
    print(f"wrote {args.out_mp4}  ({total_frames} 帧, {total_frames/fps:.1f}s @ {fps}fps)")


if __name__ == "__main__":
    main()
