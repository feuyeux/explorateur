# AGENTS.md · explorateur 工作区约束

> 本仓库（`explorateur/`）是**工作区**，不是单体工程。根目录只有七样东西：产线 `usine/`，两条 RSI 线路（`théâtre/` + `garage/`、`theatre-ii/` + `garage-ii/`），跨线路共享配置 `config/`，自我进化总文档 `docs/`，加两份索引与规则文件。仓库外同级 `app/`（`humming`、`reading`）是不随本仓库版本化的两个独立应用，本文件不约束。
> 本文件只定**工作区级**约束：产物往哪落、技能库在哪、配置在哪、Markdown 怎么排版、规则以哪份文件为准、读数纪律。**项目级细节一律不在这里复制**——进对应子项目读它自己的 README / AGENTS / PROVENANCE。

## 一、目录与各自的权威文档

| 目录 | 是什么 | 权威文档（冲突时以它为准） |
|---|---|---|
| `usine/` | feuille：多语种视频生产与发布可复用层（TS pnpm monorepo，12 包） | [usine/AGENTS.md](usine/AGENTS.md)（22 条纪律 + 工程约定 + H3 铁律）· [usine/README.md](usine/README.md) |
| `théâtre/` | RSIAgent 引擎（vendored fork，**无内部 `.git`**，版本由本仓库统一管理） | [théâtre/PROVENANCE.md](théâtre/PROVENANCE.md)（fork 纪律：POSIX 补丁逐字节不变、不回步上游）· 机制与图表 → [docs/self-evolution.md](docs/self-evolution.md) §2 |
| `garage/` | RSIAgent 线路的适配层：装配 / 传输 / 围栏 / 合并 / 门禁预检 | `run_usine.py` 模块 docstring（装配契约，13 条，次序承重）· 运行手册 / 验收 / 红线 → [docs/self-evolution.md](docs/self-evolution.md) §2、§8、§9、§11 |
| `theatre-ii/` | harness2 引擎（vendored fork，Apache-2.0，**零补丁**） | [theatre-ii/PROVENANCE.md](theatre-ii/PROVENANCE.md)（vendor 范围与已知缺口）· 机制与图表 → [docs/self-evolution.md](docs/self-evolution.md) §3 |
| `garage-ii/` | harness2 线路的桥接层：dsh 那一面 + usine 那一格 + 对照驱动 | 桥接层 / 测量协议 / 产物对照 → [docs/self-evolution.md](docs/self-evolution.md) §3–§7 · 实测逐字归档仍在 [BENCH-APPENDIX-2026-10.md](garage-ii/BENCH-APPENDIX-2026-10.md) · 跨轮次方法论在 [docs/self-evolution.md](docs/self-evolution.md) §12 |
| `config/` | 跨线路共享配置。`env.sample` 入库，`.env` 本地且被根 `.gitignore` 兜底 | [config/env.sample](config/env.sample) 的注释即说明书 |

**两条线路的引擎层不含任何 usine 专属代码**，桥接一律在适配层。改引擎前先读对应 PROVENANCE：`théâtre/` 是「补丁逐字节不变」，`theatre-ii/` 是「零补丁」。

## 二、Markdown 排版（硬规则，全工作区一律遵守，屡犯）

- **正文禁止人为按列宽硬换行**：一个自然段写一行，到段落结束才换行。换行只允许出现在结构边界——标题、列表项、表格行、代码块、空行。反例：把一句话在约 76 列处折成两三行；这是 agent 写 md 时最常犯的错，写完自查一遍，发现折叠行就地改回单行。
- 为什么立这条：硬换行让每次改动都抖动整段的 diff（评审看不出到底改了哪个字）、破坏「一行一改动」的 blame、复制粘贴出来全是断句碎片。
- **编辑既有文档不重排**：只改要改的那一行/那一段；不要顺手把别人写好的旧段落重新折行或展开。
- 表格一行一条记录、代码块保持原样、frontmatter 各键一行，这些结构不受本条约束。

## 三、技能库（复用入口）

