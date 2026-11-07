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
  narration fitted into measured windows and anchored to the frame it describes
  (absolute adelay placement, never concatenated), and assemble with burned
  captions + narration over ducked pitch-side sound — no music bed. Then close out with the two-platform deliverables: a B站
  landscape homepage image (1920×1080, every text block inside the central 4:3
  safe area) and a 抖音 portrait one (1080×1440, native 3:4), plus one
  publishing description per platform (publish-copy contract, checked by
  `feuille copy check`). Ships runnable resolvers for FC Barcelona, Liverpool,
  Borussia Dortmund and Paris Saint-Germain (latest league match, official
  highlights search included). Use when the user wants a football match
  explainer — 阵容 / 进球 / 换人 / VAR — for fans to follow the match, from a
  highlights master they supply or that exists on an official channel. The
  scoreboard-mapping method extends to other timed sports with an on-screen
  scoreboard, but league adapters and window-schema samples are football-only
  today. Not for generic live-action subtitle
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

首个完整实现是 2026-27 意甲第 10 轮米兰德比（AC米兰 3-1 国际米兰，485.48s 母版 → 8 分钟成片）。同一产线已实跑四场：`examples/klassiker-2026/`（拜仁 2-2 多特，BVB 官方 highlights 裁到 162s）、`examples/barcelona-2026/`（巴萨 6-1 阿拉维斯，192s）、`examples/psg-2026/`（勒阿弗尔 1-5 巴黎，330s）、`examples/liverpool-2026/`（利物浦 0-1 阿森纳，120s）。后三场同样无视觉输入，用 `read_scoreboard.py` OCR 读数、窗口标 `visible: unread`，画面轴待人工复核。项目产物都按内容项目落位规则放在 `usine/examples/` 下、不入库，可能已清理——**方法与实测数字已固化在本 skill 的 references 与夹具里，不依赖那些目录还在**。**装配脚手架不在本 skill 里**——从 `multilingual-video-poetry` 的入库
样例抄：`assets/example/配文.py`（文案与名单的单一事实源）· `build_voice.py`
（edge-tts 合成 + 实测校窗）· `subtitles.py`（三层字幕卡 → 透明层 → 烧录）·
`mix.py`（旁白落位 + 原声压低混音）· `封面.py`（封面）。底层能力用 `packages/core/src/`
的 `tts` / `textlayer` / `covers` / `compose` / `audio`——**本 skill 只新增赛事域的
那一层**（时间轴来源、事实源、事件轴）。

## 支持哪些球队 / 联赛

球队与联赛是**注册表**，不是正文：`assets/teams.json`（队伍，含 `default_lineup`）× `assets/leagues.json`
（联赛适配器）。新增一支球队 = 加一条注册表 + 一个联赛适配器，**不改本文件的正文**。

**默认阵容 = 五大联赛各一支**（`teams.json` 的 `default_lineup`：意甲 AC米兰 / 西甲 巴塞罗那 /
英超 利物浦 / 德甲 多特蒙德 / 法甲 巴黎圣日耳曼）。这是产品口径的默认值：`scripts/resolve_week.py`
默认就跑这 5 队。**国际米兰不在默认阵容里**——遇「米兰德比」这类同场对决，主角取主队 AC米兰。
`role=target` = 在默认阵容里，`role=baseline` = 只保留注册、默认不做。

| 队伍 | 联赛 | 官方事实源事件流 | VAR | 母版来源 | 实跑结论（2026-11-02） |
|---|---|---|---|---|---|
| AC米兰 / 国际米兰 | 意甲 | **未验证**（基线联赛，未纳入本轮实抓；`leagues.json` 里 `event_stream: unverified`） | ✗ | 官方频道 | 基线 |
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
| 7 | **母版权属口径**：母版必须来自官方频道或官方页内嵌；产物是「解说 + 标注」的评论性二创，**不搬运、不上传母版原片**；发布前过一遍平台对赛事素材的规则 | 母版是官方版权物——没有这条口径，发布就是把别人的集锦换个声音再传一遍 |

第 1 与第 3 项由 `scripts/resolve_match.py` 一步产出：它把「哪支队的哪一场」解析成
一份 fact pack（比赛页 URL + 比分 + 日期 + 事件时间线 + `key_events` + 每个字段的
来源）。母版候选由 `scripts/find_master.py` 检索（官方频道 + 比分一致性 + 时长）。
解析不出来时**退出非零并留下原始证据**，不静默兜底成默认值；比赛页抓不动、解析出
**0 条事件**（页面结构变了）、同日真冲突、候选全没有比分（未完赛，未加
`--allow-unfinished`）同样退出非零——`resolved: true` 必须意味着比赛页真的解析出来了。

官方赛程面答不出「最新一场」的联赛（实测：**法甲**），`resolve_match.py` 自动改走
**俱乐部官网 psg.fr 的月度赛程页**；`ligue1.com` 只留作阵容面。仍然解析不出来时，
才用**手动指定比赛页**兜底，用法见
[references/league-fact-sources.md](references/league-fact-sources.md) 的「巴黎怎么办」。

## 顺序不能换

