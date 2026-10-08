# -*- coding: utf-8 -*-
"""fix_collection_one.py — 只把**指定的 1 支**补进合集（本批：希伯来语）

⚠️ 为什么不直接跑 `collections.fix_collection(want=12)`：
那个函数会「取最上面那支未添加的」一直点，前提是**面板里全是我们自己的作品**。
本批面板里混着历史批次（10/6 的旧作品），一旦坐标失效就会点错行——
实测已经因此把封面盖到别的作品上。

这里改成**逐条显式匹配标题**再点，且点之前先确认该行的发布日期
属于本批（2026-10-08），双条件都满足才点。宁可少加，不可加错。

用法：
    uv run --group publish python examples/sijijie/fix_collection_one.py --no 9
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 归档位置在 skills/<skill>/assets/example：ROOT.parents[3] 才是 usine
# （examples/sijijie 原件里是 parents[1]）。uv run 下本行可省，
# 留作无 uv 环境的引导。
sys.path.insert(0, str(ROOT.parents[3] / "src"))

from feuille.publish import base, collections      # noqa: E402

OUT = ROOT / "build" / "douyin"
MANIFEST = ROOT / "build" / "publish-manifest.json"
TITLE = "十二种语言写四季"
THIS_BATCH_DATE = "2026-10-08"      # 本批发布日期：只加这一天的


def norm(s: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch):
            continue
        if unicodedata.category(ch).startswith(("L", "N")):
            out.append(ch)
    return "".join(out).lower()


# 面板里的一行：找出「已添加」之外、且标题命中目标的那一行的「+」坐标
JS_FIND_ONE = """(want) => {
  const wantN = (want || '').toLowerCase().replace(/[\\u0300-\\u036f]/g, '');
  const vw = window.innerWidth || 1600;
  const out = [];
  document.querySelectorAll('svg').forEach(e => {
    const r = e.getBoundingClientRect();
    if (Math.abs(r.width - 24) > 3 || Math.abs(r.height - 24) > 3) return;
    if (r.x + 24 < vw * 0.62 || r.x > vw - 14) return;
    if (r.y < 140) return;
    let p = e, row = null;
    for (let i = 0; i < 9 && p; i++) {
      p = p.parentElement;
      if (p && /发布于/.test(p.innerText || '')) { row = p; break; }
    }
    if (!row) return;
    const rt = (row.innerText || '').replace(/\\s+/g, ' ').trim();
    if (rt.length > 260) return;
    const n = rt.toLowerCase().replace(/[\\u0300-\\u036f]/g, '')
                    .replace(/[^\\p{L}\\p{N}]/gu, '');
    const w = wantN.replace(/[^\\p{L}\\p{N}]/gu, '');
    if (!n.includes(w)) return;              // 标题必须命中
    out.push({t: rt.slice(0, 70), date: (rt.match(/发布于([\\d-]+)/) || [])[1] || '',
              added: rt.includes('已添加'),
              x: Math.round(r.x), y: Math.round(r.y)});
  });
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no", type=int, required=True, help="清单里的序号")
    args = ap.parse_args()

    tasks = json.loads(MANIFEST.read_text("utf-8"))["douyin"]
    task = next((t for t in tasks if t["no"] == args.no), None)
    if task is None:
        raise SystemExit(f"清单里没有序号 {args.no}")
    key = norm(task["title"])[:12]
    print(f"目标：[{task['no']:02d}] {task['lang']} {task['title']}")

    prof = base.profile_dir("douyin")
    with base.launch(prof, viewport={"width": 1700, "height": 1100}) as (ctx, page):
        page.goto(collections.MANAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(10); collections.dismiss(page)

        cards = page.locator("[class*='collection-card-']")
        card = None
        for i in range(cards.count()):
            c = cards.nth(i)
            try:
                if c.is_visible(timeout=600) and TITLE in (c.inner_text() or ""):
                    card = c
                    break
            except Exception:
                continue
        if card is None:
            # 没有 collection-card 容器 → 按坐标框定位（实测该 class 不存在）
            box = page.get_by_text(TITLE, exact=False).first
            bb = box.bounding_box()
            if not bb:
                print("❌ 找不到合集标题")
                return 1
            card = box
        card.scroll_into_view_if_needed(); time.sleep(1.2)

        # 点「编辑合集」。
        # ⚠️ get_by_text("编辑合集").click() **点击成功但不导航**（实测停在列表页，
        # 「合集内作品」读出 -1）。改成按文本取坐标再用鼠标点，点了再等 URL 变化。
        before_url = page.url
        ed = page.get_by_text("编辑合集", exact=False)
        done = False
        for i in range(ed.count()):
            try:
                if not ed.nth(i).is_visible(timeout=600):
                    continue
                b = ed.nth(i).bounding_box()
                if not b:
                    continue
                page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
                done = True
                break
            except Exception:
                continue
        if not done:
            print("❌ 找不到「编辑合集」")
            return 1
        # 等导航（最多 15s）
        for _ in range(15):
            time.sleep(1.0)
            if page.url != before_url:
                break
        time.sleep(4)
        cnt = page.evaluate(collections.JS_COUNT)
        print(f"  编辑页 URL {page.url}")
        print(f"  编辑页「合集内作品」= {cnt}")
        if cnt < 0:
            print("  ❌ 没进到编辑页（计数未知）")
            page.screenshot(path=str(OUT / "fixone-not-in-edit.png"))
            return 1

        # 打开工作面板。
        # ⚠️ 不用 collections._open_picker_and_search——它按「点击添加作品」文案
        # 定位，且要求搜索框 placeholder 是「查找作品」/「作品描述」。
        # 本次合集已有 11 支，页面文案与搜索框都不匹配（实测 30s 超时）。
        # 这里直接找**任意可见 input** + 「添加作品」按钮，不依赖具体文案。
        opened = False
        for kw in ("添加作品", "点击添加作品"):
            loc = page.get_by_text(kw, exact=False)
            for i in range(min(loc.count(), 6)):
                try:
                    if loc.nth(i).is_visible(timeout=800):
                        loc.nth(i).click(); opened = True; break
                except Exception:
                    continue
            if opened:
                break
        if not opened:
            print("❌ 找不到「添加作品」入口")
            page.screenshot(path=str(OUT / "fixone-no-addbtn.png"))
            return 1
        time.sleep(5)
        print("  ✓ 已打开作品面板")
        # **不搜索**：面板默认列出全部作品。加搜索词反而会漏（历史实测：
        # 传关键词只匹配到 3/12 条，其余静默漏掉）。
        # 面板懒加载，往下滚几轮把行都渲染出来。
        for _ in range(6):
            page.mouse.wheel(0, 1200)
            time.sleep(1.0)

        cands = page.evaluate(JS_FIND_ONE, key)
        print(f"  面板内命中 {len(cands)} 行：")
        for c in cands:
            print(f"    · {c['t'][:52]} | 发布 {c['date']} | "
                  f"{'已添加' if c['added'] else '未添加'}")

        todo = [c for c in cands
                if not c["added"] and c["date"] == THIS_BATCH_DATE]
        if not todo:
            print("\n⚠️ 没有可加的目标行。")
            for c in cands:
                why = []
                if c["added"]:
                    why.append("已添加")
                if c["date"] != THIS_BATCH_DATE:
                    why.append(f"日期={c['date'] or '?'} 非本批")
                print(f"    [{c['t'][:40]}] → {'、'.join(why)}")
            page.screenshot(path=str(OUT / "fixone-no-target.png"))
            return 1

        c = todo[0]
        print(f"\n  ▶ 点这一行：{c['t'][:52]}")
        page.mouse.click(c["x"] + 12, c["y"] + 12)
        time.sleep(3)

        after = page.evaluate(collections.JS_COUNT)
        print(f"  点击后「合集内作品」= {after}")
        page.screenshot(path=str(OUT / "fixone-after-click.png"))

        want = 12
        if after != want:
            print(f"  ⚠️ 计数 {after} ≠ {want}，**不点保存**，保留现场")
            return 1

        page.get_by_text("保存", exact=True).first.click()
        time.sleep(5)
        page.screenshot(path=str(OUT / "fixone-saved.png"))
        print(f"  ✅ 已保存，总集数 = {after}")
        return 0


if __name__ == "__main__":
    sys.exit(main())