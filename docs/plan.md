---
type: "Plan"
title: "多语言教学视频人物班底：人设与实现规划"
description: "为十四个语种各设男女一位、共二十八位固定人物的班底规划：符合各语命名习惯的名字、实测锁定的 Neural 音色、token 化调色板、帧函数化动作与挂件；示范场景《问路与指路》开箱即用，换场景人物零改动；音色/用色/动作全链路高质量且幂等。"
tags: [plan, character-design, multilingual, teaching-video, tts]
generated: { by: dsh/fuyao-work, at: 2026-10-02 }
updated: { by: dsh/fuyao-work, at: 2026-10-03, note: "人物形象差异化打磨：§8.3 脸型 2 型→6 型（FACE_SPECS 按人设分配，heart/square 另有下颌绘制）；§4 schema 补 outfit 服装轮廓槽（skirt/tunic/pinafore/vest/buttons）；发型去重（short_part/short_neat）；配饰去雷同（背包 5→2，新增 zipper/clipboard/towel_shoulder，§5 各行已同步）；§8.4 管线一落地实况、§8.5 降为备选、§9 里程碑对齐现状（对标台账见 benchmark-duolingo.md）；colors 课重制：§4 schema 补 moves 排他动作槽位表（28 人，同台 A/B 零交集）" }
inputs:
  - requirement.md                      # 需求输入：界面布局 + 人物设定四模块
  - adr-character-tech.md               # 人物生成技术选型裁定（§8.5 备选案的决策记录）
  - ../kb/arts-and-humanities/linguistics/comparative/example/asking-and-giving-directions.md   # 示范场景
  - ../kb/tech/media/                   # 技术参考：角色/口型/音频/教学片/Remotion
  - ../多邻国知识库/                     # 产品参考：角色工程方法论
---

# 多语言教学视频人物班底：人设与实现规划

> **核心心智模型**（承 [character-animation.md](../../kb/tech/media/character-animation.md)）：
> **人物 = 人设数据（persona）× 骨架组件（rig）× 表演（frame 的函数）**
> 换场景换数据，换表演换参数，班底永不改。反过来，把配色和表情硬编码进某支视频，人物就死在那支视频里。

---

## 1. 目标与约束

**两条硬性需求**（来自任务书），逐条对应本规划章节：

| # | 需求 | 落点 |
| --- | --- | --- |
| 1 | 为全部语种各设两位人物（男女各一）：符合语言习惯的名字、固定的音色等；示范场景开箱即用；后续切换场景人物不需要改变 | §2 全班底一览、§5 二十八人档案、§6 示范场景 casting、§8 数据分层（场景与人物解耦） |
| 2 | 音色、用色、动作保证高质量且幂等 | §7 质量与幂等保障（音色/用色/动作三路 + 幂等七则 + 验收） |

**"全部语种"的口径**：沿用 [kb/AGENTS.md](../../kb/AGENTS.md) 的语言映射——标准对照十一种（中 `zh-CN`、英 `en-US`、德 `de-DE`、法 `fr-FR`、西 `es-ES`、俄 `ru-RU`、希腊 `el-GR`、阿拉伯 `ar-SA`、印地 `hi-IN`、日 `ja-JP`、韩 `ko-KR`）＋ 参照语种三种（意大利 `it-IT`、希伯来 `he-IL`、粤语 `zh-HK`），共 **14 语种 × 2 人 = 28 位**。示范场景《问路与指路》用到其中 9 种，即刻开演；德/西语料已在 [expressions/directions.md](../../kb/arts-and-humanities/linguistics/comparative/expressions/directions.md) 就位，意/希伯来/粤语随新语料接入——**人物先于语料存在**，这正是"换场景人物不变"的含义。

**幂等的工程定义**：同一组输入（personas 数据 + 语料 + 帧号/参数）无论重跑多少次，产出完全一致——逐帧像素一致、音频字节一致、缓存零漂移。重跑只允许"命中缓存"，不允许"悄悄重掷骰子"。

**需求输入的对接**（[requirement.md](requirement.md) → 本方案）：

| requirement.md 条目 | 本方案字段/落点 |
| --- | --- |
| §1 界面布局（文字区/气泡区/人物区） | §6.3 帧内三区布局（16:9 与 9:16 两种画幅同构） |
| §2 人物设定树（声音/动作/色彩/挂件） | §4 Persona schema 四模块一一对应 |
| §3.1 声音（语种/音色/语气） | `voice.voiceId` + `voice.rate/pitch` 基线 + 共享情绪分支表 |
| §3.2 动态（眼睛/嘴部/肢体） | `movement.blink/breath/bounce/signature` + 共用 lip-sync 轴 |
| §3.3 色彩（头发/肤色/服装） | `palette.hair/skin/outfit`（基色+高光/阴影双档） |
| §3.4 挂件（头盔/项链/墨镜） | `accessories[]`（头/颈/面/道具四锚点，swing/bounce/reflect 物理） |
| 服装"做旧/补丁"等质感项 | 保留为**皮肤（skin）层**字段：节日/剧情皮肤叠加不改基型人设（§3 原则五） |

---

## 2. 结论速览：全班底一览

命名工程四条（承 [多邻国知识库/01-人物角色档案.md](../../多邻国知识库/01-人物角色档案.md) §4）：**地道常见**（各语真实高频名）、**跨语可读**（1–2 音节为主，罗马字无歧义）、**班底内唯一**（28 人零重名，且不与多邻国班底 Duo/Lily/Zari/Oscar…撞名）、**贴性格**（名字语义与人设互文）。每语种一对"对立人格"（活泼 × 沉稳）：既是戏剧引擎，也是**声学多样性**（一语种内快/慢、亮/厚两种声线，倒逼学习者适应真实听感）。

| # | 语种（locale） | 标识色 | 女 | 男 | 女音色 | 男音色 | 能量分工 | 组队关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 汉语 `zh-CN` | 朱砂红 `#D8453B` | 林小满 | 江远 | Xiaoxiao | Yunxi | 女·活泼 | 发小 |
| 2 | 英语 `en-US` | 钴蓝 `#4657D8` | Ruby | Miles | Jenny | Guy | 男·活泼 | 街坊 |
| 3 | 法语 `fr-FR` | 法兰西玫瑰 `#CE5290` | Chloé | Théo | Denise | Henri | 女·活泼 | 同楼邻居 |
| 4 | 德语 `de-DE` | 麦金 `#D9A62E` | Lena | Felix | Katja | Conrad | 男·活泼 | 大学同窗 |
| 5 | 西班牙语 `es-ES` | 石榴橙 `#E0782C` | Lucía | Mateo | Elvira | Alvaro | 女·活泼 | 表姐弟 |
| 6 | 俄语 `ru-RU` | 深湖蓝 `#3E7FBF` | Аня | Миша | Svetlana | Dmitry | 男·活泼 | 同院邻居 |
| 7 | 希腊语 `el-GR` | 爱琴青 `#1FAE9E` | Ελένη | Νίκος | Athina | Nestoras | 女·活泼 | 表兄妹 |
| 8 | 阿拉伯语 `ar-SA` | 绿洲绿 `#1E9E6E` | ليلى | عمر | Zariyah | Hamed | 男·活泼 | 同事 |
| 9 | 印地语 `hi-IN` | 藏红花橙 `#F0993E` | प्रिया | अर्जुन | Swara | Madhur | 女·活泼 | 大学好友 |
| 10 | 日语 `ja-JP` | 樱色 `#EE8FA9` | ハルカ | リク | Nanami | Keita | 女·活泼 | 同级生 |
| 11 | 韩语 `ko-KR` | 紫水晶 `#8B5CD6` | 서연 | 도윤 | SunHi | InJoon | 男·活泼 | 幼稚园起的伙伴 |
| 12 | 意大利语 `it-IT` | 阿祖罗蓝 `#4FA3E3` | Giulia | Luca | Elsa | Diego | 女·活泼 | 合租室友 |
| 13 | 希伯来语 `he-IL` | 石榴紫红 `#C2385A` | נועה | יובל | Hila | Avri | 女·活泼 | 邻居 |
| 14 | 粤语 `zh-HK` | 洋紫荆 `#B45EB8` | 阿晴 | 阿豪 | HiuMaan | WanLung | 男·活泼 | 街坊 |

