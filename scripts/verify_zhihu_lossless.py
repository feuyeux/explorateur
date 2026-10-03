#!/usr/bin/env python3
"""反向验证：知乎 Markdown 是否真的无损覆盖了源 HTML 渲染的每一个字段。

做法是把 build/lesson/colors/index.html 逐个面板、逐行、逐字段拆出来，
当成「必须出现在产物里的字符串清单」，再去生成的 Markdown 里找。
少一个就 FAIL。

结构上照 scripts/verify_text_contract.py 的路子：先拿**故意删掉一块的坏产物**
证明这个检查会 FAIL（否则检查可能空转，永远返回真），再拿真产物证明放行。

网页版没渲染、但 scene.json 里有的 dialogue[].note（每语种 3 条舞台提示）
不在 HTML 清单里，单独正向断言一次，确认是「补回」而不是「丢失」。
"""

from __future__ import annotations

import html as html_mod
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "build" / "lesson" / "colors" / "index.html"
SCENE = ROOT / "lessons" / "colors" / "scene.json"
ANALYSIS = ROOT / "lessons" / "colors" / "analysis"
OUT_DIR = ROOT / "lessons" / "colors" / "publish" / "zhihu"

# 与生成器共用同一张表：已发布 URL 表 + 受平台字符过滤影响的语种表。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_zhihu import ARABIC_STRIPPED_LOCALES, PUBLISHED_URLS, article_url  # noqa: E402

TAB_ORDER = [
    "zh-CN", "zh-HK", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT",
    "ru-RU", "el-GR", "hi-IN", "ar-SA", "he-IL", "ja-JP", "ko-KR",
]

ROLE_ZH = {
    "open": "开场", "reply": "接话", "round": "六色问答",
    "summary": "小结", "bye": "道别",
}
COLOR_ZH = {
    "red": "红", "blue": "蓝", "green": "绿",
    "yellow": "黄", "black": "黑", "white": "白",
}

# 必须和 scripts/build_zhihu.py 里的 DECLARED_SUBS 保持同一张表。
# 期望值在比对前先按表归一，所以「本课→本篇」这类声明式口吻改写不会
# 被误判成内容丢失；同时每次运行都打印替换计数，改写范围可审计。
DECLARED_SUBS = {"本课": "本篇"}
SUB_HITS: dict[str, int] = {k: 0 for k in DECLARED_SUBS}


def voice(s: str) -> str:
    for src, dst in DECLARED_SUBS.items():
        n = s.count(src)
        if n:
            SUB_HITS[src] += n
            s = s.replace(src, dst)
    return s


def clean(raw: str) -> str:
    """去内联标签、解 HTML 实体、压 ASCII 空白，保留全角空格 U+3000。

    不做这两步会把 &quot; / &#x27; / <em>RTL</em> 误判成「产物缺内容」——
    那是本检查自己的噪声，不是真的丢失。
    """
    if raw is None:
        return ""
    raw = re.sub(r"<[^>]+>", "", raw)
    # 只压 ASCII 空白，保留全角空格——网页版「17 行　开场 1…」和
    # 「cone / poly　井位 112×120」里的分隔符就是全角空格，压成半角会误报。
    return voice(re.sub(r"[ \t\r\n]+", " ", html_mod.unescape(raw)).strip())


def txt(pattern: str, s: str, group: int = 1) -> str:
    """抽一段元素内容并归一化。"""
    m = re.search(pattern, s, re.S)
    return clean(m.group(group)) if m else ""


def panel_of(html: str, lc: str) -> str:
    """切出某个语种的整个 section 面板。

    结束边界必须用 </section>，不能用「下一个 <section class="lc">」——
    最后一个语种（ko-KR）后面没有下一个 section，那样切会把页尾 <script>
    里的模板源码当成正文，误报出 '+esc(d.a)+' 这种根本不存在的字段。
    """
    start = html.index(f'id="lc-{lc}"')
    end = html.index("</section>", start)
    return html[start:end]


