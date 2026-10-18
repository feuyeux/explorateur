# benchmarks/usine — RSI 适配层与运行手册（常青）

> 本文回答两个问题：**后续怎么跑一次 RSI wave**，以及**跑完怎么校验自进化产物**。
> 装配契约的权威全文在 [`run_usine.py`](run_usine.py) 模块 docstring（13 条，次序承重）；
> 本文是操作面，机制冲突时以 docstring 为准。
>
> 波次机器：théâtre（vendored RSIAgent 引擎）× 本适配层 × usine（TS pnpm monorepo）。
> 改进方向见 [`distribution-usine.md`](distribution-usine.md)——**流水线与智能体面
> （dsh 插件工具面 / 纪律文案 / skills howto）都是第一等方向**，护栏钉死只可加强。

## 一、怎么跑一次 RSI wave

### 0. 在哪台机器上跑

**只有 Windows wave host 能跑真 wave。** 本 Mac 结构性跑不了（SKIP 不是 PASS）：

- **凭据墙**：`~/.minimax/config.yaml` 在本机只有 minimax 系，没有 wave 阵容需要的
  fuyao-work 端点凭据；
- **基座墙**：worktree guest 的 WorktreeEnv 依赖 git-bash（macOS `/bin/bash` 被拒），
  `verifier_adapter` 强制 WorktreeEnv。

### 1. 前置（wave host 一次性/每次核对）

| 项 | 要求 |
|---|---|
| pnpm | **standalone pnpm.exe**（不是 npm shim）——合并侧用 `shell=False` 起门禁，`.cmd` shim 起不来 |
| Node / pnpm 版本 | Node ≥ 24、pnpm ≥ 11（`gate_preflight` fail-closed 复核） |
| guest 内 coreutils | GNU `sha256sum` / `stat -c`（capture 回放校验用） |
| 凭据 | wave host 的 `~/.minimax/config.yaml`：fuyao-work + minimax 阵容齐全（密钥永不进仓库/日志） |
| 代码同步 | 三棵树（`théâtre/`、本目录、`usine/`）同步到同一血缘。**本地永不 push**，同步机制由用户在仓库外完成 |
| usine 门禁 | 开跑前 wave host 与真树各跑一次 `pnpm verify` 全绿（当前基线：545 过 / 0 败 / 4 跳） |

### 2. 开跑前自检（wave host，全绿才许进 3；théâtre venv，从 `théâtre/` 根目录起跑）

```powershell
cd <explorateur>\théâtre
.\.venv\Scripts\python.exe -m pytest tests/                                # 引擎测试
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_distribution_fence.py  # 8-gram 围栏
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_wave_merge.py          # 合并/排除/exec 位
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_usine_hooks.py         # 装配接缝（live-guest 节标 wave host）
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_dry_run_wave.py        # 假 LLM 全流程干跑（内部自带 --gate-install）
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_verifier_adapter.py    # Verifier 底座
.\.venv\Scripts\python.exe ..\benchmarks\usine\smoke_guest_env.py           # worktree guest 基座
python ..\benchmarks\usine\probe_env.py                                    # guest 侧 node/pnpm 探针（host python）
```

### 3. 跑（真波次喊跑才跑）

```powershell
.\.venv\Scripts\python.exe ..\benchmarks\usine\run_usine.py --run-name <名> --preflight   # 只读：就绪载荷，不写不烧
# 人工核对载荷（模型阵容 / 端点解析 / 围栏 / 门禁可跑性 / guest 探针）后：
.\.venv\Scripts\python.exe ..\benchmarks\usine\run_usine.py --run-name <名> --execute RUN-USINE-PHASE1-WAVES
```

一次 wave 的闭环（细节见 run_usine.py docstring）：预检 → Curriculum 出题 →
Actor 在 guest 改 usine 源码/skills → capture 剪枝（`node_modules`/`dist` 不入归档）→
Verifier 复核 → 记忆蒸馏 → **合并前 `pnpm verify` 门禁**（红即整案丢弃）→ 一候选
一 commit（`X-Theatre-Wave` trailer）+ 每 wave tag `theatre/wave-N` → 绿合并后
`dist/index.mjs` 重建，改进直达 dsh 加载的智能体面 → 下一轮围栏从新 HEAD 重算。

run root（仓库外）落：`events.jsonl`（里程碑）、episode 工件（指令原文/SUBMIT/VERDICT/
outcome）、`merge_report.json`、`endpoints.json`（gitignore 兜底）、终态记忆。

## 二、怎么校验自进化产物

三层验收，全部机械可查；**SKIP 不是 PASS，编出来的数据比没有数据更坏**。

### L1 合并完整性（跑完立即，真树上）

- `merge_report.json`：merged 计数、gate exit 0、tag / base 指对；
- delta **不含** `node_modules/`、`dist/`、`*.tsbuildinfo`（capture 剪枝 ↔ merge 排除
  两头对称——一头改另一头必改，smoke_wave_merge 有对应用例）；