- 全部 28 个音色为 **edge-tts（微软 Neural 声库）实测在册 ID**（快照见附录 A；女声与现役 [make_video.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/make_video.py) 的单音色金标准完全一致，保证管线连续性）。
- 每语种恰好一位活泼（提问者气质）＋一位沉稳（向导气质）；**性别不锁定能量**——8 对女活泼、6 对男活泼，示范 9 语种的 A 角男女比为 5:4。
- 旁白（元语言汉语的逐词讲解）不是班底成员：`zh-CN-YunyangNeural` 系统播音音色，无立绘、不参与对话（见 §6.2）。

---

## 3. 设计原则

承 [多邻国知识库/01-人物角色档案.md](../../多邻国知识库/01-人物角色档案.md) §4"官方设计理念十大原则"与 [02-角色在产品中的作用.md](../../多邻国知识库/02-角色在产品中的作用.md)，针对"多语教学视频"改造为六条：

1. **人物是数据，不是代码**。班底规模的增长 = `personas.json` 的增长。角色由 `persona` 数据驱动同一 rig 渲染；任何视频里禁止手写某个角色的色值/口型/眨眼参数。
2. **对立人格组队**（opposites attract）。每语种"活泼 × 沉稳"一对：天然的对话张力 + 一语种内两种语速/音区的声学多样性（多邻国"多样化声学特征训练"策略的直译）。
3. **强人格是叙事捷径**。初级词汇也能讲好故事——观众不需要每支视频重新认识人物；这正是"换场景人物不变"的产品价值：人物资产复利。
4. **反刻板、重尊重**。Vikram 2024 重设计的教训直接入规：文化元素（头巾、胡须、kurta 等）只做几何化、低细节、非猎奇处理；服装一律**现代日常装**；无"粉色=女生"式配色分配；肤色调在各自语言社区的真实谱系内取值、班底整体覆盖从浅到深的完整人类肤色区间。
5. **基型恒定，皮肤叠加**。人物档案（名字/音色/性格/基型配色）一经锁定不随场景变化；节日装、职业装、做旧戏服等"特色服装"作为**皮肤层**按场景叠加，可装卸、不改基型（对接 requirement.md 的服装质感字段）。
6. **场景 = casting 数据**。新场景只产出一份 `course.json`（台词 + speaker 标签）和一张 casting 映射（speaker → persona id）；人物、rig、管线零改动。

---

## 4. 人物参数模型（Persona schema）

requirement.md §2 的人物树逐枝落地为如下 schema（TypeScript 表意，实存为 `personas/personas.json`，Zod/pydantic 双端校验）：

```ts
type Persona = {
  id: string;                       // "xiaoman"——seed 命名空间，全局唯一
  locale: string;                   // "zh-CN"
  gender: "female" | "male";
  name: { native: string; latin: string; gloss: string };   // 林小满 / Lin Xiaoman / 名义
  archetype: string;                // 一句话人设
  relation: { partner: string; label: string };  // 语种内搭档（对立人格组队）＋组队关系；对标裁定见 benchmark-duolingo.md §1
  quirk: string;                    // 趣味设定（入档即正史，治理规则见 benchmark-duolingo.md §4.2）
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
    signature: string[];            // 招牌动作原语 id（见 §4.2 原语库）
    seed: string;                   // = id；random(seed) 的命名空间
    gaze: "camera";                 // 视线跟随镜头（rig 层统一实现）
  };

  moves?: {                        // ── 场景线排他动作槽位表（2026-10-03 新增；缺省 = 槽名回退）──
    // 剧本 `` `pose` `` 注记只写槽位语义（point/nod/wave…），渲染时 persona_pose() 查本表
    // 映射成该人专属姿态码：同一槽位每人一码、逐人单射；活泼池 ∩ 沉稳池 = ∅，
    // 故同台 A/B 的动作词汇表零交集由构造保证（qa_scene §3 有排他探针）。
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

**构建版差异**（实存 JSON 与本表意 schema 的字段分工）：`movement.signature` 不落 personas.json——招牌动作按卡落在 `intro-cards.json`（`entry`/`entry_pose`/`close`），同一原语库（§4.2）；`movement.seed` ≡ `id`、`gaze` 由 rig 层统一实现，均不重复存档。`name.gloss`/`voice.timbre`/`relation`/`quirk` 为**人物档案维度**（不进渲染，2026-10-03 全 28 人补齐，对标台账见 [benchmark-duolingo.md](benchmark-duolingo.md)）。

### 4.1 共享语气分支表（情绪 = 数据合成，非自由发挥）

有效参数 = **个人基线 + 情绪增量**，再夹取安全域（|rate 总偏移| ≤ 20%、|pitch 总偏移| ≤ 12Hz，防止合成破音）。小步增量保证任何分支下音质不劣化：

| mood | 触发场景（示范场景幕次） | rate Δ | pitch Δ |
| --- | --- | --- | --- |
| `neutral` 平叙 | 默认 | +0% | +0Hz |
| `happy` 开心 | 道谢（第六幕 A） | +4% | +5Hz |
| `puzzled` 疑惑 | 迷路/没听清（一、二幕 A） | −8% | −2Hz |
| `encouraging` 鼓励 | 回礼/"请直走"（四、六幕 B） | −5% | +2Hz |
| `emphatic` 坚定 | 强硬"走！"（第五幕第一档 B） | +2% | −3Hz |
| `teach` 领读 | 方位词领读（第三幕 B） | −15% | +0Hz |

### 4.2 表演原语库（全部为 frame 的纯函数）

承 [character-animation.md](../../kb/tech/media/character-animation.md) 原语表并补齐班底所需；**新增原语必须先进库、后使用**，禁止在场景里私写：

`bounce-in` 弹跳入场 · `wave` 挥手 · `jump-celebrate` 跳跃庆祝（squash-stretch） · `head-shake` 摇头 · `shake` 抖动（答错） · `nod` 点头 · `shrug` 耸肩 · `scratch-head` 挠头 · `point` 指引 · `both-hands` 双手比划 · `thumbs-up` 竖拇指 · `head-tilt` 歪头 · `brow-raise` 挑眉 · `palm-open` 摊手 · `clap` 拍手 · `finger-count` 掰指数步 · `lean-in` 探身 · `hand-shoot` 举手抢答 · `twirl` 转身 · `chest-pat` 拍胸保证 · `beads-ponder` 捻珠沉吟 · `planner-snap` 合上手账 · `cap-tap` 按帽 · `ciao-wave` 告别挥手 · `come-along` 招手"跟我来" · `deadpan-nod` 面瘫点头 · `index-wait` 竖指"等等" · `mini-jump` 小跳 · `pocket-sway` 插兜晃身 · `head-tilt-smile` 侧头一笑定格 · `raise-bottle` 举水瓶 · `thumbs-run` 竖拇指后招手跑出画 · `shoot-run` 投篮后追球跑出画

嘴部（lip-sync）与视线跟随为 **rig 级共享实现**，不进 persona：口型走词级时间戳三态路线（[lip-sync.md](../../kb/tech/media/lip-sync.md) 路线 B），与逐词高亮字幕共用同一 `captions.json` 时间轴（[teaching-video-patterns.md](../../kb/tech/media/teaching-video-patterns.md) 模式一）。

---

## 5. 全班底档案（14 语种 × 男女）

每块给出：标识色及用法、组队关系、两人对照档案。**声音行 = 固定音色 + 基线偏移**（情绪分支查 §4.1 共享表）；**色彩行 = 发（基色/高光）· 肤（基色/阴影）· 上下装**；**动作行 = 脸型 · bounce · 眨眼周期 · 呼吸幅度 · 招牌原语**；**挂件行 = 资产〔锚点·物理〕**。

### 5.1 汉语 `zh-CN`｜朱砂红 `#D8453B`｜发小：元气 × 稳重

