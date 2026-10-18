// index.ts — @feuille/publish — Playwright 发布系统
// （⑨ 平台发布 / ⑩ 合集 / ⑪ 发布后核对）（publish/__init__.py 的 TS 移植）。
//
// 使用契约：
//
// 1. Playwright 走可选依赖组：包内只在函数内动态 `import('playwright')`，
//    没装时 `import '@feuille/publish'` 也不炸；真跑发布先装 playwright。
// 2. 任务来源参数化：`tasks` 是 `manifest.build_manifest` 的产物
//    （no/lang/locale/title/body/tags/video/cover），发布器不读任何写死路径；
//    截图与 result JSON 落调用方指定的 logDir。
// 3. 持久 profile 用 `base.PROFILES` 平台表，登录态存盘勿删。
// 4. 认证与风控一律人工（纪律 21）：扫码等本人完成，agent 不代填；
//    风控停等绝不自动重试，解除后确认遮罩真的消失。
// 5. 封面/必填项硬闸门（纪律 19）：没生效就中止本条，宁可整条不发；
//    抖音封面走「先发视频、后补编辑流程」两步（见 douyin.ts）。
// 6. 发布后必须核对（纪律 5）：veriflive 只产证据，最终判定 = 人眼看
//    对照图缩略图里有文字。
// 7. 本包只提供机制；何时对真实平台发起流量由使用者本人决定。
//
// 子模块：`base`（公共骨架）/ `login`（扫码登录）/ `douyin` / `xhs` /
// `bilibili`（发布器）/ `collections`（合集）/ `veriflive`（发布后核对）。
// 反向验证：`packages/publish/test/publish.test.ts`（mock HTML 驱动，零平台流量）。

export * as base from './base.js'
export * as login from './login.js'
export * as douyin from './douyin.js'
export * as xhs from './xhs.js'
export * as bilibili from './bilibili.js'
export * as collections from './collections.js'
export * as veriflive from './veriflive.js'
export * as check_plan from './check_plan.js'
