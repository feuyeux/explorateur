# 亮相卡管线 · 工程与调优手册

> 本手册沉淀 28+4 × 10s 亮相卡（`build/intro/<id>.mp4`；RTL 4 语另有 `<id>_f.mp4`
> 女性观众版，self-intro §1.4）从 0 到 1 的全部工程决策：
> 架构不变量、参数地图、验收体系、踩坑实录与调优手册。规划与 schema 见
> [plan.md](plan.md)（§8.2 音频契约、§8.3 人物绘制规格），内容种子见
> [self-introductions.md](self-introductions.md)。**改任何东西前先读 §3 参数地图。**
>
> 人物生成技术路线的裁定记录（含被否的 H3+Remotion 迁移方案）见
> [adr-character-tech.md](adr-character-tech.md)：**现役 = 本手册的 Pillow 管线**。

---

## 0. 快速上手

统一入口 [`run.ps1`](../run.ps1)（全部经 `uv run` 走单一 `.venv`，见 §1；缺 venv 时自动 `uv sync`）：

```powershell
.\run.ps1 tts              # 逐行合成 + 词级时间戳（系统 Python · edge-tts）
.\run.ps1 assets           # 文字层 PNG（Edge headless，~144 张）
.\run.ps1 render           # 帧渲染 + ffmpeg（捆绑 Python · Pillow），--Workers 7
.\run.ps1 render -Only xiaoman,layla
.\run.ps1 qa               # 32 单元全量验收（28 卡 + 4 变体，qa_all.py）
.\run.ps1 qa-motion        # 动态验收（卡拉OK/口型/眨眼/气泡镜像/进度条/语言牌/挂件物理/幂等）
.\run.ps1 all              # tts → assets → render → qa → qa-motion 全流程（~5 分钟）

.\run.ps1 scene            # 教学场景 A/B 对话线：parse → tts → assets → render（-Scene <id> 选场景，缺省 colors）
.\run.ps1 scene -Only zh-CN,ja-JP
.\run.ps1 scene-list       # 场景概览（token 序 / RTL / 装置 / 时长）
.\run.ps1 qa-scene         # 场景线验收（qa_scene.py --scene <id>：规格/文本契约/选角/画面探针/音频契约/幂等）
```

直连命令（run.ps1 的等价形式）：

```powershell
uv run usine-cards tts     [--only id1,id2]          # 逐行合成 + 词级时间戳（edge-tts 7.2.8）
uv run usine-cards assets  [--only id1,id2]          # Edge headless 文字层
uv run usine-cards render  [--only id1,id2] [--workers 7]   # 帧渲染 + ffmpeg（Pillow 12.3.0）
uv run python -m usine.qa_all                        # 32 单元静态验收
uv run python -m usine.qa_motion                     # 动态验收（含幂等重渲抽检）
uv run usine-parse --scene colors                    # scenes/scene-<id>.md → scene_<id>.json（只抽取不改写）
uv run usine-scene render --scene colors [--only zh-CN]
uv run python -m usine.qa_scene --scene colors [--only zh-CN]
```

代码都在 `src/usine/`（uv 项目 src 布局，editable 安装）；`uv run` 自动按 `pyproject.toml` + `uv.lock` 同步 `.venv`（uv 托管 CPython 3.12）。
依赖精确锁版（`edge-tts==7.2.8` / `pillow==12.3.0` / `numpy==2.3.5`）——**Pillow 12.3.0 是像素基线**，升级前必须重验 framehash 基线。

产物：`build/intro/<id>.mp4`（1080×1920，30fps，**恰好 10.0s**，h264 crf18 + aac 192k）。
改完任何东西的验收基线：**qa_all 32/32 PASS（28 卡 + 4 个 RTL 女性观众版）+ qa_motion PASS**。

---

## 1. 架构与数据流

```
personas/personas.json ──┐
（28 人档案：声线/色板/    │
 发型/配饰/identity/RTL）  │
personas/intro-cards.json ┴→ ① tts ──→ ② assets ──→ ③ render ──→ <id>.mp4
（每卡 lines/gestures/       │          │             │
 scene/close/cast A|B）      │          │             │
                        audio/<key>.mp3   text/*.png   build/intro/<id>.mp4
                        audio/<key>.json  (band/badge  + audio/<id>.m4a
                        （词级时间戳）     /pill/bubble  + audio/<id>.timeline.json
                                           双 matte 抠像）
```