def required_strings(html: str, lc: str) -> list[tuple[str, str]]:
    """从 HTML 面板里抽出 (标签, 必须出现的字符串) 清单。"""
    p = panel_of(html, lc)
    req: list[tuple[str, str]] = []

    def need(label: str, value: str) -> None:
        # 归一化必须收在这里，而不是只靠 txt()：re.findall 直接喂进来的
        # note/meta 捕获是原始 HTML，带 &quot; / &#x27; 实体，
        # 绕开归一化会被误判成「产物丢内容」。
        v = clean(value)
        if v:
            req.append((label, v))

    # 头部。h2 里的 <em>RTL</em> 是网页版的视觉徽章，Markdown 没有徽章概念，
    # 改由正文用文字说明（见 check 里的 RTL 断言），所以这里把徽章剥掉。
    need("h2 语种名", txt(r"<h2>(.*?)(?:<em>[^<]*</em>)?</h2>", p))
    need("chain 语族链", txt(r'<p class="chain">(.*?)</p>', p))
    need("famtag", txt(r'<p class="famtag"><b>\d+</b>(.*?)</p>', p))
    need("ord", txt(r'<span class="ord">(\d+)<i>', p))

    # meta 表
    for label, value in re.findall(
        r'<dt>(.*?)</dt><dd[^>]*>(.*?)</dd>', p, re.S
    ):
        need(f"meta/{label}", value)

    # 三段 note
    for label, value in re.findall(
        r'<div class="note"><b>(.*?)</b><p>(.*?)</p></div>', p, re.S
    ):
        need(f"note/{label}", value)

    need("pdesc 舞台画面", txt(r'<p class="pdesc">(.*?)</p>', p))

    # 六色词表
    for word, roman, form in re.findall(
        r'<span class="tw"><b>(.*?)</b><i>(.*?)</i><u>(.*?)</u></span>', p, re.S
    ):
        need("tok 词", word)
        need("tok 注音", roman)
        need("tok 语形", form)

    need("srcnote 创作注记", txt(r'<div class="srcnote"><b>.*?</b><p>(.*?)</p>', p))
    need("lh 行数标题", txt(r'<h3 class="lh">逐句脚本与解析<span>(.*?)</span>', p))

    # 逐行
    for art in re.findall(r'<article class="line".*?</article>', p, re.S):
        no = txt(r'<span class="no">(\d+)</span>', art)
        role = txt(r'<span class="role r-\w+">(.*?)</span>', art)
        spk = txt(r'<span class="spk s-\w">(.*?)</span>', art)
        need(f"L{no} 角色", role)
        need(f"L{no} 说话人", spk)
        need(f"L{no} 色chip", txt(r'<span class="chip"[^>]*>(.*?)</span>', art))
        need(f"L{no} 原文", txt(r'<p class="sp"[^>]*>(.*?)</p>', art))
        need(f"L{no} 注音", txt(r'<span class="roman">(.*?)</span>', art))
        need(f"L{no} 译文", txt(r'<span class="gloss">(.*?)</span>', art))
        need(f"L{no} 气泡", txt(r'<span class="bub">(.*?)</span>', art))
        need(f"L{no} 手势", txt(r'<span class="ges">(.*?)</span>', art))
        for ac in ("g", "m", "c"):
            need(
                f"L{no} 解析{ac}",
                txt(rf'<div class="ac {ac}"><b>.*?</b><span>(.*?)</span>', art),
            )
    return req


def check(md_by_locale: dict[str, str], html: str, verbose: bool = True) -> int:
    """返回未命中的条目数。0 = 无损通过。"""
    missing_total = 0
    for lc in TAB_ORDER:
        md = md_by_locale.get(lc, "")
        req = required_strings(html, lc)
        missing = [(lab, val) for lab, val in req if val not in md]
        flag = "PASS" if not missing else f"FAIL({len(missing)})"
        if verbose:
            print(f"  {lc:<7} 字段 {len(req):>4} 项  {flag}")
        for lab, val in missing[:8]:
            if verbose:
                print(f"        缺 {lab}: {val[:60]!r}")
        if len(missing) > 8 and verbose:
            print(f"        …另有 {len(missing) - 8} 项")
        missing_total += len(missing)
    return missing_total


