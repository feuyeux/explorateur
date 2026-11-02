# assets/template — 状态帧、装配契约与两个机检脚本

这里的东西是**可复制的骨架**，不是某个项目的成品。复制后只改 DATA、几何与
项目配置；脚本顺序、旗标、判据不要重写（每一条都对应
`references/music-av-traps.md` 里的一个坑）。

## status-frame.html

最小可跑的状态帧页面（1920×1080）。样例场景 `A` 含 4 个和弦块、48 根波形柱、
4 条事件线与 JS 播放头。

```bash
# 预览（把浏览器路径换成 platform.browserPath() 的解析结果）
<浏览器> "file:///<绝对路径>/status-frame.html?scene=A&state=2&ph=26.4"
```

URL 参数：

| 参数 | 含义 |
|---|---|
| `scene` | 裸场景名（`A` / `B` / …）或卡片别名（`intro` / `credit`）。不要传 `scene-A`。 |
| `state` | `-1` 全暗；`0..N-1` 高亮 `current[state]`；`>=N` 全部完成。 |
| `ph` | 播放头秒数。只由页面 JS overlay 渲染；静态基图里不要烘播放头。 |

页面里写死的纪律（改之前先读 traps）：DATA 在消费者之前（§5）、卡片别名
显式列全（§6）、caption 是块级 div（§13）、时间码 `text-anchor="end"`
（§16）、播放头单一实现（§17）、波形统一 `vmaxRef`（§15）。

## project.json

装配契约模板：`scenes[]` 的几何/时间、`audio.tracks[]` 的 offset + gain
envelope、ducking、响度目标、含墨阈值、credit 不动点。`feuille karaoke build`
的固定增益 `amix` 表达不了这份契约，builder 要自己实现（或等 `@feuille/music`
归流）。

## sources.json / facts.json

- `sources.json` —— 许可账本：每件录音/乐谱/**史料图**的 URL、许可、
  attribution、获取日期、sha256。`kind:"image"` 另带 `creator` / `date` /
  `file_url` / `width` / `height`。
- `facts.json` —— 制作信息页与发布词的唯一数字源：每个数字都带 `source`，
  `credit.source_ids` 指向 `sources.json`；`visuals[]` 把每张图的用途
  （`full-bleed` / `inset` / `background`）、图注与 `source_id` 绑定。

两份都是模板，`{{…}}` 是占位符。交付前必须替换并跑校验器。

## ink-scan.mjs — 含墨扫描

本产线的验收判据。**不要用 `feuille karaoke scan-blank`**：它判
`min(R,G,B) >= 250`，暖纸 `#f7f2e6` 的最小通道是 230，对空纸完全盲。

```bash
# 扫描成片（1fps 采样；任一层低于 0.2% 含墨即退出 1）
node ink-scan.mjs <video.mp4> [more.mp4 …] \
  --ffmpeg <ffmpeg 绝对路径> --ffprobe <ffprobe 绝对路径> \
  [--fps 1] [--gray 200] [--min-pct 0.2] [--json]

# 反向自测：暖纸空页必须 FAIL、0.46% 墨量的标题卡必须 PASS
node ink-scan.mjs --self-test \
  --ffmpeg <ffmpeg 绝对路径> --ffprobe <ffprobe 绝对路径>
```

两个可执行文件路径必须显式给（不写死可执行名，不走 PATH 兜底）。在本仓里
用 `@feuille/core` 的 `platform.ffmpeg()` / `platform.ffprobe()` 解析后传入。

## validate-facts.mjs — 事实/许可账本校验

```bash
# 交付模式：占位符、缺 source、未知 source_id 全部退出 1
node validate-facts.mjs --facts facts.json --sources sources.json

# 模板模式：允许 {{…}}，只查结构
node validate-facts.mjs --facts facts.json --sources sources.json --template

# 反向自测：好账本必过、占位符/未知来源/缺 source 必抓
node validate-facts.mjs --self-test
```

判据：`facts.numbers[]` 每项必须有数字 value + unit + source + measured_at；
`credit.source_ids` 必须存在于 `sources.json` 且对应素材有 attribution；
`kind:"image"` 必须有 `creator/date/file_url/width/height`，`full-bleed`/
`background` 长边 ≥1600px、`inset` ≥900px；`facts.visuals[]` 只能引用
`image` 来源；交付模式不许留 `{{…}}`。
