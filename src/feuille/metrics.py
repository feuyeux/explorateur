# -*- coding: utf-8 -*-
"""metrics.py — 指标回流（⑫）：results 合并 / 发布侧检查 / 分组分析

搬运自 explorateur/src/usine/publish.py 的 merge_results / check / analyze
（终态视角重构：root 参数化；分析维度参数化——explorateur 的 device/chip 等
维度是它的课程域字段，feuille 的默认维度取 manifest 派生属性）。

**没数据留 null 不填 0**：编出来的数据比没有数据更坏——它让后续每个「结论」
都建立在虚构样本上。分析器对全 null 台账必须如实说「这不是效果为零，是不知道」。

**部分回填是常态不是异常**：平台后台导出往往只给一部分指标（只有 likes 没有
views）。筛选必须落在**这一项指标**上（`(e["metrics"] or {}).get(metric)`），
不能按「有没有 metrics」筛——否则只回填 likes 时查 views 会在取值处 KeyError
（explorateur 2026-10-05 修）。

**样本不足不排名**（MIN_GROUP=5）：一条数据排出来的第一名是最容易骗人的结论形态。

**已发布凭据两级分开判，别合成一个布尔**：合成后 `weak = verifiedBy and verifiedAt`
在「有方式没日期」时为假，会掉进「无任何凭据」那句（措辞还是错的），
而真正的「缺核验日期」分支永远走不到（explorateur 反向验证第 5 条抓出）。
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

from .manifest import PLATFORMS

LEDGER_NAME = "ledger.json"
VERSION = 1

COUNT_METRICS = ("views", "likes", "comments", "collects", "shares", "follows")
RATE_METRICS = ("completionRate", "interactionRate")
ALL_METRICS = COUNT_METRICS + RATE_METRICS
MIN_GROUP = 5

# 分析维度默认表：(字段, 标签, 是否分箱)。维度字段应来自 manifest 派生属性。
DEFAULT_DIMS = (("platform", "平台", False),
                ("hook", "钩子形态", False),
                ("locale", "语种", False),
                ("title_chars", "标题字数", True),
                ("topic_count", "话题数", True),
                ("durationSec", "时长", True))

_RESULT_FIELDS = ("published", "url", "postId", "publishedAt", "verifiedBy", "verifiedAt")


def ledger_path(root) -> Path:
    return Path(root) / "publish" / LEDGER_NAME


def load(root) -> dict:
    p = ledger_path(root)
    if not p.exists():
        raise SystemExit(f"台账不存在：{p}（先构建发布台账）")
    doc = json.loads(p.read_text("utf-8"))
    if doc.get("version") != VERSION:
        raise SystemExit(f"台账 schema 版本 {doc.get('version')} != {VERSION}，请重建"
                         f"（字段是 schema 的一部分，旧文件不作猜读）")
    return doc


def save(root, doc: dict) -> None:
    p = ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, p)                    # 原子换，不留半个台账


def merge_results(doc: dict, results: dict) -> int:
    """人工层 results 合并进台账。返回合并条数。

    results 形如 `{"results": {"<键>": {published/url/…/metrics}}}`。
    **悬空引用当场报错**：键在台账里没有对应记录 = 那条发布对应的文案/素材
    被删了或改名了——不修就合并，会把指标挂到别的发布上。
    """
    n = 0
    for key, patch in (results.get("results") or {}).items():
        e = doc["entries"].get(key)
        if e is None:
            raise SystemExit(f"results 里的 {key!r} 在台账里没有对应记录——"
                             f"这条发布对应的源被删了或改名了（悬空引用必须先修）")
        for field in _RESULT_FIELDS:
            if field in patch:
                e[field] = patch[field]
        if patch.get("metrics"):
            e["metrics"] = patch["metrics"]
        n += 1
    return n


def check(doc: dict, root) -> list[str]:
    """发布侧检查（问题列表；空 = 通过）。判据取**真实目的**：

    - 「素材真的在盘上」不是「video 字段非空」；
    - 「已发布有据可查」不是「必须有 url」——两级凭据（url/postId 强、
      verifiedBy+verifiedAt 次）**分开判**；
    - 「这数是个比率」不是「比率字段存在」——比率折成 0–1，写 12.3% 填 0.123；
    - 「指标挂在真实发布过的记录上」——没发出去的作品不会有平台数据，
      有 = 手工填错了一行。
    """
    root = Path(root)
    problems: list[str] = []
    entries = doc.get("entries") or {}
    if not entries:
        return ["台账一条记录都没有（没构建过？）"]
    for key in sorted(entries):
        e = entries[key]
        want = f"{e.get('lesson', e.get('lang', '?'))}/{e.get('locale', '?')}/{e.get('platform', '?')}"
        if key != want and "key" in e:                 # 键自洽（无 lesson 字段的老条目跳过）
            problems.append(f"{key}: 键与字段不自洽")
        v = e.get("video")
        if v and not (root / v).exists():
            problems.append(f"{key}: 视频不在盘上：{v}")
        if e.get("cover") and not (root / e["cover"]).exists():
            problems.append(f"{key}: 封面不在盘上：{e['cover']}")
        meta = PLATFORMS.get(e.get("platform") or "")
        if meta and meta.get("titleMax") and e.get("title_chars", 0) > meta["titleMax"]:
            problems.append(f"{key}: 标题 {e['title_chars']} 字 > {meta['label']}上限"
                            f" {meta['titleMax']}（会被截断）")
        if e.get("published"):
            strong = bool(e.get("url") or e.get("postId"))
            if e.get("verifiedBy"):
                if not e.get("verifiedAt"):
                    problems.append(f"{key}: 凭据有 verifiedBy 但缺 verifiedAt"
                                    f"（核验是哪天做的？半截凭据无法复核）")
            elif not strong:
                problems.append(f"{key}: 标了已发布但无任何凭据"
                                f"（要 url/postId，或 verifiedBy+verifiedAt）")
        m = e.get("metrics")
        if m:
            for k, val in m.items():
                if k in COUNT_METRICS:
                    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                        problems.append(f"{key}: 指标 {k}={val!r} 不是非负整数")
                elif k in RATE_METRICS:
                    if not isinstance(val, (int, float)) or isinstance(val, bool) \
                            or not (0.0 <= float(val) <= 1.0):
                        problems.append(f"{key}: 指标 {k}={val!r} 不在 0–1 之间")
                else:
                    problems.append(f"{key}: 未知指标 {k!r}（{ALL_METRICS}）")
        if e.get("metrics") and not e.get("published"):
            problems.append(f"{key}: 有效果指标但没标已发布——没发出去的作品不会有平台数据")
    return problems


def _bucket(val) -> str:
    """连续值分箱，否则「标题字数」会分成一堆各 1 条的组、一条都排不出。"""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return str(val) if val is not None else "(缺)"
    for lo, hi, name in ((0, 100, "0-100"), (100, 150, "100-150"),
                         (150, 200, "150-200"), (200, 300, "200-300"),
                         (300, 10**9, "300+")):
        if lo <= val < hi:
            return name
    return str(val)


def analyze(doc: dict, metric: str = "views", *, min_group: int = MIN_GROUP,
            dims=DEFAULT_DIMS) -> int:
    """按维度分组比表现（中位数）。样本不足不排名。返回码 0 正常 / 1 指标名不合法。"""
    if metric not in ALL_METRICS:
        print(f"未知指标 {metric!r}；可用：{'/'.join(ALL_METRICS)}")
        return 1
    # 筛选落在**这一项指标**上（部分回填是常态，见模块头）
    rows = [e for e in (doc.get("entries") or {}).values()
            if (e.get("metrics") or {}).get(metric) is not None]
    have = len(doc.get("entries") or {})
    print("=" * 70)
    print(f"发布回流分析 · 指标 {metric} · 有指标 {len(rows)}/{have} 条记录")
    print("=" * 70)
    if not rows:
        print("平台数据尚未回填。台账里 metrics 全是 null——这不是「效果为零」，是「不知道」。")
        return 0
    for dim, dim_label, bucketed in dims:
        groups: dict[str, list] = {}
        for e in rows:
            v = e.get(dim)
            key = _bucket(v) if bucketed else str(v)
            groups.setdefault(key, []).append(e["metrics"][metric])
        sized = {k: v for k, v in groups.items() if len(v) >= min_group}
        thin = {k: len(v) for k, v in groups.items() if len(v) < min_group}
        if not sized:
            print(f"\n【{dim_label}】无任何分组达到样本量 {min_group}（"
                  f"各组 n：{sorted(thin.values(), reverse=True)[:6]}）→ 不下结论")
            continue
        ranked = sorted(sized.items(), key=lambda kv: statistics.median(kv[1]), reverse=True)
        print(f"\n【{dim_label}】按 {metric} 中位数（n≥{min_group}）")
        for k, vals in ranked:
            xs = sorted(vals)
            print(f"  {k:<14} n={len(vals):<3} 中位 {statistics.median(xs):>10.1f}  "
                  f"范围 {xs[0]}–{xs[-1]}")
        if thin:
            print(f"  样本不足未排：{dict(sorted(thin.items(), key=lambda kv: -kv[1]))}")
    return 0
