# -*- coding: utf-8 -*-
"""collections.py — 合集收录（⑩）：以 douyin_fix_collection.py 为基准

搬运自 yiyezhiqiu/scripts/douyin_fix_collection.py（**基准版**），
参考 douyin_make_collection.py / douyin_collection_step1.py（创建合集的表单/
封面/面板步骤）。

**已核实缺陷②的修复声明**：douyin_make_collection.py 的 JS_ROWS「扫文本行→
按去重序号取第 i 个」方案有去重 bug——去重后每轮都返回 target[0]，12 次点击
全落在同一行（希伯来语）。基准版改用「+」按钮**本身**做选择器：面板里未添加
的行右侧是 24x24 的 svg，已添加的行文字含「已添加」（JS_PLUS）。本模块
**不携带** JS_ROWS 方案的任何可执行代码，创建流程的挂作品环节也走 JS_PLUS。

**平台差异**（搬运时点实测，源：yiyezhiqiu AGENTS.md 平台硬限制表 +
probe_bili_collection / check_bili_level / probe_xhs_collection 系列）：
- 抖音：合集在内容管理 `?tab=collections`，本模块两条流程（编辑补挂 / 新建）
  都实测过——这是唯一在本模块实现全流程的平台。
- B 站：合集功能需**创作中心 Lv2**，等级不够时 UI 上是灰字、无任何可点控件，
  无法绕过（先攒等级，别硬闯；check_bili_level.py 只读查等级的先例）。
- 小红书：网页创作平台**没有合集管理页**——加入合集走「编辑单条笔记 →
  选择合集」的逐条链路（见源项目 xhs_add_collection.py），不存在本模块这种
  「打开合集编辑页批量补挂」的入口。

**使用契约**：
- 只对**自己的账号内容**操作；page 由 base.launch 给出（resolver Chrome）。
- 保存是修改类操作：计数不符就不点保存、保留现场（每步截图落 out_dir）。
- title / want / search_kw / desc / cover 全部由调用方传入——本模块不写死
  任何项目内容。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import base

MANAGE = "https://creator.douyin.com/creator-micro/content/manage?tab=collections"

# 找出「+」按钮：24x24 svg，在**右侧抽屉面板内**，行内不含「已添加」
# （缺陷②修复的核心：选择器长在按钮自己的几何特征上，不靠「文本行去重取序号」）
#
# ⚠️ 2026-10-08 修正两处硬编码（原版把实测值写进了选择器）：
# ① x 区间 1500..1600 是 viewport=1600 时量出的**绝对坐标**；本项目
#    viewport=1700 时「+」落在 x≈1674，全部被过滤 → 面板明明有 3 个作品
#    （截图可证），脚本却报「待加=0」。现改为**相对视口**判定。
# ② 行文本必须包含 search_kw（"四季"）：12 条里只有 3 条标题含它，
#    其余 9 条静默漏挂。现改为「未添加的一律返回」，数量核对交给调用方。
# 教训：**几何选择器里出现绝对坐标，等于把 viewport 宽度写死了。**
#（search_kw 不再进本 JS——「未添加的一律返回」后 want 形参已删，数量核对
#  交给调用方。）
#
# 几何判据只允许有一份实现：JS_PLUS（找候选）与滚入视口的 scroller
# （点前重取坐标）共用 _JS_GEOM。2026-10-08 之前两处各写一份，漂移后
# scroller 找不到元素 → 滚动没发生 → 拿旧坐标连点同一条希伯来语行 3 次。
_JS_GEOM = """
  const vw = window.innerWidth || 1600;
  const inPanel = (r) => r.x + 24 >= vw * 0.62     // 在右侧抽屉面板内
                       && r.x <= vw - 26 + 12      // 且贴近面板右缘（内约 26px）
                       && r.y >= 140;             // 排除右上角关闭/清空图标
