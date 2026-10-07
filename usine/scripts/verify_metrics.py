#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_metrics.py — 指标回流机制的反向验证

第 0 条好数据放行：好台账 + 好指标合并后 check 全过、分析出排名。
反向各防一种真实退化：

- 悬空引用（results 键不在台账）→ 当场报错，不静默挂错行
- 两级凭据**分开判**：只有 verifiedBy 没 verifiedAt → 报「缺核验日期」
  （不是「无任何凭据」——合成布尔的坑）；已发布但零凭据 → 抓
- 指标取值域：计数型负数 / 比率 1.5 / 未知指标 / 指标挂未发布 → 全抓
- **null ≠ 0**：全 null 台账分析 → 如实说「不知道」，退出码 0
- **部分回填是常态**：只回填 likes 时查 views 不炸（筛选落在指标上）
- 样本不足不排名（n<5 的组只报数量）；分箱正确
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import metrics as mt          # noqa: E402


def entry(key, **kw):
    e = {"key": key, "platform": "douyin", "locale": "zh-CN", "lang": "中文",
         "title_chars": 20, "video": "build/video/x.mp4", "metrics": None}
    e.update(kw)
    return e


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-metrics-")
    d = pathlib.Path(tmp.name)

    # ---- 0. 好数据放行 ----
    vid = d / "build" / "video" / "x.mp4"
    vid.parent.mkdir(parents=True)
    vid.write_bytes(b"x")
    good = {"version": mt.VERSION, "entries": {
        "中文/zh-CN/douyin": entry("中文/zh-CN/douyin", published=True, url="https://…",
                                   metrics={"views": 100, "likes": 10,
                                            "completionRate": 0.52}),
        "英语/en-US/douyin": entry("英语/en-US/douyin", locale="en-US", lang="英语",
                                   published=True, verifiedBy="回列表核验",
                                   verifiedAt="2026-10-07",
                                   metrics={"views": 200, "likes": 20,
                                            "completionRate": 0.61}),
    }}
    n = mt.merge_results(good, {"results": {
        "中文/zh-CN/douyin": {"published": True, "url": "https://…",
                              "metrics": {"views": 100}}}})
    m = good["entries"]["中文/zh-CN/douyin"]["metrics"]
    rows.append((n == 1 and m == {"views": 100},
                 f"合并按整体替换 metrics（原口径；得 {m}，合并 {n} 条）"))
    probs = mt.check(good, d)
    rows.append((not probs, f"好台账 + 全凭据 + 合法指标 → check 全过"
                 + (f"　**{probs}**" if probs else "")))

    # ---- 1. 悬空引用 → 当场报错 ----
    try:
        mt.merge_results(good, {"results": {"不存在/zh-CN/douyin": {"published": True}}})
        rows.append((False, "悬空引用必须报错——没报"))
    except SystemExit:
        rows.append((True, "悬空引用（键不在台账）→ 当场报错，不静默挂错行"))

    # ---- 2. 两级凭据分开判 ----
    doc = {"version": mt.VERSION, "entries": {
        "a/zh-CN/douyin": entry("a/zh-CN/douyin", lang="a", published=True,
                                verifiedBy="回列表核验"),
        "b/zh-CN/douyin": entry("b/zh-CN/douyin", lang="b", published=True),
        "c/zh-CN/douyin": entry("c/zh-CN/douyin", lang="c", published=True, url="https://…"),
    }}
    probs = mt.check(doc, d)
    p1 = [p for p in probs if p.startswith("a/")]
    p2 = [p for p in probs if p.startswith("b/")]
    p3 = [p for p in probs if p.startswith("c/")]
    rows.append((len(p1) == 1 and "缺 verifiedAt" in p1[0],
                 f"只有方式没日期 → 报「缺核验日期」（{p1[0][:36]}…）——不是「无任何凭据」"))
    rows.append((len(p2) == 1 and "无任何凭据" in p2[0],
                 f"已发布零凭据 → 抓（{p2[0][:30]}…）"))
    rows.append((not p3, "url 强凭据 → 通过"))

    # ---- 3. 指标取值域 + 指标挂未发布 ----
    doc = {"version": mt.VERSION, "entries": {
        "d/zh-CN/douyin": entry("d/zh-CN/douyin", published=True, url="u",
                                metrics={"views": -5}),
        "e/zh-CN/douyin": entry("e/zh-CN/douyin", published=True, url="u",
                                metrics={"completionRate": 1.5}),
        "f/zh-CN/douyin": entry("f/zh-CN/douyin", published=True, url="u",
                                metrics={"happiness": 3}),
        "g/zh-CN/douyin": entry("g/zh-CN/douyin", metrics={"views": 100}),
    }}
    probs = mt.check(doc, d)
    rows.append((any("不是非负整数" in p for p in probs)
                 and any("0–1" in p for p in probs)
                 and any("未知指标" in p for p in probs)
                 and any("没标已发布" in p for p in probs),
                 f"计数负数 / 比率越界 / 未知指标 / 指标挂未发布 → 全抓（{len(probs)} 条）"))

    # ---- 4. null ≠ 0：全 null 分析如实说「不知道」 ----
    empty = {"version": mt.VERSION, "entries": {
        "h/zh-CN/douyin": entry("h/zh-CN/douyin"), "i/en-US/douyin": entry("i/en-US/douyin")}}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mt.analyze(empty)
    out = buf.getvalue()
    rows.append((rc == 0 and "不知道" in out and "尚未回填" in out,
                 "全 null 台账分析 → 如实说「不知道」（退出码 0，不编数据）"))

    # ---- 5. 部分回填是常态：只回填 likes 查 views 不炸 ----
    partial = {"version": mt.VERSION, "entries": {
        f"lang{i}/zh-CN/douyin": entry(f"lang{i}/zh-CN/douyin", published=True, url="u",
                                       metrics={"likes": 10 + i}) for i in range(6)}}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mt.analyze(partial, "views")
    rows.append((rc == 0 and "有指标 0/6" in buf.getvalue(),
                 "只回填 likes 时查 views → 0/6 如实报告，不 KeyError"))

    # ---- 6. 样本不足不排名 + 分箱 ----
    doc2 = {"version": mt.VERSION, "entries": {}}
    for i in range(6):
        doc2["entries"][f"x{i}/zh-CN/douyin"] = entry(
            f"x{i}/zh-CN/douyin", published=True, url="u",
            hook="question", title_chars=120,
            metrics={"views": 100 + i * 50})
    for i in range(4):                       # 只有 4 条 → 样本不足
        doc2["entries"][f"y{i}/zh-CN/douyin"] = entry(
            f"y{i}/zh-CN/douyin", published=True, url="u",
            hook="emoji", title_chars=30,
            metrics={"views": 999 + i})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mt.analyze(doc2, "views", dims=(("hook", "钩子", False),))
    out = buf.getvalue()
    rows.append(("question" in out and "emoji" not in out.split("样本不足")[0]
                 and "n<5" not in out,
                 f"hook 分组：question（n=6）排名，emoji（n=4）不排（{'样本不足未排' in out}）"))
    rows.append((mt._bucket(120) == "100-150" and mt._bucket(20) == "0-100"
                 and mt._bucket(None) == "(缺)",
                 f"分箱正确（120→{mt._bucket(120)}，None→{mt._bucket(None)}）"))

    # ---- 7. 台账落盘往返 + 版本护栏 ----
    mt.save(d, good)
    rows.append((mt.load(d)["entries"]["中文/zh-CN/douyin"]["metrics"]["views"] == 100,
                 "台账 save→load 往返一致"))
    bad = mt.load(d)
    bad["version"] = 0
    mt.save(d, bad)
    try:
        mt.load(d)
        rows.append((False, "版本不匹配必须拒读——没拒"))
    except SystemExit:
        rows.append((True, "台账 schema 版本不匹配 → 拒读（旧文件不作猜读）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("指标回流（merge_results / check / analyze）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：指标回流 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
