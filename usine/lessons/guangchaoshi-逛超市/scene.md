---
type: "Content"
title: "五种语言逛超市"
description: "与 colors（色片）/numbers（字牌）同线可对照：chip 全为中文字牌，首次进入真实场景购物链——找货、问价、比价、付款四步。"
tags: [content, scene, teaching-video]
generated: { by: author, finalized: 2026-10-15 }
---

# 五种语言逛超市

> **学习目标**：三个语种各自完成一次完整超市购物对话——找牛奶、问价格、要便宜替代、确认刷卡付款。
> **结构**：开场提议 → 6 轮一来一往 → 开心再会
> **体例**：台词 = 原文（*注音*）——中文对照；粤语的中文对照给普通话说法。罗马注音永不入音；对照仅供阅读理解。
> **来源**：结构由 `feuille scene draft` 从 `lessons/guangchaoshi-逛超市/brief.json` 生成；台词由作者按独立创作原则填定（2026-10-15 定稿）。

## 0. 场景规格（机读体例——parse_scene.py 只认本节 + §2 台词体例 + §5 词表）

sceneId: guangchaoshi-逛超市
title: 五种语言逛超市
form: dialogue
durationBudget: 45-55
noteFloor: 3
askBalance: any

### 0.1 教学 token（书写序 = 出场序）

| key | chip |
| --- | --- |
| where | 在哪里 |
| milk | 牛奶 |
| price | 多少钱 |
| cheaper | 便宜点 |
| card | 刷卡 |

### 0.2 舞台装置规格（style = devices 的 `@device_style` 注册表；well = 空井底色）

| locale | scenes | style | shape | cellW | cellH | well | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ru-RU | shelf, counter, crates | tray | round | 112 | 112 | #F5F3EE | 三轮圆井托盘，井内嵌中文字牌（货架 · 收银台 · 纸箱堆头） |
| zh-HK | shelf, counter, crates | tray | round | 112 | 112 | #F5F3EE | 三輪圓井托盤，井內嵌中文字牌（貨架 · 收銀台 · 紙箱堆頭） |
| ja-JP | shelf, counter, crates | tray | round | 112 | 112 | #F5F3EE | 三轮圆井托盘，井内嵌中文字牌（货架 · 收银台 · 纸箱堆头） |

### 0.3 语种文本规范（语体承诺：列了就必须有非空 marker）

| locale | 语体 A | 语体 B | 区分标记 | 说明 |
| --- | --- | --- | --- | --- |
| ru-RU | 随意体（ты） | 随意体（ты） | ты 形动词（бери、прикладывай）与无人称 можно 句 | 同龄好友默认 ты；对店员要换 вы |
| zh-HK | 口语粤文 | 口语粤文 | 粤语字（喺、嘅、唔、咁、冇） | 全程口语粤文；中文对照给普通话说法 |
| ja-JP | です・ます体 | です・ます体 | 词尾 です／ます（〜ませんか、〜ですか） | 礼貌体贯穿；邀请也用 〜ませんか |

### 0.4 角色声明（选角纪律的可验收形式）

| role | energy | 说明 |
| --- | --- | --- |
| A | lively | 先问方 · 节奏引擎 |
| B | steady | 沉稳接题方 · 短问稳答 |

### 0.5 骨架节拍（台词行的角色与问句归属由本表决定，不按行号硬推）

`n` = 该语种台词行数（本课 n=17）。节拍须完整覆盖 `[0, n-1]` 且不重叠。

| beat | from | to | ask | askBy |
| --- | --- | --- | --- | --- |
| open | 0 | 0 | - | - |
| reply | 1 | 1 | - | - |
| round | 2 | n-4 | even | A |
| summary | n-3 | n-3 | - | - |
| bye | n-2 | n-1 | - | - |

## 1. 规格总则

### 1.1 骨架（全语种共享）

开场提议 → 6 轮一来一往 → 开心再会

### 1.2 独立创作原则（承 colors 课 §1.2）

