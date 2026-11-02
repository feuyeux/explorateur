读完了 `SKILL.md`（156 行）和 `references/music-av-traps.md`（134 行），并把里面点到的实现逐条对齐了仓内代码（`packages/karaoke`、`core`、`bgm`、CLI 路由表、gate 门禁）。结论先说：**内容资产是全仓最好的一份翻车记录，但作为「另一个 agent 能照着执行的 skill」，它现在有三个断点**——唯一脚手架指向一个不存在的目录、一条渲染纪律与仓库铁律正好相反、验收判据没有实现物。机检是绿的（`skills.test.ts` 4/4 通过），所以这些洞门禁抓不到，全在语义与资产层。

## 一、阻断级（照文档做会做错或做不出来）

**1. 唯一脚手架是幻影，18 条坑的价值因此悬空。** `SKILL.md:31-33` 和 `:149-152` 要求「从 `usine/examples/dvorak-new-world/tools/` 抄，不要凭记忆重写」，但 `usine/examples/` 下只有 `locative-12lang` 与 `nine-arts`，`git ls-files` 里没有任何 dvorak 记录，`.gitignore:53` 的 `examples/` 又保证它永不入库。文中点名的 6 个脚本（`opening_timeline` / `theme_timeline` / `b2_build` / `b4_build` / `credit_card` / `probe_movs`）盘上与索引里都不存在。这同时违反工作区自己的落位规则（AGENTS.md 第四节：可复用脚手架属于 `skills/<skill>/assets/`），而 `karaoke-video/SKILL.md:27` 已经是正确写法（"scaffold from `assets/example/`, not from past project directories"）。后果正是 skill 明令禁止的那件事：只能凭记忆重写，18 条坑会原样重踩。


**2. 渲染纪律与铁律相反，按文档做会在 macOS+Edge 挂死。** `SKILL.md:96-97` 要求「mock-keychain + basic password-store + 独立 user-data-dir 三个旗标」。但 `usine/AGENTS.md:104` 明令「`--headless=new` 且**不带** `--user-data-dir`」，`packages/karaoke/src/build_video.ts:70-71` 记着实测原因（图能出但进程永不退出），`packages/poster/test/poster.test.ts:542-561` 还有反向断言。而且旗标清单漏了真正影响像素的两个：`--force-device-scale-factor=1` 与 `--hide-scrollbars`（`packages/core/src/textlayer.ts:68-83`）——少了前者截图会随系统缩放漂移。源头在 `karaoke-video/references/av-sync.md:103-107`（本 skill 声称「全条沿用」的那份文件）也写着要带，两处得一起修；更稳的做法是让本 skill 直接指向共享入口 `edgeScreenshot` / `platform.HEADLESS_FLAGS`，不再手抄旗标。


**3. 运行路径与工作区纪律冲突，但技术上已无必要。** `SKILL.md:134-137` 教 uv + python 3.11 + librosa/mido，而工作区 AGENTS.md 第三节定的是「全量 TS 化，运行与门禁一律 pnpm，残留 Python 只作参考」。关键在于「没有 FFT 才得用 Python」这个前提已经站不住：`packages/bgm/src/gen_bgm.ts:185` 的自写 `rfft`（radix-2 + Bluestein，任意 N，语义对齐 `numpy.fft.rfft`）和 `:209` 的 `readWav` 就在仓里，正是 chroma 与泛音和声评分要的原语；`:655` 的 `bandShare` 甚至就是第一步探针「高频峰簇」的现成实现。建议新建 `@feuille/music`（`rfft`/`readWav` 上提到 core），配 `feuille music probe|align|build|scan-ink`；若确实要保留 Python，必须在 SKILL.md 写成明写的例外并附 uv preflight，否则 agent 读了 AGENTS 会拒绝执行。顺带一提，`d30()` 在 `:105` 被当本地函数用，唯一实现其实在 `build_video.ts:52`，引用应落到文件行（AGENTS.md 第九节的引用纪律）。


**4. 验收判据没有实现物，「含墨扫描」不存在。** `SKILL.md:117-120` 与 traps §10 都要求含墨扫描，但仓里最接近的 `packages/karaoke/src/scan_blank.ts:25` 是 `min(R,G,B) >= 250` 的纯白占比——暖纸 `#f7f2e6` 的最小通道是 230，**对空纸完全盲**，正好复现 trap §10 记的那次事故（112s 空纸、扫描全绿）。更麻烦的是 `usine/AGENTS.md:104` 把 `scan-blank` 当哨兵写进了铁律，等于把盲区制度化。修法：core 加 `inkCoverage(png, {gray: 200})`，CLI 出 `feuille music scan-ink`（或 `scan-blank --ink`），阈值按帧类型合成一张表（现在 trap §10 的 0.15–0.3%、`SKILL.md:118` 的 `<0.2%`、`:121` 的 `≥0.3%` 是三套数），并配反向自测：暖纸空页必须 FAIL、标题卡（0.46%）必须 PASS。TTS 标点同理——`gen_tts.ts:64` 的抛错点就是修复点（请求文本剥标点、按非标点字符对齐回 token），不该靠每条产线背纪律。

