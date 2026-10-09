#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_publish.py — 发布系统（M13：⑨ 发布 / ⑩ 合集 / ⑪ 核对）的反向验证

**全部离线 / 本地**：只驱动 tempfile 里的 mock HTML（file://），绝不访问任何
平台域名、绝不登录、绝不点任何真实页面（使用契约第 7 条）。

第 0 条好数据放行：resolver 在本机真实解析到 Chrome，且发布器用**真 Chrome**
打开本地 mock 页跑通全链。

反向各防一种退化（每条对应一个已核实缺陷 / 一条纪律）：
- lazy 契约：playwright 缺席时 `import feuille.publish` + 全子模块导入 + 纯函数
  调用都不炸（playwright 只许在函数内 import）；
- 缺陷③：resolve_chrome 与 platform.browser(only='chrome') 同源（无第二事实源）、
  FEUILLE_BROWSER 坏路径显式报缺、publish 包源码零写死可执行路径
  （verify_platform 的 ALLOWED 之外不许出现）；
- 发布按钮子串坑：`button:has-text('发布')` 会命中「作品发布」导航诱饵——
  find_publish_button 必须只认 `text-is` 精确文本 + class 含 primary 的可见按钮；
- 登录墙可见性：浮层墙可见 = True；墙藏进 DOM（display:none）= False
  （只信可见文本，inner_text('body') 会被底层文案骗）；login.probe 三通道同测；
- 成功词表全词（B 站「稿件投递成功」）：v1 缺「投递」的词表匹配不上成功页
  文案（11 条误判的事故形态），修复后的词表必须含全词；
- 纪律 12：filter_tasks 筛空当场报错，不静默跑 0 条；
- 缺陷①：run_tasks 的防风控节流在**循环内**——每条之间都睡 between_s
  （事件序列逐条断言），单条异常不拖垮整批，result JSON 落盘可回读。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import platform as pt                    # noqa: E402
from feuille.publish import bilibili, douyin, login, xhs  # noqa: E402
from feuille.publish import base                          # noqa: E402
# 导入冒烟：这两个模块本套件不直接驱动，import 成功本身就是断言
from feuille.publish import collections, veriflive        # noqa: E402,F401

EV = ROOT / "build" / "publish-verify"      # 证据截图（build/ 不入库）

