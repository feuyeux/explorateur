# une usine avec des machines rugissantes

> 「一座轰鸣着机器的工厂」——人物是数据（personas），课程是数据（lessons），不是代码。

28 × 10 秒人物「亮相卡」渲染管线：14 语种教学视频班底，每人设一张竖版短片
（`build/intro/<id>.mp4`，1080×1920 @ 30fps，h264+aac）；RTL 4 语卡另渲
**女性观众版** `<id>_f.mp4`（self-intro §1.4，双版本独立缓存键，共 32 个渲染单元）。
每张卡 = edge-tts 语音 + Edge headless 文字层 + Pillow 逐帧绘制，ffmpeg 合成。

> **当前状态**（2026-10-03）：
> ① 人物形象按人设差异化——`FACE_SPECS` 六型脸（圆/长/椭圆/宽/心形/方颌）逐人指派，
> 新增分缝短发/齐刘海发型、`outfit` 服装槽（丹宁 A 字裙/背带裙/长衫/马甲/扣排）与
> 人设化配饰（拉链头/笔记夹板/肩毛巾），背包只保留 quirk 驱动的两位；32 单元验收全绿。
> ② 课程资料按课归拢——每课一个 `lessons/<id>/` 目录（剧本 + 解析产物 + 逐句解析），
> 文档线全面参数化（`--scene`），新课照抄目录体例即接入，管线零改动。
> ③ 人物生成技术选型经四路线评审，**Pillow 管线续役**；MiniMax-H3 + Remotion
> 迁移案裁定为备选蓝图（决策记录见 [adr-character-tech.md](docs/adr-character-tech.md)）。

---

## 文件地图

| 文件 | 职责 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 项目规则、不变量与「想改 X → 去哪改」地图 |
| [requirement.md](docs/requirement.md) | 原始规格：界面三区布局（文字/气泡/人物）+ 人物四轴（声音/动作/色彩/挂件） |
| [plan.md](docs/plan.md) | 总规划：28 人班底、persona schema、选角规则、幂等保障、三管线路线 |
| [render-handbook.md](docs/render-handbook.md) | 工程手册——改任何东西前先读。§3 是参数地图；§5 是踩坑实录 |
| [self-introductions.md](docs/self-introductions.md) | 内容种子——每卡台词、注音、对照、场景与手势触发 |
| `lessons/<id>/`（如 [lessons/colors/](lessons/colors/scene.md)） | **课程统一目录**：`scene.md`（场景剧本唯一事实源：§0 机读规格 + §2 各语种台词 + §5 token 词表，不设母本、不互译）+ `scene.json`（解析产物）+ `analysis/`（逐句解析） |
| [adr-character-tech.md](docs/adr-character-tech.md) | 技术决策：Pillow 管线续役；H3+Remotion 迁移案为备选蓝图（含四路线裁定） |
| [benchmark-duolingo.md](docs/benchmark-duolingo.md) | 对标台账——多邻国三文档逐条裁定（✅已达成/🔧补齐/📌备选/❌不采纳）；quirk 治理规则 |
| [publish-playbook.md](docs/publish-playbook.md) | 发布手册——抖音 / 小红书创作服务平台双平台流程、平台差异对照、18 条踩坑实录、发布后核验清单 |
| `personas/personas.json` | 28 人档案——声线/色板/脸型/发型/服装/配饰/RTL + 档案四字段（名字语义/声线画像/搭档关系/趣味设定）（人设唯一事实源） |
| `personas/intro-cards.json` | 28 张卡——台词/情绪/手势/入场姿态/场景/收尾码列/A·B 选角；RTL 卡带 `variants[]`（女性观众版） |
| `pyproject.toml` / `uv.lock` / `.venv` | uv 工程清单与锁定的单一虚拟环境（uv 托管 CPython 3.12；依赖精确锁版，Pillow 12.3.0 是像素基线）；控制台入口 `usine-cards` / `usine-parse` / `usine-scene` / `usine-lesson` / `usine-dump-lesson` |
| `src/usine/intro_cards.py` | 管线一本体（`tts` / `assets` / `render` 三个子命令） |
| `src/usine/parse_scene.py` | 通用教学场景解析器：`lessons/<id>/scene.md` → `lessons/<id>/scene.json`（只抽取不改写，保证 md 与 JSON 两处同步；规格全来自剧本 §0，场景无关） |
| `src/usine/scene_video.py` | 管线二（A/B 对话教学场景，场景无关）：选角/双人站位/token 装置（色片/字牌，可选）/气泡/RTL 镜像 |
| `src/usine/qa_*.py` | 验收五件套——网格探针 / 调色板探针 / 32 单元全量 / 动态验收 / 场景线 |
| `src/usine/dump_lesson_source.py` | 把 `lessons/<id>/scene.json` 排版成 `lessons/<id>/analysis/_source/<locale>.md`（给逐句解析用的可读源文本，只排版不改写） |
| `src/usine/build_lesson.py` | 合并 `lessons/<id>/scene.json` + `lessons/<id>/analysis/<locale>.json` → `build/lesson/<id>/index.html`：按语系排序、逐句语法/词法/文化解析、每语种末尾嵌视频 |
| `scripts/` | 发布侧独立工具（抖音合集/发布，Playwright；`uv sync --group douyin` 按需装依赖）＋ 验收侧回归测试（verify_text_contract.py） |

