---
type: "Content"
title: "示范场景二《说到颜色，你会想到什么》：六色一来一往（内容 · 语气 · 场景 · casting）"
description: "班底第二个示范场景：红蓝绿黄黑白六个基本颜色词 + 联想问答。结构共享（开场提议 → 六轮一来一往 → 开心再会），剧本按语种独立原生创作——每语种用自己的惯用问句句式、本文化的联想物与自洽的舞台道具，禁止从任何语言（包括中文）互译派生。含 14 语种原生剧本、zh-CN course.json 种子示例、六色词表（对照参考），直接按 plan.md §6 casting 范式接入 M2 管线。"
tags: [content, scene, colors, vocabulary, dialogue, multilingual, teaching-video]
generated: { by: dsh/fuyao-work, at: 2026-10-03 }
inputs:
  - plan.md                       # §6 示范场景范式（casting/幕×说话人/三区布局）、§4.1 情绪分支表、§8.2 音频契约
  - self-introductions.md         # course.json 种子体例与文本原则
  - requirement.md                # 三区布局（文字/气泡/人物）
---

# 示范场景二《说到颜色，你会想到什么》

> **学习目标**：6 个基本颜色词（红 · 蓝 · 绿 · 黄 · 黑 · 白）＋一组联想问答。
> **结构（全语种共享的骨架，且仅骨架共享）**：开场提议 → **六轮一来一往**（奇数轮 A 问 B 答、偶数轮 B 问 A 答）→ 开心再会。
> **剧本（每语种独立原生创作）**：问句句式、联想物、幽默、舞台道具全部在语种内自洽——见 §1.2 独立创作四原则。
> **管线**：M2（`parse_scene.py --scene colors` → `scene_video.py --scene colors`，[plan.md §6](../docs/plan.md) casting 范式）；台词带 `speaker` 标签即 course.json 种子，人物/模板零改动（plan.md §3 原则六）。本 md 即场景唯一事实源：§0 机读规格（token/RTL/装置）+ §2 台词 + §5 词表，新场景照抄体例即可零代码接入。

## 0. 场景规格（机读体例——parse_scene.py 只认本节 + §2 台词体例 + §5 词表）

> **新教学场景 = 新建 `scene-<id>.md` 照抄本节体例，管线零改动**：`parse_scene.py --scene <id>` →
> `.\run.ps1 scene -Scene <id>`。教学 token、RTL 语种、每语种舞台装置全部由剧本自带，不进代码
> （「场景是数据不是代码」，与亮相卡的「人设是数据」同一条原则）。
> chip 两型：`#hex` = 色片（实心填充）；`"文本"` = 字牌（Edge 渲文字层贴入井内）。
> 装置规格表 locale 缺行 = 该语种无装置纯对话。§5 词表列序必须与本节 token 书写序一致。

sceneId: colors-association
title: 说到颜色，你会想到什么
rtlLocales: ar-SA, he-IL
durationBudget: 40-55

### 0.1 教学 token（书写序 = 出场序）

| key | chip |
| --- | --- |
| red | #D8453B |
| blue | #4657D8 |
| green | #1E9E6E |
| yellow | #D9A62E |
| black | #26262E |
| white | #F5F3EE |

### 0.2 舞台装置规格（style = scene_video.py 样式库；well 缺省由场景中性色推导）

| locale | scenes | style | shape | cellW | cellH | well | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zh-CN | arch_windows, table, shelf | palette | circle | 118 | 118 | | 六格调色盘 |
| en-US | shopfront, awning, counter | chalkboard | round | 128 | 104 | #5C6660 | 门口小黑板 |
| fr-FR | shopfront, stairs, window | bookspine | rect | 104 | 168 | | 橱窗六色书脊 |
| de-DE | mountains, trail, signpost | signpost | round | 136 | 62 | | 指路牌柱六色小牌 |
| es-ES | awning_market, crates, fruit_balls | fruit_basket | circle | 120 | 108 | | 六个果筐 |
| ru-RU | tree, shrubs, water | chalk_stone | circle | 112 | 112 | | 石板路上六色粉笔圈 |
| el-GR | water, masts, bench | doorframe | rect | 100 | 172 | | 码头漆色门框 |
| ar-SA | lantern_row, awning, counter | lanterns | circle | 108 | 116 | | 一排六色小灯笼 |
| hi-IN | brick_arches, columns, plant | rangoli | circle | 104 | 104 | | rangoli 六色彩粉 |
| ja-JP | shopfront, wires, lantern | traffic_lamp | circle | 92 | 120 | | 信号灯与六色街灯 |
| ko-KR | fence, sky_dusk, bunting | cone | poly | 112 | 120 | | 六只训练锥 |
| it-IT | fountain, awning, counter | gelato | round | 124 | 108 | | gelato 柜六色 |
| he-IL | skyline, clothesline, shrubs | dyed_cloth | rect | 116 | 150 | | 晾绳六块染布 |
| zh-HK | stall, neon_sign, window_grid | neon | round | 128 | 92 | #605862 | 六块 neon 小招牌 |

### 0.3 语种文本规范（qa_scene.py 验收用——本表承诺的语体差必须在台词里真实成立）

文化注记里写了「语体差本身就是关系戏」，就必须在文本层能验出来，否则注记是空头支票。
本表把这类承诺声明成数据：验收时逐行检查 A 线不含 `区分标记`、B 线必含该标记。
无语体差需求的语种不列行（缺行 = 不检查，不是「通过」）。

| locale | 语体 A | 语体 B | 区分标记 | 说明 |
| --- | --- | --- | --- | --- |
| ko-KR | 반말 | 해요체 | 요 | 도윤 반말 × 서연 敬语体（§6 变位与语体） |

> 标点不用声明、按文字系统自动判：疑问句终止符必须用该文字自己的问号
> （希腊文 U+037E），半角分号在任何现代正字法里都不是句终止符，撞上即判错
> （el-GR 曾用 U+003B 收 7 个疑问句，TTS 会读成陈述句）。

## 1. 规格总则

### 1.1 幕次骨架（全语种共享——共享的只有骨架）

| 幕 | 内容 | 问者 | 答者 | 颜色 |
| --- | --- | --- | --- | --- |
| 一 | 开场：提议玩颜色游戏 | A | B | — |
| 二 | 第一问 | A | B | 红 |
| 三 | 第二问 | B | A | 蓝 |
| 四 | 第三问 | A | B | 绿 |
| 五 | 第四问 | B | A | 黄 |
| 六 | 第五问 | A | B | 黑 |
| 七 | 第六问 | B | A | 白 |
| 八 | 开心再会 | A → B | A | — |
| 逐词解释 | 元语言讲解（汉语） | 旁白（`zh-CN-YunyangNeural`，非班底、无立绘） | — | 六色轮转 |

- 问答对称性：A 问三色（红/绿/黑）、答三色（蓝/黄/白）；B 问三色（蓝/黄/白）、答三色（红/绿/黑）。**六色零遗漏、零重复**。
- 与示范场景一的差异：场景一 A 恒为求知者、B 恒为向导；本场景**双方互问互答**——A（活泼）是先问方与节奏引擎，B（沉稳）的提问短而稳，一来一往即戏剧张力。

### 1.2 一骨架、十四个剧本——独立创作四原则（本场景核心规则）

联想问答的答案没有"标准答案"，只有"哪里的答案"。因此本场景**不做主稿＋翻译**：十四个语种是十四个独立剧本，zh-CN 只是其中之一，不是母本。

1. **句式原生**：问句/答句用该语言的惯用表达，不从任何语言直译。对照例——英语 *what comes to mind*、韩语「～하면 떠올라」、粤语「講到…諗到啲乜」、日语「～って言ったら、思い浮かべる」。回译检查：任何一行译回任一其他语种，不得得到可逐词对上的句子。
2. **联想物原生**：答案取该语言文化的原生意象（灯笼、黑森林、太极旗、青信号、复活节红蛋、利是……），**不得**跨语种对齐"同一批事物"。六个答案的挑选本身就是各语种的教学内容。
3. **彩蛋与笑点原生**：幽默挂在各自班底的档案彩蛋上（zh 版指搭档夹克、de 版 weiß「白/知道」双关、ar 版 ليلى 之名本义即「夜」、ja 版 リク 面瘫自指头发）——一个语种的梗不需要也不应该有跨语种对应物。
4. **舞台原生**：每语种独立设计主场与"当前色高亮"道具装置（§2 各节「舞台」行）——颜色游戏发生在该文化自己的场景里：市场果筐、徒步黄标、gelato 柜、neon 招牌……不共用一套布景。

汉字文化圈（zh-CN/zh-HK）互相也不作对齐：普通话版与粤语版零共用台词，句式与用词各按各的口语体写。

### 1.3 语气映射（全语种共享，plan.md §4.1 共享表，有效参数 = 基线 + 增量）

| 行型 | A（活泼） | B（沉稳） |
| --- | --- | --- |
| 提议/问句 | `happy`（兴奋抛题） | `neutral`（稳稳接题） |
| 答句 | `happy`（联想开花） | `neutral` → 末句 `encouraging` |
| 再会 | `happy` | `encouraging`（回礼） |

句内不换情绪（单段合成）；幕八 A 的总结句与再会句可按句分段。缓存键含 mood 合成参数（plan.md §8.2）。

