# ARCHITECTURE — harness2 的机制（相对设计稿的读法）

> 本文是本 fork 自带的解读文档。事实全部来自 `harness2/` 里的代码（行号随上游 commit `1cfe254`），不含推测。上游 README 与 `docs/` 逐字保留在同目录，本文不改它们一个字。

## 0. 一句话

**harness2 改的是 harness（模型周围的整个系统），不是记忆，也不是模型权重。** 一次演化 = 提一个 harness 改动的提案 → 在**同一个任务**上跑一遍看效果 → 从两次执行的**行为差异**里组合出一个更好的 harness。模型参数全程不动。

## 1. 三条轴（接缝的形状）

`harness2/core/spec.py` 的模块 docstring 定死了这件事：**method（方法）/ substrate（执行器）/ benchmark（基准）** 三层互不know each other的具体实现。

| 轴 | 是什么 | 代码位置 | 本仓对应 |
|---|---|---|---|
| **method** | 怎么改 harness：提案、探针、组合、选择、经验库 | `core/recursion.py` `core/proposer.py` `core/context.py` `core/selection.py` `core/library.py` `core/prompts.py` | 直接用（未改） |
| **substrate** | 跑 rollout 的那个智能体框架，以及它**可编辑的面** | `substrate/base.py` `substrate/opencode.py` `substrate/codex.py` `core/tree.py` 的 `SurfaceSpec` | **本仓新写**：`../garage-ii/dsh_substrate.py`（dsh 那一面） |
| **benchmark** | 任务、判据、执行环境 | `benchmarks/jobbench.py` `benchmarks/lab.py` `benchmarks/workbuddy.py` | **本仓新写**：`../garage-ii/bench_usine.py` `../garage-ii/usine_adapter.py` |

这条分界是 harness2 最值钱的设计：方法层不知道 dsh 的存在，dsh 那一面不知道方法层的存在。两边只通过 `core/spec.py` 的两个协议相遇（`SubstrateLike`、`BenchmarkAdapter`）。

## 2. c1..c8：可编辑面是**数据**，不是代码

`core/tree.py` 的 `SurfaceSpec` 是「一个智能体框架的可编辑面」的**声明式描述**：

| 字段 | 含义 |
|---|---|
| `always_on` | 永远进上下文的文件（c1 系统提示 / c2 护栏 / c3 记忆 / c4 工具指引） |
| `always_on_max` + `always_on_cap_reason` | always-on 的字符预算，以及超了会怎样 |
| `skill_dir` / `skill_name_rule` | 技能目录与命名规则（c6） |
| `autotrigger_file` / `trigger_line` | 技能没被点名时，自动补触发句到哪个文件 |
| `plugin_dir` | 插件目录（c8）；`None` = 这面不支持插件 |
| `hooks_file` + `hook_events` | 钩子文件与它允许的事件名 |
| `subagent_requires_mode` | 子智能体是否要求 `mode: subagent` 前言（c5） |
| `stubs` | 目录占位 README（不计入可编辑内容） |

**共享逻辑只写一遍**：`read_tree` / `write_tree` / `validate` / `autotrigger` / `diff_summary` 全是 `SurfaceSpec` 的泛型。两个上游 substrate（opencode、codex）**没有一个字节是重复的**——差别全在 `SurfaceSpec` 的取值与各自的 install mode。

`is_allowed()` 用**硬编码正则**定义哪些路径可编辑（技能、脚本、子智能体、插件）。这是本 fork 的一处已知缺口（见 `PROVENANCE.md` 末节）。

## 3. 一次演化：Propose–Probe–Compose

`core/recursion.py` 的 `_run_stage` 是一次「阶段」：

1. **建证据**（`core/context.py` 的 `build`）：把基准 harness、基线执行、既往证据、决策记录拼成一份上下文目录；
2. **提使命**（`context.mission`）：`core/prompts.py` 的 `propose` / `aggregate` / `compose_round` 把 benchmark 的 `BenchPrompts` 插值成一条任务说明；
3. **提案**（`core/proposer.py` 的 `Proposer.call`）：proposer 在 `context/harness/` 里**就地改文件**（edit contract：提案只声明它改了的部分，omitted-is-inherited）；
4. **收树 + 校验**：`read_tree` 读回改动的树 → `autotrigger` 补触发句 → `validate`（harness2 通用规则）→ `adapter.validate_tree`（benchmark 专属规则）→ `assert_tree_has_no_grader_verdicts`（评测隔离的机械闸）；
5. **无效提案重试一次**（`STAGE_ATTEMPTS = 2`），仍无效就**继承当前 harness**（`fell_back=True`，绝不假装成功）。

**关键点：没有 ground-truth 反馈。** 提案的依据是**同一个任务上两次执行的行为差异**（contrastive），不是分数。分数只在**选择之后**由裁判读（`core/judge.py`）。

## 4. 两种递归