| | **林小满**（女·活泼） | **江远**（男·沉稳） |
| --- | --- | --- |
| 名字 | 林小满 *Lín Xiǎomǎn*——节气名"小满"，将满未满，元气与好奇写在名字里 | 江远 *Jiāng Yuǎn*——江与远，走得再远也认得路 |
| 人设 | 元气提问者：先举手再思考 | 人形路标：话不多，指路一步不差 |
| 音色 | `zh-CN-XiaoxiaoNeural`：明亮少女声，颗粒清晰，尾音轻快；基线 `+7% / +5Hz` | `zh-CN-YunxiNeural`：温润青年声，低中音，字字落定；基线 `−6% / −3Hz` |
| 色彩 | 发 `#332E38`/`#524B5E` 高马尾；肤 `#F5C9A2`/`#E0A87E`；卫衣 `#F2EDE4`＋丹宁 A 字裙 `#4A6398` | 发 `#2B2730`/`#46414F` 侧分短发；肤 `#F3D4B8`/`#DDB295`；夹克 `#35486E`＋白 T `#F5F3EE` |
| 动作 | heart（圆收下巴）；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`bounce-in`＋`wave` | square（方颌）；bounce `16`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`nod`＋`palm-open` |
| 挂件 | 红发绳〔头〕；双肩包（标识色）〔prop·bounce〕 | 帆布斜挎包〔prop〕；颈挂耳机〔neck·swing〕 |

标识色用法：小满的发绳／江远的胸徽——**每人恰一处**，语种一眼可辨。

### 5.2 英语 `en-US`｜钴蓝 `#4657D8`｜街坊：机灵 × 靠谱

| | **Ruby**（女·沉稳） | **Miles**（男·活泼） |
| --- | --- | --- |
| 名字 | Ruby——经典暖名，宝石的红与她的冷幽默同框 | Miles——"英里"，天生在路上（问路场景彩蛋，但人设不绑场景） |
| 人设 | 街角咖啡馆掌柜：话不多但句句带钩 | 旅行型选手：热情过剩，方向感为零 |
| 音色 | `en-US-JennyNeural`：亲切成熟女声，微哑的咖啡感；基线 `−4% / −2Hz` | `en-US-GuyNeural`：开朗青年声，音区偏高语速易赶；基线 `+8% / +4Hz` |
| 色彩 | 发 `#8C4A32`/`#B26844` 波浪 lob；肤 `#F7DCC4`/`#E2B896`；白衬衫 `#F4F1EA`＋墨绿围裙 `#2E6B57` | 发 `#C7995C`/`#E0B87A` 微卷；肤 `#FAE3D0`/`#E5BEA4`；钴蓝 T `#4657D8`＋卡其裤 `#B9A279` |
| 动作 | oval；bounce `14`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`brow-raise`＋`nod` | round；bounce `9`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`scratch-head`＋`shrug` |
| 挂件 | 圆框眼镜〔face·reflect〕；名牌挂绳（标识色）〔neck·swing〕 | 相机挂绳〔neck·swing〕；折叠地图〔prop〕 |

### 5.3 法语 `fr-FR`｜法兰西玫瑰 `#CE5290`｜同楼邻居：风风火火 × 从容

| | **Chloé**（女·活泼） | **Théo**（男·沉稳） |
| --- | --- | --- |
| 名字 | Chloé——法国常年前十的女名，明快上口 | Théo——法国常年前列的男名，短而温和 |
| 人设 | 踩滑板的急先锋：说走就走 | 慢先生：先竖一根手指说"等等"，再把路讲清 |
| 音色 | `fr-FR-DeniseNeural`：圆润活泼女声，元音饱满；基线 `+7% / +5Hz` | `fr-FR-HenriNeural`：沉稳男中音，胸腔共鸣，句读分明；基线 `−6% / −3Hz` |
| 色彩 | 发 `#4A342A`/`#6B4E3F` 短波波头；肤 `#F6D8BE`/`#E1B898`；玫瑰针织 `#D67BAB`＋炭灰 A 字裙 `#3F3B45` | 发 `#33261F`/`#524036` 利落短发平刘海；肤 `#EDC9A8`/`#D6A883`；灰蓝衬衫 `#7A93B5`＋白 T `#F5F3EE` |
| 动作 | round；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`twirl`＋`wave` | tall；bounce `15`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`index-wait`＋`point` |
| 挂件 | 滑板〔prop〕；帆布单肩包〔prop〕 | 口袋书〔prop〕；长围巾（标识色）〔neck·swing〕 |

### 5.4 德语 `de-DE`｜麦金 `#D9A62E`｜大学同窗：精确 × 阳光

| | **Lena**（女·沉稳） | **Felix**（男·活泼） |
| --- | --- | --- |
| 名字 | Lena——德国常年榜首段的女名，干净利落 | Felix——拉丁语"幸运的"，德国常青男名 |
| 人设 | 人形日程表：路要掰着指头讲，一步不多一步不少 | 说走就走的徒步咖：先出发再想路线 |
| 音色 | `de-DE-KatjaNeural`：清晰标准女声，节奏均匀如节拍器；基线 `−5% / −2Hz` | `de-DE-ConradNeural`：温厚男声，带笑意的亮度；基线 `+8% / +5Hz` |
| 色彩 | 发 `#9C7A52`/`#BC9A6E` 一丝不苟低髻；肤 `#F6DFCB`/`#E1BB9F`；白衬衫（前襟扣排）`#F5F2EA`＋炭色长裤 `#3F4149` | 发 `#C09A5E`/`#DCBB82` 爆炸短卷；肤 `#F7DEC6`/`#E2BBA0`；芥末黄 T `#EBC357`＋卡其短裤 `#A98F68` |
| 动作 | oval；bounce `15`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`finger-count`＋`nod` | round；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`hand-shoot`＋`bounce-in` |
| 挂件 | 细框眼镜〔face·reflect〕；活页手账〔prop〕 | 登山双肩包〔prop·bounce〕；水壶挂扣〔prop·swing〕 |

### 5.5 西班牙语 `es-ES`｜石榴橙 `#E0782C`｜表姐弟：明快 × 从容

| | **Lucía**（女·活泼） | **Mateo**（男·沉稳） |
| --- | --- | --- |
| 名字 | Lucía——"光"，西班牙近年女名榜首段 | Mateo——西班牙近年男名榜首段 |
| 人设 | 市场里的百灵鸟：热情先到，词尾跟上 | 慢板绅士：不急不躁，路在胸中 |
| 音色 | `es-ES-ElviraNeural`：明快女声，句首起势高；基线 `+7% / +6Hz` | `es-ES-AlvaroNeural`：从容男中音，收句干净；基线 `−7% / −4Hz` |
| 色彩 | 发 `#3E2B26`/`#60453C` 大波浪；肤 `#EAC096`/`#D09B6E`；白上衣 `#F6F1E8`＋橙 A 字裙 `#E0782C` | 发 `#33291F`/`#52443A` 短卷；肤 `#DFB18A`/`#C48D61`；海蓝衬衫（前襟扣排）`#AECBE3`＋白裤 `#F1EDE3` |
| 动作 | oval；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`twirl`＋`clap` | tall；bounce `16`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`palm-open`（慢）＋`nod` |
| 挂件 | 金圆耳环〔neck·swing〕；藤编包〔prop〕 | 腕表（标识色表带）〔prop〕；太阳镜挂领〔neck·swing·reflect〕 |

