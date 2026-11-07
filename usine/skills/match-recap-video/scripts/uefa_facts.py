#!/usr/bin/env python3
"""uefa_facts.py — 按 UEFA 单场 id 取官方事实，归一成 skill 既有的 key_events 形状。

跨赛事（欧冠 / 欧联）的事实源是**赛事组织者**：UEFA 自己的数据接口。联赛站的
适配器只管国内联赛，欧战比赛必须走这里。

接口形状（2026-11-07 实测，见 references/league-fact-sources.md）：

    列表  https://match.uefa.com/v5/matches
          ?competitionId=1&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD&limit=100&offset=0
          → 数组，每项就是一场**完整比赛对象**（与单场同构）
    单场  https://match.uefa.com/v5/matches/{id}

比赛对象里本脚本要用的字段：

    id / status（FINISHED）/ kickOffTime.date + kickOffTime.dateTime（UTC）
    competition.code（UCL…）/ competition.metaData.name（**字符串**，不是对象）
    matchday.name（MD4）/ matchday.longName（Matchday 4）
    homeTeam/awayTeam：id / internationalName / teamCode / translations.displayName.ZH
    score.total.{home,away}（score.regular 是常规时间比分）
    matchAttendance / stadium.translations.name / referees[].role + person.translations.name
    playerEvents：**对象**，子键随场次变化（见下）

`playerEvents` 的子键不是固定的：2026-11-07 实测这一周 18 场欧冠里出现过
`scorers` / `redCards` / `penaltiesMissed`，没有换人、没有黄牌、没有 VAR；
0-0 的那场（2049611）整个 `playerEvents` 是 null。**没出现过的子键不许猜**——
本脚本只认已实测的映射，没见过的子键原样记进 `notes.unmapped_event_groups`，
不静默丢弃。

用法：
    python3 scripts/uefa_facts.py --match-id 2049607              # 打印 fact pack
    python3 scripts/uefa_facts.py --match-id 2049607 --out pack.json
    python3 scripts/uefa_facts.py --selftest                      # 离线回归（不联网）

退出码：0 = 解析成功（且至少解析出 1 条关键事件）；1 = 抓取失败 / 解析出 0 条事件
        （fail-closed：页面结构变了就不许冒充已解析）；2 = 参数坏了。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = ROOT / "assets" / "fixtures"

sys.path.insert(0, str(HERE))
from resolve_match import _event  # noqa: E402 —— 复用事件构造器，保证 key_events 形状一致

UEFA_BASE = "https://match.uefa.com/v5/matches"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# skill 的事件轴（见 SKILL.md「事实源纪律」）：缺哪条要在 gaps 里说明白
KEY_KINDS = ("goal", "substitution", "card", "var", "penalty", "whistle")

# 已实测的 playerEvents 子键 → 事件 kind。**没在这里的子键不许猜**：
# 未识别的子键进 notes.unmapped_event_groups（不静默丢）。
GROUP_KIND = {
    "scorers": "goal",
    "redCards": "card",
    "yellowCards": "card",
    "substitutions": "substitution",
    "penaltiesMissed": "penalty",
}


class UefaError(RuntimeError):
    """抓取 / 解析失败——必须带原始证据，不许兜底成默认值。"""


# ---------------------------------------------------------------- 抓取


def fetch_json(url: str, timeout: int = 30):
    """抓 UEFA JSON 接口。失败带原始错误往外抛（纪律 19：不静默兜底）。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise UefaError(f"UEFA 接口返回 HTTP {exc.code}：{url}") from exc
    except Exception as exc:  # noqa: BLE001 — 失败必须带原因
        raise UefaError(f"UEFA 接口抓取失败：{url}（{exc}）") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise UefaError(f"UEFA 接口返回的不是 JSON：{url}（{exc}）") from exc


def match_url(match_id: str) -> str:
    return f"{UEFA_BASE}/{match_id}"


def fetch_match(match_id: str) -> dict:
    data = fetch_json(match_url(match_id))
    if not isinstance(data, dict):
        raise UefaError(f"UEFA 单场接口返回的不是对象：{match_url(match_id)}")
    return data


# ---------------------------------------------------------------- 取字段


def _zh(container: dict | None, *path: str) -> str | None:
    """取 translations 里的中文名：translations.displayName.ZH 这类路径。"""
    node: object = container or {}
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) else None


