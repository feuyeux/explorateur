---
title: "feuille · 架构（全景 · harness 装配 · 三层归属 · 门禁 · 路由 · RSI 定位）"
updated: { by: zcode/fuyao-work, at: 2026-10-19 }
related:
  - "../AGENTS.md —— 纪律与工程约定（权威）"
  - "workflow.md —— 工作流 ①–⑬ 运行手册（同目录）"
  - "toolchain.md —— 工具链与平台后台（同目录）"
  - "仓库级引擎文档 théâtre/ARCHITECTURE.md —— RSI 引擎与适配层（usine 树之外）"
---

# 架构

状态：v2 落地中（2026-10-18）——usine 已全量迁移为 dsh（DeepSeek Harness，开源 TS 智能体 harness，everything-is-a-plugin / Cordis）原生工程：TS 十包 + dsh 插件工具面 + skills 资产层；Python 实现（src/feuille、scripts/verify_*.py、uv 工程）已随 P7 清场退役。迁移判据（金样本 parity，已采集入库）与阶段记录在 `../migration/`（采集/比对脚本随 P7 退役，金样本与记录保留）。权威门禁 = `pnpm verify`（typecheck + 全部 vitest 测试）。分工：[workflow.md](workflow.md) 教**怎么干活**（①–⑬ 每段的输入 / 步骤 / 产物 / 检查），本文教**结构**——智能体怎么装配（§2）、数据从哪来、模块归谁、门禁怎么兜底、命令怎么路由、RSI（由 théâtre 引擎驱动的波次化自动改进）从哪里接入。图表配色与术语纪律全篇统一（§0），与仓库级引擎文档 `théâtre/ARCHITECTURE.md` §0（vendored 树，位于本树之外）同一套。

---

## 0. 图例与术语速查

### 0.1 颜色语义（全篇统一）

| 色 | classDef | 语义 |
|---|---|---|
| 蓝 | `fill:#eff6ff,stroke:#2563eb` | 编排控制面（CLI 路由、`pnpm verify` 门禁） |
| 绿 | `fill:#f0fdf4,stroke:#16a34a` | 宿主内核与可信设施（library / infrastructure 模块、门禁脚本） |
| 琥珀 | `fill:#fef3c7,stroke:#d97706` | 受限执行体（skill 专属层：对外发布的 Playwright 器、场景课生产线） |
| 红 | `fill:#fff1f2,stroke:#e11d48` | 隔离域（外部平台——域外世界，只经 manifest 门禁放行） |
| 深红 | `fill:#b71c1c,stroke:#7f0000` | 封禁路径（发布红线，永不通行） |
| 灰 | `fill:#f8fafc,stroke:#334155` | 中性容器（数据、产物、缓存账本、工具后台） |
| 虚线 | `-.->` | 逻辑边界（概念归属，不存在调用） |

描绘部署拓扑的图，subgraph 标题带**拓扑范式**标注；纯机制图不加。

### 0.2 术语（先说明，后使用）

| 术语 | 定义 |
|---|---|
| **三层归属** | 每个模块属于且仅属于一层：library（≥2 个 skill 共用）/ infrastructure（与业务无关的底座）/ skill 专属（只被一个 skill 用）。归属记在 [ownership.json](../ownership.json)，不按层切目录 |
| **反向验证** | 门禁不只「对好数据放行」，还必须「对坏数据报警」：每个套件都注入已知缺陷，断言当场被抓——判据写反时自己先红 |
| **路由表** | `cli.COMMANDS`：(组, 命令) → (模块, 函数) 的映射。路由是数据，不是 if/elif |
| **门禁套件** | 各包 vitest 测试套（44 文件，反向验证纪律原样移植：凿洞必 FAIL），由 `pnpm verify` 一键全量；归属对账在 @feuille/gate |
| **RSI** | 由 théâtre（vendored RSIAgent 引擎）驱动的波次化自动改进：Actor 在隔离 guest 里改代码，Verifier 判定，门禁绿才合并回本树。本树是**改进对象**，不承载任何 RSI 运行时代码 |
| **dsh harness** | DeepSeek Harness：开源 TS 智能体 harness（everything-is-a-plugin / Cordis）。本工程智能体的**地基**——agent loop、LLM 供给、会话持久化、审批门、子代理、技能系统全部复用它，不重造（§2） |
| **Cordis 插件** | 装进 dsh 宿主的集成单元：导出 `name` + `inject` + `apply`。`inject` 声明 apply 期要取的宿主服务，真 cordis 对未声明就访问的服务抛错——inject 列表即真实依赖清单。`@feuille/dsh-plugin` 是本工程唯一的插件 |

