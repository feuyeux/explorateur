# 实测记录（2026-10）

> 静态规则见 [reference.md](reference.md)；交互见 [guide.md](guide.md)。
> 只留可复算的数字与已修缺陷；过程流水账看 git 历史。

## 1 一次真跑：一座城 · 12 语种

环境：Windows + Node 22.23.0（仓库要求 ≥24，实测可跑完整条线；升 24 是系统级变更，
未替你动）、pnpm、Edge/Chrome headless、ffmpeg/ffprobe、magick。

```powershell
$ErrorActionPreference = "Stop"
$env:FEUILLE_BROWSER = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$P   = "examples\one-city-12lang"
$ABS = "D:\coding\personal\explorateur\usine\examples\one-city-12lang"
$LOC = "zh-CN,en-US,de-DE,fr-FR,es-ES,ru-RU,el-GR,hi-IN,ar-SA,he-IL,ja-JP,ko-KR"

# 1 字体 + 字符门
pnpm exec feuille poster fetch-fonts $P\fonts.json
pnpm exec feuille poster audit-charset $P\poster_src.html $P\fonts.json
pnpm exec feuille poster audit-charset $P\video_src.html  $P\fonts.json
# 2 注入 + 海报 + 封面
pnpm exec feuille poster assemble $P\poster_src.html $P\index.html
pnpm exec feuille poster render $P\index.html "$ABS\poster.png"
pnpm exec feuille poster make-covers $P\index.html $P\cover_src.html
pnpm exec feuille poster render "$P\cover_src.html?fmt=P" "$ABS\cover_pt.png" 1080 1920 1
pnpm exec feuille poster render $P\cover_src.html "$ABS\cover_lc.png" 1920 1080 1
# 3 配音 + 合成
pnpm exec feuille karaoke tts $P\voices.json $P\tts
pnpm exec feuille karaoke build $P\video.json --only landscape
pnpm exec feuille karaoke build $P\video.json --only portrait
# 4 闸门
pnpm exec feuille karaoke scan-blank $P\out\one_city_landscape.mp4 $P\out\one_city_portrait.mp4
pnpm exec feuille karaoke verify-sync --video $P/out/one_city_landscape.mp4 --frames $P/frames --tts $P/tts --locales "$LOC" --preroll 0.8 --done 0.5 --intro 2.2
# 5 发布侧（零平台流量）
pnpm exec feuille copy check $P\publish --facts $P\publish\facts.json
pnpm exec feuille publish check-plan $P\publish\manifest.json --root $P
```

| 项 | 实测 |
|---|---|
| 语种 | 12（zh/en/de/fr/es/ru/el/hi/ar/he/ja/ko） |
| 成片 | 1920×1080 与 1080×1920，30fps，66.20s，1986 帧 |
| 同步门 | 横竖各 36/36 OK，最大 diff 608 / 40000 |
| 字体 | 7 字族子集，`fonts.css` 181,576 B（base64 woff2） |
| 复现 | 四步重跑 SHA256 一致：`poster.png` BD600809…、`cover_pt` 603670BE…、`cover_lc` D785B7F1… |
| BGM | Lyria 床 76.13s / 48 kHz / 16-bit / 立体声 / RMS −14.0 dBFS；`gain` 0.0871，fade 1.5→3.0 |

未跑（要人或要外部副作用）：`publish login`（扫码）、三平台真实发布（不可撤回）。
`publish check-plan` 可跑——零平台流量。

## 2 坑位表（一次真跑暴露）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `poster render` 报浏览器被抢占 | 输出是相对路径，Chrome 不按 cwd 解析 | 输出一律绝对路径 |
| 2 | 海报末行空白 / 转写丢失 | Edge 视口比 `--window-size` 小 24×93 | `FEUILLE_BROWSER` 指 Chrome |
| 3 | `fit-diag` OK 但图缺块 | 只看格内溢出，不看视口 | `getBoundingClientRect` 探 `innerHeight` |
| 4 | `make-covers` 退出 0 但没改文件 | 源文件 CRLF，字面 `\n` 锚点不匹配 | 源文件转 LF 重跑 |
| 5 | `audit-charset` 把拉丁大写算缺字 | `<small>` 落在 `class="f-sc"` 子树 | 字族类挪到内层 span |
| 6 | `pnpm --dir ..` 后路径全错 | `--dir` 只换包目录，cwd 仍是仓库根 | 从仓库根写相对路径 |
| 7 | `verify-sync` 找不到 seg.wav | PowerShell 把逗号当数组分隔符 | `--locales "a,b,c"` 加引号 |
| 8 | 同一封面小红书过、抖音不过 | 平台底色不同（白 vs 黑） | 按平台各出一张 |
| 9 | 视频字体没生效 | `build` 用原始 src 截图 | 先 `poster assemble` 注入 |
| 10 | `cover make` 传 `?fmt=P` 无效 | 只接受文件路径 | 竖版走 `poster render "…?fmt=P"` |
| 11 | `--locales` 顺序错，diff 全红 | 场景起点按该顺序累加 | 与 `video.json` 严格一致 |
| 12 | Node 22 上 `pnpm install` 也过 | 无 `.npmrc`，engine-strict 未开 | 升 ≥24 或显式关检查 |
| 13 | 加 BGM 后旁白小 3 dB | `aformat` mono→stereo 走 swr，每声道 −3.01 dB | 显式 `pan=stereo\|c0=c0\|c1=c0` |
| 14 | 装 playwright 后发布测试红 | `launchPersistentContext` 目录是第一个位置参数 | `(userDataDir, options)` |
| 15 | `bgm gen` 请求 76s 只得 36s | 收流按 1× 实时睡，实际 0.5–0.6× | 按音频字节数收流，wall 上限 2.5×+30s |

