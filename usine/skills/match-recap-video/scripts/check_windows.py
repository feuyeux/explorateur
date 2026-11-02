#!/usr/bin/env python3
"""check_windows.py — match-recap-video 的逐窗判据机检。

把 references/visual-commentary.md §6.2 的三条硬判据变成**可判决**的检查，
并按 §6.3 做反向验证（注入三个坏例，判据必须全部抓到；抓不到就说明判据还只是注释）。

  判据 1（动作可指认）  kind != replay 且 visible != absent：
      say 里的每个动作词，必须能在同窗 see 找到——本身命中，或其动作族族首命中。
      找不到就判 FAIL：这一句在画面上无据。
  判据 2（回放不推进）  kind == replay：
      say 不得引入**前面还没出现过**的比赛分钟 / 比分 / 事件词。回放只讲细节。
  判据 3（跳切不编画面）kind == jump：
      visible 必须是 absent；say 不得含动作细节词（只有时间、人、战术影响）。

`visible: unread` 是显式降级（运行环境没有视觉输入，画面没读）：判据 1 降 WARN，
不判 FAIL、也不冒充 PASS——冻结前必须人眼或视觉复核。

§6.4 说词表扫候选「不能自动判 FAIL」——那是**裸词表**的限制：词表不知道自己
在哪种窗、这窗之前说过什么。本检查带了窗口表上下文（kind / visible / see /
已陈述集合），上面三小段因此**可以机械判决**，所以判 FAIL。
判不了的那部分（近义改写、语义近似）一律降级 WARN，绝不冒充 FAIL。

用法：
    python3 check_windows.py <windows.json> [--lenient] [--json]
    python3 check_windows.py --selftest

退出码：0 = 无 FAIL（可能有 WARN）；1 = 有 FAIL；2 = 输入/环境坏了。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FIXTURES = ASSETS / "fixtures"

# ---------------------------------------------------------------- 词表


def load_vocab() -> dict:
    with (ASSETS / "action-families.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def build_index(vocab: dict) -> list[tuple[str, str]]:
    """(词, 族首) 列表，按词长降序——先匹配长词，避免「头球破门」被「头球」抢走。"""
    pairs: list[tuple[str, str]] = []
    for head, words in vocab["动作族"].items():
        for w in words:
            pairs.append((w, head))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def find_terms(text: str, index: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """扫出文本里命中的动作词（长词优先，已命中的位置不再重复计）。"""
    found: list[tuple[str, str]] = []
    taken: list[tuple[int, int]] = []
    for word, head in index:
        for m in re.finditer(re.escape(word), text):
            span = m.span()
            if any(span[0] < e and s < span[1] for s, e in taken):
                continue
            taken.append(span)
            found.append((word, head))
            break
    return found


# ---------------------------------------------------------------- 抽取

MINUTE_RE = re.compile(r"第\s*(\d{1,3})\s*分钟|(\d{1,3})\s*['′]")
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—:]\s*(\d{1,2})(?!\d)")
SRC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)")


def extract_minutes(text: str) -> set[int]:
    out: set[int] = set()
    for m in MINUTE_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw:
            out.add(int(raw))
    return out


def extract_scores(text: str) -> set[str]:
    return {f"{m.group(1)}-{m.group(2)}" for m in SCORE_RE.finditer(text)}


def extract_events(text: str, vocab: dict) -> set[str]:
    low = text.lower()
    out: set[str] = set()
    for ev in vocab["事件词"]:
        if ev.lower() in low:
            out.add(ev)
    return out


def visible_is_absent(win: dict) -> bool:
    return str(win.get("visible", "")).strip().lower() == "absent"


# ---------------------------------------------------------------- 三条判据


def check_window(
    win: dict,
    prior: dict,
    index: list[tuple[str, str]],
    vocab: dict,
    lenient: bool,
) -> list[dict]:
    """对单窗跑三条判据。prior = 前面各窗已陈述的分钟/比分/事件集合。"""
    key = win.get("key", "?")
    kind = str(win.get("kind", "")).lower()
    see = str(win.get("see", "") or "")
    say = str(win.get("say", "") or "")
    out: list[dict] = []

    def add(crit: str, level: str, why: str) -> None:
        out.append({"window": key, "criterion": crit, "level": level, "why": why})

    # ---- 判据 1：动作可指认 ----
    # 回放窗也要判（§6.1 的对账表里 replay 行同样勾了「say 的动作都能指回 see」）。
    # visible=unread 是显式降级：本次运行没有视觉输入（模型不能读图 / 视觉代理不可用），
    # 画面没读就**不能**判动作对不上——降 WARN，交给人眼或视觉复核，不冒充 PASS。
    if str(win.get("visible", "")).strip().lower() == "unread":
        add("判据1 动作可指认", "WARN",
            "visible=unread：画面未读，动作句未作 FAIL；需视觉复核后再冻结")
    elif not visible_is_absent(win) and say:
        terms = find_terms(say, index)
        missing = [
            (w, h)
            for w, h in terms
            if w not in see and h not in see
        ]
        if missing:
            words = "、".join(f"{w}（{h}）" for w, h in missing)
            add(
                "判据1 动作可指认",
                "WARN" if lenient else "FAIL",
                f"say 的动作词在同窗 see 里找不到：{words}",
            )

    # ---- 判据 2：回放不推进 ----
    if kind == "replay":
        new_min = sorted(extract_minutes(say) - prior["minutes"])
        new_score = sorted(extract_scores(say) - prior["scores"])
        new_event = sorted(extract_events(say, vocab) - prior["events"])
        if new_min or new_score or new_event:
            parts = []
            if new_min:
                parts.append(f"新比赛分钟 {'、'.join(str(m) for m in new_min)}")
            if new_score:
                parts.append(f"新比分 {'、'.join(new_score)}")
            if new_event:
                parts.append(f"新事件 {'、'.join(new_event)}")
            add("判据2 回放不推进", "FAIL", "回放窗推进了进程：" + "；".join(parts))

    # ---- 判据 3：跳切不编画面 ----
    if kind == "jump":
        if not visible_is_absent(win):
            add(
                "判据3 跳切不编画面",
                "FAIL",
                f"jump 窗的 visible 必须是 absent，实为 {win.get('visible')!r}",
            )
        if see.strip():
            add("判据3 跳切不编画面", "FAIL", "jump 窗写了 see（画面上并没有东西可写）")
        terms = find_terms(say, index)
        if terms:
            add(
                "判据3 跳切不编画面",
                "FAIL",
                "jump 窗的 say 里有动作细节：" + "、".join(w for w, _ in terms),
            )

    # ---- 结构项：只标记 ----
    src = str(win.get("src", "") or "")
    m = SRC_RE.search(src)
    if m:
        s, e = float(m.group(1)), float(m.group(2))
        if e <= s:
            add("结构 窗口区间", "WARN", f"src 区间非法：{src}")
        elif s < prior["last_end"]:
            add(
                "结构 窗口区间",
                "WARN",
                f"src 与前一窗重叠（前窗结束 {prior['last_end']}s，本窗起点 {s}s）：{src}",
            )
        else:
            prior["last_end"] = e

    # ---- 结构项：字幕与旁白打架 ----
    for card in ("title", "stat"):
        card_text = str(win.get(card, "") or "")
        if card_text and card_text.strip() and card_text.strip() in say:
            add(
                "结构 字幕与旁白",
                "WARN",
                f"say 复述了 {card} 卡片内容（字幕和声音会打架）：{card_text.strip()!r}",
            )

    return out


def check_table(doc: dict, lenient: bool = False) -> dict:
    vocab = load_vocab()
    index = build_index(vocab)
    windows = doc.get("windows") or []
    prior = {"minutes": set(), "scores": set(), "events": set(), "last_end": 0.0}
    findings: list[dict] = []
    for win in windows:
        findings.extend(check_window(win, prior, index, vocab, lenient))
        # 只有 live / jump 窗推进「观众已听到」的进程；replay 不推进。
        if str(win.get("kind", "")).lower() != "replay":
            say = str(win.get("say", "") or "")
            prior["minutes"] |= extract_minutes(say)
            prior["scores"] |= extract_scores(say)
            prior["events"] |= extract_events(say, vocab)
    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]
    return {
        "windows": len(windows),
        "fail": len(fails),
        "warn": len(warns),
        "findings": findings,
        "pass": not fails,
    }


# ---------------------------------------------------------------- 反向验证


def selftest() -> int:
    """§6.3：好表必须全过，三个坏例必须各自被抓到。"""
    cases = [
        ("good", "windows.good.json", True, []),
        ("bad-a", "windows.bad-a.json", False, ["判据2"]),
        ("bad-b", "windows.bad-b.json", False, ["判据3"]),
        ("bad-c", "windows.bad-c.json", False, ["判据1"]),
    ]
    bad = 0
    for name, fname, should_pass, expect_crits in cases:
        path = FIXTURES / fname
        if not path.exists():
            print(f"FAIL  {name}: 夹具缺失 {path}")
            bad += 1
            continue
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
        res = check_table(doc)
        hit = {f["criterion"].split()[0] for f in res["findings"] if f["level"] == "FAIL"}
        if should_pass:
            ok = res["pass"]
            detail = f"fail={res['fail']} warn={res['warn']}"
        else:
            ok = (not res["pass"]) and all(c in hit for c in expect_crits)
            detail = f"fail={res['fail']} 命中={sorted(hit)} 期望={expect_crits}"
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        for f in res["findings"]:
            print(f"        [{f['level']}] {f['window']} {f['criterion']} — {f['why']}")
        if not ok:
            bad += 1
    print()
    print(f"反向验证：{len(cases) - bad}/{len(cases)} 通过")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="match-recap-video 逐窗判据机检")
    ap.add_argument("table", nargs="?",
                    help="窗口表 JSON 路径；填 'selftest' 跑 §6.3 反向验证")
    ap.add_argument("--lenient", action="store_true", help="判据1 降级为 WARN（近义改写容忍模式）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    if args.table == "selftest":
        return selftest()
    if not args.table:
        ap.print_help()
        return 2

    path = Path(args.table)
    if not path.exists():
        print(f"输入不存在：{path}", file=sys.stderr)
        return 2
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"JSON 解析失败：{exc}", file=sys.stderr)
        return 2

    res = check_table(doc, lenient=args.lenient)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"窗口 {res['windows']} 个　FAIL {res['fail']}　WARN {res['warn']}")
        for f in res["findings"]:
            print(f"  [{f['level']}] {f['window']} {f['criterion']} — {f['why']}")
        print("结论：" + ("PASS" if res["pass"] else "FAIL"))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
