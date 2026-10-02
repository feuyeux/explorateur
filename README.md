# une_usine_avec_des_machines_rugissantes

> 「一座轰鸣着机器的工厂」——人物是数据（personas），不是代码。

28 × 10 秒人物「亮相卡」渲染管线：14 语种教学视频班底，每人设一张竖版短片
（`build/intro/<id>.mp4`，1080×1920 @ 30fps，h264+aac）。
每张卡 = edge-tts 语音 + Edge headless 文字层 + Pillow 逐帧绘制，ffmpeg 合成。

> **当前状态**（2026-10-03）：人物形象完成几何重设计（躯干肩同宽 + 肩楔衔接 + 肩点内收，
> 修复头/身/手脱节与名牌截断），28 卡验收全绿。人物生成技术选型经四路线评审，**Pillow
> 管线续役**；MiniMax-H3 + Remotion 迁移案裁定为备选蓝图（决策记录见
> [adr-character-tech.md](adr-character-tech.md)）。

---

## 文件地图

| 文件 | 职责 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 项目规则、不变量与「想改 X → 去哪改」地图 |
| [requirement.md](requirement.md) | 原始规格：界面三区布局（文字/气泡/人物）+ 人物四轴（声音/动作/色彩/挂件） |
| [plan.md](plan.md) | 总规划：28 人班底、persona schema、选角规则、幂等保障、三管线路线 |
| [render-handbook.md](render-handbook.md) | 工程手册——改任何东西前先读。§3 是参数地图；§5 是踩坑实录 |
| [self-introductions.md](self-introductions.md) | 内容种子——每卡台词、注音、对照、场景与手势触发 |
| [adr-character-tech.md](adr-character-tech.md) | 技术决策：Pillow 管线续役；H3+Remotion 迁移案为备选蓝图（含四路线裁定） |
| `personas/personas.json` | 28 人档案——声线/色板/发型/配饰/RTL（人设唯一事实源） |
| `personas/intro-cards.json` | 28 张卡——台词/情绪/手势/场景/收尾动作/A·B 选角 |
| `intro_cards.py` | 管线本体（`tts` / `assets` / `render` 三个子命令） |
| `qa_*.py` | 验收四件套——网格探针 / 调色板探针 / 28 卡全量 / 动态验收 |

---

## 快速上手

统一入口 [`run.ps1`](run.ps1)：

```powershell
.\run.ps1 all                                     # tts → assets → render → qa → qa-motion（~5 分钟）
.\run.ps1 tts                                     # 逐行合成 + 词级时间戳（系统 Python · edge-tts）
.\run.ps1 assets                                  # 文字层 PNG（Edge headless，~122 张）
.\run.ps1 render -Only xiaoman,layla -Workers 7   # 帧渲染 + ffmpeg
.\run.ps1 qa                                      # 28 卡全量验收（28/28）
.\run.ps1 qa-motion                               # 卡拉OK / 口型 / 眨眼 / 气泡镜像
```

### 两解释器分工（run.ps1 强制封装）

- **tts** 用**系统 `python`**——全机只有它装了 edge-tts；
- **assets / render / qa** 用**捆绑 DSH Python**（`C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`，带 Pillow + numpy）。

直连等价命令（解释器各归各位，用错立刻 ImportError）：

```powershell
python  intro_cards.py tts     [--only id1,id2]
python  intro_cards.py assets  [--only id1,id2]
C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe `
        intro_cards.py render  [--only id1,id2] [--workers 7]
```

### 验收基线

改完任何东西：**qa_all 28/28 PASS + qa_motion PASS**。

---

## 工作原理

```
personas/personas.json        （28 人档案）
personas/intro-cards.json     （28 卡：台词/情绪/手势/场景/选角）
        └→ ① tts ──→ ② assets ──→ ③ render ──→ build/intro/<id>.mp4