- **① tts**：每行按 mood 合成（见 §2 声线契约），`boundary="WordBoundary"` 捕词级时间戳；
  混音 `amix → loudnorm(-16 LUFS) → apad → atrim` 出 `<id>.m4a`（恰好 10.0s）+ `<id>.timeline.json`。
- **② assets**：Edge headless 双色截图（白底/黑底）→ `matte_combine` 精确抠像
  （`alpha = 255 − (C_w − C_b)`，半透明投影可精确还原）。
- **③ render**：每帧 = 背景层（1 次 2x 预渲染）→ RGBA 2x 人物层（`draw_character`，
  BOX 降采样抗锯齿）→ 文字带卡拉OK裁贴 → 名牌/语言牌/气泡贴图 → rgb24 管道给 ffmpeg。

**缓存**：行音频按 `sha256(voiceId|rate|pitch|text)[:16]` 为文件名——改台词自动重合成，
改声线参数全员失效（故**调优只许改文本，不许改声线**）；文字层按名字直接覆盖。
孤儿缓存（被改掉的旧文本 mp3）留在 `audio/` 无害，可整目录清理后全量重建。

---

## 2. 单一事实源与不变量（违反即引入回归）

| 不变量 | 出处 | 纪律 |
|---|---|---|
| **头身几何**：全部派生尺寸（眼位/眉/嘴/躯干/四肢/脚）只从 `face_geo(face)` 取 | `intro_cards.py::face_geo` | 渲染与 qa 探针都 import 它，**永不手抄数字** |
| **声线契约**：缓存键 = `sha256(voiceId\|rate\|pitch\|text)[:16]`；有效参数 = 基线 + mood 增量，钳制 \|rate\|≤20%、\|pitch\|≤12Hz | `intro-cards.json.moods`（neutral 0/0，happy +4/+5，puzzled −8/−2，encouraging −5/+2，emphatic +2/−3，teach −15/0） | **台词超时长只改文本**，声线参数动一次全员重合成且破坏音色一致性 |
| **时长预算**：speech_end ≤ 8.5s（收尾动作 ≥ 1.1s + 呼吸位）；成片恰好 10.0s | `self-introductions.md` §3.2 | tts 阶段打印 speech_end，超限回改文本 |
| **表情基线**：MOOD_FACE（lift/tilt/smile） | `intro_cards.py::MOOD_FACE` | 情绪是数据不是发挥，改表全员生效 |
| **词轴三用**：词级时间戳同时驱动 口型开合 + 逐词高亮 + 手势触发 | `render_card` | 动口型/卡拉OK节奏不需要新数据，换台词自动重对齐 |
| **描边禁令**：人物无描边（多邻国纯平涂）；场景道具描边只用 `pal["ink"]` 柔色 | `draw_character` / `prerender_bg` | 别给人物加 outline 回归"廉价感" |
| **贴图层级**：背景 → 人物层(2x) → 文字带 → 名牌 → 语言牌 → 气泡（尾在人物层内画，被气泡本体盖住尾根） | `render_card` 主循环 | 改层级前想清楚气泡尾的遮挡关系 |
| **uv 单环境**：全部 Python 经 `uv run`（src 布局包 `usine` + 控制台入口）；依赖精确锁版，Pillow 12.3.0 = 像素基线 | `pyproject.toml` + `uv.lock` + `run.ps1` | 裸 `python` 跑管线要么缺依赖要么错版本；升级 Pillow 必须先重验 framehash 基线 |

---

## 3. 参数地图（想改 X → 去哪改）

