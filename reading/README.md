# Ready Reader — 外语原著精读与拆解系统

跨平台桌面应用（macOS / Windows / Linux），基于 **Tauri 2 + 纯 Rust 后端**。
导入 Markdown 原著，用 LLM 做结构化拆解，在双栏对照界面里逐句精读。

后端以 Tauri command 形式在进程内运行——**没有 Python、没有本地 HTTP 服务、不占端口、不需要额外进程**。

> 📖 完整的操作说明、常见问题与排错步骤，见 **[docs/使用指南.md](docs/使用指南.md)**。

---

## ✨ 功能

- **双栏对照精读**：左栏原文、右栏中文精译，句级悬停/点击联动高亮
- **语法透视镜**：点击任意句子，展开句法主干切片（S/V/O/OC/Adv/Attr）、语境锁定词义、文化典故与习语解析
- **全书术语表**：人名地名译名全书一致（内置样例已预置术语）
- **生词本 & Anki 导出**：一键收藏生词，导出 Anki 可直接导入的 TSV 牌组
- **译文与解析导出 Markdown**：把整本书导出成双语对照 + 语法解析的 `.md`，含 YAML front matter 与解析进度；只读缓存，不消耗额度
- **全文翻译与解析**：一次跑完整本书——逐段翻译 + 逐句深度解析，3 并发、可中断、可续跑，带进度弹窗
- **离线演示引擎**：未配置 API Key 时使用内置启发式解析 + 经典段落预置精译，零配置开箱即用
- **两级缓存**：段落整段解析与单句深度分析分别缓存，重复阅读零重复调用
- **本地持久化**：SQLite 存储，API Key 与全部数据都留在本机

---

## 🚀 快速开始

