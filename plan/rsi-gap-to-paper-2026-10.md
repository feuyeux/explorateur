# RSI 流水线 vs RSIAgent 论文 · 差距与修正计划

> 对象：RSIAgent（[AetherLabsAI/RSIAgent](https://github.com/AetherLabsAI/RSIAgent)，arXiv 2609.15364）的记忆治理与三阶段闭环
> 现状：`théâtre/`（vendored RSIAgent 引擎）+ `garage/`（usine 适配层）+ `usine/`（被改进的 TS 生产线）
> 依据：[`rsiagent-memory.md`](rsiagent-memory.md)（2026-10-16 论文精读底稿）§2.2 / §4.2 / §5 / §6 + 本仓库代码与 `garage/runs/` 真跑现场实读
> 生成：2026-10-19

---

## 0. 一句话结论

**引擎层（théâtre）已忠实实现论文机制，欠账全在适配层（garage）**：三阶段闭环只接通 BRS 的前半段，DRS 与冻结复用零通路；Curriculum 的记忆纪律与 `curriculum_review` 停止策略在 Phase 2 有完整机制、Phase 1 完全没有接线。

修正按工程分：**garage 改 3 项（主战场）、théâtre 不动、usine 只加断言不改行为**。

---

## 1. 机制覆盖总表

| 论文机制 | 论文位置 | théâtre | garage | 真跑证据 |
|---|---|---|---|---|
| BRS：同一 pre-wave 记忆快照 + 隔离 VM 并行 | §2.2 | ✅ `explore/phase1_wave.py:4` | ✅ `--project-budget` 默认 8、`max_parallel: 4` | ⚠️ 两次 wave 均被 transport 异常打断 |
| DRS：串行 + `curriculum_review` 停止策略 | §2.2 | ✅ `core/self_evolving_loop.py:31-38` | ❌ 无任何 phase2 调用 | ❌ `runs/` 无 phase2 现场 |
| 冻结复用（Phase 3） | §2.2 | ✅ 引擎有 phase3 | ⚠️ 仅 `_atomic_install_memory` 落 `memory_frozen` | ❌ 无复用验证 |
| 记忆 journal | §4.2 | ✅ `explore/commit.py:139-150` | — | — |
| tree hash 对账 | §4.2 | ✅ `explore/memory_hash.py` | ✅ 收口处已带（见下） | ⚠️ 未执行到 |
| Verifier 三态（PASS/FAIL/UNVERIFIED） | §4.1 / §5 | ✅ `core/verifier.py` 45 处，含 pass→unverified 降级（`:1617-1623`） | ✅ `target-usine.yaml:90` 已开 | ✅ |
| Verifier 隔离（不见 Actor 推理与私有路径） | §4.2 | ✅ 原生 | ✅ `verifier_private_paths` 钉死 `/home/user/.memory`（`target-usine.yaml:96-98`） | ✅ |
| Curriculum 记忆只读（Phase 1） | §2.1 | ✅ `explore/charter.py:492-501` + `practice_loop.py:1396-1400` | ✅ 无需 garage 接线 | ✅ |
| Curriculum 记忆 `none` 模式（Phase 2） | §2.1 | ✅ `explore/charter.py:255-272`，12 处 recovery 断言 | ❌ DRS 未接通，故不可达 | ❌ |
| 评测隔离（官方分数不入记忆） | §4.2 | ✅ `explore/post_target_learning_recovery.py:50` | ✅ `official_evaluator_calls: 0`（`run_usine.py:1656`） | ✅ |
| 快照三方对账（文件数/字节/tree hash） | §4.2 | ✅ | ✅ `run_usine.py:1651-1654` | ❌ 未执行到 |

### 1.1 三条初判错误的更正（重要）

审计过程中推翻了三个看似成立的差距，避免后续按错方向返工：

1. **「tree hash 对账缺失」不成立。** `run_usine.py:1654` 已写 `memory_tree_sha256: _memory_tree_sha256(memory)`，与 `memory_files` / `memory_bytes` / `memory_manifest` 构成论文 §4.2 要求的文件数—字节—tree hash 三方对账。
2. **「UNVERIFIED 在适配层丢失」不成立。** `garage/config/roles-usine/target-usine.yaml:90` 已设 `verifier_unverified_evidence: true`，引擎侧 `core/verifier.py` 有 45 处实现（`:603-604` 解析、`:1253` 分流、`:1617-1623` pass→unverified 降级）。
3. **「Curriculum 记忆纪律未覆盖 Phase 1」不成立。** 引擎在 Phase 1 就已内建该纪律：`charter.py:492-501` 给 Curriculum 的 memory_contract 明写「可丢弃证据副本、不可编辑/批准/评分、Actor 独占作者权」，`practice_loop.py:1396-1400` 与 `phase1_wave.py:669` 在出题 VM 上以单向 `_push_canonical_memory` 挂载，引擎注释明确 *「only the post-outcome Actor memory phase can change the host-owned corpus」*。Phase 1 不需要 garage 做任何接线。

此外 `events.jsonl` 里的 `memory_manifest: {}` **不是**缺陷：它来自 `PHASE1_WAVE_STARTED` 事件，语义是 pre-wave 起始记忆为空，符合论文「记忆从空目录长起」（三条案例轨迹均如此）。

---

## 2. 差距一：DRS 与冻结复用零通路（最高优先级）

**现状**：garage 只有 Phase 1 入口。`run_usine.py:331` 的 `EXECUTE_ACK = "RUN-USINE-PHASE1-WAVES"` 是唯一执行令牌，`:1628-1637` 收口时只做 Phase 1 的 `memory_frozen` 落盘，没有任何 phase2/phase3 调用。

**后果**：论文的核心主张是**记忆在深度探索中持续增值**（§5 复用证据表全部来自 DRS 后的冻结记忆）。没有 DRS，论文的招牌数字（OSWorld 71.97→78.98、ALE 83.75→84.82）在当前工程里无法复现，也无法证伪。

**修正（garage）**：

| 步骤 | 落点 | 内容 |
|---|---|---|
| 2.1 | `garage/run_usine.py` 新增 `--phase` 参数 | 取值 `1`/`2`/`3`，默认 `1`；`2`/`3` 需独立 ack token（如 `RUN-USINE-PHASE2-DRS`），沿用「真波次喊跑才跑」纪律 |
| 2.2 | 新增 `garage/config/roles-usine/` 下的 phase2 计划文件 | 复用 `théâtre/benchmarks/osworld/phase2.py` 的 `development_tasks` + `stop_policy: curriculum_review` 结构 |
| 2.3 | `run_usine.py` 收口段（约 :1628 起）扩展 | phase2 结束后导出记忆，与 `memory_frozen` 做三方对账；把 DRS 新增记忆单独记 `drs_delta` |
| 2.4 | `garage/README.md` §一 | 补 phase2/phase3 的操作序列，与现有 BRS 段并列 |

**验收**：一次完整 BRS→DRS→冻结跑通，`run_root/result.json` 的 `memory_tree_sha256` 在 DRS 后**严格大于** BRS 后（记忆只增不减，或按论文 §3.2「增长包含收缩」允许重组但需文件级 diff 可解释）。

---

## 3. 差距二（已消解）：Curriculum 记忆纪律

**审计结论：这条不成立，引擎已完整落实，garage 无需接线。**

初判以为纪律只服务 phase2，实读发现 Phase 1 早已覆盖：

- `théâtre/explore/charter.py:492-501` — `memory_contract` 在 `phase1_exploration` 分支给 Curriculum 的原文：「CURRENT ACTOR-OWNED DURABLE MEMORY is available at ~/.memory as a **disposable evidence copy**…Do not edit, rewrite, approve, reject, or grade the memory; the Actor Agent exclusively owns its contents and any changes you make to this guest copy are discarded.」
- `théâtre/explore/practice_loop.py:1396-1400` — 引擎注释逐字写明「The canonical memory is mounted only as a disposable evidence copy: Curriculum may inspect it to choose an experience, but **only the post-outcome Actor memory phase can change the host-owned corpus**」，随后调 `_push_canonical_memory`。
- `théâtre/explore/phase1_wave.py:669` — Phase 1 出题 VM 同样走 `_push_canonical_memory`，配合 `:686` 的 wave 快照独立化。

单向性由机制保证（host 侧 `_push_canonical_memory` 只推不拉，回写只能走 Actor 记忆阶段），不依赖 prompt 服从。

**唯一实际改动是出题预算收紧**（与时间上限同批落地）：`curriculum-usine.yaml` 的 `max_iters` 2000→60、`wall_clock_secs` 86400→80。理由不是「它有权限乱来」，而是天级预算让整轮跑不完。

---

## 4. 差距三：BRS 从未跑完一次（阻塞项，非设计缺陷）

**现状**：`garage/runs/` 两个 wave 现场都止于 `PHASE1_BRANCH_EXCEPTION`，`classification: infra`：

- `wave1-blocked-20261018` — 5 个项目全部 `HTTP 401 auth failed`（`fuyao-work` 凭据问题）
- `wave1r-lineup-switch-20261018` — `HTTP 400 context window exceeds limit (2013)`（换阵容后仍撞上下文）

**这不是架构缺陷，是运行稳定性问题**。但它的后果是：记忆治理层从未拿到过非空记忆——`result.json` 的落盘点（`run_usine.py:1658`）两次都没执行到，所以 `memory_tree_sha256` 三方对账代码从未在真实数据上跑过一次。

**修正（garage）**：

| 步骤 | 落点 | 内容 |
|---|---|---|
| 2.8 | `garage/probe_env.py` | 在 preflight 里加**上下文预算预检**：按各角色 `ctx_high_water`（`target-usine.yaml:61` 设 900000）反推实际可用窗口，在开跑前报「某席实际窗口 < 声明值」，避免跑到一半才 400 || 2.9 | `garage/README.md` §一.1 | 凭据表补一句：401 是端点凭据问题，先跑 `probe_env.py` 再开 wave（当前表只写了变量名，没写故障症状→动作的映射） |

**验收**：一次 BRS 完整跑通（`result.json` 落盘、`memory_tree_sha256` 非空），哪怕 `status` 是 `budget_exhausted` 也算数。

---

## 5. 差距四：usine 侧缺「记忆是否真的到达智能体面」的机器断言

**现状**：`garage/README.md` §二 L3 已经把这件事定义为人工程序（dist 时间戳 → 加载垫片 → preflight → 真跑首任务 → 机械核对 `run-log.ndjson`），`usine/packages/dsh-plugin/test/plugin-parity.test.ts` 也钉了「argv 工具枚举 ↔ CLI COMMANDS」的双向一致。但这套验收是**逐条人工执行**的，且 `README.md` §二.3 记录的那次首测事故（inject 缺 `approval`、17 工具全丢而宿主无感、vitest fakeCtx 不校验 inject）说明它已经漏过一次。

论文 §5 的判据是「改进是否真到达下游执行」，当前没有常驻门禁兜着这条。

**修正（usine，只加不改）**：

| 步骤 | 落点 | 内容 |
|---|---|---|
| 2.10 | `usine/packages/dsh-plugin/test/plugin-parity.test.ts` | 加一条：`inject` 数组与 `apply()` 内实际访问的 `ctx.*` 服务集合必须一致（防首测事故复发）。这是纯新增用例，不改 `src/index.ts` 行为 |
| 2.11 | `garage/smoke_usine_hooks.py` | 把 README §二.3 的 preflight 三步 + 真跑首任务固化成可重跑的 smoke（现在只有 `runs/` 下的一次性脚本） |

**边界**：usine 是被改进对象，**不在本轮修改的行为范围内**。只加断言型测试，不动工具面、纪律文案、红线默认值——护栏钉死只可加强不可放松。

---

## 6. 执行顺序与依赖

```
2.8 预检上下文预算 ──┐
2.9 README 故障映射 ┴─→ 2.1~2.4 DRS 通路 ──→ 2.5~2.7 Curriculum 纪律 ──→ 2.10~2.11 usine 断言
        （先让 BRS 跑完，拿到非空记忆作为 DRS 的输入）
```

关键依赖：**2.1 之前必须先有成功的 BRS**。DRS 的价值在于对已有记忆做深度加练，输入是空记忆的话 DRS 退化成第二次 BRS，跑出来也不能证明论文主张。

单改一项不产生可观测收益——论文 §4.2 那条「每个 wave 完整闭环才合并」的纪律同样适用于这条修正链本身。

---

## 7. 明确不做的事

| 项 | 理由 |
|---|---|
| 改 `théâtre/` 任何代码 | vendored fork，`PROVENANCE.md` 定 POSIX 补丁逐字节不变、不回步上游。引擎机制已忠实，缺口在接线不在实现 |
| 在 garage 新造记忆隔离 / 对账机制 | 引擎 `charter.py` + `memory_hash.py` + 三处 recovery 断言已覆盖，重复实现会制造两套真相 |
| 让 Actor 侧 subprocess 调 dsh | `usine/packages/dsh-plugin/src/index.ts:12` 已定「无 subprocess 桥」，工具走进程内原生 import |
| 引入官方 grader | `target-usine.yaml:8` 记明 unavailable，`run_usine.py:1656` 钉 `official_evaluator_calls: 0`，与论文「评测隔离」一致 |
| 扩 wave 并发 / 预算 | 论文默认 8 项目 / 4 并行，当前已对齐。瓶颈是稳定性不是容量 |

---

## 8. 来源

- 论文：RSIAgent: Autonomous Exploration for Recursive Self-improvement in New Environments（arXiv 2609.15364，附录 10.2 提示词 P5/P6、附录 12 案例研究、表 A5–A8）
- 精读底稿：[`rsiagent-memory.md`](rsiagent-memory.md)（§2.2 三阶段、§4.2 合并治理、§5 复用证据、§6 失败模式）
- 引擎机制：[`../théâtre/ARCHITECTURE.md`](../théâtre/ARCHITECTURE.md)、[`../théâtre/README.md`](../théâtre/README.md:100-101)、`théâtre/core/verifier.py`、`théâtre/explore/charter.py`、`théâtre/explore/practice_loop.py`
- 适配层：[`../garage/README.md`](../garage/README.md)、`garage/run_usine.py`、`garage/verifier_adapter.py`、`garage/config/roles-usine/*.yaml`
- 真跑现场：`garage/runs/wave1-blocked-20261018/events.jsonl`、`garage/runs/wave1r-lineup-switch-20261018/events.jsonl`
- 智能体面：`usine/packages/dsh-plugin/src/index.ts`、`usine/packages/dsh-plugin/test/plugin-parity.test.ts`
