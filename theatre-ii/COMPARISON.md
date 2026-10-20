# COMPARISON — harness2（theatre-ii）对 RSIAgent（théâtre）

> 目的：把两套引擎放在**同一张桌子**上，回答一个问题——**对 `usine` 这个基于 dsh 的智能体，哪一种自我进化更合适？**
> 本文是引擎层的对照（机制、沉淀物、通道）。可跑的对照协议与数字在 [`../garage-ii/BENCHMARK.md`](../garage-ii/BENCHMARK.md)；实现它的脚本是 `../garage-ii/compare_rsiagent.py`。

## 0. 一句话结论

**两套引擎改的不是同一个东西。** RSIAgent 改**记忆**（一份 Markdown 语料库），harness2 改**harness**（模型周围的整个系统：系统提示、护栏、工具指引、技能、子智能体、脚本、插件）。

对 `usine` 而言，差别不是风格差别，是**能力差别**：

- RSIAgent 的沉淀物**进不了**智能体的系统提示、技能路由、工具面——它只能作为一份「要读的文件」存在；
- harness2 的沉淀物**就是**智能体每一步都读的那份东西。

而且有一个更结构性的差别：**usine 没有官方评测器**（`garage/config/roles-usine/target-usine.yaml:8` 记明 unavailable，`garage/run_usine.py:1656` 钉 `official_evaluator_calls: 0`）。RSIAgent 的架构**依赖**一个能给出地面的 Verifier；harness2 的方法**明确不需要地面**（论文原话：*without ground-truth feedback*，对比靠同一任务上的行为差异）。**在「没有地面」的目标上，后者是直接可用的，前者要先补一整套 Verifier 替身**——`garage/verifier_adapter.py`（41 KB）就是那套替身。

## 1. 机制对照

| 维度 | RSIAgent（`../théâtre/`） | harness2（`./`） |
|---|---|---|
| 角色 | Curriculum / Actor / Verifier 三角色 | proposer / probe / composer + selector + improver（无固定角色数） |
| 探索结构 | BRS（广度：并行 wave，8 项目预算 / 4 并发）→ DRS（深度：串行，`curriculum_review` 停止策略） | 任务级递归（Propose–Probe–Compose）→ harnessing 级递归（经验库 R） |
| 两种规模方式 | BRS 宽、DRS 深（**两种不同的阶段**） | parallel（宽：2k 候选 + k 独立组合）/ sequential（深：k 轮嵌套）——**同一机制的两种跑法** |
| 反馈信号 | Verifier 的 PASS / FAIL / **UNVERIFIED** + 证据 | **行为对比**（同一任务改前改后的差异），**无地面** |
| 写入协议 | P5 蒸馏（草稿）→ P6 调和（全库重读，修补被推翻的旧结论） | 提案直接改文件（omitted-is-inherited）→ 校验 → 无效重试一次 → 回落继承 |
| 沉淀物 | 无 schema 的 Markdown 语料库（索引 / playbook / 核查清单 / 失败记录 / 事件记录） | 被采纳的 **harness 树**（c1..c8 全文）+ 经验库里的教训（cue / lesson / evidence） |
| 治理 | 串行合并、wave barrier、journal 快照、**文件数/字节/tree hash 三方对账** | 选择是**盲选**（匿名化后选）、`Ledger.assert_identity()` 钉账目序列、指纹 `runmark.fingerprint` |
| 评测隔离 | 官方评测器输出是 host artifact，不进学习回路 | 裁判**在选择之后**才跑；`assert_tree_has_no_grader_verdicts` 钉住「判据不进 harness 树」 |
| 失败语义 | UNVERIFIED 要求补证据，不当成功 | 判据失败返回 `None`，`None` 不是零分，从分母剔除 |
| 权重 | 不动（training-free） | 不动（training-free） |
| 停止决策 | Curriculum 决定（DRS 即使 PASS 也可继续加练） | k 预算 + 预算检查 + 选择回落 |

**共同点**（值得记下来，别把两套说成对立）：两者都不碰权重；都有「第一份沉淀物指引后续工作」的结构（RSIAgent 的记忆语料 ↔ harness2 的经验库 R）；都有评测隔离；都把「沉淀物可以重组、可以收缩」当作正常（RSIAgent §3.2 的「增长包含收缩」↔ harness2 的整棵树被搬走而非追加）。

**根本分歧**：RSIAgent 的进化**不看自己改了什么的影响**（Verifier 判的是「任务做对没有」），harness2 的进化**就看改了之后行为怎么变**。所以 RSIAgent 需要地面，harness2 不需要。

## 2. 沉淀物落在 dsh 的哪个通道上

这是决定性的一张表。dsh 的可编辑通道只有三个是原生的：`AGENTS.md`（永远进上下文）、`.dsh/skills/<name>/SKILL.md`（按需加载）、工作区脚本。

