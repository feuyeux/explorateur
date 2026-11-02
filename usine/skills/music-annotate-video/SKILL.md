---
name: music-annotate-video
description: >
  Produce classical-music appreciation explainers that need note/chord/form-level
  visual annotation on top of a REAL recording: align score/MIDI ground truth to
  the recording (chord-template classification, NOT DTW), derive note-level
  timelines from f0 tracking (hand-rolled harmonic-sum scoring, NOT
  librosa.pyin), render teaching frames (chord timeline / melody line /
  instrument-range chart / waveform with measured event marks / bio timeline),
  assemble frame-exactly with narration + music excerpts (ducking while the
  narrator speaks, full level while listening), append a measured
  production-notes credit card, and enrich the frames with license-cleared
  archival images (composer portraits, manuscripts, instruments, period scenes)
  found with Firecrawl — each with its source page, license and attribution
  recorded. Multi-movement works are sized at ~15 minutes —
  listening time is the product, narration is the seasoning (see 时长定标).
  Use when the user asks for a "teach me this piece/symphony" video, a listening
  guide, or an explainer whose visuals must follow specific chords, notes, or
  form sections. Not for word-highlight karaoke of language lessons (use
  karaoke-video), not for live-action subtitle overlays (use
  multilingual-video-poetry), not for generated-from-scratch video content (use
  video-generation), and not for BGM bed production or a generic
  music-plus-pictures background video that needs no score/pitch/chord
  annotation (use bgm-bed).
---

# Music Annotate Video

古典音乐（或需要乐谱/音高/和弦级标注的真实录音）欣赏科普视频的产线：**录音是
内容本体**，画面是程序化渲染的教学标注，旁白与音乐摘录混音。与 `karaoke-video`
的结构性差异：token 不是「词」而是「音符/和弦」，时间轴不是 TTS 边界，而是
**从乐谱真值或录音实测对齐出来的**。

## 现状与事实源（开工前先认）

本产线是「纪律 + 原语 + 模板」已入库、**端到端 CLI 尚未归流**：

| 能力 | 事实源 | 状态 |
|---|---|---|
| FFT / WAV / 频段分布 | `@feuille/bgm`：`rfftMag`（`packages/bgm/src/gen_bgm.ts:185`）、`readWav`（`:209`）、`bandShare`（`:655`） | 可直接调用 |
| 30fps 网格 / headless 截图 / 分段编码 | `@feuille/karaoke`：`d30`（`packages/karaoke/src/build_video.ts:52`）、`renderChrome`（`:73`）、分段编码（`:157-180`） | 可直接调用 |
| 状态帧 / 装配 / 账本模板 | `assets/template/`（本 skill 内，见 Resources） | 可复制后改 |
| 含墨扫描 | `assets/template/ink-scan.mjs` | 已实测（反向自测 + 真实成片） |
| 事实/许可账本校验 | `assets/template/validate-facts.mjs` | 已实测（反向自测） |
| 史料图检索 | `firecrawl search`（images 源）+ `firecrawl scrape`（外部 CLI） | 可用；需 `FIRECRAWL_API_KEY`，搜索计 credits |
| 完整历史实现 | `assets/example/`（《自新世界》Python 快照） | **只读参考，不要运行** |
| `feuille music probe\|align\|build\|scan-ink` | —— | **不存在**；不要引用、不要假装跑过 |

**不要引用 `usine/examples/dvorak-new-world/` 作为可复用脚手架**：它在本机存在，
但落在工作区 `.gitignore` 的 `examples/` 规则下，永不入库，新克隆没有。完整
样例已快照到 `assets/example/`（只读），现行写法以本文件与模板为准。

**已知缺口（别假装已有）**：`feuille music` 叶子尚未归流；`inkCoverage` 还没
进 `@feuille/core`（先用 `assets/template/ink-scan.mjs`）；`gen_tts` 仍靠调用方
剥标点、未在源头收口；`feuille karaoke build` 的音频仍是固定增益 `amix`，
`audio.tracks[]` 的 envelope 要自建 builder 或等归流。

## 时长定标（多乐章作品）

