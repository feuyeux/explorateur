#!/usr/bin/env python3
"""check_budget.py — 旁白落点的**预算机检**：在合成 TTS 之前就把「装不下」拦掉。

为什么要有这一步：`place_voice.py` 判越界是在**音频已经合成之后**。
那时一条窗已经花掉一次合成往返，压词重跑又是又一轮——本 skill 最大的
时间开销（中文 TTS 一段几秒到几十秒）全花在返工上。本脚本只看
**窗口表 + 文案**，几毫秒出结果，让「压词」发生在写稿阶段而不是渲染阶段。

判据（来自 references/visual-commentary.md §5 与 scripts/place_voice.py 的落点公式）：

  落点起点 = anchor + LEAD（LEAD = 0.45s，align=start）
  落点终点 = 起点 + 该段实际时长
  合规要求：终点 ≤ 窗口终点 t1

  所以 **可用的旁白秒数 = t1 - anchor - LEAD**，在 `align=end` 时是
  `anchor - t0`（收句落在 anchor，起句要更早）。

「anchor 放窗尾」是这个 skill 最常见的结构性错误：把 anchor 写在窗口
末尾（例如 4.2 落在一个 0–8.1s 的窗里），可用预算只剩 3.45s，
一句话根本放不下；而正确的 anchor 是**动作起手那一帧**，通常在窗的前段，
预算接近整窗长度。本脚本把这种「预算被吃掉大半」的窗显式报出来。

字数换算：中文 TTS 实测约 0.24–0.31 s/字（voice / rate 不同会浮动，
本脚本默认 0.28 s/字，偏保守——宁可估得长一点，早压词）。有
`voice-report.json`（实测时长）时优先用实测值，不用估算。

用法：
    python3 check_budget.py <windows.json> [--voice voice-report.json]
                            [--s-per-char 0.28] [--lead 0.45]
                            [--min-slack-ratio 0.35] [--json]

退出码：0 = 全部装得下（可能有 WARN）；1 = 有 FAIL（预算不足 / anchor 出窗）；
2 = 输入坏了（读不动 / 表非法）。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_windows as cw  # noqa: E402  （窗口表 schema 的解析只有它一处）

LEAD = 0.45
DEFAULT_S_PER_CHAR = 0.28
# 预算被吃掉这么多以上就报 WARN：正常一窗的 anchor 落在动作起手，
# 预算应接近整窗；只剩三成以下通常意味着 anchor 写到了窗尾。
MIN_SLACK_RATIO = 0.35


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_voice(path: Path) -> dict[str, float]:
    """voice-report → {key: duration}。读不动就当没有实测值（退回字数估算）。"""
    doc = load_json(path)
    entries = doc.get("segments") if isinstance(doc, dict) else doc
    out: dict[str, float] = {}
    if isinstance(entries, list):
        for e in entries:
            if not isinstance(e, dict):
                continue
            key = str(e.get("key") or e.get("window") or "").strip()
            if not key:
                continue
            try:
                out[key] = float(e["duration"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def measure_s_per_char(windows: list[dict], voice: dict[str, float]) -> float | None:
    """从实测音频反推 s/字（比默认常数准）。样本不足就返回 None。"""
    by = {str(w.get("key")): w for w in windows}
    ratios: list[float] = []
    for key, dur in voice.items():
        win = by.get(key)
        if not win:
            continue
        say = str(win.get("say") or "")
        n = len(say)
        if n >= 4 and dur > 0:
            ratios.append(dur / n)
    if len(ratios) < 3:
        return None
    return statistics.median(ratios)


# 实测 s/字 的合理带宽：中文 TTS（zh 系音色、rate −10%~0%）实测 0.24–0.40。
# 一段离谱（比如 8.86s / 7 字 = 1.27 s/字）只可能是 voice-report 与当前
# 窗口表**不同代**——改完窗口表没重跑 TTS，旧的实测时长会污染判据
# （2026-11-08 实测：整表 12 段里 4 段被旧读数误判超窗）。此时整份报告
# 作废，退回字数估算，并显式报出来。
S_PER_CHAR_MIN = 0.10
S_PER_CHAR_MAX = 0.60


def detect_stale(windows: list[dict], voice: dict[str, float]) -> list[str]:
    """voice-report 与窗口表是否同代：逐段 s/字出带宽即视为陈旧。"""
    by = {str(w.get("key")): w for w in windows}
    out: list[str] = []
    for key, dur in voice.items():
        win = by.get(key)
        if not win:
            continue
        n = len(str(win.get("say") or ""))
        if n < 4 or dur <= 0:
            continue
        r = dur / n
        if not (S_PER_CHAR_MIN <= r <= S_PER_CHAR_MAX):
            out.append(f"{key}: {dur:.2f}s / {n} 字 = {r:.2f} s/字（合理带宽 "
                       f"{S_PER_CHAR_MIN}–{S_PER_CHAR_MAX}）")
    return out


def _interval_of(win: dict) -> tuple[float, float]:
    """窗口区间。契约层（cw.validate_table）已保证存在，这里再兜一层。

    裸解包会抛 `TypeError: cannot unpack non-iterable NoneType`——退出码 1（像判据失败），
    而实际是「输入契约坏了」，该退 2。宁可报一句人话。
    """
    iv = cw._interval(win)
    if iv is None:
        key = str(win.get("key") or "?")
        raise ValueError(
            f"{key}: 缺时间区间（t0/t1 或 src）——输入契约坏了，请先过 check_windows.py")
    return iv


def analyse(
    windows: list[dict],
    voice: dict[str, float],
    lead: float,
    s_per_char: float,
    min_slack_ratio: float,
) -> dict:
    fails: list[str] = []
    warns: list[str] = []
    rows: list[dict] = []
    for win in windows:
        key = str(win.get("key"))
        t0, t1 = _interval_of(win)
        align = str(win.get("align") or "start").strip().lower()
        anchor_raw = win.get("anchor")
        anchor = float(anchor_raw) if anchor_raw is not None else t0
        say = str(win.get("say") or "")
        n = len(say)

        # 可用秒数：align=start ⇒ t1 - anchor - LEAD；align=end ⇒ anchor - t0
        if align == "end":
            budget = anchor - t0
            if anchor_raw is None:
                fails.append(f"{key}: align=end 必须显式给 anchor")
        else:
            budget = t1 - anchor - lead

        est = voice.get(key)
        if est is None:
            est = n * s_per_char if n else 0.0
            src = "估"
        else:
            src = "实测"

        window_len = max(t1 - t0, 1e-6)
        used_ratio = (est / window_len) if window_len else 0.0
        row = {
            "key": key, "kind": win.get("kind"), "align": align,
            "t0": round(t0, 3), "t1": round(t1, 3), "anchor": round(anchor, 3),
            "chars": n, "budget_s": round(budget, 3),
            "budget_chars": int(budget / s_per_char) if s_per_char and budget > 0 else 0,
            "est_s": round(est, 3), "src": src,
            "slack": round(budget - est, 3),
            "used_ratio": round(used_ratio, 3),
        }
        rows.append(row)

        if anchor_raw is not None and not (t0 - 1e-6 <= anchor <= t1 + 1e-6):
            fails.append(f"{key}: anchor {anchor:.2f}s 出窗（本窗 {t0:.2f}–{t1:.2f}s）")
            continue
        if budget <= 0:
            fails.append(
                f"{key}: 可用预算 {budget:.2f}s ≤ 0——anchor {anchor:.2f}s "
                f"落在窗尾或窗外，改到动作起手帧，或压词/拆窗")
            continue
        if est > budget + 1e-6:
            fix = "压词（缩短 say）或拆窗" if src == "估" else "压词或拆窗"
            fails.append(
                f"{key}: 旁白约 {est:.2f}s（{src}，{n} 字），"
                f"可用预算只有 {budget:.2f}s（超 {est - budget:.2f}s）——{fix}，"
                f"不许把 anchor 往后挪")
            continue
        # 预算被吃掉大半：多半是 anchor 写到了窗尾（结构性错误，不一定超窗）
        if budget < window_len * min_slack_ratio and window_len >= 3.0:
            warns.append(
                f"{key}: 可用预算 {budget:.2f}s 只占整窗 {window_len:.2f}s 的 "
                f"{budget / window_len:.0%}——anchor 落在窗尾附近？"
                f"anchor 应是**动作起手那一帧**，通常在窗的前段")
        if n > 0 and budget / s_per_char < n * 0.6 and src == "估":
            warns.append(f"{key}: 估算时长偏保守，实际可能装得下；先跑一次 TTS 再定")

    # 叠音预估：两窗的落点区间重叠 ⇒ 合成后 place_voice 一定判叠音
    starts = []
    for row in rows:
        if row["align"] == "end":
            start = row["anchor"] - row["est_s"]
        else:
            start = row["anchor"] + lead
        starts.append((start, start + row["est_s"], row["key"]))
    starts.sort()
    for a, b in zip(starts, starts[1:]):
        if b[0] < a[1] - 1e-6:
            fails.append(
                f"{a[2]} 与 {b[2]} 预估叠音：前段到 {a[1]:.2f}s，后段 {b[0]:.2f}s 就进")

    return {"s_per_char": round(s_per_char, 4), "lead": lead,
            "rows": rows, "fail": fails, "warn": warns, "pass": not fails}


def selftest() -> int:
    """离线回归：估算/实测/陈旧报告/anchor 窗尾/叠音/align=end 缺锚点。"""
    import tempfile

    ok = True

    def check(name: str, got: bool, want: bool) -> None:
        nonlocal ok
        tag = "PASS" if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{tag}] {name}")

    win = lambda key, t0, t1, say, anchor=None, align=None: {  # noqa: E731
        "key": key, "t0": t0, "t1": t1, "kind": "live", "visible": "event",
        "anchor": anchor if anchor is not None else t0 + 0.5,
        "align": align or "start", "say": say,
        "see": "画面", "title": "t", "stat": "s"}

    # 1) 估算模式：三拍 22 字落在 8.08s 窗（anchor 1.5）→ 装不下（同真表 w01）
    t1_case = [win("w01", 0.0, 8.08, "一" * 22, anchor=1.5)]
    res = analyse(t1_case, {}, LEAD, DEFAULT_S_PER_CHAR, MIN_SLACK_RATIO)
    check("22 字 / 预算 6.13s 判 FAIL", not res["pass"], True)

    # 2) 同窗同字数压到 18 字 → 过
    res = analyse([win("w01", 0.0, 8.08, "一" * 18, anchor=1.5)],
                  {}, LEAD, DEFAULT_S_PER_CHAR, MIN_SLACK_RATIO)
    check("18 字 / 预算 6.13s 判 PASS", res["pass"], True)

    # 3) anchor 写到窗尾（结构性错误）：预算只剩 0.13s
    res = analyse([win("w01", 0.0, 8.08, "一二三四五", anchor=7.5)],
                  {}, LEAD, DEFAULT_S_PER_CHAR, MIN_SLACK_RATIO)
    check("anchor 窗尾判 FAIL", not res["pass"], True)

    # 4) align=end 缺 anchor → FAIL
    res = analyse([win("w01", 0.0, 8.08, "一二三", align="end")],
                  {}, LEAD, DEFAULT_S_PER_CHAR, MIN_SLACK_RATIO)
    check("align=end 缺 anchor 判 FAIL", not res["pass"], True)

    # 5) 叠音预估：前段（40 字 ≈ 11.2s）拖进后段（10.95s 就进）
    two = [win("a", 0.0, 10.0, "一" * 40, anchor=1.0),
           win("b", 10.0, 20.0, "二" * 28, anchor=10.5)]
    res = analyse(two, {}, LEAD, DEFAULT_S_PER_CHAR, MIN_SLACK_RATIO)
    check("相邻窗预估叠音判 FAIL", not res["pass"], True)

    # 6) 陈旧 voice-report：一段 15.2s / 12 字 = 1.27 s/字 出带宽
    with tempfile.TemporaryDirectory() as td:
        wins = [win("w01", 0.0, 20.0, "一" * 12, anchor=1.0),
                win("w02", 20.0, 40.0, "二" * 12, anchor=21.0),
                win("w03", 40.0, 60.0, "三" * 12, anchor=41.0)]
        stale_doc = {"segments": [
            {"key": "w01", "duration": 3.9}, {"key": "w02", "duration": 4.0},
            {"key": "w03", "duration": 15.2}]}  # ← 旧表的 w03
        vp = Path(td) / "voice-report.json"
        vp.write_text(json.dumps(stale_doc), encoding="utf-8")
        wp = Path(td) / "windows.json"
        wp.write_text(json.dumps({"windows": wins}, ensure_ascii=False),
                      encoding="utf-8")
        rc = main(["--voice", str(vp), str(wp)])
        check("陈旧报告整份作废、按估算判 PASS", rc == 0, True)

        # 7) 同代报告：实测时长进判据
        fresh_doc = {"segments": [
            {"key": "w01", "duration": 3.9}, {"key": "w02", "duration": 4.0},
            {"key": "w03", "duration": 4.1}]}
        vp.write_text(json.dumps(fresh_doc), encoding="utf-8")
        rc = main(["--voice", str(vp), str(wp)])
        check("同代报告按实测判 PASS", rc == 0, True)

        # 8) 同代（带宽内）但实测真超窗 → FAIL
        over_doc = {"segments": [
            {"key": "w01", "duration": 3.9}, {"key": "w02", "duration": 4.0},
            {"key": "w03", "duration": 19.4}]}  # 19.4/34 = 0.57，在带宽内
        wins2 = [win("w01", 0.0, 20.0, "一" * 17, anchor=1.0),
                 win("w02", 20.0, 40.0, "二" * 12, anchor=21.0),
                 win("w03", 40.0, 60.0, "三" * 34, anchor=41.0)]
        wp.write_text(json.dumps({"windows": wins2}, ensure_ascii=False),
                      encoding="utf-8")
        vp.write_text(json.dumps(over_doc), encoding="utf-8")
        rc = main(["--voice", str(vp), str(wp)])
        check("实测超窗判 FAIL", rc == 1, True)

    print("selftest：" + ("全部通过" if ok else "有用例失败"))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description="match-recap-video 旁白预算机检（TTS 之前）")
    ap.add_argument("windows", help="窗口表 JSON")
    ap.add_argument("--voice", help="TTS 实测报告 JSON（有就用实测时长）")
    ap.add_argument("--s-per-char", type=float, default=None,
                    help=f"秒/字（默认从实测反推，取不到用 {DEFAULT_S_PER_CHAR}）")
    ap.add_argument("--lead", type=float, default=LEAD, help=f"起拍余量（默认 {LEAD}s）")
    ap.add_argument("--min-slack-ratio", type=float, default=MIN_SLACK_RATIO,
                    help="预算占整窗比例低于此值给 WARN（默认 0.35）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args(argv)

    try:
        doc = load_json(Path(args.windows))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"窗口表读不动：{exc}", file=sys.stderr)
        return 2

    errors = cw.validate_table(doc)
    if errors:
        for e in errors:
            print(f"输入契约：{e}", file=sys.stderr)
        return 2
    windows = list(doc["windows"])

    voice: dict[str, float] = {}
    stale: list[str] = []
    if args.voice:
        try:
            voice = load_voice(Path(args.voice))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"voice-report 读不动（改用字数估算）：{exc}", file=sys.stderr)
        if voice:
            stale = detect_stale(windows, voice)
            if stale:
                print("voice-report 疑似陈旧（与当前窗口表不同代），整份作废、改用估算：",
                      file=sys.stderr)
                for s in stale:
                    print(f"  - {s}", file=sys.stderr)
                voice = {}

    s_per_char = args.s_per_char or measure_s_per_char(windows, voice) or DEFAULT_S_PER_CHAR
    try:
        res = analyse(windows, voice, args.lead, s_per_char, args.min_slack_ratio)
    except ValueError as exc:
        print(f"输入契约：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"s/char = {res['s_per_char']:.3f}"
              f"（{'实测反推' if voice else '默认'}）  LEAD = {res['lead']}s")
        print(f"{'key':<6}{'kind':<9}{'窗区间':>14}{'anchor':>8}{'预算s':>7}{'预算字':>7}"
              f"{'字':>5}{'估s':>7}{'源':>5}{'余量':>8}")
        for r in res["rows"]:
            print(f"{r['key']:<6}{str(r['kind'] or ''):<9}{r['t0']:6.2f}-{r['t1']:<7.2f}"
                  f"{r['anchor']:8.2f}{r['budget_s']:7.2f}{r['budget_chars']:7d}"
                  f"{r['chars']:5d}{r['est_s']:7.2f}{r['src']:>5}{r['slack']:+8.2f}")
        for w in res["warn"]:
            print(f"WARN  {w}")
        for f in res["fail"]:
            print(f"FAIL  {f}")
        print()
        print("预算机检："
              + ("全部装得下" if res["pass"]
                 else f"{len(res['fail'])} 条装不下"))

    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
