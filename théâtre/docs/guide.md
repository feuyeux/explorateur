# théâtre 使用指南：用最少的资源、最短的时间完成一次自我进化

> 本文从**人机交互**视角回答两个问题：**作为人，怎么让这台机器替你改进 usine**；以及**怎么让一次自我进化花得最少、跑得最快**。机制与判据的权威文本不变：[garage/README.md](../../garage/README.md)（运行手册）、[ARCHITECTURE.md](../ARCHITECTURE.md)（机制与图表）、`run_usine.py` docstring（装配契约 13 条）。本文不重复它们，只讲你什么时候说话、说什么、钱和时间花在哪、哪些关口它必须停下等你。

## 1. 你面对的是什么

不是一堆要手工操作的 Python 脚本（pytest / smoke / merge / tag），而是一台**功能完整的自动化 RSI 机器**：théâtre 引擎 × garage 适配层 × usine 生产树。你说「跑一轮自我改进」，它自己走完全闭环：

```text
预检 → Curriculum 出题 → Actor 在隔离 guest 里改 usine 源码 / skills
     → capture 剪枝（node_modules / dist 不入归档）→ Verifier 复核 → 记忆蒸馏
     → 合并前 pnpm verify 门禁（红即整案丢弃）→ 一候选一 commit（X-Theatre-Wave trailer）
     → 每 wave 打 tag theatre/wave-N → dist 重建（改进直达 dsh 智能体面）→ 围栏从新 HEAD 重算
```

全部运行产物（events / episodes / merge_report / endpoints.json）落在**仓库外**的 run root；真树只收门禁全绿后的合并结果。pytest 和 smoke 是机器的四肢，不是你的。

## 2. 一次候选的真实成本（评审后的账）

| 环节 | LLM | I/O / 墙钟（实测） |
|---|---|---|
| 前置自检 | 0 | 引擎 pytest 808 项 + 五 smoke（全套十分钟级） |
| Curriculum 出题 | 1 段（reasoning max） | 分钟级 |
| Actor 干活（VM1） | N 轮，**无实上限**（iters 2000 / 墙钟 24h / 历史永不裁剪） | guest `pnpm install` 15.8s + 全量 verify（本机 vitest 79s + typecheck，≈2 分钟） |
| Verifier（VM2） | 1–3 轮（reasoning max） | **整盘真字节快照**（`shutil.copytree`，含 Actor 装出的 node_modules） |
| Memory 蒸馏 + 调和（VM3） | 2 段 | fresh VM + 候选重放 ×2 |
| 合并门禁（host） | 0 | 全量 `pnpm verify` 再跑一次，≈2 分钟 |

三个座位全部 reasoning max + 64k token 上限、每候选最多三次 fresh VM、全量门禁两到三遍——这是按**批量波次会话**设计的量级；对「一次」目标，LLM 成本粗估有 60–70% 可省，安全性质一条不用动。

## 3. 最省的跑法（minimal wave 配方）

**先核对一个事实再烧任何 token：真树门禁必须全绿**（Windows 基线 559 过 / 0 败 / 4 跳）。基线是红的就先修红——门禁红着开 wave，额度先烧完，最后在 merge 门禁上整案丢弃。这条现在就是时间最短路径上的第一件事。

现在就生效的开关（零代码改动）：

- `--project-budget 1 --checkpoints 0,1`——单 wave、单项目、单候选（默认 8 项目 × 并行 4 是给批量会话的）；
- Curriculum 出题面挑**单一小改进**（dsh 插件面 / skills howto 是第一等方向，一个措辞级改进就是合格候选）；
- L3 验收用 in-repo 便宜入口（§7），别再走 Mac 硬编码模板。

待你点头再落地的瘦身（改配置 / 代码，收益从大到小）：

| 瘦身点 | 现状 → 建议 | 代价 |
|---|---|---|
| Actor 座位档位 | iters 2000 / 墙钟 24h / reasoning max / 温度 1.0 / 历史不裁 → iters 40 / 墙钟 45min / reasoning 降档 / 历史裁剪 | 无——这些本就是应急看门狗，不是语义停止线 |
| 门禁次数 | Actor 全量 + merge 全量（+ Verifier 可能再来一遍）→ Actor 只跑 typecheck + 受影响包，**全量只在 merge 跑一次** | 无——merge 门禁本就是权威判据，红即整案丢弃，SKIP 不是 PASS 不变 |
| Verifier 快照 | 整盘真字节拷 → ignore node_modules / dist（或硬链接式快照） | 无——VM2 本来就是剪枝后的纯源码回放 |
| Memory 两段 | 蒸馏 + 调和 → 单段或本波关闭 | 牺牲单候选的跨波记忆积累，需你裁定 |
| 前置仪式 | 每次 808 + 五 smoke → 改动面相关的 smoke | 引擎测试留作改动引擎时才跑 |