**四乐章交响曲 ≈ 15 分钟（900s）才够完整展开**——2026-11-01 实船两轮定标：
6 分钟版被评「刚要品尝菜就撤了」，9 分钟版仍偏紧；赏析类产品的时间主体
必须是**连续聆听**，不是旁白。预算表（可按乐章性格微调 ±10%）：

| 段落 | 时长 | 要点 |
|---|---|---|
| 片头卡 | 4s | |
| 生平 | 60–75s | 3 段顺延旁白 + 时间轴 states |
| 聆听地图 | 30s | 四乐章性格卡 + 「每到一个乐章我会提醒你听什么」 |
| 第一乐章 | ≈190s | 95–120s 连续录音 + 3 段旁白（含曲式导览）|
| 第二乐章（慢板） | ≈200s | 慢板给最长聆听；主题 120s 音符高亮 + 中段/回归 |
| 第三乐章 | ≈160s | 谐谑曲外壳 50s + 中段 50s（延续场景小 preroll）|
| 第四乐章 | ≈190s | 90s 连续 + 循环再现 + 结尾调性（实测）|
| 图谱 + 结语 | ≈60s | 乐器岗位 + 收束散文 |
| 制作信息页 | **8s 固定** | 二段式回填只改内容、不改帧数 |

**聆听优先三原则**（v1→v2 的核心教训）：
1. **旁白是插话，不是主体**——音乐在旁白下压 −12dB 继续走，绝不因
   「旁白讲完了」而停；每乐章纯聆听 ≥ 旁白总长。
2. **乐章间留 0.8s 呼吸**；同乐章的续段（如谐谑曲外壳→中段）用小 preroll
   （0.3s）减小停顿。
3. **画面在聆听段必须持续推进**：波形 5s/态、旋律 2.5s/态（播放头 + 时间码 +
   已播罩亮 + 实测事件线）；「同一帧停 30s」= 信息断供。

## 摘录选择原则（决定内容是否诚实）

900s 讲一部约 40 分钟的交响曲，必然只取一部分。**摘录不是「挑最好听的」，
而是「用最短时间保住曲式骨架」**：

1. **每乐章至少一段**，且优先选能说明曲式功能的段落：呈示部的主题陈述、
   发展部的变形、再现部的回归。只挑高潮会让观众以为全曲都在高潮。
2. **A–B–A 结构必须带一点 B**。若因时长只能给主题，画面与旁白都要明说
   「这里只取主题，完整乐章有 …」。
3. **片内明示「这是选段」**：第一次进入摘录时在角标写「选段 · 第 N 乐章」；
   制作信息页逐条列出摘录起止时间（`facts.json` 的 `excerpt_count` 与清单）。
4. **摘录起止必须来自探针日志**（RMS 包络 / 高频峰簇 / 和弦对拍），不许取
   整分钟；边界留 0.2–0.5s 余量，避免切在混响中间。
5. **选段比例写进交付说明**：选段总时长 / 全曲时长、省略了哪些部分、为什么。
   这是观众判断「我听到的是不是全貌」的唯一依据。

## 视觉资料研究（Firecrawl）

图表是骨架，史料图是血肉：作曲家肖像、手稿/初版扉页、乐器实物、首演城市与
音乐厅老照片。每部作品最多 3–5 张，每张服务一个旁白节拍；**没有合适素材就
空着用图表补**，不许拿未授权图或 AI「历史照」凑数。

```bash
# 最小命令；images 源 / 条数 / JSON 等完整旗标见 references/visual-research.md
firecrawl search "<composer> portrait public domain Wikimedia Commons" \
  -o .firecrawl/img-portrait.json
# 抓出处页/许可页（imageUrl 只是直链或缩略图，不是许可证据）
firecrawl scrape "<File: 页 URL>" -o .firecrawl/license.md
```

三道硬门槛，缺一不可：

1. **身份**：以出处页（Wikimedia `File:` / IMSLP / LOC / 博物馆 open access）
   的作者、年代、对象名为准，并与作品目录/传记年表交叉核对。搜索标题不算证据。
2. **许可**：PD-old / PD-US / CC0 首选；CC BY / CC BY-SA 可用但必须保留
   attribution 与许可链接；`unknown`、聚合站转载、现代演出照、版权谱例
   一律不用；AI 生成图**不许当史料**（要用必须标「示意图」）。
