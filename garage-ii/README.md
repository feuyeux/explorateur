# garage-ii — harness2 × dsh × usine 的桥接层（常青）

> 上游引擎：[../theatre-ii/](../theatre-ii/)（harness2 vendored fork，commit `1cfe254`）
> 被改进对象：`../usine/`（feuille 多语种视频产线，宿主是 dsh / DeepSeek Harness）
> 对照的另一条路：`../théâtre/` + `../garage/`（RSIAgent 引擎那一侧）
> 对照协议与数字：[BENCHMARK.md](BENCHMARK.md)｜引擎层对照：[../theatre-ii/COMPARISON.md](../theatre-ii/COMPARISON.md)

---

## 一、这一层是干什么的

`../garage/` 把 RSIAgent 引擎接到 `usine` 上。本层把**另一个**引擎（harness2）接到同一个 `usine` 上，而且接的是**同一个 dsh 智能体**——于是两套引擎的头对头对照才有可能（同任务、同模型、同判据、同执行器）。

**层次边界**（不许糊）：

```
theatre-ii/          引擎：怎么改 harness（提案 / 探针 / 组合 / 选择 / 经验库）
   ↑ 接缝 A：Substrate（执行器 + 它的可编辑面）
garage-ii/           桥：dsh 那一面 + usine 那一格（任务、判据、运行手册）
   ↑ 被改进对象
usine/               产线：dsh 插件、十个技能、十八个工具面、红线纪律
```

**引擎层里没有一行 usine 或 dsh 专属代码**（见 `../theatre-ii/PROVENANCE.md` 的零补丁声明）。桥接的活全在本层。

---

## 二、怎么跑一次

### 0. 在哪台机器上跑

| 东西 | 在哪 | 备注 |
|---|---|---|
| **执行器** | **SDK 客户端**（`@deepseek-ai/dsh-sdk-client`，随插件走） | 真跑路径不是 `dsh --profile headless`，见 §四 |
| dsh CLI | PATH 上的 `dsh`（实测 0.1.5-rc.3） | **没有 `--json`**；只做软检查（真跑不用它） |
| dsh 源码仓 | `/Users/han/coding/deepseek-harness`（0.1.7-rc.2） | 备用 |
| harness2 引擎 | `../theatre-ii/`（随本仓版本化） | Python ≥3.12 |
| 插件产物 | `usine/packages/dsh-plugin/dist/index.mjs` | 缺了就是**零工具面**；`pnpm --filter @feuille/dsh-plugin build` |
| 改 harness 的模型 | 本层自建通道（`minimax_proposer.py`） | **不用** `HARNESS2_IMPROVER_MODEL` |
| 执行器模型 | MiniMax Code 运行时 → 本机中继 | token 只在中继的**内存**里，落盘 patch 里只有占位 key |

### 1. 自检（全绿才许进 2；不花钱）

```sh
python3 garage-ii/preflight.py --root ../garage-ii-result
```

五条硬检查，任何一条不过这一轮就不许开跑：

| 检查 | 不过意味着什么 |
|---|---|
| 基准 harness 在位且没漂移 | 拿过期基准去比，数字没有意义 |
| **执行器就位**（SDK 客户端可解析 + 插件产物已构建） | 缺一样就是**零工具面**——智能体对着空工具面发 shell，而流程一路绿 |
| node 在 PATH 上 | dsh 是 Node 宿主 |
| **run root 在仓库外** | dsh 的 project root 是「最近的含 .git 的祖先，没有就用 cwd」——仓库内的 run root 会让 `.dsh/skills` 判到**仓库根**，候选技能一个都扫不到。**不报错，只是分数静默塌到基线** |

PATH 上的 `dsh` CLI 只做**软**检查：真跑的路径是 SDK 客户端，CLI 已经不在执行路径上，为它拦下一轮是白花钱。

### 2. 开跑前看一眼要跑什么（不花钱，不要 ack）

```sh
python3 garage-ii/run_usine_h2.py --phase sweep --dry-run
```

### 3. 跑（真波次喊跑才跑）

