#!/usr/bin/env python3
"""resolve_week.py — 「本周哪些注册队有已完赛比赛」的**周口径**解析器。

`resolve_match.py` 回答的是「当前赛季最新一场」（不限时间窗口，取赛季内最近的一场
已完赛）。产品口径里的「本周」是另一件事：**asof 所在的自然周（周一~周日）**。
两者的答案不一样——本轮实跑就是例证：11-03/11-04 的欧冠 MD4 在「赛季最新」口径下
被联赛场次盖住，在「本周」口径下却是这几支队本周唯一的已完赛比赛。

一条命令给出：本周（周一起止）内，每支注册队有几场已完赛、候选是哪几场、选取依据是什么。

数据面（三条，按可靠性排序）：

1. **UEFA 官方接口**（跨赛事：欧冠 / 欧联的事实源是赛事组织者）：
   `https://match.uefa.com/v5/matches?competitionId=1&fromDate=…&toDate=…&limit=100&offset=0`
   —— 本轮实测只有 `competitionId=1`（欧冠）返回数据；欧联（UEL）的比赛 id 在本环境
   **无法通过列表接口发现**（见 assets/leagues.json 的 `uel` 条目），所以欧联场次只能
   靠俱乐部官网赛程面 / 官方频道视频标题反查——本脚本会把这写成缺口，不假装能列全。
2. **各队既有联赛适配器**（复用 resolve_match 的赛程面解析器，不重写一套）。
3. **俱乐部官网赛程面兜底**（teams.json 的 `club_site.fixtures_url`）：
   psg.fr 的月度赛程页（`parse_psg_fixtures`）与 acmilan.com 的「Next Games」块
   （`parse_next_games_block`）。**这一面只列未赛场次**——能回答「本周有没有比赛」，
   答不了「本周这场已完赛吗」。

选取口径：**本周内已完赛的场次，按开球时间取最晚的一场**（同周更早开球的记进
`alternatives`，并写明为什么没选它）。本周没有已完赛 = 明确报「本周无已完赛」，
不拿未赛场次冒充。

用法：
    python3 scripts/resolve_week.py --asof 2026-11-07            # 默认阵容 5 队
    python3 scripts/resolve_week.py --asof 2026-11-07 --teams barcelona,milan
    python3 scripts/resolve_week.py --asof 2026-11-07 --out week.json
    python3 scripts/resolve_week.py --selftest                   # 离线回归（不联网）

退出码：0 = 报告产出，且每支目标队都有结论（有已完赛候选 / 明确「本周无已完赛」）；
        1 = 报告产出，但有队伍**无法判定**（数据面缺口，例如欧联 id 发现路径缺失）——
            报告仍然产出并写明缺口来源，退出码只是提醒人手动补；
        2 = 参数 / 环境坏了。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = ROOT / "assets" / "fixtures"

sys.path.insert(0, str(HERE))
from resolve_match import (  # noqa: E402 —— 复用既有赛程面解析器，不重写一套
    ResolveError,
    _fixtures_urls,
    _norm_name,
    load_registry,
    norm_date,
    parse_fixtures,
    parse_psg_fixtures,
    scrape,
)
from uefa_facts import UEFA_BASE, UefaError, fetch_json  # noqa: E402


def load_registry_full() -> tuple[dict, dict, dict]:
    """读注册表全量：teams.json 的「顶层 + teams 子表」+ leagues.json 的 leagues 子表。

    `resolve_match.load_registry()` 只返回 teams 子表（那是解析器要的形状，**不改**），
    默认阵容在 teams.json 的顶层，所以这里自己读一次。"""
    with (ROOT / "assets" / "teams.json").open(encoding="utf-8") as fh:
        raw = json.load(fh)
    with (ROOT / "assets" / "leagues.json").open(encoding="utf-8") as fh:
        leagues = json.load(fh)
    return raw.get("teams", {}), raw.get("default_lineup", {}), leagues.get("leagues", {})

# ---------------------------------------------------------------- 周窗口


def week_window(asof: date) -> tuple[date, date]:
    """asof 所在的自然周：周一 ~ 周日（周一是一周的第一天）。"""
    start = asof - timedelta(days=asof.weekday())
    return start, start + timedelta(days=6)


def iso_week_label(start: date) -> str:
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


# ---------------------------------------------------------------- 队名匹配


def team_aliases(team: dict) -> set[str]:
    """这支队在各数据源里可能出现的**拉丁写法**（归一后）。

    `name_aliases` 是注册表里显式登记的官方名变体（如 UEFA 侧的 "B. Dortmund"）——
    跨源匹配靠它，不靠猜。中文名不走归一（归一只保留字母数字，中文会被抹掉），
    中文按**原样相等**匹配，见 side_for。"""
    names = [team.get("en"), team.get("club_slug")]
    names += list(team.get("name_aliases") or [])
    return {_norm_name(n) for n in names if n}


def _same_name(a: str | None, b: str | None) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    return bool(na) and na == nb


def side_for(candidate: dict, team: dict) -> str | None:
    """这支队在候选里是主队还是客队；认不出来返回 None（不猜）。

    三条判据（任一命中即可）：注册表里的 UEFA 队伍 id / 拉丁名归一后相等 /
    中文名原样相等。"""
    tid = team.get("uefa_team_id")
    if tid and candidate.get("home_id") and tid == candidate["home_id"]:
        return "home"
    if tid and candidate.get("away_id") and tid == candidate["away_id"]:
        return "away"
    aliases = team_aliases(team)
    zh = team.get("zh")
    for side in ("home", "away"):
        if _norm_name(candidate.get(side)) in aliases:
            return side
        if zh and candidate.get(f"{side}_zh") and candidate[f"{side}_zh"] == zh:
            return side
    return None


def filter_team_candidates(cands: list[dict], team: dict) -> list[dict]:
    """候选里属于这支队的那几场（认不出主客的不进——fail-closed）。"""
    return [c for c in cands if side_for(c, team)]


# ---------------------------------------------------------------- UEFA 适配器


def uefa_list_url(start: date, end: date, competition_id: str = "1") -> str:
    return (f"{UEFA_BASE}?competitionId={competition_id}"
            f"&fromDate={start.isoformat()}&toDate={end.isoformat()}"
            f"&limit=100&offset=0")


def uefa_matches_to_candidates(matches: list[dict], source_url: str) -> list[dict]:
    """UEFA 列表响应 → 统一候选形状。"""
    out: list[dict] = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        score = (m.get("score") or {}).get("total") or {}
        comp = m.get("competition") or {}
        md = m.get("matchday") or {}
        kick = m.get("kickOffTime") or {}
        status = str(m.get("status") or "")
        home = m.get("homeTeam") or {}
        away = m.get("awayTeam") or {}
        out.append({
            "date": kick.get("date"),
            "kickoff": kick.get("dateTime"),
            "home": home.get("internationalName"),
            "home_zh": ((home.get("translations") or {}).get("displayName") or {}).get("ZH"),
            "home_id": home.get("id"),
            "away": away.get("internationalName"),
            "away_zh": ((away.get("translations") or {}).get("displayName") or {}).get("ZH"),
            "away_id": away.get("id"),
            "score": (f"{score.get('home')}-{score.get('away')}"
                      if score.get("home") is not None and score.get("away") is not None
                      else None),
            "competition": (comp.get("metaData") or {}).get("name") or comp.get("code"),
            "competition_code": comp.get("code"),
            "round": md.get("name"),
            "finished": status.startswith("FINISHED"),
            "status": status,
            "match_id": m.get("id"),
            "url": f"https://www.uefa.com/uefachampionsleague/match/{m.get('id')}/",
            "venue": ((m.get("stadium") or {}).get("translations") or {})
            .get("sponsorName", {}).get("EN"),
            "source_kind": "uefa_list",
            "source_url": source_url,
        })
    return out


def gather_uefa_candidates(start: date, end: date) -> tuple[list[dict], list[dict]]:
    """欧冠列表接口（每个 run 只抓一次，全队共用）。"""
    url = uefa_list_url(start, end)
    report = {"kind": "uefa_list", "url": url}
    try:
        data = fetch_json(url)
    except UefaError as exc:
        report.update({"ok": False, "error": str(exc)})
        return [], [report]
    if not isinstance(data, list):
        report.update({"ok": False, "error": "UEFA 列表接口返回的不是数组"})
        return [], [report]
    cands = uefa_matches_to_candidates(data, url)
    report.update({"ok": True, "candidates": len(cands),
                   "note": "接口只对 competitionId=1（欧冠）有数据；欧联场次不在这里"})
    return cands, [report]


# ---------------------------------------------------------------- 联赛适配器


def _league_candidates(raw: list[dict], source_url: str) -> list[dict]:
    """resolve_match 的赛程候选 → 统一候选形状。"""
    out: list[dict] = []
    for c in raw:
        out.append({
            "date": c.get("date"),
            "kickoff": None,
            "home": c.get("home"),
            "home_zh": None,
            "away": c.get("away"),
            "away_zh": None,
            "score": c.get("score"),
            "competition": c.get("competition"),
            "competition_code": None,
            "round": c.get("round"),
            "finished": bool(c.get("score")),
            "status": None,
            "match_id": c.get("match_id"),
            "url": c.get("url"),
            "venue": None,
            "source_kind": "league_fixtures",
            "source_url": source_url,
        })
    return out


def gather_league_candidates(lg_key: str, lg: dict, team: dict,
                             asof: date) -> tuple[list[dict], list[dict]]:
    """本队联赛的既有赛程面（复用 resolve_match 的面与解析器）。"""
    cands: list[dict] = []
    reports: list[dict] = []
    for url in _fixtures_urls(lg_key, lg, team, asof):
        report = {"kind": "league_fixtures", "url": url}
        try:
            md = scrape(url, Path(tempfile_dir()) / "fixtures.md")
        except ResolveError as exc:
            report.update({"ok": False, "error": str(exc)})
            reports.append(report)
            continue
        if "psg.fr" in url:
            raw = parse_psg_fixtures(md, asof)
        else:
            span = 80
            if lg_key == "premierleague":
                span = 25 if "/matches/premier-league/" in url else 8
            raw = parse_fixtures(md, lg_key, asof, date_span=span)
        if not raw:
            report.update({"ok": False, "error": "这个面没解析出任何候选场次（页面结构可能变了）"})
        else:
            got = _league_candidates(raw, url)
            cands.extend(got)
            report.update({"ok": True, "candidates": len(got)})
        reports.append(report)
    return cands, reports


def tempfile_dir() -> str:
    import tempfile
    return tempfile.mkdtemp(prefix="resolve-week-")


# ---------------------------------------------------------------- 俱乐部官网兜底

SHORT_DATE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+"
    r"(?:([A-Za-z]{3,9})\.?\s+)?(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s+(\d{4}))?$", re.I)
VS_LINE = re.compile(r"^(?P<home>[^|/]+?)\s+vs\.?\s+(?P<away>[^|/]+?)$", re.I)
KICKOFF = re.compile(r"^\d{1,2}:\d{2}$")
MONTH_ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11,
              "dec": 12}


def parse_short_date(text: str, asof: date) -> str | None:
    """「Sun. Nov 8th」/「8th November 2026」→ YYYY-MM-DD。认不出就 None。"""
    m = SHORT_DATE.match(text.strip())
    if not m:
        return norm_date(text, asof)
    month_raw, day_raw, year_raw = m.group(1), m.group(2), m.group(3)
    if not month_raw:
        return None
    month = MONTH_ABBR.get(month_raw[:3].lower())
    if not month:
        return None
    year = int(year_raw) if year_raw else None
    if year is None:
        # 年份从 asof 推：取离 asof 最近的同月（跨年时天然正确）
        best, best_gap = asof.year, None
        for y in (asof.year - 1, asof.year, asof.year + 1):
            gap = abs((date(y, month, 1) - asof).days)
            if best_gap is None or gap < best_gap:
                best, best_gap = y, gap
        year = best
    try:
        return date(year, month, int(day_raw)).isoformat()
    except ValueError:
        return None


def parse_next_games_block(markdown: str, asof: date) -> list[dict]:
    """俱乐部官网「Next Games」块 → 候选（**未赛场次**，finished=False）。

    口径：一条「A vs B」行是一场；它上下的邻近行里找日期 / 场地 / 赛事 / 开球时间。
    这是**赛程面**：只列未赛场次——已完赛不归它管（写进 gaps，不冒充）。
    """
    markdown = re.sub(r"<!--.*?-->", " ", markdown, flags=re.S)
    lines = [l.strip() for l in markdown.splitlines()]
    cands: list[dict] = []
    for i, line in enumerate(lines):
        if not line or line.startswith("<!--"):
            continue
        m = VS_LINE.match(line)
        if not m:
            continue
        home, away = m.group("home").strip(), m.group("away").strip()
        before = [l for l in lines[max(0, i - 8):i] if l and not l.startswith("<!--")]
        after = [l for l in lines[i + 1:i + 7] if l and not l.startswith("<!--")]
        dt = None
        venue = None
        comp = None
        side = None
        for l in before + after:
            if dt is None:
                cand_date = parse_short_date(l, asof)
                if cand_date:
                    dt = cand_date
                    continue
            if l in ("HOME", "AWAY"):
                side = l
            elif venue is None and re.search(r"\b(Stadio|Stadium|Arena|Arenas)\b", l):
                venue = l
            elif comp is None and (re.search(r"Matchday\s*\d+", l) or re.search(r"\bMD\s*\d+", l)):
                comp = l
        kickoff = next((l for l in after if KICKOFF.match(l)), None)
        cands.append({
            "date": dt,
            "kickoff": kickoff,
            "home": home,
            "home_zh": None,
            "away": away,
            "away_zh": None,
            "score": None,
            "competition": comp,
            "competition_code": None,
            "round": comp,
            "finished": False,
            "status": "SCHEDULED",
            "match_id": None,
            "url": None,
            "venue": venue,
            "source_kind": "club_site",
            "source_url": None,
            "subject_side": side,
        })
    return cands


def gather_club_site_candidates(team: dict, asof: date) -> tuple[list[dict], list[dict]]:
    """俱乐部官网赛程面兜底（teams.json 的 club_site）。"""
    site = team.get("club_site") or {}
    tpl = site.get("fixtures_url")
    if not tpl:
        return [], []
    reports: list[dict] = []
    cands: list[dict] = []
    if site.get("parser") == "psg_monthly":
        from resolve_match import _recent_month_tags
        lang = site.get("lang", "en")
        for tag in _recent_month_tags(asof):
            url = tpl.format(lang=lang, period=tag)
            report = {"kind": "club_site", "url": url}
            try:
                md = scrape(url, Path(tempfile_dir()) / "club.md")
            except ResolveError as exc:
                report.update({"ok": False, "error": str(exc)})
                reports.append(report)
                continue
            raw = parse_psg_fixtures(md, asof)
            got = _league_candidates(raw, url)
            got = [dict(c, source_kind="club_site") for c in got]
            cands.extend(got)
            report.update({"ok": bool(raw), "candidates": len(got)})
            reports.append(report)
        return cands, reports

    url = tpl.format(lang=site.get("lang", "en"))
    report = {"kind": "club_site", "url": url}
    try:
        md = scrape(url, Path(tempfile_dir()) / "club.md")
    except ResolveError as exc:
        report.update({"ok": False, "error": str(exc)})
        return [], [report]
    raw = parse_next_games_block(md, asof)
    for c in raw:
        c["source_url"] = url
    cands.extend(raw)
    report.update({"ok": bool(raw), "candidates": len(raw),
                   "note": "赛程面：只列未赛场次，已完赛不归它管"})
    reports.append(report)
    return cands, reports


# ---------------------------------------------------------------- 组装报告


def _in_window(cand: dict, start: date, end: date) -> bool:
    d = cand.get("date")
    if not d:
        return False
    return start.isoformat() <= d <= end.isoformat()


def _sort_key(cand: dict) -> tuple:
    return (cand.get("kickoff") or cand.get("date") or "", cand.get("match_id") or "")


def assemble_report(asof: date, start: date, end: date, per_team: dict,
                     teams: dict, leagues: dict, default_lineup: dict) -> dict:
    """把各队候选装成本周报告（**纯函数**：不联网，可离线自检）。"""
    report: dict = {
        "asof": asof.isoformat(),
        "week": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "iso_week": iso_week_label(start),
            "weekday_start": "Monday",
            "weekday_end": "Sunday",
        },
        "scope": "finished_matches_in_week",
        "default_lineup": default_lineup,
        "teams": {},
    }
    for key, raw in per_team.items():
        team = teams.get(key, {})
        cands = [c for c in raw.get("candidates", []) if _in_window(c, start, end)]
        finished = [c for c in cands if c.get("finished")]
        scheduled = [c for c in cands if not c.get("finished")]
        selection = None
        alternatives: list[dict] = []
        if finished:
            ordered = sorted(finished, key=_sort_key)
            selection = ordered[-1]
            alternatives = [
                {"match_id": c.get("match_id"), "date": c.get("date"),
                 "kickoff": c.get("kickoff"), "score": c.get("score"),
                 "competition": c.get("competition"),
                 "why_not": "同周更早开球"}
                for c in ordered[:-1]
            ]
        basis = _selection_basis(selection, finished, scheduled, raw.get("gaps") or [])
        status = "found" if selection else (
            "none_this_week" if (cands or raw.get("surfaces")) else "data_gap")
        if not selection and raw.get("gaps"):
            status = "data_gap"
        report["teams"][key] = {
            "team_zh": team.get("zh"),
            "league": team.get("league"),
            "status": status,
            "finished_count": len(finished),
            "scheduled_count": len(scheduled),
            "candidates": cands,
            "selection": selection,
            "selection_basis": basis,
            "alternatives": alternatives,
            "surfaces": raw.get("surfaces", []),
            "gaps": raw.get("gaps", []),
        }
    report["notes"] = [
        "本周口径 = asof 所在自然周（周一~周日）；与「当前赛季最新一场」不是一回事——"
        "后者取赛季内最近的一场（不限本周），由 resolve_match.py 出。",
        "选取依据：本周内已完赛的场次按开球时间取最晚的一场；同周更早开球的记进 alternatives。",
        "俱乐部官网赛程面只列未赛场次——它能回答「本周有没有比赛」，答不了「已完赛吗」。",
        "欧联（UEL）比赛 id 在本环境无法通过 UEFA 列表接口发现（competitionId≠1 无数据），"
        "欧联场次只能靠俱乐部官网赛程面 / 官方频道视频标题反查——本报告不假装能列全。",
    ]
    return report


def _selection_basis(selection: dict | None, finished: list[dict],
                     scheduled: list[dict], gaps: list[str]) -> str:
    if selection:
        base = (f"本周已完赛 {len(finished)} 场，按开球时间取最晚的一场："
                f"{selection.get('date')} {selection.get('competition') or ''} "
                f"{selection.get('score') or ''}（{selection.get('match_id') or selection.get('url') or ''}）")
        return base.strip()
    if finished:
        return "本周有已完赛场次但没有可排序的（缺开球时间）——需要人工核对。"
    if scheduled:
        return (f"本周候选 {len(scheduled)} 场**均未完赛**（赛程面只列未赛场次）；"
                "本周无已完赛比赛。")
    if gaps:
        return "本周无结论：数据面缺口（见 gaps）——不冒充「本周无已完赛」。"
    return "本周无已完赛比赛，且没有候选场次可供核对。"


# ---------------------------------------------------------------- 主流程


def collect(asof: date, keys: list[str], teams: dict, leagues: dict) -> dict:
    """真抓：各队候选 + 数据面报告。"""
    start, end = week_window(asof)
    uefa_cands, uefa_reports = gather_uefa_candidates(start, end)
    per_team: dict = {}
    for key in keys:
        team = teams[key]
        cands: list[dict] = []
        surfaces: list[dict] = []
        gaps: list[str] = []
        # 1) UEFA 列表（跨赛事）
        mine = [c for c in uefa_cands if side_for(c, team)]
        cands.extend(mine)
        surfaces.extend(uefa_reports)
        # 2) 本队联赛的既有适配器
        lg_key = team.get("league")
        lg = leagues.get(lg_key) or {}
        if lg.get("fact_source"):
            lg_cands, lg_reports = gather_league_candidates(lg_key, lg, team, asof)
            cands.extend(lg_cands)
            surfaces.extend(lg_reports)
            limit = lg.get("fixture_surface_limitation")
            if limit:
                gaps.append(f"{lg.get('zh')} 联赛面限制：{limit}")
        # 3) 俱乐部官网兜底
        club_cands, club_reports = gather_club_site_candidates(team, asof)
        cands.extend(club_cands)
        surfaces.extend(club_reports)
        if club_cands and not any(c.get("finished") for c in club_cands):
            gaps.append("俱乐部官网赛程面只列未赛场次：本周的场次是否已完赛，"
                        "要以联赛 / UEFA 官方接口或官方赛报页为准。")
        if not mine and not any(c.get("finished") for c in cands):
            gaps.append("UEFA 列表接口本环境只对 competitionId=1（欧冠）有数据；"
                        "该队本周若有欧联（UEL）场次，此处无法发现——"
                        "欧联 id 需另寻发现路径（俱乐部官网赛程面 / 官方频道视频标题反查）。")
        per_team[key] = {"candidates": cands, "surfaces": surfaces, "gaps": gaps}
    return per_team


def selftest() -> int:
    """离线回归：读本地夹具（不联网），验周窗口 / 队名匹配 / 选取依据 / 缺口口径。"""
    checks: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        checks.append((label, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")

    teams, default_lineup, leagues = load_registry_full()

    # 1) 周窗口 = 周一~周日
    start, end = week_window(date(2026, 11, 7))
    check("周窗口：2026-11-07 → 11-02(周一)~11-08(周日)",
          start == date(2026, 11, 2) and end == date(2026, 11, 8),
          f"{start}~{end}")
    check("ISO 周编号", iso_week_label(start) == "2026-W45", iso_week_label(start))
    s2, e2 = week_window(date(2026, 11, 2))
    check("周一当天的周窗口起点是自己",
          s2 == date(2026, 11, 2) and e2 == date(2026, 11, 8), f"{s2}~{e2}")

    # 2) UEFA 列表夹具
    list_fix = FIXTURES / "pages" / "uefa-ucl-md4-list.json"
    if not list_fix.exists():
        check("UEFA 列表夹具存在", False, str(list_fix))
        print()
        print("自检：0/1 通过")
        return 1
    matches = json.loads(list_fix.read_text(encoding="utf-8"))
    cands = uefa_matches_to_candidates(matches, "https://match.uefa.com/v5/matches?...")
    check("列表夹具解析出 18 场", len(cands) == 18, f"{len(cands)} 场")
    barca = next((c for c in cands if c["match_id"] == "2049607"), None)
    check("巴萨那场读数正确（3-0 / 11-03 / MD4）",
          bool(barca) and barca["score"] == "3-0" and barca["date"] == "2026-11-03"
          and barca["round"] == "MD4" and barca["finished"],
          str(barca)[:200])
    check("UEFA 候选带官方比赛页 URL",
          bool(barca) and barca["url"] == "https://www.uefa.com/uefachampionsleague/match/2049607/",
          barca["url"] if barca else "")

    # 3) 队名 / id 匹配
    check("巴萨按 uefa_team_id 认得出（主队）", side_for(barca, teams["barcelona"]) == "home",
          str(side_for(barca, teams["barcelona"])))
    check("利物浦按 id 认得出（客队）",
          side_for(next(c for c in cands if c["match_id"] == "2049620"), teams["liverpool"]) == "away")
    check("多特蒙德按 id 认得出（主队）",
          side_for(next(c for c in cands if c["match_id"] == "2049616"), teams["dortmund"]) == "home")
    check("巴黎按 id 认得出（客队）",
          side_for(next(c for c in cands if c["match_id"] == "2049612"), teams["psg"]) == "away")
    check("AC米兰在欧冠这一周没有场次（认不出 = None，不猜）",
          side_for(barca, teams["milan"]) is None)

    # 4) 报告组装（纯函数）
    per_team = {
        "barcelona": {"candidates": filter_team_candidates(cands, teams["barcelona"]),
                      "surfaces": [{"kind": "uefa_list", "ok": True}], "gaps": []},
        "liverpool": {"candidates": filter_team_candidates(cands, teams["liverpool"]),
                      "surfaces": [], "gaps": []},
        "milan": {"candidates": [], "surfaces": [{"kind": "uefa_list", "ok": True}],
                  "gaps": ["欧联 id 发现路径缺失"]},
    }
    rep = assemble_report(date(2026, 11, 7), start, end, per_team, teams, leagues,
                          default_lineup)
    check("报告给出周起止 + ISO 周",
          rep["week"]["start"] == "2026-11-02" and rep["week"]["end"] == "2026-11-08"
          and rep["week"]["iso_week"] == "2026-W45")
    check("巴萨本周 1 场已完赛（欧冠 MD4）",
          rep["teams"]["barcelona"]["finished_count"] == 1
          and rep["teams"]["barcelona"]["selection"]["match_id"] == "2049607",
          str(rep["teams"]["barcelona"]["selection_basis"]))
    check("利物浦本周 1 场已完赛（客负 2-3）",
          rep["teams"]["liverpool"]["finished_count"] == 1
          and rep["teams"]["liverpool"]["selection"]["score"] == "3-2")
    check("选取依据写明「本周已完赛 N 场 + 取最晚开球」",
          "本周已完赛 1 场" in rep["teams"]["barcelona"]["selection_basis"]
          and "最晚" in rep["teams"]["barcelona"]["selection_basis"],
          rep["teams"]["barcelona"]["selection_basis"])
    check("无数据的队伍报 data_gap，不冒充「本周无已完赛」",
          rep["teams"]["milan"]["status"] == "data_gap"
          and "缺口" in rep["teams"]["milan"]["selection_basis"],
          rep["teams"]["milan"]["selection_basis"])
    check("报告默认阵容 = 5 大联赛各 1 队",
          set(default_lineup) == {"seriea", "laliga", "premierleague", "bundesliga", "ligue1"}
          and "inter" not in default_lineup.values(),
          str(default_lineup))

    # 5) 同周多场 → 取最晚开球，其余进 alternatives
    multi = {
        "barcelona": {
            "candidates": filter_team_candidates([
                dict(barca, match_id="A", kickoff="2026-11-02T20:00:00Z"),
                dict(barca, match_id="B", kickoff="2026-11-06T20:00:00Z"),
            ], teams["barcelona"]),
            "surfaces": [], "gaps": [],
        }
    }
    rep2 = assemble_report(date(2026, 11, 7), start, end, multi, teams, leagues, default_lineup)
    check("同周多场：取最晚开球的一场",
          rep2["teams"]["barcelona"]["selection"]["match_id"] == "B",
          str(rep2["teams"]["barcelona"]["selection"]["match_id"]))
    check("同周更早开球的那场进 alternatives 并写明原因",
          len(rep2["teams"]["barcelona"]["alternatives"]) == 1
          and rep2["teams"]["barcelona"]["alternatives"][0]["why_not"] == "同周更早开球")

    # 6) 俱乐部官网兜底：Next Games 块
    club_fix = FIXTURES / "pages" / "acmilan-schedule-next-games.md"
    if club_fix.exists():
        club = parse_next_games_block(club_fix.read_text(encoding="utf-8"), date(2026, 11, 7))
        check("俱乐部官网赛程块解析出一场", len(club) == 1, str(len(club)))
        if club:
            c = club[0]
            check("俱乐部赛程：日期 2026-11-08 / 对阵 Genoa vs AC Milan / 15:00 / MD11",
                  c["date"] == "2026-11-08" and c["home"] == "Genoa" and c["away"] == "AC Milan"
                  and c["kickoff"] == "15:00" and "Matchday 11" in (c["competition"] or ""),
                  str(c)[:220])
            check("俱乐部赛程块 = 未赛场次（finished=False）", c["finished"] is False)
            check("俱乐部赛程场次能挂到 AC米兰（按名匹配）",
                  side_for(c, teams["milan"]) in ("home", "away"),
                  str(side_for(c, teams["milan"])))

    # 7) 短日期解析
    check("短日期 'Sun. Nov 8th' → 2026-11-08",
          parse_short_date("Sun. Nov 8th", date(2026, 11, 7)) == "2026-11-08",
          str(parse_short_date("Sun. Nov 8th", date(2026, 11, 7))))

    bad = sum(1 for _, ok, _ in checks if not ok)
    print()
    print(f"自检：{len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="match-recap-video「本周已完赛」周口径解析器")
    ap.add_argument("--asof", help="基准日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--teams", help="逗号分隔的球队 key（默认 = teams.json 的 default_lineup）")
    ap.add_argument("--out", help="报告输出路径（默认打到 stdout）")
    ap.add_argument("--selftest", action="store_true", help="离线跑夹具（不联网）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    teams, default_lineup, leagues = load_registry_full()
    asof = date.fromisoformat(args.asof) if args.asof else date.today()

    if args.teams:
        keys = [k.strip() for k in args.teams.split(",") if k.strip()]
        unknown = [k for k in keys if k not in teams]
        if unknown:
            print(json.dumps({"error": f"未知球队 {unknown}；可选：{', '.join(sorted(teams))}"},
                             ensure_ascii=False, indent=2))
            return 2
    else:
        keys = sorted(set(default_lineup.values()))

    start, end = week_window(asof)
    per_team = collect(asof, keys, teams, leagues)
    report = assemble_report(asof, start, end, per_team, teams, leagues, default_lineup)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"本周报告 → {args.out}")
    else:
        print(text)
    return 1 if any(t["status"] == "data_gap" for t in report["teams"].values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
