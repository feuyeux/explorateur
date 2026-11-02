# 联赛事实源实测矩阵

**这份文档回答一个问题**：想给某联赛的球队做「当前赛季最新一场」，它的**官方站点到底
能给什么、不能给什么**。结论不是「都能」，是**分层的**——照抄意甲的做法去做法甲会翻车。

实测日期：**2026-11-02**（2026-27 赛季进行中）。抓取方式：`firecrawl scrape`（四个
联赛页面都是 JS 渲染的，直连只能拿到壳）。机检夹具在 `assets/fixtures/pages/`。

---

## 0. 一句话结论

| 联赛 | 比赛页 URL 模式 | 事件流形态 | VAR | 母版从哪来 | 可用性 |
|---|---|---|---|---|---|
| **西甲** | `laliga.com/{lang}/match/temporada-{赛季}-{赛事}-{主}-{客}-{id}` | `structured` | ✅ 明列 | 官方频道里找 | ★★★★★ |
| **英超** | `premierleague.com/en/match/{id}/{主}-vs-{客}` | `commentary`（事件在 `/commentary`，需滚动） | ❌ | 比赛页内嵌 | ★★★★☆ |
| **德甲** | `bundesliga.com/en/bundesliga/matchday/{赛季}/{轮}/{主}-vs-{客}/liveticker` | `structured_liveticker` | ❌ | liveticker 页内 / 官方频道 | ★★★★☆ |
| **法甲** | `ligue1.com/.../match_{id}` + **psg.fr 比赛页** | `commentary`（psg.fr） | ✅ psg.fr 明列 | Ligue 1 / PSG 官方频道 | ★★★★☆（阵容仍弱） |

**事件流形态**是这份矩阵里最要紧的一列：

- `structured` —— 逐分钟结构化，一行一分钟 + 一行事件句（`Goal!` / `Substitution,` /
  `is shown the yellow card` / `VAR Decision:`）。**解析器能直接吃。**
- `commentary` —— 逐分钟文字直播：事件句 + 分钟行。页面可能是虚拟列表（英超要滚动）
  或分月赛程（巴黎要按月抓）。进球/换人/牌/VAR 都能从正文读出来。
- `structured_liveticker` —— liveticker 里进球是 `## GOAL!` 块（分钟 + 射手 + 比分 +
  Assist），换人是 `#### Substitution`，牌是黄/红牌图标；`#### 编辑标题` 只是叙述素材。
- `prose` —— overview 页只有叙述稿与内嵌集锦；逐分钟事件在另一个标签页。
- `narrative` —— 标题是**编辑文案**，没有结构化字段（旧结论；德甲已升级）。
- `none` —— 事件藏在图标图例后面，抓下来的 markdown 里**没有可用事件流**。

---

## 1. 西甲（LaLiga EA SPORTS）—— 最好用的一家

### URL 模式

```
比赛页   https://www.laliga.com/en-GB/match/temporada-2026-2027-laliga-ea-sports-fc-barcelona-deportivo-alaves-11
俱乐部   https://www.laliga.com/en-GB/clubs/fc-barcelona
下一场   https://www.laliga.com/en-GB/clubs/fc-barcelona/next-matches
```

主客 slug 用 `-` **直接相连**，没有 `vs` 分隔符；赛事段用官方小写名
（`laliga-ea-sports`、UCL 用 `ucl`）。

> ⚠️ `/clubs/{slug}/matches` 子路径**实抓是 404**，别写进脚本当入口。用俱乐部主页或
> `/next-matches`。

### 比赛页给什么

头部是**位置结构**（不是关键词结构）——按位置读：

```
Full Time
Raphinha 8' 41' … Mariano 84'      ← 射手行
SAT 31.10.2026                      ← 日期
16:00 h                             ← 开球
Spotify Camp Nou                   ← 球场
53,523 \*                          ← 上座
Adrián Cordero Vega …                ← 裁判组（主裁 + 助理 + VAR）
Matchday 11                         ← 轮次
FC Barcelona / 4-3-3                ← 阵型
Trainers → Hansi Flick, Sanchez Flores
Starters / Substitutes              ← 首发 / 替补（号码 + 名字）
```

事件流逐分钟一行：

