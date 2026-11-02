# Music AV Traps（本产线实测踩坑全集）

来源：德沃夏克《自新世界》样片与全片产线，2026-11-01 实船。每条都付了代价，
改产线前通读。完整历史实现已快照到 `assets/example/`（只读；其中的运行方式
已被现行纪律取代，见该目录 README）。

**索引**（先按症状找到条号，再读正文）：

| # | 层 | 症状 | 机检方式 / selftest |
|---|---|---|---|
| 1 | 对齐 | 参考序列被压进极短音频，映射点挤在一起 | 映射跨度比；结构块落带内 |
| 2 | 机器 | 分析进程 CPU/内存失控，系统冻结 | 禁用 pyin/DTW（代码审查 + 依赖检查） |
| 3 | f0 | 逐帧在声部间跳；上游日志八度误标 | 锚点频率 ±1Hz 交叉验证 |
| 4 | 分段 | 0 个音符、判据全红，像「量化抖动」 | 聚段循环单元测试（`j,last=i;gap=0`） |
| 5 | 渲染 | 所有状态帧同字节数的空纸 PNG | 状态帧字节数去重 + 含墨扫描 |
| 6 | 渲染 | 连标题都不渲染；分支判不中 | DOM 断言 `#scene-<裸名>` 存在 |
| 7 | 装配 | 高亮整体错一个块 | 抽帧断言 state 与音频时刻 |
| 8 | 混音 | 所有高亮滞后 0.8s | 音画偏移探针（preroll 窗口） |
| 9 | 装配 | 短音符被撑到 1s，总长多出十几秒 | 帧域钳制断言（差 0 帧） |
| 10 | 验收 | 全片空纸但白页扫描全绿 | `ink-scan.mjs --self-test`（空页必 FAIL） |
| 11 | 收尾 | 占位符流进成片；重渲不收敛 | `validate-facts.mjs` + 卡长不动点 |
| 12 | 旁白 | 尾部 token 为 null，崩在 `toFixed` | TTS preflight：标点剥离 + 非空时长 |
| 13 | HTML | caption 在奇怪位置断成三四条 | DOM 断言 `.caption` 是块级元素 |
| 14 | 装配 | 音频比视频长，漂移传染后续场景 | 逐场景对账差 0 帧 |
| 15 | 视觉 | 最响段变实心块；跨段柱高不可比 | 统一 `vmaxRef` + 刻度标注 |
| 16 | 视觉 | 时间码与事件标签相撞 | `text-anchor="end"`；改字号回归 |
| 17 | 渲染 | 预览对、成片错（或反之） | 单一 JS overlay + DOM 断言 |
| 18 | 视觉资料 | 缩略图铺满/错人/错年代/无许可 | `validate-facts` 长边+来源；人眼对出处页 |

## 1. 子序列 DTW 结构性压缩（对齐层）

子序列 DTW 的每一步都累加代价 ⇒ 把 19s 的参考序列压进 2.1s 音频反而更
「便宜」（实测 end cost 72.3，映射起点全部挤在 8.4–10.5s）。librosa 的
subsequence DTW 同样如此——这不是 bug，是代价模型的结构性质。

**替代**：和弦模板逐帧分类（模糊 Jaccard argmax）→ 众数平滑 → 切段 →
按乐谱块顺序对拍。重复音级集的和弦块（如块 0 与块 2 同为 E-G♯-B）必须先
**去重组**再分类，否则 argmax 恒取第一个模板、后一块永远匹配不到。
参考实现：`assets/example/opening_timeline.py`。

## 2. pyin/numba 会拖死开发机（机器层）

librosa.pyin 走 numba JIT：本机实测一个进程 CPU 471s、提交内存 154GB，
系统三次冻结全部复现在该调用点。**禁用 pyin 与 librosa.sequence.dtw**，
改用手写泛音和声评分 f0（纯 numpy、分块 FFT）与手写 DP。