### 5.6 俄语 `ru-RU`｜深湖蓝 `#3E7FBF`｜同院邻居：轻柔 × 热肠

| | **Аня**（女·沉稳） | **Миша**（男·活泼） |
| --- | --- | --- |
| 名字 | Аня（Anya）—— Anna 的经典昵称，全俄通吃 | Миша（Misha）—— Mikhail 的昵称，"小熊"般的国民名字 |
| 人设 | 院子里的小仙子：轻声细语，却认识每个门洞 | 热心大哥：拍着胸脯保证，笑声先到 |
| 音色 | `ru-RU-SvetlanaNeural`：轻柔女声，气息偏多；基线 `−6% / −3Hz` | `ru-RU-DmitryNeural`：厚实男声，胸腔共鸣；基线 `+6% / +3Hz` |
| 色彩 | 发 `#D8B57A`/`#EDD0A0` 长麻花辫；肤 `#F8E2D2`/`#E6C1AC`；湖蓝毛衣 `#3E7FBF`＋深灰 A 字裙 `#4A4753` | 发 `#8A6A42`/`#A98A5F` 短发微乱；肤 `#F5D9C9`/`#DDB49C`；森林绿夹克 `#3E6B4F`＋米色高领 `#EFE8DA` |
| 动作 | round；bounce `13`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`head-tilt`＋眨眼凝视 | wide（宽和）；bounce `10`；眨眼 `3.0s`；呼吸 `0.012`；招牌＝`chest-pat`＋大笑点头 |
| 挂件 | 针织帽〔head·bounce〕；围巾（标识色）〔neck·swing〕 | 外套拉链（标识色拉链头）〔prop〕（络腮短须为脸型特征，非挂件） |

### 5.7 希腊语 `el-GR`｜爱琴青 `#1FAE9E`｜表兄妹：火爆 × 沉思

| | **Ελένη**（女·活泼） | **Νίκος**（男·沉稳） |
| --- | --- | --- |
| 名字 | Ελένη（Eleni）——"光炬"，希腊第一国民女名 | Νίκος（Nikos）——"胜利"，Nikolaos 的通称，希腊每街一位 |
| 人设 | 双手比划的演说家：路线讲成一场戏 | 海边哲学家：捻着串珠想清楚，再挥手一指 |
| 音色 | `el-GR-AthinaNeural`：明亮女声，重音干脆；基线 `+7% / +4Hz` | `el-GR-NestorasNeural`：低沉男声，句尾下落如叹息；基线 `−8% / −4Hz` |
| 色彩 | 发 `#3E2A22`/`#5E4234` 蓬松卷发；肤 `#E8BE98`/`#CE9C74`；白衬衫 `#F4F0E6`＋青绿裙 `#1FAE9E` | 发 `#3A353F`/鬓角灰 `#7C7684`；肤 `#D9A479`/`#BC835C`；米色亚麻衫 `#EDE4D2`＋深蓝裤 `#3A4E75` |
| 动作 | round；bounce `9`；眨眼 `2.8s`；呼吸 `0.014`；招牌＝`both-hands`＋`point` | tall；bounce `16`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`beads-ponder`＋`point`（挥臂） |
| 挂件 | 太阳镜挂领〔neck·swing·reflect〕；金圆耳环〔neck·swing〕 | 忧思串珠 kombolói〔prop·swing〕 |

### 5.8 阿拉伯语 `ar-SA`｜绿洲绿 `#1E9E6E`｜同事：静水 × 热火

| | **ليلى**（Layla，女·沉稳） | **عمر**（Omar，男·活泼） |
| --- | --- | --- |
| 名字 | ليلى（Layla）——"夜"，古典诗歌里的国民女名 | عمر（Omar）——"旺盛的生命"，极高频男名 |
| 人设 | 安静的向导：掌心向上，路便指好 | 开心果同事：拇指一竖，笑先到话后到 |
| 音色 | `ar-SA-ZariyahNeural`：柔和女声，气声细腻；基线 `−6% / −3Hz` | `ar-SA-HamedNeural`：醇厚男声，带笑纹质感；基线 `+6% / +3Hz` |
| 色彩 | 发 `#26222B`/`#453F4E` 长直发；肤 `#E2B18C`/`#C28F68`；绿长衫 `#1E9E6E`＋米色长裤 `#EFE7D8` | 发 `#2B2530`/`#4B4453` 短卷＋络腮须（脸型特征）；肤 `#C89873`/`#A97852`；白衬衫 `#F5F1E8`＋绿马甲 `#1E9E6E` |
| 动作 | oval；bounce `15`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`palm-open`（雅致指引） | round；bounce `10`；眨眼 `3.0s`；呼吸 `0.012`；招牌＝`thumbs-up`＋`mini-jump` |
| 挂件 | 金细项链〔neck·swing〕；手环〔prop〕 | 太阳镜顶戴〔head·reflect〕；皮质手环〔prop〕 |

RTL 语种（阿/希伯来）：文字区、气泡尾巴、名牌全部镜像；双人站位对调（A 右 B 左）——rig 层由 `dir` 参数统一处理，不进 persona。

### 5.9 印地语 `hi-IN`｜藏红花橙 `#F0993E`｜大学好友：甜妹 × 学霸

| | **प्रिया**（Priya，女·活泼） | **अर्जुन**（Arjun，男·沉稳） |
| --- | --- | --- |
| 名字 | प्रिया（Priya）——"被爱的"，印度最经典女名之一 | अर्जुन（Arjun）——史诗神射手，常青男名 |
| 人设 | 蹦跳的提问机器：好奇比害羞多一步 | 笔记狂人：地图折得方方正正，答案按条给 |
| 音色 | `hi-IN-SwaraNeural`：甜美女声，节奏弹跳；基线 `+7% / +5Hz` | `hi-IN-MadhurNeural`：稳重男声，吐字工整；基线 `−5% / −2Hz` |
| 色彩 | 发 `#2A2430`/`#4A4152` 长辫；肤 `#C68F62`/`#A9714A`；藏红花 kurta `#F0993E`＋白 A 字裙 `#F6F1E7` | 发 `#262230`/`#443D4D` 微卷；肤 `#B07E52`/`#936238`；淡蓝衬衫 `#A9C4DE`＋深色牛仔裤 `#3A4258` |
| 动作 | heart（圆收下巴）；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`clap`＋`head-tilt` | square（方颌）；bounce `14`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`nod`（认真）＋`point`（点图） |
| 挂件 | 金耳环〔neck·swing〕；托特书袋〔prop〕 | 笔记夹板（标识色夹扣）〔prop〕；口袋钢笔〔prop〕 |

### 5.10 日语 `ja-JP`｜樱色 `#EE8FA9`｜同级生：元气 × 面瘫

| | **ハルカ**（Haruka，女·活泼） | **リク**（Riku，男·沉稳） |
| --- | --- | --- |
| 名字 | ハルカ（遥）——"辽远"，常年高频女名 | リク（陸）——"大地"，近年榜首段男名 |
| 人设 | 元气应援团：双手挥起来才算打招呼 | 面瘫导航：表情零起伏，指路零误差 |
| 音色 | `ja-JP-NanamiNeural`：清亮少女声，音高高；基线 `+8% / +5Hz` | `ja-JP-KeitaNeural`：平直少年声，几乎无起伏；基线 `−7% / −5Hz` |
| 色彩 | 发 `#6B4A36`/`#8F6A50` 齐肩内扣；肤 `#F6DCC6`/`#E1BBA1`；白 T `#F7F4EE`＋樱粉开衫 `#F2A4BC`＋丹宁 A 字裙 `#4B5E8C` | 发 `#2A2A33`/`#474755` 一根呆毛；肤 `#F4DBC8`/`#DEBBA4`；炭灰连帽衫 `#4E4E58`＋白 T `#F5F3EE` |
| 动作 | round；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`both-hands`（挥手）＋`mini-jump` | tall（垂眉）；bounce `17`；眨眼 `3.8s`；呼吸 `0.008`；招牌＝`deadpan-nod`＋拇指 `point` |
| 挂件 | 樱粉发夹〔头〕；斜挎小包〔prop〕 | 头戴耳机〔neck〕 |