```sh
# 一次 harness 演化：每个任务 R=4k 次 rollout + P=3k 次改 harness 的会话
python3 garage-ii/run_usine_h2.py --phase sweep --ack RUN-USINE-H2-SWEEP --k 1

# 只跑一个任务（先验证闭环时用；不花钱的部分照旧）
python3 garage-ii/run_usine_h2.py --phase sweep --ack RUN-USINE-H2-SWEEP --k 1 \
    --only-tasks routing-poster

# 机械判据（判据失败 = None，不是零分）
python3 garage-ii/run_usine_h2.py --phase judge

# 汇总
python3 garage-ii/run_usine_h2.py --phase report
```

**阶段回退必须说出口**：proposer 那一段失败时，引擎会退回基准树继续跑，于是这一轮「看起来跑完了」，而最终被采纳的其实是**没改过的基准**。所以 sweep / judge 都会把回退的阶段和原因打出来，并以**退出码 1** 结束——**分数量的是基准还是演化后的，看这一行就知道**。

**纪律与 `../garage/` 对齐**：自检先行；执行需 ack token；**发布永不自动**（本层不碰发布，`usine_publish` 默认不注册，工具面上根本没有）；真波次用户喊跑才跑。

### 3.1 测量：同树零分布、演化臂、并排读数（`arms.py`）

```sh
# 基准臂：同一棵树，每题 n 次 rollout → 这一棵树自己的零分布
python3 garage-ii/run_usine_h2.py --phase repeat --root ../garage-ii-result/exp-arms \
    --tree base --repeats 6 --tag base

# 抽出某次跑批**被采纳**的树（k≥2 时是引擎盲选的结果，不是固定 agg1）
python3 garage-ii/arms.py extract --sweep-root ../garage-ii-result/exp-k3 \
    --ns usine-dsh-dsh-agg3 --out ../garage-ii-result/exp-arms/trees/evo-k3

# 演化臂：同一棵采纳树，每题 n 次 rollout
python3 garage-ii/run_usine_h2.py --phase repeat --root ../garage-ii-result/exp-arms \
    --tree ../garage-ii-result/exp-arms/trees/evo-k3 --repeats 6 --tag evo-k3

# 并排读：精确置换检验 + 逐条判据失分率 + 要多大 n
python3 garage-ii/run_usine_h2.py --phase compare --root ../garage-ii-result/exp-arms \
    --base-arm base --evolved-arm evo-k3

# 只重跑「选择」这一步（不重跑任何 rollout）——k≥2 的盲选通道修好之后用
python3 garage-ii/run_usine_h2.py --phase reselect --root ../garage-ii-result/exp-k3 --k 3
```

**为什么要有这些**：单次得分说明不了任何事——同一棵树上跑 3 次，方差就能盖过任何效应。**先有同树零分布，才谈「演化变好了」**。细节见 [BENCHMARK.md](BENCHMARK.md) 第 10–13 节。

### 4. 三臂对照（harness2 vs RSIAgent 记忆）

```sh
python3 garage-ii/compare_rsiagent.py --dry-run
python3 garage-ii/compare_rsiagent.py --root ../garage-ii-result --ack RUN-USINE-H2-COMPARE
python3 garage-ii/compare_rsiagent.py --root ../garage-ii-result \
    --memory /path/to/frozen/memory --ack RUN-USINE-H2-COMPARE
```

臂的含义、判据的失效方向、报告怎么读：[BENCHMARK.md](BENCHMARK.md)。

**rsi 臂今天仍然跑不出有意义的一栏**：`garage/` 侧**已经产出过**产物（三条合并提交 + `memory_changed: true`），但那份记忆树只在仓库外的 run root 里，没入库、也没导出成可挂载的语料。要补这一栏，下一次 DRS 用 `--memory-seed <dir>` 把记忆树导出来，再 `--memory <dir>` 喂进来。

两条路径**已经产出的东西**逐条对照（含墙钟、含各自踩的坑）：[EVOLUTION-PATHS.md](EVOLUTION-PATHS.md)。

---

## 三、文件地图

