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

#### 3.1 铺开闸：别让每一波都落在同一个包里

**为什么有这道闸**：到 2026-10-20 为止，三次合并进仓库的改进**全部**落在`packages/dsh-plugin/` 一个包里，生产线本体（core / karaoke / poster / poetry /storyteller / copy / bgm / publish）**零改动**。查下来不是 Agent 偷懒——出题席的brief 当时写着「in menu target A, B or C ONLY」，把它锁死在了 dsh-plugin 那三个文件上。规格造成的单一化，机械地治：闸从 git 历史里读「已合并波次触及了哪些包」，把**连续重复的包列为本波禁入**，把**从未被碰过的包列为冷区（要求本波必须落在其中之一）**。

- 策略在 [`config/spread.json`](config/spread.json)：冷区窗口 3 波、连续重复 2 次即禁入、
  冷区优先级 `required`（必须落在冷区里，不是「优先考虑」）、包重要度顺序
  （core > karaoke/poster/poetry/storyteller > copy/bgm/publish > cli/gate > dsh-plugin——
  dsh-plugin 排最后，因为它已经被反复做过）。
- 约束在**装配期**追加进出题席的 `system_extra`，措辞是闭集的 MUST / MUST-NOT，
  点名目录、不写「以及其它」——与 DRS 那套「brief 必须有上界」是同一个原则。
- **只动 Phase-1 的出题席**：Phase-2（DRS）有自己的出题席，它的工作是复盘并交一份
  有上界的 drill，不是选题铺开。
- 第一次运行（还没有任何合并历史）优雅降级：不追加任何约束，不报错。
- 铺开状态是 **HEAD 派生的**，所以**不进 manifest**（manifest 是 resume 的逐字比对门，
  而 HEAD 会随合并移动——放进去每次 resume 都会拒绝自己）。它落在同级的
  `spread_state.json` 里。

#### 3.2 端点时延预检：切片吸收不了波动
网关首响应时延实测在 50.6s / 108.2s / 138.7s / 322s / >300s 之间跳，而出题席切片是 280–400s。**切片吸收不了波动**——照那样开波，运气差就整波烧光。

- preflight **只读、零成本**：不发任何 LLM 请求（这是 preflight 的老规矩），只读**历史
  run root 里引擎已经记下的每席墙钟**，与本波的计划切片比。
- 历史为空（第一次跑）→ 判「无历史」，不拒绝，载荷里写 `latency_history: "none"`。
- 历史里某席的 max 超过计划切片的 60% → 判**高时延风险**，**默认拒绝开跑**，报出
  哪一席、历史 max、计划切片、以及怎么办（降 `reasoning_effort` / 换端点 / 放宽
  `--run-ceiling-secs`）。
- `--allow-high-latency` 可以放行，但风险会**写进 manifest**——被放行却没被记录的风险，
  和根本没检查过的风险读起来一模一样。
- 历史数据坏了（坏 JSON / 缺字段）按 fail-closed 处理，**不当成 0 秒**。
- 离线验证：`python ../garage/smoke_latency_budget.py`（40 项）。

run root（仓库外，与本仓库**同级**）落 `garage-result/`（默认 `--root`）：`events.jsonl`
（里程碑）、episode 工件（指令原文/SUBMIT/VERDICT/outcome）、`merge_report.json`、
`endpoints.json`（gitignore 兜底）、终态记忆。harness2 线的产物另落 `garage-ii-result/`，
两线不混放。

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
  `PHASE1_WAVE_COMPLETED`，wave-merge 的事件入口不触发。DRS 的默认产出是记忆，
  不是代码——但候选也可以显式合进仓库，见 §5.6。
- 下一波要站在**加深后**的记忆上：见 §5.8（`--memory-seed`）。

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

#### 5.2 DRS 的 brief 必须有上界，否则切片再大也救不了

第五次 DRS（bfs16g，2026-10-20）把前四次"看起来像切片不够"的假象拆穿了：
死因不是切片小，是**任务无界**。

- DRS 出题席写的 brief 是开放集：「这个**类别里每一条**拒答消息都要改」、
  「顺手适配任何引用旧措辞的测试」、「每条改过的消息都要写旧文本/新文本/
  文件/函数/钉它的用例名」。
