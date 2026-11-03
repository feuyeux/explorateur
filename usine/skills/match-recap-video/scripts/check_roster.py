#!/usr/bin/env python3
"""check_roster.py — 球员名单的名字口径判决：球衣印字 ≠ 解说称呼。

**为什么需要这一步**：转播里最先被读到的名字是**球衣印字**（HAKIMI），而解说与
字幕卡该用的是**约定俗成的称呼**（阿什拉夫）。照着印字写词，球迷听到的是
「哈基米右路起球」——名字没错、人也没错，但这名球员在中文解说里不这么叫。
这不是翻译错误，是**称呼口径**错误：同一名球员在不同语境下有两个合法的名字，
名单必须同时记下来，并指定哪一个是本片的口径。

名单契约（每场一份，`players.json` / `名单.json`）：

    {"players": [
      {"shirt": "HAKIMI",        // 球衣印字（读画面 / 对账用）
       "shirt_zh": "哈基米",      // 印字按本片解说语念出来的样子（中文线 = 中文音译）
       "call": "阿什拉夫",        // 本片解说语称呼（旁白 / 字幕卡 / 封面只准用它）
       "full": "阿什拉夫·哈基米",  // 全名（首现可用；含印字音译时不算违规）
       "pos": "右后卫", "team": "巴黎圣日耳曼", "no": 2}
    ]}

判据：`shirt_zh` 与 `call` 不同的球员，**`shirt_zh` / `shirt` 不许出现在旁白、
字幕卡、发布文案里**；唯一例外是完整出现在 `full` 里（首现给全名是合法的）。
`shirt_zh == call` 的球员（印字就叫这个名）不触发判据。

名字是**每场比赛的事实**，不在 SKILL.md 里记具体球员；工具只执行口径。

用法：
    python3 check_roster.py --roster players.json --windows windows.json
    python3 check_roster.py --roster players.json --text publish/bilibili.md publish/douyin.md
    python3 check_roster.py selftest

退出码：0 = 名字口径合规；1 = 有违规（念了印字）；2 = 输入坏了（名单缺字段 /
重复称呼 / 窗口表非法）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_windows as cw  # noqa: E402  （窗口表 schema 的解析只有它一处）

FIELDS = ("say", "title", "stat")


# ---------------------------------------------------------------- 输入


def load_roster(doc: object) -> tuple[list[dict], list[str]]:
    """名单 → [{shirt, shirt_zh, call, full}]。契约坏了返回错误（调用方退 2）。"""
    players = doc.get("players") if isinstance(doc, dict) else doc
    if not isinstance(players, list) or not players:
        return [], ["名单里没有 players（或不是列表）——名单是每场一份，不能空"]
    out, errors, calls = [], [], {}
    for i, ent in enumerate(players, start=1):
        if not isinstance(ent, dict):
            errors.append(f"名单第 {i} 条不是对象")
            continue
        vals = {}
        for key in ("shirt", "shirt_zh", "call"):
            v = str(ent.get(key) or "").strip()
            if not v:
                errors.append(f"名单第 {i} 条缺 {key}——没有印字就无法对账，"
                              "没有称作就无法限定口径")
            vals[key] = v
        full = str(ent.get("full") or "").strip()
        if all(vals.values()):
            if vals["call"] in calls:
                errors.append(
                    f"称呼「{vals['call']}」重复（第 {calls[vals['call']]} 与第 {i} 条）"
                    "——同一称呼指两个人，判不出说的是谁")
            calls[vals["call"]] = i
            out.append({"shirt": vals["shirt"], "shirt_zh": vals["shirt_zh"],
                        "call": vals["call"], "full": full,
                        "pos": str(ent.get("pos") or "").strip(),
                        "team": str(ent.get("team") or "").strip()})
    return out, errors


def load_texts(windows_path: str | None, text_paths: list[str]) -> tuple[list[dict], list[str]]:
    """把待判文本收成 [{where, text}]。窗口表逐字段，文案整篇。"""
    items, errors = [], []
    if windows_path:
        try:
            doc = json.loads(Path(windows_path).read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], [f"窗口表读不动：{exc}"]
        errs = cw.validate_table(doc)
        if errs:
            return [], errs
        for win in doc["windows"]:
            for field in FIELDS:
                text = str(win.get(field) or "")
                if text.strip():
                    items.append({"where": f"{win.get('key')}.{field}", "text": text})
    for p in text_paths:
        try:
            items.append({"where": p, "text": Path(p).read_text("utf-8")})
        except OSError as exc:
            errors.append(f"文案读不动：{exc}")
    return items, errors


# ---------------------------------------------------------------- 判据


def _spans(hay: str, needle: str) -> list[tuple[int, int]]:
    """大小写不敏感的命中区间（拉丁字母比中文多这一层；中文不受影响）。"""
    if not needle:
        return []
    hay_l, needle_l = hay.lower(), needle.lower()
    out, i = [], hay_l.find(needle_l)
    while i >= 0:
        out.append((i, i + len(needle_l)))
        i = hay_l.find(needle_l, i + 1)
    return out


def check_text(where: str, text: str, players: list[dict]) -> list[dict]:
    """一段文本 × 名单 → 违规清单。"""
    findings: list[dict] = []
    for p in players:
        if p["shirt_zh"] == p["call"]:
            continue  # 印字就是称呼，没有口径分歧
        allowed = _spans(text, p["full"]) if p["full"] else []
        for label, needle in (("shirt_zh", p["shirt_zh"]), ("shirt", p["shirt"])):
            for s, e in _spans(text, needle):
                if any(a <= s and e <= b for a, b in allowed):
                    continue  # 完整出现在全名里（首现给全名，合法）
                findings.append({
                    "where": where, "field": label, "hit": needle,
                    "call": p["call"], "snippet": text[max(0, s - 8):e + 8],
                    "why": f"念了球衣印字「{needle}」；本片口径是「{p['call']}」"
                           + (f"（首现可用全名「{p['full']}」）" if p["full"] else ""),
                })
    return findings


def check_roster(players: list[dict], items: list[dict]) -> dict:
    findings: list[dict] = []
    for it in items:
        findings.extend(check_text(it["where"], it["text"], players))
    return {"items": len(items), "players": len(players),
            "fail": len(findings), "findings": findings, "pass": not findings}


# ---------------------------------------------------------------- 反向验证


def selftest() -> int:
    bad = 0

    def case(name: str, ok: bool, detail: object = "") -> None:
        nonlocal bad
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
        if not ok:
            bad += 1

    hakimi = {"shirt": "HAKIMI", "shirt_zh": "哈基米", "call": "阿什拉夫",
              "full": "阿什拉夫·哈基米", "pos": "右后卫", "team": "巴黎圣日耳曼"}
    mbappe = {"shirt": "MBAPPÉ", "shirt_zh": "姆巴佩", "call": "姆巴佩",
              "full": "", "pos": "前锋", "team": "皇家马德里"}
    roster = [hakimi, mbappe]

    res = check_roster(roster, [{"where": "w05.say",
                                "text": "阿什拉夫右路起球到后点"}])
    case("称呼合规 → PASS", res["pass"], f"fail={res['fail']}")

    res = check_roster(roster, [{"where": "w05.say",
                                "text": "哈基米右路起球到后点"}])
    case("念印字音译 → FAIL", not res["pass"]
         and res["findings"][0]["call"] == "阿什拉夫",
         res["findings"][0]["why"] if res["findings"] else "未报")

    res = check_roster(roster, [{"where": "w05.say",
                                "text": "阿什拉夫·哈基米右路起球"}])
    case("首现全名含印字音译 → 合法", res["pass"], f"fail={res['fail']}")

    res = check_roster(roster, [{"where": "w05.title", "text": "第4分钟 · HAKIMI"}])
    case("字幕卡念拉丁印字 → FAIL", not res["pass"]
         and res["findings"][0]["field"] == "shirt")

    res = check_roster(roster, [{"where": "w06.say", "text": "姆巴佩推射破门"}])
    case("印字即称呼（姆巴佩）不误杀", res["pass"], f"fail={res['fail']}")

    res = check_roster(roster, [{"where": "publish/douyin.md",
                                 "text": "哈基米传射，巴黎 5-1"}])
    case("发布文案也扫", not res["pass"] and res["findings"][0]["where"].endswith(".md"))

    _, errs = load_roster({"players": [{"shirt": "HAKIMI", "shirt_zh": "哈基米"}]})
    case("缺 call = 输入错误", bool(errs), errs[:1])
    _, errs = load_roster({"players": [dict(hakimi), dict(hakimi)]})
    case("称呼重复 = 输入错误", bool(errs), errs[:1])
    _, errs = load_roster({"players": []})
    case("空名单 = 输入错误", bool(errs), errs[:1])

    # 真实路径：窗口表落盘 → CLI 读回 → 判决（自检只测内存对象等于没测）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        wp, rp = Path(td) / "w.json", Path(td) / "r.json"
        wp.write_text(json.dumps({"windows": [
            {"key": "w1", "kind": "live", "visible": "event", "t0": 1, "t1": 5,
             "see": "画面", "title": "第4分钟 · 阿什拉夫破门",
             "say": "哈基米头球破门", "stat": "1-0"}]}, ensure_ascii=False), "utf-8")
        rp.write_text(json.dumps({"players": [hakimi]}, ensure_ascii=False), "utf-8")
        import subprocess
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--roster",
                            str(rp), "--windows", str(wp)],
                           capture_output=True, text=True)
        case("CLI 真路径：落盘 → 读回 → FAIL 退出码 1", r.returncode == 1,
             (r.stdout or r.stderr).strip().splitlines()[:1])
        wp.write_text(json.dumps({"windows": [
            {"key": "w1", "kind": "live", "visible": "event", "t0": 1, "t1": 5,
             "see": "画面", "title": "第4分钟 · 阿什拉夫破门",
             "say": "阿什拉夫头球破门", "stat": "1-0"}]}, ensure_ascii=False), "utf-8")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--roster",
                            str(rp), "--windows", str(wp)],
                           capture_output=True, text=True)
        case("CLI 真路径：合规 → 退出码 0", r.returncode == 0,
             (r.stdout or r.stderr).strip().splitlines()[:1])

    print()
    print(f"反向验证：{'全部通过' if not bad else f'{bad} 条不通过'}")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="球员名单名字口径判决（球衣印字 ≠ 解说称呼）")
    ap.add_argument("cmd", nargs="?", choices=["selftest"], help="只用来跑反向验证")
    ap.add_argument("--roster", help="名单 JSON（每场一份）")
    ap.add_argument("--windows", help="窗口表 JSON（扫 say / title / stat）")
    ap.add_argument("--text", nargs="*", default=[], help="额外扫的文案文件（发布描述等）")
    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()
    if not args.roster or (not args.windows and not args.text):
        print("需要 --roster 与至少一个待判面（--windows 或 --text）", file=sys.stderr)
        return 2
    try:
        rdoc = json.loads(Path(args.roster).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"名单读不动：{exc}", file=sys.stderr)
        return 2
    players, errs = load_roster(rdoc)
    items, ierrs = load_texts(args.windows, args.text)
    if errs or ierrs:
        for e in errs + ierrs:
            print(f"输入契约：{e}", file=sys.stderr)
        return 2

    res = check_roster(players, items)
    print(f"名单 {res['players']} 人 × 待判面 {res['items']} 段　违规 {res['fail']}")
    for f in res["findings"]:
        print(f"  [FAIL] {f['where']} {f['why']}　…{f['snippet']}…")
    print("结论：" + ("PASS" if res["pass"] else "FAIL"))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
