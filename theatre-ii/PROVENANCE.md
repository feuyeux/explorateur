# PROVENANCE — theatre-ii：harness2 引擎的 vendored fork

- **Upstream**: <https://github.com/google-research/harness2>
- **Paper**: Harness²: Recursive Agent Harnessing for an Open World（arXiv 2610.14224，Xu Ruiyao 等，Google LLC）
- **Vendored at commit**: `1cfe254e8d25b15f37048c3730134686abe60335`（`main` 分支）
- **Upstream license**: Apache License 2.0（保留于本目录 `LICENSE`；本 fork 的改动同样按 Apache-2.0 提供）
- **Fork date**: 2026-10-20
- **Purpose**: 作为 `usine/`（feuille 多语种视频产线，宿主是 dsh）的**第二条**自进化路径——`théâtre/`（RSIAgent 引擎）演化的对象是**记忆**，本目录的引擎演化的对象是**harness 本身**。适配层在 `../garage-ii/`。

本目录的定位与 `../théâtre/` 平行但**不是同类**：`théâtre/` 是 RSIAgent 的 vendored fork（改 harness2 之前就已存在），`theatre-ii/` 是 harness2 的 vendored fork。两者互不覆盖、共同服务于「usine 这个 dsh 智能体怎么自我进化」这一个问题。

## 纪律

1. **不回步上游**：需要新上游版本时开**新目录**重新 vendor，避免历史漂移。本目录的 `.git` 不保留（与 `../théâtre/` 的现状一致——它的 `.git` 也已被清掉，PROVENANCE 里记的是意图不是现状）。
2. **上游文件逐字节不变**：`harness2/`、`docs/`、`scripts/`、`tests/`、`LICENSE`、`pyproject.toml`、`MANIFEST.in`、`CONTRIBUTING.md`、`README.md` 全部逐字搬运，**零补丁**。本目录与上游的差异**只有两类**：
   - **新增**本文件、`ARCHITECTURE.md`、`COMPARISON.md`（本 fork 自带的文档，不改上游任何一行）；
   - **未 vendor** 上游的三个目录（见下节）。
3. **适配层不进来**：dsh 的接缝、usine 的任务与判据全在 `../garage-ii/`。本目录里**没有一行** usine 或 dsh 专属代码——引擎与桥接的边界不许模糊。

## vendor 范围（56 个文件）

| 从上游取 | 说明 |
|---|---|
| `harness2/`（39 个 .py） | 引擎本体：`core/`（方法层）、`substrate/`（执行器接缝）、`benchmarks/`（jb/lab/wb 三格）、`cli/`（命令层）、`config.py`、`preflight.py`、`install.py`、`demo.py` |
| `docs/`（3 个 .md） | `BENCHMARKS.md` / `EXPERIMENTS.md` / `SETUP.md` |
| `scripts/`（8 个） | 上游的安装/校验脚本 |
| `tests/test_workflow.py` | 上游唯一的工作流测试 |
| `LICENSE` `pyproject.toml` `MANIFEST.in` `CONTRIBUTING.md` `README.md` | 原样 |

## 未 vendor 的三个目录（以及为什么）

| 上游目录 | 内容 | 为什么没取 |
|---|---|---|
| `third_party/`（48 个文件） | JobBench / LAB / WorkBuddy 三个基准的 runner 检出、许可与补丁 | 本仓只跑 **usine × dsh** 这一格，dsh 那一格不依赖这三格的 runner 检出。**代价**：`harness2.install` 与 `harness2.preflight` 在本目录**不可用**（它们硬依赖 `third_party/` 与 `dependencies/` 里的 opencode 检出与那三格的环境）。`../garage-ii/preflight.py` 是为 dsh 这一格**另写**的一套，不复用上游那份。 |
| `dependencies/`（3 个文件） | opencode / codex / 三个基准仓的 pin 与 `ASSETS.json` | 同上：dsh 那一格的执行器是 dsh，不经 opencode/codex 检出。 |
| `assets/`（7 个 png/gif） | README 里的配图 | 二进制。本仓 `.gitattributes` 把图片统一走 Git LFS，vendored 引擎用不上配图，搬进来只是给 LFS 增加体积。 |

**这一条要写清楚**：以上三个目录的缺失**不是**「上游没有这部分功能」，而是「本仓不需要这部分功能」。哪天要把 jb/lab/wb 那一格也接进本仓，就得把 `third_party/` 与 `dependencies/` 一并 vendor 进来，`harness2.preflight` 才会重新可用。

## 与上游的零补丁声明

