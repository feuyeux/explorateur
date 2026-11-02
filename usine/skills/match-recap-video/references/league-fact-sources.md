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
| **英超** | `premierleague.com/en/match/{id}/{主}-vs-{客}` | `prose`（事件在 `/commentary`） | ❌ | 比赛页内嵌 | ★★★★☆ |
| **德甲** | `bundesliga.com/en/bundesliga/matchday/{赛季}/{轮}/{主}-vs-{客}/liveticker` | `narrative`（编辑文案标题） | ❌ | liveticker 页内 | ★★★☆☆ |
| **法甲** | `ligue1.com/en/match-sheet/l1_championship_match_{id}` | `none` | ❌ | `/highlights` 标签页 | ★★☆☆☆ |

**事件流形态**是这份矩阵里最要紧的一列：

- `structured` —— 逐分钟结构化，一行一分钟 + 一行事件句（`Goal!` / `Substitution,` /
  `is shown the yellow card` / `VAR Decision:`）。**解析器能直接吃。**
- `prose` —— overview 页只有叙述稿与内嵌集锦；逐分钟事件在另一个标签页。
- `narrative` —— 标题是**编辑文案**（「Dortmund level!」「Off the bar!」），不是
  `Goal: Silva 88'`。进球分钟抓不到结构化字段。
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
  四个联赛里**只有英超能一步拿到母版**；
- overview 页只有叙述稿 + 集锦；**逐分钟事件在 `/commentary`**。

### 赛程面的选择

- **赛季页**（`/en/matches/premier-league/2026-27`）带 `FT` 与比分 → 用它；
- **俱乐部页**（`/en/clubs/14/matches`）只有赛程**与结果页**（无比分）→ 兜底。

### VAR

英超官方页**不单独列 VAR 判决**。判罚要读 `/commentary` 全文，不要从赛果反推。

---

## 3. 德甲（Bundesliga）—— 赛程面最省事，事件流最弱

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

### 事件流：只有换人是结构化的

liveticker 的标题是**编辑文案**，不是事件行：

```
90' + 4
#### Off the bar!
Almost a last-gasp winner for Bayern as Karl strikes the crossbar …

87'
#### Substitution
```

结构化标题只有 `Substitution`、`Full time: Bayern 2-2 Dortmund`。**进球分钟与 VAR
判决抓不到结构化字段**——`#### Dortmund level!` 这类标题不标分钟归属，需要人工读，
或改走 DFL 的 `bapi.bundesliga.com` 数据层。

比分可以从终场标题 `Full time: Bayern 2-2 Dortmund` 还原。

---

## 4. 法甲（Ligue 1 McDonald's）—— 最弱的一家

### URL 模式

```
俱乐部   https://ligue1.com/en/club-sheet/l1_championship_club_2026_13
赛程     https://ligue1.com/en/club-sheet/l1_championship_club_2026_13/calendar
比赛页   https://ligue1.com/en/match-sheet/l1_championship_match_73421
标签页   /summary /formations /stats /highlights
```

- `club_id` 与**赛季**绑定在 URL 里：`l1_championship_club_2026_13` = 26/27 赛季的巴黎；
- ⚠️ **`club_id 90` 是巴黎 FC（升班马），不是巴黎圣日耳曼**。搞混会整条线跑到另一支队。

### 事件流：抓不到

`/summary` 页抓下来的 markdown 里，事件藏在**图标图例**后面（`But +` / `But -`），
只剩「Summary」里零星几条（实测只出现 `A. Gory 76'` 一条）。阵容 / 阵型 / 数据 /
积分都在，**进球时间线不在**。

→ 法甲要事件级事实，得改用**俱乐部官网**（psg.fr）或 LFP 数据层，不要硬啃
ligue1.com。

### 更硬的一层：「本赛季最新一场」**答不出来**

这比「事件流弱」更致命。实测三个面：

| 面 | 给什么 | 能定「最新一场」吗 |
|---|---|---|
| 俱乐部页「Calendar」段 | 只有**未赛场次**（`L1 - GW.10 - Friday 6`、`LDC - D.4 - today`） | ❌ 全是未来的 |
| 俱乐部页「Recent results」段 | 5 个比分（`1 - 2`、`3 - 1` …）**不带日期** | ❌ 没有排序键 |
| 比赛页 `/summary` | `17 May 2026 - D.34` —— 这是**该轮的名义日期**（第 34 轮），不是实际开球日 | ❌ 同一轮的所有比赛共用一个日期 |

也就是说：**ligue1.com 上没有任何一个面能给出「某一场实际是哪天踢的」**。
`resolve_match.py` 因此对巴黎直接报「候选里没有可排序的最新已完赛」并退出非零，
而不是猜一个——**这是设计内的失败，不是 bug**。

### 控件顺序会骗人（这条是血泪）

巴黎的俱乐部页上：

- 轮播区首位是 `HAC vs. PSG`；
- 「Recent results」首个比分是 `1 - 2`；
- 而「Match summaries」里最新的官方集锦视频是 `PSG vs. OL (2 - 0)`（6 天前），
  另一个是 15 天前的 `RCSA 1-3 PSG`。

**三个控件互相指不到同一场。** 所以「最新一场」**只能按日期定序**，页面顺序一律
不信 —— 这条已经写进 `scripts/resolve_match.py` 的 `select_latest`：没有日期的候选
不参与评选，并被原样报出来。

### 巴黎怎么办（三条路，按推荐顺序）

1. **手动指定比赛页**（最快）：
   `python3 scripts/resolve_match.py --team psg --match-url "<match-sheet URL>"`。
   比赛页能给阵容、阵型、数据、积分；**事件时间线仍然没有**。
2. **换俱乐部官网**（psg.fr）：当轮赛果与首发通常带真实日期。
3. **换 LFP / MPG 数据层**：结构化、有日期，但抓取方式与本文档其余部分不同。

---

## 5. 「当前赛季最新一场」本身有歧义

口径不同，答案就不同：

| 口径 | 巴萨 | 利物浦 | 多特 | 巴黎 |
|---|---|---|---|---|
| 只看联赛 | 6-1 阿拉维斯（10-31，第 11 轮） | 0-1 阿森纳（11-01，第 9 轮） | 2-2 拜仁（10-31，第 8 轮） | 见下 |
| 含杯赛 / 欧战 | 同上 | 联赛杯 1-1 切尔西（点球 6-5，10-28） | 德国杯 3-2 云达不来梅（10-27） | 欧冠 D.4 vs 比利亚雷亚尔（11-02 当天） |

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
3. 跑 `python3 scripts/resolve_match.py --team <key> --dry-run` 看它打算抓哪几个面；
   再跑真抓，核对 fact pack 的每个字段是否可解析。
4. 跑 `python3 scripts/check_windows.py --selftest`（回归）与本 skill 的门禁。

**不要**把球队专有事实（某场比分、某个进球分钟）写进 `SKILL.md` 或
`teams.json` —— 那是**每场比赛的事实**，走官方比赛页。注册表只放**不随比赛变的
东西**：URL 模式、频道、队色、口径。

---

## 7. 抓不动就明说

`assets/leagues.json` 的 `event_stream` 字段就是这件事的机检版：解析器在 fact pack
里写明这个联赛的事件流形态，`capability_report()` 对 `var_exposed=false` 的联赛
输出警告。**事实源能力不足时要显式降级，不要用二手数据悄悄补齐** —— 编出来的
解说比没有解说更糟。