```
解析「哪支队的哪一场」（fact pack）→ 官方频道检索母版候选 → 人眼确认后冻结
    → 逐秒实测「视频时间 ↔ 比赛时钟」映射
    → 官方页取事实（多页：英超 overview + /commentary）→ 交叉核对
    → 建本场名单（球衣印字 / 印字音译 / 解说称呼 / 全名）
    → 逐窗读画面（kind / visible / see + 抽帧存档）→ 双轴写事件窗口表
    → 机检三条硬判据（check_windows.py）→ 名字口径判决（check_roster.py）
    → TTS 实测校窗 → 旁白落点判决（place_voice.py：绝对锚点，不拼接）
    → 三层字幕卡 → 烧录 + 原声压低混音（无 BGM）
    → 双平台收尾：B站横版首页图 + 抖音竖版首页图（make_covers.py）
    → 双平台发布描述 + 数字溯源表 → 判据门（feuille copy check）
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
   排名输出候选裁窗，并为每个候选生成一张 1 帧/秒的**竖拼长图**（`--stitch N`
   覆盖探测窗口的**前 N 秒**，不是全片）供人眼确认。
   脚本给的是**候选 + 证据**，裁窗的最终值要人眼拍板后写进窗口表锚点。
   探针带地板：所有候选带的变化密度都低于 0.25 次/s 时输出 `found: false` 并
   **退出码 1**——这条母版里没有比分牌，没有映射基准，本 skill 对它不适用
   （退回 `multilingual-video-poetry` 的压字幕口径），不许拿噪声排名继续走。
   没有视觉输入时，用 `python3 scripts/read_scoreboard.py <母版> --from-probe probe.json`
   把读数交给本地 OCR（RapidOCR）：输出逐帧 `minute / score / texts`、比分变化
   （进球锚点）与跳切候选。两种时钟形态都认：`60'`（分钟）与 `89:58`（MM:SS——
   时钟优先于比分读法，不会把 89:58 误读成比分 89-58）。一帧分钟都没读出来 =
   裁窗不对，**退出码 1**；分钟覆盖率 < 20% 在 stderr 给警告。OCR 会把 8/6 认混，
   **比分变化必须和官方事件分钟互证**。
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
- **跨赛事（欧冠 / 欧联）**：**赛事组织者**是官方事实源——UEFA 的 `match.uefa.com/v5`
  接口（列表 + 单场）给比分、进球（精确到分秒）、球场、观众、裁判与阵容；
  `scripts/uefa_facts.py` 把它的 `playerEvents` 归一成 skill 既有的 `key_events` 形状
  （进球 / 牌 / 换人 / 点球，接口没有的轴写进 `gaps`，不静默丢弃）。**已知缺口**：本环境
  的列表接口只对 `competitionId=1`（欧冠）有数据，欧联（competitionId=2）返回空 ⇒
  欧联比赛 id 要另寻发现路径（俱乐部官网赛程面 / 官方频道视频标题反查），别假装能列全；
- **俱乐部官网是兜底面**：联赛官方站答不出时，用俱乐部的赛程页 / 比赛页 / 官方赛报——
  三类形态（客户端渲染的赛程页、内嵌 JSON 的比赛页、带 timeline 的比赛页）各站不同，
  写法与实测 URL 见 [references/league-fact-sources.md](references/league-fact-sources.md)；
  官网赛报常有「比分 + 进球 + 牌 + 首发 + 裁判 + 观众」全套，是换人 / 牌轴最可靠的来源；
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
- 球员名字**每场建一份名单**，旁白、字幕卡、封面、发布文案都从它取，不另抄；名单的契约定在本 skill（见下节「球衣印字 ≠ 解说称呼」），**poetry 的 `assets/example/配文.py` 只有文案与窗口表，没有名单 schema——别去那儿找**（这句话此前写错了）。

### 球员名单：球衣印字 ≠ 解说称呼

转播里最先被读到的是**球衣印字**（`HAKIMI`），而解说该用的是**约定俗成的称呼**（`阿什拉夫`）。照着印字写词，球迷听到「哈基米右路起球」——人没错、译音也没错，但这名球员在中文解说里不这么叫。**同一名球员有两个合法的名字，名单必须同时记下来，并指定本片口径。**

每场一份 `players.json`（与窗口表同项目）：

```json
{"players": [
  {"shirt": "HAKIMI", "shirt_zh": "哈基米", "call": "阿什拉夫",
   "full": "阿什拉夫·哈基米", "pos": "右后卫", "team": "巴黎圣日耳曼", "no": 2}
]}
```

| 字段 | 是什么 | 用在哪 |
|---|---|---|
| `shirt` | 球衣印字（原文） | **只用于对账**：读画面时核对是谁 |
| `shirt_zh` | 印字在**本片解说语**里念出来的样子（中文线就是中文音译） | 只用于判据：它出现在文本里就是念错了 |
| `call` | 本片解说语称呼 | **旁白 / 字幕卡 / 封面 / 发布文案只准用它** |
| `full` | 全名（可选） | 首现可给全名；完整出现时含印字音译不算违规 |
| `pos` / `team` / `no` | 位置 / 球队 / 号码 | 号码读不清时用位置称呼；对账 |

三条规矩：

1. **`shirt_zh == call` 的球员不触发判据**（印字就叫这个名，如 `MBAPPÉ` → 姆巴佩）；
2. **`call` 与本片解说语一致**：解说换成外文，`call` 就填该语种的称呼，名单不存"另一套旁白名"；
3. **名单不许缺 `call`**：拿球衣印字顶替称呼就是这条规则要防的事（缺字段 = 退出码 2，不静默放过）。

```bash
python3 scripts/check_roster.py --roster players.json --windows windows.json \
    --text cover_facts.json publish/bilibili.md publish/douyin.md
python3 scripts/check_roster.py selftest   # 念印字 / 首现全名 / 印字即称呼 / 缺字段
```

退出码 0 = 名字口径合规；1 = 有文本念了球衣印字（报出该用的称呼）；2 = 名单契约坏了或窗口表非法。名字是**每场比赛的事实**，本文件只定口径、不记具体球员。

## 「本周」要哪一场（默认口径）