- Actor 忠实地去搜那个集合：17 轮侦察（探 guest 路径、dump 记忆树、遍历
  dsh-plugin、逐段 dump 两个测试文件），**一轮都没落到编辑**。
- 900s 墙钟到点 → `safety_ceiling` → `drs_delta.memory_changed = false`，
  记忆树与 Phase-1 基线**逐字节相同**。

结论：**切片能吸收波动，吸收不了无界的任务**。上界必须写在 brief 里，而 DRS
是唯一需要另一份 brief 的相位，所以 DRS 有自己的出题席
（`config/roles-usine/curriculum-drs.yaml`），Phase-1 那份一字未动。

DRS brief 的上界（`system_extra` 里逐条钉死）：

- drill 只碰**一个**产出源文件 + **一个**测试文件，交付物**至多两个**；
- 禁写开放集措辞（「每一条」「所有」「任何其他」）；
- 点名文件与实例，**不许**让 Actor「去找到底在哪构建」；
- 只改**一个**消息族，不是一个类别；
- 报告是**表格**：每条一行、**至多 12 行**、不许写散文；
- **加深一条已存在的记忆记录**（点名是哪个文件），否则记忆相位无事可写，
  tree 原样回来，DRS 等于什么都没发生。

Actor 席另加一道**兜底**（`SCOPE DOWN, DO NOT SEARCH`）：万一 brief 还是
写宽了，Actor 只准挑**一个**具体实例改完、钉完、交作业，不准去搜全集
——「改窄并完成」比「改全但没交」值钱，因为**只有交上去记忆才会变**。

三处都被冒烟钉住（`smoke_time_budget`）：Phase-2 选 DRS 出题席、Phase-1
仍用广度席（`test_drs_seat_selection_is_phase_scoped`）；brief 的每条上界
都在（`test_drs_brief_has_a_closed_scope`）；DRS 接线拒绝广度席
（`test_drs_wiring_is_sound`）。另外 `smoke_distribution_fence` 的
`role_yaml` 期望值从 5 改成 6——**新增受审计面必须是刻意动作**，而且 DRS
那份 brief 自己也进围栏，它的话术不能漏进 distribution。

#### 5.3 DRS 的 guest 必须真的拿到仓库：种子会被 reset 抹掉

第 6 次 DRS（bfs16h）跑到一半才确诊的**最硬的一条**。

- 出题席的 brief 这次是有上界的（一个源文件、一个测试文件、报告至多 12 行、
  点名要加深的两条已有记忆记录，禁用措辞 0 命中），出题席 6 轮 / 220s 收工。
- 可 Actor 依然找不到代码：它的 `/home/user/evolution_project` 里**只有出题席
  staged 的 2 个 fixture**，没有 `package.json`、没有 `packages/`、没有源码。
  它探 guest 路径、探 pnpm store、探**别的 run 的旧 guest**（找到的是上一轮
  的 `tools.ts`，字节数都不是当前 HEAD 的）——900s 墙钟就在找仓库里烧光。

因果链（三段，每段都能独立查）：

1. 建机时 `_harness_staging_vm_factory(seed=True)` 确实推了种子；
2. 但串行核在席位之间调 `_fresh_vm` → `env.reset()`，**把 guest 还原成快照，
   种子连同仓库一起没了**；
3. 补种的那道接缝只认 `phase1-project-*` 这个 capture key，而 DRS 的
   fixture capture key 是 `ep<N>-fixtures`——**接缝一次都没被触发**。

Phase-1 走的是另一条接缝，所以 Phase-1 一直有仓库；DRS 五次全死在这，记忆树
始终与基线逐字节相同。

修法（都在适配层，不动引擎）：

- `_seeded_capture` 的接缝判据扩到 DRS 自己的 key（`_is_fixture_capture_key`），
  于是 DRS 的 capture 变成 scaffold ∪ baseline，replay 交给 Actor 的就是真仓库；
  候选 capture 与被拦草稿仍然不补种。
- 新增 `_baseline_guarded_replay`：replay 之后验 guest 里确实有基线标记
  （`package.json` + `packages/dsh-plugin/src/tools.ts`），缺了就 **fail-closed**
  ——接线缺口该付几秒，不该付三十分钟。
- 出题席的「自有根里不许有代码文件」自检不受影响：种子落在出题席**发布之后**。