---

## 1. 全景：数据 → 生产 → 发布 → 回流

一句话：**数据层唯一事实源 → 生产层 ①–⑬ → 三大产物 → manifest 门禁 →
四平台 → 指标回流闭环**。

```mermaid
flowchart TB
    subgraph DATA["数据层 —— 唯一事实源（core.data 统一入口）"]
        direction LR
        PD["personas/<br/>28 人班底：声库 / 视觉 / 选角"]
        LD["languages/<br/>14 语种 manifest：字体栈 / 书写方向 / 引号对"]
        LS["lessons/<br/>课件语料"]
    end

    subgraph LINE["生产层 —— 工作流 ①–⑬（每段手册见 workflow.md）"]
        direction LR
        C14["①–④ 创作 · 交接 · 设计 · 审计<br/>人工创作 → 机器可读化 → 七项设计 → 声称 vs 实测"]
        C57["⑤ 音频 → ⑥ 视频 → ⑦ 封面<br/>三大产物，依赖顺序固定"]
        C811["⑧ 清单 → ⑨ 发布 → ⑩ 合集 → ⑪ 核对<br/>manifest 逐项核对 → 四平台 → 只读核对"]
        C14 --> C57
        C57 --> C811
    end

    subgraph ART["产物层（build/）"]
        direction LR
        AU["audio/<br/>逐行 mp3 + 词级时间戳"]
        VI["video/<br/>横竖两画幅 mp4"]
        CO["covers/<br/>四平台变体 png"]
    end

    subgraph PLAT["外部平台域（拓扑范式：服务间——Playwright 浏览器对面是平台服务器）"]
        direction LR
        DY["抖音"]
        XH["小红书"]
        BL["bilibili"]
        ZH["知乎（导入文档 + 人工挂视频）"]
    end

    C12["⑫ 指标回流<br/>两级凭据 · null ≠ 0"]
    LEDGER["ledger 缓存账本<br/>谁新鲜 · 谁过期 · 为什么"]
    BLOCK["发布红线（永不通行）：<br/>manifest 门禁不绿 → 不发布 · 封面换不上 → 不发这条<br/>H3 额度未确认 → 不生成 · 脚本自报成功 ≠ 成功"]

    PD --> LINE
    LD --> LINE
    LS --> LINE
    C57 --> AU
    C57 --> VI
    C57 --> CO
    LEDGER -.->|"按缓存键判新鲜，miss 才重算"| C57
    C811 -->|"仅 manifest 逐项核对绿"| PLAT
    PLAT -.-> C12
    C12 -.->|"经验回写 docs/（playbook 系列）"| DATA
    BLOCK -.->|"切断"| PLAT

    classDef ctrl fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef sandbox fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef isolated fill:#fff1f2,stroke:#e11d48,color:#4c0519
    classDef blocked fill:#b71c1c,stroke:#7f0000,color:#ffffff
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class C14,C57,C811 host
    class PD,LD,LS,AU,VI,CO,LEDGER neutral
    class DY,XH,BL,ZH isolated
    class C12 ctrl
    class BLOCK blocked
```

要点：

- **片名 / 首句 / 体式标签只写一处**（② `data/`），下游一切文字从 `core.data`
  来——设计只改数据，不改编码（③ 纪律）。
- **三大产物依赖固定**：音频 → 视频 → 封面；上游一动全链重走（§3）。
- **发布是单向门**：⑧ manifest 逐项核对（素材在盘 / 字数不超限 / 话题非空 /
  条数齐全）不绿，⑨ 不开始；⑪ 只读核对不过，整条当失败——脚本自报成功不算成功。
- **回流闭环**：⑫ 指标回填（没数据留 null 不填 0），经验沉淀进
  [publish-lessons.md](publish-lessons.md)、[lessons-learned.md](lessons-learned.md)、
  [metrics-playbook.md](metrics-playbook.md)，反哺 ① 的创作决策。
- **H3 铁律**（[../AGENTS.md](../AGENTS.md)）：H3 绝不自动调用；额度逐次确认，
  未确认不生成。

