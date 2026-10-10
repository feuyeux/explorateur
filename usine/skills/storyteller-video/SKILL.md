---
name: storyteller-video
description: >
  Produce a pingshu-style (评书) character-profile video from a character
  dossier: a storyteller persona narrates in chaptered acts, each act staged
  as ONE coherent teahouse storyteller stage — wall with scene-registry
  props, a chapter plaque, the narrator in a bust close-up (the person fills
  over half the frame) behind a desk, and the narration text as word-level
  karaoke on a paper scroll lying open on the desk (gavel + folded fan
  beside it) — with a
  camera move (push-in / pull-out / pan) applied to the whole composite,
  cross-dissolve transitions between acts, and a gavel (醒木) accent at act
  open. Word-level karaoke timing rides on edge-tts word boundaries; acts
  are Pillow/Edge-headless rendered frames assembled frame-exact by ffmpeg.
  Use when the user asks for a 人物小传 / 评书风 video, a narrated
  chaptered story video with scene changes and camera moves, or to upgrade a
  karaoke-video multi-act project into storyteller staging. Not for
  single-card karaoke posters (that is karaoke-video), not for live-action
  footage (that is multilingual-video-poetry), not for authoring lesson
  content (that is lesson-scene).
---

# Storyteller Video（评书人物小传）

海报/卡片驱动成片的**评书化升级线**：一位说书人（编外专班 persona）以第三
人称娓娓道来，每幕一个连贯的书场舞台（幕匾 + 说书人半身近景 + 台口一案、
案上摊开的唱词书卷）、一镜（推/拉/摇）、一转场（叠化），幕开口一声醒木。
底层时间轴与合片**复用 karaoke-video 的全部机制**——本 skill 只新增
「舞台导演层」（幕 → 景/镜/转场），不另写时间轴。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **人物资料源**（如 kb 人物档：生平/回目/原文摘录） | 台词无从写起 |
| 2 | **幕表**（acts：每幕旁白文本 + 回目标题 + 场景 scene 列表 + 镜头 shot） | 无幕可渲染 |
| 3 | **说书人**（`feuille.data.storytellers()` 现取；缺省 changlianke） | 无旁白人设 |
| 4 | 台词风格（浓评书套语 / 平叙）与是否要醒木 | 台词与音效不确定 |
| 5 | 画幅（竖版 1080×1920 / 横版 1920×1080） | 帧几何无从校验 |

场景名一律**现取 `feuille.scenes.SCENES` 注册表真键**（65 名），姿态码现取
`rig.POSE_CODES`，情绪现取 `rig.MOOD_FACE`——不许自造（纪律 7）。

## 边界

**本 skill 是「多幕评书成片」的唯一事实源**：幕表 schema（景/镜/转场/醒木）、
镜头运动参数、叠化转场的实现与验收。词级时间轴与像素级验收**借用
`karaoke-video` 的脚本**（gen_tts / verify_sync / scan_blank），合片走本 skill 的
`assemble_storyteller.py`（叠化 + 醒木）——借用脚本不复制，改它们要回那个 skill。

**不做 / 转交**：

- 画人物 / 背景场景 / 注册表本体 → `character-rig`（实现沉在 library 的
  `rig` / `scenes`，本 skill 现取，不改注册表）
- 单卡片卡拉OK成片（无多幕导演层）→ `karaoke-video`
- 实拍母版压字幕 → `multilingual-video-poetry`
- **生成 BGM 床 / 定床位** → `bgm-bed`（醒木是 ffmpeg 合成的打击音，不是床）
- 写发布词 → `publish-copy`
- 真的点发布 → `multilingual-video-publishing`

## 场景模型（幕表 schema）

每幕一条记录（storyteller 项目的 `acts.py` 是唯一事实源，属性一律派生）：

```python
ACTS = [
  dict(
    id="a1",                       # 文件键（TTS/帧命名）
    chapter="第一回",               # 幕头回目标题
    subtitle="紫石街 · 帘下初见",   # 幕头副题
    text="……",                     # 旁白文本（TTS 输入）
    tokens=[...],                  # 展示 token（连续字符区间，karaoke 契约同源）
    vowel=[...],                   # 词面强调（染色）
    scene=["lantern_row", "table"],  # rig SCENES 真键列表（背景装置）
    shot=dict(kind="push", start=0.92, end=1.10),  # 镜头：起止缩放
    mood="neutral",                # 说书人本幕情绪（MOOD_FACE 真键）
    pose="both_hands",             # 说书人本幕姿态（POSE_CODES 真键）
    gavel=True,                    # 幕开口醒木
    quote="……",                    # 幕尾原文摘录（小字）
  ),
]
```

