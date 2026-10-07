# Ready Reader — Tauri 2 跨平台重构设计（纯 Rust 后端）

日期：2026-10-07
状态：已实施

> ⚠️ **历史文档**：本文按当时的形态记录迁移决策，其中提到的 `frontend/` 目录布局
> 已在同日的工程标准化中统一为 `src/`，详见
> [工程标准化计划](../计划/2026-10-07-工程标准化.md)。技术决策本身
> （去 Python、仅支持 Markdown、纯 Rust 进程内后端）仍然有效。

## 1. 背景与目标

Ready Reader 现为 FastAPI(Python) + 原生 JS 前端 + Swift/Cocoa 桌面壳的三层结构，
只能运行于 Apple Silicon macOS。用户需要**跨平台桌面 App（macOS / Windows / Linux）**，
并明确决定：**摆脱 Python 技术栈**；输入格式**仅支持 Markdown**（.md 为主，.txt 兼容），
不再支持 EPUB / PDF。

成功标准：
- 单一 Rust 工程，`tauri build` 产出 macOS / Windows / Linux 安装包
- 无 Python、无 venv、无 localhost 端口依赖
- 前端除 `api.js` 外零改动；交互与视觉不变
- 现有生词本数据可无损迁移
- 断句、LLM 离线演示引擎、Anki 导出行为与现状一致

## 2. 总体架构

```
Tauri 2 App (Rust)
├─ Tauri commands  ←→  前端 (window.__TAURI__.core.invoke)
├─ rusqlite (features=["bundled"])   # SQLite 编译进二进制
├─ reqwest (rustls)                  # LLM API 调用，不走 webview
├─ serde / serde_json                # 结构化解析
└─ frontend/  (现有 HTML/CSS/JS，零框架，无构建链)
```

- 进程内 IPC（commands），**无 HTTP 服务、无端口**。
- 前端无网络请求（LLM 调用全部在 Rust 侧），CSP 最小化。
- 单工程跨平台：macOS (.app/.dmg)、Windows (.msi)、Linux (.deb/AppImage)。
  本机仅可验证 macOS；Windows/Linux 保证配置正确，实测留待有对应机器时进行。

## 3. 项目结构

```
ready/
├── src-tauri/
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── icons/                # tauri icon 生成
│   └── src/
│       ├── main.rs           # 入口
│       ├── lib.rs            # run() + command 注册
│       ├── db.rs             # 连接管理、schema、旧库迁移
│       ├── markdown.rs       # 轻量 markdown → 纯文本清洗
│       ├── splitter.rs       # 断句器（自 sentence_splitter.py 翻译）
│       ├── glossary.rs
│       ├── vocab.rs          # 生词本 + Anki TSV 导出
│       ├── llm.rs            # reqwest 客户端 + 离线启发式引擎
│       ├── prompts.rs        # SYSTEM_PROMPT / schema / prompt 模板平移
│       └── commands/
│           ├── documents.rs
│           ├── analysis.rs
│           ├── vocabulary.rs
│           └── settings.rs
├── frontend/                 # 原样保留；仅改 api.js
│   ├── index.html            # 3 处小改（见 §7）
│   ├── css/ js/
├── docs/设计/   # 本文档
└── README.md                 # 重写
```

删除清单（实现完成、迁移验证后）：`backend/`、`desktop/`、`Ready Reader.app/`、
`launch.command`、`start.sh`、`.venv/`、`test_system.py`、`data/ready_reader.db`（迁移后）、
`data/samples/`（内容内嵌进二进制后）。

## 4. 数据层

- `rusqlite` + `bundled`，连接参数：`journal_mode=WAL`、`foreign_keys=ON`。
- **表结构原样沿用**六表：documents / paragraphs / sentences / glossary /
  vocabulary_book / settings（含现有索引）。
- DB 位置：标准应用数据目录
  - macOS: `~/Library/Application Support/com.ready.reader/ready_reader.db`
  - Windows: `%APPDATA%\com.ready.reader\ready_reader.db`
  - Linux: `~/.local/share/com.ready.reader/ready_reader.db`
  （Tauri `app_data_dir` 统一解析）
- **迁移**：首次启动时若新位置无 DB 且旧 `data/ready_reader.db` 存在，则整文件拷贝；
  之后旧文件保留不删（由用户清理），日志提示迁移完成。
- 设置种子数据沿用（provider=mock, mock_mode=true 等）。

## 5. Commands（与现有 11 个端点 1:1）