---

## 2. 智能体装配：dsh harness 框架（复用不重造）

一句话：**智能体 = dsh 地基（第三方，npm 钉版发布包）+ feuille 业务层（一个 Cordis 插件）**。agent loop、LLM 供给、会话持久化、审批门、子代理、技能系统全是 dsh 的；我们的代码只回答一件事——**往 dsh 里挂什么**（17 个工具、纪律 systemPrompt、审批挂点、10 个技能资产）。

```mermaid
flowchart TB
    USER["你<br/>说意图：「自检」「做 12 语种海报」"]

    subgraph ENTRYL["会话入口（packages/dsh-plugin/，编排控制面）"]
        direction LR
        ASK["ask.mjs 三挡<br/>preflight（零 LLM）/ ask（交互）/ ask 自检（单发）"]
    end

    subgraph DSH["dsh 地基 —— 第三方，npm 发布版钉版（宿主内核）"]
        direction TB
        SDK["@deepseek-ai/dsh-sdk-client 0.2.1-rc.2<br/>DeepSeekHarness：start / run / session / close"]
        subgraph PROC["dsh runtime 子进程（拓扑范式：进程间——sdk-client 与 runtime 是父子进程，经 stdio JSON-RPC 通信）"]
            direction TB
            CORE["宿主内核（Cordis · everything-is-a-plugin）<br/>agent loop · LLM 请求 · 会话/压缩 · 沙箱 · 子代理 · 内置技能"]
            SESS["~/.dsh/sessions/<br/>逐会话 zstd 存档（可回放取证）"]
        end
        OV["ask.cordis.yml 装配文件<br/>llm-pi-ai provider + 插件 insert + approval"]
        LD["entry-loader.mjs<br/>require 垫片 → dist/index.mjs（esbuild 单文件）"]
    end

    LLMG["fuyao-ai-gateway<br/>llm-pi-ai provider（apiKeyEnv，密钥不进仓库）"]

    subgraph FEUILLE["feuille 业务层 —— @feuille/dsh-plugin（本工程唯一插件）"]
        direction TB
        PLG["Cordis 插件契约：name + inject + apply<br/>inject：tools / systemPrompt / approval / skills"]
        TOOLS["ctx.tools.register ×17<br/>usine_version / scene / lesson / persona / cover /<br/>framehash / ledger / theme / copy / bgm / karaoke /<br/>poetry / poster / storyteller / verify / quota /<br/>video_generation（残余参数 = CLI argv，退出码同口径）"]
        SYSP["ctx.systemPrompt<br/>feuille:discipline 纪律 7 条"]
        APPR["ctx.approval 挂点<br/>usine_video_generation 每次强制审批；<br/>usine_publish 默认不注册——工具面上没有"]
        SKP["ctx.skills.registerProvider<br/>FileSystemSkillProvider（customSkillDirs = usine/skills）<br/>10 个技能资产宿主启动自动加载"]
    end

    CLI["@feuille/cli 路由表（§6）"]
    BIZ["@feuille/* 业务包<br/>core · karaoke · poster · bgm · poetry · copy · storyteller"]
    SKILLS["usine/skills/ 的 10 个 SKILL<br/>（说明书资产，不会被 import）"]

    USER --> ASK
    ASK --> SDK
    SDK -->|"spawn 同版本 runtime"| CORE
    OV -->|"启动装配"| CORE
    OV --> LD
    LD -->|"加载"| PLG
    CORE <-->|"LLM 请求（域外）"| LLMG
    CORE --> SESS
    PLG --> TOOLS
    PLG --> SYSP
    PLG --> APPR
    PLG --> SKP
    SKP --> SKILLS
    TOOLS -->|"工具 = CLI 的 dsh 面"| CLI
    CLI --> BIZ

    classDef ctrl fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef sandbox fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef isolated fill:#fff1f2,stroke:#e11d48,color:#4c0519
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class USER neutral
    class ASK,OV,LD ctrl
    class SDK,CORE host
    class PLG,TOOLS,SYSP,APPR,SKP host
    class SESS,CLI,BIZ neutral
    class SKILLS sandbox
    class LLMG isolated
```

要点：

