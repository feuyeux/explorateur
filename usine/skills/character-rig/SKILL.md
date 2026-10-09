---
name: character-rig
description: >
  The drawing primitives behind every feuille render — the persona rig itself
  (face specs, jaw, hair, mood→face table, gaze drift, prop physics), the
  background scene registry (65 registered scenes, all Pillow-drawn), and the
  persona contract validator that reads those same registries. Use when a
  rendered character looks wrong, when picking a face/mood/device for a scene,
  when adding a new background scene or device frame style, or when validating
  a persona roster. Not for authoring lesson content (that is lesson-scene) and
  not for producing video (that is karaoke-video or multilingual-video-poetry).
---

# Character Rig & Scene Primitives

Everything the renderer draws a person or a background with. The implementation
lives in **library**（`rig` / `scenes` / `persona`，`src/feuille/`）；本 skill 是
它们的**说明书**——怎么选、怎么排障、怎么加新东西。It is a **primitive layer**,
not a pipeline: callers compose these, they do not run them end to end.

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | 人设字段（脸型 / 表情 / 发型 / 配色） | `validate_persona` 直接判非法 |
| 2 | 场景名或设备样式名 | 必须取注册表里真实存在的键，**不许自造** |
| 3 | 输出尺寸与超采样倍率 | `DrawScaled` 的倍率错了整批重画 |

## 边界

**本 skill 是「绘制基元」的知识事实源**（选型方法、排障判据、注册纪律）；
实现与注册表本体在 library 的三个模块里：

- `rig` — 人物 rig 本体。色表（`THEME`/`SCENE`/`NECK_SHADE_F`）、随机与物理
  （`rnd`/`gaze`/`phys`/`jump_height`）、插值与缓动（`mix`/`hexc`/`ease_out_cubic`/
  `pop_scale`）、以及 `MOOD_FACE`/`EYE_MOOD`/`FACE_SPECS`/`JAW` 等规格注册表。
- `scenes` — 背景场景原语。`@scene` 注册表下 65 个注册名 / 62 个 `s_*` 函数，
  `DrawScaled` 超采样代理与 `prerender_bg` 渐变背景装配。
- `persona` — 人设契约校验器。`validate_persona` / `validate_roster` 是纯函数、
  不做 I/O，因此反向验证可以直接喂坏数据；不读本文档也能独立跑：
  `uv run feuille persona validate`。

**不做 / 转交**：

- 写/解析/校验课件 → `lesson-scene`
- 成片 → `karaoke-video`（单卡片海报驱动）/ `storyteller-video`（多幕评书，说书人从 `feuille.data.storytellers()` 现取）/ `multilingual-video-poetry`（实拍驱动）
- 多语种字体子集与逐字着色 → `one-page-poster`
- 写发布词 → `publish-copy` / 发到平台 → `multilingual-video-publishing`

## 两条纪律

**合法值一律现取注册表，不复制**（纪律 7）。`persona.py` 的脸型判定直接读
`rig.FACE_SPECS` 的键——那正是绘制规格的唯一事实源；抄一份名单，
绘制改了而校验没改，就会出现「渲染得出来但校验拒绝」的静默分歧。

**skill 之间不横向伸手**。lesson-scene 的校验层（scene_schema / scene_draft /
doctor）与本 skill 站在**同一份** library 注册表上，谁也不许把名单抄走一份。

## 代码归属

拥有模块：（无）

实现与注册表全在 **library**（`rig` / `scenes` / `persona`）——事实源见
`usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。本 skill 只留说明书，
与 `one-page-poster` 的形态一致：知识在 skill，实现沉在 library，横向支撑在下面。
`devices`（装置外框样式注册表）同样归 library——本 skill 的装置画法与
lesson-scene 的校验判据取的是同一份。