### 1.4 文本与时长原则（承 self-introductions.md §1.4/§1.5）

A1 词汇为主，单句 4–12 词；全片估算 40–55s（以 tts 实测为准；超时回改文本，绝不调基线，不变量 2）；手势词必须真实出现在该语种该行台词里（否则回退行首）；罗马注音永不入音；句尾 0.6–0.8s 呼吸位；六色取教学 token（红 `#D8453B`、蓝 `#4657D8`、绿 `#1E9E6E`、黄 `#D9A62E`、黑 `#26262E`、白 `#F5F3EE`），属场景 token，不进人物色板；道具描边只用 `pal["ink"]`（不变量 5）。

### 1.5 布局（requirement.md §1，全语种共享）

问句亮思考气泡（色名预览），答句亮提示气泡（联想物提示）；A/B 交替镜像尾巴；色名逐词高亮与道具高亮同轴（词级时间戳一轴三用）。ar-SA/he-IL 文字区右起、名牌镜像、站位对调；女性观众变体（`_f.mp4`）按 亮相卡 §1.4 规则另计缓存键。

## 2. 十四语种原生剧本

体例：台词 = 原文（*注音*）——中文对照。注音承 [kb/AGENTS.md](../../kb/AGENTS.md)：谚文/假名/天城文/阿/希按书写单元连字分段，俄/希腊连续转写，粤拼带调值；拉丁字母语种（en/fr/de/es/it）不注音；对照仅供阅读理解，永不入音。casting 规则承 plan.md §6.1：**A = 活泼者**（先问方、节奏引擎），**B = 沉稳者**（短问稳答）；「同学」等舞台关系以 [personas.json](../personas/personas.json) `relation` 为准，舞台设定不改基型关系。

### 2.1 汉语 zh-CN｜林小满 × 江远

**舞台**：放学后的美术教室。**道具装置**：长桌上一只六格调色盘，每轮问答对应颜料格弹起一格（bounce）。

- **A**（happy）：「江远江远！放学别走——我们来玩个颜色游戏吧！」｜`bounce-in` 入场，「游戏」处 `both-hands`
- **B**（neutral）：「好。怎么玩？」｜`nod`
- **A**（happy）：「说到红色，你会想到什么？」｜「红色」处 `point`（指红色颜料格）
- **B**（neutral）：「我会想到——过年的灯笼。」｜「灯笼」处 `palm-open`；红格弹起｜⚑红灯笼＝春节意象——红色在华文化主「喜庆」，不主「危险」
- **B**（neutral）：「说到蓝色呢？」｜`point`（蓝格）
- **A**（happy）：「我会想到天空！还有你的外套！」｜「外套」处 `point`（指 B 的夹克）——班底彩蛋：江远夹克 `#35486E`｜⚑「外套」的答案指向搭档真实色板——班底彩蛋，换角即失效
- **A**（happy）：「说到绿色，你会想到什么？」｜`point`（绿格）
- **B**（neutral）：「我会想到草地。」｜「草地」处 `palm-open`；绿格弹起
- **B**（neutral）：「说到黄色呢？」｜`point`（黄格）
- **A**（happy）：「我会想到银杏叶！」｜「银杏叶」处 `both-hands`（比小扇子）；黄格弹起｜⚑银杏＝城市秋日限定意象——zh 版联想全走本土生活
- **A**（happy）：「说到黑色，你会想到什么？」｜`point`（黑格）
- **B**（neutral）：「我会想到夜晚。」｜「夜晚」处 `palm-open`；黑格弹起
- **B**（neutral）：「说到白色呢？」｜`point`（白格）
- **A**（happy）：「我会想到雪！」｜「雪」处 `mini-jump`；白格弹起——六格全亮
- **A**（happy）：「六个颜色，都问完啦！真好玩！」｜「都问完」处 `jump-celebrate`（squash-stretch）
- **B**（encouraging）：「明天见。」｜`wave`
- **A**（happy）：「明天见！」｜`wave`＋蹦跳出画；B 收调色盘、关灯淡出

**文化注记**：红→灯笼（春节）、黄→银杏叶（秋日城市）——zh 版自有意象；「外套」彩蛋仅当答案指向搭档真实色板时保留（§6 验收）。

### 2.2 英语 en-US｜Miles × Ruby（街坊）

**舞台**：打烊前的街角咖啡馆。**道具装置**：店门口小黑板——每轮 Ruby 用对应色粉笔写下当前色词，「当前色被写出来」即高亮。

- **A**（happy）："Hey Ruby! One last game before you close — the color game!" ——嘿 Ruby！打烊前最后一局——颜色游戏！｜`bounce-in`，"game" 处 `both-hands`
- **B**（neutral）："Fine. How does it work?" ——行。怎么玩？｜`nod`
- **A**（happy）："What comes to mind when I say... 'red'?" ——我说"red"（红色）时，你会想起什么？｜"red" 处 `point`｜⚑问句用惯用语 what comes to mind，不是「说到」直译
- **B**（neutral）："Stop signs. And fire trucks." ——停车牌。还有消防车。｜"signs" 处 `palm-open`；粉笔写下 red
- **B**（neutral）："And 'blue'?" ——那"blue"（蓝色）呢？｜`point`
- **A**（happy）："The sky! And my camera strap!" ——天空！还有我的相机背带！｜"strap" 处 `point`——班底彩蛋：Miles 相机带钴蓝 `#4657D8`
- **A**（happy）："'Green'?" ——"green"（绿色）呢？｜`point`
- **B**（neutral）："My apron, obviously." ——我的围裙，明摆着。——冷幽默｜"apron" 处 `palm-open`——班底彩蛋：Ruby 围裙墨绿 `#2E6B57`
- **B**（neutral）："'Yellow'?" ——"yellow"（黄色）呢？｜`point`
- **A**（happy）："Yellow cabs! I once took one to the wrong airport." ——黄色出租车！我有次坐它坐错了机场。｜"cabs" 处 `scratch-head`｜⚑yellow cab＝纽约黄色出租车——配「坐错机场」是都会冷笑话
- **A**（happy）："'Black'?" ——"black"（黑色）呢？｜`point`
- **B**（neutral）："Black coffee. No sugar." ——黑咖啡。不加糖。——馆主本色｜"coffee" 处 `palm-open`｜⚑black coffee 指「不加奶糖」——这里的黑是浓度，不是色调
- **B**（neutral）："'White'?" ——"white"（白色）呢？｜`point`
- **A**（happy）："Snow! Snowball fight tomorrow?" ——雪！明天打雪仗？｜"Snow" 处 `mini-jump`
- **A**（happy）："All six colors! That was fun!" ——六个颜色全说完啦！真好玩！｜"six" 处 `jump-celebrate`
- **B**（encouraging）："Sure. See you tomorrow, Miles." ——好啊。明天见，Miles。｜"tomorrow" 处 `wave`
- **A**（happy）："See you!" ——明天见！｜`wave`＋蹦跳出画

**文化注记**：问句用惯用语 *what comes to mind*（非「说到」直译）；意象全美式（fire truck / yellow cab / black coffee）；两条班底色板彩蛋全在馆内道具上。

### 2.3 法语 fr-FR｜Chloé × Théo（同楼邻居）

**舞台**：黄昏的书店门口台阶。**道具装置**：橱窗里立着六本书脊各一色的书，每轮抽亮一本。

- **A**（happy）：« Théo ! On joue au jeu des couleurs avant la nuit ? » ——Théo！天黑前来一局颜色游戏？｜"couleurs" 处 `both-hands`｜⚑on＝口语泛指「我们」，日常法语替代 nous 的首选
- **B**（neutral）：« Pourquoi pas. Comment on joue ? » ——为什么不。怎么玩？｜`nod`
- **A**（happy）：« Quand je dis "rouge"... tu penses à quoi ? » ——我说"rouge"（红色）……你会想起什么？｜"rouge" 处 `point`｜⚑口语问句不倒装；书面须 « Penses-tu… » 或加 est-ce que
- **B**（neutral）：« Aux fraises du marché. » ——市集的草莓。｜"fraises" 处 `palm-open`
- **B**（neutral）：« Et "bleu" ? » ——那"bleu"（蓝色）呢？｜`point`
- **A**（happy）：« À la mer ! » ——大海！｜"mer" 处 `both-hands`
- **A**（happy）：« "Vert" ? » ——"vert"（绿色）呢？｜`point`
- **B**（neutral）：« À l'herbe des parcs. » ——公园的草地。｜"herbe" 处 `palm-open`
- **B**（neutral）：« Et "jaune" ? » ——那"jaune"（黄色）呢？｜`point`
- **A**（happy）：« Au soleil ! Et aux mimosas en février ! » ——太阳！还有二月的含羞花！｜"soleil" 处 `both-hands`｜⚑二月的含羞花（mimosa）＝南法花季——黄在这里是节令
- **A**（happy）：« "Noir" ? » ——"noir"（黑色）呢？｜`point`
- **B**（neutral）：« À un café, bien serré. » ——一杯咖啡，浓浓的。｜"café" 处 `palm-open`
- **B**（neutral）：« Et "blanc" ? » ——那"blanc"（白色）呢？｜`point`
- **A**（happy）：« À la neige des Alpes ! » ——阿尔卑斯的雪！｜"neige" 处 `mini-jump`
- **A**（happy）：« Six couleurs, six idées ! C'était chouette ! » ——六种颜色，六个念头！真棒！｜"Six" 处 `jump-celebrate`
- **B**（encouraging）：« Oui. À demain, Chloé. » ——嗯。明天见，Chloé。｜"demain" 处 `wave`
- **A**（happy）：« À demain ! » ——明天见！｜`wave`＋跑出画

