#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_framehash.py — 逐帧像素基线的反向验证

第 0 条好数据放行：两支确定性测试视频（lavfi 造）连算两次哈希一致；
基线保存→回读→比对零漂移。反向各防一种退化：

- **-map 0:v 是承重的**（源级断言：缺它数字不同且不报错）
- 内容变一个像素级细节 → 整支哈希必变（能抓真漂移）
- 帧数不同 → first_drift 必报（坑⑯「丢帧尾巴」症状，不能只比公共长度）
- 子集核查：基线里不在范围的归 skipped 不归 gone（门禁不喊狼嚎）
- 差异热力图没有参考帧就返回 False（不做「假装有参考」的合成图）
- 桶标识可读、含 pillow、**不含 ffmpeg**（合成器入桶只会让基线无谓失效）
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import inspect                                       # noqa: E402

from feuille import framehash as fh, platform as pt  # noqa: E402


def make_video(path, color, seconds=0.5):
    ffm = pt.ffmpeg()
    subprocess.run([ffm, "-y", "-f", "lavfi",
                    "-i", f"color=c={color}:s=320x240:d={seconds}:r=30",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    str(path)], check=True, capture_output=True)
    return path


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-framehash-")
    d = pathlib.Path(tmp.name)
    if pt.ffmpeg() is None:
        rows.append((True, "[SKIP] 全部真机判据未验（缺 ffmpeg）"))
        return rows

    a = make_video(d / "a.mp4", "0x808080")
    b = make_video(d / "b.mp4", "0x808080")
    c = make_video(d / "c.mp4", "0x909090")

    # ---- 0. 好数据放行：确定性 + 基线往返零漂移 ----
    h1, h2 = fh.framehash(a), fh.framehash(a)
    rows.append((h1 == h2 and h1.startswith("MD5="),
                 f"同支连算两次哈希一致（{h1[:20]}…）"))
    rows.append((fh.framehash(a) == fh.framehash(b),
                 "同内容两支文件哈希一致（判的是像素不是容器字节）"))
    base_only_a = fh.save_baseline({"a.mp4": h1}, d / "base-only.txt")
    rows.append((fh.read_baseline(base_only_a) == {"a.mp4": h1},
                 "基线保存→回读一致"))

    r, rc = fh.compare([a, b], base_only_a, subset=False)
    rows.append((rc == 0 and r["same"] == ["a.mp4"] and r["new"] == ["b.mp4"]
                 and not r["gone"],
                 f"好数据比对零漂移（same=1、new=1 不判失败，退出码 {rc}）"))
    # 基线里多出的条目 = gone（非子集核查时）
    base_with_old = fh.save_baseline({"a.mp4": h1, "old.mp4": "MD5=dead"},
                                     fh.baseline_path(d))
    r2, rc2 = fh.compare([a, b], base_with_old, subset=False)
    rows.append((rc2 == 1 and r2["gone"] == ["old.mp4"],
                 f"基线多出的条目判 gone、退出码 1（gone={r2['gone']}）"))

    # ---- 1. -map 0:v 承重（源级断言）----
    src = inspect.getsource(fh.framehash) + inspect.getsource(fh.per_frame)
    rows.append(('"-map", "0:v"' in src,
                 "framehash/per_frame 都带 -map 0:v（少了它数字不同且不报错——承重）"))

    # ---- 2. 内容变 → 哈希必变 ----
    rows.append((fh.framehash(a) != fh.framehash(c),
                 "内容变（灰 80→90）→ 整支哈希必变（能抓真漂移）"))

    # ---- 3. 帧数不同 → first_drift 必报 ----
    short = make_video(d / "short.mp4", "0x808080", seconds=0.2)
    full_frames = fh.per_frame(a)
    short_frames = fh.per_frame(short)
    first, last = fh.first_drift(short_frames, full_frames)
    rows.append((len(full_frames) != len(short_frames) and first is not None,
                 f"帧数不同（{len(full_frames)} vs {len(short_frames)}）→ 判漂移"
                 f"（第 {first} 帧起——只比公共长度会把丢帧当一致）"))
    first2, _ = fh.first_drift(full_frames, full_frames)
    rows.append((first2 is None, "完全一致 → 不报漂移"))

    # ---- 4. 子集核查：范围外归 skipped 不归 gone ----
    r, rc = fh.compare([c], base_with_old, subset=True)
    rows.append((rc == 0 and r["skipped"] == ["a.mp4", "old.mp4"] and r["gone"] == []
                 and r["new"] == ["c.mp4"],
                 "子集核查：范围外 2 支归 skipped、退出码 0（新片不判失败）"))

    # ---- 5. 证据帧 + 热力图契约 ----
    rows.append((fh.extract_frame(a, 0, d / "f0.png"),
                 "证据帧可抽取"))
    rows.append((not fh.diff_png(d / "nope1.png", d / "nope2.png", d / "heat.png"),
                 "无参考帧 → 差异热力图返回 False（不做「假装有参考」的合成图）"))
    # 有参考帧时热力图可产出
    fh.extract_frame(a, 0, d / "ref0.png")
    fh.extract_frame(c, 0, d / "cur0.png")
    rows.append((fh.diff_png(d / "ref0.png", d / "cur0.png", d / "heat.png"),
                 "有参考帧 → 差异热力图可产出"))

    # ---- 6. 桶标识 ----
    bkt = fh.bucket()
    rows.append(("pillow" in bkt and "-" in bkt,
                 f"桶标识可读且含 pillow（{bkt}）"))
    rows.append(("ffmpeg" not in bkt,
                 "桶不含 ffmpeg（合成器不参与逐帧像素，入桶只会让基线无谓失效）"))
    rows.append((fh.baseline_path(d).name == f"framehash-{bkt}.txt",
                 "基线路径按桶命名（不同平台不会互相读到）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("逐帧像素基线（framehash / 分桶 / 漂移定位）")
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
    print(f"{'OK' if not fails else 'FAIL'}：像素基线 {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
