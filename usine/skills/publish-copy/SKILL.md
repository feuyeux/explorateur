---
name: publish-copy
description: >
  Write platform-specific publishing copy (发布词/文案) for a content
  deliverable — 小红书 captions, 抖音 video descriptions, B站 titles +
  简介 — aimed at user acquisition and marketing (拉新/营销). Use when the
  user asks for "发布词", "发布文案", platform copy for a finished video /
  poster / project, or "怎么发小红书/抖音/B站". The skill extracts true hooks
  from the deliverable itself (never invents specs), adapts tone per
  platform, and saves one markdown file per platform under the project's
  publish/ directory. Not for writing the content itself, and not for actually
  clicking publish on a platform (that is multilingual-video-publishing).
---

# Publish Copy

Turn a finished deliverable (video, poster, article) into per-platform publishing copy whose goal is 拉新 (acquisition) and 营销 (marketing): one `<platform>.md` per platform, ready to copy-paste, with the interaction hooks that convert viewers into commenters and followers.

Proven on the 12-language "one book" karaoke video (portrait → 小红书 + 抖音, landscape → B站), then refined on the 《落叶》 three-act poem (12 languages, 3 acts, all 平台 sharing the same spine — "全世界说到落叶，说的都是回家").

**它是两条产线共用的收尾环节**，无论成片来自 `karaoke-video`（海报驱动）还是 `multilingual-video-poetry`（实拍驱动），发布词都走这里——**不要在视频 skill 里另写一份文案**。

## 前置输入契约

开工前必须拿到这 3 条。**缺哪条先问哪条**。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **成品已在盘**（成片 mp4 或海报 PNG）+ 项目 README + **内容事实源**（诗行/译文/幕名这类真正写了东西的单一事实源文件） | 无从提取真实钩子；**规格只能读，不能编**；没有事实源，写出来的只能是规格单 |
| 2 | 核验数字：时长、尺寸、语种/条目数、音频设计——**落成一份 facts.json**（ffprobe 时长 / manifest 条目数 / bgm 边车数字） | 数字溯源门只能 SKIP；写成营销素材的就是这些事实 |
| 3 | 投哪个平台 + 目标（拉新 / 带货 / 导流） | 文案形状随目标变 |

**事实来自成品本身**——时长、语言数、音量、工艺细节必须从实际产物/README 读出来。编造规格是这个 skill 最严重的失败模式。

## 边界

**本 skill 只产出 `publish/*.md`，一个字都不发。**

发布执行（登录态、Playwright、建合集、回列表核验）是 `multilingual-video-publishing` 的事。

**不做 / 转交**：

- 真的点发布、建合集、回列表核验 → `multilingual-video-publishing`
- 生产成片 → `karaoke-video`（单卡片）/ `storyteller-video`（多幕评书）/ `multilingual-video-poetry`（实拍驱动）
- 做海报 → `one-page-poster`

## 代码归属

拥有模块：（无）

本 skill **不拥有** `src/feuille` 下的任何模块——它只产出 `publish/*.md` 文本，没有代码。`scripts/check_publish_copy.py` 是发布词自检（标题字数 / 尾随空格 / 互动钩 / 置顶话术 / no-hard-wrap / AI 指纹 / `--facts` 数字溯源），与下面的 `## 验收判据` 表一一对应；它住在 `scripts/` 不是 `src/feuille/`，与 `bgm-bed/scripts/gen_bgm.py` 同一类。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

## Conventions

### 各平台规格

- **Platform ↔ format pairing**: 竖屏 9:16 → 小红书 / 抖音; 横屏 16:9 → B站; 长文/图文 → 小红书 / 公众号. 文件命名硬约定 `publish/xiaohongshu.md` / `publish/douyin.md` / `publish/bilibili.md`，加其它平台走同样命名。

- **小红书** — 标题 ≤ **20 字**（emoji 按 1 字算）；emoji per paragraph；第一人称 + 好奇心钩子；正文短段多空行；5–8 个 `#` 话题标签，**最后一个标签后留一个尾随空格**（publish-playbook 坑 ① 线上事故：Slate 在 blur 时把未闭合的 `#tag` 当话题候选弹联想面板并改内容）；结尾必须有关注引导。

