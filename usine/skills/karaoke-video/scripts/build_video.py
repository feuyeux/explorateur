#!/usr/bin/env python3
"""Assemble a karaoke video from deterministic state frames + TTS audio.

Usage:
    build_video.py video.json [--only FORMAT_NAME]

video.json:
{
  "src": "video_src.html",            // scene page with /*__FONTS__*/ marker
  "fonts_css": "../test/fonts.css",   // subset css (from one-page-poster skill)
  "tts_dir": "tts",                   // gen_tts.py output (mp3 + json per locale)
  "locales": ["zh-CN", ...],
  "preroll": 0.8, "tail": 0.8,        // silence before first / after last word
  "done": 0.5,                        // hold on the all-sung state
  "intro": 2.2, "outro": 2.8,         // poster card durations
  "intro_image": "../poster.png",     // shown as intro/outro card
  "desk": "0xe8e2d4",                 // card background color
  "formats": [                        // one pass per aspect ratio
    {"name": "landscape", "w": 1920, "h": 1080, "frames": "frames",
     "output": "one_book.mp4", "fmt": null,
     "poster_filter": "scale=-2:1010,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xe8e2d4"},
    {"name": "portrait", "w": 1080, "h": 1920, "frames": "frames_v",
     "output": "one_book_vertical.mp4", "fmt": "v",
     "poster_filter": "scale=1080:-2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0xe8e2d4"}
  ]
}

Timeline per scene: preroll (all dim) | one frame per token, switching at the
next token's start | last word holds to audio end + tail | done frame.
Every duration is snapped to the 30fps grid and encoded as an exact frame
count (see references/av-sync.md for why).
"""
import json, math, pathlib, subprocess, sys

FPS = 30


def _ensure_pil():
    """re-exec under a python that has PIL (conda envs) for the blank check"""
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        import os
        from pathlib import Path
        # portable re-exec: locate the usine uv project (pins Pillow)
        usine = None
        for anc in Path(__file__).resolve().parents:
            if (anc / "pyproject.toml").is_file() and (anc / "src" / "feuille").is_dir():
                usine = anc
                break
            if (anc / "usine" / "pyproject.toml").is_file():
                usine = anc / "usine"
                break
        if usine and subprocess.run(["uv", "--version"], capture_output=True).returncode == 0:
            os.execvp("uv", ["uv", "run", "--project", str(usine), "python",
                             str(Path(__file__).resolve()), *sys.argv[1:]])
        sys.exit("PIL not found — needed for the blank-frame sentinel; "
                 "install uv and run via `uv run --project usine python <script>`")


_ensure_pil()


def sh(*args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(map(str, args))}\n{r.stderr[-2000:]}")
    return r


def render_chrome(out, url, w, h):
    """headless screenshot in an ISOLATED profile.

    Without --user-data-dir, a running desktop Chrome can hijack the launch:
    the URL opens as a tab in the existing browser and the screenshot comes
    back as the Google new-tab page (white + #4285f4) instead of the file.
    """
    sh("google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
       "--virtual-time-budget=10000", f"--window-size={w},{h}",
       "--force-device-scale-factor=1", "--hide-scrollbars",
       f"--user-data-dir={out.parent}/_chrome_profile",
       f"--screenshot={out}", url)
    # blank-page sentinel: >90% near-pure-white means the page never loaded
    from PIL import Image
    im = Image.open(out).convert("RGB").resize((64, 36))
    white = sum(1 for p in im.getdata() if min(p) >= 250)
    if white > 0.9 * 64 * 36:
        sys.exit(f"BLANK RENDER (page failed to load?): {out}\nURL was: {url}")


