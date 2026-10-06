---
type: "Index"
title: "人设目录 · Personas"
description: "多语言教学视频全部人设内容的索引与维护规则：28 位班底人物的数据、档案、参数模型、音色、视觉与选角，以及各文件间的引擎边界与单一事实源约定。"
tags: [persona,index,multilingual,teaching-video]
generated: { by: dsh/fuyao-work, at: 2026-10-06 }
updated: { by: dsh/fuyao-work, at: 2026-10-06, note: "随 docs/plan.md 人设正文迁出而建目录" }
---

# 人设目录 · Personas


> **本目录是人设的唯一归属地。** 2026-10-06 重组：`docs/plan.md` 中的人设正文（§2 名单、§4 schema、§4.1 语气表、§4.2 原语库、§5 二十八人档案、§6.1 casting、§7.1–7.3 质量规则、§8.3 绘制规格、附录 A 声库快照）全部迁入此处。
>
> 本目录是**本项目人设的唯一归属地与唯一 voiceId 来源**；外部平台的声库目录不得混入。
>
> `docs/plan.md` **保留原章节编号作指路牌**，因此全库既有的 `plan.md §4` / `§5` / `§5.8` / `§6.1` / `§4.1` / `§4.2` / `§7.x` / `§8.3` / `附录 A` 等 40 余处交叉引用**全部继续命中**，无需逐个改写。

---

## 一、文件清单

### 数据（管线消费，机器唯一事实源）

| 文件 | 内容 | 单一事实源地位 |
|---|---|---|
| [`personas.json`](personas.json) | **28 位人物档案**——id / locale / gender / 名字三语 / archetype / relation / quirk / voice / movement / palette / accessories | ★ **人物参数唯一出处**。改配色、换音色、调脸型都只改这里 |
| [`intro-cards.json`](intro-cards.json) | 28 张亮相卡数据——moods 表 / cast / lines / entry_pose / close 动作码 | ★ 亮相卡内容唯一出处 |

### 文档（人读）

| 文件 | 内容 |
|---|---|
| [`roster.md`](roster.md) | 全班底一览（14 语种 × 男女）+ **二十八人档案**（名字语义、人设、音色基线、色板、脸型/动作、挂件） |
| [`schema.md`](schema.md) | **Persona 参数模型**（TypeScript 表意）+ 构建版差异 + 32 个表演原语库 |
| [`voice.md`](voice.md) | 共享语气分支表（情绪 = 基线 + 增量）+ 音色质量五条铁律 + **edge-tts 声库快照** |
| [`visual.md`](visual.md) | 用色质量 + 动作质量 + **人物绘制规格**（六型脸谱表、头身比例表） |
| [`casting.md`](casting.md) | 场景选角表（A/B 槽位 → 班底活泼者/沉稳者） |

---


## 二、单一事实源约定

| 维度 | 唯一出处 | 其余文件的角色 |
|---|---|---|
| 人物参数（id/locale/gender/名字/voice/movement/palette/accessories） | `personas.json` | `roster.md` 是它的**人读镜像**，改档案先改 JSON |
| 人物绘制几何（头身比、五官位置、脸型） | `intro_cards.face_geo()` | `visual.md` §3 是规格说明，代码为准 |
| 描边/五官/挂件常量色 | `intro_cards.THEME` | 各文档中的色值示例仅供理解 |
| 情绪增量 | `voice.md` §1 共享表 | 运行时由「个人基线 + 共享增量」合成，不逐人硬编码 |
| 场景选角 | `casting.md` + `course.json` | 人物与模板零改动 |

**同步纪律**：`roster.md` 与 `personas.json` 是一对，改一个必须改另一个。`qa_char` 会对 JSON 色板做探针对照，`qa_shape` 会对 `face_geo()` 做几何探针——文档漂移不会被测试拦住，只能靠人守。

---

## 三、维护规则

1. **新增语种**：先 `edge_tts.list_voices()` 实时核验音色在册 → 往 `personas.json` 加档案 → 往 `roster.md` 补档案行 → 往 `voice.md` §3 补声库快照 → 往 `casting.md` 补选角行。四处同步，缺一不可。
2. **更换音色**：必须先实时核验在册，**禁止静默自动换音色**。声库下架/更名是人工决策，须同时更新 `personas.json`、`roster.md`、`voice.md` 三处。
3. **新增表演原语**：先进 `schema.md` §2 原语库，再在场景里使用；禁止在场景中私写。
4. **改配色**：只改 `personas.json`，重渲染全班底自动跟进；lint 禁止组件/模板出现 hex 字面量。
5. **文档编号**：`plan.md` 的指路牌编号是**契约**，不要重排；`personas/*.md` 内部章节可自由增补。
6. **外部声库不进本目录**：人设目录只收本项目班底；其它平台的声库目录不要往这里放，避免拿错 voiceId。

---

## 四、相关文档

- 规划与实现路线：[`docs/plan.md`](../docs/plan.md)（目标、设计原则、示范场景、管线、阶段验收）
- 人物技术选型裁定：[`docs/adr-character-tech.md`](../docs/adr-character-tech.md)
- 多邻国对标台账：[`docs/benchmark-duolingo.md`](../docs/benchmark-duolingo.md)
- 工程与踩坑手册：[`docs/render-handbook.md`](../docs/render-handbook.md)
- 亮相卡内容种子：[`docs/self-introductions.md`](../docs/self-introductions.md)
- 新增语种流程：[`languages/README.md`](../languages/README.md)
