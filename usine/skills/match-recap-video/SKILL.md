---
name: match-recap-video
description: >
  Produce a narrated match-recap video from a real highlights master: build a
  frame-measured "video time ↔ match clock" mapping by cropping and reading the
  broadcast scoreboard (fps=1 sampling), pull lineups / goals / cards /
  substitutions / VAR from official match pages and both teams' season pages
  (cross-checked), read every window's picture from the master itself
  (kind / visible / see — what is actually on screen, live or replay), write each
  narration line as match-progress + on-screen action fused into one sentence,
  place one three-layer caption window per event (title / say / stat) with
  narration fitted into measured windows, and assemble with burned captions +
  sidechain mixing. Use when the user wants a football (or any
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

解说按**进程轴 × 画面轴**写：进程轴说清第几分钟、谁、比分与意义，画面轴只承认这一窗画面里看得见的动作；两轴合成一句话，观众既跟得上比赛，也不会听到画面上不存在的东西。

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
    → 官方页取事实 → 交叉核对
    → 逐窗读画面（kind / visible / see + 抽帧存档）→ 双轴写事件窗口表
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

## 两条轴：进程轴 × 画面轴（解说方法）

**一条成片里有两种事实，分别来自两个地方。** 进程轴回答「第几分钟、比分多少、谁进球 / 换人 / 吃牌、这件事意味着什么」，事实源是比分牌映射 + 官方比赛页 + 赛季页；画面轴回答「此刻屏幕上是谁、在做什么、哪个机位、是直播还是回放、图形页写了什么」，事实源是**母版本身**。前者进字幕的 `title` / `stat` 和旁白的定位拍、落点拍；后者进旁白的画面拍和窗口表的 `see` 字段。

**为什么必须分轴。** 只按进程轴写词，等于把官方页的时间线念一遍：回放段念「第 4 分钟进球」观众以为又进了一个，跳切段念「72 分钟换人」画面里根本没有换人镜头；只按画面写词，球迷看得见动作却不知道这是第几分钟、比分多少、这球对赛季意味着什么。**画面负责「看见」，旁白负责「看懂」**：旁白不复述观众已经看见的动作，而是补画面自证不了的信息（时间、比分、身份、因果），必要时把目光引到关键处（「注意后点」）。

**一句三拍。** 每个窗口的 `say` 最多三拍，拍与拍之间用逗号 / 句号分开：

| 拍 | 回答什么 | 例（示意，不是逐字稿） |
|---|---|---|
| 定位拍 | 时间 / 比分 / 谁——让观众知道「现在在哪」 | 第 4 分钟，米兰右路 |
| 画面拍 | 这一窗**画面上看得见**的动作与关系 | 起球到后点，普利西奇压着后卫起跳 |
| 落点拍 | 结果与意义——比分、助攻、赛季背景 | 头球破门，德比客场先手 |

- **4s 以上最多三拍，2–4s 两拍，≤2s 一拍**（通常是画面拍）。三拍是上限不是必填：缺的那一拍由 `title` / `stat` 卡补上。字数按中文 TTS 4.5–5.5 字/秒起稿，**判据是 `build_voice` 实测的 slack，不是估算**。
- 三拍顺序不固定，由镜头类型决定；把定位拍硬放最前，会在动作进行中出现念秒表的旁白，观众已经被画面带走了。

**按镜头类型分工。** 窗口表的 `kind` 决定旁白顺序与禁止项：

| kind | 旁白顺序 | 只准说 | 禁止 |
|---|---|---|---|
| `live` 现场 | （定位）→ 画面 → 落点 | 画面上可见的传球 / 跑位 / 射门 + 结果 | 不预告下一拍；球未过线不喊结果；定位只在窗口开头用 3–5 字，不在动作中间插时间 |
| `replay` 回放 | 定位 → 细节 | 「再看一遍」+ 慢镜才看得出的触球、跑位、门将站位 | **不推进进程**：不说新比分、不说「又进一个」、不报新的比赛分钟 |
| `graphic` 图形页 | 读页面 → 官方结论 | 页面上实际出现的名字、判罚词、数字 | 不从旁白或比分倒推页面没写的东西 |
| `jump` 跳切 | 进程 → 影响 | 「这两分钟里」发生了什么 + 战术含义 | **不编画面**：不写跑向边线、教练叮嘱——这些镜头不存在 |
| `ambient` 氛围 | 落点 → 画面 | 情绪、意义、画面里真实的动作 | 不加新的比赛事实；不把庆祝说成又一次进球 |

**三层字幕与旁白分工。** `title` / `stat` 已经承担事件与数据，`say` 不逐字复述——省下的字给画面拍与落点拍。判据：遮住 `title` 和 `stat` 只听旁白，仍能知道「发生了什么、为什么重要」；静音只看卡片，仍能知道「谁、第几分钟、比分多少」。两边各缺一块，合起来才完整。

**画面事实是第三类事实。** 官方页没有的扑救、中柱、单刀、冲突，只在 `live` / `replay` 窗里写，来源标注是**帧号 + 时间码**；号码 / 人脸读不清时用位置称呼（「国米左中卫」），不猜名字。这和「比赛页没有的东西只能从母版画面里看见的写」是同一条纪律的正反两面。

## 逐窗读画面（写词之前做完）

顺序里新增的一步，夹在「官方页取事实」与「写窗口表」之间：

1. **按镜头切窗**：窗口边界落在场景切点上，**一窗一个镜头状态**（`live` / `replay` / `graphic` / `jump` / `ambient`）。一个事件跨了现场和回放，就拆成两个窗——一窗里既现场又回放，旁白必然有一半对不上画面。
2. **每窗取头 / 中 / 尾三帧**，记四件事：景别与机位、主体（号码 / 位置 / 动作）、可读屏幕信息（比分牌 MM:SS、比分、图形页文字）、是否回放（慢放 / 换机位 / 回放角标）。
3. **写 `see`**：一句话写「画面上看见了什么」，只写看得见的，不写推断。
4. **判 `visible`**：`event`（动作本身可见）/ `aftermath`（只见结果：庆祝、比分牌动画）/ `absent`（事件发生在被跳过的时间里）。`absent` 的窗只能写进程，不能写动作。
5. **抽帧存档**：`shots/w05-a.jpg` / `-b` / `-c`，与窗口 key 对齐——验收时拿它对照 `see` 与 `say`，不靠回忆。

六个典型场景的写法、声画同步的机械细节与反向验证见 [references/visual-commentary.md](references/visual-commentary.md)。

## 窗口表 schema

每个事件一个窗口；`title / say / stat` 三层分别进字幕卡的三行，`kind / visible / see` 是画面轴的读数列（`see` 只写画面里看得见的；下面文案是写法示意，不是 derby 逐字稿）：

```ts
{ key: 'w05', t0: 36, t1: 42,
  kind: 'live',       // live | replay | graphic | jump | ambient
  visible: 'event',   // event | aftermath | absent
  see: '右路起球到后点，普利西奇起跳压过后卫，头球入网（远景，门后机位）',
  title: '第4分钟 · 普利西奇破门',          // 第一层：事件标题
  say: '右路起球到后点，普利西奇压着后卫起跳，头球破门——德比客场先手。', // 第二层：旁白正文（画面拍 + 落点拍）
  stat: '1-0 · 普利西奇 4\' · 助攻 莫雷拉' }  // 第三层：数据条
```

- **一窗一镜态**：窗口按镜头切点分，不按事件名字分；进球包的三段（现场 / 比分动画 / 回放）就是三个窗，信息职责不同——现场讲过程、比分动画讲数据与意义、回放讲细节，不重复同一句话；
- **阵容卡**占开球前整段（derby：0–12s），单独一张 22 人阵型卡（`kind: 'graphic'`，名字以卡片上可读的为准）；
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
| 画面 | 抽帧复核：阵容窗口见阵容卡、每个进球窗口见进球画面；回放窗见慢放 / 不同机位；跳切窗前后比分牌时间确实跳了 |
| 画面读数 | 每窗有 `kind` / `visible` / `see`，头 / 中 / 尾三帧存档与 `see` 一致 |
| 声画对账 | `say` 的每个动作短语能在同窗 `see` 找到主体；回放窗无新进程、跳切窗无动作细节（三条反向验证全抓，见 references） |
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
- [references/visual-commentary.md](references/visual-commentary.md) —— 进程轴 ×
  画面轴：读画面五步、六个典型场景模板、声画同步与反向验证
- `multilingual-video-poetry/references/ffmpeg-pitfalls.md` —— 音频三坑