```
84'
Goal! Barcelona 6, Alaves 1. Mariano Díaz (Alaves) right footed shot …
82'
Substitution, Barcelona. Gerard Martín replaces Frenkie de Jong.
64'
VAR Decision: Goal Barcelona 5-0 Alaves (Lamine Yamal).
64'
Goal! Barcelona 5, Alaves 0. … Goal awarded following VAR Review.
60'
Pablo Ibáñez (Alaves) is shown the yellow card.
```

**四个事件轴（进球 / 换人 / 牌 / VAR）全部齐**，且 VAR 是**独立事件行**——这正是
意甲工作流要的东西。

### 两个必须注意的坑

1. **事件流是倒序的**（84' → 8'）。按文档顺序取最后一个进球会拿到 1-0 而不是 6-1。
   必须**按分钟取最大**。
2. **比分不在头部**：头部只给射手行。比分要从**分钟最大的进球事件**的
   `Goal! Barcelona 6, Alaves 1.` 里反解。

### 赛程面：两个都是管道表格

```
俱乐部   https://www.laliga.com/en-GB/clubs/fc-barcelona/results
联赛总表 https://www.laliga.com/en-GB/laliga-easports/results
```

一行一场，列是管道分隔：

```
| SAT 31.10.2026 | 16:00 | [FC Barcelona](…)<br>6<br>\- <br>1<br>[Deportivo Alavés](…) | LALIGA EA SPORTS | - | [比赛页](…) |
```

三个坑，都实测踩过：

1. **两种拼法别混**：路径用 `laliga-easports`（easports 连写），**比赛 URL 里用
   `laliga-ea-sports`**（带连字符）。写错会 404。
2. **俱乐部 /results 页可能不含最新一轮**：实抓巴萨俱乐部页最新只到 10-25
   （对皇马），而 10-31 对阿拉维斯那场只在联赛总表里。所以**两个面都要跑，
   取并集**再定最新。
3. **两个面的列含义不同**：俱乐部页那一列是**赛事名**，联赛总表那一列是
   **主裁姓名**。认不出赛事就留空——填成假值会把正确的候选筛掉
   （这正是 `--scope league` 会误杀总表里巴萨那场的原因）。

### 母版

比赛页**不内嵌**集锦视频 URL（只有图片 + 官方频道入口）。母版要去
`https://www.youtube.com/user/laliga` 按队名 + 比分找。

---

## 2. 英超（Premier League）—— 母版最省事，事件要换标签页

### URL 模式

```
赛季赛程 https://www.premierleague.com/en/matches/premier-league/2026-27
俱乐部   https://www.premierleague.com/en/clubs/14/matches      （club id 是数字）
比赛页   https://www.premierleague.com/en/match/2645281/liverpool-vs-arsenal/overview
标签页   /overview /highlights /lineups /stats /commentary /info
```

`match_id` 是数字，赛程页与比赛页共用。slug 用 `-` 连接，主客之间固定 `vs`。

### 比赛页给什么

- **比分**藏在图片 alt 里：`LIV 0-1 ARS`（不是独立的 `0-1` 行）；
- **日期与球场连在同一行**：`Sun 01 NovAnfield`；下一行是主裁（`Andy Madley`）；
- **官方集锦直接内嵌**：`https://www.youtube.com/watch?v=…`（英超官方频道）——
  overview 一步拿到母版；
- overview 页只有叙述稿 + 集锦；**逐分钟事件在 `/commentary`**。

### `/commentary` 的抓法与版式

`/commentary` 是**虚拟列表**：firecrawl 不滚动只能抓到末尾几条，必须
`--actions` 先 wait 再 scroll 两次（`resolve_match.py` 已内置）。抓到后的版式是：

```
- 16'

### Goal

Liverpool 0 - 1 Arsenal
…
Goal! Liverpool 0, Arsenal 1. Kai Havertz (Arsenal) left footed shot … Assisted by Declan Rice.

- 15'

Attempt missed. Declan Rice (Arsenal) …
```

两个方向都可能出现：**普通解说句的分钟行在事件后面**；带 `### Goal` /
`### Substitution` / `### Yellow Card` 标题的块，**分钟行在事件前面**。
解析器按「块里有没有 `###` 标题」判归属，不能一律按前或按后。