### 5.11 韩语 `ko-KR`｜紫水晶 `#8B5CD6`｜幼稚园起的伙伴：利落 × 鬼点子

| | **서연**（Seoyeon，女·沉稳） | **도윤**（Doyun，男·活泼） |
| --- | --- | --- |
| 名字 | 서연（Seoyeon）——2010 年代韩国女名榜首段 | 도윤（Doyun）——同期男名榜首段 |
| 人设 | 手账少女：合上本子的一刻就是答案 | 反戴帽子的鬼灵精：正经不超过三秒 |
| 音色 | `ko-KR-SunHiNeural`：清晰女声，收音利落；基线 `−4% / −2Hz` | `ko-KR-InJoonNeural`：活泼男声，句尾上挑；基线 `+7% / +4Hz` |
| 色彩 | 发 `#3A2E2A`/`#5A4A42` 低马尾；肤 `#F9E1D2`/`#E6C1AD`；白衬衫 `#F6F3EC`＋灰西装外套 `#565A6E` | 发 `#2C2832`/`#4D4757` 紫挑染 `#8B5CD6`；肤 `#F5DCC8`/`#DFB9A0`；奶油黄卫衣 `#F2D06B`＋丹宁 `#4A5E8C` |
| 动作 | oval；bounce `13`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`planner-snap`＋`nod`（自信） | round；bounce `9`；眨眼 `2.8s`；呼吸 `0.014`；招牌＝`cap-tap`＋运球节奏点头 |
| 挂件 | 方框眼镜〔face·reflect〕；手账本〔prop〕 | 反戴棒球帽（标识色）〔head·bounce〕；篮球〔prop·bounce〕 |

### 5.12 意大利语 `it-IT`｜阿祖罗蓝 `#4FA3E3`｜合租室友：明媚 × 松弛

| | **Giulia**（女·活泼） | **Luca**（男·沉稳） |
| --- | --- | --- |
| 名字 | Giulia——意大利女名榜首段 | Luca——意大利国民男名 |
| 人设 | 飞吻告别的行动派：ciao 先行 | 插兜慢步的老好人：肩一耸，路就在那儿 |
| 音色 | `it-IT-ElsaNeural`：明媚女声，元音开放；基线 `+7% / +5Hz` | `it-IT-DiegoNeural`：松弛男声，喉音柔和；基线 `−7% / −4Hz` |
| 色彩 | 发 `#3B2A22`/`#5C4536` 蓬蓬卷马尾；肤 `#E9C199`/`#D0A070`；阿祖罗娃娃衫 `#6CB2EA`＋白裤 `#F5F1E8` | 发 `#40302A`/`#5F4B41` 随意微卷＋短须（脸型特征）；肤 `#E3B58C`/`#C89465`；亚麻蓝衬衫 `#7FB3E8`＋白 T＋卡其裤 `#B5A17E` |
| 动作 | heart（圆收下巴）；bounce `8`；眨眼 `2.8s`；呼吸 `0.015`；招牌＝`ciao-wave`＋`mini-jump` | tall；bounce `14`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`pocket-sway`＋半 `shrug` |
| 挂件 | 红发带（三色旗 wink）〔头〕；小挎包〔prop〕 | 挂绳太阳镜〔neck·swing·reflect〕 |

### 5.13 希伯来语 `he-IL`｜石榴紫红 `#C2385A`｜邻居：好奇 × 慢板

| | **נועה**（Noa，女·活泼） | **יובל**（Yuval，男·沉稳） |
| --- | --- | --- |
| 名字 | נועה（Noa）——"律动"，以色列女名榜首段 | יובל（Yuval）——"溪流/号角"，常青男名 |
| 人设 | 挎相机的观察者：探身凑近才肯罢休 | 慢悠悠的老哥：招手说"跟我来"，步子不快但稳 |
| 音色 | `he-IL-HilaNeural`：清脆女声，问句上扬；基线 `+6% / +4Hz` | `he-IL-AvriNeural`：温和男声，慢板；基线 `−6% / −3Hz` |
| 色彩 | 发 `#3A2C26`/`#5A473D` 高马尾碎发；肤 `#F4D5BE`/`#DEB196`；石榴红 T `#C75573`＋卡其工装短裤 `#A8926C` | 发 `#2E2723`/`#4C423B` 短卷 undercut；肤 `#E8BC94`/`#CD9670`；灰绿衬衫 `#8FA08C`＋白 T `#F5F3EE` |
| 动作 | round；bounce `9`；眨眼 `2.8s`；呼吸 `0.014`；招牌＝`lean-in`＋`brow-raise` | wide（宽和）；bounce `15`；眨眼 `3.6s`；呼吸 `0.008`；招牌＝`come-along`＋`nod`（慢） |
| 挂件 | 挎相机〔prop·swing〕；防晒帽（标识色）〔head·bounce〕 | 编织手环〔prop〕；大水壶〔prop·swing〕 |

### 5.14 粤语 `zh-HK`｜洋紫荆 `#B45EB8`｜街坊：心直口快 × 憨直

| | **阿晴**（女·沉稳） | **阿豪**（男·活泼） |
| --- | --- | --- |
| 名字 | 阿晴 *aa3 cing4*——"阿＋单字"街坊称谓，晴=明快 | 阿豪 *aa3 hou4*——同款命名法，港式常名（家豪/豪仔） |
| 人设 | 街坊百事通：淡定利落，边条巷有几级台阶都知 | 心直口快的好心人：挠着头憨笑，路没指错 |
| 音色 | `zh-HK-HiuMaanNeural`：明快女声，九声利落；基线 `−5% / −2Hz` | `zh-HK-WanLungNeural`：厚朴男声，尾音带笑；基线 `+7% / +4Hz` |
| 色彩 | 发 `#2B2632`/`#494253` 长直发空气刘海；肤 `#F3CBAA`/`#DDA582`；白 T `#F7F4EE`＋洋紫荆背带裙 `#B45EB8` | 发 `#2C2833`/`#4B4553` 碎盖头；肤 `#EDBD98`/`#D49C74`；米白 T `#F0EBDF`＋工装裤 `#6B7285` |
| 动作 | round；bounce `13`；眨眼 `3.4s`；呼吸 `0.009`；招牌＝`wave`（快）＋`head-tilt` | tall；bounce `11`；眨眼 `3.0s`；呼吸 `0.012`；招牌＝`scratch-head`（憨笑）＋`thumbs-up` |
| 挂件 | 透明发夹〔头〕；珍珠耳钉〔neck〕 | 胶框眼镜〔face·reflect〕；肩搭白毛巾（标识色毛巾条）〔prop〕 |

---

## 6. 示范场景开箱即用：《问路与指路》

> 场景二《说到颜色，你会想到什么》（六色一来一往问答）内容种子已成稿：[scene.md](../lessons/colors/scene.md)——同走本节 casting 范式（一来一往变体：双方互问互答）。**文化相关场景按语种独立原生创作，不设母本、不互译**：共享的只有骨架（六轮一来一往 + 再会），句式/联想物/道具/笑点逐语种独立设计（其 §1.2 为通用创作规则）。

### 6.1 Casting 表（speaker → persona）

场景叙事里的"A/B"是**角色槽位**，由 casting 数据映射到班底人物——文本（[asking-and-giving-directions.md](../../kb/arts-and-humanities/linguistics/comparative/example/asking-and-giving-directions.md) 终幕已带 A/B 标签）零改动，直接驱动双声线配音与双人站位。规则：**每语种的活泼者当 A（求知者视角），沉稳者当 B（向导视角）**——戏剧张力与"学习者视角/母语者示范"的教学分工天然对齐；casting 本身是数据，任何场景可任意改派。