| 想调什么 | 改哪里 | 注意 |
|---|---|---|
| 台词 / 注音 / 中文对照 | [self-introductions.md](self-introductions.md) + `personas/intro-cards.json` `lines[].text`（**两处同步**） | 改完跑 tts 看 speech_end ≤ 8.5s |
| 情绪分段 / 手势触发（`at` 关键词 / `do` / `dur`） | `intro-cards.json` `lines[].mood`、`gestures[]` | 手势词必须真实存在于台词，否则回退到行首 |
| 收尾招牌动作 | `intro-cards.json` `close`（单码或按序码列；pose_for 全部码：wave/thumbs_up/point/nod/shrug/mini_jump/run_out/turn_freeze/snap/camera_snap/chest_pat/deadpan_nod/twirl/lean_in/pocket_sway/head_tilt_smile/thumbs_run/shoot_run/…） | 码列按时序衔接，`close_dur_for` 表在 `render_card`；跑出画族占满剩余时长 |
| 入场姿态 | `intro-cards.json` `entry_pose`（码列，窗口 [0.05, min(entry,1.2)]s） | 取代旧"活泼统一挥手"硬编码；与手势/收尾优先级 close > gesture > entry |
| 人设（名字/声线/色板/发型/配饰/identity/RTL） | `personas/personas.json` | 色板字段被 qa_char 对照，改色必跑 qa_all |
| **头身比例 / 五官位置** | `face_geo()` 比率表（见 plan.md §8.3 表） | 探针自动跟随；跑 qa_all + qa_motion |
| 发型绘制 | `draw_character` 前发/背发层两段（`style` 分支） | 侧发会盖耳朵：新发型想露耳要留出 `rx*0.94` 之外的空间 |
| 配饰绘制 | `draw_character` 躯干挂件段 + 头部配饰段 | 帽类 PIE 见 §5 坑④；宽度参考 `torso_hw=0.435×头宽` |
| 名牌 / 语言牌 / 气泡样式 | `badge_html` / `pill_html` / `bubble_html` | **禁 position:absolute / transform**（坑⑦）；尾色必须同 `UI_INK`；语言牌 = 国旗 emoji＋语种名（`pill_<locale>` 14 张按语种共享） |
| 场景背景 | `SCENES` 注册表（64 个原语，`@scene("名")`）+ `intro-cards.json` `scene[]` | 全部用 `pal` 色板 + 模块级 `SCENE` 中性色表，禁写字面 RGB；场景描边只许 `pal["ink"]` |
| 文字带（字幕条） | `band_html`（64px 起自适应缩到 30px） | BAND_Y=100, BAND_H=300，头像区 400–840 之间别放东西 |
| 文字层字体 | `FONT_CSS`（14 语种映射） | 新语种先确认 Windows 字体可用 |
| 超采样倍率 / 帧率 / 片长 | `SS`（现 2）/ `W,H,FPS,DUR` | SS 提到 3 渲染耗时 ×~2.2，先单卡试 |
| 口型/眨眼/呼吸节奏 | `openness_at` / blinkCycleSec（personas）/ `breath` | 眨眼相位由 `rnd(seed:blink:n)` 锁定，幂等 |

---

## 4. 验收体系（无视觉模型也能验收）

| 脚本 | 职责 | 通过标准 |
|---|---|---|
| `qa_grid.py [--persona id] <frame.png>` | 帧降采样 36×64 色块分类图（S肤/H发/T衣/B裤/I标识/#带/W白/G地）；色板从 personas.json 按人设读取 | 人工目检布局：头>躯干、眼位低、鞋在地面带 |
| `qa_char.py` | 单卡调色板探针（发/肤/颈影/衣/裤/鞋/巩膜/瞳/高光/眉/腮红/帽），几何**从 face_geo 派生**，眉形/眼形/视线与 MOOD_FACE/EYE_MOOD/gaze 同源（`mood=`/`t=` 参数）；新特征探针：织带/滑板贴纸/书袋挂饰/膝盖补丁/三色旗（不变量⑩） | 0 fail；起跳帧 `probe_crown=False`（头顶撞气泡属正常遮挡） |
| `qa_all.py` | 32 单元全量（28 卡 + 4 个 `<id>_f` 变体，变体共享人设探针）：时长=10.0±0.05s、aac、t=3.0 探针（mood 从时间线推导）、收尾帧按 9.4s 活跃码查躯干（跑出画族跳过） | `ALL 32 UNITS PASS` |
| `qa_motion.py` | 卡拉OK LTR 覆盖率递增 / RTL 高亮中位 x 左移、口型开合+收尾闭合、RTL 气泡镜像、眨眼跌落、进度条推进、名牌/语言牌弹出、项链吊坠摆动、镜片反光位移、瞳孔视线漂移、呆毛颤动（采样框全部从 face_geo/布局常量推导） | `MOTION QA PASS` |
| 幂等抽检 | **qa_motion 内置**：重渲一卡 → `ffmpeg -f hash -hash md5`（`-map 0:v`） | **视频流逐帧一致**（容器字节差来自 ffmpeg 元数据，属正常——曾误报"逐字节一致"，见 §5 坑⑫） |
| `qa_scene.py`（场景线） | 六组：产物规格 / **文本契约** / 选角与骨架 / 画面探针 / 音频契约 / 幂等 | `N PASS / 0 FAIL` |

