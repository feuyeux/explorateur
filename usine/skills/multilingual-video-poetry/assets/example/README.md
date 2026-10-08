# 工作样例：《春夏秋冬》12 语种四季诗 · 短视频管线全链路

2026-10 复用验证项目 `examples/sijijie` 的源文件（12 语种 × 4 季 = 24 条成片，
横竖双画幅全验收）。**本目录是入库的事实源**——`examples/` 项目目录是本机
工作副本（被 `.gitignore` 排除，不入库），fresh clone 上只有这里这份。改写 /
对照从这里取；实跑在本机项目目录里，命令前缀为
`uv run python examples/sijijie/<文件名>`。

| 文件 | 是什么 |
|---|---|
| `朗诵.md` | 12 语种诗稿正文（人写，各用其正格 + 格律注释 + 文化气息） |
| `poems.py` | 诗稿 / 声称表 / 手写音节拆分——**诗的单一事实源** |
| `配文.py` | 四季窗口 / 12 音色 / 48 句短视频配文 / 文化标记——**短视频文案的单一事实源** |
| `季节与译文.py` | 各语种本土季词 + 中文译文 |
| `build_voice.py` | edge-tts 合成 48 段 + **实测时长校窗**（4 次重试 + 指纹缓存） |
| `subtitles.py` | 三层字幕 HTML → Edge headless 透明层 → ffmpeg 烧录 |
| `mix.py` | BGM + 旁白侧链混音 → 挂到已烧字幕的成片 |
| `封面.py` | 24 张封面（1080×1440，3:4） |
| `小红书文案.md` | 24 条发布文案（标题 + 正文 + 标签），`封面.py` 与 `plans.py` 共读 |

> `小红书文案.md` 与 `配文.py` 是**同一份项目数据**，在
> `multilingual-video-publishing/assets/example/` 下也有一份入库副本（`plans.py`
> 读它）。**两份入库副本必须一致**——改了一侧就同步另一侧（都在 git 里，
> diff 可查）。**发布词本身的事实源是 `publish-copy` skill**——本文件是它的
> 输入样本，不是它的家。

## 顺序不能换

每一步的产物是下一步的输入：

```bash
uv run python examples/sijijie/build_voice.py   # 48 段 TTS + 校窗
uv run python examples/sijijie/subtitles.py     # 96 张卡片 + 24 条烧字幕版
uv run python examples/sijijie/mix.py user      # 混音并挂载 → 24 条成片
uv run python examples/sijijie/封面.py           # 24 张封面
```

**先定边界再写词。** 慢放倍数是被实测逼出来的：定 1.6× 时 48 段里 11 段超窗，
且全部集中在最短的季节；改 2.0× 才归零。

## 换主题时最容易踩的三处

- **字体栈不要抄进脚本**，从 `languages/<locale>/manifest.json` 取——诗配文要书体感
  就用新加的 `displayFontCss` 键，不要为了好看换掉整条栈。
- **文字颜色与画面用色不能靠色**，先量该季文字区的背景亮度再决定往哪调
  （实测四季相差 3.6 倍，冬季最亮，p90=0.601）。
- **`mix.py` 的三个坑**（人声整段消失 / BGM 忽隐忽现 / 结尾提前静音）根因各不相同，
  排查手段见 SKILL.md 的「混音出问题时，按这个顺序查」——别用同一个解释套三个症状。