一骨架、每语种独立剧本：说法、语气、舞台道具全部在语种内自洽，不从中文直译。

## 2. 剧本

体例：台词 = 原文（*注音*）——中文对照；粤语的中文对照给普通话说法。罗马注音永不入音；对照仅供阅读理解。

### 2.1 俄语 ru-RU｜Миша × Аня

**舞台**：莫斯科居民区小超市：货架过道，冷柜靠墙，收银台在出口。**道具装置**：三轮圆井托盘，井内嵌中文字牌（货架 · 收银台 · 纸箱堆头）

- **A**（happy）：«Аня, пойдём в магазин!»（*Anya, poidyom v magazin!*）——阿妮亚，咱们去超市吧！｜«магазин» 处 `bounce-in` `both-hands`
- **B**（neutral）：«Пойдём! Я тут всё знаю.»（*Poidyom! Ya tut vsyo znayu.*）——走！这一带我全熟。｜«знаю» 处 `nod`
- **A**（happy）：«А где здесь молочный отдел?»（*A gde zdes molochnyy otdel?*）——那奶制品区在哪儿？｜«где» 处 `point`
- **B**（neutral）：«Молоко — прямо, потом налево, у стены.»（*Moloko pryamo, potom nalevo, u steny.*）——牛奶直走，再左转，靠墙那排。｜«Молоко» 处 `palm-open`
- **A**（happy）：«Сколько стоит эта бутылка?»（*Skolko stoit eta butylka?*）——这瓶多少钱？｜«Сколько стоит» 处 `point`｜⚑俄语·超市：сколько стоит 配 эта（这瓶，单数）用三单 стоит；换成复数 эти бутылки 要说 сколько стоят
- **B**（neutral）：«Сто рублей.»（*Sto rubley.*）——一百卢布。｜«Сто рублей» 处 `palm-open`
- **A**（happy）：«Дорого! А есть подешевле?»（*Dorogo! A yest podeshevle?*）——好贵！有便宜点的吗？｜«подешевле» 处 `point`｜⚑俄语·超市：есть подешевле 是「有便宜点的吗」的口语直问，比 есть ли у вас подешевле 更干脆
- **B**（neutral）：«Вот эта — восемьдесят рублей.»（*Vot eta vosemdyesyat rubley.*）——这瓶八十卢布。｜«восемьдесят» 处 `palm-open`
- **A**（happy）：«Отлично! Можно две таких?»（*Otlichno! Mozhno dve takikh?*）——太好了！拿两瓶行吗？｜«две» 处 `point`
- **B**（neutral）：«Конечно, бери!»（*Konechno, beri!*）——当然，拿吧！｜«бери» 处 `palm-open`｜⚑俄语·超市：бери 是 ты（你）命令形——同龄好友全程用 ты，对店员才换 вы
- **A**（happy）：«А картой можно заплатить?»（*A kartoy mozhno zaplatit?*）——那能刷卡吗？｜«картой» 处 `point`｜⚑俄语·超市：картой 是工具格（用卡），前置说 картой можно 最顺口；完整礼貌版 можно заплатить картой?
- **B**（neutral）：«Можно, прикладывай! Касса вон там, у выхода.»（*Mozhno, prikladyvay! Kassa von tam, u vykhoda.*）——可以，刷吧！收银台在那边出口处。｜«прикладывай» 处 `palm-open`
- **A**（happy）：«А пакет тоже платный?»（*A paket tozhe platnyy?*）——塑料袋也要钱吗？｜«пакет» 处 `point`
- **B**（neutral）：«Да, пять рублей. Тоже картой можно.»（*Da, pyat rubley. Tozhe kartoy mozhno.*）——对，五个卢布，也可以刷卡。｜«картой» 处 `palm-open`
- **A**（happy）：«Так: где молоко, сколько стоит, картой можно. Всё запомнил!»（*Tak: gde moloko, skolko stoit, kartoy mozhno. Vsyo zapomnil!*）——牛奶在哪、多少钱、能不能刷卡，全记住啦！｜«запомнил» 处 `jump-celebrate`
- **B**（encouraging）：«Молодец! До скорого!»（*Molodets! Do skorogo!*）——真棒！回头见！｜«До скорого» 处 `wave`
- **A**（happy）：«Пока-пока!»（*Poka-poka!*）——拜拜～！｜«Пока-пока» 处 `wave`＋蹦跳出画

