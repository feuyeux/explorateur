#!/usr/bin/env python3
"""latency_budget.py — 端点时延预检（latency preflight）：开跑前先看历史，别用运气开波。

为什么这个模块存在
------------------
网关首响应时延在**同档位同输入**下实测波动巨大：50.6s / 108.2s / 138.7s / 322s /
>300s（见 ``garage/probe_curriculum_effort.py`` 与 curriculum-usine.yaml 的注释）。
而出题席的切片是 280s（Phase-1）——**切片吸收不了波动**：运气差的时候，一次首响应
就能把整条切片吃光，然后验证席没出版报告 → 整波失败（引擎语义：没有判决 = 整波失败）。

所以规矩是：**开跑前先看历史**。本模块读**已经记录下来的**席位耗时，算出每个席位的
p50 / max，与本波**计划切片**比一比；历史 max 超过切片的某个比例（默认 60%）就判
「高时延风险」，默认**拒绝开跑**，并报出是哪一席、历史 max 多少、计划切片多少、
该怎么办。

硬约束：preflight 必须**零成本**
------------------------------
本模块**不发任何 LLM 请求**，只读磁盘上已经写好的历史记录。preflight 的定义是
「只读：就绪载荷，不写不烧」，时延判断不能为了「测一下」而先烧一轮——那正好是
它要防的事。

数据来源（**实测，不是推断**）
------------------------------
引擎每跑完一个 seat segment，就在那个 segment 目录里写一个 ``result.json``，
内容是 ``dataclasses.asdict(core.loop.LoopResult)``，其中 ``wall_secs`` 是该段
**实测**耗时。落盘位置（相对 run root）：

* ``curriculum/wave_<NNN>/segment_<NNN>/result.json``   → 出题席
  （``explore/phase1_wave.py:259`` 的 ``sink.save_result(...)``）
* ``episodes/ep<NNN>/actor/attempt_<NNN>/segment_<NNN>/result.json``   → Actor 席
* ``episodes/ep<NNN>/verifier/cycle_<NNN>/segment_<NNN>/result.json``   → 验证席
* ``episodes/ep<NNN>/memory_distillation/segment_<NNN>/result.json``   → 记忆席
* ``episodes/ep<NNN>/memory_reconciliation/segment_<NNN>/result.json`` → 记忆席

（``explore/practice_loop.py:633`` 写的是同一份 LoopResult dump，落在同样的
``segment_<NNN>/`` 目录下；Phase-1 与 DRS 两条路径的落盘形状一致。）

历史 run root = ``--root`` 指定的 runs 根目录下的 ``<lineage>/phase1`` 与
``<lineage>/phase2`` 兄弟目录。

失败策略（fail-closed）
----------------------
* 历史里某条记录**坏了**（JSON 读不出、不是对象、缺 ``wall_secs``、值非有限数）
  → **不**当成 0（当成 0 就等于「没风险」，那正是最危险的误判）→ 直接判高时延风险，
  并点名是哪个文件坏了。
* 历史**不存在**（第一次跑）→ 判「无历史」，**不拒绝**，但载荷里如实写
  ``latency_history: "none"``。没历史不等于没风险，只是没证据。
* 高时延风险成立 → 默认**拒绝开跑**（fail-closed）。要跑就显式给
  ``--allow-high-latency``，风险会被写进 manifest——**不能默默放行**。
"""

from __future__ import annotations

import dataclasses
import json
import math
import statistics
from pathlib import Path

# 风险比例：某席位的历史 max 超过本波计划切片的这个比例，就判高时延风险。
# 60% 的由来：切片的定位是「盖住一次最差往返 + 后续编辑轮」；历史 max 一旦吃掉
# 六成，剩下的四成就装不下第二件东西了。这是一条保守线，operator 可以用
# --allow-high-latency 放行（风险会进 manifest）。
DEFAULT_RISK_RATIO = 0.6

# 参与判定的席位（merge 是宿主侧动作，没有实测席位耗时）。
SEAT_NAMES = ("curriculum", "actor", "verifier", "memory")

# 一次扫描最多看多少个历史 run root（防一个塞满垃圾的 runs 目录把装配期拖死）。
MAX_HISTORY_ROOTS = 64


class LatencyHistoryError(RuntimeError):
    """历史时延记录坏了（读不出 / 缺字段）。"""


