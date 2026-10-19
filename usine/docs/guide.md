---
title: "feuille · 智能体使用指南（交互手册）"
updated: { by: zcode/fuyao-work, at: 2026-10-19 }
related:
  - "reference.md —— 结构 / 工作流 / 工具 / 不变量"
  - "record.md —— 实测数字与已修缺陷"
  - "../AGENTS.md —— 纪律与工程约定（权威）"
---

# feuille 智能体使用指南

> 像 Codex CLI 之于编码——**feuille 是装在你终端/对话里的内容生产智能体**。
> 你说意图，它自己调产线、跑门禁、交成品；花额度的生成和平台发布由**强制审批门**把守。
> 本文只讲交互：装好后怎么说、它会怎么答、哪些关口必须你点头。
> 机制与判据见 [reference.md](reference.md)；逐条命令与实测证据见 [record.md](record.md)。

## 1. 这是什么

feuille 是多语种内容生产智能体，能力覆盖工作流 ①–⑬ 全程：

| 能力 | 一句话 |
|---|---|
| 多语种文案与排版 | 14 语种注册表；字体子集、字符门、逐字着色 |
| 海报 / 封面 | A4 海报、四平台封面规格、契约校验 |
| 配音 / 成片 | 词级时间戳 TTS、卡拉 OK 成片（横竖两版）、逐场景音画同步验收 |
| 配乐 | Lyria 纯器乐 BGM 床（免费层）、按旁白实测电平定床位 |
| 发布词 / 发布 | 三平台判据文案、批量发布、回列表逐条核验 |
| 自检 | 全程门禁（好数据必须 PASS、坏数据必须 FAIL）；SKIP ≠ PASS |

智能体 = **dsh harness + feuille 业务层**，不分家：

- **地基：dsh（DeepSeek Harness）**——工具注册、审批门、systemPrompt 注入、进程生命周期，
  全部复用 dsh 框架，不重造 harness。
- **业务层：`packages/dsh-plugin`**——把 17 个 `usine_*` 工具 + 纪律 systemPrompt 挂进 dsh，并把 `usine/skills/` 的 10 个技能注册为**默认资产**（宿主启动自动加载，无需指定、无需挂软链），实现我们自己的内容产线智能（①–⑬ 的分水岭、判据、安全边界全在这层定义）。
- **兼容路：任意智能体 + skills 软链**——在没有 dsh 的环境里复用同一业务层（agent 读 `skills/*/SKILL.md`，自己调 `feuille` CLI）；能力面相同，审批门由宿主自带机制承载。

CLI（`feuille <组> <命令>`）一直都在，但**那是智能体的手，不是你的**——
交互指南教你说话，不教你记命令。

## 2. 安装

```bash
cd usine
pnpm install        # Node ≥24 + pnpm@11；实测 15.8s（109 包）
```

外部工具（缺了它会**显式报缺**，绝不静默退化）：Chromium 系浏览器（headless 渲字）、
ffmpeg / ffprobe。

装配智能体（a 为主路；b 为无 dsh 环境的兼容路）：

```bash
# a. dsh 宿主（主路）：
pnpm install                                    # dsh 依赖 = packages/dsh-plugin/package.json
pnpm --filter @feuille/dsh-plugin build         # 里的 npm 发布版钉版定义，零机器路径；
                                                # 换 dsh 版本只改这处定义
# 会话入口（packages/dsh-plugin/package.json 的 scripts）：
pnpm --filter @feuille/dsh-plugin preflight     # 零 LLM：只验「runtime 起得来 + 插件挂得上」，不花额度
pnpm --filter @feuille/dsh-plugin ask           # 交互会话：逐行输入，Ctrl-D / Ctrl-C 退出
pnpm --filter @feuille/dsh-plugin ask 自检      # 单发一句话，答完即退
# 宿主装配文件 = packages/dsh-plugin/ask.cordis.yml（provider + 插件 + approval 全在里头）；
# 插件本体经 entry-loader.mjs 垫 require 后加载 dist/。
# skills 不用挂软链：插件自己把 usine/skills/ 注册为技能资产（随宿主启动自动加载）。

# b. 任意智能体（无 dsh 环境的兼容路）：把 skills 软链过去
#    （某条缺失不影响使用，SKILL.md 直接读本仓库也行）
mkdir -p ~/.agents/skills
for s in usine/skills/*/; do ln -sfn "$PWD/$s" ~/.agents/skills/"$(basename "$s")"; done
#    Windows 无管理员权限时用目录联接（junction）：mklink /J 或
#    PowerShell New-Item -ItemType Junction，效果等同软链
```