## 3 装库 / 真 key 之后才暴露的三个缺陷

1. **`launchPersistentContext` 签名**：没装 playwright 时测试 `skipIf` 跳过；装上立刻
   `TypeError: "path" argument must be of type string`。修后 `packages/publish` 22/22 通过。
2. **有床分支压旁白 3 dB**：静音床对照 −23.5 vs −26.5 dB，差恰 3.01；`aformat` 的
   mono→stereo 矩阵每声道 ×1/√2。改显式 `pan` 复制后回到 −23.5 dB。
3. **Lyria 收流提前收工**：请求 76.13s 实得 36.0s（47%），69s→42s（61%），23s→20s（87%）；
   探针显示到账约 0.59× 实时且中间成段停 5–10s。根因是 `session.play()` 后
   `sleep(seconds)`。改为凑够 `seconds×48000×2×2` 字节、250ms 轮询、20s 无新数据判流断；
   同一命令 76.13s / exit 0。原先记的「实时后端短约 10%」是假象。

## 4 发布：证据与判据（2026-10-06 批）

- **证据优先级**：截图/像素 > 脚本自报。反复出现「脚本说找不到、截图里明明有」和
  「脚本说成功、截图里没生效」。
- **未知状态一律当失败**；不许静默 fallback（已删三处「封面上传失败 → 用默认首帧 → 继续」）。
- **每条前强制回干净投稿页**：小红书 03 撞风控后残留遮罩，04–12 全部把上一条封面盖上去。
- **草稿箱计数不是判据**：小红书发布成功也不清草稿，计数从 (1) 涨到 (4) 时四条其实全成功。
- **成功判据**：回列表核验到作品（抖音计数递增并刷新一次；小红书按标题搜到）。
- **标题按平台倒推**：抖音 `系列名｜第NN话 语种：场景`（≤30）；小红书砍成
  `系列名｜NN语种`（≤20）；29 字抖音标题搬过去直接红字。
- **自检清单**：封面是预制带字图 → 文字在真实裁切框内 → 分区/声明由用户拍板 →
  发布后重开管理页截图核对 → 数量对不上拒绝提交 → 撞风控停下等人。

**2026-10-06 基线**（发布后 8.5h）：小红书 +35 粉 / 3,965 观看 / 曝光环比 +4249%；
抖音 +3 粉 / 平均播放 4.72s / 完播 0.8%。归因两次被推翻：不是「批量发布」，也不是
「45–56s 太长」；区分变量是语种与包装。

## 5 一次真跑：各国美食名称 · 寿司 · 12 语种（2026-10-19）

「各国美食名称」系列第 1 期。画面 = 一道菜的 12 语种对照：海报每格只放菜名，
视频每格放整句「菜名 + 是日本料理」。**题眼**：12 个写法里 11 个是从日语借的，
唯一没借的那个（日语 すし）就是被借走的那个。

项目源文件在 `examples/sushi-12lang/`（该目录被仓库根 `.gitignore` 忽略，
源文件不入库；完整命令块见该目录的 `README.md`）。下面只留可复算的数字与已修缺陷。