| 模式 | 磁盘 token | 形状 | 什么时候用 |
|---|---|---|---|
| parallel | `agg` | **宽**：从共享证据提 2k 个候选（k 个 INV 通用改动 + k 个 DOM 领域改动），跑完后再从共享证据提 k 个**互不相干**的组合 | 想要更宽的探索面 |
| sequential | `seq` | **深**：k 轮嵌套，每轮把上一轮组合出来的 harness 带着继续改 | 想要更深的精修 |

`core/schedule.py` 的 `run_task` / `run_domain` / `run_sweep` 负责调度：域之间并行，域内按流序串行；`core/ledger.py` 的 `Ledger.assert_identity()` 钉住「并发与串行记的账目序列一致」。

## 5. 经验库 R：harnessing 级递归的载体

`core/library.py` 的 `Library` 是**第二个沉淀物**（第一个是被选中的 harness 树）：

```
<root>/<run-tag>/<mode>/<domain>/INDEX.md
<root>/<run-tag>/<mode>/<domain>/harnesses/<task>/harness/<rel>   被采纳的整棵树
<root>/<run-tag>/<mode>/<domain>/harnesses/<task>/EXPERIENCE.md   为什么选它 + 教训
```

**整棵树被搬过去，从不存摘要。** 检索是构造性的：一个域的目录里只放同域条目。每轮 sweep 每个域从空开始（root 按 run 与 mode 分域）。

这条正是 harness2 论文里「harnessing-level recursion」的实现：每个任务结束后，把**被采纳的 harness** 与**有证据支撑的教训**写进 R，指引后续任务的精修。

## 6. 选择与裁判

- `core/selection.py`：候选**匿名化**后交给 selector 选一个（`run_selection`）；selector 失败时**回落到**一个已交付的基线（`trivial_selection`），**绝不抛异常**。`reflect_adoption` 从采纳记录里抽「有支撑的教训」（`has_experience` 要求 cue / lesson / evidence 三样都在）。
- `core/judge.py`：**在选择之后**才判。`Scored.graded` 说的是「判成了」，不是「跑得好」。判据失败返回 `None`，**`None` 不是零分，且从分母里剔除**。
- `core/report.py`：`summarise` 按 (mode, k) 汇总，`render` 出可打印的表。

## 7. 评测隔离

方法层**不 import** `core/judge.py`（judge 模块自己的 docstring 明写这条）。加上一道机械闸 `core/context.py` 的 `assert_tree_has_no_grader_verdicts`：判据/裁判结论不许出现在 harness 树里。

对应到 RSIAgent 那边的同一条纪律（论文 §4.2「评测隔离：官方评测器输出是 host artifact，不得进入该轮后续学习」），两边是**同名同义**的独立实现。

## 8. 本仓的接线点在哪

| harness2 的接缝 | 本仓的实现 |
|---|---|
| `SubstrateLike.surface()` | `../garage-ii/dsh_substrate.py` 的 `DSH_SURFACE`（dsh 的 c1..c8 落点表） |
| `Substrate.materialise()` | 同上：把 c1..c8 树装成 `AGENTS.md` + `.dsh/skills/` + `harness_scripts/` |
| `Substrate.read_trajectory()` | 同上：dsh 的 `--json` 事件流 → 共享文法 `[ACTION]/[OBSERVATION]/[ERROR]` |
| `BenchmarkAdapter` | `../garage-ii/usine_adapter.py` 的 `UsineAdapter` |
| 判据 | `../garage-ii/bench_usine.py`（机械判据，不调 LLM 打分） |
| 基准 harness 树 | `../garage-ii/harness_base/`（由 `build_base_harness.py` 从真实 dsh 插件**派生**，带漂移闸） |

**没有接的两处**（诚实记账）：dsh 没有工作区级的子智能体文件约定（子智能体是 profile 里的插件），dsh 的插件也装不进工作区（要进 profile）。所以 c5 与 c8 在 dsh 这一面**不做**——给一个看起来能用、实际不生效的面，比标「不支持」更坏。

## 9. 机制索引（源码定位）

| 机制 | 位置 |
|---|---|
| c1..c8 可编辑面 | `harness2/core/tree.py:40`（`SurfaceSpec`）、`:92`（`is_allowed`）、`:336`（`validate`） |
| 三态的接缝协议 | `harness2/core/spec.py:190`（`SubstrateLike`）、`:200`（`BenchmarkAdapter`） |
| 一次演化阶段 | `harness2/core/recursion.py:135`（`_run_stage`） |
| 宽递归 | `harness2/core/recursion.py:343`（`run_parallel`） |
| 深递归 | `harness2/core/recursion.py:452`（`run_sequential`） |
| 提案与审计 | `harness2/core/proposer.py`（`Proposer.call`） |
| 经验库 | `harness2/core/library.py:20`（模块 docstring）、`:58`（`Library`） |
| 选择与教训 | `harness2/core/selection.py:279`（`run_selection`）、`:412`（`reflect_adoption`） |
| 评测隔离的机械闸 | `harness2/core/context.py`（`assert_tree_has_no_grader_verdicts`） |
| 判据失败 ≠ 零分 | `harness2/core/judge.py:40`（`Scored.graded`）、`:61`（`judge_one`） |
| 装配的指纹 | `harness2/core/runmark.py`（`fingerprint`） |