**「文本契约」这组是踩过坑才加的**——三类问题都不影响渲染，ffmpeg 全部 `rc=0`，
画面探针也照样 PASS，全靠人眼/记性发现。它们的共同形状是「**承诺与文本不一致**」，
所以统一做成数据声明 + 验收对账（数据在 `scene-<id>.md §0`，管线零改动）：

| 检查 | 数据来源 | 抓的是什么 | 实例 |
|---|---|---|---|
| 句末标点 | 代码（Unicode 事实，非场景数据） | 句末不得是半角分号 `;`；疑问句须用本文字系统的问号（希腊文 `U+037E`） | el-GR 7 个疑问句用 ASCII 分号收尾，TTS 读成陈述句 |
| 语体差 | `§0.3` 表 `locale \| 语体 A \| 语体 B \| 区分标记` | A 线不得含标记、B 线必须含标记——「语体差即关系戏」只能在文本层验 | ko-KR 注记承诺「서연 敬语体」，成片里 B 全线해체 |
| 时长预算 | `§0` 的 `durationBudget: 40-55` | 超时即 FAIL，处方是回改文本（不变量②，绝不动基线） | he-IL 60.04s / hi-IN 56.97s / ar-SA 56.45s |

> 缺行 = **不检查**，不是「通过」——`§0.3` 没列的语种不会被静默认成合规。

> 回归测试：`uv run python scripts/verify_text_contract.py` 把**修复前**的原始数据喂进
> 同一套检查逻辑，要求三项全部判 FAIL、再喂修复后的数据要求全部 PASS。
> 这条测试真抓到过一个 bug：`QMARK_BY_SCRIPT` 里的希腊问号在编辑过程中被工具链
> 静默归一成 ASCII 分号，导致真跑验收时 7 个希腊问句全部误判。
> **教训：形近码位（`;` U+003B / `;` U+037E）一律用 `chr(0x…)` 写死，
> 不要在源码里直接敲字面字符，也不要靠肉眼看 diff。**

**探针纪律**：新加视觉特性 = 同时加对应探针；探针采样点必须从 `face_geo` 算，
不许手抄坐标（今天 3 个"假失败"全是手抄坐标撞上大眼/气泡/帽檐——见 §5）。

---

## 5. 踩坑实录（症状 → 根因 → 修法）

1. **卡拉OK/口型整行不动**：edge-tts 7.2.8 默认只发 `SentenceBoundary`。
   → `edge_tts.Communicate(..., boundary="WordBoundary")`，并在消费端识别伪词
   （`len(words)==1 and words[0]["w"]==text[:12]`）当心静默回退。
2. **时长凭空多 0.5–1.5s**：mp3 尾部静音。 → 行时长 = `min(探针时长, 末词end + 0.20s)`。
3. **多行卡成片不足 10s**（theo 9.469s / mateo 9.371s / seoyeon 8.637s / yuval 9.011s）：
   loudnorm（内部升采样 192k）**之后**接 `apad` 是非确定的 EOF 冲刷竞态——2026-10-03
   同命令 10 连跑 3 次丢补尾（9.469s）、7 次正常（10.0s）；amix 输出止于最长行的
   **原始 mp3 尾**（非裁尾时长），`atrim` 只裁不补；单行卡靠原始尾巴 ≥10s 侥幸通过。
   → `apad=whole_dur={DUR}` 前置到 loudnorm **之前**再 `atrim=0:10`（同日 10 连跑
   10/10 全 10.0s；loudnorm 门控响度不计静音，增益不变；对已 ≥10s 的流是 no-op）。