**文化注记**：tu 体（同楼年轻人）；口语问句 « tu penses à quoi ? »（非倒装）；mimosa 二月南法花季——fr 版原生意象。

### 2.4 德语 de-DE｜Felix × Lena（大学同窗）

**舞台**：山径起点的徒步小屋。**道具装置**：路口的指路牌柱——六块不同色的小牌，每轮翻亮一块（德国徒步路牌文化）。

- **A**（happy）：« Lena! Bevor wir losgehen – eine Runde Farbenspiel! » ——Lena！出发前来一局颜色游戏！｜"Farbenspiel" 处 `both-hands`
- **B**（neutral）：« Einverstanden. Wie geht das? » ——同意。怎么玩？｜`nod`
- **A**（happy）：« Wenn ich "Rot" sage – woran denkst du? » ——我说"Rot"（红色）——你会想起什么？｜"Rot" 处 `point`
- **B**（neutral）：« An den Marienkäfer auf meinem Notizbuch. » ——我计划本封面上的瓢虫。｜"Marienkäfer" 处 `palm-open`——班底彩蛋：Lena 计划本
- **B**（neutral）：« Und "Blau"? » ——那"Blau"（蓝色）呢？｜`point`
- **A**（happy）：« An den Himmel über den Gipfeln! » ——山峰上方的天空！｜"Himmel" 处 `both-hands`
- **A**（happy）：« "Grün"? » ——"Grün"（绿色）呢？｜`point`
- **B**（neutral）：« An den Wald. Den Weg durch den Wald. » ——森林。穿过森林的那条路。｜"Wald" 处 `palm-open`
- **B**（neutral）：« Und "Gelb"? » ——那"Gelb"（黄色）呢？｜`point`
- **A**（happy）：« An die gelben Schilder am Wanderweg! » ——徒步道上的黄色路牌！｜"Schilder" 处 `point`（指道具柱）｜⚑德国徒步指路牌统一黄色（Wanderweg 标准）——道具柱即按此设
- **A**（happy）：« "Schwarz"? » ——"Schwarz"（黑色）呢？｜`point`
- **B**（neutral）：« An den Schwarzwald. Dort war ich als Kind. » ——黑森林。我小时候去过。｜"Schwarzwald" 处 `palm-open`｜⚑Schwarzwald＝「黑森林」——地名自带颜色
- **B**（neutral）：« Und "Weiß"? » ——那"Weiß"（白色）呢？｜`point`
- **A**（happy）：« An den Schnee auf dem Gipfel! » ——峰顶的雪！｜"Schnee" 处 `mini-jump`
- **A**（happy）：« Sechs Farben – und jetzt weiß ich alles über dich! » ——六种颜色——现在我"weiß"（知道）你的一切啦！｜"weiß" 处 `jump-celebrate`——双关：weiß 既是「白」又是「知道」｜⚑weiß 既是「白」又是「知道」——德语原生双关，不硬译
- **B**（encouraging）：« Nicht alles. Bis morgen, Felix. » ——可没全知道。明天见，Felix。｜"morgen" 处 `wave`——deadpan 反将一军
- **A**（happy）：« Bis morgen! » ——明天见！｜`wave`＋出画

**文化注记**：du 体；Marienkäfer / Schwarzwald / gelbe Wegweiser 全德式；结尾 weiß 双关是德语原生玩梗，其他语种不需要、也不应该有对应物。

### 2.5 西班牙语 es-ES｜Lucía × Mateo（表姐弟）

**舞台**：清晨的果摊（Lucía 主场——颜色游戏在市场里天然成立）。**道具装置**：六个果筐各对应一色，每轮推亮一筐。

- **A**（happy）：« ¡Mateo! Antes de abrir el mercado – ¡el juego de los colores! » ——Mateo！开市前来玩颜色游戏！｜"colores" 处 `both-hands`
- **B**（neutral）：« Vale. ¿Cómo se juega? » ——好。怎么玩？｜`nod`
- **A**（happy）：« Cuando digo "rojo"... ¿en qué piensas? » ——我说"rojo"（红色）……你会想起什么？｜"rojo" 处 `point`｜⚑西语问句须前后双问号 ¿?——正字法特有
- **B**（neutral）：« En los tomates del mercado, claro. » ——市场的番茄，当然。｜"tomates" 处 `palm-open`
- **B**（neutral）：« ¿Y "azul"? » ——那"azul"（蓝色）呢？｜`point`
- **A**（happy）：« ¡En el mar! ¡Y en el cielo de agosto! » ——大海！还有八月的天空！｜"mar" 处 `both-hands`
- **A**（happy）：« ¿"Verde"? » ——"verde"（绿色）呢？｜`point`
- **B**（neutral）：« En las aceitunas de mi abuelo. » ——我爷爷的橄榄。｜"aceitunas" 处 `palm-open`｜⚑「绿」落在橄榄上——头号橄榄生产国的日常
- **B**（neutral）：« ¿Y "amarillo"? » ——那"amarillo"（黄色）呢？｜`point`
- **A**（happy）：« ¡En los girasoles de Castilla! » ——卡斯蒂利亚的向日葵！｜"girasoles" 处 `both-hands`｜⚑卡斯蒂利亚向日葵田＝西班牙经典夏日风景
- **A**（happy）：« ¿"Negro"? » ——"negro"（黑色）呢？｜`point`
- **B**（neutral）：« En la noche de verano. Silencio y estrellas. » ——夏夜。安静，满天星。｜"noche" 处 `palm-open`
- **B**（neutral）：« ¿Y "blanco"? » ——那"blanco"（白色）呢？｜`point`
- **A**（happy）：« ¡En la harina para el pan! » ——做面包的面粉！｜"harina" 处 `mini-jump`
- **A**（happy）：« ¡Seis colores y seis historias! ¡Qué divertido! » ——六种颜色六个故事！真好玩！｜"Seis" 处 `jump-celebrate`
- **B**（encouraging）：« Sí. Hasta mañana, Lucía. » ——是啊。明天见，Lucía。｜"mañana" 处 `wave`
- **A**（happy）：« ¡Hasta mañana! » ——明天见！｜`wave`＋转圈出画

**文化注记**：tú 体；市场语境自带道具（番茄/面粉/橄榄都在摊上）；girasoles（卡斯蒂利亚向日葵田）；旁白可拓展：pueblos blancos（安达卢西亚白墙小镇）。

### 2.6 俄语 ru-RU｜Миша × Аня（同院邻居）

**舞台**：老庭院的花坛旁。**道具装置**：花坛边一盒六色粉笔，每轮 Аня 在石板路上圈出当前色。

- **A**（happy）：« Аня, а давай в цвета поиграем! »（*Anya, a davay v tsveta poigrayem!*）——Аня，来玩颜色游戏吧！｜"цвета" 处 `both-hands`
- **B**（neutral）：« Давай. А как играть? »（*Davay. A kak igrat'?*）——来吧。怎么玩？｜`nod`
- **A**（happy）：« Скажу "красный" — о чём ты подумаешь? »（*Skazhu "krasnyy" — o chyom ty podumayesh?*）——我说"красный"（红色）——你会想起什么？｜"красный" 处 `point`｜⚑красный 与 красивый（美丽）同根——红场本义「美场」
- **B**（neutral）：« О клубнике в саду у бабушки. »（*O klubnike v sadu u babushki.*）——奶奶花园里的草莓。｜"клубнике" 处 `palm-open`
- **B**（neutral）：« А "синий"? »（*A "siniy"?*）——那"синий"（蓝色）呢？｜`point`｜⚑俄语两蓝分立：синий 深蓝／голубой 浅蓝——本课取深蓝
- **A**（happy）：« О небе над нашим двором! »（*O nebe nad nashim dvorom!*）——我们院子上方的天空！｜"небе" 处 `both-hands`
- **A**（happy）：« "Зелёный"? »（*"Zelyonyy"?*）——"зелёный"（绿色）呢？｜`point`
- **B**（neutral）：« О наших берёзах. »（*O nashikh beryozakh.*）——我们的白桦树。｜"берёзах" 处 `palm-open`
- **B**（neutral）：« А "жёлтый"? »（*A "zhyoltyy"?*）——那"жёлтый"（黄色）呢？｜`point`
- **A**（happy）：« О подсолнухах! Они, как я, всегда смотрят на солнце. »（*O podsolnukhakh! Oni, kak ya, vsegda smotryat na solntse.*）——向日葵！它们跟我一样，永远朝着太阳。｜"подсолнухах" 处 `both-hands`——Миша 式自比
- **A**（happy）：« "Чёрный"? »（*"Chyornyy"?*）——"чёрный"（黑色）呢？｜`point`
- **B**（neutral）：« О чёрном чае вечером. »（*O chyornom chaye vecherom.*）——晚上的黑茶。｜"чае" 处 `palm-open`｜⚑чёрный чай 字面「黑茶」＝中文「红茶」——同一杯茶，两种命名
- **B**（neutral）：« А "белый"? »（*A "belyy"?*）——那"белый"（白色）呢？｜`point`
- **A**（happy）：« О снеге! Первый снег — это праздник! »（*O snege! Pervyy sneg — eto prazdnik!*）——雪！初雪就是节日！｜"снеге" 处 `mini-jump`
- **A**（happy）：« Все шесть! Вот это игра! »（*Vse shest'! Vot eta igra!*）——六个全齐！这才叫游戏！｜"шесть" 处 `jump-celebrate`
- **B**（encouraging）：« Спасибо, Миша. До завтра. »（*Spasibo, Misha. Do zavtra.*）——谢谢你，Миша。明天见。｜"завтра" 处 `wave`
- **A**（happy）：« До завтра! »（*Do zavtra!*）——明天见！｜`wave`＋出画

