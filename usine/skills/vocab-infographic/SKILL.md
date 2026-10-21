---
name: vocab-infographic
description: >
  Turn ONE user-given Chinese noun or verb (叶子 / 飞翔 / 攀爬 / 草莓 …) into a
  12-language vocabulary infographic as a single generated image. Two stages:
  (1) draft the 12-language dictionary-form word list with phonetic notation /
  transliteration, get the user to review it word-by-word, then assemble an
  idempotent image-generation prompt from the template and save it under
  prompts/<word>-vocab-infographic/; (2) after confirmation, generate the PNG
  with the user's image skill. Fixed vintage-encyclopedia illustration style,
  central subject drawn per word, clockwise 12-word ring, vowel-red /
  consonant-blue coloring, theme-token palette. Not for HTML/CSS page posters
  (that is one-page-poster), not for video assembly (karaoke-video /
  storyteller-video), not for live-action footage (video-generation), not for
  multi-word decks or courseware (lesson-scene).
---

# Vocab Infographic

一个词 → 一张 12 语种词汇图鉴（生成式图像）。画面骨架全部钉死（环排方位、
三行堆叠、指引线、图例、颜色 token），只有两样东西随输入变化：**中央主体插画**
（按词生成）与**十二组词汇内容**（现翻 + 人审）。模板与全部约定见
`assets/template/prompt_template.md`；一份逐字核过的工作样例（草莓）见
`assets/example/strawberry/prompt.md`——**从模板起草，从样例对账**。

## 前置输入契约

开工前必须拿到这 5 条。**缺哪条先问哪条，不要拿占位值往下跑**——词表错一个
拼写，整张图作废。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **一个名词或动词**（词 + 词性） | 中央主体与词表无从谈起；一次只做一个词 |
| 2 | **逐词核对清单过审**：12 语种译文 + 注音/转写由 LLM 现翻，用户逐词确认后才能进提示词 | 错译 / 错拼写会直接烙进图里，生图模型不会替你校对 |
| 3 | **中央主体画面描述**：该词画成什么（叶子=单片叶特写；飞翔=展翅的鸟；攀爬=藤蔓绕杆） | 生图模型自行发挥，多次生图主体漂移 |
| 4 | **主题**：5 套之一；不指定时跑 `pnpm feuille theme match <词>` 自动推荐，向用户报备 | 颜色漂移，幂等性破功 |
| 5 | **图像模型与画幅**：默认 3:2 横版；用哪个用户级图像 skill 出图 | Stage 2 无从执行 |

词形与注音规则（Stage 1 现翻时逐条适用）：

- **词典基本形**：名词取单数，动词取不定式 / 词典形（climber 不收，收 climb；
  登る不收，收 登る的词典形——各语种按其词典的 lemma 惯例）。
- 注音 / 转写体系固定：汉语用**注音符号（ㄅㄆㄇㄈ），不用汉语拼音**；日文
  Hepburn；韩文文化观光部 2000 罗马字；印地 ISO 15919；阿文 DIN 31635；
  希文 ISO 259。不得为配色改拼写。
- 语言称谓一律本地名（English / Deutsch / 日本語…），禁统一「×语」标签。

## 流程（两段式）

**Stage 1 · 词表 + 提示词（必须先过审）**

1. 拿到词后先出**逐词核对清单**：12 个语种各一行（称谓 / 词汇 / 注音·转写 /
   该语种着色方式），附中央主体画面描述与主题推荐，一并交用户审核。
   语种集合与顺序以 `languages/*/manifest.json` 的 `order`/`tier` 字段为准
   （核心 12 种）；规范顺序的唯一事实源在 `one-page-poster` §Conventions，
   本 skill 不另抄。
2. 用户逐词确认（或改词）后，复制 `assets/template/prompt_template.md` 到
   `prompts/<word>-vocab-infographic/prompt.md`，把过审的词表、中央主体描述、
   所选主题的 token 值表逐项填入。词表内容**逐字使用**，模板的布局 / 着色 /
   红线条款一个字不改。
3. 自查：十二组方位表、内容表、图例示例字、§8 红线逐条可对账（对照
   `assets/example/strawberry/prompt.md` 的成熟形态）。

**Stage 2 · 生图与验收**

4. 用用户级图像 skill（如 nano-banana-pro / gpt-image-2 / openai-image-gen）
   按提示词出图，3:2 横版高清。
