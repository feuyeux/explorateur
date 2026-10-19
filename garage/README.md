# garage — RSI 适配层与运行手册（常青）

> 本文回答两个问题：**后续怎么跑一次 RSI wave**，以及**跑完怎么校验自进化产物**。
> 装配契约的权威全文在 [`run_usine.py`](run_usine.py) 模块 docstring（13 条，次序承重）；
> 本文是操作面，机制冲突时以 docstring 为准。
>
> 波次机器：théâtre（vendored RSIAgent 引擎）× 本适配层 × usine（TS pnpm monorepo）。
> 改进方向见 [`distribution-usine.md`](distribution-usine.md)——**流水线与智能体面
> （dsh 插件工具面 / 纪律文案 / skills howto）都是第一等方向**，护栏钉死只可加强。

## 一、怎么跑一次 RSI wave

### 0. 在哪台机器上跑

两台主机都能跑全链路（预检 → 真 wave）：**Windows wave host** 与
**POSIX dev host（macOS）**。同一套 `guest_env.py` 双底座：Windows 走 per-VM
subst 盘符，POSIX 走 scratch 根直挂（`~/.cache/rsi-usine-vm`），Windows 代码
路径字节不变（wave host 仍在跑它）。本机（Mac，2026-10-18）已实测：引擎
pytest 808 过 3 跳 + 五 smoke 全绿（fence / wave_merge / hooks /
verifier_adapter / guest_env）+ 只读 `--preflight` ready。（干跑
smoke_dry_run_wave.py 已于 2026-10-19 按用户决定退役：只跑真实 wave。）

**全平台无浏览器门禁（刻意设计，不是缺陷）**：**双侧**导出
`FEUILLE_BROWSER=<不存在路径>` 哨兵——guest 侧
`guest_env._disable_in_guest_browser`，host 侧
`run_usine._wave_host_no_browser`（`setdefault`——操作员显式指定真浏览器
可覆盖）。`usine` 的 `platform.browser()` 对 `FEUILLE_BROWSER` 优先于一切
查找、路径不存在 = null → 浏览器门控用例 skipIf / early-return，零 Edge 启动。

两个平台各自的理由，都是实测：

- **macOS**：Edge 无头模式每次启动都写一个随机 GUID 名的钥匙串项并弹
  「找不到钥匙串」系统弹窗——「始终允许」永远盖不住（项名无界），
  `--use-mock-keychain` 在 Edge 正式版二进制里不存在（0d59354 提交说明称其能
  抑制钥匙串，实测为 no-op）。
- **Windows**（2026-10-19 加入，用户决定「不必非得真浏览器」）：本机 Edge 在
  vitest 下**稳定**产不出截图——`covers.test.ts` 4/4 渲染用例单独跑也全败
  （`textlayer.edgeScreenshot` → `cropTo` 拿不到文件），而裸跑
  `Edge --screenshot` 成功。门禁因此必红（13 败），每个候选都会被判 FAIL、
  wave 永远合不上。无浏览器哨兵把它变成诚实的 SKIP，门禁回到
  **524 过 / 8 跳 / 0 败**（退出码 0，24s）。
  顺带修了同族真 bug：`publish.test.ts` 的「playwright 驱动本地 mock」整块只判
  `hasPw`、漏判浏览器在场，而 `base.resolveChrome()` 在无浏览器时是**显式抛错**
  而非返回 null（本包契约：绝不静默换浏览器），于是无浏览器主机上把该块打成
  FAIL；现已补上 `pt.browserPath() === null` 门控，与同文件另两处同形。

**诚实成本：门禁不跑渲染路径**（浏览器用例计入 skip，**SKIP 不是 PASS**），
任何运行报告必须如实把它们记为跳过，不得充作覆盖。**singleFork 陷阱**：
vitest edge 工程单 worker 串行跑全部测试文件，任何用例里无条件
`delete process.env.FEUILLE_BROWSER` 都会毒化同 worker 的后续用例——改环境
变量必须保存旧值、finally 里还原（poster/publish 的旧写法曾导致测试中弹窗）。
新增浏览器门控用例时，**两个条件都要判**（依赖在场 ∧ 浏览器在场），
只判其一会把「显式报缺」型契约打成 FAIL 而不是 SKIP。

### 1. 前置（两台 host 一次性/每次核对）

