# 工作样例：「一杯茶」12 语种视频三件套（全验收）

这是 2026-10 复用验证项目 `one-cup-tea-poster/video` 的成套源文件，横竖双画幅成片全验收（scan_blank 零白页、verify_sync 12 语种 pre/word0/done 全过、BGM 垫人声下 ~14 dB）。**模板 `assets/template/scenes.html` 只有 1 个 worked 场景；其余 11 种文字系的场景标记以本样例为准**——换主题时 `data-lang` 场景逐个替换文字内容，`.tok` 结构照抄（spoken order）：

- `voices.json` — 12 语种配音人物 + TTS 文本 + 显示 token；注意日语「お茶一杯」的 いっぱい 连读会产生嵌套词边界（一 0.38–0.84、杯 0.61–0.84），builder 按下一 token 起点切状态帧，嵌套无害
- `video.json` — 双画幅（landscape 1920×1080 → B站 / portrait 1080×1920 → 小红书、抖音）+ intro/outro 封面卡 + `bgm` 床（增益 0.13，淡入淡出 1.5s/3s）
- `video_src.html` — 12 个场景的完整标记 + 状态帧 JS（`?lang=&state=&fmt=`）；`.gold` 品牌汉字独占金色

场景内的着色 CSS 与 one-page-poster skill 的 `assets/example/poster_src.html` 同源；韩语 `.ksyl` 色块几何同样**必须按新字形用该 skill 的 `measure_korean.py` 重测**，不可照抄。
