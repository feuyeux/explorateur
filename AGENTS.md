# AGENTS.md · explorateur 工作区约束

> 本工作区有三个子项目：`usine/`（feuille——多语种视频生产与发布的可复用层）、
> `humming/` 与 `reading/`（两个独立应用，本文件不约束其内部实现）。
> 本文件只定**工作区级**的约束：技能库在哪、怎么复用、与全局技能的分工、规则以哪份文件为准。

## 技能库（复用入口）

**本工程的技能库在 `usine/skills/`**——仓库资产，随 git 版本化，共 8 个自建 SKILL：

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

- **总路由表**：[usine/skills/README.md](usine/skills/README.md)——先判断在哪一层，再选 skill；
  每个 skill 的 description 自带排除语句（Not for …），路由靠它而不是靠猜。
- **运行方式**：一切 Python 走 `uv run --project usine …`；音乐类依赖（bgm-bed 的
  Lyria 客户端）在可选组 `--group music`。
- **发现与引用**：运行机器 `~/.agents/skills/` 只放指向这里的**全局软链**，不存实体
  （见 usine/AGENTS.md「SKILL 资产」条）。当前只有部分 skill 做了软链——
  若会话技能列表里没有某个 skill，**直接读本仓库 `usine/skills/<name>/SKILL.md` 照常使用**，
  不依赖软链存在。

## 与全局同名能力的关系

- **BGM / 配乐**：本工作区一律走 `usine/skills/bgm-bed`——底床生成（Google Lyria，
  免费层实测线；MiniMax 音乐 API 官方 2026-08-20 日落、两区不收新用户，Suno/Udio
  无官方 API，三条死线已删**别再接回**）+ 采样率/频段自检 + 实测反推 `gain`。key
  统一配在 `~/.config/feuille/bgm-bed.env`（样例见该 skill 的
  `references/keys.env.sample`；环境变量优先于文件，文件在 $HOME 下永不进 git）。
  全局 `music-generation` skill（`~/.agents/skills/`，**非本仓库资产**）的封装
  能力**已并入 bgm-bed**：它不量频段、不反推床位、没有验收判据，在本工程里已被
  取代，**不要再往它路由**。
- 同理：视频生成（Veo 等）一律按 usine/AGENTS.md 的 H3 铁律处理，与全局
  `video-generation` 等 skill 的关系先查 usine/AGENTS.md 再动手。

## 规则层级

- 在 `usine/` 内工作、或把 feuille 资产用于任何内容项目时，纪律与工程约定的
  **权威文本是 [usine/AGENTS.md](usine/AGENTS.md)**（22 条纪律 + 跨平台/uv 约定 +
  H3 铁律）；冲突时以它为准。
- 生成类命令默认不覆盖已有产物（显式 `--force` 才覆盖）；验收一律看退出码。