**文化注记**：красный 与 красивый（美丽）同根——Красная площадь「红场」本义「美场」（旁白素材）；чёрный чай＝中文的「红茶」——同一杯茶两种命名，跨文化对比素材；белый→初雪＝冬日节庆感（俄式）。

### 2.7 希腊语 el-GR｜Ελένη × Νίκος（表兄妹）

**舞台**：港口长凳（Νίκος 主场）。**道具装置**：码头一排小门框各漆一色（基克拉泽斯式蓝门窗），每轮镜头轻摇向当前色那扇。

- **A**（happy）：« Νίκο! Ας παίξουμε με τα χρώματα! »（*Níko! As péksoume me ta hrómata!*）——Νίκος！来玩颜色游戏吧！｜"χρώματα" 处 `both-hands`
- **B**（neutral）：« Καλά. Πώς παίζεται; »（*Kalá. Pós pézete?*）——好。怎么玩？｜`nod`
- **A**（happy）：« Όταν λέω "κόκκινο" — σε τι σκέφτεσαι; »（*Ótan léo "kókkino" — se ti skéftese?*）——我说"κόκκινο"（红色）——你会想起什么？｜"κόκκινο" 处 `point`｜⚑希腊语问号写作「;」——分号才是问号
- **B**（neutral）：« Στο κόκκινο αυγό του Πάσχα. »（*Sto kókkino avyó tou Pásha.*）——复活节的红蛋。｜"αυγό" 处 `palm-open`｜⚑复活节染红蛋是希腊习俗——蛋还要互撞比硬
- **B**（neutral）：« Και "μπλε"; »（*Ke "ble"?*）——那"μπλε"（蓝色）呢？｜`point`｜⚑μπλε 是法语 bleu 借词，άσπρο（白）却是原生词——颜色词照出借词层
- **A**（happy）：« Στη θάλασσα! Όπως εδώ! »（*Sti thálassa! Opos edó!*）——大海！就像这里！｜"θάλασσα" 处 `both-hands`——指向画外爱琴海
- **A**（happy）：« "Πράσινο"; »（*"Prássino"?*）——"πράσινο"（绿色）呢？｜`point`
- **B**（neutral）：« Στις ελιές του χωριού. »（*Stis eliés tou choriú.*）——村子里的橄榄树。｜"ελιές" 处 `palm-open`
- **B**（neutral）：« Και "κίτρινο"; »（*Ke "kítrino"?*）——那"κίτρινο"（黄色）呢？｜`point`
- **A**（happy）：« Στον ήλιο του καλοκαιριού! »（*Ston ílio tou kalokayriú!*）——夏天的太阳！｜"ήλιο" 处 `both-hands`
- **A**（happy）：« "Μαύρο"; »（*"Mávro"?*）——"μαύρο"（黑色）呢？｜`point`
- **B**（neutral）：« Στον καφέ το πρωί. Πικρός — όπως η ζωή. »（*Ston kafé to proí. Pikrós — opós i zoí.*）——早晨的咖啡。苦的——就像生活。｜"καφέ" 处 `palm-open`——Νίκос 哲学家人设
- **B**（neutral）：« Και "άσπρο"; »（*Ke "áspro"?*）——那"άσπρο"（白色）呢？｜`point`
- **A**（happy）：« Στα σύννεφα πάνω απ' τη θάλασσα! »（*Sta síntnefa páno ap' ti thálassa!*）——海面上方的云！｜"σύννεφα" 处 `mini-jump`
- **A**（happy）：« Έξι χρώματα! Τέλεια παρτίδα! »（*Éxi hrómata! Télia partída!*）——六种颜色！完美一局！｜"Έξι" 处 `jump-celebrate`
- **B**（encouraging）：« Ναι. Τα λέμε αύριο, Ελένη. »（*Ne. Ta léme ávrio, Eléni.*）——嗯。明天聊，Ελένη。｜"αύριο" 处 `wave`
- **A**（happy）：« Τα λέμε! »（*Ta léme!*）——明天见！｜`wave`＋出画

**文化注记**：κόκκινο αυγό（希腊复活节染红蛋传统）；θάλασσα（爱琴海即景）；语言彩蛋：μπλε 是法语 bleu 借词，而白色是原生词 άσπρο——颜色词最能照出希腊语的借词层（旁白素材）。

### 2.8 阿拉伯语 ar-SA｜عمر × ليلى（同事）

**舞台**：街角咖啡座（عمر 主场）。**道具装置**：一排六色小灯笼，每轮点亮一盏。RTL：文字区右起、名牌镜像、站位对调。

- **A**（happy）：« ليلى! هيا نلعب الألوان! »（*lay-la! ha-ya nal-ʿab al-al-wan!*）——ليلى！来玩颜色吧！｜"الألوان" 处 `both-hands`
- **B**（neutral）：« كيف نلعب؟ »（*kay-fa nal-ʿab?*）——怎么玩？｜`nod`
- **A**（happy）：« إذا قلت "أحمر" — بماذا تفكرين؟ »（*i-dha qult "ah-mar" — bi-ma-dha taf-ki-rin?*）——我说"أحمر"（红色）——你会想起什么？（对 ليلى 用阴性 تفكرين）｜"أحمر" 处 `point`｜⚑问句随听者性别变位：对 ليلى 用阴性 تفكرين——阿语必须双套问句
- **B**（neutral）：« أفكر في الورد... في ورد الطائف. »（*af-kir fi-l-ward... fi ward at-ta-if.*）——我会想起玫瑰……塔伊夫的玫瑰。｜"الورد" 处 `palm-open`｜⚑塔伊夫玫瑰（ورد الطائف）＝沙特最著名的花香产地
- **B**（neutral）：« وإذا قلت "أخضر"؟ »（*wa-i-dha qult "akh-dar"?*）——那我说"أخضر"（绿色）呢？｜`point`
- **A**（happy）：« أفكر في النخيل في مزرعة جدي! »（*af-kir fi-n-na-khil fi maz-ra-ʿat ja-di!*）——我会想起爷爷农场里的椰枣树！｜"النخيل" 处 `both-hands`
- **A**（happy）：« و"أصفر"؟ »（*wa "as-far"?*）——那"أصفر"（黄色）呢？｜`point`
- **B**（neutral）：« أفكر في الرمل عند الغروب. »（*af-kir fi-r-ram-l ʿind al-ghu-rub.*）——我会想起日落时的沙子。｜"الرمل" 处 `palm-open`
- **B**（neutral）：« و"أسود"؟ »（*wa "as-wad"?*）——那"أسود"（黑色）呢？｜`point`
- **A**（happy）：« أفكر في الليل... مثلك يا ليلى! »（*af-kir fi-l-layl... mith-lak ya lay-la!*）——我会想起夜（ليل）……跟你一样，ليلى！｜"الليل" 处 `mini-jump`——ليلى 之名本义即「夜」：阿语原生双关｜⚑ليلى 之名本义即「夜」——阿语原生双关
- **A**（happy）：« و"أبيض"؟ »（*wa "ab-yad"?*）——那"أبيض"（白色）呢？｜`point`
- **B**（neutral）：« أفكر في الثلج... يوماً ما سأراه. »（*af-kir fi-th-thalj... yaw-man ma sa-ra-h.*）——我会想起雪……总有一天我要亲眼看看。｜"الثلج" 处 `palm-open`——沙漠视角的「未见之白」
- **B**（neutral）：« و"أزرق"؟ »（*wa "azraq"?*）——那"أزرق"（蓝色）呢？｜"أزرق" 处 `point`
- **A**（happy）：« أفكر في البحر! في جدة! »（*af-kir fi-l-baḥr! fi Jedda!*）——我想起大海！在吉达！｜"البحر" 处 `both-hands`——吉达海岸（本土意象）
- **A**（happy）：« ستة ألوان! يا سلام! »（*sit-tat al-wan! ya sa-lam!*）——六种颜色！太棒啦！｜"ستة" 处 `jump-celebrate`
- **B**（encouraging）：« كان هذا جميلاً. إلى الغد يا عمر. »（*kan ha-dha ja-mi-lan. i-lal-ghad ya ʿu-mar.*）——真美好。明天见，عمر。｜"الغد" 处 `wave`
- **A**（happy）：« إلى الغد! »（*i-lal-ghad!*）——明天见！｜`wave`＋出画