vendor 时对 `harness2/`、`docs/`、`scripts/`、`tests/` 与四个根文件逐字节 `cmp` / `diff -r` 核对，全部一致。本 fork **没有**修改上游任何一行代码。

上游自身在别的层面做的跨平台/工程化处理（POSIX 语义、路径归一等）留在它自己的代码里，不在本 fork 的职责范围内。

**零补丁 ≠ 零扩展**：`harness2/core/prompts.py` 有一张按 **surface 名**索引的提示表（`_SURFACE_TEXTS`），只认 `codex` 与 `opencode`。dsh 不是这两个之一，不注册就会抛 `ValueError: no prompt surface for 'dsh'`，整个 sweep 一个任务都跑不动。`../garage-ii/dsh_surface.py` 在**运行时**往那张表里注册一条 dsh 自己的条目——**上游文件一个字节都没动**，改的是本仓的调用方。这条扩展写的是 dsh 真实的可编辑面（c5/c8 在 dsh 上根本不存在，10 份插件技能被冻结）；拿 opencode 那份顶替会让 proposer 提出装不上去的组件。

## 已知不适用的上游面

| 上游面 | 状态 | 理由 |
|---|---|---|
| `harness2.cli.run_sweep` 的 `--bench jb|wb|lab` | 不适用 | 那三格是上游的基准。本仓用的是 `../garage-ii/run_usine_h2.py`，它复用上游的 `core.schedule` / `core.proposer` / `core.judge` / `core.report`，但自己组装 adapter。 |
| `harness2.cli.run_sweep` 的 `--substrate oc|cx` | 不适用 | 执行器是 dsh，接缝在 `../garage-ii/dsh_substrate.py`。 |
| `harness2.preflight.check` | 不适用 | 硬依赖 `missing_runners()` 与 `OpencodeSubstrate().preflight()`。dsh 这一格用 `../garage-ii/preflight.py`。 |
| `harness2.config.validate_models` | 不适用 | 它要求 `HARNESS2_SOLVER_MODEL`（opencode 风格的 provider/model 串）。dsh 这一格的**执行器**模型由 dsh 自己配（走本机中继到 MiniMax 运行时）；**改 harness 的那个模型**（proposer）也不走上游通道——`../garage-ii/minimax_proposer.py` 是自建的直连通道，所以 `HARNESS2_IMPROVER_MODEL` **不用设**。 |
| `harness2.core.prompts._SURFACE_TEXTS` | **运行时扩展** | 表里只有 `codex` / `opencode` 两条。dsh 那条由 `../garage-ii/dsh_surface.py` 在运行时注册（上游文件零改动，见上一节）。 |
| `harness2.core.schedule._selector_for` | 绕开 | 它会拿 `BenchSpec.channels["selector"]` 构造上游 `Proposer`，而上游 `Proposer.__post_init__` 在模型为空时直接 `ValueError`。`../garage-ii/run_usine_h2.py` 用 `selector_prop=prop` 把 selector 也指到本层的通道上。 |
| `harness2.core.context.assert_tree_has_no_grader_verdicts` | **适用且重要** | 它是「评测隔离」在方法层的机械闸：判据不许进 harness 树。本仓的机械判据在 `../garage-ii/bench_usine.py`，与这条闸配套。 |

## 一处**已知的能力缺口**（不是缺陷，是设计后果）

harness2 的可编辑面由 `harness2/core/tree.py` 的 `is_allowed()` 用**硬编码正则**定义：技能只认 `<skill_dir>/<name>/SKILL.md` 与 `<skill_dir>/<name>/scripts/<file>`。usine 的十份技能除了 `SKILL.md`，还带 `references/` 与 `assets/` 子目录——**这些不在可编辑面上**。

后果：harness2 的 proposer 能改技能的 `SKILL.md` 正文与脚本，**改不了**技能引用的参考文档与素材。v1 接受这个缺口（不改上游代码，不制造两套真相），并把它记在 `../garage-ii/BENCHMARK.md` 的「测不到什么」一节里。若将来要补，正确的做法是**在本 fork 之上加一个带补丁清单的改动**（像 `../théâtre/PROVENANCE.md` 记的那 24 个文件那样），而不是在 `../garage-ii/` 里另造一套树语义。

## 来源

- 仓库：<https://github.com/google-research/harness2>（`main`，commit `1cfe254e8d25b15f37048c3730134686abe60335`，取于 2026-10-20）
- 论文：<https://arxiv.org/abs/2610.14224>
- 上游 README（本目录 `README.md` 逐字保留）与 `docs/`
