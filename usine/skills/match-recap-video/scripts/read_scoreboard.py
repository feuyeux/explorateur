#!/usr/bin/env python3
"""read_scoreboard.py — 用本地 OCR 读比分牌，建立「视频时间 ↔ 比赛时钟」。

为什么需要它：`probe_scoreboard.py` 只给候选裁窗；读数原本要靠人眼逐帧看
竖拼长图。当运行环境没有视觉输入（模型不能读图、视觉代理不可用）时，
人眼这一步就断了。本脚本把「读数」变成可复跑的 OCR，输出可直接回填窗口表的
锚点、比分变化（进球）与跳切候选。

用法：
    # 1) 先用探针拿候选裁窗
    python3 probe_scoreboard.py master.mp4 --out probe.json
    # 2) 用排名第一的候选读数（或手动 --crop）
    python3 read_scoreboard.py master.mp4 --from-probe probe.json --out sb.json
    python3 read_scoreboard.py master.mp4 --crop 480:110:1440:0 --out sb.json
    # 3) 离线回归（不跑 OCR、不需要 rapidocr）
    python3 read_scoreboard.py selftest

crop 的格式是 `w:h:x:y`（宽:高:左:上，裁窗四元组）。不同转播的比分牌几何不同，**不要抄别人的数字**。

读数下限（fail-closed）：一帧分钟都没读出来 = 裁窗多半不对（或这个转播没有
比分牌），**退出码 1** 并回显裁窗——不许拿全 None 的读数冒充「读过了」；
下游窗口表会把它当映射基准。分钟覆盖率 < 20% 时在 stderr 给警告。

依赖：`pip install rapidocr_onnxruntime`（CPU 即可）。没装就退出非零，不静默跳过。
selftest 不需要它。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MINUTE_RE = re.compile(r"(?<!\d)(\d{1,3})\s*'")
CLOCK_RE = re.compile(r"(?<!\d)(\d{1,3}):(\d{2})(?!\d)")
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?!\d)")
TEAMS_RE = re.compile(r"\b([A-Z]{1,4})\s*[:.]\s*([A-Z]{1,4})\b")


class ReadError(RuntimeError):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ReadError(f"找不到 {name}——装好 ffmpeg 并放进 PATH。")
    return path


def _crop_from_probe(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []
    if not cands:
        raise ReadError(f"{path} 里没有 candidates")
    return str(cands[0]["crop"])


def _extract(master: Path, crop: str, fps: float, out_dir: Path) -> list[Path]:
    """按 fps 采样裁窗帧。fps=1 时 t≈帧号-1。"""
    ff = _tool("ffmpeg")
    pattern = out_dir / "%05d.png"
    cmd = [ff, "-y", "-v", "error", "-i", str(master),
           "-vf", f"crop={crop},fps={fps}", str(pattern)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReadError(f"ffmpeg 抽帧失败：\n{proc.stderr[-1500:]}")
    frames = sorted(out_dir.glob("*.png"))
    if not frames:
        raise ReadError("抽帧结果为空——检查 crop 是否越界。")
    return frames


def _parse(texts: list[str]) -> dict:
    """从一帧 OCR 文本里读分钟 / 比分 / 队伍缩写。

    两种时钟形态都要认：`60'`（德甲，只有分钟）与 `89:58`（意甲 MM:SS）。
    MM:SS 会被比分正则误读成 89-58——时钟**优先**，且与时间钟重叠的比分
    候选跳过，取下一个不重叠的（同一帧里真正的比分「2-2」不能被吞）。"""
    joined = " | ".join(texts)
    mm = MINUTE_RE.search(joined)
    clock_match = CLOCK_RE.search(joined)
    minute = second = None
    clock = None
    minute_span: tuple[int, int] | None = None
    if mm and (not clock_match or mm.start() <= clock_match.start()):
        minute = int(mm.group(1))
        clock = f"{minute}'"
        minute_span = mm.span()
    elif clock_match:
        minute, second = int(clock_match.group(1)), int(clock_match.group(2))
        clock = f"{minute:02d}:{second:02d}"
        minute_span = clock_match.span()
    score = None
    for m in SCORE_RE.finditer(joined):
        if minute_span and m.start() < minute_span[1] and minute_span[0] < m.end():
            continue  # 时钟那一段不是比分
        score = f"{m.group(1)}-{m.group(2)}"
        break
    mt = TEAMS_RE.search(joined)
    return {
        "minute": minute,
        "second": second,
        "clock": clock,
        "score": score,
        "teams": f"{mt.group(1)}:{mt.group(2)}" if mt else None,
    }


def _fill(rows: list[dict]) -> None:
    """给每一行补 minute_est（线性插值）与 score_est（前向填充）。

    插值只用于**粗定位**；它不改变原始读数。跳切段的斜率会明显异常，
    所以同时输出 `minute_slope` 供人复核。
    """
    pts = [(r["t"], r["minute"] + (r.get("second") or 0) / 60.0)
           for r in rows if r["minute"] is not None]
    pts.sort()
    for r in rows:
        if r["minute"] is not None:
            r["minute_est"] = round(r["minute"] + (r.get("second") or 0) / 60.0, 2)
            r["minute_interpolated"] = False
            continue
        t = r["t"]
        if not pts:
            r["minute_est"] = None
            r["minute_interpolated"] = True
            continue
        if t <= pts[0][0]:
            r["minute_est"] = float(pts[0][1])
        elif t >= pts[-1][0]:
            r["minute_est"] = float(pts[-1][1])
        else:
            for (t0, m0), (t1, m1) in zip(pts, pts[1:]):
                if t0 <= t <= t1:
                    span = max(t1 - t0, 1e-9)
                    r["minute_est"] = round(m0 + (m1 - m0) * (t - t0) / span, 1)
                    break
        r["minute_interpolated"] = True

    # 前向填充比分；第一个读数之前保持 None
    last = None
    for r in rows:
        if r["score"] is not None:
            last = r["score"]
        r["score_est"] = last


def _anchors(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    score_changes: list[dict] = []
    last_score = None
    for r in rows:
        s = r["score"]
        if s is None:
            continue
        if last_score is not None and s != last_score:
            score_changes.append({
                "t": r["t"], "from": last_score, "to": s,
                "minute": r["minute"], "teams": r["teams"], "raw": r["texts"],
            })
        last_score = s

    jumps: list[dict] = []
    known = [(r["t"], r["minute"] + (r.get("second") or 0) / 60.0)
             for r in rows if r["minute"] is not None]
    for (t0, m0), (t1, m1) in zip(known, known[1:]):
        dt = t1 - t0
        dm = m1 - m0
        if dt > 0 and dm / dt > 1.5:
            jumps.append({"t0": t0, "t1": t1, "minute0": m0, "minute1": m1,
                          "video_dt": dt, "match_dm": dm,
                          "slope": round(dm / dt, 3)})
    return score_changes, jumps


# 读数覆盖率地板：比分牌每秒都在画面上，fps=1 采样下正常读数覆盖率远高于此。
MIN_MINUTE_COVERAGE = 0.2


def assert_reads(rows: list[dict], crop: str) -> float:
    """读数覆盖率下限（fail-closed）。返回分钟覆盖率。

    全 None 的读数会让下游把「没读到」当「读过了」——映射表是窗口表一切
    落点的依据，空读数必须退出码非零并回显裁窗，不许静默产出。"""
    if not rows:
        raise ReadError(f"一帧都没采到（crop={crop}）——检查 crop 是否越界。")
    reads = sum(1 for r in rows if r["minute"] is not None)
    coverage = reads / len(rows)
    if reads == 0:
        raise ReadError(
            f"OCR 一帧分钟都没读出来（crop={crop}）——裁窗多半不对，或这个转播"
            "根本没有比分牌。映射表不能建立在零读数上；先用 probe_scoreboard.py "
            "重探候选裁窗。")
    if coverage < MIN_MINUTE_COVERAGE:
        print(f"警告：分钟读数覆盖率只有 {coverage:.0%}（{reads}/{len(rows)} 帧）——"
              "裁窗可能只擦到比分牌边缘，逐帧核对 reads 再用。",
              file=sys.stderr)
    return coverage


# ---------------------------------------------------------------- 自检（纯函数，不跑 OCR）


def selftest() -> int:
    """_parse / _fill / _anchors / assert_reads 的离线回归。

    这些是纯函数，喂罐头数据就能测——不需要 rapidocr、不需要真视频；
    覆盖率地板的负例（全 None 读数必须炸）也在这里锁住。"""
    checks: list[tuple[str, bool, str]] = []

    def check(label, ok, detail=""):
        checks.append((label, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")

    # _parse：分钟 / 比分 / 队伍缩写
    got = _parse(["60'", "1-1", "FCB:BVB"])
    check("_parse: 德甲分钟 + 比分 + 队伍",
          got == {"minute": 60, "second": None, "clock": "60'",
                  "score": "1-1", "teams": "FCB:BVB"}, f"{got}")
    got = _parse(["89:58", "2-2"])
    check("_parse: 意甲 MM:SS 时钟（秒不进分钟）",
          got["minute"] == 89 and got["second"] == 58
          and got["clock"] == "89:58" and got["score"] == "2-2", f"{got}")
    check("_parse: 读不出时全 None", _parse(["看台镜头"])["minute"] is None)

    # _fill：已知读数之间线性插值，比分前向填充
    rows = [
        {"t": 0.0, "minute": 1, "score": "0-0", "teams": None, "texts": []},
        {"t": 5.0, "minute": None, "score": None, "teams": None, "texts": []},
        {"t": 10.0, "minute": 11, "score": "1-0", "teams": None, "texts": []},
    ]
    _fill(rows)
    check("_fill: 插值（t=5 → 6.0）",
          rows[1]["minute_est"] == 6.0 and rows[1]["minute_interpolated"],
          f"{rows[1]['minute_est']}")
    check("_fill: 已知读数不标插值", not rows[0]["minute_interpolated"])
    check("_fill: 比分前向填充（缺失段沿用前值）", rows[1]["score_est"] == "0-0")

    # _anchors：比分变化 + 跳切（slope > 1.5 分钟/秒）
    rows = [
        {"t": 0.0, "minute": 60, "score": "1-1", "teams": "FCB:BVB", "texts": []},
        {"t": 1.0, "minute": 64, "score": "1-1", "teams": "FCB:BVB", "texts": []},
        {"t": 2.0, "minute": 64, "score": "2-1", "teams": "FCB:BVB", "texts": []},
    ]
    changes, jumps = _anchors(rows)
    check("_anchors: 比分变化被抓到",
          len(changes) == 1 and changes[0]["from"] == "1-1" and changes[0]["to"] == "2-1")
    check("_anchors: 跳切被抓到（slope=4）",
          len(jumps) == 1 and jumps[0]["slope"] == 4.0, f"{jumps}")
    _, jumps = _anchors([
        {"t": 0.0, "minute": 60, "score": "1-1", "teams": None, "texts": []},
        {"t": 1.0, "minute": 60, "score": "1-1", "teams": None, "texts": []},
    ])
    check("_anchors: 正常读数不算跳切", not jumps)

    # assert_reads：零读数必须炸（fail-closed），有读数返回覆盖率
    try:
        assert_reads([{"minute": None, "texts": []}], "1:1:0:0")
        check("assert_reads: 零读数必须拒绝", False, "没有抛 ReadError")
    except ReadError as exc:
        check("assert_reads: 零读数必须拒绝", "crop=1:1:0:0" in str(exc))
    try:
        assert_reads([], "1:1:0:0")
        check("assert_reads: 空帧必须拒绝", False)
    except ReadError:
        check("assert_reads: 空帧必须拒绝", True)
    cov = assert_reads([{"minute": 1}, {"minute": None}, {"minute": 3}], "c")
    check("assert_reads: 覆盖率 = 有读数帧占比", abs(cov - 2 / 3) < 1e-9, f"{cov:.2f}")

    bad = sum(1 for _, ok, _ in checks if not ok)
    print()
    print(f"自检：{len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="比分牌 OCR：视频时间 ↔ 比赛时钟")
    ap.add_argument("master", help="母版视频；填 'selftest' 跑离线回归（不跑 OCR）")
    ap.add_argument("--crop", help="裁窗四元组 w:h:x:y（与 --from-probe 二选一）")
    ap.add_argument("--from-probe", help="probe_scoreboard.py 的输出；取 rank 1 的 crop")
    ap.add_argument("--fps", type=float, default=1.0, help="采样帧率（默认 1）")
    ap.add_argument("--out", help="输出 JSON（默认 stdout）")
    ap.add_argument("--selftest", action="store_true", help="离线跑纯函数回归，不跑 OCR")
    args = ap.parse_args(argv)

    if args.selftest or args.master == "selftest":
        return selftest()

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        print("缺 rapidocr_onnxruntime：pip install rapidocr_onnxruntime", file=sys.stderr)
        return 2

    crop = args.crop or (_crop_from_probe(Path(args.from_probe)) if args.from_probe else None)
    if not crop:
        print("需要 --crop w:h:x:y 或 --from-probe probe.json", file=sys.stderr)
        return 2

    master = Path(args.master)
    if not master.exists():
        print(f"母版不存在：{master}", file=sys.stderr)
        return 2

    engine = RapidOCR()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            frames = _extract(master, crop, args.fps, Path(tmp))
            rows = []
            for i, f in enumerate(frames):
                res, _ = engine(str(f))
                texts = [str(t) for _, t, _ in (res or [])]
                row = {"t": round(i / args.fps, 3), "frame": i + 1,
                       "texts": texts, **_parse(texts)}
                rows.append(row)
        coverage = assert_reads(rows, crop)
    except ReadError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _fill(rows)
    score_changes, jumps = _anchors(rows)
    first_score = next((r["score"] for r in rows if r["score"]), None)
    last_score = next((r["score"] for r in reversed(rows) if r["score"]), None)
    out = {
        "master": str(master),
        "crop": crop,
        "fps": args.fps,
        "minute_coverage": round(coverage, 3),
        "reads": rows,
        "first_score": first_score,
        "last_score": last_score,
        "score_changes": score_changes,
        "jumps": jumps,
        "notes": [
            "minute_est 是已知读数之间的线性插值，只用于粗定位；跳切段看 jumps。",
            "score_est 是前向填充；比分变化以 score_changes 为准。",
            "OCR 会把 8/6、1/7 认混；比分变化要和官方事件分钟互相印证。",
        ],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"比分牌读数 → {args.out}")
    else:
        print(text)
    print(f"有效分钟读数 {sum(1 for r in rows if r['minute'] is not None)} / {len(rows)} 帧"
          f" · 比分变化 {len(score_changes)} 次 · 跳切候选 {len(jumps)} 处",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
