#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频拆轨对比：定位「人声消失 / BGM 忽隐忽现 / 提前静音」类问题。

只听最终混音定位不了问题——把滤镜图拆成独立分轨逐段对齐才有诊断力：

    人声干轨  vs  被压 BGM 轨  vs  最终混音

三者同源同长，同一时间点横向对比，一眼看出是哪一环丢的。
本文两个真实 bug 都是这么定位的（人声被压掉 25–30 dB、BGM 提前 2.6 秒静音）。

## 用法

    uv run python scripts/audio_profile.py <音频文件> [窗口定义...]

窗口从 stdin 的 JSON 读，形如（**终端下不传窗口 = 直接出全曲曲线**——
只有管道 / 重定向才读 stdin，交互终端不会等输入）：

    {"voice": [[0.55, 2.88], [5.75, 8.22]], "gaps": [[3.13, 5.50]]}

不传窗口时只打印全曲逐 0.1s 电平曲线。

    # 全曲曲线
    uv run python scripts/audio_profile.py mix.m4a

    # 带人声段/空档段对比（推荐）
    echo '{"voice":[[0.55,2.88]],"gaps":[[3.13,5.50]]}' | \
        uv run python scripts/audio_profile.py mix.m4a

    # 同上，外加每段 RMS 交叉核对（判据仍用 LUFS，RMS 只作旁证）
    echo '{"voice":[[0.55,2.88]],"gaps":[[3.13,5.50]]}' | \
        uv run python scripts/audio_profile.py mix.m4a --rms

## 输出

- 无窗口：逐 0.1s 的 RMS 电平条 + 峰值/静音段提示
- 有窗口：人声段 vs 空档段的平均电平，以及差值（差值 < 8 dB 说明人声被盖住了）
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

_BIN: dict[str, str] = {}


def _bin(name: str) -> str:
    """外部可执行文件经 `feuille.platform` 解析（AGENTS.md 跨平台硬约定 1：
    外部可执行文件不许写死路径名，找不到显式失败）。"""
    if name not in _BIN:
        try:
            from feuille import platform
            got = getattr(platform, name)() or ""
        except ImportError:
            got = ""
        if not got:
            sys.exit(f"找不到 {name}：请用 `uv run --project usine python …` 运行"
                     f"（feuille.platform 解析），或安装后重跑")
        _BIN[name] = got
    return _BIN[name]


def _run_ffmpeg(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """解码器统一入口：超时与退出码都要响亮失败。

    解码失败时测量行不会出现，正则失配会让上层拿到 None——再把 None
    印成「静音」，就把真错误伪装成了「测不出来」（纪律 19：禁止静默
    兜底）。所以退出码非 0 必须在这里就失败，带上 stderr 尾巴。
    """
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"ffmpeg 超时（{timeout}s）：{' '.join(map(str, args[:6]))} …")
    if r.returncode != 0:
        sys.exit(f"ffmpeg 退出 {r.returncode}：{r.stderr[-300:]}")
    return r