**文化注记**：问句按**听者性别**变位（对 ليلى 用 تفكرين、对 عمر 用 تفكر）——阿语脚本必须双套问句（§6 验收）；ورد الطائف（塔伊夫玫瑰）、النخيل（绿洲椰枣）；أبيض→雪是「想见未见之白」，沙漠视角的独立设计。；**蓝色一轮为补写**（原剧本缺蓝色致全片只 5 轮）：问句沿用 ar 版短式 «و"X"؟»（B 问 A，不触变位），联想物取沙特本土的 «البحر! في جدة!»——与 en/ru/hi 的「天空」、fr/it/es/el 的「大海」均不逐词对译。补写后六色零遗漏零重复、A 问三 / B 问三、一来一往逐幕交替成立；出场次序为 红-绿-黄-黑-白-蓝（蓝置于末轮，不打乱原有台词与问方）。

### 2.9 印地语 hi-IN｜प्रिया × अर्जुन（大学好友）

**舞台**：大学的红砖走廊。**道具装置**：廊柱边摊开的六色 rangoli 彩粉（节日地画颜料），每轮指尖点出一色。

- **A**（happy）：« अर्जुन! रंगों का खेल खेलें! »（*ar-jun! ran-gon ka khel khe-len!*）——अर्जुन！来，玩个颜色游戏！｜"खेल" 处 `both-hands`
- **B**（neutral）：« ठीक है। कैसे खेलेंगे? »（*thik hai. kai-se khe-len-ge?*）——好。怎么玩？｜`nod`
- **A**（happy）：« मैं "लाल" कहूँ, तो तुम क्या सोचते हो? »（*main "lal" ka-hun, to tum kya so-che ho?*）——我说"लाल"（红色）——你会想起什么？｜"लाल" 处 `point`
- **B**（neutral）：« मैं लाल किला सोचता हूँ। »（*main lal ki-la so-che-ta hun.*）——我会想起红堡。｜"लाल किला" 处 `palm-open`｜⚑लाल किला＝德里「红堡」，莫卧儿皇城
- **B**（neutral）：« और "नीला" कहूँ? »（*aur "ni-la" ka-hun?*）——那我说"नीला"（蓝色）呢？｜`point`
- **A**（happy）：« मैं आसमान सोचती हूँ! और तुम्हारी जीन्स! »（*main a-sa-man so-chi-ti hun! aur tum-ha-ri jins!*）——我会想起天空！还有你的牛仔裤！｜"जीन्स" 处 `point`——班底彩蛋：अर्जुन 的深蓝牛仔裤｜⚑动词随说话者性别双叉：प्रिया 说 सोचती हूँ、अर्जुन 说 सोचता हूँ——印地语必须双套动词
- **A**（happy）：« "हरा" कहूँ? »（*"ha-ra" ka-hun?*）——那"हरा"（绿色）呢？｜`point`
- **B**（neutral）：« मैं हरी पत्तियाँ सोचता हूँ। »（*main ha-ri pat-ti-yan so-che-ta hun.*）——我会想起绿叶。｜"पत्तियाँ" 处 `palm-open`
- **B**（neutral）：« और "पीला" कहूँ? »（*aur "pi-la" ka-hun?*）——那我说"पीला"（黄色）呢？｜`point`
- **A**（happy）：« मैं हल्दी सोचती हूँ! रसोई वाली। »（*main hal-di so-chi-ti hun! ras-sui va-li!*）——我会想起姜黄！厨房的那种。｜"हल्दी" 处 `both-hands`
- **A**（happy）：« "काला" कहूँ? »（*"ka-la" ka-hun?*）——那"काला"（黑色）呢？｜`point`
- **B**（neutral）：« मैं काजल सोचता हूँ। कलम की स्याही। »（*main ka-jal so-che-ta hun. ka-lam ki sya-hi.*）——我会想起眼妆墨（काजל）。还有钢笔墨水。｜"काजल" 处 `palm-open`——काजल 与 काला 同根；口袋钢笔人设｜⚑काजल（描眼墨）与 काला（黑）同根——颜色词的词族亲缘
- **B**（neutral）：« और "सफ़ेद" कहूँ? »（*aur "sa-fed" ka-hun?*）——那我说"सफ़ेद"（白色）呢？｜`point`
- **A**（happy）：« मैं दूध सोचती हूँ! »（*main doodh so-chi-ti hun!*）——我会想起牛奶！｜"दूध" 处 `mini-jump`
- **A**（happy）：« छह रंग पूरे! मज़ा आया! »（*chhah rang pu-re! ma-za a-ya!*）——六种颜色全齐！真好玩！｜"छह" 处 `jump-celebrate`
- **B**（encouraging）：« हाँ। कल मिलते हैं, प्रिया। »（*haan. kal mil-te hain, pri-ya.*）——是啊。明天见，प्रिया。｜"कल" 处 `wave`
- **A**（happy）：« कल मिलते हैं! »（*kal mil-te hain!*）——明天见！｜`wave`＋出画

**文化注记**：तुम 体 + 动词阴阳性双叉（प्रिया सोचती हूँ / अर्जुन सोचता हूँ；问句 सोचते हो / सोचती हो）——印地语脚本必须双套动词（§6 验收）；लाल किला（德里红堡）、हल्दी（厨房姜黄）、काजल（同根词）全印地原生。

### 2.10 日语 ja-JP｜ハルカ × リク（同级生）

**舞台**：放学后的商店街。**道具装置**：路口的行人信号灯——轮到「青」那一轮恰好转青，两人相视一笑；街边六盏小灯各罩一色玻璃纸，每轮亮一盏。

- **A**（happy）：「ねえリク！帰る前に、色のゲームしようよ！」（*nee ri-ku! ka-e-ru ma-e-ni, i-ro no ge-e-mu shi-yo-u yo!*）——喂リク！回家前来玩颜色游戏嘛！｜「ゲーム」处 `both-hands`
- **B**（neutral）：「…いいよ。どうやる。」（*... i-i yo. do-u ya-ru.*）——……行啊。怎么玩？｜`nod`
- **A**（happy）：「赤って言ったら、何を思い浮かべる？」（*a-ka tte it-ta-ra, na-ni o o-mo-i u-ka-be-ru?*）——说「あか」（红色）的话，会想起什么？｜「赤」处 `point`
- **B**（neutral）：「…祭りの提灯。」（*... ma-tsu-ri no cho-chin.*）——……祭典的灯笼。｜「提灯」处 `palm-open`
- **B**（neutral）：「青って言ったら？」（*a-o tte it-ta-ra?*）——那「あお」（蓝色）呢？｜`point`
- **A**（happy）：「青信号！押したら渡れるやつ！」（*a-o shin-go! o-shi-ta-ra wa-ta-re-ru yat-su!*）——绿灯（青信号）！一按就能过马路的那种！｜「青信号」处 `mini-jump`｜⚑「青」兼指绿灯（青信号）——青覆盖蓝绿两域，ja 版最经典语言现象
- **A**（happy）：「緑って言ったら？」（*mi-do-ri tte it-ta-ra?*）——那「みどり」（绿色）呢？｜`point`
- **B**（neutral）：「緑茶。」（*ryo-ku-cha.*）——绿茶。｜「緑茶」处 `palm-open`｜⚑「緑茶」是音读汉字词（りょくちゃ），与训读「みどり」并存——一色两读
- **B**（neutral）：「黄色って言ったら？」（*ki-i-ro tte it-ta-ra?*）——那「きいろ」（黄色）呢？｜`point`
- **A**（happy）：「ひまわり！夏のひまわり！」（*hi-ma-wa-ri! na-tsu no hi-ma-wa-ri!*）——向日葵！夏天的向日葵！｜「ひまわり」处 `both-hands`
- **A**（happy）：「黒って言ったら？」（*ku-ro tte it-ta-ra?*）——那「くろ」（黑色）呢？｜`point`
- **B**（neutral）：「…俺の髪。」（*... o-re no ka-mi.*）——……我的头发。｜「髪」处 `deadpan-nod`——面瘫自指：リク 发色 `#2A2A33`
- **B**（neutral）：「白って言ったら？」（*shi-ro tte it-ta-ra?*）——那「しろ」（白色）呢？｜`point`
- **A**（happy）：「白いごはん！今日の晩ごはん！」（*shi-ro-i go-han! kyo-u no ban go-han!*）——白米饭！今天的晚饭！｜「ごはん」处 `both-hands`｜⚑白米饭是日式餐桌底色——「白」最日常的答案
- **A**（happy）：「六色、全部やった！楽しかった！」（*ro-ku i-ro, zen-bu ya-tta! ta-no-shi-ka-tta!*）——六色全玩了！真开心！｜「全部」处 `jump-celebrate`
- **B**（encouraging）：「…悪くない。また明日。」（*... wa-ru-ku na-i. ma-ta a-shi-ta.*）——……不赖。明天见。｜「明日」处 `wave`
- **A**（happy）：「また明日！」（*ma-ta a-shi-ta!*）——明天见！｜`wave`＋出画

**文化注记**：同级生常体（不用敬体）；青信号＝日语「あお」兼指绿灯——旁白必讲；白いごはん（白饭）、黒→自分の髪（面瘫自指）都是 ja 版自有笑点。

### 2.11 韩语 ko-KR｜도윤 × 서연（幼稚园起的伙伴）

**舞台**：黄昏的街球场。**道具装置**：场边六只不同色的训练锥，每轮踢正一只。