装好先说一句「**自检**」：

```bash
pnpm --filter @feuille/dsh-plugin ask 自检
```

预期报回版本 + 额度/门禁数字 + 外部工具状态（实测：版本与额度只读查询返回 0；`usine_verify` 会真跑 typecheck + 全量 vitest，约 1 分钟）。

**「说」的地方就是终端**——feuille 不自带聊天框，上面三条命令哪条都是入口：

- **单发**：`pnpm --filter @feuille/dsh-plugin ask 自检`（一句答完即退，适合例行体检）。
- **交互**：`pnpm --filter @feuille/dsh-plugin ask` 进会话逐行说。
- **零 LLM 预检**：`pnpm --filter @feuille/dsh-plugin preflight`（不花额度，只验装配）。
- **dsh 自家宿主**：dsh 的会话框（如 `npx @deepseek-ai/dsh web`）+ 本插件 patch，工具面相同。
- **走 b（任意智能体）**：在任何一个会读 `~/.agents/skills/` 的 agent CLI 里说；软链挂好后**要新开一个会话**，宿主启动时才发现新技能。

## 3. 登录与凭据（按需，一次性）

| 想用的能力 | 需要什么 | 你怎么给 | 它怎么验 |
|---|---|---|---|
| TTS / 海报 / 成片 | 无凭据 | — | — |
| BGM 配乐 | `GEMINI_API_KEY`（Lyria 免费层，$0） | 填进 `explorateur/config/.env` 的 `GEMINI_API_KEY=`（等号后直接贴，别加引号；样例见同目录 `env.sample`；**勿进仓库**） | 说「查一下 BGM 凭据」→ 只探凭据不碰网络 |
| 实拍母版 | MiniMax 套餐额度 / 积分 | 宿主侧账号 | 说「查一下额度」→ 只读查询 |
| 平台发布 | 各平台登录态 | 说「登录小红书」→ 扫码**你自己扫** | 回读登录态；profile 目录存盘勿删 |

## 4. 快速开始：第一段对话

```text
你：用「长安是千年古都」做 12 语种单卡片成片：A4 海报一张、横竖两条 mp4、
   小红书/抖音/B站三平台发布词。做到发布清单自检为止，先不发。

feuille：开工。范围：12 语种 × {海报， 成片×2， 发布词×3}；发布执行不碰。
  …逐环节汇报（结论 + 退出码 + 判据 + 产物路径）…
  完成：poster.png 2480×3508 · 两条 mp4（66.20s / 1986 帧，同步门最大 diff 608/40000）
        · 发布词判据全绿 · manifest 24 条离线自检通过。
  下一步：A. 海报定稿后我配乐；B. 现在就发布——需要你明确说「发」。
```

全程以分钟计（实测：依赖 15.8s，单格式合成 214s，出床 wall≈137s）；
配套实物在 [`examples/one-city-12lang/`](../examples/one-city-12lang/)。
「**做到发布清单自检为止**」是刻意的：第一轮零平台流量、纯本地。
第一次建议更小步——先说「**只出一张海报，看看排版**」，秒级出图，风格满意再全量。

## 5. 你怎么说（任务速查）

说你**要什么**，不用说**怎么做**；不确定走哪条产线就描述内容
（有没有实拍画面？单卡片还是多幕评书？），分水岭它比你熟：

| 你说 | 它自动跑完 | 你拿到 |
|---|---|---|
| 「做 12 语种海报」 | 字体子集 → 字符门 → 注入 → 渲染 →（要封面时）双版式封面 + 契约校验 | 海报 PNG（+ 封面 PNG） |
| 「把海报做成逐词高亮成片」 | 12 语种配音（词级时间戳）→ 分段合成 → 空帧门 → 逐场景同步门 | 横竖两条 mp4 + 验收报告 |
| 「配乐」 | 出床 → 按旁白实测电平定床位 → 挂床重建（需要 key，§3） | 带床成片（覆盖无床版） |
| 「写三平台发布词」 | 起稿 → 机检（标题字数 / 话题 / 钩子 / AI 指纹 / 数字溯源） | 判据全绿的 `publish/*.md` |
| 「出实拍母版」 | 查额度 → 选线（默认套餐额度线）→ **弹审批卡**（提示词/画幅/时长/预估消耗）→ 你点头才提交 | 冻结的母版对 |
| 「发小红书和抖音」 | 清单 → 离线自检 → **你明确指令后才开浏览器** → 发布 → 回列表逐条核验 | 已发布 + 核验报告 |