| 文件 | 职责 |
|---|---|
| `dsh_substrate.py` | dsh 那一面：可编辑面（`DSH_SURFACE`）、装配（c1..c8 → dsh 原生文件）、轨迹渲染（dsh 事件流 → 共享文法）、dsh 命令解析与能力探测 |
| `usine_adapter.py` | usine 那一格：任务、执行（起 dsh）、读回、dsh 侧树不变量、机械判据的投影 |
| `bench_usine.py` | 任务集（7 个）、提示剖面、机械判据的执行 |
| `build_base_harness.py` | 从真实 dsh 插件**派生**基准 harness 树，带漂移闸（工具表 + 纪律文本 + **技能资源引用**） |
| `harness_base/` | 派生出来的基准 harness 树（c1 系统提示 / c2 护栏 / c3 记忆 / c4 工具指引 / c6 十份技能） |
| `preflight.py` | 自检（七条硬检查 + 软警告） |
| `run_usine_h2.py` | 运行手册入口：preflight / sweep / repeat / compare / reselect / judge / report |
| `arms.py` | 测量层：臂（同树零分布）、配对比较（精确置换检验）、重判、失败语料、树的抽取 |
| `tree_discipline.py` | 树级**纪律留存**检查：比对候选树与基准树的 `systemprompt.md` 工作方式条目 + `guardrails.md` 红线（丢失 / 改写 / 新增）。**不参与置换检验**，只作旁证——产物判据看不见「纪律被删了」 |
| `compare_rsiagent.py` | 三臂对照驱动与报告 |
| `EVOLUTION-PATHS.md` | **两条路径的产物对照**：RSIAgent（改记忆，产物是 git 提交）vs harness2（改 harness，产物是一棵树），含各自墙钟与「今天不能说什么」 |
| `smoke_dsh_bridge.py` | 离线自检（**不调任何模型**，12 段） |
| `BENCHMARK.md` | 对照协议：任务、判据、公平性保障、读数纪律 |
| `dsh_run.mjs` | 执行器桥：SDK 客户端跑一次 rollout，把事件流 / 终局答案 / 装配清单落盘 |
| `dsh_provider.py` | provider 装配：凭据从哪来（运行时凭据店，**只在内存**）、patch 怎么生成、中继句柄 |
| `minimax_relay.mjs` | 本机中继：摘掉 `x-api-key`、换上 `Authorization`；遇 401 重读 token 重试 |
| `llm_relay.mjs` | 统一凭据中继：按 slug 从 `config/.env` 解析端点对（最长前缀优先、组级兜底、fail-closed），`/v1/messages` → 上游 `/messages`；**凭据只在内存、不打印** |
| `browser_shim.py` | 跑批专用浏览器垫片：每次启动都包上 `--use-mock-keychain --password-store=basic`（headless 渲染不碰用户钥匙串），`$CHROME_BIN` 与 PATH 裸名都指向它；**工具面的浏览器不变、被测行为不变、用户钥匙串不碰** |
| `minimax_proposer.py` | 自建 proposer 通道：直连模型改 harness 树（内联证据 + `<<<FILE … >>>FILE` 协议） |
| `dsh_surface.py` | 给引擎**注册** dsh 的提示面（运行时扩展，上游文件零改动） |

---

## 四、dsh 那一面的形状（本层唯一有实质逻辑的地方）

harness2 的可编辑面由 `SurfaceSpec` 声明。上游两个 substrate（opencode / codex）与 dsh 的对应关系：

| harness2 组件 | dsh 原生落点 | 状态 |
|---|---|---|
| c1 system prompt | `AGENTS.md`（agent-instructions 读同名候选） | 原生 |
| c2 guardrails | `AGENTS.md` 的一节 | 拼进去（dsh 的 guard 是**代码插件**，不是文本） |
| c3 memory | `AGENTS.md` 的一节 | 拼进去（dsh 默认没有工作区记忆文件） |
| c4 tool guidance | `AGENTS.md` 的一节 | 拼进去（dsh 的工具描述在插件代码里） |
| c5 subagents | dsh 的子智能体是**插件 provider**（in-process / ACP / Codex） | **v1 不做** |
| c6 skills | `<projectRoot>/.dsh/skills/<name>/SKILL.md` | 原生 |
| c7 scripts | 工作区里的确定性帮手（`harness_scripts/`） | 原生 |
| c8 plugins | cordis 插件，装在 **profile** 里 | **v1 不做** |