def media_dur(path):
    r = sh("ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "csv=p=0", str(path))
    return float(r.stdout.strip())


def d30(d):
    """snap a duration onto the fps grid so the timeline is exact"""
    return math.ceil(d * FPS - 1e-9) / FPS


def build_format(fmt, cfg, HERE, tts_dir):
    F = HERE / fmt["frames"]
    F.mkdir(parents=True, exist_ok=True)
    W, H = fmt["w"], fmt["h"]
    fmtq = f"&fmt={fmt['fmt']}" if fmt.get("fmt") else ""
    PREROLL, TAIL, DONE = cfg["preroll"], cfg["tail"], cfg["done"]

    # intro / outro card from the intro image (per-format override allowed);
    # when the image already matches the format size exactly the filter is a
    # no-op scale — full-bleed, no desk padding
    desk = cfg.get("desk", "0xe8e2d4")
    vf = fmt["poster_filter"].replace("{desk}", desk)
    img = HERE / fmt.get("intro_image", cfg["intro_image"])
    for name in ("intro", "outro"):
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", str(img),
           "-vf", vf, str(F / f"{name}.png"))

    video_parts = []   # (png, grid duration)
    audio_parts = []
    for name, dur in (("_sil_intro", cfg["intro"]), ("_sil_outro", cfg["outro"])):
        sh("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
           "-i", "anullsrc=r=24000:cl=mono", "-t", str(dur), str(F / f"{name}.wav"))
    video_parts.append((F / "intro.png", d30(cfg["intro"])))
    audio_parts.append(F / "_sil_intro.wav")

    for loc in cfg["locales"]:
        meta = json.loads((tts_dir / f"{loc}.json").read_text())
        toks = meta["tokens"]
        k = len(toks)
        adur = media_dur(tts_dir / f"{loc}.mp3")

        render_chrome(F / f"{loc}-pre.png",
                      f"file://{HERE/cfg['src']}?lang={loc}&state=-1{fmtq}", W, H)
        video_parts.append((F / f"{loc}-pre.png", d30(PREROLL)))
        scene_durs = []
        for s in range(k):
            render_chrome(F / f"{loc}-{s}.png",
                          f"file://{HERE/cfg['src']}?lang={loc}&state={s}{fmtq}", W, H)
            d = (toks[s + 1]["start"] - toks[s]["start"] if s < k - 1
                 else (adur - toks[s]["start"]) + TAIL)
            scene_durs.append(d30(d))
            video_parts.append((F / f"{loc}-{s}.png", scene_durs[-1]))
        render_chrome(F / f"{loc}-done.png",
                      f"file://{HERE/cfg['src']}?lang={loc}&state={k}{fmtq}", W, H)
        scene_durs.append(d30(DONE))
        video_parts.append((F / f"{loc}-done.png", scene_durs[-1]))

        total = d30(PREROLL) + sum(scene_durs)   # MUST include the preroll frame
        seg = F / f"{loc}-seg.wav"
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", str(tts_dir / f"{loc}.mp3"),
           "-af", f"adelay={int(PREROLL*1000)}:all=1,apad", "-t", f"{total:.3f}",
           "-ar", "24000", "-ac", "1", str(seg))
        audio_parts.append(seg)
        print(f'  {loc}: {k} tokens, scene {total:.2f}s')

    video_parts.append((F / "outro.png", d30(cfg["outro"])))
    audio_parts.append(F / "_sil_outro.wav")

    # concat: per-entry encode with an exact frame count, then stream copy
    seg_files = []
    for i, (png, d) in enumerate(video_parts):
        n = max(1, round(d * FPS))
        out = F / f"_vseg{i:03d}.mp4"
        sh("ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS),
           "-i", str(png), "-t", f"{n/FPS:.6f}", "-frames:v", str(n),
           "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", str(out))
        seg_files.append(out)
    with open(HERE / "concat_v.txt", "w") as fh:
        for seg in seg_files:
            fh.write(f"file '{seg}'\n")
    with open(HERE / "concat_a.txt", "w") as fh:
        for wav in audio_parts:
            fh.write(f"file '{wav}'\n")

    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
       "-i", str(HERE / "concat_v.txt"), "-c", "copy", str(HERE / "video_noaudio.mp4"))
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
       "-i", str(HERE / "concat_a.txt"), "-c:a", "pcm_s16le", str(HERE / "audio_all.wav"))
    out = HERE / fmt["output"]

    bgm = cfg.get("bgm")
    if bgm:
        # bed music under the narration: trim to the video grid, fade both
        # ends, apply a fixed gain, then amix (normalize=0 keeps voice level)
        vdur = media_dur(HERE / "video_noaudio.mp4")
        fi, fo = bgm.get("fade_in", 1.5), bgm.get("fade_out", 3.0)
        track = F / "_bgm_track.wav"
        sh("ffmpeg", "-y", "-loglevel", "error",
           "-i", str((HERE / bgm["file"]).resolve()),
           "-af", (f"afade=t=in:st=0:d={fi},"
                   f"afade=t=out:st={max(0, vdur - fo):.3f}:d={fo},"
                   f"volume={bgm.get('gain', 0.1)}"),
           "-t", f"{vdur:.3f}", "-ar", "48000", "-ac", "2", str(track))
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", str(HERE / "video_noaudio.mp4"),
           "-i", str(HERE / "audio_all.wav"), "-i", str(track),
           "-filter_complex",
           "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[nar];"
           "[nar][2:a]amix=inputs=2:duration=first:normalize=0[aout]",
           "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out))
    else:
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", str(HERE / "video_noaudio.mp4"),
           "-i", str(HERE / "audio_all.wav"), "-c:v", "copy", "-c:a", "aac",
           "-b:a", "128k", "-movflags", "+faststart", str(out))
    print(f"  wrote {out}")


def main():
    cfgp = pathlib.Path(sys.argv[1])
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    cfg = json.loads(cfgp.read_text())
    HERE = cfgp.resolve().parent   # ABSOLUTE: a relative dir makes the file://
                                   # URL host-relative -> Chrome searches Google
    tts_dir = HERE / cfg.get("tts_dir", "tts")

    # build html once (fonts injected)
    html = (HERE / cfg["src"]).read_text()
    fonts = (HERE / cfg["fonts_css"]).read_text()
    (HERE / "video_build.html").write_text(html.replace("/*__FONTS__*/", fonts))

    for fmt in cfg["formats"]:
        if only and fmt["name"] != only:
            continue
        print(f"format: {fmt['name']} ({fmt['w']}x{fmt['h']})")
        build_format(fmt, cfg, HERE, tts_dir)

    # intermediates are disposable
    for p in ("audio_all.wav", "video_noaudio.mp4"):
        f = HERE / p
        if f.exists():
            f.unlink()


if __name__ == "__main__":
    main()