**本工程的技能库在 `usine/skills/`**——仓库资产，随 git 版本化，共 11 个自建 SKILL（**唯一权威清单是 `usine/skills/*/SKILL.md` 的目录列举**；本表列漏了只会让人少看见一个，不会让路由失效，但漏了就补上）：

| skill | 用途 |
|---|---|
| `one-page-poster` | 一页纸海报 / 12 语种排版 / 逐字着色 |
| `vocab-infographic` | 单词语汇图鉴（生成式图像，不走渲染/合片） |
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
- **发现与引用**：运行机器 `~/.agents/skills/` 只放指向这里的**全局软链**，不存实体（见 usine/AGENTS.md「SKILL 资产」条）。若会话技能列表里没有某个 skill，**直接读本仓库 `usine/skills/<name>/SKILL.md` 照常使用**，不依赖软链存在。

## 四、内容产物落位（硬规则）

- **生成出来的内容项目只允许两处**：`usine/skills/<skill>/assets/`（可复用资产——模板、示例、夹具，随 git 版本化）与 `usine/examples/<项目名>/`（内容项目产物——成片、封面、12 语种文案，**不入库**，由根 `.gitignore` 的 `examples/` 兜底）。**没有第三处。**
- 仓库根与 `usine/` 顶层**不长项目目录**。反例：`chess-12lang/`（12 语种国际象棋系列）曾直接堆在仓库根并被入库——222 个文件、99 个 LFS 对象共 129.5 MB。它的内容和产物都没毛病，**位置错了**。
- 判断口径：这个项目**以后还会被别的项目复用**吗？会 → 抽成 skill 资产（进 `skills/`）；不会，只是这一轮的内容 → 进 `examples/`。拿不准按后者走，别进索引。
- **CLI 的产物目录是 `<项目根>/build/`**——**项目根不能是仓库根**。在仓库根跑一次 CLI 就会重新长出 `build/`，白名单门禁又红一次（`.gitignore` 忽略它也没用：门禁按目录名判定，不看 ignore）。要跑就在 `usine/examples/<项目名>/` 这类项目根里跑。
- 机检：`usine/packages/gate/test/layout.test.ts` 对仓库根目录做白名单，多一个就 FAIL，失败信息直接给出这两条落位路径。白名单是人手工维护的（**故意的**：新增根目录必须停下来回答「这是不是又一处放内容的地方」）。
- **这条门禁已转绿（2026-10-21 处置记录）**：仓库根曾同时存在 `build/`、`garage-result/`、`garage-ii-result/` 三个不在白名单里的目录。`garage-result/` 与 `garage-ii-result/` 是**误建**——真运行产物在仓库外（见下节），仓库内这两个空目录已删（可从回收站恢复）；`build/` 是 CLI 在仓库根跑出来的产物目录（673 MB / 17129 文件，被 `.gitignore` 忽略），它装的是**内容产物**（4222 个 md、4010 个 png、3460 个 tex），按上面的落位口径已迁到 `usine/examples/build/`（`examples/` 不入库）。**别为了让门禁变绿就把白名单当补丁清单**——白名单是人手工维护的判断题。

## 五、运行产物落位（硬规则）

- **两条 RSI 线路的运行产物只允许落两处，且都在仓库外**（与本仓库**同级**）：RSIAgent 线（`théâtre/` + `garage/`）落 `garage-result/`，harness2 线（`theatre-ii/` + `garage-ii/`）落 `garage-ii-result/`。**没有第三处**——尤其不再落 `theatre-usine-runs/`（旧名，已作废；既有产物已迁到 `garage-result/`）。
- **为什么必须在仓库外**：dsh 的 project root 判定是「最近的含 `.git` 的祖先，没有就用 cwd」。run root 落在本仓库里，`.dsh/skills` 会被判到**仓库根**，候选技能一个都扫不到——**跑得动、跑得对、跑的是错的**。这类故障不报错，只让分数静默塌到基线。
- **为什么两线分开放**：两线的读数必须能分开翻账（RSIAgent 改记忆、harness2 改 harness，判据与产物形态都不同）。混在一个根里，「这批数字是哪条线路的」就得靠猜。
- 落位由代码保证，不是靠自觉：`garage/run_usine.py` 的 `DEFAULT_RUNS_ROOT` 与 `garage-ii/preflight.py` 的 `DEFAULT_ROOT` 是唯一事实源（`garage-ii/run_usine_h2.py` 与 `compare_rsiagent.py` 都从后者取）。`GARAGE_II_RUNS_DIR` 可覆盖 harness2 线的根；**别把根指进仓库**（`preflight.check_run_root` 会 fail-closed）。
- 根 `.gitignore` 有兜底规则（`garage-result/`、`garage-ii-result/`、`endpoints.json`）：万一根被指进仓库，产物与真网关凭据都不会进索引。

