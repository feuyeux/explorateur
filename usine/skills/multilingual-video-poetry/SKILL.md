---
name: multilingual-video-poetry
description: >
  **[Requires a live-action master footage clip]** Produce a narrated video
  whose picture is real filmed footage, with per-language voiceover and
  three-layer subtitles burned on top — TTS timing fitted to frame-measured
  scene windows, Edge-headless multilingual typography over that footage,
  sidechain BGM mixing, and platform cover/caption sets. Use when the user has
  or will supply filmed footage and wants narration and subtitles over it. Use
  for RTL/Indic subtitles that libass cannot shape, for a voiceover+BGM mix
  where narration disappears or fades early, and for ffmpeg filtergraph bugs
  that silently drop or attenuate a track. Do NOT use when there is no
  footage — a poster/card-driven narrated video is karaoke-video, and posters
  themselves are one-page-poster.
---

# 多语种配文短视频管线

产出「同一条画面 × N 种语言」的视频：每语种独立配文、独立 TTS 旁白、烧录三层字幕。
参考实现见 `assets/example/`（12 语种 × 4 季 = 24 条成片，源文件已归档）。

## 前置输入契约

**⛔ 第 1 条是硬门禁，没有它整个 skill 不适用。**

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **一条实拍母版视频** | **本 skill 不适用**。没有实拍就转 `karaoke-video`（海报/卡片驱动）——不要拿占位画面硬跑 |
| 2 | 语种范围与每语种配文 | TTS 无从合成；且各语种要按其**正格**写，不是同一句话翻 12 遍 |
| 3 | 画幅与母版时长 | 字幕卡片几何与场景窗口无基准 |
| 4 | 是否要 BGM | 决定走侧链压缩还是线性 `amix` |

**先有母版，再谈一切。** 场景边界必须**逐帧密集取样实测**后回填 `配文.py` 的 `WINDOWS`，**不许均分**——画面里最短的那段往往就是最容易超窗的那段。慢放倍数同理，是被实测时长逼出来的（参考实现：1.6× 时 48 段里 11 段超窗且全在最短的季节，2.0× 才归零）。

配文文件按 `assets/example/配文.py` 的 schema 写：`VOICES` / `LANGS` / `LINES` / `WINDOWS`。`LANGS` 顺序即交付顺序。

## 边界

**本 skill 是「实拍画面驱动」的成片事实源**：母版逐帧实测 → TTS 校窗 → 三层字幕压实拍 → **侧链 BGM**（底床要被旁白动态压住）→ 封面。

「文字压在实拍上」的判据在这里：**文字颜色不能靠色**，先量该季文字区背景亮度再定；且 **WCAG 对比度不适用于彩字压实拍**，会把已验收的成果误判为不达标。

BGM 在这里是**侧链压缩**。海报/卡片驱动的线性 `amix` 方案在 `karaoke-video`，**不要实现第二份**。两种压法读的都是同一条床——**床的生成与床位定标（Lyria 调用 / 采样率解读 / 频段自检 / `gain` 反推）统一在 `bgm-bed`**，这里只管怎么压。

字体栈仍从 `languages/<locale>/manifest.json` 取（`fontCss` 或书体感更强的 `displayFontCss`），**不在脚本里另抄**——多语种排版技术的事实源在 `one-page-poster`。

**不做 / 转交**：

- **没有实拍母版** → `karaoke-video`（海报/卡片驱动的成片）
- **生成 BGM 床 / 定床位** → `bgm-bed`
- 做海报、字体子集、逐字着色 → `one-page-poster`
- 写发布词 → `publish-copy`
- 真的点发布、建合集 → `multilingual-video-publishing`

## 代码归属

拥有模块：（无）

本 skill 不拥有任何模块：格律审计（`audit`）、TTS 与音轨（`tts` / `audio`）、渲字与封面（`textlayer` / `covers`）全在 **library**，与海报线、karaoke 线共用；跨用走 library 的实现，不要另写一份。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

## 顺序不能换

每一步的产物是下一步的输入，顺序错了后面全部白做：

```
逐帧实测场景边界 → 慢放定时长 → 写配文 → TTS 实测校窗
    → 字幕烧录 → 混音挂载 → 封面/文案
```

**先定边界再写词。** 边界是逐帧密集取样实测的，不是均分——画面里最短的那段
往往就是最容易超窗的那段。

**慢放倍数是被实测逼出来的，不是先定倍数再凑文字。** 定 1.6× 时 48 段里 11 段超窗
且全部集中在最短的季节；改 2.0× 才归零。慢放的收益是给每段更多时间窗。

## 每一步的验收判据

没有可测判据就等于没做完：