| 语种 | A 问路人 | B 指路人 | 对手戏看点 |
| --- | --- | --- | --- |
| 汉语 | 林小满 | 江远 | 元气少女 × 惜字如金 |
| 英语 | Miles | Ruby | 迷路冒失鬼 × 冷幽默店掌柜 |
| 法语 | Chloé | Théo | 说走就走 × "等等"先生 |
| 德语 | Felix | Lena | 冲动徒步咖 × 掰着指头讲路 |
| 西班牙语 | Lucía | Mateo | 热情百灵鸟 × 慢板绅士 |
| 俄语 | Миша | Аня | 拍胸脯大哥 × 轻声小仙子 |
| 希腊语 | Ελένη | Νίκος | 双手演说家 × 捻珠哲学家 |
| 阿拉伯语 | عمر | ليلى | 开心果 × 静水向导 |
| 印地语 | प्रिया | अर्जुन | 好奇甜妹 × 折图学霸 |
| 日语 | ハルカ | リク | 元气应援 × 面瘫导航 |
| 韩语 | 도윤 | 서연 | 反帽鬼灵精 × 合账即答案 |
| 意大利语 | Giulia | Luca | ciao 行动派 × 插兜老好人 |
| 希伯来语 | נועה | יובל | 探身好奇 × 慢板老哥 |
| 粤语 | 阿豪 | 阿晴 | 憨直热血 × 淡定百事通 |

示范场景用到前 9 行（汉/英/法/俄/希/日/韩/印地/阿）；后 5 行随语料接入即刻可用——[expressions/directions.md](../../kb/arts-and-humanities/linguistics/comparative/expressions/directions.md) 已含德/西对齐对话，A/B 标签补上即演。

### 6.2 幕 × 说话人矩阵（情绪分支的现场验收）

示范场景六幕 + 终幕恰好把语气分支表全部演一遍——**第五幕"三档语气"就是情绪分支系统的产品级 Demo**（同一 B 角，对孙子/朋友/外乡人三档祈使）：

| 幕 | 内容 | 主说话人 | 情绪分支 |
| --- | --- | --- | --- |
| 一 | 拦人·道歉·"我迷路了" | A | `puzzled` |
| 二 | 把问题问出去 | A | `puzzled` → `neutral` |
| 三 | 方位与地标（领读） | B | `teach` |
| 四 | 把路讲清楚 | B | `neutral` → `encouraging` |
| 五 | 三档语气的"直走" | B | `emphatic` / `neutral` / `encouraging` |
| 六 | 道谢与回礼 | A → B | `happy` → `encouraging` |
| 终幕 | 整段对话 | A/B 交替 | 全分支轮转 |
| 逐词解释 | 元语言讲解（汉语） | **旁白**（`zh-CN-YunyangNeural`，系统播音、非班底、无立绘） | `teach` |

语料解析直接复用现役 [make_video.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/make_video.py) 的解析器：语种标签 → LangMeta；新增 `speaker` 维度 → casting 查 persona → (voiceId, rate, pitch)。

### 6.3 帧内三区布局（对接 requirement.md §1）

requirement 的界面分区在两种画幅下同构落地（三区比例进主题 token，角色区遵守双人站位规则：各占 1/3，说话者 `scale 1.05` 前移、听者压暗 0.85）：

```
16:9（1920×1080）                      9:16（1080×1920）
+------------------------------------+  +------------------+
| 文字区：逐词高亮字幕（高 22%）       |  | 文字区（上 18%）  |
+-----------------+------------------+  +------------------+
| 气泡区·提示      | 气泡区·思考      |  | 气泡区·提示/思考  |
+-----------------+------------------+  | （中 22%，上下叠）|
| 人物区：A 立绘    | B 立绘          |  +------------------+
| （左 1/3）       | （右 1/3）      |  | 人物区（下 60%）  |
+-----------------+------------------+  +------------------+
```

- **思考气泡** = B 收到问题后的 1.5s 思考停顿（[teaching-video-patterns.md](../../kb/tech/media/teaching-video-patterns.md) 模式四），承载关键词预览；
- **提示气泡** = 操作/跟读指引（"跟读一遍""注意第二声"），系统文案、不带人物口吻；
- 气泡尾巴三角指向说话者，A/B 交替时镜像；`ar`/`he` 语种整体 RTL 镜像（§5.8）。

---

## 7. 高质量与幂等保障

### 7.1 音色：高质量

1. **实测在册才可用**：28 个 voiceId 全部经 edge-tts 7.2.8 `list_voices()` 实时核验（2026-10-02，快照见附录 A）；新增/更换 voiceId 时先 `edge_tts.list_voices()` 实时核验再入档（不建独立 manifest 文件，附录 A 即快照）——声库下架/更名即 tts 阶段报错，**禁止静默自动换音色**（固定音色原则：迁移必须人工决策并更新档案）。
2. **声学多样性**：一语种两声互补（活泼=快/亮，沉稳=慢/厚），14 语种各自成对——学习者每课至少暴露两种语速/音区（多邻国"多样化声学特征训练"的直译）。
3. **冷门语种的唯一正路**：希腊/印地/阿语本地声库大面积缺位（[speech-systems.md](../../kb/tech/system-admin/speech-systems.md) §7.1 实测），视频端**只用离线烘焙音频**（[audio-narration.md](../../kb/tech/media/audio-narration.md) 硬立场：渲染器逐帧截图时 Web Speech 无时钟语义）。
4. **文本纯净隔离**：罗马字注音、中文释义永不入音；拉丁转写按既有分段体例（[kb/AGENTS.md](../../kb/AGENTS.md)）。
5. **节奏与响度**：每句尾 0.6–0.8s 呼吸位；所有音轨 ffmpeg `loudnorm` 统一响度后进时间线；情绪增量小步夹取（|rate|≤20%、|pitch|≤12Hz），任何分支不出破音。

### 7.2 用色：高质量

1. **token 化**：色值只存在于 `personas.json` 与主题文件；lint 禁止组件/模板出现 hex 字面量。
2. **可读性**：语种标识色上的文字对比度 ≥ 4.5:1（WCAG AA）；描边 `#4B4B4B`、1080 画布线宽 6px、圆角与三条缓动曲线全班底统一（[character-animation.md](../../kb/tech/media/character-animation.md) 一致性节）。
3. **可辨性**：标识色承担"语种一眼认"，但永远与国旗 emoji＋语种文字**双通道冗余**（沿用 [tts_page.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/tts_page.py) 状态栏既有设计）；示范九语横排相邻者避开同色系邻对。
4. **无刻板分配**：配色由性格与标识色决定，不做"粉色=女生"；文化元素几何化、低细节（§3 原则四）。

### 7.3 动作：高质量

1. **弹性物理**：`bounce`（spring damping）按能量档分参（活泼 8–11 / 沉稳 13–17），跳跃庆祝带 squash-stretch，全部复用 §4.2 原语库。
2. **确定性 idle**：眨眼/呼吸/微晃全部帧函数（`random(seed)` 错相、0.4Hz 正弦呼吸），同帧同貌（[character-animation.md](../../kb/tech/media/character-animation.md) 确定性 idle 一节）。
3. **口型同轴**：口型与逐词高亮字幕共用 `captions.json`（路线 B 三态口型：闭/开/宽），说话联动传导到眉与身体（`browLift`/`bodyScale`）。
4. **挂件物理**：项链/挂绳/围巾 swing、帽子 bounce、镜片 reflect——四锚点分层渲染，遮挡层级进 rig 常量。

### 7.4 幂等七则（验收必查）