## 六、配置唯一事实源

- **机器本地配置与凭据只允许出现在 `config/.env`**。两条 RSI 线路（引擎 + 适配层）与 usine 流水线都只读这里；样例见 `config/env.sample`，环境变量优先于文件。
- 旧配置位（`~/.minimax/config.yaml`、`~/.config/feuille/keys.env`、`~/.config/feuille/bgm-bed.env`、`~/.gemini_api_key`）自 2026-10-19 起退役，**不再被读取**——别往那儿写。
- 不归本文件管的外部产品自管配置：dsh 宿主（`~/.dsh/`）、`mmx` CLI 的登录态。

## 七、与全局同名能力的关系

- **BGM / 配乐**：本工作区一律走 `usine/skills/bgm-bed`——底床生成（Google Lyria，免费层实测线；MiniMax 音乐 API 官方 2026-08-20 日落、两区不收新用户，Suno/Udio 无官方 API，三条死线已删**别再接回**）+ 采样率/频段自检 + 实测反推 `gain`。全局 `music-generation` skill（`~/.agents/skills/`，**非本仓库资产**）的封装能力**已并入 bgm-bed**：它不量频段、不反推床位、没有验收判据，在本工程里已被取代，**不要再往它路由**。
- 同理：视频生成（Veo 等）一律按 usine/AGENTS.md 的 H3 铁律处理，与全局 `video-generation` 等 skill 的关系先查 usine/AGENTS.md 再动手。

## 八、规则层级

- 在 `usine/` 内工作、或把 feuille 资产用于任何内容项目时，**权威文本是 [usine/AGENTS.md](usine/AGENTS.md)**（22 条纪律 + 跨平台/pnpm 约定 + H3 铁律）；冲突时以它为准。本文件的排版条与产物落位条是工作区级新增，与它不冲突时同时生效。
- 在 `théâtre/` 内工作或操作 RSI 波次时，先读 [théâtre/PROVENANCE.md](théâtre/PROVENANCE.md) 与 [docs/self-evolution.md](docs/self-evolution.md) §2、§8.2（A 线机制与运行手册）；操作走 `garage/run_usine.py`（`--preflight` 先行，`--execute` 需 ack token `RUN-USINE-PHASE1-WAVES`；发布永不自动，真波次用户喊跑才跑）。
- 在 `theatre-ii/` 内工作或操作 harness 演化时，先读 [theatre-ii/PROVENANCE.md](theatre-ii/PROVENANCE.md) 与 [docs/self-evolution.md](docs/self-evolution.md) §3、§8.3（B 线机制与运行手册）；桥接与操作走 `garage-ii/run_usine_h2.py`（`--phase preflight` 先行，`--phase sweep` 需 ack token `RUN-USINE-H2-SWEEP`）。

## 九、RSI 读数纪律

**两条路径的关系**：RSIAgent（`théâtre/`+`garage/`）改的是**记忆**，harness2（`theatre-ii/`+`garage-ii/`）改的是 **harness 本身**。引擎层对照、产物对照与可跑的三臂对照协议**已合并进 [docs/self-evolution.md](docs/self-evolution.md)**（§5–§7）——**读数字之前先读那一节的「测不到什么」**；逐字实测归档留在 [garage-ii/BENCH-APPENDIX-2026-10.md](garage-ii/BENCH-APPENDIX-2026-10.md) §17，跨轮次方法论偏差在 [docs/self-evolution.md](docs/self-evolution.md) §12。