3. **尺寸**：`full-bleed`/`background` 长边 ≥1600px，`inset` ≥900px
   （实测反例：搜到 296×393 的肖像，铺满必糊）。同时人眼查 watermark、
   黑边、AI 放大纹理与裁切。

下载到 `assets/images/`、算 sha256、量宽高，然后写两处账：`sources.json` 的
`kind: "image"`（出处页 + 直链 + 许可 + attribution + 尺寸）与 `facts.json`
的 `visuals[]`（用途 → `source_id` → 图注）。`validate-facts.mjs` 会机检
长边门槛、图片类型与 attribution。完整查询模板、下载/校验命令与失败模式见
[references/visual-research.md](references/visual-research.md)。

## 赏析知识清单（每部作品过一遍）

| # | 必讲 | 事实口径 |
|---|---|---|
| 1 | 作曲家生平 3–4 个锚点（生卒/赴任/首演） | 公认传记史料；日期入画面卡 |
| 2 | **每乐章的曲式**（奏鸣曲式/三段式/谐谑曲…） | 结构为通说；用比喻讲规矩（如「盖楼法」），不堆术语 |
| 3 | **调性旅程**（出发调→最远处→收束调） | 收束调性由 chroma 实测判定（大三度 vs 小三度音级），不凭记忆 |
| 4 | 主题再现/循环结构 | 「四乐章是一座建筑的四根柱子」类比喻 |
| 5 | 派生作品史实（如《回家》填词歌） | **派生方向必须讲对**（曲调在前、填词在后）|
| 6 | 有争议的引用/灵感说 | 写**当事人的澄清**，不写定论 |
| 7 | 乐器岗位图谱 | 音域带为参考值须标注；独奏实际落点用录音实测 |

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **公有领域录音**（Wikimedia Commons / Musopen 等），逐件登记 URL + 许可 + attribution（`assets/template/sources.json`） | 版权风险；无法剪辑混音；CC 录音无法署名 |
| 2 | 乐谱真值（CC0 MIDI / 谱例 SVG）——没有真值的段落用「录音实测」口径并如实标注 | 高亮与声音对不上还不自知 |
| 3 | 每个教学段落的时间码**实测**（RMS 包络 / 高频峰簇 / 和弦对拍），日志落盘 | 摘录切错位置，旁白讲的东西不在音频里 |
| 4 | **摘录选择方案**（每乐章取哪段、为什么、省略了什么） | 只挑高潮 / 只挑主题，内容失真 |
| 5 | 旁白语种与画幅（16:9 / 9:16） | 无法定 TTS 与状态帧几何 |
| 6 | 讲述者口径（人声不出镜 · 散文讲者 / 听辨式教学） | 做成语言课或评书 |
| 7 | 交付规格：时长目标、响度、封面、发布平台 | 「做完」没有边界，半成品静默收工 |

史料图是可选项；一旦进入画面，就必须按「视觉资料研究」入 `sources.json` +
`facts.visuals`，没有例外。

## Requirements (fresh machine)

- **Node ≥24 + pnpm@11**，在工作区根跑：`pnpm verify`（类型 + 全量测试）必须绿。
  不写死 `node_modules` 路径，不全局装包。
- **ffmpeg / ffprobe**：经 `@feuille/core` 的 `platform.ffmpeg()` / `platform.ffprobe()`
  解析；解析不到就显式失败，不用系统默认兜底（AGENTS.md 跨平台硬约定 1）。
- **Chromium 系浏览器**（Edge 优先，Chrome 次选）：经 `platform.browserPath()`
  解析，或 `$CHROME_BIN` 显式覆盖。
- **TTS**：`feuille karaoke tts`（edge-tts 协议在 `@feuille/core`），需要网络。
- **Firecrawl CLI**（`firecrawl`，需 `FIRECRAWL_API_KEY`）：史料图检索与出处页
  抓取。先跑 `firecrawl status` 看余额；搜索计 credits，同一查询不要反复跑。
- **分析原语**：`@feuille/bgm` 的 `rfftMag` / `readWav` / `bandShare`。本产线
  **默认不引入 Python / uv / librosa / mido**。若确有历史脚本必须参考，走
  `assets/example/`（只读）；要执行 Python 属于明写例外：独立 uv 环境 +
  `OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2` + 单进程前台 + 不用 pyin / DTW。
