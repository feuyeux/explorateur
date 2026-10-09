# Skills 总路由

九个 skill,三层。**先判断在哪一层,再选 skill**。

## 层次

```
┌─ 课件与绘制层（内容生产，不出成片）──────────────────────┐
│  lesson-scene      scene.md ⇄ scene.json + 校验          │
│  character-rig     人物 rig / 背景场景 / 人设契约校验      │
└──────────────────────────────────────────────────────────┘
┌─ 成品层（出画面）───────────────────────────────────────┐
│  Cluster A 画面由渲染生成                                 │
│    one-page-poster → karaoke-video（单卡片）              │
│                      └→ storyteller-video（多幕评书导演层）│
│  Cluster B 画面是实拍                                     │
│    video-generation（出母版）→ multilingual-video-poetry  │
└──────────────────────────────────────────────────────────┘
┌─ 音频层（成片线共用）────────────────────────────────────┐
│  bgm-bed            底床生成（Lyria 实测线；死线已删）+          │
│                     床位定标                                      │
└──────────────────────────────────────────────────────────┘
┌─ 收尾层───────────────────────────────────────────────┐
│  publish-copy               写发布词（各线共用）           │
│  multilingual-video-publishing   发平台 + 建合集 + 核验   │
└──────────────────────────────────────────────────────────┘
```

**画面产线的分水岭：有没有实拍母版。** 有 → Cluster B；只有海报/卡片 → Cluster A。
Cluster A 内部再分：**单卡片逐词高亮 → karaoke-video；多幕评书（每幕一景一镜
一转场、说书人立绘）→ storyteller-video**——它复用 karaoke 的时间轴与合片
机制，只新增导演层。音频不分线——各成片线读的是同一条床，只是压法不同
（线性 / 侧链），所以 `bgm-bed` 独立成 skill。

**Cluster B 的母版从哪来**：`video-generation`——三条视频线选线（Hailuo-2.3 走
套餐额度、H3 烧积分），提交前确认、取回后冻结。

## 路由表

| 我要做的事 | 用这个 | 前置必须已有 | 它不管 |
|---|---|---|---|
| 一页纸海报 / 12 语种排版 / 逐字着色 | `one-page-poster` | 内容清单 + 网格规格 + 配色 | 成片视频 |
| 海报/卡片 → 旁白视频（逐词高亮） | `karaoke-video` | 已有海报 + 各语种文案 + 音色 | 实拍画面 |
| **人物小传 / 多幕评书**（说书人 + 每幕一景一镜一转场 + 醒木） | `storyteller-video` | 人物资料 + 幕表（文本/场景/镜头）+ 说书人 | 单卡片成片、实拍画面 |
| **出实拍母版**（选视频线 / 提交确认 / 取回冻结） | `video-generation` | 画面描述 + 画幅 + 时长 + 套餐额度状态 | 母版上的字幕/旁白/混音 |
| **实拍母版** → 配文视频（压字幕 + 侧链混音） | `multilingual-video-poetry` | **一条实拍母版视频**（由 `video-generation` 出）+ 配文 | 海报/卡片画面 |
| 生成 BGM 床 / 定床位（两条成片线共用） | `bgm-bed` | 成片时长 + 配器短词 + 旁白实测电平 + 至少一家供应商 key | 把床混进成片 |
| 新课开坑 / 课件解析 / 场景校验 / 草稿 | `lesson-scene` | 课 id + 场景骨架 + 语种范围 | 画人物与背景 |
| 画人物 / 背景场景 / 装置外框 / 校验人设 | `character-rig` | 人设字段 + 场景名（取注册表真键） | 写课件 |
| 小红书/抖音/B站 发布词 | `publish-copy` | 成品 + 核验数字 | 实际点发布 |
| 抖音/小红书/B站 批量发布、建合集（合集仅抖音）、回列表核验 | `multilingual-video-publishing` | 成片 + 发布清单 | 写文案 |

## 完整产线（完成定义）

**一个内容项目只有下表四层全齐才算完成；缺任何一层都是半成品，不许静默收工。**
任务往往以碎片进来（修一条供应商线、补一张床、改一版海报）——收工前必须拿这张表
盘点项目现状：当场补齐缺口，或者明说缺哪层、为什么不做；只字不提就是流程截断。

