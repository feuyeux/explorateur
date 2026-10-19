# explorateur

> 一个装着一台多语种视频生产机器和一台 RSI 自进化引擎的工作区仓库。

这个仓库是工作区，不是单体工程。本仓库（`explorateur/`）承载 `usine/` 与 RSI 工作流（[`théâtre/`](théâtre/) 引擎 + [`garage/`](garage/) 适配层）；RSI 工作流对 usine 是单向安全改进关系，不构成子项目间依赖（见下文「RSI 工作流」）。两个独立应用 `humming` 与 `reading` 在**仓库外**的同级目录 [`app/`](../app/)，各自维护、各自版本化，本仓库不覆盖其文档与测试。下面是入口索引；改代码前请直接进对应子项目读它自己的文档。

---

## 子项目

| 目录 | 是什么 | 栈 | 规模 | 入口文档 |
|---|---|---|---|---|
| [`usine/`](usine/) | **feuille** 多语种视频生产与发布可复用层：TTS / 渲字 / 合成 / 封面 / 四平台发布 / 发布后核对 | TS pnpm monorepo（Node ≥24） | 10 包 / 约 3.2 万行 TS | [README](usine/README.md) · [**AGENTS.md**](usine/AGENTS.md) · [架构](usine/docs/architecture.md) |

规模口径见 [usine/README.md](usine/README.md)。

---

## RSI 工作流（théâtre × usine）

usine 除人工演进外，还由 **RSI 引擎**（波次化递归自我改进）安全地改进——Actor 在
隔离 guest 里改代码、Verifier 判定、门禁绿才合并回真树：

| 目录 | 是什么 | 入口 |
|---|---|---|
| [`théâtre/`](théâtre/) | vendored RSIAgent 引擎（上游 [AetherLabsAI/RSIAgent](https://github.com/AetherLabsAI/RSIAgent) @ `4d7ef43`；内嵌 `.git` 磁盘保留、**绝不进本仓库索引**） | [ARCHITECTURE.md](théâtre/ARCHITECTURE.md)（机制与图表）· [PROVENANCE.md](théâtre/PROVENANCE.md)（补丁纪律）· [ADAPTATION.md](théâtre/ADAPTATION.md)（实现偏离） |
| [`garage/`](garage/) | 适配层：装配 / 传输 / 围栏 / 合并 / 门禁预检；**改进方向含智能体面（dsh 插件工具面）** | [README](garage/README.md)（**运行手册：怎么跑一次 wave、怎么校验自进化产物**）· `run_usine.py`（`--preflight` 先行；`--execute` 需 ack token；真波次喊跑才跑；Windows wave host 与 macOS POSIX host 均可跑） |
| [`plan/`](plan/) | 排产与调研文档 | [rsiagent-memory.md](plan/rsiagent-memory.md)（RSI 调研） |

红线：发布 / 登录永不自动执行（VM 门面三层防线）；一候选一 commit，每波 tag
`theatre/wave-N`；运行产物与 `endpoints.json`（真网关凭据）一律落仓库外 run root
（`theatre-usine-runs`），根 `.gitignore` 兜底；真波次**用户喊跑才跑**。

---

## 前置依赖

- `usine`：Node ≥24、pnpm ≥11（standalone）；`pnpm install` 一次后 `pnpm verify` 全量门禁。

BGM 底床生成（`usine/skills/bgm-bed`，走 Google Lyria）的 API key 统一配在 `explorateur/config/.env`（样例见 `config/env.sample`；环境变量优先于文件），key 申请页：https://aistudio.google.com/api-keys 。

---

## 测试

usine 的测试套件应保持全绿：

```bash
# usine —— pnpm monorepo 全量门禁：typecheck + 全部 vitest 套件（545 用例 / 4 跳过，2026-10-18 基线）
cd usine && pnpm install && pnpm verify
```

`usine` 的验证继承**反向验证**纪律（好数据必须全 PASS，坏数据必须 FAIL）并叠加钉版对账
（dsh 工具面 ↔ CLI 路由 ↔ SKILL 积分表），全部进 `pnpm verify`——详见 `usine/AGENTS.md`。

---

## 仓库级约定

- **`.gitignore` 在根目录统一管理**，覆盖仓库内项目：依赖目录（`node_modules/`、`.venv/`）、构建产物（`target/`、`dist/`、`build/`）、密钥文件与系统文件。
- **lockfile 一律入库**：仓库内 `pnpm-lock.yaml`（uv.lock 已随 P7 Python 清场退役）。可复现构建优先于 diff 整洁。
- 纪律条文的权威文本在 [`usine/AGENTS.md`](usine/AGENTS.md)（22 条纪律 + 工程约定 + H3 铁律）；工作区级约束（技能库路由 / 规则层级）在 [AGENTS.md](AGENTS.md)——两层各管各的，互不覆盖。

---

## 文档分层

两个层次，职责不重叠：

| 层 | 位置 | 写什么 | 生命周期 |
|---|---|---|---|
| **工作区级** | 本文件 | 子项目索引与跨项目约定 | 随工作区 |
| **项目级** | [usine/README.md](usine/README.md) | 这是什么、怎么构建、怎么跑测试、目录树 | 随项目 |

`usine` 自带 [AGENTS.md](usine/AGENTS.md)（纪律条文 + 工程约定），是该项目的权威文本；人机交互与工具面细节在 [usine/docs/guide.md](usine/docs/guide.md)，分层架构在 [usine/docs/dsh.md](usine/docs/dsh.md)。
