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
     （纪律 19）。候选面之间若给出不同的「最新」，两个读数都报出来，退出码 1。
     比赛页抓不动、或解析出 0 条事件，同样不许标 resolved。
  3. **每个字段带来源。** fact pack 里每个值都记着它是从哪个 URL、哪条规则
     抽出来的；没抽到的字段是 null 并标 reason，不填猜测值。

用法：
    python3 resolve_match.py barcelona                 # 解析并打印 fact pack（league 口径）
    python3 resolve_match.py barcelona all --out pack.json
    python3 resolve_match.py barcelona --dry-run       # 只打印将要抓的 URL，不联网
    python3 resolve_match.py barcelona --allow-unfinished  # 最新一场还没有比分时仍出 fact pack
    python3 resolve_match.py --all-targets --asof 2026-11-02 --out packs.json
    python3 resolve_match.py selftest                  # 离线跑夹具 + 判别逻辑负例，不联网

退出码：0 = 解析成功；1 = 没解析出可用的「最新已完赛」（含比赛页抓不动/解析出
        0 条事件/同日真冲突/未完赛未加 --allow-unfinished）；2 = 输入/环境坏了。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
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


def scrape(url: str, out_path: Path, scroll: bool = False) -> str:
    """把 URL 抓成 markdown。优先 firecrawl（四个联赛的页面都是 JS 渲染的，
    直连只能拿到壳）；没有 firecrawl 就退到 urllib，但那时多半解析不出来——
    那是事实，不是可以兜底的事。

    scroll=True 用于英超 /commentary：它是虚拟列表，不滚动只能拿到末尾几条。
    """
    exe = shutil.which("firecrawl")
    if exe and sys.platform == "win32" and not exe.lower().endswith((".cmd", ".exe", ".bat")):
        # npm 在 Windows 上装的是无扩展名的 sh 脚本，CreateProcess 执行不了；
        # 同目录的 firecrawl.cmd 才是可直接调用的入口。
        cmd_exe = Path(exe + ".cmd")
        if cmd_exe.exists():
            exe = str(cmd_exe)
    if exe:
        cmd = [exe, "scrape", url, "-o", str(out_path), "--max-age", "0"]
        if scroll:
            # 先等内容渲染，再滚；否则抓到的是只有页头的空壳。
            cmd += ["--actions", json.dumps([
                {"type": "wait", "milliseconds": 2000},
                {"type": "scroll", "direction": "down", "amount": 3000},
                {"type": "wait", "milliseconds": 1500},
                {"type": "scroll", "direction": "down", "amount": 3000},
                {"type": "wait", "milliseconds": 1500},
            ])]
        proc = subprocess.run(cmd, capture_output=True, text=True)
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
DATE_DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+)\s+(\d{4})\b")
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
    low = raw.strip().lower()
    for word, rel in (("today", 0), ("yesterday", -1), ("tomorrow", 1)):
        if re.match(rf"^{word}\b", low):
            return (asof + timedelta(days=rel)).isoformat()
    m = DATE_LALIGA.search(raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = DATE_DAY_MONTH_YEAR.search(raw)
    if m:
        mo = MONTHS.get(m.group(2).lower())
        if mo:
            try:
                return date(int(m.group(3)), mo, int(m.group(1))).isoformat()
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


RELATIVE_DATES = {
    "today": 0,
    "yesterday": -1,
    "tomorrow": 1,
}


def _date_before(lines: list[str], i: int, asof: date, span: int = 80) -> str | None:
    """从第 i 行往回找最近的一个日期。

    德甲俱乐部页的日期在 20 行开外（夹在上一场的块尾），所以默认往回找 80 行；
    英超俱乐部页的「比分/结果」行没有日期，往回找太远会串到上面赛程的日期——
    英超单独用 span=8。
    """
    for back in range(i, max(-1, i - span), -1):
        line = lines[back].strip()
        low = line.lower()
        rel = next((rel for word, rel in RELATIVE_DATES.items()
                    if re.match(rf"^{word}\b", low)), None)
        if rel is not None:
            return (asof + timedelta(days=rel)).isoformat()
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


def _slug_name(slug: str | None) -> str | None:
    if not slug:
        return None
    return " ".join(part.capitalize() for part in slug.split("-"))


# ---------------------------------------------------------------- 事件时间线
#
# 四个联赛的事件写法不同，但都能落到同一个事件 schema：
#   {minute, added, clock, kind, text, ...}
# kind: goal | substitution | card | var | penalty | editorial | whistle | other
#
# 分钟写法有四种，全部实测见过：
#   89'      90'+4'（英超/巴黎）   90' + 4（德甲）   90'+5'+5'（巴黎页面重复渲染）

MINUTE_LINE = re.compile(r"^(?:-\s*)?(\d{1,3})'\s*(?:\+\s*(\d{1,2}))?")
PLAYER_LINK = re.compile(r"\[([^\]\n]+)\]\((?:https?://[^)\s]*?/player/[^)\s]+)\)")
TEAM_IN_PARENS = re.compile(r"\(([^()]+)\)")


def parse_minute(line: str) -> tuple[int, int] | None:
    m = MINUTE_LINE.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def _clock(minute: int, added: int) -> str:
    return f"{minute}+{added}" if added else str(minute)


def _event(minute: int, added: int, kind: str, text: str, **extra) -> dict:
    ev = {"minute": minute, "added": added, "clock": _clock(minute, added),
          "kind": kind, "text": _clean(text)}
    ev.update({k: v for k, v in extra.items() if v not in (None, "")})
    return ev


def _sort_events(events: list[dict]) -> list[dict]:
    """按比赛时钟升序；同分钟按原文顺序（倒序页面要先 reverse 再 sort 会乱）。"""
    return sorted(events, key=lambda e: (e["minute"], e.get("added", 0)))


def _dedupe_events(events: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for ev in events:
        key = (ev["minute"], ev.get("added", 0), ev["kind"],
               ev.get("player") or ev.get("in") or ev["text"][:40])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _player_from_link(line: str) -> str | None:
    """从 markdown 里取球员名。

    liveticker 的球员头像是 `[![Name](…/player/….png)](…/player/slug)`：
    图片 URL 也含 `/player/`，所以第一个匹配会带出 `![Name`。优先取纯文字
    链接；只有图片链接时再去掉 `![`。"""
    fallback = None
    for m in PLAYER_LINK.finditer(line):
        name = _clean(m.group(1))
        if not name.startswith("!"):
            return name
        fallback = name.lstrip("![").strip()
    return fallback


def parse_fixtures(markdown: str, league: str, asof: date,
                   date_span: int = 80) -> list[dict]:
    """从赛程面里抽出候选场次。每条候选带日期、比分、主客、比赛页 URL。

    date_span 控制「往回找日期」的行数：德甲俱乐部页日期在 20 行外，要 80；
    英超赛季页的相对日期（Yesterday）在 15 行外，要 25；英超俱乐部页的结果行
    没有日期，只能用 8——否则会串到上面的赛程日期。
    """
    lines = markdown.splitlines()
    cands: list[dict] = []

    if league == "premierleague":
        # 形状：日期行 → 队名 → 比分/时间 → 队名 → 比赛页链接
        for i, line in enumerate(lines):
            m = PREMIER_LEAGUE_URL_RE.search(line)
            if not m:
                continue
            mid, home_slug, away_slug = m.group(1), m.group(2), m.group(3)
            window = _clean("\n".join(lines[max(0, i - 6):i + 3]))
            # 英超俱乐部页的结果行没有日期，往回扫 80 行会串到上面的赛程；
            # 只认紧邻 8 行内的日期，或同一行里的 `Sun 01 Nov`。
            dt = _date_before(lines, i, asof, span=date_span) or norm_date(window, asof)
            # 比分取窗口里**最后一个**：当前场的比分紧贴在比赛页链接前，
            # 窗口靠前的位置可能是上一场的比分。
            score_window = _clean("\n".join(lines[max(0, i - 10):i + 2]))
            scores = SCORE_PAIR.findall(score_window)
            score = f"{scores[-1][0]}-{scores[-1][1]}" if scores else None
            cands.append({
                "date": dt, "score": score, "match_id": mid,
                "home_slug": home_slug, "away_slug": away_slug,
                "home": _slug_name(home_slug), "away": _slug_name(away_slug),
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
            raw_window = lines[max(0, i - 30):i + 2]
            window = _clean("\n".join(raw_window))
            dt = _date_before(lines, i, asof)
            score = None
            # 队名在 logo 的 alt 里（比 slug 好看：FC Bayern München 而不是
            # Fc Bayern Muenchen）。以比分行 `2 - 2` 为锚，往前/后各取一个 alt。
            home_name, away_name = None, None
            score_at = next((j for j, l in enumerate(raw_window)
                             if re.fullmatch(r"\s*\d{1,2}\s*-\s*\d{1,2}\s*", l)), None)
            if score_at is not None:
                for j in range(score_at - 1, -1, -1):
                    am = re.search(r"!\[([^\]]+)\]", raw_window[j])
                    if am and not am.group(1).lower().startswith("highlights"):
                        home_name = _clean(am.group(1))
                        break
                for j in range(score_at + 1, len(raw_window)):
                    am = re.search(r"!\[([^\]]+)\]", raw_window[j])
                    if am and not am.group(1).lower().startswith("highlights"):
                        away_name = _clean(am.group(1))
                        break
            if not (home_name and away_name):
                # 有的版式把整张比赛卡拆成多行（`主队 2 / 客队 2` 都在链接里），
                # 没有独立比分行；取 URL 所在的**连续块**里的两个队徽 alt。
                # 不能从 30 行窗口取——会串到上一场的队名。
                start = i
                while start > 0 and lines[start - 1].strip():
                    start -= 1
                block_text = "\n".join(lines[start:i + 1])
                alts = [_clean(a) for a in re.findall(r"!\[([^\]]+)\]", block_text)]
                alts = [a for a in alts if a and not a.lower().startswith(
                    ("highlights", "play-button", "watch"))]
                if len(alts) >= 2:
                    home_name, away_name = alts[0], alts[1]
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
                "home": home_name or _slug_name(home_slug),
                "away": away_name or _slug_name(away_slug),
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


def _norm_url(url: str | None) -> str:
    """URL 归一：去 query/fragment、去尾斜杠、小写协议与主机名。

    同一场比赛在两个面上可能带不同 tracking 参数或尾斜杠出现两次——
    精确字符串去重会把它们当两条，进而把「同日同场」误判成真冲突。"""
    if not url:
        return ""
    u = url.strip()
    for sep in ("#", "?"):
        u = u.split(sep, 1)[0]
    while u.endswith("/"):
        u = u[:-1]
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*)://([^/]*)(.*)$", u)
    if m:
        u = f"{m.group(1).lower()}://{m.group(2).lower()}{m.group(3)}"
    return u


def _norm_name(name: str | None) -> str:
    """队名归一：小写、去变音符、只留字母数字。Alavés 与 Alaves 是同一支队。"""
    if not name:
        return ""
    low = name.lower()
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", low)
                       if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", stripped)


def _same_match(a: dict, b: dict) -> bool:
    """两个候选是不是**同一场比赛**：日期相同，且双方队名归一后一致、比分一致
    （比分一侧缺失按「不矛盾」放行——发现面常先给日期后给比分）。

    队名认不出来时**返回 False**（fail-closed）：证明不了是同一场，
    就按「同日不同比赛」报冲突，让人来定，不许静默合并。"""
    if not a.get("date") or a.get("date") != b.get("date"):
        return False
    for side in ("home", "away"):
        na, nb = _norm_name(a.get(side)), _norm_name(b.get(side))
        if not na or not nb or na != nb:
            return False
    sa, sb = a.get("score"), b.get("score")
    if sa and sb and sa != sb:
        return False
    return True


def corroborating_surfaces(cands: list[dict], winner: dict) -> set[str]:
    """赢家被**几个候选面**印证：其余候选里与赢家同日同场的面（URL 是否相同
    不影响——同一场在两个面上挂着同一个链接，是最硬的印证）。

    「有两个面出过候选」不等于「选中这场被交叉核对过」——西甲的俱乐部
    /results 页可能整轮缺失，赢家只在一个面上出现过；这时 cross-check
    是空话，必须如实说没有。"""
    surfaces = {winner.get("_surface") or ""}
    for c in cands:
        if c is winner or not c.get("_surface"):
            continue
        if _same_match(winner, c):
            surfaces.add(c["_surface"])
    return {s for s in surfaces if s}


def dedupe_candidates(cands: list[dict]) -> list[dict]:
    """同一场比赛可能从多个面抓到（西甲两个表格、德甲俱乐部页 + 轮次页）。
    按**归一化 URL** 去重；保留先到的那条，缺的字段从后到的补。"""
    out: list[dict] = []
    by_url: dict[str, dict] = {}
    for c in cands:
        key = _norm_url(c.get("url"))
        if key and key in by_url:
            kept = by_url[key]
            for field in ("date", "score", "home", "away", "competition", "round"):
                if not kept.get(field) and c.get(field):
                    kept[field] = c[field]
            continue
        if key:
            by_url[key] = c
        out.append(c)
    return out


def select_latest(cands: list[dict], asof: date, scope: str,
                  league_tokens: list[str] | None = None) -> tuple[dict | None, list[dict]]:
    """挑「当前赛季最新一场已完赛」。

    排序键是日期，不是页面顺序（法甲的控件顺序会骗人）。
    没日期的候选不参与评选，但会被原样返回，让人看得见它为什么出局。
    池里没有任何带比分的候选时，赢家带 `unfinished` 标记——「最新一场」
    可能仍在进行或官网未更新赛果，不许冒充已完赛。
    """
    undated = [c for c in cands if not c.get("date")]
    dated = [c for c in cands if c.get("date")]

    # 未来日期的候选剔除（asof 当天或之后开球的都算未来）
    asof_iso = asof.isoformat()
    past = [c for c in dated if c["date"] <= asof_iso]

    # 已完赛 = 有比分。有比分的才进评选。
    completed = [c for c in past if c.get("score")]
    pool = completed or past
    unfinished = not completed and bool(pool)

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
    winners[0]["unfinished"] = unfinished
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
LALIGA_MINUTE_FULL = re.compile(r"^(\d{1,3})'(?:\+(\d{1,2})')?$")


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
    if referees:
        meta["referee"] = referees[0]
    if meta.get("date"):
        raw_date = meta["date"]
        iso = norm_date(raw_date, date.today())
        if iso:
            meta["date_raw"] = raw_date
            meta["date"] = iso

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


# ---------------------------------------------------------------- 巴黎：俱乐部官网赛程
#
# ligue1.com 给不出「真实开球日」，但 psg.fr 的月度赛程页给：
#   ## Le Havre AC vs Paris Saint-Germain - 30 October 2026 - 19:00
#   [..](https://www.psg.fr/en/matches/mens-football/20262027/le-havre-vs-paris-2026-10-30)
#   L1  /  Matchweek 9
#   ![Le Havre logo](…)Le Havre1
#   ![Paris logo](…)Paris5
#   FRIDAY OCTOBER 30 202619:00 / Stade CMA CGM Océane
# 日期、赛事、比分、球场都在，因此它就是法甲的发现面（ligue1.com 退为阵容面）。

PSG_FIXTURE_HEAD = re.compile(
    r"^##\s+(.+?)\s+vs\.?\s+(.+?)\s+-\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s+-\s+(\d{1,2}:\d{2})"
)
PSG_SCORE_LINE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*([^0-9]+?)\s*(\d{1,2})\s*$")
PSG_COMPETITIONS = {
    "L1": "Ligue 1",
    "UCL": "UEFA Champions League",
    "CDF": "Coupe de France",
    "FRC": "Trophée des Champions",
    "AMF": "Friendly",
    "LDC": "UEFA Champions League",
}


def parse_psg_fixtures(markdown: str, asof: date) -> list[dict]:
    """解析 psg.fr 月度赛程页。只抽「标题行 + 紧随其后的比赛块」。"""
    lines = markdown.splitlines()
    cands: list[dict] = []
    for i, line in enumerate(lines):
        m = PSG_FIXTURE_HEAD.match(line.strip())
        if not m:
            continue
        home, away = _clean(m.group(1)), _clean(m.group(2))
        dt = norm_date(f"{m.group(3)} {m.group(4)} {m.group(5)}", asof)
        url = None
        comp = None
        round_ = None
        scores: list[str] = []
        for j in range(i + 1, min(len(lines), i + 45)):
            raw = lines[j].strip()
            if not url:
                mu = re.search(r"https://www\.psg\.fr/en/matches/[^\s)\"']+", raw)
                if mu:
                    url = mu.group(0)
            code = PSG_COMPETITIONS.get(raw)
            if code:
                comp = code
            if re.match(r"^(Matchweek \d+|League phase.*|Round of .*|Group .*)$", raw):
                round_ = raw
            ms = PSG_SCORE_LINE.match(raw)
            if ms and len(scores) < 2 and not raw.startswith("## "):
                scores.append(ms.group(2))
            # 下一场的标题行 = 本块结束
            if raw.startswith("## ") and j > i + 1:
                break
        if not url:
            continue
        cands.append({
            "date": dt,
            "score": f"{scores[0]}-{scores[1]}" if len(scores) == 2 else None,
            "home": home,
            "away": away,
            "competition": comp,
            "round": round_,
            "url": url,
            "source_line": i + 1,
        })
    return cands


# ---------------------------------------------------------------- 英超：/commentary
#
# overview 只有叙述稿；逐分钟事件在 /commentary。该页是虚拟列表，需要滚动抓。
# 版式是「事件块 → 分钟行」：分钟在事件**后面**（`- 16'`），不是前面。

PL_MINUTE_FULL = re.compile(r"^(?:-\s*)?(\d{1,3})'\s*(?:\+\s*(\d{1,2})'?)?$")
PL_GOAL = re.compile(r"^Goal!\s*(.+?)\s+(\d+),\s*(.+?)\s+(\d+)\.\s*(.*)$")
PL_OWN_GOAL = re.compile(r"^Own Goal by (.+?),\s*(.+?)\.\s*(.+?)\s+(\d+),\s*(.+?)\s+(\d+)\.")
PL_SUB = re.compile(r"^Substitution,\s*([^.]+)\.\s*(.+?)\s+replaces\s+(.+?)(?:\.|$)")
PL_CARD = re.compile(r"^(.+?)\s+\(([^()]+)\)\s+is shown the (yellow|red) card")
PL_EVENT_PREFIXES = (
    "Goal!", "Own Goal", "Substitution,", "Attempt ", "Foul ", "Corner,",
    "Offside,", "Handball", "Penalty", "First Half", "Second Half",
    "Match ends", "VAR",
)


def _pl_minute(line: str) -> tuple[int, int] | None:
    m = PL_MINUTE_FULL.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def _pl_assist(desc: str) -> str | None:
    m = re.search(r"Assisted by\s+([A-Z][^.,]*?)(?:\s+with|\s+following|\.|$)", desc)
    return _clean(m.group(1)) if m else None


def parse_premierleague_commentary(markdown: str) -> list[dict]:
    lines = [l.rstrip() for l in markdown.splitlines()]
    minute_rows = [(i, _pl_minute(l)) for i, l in enumerate(lines) if _pl_minute(l)]
    events: list[dict] = []

    def emit(block: list[str], minute: int, added: int) -> None:
        text = next((l for l in block if l.startswith(PL_EVENT_PREFIXES) or
                     "is shown the" in l), None)
        if not text:
            return
        text = _clean(text)

        m = PL_GOAL.match(text)
        if m:
            desc = m.group(5)
            pm = re.match(r"^(.*?)\s+\(([^()]+)\)", desc)
            player = _clean(pm.group(1)) if pm else None
            team = _clean(pm.group(2)) if pm else None
            events.append(_event(
                minute, added, "goal", text,
                player=player, team=team, assist=_pl_assist(desc),
                score=f"{m.group(2)}-{m.group(4)}",
                score_home=_clean(m.group(1)), score_away=_clean(m.group(3)),
            ))
            return

        m = PL_OWN_GOAL.match(text)
        if m:
            events.append(_event(
                minute, added, "goal", text, player=_clean(m.group(1)),
                team=_clean(m.group(2)), own_goal=True,
                score=f"{m.group(4)}-{m.group(6)}",
            ))
            return

        m = PL_SUB.match(text)
        if m:
            events.append(_event(
                minute, added, "substitution", text, team=_clean(m.group(1)),
                in_player=_clean(m.group(2)), out_player=_clean(m.group(3)),
            ))
            return

        m = PL_CARD.match(text)
        if m:
            events.append(_event(
                minute, added, "card", text, player=_clean(m.group(1)),
                team=_clean(m.group(2)), card=m.group(3),
            ))
            return

        if "VAR" in text.upper():
            events.append(_event(minute, added, "var", text))
        elif text.startswith(("First Half ends", "Second Half ends", "Match ends")):
            events.append(_event(minute, added, "whistle", text))
        else:
            events.append(_event(minute, added, "other", text))
    # 版式两种都见过：普通解说句的分钟行在事件**后**；带 ### Goal/Substitution/
    # Yellow Card 标题的块，分钟行在事件**前**。按块内有没有标题决定归属。
    for n, (i, parsed) in enumerate(minute_rows):
        if not parsed:
            continue
        minute, added = parsed
        next_i = minute_rows[n + 1][0] if n + 1 < len(minute_rows) else len(lines)
        before = [l.strip() for l in lines[(minute_rows[n - 1][0] + 1) if n else 0:i]
                  if l.strip()]
        after = [l.strip() for l in lines[i + 1:next_i] if l.strip()]
        after_headed = any(l.startswith("### ") for l in after)
        before_headed = any(l.startswith("### ") for l in before)
        if after_headed:
            emit(after, minute, added)
        elif before_headed:
            # 块在分钟行之前且后面没有新块：少见版式，仍按当前分钟收
            if not after:
                emit(before, minute, added)
        else:
            emit(before, minute, added)
    return _sort_events(_dedupe_events(events))


# ---------------------------------------------------------------- 德甲：liveticker
#
# 旧结论「进球分钟抓不到」是错的：liveticker 的进球是结构化块——
#   89'
#   ### [Fabio Silva](…/player/fabio-silva)
#   ## GOAL!
#   2:2
#   Assist: [K. Karetsas](…)
# 换人/牌也有结构化标记（### Substitution / ![yellowCard]）。编辑文案标题
# （#### Dortmund level!）只是同分钟的叙述，保留为 editorial 供画面轴取材。

BVB_SCORE_AFTER_GOAL = re.compile(r"^(\d{1,2}):(\d{1,2})$")
BVB_ASSIST = re.compile(r"^Assist:\s*\[([^\]]+)\]")
BVB_CLUB_ID = re.compile(r"clublogos/DFL-SEA-0001KA/(DFL-CLU-[A-Z0-9]+)\.svg")


def _prev_minute(lines: list[str], i: int, span: int = 8) -> tuple[int, int] | None:
    for back in range(i - 1, max(-1, i - span), -1):
        got = parse_minute(lines[back])
        if got:
            return got
    return None


def _next_player_link(lines: list[str], i: int, span: int = 10) -> str | None:
    for j in range(i, min(len(lines), i + span)):
        name = _player_from_link(lines[j])
        if name:
            return name
    return None


def parse_bundesliga(markdown: str, team: dict | None = None) -> dict:
    lines = [l.strip() for l in markdown.splitlines()]
    events: list[dict] = []

    # 主客 club id（用于给换人/牌标队）：头部前两个 clublogo
    club_ids: list[str] = []
    for line in lines[:80]:
        for cid in BVB_CLUB_ID.findall(line):
            if cid not in club_ids:
                club_ids.append(cid)
        if len(club_ids) == 2:
            break

    def side_of(block_text: str) -> str | None:
        found = BVB_CLUB_ID.search(block_text)
        if not found or not club_ids:
            return None
        return "home" if found.group(1) == club_ids[0] else "away"

    # 比分：终场标题最可靠；没有就用头部两个数字
    meta: dict = {"score": None, "event_stream": "structured_liveticker"}
    for line in lines:
        m = re.match(r"^####\s*Full time:\s*.+?\s+(\d{1,2})-(\d{1,2})\s+.+$", line, re.I)
        if m:
            meta["score"] = f"{m.group(1)}-{m.group(2)}"
            meta["result_headline"] = line[5:].strip()
            break

    # 球场 / 主裁 / 进球视频
    for i, line in enumerate(lines):
        if "/stadium/icon/" in line:
            tail = re.sub(r"^(?:!\[[^\]]*\]\([^)]*\))+", "", line).strip()
            if not tail:
                tail = next((x for x in lines[i + 1:i + 4] if x), "")
            if tail:
                meta["venue"] = re.sub(r"\s*\(\s*(Sold out|sold out)\s*\)", "", tail)
        if "whistle.svg" in line:
            meta["referee"] = re.sub(r"^.*?whistle\.svg\)", "", line).strip()
        if "/video/jw/" in line and not meta.get("highlights_poster"):
            m = re.search(r"(https://assets\.bundesliga\.com/video/jw/[A-Za-z0-9]+\.jpg)", line)
            if m:
                meta["highlights_poster"] = m.group(1)
                meta["highlights_video_id"] = m.group(1).rsplit("/", 1)[-1].split(".")[0]

    # 进球块
    for i, line in enumerate(lines):
        if line not in ("## GOAL!", "## PENALTY GOAL!", "## OWN GOAL!"):
            continue
        minute = _prev_minute(lines, i, span=6)
        if not minute:
            continue
        scorer = None
        for back in range(i - 1, max(-1, i - 5), -1):
            if lines[back].startswith("### "):
                scorer = _player_from_link(lines[back]) or _clean(lines[back][4:])
                break
        score_after = None
        assist = None
        for nxt in lines[i + 1:i + 12]:
            ms = BVB_SCORE_AFTER_GOAL.match(nxt)
            if ms and not score_after:
                score_after = f"{ms.group(1)}-{ms.group(2)}"
            ma = BVB_ASSIST.match(nxt)
            if ma and not assist:
                assist = _clean(ma.group(1))
        kind = "goal"
        note = None
        if line.startswith("## PENALTY"):
            note = "penalty"
        elif line.startswith("## OWN"):
            note = "own_goal"
        ev = _event(minute[0], minute[1], kind, scorer or "GOAL", player=scorer,
                    assist=assist, score_after=score_after, note=note)
        events.append(ev)

    # 终场比分以**分钟最大的进球**的赛后比分为准；页面事件是倒序的，
    # 按文档顺序覆盖会拿到 1:0。取不到就用终场标题的比分。
    goals = [e for e in events if e["kind"] == "goal" and e.get("score_after")]
    if goals:
        top = max(goals, key=lambda e: (e["minute"], e.get("added", 0)))
        meta["score"] = top["score_after"]
        meta["score_from"] = f"{top['clock']}' 进球块"

    # 换人块
    for i, line in enumerate(lines):
        if line != "#### Substitution":
            continue
        minute = _prev_minute(lines, i, span=6)
        if not minute:
            continue
        block = lines[i:i + 14]
        names: list[str] = []
        for j, raw in enumerate(block[1:], start=1):
            name = _player_from_link(raw)
            if name and (not names or names[-1] != name):
                names.append(name)
            if raw.startswith("#### ") or parse_minute(raw):
                break
        if len(names) >= 2:
            events.append(_event(
                minute[0], minute[1], "substitution", f"{names[0]} replaces {names[1]}",
                in_player=names[0], out_player=names[1], side=side_of("\n".join(block)),
            ))

    # 牌块：liveticker 用图标节点，不在正文句子里
    for i, line in enumerate(lines):
        low = line.lower()
        if "yellowcard.svg" not in low and "redcard.svg" not in low:
            continue
        minute = _prev_minute(lines, i, span=5)
        if not minute:
            continue
        player = _next_player_link(lines, i, span=8)
        color = "red" if "redcard" in low else "yellow"
        events.append(_event(
            minute[0], minute[1], "card", f"{player or 'player'} — {color} card",
            player=player, card=color, side=side_of("\n".join(lines[max(0, i - 3):i + 8])),
        ))

    # 编辑文案：保留标题 + 前两句，供画面轴/进程轴取材；不冒充结构化事件
    skip = ("watch:", "vote now", "recommended", "editorial", "full time")
    for i, line in enumerate(lines):
        if not line.startswith("#### "):
            continue
        title = line[5:].strip()
        low = title.lower()
        if any(low.startswith(p) for p in skip) or low == "substitution":
            continue
        minute = _prev_minute(lines, i, span=6)
        if not minute:
            continue
        body = " ".join(x for x in lines[i + 1:i + 4] if x and not x.startswith("###"))
        kind = "var" if ("var" in low or "var" in body.lower()) else "editorial"
        events.append(_event(minute[0], minute[1], kind, f"{title} — {body[:220]}"))

    meta["stream_note"] = (
        "进球/换人/牌来自 liveticker 的结构化节点；#### 标题是编辑文案，"
        "只作叙述素材，不作为事件分钟的事实源。"
    )
    return {"meta": meta, "events": _sort_events(_dedupe_events(events))}


# ---------------------------------------------------------------- 巴黎：比赛页
#
# psg.fr 的比赛页有完整逐分钟文字直播（与英超同源 Opta 式写法），
# 但**不提供阵容/阵型**；阵容要回 ligue1.com 的 match-sheet。

PSG_MINUTE = re.compile(r"^(\d{1,3})'(?:\+(\d{1,2}))?")
PSG_GOAL = re.compile(r"^Goal!\s*(.+?)\s+(\d+),\s*(.+?)\s+(\d+)\.\s*(.*)$")
PSG_SUB = re.compile(r"^Substitution,\s*([^.]+)\.\s*(.+?)\s+replaces\s+(.+?)(?:\.|$)")
PSG_CARD = re.compile(r"^(.+?)\s+\(([^()]+)\)\s+is shown the (yellow|red) card")
PSG_VAR = re.compile(r"^VAR Decision:\s*(.+)$")


def parse_psgfr_match(markdown: str) -> dict:
    lines = [l.strip() for l in markdown.splitlines()]
    meta: dict = {"score": None, "date": None, "venue": None, "referee": None,
                  "event_stream": "commentary", "lineups": {},
                  "lineups_note": "psg.fr 比赛页不含阵容/阵型；阵容需回 ligue1.com match-sheet。",
                  "lineups_hint": "ligue1.com/en/match-sheet/l1_championship_match_<id>（按对手 + 比分在 Ligue 1 赛程页定位）"}
    events: list[dict] = []

    # 比分：Full time FT 前后两行的数字
    for i, line in enumerate(lines):
        if line.lower() in ("full time ft", "full time"):
            before = next((x for x in reversed(lines[max(0, i - 4):i]) if x), "")
            after = next((x for x in lines[i + 1:i + 4] if x), "")
            if before.isdigit() and after.isdigit():
                meta["score"] = f"{before}-{after}"
            break

    # 日期 / 球场 / 主裁
    for i, line in enumerate(lines):
        if meta["date"] is None:
            m = re.match(r"^#*\s*([A-Z][a-z]+day\s+\d{1,2}\s+[A-Z][a-z]+\s+\d{4})$", line)
            if m:
                meta["date"] = norm_date(m.group(1), date.today())
        if line.startswith("Ref:"):
            ref = _clean(line[4:])
            # psg.fr 把名字压成一串（FrançoisLetexier）；驼峰处补空格
            meta["referee"] = re.sub(r"(?<=[a-zà-ÿ])(?=[A-Z])", " ", ref)
            prev = next((x for x in reversed(lines[max(0, i - 4):i]) if x), "")
            if prev and not prev.startswith("Ref"):
                meta["venue"] = prev

    # 事件：分钟行在前，正文紧随其后
    for i, line in enumerate(lines):
        mm = PSG_MINUTE.match(line)
        if not mm:
            continue
        minute, added = int(mm.group(1)), int(mm.group(2) or 0)
        body = next((x for x in lines[i + 1:i + 4] if x), "")
        if not body:
            continue
        m = PSG_GOAL.match(body)
        if m:
            desc = m.group(5)
            pm = re.match(r"^(.*?)\s+\(([^()]+)\)", desc)
            events.append(_event(
                minute, added, "goal", body,
                player=_clean(pm.group(1)) if pm else None,
                team=_clean(pm.group(2)) if pm else None,
                assist=_pl_assist(desc),
                score=f"{m.group(2)}-{m.group(4)}",
                score_home=_clean(m.group(1)), score_away=_clean(m.group(3)),
            ))
            continue
        m = PSG_SUB.match(body)
        if m:
            events.append(_event(
                minute, added, "substitution", body, team=_clean(m.group(1)),
                in_player=_clean(m.group(2)), out_player=_clean(m.group(3)),
            ))
            continue
        m = PSG_CARD.match(body)
        if m:
            events.append(_event(
                minute, added, "card", body, player=_clean(m.group(1)),
                team=_clean(m.group(2)), card=m.group(3),
            ))
            continue
        m = PSG_VAR.match(body)
        if m:
            events.append(_event(minute, added, "var", body, decision=_clean(m.group(1))))
            continue
        events.append(_event(minute, added, "other", body))

    # 比分交叉核对：分钟最大的进球
    goals = [e for e in events if e["kind"] == "goal"]
    if goals:
        top = max(goals, key=lambda e: (e["minute"], e.get("added", 0)))
        if top.get("score"):
            meta["score"] = top["score"]
            meta["score_from"] = f"{top['clock']}' 进球事件"
    return {"meta": meta, "events": _sort_events(_dedupe_events(events))}


def parse_match_page(markdown: str, league: str) -> dict:
    """从官方比赛页抽事实包。抽不到就留 null + reason，不填猜测值。"""
    lines = [l.strip() for l in markdown.splitlines()]
    events: list[dict] = []
    meta: dict = {"score": None, "date": None, "venue": None, "attendance": None,
                  "trainers": [], "formations": [], "lineups": {}, "highlights": None}

    if league == "laliga":
        for i, line in enumerate(lines):
            mm = LALIGA_MINUTE_FULL.match(line)
            if not mm:
                continue
            minute, added = int(mm.group(1)), int(mm.group(2) or 0)
            body = ""
            for nxt in lines[i + 1:i + 5]:
                if not nxt or LALIGA_MINUTE_FULL.match(nxt):
                    continue
                if nxt.startswith("!") or nxt.startswith("["):
                    continue
                body = nxt
                break
            if not body:
                continue

            gm = PL_GOAL.match(body)
            if gm:
                desc = gm.group(5)
                pm = re.match(r"^(.*?)\s+\(([^()]+)\)", desc)
                events.append(_event(
                    minute, added, "goal", body,
                    player=_clean(pm.group(1)) if pm else None,
                    team=_clean(pm.group(2)) if pm else None,
                    assist=_pl_assist(desc),
                    score=f"{gm.group(2)}-{gm.group(4)}",
                    score_home=_clean(gm.group(1)), score_away=_clean(gm.group(3)),
                ))
                continue
            sm = LALIGA_SUB.match(body)
            if sm:
                events.append(_event(
                    minute, added, "substitution", body, team=_clean(sm.group(1)),
                    in_player=_clean(sm.group(2)), out_player=_clean(sm.group(3)),
                ))
                continue
            cm = LALIGA_CARD.match(body)
            if cm:
                raw_player = _clean(cm.group(1))
                pm = re.match(r"^(.*?)\s+\(([^()]+)\)$", raw_player)
                events.append(_event(
                    minute, added, "card", body,
                    player=_clean(pm.group(1)) if pm else raw_player,
                    team=_clean(pm.group(2)) if pm else None,
                    card=cm.group(2),
                ))
                continue
            vm = LALIGA_VAR.match(body)
            if vm:
                events.append(_event(minute, added, "var", body, decision=_clean(vm.group(1))))
                continue
            kind = "foul" if (body.startswith("Foul by") or "wins a free kick" in body) else "unknown"
            events.append(_event(minute, added, kind, body))

        parse_laliga_header(lines, meta)
        # 比分：取**分钟最大**的那个进球事件（页面事件流是倒序的，
        # 最后一条不是最后一场进球——按文档顺序取会拿到 1-0）。
        goals = [e for e in events if e["kind"] == "goal" and e.get("score")]
        if goals:
            top = max(goals, key=lambda e: (e["minute"], e.get("added", 0)))
            meta["score"] = top["score"]
            meta["score_from"] = f"{top['clock']}' 进球事件（页面事件流倒序，按分钟取最大）"

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
        # 结构化 liveticker：进球/换人/牌都有节点，编辑标题保留为 editorial。
        parsed = parse_bundesliga(markdown)
        meta.update(parsed["meta"])
        events = parsed["events"]

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


# ---------------------------------------------------------------- 比赛页抓取（可能多页）


def gather_match(match: dict, team: dict, lg_key: str) -> dict:
    """取比赛页事实包。有的联赛需要两页才完整：

    - 英超：overview（比分/日期/球场/集锦）+ /commentary（逐分钟事件，需滚动）
    - 德甲：liveticker 一页全有
    - 法甲/巴黎：psg.fr 比赛页（事件/比分/日期）——阵容仍需 ligue1.com
    - 西甲：比赛页一页全有
    """
    url = match["url"]
    result: dict = {"url": url, "sources": [url], "events": [], "meta": {}}
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        if lg_key == "premierleague":
            md = scrape(url, tmpdir / "overview.md")
            result = parse_match_page(md, "premierleague")
            result["url"] = url
            result["sources"] = [url]
            result["meta"]["lineup_url"] = re.sub(r"/overview/?$", "/lineups", url)
            c_url = re.sub(r"/overview/?$", "/commentary", url)
            if c_url != url:
                try:
                    cmd = scrape(c_url, tmpdir / "commentary.md", scroll=True)
                    c_events = parse_premierleague_commentary(cmd)
                    if c_events:
                        result["events"] = c_events
                        result["meta"]["event_stream"] = "commentary"
                        result["meta"]["commentary_url"] = c_url
                        result["sources"].append(c_url)
                    else:
                        result["meta"]["commentary_note"] = "commentary 页抓到但没解析出事件"
                except ResolveError as exc:
                    result["meta"]["commentary_error"] = str(exc)
            return result

        if lg_key == "bundesliga":
            md = scrape(url, tmpdir / "liveticker.md")
            result = parse_match_page(md, "bundesliga")
            result["url"] = url
            result["sources"] = [url]
            if "/liveticker" in url:
                result["meta"]["lineup_url"] = url.replace("/liveticker", "/lineup")
            return result

        if lg_key == "ligue1":
            md = scrape(url, tmpdir / "match.md")
            if "psg.fr" in url:
                result = parse_psgfr_match(md)
            else:
                result = parse_match_page(md, "ligue1")
            result["url"] = url
            result["sources"] = [url]
            return result

        md = scrape(url, tmpdir / "match.md")
        result = parse_match_page(md, lg_key)
        result["url"] = url
        result["sources"] = [url]
        return result


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
    elif stream == "structured_liveticker":
        problems.append(
            f"{lg['zh']}的进球/换人/牌来自 liveticker 的结构化节点"
            "（`## GOAL!` + 分钟 + 比分 + Assist、`#### Substitution`、黄/红牌图标）；"
            "`#### 编辑标题` 只是叙述素材，**不要拿它当事件分钟的事实源**。"
        )
    elif stream == "commentary":
        problems.append(
            f"{lg['zh']}的逐分钟事件是**文字直播流**（`Goal!` / `Substitution,` / "
            "`is shown the … card` / `VAR Decision:`），分页/虚拟列表："
            "英超要滚动抓 /commentary，巴黎用 psg.fr 比赛页。缺结构化阵型/换人图例时，"
            "阵容另回官方 lineup 面。"
        )
    elif stream == "prose":
        problems.append(
            f"{lg['zh']}官方比赛页的 overview 只有叙述稿与内嵌集锦；"
            "逐分钟事件在 /commentary 标签页——overview 解析拿不到事件时间线。"
        )
    elif stream == "narrative":
        problems.append(
            f"{lg['zh']}官方 liveticker 是叙述式直播：标题是编辑文案，"
            "进球分钟抓不到结构化字段——需人工读，或改走 DFL 的 bapi 数据层。"
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
            f"{lg['zh']}官方页不明列 VAR 判决：文字直播里出现的 VAR 句只作线索，"
            "判罚需另找裁判报告或当场解说稿，**不得从赛果反推**。"
        )
    return problems


# ---------------------------------------------------------------- 主流程


def _gather_or_refuse(ctx: dict, pick: dict, team: dict,
                      lg_key: str, leagues: dict) -> bool:
    """抓比赛页并装进 ctx。抓不动 / 解析出 0 条事件 = fact pack **拒绝**标 resolved。

    2026-11-02 评审实测的 fail-open：gather_match 抛错被吞进 match_page.error、
    key_events 变空，resolved 仍是 True、CLI 退出 0——下游会拿零个事件去建
    窗口表还以为成功。比赛页失败与「页面结构变了」必须退出码非零（规矩 2）。
    足球比赛至少有换人/牌，解析出 0 条事件 = 解析器没跟上页面，不是没事件。
    """
    try:
        ctx["match_page"] = gather_match(pick, team, lg_key)
    except ResolveError as exc:
        ctx["match_page"] = {"error": str(exc), "url": pick.get("url")}
        ctx["resolved"] = False
        ctx["reason"] = (f"比赛页抓取/解析失败：{exc}——页面结构可能变了；"
                         "fact pack 不冒充已解析（原始错误见 match_page.error）")
        ctx["capability_warnings"] = capability_report(lg_key, leagues)
        return False
    if not (ctx["match_page"].get("events") or []):
        ctx["resolved"] = False
        ctx["reason"] = ("比赛页解析出 0 条事件——足球比赛至少有换人/牌，"
                         "解析器多半没跟上页面结构；需要人工看原始页面（url 见 match_page.url）")
        ctx["capability_warnings"] = capability_report(lg_key, leagues)
        return False
    return True


def _fill_key_events(ctx: dict) -> None:
    """窗口表只需要关键事件；其余（射门/犯规/角球）留作画面轴取材。

    key_events = 进球/换人/牌/VAR/点球/哨（SKILL.md 的口径同步）；event_counts
    按 kind 逐条计数，缺 0 不缺省——counts 里看不出哨与点球就等于没数。"""
    key_kinds = {"goal", "substitution", "card", "var", "penalty", "whistle"}
    events = (ctx.get("match_page") or {}).get("events") or []
    ctx["key_events"] = [e for e in events if e.get("kind") in key_kinds]
    ctx["event_counts"] = {
        k: sum(1 for e in events if e.get("kind") == k)
        for k in sorted(key_kinds)
    }


def resolve(team_key: str, asof: date, scope: str, dry_run: bool = False,
            match_url: str | None = None, allow_unfinished: bool = False) -> dict:
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
        # 跳过发现，直接读比赛页出 fact pack。抓不动/解析不出事件同样拒绝标 resolved。
        ctx["latest_pick"] = {"url": match_url, "date": None, "score": None,
                              "source": "manual --match-url"}
        ctx["cross_checked"] = False
        ctx["cross_check_note"] = "比赛页由人工指定，未做发现面交叉核对。"
        if not _gather_or_refuse(ctx, {"url": match_url}, team, lg_key, leagues):
            return ctx
        _fill_key_events(ctx)
        ctx["resolved"] = True
        return ctx

    if dry_run:
        ctx["plan"] = {
            "fixtures_urls": _fixtures_urls(lg_key, lg, team, asof),
            "match_url_template": fs.get("match_url"),
        }
        ctx["capability_warnings"] = capability_report(lg_key, leagues)
        return ctx

    surfaces = _fixtures_urls(lg_key, lg, team, asof)
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
            if "psg.fr" in url:
                cands = parse_psg_fixtures(md, asof)
            else:
                span = 80
                if lg_key == "premierleague":
                    span = 25 if "/matches/premier-league/" in url else 8
                cands = parse_fixtures(md, lg_key, asof, date_span=span)
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

    all_cands = dedupe_candidates(all_cands)
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

    # ---- 未完赛：显式降级，不冒充「最新已完赛」 ----
    if best.get("unfinished"):
        ctx["unfinished"] = True
        ctx["latest_pick"] = best
        if not allow_unfinished:
            ctx["resolved"] = False
            ctx["reason"] = (
                "候选里没有任何一场带比分——「最新一场」可能仍在进行，或官网还没更新赛果。"
                "确要使用这一场时加 --allow-unfinished（fact pack 会带 unfinished 标记）。"
            )
            return ctx
        ctx["allow_unfinished"] = True

    # ---- 同日候选分流：证明是同一场的算重复记录，证明不了的才是真冲突 ----
    # URL 不同 ≠ 不同比赛：两个面常用不同 tracking 参数 / 尾斜杠指同一场
    # （2026-11-02 评审实测：同日同队同比分不同 URL 会被误判成真冲突）。
    # 队名认不出来 = 证明不了是同一场 → 按真冲突报，让人来定（fail-closed）。
    same_day = [c for c in all_cands
                if c.get("date") == best["date"]
                and _norm_url(c.get("url")) != _norm_url(best.get("url"))]
    conflicts = [c for c in same_day if not _same_match(best, c)]
    duplicates = [c for c in same_day if _same_match(best, c)]
    if conflicts:
        ctx["resolved"] = False
        ctx["conflict"] = [
            {"surface": c.get("_surface"), "date": c["date"], "score": c.get("score"),
             "home": c.get("home"), "away": c.get("away"),
             "url": c["url"], "same_match": _same_match(best, c)}
            for c in [{"_surface": best.get("_surface"), **best}] + conflicts
        ]
        ctx["reason"] = (
            f"同一日期（{best['date']}）在候选面之间指向了不同比赛——"
            "这是真冲突，需要人工指定比赛页。"
        )
        return ctx
    if duplicates:
        ctx["duplicate_candidates"] = [
            {"surface": c.get("_surface"), "url": c["url"],
             "note": "同日同场不同 URL，按内容确认为重复记录，不算冲突"}
            for c in duplicates
        ]

    ctx["latest_pick"] = best
    # 母版检索线索：官方频道 + 一条可复制到 YouTube 的查询串。
    # 不自动猜「哪个视频对」——集锦视频的标题常带情绪词，人工确认后再冻结。
    home = best.get("home") or _slug_name(best.get("home_slug"))
    away = best.get("away") or _slug_name(best.get("away_slug"))
    score = best.get("score")
    ctx["official_channel"] = team.get("official_channel")
    ctx["highlights"] = {
        "strategy": lg.get("highlights", {}).get("strategy"),
        "channel_url": lg.get("highlights", {}).get("channel_url"),
        "query": " ".join(x for x in (home, score, away, "highlights") if x),
        "note": lg.get("highlights", {}).get("note"),
    }
    # 「交叉核对」的口径 = 赢家被 ≥2 个面印证（同日同场出现在不同面上），
    # 不是「有两个面出过候选」——赢家可能整轮只在一个面上出现（西甲实测）。
    surfaces = corroborating_surfaces(all_cands, best)
    ctx["corroborating_surfaces"] = sorted(surfaces)
    ctx["cross_checked"] = len(surfaces) > 1
    if not ctx["cross_checked"]:
        ctx["cross_check_note"] = (
            "选中的这一场只出现在一个候选面上（没有第二个面给出同日同场的记录）——"
            "页面顺序不可信，请人工确认这条日期。"
        )

    # 比赛页事实包（英超要 overview + commentary 两页）。
    # 抓不动 / 解析出 0 条事件 = 拒绝标 resolved（见 _gather_or_refuse）。
    if not _gather_or_refuse(ctx, best, team, lg_key, leagues):
        return ctx

    # 比赛页缺的基础字段用发现面的读数补齐（德甲 liveticker 不给日期，
    # psg.fr 的日期在标题里，统一回填成 ISO）。
    if isinstance(ctx["match_page"], dict) and ctx["match_page"].get("meta") is not None:
        mp_meta = ctx["match_page"]["meta"]
        for field in ("date", "home", "away", "score"):
            if not mp_meta.get(field):
                mp_meta[field] = best.get(field)

    _fill_key_events(ctx)
    ctx["capability_warnings"] = capability_report(lg_key, leagues)
    ctx["resolved"] = True
    return ctx


_MONTH_TAG = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _recent_month_tags(asof: date, count: int = 3) -> list[str]:
    """当前月 + 前 count-1 个月。psg.fr 的赛程页按月分片，跨月要都抓。"""
    tags: list[str] = []
    y, m = asof.year, asof.month
    for _ in range(count):
        tags.append(_MONTH_TAG[m - 1])
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return tags


def _fixtures_urls(lg_key: str, lg: dict, team: dict, asof: date | None = None) -> list[str]:
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
        # ligue1.com 的俱乐部面只给未赛场次 / 不带日期的比分，答不出「最新」。
        # psg.fr 的月度赛程页有真实日期 + 比分 + 比赛页链接，优先用它。
        site = team.get("club_site") or {}
        tpl = site.get("fixtures_url")
        if tpl:
            day = asof or date.today()
            return [tpl.format(lang=site.get("lang", fs.get("lang", "en")),
                               period=tag)
                    for tag in _recent_month_tags(day)]
        return [
            f"{base}/{fs['lang']}/club-sheet/l1_championship_club_{season}_{cid}/matches",
            f"{base}/{fs['lang']}/club-sheet/l1_championship_club_{season}_{cid}/calendar",
        ]
    return [f"{base}/{fs['lang']}"]


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """离线跑夹具：解析器必须能从实抓页面里抽出预期事实。不联网。"""
    checks: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        checks.append((label, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")

    # 1) 联赛主页面
    cases = [
        ("laliga", "pages/laliga-match.md"),
        ("premierleague", "pages/premierleague-match.md"),
        ("bundesliga", "pages/bundesliga-match.md"),
        ("ligue1", "pages/psg-match.md"),
    ]
    for league, fname in cases:
        path = FIXTURES / fname
        if not path.exists():
            check(f"{league}: 夹具存在", False, str(path))
            continue
        md = path.read_text(encoding="utf-8")
        try:
            out = parse_psgfr_match(md) if league == "ligue1" else parse_match_page(md, league)
        except Exception as exc:  # noqa: BLE001
            check(f"{league}: 解析不抛异常", False, str(exc))
            continue
        n = len(out["events"])
        if league != "premierleague":  # overview 只有叙述稿，事件在 /commentary
            check(f"{league}: 解析出事件", n > 0, f"{n} 条")
        if league == "laliga":
            check("laliga: 事件数 ≥ 10", n >= 10, f"{n} 条")
        if league == "premierleague":
            check("premierleague: 抓到官方集锦链接", bool(out["meta"].get("highlights")))
        if league == "bundesliga":
            goals = [e for e in out["events"] if e["kind"] == "goal"]
            cards = [e for e in out["events"] if e["kind"] == "card"]
            subs = [e for e in out["events"] if e["kind"] == "substitution"]
            check("bundesliga: 进球块解析出分钟 + 射手",
                  bool(goals) and goals[0]["minute"] == 89 and goals[0].get("player") == "Fabio Silva",
                  f"{[(g['minute'], g.get('player')) for g in goals]}")
            check("bundesliga: 换人块有 in/out", bool(subs) and bool(subs[0].get("in_player")),
                  f"{subs[:1]}")
            check("bundesliga: 黄牌块解析出球员", bool(cards) and cards[0].get("card") == "yellow",
                  f"{cards[:1]}")
        if league == "ligue1":
            check("ligue1(psg.fr): 比分 1-5", out["meta"].get("score") == "1-5")
            check("ligue1(psg.fr): 进球 6 个",
                  len([e for e in out["events"] if e["kind"] == "goal"]) == 6,
                  f"{[(e['clock'], e.get('player')) for e in out['events'] if e['kind'] == 'goal']}")
            check("ligue1(psg.fr): VAR 判决", any(e["kind"] == "var" for e in out["events"]))

    # 2) 英超 /commentary（事件在正文后跟分钟行）
    pl_path = FIXTURES / "pages/premierleague-commentary.md"
    if not pl_path.exists():
        # 缺夹具必须算 FAIL，不许静默不跑——否则末行仍打「自检：21/21 通过」，
        # 覆盖度丢了却看不出来（数量变小 ≠ 少跑了什么）。
        check("premierleague: /commentary 夹具存在", False, str(pl_path))
    else:
        evs = parse_premierleague_commentary(pl_path.read_text(encoding="utf-8"))
        goals = [e for e in evs if e["kind"] == "goal"]
        check("premierleague: commentary 解析出进球 16' Havertz",
              bool(goals) and goals[0]["minute"] == 16 and goals[0].get("player") == "Kai Havertz",
              f"{[(g['clock'], g.get('player'), g.get('assist')) for g in goals]}")
        check("premierleague: commentary 解析出换人/黄牌",
              any(e["kind"] == "substitution" for e in evs) and
              any(e["kind"] == "card" and e.get("card") == "yellow" for e in evs),
              f"{sorted({e['kind'] for e in evs})}")

    # 3) 巴黎赛程页：日期定序、L1 口径
    psg_fx = FIXTURES / "pages/psg-fixtures-oct.md"
    if not psg_fx.exists():
        check("psg.fr: 赛程页夹具存在", False, str(psg_fx))
    else:
        cands = parse_psg_fixtures(psg_fx.read_text(encoding="utf-8"), date(2026, 11, 2))
        best, _ = select_latest(cands, date(2026, 11, 2), "league", ["Ligue 1"])
        check("psg.fr: 最新 L1 = 2026-10-30 勒阿弗尔 1-5",
              bool(best) and best["date"] == "2026-10-30" and best["score"] == "1-5",
              f"{best}")
        check("psg.fr: 未来场次不参与评选",
              best is not None and best["date"] < "2026-11-02")

    # 4) 选取逻辑：日期优先于页面顺序
    fake = [
        {"date": "2026-10-25", "score": "2-2", "source_line": 90},
        {"date": "2026-10-31", "score": "6-1", "source_line": 12},
        {"date": None, "score": "1-0", "source_line": 3},
        {"date": "2026-11-05", "score": "3-0", "source_line": 5},
    ]
    best, undated = select_latest(fake, date(2026, 11, 2), "league")
    check("select_latest: 日期优先且剔除未来",
          bool(best) and best["date"] == "2026-10-31" and len(undated) == 1,
          f"输入含未来场 2026-11-05（带比分），取 {best and best['date']}")
    check("select_latest: 有比分的候选不标未完赛",
          bool(best) and not best.get("unfinished"))

    # 5) 负例：全部候选都没有比分 → 显式标未完赛，不冒充「最新已完赛」
    best_u, _ = select_latest(
        [{"date": "2026-11-01", "score": None, "url": "u", "source_line": 1}],
        date(2026, 11, 2), "league")
    check("select_latest: 无比分时标 unfinished",
          bool(best_u) and best_u.get("unfinished") is True)

    # 6) 同场判别：URL 归一 + 队名/比分对内容，不对 URL 字符串
    a = {"date": "2026-10-31", "home": "FC Barcelona", "away": "Deportivo Alavés",
         "score": "6-1", "url": "https://X.com/match/a?utm=feed"}
    b = {"date": "2026-10-31", "home": "FC Barcelona", "away": "Deportivo Alaves",
         "score": "6-1", "url": "https://X.com/match/a/"}
    c = {"date": "2026-10-31", "home": "Real Madrid", "away": "Girona",
         "score": "2-0", "url": "https://x/match/b"}
    check("_norm_url: query/尾斜杠/主机大小写不产生重复",
          _norm_url(a["url"]) == _norm_url(b["url"]),
          f"{_norm_url(a['url'])} vs {_norm_url(b['url'])}")
    check("_same_match: 变音符与 URL 差异不算不同比赛", _same_match(a, b))
    check("_same_match: 同日不同对阵是真冲突", not _same_match(a, c))
    check("_same_match: 队名认不出来证明不了同场（fail-closed）",
          not _same_match(a, {"date": "2026-10-31", "score": "6-1",
                              "home": None, "away": None, "url": "z"}))
    a2, b2, c2 = ({**a, "_surface": "s1"}, {**b, "_surface": "s2"}, {**c, "_surface": "s2"})
    check("corroborating_surfaces: 同场不同 URL 算印证",
          corroborating_surfaces([a2, b2, c2], a2) == {"s1", "s2"})
    check("corroborating_surfaces: 只有一个面不算交叉核对",
          corroborating_surfaces([a2, c2], a2) == {"s1"})
    check("corroborating_surfaces: 两个面但没有同场记录不算印证",
          corroborating_surfaces([a2, c2], a2) != {"s1", "s2"})

    bad = sum(1 for _, ok, _ in checks if not ok)
    print()
    print(f"自检：{len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def resolve_targets(keys: list[str], asof: date, scope: str,
                    dry_run: bool = False,
                    allow_unfinished: bool = False) -> tuple[dict, list[str]]:
    """批量解析。每支队伍独立成败——一支失败不拖垮其他三支。"""
    out: dict = {"asof": asof.isoformat(), "scope": scope, "teams": {}}
    failed: list[str] = []
    for key in keys:
        try:
            ctx = resolve(key, asof, scope, dry_run=dry_run,
                          allow_unfinished=allow_unfinished)
        except ResolveError as exc:
            ctx = {"resolved": False, "error": str(exc)}
        out["teams"][key] = ctx
        if not ctx.get("resolved"):
            failed.append(key)
    out["all_resolved"] = not failed
    out["unresolved"] = failed
    return out, failed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="match-recap-video「当前赛季最新一场」解析器",
        epilog="队伍 key 与口径走位置参数（skill 本地脚本的私有参数不进库层旗标词表）。")
    ap.add_argument("team", nargs="?", help="teams.json 里的队伍 key")
    ap.add_argument("scope", nargs="?", choices=["league", "all"], default="league",
                    help="league = 只看联赛（默认）；all = 含杯赛/欧战（口径不同）")
    ap.add_argument("asof", nargs="?", help="基准日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--asof", dest="asof_opt", help="基准日（批量模式必须用这个；位置参数留给单队调用）")
    ap.add_argument("--targets", help="批量解析：逗号分隔的球队 key（如 barcelona,dortmund,liverpool,psg）")
    ap.add_argument("--all-targets", action="store_true",
                    help="批量解析 teams.json 里 role=target 的全部球队")
    ap.add_argument("--out", help="fact pack 输出路径（默认打到 stdout）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要抓的 URL，不联网")
    ap.add_argument("--allow-unfinished", action="store_true",
                    help="最新一场还没有比分时仍出 fact pack（带 unfinished 标记）；默认拒绝，不冒充已完赛")
    ap.add_argument("--match-url", help="手动指定官方比赛页 URL（跳过发现面，用于官方赛程面答不了的联赛）")
    ap.add_argument("--selftest", action="store_true", help="离线跑夹具")
    args = ap.parse_args(argv)

    if args.selftest or args.team == "selftest":
        return selftest()

    asof_raw = args.asof_opt or args.asof
    asof = date.fromisoformat(asof_raw) if asof_raw else date.today()
    teams, _ = load_registry() if (args.targets or args.all_targets) else ({}, {})

    if args.all_targets:
        keys = [k for k, v in teams.items() if v.get("role") == "target"]
    elif args.targets:
        keys = [k.strip() for k in args.targets.split(",") if k.strip()]
    else:
        keys = []

    if keys:
        unknown = [k for k in keys if k not in teams]
        if unknown:
            print(json.dumps({"resolved": False,
                              "error": f"未知球队 {unknown}；可选：{', '.join(sorted(teams))}"},
                             ensure_ascii=False, indent=2))
            return 2
        out_ctx, failed = resolve_targets(keys, asof, args.scope, dry_run=args.dry_run,
                                          allow_unfinished=args.allow_unfinished)
        text = json.dumps(out_ctx, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"fact packs → {args.out}")
        else:
            print(text)
        return 0 if not failed else 1

    if not args.team:
        ap.print_help()
        return 2

    try:
        ctx = resolve(args.team, asof, args.scope, dry_run=args.dry_run,
                      match_url=args.match_url, allow_unfinished=args.allow_unfinished)
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
