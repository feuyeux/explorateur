#!/usr/bin/env python3
"""render_act_frames.py — 评书幕帧渲染器（storyteller-video 的导演层实现）。

每幕渲染三类帧（帧名 = karaoke-video build 的探针契约）：
  <act>-pre.png   幕首（全暗，preroll）
  <act>-<k>.png   词状态帧（第 k 个 token 点亮）
  <act>-done.png  幕尾（全亮）
每帧 = 背景（rig scenes 注册表）+ 说书人立绘（rig.draw_character，幕 pose/mood）
     + 字卡层（Edge headless 截图渲染文字，Pillow 只做合成与缩放——
     raqm=False 纪律：Pillow 不画字）+ 镜头变换（缩放/位移按帧内插）。

确定性：镜头插值与人物 t 全部由帧序号驱动（同参数重渲逐字节一致）。
醒木音（gavel.wav）由 synth_gavel.py 生成，build 阶段混入。

用法：
  uv run --project usine python render_act_frames.py acts.json out_frames_dir \
      [--act a1] [--fps 30]
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys
import tempfile
import shutil

HERE = pathlib.Path(__file__).resolve().parent


def _resolve(name):
    """外部可执行文件经 library 的 platform resolver（AGENTS.md 硬约定 1）。"""
    from feuille import platform
    got = getattr(platform, name)() or ""
    if not got:
        sys.exit(f"找不到 {name}（feuille.platform 解析）")
    return got


FFMPEG = None   # main() 里懒解析（import 期零依赖）
FFPROBE = None


def shot_transform(shot, n_frames, fps, w=1080):
    """帧序 → (scale, xoff, yoff)。kind ∈ push|pull|pan_l|pan_r|static。

    ease = smoothstep：两端一阶导 0（与 rig 的 smoothstep 同式，Ken Burns
    不抖）。pan 的位移量 = 画布宽 4% 的行程，方向由 kind 定。
    """
    kind = (shot or {}).get("kind", "static")
    s0 = float((shot or {}).get("start", 1.0))
    s1 = float((shot or {}).get("end", 1.0))
    if kind == "pull":
        s0, s1 = s1, s0
    if kind == "static":
        s0 = s1 = 1.0
    # 画布满幅纪律：行程 <1 的端点镜像到 ≥1（zoom-out 语义 = 主体变小，画布不露底）
    if s0 < 1.0 or s1 < 1.0:
        lo = min(s0, s1)
        s0, s1 = s0 + (1 - lo) * 2, s1 + (1 - lo) * 2
    out = []
    for k in range(n_frames):
        u = k / max(1, n_frames - 1)
        e = u * u * (3 - 2 * u)
        scale = s0 + (s1 - s0) * e
        xoff = 0.0
        if kind == "pan_l":
            xoff = 0.04 * w * (1 - 2 * e)
        elif kind == "pan_r":
            xoff = -0.04 * w * (1 - 2 * e)
        out.append((scale, xoff, 0.0))
    return out


def synth_gavel(path: pathlib.Path, fps: int):
    """醒木声：60ms 低频正弦（150Hz→70Hz 扫频）× 指数衰减 + 3ms 噪声瞬态。

    纯库内合成器（sine/anoisesrc 滤波组，无额度、无外部依赖）。峰值 ≈ −3 dBFS。
    """
    flt = (
        "sine=frequency=150:duration=0.06[s1];"
        "sine=frequency=70:duration=0.06[s2];"
        "[s1][s2]amix=inputs=2:normalize=0[drone];"
        "anoisesrc=color=brown:duration=0.004:amplitude=0.9[nz];"
        "[nz]adelay=0|0,apad=whole_dur=0.06[trans];"
        "[drone][trans]amix=inputs=2:normalize=0,"
        "afade=t=out:st=0.004:d=0.056:curve=exp,"
        "volume=0.7,apad=whole_dur=0.25"
    )
    subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                    "-filter_complex", flt, "-ar", "48000", "-ac", "1",
                    str(path)], check=True)


def render_word_card(html_path: pathlib.Path, png: pathlib.Path, w: int, h: int,
                     query: str, browser: str):
    """字卡层截图（Edge headless，library 参数组：不带 user-data-dir）。"""
    url = f"file://{html_path.resolve()}{query}"
    subprocess.run([browser, "--headless=new", "--disable-gpu",
                    "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={w},{h}", "--screenshot=" + str(png),
                    "--virtual-time-budget=10000", url],
                   check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not png.exists():
        sys.exit(f"字卡渲染失败：{png}")


def matte_unpremultiply(png: pathlib.Path):
    """黑底字卡 → RGBA 文字层（亮度即 alpha，单色文字 matte 数学成立）。

    headless screenshot 永远输出不透明图（transparent body 会被填底），
    所以字卡页用**纯黑底**渲染：每像素的亮度 L ∈ [0,255] 就是该像素的
    文字覆盖率。文字像素 = 文字色（各像素取该位置的原始色——强调色/金色
    多色文字也正确），alpha = max(RGB)（对纯黑底上的任意非加色文字成立）。

    与 textlayer 双 matte 的取舍：双 matte 服务任意色文字的精确抠像；
    黑底亮度 matte 在「深底亮字或彩字」下同样精确且只需一张图——
    字卡是纯文字层，无半透明叠加，亮度近似在 8bit 量化内无可见差。
    """
    from PIL import Image
    import numpy as np
    im = np.asarray(Image.open(png).convert("RGB"), dtype=np.float64)
    lum = im.max(axis=2)
    # 调色板 matte：字卡页的全部实色（纸/墨/金/朱褐/墨绿/灰/棕）已知——
    # 黑底亮度 matte 对「非白实色」只会给出 alpha=max(RGB)<255 的半透明，
    # 让下层人物透出来。改为按色表分解：每像素 = alpha·前景 + (1-alpha)·黑，
    # 前景必是色表色之一。对每像素：在色表里找使 |obs - a·c| 最小的 (c, a)。
    # 实用近似：若像素接近某色表色（距离小）→ alpha=255、取该色；
    # 否则视为黑↔色表色的插值 → alpha = 255 - 最近距离比例，色取该色表色。
    pal = np.array([
        (242, 234, 216),  # paper
        (44, 36, 24),     # ink
        (184, 134, 11),   # gold
        (176, 85, 46),    # vowel
        (74, 93, 58),     # cons
        (138, 124, 98),   # mut
        (110, 98, 80),    # sub
    ], dtype=np.float64)
    # 每像素到各色表色的距离
    d = np.linalg.norm(im[:, :, None, :] - pal[None, None, :, :], axis=3)  # H,W,P
    nearest = d.argmin(axis=2)
    ndist = d.min(axis=2)
    alpha = np.clip(255.0 - ndist, 0, 255)     # 距色表色越远越透明（黑基底的镜像）
    alpha[lum < 20] = 0                        # 纯黑基底 = 透明（墨字 lum≈44 必须保留）
    color = pal[nearest]
    out = np.dstack([color.astype(np.uint8), alpha.astype(np.uint8)])
    return Image.fromarray(out, "RGBA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acts_json")
    ap.add_argument("out_dir")
    ap.add_argument("--act", default=None, help="只渲这一幕（迭代用）")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    from feuille import rig, scenes
    from feuille.data import storytellers
    from PIL import Image, ImageDraw

    cfg = json.loads(pathlib.Path(args.acts_json).read_text())
    st = storytellers().get(cfg.get("storyteller_id", "changlianke"))
    if not st:
        sys.exit("storyteller.json 里没有这个说书人 id")
    fps = args.fps
    W, H = cfg["formats"][0]["w"], cfg["formats"][0]["h"]
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    from feuille import platform
    browser = platform.browser_path()
    global FFMPEG, FFPROBE
    FFMPEG, FFPROBE = _resolve("ffmpeg"), _resolve("ffprobe")
    if not browser:
        sys.exit("找不到 Chromium 系浏览器（feuille.platform）")

    # 醒木音（一次；FFMPEG 已在 main 顶部解析）
    gavel_path = out / "gavel.wav"
    if not gavel_path.exists():
        synth_gavel(gavel_path, fps)
        print(f"  gavel.wav 合成完毕")

    acts = cfg["acts"]
    if args.act:
        acts = [a for a in acts if a["id"] == args.act]
        if not acts:
            sys.exit(f"--act {args.act}: 幕表里没有")

    # 字卡 HTML（一次注入 fonts；本项目 scenes.py 派生脚本已写好 video_src.html）
    here = pathlib.Path(args.acts_json).resolve().parent
    card_html = here / "video" / "video_src.html"
    if not card_html.exists():
        sys.exit(f"缺字卡源 {card_html}（先跑项目的派生脚本）")
    build_html = card_html.parent / "video_build.html"
    fonts_p = here / "fonts.css"
    build_html.write_text(card_html.read_text().replace(
        "/*__FONTS__*/", fonts_p.read_text()) if fonts_p.exists()
        else card_html.read_text())

    timing = cfg.get("timing", {})
    preroll = float(timing.get("preroll", 0.8))
    tts_dir = here / "tts"
    import subprocess as sp

    for act in acts:
        # gen_tts 按 locale 键落盘（zh-<act>）；先试裸 act id，再试带前缀
        cand = [tts_dir / f"{act['id']}.json", tts_dir / f"zh-{act['id']}.json"]
        meta_p = next((c for c in cand if c.exists()), None)
        mp3_p = (meta_p.with_suffix('.mp3') if meta_p else None)
        if not meta_p:
            sys.exit(f"缺 TTS 产物 {cand[0]}（先跑 karaoke-video 的 gen_tts.py）")
        meta = json.loads(meta_p.read_text())
        toks = meta["tokens"]
        adur = float(sp.run([FFPROBE, "-v", "quiet", "-show_entries",
                             "format=duration", "-of", "csv=p=0", str(mp3_p)],
                            capture_output=True, text=True).stdout.strip())
        # 帧数口径与 karaoke build 一致：preroll + Σ词段 + tail + done
        durs = [preroll]
        for i in range(len(toks)):
            d = (toks[i + 1]["start"] - toks[i]["start"] if i < len(toks) - 1
                 else (adur - toks[i]["start"]) + float(timing.get("tail", 0.8)))
            durs.append(math.ceil(d * fps - 1e-9) / fps)
        durs.append(float(timing.get("done", 0.5)))
        n_frames = sum(round(d * fps) for d in durs)

        # 背景（每幕一次，按 identity 调色）
        bg = scenes.prerender_bg(st, {"scene": act["scene"]}).convert("RGBA")

        # 人物层（幕 pose/mood；blink/openness 由帧序驱动——确定性）。
        # 站位导演（案后构图）：半身 scale 1.35、画面中轴、yoff -0.30H——
        # 说书人坐在「案」后，上半身在字卡纸区下缘与摘录条之间的窗口里，
        # 下半身被底部摘录纸条遮住（z 序：人物层 < 字卡层）。
        ACTOR_X, ACTOR_Y, ACTOR_S = 0.0, -0.02 * H, 1.06

        def actor_frame(t_sec, pose_override=None):
            pose_code = pose_override or act.get("pose", "both_hands")
            pose = {}
            if pose_code and pose_code in rig.POSE_CODES:
                u = (t_sec % 2.0) / 2.0
                pose = rig.pose_for(pose_code, u, t_sec, st)
                pose = {k: v for k, v in pose.items() if k in ("armL", "armR", "legL", "legR")}
            blink = (t_sec % st["movement"]["blinkCycleSec"]) < 0.12
            layer = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            ctx = dict(scale=ACTOR_S, xoff=ACTOR_X, yoff=ACTOR_Y, squash=0.0, xscale=1.0,
                       head_dx=0, head_dy=0, brow_lift_extra=0, pose=pose,
                       openness=0.0, blink=blink, mood=act.get("mood", "neutral"),
                       ss=2)
            rig.draw_character(layer, d, st, t_sec, ctx)
            return layer.resize((W, H), Image.Resampling.BOX)

        shot_frames = shot_transform(act.get("shot"), n_frames, fps, W)

        # 词边界 → 每帧该亮的 token 数
        token_at = []
        t_abs = 0.0
        for d in durs:
            token_at.append(len(token_at))
        # 逐帧：preroll 全暗；词段按边界推进；done 全亮
        boundaries = [round(preroll * fps)]
        acc = round(preroll * fps)
        for i, d in enumerate(durs[1:-1], 1):
            acc += round(d * fps)
            boundaries.append(acc)
        done_start = acc

        print(f"  {act['id']}: {n_frames} 帧 ({n_frames/fps:.1f}s), scene={act['scene']}, shot={act.get('shot', {}).get('kind', 'static')}")

        # 合成循环
        for k in range(n_frames):
            scale, sx, sy = shot_frames[k]
            t_sec = k / fps
            state = -1 if k < boundaries[0] else (
                len(toks) if k >= done_start else
                max(i for i, b in enumerate(boundaries) if k >= b))
            # 1) 底 = 背景
            frame = bg.copy()
            # 2) 人物（拍案手 pose 在幕首 1.2s 内用 gavel 拍案 pose）
            pose_code = act.get("pose", "both_hands")
            if act.get("gavel") and k < round(1.2 * fps) and state < 1:
                pose_code = "clap"   # 拍案手
            frame.alpha_composite(actor_frame(t_sec, pose_code))
            # 3) 镜头：画布外扩缩放 + 平移后裁回。
            #    scale<1（缩小）时 big 比画布小，crop 越界会填黑——
            #    镜头行程一律锁 ≥1.0：先用 max(scale,1) 放大，缩小感由
            #    「从 1.0 缓降到 0.94」的 push/pull 反向表达（Ken Burns 的
            #    zoom-out 语义 = 画面元素变小，但画布永远满幅）。
            if abs(scale - 1.0) > 1e-3 or abs(sx) > 1e-3:
                eff = max(scale, 1.0)
                sw, sh = int(W * eff), int(H * eff)
                big = frame.resize((sw, sh), Image.Resampling.LANCZOS)
                ox = int((sw - W) / 2 + sx)
                oy = int((sh - H) / 2 + sy)
                ox = max(0, min(sw - W, ox)); oy = max(0, min(sh - H, oy))
                frame = big.crop((ox, oy, ox + W, oy + H))
            # 4) 字卡（Edge headless 文字层）——按 state 取缓存截图再合成
            png = out / f"{act['id']}-{state if state >= 0 else 'pre'}.png"
            # 字卡层与人物/背景的合成：字卡图本身是不透明 1080×1920（纸色底），
            # 直接作为最上层会盖掉场景——因此字卡 HTML 的字卡区必须透明底
            # （CSS 用 rgba 纸色，body 透明）。此处 alpha_composite。
            card_cache = out / "_cards" / f"{act['id']}-{state if state >= 0 else 'pre'}.png"
            if not card_cache.exists():
                card_cache.parent.mkdir(exist_ok=True)
                q = f"?lang=zh-{act['id']}&state={state}" if state >= 0 else f"?lang=zh-{act['id']}&state=-1"
                render_word_card(build_html, card_cache, W, H, q, browser)
            card = matte_unpremultiply(card_cache)
            frame.alpha_composite(card)
            frame.convert("RGB").save(out / f"f{act['id']}-{k:04d}.png")
        print(f"  {act['id']}: 帧序列写完")


if __name__ == "__main__":
    main()
