---
type: "Decision Record"
title: "人物生成技术选型：Pillow 管线续役，H3+Remotion 迁移案备选"
description: "une_usine 亮相卡人物生成的选型记录：四类路线（Talking Face/姿态迁移/T2V/3D 数字人）在本机 RTX 4060 8GB + MiniMax CLI 已认证约束下的逐一裁定；H3 参考生成 + Remotion 编排方案评审通过但暂缓实施——用户裁定回到 Pillow 管线打磨路线（肩楔/肩同宽/臂内收重设计后 28/28 全绿），本 ADR 保留为路线升级时的启动蓝图。"
tags: [decision, character-design, video-pipeline, remotion, minimax]
generated: { by: dsh/fuyao-work, at: 2026-10-03 }
updated: { by: dsh/fuyao-work, at: 2026-10-03, note: "结论反转：迁移案暂缓，Pillow 续役（用户裁定）；§0 现状、§3 保鲜口径同步改写" }
inputs:
  - plan.md                        # 三管线规划（§8.4-8.6）
  - render-handbook.md             # 现役 Pillow 管线的工程沉淀（坑⑩⑪⑫）
  - ../kb/tech/media/remotion.md   # 下游编排引擎规范
  - ../多邻国知识库/03-技术实现.md  # 产品参照（Rive/viseme 管线）
---

# 人物生成技术选型（ADR）

> **状态：已裁定，迁移案暂缓（2026-10-03）**。裁定经过：Pillow 管线的人物形象暴露
> 头/身/手脱节缺陷（§0）→ 做了四路线选型（§1，结论 = H3+Remotion）→ 同日用户裁定
> **回到 Pillow 管线打磨**（几何重设计：肩楔 + 躯干肩同宽 + 肩点内收，28/28 全绿验收）。
> 本 ADR §1/§2 的分析与架构设计保留完整——将来 Pillow 路线到顶或需要真实感人物时，
> 这就是启动蓝图；**现行管线 = render-handbook.md**。

## 0. 触发与硬约束

Pillow 2D 管线（当时现役）的人物形象曾暴露几何拼接缺陷：头/身/手脱节、肩点落在躯干外 35px、
臂躯间 22px 露底缝——2D 图形库**没有解剖结构概念**。该缺陷已通过几何重设计修复
（躯干肩同宽 + 肩楔三角 + 肩点内收，`face_geo()` 重排；见 render-handbook.md §5 坑⑪），
28 卡 qa_all/qa_motion/幂等全绿。硬约束（全部实测）：

| 约束 | 实测值 | 对选型的含义 |
|---|---|---|
| GPU | RTX 4060 Laptop **8GB** | 本地 Diffusion 路线（Hallo/AnimateAnyone/SVD/CogVideoX-5B）全部出局 |
| 网络 | HF/GitHub 经本地代理可达 | HF Space（A10G 免费档）可用作兜底 |
| MiniMax CLI | 已认证，H3/S2V-01 可用，配额无计数限制 | 已验证能生成高质量 3D 风格人物的通道（10-02 两支测试片：2560×1440、24fps、角色一致性成立） |
| 语音 | edge-tts 28 声线 + 词级时间戳管线在产 | 上游音频契约不变 |
| 资产 | personas.json 28 人档案 + intro-cards.json | **与渲染技术无关，全部保值** |
| 下游 | Remotion 知识库齐备（remotion/character-animation/lip-sync/teaching-video-patterns） | 编排版成熟，只需换"人物图层"来源 |

## 1. 四类路线逐一裁定

### 路线① Talking Face（照片+音频驱动说话）

| 候选 | 裁定 | 理由 |
|---|---|---|
| LivePortrait | ☐ 兜底 | 本地可跑（8GB 贴边），但**只认驱动视频不认音频**——还需一段真人表演视频作 driver，与"程序化产线"目标相悖；且只动脸不动肢体，亮相卡的挥手/跳跃覆盖不了 |
| Hallo / EchoMimic / EMO | ✗ | 官方测试环境 A100；Hallo 仅支持英文音频——14 语种班底直接出局 |
| SadTalker / Wav2Lip | ✗ | 画质与"多邻国级形象"差距过大 |
| HeyGen / 剪映数字人 | ✗ | 写实数字人审美，与 Q 版教学班底风格冲突；按分钟计费不可控 |