| 项 | 实测 |
|---|---|
| 语种 | 12（zh/en/de/fr/es/ru/el/hi/ar/he/ja/ko） |
| 菜名 12 形 | 寿司 / sushi / Sushi / sushi / *sushi* / суши / σούσι / सुशी / سوشي / סושי / すし / 스시 |
| 成片 | 1920×1080 与 1080×1920，30fps，62.60s，1878 帧，H.264 crf18 + AAC 160k/48 kHz 立体声 |
| 同步门 | 横竖各 36/36 OK，最大 diff 512（横）/ 487（竖），阈值 40000 |
| 白帧门 | 两版各 63 帧采样，0 白帧 |
| 旁白 | 12 段 edge-tts Neural；语音窗实测加权 RMS **−18.57 dBFS**（最响 hi-IN −14.5，最轻 es-ES/ar-SA −22.0，跨度 7.5 dB） |
| BGM | Lyria 床 72.45s / 48 kHz / 16-bit / 立体声 / RMS −15.1 dBFS / 峰值 0.0 dBFS；拍速实测 87.9 BPM（请求 84，1 倍命中 → 采样率解读可信）；`gain` 0.1063，fade 1.5→3.0 |
| 床位 | 混后 `_bgm_track.wav` RMS −34.9 dBFS，比旁白低 **16.3 dB**（判据 15–18 dB） |
| 字体 | 7 字族子集，`fonts.css` 215,091 B（base64 woff2） |
| 封面 | `cover_lc.png` 1920×1080（B 站）、`cover_pt.png` 1080×1920（竖版全屏）、`cover_t34.png` 1080×1440（竖版平台信息流原生比例） |
| 复现 | SHA256：`poster.png` 14144A56…、`cover_lc` 75AC7142…、`cover_t34` FE8CB4E9…、`sushi_landscape` B00522FA…、`sushi_portrait` D92E877E… |
| 发布侧 | `copy check` 三平台 × 8 项 0 违规（带 `--facts`）；`publish check-plan` 3 条无阻塞 |

未跑（要人或要外部副作用）：`publish login`（扫码）、三平台真实发布（不可撤回）。

**词形口径（两个别混）**：海报/封面用**词条形**（英语 sushi、俄语 суши 小写），
视频用**句中形**（英语 Sushi、俄语 Суши——句首大写是各语正字法，不是另一个词形）。
带音符的词典形（阿拉伯语 سُوشِي、希伯来语 סוּשִׁي）**只进发布词注记**，画面用通行形
（无音符）。未证实的说法不写（「俄语 суши 兼指风干鱼」等一律不落笔）。

## 6 本轮新暴露的坑

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 16 | `verify-colors` 除首格外全报「NO … pixels」 | `verify_colors.ts` 的 `cluster()` 把「簇内最后一个元素」写成 `out[out.length-1][out.length-1]`（簇下标），只有第 0 簇能合并；2x 渲染时 1.5px 网格线占 3px，格子取样框退化成空区间 | 改回元素下标；新增 3px 粗线夹具的反向验证用例（1px 夹具永远测不到） |
| 17 | `karaoke build` 最后一步炸 `No such file or directory`，前面十几分钟状态帧全白跑 | build 建了 `frames/`，没建输出目录 `out/` | `mkdirSync(dirname(out))`；e2e 用例的输出路径改成**尚不存在的子目录**当回归 |
| 18 | Edge headless `--dump-dom` 返回空 | Edge 在本机拿不到 dump | 所有渲字/门禁显式设 `FEUILLE_BROWSER` 与 `CHROME_BIN` 指 Chrome（否则 `measure-korean` 报「rect dump not found」） |
| 19 | 竖版平台封面按 3:4 裁掉标题 | 投的是 9:16 全屏封面，平台信息流按 3:4 居中裁切，上下各掉 12.5%，而标题在顶部 | `make-covers` 加第三个变体 `?fmt=T`（1080×1440），竖版平台投它；视频本体仍 9:16 全屏 |

两条 PowerShell 陷阱（不报错，只是静默给错结果）：

- **`$U?lang=zh-CN&state=1` 里的 `?` 会被 PowerShell 7 当三元运算符**，
  整段被吃掉 → Chrome 报 `Page load failed: net::ERR_NAME_NOT_RESOLVED`。
  URL 必须显式拼接：`$URL = $BASE + '?lang=zh-CN&state=1'`。
- **Chrome 批量截图那一轮的命令输出整段是空的，但文件其实已落盘**。
  同一段代码换个写法又正常输出，判不出确切机制——**以文件落盘为准，别以 stdout 为准**。

## 7 系列批量化：12 期数据驱动（2026-10-20）

「各国美食名称」从「一期手写」推到「一期一份数据 + 一条命令」。第 01 期（寿司）
反写成 `data/ep01-sushi.json` 当**回归基准**：生成器重出的第 01 期必须与已交付的
手写版同构（叠印门矩形逐位相同、旁白实测电平与时长复算出同样的数）。
第 02 期起全部由 `tools/foodnames/` 的脚本生成。

**产线（`run_episode.mjs`，一期一条命令）**：生成源文件 → 字体子集 → 韩语补丁实测
注入 → 海报 → 三版封面 → 门禁（字符/适配/逐格颜色/叠印配准）→ 配音 → 旁白实测 →
床位反推 → 双画幅成片 → 同步门 + 白帧门 → 发布侧（事实表 + 清单 + 两道门）。
任一门禁红即非零退出，不留半成品。

**批量调度（`run_series.mjs --eps 03 04 --jobs 2`）**：把若干期分批投到子进程，
任一期红即整批非零退出。

