#!/usr/bin/env python3
"""Douyin Collection Creator (创建抖音合集并添加全集视频).

Navigates to https://creator.douyin.com/creator-micro/content/collection/create,
fills metadata, uploads 1080x1080 cover, selects the 7 full collection videos
in chronological episode order (Acts 1-6 + Master), and submits creation.
"""

from __future__ import annotations

import os
import sys
import time
from playwright.sync_api import sync_playwright

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR = os.path.expanduser("~/.douyin_creator_profile")
COVER_PATH = "/Users/han/.gemini/antigravity-ide/brain/605ece1e-1fde-448d-bc22-c7206e74c129/scratch/collection_cover.png"
SCREENSHOT_DIR = "/Users/han/.gemini/antigravity-ide/brain/605ece1e-1fde-448d-bc22-c7206e74c129/scratch"

COLLECTION_TITLE = "九种语言问路与指路全集"
COLLECTION_DESC = "涵盖中、英、法、俄、希、日、韩、印地、阿拉伯九种语言问路与指路的高频表达、语法对照、礼貌语气与发音对比，共六幕情景与完整总集。"

# Desired episode order (1 to 7)
EPISODE_ORDER = [
    "第一幕全集",
    "第二幕全集",
    "第三幕全集",
    "第四幕全集",
    "第五幕全集",
    "第六幕全集",
    "全景终极完整版",
]

def main():
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

        print("🔍 正在打开合集创建页面...")
        page.goto("https://creator.douyin.com/creator-micro/content/collection/create", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)

        # Step 1: Fill title
        print(f"📝 填写合集标题: {COLLECTION_TITLE}")
        title_input = page.locator("input[placeholder*='合集的标题']").first
        title_input.click()
        title_input.fill(COLLECTION_TITLE)
        time.sleep(1)

        # Step 2: Fill description
        print("📝 填写合集简介...")
        desc_input = page.locator("textarea[placeholder*='合集的简介']").first
        desc_input.click()
        desc_input.fill(COLLECTION_DESC)
        time.sleep(1)

        # Step 3: Upload cover image
        print(f"🖼️ 上传 1080x1080 高清合集封面: {COVER_PATH}")
        cover_input = page.locator("input[type='file'][accept*='image']").first
        cover_input.set_input_files(COVER_PATH)
        time.sleep(2)

        # Confirm crop modal by clicking '保存'
        try:
            save_btn = page.locator(".semi-modal button:has-text('保存'), button.primary-cECiOJ:has-text('保存')").first
            if save_btn.is_visible(timeout=5000):
                save_btn.click()
                print("   ✓ 已确认并保存合集封面！")
                time.sleep(2)
                # Wait for crop modal to finish and close
                try:
                    page.locator(".semi-modal-wrap, .ReactCrop").wait_for(state="hidden", timeout=8000)
                except Exception:
                    pass
        except Exception as e:
            print(f"   封面保存提示: {e}")

        time.sleep(1)

        # Step 4: Open Add Works Drawer
        print("\n📂 点击【点击添加作品】打开视频抽屉...")
        add_btn = page.locator("text=点击添加作品").first
        add_btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        add_btn.click()
        time.sleep(2)

        # Step 5: Add the 7 videos in chronological order (Act 1 -> 6 -> Master)
        print("🎬 正在将 7 部全集视频按集数顺序加入合集...")
        for ep_idx, kw in enumerate(EPISODE_ORDER, 1):
            found = False
            plus_elements = page.locator("div[class*='plus-area']").all()
            for p_el in plus_elements:
                try:
                    row_text = p_el.locator("xpath=..").inner_text().replace("\n", " ")
                    if kw in row_text:
                        p_el.click()
                        print(f"   ✓ [第 {ep_idx} 集] 已添加: {kw}")
                        found = True
                        break
                except Exception:
                    pass
            if not found:
                print(f"   ✗ 未能在列表中匹配到: {kw}")
            time.sleep(1)

        time.sleep(2)

        # Step 6: Close Drawer
        print("🔒 关闭作品选择抽屉...")
        try:
            close_btn = page.locator(".semi-sidesheet-header button, span[class*='icon-fZcWbp'], .semi-sidesheet-close").first
            if close_btn.is_visible(timeout=1000):
                close_btn.click()
            else:
                page.keyboard.press("Escape")
        except Exception:
            page.keyboard.press("Escape")
        time.sleep(2)

        # Capture readiness screenshot
        ready_img = os.path.join(SCREENSHOT_DIR, "collection_final_ready.png")
        page.screenshot(path=ready_img)
        print(f"📸 提交前页面完整截图: {ready_img}")

        # Step 7: Submit Creation
        print("\n🚀 点击【创建】按钮提交合集...")
        create_btn = page.locator("button.btn-create-SARls6, button:has-text('创建')").first
        create_btn.scroll_into_view_if_needed()
        time.sleep(1)
        create_btn.click()
        print("   ✅ 已触发【创建】操作！")

        # Wait for redirect or toast
        time.sleep(5)
        for _ in range(15):
            curr_url = page.url
            if "/content/collection" in curr_url and "/create" not in curr_url:
                print(f"🎉 合集创建成功！已跳转至合集管理列表: {curr_url}")
                break
            try:
                if page.locator("text=创建成功, text=合集创建成功, .semi-toast-success").count() > 0:
                    print("🎉 检测到【合集创建成功】提示！")
                    break
            except Exception:
                pass
            time.sleep(2)

        result_img = os.path.join(SCREENSHOT_DIR, "collection_created_result.png")
        page.screenshot(path=result_img)
        print(f"📸 最终结果截图: {result_img}")

        print("\n✨ 抖音合集创建流程全部完成！")
        time.sleep(3)

if __name__ == "__main__":
    main()