- **依赖只走发布包定义**：dsh 侧的一切（sdk-client、dsh-skill-filesystem）钉版在 [packages/dsh-plugin/package.json](../packages/dsh-plugin/package.json)（0.2.1-rc.2，cordis 4.0.5 精确版），零 `link:` 机器路径——换 dsh 版本只改这处定义，与 dsh-example 的钉版纪律同口径（不依赖传递提升）。
- **地基与业务层不分家**：宿主内核的一切能力（loop / 会话 / 审批 / 子代理 / 技能系统）复用不重造；插件不实现业务，只做「feuille → dsh」的集成——17 个工具的残余参数与 CLI 完全一致，业务仍在 @feuille/* 包里，一份实现两个面（dsh 工具面 / CLI 路由面）。
- **技能资产自动加载**：插件注册 `FileSystemSkillProvider` 只扫 `usine/skills/`（路径运行期由 usineRoot() 推得，零机器路径）；宿主启动即在系统提示词的技能清单里——dsh 路不需要挂软链。软链只是无 dsh 环境的兼容路（agent 直读 `~/.agents/skills/`）。
- **审批红线承载在 harness 的 approval 服务上**：花额度的 `usine_video_generation` 每次强制审批（fail-closed、单次有效，「你直接跑」不算授权）；`usine_publish` 默认不注册——发布不可达是「工具面上没有」，不是「调了会报错」。
- **入口三挡，一条命令即会话**（详见 [guide.md](guide.md) §2）：`pnpm --filter @feuille/dsh-plugin preflight`（零 LLM 验装配）、`… ask`（交互）、`… ask 自检`（单发）。2026-10-19 实测：preflight 绿；「自检」真跑中 17 工具可调、10 技能全部在宿主技能清单、quota/verify 真执行（Windows 下固定 argv 通道经 cross-spawn 可跑 .cmd shim，模型可控 argv 通道 fail-closed 不拼 shell——注入红线）。

---

## 3. 生产主线：三大产物、改稿数据流与三层验收

```mermaid
flowchart TB
    subgraph DEP["产物依赖链（改文字最便宜，越往右重算越贵）"]
        direction LR
        D["② data/<br/>唯一文字来源"] -->|"文字 / 选角"| A["⑤ 音频"]
        A -->|"人声轨 + 时间轴"| V["⑥ 视频"]
        V -->|"首帧 / 画面基底"| K["⑦ 封面"]
        D -->|"文字标签"| K
    end

    subgraph RIP["改稿数据流：改一处，全链重走"]
        direction LR
        CH["① / ③ 改"] --> A4["④ 审计"]
        A4 --> A5["⑤ 音频"]
        A5 --> A6["⑥ 视频"]
        A6 --> A7["⑦ 封面"]
        A7 --> A8["⑧ 清单"]
        A8 -.->|"才轮到"| A9["⑨ 发布"]
    end

    LED["ledger 缓存账本：按缓存键判新鲜，miss 才重算——没动的段不白跑"]
    G13["⑬ 三层验收（贯穿 ⑤–⑪）"]

    LED -.-> DEP
    LED -.-> RIP
    G13 -.-> DEP
    G13 -.-> RIP

    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef ctrl fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class D,A,V,K,A4,A5,A6,A7,A8,A9 host
    class CH,G13 ctrl
    class LED neutral
```

三层验收（⑬，贯穿全程）：

| 层 | 时机 | 内容 |
|---|---|---|
| 渲染前检查 | 渲染 / 发布前 | 素材存在、schema 纯函数校验、文案字数 / 话题、格律审计 |
| 渲染后检查 | 渲染后 | `core.framehash` 逐帧像素（按平台分桶）、画面探针、裁切安全拼图、重渲比对 |
| 发布后核对 | 发布后 | 管理页截图 + 人眼判定（= ⑪，只读，不点任何修改） |

改稿的两个省钱位：**时长预算卡在 ⑤**（改文本便宜，超预算放宽预算、不压台词）；
**缓存账本卡在重算前**（`core.ledger` 按内容寻址键判新鲜，命中不重算）。

---

## 4. 模块三层归属：ownership.json 是唯一事实源

归属不看目录，看 [ownership.json](../ownership.json)：目录解决打包（能不能被
import），账本解决归属（算谁的）。**刻意不按归属层横切目录**——归属是易变
元数据：`devices` 与 `rig` / `scenes` / `persona` 都经历过「skill 专属 →
library」的翻转，翻转在账本里是三处编辑，在目录里是一次搬文件 + 全量改
import。分目录按**域**分（`publish/` 就是先例），不按层分。

```mermaid
flowchart TB
    OWN["ownership.json<br/>模块 → 归属层 + 归属 skill（唯一事实源）"]

    subgraph LY3["library —— 15 个（≥2 个 skill 共用，或跨产线的判定源）"]
        L3A["音画内核<br/>tts · audio · timeline · textlayer · compose · render"]
        L3B["封面 · 清单 · 指标<br/>covers · manifest · metrics"]
        L3C["数据与审计<br/>data · audit"]
        L3D["人物与场景<br/>devices · rig · scenes · persona"]
    end

    subgraph LY2["infrastructure —— 9 个（与业务无关的底座）"]
        L2A["跨平台与账本<br/>platform · ledger · framehash"]
        L2B["交付与入口<br/>packaging · cli · errors"]
        L2C["数值/成像底座<br/>num · imaging"]
        L2D["插件面<br/>dsh-plugin"]
    end

    subgraph LY1["skill 专属 —— 13 个（只被这一个 skill 用）"]
        L1A["multilingual-video-publishing：<br/>publish 族（base · login · douyin · xhs · bilibili · collections · veriflive · check_plan · clock）"]
        L1B["lesson-scene：<br/>lesson · parse_scene · scene_schema · scene_draft · scene_audio · section_patch"]
        L1C["产线包：<br/>poster · karaoke · storyteller · bgm · poetry · copy"]
    end

    CHK["@feuille/gate vitest 门禁<br/>双向机检：账本 ↔ 实际模块 ↔ 每个 SKILL.md「拥有模块」行"]

    OWN --> L3A
    OWN --> L3B
    OWN --> L3C
    OWN --> L3D
    OWN --> L2A
    OWN --> L2B
    OWN --> L1A
    OWN --> L1B
    CHK -.->|"改归属不改账本（或反之）当场 FAIL"| OWN

    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef sandbox fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class OWN neutral
    class L3A,L3B,L3C,L3D,L2A,L2B host
    class L1A,L1B sandbox
    class CHK host
```

每层的完整模块表（职责 + 谁在用）见
[../README.md 模块地图](../README.md#srcfeuille-模块地图三层归属)；
skill 层（`skills/<name>/`）只放**不会被 import** 的资产（SKILL.md 说明书、
模板、工作样例、直跑诊断脚本），会被 import 的实现一律进包、进账本。

---

## 5. 门禁体系：vitest 全量反向验证（`pnpm verify`）

纪律是「**没验不许长得像验过了**」。Python 时代的 20 套 `scripts/verify_*.py`
已随 P7 清场退役——反向验证纪律**原样移植**为各包 vitest 测试套（44 个测试文件
/ 538 项断言，`SKIP 不是 PASS` 仍然成立）；聚合器 verify_probes.py 退役为单命令
`pnpm verify`（= typecheck + 全部测试）。Edge 系测试文件单独成 project 串行
（vitest.config.ts：多实例并发抢浏览器进程是已证实的抖动根因）。

```mermaid
flowchart TB
    CLI["pnpm verify<br/>（pnpm -s typecheck && pnpm -s test）"]
    TC["tsc --noEmit<br/>类型口径全绿"]
    subgraph SU["各包 vitest 测试套（packages/*/test/，44 文件）"]
        S1["@feuille/core：底座 + 音画内核 + 数据与人物场景（27 文件）"]
        S2["产线包：karaoke · poster · poetry · storyteller · copy · bgm（e2e 含真 Edge/ffmpeg）"]
        S3["发布：publish（mock 页驱动，零平台流量）"]
        S4["入口与插件：cli · dsh-plugin"]
        S5["归属门禁：@feuille/gate（skills.test.ts）"]
    end
    RV["反向验证：每套注入已知缺陷，断言当场被抓<br/>（凿洞必 FAIL；判据写反时自己先红）"]

    CLI --> TC
    CLI --> SU
    SU -.->|"判据写反时自己先红"| RV

    classDef ctrl fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class CLI,TC ctrl
    class S1,S2,S3,S4,S5,RV host
