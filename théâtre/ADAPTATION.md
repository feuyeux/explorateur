# ADAPTATION — théâtre v1 × usine：实现相对设计稿的偏离记录

状态：v1 实现完成（2026-10-16）。本文件只记**实现相对设计稿的偏离与
裁定**，是 v1 当时的记录——其中「usine 保持 Python」「uv 门禁」等表述随
P7 TS 迁移与 P9 真作用力改造（2026-10-18）失效：现行门禁为 `pnpm verify`，
现行机制与运行手册见 [../benchmarks/usine/README.md](../benchmarks/usine/README.md)。
机制、图表与装配次序见 [ARCHITECTURE.md](ARCHITECTURE.md)；跨平台
补丁清单见 [PROVENANCE.md](PROVENANCE.md)；POSIX 病根见
[PORTING-NOTES.md](PORTING-NOTES.md)。本文件的设计稿形态（v0）在 git 历史。

## 0. 目标

对 `explorateur/usine`（feuille，多语种视频生产可复用层）执行 RSI：Curriculum
提出改进波次，Actor 在 worktree guest 里干活，Verifier 独立验证（usine 门禁
全量绿），波末合并回真树。**第一阶段 usine 保持 Python**；全量 TS 迁移
（dsh 插件）是 v1 之后的独立马拉松。

## 1. 模型阵容（2026-10-16 用户裁定 → 实现落位）

约束：**不用 M3 以下的模型**（M2.7 / M2.7-highspeed 不好使，弃用）；
**fuyao 的 work / coding 两个可用**（fuyao-data 未获批）。实现落位与设计稿的
座位表一致，**视觉接法偏离设计稿**（见下表注）：

| 座位 | 模型 | 视觉接法 |
|---|---|---|
| Actor | `MiniMax-M3` | 原生视觉（`vision_model` 留空） |
| Memory Actor | 同 Actor（`MiniMax-M3`，代码强制同模型） | 同上 |
| Curriculum | `fuyao-work` | 视觉 Look 座位 = `MiniMax-M3`（fuyao 系纯文本） |
| Agentic Verifier | `MiniMax-M3.1-Flash-Preview` | 原生视觉（`vision_model` 留空） |
| 升档 Actor | `MiniMax-M3.1-Flash-Preview` | 原生视觉 |
| 升档 Verifier | `MiniMax-M3`（cross-model：升档裁决禁止自审） | 原生视觉 |

- **视觉偏离说明**：设计稿写「`vision_model: MiniMax-M3`（actor 用）」——
  把视觉当外挂座位。实现把 Actor / Verifier 的 `vision_model` **留空**：M3 与
  M3.1-Flash 原生收图，外挂座位会把 Look 引到第二模型；`_check_lineup` 对此
  fail-closed（"must use native vision"）。Curriculum 座位相反——fuyao-work
  纯文本，其视觉座位必须显式挂 `MiniMax-M3`。
- **fail-closed 阵容校验**（`run_usine._check_lineup`）：座位逐条断言 +
  `ALLOWED_MODEL_SLUGS = {MiniMax-M3, MiniMax-M3.1-Flash-Preview, fuyao-work,
  fuyao-coding}` 白名单 + 升档对按 `core.loop.escalation_cfg` 同式复算钉死；
  出格即拒，一分钱不烧。
- 备胎：Verifier 若 flash 表现不稳 → `fuyao-coding`（纯文本，256k ctx /
  64k out；届时 Verifier 的 look 降级为探查文本）。

### 端点接线（零密钥落仓库）

两个网关都实测支持 OpenAI `/chat/completions` 协议：

- minimax：`https://agent.minimax.cn/mavis/api/v1/llm/v1`（`~/.minimax/config.yaml`
  → `provider.minimax.options.{baseURL,apiKey}`）
- fuyao：`http://fuyao-ai-gateway.xiaopeng.link/v1`（同文件
  → `custom_provider.fuyao.options.{baseURL,apiKey}`）

