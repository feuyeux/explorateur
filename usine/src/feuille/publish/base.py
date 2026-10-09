# -*- coding: utf-8 -*-
"""base.py — 发布器共享骨架（⑨）：三份发布器的公共结构拆成可测小函数

平台特有逻辑在 douyin.py / xhs.py / bilibili.py。两条硬约定：
- `run_tasks` 的防风控节流写在**循环内**（每条之间都睡；实测连发 2 条就撞风控）。
- `resolve_chrome()` 经 `feuille.platform.browser(only="chrome")` 解析，
  找不到显式报缺（SystemExit），绝不编路径、绝不退化成「系统默认」；
  `FEUILLE_BROWSER` 环境变量可临时覆盖。

使用契约：
- playwright **只在函数内 lazy import**：主环境不装 playwright 也必须能
  `import feuille.publish`；发布前先 `uv sync --group publish`。
- 任务来源参数化：`tasks` 是 `feuille.manifest.build_manifest` 的产物
  （no / lang / locale / title / body / tags / video / cover），本模块不读写死路径。
- profile 默认值是 PROFILES 平台表里的数据，登录态存盘勿删。
- 认证与风控一律人工（纪律 21）：wait_login / wait_risk_clear 只等待、绝不代填、
  绝不自动重试；解除后必须确认遮罩真的消失。
"""
from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------- 平台 profile 表
# 各平台持久 user-data 目录（登录态存盘勿删）。作为数据放在表里，不散落在代码里。
PROFILES: dict[str, str] = {
    "douyin":      "~/.douyin_creator_profile",
    "xiaohongshu": "~/.xhs_creator_profile",
    "bilibili":    "~/.bili_creator_profile",
    "zhihu":       "~/.zhihu_creator_profile",
}


def profile_dir(platform: str) -> str:
    """平台持久 profile 目录（展开后的绝对路径）。"""
    try:
        raw = PROFILES[platform]
    except KeyError:
        raise SystemExit(f"未知平台 {platform!r}（合法：{sorted(PROFILES)}）") from None
    return os.path.abspath(os.path.expanduser(raw))


def resolve_chrome() -> str:
    """Chrome 可执行文件绝对路径——**唯一入口**，发布器一律从这里拿（缺陷③修复）。

    经 `feuille.platform.browser(only="chrome")` 解析（发布 profile 与 Chrome 绑定，
    所以只认 Chrome，不吃 Edge 候选；`FEUILLE_BROWSER` 环境变量可临时覆盖做 A/B）。
    找不到 = 显式报缺并中止，绝不编造路径、绝不退化成 Playwright 自带浏览器。
    """
    from .. import platform as _platform
    b = _platform.browser(only="chrome")
    if b is None:
        raise SystemExit(
            "找不到 Chrome：发布器用系统 Chrome + 持久 profile（自带 Chromium 没有登录态）。"
            "装 Google Chrome，或设 FEUILLE_BROWSER 指向可执行文件。")
    return b[1]


