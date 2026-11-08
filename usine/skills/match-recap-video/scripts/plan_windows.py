# -*- coding: utf-8 -*-
"""plan_windows.py — 候选窗口边界 = 镜头切点 ∪ 比分牌时钟跳变。

为什么两个来源都要：
  - **镜头切点**（cuts.py 的场景分）给「换机位 / 进慢放 / 出图形页」的边界；
  - **比分牌时钟跳变**（read_scoreboard.py 的逐秒读数）给「集锦跳掉了几分钟」的边界。
  两者常常不重合：官方集锦跳时间时可能仍是同一机位的远景（软切），scene 分
  抓不到；但比分牌时钟一定跳。反过来换机位时时钟可能连续。⇒ 只用其一都会漏。

实测补充（2026-11-08 四场欧冠/欧联）：
  - 一个读数间隙里可能藏着**不止一个跳变**（进球包的回放没有比分牌，
    读数间隙 = 「跳进回放 + 跳出回放」两段）；本脚本只在可读读数之间
    报一个跳变点，**间隙内部要靠抽帧再分**；
  - 被完全跳过的进球（现场镜头根本没进母版）没有时钟可读——这种窗用
    kind=jump / visible=absent 承载进程，比分交给 stat 卡；
  - 转播时钟与官方事件钟差约 ±1 分钟，**标分钟用官方 minute 字段，
    定锚用转播时钟读数**，两套数不混用。

用法：
    python3 scripts/plan_windows.py <cuts.json> [sb.json] [--out plan.json]

退出码：0 = 出 plan；2 = 输入坏了。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def clock_seconds(text: str) -> float | None:
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"(\d{1,3})'", text)
    if m:
        return int(m.group(1)) * 60
    return None


def score_of(text: str) -> str | None:
    """从读数文本里抓比分（XX 1-2 YY / XX12YY 两种形态）。

    ⚠️ OCR 会把 8/6、1/7 认混，比分列还可能整列失败（客队名前缀格式）——
    比分的**事实源永远是官方比赛页**，这里只做粗定位。
    """
    m = re.search(r"[A-Z]{2,4}\s*(\d)\D{0,3}(\d)\s*[A-Z]{2,4}", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def build_series(reads: list[dict]) -> list[tuple[float, float, str | None]]:
    """逐秒读数 → [(视频秒, 时钟秒, 比分|None)]。"""
    series: list[tuple[float, float, str | None]] = []
    for r in reads:
        txt = "".join(r.get("texts") or [])
        c = clock_seconds(txt)
        if c is None and r.get("minute") is not None:
            c = float(r["minute"]) * 60 + float(r.get("second") or 0)
        if c is None:
            continue
        series.append((float(r["t"]), c, score_of(txt)))
    return series


def find_jumps(series: list[tuple[float, float, str | None]],
               min_jump: float = 45.0) -> list[dict]:
    """相邻可读读数的时钟差 > min_jump 秒 = 一次时间轴跳变。"""
    jumps: list[dict] = []
    for i in range(1, len(series)):
        t0, c0, _ = series[i - 1]
        t1, c1, _ = series[i]
        if c1 - c0 > min_jump:
            jumps.append({"t": round((t0 + t1) / 2, 2), "from": round(c0, 1),
                          "to": round(c1, 1), "gap": round(c1 - c0, 1)})
    return jumps


def merge_segments(bounds: list[float], total: float,
                   min_len: float = 1.2) -> list[dict]:
    """合并过短的段（<min_len 并进前一段），输出连续段。"""
    segs: list[dict] = []
    prev = 0.0
    for b in bounds + [total]:
        if b - prev < min_len and segs:
            segs[-1]["t1"] = round(b, 2)
            prev = b
            continue
        segs.append({"t0": round(prev, 2), "t1": round(b, 2)})
        prev = b
    return segs


def plan(cuts_doc: dict, reads: list[dict]) -> dict:
    total = float(cuts_doc["total"])
    series = build_series(reads)
    jumps = find_jumps(series)
    bounds = {0.0, total}
    for c in cuts_doc.get("cuts", []):
        bounds.add(float(c[0]))
    for j in jumps:
        bounds.add(j["t"])
    bounds_list = sorted(b for b in bounds if 0.0 < b < total)
    segs = merge_segments(bounds_list, total)
    for i, s in enumerate(segs):
        s["i"] = i
        s["len"] = round(s["t1"] - s["t0"], 2)
        inside = [x for x in series if s["t0"] <= x[0] <= s["t1"]]
        if inside:
            s["clock0"] = f"{int(inside[0][1]) // 60}:{int(inside[0][1]) % 60:02d}"
            s["clock1"] = f"{int(inside[-1][1]) // 60}:{int(inside[-1][1]) % 60:02d}"
            sc = [x[2] for x in inside if x[2]]
            s["score"] = sc[-1] if sc else None
        else:
            s["clock0"] = s["clock1"] = None
            s["score"] = None
    return {"total": round(total, 2), "jumps": jumps, "segments": segs}


def selftest() -> int:
    """离线回归：合成切点+读数 → 跳变与分段都要对。"""
    ok = True

    def check(name: str, got: bool, want: bool) -> None:
        nonlocal ok
        if got != want:
            ok = False
        print(f"  [{'PASS' if got == want else 'FAIL'}] {name}")

    check("clock_seconds 89:58", clock_seconds("89:58") == 89 * 60 + 58, True)
    check("clock_seconds 60'", clock_seconds("60'") == 3600, True)
    check("clock_seconds 无时钟", clock_seconds("MIL 0 0 FER") is None, True)
    check("score_of BAR 3 0 AVL", score_of("BAR 3 0 AVL") == "3-0", True)
    check("score_of 紧凑形", score_of("MIL02FER") == "0-2", True)
    check("score_of 无比分", score_of("8:25 crowd noise") is None, True)

    series = [(10.0, 500.0, None), (20.0, 510.0, None),   # 1:1 段
              (21.0, 700.0, None),                        # 跳 +190s
              (30.0, 709.0, None)]
    jumps = find_jumps(series)
    check("跳变检测 1 处", len(jumps) == 1 and jumps[0]["gap"] == 190.0, True)

    cuts_doc = {"total": 100.0, "cuts": [[15.0, 1.0], [50.0, 1.0]]}
    out = plan(cuts_doc, [{"t": t, "texts": [f"{int(c // 60)}:{int(c % 60):02d}"]}
                          for t, c, _ in series])
    check("分段含切点与跳变点", len(out["segments"]) >= 4, True)
    check("段连续且覆盖全长",
          out["segments"][0]["t0"] == 0.0
          and abs(out["segments"][-1]["t1"] - 100.0) < 0.01, True)

    print("selftest：" + ("全部通过" if ok else "有用例失败"))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description="候选窗口边界 = 切点 ∪ 时钟跳变")
    ap.add_argument("cuts", help="cuts.py 的 cuts.json")
    ap.add_argument("sb", nargs="?", help="read_scoreboard.py 的输出（可选；无时钟版式可省）")
    ap.add_argument("--out", help="输出 plan.json（默认与 cuts.json 同目录）")
    args = ap.parse_args(argv)

    try:
        cuts_doc = json.loads(Path(args.cuts).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cuts.json 读不动：{exc}", file=sys.stderr)
        return 2
    reads: list[dict] = []
    if args.sb:
        try:
            reads = json.loads(Path(args.sb).read_text(encoding="utf-8")).get("reads") or []
        except (OSError, json.JSONDecodeError) as exc:
            print(f"sb.json 读不动（按纯切点分段）：{exc}", file=sys.stderr)

    out = plan(cuts_doc, reads)
    out_path = Path(args.out) if args.out else Path(args.cuts).with_name("plan.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"候选窗 {len(out['segments'])} 段（切点 {len(cuts_doc.get('cuts', []))}"
          f" + 时钟跳变 {len(out['jumps'])}）→ {out_path}")
    for s in out["segments"]:
        c = f"{s['clock0']}–{s['clock1']}" if s["clock0"] else "—"
        print(f"{s['i']:>3}{s['t0']:8.2f}–{s['t1']:<7.2f}{s['len']:7.2f}  "
              f"{c:>16}{str(s['score'] or '—'):>8}")
    for j in out["jumps"]:
        print(f"  跳变 t={j['t']:7.2f}  {int(j['from']) // 60}:{int(j['from']) % 60:02d}"
              f" → {int(j['to']) // 60}:{int(j['to']) % 60:02d}  (跳 {j['gap'] / 60:.1f} 分钟)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