#### 5.4 DRS 不合并，所以它不需要一棵干净的工作树

`_assert_preconditions`（脏树 / 暂存区 fail-closed）是**给 merge 的**门：
波次提交会把脏内容一起吞进去。DRS 根本不合并（串行核发 `PROJECT_CLOSED`），
而它的种子是 `git archive HEAD`，**一个字节都不读工作树**。

所以 Phase-1 保留严门，Phase-2 改走 `_assert_seedable`：只要求 HEAD 可解析，
并把工作树状态**记进 `seed_source.json`**（不是记进 manifest——manifest 是
resume 的逐字比对门，HEAD 会随波次合并而移动，放进去 resume 就废了）。
实测：并发会话正在改 `usine/docs/record.md` 时，DRS 该跑得动、Phase-1 该拦住。

#### 5.5 DRS 跑通了（bfs16i，2026-10-20）：`memory_changed: true`

第七次尝试，第一次拿到深度波次的真信号。

- **记忆树变了**：`21c6846c…` → `56b3afb9…`（用引擎自己的 `_memory_tree_sha256`
  重算过，不是读载荷）；3 个文件全改，7290B → 8410B，新增 0、删除 0。
- **用时 1650.6s / 2100s**，`over_ceiling: false`；status `budget_exhausted`
  （项目预算用完，是边界不是失败）。
- 出题席 4 轮（首响应撞了 120s 网关尾巴，393s / 400s 切片内收工）；
  Actor 26 轮（墙钟用掉 620s / 900s 就交了 `STATUS: SUBMIT`）；
  验证席 14 轮 100s 出版 `VERDICT: PASS`（`doubts: none`）；
  记忆相位 5 轮 + 整合段 5 轮。
- **改了什么**：`packages/dsh-plugin/src/tools.ts` 里"审批被拒/取消"那一条
  拒答卡（`审批结果：${outcome}——未提交。`）改写成对人说话的话——请求没被批准、
  什么都没提交没排队没生成、下一步该怎么做；`plugin.test.ts` 补两条钉子
  （rejected / cancelled 各一条，逐字匹配新卡 + 断言 status 未变 + 无 task_id）；
  报告 `WORDING_CHANGE_REPORT.md` 就 1 行 4 字段。门禁 `pnpm verify` exit 0，
  42 个测试文件 / 527 通过 / 8 跳过。
- **记忆被加深并纠正**（不是追加）：
  - `usine-monorepo.md` 现在写明 `config.publish === true` 的字面量在
    **index.ts**、不在 tools.ts（这是本轮一个失败探针换来的纠正）；
    还记下"`await approval.request(` 只算 await 形式才是 1"、
    以及 parity:230 逐字钉了 `审批结果：rejected` ——**今后任何改写都必须保留
    `（审批结果：${outcome}——未提交。）` 这个括号回声**。
  - `verification-discipline.md` 标题变成 "PASS ×2"，新增两条纪律：
    探针失败先归类（针选错 / 通道错 / 对象错；**每个探针的 needle 必须来自
    打印出来的源码证据，不能来自任务散文或记忆**）；冻结套件逐字钉着旧措辞
    而任务要求新措辞时，**用新措辞开头 + 保留旧结论作括号回声**来同时满足。
  - `environment-quirks.md` 把"handoff 跨相位不持久"的结论**纠正**成
    "两个方向都不可靠"（三个数据点：10-19 没了；10-20 过了蒸馏还在、到整合
    相位又没了）。

**怎么验的**：`garage/verify_drs_run.py --run-root <lineage>`——它用引擎自己的
哈希函数重算终态与基线两棵树、重算逐文件 manifest、查载荷的 `memory_changed`
与 `files_added` 是否诚实，并把出题席真正发布的 brief 读出来判上界（开放集
措辞？恰好一个源文件 + 一个测试文件？报告 ≤12 行？）。对第 5 次失败跑
（bfs16g）它是反例：9 passed / 5 failed，如实点出"记忆树没变""brief 带开放集
措辞""brief 没有报告上界"。