---

## 快速上手

统一入口 [`run.ps1`](run.ps1)：

```powershell
.\run.ps1 all                                     # 亮相卡全流程：tts → assets → render → qa → qa-motion（~5 分钟）
.\run.ps1 tts                                     # 逐行合成 + 词级时间戳（edge-tts）
.\run.ps1 assets                                  # 文字层 PNG（Edge headless，~144 张）
.\run.ps1 render -Only xiaoman,layla -Workers 7   # 帧渲染 + ffmpeg
.\run.ps1 qa                                      # 32 单元全量验收（28 卡 + 4 变体）
.\run.ps1 qa-motion                               # 卡拉OK / 口型 / 眨眼 / 气泡镜像 / 进度条 / 语言牌 / 挂件物理 / 幂等

.\run.ps1 scene -Scene colors                     # 场景线：parse → tts → assets → render（14 语种，~20 分钟）
.\run.ps1 scene -Scene colors -Only zh-CN,ja-JP   # 只渲指定语种
.\run.ps1 scene-list -Scene <id>                  # 列场景（台词行数 / 时长 / 选角 / 装置）
.\run.ps1 qa-scene -Scene <id>                    # 场景线验收（规格 / 文本契约 / 选角 / 画面探针 / 音频契约 / 幂等）

.\run.ps1 dump-lesson -Scene colors               # 导出逐语种解析源文本（analysis/_source/）
.\run.ps1 lesson -Scene colors                    # 合并成 build/lesson/colors/index.html
```

### 课程资料组织（每课一目录）

一切课程资料都在 `lessons/<id>/` 里，不同主题互不混杂：

```
lessons/colors/
├─ scene.md                    # 场景剧本（唯一事实源：§0 机读规格 + §2 各语种台词 + §5 token 词表）
├─ scene.json                  # 解析产物（parse_scene.py 只抽取不改写；渲染与教学文档共用）
└─ analysis/
   ├─ _source/<locale>.md      # 逐语种可读源文本（dump_lesson_source.py 导出，供逐句解析委派）
   └─ <locale>.json            # 逐句 {grammar, morph, culture} + 家族/书写/舞台三段（人工产出）
```

产物在 `build/` 下按课分家：成片 `build/scene/scene-<id>_<locale>.mp4`（跨课共享渲染缓存，
文件名带 `scene-<id>` 前缀），教学文档 `build/lesson/<id>/index.html` + 海报。

### 场景线产物（示范场景二：colors 课）

`build/scene/scene-colors_<locale>.mp4`——14 语种各一支 40–55s 的 A/B 对话教学片，
文件名带语种后缀。两人同框立绘、词级时间戳驱动口型与色名卡拉OK高亮、每语种独立舞台装置
（六色边问边亮）、思考/提示气泡交替镜像、ar-SA 与 he-IL 站位与文字区 RTL 对调。

### 教学文档（场景线配套）

`build/lesson/<id>/index.html`——按语系排序的完整教学文档。每个语种一节：家族背景 / 书写特点 /
舞台文化三段，六色词表，17 行逐句的**原文 + 注音 + 中文翻译 + 中文语法解析 + 中文词法解析 +
文化背景**，本语种成片嵌在该节末尾，可以边看边对。顶部两个开关只切换显示、不删内容。

```powershell
uv run usine-dump-lesson --scene colors --only ja-JP   # 指定课程/语种导出解析源文本
uv run usine-lesson --scene colors [--allow-missing]   # 合并成 build/lesson/<id>/index.html
```

分工：原文 / 注音 / 翻译 / 舞台规格来自 `lessons/<id>/scene.json`（与渲染同源），
逐句解析来自 `lessons/<id>/analysis/<locale>.json`（人工产出，14 份），
`build_lesson.py` 只排版、两侧文本都不改写，并在出片前做标签配平自检。

