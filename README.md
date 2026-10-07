# explorateur

> 一个装了三台独立机器的工作区。每个子项目自带栈、自带文档、自带测试，**互不依赖**。

这个仓库是工作区，不是单体工程——三个子项目之间没有代码引用，各自可单独 clone、单独构建、单独发布。下面是入口索引；改代码前请直接进对应子项目读它自己的文档。

---

## 子项目

| 目录 | 是什么 | 栈 | 规模 | 入口文档 |
|---|---|---|---|---|
| [`humming/`](humming/) | **HummingScore** 哼唱识谱：哼一段 → 实时转五线谱 / 简谱 / MIDI / MusicXML | Tauri 2 + 原生 JS（无框架） | 28 文件 / 6227 行 | [README](humming/README.md) · [使用指南](humming/docs/使用指南.md) |
| [`reading/`](reading/) | **Ready Reader** 外语原著精读：导入 Markdown → LLM 结构化拆解 → 双栏逐句精读 | Tauri 2 + 纯 Rust 后端 | 26 文件 / 6594 行 | [README](reading/README.md) · [使用指南](reading/docs/使用指南.md) |
| [`usine/`](usine/) | **feuille** 多语种视频生产与发布可复用层：TTS / 渲字 / 合成 / 封面 / 四平台发布 / 发布后核对 | Python 3.12 + uv | 52 文件 / 12950 行 | [README](usine/README.md) · [**AGENTS.md**](usine/AGENTS.md) |

`humming` 与 `reading` 是两个**应用**（可打包成安装包分发的桌面程序）；`usine` 是一个**库层**（被其它内容项目复用的机制 + 体例 + 纪律，不直接分发）。

---

## 前置依赖

| 子项目 | 需要 |
|---|---|
| `humming` | Rust 1.77.2+、tauri-cli 2.x、Node（仅用于 vendor 构建依赖） |
| `reading` | Rust 1.77.2+、tauri-cli 2.x。**前端无 npm 依赖，不需要 Node** |
| `usine` | uv；发布相关依赖走可选组 `uv sync --group publish` |

`humming` 与 `reading` 的 `cargo tauri` 命令要在**各自项目根目录**（`humming/`、`reading/`）执行，不是仓库根目录。

---

## 测试

三个子项目各有独立测试套件，全部应保持全绿：

```bash
# humming —— 5 个 Node 测试：流水线 / 音符编辑 / 合成器 / UI 契约 / 端到端
cd humming && npm install && npm test

# reading —— 119 个 Rust 测试：单元 + command 调度 + 前后端契约 + 全链路冒烟
cd reading/src-tauri && cargo test

# usine —— 16 套 250 项反向验证
cd usine && uv sync && uv run feuille verify
```

`usine` 的验证是**反向验证**（好数据必须全 PASS，坏数据必须 FAIL），不是常规单测——详见 `usine/AGENTS.md`。

---

## 仓库级约定

- **`.gitignore` 在根目录统一管理**，覆盖三个子项目：依赖目录（`node_modules/`、`.venv/`）、构建产物（`target/`、`dist/`、`build/`）、Tauri 生成物（`**/gen/schemas/`）、`humming/src/vendor/`、密钥文件与系统文件。
- **lockfile 一律入库**：`package-lock.json`、两个 `Cargo.lock`、`uv.lock`。三个都是应用项目，可复现构建优先于 diff 整洁。
- **`src-tauri/target/` 是本机私有的**，不随仓库分发，也因此**会带上编译时的绝对路径**。项目目录一旦改名或移动，必须 `cargo clean` 后重建，否则 tauri-build 会继续去读旧路径而构建失败（见下方「已知坑」）。
- 纪律条文的权威文本在 [`usine/AGENTS.md`](usine/AGENTS.md)（22 条纪律 + 工程约定 + H3 铁律）。该文件自带完整约定，本工作区没有更上层的 `AGENTS.md`。

---

## 已知坑

**Tauri 项目移动目录后构建失败**，报 `failed to read plugin permissions: ... No such file or directory`，且路径指向旧目录。

原因不是源码问题：`tauri-build` 的构建脚本会把权限文件清单以**绝对路径**写进 `target/debug/build/tauri-*/output`，cargo 会缓存并在后续构建中直接回放。目录改名/移动后这份缓存不会自动失效，于是构建脚本去读一个已不存在的旧路径。

`cargo clean -p <包名>` **不足以修复**——它只清本包的产物，不会重跑依赖的构建脚本。有效做法是清掉这些缓存文件，强制 tauri-build 重跑：

```bash
cd <项目>/src-tauri
grep -rl "<旧绝对路径>" target/debug/build --include=output --include=root-output \
  | xargs -I{} mv {} {}.stale
cargo test
```

---

## 文档分层

- **工作区级**（本文件）：索引与跨项目约定。
- **项目级**：各子项目的 `README.md`（这是什么、怎么构建）+ `docs/使用指南.md`（日常操作与排错）。
- **设计与计划**：`humming|reading/docs/{设计,计划}/`，记录当时的决策与实施步骤。**这些是历史记录，其中的路径与命令反映当时的机器状态，不必与现状一致。**