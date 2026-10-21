# feuille

> feuille（法语：叶 / 一页）——多语种视频生产与发布的**可复用层**。
> TTS / 渲字 / 合成 / 封面 / 四平台发布 / 发布后核对，工作流 ①–⑬ 全覆盖。
>
> ### une usine avec des machines rugissantes
>
> 一座轰鸣着机器的工厂

## 目录

| 文件/目录 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | ★ 活规则：22 条纪律 + 工程约定（跨平台 + pnpm 统一）+ H3 铁律 |
| `package.json` + `pnpm-workspace.yaml` | pnpm TS monorepo（Node ≥24；devDependencies 锁在 lockfile） |
| `packages/` | 代码：pnpm 工作区 12 包（core / cli / publish / poster / karaoke / poetry / storyteller / copy / bgm / dsh-plugin + gate 门禁 + eval 健康分），按工作流①–⑬全覆盖——三层归属见[下方模块地图](#packages-模块地图三层归属) |
| 各包 `test/` | vitest 门禁：反向验证纪律原样移植（**凿洞必被抓**；`pnpm verify` 一条命令全量跑：typecheck + 全部测试） |
| `languages/` | 语种注册表：14 语种 manifest（字体栈 / 国旗 / 书写方向 / 引号对） |
| `personas/` | 人设目录：28 人班底 + schema / 声库 / 视觉 / 选角文档 |
| [docs/](docs/) | 全部文档（工作流/工具链 + playbook 系列） |
| `skills/` | 自建 SKILL 资产（11 个，总路由见 [skills/README.md](skills/README.md)），机器侧以软链挂到 `~/.agents/skills/`（只放软链，不存实体） |
| `examples/` | 内容项目产物示例（yiyezhiqiu 等：诗稿 / 文案 / 数据 / 设计稿 / H3 母版——母版不可再生） |

## packages/ 模块地图（三层归属）

**归属不看目录，看 [ownership.json](ownership.json)**：目录解决打包（能不能被 import），
账本解决归属（算谁的），由 @feuille/gate 的 vitest 门禁与每个 SKILL.md「拥有模块：」行
**双向机检**。刻意不按归属层横切包（`lib/`、`infra/`）——归属是**易变元数据**：
`core.devices` 与 `core.rig`/`core.scenes`/`core.persona` 都经历过「skill 专属 → library」
的翻转，翻转在账本里是三处编辑，在目录里是一次搬文件 + 全量改 import + 文档回填。
分**包**按域分（模块多了、同一域在长），不按层分——`publish/` 就是先例。
模块 ID =「包.源文件」（如 core.tts）；声明父 ID 即覆盖子模块（publish 覆盖 publish 包全部源文件）。

下面三个小节的**模块清单**由 packages/gate 的 vitest 门禁与 ownership.json 双向对账：
改归属不改地图（或新入层忘了画），`pnpm verify` 当场 FAIL。

### library —— 16 个（被 ≥2 个 skill 共用，或跨产线的判定源）

| 模块 | 职责 | 谁在用 |
|---|---|---|
| `core.tts` | edge-tts 合成内核（协议自复刻）：词级时间戳、重试、内容寻址缓存 | karaoke + poetry |
| `core.audio` | ffmpeg 音轨合成与时长探测 | karaoke + poetry |
| `core.timeline` | 行时间轴与词级进度轴 | 成片线 + 课件渲染线 |
| `core.textlayer` | Edge headless 渲字（视口探测 / 截图 / 双 matte 抠像） | poster + poetry |
| `core.compose` | 母版叠加合成（`-shortest` → 显式 `-t` 的教训） | 成片线 + 课件渲染线 |
| `core.render` | 帧编码基座：rawvideo → ffmpeg 管道 | 同上 |
| `core.covers` | 封面机制：平台规格 / 预裁底图 / 裁切模拟 | poster + poetry |
| `core.manifest` | 发布清单：文案稿解析 / 平台限制检查 / 清单构建 | publishing + lesson-scene |
| `core.metrics` | 指标回流：两级凭据、null≠0 | publishing + lesson-scene |
| `core.data` | 数据入口唯一事实源：personas / languages / lessons | 各 skill 共读 |
| `core.audit` | 格律计数审计：声称 vs 实测 | poetry + 课件诗稿 |
| `core.devices` | 装置外框样式注册表（16 样式） | character-rig（画）+ lesson-scene（校验） |
| `core.rig` | 人物 rig 本体：色表 / 物理 / 缓动 / FACE_SPECS / MOOD_FACE / POSE_CODES / draw_character | character-rig（说明书）+ lesson-scene（校验判据） |
| `core.scenes` | 背景场景原语：65 注册场景 + prerender_bg + DrawScaled | character-rig + lesson-scene（doctor 合法值） |
| `core.persona` | 人设契约校验器（`feuille persona validate` 直调） | character-rig + lesson-scene（doctor 班底体检） |
| `core.themes` | 教学视频垂域主题匹配器（`feuille theme match` 直调） | karaoke + poster |

### infrastructure —— 10 个（与业务无关的底座）

| 模块 | 职责 |
|---|---|
| `core.platform` | 浏览器 / ffmpeg / ffprobe / magick 跨平台解析，全仓唯一事实源（三系统可跑的保证） |
| `core.ledger` | 产物缓存账本：谁新鲜、谁过期、为什么 |
| `core.framehash` | 逐帧像素基线（按平台分桶），验收的像素判据 |
| `core.packaging` | 交付打包（zip，非 ASCII 文件名必须置 UTF-8 flag） |
| `cli` | 统一入口路由表 `feuille <组> <命令>`——路由表是数据不是 if/elif |
| `core.errors` | 库层显式错误通道 `FeuilleError`：库函数报错的唯一异常类型，CLI 统一接住（stderr + 退出码 1） |
| `core.num` | 数值口径底座：pyFloat / roundHalfEven / clamp——Python 口径镜像 |
| `core.argv` | CLI 旗标取值：`--k v` 与 `--k=v` 同收 |
| `core.imaging` | 成像底座：sharp 解码/编码 + @napi-rs/canvas 绘制（Pillow 语义镜像），唯一成像实现 |
| `dsh-plugin` | dsh 原生智能体插件：17 工具面 + 统一结果契约 + dispatch 层额度审批门 + systemPrompt 纪律节 |

### skill 专属 —— 13 个（只被这一个 skill 用的业务实现）

| 模块 | 归属 | 职责 |
|---|---|---|
| `poster` | one-page-poster | 海报产线十条编排（fetch_fonts / assemble / render_poster / render_page / audit_charset / fit_diag / verify_colors / check_overlay / make_covers / measure_korean） |
| `karaoke` | karaoke-video | 单卡片成片产线编排（gen_tts / build_video / verify_sync / scan_blank） |
| `storyteller` | storyteller-video | 多幕评书成片产线编排（render_act_frames / assemble_storyteller） |
| `bgm` | bgm-bed | BGM 床生成（gen_bgm：Lyria realtime + 实测判据） |
| `poetry` | multilingual-video-poetry | 实拍母版线诊断（audio_profile / color_contrast） |
| `copy` | publish-copy | 发布词自检（check_publish_copy：三平台判据 + --facts 数字溯源） |
| `publish`（base / login / douyin / xhs / bilibili / collections / veriflive / check_plan / clock） | multilingual-video-publishing | Playwright 发布器本体；对包内其他模块零依赖，自成一体 |
| `core.lesson` / `core.parse_scene` / `core.scene_schema` / `core.scene_draft` / `core.scene_audio` / `core.section_patch` | lesson-scene | 开坑体检 / scene.md→scene.json / parse-render 之间校验闸门 / 创意→草稿 / 场景课 TTS 语音线（timeline.json + 逐行 mp3）/ 按节头整节替换 |

> skill 层（`skills/<name>/`）只放**不会被 import** 的资产：SKILL.md 说明书、模板、
> 工作样例。会被 import 的实现一律进包、进账本；skill 的产线编排消费包里的唯一实现，
> 不自带第二份。

## 使用

```bash
cd usine                       # pnpm 工程根（package.json / pnpm-workspace.yaml 所在层）
pnpm install                   # 安装依赖（pnpm@11；Node ≥24）
pnpm verify                    # 全量门禁：typecheck + 全部 vitest 测试（含反向验证）
pnpm vitest run                # 只跑测试（不 typecheck）
pnpm vitest run packages/core  # 单跑一个包的测试
npx tsx packages/cli/src/main.ts <组> <命令>   # 直跑 CLI（或 `pnpm --filter @feuille/cli exec feuille …`）
```

## skills/ 跨机器复用

自建 skill 自足在仓库内，不含任何绝对路径或本机解释器绑定；换机器 clone 后只需三步：

```bash
cd usine && pnpm install      # ① Node 依赖（pnpm-workspace.yaml 锁定，Node ≥24 + pnpm@11）
mkdir -p ~/.agents/skills                    # ② 挂软链，让本机 agent 能发现 skill
for s in usine/skills/*/; do ln -sfn "$PWD/$s" ~/.agents/skills/"$(basename "$s")"; done
# ③ 系统外部工具：Chromium 系浏览器（headless 渲字）、ffmpeg（合成/测量）
#    软链只是发现入口——某条软链缺失不影响使用：直接读本仓库 usine/skills/<name>/SKILL.md 照常工作
```

自足约定（skill 收录时必须满足，违反即无法跨机器复用）：

- 脚本与 SKILL.md 内**禁止出现**任何 `/home/…`、`~/.agents`、特定解释器 / 全局 node_modules 路径——一律写 `pnpm --filter <pkg> exec …`、`feuille <组> <命令>` 或仓库相对路径；
- 每种文字系/场景的**完整工作样例**必须进 skill 资产（`assets/example/`），不得只留骨架模板、让使用者去翻历史项目或 reflog；
- 逐字形实测的几何值（如韩语色块）不可硬编码迁移，必须配套可重跑的测量命令（`feuille poster measure-korean`，实现在 @feuille/poster）；
- 依赖外部能力（如 BGM 的 Google Lyria）必须在 SKILL.md 显式声明为可选，并给出无该能力时的退化路径（`bgm.file` 接任意纯音乐 wav 或删掉 bgm 段）。

## docs/ 一览

| 文件 | 内容 |
|---|---|
| [dsh.md](docs/dsh.md) | 智能体分层架构：dsh 地基 / 入口装配 / 插件 / 业务包 / 技能资产 + 红线双承载 + 验收面 |
| [guide.md](docs/guide.md) | 人机交互：安装 / 凭据 / 怎么说 / 审批门 / 工具面 |
| [reference.md](docs/reference.md) | 结构 · ①–⑬ 流程 · 工具链 · 渲染不变量 · 发布规则 |
| [record.md](docs/record.md) | 实测数字（12 语种）· 坑位表 · 已修缺陷 · 发布判据 |
