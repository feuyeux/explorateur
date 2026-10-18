// index.ts — @feuille/poster — one-page-poster 排版产线
// （one-page-poster/scripts 十个脚本的 TS 归流）。
//
// 使用契约：
//
// 1. 浏览器解析消费 @feuille/core 唯一事实源（platform.browserPath；
//    $CHROME_BIN 优先）——render_poster 曾写死 google-chrome 在只有 Edge 的
//    机器上直接失败，归流后只此一份。
// 2. 渲字一律 Edge/Chrome headless 实渲（raqm=False 纪律同源：成像库不画字）；
//    rect 探测挂 document.fonts.ready 门后（探针字体解码竞速）。
// 3. audit_charset 是 tofu 防线 + 垫片规则绑定门（A-03 实锤），两门全报再退。
// 4. measure-korean 的垫片分数逐字形——绝不跨主题/字体复用；元音墨贴声母墨
//    （融合连通域）必须响亮失败，不许让 classify 给孤 blob 标 V。
// 5. 本包零平台流量、零额度（fetch_fonts 只打 Google Fonts css2 子集端点）。
//
// 反向验证：packages/poster/test/{poster,measure_korean}.test.ts
// （audit_charset 三判据原 verify_skill_scripts.py §4 随归流移植）

export * as fetch_fonts from './fetch_fonts.js'
export * as assemble from './assemble.js'
export * as render_poster from './render_poster.js'
export * as render_page from './render_page.js'
export * as audit_charset from './audit_charset.js'
export * as fit_diag from './fit_diag.js'
export * as verify_colors from './verify_colors.js'
export * as check_overlay from './check_overlay.js'
export * as make_covers from './make_covers.js'
export * as measure_korean from './measure_korean.js'