| 项 | Windows wave host | POSIX dev host（macOS） |
|---|---|---|
| pnpm | **standalone pnpm.exe**（不是 npm shim）——合并侧用 `shell=False` 起门禁，`.cmd` shim 起不来 | PATH 上的 pnpm（≥ 11）即可 |
| Node / pnpm 版本 | Node ≥ 24、pnpm ≥ 11（`gate_preflight` fail-closed 复核） | 同左 |
| coreutils | guest 内 GNU `sha256sum` / `stat -c`（capture 回放校验用） | **`brew install coreutils`** + 把 gnubin 写进 bash 登录 PATH（`~/.bash_profile` 里 `export PATH="/opt/homebrew/opt/coreutils/libexec/gnubin:$PATH"`）——引擎回放测试与 guest GNU 方言都走 `bash -lc`，macOS path_helper 会把仅前缀的 PATH 降级，必须落在 profile 里 |
| guest python | théâtre venv | théâtre venv（`feuille/.venv/theatre-mac`）自动被选为 guest `python3` |
| 凭据 | `explorateur/config/.env`：组级合并写法 `LLM_<组>_{BASE_URL,API_KEY}`（如 `LLM_FUYAO_*` 覆盖 fuyao-work / fuyao-coding / fuyao-data，逐 slug 变量可覆盖组级）+ `GEMINI_API_KEY`，样例见 `config/env.sample`（密钥永不进仓库/日志） | 同左（本机已有） |
| **症状 → 动作** | **开跑前先解掉这两条，否则每个 wave 都白烧满 10 分钟**：<br/>• preflight 报 `'pnpm' resolves to …\pnpm.CMD` → 门禁会静默毁掉每个候选，装 standalone `pnpm.exe`<br/>• 跑到一半 `HTTP 401 auth failed` → key 与端点不配对（wave1-blocked 即此因：平台 key 打在 `agent.minimax.cn/mavis` 控制台端点上；MiniMax 平台 key 只配 `https://api.minimaxi.com/v1`），核对 `config/.env` 里每组 `LLM_*_BASE_URL` 与 `LLM_*_API_KEY` 是配对的一对<br/>• 跑到一半 `HTTP 400 context window exceeds limit` → 席的窗口声明大于端点真实窗口（wave1r 即此因），现已被 `context_budget` 门禁提前拦住，但端点侧窗口变更仍需改角色 yaml | 同左 |
| harness `link:` 锚 | `deepseek-harness` checkout 在 usine 树上五级目录（dsh-plugin 的 `link:` devDeps 解析锚：`vendor/cordis` + `packages/core/tools`）；缺则 `_seed_guest` fail-closed 直接红（不烧 token） | 同左 |
| 代码同步 | 三棵树（`théâtre/`、本目录、`usine/`）同步到同一血缘。**本地永不 push**，同步机制由用户在仓库外完成 | 同左（Windows wave host 上未 push 的本地 commit 需带过去） |
| usine 门禁 | 开跑前 wave host 与真树各跑一次 `pnpm verify` 全绿（**当前实测基线：无浏览器哨兵下 524 过 / 0 败 / 8 跳**，退出码 0，24s） | 同左，但 macOS 是无浏览器基线：**548 过 / 0 败 / 14 跳**（多出的跳数是浏览器渲染用例，见第 0 节；跳过数对不上基线先查哨兵是否被清） |

### 2. 开跑前自检（全绿才许进 3；théâtre venv，从 `théâtre/` 根目录起跑）

Windows wave host：

```powershell
cd <explorateur>\théâtre
.\.venv\Scripts\python.exe -m pytest tests/                                # 引擎测试
.\.venv\Scripts\python.exe ..\garage\smoke_distribution_fence.py  # 8-gram 围栏
.\.venv\Scripts\python.exe ..\garage\smoke_wave_merge.py          # 合并/排除/exec 位
.\.venv\Scripts\python.exe ..\garage\smoke_usine_hooks.py         # 装配接缝（live-guest 节标 wave host）
.\.venv\Scripts\python.exe ..\garage\smoke_verifier_adapter.py    # Verifier 底座
.\.venv\Scripts\python.exe ..\garage\smoke_guest_env.py           # worktree guest 基座
python ..\garage\probe_env.py                                    # guest 侧 node/pnpm 探针（host python）
```

POSIX dev host（macOS；probe_env.py 仍是 Windows 专用——POSIX 的 guest 工具链探针
由 run_usine 内部预检代跑）：

