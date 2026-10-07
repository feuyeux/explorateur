# 🎵 哼唱识谱 (Humming-to-Score)

将人声哼唱音频实时转换为结构化乐谱 —— **五线谱、简谱、MIDI 与 MusicXML**。

跨平台桌面应用，基于 **Tauri 2**。全部转谱推理在应用内本地完成，不依赖任何云端服务；
可选的本地 Node 服务仅用于浏览器调试。

> 📖 完整的操作步骤、功能说明与故障排查，请阅读 **[docs/使用指南.md](docs/使用指南.md)**。

---

## 🚀 快速开始

前置依赖：Rust 1.77.2+ 与 tauri-cli 2.x（`cargo install tauri-cli --version "^2"`
或 `brew install tauri-cli`）。命令一律在**本项目根目录（`humming/`）**执行。

```bash
cd humming           # 进入 humming 项目根目录（从仓库根目录执行）
npm install          # 仅首次需要：装 vendor 构建依赖（esbuild / tfjs）
cargo tauri dev      # 开发模式
cargo tauri build    # 打包当前平台安装包
```

`cargo tauri dev` / `cargo tauri build` 会通过 `tauri.conf.json` 的
`beforeDevCommand` / `beforeBuildCommand` 自动构建 vendor 产物，无需手工先跑构建脚本。

构建产物：

```
src-tauri/target/release/bundle/macos/HummingScore.app
src-tauri/target/release/bundle/dmg/HummingScore_1.0.0_aarch64.dmg
```

### 浏览器调试（可选）

```bash
npm run serve        # 本地静态服务，访问 http://127.0.0.1:3000
```

此模式**不含** Tauri 外壳，仅用于快速验证前端逻辑。

### 常用命令

| 命令 | 执行目录 | 作用 |
| --- | --- | --- |
| `cargo tauri dev` | 根 | 桌面应用开发模式（前端热重载 + Rust 重编译） |
| `cargo tauri build` | 根 | 打包 `.app` + `.dmg`（或其他平台安装包） |
| `cargo test` | `src-tauri/` | Rust 测试 |
| `cargo clippy --all-targets` | `src-tauri/` | Rust 静态检查 |
| `cargo fmt` | `src-tauri/` | Rust 格式化 |
| `npm test` | 根 | 前端回归测试（声学流水线 + 乐理编辑 + 试听链路 + 界面契约） |
| `npm run build:vendor` | 根 | 单独重建 Basic Pitch vendor bundle 与模型 |
| `npm run serve` | 根 | 仅启动本地静态服务（浏览器调试） |
| `npm install` | 根 | 首次安装 vendor 构建依赖 |