4. **帽子与帽檐之间露发缝**：`PIE(182,358)` 只画椭圆**上半**，帽冠下沿与帽檐之间有缝。
   → 帽冠 bbox 下探到与檐相接（knit `hy+0.17ry`、cap `hy−0.10ry`、sun `hy+0.02ry`）。
5. **胡子把嘴盖住**（nikos 的嘴从来没显示过）：胡子画在表情之后。
   → 绘制顺序 = 发 → 胡子 → 表情（嘴压在胡子上）。
6. **草帽檐压眉**：檐下沿 1111 > 眉顶 1104。 → 檐上提到 `hy−0.78ry..−0.32ry`，
   **准则：一切头饰不得压眉**（眉顶 = `face_geo.brow_y − 眉厚/2`）。
7. **Edge headless 里 position:absolute/transform 破坏父盒高度**：流式布局截图才是可靠的。
   → 全部文字层用流式；气泡尾巴由渲染端 PIL 补画；半透明投影经双色 matte 精确还原。
8. **DrawScaled 代理炸 `cannot unpack int`**：PIL 原生 `d.line` 接受扁平坐标序列，场景里大量
   `[x0,y0,x1,y1]` 写法。 → 代理里检测首元素类型再配对。
9. **探针假失败**：a) PIL 弧顶点在包围盒**上缘**而非中线（发带探针采到发色）；
   b) 起跳顶点头顶撞进气泡图层（气泡本来就在人物前面）；
   c) 大眼改宽后旧"脸颊"采样点落进巩膜。 → 探针点全部改为 face_geo 派生 + 遮挡感知。
10. **文字层截图底部截断**：Edge headless 的 `--window-size` 高度 ≠ 实际视口高度
    （本机实测差 94px），文字带底部被裁掉一截。
    → `edge_viewport_h()` 探针实测视口高，`edge_win_h = BAND_H + max(0, 300 − 视口高)` 动态补高
    （`intro_cards.py::cmd_assets`）——不写死 94，换机器自动重测。
11. **肩点落在躯干轮廓外 + 臂躯间露底缝**：几何拼接无解剖概念，肩关节浮在躯干外
    ~35px，臂与躯干之间 22px 露出背景；静止手位距躯干 100px（a1=14° 外张）。
    → `face_geo` 躯干加宽 `torso_hw=sh_hw=0.435×头宽`（旧 0.34×）+ 腿加粗 0.185H +
    臂加粗 0.155H；肩点内收 `sh = (cx + s·(sh_hw − arm_w·0.30), sh_y)` 落回躯干轮廓上；
    颈侧→肩峰加肩楔三角过渡填平缺口（`draw_character` 躯干段/手臂段）；
    静止角 14°→7°。改后帧内臂-躯干 0 露底缝（qa 扫 1360..1560 行无 BG 缝）。
12. **幂等抽检误报"逐字节一致"**：ffmpeg 容器（mp4 元数据/mtime）每次编码字节不同，
    对整文件做 `Get-FileHash` 双跑必然不一致。 → 对比**视频流** framehash：
    `ffmpeg -map 0:v -f hash -hash md5 -i <id>.mp4 -`；音频流同理可验（§4 已改口径）。
13. **语言牌国旗 emoji 不出旗**：Windows `Segoe UI Emoji` 无国旗字形（系统级一致），
    🇨🇳 渲染为 "CN" 双字母对；语言牌双通道（字母对＋语种文字）仍成立，国旗字形平台
    （macOS/移动端）自动出真旗。→ 保留 emoji 写法（规格正确、平台自适应）；
    **禁为"补旗"私画简化国旗**——沙（经文）/港（洋紫荆）/印（法轮）徽记不可几何简化，
    错旗比字母对更糟。