**发布侧的关键设计：事实表是算出来的，不是抄文案。**
`make_publish.mjs` 从「数据 + 实测产物」算出 `publish/facts.json`——结构量
（12 语种 / N 条来路 / 各来源语言的格数 / 各语种位次）+ 实测量（时长 / 帧数 /
fps / 分辨率 / 旁白实测电平 / 床实测电平与时长 / 增益）；内容型事实（年份这类
不是量出来但可核对的数）由数据文件的 `extra_facts` 带进来，**脚本里不写死任何
具体年份**。`copy-*.md` 与 `manifest.json` **只抽取**三平台原稿，一个字都不改写
（清单与稿件同源，免得互相拆台）。

**为什么还要一个离线预检（`audit_copy_numbers.mjs`）**：`copy check --facts` 要等
成片出来才有 facts.json，但**稿子里的数字是写死的**——等产线跑完才发现某个数
没出处，返工的是文案不是产线。预检用「结构量 + extra_facts」离线算一遍，
把问题挡在写稿阶段。实测：预检第一遍就抓到番茄期的「1886」（希伯来语自造年份）
缺出处，补进 `extra_facts` 后过。

**词源语（`origin_locale`）口径**：manifest 的 `locale` 字段记「这个词从哪来」，
不是配音语种。口径 = **12 格内词源链的最上游格**；链的起点不在 12 格内时
（例：披萨 12 格全部借自意大利语）就记那个上游语言的 locale（`it-IT`）。
数据文件显式写；没写时按「唯一一格不是借来的」推导，推不出就报错——**不猜**。

**每格的「来源」标签记的是直接借词方向，不是终极源头**（en coffee ← 荷兰 koffie，
不是 ← 阿拉伯；阿拉伯格才写「词源」），有争议的写「有争议」而不是替它选一个。
这个口径是 12 期一致的最容易翻车处——第 07 期啤酒一格就有五个「本族词」
（英/德/西/俄/韩各一支拉丁/日耳曼源流），第 09 期拉面的日语格是
「借自汉语 · 有争议」（ラーメン ← 汉语 拉麵／拉面，见 wiktionary）。

## 8 批量化新暴露的坑

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 20 | worker 交回的发布词里视频名写成「茶_vertical.mp4」，实际产物是 `tea_portrait.mp4` | 作者按中文名自造了文件名，没有从产线产物名反查 | `patch_publish.mjs` 按 slug 批量改；发布贴士的封面口径统一到 3:4 信息流版（产线出三版封面，不是「用视频首帧」） |
| 21 | `buildManifest` 报一堆「素材缺失」，但文件明明在盘 | 清单里的素材路径是相对**期目录**的（`out/…`），存在性校验按进程 cwd 解析 | `make_publish.mjs` 先 `process.chdir(期目录)`；相对路径必须相对期目录解析，不相对调用者的 cwd |
| 22 | `copy check --facts` 的数字溯源要等成片才跑得起来，文案返工太晚 | 事实表里的实测项依赖成片，但**结构量与 extra_facts 不依赖** | 拆出 `audit_copy_numbers.mjs` 离线预检（见 §7） |
| 23 | 韩语 script 键写成 `ko` 会**静默**走不到补丁分支，格子全黑 | 键名不校验，错键只是不匹配 | 键固定为 `kr`（见 §6 坑 ③ 同一族的静默失败） |
| 24 | 韩语补丁门红：`토`（토마토）、`버`（햄버거）报 LABEL FAIL「initial and medial ink are ONE fused component」 | 初声+中声笔画**横接成一个连通域**（ㅌ+ㅗ、ㅂ+ㅓ），矩形补丁按连通域切，分不开 | 数据文件用 `ko_fused_syllables` **显式声明**融合音节（哪些融合**必须实测**，不猜）→ 这些音节整字走 `.cv` 融合渐变（与日语假名同款），不进矩形补丁；runner 只量非融合音节 |
| 25 | `run_series.mjs --eps 03 04` 只跑了 03，04 被静默丢掉 | `--eps` 只取 `argv[i+1]`，后面的裸值被忽略——不报错也不跑，看着像「排队没轮到」 | 多值参数吃到下一个 `--` 开关为止（`argList`） |
| 26 | 后台任务报 succeeded，但产物目录空 | PowerShell 后台任务壳被回收时把子进程一起带走 | 长跑产线用 `Start-Process` 脱离任务壳，输出重定向到日志文件 |
| 27 | 韩语融合音节在**海报与封面**上渲染成**实心色块**（ep04「토」、ep11「버」），而**成片正常** | `.ksyl.cv` 规则用了 `background:` **简写** → 简写把 `background-clip` 重置回 `border-box`；`.ksyl.cv` 的权重 (0,2,0) 高于 `.cv`/`.ksyl` 的 `background-clip: text` (0,1,0) → 渐变不再裁到字形，画满整个 inline-block 盒子。视频侧 `video_style.css` 没有 `.ksyl.cv` 规则，所以**只有海报坏** | ① 规则改用 `background-image:` 长写，并在**同一条规则里**自带 `-webkit-background-clip: text; background-clip: text; color: transparent;`（别指望别的规则兜底）；② 加像素门 `check_fused_glyph.mjs`：量韩语格里彩色像素的**最大实心轴对齐矩形**，短边 ≥60px 且长宽比 <3 即失败（实测坏例 134×134、长宽比 1.00；正常各期最大实心都是细长条，长宽比 8.8~10.2）——**「实心」本身不是病（横竖笔画就是实心的），「又大又方正」才是** |
| 28 | 并发跑两期时其中一期 TTS 步失败：`Error: Opening handshake has timed out` | edge-tts 连微软端点的瞬时网络故障，与代码无关；runner 的 fail-fast 正确地把它变成非零退出 | 直接重跑该期即可（TTS 目录已缓存的语种不重做）；注意 `--jobs 1` 单独重跑比整批重跑省时 |
| 29 | 汇总表 `series_report` 里第 12 期整行不见了，看着像「那期没跑完」 | 表头 6 行 + 12 行数据，输出时 `md.slice(0, 6 + rows.length)` **少切一行** → 最后一行（ep12）被吞。产物其实全在（海报/三封面/双成片/发布词/清单都齐） | 切片放宽一行，并加自检：**输出里的期行数 ≠ 期数就响亮失败**（这类「汇总工具自己截断」的 bug 极难用肉眼发现——先怀疑工具，再怀疑产物） |