5. 验收 = 提示词 §8 红线逐条人眼核对（12 组落位、拼写、RTL、着色、感官等大）。
   不合格改图重来，**不改提示词红线**；确需改约定的（如换主题），回 Stage 1
   重走确认。

## 复用幂等（AGENTS.md 纪律 13/23）

- **Stage 1 重跑**：`prompts/<word>-vocab-infographic/prompt.md` 已存在时不
  静默覆盖——先把新起草稿与现存文件 diff，报差异清单，用户确认哪版为准后再落盘
  （生成类命令默认不覆盖，纪律 13）。
- **Stage 2 重跑**：PNG 已存在时先报备再重新出图。生图模型非确定性，同一
  提示词两次出图不会逐字节一致——本线的幂等不靠文件字节，靠提示词 §8 红线
  逐条可对账；所以提示词是唯一值得锁定的产物。
- **落位（AGENTS.md「内容产物落位」）**：本轮的提示词草稿写到项目根下的 `prompts/<word>-vocab-infographic/prompt.md`——项目根是 `usine/examples/<项目名>/`（不入库）。**不要写进 `usine/` 顶层**。唯一的例外是随 git 版本化的模板与样例，它们在 `assets/template/` 与 `assets/example/`。
- **样例不是活实例**：`assets/example/` 下是**冻住的参考稿**（`strawberry` + 九大艺术系列 9 个词，各含横竖两版），逐字核过，起草后拿它逐项对账。**它们与任何活实例之间没有同步义务**——曾经有一条「双副本必须逐字节一致、机检在 `verify_skill_scripts.py`」的约定，而那个脚本已随 Python 退役删除、草稿也已迁出仓库，所以那条约定在 2026-10-21 一并撤掉。**别为了满足一条不存在的机检去改文件。**
- **为什么这 9 个词进了 assets 而不是 examples**：它们是**已过审的系列样例**（九大艺术，2026-10-13 人审过），会被反复拿来对账，性质是「以后还会被复用」⇒ 按落位口径属资产、随 git 版本化。一次性的下一轮新词仍走 `examples/<项目名>/`，不入库。这批文件原先堆在 `usine/prompts/` 顶层（AGENTS.md 里明令禁止的第三处），2026-10-21 按上图口径归位，**内容一字未改**。

## 边界

**本 skill 只管「单张 12 语种词卡的生成式图像提示词 + 出图」**。风格、堆叠、
着色、图例的约定钉死在模板里，泛化只发生在词表与中央主体两处。

**不做 / 转交**：

- 排 HTML/CSS 海报、逐字着色的字形级实现 → `one-page-poster`（那是渲染产线，
  有像素级机检；本 skill 的提示词可作它的设计 brief）
- 组装成片 / 逐词高亮视频 → `karaoke-video`（单卡片）或 `storyteller-video`
  （多幕评书）
- 实拍视频母版 → `video-generation`（那是视频线；本 skill 出的是静态图）
- 多词词卡册、整课课件 → `lesson-scene`
- 出图本身走用户级图像 skill，本 skill 不拥有任何生图调用代码

## 代码归属

拥有模块：（无）

本 skill 是纯说明书：模板 + 工作样例 + 流程约定，没有任何 `src/feuille` 模块。主题色事实源在 `skills/theme-tokens.css`，主题推荐走 `pnpm feuille theme match <词>`（`@feuille/core/themes`；它的前身 `skills/match_theme.py` 已升包退役）。事实源见 `usine/ownership.json`，由 `packages/gate` 的归属对账机检。

## Resources

- `assets/template/prompt_template.md` — 提示词骨架（布局 / 着色 / 红线全钉死，含全部占位符与填写说明）
- `assets/example/` — 冻住的参考稿：`strawberry/`（草莓）+ 九大艺术（`01_painting` / `02_sculpture` / `03_architecture` / `04_music` / `05_literature` / `06_dance` / `07_theatre` / `08_cinema` / `09_video-games`），每词 `prompt.md`（横版）+ `prompt_vertical.md`（竖版），起草后逐项对账用
- `skills/theme-tokens.css` — 5 套主题 token，颜色的唯一事实源
- `pnpm feuille theme match <词>` — 按词自动推荐主题（`@feuille/core/themes`）
- `languages/*/manifest.json` — 语种集合与 order/tier 的事实源