实现（相对设计稿的收窄）：`_resolve_endpoints` **在内存里**按 needed slug 集扫
`provider.*` 再 `custom_provider.*`，任一 slug 缺凭据或字段不齐即 fail-closed；
`endpoints.json` 写**仓库外 run root**（不是设计稿的"临时文件"——run root
整条血缘共享一份），经 `RSIAGENT_LLM_ENDPOINTS_FILE` 注入；explorateur 根
`.gitignore` 对 `endpoints.json` 兜底。密钥永不进日志、manifest、preflight
载荷。`tests/test_llm_endpoint.py` 覆盖：无映射→默认 OpenRouter 逐字节不变，
坏/缺文件 fail-closed 回默认。

M3.1-Flash-Preview 思考 forced_on——请求 `reasoning.enabled=false` 可能 400，
`chat()` 的「出错即丢可选参数重试」自愈。

## 2. 角色配置（不改 fork，只给路径）

适配层自带 `config/roles-usine/` 五份 YAML（explorateur 层，不进 théâtre 树）：
`actor-usine` / `verifier-usine` / `target-usine`（control 座位）/ 
`curriculum-usine` / `verifier_escalation-usine`；memory 沿用 actor 配置。
`_load_roles` 在加载期强制 Phase-1 practice 不变量（Agent-owned practice：
`agent_decided_stop` + `practice_mode` + 非 `independent_verify` +
`max_resumes == 0`）；control 必须 candidate-only + `rollback_mirror` + 隐藏
Actor 记忆。要点：

- 全部 `provider_order: []`（OpenRouter 路由语义对这些网关无意义）
- `script_timeout` 用引擎默认 600s，实测够用，不改 YAML
- Actor `max_iters` / `wall_clock_secs` 按波次预算收紧

## 3. Corpus：从「每波 fixtures」到「全程固定」

设计稿（v0 §4）让 Curriculum fixtures 携带项目简报、按波生长。**实现撤回
per-wave corpus 增长**：corpus = distribution 的 shingles，**整条 run 固定**。
理由（`run_usine.py` 模块注记）：stock Phase 1 把每个先前 project 的文本
**逐字**回灌后续 Curriculum prompt（`previous_wave_outcomes` →
`_outcome_text`），而 `_audit_prompt` 只授权目标方向——中途扩 corpus 必然在
下一波的**第一个授权段**触发泄漏隔离。因此：

- fresh run 从 distribution 构建 corpus；resume 先合并 pending waves，再要求
  corpus 与「从 distribution 重建的副本」**逐项相等**（等值校验拒漂移）。
- `extend_corpus` 在 usine_hooks 里保留，供操作者显式驱动；编排器永不中途扩。

## 4. 种子：加性（S1），不是整树替换

`_build_seed`：`git archive HEAD -- <usine 前缀>`（tracked + committed only），
成员名重写为 `evolution_project/<rel>`；目录成员丢弃；非常规成员（symlink——
Windows guest 无忠实语义）跳过并计数；gzip `mtime=0` → sha256 幂等；落
run root `baselines/seed.tgz` + manifest（原子写）。注入点在**捕获接缝**：
每波第一个 `phase1-project-*` 捕获时推送 seed → guest 内做 size + sha256
双重验证 → 解包到 `/home/user` **不擦除**（Curriculum 骨架的任务性附加文件
保留，baseline 赢文件碰撞）——捕获下来的 fixture（即合并基线）= 骨架 ∪ 基线。
candidate 捕获（`phase1-candidate-*`）与 blocked-draft 捕获**永不种**。
干跑实测：197 成员。

## 5. 门禁配方

- **guest 内（Actor 段）**：`UV_PROJECT_ENVIRONMENT="$HOME/.venv-gate" uv run
  feuille verify`——uv 环境钉在树外，`.venv` 与缓存永不进捕获的工作树
  （actor 系统提示补丁把这条配方写进段说明）。