**验收时的坑：真树门禁会因为桌面浏览器开着而变红。** 宿主上此刻有 8 个
chrome + 5 个 msedge 进程，它们抢走渲染单例，那 8 个浏览器套件于是从「设计内
SKIP」翻成 fail——实测 `pnpm verify` 变 11 failed / 522 passed，报错自己写着
"大概率被已开着的桌面浏览器抢占（singleton 移交）"。把 `FEUILLE_BROWSER` 指到
一个不存在的路径（平台的 `browser()` 找不到就返回 null，绝不静默换人）再跑，
就是 **42 文件 / 525 通过 / 8 跳过 / exit 0**——与波次验收时的数字逐项相同。
**别把这种红当成改动引入的回归**：先复跑一次再下结论。SKIP 不是 PASS，但
「被环境抢占而 fail」和「因为跳过而没验证」是两回事。

**这一轮真正的三个修复**（前六次全败的原因链）：
1. brief 要有上界（§5.2）——切片吸收不了无界的任务；
2. guest 必须真的拿到仓库（§5.3）——种子被 reset 抹掉、capture key 不匹配，
   Actor 满墙钟找代码；
3. DRS 不该被 merge 门拦住（§5.4）——它不合并。

#### 5.6 DRS 的改进要看得见：`--merge-drs` 与 `merge_drs.py`

DRS 的**记忆**产出已经进仓库，DRS 的**候选**（那一轮真改出来的代码）却没有：它过了验证席的 PASS、过了 guest 里的门禁，却因为串行核发的是 `PROJECT_CLOSED` 而不是 `PHASE1_WAVE_COMPLETED`，永远不会被 wave-merge 的事件入口捞走。于是"DRS 改进了 usine"这句话没有任何产物能证明——仓库里看不出任何变化。

- `run_usine.py --merge-drs`（**Phase-2 专有**，与 Phase-1 互斥，误用 fail-closed）：跑完 DRS 顺手把候选合进仓库。合并走的是**广度波次同一套机器**——delta、漂移闸、真树门禁、commit、tag，所以一条 DRS 改进进仓库的规矩和其余所有改动一样。合不进去不吞：结果载荷写 `drs_merge.ok=false` + 原因，进程退出码 **4**（"跑成了但没合进去"和"跑成了并合进去了"是两个不同的claim，不能混成一句"DRS 成功"）。
- `garage/merge_drs.py --run-root <phase2 目录>`：给**已经跑完**的 DRS 补合（当时门禁红了、事后才想看、想重做一次）。`--plan` 是只读预览：报 delta 和**合并会得出的判定**（fresh / already_merged / drift），不碰仓库、不跑门禁、不建 commit 与 tag——"会落什么"应该在付门禁时间之前就是事实。
- 引擎自己的 `episodes/<ep>/outcome.json` **一个字节都不改**：它没有 `wave_index` / `project_id`（那是 Phase-1 波次的形状，DRS 是串行的一个 project）。合并另写一个兄弟文件 `merge_outcome.json` 补上这两个字段，wave 读取器读它。
- **命名不撒谎**：tag 是 `theatre/drs-1`（不是 `theatre/wave-1`），commit scope 是 `theatre-drs(drs-1)`，trailer 是 `X-Theatre-Drs: 1`——没有任何一处把 DRS 说成 wave。合并记录的 `source` 字段写 `drs_phase2_episode`，一眼能看出这条改动来自哪。

#### 5.7 行尾不是内容变化：漂移闸必须比 git 宽一点

合并前有一道漂移闸：工作树里每个被改动的路径，必须**要么**等于基线（还没合）**要么**等于候选（已经合了），否则判 `drift`、**整条候选**跳过。

只比原始字节时，这道闸会在本机**误杀**。仓库的规范形式是 LF blob（`core.autocrlf=input`：入库时折叠 CRLF，签出时不展开），所以工作树里的文件可以带着 CRLF，而 **git 仍然认为它是干净的**（index 条目缓存的是工作树文件的 stat，blob 折叠成 LF）。

实测（2026-10-20，bfs16i 的 DRS 候选）：`packages/dsh-plugin/src/tools.ts` 工作树 28831B / 558 处 CRLF，基线 blob 28273B——原始字节不等、**折叠后逐字节相等**。只比原始字节 → 判 `drift` → 一条过了验证席、过了门禁的改进被**静默跳过**，报告里只留一句"工作树既不匹配基线也不匹配候选"。bfs16 当初能合，纯粹是因为合并器刚把 LF 写进过工作树；并发会话一次 checkout/stash 就把它还原成 CRLF。