### 2.2 粤语 zh-HK｜阿豪 × 阿晴

**舞台**：香港屋邨附近超市：冻柜区过道，价签密密排开，收银台就在出口。**道具装置**：三輪圓井托盤，井內嵌中文字牌（貨架 · 收銀台 · 紙箱堆頭）

- **A**（happy）：「阿晴，一齊去超市呀！」（*aa3 cing4, jat1 cai4 heoi3 ciu1 si1 aa3!*）——阿晴，一起去超市吧！｜「超市」 处 `bounce-in` `both-hands`
- **B**（neutral）：「好啊，呢間我熟㗎！」（*hou2 aa3, nei1 gaan3 ngo5 suk6 gaa3!*）——好啊，这家店我熟！｜「呢間」 处 `nod`
- **A**（happy）：「噉牛奶喺邊度呀？」（*gam2 ngau4 naai5 hai2 bin1 dou6 aa3?*）——那牛奶在哪儿？｜「邊度」 处 `point`｜⚑粤语·超市：「噉」（gam2）＝那么、接着问——和「咁貴」的「咁」（gam3，这么）不是一个字
- **B**（neutral）：「牛奶喺凍櫃嗰邊，直行轉左。」（*ngau4 naai5 hai2 dung3 gwai6 go2 bin1, zik6 haang4 zyun2 zo2.*）——牛奶在冷藏柜那边，直走左转。｜「牛奶」 处 `palm-open`
- **A**（happy）：「呢樽幾多錢呀？」（*nei1 zun1 gei2 do1 cin2 aa3?*）——这一瓶多少钱？｜「幾多錢」 处 `point`｜⚑粤语·超市：问价固定说「幾多錢」，别把普通话「多少钱」直接搬过去
- **B**（neutral）：「十蚊一樽。」（*sap6 man1 jat1 zun1.*）——十块一瓶。｜「十蚊」 处 `palm-open`｜⚑粤语·超市：「蚊」是钱的口语单位——十蚊＝十块，八蚊＝八块
- **A**（happy）：「咁貴嘅？有冇平啲嘅？」（*gam3 gwai3 ge3? jau5 mou5 peng4 di1 ge3?*）——这么贵？有没有便宜点的？｜「平啲」 处 `point`｜⚑粤语·超市：「平」就是便宜，「平啲」＝便宜一点；「咁貴」的「咁」＝这么
- **B**（neutral）：「呢樽平啲，八蚊。」（*nei1 zun1 peng4 di1, baat3 man1.*）——这瓶便宜点，八块。｜「八蚊」 处 `palm-open`
- **A**（happy）：「好嘢！我要兩樽，得唔得？」（*hou2 je5! ngo5 jiu3 loeng5 zun1, dak1 m4 dak1?*）——好！我要两瓶，行不行？｜「兩樽」 处 `point`
- **B**（neutral）：「得，自己攞啦！」（*dak1, zi6 gei2 lo2 laa1!*）——行，自己拿吧！｜「攞」 处 `palm-open`
- **A**（happy）：「可以碌卡嘛？」（*ho2 ji5 luk1 kaat1 maa3?*）——可以刷卡吗？｜「碌卡」 处 `point`
- **B**（neutral）：「得，拍卡就得。」（*dak1, paak3 kaat1 zau6 dak1.*）——行，拍一下卡就行。｜「拍卡」 处 `palm-open`｜⚑粤语·超市：「碌卡」＝刷卡，「拍卡」＝感应式拍一下——上一句问「可以碌卡嘛」，这句答「拍卡就得」，两个词正好对照
- **A**（happy）：「膠袋要錢嘛？」（*gaau1 doi6 jiu3 cin2 maa3?*）——塑料袋要钱吗？｜「膠袋」 处 `point`
- **B**（neutral）：「要呀，一蚊一個，碌埋佢吖！」（*jiu3 aa3, jat1 man1 jat1 go3, luk1 maai4 keoi5 aa1!*）——要的，一块一个，一起刷了吧！｜「一蚊」 处 `palm-open`
- **A**（happy）：「我識晒喇：牛奶喺邊度、幾多錢、點樣碌卡！」（*ngo5 sik1 saai3 laa3: ngau4 naai5 hai2 bin1 dou6, gei2 do1 cin2, dim2 joeng6 luk1 kaat1!*）——我全学会了：牛奶在哪、多少钱、怎么刷卡！｜「識晒」 处 `jump-celebrate`
- **B**（encouraging）：「得閒再一齊嚟行超市呀！」（*dak1 haan4 zoi3 jat1 cai4 lai4 haang4 ciu1 si1 aa3!*）——有空再一起来逛超市呀！｜「得閒」 处 `wave`
- **A**（happy）：「好呀，拜拜！」（*hou2 aa3, baai3 baai3!*）——好呀，拜拜！｜「拜拜」 处 `wave`＋蹦跳出画

