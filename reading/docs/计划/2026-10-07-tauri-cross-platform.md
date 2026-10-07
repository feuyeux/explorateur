# Ready Reader Tauri 2 跨平台重构 — 实施计划

> ⚠️ **历史文档**：本计划描述迁移当时的仓库形态（含 `frontend/` 目录布局）。
> 该布局已在同日的工程标准化中统一为 `src/`，详见
> [工程标准化计划](2026-10-07-工程标准化.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Ready Reader 从 FastAPI(Python)+Swift 壳重构为 Tauri 2 纯 Rust 后端跨平台桌面 App（macOS/Windows/Linux），随后清理全部过时 Python/Swift 资产并重写 README 使用指南。

**Architecture:** Tauri 2 进程内 commands（无 HTTP/端口）+ rusqlite(bundled) + reqwest(rustls)。前端原样保留，仅 `api.js` 改走 `window.__TAURI__.core.invoke`。断句器/离线 LLM 引擎/Anki 导出逐条从 Python 平移，行为一致。

**Tech Stack:** Tauri 2、rusqlite(bundled)、reqwest(rustls-tls)、serde_json、regex + fancy-regex、chrono、uuid。前端零框架零构建链（withGlobalTauri）。

**Spec:** `docs/设计/2026-10-07-tauri-cross-platform-design.md`（本计划从 spec 论证，执行者需同读两份）

## Global Constraints

- 禁止引入任何 Python 依赖；后端逻辑全部在 `src-tauri/`（Rust）
- `rusqlite` 必须用 `features = ["bundled"]`（不得依赖系统 sqlite）
- `reqwest` 用 `default-features = false, features = ["json", "rustls-tls"]`（禁 openssl）
- identifier 固定 `com.ready.reader`；productName `Ready Reader`
- SQLite 六表 + 索引 + 种子设置与旧 `backend/app/database.py` 逐字段一致
- Command 错误文案沿用旧中文文案（"文档未找到"、"段落未找到"、"句子未找到"、"生词与释义不能为空"等）
- 默认 mock 优先：provider=mock、mock_mode=true
- 前端无 npm 构建链：`withGlobalTauri: true`，`frontendDist: "../frontend"`；frontend 只允许改 api.js、vocabulary.js 的导出函数、index.html 的 accept 与提示文案
- 图标文字渲染必须走 Edge headless 截图，禁止 Pillow 画字（工作区硬性规则）
- 交付文件只写工作区目录
- 每个 commit message 尾行：`Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 首次 `cargo check` 拉取约 500 个 crate（数分钟），属预期
- 本机只验证 macOS；Windows/Linux 仅保证配置正确（spec §2）

## Review Focus

spec 隐含但最容易咬到真实用户的输入类别（每条已钉进对应任务的测试步骤）：

1. **非 UTF-8 编码文件（GBK 等）** — 前端 FileReader 按 UTF-8 读出 U+FFFD 乱码。期望：后端检测到替换符时拒绝并提示，不把乱码存库。→ Task 8 测试钉住。
2. **空文件 / 纯空行文件** — 期望：提示"文件内容为空"，不建文档记录。→ Task 8 测试钉住。
3. **LLM 端点不可达/超时** — 期望：60s 超时后静默降级离线引擎，用户仍拿到结构化结果。→ Task 7 测试钉住（降级路径单测）。
4. ** Anki 导出含特殊字符（词/释义内含引号、制表符、换行）** — 期望：TSV 字段正确转义，Anki 可导入。→ Task 10 测试钉住。
5. **sentence_id 在缓存 JSON 中与请求不一致（LLM 幻觉改 ID）** — 期望：按请求的 DB sentence_id 对齐写库，幻觉 ID 丢弃。→ Task 7 测试钉住。

---

### Task 1: git init + 脚手架（Tauri 2 工程骨架）

**Files:**
- Create: `.gitignore`
- Create: `src-tauri/Cargo.toml`
- Create: `src-tauri/build.rs`
- Create: `src-tauri/tauri.conf.json`
- Create: `src-tauri/src/main.rs`
- Create: `src-tauri/src/lib.rs`（最小可编译版，仅 health command）

**Interfaces:**
- Produces: 可编译的 tauri 工程；`lib.rs::run()` 入口；`#[tauri::command] fn health() -> String`（后续 Task 12 前端接线时不再需要，但用于本任务验证 IPC 通路）

- [ ] **Step 1: git init + .gitignore**

```bash
cd /Users/han/coding/personal/ready
git init
```

`.gitignore`:

```gitignore
# Rust / Tauri
src-tauri/target/
src-tauri/Cargo.lock

# Node (none expected, but guard)
node_modules/

# macOS
.DS_Store

# Legacy (to be deleted in Task 12, ignore meanwhile)
.venv/
data/ready_reader.db

# Python caches
__pycache__/
```

- [ ] **Step 2: 写 Cargo.toml**

`src-tauri/Cargo.toml`:

```toml
[package]
name = "ready-reader"
version = "1.0.0"
description = "外语原著精读与拆解系统"
authors = ["han"]
edition = "2021"
rust-version = "1.77"

[lib]
name = "ready_reader_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-dialog = "2"
tauri-plugin-fs = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
rusqlite = { version = "0.32", features = ["bundled"] }
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls"] }
regex = "1"
fancy-regex = "0.14"
chrono = "0.4"
uuid = { version = "1", features = ["v4"] }
```

`src-tauri/build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

- [ ] **Step 3: 写 tauri.conf.json**

`src-tauri/tauri.conf.json`（注意：icons 字段指向尚不存在的图标会在 build 报错，本任务先注释掉 icons，Task 11 生成后恢复）：

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Ready Reader",
  "version": "1.0.0",
  "identifier": "com.ready.reader",
  "build": {
    "frontendDist": "../frontend"
  },
  "app": {
    "withGlobalTauri": true,
    "windows": [
      {
        "title": "Ready Reader - 外语原著精读与拆解",
        "width": 1360,
        "height": 920,
        "minWidth": 960,
        "minHeight": 600,
        "center": true
      }
    ],
    "security": {
      "csp": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'"
    }
  },
  "bundle": {
    "active": true,
    "targets": "all",
    "icon": []
  }
}
```

- [ ] **Step 4: 写最小 main.rs / lib.rs**

`src-tauri/src/main.rs`:

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ready_reader_lib::run()
}
```

`src-tauri/src/lib.rs`:

```rust
mod db;

#[tauri::command]
fn health() -> String {
    "ok".to_string()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![health])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

`src-tauri/src/db.rs` 本任务先建占位（Task 2 填充）：

```rust
// Database layer — implemented in Task 2.
```

- [ ] **Step 5: 首次编译验证**

Run: `cd /Users/han/coding/personal/ready/src-tauri && cargo check 2>&1 | tail -5`
Expected: 编译通过（首次拉取大量 crate，数分钟）。若 tauri context 报缺图标，确认 tauri.conf.json 的 bundle.icon 为空数组后重试。

- [ ] **Step 6: Commit**

```bash
git add .gitignore src-tauri/
git commit -m "chore: scaffold tauri 2 workspace (rust backend skeleton)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: db.rs — schema、连接、旧库迁移、设置种子

**Files:**
- Create: `src-tauri/src/db.rs`（替换 Task 1 占位）

**Interfaces:**
- Produces:
  - `pub fn db_path(app: &tauri::AppHandle) -> PathBuf` — 解析应用数据目录下 `ready_reader.db`
  - `pub fn init_db(app: &tauri::AppHandle) -> Result<(), String>` — 建目录、迁移旧库、执行 schema、种子设置
  - `pub fn with_conn<T>(app: &tauri::AppHandle, f: impl FnOnce(&rusqlite::Connection) -> Result<T, String>) -> Result<T, String>` — 所有 command 的统一 DB 访问入口

- [ ] **Step 1: 实现 db.rs**

`src-tauri/src/db.rs`（完整替换）:

```rust
use rusqlite::Connection;
use std::path::PathBuf;

pub fn db_path(app: &tauri::AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .expect("no app data dir")
        .join("ready_reader.db")
}

// Legacy monorepo db, migrated on first launch (spec §4).
fn legacy_db_path() -> Option<PathBuf> {
    let candidates = [
        PathBuf::from("../../data/ready_reader.db"),
    ];
    candidates
        .iter()
        .map(|p| p.canonicalize().ok())
        .find(|p| p.is_some())
        .flatten()
}