| 层 | Cluster A 海报驱动 | Cluster B 实拍驱动 | 完成判据 |
|---|---|---|---|
| 画面层 | `one-page-poster` → `karaoke-video`（单卡片）或 `storyteller-video`（多幕评书） | `multilingual-video-poetry` | build 退出 0 + `verify_sync` 全过（A）/ 母版与字幕验收（B） |
| 音频层 | `bgm-bed`（各线读同一条床，压法不同） | 同左 | `gen_bgm` 判据全绿，床长 ≥ 成片时长 |
| 混后验收 | 床位 15–18 dB · 连续性 ≥ −45 dBFS · 平稳性 ≤ 12 dB · LUFS 配比 ≥ 8 dB | 同左（侧链压法） | 五项全过，数字记进项目文档 |
| 收尾层 | `publish-copy`：竖屏 → 小红书/抖音，横屏 → B站 | 同左 | 每平台一份 `publish/*.md` + no-hard-wrap 自检 0 违规 |
| 发布执行 | `multilingual-video-publishing` | 同左 | 需用户明确指令，agent 不自动碰；平台回列表核验通过 |

细则各归各的 SKILL.md / field notes，本表只定「到哪才算完」。

## 三层归属模型

| 层 | 是什么 | 落点 |
|---|---|---|
| **skill** | 说明书：怎么用 + 工作样例 + 诊断脚本 | `skills/<name>/` |
| **library** | 被 ≥2 个 skill 用的业务实现，或跨产线共用的判定源 | `src/feuille/` |
| **infrastructure** | 与业务无关的底座：平台解析、缓存账本、打包、CLI 路由 | `src/feuille/` |

**归属唯一，跨用不另写。** 例如 `tts` 归 library，`karaoke-video` 与
`multilingual-video-poetry` 都用它——但不许任何一方在自己目录里再实现一份。

`usine/ownership.json` 是归属的唯一事实源；每个 SKILL.md 的 `## 代码归属` 段用
`拥有模块：a, b` 那一行声明自己的地盘，与清单**双向机检**。

## 多处易混能力的唯一归属

| 能力 | 归谁 | 不要在别处实现 |
|---|---|---|
| 多语种字体子集 / 逐字着色 / 塑形 | `one-page-poster`（说明书）＋ `library/textlayer`（实现） | 视频 skill 需要新字形时，回 poster 的 `fonts.json` 加并重跑 `fetch_fonts.py` |
| 12 语种规范顺序 | `one-page-poster` §Conventions | 其余 skill 引用，**不另抄一份** |
| TTS / 音轨 | `library` 的 `tts`、`audio` | 不许任何 skill 私藏一份合成逻辑 |
| 脸型 / 表情 / 装置规格注册表 | `library` 的 `rig`、`devices` | `persona.py` 与 `scene_schema.py` 取**同一份**，不抄名单（纪律 7） |
| BGM 床的**生成与床位定标** | `bgm-bed` | 不在任何 skill 里另写一份音乐生成调用或 `gain` 反推。全局 `music-generation` skill 的能力已并入 `bgm-bed`（MiniMax/Suno/Udio 三条死线已删，现存唯一实测线 Lyria）——本工程里它已被取代，见 `bgm-bed` 边界段 |
| BGM 的**混音压法** | 看画面来源 | 海报驱动 → `karaoke-video` 的线性 `amix`；实拍驱动 → `multilingual-video-poetry` 的侧链压缩 |
| 多幕评书**导演层**（幕表 schema / 镜头 / 叠化 / 醒木） | `storyteller-video` | 词级时间轴与合片复用 `karaoke-video` 的脚本，不另写；说书人编外专班走 `feuille.data.storytellers()`，不进班底 roster |
| 封面 | 看画面来源 | 海报驱动 → `one-page-poster` 的 `make_covers.py`；实拍驱动 → `multilingual-video-poetry` 的 `assets/example/封面.py` |
| 发布词 | `publish-copy` | 发布执行 → `multilingual-video-publishing` |

## 七条歧义防线

1. **description 互斥**——每个 skill 都写明「本 skill 不管什么、该转哪个」。description 是 agent 的路由依据，排除语句比介绍语句更有用。
2. **前置输入契约**——每个 SKILL.md 都有 `## 前置输入契约`，缺哪条先问哪条，不要拿占位值往下跑。
3. **边界与转交**——每个 SKILL.md 都有 `## 边界`，显式列出不做什么、转哪个 skill。
4. **事实源唯一**——规范顺序只在 `one-page-poster`；注册表现取不抄；共享实现进 `library`。
5. **代码归属唯一**——`ownership.json` + 每个 SKILL.md 的 `拥有模块：` 行，双向机检。
6. **机检**——`usine/scripts/verify_skills.py` 机检上面全部，回归会被 `feuille verify` 抓到。
7. **完成定义**——交付终点以「完整产线」表为准：四层不齐就是半成品。碎片任务收工前必须按表盘点，缺哪层要么补齐、要么明说，不许静默截断。

**存量代码已全部消化完**：`unclaimed` 为空，每个模块都有家——归 skill、归 library 或归基础设施。