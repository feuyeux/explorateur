---
type: "Content"
title: "示范场景三《一起数到六》：1–6 六个数字（数字 · 计数 · A/B 对话）"
description: "新课验收用场景：1–6 六个数字的 A/B 对话计数游戏。与 colors 课的差别有三处，都用来压「场景是数据不是代码」这条原则：① token 用**字牌 chip**（`\"1\"`）而不是色片；② 装置选 `lanterns`（与 colors 的每语种装置都不同）；③ 骨架完全由 §0.5 节拍表声明。跑通本课且 git diff src/ 为空，即证明新课零代码接入。"
tags: [content, scene, numbers, vocabulary, dialogue, multilingual, teaching-video]
generated: { by: dsh/fuyao-work, at: 2026-10-04 }
inputs:
  - plan.md
  - self-introductions.md
  - requirement.md
---

# 一起数到六

> **学习目标**：1–6 六个基本数字词 + 一组「数一数」问答。
> **结构（全语种共享的骨架）**：开场提议 → 六轮一来一往（A 问 B 答）→ 开心再会。
> **与 colors 课的差异**：token 是**字牌**（井里贴数字文字，不是色块）；装置是灯笼架。
> 两者都只改 §0 声明，不改一行 Python。

## 0. 场景规格（机读体例——parse_scene.py 只认本节 + §2 台词体例 + §5 词表）

sceneId: numbers-count-to-six
title: 一起数到六
form: dialogue
durationBudget: 20-55

### 0.1 教学 token（书写序 = 出场序）

> 本课 token 用**字牌 chip**（`"文本"` 形式）：井里贴数字文字，不是色块。
> 井底色由 §0.2 的 `well` 给，否则深色数字看不清。

| key | chip |
| --- | --- |
| one | "1" |
| two | "2" |
| three | "3" |
| four | "4" |
| five | "5" |
| six | "6" |

### 0.2 舞台装置规格（style = scene_video 的 `@device_style` 注册表；well = 空井底色）

| locale | scenes | style | shape | cellW | cellH | well | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zh-CN | awning, table, plant | lanterns | round | 108 | 116 | #F5F3EE | 六只数字小灯笼 |
| en-US | shopfront, awning, counter | lanterns | round | 108 | 116 | #F5F3EE | six paper lanterns |

### 0.4 角色声明（选角纪律的可验收形式——plan §6.1）

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
| round | 2 | n-4 | even | - |
| summary | n-3 | n-3 | - | - |
| bye | n-2 | n-1 | - | - |

## 1. 规格总则

### 1.1 骨架（全语种共享）

开场提议 → 六轮一来一往（A 问 B 答，依次 1…6）→ 开心再会。六轮零遗漏、零重复。

### 1.2 独立创作原则（承 colors 课 §1.2）

一骨架、每语种独立剧本：数字的说法、数数时的语气、舞台道具全部在语种内自洽，不从中文直译。

## 2. 剧本

体例：台词 = 原文（*注音*）——中文对照。罗马注音永不入音；对照仅供阅读理解。

### 2.1 汉语 zh-CN｜林小满 × 江远

**舞台**：放学后的小院廊下。**道具装置**：廊下挂六只小灯笼，每轮点亮一只，灯笼上写着数字。

- **A**（happy）：「江远江远！我们在数灯笼——从一到六！」｜`bounce-in` 入场，「数」处 `both-hands`
- **B**（neutral）：「好，怎么数？」｜`nod`
- **A**（happy）：「一是什么？」｜「一」处 `point`
- **B**（neutral）：「一盏。」｜「一盏」处 `palm-open`；一号灯笼亮
- **A**（happy）：「那二呢？」｜「二」处 `point`
- **B**（neutral）：「两盏。」｜「两盏」处 `palm-open`；二号灯笼亮
- **A**（happy）：「三？」｜「三」处 `point`
- **B**（neutral）：「三盏。」｜「三盏」处 `palm-open`；三号灯笼亮
- **A**（happy）：「四呢？」｜「四」处 `point`
- **B**（neutral）：「四盏。」｜「四盏」处 `palm-open`；四号灯笼亮
- **A**（happy）：「五！」｜「五」处 `point`
- **B**（neutral）：「五盏——该我了。」｜「五盏」处 `palm-open`；五号灯笼亮
- **A**（happy）：「最后一个，六！」｜「六」处 `point`
- **B**（neutral）：「六盏。数完啦。」｜「六盏」处 `palm-open`；六号灯笼亮——六只全亮
- **A**（happy）：「一到六！全数完啦！」｜「全数完」处 `jump-celebrate`
- **B**（encouraging）：「明天接着数。」｜`wave`
- **A**（happy）：「明天见！」｜`wave`＋蹦跳出画

**文化注记**：中文数词「一盏/两盏」——量词随数词变；灯笼在节庆里是「圆满」的意象，与数数不冲突但要分开讲。

### 2.2 英语 en-US｜Miles × Ruby

**stage**：打烊前的街角咖啡馆。**prop**：门口挂六只纸灯笼，每轮 Ruby 点亮一只，灯笼上写着数字。

- **A**（happy）："Ruby! We're counting the lanterns — one to six!" ｜`bounce-in`，"counting" 处 `both-hands`
- **B**（neutral）："Go ahead. How do we count?" ｜`nod`
- **A**（happy）："What's one?" ｜"one" 处 `point`
- **B**（neutral）："One lantern." ｜"One lantern" 处 `palm-open`；一号灯笼亮
- **A**（happy）："And two?" ｜"two" 处 `point`
- **B**（neutral）："Two." ｜"Two" 处 `palm-open`；二号灯笼亮
- **A**（happy）："Three?" ｜"Three" 处 `point`
- **B**（neutral）："Three." ｜"Three" 处 `palm-open`；三号灯笼亮
- **A**（happy）："Four?" ｜"Four" 处 `point`
- **B**（neutral）："Four." ｜"Four" 处 `palm-open`；四号灯笼亮
- **A**（happy）："Five!" ｜"Five" 处 `point`
- **B**（neutral）："Five — my turn." ｜"Five" 处 `palm-open`；五号灯笼亮
- **A**（happy）："Last one: six!" ｜"six" 处 `point`
- **B**（neutral）："Six. That's all of them." ｜"Six" 处 `palm-open`；六号灯笼亮——六只全亮
- **A**（happy）："One to six — all counted!" ｜"all counted" 处 `jump-celebrate`
- **B**（encouraging）："We'll count more tomorrow." ｜`wave`
- **A**（happy）："See you!" ｜`wave`＋蹦跳出画

**文化注记**：英语用基数词直接计物（one/two lanterns），不套量词——这与中文「一盏/两盏」的结构差异本身就是教学内容。

## 5. 数字词表（对照参考——列序 = §0.1 token 书写序，机读按位置对位）

注音体例承 [kb/AGENTS.md](../../kb/AGENTS.md)：谚文/假名/天城文/阿/希按书写单元连字分段；
注音永不入音。台词中的数字词以本表为准。单元格 `词 = 别形` 列出全部可逐字命中台词的书写形。

| locale | 一 | 二 | 三 | 四 | 五 | 六 |
| --- | --- | --- | --- | --- | --- | --- |
| zh-CN | 一 (*yī*) | 二 (*èr*) | 三 (*sān*) | 四 (*sì*) | 五 (*wǔ*) | 六 (*liù*) |
| en-US | one | two | three | four | five | six |