pub fn init_db(app: &tauri::AppHandle) -> Result<(), String> {
    let path = db_path(app);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }

    // One-time migration from the legacy project-local db.
    if !path.exists() {
        if let Some(legacy) = legacy_db_path() {
            if std::fs::copy(&legacy, &path).is_ok() {
                eprintln!("migrated legacy db from {}", legacy.display());
            }
        }
    }

    let conn = Connection::open(&path).map_err(|e| e.to_string())?;
    conn.pragma_update(None, "journal_mode", "WAL").ok();
    conn.pragma_update(None, "foreign_keys", "ON").ok();

    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT DEFAULT '未知作者',
            file_type TEXT NOT NULL,
            raw_content TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paragraphs (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chapter_id TEXT DEFAULT 'ch_1',
            order_index INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sentences (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            paragraph_id TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            original TEXT NOT NULL,
            translation TEXT,
            deep_analysis_json TEXT,
            updated_at TEXT,
            FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE,
            FOREIGN KEY (paragraph_id) REFERENCES paragraphs (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            term TEXT NOT NULL,
            category TEXT DEFAULT '专有名词',
            canonical_translation TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS vocabulary_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            pos TEXT,
            translation TEXT NOT NULL,
            sentence_context TEXT,
            sentence_id TEXT,
            cultural_background TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sentences_doc ON sentences(doc_id);
        CREATE INDEX IF NOT EXISTS idx_sentences_para ON sentences(paragraph_id);
        CREATE INDEX IF NOT EXISTS idx_paragraphs_doc ON paragraphs(doc_id);
        "#,
    )
    .map_err(|e| e.to_string())?;

    // Seed default settings (mirrors backend/app/database.py).
    let count: i64 = conn
        .query_row("SELECT COUNT(*) FROM settings", [], |r| r.get(0))
        .map_err(|e| e.to_string())?;
    if count == 0 {
        for (k, v) in [
            ("provider", "mock"),
            ("api_key", ""),
            ("base_url", ""),
            ("model_name", "gpt-4o-mini"),
            ("temperature", "0.2"),
            ("mock_mode", "true"),
        ] {
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (k, v),
            )
            .map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

pub fn with_conn<T>(
    app: &tauri::AppHandle,
    f: impl FnOnce(&Connection) -> Result<T, String>,
) -> Result<T, String> {
    let conn = Connection::open(db_path(app)).map_err(|e| e.to_string())?;
    conn.pragma_update(None, "foreign_keys", "ON").ok();
    f(&conn)
}
```

注意 `legacy_db_path`：Tauri 进程 cwd 是打包资源目录，`../../data/` 相对路径不可靠。
实现后立即用 `tauri dev` 从 dev 目录验证（cwd = `src-tauri`，`../../data/` 解析为项目 `data/`）。
打包后旧库通常已随用户迁移完成，此路径仅一次性用途，可接受失效（spec §4：迁移动作只在旧库存在的开发机上发生）。

- [ ] **Step 2: 接入启动流程**

修改 `src-tauri/src/lib.rs` 的 `run()`，在 builder 前后接入：

```rust
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            db::init_db(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![health])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 3: 编译 + dev 冒烟**

Run: `cd /Users/han/coding/personal/ready/src-tauri && cargo check 2>&1 | tail -3`
Expected: PASS

Run: `cargo tauri dev`（若无 tauri-cli：`cargo install tauri-cli --version "^2"` 或用 `npx @tauri-apps/cli@latest dev`）窗口弹出、终端出现 "migrated legacy db from ..."（旧库存在时）、无 panic。`~/Library/Application Support/com.ready.reader/ready_reader.db` 存在。Ctrl+C 退出。

- [ ] **Step 4: Commit**

```bash
git add src-tauri/src/db.rs src-tauri/src/lib.rs
git commit -m "feat: sqlite schema, legacy db migration, settings seed

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: splitter.rs — 精准断句器（TDD，自 Python 平移）

**Files:**
- Create: `src-tauri/src/splitter.rs`
- Test: `src-tauri/src/splitter.rs` 内联 `#[cfg(test)]`

**Interfaces:**
- Produces:
  - `pub fn split_paragraphs_and_sentences(text: &str) -> Vec<Paragraph>` 其中
    `pub struct Paragraph { pub paragraph_id: String, pub order_index: i64, pub raw_text: String, pub sentences: Vec<SentenceUnit> }`、
    `pub struct SentenceUnit { pub sentence_id: String, pub order_index: i64, pub original: String }`
  - `pub fn split_sentences_western(paragraph_text: &str) -> Vec<String>`（Task 3 内部使用 + 单测）

- [ ] **Step 1: 写失败测试（对照 test_system.py 的断言）**

`src-tauri/src/splitter.rs` 起步只写测试与空实现：

```rust
#[derive(Debug, Clone, serde::Serialize)]
pub struct SentenceUnit {
    pub sentence_id: String,
    pub order_index: i64,
    pub original: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Paragraph {
    pub paragraph_id: String,
    pub order_index: i64,
    pub raw_text: String,
    pub sentences: Vec<SentenceUnit>,
}

pub fn split_sentences_western(_paragraph_text: &str) -> Vec<String> {
    vec![] // TODO Task 3
}

pub fn split_paragraphs_and_sentences(_text: &str) -> Vec<Paragraph> {
    vec![] // TODO Task 3
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_precision_sentence_splitting() {
        let sample = "Mr. Smith and Dr. Watson arrived at 8.30 a.m. in Washington, D.C. \
They met Prof. Moriarty near St. Jude's hospital (e.g., on 5th Ave.). \
\"Call me Ishmael!\" he said. \
Is this not curious? Absolutely.";
        let sents = split_sentences_western(sample);
        assert!(sents.iter().any(|s| s.contains("Mr. Smith and Dr. Watson arrived")), "got {:?}", sents);
        assert!(sents.iter().any(|s| s.contains("Washington, D.C.")), "got {:?}", sents);
        assert!(sents.iter().any(|s| s.contains("Prof. Moriarty")), "got {:?}", sents);
        assert!(sents.iter().any(|s| s.contains("Call me Ishmael!")), "got {:?}", sents);
        assert_eq!(sents.len(), 4, "got {:?}", sents);
    }

    #[test]
    fn test_structured_paragraph_decomposition() {
        let text = "Call me Ishmael.\n\nSome years ago, I went to sea.";
        let paras = split_paragraphs_and_sentences(text);
        assert_eq!(paras.len(), 2);
        assert_eq!(paras[0].paragraph_id, "p1");
        assert_eq!(paras[0].sentences[0].sentence_id, "p1_s1");
        assert_eq!(paras[0].sentences[0].original, "Call me Ishmael.");
        assert_eq!(paras[1].paragraph_id, "p2");
        assert_eq!(paras[1].sentences[0].sentence_id, "p2_s1");
    }

    #[test]
    fn test_ellipsis_and_multiple_punct() {
        let sents = split_sentences_western("What the devil is the matter?\" asked he...");
        assert_eq!(sents.len(), 1, "got {:?}", sents);
        assert!(sents[0].contains("..."));
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /Users/han/coding/personal/ready/src-tauri && cargo test --lib splitter 2>&1 | tail -8`
Expected: 3 个测试 FAIL（空实现返回空数组）

- [ ] **Step 3: 实现断句器（Python 逻辑逐条翻译）**

在 `splitter.rs` 顶部加入并填充两个函数。要点（来自 `backend/app/parsers/sentence_splitter.py`）：

```rust
use fancy_regex::Regex as FancyRegex;
use std::collections::HashMap;

const TITLES: &[&str] = &[
    "mr", "mrs", "ms", "dr", "prof", "rev", "gen", "col", "maj", "capt", "lt",
    "cmdr", "sgt", "st", "jr", "sr", "esq", "hon", "messrs", "mme", "mlle",
];

const GENERAL_ABBREVIATIONS: &[&str] = &[
    "e.g", "i.e", "etc", "vs", "v", "viz", "al", "ca", "cf", "ibid", "id",
    "inc", "ltd", "corp", "co", "assn", "dept", "univ", "fig", "figs",
    "no", "nos", "vol", "vols", "p", "pp", "ch", "sec", "ed", "eds", "trans",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "ave", "blvd", "rd", "sq", "apt",
];

/// Protect decimals/acronyms/titles/abbreviations behind __TOK_N__ placeholders.
fn protect_tokens(text: &str) -> (String, HashMap<String, String>) {
    let mut placeholders: HashMap<String, String> = HashMap::new();
    let mut counter = 0usize;
    let mut out = text.to_string();

    let mut sub = |out: &mut String, re: &FancyRegex, counter: &mut usize, ph: &mut HashMap<String, String>| {
        let mut next = String::with_capacity(out.len());
        let mut last = 0usize;
        if let Ok(Some(matches)) = re.find_iter(out).collect::<Result<Vec<_>, _>>() {
            for m in matches {
                let (s, e) = (m.start(), m.end());
                next.push_str(&out[last..s]);
                let token = format!("__TOK_{}__", *counter);
                *counter += 1;
                ph.insert(token.clone(), m.as_str().to_string());
                next.push_str(&token);
                last = e;
            }
        }
        next.push_str(&out[last..]);
        *out = next;
    };
    // 1. decimals 2. acronym chains 3. single-capital-initials 4. titles 5. general abbreviations
    // （按 Python _protect_tokens 的五个正则逐条构造 FancyRegex，循环调用 sub）
    // ... 实现见下方说明
    (out, placeholders)
}
```

> 实现说明（执行者照此落地）：五个正则与 Python 语义一一对应——
> 1. `\b\d+\.\d+\b`
> 2. `\b(?:[A-Za-z]\.){2,}`
> 3. `\b[A-Z]\.(?=\s+[A-Z])`
> 4. 每个 title：`(?i)\b({title})\.(?=\s+["'“‘]?[a-zA-Z0-9])`
> 5. 每个 abbr：`(?i)\b({abbr})\.(?=\s*[,;:]|\s+["'“‘]?[a-z0-9]|\s+[A-Z][a-z])`
> fancy-regex 支持 `(?=` lookahead 与 `(?i)`。恢复顺序无需保证（HashMap + replace 每个占位符）。
> 省略号折叠：`Regex::new(r"\.{3,}")` → `"…"`；还原时把 `…` 替换回 `"..."`。

断句主函数：用 fancy-regex 拆分 `([.?!…]+["'”’)\]]*)\s+(?=["'“‘A-Z0-9—]|$)`，
按 Python 的 parts 配对重组逻辑（i += 2 / i += 1 循环），再做对话归属合并
（下一句以 `[a-z]` 开头则 `curr + " " + next`），最后还原占位符、过滤空串；
若结果为空返回 `[cleaned]`。

`split_paragraphs_and_sentences`：`\r\n|\r` 归一为 `\n`，`Regex::new(r"\n\s*\n")`
分段（空结果则退化为按单 `\n` 分段——对应 Python 的 fallback），strip 后构造
Paragraph/SentenceUnit，编号 `p{n}` / `p{n}_s{n}`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cargo test --lib splitter 2>&1 | tail -8`
Expected: 3 passed。若 `test_precision_sentence_splitting` 断言失败，对照 Python 行为逐正则排查（优先怀疑占位符还原顺序与 lookahead 边界）。

- [ ] **Step 5: 在 lib.rs 注册模块**

`lib.rs` 顶部 `mod db;` 后加 `mod splitter;`（pub 供后续 task 使用）。

- [ ] **Step 6: Commit**

```bash
git add src-tauri/src/splitter.rs src-tauri/src/lib.rs
git commit -m "feat: precision sentence splitter ported from python (tdd)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: markdown.rs — Markdown/TXT 清洗（TDD）

**Files:**
- Create: `src-tauri/src/markdown.rs`
- Test: 内联 `#[cfg(test)]`

**Interfaces:**
- Produces: `pub fn strip_markdown(input: &str) -> String` — 保留段落空行结构，剥离行内标记

- [ ] **Step 1: 写失败测试**

`src-tauri/src/markdown.rs`:

```rust
pub fn strip_markdown(_input: &str) -> String {
    String::new() // TODO Task 4
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strips_headers_emphasis_links() {
        let md = "# Chapter 1\n\nIt was a **dark** and *stormy* night — see [the wiki](https://example.com) for more.\n\n> A quote line\n\n```\ncode fence\n```\n\nPlain tail.";
        let out = strip_markdown(md);
        assert!(out.contains("Chapter 1"));
        assert!(out.contains("It was a dark and stormy night — see the wiki for more."));
        assert!(!out.contains("**"));
        assert!(!out.contains("](http"));
        assert!(!out.contains("```"));
        assert!(!out.contains("> A quote"));
        // paragraph structure preserved: at least 3 separated blocks
        let blocks: Vec<&str> = out.split("\n\n").collect();
        assert!(blocks.len() >= 3, "got {:?}", blocks);
        assert!(out.contains("Plain tail."));
    }

    #[test]
    fn test_plain_text_passthrough() {
        let txt = "Call me Ishmael.\n\nSome years ago.";
        assert_eq!(strip_markdown(txt), txt);
    }

    #[test]
    fn test_inline_code_and_images() {
        let out = strip_markdown("Use `foo.py` here.\n\n![portrait](img.png) Captain Ahab.");
        assert!(out.contains("Use foo.py here."));
        assert!(out.contains("portrait Captain Ahab."));
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cargo test --lib markdown 2>&1 | tail -8`
Expected: 3 FAIL

- [ ] **Step 3: 实现清洗**

替换空实现。处理顺序（顺序很重要：先围栏代码块，再行内）：

```rust
use regex::Regex;

pub fn strip_markdown(input: &str) -> String {
    let normalized = input.replace("\r\n", "\n").replace('\r', '\n');

    // 1. Drop fenced code blocks entirely (fence lines removed, keep inner text
    //    is NOT wanted for fiction; fence blocks are rarely used in novels — drop whole block).
    let fenced = Regex::new(r"(?s)```[^\n]*\n.*?```").unwrap();
    let no_fences = fenced.replace_all(&normalized, "");

    let mut out_lines: Vec<String> = Vec::new();
    for line in no_fences.lines() {
        let mut l = line.to_string();
        // 2. Header hashes
        let hdr = Regex::new(r"^\s{0,3}#{1,6}\s+").unwrap();
        l = hdr.replace(&l, "").to_string();
        // 3. Blockquote marker
        let bq = Regex::new(r"^\s{0,3}>\s?").unwrap();
        l = bq.replace(&l, "").to_string();
        // 4. Images ![alt](url) -> alt  (before links)
        let img = Regex::new(r"!\[([^\]]*)\]\([^)]*\)").unwrap();
        l = img.replace_all(&l, "${1}").to_string();
        // 5. Links [text](url) -> text
        let link = Regex::new(r"\[([^\]]+)\]\([^)]*\)").unwrap();
        l = link.replace_all(&l, "${1}").to_string();
        out_lines.push(l);
    }

    let joined = out_lines.join("\n");

    // 6. Inline emphasis: **bold**, __bold__, *it*, _it_, `code`
    let bold1 = Regex::new(r"\*\*([^*]+)\*\*").unwrap();
    let bold2 = Regex::new(r"__([^_]+)__").unwrap();
    let ital1 = Regex::new(r"\*([^*\n]+)\*").unwrap();
    let ital2 = Regex::new(r"(?m)(?<![A-Za-z0-9])_([^_\n]+)_(?![A-Za-z0-9])").unwrap();
    let code = Regex::new(r"`([^`\n]+)`").unwrap();

    let mut out = joined;
    for re in [bold1, bold2, ital1, ital2, code] {
        out = re.replace_all(&out, "${1}").to_string();
    }

    // 7. Collapse runs of 3+ blank lines
    let multi = Regex::new(r"\n{3,}").unwrap();
    multi.replace_all(&out, "\n\n").trim().to_string()
}
```

> 注意 italic `_` 规则用了 lookbehind，`regex` crate 不支持 —— 改用 `fancy_regex::Regex`
> 处理 ital2（或改写为捕获组形式 `(^|[^A-Za-z0-9])_([^_\n]+)_(?![A-Za-z0-9])` →
> `${1}${2}`，用普通 regex 即可，推荐后者避免双库混用）。执行者按推荐改写。

- [ ] **Step 4: 运行测试确认通过**

Run: `cargo test --lib markdown 2>&1 | tail -8`
Expected: 3 passed

- [ ] **Step 5: 注册模块 + Commit**

`lib.rs` 加 `mod markdown;`

```bash
git add src-tauri/src/markdown.rs src-tauri/src/lib.rs
git commit -m "feat: markdown/txt inline-markup stripper (tdd)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: prompts.rs — 提示词与 Schema 平移

**Files:**
- Create: `src-tauri/src/prompts.rs`

**Interfaces:**
- Produces:
  - `pub const SYSTEM_PROMPT: &str`
  - `pub fn build_paragraph_analysis_prompt(paragraph_id: &str, paragraph_text: &str, sentences_meta: &[(String, String)], glossary_context: &str) -> String`（元组 = (sentence_id, original)）
  - `pub fn build_single_sentence_deep_prompt(sentence_id: &str, target_sentence: &str, paragraph_context: &str, glossary_context: &str) -> String`

- [ ] **Step 1: 平移三个常量/函数**

从 `backend/app/services/prompt_templates.py` 逐字平移（纯字符串搬运，无逻辑）：
- `SYSTEM_PROMPT`（Python 三引号字符串原样，UTF-8）
- `build_paragraph_analysis_prompt`：f-string → format!，句子列表格式
  `- ID: {id} | 原文: {orig}`，整体骨架（含 `"""{paragraph_text}"""`）原样
- `build_single_sentence_deep_prompt`：同上；注意 Python 源码里
  `{{"sentences": [...]}}` 转义后实际输出是 `{"sentences": [...]}`，format! 中写作
  `{{"sentences": [...]}}`
- `STRUCTURED_OUTPUT_SCHEMA` 不移植：调用方走 OpenAI 兼容 `response_format: json_object`
  （与现 Python 行为一致，schema 从未随请求发送）

- [ ] **Step 2: 编译 + smoke 断言**

在 `prompts.rs` 加一个最小单测钉住格式占位：

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_paragraph_prompt_contains_parts() {
        let p = build_paragraph_analysis_prompt(
            "p1",
            "Call me Ishmael.",
            &[("p1_s1".to_string(), "Call me Ishmael.".to_string())],
            "【全书统一专有名词与术语表（必须严格遵循一致译名）】：\n- Ishmael [主角]: 以实玛利",
        );
        assert!(p.contains("Paragraph ID: p1"));
        assert!(p.contains("- ID: p1_s1 | 原文: Call me Ishmael."));
        assert!(p.contains("以实玛利"));
        assert!(p.contains("{\"sentences\": [...]}"));
    }
}
```

Run: `cargo test --lib prompts 2>&1 | tail -5`
Expected: 1 passed

- [ ] **Step 3: 注册模块 + Commit**

`lib.rs` 加 `mod prompts;`

```bash
git add src-tauri/src/prompts.rs src-tauri/src/lib.rs
git commit -m "feat: port prompt templates to rust

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: glossary.rs — 术语表（TDD）

**Files:**
- Create: `src-tauri/src/glossary.rs`
- Test: 内联（用内存 SQLite，不碰真实 DB）

**Interfaces:**
- Produces:
  - `pub fn get_document_glossary(conn: &Connection, doc_id: &str) -> Result<Vec<GlossaryItem>, String>`
  - `pub fn add_glossary_item(conn: &Connection, doc_id: &str, term: &str, canonical_translation: &str, category: &str, notes: &str) -> Result<(), String>`
  - `pub fn format_glossary_for_prompt(conn: &Connection, doc_id: &str) -> Result<String, String>`
  - `#[derive(Serialize)] pub struct GlossaryItem { pub term: String, pub category: String, pub canonical_translation: String, pub notes: String }`
  - 签名带 `conn` 参数（区别于 Python 版的全局连接），便于测试与 command 复用

- [ ] **Step 1: 写失败测试**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE glossary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL, term TEXT NOT NULL,
                category TEXT DEFAULT '专有名词',
                canonical_translation TEXT NOT NULL, notes TEXT);",
        )
        .unwrap();
        conn
    }

    #[test]
    fn test_glossary_add_and_format() {
        let conn = mem_db();
        add_glossary_item(&conn, "d1", "Ishmael", "以实玛利", "主角", "圣经典例").unwrap();
        add_glossary_item(&conn, "d1", "Cato", "加图", "典故人物", "").unwrap();
        let items = get_document_glossary(&conn, "d1").unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].term, "Ishmael");
        let snippet = format_glossary_for_prompt(&conn, "d1").unwrap();
        assert!(snippet.contains("以实玛利"));
        assert!(snippet.contains("Ishmael [主角]: 以实玛利 (圣经典例)"));
        // empty doc
        let empty = format_glossary_for_prompt(&conn, "nope").unwrap();
        assert!(empty.contains("暂无预设术语表"));
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cargo test --lib glossary 2>&1 | tail -5`
Expected: FAIL（函数未定义）

- [ ] **Step 3: 实现（对照 glossary.py 语义）**

`add_glossary_item`：INSERT 四元组（term/translation strip，空 notes 存 ""）。
`get_document_glossary`：按 id ASC 查询，notes 为 NULL 时取 ""。
`format_glossary_for_prompt`：空表返回 `"暂无预设术语表（请遵循通用经典翻译规范）。"`；
否则首行 `"【全书统一专有名词与术语表（必须严格遵循一致译名）】："` + 每条
`"- {term} [{category}]: {canonical_translation}{notes_str}"`（notes 非空时加 ` ({notes})`）。

- [ ] **Step 4: 运行测试确认通过 + 注册 + Commit**

Run: `cargo test --lib glossary 2>&1 | tail -5`
Expected: 1 passed

`lib.rs` 加 `mod glossary;`

```bash
git add src-tauri/src/glossary.rs src-tauri/src/lib.rs
git commit -m "feat: glossary store and prompt formatting (tdd)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: llm.rs — 离线引擎 + reqwest 客户端（TDD，含 Review Focus #3/#5）