## 二、质量与可复现（P1）

**5. 装配层重复实现且与现有能力不兼容。** `karaoke build` 的底床是固定增益 `amix`（`build_video.ts:184-205`），表达不了本 skill 需要的「摘录绝对偏移 + 旁白期 ducking + 聆听段全电平」。所以要自己造 builder，trap §8/§9/§14 就每个项目重踩一次。建议把音频轨契约扩成 `tracks[]`（offset + gain envelope 或 `sidechaincompress`），别停在散文描述里。

**6. 没有交付规格，且这条线没有「完成定义」。** 终混响度的事实源已经存在（`core/compose.ts:6-9, 68-70`：−14 LUFS / TP −1.5 / LRA 11），本 skill 只写了「旁白下压到 0.25」，终混目标、画幅/fps/码率、封面、发布交接全缺。更上层，`skills/README.md` 的「完整产线」表只有 Cluster A / B 两列，本线没有完成判据——建议补第三列，否则「半成品静默收工」在这条线上没有边界。

**7. 事实与许可账本只有原则，没有 schema。** 「每个数字必须有出处」「逐件登记 URL+许可」（`:77, :98-99`）没有可机检的载体，而 trap §11 又说「交付前 grep facts JSON」。建议补 `assets/template/{sources.json, facts.json}` 与校验（占位符 grep + 数字↔来源溯源），与 `publish-copy` 的 `--facts` 同族。制作信息页也应承载作品/演奏者/许可/来源——Musopen 的 CC 录音需要署名，不只是 PD 声明。

**8. 摘录口径缺失。** 900s 讲一部约 40min 的交响曲，必须写「摘录选择原则」（每乐章选哪段、为什么、怎样避免只挑高潮造成失真）和片内「这是选段」的明示。18 条坑没有一条管这个，而它决定内容是否诚实。

**9. 引用与数字漂移。** `PLAN §5.2 / §5.3(b)`（`:132, :136`）指向不存在的文件；「工厂 H3 铁律」（`:137`）张冠李戴——H3 是额度铁律（`usine/AGENTS.md:11`），钥匙串隔离在 `:104`。这正是 AGENTS.md 第九节警告的「编号会漂、也会张冠李戴」。

## 三、结构（P2）

- 缺 `## 代码归属`：13 个 skill 里 11 个有，`ownership.json` 也没有本条目。脚本一旦入库，gate 的 `checkOwnership` 就会要求这一行。
- 缺 `## Requirements (fresh machine)` 与 `## 验收判据` 两个一级段。验收现在埋在第 7 步，和「时长定标」「赏析知识清单」抢注意力。
- traps §13 与 §18 是同一根因写两遍（§18 自称「§13 的现场」），合并后 18 条可压到 17。
- 18 条坑建议改成表（层 / 症状 / 机检方式 / 是否已有 selftest），把可机检的五条升成脚本：TDZ 空帧字节数、逐场景对账、preroll 音画差、ink 覆盖率、credit 占位符。`match-recap-video` 的 `check_windows.py selftest` 是好范式（好例全过 + 坏例全抓）。
- 描述里 "any recorded-music"（`:14-15`）过宽，会与 `multilingual-video-poetry` / `bgm-bed` 抢路由；收窄为「需要乐谱/音高/和弦级标注的欣赏科普」。
- 视觉细节三条：trap §15 每段独立 `vmax` 归一后柱高不可跨段比较（标刻度或用统一参考）；§16 的 `x1 − 180` 是硬编码像素，应按字号/文本宽度推导；§11 的二段式要写明「卡长固定」这个不动点条件，否则重渲不收敛。

## 四、别在重构里丢掉的部分

时长定标表与「聆听优先三原则」、赏析知识清单的「事实口径」列、把版权放在前置契约第 1 条、以及 traps 里「症状 → 根因 → 修法」的叙述方式——这是仓里最好的一份翻车记录，稀缺价值就在这，改进时请把它当资产而不是当散文。

## 五、建议落地顺序（四个小 PR）

1. **纯文档修正**（风险最低）：user-data-dir（含 `av-sync.md`）、PLAN 死引用、H3 误引、阈值表统一、`d30` 补文件行。
2. **资产入库**：`scripts/` + `assets/template/`（状态帧 HTML、facts/sources schema）+ selftest fixture；改 SKILL.md 指路。这一步能结构性消掉 trap §5/§6/§13/§17。
3. **判据落地**：ink 覆盖率进 core/CLI + 反向自测；`gen_tts` 标点收口（或先加 preflight）；逐场景对账脚本化。
4. **归流**：`@feuille/music`（基于 `bgm` 的 `rfft`/`readWav`）+ `feuille music` 叶子，补 `ownership.json`、代码归属段、交付规格与 README 完成定义第三列。

要不要我先做第 1 步？它是纯文档改动，改完 `pnpm verify` 仍应全绿，也能立刻把「照文档做会挂死」这条风险消掉。
