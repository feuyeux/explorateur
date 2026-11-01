---
name: music-annotate-video
description: >
  Produce music-appreciation teaching videos built on REAL recordings: align
  score/MIDI ground truth to a recording (chord-template classification, NOT
  DTW), derive note-level timelines from f0 tracking (hand-rolled
  harmonic-sum autocorrelation, NOT librosa.pyin), render teaching frames
  (chord timeline / melody line / instrument-range chart / waveform with
  measured event marks / bio timeline), assemble frame-exactly with narration
  + music excerpts (ducking while the narrator speaks, full level while
  listening), and append a measured-numbers production-notes credit card.
  Multi-movement works (symphonies etc.) are sized at ~15 minutes — listening
  time is the product, narration is the seasoning (see 时长定标 below).
  Use when the user asks for a classical-music (or any recorded-music)
  explainer/appreciation video, "teach me this piece/symphony" videos, or
  listening-guide videos with synced visual annotation. Not for
  word-highlight karaoke of language lessons (use karaoke-video), not for
  live-action subtitle overlays (use multilingual-video-poetry), not for
  generated-from-scratch video content (use video-generation), and not for
  BGM bed production (use bgm-bed — this skill consumes recordings, it never
  invents music).
---

# Music Annotate Video

古典音乐（或任何真实录音）欣赏科普视频的产线：**录音是内容本体**，画面是
程序化渲染的教学标注，旁白与音乐摘录混音。与 `karaoke-video` 的结构性差异：
token 不是「词」而是「音符/和弦」，时间轴不是 TTS 边界而是**从乐谱真值或
录音实测对齐出来的**。

首个完整实现：`usine/examples/dvorak-new-world/tools/`（德沃夏克《自新世界》，
B0–B4 全链路验证）。**脚手架从那里抄，不要凭记忆重写**——每个函数背后都有
一次实测翻车的教训（见 references/music-av-traps.md，先读它再动手）。

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
| 制作信息页 | 8s | |

**聆听优先三原则**（v1→v2 的核心教训）：
1. **旁白是插话，不是主体**——音乐在旁白下压 −12dB 继续走，绝不因
   「旁白讲完了」而停；每乐章纯聆听 ≥ 旁白总长。
2. **乐章间留 0.8s 呼吸**；同乐章的续段（如谐谑曲外壳→中段）用小 preroll
   （0.3s）减小停顿。
3. **画面在聆听段必须持续推进**：波形 5s/态、旋律 2.5s/态（播放头 + 时间码 +
   已播罩亮 + 实测事件线）；「同一帧停 30s」= 信息断供。

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
| 1 | **公有领域录音**（Wikimedia Commons / Musopen 等），逐件登记 URL+许可 | 版权风险；无法剪辑混音 |
| 2 | 乐谱真值（CC0 MIDI / 谱例 SVG）——没有真值的段落用「录音实测」口径并如实标注 | 高亮与声音对不上还不自知 |
| 3 | 每个教学段落的时间码**实测**（RMS 包络 / 高频峰簇 / 和弦对拍），不凭记忆 | 摘录切错位置，旁白讲的东西不在音频里 |
| 4 | 旁白语种与画幅 | 无法定 TTS 与状态帧几何 |
| 5 | 讲述者口径（人声不出镜·散文讲者/听辨式教学） | 做成语言课或评书 |

## Workflow

1. **探针先行（零额度）**：对录音跑 RMS 包络（找引子/爆发/主题进入）、
   高频峰簇（找三角铁/钹段）、和弦模板分类（对 MIDI 段）。所有摘录时间码
   必须有探针日志背书。
2. **对齐**：
   - 有 MIDI 真值 → `opening_timeline.py` 式「和弦模板逐帧分类 + 段序对拍 +
     带内判据 + 逐和弦 chroma 交叉验证」→ 逐音符时间轴 JSON；
   - 无真值的独奏段 → `theme_timeline.py` 式「手写泛音和声评分 f0 → 半音域
     中值平滑 → 滞回量化 → 聚段」→ 逐音符时间轴 JSON。
   判据双条：结构块落带内 + 起点后 0.05–0.6s 最强音级交集 ≥ 2/3。任何一条
   不满足即 fail-closed，不许当「差不多」读。
3. **视觉形态**：和弦时间轴 / 旋律线 / 乐器音域图 / 波形+实测事件线 /
   生平时间轴——全部内联 SVG + Chrome headless 状态帧
   （mock-keychain + basic password-store + 独立 user-data-dir 三个旗标）。
   事实口径：画面里每个数字/引语必须有出处；有争议的（如灵歌引用）写
   当事人的澄清，不写定论。