- **A**（happy）：「야, 서연아! 색깔 게임 하나만!」（*ya, seo-yeon-a! saek-kkap ge-im ha-na-man!*）——喂서연！走之前来一局颜色游戏呗！｜「게임」处 `both-hands`
- **B**（neutral）：「좋아요. 어떻게 해요?」（*jo-a-yo. eo-tteo-ke hae-yo?*）——好。怎么玩？｜`nod`｜⚑서연 全程敬语体（해요체）、도윤 全程平语——语体差本身就是关系戏
- **A**（happy）：「빨간색 하면 뭐가 떠올라?」（*ppal-gan-saek ha-myeon mwo-ga tteo-ol-la?*）——说「빨간색」（红色）的话会想起什么？｜「빨간색」处 `point`
- **B**（neutral）：「태극기가 떠올라요.」（*tae-geuk-gi-ga tteo-ol-la-yo.*）——会想起太极旗。｜「태극기」处 `palm-open`｜⚑太极旗的红蓝两色＝韩国国家象征
- **B**（neutral）：「파란색 하면요?」（*pa-ran-saek ha-myeon-yo?*）——那「파란색」（蓝色）呢？｜`point`
- **A**（happy）：「하늘! 가을 하늘!」（*ha-neul! ga-eul ha-neul!*）——天空！秋天的天空！｜「하늘」处 `both-hands`
- **A**（happy）：「초록색 하면?」（*cho-rok-saek ha-myeon?*）——那「초록색」（绿色）呢？｜`point`
- **B**（neutral）：「할머니 댁 산이 떠올라요. 온통 초록!」（*hal-meo-ni taek sa-ni tteo-ol-la-yo. on-tong cho-rok!*）——会想起奶奶家的山。满山都是绿！｜「산」处 `palm-open`
- **B**（neutral）：「노란색 하면요?」（*no-ran-saek ha-myeon-yo?*）——那「노란색」（黄色）呢？｜`point`
- **A**（happy）：「은행나무! 학교 앞에 있잖아!」（*eun-haeng-na-mu! hak-gyo a-pe it-ja-na!*）——银杏树！学校门口不是有嘛！｜「은행나무」处 `both-hands`
- **A**（happy）：「검은색 하면?」（*geo-meun-saek ha-myeon?*）——那「검은색」（黑色）呢？｜`point`
- **B**（neutral）：「먹이 떠올라요. 붓글씨 먹이에요.」（*meo-gi tteo-ol-la-yo. but-geul-ssi meo-gi-e-yo.*）——会想起墨。写毛笔字的墨。｜「먹」处 `palm-open`
- **B**（neutral）：「흰색 하면요?」（*huin-saek ha-myeon-yo?*）——那「흰색」（白色）呢？｜`point`
- **A**（happy）：「흰 옷! 옛날 조상들이 늘 입었대!」（*huin ot! yen-nal jo-sang-deu-ri neul i-beot-dae!*）——白衣！听说从前的祖先们总穿白衣！｜「흰 옷」处 `mini-jump`——백의민족（白衣民族）｜⚑白衣（흰 옷）呼应「白衣民族」（백의민족）——韩民族尚白传统
- **A**（happy）：「여섯 색깔 다! 재밌다!」（*yeo-seot saek-kkap da! jae-mit-da!*）——六色全玩了！真有意思！｜「여섯」处 `jump-celebrate`
- **B**（encouraging）：「그럼, 내일 봐요, 도윤아.」（*geu-reom, na-il bwa-yo, do-yun-a.*）——那，明天见，도윤。｜「내일」处 `wave`
- **A**（happy）：「내일 봐!」（*na-il bwa!*）——明天见！｜`wave`＋拍球出画

**文化注记**：「～하면 떠오르다」是韩语固有联想句式（非「说到」直译）；오방색（传统五方色：红蓝黄白黑——恰为本课六色中的五个，旁白必讲）；은행나무（秋日首尔）、먹（文房）、백의민족（白衣民族）；도윤 反语体 × 서연 敬语体——语体差本身就是两人的关系戏。

### 2.12 意大利语 it-IT｜Giulia × Luca（合租室友）

**舞台**：黄昏喷泉广场的 gelato 柜台。**道具装置**：六色 gelato（柠檬黄/开心果绿/espresso 黑/奶油白/草莓红/蓝莓蓝），每轮舀起一勺——「说到颜色」直接被颜色本身端出来。

- **A**（happy）：« Luca! Prima del tramonto – il gioco dei colori! » ——Luca！日落前来玩颜色游戏！｜"colori" 处 `both-hands`
- **B**（neutral）：« Va bene. Come si fa? » ——行。怎么玩？｜`nod`
- **A**（happy）：« Quando dico "rosso"... a cosa pensi? » ——我说"rosso"（红色）……你会想起什么？｜"rosso" 处 `point`
- **B**（neutral）：« A una Ferrari, ovviamente. Siamo in Italia! » ——法拉利，还用说。我们可是在意大利！｜"Ferrari" 处 `palm-open`｜⚑rosso Ferrari＝意大利的「国家红」——车企色卡成了文化符号
- **B**（neutral）：« E "blu"? » ——那"blu"（蓝色）呢？｜`point`｜⚑意大利两蓝之分：blu 深蓝／azzurro 天蓝——国家队就叫 Gli Azzurri
- **A**（happy）：« Al mare! Al nostro mare! » ——大海！我们的海！｜"mare" 处 `both-hands`
- **A**（happy）：« "Verde"? » ——"verde"（绿色）呢？｜`point`
- **B**（neutral）：« Al basilico del pesto. » ——青酱里的罗勒。｜"basilico" 处 `palm-open`
- **B**（neutral）：« E "giallo"? » ——那"giallo"（黄色）呢？｜`point`
- **A**（happy）：« Al limone di Sorrento! » ——索伦托的柠檬！｜"limone" 处 `both-hands`
- **A**（happy）：« "Nero"? » ——"nero"（黑色）呢？｜`point`
- **B**（neutral）：« Al caffè. Quello vero, in tazzina. » ——咖啡。小杯装的、真正的咖啡。｜"caffè" 处 `palm-open`
- **B**（neutral）：« E "bianco"? » ——那"bianco"（白色）呢？｜`point`
- **A**（happy）：« A una Vespa bianca! Come quella di zia! » ——白色的 Vespa 小摩托！我姑妈那辆那种！｜"Vespa" 处 `mini-jump`｜⚑白色 Vespa 小摩托＝意式街头经典款
- **A**（happy）：« Sei colori, sei sogni! Com'era bello! » ——六种颜色六个梦！真美！｜"Sei" 处 `jump-celebrate`
- **B**（encouraging）：« Sì. A domani, Giulia. » ——是啊。明天见，Giulia。｜"domani" 处 `wave`
- **A**（happy）：« A domani! » ——明天见！｜`wave`＋出画

**文化注记**：全意大利意象（Ferrari / pesto / limone di Sorrento / caffè in tazzina / Vespa）；tu 体；blu 与 azzurro 之分（国家队称 Gli Azzurri）入旁白注记。

### 2.13 希伯来语 he-IL｜נועה × יובל（邻居）

**舞台**：城市天台（נועה 主场）。**道具装置**：晾衣绳上六块染布，每轮风掀开一块。RTL：文字区右起、名牌镜像、站位对调。

- **A**（happy）：« יובל! משחק אחד בצבעים לפני השקיעה! »（*yu-val! mis-chach e-chad ba-tze-va-im lif-ney ha-shki-a!*）——יובל！日落前来一局颜色游戏！｜"צבעים" 处 `both-hands`
- **B**（neutral）：« איך משחקים? »（*eich mis-chach-im?*）——怎么玩？｜`nod`
- **A**（happy）：« כשאני אומרת "אדום" – במה אתה חושב? »（*kshe-a-ni o-me-ret "a-dom" – be-ma a-ta cho-shev?*）——我说"אדום"（红色）——你会想起什么？（נועה 说话用阴性 אומרת）｜"אדום" 处 `point`｜⚑动词随说话者性别变位：נועה 说 אומרת（阴性）、יובל 说 אומר——希语必须双套动词
- **B**（neutral）：« אני חושב על הכלניות בנגב. »（*a-ni cho-shev al ha-kal-a-niyot ba-negev.*）——我会想起内盖夫的银莲花。｜"כלניות" 处 `palm-open`
- **B**（neutral）：« "ירוק" – במה את חושבת? »（*"ya-rok" – be-ma at cho-shevet?*）——那"ירוק"（绿色）呢——你会想起什么？（对 נועה 提问用阴性 חושבת）｜"ירוק" 处 `point`
- **A**（happy）：« אני חושבת על זית והדגל! »（*a-ni cho-shevet al zayit ve-ha-de-gel!*）——我会想起橄榄叶和国旗！｜"זית" 处 `both-hands`｜⚑橄榄枝＋国旗＝一句话两个国家符号——旗上正画着橄榄枝
- **A**（happy）：« "צהוב" – במה אתה חושב? »（*"tza-hov" – be-ma a-ta cho-shev?*）——那"צהוב"（黄色）呢——你会想起什么？｜`point`
- **B**（neutral）：« אני חושב על חול המדבר. שקט וחם. »（*a-ni cho-shev al chol ha-mid-bar. sha-ket ve-cham.*）——沙漠的沙。安静，又热。｜"חול" 处 `palm-open`
- **B**（neutral）：« "שחור" – במה את חושבת? »（*"sha-chor" – be-ma at cho-shevet?*）——那"שחור"（黑色）呢——你会想起什么？｜`point`
- **A**（happy）：« אני חושבת על קפה של אמא בבוקר! »（*a-ni cho-shevet al ka-fe shel i-ma ba-boker!*）——妈妈早晨的咖啡！｜"קפה" 处 `mini-jump`
- **A**（happy）：« "לבן" – במה אתה חושב? »（*"la-van" – be-ma a-ta cho-shev?*）——那"לבן"（白色）呢——你会想起什么？｜`point`
- **B**（neutral）：« אני חושב על קצף הגלים! מים! »（*a-ni cho-shev al ke-tsef ha-ga-lim! ma-yim!*）——浪尖的白沫。水！｜"קצף" 处 `palm-open`——יובל 大水壶人设
- **B**（neutral）：« "כחול" – במה את חושבת? »（*"ka-chol" – be-ma at cho-shevet?*）——那"כחול"（蓝色）呢——你会想起什么？｜`point`｜⚑תכלת（圣经蓝）源自古代染色螺——希语的「蓝」自带圣经典故
- **A**（happy）：« אני חושבת על הדגים באקווריום! »（*a-ni cho-shevet al ha-dagim be-aquarium!*）——我想起水族箱里的鱼！｜"הדגים" 处 `both-hands`——家庭日常（以 aquarium 而非天空/浪花）
- **A**（happy）：« שישה צבעים! איזה כיף! »（*shi-sha tze-va-im! ei-ze kef!*）——六种颜色！真开心！｜"שישה" 处 `jump-celebrate`
- **B**（encouraging）：« נתראה מחר, נועה. »（*nit-ra-e machar, no-a.*）——明天见，נועה。｜"מחר" 处 `wave`
- **A**（happy）：« נתראה מחר! »（*nit-ra-e machar!*）——明天见！｜`wave`＋出画