"""
JS_PLUS = """() => {""" + _JS_GEOM + """  const cands = [];
  document.querySelectorAll('svg').forEach(e => {
    const r = e.getBoundingClientRect();
    if (Math.abs(r.width - 24) > 3 || Math.abs(r.height - 24) > 3) return;
    if (!inPanel(r)) return;
    let p = e, row = null;
    for (let i = 0; i < 9 && p; i++) {
      p = p.parentElement;
      if (p && /发布于/.test(p.innerText || '')) { row = p; break; }
    }
    if (!row) return;
    const rt = (row.innerText || '').replace(/\\s+/g, ' ').trim();
    if (rt.length > 220) return;                 // 行容器识别失败
    // ⚠️ 2026-10-08：原来要求行文本包含 search_kw（"四季"）。实测 12 条里
    // 只有 3 条标题含「四季」，其余 9 条永远匹配不上 → 静默漏挂。
    // 改为：**未添加的一律返回**，数量核对交给调用方。
    if (rt.includes('已添加')) return;
    cands.push({t: rt.slice(0, 46), x: Math.round(r.x), y: Math.round(r.y)});
  });
  cands.sort((a, b) => a.y - b.y);
  return cands;
}"""

JS_COUNT = """() => {
  const b = document.body.innerText || '';
  // ⚠️ 2026-10-08：空合集时页面**根本没有**「合集内作品 N」这段文本
  //（截图实证：只有标题 +「点击添加作品」）。旧正则匹配不到返回 -1，
  // 与「面板被服务端清空」混为一谈。
  // 现在区分三种状态：正数 = 计数 / 0 = 确认空 / -1 = 未知。
  const m = b.match(/合集内作品\\s*(\\d+)/);
  if (m) return parseInt(m[1], 10);
  if (/点击添加作品/.test(b)) return 0;
  return -1;
}"""

# 面板是否被服务端错误清空
JS_PANEL_EMPTY = """() => {
  const b = document.body.innerText || '';
  // ⚠️ 2026-10-08 修正：原来把「没有更多视频」当成面板被清空。实测那是
  // **分页到底**的正常文案，不是故障。判据应是「共 0 个作品」或服务端错误。
  if (/共\\s*0\\s*个作品/.test(b)) return true;
  if (/服务器\\/网络开小差了/.test(b)) return true;
  return false;
}"""

# 关掉飘在页面上的错误 toast，避免遮挡底部按钮
JS_CLEAR_TOAST = """() => {
  let n = 0;
  document.querySelectorAll('svg,button,div,span').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.width > 26 || r.height > 26) return;
    if (r.x < 600 || r.x > 990) return;         // toast 关闭钮在中间偏上
    if (r.y < 10 || r.y > 360) return;
    let p = e;
    for (let i = 0; i < 5 && p; i++) {
      if (/开小差了|稍后再试/.test(p.innerText || '')) {
        try { e.click(); n++; } catch (err) {}
        break;
      }
      p = p.parentElement;
    }
  });
  return n;
}"""


def shot(page, out_dir, n):
    try:
        page.screenshot(path=str(Path(out_dir) / n)); print(f"  📸 {n}")
    except Exception:
        pass


def dismiss(page):
    for kw in ("我知道了", "知道了", "以后再说"):
        loc = page.get_by_text(kw, exact=True)
        for i in range(min(loc.count(), 3)):
            try:
                if loc.nth(i).is_visible(timeout=400):
                    loc.nth(i).click(); time.sleep(0.8)
            except Exception:
                pass


def research(page, *, search_kw, out_dir, tries=4):
    """面板被服务端错误清空时，重新搜索把列表拉回来。"""
    for k in range(tries):
        page.evaluate(JS_CLEAR_TOAST)
        time.sleep(1.2)
        try:
            box = page.locator(
                "input[placeholder*='查找作品'], input[placeholder*='作品描述']").first
            box.click()
            box.fill("")
            box.fill(search_kw)
            page.keyboard.press("Enter")
        except Exception as e:
            print(f"    重搜 {k+1} 异常 {type(e).__name__}")
        time.sleep(4.5)
        page.evaluate(JS_CLEAR_TOAST)
        empty = page.evaluate(JS_PANEL_EMPTY)
        n = page.evaluate(JS_PLUS)
        print(f"    重搜 {k+1}: 空={empty} 待加={len(n)}")
        if not empty and n:
            return True
    return False


def _open_picker_and_search(page, *, search_kw, out_dir):
    """打开作品选择面板并搜索本系列（fix/make 两流程共用）。"""
    print("▶ 打开作品面板")
    for kw in ("点击添加作品", "添加上传的视频作品到你的合集里", "添加作品"):
        loc = page.get_by_text(kw, exact=False)
        for i in range(min(loc.count(), 6)):
            try:
                if loc.nth(i).is_visible(timeout=800):
                    loc.nth(i).click(); break
            except Exception:
                continue
        else:
            continue
        break
    time.sleep(5)

    box = page.locator("input[placeholder*='查找作品'], input[placeholder*='作品描述']").first
    box.click(); box.fill(search_kw)
    page.keyboard.press("Enter")
    print(f"  ✓ 搜索「{search_kw}」")
    time.sleep(5)


def _add_loop(page, *, want, search_kw, before, out_dir):
    """逐个补挂（基准循环，douyin_fix_collection 已验证）。

    ⛔ 不要改成「扫文本行 → 去重 → 按序号取第 i 个」（douyin_make_collection
    的 JS_ROWS）：去重每轮都返回 target[0]，12 次点击全落在同一行（缺陷②）。
    JS_PLUS 每轮现取**最上面那支未添加的**（svg 24x24 + 在右侧面板内 + 不含「已添加」），
    已添加的行天然被过滤，不存在「同一行点 12 次」。
    """
    added, fails, researches = [], [], 0
    seen: set[str] = set()      # 已点过的行首文字，防重复点击
    stale = 0                   # 连续取到同一支的次数
    for rnd in range(want + 14):
        cands = page.evaluate(JS_PLUS)
        if not cands:
            # 面板被服务端错误清空了 → 重搜自愈，而不是放弃
            if researches >= 5:
                print(f"  轮{rnd+1}: 面板仍空，重搜次数用尽")
                break
            researches += 1
            print(f"  轮{rnd+1}: 面板无未添加行（第 {researches} 次重搜）")
            if research(page, search_kw=search_kw, out_dir=out_dir):
                continue
            print("    重搜失败，停止")
            break
        c = cands[0]                        # 永远取最上面那支未添加的
        # 滚动进视口中心再取新鲜坐标。几何判据**不再另写一份**——直接拼
        # _JS_GEOM（2026-10-08 之前这里曾另有 `r.x > 1500` 硬编码，两份
        # 漂移后 viewport=1700 找不到元素 → 滚动没发生 → 拿旧坐标点击 →
        # 轮10/11/12 三次都点在同一条希伯来语行上（12 次点击只加进 9 支））。
        page.evaluate("""(y) => {""" + _JS_GEOM + """
            const el = [...document.querySelectorAll('svg')].find(e => {
                const r = e.getBoundingClientRect();
                return Math.abs(r.width-24)<3 && Math.abs(r.height-24)<3
                       && inPanel(r) && Math.abs(Math.round(r.y)-y) < 30; });
            if (el) el.scrollIntoView({block: 'center'});
        }""", c["y"])
        time.sleep(1.0)
        c2 = page.evaluate(JS_PLUS)
        if not c2:
            time.sleep(1.2)
            c2 = page.evaluate(JS_PLUS)
        if not c2:
            researches += 1
            research(page, search_kw=search_kw, out_dir=out_dir); continue
        c = c2[0]
        # ⚠️ 2026-10-08 加的护栏：坐标失效时 JS_PLUS 会反复返回同一支
        # （上一版实测轮10/11/12 连点同一条希伯来语，12 次点击只加进 9 支）。
        # 这里按**行首文字**去重，已点过的直接跳过——
        # 宁可少点，也不要把同一条点 12 次然后拿一个假计数当成功。
        # 去重键 = 行文本前 46 字符（JS_PLUS 里 slice(0,46) 截的）。
        # 假设：各行行首 46 字符互不相同（本系列标题含语种名，天然错开）；
        # 若未来行间共享更长前缀，这里会误跳——那不是本护栏的适用场景。
        key = c["t"].strip()
        if key in seen:
            print(f"  轮{rnd+1}: ⏭ 跳过重复「{key[:24]}」（坐标可能已失效）")
            stale += 1
            if stale >= 6:
                print("  ⚠️ 连续多次取到同一支，判定位失效，停止本轮")
                break
            # 面板没刷新：滚一下再取，避免死循环
            page.mouse.wheel(0, 420); time.sleep(1.0)
            continue
        stale = 0
        seen.add(key)
        px, py = c["x"] + 12, c["y"] + 12
        try:
            page.mouse.click(px, py)
            time.sleep(2.2)
            page.evaluate(JS_CLEAR_TOAST)
            added.append(c["t"])
            print(f"  轮{rnd+1}: ✓ 加「{c['t'][:30]}」  累计 {len(added)}")
        except Exception as e:
            fails.append(c["t"])
            print(f"  轮{rnd+1}: ✗ {c['t'][:30]} → {type(e).__name__}")
            time.sleep(1.5)
        if len(added) + before >= want:
            break
    return added, fails


def fix_collection(page, *, title, want, search_kw, out_dir) -> dict:
    """编辑已有合集，补挂缺失作品 → 计数核对 → 达标才保存。

    返回 log dict（原版落盘 fix-collection.json 的内容 + 退出状态在 ok_count）。
    计数不符就不点「保存」、保留现场——修改类操作的默认保守（纪律 15/19）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []

    page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
    time.sleep(10); dismiss(page)

    # ---- 定位合集卡片 ----
    print("▶ 打开合集编辑页")
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
        print("  ✗ 找不到合集卡片，中止")
        log.append({"stage": "abort", "reason": "card-not-found"})
        (out_dir / "fix-collection.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": False, "log": log}
    card.scroll_into_view_if_needed(); time.sleep(0.8)
    card.locator("[class*='new-layout-action-']").first.click()
    time.sleep(6)
    shot(page, out_dir, "fix-01-edit-open.png")

    before = page.evaluate(JS_COUNT)
    print(f"  编辑页「合集内作品」= {before}")
    log.append({"stage": "open", "before": before})
    if before > want:
        print(f"  ⚠ 已有 {before} > 预期 {want} —— 仍按补挂逻辑继续")

    _open_picker_and_search(page, search_kw=search_kw, out_dir=out_dir)
    shot(page, out_dir, "fix-02-searched.png")

    # ---- 逐个补挂（基准：JS_PLUS svg 选择器，缺陷②修复） ----
    added, fails = _add_loop(page, want=want, search_kw=search_kw,
                             before=before, out_dir=out_dir)
    shot(page, out_dir, "fix-03-all-added.png")

    # ---- 关闭面板 ----
    print("▶ 关闭作品面板")
    try:
        page.locator("[class*='semi-modal-close'], [class*='icon-close']").first.click(timeout=3000)
    except Exception:
        page.mouse.click(700, 300)
    time.sleep(2)
    # 若面板还在，按 ESC
    if page.evaluate(JS_PLUS):
        page.keyboard.press("Escape"); time.sleep(2)
    shot(page, out_dir, "fix-04-panel-closed.png")

    after = page.evaluate(JS_COUNT)
    print(f"\n  「合集内作品」= {after}（预期 {want}）")
    log.append({"stage": "added", "count": after, "added": added, "fails": fails})

    if after != want:
        print(f"  ✗ 数量不符（{after} != {want}），不点保存，保留现场")
        (out_dir / "fix-collection.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": False, "count": after, "log": log}
    print("▶ 点「保存」")
    page.get_by_text("保存", exact=True).first.scroll_into_view_if_needed()
    time.sleep(0.8)
    page.get_by_text("保存", exact=True).first.click()
    time.sleep(7)
    shot(page, out_dir, "fix-05-saved.png")
    print(f"  URL {page.url}")
    b2 = page.inner_text("body", timeout=10000)
    back = title in b2
    print(f"  返回列表页: {back}")
    log.append({"stage": "saved", "url": page.url, "back_to_list": back})
    for kw in ("保存成功", "操作成功", "创建成功"):
        if kw in b2:
            print(f"  成功提示: {kw}")

    (out_dir / "fix-collection.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": back, "count": after, "log": log}


