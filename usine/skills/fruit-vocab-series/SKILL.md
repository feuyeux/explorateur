---
name: fruit-vocab-series
description: >
  水果系列的 12 语种视频产线：40 种常见水果（常见度排序）× 12 语种，
  每集 4 种、共 10 集；一集 = 扁平贴纸插画 4 张 + 12 语种分格海报 +
  卡拉OK 成片 + 发布词。两段式推进：(1) 全系词表（40 × 12）逐格过审，
  落 data/fruitlist-12lang.md 并派生 fruitlist.json；(2) 逐集——注音/转写
  清单人审 → 插画（VLM 风格门预检 + 人眼联络表终审）→ 海报/成片（沿用
  foodnames 的句子门与版式门口径）→ 发布词。插画有 matrix / mmx 两条
  引擎线，风格后缀逐字钉死。Not for 单词图鉴（vocab-infographic）、
  菜品/美食名称系列（tools/foodnames 是它的姊妹产线，一道菜 × 12 语）、
  实拍画面（video-generation）、海报排版细节（one-page-poster）、写发布词
  （publish-copy）。
---

# Fruit Vocab Series

一个系列 = **40 种水果 × 12 语种 = 10 集**，每集 4 种、按常见度排序。视觉语言
来自用户给的参考海报（扁平矢量贴纸：纯色块 + 粗深描边 + 一叶一柄 + 奶油纸底），
全部约定钉死在模板与产线脚本里，随输入变化的只有**词表内容**与**插画主体**。

产线脚本在 `usine/tools/fruitnames/`（本 skill 的姊妹 `tools/foodnames/` 是
「一道菜 × 12 语」的系列产线，两道版式门与句子门直接沿用它）。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **过审的全系词表**（40 词 × 12 语，含地区变体的取舍记录） | 词错一个拼写，海报与配音全作废 |
| 2 | **插画风格已打样验收**（联络表人眼过） | 40 张不成套，重烧配额 |
| 3 | **插画引擎**（matrix 需 mcode 运行时 PATH；mmx 随时可跑但「扁平」轴随机，靠 VLM 门兜） | 选错引擎整批风格漂移 |
| 4 | **每集的注音/转写清单已过审**（开画前逐集出，不许全系铺一张大表混过去） | 阿文/希文/天城文转写错，烙进画面 |
| 5 | 音色人设与画幅（沿用 foodnames 的 12 语人设班底与横竖双画幅） | 成片期返工 |

## 流程（两段式）

**Stage 1 · 全系词表（一次，人审硬门）**

1. 选词与排序：常见度优先；汉语译名逐个核对（撞名/生僻词就地换，理由写进
   词表的取舍记录）。
2. 词表落 `data/fruitlist-12lang.md`（人审底稿，唯一事实源）→
   `node tools/fruitnames/build_fruitlist.mjs --force` 派生
   `data/fruitlist.json`（双列格拆 `variants`，首项为默认词形；坏数据不落盘）。
3. 词形规则沿用 `vocab-infographic`：词典基本形、注音体系固定（汉语注音符号、
   日文 Hepburn、韩文 RR-2000、印地 ISO 15919、阿文 DIN 31635、希文 ISO 259）。

**Stage 2 · 逐集推进（每集四步，缺一不可）**

1. **注音/转写清单**：4 词 × 12 语 = 48 行，模板见
   `assets/template/episode-checklist.md`，用户过审才进构建。
2. **插画**：`node tools/fruitnames/gen_art.mjs --engine <matrix|mmx>`——
   主体描述只写外观特征（不写水果名，生图模型会自由发挥成写实渲染）；底色
   归一化到纸色 `#fffcf5`；**逐图 VLM 风格门 + 人眼联络表终审**
   （判据与两条引擎的风格后缀原文见 `assets/template/illustration-style.md`，
   事实源在 `gen_art.mjs` 的 `STYLE` / `MMX_STYLE`）。**同一集的图必须同一
   引擎出的**——跨引擎不混批。
3. **海报 + 成片**：12 语分格海报（着色约定引 `one-page-poster`，不另抄）+
   卡拉OK 成片。两条量化口径**只认 foodnames 的门**：暗词不透明度 ≥ 0.45、
   当前词高亮落品牌三色（`c9403a` / `2f5d9e` / `b8860b`）——通用 karaoke
   模板教的 `opacity: 0.18` + 中性灰是错的，照抄必红；句子门
   （`check_sentence_matches.mjs` 的口径）保证画面句 == 配音句。
4. **发布侧**：`publish-copy` 写三平台发布词，数字全部溯源事实表
   （`make_publish.mjs` 口径）。

## 幂等与落位

- 生成类命令默认不覆盖（`gen_art.mjs` 已有产物跳过；`--force` 才覆盖；
  `--only <key>` 单独重跑）。
- 词表改一个字 → 改 md → 重跑 `build_fruitlist.mjs --force`，**不许直接改
  json**（json 是派生物，`generated_from` 字段记着出处）。
- 内容产物落 `usine/examples/fruitnames/`（不入库）；skill 资产只有模板与
  冻结判据（`assets/`，入库）。产线跑批在任何项目根之外不留目录。

## 边界

- 单词图鉴（一个词一张生成式图像，不走渲染/合片）→ `vocab-infographic`
- 一道菜/一样吃的 × 12 语 → `tools/foodnames`（姊妹产线，无 skill）
- 海报的字体子集 / 逐字着色 / 封面变体 → `one-page-poster`（实现归
  `@feuille/poster`，12 语种规范顺序的唯一事实源也在它 §Conventions）
- 实拍母版 → `video-generation`；写发布词 → `publish-copy`；点发布 →
  `multilingual-video-publishing`

## 代码归属

拥有模块：（无）

产线脚本在 `usine/tools/fruitnames/`（`build_fruitlist.mjs` / `gen_art.mjs` /
`normalize_bg.mjs` / `contact_sheet.mjs` 等），本 skill 是纯说明书 + 模板 +
冻结判据。插画出图调用属 `gen_art.mjs`，不进任何 skill 的 scripts/。

## Resources

- `assets/template/illustration-style.md` — 插画风格判据 + 两条引擎的风格后缀原文与引擎差异记录
- `assets/template/episode-checklist.md` — 每集 48 行注音/转写核对清单模板
- `usine/tools/fruitnames/gen_art.mjs` — 插画产线（STYLE / MMX_STYLE / GATE_PROMPT 唯一事实源）
- `usine/tools/fruitnames/strip_shadow.mjs` — 程序去影 + 像素残影判据（mmx 引擎必经步骤）
- `feuille karaoke check-edges` — 帧边缘溢出门（通用叶子；本产线在成片验收步调用，`--skip intro.png,outro.png`）
- `usine/tools/fruitnames/build_fruitlist.mjs` — 词表派生器（md → json）
- `usine/tools/foodnames/` — 句子门 / 版式门 / 发布侧口径的出处
