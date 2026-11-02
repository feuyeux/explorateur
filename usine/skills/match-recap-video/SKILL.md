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
  sidechain mixing. Ships runnable resolvers for FC Barcelona, Liverpool,
  Borussia Dortmund and Paris Saint-Germain (latest league match, official
  highlights search included). Use when the user wants a football (or any
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

首个完整实现是 2026-27 意甲第 10 轮米兰德比（AC米兰 3-1 国际米兰，485.48s 母版 →
8 分钟成片）。同一产线已实跑四场：`examples/klassiker-2026/`（拜仁 2-2 多特，BVB 官方
highlights 裁到 162s）、`examples/barcelona-2026/`（巴萨 6-1 阿拉维斯，192s）、
`examples/psg-2026/`（勒阿弗尔 1-5 巴黎，330s）、`examples/liverpool-2026/`
（利物浦 0-1 阿森纳，120s）。后三场同样无视觉输入，用 `read_scoreboard.py`
OCR 读数、窗口标 `visible: unread`，画面轴待人工复核。**装配脚手架不在本 skill 里**——从 `multilingual-video-poetry` 的入库
样例抄：`assets/example/配文.py`（文案与名单的单一事实源）· `build_voice.py`
（edge-tts 合成 + 实测校窗）· `subtitles.py`（三层字幕卡 → 透明层 → 烧录）·
`mix.py`（BGM + 旁白侧链混音）· `封面.py`（封面）。底层能力用 `packages/core/src/`
的 `tts` / `textlayer` / `covers` / `compose` / `audio`——**本 skill 只新增赛事域的
那一层**（时间轴来源、事实源、事件轴）。

## 支持哪些球队 / 联赛

球队与联赛是**注册表**，不是正文：`assets/teams.json`（队伍）× `assets/leagues.json`
（联赛适配器）。新增一支球队 = 加一条注册表 + 一个联赛适配器，**不改本文件的正文**。

| 队伍 | 联赛 | 官方事实源事件流 | VAR | 母版来源 | 实跑结论（2026-11-02） |
|---|---|---|---|---|---|
| AC米兰 / 国际米兰 | 意甲 | 结构化 | ✗ | 官方频道 | 基线 |
| **巴塞罗那** | 西甲 | **结构化**（进球/换人/牌/VAR 分行） | ✓ 明列 | 官方频道检索 | ✅ **跑通**：6-1 阿拉维斯（10-31 第 11 轮）· 7 进球（含射手/助攻）/ 10 换人 / 5 黄牌 / 1 VAR |
| **利物浦** | 英超 | **文字直播**（`/commentary`，需滚动抓） | ✗ | **比赛页内嵌** | ✅ **跑通**：0-1 负阿森纳（11-01 第 9 轮）· 16' Havertz / 9 换人 / 8 牌 · 球场 Anfield · 主裁 Andy Madley · 官方集锦链接直出 |
| **多特蒙德** | 德甲 | **结构化 liveticker**（`## GOAL!` + 分钟 + 比分 + Assist） | ✗ | liveticker 页内 / 官方频道 | ✅ **跑通**：2-2 拜仁（10-31 第 8 轮）· 4 进球（38' Laimer、60' Guirassy、66' Upamecano、89' F. Silva）/ 8 换人 / 3 牌 |
| **巴黎圣日耳曼** | 法甲 | **psg.fr 文字直播**（`Goal!` / `Substitution,` / `VAR Decision:`） | ✓ 明列 | Ligue 1 / PSG 官方频道 | ✅ **跑通**：1-5 勒阿弗尔（10-30 第 9 轮）· 6 进球 / 8 换人 / 1 VAR · `psg.fr` 月度赛程页按日期定序出「最新一场」；**阵容仍缺**（psg.fr 不含阵型） |

⚠️ **四个目标联赛不是等价的，但四个都已能跑通。** 西甲的官方比赛页是即装即用版；
英超的 overview 只有叙述稿，逐分钟事件要**滚动抓 `/commentary`**（不滚动只剩末尾几条）；
德甲 liveticker 的进球是结构化块（旧的「进球分钟抓不到」结论已作废），只是编辑标题
仍要当叙述素材而不是事件分钟；法甲的 `ligue1.com` 仍答不出「最新一场」，改由
**psg.fr 月度赛程页 + 比赛页文字直播**接管，`ligue1.com` 退为阵容面（psg.fr 没有阵容）。
逐个联赛的实测结论（URL 模式、坑、样例解析结果）见
[references/league-fact-sources.md](references/league-fact-sources.md)——**先读它再动手**。

事实源能力不足时**显式降级**：不拿二手数据悄悄补齐，编出来的解说比没有解说更糟。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **一支球队 + 「本赛季最新一场」的口径**（只看联赛 / 含杯赛欧战） | 口径不同答案不同：利物浦联赛最新是 0-1 负阿森纳，含杯赛则是联赛杯点球大战。用 `scripts/resolve_match.py <key> [league\|all]` 解析，别手挑 |
| 2 | **一条集锦母版**（官方频道 extended highlights 优先） | 本 skill 不适用——集锦的压缩比 10×–20× 还不等，没有母版就没有映射基准。用 `scripts/find_master.py` 出候选，人眼确认后冻结 |
| 3 | **官方比赛页**（见 `assets/leagues.json` 的 `match_url` 模板） | 阵容 / 进球 / 换人 / VAR 无事实源，解说会编造 |
| 4 | **两队赛季页**（Wikipedia）交叉核对主帅、积分背景 | 主帅与「赛季首败」这类叙事没有归属地 |
| 5 | 解说语种 + 音色 + 画幅 | TTS 与字幕几何定不了 |
| 6 | 覆盖哪些事件轴（阵容 / 进球 / 换人 / 红黄牌 / VAR） | 窗口表无从建；默认全要。**该联赛官方页不支持的轴要显式说做不到** |

第 1 与第 3 项由 `scripts/resolve_match.py` 一步产出：它把「哪支队的哪一场」解析成
一份 fact pack（比赛页 URL + 比分 + 日期 + 事件时间线 + `key_events` + 每个字段的
来源）。母版候选由 `scripts/find_master.py` 检索（官方频道 + 比分一致性 + 时长）。
解析不出来时**退出非零并留下原始证据**，不静默兜底成默认值。

官方赛程面答不出「最新一场」的联赛（实测：**法甲**），`resolve_match.py` 自动改走
**俱乐部官网 psg.fr 的月度赛程页**；`ligue1.com` 只留作阵容面。仍然解析不出来时，
才用**手动指定比赛页**兜底，用法见
[references/league-fact-sources.md](references/league-fact-sources.md) 的「巴黎怎么办」。

## 顺序不能换

```
解析「哪支队的哪一场」（fact pack）→ 官方频道检索母版候选 → 人眼确认后冻结
    → 逐秒实测「视频时间 ↔ 比赛时钟」映射
    → 官方页取事实（多页：英超 overview + /commentary）→ 交叉核对
    → 逐窗读画面（kind / visible / see + 抽帧存档）→ 双轴写事件窗口表
    → 机检三条硬判据（check_windows.py）
    → TTS 实测校窗 → 三层字幕卡 → 烧录 + 侧链混音 → 封面 → 发布词
```

**先定「哪一场」，再取母版。** 「当前赛季最新一场」本身有歧义：联赛 vs 所有赛事、
两个候选面给出不同的日期、解说口径不同（点球大战 vs 联赛负）。这些要在写词**之前**
定死，否则母版与事件表会对不上。

**先建映射再写词。** 母版把 95 分钟压进 8 分钟且含回放，压缩比不均匀——
凭印象写「第 X 分钟的画面在视频第 Y 秒」必错。映射表是后面一切落点的依据
（做法见下节）。

## 视频时间 ↔ 比赛时钟的实测映射（本 skill 的核心新增）

1. **全片 fps=1 采样**（485s 母版 = 485 帧）；
2. **裁比分牌**：转播比分牌位置固定，裁出后**竖拼**成对照长图逐帧读
   MM:SS 与比分（derby 实测裁法：`crop=100:36:170:86` 与 `crop=60:36:400:86`；
   每个联赛转播的比分牌几何不同，**先探针再定裁窗，不抄数字**）。
   探针已做成脚本：`python3 scripts/probe_scoreboard.py <母版>` 会在上沿/下沿
   六块候选带上量**每秒变化密度**（比分牌每秒钟跳一次，密度远高于静态画面），
   排名输出候选裁窗，并为每个候选生成一张 1 帧/秒的**竖拼长图**供人眼确认。
   脚本给的是**候选 + 证据**，裁窗的最终值要人眼拍板后写进窗口表锚点。
   没有视觉输入时，用 `python3 scripts/read_scoreboard.py <母版> --from-probe probe.json`
   把读数交给本地 OCR（RapidOCR）：输出逐帧 `minute / score / texts`、比分变化
   （进球锚点）与跳切候选。OCR 会把 8/6 认混，**比分变化必须和官方事件分钟互证**。
   ⚠️ 不是所有转播都给 MM:SS——德甲比分牌只有 `60'`（分钟），读数粒度就是 1 分钟；
   先确认该联赛的时钟格式，不要把「分钟」当「分秒」。
3. **ffmpeg 场景检测**定位事件包：`select='gt(scene,0.25)'` 的切点聚集处 =
   进球包 / VAR 图形页 / 终场哨，与比分牌读数互相印证；
4. **盯住跳切**：集锦会整段跳过时间（derby 实测 311→314s 从 69:46 跳到
   73:26、353→354s 从 74:56 跳到 89:58）。**跳切点就是事件落点**——被跳过的
   换人（72'、81'–89'）解说就放在跳切上，与画面的时间跳跃对齐，不要找
   「换人画面」（根本不存在）；
5. 读数锚点全部回填 `配文.py` 的窗口表（derby 实测样例：4' 进球画面在
   36–42s、比分动画 ~42s、回放 43–57s；VAR 改判 336–345s（图形页写着
   PAVLOVIC / FOUL）；终场哨 403–406s，比分牌最后读到 95:03）。

详细坑表：[references/match-clock-mapping.md](references/match-clock-mapping.md)。

## 事实源纪律

- **进球 / 助攻 / 换人 / 红黄牌 / VAR**：**该联赛的官方比赛页**为事实源。URL 模板
  与各联赛的实抓结论在 `assets/leagues.json` 与
  [references/league-fact-sources.md](references/league-fact-sources.md)，**不要凭印象
  拼链接**（法甲的 `club_id 90` 是巴黎 FC 不是巴黎；西甲的主客 slug 用 `-` 直连没有
  `vs`）；
- **主帅**：以两队 Wikipedia infobox 为准（官方比赛视频标题可作旁证）；
- **赛季叙事**（联赛排名、赛季首败、德比背景）：两队赛季页交叉核对；
- 比赛页没有的东西（谁抗议、谁拥抱）**只能从母版画面里看见的写**，
  看不见的不写；
- **该联赛官方页不支持的事件轴要显式说做不到**，不拿二手数据悄悄补齐：
  西甲明列 VAR 判决；英超/德甲不明列（只能从 `/commentary` / liveticker 正文找线索）；
  巴黎的 psg.fr 比赛页**明列 `VAR Decision:`**，但 `ligue1.com` 不列；
- **巴黎的「最新一场」走 psg.fr，不走 ligue1.com**：`ligue1.com` 只给未赛场次 /
  不带日期的比分，`psg.fr` 的 `.../mens-football/fixtures?period=Mon` 有真实日期 +
  比分 + 比赛页链接。`resolve_match.py` 自动抓当前月 + 前两个月并取并集；
- **巴黎阵容是已知缺口**：psg.fr 比赛页有事件、比分、球场、主裁，但没有阵容/阵型；
  阵容要回 `ligue1.com` 的 match-sheet。fact pack 的 `lineups_note` 会写明这一点，
  不能拿「事件齐了」冒充「阵容齐了」；
- 球员中文译名全文一致：**每场比赛建一份名单**，旁白、字幕卡、封面都从它取，不另抄。
  名单的字段口径与命名约定见下节。

## 「当前赛季最新一场」怎么定（多球队产线的入口）

`scripts/resolve_match.py` 把这一步做成可复跑、可审计的脚本，而不是人工翻网页：

```bash
python3 scripts/resolve_match.py barcelona            # 默认 league 口径，真抓，出 fact pack
python3 scripts/resolve_match.py barcelona all        # 含杯赛 / 欧战口径
python3 scripts/resolve_match.py barcelona --dry-run  # 先看它打算抓哪几个面
python3 scripts/resolve_match.py --all-targets --asof 2026-11-02 --out packs.json
                                                      # 四支目标队一次解析（巴萨/利物浦/多特/巴黎）
python3 scripts/resolve_match.py selftest             # 离线回归（不联网）
```

参数：`resolve_match.py <队伍 key> [league|all] [基准日]`（位置参数，适合单队）；
批量用 `--targets a,b,c` 或 `--all-targets` + `--asof`。出口用 `--out <路径>`。
fact pack 里除 `latest_pick` / `match_page` 外还有 `key_events`（只留进球/换人/牌/VAR）
与 `event_counts`，窗口表直接从 `key_events` 取。完整参数见
`python3 scripts/resolve_match.py --help`。

**母版检索**接着跑（人工确认后才冻结）：

```bash
python3 scripts/find_master.py barcelona --fact-pack packs.json   # 官方频道候选 + 排序
python3 scripts/find_master.py psg --fact-pack packs.json --download masters/
```

它读 fact pack 的「主客 + 比分」，在 YouTube 上跑两轮检索（普通 / extended），
按**官方频道、标题比分是否一致、时长**排序，输出候选与推荐；`--download` 才真的下载。
官方频道是精确 handle 匹配——`Sky Sports Premier League` 这类媒体号不会被误判成官方。
排名第一也仍要人眼核对标题与频道；脚本给的是证据，不是拍板。

三条硬规矩（来自纪律 12 / 19）：

1. **不许凭网页顺序猜「最新」。** 法甲巴黎的俱乐部页上，轮播首位、比分控件、
   官方集锦视频列表**互相指不到同一场**。只有**日期**能定序——排序键永远是日期，
   取不到日期的候选不进评选，并被原样报出来。
2. **解析不出来就退出非零并留下原始证据**，不许静默兜底成默认值。
3. **每个字段带来源**：fact pack 记着它是从哪个 URL、哪条规则抽出来的；抽不到的字段
   是 `null` 并标 reason，不填猜测值。

「league 口径」与「all 口径」的差别不是细节，是解说叙事的分岔：利物浦联赛最新
是 0-1 主场负阿森纳，含杯赛则是联赛杯点球大战。

**新增球队**只要两步：往 `assets/teams.json` 加一条（中文名 / 英文名 / 联赛 / 俱乐部
slug 与 id / 官方集锦频道 / 品牌色 / 原声语言 / 宿敌），往 `assets/leagues.json` 加一
条联赛适配器（若该联赛还没有）。若联赛官方站答不出「最新一场」（法甲就是），
再给球队加 `club_site.fixtures_url`（月度赛程模板，`{lang}` / `{period}` 占位），
`resolve_match.py` 会自动按当前月 + 前两个月抓。**不要把球队专有事实写进本文件**——
某场比分、某个进球分钟是每场比赛的事实，走官方比赛页。

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
4. **判 `visible`**：`event`（动作本身可见）/ `aftermath`（只见结果：庆祝、比分牌动画）/ `absent`（事件发生在被跳过的时间里）/ `unread`（**画面没读**）。`absent` 的窗只能写进程，不能写动作；`unread` 是显式降级——当运行环境没有视觉输入（模型不能读图、视觉代理不可用），`see` 只写 OCR 能自证的比分牌/图形页，`check_windows.py` 对这类窗的动作对账降为 WARN，**不冒充 PASS**，交给人眼或视觉复核后再冻结。
5. **抽帧存档**：`shots/w05-a.jpg` / `-b` / `-c`，与窗口 key 对齐——验收时拿它对照 `see` 与 `say`，不靠回忆。

六个典型场景的写法、声画同步的机械细节与反向验证见 [references/visual-commentary.md](references/visual-commentary.md)。

**三条硬判据已经有机检。** `references/visual-commentary.md` §6.3 要求「注入三个坏例，
判据必须全部抓到」——`scripts/check_windows.py` 就是那份坏例的载体：

```bash
python3 scripts/check_windows.py selftest      # 反向验证：好表全过 + 三个坏例全抓
python3 scripts/check_windows.py windows.json   # 判决窗口表（FAIL 退出码 1）
```

§6.4 说「词表扫候选**不能自动判 FAIL**」——那是**裸词表**的限制：词表不知道自己
在哪种窗、这窗之前说过什么。检查带了窗口表上下文（`kind` / `visible` / `see` /
已陈述集合），判据 1–3 各自的那一小段因此可机械判决；判不了的（近义改写）一律降级
WARN，不冒充 FAIL。

## 窗口表 schema

每个事件一个窗口；`title / say / stat` 三层分别进字幕卡的三行，`kind / visible / see` 是画面轴的读数列（`see` 只写画面里看得见的；下面文案是写法示意，不是 derby 逐字稿）：

```ts
{ key: 'w05', t0: 36, t1: 42,
  kind: 'live',       // live | replay | graphic | jump | ambient
  visible: 'event',   // event | aftermath | absent | unread
  see: '右路起球到后点，普利西奇起跳压过后卫，头球入网（远景，门后机位）',
  title: '第4分钟 · 普利西奇破门',          // 第一层：事件标题
  say: '右路起球到后点，普利西奇压着后卫起跳，头球破门——德比客场先手。', // 第二层：旁白正文（画面拍 + 落点拍）
  stat: '1-0 · 普利西奇 4\' · 助攻 莫雷拉' }  // 第三层：数据条
```

- **一窗一镜态**：窗口按镜头切点分，不按事件名字分；进球包的三段（现场 / 比分动画 / 回放）就是三个窗，信息职责不同——现场讲过程、比分动画讲数据与意义、回放讲细节，不重复同一句话；
- **阵容卡**占开球前整段（derby：0–12s），单独一张 22 人阵型卡（`kind: 'graphic'`，名字以卡片上可读的为准）；**没有可靠首发数据时只出「比分 + 赛事信息」开场卡，不编阵容**（巴萨/巴黎/利物浦实跑中，psg.fr 无阵容、PL/西甲阵容页只是可选面，均用开场卡降级）；
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
- 大段音频定位不了时用 `mix.py` 的**分轨模式**落盘逐段对齐（另带片段预览模式，先看一段再跑全片）。

## 每一步的验收判据

| 步骤 | 判据 |
|---|---|
| 定场 | fact pack 里每个字段都有来源；解析失败时退出码非零且留下原始证据（`resolve_match.py`） |
| 母版 | `find_master.py` 的第一名是**已注册官方频道**（精确 handle）、标题比分与 fact pack 一致；不足 180s 时要显式接受「成片会更短」 |
| 映射 | 比分牌读数长图逐帧目视确认；跳切点前后 MM:SS 有记录（裁窗来自 `probe_scoreboard.py` 的候选 + 人眼确认，**不抄别的联赛的数字**） |
| 事实 | 每个进球/换人/VAR 都能指到官方页条目；主帅指到 Wikipedia infobox；**该联赛不支持的轴显式标注做不到** |
| 窗口表 | `check_windows.py` 退出码 0（好表必须全过）；自检模式三条反向验证全抓 |
| TTS | 每段实测时长 ≤ 窗口；超窗压词（build_voice 退出码 0 = 全部过） |
| 成片 | ffprobe 通过（**moov atom 找不到 = 渲染被杀，重跑，不要当产物用**）；时长 = 母版时长 |
| 画面 | 抽帧复核：阵容窗口见阵容卡、每个进球窗口见进球画面；回放窗见慢放 / 不同机位；跳切窗前后比分牌时间确实跳了 |
| 画面读数 | 每窗有 `kind` / `visible` / `see`，头 / 中 / 尾三帧存档与 `see` 一致；无视觉输入时 `visible=unread` 且必须写明「画面未验收」，不能拿 WARN 当 PASS |
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

**装配脚手架（从 `multilingual-video-poetry` 抄，本 skill 不另写一套）**

- `multilingual-video-poetry/assets/example/配文.py` —— 文案与名单的单一事实源
  （窗口表 + 球员名单 + 事件表）
- `…/build_voice.py` —— edge-tts 合成 + **实测时长校窗**（重试 + 指纹缓存）
- `…/subtitles.py` —— 三层字幕 HTML → 透明层 → ffmpeg 烧录
- `…/mix.py` —— BGM + 旁白侧链混音（自带片段预览与分轨诊断两种模式）
- `…/封面.py` —— 封面（3:4，底帧选无比分牌中间态的庆祝帧）
- 底层能力：`packages/core/src/` 的 `tts` / `textlayer` / `covers` / `compose` / `audio`

**本 skill 自己的产物**

- `assets/teams.json` —— 队伍注册表（中文名 / 英文名 / 联赛 / 俱乐部 slug 与 id /
  官方集锦频道 / 品牌色 / 原声语言 / 宿敌）
- `assets/leagues.json` —— 联赛适配器（URL 模板 / 事件流形态 / VAR 是否明列 /
  母版策略 / 实测验证记录）
- `assets/action-families.json` —— 动作词族表（判据机检的受控词表，事实源唯一）
- `assets/fixtures/` —— 机检夹具：窗口表好例与三个坏例 + 三个联赛的实抓页面样本
- `scripts/resolve_match.py` —— 「当前赛季最新一场」解析器（出 fact pack + `key_events` + 来源；
  英超自动补抓 `/commentary`，巴黎自动抓 psg.fr 月度赛程 + 比赛页）
- `scripts/find_master.py` —— 官方频道集锦母版检索（候选 + 官方/比分/时长排序，`--download` 才下载）
- `scripts/probe_scoreboard.py` —— 比分牌几何探针（候选裁窗 + 竖拼长图）
- `scripts/read_scoreboard.py` —— 比分牌 OCR（逐帧分钟/比分/比分变化/跳切候选；无视觉输入时的读数替代）
- `scripts/check_windows.py` —— 三条硬判据机检（含 §6.3 反向验证；`visible=unread` 降 WARN）

**参考文档**

- [references/league-fact-sources.md](references/league-fact-sources.md) —— **四个
  目标联赛的官方事实源实测矩阵**（URL 模式、事件流形态、坑、母版策略）——先读
- [references/match-clock-mapping.md](references/match-clock-mapping.md) —— 比分牌
  映射的实测坑表（先读）
- [references/visual-commentary.md](references/visual-commentary.md) —— 进程轴 ×
  画面轴：读画面五步、六个典型场景模板、声画同步与反向验证
- `multilingual-video-poetry/references/ffmpeg-pitfalls.md` —— 音频三坑