前置依赖：[Rust](https://rustup.rs) 1.77.2+ 与 tauri-cli 2.x
（`cargo install tauri-cli --version "^2"` 或 `brew install tauri-cli`）。
Linux 还需 webkit2gtk-4.1 等系统依赖，见 [Tauri 官方文档](https://tauri.app/start/prerequisites/)。
前端无 npm 依赖，不需要 Node。

### 方式一：安装包（推荐）

从发布页下载对应平台安装包：

| 平台 | 安装包 |
|---|---|
| macOS | `.dmg`（Apple Silicon / Intel） |
| Windows | `.msi` |
| Linux | `.deb` 或 `.AppImage` |

安装后启动 Ready Reader。**首次启动若本地没有任何原著，会自动载入《白鲸记》样例**，可以直接上手。

### 方式二：直接运行已构建好的 app

本机 `src-tauri/target/release/bundle/macos/` 下已有构建产物，可直接启动，不必重新编译：

```bash
cd reading               # 进入 reading 项目根目录（从仓库根目录执行）
open "src-tauri/target/release/bundle/macos/Ready Reader.app"
```

> ⚠️ 两个前提，缺一不可：
> - **必须在项目根目录（`reading/`）执行。** 这条是相对路径，在别的目录（比如家目录）执行会被解析成
>   `<当前目录>/src-tauri/...`，报 `does not exist`。
> - **产物是本机私有的。** `src-tauri/target/` 已被 `.gitignore` 排除，不随仓库分发。
>   换一台机器或重新克隆后这个方式直接不可用，请走方式一或方式三。
>
> 另外，构建产物总是**落后于源码**——它是上一次 `cargo tauri build` 的快照。
> 若启动后界面或功能与当前源码对不上，重新构建即可：

```bash
cd reading
cargo tauri build
```

### 方式三：从源码运行（开发模式）

```bash
cd reading
cargo tauri dev      # 开发模式，前端改动刷新即可
cargo tauri build    # 构建安装包
```

构建产物在 `src-tauri/target/release/bundle/` 下，按构建平台而定：

| 平台 | 产物 |
|---|---|
| macOS | `macos/Ready Reader.app`、`dmg/Ready Reader_<版本>_<架构>.dmg` |
| Linux | `deb/`、`appimage/`（在 Linux 上构建才会生成） |

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

## 📖 使用指南

### 1. 导入你的书

- 点击顶栏 **📤 导入原著**，选择或拖入 `.md` / `.markdown` / `.txt` 文件（**UTF-8 编码**）
- 文件内容即原著正文。`#` 标题、`*` 强调、`[链接](url)`、`![图片](url)` 等 Markdown 标记会被自动清洗，空行分段的段落结构完整保留
- 顶栏下拉框可在多本原著之间切换；**《白鲸记》《了不起的盖茨比》第一章**是内置样例，点顶栏按钮即可随时重新加载
- 空文件或编码异常（大量替换字符）的文件会被拒绝导入并给出提示，不会写入任何数据

### 2. 精读与解析

- 每个段落右上有 **⚡ 一键解析本段** 按钮，点击后右栏逐句生成精译，段落状态变为 **✓ 已对齐**
- 鼠标悬停任意句子，左右栏对应句同步高亮
- **点击任意句子**打开右侧「语法透视镜」：
  - 句法切片：主干成分逐个徽章展示
  - 词法速查：重点词的**当前语境**释义，而非词典泛义
  - 典故解析：成语、隐喻、文化背景
  - 每个词条旁可 **一键收藏进生词本**
- 点击句子后，下一段会在后台自动预取解析，连续阅读基本无等待
- 已解析过的段落直接读缓存，不重复调用模型

### 3. 生词本与 Anki

- 顶栏 **📚 生词本 & Anki** 打开生词本，可查看与删除收藏
- 点击 **⚡ 一键导出至 Anki (TSV/CSV)**，弹出系统保存对话框（默认文件名 `ready_reader_anki_cards.txt`），选好位置即生成文件
- 在 Anki 中：文件 → 导入 → 选择该文件，字段分隔符选 **Tab**，勾选「允许 HTML」，导入成功
- 导出时每张卡片固定为 5 列：Anki 的 TSV 导入器不处理引号，因此字段内的制表符与换行会先折叠为空格（HTML 渲染效果不变），确保一行就是一张卡。正文会做 HTML 转义，避免释义里的 `<`、`&` 破坏卡片排版

### 4. 全文翻译与解析

- 顶栏 **⚡ 全文翻译**，确认后开始跑完整本书
- 先逐段翻译，全部段落完成后逐句做深度解析（语法切片 / 语境词义 / 典故）
- **3 个请求并发**；进度弹窗显示进度条、当前条目、失败计数与最后一次错误原因
- **可随时停止**，**可续跑**：已翻译的段落和已分析的句子自动跳过，重跑只补缺口
- **离线演示模式下拒绝启动** —— 否则一次全文跑完只会在缓存里塞满 `【译文】+原文` 占位符，它们之后在界面和导出里都跟真译文长得一样
- 这是花钱的操作：开始前会弹确认。建议先跑一两段验证质量，再全书运行

### 5. 导出译文与解析（Markdown）

- 顶栏 **📄 导出 Markdown**，选好保存位置即生成 `.md`
- 内容：YAML front matter（书名 / 作者 / 导出时间 / 解析进度）+ 逐段**原文/译文对照** + 每句的句法切片、语境词义、典故、基调
- **全书范围，但只导已解析的段落**；文件头写明 `已解析 N/M 段`，跳过的段落留下编号空洞，便于对照原书定位
- **只读缓存，不触发模型调用、不消耗额度**
- 译文渲染在 Markdown 引用块里，多行译文不会掉出引用块

### 6. 配置 LLM（可选）

默认使用内置离线演示引擎：零配置、零成本，输出为经典段落预置精译 + 启发式句法切片。要获得真正的整段翻译与深度解析：

1. 顶栏 **⚙️ 设置** 打开「模型与解析引擎设置」
2. 选择提供商：内置智能演示引擎 / DeepSeek / OpenAI / Google Gemini / Anthropic Claude / 自定义兼容端点（Ollama 等）
3. 填入 **API Key**（仅存储在本机 SQLite，不上传任何第三方服务器）、按需填写 Base URL 与模型名称
4. 如需完全跳过离线预置，关闭「优先离线演示模式」，点 **保存配置**

支持的提供商与默认模型（切换提供商时，模型输入框会自动填入下表默认值）：

| 提供商 | 默认端点 | 默认模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-1.5-flash` |
| Anthropic Claude | `https://api.anthropic.com/v1` | `claude-3-5-sonnet` |
| MiniMax | `https://api.minimaxi.com/anthropic/v1` | `MiniMax-M3` |
| 自定义兼容端点 | 你填写的 Base URL | `gpt-4o-mini`（可改） |

生成温度默认 `0.2`。解析失败时自动回退离线引擎，阅读不会中断。

> **旧版数据迁移**：本工程已移除 Python 后端，但它留下的数据库仍保留在 `legacy-backup/data/ready_reader.db`。首次启动时若应用数据目录还没有数据库，程序会自动把它复制过去，生词本与已有译文随之保留。`db.rs` 里的 `LEGACY_DB_CANDIDATES` 同时兼容更早的 `<项目>/data/ready_reader.db` 位置。确认迁移成功后即可删除 `legacy-backup/`。

---

## 🗂️ 数据位置

| 平台 | 数据库路径 |
|---|---|
| macOS | `~/Library/Application Support/com.ready.reader/ready_reader.db` |
| Windows | `%APPDATA%\com.ready.reader\ready_reader.db` |
| Linux | `~/.local/share/com.ready.reader/ready_reader.db` |

删除该文件即完全重置应用（文档、生词本、术语表、配置全部清空，下次启动重新初始化）。

---

## 🏗️ 架构

```
reading/
├── src/                      # 前端源码 = frontendDist（原生 HTML/CSS/JS，无框架、无构建链）
│   ├── index.html
│   ├── main.js               # 入口脚本与主控制器
│   ├── css/                  # main.css + components.css
│   ├── api.js                # Tauri command 调用封装
│   ├── dual_reader.js        # 双栏对照阅读器
│   ├── inspector.js          # 语法透视镜
│   ├── settings.js           # 模型与解析引擎设置
│   └── vocabulary.js         # 生词本与 Anki 导出
├── src-tauri/                # Tauri 2 + Rust 后端（进程内 command，无端口）
│   ├── src/
│   │   ├── commands/         # documents / analysis / vocabulary / settings
│   │   ├── db.rs             # SQLite（bundled）schema、迁移、默认配置
│   │   ├── splitter.rs       # 精准断句器（缩写 / 引语 / 小数保护）
│   │   ├── markdown.rs       # Markdown 清洗
│   │   ├── llm.rs            # LLM 客户端 + 离线演示引擎
│   │   ├── prompts.rs        # 提示词模板
│   │   ├── export.rs         # 译文与解析的 Markdown 导出
│   │   ├── batch.rs          # 全文翻译与解析的后台任务编排
│   │   ├── glossary.rs       # 全书术语表
│   │   ├── vocab.rs          # 生词本 + Anki TSV 导出
│   │   └── schema_minimal.sql
│   ├── assets/               # 内置样例原著与图标源 (icon_source.svg)
│   ├── capabilities/
│   ├── tests/                # command 调度 / 前后端契约 / 全链路冒烟
│   ├── build.rs
│   ├── Cargo.toml
│   └── tauri.conf.json
└── docs/
    ├── 使用指南.md            # 日常操作、常见问题、开发者备忘
    ├── 设计/                 # 设计决策与架构文档
    │   └── 2026-10-07-tauri-cross-platform-design.md
    └── 计划/                 # 实施计划
        ├── 2026-10-07-tauri-cross-platform.md
        └── 2026-10-07-工程标准化.md
```

数据流：导入 → Markdown 清洗 → 段落/句子切分（带 `paragraph_id` / `sentence_id`）→ LLM 结构化解析（严格 JSON）→ SQLite 缓存 → 双栏渲染 → 透视镜 → 生词本 / Anki。

---

## 🧪 测试

```bash
cd src-tauri
cargo test                        # 单元 + command 调度 + 前后端契约 + 全链路冒烟
cargo test --lib vocab::          # 只跑生词本 / Anki 导出
cargo clippy --all-targets
cargo fmt
```

覆盖断句、Markdown 清洗、提示词、LLM 解析、端点解析、术语表、生词本与 Anki 导出、旧库迁移、每个 command 的调度形态，以及前后端契约（前端调用的 command 名必须已注册、toast 不得用 innerHTML 拼接）。`tests/command_dispatch.rs` 还会扫描源码，确保没有 async command 直接调用 `block_on`——那会让按钮永远转圈。

`tests/frontend_contract.rs` 会直接扫描 `../src` 下的前端 JS：
目录结构一旦调整，这个测试会在 `cargo test` 时立刻失败，不会静默失效。

---

## 与标准的差异

| 项 | 本工程取值 | 原因 |
| --- | --- | --- |
| `package.json` 不存在 | 是（无） | 前端零 npm 依赖、零构建步骤，装了也是空壳 |
| `tests/` 目录不存在 | 是（无） | 前端相关测试走 Rust 侧的 `src-tauri/tests/frontend_contract.rs` |
| `scripts/` 目录不存在 | 是（无） | 没有构建脚本 |
| `app.withGlobalTauri` | `true` | 前端经 `api.js` 调用 Tauri command，需要全局注入 |

---

## 开发约定

- 后端仅 Rust（`src-tauri/`）；前端无 npm 依赖、无构建链，改完直接刷新
- `rusqlite` bundled / `reqwest` rustls —— 不依赖系统 SQLite 或 OpenSSL
- 前端渲染用户/模型产出的文本一律转义（`escapeHtml` 或 `textContent`），不要用 `innerHTML` 拼接
- 新的 Tauri command 要同时在 `lib.rs` 的 `generate_handler!` 注册
- async command 里不要直接 `block_on`，一律走 `crate::run_blocking`
- 断句正则等常量模式用 `OnceLock` 编译一次，不要在按段落调用的路径里重复 `Regex::new`
- 重新生成平台图标集：`cargo tauri icon src-tauri/assets/icon_source.svg`
- 提交信息遵循 [conventional commits](https://www.conventionalcommits.org/)