## 6. 它的工作方式（你会看到什么）

- **探 → 跑 → 判 → 报**：每个环节汇报「结论 + 退出码 + 一条判据 + 产物路径 + 下一步两个选项」，
  不贴整屏日志（原始 stdout 落 `examples/<项目>/logs/`，只追加不改写）。
- **四态不混**：PASS / FAIL / SKIP / NOT RUN。**SKIP 不是 PASS**——看到 SKIP 是它在说实话，
  补齐前置（§3）再喊它跑即可。
- **卡住才问，一次只问一个决策**：给 2–3 个带代价的选项 + 建议。
- **坑自己修**：CRLF 换行、字族嵌套、浏览器视口、参数引号——全部真踩过、已修、有证据
  （[record.md §2](record.md#2-坑位表一次真跑暴露)）；同一修复连试 2 次不收敛它会停下来问你。
- **完成有定义**：画面 / 音频 / 混后 / 收尾四层全齐才算完（定义见
  [skills/README.md](../skills/README.md) 的完成定义表），缺层它会明说缺哪层、为什么。
- **验收可自查**：收成品扫三个数字——全部环节 exit 0；成片 `nb_frames = 时长 × 30`；
  同步门最大 diff 远小于 40000。

## 7. 审批与安全（机制承载，不是客套话）

| 关口 | 机制 | 你会看到 |
|---|---|---|
| 视频生成（花额度） | `usine_video_generation` **每次执行强制审批**，fail-closed、单次有效 | 审批卡：提示词 / 画幅 / 时长 / 分辨率 / 预估消耗。**「你直接跑」不算授权**，每次消耗额度的调用都单独点头 |
| 发布 | `usine_publish` **默认不注册**，dsh 宿主 config 显式 `publish: true` 才挂 | 它不会建议你开启，也不会用 shell 绕过；开启后每条发布前仍要你明确指令 |
| 扫码 / 风控 | 永远人工 | 只等待，绝不代填凭据，绝不自动重试；风控停下等人 ≤10 分钟 |
| 汇报诚实 | 纪律 systemPrompt（`feuille:discipline`，7 条） | exit ≠ 0 就是不过；把 SKIP 当 PASS 汇报 = 造假；门禁结果原样上报 |

选线纪律它自己执行：提交母版前先查额度（`usine_quota`），额度够走 Hailuo-2.3
（套餐额度、不烧积分）；**母版一次生成、按画幅成对、生成后冻结，永不重复消耗**，
后续只做叠加（字幕 / 配音 / 封面）。

## 8. 工具面参考（dsh 宿主）

默认注册 17 个工具，与 CLI 路由同覆盖面（发布除外）；每个工具的残余参数与
`feuille <组> <命令>` 完全一致，退出码 0/1/2 同口径：

| 工具 | 干什么 |
|---|---|
| `usine_version` | 版本号（只读自检，无副作用） |
| `usine_scene` | 场景课产线：parse / validate / draft / tts |
| `usine_lesson` | 课件就绪度：新课开坑 + 七层体检（每条未完成带下一条命令） |
| `usine_persona` | 人设契约体检：28 人班底逐人校验 |
| `usine_cover` | 封面产线：make（HTML → 平台规格截图）/ check（尺寸 + 外圈底色契约） |
| `usine_framehash` | 逐帧像素基线：save 采集 / check 零漂移门禁 |
| `usine_ledger` | 产物缓存账本：谁过期了、因为什么 |
| `usine_theme` | 话题 / 语种 → 垂域主题推荐 |
| `usine_copy` | 发布词自检（零平台流量；未给 facts 时数字溯源是 SKIP 不是 PASS） |
| `usine_bgm` | BGM 床生成 + 实测判据（床长 / 拍速反查 / 频段分布） |
| `usine_karaoke` | 卡拉 OK 成片线：tts / build / verify-sync / scan-blank |
| `usine_poetry` | 实拍母版诊断：人声 LUFS 对比 / 文字压实拍量化 |
| `usine_poster` | 海报产线：字体子集 / 字符门 / 渲染 / 四色验收 / 封面变体 / 韩文字素测量 |
| `usine_storyteller` | 评书成片：幕帧渲染 + 叠化转场 + 醒木混音 |
| `usine_verify` | 全量门禁：typecheck + 全量 vitest（≈1 分钟，别并发跑多个） |
| `usine_quota` | MiniMax 套餐额度查询（只读） |
| `usine_video_generation` | 实拍母版三条线（Hailuo-2.3 / H3 / H3-Max），**每次强制审批** |
| （`usine_publish`） | 平台发布；默认不注册，config 显式开启才挂 |

## 9. 配置

| 项 | 说明 |
|---|---|
| 发布开关 | dsh 宿主 config `publish: true` 才注册发布工具（有意设计，见 §7） |
| `FEUILLE_BROWSER` | 临时钉 headless 浏览器路径（如 Edge 视口异常时指到 Chrome） |
| `explorateur/config/.env` | **工作区唯一**配置/凭据文件（`KEY=VALUE`，`#` 注释，环境变量优先；LLM 波次凭据与 `GEMINI_API_KEY` 都在这里，样例同目录 `env.sample`）；`BGM_BED_ENV` 仅测试显式改指 |
| 平台 profile | `~/.{douyin,xhs,bili,zhihu}_creator_profile`，登录态存盘**勿删** |
| 交付位置 | 一律在当前工作区项目目录内；不写 Desktop / Downloads / 临时目录 |

## 10. 故障排查

| 你看到的 | 原因 | 你做什么 |
|---|---|---|
| 它报「缺 X（ENOENT）」 | 外部工具不在 PATH | 装上 / 给路径，或批准它安装；它会重跑探测 |
| `pnpm install` 报 `@deepseek-ai/*` 解析失败 | npm registry 不可达，或钉版号下线 | 照报错改 `packages/dsh-plugin/package.json` 里的版本定义，重跑 `pnpm install`；别手改 `node_modules` |
| 它报「pnpm/mmx 解析到 .cmd/.bat shim，本通道不开 shell」 | Windows 上这两个是 shim；argv 含模型可控内容的通道 fail-closed（注入红线，故意不拼 shell） | 装 standalone 版（.exe）并确保排在 shim 前；固定 argv 的通道（verify/quota）不受影响，已可正常跑 |
| 它停成一张审批卡 | 额度红线（§7） | 看卡上的消耗，点头或拒绝；**别期待「同意过一次以后免审」** |
| 汇报里出现 SKIP | 前置缺失（如没填 key） | 按 §3 补前置，再喊它跑 |
| 门禁红（FAIL） | 判据不过 | 让它贴判据原文——它自己定位、修、重跑；连试 2 次不收敛它会停下来问你 |
| dsh 宿主加载报 `Dynamic require not supported` | esbuild 产物在 Node 原生 ESM 下缺 require 垫片 | 用 `packages/dsh-plugin/entry-loader.mjs` 作为插件入口（垫片已内置），别直挂 `dist/index.mjs` |
| 它 boot 成功但工具全没了 | 宿主静默吞了 apply 抛错（如 inject 缺 `approval`） | 跑 `pnpm --filter @feuille/dsh-plugin preflight`——零 LLM 验装配，工具没挂上当场红 |
| DSH 沙箱报 `SetNamedSecurityInfoW` 之类的 Windows 权限错 | 宿主环境的文件权限问题，与插件工具面无关 | 让宿主跑它自带的 `diagnose-windows-sandbox-acl` 诊断技能；必要时把宿主会话切到完全权限 |
| 换台机器还能用吗 | skills 与插件均无绝对路径绑定 | 能：§2（pnpm install + build + ask）即可；dsh 主路连软链都不用 |

## 11. 深入阅读

| 想了解 | 读 |
|---|---|
| 结构 / ①–⑬ 流程 / 工具链 / 渲染不变量 / 发布规则 | [reference.md](reference.md) |
| 一次真跑的 12 语种数字、坑位表、三个后置缺陷 | [record.md](record.md) |
| 10 个 skill 的路由与完成定义 | [../skills/README.md](../skills/README.md) |
| 22 条纪律与工程约定（权威） | [../AGENTS.md](../AGENTS.md) |
