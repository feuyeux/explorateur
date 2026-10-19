# théâtre 使用指南：你面对的是一台自我改进机器

> 本文从**人机交互**视角回答一个问题：**作为人，怎么让这台机器替你改进 usine**。
> 机器做什么、判据是什么，权威文本在
> [`../../benchmarks/usine/README.md`](../../benchmarks/usine/README.md)（运行手册）与
> [`../ARCHITECTURE.md`](../ARCHITECTURE.md)（机制与图表）；
> `run_usine.py` 的 docstring 是装配契约的权威全文。本文不重复它们，只讲**你什么时候说话、
> 说什么、机器自动跑完什么、哪些关口它必须停下等你**。

---

## 1. 你面对的是什么

你面对的不是一堆要手工操作的 Python 脚本（pytest、smoke、merge、tag），而是一台
**功能完整且自动化的 RSI（递归自我改进）机器**：théâtre 引擎 × benchmarks/usine 适配层 ×
usine 生产树。你说「**跑一轮自我改进**」，它自己走完整个闭环：

```text
预检 → Curriculum 出题 → Actor 在隔离 guest 里改 usine 源码 / skills
     → capture 剪枝（node_modules/dist 不入归档）→ Verifier 复核 → 记忆蒸馏
     → 合并前 pnpm verify 门禁（红即整案丢弃）→ 一候选一 commit（X-Theatre-Wave trailer）
     → 每 wave 打 tag theatre/wave-N → dist 重建（改进直达 dsh 智能体面）
     → 下一轮围栏从新 HEAD 重算
```

全部运行产物（events / episodes / merge_report / endpoints.json）落在**仓库外**的 run root
（`theatre-usine-runs`），真树只收下门禁全绿后的合并结果。你从头到尾不需要
手动跑任何一条 pytest / smoke / merge 命令——那是机器的四肢，不是你的。

## 2. 快速上手（一次性）

每台主机只需备一次；逐项核对清单（两台 host 各一列）在
[benchmarks/usine/README.md](../../benchmarks/usine/README.md) 第 1 节，这里是速览：

| # | 备什么 | 一句话说明 |
|---|---|---|
| 1 | Node ≥24 + **standalone pnpm**（Windows；不是 npm shim） | 合并侧门禁靠它起 |
| 2 | théâtre venv + coreutils（Windows guest 内 GNU 工具 / macOS brew） | 引擎与 guest 的运行底座 |
| 3 | 模型凭据 `~/.minimax/config.yaml`（fuyao-work + minimax 阵容） | 密钥永不进仓库与日志 |
| 4 | `deepseek-harness` checkout（dsh-plugin 的 `link:` 解析锚） | 缺了预检直接红，不烧 token |
| 5 | 三棵树（théâtre / benchmarks/usine / usine）同步到同一血缘 | 改进对象与围栏必须对得上 |
| 6 | 开跑前真树上 `pnpm verify` 全绿 | 基线：Windows 559 过 / 0 败 / 4 跳 |

## 3. 快速见效：零风险的三步（按顺序）

每一步都**不烧 token、不写真树、不产生外部副作用**，做完你对这台机器就有了完整的信心：

| # | 你说什么 | 机器自动做什么 | 你看到什么 |
|---|---|---|---|
| 1 | 「**跑一遍 RSI 自检**」 | 引擎 pytest 全绿 + 六个 smoke（围栏 / 合并 / 装配接缝 / Verifier / guest 基座） | 全绿报告（Mac 实测：pytest 808 过 / 3 跳 + 六 smoke） |
| 2 | 「**跑一遍假波次干跑**」 | `smoke_dry_run_wave.py`：假 LLM 走完全流程（含门禁安装） | 全波次 12/12、零弹窗——闭环真的转起来了 |
| 3 | 「**做一次 preflight**」 | `run_usine.py --run-name <名> --preflight`：只读装配，不写不烧 | 就绪载荷：模型阵容 / 端点解析 / 围栏 / 门禁可跑性 / guest 探针 |