- **两个模板脚本零依赖**：`node assets/template/ink-scan.mjs` 与
  `node assets/template/validate-facts.mjs` 只用 Node 内建模块。

## Workflow

0. **视觉资料研究（可选，先于画面设计）**：按「视觉资料研究」节找 3–5 张史料图，
   验身份/许可/尺寸，落 `sources.json` + `facts.visuals`。没有合适图就空着，
   不要为了「有图」降低标准。
1. **探针先行（零额度）**：对录音跑 RMS 包络（找引子/爆发/主题进入）、
   `bandShare` 高频段占比（找三角铁/钹段）、和弦模板分类（对 MIDI 段）。
   **所有摘录时间码必须有探针日志背书**，日志写 `<project>/notes/probe/*.log`。
2. **对齐**（任何一条判据不满足即 fail-closed，不许当「差不多」读）：
   - 有 MIDI 真值 → 和弦模板逐帧分类（模糊 Jaccard argmax）→ 众数平滑 →
     切段 → 按乐谱块顺序对拍 → 逐和弦 chroma 交叉验证。重复音级集的和弦块
     必须先去重组，否则 argmax 恒取第一个模板（traps §1）。
   - 无真值的独奏段 → 手写泛音和声评分 f0
     （`score(τ)=mean(r(τ),…,r(4τ))/r(0)`）→ 半音域中值平滑 → 滞回量化 → 聚段。
     全程用 `rfftMag`，分块控内存；**不用** `librosa.pyin` / 子序列 DTW。
   - 判据双条：结构块落带内 + 起点后 0.05–0.6s 最强音级交集 ≥ 2/3。
3. **视觉形态**：和弦时间轴 / 旋律线 / 乐器音域图 / 波形 + 实测事件线 /
   生平时间轴——从 `assets/template/status-frame.html` 复制骨架。纪律已写进
   模板注释：DATA 在消费者之前、裸 scene 名、caption 包块级 div、播放头只有
   JS overlay 一份、时间码 `text-anchor="end"`、波形用统一 `vmaxRef`。
   事实口径：画面里每个数字/引语必须有 `facts.json` 出处；有争议的（如灵歌
   引用）写当事人的澄清，不写定论。
4. **截图**：完整旗标清单与命令见
   [references/headless-render.md](references/headless-render.md)，照抄、不要增删。
   三条底线：用新版 headless 模式（不抢已开着的桌面浏览器）；**不要带
   user-data-dir**（macOS + Edge 实测图能出但进程永不退出，
   `usine/AGENTS.md:104`、`packages/karaoke/src/build_video.ts:73-80`）；
   截图后立刻跑含墨哨兵。`file://` URL 必须是绝对路径。
5. **旁白**：`feuille karaoke tts` 生成。**TTS 文本剥除全部标点**（标点→空格），
   display token 才留标点——不然词边界缺失、尾部 token 拿到 `null`、构建崩在
   `toFixed`（`packages/karaoke/src/gen_tts.ts`）。多句按实测 mp3 时长**顺延**
   （at 累加 + 0.9s 间隔），不许同刻齐发。
6. **装配**（帧精确，纪律同 `karaoke-video/references/av-sync.md`）：
   - 每个状态段用精确帧数单独编码再 `concat -c copy`（`build_video.ts:157-180`）；
   - 所有场景总长 `d30()` 吸附 30fps 网格，音频段 `-t` 裁到场景总长；
   - **音乐轨 `adelay` 顺延 preroll**（否则高亮整体滞后 0.8s——traps §8）；
   - **音频轨契约不是固定增益 amix**：用 `project.json` 的 `audio.tracks[]`
     （offset + gain envelope）或 `sidechaincompress`，表达「摘录绝对偏移 +
     旁白期 ducking + 聆听段全电平」。`feuille karaoke build` 的固定增益
     `amix`（`build_video.ts:184-205`）表达不了，自己造 builder 时别降级。
   - 状态段与高亮是**同一段 `[t[i−1], t[i])` 显示 state i−1**——off-by-one
     会把高亮整体错一个块（traps §7）；
   - 封装 `apad + -t v_dur` 裁齐双流；终混 loudnorm 必须在流长锁死之后。