实测（2026-11-02，Liverpool 0-1 Arsenal）：16' Havertz（助攻 Rice）、9 次换人、
8 张牌全部取出。VAR 仍不单列，正文里的 VAR 句只能当线索。

### 赛程面的选择

- **赛季页**（`/en/matches/premier-league/2026-27`）带日期 + `FT` + 比分 → 主面。
  日期有相对写法（`Yesterday` / `Today`），解析器按 asof 换算；
- **俱乐部页**（`/en/clubs/14/matches`）的结果行**没有日期**（只有 `MW 9`），
  往回找 80 行会串到上面赛程的 `Sun 08 Nov`。解析器对俱乐部页只看紧邻 8 行，
  找不到就留空——它的作用只是发现 URL，不负责定序。

### VAR

英超官方页**不单独列 VAR 判决**。判罚要读 `/commentary` 全文，不要从赛果反推。

---

## 3. 德甲（Bundesliga）—— 赛程面最省事，进球是结构化块

### URL 模式

```
俱乐部   https://www.bundesliga.com/en/bundesliga/clubs/borussia-dortmund/matches
全赛程   https://www.bundesliga.com/en/bundesliga/matchday/2026-2027/borussia-dortmund
比赛页   https://www.bundesliga.com/en/bundesliga/matchday/2026-2027/8/fc-bayern-muenchen-vs-borussia-dortmund/liveticker
```

`matchday` 是**轮次数字**（8），不是比赛 id。俱乐部 id 形如 `DFL-CLU-000007`。

### 赛程面给什么（德甲最省事的一处）

俱乐部页的「Fixtures & Results」块直接给出**日期 + 比分 + 轮次 + 比赛页链接**：

```
Saturday 31 October
FC Bayern München   2 - 2   Borussia Dortmund
[Highlights Matchday 8: …]
```

### 事件流：进球/换人/牌都有结构化节点

**旧结论「进球分钟抓不到」是错的。** liveticker 的编辑标题（「Dortmund level!」）
确实只是叙述，但同一条目下面跟着结构化进球块：

```
89'

### [Fabio Silva](…/player/fabio-silva)

## GOAL!

2:2

Assist: [K. Karetsas](…)
```

换人是 `#### Substitution` + 球员头像/文字链接（in / out），牌是
`![yellowCard]` / `![redCard]` 图标 + 球员链接。`#### 编辑标题` 保留为 `editorial`
事件，写画面轴时可用，但**不要拿它当进球分钟的事实源**。

实测（2026-11-02，Bayern 2-2 Dortmund）：4 个进球全部取出
（38' Laimer、60' Guirassy、66' Upamecano、89' F. Silva），8 次换人、3 张牌；
比分从终场标题 `Full time: Bayern 2-2 Dortmund` 还原，球场 Allianz Arena、
主裁 Tobias Stieler 也可读。集锦在 liveticker 页内是 JWPlayer（poster 形如
`assets.bundesliga.com/video/jw/peGVWUsv.jpg`），YouTube 上另有官方频道版。

VAR 仍不单列；正文里提到 VAR 的句子（「VAR spotted a foul」）只能当线索。

### 母版：官方 highlights 可能带采访

2026-11-02 实跑（Bayern 2-2 Dortmund）：BVB 官方 highlights 原片 362.94s，
前 162s 是集锦本体，之后是球员采访（视频描述里有「I'm glad I was able to help」）。
**先确认哪一段是集锦**，用比分牌最后一次可读 + 场景切点判断，再裁掉采访；
否则窗口表会排到采访画面上。

---

## 4. 法甲（Ligue 1 McDonald's）—— ligue1.com 不行，psg.fr 行

### 两套 URL，各管一段

```
ligue1.com（阵容/阵型面）
  俱乐部   https://ligue1.com/en/club-sheet/l1_championship_club_2026_13
  赛程     https://ligue1.com/en/club-sheet/l1_championship_club_2026_13/calendar
  比赛页   https://ligue1.com/en/match-sheet/l1_championship_match_73421
  标签页   /summary /formations /stats /highlights

psg.fr（发现面 + 事件面）
  月度赛程 https://www.psg.fr/en/mens-football/fixtures?period=Oct
  比赛页   https://www.psg.fr/en/matches/mens-football/20262027/le-havre-vs-paris-2026-10-30
```

