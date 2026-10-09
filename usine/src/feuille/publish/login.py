# -*- coding: utf-8 -*-
"""login.py — 逐平台扫码登录（⑨ 前置）：打开 + 等待 + 存盘，不碰任何发布按钮

逐个而不是一次全开：二维码有效期约 1–3 分钟，一次全开会有人过期。
本模块的 wait_login 走 probe() 的三通道判据（可见文本 → URL 特征）；
base.wait_login 是通用登录墙轮询（关键词表由调用方传），两者用途不同。

使用契约：认证一律人工（纪律 21）——脚本只等扫码，不代填任何凭据；
profile 用 base.PROFILES 的持久 user-data 目录，登录态存盘勿删。

用法：
    from feuille.publish import login
    login.login(["douyin"])                                # 登录一个平台
    login.login(["douyin", "xhs", "bilibili", "zhihu"])    # 按给定顺序逐个
    login.login(wait=False)                                # 只查状态，不等待
"""
from __future__ import annotations

import time
from pathlib import Path

from . import base

# 每个平台：入口 URL、常驻 profile、登录成功判据、登录墙判据
# profile 值从 base.PROFILES 派生（单一事实源），这里只放各平台的判据数据。
SITES: dict[str, dict] = {
    "douyin": {
        "label": "抖音创作者中心",
        "url": "https://creator.douyin.com/creator-micro/home",
        # 登录后：左上角有「发布视频」入口，或落在内容管理页
        "in": ["发布视频", "作品管理", "数据概览"],
        "in_url": ["/creator-micro/content", "/creator-micro/home"],
        # 登录墙：出现扫码登录面板
        "wall": ["扫码登录", "验证码登录", "密码登录"],
    },
    "xiaohongshu": {
        "label": "小红书创作服务平台",
        "url": "https://creator.xiaohongshu.com/publish/publish",
        "in": ["发布笔记", "上传视频", "创作中心", "数据中心"],
        "in_url": ["/publish/publish", "/new/note"],
        "wall": ["扫码登录", "验证码登录", "手机号登录", "立即登录"],
    },
    "bilibili": {
        "label": "B站创作中心",
        "url": "https://member.bilibili.com/platform/upload/video/frame",
        "in": ["投稿", "上传稿件", "内容管理", "创作中心"],
        "in_url": ["/platform/upload", "/platform/home"],
        "wall": ["扫码登录", "密码登录", "手机号登录", "登录后"],
    },
    "zhihu": {
        "label": "知乎创作中心",
        "url": "https://www.zhihu.com/creator",
        "in": ["创作中心", "发布文章", "发布视频", "内容管理", "数据概览"],
        "in_url": ["/creator", "/creator/manage"],
        "wall": ["扫码登录", "验证码登录", "手机号登录", "立即登录"],
    },
}

ORDER = ["douyin", "xiaohongshu", "bilibili", "zhihu"]


KEYWORDS = [
    "扫码登录", "验证码登录", "密码登录", "手机号登录", "立即登录", "登录后",
    "发布视频", "作品管理", "数据概览", "创作中心",
    "发布笔记", "上传视频", "投稿", "上传稿件", "内容管理", "发布文章",
]


def _visible_texts(page) -> list[str]:
    """只取**可见**的文本节点。

    踩过的两个坑：
    1) 登录弹窗是浮层，底层页面的「作品管理」等文案仍在 body 文本里，
       用 inner_text('body') 会把「未登录」误判成「已登录」。必须按可见性过滤。
    2) Playwright 的 `text=` 引擎不能写成逗号并用（会被当成 CSS 解析），
       必须逐个关键词 get_by_text 查。
    """
    seen: list[str] = []
    for kw in KEYWORDS:
        try:
            loc = page.get_by_text(kw, exact=False)
            n = min(loc.count(), 3)
            for i in range(n):
                el = loc.nth(i)
                if el.is_visible():
                    t = (el.inner_text() or "").strip()
                    if t and t not in seen:
                        seen.append(t)
                    break          # 该关键词已确认可见即可
        except Exception:
            continue
    return seen