另：渲染里所有随机性（眨眼相位、场景微扰）必须 `rnd(f"{seed}:...")` 播种，否则幂等破坏。

> 坑坑⑩⑪⑫⑬ 记录于 2026-10-03 人物形象打磨（肩楔/肩点内收/Edge 视口补偿 + 幂等口径修正 + 国旗 emoji 平台回退）。
> 技术路线裁定（H3+Remotion 迁移案被否、Pillow 管线续役）见 [adr-character-tech.md](adr-character-tech.md)。

---

## 6. 调优手册（recipes）

### 6.1 改台词
1. 同时改 [self-introductions.md](self-introductions.md) 与 `intro-cards.json` 的 `text`；
2. `.\run.ps1 tts`（缓存自动失效重合成）→ 看 speech_end ≤ 8.5s，超了**删字**（对照各声线实测字/秒，见 self-introductions.md §1.5）；
3. `.\run.ps1 render -Only <id>` + qa。

### 6.2 调头身/五官
只改 `face_geo()` 比率表（单位=头高 H）。发型/配饰/探针全部按比例自动跟随。
改完必须跑 **qa_all + qa_motion**（口型采样框、眨眼框在 qa_motion 里按 face_geo 手写，
大改眼/嘴位置时要同步这两处采样框——见 qa_motion 头部注释）。

### 6.3 加发型/配饰
- 发型：`draw_character` 背发层（头后体积）+ 前发层（`style` 分支）各加分支；
  发色统一 `hair_c`/`hl_c`（双色高光），别写死颜色。
- 配饰：挂件放躯干段、头饰放头部配饰段；宽度以 `torso_hw`/`u()`（头高单位）表达；
  **帽类过坑④⑥**：檐不压眉、PIE 下探到檐。
- 验收：`qa_char.check` 加 spec-aware 探针（对照 `acc` 集合），qa_all 自动带上。

### 6.4 改名牌/气泡
改 `badge_html`/`pill_html`/`bubble_html`（流式布局！），跑 `.\run.ps1 assets` 重建贴图。
投影随意加——matte 抠像能还原任意半透明；尾色改了要同步 `render_card` 里的 `tail_col`。

### 6.5 加语种/加人物
1. `personas.json` 加档案（voiceId 从 plan.md 附录 A 实测快照里选，新语种先 `edge_tts.list_voices()` 核验）；
2. `intro-cards.json` 加卡（cast A=文字气泡 / B=地图气泡；RTL 记得 `rtl:true`）；
3. `FONT_CSS` 补字体；qa_char 若有新配饰类型加探针；
4. self-introductions.md 补内容种子；`.\run.ps1 all`。

### 6.6 性能
单卡 ~36s（SS=2 不显著拖慢：开销大头是 Pillow 画形状与 BOX 降采样很快）。
28 卡 7 workers ≈ 3 分钟。要快：`--workers` 拉满核数；要更顺滑：SS 提 3（先单卡看耗时）。
音频缓存命中时 tts 秒回；`render` 无法缓存（幂等但每次全渲）。

### 6.7 场景线（教学场景 A/B 对话）

第二条渲染线：**场景是数据不是代码**——教学 token、RTL 语种、每语种舞台装置全部由剧本自带，
管线零改动。

```
scenes/scene-<id>.md ──parse_scene.py──▶ scene_<id>.json ──scene_video.py──▶ build/scene/scene-<id>_<locale>.mp4
```

```powershell
python  parse_scene.py --scene colors            # 剧本 → 场景 JSON（只抽取不改写）
python  parse_scene.py --list                    # 列出仓库内已有场景 id
.\run.ps1 scene                                   # parse → tts → assets → render
.\run.ps1 scene -Only zh-CN,ja-JP -Workers 6      # 只渲指定语种
.\run.ps1 scene-list                              # 场景清单（token 序 / RTL / 装置 / 时长）
.\run.ps1 qa-scene                                # qa_scene.py 六组验收
```

