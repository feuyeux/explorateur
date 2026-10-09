---
name: video-generation
description: >
  Produce the H3-class master footage clip (母版) for a content project by
  choosing between the three mcode-tools video lines — Hailuo-2.3, H3 and
  H3 Max — showing the prompt / aspect ratio / duration / resolution /
  cost nature and getting explicit human approval before submitting, then
  fetching the finished clip and freezing it. Use when a project needs a
  live-action master clip as its picture base, when deciding which video model
  to burn quota on, or when a Hailuo-2.3 clip will not meet the duration or
  resolution requirement and the choice is whether to escalate to H3 (which
  spends credits, not plan allowance). Not for overlaying subtitles, narration
  or BGM onto an existing master (that is multilingual-video-poetry), not for
  poster/card-driven finished videos (karaoke-video, storyteller-video), and
  not for image, audio or music generation.
---

# 视频生成（母版生产）

一条母版 = **一段实拍画面 + 一次性的额度花费**。本 skill 只把这两样做成可复现的：
**选哪条线**（三条线扣的不是同一个账）、**提交前摆清楚让人点头**、**取回后冻结**。

**母版纪律（来自 `usine/AGENTS.md` 铁律，本skill 的执行细则）**：一次生成、
按画幅成对、生成后冻结；后续一切加工只做叠加（字幕 / 配音 / 封面），
**永不重复消耗**。母版与画幅几何在配置里**成对绑定**：换档位 = 换一份母版 +
一套文字层尺寸。

## 三条线：扣的不是同一个账

`mcode-tools` 的三条视频线**消耗性质完全不同**，选错就是白烧额度：

| 线 | 扣什么 | 时长 / 画质 | 出片 | 参考素材 |
|---|---|---|---|---|
| **`MiniMax-Hailuo-2.3`** | **Token Plan / M Plan 套餐额度**（不烧积分） | 768P 6s / 10s、1080P 6s | 快 | ❌ 不支持 |
| `MiniMax-H3` | **只扣积分**，不吃套餐额度 | 768P / 2K，4–15s 整数 | 15–30 分钟 | ✅ ≤9 图 + ≤3 视频 + ≤3 音频 |
| `MiniMax-H3-Max` | **只扣积分**，不吃套餐额度 | 480P / 768P，5–15s 整数 | 约 20 秒 | ❌ 不支持 |

### 默认选 Hailuo-2.3

**只要套餐额度还有余额，就不要为同一条母版烧积分。** H3 / H3 Max 留到
「Hailuo 的时长或画质确实不满足」时再用，且要在展示里写明「本条走积分、约扣
多少积分」。

**Hailuo-2.3 的三条边界**（选之前先认，用了才知道）：

- **时长/画质有限**：只有 768P 6s / 10s 与 1080P 6s。要更长或 2K → 升 H3。
- **成片静音**：母版**不带原生音轨**。这对本管线反而常是优点——旁白
  （`library.tts`）与底床（`bgm-bed`）本来就要各自叠上去，母版自带声音
  反而打架。
- **不支持多模态参考**：不能传参考图/视频/音频来锁人物、风格或声音。要锁
  风格 → 升 H3。

**积分速查**（1000 积分 = ¥7）：H3 768P ¥0.50/秒 ≈ 71 积分/秒；2K ¥0.80/秒
≈ 114 积分/秒；H3 Max 480P ¥0.33/秒 ≈ 47 积分/秒。**传参考视频按同价另计一份
时长费**（图片前 5 张免费、每张 ¥0.20）——带参考素材时账单是双份，算积分别忘了。
套餐额度用 `mmx quota` 查。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **画面描述（提示词）**：主体 / 动作 / 场景 / 镜头 / 情绪 | 无从生成 |
| 2 | **画幅**（如 16:9 与 9:16 —— 按母版纪律**成对**） | 母版与文字层几何无法成对绑定 |
| 3 | **时长**（Hailuo 6/10s；H3 4–15s 整数） | 时长不可事后拉伸，只能重生成 |
| 4 | **是否要锁人物/风格**（要 → 得上 H3 传参考素材） | 选线错，Hailuo 做不到 |
| 5 | **套餐额度是否够**（`mmx quota`） | 决定走 Hailuo（不烧积分）还是 H3（烧积分） |