**c5 / c8 为什么不做**：一个装在 `<workspace>/plugin/foo.ts` 的文件既不会被 dsh 加载，也无法在本轮里被 proposer 改完就生效——那是个**假接口**。宁可标「不支持」，也不给一个看起来能用、实际不生效的面。

**拼装的代价**：c1..c4 在方法层是四个独立可编辑组件，在安装层才合成一个 `AGENTS.md`。一个文件坏了，全盘坏。所以 `compose_agents_md` 保序、给每节留锚点，**空节留占位**（模型知道这里本该有护栏，比护栏变成空白更危险）。

### 装配：技能**资源**必须一起装，CLI 必须在 PATH 上

2026-10-20 踩到本层最贵的一个坑：**基准工作区本身是坏的**，于是那一格量的是「工作区完整与否」，不是 harness 的好坏。

两处根因：

1. **技能只装了 `SKILL.md`**。真实插件注册技能的写法是 `customSkillDirs: [resolve(usineRoot(), 'skills')]`——**整个 `usine/skills/` 目录连同 `assets/` 与 `references/` 一起注册**。只搬手册，等于把真实环境删掉一半：手册里「copy `assets/template/poster_src.html`」这一步不可执行，智能体于是（**正确地**）判定「工具面之外没有验收口径」而停手。
2. **PATH 上没有 `feuille`**。工作区是仓库外的裸目录，而真实产线里它在 PATH 上（pnpm workspace）。智能体 `which feuille` 落空，就推断「工具面没有包」——哪怕 `usine_poster` **确实注册在工具面上**。

修法：

- `dsh_substrate._install_skill_assets()` 把真实资产源 `usine/skills/` 装进 `.dsh/skills/`（以及工作区里的 `skills/`），SKILL.md 由 harness 树覆盖——**资产是源，手册是被改进对象**（树里那份可能已被演化改过）。
  **为什么资产不进 harness 树**：树是**可编辑面**，引擎 `core/tree.py` 按正则定义只认 `SKILL.md` 与 `scripts/`；把 347KB 资产塞进去会撑爆每一次提案提示。
- `usine_adapter._feuille_shim_dir()` 造一个只含 `feuille` 的小 bin 目录（垫片是一行 `exec node <真实 cli> "$@"`——**不复制、不改写 CLI**）。
- 两条闸：`build_base_harness.py --check` 的 `check_skill_assets()`（手册引用的每个资源路径都必须在盘上）与 `preflight.py` 的 `check_workspace_assets()`（**装配一次**——只装配、不跑模型、不花钱——逐个核对资源真落进了工作区）。源在不在与装得对不对，是两回事。

完整记录见 [BENCHMARK.md](BENCHMARK.md) 第 12 节。

### 执行器：SDK 客户端，不是 `dsh --profile headless`

实测下来 PATH 上的 dsh（0.1.5-rc.3）当执行器有两条硬伤：

1. **工具面是空的**——headless 剖面只装 `dsh-base` + `dsh-headless`，**没有** feuille-usine 插件。智能体会对着零工具面发 shell（2026-10-18 真宿主首测实录），而流程一路绿。
2. **没有 `--json`**——事件流是后加的，stdout 里什么都没有，轨迹是空的。

   所以本层的执行器是 **SDK 客户端**（`dsh_run.mjs` → `@deepseek-ai/dsh-sdk-client`，版本随插件走）：

- 插件面用 `patches:` 显式声明（`dsh_provider.make_patch` 生成的 patch 覆盖），工具面逐字对得上 `tools.ts`（17 个）；
- 轨迹来自 SDK 的 **`session.event` 通知**（规范 SessionEvent 流：`tool/call` / `tool/result` / `assistant/message`），**所有版本都有**，比 `--json` 投影更全；
- 审批策略固定 `never`（本层任何一次跑批都不许烧额度）。

### provider：MiniMax 运行时 + 本机中继

PATH 上的 dsh 默认走 fuyao 网关，而那把 key **余额已尽**（实测 `QUOTA: Insufficient Balance`）；`codex` 登出、`claude` 未登录。MiniMax Code 运行时的 Anthropic 兼容端点是这台机器上**当下唯一活着**的模型通路。