「本周」= asof 所在自然周（周一 ~ 周日）。这一步与「当前赛季最新一场」**不是同一件事**：`resolve_match.py` 给的是该队**赛季内**最新一场已完赛（可能在上周、甚至上个月）；「本周已完成的比赛」要在这一周里筛。跨赛事（欧冠/欧联）还会让同一周出现多场——本轮 2026-11-02~11-07 就有 4 场欧冠 + 1 场欧联。

`scripts/resolve_week.py` 一条命令回答这个口径：

```bash
python3 scripts/resolve_week.py --asof 2026-11-07                      # 默认阵容 5 队，逐队给本周已完赛
python3 scripts/resolve_week.py --asof 2026-11-07 --teams milan,dortmund --out week.json
```

它把每队的本周候选（日期 / 对阵 / 比分 / 赛事 / 来源）列出来，按**开球时间取最晚的一场**（同周多场时其余进 `alternatives` 并写明原因）；数据面缺口写进 `gaps`，**不冒充「本周无已完赛」**。选哪一场要在 fact pack 里留依据，不要凭印象挑。

## 「当前赛季最新一场」怎么定（多球队产线的入口）

`scripts/resolve_match.py` 把这一步做成可复跑、可审计的脚本，而不是人工翻网页：

```bash
python3 scripts/resolve_match.py barcelona            # 默认 league 口径，真抓，出 fact pack
python3 scripts/resolve_match.py barcelona all        # 含杯赛 / 欧战口径
python3 scripts/resolve_match.py barcelona --dry-run  # 先看它打算抓哪几个面
python3 scripts/resolve_match.py barcelona --allow-unfinished  # 最新一场还没有比分时仍出 pack（带 unfinished 标记）
python3 scripts/resolve_match.py --all-targets --asof 2026-11-02 --out packs.json
                                                      # 四支目标队一次解析（巴萨/利物浦/多特/巴黎）
python3 scripts/resolve_match.py selftest             # 离线回归（不联网：解析夹具 + 判别逻辑负例）
```

参数：`resolve_match.py <队伍 key> [league|all] [基准日]`（位置参数，适合单队）；
批量用 `--targets a,b,c` 或 `--all-targets` + `--asof`。出口用 `--out <路径>`。
fact pack 里除 `latest_pick` / `match_page` 外还有 `key_events`（只留进球/换人/牌/VAR/点球/哨）
与 `event_counts`（按 kind 逐条计数），窗口表直接从 `key_events` 取。完整参数见
`python3 scripts/resolve_match.py --help`。

**母版检索**接着跑（人工确认后才冻结）：

```bash
python3 scripts/find_master.py barcelona --fact-pack packs.json   # 官方频道候选 + 排序
python3 scripts/find_master.py psg --fact-pack packs.json --download masters/
```

它读 fact pack 的「主客 + 比分」，在 YouTube 上跑两轮检索（普通 / extended），
按**官方频道、标题比分是否一致、时长、赛季年份**排序，输出候选与推荐；`--download` 才真的下载。
官方判定分两档（结果里的 `official_basis`）：`id` = uploader_id / channel_id 精确命中
注册 handle；`name` = 频道**名字**精确等于 handle（同名仿冒号也能过，结果会带警告，
冻结前核对频道 id）。频道名的后缀变体（handle+official/tv/fc）**不算官方**——起名就能
满足的条件挡不住仿冒；`Sky Sports Premier League` 这类媒体号不会被误判成官方。
标题里出现**不在本赛季**的年份（如往季同名对阵的 `2022/23`）会被压到后面。
排名第一也仍要人眼核对标题与频道；脚本给的是证据，不是拍板。

**频道身份以实测 `uploader_id` 为准。** 注册表里的 handle 可能写错（本轮实测：意甲那支
的 `youtube` 写的是 `@ACMilanOfficial`，真身是 `@ACMilan`；`@ACMilanOfficial` 没有 videos
tab，yt-dlp 会直接报 `This channel does not have a videos tab`——这个报错就是「handle 写错了」
的信号，不是「频道不存在」）。冻结母版前按 `uploader_id` 核一遍，别拿注册表当证据。

**官方俱乐部的高光通常很短。** 俱乐部官方频道的单场高光实测常在 **130–200s**（不足 180s
就要显式接受「成片会更短」并写进交付说明）；20 分钟量级的 EXTENDED HIGHLIGHTS 多在
**官方联赛频道**（如 `@seriea`）。持权转播商（TUDN / CBS Golazo 等）也有长版，但**不是官方
俱乐部 / 联赛频道**，按母版权属口径只能当候选、不能当官方母版。

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

**三条硬判据已经有机检。** `references/visual-commentary.md` §6.3 要求「注入坏例，
判据必须全部抓到」——`scripts/check_windows.py` 就是那份坏例的载体（坏例 A/B/C 是
三个语义坏例，D 是 jump 窗 `see` 混进动作词；另有输入契约：空表、`kind` / `visible`
枚举笔误一律退出码 2，不进判据、更不冒充 PASS）：

```bash
python3 scripts/check_windows.py selftest      # 反向验证：好表全过 + 四个坏例全抓 + 输入契约
python3 scripts/check_windows.py windows.json   # 判决窗口表（FAIL 退出码 1；坏表退出码 2）
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
  anchor: 37.4,       // 旁白要对齐的那一帧：动作起手（缺省 = t0）
  align: 'start',     // start（起句对齐）| end（收句对齐，卡片短窗用）
  see: '右路起球到后点，普利西奇起跳压过后卫，头球入网（远景，门后机位）',
  title: '第4分钟 · 普利西奇破门',          // 第一层：事件标题
  say: '右路起球到后点，普利西奇压着后卫起跳，头球破门——德比客场先手。', // 第二层：旁白正文（画面拍 + 落点拍）
  stat: '1-0 · 普利西奇 4\' · 助攻 莫雷拉' }  // 第三层：数据条
```

