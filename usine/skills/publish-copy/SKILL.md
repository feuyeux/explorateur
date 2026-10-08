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

Proven on the 12-language "one book" karaoke video (portrait → 小红书 + 抖音, landscape → B站).

**它是两条产线共用的收尾环节**，无论成片来自 `karaoke-video`（海报驱动）还是 `multilingual-video-poetry`（实拍驱动），发布词都走这里——**不要在视频 skill 里另写一份文案**。

## 前置输入契约

开工前必须拿到这 3 条。**缺哪条先问哪条**。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **成品已在盘**（成片 mp4 或海报 PNG）+ 项目 README | 无从提取真实钩子；**规格只能读，不能编** |
| 2 | 核验数字：时长、尺寸、语种/条目数、音频设计 | 写成营销素材的就是这些事实 |
| 3 | 投哪个平台 + 目标（拉新 / 带货 / 导流） | 文案形状随目标变 |

**事实来自成品本身**——时长、语言数、音量、工艺细节必须从实际产物/README 读出来。编造规格是这个 skill 最严重的失败模式。

## 边界

**本 skill 只产出 `publish/*.md`，一个字都不发。**

发布执行（登录态、Playwright、建合集、回列表核验）是 `multilingual-video-publishing` 的事。

**不做 / 转交**：

- 真的点发布、建合集、回列表核验 → `multilingual-video-publishing`
- 生产成片 → `karaoke-video`（海报驱动）/ `multilingual-video-poetry`（实拍驱动）
- 做海报 → `one-page-poster`

## 代码归属

拥有模块：（无）

本 skill **不拥有** `src/feuille` 下的任何模块——它只产出 `publish/*.md` 文本，没有代码。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

## Conventions

- **Platform ↔ format pairing**: 竖屏 9:16 → 小红书 / 抖音; 横屏 16:9 → B站; 长文/图文 → 小红书 / 公众号. One markdown file per platform in the project's `publish/` dir, named `xiaohongshu.md` / `douyin.md` / `bilibili.md` (add others as needed), each with: 文案 sections + 话题标签 + 发布贴士.
- **Platform tone specs**:
  - 小红书 — 标题 ≤ 20 字; emoji per paragraph; 第一人称 + 好奇心钩子; 正文短段多空行; 5–8 个 `#` 话题标签; 结尾必须有关注引导.
  - 抖音 — 一句话钩子 + 互动挑战 (报数/敢不敢); 标签 3–5 个; 附一条备选投流文案.
  - B站 — 标题带 `【】` 分区记号可写长; 简介含 "看片指南" bullet list (把制作细节变成看点) + 制作解析催更钩; 标签空格分隔不带 `#`.
- **拉新 mechanics, every file**: ① 互动钩子把观众赶进评论区 (报数 / 点单 / 跟读挑战); ② 发布贴士里必写 "发布后自己置顶一条引路评论" 并给出具体话术; ③ 下期定制承诺 ("评论区点的语言下一期就做") 让关注有理由.
- **Facts come from the deliverable** — durations, language counts, audio levels, craft details must be read off the actual artifact/README; never invent specs. Craft details (元音红辅音蓝, 词级时间轴, 14 dB BGM bed) ARE the marketing material — surface them as 看点.
- **Markdown style**: follow the `markdown-no-hard-wrap` skill (one logical block per line; run its self-check — `violations: none`).
- After saving, add a `publish/` row to the project README's file listing.

## Workflow

1. **Read the deliverable**: project README + the artifact's verification numbers (duration, dimensions, language/item count, audio design). List the hooks a viewer would care about and the craft details worth bragging about.
2. **Pick platforms** by format (pairing rule above) and confirm the goal (拉新 vs 带货 vs 导流) — copy shape changes accordingly.
3. **Write one file per platform**, each self-contained: 标题 → 正文 → 话题标签 → 发布贴士. Same content hooks, different voice.
4. **Check**: 标题字数 (小红书 ≤20), factual claims vs deliverable, no-hard-wrap self-check on every file.
5. **Update the project README** to mention `publish/`.

## Resources

- `assets/template/` — worked examples from the "one book" video: `xiaohongshu.md`, `douyin.md`, `bilibili.md` (copy the section skeleton, replace the content).
