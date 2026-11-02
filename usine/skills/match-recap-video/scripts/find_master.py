#!/usr/bin/env python3
"""find_master.py — 按 fact pack 找官方集锦母版（候选 + 排序 + 可选下载）。

不是「自动选一条视频就用」：集锦标题常带情绪词、频道有仿冒、时长差 10 倍。
本脚本做的是**把候选和证据摆出来**，官方频道优先、extended highlights 次之；
最终冻结哪条仍由人拍板（`--download` 只在显式要求时执行）。

用法：
    python3 find_master.py barcelona --fact-pack pack.json
    python3 find_master.py barcelona --asof 2026-11-02          # 内部先跑 resolve_match
    python3 find_master.py psg --fact-pack pack.json --download masters/
    python3 find_master.py --query "Le Havre 1-5 PSG highlights" \
        --official-channel https://www.youtube.com/@PSG

依赖：yt-dlp（PATH 里有即可）。没有就退出非零并说明——不猜链接。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve_match import ResolveError, load_registry, resolve  # noqa: E402


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _handle_from_url(url: str | None) -> str | None:
    """从频道 URL 取 handle：@PSG / user/laliga / c/LiverpoolFC / youtube.com/premierleague 都认。"""
    if not url:
        return None
    m = re.search(r"/@([^/?#]+)", url)
    if not m:
        m = re.search(r"/(?:user|c|channel)/([^/?#]+)", url)
    if not m:
        m = re.search(r"youtube\.com/([^/?#]+)", url)
    return _norm(m.group(1)) if m else None


def _official_handles(team: dict, league_meta: dict | None) -> set[str]:
    handles: set[str] = set()
    league_meta = league_meta or {}
    hl = league_meta.get("highlights") or {}
    urls = [(team.get("official_channel") or {}).get("youtube"),
            hl.get("channel_url") or league_meta.get("channel_url")]
    urls.extend(hl.get("official_channels") or [])
    for url in urls:
        h = _handle_from_url(url)
        if h:
            handles.add(h)
    return handles


def _is_official(entry: dict, handles: set[str]) -> bool:
    """只认精确的 handle / 频道 id。

    不能用子串：Sky Sports Premier League 的频道名里也含 premierleague，
    子串匹配会把媒体号当成官方号。"""
    if not handles:
        return False
    ids = {_norm(entry.get("uploader_id")), _norm(entry.get("channel_id"))}
    names = {_norm(entry.get("channel")), _norm(entry.get("uploader"))}
    for h in handles:
        if h in ids:
            return True
        if any(n == h or n in (h + "official", h + "tv", h + "fc") for n in names):
            return True
    return False


def _score(entry: dict, handles: set[str], match: dict) -> tuple[int, list[str]]:
    title = (entry.get("title") or "").lower()
    duration = entry.get("duration") or 0
    score = match.get("score")
    points = 0
    reasons: list[str] = []

    if _is_official(entry, handles):
        points += 100
        reasons.append("官方频道 +100")
    if "highlight" in title:
        points += 40
        reasons.append("标题含 highlight +40")
    if "extended" in title:
        points += 25
        reasons.append("extended +25")

    # 比分是硬判据：同一天/同一对手的标题可能写成反向比分（1-0 vs 0-1），
    # 官方频道里也会有别的场次。比分对上才加，写反了直接压下去。
    if score:
        variants = {score, score.replace("-", " "), score.replace("-", ":")}
        if any(v in title for v in variants):
            points += 30
            reasons.append("标题比分与官方一致 +30")
        else:
            other = re.search(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b", title)
            if other and f"{other.group(1)}-{other.group(2)}" != score:
                points -= 50
                reasons.append(f"标题比分 {other.group(0)} 与官方 {score} 不一致 -50")

    for side in ("home", "away"):
        name = (match.get(side) or "").lower()
        token = next((w for w in re.split(r"\W+", name) if len(w) >= 4), "")
        if token and token in title:
            points += 10
            reasons.append(f"标题含 {token} +10")
    if 300 <= duration <= 1500:
        points += 20
        reasons.append(f"{duration}s（适合 8 分钟成片）+20")
    elif 120 <= duration < 300:
        points += 5
        reasons.append(f"{duration}s（偏短）+5")
    elif duration and duration < 90:
        points -= 30
        reasons.append(f"{duration}s（短片）+/-30")
    if "full match" in title or "full game" in title:
        points -= 40
        reasons.append("full match -40（不是集锦）")
    if "shorts" in title or "#shorts" in title:
        points -= 30
        reasons.append("shorts -30")
    return points, reasons


def _search(query: str, limit: int) -> list[dict]:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise ResolveError("PATH 里没有 yt-dlp；装好后重跑。没有 yt-dlp 就不猜链接。")
    cmd = [exe, "--flat-playlist", "-J", f"ytsearch{limit}:{query}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        raise ResolveError(f"YouTube 搜索超时：{query}") from exc
    if proc.returncode != 0:
        raise ResolveError(f"yt-dlp 搜索失败：{query}\n{proc.stderr[-500:]}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ResolveError(f"yt-dlp 输出不是 JSON：{query}") from exc
    out: list[dict] = []
    for e in payload.get("entries") or []:
        if not e or not e.get("id"):
            continue
        out.append({
            "id": e.get("id"),
            "title": e.get("title"),
            "channel": e.get("channel") or e.get("uploader"),
            "uploader_id": e.get("uploader_id"),
            "duration": e.get("duration"),
            "url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
        })
    return out


def _fact_pack(team_key: str, asof: date, scope: str) -> dict:
    return resolve(team_key, asof, scope)


def _query_from_pack(pack: dict) -> tuple[str, dict]:
    meta = (pack.get("match_page") or {}).get("meta") or {}
    pick = pack.get("latest_pick") or {}
    home = meta.get("home") or pick.get("home") or pick.get("home_slug")
    away = meta.get("away") or pick.get("away") or pick.get("away_slug")
    score = meta.get("score") or pick.get("score")
    bits = [x for x in (home, score, away, "highlights") if x]
    return " ".join(bits), {"home": home, "away": away, "score": score,
                            "date": pick.get("date")}


def _download(entry: dict, out_dir: Path) -> str:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise ResolveError("PATH 里没有 yt-dlp，无法下载。")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "%(title).120B [%(id)s].%(ext)s"
    cmd = [exe, "-f", "bv*+ba/b", "--no-playlist", "-o", str(target),
           entry["url"]]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ResolveError(f"下载失败：{entry['url']}\n{proc.stderr[-800:]}")
    # yt-dlp 不回报最终文件名，按 id 在目录里找。
    # ⚠️ 不能用 glob：`[id]` 在 glob 里是字符类，匹配不到字面量的方括号。
    hits = sorted(p for p in out_dir.iterdir() if f"[{entry['id']}]" in p.name)
    return str(hits[-1]) if hits else str(out_dir)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="找官方集锦母版（候选 + 排序）")
    ap.add_argument("team", nargs="?", help="teams.json 里的队伍 key（用 --query 时可省）")
    ap.add_argument("--fact-pack", help="已有 fact pack JSON（省一次抓取）")
    ap.add_argument("--asof", help="基准日 YYYY-MM-DD（未给 fact pack 时使用）")
    ap.add_argument("scope", nargs="?", choices=["league", "all"], default="league")
    ap.add_argument("--query", help="覆盖检索词；可重复调用 --query 组合多个检索")
    ap.add_argument("--official-channel", action="append", default=[],
                    help="额外官方频道 URL（可重复）")
    ap.add_argument("--limit", type=int, default=8, help="每个检索词取前 N 条（默认 8）")
    ap.add_argument("--download", help="下载选中母版到该目录（显式要求才执行）")
    args = ap.parse_args(argv)

    teams, leagues = load_registry()
    pack: dict = {}
    team: dict = {}
    league_meta: dict = {}

    if args.fact_pack:
        pack = json.loads(Path(args.fact_pack).read_text(encoding="utf-8"))
        # 单队 fact pack 与 --all-targets 的批量包都吃
        if "teams" in pack:
            batch = pack["teams"]
            key = args.team or (next(iter(batch)) if len(batch) == 1 else None)
            if key not in batch:
                print(json.dumps({
                    "resolved": False,
                    "error": (f"批量 fact pack 里有多支球队，请用队伍 key 指定："
                              f"{', '.join(sorted(batch))}"),
                }, ensure_ascii=False, indent=2))
                return 2
            pack = batch[key]
        else:
            key = args.team or pack.get("team")
        if key not in teams:
            print(json.dumps({"resolved": False,
                              "error": f"fact pack 里没有可识别的 team（{key!r}）"},
                             ensure_ascii=False, indent=2))
            return 2
        team = teams[key]
        league_meta = leagues.get(team.get("league"), {})
    elif args.team:
        if args.team not in teams:
            print(json.dumps({"resolved": False,
                              "error": f"未知球队 {args.team!r}；可选：{', '.join(sorted(teams))}"},
                             ensure_ascii=False, indent=2))
            return 2
        key = args.team
        team = teams[key]
        league_meta = leagues.get(team.get("league"), {})
        asof = date.fromisoformat(args.asof) if args.asof else date.today()
        try:
            pack = _fact_pack(key, asof, args.scope)
        except ResolveError as exc:
            print(json.dumps({"resolved": False, "error": str(exc)},
                             ensure_ascii=False, indent=2))
            return 2
        if not pack.get("resolved"):
            print(json.dumps({
                "resolved": False,
                "error": "fact pack 没解析出「最新一场」，先修 resolve_match.py 再来找母版",
                "detail": pack.get("reason") or pack.get("error"),
            }, ensure_ascii=False, indent=2))
            return 1
    else:
        key = None

    pack_query, match = _query_from_pack(pack) if pack else ("", {})
    queries = [args.query] if args.query else []
    if not queries and pack_query:
        queries.append(pack_query)
        # 第二个检索词专门找 extended；很多官方频道把 8–10 分钟版单独发
        if "extended" not in pack_query.lower():
            queries.append(pack_query.replace("highlights", "extended highlights"))
    if not queries:
        ap.print_help()
        return 2

    handles = _official_handles(team, league_meta)
    for url in args.official_channel:
        h = _handle_from_url(url)
        if h:
            handles.add(h)

    candidates: dict[str, dict] = {}
    errors: list[str] = []
    for q in queries:
        try:
            for e in _search(q, args.limit):
                e["query"] = q
                if e["id"] not in candidates:
                    candidates[e["id"]] = e
        except ResolveError as exc:
            errors.append(str(exc))

    ranked = []
    for e in candidates.values():
        pts, why = _score(e, handles, match)
        e.update({"official": _is_official(e, handles), "score_points": pts,
                  "reasons": why})
        ranked.append(e)
    ranked.sort(key=lambda x: (-x["score_points"], -(x.get("duration") or 0)))

    for i, e in enumerate(ranked, 1):
        e["rank"] = i

    warnings: list[str] = []
    if not ranked:
        warnings.append("没有搜到候选：换检索词，或把 --limit 调大。")
    elif not ranked[0]["official"]:
        warnings.append("排名第一的不是已注册的官方频道；先人工核对频道，再冻结母版。")
    if ranked and (ranked[0].get("duration") or 0) < 180:
        warnings.append("排名第一的候选不足 3 分钟，做 8 分钟成片会很紧；优先找 extended highlights。")

    chosen = ranked[0] if ranked else None
    result = {
        "team": key,
        "match": match,
        "queries": queries,
        "official_handles": sorted(handles),
        "candidates": ranked,
        "chosen": chosen,
        "warnings": warnings,
        "errors": errors,
    }
    if args.download and chosen:
        try:
            result["downloaded_path"] = _download(chosen, Path(args.download))
        except ResolveError as exc:
            result["download_error"] = str(exc)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ranked else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