- `club_id` 与**赛季**绑定在 ligue1.com 的 URL 里：`l1_championship_club_2026_13`
  = 26/27 赛季的巴黎；⚠️ **`club_id 90` 是巴黎 FC（升班马）**，不是巴黎圣日耳曼；
- psg.fr 的 URL 带**真实日期**（`...-2026-10-30`），比赛页标题也写
  `Friday 30 October 2026`。

### ligue1.com 仍然不给的两样东西

| 面 | 给什么 | 缺什么 |
|---|---|---|
| 俱乐部页「Calendar」段 | 只有**未赛场次**（`L1 - GW.10 - Friday 6`） | 已赛场次没有日期 |
| 俱乐部页「Recent results」段 | 5 个比分（`1 - 2`、`3 - 1` …） | **不带日期**，没有排序键 |
| 比赛页 `/summary` | `17 May 2026 - D.34` | 这是**该轮名义日期**，不是开球日 |
| 比赛页 `/summary` | 阵容 / 阵型 / 数据 / 积分 | **进球时间线不在**（事件藏在图标图例后） |

所以 `resolve_match.py` **不拿 ligue1.com 定「最新」**；它只把 ligue1.com 当阵容面。

### psg.fr 给的两样关键数据

**(1) 月度赛程页 = 发现面。** 每场一块：

```
## Le Havre AC vs Paris Saint-Germain - 30 October 2026 - 19:00
[…]（比赛页链接，带日期）
L1
Matchweek 9
![Le Havre logo](…)Le Havre1
![Paris logo](…)Paris5
FRIDAY OCTOBER 30 202619:00
Stade CMA CGM Océane
```

日期、赛事码（L1 / UCL / CDF…）、比分、球场、比赛页链接都在。赛程按**月**分片，
`resolve_match.py` 自动抓当前月 + 前两个月，取并集后按日期定序。

**(2) 比赛页 = 事件面。** 有完整逐分钟文字直播（Opta 式）：

```
69'

Goal! Le Havre 1, Paris Saint Germain 5. Achraf Hakimi (Paris Saint Germain) with an attempt …

55'

VAR Decision: Goal Le Havre 1-2 Paris Saint Germain (Achraf Hakimi).

87'

Substitution, Paris Saint Germain. David Boly replaces Achraf Hakimi.
```

进球（射手/助攻/赛后比分）、换人、VAR 判决都能读；主裁形如 `Ref:FrançoisLetexier`
（页面把空格压掉，解析器在驼峰处补空格）。**唯一缺口是阵容**：psg.fr 比赛页只有
「Lineups are announced…」占位，没有首发/替补/阵型——这仍要回 ligue1.com 的
match-sheet。

### 控件顺序仍然不可信

巴黎的 ligue1.com 俱乐部页上：轮播区首位是 `HAC vs. PSG`；「Recent results」首个
比分是 `1 - 2`；「Match summaries」最新视频是 `PSG vs. OL (2 - 0)`。**三个控件互相
指不到同一场。** psg.fr 的月度赛程页解决了排序键问题，但「按日期定序」这条纪律不变：
没有日期的候选不参与评选。

### 巴黎怎么办（现行流程）

1. `python3 scripts/resolve_match.py psg` —— 自动抓 psg.fr 当前月 + 前两个月，
   出 fact pack（含 `key_events`、比赛页 URL、日期、比分）；
2. 阵容/阵型另取 `ligue1.com` match-sheet（fact pack 的 `lineups_note` 会提醒）；
3. 母版用 `find_master.py` 在 **Ligue 1 McDonald's 官方频道（@Ligue1）** 找，
   标题形如「LE HAVRE AC - PARIS SAINT-GERMAIN (1-5) | Week 9」；PSG 官方频道
   （@PSG）多为片段；
4. 手动指定比赛页仍可用 `--match-url` 兜底。

---

## 5. 「当前赛季最新一场」本身有歧义

口径不同，答案就不同：