### 2.3 日语 ja-JP｜ハルカ × リク

**舞台**：日本街角超市：乳制品冷柜前的过道，吊牌价签，收银台在入口旁。**道具装置**：三轮圆井托盘，井内嵌中文字牌（货架 · 收银台 · 纸箱堆头）

- **A**（happy）：«リクさん、スーパーへ行きませんか。»（*Riku-san, sūpā e ikimasen ka.*）——小陆，要不要一起去超市？｜«スーパー» 处 `bounce-in` `both-hands`｜⚑日语·超市：〜ませんか 是邀请的礼貌形，比 〜ましょう 更柔和，给对方留出婉拒的余地
- **B**（neutral）：«いいですね。場所は僕が知っています。»（*Ii desu ne. Basho wa boku ga shitte imasu.*）——好啊。地方我熟。｜«場所» 处 `nod`
- **A**（happy）：«あの、牛乳はどこですか。»（*Ano, gyūnyū wa doko desu ka.*）——请问，牛奶在哪儿？｜«どこ» 处 `point`
- **B**（neutral）：«牛乳は乳製品のコーナーです。まっすぐ行って左です。»（*Gyūnyū wa nyūseihin no kōnā desu. Massugu itte hidari desu.*）——牛奶在乳制品区，直走左手边。｜«コーナー» 处 `palm-open`
- **A**（happy）：«この牛乳、いくらですか。»（*Kono gyūnyū, ikura desu ka.*）——这牛奶多少钱？｜«いくら» 处 `point`｜⚑日语·超市：いくらですか 不分单复数——一瓶一箱都这么问，不用改句子
- **B**（neutral）：«一本二百円です。»（*Ippon nihyaku-en desu.*）——一瓶两百日元。｜«一本» 处 `palm-open`
- **A**（happy）：«少し高いですね。安いのはありませんか。»（*Sukoshi takai desu ne. Yasui no wa arimasen ka.*）——有点贵呢。没有便宜点的吗？｜«安い» 处 `point`
- **B**（neutral）：«こちらは百五十円ですよ。»（*Kochira wa hyakugojū-en desu yo.*）——这个是一百五十日元哦。｜«こちら» 处 `palm-open`
- **A**（happy）：«じゃあ、安いのを二本いただけますか。»（*Jaa, yasui no o nihon itadakemasu ka.*）——那请给我两瓶便宜的。｜«二本» 处 `point`｜⚑日语·超市：瓶装牛奶的量词是「本」，两瓶＝二本（にほん）——和「日本」同音，听到别愣
- **B**（neutral）：«はい、二本ですね。どうぞ。»（*Hai, nihon desu ne. Dōzo.*）——好，两瓶是吧。请拿好。｜«どうぞ» 处 `palm-open`
- **A**（happy）：«カードでいいですか。»（*Kādo de ii desu ka.*）——刷卡可以吗？｜«カード» 处 `point`｜⚑日语·超市：〜でいいですか 的 で 表示手段（用……行吗），付款时的万能句式
- **B**（neutral）：«はい、大丈夫ですよ。»（*Hai, daijōbu desu yo.*）——可以，没问题。｜«大丈夫» 处 `palm-open`
- **A**（happy）：«レジ袋は有料ですか。»（*Rejibukuro wa yūryō desu ka.*）——购物袋要收费吗？｜«レジ袋» 处 `point`
- **B**（neutral）：«はい、三円です。カードで一緒に払えますよ。»（*Hai, san-en desu. Kādo de issho ni haraemasu yo.*）——是的，三日元，刷卡时一起付就行。｜«一緒» 处 `palm-open`
- **A**（happy）：«どこにあるか、いくらか、カードが使えるか、全部覚えました！»（*Doko ni aru ka, ikura ka, kādo ga tsukaeru ka, zenbu oboemashita!*）——在哪儿、多少钱、能不能刷卡，全记住啦！｜«全部» 处 `jump-celebrate`
- **B**（encouraging）：«また一緒に行きましょう。»（*Mata issho ni ikimashō.*）——下次再一起去吧。｜«行きましょう» 处 `wave`
- **A**（happy）：«はい！では、また！»（*Hai! De wa, mata!*）——好！那回见！｜«また» 处 `wave`＋蹦跳出画