**文化注记**：希语问句按**说话者×听者双方性别**各变位（אומרת/אומר、חושב/חושבת）——he 脚本必须双套动词（§6 验收）；כלניות（内盖夫红银莲花花季）、עלי זית（国旗橄榄枝）；תכלת（圣经蓝）可入旁白拓展。；**蓝色一轮为补写**（原剧本缺蓝色致全片只 5 轮）：问句沿用 he 版短式 «"X" – במה את חושבת?»（B=יובל 问 A=נועה，阴性变位），联想物取 «הדגים באקווריום»（水族箱的鱼，以色列家庭日常），刻意避开 en/ru/hi/zh 已用的「天空」与本版白轮已用的「浪花」。补写后六色零遗漏零重复、A 问三 / B 问三成立；出场次序为 红-绿-黄-黑-白-蓝。

### 2.14 粤语 zh-HK｜阿豪 × 阿晴（街坊）

**舞台**：街市小吃摊与茶餐厅之间的窄巷。**道具装置**：茶餐厅门口六块 neon 小招牌各一色，每轮「啪」一声亮起一块。

- **A**（happy）：「阿晴！收工之前——玩個顏色遊戲，好唔好？」（*aa3cing4! sau1gung1 zi1cin4 — waan2 go3 ngaan4sik1 jau4hei3, hou2 m4 hou2?*）——阿晴！收工前——玩个颜色游戏，好不好？｜「遊戲」处 `both-hands`
- **B**（neutral）：「好呀。點玩？」（*hou2aa3. dim2waan2?*）——好呀。怎么玩？｜`nod`｜⚑「點玩」＝怎么玩——粤语疑问词用「點」不用「怎」
- **A**（happy）：「講到紅色，你會諗到啲乜？」（*gong2dou3 hung4sik1, nei5wui5 nam2dou3 di1mat1?*）——说到红色，你会想到什么？｜「紅色」处 `point`
- **B**（neutral）：「利是！過年嗰陣最開心。」（*lai6si6! gwo3nin4 go2zan6 zeoi3hoi1sam1.*）——红包（利是）！过年那阵最开心。｜「利是」处 `palm-open`｜⚑「利是」即红包——粤语固有说法，不叫「红包」
- **B**（neutral）：「講到藍色呢？」（*gong2dou3 laam4sik1 ne1?*）——那蓝色呢？｜`point`
- **A**（happy）：「牛仔褲！人人都有嗰條！」（*ngau4zai2fu3! jan4jan4 dou1jau5 go2tiu4!*）——牛仔裤！人人都有一条！｜「牛仔褲」处 `both-hands`
- **A**（happy）：「講到綠色呢？」（*gong2dou3 luk6sik1 ne1?*）——那绿色呢？｜`point`
- **B**（neutral）：「街市啲菜心。新鮮嗰啲。」（*gaai1si5 di1coi3sam1. san1sin1 go2di1.*）——街市的菜心。新鲜那些。｜「菜心」处 `palm-open`
- **B**（neutral）：「講到黃色呢？」（*gong2dou3 wong4sik1 ne1?*）——那黄色呢？｜`point`
- **A**（happy）：「蛋撻！金黃金黃嗰隻！」（*daan6taat1! gam1wong4gam1wong4 go2zek3!*）——蛋挞！金黄金黄那只！｜「蛋撻」处 `both-hands`——阿豪小吃摊主场
- **A**（happy）：「講到黑色呢？」（*gong2dou3 hak1sik1 ne1?*）——那黑色呢？｜`point`
- **B**（neutral）：「廿四味。」（*jaa6sei3mei2.*）——廿四味凉茶。｜「廿四味」处 `palm-open`——阿晴茶餐厅地头
- **B**（neutral）：「講到白色呢？」（*gong2dou3 baak6sik1 ne1?*）——那白色呢？｜`point`
- **A**（happy）：「白切雞！今晚食唔食？」（*baak6cit3gai1! gam1maan5 sik6m4sik6?*）——白切鸡！今晚吃不吃？｜「白切雞」处 `mini-jump`
- **A**（happy）：「六隻色講晒！好好玩！」（*luk6zek3 sik1 gong2saai3! hou2hou2waan2!*）——六只颜色说「晒」（全）了！真好玩！｜「講晒」处 `jump-celebrate`——句末「晒」＝全、完，粤语自有表达｜⚑句末「晒」表「全、完」——粤语特有助词
- **B**（encouraging）：「聽日見。」（*ting1jat6gin3.*）——明天见。｜`wave`
- **A**（happy）：「聽日見！」（*ting1jat6gin3!*）——明天见！｜`wave`＋出画

**文化注记**：利是（红包）、廿四味（凉茶）、白切雞、蛋撻——全部街市/茶餐廳语境；与 zh-CN 版零共用台词，句式与口语词（嗰啲/點玩/講晒/聽日見）全按粤语口语体独立创作。

## 3. course.json 种子

每语种一份独立的 `dialogue` 数组（独立创作，非互译）。以下为 zh-CN 版示例（体例承 self-introductions.md）：

```json
{
  "type": "scene-dialogue",
  "sceneId": "colors-association",
  "locale": "zh-CN",
  "durationSec": 43.0,
  "dialogue": [
    { "speaker": "A", "text": "江远江远！放学别走——我们来玩个颜色游戏吧！", "mood": "happy" },
    { "speaker": "B", "text": "好。怎么玩？", "mood": "neutral" },
    { "speaker": "A", "text": "说到红色，你会想到什么？", "mood": "happy", "gesture": { "word": "红色", "pose": "point" } },
    { "speaker": "B", "text": "我会想到——过年的灯笼。", "mood": "neutral", "gesture": { "word": "灯笼", "pose": "palm_open" } },
    { "speaker": "B", "text": "说到蓝色呢？", "mood": "neutral", "gesture": { "word": "蓝色", "pose": "point" } },
    { "speaker": "A", "text": "我会想到天空！还有你的外套！", "mood": "happy", "gesture": { "word": "外套", "pose": "point" } },
    { "speaker": "A", "text": "说到绿色，你会想到什么？", "mood": "happy", "gesture": { "word": "绿色", "pose": "point" } },
    { "speaker": "B", "text": "我会想到草地。", "mood": "neutral", "gesture": { "word": "草地", "pose": "palm_open" } },
    { "speaker": "B", "text": "说到黄色呢？", "mood": "neutral", "gesture": { "word": "黄色", "pose": "point" } },
    { "speaker": "A", "text": "我会想到银杏叶！", "mood": "happy", "gesture": { "word": "银杏叶", "pose": "both_hands" } },
    { "speaker": "A", "text": "说到黑色，你会想到什么？", "mood": "happy", "gesture": { "word": "黑色", "pose": "point" } },
    { "speaker": "B", "text": "我会想到夜晚。", "mood": "neutral", "gesture": { "word": "夜晚", "pose": "palm_open" } },
    { "speaker": "B", "text": "说到白色呢？", "mood": "neutral", "gesture": { "word": "白色", "pose": "point" } },
    { "speaker": "A", "text": "我会想到雪！", "mood": "happy", "gesture": { "word": "雪", "pose": "mini_jump" } },
    { "speaker": "A", "text": "六个颜色，都问完啦！真好玩！", "mood": "happy", "gesture": { "word": "都问完", "pose": "jump_celebrate" } },
    { "speaker": "B", "text": "明天见。", "mood": "encouraging", "gesture": { "word": "明天见", "pose": "wave" } },
    { "speaker": "A", "text": "明天见！", "mood": "happy", "gesture": { "word": "明天见", "pose": "wave" } }
  ]
}
```