本来就省的部分（一条都不要动）：Curriculum 一段即收、capture/合并对称剪枝、corpus 全程固定、审计五面零成本在岗、发布红线零额度三层防线、副作用显式回滚、预检全在零 LLM 侧。

瘦身配方全落地后的量级：LLM 调用 10–30 次、墙钟 15–25 分钟、I/O 除快照外全在分钟级。

## 4. 快速见效：零风险两步（不烧 token、不写真树）

| # | 你说什么 | 机器自动做什么 |
|---|---|---|
| 1 | 「跑一遍 RSI 自检」 | 引擎 pytest 全绿 + 五 smoke（围栏 / 合并 / 装配接缝 / Verifier / guest 基座） |
| 2 | 「做一次 preflight」 | `run_usine.py --preflight` 只读装配：阵容 / 端点 / 围栏 / 门禁可跑性 / guest 探针 |

从 `théâtre/` 根目录起（Windows wave host 示例）：

```powershell
.\.venv\Scripts\python.exe ..\garage\run_usine.py --run-name <名> --preflight
```

两步全绿 + 就绪载荷人工核对无误，机器就处于「随时可真跑」状态。（假 LLM 干跑剧本已于 2026-10-19 按用户决定退役：只跑真实 wave；接缝咬合由引擎测试与五 smoke 守住。）

## 5. 真跑：你只说一次「跑」

**真波次喊跑才跑**——execute token 就是喊跑本身，机器不会替你按：

```powershell
.\.venv\Scripts\python.exe ..\garage\run_usine.py `
  --run-name fast-wave-20261019 --project-budget 1 --checkpoints 0,1 `
  --execute RUN-USINE-PHASE1-WAVES
```

喊完之后全自动：出题、改造、复核、门禁、合并、tag、重建智能体面、重设围栏。你只需要在结束时核对 §7 的验收报告。

## 6. 它停下找你的时刻（刻意的安全边界）

| 时刻 | 机器的行为 | 你做什么 |
|---|---|---|
| 真波次开始前 | 停在 preflight，不主动越权 | 核对载荷，说出 execute token |
| 要花额度的调用 | 先报提示词 / 画幅 / 时长 / 分辨率 / 预估消耗；**「你直接跑」不算授权** | 明确同意或拒绝 |
| 发布 / 登录 | **永不自动执行**（VM 门面 / guest HOME 钉死 / offline-only 门禁三层防线） | 该发生时只能由你亲手做 |
| 门禁红 | 整案丢弃，不硬合并、不硬修到绿 | 看丢弃报告，定下一轮方向 |

机器停下来不是故障，是纪律；跑不了的项如实标「wave host 待跑」，**SKIP 不是 PASS**。

## 7. 跑完怎么验收：三层，全部机械可查

- **L1 合并完整性**：merge_report 的 merged 计数 / gate exit 0 / tag 指对；delta 不含 `node_modules`、`dist`；一候选一 commit 带 `X-Theatre-Wave`；零 push。
- **L2 门禁层**：真树 `pnpm verify` 全绿，跳过数对上基线（Windows 559/0/4）；wave 若动了围栏面，重跑 `smoke_distribution_fence.py`。
- **L3 智能体面真验**（in-repo 便宜入口，已实测）：`pnpm verify` 顺带重建 `packages/dsh-plugin/dist`；`pnpm --filter @feuille/dsh-plugin preflight`（零 LLM，只验 runtime + 插件加载）；`pnpm --filter @feuille/dsh-plugin ask 自检`（单发一轮：版本 + 额度只读 + 门禁数字）；红线步确认审批卡停车、未提交——产物从 `run-log.ndjson` 机械核对，不轻信模型自述。

## 8. 红线（对你同样成立）

零 H3 / mcode-tools 额度调用（未确认不生成）；零平台发布 / 登录；真波次喊跑才跑；一候选一 commit；每 wave tag；**永不 push**。

## 9. 文档地图

| 想了解 | 读 |
|---|---|
| 怎么跑一次 wave、逐项前置、验收细则（权威） | [garage/README.md](../../garage/README.md) |
| 装配契约 13 条（权威全文） | `run_usine.py` 模块 docstring |
| 引擎机制与图表 | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| 改进方向与护栏（Curriculum 的许可面） | [distribution-usine.md](../../garage/distribution-usine.md) |
| fork 纪律 / 实现偏离 / 跨平台病根 | [PROVENANCE.md](../PROVENANCE.md) · [ADAPTATION.md](../ADAPTATION.md) · [PORTING-NOTES.md](../PORTING-NOTES.md) |
| 真跑现场归档（含首测事故） | [garage/runs/](../../garage/runs/) |
