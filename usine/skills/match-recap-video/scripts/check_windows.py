#!/usr/bin/env python3
"""check_windows.py — match-recap-video 的逐窗判据机检。

把 references/visual-commentary.md §6.2 的三条硬判据变成**可判决**的检查，
并按 §6.3 做反向验证（注入坏例，判据必须全部抓到；抓不到就说明判据还只是注释）。

  判据 1（动作可指认）  kind != replay 且 visible != absent：
      say 里的每个动作词，必须能在同窗 see 找到——本身命中，或其动作族族首命中。
      找不到就判 FAIL：这一句在画面上无据。
  判据 2（回放不推进）  kind == replay：
      say 不得引入**观众还没听说过**的比赛分钟 / 比分 / 事件词。「听说过」的
      口径 = 前面各窗的 say **加 title / stat 卡**（§5：字幕卡已经说过的不算
      新信息，回放引用本事件的时间是合法的——「第 4 分钟那个球」）。
  判据 3（跳切不编画面）kind == jump：
      visible 必须是 absent；see 允许只写**读数**（比分牌 69:46 → 73:26、
      「无换人镜头」——§4.2 要求记读数），但 see 与 say 都不得含动作细节词；
      被跳过的时间里没有镜头，写了动作就是编。

`visible: unread` 是显式降级（运行环境没有视觉输入，画面没读）：判据 1 降 WARN，
不判 FAIL、也不冒充 PASS——冻结前必须人眼或视觉复核。

输入契约（表坏了是退出码 2，不是 FAIL 更不是 PASS）：
  - `windows` 必须是非空列表——空表没有可判的东西，静默 PASS 等于没有门禁；
  - 每窗必须有 `key`，且 `kind` ∈ live|replay|graphic|jump|ambient、
    `visible` ∈ event|aftermath|absent|unread——枚举写错会让判据 2/3 整段
    跳过（fail-open），必须在门口拦下；
  - 时间区间认 `src`（"36.2-42.0"）**或** `t0`/`t1`（SKILL.md 窗口表 schema 的
    字段）；两处同给时 `t0`/`t1` 优先。

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

KINDS = {"live", "replay", "graphic", "jump", "ambient"}
VISIBLE = {"event", "aftermath", "absent", "unread"}

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
# 只认横线分隔：`:` 会让比分牌时钟 69:46 被当成比分 69-46（中文旁白里
# 比分写「1-0」或「1 比 0」，时钟才会写成 MM:SS）。
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—]\s*(\d{1,2})(?!\d)")
SRC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)")
TIME_FIELDS = ("say", "title", "stat")


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


def _interval(win: dict) -> tuple[float, float] | None:
    """窗口时间区间：`src`（"36.2-42.0"）或 `t0`/`t1`（schema 字段）。

    两处同给时 t0/t1 优先——它是 SKILL.md 窗口表 schema 的正式字段，`src`
    是装配脚本沿用的紧凑写法，别让两处打架时静默取了不打算改的那份。
    """
    if win.get("t0") is not None and win.get("t1") is not None:
        try:
            return float(win["t0"]), float(win["t1"])
        except (TypeError, ValueError):
            return None
    src = str(win.get("src", "") or "").strip()
    m = SRC_RE.search(src) if src else None
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


# ---------------------------------------------------------------- 输入契约


def validate_table(doc: object) -> list[str]:
    """表级输入契约。违反 = 退出码 2：坏表不进判据，更不许静默 PASS。

    枚举必须在这里拦：`kind: "liive"` 的窗会让判据 2/3 整段跳过（fail-open），
    而 FAIL 才能被人修，静默跳过只会让人以为没问题。
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return [f"窗口表必须是 JSON 对象，实为 {type(doc).__name__}"]
    windows = doc.get("windows")
    if not isinstance(windows, list) or not windows:
        return ["windows 为空——没有可判的窗口；空表不是 PASS，是没输入"]
    for i, win in enumerate(windows):
        if not isinstance(win, dict):
            errors.append(f"第 {i + 1} 窗不是对象")
            continue
        key = str(win.get("key", "") or "").strip() or f"#{i + 1}"
        if not win.get("key"):
            errors.append(f"{key}: 缺 key")
        kind = str(win.get("kind", "") or "").strip().lower()
        if kind not in KINDS:
            errors.append(f"{key}: kind 必须是 {'|'.join(sorted(KINDS))}，实为 {win.get('kind')!r}"
                          "（枚举写错会让判据 2/3 整段跳过）")
        vis = str(win.get("visible", "") or "").strip().lower()
        if vis not in VISIBLE:
            errors.append(f"{key}: visible 必须是 {'|'.join(sorted(VISIBLE))}，实为 {win.get('visible')!r}")
        iv = _interval(win)
        if iv is not None and iv[1] <= iv[0]:
            errors.append(f"{key}: 时间区间非法（起点 ≥ 结点：{iv[0]}-{iv[1]}）")
    return errors