| Command | 参数 → 返回 | 对应旧行为 |
|---|---|---|
| `list_documents` | — → Vec<DocumentMeta> | GET /api/documents（含段落/句子计数聚合 SQL） |
| `get_document` | doc_id → DocumentDetail | GET /api/documents/{id}（含 glossary + paragraphs + sentences） |
| `upload_document` | title, content(text) → UploadResult | POST /upload；改为前端读文本后传字符串，无 multipart |
| `load_sample` | sample_name("moby_dick"\|"the_great_gatsby") → LoadResult | POST /load_sample；样例文本 `include_str!` 内嵌，含 glossary 种子 |
| `delete_document` | doc_id → () | DELETE /api/documents/{id}（四表级联删除） |
| `analyze_paragraph` | paragraph_id → ParagraphAnalysis | POST /analysis/paragraph/{id}：缓存命中直接返回；否则 LLM → 写缓存 → **后台预取下一段**（tauri::async_runtime::spawn 替代 BackgroundTasks） |
| `get_sentence_analysis` | sentence_id → SentenceAnalysis | GET /analysis/sentence/{id}：Level 2 深度解析，命中缓存即返 |
| `get_vocabulary` | — → Vec<VocabRecord> | GET /api/vocabulary |
| `add_vocabulary` | payload → {id} | POST /api/vocabulary |
| `delete_vocabulary` | vocab_id → () | DELETE /api/vocabulary/{id} |
| `export_anki_tsv` | — → String | GET /export/anki：返回 Anki TSV 文本（含 #separator:tab 头、高亮 HTML），保存见 §7 |
| `get_settings` / `update_settings` | 同现有 GET/POST 语义 | settings 表读写 |

错误模型：command 返回 `Result<T, String>`；中文错误文案与现有一致
（"文档未找到"、"段落未找到"、"生词与释义不能为空"等）。

## 6. 后端逻辑移植要点

### 6.1 断句器 splitter.rs（自 sentence_splitter.py 逐条翻译）
- TITLES / GENERAL_ABBREVIATIONS 两个集合原样保留
- 保护-还原机制：小数、缩写串 (D.C., a.m.)、单字母缩写、头衔、通用缩写 →
  `__TOK_N__` 占位符 → 还原
- 省略号 `...` → `…` 单字符化，split 后还原为 `...`
- 断句正则 `([.?!…]+["'”’)\]]*)\s+(?=["'“‘A-Z0-9—]|$)`：
  Rust `regex` 不支持 lookahead —— 用**手写顺序扫描**（或 fancy-regex crate）实现同语义。
  选型：`fancy-regex`（支持 lookahead，改动最小、可对照原正则验证）。
- 对话归属合并：`"..." he said.` 下一句小写开头则合并
- `split_paragraphs_and_sentences`：`\n\s*\n` 分段 + p{n}/p{n}_s{n} 编号，语义不变
- **去掉 spaCy 分支**（Python 里 try-import 的可选依赖，Rust 版无此依赖）

### 6.2 LLM 引擎 llm.rs
- 离线引擎整体平移：`CURATED_OFFLINE_KNOWLEDGE` 三条精讲 + SVO 启发式拆解 +
  词汇挑选逻辑（≥6 字母词前 2 个等规则）
- `call_llm`：reqwest POST `{base_url}/chat/completions`，OpenAI 兼容；
  provider 缺省端点映射沿用（openai / deepseek / gemini(OpenAI 兼容层) / custom）
- **修正潜在 bug**：原 Python 对 `claude` provider 也走 Bearer + /chat/completions
  （Anthropic 实际是 x-api-key + /v1/messages，原代码会 404）。Rust 版为 claude
  单独分支：POST /v1/messages、头 x-api-key + anthropic-version，响应映射
  content[0].text，再把 JSON 文本交给同一解析管线。
- 超时 60s；失败降级离线引擎（与现一致），日志走 `log` + `tauri-plugin-log`
  （或先 println!，不引入额外插件，保持最小依赖）
- mock 判定：`mock_mode == true 或 api_key 为空` → 离线引擎