- **新场景零代码接入**：新建 `scenes/scene-<id>.md` 照抄 §0 机读规格体例即可，解析器与渲染线不动。
  §0 = `sceneId` / `title` / `rtlLocales` / `durationBudget`（可选，`40-55`）
  + §0.1 教学 token 表 + §0.2 装置规格表
  （`locale | scenes | style | shape | cellW | cellH | well | label`；locale 缺行 = 纯对话）
  + §0.3 语种文本规范表（可选，`locale | 语体 A | 语体 B | 区分标记 | 说明`；locale 缺行 = 不做语体检查）。
- **token chip 两型**：`#hex` = 色片（井内实心填充）；`"文本"` = 字牌（Edge 渲 token 词文字层贴入井）。
  §0.2 `well` 缺省时由场景中性色推导——**浅色 chip 落在同色底上会看不见**，故显式给色是常用手段。
- **人物 rig 零复制**：`scene_video.py` 从 `intro_cards` import `draw_character` / `face_geo` /
  `pose_for` / `gaze` / `phys` / `SCENES` / 文字层抠像 / 情绪增量表，只写场景层（选角、双人站位、
  token 装置、气泡与 RTL 镜像）。加人物或改脸型 → 只动 `intro_cards.py`，两条线同时受益。
- **选角走 `intro-cards.json` 的 `cast` 事实源**（A=活泼先问 / B=沉稳后答），并与剧本 §4 表格
  姓名交叉核对，不一致即报错——绝不静默换角。
- **词级时间戳一轴三用**（不变量④）：口型开合 / 卡拉OK 逐词高亮 / 手势触发共用一条时间轴；
  token 装置的「当前 token 弹起」再叠第四用，与色名高亮同轴。
- **色值分层**：token 色片只用于装置与卡拉OK高亮，不进人物色板；装置描边只用 `pal["ink"]`
  （不变量⑤）；浅色 chip 在深色文字带上落 `THEME["gold"]`。
- **RTL**：`rtlLocales` 内语种站位左右对调、文字带 `dir=rtl`、进度条右起、气泡尾镜像；
  名牌随人出画退场。
- **资产命名**：`scene-<id>_<locale>` 前缀（`band_` / `bub_` / `pill_` / `tok_`（字牌）/ 时间轴 / 音频 / mp4），
  多场景并存不串扰；逐行语音缓存仍按 `sha256(voice|rate|pitch|text)`，跨场景天然复用；
  `badge_<id>`（人物名牌）不含场景，跨场景共享。
- **性能**：单语种 ~45–60s×30fps ≈ 1400–1800 帧、双立绘 2x 超采样 ≈ 4–5 分钟；
  14 语种 6 workers ≈ 12 分钟（文字层 Edge 截图另需 ~10 分钟）。

---

## 7. 后续调优 backlog（按性价比排序）

1. **眨眼/呼吸随情绪**：happy 眨眼快、steady 呼吸深——mood 进 blink/breath 参数。
2. **手势过渡**：pose_for 目前硬切，加 0.15s ease 混合（arm 角度插值）会更"贵"。
3. **口型三态**（开/闭/圆唇）：现在只有开度一维，圆唇音（o/u）加圆口型 PIE。
4. **发丝层次**：给长发加第二层暗色内影（现在只有单高光弧）。
5. **场景与身份联动**：SCENES 原语按 identity 自动调色已有，可再加"每卡 1 个身份道具呼应台词"。
6. **全量 framehash 幂等**：现在抽检 2 卡，可写脚本 28 卡全量（渲两次逐帧 hash，约 6 分钟）。
7. **qa 探针并入 CI**：`run.ps1 qa` 已是一键，可挂 pre-push。
8. **管线二（Remotion + 生成式人物）**：裁定记录见 [adr-character-tech.md](adr-character-tech.md)——
   本管线的 face_geo/姿态库/词轴三用/personas.json 可直接移植。

---

## 8. 文件地图

