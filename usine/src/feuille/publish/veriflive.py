# -*- coding: utf-8 -*-
"""veriflive.py — 发布后核对（⑪）：管理页 → 按标题搜索 → 逐条截图 → 拼对照图

全部只读，不做任何修改。最终判定 = 人眼看缩略图里有文字（纪律 5：
发布成功的唯一权威判据 = 回列表核验到这条作品）。本模块只产证据
（逐条截图 + full-page 截图 + 对照图），不判 ok/fail——程序打 ✓ 不算数。

对照图用 `feuille.covers.sheet` 拼（PIL），不用 magick montage，少一个外部件。

合集核对是双通道互证：① 合集卡片的「N 个作品」计数；② 进编辑页滚遍
列表抓到的逐条唯一标题清单。两通道都等于 want 才算齐——只看计数会被
「计数对但挂错条」骗，只看清单会被「重复挂同一条」骗。可再加交叉验证：
「只看可添加的作品」计数应为 0（否则还有漏挂）。

使用契约：page 由 base.launch 给出（resolver Chrome + 平台 profile）；
截图全部落 out_dir；返回 dict 只是证据索引，结论由人眼下。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import covers
from . import base

# 各平台核对入口（管理页 URL / 搜索框 / 行定位模板 / 视口）。
# row_text 的 {kw} 会被 keyword 替换：抖音行文本是「…」的前缀、B 站是【…】标题、
# 小红书没有搜索框（走滚动采集，正则按 keyword 匹配）。
PLATFORMS: dict[str, dict] = {
    "douyin": {
        "manage": "https://creator.douyin.com/creator-micro/content/manage",
        "search_sel": "input[placeholder*='搜索']",
        "row_text": "「{kw}」的",
        "viewport": {"width": 1700, "height": 1100},
    },
    "bilibili": {
        "manage": "https://member.bilibili.com/platform/upload-manager/article",
        "search_sel": "input[placeholder*='搜索'], input[placeholder*='标题']",
        "row_text": "【{kw}",
        "viewport": {"width": 1600, "height": 1000},
    },
    "xiaohongshu": {
        "manage": "https://creator.xiaohongshu.com/new/note-manager",
        "search_sel": None,               # 无搜索框：滚动采集（verify_xhs_all 实测）
        "row_text": None,
        "viewport": {"width": 1600, "height": 1000},
    },
}

# 滚动采集（小红书）：抓含系列关键词的短文本行
JS_COLLECT = """(kw) => {
  const out=[];
  document.querySelectorAll('a,div[class*=note],div[class*=card],div[class*=item]')
    .forEach(e => {
      const t=(e.innerText||'').replace(/\\s+/g,' ').trim();
      if (t && t.includes(kw) && t.length < 80 && !out.includes(t)) out.push(t);
    });
  return out;
}"""

# 找真正的滚动容器（小红书列表不在 window 上滚）
JS_SCROLLER = """() => {
  const cands = [document.scrollingElement, document.body,
                 ...document.querySelectorAll('div[class*=scroll],div[class*=list],main')];
  let best = null, bestArea = 0;
  for (const c of cands) {
    if (!c) continue;
    const area = c.scrollHeight;
    if (area > bestArea) { bestArea = area; best = c; }
  }
  if (!best) return {moved:0, sh:0};
  const before = best.scrollTop;
  best.scrollTop = before + best.clientHeight * 0.85;
  return {moved: best.scrollTop - before, sh: best.scrollHeight, ch: best.clientHeight};
}"""

# 合集编辑页：抓条目标题（「系列名」开头的短文本）
JS_COLLECT_TITLES = """(kw) => [...document.querySelectorAll('*')]
  .map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())
  .filter(t => t.startsWith('「'+kw+'」') && t.length < 200)"""


def _search_rows(page, plat: str, keyword: str, out_dir: Path) -> tuple[list, list[str]]:
    """douyin/bilibili 共用：搜索 → full-page 截图 → 逐条裁剪行截图（只读）。

    返回 (标题 locator 的快照迭代所需参数, 截图文件名列表)——这里直接返回
    (titles_locator, pngs)。
    """
    cfg = PLATFORMS[plat]
    page.goto(cfg["manage"], wait_until="domcontentloaded", timeout=60000)
    time.sleep(6 if plat == "bilibili" else 7)
    if plat == "bilibili":
        for kw in ("知道了", "我知道了"):
            try:
                b = page.get_by_text(kw, exact=True).first
                if b.is_visible(timeout=900):
                    b.click(); time.sleep(1)
            except Exception:
                pass

    # 搜系列关键词
    try:
        box = page.locator(cfg["search_sel"]).first
        box.click(); box.fill(keyword); page.keyboard.press("Enter")
        time.sleep(5)
    except Exception as e:
        print(f"搜索框不可用：{type(e).__name__}")

    # 整页一张，先看全貌
    page.screenshot(path=str(out_dir / "list-all.png"), full_page=True)

    titles = page.get_by_text(cfg["row_text"].format(kw=keyword), exact=False)
    n = titles.count()
    print(f"命中 {n} 条")
    vp = page.viewport_size or cfg["viewport"]
    pngs = ["list-all.png"]
    for i in range(n):
        try:
            t = (titles.nth(i).inner_text() or "").strip()
        except Exception:
            continue
        titles.nth(i).scroll_into_view_if_needed()
        time.sleep(0.8 if plat == "douyin" else 0.7)
        bb = titles.nth(i).bounding_box()
        if not bb:
            continue
        # 缩略图约 145px 高，封面文字在**底部**那 35px，
        # 所以裁剪窗必须比缩略图还高，否则正好把文字切掉（栽过）。
        x0 = max(0, bb["x"] - (130 if plat == "douyin" else 150))
        y0 = max(0, min(bb["y"] - 45, vp["height"] - (210 if plat == "douyin" else 220)))
        clip_w = min(760 if plat == "douyin" else 800, vp["width"] - x0)
        name = f"row-{i:02d}.png"
        page.screenshot(path=str(out_dir / name),
                        clip={"x": x0, "y": y0, "width": clip_w, "height": 200
                              if plat == "douyin" else 210})
        print(f"  [{i:02d}] {t[:46]}")
        pngs.append(name)
    return pngs


def _scroll_rows(page, keyword: str, out_dir: Path) -> tuple[list[str], list[str]]:
    """xiaohongshu：无搜索框，滚动穷举「已发布」列表（verify_xhs_all 实测链路）。"""
    cfg = PLATFORMS["xiaohongshu"]
    page.goto(cfg["manage"], wait_until="domcontentloaded", timeout=60000)
    time.sleep(8)
    # 点「已发布」页签
    for i in range(4):
        try:
            loc = page.get_by_text("已发布", exact=True)
            if loc.count() and loc.nth(i).is_visible(timeout=800):
                loc.nth(i).click(); print("  已点「已发布」"); break
        except Exception:
            continue
    time.sleep(4)

    # 不做搜索过滤，直接看「已发布」页签的全量最新列表
    found: list[str] = []
    page.mouse.move(800, 600)   # 鼠标放到列表区域上，滚轮才作用在正确的容器
    prev_count = -1
    for i in range(30):
        for t in page.evaluate(JS_COLLECT, keyword):
            if t not in found:
                found.append(t)
        if i % 3 == 0:
            print(f"  轮{i+1}: 累计 {len(found)} 条")
        if len(found) == prev_count:
            break
        prev_count = len(found)
        page.mouse.wheel(0, 700)
        time.sleep(1.1)
    print(f"  最终采集 {len(found)} 条")

    # 看看有没有分页
    pag = page.evaluate("""() => [...document.querySelectorAll('li,button,a,div')]
      .filter(e => { const t=(e.innerText||'').trim();
        return /^\\d+$/.test(t) && parseInt(t) <= 20
               && e.getBoundingClientRect().width < 80; })
      .map(e => (e.innerText||'').trim())""")
    print(f"  疑似分页数字: {sorted(set(pag))}")

    page.mouse.move(800, 600)
    for _ in range(12):
        page.mouse.wheel(0, -900); time.sleep(0.35)
    time.sleep(1.5)
    page.screenshot(path=str(out_dir / "list-all.png"))

    titles = []
    for t in found:
        m = re.search(rf"({re.escape(keyword)}[^0-9]{{2,14}}版)", t)
        k = m.group(1) if m else t[:24]
        if k not in titles:
            titles.append(k)
    print(f"\n=== 共 {len(titles)} 个标题 ===")
    for i, t in enumerate(titles, 1):
        print(f"  {i:02d} {t}")
    (out_dir / "titles.json").write_text(
        json.dumps(titles, ensure_ascii=False, indent=1), "utf-8")
    return found, ["list-all.png"]


def verify(platform: str, page, out_dir, *, keyword: str = "一叶知秋") -> dict:
    """发布后只读核对：进管理页 → 按标题搜索 → 逐条截图 → 拼对照图。

    返回证据索引 dict（截图清单 / 对照图路径 / 命中数）。
    **最终判定 = 人眼看对照图缩略图里有文字**——本函数不判 ok/fail。
    keyword 默认值只是示例系列词；接入新项目必须传自己的。
    """
    if platform not in PLATFORMS:
        raise SystemExit(f"未知平台 {platform!r}（合法：{sorted(PLATFORMS)}）")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if platform == "xiaohongshu":
        found, pngs = _scroll_rows(page, keyword, out_dir)
        n_rows = len(found)
    else:
        pngs = _search_rows(page, platform, keyword, out_dir)
        n_rows = len(pngs) - 1          # 去掉 list-all

    # 对照图（PIL 拼版，不用 magick）：人眼判定的载体
    sheet_path = covers.sheet([out_dir / p for p in pngs], out_dir / "sheet.png")
    print(f"\n对照图：{sheet_path}")
    print("👉 最终判定：人眼看对照图——缩略图里有文字 = 预制封面生效；纯画面 = 没生效")
    return {"platform": platform, "keyword": keyword, "rows": n_rows,
            "shots": pngs, "sheet": str(sheet_path), "out_dir": str(out_dir)}


# ---------------------------------------------------------------- 合集核对
def verify_collection(page, out_dir, *, title: str, want: int,
                      keyword: str, expect_langs: dict[str, str] | None = None,
                      cross_check: bool = True) -> dict:
    """合集只读核对：作品数 + 逐条清单**双通道互证**（+可选交叉验证）。

    - 通道一：合集卡片文本里的「N 个作品」计数；
    - 通道二：进编辑页滚遍「合集内作品」列表抓到的唯一标题清单；
    - 互证：两通道都要等于 want；expect_langs（{语种名: 标题内子串}）可再查语种覆盖；
    - 交叉验证（cross_check）：作品面板勾「只看可添加的作品」后本系列计数应为 0
      （还有漏没挂）。

    只读，不点任何修改类按钮。返回证据 dict；结论仍以人眼看截图为准。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manage = "https://creator.douyin.com/creator-micro/content/manage?tab=collections"

    def shot(n):
        try:
            page.screenshot(path=str(out_dir / n)); print(f"  📸 {n}")
        except Exception:
            pass

    page.goto(manage, wait_until="domcontentloaded", timeout=60000)
    time.sleep(10)
    for kw in ("我知道了", "知道了", "以后再说"):
        loc = page.get_by_text(kw, exact=True)
        for i in range(min(loc.count(), 3)):
            try:
                if loc.nth(i).is_visible(timeout=400):
                    loc.nth(i).click(); time.sleep(0.8)
            except Exception:
                pass

    cards = page.locator("[class*='collection-card-']")
    card = None
    for i in range(cards.count()):
        c = cards.nth(i)
        try:
            if title[:6] in (c.inner_text(timeout=3000) or ""):
                card = c; break
        except Exception:
            continue
    if card is None:
        print("  ✗ 找不到合集卡片")
        raise SystemExit(f"找不到合集「{title}」的卡片（只读核对中止，未点任何东西）")

    txt = card.inner_text()
    print("=== 卡片全文 ===")
    print("  " + txt.replace("\n", " | "))
    shot("verify-col-card.png")

    m = re.search(r"(\d+)\s*个作品", txt)
    n = int(m.group(1)) if m else -1
    print(f"\n  作品数 = {n}  {'✓' if n == want else f'✗ 预期 {want}'}")

    # 通道二：进编辑页滚遍合集内作品列表
    print("\n▶ 进编辑页看逐条清单")
    card.scroll_into_view_if_needed(); time.sleep(0.8)
    card.locator("[class*='new-layout-action-']").first.click()
    time.sleep(6)

    seen: list[str] = []
    for step in range(22):
        for t in page.evaluate(JS_COLLECT_TITLES, keyword):
            if t not in seen:
                seen.append(t)
        page.screenshot(path=str(out_dir / f"scroll-list-{step:02d}.png"))
        # 滚到底
        page.evaluate("""() => {
          const b = [...document.querySelectorAll('div')]
            .find(e => e.scrollHeight > e.clientHeight + 40
                    && e.clientHeight > 300 && /合集内作品/.test(e.innerText||''));
          if (b) b.scrollTop = b.scrollHeight;
          else window.scrollBy(0, 600);
        }""")
        time.sleep(1.1)
        at_end = page.evaluate("""() => {
          const b = [...document.querySelectorAll('div')]
            .find(e => e.scrollHeight > e.clientHeight + 40
                    && e.clientHeight > 300 && /合集内作品/.test(e.innerText||''));
          return b ? (b.scrollTop + b.clientHeight >= b.scrollHeight - 12) : true;
        }""")
        if at_end:
            print(f"  第 {step+1} 屏到底")
            break
    for t in page.evaluate(JS_COLLECT_TITLES, keyword):
        if t not in seen:
            seen.append(t)

    print(f"\n=== 抓到 {len(seen)} 条唯一标题 ===")
    for k, t in enumerate(seen, 1):
        print(f"  {k:2d}. {t[:58]}")

    # 查重（重复挂同一条会让计数对、清单错——双通道互证的意义就在这）
    heads = [t.split(" ")[0] for t in seen]
    dup = [h for h in set(heads) if heads.count(h) > 1]
    print(f"\n  重复标题: {dup if dup else '无'}")

    missing: list[str] = []
    if expect_langs:
        hit = {k: any(v in t for t in seen) for k, v in expect_langs.items()}
        missing = [k for k, v in hit.items() if not v]
        print(f"  语种覆盖: {sum(hit.values())}/{len(expect_langs)}  缺={missing if missing else '无'}")

    # 交叉验证：作品面板里「只看可添加的作品」→ 本系列还剩 0 支可挂 = 全挂上了
    left = None
    if cross_check:
        print("\n▶ 交叉验证：作品面板 → 只看可添加的作品")
        for kw in ("添加作品", "点击添加作品"):
            loc = page.get_by_text(kw, exact=True)
            if loc.count() and loc.first.is_visible(timeout=2000):
                loc.first.click(); break
        time.sleep(5)
        box = page.locator("input[placeholder*='查找作品'], input[placeholder*='作品描述']").first
        box.click(); box.fill(keyword); page.keyboard.press("Enter")
        time.sleep(4.5)
        chk = page.get_by_text("只看可添加的作品", exact=False).first
        if chk.count():
            chk.click(); time.sleep(4)
            print("  ✓ 勾上「只看可添加的作品」")
        shot("verify-only-addable.png")
        body = page.inner_text("body", timeout=8000)
        mm = re.search(r"共\s*(\d+)\s*个作品", body)
        left = int(mm.group(1)) if mm else -1
        print(f"  本系列「还可添加」的作品数 = {left}  "
              f"{'✓ 全挂上了' if left == 0 else '✗ 还有漏'}")

    both_ok = (n == want) and (len(seen) == want)
    print(f"\n  双通道互证：卡片计数 {n} / 清单 {len(seen)} / 预期 {want} → "
          f"{'✓ 齐' if both_ok else '✗ 不齐'}")
    result = {"title": title, "want": want, "count": n, "items": seen,
              "dup": dup, "missing_lang": missing, "addable_left": left,
              "both_channels_ok": both_ok}
    (out_dir / "verify-col.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("👉 最终判定仍以人眼看 verify-col-card.png / scroll-list-*.png 为准")
    return result


def run(platform: str, *, profile_dir=None, out_dir, keyword: str = "一叶知秋",
        headless=False) -> dict:
    """便捷入口：launch + verify（登录态在平台 profile 里，未登录则当场停下）。"""
    profile_dir = profile_dir or base.profile_dir(platform)
    with base.launch(profile_dir, headless=headless,
                     viewport=PLATFORMS[platform]["viewport"]) as (ctx, page):
        return verify(platform, page, out_dir, keyword=keyword)