**Files:**
- Create: `src-tauri/src/llm.rs`
- Test: 内联

**Interfaces:**
- Consumes: `prompts::`（Task 5）、`glossary::format_glossary_for_prompt` 产出的字符串
- Produces:
  - `pub struct SentenceAnalysis { pub sentence_id: String, pub original: String, pub translation: String, #[serde(skip_serializing_if = "Option::is_none")] pub overall_tone: Option<String>, #[serde(skip_serializing_if = "Option::is_none")] pub grammar_analysis: Option<GrammarAnalysis>, pub vocabulary_and_phrases: Vec<VocabItem>, pub idioms_and_conventions: Vec<IdiomItem> }`
  - `pub struct GrammarAnalysis { pub structure: String, pub components: Vec<GrammarComponent> }`、
    `pub struct GrammarComponent { pub element: String, pub role: String }`、
    `pub struct VocabItem { pub token: String, pub pos: String, pub literal_meaning: String, #[serde(skip_serializing_if = "Option::is_none")] pub cultural_background: Option<String> }`、
    `pub struct IdiomItem { pub expression: String, pub usage: String }`
    （全部 `#[derive(Debug, Clone, Serialize, Deserialize)]`，字段名 lowerCamel 与
    schemas.py 对齐——实际均为 snake_case，serde 默认即可，前端字段名不变）
  - `pub async fn analyze_paragraph_structured(provider_cfg: &ProviderCfg, paragraph_id: &str, paragraph_text: &str, sentences_meta: &[(String, String)], glossary_context: &str) -> Vec<SentenceAnalysis>`
  - `pub async fn analyze_single_sentence_deep(provider_cfg: &ProviderCfg, sentence_id: &str, target_sentence: &str, paragraph_context: &str, glossary_context: &str) -> SentenceAnalysis`
  - `#[derive(Clone)] pub struct ProviderCfg { pub provider: String, pub api_key: String, pub base_url: String, pub model_name: String, pub temperature: f64, pub mock_mode: bool }`
  - `pub fn is_mock(cfg: &ProviderCfg) -> bool`（mock_mode || api_key 为空）

