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
| [AGENTS.md](AGENTS.md) | ★ 活规则：22 条纪律 + 工程约定（跨平台 + uv 统一）+ H3 铁律 |
| [pyproject.toml](pyproject.toml) + `uv.lock` | uv 工程（Python 3.12；publish 组 = Playwright） |
| `src/feuille/` | 终态代码：34 个归属模块 / 1.07 万行，按工作流①–⑬全覆盖——三层归属见[下方模块地图](#srcfeuille-模块地图三层归属) |
| `scripts/` | 20 个反向验证脚本（19 套 + `verify_probes` 聚合器；`uv run feuille verify` 一条命令全量跑，330+ 项断言） |
| `languages/` | 语种注册表：14 语种 manifest（字体栈 / 国旗 / 书写方向 / 引号对） |
| `personas/` | 人设目录：28 人班底 + schema / 声库 / 视觉 / 选角文档 |
| [docs/](docs/) | 全部文档（工作流/工具链 + playbook 系列） |
| `skills/` | 自建 SKILL 资产（8 个，总路由见 [skills/README.md](skills/README.md)），机器侧以软链挂到 `~/.agents/skills/`（只放软链，不存实体） |
| `examples/yiyezhiqiu/` | 示例项目内容包（诗稿 / 文案 / 数据 / 设计稿 / H3 母版——母版不可再生） |

## src/feuille 模块地图（三层归属）

**归属不看目录，看 [ownership.json](ownership.json)**：目录解决打包（能不能被 import），
账本解决归属（算谁的），由 `verify_skills.py` 与每个 SKILL.md「拥有模块：」行**双向机检**。
刻意不按归属层横切目录（`lib/`、`infra/`）——归属是**易变元数据**：`devices` 与
`rig`/`scenes`/`persona` 都经历过「skill 专属 → library」的翻转，翻转在账本里是三处编辑，
在目录里是一次搬文件 + 全量改 import + 文档回填。分目录按**域**分（模块多了、同一域在长），
不按层分——`publish/` 就是先例。

下面三个小节的**模块清单**由 `scripts/verify_skills.py` 与 ownership.json 双向对账：
改归属不改地图（或新入层忘了画），`uv run feuille verify` 当场 FAIL。

### library —— 15 个（被 ≥2 个 skill 共用，或跨产线的判定源）

| 模块 | 职责 | 谁在用 |
|---|---|---|
| `tts` | edge-tts 合成内核：词级时间戳、重试、内容寻址缓存 | karaoke + poetry |
| `audio` | ffmpeg 音轨合成与时长探测 | karaoke + poetry |
| `timeline` | 行时间轴与词级进度轴 | 成片线 + 课件渲染线 |
| `textlayer` | Edge headless 渲字（视口探测 / 截图 / 双 matte 抠像） | poster + poetry |
| `compose` | 母版叠加合成（`-shortest` → 显式 `-t` 的教训） | 成片线 + 课件渲染线 |
| `render` | 帧编码基座：rawvideo → ffmpeg 管道 | 同上 |
| `covers` | 封面机制：平台规格 / 预裁底图 / 裁切模拟 | poster + poetry |
| `manifest` | 发布清单：文案稿解析 / 平台限制检查 / 清单构建 | publishing + lesson-scene |
| `metrics` | 指标回流：两级凭据、null≠0 | publishing + lesson-scene |
| `data` | 数据入口唯一事实源：personas / languages / lessons | 各 skill 共读 |
| `audit` | 格律计数审计：声称 vs 实测 | poetry + 课件诗稿 |
| `devices` | 装置外框样式注册表（16 样式） | character-rig（画）+ lesson-scene（校验） |
| `rig` | 人物 rig 本体：色表 / 物理 / 缓动 / FACE_SPECS / MOOD_FACE / POSE_CODES / draw_character | character-rig（说明书）+ lesson-scene（校验判据） |
| `scenes` | 背景场景原语：65 注册场景 + prerender_bg + DrawScaled | character-rig + lesson-scene（doctor 合法值） |
| `persona` | 人设契约校验器（`feuille persona validate` 直调） | character-rig + lesson-scene（doctor 班底体检） |

### infrastructure —— 6 个（与业务无关的底座）

| 模块 | 职责 |
|---|---|
| `platform` | 浏览器 / ffmpeg / ffprobe / magick 跨平台解析，全仓唯一事实源（三系统可跑的保证） |
| `ledger` | 产物缓存账本：谁新鲜、谁过期、为什么 |
| `framehash` | 逐帧像素基线（按平台分桶），验收的像素判据 |
| `packaging` | 交付打包（zipfile，非 ASCII 文件名必须置 UTF-8 flag） |
| `cli` | 统一入口路由表 `feuille <组> <命令>`——路由表是数据不是 if/elif |
| `_run_verify_probes` | `feuille verify` 的 CLI 桥，转发到 scripts/verify_probes.py |

### skill 专属 —— 6 个（只被这一个 skill 用的业务实现）

| 模块 | 归属 | 职责 |
|---|---|---|
| `publish`（base / login / douyin / xhs / bilibili / collections / veriflive） | multilingual-video-publishing | Playwright 发布器本体；对包内其他模块零依赖，自成一体 |
| `lesson` / `parse_scene` / `scene_schema` / `scene_draft` / `section_patch` | lesson-scene | 开坑体检 / scene.md→scene.json / parse-render 之间校验闸门 / 创意→草稿 / 按节头整节替换 |

> skill 层（`skills/<name>/`）只放**不会被 import** 的资产：SKILL.md 说明书、模板、
> 工作样例、直接执行的诊断脚本（`gen_bgm.py`、`check_publish_copy.py`、
> `build_video.py`……）。会被 import 的实现一律进包、进账本。

## 使用

```bash
cd usine                      # uv 工程根（pyproject.toml 所在层）
uv sync                     # 安装主依赖
uv sync --group publish    # 加装 Playwright（发布器用）
uv sync --group music      # 加装 Lyria 客户端（bgm-bed 生成 BGM 床用）
uv run feuille verify       # 全量反向验证（19 套 330+ 项断言）
uv run feuille verify --list       # 列出所有验证套件
uv run feuille verify --only rig   # 单跑一套
```

## skills/ 跨机器复用

自建 skill 自足在仓库内，不含任何绝对路径或本机解释器绑定；换机器 clone 后只需三步：

```bash
uv sync --project usine                      # ① Python 依赖（edge-tts / pillow / numpy 由 usine/pyproject.toml 锁定）
mkdir -p ~/.agents/skills                    # ② 挂软链，让本机 agent 能发现 skill
for s in usine/skills/*/; do ln -sfn "$PWD/$s" ~/.agents/skills/"$(basename "$s")"; done
# ③ 系统外部工具：Chromium 系浏览器（headless 渲字）、ffmpeg（合成/测量）；可选 Playwright 走 publish 组
#    软链只是发现入口——某条软链缺失不影响使用：直接读本仓库 usine/skills/<name>/SKILL.md 照常工作
```

自足约定（skill 收录时必须满足，违反即无法跨机器复用）：

- 脚本与 SKILL.md 内**禁止出现**任何 `/home/…`、`~/.agents`、特定 conda/venv 解释器路径——一律写 `uv run --project usine python …` 或仓库相对路径；
- 每种文字系/场景的**完整工作样例**必须进 skill 资产（`assets/example/`），不得只留骨架模板、让使用者去翻历史项目或 reflog；
- 逐字形实测的几何值（如韩语色块）不可硬编码迁移，必须配套可重跑的测量脚本（`one-page-poster/scripts/measure_korean.py`）；
- 依赖外部能力（如 BGM 的 Google Lyria）必须在 SKILL.md 显式声明为可选，并给出无该能力时的退化路径（`bgm.file` 接任意纯音乐 wav 或删掉 bgm 段）。

## docs/ 一览

| 文件 | 内容 |
|---|---|
| [workflow.md](docs/workflow.md) | 工作流运行手册（①–⑬：内容创作→合集收录，每段输入/步骤/产物/检查） |
| [toolchain.md](docs/toolchain.md) | 工具链：①–⑬ 每段用什么工具 + 工具明细 + 平台后台 |
| [publish-lessons.md](docs/publish-lessons.md) | 发布踩坑与经验教训总账（270 行，按平台分节） |
| [publish-playbook.md](docs/publish-playbook.md) | 多平台发布手册（881 行，32 条坑 + 三条元规则） |
| [zhihu-publish-playbook.md](docs/zhihu-publish-playbook.md) | 知乎发布手册（409 行，20 条坑） |
| [metrics-playbook.md](docs/metrics-playbook.md) | 数据取数手册（220 行） |
| [render-handbook.md](docs/render-handbook.md) | 渲染工程手册（1301 行，踩坑实录 §5） |
| [lessons-learned.md](docs/lessons-learned.md) | 经验总纲（入口式，只写最终成立的结论） |