7. **逐场景音画对账**：每场景「视频段总长 vs `d30(pre+body+done+tail)`」
   差值必须为 **0 帧**（traps §14）——只看全片总长会漏掉互相抵消的错位。
8. **验收**（见下节，程序 + 人眼，缺一不可）。
9. **制作信息页二段式**：卡长在第一次装配前定死（8s）；先出占位卡拼进成片，
   成片完成后回填实测数字重渲、重编该段、`concat -c copy` 重拼接、重封装。
   所有数字实测，不许手抄（traps §11）。

## 交付规格（「完成」的边界）

| 项 | 规格 | 事实源 |
|---|---|---|
| 画幅 / 帧率 | 1920×1080 或 1080×1920；30fps CFR | `build_video.ts:29`、`d30:52` |
| 视频编码 | H.264 `yuv420p`，`preset medium`，`crf 18` | `build_video.ts:163-164` |
| 音频编码 | AAC 128–160k，`+faststart` | `build_video.ts:203,207` |
| 终混响度 | **−14 LUFS / TP −1.5 dBTP / LRA 11** | `packages/core/src/compose.ts:6-9,68-70` |
| 时长 | 四乐章 ≈900s（±10%）；片尾制作信息页固定 8s | 本文件「时长定标」 |
| 封面 | 第一帧全出血（无桌面色带），可单独出 1 张缩略图 | 同 `one-page-poster` 封面变体 |
| 史料图 | 每张有 `source_id` + license + attribution；full-bleed 长边 ≥1600px / inset ≥900px；无 watermark/AI 放大 | `sources.json` / `facts.visuals` |
| 交付物 | `out.mp4` + `project.json` + `facts.json` + `sources.json` + 探针日志 + 状态帧 + `assets/images/` | 本 skill |
| 发布交接 | 发布词走 `publish-copy`；点发布走 `multilingual-video-publishing` | 两个 skill |

## 验收判据（程序 + 人眼，缺一不可）

| # | 判据 | 怎么判 | 通过条件 |
|---|---|---|---|
| 1 | 双流时长 | `ffprobe` 视频/音频流 | 差 <50ms，理想 0 |
| 2 | 逐场景对账 | 每段视频帧数 vs `d30(pre+body+done+tail)` | 差 0 帧 |
| 3 | **含墨覆盖** | `node assets/template/ink-scan.mjs <out.mp4>`（参数见 `assets/template/README.md`） | 每帧 `gray<200` 占比 **≥0.2%** |
| 4 | 事实/许可/图像 | `node assets/template/validate-facts.mjs`（参数见 `assets/template/README.md`） | 退出 0（交付模式，无占位符；图像长边/类型/attribution 全过） |
| 5 | 高亮正确 | 每场景抽一帧 + 每个同步点一帧，人眼对探针数据 | 画面与 `notes/*.json` 一致 |
| 6 | 内容诚实 | 片内「选段」角标 + 信息页摘录清单 | 与「摘录选择原则」一致 |
| 7 | 史料图身份 | 出处页核对人物/年代/作者；人眼查 watermark、黑边、AI 放大、裁切 | 与图注/旁白一致，且无版权风险 |

**含墨阈值只有一张表**（不要在别处再写一套数）：

| 帧类型 | 含墨占比 | 结论 |
|---|---|---|
| 暖纸 `#f7f2e6` 空页 | 0%（灰度≈242） | **FAIL**——`scan-blank` 抓不到，必须用含墨扫描 |
| 稀疏合法标题卡 | 0.46% | PASS |
| 正常教学帧 / 波形 / preroll | ≥0.3%（实船全片最低 0.868%，样片最低 0.903%，均 1fps） | PASS |
| 判定阈值 | **0.2%** | 低于即坏帧；与稀疏卡 0.46% 之间留 0.26 个百分点余量 |

- **不要用 `feuille karaoke scan-blank` 作为本产线的验收**：它判
  `min(R,G,B) >= 250`，暖纸最小通道 230，对空纸完全盲
  （`packages/karaoke/src/scan_blank.ts:25`，traps §10）。
- 反向自测：按 `assets/template/README.md` 里的自测命令跑，必须得到
  `blank=caught card=passed`。**只证明抓到坏帧不够，必须同时证明好帧没被误杀。**
