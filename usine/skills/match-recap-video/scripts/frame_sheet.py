# -*- coding: utf-8 -*-
"""frame_sheet.py — 抽指定时间点的一帧、打上时间戳、拼成网格长图（人眼定窗/定锚用）。

窗口表的 `see` 与 `anchor` 必须以帧为证据，不能凭印象写。本脚本一次抽一排
带秒数标注的帧拼成一张图：read 工具看一张图 = 看完一整段母版。

用法：
    python3 scripts/frame_sheet.py <母版.mp4> --times 12,24.5,31 --cols 4 --out sheet.png
    python3 scripts/frame_sheet.py <母版.mp4> --step 4 --rows 8        # 每 4s 一格

退出码：0 = 出图；1 = 一帧都没抽出来；2 = 输入坏了。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

def _need(binary: str) -> str:
    """解析外部可执行文件：优先 FEUILLE_<NAME> 环境变量覆盖，否则 PATH 里找。

    全仓的跨平台解析事实源是 @feuille/core 的 platform resolver；本脚本是
    skill 内的独立 Python，用同样的「可覆盖 + 找不到就报错」口径，
    不静默拿别的同名程序顶替。
    """
    import os
    import shutil
    env = os.environ.get(f"FEUILLE_{binary.upper()}")
    if env:
        if not Path(env).exists():
            raise RuntimeError(f"环境变量 FEUILLE_{binary.upper()} 指向的文件不存在：{env}")
        return env
    found = shutil.which(binary)
    if not found:
        raise RuntimeError(f"找不到 {binary}——请装好它，或用 FEUILLE_{binary.upper()} 指定路径。")
    return found


CELL_W = 480


def cell_times(args: argparse.Namespace, total: float) -> list[float]:
    if args.times:
        return [float(x) for x in args.times.split(",") if x.strip()]
    step = max(args.step, 0.5)
    n = args.rows * args.cols if (args.cols and args.rows) else int(total // step)
    ts = [round(i * step, 2) for i in range(int(total // step) + 1)][:n]
    return ts


def extract_frames(master: Path, times: list[float], out_dir: Path,
                   font: str | None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outs: list[Path] = []
    for t in times:
        out = out_dir / f"f_{t:g}.png"
        vf = f"scale={CELL_W}:-1"
        if font:
            # drawtext 的路径要转义冒号；标签让「哪格是哪秒」不靠数格子
            vf = (f"drawtext=fontfile='{font}':text='{t:g}s':x=6:y=4:fontsize=28:"
                  f"fontcolor=yellow:box=1:boxcolor=black@0.65,{vf}")
        r = subprocess.run(
            [_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(t), "-i", str(master), "-frames:v", "1", "-vf", vf,
             str(out)], capture_output=True, text=True)
        if r.returncode == 0 and out.exists():
            outs.append(out)
    return outs


def tile(frames: list[Path], cols: int, out: Path) -> bool:
    """横竖拼接（末行不足补末格，行宽一致才 vstack 得起来）。不改传入列表。"""
    if not frames:
        return False
    frames = list(frames)
    while len(frames) % cols:
        frames.append(frames[-1])
    # concat 清单里的相对路径以「清单所在目录」解析——清单放帧目录里最稳
    lst = frames[0].parent / (out.stem + "_list.txt")
    lst.write_text("\n".join(f"file '{f.name}'" for f in frames) + "\n",
                   encoding="utf-8")
    rows = -(-len(frames) // cols)
    r = subprocess.run(
        [_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(lst),
         "-vf", f"tile={cols}x{rows}", "-frames:v", "1", str(out.resolve())],
        capture_output=True, text=True)
    lst.unlink(missing_ok=True)
    return r.returncode == 0 and out.exists()


def find_font() -> str | None:
    """时间戳标签字体：找不到就出无标签版（不因字体缺席而失败）。"""
    for p in (Path("C:/Windows/Fonts/consola.ttf"), Path("C:/Windows/Fonts/arial.ttf")):
        if p.exists():
            # ffmpeg filter 里冒号要转义
            return str(p).replace(":", "\\:")
    return None


def selftest() -> int:
    """离线回归：lavfi 合成 2s 视频 → 抽 3 帧 → 拼图成功。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        master = td_path / "fake.mp4"
        r = subprocess.run(
            [_need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
             "-pix_fmt", "yuv420p", str(master)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"selftest：lavfi 合成失败 {r.stderr[:200]}")
            return 1
        frames = extract_frames(master, [0.2, 1.0, 1.8], td_path / "shots",
                                find_font())
        ok = len(frames) == 3
        tiled = tile(frames, 2, td_path / "sheet.png")
        ok = ok and tiled and (td_path / "sheet.png").exists()
        print(f"selftest：抽帧 {len(frames)}/3、拼图 {'成功' if tiled else '失败'}"
              f"（{'通过' if ok else '不通过'}）")
        return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description="带时间戳的抽帧拼版")
    ap.add_argument("master", help="母版 mp4")
    ap.add_argument("--times", help="逗号分隔的秒数列表（与 --step 二选一）")
    ap.add_argument("--step", type=float, default=4.0,
                    help="均匀抽帧步长（默认 4s；给 --times 时忽略）")
    ap.add_argument("--cols", type=int, default=5, help="列数（默认 5）")
    ap.add_argument("--rows", type=int, default=8, help="行数上限（默认 8）")
    ap.add_argument("--out", help="输出 png（默认 <母版目录>/<母版名>-sheet.png）")
    args = ap.parse_args(argv)

    master = Path(args.master)
    if not master.exists():
        print(f"母版不存在：{master}", file=sys.stderr)
        return 2
    dur = subprocess.run(
        [_need("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(master)], capture_output=True, text=True)
    try:
        total = float(dur.stdout.strip() or 0)
    except ValueError:
        total = 0.0
    if total <= 0:
        print(f"母版时长读不出来：{master}", file=sys.stderr)
        return 2
    times = [t for t in cell_times(args, total) if 0 <= t < total]
    if not times:
        print("没有可抽的时间点", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else master.with_name(
        master.stem + "-sheet.png")
    font = find_font()
    if font is None:
        # 拼版是「人眼定窗/定锚的证据链」，没有时间戳的拼版证据力大幅下降——
        # 静默出一张无标签版，机器不会报错，但人看图时已经对不上一帧是第几秒。
        print("⚠ 找不到时间戳字体（consola.ttf / arial.ttf）——拼版**不带时间戳**，"
              "用它定窗/定锚时只能靠帧序，证据力下降；机器不判失败，但要人眼知道这件事。",
              file=sys.stderr)
    frames = extract_frames(master, times, out.parent / (out.stem + "-frames"), font)
    if not frames:
        print("一帧都没抽出来", file=sys.stderr)
        return 1
    if not tile(frames, max(args.cols, 1), out):
        print("拼图失败", file=sys.stderr)
        return 1
    print(f"拼版 {len(frames)} 帧 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