- **一窗一镜态**：窗口按镜头切点分，不按事件名字分；进球包的三段（现场 / 比分动画 / 回放）就是三个窗，信息职责不同——现场讲过程、比分动画讲数据与意义、回放讲细节，不重复同一句话；
- **时间区间写 `t0` / `t1`**（本 schema 的正式字段）；机检也认装配脚本沿用的紧凑写法 `src`（`"36.2-42.0"`），两处同给时 `t0`/`t1` 优先。`kind` / `visible` 是受控枚举，写错会**退出码 2**（不是 FAIL、更不是 PASS）；
- **`anchor` / `align` 是声画对齐的两个字段**：`anchor` 落在本窗区间内（出窗 = 表写错，退出码 2），`align` 只认 `start` / `end`。它们是 `place_voice.py` 的输入，不是文案装饰——写错就等于认了「声音和画面对不上」；
- **jump 窗的 `see` 只写读数**（比分牌 69:46 → 73:26、「无换人镜头」），不写动作词——机检判据 3 对 `see` 与 `say` 都扫动作细节词；
- **回放窗可以引用本事件的时间 / 比分**（「第 4 分钟那个球」）——「观众已经知道的」包括 `title` / `stat` 卡说过的，机检的已陈述集合含这三层；
- **阵容卡**占开球前整段（derby：0–12s），单独一张 22 人阵型卡（`kind: 'graphic'`，名字以卡片上可读的为准）；**没有可靠首发数据时只出「比分 + 赛事信息」开场卡，不编阵容**（巴萨/巴黎/利物浦实跑中，psg.fr 无阵容、PL/西甲阵容页只是可选面，均用开场卡降级）；
- 旁白落点由 `place_voice.py` 判决（见下节）：`start` 对齐时起句在 `anchor + LEAD`（0.45s），`end` 对齐时收句在 `anchor`；
- **TTS 时长是实测的**：每段合成后立刻量，超窗压词不硬塞（build_voice 报
  每段 slack，超窗退出码 1）；
- 结尾必有一段「回顾」窗口（全场进球 / 换人次数汇总），球迷的收获沉淀在这。

## 旁白落点：绝对锚点，不按顺序拼接

`t0` 说的是「这一镜从哪开始」，旁白要对齐的却是「这一镜里动作的那一帧」。一个 6s 的镜头里起球可能在 `t0+2s`、球过线在 `t0+4s`：旁白一律贴 `t0` 进，结果词就抢在画面前面（**早了**）；窗口紧的时候又把 LEAD 静默回贴到 `t1 - 时长`，同一句话反而拖到动作之后（**晚了**）。四场实跑的「有的早、有的晚」不是两个毛病，是同一条规则在两种窗型下的两个极端。

四条规矩，全部由 `scripts/place_voice.py` 机检：

1. **绝对时间**：每段起点钉在时间线上（`adelay`）。**不许按顺序拼接**（`concat` / 累加时长）——一段的误差会累加到后面每一段，片子越长偏得越多；
2. **`anchor` 是画面锚点**，`align` 决定对齐哪一头：

   | align | 落点 | 用在 |
   |---|---|---|
   | `start`（缺省） | 起句 = `anchor + LEAD` | 现场 / 跳切 / 氛围：动作起手时开口 |
   | `end` | 收句 = `anchor` | 比分动画 / 图形页等短卡片窗：话收在画面上那一下 |

   回放窗把 `start` 的 anchor 往后放 0.3–0.5s（先让观众认出「这是回放」），不另设 lead 参数；
3. **LEAD 固定、不静默回贴**：放不下就是 FAIL。修法只有压词或拆窗，**不许挪落点**——挪了就没有「对齐」这回事；
4. **一段不许越过 `t1`、也不许起在 `t0` 之前**：越界就是旁白压到下一镜的画面上。

```bash
# voice-report.json 是 build_voice 的实测产物：{"segments":[{key,file,duration}]}
python3 scripts/place_voice.py plan --windows windows.json \
    --voice voice-report.json --total 162 --out place.json
python3 scripts/place_voice.py plan ... --chain-only   # 只打印 ffmpeg 链
python3 scripts/place_voice.py selftest                # 早 / 晚 / 叠音 / 缺段的反向用例
```

`place_voice.py` 同时生成混音链（旁白绝对落位 + 原声被旁白侧链压低，见「装配」）。退出码 0 = 落点全部合法；1 = 越界 / 叠音 / 缺段；2 = 输入坏了（缺 `--total`、窗口表非法、voice-report 读不动）。

⚠️ 本线的 `voice-report.json` 按**窗口 key** 出（`{"segments":[{key,file,duration}]}`），不是 poetry 样例里 `lang/season` 的形状——抄 `build_voice.py` 时把循环换成遍历窗口表，别让两套 key 对不上（对不上时 `place_voice.py` 报「缺实测音频」退出码 1）。

## 双语字幕卡（解说语 + 中文）

一条成片的**旁白是什么语言，字幕就必须是那个语言**。原来三层卡写死中文，解说换成外文
就变成「听得懂英文、看的是中文字幕」——两头别扭，字幕等于没有。

所以卡片分两种版式（`render_cards.py` 的 `LAYOUTS`）：

| 版式 | 何时 | 层 |
|---|---|---|
| `mono` | 解说语 == 中文 | `title` / `say` / `stat` 三层，**逐坐标与现有着色卡一致**（578 / 682 / 912）——已有成片不变形 |
| `bilingual` | 解说语 ≠ 中文 | 解说语 `title`（白大）/ `say`（金大）+ **中文 `zh`（淡小）** + `stat` |

