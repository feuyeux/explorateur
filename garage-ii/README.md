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
python3 garage-ii/preflight.py --root ~/.cache/usine-h2
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

### 4. 三臂对照（harness2 vs RSIAgent 记忆）

```sh
python3 garage-ii/compare_rsiagent.py --dry-run
python3 garage-ii/compare_rsiagent.py --root ~/.cache/usine-h2 --ack RUN-USINE-H2-COMPARE
python3 garage-ii/compare_rsiagent.py --root ~/.cache/usine-h2 \
    --memory /path/to/frozen/memory --ack RUN-USINE-H2-COMPARE
```

臂的含义、判据的失效方向、报告怎么读：[BENCHMARK.md](BENCHMARK.md)。

---

## 三、文件地图

| 文件 | 职责 |
|---|---|
| `dsh_substrate.py` | dsh 那一面：可编辑面（`DSH_SURFACE`）、装配（c1..c8 → dsh 原生文件）、轨迹渲染（dsh 事件流 → 共享文法）、dsh 命令解析与能力探测 |
| `usine_adapter.py` | usine 那一格：任务、执行（起 dsh）、读回、dsh 侧树不变量、机械判据的投影 |
| `bench_usine.py` | 任务集（6 个）、提示剖面、机械判据的执行 |
| `build_base_harness.py` | 从真实 dsh 插件**派生**基准 harness 树，带漂移闸 |
| `harness_base/` | 派生出来的基准 harness 树（c1 系统提示 / c2 护栏 / c3 记忆 / c4 工具指引 / c6 十份技能） |
| `preflight.py` | 自检（五条硬检查 + 软警告） |
| `run_usine_h2.py` | 运行手册入口：preflight / sweep / judge / report |
| `compare_rsiagent.py` | 三臂对照驱动与报告 |
| `smoke_dsh_bridge.py` | 离线自检（**不调任何模型**，8 段） |
| `BENCHMARK.md` | 对照协议：任务、判据、公平性保障、读数纪律 |
| `dsh_run.mjs` | 执行器桥：SDK 客户端跑一次 rollout，把事件流 / 终局答案 / 装配清单落盘 |
| `dsh_provider.py` | provider 装配：凭据从哪来（运行时凭据店，**只在内存**）、patch 怎么生成、中继句柄 |
| `minimax_relay.mjs` | 本机中继：摘掉 `x-api-key`、换上 `Authorization`；遇 401 重读 token 重试 |
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
- 引擎从 `reply.text` 里用 `<notes>…</notes>` 抠决策说明，所以 `text` 必须带这个标记；
- 每次会话的 mission / 回复 / 耗时落成审计文件（`adapt/_audit/<ns>/`）。

**本通道没有文件工具**这件事必须写进给 proposer 的提示里——上游那句「Open the files, change them in place with your normal tools」在本通道是假的，会让模型去找一个不存在的工具。`dsh_surface.py` 的 "HOW TO MAKE A CHANGE" 一节改成了「报告你改了哪些文件」。

---

## 五、红线（本层对 wave、对测试、对验收同样成立）

1. **基准 harness 必须与被改进对象同源**。`harness_base/` 是派生的（`build_base_harness.py`），漂移闸双向核对 `tools.ts` 的工具表、逐字核对 `discipline.ts` 的纪律段。漂了就红，不许悄悄过期。
2. **判据不许进 harness 树**。harness2 侧有机械闸（`assert_tree_has_no_grader_verdicts`），本层不重复实现第二套。
3. **判据失败不是零分**。`adapter.score` 失败返回 `None`；harness2 的 `Scored.graded` 说的是「判成了」，不是「跑得好」。`None` 从分母剔除。
4. **同名技能不许被改写**。dsh 的技能注册表按 rank 合并，项目根（rank 100）会**静默盖掉**插件的 custom 根（rank 300）——一份被改写的同名技能会让「harness 变好」和「技能被换掉」分不开。所以基准树里那十份技能必须与插件里的**逐字相同**。
5. **run root 在仓库外**。见 §二.1 那条检查。
6. **每个 rollout 一份独立工作区**。装配目录共用，工作区必须每次 rollout 独占，否则并行 rollout 会互相改对方的 `AGENTS.md`。
7. **真波次要 ack**。sweep 与对照都锁在 ack token 后面；`--dry-run` 不花钱也不要 ack。
8. **不改 `usine/` 的行为**。本层只读 `usine/` 的插件与技能资产；`usine` 是被改进对象，不在本层的修改范围内。
9. **一个 run root 同时只许一个 sweep**。两个 sweep 共用一个 root 会**互相覆盖**产物，而且**不报错**——分数有、报告有、退出码 0，数字是错的。run root 上有锁（`adapt/.sweep.lock`），第二个 sweep 会被挡下。
10. **阶段回退要说出口**。提案阶段失败时引擎会退回基准树继续跑，这一轮「看起来跑完了」，而最终被采纳的其实是**没改过的基准**。sweep / judge 都会把回退打出来并以**退出码 1** 结束——**分数量的是基准还是演化后的，看这一行就知道**。
11. **token 只在中继的内存里**。落盘的 patch 里只有环境变量名与占位 key；token 不进仓库、不进 run 目录、不进日志。

---

## 六、怎么校验本层

```sh
python3 garage-ii/smoke_dsh_bridge.py     # 离线自检，不调任何模型
python3 garage-ii/build_base_harness.py --check   # 基准树漂移闸
python3 garage-ii/preflight.py            # 开跑前自检
```

`smoke_dsh_bridge.py` 走一遍桥接的每一段接缝：基准树过校验 → 装配出 dsh 原生形状 → AGENTS.md 四节保序 → dsh 事件流渲染成共享文法 → 机械判据在造出来的轨迹上判对判错 → run root 闸拦下仓库内路径。

**它不调模型**，所以可以随时跑，也应该随时跑。

---

## 七、文档地图

| 想知道的 | 去哪 |
|---|---|
| harness2 的机制（c1..c8、Propose–Probe–Compose、经验库、选择、评测隔离） | `../theatre-ii/ARCHITECTURE.md` |
| harness2 与 RSIAgent 的引擎层对照 | `../theatre-ii/COMPARISON.md` |
| harness2 的来源、vendor 范围、零补丁声明、能力缺口 | `../theatre-ii/PROVENANCE.md` |
| 对照协议、任务集、判据、公平性保障、读数纪律 | [BENCHMARK.md](BENCHMARK.md) |
| dsh 侧的事实（事件 schema、技能发现与 rank、AGENTS.md 发现） | <https://github.com/deepseek-ai/deepseek-harness> |
| RSIAgent 那一侧的现状与欠账 | `../plan/rsi-gap-to-paper-2026-10.md`、`../plan/rsiagent-memory.md` |
| `usine` 产线的红线与工具面 | `../usine/packages/dsh-plugin/src/discipline.ts`、`tools.ts` |