修法：漂移闸同时比**原始**和**折叠 CRLF→LF** 两个 sha（`_normalized_sha`），原始相同**或**折叠后相同都算匹配。折叠只原谅行尾，不原谅内容——工作树真的既不匹配基线也不匹配候选时，仍然判 `drift`、仍然跳过。

踩坑记录也留在这里：**复现这个现象时，`core.autocrlf` 必须在提交那一刻就设对**。git 把"入库时的转换过滤器"缓存进 index 条目，事后改 config 不生效——所以"先提交再改 config 再改行尾"会得到一个 ` M` 的脏树，而真实仓库（提交时就是 `input`）是干净的。冒烟照真实情形复现（带 CRLF 写入 → `git add` 刷新 index stat → 树读起来是干净的），见 `smoke_wave_merge` 的 `crlf:` 组。

#### 5.8 下一波要站在加深后的记忆上：`--memory-seed`

「再跑一遍会不会更好」的前提是**第二遍看到的是第一遍学到的东西**，而不是从零重来。引擎本来就既读又写 `lineage/memory`（出题席读它、Actor 拿着它干活、分支蒸馏后回灌），所以预置这棵树**不需要改引擎**：把记录拷进 run root 的 `memory/` 就行。

- `--memory-seed <目录>`：这次波次从这棵记忆树起步。Phase-1 默认从空树起步；给了种子就是"在上一波的收获上再跑"。
- Phase-2 默认以 `phase1/memory/` 为基线；给了 `--memory-seed` 就**换基线**——这就是"第二次 DRS 加深的是第一次 DRS 加深过的那棵树"。`drs_delta` 的基线也跟着换（`baseline_dir` 写进载荷），所以"长了多少"仍然答得上来。
- 种子是**拷贝**，不是链接也不是搬移：Phase-1 的 manifest 与 tree hash 必须保持权威、可重复读。
- 种子目录必须存在且非空，否则 fail-closed（空记忆上的深度波次证明不了任何事）。
- 预置在**引擎跑之前**完成，引擎自己那个 `mkdir(exist_ok=True)` 不会动已放好的记录。
- 这条接缝有专测（`smoke_memory_seed`，9 项）：引擎自己的 `_read_memory_tree` 读到的就是预置的那几条、种子是拷贝不是链接、重种会整棵替换（不留上一次的陈记录）、空或不存在的种子目录在开跑前 fail-closed、`--merge-drs` 在 Phase-1 上被拒。

实测（2026-10-20，bfs17）：第二波站在 bfs16i DRS 加深后的记忆上（种子 8410B），754.7s/1500s 跑完并合并出新提交 `6e8665f18e` + tag `theatre/bfs17-1`（真树门禁 exit 0 / 26.4s），记忆 8410B→11460B 三文件全变。因果链可独立复查：种子记忆里已有「`usine_video_generation` 的 4 条拒答分支清单 + (a)(b)(c) 三点标准」，出题席据此立题 `vg_refusal_words`，把 wave-1（分支1）与 DRS（分支4）各改一条之后剩下的分支2/3 也改写为三点全中，`refusal-audit.md` 里显式记着「本 wave 沿同一标准」——第二波不是从零重来，而是站在第一波的收获上继续长。

## 二、怎么校验自进化产物

三层验收，全部机械可查；**SKIP 不是 PASS，编出来的数据比没有数据更坏**。

### L1 合并完整性（跑完立即，真树上）

- `merge_report.json`：merged 计数、gate exit 0、tag / base 指对；
- delta **不含** `node_modules/`、`dist/`、`*.tsbuildinfo`（capture 剪枝 ↔ merge 排除
  两头对称——一头改另一头必改，smoke_wave_merge 有对应用例）；