**解说语 == 中文时不出中文层**（同一句话印两遍是噪音）。**不做平台字幕文件（.txt）**——
平台字幕轨与卡片是两回事。

四条纪律：

1. **版式是数据**（`LAYOUTS` 逐层声明 `top` / `h` / `size` / `color` / `weight`），不是代码里写死的坐标。`h` 只参与判据、不进渲染 HTML ⇒ 调 `h` 改判据口径，画面不变。
2. **`h` 按实测反推**（单行实测高 + 2px 余量），不按估算。踩过的坑：按估算写 60/66 ⇒ **14 个语种全报「超出声明盒」而画面没问题**——那是「判据比被改进对象更严」，改的是声明盒不是画面。
3. **排版判据用实测层盒**（浏览器量出的文本高度），不是字符数估算——外文比中文长 1.5–2 倍，德/法/俄的 `say` 实测折两行（119px vs 英文 60px），希伯来/阿拉伯还多一层行距。
4. **字体栈与书写方向取 `languages/<locale>/manifest.json`**（唯一事实源，不另抄）：`fontCss` / `displayFontCss` / `dir`（`ar-SA`、`he-IL` = rtl）。中文辅助层恒 `ltr`，不管解说语是不是 RTL。

```bash
python3 scripts/render_cards.py --windows windows.json \
    --i18n i18n.json --lang en-US --out cards
python3 scripts/render_cards.py --i18n assets/fixtures/i18n/bilingual-cards.json \
    --lang all --out build/cards     # 注册表 14 语种全覆盖
python3 scripts/render_cards.py --selftest
```

**覆盖 `languages/` 注册表全部 14 语种**（ar-SA / de-DE / el-GR / en-US / es-ES / fr-FR /
he-IL / hi-IN / it-IT / ja-JP / ko-KR / ru-RU / zh-CN / zh-HK）——能力夹具
`assets/fixtures/i18n/bilingual-cards.json` 给出同一窗口在 14 语种下的解说语文案。

**脚本分工照 `make_covers.py` 的先例**：Python 只做编排 + 判据，渲染交给 TS 运行时
（`pnpm exec feuille textlayer shoot`，一次运行同时出双 matte 与实测层盒，测量不额外
花一次浏览器启动）。**输入契约**：解说语窗口表缺窗口 ⇒ 退出码 2，不拿别的语言文案顶替。

完整契约——版式表、`h` 的定法、实测层高表（14 语种）、坑表、已知缺口——见
[references/bilingual-cards.md](references/bilingual-cards.md)。

## 装配（沿用 multilingual-video-poetry，不另写）

- 三层字幕卡 = 透明 PNG 逐张 overlay 串接烧录；**卡片走单帧输入，不加
  `-loop 1`**——53 张卡就是 53 路 × fps 的无限 PNG 解码，实测 65s 预览
  5 分钟不出片；overlay 默认 `eof_action=repeat` + `enable=between(t,…)` 足够；
- **混音只有两层，没有 BGM**：中文旁白（loudnorm −16 LUFS）> 母版现场原声（观众 / 客场解说，压低保留作氛围）。**赛事线的底就是真实比赛的声音**——音乐床是教学线的做法，铺上来会盖掉进球瞬间的声浪，也让「这是真实比赛」这件事失真。`bgm-bed` 与本线无关，不要接回来；
- 链由 `place_voice.py` 生成（`--chain-only` 直接可跑）：**输入 `0` = 母版（含原声），`1..N` = 旁白段**（按落点先后）；每段按 `anchor` 用 `adelay` 钉在绝对时间上 → `amix` → `loudnorm` → `asplit=2` → 原声 `volume` 压低（缺省 0.14，**换片重测**）→ `sidechaincompress` → 合并 → `alimiter`。三个经典音频坑（`asplit` 缺失 / `loudnorm` 排序 / 结尾余量）见 `multilingual-video-poetry` 的 references，**不要在这里复写**；
- **原声电平用成片轨量出的旁白电平定**（旁白 − 原声 ≥ 8 dB，LUFS 口径；loudnorm 后语音段比单段 mp3 高 ~6.9 dB，口径混了会白调）；
- 大段音频定位不了时用 `mix.py` 的**分轨模式**落盘逐段对齐（另带片段预览模式，先看一段再跑全片）；`mix.py` 的 BGM 模式（`user` / `a|b|c`）**本线不用**。

## 双平台收尾：发布描述 + 首页图

成片是**同一条横版**（16:9）。收尾出两个平台的发布物，各两件：

| 平台 | 首页图 | 发布描述 |
|---|---|---|
| B站 | **横版 16:9**（1920×1080），文字块整体落在**中央 4:3 安全区**（x 240–1680）——平台首页推荐按 4:3 裁、个人空间按 16:9 裁，两个框都得有字 | `publish/bilibili.md`（标题 / 简介 / 标签 / 发布贴士，标题 ≤80 字） |
| 抖音 | **竖版 3:4**（1080×1440），**零裁切**——竖封面槽的原生比例（传 9:16 会被居中裁掉上下各 240px，标题带正好被切没）；16:9 画面完整内嵌 + 模糊铺底，比分牌留在画内 | `publish/douyin.md`（文案 / 话题 / 发布贴士，首行即标题 ≤30 字，末话题后留一个尾随空格） |

```bash
python3 scripts/make_covers.py --pack packs/barcelona.json --facts cover_facts.json \
    --master master.mp4 --backdrop-time 42.5 --out build/cover --name barcelona-alaves
python3 scripts/build_publish_facts.py --pack packs/barcelona.json \
    --video build/final.mp4 --master master.mp4 --windows windows.json --out publish/facts.json
pnpm exec feuille copy check publish/ --platform bilibili,douyin --facts publish/facts.json
```