- **抖音** — 标题 ≤ **30 字**（`## 文案` 段**第一行**就是标题——抖音投稿表单的「标题」与「正文」共用一个输入框，开头即标题；标题与正文之间空一行）；第一行钩子 + 互动挑战（报数/点单/跟读）；标签 3–5 个，**最后一个标签后留一个尾随空格**（同坑 ①，抖音 + 小红书都适用）；附一条备选投流文案（放在 `## 备选文案（投流版）` 段）。

- **B站** — 标题 ≤ **80 字**，带 `【】` 分区记号可写长；简介含「制作解析催更钩」（**不要做"看片指南/彩蛋"bullet 段**——那是规格单，发布词要承载的是思想/意境/态度；工艺细节留在 README 与技术文档）；标签**空格分隔不带 `#`**（B 站 tag 区是 `language tag` 风格，不存在尾随空格问题）。

### 跨平台铁律

- **拉新 mechanics, every file**: ① 互动钩子把观众赶进评论区（报数 / 点单 / 跟读挑战）；② 发布贴士里必写"发布后自己置顶一条引路评论"并给出具体话术（带引号的示例）；③ 下期定制承诺（"评论区点的语言下一期就做"）让关注有理由。

- **不解释画面** — 文案里**不要给读者解释画面上的物理信息**：什么颜色代表什么、字幕怎么动、BGM 是几 dB、画面多大、播放几秒。读者会自己看视频。**你给的是思想、意境、态度**——读完后读者带走的是感受，不是规格单。工艺细节属于 README 与技术文档，**不属于发布词**。这一条比"把工艺当卖点"更基本：规格当卖点是"放错位置"，物理进文案是"放错了工具箱"。

- **Facts come from the deliverable** — 数字必须可溯源，never invent specs：Bed level 以 `bgm-bed` 边车 json 为准（例：《落叶》`gain_basis = 旁白 -23.2 dBFS − 目标 16 dB − 床 -13.8 dBFS`），时长以 `ffprobe` 出的 mp4 时长为准。这些数字**只进项目 README 与发布贴士，不进文案正文**。

- **Markdown style** — follow the `markdown-no-hard-wrap` skill（全局 skill，仓库内不存实体）：每个逻辑块一行，不按字数硬换行；`scripts/check_publish_copy.py` 内联其判定逻辑（drift 风险写在脚本注释里）。
- **字斟句酌，没有一字是废话** — "原来..." "藏了心机" "yyds" "绝绝子" "宝藏" 是 AI 指纹；emoji 滥用、感叹号刷屏、通用 closer、"像 X 一样的 Y" 模板句，单独无害连用即 AI 味。可枚举签名已由机检拦，「听起来像在给另一个 AI 解释」的语感仍归人工走查（详见「失败模式」末条）。

- After saving, add a `publish/` row to the project README's file listing.

## 题眼（文案拿得出手的线）

把规格当钩子是本 skill 最常见的不合格态（理由见「跨平台铁律 · 不解释画面」）。

拿得出手的发布词有**一条脊柱**：从内容事实源里挖出的那个让人愿意看完的发现，一句话能说清。例（《落叶》）：一片叶子，落在十二种语言里。离枝、随风、归根——各自写。写到"归根"那一幕，写的全是"回家"——英语 Homecoming，德语 Heimkehr，俄语 Домой，希腊语借了荷马史诗"归途"那个词——Νόστος。英语"乡愁"（nostalgia）的根，就在这里。三份平台稿共用同一条脊柱，只换嗓门。