# ---------------------------------------------------------------- 三条判据


def check_window(
    win: dict,
    prior: dict,
    index: list[tuple[str, str]],
    vocab: dict,
    lenient: bool,
) -> list[dict]:
    """对单窗跑三条判据。prior = 前面各窗已陈述（say + title + stat）的分钟/比分/事件集合。"""
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
    # 「已陈述」含 title / stat：字幕卡说过的（观众看得到），回放引用不算推进
    # ——这是 §5「这条信息是不是观众上一窗已经知道的」的机检口径。
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
    # see 允许写**读数**（§4.2：比分牌 69:46 → 73:26、无换人镜头）——跳切段
    # 里比分牌还在画面上，读数是证据不是编造；但动作细节词进 see 同样是编。
    if kind == "jump":
        if not visible_is_absent(win):
            add(
                "判据3 跳切不编画面",
                "FAIL",
                f"jump 窗的 visible 必须是 absent，实为 {win.get('visible')!r}",
            )
        if not see.strip():
            add("判据3 跳切不编画面", "WARN",
                "jump 窗 see 为空：建议记下比分牌读数（跳切前后 MM:SS），别丢证据")
        for field, text in (("see", see), ("say", say)):
            terms = find_terms(text, index)
            if terms:
                add(
                    "判据3 跳切不编画面",
                    "FAIL",
                    f"jump 窗的 {field} 里有动作细节：" + "、".join(w for w, _ in terms),
                )

    # ---- 结构项：只标记 ----
    iv = _interval(win)
    if iv is not None:
        s, e = iv
        if s < prior["last_end"]:
            add(
                "结构 窗口区间",
                "WARN",
                f"时间区间与前一窗重叠（前窗结束 {prior['last_end']}s，本窗起点 {s}s）",
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


VOCAB: dict = {}  # 受控词表（_load_vocab_once 首次调用时加载，进程内唯一）


def _load_vocab_once() -> dict:
    global VOCAB
    if not VOCAB:
        VOCAB = load_vocab()
    return VOCAB


def check_table(doc: dict, lenient: bool = False) -> dict:
    """判据主体。输入契约的违例不进判据——由 validate_table 单独报，退出码 2。"""
    vocab = _load_vocab_once()
    index = build_index(vocab)
    windows = doc.get("windows") or []
    prior = {"minutes": set(), "scores": set(), "events": set(), "last_end": 0.0}
    findings: list[dict] = []
    for win in windows:
        findings.extend(check_window(win, prior, index, vocab, lenient))
        # 只有 live / jump / graphic / ambient 窗推进「观众已听到/看到」的进程；
        # replay 不推进。say 之外，title / stat 卡是观众同样看得到的信息层。
        if str(win.get("kind", "")).lower() != "replay":
            for field in TIME_FIELDS:
                text = str(win.get(field, "") or "")
                prior["minutes"] |= extract_minutes(text)
                prior["scores"] |= extract_scores(text)
                prior["events"] |= extract_events(text, vocab)
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
    """§6.3：好表必须全过，四个坏例必须各自被抓到；输入契约的坏表必须退出码 2。"""
    _load_vocab_once()
    cases = [
        ("good", "windows.good.json", True, []),
        ("bad-a", "windows.bad-a.json", False, ["判据2"]),
        ("bad-b", "windows.bad-b.json", False, ["判据3"]),
        ("bad-c", "windows.bad-c.json", False, ["判据1"]),
        ("bad-d", "windows.bad-d.json", False, ["判据3"]),
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
        if validate_table(doc):
            print(f"FAIL  {name}: 好例/坏例夹具本身过不了输入契约")
            bad += 1
            continue
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

    # ---- 输入契约：坏表必须被门口拦下（退出码 2 的那批） ----
    contract_cases: list[tuple[str, dict, bool]] = [
        ("空表不是 PASS", {"windows": []}, True),
        ("缺 windows 键", {}, True),
        ("kind 枚举笔误（liive）", {"windows": [
            {"key": "w1", "kind": "liive", "visible": "event", "say": "x", "see": "x"}]}, True),
        ("visible 枚举笔误（evnt）", {"windows": [
            {"key": "w1", "kind": "live", "visible": "evnt", "say": "x", "see": "x"}]}, True),
        ("区间倒挂", {"windows": [
            {"key": "w1", "kind": "live", "visible": "event", "t0": 30, "t1": 20,
             "say": "", "see": ""}]}, True),
        ("合法表过契约", {"windows": [
            {"key": "w1", "kind": "live", "visible": "event", "t0": 1, "t1": 2,
             "say": "", "see": ""}]}, False),
    ]
    for name, doc, should_reject in contract_cases:
        errs = validate_table(doc)
        ok = bool(errs) == should_reject
        print(f"{'PASS' if ok else 'FAIL'}  契约 {name}: "
              + (f"拦下 {errs[:1]}" if errs else "放行"))
        if not ok:
            bad += 1

    # ---- 语义锁：文档教的写法必须过判据 ----
    # 回放引用「只在 title 卡里出现过」的本事件时间——§5 明确合法，
    # 这条锁住 prior 必须并入 title/stat（否则照文档写会被误杀）。
    doc = {"windows": [
        {"key": "w1", "kind": "live", "visible": "event", "t0": 12.4, "t1": 16.0,
         "see": "国米前场断球后直塞，前锋禁区外远射",
         "title": "第12分钟 · 国米远射", "stat": "0-0",
         "say": "国米前场断球后直塞，前锋禁区外远射"},
        {"key": "w2", "kind": "replay", "visible": "event", "t0": 41.2, "t1": 44.0,
         "see": "禁区外远射（慢镜）",
         "title": "回看 · 第12分钟远射", "stat": "0-0",
         "say": "再看一遍，第 12 分钟那个球，禁区外远射"},
    ]}
    res = check_table(doc)
    ok = res["pass"]
    print(f"{'PASS' if ok else 'FAIL'}  语义锁 回放引用 title-only 分钟: "
          f"fail={res['fail']}")
    if not ok:
        bad += 1
        for f in res["findings"]:
            print(f"        [{f['level']}] {f['window']} {f['criterion']} — {f['why']}")

    # ---- 语义锁：jump 窗按 §4.2 写读数必须过；读数里混动作词必须被抓 ----
    doc_reading = {"windows": [
        {"key": "w1", "kind": "jump", "visible": "absent", "t0": 44.2, "t1": 46.0,
         "see": "比分牌 69:46 → 73:26；画面直接切到 73 分钟界外球，无换人镜头",
         "title": "换人 · 72' 国米", "stat": "1-1",
         "say": "这两分钟里国米先动了棋子：72 分钟两人上、两人下"},
    ]}
    res = check_table(doc_reading)
    ok = res["pass"]
    print(f"{'PASS' if ok else 'FAIL'}  语义锁 jump 窗 see 记读数: fail={res['fail']}")
    if not ok:
        bad += 1
        for f in res["findings"]:
            print(f"        [{f['level']}] {f['window']} {f['criterion']} — {f['why']}")

    print()
    print(f"反向验证：{'全部通过' if not bad else f'{bad} 条不通过'}")
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

    errs = validate_table(doc)
    if errs:
        for e in errs:
            print(f"输入契约：{e}", file=sys.stderr)
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
