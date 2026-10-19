# AGENTS.md · explorateur 工作区约束

> 本仓库承载 `usine/`（feuille——多语种视频生产与发布的可复用层）与 RSI 工作流（`théâtre/` 引擎 + `garage/` 适配层，只对 usine 做单向安全改进）；仓库外同级 `app/` 目录另有两个独立应用，不随本仓库版本化，本文件不约束。
> 本文件只定**工作区级**的约束：技能库在哪、怎么复用、与全局技能的分工、规则以哪份文件为准、Markdown 怎么排版。

## Markdown 排版（硬规则，全工作区一律遵守，屡犯）

- **正文禁止人为按列宽硬换行**：一个自然段写一行，到段落结束才换行。换行只允许出现在结构边界——标题、列表项、表格行、代码块、空行。反例：把一句话在约 76 列处折成两三行；这是 agent 写 md 时最常犯的错，写完自查一遍，发现折叠行就地改回单行。
- 为什么立这条：硬换行让每次改动都抖动整段的 diff（评审看不出到底改了哪个字）、破坏「一行一改动」的 blame、复制粘贴出来全是断句碎片。
- **编辑既有文档不重排**：只改要改的那一行/那一段；不要顺手把别人写好的旧段落重新折行或展开（本文件自身是唯一例外：立规时按新规则整体重排了一次，此后不再动）。
- 表格一行一条记录、代码块保持原样、frontmatter 各键一行，这些结构不受本条约束。

## 技能库（复用入口）

**本工程的技能库在 `usine/skills/`**——仓库资产，随 git 版本化，共 10 个自建 SKILL：

| skill | 用途 |
|---|---|
| `one-page-poster` | 一页纸海报 / 12 语种排版 / 逐字着色 |
| `karaoke-video` | 海报/卡片 → 逐词高亮旁白视频 |
| `multilingual-video-poetry` | 实拍母版 → 配文视频（侧链混音） |
| `bgm-bed` | BGM 底床生成（Lyria）+ 床位定标 |
| `lesson-scene` | 课件解析与场景校验 |
| `character-rig` | 人物 rig / 背景场景 |
| `publish-copy` | 发布词写作 |
| `multilingual-video-publishing` | 平台发布 + 合合集 + 核验 |
| `storyteller-video` | 多幕评书成片（说书人 + 景/镜/转场） |
| `video-generation` | 视频生成母版（选线/提交确认/取回冻结） |

- **总路由表**：[usine/skills/README.md](usine/skills/README.md)——先判断在哪一层，再选 skill；每个 skill 的 description 自带排除语句（Not for …），路由靠它而不是靠猜。
- **运行方式**：feuille 已全量 TS 化（P0–P8 迁移完成，P7 已把 uv/Python 工程物清场退役）——运行与门禁一律走 `pnpm`（Node ≥24）：`pnpm verify` 全量门禁、`pnpm feuille …` CLI；bgm-bed 的 Lyria 客户端（`@google/genai`）随 `@feuille/bgm` 包常装，无需另配 Python 环境。skills 资产里残留的历史 Python 示例脚本只作参考，不是运行路径。
- **发现与引用**：运行机器 `~/.agents/skills/` 只放指向这里的**全局软链**，不存实体（见 usine/AGENTS.md「SKILL 资产」条）。当前只有部分 skill 做了软链——若会话技能列表里没有某个 skill，**直接读本仓库 `usine/skills/<name>/SKILL.md` 照常使用**，不依赖软链存在。

## 与全局同名能力的关系

- **BGM / 配乐**：本工作区一律走 `usine/skills/bgm-bed`——底床生成（Google Lyria，免费层实测线；MiniMax 音乐 API 官方 2026-08-20 日落、两区不收新用户，Suno/Udio 无官方 API，三条死线已删**别再接回**）+ 采样率/频段自检 + 实测反推 `gain`。key 统一配在 `explorateur/config/.env`（样例见 `config/env.sample`；环境变量优先于文件，文件被根 `.gitignore` 兜底永不进仓库）。全局 `music-generation` skill（`~/.agents/skills/`，**非本仓库资产**）的封装能力**已并入 bgm-bed**：它不量频段、不反推床位、没有验收判据，在本工程里已被取代，**不要再往它路由**。
- 同理：视频生成（Veo 等）一律按 usine/AGENTS.md 的 H3 铁律处理，与全局 `video-generation` 等 skill 的关系先查 usine/AGENTS.md 再动手。

## 规则层级

- 在 `usine/` 内工作、或把 feuille 资产用于任何内容项目时，纪律与工程约定的**权威文本是 [usine/AGENTS.md](usine/AGENTS.md)**（22 条纪律 + 跨平台/pnpm 约定 + H3 铁律）；冲突时以它为准。Markdown 排版条（上文）是工作区级新增，usine/AGENTS.md 与它不冲突时同时生效。
- 在 `théâtre/` 内工作或操作 RSI 波次时，先读 [théâtre/PROVENANCE.md](théâtre/PROVENANCE.md)（fork 纪律：POSIX 补丁逐字节不变、不回步上游）与 [théâtre/ARCHITECTURE.md](théâtre/ARCHITECTURE.md)（机制、图表与红线）；适配层操作走 `garage/run_usine.py`（`--preflight` 先行，执行需 ack token；发布永不自动，真波次用户喊跑才跑）。
- 生成类命令默认不覆盖已有产物（显式 `--force` 才覆盖）；验收一律看退出码。