从 `théâtre/` 根目录起（Windows wave host 示例）：

```powershell
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_dry_run_wave.py   # 第 2 步
.\.venv\Scripts\python.exe ..\benchmarks\usine\run_usine.py --run-name <名> --preflight   # 第 3 步
```

三步全绿，就绪载荷人工核对无误，这台机器就处于「随时可以真跑」的状态。

## 4. 真跑一轮：你只说一次「跑」

**真波次喊跑才跑**——`--execute RUN-USINE-PHASE1-WAVES` 这个 token 就是喊跑本身，
机器不会替你按下它：

```sh
./.venv/Scripts/python.exe ../benchmarks/usine/run_usine.py \
  --run-name fast-wave-20261019 \
  --project-budget 1 --checkpoints 0,1 \
  --execute RUN-USINE-PHASE1-WAVES
```

喊完之后是**全自动**的：出题、改造、复核、门禁、合并、tag、重建智能体面、重设围栏，
一路走完。你只需要在结束时核对它的三层验收报告（§6）。

## 5. 它停下找你的时刻（刻意的安全边界）

| 时刻 | 机器的行为 | 你做什么 |
|---|---|---|
| 真波次开始前 | 停在 preflight，不主动越权 | 核对载荷，说出 execute token |
| 任何要花额度的调用 | 先报提示词 / 画幅 / 时长 / 分辨率 / 预估消耗；**「你直接跑」不算授权** | 明确同意或拒绝 |
| 发布 / 登录 | **永不自动执行**（三层防线：VM 门面 / guest HOME 钉死 / offline-only 门禁） | 该发生时只能由你亲手做 |
| 门禁红 | **整案丢弃**，不硬合并、不硬修到绿 | 看它的丢弃报告，决定下一轮方向 |

「机器停下来」不是故障，是纪律。它对状态同样诚实：跑不了的项如实标
「wave host 待跑」，**SKIP 不是 PASS**。

## 6. 跑完怎么验收：三层，全部机械可查

对着机器交回的验收报告扫三眼（细则在
[benchmarks/usine/README.md](../../benchmarks/usine/README.md) 第二节）：

- **L1 合并完整性**：merge_report 的 merged 计数 / gate exit 0 / tag 指对；delta 不含
  `node_modules`、`dist`；一候选一 commit 带 `X-Theatre-Wave`；零 push。
- **L2 门禁层**：真树 `pnpm verify` 全绿，跳过数对上基线（Windows 559/0/4）。
- **L3 智能体面真验**：dist 已重建；dsh 宿主带 require 垫片加载；一次性 apply 确认
  17 工具面真的挂上；真跑首任务（版本 → 门禁数字 → 额度红线停在审批未提交）；
  产物从 `run-log.ndjson` 机械核对，不轻信模型自述。

## 7. 红线（对你同样成立）

零 H3 / mcode-tools 额度调用（未确认不生成）；零平台发布 / 登录；
真波次喊跑才跑；一候选一 commit；每 wave tag；**永不 push**。

## 8. 文档地图

| 想了解 | 读 |
|---|---|
| 怎么跑一次 wave、逐项前置清单、验收细则（权威） | [benchmarks/usine/README.md](../../benchmarks/usine/README.md) |
| 装配契约 13 条（权威全文） | `run_usine.py` 模块 docstring |
| 引擎机制与图表 | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| 改进方向与护栏（给 Curriculum 的许可面） | [distribution-usine.md](../../benchmarks/usine/distribution-usine.md) |
| fork 纪律 / 实现偏离 / 跨平台病根 | [PROVENANCE.md](../PROVENANCE.md) · [ADAPTATION.md](../ADAPTATION.md) · [PORTING-NOTES.md](../PORTING-NOTES.md) |
| 真跑现场归档（含首测事故） | [benchmarks/usine/runs/](../../benchmarks/usine/runs/) |