- **挖题眼**：通读内容的单一事实源（诗行、译文、幕名……），抄下可直接引用的句子（"叶子飞着，像一封信"），找跨语种/跨条目反复出现的母题——它就是题眼；
- **工艺不进文案**：逐词高亮、双色标记、底床定标是成片自带的东西，发布词里**不出现**（完整理由见「跨平台铁律 · 不解释画面」条）；
- **引文逐字**：抄进文案的每一句诗、每一个外语词必须与事实源逐字一致；涉及顺序的数字（"第 7 个是希腊语"）要对成片时间轴核过再写；
- **成品自检三问**：第一行能让人停下滑动的手吗？最后一段给"看完"之外的动作（报数/点单）了吗？三份稿是同一条脊柱吗？——一个"否"就回炉。

## 失败模式

按发生频率排，都从真实事故或实测踩坑里来：

- **规格单当钩子 / 把工艺塞进文案** — "12 语种 / 16 dB 床 / 52 秒""大字红是元音，蓝是辅音"是工艺参数不是卖点，第一段就把观众赶跑。**工艺不进文案**（见「跨平台铁律 · 不解释画面」条）；文案只承载**思想/意境/态度**，工艺细节留给 README 与技术文档。
- **编造规格** — 时长 / 语种数 / 电平没从成片或 README 读就写出来，是本 skill 最严重的失败模式。每条数字必须可溯源到事实源文件。
- **序号对不上时间轴** — "第 7 个希腊语跟读翻车"这种位置引用必须对成片时间轴核过再写；同一批 12 语种成片，时间轴里希腊语不一定是第 7 个，写错了就是反向造假。
- **跨平台标题照搬** — 抖音 ≤30 / 小红书 ≤20 不一致，29 字抖音标题原样进小红书被编辑器红字拒（实测显示 `28/20`）。**小红书标题另起一句**，按 publish-playbook §2 反推字数。
- **话题不带尾随空格** — 抖音 + 小红书的最后一个 `#tag` 后必须留一个尾随空格，否则 Slate 在 blur 时把它当未闭合话题弹出联想面板并改写内容（publish-playbook 坑 ① 线上事故，已造成发布事故）。`scripts/check_publish_copy.py::check_trailing_space` 拦这道门。
- **AI 味重** — 这是行业病，比规格单当钩子更隐蔽：单独看每句都不算坏，连着用就是 AI 指纹。**可枚举的签名已机器拦截**（`check_ai_fingerprint`：字面词清单、句首「原来…」揭秘句式、连叹号、「像 X 一样的 Y」模板句、一行 emoji 滥用——反向验证在 `usine/scripts/verify_skill_scripts.py`，且以归稿《落叶》为校准锚：新签名在已验收成果上误伤就是太凶）。机器拦不住的部分——节奏、模板感、「听起来像在给另一个 AI 解释」的语感——仍是写者的人工走查。

## 验收判据

机检门（`scripts/check_publish_copy.py` 一一对应，纪律 6 不变量必须有机检）：

| 判据 | 实现 | 不达标怎么读 |
|---|---|---|
| 三平台 标题字数（小红书 ≤20 / 抖音 ≤30 / B站 ≤80） | `check_title_len` | 超字数 → 平台编辑器红字拒 |
| 抖音 + 小红书 话题末尾尾随空格 | `check_trailing_space` | 漏空格 → Slate 联想面板吃掉末段话题（见「失败模式」末条） |
| 三平台 互动钩短语必现一 | `check_hook_phrase` | 缺互动钩 → 评论区冷场，拉新失败 |
| 三平台 发布贴士含置顶话术（"置顶" + 引号示例） | `check_pinned_quote` | 没具体话术 → 自己置顶时临时编，编出来的钩子弱 |
| 各平台必需 H2 段落齐全 | `check_required_sections` | 段落缺失 → 下一棒 publishing skill 取不到字段 |
| no-hard-wrap 零违规 | `check_no_hard_wrap` | 段内硬换行 → diff 噪声放大 + CJK 边界伪影 |
| AI 指纹零命中（读者面） | `check_ai_fingerprint` | 字面签名（yyds/绝绝子/宝藏…）、句首「原来…」、连叹号、「像 X 一样的 Y」、一行 emoji 滥用 → **可枚举的 AI 味已机器拦截**；语感仍归编辑走查 |
| 数字可溯源（`--facts facts.json` 给了才跑） | `check_fact_provenance` | 读者面文字里的数字对不上事实表 → 编造规格嫌疑；**未给 `--facts` 时 SKIP，SKIP 不是 PASS** |

