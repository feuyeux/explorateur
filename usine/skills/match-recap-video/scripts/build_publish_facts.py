#!/usr/bin/env python3
"""build_publish_facts.py — 发布描述的数字溯源表（facts.json）。

**为什么要有这张表**：`feuille copy check --facts facts.json` 的「数字可溯源」
判据——读者面（标题 + 正文）里出现的**每一个数字**都要在这张表里找到出处，
否则报「编造规格」。不给 `--facts` 时这道门是 SKIP，**SKIP 不是 PASS**。

**表里的数从哪来**（每一项都有出处，不许手填）：
- fact pack（`resolve_match.py` 的产出）：比分、进球/换人/牌/VAR 计数、轮次、日期；
- 窗口表：窗口数、**逐个**比赛分钟（「第 N 分钟」与「N:SS」两种形态）、分钟上限、
  进球跨度（首球 → 末球经过的分钟数）；
- 成片实测（外部探测器量时长）：时长秒数、成片分钟数、**时长分解**
  （整分 + 余秒——文案写「3 分 12 秒」时，「3」和「12」两个数各要能找到出处）。

**不能出现在文案里的数**（表里没有就是没有出处）：电平、dB、渲染参数之类工艺
数字不进文案；比赛分钟数只有窗口表能推出时才进表（推不出就不许写）。

用法：
    python3 scripts/build_publish_facts.py --pack packs/barcelona.json \\
        --video build/final.mp4 --master master.mp4 --windows windows.json \\
        --out publish/facts.json
    python3 scripts/build_publish_facts.py selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 外部可执行文件（引号里的名字不算硬编码——解析口径见 _need）
FFPROBE = "ffprobe"

# 窗口标题里的比赛分钟：「第4分钟 · 普利西奇破门」「终场 95:03」
MINUTE_RES = (
    re.compile(r"第\s*(\d{1,3})\s*分钟"),
    re.compile(r"(\d{1,3})\s*[:'′]\s*\d{1,2}\b"),
)
ROUND_RE = re.compile(r"(\d{1,3})")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
SCORE_RE = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$")


class ContractError(Exception):
    """输入契约不满足 → 退出码 2。"""


def load_json(path: Path) -> dict:
    if not path.exists():
        raise ContractError(f"文件不存在：{path}")
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"JSON 读不动：{path}（{exc}）") from exc


def _need(binary: str) -> str:
    """解析外部可执行文件。

    优先环境变量覆盖（`FEUILLE_FFPROBE`），否则在 PATH 里找。全仓的跨平台解析
    事实源是 @feuille/core 的 platform resolver；这个脚本是 skill 内的独立
    Python 脚本，用同样的「可覆盖 + 找不到就报错」口径，**不静默拿别的同名
    程序顶替**（口径与同族的 probe_scoreboard.py 一致）。
    """
    env = os.environ.get(f"FEUILLE_{binary.upper()}")
    if env:
        if not Path(env).exists():
            raise ContractError(f"环境变量 FEUILLE_{binary.upper()} 指向的文件不存在：{env}")
        return env
    path = shutil.which(binary)
    if not path:
        raise ContractError(f"找不到 {binary}——装好它，或用 FEUILLE_{binary.upper()} 指定路径。")
    return path


def probe_duration(path: Path) -> float:
    """实测时长（秒）。"""
    if not path.exists():
        raise ContractError(f"文件不存在：{path}")
    exe = _need(FFPROBE)
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise ContractError(f"时长探测失败：{path}（{proc.stderr.strip()[:300]}）")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise ContractError(f"时长探测没给出数：{path}") from exc


def parse_round(raw: object) -> int | None:
    """轮次（"11" / "Matchday 8" / "第 11 轮" → 整数；认不出 → None）。"""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw)
    m = re.search(r"(\d{1,3})", text)
    return int(m.group(1)) if m else None


def parse_score(raw: object) -> tuple[int, int] | None:
    """比分（"6-1" → (6, 1)；认不出 → None）。"""
    if not isinstance(raw, str):
        return None
    m = SCORE_RE.match(raw)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def max_match_minute(windows: list[dict]) -> int | None:
    """窗口表里的最大比赛分钟（「第 N 分钟」/「N:SS」两种形态）。"""
    minutes = all_match_minutes(windows)
    return minutes[-1] if minutes else None


def all_match_minutes(windows: list[dict]) -> list[int]:
    """窗口表里出现过的**全部**比赛分钟（去重升序）。

    「第 N 分钟」与「N:SS」两种形态都收——秒级时刻的分钟部分也是分钟。
    """
    found: set[int] = set()
    for w in windows:
        chunks = [str(w.get("title") or ""), str(w.get("stat") or ""),
                  str(w.get("say") or ""), str(w.get("key") or "")]
        for chunk in chunks:
            for rx in MINUTE_RES:
                for hit in rx.findall(chunk):
                    found.add(int(hit))
    return sorted(found)


def duration_parts(duration: float) -> dict[str, float]:
    """成片时长的分解写法。

    文案里写「3 分 12 秒」时，机检是**按数字**对账的——「3」「12」两个数各
    要有出处。所以时长除了总秒数，还要给出「整分」与「余秒」两个分量。
    """
    whole = int(duration // 60)
    return {
        "duration_minutes_floor": whole,
        "duration_seconds_in_minute": round(duration - whole * 60, 1),
    }


def season_years(date_text: str | None) -> tuple[int, int] | None:
    """赛季年（"2026-10-31" → (2026, 2027)）。

    口径：欧洲赛季跨年，7 月起算新赛季（五大联赛都是 8 月开赛，7 月起的整数月
    都在夏窗内）。**只推算，不手填**——推不出就不写年份进文案。
    """
    if not date_text:
        return None
    m = DATE_RE.search(str(date_text))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    return (year, year + 1) if month >= 7 else (year - 1, year)


def build_facts(pack: dict, duration: float | None, master: float | None,
                windows: list[dict] | None) -> dict:
    """事实表：键 → 可核对的数（值的形态要能被 copy check 的 factNumbers 收）。"""
    pick = pack.get("latest_pick") or {}
    score = parse_score(pick.get("score"))
    if score is None:
        raise ContractError(
            "fact pack 里没有可解析的比分（latest_pick.score）——"
            "未解析出比赛的 pack 不许出发布词")
    counts = pack.get("event_counts") or {}

    facts: dict[str, object] = {
        "score_home": score[0],
        "score_away": score[1],
    }
    for key, out_key in (("goal", "goals"), ("substitution", "substitutions"),
                         ("card", "cards"), ("var", "var_events"),
                         ("penalty", "penalties"), ("whistle", "whistles")):
        val = counts.get(key)
        if isinstance(val, int):
            facts[out_key] = val

    rnd = parse_round(pick.get("round"))
    if rnd is not None:
        facts["round"] = rnd

    date_text = pick.get("date")
    if date_text:
        m = DATE_RE.search(str(date_text))
        if m:
            facts["date_year"] = int(m.group(1))
            facts["date_month"] = int(m.group(2))
            facts["date_day"] = int(m.group(3))
        years = season_years(str(date_text))
        if years:
            facts["season_start"] = years[0]
            facts["season_end"] = years[1]

    if duration is not None:
        facts["duration_seconds"] = round(duration, 1)
        facts["recap_minutes"] = round(duration / 60)
        facts.update(duration_parts(duration))
    if master is not None:
        facts["master_seconds"] = round(master, 1)
    if windows is not None:
        facts["windows"] = len(windows)
        minutes = all_match_minutes(windows)
        if minutes:
            facts["match_minutes"] = minutes[-1]
            # 逐分钟出處：文案里「第 23 分钟」这种写法要能对账
            for minute in minutes:
                facts[f"minute_{minute}"] = minute
            # 进球跨度：首球到末球经过的分钟数（「用了 51 分钟完成反超」这类）
            if len(minutes) >= 2:
                facts["goal_span_minutes"] = minutes[-1] - minutes[0]
    return facts


def load_windows(path: Path | None) -> list[dict] | None:
    if path is None:
        return None
    data = load_json(path)
    if isinstance(data, dict):
        data = data.get("windows", [])
    if not isinstance(data, list):
        raise ContractError(f"窗口表不是列表：{path}")
    return data


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()

    ap = argparse.ArgumentParser(description="发布描述的数字溯源表（facts.json）")
    ap.add_argument("--pack", help="fact pack JSON")
    ap.add_argument("--video", help="成片 mp4（用来量时长）")
    ap.add_argument("--master", help="母版 mp4（用来量时长）")
    ap.add_argument("--windows", help="窗口表 JSON")
    ap.add_argument("--out", default="publish/facts.json", help="输出路径")
    args = ap.parse_args(argv)

    try:
        if not args.pack:
            raise ContractError("要 --pack（fact pack）")
        pack = load_json(Path(args.pack))
        duration = probe_duration(Path(args.video)) if args.video else None
        master = probe_duration(Path(args.master)) if args.master else None
        windows = load_windows(Path(args.windows)) if args.windows else None
        facts = build_facts(pack, duration, master, windows)
    except ContractError as exc:
        print(f"❌ 输入契约不满足：{exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(facts, ensure_ascii=False, indent=2), "utf-8")
    print(f"事实表 {len(facts)} 项 → {out}")
    for key, val in facts.items():
        print(f"  {key:<18} {val}")
    print("\n下一步：`feuille copy check publish/ --facts " + str(out) + "`")
    return 0


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def _pack() -> dict:
    return {
        "latest_pick": {"score": "6-1", "round": "11", "date": "2026-10-31",
                        "home": "FC Barcelona", "away": "Deportivo Alaves"},
        "event_counts": {"goal": 7, "substitution": 10, "card": 5, "var": 1},
    }


def selftest() -> int:
    passed = 0
    failed: list[str] = []

    def case(name: str, fn) -> None:
        nonlocal passed
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except AssertionError as exc:
            failed.append(name)
            print(f"  ❌ {name}：{exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  ❌ {name}：{type(exc).__name__} {exc}")

    def expect_raises(exc_type, fn) -> None:
        try:
            fn()
        except exc_type:
            return
        raise AssertionError(f"应当抛 {exc_type.__name__}，却没抛")

    def t_round():
        assert parse_round("11") == 11
        assert parse_round("Matchday 8") == 8
        assert parse_round("第 11 轮") == 11
        assert parse_round(None) is None
        assert parse_round("无") is None
    case("轮次解析：三种写法都认，认不出给 None", t_round)

    def t_score():
        assert parse_score("6-1") == (6, 1)
        assert parse_score(" 2 - 2 ") == (2, 2)
        assert parse_score(None) is None
        assert parse_score("未完赛") is None
    case("比分解析：认得出才给数", t_score)

    def t_minute():
        wins = [{"title": "第4分钟 · 普利西奇破门"}, {"title": "终场 95:03"}]
        assert max_match_minute(wins) == 95, max_match_minute(wins)
        assert max_match_minute([]) is None
    case("比赛分钟上限：从窗口标题里取", t_minute)

    def t_season():
        assert season_years("2026-10-31") == (2026, 2027)
        assert season_years("2026-03-15") == (2025, 2026)
        assert season_years(None) is None
    case("赛季年：7 月起算跨年", t_season)

    def t_facts():
        facts = build_facts(_pack(), 485.48, 485.48,
                            [{"title": "第4分钟 · 破门"}, {"title": "终场"}])
        assert facts["score_home"] == 6 and facts["score_away"] == 1
        assert facts["goals"] == 7 and facts["substitutions"] == 10
        assert facts["round"] == 11
        assert facts["date_day"] == 31 and facts["date_month"] == 10
        assert facts["season_start"] == 2026 and facts["season_end"] == 2027
        assert facts["recap_minutes"] == 8, facts["recap_minutes"]
        assert facts["windows"] == 2
        assert facts["match_minutes"] == 4, facts["match_minutes"]
        assert facts["minute_4"] == 4
    case("事实表：比分 / 计数 / 轮次 / 日期 / 时长 / 分钟", t_facts)

    def t_minutes_and_span():
        wins = [{"title": "第18分钟 · 马贾破门"}, {"title": "第26分钟 · 扳平"},
                {"title": "第69分钟 · 戴帽"}]
        facts = build_facts(_pack(), 330.09, None, wins)
        assert facts["minute_18"] == 18
        assert facts["minute_69"] == 69
        assert facts["match_minutes"] == 69
        assert facts["goal_span_minutes"] == 51, facts["goal_span_minutes"]
    case("逐分钟出處 + 进球跨度（首球→末球）", t_minutes_and_span)

    def t_single_goal_no_span():
        wins = [{"title": "第16分钟 · 哈弗茨破门"}]
        facts = build_facts(_pack(), 120.0, None, wins)
        assert "goal_span_minutes" not in facts, facts
    case("反向：只有一球就不给跨度（0 不是跨度）", t_single_goal_no_span)

    def t_duration_parts():
        parts = duration_parts(192.34)
        assert parts["duration_minutes_floor"] == 3, parts
        assert abs(parts["duration_seconds_in_minute"] - 12.3) < 0.05, parts
        facts = build_facts(_pack(), 192.34, None, [{"title": "第8分钟 · 破门"}])
        assert facts["duration_minutes_floor"] == 3
        assert round(facts["duration_seconds_in_minute"]) == 12, facts
    case("时长分解：整分 + 余秒（「3 分 12 秒」两个数各有着落）", t_duration_parts)

    def t_facts_bad_pack():
        expect_raises(ContractError, lambda: build_facts({"latest_pick": {}}, None, None, None))
    case("反向：pack 没解析出比赛 → 拒出事实表", t_facts_bad_pack)

    def t_numbers_are_py_floatable():
        # copy check 的 factNumbers 只收「Python float() 收得下」的值
        facts = build_facts(_pack(), 485.48, None, None)
        py = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
        for key, val in facts.items():
            if isinstance(val, bool):
                continue
            if isinstance(val, str):
                assert py.match(val.strip()), f"{key}={val!r} 不被 factNumbers 收"
            else:
                assert isinstance(val, (int, float)), f"{key}={val!r} 类型不对"
    case("事实表的每个值都落在 factNumbers 的接受面内", t_numbers_are_py_floatable)

    print(f"\n{'通过' if not failed else '未通过'}：{passed}/{passed + len(failed)}")
    if failed:
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