def team_side(match: dict, side: str) -> dict:
    raw = match.get(side) or {}
    return {
        "id": raw.get("id"),
        "name": raw.get("internationalName"),
        "name_zh": _zh(raw, "translations", "displayName", "ZH"),
        "team_code": raw.get("teamCode"),
    }


def _event_minute(item: dict) -> int | None:
    t = (item or {}).get("time") or {}
    m = t.get("minute")
    return int(m) if isinstance(m, (int, float)) else None


def _event_second(item: dict) -> int | None:
    t = (item or {}).get("time") or {}
    s = t.get("second")
    return int(s) if isinstance(s, (int, float)) else None


def _player_fields(item: dict) -> dict:
    p = (item or {}).get("player") or {}
    return {
        "player": p.get("internationalName"),
        "player_zh": _zh(p, "translations", "name", "ZH"),
        "shirt": p.get("clubShirtName"),
        "jersey": p.get("clubJerseyNumber"),
    }


def _side_of(match: dict, team_id: str | None) -> tuple[str | None, str | None]:
    """事件归属哪一方：按 event.teamId 对上 homeTeam.id / awayTeam.id。

    对不上就返回 (None, None)——**不许猜**（teamId 对不上通常是球员转会期
    的边界数据，宁可留空让解说用位置称呼）。"""
    home, away = team_side(match, "homeTeam"), team_side(match, "awayTeam")
    if team_id and home.get("id") and team_id == home.get("id"):
        return home.get("name"), home.get("name_zh")
    if team_id and away.get("id") and team_id == away.get("id"):
        return away.get("name"), away.get("name_zh")
    return None, None


def _scorer_kind(item: dict) -> tuple[str, dict]:
    """scorers[] → (kind, 附加字段)。goalType 实测有 SCORED / OWN。"""
    gt = str(item.get("goalType") or "").upper()
    if gt == "OWN":
        return "goal", {"own_goal": True, "goal_type": gt}
    if gt == "PENALTY":
        return "penalty", {"goal_type": gt}
    return "goal", {"goal_type": gt} if gt else {}


def normalize_events(match: dict, source: str) -> tuple[list[dict], list[str], list[str]]:
    """playerEvents → key_events 形状。返回 (events, unmapped_groups, notes)。

    events 每条都是 skill 既有形状：{minute, added, clock, kind, text, ...}，
    kind ∈ goal/substitution/card/var/penalty/whistle，另有 player / team / source。
    """
    pe = match.get("playerEvents")
    events: list[dict] = []
    unmapped: list[str] = []
    notes: list[str] = []

    if pe is None:
        notes.append("playerEvents 为 null（本场接口没有给事件）——可能是 0-0 或接口未填充。")
        return events, unmapped, notes
    if not isinstance(pe, dict):
        raise UefaError(f"playerEvents 不是对象（是 {type(pe).__name__}）：接口结构变了")

    for group, items in pe.items():
        if not isinstance(items, list):
            notes.append(f"playerEvents.{group} 不是数组，原样带过（未解析）。")
            continue
        kind = GROUP_KIND.get(group)
        if kind is None:
            unmapped.append(group)
            continue
        for item in items:
            minute = _event_minute(item)
            if minute is None:
                continue
            team, team_zh = _side_of(match, item.get("teamId"))
            fields = _player_fields(item)
            if group == "scorers":
                ev_kind, extra = _scorer_kind(item)
            elif group == "redCards":
                ev_kind, extra = "card", {"card": "red"}
            elif group == "yellowCards":
                ev_kind, extra = "card", {"card": "yellow"}
            elif group == "penaltiesMissed":
                ev_kind, extra = "penalty", {"outcome": "missed"}
            else:  # substitutions
                ev_kind, extra = "substitution", {}
            label = {"goal": "进球", "penalty": "点球", "card": "红牌",
                     "substitution": "换人"}[ev_kind]
            who = fields.get("player_zh") or fields.get("player") or "球员"
            side = team_zh or team or ""
            text = f"{label} {who}" + (f"（{side}）" if side else "")
            ev = _event(minute, 0, ev_kind, text, **fields, team=team,
                        team_zh=team_zh, source=source, team_id=item.get("teamId"), **extra)
            second = _event_second(item)
            if second is not None:
                ev["second"] = second
            if item.get("phase"):
                ev["period"] = item["phase"]
            events.append(ev)

    events.sort(key=lambda e: (e["minute"], e.get("added", 0)))
    if unmapped:
        notes.append("playerEvents 里出现未识别的子键：" + "、".join(sorted(unmapped))
                     + "——本脚本只认已实测的映射，其余原样报出，不静默丢弃。")
    return events, unmapped, notes


