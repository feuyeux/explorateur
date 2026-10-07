# 🎵 哼唱识谱（HummingScore）

将人声哼唱音频实时转换为结构化乐谱 —— **五线谱、简谱、MIDI 与 MusicXML**。

跨平台桌面应用，基于 **Tauri 2**。全部转谱推理在应用内本地完成，不依赖任何云端服务；
可选的本地 Node 服务仅用于浏览器调试。

> 📖 完整的操作步骤、功能说明与故障排查，见 **[docs/使用指南.md](docs/使用指南.md)**。

---

## 🚀 快速开始

前置依赖：Rust 1.77.2+ 与 tauri-cli 2.x（`cargo install tauri-cli --version "^2"`
或 `brew install tauri-cli`）。命令一律在**本项目根目录（`humming/`）**执行。

```bash
cd humming               # 进入 humming 项目根目录（从仓库根目录执行）
npm install              # 仅首次需要：装 vendor 构建依赖（esbuild / tfjs）
cargo tauri dev          # 开发模式
cargo tauri build        # 打包当前平台安装包
```

`cargo tauri dev` / `cargo tauri build` 会通过 `tauri.conf.json` 的
`beforeDevCommand` / `beforeBuildCommand` 自动构建 vendor 产物，无需手工先跑构建脚本。

构建产物：

```
src-tauri/target/release/bundle/macos/HummingScore.app
src-tauri/target/release/bundle/dmg/HummingScore_<版本>_<架构>.dmg
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
| `cargo tauri build` | 根 | 打包安装包 |
| `cargo test` | `src-tauri/` | Rust 测试（本工程 Rust 侧无业务逻辑，当前无测试） |
| `cargo clippy --all-targets` | `src-tauri/` | Rust 静态检查 |
| `cargo fmt` | `src-tauri/` | Rust 格式化 |
| `npm test` | 根 | 前端回归测试（声学流水线 + 乐理编辑 + 试听链路 + 界面契约 + 原声播放 + 端到端） |
| `npm run build:vendor` | 根 | 单独重建 Basic Pitch vendor bundle 与模型 |
| `npm run serve` | 根 | 仅启动本地静态服务（浏览器调试） |
| `npm install` | 根 | 首次安装 vendor 构建依赖 |

---

## ✨ 功能

1. **现场哼唱录音**：点击「开始哼唱录音」，监控屏实时显示示波器波形、音高调音计（音名 + Hz + 音分偏差）与 VU 电平表；停止后自动转谱并渲染乐谱
2. **导入音频文件识谱**：支持 `.m4a`（iPhone 语音备忘录默认格式）、`.wav`、`.mp3`、`.aac`、`.ogg`；可选文件、拖拽到窗口任意位置，或用内置示例
3. **对照原声播放**：识别完成后可先「▶ 播放原声」试听并拖拽进度条，再决定是否修改
4. **三引擎可切换**：Spotify Basic Pitch（默认，tfjs 神经网络）/ Magenta SPICE / pYIN + Viterbi；不可用时自动回退 pYIN，状态栏**如实显示**实际使用的引擎
5. **三种乐谱视图**：顶部 Tabs 切换五线谱 / 简谱 / 钢琴卷帘；钢琴卷帘中青色曲线为连续 F0 轨迹，绿色方块为量化后的音符
6. **标准文件导出**：MIDI（`.mid`，导入任意 DAW）与 MusicXML 3.1（`.musicxml`，导入 MuseScore / Sibelius）
7. **音符微调**：点击音符或用快捷键改音高、改时值、划分小节、增删音符；节拍器、BPM、拍号与量化网格的调整会**实时重算**并重新渲染
8. **全程本地**：Basic Pitch 神经网络以 tfjs 完全运行在前端，桌面应用与浏览器模式均无需后端服务、无需联网、无需 Python

操作步骤详见 [docs/使用指南.md](docs/使用指南.md)。

---

## 🏗️ 架构

```
humming/
├── src/                      # 前端源码 = frontendDist
│   ├── index.html            # 界面骨架
│   ├── main.js               # 入口脚本与主控制器交互
│   ├── css/style.css         # 浅色主题样式
│   ├── assets/
│   │   └── demo_twinkle.m4a  # 内置演示音频
│   ├── dsp/                  # 预处理 / 音高追踪 / 切分量化 / 三转谱引擎
│   ├── audio/                # 录音监控、节拍器、拟真钢琴合成器、示例音频合成
│   ├── render/               # 五线谱 / 简谱 / 钢琴卷帘渲染器
│   ├── export/               # MIDI 与 MusicXML 导出器
│   ├── theory/               # 调性推断 (Krumhansl-Schmuckler)
│   └── vendor/               # 构建产物 (esbuild 打包的 Basic Pitch + tfjs 模型)
├── scripts/                  # 构建与调试脚本
│   ├── build_vendor.mjs      # vendor 构建脚本 (由 before*Command 调用)
│   ├── clean_bundle_state.mjs # 清理残留 DMG 临时镜像
│   └── serve.mjs             # 本地静态服务 (仅浏览器调试用，无后端逻辑)
├── tests/                    # 前端回归测试 (Node)
├── src-tauri/                # Tauri 2 桌面外壳 (Rust)
│   ├── assets/icon_source.html  # 图标源文件 → cargo tauri icon
│   ├── capabilities/         # 权限能力集
│   ├── icons/
│   └── src/                  # 仅窗口与 WebView，无业务逻辑
└── docs/
    ├── 使用指南.md            # 日常操作、快捷键、故障排查
    ├── 设计/
    │   └── 架构.md            # 内部结构与关键技术决策（长期维护）
    └── 计划/
        └── 2026-10-07-工程标准化.md