测试覆盖：

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_pipeline.mjs` | 三种转谱引擎的音符提取、调性推断、MIDI/MusicXML 导出 |
| `tests/test_note_editor.mjs` | 乐理与音符编辑：音高修改、时值对齐、小节划分、增删音符 |
| `tests/test_synthesizer.mjs` | 试听链路：发声拓扑、音符时序、音高换算、停止复位、suspended 上下文恢复 |
| `tests/test_ui_contract.mjs` | 界面契约：确保 `main.js` 引用的元素 id 与样式在 `index.html`/CSS 中真实存在 |

> 界面契约测试用于防止一类隐蔽回归：元素 id 缺失时事件监听会被静默跳过，
> 界面照常渲染但按钮全部失效，且控制台无任何报错。

---

## 🎼 功能速览

### 1. 现场哼唱录音

1. 点击 **「开始哼唱录音」**，首次运行会请求麦克风权限。
2. 监控屏实时显示示波器波形、音高调音计（音名 + Hz + 音分偏差）与 VU 电平表。
3. 点击「停止录音」，系统自动完成转谱并渲染乐谱。

> 可开启「节拍器」并用 BPM 滑杆设定速度，帮助哼出稳定的节奏。

### 2. 导入音频文件识谱

支持 `.m4a`（iPhone 语音备忘录默认格式）、`.wav`、`.mp3`、`.aac`、`.ogg`。

三种方式任选：

- 点击 **「📥 载入 m4a / 录音文件」** 选择本地文件
- **直接拖拽**音频文件到窗口任意位置
- 点击 **「📱 载入内置 m4a 样本」** 使用随附的 `src/assets/demo_twinkle.m4a`

载入后可点击 **「▶ 播放原声」** 试听并拖拽进度条，然后点击绿色的
**「🎼 开始识谱」** 执行转谱。

### 3. 选择转谱引擎

| 引擎 | 说明 |
| --- | --- |
| 🧠 **Spotify Basic Pitch**（默认） | 内置 tfjs 神经网络推理，多音识别能力最强。**无需联网、无需 Python** |
| 🎵 **Magenta SPICE** | 面向单音人声的声学模型，对清唱哼唱较友好 |
| 🎙️ **pYIN + Viterbi** | 纯 DSP 本地算法，零依赖、极速，适合快速预览 |

引擎不可用时会自动回退到 pYIN，界面状态栏会**如实显示**实际使用的引擎。

### 4. 视图与导出

顶部 Tabs 可切换 **五线谱 / 简谱 / 钢琴卷帘** 三种视图。
钢琴卷帘中青色曲线为连续 F0 轨迹，绿色方块为量化后的音符。

识别完成后可直接导出标准文件：

- **MIDI** (`.mid`) —— 导入任意 DAW 继续编辑
- **MusicXML 3.1** (`.musicxml`) —— 导入 MuseScore、Sibelius 等制谱软件

### 5. 音符微调

点击乐谱中任意音符即可进入编辑模式，或用快捷键：

| 快捷键 | 功能 |
| --- | --- |
| `←` / `→` | 选择上一个 / 下一个音符 |
| `↑` / `↓` | 升 / 降半音 |
| `Shift` + `↑` / `↓` | 升 / 降八度 |
| `空格` | 试听当前选中音符 |
| `Delete` / `Backspace` | 删除当前音符 |

编辑栏还提供时值切换、附点、插入音符与休止符等操作。
节拍器、BPM、拍号与量化网格的调整会**实时重算**并重新渲染乐谱。

---

## 🧠 技术架构

### 五阶段转谱流水线

```
① 采集/解码 (WebAudio)  →  ② 声学转谱引擎  →  ③ 切分与量化
   →  ④ 调性推断 (Krumhansl-Schmuckler)  →  ⑤ 乐谱渲染与导出
```

### 目录结构

```
funny/
├── src/                      # 前端源码 = frontendDist
│   ├── index.html            # 界面骨架
│   ├── main.js               # 入口脚本与主控制器交互
│   ├── css/style.css         # 浅色主题样式
│   ├── assets/
│   │   └── demo_twinkle.m4a  # 内置演示音频
│   ├── dsp/                  # 阶段一~三：预处理 / 音高追踪 / 切分量化 / 转谱引擎
│   ├── audio/                # 录音监控、节拍器、拟真钢琴合成器、示例音频合成
│   ├── render/               # 五线谱 / 简谱 / 钢琴卷帘渲染器
│   ├── export/               # MIDI 与 MusicXML 导出器
│   ├── theory/               # 调性推断 (Krumhansl-Schmuckler)
│   └── vendor/               # 构建产物 (esbuild 打包的 Basic Pitch + tfjs 模型)
├── scripts/                   # 构建与调试脚本
│   ├── build_vendor.mjs       # vendor 构建脚本 (由 before*Command 调用)
│   └── serve.mjs              # 本地静态服务 (仅浏览器调试用，无后端逻辑)
├── tests/                    # 前端回归测试 (Node)
├── src-tauri/                # Tauri 2 桌面外壳 (Rust)
│   ├── assets/icon_source.html  # 图标源文件 → cargo tauri icon
│   ├── capabilities/         # 权限能力集
│   └── ...
└── docs/
    ├── 使用指南.md            # 日常操作、快捷键、故障排查
    ├── 设计/                 # 架构与设计决策
    └── 计划/                 # 实施计划