def derive_score_after(match: dict, events: list[dict]) -> None:
    """给进球类事件补 `score_after`（**派生值**：按事件时间顺序累加）。

    乌龙球（goal_type=OWN）记在对方名下——这是规则，不是猜测；其余按 event.teamId。
    """
    home = team_side(match, "homeTeam")
    away = team_side(match, "awayTeam")
    h, a = 0, 0
    for ev in events:
        if ev.get("kind") not in ("goal", "penalty"):
            continue
        if ev.get("outcome") == "missed":
            continue  # 点球未中不是进球，不进比分
        own = bool(ev.get("own_goal"))
        tid = ev.get("team_id")
        if own:
            # 乌龙球记在对方名下（规则，不是猜测）；team_id 对不上就不派生比分
            if tid and tid == home.get("id"):
                a += 1
            elif tid and tid == away.get("id"):
                h += 1
            else:
                continue
        else:
            if ev.get("team") == home.get("name"):
                h += 1
            elif ev.get("team") == away.get("name"):
                a += 1
            else:
                continue
        ev["score_after"] = {"home": h, "away": a}
        ev["score_after_derived"] = True


def build_fact_pack(match: dict, source: str) -> dict:
    """单场响应 → fact pack（字段口径与 resolve_match 的 fact pack 对齐）。"""
    events, unmapped, notes = normalize_events(match, source)
    derive_score_after(match, events)

    score = match.get("score") or {}
    total = score.get("total") or {}
    regular = score.get("regular") or {}
    md = match.get("matchday") or {}
    comp = match.get("competition") or {}
    kick = match.get("kickOffTime") or {}
    stadium = match.get("stadium") or {}
    status = str(match.get("status") or "")

    pack = {
        "source": source,
        "match_id": match.get("id"),
        "competition": {
            "id": comp.get("id"),
            "code": comp.get("code"),
            "name": (comp.get("metaData") or {}).get("name"),
            "phase": match.get("competitionPhase"),
        },
        "matchday": {"name": md.get("name"), "long_name": md.get("longName")},
        "kickoff": {"date": kick.get("date"), "date_time": kick.get("dateTime"),
                    "utc_offset_hours": kick.get("utcOffsetInHours")},
        "status": status,
        "finished": status.startswith("FINISHED"),
        "score": {"home": total.get("home"), "away": total.get("away"),
                  "regular": {"home": regular.get("home"), "away": regular.get("away")}},
        "teams": {"home": team_side(match, "homeTeam"), "away": team_side(match, "awayTeam")},
        "venue": {
            "name": _zh(stadium, "translations", "name", "EN"),
            "name_zh": _zh(stadium, "translations", "name", "ZH"),
            "sponsor_name": _zh(stadium, "translations", "sponsorName", "EN"),
            "sponsor_name_zh": _zh(stadium, "translations", "sponsorName", "ZH"),
            "capacity": stadium.get("capacity"),
        },
        "attendance": match.get("matchAttendance"),
        "referees": [
            {"role": r.get("role"),
             "name": _zh(r, "person", "translations", "name", "EN"),
             "name_zh": _zh(r, "person", "translations", "name", "ZH")}
            for r in (match.get("referees") or [])
        ],
        "key_events": events,
        "event_counts": {k: sum(1 for e in events if e.get("kind") == k) for k in KEY_KINDS},
        "gaps": _gaps(match, events),
        "notes": notes + ([f"unmapped_event_groups: {', '.join(sorted(unmapped))}"]
                          if unmapped else []),
    }
    return pack