# ---------------------------------------------------------------- mock 页面
# A：发布页诱饵——「作品发布」导航（子串坑的原型）+ 无 primary 的同文本按钮 +
#    display:none 的假按钮 + div 假按钮 + 真·主按钮（class 含 primary）。
MOCK_A = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-A 抖音投稿页（诱饵版）</title>
<style>body{font:16px/1.6 sans-serif;margin:24px;background:#fff}
nav{border-bottom:1px solid #ddd;padding:8px}
button{font-size:16px;padding:8px 20px;margin:4px}
#real-publish{background:#fe2c55;color:#fff}
#decoy-div{display:inline-block;padding:8px 20px;margin:4px}
</style></head><body>
<nav>创作者中心 <button id="nav-publish" onclick="clickLog('nav-作品发布')">作品发布</button></nav>
<p>（诱饵 1：导航按钮文本含「发布」子串——has-text 会命中，text-is 不会）</p>
<button id="ghost-btn" class="btn-plain" onclick="clickLog('ghost-无primary')">发布</button>
<p>（诱饵 2：文本精确等于「发布」但 class 不含 primary）</p>
<button id="hidden-btn" class="semi-button primary" style="display:none"
        onclick="clickLog('hidden')">发布</button>
<p>（诱饵 3：class 含 primary 且文本精确，但不可见）</p>
<div id="decoy-div" class="semi-button primary" onclick="clickLog('div-假按钮')">发布</div>
<p>（诱饵 4：div 元素，class 含 primary、文本精确——但不是 button）</p>
<hr>
<button id="real-publish" class="semi-button primary" onclick="clickLog('real-发布')">发布</button>
<div style="height:600px"></div>
<div id="clicklog">[]</div>
<script>
window.__CLICKS = [];
function clickLog(w){ window.__CLICKS.push(w);
  document.getElementById('clicklog').textContent = JSON.stringify(window.__CLICKS);
  if (w === 'real-发布') document.title = 'PUBLISHED'; }
</script>
</body></html>"""

# B：登录墙页——可见「扫码登录」面板 + 藏在 DOM 里的「作品管理」（浮层陷阱）
MOCK_B = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-B 登录墙</title></head><body>
<div id="wall" style="border:2px solid #fe2c55;padding:16px">
  <h2>扫码登录</h2><p>验证码登录 · 手机号登录</p>
</div>
<div id="content" style="display:none"><h1>作品管理</h1><p>数据概览</p></div>
</body></html>"""

# C：成功页 + 风控页（B 站「稿件投递成功」全词 + xhs 风控文案）
MOCK_C = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>mock-C 成功与风控</title></head><body>
<h1>稿件投递成功</h1>
<p> Scan to verify —— 请稍后再试 </p>
</body></html>"""

_WIN_EXE = re.compile(r"""[A-Za-z]:\\?[A-Za-z0-9_ .\\-]+\.(?:exe|cmd|bat)\b""", re.I)
_MAC_APP = re.compile(r"""/Applications/[\w .]+\.app/""")


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []
    EV.mkdir(parents=True, exist_ok=True)

    # ---- 0. 好数据放行：resolver 真解析 + lazy 契约 ----
    got = base.resolve_chrome()
    rows.append((bool(got) and pathlib.Path(got).is_file(),
                 f"resolve_chrome() 解析到真实存在的 Chrome：{got}"))
    b = pt.browser(only="chrome")
    rows.append((b is not None and got == b[1],
                 "resolve_chrome 与 feuille.platform.browser(only='chrome') 同源（无第二事实源）"))
    os.environ["FEUILLE_BROWSER"] = "/definitely/not/a/chrome"
    try:
        base.resolve_chrome()
        rows.append((False, "FEUILLE_BROWSER 指向不存在路径时必须显式报缺（却返回了）"))
    except SystemExit as e:
        rows.append((True, f"FEUILLE_BROWSER 坏路径 → 显式报缺不静默换人（{str(e)[:24]}…）"))
    finally:
        del os.environ["FEUILLE_BROWSER"]

    code = ("import sys; sys.modules['playwright']=None;"
            f"sys.path.insert(0, {str(ROOT / 'src')!r});"
            "import feuille.publish;"
            "from feuille.publish import base, douyin, xhs, bilibili,"
            " collections, veriflive, login;"
            "assert base.filter_tasks([{'no':1,'lang':'x'}]) == [{'no':1,'lang':'x'}];"
            "print('lazy-ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    rows.append((r.returncode == 0 and "lazy-ok" in r.stdout,
                 "playwright 缺席：import + 七个子模块 + 纯函数全不炸（lazy 契约）"
                 if r.returncode == 0 else f"lazy 检查失败：{r.stderr.strip()[:120]}"))

    hits = [f.name for f in (ROOT / "src" / "feuille" / "publish").glob("*.py")
            if _WIN_EXE.search(f.read_text("utf-8")) or _MAC_APP.search(f.read_text("utf-8"))]
    rows.append((not hits,
                 f"publish 包源码零写死可执行路径（.app/.exe 正则零命中）{('命中：' + str(hits)) if hits else ''}"))

    # ---- 成功词表全词（B 站「稿件投递成功」，v1 缺「投递」的事故形态） ----
    body = "稿件投递成功"
    v1_words = ("投稿成功", "稿件提交成功", "发布成功", "提交成功", "已进入审核", "审核中")
    rows.append((not any(k in body for k in v1_words),
                 "反向复现：v1 词表（缺「投递」二字）对「稿件投递成功」全不命中 → 11 条被误判的事故形态"))
    rows.append((any(k in body for k in bilibili.BILI_SUCCESS_WORDS),
                 "修复后 BILI_SUCCESS_WORDS 含全词「稿件投递成功」"))

    # ---- filter_tasks（纪律 12：筛空当场报错） ----
    tasks = [{"no": i, "lang": f"语{i}", "title": f"标{i}", "body": "b",
              "tags": ["#x"], "video": "v", "cover": "c"} for i in range(1, 6)]
    rows.append(([t["no"] for t in base.filter_tasks(tasks, only="2,4")] == [2, 4],
                 "filter_tasks only='2,4' → [2, 4]"))
    rows.append(([t["no"] for t in base.filter_tasks(tasks, frm=3)] == [3, 4, 5],
                 "filter_tasks frm=3 → [3, 4, 5]"))
    rows.append(([t["no"] for t in base.filter_tasks(tasks)] == [1, 2, 3, 4, 5],
                 "filter_tasks 不过滤 → 原样全量（好数据放行）"))
    try:
        base.filter_tasks(tasks, only="9")
        rows.append((False, "only='9' 筛空必须当场报错（却静默返回）"))
    except SystemExit as e:
        rows.append((True, f"only='9' 筛空 → SystemExit 当场报错（{str(e)[:28]}…）"))

    # ---- playwright 驱动本地 mock（真 Chrome + file:// 本地页，零平台流量） ----
    try:
        import playwright  # noqa: F401
    except ImportError:
        rows.append((True, "SKIP：本环境未装 playwright——"
                            "uv sync --group publish 后重跑本脚本补齐 mock 断言"))
        return rows

    with tempfile.TemporaryDirectory(prefix="feuille-publish-mock-") as _td:
        td = pathlib.Path(_td)
        for name, html in (("mock-a", MOCK_A), ("mock-b", MOCK_B), ("mock-c", MOCK_C)):
            (td / f"{name}.html").write_text(html, "utf-8")
            (EV / f"{name}.html").write_text(html, "utf-8")     # 证据副本
        with base.launch(td / "profile", headless=True,
                         viewport={"width": 1280, "height": 800}) as (ctx, page):

            # ---- A. find_publish_button：精确匹配，绝不点中诱饵 ----
            page.goto((td / "mock-a.html").as_uri())
            page.wait_for_load_state("load")
            page.screenshot(path=str(EV / "mock-a-before.png"))
            found = base.find_publish_button(page)
            id_ok = found is not None and found.get_attribute("id") == "real-publish"
            rows.append((id_ok,
                         "find_publish_button 选中真·主按钮 #real-publish"
                         "（text-is 精确 + class 含 primary；四个诱饵全躲开）"))
            found.click()
            clicks = page.evaluate("window.__CLICKS")
            rows.append((clicks == ["real-发布"] and page.title() == "PUBLISHED",
                         f"点击后仅真按钮入账（诱饵零点击）：{clicks}"))
            page.screenshot(path=str(EV / "mock-a-clicked.png"))
            # 反向：真按钮藏起来 → 必须返回 None，不退回任何诱饵
            page.evaluate("document.getElementById('real-publish').style.display='none'")
            none_ok = base.find_publish_button(page) is None
            rows.append((none_ok,
                         "真按钮隐藏后 find_publish_button 返回 None——拒绝退回子串/无 primary 诱饵"))
            page.screenshot(path=str(EV / "mock-a-hidden.png"))

            # ---- B. login_wall 只认可见文本 + login.probe 三通道 ----
            page.goto((td / "mock-b.html").as_uri())
            page.wait_for_load_state("load")
            wall_vis = base.login_wall(page, douyin.DOUYIN_WALL)
            page.screenshot(path=str(EV / "mock-b-wall-visible.png"))
            st1, desc1 = login.probe(page, "douyin")
            page.evaluate("document.getElementById('wall').style.display='none';"
                          "document.getElementById('content').style.display='';")
            wall_hidden = base.login_wall(page, login.SITES["douyin"]["wall"])
            st2, desc2 = login.probe(page, "douyin")
            page.screenshot(path=str(EV / "mock-b-wall-hidden.png"))
            rows.append((wall_vis,
                         "login_wall：可见「扫码登录」面板 → True"))
            rows.append((not wall_hidden,
                         "login_wall：墙藏进 DOM（display:none）→ False——只信可见文本"))
            rows.append((st1 is False and "登录弹窗可见" in desc1,
                         f"login.probe：墙可见 → 未登录（{desc1}）"))
            rows.append((st2 is True and "作品管理" in desc2,
                         f"login.probe：墙隐藏+「作品管理」可见 → 已登录（{desc2}）——"
                         "inner_text('body') 式判法会在这里误判"))

            # ---- C. wait_success 全词 + risk_hit ----
            page.goto((td / "mock-c.html").as_uri())
            page.wait_for_load_state("load")
            ok_c = base.wait_success(page, bilibili.BILI_SUCCESS_WORDS, timeout_s=6, poll_s=0.3)
            rows.append((ok_c, "wait_success：页面文案「稿件投递成功」→ B 站词表命中"))
            neg_c = base.wait_success(page, xhs.XHS_SUCCESS_WORDS, timeout_s=0.6, poll_s=0.2)
            rows.append((not neg_c, "wait_success 反向：无小红书成功词 → 超时返回 False"))
            rows.append((base.risk_hit(page),
                         "risk_hit：'Scan to verify' 风控文案 → True"))
            page.goto((td / "mock-a.html").as_uri())
            rows.append((not base.risk_hit(page) and not base.login_wall(page),
                         "干净页：risk_hit / login_wall 均 False"))

            # ---- 缺陷①：run_tasks 节流在循环内 + 异常隔离 + JSON 落盘 ----
            events: list[tuple] = []
            real_sleep = time.sleep

            def rec_sleep(d):
                events.append(("sleep", d))
                if d < 0.5:
                    real_sleep(d)

            def mock_one(pg, t, auto, *, log_dir):
                events.append(("pub", t["no"]))
                if t["no"] == 2:
                    raise RuntimeError("模拟第 2 条挂掉")
                return {"no": t["no"], "lang": t["lang"], "ok": True, "stage": "mock-已发布"}

            mtasks = [{"no": i, "lang": f"语{i}", "title": f"标{i}", "body": "b",
                       "tags": ["#x"], "video": "v", "cover": "c"} for i in range(1, 5)]
            up = page.url
            logd = td / "runlog"
            saved = time.sleep
            time.sleep = rec_sleep          # base 模块内的 time.sleep 即此（同一 stdlib 模块对象）
            try:
                results = base.run_tasks(page, mtasks, mock_one, upload_url=up,
                                         log_dir=logd, between_s=0.15,
                                         result_json="mock-result.json")
            finally:
                time.sleep = saved

            seq = [e for e in events if e[0] == "pub" or e[1] == 0.15]
            want_seq = [("pub", 1), ("sleep", 0.15), ("pub", 2), ("sleep", 0.15),
                        ("pub", 3), ("sleep", 0.15), ("pub", 4)]
            rows.append((seq == want_seq,
                         f"缺陷①修复：事件序列逐条断言 = 发布→睡0.15s→发布→睡→发布→睡→发布"
                         f"（每条之间都睡，{seq if seq != want_seq else 'n-1=3 次节流全在循环内'}）"))
            rows.append(([r["no"] for r in results] == [1, 2, 3, 4]
                          and [r["ok"] for r in results] == [True, False, True, True]
                          and results[1]["stage"] == "异常 RuntimeError",
                         "单条异常隔离：第 2 条炸掉只记「异常 RuntimeError」，1/3/4 照常完成"))
            back = json.loads((logd / "mock-result.json").read_text("utf-8"))
            rows.append((len(back) == 4 and back[1]["stage"] == "异常 RuntimeError",
                         f"result JSON 落盘可回读（{logd / 'mock-result.json'}，{len(back)} 条）"))
            (EV / "mock-result.json").write_text(
                (logd / "mock-result.json").read_text("utf-8"), "utf-8")
            (EV / "mock-events.json").write_text(json.dumps(
                {"events": [list(e) for e in events],
                 "filtered_sequence": [list(e) for e in seq]},
                ensure_ascii=False, indent=1), "utf-8")      # 缺陷①修复的持久证据
            rows.append(((logd / "crash-02.png").is_file()
                         and all((logd / f"{p}-{n:02d}.png").is_file()
                                 for n in (1, 2, 3, 4) for p in ("pre", "post")),
                         "关键节点截图齐：pre/post 每条各一张 + crash-02 异常现场"))

    rows.append((True, f"证据目录：{EV}（mock-*.html / mock-*.png 截图留证）"))
    return rows


def main() -> int:
    rows = check()
    npass = sum(1 for ok, _ in rows if ok)
    nfail = sum(1 for ok, _ in rows if not ok)
    print(f"\n===== verify_publish：{npass} PASS / {nfail} FAIL =====")
    for ok, msg in rows:
        print(f"  {'✅ PASS' if ok else '❌ FAIL'}  {msg}")
    if nfail:
        print("\n❌ 中途有断言失败——以上结果不构成完整结论，先修再跑。")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(main())