- 抽帧人眼复核：**机器全绿 ≠ 画面对**（同 `karaoke-video` 的教训）。每个场景
  至少一帧 + 每个同步关键点一帧，用 `read` 真正看进眼里。

## 机器安全（本产线特有的硬约束）

- **禁用 `librosa.pyin` / `librosa.sequence.dtw`**：pyin 走 numba JIT（本机实测
  CPU 471s + 提交内存 154GB，系统三次冻结）；子序列 DTW 的代价模型每步累加，
  结构性偏向把 19s 参考压进 2.1s（假阳性）。
- 替代：`rfftMag` 分块 FFT + 手写泛音和声评分 / 手写 DP。Node 单进程，
  一次只跑一个重分析。
- Python 只作明写例外：独立 uv 环境、`OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2`、
  单进程前台；且仍不许 pyin / DTW。默认路径是 TS。
- Chrome 截图必须带 mock-keychain 旗标（**钥匙串隔离**，`usine/AGENTS.md:104`）；
  **H3 铁律是额度纪律，不是截图纪律**（`usine/AGENTS.md:11`）——不要张冠李戴。
- 史料图只下载到本地再入画面：不热链、不把搜索缩略图当原图、不把 AI 生成图
  当历史照片；CC BY/SA 的 attribution 原样保留。搜索产物落 `.firecrawl/`，
  不放进交付目录（已列入工作区 `.gitignore`）。

## 代码归属

拥有模块：（无）

本产线不拥有 TS 模块：分析原语在 `@feuille/bgm`，装配与截图基座在
`@feuille/karaoke`，TTS 在 `@feuille/core`；模板与只读样例在 `assets/`。
事实源见 `usine/ownership.json`，由 `@feuille/gate` 的 vitest 门禁（`pnpm verify`）
与本行双向机检。

## 边界

- 词级卡拉OK语言课 → `karaoke-video`（本 skill 复用它的帧精确装配纪律，
  不复制实现）
- 实拍压字幕 → `multilingual-video-poetry`
- 生成 BGM 床 / 定床位 → `bgm-bed`（本 skill 只消费真实录音）
- 从零生成画面 → `video-generation`
- 发布词 → `publish-copy`；发布 → `multilingual-video-publishing`

## Resources

- `assets/template/status-frame.html` —— 状态帧骨架（DATA 先于消费者、裸 scene
  名、caption 块级 div、唯一播放头 overlay、`text-anchor="end"` 时间码、统一
  `vmaxRef` 波形）。复制后只改 DATA 与几何，不要重写脚本顺序。
- `assets/template/project.json` —— 装配契约：`scenes[]` 几何/时间、`audio.tracks[]`
  的 offset + gain envelope、ducking、响度目标、含墨阈值、credit 不动点。
- `assets/template/sources.json` —— 许可账本（URL / 许可 / attribution / 日期 / sha256）；
  `kind: "image"` 另带出处页 + 直链 + creator/date/width/height。
- `assets/template/facts.json` —— 制作信息页与发布词的唯一数字源；`visuals[]`
  把每张史料图的用途、图注与 `source_id` 绑死。
- [references/visual-research.md](references/visual-research.md) —— Firecrawl
  史料图检索：查询模板、出处页/许可验证、下载与 sha256、尺寸门槛、入账与
  失败模式。
- `assets/template/ink-scan.mjs` —— 含墨扫描；反向自测（暖纸空页必须 FAIL、
  0.46% 标题卡必须 PASS），命令见 `assets/template/README.md`。
- `assets/template/validate-facts.mjs` —— 账本机检：数字必须有出处、
  `source_ids` 必须存在、交付模式不许留占位符；反向自测命令同 README，
  并已挂进 `packages/gate/test/skills-assets.test.ts`（`pnpm verify` 会跑）。
- `assets/example/` —— 《自新世界》完整链路（Python 快照，**只读**）。读算法与
  几何，不照抄运行方式；差异表见其 `README.md`。
- [references/music-av-traps.md](references/music-av-traps.md) —— 本产线实测
  踩过的坑全集（先读），每条带「层 / 症状 / 机检方式」索引。
- `karaoke-video/references/av-sync.md` —— 帧精确装配纪律（本 skill 沿用；
  其中 headless 旗标一节已与本文件对齐）。