**裁定：不选**。亮相卡需要肢体表演（挥手/蹦跳/滑板），纯面部驱动覆盖不了；唯一本地可行的 LivePortrait 需要 driver 视频，绕不开"先有真人表演"的死循环。

### 路线② 姿态迁移（立绘+骨骼驱动）

AnimateAnyone / Champ / MagicAnimate：**全部出局**——24GB+ 显存要求 vs 8GB 现实；HF Space 无一在 RUNNING 状态（Moore-AnimateAnyone RUNTIME_ERROR）。且输出是"写实照片风格迁移"，Q 版卡通不是其设计目标。

### 路线③ T2V / 参考生成（文本/参考图→视频）★ **选中**

| 候选 | 裁定 | 理由 |
|---|---|---|
| **MiniMax-H3 reference-to-video** | ★ **主选** | 已验证：`--reference-image` 锁定角色形象，2K/24fps/4-15s，CLI 现成；10-02 两支测试片角色一致性成立。配额实测无硬上限 |
| MiniMax S2V-01 | ◐ 备胎 | `--subject-image` 单图保角色，专为角色一致性设计；留作 H3 参考生成翻车时的降级通道 |
| 可灵 / Runway Gen-3 / Luma | ✗ | 需另开账号+计费；MiniMax 通道已通，不再引入第二供应商 |
| CogVideoX / SVD / AnimateDiff 本地 | ✗ | 8GB 显存不够（SVD 标配 20GB+；CogVideoX-5B fp16 ~12GB） |

### 路线④ 3D 数字人（UE5 MetaHuman / 4D-GS）

✗ 写实人类审美与 Q 版班底相反方向；UE5 工程重量级与"10 秒 × 28 卡"的批量小片场景错配。多邻国官方自己的路线（Rive 状态机 + viseme 查表）本质是**手工动画资产**——没有"生成"环节，美术成本不在本产能预算内。

## 2. 落地架构：两阶段管道（生成上游 × Remotion 下游）

```
personas.json + intro-cards.json（保值资产，原样复用）
        │
        ├─ ① tts：edge-tts → <id>.m4a + timeline.json（词级时间戳）   ← 不变
        │
        ├─ ② generate（新）：Python 脚本调 mmx CLI
        │      mmx video generate --model MiniMax-H3 \
        │        --prompt "<subject_definitions + summary + detailed_description>" \
        │        --reference-image persona_ref.png \
        │        --duration 10 --ratio 9:16 --download avatar_<id>.mp4
        │    关键实践：
        │      · 生成端只出"人物表演"，prompt 要求**纯色背景（建议 chroma 绿/或场景化二选一）**
        │      · 每人设一张 reference 图（一次用 H3 文生图或手工定稿，之后全管线复用）
        │      · 异步任务轮询（mmx --async + task get），失败重试与 .video-creater 同款
        │
        └─ ③ Remotion 工程（新）：npx remotion render
               <OffthreadVideo src={avatar}>  ← 人物动态层（抠像或直接场景化）
               + @remotion/captions 词级卡拉OK字幕（timeline.json 同轴）
               + 名牌/语言牌/气泡（React 组件，替代 Edge headless 文字层）
               + 场景背景（CSS/SVG 渐变，替代 SCENES 原语）
               + 五幕模板/TransitionSeries/16x9·9x16 双注册
```

**两阶段解耦的理由**（照抄用户补充的范式）：Remotion 渲染生命周期里绝不发起
几十秒的 AI 推理——生成是异步批处理脚本，Remotion 只消费产物文件。失败域隔离：
视频生成翻车重跑②，Remotion 层零改动；改字幕/排版/转场只重跑③（分钟级），不碰②（十几分钟级）。

### 2.1 逐字口径（谁负责什么）