**舞台合成（单一空间，不是图层拼贴）**：墙（prerender_bg 渐变 + 幕 scene
道具；低处道具由台口护墙板遮挡）→ 挂幕匾（chapter/subtitle）→ 说书人
**半身近景**立绘（可见身高 ≈53%，是画面主角；站位常量在
render_act_frames.py 模块头，双手搭案沿）→ 案沿窄条（醒木与折扇摆条上）
+ 案身 → **案上摊开的唱词书卷**（卷尾两根立柱、卷面唱词 .tok/.pun、
卷尾 quote 小字；卷在人物身前，近景下手势展开 ±370 原生像素也扫不到侧挂
文字）→ 镜头变换**最后作用于整幅合成**（文字长在卷面上，随画面一起动，
不浮在镜头外）。字卡页（匾文 + 卷面 .tok/.pun）由 render_act_frames.py
从 TTS meta 的 text/tokens + 幕表章回**自生成**——黑底纯文字层走 Edge
headless 截图，字体用系统楷体（Kaiti SC）；dim 态用实色暗字而不用 opacity
（黑底会把半透明墨字压暗，matte 分不清"深色"与"半透明"）。

**镜头（shot）**：`kind ∈ {push, pull, pan_l, pan_r, static}`；`start/end`
是画布缩放系数（1.0 = 原尺寸；push 0.92→1.10 缓推，pan 配 xoff 位移）。
渲染层按帧内插值—— Ken Burns 式，逐帧确定性（同参数两渲逐字节一致，
rig 幂等不变量⑦同源）。

**转场（transition）**：幕与幕之间 0.5s 交叉叠化——前幕末帧与后幕首帧
alpha 混合若干中间帧（ffmpeg `xfade` 或预渲混合帧皆可；默认预渲混合帧，
因为它落在同一套逐帧管线里、可被 scan_blank/verify_sync 直接验收）。

**醒木（gavel）**：幕开口一声短促打击音（ffmpeg 合成：低频正弦衰减 +
噪声瞬态，20–60ms），与说书人拍案手 pose 同帧对齐。纯 ffmpeg 合成，
**不消耗任何额度**。

## 说书人

- 编外专班从 `feuille.data.storytellers()` 现取（`personas/storyteller.json`）；
  逐人字段契约与班底**同一份** `persona.validate_persona`，只豁免
  `validate_roster` 的语种配对不变量（编外不占 A/B 槽）。
- 音色基线写在人设 `voice` 段（voiceId/rate/pitch），经 `tts.voice_params`
  夹安全域；情绪增量沿用 `personas/voice.md` §1 共享表（情绪 = 基线 + 增量）。
- **配色组合纪律**：大胡子人设的 palette 必须与 rig 探针全绿（E1 颏下
  无胡须色）——衣色/颈色/胡须混合色两两 AA 中间色不得落进探针 tolerance
  带（changlianke 调色实录见 examples/panjinlian/README）。

## 管线（borrow + new）

```
acts.py（唯一事实源）
  → derive：voices.json + fonts   （派生脚本；字卡页已由 render 自生成，不再消费派生 HTML）
  → gen_tts.py            （karaoke-video 的，逐幕 TTS + 词级时间轴）
  → render_act_frames.py  （本 skill：书场舞台逐帧 + 自生成字卡页，镜头最后作用于整帧）
  → assemble_storyteller.py （本 skill：叠化转场 + 醒木对齐幕开口，帧精确合片）
  → scan_blank / verify_sync（karaoke-video 的，逐幕探针 + 白页哨兵）
```

## 验收判据

| 步骤 | 判据 |
|---|---|
| 人设 | `persona.validate_persona` 零问题 + rig 探针（verify_rig.probe_person）9/9 |
| 台词 | token 拼接还原原文；voice_params 夹安全域 |
| 帧 | 镜头内插值逐帧确定性（同参数重渲逐字节一致）；scan_blank 零白页 |
| 音画 | verify_sync 逐幕 × pre/word0/done 全 OK（**--intro 用 acts 配置值**） |
| 醒木 | 幕首帧 ±1 帧内有瞬态（astats 峰值窗），无爆音（≤ −3 dBFS） |
| 成片 | ffprobe 尺寸/时长/音轨规格；双流时长差 ≤ 1ms |

## 代码归属

拥有模块：（无）

镜头/转场/醒木的**渲染实现**全在本 skill 的 `scripts/`（直接执行的脚本，
不被 import——skill 层放「不会被 import 的资产」是仓库约定）；被 import 的
一切（`rig` / `scenes` / `persona` / `data` / `tts` / `audio` / `timeline` /
`compose` / `render` / `platform`）全在 **library** 与 infrastructure，
事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。
词级时间轴与合片脚本**借用** `karaoke-video`（其 SKILL.md 为机制说明书），
跨用不另写。