它不能直连，三个实测结论（`minimax_relay.mjs` 的注释里有完整版）：

- 端点**只认** `Authorization: Bearer`，只发 `x-api-key` → 401；
- pi-ai 的 anthropic 适配器**只**在 key 形如 `sk-ant-oat*` 时走 Bearer，否则一律当 apiKey 发成 `x-api-key`；
- 两样都带能过鉴权，但平台**按 `x-api-key` 的有无选路** → 503 `direct_route_not_configured`。

  **解法 = 本机中继摘掉 `x-api-key`、换上 `Authorization`**。顺带解决凭据纪律：token 只活在中继进程的**内存**里，落盘的 patch 里只有一个本地 URL 与一个占位 key——凭据不进磁盘。

### 引擎的提示面：dsh 要有自己的一条

harness2 的 `core/prompts.py` 有一张按 **surface 名**索引的提示表（`_SURFACE_TEXTS`），只认 `codex` 与 `opencode`。dsh 不是这两个之一——不注册就直接抛 `ValueError: no prompt surface for 'dsh'`，整个 sweep 一个任务都跑不动。

`dsh_surface.py` 在**运行时**注册一条 dsh 自己的条目（**上游文件零改动**）。它必须写 dsh 真实的可编辑面：c5/c8 在 dsh 上根本不存在、插件那十份技能被冻结、always-on 四个文件拼成一个 `AGENTS.md`、上限 24000 字。拿 opencode 那份顶替，proposer 会去提 `plugin/<name>.ts` 和 `sub_agents/`——装不上去，整个提案被丢掉。

### proposer 通道：本层自建

上游两个通道都不通：`opencode` 要 vendor 半个第三方仓的源码检出；`claude_cli` 强制走 Vertex（本机没有 ADC）。所以 `minimax_proposer.py` 自建一条直连通道：

- 上游 proposer 是**能读文件的 agent**，mission 是「证据在磁盘上 `context/`，去读」的**指针**；本通道没有文件工具，所以把证据**内联**进提示（`task.md` / harness 树 / rollout / 候选池 / 经验库 / 既往决策）；
- 编辑契约：**omitted-is-inherited**——只回报自己改了哪些文件，格式是 `<<<FILE … >>>FILE`；
- **「不用改」是正当答案**：证据不支持任何改动时，模型回 `KEEP_BASE` 且不回报任何文件，
  通道**成功**返回并交回**没改过**的树（引擎记成 `kept_base`）。这不是「白跑」——上游的 proposer 改的就是磁盘上的文件，不改 = 交回原树。**少了这一条，模型在饱和任务上会去编一个不存在的失败**（2026-10-20 实测：它凭空描述了一次轨迹里没发生过的工具调用）；
- **「改不动」也是正当答案**：想改的东西不在可编辑面（冻结的技能、插件自带的东西）时，
  回 `KEEP_BASE OUT_OF_SCOPE` + 说明为什么改不动，同样交回原树、同样不作废。**为什么单开一个标记**：读数时要分得开「没有证据」（这一格饱和）和「改不动」（这一格碰到的障碍在 harness 之外）。混成一个词，报告里就分不出「引擎保守」和「引擎够不着」；
- **提示面告诉它「做不成」是正确行为**：`BenchPrompts.yardstick` 里写明**有些活天生就是做不成的**
  （工具按设计没挂载、流程要求人工审批、前置材料没给全），那时说清不可达、给替代路径、如实报状态**就是做对了**。这是**产线纪律里本来就有的领域事实**（`guardrails.md` /`tool_guidance.md` 里逐条写着），不是判据——不含任何 measurement 词汇，过得了引擎`BenchPrompts.__post_init__` 的硬校验。少了这一条，proposer 会把「智能体守住了红线」读成「智能体失败了」，然后去改那条红线（2026-10-20 实测：它把红线改成了「磁盘上的 skill 是可执行入口，应该真去发抖音/小红书」）；