- [ ] **Step 1: 写失败测试（离线引擎 schema 一致性 + 降级 + ID 对齐）**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    fn mock_cfg() -> ProviderCfg {
        ProviderCfg {
            provider: "mock".into(),
            api_key: String::new(),
            base_url: String::new(),
            model_name: "gpt-4o-mini".into(),
            temperature: 0.2,
            mock_mode: true,
        }
    }

    #[test]
    fn test_is_mock_rules() {
        let mut c = mock_cfg();
        assert!(is_mock(&c));
        c.mock_mode = false;
        assert!(is_mock(&c), "empty api_key still mock");
        c.api_key = "sk-x".into();
        assert!(!is_mock(&c));
        c.mock_mode = true;
        assert!(is_mock(&c), "mock_mode wins");
    }

    #[test]
    fn test_curated_ishmael_exact_match() {
        let cfg = mock_cfg();
        let out = futures_block(analyze_paragraph_structured(
            &cfg,
            "p1",
            "Call me Ishmael.",
            &[("p1_s1".into(), "Call me Ishmael.".into())],
            "",
        ));
        assert_eq!(out.len(), 1);
        let a = &out[0];
        assert_eq!(a.sentence_id, "p1_s1");
        assert_eq!(a.translation, "叫我以实玛利吧。");
        let comps = &a.grammar_analysis.as_ref().unwrap().components;
        assert!(comps.iter().any(|c| c.role.contains("谓语")));
        assert!(comps.iter().any(|c| c.role.contains("宾语")));
        assert_eq!(a.vocabulary_and_phrases[0].token, "Ishmael");
        assert!(a.vocabulary_and_phrases[0].literal_meaning.len() > 0);
        assert!(a.idioms_and_conventions[0].expression.len() > 0);
    }

    #[test]
    fn test_heuristic_fallback_svo() {
        let cfg = mock_cfg();
        let orig = "The old man carefully navigated the treacherous strait near the harbor.";
        let out = futures_block(analyze_paragraph_structured(
            &cfg, "p2", orig, &[("p2_s1".into(), orig.into())], "",
        ));
        let a = &out[0];
        assert_eq!(a.translation, format!("【译文】{orig}"));
        assert!(!a.grammar_analysis.as_ref().unwrap().components.is_empty());
        assert!(a.vocabulary_and_phrases.iter().any(|v| v.token == "Treacherous" || v.token == "Navigated" || v.token == "Harbor"));
    }

    #[test]
    fn test_unreachable_endpoint_falls_back_to_heuristic() {
        // Review Focus #3: unreachable endpoint + non-mock cfg -> heuristic result, not error.
        let cfg = ProviderCfg {
            provider: "custom".into(),
            api_key: "sk-test".into(),
            base_url: "http://127.0.0.1:1".into(), // nothing listens here
            model_name: "test".into(),
            temperature: 0.2,
            mock_mode: false,
        };
        let out = futures_block(analyze_paragraph_structured(
            &cfg,
            "p3",
            "A simple sentence.",
            &[("p3_s1".into(), "A simple sentence.".into())],
            "",
        ));
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].sentence_id, "p3_s1");
        assert!(out[0].translation.starts_with("【译文】"));
    }

    #[test]
    fn test_llm_response_with_wrong_sentence_id_is_dropped() {
        // Review Focus #5: LLM 幻觉改 ID -> 按请求 ID 对齐，幻觉丢弃。
        let raw = r#"{"sentences":[{"sentence_id":"p9_s99","original":"A simple sentence.","translation":"幻觉译文","overall_tone":"x","grammar_analysis":{"structure":"陈述句","components":[]},"vocabulary_and_phrases":[],"idioms_and_conventions":[]}]}"#;
        let parsed: serde_json::Value = serde_json::from_str(raw).unwrap();
        let sents = parse_llm_sentences(&parsed);
        assert!(sents.is_empty(), "hallucinated id must not map to p3_s1");
    }
}
```

测试需要阻塞执行 async —— `#[tokio::test]` 亦可，但 Cargo.toml 尚无 tokio 依赖。
`tauri::async_runtime::block_on` 可用（tauri 内置 tokio）。
在测试里写 `fn futures_block<F: std::future::Future>(f: F) -> F::Output { tauri::async_runtime::block_on(f) }`。

- [ ] **Step 2: 运行确认失败**

Run: `cargo test --lib llm 2>&1 | tail -8`
Expected: 编译失败（类型/函数未定义）——TDD 的"失败"标准包含编译失败

- [ ] **Step 3: 实现**

结构：
1. `CURATED_OFFLINE_KNOWLEDGE`：`once_cell` 不引入——用 `fn curated_lookup(s: &str) -> Option<SentenceAnalysis>`，内部 `match s { "Call me Ishmael." => ... }` 三个分支手写 `serde_json::json!` → 反序列化，或直接构造结构体。三条数据从 `llm_engine.py` 的字典逐字段搬运（translation / overall_tone / grammar_analysis / vocabulary_and_phrases / idioms_and_conventions 全部字段，中文文案一字不差）。
2. `pub fn heuristic_sentence_analysis(sentence_id: &str, original: &str) -> SentenceAnalysis`：翻译 `_heuristic_sentence_analysis`（首词从句/祈使/陈述三分支、S-V-O 切片、≥6 字母词取前 2 个、`【译文】`前缀、固定 tone 文案）。
3. `parse_llm_sentences(parsed: &serde_json::Value) -> Vec<SentenceAnalysis>`：取 `["sentences"]` 数组反序列化为 `Vec<SentenceAnalysis>`（`#[serde(default)]` 容忍缺字段：`overall_tone`/`grammar_analysis` Option + `vocabulary_and_phrases`/`idioms_and_conventions` 标 `#[serde(default)]`）。
4. `async fn call_llm(cfg: &ProviderCfg, messages: Vec<serde_json::Value>, json_mode: bool) -> Result<String, String>`：
   - base_url 缺省映射：deepseek → `https://api.deepseek.com/v1`（model `deepseek-chat`）、gemini → `https://generativelanguage.googleapis.com/v1beta/openai`（model `gemini-1.5-flash`）、custom/openai/其他 → `https://api.openai.com/v1`
   - **claude 分支（Review：修正 Python 版 404 bug）**：POST `{base_url 或 https://api.anthropic.com/v1}/messages`，headers `x-api-key` + `anthropic-version: 2023-06-01`，payload `{model, max_tokens: 4096, temperature, system, messages}`（system 单独字段，messages 只含 user），响应取 `json["content"][0]["text"]`
   - 其余分支：POST `{base_url}/chat/completions`，`Authorization: Bearer {key}`，`response_format: {"type":"json_object"}`（json_mode 时），响应取 `json["choices"][0]["message"]["content"]`
   - reqwest client：`Client::builder().timeout(Duration::from_secs(60)).build()`