@contextmanager
def launch(profile_dir_, *, headless=False, viewport=None, args=None):
    """Chrome 持久 profile 启动（系统 Chrome 经 resolver 解析，缺陷③修复）。

    用法：
        with base.launch(base.profile_dir("douyin")) as (ctx, page):
            ...
    退出 with 即关闭 context —— 关闭才把 cookie 写进 profile（登录态落盘）。
    """
    from playwright.sync_api import sync_playwright
    exe = resolve_chrome()
    user_data_dir = os.path.abspath(os.path.expanduser(profile_dir_))
    os.makedirs(user_data_dir, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, executable_path=exe, headless=headless,
            viewport=viewport or {"width": 1440, "height": 900},
            args=args if args is not None else
            ["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        yield ctx, page
        ctx.close()


# ---------------------------------------------------------------- 登录墙
# 登录墙关键词（各平台后台实测过的面板文案，按平台传自己的子集）
WALL_DEFAULT = ("扫码登录", "验证码登录", "密码登录", "手机号登录", "立即登录", "登录后")


def login_wall(page, kws: tuple[str, ...] = WALL_DEFAULT) -> bool:
    """登录墙判定：只信**可见**文本。

    踩过的坑（login_helper._visible_texts 同源教训）：登录弹窗是浮层，
    底层页面的「作品管理」等文案仍躺在 body 文本里，按 inner_text('body')
    判会把「未登录」误判成「已登录」——必须逐关键词 get_by_text + is_visible。
    """
    for kw in kws:
        try:
            loc = page.get_by_text(kw, exact=False)
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


def wait_login(page, timeout_s=600, *, poll_s=3, kws: tuple[str, ...] = WALL_DEFAULT) -> bool:
    """人工扫码等待（纪律 21：认证一律人工，agent 不代填）。墙消失即返回 True。"""
    deadline = time.time() + timeout_s
    tick = 0
    while time.time() < deadline:
        if not login_wall(page, kws):
            print("   ✅ 已检测到登录完成")
            return True
        if tick % 10 == 0:
            print(f"   ⏳ 仍在等待扫码…（余 {int((deadline - time.time()) // 60) + 1} 分钟）")
        tick += 1
        time.sleep(poll_s)
    print("   ❌ 超时未登录，中止。")
    return False


# ---------------------------------------------------------------- 发布按钮
# 真正的「发布」按钮：角色=button 且文本**精确**等于「发布」。
# 踩过的坑：原来用 `button:has-text('发布')` 做子串匹配，
# 而左上角导航有个「作品发布」按钮也含「发布」二字且不含
# 定时/视频/图文/全景/文章，于是 .first 一直点中它 —— 点完只跳草稿页，
# 脚本却自报「已发布」。文本必须 exact，且排除「作品发布」这类导航。
PUB_BTN_EXACT = 'button:text-is("发布")'


def find_publish_button(page, texts: tuple[str, ...] = ("发布",)):
    """返回真正的发布按钮；找不到返回 None。绝不退回子串匹配。"""
    for txt in texts:
        try:
            loc = page.locator(f'button:text-is("{txt}")')
            n = loc.count()
            for i in range(n):
                b = loc.nth(i)
                if not b.is_visible(timeout=500):
                    continue
                cls = b.get_attribute("class") or ""
                t = (b.inner_text() or "").strip()
                if t != txt:
                    continue
                # 主按钮的 class 里带 primary
                if "primary" not in cls.lower():
                    continue
                return b
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- 成功判定
def wait_success(page, words, timeout_s=120, poll_s=2) -> bool:
    """成功词表判定：轮询 body 可见文本，命中任一**全词**即 True（只读，不点任何东西）。

    B 站成功页文案是「稿件投递成功」全词——v1 词表缺「投递」二字，11 条实际
    已进后台的稿件全被判成「已提交未确认」（见 bilibili.BILI_SUCCESS_WORDS 的坑注）。
    词表由平台模块以数据传入，本函数不做任何默认兜底：词表缺词 = 判不出成功，
    这正是如实报「未确认」而不是谎报成功的底线。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            tip = page.inner_text("body", timeout=8000)
            if any(k in tip for k in words):
                return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


# ---------------------------------------------------------------- 风控
# 风控词表（小红书实测撞过；其他平台复用时按平台传入自己的词表）
RISK_WORDS = ("Scan to verify", "发布失败，请稍后重试", "操作过于频繁", "请稍后再试")


def risk_hit(page, kws: tuple[str, ...] = RISK_WORDS) -> bool:
    """检测平台风控弹窗/提示。

    撞上风控时**不能**自动重试——只会越撞越死。必须停下来让用户本人扫码。
    """
    try:
        txt = page.inner_text("body", timeout=6000)
    except Exception:
        return False
    return any(k in txt for k in kws)


def modal_mask(page, sel: str = ".d-modal-mask, .d-modal-wrapper"):
    """读遮罩浮层的几何与样式（display/opacity/宽高）——「遮罩还在不在」的判据。"""
    try:
        return page.evaluate("""(sel) => {
            const m = document.querySelector(sel);
            if (!m) return null;
            const r = m.getBoundingClientRect();
            const cs = getComputedStyle(m);
            return {w: Math.round(r.width), h: Math.round(r.height),
                    disp: cs.display, opa: cs.opacity};
        }""", sel)
    except Exception:
        return None


def wait_risk_clear(page, *, no=0, log_dir, limit_min=10, kws=RISK_WORDS,
                    mask_sel=".d-modal-mask, .d-modal-wrapper",
                    hint="完成扫码验证", reset=None) -> bool:
    """等用户扫码。浏览器窗口保持打开，等风控解除再返回 True。

    解除后**必须**确认遮罩真的没了——扫码后那层遮罩常常还在，
    文本没了但遮罩留着，不重置的话下一条必挂。
    reset：平台自己的「回干净页」函数（如 xhs.reset_page），None 则只按 Esc。
    """
    shot = Path(log_dir) / f"risk-{no:02d}.png"
    try:
        page.screenshot(path=str(shot))
    except Exception:
        pass
    print("\n🛑 撞上平台风控，需要你本人扫码验证")
    print(f"   📸 {shot}")
    print(f"   请在弹出的 Chrome 窗口里{hint}（最多等 {limit_min} 分钟）…")
    deadline = time.time() + limit_min * 60
    cleared = False
    while time.time() < deadline:
        time.sleep(6)
        if not risk_hit(page, kws):
            cleared = True
            break
    if not cleared:
        print("   ❌ 超时未解除")
        return False
    print("   ✓ 风控文案已消失，检查遮罩…")
    m = modal_mask(page, mask_sel)
    if m and m.get("disp") != "none" and m.get("w", 0) >= 50:
        print(f"   ⚠️ 遮罩仍在 {m}，强制重置")
        page.keyboard.press("Escape"); time.sleep(1.5)
        if reset is not None and not reset(page):
            print("   ❌ 重置失败")
            return False
    print("   ✓ 风控已彻底解除")
    return True


# ---------------------------------------------------------------- 批量骨架
def run_tasks(page, tasks, publish_one, *, upload_url, log_dir,
              between_s=35, dry_run=0, result_json="publish-result.json"):
    """批量循环骨架：单条异常不拖垮整批 + 防风控节流（**写在循环内**）。

    - 每条 try/except：一条挂掉只记「异常」，异常后强制回干净投稿页
      （脏状态会跨条污染——第 5 条编辑器里躺着第 3 条内容的教训）；
    - 关键节点前后截图：pre/post 各一张 + 异常现场 crash-*，全留证；
    - result 记录逐条落 JSON，可回读复核；
    - **节流在循环内**（已核实缺陷①修复）：原 xhs 版「每条之间歇 35s」写在
      循环外，整批只睡最后一次。这里每条之间都睡 between_s（最后一条后不睡）。

    publish_one(page, task, auto, log_dir=...) -> dict（含 no/lang/ok/stage）。
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    results = []
    n = len(tasks)
    for idx, t in enumerate(tasks):
        auto = not (dry_run and t["no"] == dry_run)
        try:
            try:
                page.screenshot(path=str(log_dir / f"pre-{t['no']:02d}.png"))
            except Exception:
                pass
            results.append(publish_one(page, t, auto, log_dir=log_dir))
        except Exception as e:
            # 一条挂掉不能带走整批
            print(f"\n💥 [{t['no']:02d}] {t['lang']} 异常 {type(e).__name__}: {str(e)[:120]}")
            try:
                page.screenshot(path=str(log_dir / f"crash-{t['no']:02d}.png"))
            except Exception:
                pass
            results.append({"no": t["no"], "lang": t["lang"], "ok": False,
                            "stage": f"异常 {type(e).__name__}"})
            # 回投稿页，避免脏状态污染下一条
            try:
                page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(5)
            except Exception:
                pass
        try:
            page.screenshot(path=str(log_dir / f"post-{t['no']:02d}.png"))
        except Exception:
            pass
        # 防风控节流：每条之间都歇（原版写在循环外只睡一次，缺陷①）
        if idx < n - 1:
            print(f"\n⏸ 歇 {between_s}s 再发下一条（防风控）…")
            time.sleep(between_s)
    out = log_dir / result_json
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    print(f"\n明细写入 {out}")
    return results


def summarize(results, label="") -> int:
    """汇总打印 + 退出码（全成才算成，失败判定一律看退出码）。"""
    print(f"\n===== {label}发布汇总 =====" if label else "\n===== 发布汇总 =====")
    done = [r for r in results if r["ok"]]
    print(f"  成功 {len(done)} / {len(results)}")
    for r in results:
        extra = f" · 封面{r['cover']}" if r.get("cover") else ""
        print(f"  {'✅' if r['ok'] else '❌'} [{r['no']:02d}] {r['lang']:8s} {r['stage']}{extra}")
    return 0 if len(done) == len(results) else 1


# ---------------------------------------------------------------- 任务过滤
def filter_tasks(tasks, only=None, frm=None):
    """`--only 1,7` / `--from 3` 过滤（纪律 12：筛空当场报错，不许静默跑 0 条）。"""
    out = list(tasks)
    if only:
        keep = {int(x) for x in str(only).split(",") if x.strip()}
        out = [t for t in out if t["no"] in keep]
    elif frm:
        out = [t for t in out if t["no"] >= frm]
    if not out:
        raise SystemExit(
            f"筛选后任务为空（only={only!r}, from={frm!r}）——"
            f"按纪律 12 当场报错，不静默跑 0 条。原始任务数 {len(tasks)}。")
    return out


# ---------------------------------------------------------------- CLI 适配层
def manifest_argparser(prog: str) -> argparse.ArgumentParser:
    """三个发布器 CLI 叶子的公共参数表（平台差异项由调用方再 add_argument）。

    参数表长一个样是**约定**不是巧合（cli.py 路由叶子；`feuille.manifest.
    build_manifest` 的清单格式三个平台同构），各抄一份只会漂移出三个
    「文档说 a、代码收 b」的版本。
    """
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("manifest", help="build_manifest 落盘的清单 JSON")
    ap.add_argument("--log-dir", required=True,
                    help="每条的过程截图 / result JSON 落盘目录")
    ap.add_argument("--only", default=None, help="只发指定序号（如 1,7；续跑用）")
    ap.add_argument("--frm", type=int, default=None, help="从指定序号起发")
    ap.add_argument("--dry-run", type=int, default=0, help="只走前 N 条的干跑")
    ap.add_argument("--headless", action="store_true")
    return ap


def manifest_tasks(manifest: str, platform_key: str) -> list:
    """从 build_manifest 的产物里取平台段。

    形状不对要说清缺哪段、现有哪些键，而不是抛一个裸 KeyError 让人猜
    清单到底是谁生成的（FAIL 要能被修，门禁哲学同 filter_tasks）。
    """
    try:
        doc = json.loads(Path(manifest).read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SystemExit(f"{manifest} 解析不了：{e}")
    tasks = doc.get(platform_key) if isinstance(doc, dict) else None
    if not isinstance(tasks, list):
        got = sorted(doc) if isinstance(doc, dict) else type(doc).__name__
        raise SystemExit(f"{manifest} 缺 {platform_key!r} 段——确认这是 "
                         f"feuille.manifest.build_manifest 的产物（顶层键：{got}）")
    return tasks
