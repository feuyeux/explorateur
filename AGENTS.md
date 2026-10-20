# AGENTS.md · explorateur 工作区约束

> 本仓库承载 `usine/`（feuille——多语种视频生产与发布的可复用层）与**两条** RSI 工作流：`théâtre/` 引擎 + `garage/` 适配层（RSIAgent 路线，改**记忆**），`theatre-ii/` 引擎 + `garage-ii/` 适配层（harness2 路线，改 **harness 本身**）；两条都只对 usine 做单向安全改进。仓库外同级 `app/` 目录另有两个独立应用，不随本仓库版本化，本文件不约束。
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

## 内容产物落位（硬规则）

- **生成出来的内容项目只允许两处**：`usine/skills/<skill>/assets/`（可复用资产——模板、示例、夹具，随 git 版本化）与 `usine/examples/<项目名>/`（内容项目产物——成片、封面、12 语种文案，**不入库**，由根 `.gitignore` 的 `examples/` 兜底）。**没有第三处。**
- 仓库根与 `usine/` 顶层**不再长项目目录**。反例：`chess-12lang/`（12 语种国际象棋系列）曾直接堆在仓库根并被入库——222 个文件、99 个 LFS 对象共 129.5 MB。它的内容和产物都没毛病，**位置错了**。
- 判断口径：这个项目**以后还会被别的项目复用**吗？会 → 抽成 skill 资产（进 `skills/`）；不会，只是这一轮的内容 → 进 `examples/`。拿不准按后者走，别进索引。
- 机检：`usine/packages/gate/test/layout.test.ts` 对仓库根目录做白名单，多一个就 FAIL，失败信息直接给出这两条落位路径。

## 与全局同名能力的关系

- **BGM / 配乐**：本工作区一律走 `usine/skills/bgm-bed`——底床生成（Google Lyria，免费层实测线；MiniMax 音乐 API 官方 2026-08-20 日落、两区不收新用户，Suno/Udio 无官方 API，三条死线已删**别再接回**）+ 采样率/频段自检 + 实测反推 `gain`。key 统一配在 `explorateur/config/.env`（样例见 `config/env.sample`；环境变量优先于文件，文件被根 `.gitignore` 兜底永不进仓库）。全局 `music-generation` skill（`~/.agents/skills/`，**非本仓库资产**）的封装能力**已并入 bgm-bed**：它不量频段、不反推床位、没有验收判据，在本工程里已被取代，**不要再往它路由**。
- 同理：视频生成（Veo 等）一律按 usine/AGENTS.md 的 H3 铁律处理，与全局 `video-generation` 等 skill 的关系先查 usine/AGENTS.md 再动手。

## 规则层级

