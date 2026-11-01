---
name: match-recap-video
description: >
  Produce a narrated match-recap video from a real highlights master: build a
  frame-measured "video time ↔ match clock" mapping by cropping and reading the
  broadcast scoreboard (fps=1 sampling), pull lineups / goals / cards /
  substitutions / VAR from official match pages and both teams' season pages
  (cross-checked), place one three-layer caption window per event (title / say /
  stat) with narration fitted into measured windows, and assemble with burned
  captions + sidechain mixing. Use when the user wants a football (or any
  timed-sport with an on-screen scoreboard) match explainer — 阵容 / 进球 / 换人
  / VAR — for fans to follow the match, from a highlights master they supply or
  that exists on an official channel. Not for generic live-action subtitle
  overlays (multilingual-video-poetry owns the assembly mechanics and this skill
  reuses them), not for poster/card-driven videos (karaoke-video /
  storyteller-video), not for music-appreciation annotation (music-annotate-video),
  and not for BGM bed production (bgm-bed).
---

# 赛事集锦解说视频

从**一条真实比赛集锦母版** + **官方赛事数据**出一条中文解说成片：球迷看完能
清晰掌握比赛过程（谁进了球、何时换人、VAR 改了什么）。画面是实拍母版，
装配机制沿用 `multilingual-video-poetry`；本 skill 的新增物只有一件事——
**把 95 分钟的比赛坐标映射进 8 分钟的集锦**。

首个完整实现：`usine/examples/derby-2026/`（2026-27 意甲第 10 轮米兰德比，
AC米兰 3-1 国际米兰，485.48s 母版 → 8 分钟成片）。**脚手架从那里抄**：
`src/配文.ts`（文案与赛事事实单一事实源）· `build_voice.ts`（TTS 校窗）·
`render_cards.ts`（三层字幕卡）· `mix.ts`（烧录 + 侧链混音）· `render_cover.ts`（封面）。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **一条集锦母版**（官方频道 extended highlights 优先） | 本 skill 不适用——集锦的压缩比 10×–20× 还不等，没有母版就没有映射基准 |
| 2 | **官方比赛页**（如 legaseriea match 页 + /lineups 页） | 阵容 / 进球 / 换人 / VAR 无事实源，解说会编造 |
| 3 | **两队赛季页**（Wikipedia）交叉核对主帅、积分背景 | 主帅与「赛季首败」这类叙事没有归属地 |
| 4 | 解说语种 + 音色 + 画幅 | TTS 与字幕几何定不了 |
| 5 | 覆盖哪些事件轴（阵容 / 进球 / 换人 / 红黄牌 / VAR） | 窗口表无从建；默认全要 |

## 顺序不能换

```
母版下载冻结 → 逐秒实测「视频时间 ↔ 比赛时钟」映射
    → 官方页取事实 → 交叉核对 → 写事件窗口表
    → TTS 实测校窗 → 三层字幕卡 → 烧录 + 侧链混音 → 封面 → 发布词
```

**先建映射再写词。** 母版把 95 分钟压进 8 分钟且含回放，压缩比不均匀——
凭印象写「第 X 分钟的画面在视频第 Y 秒」必错。映射表是后面一切落点的依据
（做法见下节）。

## 视频时间 ↔ 比赛时钟的实测映射（本 skill 的核心新增）

1. **全片 fps=1 采样**（485s 母版 = 485 帧）；
2. **裁比分牌**：转播比分牌位置固定，裁出后**竖拼**成对照长图逐帧读
   MM:SS 与比分（derby 实测裁法：`crop=100:36:170:86` 与 `crop=60:36:400:86`；
   每个联赛转播的比分牌几何不同，**先探针再定裁窗，不抄数字**）；
3. **ffmpeg 场景检测**定位事件包：`select='gt(scene,0.25)'` 的切点聚集处 =
   进球包 / VAR 图形页 / 终场哨，与比分牌读数互相印证；
4. **盯住跳切**：集锦会整段跳过时间（derby 实测 311→314s 从 69:46 跳到
   73:26、353→354s 从 74:56 跳到 89:58）。**跳切点就是事件落点**——被跳过的
   换人（72'、81'–89'）解说就放在跳切上，与画面的时间跳跃对齐，不要找
   「换人画面」（根本不存在）；
5. 读数锚点全部回填 `配文.ts` 的 `WINDOWS`（derby 实测样例：4' 进球画面在
   36–42s、比分动画 ~42s、回放 43–57s；VAR 改判 336–345s（图形页写着
   PAVLOVIC / FOUL）；终场哨 403–406s，比分牌最后读到 95:03）。

详细坑表：[references/match-clock-mapping.md](references/match-clock-mapping.md)。

## 事实源纪律

- **进球 / 助攻 / 换人 / 红黄牌 / VAR**：官方比赛页（legaseriea）为事实源；
- **主帅**：以两队 Wikipedia infobox 为准（官方比赛视频标题可作旁证）；
- **赛季叙事**（联赛排名、赛季首败、德比背景）：两队赛季页交叉核对；
- 比赛页没有的东西（谁抗议、谁拥抱）**只能从母版画面里看见的写**，
  看不见的不写；