```bash
cd <explorateur>/théâtre
.venv/theatre-mac/bin/python -m pytest tests/                                # 引擎测试
.venv/theatre-mac/bin/python ../garage/smoke_distribution_fence.py
.venv/theatre-mac/bin/python ../garage/smoke_wave_merge.py
.venv/theatre-mac/bin/python ../garage/smoke_usine_hooks.py        # live-guest 节仍标 wave host 待跑
.venv/theatre-mac/bin/python ../garage/smoke_verifier_adapter.py
.venv/theatre-mac/bin/python ../garage/smoke_guest_env.py
```

### 3. 跑（真波次喊跑才跑）

Windows wave host：

```powershell
.\.venv\Scripts\python.exe ..\garage\run_usine.py --run-name <名> --preflight   # 只读：就绪载荷，不写不烧
# 人工核对载荷（模型阵容 / 端点解析 / 围栏 / 门禁可跑性 / guest 探针）后：
.\.venv\Scripts\python.exe ..\garage\run_usine.py --run-name <名> --execute RUN-USINE-PHASE1-WAVES
```

POSIX dev host（macOS）：

```bash
.venv/theatre-mac/bin/python ../garage/run_usine.py --run-name <名> --preflight  # 只读：就绪载荷，不写不烧
# 人工核对载荷后：
.venv/theatre-mac/bin/python ../garage/run_usine.py --run-name <名> --execute RUN-USINE-PHASE1-WAVES
```

一次 wave 的闭环（细节见 run_usine.py docstring）：预检 → Curriculum 出题 →
Actor 在 guest 改 usine 源码/skills → capture 剪枝（`node_modules`/`dist` 不入归档）→
Verifier 复核 → 记忆蒸馏 → **合并前 `pnpm verify` 门禁**（红即整案丢弃）→ 一候选
一 commit（`X-Theatre-Wave` trailer）+ 每 wave tag `theatre/wave-N` → 绿合并后
`dist/index.mjs` 重建，改进直达 dsh 加载的智能体面 → 下一轮围栏从新 HEAD 重算。

run root（仓库外）落：`events.jsonl`（里程碑）、episode 工件（指令原文/SUBMIT/VERDICT/
outcome）、`merge_report.json`、`endpoints.json`（gitignore 兜底）、终态记忆。

### 4. 时间上限（每次自进化都必须可控）

**一次自进化不超过 25 分钟**（`--run-ceiling-secs` 默认 1500）。这不是建议：
没有时间闸门的自进化跑不起来，也就无法迭代。

上限在 2026-10-19 从 10 分钟提到 25 分钟，依据是**实测**而非口味，两个独立的
阻塞各自被量出来：

- **网关首响应时延**：出题席首响应实测 50.6s / 108.2s / 138.7s / 322s / >300s
  （同档位同输入的方差远大于档位差异，见 `probe_curriculum_effort.py`）。
  180s 切片连一次最差往返都盖不住。
- **门禁**：Actor 必须跑离线门禁（`pnpm verify`，本机绿树实测 24s）外加自己的
  编辑轮次与又一次最差往返。

**上限跟着测量走**：门禁修好后（见第 1 节无浏览器策略）若时延显著改善，
应当重新量并把上限收回去——25 分钟不是新常态，是当前网关条件下的必要值。

- 上限按席切片：curriculum 280s / actor 580s / verifier 420s / merge 120s，加 100s 适配层开销预留 = 1500s，恰好填满上限（实跑通常远低于此：bfs13 用掉 804s）。逐席 `wall_clock_secs` 在装配期被夹紧；**已有的更紧配置不会被放松**（切片是天花板，不是地板）。
- 超时是独立终态 `time_budget_exhausted`（**退出码 3**），与引擎的 `budget_exhausted`（项目预算花完）区分。收口永远落在**完整 wave 边界**，不会中途丢下半合并状态。
- `--time-budget-allow-over` 可放宽 fail-closed，但**必须同时**给更大的 `--run-ceiling-secs`；上限永远记进 `manifest.json`，从不明示。
- 上下文预算门禁（`_context_budget_check`）静态自洽检查各席声明，**不发请求不烧 token**：输出上限 vs 高水位、水位倒置、声明了高水位却无保留策略、输出上限超网关上限。wave1r 的 `HTTP 400 context window exceeds limit` 就是四个席 `ctx_high_water: 0` 长出来的。
- 离线验证：`.\.venv\Scripts\python.exe ..\garage\smoke_time_budget.py`