**机检门过了还有编辑层**——`scripts/check_publish_copy.py` 不查的：引文是否逐字取自
事实源、序号是否对时间轴（「第 7 个」类位置引用）、题眼是否到位、成品自检三问、
语感（指纹门只拦得住能写成规则的签名，拦不住节奏与模板感）。这是**写者本人**的
走查，机检做不了。「事实 vs 成品」在给了 `--facts` 时已降级成机检（上表末行）——
把 ffprobe / manifest / 边车的实测数抄进 facts.json 再写文案，写进去的每个数字都有出处。

## Workflow

1. **挖题眼（先于一切）**：通读内容事实源——诗行/译文/幕名这些真正写了东西的文件，不是只读 README 的规格数字。抄下可逐字引用的句子，找跨语种/跨条目的母题，用一句话说出"观众为什么要看完这条"。规格数字随后读，作佐证与发布贴士。
2. **Pick platforms** by format (pairing rule above) and confirm the goal (拉新 vs 带货 vs 导流) — copy shape changes accordingly.
3. **Write one file per platform**, each self-contained: 标题 → 正文 → 话题标签 → 发布贴士. Same spine, different voice.
4. **Check** — run `python scripts/check_publish_copy.py <publish_dir> --facts facts.json`（机检门与「验收判据」表一一对应；facts.json 只抄实测数——ffprobe 时长、manifest 条目数、bgm 边车数字，键随意、值必须可核对；没给 `--facts` 数字溯源是 SKIP 不是 PASS）。Then layer the editorial checks the script can't do: 引文逐字对事实源, 序号对时间轴, 题眼, 成品自检三问. **机检 0 违规 + 编辑三问全 YES 才算过**。
5. **Update the project README** to mention `publish/`.

## 与发布执行的接缝

`multilingual-video-publishing` 消费本 skill 的产物，**不写、不改文案**——只搬运 + 拍照核验。契约如下：

- **文件命名硬约定**：`publish/xiaohongshu.md` / `publish/douyin.md` / `publish/bilibili.md`。加其它平台走同样命名。
- **段落齐全**：见 `## 验收判据` 表的 `check_required_sections` 行——publishing 端按 H2 标题取字段，缺段直接报错。
- **字数硬上限**：20 / 30 / 80（小红书 / 抖音 / B站）。publishing 端 `check_plan.py` 也会卡，但写时就过更便宜。
- **话题末尾尾随空格**：抖音 + 小红书必带；B 站 tag 区无此问题。
- **三平台一致性**：同一条脊柱 / 三种嗓门。**publishing 不会替你做编辑**——如果三份稿脊柱不一致或事实互相打架，publishing 会原样发出去互相拆台。
- **不要把发布执行的事编进文案**：发布贴士里写"发布后置顶评论（话术：'…'）"是本 skill 的事；写"用 XX 工具点 XX 按钮"是 publishing 的事，不归这里。

## 资源

- `assets/template/` — worked skeleton from the "one book" video: `xiaohongshu.md`, `douyin.md`, `bilibili.md` (copy the section skeleton, replace the content). 模板已含尾随空格与各平台必需段落。
- `assets/example/` — 《落叶》精修成稿（竖屏→小红书/抖音，横屏→B站）：题眼"12 语种的『归根』全是『回家』"，工艺细节零入文。与 `assets/template/` 对照着读——同一套骨架，规格单文案与题眼文案的差距一目了然。
- `scripts/check_publish_copy.py` — 发布词自检（标题字数 / 尾随空格 / 互动钩 / 置顶话术 / no-hard-wrap / AI 指纹 / `--facts` 数字溯源），与 `## 验收判据` 表一一对应；写完必跑 `--facts facts.json`，0 违规才进 publishing。反向验证（指纹凿洞、溯源对账、归稿校准锚）在 `usine/scripts/verify_skill_scripts.py`。