### uv 单一环境（run.ps1 全部经 `uv run`）

- 本工程是标准 uv 工程（src 布局）：代码在 `src/usine/`，`uv run` 按 `pyproject.toml` + `uv.lock`
  自动同步 `.venv`（uv 托管 CPython 3.12）——不再区分系统 Python / 捆绑 Python；
- 依赖精确锁版（`edge-tts==7.2.8` / `pillow==12.3.0` / `numpy==2.3.5`）；
  **Pillow 12.3.0 是像素基线**，升级前必须重验 framehash 基线；
- `.venv` 缺失时 `uv sync` 一次即可（run.ps1 会自动做）。

直连等价命令：

```powershell
uv run usine-cards tts     [--only id1,id2]
uv run usine-cards assets  [--only id1,id2]
uv run usine-cards render  [--only id1,id2] [--workers 7]
uv run python -m usine.qa_all
```

### 验收基线

改完任何东西：**qa_all 32/32 PASS + qa_motion PASS**；场景线另加 **qa_scene PASS**。

---

## 工作原理

```
personas/personas.json        （28 人档案：声线/色板/脸型/发型/服装/配饰）
personas/intro-cards.json     （28 卡：台词/情绪/手势/场景/选角）
        └→ ① tts ──→ ② assets ──→ ③ render ──→ build/intro/<id>.mp4

lessons/<id>/scene.md         （教学场景唯一事实源：§0 机读规格 + §2 台词 + §5 词表）
        └→ parse_scene.py --scene <id> ──→ lessons/<id>/scene.json
lessons/<id>/scene.json + personas └→ ① tts ──→ ② assets ──→ ③ render ──→ build/scene/scene-<id>_<locale>.mp4
lessons/<id>/scene.json + analysis/ └→ build_lesson.py ──→ build/lesson/<id>/index.html
```

1. **tts**——每行按情绪合成语音，`boundary="WordBoundary"` 捕获词级时间戳，混音出恰好
   10.0s 的 `.m4a` + `timeline.json`。行音频按 `sha256(voiceId|rate|pitch|text)[:16]` 缓存——
   改一行台词只重合成那一行。
2. **assets**——每个 HTML 文字层经 Edge headless 双色截图（白底 + 黑底），
   `matte_combine` 依 `alpha = 255 − (C_w − C_b)` 精确抠像，半透明投影也能还原。
3. **render**——每帧 = 2x 预渲染背景 → 2x RGBA 人物层（`draw_character`，BOX 降采样抗锯齿）
   → 文字带卡拉OK裁贴 → 名牌/语言牌/气泡贴图 → rgb24 管道喂 ffmpeg。

架构图与缓存模型见 [render-handbook.md](docs/render-handbook.md)（§1 架构、§2 不变量、§5 踩坑实录）。

---

## 设计原则

浓缩自 [CLAUDE.md](CLAUDE.md) 的不变量与 [plan.md](docs/plan.md) §4（人物参数模型）/ §7（高质量与幂等保障）：

- **人设是数据不是代码**：`personas.json` 驱动整个绘制 rig（`face_geo()` 六型脸是几何唯一事实源，
  脸型/服装/配饰全走数据槽）；场景里永不写死 RGB、嘴形、眨眼节奏。
- **课程是数据不是代码**：教学 token、RTL 语种、舞台装置全在 `lessons/<id>/scene.md` §0 机读规格里；
  新课 = 新建目录照抄体例，解析器与渲染线零改动。
- **词级时间戳一轴三用**：口型开合、卡拉OK逐词高亮、手势触发共用同一时间轴，换台词自动重对齐。
- **动作排他是人设数据**：剧本只写槽位语义（point/wave…），每人 `personas.json` `moves`
  槽位表映射成专属姿态码——逐人单射、活泼池∩沉稳池=∅，同台 A/B 动作词汇零交集由构造保证。
- **场景文字带三层堆叠**：原文（64px 自适应缩排）→ 中文对照（30px）→ ⚑ 文化/语言注记
  （22px 金，比对照更小一号）；对照只认第一个 ｜ 之前的「——」，注记内可自由用破折号。
- **画面不靠色**：舞台背板带把人物区渐变底压暗 26%（奶油色上装/肤色才不陷进米色底），
  场景原语再按同台取样色半空间推开；文字带各层文字色与带底、卡拉OK高亮与带底、
  立绘与背景的对比全部有 qa_scene 数值探针。