1. **单一事实源**：`personas/personas.json` 是人物参数的唯一出处，进版本控制；班底规模=数据规模。
2. **渲染纯函数**：画面 = f(persona, course, frame)；禁 `Math.random`/`Date.now`/CSS animation/`setTimeout`（[remotion.md](../../kb/tech/media/remotion.md) 确定性守则 1–4）；同 props 渲染两次，`ffmpeg framehash` 逐帧一致为验收项。
3. **随机必带 seed**：一切随机走 `random(seed)`，seed 命名空间 = persona.id（如 `blink:xiaoman`），保证人物间相位错开且各自恒定。
4. **音频内容寻址**：缓存键 = `sha256(voiceId | rate | pitch | text)`，文件名即键；重跑命中即复用，**miss 才合成**——改文案只重合成变更句；情绪分支改参数即改键，天然隔离。
5. **参数显式锁定**：每次合成显式传 `rate`/`pitch`（个人基线+情绪增量的合成值），不裸调引擎默认；引擎版本 pin（`edge-tts==7.2.8`）。
6. **色板锁定**：lint 校验全部 hex 出自 token；改色=改 `personas.json`，重渲染全班底自动跟进（绝不出现"改了档案、视频还是旧色"的漂移）。
7. **资产版本锁定**：Remotion 全家桶同版本（4.0.532，[remotion.md](../../kb/tech/media/remotion.md) 版本快照）；音频/立绘资产清单带哈希，`npx remotion versions` 进 CI 检查单。

---

## 8. 实现路线

### 8.1 文件布局

```
une_usine_avec_des_machines_rugissantes/
├─ CLAUDE.md / README.md             # 项目规则（简）· 项目说明（新人入口）
├─ requirement.md / plan.md          # 需求与本规划
├─ adr-character-tech.md             # 人物生成技术选型裁定（§8.4 管线一续役的决策记录）
├─ self-introductions.md             # 28+4 × 10s 亮相卡内容种子（内容·语气·场景·分镜；RTL 4 卡含女性观众版）
├─ render-handbook.md                # ★ 工程与调优手册（架构/参数地图/验收/踩坑实录/recipes）
├─ run.ps1                           # ★ 统一入口（tts/assets/render/qa，两解释器分工封装）
├─ intro_cards.py                    # ★ 亮相卡管线（tts→assets→render，§8.2 契约；人物=多邻国式纯平涂矢量）
├─ qa_grid.py / qa_char.py / qa_all.py / qa_motion.py   # 验收工具（§9 与 self-introductions.md §3.2）
├─ personas/
│  ├─ personas.json                  # ★ 28 人档案（唯一事实源，schema 见 §4）
│  └─ intro-cards.json               # ★ 亮相卡数据（moods 表 / cast / lines / close 动作）
└─ build/intro/                      # 产物与缓存（.gitignore；音频缓存名=内容哈希）
   ├─ <id>.mp4                       # 32 × 10s 亮相卡（28 主卡 + 4 个 <id>_f 女性观众版；1080×1920@30fps，h264+aac）
   ├─ audio/                         # <key>.mp3 + <key>.json 词表缓存、<id>.m4a、<id>.timeline.json
   └─ text/                          # Edge headless 文字层（band/badge/pill/bubble 的 PNG+HTML）
```

声库快照以 plan.md 附录 A 为准（edge-tts 7.2.8 实测；新增语种时先 `edge_tts.list_voices()` 核验再入档，不建独立 manifest 文件）。管线侧不新增运行时副本：现役 [make_video.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/make_video.py) 与 HTML 管线 [tts_page.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/tts_page.py) 通过 `--personas <path>` 消费同一份档案（遵守 [kb/AGENTS.md](../../kb/AGENTS.md) "禁止复制粘贴运行时代码"）。

### 8.2 音频生成契约（两条渲染管线共用）

```
synthesize(text, persona, mood):
  rate, pitch = clamp(persona.voice 基线 + 共享情绪增量)     # §4.1
  key = sha256(voiceId|rate|pitch|text)[:16]
  if build/voice/<locale>/<key>.mp3 + build/captions/<key>.json 存在: 复用   # 幂等
  else: edge_tts.Communicate(text, voiceId, rate=…, pitch=…)
        → mp3；stream() 捕 WordBoundary 事件 → captions.json（词级时间戳）
  统一 ffmpeg loudnorm + 尾部 0.6~0.8s 静音呼吸位
```

词级时间戳同时驱动：口型三态（路线 B）、逐词高亮字幕（模式一）、打字机气泡（模式三）——**一轴三用**。

### 8.3 人物绘制规格（多邻国式头身，单一事实源 `intro_cards.face_geo()`）

单位 = 头高 H。脸型规格表 `FACE_SPECS`（2026-10-03 人物形象打磨：2 型 → **6 型按人设分配**，
不再"活泼一律圆脸、沉稳一律长脸"；heart＝上圆下贝塞尔圆收下巴（禁尖角——尖下巴观感像鬼）、square＝方颌，下颌轮廓由
`draw_character` 组合绘制，其余型为纯椭圆）：

| 脸型 | 头高 H | 头宽系数 WH/H | 观感 | 分配示例 |
|---|---|---|---|---|
| round | 356 | 0.955 | 婴儿圆宽头 | Miles/Chloé/Felix/Anya/Eleni/Omar/Haruka/Doyun/Noa/阿晴 |
| tall | 396 | 0.78 | 清瘦窄长 | Théo/Mateo/Nikos/Riku/Luca/阿豪 |
| oval | 386 | 0.84 | 端正匀称 | Ruby/Lena/Lucía/Layla/Seoyeon |
| wide | 348 | 1.02 | 宽和大气 | Misha/Yuval |
| heart | 372 | 0.90 | 圆收下巴俏丽 | 小满/Priya/Giulia |
| square | 392 | 0.88 | 方颌硬朗 | 江远/Arjun |

渲染与 qa 探针都从 `face_geo()` 取派生几何，永不漂移。**躯干与肩同宽、臂嵌进躯干轮廓、
肩楔填平头-肩缺口**（2026-10-03 重设计：剪影连续是硬要求，杜绝"头身手脱节/手像悬挂"——
见 render-handbook.md §5 坑⑪）：

| 部位 | 比例 | 说明 |
|---|---|---|
| 头占身高 | ~46% | 大头短身（2x 超采样实测占比；旧稿 ~48% 已过时） |
| 躯干宽 | 0.435×头宽 = 肩半宽 | **躯干与肩同宽**（宽高 0.52H）；肩楔三角衔接颈部两侧→肩峰 |
| 眼位 | 头顶下 0.615H | 低位大眼；瞳距 ±0.30×头宽；巩膜 0.28×0.34×头宽 |
| 眉位 | 巩膜顶**上方** 0.035H（brow_y = eye_y − 0.170×头宽 − 0.035H） | 胶囊眉紧贴眼上（帽檐/发带一律不压眉） |
| 嘴位 | 头顶下 0.815H | 张嘴半椭圆 + 舌；闭口为宽笑弧 |
| 腮红 | 头顶下 0.700H | 仅活泼型（±0.42×头宽） |
| 四肢 | 上臂 0.27H / 前臂 0.24H / 臂宽 0.155H / 手径 0.21H | 胶囊袖 + 袖口收边；**肩关节内收至躯干轮廓上**（`sh_hw − arm_w·0.30`），静止角 7° |
| 腿脚 | 腿宽 0.185H、腿距 ±0.145H；脚长 0.335H、外八字 +0.085H | 圆角鞋形 + 鞋头高光 |

画质工艺：**全链路 2x 超采样**（人物层、场景层、气泡尾、进度条按 2x 语义坐标绘制，
BOX 精确降采样 = 全形状抗锯齿）；无描边纯平涂 + 双色发丝高光 + 耳朵/衣领/侧体积影细节。
名牌/语言牌/气泡：药丸形 + 身份色/墨色描边 + 半透明投影（matte 双色抠像精确还原投影 alpha）。