## 边界

**本 skill 是「母版生产」的唯一事实源**：三条视频线的选线优先级、提交前的
展示清单、额度与消耗估算、取回与冻结。

**不做 / 转交**：

- 把母版压字幕、配文、加旁白、侧链混音、封面 → `multilingual-video-poetry`
  （实拍母版驱动的成片）
- 海报/卡片驱动或说书人立绘驱动��成片（画面是渲染的，不碰视频模型）→
  `karaoke-video`（单卡片）/ `storyteller-video`（多幕评书）
- 生成 BGM 床 / 定床位 → `bgm-bed`
- 做海报、字体子集、逐字着色 → `one-page-poster`
- 生成图片 / 语音 / 音乐 → 不归本 skill（用 mcode-tools 对应工具）

**铁律**：绝不自动调用。额度消耗只在内容项目里逐次发生，提交前必须拿到人的
明确同意——「你直接跑」不算授权。

## 代码归属

拥有模块：（无）

本 skill 只有说明书——生成动作走 `mcode-tools` 通道（MCode 运行时自带），不在
`src/feuille` 下留实现。它没有进 library：母版消费侧的字幕/旁白/混音在
`multilingual-video-poetry`，两边不共享代码。事实源见 `usine/ownership.json`，
由 `verify_skills.py` 与本段双向机检。

## 怎么用

提交前把**提示词 / 画幅 / 时长 / 分辨率 / 消耗性质**摆给人看，拿到同意再提交。
这是铁律，不能跳。

```bash
# Hailuo-2.3（默认；走套餐额度，不烧积分）
#提交一个异步任务，返回 task_id
mcode-tools connector call connector__matrix__submit_video_generation --args '{
  "model":"MiniMax-Hailuo-2.3",
  "prompt":"<把画面描述贴这里>",
  "duration":6, "resolution":"768P"
}'

# 轮询（带同一个 task_id 与 model）
mcode-tools connector call connector__matrix__query_video_generation --args '{
  "task_id":"<task_id>", "model":"MiniMax-Hailuo-2.3"
}'

# 下载：task 成功后拿 video_url（链接临时、7 天内有效；本地素材先用
# upload_temp_url 换 URL）
curl -sL -o 母版.mp4 "<video_url>"
```

`prompt` 上限 7000 字符；素材只能传 URL（本地先 `mcode-tools upload_temp_url`）。
H3 文本生视频要显式给 `ratio`；Hailuo 不需要。

## 验收判据

| 步骤 | 判据 | 不达标怎么读 |
|---|---|---|
| 选线 | 套餐额度够 → Hailuo；不够/时长画质不够 → H3（报积分） | 一律优先不烧积分 |
| 提交 | 展示清单齐、拿到明确同意 | 未拿到同意不提交（铁律） |
| 取回 | 任务 `succeeded`，拿到 `video_url` 并落盘 | `failed`/`cancelled` 不重试烧额度，先看报错 |
| 冻结 | 母版 + 画幅几何成对绑定进配置 | 未绑定 → 后续加工会错位 |
| 母版可用 | 母版无字幕/无旁白（叠加前的干净基底） | 已有字幕的成片不能当母版再加工 |

⚠️ **母版别重复生成**：一次生成后冻结。换画幅 = 换一份母版 + 一套文字层尺寸，
不是「再叠一次」。生成类命令默认不覆盖已有文件，要覆盖显式 `--force`。

## 与其它层的分工

- **额度纪律的权威文本在 `usine/AGENTS.md` 铁律「H3 与额度」**；本 skill 是它的
  执行细则（选线顺序、展示清单、消耗估算）。
- **工具条目在 `docs/toolchain.md`**（⑥ 视频阶段的 H3 行）。
- **成片消费母版在 `multilingual-video-poetry`**；本 skill 只负责「把母版生出来
  并冻结」，不碰母版上的字幕 / 旁白 / 混音。