5. `analyze_paragraph_structured`：`is_mock` → 逐句 curated/heuristic；否则构造 messages（SYSTEM_PROMPT + build_paragraph_analysis_prompt）→ call_llm → clean_json（剥 ```json 围栏）→ parse_llm_sentences → **按请求 sentences_meta 的 id 对齐过滤**（丢弃幻觉 ID——测试钉住）→ 失败/异常一律降级逐句 heuristic。
6. `analyze_single_sentence_deep`：同构；mock 直接 heuristic；成功解析取 sentences[0]。

- [ ] **Step 4: 运行测试确认通过**

Run: `cargo test --lib llm 2>&1 | tail -8`
Expected: 5 passed

- [ ] **Step 5: 注册模块 + Commit**

`lib.rs` 加 `mod llm;`

```bash
git add src-tauri/src/llm.rs src-tauri/src/lib.rs
git commit -m "feat: llm engine — offline heuristics, openai-compatible + claude clients (tdd)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: commands/documents.rs — 文档五命令（TDD，含 Review Focus #1/#2）

**Files:**
- Create: `src-tauri/src/commands/mod.rs`
- Create: `src-tauri/src/commands/documents.rs`
- Test: 内联（内存库直测核心函数；command 薄封装）

**Interfaces:**
- Consumes: `db::with_conn`、`splitter::split_paragraphs_and_sentences`、`markdown::strip_markdown`、`glossary::add_glossary_item`
- Produces（全部 `#[tauri::command]`，放 `commands::documents`）:
  - `list_documents(app) -> Result<Vec<DocumentMeta>, String>`
  - `get_document(app, doc_id: String) -> Result<serde_json::Value, String>`
  - `upload_document(app, title: String, content: String) -> Result<serde_json::Value, String>`（前端已读文本；title 为文件名 stem）
  - `load_sample(app, sample_name: String) -> Result<serde_json::Value, String>`
  - `delete_document(app, doc_id: String) -> Result<serde_json::Value, String>`
  - `#[derive(Serialize)] pub struct DocumentMeta { pub id: String, pub title: String, pub author: String, pub file_type: String, pub total_paragraphs: i64, pub total_sentences: i64, pub created_at: String }`
  - 核心逻辑函数（可测）：`pub fn ingest_text(conn: &Connection, doc_id: &str, title: &str, author: &str, file_type: &str, raw_content: &str) -> Result<(i64, usize), String>`（建 documents/paragraphs/sentences 行，返回 (used_created_at_unused, total_paragraphs)——实际返回 total_paragraphs 即可）；`pub fn validate_upload(content: &str) -> Result<(), String>`（空/乱码校验）

- [ ] **Step 1: 写失败测试**

