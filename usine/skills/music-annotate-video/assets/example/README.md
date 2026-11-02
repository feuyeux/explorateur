# assets/example — 德沃夏克《自新世界》产线（只读历史归档）

来源：`examples/dvorak-new-world/tools/`（2026-11-01 实船）。该目录在工作区
`.gitignore` 的 `examples/` 规则下**永不入库**，新克隆看不到；这里复制的是
2026-11-02 的磁盘快照，目的是让「唯一完整样例」不再依赖某台机器的本地目录。

## 先读这一条：不要照抄运行方式

这些是 **Python/librosa 时代的实现**，只作为算法与几何的参考，不是现行运行时：

| 归档里的写法 | 现行纪律（以 `../../SKILL.md` 与 `usine/AGENTS.md` 为准） |
|---|---|
| `import librosa` / `mido` / uv/python 3.11 | 全量 TS 化；分析原语用 `@feuille/bgm` 的 `rfftMag` / `readWav` / `bandShare`（`packages/bgm/src/gen_bgm.ts:185,209,655`）；不得引入 librosa（pyin/numba 会拖死机器） |
| 写死 `C:\Program Files\Google\Chrome\...` | 经 `@feuille/core` 的 `platform.browserPath()` 解析；skill 脚本禁止硬编码可执行名（gate 机检） |
| `--user-data-dir=<临时目录>` | **不要带**：macOS + Edge 实测图能出但进程永不退出（`usine/AGENTS.md:104`、`packages/karaoke/src/build_video.ts:73-80`） |
| `b2_build.py` 把播放头烘进静态 SVG | 渲染只走 JS overlay（`assets/template/status-frame.html`）；两套播放头实现必然漂移（traps §17） |
| 时间码 `x1 - 180` | 用 `text-anchor="end"` 锚在绘图区右缘，按字宽推导（traps §16） |
| 每段局部 `vmax` 归一波形 | 用整段摘录的统一 `vmaxRef`，或显式标出刻度（traps §15） |

## 各文件在读什么

- `opening_timeline.py` —— 有 MIDI 真值的对齐：和弦模板逐帧分类（模糊 Jaccard）
  → 众数平滑 → 切段 → 按乐谱块序对拍；重复音级集先**去重组**（traps §1）。
  判据：结构块落带内 + 起点后 0.05–0.6s 最强音级交集 ≥ 2/3。
- `theme_timeline.py` —— 无真值的独奏段：手写泛音和声评分 f0 → 中值平滑 →
  滞回量化 → 聚段（traps §2/§3/§4）。这是「不用 pyin」的原始实现。
- `b1_render.py` —— 静态教学图（谱例高亮 / f0 轨迹 / 乐器音域图）的 SVG 生成。
- `b2_build.py` —— 单场景 90–120s 样片：状态帧 → 分段精确帧数编码 → concat；
  含旁白 ducking 的音频链。
- `b4_build.py` —— 多场景全片：场景注册、DATA 注入、JS 播放头 overlay、
  逐场景时长对账。**这是 traps §14 三处「首段」口径的现场。**
- `covers.py` —— 封面/片头片尾卡的渲染入口。
- `credit_card.py` —— 二段式制作信息页：占位卡先拼进成片，成片完成后回填
  实测数字重渲（traps §11）。注意它也用 `--user-data-dir`，按上表改正。

## 不在这里的

旧版 SKILL.md 曾把 `probe_movs.py` 列为本目录的「摘录探针」，但该文件在
原目录与快照里都不存在。探针结论散在 `examples/dvorak-new-world/notes/` 的
日志里；新项目请把探针命令与输出写进 `<project>/notes/probe/*.log`，不要
引用一个不存在的脚本。

## 归档地位

`assets/example/` 是全仓约定的**只读历史归档**（gate 的硬编码可执行名检查
对此目录豁免，正因为它是历史快照）。不要在归档里修 bug；要修的是
`SKILL.md` 的现行纪律或 `packages/` 里的实现。
