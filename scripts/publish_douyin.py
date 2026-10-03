#!/usr/bin/env python3
"""Douyin Creator Platform Auto-Publisher (抖音创作者服务平台全集自动发布脚本).

Automates publishing educational short videos to Douyin Creator Platform
(https://creator.douyin.com/) using Playwright with local Chrome and
persistent login session.

Features:
- Handles both Full Collection (全集) and Single Scene (分集) videos.
- Automatically clears unreleased draft banners ("放弃上次未发布的视频").
- Avoids triggering the cover screenshot modal (截取封面界面).
- Accurately fills title, description, and hashtag capsules.
- Automatically confirms modals and triggers publication.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR = os.path.expanduser("~/.douyin_creator_profile")
VIDEOS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../videos")
)

@dataclass
class VideoTask:
    filename: str
    title: str
    desc: str
    tags: List[str]

# ---------------------------------------------------------------------------
# 全集队列 (Full Collection Queue: 6幕全集 + 1部终极完整版)
# ---------------------------------------------------------------------------
FULL_COLLECTION_QUEUE: List[VideoTask] = [
    VideoTask(
        filename="Act1_全集_拦下陌生人.mp4",
        title="第一幕全集：拦下陌生人 · 九种语言从破冰到求助",
        desc="九种语言问路全集第一幕：中、英、法、俄、希、日、韩、印地、阿九国语言从“打扰一下”到“我迷路了”完整对照解析。",
        tags=["语言学习", "多语言对比", "外语学习", "口语干货", "英语口语"],
    ),
    VideoTask(
        filename="Act2_全集_把问题问出去.mp4",
        title="第二幕全集：把问题问出去 · 九种语言问路句式大比拼",
        desc="九种语言问路全集第二幕：目的地在哪、火车站怎么走、这附近有便利店吗，九种语言三大高频句式全景对照。",
        tags=["语言学", "英语口语", "日语日常", "法语学习", "小语种"],
    ),
    VideoTask(
        filename="Act3_全集_方位与地标.mp4",
        title="第三幕全集：方位与地标 · 听懂“左、右、直走”九国说法",
        desc="九种语言问路全集第三幕：听懂大爷指路最关键！九种语言方位词精准发音与词根背景全汇总。",
        tags=["日常英语", "旅游日语", "多国语言", "语言日常", "口语学习"],
    ),
    VideoTask(
        filename="Act4_全集_把路讲清楚.mp4",
        title="第四幕全集：把路讲清楚 · 路线规划的九国地道表达",
        desc="九种语言问路全集第四幕：沿路直走、路口左转、红绿灯右转，九国语言连贯路线指引完整演练。",
        tags=["实用英语", "小语种学习", "语言学", "多语对照", "口语干货"],
    ),
    VideoTask(
        filename="Act5_全集_三档语气.mp4",
        title="第五幕全集：三档语气对比 · 命令、中性与敬语九国变位",
        desc="九种语言问路全集第五幕：走！直走。请直走。九种语言从最粗暴的命令式到最客气的敬语完整语法对比。",
        tags=["语法变位", "多语言对比", "英语敬语", "日语敬语", "语言学"],
    ),
    VideoTask(
        filename="Act6_全集_道谢与回礼.mp4",
        title="第六幕全集：道谢与回礼 · 九种语言说谢谢与不客气",
        desc="九种语言问路全集第六幕：终点礼仪！九种语言说“太感谢了”与回敬“不客气”的词根与文化意涵。",
        tags=["多语言", "礼貌口语", "文化对比", "英语口语", "小语种干货"],
    ),
    VideoTask(
        filename="问路与指路_九种语言语法现场_全集完整版.mp4",
        title="九种语言问路指路语法现场 · 全景终极完整版",
        desc="问路指路九国语言完整版！中英法俄希日韩印地阿，六大场景、十六大句式全流程视听盛宴。",
        tags=["语言学习", "多语言对比", "外语启蒙", "英语口语", "日语学习"],
    ),
]

# 单集队列 (Single Scenes)
SINGLE_SCENE_QUEUE: List[VideoTask] = [
    VideoTask(
        filename="Act1_01_拦下陌生人_打扰一下.mp4",
        title="第一幕：拦下陌生人 · 九种语言的“打扰一下”各怎么说？",
        desc="出门在外，开口第一句最关键！中、英、法、俄、希、日、韩、印地、阿九国语言发音对照与礼貌深意。",
        tags=["语言学习", "多语言对比", "英语口语", "日语日常", "法语学习"],
    ),
    VideoTask(
        filename="Act1_02_拦下陌生人_我迷路了.mp4",
        title="第一幕：拦下陌生人 · 九种语言说“我迷路了”，性别当场现形！",
        desc="“我迷路了”在九种语言里动词怎么变？法语、俄语、印地语的说话人性别如何藏在词尾里？",
        tags=["多语言", "外语学习", "实用口语", "俄语学习", "法语"],
    ),
    VideoTask(
        filename="Act2_01_把问题问出去_目的地在哪.mp4",
        title="第二幕：把问题问出去 · 九种语言问“目的地在哪儿”",
        desc="问路核心句式！从原位疑问词到倒装前移，看九种语言如何定位目的地。",
        tags=["语言学", "英语语法", "日语口语", "多语言学习", "小语种"],
    ),
    VideoTask(
        filename="Act2_02_把问题问出去_火车站怎么走.mp4",
        title="第二幕：把问题问出去 · “火车站怎么走”九国语言对照",
        desc="赶火车必备表达！九种语言如何用不同句式问出最接地气的路线。",
        tags=["日常英语", "旅游日语", "多国语言", "语言日常", "口语干货"],
    ),
    VideoTask(
        filename="Act2_03_把问题问出去_这附近有便利店吗.mp4",
        title="第二幕：把问题问出去 · “附近有便利店吗”九种语言实战",
        desc="出门找补给！九种语言的存在句与是非问句装置对比。",
        tags=["实用外语", "英语积累", "日语笔记", "多语言", "口语提升"],
    ),
    VideoTask(
        filename="Act3_01_方位与地标_左.mp4",
        title="第三幕：听懂回答 · 方位词“左”的各国说法与文化偏向",
        desc="大爷一指路，方位词最先涌出来！看中、英、法、俄、希、日、韩、印、阿各国如何说“左”。",
        tags=["多语言学习", "语言学常识", "口语听力", "趣味外语", "英语"],
    ),
    VideoTask(
        filename="Act3_02_方位与地标_右.mp4",
        title="第三幕：听懂回答 · 方位词“右”的各国说法",
        desc="听懂回答第一步：九种语言中“右”的精准发音与词根故事。",
        tags=["多语言对比", "外语启蒙", "发音技巧", "日常口语", "日语"],
    ),
    VideoTask(
        filename="Act3_03_方位与地标_直走.mp4",
        title="第三幕：听懂回答 · “直走/往前”九种语言对照",
        desc="指路最常听到的词！九国语言如何形容“一直往前走”。",
        tags=["实用英语", "小语种学习", "语言学", "多语对照", "口语学习"],
    ),
    VideoTask(
        filename="Act4_01_把路讲清楚_沿这条路直走.mp4",
        title="第四幕：把路讲清楚 · “沿这条路直走”九国地道说法",
        desc="把路线铺开！介词搭配与动作动词的九国语法形态。",
        tags=["多国语言", "日常口语", "英语表达", "小语种", "学外语"],
    ),
    VideoTask(
        filename="Act4_02_把路讲清楚_到路口左转.mp4",
        title="第四幕：把路讲清楚 · “到路口左转”九国表达",
        desc="听清转弯关键点！九种语言的转弯动词与路口搭配。",
        tags=["英语实战", "日语进阶", "多语言学习", "旅游口语", "俄语"],
    ),
    VideoTask(
        filename="Act4_03_把路讲清楚_第二个红绿灯右转.mp4",
        title="第四幕：把路讲清楚 · “第二个红绿灯右转”实景指路",
        desc="复杂路况指引！序数词、地标名词与转弯指令的连贯表达。",
        tags=["口语表达", "语言学干货", "多语言", "高频词汇", "外语日常"],
    ),
    VideoTask(
        filename="Act5_01_三档语气_走.mp4",
        title="第五幕：三档语气对比 · 强硬命令式的“走！”",
        desc="同一个大爷声口不同！九种语言最直白硬核的命令式动词变位。",
        tags=["语法变位", "多语言对比", "语言学", "英语口语", "日语语法"],
    ),
    VideoTask(
        filename="Act5_02_三档语气_直走.mp4",
        title="第五幕：三档语气对比 · 平铺直叙的“直走”",
        desc="中性语气的日常陈述：九种语言如何自然表达动作指引。",
        tags=["外语学习", "口语提升", "语言技巧", "多国语言", "小语种"],
    ),
    VideoTask(
        filename="Act5_03_三档语气_请直走.mp4",
        title="第五幕：三档语气对比 · 最客气的“请直走”礼貌标记",
        desc="客气话怎么说？敬语、礼貌副词与虚拟语气的九国呈现。",
        tags=["礼貌用语", "日常口语", "英语敬语", "日语敬语", "多语言"],
    ),
    VideoTask(
        filename="Act6_01_道谢与回礼_道谢.mp4",
        title="第六幕：道谢与回礼 · 九种语言说“太感谢了”",
        desc="问路终点：九种语言的“谢谢”词根各从何处来？",
        tags=["日常口语", "多语言学习", "词源故事", "英语学习", "实用外语"],
    ),
    VideoTask(
        filename="Act6_02_道谢与回礼_回礼.mp4",
        title="第六幕：道谢与回礼 · 九种语言怎么回敬“不客气”",
        desc="有来有回才算完整！各国如何回应别人的道谢与祝福。",
        tags=["多语言", "礼貌口语", "文化对比", "英语口语", "小语种干货"],
    ),
]


def check_and_login(page, account_id: str = "30749309055") -> None:
    """Ensure user is logged into Douyin Creator Platform."""
    print(f"\n🔍 正在打开抖音创作者服务平台 (目标账号: {account_id})...")
    page.goto("https://creator.douyin.com/creator-micro/content/upload", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)

    login_indicators = [
        "text=扫码登录",
        "text=快捷登录",
        "text=密码登录",
        ".login-mask",
        ".semi-modal",
        "input[placeholder*='手机号']",
        "text=登录后即可发布",
    ]

    def has_login_prompt() -> bool:
        for ind in login_indicators:
            try:
                if page.locator(ind).first.is_visible(timeout=1000):
                    return True
            except Exception:
                pass
        return False

    def is_logged_in() -> bool:
        try:
            if page.locator('input[type="file"]').count() > 0:
                return True
            if page.locator(".semi-avatar, .user-avatar, img[alt*='avatar'], text=退出登录, text=创作者服务平台").count() > 0:
                if not has_login_prompt():
                    return True
        except Exception:
            pass
        return False

    if not is_logged_in():
        print("\n" + "=" * 62)
        print(f"🔔 请在弹出的 Chrome 浏览器窗口中，使用抖音 APP 扫码登录账号 [{account_id}]")
        print("   登录成功后，脚本将自动检测并进入视频上传流程...")
        print("=" * 62 + "\n")

        while True:
            curr_url = page.url
            if "/creator-micro/home" in curr_url or "/creator-micro/content/manage" in curr_url:
                print("✅ 登录成功！正在跳转至发布页面...")
                page.goto("https://creator.douyin.com/creator-micro/content/upload", timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                break

            if page.locator('input[type="file"]').count() > 0 and not has_login_prompt():
                print("✅ 登录成功！已检测到发布上传控件。")
                break

            time.sleep(2)

    if "/creator-micro/content/upload" not in page.url:
        page.goto("https://creator.douyin.com/creator-micro/content/upload", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)

    print("✅ 创作者服务平台已连接就绪！\n")


def clean_draft_banner(page) -> None:
    """Discard any lingering draft banner on the upload page."""
    try:
        abandon_btn = page.locator("button:has-text('放弃'), a:has-text('放弃'), span:has-text('放弃')").first
        if abandon_btn.is_visible(timeout=1500):
            abandon_btn.click()
            print("   ✓ 已自动放弃并清理上次未发布的草稿。")
            time.sleep(1.5)
            # Confirm secondary discard dialog if any
            conf_btn = page.locator(".semi-modal button:has-text('确定'), .semi-modal button:has-text('放弃')").first
            if conf_btn.is_visible(timeout=1500):
                conf_btn.click()
                time.sleep(1)
    except Exception:
        pass


def dismiss_cover_modal(page) -> None:
    """Close cover screenshot / selection modal if opened."""
    for modal_sel in [
        "div[role='dialog'] button:has-text('完成')",
        "div[role='dialog'] button:has-text('确定')",
        ".semi-modal button:has-text('完成')",
        ".semi-modal button:has-text('确定')",
        "button:has-text('完成')",
    ]:
        try:
            btn = page.locator(modal_sel).first
            if btn.is_visible(timeout=800):
                btn.click()
                print("   ✓ 已自动确认并关闭封面截取界面。")
                time.sleep(1)
                break
        except Exception:
            pass


def upload_single_video(page, task: VideoTask, auto_publish: bool = False) -> bool:
    """Upload and publish a single video task seamlessly."""
    video_path = os.path.join(VIDEOS_DIR, task.filename)
    if not os.path.exists(video_path):
        print(f"❌ 视频文件不存在: {video_path}")
        return False

    print(f"\n🚀 开始发布: {task.filename}")
    print(f"   标题: {task.title}")
    print(f"   简介: {task.desc}")

    # Ensure on upload page
    if "/creator-micro/content/upload" not in page.url:
        page.goto("https://creator.douyin.com/creator-micro/content/upload", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)

    # Discard old draft banner if present
    clean_draft_banner(page)

    # Locate file input
    file_input = page.locator('input[type="file"]').first
    file_input.set_input_files(video_path)
    print("   已将视频文件送入上传通道，正在等待服务器接收与解析...")

    # Wait up to 30s for the edit form
    title_box = page.locator("input[placeholder*='标题'], input[placeholder*='作品标题']").first
    # IMPORTANT: Target contenteditable div ONLY, strictly avoiding drop-zones (.zone-container)
    desc_box = page.locator(
        "div.notranslate[contenteditable='true'], "
        "div.editor-kit-editor, "
        "div[data-placeholder*='简介'], "
        "div[contenteditable='true']:not([class*='cover']):not([class*='upload']):not([class*='zone'])"
    ).first

    editor_ready = False
    for _ in range(30):
        try:
            if title_box.is_visible(timeout=1000) or desc_box.is_visible(timeout=1000):
                editor_ready = True
                break
        except Exception:
            pass
        time.sleep(1)

    if not editor_ready:
        print("   ⚠️ 未能自动定位到视频编辑框，请在浏览器中查看状态。")
        return False

    # 1. Fill Title (max 30 chars)
    short_title = task.title[:30]
    try:
        if title_box.is_visible(timeout=3000):
            title_box.click()
            title_box.fill(short_title)
            print(f"   ✓ 标题已录入: {short_title}")
    except Exception as e:
        print(f"   填写标题提示: {e}")

    # 2. Fill Description and Tags
    try:
        if desc_box.is_visible(timeout=3000):
            desc_box.click()
            # Clear text
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            # Type description body
            page.keyboard.type(f"{task.desc}\n\n")
            time.sleep(0.3)
            # Type tags with hash and space to generate official capsules
            for tag in task.tags:
                page.keyboard.type(f"#{tag} ")
                time.sleep(0.35)
            print(f"   ✓ 简介与话题标签已录入: {' '.join(['#'+t for t in task.tags])}")
    except Exception as e:
        print(f"   填写描述提示: {e}")

    # 3. Dismiss any cover screenshot modal if it popped up
    dismiss_cover_modal(page)

    # 4. Wait for video upload & transcoding to complete
    print("   ⏳ 等待视频上传与转码完成...")
    upload_done = False
    for _ in range(120):
        dismiss_cover_modal(page)
        try:
            pub_btn = page.locator(
                "button.semi-button-primary:has-text('发布'), "
                "button:has-text('发布'):not(:has-text('定时')):not(:has-text('视频')):not(:has-text('图文')):not(:has-text('全景')):not(:has-text('文章'))"
            ).first
            if pub_btn.is_visible(timeout=1000):
                is_disabled = (
                    pub_btn.get_attribute("disabled") is not None
                    or "disabled" in (pub_btn.get_attribute("class") or "")
                )
                if not is_disabled:
                    print("   ✓ 视频上传完毕，发布按钮已可用！")
                    upload_done = True
                    break
        except Exception:
            pass
        time.sleep(1)

    if not upload_done:
        print("   ⚠️ 上传等待超时或发布按钮不可用，请在浏览器中核实。")

    # 5. Direct Publish
    if auto_publish:
        try:
            dismiss_cover_modal(page)
            time.sleep(1.5)
            pub_btn = page.locator(
                "button.semi-button-primary:has-text('发布'), "
                "button:has-text('发布'):not(:has-text('定时')):not(:has-text('视频')):not(:has-text('图文')):not(:has-text('全景')):not(:has-text('文章'))"
            ).first
            pub_btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            pub_btn.click()
            print("   ✅ 已自动点击【发布】按钮！")
            time.sleep(2)

            # Check for any secondary confirm modal (e.g. 声明、确认发布)
            for modal_sel in [
                ".semi-modal button:has-text('确认发布')",
                ".semi-modal button:has-text('确定')",
                ".semi-modal button:has-text('确认')",
                ".semi-modal button:has-text('我知道了')",
                "button:has-text('确认发布')",
            ]:
                try:
                    c_btn = page.locator(modal_sel).first
                    if c_btn.is_visible(timeout=1500):
                        c_btn.click()
                        print("   ✓ 已确认弹窗提示。")
                        break
                except Exception:
                    pass
        except Exception as e:
            print(f"   ❌ 点击发布按钮出错: {e}")
            return False

    print("   👉 正在等待该条视频发布确认...")
    start_wait = time.time()
    while time.time() - start_wait < 180:
        if "/creator-micro/content/manage" in page.url:
            print(f"   ✅ 发布成功（已跳转至作品管理）: {task.filename}")
            return True
        try:
            if page.locator("text=发布成功, text=作品已发布, text=发布已完成, .semi-toast-success").count() > 0:
                print(f"   ✅ 检测到【发布成功】: {task.filename}")
                time.sleep(3)
                return True
        except Exception:
            pass
        time.sleep(2)

    print("   ⚠️ 未在超时时间内检测到发布完成跳转，继续下一个流程。")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Douyin Creator Auto-Publisher (全集专用)")
    parser.add_argument("--single", action="store_true", help="Publish single scene clips instead of full collection")
    parser.add_argument("--video", type=str, default="", help="Specific video filename to publish (e.g. Act1_全集...)")
    parser.add_argument("--start-from", type=str, default="", help="Start publishing from this video onwards")
    parser.add_argument("--publish-now", action="store_true", default=True, help="Automatically click publish button without manual pause")
    parser.add_argument("--no-auto-publish", action="store_true", help="Pause for manual review before clicking publish")
    parser.add_argument("--list", action="store_true", help="List all videos in publishing queue")

    args = parser.parse_args()
    auto_publish = not args.no_auto_publish

    # Select queue
    if args.single:
        base_queue = SINGLE_SCENE_QUEUE
        mode_desc = "单集分段片段 (16集)"
    else:
        base_queue = FULL_COLLECTION_QUEUE
        mode_desc = "全集完整版 (6幕全集 + 1部大合集)"

    if args.list:
        print(f"📋 当前队列模式: {mode_desc} (共 {len(base_queue)} 部):\n")
        for i, t in enumerate(base_queue, 1):
            path = os.path.join(VIDEOS_DIR, t.filename)
            exists = "✓" if os.path.exists(path) else "✗"
            print(f"[{i:02d}] [{exists}] {t.filename}")
            print(f"     标题: {t.title}")
            print(f"     标签: {' '.join(['#'+x for x in t.tags])}")
        return

    # Filter target tasks
    if args.video:
        tasks = [t for t in base_queue if t.filename.lower() == args.video.lower() or args.video in t.filename]
        if not tasks:
            # Also search the other queue
            other_queue = SINGLE_SCENE_QUEUE if not args.single else FULL_COLLECTION_QUEUE
            tasks = [t for t in other_queue if t.filename.lower() == args.video.lower() or args.video in t.filename]
            if not tasks:
                print(f"Error: 视频未找到在队列中: {args.video}", file=sys.stderr)
                sys.exit(1)
    elif args.start_from:
        start_idx = -1
        for i, t in enumerate(base_queue):
            if args.start_from.lower() in t.filename.lower():
                start_idx = i
                break
        if start_idx == -1:
            print(f"Error: 未找到起始视频: {args.start_from}", file=sys.stderr)
            sys.exit(1)
        tasks = base_queue[start_idx:]
    else:
        tasks = base_queue

    print(f"============================================================")
    print(f"🎬 准备发布 {len(tasks)} 部【全集】视频至抖音账号 [30749309055]")
    print(f"   模式: {'全自动无缝直接发布' if auto_publish else '手动核对发布'}")
    print(f"   起始: {tasks[0].filename}")
    print(f"============================================================\n")

    # Launch Chrome with persistent profile
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            viewport=None,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Step 1: Ensure login
        check_and_login(page, "30749309055")

        # Step 2: Upload and publish each video
        for idx, task in enumerate(tasks, 1):
            print(f"\n==========================================")
            print(f"[{idx}/{len(tasks)}] 正在处理: {task.filename}")
            print(f"==========================================")
            success = upload_single_video(page, task, auto_publish=auto_publish)
            if not success:
                print(f"跳过当前视频。")
            if idx < len(tasks):
                print("\n等待 8 秒后进入下一个全集视频上传...")
                time.sleep(8)

        print("\n🎉 全部【全集】视频处理完毕！可在创作者平台作品管理中查看发布列表。")
        time.sleep(5)


if __name__ == "__main__":
    main()