```

按包清单（`pnpm vitest run <包路径>` 可单跑）：

| 包 | 测试文件（test/） | 验什么 |
|---|---|---|
| @feuille/core | platform · ledger · tts-×5（drm/pure/split/synth/live）· scene_audio · audio · timeline · textlayer · compose · render · rig · persona · data · devices · scenes · themes · lesson · parse_scene · scene_schema · scene_draft · covers · manifest · audit · metrics · framehash · packaging · skeleton · imaging-spike2 | 底座 / 音画内核 / 数据与人物场景全量（金样本 parity：确定性逐字节，光栅化结构与几何） |
| @feuille/karaoke | karaoke.test.ts | 单卡片成片四段产线（gen_tts / build / verify-sync / scan-blank，真 Edge e2e） |
| @feuille/poster | poster.test.ts · measure_korean.test.ts | 海报产线十条 + 韩文逐字形几何实测 |
| @feuille/poetry | poetry.test.ts | 实拍线诊断（audio_profile / color_contrast） |
| @feuille/storyteller | storyteller.test.ts | 多幕评书产线（render_act_frames / assemble，真 Edge e2e） |
| @feuille/copy | check_publish_copy.test.ts | 发布词三平台判据 + --facts 数字溯源 |
| @feuille/bgm | gen_bgm.test.ts | 床生成判据（**零真实 API 调用**：拍速反查 / 频段分布 / 床长） |
| @feuille/publish | publish.test.ts · check_plan.test.ts | 发布器 mock 页驱动（file:// 假页，零平台流量） |
| @feuille/cli | cli.test.ts · router.test.ts | 路由表可达性 + 路由器契约（首参数回还） |
| @feuille/dsh-plugin | plugin.test.ts | 17 工具面 + 红线机制（审批卡停车 / publish 默认不可达）+ 假 LLM 干跑 |
| @feuille/gate | skills.test.ts | ownership.json 三方对账 + skills 去歧义（verify_skills.py 移植 + 凿洞自证） |

> docs 清账门禁（verify_docs.py 的命令 / 脚本 / 符号 / 链接真实性五判据）随
> Python 侧退役，判据未单独移植——命令真实性由 @feuille/cli 路由测试与评审
> 承担；「死入口零容忍、考古看 git 历史」仍是评审纪律。

---

## 6. CLI 路由：表驱动，不是 if/elif

统一入口 `feuille <组> <命令>`。路由器只做三件事：查表、lazy import、
把残余参数原样交给叶子——叶子拿不到组与命令，只拿真实参数（路由层消化掉的
首参数必须还给 argv，这是路由器与叶子之间的契约）。

```mermaid
flowchart LR
    IN["argv：组 · 命令 · 参数……"]
    MAIN["cli.main<br/>弹出组与命令，其余留给 argv"]
    TBL["COMMANDS 路由表<br/>（组, 命令）→（模块, 函数）"]
    LAZY["lazy import 目标模块<br/>CLI 启动零依赖"]
    LEAF["叶子 fn(argv)<br/>库函数挂 main_* 薄适配层"]
    OK["返回叶子退出码"]
    BAD["未知命令 → usage + 退出码 2<br/>FeuilleError → stderr + 退出码 1"]

    IN --> MAIN
    MAIN --> TBL
    TBL -->|"查到"| LAZY
    TBL -->|"查无（且组无省略形态）"| BAD
    LAZY --> LEAF
    LEAF --> OK
    LEAF -->|"库层显式失败"| BAD

    classDef ctrl fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef blocked fill:#b71c1c,stroke:#7f0000,color:#ffffff
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class IN,MAIN,TBL,LAZY ctrl
    class LEAF,OK host
    class BAD blocked