## 9 dsh 插件层架构评审整改与真宿主实跑（2026-10-20）

这一轮的起点是「评审 `usine` 工程从 dsh 框架角度的实现是否足够纯粹」，结论是**装配层纯粹、交互契约层不纯粹、验证面不诚实**（分项打分：接缝 7 / 审批 4 / 契约 4 / 诚实度 3）。十条 P0/P1 改动的理由见 [dsh.md §10](dsh.md#10-2026-10-20-架构评审的改动)，这里只记**可复算的数字**。

**钉版**：`@deepseek-ai/*` 钉 **0.2.1-rc.2**；真宿主 runtime 实测同为 **0.2.1-rc.2**（`preflight` 第 ② 道机械检查当场核，不一致就红）。

**门禁**：`pnpm -s typecheck` 退出码 0；`pnpm -s verify` **43 文件 / 563 测试全绿**（改动前后各跑一次，测试数同数——本轮只改写断言口径，没有偷偷加宽判据）。**这是 2026-10-20 当天的读数，不是现值**：现值看 `record.md` 最新一节或直接跑 `pnpm verify`。

**插件自测**：`packages/dsh-plugin/test/` 两套件 **44/44 绿**（`plugin.test.ts` 23 例 + `plugin-parity.test.ts` 21 例）。

**preflight（零 LLM）**：**4/4 绿**——产物自足加载 / dsh 钉版一致 / 宿主起得来 / 插件真挂上（装配清单新鲜 + 工具面 17 个逐字相符）。

**host-run（真宿主实跑，MiniMax-M3.1-Flash）**：**5/5 绿**，会话 `session-2d9aa970df7d4134901cee237cb7c185`。会话日志逐帧解码后取到 12 条关键事件——**逐条表格在 [dsh.md §8.1](dsh.md#81-2026-10-20-真宿主实跑结果55-通过)**，此处不再抄第二份：同一份证据写两处，改一处忘一处就成了「两边都像真的」。本节只记这一轮**独有**的数字与结论。

**全程无 `task_id`**：没有生成任务被提交、额度零消耗——这是红线在**派发层**成立的机械证据（批准之前工具体根本没跑过）。证据落 `docs/dsh-host-evidence.ndjson` + `docs/dsh-host-summary.json`。

**旗标层对账**（parity 新增的一条）：SKILL.md 里写的每个 CLI 旗标都必须在库层真实存在——**差集实测 0**。反向（库层 ⊆ SKILL.md）本轮不查：库层有 70 个内部/浏览器旗标不在说明书里，超出本轮比例，硬做会逼出一堆与本轮无关的说明书改动。

**MiniMax 接入实测**：`api.minimaxi.com` 可达（401→鉴权通过）；`MiniMax-M3.1-Flash` 支持 OpenAI 工具调用；`max_tokens=32768` 被接受；模型清单 M3.1-Flash / M3 / M2.7 / M2.5 / M2.1 / M2。**换 provider 的起因**：`fuyao-ai-gateway.xiaopeng.link` 当日**连接超时**（curl 25s 超时，不是鉴权问题）——fuyao 条目仍保留在 overlay 里，改端点即可切回。

**已知非本轮回归**：`publish` 的 playwright mock e2e 在负载下偶发 5s 超时（实跑里 `usine_verify` 如实报 `failed`）；单独连跑两次 11/11 绿 → 既有 flake，仓库 git 历史已有同类记录（桌面浏览器开着会让门禁变红）。

**本轮新暴露的坑**

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 30 | 声明了 `inject` 但宿主没那个服务 → 插件**永不生效**、工具面全空、宿主毫无报错 | cordis 的 `inject` 是**硬激活门槛**（拿不到服务则 fiber 永远 pending），不是「可选声明」 | `inject` 只留硬依赖（`tools`）；可选服务走 `ctx.get`（读）/ `ctx.inject`（等）——同一个坑的反方向也踩过（2026-10-18 首测是「少声明导致服务没到」） |
| 31 | 审批写在工具体内 → 工具**已经跑过**才说「等审批」，宿主也没法按工具名否决，审计断在工具体里 | 审批服务本来在派发层（`tools/pre-execute` → dsh-tools `serviceAsk`），插件自己又手写了一遍镜像 | 门从工具体内迁到 `ctx.on('tools/pre-execute')`，返回 `{kind:'ask'}`；删掉 120 行手写审批与 `ApprovalLike` 镜像 |
| 32 | 工具输出里混进宿主自己的日志 / JSON-RPC 帧 | 猴补 `process.stdout.write` 的**时间窗**捕获把窗口内的所有写都收走，宿主写与工具写不分 | 改用 `AsyncLocalStorage` 按**异步上下文**捕获，串行锁删掉；console 与 stdout/stderr 两个出口都盖（vitest 下 console 被测试框架接管，只盖 stdout 会漏） |
| 33 | 会话日志只解出第一帧，后面的事件全丢 | 日志是多段 zstd 帧拼接，Node 的 `zstdDecompressSync` 只解第一帧 | 取证脚本逐帧解码；审批审计是 log-only（不进通知流），只能从会话日志拿 |
| 34 | 改完 inject 纪律后**复查发现 systemPrompt 还在 inject 里**——宿主一缺它，17 个工具掉到 **0** 且不报错 | 同一个坑的第三个实例：只清了 `approval` / `skills`，没看清 `systemPrompt` 承载的只是纪律文本，17 个工具一个都不依赖它 | `inject` 只留 `tools`；纪律文本节改走 `ctx.inject(['systemPrompt'], …)`。真 cordis 实测：只 `provide('tools')` 时注册工具数 **0 → 17**，纪律节安静跳过；该对比进了 `plugin.test.ts` 的常驻断言（真 `new Context()`，不是假 ctx） |
| 35 | 工具面里 `fit-diag` 空参调用**永不返回**，整条 rollout 的时间预算被烧光 | 缺参数就 `readFileSync(0)` 读 stdin；工具面里叶子**同进程**跑（`runMain` 直接 `await fn(argv)`），stdin 是宿主那根**永远不关**的管道 → 永久阻塞 | 边界层设 `FEUILLE_STDIN=off`；叶子缺参数/文件不存在立刻 exit 2 + 用法错，管道用法 `-` 显式保留，**CLI 那条路一个字没改**。2026-10-22 在 B 线跑批里实测：两轮 16 条 rollout 有 9 条卡在工具调用，8 条卡在这同一个调用上 |
| 36 | 换一批重渲的产线时，发布词里描述**旧版画面**的那句照搬过去 → 发出去的文案在描述一支已经不存在的画面 | 文案里的画面描述绑定了**具体渲染版本**，而画面恰恰是这轮唯一会改的部分（本次：词形从「句首的一个 token」变成「独立主角」） | 判据一句话：**这句话说的是「交付物」还是「内容」**——说交付物的要重取（规格由 `make_publish.mjs` 从新成片实测），说内容的才可带（数据没变 → 结构量逐项核对一致），说画面的**一句都不能照搬**；改法是**删掉画面那半句、留下语言学那半句**，不是改写成另一句画面描述（2026-10-22 实测：12 期 × 3 平台搬过来只改 2 句，`copy check --facts` 与 `check-plan` 12 期全绿） |

| 37 | 照抄通用 karaoke 模板的 `.tok` 规则 → 暗词不透明度 0.18、当前词高亮中性灰，**拿到这条产线自己的版式门下必红** | 通用技能教的是**通用**的卡拉OK观感，而这条产线的版式门要求的是**专有**的量化阈值（暗词 ≥ 0.45、当前高亮必须落在品牌三色里）；通用模板的默认值（`.tok.dim{opacity:0.18}` / `.tok.cur{background:rgba(44,38,32,0.09)}`）恰好就是这条产线**判红**的那两组数 | 阈值只从本产线自己的门里抄（`check_video_layout.mjs` 的 `TH` 与 `BRAND`，`usine/tools/foodnames/README.md` 本节复述一遍）；**通用资产里一个量化阈值都没有**（`usine/skills/` 整棵树 grep `12%` / `30%` / `墨迹` / `空白带` / `0.45` 全无）；2026-10-22 实测：RSI B 线基准臂 4/4 rollout 的交付产物照抄了那两行，两臂工作区里装的模板与仓内那份 sha256 相同 |

| 38 | 探针副本挪到别的目录 → 相对路径的 `<link>` 断了 → **样式全丢、量出来全是「达标」的假绿** | 页面用相对路径引本地样式表（通用 karaoke 模板就是 `<link href="../../theme-tokens.css">`）；副本换了目录，样式找不到 → 每个 token 的 opacity 变成浏览器默认的 1 → 「暗词不透明度 ≥ 0.45」这条判据**永远过** | 探针副本必须**自包含**：把本地样式表**内联**进副本，相对 `url()` 改成绝对 `file:///` 路径（`usine/tools/foodnames/check_scene_tokens.mjs` 的 `inlineCss`）；并且**每道新门都要做反向验证**——改对了的副本必须绿、没改的必须红（2026-10-22 实测：基准臂 4/4 红、本产线自己交付的 12 期全绿，改两行的副本立刻转绿） |
| 39 | 判据的**声明值**与**计算值**不是一回事：`opacity: var(--dim-opacity)` 静态读出来是「一个变量名」 | 阈值是量「渲染后看得见的那个值」——变量解析、层叠、祖先透明度叠加，静态读声明值会读出「没有具体数值」或读错对象 | 判据在**浏览器里**量 `getComputedStyle` 的计算值（`check_scene_tokens.mjs`），不解析源码；高亮色同样按「祖先链上第一个非透明底色」算，与产线自己的 `check_video_layout.mjs` 探针同一口径 |

| 40 | rollout **根本没跑起来**却被判成 **0 分**（「工作区里没有 HTML 画面文件」） | 「启动失败」与「跑完了没交付」在判分器眼里是同一件事：工作区里什么都没有 → 记 0 分。2026-10-22 实测：机器上 11 条 rollout 并发（合计 88 个 node 进程）时，dsh SDK 的 `initialize` 等不到 runtime 就 10 秒超时（`initialize timed out after 10000ms waiting for dsh profile "sdk"`），4 条 rollout **一个事件都没产生** | 分开两条路：**一个事件都没产生**（`diagnostics.json` 有 error ＋ `events.jsonl` 空 ＋ 没有 `final.txt`）⇒ **判据返回 None（作废），不是零分**；并且**只重试启动**（退避 20s / 40s）——重试启动不是重试行为、不改变测量，而模型跑满上限被掐死、智能体交了不合格的东西**都不许重试**（那是行为表现，重试它就是挑好结果）。修法在 `garage-ii/scene_layout_arms.py` 的 `launch_failure()` 与 `_execute_with_retry()` |

| 41 | 拿一份**自相矛盾**的处理项去量，读数无论好坏都解释不了 | 演化树是**处理项**（手写的），不是尺子——它自己的「交卷前自己核一遍」里两条写反了（问「没唱到的词是不是几乎看不见（< 0.45）？」「当前词的高亮是不是中性灰？」，与规则正文正相反），智能体照着做就正好踩判红的那两条 | 跑之前把**处理项当尺子一样自查**：清单与规则正文必须同向。发现时那条臂已经跑了 25 分钟，直接**停掉、改、重起**——别拿一个有歧义的处理项去解释读数（分数低了说不清是「这招不管用」还是「清单措辞把人带沟里了」）。2026-10-22 实测：B 线第五轮起跑前发现，只改末尾两行清单（④「看得清（≥ 0.45），不能几乎看不见」、⑤「高亮落在品牌三色里，不能是中性灰」），手册正文一个字未动 |

| 42 | **同一类情形按「谁掐的」给出不同处置**：提供方掐死 ⇒ 作废；时间上限掐死 ⇒ 记 0 分——两条 rollout 结构完全相同 | 演化臂 r1（**提供方**掐死，`final.txt` 空 + 末步 `finish.reason.kind=="error"`）与 r5（**我们自己的 5400s 上限**掐死，`exit_code=124`）**结构一模一样**：都被掐在半路、盘上只有没有 token 契约的 HTML 候选、判据证据都写着「量不到」。但 r1 作废、r5 记 0 分。分类的依据跑偏了——**该看的不是「谁掐的」，是「有没有可比的行为样本」** | 两边都有据（作废派：作废的完整条件是「被掐死 且 没有可判的交付」；记 0 派：仓里写明「跑满上限被掐死是行为表现」，而且作废超时项**反保守**——手册让会话变长 ⇒ 更容易撞上限 ⇒ 作废掉恰好把「用手册的代价」藏起来了）⇒ 按「修判据与调尺子的分界是理由，不是效果」的纪律，**判据代码不动、留成明写的未决项，两种处置的读数一起报**（2026-10-22：主读数 Δ=0.75/p=0.0333、处置B Δ=1.0/p=0.0119、最坏情形「作废当零分」Δ=0.5/p=0.0909，**三种都通过**，结论不依赖处置的选择）。**教训**：把「未决项」明写出来，比偷偷挑一个对自己好看的处置诚实得多 |

| 43 | 归因口径太宽：「智能体读了仓库里的文件」被当成「智能体自己找到了真相」 | 「读产线事实源」有两个意思：**读内容**（`tools/foodnames/data/*.json` 的词表——任何认真的智能体都该读）与**读版式**（`templates/video_style.css` / `layout_rules.mjs`——**只有它能带来 0.45 与品牌三色**）。按「有没有读过 `usine/…` 路径」计数，会把读了词表的那条误判成找到了版式真相 | 归因要数**只可能带来答案的那个文件**：`"type":"tool/call"` 的行里出现 `video_style.css` / `layout_rules.mjs` 才算。2026-10-22 实测（17 条 rollout 逐条数）：基准臂 6 条**全部 0 次**（连找都没找）；演化臂 6 条里只有 r6 读了 3 次，**另外两条通过的（r2/r3）一次都没读**——值来自手册正文；第三臂唯一那条通过（r1）读了 4 次，**是它自己找到了真相，不是树教的** |

| 44 | 机制计数**求和** ⇒ 结论被「被掐死的那几条事件数天然偏少」污染 | 演化臂有 2 条被提供方掐死，事件流只有几十条；把它们和跑满全程的几条求和，比出来的 shell 用量差可能只是「它被掐早了」，不是它更省 shell | 机制计数**逐条统计、按「计入 / 作废」分组**，只比**计入条目的均值**。2026-10-22 实测：求和口径下演化臂 pwsh 79 次看着比基准臂 77 次还多；分组求均值后是基准 19.2 / 演化 24.5 / 第三臂 **5.4**——第三臂那条通用回退规则压 shell 用量的效果才显出来（它压到约 1/4），而它救不了产线专有的版式规则 |

| 45 | 判据把**「量不到」当成「达标」**——一个只渲染当前词、其余全藏起来的页面白拿一分 | `check_scene_tokens.mjs` 原来写的是 `const opacityOk = m.minOpacity === null ? true : m.minOpacity >= 0.45`：**量不到暗词不透明度（null）⇒ 判通过**。2026-10-22 实测：RSI B 线第三臂 r5 的交付页有 12 个 `.tok`，但**只渲染当前那一个**，其余 11 个 `display:none` / 零尺寸 ⇒ `minOpacity` 量不到 ⇒ 这条判据被记成通过（0.5 分里有一分是假的）。它同时也不满足另一条（中性灰高亮），真值应是 0 分 | 「量不到」有三种归宿，**没有一种叫「达标」**：① 门跑不成（页面上一个可见 token 都没有）⇒ `measurable=false`，整条 rollout 不进分布；② **量到了「看不见」这个事实**（非当前 token 一个都没渲染）⇒ **判红**，证据要写清「N 个 token、可见 M 个、其中非当前 0 个」；③ 量到了具体的低不透明度 ⇒ 判红。修法：`m.minOpacity !== null && m.minOpacity >= TH.other_token_opacity`，并把 token 计数带进证据。**同一个洞在生产门 `check_video_layout.mjs` 里也有一份**（`dom.others_opacity === null || ...`）——一并修了；已记的读数**可证不受影响**（2026-10-22 复核：24 期报告 576 条 `others_opacity` **无一条 null**，取值只有 0.18 与 0.45） |

## 附：`usine/人物宣传图.zip` —— 一个被登记下来的孤立大文件（不删）

`usine/人物宣传图.zip` **32,074,712 字节**，2026-10-19 的 LFS 迁移提交 `37075a6`（`chore: 大文件（图片/音视频/压缩包）统一走 Git LFS`）把它以 LFS 对象入库（blob `64e85153`）。**它是那次迁移的副产物，不是任何一个流程的产物**：

- `git grep 人物宣传图` 只命中它自己（二进制），**没有任何文本引用它**——没有 SKILL 指向它、没有测试读它、没有文档把它当样例。
- 它不在 `usine/skills/*/assets/` 也不在 `usine/examples/`，所以按落位口径它**本来就不该在这个位置**。

**为什么只登记不删**：它是**已入库的历史归档**，删它要重写 LFS 历史，而它既不挡门禁也不影响构建——为一个"看起来占地"的文件去动 LFS 历史，风险远大于收益。**这条记录的作用是让下一个人查到这里就知道它是什么、为什么还在**，而不是再花一次时间重新判断。

真要清理，正确的做法是**在专门的一次提交里**删它并说明「移除 32 MB 无引用归档」，而不是顺手指掉。