**只查这两个平台**：成片是横版，小红书吃竖屏，本线**不投小红书**——判据门用 `--platform bilibili,douyin` 挑要查的（不给就是三平台齐为硬门，缺 `xiaohongshu.md` 会判 FAIL，那一行与稿子质量无关）。

三条纪律：

1. **数字不许编**：封面上的比分对着 fact pack 校（不符 → 退出码 1）；文案里每个数字对着 `facts.json` 溯源（没出处 → 判红）。**fact pack 没解析出比赛就不许出封面**（没有事实源的封面比没有封面更糟）。
2. **底图不许带字幕**：从**无字幕母版**抽帧——成片已烧了三层字幕卡，再叠封面标题就是两层字打架。
3. **文字不许落在安全区外**：版式是**数据**（`make_covers.py` 的 `LAYOUTS`：画布 / 安全区 / 四行文字块的盒子与字号），越界由 `assert_layout` 判，`selftest` 有反向用例盯着。

样例见 `assets/publish/`（《巴萨 6-1 阿拉维斯》成稿 + 配套事实表，两份都能过判据门）。完整契约——两道比例门的口径差、抖音封面「发布后补」与每支 5 次修改额度、B站合集 Lv2 门槛、**两平台存草稿的落点差异与封面安全区**、已知缺口（本轮不做竖版成片）——见 [references/publishing-and-covers.md](references/publishing-and-covers.md)。

## 每一步的验收判据

| 步骤 | 判据 |
|---|---|
| 定场 | fact pack 里每个字段都有来源；解析失败时退出码非零且留下原始证据（`resolve_match.py`）：比赛页抓不动 / 解析出 0 条事件 / 同日真冲突 / 未完赛未加 `--allow-unfinished` 都算失败；`cross_checked` 只有当选中这场被 ≥2 个面印证时才是 true |
| 母版 | `find_master.py` 的第一名是**已注册官方频道**（`official_basis` = id 或精确频道名）、标题比分与 fact pack 一致；basis=name 或出现后缀变体警告时，冻结前核对频道 id；不足 180s 时要显式接受「成片会更短」 |
| 映射 | 探针 `found: true`（无比分牌 = 退出码 1，本 skill 对这条母版不适用）；比分牌读数长图逐帧目视确认；跳切点前后 MM:SS 有记录（裁窗来自 `probe_scoreboard.py` 的候选 + 人眼确认，**不抄别的联赛的数字**）；OCR 分钟覆盖率 < 20% 有警告、零读数退出码 1 |
| 事实 | 每个进球/换人/VAR 都能指到官方页条目；主帅指到 Wikipedia infobox；**该联赛不支持的轴显式标注做不到** |
| 窗口表 | `check_windows.py` 退出码 0（好表必须全过）；自检模式四个坏例 + 输入契约全抓；空表 / 枚举笔误 / `anchor` 出窗 / `align=end` 缺锚点 = 退出码 2，不算过 |
| 名单 | `check_roster.py` 退出码 0：每名球员都有 `shirt` / `shirt_zh` / `call`；旁白 / 字幕卡 / 发布文案里没有把球衣印字当称呼（`shirt_zh ≠ call` 时，印字只准完整出现在 `full` 里）；自检模式的念印字 / 首现全名 / 印字即称呼 / 缺字段 / 称呼重复全抓 |
| TTS | 每段实测时长 ≤ 窗口；超窗压词（build_voice 退出码 0 = 全部过） |
| 旁白落点 | `place_voice.py plan` 退出码 0：每段都落在 `anchor` 上（`start` 起句 / `end` 收句）、不早于 `t0`、不越过 `t1`、两段不叠音；自检模式「拼接漂移 / 早 / 晚 / 叠音 / 缺段」全抓。**落点靠 `adelay` 绝对钉位，不按顺序拼接** |
| 成片 | ffprobe 通过（**moov atom 找不到 = 渲染被杀，重跑，不要当产物用**）；时长 = 母版时长 |
| 画面 | 抽帧复核：阵容窗口见阵容卡、每个进球窗口见进球画面；回放窗见慢放 / 不同机位；跳切窗前后比分牌时间确实跳了 |
| 画面读数 | 每窗有 `kind` / `visible` / `see`，头 / 中 / 尾三帧存档与 `see` 一致；无视觉输入时 `visible=unread` 且必须写明「画面未验收」，不能拿 WARN 当 PASS |
| 声画对账 | `say` 的每个动作短语能在同窗 `see` 找到主体；回放窗无新进程、跳切窗无动作细节（三条反向验证全抓，见 references）；**成片抽听**：每句的第一个字落在 `place.json` 的 `start` 上（偏差 > 0.2s = 重跑落点，不要靠耳朵调） |
| 混音 | 两层（旁白 + 原声，**无 BGM**）：`feuille poetry audio-profile` 配比判据：人声段 − 原声空档 ≥ 8 dB（LUFS 口径）；成片里听不到音乐床（有床 = 混错了，`bgm-bed` 的产物不该进这条线） |
| 双语卡 | `render_cards.py --lang all` 退出码 0：注册表 **14 语种**每种都出卡，且**每一层的实测高度都在自己的声明盒里**（层高超出 / 压到下一层 / 拿不到实测盒都算失败）；`cards-report.json` 落盘；`--selftest` 反向用例全抓。解说语 == 中文时**不许出中文层**（同一句话印两遍） |
| 收尾 | 首页图两张：B站 1920×1080（文字块在中央 4:3 安全区内）+ 抖音 1080×1440（零裁切），尺寸由脚本自检、**展示裁切靠 `preview_*.png` 人眼判**；发布描述两份 `publish/bilibili.md` / `publish/douyin.md` 过 `feuille copy check --platform bilibili,douyin --facts publish/facts.json`（0 违规；数字溯源 SKIP 不算过） |

