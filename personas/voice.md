# 音色 · Voice

---
type: "Persona"
title: "音色：语气分支表、质量规则与 edge-tts 声库快照"
description: "plan.md §4.1 共享语气分支表、§7.1 音色高质量、附录 A 实测声库快照的迁出版本：情绪=基线+增量的合成表、音色五条质量铁律，以及 edge-tts 7.2.8 逐 locale 实测在册音色。"
tags: [persona,voice,tts,edge-tts,mood]
generated: { by: dsh/fuyao-work, at: 2026-10-06 }
updated: { by: dsh/fuyao-work, at: 2026-10-06, note: "自 docs/plan.md 迁出，章节编号已重编" }
---


> **原位置**：`docs/plan.md` §4.1 / §7.1 / 附录 A。

> **音色引擎**：本项目班底用 **edge-tts（微软 Neural 声库）**，voiceId 形如 `zh-CN-XiaoxiaoNeural`。`personas.json` 的 `voice.voiceId` 是管线唯一来源，本文件 §3 是其核验快照。
>
> 本目录只收本项目人设；其它平台的声库目录不得混入，避免拿错 voiceId。

---

## 1. 共享语气分支表（情绪 = 数据合成，非自由发挥）

> 原 `plan.md` §4.1

有效参数 = **个人基线 + 情绪增量**，再夹取安全域（|rate 总偏移| ≤ 20%、|pitch 总偏移| ≤ 12Hz，防止合成破音）。小步增量保证任何分支下音质不劣化：

| mood | 触发场景（示范场景幕次） | rate Δ | pitch Δ |
| --- | --- | --- | --- |
| `neutral` 平叙 | 默认 | +0% | +0Hz |
| `happy` 开心 | 道谢（第六幕 A） | +4% | +5Hz |
| `puzzled` 疑惑 | 迷路/没听清（一、二幕 A） | −8% | −2Hz |
| `encouraging` 鼓励 | 回礼/"请直走"（四、六幕 B） | −5% | +2Hz |
| `emphatic` 坚定 | 强硬"走！"（第五幕第一档 B） | +2% | −3Hz |
| `teach` 领读 | 方位词领读（第三幕 B） | −15% | +0Hz |

---

## 2. 音色：高质量

> 原 `plan.md` §7.1


1. **实测在册才可用**：28 个 voiceId 全部经 edge-tts 7.2.8 `list_voices()` 实时核验（2026-10-02，快照见附录 A）；新增/更换 voiceId 时先 `edge_tts.list_voices()` 实时核验再入档（不建独立 manifest 文件，附录 A 即快照）——声库下架/更名即 tts 阶段报错，**禁止静默自动换音色**（固定音色原则：迁移必须人工决策并更新档案）。
2. **声学多样性**：一语种两声互补（活泼=快/亮，沉稳=慢/厚），14 语种各自成对——学习者每课至少暴露两种语速/音区（多邻国"多样化声学特征训练"的直译）。
3. **冷门语种的唯一正路**：希腊/印地/阿语本地声库大面积缺位（speech-systems.md §7.1 实测），视频端**只用离线烘焙音频**（audio-narration.md 硬立场：渲染器逐帧截图时 Web Speech 无时钟语义）。
4. **文本纯净隔离**：罗马字注音、中文释义永不入音；拉丁转写按既有分段体例（kb/AGENTS.md）。
5. **节奏与响度**：每句尾 0.6–0.8s 呼吸位；所有音轨 ffmpeg `loudnorm` 统一响度后进时间线；情绪增量小步夹取（|rate|≤20%、|pitch|≤12Hz），任何分支不出破音。

---

## 3. 附录：edge-tts 实测声库快照

> 原 `plan.md` 附录 A（edge-tts 7.2.8，2026-10-02）


获取方式：`edge_tts.list_voices()` 实时拉取（本规划定稿当日实测）。**加粗 = 班底选用**；其余为该 locale 的在册备选（仅用于声库下架时的人工迁移评估，日常禁用）：

| locale | 在册音色（F=女，M=男） |
| --- | --- |
| `zh-CN` | **Xiaoxiao**(F) · Xiaoyi(F) · **Yunxi**(M) · Yunjian(M) · Yunxia(M) · Yunyang(M)※旁白 |
| `en-US` | **Jenny**(F) · **Guy**(M) · Ana(F) · Aria(F) · Ava(F) · Emma(F) · Michelle(F) · Andrew(M) · Brian(M) · Christopher(M) · Eric(M) · Roger(M) · Steffan(M) |
| `fr-FR` | **Denise**(F) · **Henri**(M) · Eloise(F) · Vivienne(F) · Remy(M) |
| `ru-RU` | **Svetlana**(F) · **Dmitry**(M)（仅此一双，零备选） |
| `el-GR` | **Athina**(F) · **Nestoras**(M)（仅此一双） |
| `ja-JP` | **Nanami**(F) · **Keita**(M)（仅此一双） |
| `ko-KR` | **SunHi**(F) · **InJoon**(M) · Hyunsu(M) |
| `hi-IN` | **Swara**(F) · **Madhur**(M)（仅此一双） |
| `ar-SA` | **Zariyah**(F) · **Hamed**(M)（仅此一双） |
| `de-DE` | **Katja**(F) · **Conrad**(M) · Amala(F) · Seraphina(F) · Florian(M) · Killian(M) |
| `es-ES` | **Elvira**(F) · **Alvaro**(M) · Ximena(F)（男声仅此一位） |
| `it-IT` | **Elsa**(F) · **Diego**(M) · Isabella(F) · Giuseppe(M) |
| `he-IL` | **Hila**(F) · **Avri**(M)（仅此一双） |
| `zh-HK` | **HiuMaan**(F) · **WanLung**(M) · HiuGaai(F)（男声仅此一位） |

7 个 locale 恰好只有一男一女两个 Neural 音色——这些语种的班底音色是**零选择锁定**，天然幂等；多备选 locale 由档案锁死单一 id。

---

**相关**：[roster.md](roster.md) 每人的音色基线 · [schema.md](schema.md) `voice` 字段定义
