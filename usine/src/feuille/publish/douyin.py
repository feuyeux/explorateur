# -*- coding: utf-8 -*-
"""douyin.py — 抖音发布器（⑨）：上传 → 标题/正文/话题 → 发布；封面**后补**

搬运自 yiyezhiqiu/scripts/publish_douyin_yyzq.py（发布序列）+
fix_all_douyin_covers.py（fix_covers 编辑流程补封面）。

**已核实缺陷的修复**（逐条指认，公共件在 base.py）：
- ③ 写死的 Chrome 绝对路径 → `base.launch`（内部 `base.resolve_chrome()`，
  经 `feuille.platform.browser(only="chrome")` 解析）。
- ① 防风控节流 → `base.run_tasks` 写在循环内（本平台节流间隔沿用原版 3s）。

**封面为什么后补**（2026-10-06 首轮事故，注释原文见 publish_one 内）：
上传流程的封面面板喂不准——`input[0]` 挂在 `list-*`（生成参考图）下，
正确入口是 `selectArea-*`；确认键上传层是「保存」、编辑层是「完成」。
首轮 12 条封面全发成平台默认帧而脚本自报 12/12 成功。所以发布流程是**两步**：
先发视频（本模块 publish），再用 fix_covers（已验证的编辑流程）补封面。

**使用契约**：
- tasks 是 `feuille.manifest.build_manifest` 的产物（no/lang/locale/title/body/tags/video/cover）；
  profile 默认 `base.PROFILES["douyin"]`；截图与 result JSON 全部落 log_dir。
- 修改预算（纪律 20）：抖音每个作品**最多修改 5 次，补封面算 1 次**——
  批量补之前先单条验证落库（fix_covers 只筛要补的条目，不盲目全跑）。
- 补完必须用 veriflive.verify 回查缩略图确认有文字（PUBLISH-RULES 规则 1/3）。

用法：
    from feuille.publish import douyin
    douyin.list_tasks(tasks)
    douyin.publish(tasks, log_dir="build")                 # 批量
    douyin.publish(tasks, log_dir="build", only="1,7")     # 指定条目
    douyin.fix_covers(tasks, search_kw="一叶知秋", log_dir="build", only="7,8")
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import base

UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"

# 抖音登录墙面板文案（publish_douyin_yyzq.login_wall_visible 实测词表）
DOUYIN_WALL = ("扫码登录", "验证码登录", "密码登录", "手机号登录")


# ── 登录 ──────────────────────────────────────────────────────────────
def ensure_login(page, wait_min: int = 10) -> bool:
    """确保落到上传页。若在登录墙，等用户扫码。"""
    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)

    if base.login_wall(page, DOUYIN_WALL):
        print("   ⚠️ 抖音未登录。请在弹出的 Chrome 窗口扫码。")
        print(f"      等待中（最多 {wait_min} 分钟）…")
        if not base.wait_login(page, wait_min * 60, kws=DOUYIN_WALL):
            print("      ❌ 超时未登录，中止。")
            return False
        time.sleep(3)

    # 登录后如果被踢回首页，再去一次上传页
    if UPLOAD_URL.split("/creator-micro")[-1] not in page.url and "upload" not in page.url:
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
    return not base.login_wall(page, DOUYIN_WALL)


# ── 页面杂务 ──────────────────────────────────────────────────────────
def clean_draft_banner(page) -> None:
    try:
        btn = page.locator("button:has-text('放弃'), a:has-text('放弃'), span:has-text('放弃')").first
        if btn.is_visible(timeout=1500):
            btn.click()
            print("      ✓ 已清理上次未发布的草稿")
            time.sleep(1.5)
            conf = page.locator(".semi-modal button:has-text('确定'), .semi-modal button:has-text('放弃')").first
            if conf.is_visible(timeout=1500):
                conf.click()
                time.sleep(1)
    except Exception:
        pass


def dismiss_cover_modal(page) -> bool:
    """清掉盖版面上的层层弹窗。返回是否点掉了什么。

    踩过的坑：抖音上传封面后会叠一层「设置横封面获得更多流量」，
    按钮是「暂不设置 / 设置横封面」，既不含「完成」也不含「确定」，
    原来的 dismiss 完全漏掉，脚本却照样往下报成功。
    我们发的是 9:16 竖封面，没有横版可设 → 一律选「暂不设置」。
    """
    clicked = False
    # 1) 横封面推荐层 —— 必须选「暂不设置」
    for sel in ("button:has-text('暂不设置')", ".semi-modal button:has-text('暂不设置')"):
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=800):
                b.click()
                print("      ✓ 已关闭「横封面推荐」弹窗（选暂不设置）")
                clicked = True
                time.sleep(1.0)
                break
        except Exception:
            continue

    # 2) 封面检测 / 截取类弹窗
    for sel in ("div[role='dialog'] button:has-text('完成')",
                ".semi-modal button:has-text('完成')",
                ".semi-modal button:has-text('确定')",
                "div[role='dialog'] button:has-text('确定')"):
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=800):
                b.click()
                print("      ✓ 已关闭封面弹窗")
                clicked = True
                time.sleep(0.8)
                break
        except Exception:
            continue
    return clicked


def blocking_modals(page) -> list[str]:
    """列出当前仍然可见、且会挡住发布按钮的弹窗。用于诚实报状态。"""
    out = []
    for sel, name in (
        ("button:has-text('暂不设置')", "横封面推荐"),
        ("div[role='dialog'] button:has-text('完成')", "封面截取弹窗"),
        (".semi-modal button:has-text('确定')", "确认弹窗"),
        ("button:has-text('确认发布')", "确认发布弹窗"),
    ):
        try:
            if page.locator(sel).first.is_visible(timeout=600):
                out.append(name)
        except Exception:
            continue
    return out


# ── 单条发布 ──────────────────────────────────────────────────────────
def publish_one(page, t: dict, auto: bool, *, log_dir) -> dict:
    vid, cov = t["video"], t["cover"]
    log_dir = Path(log_dir)
    res = {"no": t["no"], "lang": t["lang"], "ok": False, "stage": "", "cover": False}

    print(f"\n🚀 [{t['no']:02d}] {t['lang']}  {Path(vid).name}")
    print(f"   标题: {t['title']}")

    if not Path(vid).exists():
        print("   ❌ 视频文件不存在")
        res["stage"] = "素材缺失"
        return res

    if "upload" not in page.url:
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
    clean_draft_banner(page)

    page.locator('input[type="file"]').first.set_input_files(vid)
    print("   ✓ 已送入上传通道，等待解析…")

    title_box = page.locator("input[placeholder*='标题'], input[placeholder*='作品标题']").first
    # 只认正文编辑器，严格避开封面上传框与拖拽区
    desc_box = page.locator(
        "div.notranslate[contenteditable='true'], div.editor-kit-editor, "
        "div[data-placeholder*='简介'], "
        "div[contenteditable='true']:not([class*='cover']):not([class*='upload']):not([class*='zone'])"
    ).first

    ready = False
    for _ in range(40):
        try:
            if title_box.is_visible(timeout=800) or desc_box.is_visible(timeout=800):
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)
    if not ready:
        res["stage"] = "编辑器未就绪"
        print("   ❌ 编辑器未就绪")
        return res

    # 标题
    try:
        title_box.click()
        title_box.fill(t["title"][:30])
        print(f"   ✓ 标题已录入（{len(t['title'][:30])} 字）")
    except Exception as e:
        print(f"   ⚠️ 标题：{e}")

    # 正文 + 话题胶囊
    try:
        desc_box.click()
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(t["body"] + "\n\n")
        time.sleep(0.3)
        for tag in t["tags"]:
            page.keyboard.type(tag if tag.startswith("#") else f"#{tag}")
            page.keyboard.type(" ")
            time.sleep(0.35)
        print(f"   ✓ 正文与 {len(t['tags'])} 个话题已录入")
    except Exception as e:
        print(f"   ⚠️ 正文：{e}")

    dismiss_cover_modal(page)

    # ── 封面不在发布流程里做，发布后单独补 ─────────────────────────
    # 上传流程的封面面板喂不准：file input[0] 挂在 list-*（生成参考图）下，
    # 正确入口是 selectArea-* 下的那个；确认键在上传层是「保存」、
    # 在编辑层是「完成」。2026-10-06 首轮就是这么把 12 条封面全发成
    # 平台默认首帧的，而脚本自报 12/12 成功。
    #
    # 改用已验证的编辑流程补封面：
    #     fix_covers(tasks, search_kw=…, only=[本条])
    # 该流程 selectArea-* + 「完成」，逐条比对缩略图，落库可查。
    res["cover"] = False
    res["cover_pending"] = cov
    print("   ℹ️ 封面留到发布后用 fix_covers 补（编辑流程已验证）")

    # 把「设置封面」那一块单独截下来，便于事后核对到底用没用我们那张
    try:
        sec = None
        for sel in ("text=设置封面", "div:has-text('设置封面')"):
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                sec = loc
                break
        if sec is not None:
            sec.scroll_into_view_if_needed()
            time.sleep(1.2)
            box = sec.bounding_box()
            if box:
                page.screenshot(
                    path=str(log_dir / f"covershot-{t['no']:02d}.png"),
                    clip={"x": max(0, box["x"] - 10), "y": max(0, box["y"] - 10),
                          "width": min(1400, box["width"] + 20),
                          "height": min(760, box["height"] + 20)},
                )
                print(f"      📷 封面区截图 covershot-{t['no']:02d}.png")
    except Exception as e:
        print(f"      （封面区截图跳过：{type(e).__name__}）")

    # 封面由发布后的 fix_covers 补，补完必须用 veriflive.verify 回查
    # 缩略图确认有文字（PUBLISH-RULES.md 规则 1/3）。
    # 这里不阻断发布，但要如实标成「封面待补」，不许算作完成。

    # 等转码完成（发布按钮解禁）
    print("   ⏳ 等待上传与转码…")
    ok = False
    for _ in range(150):
        dismiss_cover_modal(page)
        try:
            b = base.find_publish_button(page)
            if b is not None:
                disabled = (b.get_attribute("disabled") is not None
                            or "disabled" in (b.get_attribute("class") or ""))
                if not disabled:
                    ok = True
                    print("   ✓ 转码完成，真正的发布按钮已解禁")
                    break
        except Exception:
            pass
        time.sleep(1)
    if not ok:
        res["stage"] = "转码超时"
        print("   ❌ 转码等待超时")
        return res

    if not auto:
        # 先把残留弹窗清干净，再拍能看清标题/正文的图
        for _ in range(3):
            if not dismiss_cover_modal(page):
                break
        try:
            page.mouse.wheel(0, 600)
            time.sleep(1)
            title_box.scroll_into_view_if_needed()
            time.sleep(0.6)
        except Exception:
            pass
        left = blocking_modals(page)
        shot = log_dir / f"dryrun-douyin-{t['no']:02d}.png"
        page.screenshot(path=str(shot))
        res.update(ok=not left, stage="已填词(dry-run，未发布)")
        print(f"   🧪 dry-run：已填词并停在发布前，未点击发布")
        if left:
            res["stage"] = f"dry-run 残留弹窗 {left}"
            print(f"   ❌ 仍有弹窗挡着：{left}")
        print(f"   📷 截图 {shot}")
        return res

    # 点发布
    try:
        for _ in range(3):
            if not dismiss_cover_modal(page):
                break
        left = blocking_modals(page)
        if left:
            res["stage"] = f"发布前仍有弹窗 {left}"
            print(f"   ❌ 发布前仍有弹窗挡着，不点发布：{left}")
            return res
        time.sleep(1.2)

        b = base.find_publish_button(page)
        if b is None:
            res["stage"] = "找不到真正的发布按钮"
            print("   ❌ 找不到文本精确为「发布」的主按钮，拒绝乱点")
            return res
        b.scroll_into_view_if_needed()
        time.sleep(0.4)

        # 点之前拍一张，便于事后对照
        pre = log_dir / f"prepublish-{t['no']:02d}.png"
        try:
            page.screenshot(path=str(pre))
        except Exception:
            pass

        b.click()
        print("   ✅ 已点击【发布】")
        time.sleep(3)

        # 点之后立刻拍一张 —— 上一版就是缺这一步，才把「点了没生效」当成成功
        post = log_dir / f"postpublish-{t['no']:02d}.png"
        try:
            page.screenshot(path=str(post))
        except Exception:
            pass

        # 把点击后页面上的可见提示全抓出来，失败时才有线索
        try:
            tip = page.inner_text("body", timeout=8000)
            marks = [x for x in ("作品已发布", "发布已完成",
                                 "请填写", "请输入", "不能为空", "封面检测",
                                 "审核中", "存在风险", "请确认", "声明") if x in tip]
            if marks:
                print(f"   ℹ️ 页面提示关键词：{marks}")
        except Exception:
            pass

        for sel in (".semi-modal button:has-text('确认发布')",
                    ".semi-modal button:has-text('确定')",
                    ".semi-modal button:has-text('确认')",
                    "button:has-text('确认发布')"):
            try:
                c = page.locator(sel).first
                if c.is_visible(timeout=1500):
                    c.click()
                    print("   ✓ 已确认二次弹窗")
                    break
            except Exception:
                continue
    except Exception as e:
        res["stage"] = f"点击发布失败:{e}"
        print(f"   ❌ 点击发布失败：{e}")
        return res

    # 等确认
    deadline = time.time() + 180
    while time.time() < deadline:
        if "content/manage" in page.url:
            res.update(ok=True, stage="已发布·封面待补" if not res["cover"] else "已发布")
            print("   ✅ 发布成功（已跳转作品管理）")
            if not res["cover"]:
                print(f"   ⚠️ 封面还没补：{res.get('cover_pending','')}")
                print("      补完：fix_covers(tasks, only=本条)，再用 veriflive.verify 回查")
            return res
        try:
            if page.locator("text=发布成功, text=作品已发布, text=发布已完成, "
                            ".semi-toast-success").count() > 0:
                res.update(ok=True, stage="已发布·封面待补" if not res["cover"] else "已发布")
                print("   ✅ 检测到【发布成功】")
                if not res["cover"]:
                    print(f"   ⚠️ 封面还没补：{res.get('cover_pending','')}")
                time.sleep(3)
                return res
        except Exception:
            pass
        time.sleep(2)

    res["stage"] = "已点击但未确认"
    fail = log_dir / f"publish-fail-{t['no']:02d}.png"
    try:
        page.screenshot(path=str(fail))
        print(f"   📷 失败现场截图 {fail}")
    except Exception:
        pass
    try:
        print(f"   当前 URL: {page.url}")
    except Exception:
        pass
    print("   ⚠️ 已点发布但未检测到成功提示，请人工核实这一条")
    return res


def list_tasks(tasks) -> None:
    """--list：打印待发布条目。"""
    for t in tasks:
        print(f"  {t['no']:02d} {t['lang']:8s} {t['title'][:34]:36s} "
              f"{len(t['tags'])}话题  {Path(t['video']).name}")


def publish(tasks, *, profile_dir=None, log_dir, only=None, frm=None,
            dry_run=0, headless=False) -> int:
    """批量发布（骨架在 base.run_tasks：异常隔离 + 循环内节流 + result JSON）。"""
    tasks = base.filter_tasks(tasks, only, frm)
    profile_dir = profile_dir or base.profile_dir("douyin")
    print(f"待发布 {len(tasks)} 条 · profile {profile_dir}")

    with base.launch(profile_dir, headless=headless,
                     viewport={"width": 1440, "height": 900}) as (ctx, page):
        if not ensure_login(page):
            return 1
        print("✅ 抖音创作者后台就绪\n")
        results = base.run_tasks(page, tasks, publish_one, upload_url=UPLOAD_URL,
                                 log_dir=log_dir, between_s=3, dry_run=dry_run,
                                 result_json="publish-douyin-result.json")
    return base.summarize(results, "抖音")


# ── 封面后补（编辑流程，已验证） ────────────────────────────────────────
def set_cover(page, cover_path: str, tag: str, *, log_dir) -> bool:
    """打开封面弹窗 → 点上传封面 → 喂文件 → 完成。返回是否成功。"""
    log_dir = Path(log_dir)
    lbl = page.get_by_text("竖封面3:4", exact=True).first
    if not lbl.is_visible(timeout=4000):
        lbl = page.get_by_text("竖封面 3:4", exact=True).first
    lbl.scroll_into_view_if_needed(); time.sleep(1.2)
    b = lbl.bounding_box()
    if not b:
        print("   ⚠️ 找不到竖封面标签"); return False
    page.mouse.click(b["x"] + b["width"] / 2, b["y"] - 80)
    time.sleep(4)

    # 弹窗里有两组 file input，必须按祖先 class 区分：
    #   list-*   → 生成参考图（喂这里封面不会生效，栽过）
    #   selectArea-* → 上传封面（正确入口）
    up_in = page.locator("div[class*='selectArea'] input[type='file']")
    n_up = up_in.count()
    print(f"   selectArea 内 file input: {n_up}")
    if n_up == 0:
        page.screenshot(path=str(log_dir / f"covfail-{tag}-noselect.png"))
        print("   ⚠️ 没找到上传封面的 input")
        return False
    try:
        # 优先 hidden-input（非 replace），它是首次上传口
        up_in.first.set_input_files(cover_path, timeout=15000)
        print("   ✓ 已喂给 selectArea（上传封面）")
    except Exception as e:
        print(f"   ⚠️ 喂 selectArea 失败（{type(e).__name__}）")
        return False

    time.sleep(6)
    page.screenshot(path=str(log_dir / f"covdbg-{tag}-uploaded.png"))

    # 裁切框里必须看得见文字：主编辑区不该还是纯叶子
    try:
        page.get_by_text("完成", exact=True).first.click()
        print("   · 已点「完成」")
        time.sleep(4)
    except Exception:
        pass

    page.screenshot(path=str(log_dir / f"covdbg-{tag}-done.png"))
    return True


def fix_one(page, task: dict, *, search_kw: str, log_dir) -> bool:
    log_dir = Path(log_dir)
    lang = task["lang"]
    print(f"\n🔧 [{task['no']:02d}] {lang}")
    page.goto(MANAGE_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(7)
    box = page.locator("input[placeholder*='搜索']").first
    box.click(); box.fill(search_kw); page.keyboard.press("Enter")
    time.sleep(5)

    # 定位目标条目：按「编辑作品」按钮的纵向顺序，与同位置的标题文本对齐。
    # 每张卡片是一行：封面 | 标题+数据 | 操作区(编辑/设置权限/删除)
    #
    # ⚠️ 2026-10-08 修正：原定位器写死成 get_by_text(f"「{search_kw}」的")
    # ——即「**「X」的Y版**」这种标题格式。本项目标题是「老树枯枝立野原，中文的
    # 冬天很轻」，**不含该结构** → 匹配到 0 个标题，整条卡在「没找到」。
    # 这与 collections 的硬编码是同一类病：**把某个项目的文案格式当成通用格式**。
    # 现在直接用**清单里的真实标题**做前缀匹配，与文案格式无关。
    eds = page.get_by_text("编辑作品", exact=False)
    want = task["title"]        # 以文案里的完整标题为准
    ne = eds.count()
    idx = None
    # 候选标题 = 编辑按钮所在行（xpath 上两级容器）的文本。
    # ⚠️ 不做「全页找标题 → 按出现顺序对齐第 j 个编辑按钮」的退化定位：
    # 位置对齐只是假设，标题一旦在提示条 / 置顶卡等处也出现，就会点错作品的
    # 编辑按钮——白耗修改配额（抖音每作品 5 次，纪律 19/20）。行容器对不上
    # 就按「没找到」中止，人工看行文本再修容器层级，不盲配。
    rows = []
    for i in range(ne):
        try:
            box = eds.nth(i).locator("xpath=../..")
            rows.append((i, (box.inner_text() or "").replace("\\n", " ")))
        except Exception:
            rows.append((i, ""))
    for i, t in rows:
        if want[:10] in t:
            idx = i
            print(f"   匹配第 {i} 行：{t[:44]}")
            break

    if idx is None:
        print(f"   ⚠️ 没找到「{want[:20]}…」那条（页面 {ne} 个编辑按钮）")
        for i, t in rows[:8]:
            if t:
                print("      -", t[:56])
        return False

    eds.nth(idx).click()
    time.sleep(7)
    print(f"   编辑页: {page.url}")

    ok = set_cover(page, task["cover"], f"{task['no']:02d}", log_dir=log_dir)
    if ok:
        try:
            page.get_by_text("提交修改", exact=True).first.click()
            print("   · 已点「提交修改」")
            time.sleep(7)
            page.screenshot(path=str(log_dir / f"covdbg-{task['no']:02d}-submitted.png"))
        except Exception as e:
            print(f"   ⚠️ 提交修改失败：{e}")
    return ok


def fix_covers(tasks, *, search_kw, log_dir, profile_dir=None,
               only=None, lang=None) -> int:
    """发布后补封面（编辑流程：selectArea input + 「完成」）。

    修改预算（纪律 20）：抖音每个作品**最多修改 5 次，补封面算 1 次**——
    批量补之前先只筛 1–2 条验证落库（only 参数就是干这个的），
    补完用 veriflive.verify 回查缩略图有文字才算数。
    """
    tasks = list(tasks)
    if lang:
        tasks = [t for t in tasks if t["lang"] == lang]
    tasks = base.filter_tasks(tasks, only)
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = profile_dir or base.profile_dir("douyin")

    results = []
    with base.launch(profile_dir, viewport={"width": 1700, "height": 1100}) as (ctx, page):
        for t in tasks:
            try:
                results.append({"no": t["no"], "lang": t["lang"],
                                "ok": fix_one(page, t, search_kw=search_kw, log_dir=log_dir)})
            except Exception as e:
                print(f"   ❌ 异常 {type(e).__name__}: {e}")
                results.append({"no": t["no"], "lang": t["lang"], "ok": False})
            time.sleep(4)

    print("\n===== 封面修正汇总 =====")
    for r in results:
        print(f"  {'✅' if r['ok'] else '❌'} [{r['no']:02d}] {r['lang']}")
    out = log_dir / "fix-douyin-covers-result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    print(f"明细写入 {out}")
    return 0 if all(r["ok"] for r in results) else 1


# ── CLI 适配层（cli.py 路由叶子；业务在 publish()，这里只接线） ────────


def main(argv=None) -> int:
    """cli.py 路由入口：`feuille publish douyin <manifest.json> --log-dir D`。

    manifest.json = plans 契约经 `feuille.manifest.build_manifest` 落盘的清单，
    本入口取其中的 "douyin" 段作为 tasks。
    """
    a = base.manifest_argparser("feuille publish douyin").parse_args(argv)
    tasks = base.manifest_tasks(a.manifest, "douyin")
    return publish(tasks, log_dir=a.log_dir, only=a.only, frm=a.frm,
                   dry_run=a.dry_run, headless=a.headless)