- exec 位保留：`bin/feuille.js` 仍 100755（锚点用例在 smoke_wave_merge）；
- 每候选一 commit、带 `X-Theatre-Wave` trailer；每 wave 一 tag `theatre/wave-N`；零 push。
- **规范同步闸**：改了被规范文档管辖的代码，规范必须同批更新，否则整条候选被拒
  （`spec_sync_rejected`，报告里点名规范路径与代码路径）。规范文档自己声明它钉住什么
  ——文档里的 ` ```anchors ` 围栏块（单一事实源，注册表 `config/spec-sync.json` 只做
  路由）。存量的漂移（合并前就与代码对不上）**不**否决候选，只记 notice——闸只管
  本次候选造成的漂移，否则一道失效的闸会把整条流水线卡死，而卡死的闸没人看得见。
- **门禁跳过数进报告**：门禁输出里的 `Tests N passed | M skipped` 被解析出来记进
  候选条目与提交信息。**SKIP 不是 PASS**，报告与提交都如实写；解析不出来记 `null`
  而不是 0（纪律 8：没数据留 null 不填 0）。
- **记忆快照进仓库**：波次收口时把终态记忆树抄进 `garage/memory-snapshots/<unit>-<NNN>/`
  并单独提交（`X-Theatre-Memory` trailer），manifest 记引擎自己的树哈希。记忆是唯一
  跨波次传递的东西，它必须能被 review、能 diff，而不是只活在仓库外的 run root 里。
- **锚点以 commit 为准**：`merge_report.json` 的 `anchors` 段写明 primary = commit
  sha，tag 标 `portable: false`。tag 只存在于创建它的那个 clone——本工程「永不
  push」，代码靠人工同步，而**同步带提交不带 tag**（实测：本机 clone 的
  `git tag -l` 是空的）。回滚请用 commit sha 或 commit body 里的
  `X-Theatre-Wave` / `X-Theatre-Drs` trailer。

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

### L2.5 健康分：门禁说「没坏」，它说「更好了」
门禁只能证明没把产线改坏。**「这一波让产线好了多少」此前没有任何数字回答**——官方 grader 在本环境不可用（`official_evaluator_calls: 0`），于是自我进化实际只剩下「防退化 + 刷验证席 PASS」。2026-10-20 起合并器多了一道**产线健康分闸**：

- 指标在 `usine/packages/eval`（离线、零网络、零浏览器、零额度，确定性）：v0 三个指标
  ——排版装不下事件数、词级时间轴对齐误差、语种矩阵通过率。**算不出来的指标一律留
  `null` 并写明为什么**（纪律 8：没数据留 null 不填 0；编出来的数据比没有数据更坏），
  不拿别的判据冒充。
- 合并器在应用候选**之前**量一次基线、应用**之后**量一次候选，逐指标比：有指标变坏
  → 整条候选作废（`health_rejected`），报告里点名是哪个指标。
- 样本不足（<5）不排名、`null` 一律 not-comparable——**不知道 ≠ 退化**。
- 健康分工具自己坏了**不拦**合并（真门禁与验证席还在），但会记成 notice——闸缺席与
  闸失效是两回事，后者才危险。

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

**其中第 1 步与「不烧 token 的那几节」已经常驻**：合并器在门禁绿之后会自动跑[`smoke_agent_surface.py`](smoke_agent_surface.py)（dist 新鲜度、inject 与 src 逐字一致、工具族数量、`__require` 垫片形状、仓库里的 loader 产物没漂路径），红即整条候选作废（`l3_rejected`）。真正需要 dsh 宿主的 boot 与首任务真跑仍是人工工序（第 3–5 步）——**SKIP 不是 PASS**，那几节不许充作覆盖。

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
| [`spec_sync.py`](spec_sync.py) | 规范同步闸：规范文档自带 `anchors` 围栏，代码改了规范必须同批更新 |
| [`spread.py`](spread.py) + [`config/spread.json`](config/spread.json) | 铺开闸：连续同包禁入 + 冷区清单 |
| [`latency_budget.py`](latency_budget.py) | 端点时延预检：只读历史、零成本、fail-closed |
| [`runs/`](runs/) | 真跑现场归档（含首测事故与修复全套） |
| [`../théâtre/ARCHITECTURE.md`](../théâtre/ARCHITECTURE.md) | 引擎机制与图表（v1 基线） |
| [`../théâtre/ADAPTATION.md`](../théâtre/ADAPTATION.md) · [`PROVENANCE.md`](../théâtre/PROVENANCE.md) · [`PORTING-NOTES.md`](../théâtre/PORTING-NOTES.md) | v1 偏离记录 / fork 纪律 / 跨平台病根 |
| [`../usine/migration/README.md`](../usine/migration/README.md) | usine TS 迁移与 P9 改造收口史 |