- **幂等是硬约束**：一切随机性播种（`rnd(seed:...)`）；同输入 → 视频流逐帧同输出
  （`ffmpeg -map 0:v -f hash -hash md5` 抽检；容器字节差来自 ffmpeg 元数据，属正常）。
- **人物无描边**（多邻国式纯平涂）；场景道具描边只用 `pal["ink"]` 柔色。
- **情绪与手势是数据不是发挥**：共享情绪增量表（neutral / happy / puzzled / encouraging /
  emphatic / teach）+ 行级基线，合成出声线与表情参数。

---

## 班底一览

14 语种 × 男女 = 28 位 persona。每语种一对「活泼 × 稳重」搭档——自然的对话张力，
同语种内的声学多样性。脸型/发型/着装/配饰按人设逐人差异化：心形脸小满、方颌江远、
宽盘脸米沙……丹宁裙、背带裙、长衫、马甲各有归属，背包只留给「书包不离身」写进 quirk 的两位。

| 语种 | 女声 | 男声 | 语种 | 女声 | 男声 |
|---|---|---|---|---|---|
| zh-CN | 林小满 | 江远 | ja-JP | ハルカ | リク |
| en-US | Ruby | Miles | ko-KR | 서연 | 도윤 |
| fr-FR | Chloé | Théo | it-IT | Giulia | Luca |
| de-DE | Lena | Felix | he-IL | נועה | יובל |
| es-ES | Lucía | Mateo | zh-HK | 阿晴 | 阿豪 |
| ru-RU | Аня | Миша | hi-IN | प्रिया | अर्जुन |
| el-GR | Ελένη | Νίκος | ar-SA | ليلى | عمر |

完整档案（声线、色板、脸型、着装、招牌动作、配饰、人物关系）见 [plan.md](docs/plan.md) §5。

---

## 想改什么 → 去哪改

| 想改 | 改这里 |
|---|---|
| 台词 / 注音 / 中文对照 | [self-introductions.md](docs/self-introductions.md) + `intro-cards.json` `lines[].text`（**两处同步**），跑 tts 看 speech_end ≤ 8.5s |
| 情绪 / 手势触发 | 行级 `intro-cards.json` `lines[].mood`；卡级 `gestures[]`（手势词必须真实出现在台词里，否则回退到行首） |
| 收尾招牌动作 | `intro-cards.json` `close`（pose 码见 `pose_for`，时长表在 `render_card`） |
| 人设（名字/声线/色板/脸型/发型/服装/配饰） | `personas/personas.json`（脸型走 `FACE_SPECS` 六型；服装走 `outfit` 槽——skirt/tunic/pinafore/vest/buttons；qa_char 对照色板与探针，改后必跑 qa_all） |
| 人物档案（名字语义/声线画像/搭档关系/趣味设定） | `personas/personas.json` 的 `gloss`/`timbre`/`relation`/`quirk`——不进渲染；quirk 入档即正史（治理规则见 [benchmark-duolingo.md](docs/benchmark-duolingo.md) §4.2） |
| 头身比例 / 五官位置 | 只改 `face_geo()` 比率表；发型/配饰/探针全部按比例自动跟随 |
| 场景背景 | `intro_cards.py` 的 `@scene(...)` 原语注册表 + 卡级 `scene[]` |
| 名牌 / 语言牌 / 气泡样式 | `badge_html` / `pill_html` / `bubble_html`（流式布局） |
| 人物生成技术路线 | 见 [adr-character-tech.md](docs/adr-character-tech.md)（现役 Pillow；动 `draw_character` 前先读） |
| **新增课程**（数字/食物/问候…） | 新建 `lessons/<id>/scene.md` 照抄体例（§0 机读规格 + §2 台词 + §5 词表），然后 `.\run.ps1 scene -Scene <id>`——**管线零改动**（token 用 `#hex` 色片或 `"文本"` 字牌；纯对话场景装置表留空即可） |
| 场景台词 / 情绪 / 手势 / 舞台 | 只改该课的 `lessons/<id>/scene.md`，然后 `.\run.ps1 scene -Scene <id> -Only <locale>`（解析器只抽取不改写，md 仍是唯一事实源） |
| 场景教学 token / RTL / 装置规格 | `lessons/<id>/scene.md` **§0**（token 表 + 装置规格表；井位/井形/空井色全在数据里） |
| 逐句语法/词法/文化解析 | `lessons/<id>/analysis/<locale>.json`（先 `.\run.ps1 dump-lesson -Scene <id>` 导出源文本），然后 `.\run.ps1 lesson -Scene <id>` 合成文档 |