def _gaps(match: dict, events: list[dict]) -> list[str]:
    """这个接口**没给**的东西，必须写明（不许拿二手数据悄悄补齐）。"""
    gaps: list[str] = []
    kinds = {e.get("kind") for e in events}
    if not (kinds & {"substitution"}):
        gaps.append("本接口的 playerEvents 不含换人——解说里不要编换人，"
                    "换人要另找官方比赛页 / 文字直播面。")
    if not (kinds & {"card"}):
        gaps.append("本场 playerEvents 不含牌（黄牌/红牌）——牌轴在本接口上**做不到**，"
                    "要显式说做不到。")
    if not (kinds & {"var"}):
        gaps.append("本接口不含 VAR 判决——VAR 轴在本接口上**做不到**。")
    if not any((match.get(k) or {}).get("lineup") for k in ("lineups", "homeLineup", "awayLineup")):
        gaps.append("接口不给阵容 / 阵型（只有 lineupStatus 标记）——阵容轴要另找面。")
    if not any(e.get("assist") for e in events):
        gaps.append("进球事件里没有助攻字段——助攻轴要另找面。")
    return gaps


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """离线回归：读本地夹具（2026-11-07 实抓响应裁剪版），不联网。"""
    checks: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        checks.append((label, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")

    fixture = FIXTURES / "pages" / "uefa-match-2049607.json"
    if not fixture.exists():
        check("夹具存在", False, str(fixture))
        print()
        print("自检：0/1 通过")
        return 1
    match = json.loads(fixture.read_text(encoding="utf-8"))
    src = match_url("2049607")
    pack = build_fact_pack(match, src)

    check("比赛 id / 状态 / 开球日",
          pack["match_id"] == "2049607" and pack["status"] == "FINISHED"
          and pack["kickoff"]["date"] == "2026-11-03",
          f"{pack['match_id']} {pack['status']} {pack['kickoff']['date']}")
    check("赛事 = 欧冠 MD4",
          pack["competition"]["code"] == "UCL" and pack["matchday"]["name"] == "MD4",
          f"{pack['competition']['code']} {pack['matchday']['name']}")
    check("比分 3-0", pack["score"]["home"] == 3 and pack["score"]["away"] == 0,
          f"{pack['score']['home']}-{pack['score']['away']}")
    check("上座 / 球场可读",
          pack["attendance"] == 52662 and pack["venue"]["sponsor_name"] == "Spotify Camp Nou",
          f"{pack['attendance']} {pack['venue']['sponsor_name']}")
    check("主裁可读（REFEREE 角色）",
          any(r["role"] == "REFEREE" and r["name"] for r in pack["referees"]),
          str([r["name"] for r in pack["referees"] if r["role"] == "REFEREE"]))

    goals = [e for e in pack["key_events"] if e["kind"] == "goal"]
    check("进球 3 个", len(goals) == 3, f"{[(g['clock'], g.get('player')) for g in goals]}")
    check("进球分钟按接口读数（7/52/64）",
          [g["minute"] for g in goals] == [7, 52, 64],
          f"{[g['minute'] for g in goals]}")
    check("射手带国际名 / 中文名 / 球衣印字",
          goals and goals[0].get("player") == "Lamine Yamal"
          and goals[0].get("player_zh") == "拉明·亚马尔" and goals[0].get("shirt") == "Lamine Yamal",
          f"{goals[0].get('player')} / {goals[0].get('player_zh')} / {goals[0].get('shirt')}")
    check("进球归属主队（team / team_zh）",
          goals and goals[0].get("team") == "Barcelona" and goals[0].get("team_zh") == "巴塞罗那",
          f"{goals[0].get('team')} / {goals[0].get('team_zh')}")
    check("每个事件都带来源 URL",
          all(e.get("source") == src for e in pack["key_events"]))
    check("event_counts 按 kind 逐条计数（缺 0 不缺省）",
          pack["event_counts"] == {"goal": 3, "substitution": 0, "card": 0,
                                   "var": 0, "penalty": 0, "whistle": 0},
          str(pack["event_counts"]))
    check("派生比分（score_after）只挂在进球上",
          goals and goals[-1].get("score_after") == {"home": 3, "away": 0},
          f"{goals[-1].get('score_after') if goals else None}")
    check("接口没有的轴写进 gaps（换人 / 牌 / VAR / 阵容）",
          any("换人" in g for g in pack["gaps"]) and any("牌" in g for g in pack["gaps"])
          and any("VAR" in g for g in pack["gaps"]) and any("阵容" in g for g in pack["gaps"]),
          f"{len(pack['gaps'])} 条")

    # ---- 反向用例 ----
    red = {"id": "x", "status": "FINISHED", "kickOffTime": {"date": "2026-11-04"},
           "competition": {"code": "UCL", "metaData": {"name": "UEFA Champions League"}},
           "homeTeam": {"id": "1", "internationalName": "A", "translations": {"displayName": {"ZH": "甲"}}},
           "awayTeam": {"id": "2", "internationalName": "B", "translations": {"displayName": {"ZH": "乙"}}},
           "score": {"total": {"home": 1, "away": 0}},
           "playerEvents": {"redCards": [
               {"id": "r1", "phase": "SECOND_HALF", "teamId": "2",
                "player": {"internationalName": "John Doe", "clubShirtName": "DOE",
                           "translations": {"name": {"ZH": "约翰·多"}}},
                "time": {"minute": 77, "second": 53}}]}}
    p2 = build_fact_pack(red, "https://x")
    check("红牌归一成 kind=card / card=red",
          p2["event_counts"]["card"] == 1
          and p2["key_events"][0].get("card") == "red"
          and p2["key_events"][0]["minute"] == 77,
          str(p2["key_events"][0]))
    check("红牌归属按 teamId 对上的一方（乙）",
          p2["key_events"][0].get("team_zh") == "乙")

    pen = {"id": "y", "status": "FINISHED", "kickOffTime": {"date": "2026-11-04"},
           "competition": {"code": "UCL"},
           "homeTeam": {"id": "1", "internationalName": "A"}, "awayTeam": {"id": "2", "internationalName": "B"},
           "score": {"total": {"home": 0, "away": 0}},
           "playerEvents": {"penaltiesMissed": [
               {"id": "p1", "penaltyType": "MISSED", "teamId": "1",
                "player": {"internationalName": "K. Tripic"}, "time": {"minute": 69, "second": 25}}]}}
    p3 = build_fact_pack(pen, "https://x")
    check("点球未中归一成 kind=penalty / outcome=missed",
          p3["event_counts"]["penalty"] == 1 and p3["key_events"][0].get("outcome") == "missed",
          str(p3["key_events"][0]))
    check("点球未中不进派生比分（未进球）",
          "score_after" not in p3["key_events"][0], str(p3["key_events"][0].get("score_after")))

    unknown = {"id": "z", "status": "FINISHED", "kickOffTime": {"date": "2026-11-04"},
               "competition": {"code": "UCL"},
               "homeTeam": {"id": "1", "internationalName": "A"}, "awayTeam": {"id": "2", "internationalName": "B"},
               "score": {"total": {"home": 0, "away": 0}},
               "playerEvents": {"mysteryEvents": [{"time": {"minute": 5}}]}}
    p4 = build_fact_pack(unknown, "https://x")
    check("未识别的 playerEvents 子键不被静默丢弃",
          any("unmapped_event_groups" in n for n in p4["notes"]),
          str(p4["notes"]))
    check("未识别子键不产生假事件", p4["event_counts"]["goal"] == 0)

    empty = {"id": "w", "status": "FINISHED", "kickOffTime": {"date": "2026-11-04"},
             "competition": {"code": "UCL"},
             "homeTeam": {"id": "1", "internationalName": "A"}, "awayTeam": {"id": "2", "internationalName": "B"},
             "score": {"total": {"home": 0, "away": 0}}, "playerEvents": None}
    p5 = build_fact_pack(empty, "https://x")
    check("playerEvents 为 null 时报出来、且不冒充已解析",
          not p5["key_events"] and any("null" in n for n in p5["notes"]),
          str(p5["notes"]))

    bad = sum(1 for _, ok, _ in checks if not ok)
    print()
    print(f"自检：{len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="UEFA 单场事实源（归一成 key_events）")
    ap.add_argument("--match-id", help="UEFA 比赛 id（如 2049607）")
    ap.add_argument("--out", help="fact pack 输出路径（默认打到 stdout）")
    ap.add_argument("--selftest", action="store_true", help="离线跑夹具（不联网）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.match_id:
        ap.print_help()
        return 2

    src = match_url(args.match_id)
    try:
        match = fetch_match(args.match_id)
    except UefaError as exc:
        print(json.dumps({"resolved": False, "error": str(exc), "source": src},
                         ensure_ascii=False, indent=2))
        return 1
    pack = build_fact_pack(match, src)
    if not pack["key_events"]:
        # fail-closed：足球比赛至少有进球或牌，0 条 = 接口结构变了，不是「没有事件」
        pack["resolved"] = False
        pack["reason"] = ("UEFA 单场接口解析出 0 条关键事件——足球比赛至少有进球或牌，"
                          "解析器多半没跟上接口结构；需要人工看原始响应（url 见 source）。")
    else:
        pack["resolved"] = True
    text = json.dumps(pack, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"fact pack → {args.out}")
    else:
        print(text)
    return 0 if pack.get("resolved") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