现行默认不是 Python：FFT 原语用 `@feuille/bgm` 的 `rfftMag`
（`packages/bgm/src/gen_bgm.ts:185`）。若确有历史脚本要跑，才是明写例外：
独立 uv 环境、`OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2`、单进程前台。

## 3. 泛音和声评分（f0 层）

复音竞争下（独奏 + 低八度伴奏），「滞内第一峰」跟踪器逐帧在两个声部间跳
（210Hz↔530Hz），中值平滑救不了。改泛音和声评分
`score(τ)=mean(r(τ),r(2τ),…,r(4τ))/r(0)` + 搜索带限定旋律音区（排除伴奏
基音区），锚点精度到 ±1Hz（416.6 vs probe 417.0）。
注意：上游探针日志会有**八度误标**（209.7Hz 被标成 G♯4，实为 G♯3）——
交叉验证以频率为准，不抄标签。参考：`assets/example/theme_timeline.py`。

## 4. 聚段循环的初始化（分段层）

`j = gap = last = i` 把 gap 初始化成帧下标（37），条件 `gap <= 4` 立即为假
——从第 5 帧起所有段被切成单帧，0 个音符、判据全红，且看起来像「量化抖动」。
正确：`j, last = i, i; gap = 0`。迁移到 TS 时写成纯函数 + 单元测试，
反向用例：一段连续浊音必须切成 1 段而不是 N 段。

## 5. 状态帧脚本顺序（渲染层）

数据 `<script>const DATA=…</script>` 必须在使用它的 JS **之前**——const 无
提升，后置脚本在先置脚本执行时处于 TDZ，`DATA[scene]` 直接 ReferenceError，
整页只剩背景色。症状：所有状态帧同字节数的空纸 PNG。

**机检**：同一场景不同 state 的 PNG 字节数若全部相等 → 可疑；再用含墨扫描
（§10）确认。模板 `assets/template/status-frame.html` 已把 DATA 放在消费者前。

## 6. scene 名与 DOM id 的拼接（渲染层）

URL 传 `scene=scene-A`，JS 再拼前缀 `show("scene-"+scene)` → 查
`scene-scene-A`（不存在）→ 连标题都不渲染。同理 `scene=card-intro` 配
`if (scene === "intro")` 分支判不中。约定：URL 传裸名（A/B/C），卡片分支
显式列全别名。

**机检**：截图前 `--dump-dom` 断言 `#scene-A`（或卡片 id）带 `on` 类。

## 7. 段-状态错位 off-by-one（装配层）

段 `[t[i−1], t[i])` 覆盖的是**块 i−1 活跃**的时间，必须显示 state i−1。
错位成 state i 会把高亮整体错一个块（实测：音乐在 №5、金色却亮在 №6）。
首段 `[0, t[0])` 归 state −1（全暗）。

## 8. 音乐轨没有顺延 preroll（混音层）

视频头 0.8s 全暗 preroll，音乐却从场景 0s 开始响 ⇒ 高亮时刻按
`PREROLL + t` 排、声音按 `t` 排 ⇒ **所有高亮滞后 0.8s**（av-sync §4 的
镜像陷阱）。修：音乐链 `adelay=800`，与旁白一致。

**机检**：在 preroll 结束后的第一个事件附近抽帧 + 读音频能量，确认两者
同时到达；只对全片总长不抓这个。

## 9. 时长钳制的单位（装配层）

`max(1, d30(end) − d30(start))` 里的 `1` 是 **1 秒**不是 1 帧——所有短于
1s 的音符段被撑到 1s，B 场景多出 11.6s，音画全错。钳制必须在帧域：
`max(1, round(d30(end)*30) − round(d30(start)*30))`。现行实现：
`packages/karaoke/src/build_video.ts:52`（`d30`）与分段编码 `:157-180`。

## 10. 纸色躲过「白页扫描」（验收层）

暖纸主题背景 #f7f2e6：最小通道 230、灰度≈242。「近白阈值 244」的扫描抓不住
**空纸渲染**：实船事故是 112s 全片空纸而白页扫描 0 命中。

