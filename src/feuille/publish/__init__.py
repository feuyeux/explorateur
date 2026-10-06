# -*- coding: utf-8 -*-
"""feuille.publish — Playwright 发布系统（⑨ 平台发布 / ⑩ 合集 / ⑪ 发布后核对）

**搬运来源**（yiyezhiqiu/scripts/，函数体逐字节照搬、坑注释一字不动）：

    base.py        ← publish_douyin_yyzq.py / publish_xhs_yyzq.py /
                     publish_bilibili_yyzq.py 三份发布器的公共骨架
    douyin.py      ← publish_douyin_yyzq.py + fix_all_douyin_covers.py
    xhs.py         ← publish_xhs_yyzq.py
    bilibili.py    ← publish_bilibili_yyzq.py
    collections.py ← douyin_fix_collection.py（基准）+ douyin_make_collection.py /
                     douyin_collection_step1.py（参考）
    veriflive.py   ← verify_douyin_covers_live.py / verify_bilibili_live.py /
                     verify_xhs_all.py / verify_douyin_collection.py /
                     verify_douyin_collection_full.py
    login.py       ← login_helper.py

**三个已核实缺陷的修复声明**（源指认 + 修复位置）：

① **防风控节流写在循环外**（publish_xhs_yyzq.py main：循环结束后才
   `time.sleep(35)`，注释却写「每条之间」——整批只睡最后一次）。
   → 修复在 `base.run_tasks`：节流挪进循环内，每条之间都睡 between_s。

② **douyin_make_collection.py 的 JS_ROWS 去重每轮返回同一行**（12 次点击
   全落在希伯来语那条）。
   → 修复在 `collections.py`：以 douyin_fix_collection.py 为基准——「+」按钮
   svg 本身做选择器（JS_PLUS），已添加的行按「已添加」文本过滤，不靠
   「扫文本行→按序号取第 i 个」。

③ **发布器写死的 Chrome 绝对路径**（三份发布器顶部的 CHROME 常量，
   macOS-only，跨平台必炸）。
   → 修复在 `base.resolve_chrome()`：经 `feuille.platform.browser(only="chrome")`
   解析，找不到显式报缺（SystemExit），绝不编路径、绝不退化成自带浏览器；
   `FEUILLE_BROWSER` 环境变量可临时覆盖。

**使用契约**：

1. **Playwright 走可选依赖组**：feuille 主环境不装 playwright；本包内
   playwright **只在函数内 lazy import**，所以没装 publish 组时
   `import feuille.publish` 也不炸。要真跑发布：`uv sync --group publish`。
2. **任务来源参数化**：`tasks` 是 `feuille.manifest.build_manifest` 的产物
   （no/lang/locale/title/body/tags/video/cover），发布器不读任何写死路径；
   截图与 result JSON 由调用方指定 log_dir。
3. **持久 profile 表**：默认值是 `base.PROFILES` 平台表里的数据
   （`~/.{douyin,xhs,bili,zhihu}_creator_profile` 命名约定），登录态存盘勿删。
4. **认证与风控一律人工**（纪律 21）：扫码等本人完成，agent 不代填；
   风控停等绝不自动重试，解除后确认遮罩真的消失。
5. **封面硬闸门**（纪律 19）：封面/必填项没生效就中止本条，宁可整条不发；
   抖音封面走「先发视频、后补编辑流程」两步（见 douyin.py 头注）。
6. **发布后必须核对**（纪律 5）：veriflive 只产证据，最终判定 = 人眼看
   对照图缩略图里有文字。
7. 本包只提供机制；**何时对真实平台发起流量由使用者本人决定**——
   蒸馏/验证阶段零平台调用。

子模块一览：`base`（骨架）/ `login`（逐平台扫码）/ `douyin` / `xhs` /
`bilibili`（发布器）/ `collections`（合集）/ `veriflive`（发布后核对）。
反向验证：`scripts/verify_publish.py`（mock HTML 驱动，零平台流量）。
"""

__all__ = ["base", "login", "douyin", "xhs", "bilibili", "collections", "veriflive"]