⚠️ **渲染被中断的 mp4 是半成品**：ffmpeg 中途被杀（会话结束、断电）留下
没有 moov atom 的文件，ffprobe 直接报 Invalid data。判定口径只有 ffprobe，
不看文件大小（270 MB 的「大文件」照样是废片）。

## 边界

- 装配机制（TTS 校窗 / 三层烧录 / 落点判决 / 封面规范）→ `multilingual-video-poetry`
  （本 skill 是它在赛事域的特化：时间轴来自**比分牌映射 + 官方事件**，
  不是场景美学）
- **母版里没有比分牌**（`probe_scoreboard.py` 输出 `found: false`、退出码 1）→
  退回 `multilingual-video-poetry`：没有「视频时间 ↔ 比赛时钟」的映射基准，
  就只能做压字幕，做不了进程轴解说
- 出母版（无现成集锦、要生成画面）→ `video-generation`；但**官方集锦优先**——
  生成画面出不了真实比赛
- **本线不铺 BGM**：音乐床是教学线的做法（`bgm-bed` 只服务配文 / 教学成片）。赛事线的底是母版现场原声，铺音乐会盖掉进球声浪、也让真实比赛失真——这条线**不要**往 `bgm-bed` 路由
- 发布词 → `publish-copy`（本 skill 给的是**赛事域事实面与平台配对**，写与判都归它：
  `feuille copy check --platform bilibili,douyin`）；发布执行 → `multilingual-video-publishing`
  （永不自动，用户喊了才发）
- 首页图的**版式与取帧**归本 skill（`make_covers.py`），**渲染机制**归 library 的 `core.covers`
  （`feuille cover make`）——本 skill 不另写渲染器
- 泛化到其他运动：比分牌映射法适用于任何**带屏幕比分牌的计时运动**
  （篮球 / 网球…），但事实源与窗口 schema 的样例目前只有足球——
  换运动先重新探针比分牌几何，且联赛适配器要新写（`leagues.json` 里没有）

## 代码归属

拥有模块：（无）

本 skill 只有说明书与 skill 内脚本（`scripts/` 下十二个 Python：resolve_match / resolve_week / uefa_facts / find_master / probe_scoreboard / read_scoreboard / check_windows / place_voice / check_roster / make_covers / build_publish_facts / render_cards，每个都带离线 selftest）——装配层与封面、发布词判据的底层能力全在 **library**（`tts` / `textlayer` / `covers` / `compose` / `audio` / `copy`），与 `multilingual-video-poetry`、`publish-copy` 共用；本 skill 不拥有任何 packages/ 模块。事实源见 `usine/ownership.json`，由 @feuille/gate 的 vitest 门禁（`pnpm verify`）与本段双向机检。

## Requirements (fresh machine)

- **Python ≥ 3.10**（脚本用了 `str | None` 等语法）。本线的十二个脚本是 skill 内 Python，不进 packages/——与 `multilingual-video-poetry` 的装配脚手架同一口径，运行入口就是 `python3 scripts/…`（各脚本自带 `selftest` 子命令，不需要网络）。
- **ffmpeg / ffprobe**（PATH，或 `FEUILLE_FFMPEG` / `FEUILLE_FFPROBE` 指路径）：探针、抽帧、读数、首页图底图与裁切预览都要。
- **Node ≥ 24 + pnpm**（`pnpm exec feuille …`）：首页图渲染走 `feuille cover make`（封面机制在 library 的 `core.covers`，本 skill 不另写渲染器）；发布描述判据走 `feuille copy check`。
- **Edge 或 Chrome**（PATH，渲字必需）：封面上的中文标题由浏览器渲——`core.covers` 经 `core.platform` 解析浏览器路径，探测不到就显式失败，不静默换人。
- **firecrawl**（PATH）：四个联赛页面都是 JS 渲染，直连只能拿到壳（`resolve_match.py` 内置滚动抓取）。
- **yt-dlp**（PATH）：`find_master.py` 的检索与 `--download`。
- **rapidocr_onnxruntime**（可选，`pip install rapidocr_onnxruntime`）：只在**无视觉输入**时给 `read_scoreboard.py` 用；`selftest` 不需要它。
- 一条命令跑全验收：`python3 scripts/verify_all.py [--windows windows.json]`——十二个 selftest（+ 可选窗口表判决）聚合退出码，缺环即非零，不靠 agent 逐条记得跑。

## Resources

**装配脚手架（从 `multilingual-video-poetry` 抄，本 skill 不另写一套）**

- `multilingual-video-poetry/assets/example/配文.py` —— 文案与窗口表的单一事实源（窗口表 + 文案；**不含球员名单**——名单契约在本 skill）
- `…/build_voice.py` —— edge-tts 合成 + **实测时长校窗**（重试 + 指纹缓存）
- `…/subtitles.py` —— 三层字幕 HTML → 透明层 → ffmpeg 烧录
- `…/mix.py` —— 混音链（自带片段预览与分轨诊断两种模式）；**本线只用它的分轨 / 预览模式，不用 BGM 模式**（赛事线不铺音乐床）
- `…/封面.py` —— 封面（3:4，底帧选无比分牌中间态的庆祝帧）
- 底层能力：`packages/core/src/` 的 `tts` / `textlayer` / `covers` / `compose` / `audio`

**本 skill 自己的产物**

- `assets/teams.json` —— 队伍注册表（中文名 / 英文名 / 联赛 / 俱乐部 slug 与 id /
  官方集锦频道 / 品牌色 / 原声语言 / 宿敌）