| 职责 | 归属 | 替代了旧管线的 |
|---|---|---|
| 人物形象与表演（身体/手势/呼吸） | H3 生成视频 | `draw_character` + `pose_for`（**整体废弃**） |
| 口型 | H3 内建（prompt 约束张嘴说话）+ 生成后不逐帧修 | `openness_at` 词级驱动（废弃，改 prompt 级约束 + 可选 lip-sync 后处理） |
| 卡拉OK字幕 | @remotion/captions + timeline.json | band 双 PNG 裁贴 |
| 名牌/语言牌/气泡 | React 组件（CSS 圆角+投影，无抠像问题） | Edge headless 双 matte（**连同 Edge 视口差截断坑一起消失**） |
| 场景背景 | CSS/SVG 组件或 H3 prompt 场景化 | SCENES 57 原语 |
| 词级时间戳 | edge-tts WordBoundary（不变） | — |

### 2.2 风险与对策

| 风险 | 对策 |
|---|---|
| H3 生成人物与 reference 偶发漂移 | 每卡生成后跑参考图相似度抽检（首/中/尾帧 vs ref）；漂移即重试。S2V-01 作降级 |
| 生成视频带背景，与 Remotion 场景层叠加需要抠像 | 双轨：a) prompt 指定纯绿幕底 → rembg/ffmpeg chromakey 抠透明 WebM；b) 直接让 H3 生成完整场景（背景一步到位，Remotion 只叠加 UI 层）。**默认走 b**——背景生成质量已够，抠像只留给需要透明叠加的卡 |
| 28 卡 × 生成时长（H3 单卡数十秒到几分钟） | `--async` 批量提交 + 轮询下载；quota 无计数限制；一次定稿 reference 图后这是**一次性成本**，改台词/排版不再触发② |
| 口型与 edge-tts 音频相位错位 | H3 支持 `--reference-audio`：把 edge-tts 产物直接作为参考音频喂给生成端，让嘴型跟随真实音素——比逐帧后处理便宜得多 |
| **9:16 竖幅未实测**（10-02 两支验证片为 2560×1440 横幅，而目标是 9:16 1080×1920） | 首批只渲 xiaoman + layla 两张 9:16 卡，先过 reference-to-video 在竖幅下的构图与角色一致性验收，通过后再放全量 28 |
| 成本/时长超预算 | 先渲 2 卡（xiaoman + layla）全流程验收，再放全量 28 |

## 3. 迁移案暂缓后的关系口径（原"保鲜"节改写）

- **Pillow 管线 = 现役**（render-handbook.md 是其工程手册），继续承接亮相卡与后续教学片。
- **本迁移案 = 备选蓝图**（plan.md §8.5 已同步降为"备选态"）：§1 路线裁定与 §2 架构设计完整保留，
  启动条件 = Pillow 路线到顶（形象质感无法再进）或需求转向真实感人物。
- 已完成的修复归现役管线所有：Edge 视口差动态补偿（`edge_win_h`，坑⑩）、人物肩楔/肩点内收（坑⑪）、
  幂等口径修正为视频流 framehash（坑⑫）——这三条与选型无关，是管线自身的工艺进步。
- 多邻国知识库 Rive 路线仍列为**交互页管线（plan.md §8.6）的候选**：Web 端交互页要的是
  "点击即动"的状态机，Rive 状态机仍是对话页立绘的合理选项，与本 ADR（视频端生成）不冲突。

## 4. 验收口径（迁移案启动时生效）

| 项 | 标准 |
|---|---|
| 角色一致性 | 同一 reference 图生成的 3 段视频首/中/尾帧人物特征一致（人工目检 + 首帧 vs ref 相似度抽检） |
| 音画对齐 | Remotion 侧卡拉OK逐词推进与 edge-tts 时间戳同轴（复用 qa_motion 的 band_stats 思路改到 React 层测） |
| 名牌/字幕 | 不再有"矩形不完整"类资产裁切（Edge headless 层已不存在） |
| 28 卡全量 | 时长=10.0s、h264+aac、9:16 1080×1920（沿用 qa_all 骨架，探针改测 Remotion 产物） |
| 幂等 | Remotion 渲染同 props 同帧同像素（Remotion 天然保证）；生成端幂等不追求（AI 推理本质非确定），以"定稿 reference + 台词不变则②不重跑"保证稳定性 |
