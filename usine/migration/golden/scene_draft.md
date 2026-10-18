---
type: "Content"
title: "五种语言逛超市"
description: "与 colors（色片）/numbers（字牌）同线可对照：chip 全为中文字牌（在哪里/牛奶/多少钱/便宜点/刷卡），首次进入真实场景购物链——找货、问价、比价、付款四步"
tags: [content, scene, teaching-video]
generated: { by: scene_draft, draft: true }
---

# 五种语言逛超市

> **学习目标**：三个语种各自完成一次完整超市购物对话：找牛奶、问价格、要便宜替代、确认刷卡付款
> **结构**：开场提议 → 6 轮一来一往 → 开心再会
> **待办**：本文件是 guangchaoshi-逛超市 的**结构草稿**，由 `feuille scene draft` 从 `lessons/guangchaoshi-逛超市/brief.json` 生成。所有 `TODO` 都是待填槽位。
> 填完跑 `feuille scene parse --scene guangchaoshi-逛超市` + `feuille scene draft --brief ... --gaps` 查欠账。

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

体例：台词 = 原文（*注音*）——中文对照。罗马注音永不入音；对照仅供阅读理解。

### 2.1 俄语 ru-RU｜Миша × Аня

**舞台**：莫斯科居民区小超市：货架过道，冷柜靠墙，收银台在出口　**道具装置**：三轮圆井托盘，井内嵌中文字牌（货架 · 收银台 · 纸箱堆头）

- **A**（happy）：«TODO»｜«TODO» 处 `bounce-in` `both-hands`
- **B**（neutral）：«TODO»｜«TODO» 处 `nod`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `jump-celebrate`
- **B**（encouraging）：«TODO»｜«TODO» 处 `wave`
- **A**（happy）：«TODO»｜«TODO» 处 `wave`＋蹦跳出画

### 2.2 粤语 zh-HK｜阿豪 × 阿晴

**舞台**：香港屋邨附近超市：冻柜区过道，价签密密排开，收银台就在出口　**道具装置**：三輪圓井托盤，井內嵌中文字牌（貨架 · 收銀台 · 紙箱堆頭）

- **A**（happy）：「TODO」｜「TODO」 处 `bounce-in` `both-hands`
- **B**（neutral）：「TODO」｜「TODO」 处 `nod`
- **A**（happy）：「TODO」｜「TODO」 处 `point`
- **B**（neutral）：「TODO」｜「TODO」 处 `palm-open`
- **A**（happy）：「TODO」｜「TODO」 处 `point`
- **B**（neutral）：「TODO」｜「TODO」 处 `palm-open`
- **A**（happy）：「TODO」｜「TODO」 处 `point`
- **B**（neutral）：「TODO」｜「TODO」 处 `palm-open`
- **A**（happy）：「TODO」｜「TODO」 处 `point`
- **B**（neutral）：「TODO」｜「TODO」 处 `palm-open`
- **A**（happy）：「TODO」｜「TODO」 处 `point`
- **B**（neutral）：「TODO」｜「TODO」 处 `palm-open`
- **A**（happy）：「TODO」｜「TODO」 处 `point`
- **B**（neutral）：「TODO」｜「TODO」 处 `palm-open`
- **A**（happy）：「TODO」｜「TODO」 处 `jump-celebrate`
- **B**（encouraging）：「TODO」｜「TODO」 处 `wave`
- **A**（happy）：「TODO」｜「TODO」 处 `wave`＋蹦跳出画

### 2.3 日语 ja-JP｜ハルカ × リク

**舞台**：日本街角超市：乳制品冷柜前的过道，吊牌价签，收银台在入口旁　**道具装置**：三轮圆井托盘，井内嵌中文字牌（货架 · 收银台 · 纸箱堆头）

- **A**（happy）：«TODO»｜«TODO» 处 `bounce-in` `both-hands`
- **B**（neutral）：«TODO»｜«TODO» 处 `nod`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `point`
- **B**（neutral）：«TODO»｜«TODO» 处 `palm-open`
- **A**（happy）：«TODO»｜«TODO» 处 `jump-celebrate`
- **B**（encouraging）：«TODO»｜«TODO» 处 `wave`
- **A**（happy）：«TODO»｜«TODO» 处 `wave`＋蹦跳出画

## 5. token 词表（对照参考——列序 = §0.1 token 书写序，机读按位置对位）

| locale | where | milk | price | cheaper | card |
| --- | --- | --- | --- | --- | --- |
| ru-RU | TODO | TODO | TODO | TODO | TODO |
| zh-HK | TODO | TODO | TODO | TODO | TODO |
| ja-JP | TODO | TODO | TODO | TODO | TODO |