- `assets/leagues.json` —— 联赛适配器（URL 模板 / 事件流形态 / VAR 是否明列 /
  母版策略 / 实测验证记录）
- `assets/action-families.json` —— 动作词族表（判据机检的受控词表，事实源唯一）
- `assets/publish/` —— 赛事域发布描述**成稿样例** + 配套事实表（`bilibili.md` / `douyin.md` / `facts.example.json`；两份稿都能过 `feuille copy check --platform bilibili,douyin`）
- `assets/fixtures/` —— 机检夹具：窗口表好例与四个坏例（A/B/C 语义坏例 + D：jump 窗 `see` 混动作词）+ 四个联赛的实抓页面样本
- `scripts/resolve_match.py` —— 「当前赛季最新一场」解析器（出 fact pack + `key_events` + 来源；
  英超自动补抓 `/commentary`，巴黎自动抓 psg.fr 月度赛程 + 比赛页；
  比赛页失败 / 0 事件 / 真冲突 / 未完赛都退出非零；`selftest` 含判别逻辑负例）
- `scripts/resolve_week.py` —— 「本周已完赛」口径解析器（asof 所在自然周；默认跑 `teams.json`
  的 `default_lineup` 五队；逐队给本周候选与选取依据；数据缺口写 `gaps`，不冒充「本周无已完赛」；
  `--selftest` 离线回归）
- `scripts/uefa_facts.py` —— 欧战事实源（UEFA v5 单场 / 列表接口 → skill 的 `key_events` 形状：
  进球 / 牌 / 换人 / 点球，带分钟与来源 URL；接口没有的轴写进 `gaps`；未识别的
  `playerEvents` 子键原样报出、不静默丢弃；`--selftest` 离线回归）
- `scripts/find_master.py` —— 官方频道集锦母版检索（候选 + 官方/比分/时长/赛季年排序，
  `official_basis` 分 id/name 两档并带仿冒警告；`--download` 才下载；`--selftest` 离线回归）
- `scripts/probe_scoreboard.py` —— 比分牌几何探针（候选裁窗 + 竖拼长图 + 无比分牌地板 `found`；
  `selftest` 用 lavfi 合成视频离线回归）
- `scripts/read_scoreboard.py` —— 比分牌 OCR（逐帧分钟/比分/比分变化/跳切候选；`60'` 与 `89:58` 两种时钟都认；零读数退出码 1；`selftest` 纯函数回归，不需要 OCR 依赖）
- `scripts/check_windows.py` —— 三条硬判据机检（含 §6.3 反向验证 + 输入契约；`visible=unread` 降 WARN；`anchor` / `align` 进契约）
- `scripts/check_roster.py` —— 球员名单名字口径判决：`shirt`（球衣印字）/ `shirt_zh`（印字音译）/ `call`（解说称呼）/ `full`（全名）；`shirt_zh ≠ call` 时印字不许出现在旁白 / 字幕卡 / 发布文案（首现全名例外）；`selftest` 含念印字 / 缺字段 / 称呼重复的反向用例与 CLI 真路径（落盘 → 读回 → 判决）
- `scripts/place_voice.py` —— 旁白落点判决：绝对锚点（`anchor` + `align` start/end）、起句不早于 `t0`、收句不越 `t1`、不叠音；同时生成**无 BGM** 的混音链（旁白 `adelay` 钉位 + 原声侧链压低）；`selftest` 含拼接漂移 / 早 / 晚 / 叠音 / 缺段的反向用例
- `scripts/make_covers.py` —— 双平台首页图（B站 1920×1080 + 抖音 1080×1440）：版式是数据（`LAYOUTS` 带安全区）、数字对着 fact pack 校、底图从无字幕母版抽、出裁切预览；`selftest` 含版式越界与事实对账的反向用例
- `scripts/build_publish_facts.py` —— 发布描述的数字溯源表（fact pack + ffprobe + 窗口表 → `facts.json`；每一项都有出处，不许手填）
- `scripts/render_cards.py` —— 双语字幕卡（解说语 + 中文）：版式是数据（`LAYOUTS` 的 mono / bilingual）、字体栈与书写方向取 `languages/<locale>/manifest.json`、排版判据用**实测层盒**（`textlayer shoot` 同一次运行出图 + 量盒）；`--lang all` 覆盖注册表 14 语种；`--selftest` 含版式越界与缺测量的反向用例
- `scripts/verify_all.py` —— 一条命令跑全验收（十二个 selftest + 可选窗口表判决，聚合退出码）

**参考文档**

- [references/league-fact-sources.md](references/league-fact-sources.md) —— **四个
  目标联赛的官方事实源实测矩阵**（URL 模式、事件流形态、坑、母版策略）——先读
- [references/match-clock-mapping.md](references/match-clock-mapping.md) —— 比分牌
  映射的实测坑表（先读）
- [references/visual-commentary.md](references/visual-commentary.md) —— 进程轴 ×
  画面轴：读画面五步、六个典型场景模板、声画同步与反向验证
- [references/publishing-and-covers.md](references/publishing-and-covers.md) —— 双平台
  收尾契约：发布描述的事实面与钩子、首页图两版规格与安全区、两道比例门的口径差、
  抖音封面后补与修改额度、存草稿模式的两平台落点差异、已知缺口（本轮不做竖版成片）
- [references/bilingual-cards.md](references/bilingual-cards.md) —— 双语字幕卡契约：
  版式表（mono / bilingual）、`h` 按实测反推、14 语种实测层高表、坑表、已知缺口
- `multilingual-video-poetry/references/ffmpeg-pitfalls.md` —— 音频三坑