| usine 的具体面 | RSIAgent 能改吗 | harness2 能改吗 | 原因 |
|---|---|---|---|
| 红线纪律文本（`discipline.ts`） | ❌ | ✅ | 记忆进不了系统提示；harness 的 c2 就是它 |
| 技能路由 / 触发句 | ❌ | ✅ | 记忆不是路由；harness 的 c6 + `autotrigger` 就是它 |
| 技能正文（`SKILL.md`） | ❌ | ✅（**但不含 `references/` 与 `assets/`**，见 `PROVENANCE.md` 末节） | 记忆 ≠ 技能 |
| 工具指引（18 个工具的选型口径） | ❌ | ✅ | h2 的 c4 |
| **工具面本身**（17 个注册工具） | ❌❌ | ⚠️ c8 能改，但**在 dsh 这一面没接**（插件要装进 profile，不是工作区文件） | 两边都改不了；h2 差一步 |
| 发布工具「不可达」这件事 | ⚠️ 记忆里可以写「发布要先开 config」——但**写成了反而是错的** | ✅ c2 可以把「不可达是设计」写死在护栏里 | 见下 |
| 跨会话沉淀的产线事实 | ✅ 这是它的本行 | ⚠️ c3 的 `LongTermMEMORY.md` 是一节，但没有 Verifier 那种 grounding | RSIAgent 的强项 |
| 「只写验证过的东西」的纪律 | ✅ Verifier 隔离天然保证 | ❌ 没有地面就没有 grounding | RSIAgent 的强项 |

**「发布不可达」这一行值得单独说**：RSIAgent 的记忆是**经验**的载体，而「发布默认不可达」是**设计**，不是经验。记忆里写「发布要先开 config」是一条**危险的**记忆（它把不可达说成了待解锁）；harness2 的 c2 护栏节写「发布不在工具面上，不要建议开启」才是对的。这不是谁更强，是**沉淀物的形状决定了它能承载哪类知识**。

## 3. 对「usine 这个 dsh 智能体」的适配度

| 判据 | RSIAgent | harness2 | 说明 |
|---|---|---|---|
| 有没有地面可用 | ❌ 无官方评测器 | ✅ 不需要地面 | 最硬的一条 |
| 能不能改智能体的系统提示 | ❌ | ✅ | 「智能体每一步都看见的东西」是 harness 的定义 |
| 能不能改技能路由 | ❌ | ✅ | |
| 能不能保证沉淀物**被读到** | ❌ 记忆要模型主动去读 | ✅ always-on | 记忆语料躺在目录里，模型不读就等于没有 |
| 跨任务的知识积累 | ✅ 强 | ✅（经验库 R，但每轮 sweep 每域从空开始） | harness2 的 R 是**按 run 与 mode 分域**的 |
| 沉淀物的可审计性 | ✅ 树哈希三方对账 | ✅ 整棵树被搬走、指纹、账目一致性 | 两边都有 |
| 失败模式 | 记忆固化不可靠（论文 §6 第三条） | 提案无效 → 回落继承（不假装成功） | |
| 本仓的工程债 | `garage/` 已有 41 KB 的 verifier 替身 + 一套没跑完的波次 | `garage-ii/` 已跑通的装配 + 机械判据 | |

## 4. 结论：两条路不是二选一

**它们改的是不同的层，理论上正交。** 对 `usine` 这样的智能体，合理的终局形态是：

- **harness2 那条路**负责「智能体的**形状**」：纪律怎么写、路由怎么排、工具口径怎么说——这是 dsh 每一步都在读的东西，错了就一直错。
- **RSIAgent 那条路**负责「**产线的事实**」：某条产线在某个版本下的实际验收口径、某个坑的成因——这是形状管不了的知识。

但**顺序有讲究**：RSIAgent 那一路现在**跑不出东西**（波次没跑完过一次，见 `../plan/rsi-gap-to-paper-2026-10.md`），而且它需要一整套 verifier 替身才能在 `usine` 上落地。所以**先走 harness2 这条路是能立刻出结果的**，RSIAgent 那条路的记忆语料一旦产出，正好可以作为 `../garage-ii/compare_rsiagent.py` 的 rsi 臂喂进去做真对照。

## 5. 本对照**不能**回答什么

- **不能**说「harness2 比 RSIAgent 强」。两者的目标面不同，且 `usine` 的 rsi 臂目前是**空记忆**——那是「记忆缺席」，不是「记忆没用」。
- **不能**说内容质量谁更好。任务集只覆盖路由 / 红线 / 诚实三件只有读了 harness 才知道的事。
- **不能**在多 seed 重复之前解读臂间的小差距。
- **不能**评估 RSIAgent 的记忆治理机制本身（Verifier 隔离、蒸馏/调和），本对照只评估「一份记忆语料放到 dsh 面前时的效果」。

这些限制在 `../garage-ii/BENCHMARK.md` 里逐条落地成报告里的固定段落——**读数字的人先读限制**。

## 6. 来源

- RSIAgent：arXiv 2609.15364；`../théâtre/ARCHITECTURE.md`；`../plan/rsiagent-memory.md`（2026-10-16 精读底稿）；`../plan/rsi-gap-to-paper-2026-10.md`（本仓的差距审计）
- harness2：arXiv 2610.14224；本目录 `README.md` / `docs/` / `harness2/`（commit `1cfe254`）；机制解读见本目录 `ARCHITECTURE.md`
- dsh 侧：<https://github.com/deepseek-ai/deepseek-harness>（`packages/bundle/headless/src/json-stream.ts` 的事件 schema；`packages/skill/skill-filesystem` 的技能发现与 rank；`packages/context/agent-instructions` 的 AGENTS.md 发现）
- 本仓：usine 产线的红线见 `../usine/packages/dsh-plugin/src/discipline.ts`；工具面见同目录 `tools.ts`