#### 4.1 整条流水线只有一道硬闸：验证席必须「出版报告」

2026-10-19 的 14 次真跑里，记忆一次都没出来过。逐轮核对后原因收敛到一处，且**与 Agent 的判断力无关**：

引擎语义上，验证席没有报告 = 无判决 = **整波失败**（`explore/phase1_wave.py:418` 抛 `PracticeInfrastructureError`），记忆零提交、候选零合并。bfs13 的 `verify2.json` 里 verdict 是 `unverified`，findings 只有一句 `Verifier Agent ended at emergency/infrastructure status safety_ceiling`——不是格式错，也不是 transport 空转：**23 轮里 19 轮是真 Program 勘察**，席位把 280s 切片全烧完，在最后一步收尾核对上被 `core/loop.py` 的紧急墙钟掐掉，报告从未出版。bfs12 在第 31 轮以同样方式死亡，而它自己的探针早已报出全部测试通过。

于是有三条不直观的结论：

- **失败即终局的不是 FAIL，是「没有结论」。** FAIL 与 PASS 同样进记忆蒸馏（`_commit_branch_memory` 吃的是 `terminal_outcome` + `verifier_report`），只有 PASS 会进 `wave_merge` 合并到 usine（`wave_merge.py:778`）。所以「验证席判 FAIL」也能出记忆，「验证席没判」则什么都不出。
- **charter 明说「没有规定的探针数与轮数」**，勘察可以无限延长，而唯一终点是墙钟。charter 讲了 PASS 的含义，却没讲**预算耗尽等于没有判决**——席位于是理性地继续确认，每一轮确认都记在同一只钟上。这是注记（`_VERIFIER_PUBLISH_NOTE`）要补的那一课。
- **该按「失败的席位」而不是「跑得最久的席位」来分预算。** 连续三次真跑（bfs12/bfs13/bfs15）都死在验证席，而 Actor 席的 780s 切片是全场最宽的。修复把 200s 从 Actor 切片挪给验证席，Actor 席在 `reasoning_effort: low` 下（实测同字节快 5 倍、输出质量未降）仍保有 bfs13 实测 332s 的 1.75 倍余量。

误判风险有下游兜底：wave_merge 在提交候选前会重跑真门禁 `pnpm verify`，所以**假的 PASS 进不了 usine**（只损失一次门禁时间），**假的 FAIL 只损失 merge、不损失记忆**。验证席降档的代价因此是有界的。

### 5. DRS 深度波次（`--phase 2`）

BRS 是并行广度，DRS 是串行深度（论文 RSIAgent §2.2）。DRS **必须在 BRS 之后**，
且有独立 ack token——深度波次绝不会被一条陈旧的 Phase-1 命令行带起来：

```powershell
# 先把 Phase-1 跑完（它产出 phase1/memory/ 这棵记忆树）
.\.venv\Scripts\python.exe ..\garage\run_usine.py --run-name <名> --execute RUN-USINE-PHASE1-WAVES
# 再在它之上加深：
.\.venv\Scripts\python.exe ..\garage\run_usine.py --run-name <名> --phase 2 --preflight
.\.venv\Scripts\python.exe ..\garage\run_usine.py --run-name <名> --phase 2 --execute RUN-USINE-PHASE2-DRS
```

- run root 是 Phase-1 的**同级兄弟**（`phase2/`），Phase-1 的 manifest 与
  tree hash 保持权威，DRS 只复制不搬移。
- **fail-closed**：`phase1/memory/` 为空时拒绝跑 DRS——空记忆上的深度波次
  退化成第二次广度波次，证明不了深度递归。
- 结果载荷带 `drs_delta`：基线/终态 tree hash、文件数增量、`memory_changed`。
  论文 §3.2 指出增长包含收缩（整合记录会替换多条旧记录），所以判据是
  **tree 变化**，不是体积增长。
- DRS **不合并进 usine**：串行核发的是 `PROJECT_CLOSED` 而不是
  `PHASE1_WAVE_COMPLETED`，wave-merge 的事件入口不触发。DRS 的产出是记忆，
  不是代码。

#### 5.1 DRS 有自己的运行上限，而且它的切片必须真的生效