`feuille karaoke scan-blank` 判的是 `min(R,G,B) >= 250`
（`packages/karaoke/src/scan_blank.ts:25`），**对本产线是盲的**，不能当验收。
改用**含墨扫描**：1fps 采样，每帧转灰度，统计 `gray < 200` 的像素占比
（`assets/template/ink-scan.mjs`）。

阈值只有一张表：**判定阈值 0.2%**；暖纸空页 0% 必 FAIL；稀疏合法标题卡
0.46% PASS；正常教学帧/preroll 设计上 ≥0.3%（实船全片最低 0.868%、样片
最低 0.903%，均 1fps 采样）。反向自测：`ink-scan.mjs --self-test` 必须同时
「抓到空页」且「不误杀 0.46% 标题卡」。

## 11. 制作信息页是「先有鸡还是先有蛋」（收尾层）

卡片本身是成片最后一段，而卡上的「总时长/结束时间」要成片出来才存在。
**二段式**：占位卡先拼进成片 → 成片完成后回填实测数字重渲 → 只重编最后
一段 → `concat -c copy` 重拼接 → `apad + -t v_dur` 重封装。

**不动点条件：卡长在第一次装配前就定死（例如 8.0s），回填只改内容不改帧数。**
否则总时长变 → 数字变 → 再重渲，永远不收敛。占位符（「见成片 ffprobe」
「渲染完成后回填」）不许流进成片——交付前跑
`assets/template/validate-facts.mjs`（交付模式，禁止 `{{…}}`）。

## 12. TTS 文本纪律（旁白层）

标点进 TTS 文本 ⇒ 词边界缺失 ⇒ 尾部 token 拿到 null ⇒ `feuille karaoke tts`
崩在 `toFixed`（`packages/karaoke/src/gen_tts.ts`；av-sync §1b）。中文旁白：
标点→空格、子句留空格分隔。多句旁白按实测 mp3 时长**顺延**（at 累加 +
0.9s 间隔），不许同刻齐发。

**修法在源头**：调用方剥标点、按非标点字符对齐回 token，不要让每条产线
各自背纪律。

## 13. 裸文本进 flex 容器会碎成窄条（HTML 层）

场景容器是 `display:flex; flex-direction:column`，caption 若以**裸文本节点**
插入（没有 `<div class="caption">` 包裹），文本 + `<b>` + 文本会变成多个
**匿名 flex item**，各自窄幅换行——症状是「caption 在奇怪的位置断行成三四条」，
和宽度无关（设 width 也没用）。修法：模板里永远包一层块级 div。

**根因记忆**（原 §18，已并入本条）：「caption 在奇怪位置断行、设 width 无效」
→ 先查 HTML 里有没有 `<div class="caption">`。裸文本在 flex 列容器里成为
匿名 item（文本、`<b>`、后续文本 = 三个 item 并排各自换行）。模板缺 div 时
symptom 看似 CSS 问题，实为结构问题。

**机检**：DOM 断言 caption 的父节点是块级元素且只有一个文本流；
`assets/template/status-frame.html` 已内置正确结构。

## 14. 时间轴三处「首段」口径必须一致（装配层）

场景的 -1 帧（preroll）时长有三个不同口径，错任何一个都造成**音画逐场景
漂移**（v2 实测：音频比视频长 2.0s，且漂移会传染给后续所有场景的旁白）：
- waveform/melody：`d30(pre + states[0])`（时间态，通常 = pre）；
- chords/timeline/map：`d30(pre + 首个 marks)`（**不是** states[0]——
  那是下标 0，会把 1.2s 的首事件间隙吃掉）；
- chart：**没有 -1 段**（单一静态帧已含 preroll；否则 preroll 计两次）。

验收手段：逐场景对账——视频段总长 vs `d30(pre+body+done+tail)`，差值
必须为 0；只看全片总长会漏掉互相抵消的错位。参考：
`assets/example/b4_build.py`。

## 15. 波形缩放：线性会变实心块，分段 vmax 会不可比（视觉层）

