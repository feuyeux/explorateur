# 亮相卡管线 · 工程与调优手册

> 本手册沉淀 28 × 10s 亮相卡（`build/intro/<id>.mp4`）从 0 到 1 的全部工程决策：
> 架构不变量、参数地图、验收体系、踩坑实录与调优手册。规划与 schema 见
> [plan.md](plan.md)（§8.2 音频契约、§8.3 人物绘制规格），内容种子见
> [self-introductions.md](self-introductions.md)。**改任何东西前先读 §3 参数地图。**
>
> 人物生成技术路线的裁定记录（含被否的 H3+Remotion 迁移方案）见
> [adr-character-tech.md](adr-character-tech.md)：**现役 = 本手册的 Pillow 管线**。

---

## 0. 快速上手

统一入口 [`run.ps1`](run.ps1)（封装两解释器分工，见 §1）：

```powershell
.\run.ps1 tts              # 逐行合成 + 词级时间戳（系统 Python · edge-tts）
.\run.ps1 assets           # 文字层 PNG（Edge headless，~122 张）
.\run.ps1 render           # 帧渲染 + ffmpeg（捆绑 Python · Pillow），--Workers 7
.\run.ps1 render -Only xiaoman,layla
.\run.ps1 qa               # 28 卡全量验收（qa_all.py）
.\run.ps1 qa-motion        # 动态验收（卡拉OK/口型/眨眼/气泡镜像）
.\run.ps1 all              # tts → assets → render → qa → qa-motion 全流程（~5 分钟）
```

直连命令（run.ps1 的等价形式）：

```powershell
python  intro_cards.py tts     [--only id1,id2]          # 系统 Python：edge-tts 7.2.8
python  intro_cards.py assets  [--only id1,id2]          # 任意 Python：调 Edge headless
C:\Users\feuye\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe `
        intro_cards.py render [--only id1,id2] [--workers 7]   # 捆绑 Python：Pillow+numpy