def mean_volume(path: Path, start: float, dur: float) -> float | None:
    """单段 RMS（dB）。volumedetect 的输出在 info 级，**不要加 -v error**。"""
    r = _run_ffmpeg(
        [_bin("ffmpeg"), "-ss", f"{start:.3f}", "-t", f"{max(0.05, dur):.3f}",
         "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def lufs(path: Path, start: float, dur: float) -> float | None:
    """单段 K 加权积分响度（LUFS）。

    **配比判据必须用 LUFS，不能用 RMS。** 同样 −20 dB RMS，密集音乐和语音的
    听感响度完全不同：实测同一段混音，RMS 口径差 6.3 dB，LUFS 口径差 8.2 dB。
    阈值是按 LUFS 定标的，拿 RMS 去比会得出「不达标」的假结论。要看 RMS
    作交叉核对，用 `--rms`（不是拿来比阈值的）。
    """
    r = _run_ffmpeg(
        [_bin("ffmpeg"), "-ss", f"{start:.3f}", "-t", f"{max(0.1, dur):.3f}",
         "-i", str(path), "-af", "loudnorm=I=-16:print_format=json",
         "-f", "null", "-"])
    m = re.search(r'"input_i"\s*:\s*"?(-?[\d.]+)', r.stderr)
    return float(m.group(1)) if m else None


def curve(path: Path, reset: int = 5) -> dict[float, float]:
    """全曲逐 N 帧电平曲线。

    注意：astats 的逐点数值与 volumedetect 不完全一致，适合看**趋势**，
    下结论前请用 `--rms` 让窗口模式顺带打出每段 RMS 交叉核对。
    """
    r = _run_ffmpeg(
        [_bin("ffmpeg"), "-i", str(path), "-af",
         f"astats=metadata=1:reset={reset},"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level",
         "-f", "null", "-"])
    cur, out = None, {}
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            cur = float(m.group(1))
        m2 = re.search(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-\w+)", line)
        if m2 and cur is not None:
            # astats 对静音输出 `-inf`；float() 能解析它但不抛异常，
            # 会一路带到 int() 才 OverflowError，必须在这里就归一。
            v = float(m2.group(1))
            out[round(cur, 1)] = v if math.isfinite(v) else -99.0
    return out


def in_windows(t: float, wins: list[list[float]]) -> bool:
    return any(a <= t <= b for a, b in wins)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"找不到 {path}")
        return 2

    spec = {"voice": [], "gaps": []}
    # 终端下不传窗口 = 直接出全曲曲线；只有管道/重定向才读 stdin（否则挂起）。
    # argv 项之间要加空格拼回 JSON（"".join 会把被 shell 拆开的 JSON 拼坏）；
    # --rms 是开关，不是窗口 JSON 的一部分。
    argv = sys.argv[2:]
    want_rms = "--rms" in argv
    raw = " ".join(x for x in argv if x != "--rms") or \
        ("" if sys.stdin.isatty() else sys.stdin.read())
    if raw.strip():
        spec = json.loads(raw)

    voice, gaps = spec.get("voice") or [], spec.get("gaps") or []

    if voice or gaps:
        print(f"{path.name}  （窗口测量用 LUFS，感知口径）\n")

        def measure_wins(wins: list[list[float]]) -> list[tuple[float, float, float | None, float | None]]:
            out = []
            for a, b in wins:
                lv = lufs(path, a, b - a)
                rv = mean_volume(path, a, b - a) if want_rms else None
                out.append((a, b, lv, rv))
            return out

        vs, gs = measure_wins(voice), measure_wins(gaps)
        for label, ws in (("【人声段】", vs), ("【空档段（底床）】", gs)):
            print(label)
            for a, b, lv, rv in ws:
                s = f"  {a:6.2f}–{b:6.2f}s   " + (
                    f"{lv:7.1f} LUFS" if lv is not None else "      静音")
                if want_rms:
                    s += f"   （RMS {rv:6.1f} dB）" if rv is not None else "   （RMS 静音）"
                print(s)
        vv = [lv for _, _, lv, _ in vs if lv is not None]
        gg = [lv for _, _, lv, _ in gs if lv is not None]
        if vv and gg:
            d = sum(vv) / len(vv) - sum(gg) / len(gg)
            ok = "✓ 人声盖过底床" if d >= 8 else "✗ 人声未高出底床 8 dB"
            print(f"\n人声均值 {sum(vv)/len(vv):.1f} LUFS · 底床均值 {sum(gg)/len(gg):.1f} LUFS"
                  f" · 差 {d:+.1f} dB  {ok}")
        return 0

    print(f"{path.name} 逐 0.1s 电平\n")
    prev = None
    for t, db in sorted(curve(path).items()):
        bar = "#" * max(0, min(50, int((db + 60) * 0.9)))
        mark = ""
        if db <= -70:
            mark = "  ← 静音"
            if prev is not None and prev > -60:
                mark += "（此处起断流）"
        print(f"{t:6.1f}s  {bar:<50} {db:6.1f}{mark}")
        if db > -60:
            prev = db
    return 0


if __name__ == "__main__":
    sys.exit(main())