- 引擎从 `reply.text` 里用 `<notes>…</notes>` 抠决策说明，所以 `text` 必须带这个标记；
- 每次会话的 mission / 回复 / 耗时落成审计文件（`adapt/_audit/<ns>/`）。

  **本通道没有文件工具**这件事必须写进给 proposer 的提示里——上游那句「Open the files, change them in place with your normal tools」在本通道是假的，会让模型去找一个不存在的工具。`dsh_surface.py` 的 "HOW TO MAKE A CHANGE" 一节改成了「报告你改了哪些文件」。

---

## 五、红线（本层对 wave、对测试、对验收同样成立）

1. **基准 harness 必须与被改进对象同源**。`harness_base/` 是派生的（`build_base_harness.py`），漂移闸双向核对 `tools.ts` 的工具表、逐字核对 `discipline.ts` 的纪律段。漂了就红，不许悄悄过期。
2. **判据不许进 harness 树**。harness2 侧有机械闸（`assert_tree_has_no_grader_verdicts`），本层不重复实现第二套。
3. **判据失败不是零分**。`adapter.score` 失败返回 `None`；harness2 的 `Scored.graded` 说的是「判成了」，不是「跑得好」。`None` 从分母剔除。
4. **同名技能不许被改写**。dsh 的技能注册表按 rank 合并，项目根（rank 100）会**静默盖掉**插件的 custom 根（rank 300）——一份被改写的同名技能会让「harness 变好」和「技能被换掉」分不开。所以基准树里那十份技能必须与插件里的**逐字相同**。
5. **run root 在仓库外**，且与 RSIAgent 线的 `garage-result` 分开落：本线默认 `../garage-ii-result`（与本仓库**同级**），实验根用其下的 `exp-*` 子目录（每个根有各自的 sweep 锁）。见 §二.1 那条检查。
6. **每个 rollout 一份独立工作区**。装配目录共用，工作区必须每次 rollout 独占，否则并行 rollout 会互相改对方的 `AGENTS.md`。
7. **真波次要 ack**。sweep 与对照都锁在 ack token 后面；`--dry-run` 不花钱也不要 ack。
8. **不改 `usine/` 的行为**。本层只读 `usine/` 的插件与技能资产；`usine` 是被改进对象，不在本层的修改范围内。
9. **一个 run root 同时只许一个 sweep**。两个 sweep 共用一个 root 会**互相覆盖**产物，而且**不报错**——分数有、报告有、退出码 0，数字是错的。run root 上有锁（`adapt/.sweep.lock`），第二个 sweep 会被挡下。
10. **阶段回退要说出口**。提案阶段失败时引擎会退回基准树继续跑，这一轮「看起来跑完了」，而最终被采纳的其实是**没改过的基准**。sweep / judge 都会把回退打出来并以**退出码 1** 结束——**分数量的是基准还是演化后的，看这一行就知道**。
11. **token 只在中继的内存里**。落盘的 patch 里只有环境变量名与占位 key；token 不进仓库、不进 run 目录、不进日志。
12. **臂间比较必须先有同树零分布**。同一棵 harness 树、同一道题、同一模型，重复 rollout 的分数会在一个宽度里动（2026-10-20 实测：四棵臂树逐字相同，分数 80%/100%/100%/100%）。**没有零分布就没有「提升」这个说法**——`arms.py` + `--phase repeat/compare` 就是这把尺子（详见 [BENCHMARK.md §10](BENCHMARK.md)）。
13. **基准环境必须与真实产线一样健全**。2026-10-20 实测：基准工作区漏装了技能自带的 `assets/` 与 `references/`、PATH 上也没有 `feuille`，于是智能体（正确地）判定「工具面之外没有验收口径」而停手——那一格量的是**工作区完整与否**。闸在 `preflight.py` 的 `check_workspace_assets()` 与 `build_base_harness.py --check` 的 `check_skill_assets()`。
14. **异常必须留下证据，链必须在失败处停下**。2026-10-20 实测两件事：① 改错一行代码，adapter 的异常被引擎收成一句「no base rollout produced anything」，run 目录里**连 traceback 都没有**——现在 `_launch_one` 一定写 `error.txt`；② 跑批的脚本链在第一步失败后**继续往下跑**，最后给出一份「演化什么都没做」的正常报告——链必须在任一步退出非零时停下。
15. **自检必须走真实路径**。只测内存里的对象，等于没测：2026-10-20 实测，一个新字段没进 `to_dict`，于是**零格规则在 CLI 路径上从来没生效过**。落盘 → 读回 → 判定、CLI 路径、错误参数路径，三条都要有例。
16. **判据不许比 harness 自己的文件更严**。2026-10-20 实测两处误伤：① `tool_called:usine_poster` 只认 MCP 工具入口，而技能手册的 Requirements 写着「进程内直跑 `feuille poster <子命令>`」——基准臂一半走 MCP、一半走 CLI，**用的都是手册钦定的那套子命令**，判据却按入口方式把它们劈成 0.8 和 0.6；② `no_tool_face_bypass` 把「定位浏览器二进制」这种准备动作也算绕行。收紧与放宽都**必须拿 harness 自己的文件作依据**（`SKILL.md` / `systemprompt.md` / `tool_guidance.md`），不是「我觉得更合理」——而且**放宽的方向往往更严**：把基准抬高，演化要追的差距更小。
17. **「没测到」不许说成「零分」「全过」「更差」**。2026-10-20 实测：演化臂 6 条全 `score=None`，逐判据表却显示「演化臂失分 0.0%、Δ=−100、← 变了」——`None` 在分布层面守住了，一到渲染层就被 `get(name, 0.0)` 变回零分。**空样本格单列**（「比不了」），失分率用 `None` 承载「未知」，渲染打「—」。
18. **证据不许被后来的进程改写而不留痕**。2026-10-20 实测：同一个 `run_id` 被重跑一次时，旧那次留下的 `exit_code` / `final.txt` 还在，工作区却被重建成空的——判据拿「最终回答说交付了」和「工作区里没有产物」对着看，量出来的是**进程管理**不是智能体（基准臂 2 条因此被记成 0.6，方向还是**对演化有利**的假阳性）。三处修法：`_launch_one` **整目录清盘**、`rollout_integrity()` 认「任务文件必须写在 rollout 结束之前」、**作废 ≠ 工具故障**（作废的 rollout 从 n 里剔出去并记理由；工具故障仍然报错退出、不写回）。
19. **提案者也要看得见纪律**。2026-10-20 实测：海报格 5/5 条轨迹都手搓了浏览器（always-on 明文写着「不要用 shell 绕开工具」），九个提案会话里六个 `KEEP_BASE`——因为引擎的两个维度分工是「DOM 管领域知识 / INV 管工序」，**没人被问「这条纪律守住了吗」**。提案提示里现在有一段**纪律自查**：清单是 harness 自己的 always-on 文字（冻结技能里的句子不进清单），要求模型拿轨迹里**实际执行的动作**去核，并把结论写进 notes。**判据名、评分、grader 一律不许进那段文字**（评测隔离）。
20. **跑批不许在跑批机器的主人身上留外部副作用**。2026-10-20 实测：冻结手册第 6 步教的 `google-chrome --headless --dump-dom` **没有**本仓自己的 mock-keychain 旗标（`usine/packages/core/src/platform.ts` 明写「headless 渲染绝不碰用户钥匙串」），于是每轮 rollout 都多一次「摸用户钥匙串」的机会（**用户当时报的那个弹窗，取证结论是本助手运行时自带的 puppeteer CfT 拉起来的，不是跑批——但跑批这个隐患是真的**）。**隔离要掐副作用，但不许顺手改掉被测行为**——垫片（`garage-ii/browser_shim.py`）把每次浏览器启动包上 `--use-mock-keychain --password-store=basic`，`$CHROME_BIN` 与 PATH 裸名都指向它；**工具面用的浏览器不许变**（垫片照抄 `platform.BROWSERS` 的顺序解析出同一个二进制，换浏览器就是换像素基线），**智能体照样手搓、照样绕开工具面**（判据照样命中），**用户的钥匙串一律不碰**（不改 ACL、不删项、不动 `security list-keychains`）。机检在 `browser_shim.selfcheck()`：垫片起一次 headless 浏览器 + 全新 profile，断言 **`SecurityAgent` 没被拉起**（它出现 = 弹窗出现）。踩过的死路也留档：**沙箱 HOME 不解药**（弹窗照旧 + 退出码 2），**sandbox-exec 拦不住**。
21. **被杀/超时也要留下已经发生的事**。2026-10-20 实测：一次 900s 超时的 smoke 只剩 `exit_code=124`，**连轨迹都没有**——`dsh_run.mjs` 原来跑完才写 `events.jsonl`。现在**边跑边 append**。这与第 18 条同源：**证据在关键处消失，而读数看着像「没做」**。

    ---