- **两条路径共同的硬约束**：基准 harness 必须与被改进对象**同源**（`garage-ii/build_base_harness.py` 派生，带漂移闸）；运行产物落**仓库外** run root，且两线分开放（见第五节）；判据失败是 `None` 不是零分；判据不进 harness 树。
- **演化结果先看「阶段回退」再看分数**：提案阶段失败时引擎会**退回基准树**继续跑，这一轮「看起来跑完了」，而最终被采纳的其实是**没改过的基准**——分数量的是基准，不是演化后的。`garage-ii` 的 sweep / judge 会把回退打出来并以**退出码 1** 结束。
- **说「演化带来了提升」之前，先有同树零分布**：同一棵 harness 树、同一道题、同一模型，重复 rollout 的分数会在一个宽度里动——2026-10-20 实测：**四棵臂树逐字相同**，分数 80%/100%/100%/100%。没有零分布就没有「提升」这个说法。`garage-ii/arms.py` + `--phase repeat` / `--phase compare` 是这把尺子（判据：Δ > 0 **且** 单侧精确置换检验 p ≤ 0.1；零分布宽度只报不判）。
- **说「泛化」之前，先有 train/eval 分侧读数**：2026-10-21 之前 `split` 参数收下却忽略——提案与判分同一批题，过拟合在读数上**结构上不可见**（train 涨、eval 跌，合并均值照样为正）。切分按产线层分层、固定种子（`garage-ii/task_split.py`），泛化读数走 `--split both` 两段式，判决按两侧显著性（`generalization.py`：train 涨 + eval 不涨 = `train_only`；eval 显著跌 = `harmful`，**train 涨多少都不抵**）。**两侧的记录与判据分开落盘，永不合并成一个均值**；缺 eval 侧 = `no_eval`，不许当「泛化没问题」读。A 线同族：记忆迁移要 `--project-budget ≥ 2` 才被观测过（`garage/transfer_check.py`），单项目波次的「held_out_generalization」只是标签。
- **基准环境不健全时，任何读数都量不到 harness**：2026-10-20 实测，基准工作区**漏装了技能自带的 `assets/` 与 `references/`、PATH 上也没有 `feuille`**——技能手册指向不存在的模板，智能体于是（正确地）判定「工具面之外没有验收口径」而停手。**凡是换过工作区/题面/判据之后，旧读数一律作废**；`garage-ii/preflight.py` 的「装出来的工作区里技能资源在位」是这条的闸。
- **自检只测内存里的对象，等于没测**：2026-10-20 实测，独立复查抓到三个**自查测不到**的缺陷——新字段没进 `to_dict`（于是 CLI 路径上的判定从来没生效）、compare 只比两臂的交集（少一格照样绿灯）、`rescore` 指错参数会**静默擦掉**一个臂还退出 0。**凡是「落盘 → 读回 → 判定」的逻辑，自检必须走那条真实路径**（落盘、CLI、错误参数三条都要有例）。
- **判据不许比被改进对象自己的文件更严**：判据的依据必须是**被改进对象自己的文件**（手册、系统提示、工具指引），不是「我觉得更合理」；而且**放宽往往更严**（基准抬高 ⇒ 演化要追的差距更小）。
- **量到「缺陷」之前先问一句：这是被改进对象的缺陷，还是我自己的判据/环境的缺陷**：2026-10-20 实测，基准臂 2 条 rollout 的产物被**后来的进程**擦掉（run 目录被重建），判据照直判成「没交付」——那量的是进程管理。**不是「智能体不行」的不要记成「智能体不行」**。
- **跑批不许在跑批机器的主人身上留外部副作用**：冻结手册教的 `google-chrome --headless --dump-dom` **没有**本仓自己的 mock-keychain 旗标（`usine/packages/core/src/platform.ts` 明写「headless 渲染绝不碰用户钥匙串」）。跑批必须**在跑批边界把副作用掐掉**（浏览器垫片：每次启动都包上 `--use-mock-keychain --password-store=basic`），但**不许顺手改掉被测行为**，也**不许替用户动钥匙串**（ACL、删项、`security list-keychains` 一律不碰）。
- **被杀/超时也要留下已经发生的事**：跑批的 rollout 可能跑十几分钟，事件流必须**边跑边落盘**（`garage-ii/dsh_run.mjs` append 写 `events.jsonl`）——「跑完才写」等于一次超时就零证据，而读数看着像「没做」。
- **跑批要压时间，先查线上协议，再谈请求参数**：同一个网关、同一个模型，Anthropic 风格 `/messages` 与 OpenAI 风格 `/chat/completions` 两条路的**推理块差一个量级**，实际耗时 56–116s vs 36–47s，而**耗时的 59% 砸在那个块上**。请求参数在 `/messages` 那一路**网关不稳定认**（`thinking.budget_tokens=4096` 直接 400）——**别拿一次快读数当效果，A/B 连打三次再下结论**。换协议后同题同树实测：一条海报 rollout 42.1 分钟 → **18.7 分钟**（步数反而更多，省的是每次往返的时延）。
- **一条臂的 n 次 rollout 要并行跑**：瓶颈在模型往返不在机器。2026-10-20 实测：n=4 串行 2 小时 48 分，并行后整条臂 = 最慢那条的实际耗时。`arms.py` 的 `run_arm` 带 `workers`（CLI `--arm-workers`）。**但并行买到的是总耗时不是单条成本**——网关总吞吐不随并发变大，**读臂的耗时要当「并发下的总耗时」读**。
- **判据引用纪律要给「文件 + 行号」，别写编号**：判据注释里写「红线第 5 条」，而 `guardrails.md` 的第 5 条其实是「验收诚实」，真正那条在 `systemprompt.md:14`——**编号会漂、也会张冠李戴**。引用纪律时把**文件名 + 行号 + 原文**一起写上。
- **判据要分清「量」与「产」，也要认「程序位」**：判据抓的是「**绕开工具面做出来的东西**」，所以① 浏览器**在不在程序位上**才算执行（引号感知的切段，`grep -n 'a\|b'` 里那个 `|` 不是管道）；② 带**产物开关**（`--screenshot` / `--print-to-pdf`）才算「产」，`--dump-dom` 是「量」。
- **产物判据覆盖不了「纪律有没有被改」，得另有一条树级轴**：演化提案在加技能时**顺手删掉了系统提示里的一条纪律**，产物照样交得出来、5 条产物判据照样不红。`garage-ii/tree_discipline.py` 量的是这个（树对树比对 `systemprompt.md` 与 `guardrails.md`，**不参与置换检验**，只作旁证）。
- **heredoc 正文不是命令**：`cat > wrap.sh <<'EOF'` 到 `EOF` 之间是**数据**，shell 从不执行它。凡是「把一段文本当命令读」的地方，先问它到底会不会被 shell 执行。修法：`bench_usine._strip_heredocs()` 在 `_shell_commands()` 收口生效。
- **清洗函数必须幂等，尤其当它在多个收口被调用**：剥 heredoc 的第一版把起头行原样保留，于是第二次调用找不到终止符、一路剥到结尾，把后面所有真命令吃掉。**幂等不是优点而是前提**；断言要直接比 `f(f(x)) == f(x)`。
- **「修判据」与「调尺子」的分界是理由，不是效果**：有独立于结论的语义依据（如 heredoc 不是命令）才算**修错**；无论往哪边定都有据的（如探针算不算产）必须留成**明写的未决项**。**一格判据的结论能在 p=0.05 与 p=1.00 之间摆动时，它的 Δ 无论正负都不进判决**——正确定位是「待重造」，不是「已量到」。
- 生成类命令默认不覆盖已有产物（显式 `--force` 才覆盖）；验收一律看退出码。
- **用词纪律：不许出现「墙钟」（wall clock），改用人类日常说法**：「实际耗时 / 总耗时 / 时间上限 / 时间预算 / 限时」。2026-10-21 已把仓库自有代码与文档里的该词全部改写（含 `garage/config/roles-usine/*.yaml` 的 prompt 正文）。**这条改动动了 prompt 正文，因此 2026-10-21 之前的 RSI 读数按「换过题面」处理，一律作废**；`théâtre/`（vendored fork，补丁逐字节不变）与 `theatre-ii/`（零补丁）里的上游原文不动。