- **合并（wave_merge，跑在真 usine 树）**：`gate_argv` **强制显式**
  （默认 `uv run feuille verify`）、`gate_timeout` 1800s。合并门禁会在
  usine 目录建未跟踪 `.venv/`（无害，`uv` 默认行为）；`UsineMergeConfig.
  gate_env` 旋钮可重定向，run_usine 的 CLI 未暴露——按需再开。
- 基准（实测）：真树全量 21 套 ≈ 46s；干跑里 actor 门禁 53–56s、合并门禁
  44.4–53s。

## 6. 围栏与审计：静态真载荷 + 运行时空转的诚实结论

`_check_distribution_fences` 在**写盘花钱之前**（两个入口 + 每次 resume，
resume 在 pending 合并后重跑——HEAD 动过）证明 distribution 的 8-gram
shingles 与**一切可审计面**不相交：种子化的 usine tracked 文本与捕获成员名、
théâtre 五包（explore/core/env/config/llm）全部 `.py`、适配层 `.py`、五份
role YAML 的 `system_extra`。干跑实测：435 shingles × 447 源，零碰撞。

- **运行时审计是构造性空转**（诚实结论，不是缺陷）：corpus 本来就是
  distribution 的 shingles，而 stock 审计只豁免目标方向与 project 指令、
  **从不豁免 distribution**——真泄漏一个 shingle 就会波波触发审计报警；
  但编排器禁止中途扩 corpus，所以运行时审计对 distribution 的实际载荷为零。
  **真载荷是这条静态预检围栏**。
- 围栏只审 `.py` 与 YAML（可 import / 可回灌的面）；markdown 文档在围栏外。
- 审计镜像解码规则：前 8 KiB 含 NUL 判二进制、**内容**跳过但**名字**照审
  ——捕获成员名 `evolution_project/<rel>` 逐文件入围栏源。
- distribution 必须写成英文散文：shingle 分词器是 `[a-z0-9]+`，CJK 文本
  产出零 shingle = 围栏静默失效——守卫对此 fail-closed。

## 7. docs 门禁契约（对 usine 树的写作纪律）

usine 的 docs 清账门禁（`verify_docs.py` DEAD_PATTERNS）对 **usine 树内**
`.md` 生效：`USINE_*` 环境变量拼写与 `usine-` 连字符词一律不得出现。适配层
自己的标记（如 seed 解包回显 `USINE_SEED_RC`、合并事件 `USINE_WAVE_MERGED`）
**只出现在 théâtre 侧文档**（本文件与 ARCHITECTURE.md，均在门禁与围栏之外）；
usine 树内文档（含 [../usine/docs/architecture.md](../usine/docs/architecture.md)
的 RSI 定位节）只写「VM 门面拒绝发布类命令」这类不含拼写的表述。

## 8. 发布红线（三层防线，比设计稿更强）

设计稿（v0 §4）计划「在 hooks 的 audit_text / audit_transcripts 挂发布动词
黑名单」（事后审计）。实现升级为**执行前拒绝**的三层：

1. **VM 门面**：publish 形态的程序在执行前直接拒（不进 guest）；
2. **guest-home USERPROFILE 钉死**：发布器读不到宿主平台登录态；
3. **offline-only 门禁**：`uv run feuille verify` 全量不含任何平台流量。

红线不变：零 H3 / TTS / 积分消耗；发布与登录永不自动执行；no push。

## 9. CLI 形态（偏离设计稿的入口语法）

设计稿（v0 §5）写 `run_usine.py wave N [--resume] [--dry-run]`。实现改为
**preflight / execute 二元入口 + ack token**（比 `--dry-run` 硬）：

```
uv run python benchmarks/usine/run_usine.py --run-name <名> --preflight
    # 打印就绪载荷，什么都不写：无 endpoints 文件、无 run root、无 corpus
uv run python benchmarks/usine/run_usine.py --run-name <名> --execute RUN-USINE-PHASE1-WAVES
    # 没有精确 ack token 不执行
```