## 六、怎么校验本层

```sh
python3 garage-ii/smoke_dsh_bridge.py     # 离线自检，不调任何模型
python3 garage-ii/build_base_harness.py --check   # 基准树漂移闸
python3 garage-ii/preflight.py            # 开跑前自检
python3 garage-ii/browser_shim.py         # 浏览器垫片自检（起一次 headless + 全新 profile，断言不拉起 SecurityAgent）
```

`smoke_dsh_bridge.py` 走一遍桥接的每一段接缝（12 段）：基准树过校验 → 装配出 dsh 原生形状 → AGENTS.md 四节保序 → dsh 事件流渲染成共享文法 → 机械判据在造出来的轨迹上判对判错 → run root 闸拦下仓库内路径 → 端到端（**假执行器**，装配 → 会话 → 事件落盘 → 轨迹 → 判据）→ 引擎的提示面认得 dsh → 「不用改」（KEEP_BASE）与「改不动」（KEEP_BASE OUT_OF_SCOPE）都是正当答案 → 「做不成」是领域事实、不是失败（yardstick 带着这条）→ 「不要建议用户开启」这条针不误伤（拿 2 份真违规 + 7 份合规样本守着）→ 臂：同树零分布 + 配对比较（假执行器）。

**它不调模型**，所以可以随时跑，也应该随时跑。