`commands/documents.rs` 内联测试：

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                author TEXT DEFAULT '未知作者', file_type TEXT NOT NULL,
                raw_content TEXT, created_at TEXT NOT NULL);
            CREATE TABLE paragraphs (id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                chapter_id TEXT DEFAULT 'ch_1', order_index INTEGER NOT NULL,
                raw_text TEXT NOT NULL);
            CREATE TABLE sentences (id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                paragraph_id TEXT NOT NULL, order_index INTEGER NOT NULL,
                original TEXT NOT NULL, translation TEXT, deep_analysis_json TEXT,
                updated_at TEXT);",
        )
        .unwrap();
        conn
    }

    #[test]
    fn test_validate_upload_rejects_empty() {
        assert!(validate_upload("").is_err());
        assert!(validate_upload("   \n\n  \n").is_err());
    }

    #[test]
    fn test_validate_upload_rejects_garbled_utf8() {
        // Review Focus #1: GBK bytes mis-decoded by FileReader -> U+FFFD soup.
        let garbled = "\u{FFFD}\u{FFFD}\u{FFFD}\u{FFFD}一些乱码\u{FFFD}";
        let err = validate_upload(garbled).unwrap_err();
        assert!(err.contains("编码"), "got: {err}");
        assert!(validate_upload("Call me Ishmael. Some years ago.").is_ok());
    }

    #[test]
    fn test_ingest_text_creates_rows() {
        let conn = mem_db();
        let total = ingest_text(
            &conn, "doc_x", "Test Book", "Author", "md",
            "Call me Ishmael.\n\nSome years ago, I went to sea.",
        )
        .unwrap();
        assert_eq!(total, 2);
        let n_docs: i64 = conn.query_row("SELECT COUNT(*) FROM documents", [], |r| r.get(0)).unwrap();
        let n_paras: i64 = conn.query_row("SELECT COUNT(*) FROM paragraphs", [], |r| r.get(0)).unwrap();
        let n_sents: i64 = conn.query_row("SELECT COUNT(*) FROM sentences", [], |r| r.get(0)).unwrap();
        assert_eq!((n_docs, n_paras, n_sents), (1, 2, 2));
        // sentence id convention: {doc_id}_{paragraph_id}_{...} -> doc_x_p1_s1
        let sid: String = conn.query_row("SELECT id FROM sentences LIMIT 1", [], |r| r.get(0)).unwrap();
        assert_eq!(sid, "doc_x_p1_s1");
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cargo test --lib documents 2>&1 | tail -6`
Expected: 编译失败（函数未定义）

- [ ] **Step 3: 实现**

要点（对照 `routers/documents.py`）：
- `validate_upload`：trim 后为空 → `Err("文件内容为空，请导入有效的 Markdown 或 TXT 文件。")`；
  统计 U+FFFD（`content.chars().filter(|&c| c == '\u{FFFD}').count()`），非零且占比
  `> 0.5%`（`count as f64 / total_chars as f64 > 0.005`，正常文本也可能含一个替换符）
  → `Err("文件编码异常：检测到无法解码的字符（可能不是 UTF-8），请将文件另存为 UTF-8 后重试。")`
- `ingest_text`：`split_paragraphs_and_sentences(strip_markdown(raw_content))`；
  `doc_id = format!("doc_{}", &uuid::Uuid::new_v4().simple().to_string()[..8])`；
  paragraphs 表 `chapter_id='ch_1'`，sentence id 为 `{doc_id}_p{n}_s{m}`
  （注意 Python 里 DB 的 sentence id 是 `{doc_id}_p1_s1` 格式——`paragraph_id` 列存
  `{doc_id}_p1`）；
  `created_at` 用 chrono `Local::now().format("%Y-%m-%d %H:%M:%S")`
- `list_documents`：照搬聚合 SQL（LEFT JOIN ×2 + GROUP BY + ORDER BY created_at DESC）
- `get_document`：主行 + paragraphs + sentences 三层循环组装（照搬 Python 返回结构，
  JSON 键名与 Python 完全一致：`id/title/author/file_type/created_at/glossary/paragraphs`
  ，paragraphs 内 `paragraph_id/order_index/raw_text/sentences`，sentences 内
  `sentence_id/original/translation/has_deep_analysis`）
- `upload_document` command：validate → ingest → 返回
  `{"status":"success","doc_id","title","total_paragraphs"}`；title 前端传文件 stem
- `load_sample`：样例文本 `include_str!`（Task 11 转换 .md 时改路径，本任务先引
  `../../data/samples/moby_dick_ch1.txt` 等原 TXT——内容一致，Task 11 切换）；
  doc_id `sample_{name}`；已存在 → `{"status":"already_loaded",...}`；glossary 种子
  （moby_dick 三条 / gatsby 两条，中文文案照搬）
- `delete_document`：DELETE 四表（documents/paragraphs/sentences/glossary，同 Python），
  返回 `{"status":"deleted","doc_id"}`
- command 均为薄封装：`db::with_conn(&app, |conn| ...)`；`load_sample`/`upload_document`
  标注 `#[tauri::command(async)]`（ingest 是同步 DB 写，放 async 线程池避免卡 UI——
  tauri 默认在单独线程跑 async command）

- [ ] **Step 4: 运行测试确认通过**

Run: `cargo test --lib documents 2>&1 | tail -6`
Expected: 3 passed

- [ ] **Step 5: 注册命令 + Commit**

`lib.rs`：

```rust
mod commands;
// ...
.invoke_handler(tauri::generate_handler![
    health,
    commands::documents::list_documents,
    commands::documents::get_document,
    commands::documents::upload_document,
    commands::documents::load_sample,
    commands::documents::delete_document,
])
```

`commands/mod.rs`:

```rust
pub mod documents;
```

```bash
git add src-tauri/src/commands/
git commit -m "feat: document commands — upload/sample/list/get/delete (tdd)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: commands/analysis.rs — 分析两命令（缓存 + 预取）

**Files:**
- Create: `src-tauri/src/commands/analysis.rs`
- Modify: `src-tauri/src/commands/mod.rs`（加 `pub mod analysis;`）
- Modify: `src-tauri/src/lib.rs`（handler 注册）

**Interfaces:**
- Consumes: `llm::analyze_paragraph_structured / analyze_single_sentence_deep / ProviderCfg / is_mock`、`glossary::format_glossary_for_prompt`、`db::with_conn`
- Produces:
  - `#[tauri::command] pub async fn analyze_paragraph(app: tauri::AppHandle, paragraph_id: String) -> Result<serde_json::Value, String>`
  - `#[tauri::command] pub async fn get_sentence_analysis(app: tauri::AppHandle, sentence_id: String) -> Result<serde_json::Value, String>`
  - `pub fn load_provider_cfg(conn: &Connection) -> ProviderCfg`（settings 表 → ProviderCfg；temperature 解析失败回退 0.2；"true"/"false" → bool）

**本任务无新单测**（核心逻辑 llm.rs 已测；本文件是缓存编排，靠 Task 11 冒烟覆盖）。
保持行为对照 `routers/analysis.py`：

- [ ] **Step 1: 实现 analyze_paragraph**

流程（严格对照 Python）：
1. `with_conn`：查 paragraphs 行，无 → `Err("段落未找到")`
2. 查 sentences（ORDER BY order_index）；若所有句 translation 均非空 → 组装缓存返回
   `{"paragraph_id", "sentences": [...], "source": "cache"}`（sentence 项含
   `sentence_id/original/translation/has_deep_analysis/deep_analysis`——deep_analysis 是
   `deep_analysis_json` 的 parse，NULL 则 null）
3. 否则 `load_provider_cfg` + `format_glossary_for_prompt`，调
   `analyze_paragraph_structured`（注意：它需要 `sentences_meta: &[(String,String)]`）
4. 组装：LLM 结果按 DB sentence_id 对齐；命中项 UPDATE sentences（translation +
   `serde_json::to_string(&parsed)` + updated_at），组装
   `has_deep_analysis: true`；未命中项 translation 用旧值或 `"【解析中】"`，
   has_deep_analysis false
5. commit 后，`tauri::async_runtime::spawn` 预取下一段（`prefetch_next_paragraph`：
   查 `order_index + 1` 段，若无/已有 translation 跳过；调同一分析函数写缓存，
   失败仅 eprintln）
6. 返回 `{"paragraph_id", "sentences": [...], "source": "generated"}`

- [ ] **Step 2: 实现 get_sentence_analysis**

1. 查 sentences 行，无 → `Err("句子未找到")`
2. `deep_analysis_json` 非空 → parse 成功直接返回该 JSON（含 sentence_id/original/
   translation 等，同 Python）
3. 否则取段落 raw_text + doc_id → glossary → `analyze_single_sentence_deep` →
   UPDATE 缓存 → 返回结果

- [ ] **Step 3: 编译 + 注册**

Run: `cargo check 2>&1 | tail -3`
Expected: PASS

`commands/mod.rs` 加 `pub mod analysis;`；`lib.rs` handler 注册两条命令。

- [ ] **Step 4: Commit**

```bash
git add src-tauri/src/commands/ src-tauri/src/lib.rs
git commit -m "feat: analysis commands with cache + background prefetch

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: vocabulary.rs + commands（TDD，含 Review Focus #4）

**Files:**
- Create: `src-tauri/src/vocab.rs`
- Create: `src-tauri/src/commands/vocabulary.rs`
- Modify: `src-tauri/src/commands/mod.rs`、`lib.rs`

**Interfaces:**
- Consumes: `db::with_conn`
- Produces:
  - `#[derive(Serialize, Clone)] pub struct VocabRecord { pub id: i64, pub word: String, pub pos: String, pub translation: String, pub sentence_context: String, pub sentence_id: String, pub cultural_background: String, pub created_at: String }`
  - `pub fn add_vocabulary_item(conn, word, pos, translation, sentence_context, sentence_id, cultural_background) -> Result<i64, String>`
  - `pub fn list_vocabulary_items(conn) -> Result<Vec<VocabRecord>, String>`
  - `pub fn delete_vocabulary_item(conn, vocab_id: i64) -> Result<(), String>`
  - `pub fn export_vocabulary_anki_tsv(conn) -> Result<String, String>`
  - commands: `get_vocabulary / add_vocabulary / delete_vocabulary / export_anki_tsv`
    （add_vocabulary 入参 `word, translation, pos?, sentence_context?, sentence_id?, cultural_background?`——tauri command 参数用 `Option<String>`，返回 `{"status":"success","id","word"}`；`export_anki_tsv` 返回 TSV 字符串）

- [ ] **Step 1: 写失败测试**

`vocab.rs` 内联：

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE vocabulary_book (
                id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT NOT NULL, pos TEXT,
                translation TEXT NOT NULL, sentence_context TEXT, sentence_id TEXT,
                cultural_background TEXT, created_at TEXT NOT NULL);",
        )
        .unwrap();
        conn
    }

    #[test]
    fn test_add_list_delete_roundtrip() {
        let conn = mem_db();
        let id = add_vocabulary_item(&conn, "Ishmael", "专有名词", "以实玛利（人名）",
            "Call me Ishmael.", "p1_s1", "《圣经》亚伯拉罕之子").unwrap();
        let items = list_vocabulary_items(&conn).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].word, "Ishmael");
        assert_eq!(items[0].pos, "专有名词");
        assert!(!items[0].created_at.is_empty());
        delete_vocabulary_item(&conn, id).unwrap();
        assert!(list_vocabulary_items(&conn).unwrap().is_empty());
    }

    #[test]
    fn test_anki_tsv_structure_and_highlight() {
        let conn = mem_db();
        add_vocabulary_item(&conn, "Ishmael", "专有名词", "以实玛利（人名）",
            "Call me Ishmael.", "p1_s1", "《圣经》亚伯拉罕之子").unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        assert!(tsv.starts_with("#separator:tab\n#html:true\n#tags column:5\n"));
        let lines: Vec<&str> = tsv.lines().collect();
        assert_eq!(lines.len(), 4); // 3 header + 1 row
        let cols: Vec<&str> = lines[3].split('\t').collect();
        assert_eq!(cols.len(), 5);
        assert!(cols[0].contains("Ishmael"));                    // front
        assert!(cols[0].contains("<b style='color:#3b82f6;'>Ishmael</b>")); // highlighted ctx
        assert!(cols[1].contains("以实玛利"));                    // back
        assert_eq!(cols[3], "以实玛利（人名）");                  // meaning column
        assert_eq!(cols[4], "ReadyReader ForeignLiterature");    // tags column
    }

    #[test]
    fn test_anki_tsv_escapes_special_chars() {
        // Review Focus #4: tabs/newlines/quotes inside fields must not break TSV.
        let conn = mem_db();
        add_vocabulary_item(&conn, "test \"quoted\"", "名", "释义\t带tab\n带换行",
            "He said \"quoted\" today.", "", "").unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        let data_lines: Vec<&str> = tsv.lines().skip(3).collect();
        assert_eq!(data_lines.len(), 1, "embedded newline must not create extra row: {:?}", tsv);
        let cols: Vec<&str> = data_lines[0].split('\t').collect();
        assert_eq!(cols.len(), 5);
    }

    #[test]
    fn test_highlight_case_insensitive() {
        let conn = mem_db();
        add_vocabulary_item(&conn, "ishmael", "名", "释", "Call me ISHMAEL now.", "", "").unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        assert!(tsv.contains("<b style='color:#3b82f6;'>ishmael</b>"));
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cargo test --lib vocab 2>&1 | tail -6`
Expected: 编译失败

- [ ] **Step 3: 实现**

- CRUD 照搬 `vocab_service.py`（pos/contexts NULL→""，created_at
  `%Y-%m-%d %H:%M:%S`，ORDER BY id DESC）
- `export_vocabulary_anki_tsv`：手写 TSV（**不用 csv crate**——字段内含 tab/换行/
  引号时按 Python csv.QUOTE_MINIMAL 语义：字段含 `\t`/`\n`/`"`/`\r` 时整体加双引号，
  内部 `"` 翻倍；测试 #4 钉住换行不产生新行）。头部三行
  `#separator:tab\n#html:true\n#tags column:5\n` 固定。行 = front/back/word/meaning/tags
  五列。front/back HTML 模板逐字对照 `vocab_service.py:80-86`（含
  `<b style='color:#3b82f6;'>` 高亮，ctx 中大小写不敏感子串替换——regex
  `(?i)escaped(word)`，替换为高亮版本；无 ctx 或不含词则原样）。tags 固定
  `ReadyReader ForeignLiterature`

- [ ] **Step 4: 运行测试确认通过**

Run: `cargo test --lib vocab 2>&1 | tail -6`
Expected: 4 passed

- [ ] **Step 5: commands 接线 + 注册 + Commit**

`commands/vocabulary.rs`：四个薄封装 command（add_vocabulary 校验 word/translation
非空 → `Err("生词与释义不能为空")`；delete_vocabulary 入参 i64）。

`lib.rs` 注册 `commands::vocabulary::{get_vocabulary, add_vocabulary, delete_vocabulary, export_anki_tsv}`。

```bash
git add src-tauri/src/vocab.rs src-tauri/src/commands/
git commit -m "feat: vocabulary notebook + anki tsv export (tdd)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: commands/settings.rs + 样例转 markdown + 图标

**Files:**
- Create: `src-tauri/src/commands/settings.rs`
- Create: `src-tauri/assets/sample_moby_dick.md`、`src-tauri/assets/sample_the_great_gatsby.md`
- Create: `src-tauri/icons/`（tauri icon 生成）
- Modify: `src-tauri/src/commands/documents.rs`（include_str 切到 .md 资产）
- Modify: `src-tauri/tauri.conf.json`（bundle.icon）
- Modify: `src-tauri/src/commands/mod.rs`、`lib.rs`

**Interfaces:**
- Consumes: `db::{get_setting 直接 SQL, set_setting}`（本任务在 settings.rs 内实现两个小助手，不放 db.rs，避免 db.rs 变杂）
- Produces:
  - `#[tauri::command] pub fn get_settings(app) -> Result<serde_json::Value, String>`（返回对象带类型转换：true/false→bool、数字→f64，同 Python get_all_settings）
  - `#[tauri::command] pub fn update_settings(app, provider: String, api_key: Option<String>, base_url: Option<String>, model_name: Option<String>, temperature: f64, mock_mode: bool) -> Result<serde_json::Value, String>`

- [ ] **Step 1: 实现 settings 命令**

- `get_settings`：读全表 → 每值按 Python `get_all_settings` 的转换规则
  （"true"/"false" → bool；含 "." 可解析 → f64；否则 int 尝试 → 字符串）
- `update_settings`：provider 必写；其余 Option 值 Some 才写（同 Python 语义）；
  temperature/mode 用 `to_string()`；返回 `{"status":"success","settings":{...}}`

- [ ] **Step 2: 样例转 markdown**

```bash
mkdir -p src-tauri/assets
cp data/samples/moby_dick_ch1.txt src-tauri/assets/sample_moby_dick.md
cp data/samples/the_great_gatsby_ch1.txt src-tauri/assets/sample_the_great_gatsby.md
```

两个文件头部改成 markdown 结构（`CHAPTER 1. Loomings.` 前加 `# `，其余内容不动——
这些文件本身几乎没有 markdown 语法，strip_markdown 后与原 TXT 输入逐字节等价，
保证断句行为不变）：

moby_dick.md 头三行改为：
```markdown
# MOBY-DICK; or, THE WHALE.

# CHAPTER 1. Loomings.
```

gatsby.md 头两行改为：
```markdown
# THE GREAT GATSBY

# CHAPTER 1
```

`commands/documents.rs` 中 `load_sample` 的 include_str 切换：

```rust
const SAMPLE_MOBY: &str = include_str!("../../assets/sample_moby_dick.md");
const SAMPLE_GATSBY: &str = include_str!("../../assets/sample_the_great_gatsby.md");
```

- [ ] **Step 3: 图标（Edge headless 渲染 + tauri icon）**

```bash
mkdir -p src-tauri/icons
```

1. 写 SVG 源 `src-tauri/assets/icon_source.svg`（1024×1024，渐变圆角方 + 白色粗体
   "R"，视觉对照 make_icon.swift：#8C382B → #D9731F 的 -45° 渐变、220 圆角、
   内描边 rgba(255,255,255,0.2)）。SVG 文字是矢量定义，无 Pillow 参与。
2. Edge headless 截图 PNG：`"/Applications/Microsoft Edge.app/Contents/Microsoft Edge" --headless --screenshot=icon_1024.png --window-size=1024,1024 --default-background-color=00000000 file://$(pwd)/icon_source.svg`（若本机无 Edge，用 `microsoft-edge` 或确认路径；产出核对 1024×1024）
3. `cargo tauri icon src-tauri/assets/icon_1024.png`（自动产出 icons/ 全套）
4. tauri.conf.json 恢复图标配置：`"icon": ["icons/32x32.png", "icons/128x128.png", "icons/128x128@2x.png", "icons/icon.icns", "icons/icon.ico"]`

- [ ] **Step 4: 编译 + 全量测试**

Run: `cd src-tauri && cargo test 2>&1 | tail -5 && cargo check 2>&1 | tail -3`
Expected: 全部 passed（splitter 3 + markdown 3 + prompts 1 + glossary 1 + llm 5 + documents 3 + vocab 4 = 20 tests）

- [ ] **Step 5: 注册 + Commit**

`lib.rs` 注册 settings 两命令。

```bash
git add src-tauri/
git commit -m "feat: settings commands, markdown samples, app icons

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: 前端接线 — api.js 重写 + Anki 保存对话框 + index.html 文案

**Files:**
- Modify: `frontend/js/api.js`（重写）
- Modify: `frontend/js/vocabulary.js:105-108`（exportAnki 方法）
- Modify: `frontend/index.html:134-135`（dropzone 提示与 accept）
- Modify: `frontend/index.html:121`（注释里 TXT/EPUB/PDF 字样顺带改）

**Interfaces:**
- Consumes: 全部 11 个 command（Tasks 8-11 注册的最终签名）
- Produces: `export const api` —— 11 个方法名与返回结构不变（调用方 5 个 JS 文件零改动）

- [ ] **Step 1: 重写 api.js**

```javascript
// API client for Ready Reader backend (Tauri IPC)
const { invoke } = window.__TAURI__.core;

async function call(cmd, args = {}) {
  try {
    return await invoke(cmd, args);
  } catch (err) {
    // Tauri commands reject with String errors
    throw new Error(typeof err === 'string' ? err : (err?.message || JSON.stringify(err)));
  }
}

export const api = {
  async getDocuments() {
    return call('list_documents');
  },

  async getDocument(docId) {
    return call('get_document', { docId });
  },

  async uploadDocument(file) {
    // Read file content in webview, send text to Rust (no multipart needed)
    const text = await file.text();
    const stem = file.name.replace(/\.[^.]+$/, '');
    return call('upload_document', { title: stem, content: text });
  },

  async loadSample(sampleName = 'moby_dick') {
    return call('load_sample', { sampleName });
  },

  async deleteDocument(docId) {
    return call('delete_document', { docId });
  },

  async analyzeParagraph(paragraphId) {
    return call('analyze_paragraph', { paragraphId });
  },

  async getSentenceAnalysis(sentenceId) {
    return call('get_sentence_analysis', { sentenceId });
  },

  async getVocabulary() {
    return call('get_vocabulary');
  },

  async addVocabulary(payload) {
    return call('add_vocabulary', payload);
  },

  async deleteVocabulary(vocabId) {
    return call('delete_vocabulary', { vocabId });
  },

  async getSettings() {
    return call('get_settings');
  },

  async updateSettings(payload) {
    return call('update_settings', payload);
  }
};
```

> 注意：tauri command 参数名在 Rust 侧是 snake_case 时，invoke 传 camelCase
> （tauri 2 默认转换）；Rust 侧参数 `doc_id` ↔ JS `{ docId }`。执行时若
> command 报 "invalid args"，检查 Rust 签名是否用了 `rename_all` —— 默认行为
> 即 camelCase，无需额外配置。

- [ ] **Step 2: vocabulary.js 导出改对话框保存**

`exportAnki`（vocabulary.js:105-108）替换为：

```javascript
  async exportAnki() {
    try {
      const tsv = await call('export_anki_tsv');
      const { save } = window.__TAURI__.dialog;
      const { writeTextFile } = window.__TAURI__.fs;
      const path = await save({
        defaultPath: 'ready_reader_anki_cards.txt',
        filters: [{ name: 'Anki TSV', extensions: ['txt'] }]
      });
      if (!path) return; // user cancelled
      await writeTextFile(path, tsv);
      this.showToast('Anki 牌组导出文件已保存', 'success');
    } catch (e) {
      this.showToast(`导出失败: ${e.message}`, 'error');
    }
  }
```

vocabulary.js 头部第 1 行改为 `import { api } from './api.js';` 保持，并补
`const { invoke: call } = window.__TAURI__.core;` —— 更简单：直接在方法内用
`window.__TAURI__.core.invoke('export_anki_tsv')`，不新增模块级 import。

（vocabulary.js 是唯一在此文件里直接调 ipc 的；其余全走 api.js。）

- [ ] **Step 3: index.html 文案三处**

- 行 121 注释 `<!-- Modal 1: Document Upload (TXT / EPUB / PDF) -->` → `(Markdown / TXT)`
- 行 134 dropzone-hint：`全面支持 .TXT, .EPUB (电子书自动解包), .PDF 格式` →
  `支持 .md / .markdown / .txt 纯文本原著`
- 行 135 accept：`.txt,.epub,.pdf` → `.md,.markdown,.txt`

- [ ] **Step 4: 全量编译 + tauri dev 手动验收**

Run: `cd src-tauri && cargo test 2>&1 | tail -3`

Run: `cargo tauri dev`，走查清单：
1. 启动无白屏；旧库迁移提示（首次）
2. 自动加载白鲸记样例；双栏渲染，§编号正常
3. 点击"⚡ 一键解析本段"→ mock 引擎出译文，右栏对齐
4. 点击句子 → 透视镜抽屉展开，句法切片徽章渲染
5. 透视镜内"+ 加入生词本"成功；生词本 modal 列表出现该词
6. 导出 Anki → 系统保存对话框 → 文件落盘、内容含 `#separator:tab`
7. 设置面板读写 roundtrip；切换 mock_mode 保存成功
8. 导入一个 .md 文件成功；导入一个空文件被拒（toast 报错）
9. 暗色主题切换；窗口缩放 min 960×600 生效

Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: wire frontend to tauri ipc — api.js rewrite, anki save dialog

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: 全链路冒烟测试（Rust 集成测试）

**Files:**
- Create: `src-tauri/tests/smoke.rs`

**Interfaces:**
- Consumes: `ready_reader_lib` 导出的核心函数（需要 lib.rs 中相关模块 `pub mod`：splitter/markdown/glossary/vocab/llm 已 pub；documents 的 `ingest_text`/`validate_upload` pub）

- [ ] **Step 1: 写集成测试（mock 全链路，临时目录 DB）**

```rust
// src-tauri/tests/smoke.rs
use ready_reader_lib::smoke_support::*;
use rusqlite::Connection;

#[test]
fn full_pipeline_mock_mode() {
    // temp db
    let dir = std::env::temp_dir().join(format!("rr_smoke_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let db_file = dir.join("smoke.db");
    let conn = Connection::open(&db_file).unwrap();
    conn.execute_batch(include_str!("../src/schema_minimal.sql")).unwrap();

    // 1. ingest sample (uses include_str asset via lib export)
    let total = ingest_text(&conn, "sample_moby_dick", "白鲸记 (Moby-Dick)", "Herman Melville", "md", SAMPLE_MOBY).unwrap();
    assert!(total > 5);

    // 2. analyze paragraph (mock) — direct call with cfg
    let cfg = default_mock_cfg();
    let doc = get_document_json(&conn, "sample_moby_dick").unwrap();
    let p1_id = doc["paragraphs"][0]["paragraph_id"].as_str().unwrap().to_string();
    let sents_meta: Vec<(String, String)> = doc["paragraphs"][0]["sentences"]
        .as_array().unwrap()
        .iter()
        .map(|s| (s["sentence_id"].as_str().unwrap().to_string(), s["original"].as_str().unwrap().to_string()))
        .collect();
    let out = tauri::async_runtime::block_on(analyze_paragraph_structured(
        &cfg, &p1_id, doc["paragraphs"][0]["raw_text"].as_str().unwrap(), &sents_meta, "",
    ));
    assert_eq!(out.len(), sents_meta.len());

    // 3. vocab + anki export
    add_vocabulary_item(&conn, "Ishmael", "专有名词", "以实玛利", "Call me Ishmael.", "p1_s1", "圣经").unwrap();
    let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
    assert!(tsv.contains("#separator:tab"));
    assert!(tsv.contains("Ishmael"));

    std::fs::remove_dir_all(&dir).ok();
}
```

> 实现说明：`src/schema_minimal.sql` 抽出与 db.rs 相同的建表 SQL（db.rs 的
> `execute_batch` 也改用 `include_str!` 引同一文件，避免双份漂移）。lib.rs 增加
> `pub mod smoke_support;` 薄转发（re-export `ingest_text`、`SAMPLE_MOBY`、
> `default_mock_cfg`、`get_document_json`、`add_vocabulary_item`、
> `export_vocabulary_anki_tsv`、`analyze_paragraph_structured`），或在相关模块上
> 直接 `pub mod` 后 `use ready_reader_lib::...`。执行者二选一，保证 tests/ 可引用。

- [ ] **Step 2: 运行**

Run: `cd src-tauri && cargo test --test smoke 2>&1 | tail -5`
Expected: 1 passed

- [ ] **Step 3: Commit**

```bash
git add src-tauri/tests/ src-tauri/src/schema_minimal.sql src-tauri/src/lib.rs
git commit -m "test: full-pipeline smoke test in mock mode

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 14: 打包验证（macOS）+ 清理过时资产

**Files:**
- Delete: `backend/`、`desktop/`、`Ready Reader.app/`、`launch.command`、`start.sh`、
  `test_system.py`、`.venv/`、`data/ready_reader.db`（确认迁移后）、`data/samples/`
  （已内嵌）、`Ready Reader.app` 残留
- Modify: `README.md`（重写，见 Task 15；本任务仅删除，README 单独任务）

**Interfaces:**
- Consumes: Task 12 验收通过的完整应用

- [ ] **Step 1: macOS 打包**

Run: `cd src-tauri && cargo tauri build 2>&1 | tail -10`
Expected: 产出 `target/release/bundle/macos/Ready Reader.app` 与
`dmg/Ready Reader_1.0.0_aarch64.dmg`（版本号随 tauri.conf.json）。
打开 .app 双栏加载、解析、导出全部正常（重复 Task 12 走查 2-6 项）。

- [ ] **Step 2: 删除过时资产（先逐一确认内容已被替代）**

```bash
cd /Users/han/coding/personal/ready
# 确认新 DB 已存在于应用数据目录且包含迁移数据
ls -la ~/Library/"Application Support"/com.ready.reader/ready_reader.db
# 删除（git 已跟踪历史，可随时找回）
git rm -r backend desktop "Ready Reader.app" launch.command start.sh test_system.py
rm -rf .venv
# data 目录：samples 已内嵌进二进制；db 已迁移
git rm -r data
```

> 注意：`git rm -r "Ready Reader.app"` 若因二进制过大被 git 拒绝跟踪历史，仍按普通
> rm 处理。删除前每个目标都已在上文确认被 Rust 实现替代：
> - `backend/` → src-tauri 全部 commands
> - `desktop/main.swift` → Tauri 壳
> - `Ready Reader.app/` → cargo tauri build 产物
> - `launch.command` / `start.sh` → tauri dev / 直接双击 .app
> - `test_system.py` → cargo test（20 tests + smoke）
> - `.venv` / `data/ready_reader.db` → 不再需要（db 已迁移）

- [ ] **Step 3: 更新 .gitignore（移除 legacy 段）**

`.gitignore` 收敛为：

```gitignore
src-tauri/target/
node_modules/
.DS_Store
```

- [ ] **Step 4: 最终全量验证**

Run: `cd src-tauri && cargo test 2>&1 | tail -4`
Expected: 21+ passed（20 单测 + smoke）

Run: `git status`
Expected: clean（或仅 README 待改）

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove legacy python/swift stack after tauri migration

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 15: README 重写为使用指南

**Files:**
- Modify: `README.md`（整文件替换）

**Interfaces:**
- Consumes: 最终形态的工程（src-tauri + frontend）

- [ ] **Step 1: 重写 README.md**

```markdown
# Ready Reader — 外语原著精读与拆解系统

跨平台桌面应用（macOS / Windows / Linux），基于 Tauri 2 + 纯 Rust 后端。
结合 Markdown 原著导入、LLM 结构化解析与双向联动交互界面，用于外语原著精读。

## ✨ 功能

- **双栏对照精读**：左栏原文、右栏中文精译，句级双向悬停/点击联动
- **语法透视镜**：点击任意句子，展开句法主干切片（S/V/O/OC/Adv/Attr）、
  语境锁定词义、文化典故与习语解析
- **全书术语表**：人名地名译名全书一致（内置样例已预置）
- **生词本 & Anki 导出**：一键收藏生词，导出 Anki 可导入的 TSV 牌组
- **离线演示引擎**：未配置 API Key 时内置启发式解析，开箱即用
- **本地持久化**：SQLite 存储，全部数据留在本机

## 🚀 快速开始

### 方式一：直接运行安装包（推荐）

1. 从发布页下载对应平台安装包并安装：
   - macOS：`.dmg`（Apple Silicon）
   - Windows：`.msi`
   - Linux：`.deb` 或 `.AppImage`
2. 启动 Ready Reader，首次启动会自动加载《白鲸记》样例。

### 方式二：从源码运行（开发模式）

前置要求：[Rust](https://rustup.rs) 1.77+；Linux 需 webkit2gtk-4.1 等系统依赖
（见 Tauri 文档）。

```bash
# 安装 tauri-cli（一次性）
cargo install tauri-cli --version "^2"

# 开发模式运行（热重载）
cargo tauri dev

# 构建安装包
cargo tauri build
# 产物：src-tauri/target/release/bundle/{macos,dmg,deb,appimage}/
```

## 📖 使用指南

### 1. 导入你的书

- 点击顶部 **"📤 导入原著"**，选择或拖入 `.md` / `.markdown` / `.txt` 文件
  （UTF-8 编码）
- 文件内容即原著正文；`#` 标题、`*` 强调等 Markdown 标记会被自动清理，
  空行分段的段落结构会完整保留
- 内置《白鲸记》《了不起的盖茨比》第一章样例，点击顶栏按钮即可加载

### 2. 精读与解析

- 每个段落左侧有 **"⚡ 一键解析本段"** 按钮，点击后右栏逐句生成精译
- 鼠标悬停任意句子，左右栏对应句同步高亮
- **点击任意句子**打开右侧"语法透视镜"：
  - 句法切片：主干成分逐个徽章展示
  - 词法速查：重点词的语境释义（非词典泛义）
  - 典故解析：成语、隐喻、文化背景
  - 每个词条旁 **"+ 加入生词本"** 一键收藏
- 点击句子后下一段会自动在后台预取解析，连续阅读无等待

### 3. 生词本与 Anki

- 顶栏 **"📚 生词本 & Anki"** 打开生词本，可查看、删除收藏
- **"⚡ 一键导出至 Anki"** 选择保存位置后生成 TSV 文件
- 在 Anki 中：文件 → 导入，选择该 TSV，字段分隔符选 Tab，允许 HTML

### 4. 配置 LLM（可选）

默认使用内置离线演示引擎（零配置、零成本、结果为预置解析+启发式切片）。
要获得真正的整段翻译与深度解析：

1. 顶栏 **"⚙️ 设置"** 打开配置
2. 选择提供商：DeepSeek / OpenAI / Gemini / Claude / 自定义兼容端点（Ollama 等）
3. 填入 API Key（仅存储在本机 SQLite，不上传）
4. 关闭"优先离线演示模式"，保存

支持的提供商与默认模型：

| 提供商 | 默认端点 | 默认模型 |
|---|---|---|
| DeepSeek | api.deepseek.com/v1 | deepseek-chat |
| OpenAI | api.openai.com/v1 | gpt-4o-mini |
| Gemini | generativelanguage.googleapis.com/v1beta/openai | gemini-1.5-flash |
| Claude | api.anthropic.com/v1 | claude-3-5-sonnet |
| 自定义 | 自填 Base URL | 自填 |

解析失败时自动回退离线引擎，阅读体验不会中断。

## 🗂️ 数据位置

| 平台 | 数据库路径 |
|---|---|
| macOS | `~/Library/Application Support/com.ready.reader/ready_reader.db` |
| Windows | `%APPDATA%\com.ready.reader\ready_reader.db` |
| Linux | `~/.local/share/com.ready.reader/ready_reader.db` |

删除该文件即完全重置应用（生词本、文档、设置全部清空）。

## 🏗️ 架构

```
ready/
├── src-tauri/          # Tauri 2 + Rust 后端
│   ├── src/
│   │   ├── commands/   # documents / analysis / vocabulary / settings
│   │   ├── db.rs       # SQLite（bundled）schema 与迁移
│   │   ├── splitter.rs # 精准断句器（缩写/引语保护）
│   │   ├── markdown.rs # Markdown 清洗
│   │   ├── llm.rs      # LLM 客户端 + 离线引擎
│   │   ├── vocab.rs    # 生词本 + Anki 导出
│   │   ├── glossary.rs # 术语表
│   │   └── prompts.rs  # 提示词模板
│   └── assets/         # 内置样例与图标源
└── frontend/           # 原生 HTML/CSS/JS（无框架无构建链）
```

## 🧪 测试

```bash
cd src-tauri && cargo test
```

## 开发约定

- 后端仅 Rust（src-tauri/）；前端无 npm 依赖
- `rusqlite` bundled / `reqwest` rustls —— 无系统级依赖
- 提交信息遵循 conventional commits
```

- [ ] **Step 2: 校对指南与实际行为一致**

逐条对照 Task 12 走查结果：按钮文案、菜单名、保存对话框行为、模型默认值。
有出入以实际 UI 为准改 README。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite readme as cross-platform user guide

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```
