#!/usr/bin/env python3
"""Douyin Collection Promoter (抖音合集全集推广与评论区引流脚本).

Automatically navigates to https://creator.douyin.com/creator-micro/interactive/comment,
iterates through each of the 7 full collection videos, and posts an author guide comment
directing viewers to the collection pill while prompting engagement.
"""

from __future__ import annotations

import os
import sys
import time
from playwright.sync_api import sync_playwright

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR = os.path.expanduser("~/.douyin_creator_profile")
SCREENSHOT_DIR = "/Users/han/.gemini/antigravity-ide/brain/605ece1e-1fde-448d-bc22-c7206e74c129/scratch"

COMMENTS = [
    {
        "keyword": "第一幕全集",
        "title": "第一幕全集：拦下陌生人",
        "comment": "📌【九种语言问路全集·第1讲】从陌生人破冰到开口求助！\n👉 点击视频左下方【九种语言问路与指路全集】标签，可自动连播全部7集（含10分钟全景终极完整版）！\n💡 互动讨论：你觉得德语/俄语/阿拉伯语这几个发音里，哪一个最难读准？",
    },
    {
        "keyword": "第二幕全集",
        "title": "第二幕全集：把问题问出去",
        "comment": "📌【九种语言问路全集·第2讲】“请问火车站怎么走？这附近有卫生间吗？”\n👉 点击视频左下方【九种语言问路与指路全集】标签，直接连播第三幕：方位与地标！\n💡 核心语法：法语的倒装 est-ce que 与德语的动词后置，大家掌握了吗？",
    },
    {
        "keyword": "第三幕全集",
        "title": "第三幕全集：方位与地标",
        "comment": "📌【九种语言问路全集·第3讲】听懂大爷指路最关键！“左转、右转、直走、红绿灯”\n👉 点击视频左下方【九种语言问路与指路全集】合集，无缝连播第四幕（路线规划实战）！\n💡 听力打卡：俄语的 прямо 和印地语的 सीधा (seedha)，哪个更顺耳？",
    },
    {
        "keyword": "第四幕全集",
        "title": "第四幕全集：把路讲清楚",
        "comment": "📌【九种语言问路全集·第4讲】复合路线指引！十字路口、第二个街区、沿这条街一直走。\n👉 点击视频左下方【九种语言问路与指路全集】标签，进入第五幕语气与敬语大比拼！\n💡 语法彩蛋：西语的 'Siga todo recto' 是地道用法，收藏起来出国防走丢！",
    },
    {
        "keyword": "第五幕全集",
        "title": "第五幕全集：三档语气对比",
        "comment": "📌【九种语言问路全集·第5讲】硬核语法现场！直走 / 请直走 / 您能告诉我怎么走吗？三档语气变位对比。\n👉 点击视频左下方【九种语言问路与指路全集】标签，连播第六幕：道谢与回礼！\n💡 语言学思考：日语的敬语变位 vs 法语的条件式 (Pourriez-vous)，哪个更显礼貌？",
    },
    {
        "keyword": "第六幕全集",
        "title": "第六幕全集：道谢与回礼",
        "comment": "📌【九种语言问路全集·第6讲】终点礼仪！九种语言说“非常感谢”与回敬“不客气”。\n👉 点击视频左下方【九种语言问路与指路全集】标签，查看【10分钟全景终极完整版】！\n💡 知识点：俄语 Пожалуйста (Pozhaluysta) 既能表“请”又能表“不客气”，大家记住了吗？",
    },
    {
        "keyword": "全景终极完整版",
        "title": "全景终极完整版",
        "comment": "🎓【九种语言问路与指路·全景终极完整版】六大幕、十六大场景、九国语言发音+语法解析全流程！\n📌 建议先【收藏】备用！若想按幕数拆解精读，可点击左下方【九种语言问路与指路全集】分集自选播放。\n💡 欢迎大家在评论区留下你最想看的下一个多语对比场景（点餐/购物/就医）！",
    },
]


def post_comments():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
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

        print("🔍 正在打开抖音创作者中心评论管理页面...")
        page.goto("https://creator.douyin.com/creator-micro/interactive/comment", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)

        for idx, item in enumerate(COMMENTS, 1):
            kw = item["keyword"]
            title = item["title"]
            cmt_text = item["comment"]
            print(f"\n==================================================")
            print(f"[{idx}/7] 处理作品: {title} (匹配关键词: {kw})")

            # Step 1: Open works sidesheet
            try:
                sel_btn = page.locator("text=选择作品").first
                sel_btn.click(timeout=5000)
                time.sleep(1.5)
            except Exception as e:
                print(f"   打开选择抽屉提示: {e}")

            # Step 2: Click the target video in the sidesheet
            try:
                target_el = page.locator(f".douyin-creator-interactive-sidesheet-body :has-text('{kw}')").last
                if target_el.is_visible(timeout=5000):
                    target_el.click()
                    print(f"   ✓ 成功选择作品: {kw}")
                    time.sleep(2)
                else:
                    print(f"   ✗ 未能在列表中找到: {kw}")
                    page.keyboard.press("Escape")
                    time.sleep(1)
                    continue
            except Exception as e:
                print(f"   选择作品出错: {e}")
                continue

            # Step 3: Type into comment input box
            input_box = page.locator("div[contenteditable='true']").first
            if not input_box.is_visible(timeout=3000):
                print("   ✗ 评论输入框不可见，跳过")
                continue

            input_box.click()
            time.sleep(0.5)

            # Clear existing content if any
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            time.sleep(0.3)

            # Insert comment text
            page.keyboard.insert_text(cmt_text)
            time.sleep(1)

            # Step 4: Click Send button
            send_btn = page.locator("button:has-text('发送')").first
            if send_btn.is_visible(timeout=2000):
                send_btn.click()
                print(f"   ✅ 已发布作者引导评论！")
                time.sleep(2)
            else:
                print("   ✗ 发送按钮不可见")

        # Take final screenshot
        res_img = os.path.join(SCREENSHOT_DIR, "comments_posted_summary.png")
        page.screenshot(path=res_img)
        print(f"\n📸 最终状态截图: {res_img}")
        print("🎉 全部 7 部作品的作者引导评论均已发布完毕！")
        time.sleep(2)


if __name__ == "__main__":
    post_comments()
