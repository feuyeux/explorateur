#!/usr/bin/env python3
"""probe_scoreboard.py — 比分牌几何探针。

SKILL.md 写的是「先探针再定裁窗，**不抄数字**」。这句话在没有工具的时候只是
一句提醒——每个联赛转播的比分牌位置与尺寸都不同，抄意甲的 `crop=100:36:170:86`
到英超上，裁出来的是一片草坪。

这个脚本把探针做成可复跑的一步：

  1. 用探针工具量母版尺寸（宽高 / 时长 / 帧率）；
  2. 在画面若干候选带（上沿 / 下沿 × 左 / 中 / 右）上分别裁窗，
     用场景检测数每个带的**变化密度**——比分牌每秒钟跳一次，
     所以它的变化密度远高于静态画面（记分牌、广告牌、球衣号码都更稳定）；
  3. 排名输出候选裁窗，并给每个候选生成一张**竖拼长图**
     （1 帧/秒，纵向 tile），供人眼逐帧读 MM:SS 与比分。

人眼仍然拍板：脚本给的是**候选 + 证据**，裁窗的最终值要写进窗口表的锚点里。

用法：
    python3 probe_scoreboard.py <master.mp4> [--top 3] [--stitch 40] [--out probe.json]
    python3 probe_scoreboard.py selftest          # 离线回归：lavfi 合成视频，不联网

退出码：0 = 探到比分牌候选（仍需人眼确认）；1 = 探不到比分牌（变化密度低于
地板，本 skill 对这条母版不适用——没有映射基准）；2 = 输入/环境坏了。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
# 候选带：横向三档（左右中）× 纵向两档（画面上沿 / 下沿），每档一块。
# 横向取画面宽度的 1/4，纵向取画面高度的 1/12 —— 比分牌通常在角上或顶部中央。
BANDS = [
    ("top-left", 0.00, 0.00),
    ("top-center", 0.375, 0.00),
    ("top-right", 0.75, 0.00),
    ("bottom-left", 0.00, 0.90),
    ("bottom-center", 0.375, 0.90),
    ("bottom-right", 0.75, 0.90),
]


class ProbeError(RuntimeError):
    pass


def _need(binary: str) -> str:
    """解析外部可执行文件。

    优先环境变量覆盖（`FEUILLE_FFMPEG` / `FEUILLE_FFPROBE`），否则在 PATH 里找。
    全仓的跨平台解析事实源是 @feuille/core 的 platform resolver；这个脚本是
    skill 内的独立 Python 脚本，用同样的「可覆盖 + 找不到就报错」口径，
    **不静默拿别的同名程序顶替**。
    """
    env = os.environ.get(f"FEUILLE_{binary.upper()}")
    if env:
        if not Path(env).exists():
            raise ProbeError(f"环境变量 FEUILLE_{binary.upper()} 指向的文件不存在：{env}")
        return env
    path = shutil.which(binary)
    if not path:
        raise ProbeError(f"找不到 {binary}——请装好它，或用 "
                        f"FEUILLE_{binary.upper()} 指定路径。")
    return path


def probe_video(master: Path) -> dict:
    """量母版：宽高、时长、帧率。"""
    exe = _need(FFPROBE)
    proc = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
         "-show_entries", "format=duration",
         "-of", "json", str(master)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise ProbeError(f"ffprobe 读不出 {master}：{proc.stderr[-400:]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or [{}]
    s = streams[0]
    dur_raw = (data.get("format") or {}).get("duration") or "0"
    try:
        num, _, den = str(s.get("r_frame_rate", "0/1")).partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "width": int(s.get("width") or 0),
        "height": int(s.get("height") or 0),
        "fps": round(fps, 3),
        "duration": round(float(dur_raw or 0), 3),
    }


SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")

# 抽格拼版每 SHEET_EVERY_SECS 秒取一格（12 格覆盖前 96s）
SHEET_EVERY_SECS = 8

# 「有没有比分牌」的地板：比分牌每秒跳一次，fps=1 采样下它的带 changes_per_sec
# 接近 1；只有切点会动的普通画面带通常 ≤ 0.2/s。低于地板 = 这个母版里探不到
# 比分牌，映射方法不适用（没有映射基准）——退出码 1，把母版退回
# multilingual-video-poetry 的口径，不许拿着纯噪声的「候选排名」继续走。
MIN_CHANGES_PER_SEC = 0.25


def score_band(master: Path, crop: str, seconds: int) -> dict:
    """量一条候选带上的**逐帧场景变化强度**。

    比分牌每秒钟跳一次 → 它的 scene score 在这条带上**持续非零**；
    静态画面（看台、广告牌、球衣号码）得分接近 0。
    所以用「分数分布」而不是「变化次数」排序：均值抗噪，p90 抓瞬时跳变。

    注意：`metadata=print` 的输出级别是 INFO，用 `-v error` 会把它吞掉——
    这正是第一版探针全 0 的原因。
    """
    exe = _need(FFMPEG)
    vf = f"crop={crop},fps=1,select='gt(scene,0)',metadata=print"
    proc = subprocess.run(
        [exe, "-hide_banner", "-nostats", "-v", "info", "-t", str(seconds),
         "-i", str(master), "-vf", vf, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    scores = [float(x) for x in SCORE_RE.findall(proc.stderr)]
    if not scores:
        return {"n": 0, "mean": 0.0, "p90": 0.0, "changes": 0}
    ordered = sorted(scores)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    return {
        "n": len(scores),
        "mean": round(sum(scores) / len(scores), 5),
        "p90": round(p90, 5),
        "changes": sum(1 for x in scores if x >= 0.015),
    }


def make_stitch(master: Path, crop: str, out_png: Path, rows: int) -> bool:
    """把裁窗按 1 帧/秒竖拼成一张长图——逐帧读 MM:SS 与比分。"""
    exe = _need(FFMPEG)
    vf = f"crop={crop},fps=1,tile=1x{rows}"
    proc = subprocess.run(
        [exe, "-hide_banner", "-v", "error", "-i", str(master),
         "-vf", vf, "-frames:v", "1", "-y", str(out_png)],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and out_png.exists()


def make_contact_sheet(master: Path, out_png: Path, cols: int = 4, rows: int = 3) -> bool:
    """全画面抽格拼版——人眼一眼看出比分牌在哪。"""
    exe = _need(FFMPEG)
    vf = f"fps=1/{SHEET_EVERY_SECS},scale=-1:360,tile={cols}x{rows}"
    proc = subprocess.run(
        [exe, "-hide_banner", "-v", "error", "-i", str(master),
         "-vf", vf, "-frames:v", "1", "-y", str(out_png)],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and out_png.exists()


def probe(master: Path, top: int, stitch_rows: int, seconds: int,
          args_out: str | None = None) -> dict:
    info = probe_video(master)
    if not info["width"] or not info["height"]:
        raise ProbeError(f"读不到画面尺寸：{info}")
    w, h = info["width"], info["height"]
    bw = max(16, w // 4)
    bh = max(10, h // 12)

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for name, fx, fy in BANDS:
            x = int(w * fx)
            y = int(h * fy)
            x = max(0, min(x, w - bw))
            y = max(0, min(y, h - bh))
            crop = f"{bw}:{bh}:{x}:{y}"
            st = score_band(master, crop, seconds)
            st["changes_per_sec"] = round(st["changes"] / max(1, seconds), 3)
            results.append({"band": name, "crop": crop,
                            "x": x, "y": y, "w": bw, "h": bh, **st})

        results.sort(key=lambda r: (r["p90"], r["mean"]), reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1
            r["stitch_png"] = None
            if i < top:
                png = tmpdir / f"{r['band']}-stitch.png"
                if make_stitch(master, r["crop"], png, stitch_rows):
                    r["stitch_png"] = f"{r['band']}-stitch.png"
        sheet = tmpdir / "contact-sheet.png"
        has_sheet = make_contact_sheet(master, sheet)

        # 产物写进专门目录，不往当前目录里撒图片
        out_dir = Path(args_out) if args_out else Path.cwd() / "probe-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = []
        for r in results:
            if not r.get("stitch_png"):
                continue
            src = tmpdir / r["stitch_png"]
            dst = out_dir / r["stitch_png"]
            shutil.copyfile(src, dst)
            r["stitch_png"] = str(dst)
            exported.append(str(dst))
        if has_sheet:
            dst = out_dir / "contact-sheet.png"
            shutil.copyfile(sheet, dst)
            exported.append(str(dst))

    best = results[0] if results else None
    found = bool(best) and best["changes_per_sec"] >= MIN_CHANGES_PER_SEC
    return {
        "master": str(master),
        "video": info,
        "probe_seconds": seconds,
        "found": found,
        "candidates": results,
        "exported": exported,
        "verdict": (
            "候选已按变化密度排名；**人眼读竖拼长图确认**比分牌真的在这里，"
            "再把 crop 值写进窗口表锚点。变化密度只是线索，不是判据。"
            if found else
            f"排名最高的候选带变化密度也只有 {best['changes_per_sec']}/s"
            f"（地板 {MIN_CHANGES_PER_SEC}/s）——**这个母版里探不到比分牌**。"
            "没有比分牌就没有「视频时间 ↔ 比赛时钟」的映射基准，本 skill 不适用；"
            "母版退回 multilingual-video-poetry 的口径（压字幕），不要拿噪声排名当候选。"
        ),
    }


# ---------------------------------------------------------------- 自检（合成视频，不联网）


def selftest() -> int:
    """用 lavfi 合成两条视频做离线回归：带「跳动带」的必须探到并排对位置，
    全静态的必须给出 found=False（无比分牌地板）。

    正例：灰底 + 左上角一条**低频纹理在平移**的带（模拟比分牌每秒跳动）；
    负例：纯灰底（什么都没有）。都不需要字体、不需要真集锦。

    ⚠️ 夹具为什么不是「高频随机噪声带」——这是实测踩出来的，别改回去：
    FFmpeg 的 `scene` 分（select 滤镜的 scene 变量）**不把高频随机噪声当场景变化**：
    纯噪声带逐帧像素平均绝对差高达 165/255，scene 分却只有 0.001–0.01；
    真母版（1920x1080 集锦）的比分牌带每秒是 0.02–0.11。
    ⇒ 用噪声当夹具，正例必然测不出 found=True（这一环在 FFmpeg 8.1 上是红的）。
    而「有结构、每秒在动」的内容（低频平移纹理）实测 0.5/s，过地板 0.25/s。
    另外 `geq` 的 `random(1)` 在不同 FFmpeg 版本上语义不同（8.1 上退化成近常量），
    ⇒ 夹具一律只用 `sin`/`T`/`X`/`Y` 这类跨版本稳定的表达式。
    """
    checks: list[tuple[str, bool, str]] = []

    def check(label, ok, detail=""):
        checks.append((label, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")

    exe = _need(FFMPEG)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        clock = tmpdir / "clock.mp4"
        static = tmpdir / "static.mp4"
        # 640x360 ⇒ 候选带 = 160x30；跳动带 (X<160, Y<30) 恰好落在 top-left 候选带里
        r = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "color=c=gray:s=640x360:r=30:d=8",
             "-vf", ("geq=lum='if(lt(X,160)*lt(Y,30),"
                     "128+120*sin(X*0.08+T*3)+60*sin(Y*0.4+T*2),128)':cb=128:cr=128"),
             "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(clock)],
            capture_output=True, text=True)
        check("合成带跳动带的视频", r.returncode == 0 and clock.exists(),
              (r.stderr or "")[-200:])
        r = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "color=c=gray:s=640x360:r=30:d=6",
             "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(static)],
            capture_output=True, text=True)
        check("合成全静态视频", r.returncode == 0 and static.exists(),
              (r.stderr or "")[-200:])

        if clock.exists():
            res = probe(clock, top=1, stitch_rows=4, seconds=8,
                        args_out=str(tmpdir / "artifacts"))
            check("跳动带：found=True", res.get("found") is True,
                  f"top={res['candidates'][0]['band']} "
                  f"{res['candidates'][0]['changes_per_sec']}/s")
            check("跳动带：排名第一的是 top-left（跳动带所在候选）",
                  res["candidates"][0]["band"] == "top-left")
        if static.exists():
            res = probe(static, top=1, stitch_rows=4, seconds=6,
                        args_out=str(tmpdir / "artifacts2"))
            check("全静态：found=False（无比分牌地板）", res.get("found") is False,
                  f"top={res['candidates'][0]['band']} "
                  f"{res['candidates'][0]['changes_per_sec']}/s")

    bad = sum(1 for _, ok, _ in checks if not ok)
    print()
    print(f"自检：{len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="match-recap-video 比分牌几何探针")
    ap.add_argument("master", help="集锦母版视频；填 'selftest' 跑离线回归（合成视频）")
    ap.add_argument("--top", type=int, default=3, help="生成竖拼长图的候选数")
    ap.add_argument("--stitch", type=int, default=40,
                    help="竖拼长图的帧数（fps=1 采样 ⇒ 覆盖探测窗口的前 N 秒）")
    ap.add_argument("--seconds", type=int, default=120, help="探测时长（秒）")
    ap.add_argument("--out", help="探针结果 JSON 输出路径")
    ap.add_argument("--artifacts", help="竖拼长图与抽格图的输出目录（默认 ./probe-out）")
    ap.add_argument("--selftest", action="store_true", help="离线跑合成视频回归")
    args = ap.parse_args(argv)

    if args.selftest or args.master == "selftest":
        return selftest()

    master = Path(args.master)
    if not master.exists():
        print(f"母版不存在：{master}", file=sys.stderr)
        return 2
    try:
        res = probe(master, args.top, args.stitch, args.seconds, args.artifacts)
    except ProbeError as exc:
        print(f"探针失败：{exc}", file=sys.stderr)
        return 2

    out = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"探针结果 → {args.out}")
    else:
        print(out)
    print()
    print("场景变化强度排名（线索，需人眼确认）：")
    for r in res["candidates"]:
        print(f"  {r['rank']}. {r['band']:<14} crop={r['crop']:<22} "
              f"p90={r['p90']:<9} 均值={r['mean']:<9} 变化 {r['changes']:>4} 次"
              f"（{r['changes_per_sec']}/s）")
    if not res["found"]:
        print()
        print(f"未找到比分牌（地板 {MIN_CHANGES_PER_SEC}/s）——本 skill 对这条母版不适用，"
              "没有映射基准。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
