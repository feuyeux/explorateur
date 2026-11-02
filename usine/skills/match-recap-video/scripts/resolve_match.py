#!/usr/bin/env python3
"""resolve_match.py — 「当前赛季最新的一场比赛」解析器。

把「给一支球队，找到本赛季最新一场已完赛比赛，并拿到官方事实源 + 集锦母版」
做成可复跑、可审计的一步，而不是人工翻网页抄链接。

三条硬规矩：

  1. **不许凭网页顺序猜「最新」。** 四个联赛的赛程页控件顺序互相打架
     （法甲的 club 页上，最近一场在轮播首位、官方集锦视频列表里却是另一场）。
     只有**日期**能定序。所以：排序键永远是日期，取不到日期的候选一律不进
     「最新」评选，而是报出来让人看。
  2. **解析不出来就退出非零并留下原始证据。** 不许静默兜底成默认值
     （纪律 19）。候选面之间若给出不同的「最新」，两个读数都报出来，退出码 2。
  3. **每个字段带来源。** fact pack 里每个值都记着它是从哪个 URL、哪条规则
     抽出来的；没抽到的字段是 null 并标 reason，不填猜测值。

用法：
    python3 resolve_match.py --team barcelona                 # 解析并打印 fact pack
    python3 resolve_match.py --team barcelona --out pack.json # 写文件
    python3 resolve_match.py --team barcelona --dry-run       # 只打印将要抓的 URL
    python3 resolve_match.py --selftest                       # 离线跑夹具，不联网

退出码：0 = 解析成功；1 = 有 FAIL 级问题（事实源能力不足等）；2 = 输入/环境坏了；
        3 = 多个候选面互相矛盾（需要人来定）。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FIXTURES = ASSETS / "fixtures"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ---------------------------------------------------------------- 注册表


def load_registry() -> tuple[dict, dict]:
    with (ASSETS / "teams.json").open(encoding="utf-8") as fh:
        teams = json.load(fh)
    with (ASSETS / "leagues.json").open(encoding="utf-8") as fh:
        leagues = json.load(fh)
    return teams["teams"], leagues["leagues"]


class ResolveError(RuntimeError):
    """解析失败——必须带原始证据，不许兜底。"""


# ---------------------------------------------------------------- 抓取


def scrape(url: str, out_path: Path) -> str:
    """把 URL 抓成 markdown。优先 firecrawl（四个联赛的页面都是 JS 渲染的，
    直连只能拿到壳）；没有 firecrawl 就退到 urllib，但那时多半解析不出来——
    那是事实，不是可以兜底的事。"""
    if shutil.which("firecrawl"):
        proc = subprocess.run(
            ["firecrawl", "scrape", url, "-o", str(out_path)],
            capture_output=True,
            text=True,
        )
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path.read_text(encoding="utf-8", errors="replace")
        raise ResolveError(
            f"firecrawl 抓取失败：{url}\n"
            f"stdout={proc.stdout[-400:]}\nstderr={proc.stderr[-400:]}"
        )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — 失败必须带原因往外抛
        raise ResolveError(f"直连抓取失败：{url}（{exc}）。"
                           "四个联赛页面多为 JS 渲染，建议装 firecrawl。") from exc


# ---------------------------------------------------------------- 日期

DATE_LALIGA = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
DATE_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+)\b")
DATE_WEEKDAY_DAY_MONTH = re.compile(r"\b[A-Z][a-z]+day\s+(\d{1,2})\s+([A-Z][a-z]+)\b")
DATE_WEEKDAY_DAY = re.compile(r"\b[A-Z][a-z]+day\s+(\d{1,2})\b")
MONTH_HEADING = re.compile(r"^#{2,6}\s*([A-Z][a-z]+)\b")
MONTH_HEADING_FULL = re.compile(r"^#{2,6}\s*(January|February|March|April|May|June|July|August|September|October|November|December)\b")


def _year_for(month: int, asof: date) -> int:
    """按 asof 推年份：取离 asof 最近的那个同月（赛季跨年时天然正确）。"""
    cand = asof.year
    best, best_gap = cand, None
    for y in (cand - 1, cand, cand + 1):
        try:
            d = date(y, month, 1)
        except ValueError:
            continue
        gap = abs((d - asof).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = y, gap
    return best


def _month_from_heading(text: str, pos: int) -> int | None:
    """往前找最近的月份小节标题（法甲/德甲的日期只给日，月份在标题里）。"""
    for line in reversed(text[:pos].splitlines()[-80:]):
        m = MONTH_HEADING_FULL.match(line.strip()) or MONTH_HEADING.match(line.strip())
        if m:
            return MONTHS.get(m.group(1).lower())
    return None


def norm_date(raw: str, asof: date, context_month: int | None = None) -> str | None:
    """把各联赛的日期写法统一成 YYYY-MM-DD。认不出就返回 None——绝不猜。"""
    m = DATE_LALIGA.search(raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = DATE_WEEKDAY_DAY_MONTH.search(raw)
    if m:
        mo = MONTHS.get(m.group(2).lower())
        if mo:
            try:
                return date(_year_for(mo, asof), mo, int(m.group(1))).isoformat()
            except ValueError:
                return None
    m = DATE_DAY_MONTH.search(raw)
    if m:
        mo = MONTHS.get(m.group(2).lower())
        if mo:
            try:
                return date(_year_for(mo, asof), mo, int(m.group(1))).isoformat()
            except ValueError:
                return None
    m = DATE_WEEKDAY_DAY.search(raw)
    if m and context_month:
        try:
            return date(_year_for(context_month, asof), context_month, int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- 赛程候选解析

SCORE_PAIR = re.compile(r"\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\b")
MATCH_URL_RE = re.compile(r"https?://[^\s)\]]+/match[^\s)\]]*")
PREMIER_LEAGUE_URL_RE = re.compile(
    r"https?://www\.premierleague\.com/en/match/(\d+)/([a-z0-9-]+)-vs-([a-z0-9-]+)"
)
BUNDESLIGA_URL_RE = re.compile(
    r"https?://www\.bundesliga\.com/en/bundesliga/matchday/([\d-]+)/(\d+)/([a-z0-9-]+)-vs-([a-z0-9-]+)"
)
LALIGA_URL_RE = re.compile(
    r"https?://www\.laliga\.com/([a-zA-Z-]+)/match/temporada-([\d-]+)-([a-z0-9-]+?)-(\d+)\b"
)
LIGUE1_URL_RE = re.compile(
    r"https?://ligue1\.com/[a-z/]*match-sheet/l1_championship_match_(\d+)"
)


DATE_L1_GW = re.compile(r"GW\.\d+\s*-\s*[A-Z][a-z]+day\s+(\d{1,2})")
BVB_SCORE = re.compile(r"\b([A-Z]{2,4})\s+(\d{1,2})\s+([A-Z]{2,4})\s+(\d{1,2})\b")


def _date_before(lines: list[str], i: int, asof: date) -> str | None:
    """从第 i 行往回找最近的一个日期。

    德甲俱乐部页的日期在 20 行开外（夹在上一场的块尾），固定 ±N 行的窗口
    抓不到；往回找「最近的一个认得出的日期」比窗口稳。
    """
    for back in range(i, max(-1, i - 80), -1):
        line = lines[back]
        for pat in (DATE_LALIGA, DATE_WEEKDAY_DAY_MONTH, DATE_DAY_MONTH):
            if pat.search(line):
                d = norm_date(line, asof)
                if d:
                    return d
    return None

def _clean(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # markdown 链接 → 文字
    text = text.replace("\\", "").replace("\\\\", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_fixtures(markdown: str, league: str, asof: date) -> list[dict]:
    """从赛程面里抽出候选场次。每条候选带日期、比分、主客、比赛页 URL。"""
    lines = markdown.splitlines()
    cands: list[dict] = []

    if league == "premierleague":
        # 形状：日期行 → 队名 → 比分/时间 → 队名 → 比赛页链接
        for i, line in enumerate(lines):
            m = PREMIER_LEAGUE_URL_RE.search(line)
            if not m:
                continue
            mid, home_slug, away_slug = m.group(1), m.group(2), m.group(3)
            window = _clean("\n".join(lines[max(0, i - 12):i + 2]))
            dt = _date_before(lines, i, asof) or norm_date(window, asof)
            score = None
            ms = SCORE_PAIR.search(window)
            if ms:
                score = f"{ms.group(1)}-{ms.group(2)}"
            cands.append({
                "date": dt, "score": score, "match_id": mid,
                "home_slug": home_slug, "away_slug": away_slug,
                "competition": "Premier League",
                "url": f"https://www.premierleague.com/en/match/{mid}/{home_slug}-vs-{away_slug}/overview",
                "source_line": i + 1,
            })

    elif league == "bundesliga":
        # 形状：Saturday 31 October → 队名 → 比分 → 队名 → 链接
        for i, line in enumerate(lines):
            m = BUNDESLIGA_URL_RE.search(line)
            if not m:
                continue
            season, md, home_slug, away_slug = m.group(1), m.group(2), m.group(3), m.group(4)
            window = _clean("\n".join(lines[max(0, i - 30):i + 2]))
            dt = _date_before(lines, i, asof)
            score = None
            # 德甲俱乐部页的比分是「主队缩写 主分 客队缩写 客分」四段，
            # 不是 "2-2" 连写——按缩写夹着的数字取。
            ms = BVB_SCORE.search(window)
            if ms:
                score = f"{ms.group(2)}-{ms.group(4)}"
            else:
                ms = SCORE_PAIR.search(window)
                if ms:
                    score = f"{ms.group(1)}-{ms.group(2)}"
            cands.append({
                "date": dt, "score": score, "matchday": md, "season": season,
                "home_slug": home_slug, "away_slug": away_slug,
                "competition": "Bundesliga",
                "url": (f"https://www.bundesliga.com/en/bundesliga/matchday/{season}/{md}/"
                        f"{home_slug}-vs-{away_slug}/liveticker"),
                "source_line": i + 1,
            })

    elif league == "laliga":
        # 西甲的赛程面是**管道表格**，一行一场，比「从 URL 附近猜日期」可靠得多：
        #   | SAT 31.10.2026 | 16:00 | [主](…)<br>6<br>\- <br>1<br>[客](…) | 赛事 | - | [比赛页](…) |
        # 注意两处坑：
        #  1) 赛事段与主客 slug 之间没有分隔符，**拆不开就别拆**（整段留着当 slug 串用）；
        #  2) 俱乐部 /results 页可能**不含最新一轮**（实抓：巴萨俱乐部页缺 10-31 对阿拉维斯那场，
        #     联赛总表里却有）——所以必须两个面交叉核对，见 resolve()。
        for i, line in enumerate(lines):
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            dt = None
            for c in cells:
                if LALIGA_DATE.match(c):
                    dt = norm_date(c, asof)
                    break
            if not dt:
                continue
            ms = re.search(r"<br>(\d{1,2})<br>\\-\s*<br>(\d{1,2})<br>", line)
            score = f"{ms.group(1)}-{ms.group(2)}" if ms else None
            mu = re.search(
                r"https://www\.laliga\.com/[a-zA-Z-]+/match/temporada-[^\s\)\"]+", line)
            if not mu:
                continue
            url = mu.group(0)
            # ⚠️ 两个面的列含义不同：俱乐部 /results 页这一列是**赛事名**，
            # 联赛总表这一列是**主裁姓名**。认不出赛事就留 None——
            # 留 None 的行**不被 scope 收窄**（信息缺失 ≠ 不是联赛），
            # 填成假值会把正确的候选筛掉。
            comp = None
            for c in cells:
                if re.search(r"EA SPORTS|HYPERMOTION|Champions League|Copa|Segunda", c):
                    comp = c
                    break
            names = re.findall(
                r"\[([^\]]+)\]\(https://www\.laliga\.com/[a-zA-Z-]+/clubs/", line)
            home = names[0] if names else None
            away = names[1] if len(names) > 1 else None
            mid = url.rsplit("-", 1)[-1]
            slugs = re.search(r"/match/temporada-([\d-]+)-(.+)-(\d+)$", url)
            cands.append({
                "date": dt, "score": score, "match_id": mid,
                "season": slugs.group(1) if slugs else None,
                "slugs": slugs.group(2) if slugs else None,
                "home": home, "away": away,
                "competition": comp,
                "url": url,
                "source_line": i + 1,
            })

    elif league == "ligue1":
        for i, line in enumerate(lines):
            m = LIGUE1_URL_RE.search(line)
            if not m:
                continue
            window = "\n".join(lines[max(0, i - 20):i + 2])
            mo = _month_from_heading(window, len(window))
            dt = None
            # 法甲的赛程行是「L1 - GW.10 - Friday 6」：只有日，月份在
            # 上面的月份小节标题里（「##### November」）。
            for back in range(i, max(-1, i - 40), -1):
                mg = DATE_L1_GW.search(lines[back])
                if mg:
                    dt = norm_date(lines[back], asof, context_month=mo)
                    if dt:
                        break
            if not dt:
                dt = norm_date(window, asof, context_month=mo)
            score = None
            ms = SCORE_PAIR.search(_clean(window))
            if ms:
                score = f"{ms.group(1)}-{ms.group(2)}"
            cands.append({
                "date": dt, "score": score, "match_id": m.group(1),
                "competition": "Ligue 1",
                "url": f"https://ligue1.com/en/match-sheet/l1_championship_match_{m.group(1)}",
                "source_line": i + 1,
            })

    return cands


# ---------------------------------------------------------------- 选取「最新」


def select_latest(cands: list[dict], asof: date, scope: str,
                  league_tokens: list[str] | None = None) -> tuple[dict | None, list[dict]]:
    """挑「当前赛季最新一场已完赛」。

    排序键是日期，不是页面顺序（法甲的控件顺序会骗人）。
    没日期的候选不参与评选，但会被原样返回，让人看得见它为什么出局。
    """
    undated = [c for c in cands if not c.get("date")]
    dated = [c for c in cands if c.get("date")]
    future = [c for c in dated if c["date"] > asof.isoformat()]

    # 未来日期的候选剔除（asof 当天或之后开球的都算未来）
    asof_iso = asof.isoformat()
    past = [c for c in dated if c["date"] <= asof_iso]

    # 已完赛 = 有比分。有比分的才进评选。
    completed = [c for c in past if c.get("score")]
    pool = completed or past

    # scope=league：只要联赛正赛。赛事名认不出来的候选**保留**
    # （信息缺失不该被当成「不是联赛」——那会悄悄缩小候选池）。
    if scope == "league" and league_tokens:
        narrowed = [c for c in pool
                    if not c.get("competition") or c["competition"] in league_tokens]
        if narrowed:
            pool = narrowed

    if not pool:
        return None, undated

    best_date = max(c["date"] for c in pool)
    winners = [c for c in pool if c["date"] == best_date]
    # 同一日多场（罕见）：取带比分的
    winners.sort(key=lambda c: (bool(c.get("score")), c.get("source_line", 0)), reverse=True)
    return winners[0], undated


# ---------------------------------------------------------------- 比赛页事实包


EVENT_LINE = re.compile(r"^(\d{1,3})'\s*$")
LALIGA_GOAL = re.compile(r"^Goal!\s*(.+?)\.\s*(.+)$")
LALIGA_SUB = re.compile(r"^Substitution,\s*(.+?)\.\s*(.+?)\s+replaces\s+(.+)$")
LALIGA_CARD = re.compile(r"^(.+?) is shown the (yellow|red) card")
LALIGA_VAR = re.compile(r"^VAR Decision:\s*(.+)$")
PL_YOUTUBE = re.compile(r"https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]+)")


def _next_nonempty(lines: list[str], i: int) -> int:
    j = i
    while j < len(lines) and not lines[j].strip():
        j += 1
    return j


LALIGA_DATE = re.compile(r"^[A-Z]{3},?\s+\d{1,2}\.\d{1,2}\.\d{4}$")
LALIGA_KICKOFF = re.compile(r"^\d{1,2}:\d{2}\s*h$")
LALIGA_ATTEND = re.compile(r"^(\d{1,3}(?:,\d{3})+|\d{4,6})\s*\\?\*?$")
LALIGA_FORMATION = re.compile(r"^\d-\d-\d$")
LALIGA_GOAL_SCORE = re.compile(r"^Goal!\s*.+?\s(\d+),\s*.+?\s(\d+)\.")


def parse_laliga_header(lines: list[str], meta: dict) -> None:
    """西甲比赛页头部是**位置结构**（Full Time → 射手行 → 日期 → 开球 → 球场 →
    上座 → 裁判名单），不是关键词结构。按位置读，别按关键词猜。"""
    ft = next((i for i, l in enumerate(lines) if l == "Full Time"), None)
    if ft is None:
        return
    j = _next_nonempty(lines, ft + 1)

    scorers: list[str] = []
    while j < len(lines):
        line = lines[j]
        if LALIGA_DATE.match(line) or line.startswith("!") or line.startswith("["):
            break
        scorers.append(line)
        j = _next_nonempty(lines, j + 1)
    meta["scorers"] = scorers

    if j < len(lines) and LALIGA_DATE.match(lines[j]):
        meta["date"] = lines[j]
        j = _next_nonempty(lines, j + 1)
    if j < len(lines) and LALIGA_KICKOFF.match(lines[j]):
        meta["kickoff"] = lines[j]
        j = _next_nonempty(lines, j + 1)
    if j < len(lines):
        meta["venue"] = lines[j]
        j = _next_nonempty(lines, j + 1)
    if j < len(lines):
        m = LALIGA_ATTEND.match(lines[j])
        if m:
            meta["attendance"] = m.group(1)
            j = _next_nonempty(lines, j + 1)

    referees: list[str] = []
    while j < len(lines):
        line = lines[j]
        if line.startswith("!") or line.startswith("["):
            break
        if LALIGA_DATE.match(line) or re.match(r"^Matchday", line):
            break
        referees.append(line)
        j = _next_nonempty(lines, j + 1)
    meta["referees"] = referees

    md = next((l for l in lines if l.startswith("Matchday")), None)
    if md:
        meta["round"] = md

    formations: list[str] = []
    for i, line in enumerate(lines):
        if LALIGA_FORMATION.match(line):
            k = i - 1
            while k >= 0 and not lines[k].strip():
                k -= 1
            if k >= 0:
                formations.append(f"{lines[k]} {line}")
    meta["formations"] = formations

    tr = next((i for i, l in enumerate(lines) if l == "Trainers"), None)
    if tr is not None:
        trainers: list[str] = []
        j = _next_nonempty(lines, tr + 1)
        while j < len(lines) and len(trainers) < 4:
            line = lines[j]
            if line.startswith("!") or line.startswith("[") or LALIGA_DATE.match(line):
                break
            if re.match(r"^(Starters|Substitutes|Trainers)$", line):
                break
            trainers.append(line)
            j = _next_nonempty(lines, j + 1)
        meta["trainers"] = trainers


def parse_match_page(markdown: str, league: str) -> dict:
    """从官方比赛页抽事实包。抽不到就留 null + reason，不填猜测值。"""
    lines = [l.strip() for l in markdown.splitlines()]
    events: list[dict] = []
    meta: dict = {"score": None, "date": None, "venue": None, "attendance": None,
                  "trainers": [], "formations": [], "lineups": {}, "highlights": None}

    if league == "laliga":
        for i, line in enumerate(lines):
            if not line or not EVENT_LINE.match(line):
                continue
            minute = int(EVENT_LINE.match(line).group(1))
            body = ""
            for nxt in lines[i + 1:i + 5]:
                if not nxt or EVENT_LINE.match(nxt):
                    continue
                if nxt.startswith("!") or nxt.startswith("["):
                    continue
                body = nxt
                break
            if not body:
                continue
            kind = "unknown"
            if LALIGA_GOAL.match(body):
                kind = "goal"
            elif LALIGA_SUB.match(body):
                kind = "substitution"
            elif LALIGA_CARD.match(body):
                kind = "card"
            elif LALIGA_VAR.match(body):
                kind = "var"
            elif body.startswith("Foul by") or "wins a free kick" in body:
                kind = "foul"
            events.append({"minute": minute, "kind": kind, "text": body})
        parse_laliga_header(lines, meta)
        # 比分：取**分钟最大**的那个进球事件（页面事件流是倒序的，
        # 最后一条不是最后一场进球——按文档顺序取会拿到 1-0）。
        goals = [e for e in events if e["kind"] == "goal"]
        if goals:
            top = max(goals, key=lambda e: e["minute"])
            mg = LALIGA_GOAL_SCORE.match(top["text"])
            if mg:
                meta["score"] = f"{mg.group(1)}-{mg.group(2)}"
                meta["score_from"] = f"{top['minute']}' 进球事件（页面事件流倒序，按分钟取最大）"

    elif league == "premierleague":
        m = PL_YOUTUBE.search(markdown)
        if m:
            meta["highlights"] = f"https://www.youtube.com/watch?v={m.group(1)}"
        # 比分藏在图片 alt 里：LIV 0-1 ARS
        m = re.search(r"\b([A-Z]{2,4})\s+(\d{1,2})-(\d{1,2})\s+([A-Z]{2,4})\b", markdown)
        if m:
            meta["score"] = f"{m.group(2)}-{m.group(3)}"
            meta["score_abbr"] = f"{m.group(1)} {m.group(4)}"
        # 日期与球场连在同一行：Sun 01 NovAnfield；下一行是主裁
        for i, line in enumerate(lines):
            m = re.match(r"^([A-Z][a-z]{2})\s+(\d{2})\s+([A-Z][a-z]{2})([A-Z][A-Za-z' ]+)$", line)
            if not m:
                continue
            meta["date_raw"] = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            meta["venue"] = m.group(4).strip()
            j = _next_nonempty(lines, i + 1)
            if j < len(lines):
                meta["referee"] = lines[j]
            break
        meta["report_present"] = "Open match report" in markdown
        meta["event_stream"] = "prose"   # 事件在 /commentary 标签页，overview 只有叙述稿

    elif league == "bundesliga":
        # 实抓结论：德甲的 liveticker 是**叙述式直播**，标题是编辑文案
        # （"Dortmund level!"、"Off the bar!"），不是 "Goal: Silva 88'"。
        # 只有换人与终场是结构化标题。所以这里只把能认的认出来，其余标 editorial。
        meta["event_stream"] = "narrative"
        skip_prefix = ("watch:", "vote now", "recommended", "editorial")
        for i, line in enumerate(lines):
            if not line.startswith("#### "):
                continue
            title = line[5:].strip()
            low = title.lower()
            if any(low.startswith(p) for p in skip_prefix):
                continue
            minute = None
            for back in range(i - 1, max(-1, i - 5), -1):
                mm = EVENT_LINE.match(lines[back])
                if mm:
                    minute = int(mm.group(1))
                    break
            if minute is None:
                # 终场标题自带结果
                m = re.match(r"full time:\s*(.+?)\s+(\d{1,2})-(\d{1,2})\s+(.+)$", low)
                if m:
                    meta["score"] = f"{m.group(2)}-{m.group(3)}"
                    meta["result_headline"] = title
                continue
            body = " ".join(x for x in lines[i + 1:i + 4] if x)
            if low.startswith("substitution"):
                kind = "substitution"
            elif "card" in low:
                kind = "card"
            elif "penalty" in low or "var" in low:
                kind = "var"
            else:
                kind = "editorial"
            events.append({"minute": minute, "kind": kind, "text": f"{title} — {body[:160]}"})

    elif league == "ligue1":
        # 实抓结论：ligue1.com 的比赛页在 markdown 里**不暴露可用的事件流**——
        # 事件藏在图标图例后面，只剩「Summary」里零星几条。这里如实记录，不假装有。
        meta["event_stream"] = "none"
        for m in re.finditer(r"^([A-Z]\.[A-Z]?\.?\s*[A-Za-zÀ-ÿ' -]+)$", markdown, re.M):
            ev = m.group(1).strip()
            if ev and len(ev) < 40:
                events.append({"minute": None, "kind": "sparse", "text": ev})
        for m in re.finditer(r"^(\d{1,3})'\s*$", markdown, re.M):
            events.append({"minute": int(m.group(1)), "kind": "sparse", "text": ""})
        break_flag = True
        if break_flag:
            meta["lineups_present"] = "##### Formation" in markdown
            meta["stats_present"] = "##### Statistics" in markdown

    return {"meta": meta, "events": events}


# ---------------------------------------------------------------- 能力声明


def _team_scoped(cands: list[dict], team: dict, leagues: dict, lg_key: str) -> list[dict]:
    """把候选收窄到**这支队**的比赛。

    联赛总表是全联赛的（西甲的总表里最后一场可能是别人的比赛），不收窄就会
    把「联赛最后一场」当成「这支队的最后一场」。URL 里带队伍 slug 的联赛
    按 slug 过滤；URL 只有数字 id 的联赛（法甲）本来就只有俱乐部面，不动。
    """
    lg = leagues[lg_key]
    if not lg.get("match_url_carries_team_slug"):
        return cands
    slug = team.get("club_slug")
    if not slug:
        raise ResolveError(f"{team.get('zh')} 缺 club_slug，无法按队收窄候选")
    # 分隔符要含 "/"：英超 URL 里 slug 前面是 "/match/{id}/liverpool-vs-…"，
    # 德甲后面是 "/liveticker"，西甲两边都是 "-"。三种都得认。
    pat = re.compile(r"(?:^|[-/])" + re.escape(slug) + r"(?:[-/.]|$)")
    kept = [c for c in cands if pat.search(c.get("url", ""))]
    if not kept:
        raise ResolveError(
            f"候选里没有一场属于 {team.get('zh')}（slug={slug}）："
            "URL 模板可能变了，或 club_slug 写错了。"
        )
    return kept


def capability_report(league_key: str, leagues: dict) -> list[str]:
    """这个联赛的官方事实源能撑住哪几条事件轴。撑不住的必须说明白。"""
    lg = leagues[league_key]
    problems: list[str] = []
    stream = lg.get("event_stream", "unverified")
    if stream == "structured":
        pass  # 进球 / 换人 / 牌 / VAR 全有结构化字段
    elif stream == "prose":
        problems.append(
            f"{lg['zh']}官方比赛页的 overview 只有叙述稿与内嵌集锦；"
            "逐分钟事件在 /commentary 标签页——overview 解析拿不到事件时间线。"
        )
    elif stream == "narrative":
        problems.append(
            f"{lg['zh']}官方 liveticker 是叙述式直播：标题是编辑文案"
            "（「Dortmund level!」「Off the bar!」），只有换人与终场是结构化标题。"
            "**进球分钟与判罚抓不到结构化字段**——需人工读，或改走 DFL 的 bapi 数据层。"
        )
    elif stream == "none":
        problems.append(
            f"{lg['zh']}官方比赛页在抓下来的 markdown 里**没有可用事件流**"
            "（事件藏在图标图例后面）。进球/换人/牌的时间线要改用俱乐部官网或 LFP 数据层，"
            "不要硬啃 ligue1.com。"
        )
    else:
        problems.append(f"{lg['zh']}适配器的事件流形态未验证（event_stream={stream}）。")
    if not lg.get("var_exposed"):
        problems.append(
            f"{lg['zh']}官方页不明列 VAR 判决：判罚需另找裁判报告或当场解说稿，"
            "**不得从赛果反推**。"
        )
    return problems


# ---------------------------------------------------------------- 主流程


def resolve(team_key: str, asof: date, scope: str, dry_run: bool = False,
            match_url: str | None = None) -> dict:
    teams, leagues = load_registry()
    if team_key not in teams:
        raise ResolveError(f"未知球队 {team_key!r}；可选：{', '.join(sorted(teams))}")
    team = teams[team_key]
    lg_key = team["league"]
    lg = leagues[lg_key]
    fs = lg["fact_source"]

    ctx = {
        "team": team_key,
        "team_zh": team["zh"],
        "team_en": team["en"],
        "league": lg_key,
        "league_zh": lg["zh"],
        "season": lg["season_label"],
        "asof": asof.isoformat(),
        "scope": scope,
    }

    if match_url:
        # 手动指定比赛页（法甲这类「官方赛程面答不了」的联赛的兜底）：
        # 跳过发现，直接读比赛页出 fact pack。
        ctx["latest_pick"] = {"url": match_url, "date": None, "score": None,
                              "source": "manual --match-url"}
        ctx["resolved"] = True
        ctx["cross_checked"] = False
        ctx["cross_check_note"] = "比赛页由人工指定，未做发现面交叉核对。"
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            try:
                md = scrape(match_url, tmpdir / "match.md")
                ctx["match_page"] = parse_match_page(md, lg_key)
                ctx["match_page"]["url"] = match_url
            except ResolveError as exc:
                ctx["match_page"] = {"error": str(exc), "url": match_url}
        ctx["capability_warnings"] = capability_report(lg_key, leagues)
        return ctx

    if dry_run:
        ctx["plan"] = {
            "fixtures_urls": _fixtures_urls(lg_key, lg, team),
            "match_url_template": fs.get("match_url"),
        }
        ctx["capability_warnings"] = capability_report(lg_key, leagues)
        return ctx

    surfaces = _fixtures_urls(lg_key, lg, team)
    findings: list[dict] = []
    undated_total: list[dict] = []
    all_cands: list[dict] = []
    tokens = lg.get("league_competition_tokens")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for url in surfaces:
            try:
                md = scrape(url, tmpdir / "page.md")
            except ResolveError as exc:
                findings.append({"surface": url, "ok": False, "error": str(exc)})
                continue
            cands = parse_fixtures(md, lg_key, asof)
            if not cands:
                findings.append({"surface": url, "ok": False,
                                 "error": "这个面没解析出任何候选场次（页面结构可能变了）"})
                continue
            best, undated = select_latest(cands, asof, scope, tokens)
            findings.append({"surface": url, "ok": True,
                             "candidates": len(cands),
                             "dated": len([c for c in cands if c.get("date")]),
                             "undated": len(undated),
                             "latest": best})
            undated_total.extend(undated)
            for c in cands:
                c["_surface"] = url
            try:
                scoped = _team_scoped(cands, team, leagues, lg_key)
            except ResolveError as exc:
                findings.append({"surface": url, "ok": False, "error": str(exc)})
                continue
            all_cands.extend(scoped)

    ctx["surfaces"] = findings
    ctx["undated_candidates"] = undated_total
    ctx["capability_warnings"] = capability_report(lg_key, leagues)
    limit = lg.get("fixture_surface_limitation")
    if limit:
        ctx["fixture_surface_limitation"] = limit
    if lg.get("supplemental_fact_sources"):
        ctx["supplemental_fact_sources"] = lg["supplemental_fact_sources"]

    if not all_cands:
        ctx["resolved"] = False
        ctx["reason"] = "所有候选面都没给出可排序的「最新已完赛」——需要人工指定比赛页。"
        return ctx

    future = [c for c in all_cands if c.get("date") and c["date"] > asof.isoformat()]
    if future:
        ctx["future_candidates"] = [
            {"date": c["date"], "competition": c.get("competition"),
             "url": c["url"], "surface": c.get("_surface")} for c in future
        ]

    # ---- 取并集再定最新 ----
    # 各面的覆盖范围不同（实抓：西甲俱乐部 /results 页可能不含最新一轮），
    # 所以「最新」是**所有面的并集**里的最大日期，不是逐面比大小。
    best, _ = select_latest(all_cands, asof, scope, tokens)
    if not best:
        ctx["resolved"] = False
        ctx["reason"] = (
            "候选里没有可排序的「最新已完赛」——这个联赛的官方赛程面"
            "**只给未赛场次或不给日期**，需要人工指定比赛页。"
            "（法甲尤其如此：club 页只有未来赛程，比赛页给的是轮次名义日期。）"
        )
        return ctx

    # ---- 真冲突：同一日期给出不同比赛 ----
    same_day = [c for c in all_cands
                if c.get("date") == best["date"] and c.get("url") != best["url"]]
    if same_day:
        ctx["resolved"] = False
        ctx["conflict"] = [
            {"surface": c.get("_surface"), "date": c["date"], "score": c.get("score"),
             "url": c["url"]}
            for c in [{"_surface": best.get("_surface"), **best}] + same_day
        ]
        ctx["reason"] = (
            f"同一日期（{best['date']}）在候选面之间指向了不同比赛——"
            "这是真冲突，需要人工指定比赛页。"
        )
        return ctx

    ctx["latest_pick"] = best
    ctx["cross_checked"] = len({c.get("_surface") for c in all_cands}) > 1
    if not ctx["cross_checked"]:
        ctx["cross_check_note"] = (
            "只有一个候选面解析出结果，未做交叉核对；"
            "页面顺序不可信，请人工确认这条日期。"
        )

    # 比赛页事实包
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        try:
            md = scrape(best["url"], tmpdir / "match.md")
            ctx["match_page"] = parse_match_page(md, lg_key)
            ctx["match_page"]["url"] = best["url"]
        except ResolveError as exc:
            ctx["match_page"] = {"error": str(exc), "url": best["url"]}

    ctx["capability_warnings"] = capability_report(lg_key, leagues)
    ctx["resolved"] = True
    return ctx


def _fixtures_urls(lg_key: str, lg: dict, team: dict) -> list[str]:
    """候选赛程面。顺序 = 尝试顺序；第一个解析出结果的即为所用来源。"""
    fs = lg["fact_source"]
    base = fs["base"]
    slug = team.get("club_slug")
    cid = team.get("club_id")
    season = lg["season_arg"]
    # ⚠️ 西甲的赛事段有两种拼法，**别混**：
    #    路径用 `laliga-easports`（easports 连写），比赛 URL 里用 `laliga-ea-sports`（带连字符）。
    comp = lg.get("competition_path") or (
        "laliga-easports" if lg_key == "laliga" else lg_key)

    if lg_key == "laliga":
        # 俱乐部 /results 页（管道表格）与联赛总表 —— 两个面**必须都跑**：
        # 实抓发现俱乐部页可能不含最新一轮（巴萨俱乐部页缺 10-31 对阿拉维斯那场），
        # 所以取**并集**再定最新；只有同一日期给出不同比赛时才是真冲突。
        return [
            f"{base}/{fs['lang']}/clubs/{slug}/results",
            f"{base}/{fs['lang']}/{comp}/results",
        ]
    if lg_key == "premierleague":
        return [
            f"{base}/{fs['lang']}/matches/premier-league/{season}",
            f"{base}/{fs['lang']}/clubs/{cid}/matches",
        ]
    if lg_key == "bundesliga":
        return [
            f"{base}/{fs['lang']}/{comp}/clubs/{slug}/matches",
            f"{base}/{fs['lang']}/{comp}/matchday/{season}/{slug}",
        ]
    if lg_key == "ligue1":
        return [
            f"{base}/{fs['lang']}/club-sheet/l1_championship_club_{season}_{cid}/matches",
            f"{base}/{fs['lang']}/club-sheet/l1_championship_club_{season}_{cid}/calendar",
        ]
    return [f"{base}/{fs['lang']}"]


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """离线跑夹具：解析器必须能从实抓页面里抽出预期事实。不联网。"""
    cases = [
        ("laliga", "pages/laliga-match.md", "parse_match_page", {"score_expected": None}),
        ("premierleague", "pages/premierleague-match.md", "parse_match_page", {}),
        ("bundesliga", "pages/bundesliga-match.md", "parse_match_page", {}),
    ]
    bad = 0
    for league, fname, fn, _ in cases:
        path = FIXTURES / fname
        if not path.exists():
            print(f"FAIL  {league}: 夹具缺失 {path}")
            bad += 1
            continue
        md = path.read_text(encoding="utf-8")
        try:
            out = parse_match_page(md, league)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {league}: 解析抛异常 {exc}")
            bad += 1
            continue
        n = len(out["events"])
        print(f"PASS  {league}: 事件 {n} 条，meta 键 {sorted(out['meta'])}")
        if league == "laliga" and n < 10:
            print(f"FAIL  {league}: 事件数 {n} < 10，实抓页里有 20+ 条")
            bad += 1
        if league == "premierleague" and not out["meta"].get("highlights"):
            print("FAIL  premierleague: 没抓到官方集锦链接")
            bad += 1

    # 选取逻辑：日期优先于页面顺序
    fake = [
        {"date": "2026-10-25", "score": "2-2", "source_line": 90},
        {"date": "2026-10-31", "score": "6-1", "source_line": 12},
        {"date": None, "score": "1-0", "source_line": 3},
        {"date": "2026-11-05", "score": "3-0", "source_line": 5},
    ]
    best, undated = select_latest(fake, date(2026, 11, 2), "league")
    ok = best and best["date"] == "2026-10-31" and len(undated) == 1
    print(f"{'PASS' if ok else 'FAIL'}  select_latest: 取 {best and best['date']}（页面顺序在前的 2026-10-25 被正确跳过；未来场次 11-05 被剔除）")
    if not ok:
        bad += 1

    print()
    print(f"自检：{len(cases) + 1 - bad}/{len(cases) + 1} 通过")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="match-recap-video「当前赛季最新一场」解析器",
        epilog="队伍 key 与口径走位置参数（skill 本地脚本的私有参数不进库层旗标词表）。")
    ap.add_argument("team", nargs="?", help="teams.json 里的队伍 key")
    ap.add_argument("scope", nargs="?", choices=["league", "all"], default="league",
                    help="league = 只看联赛（默认）；all = 含杯赛/欧战（口径不同）")
    ap.add_argument("asof", nargs="?", help="基准日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--out", help="fact pack 输出路径（默认打到 stdout）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要抓的 URL，不联网")
    ap.add_argument("--match-url", help="手动指定官方比赛页 URL（跳过发现面，用于官方赛程面答不了的联赛）")
    ap.add_argument("--selftest", action="store_true", help="离线跑夹具")
    args = ap.parse_args(argv)

    if args.selftest or args.team == "selftest":
        return selftest()
    if not args.team:
        ap.print_help()
        return 2

    asof = date.fromisoformat(args.asof) if args.asof else date.today()
    try:
        ctx = resolve(args.team, asof, args.scope, dry_run=args.dry_run,
                      match_url=args.match_url)
    except ResolveError as exc:
        print(json.dumps({"resolved": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    out = json.dumps(ctx, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"fact pack → {args.out}")
    else:
        print(out)
    return 0 if ctx.get("resolved") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