def probe(page, name: str) -> tuple[bool, str]:
    """返回 (是否已登录, 现场描述)。只看可见元素，不点击。

    （适配点：原版用全局 CUR 标记当前平台——不可测；改为显式 name 参数，逻辑不变。）
    """
    url = page.url or ""
    vis = _visible_texts(page)
    if not vis:
        return False, "页面尚未渲染出可判定特征"

    wall = [w for w in SITES[name]["wall"] if w in vis]
    inside = [w for w in SITES[name]["in"] if w in vis]

    # 登录墙可见 → 未登录（可见性优先，浮层不会再骗人）
    if wall:
        return False, f"登录弹窗可见（{wall[0]}）"
    if inside:
        return True, f"内容区可见（{inside[0]}）"
    in_url = [u for u in SITES[name]["in_url"] if u in url]
    if in_url and not wall:
        return True, f"落在内容页 URL（{in_url[0]}）"
    return False, f"未见登录入口也未见内容区（可见：{vis[:3]}）"


def wait_login(ctx, name: str, minutes: int = 6) -> bool:
    """轮询等待登录完成。二维码过期的话页面会自己刷新出新码。

    （与 base.wait_login 不同：这里用 probe() 的可见文本 + URL 双通道判据，
    是 login_helper 原版逻辑；ctx 是持久 profile context，登录即落盘。）
    """
    site = SITES[name]
    limit = time.time() + minutes * 60
    tick = 0
    while time.time() < limit:
        ok, desc = probe(ctx.pages[0] if ctx.pages else ctx.new_page(), name)
        if ok:
            print(f"   ✅ {site['label']} 登录成功 · {desc}")
            return True
        if tick % 5 == 0:
            print(f"   ⏳ 等待扫码…（{desc}）已等 {int((limit - time.time())//60)+1} 分钟内")
        tick += 1
        time.sleep(3)
    print(f"   ❌ {site['label']} 超时未登录")
    return False


def do_one(name: str, wait: bool = True, *, shot_dir=None) -> bool:
    """打开一个平台的后台，判定登录态；未登录则（可选）等用户扫码，存盘退出。"""
    site = SITES[name]
    profile = base.profile_dir(name)
    print(f"\n=== {site['label']} ===")
    with base.launch(profile, viewport={"width": 1440, "height": 900}) as (ctx, page):
        page.goto(site["url"], wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        ok, desc = probe(page, name)
        print(f"   当前状态：{desc}")
        if shot_dir is not None:
            shot_dir = Path(shot_dir)
            shot_dir.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=str(shot_dir / f"login-{name}.png"))
            except Exception as e:
                # 截图只是留证，不该让它中断登录流程（部分站点会开新页导致原页关闭）
                print(f"   （截图跳过：{type(e).__name__}）")

        if ok:
            print("   ✅ 已是登录态，无需扫码")
        elif not wait:
            print("   ⚠️  未登录。需你本人在弹出的 Chrome 窗口扫码/登录。")
        else:
            print("   👉 请在弹出的 Chrome 窗口中扫码登录（脚本会等，登录后自动继续）")
            ok = wait_login(ctx, name)
            if ok and shot_dir is not None:
                try:
                    page.screenshot(path=str(shot_dir / f"login-{name}-ok.png"))
                except Exception:
                    pass

    # with 退出即 ctx.close() —— 关闭才把 cookie 写进 profile
    print(f"   💾 会话已存盘到 {profile}")
    return ok


def login(names=None, *, wait=True, shot_dir=None) -> int:
    """按给定顺序逐个登录（不并行——二维码 1–3 分钟过期，一次全开会有人过期）。

    names=None 按默认顺序全走一遍；wait=False 只查状态不等待。返回退出码。
    """
    names = list(names) if names else list(ORDER)
    bad = [n for n in names if n not in SITES]
    if bad:
        print("未知平台:", bad, "可选:", list(SITES))
        return 2

    results = {}
    for n in names:
        try:
            results[n] = do_one(n, wait, shot_dir=shot_dir)
        except Exception as e:
            print(f"=== {n} 异常: {e}")
            results[n] = False

    print("\n===== 登录结果汇总 =====")
    for n, ok in results.items():
        print(f"  {SITES[n]['label']:20s} {'✅ 已登录' if ok else '❌ 未登录'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":          # 参考入口：python -m feuille.publish.login [平台…]
    import sys
    raise SystemExit(login([a for a in sys.argv[1:] if not a.startswith("--")],
                          wait="--status" not in sys.argv))