```
une_usine_avec_des_machines_rugissantes/
├─ CLAUDE.md / README.md             # 项目规则（简）· 项目说明（新人入口）——工具惯例留在仓库根
├─ docs/                             # 全部工程文档
│  ├─ render-handbook.md             # ★ 本手册
│  ├─ requirement.md / plan.md       # 需求 · 总规划（§8.2 音频契约 / §8.3 绘制规格 / §8.4-8.6 三管线）
│  ├─ adr-character-tech.md          # 人物生成技术选型裁定（H3+Remotion 迁移案 = 备选，Pillow 续役）
│  ├─ self-introductions.md          # 28+4 卡内容种子（台词/注音/对照/分镜/验收清单）
│  └─ benchmark-duolingo.md          # 对标台账（多邻国三文档逐条裁定）
├─ scenes/                           # ★ 教学场景剧本（scene-<id>.md，机读事实源；新场景在这里新建）
│  └─ scene-colors.md                # colors 场景：§0 机读规格 + 共享骨架 + 14 语种原生剧本 + 词表
├─ scene_colors.json                 # 场景线数据（parse_scene.py 从 scenes/scene-<id>.md 机械抽取；渲染与教学文档共用）
├─ run.ps1                           # ★ 统一入口（-Scene <id> 选教学场景）
├─ pyproject.toml / uv.lock / .venv # 包与依赖（usine-cards / usine-parse / usine-scene / usine-lesson / usine-dump-lesson）
├─ src/usine/                        # ★ 全部代码（数据在仓库根，产物在 build/；`from usine import ROOT` 定位根，不依赖 cwd）
│  ├─ intro_cards.py                 # ★ 管线一（tts/assets/render；face_geo/MOOD_FACE/SCENES/pose_for/POSE_CODES）
│  ├─ qa_grid.py / qa_char.py / qa_all.py / qa_motion.py   # 验收四件套（§4）
│  ├─ parse_scene.py                 # 场景线：scenes/scene-<id>.md → scene_<id>.json（通用解析器，只抽取不改写）
│  ├─ scene_video.py                 # 场景线（M2，场景无关：tts/assets/render；选角/双人站位/token 装置/RTL 镜像）
│  ├─ qa_scene.py                    # 场景线验收（§4.5，--scene <id>）
│  ├─ dump_lesson_source.py          # scene_<id>.json → lesson_analysis/_source/<locale>.md（只排版不改写）
│  └─ build_lesson.py                # 合并成 build/lesson/index.html（语系排序 9 组 + 逐句解析；视频走顶部 sticky 固定栏 + 语种 tab）
├─ lesson_analysis/                  # 教学文档侧的人工解析（与视频管线解耦）
│  ├─ _source/<locale>.md            # dump_lesson_source.py 导出的可读源文本（原文/注音/翻译/舞台/创作注记）
│  └─ <locale>.json × 14             # 逐句 {grammar, morph, culture} + 家族/书写/舞台三段（人工委派产出）
├─ personas/
│  ├─ personas.json                  # ★ 28 人档案（人设唯一事实源）
│  └─ intro-cards.json               # ★ 28 卡种子（cast/lines/moods/gestures/entry_pose/scene/close；RTL 卡带 variants[] 女性观众版）
├─ scripts/                          # 发布侧（抖音）＋ 验收侧回归测试（verify_text_contract.py）
└─ build/                            # 产物（.gitignore）
   ├─ intro/                         # 管线一产物
   │  ├─ <id>.mp4                     # 32 × 10s（28 卡 + 4 个 <id>_f 女性观众版）
   │  ├─ audio/                       # <key>.mp3+<key>.json 词表缓存 · <id>.m4a · <id>.timeline.json（变体独立键）
   │  └─ text/                        # 文字层 PNG（band_<unit>_<i>_{base,hl}/badge_<id>/pill_<locale>/bubble，双 matte 抠像）
   ├─ scene/                         # 管线二产物（多场景共存，文件名带 scene-<id> 前缀）
   │  ├─ scene-<id>_<locale>.mp4      # 每场景每语种一支（40–60s）
   │  ├─ audio/                       # scene-<id>_<locale>.m4a / .timeline.json（cast/token 点亮时刻/逐行词轴）+ 逐行 mp3 缓存
   │  └─ text/                        # band_/bub_/pill_/tok_ 均带 scene-<id>_<locale> 前缀 · badge_<id>（人物名牌，跨场景共享）
   └─ lesson/index.html               # 教学文档（build_lesson.py 产物；视频按 ../scene/ 相对路径引用）
```