```

产物：`build/intro/<id>.mp4`（1080×1920，30fps，**恰好 10.0s**，h264 crf18 + aac 192k）。
改完任何东西的验收基线：**qa_all 28/28 PASS + qa_motion PASS**。

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
| **两解释器分工**：tts=系统 Python（有 edge-tts）；assets/render=捆绑 DSH Python（有 Pillow/numpy） | `run.ps1` | 用错解释器立刻 ImportError |

---

## 3. 参数地图（想改 X → 去哪改）

| 想调什么 | 改哪里 | 注意 |
|---|---|---|
| 台词 / 注音 / 中文对照 | [self-introductions.md](self-introductions.md) + `personas/intro-cards.json` `lines[].text`（**两处同步**） | 改完跑 tts 看 speech_end ≤ 8.5s |
| 情绪分段 / 手势触发（`at` 关键词 / `do` / `dur`） | `intro-cards.json` `lines[].mood`、`gestures[]` | 手势词必须真实存在于台词，否则回退到行首 |
| 收尾招牌动作 | `intro-cards.json` `close`（pose_for 全部码：wave/thumbs_up/point/nod/shrug/mini_jump/run_out/turn_freeze/snap/camera_snap/chest_pat/…） | `close_dur` 表在 `render_card` |
| 人设（名字/声线/色板/发型/配饰/identity/RTL） | `personas/personas.json` | 色板字段被 qa_char 对照，改色必跑 qa_all |
| **头身比例 / 五官位置** | `face_geo()` 比率表（见 plan.md §8.3 表） | 探针自动跟随；跑 qa_all + qa_motion |
| 发型绘制 | `draw_character` 前发/背发层两段（`style` 分支） | 侧发会盖耳朵：新发型想露耳要留出 `rx*0.94` 之外的空间 |
| 配饰绘制 | `draw_character` 躯干挂件段 + 头部配饰段 | 帽类 PIE 见 §5 坑④；宽度参考 `torso_hw=0.435×头宽` |
| 名牌 / 语言牌 / 气泡样式 | `badge_html` / `pill_html` / `bubble_html` | **禁 position:absolute / transform**（坑⑦）；尾色必须同 `UI_INK` |
| 场景背景 | `SCENES` 注册表（57 个原语，`@scene("名")`）+ `intro-cards.json` `scene[]` | 全部用 `pal` 色板，勿写死 RGB |
| 文字带（字幕条） | `band_html`（64px 起自适应缩到 30px） | BAND_Y=100, BAND_H=300，头像区 400–840 之间别放东西 |
| 文字层字体 | `FONT_CSS`（14 语种映射） | 新语种先确认 Windows 字体可用 |
| 超采样倍率 / 帧率 / 片长 | `SS`（现 2）/ `W,H,FPS,DUR` | SS 提到 3 渲染耗时 ×~2.2，先单卡试 |
| 口型/眨眼/呼吸节奏 | `openness_at` / blinkCycleSec（personas）/ `breath` | 眨眼相位由 `rnd(seed:blink:n)` 锁定，幂等 |

---

## 4. 验收体系（无视觉模型也能验收）

| 脚本 | 职责 | 通过标准 |
|---|---|---|
| `qa_grid.py <frame.png>` | 帧降采样 36×64 色块分类图（S肤/H发/T衣/B裤/I标识/#带/W白/G地） | 人工目检布局：头>躯干、眼位低、鞋在地面带 |
| `qa_char.py` | 单卡调色板探针（发/肤/衣/裤/鞋/巩膜/瞳/高光/眉/腮红/帽），几何**从 face_geo 派生**；支持 hop（起跳 squash）与 dx（走位） | 0 fail；起跳帧 `probe_crown=False`（头顶撞气泡属正常遮挡） |
| `qa_all.py` | 28 卡全量：时长=10.0±0.05s、aac、t=3.0 探针、收尾帧躯干在位 | `ALL 28 CARDS PASS` |
| `qa_motion.py` | 卡拉OK LTR 覆盖率递增 / RTL 高亮中位 x 左移、口型说话中开合+收尾闭合、RTL 气泡镜像（layla 右 vs jiangyuan 左）、眨眼跌落 | `MOTION QA PASS` |
| 幂等抽检 | 渲两次 → `ffmpeg -f hash -hash md5`（`-map 0:v`） | **视频流逐帧一致**（容器字节差来自 ffmpeg 元数据，属正常——曾误报"逐字节一致"，见 §5 坑⑫） |

**探针纪律**：新加视觉特性 = 同时加对应探针；探针采样点必须从 `face_geo` 算，
不许手抄坐标（今天 3 个"假失败"全是手抄坐标撞上大眼/气泡/帽檐——见 §5）。

---

## 5. 踩坑实录（症状 → 根因 → 修法）

1. **卡拉OK/口型整行不动**：edge-tts 7.2.8 默认只发 `SentenceBoundary`。
   → `edge_tts.Communicate(..., boundary="WordBoundary")`，并在消费端识别伪词
   （`len(words)==1 and words[0]["w"]==text[:12]`）当心静默回退。
2. **时长凭空多 0.5–1.5s**：mp3 尾部静音。 → 行时长 = `min(探针时长, 末词end + 0.20s)`。
3. **theo 成片 9.469s**：`apad=whole_dur` 在 loudnorm（内部升采样 192k）后不生效；
   amix 输出止于最长行，`atrim` 只裁不补。 → `apad=pad_dur` 补够再 `atrim=0:10`。
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

另：渲染里所有随机性（眨眼相位、场景微扰）必须 `rnd(f"{seed}:...")` 播种，否则幂等破坏。

> 坑⑩⑪⑫ 记录于 2026-10-03 人物形象打磨（肩楔/肩点内收/Edge 视口补偿 + 幂等口径修正）。
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
├─ CLAUDE.md / README.md             # 项目规则（简）· 项目说明（新人入口）
├─ requirement.md / plan.md          # 需求 · 总规划（§8.2 音频契约 / §8.3 绘制规格 / §8.4-8.6 三管线）
├─ adr-character-tech.md             # 人物生成技术选型裁定（H3+Remotion 迁移案 = 备选，Pillow 续役）
├─ self-introductions.md             # 28 卡内容种子（台词/注音/对照/分镜/验收清单）
├─ render-handbook.md                # ★ 本手册
├─ run.ps1                           # ★ 统一入口（两解释器分工封装）
├─ intro_cards.py                    # ★ 管线（tts/assets/render；face_geo/MOOD_FACE/SCENES/pose_for）
├─ qa_grid.py / qa_char.py / qa_all.py / qa_motion.py   # 验收四件套（§4）
├─ personas/
│  ├─ personas.json                  # ★ 28 人档案（人设唯一事实源）
│  └─ intro-cards.json               # ★ 28 卡种子（moods 增量表/cast/lines/gestures/scene/close）
└─ build/intro/                      # 产物（.gitignore）
   ├─ <id>.mp4                       # 28 × 10s
   ├─ audio/                         # <key>.mp3+<key>.json 词表缓存 · <id>.m4a · <id>.timeline.json
   └─ text/                          # 文字层 PNG（band/badge/pill/bubble，双 matte 抠像）
```