4. **旁白**：`feuille karaoke tts` 生成（edge-tts 协议在 @feuille/core）。
   **TTS 文本剥除全部标点**（标点→空格），display token 才留标点——
   不然词边界缺失、尾部 token 拿到 null、构建崩在 `toFixed`。
5. **装配**（帧精确，纪律同 karaoke-video/av-sync.md）：
   - 每个状态段用精确帧数单独编码再 `concat -c copy`；
   - 所有场景总长 `d30()` 吸附 30fps 网格，音频段 `-t` 裁到场景总长；
   - **音乐轨 `adelay` 顺延 preroll**（否则高亮整体滞后 0.8s——§4 的镜像陷阱）；
   - 旁白出声时音乐压到 0.25（≈−12dB），聆听段全电平；**多乐章作品按
     「时长定标」表配聆听时长**——旁白讲完音乐继续；
   - 状态段与高亮是**同一段 [t[i−1], t[i]) 显示 state i−1**——off-by-one
     会把高亮整体错一个块；
   - 旁白多句按实测时长**顺延**（at 累加），不许同刻齐发；
   - 封装 `apad + -t v_dur` 裁齐双流（AAC priming 被吃掉，双流差 0ms）。
6. **逐场景音画对账**：每场景「视频段总长 vs d30(pre+body+done+tail)」
   差值必须为 0（traps §14）——只看全片总长会漏掉互相抵消的错位，而错位
   会传染给后续所有场景的旁白。
7. **验收**（程序 + 人眼，缺一不可）：
   - ffprobe 双流时长差（<50ms，理想 0）；
   - **含墨扫描**代替白页扫描：1fps 采样，可见标记（灰度 <200）<0.2% = 坏帧。
     **不要用「近白占比」**——纸色 #f7f2e6 灰度≈242，恰好躲过白色阈值
     （实船事故：全片 112s 空纸但白页扫描全绿）；
   - 空白帧哨兵同口径（全暗 preroll 帧也必须有 ≥0.3% 可见标记）；
   - 抽帧人眼复核：每个场景至少一帧 + 每个同步关键点一帧，核对高亮与
     时间轴/探针数据一致。
8. **制作信息页二段式**：卡片是成片的一部分，时长/结束时间在成片出来前
   不存在——先出占位卡拼进成片，成片完成后回填实测数字重渲、重编该段、
   `concat -c copy` 重拼接、重封装。所有数字实测，不许手抄。

## 机器安全（本产线特有的硬约束）

- **禁用 librosa.pyin / librosa.sequence.dtw**：pyin 走 numba JIT（本机实测
  拖死系统：CPU 471s + 提交内存 154GB）；子序列 DTW 的代价模型每步累加，
  结构性偏向把 19s 参考压进 2.1s（假阳性，PLAN §5.3(b) 的根源）。
  替代：手写 numpy DP / 泛音和声评分（纯 numpy，分块 FFT 控内存）。
- 重计算一律前台单步跑、`OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2` 压顶、
  一次只跑一个重进程；uv 环境用 python 3.11、librosa 与 mido 挂临时依赖
  （uv 的 python / with 两个旗标；numpy/scipy 二进制不兼容 anaconda 基座，见 PLAN §5.2）。
- Chrome 截图必须带 mock-keychain 旗标（工厂 H3 铁律）。

## 边界

- 词级卡拉OK语言课 → `karaoke-video`（本 skill 复用它的帧精确装配纪律，
  不复制实现）
- 实拍压字幕 → `multilingual-video-poetry`
- 生成 BGM 床 / 定床位 → `bgm-bed`（本 skill 只消费真实录音）
- 发布 → `multilingual-video-publishing`；发布词 → `publish-copy`

## Resources

- 参考实现（唯一完整样例）：`usine/examples/dvorak-new-world/tools/`
  - `opening_timeline.py` 和弦模板对拍对齐 · `theme_timeline.py` f0 音符时间轴
  - `b2_build.py` 单场景产线（样片）· `b4_build.py` 多场景全片产线
  - `credit_card.py` 制作信息页 · `probe_movs.py` 系摘录探针
- [references/music-av-traps.md](references/music-av-traps.md) —— 本产线实测
  踩过的坑全集（先读）：DTW 压缩、pyin 死机、脚本顺序 TDZ、scene 名拼接、
  off-by-one、preroll 延迟、纸色躲过白页扫描、credit 二段式
- `karaoke-video/references/av-sync.md` —— 帧精确装配纪律（本 skill 全条沿用）