@dataclasses.dataclass(frozen=True)
class LatencyConfig:
    """时延预检的旋钮。"""

    risk_ratio: float = DEFAULT_RISK_RATIO
    max_roots: int = MAX_HISTORY_ROOTS

    def to_dict(self) -> dict:
        return {"risk_ratio": self.risk_ratio,
                "max_roots": self.max_roots}


# ------------------------------------------------------------- 历史采集

def _seat_of(relative: Path) -> str | None:
    """从 run root 相对路径认出这是哪个席的 segment 结果。"""
    parts = relative.parts
    if not any(part.startswith("segment_") for part in parts):
        return None
    if parts and parts[0] == "curriculum":
        return "curriculum"
    if parts and parts[0] == "episodes":
        for marker, seat in (("actor", "actor"),
                             ("verifier", "verifier"),
                             ("memory_distillation", "memory"),
                             ("memory_reconciliation", "memory")):
            if marker in parts:
                return seat
    return None


def _read_wall_secs(path: Path) -> tuple[float | None, str]:
    """读一份 segment result.json 里的实测耗时。

    返回 ``(值, "")`` 或 ``(None, 原因)``。**不做静默兜底**：坏记录必须被点名，
    绝不能变成 0（0 会被读成「没有风险」）。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, f"unreadable: {exc}"
    try:
        record = json.loads(raw)
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(record, dict):
        return None, "not a JSON object"
    value = record.get("wall_secs")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "missing or non-numeric wall_secs"
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None, "wall_secs is not a finite number"
    if number < 0:
        return None, "negative wall_secs"
    return number, ""


def _run_roots(runs_root: Path) -> list[Path]:
    """列出 runs 根目录下的历史 run root（``<lineage>/phase1|phase2``）。

    传入的目录本身就是一个 run root 时（里面有 ``episodes/`` 或 ``curriculum/``），
    它自己也算一个——这样模块既能吃整棵 runs 目录，也能吃单个 run root。
    """
    runs_root = Path(runs_root)
    if not runs_root.is_dir():
        return []
    roots: list[Path] = []
    if ((runs_root / "episodes").is_dir()
            or (runs_root / "curriculum").is_dir()):
        roots.append(runs_root)
    try:
        lineages = sorted(entry for entry in runs_root.iterdir()
                          if entry.is_dir())
    except OSError:
        return roots
    for lineage in lineages:
        for phase in ("phase1", "phase2"):
            candidate = lineage / phase
            if candidate.is_dir():
                roots.append(candidate)
    return roots


def _collect_run(run_root: Path) -> tuple[dict, list]:
    """扫一个 run root，收集每席的 segment 实测耗时与每席合计。"""
    segments: dict = {}
    totals: dict = {}
    corrupt: list = []
    for base in ("curriculum", "episodes"):
        directory = run_root / base
        if not directory.is_dir():
            continue
        try:
            paths = sorted(directory.rglob("result.json"))
        except OSError as exc:
            corrupt.append({"file": str(directory), "reason": f"unreadable: {exc}"})
            continue
        for path in paths:
            relative = path.relative_to(run_root)
            seat = _seat_of(relative)
            if seat is None:
                continue
            value, reason = _read_wall_secs(path)
            if value is None:
                corrupt.append({"file": str(path), "reason": reason})
                continue
            segments.setdefault(seat, []).append(value)
            totals[seat] = totals.get(seat, 0.0) + value
    return {"segments": segments, "totals": totals}, corrupt


def collect_history(runs_root: Path,
                    config: LatencyConfig | None = None) -> dict:
    """读历史 run root，返回每席的实测样本、合计与坏记录清单。"""
    config = config or LatencyConfig()
    roots = _run_roots(Path(runs_root))[:config.max_roots]
    samples: dict = {}
    totals: dict = {}
    corrupt: list = []
    for root in roots:
        collected, broken = _collect_run(root)
        for seat, values in collected["segments"].items():
            samples.setdefault(seat, []).extend(values)
        for seat, value in collected["totals"].items():
            totals[seat] = max(totals.get(seat, 0.0), value)
        for entry in broken:
            corrupt.append(entry)
    return {
        "runs_root": str(runs_root),
        "runs_scanned": len(roots),
        "samples": samples,
        "totals": totals,
        "corrupt": corrupt,
    }


# ------------------------------------------------------------- 判定

def _p50(values: list) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def assess(*, runs_root: Path, slices: dict, applied: dict | None = None,
           config: LatencyConfig | None = None,
           allow_high_latency: bool = False) -> dict:
    """判定本波的高时延风险。

    ``slices`` = 本波计划切片（seat → 秒），``applied`` = 装配后真正生效的席位实际耗时
    （切片是天花板，席位自己声明的更紧值不会被放松）。

    返回的载荷里：
    * ``latency_history`` = ``"none"``（没有任何历史）或 ``"measured"``；
    * ``risk`` = ``"none"`` 或 ``"high"``；
    * ``reason`` = 人读的结论（哪一席、历史 max、计划切片、怎么办）；
    * ``allowed`` = 是否被 ``--allow-high-latency`` 放行（放行时 risk 仍然是 high，
      风险会被写进 manifest，不存在默默放行）。
    """
    config = config or LatencyConfig()
    slices = dict(slices or {})
    applied = dict(applied or {})
    history = collect_history(Path(runs_root), config)
    samples: dict = history["samples"]
    totals: dict = history["totals"]
    corrupt: list = history["corrupt"]

    seats: dict = {}
    findings: list[str] = []
    for seat in SEAT_NAMES:
        planned = slices.get(seat)
        values = list(samples.get(seat) or [])
        seat_total = totals.get(seat)
        entry = {
            "planned_slice_secs": planned,
            "effective_wall_clock_secs": applied.get(seat),
            "segments": len(values),
            "p50_secs": round(_p50(values), 1) if values else None,
            "max_secs": round(max(values), 1) if values else None,
            "max_total_secs": (round(seat_total, 1)
                               if seat_total is not None else None),
            "threshold_secs": (round(planned * config.risk_ratio, 1)
                               if planned else None),
            "verdict": "not_planned",
            "history": "measured" if values else "none",
        }
        if planned is None:
            entry["verdict"] = "not_planned"
            seats[seat] = entry
            continue
        if not values:
            # 没有实测 = 没有证据，不判风险（但如实说没有证据）。
            entry["verdict"] = "no_history"
            seats[seat] = entry
            continue
        threshold = planned * config.risk_ratio
        observed = max(max(values), seat_total or 0.0)
        if observed > threshold:
            entry["verdict"] = "risk"
            findings.append(
                f"{seat}: observed {observed:.1f}s "
                f"(segment max {max(values):.1f}s, seat total "
                f"{(seat_total or 0.0):.1f}s) exceeds "
                f"{config.risk_ratio:.0%} of the planned {planned}s slice "
                f"({threshold:.1f}s)")
        else:
            entry["verdict"] = "ok"
        seats[seat] = entry

    if corrupt:
        # 坏记录 fail-closed：不能当成 0（0 = 没有风险 = 最危险的误判）。
        for entry in corrupt[:5]:
            findings.append(
                f"corrupt latency history: {entry['file']} ({entry['reason']})")
        if len(corrupt) > 5:
            findings.append(f"... and {len(corrupt) - 5} more corrupt record(s)")
        risk = "high"
    else:
        risk = "high" if any(entry["verdict"] == "risk"
                             for entry in seats.values()) else "none"

    has_history = bool(samples)
    if risk == "high":
        reason = (
            "high-latency risk: " + "; ".join(findings) + ". "
            "A slice absorbs variance only up to a point: one worst-case "
            "gateway round trip has been measured at 50.6s, 108.2s, 138.7s, "
            "322s and over 300s, and a stalled request is charged to the "
            "seat's time budget. Options: lower that seat's reasoning_effort, "
            "move the seat to another endpoint, or raise the run ceiling "
            "(--run-ceiling-secs). To run anyway, pass --allow-high-latency; "
            "the risk is then recorded in the manifest."
            + (" The history itself is damaged, so this verdict is "
               "deliberately conservative." if corrupt else ""))
    elif not has_history:
        reason = ("no latency history yet (first run on this runs root): the "
                  "preflight cannot judge the risk, so it does not refuse; "
                  "the run ceiling and the per-seat slices remain the guard.")
    else:
        reason = ("measured latency history is within the planned slices "
                  "(every judged seat's observed elapsed time is at or under "
                  f"{config.risk_ratio:.0%} of its planned slice)")

    return {
        "latency_history": "measured" if has_history else "none",
        "source": ("engine per-segment wall_secs (measured, not inferred)"
                   if has_history else ""),
        "runs_root": str(runs_root),
        "runs_scanned": history["runs_scanned"],
        "risk": risk,
        "ratio": config.risk_ratio,
        "allowed": bool(allow_high_latency),
        "seats": seats,
        "corrupt": corrupt,
        "findings": findings,
        "reason": reason,
    }