### 8.4 管线一（现役）：亮相卡短片（`intro_cards.py`，已落地）

**实际落地形态**与本节初稿（扩展 make_video.py + SVG 立绘）不同：28+4 × 10s 亮相卡（RTL 4 语
另渲女性观众版，self-intro §1.4）由本仓库的
[intro_cards.py](../src/usine/intro_cards.py) 独立成线（tts → Edge headless 文字层 → Pillow 帧渲染 → ffmpeg），
工程决策与踩坑全部沉淀在 [render-handbook.md](render-handbook.md)。人物绘制规格见 §8.3
（`face_geo()` 单一事实源）。make_video.py 的 `--personas` 接入（示范场景《问路与指路》九语种
A/B 对话）仍按 §6 的 casting 设计推进，其音频契约走 §8.2，与亮相卡管线共用 personas.json。

### 8.5 管线二（备选态）：Remotion 班底 + 生成式人物

**裁定为备选**（非目标态）：技术选型详见 [adr-character-tech.md](adr-character-tech.md)——
MiniMax-H3 reference-to-video 生成人物动态层 + Remotion 编排合成的迁移案经评审**暂缓**，
Pillow 管线（§8.4）续役；本节规格保留，作为人物生成路线升级时的启动蓝图。
按 [kb/tech/media](../../kb/tech/media/README.md) 全套规范搭 Remotion 工程：

- `characters/Character.tsx`：分层 SVG rig（torso/head/eyes/mouth/arms + 四锚点挂件层），`<Character persona={p} mood={m} talking={openness} />` 一组件渲全班底；
- `generate-voice.ts`：§8.2 契约的 Node 版（渲染前跑一次，音频进缓存目录）；
- 人物动态层：MiniMax-H3 `--reference-image`（每班底一张定稿参考图）+ `--reference-audio`（edge-tts 产物直接喂生成端，口型跟随真实音素）——ADR §2 架构图；
- `calculateMetadata` 按音频真实时长反推 composition 时长（[audio-narration.md](../../kb/tech/media/audio-narration.md)）；
- 五幕模板（钩子/教/练/奖/CTA）+ `TransitionSeries` 转场；`Course16x9`/`Course9x16` 双注册共享场景组件（[teaching-video-patterns.md](../../kb/tech/media/teaching-video-patterns.md)）；
- course.json schema：`locale` + `dialogue[{speaker, text, sceneId}]` + `casting{A,B}`——**新场景 = 新 JSON，模板零改动**。

### 8.6 管线三（交互页）：HTML 产物的立绘与双声线

[asking-and-giving-directions.html](../../kb/arts-and-humanities/linguistics/comparative/example/asking-and-giving-directions.html) 一系交互页（[tts_page.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/tts_page.py) 构建）接入班底：

- **人物区**：同一份 personas.json 渲染 SVG 动态立绘（CSS keyframes 驱动眨眼/呼吸——交互页不受视频确定性守则约束，但循环参数取 persona 同款周期，尊重 `prefers-reduced-motion`）；
- **发音按钮**：A/B 例句分别锚定两位人物；Web Speech 加权选音器（既有评分算法不动）增加**性别锚定**——persona 附平台音名优先清单（如 macOS `Tingting`/Windows `Yaoyao`），无匹配性别音色时降级并在状态栏标 ⚠，**不静默错配**；
- 边界声明：交互页声库因观看者机器而异（既有架构如此），"固定音色"在交互页的语义是"固定声线画像 + 加权选音锚定"；**绝对固定只存在于烘焙音频的视频端**。

---

## 9. 分阶段落地与验收

| 阶段 | 交付 | 验收（全绿才进下一阶段） |
| --- | --- | --- |
| **M0 数据与校验** | `personas.json`（28 档案） | 覆盖矩阵 14 locale × {female, male} = 28/28；voiceId 全部 ∈ 附录 A 实测快照；`seed`/`id`/名字三元唯一；hex 合法且标识色上白字对比度 ≥ 4.5:1；情绪增量全部落在安全域内（**已达成**：qa_char 调色板探针逐卡对照） |
| **M1 亮相卡产线**（管线一，已落地） | `intro_cards.py` 三段管线 + 验收四件套 | 28 卡 + 4 个 RTL 女性观众版：qa_all 32/32 PASS + qa_motion PASS（幂等抽检内置于 qa_motion：重渲一卡视频流 framehash 逐帧一致）；人物剪影连续（臂-躯干 0 露底缝、名牌/文字资产无截断） |
| **M2 示范场景开箱** | make_video.py `--personas`《问路与指路》 | 终幕 9 语种 A/B 声线正确、站位/名牌/RTL 正确；幕五三档语气 ≥ 3 语种盲听可辨；重跑仅变更句重新合成（缓存命中日志）；既有 `run_tests.py`/`test_make_video.py` 全绿 |
| **M3 生成式人物 + 场景切换**（备选，见 ADR） | Remotion 工程 + H3 人物动态层 + course.json 化 | 同 props 渲染两次 `ffmpeg framehash` 逐帧一致；生成视频首/中/尾帧与 reference 图一致性抽检；口型-字幕同轴抽查（Studio 拖帧）；人物零改动、模板零改动，仅新增 JSON |

---

## 附录 A：实测声库快照（edge-tts 7.2.8，2026-10-02）

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

## 附录 B：参考与信源

- 需求输入：[requirement.md](requirement.md)（人物设定四模块 + 界面三区布局）
- 技术裁定：[adr-character-tech.md](adr-character-tech.md)（人物生成四路线裁定：Pillow 续役，H3+Remotion 备选）
- 工程沉淀：[render-handbook.md](render-handbook.md)（架构/参数地图/验收/踩坑实录）
- 示范场景：[asking-and-giving-directions.md](../../kb/arts-and-humanities/linguistics/comparative/example/asking-and-giving-directions.md) · [expressions/directions.md](../../kb/arts-and-humanities/linguistics/comparative/expressions/directions.md)（十一语对齐语料）
- 示范场景二（内容种子）：[scene.md](../lessons/colors/scene.md)（六色联想问答：14 语种原生剧本 / course.json 种子 / 六色词表——文化场景不设母本、不互译）
- 现役管线：[make_video.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/make_video.py) · [tts_page.py](../../kb/arts-and-humanities/linguistics/comparative/example/scripts/tts_page.py) · [kb/AGENTS.md](../../kb/AGENTS.md)（语言映射与 TTS 架构规范）
- 技术参考：[character-animation.md](../../kb/tech/media/character-animation.md)（persona schema/原语库/确定性 idle） · [lip-sync.md](../../kb/tech/media/lip-sync.md)（路线 B） · [audio-narration.md](../../kb/tech/media/audio-narration.md)（烘焙音频立场/内容缓存） · [teaching-video-patterns.md](../../kb/tech/media/teaching-video-patterns.md)（五幕/双人对白/思考停顿） · [remotion.md](../../kb/tech/media/remotion.md)（确定性守则/版本快照） · [speech-systems.md](../../kb/tech/system-admin/speech-systems.md)（九语音色生态矩阵与质量工程）
- 产品参考：[多邻国知识库/01-人物角色档案.md](../../多邻国知识库/01-人物角色档案.md)（命名工程/对立人格/反刻板十则） · [02-角色在产品中的作用.md](../../多邻国知识库/02-角色在产品中的作用.md)（声学多样性/叙事捷径） · [03-技术实现.md](../../多邻国知识库/03-技术实现.md)（定制 TTS 混合方案/viseme 管线）
- 对标台账：[benchmark-duolingo.md](benchmark-duolingo.md)（三维度逐条裁定：✅已达成/🔧补齐/📌备选/❌不采纳；含 quirk 治理规则）