**「跑一次」之前的三件事**（顺序不能反）：

1. `build_base_harness.py --check` 绿——基准漂了，数字没有意义；
2. `smoke_dsh_bridge.py` 绿——桥接的每一段接缝都通；
3. `run_usine_h2.py --phase sweep --dry-run` 看一眼要跑什么（**不花钱、不要 ack**）。

   ---

## 七、文档地图

| 想知道的 | 去哪 |
|---|---|
| harness2 的机制（c1..c8、Propose–Probe–Compose、经验库、选择、评测隔离） | `../theatre-ii/ARCHITECTURE.md` |
| harness2 与 RSIAgent 的引擎层对照 | `../theatre-ii/COMPARISON.md` |
| harness2 的来源、vendor 范围、零补丁声明、能力缺口 | `../theatre-ii/PROVENANCE.md` |
| 对照协议、任务集、判据、公平性保障、读数纪律 | [BENCHMARK.md](BENCHMARK.md) |
| **第一批真跑实测到了什么**（管线通 / 基准饱和 / 判据噪声 / 方差盖过效应 / proposer 会编造失败 / 阶段回退会骗人） | [BENCHMARK.md §9 实测记录](BENCHMARK.md) |
| **怎么量「有没有用」**（同树零分布、配对比较、精确置换检验、失败语料） | [BENCHMARK.md §10 怎么量](BENCHMARK.md) |
| **基准臂的零分布长什么样**（各格的方差；要多大 n 才测得出来） | [BENCHMARK.md §11 零分布](BENCHMARK.md) |
| **基准工作区曾经是坏的**（技能资源没装、CLI 不在 PATH；旧读数为何作废） | [BENCHMARK.md §12 工作区缺陷](BENCHMARK.md) |
| **修好环境之后重跑的判决**（零格、判据第三次收紧、独立复查抓到的缺陷） | [BENCHMARK.md §13 v2/v3 重跑](BENCHMARK.md) |
| dsh 侧的事实（事件 schema、技能发现与 rank、AGENTS.md 发现） | <https://github.com/deepseek-ai/deepseek-harness> |
| RSIAgent 那一侧的现状与欠账 | `../plan/rsi-gap-to-paper-2026-10.md`、`../plan/rsiagent-memory.md` |
| `usine` 产线的红线与工具面 | `../usine/packages/dsh-plugin/src/discipline.ts`、`tools.ts` |
