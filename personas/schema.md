# 人物参数模型 · Persona Schema

---
type: "Persona"
title: "人物参数模型：Persona schema 与表演原语库"
description: "plan.md §4 Persona schema、§4.2 表演原语库的迁出版本：人物参数的类型定义、构建版差异说明，以及 32 个表演原语的纯函数库。"
tags: [persona,schema,rig,motion]
generated: { by: dsh/fuyao-work, at: 2026-10-06 }
updated: { by: dsh/fuyao-work, at: 2026-10-06, note: "自 docs/plan.md 迁出，章节编号已重编；plan.md 原编号留指路牌" }
---


> **原位置**：`docs/plan.md` §4 与 §4.2。**实存数据**：[`personas.json`](personas.json)（Zod / pydantic 双端校验）。

> `personas.json` 的 `$schema` 字段指向本文件。

---

## 1. 人物参数模型（Persona schema）

requirement.md §2 的人物树逐枝落地为如下 schema（TypeScript 表意，实存为 `personas/personas.json`，Zod/pydantic 双端校验）：

```ts
type Persona = {
  id: string;                       // "xiaoman"——seed 命名空间，全局唯一
  locale: string;                   // "zh-CN"
  gender: "female" | "male";
  name: { native: string; latin: string; gloss: string };   // 林小满 / Lin Xiaoman / 名义
  archetype: string;                // 一句话人设
  relation: { partner: string; label: string };  // 语种内搭档（对立人格组队）＋组队关系；对标裁定见 benchmark-duolingo.md §1
  quirk: string;                    // 趣味设定（入档即正史，治理规则见 benchmark-duolingo.md [schema.md §2](../personas/schema.md)）
  energy: "lively" | "steady";      // 能量档：决定 bounce/rate 基线族

  voice: {                          // ── requirement §3.1 声音 ──
    engine: "edge-tts";
    voiceId: string;                // 固定音色 ID，永不随场景重选
    rate: string;                   // 基线语速偏移，如 "+7%"
    pitch: string;                  // 基线音高偏移，如 "+5Hz"
    timbre: string;                 // 音色特质描述（选型依据，人读）
    // 语气（情绪分支）不逐人硬编码：共享下表 + 个人基线，运行时合成
  };

  movement: {                       // ── requirement §3.2 动态 ──
    face: "round" | "tall" | "oval" | "wide" | "heart" | "square";   // 脸型 → face_geo 规格（§8.3；heart=圆收下巴（贝塞尔弧收底，禁尖角）/square=方颌，另有下颌绘制）
    bounce: number;                 // spring damping：越小越弹（个性参数）
    blinkCycleSec: number;          // 眨眼周期（帧函数，相位由 seed 错开）
    breathAmp: number;              // 待机呼吸幅度（0.4Hz 正弦）
    signature: string[];            // 招牌动作原语 id（见 [schema.md §2](../personas/schema.md) 原语库）
    seed: string;                   // = id；random(seed) 的命名空间
    gaze: "camera";                 // 视线跟随镜头（rig 层统一实现）
  };

  moves?: {                        // ── 场景线排他动作槽位表（2026-10-03 新增；缺省 = 槽名回退）──
    // 剧本 `` `pose` `` 注记只写槽位语义（point/nod/wave…），渲染时查本表映射成该人**签名码**：
    // 同一槽位每人一码、逐人单射；活泼池 ∩ 沉稳池 = ∅，故同台 A/B 的动作词汇表零交集由构造
    // 保证（qa_scene §3 有排他探针）。
    // **签名码 ≠ 全片动作**（2026-10-03 用户反馈补强）：同一人一支片内手势按出场次序在
    // 「签名码 → 槽位语义池（SLOT_POOLS，按能量分列）→ 全能量池」里轮换（scene_video.resolve_pose_seq），
    // 全片已用的码跳过 → 同一片内同一人动作零重复；池尽才允许复现，且不得相邻重复。
    // 解析是渲染期纯函数（时间线只存槽位，不改 TTS 产物），幂等探针覆盖。
    point: string; palm_open: string; both_hands: string; nod: string;
    jump_celebrate: string; mini_jump: string; wave: string;
    scratch_head: string; deadpan_nod: string;
  };

  outfit?: {                        // ── 服装轮廓槽（可选；2026-10-03 打磨新增，缺省=长裤零改动）──
    bottom?: "skirt";               // A 字裙：腿画肤色＋裙身取 outfitBottom 色
    kind?: "tunic" | "pinafore" | "vest";   // 长衫（下摆过臀）/ 背带裙（护胸+背带）/ 马甲（中开襟片）
    buttons?: boolean;              // 前襟扣排（衬衫通勤感）
  };

  palette: {                        // ── requirement §3.3 色彩 ──
    identity: string;               // 语种标识色（每人恰一处点缀）
    hair: string; hairHighlight: string;
    skin: string; skinShade: string;         // 基色 + 光影边缘色
    outfitTop: string; outfitBottom: string;
  };
  // 描边/五官/挂件常量色统一走 intro_cards.THEME（ink/blush/gold/shoe…），单一事实源，
  // qa_char 同源对照；palette 不再含 line 字段（2026-10-03 收敛）。
  skin?: {                        // ── 皮肤层（可选；磨损/补丁，qa_char 有对应探针）──
    note: string;                 // 磨损说明（验收可读）
    worn: ("top" | "bottom")[];   // 磨白位置：对应衣片画褪色带
    patches: Array<{              // 补丁：同色块 + 缝线（位置从腿几何派生）
      on: "top" | "bottom";
      where: string;              // 如 "knee_L" / "knee_R"
      color: string;              // 补丁色（hex）
    }>;
  };

  accessories: Array<{              // ── requirement §3.4 挂件 ──
    anchor: "head" | "neck" | "face" | "prop";
    asset: string;                  // "sunglasses" / "necklace" / "knit-hat" / "planner"…
    physics?: "swing" | "bounce" | "reflect";   // 摆动碰撞 / 弹跳 / 高光透光（28 档案各 ≥1 已全量标注）
  }>;
};
```