- 球员中文译名全文一致（`配文.ts` 的 `MILAN_XI / INTER_XI` 是唯一名单，
  旁白、字幕卡、封面都从它取，不另抄）。

## 窗口表 schema

每个事件一个窗口；`title / say / stat` 三层分别进字幕卡的三行：

```ts
{ key: 'w05', t0: 36, t1: 43,
  title: '第4分钟 · 普利西奇破门',          // 第一层：事件标题
  say: '第四分钟，莫雷拉右路传中，普利西奇抢点头球破门！', // 第二层：旁白正文
  stat: '1-0 · 普利西奇 4\' · 助攻 莫雷拉' }  // 第三层：数据条
```

- **阵容卡**占开球前整段（derby：0–12s），单独一张 22 人阵型卡；
- 旁白落点带 `LEAD`（实测 0.45s）：画面先到位，声音再进来；
- **TTS 时长是实测的**：每段合成后立刻量，超窗压词不硬塞（build_voice 报
  每段 slack，超窗退出码 1）；
- 结尾必有一段「回顾」窗口（全场进球 / 换人次数汇总），球迷的收获沉淀在这。

## 装配（沿用 multilingual-video-poetry，不另写）

- 三层字幕卡 = 透明 PNG 逐张 overlay 串接烧录；**卡片走单帧输入，不加
  `-loop 1`**——53 张卡就是 53 路 × fps 的无限 PNG 解码，实测 65s 预览
  5 分钟不出片；overlay 默认 `eof_action=repeat` + `enable=between(t,…)` 足够；
- 混音三层：中文旁白（loudnorm −16 LUFS）> 意语原声（压低保留作氛围）>
  BGM 床（`bgm-bed` 反推 gain）；旁白轨 `asplit=3`（主轨 + 两路侧链触发），
  床与原声被侧链动态压住。三个经典音频坑（asplit 缺失 / loudnorm 排序 /
  结尾余量）见 `multilingual-video-poetry` 的 references，**不要在这里复写**；
- 床位增益必须用**成片轨**量出的旁白电平反推（loudnorm 后语音段比单段 mp3
  高 ~6.9 dB，口径混了床会白生成）；
- 大段音频定位不了时用 mix.ts 的**分轨模式**落盘逐段对齐（另带片段预览模式，先看一段再跑全片）。

## 每一步的验收判据

| 步骤 | 判据 |
|---|---|
| 映射 | 比分牌读数长图逐帧目视确认；跳切点前后 MM:SS 有记录 |
| 事实 | 每个进球/换人/VAR 都能指到官方页条目；主帅指到 Wikipedia infobox |
| TTS | 每段实测时长 ≤ 窗口；超窗压词（build_voice 退出码 0 = 全部过） |
| 成片 | ffprobe 通过（**moov atom 找不到 = 渲染被杀，重跑，不要当产物用**）；时长 = 母版时长 |
| 画面 | 抽帧复核：阵容窗口见阵容卡、每个进球窗口见进球画面 |
| 混音 | `feuille poetry audio-profile` 配比判据：人声段 − 空档底 ≥ 8 dB（LUFS 口径） |
| 收尾 | 封面 + 各平台 `publish/*.md`（横屏 → B站） |

⚠️ **渲染被中断的 mp4 是半成品**：ffmpeg 中途被杀（会话结束、断电）留下
没有 moov atom 的文件，ffprobe 直接报 Invalid data。判定口径只有 ffprobe，
不看文件大小（270 MB 的「大文件」照样是废片）。

## 边界

- 装配机制（TTS 校窗 / 三层烧录 / 侧链混音 / 封面规范）→ `multilingual-video-poetry`
  （本 skill 是它在赛事域的特化：时间轴来自**比分牌映射 + 官方事件**，
  不是场景美学）
- 出母版（无现成集锦、要生成画面）→ `video-generation`；但**官方集锦优先**——
  生成画面出不了真实比赛
- 生成 BGM 床 / 定床位 → `bgm-bed`
- 发布词 → `publish-copy`；发布执行 → `multilingual-video-publishing`
  （永不自动，用户喊了才发）
- 泛化到其他运动：比分牌映射法适用于任何**带屏幕比分牌的计时运动**
  （篮球 / 网球…），但事实源与窗口 schema 的样例目前只有足球——
  换运动先重新探针比分牌几何

## Resources

- 参考实现（唯一完整样例）：`usine/examples/derby-2026/`
  - `src/配文.ts` 文案与赛事事实单一事实源（53 窗口 + 名单 + 事件表）
  - `src/build_voice.ts` TTS 逐段实测校窗 · `src/render_cards.ts` 三层字幕卡
  - `src/mix.ts` 烧录 + 侧链混音（自带片段预览与分轨诊断两种模式）
  - `src/render_cover.ts` 封面（3:4，底帧选无比分牌中间态的庆祝帧）
- [references/match-clock-mapping.md](references/match-clock-mapping.md) —— 比分牌
  映射的实测坑表（先读）
- `multilingual-video-poetry/references/ffmpeg-pitfalls.md` —— 音频三坑
