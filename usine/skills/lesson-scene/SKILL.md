---
name: lesson-scene
description: >
  Author, parse, validate and draft the teaching-scene data for a lesson —
  `lessons/<id>/scene.md` as the single source, compiled to `scene.json`, with
  a validation gate sitting between parse and render. Use when scaffolding a new
  lesson, when turning a scene spec into `scene.json`, when scene validation
  fails before rendering, when generating a `scene.md` draft from a teaching
  idea, or when replacing one language's section of publishing copy in place.
  Not for drawing the persona or the background (that is character-rig) and not
  for producing video (that is karaoke-video or multilingual-video-poetry).
---

# Teaching Scene Pipeline

Lesson content is one editable file (`scene.md`) compiled to one machine file
(`scene.json`), with a validation layer between parse and render. Nothing else
may be edited by hand — if you find yourself editing `scene.json` directly, the
pipeline has been bypassed and the next `parse` will silently overwrite you.

```
教学创意 ──draft──▶ scene.md ──parse──▶ scene.json ──validate──▶ 可渲染
```

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | 课 id（`lessons/<id>/` 目录名） | 全线无从定位 |
| 2 | 场景骨架：几个 unit、每 unit 几个 beat | `parse` 出的 `scene.json` 是空壳 |
| 3 | 每 unit 的语种范围与共享舞台（shared stage） | `parse_shared_stage` 分不清共享与独享 |
| 4 | 每个 unit 的角色与台词 | `scene draft` 的 `assign_lines` 无从分配 |
| 5 | 角色是否在人设名册内 | `validate` 会在最后一步才拦 |

人设契约见 `personas/schema.md`，机器判定在 library 的 `persona`（`uv run feuille
persona validate` 可独立跑，不读本文件也行）。

## 边界

**本 skill 是「课件内容」的唯一事实源**：`scene.md` 怎么写、怎么解析成 `scene.json`、解析后凭什么算合法。

四个动作各对应一个 CLI 叶子：

| 命令 | 作用 |
|---|---|
| `uv run feuille lesson new` | 新课开坑，铺目录与骨架 |
| `uv run feuille lesson doctor` | 就绪度体检，报缺什么 |
| `uv run feuille scene draft` | 教学创意 → `scene.md` 草稿 |
| `uv run feuille scene parse` | `scene.md` → `scene.json` |
| `uv run feuille scene validate` | parse 与 render 之间的前置校验 |

**不做 / 转交**：

- 画人物 / 背景 / 装置外框，或校验人设契约 → `character-rig`
- 成片 → `karaoke-video`（海报驱动）/ `multilingual-video-poetry`（实拍驱动）
- 做海报 → `one-page-poster`
- 写发布词 → `publish-copy`
- 发到平台 → `multilingual-video-publishing`

## 两条纪律

**判定源一律现取注册表，不复制名单**（纪律 7）。`scene_schema` 与 `scene_draft` 取
**同一份**注册表（`rig` 的脸型/表情、`devices` 的装置规格）——名单必腐烂，
抄两份就等于宣告哪个是对的。

**`section_patch` 按节头边界替换，不用行号区间**。RTL 文本（阿拉伯语/希伯来语）
从终端或编辑器复制会被双向算法重排，行号会指向错误位置——这是三个真实事故换来的。
节头形如 `### NN · 语种`，替换是幂等的。

## 代码归属

拥有模块：lesson, parse_scene, scene_schema, scene_draft, section_patch

事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。
本 skill **跨用**（不拥有）**library** 的 `data` / `devices` / `manifest` /
`metrics` / `rig` / `scenes` / `persona`——跨用走它们的实现，不要另写一份；
skill 之间不横向伸手，校验判据与绘制规格同站一份注册表。