```

五阶段流水线：

```
① 采集/解码 (WebAudio) → ② 声学转谱引擎 → ③ 切分与量化
  → ④ 调性推断 (Krumhansl-Schmuckler) → ⑤ 乐谱渲染与导出
```

> 📐 模块职责与关键技术决策，详见 **[docs/设计/架构.md](docs/设计/架构.md)**。

---

## 🧪 测试

```bash
npm test                   # 全部前端测试（6 个测试文件）
npm run build:vendor       # 需要时单独重建 vendor
```

各测试文件的覆盖内容见 [docs/使用指南.md](docs/使用指南.md) 的「命令速查表」。

---

## 🗂️ 数据位置

本应用**不产生任何本地持久化数据** —— 不写数据库、不落盘用户文件，关掉窗口即无残留。

唯一的本地生成物是 `src/vendor/`（Basic Pitch bundle + TFJS 模型权重），已 gitignored，
每次 `cargo tauri dev/build` 自动重建，删掉后重跑 `npm run build:vendor` 即可复原。

---

## 🛠 依赖与环境

| 组件 | 版本 | 必需性 |
| --- | --- | --- |
| Rust | 1.77.2+ | 必需 |
| tauri-cli | 2.x | 必需 |
| Node.js | 18+ | 仅 vendor 构建与前端测试需要 |
| Python | — | **不需要**（项目无 Python 依赖） |

---

## 与标准的差异

以下几项按工程需要偏离 Tauri 官方 `create-tauri-app` vanilla 模板，理由如下：

| 项 | 本工程取值 | 原因 |
| --- | --- | --- |
| `package.json` | 存在 | 有前端构建链（vendor 打包），需要 esbuild / tfjs 依赖 |
| `scripts/` 目录 | 存在 | `build_vendor.mjs`（构建链）+ `serve.mjs`（浏览器调试静态服务） |
| `tests/`（项目根级） | 存在 | 前端逻辑与 UI 契约测试用 Node 跑 |
| `beforeDevCommand` / `beforeBuildCommand` | 均指向 `node scripts/clean_bundle_state.mjs && node scripts/build_vendor.mjs` | vendor bundle 是 gitignored 构建产物，必须先于 `cargo tauri dev/build` 生成 |
| `app.withGlobalTauri` | `false` | 前端不调用任何 Tauri IPC，无需注入全局对象 |
| `src-tauri/tests/` | 不存在 | Rust 侧只有窗口与 WebView，无业务逻辑可测；前端测试全在 `tests/` |
| `src-tauri/Info.plist` | 存在 | macOS 麦克风权限声明（`NSMicrophoneUsageDescription`），录哼唱必需 |
| CSP | 放行 `'unsafe-eval'`、`blob:` | tfjs 动态求值与 Blob 资源加载需要 |

---

## 📏 开发约定

- 前端模块间一律用相对路径 `import`，因此 `src/` 可整体改名或迁移而不动 import 语句
- 不新增前端运行时依赖：新依赖须由 `scripts/build_vendor.mjs` 预打包成免打包器可用的 IIFE bundle
- 推理后端 WebGL 优先、不可用时回退 CPU，**不引入 WASM 后端**（tfjs 3.21 的 wasm 后端缺 `tf.signal.frame` 算子）
- **不使用 Web Worker**：实测 tfjs 的 WebGL 计算在 Worker 中会挂起，且 macOS WKWebView 基本不支持 Worker 内 WebGL
- 不保留前端产物副本：`frontendDist` 直接指向 `src/`，双份源码必然漂移
- 界面契约是硬门禁：`main.js` 引用的元素 id 与 CSS 类必须在 `index.html` / 样式表中真实存在，`npm test` 会逐项核对
- Rust 侧不注册任何 command、不开端口、不做业务计算
- 提交信息遵循 [conventional commits](https://www.conventionalcommits.org/)

---

## 📄 许可

MIT。完整条款见 [LICENSE](LICENSE)；`package.json` 的 `license` 与
`src-tauri/Cargo.toml` 的 `license` 字段均已声明。