### 6.3 Markdown 清洗 markdown.rs
输入 `.md`/`.txt`，产出与旧 TXT 解析器同构的 `raw_content`：
- 段落结构保留：空行分段逻辑交给 splitter，不合并
- 去除：ATX 标题 `#{1,6} `、强调标记 `*`/`_`/`**`/`__`、行内代码反引号、
  链接 `[text](url)` → `text`、图片 `![alt](url)` → `alt`、
  围栏代码块 ``` 围栏行、引用块行首 `> `
- 不解析表格/HTML 块（原著小说场景 YAGNI），仅做行内标记剥离
- 上传校验：非空文本；`.md`/`.markdown`/`.txt` 之外扩展名拒绝并提示

### 6.4 Anki 导出 vocab.rs
- TSV 格式与 vocab_service.py 逐字段一致（#separator:tab / #html:true /
  #tags column:5；front/back HTML 含上下文高亮 `<b style='color:#3b82f6'>`）
- 词高亮：大小写不敏感子串替换（与原 re.IGNORECASE + re.escape 语义一致）

## 7. 前端改动（最小化）

1. **api.js 重写**（唯一大改）：11 个方法签名与返回结构不变，内部从 fetch 换成
   `window.__TAURI__.core.invoke('command_name', { args })`；
   错误 catch invoke 的 String rejection 后 throw Error（toast 文案不变）。
2. **vocabulary.js 一处**：`window.location.href = '/api/vocabulary/export/anki'` 改为
   invoke `export_anki_tsv` 拿文本 → `dialog.save`（tauri-plugin-dialog，JS API）选路径 →
   `writeTextFile`（tauri-plugin-fs），默认文件名 `ready_reader_anki_cards.txt`。
3. **index.html 三处**：
   - 上传 dropzone `accept=".txt,.epub,.pdf"` → `accept=".md,.markdown,.txt"`，
     提示文案改为支持 Markdown/TXT
   - 顶部 `file_type` 无 UI 变化；无其他改动
4. `withGlobalTauri: true`，无 npm 构建链；`frontendDist: "../frontend"`。
   绝对路径 `/css/main.css`、`/js/app.js` 在 tauri:// origin 下照常工作。
5. CSP：`default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:`
   （页面大量内联 style，需 unsafe-inline；脚本仅本地 module）。
6. localStorage（主题记忆）在 WKWebView/WebView2 中可用，不动。

## 8. 配置与打包

- `tauri.conf.json`：productName "Ready Reader"、identifier `com.ready.reader`、
  窗口 1360×920 / minSize 960×600、标题 "Ready Reader - 外语原著精读与拆解"
- 图标：单一 1024px 源图（渐变圆角方 + 白色 "R"，沿用现 make_icon.swift 视觉），
  文字渲染走 Edge headless 截图（遵守工作区规则：不用 Pillow 画字），
  `tauri icon` 生成全套平台图标
- 插件：tauri-plugin-dialog、tauri-plugin-fs（仅 Anki 导出保存用，scope 限定
  用户经 dialog 选择的路径）
- 打包目标：macOS .app/.dmg；Windows .msi；Linux .deb + AppImage

## 9. 测试

`cargo test`（对应 test_system.py 六用例平移）：
1. 精准断句：Mr./Dr./e.g./D.C./8.30/引语对话 4 断言（与原测试同文本同断言）
2. 段落分解：p1/p2 与 p1_s1 编号
3. 离线引擎 schema 一致性：谓语/宾语角色、词汇字段、idiom 字段
4. Glossary 写入与 prompt 格式化
5. 生词本增删查 + Anki TSV 内容断言（#separator:tab、词、释义）
6. Markdown 清洗：标题/强调/链接/代码块剥离

集成冒烟：mock 模式下 load_sample → get_document → analyze_paragraph →
get_sentence_analysis → add_vocabulary → export_anki_tsv 全链路（cargo test 内
用临时目录 DB）。

验收（本机）：`tauri dev` 手动走查——加载白鲸记、点击句子开透视镜、
生词本导出 Anki 文件落盘、设置面板切换 provider、暗色主题切换、窗口缩放。

## 10. 实施顺序（后续 writing-plans 展开）

1. git init + 初始提交（含本 spec）
2. `src-tauri` 脚手架 + db.rs（schema/迁移）+ settings commands
3. splitter.rs + markdown.rs + 单测
4. documents/analysis/vocabulary commands + 单测
5. llm.rs（离线引擎 + reqwest + claude 修正）
6. api.js/dialog/fs 前端接线
7. 全链路冒烟 + 图标 + tauri.conf 收尾
8. 删除旧 Python/Swift 资产 + README 重写

## 11. 明确不做（YAGNI）

- EPUB / PDF 解析（用户已裁掉）
- HTTP API 兼容层、多窗口、自动更新、代码签名（分发阶段另议）
- spaCy 或任何 NLP 重依赖