- 在 `usine/` 内工作、或把 feuille 资产用于任何内容项目时，纪律与工程约定的**权威文本是 [usine/AGENTS.md](usine/AGENTS.md)**（22 条纪律 + 跨平台/pnpm 约定 + H3 铁律）；冲突时以它为准。Markdown 排版条（上文）是工作区级新增，usine/AGENTS.md 与它不冲突时同时生效。
- 在 `théâtre/` 内工作或操作 RSI 波次时，先读 [théâtre/PROVENANCE.md](théâtre/PROVENANCE.md)（fork 纪律：POSIX 补丁逐字节不变、不回步上游）与 [théâtre/ARCHITECTURE.md](théâtre/ARCHITECTURE.md)（机制、图表与红线）；适配层操作走 `garage/run_usine.py`（`--preflight` 先行，执行需 ack token；发布永不自动，真波次用户喊跑才跑）。
- 在 `theatre-ii/` 内工作或操作 harness 演化时，先读 [theatre-ii/PROVENANCE.md](theatre-ii/PROVENANCE.md)（vendor 范围、零补丁声明、已知能力缺口）与 [theatre-ii/ARCHITECTURE.md](theatre-ii/ARCHITECTURE.md)（c1..c8 与 Propose–Probe–Compose）；**引擎层不含任何 usine/dsh 专属代码**，桥接一律在 `garage-ii/`，操作走 `garage-ii/run_usine_h2.py`（`--phase preflight` 先行，`--phase sweep` 需 ack token `RUN-USINE-H2-SWEEP`）。
- **两条路径的关系**：RSIAgent（`théâtre/`+`garage/`）改的是**记忆**，harness2（`theatre-ii/`+`garage-ii/`）改的是**harness 本身**。引擎层对照见 [theatre-ii/COMPARISON.md](theatre-ii/COMPARISON.md)，可跑的三臂对照协议见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md)——**读数字之前先读该文档的「测不到什么」一节**。
- **两条路径共同的硬约束**：基准 harness 必须与被改进对象**同源**（`garage-ii/build_base_harness.py` 派生，带漂移闸）；运行产物落**仓库外** run root（dsh 的 project root 判定会让仓库内的 `.dsh/skills` 判到仓库根，候选技能一个都扫不到，且**不报错**）；判据失败是 `None` 不是零分；判据不进 harness 树。
- **演化结果先看「阶段回退」再看分数**：提案阶段失败时引擎会**退回基准树**继续跑，这一轮「看起来跑完了」，而最终被采纳的其实是**没改过的基准**——分数量的是基准，不是演化后的。`garage-ii` 的 sweep / judge 会把回退打出来并以**退出码 1** 结束。读数纪律与第一批真跑的实测记录见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md) 的「实测记录」一节。
- **说「演化带来了提升」之前，先有同树零分布**：同一棵 harness 树、同一道题、同一模型，重复 rollout 的分数会在一个宽度里动——2026-10-20 实测：**四棵臂树逐字相同**，分数 80%/100%/100%/100%。没有零分布就没有「提升」这个说法。`garage-ii/arms.py` + `--phase repeat` / `--phase compare` 是这把尺子（判据：Δ > 0 **且** 单侧精确置换检验 p ≤ 0.1；零分布宽度只报不判）。用法见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md) 的「怎么量」一节。
- **基准环境不健全时，任何读数都量不到 harness**：2026-10-20 实测，基准工作区**漏装了技能自带的 `assets/` 与 `references/`、PATH 上也没有 `feuille`**——技能手册指向不存在的模板，智能体于是（正确地）判定「工具面之外没有验收口径」而停手。那一格的分数量的是「工作区完整与否」。**凡是换过工作区/题面/判据之后，旧读数一律作废**；`garage-ii/preflight.py` 的「装出来的工作区里技能资源在位」是这条的闸。记录见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md) 第 12 节。
- **自检只测内存里的对象，等于没测**：2026-10-20 实测，独立复查抓到三个**自查测不到**的缺陷——新字段没进 `to_dict`（于是 CLI 路径上的判定从来没生效）、compare 只比两臂的交集（少一格照样绿灯）、`rescore` 指错参数会**静默擦掉**一个臂还退出 0。**凡是「落盘 → 读回 → 判定」的逻辑，自检必须走那条真实路径**（落盘、CLI、错误参数三条都要有例）。记录见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md) 第 13 节。
- **判据不许比被改进对象自己的文件更严**：2026-10-20 实测两处误伤——「只认 MCP 工具入口」把走手册钦定 CLI 入口的 rollout 判成没干活；「抓绕行」把「定位浏览器二进制」这种准备动作也算绕行。判据的依据必须是**被改进对象自己的文件**（手册、系统提示、工具指引），不是「我觉得更合理」；而且**放宽往往更严**（基准抬高 ⇒ 演化要追的差距更小）。记录见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md) 第 14 节。
- **量到「缺陷」之前先问一句：这是被改进对象的缺陷，还是我自己的判据/环境的缺陷**：2026-10-20 实测，基准臂 2 条 rollout 的产物被**后来的进程**擦掉（run 目录被重建），判据照直判成「没交付」——那量的是进程管理；同一轮里，演化提案者的「什么也不改」也有据可查：它看的证据是全的，但引擎的两个维度分工里没人被问「always-on 写着的纪律，轨迹守住了吗」。**两处都不是「智能体不行」**。记录见 [garage-ii/BENCHMARK.md](garage-ii/BENCHMARK.md) 第 14、15 节。
- 生成类命令默认不覆盖已有产物（显式 `--force` 才覆盖）；验收一律看退出码。
