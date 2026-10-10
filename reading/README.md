# 📖 Ready Reader — 外语原著精读与拆解系统

跨平台桌面应用（macOS / Windows / Linux），基于 **Tauri 2 + 纯 Rust 后端**。
导入 Markdown 原著，用 LLM 做结构化拆解，在双栏对照界面里逐句精读。

后端以 Tauri command 形式在进程内运行——**没有 Python、没有本地 HTTP 服务、不占端口、不需要额外进程**。

> 📖 完整的操作说明、常见问题与排错步骤，见 **[docs/使用指南.md](docs/使用指南.md)**。

---

## 🚀 快速开始

前置依赖：Rust 1.77.2+ 与 tauri-cli 2.x（`cargo install tauri-cli --version "^2"`
或 `brew install tauri-cli`）。Linux 还需 webkit2gtk-4.1 等系统依赖，见
[Tauri 官方文档](https://tauri.app/start/prerequisites/)。
前端无 npm 依赖，不需要 Node。命令一律在**本项目根目录（`reading/`）**执行。

```bash
cd reading               # 进入 reading 项目根目录（从仓库根目录执行）
cargo tauri dev          # 开发模式，前端改动刷新即可
cargo tauri build        # 打包当前平台安装包
```

`cargo tauri dev` / `cargo tauri build` 会经 `tauri.conf.json` 找到 `frontendDist`（`../src`），
无需任何前置构建步骤 —— 前端零 npm 依赖、零构建链。

构建产物：

```
src-tauri/target/release/bundle/macos/Ready Reader.app
src-tauri/target/release/bundle/dmg/Ready Reader_<版本>_<架构>.dmg
```

| 平台 | 产物 |
|---|---|
| macOS | `macos/Ready Reader.app`、`dmg/…dmg` |
| Windows | `msi/…msi` |
| Linux | `deb/…deb`、`appimage/…AppImage`（在 Linux 上构建才会生成） |

> ⚠️ `src-tauri/target/` 已被 `.gitignore` 排除，是本机私有的，不随仓库分发。
> 另注意构建产物总是**落后于源码**——它是上一次 `cargo tauri build` 的快照。

> tauri-cli 从当前目录及其上级查找 `tauri.conf.json`，并回退到 `src-tauri/`，
> 因此命令要在**本项目根目录（`reading/`）**执行，在 `src-tauri/` 里直接跑会找不到配置。

### 常用命令

| 命令 | 执行目录 | 作用 |
| --- | --- | --- |
| `cargo tauri dev` | 根 | 桌面应用开发模式（前端热重载 + Rust 重编译） |
| `cargo tauri build` | 根 | 打包安装包 |
| `cargo test` | `src-tauri/` | Rust 测试（单元 + command 调度 + 前后端契约 + 全链路冒烟） |
| `cargo clippy --all-targets` | `src-tauri/` | Rust 静态检查，应无告警 |
| `cargo fmt` | `src-tauri/` | Rust 格式化 |

---

## ✨ 功能

1. **双栏对照精读**：左栏原文、右栏中文精译，句级悬停/点击联动高亮
2. **语法透视镜**：点击任意句子，展开句法主干切片（S/V/O/OC/Adv/Attr）、语境锁定词义、文化典故与习语解析
3. **全书术语表**：人名地名译名全书一致（内置样例已预置术语）
4. **生词本 & Anki 导出**：一键收藏生词，导出 Anki 可直接导入的 TSV 牌组
5. **译文与解析导出 Markdown**：把整本书导出成双语对照 + 语法解析的 `.md`，含 YAML front matter 与解析进度；只读缓存，不消耗额度
6. **全文翻译与解析**：一次跑完整本书——逐段翻译 + 逐句深度解析，3 并发、可中断、可续跑，带进度弹窗
7. **多语朗读**：导入时选文档语言（13 种 BCP-47 标签），逐句 🔊 发音走加权选音的 Web Speech 内核（排序永不过滤，Chromium 长句坑有防御）；阿拉伯语/希伯来语原文自动 RTL 排版
8. **离线演示引擎**：未配置 API Key 时使用内置启发式解析 + 经典段落预置精译，零配置开箱即用
9. **两级缓存**：段落整段解析与单句深度分析分别缓存，重复阅读零重复调用
10. **本地持久化**：SQLite 存储，API Key 与全部数据都留在本机

操作步骤详见 [docs/使用指南.md](docs/使用指南.md)。

---

## 🏗️ 架构

```
reading/
├── src/                      # 前端源码 = frontendDist（原生 HTML/CSS/JS，无框架、无构建链）
│   ├── index.html            # 界面骨架
│   ├── main.js               # 入口脚本与主控制器
│   ├── api.js                # Tauri command 调用封装
│   ├── dual_reader.js        # 双栏对照阅读器
│   ├── inspector.js          # 语法透视镜
│   ├── settings.js           # 模型与解析引擎设置
│   ├── vocabulary.js         # 生词本与 Anki 导出
│   ├── tts.js                # Web Speech 朗读内核（加权选音 / Chromium 防御）
│   └── css/                  # main.css + components.css
├── src-tauri/                # Tauri 2 + Rust 后端（进程内 command，无端口）
│   ├── src/
│   │   ├── main.rs           # 入口
│   │   ├── lib.rs            # run() + 18 个 command 注册 + run_blocking
│   │   ├── db.rs             # SQLite（bundled）schema、迁移、默认配置
│   │   ├── splitter.rs       # 精准断句器（缩写 / 引语 / 小数保护）
│   │   ├── markdown.rs       # Markdown 清洗
│   │   ├── llm.rs            # LLM 客户端 + 离线演示引擎
│   │   ├── prompts.rs        # 提示词模板与 JSON schema
│   │   ├── batch.rs          # 全文翻译与解析的后台任务编排
│   │   ├── export.rs         # 译文与解析的 Markdown 导出
│   │   ├── glossary.rs       # 全书术语表
│   │   ├── vocab.rs          # 生词本 + Anki TSV 导出
│   │   ├── translit.rs       # 转写分段检查器（注音粘连拉丁 token）
│   │   ├── commands/         # documents / analysis / vocabulary / settings
│   │   └── schema_minimal.sql
│   ├── assets/               # 内置样例原著与图标源 (icon_source.svg)
│   ├── capabilities/         # 权限能力集
│   ├── tests/                # command 调度 / 前后端契约 / 全链路冒烟
│   ├── build.rs
│   ├── Cargo.toml
│   └── tauri.conf.json
└── docs/
    ├── 使用指南.md            # 日常操作、常见问题、开发者备忘
    ├── 设计/
    │   ├── 架构.md            # 内部结构与关键技术决策（长期维护）
    │   ├── 2026-10-07-tauri-跨平台重构-design.md
    │   └── 2026-10-10-多语朗读与转写分段-design.md
    └── 计划/
        ├── 2026-10-07-工程标准化.md
        └── 2026-10-07-tauri-跨平台重构.md
```

数据流：导入 → Markdown 清洗 → 段落/句子切分（带 `paragraph_id` / `sentence_id`）→ LLM 结构化解析（严格 JSON）→ SQLite 缓存 → 双栏渲染 → 透视镜 → 生词本 / Anki。

> 📐 模块职责、18 个 command 的边界与关键技术决策，详见 **[docs/设计/架构.md](docs/设计/架构.md)**。

---

## 🧪 测试

```bash
cd reading/src-tauri
cargo test                        # 单元 + command 调度 + 前后端契约 + 全链路冒烟
cargo test --lib vocab::          # 只跑生词本 / Anki 导出
cargo clippy --all-targets
cargo fmt
```

各测试文件的覆盖内容见 [docs/使用指南.md](docs/使用指南.md) 的「命令速查表」。
`tests/frontend_contract.rs` 会直接扫描 `../src` 下的前端 JS —— 目录结构一旦调整，
它会在 `cargo test` 时立刻失败，不会静默失效。

---

## 🗂️ 数据位置

| 平台 | 数据库路径 |
|---|---|
| macOS | `~/Library/Application Support/com.ready.reader/ready_reader.db` |
| Windows | `%APPDATA%\com.ready.reader\ready_reader.db` |
| Linux | `~/.local/share/com.ready.reader/ready_reader.db` |

删除该文件即完全重置应用（文档、生词本、术语表、配置全部清空，下次启动重新初始化）。
旧版 Python 后端留下的数据库保留在 `legacy-backup/data/ready_reader.db`，首次启动时自动迁移，
详见 [docs/使用指南.md](docs/使用指南.md)。

---

## 🛠 依赖与环境

| 组件 | 版本 | 必需性 |
| --- | --- | --- |
| Rust | 1.77.2+ | 必需 |
| tauri-cli | 2.x | 必需 |
| Node.js | — | **不需要**（前端无 npm 依赖、无构建链） |
| Python | — | **不需要**（后端已全部改写为 Rust） |
| SQLite | — | **不需要**（`rusqlite` bundled，随二进制分发） |
| OpenSSL | — | **不需要**（`reqwest` 走 rustls） |

---

## 与标准的差异

以下几项按工程需要偏离 Tauri 官方 `create-tauri-app` vanilla 模板，理由如下：

| 项 | 本工程取值 | 原因 |
| --- | --- | --- |
| `package.json` | 不存在 | 前端零 npm 依赖、零构建步骤，装了也是空壳 |
| `scripts/` 目录 | 不存在 | 没有构建脚本 |
| `tests/`（项目根级） | 不存在 | 前端相关测试走 Rust 侧的 `src-tauri/tests/frontend_contract.rs` |
| `beforeDevCommand` / `beforeBuildCommand` | 均不设 | 没有需要预先生成的产物 |
| `app.withGlobalTauri` | `true` | 前端经 `api.js` 调用 Tauri command，需要全局注入 |
| `src-tauri/tests/` | 存在 | Rust 侧承载全部业务逻辑，需单元 + 契约 + 冒烟测试 |

---

## 📏 开发约定

- 后端仅 Rust（`src-tauri/`）；前端无 npm 依赖、无构建链，改完直接刷新
- `rusqlite` bundled / `reqwest` rustls —— 不依赖系统 SQLite 或 OpenSSL
- 前端渲染用户/模型产出的文本一律转义（`escapeHtml` 或 `textContent`），不要用 `innerHTML` 拼接
- 新的 Tauri command 要同时在 `lib.rs` 的 `generate_handler!` 注册
- async command 里不要直接 `block_on`，一律走 `crate::run_blocking`
- 断句正则等常量模式用 `OnceLock` 编译一次，不要在按段落调用的路径里重复 `Regex::new`
- 重新生成平台图标集：`cargo tauri icon src-tauri/assets/icon_source.svg`
- 提交信息遵循 [conventional commits](https://www.conventionalcommits.org/)

---

## 📄 许可

MIT。完整条款见 [LICENSE](LICENSE)；`src-tauri/Cargo.toml` 的 `license` 字段已声明。