```

1. **tts**——每行按情绪合成语音，`boundary="WordBoundary"` 捕获词级时间戳，混音出恰好
   10.0s 的 `.m4a` + `timeline.json`。行音频按 `sha256(voiceId|rate|pitch|text)[:16]` 缓存——
   改一行台词只重合成那一行。
2. **assets**——每个 HTML 文字层经 Edge headless 双色截图（白底 + 黑底），
   `matte_combine` 依 `alpha = 255 − (C_w − C_b)` 精确抠像，半透明投影也能还原。
3. **render**——每帧 = 2x 预渲染背景 → 2x RGBA 人物层（`draw_character`，BOX 降采样抗锯齿）
   → 文字带卡拉OK裁贴 → 名牌/语言牌/气泡贴图 → rgb24 管道喂 ffmpeg。

架构图与缓存模型见 [render-handbook.md](render-handbook.md)（§1 架构、§2 不变量、§5 踩坑实录）。

---

## 设计原则

浓缩自 [CLAUDE.md](CLAUDE.md) 的不变量与 [plan.md](plan.md) §4（人物参数模型）/ §7（高质量与幂等保障）：

- **人设是数据不是代码**：`personas.json` 驱动整个绘制 rig；场景里永不写死 RGB、嘴形、眨眼节奏。
- **词级时间戳一轴三用**：口型开合、卡拉OK逐词高亮、手势触发共用同一时间轴，换台词自动重对齐。
- **幂等是硬约束**：一切随机性播种（`rnd(seed:...)`）；同输入 → 视频流逐帧同输出
  （`ffmpeg -map 0:v -f hash -hash md5` 抽检；容器字节差来自 ffmpeg 元数据，属正常）。
- **人物无描边**（多邻国式纯平涂）；场景道具描边只用 `pal["ink"]` 柔色。
- **情绪与手势是数据不是发挥**：共享情绪增量表（neutral / happy / puzzled / encouraging /
  emphatic / teach）+ 行级基线，合成出声线与表情参数。

---

## 班底一览

14 语种 × 男女 = 28 位 persona。每语种一对「活泼 × 稳重」搭档——自然的对话张力，
同语种内的声学多样性。

| 语种 | 女声 | 男声 | 语种 | 女声 | 男声 |
|---|---|---|---|---|---|
| zh-CN | 林小满 | 江远 | ja-JP | ハルカ | リク |
| en-US | Ruby | Miles | ko-KR | 서연 | 도윤 |
| fr-FR | Chloé | Théo | it-IT | Giulia | Luca |
| de-DE | Lena | Felix | he-IL | נועה | יובל |
| es-ES | Lucía | Mateo | zh-HK | 阿晴 | 阿豪 |
| ru-RU | Аня | Миша | hi-IN | प्रिया | अर्जुन |
| el-GR | Ελένη | Νίκος | ar-SA | ليلى | عمر |

完整档案（声线、色板、招牌动作、配饰、人物关系）见 [plan.md](plan.md) §5。

---

## 想改什么 → 去哪改

| 想改 | 改这里 |
|---|---|
| 台词 / 注音 / 中文对照 | [self-introductions.md](self-introductions.md) + `intro-cards.json` `lines[].text`（**两处同步**），跑 tts 看 speech_end ≤ 8.5s |
| 情绪 / 手势触发 | 行级 `intro-cards.json` `lines[].mood`；卡级 `gestures[]`（手势词必须真实出现在台词里，否则回退到行首） |
| 收尾招牌动作 | `intro-cards.json` `close`（pose 码见 `pose_for`，时长表在 `render_card`） |
| 人设（名字/声线/色板/发型/配饰） | `personas/personas.json`（qa_char 对照色板；改色必跑 qa_all） |
| 头身比例 / 五官位置 | 只改 `face_geo()` 比率表；发型/配饰/探针全部按比例自动跟随 |
| 场景背景 | `intro_cards.py` 的 `@scene(...)` 原语注册表 + 卡级 `scene[]` |
| 名牌 / 语言牌 / 气泡样式 | `badge_html` / `pill_html` / `bubble_html`（流式布局） |
| 人物生成技术路线 | 见 [adr-character-tech.md](adr-character-tech.md)（现役 Pillow；动 `draw_character` 前先读） |

**不变量**（每条都来自一次真实翻车）见 [render-handbook.md](render-handbook.md) §2 与 [CLAUDE.md](CLAUDE.md)。