def create_collection(page, *, title, desc, cover, want, search_kw, out_dir) -> bool:
    """创建合集：填表 + 上传封面 + 打开作品选择面板 + JS_PLUS 挂 want 支 → 创建。

    表单/封面/面板步骤搬运自 douyin_make_collection.py / douyin_collection_step1.py
    （这些步骤实测有效）；挂作品环节**不用** make 版的 JS_ROWS 循环（缺陷②），
    走 fix 版的 _add_loop（JS_PLUS）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
    time.sleep(9); dismiss(page)

    print("▶ 打开创建合集")
    page.get_by_text("创建合集", exact=True).first.click(); time.sleep(3)

    ti = page.locator("input[placeholder*='合集的标题']").first
    ti.click(); ti.fill(title)
    de = page.locator("textarea[placeholder*='合集的简介']").first
    de.click(); de.fill(desc)
    print(f"  ✓ 标题「{title}」({len(title)}/20)  简介({len(desc)}/200)")

    page.locator("input[type=file]").first.set_input_files(str(cover))
    time.sleep(4)
    # 封面上传后会弹裁剪框 → 点「保存」确认（方图无裁切）
    for kw in ("保存", "确定", "完成"):
        loc = page.get_by_text(kw, exact=True)
        for i in range(min(loc.count(), 4)):
            try:
                if loc.nth(i).is_visible(timeout=900):
                    loc.nth(i).click(); print(f"  ✓ 封面裁剪「{kw}」"); time.sleep(2); break
            except Exception:
                continue
        else:
            continue
        break
    shot(page, out_dir, "create-01-cover-ok.png")

    _open_picker_and_search(page, search_kw=search_kw, out_dir=out_dir)
    shot(page, out_dir, "create-02-searched.png")

    added, fails = _add_loop(page, want=want, search_kw=search_kw, before=0,
                             out_dir=out_dir)
    shot(page, out_dir, "create-03-added.png")
    print(f"\n  共加入 {len(added)} 支（失败 {len(fails)}）")

    # 关闭抽屉：ESC + 点抽屉外空白
    try:
        page.keyboard.press("Escape"); time.sleep(1.5)
    except Exception:
        pass
    page.mouse.click(700, 500); time.sleep(2)
    shot(page, out_dir, "create-04-before-create.png")

    body = page.inner_text("body", timeout=8000)
    print("\n=== 合集内作品区 ===")
    i = body.find("合集内作品")
    print("  " + (body[i:i+200].replace("\n", " | ") if i >= 0 else "（未找到）"))

    # 创建
    btn = page.get_by_text("创建", exact=True).first
    btn.scroll_into_view_if_needed(); time.sleep(0.8)
    btn.click()
    print("\n  ✓ 点「创建」")
    time.sleep(6)
    shot(page, out_dir, "create-05-created.png")
    print(f"  URL {page.url}")
    body2 = page.inner_text("body", timeout=8000)
    ok = title in body2
    print(f"  页面含新合集名：{ok}")
    return ok