| 步骤 | 判据 |
|---|---|
| 边界 | 逐帧取样拼图目视确认，不是凭印象 |
| TTS | **每段实测时长 ≤ 该季窗口**，超窗就压词，不是超了就硬塞 |
| 字幕 | **先量后看**：`color_contrast.py --gate <标定阈值>` 逐季二值判据全 PASS（阈值在已目视验收的成片帧上标定），再抽帧目视复核 |
| 混音 | 人声段 − 空档底床 ≥ 8 dB；底床全程无断点 |
| 收尾 | 音频在**画面结束那一刻**归零，不是提前哑、也不是戛然而止 |
| 成片 | 逐条 ffprobe 尺寸/时长/音轨规格 |

## 混音出问题时，按这个顺序查

**不要只听最终混音。** 把滤镜图拆成独立分轨逐段对比，是唯一定位手段：

```
人声干轨  vs  被压 BGM 轨  vs  最终混音
```

三者逐 0.1s 对比，一眼看出是哪一环丢的。`scripts/audio_profile.py` 做这件事。

三个坑都表现为「声音听起来不对」，但根因完全不同：

1. **人声整段消失** → 同一个 filter 输出被两个滤镜引用时 ffmpeg 不自动拆分，缺 `asplit`
2. **BGM 忽隐忽现** → `loudnorm` 排在 `afade` 之后，把淡出尾巴冲掉了
3. **结尾提前静音** → `atrim` 终点等于淡出终点，没有余量可淡

坑 1 的症状极具欺骗性：侧链拿到的是完好的信号，所以 BGM 一直在被**正确压低**，
但主混音里根本没有人声。听感是「BGM 忽强忽弱却没有旁白」——会被误判成两个问题。

诊断工具（把上面三个坑都定位出来的那个）：

```bash
# 人声段 vs 空档底床，LUFS 口径，配比判据
echo '{"voice":[[0.55,2.88],[5.75,8.22]],"gaps":[[3.13,5.50]]}' | \
    uv run python skills/multilingual-video-poetry/scripts/audio_profile.py 成片.mp4

# 不传窗口：逐 0.1s 电平曲线，用于看断流与淡出
uv run python skills/multilingual-video-poetry/scripts/audio_profile.py 成片.mp4
```

⚠️ **配比判据必须用 LUFS 不能用 RMS**——同一段混音两种口径差 6.3 vs 8.2 dB，
拿 RMS 比会得出「不达标」的假结论。

详见 `references/ffmpeg-pitfalls.md` 与 `references/audio-measurement.md`。

## 文字压在实拍画面上

**不要用 ffmpeg subtitles 滤镜，也不要用 Pillow 画文字。** 前者常缺 libass；
后者 `raqm=False` 无 HarfBuzz/FriBiDi，阿拉伯／希伯来／天城文会散字错向。
用 `src/feuille/textlayer` 的 Edge headless 截图，Chromium 内核自带完整塑形。

- 透明叠加层用 `shoot_matte`，不透明成图（封面）用 `edge_screenshot`
- **Edge 截图必须串行**，并发会被 SIGKILL，炸掉是整批重做
- 字体栈一律从 `languages/<locale>/manifest.json` 取，不在脚本里另抄
- **文字颜色与画面用色不能靠色**——先量该季文字区的背景亮度，再决定往哪调

```bash
uv run python skills/multilingual-video-poetry/scripts/color_contrast.py \
    --seasons 母版.mp4 --cards cards/横版
```

实测发现四季背景亮度相差 **3.6 倍**（冬季 p90=0.601，其余三季 0.168–0.328），
这才是冬季配色要多压两档的可测原因。注意 **WCAG 对比度不适用于彩字压实拍**
（会把已验收的成果误判为不达标）。

**「可读」可以降级成二值判据**：`--gate <min_gap>` 给出后，脚本算每季
`|字芯亮度 − 环带背景 p90|`，低于阈值的季 FAIL、退出码 1；未量到的季在 gate
模式下也算 FAIL（SKIP 不是 PASS）。**阈值没有默认值**——在已目视验收的成片帧
上实测后标定再给；拿四季归档数字或 WCAG 当普适阈值就是编数据。判据纯函数
`gap_verdict` 的反向验证在 `usine/scripts/verify_skill_scripts.py`。

```bash
# 量 + 二值判据（阈值自标定）：CI / 验收官可抓退出码
uv run python skills/multilingual-video-poetry/scripts/color_contrast.py \
    --seasons 母版.mp4 --cards cards/横版 --gate 0.30 --gap-ref p90
```

详见 `references/typography-over-footage.md`。

## 发布物料

封面 1080×1440（3:4），文案标题 ≤ 20 字。**批量内容不要共用一个模板**——
结构雷同本身就是异常信号。开头方式、段落长度、标签都要逐条错开。
抽帧用**无字幕母版**，不要用已烧字幕的成片，否则封面上一屏挤两层字。

## 参考实现里的可复用文件

`assets/example/`：`配文.py`（文案单一事实源）、`季节与译文.py`（季词/译文/配色）、
`build_voice.py`（TTS 校窗）、`subtitles.py`（三层字幕 + 烧录）、
`mix.py`（混音挂载）、`封面.py`（封面）。运行顺序与换主题的坑见该目录的 `README.md`。