```

### 关键实现说明

**推理后端**：优先 WebGL，不可用时回退 CPU。**不使用 WASM 后端** —— tfjs 3.21 的
wasm 后端缺少 `tf.signal.frame` 算子支持，而 Basic Pitch 的 `prepareData` 依赖该算子，
会抛出 `Unknown dtype undefined`。

**主线程推理**：不使用 Web Worker。实测 tfjs 的 WebGL 计算在 Worker 中会挂起
（0.3s 音频卡死 >60s），且 macOS WKWebView 基本不支持 Worker 内 WebGL。
tfjs 的 GPU 调用均为 async，主线程在 GPU 操作之间会让出，界面不会冻结。

**vendor 构建**：`scripts/build_vendor.mjs` 用 esbuild 把 `@spotify/basic-pitch` + tfjs
打成免打包器可用的 IIFE bundle，并把 TFJS 模型拷到 `src/vendor/`，以 SHA-1 内容哈希之外的
增量策略（入口与依赖包 mtime）判断是否重建，源未变时跳过。该脚本挂在
`beforeDevCommand` / `beforeBuildCommand` 上，构建产物**不纳入版本管理**
（见 `.gitignore`），干净克隆后首次 `cargo tauri dev` 会自动重建。

**无前端产物副本**：`frontendDist` 直接指向 `src/`，打包时前端资源内嵌进二进制。
历史上曾用 `src-tauri/www/` 存放一份前端副本并靠内容哈希同步，已移除 ——
双份源码必然漂移，且同步脚本一失效就会把过期内容打进发布包。

**CSP**：`src-tauri/tauri.conf.json` 中已放行 `'unsafe-eval'` 与 `blob:`，
以支持 tfjs 的动态代码求值与 Worker/Blob 资源加载。

---

## 与标准的差异

以下几项按工程需要偏离统一标准，理由如下：

| 项 | 本工程取值 | 原因 |
| --- | --- | --- |
| `package.json` 存在 | 是 | 有前端构建链（vendor 打包），需要 esbuild / tfjs 依赖 |
| `scripts/` 目录存在 | 是 | `build_vendor.mjs`（构建链）+ `serve.mjs`（浏览器调试静态服务） |
| `tests/` 目录存在 | 是 | 前端逻辑与 UI 契约测试用 Node 跑 |
| `src-tauri/Info.plist` 存在 | 是 | macOS 麦克风权限声明（`NSMicrophoneUsageDescription`），录哼唱必需 |
| `beforeDevCommand` / `beforeBuildCommand` | 均指向 `node scripts/build_vendor.mjs` | vendor bundle 是 gitignored 构建产物，必须先于 `cargo tauri dev/build` 生成 |
| CSP | 放行 `'unsafe-eval'`、`blob:` | tfjs 动态求值与 Blob 资源加载需要 |
| `app.withGlobalTauri` | `false` | 前端不调用任何 Tauri IPC，无需注入全局对象 |
| `src-tauri/tests/` 不存在 | 是（无） | Rust 侧只有窗口与 WebView，无业务逻辑可测；前端测试全在 `tests/` |

---

## 🛠 依赖与环境

| 组件 | 版本 | 必需性 |
| --- | --- | --- |
| Rust | 1.77.2+ | 必需 |
| tauri-cli | 2.x | 必需 |
| Node.js | 18+ | 仅 vendor 构建与前端测试需要 |
| Python | — | **不需要**（项目已无 Python 依赖） |

Basic Pitch 神经网络以 tfjs 完全运行在前端，桌面应用与浏览器模式均无需后端服务、
无需联网、无需 Python。

---

## 📄 许可

MIT