def main() -> int:
    html = HTML.read_text(encoding="utf-8")
    scene = json.loads(SCENE.read_text(encoding="utf-8"))

    md_by_locale: dict[str, str] = {}
    for lc in TAB_ORDER:
        label = json.loads(
            (ANALYSIS / f"{lc}.json").read_text(encoding="utf-8")
        )["langLabel"]
        f = next(OUT_DIR.glob(f"??-{label}.md"), None)
        if f is None:
            print(f"!! 找不到 {lc} 的产物文件")
            return 1
        md_by_locale[lc] = f.read_text(encoding="utf-8")

    print("=" * 68)
    print("反向验证：这个检查能不能抓到丢失？")
    print("=" * 68)

    # ---- 1. 喂坏数据：抽掉日语一篇里的一整段解析，要求被判 FAIL ----
    broken = dict(md_by_locale)
    ja = broken["ja-JP"]
    victim = txt(r'<div class="ac g"><b>.*?</b><span>(.*?)</span>', panel_of(html, "ja-JP"))
    assert victim and victim in ja, "找不到用于制造缺陷的样本"
    broken["ja-JP"] = ja.replace(victim, "【故意删除的一段】", 1)
    caught = check(broken, html, verbose=False)
    print(f"\n[1] 删掉日语一段解析 → {'FAIL(抓到) OK' if caught else 'PASS 没抓到 !!'}")
    fails = 0 if caught else 1

    # ---- 2. 删掉一个整行，要求被判 FAIL ----
    broken2 = dict(md_by_locale)
    ko_line = txt(r'<p class="sp"[^>]*>(.*?)</p>', panel_of(html, "ko-KR"))
    assert ko_line and ko_line in broken2["ko-KR"], "找不到用于制造缺陷的韩语台词"
    broken2["ko-KR"] = broken2["ko-KR"].replace(ko_line, "【整行删除】", 1)
    caught2 = check(broken2, html, verbose=False)
    print(f"[2] 删掉韩语一整行台词 → {'FAIL(抓到) OK' if caught2 else 'PASS 没抓到 !!'}")
    fails += 0 if caught2 else 1

    # ---- 3. 真产物：要求逐字段全中 ----
    print("\n[3] 真产物逐字段核对")
    real = check(md_by_locale, html)
    print(f"    → {'PASS 无损 OK' if real == 0 else f'FAIL 仍有 {real} 项丢失 !!'}")
    fails += 0 if real == 0 else 1

    # ---- 4. 正向断言：网页版漏渲染的 stage note 必须被补回 ----
    note_total = note_back = 0
    for lc in TAB_ORDER:
        for d in scene["locales"][lc]["dialogue"]:
            n = (d.get("note") or "").strip()
            if n:
                note_total += 1
                if voice(n) in md_by_locale[lc]:
                    note_back += 1
    ok = note_total == note_back
    print(f"\n[4] 网页版漏掉的舞台提示补回 {note_back}/{note_total} "
          f"→ {'PASS OK' if ok else 'FAIL !!'}")
    fails += 0 if ok else 1

    # ---- 4c. 声明式口吻改写：确认按表改掉了，且没有误伤同形词 ----
    sub_report = "、".join(
        f"{k}→{v} {SUB_HITS.get(k, 0)} 处" for k, v in DECLARED_SUBS.items()
    )
    left_over = [lc for lc in TAB_ORDER if "本课" in md_by_locale[lc]]
    # ru-RU 的「学校这天不上课让孩子玩雪」是真实文化事实，不在改写表里，必须原样保留
    ru_kept = "不上课" in md_by_locale.get("ru-RU", "")
    tone_ok = not left_over and ru_kept
    print(f"\n[4c] 口吻改写：{sub_report} → {'PASS OK' if tone_ok else 'FAIL ' + str(left_over)}")
    if not ru_kept:
        print("        注意：ru-RU 的「不上课」文化表述疑似被误改，请检查改写表")
    fails += 0 if tone_ok else 1

    # ---- 4b. RTL 徽章的等价替代：网页版用 <em>RTL</em> 徽章，Markdown 没徽章，
    #          必须用文字把「从右往左书写」这件事说出来，否则阿拉伯语/希伯来语
    #          读者遇到标点错位时没有任何提示。 ----
    rtl_missing = [
        lc for lc in scene.get("rtlLocales", [])
        if "RTL" not in md_by_locale.get(lc, "")
        or "从右往左" not in md_by_locale.get(lc, "")
    ]
    print(f"\n[4b] RTL 语种（{'、'.join(scene.get('rtlLocales', []))}）"
          f"已用文字标注书写方向 → {'PASS OK' if not rtl_missing else 'FAIL ' + str(rtl_missing)}")
    fails += 0 if not rtl_missing else 1

    # ---- 4d. 知乎会剥掉阿拉伯文字区段（U+0600–U+06FF）。
    #          受影响语种必须在正文顶部把这件事说出来，并把「原字去哪看」指清楚；
    #          主文导览的六色总表也必须挂同样的说明，否则读者会当成漏排。
    #          漏了这条 = 线上已知的静默缺陷（见 docs/zhihu-publish-playbook.md 坑 ⑰）。 ----
    strip_missing = [
        lc for lc in ARABIC_STRIPPED_LOCALES
        if "U+0600" not in md_by_locale.get(lc, "")
    ]
    idx_text = (OUT_DIR / "00-主文-六个颜色词十四种语言.md").read_text(encoding="utf-8")
    idx_strip_ok = "U+0600" in idx_text
    strip_ok = not strip_missing and idx_strip_ok
    print(f"\n[4d] 阿拉伯文过滤说明（{'、'.join(sorted(ARABIC_STRIPPED_LOCALES))}）"
          f"正文+主文总表均已标注 → {'PASS OK' if strip_ok else 'FAIL'}"
          + ("" if not strip_missing else " 正文缺: " + str(strip_missing))
          + ("" if idx_strip_ok else " 主文总表缺"))
    fails += 0 if strip_ok else 1

    # ---- 5. 规模与结构 ----
    plan = json.loads((OUT_DIR / "publish-plan.json").read_text(encoding="utf-8"))
    idx_ok = (OUT_DIR / "00-主文-六个颜色词十四种语言.md").exists()
    files_ok = len(plan) == 15
    dur_ok = all(
        p["duration"] is None
        or scene["durationBudget"][0] <= p["duration"] <= scene["durationBudget"][1]
        for p in plan
    )
    vid_ok = all(
        p["video"] is None or (ROOT / "build" / "scene" / p["video"]).exists()
        for p in plan
    )
    print(f"\n[5] 主文存在 {idx_ok} / 计划 15 篇 {files_ok} "
          f"/ 时长在预算内 {dur_ok} / 视频文件齐备 {vid_ok}")
    for ok_i, name in ((idx_ok, "主文"), (files_ok, "篇数"), (dur_ok, "时长"), (vid_ok, "视频")):
        fails += 0 if ok_i else 1

    # ---- 6. 目录互链可达：主文里必须是真实知乎 URL，不能是 .md 相对路径 ----
    idx = (OUT_DIR / plan[0]["file"]).read_text(encoding="utf-8")
    link_bad = [p["file"] for p in plan[1:] if f"({article_url(p['file'])})" not in idx]
    print(f"[6a] 主文目录链接 {len(plan) - 1 - len(link_bad)}/{len(plan) - 1} 指向真实知乎 URL "
          f"→ {'PASS OK' if not link_bad else 'FAIL ' + str(link_bad)}")
    fails += 0 if not link_bad else 1

    # 任何残留的 .md 相对链接在知乎上都会变成 404
    md_left = []
    for p in plan:
        body = (OUT_DIR / p["file"]).read_text(encoding="utf-8")
        for m in re.finditer(r"\]\(([^)]*\.md)\)", body):
            if m.group(1) not in PUBLISHED_URLS:
                md_left.append(f"{p['file']} → {m.group(1)}")
    print(f"[6b] 残留 .md 相对链接 {len(md_left)} 处 "
          f"→ {'PASS OK' if not md_left else 'FAIL ' + str(md_left)}")
    fails += 0 if not md_left else 1

    print("\n" + "=" * 68)
    print("反向验证结果：" + ("全部按预期 OK" if fails == 0 else f"{fails} 项未按预期 !!"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