- exec 位保留：`bin/feuille.js` 仍 100755（锚点用例在 smoke_wave_merge）；
- 每候选一 commit、带 `X-Theatre-Wave` trailer；每 wave 一 tag `theatre/wave-N`；零 push。

### L2 门禁层（真树上 `pnpm verify`）

- 全绿，对照基线：**545 过 / 0 败 / 4 跳**（跳过名单只许诚实新增，不许把红的算成跳）；
- 钉版对账自动在环：`packages/dsh-plugin/test/plugin-parity.test.ts`——argv 族工具
  action 枚举 ↔ `@feuille/cli` COMMANDS 路由、video-generation 规格/积分 ↔
  `skills/video-generation/SKILL.md` 速查表，wave 改任何一侧不跟另一侧，当场红；
- 红线用例只可加强不可放松：approval fail-closed、publish 默认不可达、反向验证探针；
- wave 若动了 `distribution-usine.md` / 传输注 / curriculum 配置：重跑
  `smoke_distribution_fence.py`（8-gram 围栏从新 HEAD 重算）。

### L3 智能体面真验（RSI「真作用力」的最终判据）

L2 绿只证明代码没坏；改进是否**真的到达智能体面**要真宿主加载 + 真跑一次：

1. **dist 已重建**：`pnpm verify` 顺带重建 gitignored 的
   `packages/dsh-plugin/dist/index.mjs`——核时间戳。
2. **dsh 宿主加载必带 require 互操作垫片**：esbuild 产物的内联 `__require` 在
   Node 原生 ESM（dsh 入口加载器）下对未打包的 CJS 依赖（yazl）直接抛
   "Dynamic require not supported"。垫片 =
   `globalThis.require = createRequire(<dist 目录>)` 再 import dist，模板见
   [`runs/dsh-sdk-first-task-20261018/feuille-usine-loader.mjs`](runs/dsh-sdk-first-task-20261018/feuille-usine-loader.mjs)。
   **wave host 的 dsh web 直接吃 dist 会撞同一堵墙**——同样挂垫片。
3. **零成本 preflight**：只 start+close 验 boot（模板
   [`runs/dsh-sdk-first-task-20261018/preflight.mjs`](runs/dsh-sdk-first-task-20261018/preflight.mjs)）。
   注意：dsh 会**静默吞 apply 抛错**、boot 照样成功——boot 过 ≠ 插件活；用一次性
   apply 标记确认 apply 真返回（首测教训：inject 缺 `approval`，17 工具面全丢而
   宿主无感，vitest fakeCtx 不校验 inject 所以测试面永远看不见）。
4. **真跑首任务**（模板 [`runs/dsh-sdk-first-task-20261018/run.mjs`](runs/dsh-sdk-first-task-20261018/run.mjs)，
   approval `policy: never` 确定性拒绝、零 H3 额度）：三步——`usine_version` 报版本、
   `usine_verify` 报门禁数字、红线步 `usine_video_generation` 发起 768P/6s 提交并确认
   **停在审批、未提交**。
5. **产物核对不轻信模型自述**：从 `run-log.ndjson` 机械核对——三个工具真调
   （call/result 事件成对）、`approval/asked` → `approval/decided(rejected)`、返回
   无 task_id、纪律节生效（模型在思考/回复中引用纪律文本）、零 shell 误调。

## 三、红线（对 wave、对测试、对验收同样成立）

- **零 H3 / mcode-tools 额度调用**：任何会消耗视频生成额度的调用，先向用户报
  提示词/画幅/时长/分辨率/预估消耗并拿到明确同意；「你直接跑」不算授权。
- **零平台发布/登录**：VM 门面、guest-home USERPROFILE 钉死、offline-only 门禁三层防线。
- **真波次喊跑才跑**；一候选一 commit；每 wave tag；**永不 push**。
- **SKIP 不是 PASS**；跑不了的项如实标「wave host 待跑」。

## 四、文档地图

| 文档 | 角色 |
|---|---|
| [`run_usine.py`](run_usine.py) docstring | 装配契约权威全文（13 条）+ wave host 就绪清单 |
| [`distribution-usine.md`](distribution-usine.md) | 给 Curriculum 的目标方向（改进面许可 + 护栏） |
| `config/roles-usine/*.yaml` | 座位表（模型阵容 fail-closed 校验） |
| [`runs/`](runs/) | 真跑现场归档（含首测事故与修复全套） |
| [`../théâtre/ARCHITECTURE.md`](../théâtre/ARCHITECTURE.md) | 引擎机制与图表（v1 基线） |
| [`../théâtre/ADAPTATION.md`](../théâtre/ADAPTATION.md) · [`PROVENANCE.md`](../théâtre/PROVENANCE.md) · [`PORTING-NOTES.md`](../théâtre/PORTING-NOTES.md) | v1 偏离记录 / fork 纪律 / 跨平台病根 |
| [`../usine/migration/README.md`](../usine/migration/README.md) | usine TS 迁移与 P9 改造收口史 |
