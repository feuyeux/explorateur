# 工具指引（dsh 工具面）

工具面是产线的机器可执行面。**退出码就是判据**：0=过，1=检查不过/出错，2=用法错误。
SKIP 不是 PASS——把 SKIP 当 PASS 汇报就是造假。

## 选工具（按产线层）

- `usine_version` — 只读自检：@feuille/core 版本号。无副作用，可随时调。
- `usine_lesson` — 开新课件 / 体检已有课件（①–⑦ 七层，每条未完成带下一条命令）。开工第一步。
- `usine_scene` — 场景课产线：创意交接 → 解析 → 校验 → 成稿 → TTS 音频。
- `usine_persona` — 人设契约体检：28 人班底逐人校验 + 班底不变量。
- `usine_theme` — 主题自动匹配：话题/语种 → 5 套垂域主题推荐。
- `usine_poster` — 海报产线：字体子集 → 组装 → 截图 → 字符子集门 → 四色验收 → 叠印对齐。
- `usine_cover` — 封面产线：整页 HTML → 平台规格整图截图 + 尺寸/底色验收。
- `usine_karaoke` — 词级卡拉OK成片：TTS 词级时间线 → 状态帧渲染 → 组装 → AV 同步验收。
- `usine_poetry` — 实拍母版成片诊断：人声段/空档段 LUFS 对比 + 文字压实拍量化。
- `usine_storyteller` — 评书成片：幕帧渲染（舞台 + 人物 + 卡拉OK字卡）→ 叠化转场 → 醒木混音。
- `usine_bgm` — 纯器乐 BGM 床生成（Lyria 免费层）+ 拍速反查/频段分布/床长实测判据。
- `usine_copy` — 发布词自检：三平台字数/钩子/置顶话术/no-hard-wrap/AI 指纹 + 数字溯源。零平台流量。
- `usine_ledger` — 产物缓存账本：谁过期了、因为什么。
- `usine_framehash` — 逐帧像素基线：save 采集分桶落盘，check 零漂移门禁。
- `usine_quota` — 查套餐额度（只读不烧额度）。**提交视频生成前必查**。
- `usine_verify` — 跑 usine 全量门禁（typecheck + vitest，约 1 分钟，别并发跑）。
- `usine_video_generation` — 视频生成母版。三条线（Hailuo-2.3 走套餐额度 / H3、H3-Max 扣积分）。**每次执行强制人工审批**。

## 工具面外的工具

- `usine_publish` — **默认不注册**，工具面里根本没有它（config 显式开启才挂）。不要建议用户开启，不要用 shell 命令绕。

## 通用口径

- 工具都是进程内直调 @feuille/* 包，没有 subprocess 桥。
- `usine_verify` 跑全量门禁，约 1 分钟，**不要并发跑多个**。
- 工具外的路径没有验收口径。绕开工具面做出来的东西，验收时一律不算过。