## 5. token 词表（对照参考——列序 = §0.1 token 书写序，机读按位置对位）

注音必须是 ASCII 尾缀 `词 (*注音*)`：`parse_token_words` 只剥 `(*…*)`/`*…*`，写全角 `（注音）` 会把注音并进书写形，token 全灭（parse 自检 `token 序` 显示 `-` 即此症状）。台词行内的注音则相反，用全角 `（*…*）`。

| locale | where | milk | price | cheaper | card |
| --- | --- | --- | --- | --- | --- |
| ru-RU | где (*gde*) | молоко (*moloko*) | сколько стоит (*skolko stoit*) | подешевле (*podeshevle*) | картой (*kartoy*) |
| zh-HK | 邊度 (*bin1 dou6*) | 牛奶 (*ngau4 naai5*) | 幾多錢 (*gei2 do1 cin2*) | 平啲 (*peng4 di1*) | 碌卡 (*luk1 kaat1*) |
| ja-JP | どこ (*doko*) | 牛乳 (*gyūnyū*) | いくら (*ikura*) | 安い (*yasui*) | カード (*kādo*) |

## 6. 场景专属验收（md 层自检；渲染后另有 qa_scene）

1. token 出场序 = §0.1 书写序，三语种逐行核对：俄 где→молоко→сколько стоит→подешевле→картой；粤 邊度→牛奶→幾多錢→平啲→碌卡；日 どこ→牛乳→いくら→安い→カード。复述行（第 14 行）允许重提全部 token。
2. 游标无回退：第 14 行之前不得把已出场 token 拉回。互为子串处按最长命中与 §0.1 序裁决：「牛奶喺邊度呀」等长并列先亮 where，「この牛乳、いくら」按最长先亮 price，「молочный отдел」不含 молоко 不得误亮 milk。
3. A 六问齐备：round 偶数行（2/4/6/8/10/12）全为问句，B 稳答无反问；bye/summary 无问句要求。
4. ⚑ 注记俄 4 / 粤 5 / 日 4 条，均 ≥ noteFloor 3（注记按语种单独计数）。
5. 货币量词口径：俄＝卢布（100/80/5）、粤＝蚊（10/8/1，量词樽）、日＝円（200/150/3，量词本）——价格均为教学虚构价，非实价声明。