其余旋钮：`--resume-completed-boundary`（仅在全部 accepted project 已持久收口
且 Curriculum 持久转录完好时恢复）；`--root` 默认 `theatre-usine-runs`
（**仓库外**，endpoints.json 在那里生成）；`--project-budget 8` /
`--checkpoints 0,2,4,8` / `--max-parallel 4`（宿主调度容量，不规定波宽）；
`--gate-argv` / `--gate-timeout`；`--llm-config` 默认 `~/.minimax/config.yaml`。
按需波次：一波一喊，不自动连续波（节奏升级留待用户裁定）。

## 10. 合并管线 v1 限制

symlink 变更不合并、mode / exec-bit 变更不合并（拒绝如实记录进 merge_report）；
一候选一 commit（identity `theatre-rsi` + trailers），每波 tag
`theatre/wave-N`，merge_report 落 run root；合并挂 `PHASE1_WAVE_COMPLETED`
事件**同步**执行——门禁不绿，波不算完。机制与回滚事务见
[ARCHITECTURE.md](ARCHITECTURE.md) §8。

## 11. v1 验收口径

1. `uv run python -m pytest tests/`（排除 18 个 POSIX-only 面，清单见
   PROVENANCE.md）本机全绿 ✅（2026-10-16，569 passed / 2 skipped）
2. POSIX 宿主跑同一范围全绿——**未验**（补丁全部 POSIX 中立，预期绿）
3. 假 LLM（mock chat）干跑 wave 1 全流程 ✅ **12/12 全绿**：三跑收敛，
   两处失败均为**假脚本自身 bug**（续轮归座需倒序扫 history；CRLF 按底座
   真实字节断言）——接缝零 bug；全流程 115–128s、8 次 fake 调用严丝合缝、
   记忆 602 字节逐字节吻合、五里程碑事件、tag 落位、真 usine 未动（实录见
   [ARCHITECTURE.md](ARCHITECTURE.md) §9）
4. 真 LLM wave 1（烧 MiniMax 额度）：**用户喊跑才跑**

## 12. 运维备注

- **悬空 `Z:` 盘符**：历史 scratch 泄漏残留（`Z: => D:\.rsi-usine-vm\...`，
  目标目录已回收）。所有 VM 统一回落 `Y:`，行为一致；干跑期间保持不动，
  收口时 `subst Z: /D` 摘除（教训入 [ARCHITECTURE.md](ARCHITECTURE.md) §5）。
- **防休眠任务**：跑波次期间常驻（长跑不被系统睡眠打断），收口时停。
- **run root 在仓库外**（`theatre-usine-runs`）：events / result / corpus /
  endpoints.json / memory / waves / episodes 全在那里；explorateur 根
  `.gitignore` 兜底 `endpoints.json`。
- **théâtre/.git 入库裁定**（原 §7 未决项，已定）：磁盘保留（HEAD 即上游
  commit），**绝不进 explorateur 索引**——`.gitignore` 规则 + 入库时暂移 +
  暂存集 mode-160000 审计三层防线。

## 13. 未决（需用户裁定）

- 真 wave 1 触发时机（干跑已全绿，待喊跑）
- POSIX 宿主验证窗口（§11 第 2 条）
- 波次节奏（连续 / 定时）与预算上限
- ~~dsh 迁移启动点（v1 波次产出稳定后再谈）~~ → **已启用（2026-10-18，用户裁定）**：
  范围 = usine 全量 TS 迁移为 dsh（DeepSeek Harness）原生工程（金样本 parity +
  vitest 门禁移植 + Python 清场）。**RSI 影响**：真 wave 顺延至迁移完成后，
  届时本适配层 gate_argv 改指 TS 门禁、围栏源清单 .py→.ts（适配层小改，
  théâtre 本体不动）