| 口径 | 巴萨 | 利物浦 | 多特 | 巴黎 |
|---|---|---|---|---|
| 只看联赛 | 6-1 阿拉维斯（10-31，第 11 轮） | 0-1 阿森纳（11-01，第 9 轮） | 2-2 拜仁（10-31，第 8 轮） | 1-5 勒阿弗尔（10-30，第 9 轮） |
| 含杯赛 / 欧战 | 同上 | 联赛杯 1-1 切尔西（点球 6-5，10-28） | 德国杯 3-2 云达不来梅（10-27） | 欧冠 D.3 4-2 巴萨（10-20）；下一场 11-03 对比利亚雷亚尔 |

**这不是细节，是解说叙事的分岔**：利物浦的「最新一场」若是联赛杯点球大战，解说轴
是点球；若是联赛，则是 0-1 主场负。`resolve_match.py --scope league|all` 把这个
选择显式化，不替你猜。

---

## 6. 新增一支球队要做什么

1. `assets/leagues.json` —— 若该联赛还没有适配器，加一条（URL 模板 / 事件流形态 /
   VAR 是否明列 / 母版策略）。**先实抓验证再写**，并把验证日期与样例记进
   `verified`。
2. `assets/teams.json` —— 加一条：中文名、英文名、`league`、俱乐部 slug 与 id
   （**这两项各联赛含义不同**：英超是数字 id、法甲是赛季绑定的 id、德甲是
   `DFL-CLU-…`、西甲是 slug）、官方集锦频道、品牌色、原声语言、宿敌表。
3. 跑 `python3 scripts/resolve_match.py <key> --dry-run` 看它打算抓哪几个面；
   再跑真抓，核对 fact pack 的每个字段是否可解析。德甲/英超的 fact pack 会带
   `lineup_url`（liveticker→/lineup、overview→/lineups）；阵容仍要单独取。
4. 跑 `python3 scripts/resolve_match.py selftest` 与
   `python3 scripts/check_windows.py selftest`（回归）。
5. 跑 `python3 scripts/find_master.py <key>` 看官方频道候选是否排得出来；
   第一名不是官方频道或比分对不上，说明 `official_channels` 或检索词要改。

**不要**把球队专有事实（某场比分、某个进球分钟）写进 `SKILL.md` 或
`teams.json` —— 那是**每场比赛的事实**，走官方比赛页。注册表只放**不随比赛变的
东西**：URL 模式、频道、队色、口径。

---

## 7. 抓不动就明说

`assets/leagues.json` 的 `event_stream` 字段就是这件事的机检版：解析器在 fact pack
里写明这个联赛的事件流形态，`capability_report()` 对 `var_exposed=false` 的联赛
输出警告。**事实源能力不足时要显式降级，不要用二手数据悄悄补齐** —— 编出来的
解说比没有解说更糟。

---

## 8. 母版检索：官方频道优先，比分是硬判据

`find_master.py` 用 yt-dlp 的 `ytsearch` 跑两轮（普通 / extended），把候选按三件事排序：

1. **官方频道**（+100）：只认精确的 `uploader_id` / `channel_id`。子串匹配会把
   `Sky Sports Premier League` 误判成官方，已经用精确 handle 修掉；
2. **标题比分与 fact pack 一致**（+30；写反了 −50）：同名对手、反向比分（1-0 vs 0-1）
   在搜索结果里很常见；
3. **时长**（300–1500s +20）：8 分钟成片需要母版有足够素材；不足 180s 会显式警告。

各队实际排到的官方频道：

| 队伍 | 官方频道 handle | 备注 |
|---|---|---|
| 巴塞罗那 | `@FCBarcelona` / `laliga` | LALIGA EA SPORTS 的 3 分钟集锦通常排第一 |
| 利物浦 | `@LiverpoolFC` / `premierleague` | overview 内嵌的官方视频可作交叉核对 |
| 多特蒙德 | `@BVB` / `@bundesliga` | BVB 官方 6 分钟版通常排第一 |
| 巴黎 | `@Ligue1` / `@PSG` | Ligue 1 官方单场集锦（约 5.5 分钟）比 PSG 片段完整 |

⚠️ 排名只是证据，不是拍板。公共搜索结果会变，频道也可能仿冒；`--download`
只在显式要求时执行，下载后仍要人眼确认是这一场（比分牌 / 队徽 / 日期）。