**构建版差异**（实存 JSON 与本表意 schema 的字段分工）：`movement.signature` 不落 personas.json——招牌动作按卡落在 `intro-cards.json`（`entry`/`entry_pose`/`close`），同一原语库（见本文件 §2）；`movement.seed` ≡ `id`、`gaze` 由 rig 层统一实现，均不重复存档。`name.gloss`/`voice.timbre`/`relation`/`quirk` 为**人物档案维度**（不进渲染，2026-10-03 全 28 人补齐，对标台账见 [benchmark-duolingo.md](../docs/benchmark-duolingo.md)）。

---

## 2. 表演原语库（全部为 frame 的纯函数）

承 character-animation.md 原语表并补齐班底所需；**新增原语必须先进库、后使用**，禁止在场景里私写：

`bounce-in` 弹跳入场 · `wave` 挥手 · `jump-celebrate` 跳跃庆祝（squash-stretch） · `head-shake` 摇头 · `shake` 抖动（答错） · `nod` 点头 · `shrug` 耸肩 · `scratch-head` 挠头 · `point` 指引 · `both-hands` 双手比划 · `thumbs-up` 竖拇指 · `head-tilt` 歪头 · `brow-raise` 挑眉 · `palm-open` 摊手 · `clap` 拍手 · `finger-count` 掰指数步 · `lean-in` 探身 · `hand-shoot` 举手抢答 · `twirl` 转身 · `chest-pat` 拍胸保证 · `beads-ponder` 捻珠沉吟 · `planner-snap` 合上手账 · `cap-tap` 按帽 · `ciao-wave` 告别挥手 · `come-along` 招手"跟我来" · `deadpan-nod` 面瘫点头 · `index-wait` 竖指"等等" · `mini-jump` 小跳 · `pocket-sway` 插兜晃身 · `head-tilt-smile` 侧头一笑定格 · `raise-bottle` 举水瓶 · `thumbs-run` 竖拇指后招手跑出画 · `shoot-run` 投篮后追球跑出画

嘴部（lip-sync）与视线跟随为 **rig 级共享实现**，不进 persona：口型走词级时间戳三态路线（lip-sync.md 路线 B），与逐词高亮字幕共用同一 `captions.json` 时间轴（teaching-video-patterns.md 模式一）。

> 原语库的使用纪律：**新增原语必须先进库、后使用**，禁止在场景里私写。口型（lip-sync）与视线跟随为 rig 级共享实现，不进 persona。