DRS 不是 Phase-1 的同一份活：出题席做的是**复盘**（不是出波），Actor 面对
的是**更深的任务**（记忆已存在，要往深里钻），记忆相位要重写那棵记忆。
两者共用一套切片必然错配。

实测（2026-10-20，四次 DRS）给出的席位成本：出题复盘 152s、Actor 805s
（31 轮、四份交付物）、验证 ~150s、记忆 277s——**零余量就已经 1384s**，
1400s 的席位预算根本放不下。所以 DRS 有自己的上限（`time_budget.
DRS_RUN_CEILING_SECS`，当前 2100s）与自己的切片计划
（`time_budget.DRS_SLICES`：400/900/280/320/20 = 1920s）。Phase-1 仍是
1500s / 280-580-420-120，两条路径互不影响。

两个反复踩到的坑，**都该被冒烟钉住而不是靠真跑发现**：

- **切片是天花板，不是地板。** `apply_slices` 只会把席位**收紧**到切片，
  绝不会放松它自己声明的 `wall_clock_secs`。所以一个席位自己的配置如果比
  计划切片更小，它会静默按那个更小的数跑——计划里的分配就是一句空话。
  实测踩了两次：出题席自声明 280s 把 DRS 的 400s 夹回；Actor 席自声明
  780s 把 DRS 的 900s 夹回。`smoke_time_budget` 现在用**真实角色配置**断言
  每个计划切片都是**实际生效**的墙钟。
- **DRS 的验证席接线与 Phase-1 不同。** 串行核的 `agentic_verifier_cfg` 要
  的是**验证席控制档**（它用 `agentic_verifier_config` 指向验证 Agent 档），
  传成 Agent 档本身会在 Actor 烧完整轮预算之后才炸：
  "Phase-1 Agentic Verifier control config is missing"（实测 1158s）。
  现在有 `_check_drs_wiring()` 在**开跑前** fail-closed。

## 二、怎么校验自进化产物

三层验收，全部机械可查；**SKIP 不是 PASS，编出来的数据比没有数据更坏**。

### L1 合并完整性（跑完立即，真树上）

- `merge_report.json`：merged 计数、gate exit 0、tag / base 指对；
- delta **不含** `node_modules/`、`dist/`、`*.tsbuildinfo`（capture 剪枝 ↔ merge 排除
  两头对称——一头改另一头必改，smoke_wave_merge 有对应用例）；
- exec 位保留：`bin/feuille.js` 仍 100755（锚点用例在 smoke_wave_merge）；
- 每候选一 commit、带 `X-Theatre-Wave` trailer；每 wave 一 tag `theatre/wave-N`；零 push。

### L2 门禁层（真树上 `pnpm verify`）

- 全绿，对照基线：Windows wave host（无浏览器哨兵，2026-10-19 起）
  **524 过 / 0 败 / 8 跳**；macOS（同样哨兵下）**548 过 / 0 败 / 14 跳**——
  跳过名单只许诚实新增，不许把红的算成跳；
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
- **零平台发布/登录**：VM 门面、guest-home `USERPROFILE`（Windows）／`HOME`（POSIX）
  钉死、offline-only 门禁三层防线。
- **真波次喊跑才跑**；一候选一 commit；每 wave tag；**永不 push**。
- **SKIP 不是 PASS**；跑不了的项如实标「wave host 待跑」。

## 四、文档地图

| 文档 | 角色 |
|---|---|
| [`run_usine.py`](run_usine.py) docstring | 装配契约权威全文（13 条）+ 双宿主就绪清单 |
| [`distribution-usine.md`](distribution-usine.md) | 给 Curriculum 的目标方向（改进面许可 + 护栏） |
| `config/roles-usine/*.yaml` | 座位表（模型阵容 fail-closed 校验） |
| [`runs/`](runs/) | 真跑现场归档（含首测事故与修复全套） |
| [`../théâtre/ARCHITECTURE.md`](../théâtre/ARCHITECTURE.md) | 引擎机制与图表（v1 基线） |
| [`../théâtre/ADAPTATION.md`](../théâtre/ADAPTATION.md) · [`PROVENANCE.md`](../théâtre/PROVENANCE.md) · [`PORTING-NOTES.md`](../théâtre/PORTING-NOTES.md) | v1 偏离记录 / fork 纪律 / 跨平台病根 |
| [`../usine/migration/README.md`](../usine/migration/README.md) | usine TS 迁移与 P9 改造收口史 |