```

路由表全量（登记于 `cli.COMMANDS`，`packages/cli` 的 router/cli 测试保证每个叶子
真实可达——登记了不存在的函数 = 路由表说谎，当场抓）：

| 组 | 命令 | 归属包 | 覆盖段 |
|---|---|---|---|
| version | — | cli | 版本口径 |
| ledger | status | core | 产物新鲜度问答 |
| framehash | save / check | core | ⑬ 采逐帧像素基线 / 零漂移门禁 |
| cover | make / check | core | ⑦ 封面生成 / 自检 |
| persona | validate | core | ②③ 人设契约校验 |
| scene | parse / validate / draft / tts | core | ②③④ scene.md → scene.json → 语音线 |
| lesson | new / doctor | core | ③④ 开新课件坑 / 班底体检 |
| theme | match | core | 主题自动匹配（match_theme.py 升包） |
| karaoke | tts / build / verify-sync / scan-blank | karaoke | ⑤⑥⑬ 单卡片成片四段产线 |
| poetry | audio-profile / color-contrast | poetry | ⑬ 实拍线诊断 |
| storyteller | render-frames / assemble | storyteller | ⑥ 多幕评书产线 |
| poster | fetch-fonts / assemble / render / render-page / audit-charset / fit-diag / verify-colors / check-overlay / make-covers / measure-korean | poster | ⑦ 海报产线十件 |
| copy | check | copy | ⑧ 发布词自检（零平台流量） |
| bgm | gen | bgm | ⑤ 纯器乐 BGM 床生成 |
| publish | login / check-plan / douyin / xhs / bilibili | publish | ⑨⑩ 扫码登录 / 清单自检 / 三平台发布 |

三个设计取舍：

- **发布类叶子要求可选依赖**（`playwright` 1.64.1 装在 @feuille/publish 的
  optionalDependencies；代码是 `import('playwright')`，装 `@playwright/test` 不会
  在这里解析得到）：没装时 import 在函数内 lazy 失败，报的是「缺 playwright」
  而不是「未知命令」——前者告诉用户怎么修。系统 Chrome 经 `FEUILLE_BROWSER`
  解析，不下载 Playwright 自带浏览器（`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`）。
- **清单组装没有 CLI 叶子**：`core.manifest` 的构建吃带闭包的 plans 契约，
  只能从项目脚本调用（⑧ 的调用形态见 [toolchain.md](toolchain.md)）。
- **聚合命令退役为 pnpm 脚本**：全量门禁 = `pnpm verify`
  （typecheck + 全部测试），单包单跑 = `pnpm vitest run <包路径>`。

---

## 7. RSI 定位：本树如何被安全地自动改进

本树（`usine/`）在 explorateur 仓库里是 RSI 的**改进对象**；引擎
（`../théâtre/`，vendored RSIAgent）与适配层（`../../benchmarks/usine/`）
都在本树之外。**本树不承载任何 RSI 运行时代码**——波次合进来的只是对既有
模块 / 文档的修改，且必须先过 §5 的门禁（`pnpm verify` 全量）。

```mermaid
flowchart LR
    subgraph EX["explorateur 仓库（拓扑范式：进程间——编排进程与 guest 进程互不共享内存）"]
        TH["théâtre<br/>vendored RSIAgent 引擎"]
        BM["benchmarks/usine<br/>适配层：装配 · 围栏 · 合并"]
        US["usine 生产树（本树）"]
    end

    SEED["seed：本树波首 git archive 快照"]
    GUEST["worktree guest<br/>Actor 在 seed 里改代码，副作用不落本树"]
    WM["wave_merge：delta 分类 + 门禁<br/>一候选一 commit + tag"]

    BM -->|"装配 hooks + vm_factory"| TH
    US -->|"波首快照"| SEED
    SEED --> GUEST
    TH -->|"驱动练习循环"| GUEST
    GUEST -->|"候选 delta"| WM
    WM -->|"门禁绿才落（含本树 20 套全量）"| US

    classDef host fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef ctrl fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    classDef sandbox fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef neutral fill:#f8fafc,stroke:#334155,color:#0f172a
    class TH host
    class BM,WM ctrl
    class US,SEED neutral
    class GUEST sandbox
```

安全性质（全部由适配层保证，细节见仓库级引擎文档
`théâtre/ARCHITECTURE.md`（vendored 树，位于本树之外））：

- **本树在波次期间分毫不动**：Actor 改的是 seed 快照（worktree guest），
  候选以 delta 形式出来，合并是显式动作（一候选一 commit，带 tag）。
- **门禁是合并判据的一部分**：候选 delta 过不了 `feuille verify`
  全量，就不落本树。
- **发布红线对 RSI 同样成立**：适配层在 VM 门面处拒绝发布类命令（三层防线），
  改进波次永不触碰真实平台流量。
- 引擎内部机制（三角色、练习循环、围栏与审计、Verifier 隔离、合并管线）的
  完整架构见仓库级引擎文档 `théâtre/ARCHITECTURE.md`（vendored 树，位于
  本树之外）；适配层相对设计稿的偏离记录见同目录的
  `ADAPTATION.md`（同一 vendored 树内）。
