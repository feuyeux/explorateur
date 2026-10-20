#!/usr/bin/env python3
"""spread.py — 铺开闸（spread gate）：机械地让连续的 RSI 波次不能都落在同一个包里。

为什么这个模块存在
------------------
2026-10-20 之前，RSI 自我进化的全部改进都落在同一个文件上：至今 3 次合并进仓库的
改进（6e8665f wave-1、1d550b2 drs-1、eedaf73 wave-1）全部落在
``packages/dsh-plugin/src/tools.ts`` 一个函数的 4 条拒答分支上，而生产线本体
（core / karaoke / poster / poetry / storyteller / copy / bgm / publish）**零改动**。

这不是 Agent 偷懒，是**规格造成的**：`config/roles-usine/curriculum-usine.yaml` 的
``system_extra`` 写着「in menu target A, B or C ONLY」，而 TARGET MENU 的 A–E 全是
``packages/dsh-plugin/**`` 与 ``skills/``，真正的生产线 ``packages/core/src`` 排在 F 且
标着 EXPENSIVE。规格把出题席圈死在一个包里，于是每一波都在同一个局部最优里打转。

`distribution-usine.md` 里那句「把这一波铺到产线的不同区域」的要求是**没有机械约束
的空话**——它扛住了三次连续的单包波次。本模块就是那句话的机械版本：
它读 git 历史，算出哪些包被冷落、哪些包被连着打，把结果**装配进出题席自己的
system_extra**（而不是留成一句建议）。

本模块**不做什么**
-----------------
* 不改仓库：读历史只用 ``git log``，全程只读，绝不 checkout / reset / commit。
* 不决定选题：出题席仍然是作者，本模块只把「哪些包不许碰、哪些包优先」写成硬约束。
* 不碰 DRS 席：Phase 2 有自己的出题席（``curriculum-drs.yaml``），接线在 run_usine 里
  按相位跳过。

口径
----
* 「一个包」= ``packages/<name>/``；落在 ``packages/`` 之外的路径归到顶层三类之一：
  ``skills``、``docs``、``other``。
* 「RSI 合并过的 commit」= commit body 里带 trailer ``X-Theatre-Wave: <n>`` 或
  ``X-Theatre-Drs: <n>`` 的提交（现役代码在 ``wave_merge._commit_candidate`` 里写这两个
  trailer）。单位名 = ``wave-<n>`` / ``drs-<n>``。
* 「冷区（cold）」= **从未**被任何 RSI commit 触及过的包；按产线重要度排序（见
  ``config/spread.json`` 的 ``package_priority``）。「近期冷（cold_recently）」= 最近
  ``cold_window`` 次波次里没被触及过的包。
* 第一次跑（历史里一条 RSI commit 都没有）→ 优雅降级：``render_constraint`` 返回空串，
  不加任何禁入/冷区文本，也不报错。

依赖与平台
----------
只依赖标准库（json / re / subprocess / pathlib），跨 POSIX 与 Windows：路径一律走
``pathlib``，不写死分隔符，不调用 GNU-only 工具（git 是仓库自带，两个底座都有）。
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = HERE / "config" / "spread.json"

# 产线重要度排序（兜底值；权威值在 config/spread.json 的 package_priority 里）。
# 理由写在那份配置的 _comment_package_priority 里：core 是操作员真正跑的代码，
# 其次是四个出片管线包，再次是内容/资产包，然后是操作员外壳与账目门，
# dsh-plugin 排最后——它已经被连着做过三次了。
DEFAULT_PACKAGE_PRIORITY = (
    "core",
    "karaoke",
    "poster",
    "poetry",
    "storyteller",
    "copy",
    "bgm",
    "publish",
    "cli",
    "gate",
    "dsh-plugin",
)

# packages/ 之外的三类顶层单位。
TOP_LEVEL_UNITS = ("skills", "docs", "other")

# RSI commit 的 trailer。X-Theatre-Wave 是广度波次，X-Theatre-Drs 是深度递归，
# 两者都不是普通的人写提交：只有 wave_merge._commit_candidate 会写这两个 trailer。
_TRAILER_RE = re.compile(
    r"^X-Theatre-(Wave|Drs):[ \t]*([0-9]+)[ \t]*$", re.MULTILINE)

# git log 的记录分隔符：\x01 开头一条 commit，\x02 分隔 sha 与 body，\x03 分隔 body
# 与文件列表。commit message 里不可能出现 \x00-\x08 这些控制字符（git 自身禁止 NUL），
# 所以这套分隔是安全的。
_RECORD = "\x01"
_SHA_SEP = "\x02"
_BODY_SEP = "\x03"

# 扫多少条 commit。RSI 合并的提交总是最新的那几条，200 足够覆盖一个仓库的全部
# RSI 历史；上限是为了不让一个有几万次提交的老仓库把装配期拖慢。
_LOG_LIMIT = 200

_GIT_TIMEOUT_SECS = 120


class SpreadError(RuntimeError):
    """铺开状态算不出来（配置坏掉 / git 读不了）。"""


# ----------------------------------------------------------------- 配置

@dataclasses.dataclass(frozen=True)
class SpreadConfig:
    """铺开闸的三个旋钮 + 产线重要度排序。"""

    cold_window: int = 3
    repeat_ban: int = 2
    cold_priority: str = "required"
    package_priority: tuple = DEFAULT_PACKAGE_PRIORITY
    source: str = "builtin_defaults"

    def to_dict(self) -> dict:
        return {
            "cold_window": self.cold_window,
            "repeat_ban": self.repeat_ban,
            "cold_priority": self.cold_priority,
            "package_priority": list(self.package_priority),
            "source": self.source,
        }


def load_config(path: Path | None = None) -> SpreadConfig:
    """读 ``config/spread.json``。

    口径（fail-closed 的分界）：
    * 文件**不在** → 用内置默认值。策略文件是覆盖项，缺它不等于策略未知；
      缺了闸门仍然关着（默认值就是「3 次窗口 / 2 次连击禁入 / 冷区必须去」）。
    * 文件**在但坏了**（JSON 语法错、类型错、值不合法）→ 抛错。坏掉的覆盖项
      绝不能被静默当成默认值：那等于把「有人改过策略」读成「策略没改过」。
    """
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not path.is_file():
        return SpreadConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SpreadError(
            f"铺开策略配置读不了（{path}）：{exc}") from exc
    if not isinstance(raw, dict):
        raise SpreadError(f"铺开策略配置必须是 JSON 对象：{path}")
    cold_window = raw.get("cold_window", 3)
    repeat_ban = raw.get("repeat_ban", 2)
    cold_priority = raw.get("cold_priority", "required")
    priority = raw.get("package_priority", list(DEFAULT_PACKAGE_PRIORITY))
    if not isinstance(cold_window, int) or isinstance(cold_window, bool) \
            or cold_window < 1:
        raise SpreadError(
            f"config/spread.json 的 cold_window 必须是 >=1 的整数：{cold_window!r}")
    if not isinstance(repeat_ban, int) or isinstance(repeat_ban, bool) \
            or repeat_ban < 1:
        raise SpreadError(
            f"config/spread.json 的 repeat_ban 必须是 >=1 的整数：{repeat_ban!r}")
    if cold_priority not in {"required", "preferred", "off"}:
        raise SpreadError(
            "config/spread.json 的 cold_priority 必须是 "
            f"required / preferred / off 之一：{cold_priority!r}")
    if not isinstance(priority, list) or not priority \
            or any(not isinstance(name, str) or not name.strip()
                   for name in priority):
        raise SpreadError(
            "config/spread.json 的 package_priority 必须是非空的字符串数组")
    seen: set = set()
    for name in priority:
        if name in seen:
            raise SpreadError(
                f"config/spread.json 的 package_priority 有重复项：{name!r}")
        seen.add(name)
    return SpreadConfig(
        cold_window=cold_window,
        repeat_ban=repeat_ban,
        cold_priority=cold_priority,
        package_priority=tuple(priority),
        source=str(path),
    )


# ----------------------------------------------------------------- git 历史

def _git(repo_dir: Path, args: list[str]) -> str:
    """跑一条只读 git 命令，返回 stdout。"""
    argv = ["git", "-C", str(repo_dir), *args]
    try:
        proc = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT_SECS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpreadError(
            f"git {' '.join(args[:2])} 跑不起来（{repo_dir}）：{exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise SpreadError(
            f"git {' '.join(args[:2])} 失败（exit {proc.returncode}，{repo_dir}）："
            f"{detail}")
    return proc.stdout.decode("utf-8", "replace")


def _parse_log(raw: str) -> list[dict]:
    """把 ``git log --name-only`` 的输出拆成一条条 commit 记录。"""
    records: list[dict] = []
    for chunk in raw.split(_RECORD):
        if not chunk.strip():
            continue
        if _SHA_SEP not in chunk:
            continue
        sha, rest = chunk.split(_SHA_SEP, 1)
        if _BODY_SEP not in rest:
            body, files_text = rest, ""
        else:
            body, files_text = rest.split(_BODY_SEP, 1)
        paths = [line.strip() for line in files_text.splitlines()]
        records.append({
            "sha": sha.strip(),
            "body": body,
            "paths": [path for path in paths if path],
        })
    return records


def classify_path(rel_path: str) -> str:
    """把一条仓库内路径归到一个「单位」。

    * ``packages/<name>/...`` → ``<name>``（这就是一个「包」）
    * ``skills/...`` → ``skills``
    * ``docs/...`` → ``docs``
    * 其余（package.json、src/、lessons/、tools/…）→ ``other``
    """
    parts = [part for part in str(rel_path).replace("\\", "/").split("/")
             if part and part != "."]
    if not parts:
        return "other"
    if parts[0] == "packages" and len(parts) >= 2:
        return parts[1]
    if parts[0] in TOP_LEVEL_UNITS:
        return parts[0]
    return "other"


def read_rsi_commits(repo_dir: Path, limit: int = _LOG_LIMIT) -> list[dict]:
    """读出历史上所有「RSI 合并过」的 commit，按时间倒序（新的在前）。

    判定依据是 commit body 里的 trailer ``X-Theatre-Wave: <n>`` / ``X-Theatre-Drs: <n>``。
    路径用 ``--relative`` 取相对当前目录——调用方给的是被改进对象自己的目录
    （usine），所以拿到的就是 ``packages/dsh-plugin/src/tools.ts`` 这种形状，
    跟仓库是不是某个大仓库的子树无关。
    """
    raw = _git(repo_dir, [
        "log", f"-{int(limit)}", "--no-merges", "--no-renames",
        "--name-only", "--relative",
        f"--format={_RECORD}%H{_SHA_SEP}%B{_BODY_SEP}",
    ])
    commits: list[dict] = []
    for record in _parse_log(raw):
        match = _TRAILER_RE.search(record["body"])
        if not match:
            continue
        label, index = match.group(1), int(match.group(2))
        units: list[str] = []
        for path in record["paths"]:
            unit = classify_path(path)
            if unit not in units:
                units.append(unit)
        commits.append({
            "unit": f"{label.lower()}-{index}",
            "label": label.lower(),
            "index": index,
            "packages": units,
            "commit": record["sha"],
        })
    return commits


def discover_packages(repo_dir: Path) -> list[str]:
    """列出仓库真实存在的包（``packages/<name>/``）。

    只认 **git 跟踪到的** 包：seed 是 ``git archive HEAD``，未跟踪的目录在 guest 里
    根本不存在，把它列进冷区等于给出一个 Agent 够不着的目标（实测：某个并发会话
    在 ``packages/`` 下留了一个未跟踪的 scratch 目录，里面只有 node_modules）。

    git 读不了时退回目录扫描，并在状态里如实说明（宁可少一个候选，
    也不能编一个目标出来）。
    """
    names: set = set()
    try:
        raw = _git(repo_dir, ["ls-files", "-z", "--", "packages"])
    except SpreadError:
        raw = ""
    if raw:
        for entry in raw.split("\0"):
            if not entry:
                continue
            parts = [part for part in entry.replace("\\", "/").split("/")
                     if part]
            if len(parts) >= 2 and parts[0] == "packages":
                names.add(parts[1])
    if names:
        return sorted(names)
    root = Path(repo_dir) / "packages"
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())


def _rank(unit: str, priority: tuple) -> tuple:
    """产线重要度排序键：表内的按表序，表外的排到最后并按名字排。"""
    if unit in priority:
        return (0, priority.index(unit), "")
    return (1, 0, unit)


# ----------------------------------------------------------------- 铺开状态

def build_spread_state(repo_dir: Path, config: SpreadConfig | None = None,
                       ) -> dict:
    """算出本波的铺开状态。

    返回的形状（载荷里就叫这几个键）::

        {"recent": [{"unit": "wave-1", "packages": ["dsh-plugin"],
                     "commit": "<sha>"}],
         "touched_counts": {"dsh-plugin": 3},
         "cold": ["core", "karaoke", ...]}

    外加几个诊断字段：``banned``（本波禁入的包）、``streaks``（每个包的连击数）、
    ``cold_recently``（最近 cold_window 次波次没碰过的包）、``packages``（仓库真实
    存在的包）、``history_commits``（扫到的 RSI commit 条数）。

    读历史失败**不抛**：git 读不了不是安全事件（它只影响选题偏好，不影响护栏），
    但必须**如实记在 ``history_error`` 里**——一个默默失效的闸门比没有闸门更坏。
    """
    config = config or SpreadConfig()
    repo_dir = Path(repo_dir)
    state: dict = {
        "repo": str(repo_dir),
        "config": config.to_dict(),
        "recent": [],
        "touched_counts": {},
        "cold": [],
        "cold_recently": [],
        "banned": [],
        "streaks": {},
        "packages": discover_packages(repo_dir),
        "history_commits": 0,
        "history_error": "",
    }
    try:
        commits = read_rsi_commits(repo_dir)
    except SpreadError as exc:
        state["history_error"] = str(exc)
        return state

    state["history_commits"] = len(commits)
    state["recent"] = [
        {"unit": commit["unit"], "packages": commit["packages"],
         "commit": commit["commit"]}
        for commit in commits
    ]
    counts: dict = {}
    for commit in commits:
        for unit in commit["packages"]:
            counts[unit] = counts.get(unit, 0) + 1
    state["touched_counts"] = dict(sorted(counts.items()))

    # 连击数：从最新的一条往回数，连续触及同一个包才算连击。
    # 口径：某包的连击 = 从最新一条开始、每一条都触及它的连续条数；中间断一次就归零。
    streaks: dict = {}
    for unit in counts:
        streak = 0
        for commit in commits:
            if unit in commit["packages"]:
                streak += 1
            else:
                break
        streaks[unit] = streak
    state["streaks"] = dict(sorted(streaks.items()))

    # 禁入：连着被打了 repeat_ban 次的包，本波不许再碰。
    state["banned"] = sorted(
        (unit for unit, count in streaks.items()
         if count >= config.repeat_ban),
        key=lambda unit: _rank(unit, config.package_priority))

    # 冷区：从未被任何 RSI commit 触及过的包（按产线重要度排序）。
    touched = set(counts)
    present = set(state["packages"])
    known = list(config.package_priority)
    for name in state["packages"]:
        if name not in known:
            known.append(name)
    state["cold"] = sorted(
        (name for name in known if name not in touched and name in present),
        key=lambda name: _rank(name, config.package_priority))

    # 近期冷：最近 cold_window 次波次里没被触及过的包（cold_window 这个旋钮管的就是它）。
    window = commits[:config.cold_window]
    recent_touched = set()
    for commit in window:
        recent_touched.update(commit["packages"])
    state["cold_recently"] = sorted(
        (name for name in known if name not in recent_touched and name in present),
        key=lambda name: _rank(name, config.package_priority))
    # 轮换候选：以前碰过、但最近 cold_window 次波次里没再碰的包（冷区之外的那部分）。
    state["rotation"] = [name for name in state["cold_recently"]
                         if name not in set(state["cold"])]
    return state


# ----------------------------------------------------------------- 约束文本

def _package_path(unit: str) -> str:
    """包在仓库里的相对路径（顶层单位没有 packages/ 前缀）。"""
    if unit in ("skills", "docs", "other"):
        return unit
    return f"packages/{unit}"


def render_constraint(state: dict, config: SpreadConfig | None = None) -> str:
    """把铺开状态渲染成一段追加进出题席 system_extra 的硬约束。

    口径（这是 DRS 那套「brief 必须有上界」的同一原则）：
    * 具体：点名目录，不让 Agent「去找到底在哪构建」；
    * 可执行：写成 MUST / MUST NOT，不用「优先考虑」这种没有约束力的措辞；
    * 无开放集：禁入清单与冷区清单都是**闭集**，不写「以及其它」这种话。

    第一次跑（没有任何 RSI 历史）→ 返回空串：不追加任何禁入/冷区文本，
    也不报错（那时候还没有「连续重复」可言，闸门无事可做）。
    """
    config = config or SpreadConfig()
    if not state.get("recent"):
        return ""
    if config.cold_priority == "off":
        return ""
    banned = list(state.get("banned") or [])
    cold = list(state.get("cold") or [])
    rotation = list(state.get("rotation") or [])
    lines: list[str] = []
    lines.append(
        "SPREAD GATE (mechanical; it decides this wave's target area and it "
        "overrides the TARGET MENU below):")
    if banned:
        paths = ", ".join(_package_path(unit) for unit in banned)
        lines.append(
            f"- BANNED FOR THIS WAVE: {paths}. Every file of your project "
            f"must live outside that directory, and your instruction must "
            f"not name it. This area has already been improved by the last "
            f"merged waves; improving it again is wasted budget.")
    if cold:
        paths = ", ".join(_package_path(unit) for unit in cold)
        if config.cold_priority == "required":
            lines.append(
                f"- YOUR PROJECT MUST BE INSIDE ONE OF THESE: {paths}. These "
                f"areas have never been touched by a merged wave, so they are "
                f"where the line still needs work. Pick exactly one of them "
                f"and say which one in the instruction you author.")
        else:
            lines.append(
                f"- PREFER ONE OF THESE: {paths}. These areas have never been "
                f"touched by a merged wave, so they are where the line still "
                f"needs work. Say which one your instruction works in.")
    if rotation:
        paths = ", ".join(_package_path(unit) for unit in rotation)
        lines.append(
            f"- ROTATION CANDIDATES (touched by an older wave, untouched by "
            f"the last {config.cold_window} merged waves): {paths}. Use one "
            f"of these only if the list above holds no file you can change "
            f"and pin offline.")
    if not cold and not rotation:
        lines.append(
            "- Every area of the line has been touched by a merged wave, so "
            "there is no cold area left; pick any single package directory "
            "that is not the banned one and say which one in the instruction "
            "you author.")
    lines.append(
        "- ONE PACKAGE DIRECTORY PER PROJECT: the source file and its test "
        "must both live under the same single package directory you picked. "
        "Two package directories in one project is two projects, and two "
        "projects do not fit in this wave's budget.")
    lines.append(
        "- NAME THE DIRECTORY: the instruction you author must name the exact "
        "package directory it works in, so the choice can be checked without "
        "guessing.")
    return "\n".join("  " + line for line in lines)


def apply_to_seat(seat, state: dict,
                  config: SpreadConfig | None = None) -> dict:
    """把约束文本追加进出题席的 ``system_extra``（原地改）。

    返回一个描述「改了什么」的小字典，调用方把它记进 manifest / 预检载荷。
    没有历史 → 什么都不改（优雅降级）。
    """
    config = config or SpreadConfig()
    text = render_constraint(state, config)
    if not text:
        return {"applied": False, "reason": "no RSI history yet",
                "chars": 0}
    extra = getattr(seat, "system_extra", "") or ""
    seat.system_extra = extra.rstrip() + "\n\n" + text
    return {"applied": True, "reason": "spread gate", "chars": len(text)}