`h = v × 系数`：RMS 0.14 × 2600 ≈ 364px 半高 ≈ 整个绘图区——最响的十几秒
渲染成实心矩形，波形细节全灭。改 **sqrt 压缩**（响度感知近似）：
`h = max_h × sqrt(v / vmaxRef)`，并给 `h` 设上限
`max_h ≤ (ybot−ytop)/2 − 4`。

**`vmaxRef` 必须是整段摘录（乃至全片）的统一参照，不是每个分镜段的局部
最大值**——否则「A 段最响」和「B 段最响」的柱高不可跨段比较。画面右下角
标出参照（`柱高参照：全段最响 RMS …`）。模板已按此实现。

## 16. 播放头时间码别贴播放头（视觉层）

时间码锚在**绘图区右缘固定位置**，不要跟随播放头——跟随会与事件标签（同样
挂在顶部）相撞；事件多时需错位排布。

**不要写死 `x = x1 − 180`**：180 是按当时字号/文案试出来的像素值，字号或
时间码长度一变就撞。用 `text-anchor="end"` + `x = x1`（可加统一内边距），
字宽由浏览器按实际字形推导。回归：把时间码改成 `999.9s / 9999s` 再截图，
仍不得与事件标签重叠。

## 17. 播放头态有两份实现，改一处要查另一处（渲染层）

Python 侧 SVG（`playhead=` 参数烘进 SVG）与页面 JS overlay（`?ph=` 参数
动态追加）是**两份播放头实现**——只改一份会出现「预览对、成片错」或反之。
定标：**渲染走 JS overlay**（静态基图不含播放头），另一侧参数只作静帧样张；
改几何（yTop/yBot/x0/x1）时两处 + DATA 的几何字段同步。

模板只保留一份 JS overlay；`b2_build.py` 里的烘焙式播放头是反例，不要照抄。

## 18. 搜到图不等于能用（视觉资料层）

Firecrawl 的图片结果给的是 `imageUrl`（直链/缩略图）+ `url`（出处页）。
把 `imageUrl` 铺满 1920：搜到的 296×393 肖像直接糊成色块；把搜索标题当
「这是谁」：同名作曲家、后人塑像、演员定妆照、AI 生成「历史照」都会混进来；
把聚合站/博客转载当许可证据：真正出处页写着「All rights reserved」。

**修法**：三道门槛 + 入账。
1. 身份：以出处页（Wikimedia `File:` / IMSLP / LOC / 博物馆 open access）的
   作者、年代、对象名为准，并与作品目录交叉核对；
2. 许可：PD-old / PD-US / CC0 首选，CC BY/SA 保留 attribution；`unknown`、
   聚合站转载、现代演出照、版权谱例一律不用；AI 图不许当史料；
3. 尺寸：`full-bleed`/`background` 长边 ≥1600px，`inset` ≥900px；人眼查
   watermark、黑边、AI 放大纹理与裁切。

`assets/template/validate-facts.mjs` 机检 `sources.json` 的 `kind:"image"`
字段、`facts.visuals[]` 的 `source_id` 类型与长边门槛。完整流程见
`references/visual-research.md`。

## 机检落点

已可执行（本 skill 的 `assets/template/`）：

- `ink-scan.mjs` —— §10 的含墨判据；`--self-test` 覆盖「空页 FAIL + 稀疏卡 PASS」。
- `validate-facts.mjs` —— §11 的占位符/出处判据 + §18 的图像长边/类型判据；
  `--self-test` 覆盖五类坏账（占位符/未知来源/缺 source/小幅面图/错 kind）。
  已挂进 `packages/gate/test/skills-assets.test.ts`，`pnpm verify` 会跑它的反向自测。

尚未脚本化、建议随 `@feuille/music` 归流时补 vitest 的四条：
TDZ 空帧字节数（§5）、逐场景对账（§14）、preroll 音画差（§8）、
含墨覆盖率迁进 core（§10，目前是独立 mjs；阈值与反向用例已定）。
范式参考 `match-recap-video/scripts/check_windows.py selftest`：好例全过 +
坏例全抓。
