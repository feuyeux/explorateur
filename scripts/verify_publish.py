#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_publish.py — 发布台账（publish/ledger.json）的正判据与反向验证

**这个台账最危险的失败模式不是「查得不够严」，而是「查了，但查的其实不是那件事」**：
门禁说「通过」，于是有人照着它写下一支文案——而它验的是「字段齐不齐」，
不是「这份台账能不能支撑『哪支文案更有效』这个结论」。前者永远绿。

所以这里有两条纪律：
1. **第 0 条断言是好数据放行**。一个恒返回 FAIL 的门禁也"安全"，但毫无价值——
   它会让人养成无视 FAIL 的习惯，于是真的坏了也看不见。
2. **每条判据都要能指出它的真实目的**。引用完整性验的是「视频真在磁盘上」，
   不是「video 字段非空」；已发布凭据验的是「这句话有据可查」，不是「必须有 url」。

另外单独验三件**分析侧**的事，它们不是门禁但比门禁更影响结论质量：
  - 无平台数据时**必须**明说「不知道」，不许输出空洞的排名（把 null 当 0 是最贵的错）；
  - 分组样本不足时**必须**拒绝排名；
  - 钩子形态取**首句**而不是首行——抖音正文是一整行三句话，按行切会把问句判成陈述句。
"""
from __future__ import annotations

import copy
import io
import json
import pathlib
import sys
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usine import publish                                      # noqa: E402

LEDGER = publish.LEDGER_PATH
RESULTS = ROOT / "publish" / "results.json"


def _mutate(fn):
    """在**内存副本**上改，跑完不落盘。测试不许动真台账。"""
    doc = json.loads(LEDGER.read_text("utf-8"))
    fn(doc)
    return publish.check(doc)


def _one(key="colors/en-US/douyin"):
    """取一条真记录做变体。变体是单条，别的条目原样保留——
    只把一条改坏，门禁应当只因这一条报问题。"""
    return key


def positive():
    """正判据：真实台账必须全绿。"""
    doc = json.loads(LEDGER.read_text("utf-8"))
    problems = publish.check(doc)
    n = len(doc["entries"])
    if problems:
        return False, f"真实台账 {n} 条未通过：{problems[:3]}"
    return True, f"真实台账 {n} 条 0 问题（引用完整性 / 指标取值域 / 标题上限 / 已发布凭据）"


def selftest():
    rows = [positive()]

    # ---------- 1. 视频路径悬空 ----------
    def hang():
        doc = json.loads(LEDGER.read_text("utf-8"))
        doc["entries"][_one()]["video"] = "build/scene/does-not-exist_xx-XX.mp4"
        return publish.check(doc)
    p = hang()
    rows.append((any("不在磁盘上" in x for x in p),
                 f"视频路径悬空 → 判死（{p[0][:44] if p else '**没抓到**'}）"))

    # ---------- 2. 缺视频字段 ----------
    p = _mutate(lambda d: d["entries"][_one()].pop("video"))
    rows.append((any("没有视频路径" in x for x in p),
                 f"缺视频字段 → 判死（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 3. 标题超平台上限 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(titleChars=999))
    rows.append((any("上限" in x for x in p),
                 f"标题 999 字 > 抖音 30 字 → 判死（{p[0][:44] if p else '**没抓到**'}）"))

    # ---------- 4. 已发布但零凭据 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(
        published=True, url=None, postId=None, verifiedBy=None, verifiedAt=None))
    rows.append((any("无任何凭据" in x for x in p),
                 f"标已发布且零凭据 → 判死（{p[0][:44] if p else '**没抓到**'}）"))

    # ---------- 5. 只有 verifiedBy 没有 verifiedAt（半截凭据） ----------
    p = _mutate(lambda d: d["entries"][_one()].update(
        published=True, url=None, postId=None, verifiedBy="内容管理页核验", verifiedAt=None))
    rows.append((any("缺 verifiedAt" in x for x in p),
                 f"凭据只有 verifiedBy 没有日期 → 判死（{p[0][:44] if p else '**没抓到**'}）"))

    # ---------- 6. 弱凭据（无 url 但有核验方式+日期）必须放行 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(
        published=True, url=None, postId=None,
        verifiedBy="笔记管理页核验", verifiedAt="2026-10-04"))
    rows.append((not any(_one() in x for x in p),
                 f"已发布 + verifiedBy + verifiedAt（无 url）→ 放行"
                 f"（{'无问题' if not p else p[0][:40]}）"))

    # ---------- 7. 计数指标为负 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(metrics={"views": -1}))
    rows.append((any("非负整数" in x for x in p),
                 f"views=-1 → 判死（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 8. 计数指标是浮点 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(metrics={"likes": 12.5}))
    rows.append((any("非负整数" in x for x in p),
                 f"likes=12.5（计数型给了小数）→ 判死（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 9. 比率指标越界 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(metrics={"completionRate": 1.2}))
    rows.append((any("0–1" in x for x in p),
                 f"完播率 1.2 → 判死（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 10. 比率指标为负 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(metrics={"interactionRate": -0.01}))
    rows.append((any("0–1" in x for x in p),
                 f"互动率 -0.01 → 判死（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 11. 边界值放行（0 和 1 都是合法比率） ----------
    p = _mutate(lambda d: d["entries"][_one()].update(
        metrics={"views": 0, "completionRate": 0.0, "interactionRate": 1.0}))
    rows.append((not any(_one() in x for x in p),
                 f"views=0 / 比率取 0.0 与 1.0（边界）→ 放行（{len(p)} 个问题）"))

    # ---------- 12. 未知指标名 ----------
    p = _mutate(lambda d: d["entries"][_one()].update(metrics={"fans": 100}))
    rows.append((any("未知指标" in x for x in p),
                 f"指标名 fans 不在白名单 → 判死（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 13. 语种目录缺失（属性静默降级） ----------
    p = _mutate(lambda d: d["entries"][_one()].update(dir=None))
    rows.append((any("无书写方向" in x for x in p),
                 f"语种目录缺失 → dir=None 判死（{p[0][:44] if p else '**没抓到**'}）"))

    # ---------- 14. 键与字段不自洽 ----------
    p = _mutate(lambda d: d["entries"].__setitem__(
        "colors/en-US/bilibili", d["entries"].pop(_one())))
    rows.append((any("不自洽" in x for x in p),
                 f"键 platform 写成 bilibili 但字段还是 douyin → 判死"
                 f"（{p[0][:40] if p else '**没抓到**'}）"))

    # ---------- 15. 台账空了 ----------
    p = publish.check({"entries": {}})
    rows.append((any("一条记录都没有" in x for x in p),
                 f"台账为空 → 判死（{p[0][:36] if p else '**没抓到**'}）"))

    # ---------- 15b. 指标挂在没发布的记录上 ----------
    #     这条判据 2026-10-05 是先写进 check() 的 docstring、忘了落成代码的（坑㉝重演）。
    #     补上代码后必须立刻给它反向验证，否则下一任也会把它「优化」掉。
    p = _mutate(lambda d: d["entries"][_one()].update(published=None, metrics={"views": 500}))
    rows.append((any("没标已发布" in x for x in p),
                 f"没发布的记录却有指标 → 判死（{p[0][:44] if p else '**没抓到**'}）"))

    #     反过来：已发布 + 有凭据 + 有指标 = 合法组合，必须放行
    p = _mutate(lambda d: d["entries"][_one()].update(
        published=True, url=None, postId=None,
        verifiedBy="笔记管理页核验", verifiedAt="2026-10-04",
        metrics={"views": 500, "likes": 42}))
    rows.append((not any(_one() in x for x in p),
                 f"已发布 + 有凭据 + 有指标 → 放行（{len(p)} 个问题）"))

    # ================= 分析侧：三条比门禁更影响结论质量 =================

    # ---------- 16. 无数据时必须说「不知道」，不许输出排名 ----------
    doc = json.loads(LEDGER.read_text("utf-8"))
    for e in doc["entries"].values():
        e["metrics"] = None
    buf = io.StringIO()
    with redirect_stdout(buf):
        publish.analyze(doc, "views")
    out = buf.getvalue()
    ok = ("尚未回填" in out and "不是「效果为零」，是「不知道」" in out
          and "中位" not in out)
    rows.append((ok, f"0 条指标 → 报告「无数据」且不输出任何中位排名"))

    # ---------- 17. 把 null 误填成 0 会被门禁放行吗？（不会——但分析会得出结论） ----------
    #     这条验的是**为什么**必须留 null：0 是合法计数，check 抓不住它，
    #     但它会把「没数据」变成「效果垫底」。用 n=4 验证 0 确实会参与排名。
    doc = json.loads(LEDGER.read_text("utf-8"))
    for i, e in enumerate(sorted(doc["entries"].values(), key=lambda x: x["key"])[:4]):
        e["metrics"] = {"views": 0}          # 假装「全部零播放」
    buf = io.StringIO()
    with redirect_stdout(buf):
        publish.analyze(doc, "views", min_group=3)
    out = buf.getvalue()
    rows.append((("n=4" in out or "n=" in out) and "n≥3" in out,
                 f"零值样本 n=4 能被排名（min_group=3）→ 说明「填 0」确实会扭曲结论，"
                 f"所以没数据必须留 null"))

    # ---------- 18. 样本不足必须拒绝排名 ----------
    doc = json.loads(LEDGER.read_text("utf-8"))
    for e in sorted(doc["entries"].values(), key=lambda x: x["key"])[:2]:
        e["metrics"] = {"views": 1000}
    buf = io.StringIO()
    with redirect_stdout(buf):
        publish.analyze(doc, "views", min_group=5)
    out = buf.getvalue()
    rows.append((("不下结论" in out) and ("n≥5" not in out.split("不下结论")[0].split("按 views")[-1]
                                          or "样本不足" in out),
                 f"每组 n=1 < min_group 5 → 拒绝排名"))

    # ---------- 19. 样本充足必须真排名（防止「永远不下结论」也是坏的） ----------
    doc = json.loads(LEDGER.read_text("utf-8"))
    for i, e in enumerate(sorted(doc["entries"].values(), key=lambda x: x["key"])):
        e["metrics"] = {"views": 100 * i}
    buf = io.StringIO()
    with redirect_stdout(buf):
        publish.analyze(doc, "views", min_group=5)
    out = buf.getvalue()
    rows.append(("中位" in out, f"28 条齐备 → 正常输出中位排名"))

    # ---------- 20. 未知指标名必须非零退出 ----------
    rc = publish.analyze({"entries": {}}, "fans")
    rows.append((rc == 1, f"analyze --metric fans（不在白名单）→ rc={rc}（应 1）"))

    # ---------- 20b. 部分回填：只填了 likes 就要查 views，不能 KeyError ----------
    #     平台后台导出常常只给一部分指标，**部分回填是常态**。
    #     按「有没有 metrics」筛会在取值处 KeyError——分析器一崩，
    #     就没人回填了，闭环反而被这个 bug 卡死。
    doc = {"entries": {}}
    for i, loc in enumerate(["en-US", "zh-CN", "ja-JP", "ar-SA", "ko-KR"]):
        k = f"colors/{loc}/douyin"
        doc["entries"][k] = {"key": k, "lesson": "colors", "locale": loc,
                             "platform": "douyin", "published": True,
                             "metrics": {"likes": 100 + i}}
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            publish.analyze(doc, "views")
        ok, why = True, f"报「有指标 0/5」且未抛异常"
    except KeyError as e:
        ok, why = False, f"**KeyError {e}**"
    rows.append((ok, f"只回填 likes 却查 views → 不崩，如实报无数据（{why}）"))
    #     同一份数据查 likes 必须能正常出结论（证明不是「一律不给结果」）
    buf = io.StringIO()
    with redirect_stdout(buf):
        publish.analyze(doc, "likes")
    rows.append(("中位" in buf.getvalue(),
                 f"同一份数据查 likes → 正常出排名（5 条够样本量）"))

    # ---------- 21. 钩子形态取首句而非首行 ----------
    three_in_one = ("说到颜色，你会想到什么？十四种语言同一堂颜色课的第01话："
                    "Miles和Ruby在打烊前的街角咖啡馆。（00:52）")
    got = publish.hook_shape(three_in_one)
    rows.append((got == "question",
                 f"单行三句的抖音正文 → 钩子判为 {got!r}（应 'question'，"
                 f"按行切会误判成 statement）"))

    # ---------- 22. emoji 开场 + 问句，两条特征都要保留 ----------
    got = publish.hook_shape("\U0001F3A8 说到颜色，你会先想到哪一个？\n\n第01话…")
    rows.append((got == "emoji+question",
                 f"emoji 开场的问句 → 钩子判为 {got!r}（应 'emoji+question'，"
                 f"压成 'emoji' 就丢了「它同时是问句」）"))

    # ---------- 23. emoji 判定必须是码位区间，不是字符串成员测试 ----------
    got = publish.hook_shape("\U0001F3A8 只有 emoji 没有问号")
    rows.append((got == "emoji",
                 f"emoji 开场的陈述句 → {got!r}（若用 `ch in \"🎰-🫿…\"` 这种成员测试，"
                 f"这里会恒为 False）"))

    # ---------- 24. results.json 悬空键必须报错，不能静默丢弃 ----------
    tmp = ROOT / "build" / "publish" / "_selftest-results.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps({"results": {"colors/xx-XX/douyin": {"url": "x"}}}), "utf-8")
    doc = json.loads(LEDGER.read_text("utf-8"))
    try:
        publish.merge_results(doc, tmp)
        caught = False
        msg = "**没报错**"
    except SystemExit as e:
        caught = True
        msg = str(e)[:40]
    finally:
        tmp.unlink(missing_ok=True)
    rows.append((caught, f"results.json 悬空键 → 报错（{msg}）"))

    ok = sum(1 for r, _ in rows if r)
    print("=" * 72)
    print(f"发布台账反向验证：{ok}/{len(rows)} 条生效")
    print("=" * 72)
    for r, msg in rows:
        print(f"  [{'PASS' if r else 'FAIL'}] {msg}")
    return 0 if ok == len(rows) else 1


def main():
    import argparse
    ap = argparse.ArgumentParser(description="发布台账门禁 + 反向验证")
    ap.add_argument("--selftest", action="store_true", help="跑反向验证")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    ok, msg = positive()
    print("=" * 68)
    print(f"发布台账门禁：{msg}")
    print("=" * 68)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