其余 13 个语种按 §2 各节台词直接落 JSON：`gesture.word` 必须逐字取该语种台词中的词（如 ja「青信号」、ko「태극기」、ar「تفكرين」句中的色词）；ar-SA/he-IL 按 §2 各节 RTL 规则渲染；女性观众变体按 亮相卡 §1.4 另计缓存键。新场景 = 新 JSON + 一张 casting 映射（§4）；音频走 [plan.md §8.2](../docs/plan.md) 契约，词级时间戳驱动口型/高亮/手势（一轴三用）。

## 4. casting 表（14 语种派角总览）

规则承 plan.md §6.1：**A = 活泼者**（先问方、节奏引擎），**B = 沉稳者**（短问稳答）。标注 ★ 的语种搭档关系天然是同学/同窗；其余按各自档案关系作舞台化设定（「两位同学」是 zh-CN 需求的舞台设定，其余语种按其搭档关系自然落地——见 §2 各节舞台行）。

| 语种 | A 先问 | B 后答 | 搭档关系（档案为准） | 舞台 |
| --- | --- | --- | --- | --- |
| 汉语 ★ | 林小满 | 江远 | 发小（同班） | 美术教室·调色盘 |
| 英语 | Miles | Ruby | 街坊 | 街角咖啡馆·粉笔黑板 |
| 法语 | Chloé | Théo | 同楼邻居 | 书店台阶·橱窗书脊 |
| 德语 ★ | Felix | Lena | 大学同窗 | 徒步小屋·指路牌柱 |
| 西班牙语 | Lucía | Mateo | 表姐弟 | 清晨果摊·果筐 |
| 俄语 | Миша | Аня | 同院邻居 | 老庭院·六色粉笔 |
| 希腊语 | Ελένη | Νίκος | 表兄妹 | 港口长凳·漆色门框 |
| 阿拉伯语 | عمر | ليلى | 同事 | 街角咖啡座·六色灯笼 |
| 印地语 ★ | प्रिया | अर्जुन | 大学好友 | 红砖走廊·rangoli 彩粉 |
| 日语 ★ | ハルカ | リク | 同级生 | 商店街·信号灯与街灯 |
| 韩语 | 도윤 | 서연 | 幼稚园起的伙伴 | 街球场·训练锥 |
| 意大利语 | Giulia | Luca | 合租室友 | 喷泉广场·gelato 柜 |
| 希伯来语 | נועה | יובל | 邻居 | 城市天台·晾绳染布 |
| 粤语 | 阿豪 | 阿晴 | 街坊 | 街市窄巷·neon 招牌 |

## 5. 六色词表（对照参考——本场景核心词汇）

注音体例承 [kb/AGENTS.md](../../kb/AGENTS.md)：谚文/假名/天城文/阿/希按书写单元连字分段，俄/希腊连续转写，粤拼带调值；注音永不入音。各语种台词中的色词以本表为准（§2 台词用形容/名词形，随句法变化）。**列序 = §0.1 token 书写序**（机读按位置对位）；单元格 `词 = 别形` 列出全部可逐字命中台词的书写形（如 ja 词表假名、台词汉字）。语料对齐后可入 [expressions](../../kb/arts-and-humanities/linguistics/comparative/expressions/) 平行词表。

| locale | 红 | 蓝 | 绿 | 黄 | 黑 | 白 |
| --- | --- | --- | --- | --- | --- | --- |
| zh-CN | 红 *hóng* | 蓝 *lán* | 绿 *lǜ* | 黄 *huáng* | 黑 *hēi* | 白 *bái* |
| en-US | red | blue | green | yellow | black | white |
| fr-FR | rouge | bleu | vert | jaune | noir | blanc |
| de-DE | Rot | Blau | Grün | Gelb | Schwarz | Weiß |
| es-ES | rojo | azul | verde | amarillo | negro | blanco |
| ru-RU | красный (*krasnyj*) | синий (*sinij*) | зелёный (*zelyonyj*) | жёлтый (*zhyoltyj*) | чёрный (*chyornyj*) | белый (*belyj*) |
| el-GR | κόκκινο (*kókkino*) | μπλε (*ble*) | πράσινο (*prássino*) | κίτρινο (*kítrino*) | μαύρο (*mávro*) | άσπρο (*áspro*) |
| ar-SA | أحمر (*aḥ-mar*) | أزرق (*az-raq*) | أخضر (*akh-ḍar*) | أصفر (*aṣ-far*) | أسود (*as-wad*) | أبيض (*ab-yaḍ*) |
| hi-IN | लाल (*lāl*) | नीला (*nī-lā*) | हरा (*ha-rā*) | पीला (*pī-lā*) | काला (*kā-lā*) | सफ़ेद (*sa-fed*) |
| ja-JP | あか = 赤 (*a-ka*) | あお = 青 (*a-o*) | みどり = 緑 (*mi-do-ri*) | きいろ = 黄色 (*ki-i-ro*) | くろ = 黒 (*ku-ro*) | しろ = 白 (*shi-ro*) |
| ko-KR | 빨간색 (*ppal-gan-saek*) | 파란색 (*pa-ran-saek*) | 초록색 (*cho-rok-saek*) | 노란색 (*no-ran-saek*) | 검은색 (*geo-meun-saek*) | 흰색 (*huin-saek*) |
| it-IT | rosso | blu | verde | giallo | nero | bianco |
| he-IL | אדום (*a-dom*) | כחול (*ka-chol*) | ירוק (*ya-rok*) | צהוב (*tza-hov*) | שחור (*sha-chor*) | לבן (*la-van*) |
| zh-HK | 紅 (*hung4*) | 藍 (*laam4*) | 綠 (*luk6*) | 黃 (*wong4*) | 黑 (*hak1*) | 白 (*baak6*) |

教学注记（旁白逐词解释可取，按语种各自适用，不做跨语种对齐）：俄语「深蓝/浅蓝」二分（синий / голубой）与 красный/красивый 同根；希腊语 μπλε 为法语借词（白色 άσπρο 为原生词）；日语「あお」兼指蓝绿（青信号）；韩语 오방색（红蓝黄白黑恰是本课六色中五个）与 ～색 后缀；阿语答案注意定冠形（الورد）与问句性别变位；希语动词按双方性别变位；法/西/意形容词与名词性数一致。

## 6. 验收补充（在 plan.md §9 M2 验收之上追加）

- [ ] 六色零遗漏零重复；A 问三答三、B 问三答三，一来一往逐幕交替（幕表 §1.1）
- [ ] **原生性**：每语种问句句式为该语言惯用表达；回译检查——任一行译回任一其他语种不得得到可逐词对上的句子；联想物为该文化原生意象，无跨语种「同一批事物」对齐（§1.2 原则 1/2）
- [ ] **变位与语体**：ar/he/hi 问句与答句动词按说话者×听者性别双套核对；ja 常体、ko 反/敬体差、fr/de/es/it tu/tú 体、zh-HK 粤语口语体逐语种核对（§2 各节）
- [ ] 17 行台词全部单 mood 单段合成；缓存键独立，重跑幂等命中
- [ ] 手势词全部逐字出现在对应语种行文本中（否则回退行首）；`point`/`palm-open`/`both-hands`/`mini-jump`/`jump-celebrate`/`wave`/`scratch-head`/`deadpan-nod` 按各节标注
- [ ] 每语种道具装置独立实现，当前色高亮与色名逐词高亮同轴（词级时间戳）；道具色 = 教学六色 token，描边只用 `ink`
- [ ] 跨搭档彩蛋仅当答案指向该搭档/道具真实色板时保留（zh 江远夹克 `#35486E`、en Miles 相机带/Ruby 围裙、hi अर्जुन 牛仔裤、ja リク 发色）
- [ ] RTL 语种（ar/he）：文字区右起、名牌镜像、站位对调；女性观众变体 `_f.mp4` 独立缓存键
- [ ] 幕八 `jump-celebrate` 带 squash-stretch；再会 A `happy`、B `encouraging`，盲听可辨

## 7. 复用去向

- **expressions 平行词表**：六色词表（§5）可入 [expressions](../../kb/arts-and-humanities/linguistics/comparative/expressions/) 平行体系——**平行的是词表与骨架，不是联想答案**；联想问答句式按语种各记一条惯用式（en *what comes to mind*、ko「～하면 떠올라」…），标注「非互译」。
- **交互页（管线三）**：A/B 例句分别锚定两位人物发音按钮；各语种道具装置（调色盘/黑板/果筐/gelato 柜/neon 招牌）即网页端的色卡交互件。
- **后续场景模板**：「联想问答」是可复用骨架——但按 §1.2，后续「食物/动物/数字」系列同样**先定骨架、再逐语种原生创作**，不设母本。**管线已场景无关**：新场景 = 新建 `scene-<id>.md`（§0 机读规格 + §2 台词体例 + §5 词表），`parse_scene.py --scene <id>` → `.\run.ps1 scene -Scene <id>`，渲染/验收零改动；数字类场景 token 用 `"文本"` 字牌 chip（§0 体例注）。
