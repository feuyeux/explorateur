# migration/ — TS 迁移工作目录（P7 清场时整体退役）

本目录是 usine → dsh（DeepSeek Harness）原生 TS 工程全量迁移的工作区：
金样本判据、基线记录、迁移专用脚本。**门禁不扫描本目录**；迁移期 usine 的
权威门禁仍是 21 套 Python 反向验证（`uv run feuille verify`）。迁移完成后
（P7）本目录随 Python 侧一并清场，金样本迁入 TS 门禁包后删除。

## 目录

| 路径 | 内容 |
|---|---|
| `baseline/verify-baseline.txt` | 迁移起点基线：21 套全 PASS（1 SKIP 诚实列出），本机全量 ≈19.5s（2026-10-18，macOS arm64；ADAPTATION 记录的 46s 为当时 Windows 宿主口径） |
| `golden/*.json` | 金样本判据（capture_golden.py 产出）：纯函数**逐字节对齐**，环境相关项带机桶元数据、断**结构与几何** |
| `golden/assets/` | 金样本实物：tts-cache（3 语料 mp3+词表）、textlayer 渲染 PNG（不透明整图 + 双 matte 抠像） |
| `capture_golden.py` | 采集脚本：`uv run python migration/capture_golden.py [tts\|audio\|timeline\|textlayer\|all]` |

## 金样本口径

- **纯函数**（缓存键 / 滤镜图 / 时间轴 / HTML 模板 / 转义）：TS 侧逐字节复现
  同一输出（含 sha256 缓存键口径——口径不许变，变了等于换缓存空间）。
- **机桶项**（视口亏空 / 像素哈希 / 时长）：随 `_meta`（机器 / 浏览器 / ffmpeg /
  edge_tts 版本）落盘；跨实现断结构与几何（alpha 覆盖率 / 包围盒 / 时长容差），
  像素逐字节只在同桶内作参照。

## 迁移期事实记录

- **2026-10-18：Edge TTS 服务端协议已变更（v2）**。微软于 2026-10-16 前后弃用
  `speech.platform.bing.com` 旧握手：钉版 edge-tts 7.2.8 在线合成稳定 403
  （离线门禁不受影响）。上游 rany2/edge-tts #491/#492：改走
  `api.msedgeservices.com` + Sec-MS-GEC **v2** 令牌，7.3.1 适配。本项目已将
  基线从 7.2.8 升至 7.3.1（pyproject 同步注明；21 套门禁复验全绿）。
  **TS 移植必须实现 v2 协议**；金样本 `tts.json` 的 `synth` 段即 v2 协议的
  实测输出（词级时间戳语义不变：offset/duration 单位 100ns）。
- 金样本批次 1（tts / audio / timeline / textlayer）已采集；后续批次随
  P2–P4 各阶段在 Python 侧退役前补齐。

## Spike 结论（P1）

### Spike 1 — TS 版 edge-tts v2 客户端（2026-10-18，✅ 通过）

落地 `packages/core/src/tts/`（drm.ts / pure.ts / client.ts），vitest 15/15 绿
（含 `FEUILLE_LIVE=1` 真机合成）。

- **v2 协议全貌（实测）**：端点仍是 `speech.platform.bing.com`——403 根因是
  令牌必须 v2，不是换域名（上游 issue 里的新端点说法与 7.3.1 实现不符）。
  v2 令牌 = `<CS64 16hex>-<魔改 SHA-256 64hex>`：SHA-256 换了第 14/29 轮常量、
  双状态注入（`_SHA256_STATE`）+ 14 字盐调度表注入，完全混淆——只能逐段
  照抄，不能化简。BigInt 承载 Python 无限位整数语义（乘 2^32+1 的旋转技巧、
  未掩码累加等），固定时间戳与 Python 输出逐字节相等（5 组 fixtures）。
- **协议坑（TS 侧已全部内置）**：握手 403 带服务端 Date 头 → 修时钟偏斜重试
  一次；文本帧 body 从首个 `\r\n\r\n` 的 +2 起（前导 `\r\n` 是 JSON 合法空白）；
  二进制帧前 2 字节大端长度 N 含长度字节、body 从 N+2 起；跨段偏移按 CBR
  48kbps 字节数精确折算。
- **mp3 字节非确定（服务端行为，非客户端缺陷）**：Python 7.3.1 自身连跑两次
  同文本，sha256 即不同，但字节长度 / 词级时间戳 / ffprobe 时长完全一致。
  金样本 `synth[].mp3_sha256` 只是采集时快照，**不作 parity 门禁**；门禁改比
  结构几何：词表逐字节 + 字节长度 ±64 容差（CBR 下长度即时长；实测 TS 与
  金样本同为 15840B、probe 2.640s 逐字节同）。
- **遗留到 P3**：4096 字节分片（`split_text_by_byte_length`）与内容寻址缓存
  （`synth_cached`）；spike 只做单段合成 + 重试。


### Spike 2 — sharp + canvas 成像管线（2026-10-18，✅ 通过）

落地 `packages/core/src/imaging/`（matte.ts / draw.ts / index.ts），依赖
sharp + @napi-rs/canvas（Skia，预编译二进制）。判据走共享 op-spec
（`golden/assets/scenes_ref.spec.json`）：Python(Pillow) 与 TS(Skia) 按同一份
数据渲染，杜绝两侧漂移。

- **matte 数学：逐像素逐字节 parity（0 不等字节）**。TS(sharp raw) 与
  Python(Pillow+numpy) 对同一对 matte_w/matte_b 截图输入输出完全相等——
  双 matte 是解码后的纯数学（alpha=255-max(C_w-C_b)、去预乘 C_b/a、
  astype(uint8) 截断），不存在栅格化自由度；alpha 结构统计
  （coverage 0.05237 / mean 61.08 / max 255 / bbox）与金样本一致。
  **P3 textlayer 可直接按逐字节判据入迁移。**
- **rig/scenes 渲染：结构 parity，阈值实测校定**。关键语义差（实测探针证明）：
  **PIL 的 arc/ellipse 描边从 box 内接椭圆向内加粗，canvas 居中描边**——TS 侧
  路径须内缩 width/2，否则弧带整体外扩（修正前 p99=49，修正后 p99=5）。
  其余对齐：PIL box 闭区间(+1)、角度同约定（0°=三点钟、y 向下顺时针）、
  gradient 逐行带状着色（banker's rounding）、SS 超采样 + LANCZOS 缩回
  （sharp lanczos3）。
- **判据口径（机桶纪律）**：降采样 270×480 灰度的均值绝对差与 p99——
  实测 mean=0.144 / p99=5 / max=79（max 为单像素 AA 尾部），门禁阈值定
  mean<0.5、p99<15（留机桶余量）。Pillow↔Skia 边缘 AA 必然不同，
  比结构与几何，不比像素。
- **遗留到 P4**：DrawScaled 代理、65 个注册场景名、rig TB/T 变换壳在
  draw.ts 的 op 面上铺开（op 面已覆盖 scenes/rig 用到的全部绘制原语）。

### Spike 3 — dsh 插件最小骨架（2026-10-18，✅ 通过）

落地 `packages/dsh-plugin/`（P6 工具面全量接线的种子）。插件形状按 dsh 插件
契约（Cordis plugin：`export const name` + `apply(ctx)`；工具走
`ctx.tools.register()` raw ToolDefinition 通道——MCP 工具同通道，最小骨架不
引入 dsh 运行时依赖，dsh 类型仅编译期 link:）。

- **钉版执行**：PATH 上全局装的 `dsh` 是 0.1.5-rc.3，**不是钉的 rc.2**——一律用
  本地 checkout 启动：`node /Users/han/coding/deepseek-harness/apps/cli/lib/bin.js
  web --patch <usine>/packages/dsh-plugin/feuille-usine.cordis.yml`。
- **关键事实：dsh 宿主是纯 node，无 TS 变换钩子**——`@feuille/core` 的 exports
  指 TS 源（vitest 吃得了，dsh 吃不了，实测 `failed to import`）。对策已定型：
  **dsh-plugin 用 esbuild 把 core 源码打进单文件 dist/index.mjs**，sharp/
  @napi-rs/canvas/ws 三个原生依赖保持 external 并声明为 dsh-plugin 自己的
  dependencies（pnpm 同 store 去重，运行时从其 node_modules 解析）。
  该对策即 P6 的加载模型，不在 P6 再议。
- **加载与激活证据**：`dsh web --patch` 启动干净（对照：修正前同样启动会打
  `dsh: warning: 1 entry did not activate` + `feuille-usine: failed to import`）；
  正面证据是 `packages/dsh-plugin/test/plugin.test.ts`——**vitest 吃的就是 dsh
  实际加载的构建产物 dist/index.mjs**（假 ctx 断言注册形状 + `usine_version`
  执行回程 + fiber 销毁反注册反向验证）。进程内 @feuille/core 调用接缝
  （无 subprocess 桥）在此证明可用。
- **如实记录：动态 HMR 未证明**。dsh-hmr 对 patch yml 做精确路径 watch，但
  web profile 下 yml 变更（含故意改坏语法）stdout 全程静默，无重载/报错
  反馈可观测。P1 验收口径为「--patch 机制下加载激活成功」；watcher 的动态
  行为留到 P8 的 dsh Web UI 实测一并看。
- 根 `pnpm test` 现在先 `--filter @feuille/dsh-plugin build` 再跑 vitest
  （测试依赖构建产物，单命令确定性）。

## P2 基础层迁移（2026-10-18，✅ 完成）

platform / errors / packaging / ledger / framehash 五模块 TS 落地 + CLI 三叶子
接线 + 反向验证五套移植（verify_ledger / verify_framehash / verify_platform /
verify_cli / verify_audit 打包节）+ 金样本批次 2 采集。门禁：typecheck 绿、
vitest 68 passed / 1 skipped、Python 侧对应四套 verify_*.py 全绿（rc=0，双轨纪律）。

### 金样本批次 2（migration/golden/ledger.json + framehash.json）

- **ledger `_digest` 跨语言逐字节 parity 已证**：sha256("v2" + `|label:sha` 逐段)
  是纯字节数学，夹具（UTF-8 中文 + 二进制字节）以 base64 内嵌金样本，TS 复算
  与 Python 引擎**逐字一致**（two_parts / order_swapped / label_changed /
  with_binary / empty / missing→null / one_byte_changed / reproducible 八形态全对）。
- framehash 纯函数（classify 三形态 / firstDrift 四形态 / 基线文件格式含非
  ASCII 文件名）同样逐字节对齐。framehash 本体（解码像素）按桶逐机重采，
  不进跨语言金样本——TS 桶成像库段是 sharp（Python 是 pillow），**桶名不同
  是设计内**，迁移切换 = 一次保守全量重渲（账本条目全判过期）。
- 采集口径：`uv run python migration/capture_golden.py ledger framehash`。

### 移植中新踩的坑（复用价值）

- **块注释里写不出「星号+斜杠」字面量**：ledger.ts 的 JSDoc 注释曾写
  `langs/*/manifest.json`——`langs` 后的 `*/` 把注释提前关闭，后半段注释
  连同反引号变成代码，模板字符串配对从此错位，报错全在下游几百行处
  （TS1005/TS1109/TS1160 连锁，第一现场无错）。Python `#` 注释无此坑，
  移植时 glob 字面量一律写成 `<*>` 或改行注释。
- **ESM 导出绑定不可 monkeypatch**：Python 反向验证用
  `ledger.toolchain = lambda: {...}` 模拟工具链读不到；TS 侧 `export function`
  是不可变绑定，改为显式测试缝 `overrideToolchainForTests(tc | null)`
  （带 cache 重置），语义与 monkeypatch 等价。
- **vitest afterEach 共享 tmpRoots 的清理时序**：describe 收集期建的临时目录
  会被第一个测试的 afterEach 清掉——夹具目录必须在每个测试内重建。
- **CLI 路由回退还参契约**：TS 骨架曾漏了 Python 侧 `argv.insert(0, cmd)`
  （组键回退时 cmd 是叶子第一个参数），verify_cli 移植时补齐并加了形态测试。

### 性能修复按设计内建（不先移植再修）

- `ledger.toolchain()` memoize 进程内缓存（浏览器 size+mtime 与 ffmpeg 版本
  一次进程内不变）；测试缝 `resetToolchainCacheForTests()`。
- `framehash()` 按 (path, size, mtime) 键 memoize（report 循环反复点名同一
  片子不再重复 spawn ffmpeg）；反向面有测试锁住「文件变了拿不到旧哈希」。

### 口径对齐明细（与 Python 逐条核对过的）

- CLI：无参 / -h / --help / help → usage + 退出码 0；未知命令 → 2；
  FeuilleError → stderr + 1。ledger status 空账本 → 0。
- `read_baseline` / `save_baseline` 两空格分隔、排序键序、非 ASCII 文件名
  逐字节一致；`-map 0:v` 在 framehash/perFrame 双双承重（源级断言移植为读
  源文件抓函数体，Python 侧 inspect.getsource 的对应物）。
- 已知且不追的量化差：diffPng 热力图的 601 灰度量化与 PIL convert("L") 的
  定点舍入可差 ±1——它是人看的证据图不是判据，权重（299/587/114）与结构
  对齐即可。slug 的 Unicode isalnum 差异同理（桶名各段实际都是 ASCII）。

## P3 中间收口（批次 3）：tts 全量（分片/缓存）+ audio + timeline + num

金样本批次 3：`migration/golden/tts_split.json`（edge-tts 7.3.1
`split_text_by_byte_length` 十例，逐字节 b64 对齐——含**上游 quirk**：无分隔符
长文本的安全切点在整段剩余文本上求最大合法 UTF-8 前缀，会产出超过限长的单块，
实测 `"a"*9000 / 4096 → 一个 9000 字节块`。按行为钉住，不"顺手修"）。
audio/timeline 金样本沿用 P0 采集（filter_graph 逐字节、enrich_lines 对
金样本 mp3 实测、karaoke_points/frac_at 浮点逐位）。

- `tts/split.ts`：字节级移植（Buffer.lastIndexOf 对 rfind、fatal TextDecoder
  对 UTF-8 安全点、& 实体回退、ASCII 空白 strip、切点 0 前进 1）。
- `tts/client.ts`：多段重构——转义+清洗后按 4096 切，每段各开连接、各重置
  chunkAudioBytes、各享一次 403 偏斜重试；段间 CBR 补偿不变。
  live 测试加长文本多段用例（FEUILLE_LIVE=1 门控）。
- `tts/synth.ts`：synth_cached 移植 + **时长边车 `{key}.dur`**（设计内置的
  性能修复：HIT 读边车零 ffprobe，边车缺失探测一次并补写；哨兵值测试钉契约）。
  `{key}.json` 保持纯数组形态（与 Python 迁移期缓存互读），readMeta 兼容老
  `{words:[…]}` 形态。
- `audio.ts`：filter_graph（adelay/amix|anull/apad→loudnorm→atrim，坑③顺序
  纪律由测试断言钉住）、compose_track、probe_duration；整值浮点走 pyFloat
  （`10.0` 带 `.0` 尾）保滤镜图字符串跨语言逐字节。
- `timeline.ts`：compute_starts / enrich_lines / karaoke_points / frac_at；
  enrichLines 增设可选 `durs` 实测时长表（synthCached 的时长直通——全缓存
  命中时零探测；缺省仍逐行 ffprobe，Python 口径不变）。karaoke 字符进度按
  **码点**（Python len()），不用 UTF-16 .length（增补平面字符会双计）。
- `num.ts roundHalfEven`：Python round 的真移植。**两次翻车的实录**：
  1. 乘积判平手不可靠——`2.6749…×100` 的浮点乘积会拉回精确的 `267.5`，
     假平手 → round(2.675, 2) 得 2.68（Python 2.67）；
  2. BigInt 精确展开（值 = m·5^s/10^s，s=-e）重写时丢了 `×5^s` 一步，
     全函数归零（插桩定位）。
  终版：double 位拆解 → BigInt 精确十进制 → 整除平手取偶；对 Python round
  **2000 例随机 fuzz 逐位一致**（含 0.5/0.125 精确平手与 2.675 类二进制陷阱）。

### 本批移植新坑

- **`x*10^d` 判平手是假平手**（见上）：必须取二进制精确值的十进制展开。
  Python round 与 JS toFixed 的口径差异也在此——toFixed 在 V8 对 2.675
  这类值同样不可靠，不可用作替身。
- **测试里 contentHash 参数序**：synthCached 的键序是 (voice, rate, pitch,
  text)；测试按 (text, voice, …) 预置缓存会静默 miss（还把离线测试逼去
  真网络直到超时）。反向面：key 序敏感性本身有测试钉住。
- **karaoke 点位下标**：词首点在前、`c += 词距` 在词首点之后——测试里
  "首词尾点"实际是 pts[2]（含词距）不是 pts[1]。

### 口径对齐明细

- filter_graph 三形态逐字节（含 `whole_dur=10.0` 的 Python float repr）；
  adelay 毫秒 = Python `int(round(s*1000))` 的银行家舍入。
- probe_duration 对金样本 mp3 逐值一致（同机 ffprobe 桶内确定性）；
  enrich_lines 的 file_dur/tail_silence/start/total/span 对金样本全对齐。
- compute_starts 四形态、karaoke_points/frac_at 浮点逐位一致
  （末点 `5.050000000000001` 这类二进制痕迹逐位复现）。
- 分片十例逐字节一致（换行优先/空格/UTF-8 边界/& 实体/strip/超限单块 quirk）。

门禁：typecheck 干净；vitest 96 passed / 2 skipped（live 门控）；
Python verify_tts 16 PASS、verify_audio 8 PASS、verify_timeline 13 PASS
（双轨期 Python 门禁持续在跑）。

## P3c：textlayer（Edge 渲字层）

`packages/core/src/textlayer.ts`：htmlEscape / page（金样本逐字节）+
viewportDeficit（**memoize 设计内置**：亏空按 (browser, nominal) 键进程内缓存，
Python 侧每次截图都要多开一次浏览器探亏空；命中不写探测 HTML——测试以此
为证）+ edgeScreenshot / shootMatte（execFileSync 同步 spawn，串行纪律由
机制天然承载）。matte 数学沿用 spike 2 的 imaging/matte.ts。

### parity 结果

- html_escape / page：与 Python 逐字节（金样本 4+2 例）。
- matte：**金样本双底输入对 → 与 Python PIL 输出逐像素零差异**（matte 只做
  解码后的纯浮点同序数学，证明 spike 2 的口径移植是精确的）。
- 合成夹具（verify_textlayer §1 移植）：alpha ≈128 ±2 区内均匀、去预乘
  R ≈200 ±4、底区全透明、全不透明 ≥253——「双底除底色外逐字节同构」契约
  的数学验收。
- 真机（同机桶）：视口亏空 84px 与金样本一致；中文单次截图裁齐 (400,300)；
  **阿拉伯 RTL + text-shadow 渲字**的 alpha 结构统计（coverage/均值/包围盒）
  与金样本逐值一致——这正是「文字必须走 Edge 截图不许成像库画字」铁律的
  活证据。

### 观察项（不追）

- packaging.test.ts 出现过一次「zip truncated」后连续 4 轮全绿——一次性
  文件系统抖动，暂记录在案；复发再查。

门禁：typecheck 干净；vitest 105 passed / 2 skipped；Python verify_textlayer
12 PASS（双轨）。

## P3d：compose / render / covers（P3 收口）

`packages/core/src/compose.ts`：lineSpans（roundHalfEven(t,3) 口径）+
filterGraph（纯函数留 `{y}`/`{between}` 槽；dur `.3f` 定点）+ mux
（spawnSync 捕获 stderr，rc≠0 抛错带尾 2500 字）。`render.ts`：encodeFrames
（raw rgb24 管道；sharp 帧自动转 RGB 对齐 PIL convert("RGB") 的丢 alpha 口径；
坏帧显式抛错且先把 ffmpeg 进程收尾，不留悬垂进程）。`covers.ts`：SPECS/
filename/spec/cropBackdrop/make/displayCrop/sheet/check + CLI 适配
（cover/make、cover/check 进 commands.ts 路由表，叶子薄适配）。
cropBackdrop 属活代码（lesson 管线用），与 skills 死代码三件
（crop_backdrop 拷贝/taglist/describe，P5 不迁）不冲突。

### 坑与实录

- **packaging zip 截断——复发且追查，是生产 bug**：P3c 记过一次观察项，
  本批 4 轮全量挂 2 轮，按「复发才追」约定开箱。根因：zipTree 的收尾
  Promise 挂在 yazl 读流的 `end` 上，而非写流的 `close`——高负载下读流
  超前写流，zipTree 提前返回，紧接的开包读到半截 zip。修为 `ws.on('close')`
  后连续 4 轮全量全绿。**交付包在高并发下会真损坏，不是测试 flake。**
- **describe 作用域建临时目录 = 定时炸弹**：`const d = tmp()` 写在 describe
  体里会在收集期建目录，而文件级 afterEach 在**第一个测试后**就清掉全部
  已注册临时根——后续测试拿到已删除的路径（sharp unable to open for write
  / ffmpeg 造母版失败）。修法：每测试体内 `tmp()`；compose 真机 smoke 并为
  单个自建自验测试（与 verify_compose 单趟同构）。
- sharp 实例不能再喂 `sharp()`（无此重载）——帧源类型用
  `ReturnType<typeof sharp>`，转 RGB 直接在实例上 `.removeAlpha().raw()`。
- vitest 断言注意 `it.each` 元组里 `ink=ink` 是 Python 惯性，TS 位置传参。

### parity 结果

- line_spans [[0,1],[1,2.1],[2.5,3.6]]、filter_graph 要素串、apad<loudnorm、
  mux 无 -shortest + 显式 `-t dur.toFixed(3)`——与 verify_compose §0–§3 逐条对齐。
- 真机 smoke：成片 3.00s；t=1.5 R≈255/G<60、t=0.5 R≈128；音轨 aac。
  Python 侧同趟 (R 254 G 0 / R 128)。
- covers：check 尺寸/底色反例、displayCrop 进/出安全区墨迹判据
  （sharp 墨块夹具全机器可跑；Edge 真渲字部分浏览器门控）、sheet (1440,2522)。
- render 契约：72 帧 @24fps → 3.0s；帧不足 → 短于 dur 且 rc 0（无静默补帧）；
  错尺寸帧显式抛错。

门禁：typecheck 干净；vitest 19 文件全绿（136 用例，2 skipped live 门控）
×4 连续；Python verify_compose 11 PASS、verify_covers 10 PASS；已迁模块
全量复跑（platform 11 / ledger 19 / framehash 22 / cli 8 / tts 16 /
audio 8 / timeline 13 / textlayer 12）全绿。**P3 音画内核迁移完毕。**

## P4a 收口（data / audit / manifest / metrics）

### 移植模块

- `packages/core/src/data.ts`：personas / 编外专班 storyteller.json / 语言目录
  manifest / intro-cards / 字体 CSS / 旗帜 emoji / 语种标签。ROOT 以
  pnpm-workspace.yaml 为标记向上走（FEUILLE_ROOT 环境变量可覆写）；Map 缓存
  按目录实参分键（lru_cache parity）+ `resetDataCacheForTests` 测试缝。
  sceneDoc 延到 P5（依赖 parse_scene）。
- `packages/core/src/audit.ts`：九语种格律计数器（印地 matra / 阿语音节 /
  希语闭音节优先 / 中文按字 / 俄语元音 / 希腊双元音 / 德语 sch-ch-ph-th→X /
  西语元音组 / 韩语谚文方块）+ auditOne 三态（✅/❌/○ 主动不作声称）+
  auditAll 汇总。`\p{M}` + normalize 对齐 unicodedata；pyList 复刻 Python
  list repr（`[7, 7]` 带空格——auditOne 状态串文案 parity）。
- `packages/core/src/manifest.ts`：PLATFORMS 表驱动、文案稿解析（两版体例：
  时长/已发布标记可选）、check_copy 平台限制、fill_annotations 按
  `[...str].length` 实测回填、build_manifest 素材存在性前置。
  taglist 是死代码不迁（P5 归流审计确认）。
- `packages/core/src/metrics.ts`：台账 load/save（sortKeysDeep 单源升为
  ledger.ts 导出；utcNowIso 对齐 isoformat(timespec="seconds")；.json.tmp +
  renameSync 原子换）、merge_results 悬空引用当场报错、check 两级凭据分开判、
  analyze 样本不足不排名 + 分箱。JS `{}` 为真值（Python `{}` 为假）——
  空 metrics 守卫一律 `Object.keys(m).length > 0`。
- index.ts 导出 data/audit/manifest/metrics 四个命名空间。

### 测试（verify_*.py 的 vitest 对应移植）

- `audit.test.ts`：合成多语诗稿计数器全命中手数期望值（防循环验证——
  期望值手工独立数出，跨语言值一致本身就是 parity）+ 三态逻辑 +
  混合拆分以算法为准 + auditAll 汇总行。
- `manifest.test.ts`：12 语种 × 三平台合成文案稿全解析、两版体例、缺块拒解析、
  四类问题、坑㉲ emoji 码位区间、fillAnnotations 往返、buildManifest
  素材前置 + 清单落盘回读。
- `metrics.test.ts`：好台账放行、悬空引用、两级凭据、指标取值域、
  null ≠ 0「不知道」、部分回填 0/6、样本不足不排、分箱、save→load 往返 +
  版本护栏。
- `data.test.ts`：ROOT 定位、索引形状（28 personas / 28 cards / 语种目录）、
  缓存同对象引用 + 目录实参分键互不串味、未知语种报错、编外专班缺目录
  = 空专班。

### 坑与实录

- **hookShape 的 `first[0]` 是半个代理对**：JS 里 `"...🍂..."[0]` 取到 lone
  surrogate，codePointAt 落在代理区段，astral emoji 全判非 emoji——
  小红书钩子全错判成 question。修为 `[...first][0]` 按码位取整字。
  （Python first[0] 即整字，无此坑。）
- **捕获 stdout 的 join 时机**：`captureWrites()` 在调用瞬间 join——
  模块还没跑，断言拿到空串。改为 capture 后 join（audit 的汇总行还带
  前导 `\n`，需按 `\n` 切再 find）。
- **夹具目录要先建**：Python `parent.mkdir(parents=True)` 的习惯在 TS
  writeFileSync 前要显式 mkdirSync——metrics 的 video 夹具、manifest 的
  video/covers 目录各炸一次。
- **「取首句不取首行」的正例方向**：问句在前、句读在后
  （"你见过吗？……"）才是首句判钩子的用例；问句在后按算法就是陈述句，
  别把错误的期望写进测试。

门禁：typecheck 干净；vitest 23 文件全绿（179 用例，2 skipped live 门控）
×4 连续；Python verify_audit 23/23、verify_manifest 25/25、
verify_metrics 13/13 全绿。**P4a（data/audit/manifest/metrics）收口。**

## P4c：pildraw + rig + scenes + devices——人物与场景全量（含数值 parity 逐位一致）

### 实现（packages/core/src/）

- `imaging/pildraw.ts`：PIL ImageDraw 语义基座（rectangle 闭盒 x1-x0+1 /
  outline 内缩 lw/2 / ellipse 弧线内缩 / arc 内缩 / line 平头 + joint=curve
  圆角连接——粗线圆头 rig 的 CAP 自己补端圆）。DrawScaled 代理（scenes）与
  draw.ts 的语义坐标 setTransform 是两条并行道：pildraw 是 PIL 像素语义的
  忠实对应物，draw.ts 的 DrawSpec 线用圆头是金样学校准过的既有口径——
  分歧是有意的，两处注释各自声明。
- `rig.ts`（~1600 行，rig.py 全量）：数值约定逐条钉死——Python `int()` =
  向零截断 → mix / LN / ARC 宽度一律 `Math.trunc`；`round(s,2)` 走
  num.roundHalfEven；**拼种子串过 `pyFloat`（Python str(2.0)="2.0"、JS
  `${2}`="2"——差一个 ".0" 种子空间就换）**；rnd = sha256 前 8 字节大端 ÷
  2^64，与 Python 大整数除法逐位一致。CharCtx 的 E/RR/LN/CAP/ARC 等绘制原语
  全部是**箭头方法字段**（场景阶段函数解构 `const { E, RR } = c` 后 `this`
  仍在——普通方法解构即丢脸）。37 姿态注册表 + POSE_CODES 派生、
  opennessAt 词级口型、BEARD_LEGACY 留作反向验证接缝。
- `scenes.ts`：DrawScaled（box×k / flat 数组配对 / line·arc 宽度
  `max(1,trunc(w·k))`，roundedRectangle 的 width **不**缩放——Python 代理
  原样如此）+ prerenderBg（逐语义行 mix 截断渐变 → sharp **linear kernel**
  （=PIL BILINEAR）上采样 SS 画布 → 场景绘制 → LANCZOS 缩回，返回 sharp
  管道而非 Buffer——调用方 .convert("RGBA") 对应 .composite）+ 62 场景函数
  65 注册名（arch/lantern/boardn 双名，注册表与 Python 金样本逐名对账）。
- `devices.ts`：16 样式注册表 + drawDevice（未知 style 当场报错）+ chip 两型
  契约 + LAST_WELL_RGB 跨调用副作用（`export let` live binding）+
  GROUND_Y 地面线（`setGroundY(null)` = 封面不画悬空立柱；ES import 绑定
  外部只读，写必须走模块内函数）。
- index.ts 导出 rig/scenes/devices 三命名空间；tts.pure 的 clamp 导出
  （单一事实源在 tts，rig 只引用不复制）。

### 测试（verify_rig.py 的 vitest 移植 + 注册表金样本）

- `rig.test.ts`：A1–E2 几何探针全量移植（判定窗/取样点/阈值逐字保留）。
  渲层 = napi canvas SS 超采样 → 2×2 块平均（PIL BOX 下采样的整数倍精确
  等价）。三人设全探针放行 + C1/C2 抬臂族五官 + A1 凿洞自证 + 幂等。
- `scenes.test.ts`：注册表键集对 `golden/scenes_registry.json`（Python
  落盘）逐名一致、双名注册同一函数引用、全 65 场景一张卡渲染冒烟、
  未知场景名静默跳过（Python `SCENES.get` 语义）、幂等。
- `devices.test.ts`：注册表键集金样本对账、chip 两型（"1" 是字牌不是色片）、
  well 推导、未知 style 报错、LAST_WELL_RGB 逐调用更新、panel 的
  GROUND_Y=1700/null 两分支——画法断言用录制桩（断「画了什么」比像素反推准）。

### 坑与实录

- **pyFloat 种子串**：opennessAt 的 amp 种子拼 `round(s,2)`——整数值浮点
  Python 渲 "2.0"、JS 渲 "2"，一个 ".0" 换掉整个 rnd 空间。探针
  `open2`（词首恰 2.0）两侧同为 0.9602105028403203 证明修齐。
- **sharp 类型引用**：sharp 的 d.ts 是 `export =` 命名空间，default import
  下 `sharp.Sharp` 不可作类型——用 `ReturnType<typeof sharp>`；resize 的
  双线性 kernel 叫 **linear**（bilinear 是插值器名不是 resize kernel 名）。
- **noUncheckedIndexedAccess 连 TypedArray 索引也判 possibly undefined**：
  探针的热循环里 `rgb[o]` 全部要 `!`——纯 TS 严格性开销，无语义影响。

门禁：typecheck 干净；vitest 26 文件全绿（197 用例，2 skipped live 门控）
×4 连续；Python verify_rig 27/27 复跑全绿（双轨期纪律）。**P4c（rig/scenes/
devices + pildraw 基座）收口。**

## P4b：persona——人设契约校验器（②③ persona 半边收口，P4 全批完成）

### 实现（packages/core/src/persona.ts + CLI 叶子）

- `validatePersona(p, where?)`：纯函数零 I/O（反向验证直接喂坏数据）。
  合法值**现取注册表不复制**（纪律 7）：脸型 → rig.FACE_SPECS 键、moves
  槽位值 → rig.POSE_CODES（37 码）、声线安全域 → tts.SAFE_RATE/SAFE_PITCH
  （±20% / ±12Hz，parseSigned 同源）。NaN 放行按 Python 原式镜像
  （`val <= 0` 两边都为假）——不「顺手修正」，行为漂移本身就是 parity 破坏。
- `validateRoster`：id 唯一（id = rnd 种子命名空间）+ 每语种一男一女 ×
  一活泼一沉稳（活泼当 A / 沉稳当 B 的选角分工依赖它）。
- `mainValidate(argv)`（`feuille persona validate [--personas DIR]`）：
  逐人走 personasDoc **原始清单**而非 {id} 索引——索引会把重复 id 静默折叠，
  班底级「id 唯一」就永远验不出来（Python 侧同一句话的坑，原样保留）。
- CLI：commands.ts 注册 `persona/validate` + 薄叶子（判据全在 core）。
- index.ts 导出 persona 命名空间。

### 测试（verify_personas.py 的 vitest 移植，18 项 → 20 用例）

- 好数据放行：28 人逐人零问题 + 班底不变量全过。
- 反向 12 条定向破坏：坏脸型 / 坏姿态码 / 坏 hex / 缺调色板键 / rate 与
  pitch 越安全域 / locale 分隔符 / 档案字段清空 / 私加槽位 / 挂件 physics
  非法 / 眨眼周期 0 / energy 非法——每条断关键词命中。
- 班底反向：撞 id → 「重复」；同语种同 energy → 「一活泼一沉稳」。
- 注册表活性：FACE_SPECS 六型脸、POSE_CODES ≥ 30。
- CLI 端到端：缺省班底 → 0；坏班底目录（撞 id + 坏 locale）→ 1；
  cli.test.ts 补 `persona validate` 经路由可达用例。

门禁：typecheck 干净；vitest 27 文件全绿（218 用例，2 skipped live 门控）
×4 连续；Python verify_personas 18/18 复跑全绿（双轨期纪律）。
**P4b 收口——P4（data/audit/manifest/metrics/rig/scenes/devices/persona）
全批完成。**

## P5 第二批（P5-2a）：scene_schema 场景校验层

日期：2026-10-18　对应 Python：src/feuille/scene_schema.py（472 行）→ packages/core/src/scene_schema.ts

### 实现（packages/core/src/scene_schema.ts）

- `validateScene(scene, personas?, cards?) → 问题列表`：纯函数零 I/O、不抛异常
  ——反向验证直接喂坏数据。合法值**现取注册表不复制**（纪律 7）：情绪 →
  rig.MOOD_FACE 键、姿态 → rig.POSE_CODES + ENTRY_POSE（bounce_in）、
  装置样式 → devices.DEVICE_STYLES。
- 合法说话人不写死：§0.4 `roles` 本课声明了谁就是谁（第三个人 = 剧本多写一行，
  代码零改动）。`unitsOf` 两形态统一清单（dialogue 每语种一单元 / polyglot 单元
  = 舞台、行内自带语标）——校验层按清单走，不各自 if/else。
- §8 选角（personas+cards 都给才跑）：dialogue 走 intro-cards cast 表；
  polyglot 按 §0.6 `locale + energy` 唯一解出（亮相卡 cast 表只有一个角色，
  同台三人无 C 角）。8b 彩蛋批注必须命中**本课演员真实色板**的 hex（悬空引用
  抓手）。姓名槽位随角色名走：`${role.toLowerCase()}Name`。
- Python 真值口径 `pyFalsy`（None/""/0/false/空数组/空对象皆 falsy）与 repr
  口径（单引号/None/列表字典）本地小helper，与 persona.ts 同款。
- **main 暂缓**：`scene validate` 的 main 需要 data.sceneDoc（依赖 parse_scene），
  随 P5-2b 一并接入——叶子不接半截线。

### 测试（verify_lesson.py §1–§2 的 vitest 移植，3 用例）

- 好数据放行：**全注册表演习**（16 device_style 一岛一台 + 台词行轮转铺满
  6 mood × 38 姿态码）零问题——注册表↔校验层契约测试。
- 凿洞十枪：坏 mood / 坏姿态码 / 坏装置样式 / 幽灵说话人 / token 幽灵键 /
  空角色表 / 缺节拍表 / 行号重复 / dialogue 带同台表 / polyglot 缺同台表，
  各自命中对应报错关键词。
- 实弹：真实课件 guangchaoshi-逛超市/scene.json × 真实班底 × 亮相卡
  → §8 选角/彩蛋全量数据下零问题（Python 侧同判据已探针确认）。
- §3 doctor 班底体检接线随 lesson.ts（P5-5）补。

门禁：typecheck 干净；vitest 28 文件全绿（225 用例，2 skipped）×4 连续；
Python verify_lesson 13/13 复跑全绿（双轨期纪律）。

## P5 第三批（P5-2b）：parse_scene 解析器 + data.sceneDoc 接线 + scene 两叶子

日期：2026-10-18　对应 Python：src/feuille/parse_scene.py（748 行）→ packages/core/src/parse_scene.ts

### 实现（packages/core/src/parse_scene.ts）

- 全量移植：`parseSpec`（§0 机读规格：meta/tokenOrder/tokens/devices/levels/
  roles/cast/beats 八字段**命名字段**——Python NamedTuple 堵下标误用的同款理由）、
  `parseLine`（台词行体例：引号四对优先级、注音（\*…\*）、⚑ 注记先行剥离、
  对照只认首段「——」、姿态码反引号、手势词「…」处、彩蛋批注、出画、polyglot
  语标段 `· locale`）、`applyBeats`（骨架节拍：完整覆盖 + 不重叠 + n-K 记法 +
  even/odd 按绝对行号 + 空问句节拍报错）、`parseLocales` / `parseSharedStage`
  （dialogue 每语种一剧本 / polyglot 一份共享剧本 + locale 薄壳）、
  `parseTokenWords`（`词 = 别形`（注音）全书写形）、`matchToken`（**最长命中**：
  ouest ⊃ est 的真实事故口径，casefold 近似 = toLowerCase + ß→ss）、`annotate`
  （游标单调推进 + think/hint 气泡）、`parseScene`（解析 → scene_schema
  validateScene 前置校验通过才返回）。
- **金样本字节 parity**：`pyJsonDump`（json.dumps ensure_ascii=False indent=1 的
  字节级对应物）+ `PyFloat`（Python float 落库带 .0：45 → "45.0"——
  durationBudget 逐字节 parity 的命门；valueOf/toString 让校验层免拆箱）。
  真实课件 guangchaoshi-逛超市 解析落盘与 Python 生成入库的 scene.json
  **逐字节一致**（Python 重生成字节不变已实测，入库文件即有效金样本）。
- 键序即落库序：line 对象 speaker→…→exits→[lang]→i→role→isQuestion→
  tokenKey→tokenChip→tokenWord→bubble 与 Python dict 插入序逐位对齐；
  cast/stage/dialogue 仅 polyglot 落库；lang 只在真写了才落库。
- 错误通道同构：FeuilleError 仅「剧本不存在」；体例违规对应 Python ValueError
  → 普通 Error（CLI 不接、退出码 1 的口径两边一致）。
- `data.sceneDoc` 补上预留契约：静态环 data ⇄ parse_scene（两边模块顶层都不
  解引用对方导出，ESM 活绑定保证调用时初始化完毕）——与 Python 侧延迟导入
  同构。`scene_schema.mainValidate` + `mainParse` 落地，CLI 注册 `scene/parse`、
  `scene/validate` 两叶子。
- 忠实镜像不「顺手修」：`meta_val` 的 `[^\S\n]` 坑（留空 rtlLocales 不吞下一行）、
  装置表 header[1]=="scenes" 判据（§0.3 语体表恰好 4 token 时会误当词表——
  Python 侧同样如此，原样保留）、tables() 行长不齐即另起一张表的分组法。

### 测试（packages/core/test/parse_scene.test.ts，20 用例 + cli 1 用例）

- 字节 parity 两条：parseScene→pyJsonDump 逐字节；mainParse --lessons 临时目录
  落盘逐字节。
- 反向：坏行缺引号、留白/重叠/反序节拍、空问句节拍（even/odd 写反口径）、
  缺 §0/缺 token 表/token 重复/缺节拍表/坏 durationBudget、缺剧本 → FeuilleError、
  缺 §2 剧本 → parse 自检就地失败。
- 长期命中的价值断言：ouest/est 最长命中、красн 词干命中变格形、
  lang 不落库、n-K 记法 + askBy 过滤、durationBudget 浮点口径 "45.0"。
- CLI 端到端：`scene parse` 路由可达 + 落盘字节 parity + `scene validate` 复查 → 0。

门禁：typecheck 干净；vitest 30 文件全绿（246 用例，2 skipped）×4 连续；
Python verify_lesson 13/13、verify_scene_audio / verify_publish / verify_audit
复跑全绿（双轨期纪律）。**P5-2 收口。**

## P5-3 scene_draft 草稿层（brief.json → scene.md 结构草稿）

### 实现（packages/core/src/scene_draft.ts；CLI 叶子 scene/draft）

- 全量移植 scene_draft.py：`render` 纯函数只填结构不生成内容（台词/词义/舞台
  留 TODO）；`expandSkeleton` 骨架展开（rest 吸收剩余行、n-K 记法的 relFrom/relTo
  判据）、`beatTableMd` §0.5 节拍表、`assignLines` 行归属（问句节 ask 奇偶 + Ask/
  Reply 变体、列表按节内行偏移逐行给）、`castFor` 选角（personas × intro-cards
  cast 表唯一解）、`gaps` 欠账清单、`mainDraft`（--brief 必填缺 → 2；--out/
  --languages/--personas/--force/--print-plan/--gaps）。
- 注册表全部现取：moods = MOOD_FACE 键、poses = POSE_CODES 归一 + bounce_in、
  deviceStyles = DEVICE_STYLES 键——姿态码先过 parse_scene.normPose 再查
  （md 写 `jump-celebrate`、注册表记 `jump_celebrate`，拿未归一串量注册表会误杀）。
- 金样本（migration/golden/scene_draft.md）：Python `feuille scene draft --brief`
  **落盘**产物入库——不取 --print-plan 口径（print 会多补一个换行，落盘字节才是
  render 真身，首跑 8 个失败里 5 个全是这个口径差）。真实 brief 全文
  **逐字节一致**。
- 忠实镜像不「顺手修」：
  - expand_skeleton 的怪文案：「骨架含 rest 项时不需要再给 n」实际在
    **rest 在场且未给 n** 时触发（这时必须给，rest_n 要靠 total 减）——条件与
    文案原样保留。推论：无 rest 不给 n 也报错，n 实际恒必填。
  - 装置 style 缺失：Python `{d.get("style")}` 集合进 None → 单 None 时报错名单
    印 `[None]`；None 混排字符串时 sorted() 抛 TypeError——TS 同样裸 TypeError
    崩溃（CLI 不接、退出码 1 口径两边一致）。
  - 骨架缺 lines 键：Python KeyError 崩溃 → TS 裸 Error（"KeyError: 'lines'"），
    不升 FeuilleError。
  - 错误名单渲染按 Python str(list) 口径：单引号 `['a', 'b']`、None 印 None。
  - `if d` 过滤空装置 dict（pyFalsy 口径）；`k in d` 用自有键判定（值假也算）。
  - noteOn 的 "exit" 是**子串**命中（mark.includes）；⚑TODO 与 ＋蹦跳出画 按
    节内行偏移点亮，草稿锚词槽写成最终形状 `«TODO» 处`（parse_line 正则只认
    带引号形式）。

### 测试（packages/core/test/scene_draft.test.ts，20 用例 + cli 1 用例）

- 字节 parity 三条：render 全文逐字节；mainDraft --brief 临时目录落盘逐字节 +
  欠账清单（台词行=51 = 3 语种 × 17，待写舞台=0）；--print-plan 只打印不落盘。
- 落盘纪律：无草稿标记拒覆盖（FeuilleError、原文件不动）→ --force 放行；
  带标记免 --force 重写；--gaps 只数不生成、目标缺失 → FeuilleError。
- 骨架反向：双 rest、rest 超载（负余行）、无 rest 缺 n / n 不一致、
  rest 缺 n（怪文案）、缺 lines 键 → KeyError 通道；beat_table n-4/n-3/n-2/n-1
  边界与 relFrom/relTo 矩阵逐格断言。
- 行归属：round 节 even 奇偶（A 问 B 答各取 Ask/Reply 变体）、列表短于节长
  越界退缺省、bye 列表逐行；选角 Миша/Аня 实名断言 + 空语种报人话。
- render 反向：坏语种/坏姿态/坏情绪/坏装置样式/单 None style/骨架只 1 行，
  定向命中各自报错；levels 与 rtlLocales 可选节给了才渲染（金样本无此节）。
- CLI 端到端：`scene draft` 路由可达 + 落盘字节 parity + 拒覆盖已定稿 → 1。

门禁：typecheck 干净；vitest 30 文件全绿（267 用例，2 skipped）×4 连续；
Python verify_lesson 13/13、verify_scene_audio / verify_publish / verify_audit
复跑全绿（双轨期纪律）。**P5-3 收口。**

## P5-4 scene_audio 场景课 TTS 叶子（④成片·语音线第一段）

### 实现（packages/core/src/scene_audio.ts；CLI 叶子 scene/tts）

- 全量移植 scene_audio.py：`buildLocaleTimeline`（逐行合成 → enrichLines →
  timeline，不落盘便于测试）、`runScene`（台账增量 + 落盘 + line-XX.mp3 副本）、
  `mainTts`（--scene 必填缺 → 2；**本模块自捕 FeuilleError** → stderr + 1，
  与 Python main 的 try/except 同构）、`pickCast`（§0.4 roles 声明驱动：
  role → energy → 班底唯一人，解不出显式报错不静默回落）、`moodOffset`
  （moodVoices 缺省 ±0 不猜）、`effectiveDurOf`（实测时长，不用 1e9 哨兵——
  空 words/伪词行哨兵直灌 enrich 会炸 tail_silence≈-1e9）、`sceneMdSha16`、
  `timelineName`（doctor ④ 探针与落盘同一条格式串，lesson.ts P5-5 复用）。
- 选角不看名字只看 energy：A 声明 steady 就配沉稳声线（曾经收了名字不看，
  A=steady 的合法课会被静默换声线——这条纪律原样保留并有测试钉住）。
- 产物线注册：modules = tts 拆分后的全部五个文件（synth/pure/client/drm/split）
  + timeline.ts + audio.ts——Python 单文件 tts.py 的对应物；data =
  @lessons/*/scene.md + personas/personas.json 不变。
- **双态口径**：内存 = TS camelCase（TimelineLine 的 speechDur/…，timeline.ts
  P3 既定约定）；落盘 = Python 同款 snake_case 键序（i→speaker→mood→text→key→
  words→dur→speech_dur→file_dur→tail_silence→start；顶层 locale→lines→gap→
  totalDur→spanDur），经 parse_scene.pyJsonDump 写出——doctor ④ / compose 线
  消费的是落盘形态，迁移期与 Python 产物互读。
- 性能修复传导：synthCached 返回的实测时长以 durs 表传给 enrichLines——
  全缓存命中零 ffprobe（P3 的设计内置修复，在第一条产线上真正生效）。

### 测试（packages/core/test/scene_audio.test.ts，12 用例；verify_scene_audio.py
### 14 断言全数对应 + 离线端到端）

- 好数据放行：ru 选角 A=lively→misha、B=steady→anya；roles 换能量
  （A=steady→anya）证声明驱动；LINE_GAP=0.35。
- 反向：班底双活泼 → FeuilleError；说话人 'C' 不在 roles → 报错名单按
  Python sorted-list 口径印；moodVoices 无该 mood → ±0、声明生效；
  空 words 行 dur 回落实测 ≈3s（不是 1e9 哨兵）。
- 台账：产物缺失判过期（不钉 why 措辞——Python verify 同款只断 not ok；
  账本无条目时先命中「首建」判据）；漏传 extra 按条目里那份复算 → fresh；
  sha 变则指纹变。真实 root 布局夹具（lessons/<id>/scene.md + personas/）。
- 叶子可达 + 格式串源码机检（scene-${sid}_${lc}.timeline.json 与
  build/scene/audio 目录约定任何一边改名当场红）。
- **离线端到端**：预置内容寻址缓存（ffmpeg 真造 mp3 + 词表；键走产线同一
  取值链 pickCast→moodOffset→voiceParams→contentHash）→ runScene 全程零网络：
  落盘字节起手 = Python json.dumps(indent=1) 口径（键序逐位断言）、行 0 真词表
  裁尾 ≈0.8s / 行 1 空词表回落实测 ≈2s、start 累进、line-00/01.mp3 副本、
  台账 extra=(sid, sha, "0.35")、二跑不 --force → [SKIP]。
- mainTts：缺 --scene → 2；缺 roles 声明 → stderr + 1。

门禁：typecheck 干净；vitest 31 文件全绿（279 用例，2 skipped）×4 连续；
Python verify_lesson 13/13、verify_scene_audio 14/0、verify_tts 16/0（含真实
网络合成一次）、verify_timeline 13/0、verify_publish、verify_audit 23/23
复跑全绿（双轨期纪律）。**P5-4 收口。**

## P5-5：lesson.ts（new 开坑 + doctor 七层体检）——2026-10-18

lesson.py 全量移植（cmd_new / cmd_doctor / tier_report / baseline_hits），
CLI 接 lesson/new + lesson/doctor 两叶子。verify_lesson.py 的 §3（doctor 班底
体检接线）随之落 vitest（§1/§2 已在 scene_schema.test.ts，本批补齐最后一块）。

### 移植要点

- **事实源现取**：registries() = scene_draft.registries()（同一份集合运算依据，
  不另抄）+ scenes（SCENES 键）+ shapes（draw_device 分支口径）。langs 直接
  复用 scene_draft.langs——两边错误文案逐字相同，复用即忠实。
- **argparse 口径**：位置参数 + 带值旗标跳值（positional）、重复旗标后者覆盖
  （argValue lastIndexOf）、int/choices 坏值 → 退出码 2；FeuilleError 照旧上抛
  （统一入口 → 1）。
- **_pad 显示宽度**：east_asian_width W/F 类按码点区间镜像（CJK/假名/谚文/全角/
  表情记 2 格）——标签字符集内与 Python 对齐；测试按**显示列**断言而非 UTF-16
  下标（下标口径下「班底体检」永远比「brief.json」少 4，那测的是编码不是排版）。
- **freshness 深比较 pyEq**：键序无关递归 + 45 与 PyFloat(45.0) 互等
  （valueOf 解包）——parse 出的 durationBudget 是 PyFloat，落库 JSON 回读是 45，
  Python `==` 为 True，pyEq 不同口径则每课都误报「不新鲜」。
- **班底体检走原始清单**（personasDoc 而非 {id} 索引——索引静默折叠重复 id）；
  try/else 口径：读得走班底才做体检，读不了只报读不了。
- **baselineHits 应命中数口径**：表空/缺表 → (0,0) = SKIP（「还没渲」≠「漏了
  基线」）；表在但没这门课 → 0/N。基线路径经 framehash.baselinePath 按平台分桶。
- **显示代码不让命令失败**：shown 路径——Node relative 不抛，以「跑出根外」
  判定回落，与 Python relative_to ValueError 回落同义。
- **--strict 结构性观察**：qa_scene 未接入前，⑦验收场景线在有 mp4 后恒 TODO
  （硬层）——strict→0 结构上不可达，Python 同构；测试按此如实断言（strict→1
  由 ④/⑦ 硬层 pending 判定，⑤/⑥ OPTIONAL 过滤不误伤）。
- 按原样镜像，不「顺手修正」：tier ① 的 `brief.get('lines')` 缺键 → 印 "None"；
  style 集合缺键 → set 里是 None（repr {None}）；"  " 作为 --tokens 在 Python
  也是 truthy → 走「--tokens 是空的」而非「要教什么词」。

### 测试（packages/core/test/lesson.test.ts，18 用例；verify_lesson.py §3 对应）
### + cli.test.ts 路由端到端 1 条

- **§3 对应（判据与 Python verify 同款）**：坏班底（id 重复，原始清单）→ FAIL
  且 detail 含「重复」；好班底（feuille 缺省 28 人）→ OK。
- cmd_new：键序 = 落库序逐键断言、rounds=3 → 11 行、tokens 两型、scenes 写进
  devices、--tokens-file、拒覆盖/--force、id/旗标错误各打一枪、用法错 → 2。
- tierReport：只有 brief 的新课分层状态（⑤ 整层无行）；真实课件 freshness
  OK → 改 json → FAIL（漂移可见）；④ 逐项 TODO、基线 SKIP。
- baselineHits、printReport 显示列对齐、cmd_doctor 退出码（空清单 0 / 指错课 1 /
  strict 1）、--json 键序与 tier 序、--all iterdir 排序。

门禁：typecheck 干净；vitest 32 文件全绿（298 用例，2 skipped）×4 连续；
Python verify_lesson 13/13、verify_scene_audio 14/0、verify_tts 16/0、
verify_timeline 13/0、verify_publish、verify_audit 23/23 复跑全绿（双轨期纪律）。
**P5-5 收口。**

## P5-6：publish 族（Playwright TS 原生）——2026-10-18

publish/ 八文件全量移植为 `@feuille/publish`（base / login / douyin / xhs /
bilibili / collections / veriflive + index barrel），CLI 接 publish/login、
publish/douyin、publish/xhs、publish/bilibili 四叶子。verify_publish.py 的
vitest 对应 = packages/publish/test/publish.test.ts。

### 设计决定（Playwright TS 原生的移植面）

- **lazy 契约（使用契约第 1 条）**：playwright 不进静态依赖——包内一律函数内
  `await import('playwright')`，环境缺它时 `import '@feuille/publish'` 也不炸
  （真跑发布报「缺 playwright」）。类型面用 ambient `declare module 'playwright'`
  （playwright.d.ts），page/ctx 使用点 any——不加包名依赖也能 typecheck。
- **Python SystemExit → FeuilleError**（stderr + 退出码 1 口径不变）；
  argparse 语义 → manifestArgs 手写解析：缺参/坏 int → usage 到 stderr +
  {rc:2}；-h → stdout + {rc:0}。
- **API 差异逐点补齐**（按原样镜像，不「顺手改」）：Python is_visible(timeout=N)
  会等 → visibleWithin（waitFor）；JS Locator.boundingBox() 无 timeout 参数
  → 先 waitFor 再 boundingBox；Python page.evaluate(expr, locator) 传参 →
  JS 对应 jsClick（locator.evaluate）；evaluate 内嵌 JS 的 `\\s` 双写转义；
  Python str 切片按码点 → clip()；repr/list/tuple 排版 → pyRepr/pyList/
  pyReprList（报错文案逐字对齐）；argparse int 显式挡 Number('')===0。
- **clock.ts seam**：sleep/now 独立小模块——门禁用 vi.mock 整模块记录
  ['sleep', d] 事件（d<0.5 委托真睡），缺陷①的循环内节流事件序列断言不动
  业务签名（Python 侧 monkeypatch time.sleep 的对应物）。
- **launch 回调形态**：Python contextmanager with 块 → launch(profileDir,
  opts, fn(ctx,page))，finally 里 ctx.close()（cookie 落盘语义保留）。
- **CLI 叶子接线形态**：Python cli.py 的 `fn(argv) if argv else fn()` 原样
  镜像——publish login 的 --status 怪癖（argv 非空才传 names，'--status'
  会被当平台名报未知平台）保留为已知行为，要改另立议题。

### 与 Python 侧的刻意差异（改进，非放松）

- **run_tasks 门禁行离线跑**：stub page（screenshot 写真文件、goto 空操作）
  驱动，不再像 Python 侧那样被「playwright 是否安装」门控——runTasks 骨架
  本身不碰浏览器内部。断言逐条不变（事件序列 / 异常隔离 / result JSON /
  pre-post-crash 截图）。
- **playwright 门控行**：describe.skipIf(!hasPw)（hasPw = 动态 import 探测），
  本机未装 → 整块 SKIP，镜像 verify_publish.py 的 SKIP 行；装上自动补齐
  mock-A/B/C（真 Chrome + file:// 本地页，零平台流量）全部断言。
- **静态依赖源码面断言**：TS 侧无 sys.modules 注入手段，lazy 契约由
  「in-process import 全通」+「源码零静态 playwright import 正则」两行合证。
- **证据**：build/publish-verify/（mock-*.html / mock-events.json /
  mock-result.json；有 playwright 时另有 mock-*.png）。

### 测试（packages/publish/test/publish.test.ts，11 用例；verify_publish.py 对应）

- 第 0 条好数据放行：resolveChrome 真实文件、与 platform.browser('chrome')
  同源、FEUILLE_BROWSER 坏路径 → FeuilleError。
- lazy 契约：index 七命名空间 + filterTasks 纯函数全不炸；源码零写死
  .exe/.app 路径（verify_platform ALLOWED 口径）+ 零静态 playwright 依赖。
- 词表反向复现：v1 词表（缺「投递」）对「稿件投递成功」全不命中；
  BILI_SUCCESS_WORDS 含全词。
- filterTasks：only='2,4'→[2,4] / frm=3→[3,4,5] / 不过滤全量 / only='9'
  → FeuilleError（纪律 12）。
- run_tasks 缺陷①：事件序列逐条断言 [pub,1]→[sleep,0.15]→[pub,2]→…→[pub,4]
  （节流在循环内）、第 2 条 RuntimeError 只记「异常 RuntimeError」、
  mock-result.json 落盘回读、crash-02 + pre/post-NN 截图齐全、证据副本。
- gated（skipIf）：findPublishButton 四诱饵全躲开（#real-publish）/ 隐藏后
  不退回诱饵；login_wall 只认可见文本 + login.probe 三通道两态；
  wait_success B 站全词命中 / 小红书超时 False / risk_hit 真假两态。
- 导入冒烟：collections / veriflive import 成功即断言（Python 侧同款）。

门禁：typecheck 干净；vitest 34 文件全绿（308 用例，3 skipped——gated 块
随 playwright 缺席 SKIP，与 Python 侧口径一致）×4 连续；Python
verify_publish 12/12 复跑全绿（双轨期纪律）。**P5-6 收口。**

## P5-7a：match_theme 升包（@feuille/core/themes + `feuille theme match`）——2026-10-18

P5-7 归流第一子批：`skills/match_theme.py`（169 行，skills 根下的孤立脚本）
升包为 @feuille/core 第 31 个库模块 `themes`。它被 one-page-poster 与
karaoke-video 两个 skill 的 SKILL.md 同列引用——按 ownership 三层模型
这是典型的 library 归属（≥2 skill 用的业务实现），升包后 skills/ 里只留
对包的调用（SKILL.md 资源行改指 `feuille theme match`）。

### 归流决定与移植要点

- **唯一实现**：THEMES / KEYWORDS_RULES / matchTheme / describeThemes 全量
  进包，零重复。匹配优先级原样镜像：显式指定 > 语言强约束（ar/he/fa/ur
  **前缀**命中 → desert-sand）> 关键词评分（`score > maxScore` 严格大于才
  换人 → 同分先列者胜，规则表顺序即优先级）> 零命中兜底（非 zh 外语 →
  clean-paper；中文话题带课/讲/学字样 → clean-paper；否则 warm-paper 基线）。
- **query 口径**：`topic + " " + lang` 全小写；兜底分支里 `lang.startsWith('zh')`
  用**原参**不落小写——Python 侧同款（第 3 步的 lang 是函数入参，不是
  query），逐行镜像。
- **CLI 对应形态**：Python `__main__` 的 argparse 口径进 `themes.main(argv)`：
  `-h` → usage stdout + 0；未知旗标 / `--lang` 缺值 / 第二个位置参数
  （argparse unrecognized）→ usage stderr + 2；`--lang=x` 带值形态收；
  重复旗标后者覆盖（argparse 同款）。`--list` 或无 topic → 列 5 套主题，
  输出逐行镜像（含 Python print 尾随 `\n` 的视觉空行——按调用串形态断言）。
- **接线**：cli 路由表新增 `theme/match` 叶子（薄适配层，残余 argv 原样
  交接）；SKILL.md 两处资源行改指包调用；skills/match_theme.py 删除
  （skills/ 只留资产 + 对包的调用）。

### 测试（packages/core/test/themes.test.ts，14 用例 + cli.test.ts 路由 1 条）

- 匹配优先级：显式合法/非法、语言强约束前缀族（ar/ar-SA/he/fa/ur，zh 反例）、
  关键词四主题各一例、语种名携带关键词进评分、同分先列者胜、零命中外语/
  中文兜底三分支、空参默认。
- describeThemes：5 套齐全、`THEMES[k] === t` 键值自洽、双色号格式。
- main：--list/无 topic 输出行形态、话题匹配四行逐字断言、-h/0、
  未知旗标/--lang 缺值/双位置参数 → 2、--lang= 带值合法、--list 覆盖话题。
- cli.test.ts：`feuille theme match` 经路由端到端 0/0/2 三态。

门禁：typecheck 干净；vitest 34 文件全绿（323 用例，3 skipped）——首轮
1 例瞬时失败后连续 9 轮全绿（失败日志已失，未能定位；新增两文件均为
纯函数断言无时序依赖，疑为既有套件在冷启动负载下的一次性时序抖动，
如实记录，后续轮次若复现再行定位）；Python verify_skills 78/78 复跑
全绿（SKILL.md 改行 + skills/ 删文件后边界机检不破）。**P5-7a 收口。**

## P5-7b：karaoke-video 四脚本归流（@feuille/karaoke + `feuille karaoke …`）——2026-10-18

### 归流决定与移植要点

- **新包 @feuille/karaoke**（karaoke-video 的产线编排专属，消费 core 唯一实现，
  不带第二份）：`gen_tts` / `build_video` / `verify_sync` / `scan_blank` 四模块
  + barrel。cli 新增 `karaoke/tts|build|verify-sync|scan-blank` 四条薄叶子路由。
- **edge-tts 协议归流**：core tts client 的裸 `stream()` 从私有改导出——
  gen_tts 原版就是直接吃 `edge_tts.Communicate.stream()` 的音频块 +
  WordBoundary 事件，**没有** synthOnce 的无词兜底（那是行合成语义，不是
  karaoke 语义）；原版无缓存，照原样不引入（poetry 侧的平行缓存是另一族）。
- **gen_tts**：`tokenTimings` 纯函数逐行镜像——码点数组、连续区间 assert
  （`pos !== stream.length` 直接炸）、`into = wl - cov`（本界内已消费字符，
  **不是**流内前缀——ja 嵌套界 一杯/いっぱい 里 杯 start = 0.38+0.46×(1/4)，
  测试初稿曾按 3/6 算错，以算法口径为准）、空格跳过、`next()` StopIteration
  炸点保留。CLI 无 argparse（原版裸吃 sys.argv[1]/[2]）：无 `-h`；缺 cfg
  在 Python 是 IndexError 裸炸，叶子统一口径报 usage + 2；outDir 缺省
  **相对 CWD**（Python pathlib 相对路径同款，不相对 cfg 所在目录）。
- **build_video**：30fps 网格（`d30 = ceil(d*30-1e-9)/30`）+ 逐段**精确帧数**
  编码再 concat（av-sync 漂移修复原样保留）；Chrome 截图参数与 textlayer
  shotArgs 同源口径（`--headless=new` 不带 `--user-data-dir`，铁律）；**白页
  哨兵同步 await**（初稿 fire-and-forget 不会中断产线，已改为 async 全链）；
  ffmpeg/ffprobe **函数内懒解析**（模块级 throw 会破坏 barrel 导入，更晚一步
  报的代价是包可安全 import）；`video_build.html` 落盘但状态帧截图走**原始
  cfg.src**（原版如此，要改另立议题）；bgm 分支 amix normalize=0 语义照旧。
- **verify_sync**：`ImageChops.difference(...).histogram()[12:]` 的 Python
  口径 = **|diff| ≥ 12 的像素计数**（≤11 编码噪声不计），sharp 灰度 raw
  循环镜像；探点 pre=s+0.4（写死）、word0=s+preroll+s0/2（s0 取下一 token
  start 差，单 token 取 d−preroll−done）、done=s+d−done/2；场景起点由各
  seg wav 时长累加（probeDuration）。失配 → FeuilleError `SYNC FAILURES` → 1。
- **scan_blank**：`fps=N` 采样进 mkdtemp（**不清理——原样镜像 wart**）；
  白帧判定 160×90 min(R,G,B)≥250；`bad[:6]` 按 Python tuple-repr 风格打印；
  含白帧 → 1。
- **tsconfig 坑**：`Record<string, number>` 下标访问在 noUncheckedIndexedAccess
  下是 `T|undefined`——tokens 一律 `Array<{start: number}>`；Node spawnSync
  捕获输出用 `{encoding:'utf8'}`（`captureOutput` 是 Bun 的 API，不存在于 Node）。
- **接线**：SKILL.md 产线五步 + Resources 改指 `feuille karaoke …`（promoted
  from 四个 .py）；Requirements 弃 Python 改 Node/pnpm 口径；references/
  av-sync.md、delivery-check.md、storyteller SKILL.md 产线图、usine/AGENTS.md
  白页哨兵行同步改指；skills/karaoke-video/scripts/*.py 四文件删除
  （skills/ 只留资产 + 对包的调用）。ownership.json 不动——它此刻的机检对象
  仍是 src/feuille 的 .py（双轨期），TS 包记账是 P7 清场的事。

### 测试（packages/karaoke/test/karaoke.test.ts，15 用例 + cli.test.ts 路由 1 条）

- tokenTimings：zh「一本」跨界按字符份额切分、单 token 空格跳过、部分覆盖
  → null（含 0.1+0.2 IEEE 尾数断言）、ja 嵌套界全 4 token 数值断言
  （含 杯 into=1/4 口径与 0.38+0.46 尾数）。
- gen_tts：**真 edge-tts 一轮**（zh-CN Xiaoxiao；免费服务不在额度红线内，
  verify_tts 同款先例）——mp3 落盘 + JSON 键序 = Python dict 插入序 +
  逐 token 打印行；缺 voices.json → usage + 2。显式传绝对 outDir（原版缺省
  相对 CWD，首轮测试真往 usine/out 拉了屎——已清掉并显式传参）。
- build_video：d30 网格四格、缺 video.json → 2；**端到端最小产线闭环**
  （真 Chrome 状态帧 + libmp3lame 静音 mp3 + 双画幅段编码 concat → 成片，
  verify-sync 对成品回 0；video_build.html 落盘但截图走原始 src 的原样
  镜像 quirk 一并断言）。测试 fixture 需带 `/*__FONTS__*/` 标记（替换契约）。
- verify_sync：diffGray 12 阈值两侧、缺必填/坏 int → 2、端到端两态
  （同色 → 0；异色 → SYNC FAILURES 抛出）。输出行的 padEnd 间距
  （loc.padEnd(8) + 显式空格 + label.padEnd(6)）按 f"{loc:8s} {label:6s}" 镜像。
- scan_blank：whiteRatio 三色、真 ffmpeg 采样两态（2s 白片 →
  [('f001.png', 1), ('f002.png', 1)]）、main 多态（-h/0、无视频/坏值 → 2、
  白片 → 1、干净片 → 0）。
- cli.test.ts：四叶子经路由缺参可达 → 2（0 态留给真产线行）。

门禁：typecheck 干净；vitest 36 文件全绿（342 用例，3 skipped）。本轮曾现
**一次**未定位的整 suite 瞬时失败（1 例，失败日志当时未捕获即被后一轮覆盖；
唯一依赖网络的是 edge-tts 真连行，疑点最大），其后连续 4+4 轮全绿（含
cli.test.ts 加行后重跑的最后一轮 4 连绿）；Python verify_skills 78/78 复跑
全绿（SKILL.md 改行 + 四 .py 删除后边界机检不破——ownership 机检对象仍是
src/feuille，skill 脚本不在其扫描面，双轨期不受影响）。**P5-7b 收口。**

## P5-7c（2026-10-18）：poetry/publishing 脚本归流——@feuille/poetry 立包 + check_plan 入 @feuille/publish

**归流决定**：poetry 线两个诊断脚本立新包 **@feuille/poetry**（audio_profile /
color_contrast 各一模块 + barrel）；publishing 线的 check_plan 进已存在的
**@feuille/publish**（它本来就是发布域的包，不再另立）。三个 CLI 叶子
（poetry/audio-profile、poetry/color-contrast、publish/check-plan）走既有
thin-leaf 模式；commands.ts 路由加三行。

- **audio_profile**：ffmpeg volumedetect / loudnorm / astats 三口径解析
  （spawnSync；`_bin` 平行缓存不迁——platform.ffmpeg() 在函数内懒解析，
  P5-7a 同款归流）。stdin 只在 `!process.stdin.isTTY` 时读（readFileSync(0)
  try/catch→''）；窗口 JSON 从 argv join 取（`--rms` 旗标滤除），argv 不给再
  退 stdin。f-string 镜像：toFixed + padStart；`int()` → Math.trunc；
  astats 的 `-inf` 就地归一 -99。**`in_windows` Python 版定义了但 main 未
  引用——按原样镜像移植，不擅自删**（纪律：镜像优先，删除另立议题）。
- **color_contrast**：numpy percentile → 线性插值 `rank=(n-1)*p/100`；PIL
  LANCZOS → sharp lanczos3；colorsys rgb_to_hls/hls_to_rgb 镜像；Python
  round() 银行家舍入 → pyRound 助手；`%g` → pyG。glyph_mask 色相向量化
  分支优先级 r>g>b 原样；dilate 4 邻域迭代；argparse 用 token-walker 仿真
  （旗标值不漏进位置参数）。
- **⚠️ sharp raw 通道大坑（生产 bug，实测抓到）**：`ensureAlpha().removeAlpha()
  .raw()` 的 ensure/remove 对被优化掉，raw 返回 **4 通道** RGBA——按 3 通道
  步长读会混进 alpha 字节，亮度全错（0.161 vs 正确 0.0212）且红色卡片出现
  幻灵绿色字形命中。修法：`toBuffer({resolveWithObject:true})` 后按
  `info.channels` 做步长抽取重组 3 通道缓冲。已写进实现处注释。
- **seasonColorsFromArchive**：TS 无法 import Python——季色默认值改为**解析
  归档字面量**（assets/example/季节与译文.py 的 SEASON_COLOR dict，正则 +
  逐条 matchAll），候选目录序与 Python sys.path 插入序一致（归档副本优先，
  examples/sijijie 本机退路）。机制变了，事实源没变（归档字面量原样）。
- **check_plan 入 @feuille/publish + 限值漂移拷贝消解**：Python 版 TITLE_MAX
  是带 `_limit_drift` 守卫的独立副本（纪律 10），前提是「发布机零依赖可跑」
  ——TS 单仓后该前提已死，直接消费 `manifest.PLATFORMS` 派生
  （`Object.fromEntries`），**漂移拷贝不迁移即天然消除**，守卫检查 #6 随之
  退役（TITLE_MAX 导出仅为反向验证派生关系）。COVER_RATIO / MOD_BUDGET 是
  check_plan 私有事实（无 library 同源），留本地。PIL Image.size → sharp
  metadata；Python len() → charLen 码点计数；set repr → setRepr 镜像
  （`{'ja-JP'}` 带空格）。**横竖配对通过行只判条数相等、不判集合一致
  （集合不一致由 problems 拦）——Python 原版口径，镜像并加测试锚定**。

### 测试（poetry.test.ts 17 用例 + check_plan.test.ts 11 用例 + cli.test.ts 路由行）

- poetry：gap_verdict 两行（**verify_skill_scripts.py 的 color_contrast 段随
  归流移植**，该段已从 Python 验证脚本移除并在 docstring 记去向）；percentile
  插值、hex/lum/WCAG（白上黑 21）、hls 往返、suggest 四档递减、glyph_mask
  红中灰不中、dilate 5→9、seasonColorsFromArchive 四季全值、measure 端到端
  （sharp 真成像，gl 对 lumHex('#FF0000') 精度 3）、seasons 端到端（真 ffmpeg
  抽帧 + 卡片合成，--gate 双阈值两态）、gate 未量到不许混过（SKIP≠PASS）、
  argparse 多态、audio curve/meanVolume/lufs/窗口模式/--rms、__doc__ 与
  找不到行。
- check_plan：TITLE_MAX 派生关系逐平台逐项 + 取值；charLen emoji=1；六项判据
  逐条（清单齐/素材缺失/标题超限/语种集合多缺两侧/封面比例提醒/封面读不出）；
  **配对通过行的 Python quirk 加伴生用例**（条数相等而集合不一致 → ✅ 照发）；
  --root 两级解析；argparse 行。
- **curve 双轨 parity 实证**：TS c[0.1]=-27.095662 与 Python 逐字节一致
  （astats 逐点值与 volumedetect 不一致是 astats 本性，脚本 docstring 自证
  只看趋势——测试阈值按 Python 实测留余量，不按直觉拍）。

门禁：typecheck 干净；vitest 38 文件全绿（372 用例，3 skipped）**4 连绿**
（本轮再遇两例瞬时失败：一次未定位单例、一次为 Edge 渲字 + edge-tts 真连
两行在并行满载下同轮抖动，单文件复跑全绿，均与 P5-7c 改动无交集——Edge
类行在并行下的抖动已是第二次出现，P7 移植 verify 时值得单独审视隔离策略）；
Python verify_skill_scripts.py 14/14（color_contrast 段移除后）、verify_skills
78/78 复跑全绿。接线面：poetry SKILL.md（验收判据/混音排查/先量后看/代码
归属段）+ references/{audio-measurement,ffmpeg-pitfalls,typography-over-footage}
+ publishing SKILL.md + publish-copy SKILL.md + bgm-bed/references/
lyria-field-notes.md 全部改指 `feuille poetry …` / `feuille publish
check-plan`；三个 .py 删除（scripts/ 目录随之清空移除）。ownership.json
不动——机检对象仍是 src/feuille（双轨期），TS 包记账 P7 清场。**P5-7c 收口。**

## P5-7d：storyteller-video 归流（@feuille/storyteller 新包）

新包 **@feuille/storyteller**（packages/storyteller/）：`render_act_frames`
（幕帧渲染）+ `assemble_storyteller`（成片组装）——skills/storyteller-video
两脚本的唯一实现归流，CLI 走 `feuille storyteller render-frames` / `assemble`
两路由。包消费 @feuille/core 唯一实现（rig.drawCharacter / poseFor /
POSE_CODES / SCENE / mix / hexc、scenes.prerenderBg / DrawScaled、
data.storytellers、audio.probeDuration、platform、roundHalfEven——Python
round() 银行家舍入不自造第二份），包内零重复；ffmpeg 只剩醒木合成与合片
编排。错误信息里的 TTS 前置指引随归流改指 `feuille karaoke tts`
（原指 karaoke-video 的 gen_tts.py——命令名变了，所指没变）。

**接线 storyteller 时抓出的两个 core 真 bug（本批最有价值的产出）**：

- **prerenderBg RGB→RGBA 错位**：3 通道 raw 直接 `data.set(up)` 铺进 RGBA
  ImageData，字节流错位（颜色垃圾 + 尾部 1/4 全透明）。P4 冒烟只验尺寸/
  幂等没采样像素，storyteller 以 bg 为合成底才炸出来。修复：按步长散布 +
  alpha=255，补渐变像素回归测试（scenes.test 顶部/中部/底部三点取样）。
- **pildraw eraseThen 的 erase pass 被闭包里的 fillStyle 覆盖**：RGBA 替换
  语义的 erase（destination-out）pass 里 paint 闭包先执行 `fillStyle =
  rgba(0,0,0,26/255)` 再填，destination-out 只吃源 alpha → 只抠掉 10%
  （实测 alpha 232 而非 0）。重构 paint 闭包带 erase 参：erase pass 一律
  不透明 #000。接触影测试（案沿上画 (0,0,0,26) → 像素恰为 (0,0,0,26)）
  是替换语义的像素级直证。

**core 接口补面**（storyteller 包要吃，属包间 API 完成而非行为变更）：
pildraw 从 imaging/index 显式再导出（createPilDraw + PilDraw/DrawOpts/
RGBA/Box/Pt 类型——与 draw.ts 的 RGB 同形异名，star 混出会歧义，按名出）；
scenes.DrawScaled 的 opts 类型从内联 `{fill?: RGB…}` 统一放宽到 DrawOpts
（4 元组 fill/outline 随 pildraw 语义过代理）。

**实现口径**（与 Python 版逐点对齐）：GEO/ACTOR/色表常量同值；演员层 PIL
BOX 2× 下采 = 直写 2×2 均值（sharp 无 box 核）；back/front LANCZOS→lanczos3；
Image.blend 转场 = sharp raw + JS 混合（栅格化差异按「比结构与几何」纪律）；
幕段编码 image2 序列输入不用 concat demuxer（DTS 事故注释照搬）；n_in 输入
计数器、gavel 缺省真而显式 null 为 falsy（Python get 语义，不用 ??）、
act.pose 显式 null → 无姿态（falsy 链，不用 ??）都按原样镜像。

### 测试（storyteller.test.ts 19 用例）

shotTransform 六态（含 s<1 端点镜像、nFrames=1）；gavel ≈0.25s；
buildCardHtml GEO 注入/token/pun/vow span/data-n/quote 两态/转义/状态契约
脚本；matteUnpremultiply 八像素（精确色 255、纯黑 0、近色 255−√88 截断）；
舞台像素（接触影替换直证 + 顶梁/匾板 mix 公式 ±1）；render e2e 真 Edge
4 张状态卡 + 9 帧全链路 + **幂等重渲逐字节一致** + 缺 TTS 产物 / --act 未知
幕反向验证（错误信息断言含「先跑 feuille karaoke tts」）；assemble e2e
合成帧 32×64 两幕 + 转场 2 帧 + gavel 混音 → 24 帧 @5fps 成片（时长 4.8s
±0.3 + aac 音轨在场）；barrel 导出面。

门禁：typecheck 干净；vitest **39 文件全绿（392 用例，3 skipped）4 连绿**
（本轮另有两轮各现 1 例瞬时失败、复跑即绿——Edge/网络行在并行满载下的
抖动已是第三次，与前两批同模式，P7 移植 verify 时一并审视隔离策略）；
Python verify_skill_scripts.py 14/14、verify_skills.py 78/78 复跑全绿
（storyteller 两脚本原不在其清单内，无需改判据）。接线面：storyteller
SKILL.md（边界/舞台合成/管线/代码归属段改指 `feuille storyteller …` +
`feuille karaoke …`）；两个 .py 删除（scripts/ 目录随之清空移除）。
ownership.json 不动——机检对象仍是 src/feuille（双轨期），TS 包记账
P7 清场。**P5-7d 收口。**

## P5-7e：one-page-poster 归流（@feuille/poster 新包）

新包 **@feuille/poster**（packages/poster/，10 产线模块 + pixels 通道层 +
barrel）：`fetch_fonts`（Google Fonts css2 免费子集端点 → 内嵌 fonts.css）、
`assemble`（@import 合并内嵌 + --theme token 注入）、`render_poster`
（原 .sh：全新临时 --user-data-dir 隔离 + GNU timeout 兜底 + 退出码透传）、
`render_page`（dump/render 双模式，(24,93) 窗框开销补偿）、`audit_charset`
（栈式家族归属 tofu 门 + .ksyl 补丁规则绑定门）、`fit_diag`、`verify_colors`、
`check_overlay`、`make_covers`、`measure_korean`——本 skill 原十条 scripts/
脚本的唯一实现归流，CLI 走 `feuille poster <子命令>` 十路由，@feuille/poster
入 cli deps。包消费 @feuille/core 唯一实现（platform.browserPath /
FeuilleError / roundHalfEven——Python round() 银行家舍入），浏览器解析零写死。

**Python 地基校准抓出的两个真移植 bug（本批最有价值的产出）**：韩文音节
UAX34 转写表 `L_PART` 缺 ㅈ→'J'（18 项抄漏 1 项，차→'KA'、한→'undefinedAN'）、
`T_PART[8]` 单ㄹ终声应为 'L' 非 'R'（初声位 ㄹ 才是 R，떨→DDEOR 错）。
先写 Python ground-truth 测试再跑门禁的顺序把两个都拦在了门禁前；修复后对
**全部 399 个无终声音节 + 全部 28 个终声变体**与 Python unicodedata 逐名
diff，全对齐。其余实现口径按原样镜像：`np.roll` 环绕移位（check_overlay
非零位移天然压分）、dilate 是方形（Chebyshev）不是十字形、erode 越界记
非障碍（numpy-clamp 镜像，边条幸存）、PIL L 灰度公式、html.unescape 部分
实体表（只覆盖 Python 原表命中的实体——宁可漏转不可错转，方向与原版一致）。

### 测试（poster.test.ts 34 + measure_korean.test.ts 26）

- poster：fetch_fonts 单元 + 真网 e2e；assemble 标记全量替换（'FONTCSS'
  两处）/无标记直通/--theme 注入（**assemble 读 process.cwd()——vitest 线程
  池共享 worker 进程，进程内 chdir 会与并行文件竞态**：spawnSync 子进程 +
  绝对 tsx loader URL + eval-import **叶子模块**直跑；CLI 入口的 ESM 入口
  判定在 tsx 下永不触发，import 入口静默 rc=0 是坑）；make_covers OVERRIDES/
  BOOT 前注 + src 不动；fit_diag OK/OVERFLOW/UNLOADED FONT 三态；
  audit_charset §4 三行 verbatim 移植（叠印层 ा 删出子集 → MISSING、族外
  Ω 弹栈不误归）+ 补丁规则绑定门五凿洞（穿错规则/无规则/孤儿逗号形/多
  字素/`<img>` void 不推栈）；verify_colors 网格检测四色抽样（sharp SVG
  夹具）；check_overlay 配准/失准（**夹具教训：墨块必须紧凑**——整列墨在
  np.roll 环绕 + 平手取更小 dx/dy 决胜规则下竖直位移简并，dy 平手落到
  -radius；算法是 Python 原语义的忠实镜像，夹具错了几何）；render e2e
  真 Edge（query 后缀透传到 JS / dump-dom / (24,93) 裁齐精确尺寸）；
  barrel 十模块导出面。
- measure_korean：音节名 19 样本 ground truth（对过 Python）/CLUSTER_FINALS
  11 项/jamoDeomp/掩膜代数（closing ⊇ red、方形 dilate、全真 erode）/
  labelComponents/largestRect/rectCover/expandRects（蓝墙夹扩边）/dedupeRects/
  coverVowel 三响亮失败（overlap / cap 内盖不满 / 会漆红辅墨——
  **not-coverable 夹具的蓝竖条纹墙是三次迭代才凿出来的**：closing 是闭包、
  无墙时扩边沿自由行铺满全幅反而盖得全）/classify 五态/emitRule 精确四行/
  e2e 全链（真网 fetch_fonts → measure → verify PASS + .kCC28 规则名）。

门禁：typecheck 干净；vitest **41 文件全绿（452 用例，3 skipped）4 连绿**。
本轮 Edge 并行抖动第 4 次出现且首见**连续复跑不绿**（covers demo_xiaohongshu
+ textlayer 阿拉伯 RTL 在 5s 默认超时下被新增的 poster 浏览器 e2e 挤兑
挤爆）——rig/scenes 同款显式 120s 超时补上（covers Edge 渲字 4 it + 
textlayer 真机 3 it），不改判据只放宽限时；**P7 移植 verify 时隔离策略必须
一并落地**（四批三现，这批转持续）。Python 侧
verify_skill_scripts.py §4 strike（audit_charset 三行移植 poster.test.ts，
14/14 → **11/11**）、verify_skills.py 78/78 复跑全绿。接线面：one-page-poster
SKILL.md（Requirements uv→node/pnpm、工作流 3–7 步、Conventions、代码归属
「已归流 @feuille/poster 包」、Resources）、references/script-coloring.md
八处、skills/README.md 两处、karaoke-video SKILL.md 两处（上游 fetch_fonts
改指）、模板头注释与 DIAG 行——assets/example/ 归档按只读豁免不动
（verify_skills 的既有纪律）；十个脚本 git rm（9 .py + render_poster.sh），
scripts/ 目录随之清空移除。examples/ 归档项目目录全程未碰。
ownership.json 不动——机检对象仍是 src/feuille（双轨期），TS 包记账
P7 清场。**P5-7e 收口。**

## P5-7f：publish-copy / bgm-bed 归流（@feuille/copy + @feuille/bgm 新包）

新包两枚：**@feuille/copy**（check_publish_copy.py 唯一实现）与 **@feuille/bgm**
（gen_bgm.py 唯一实现，含自写 FFT）。CLI 加 `copy/check` + `bgm/gen` 两路由
（packages/cli/src/commands.ts），薄叶 leaves/copy-check.ts + bgm-gen.ts
（poster 三行叶同款），两包入 cli deps。ownership.json 不动——机检对象仍是
src/feuille（双轨期），TS 包记账 P7 清场。

### @feuille/copy：夹具裁决抓出一个真移植 bug

29/29 绿。**splitlines 真镜像**是本批抓出的真 bug：正则 split 会留一个尾随
''（`'a\n'.split(/…/) → ['a','']`），Python `str.splitlines()` 不留——段末行
判定（check_trailing_space 读「最后一个非空行」）在带尾随换行的文件上整条
错位。正解 = 边界正则切完 `parts.at(-1)===''` 就 pop，且 `'' → []`。夹具对
Python 源码逐行裁决还校准了三个语义：**check_trailing_space 是「要求」尾随
空格**不是禁止（Slate 联想面板吃末尾话题——publish-playbook 坑 ① 的机器门，
判反了门就变成帮倒忙）；**no-hard-wrap 的 '---' 不是结构行**（`[-*+]\s` 要求
bullet 后有空白，未闭合 frontmatter 逐行原样过——'---' 后跟正文行就是违规
[1]）；字数按**码点**不按 UTF-16（`[...s].length`）。--facts 数字溯源：正则
 `\d+(?:\.\d+)?` 逐字对表、**未给 --facts 是 SKIP 不是 PASS**（文案按原样镜像）。

### @feuille/bgm：自写 FFT + Python 格式化镜像

34 passed | 1 skipped（skip = key-missing 守卫在本机不可测：真
`~/.gemini_api_key` 在，it.skipIf 诚实让位）。**FFT 不引新依赖**：迭代 radix-2
+ Bluestein chirp-z 任意 N，平方指数 mod 2N 保精度，逆变换 swap 技
（`fftPow2(aim, are)` 后实部在 `are`）；rfftMag = numpy rfft+abs 语义
（k=0..⌊N/2⌋），对朴素 DFT N=16/21/1500 相对误差 <1e-8。bandShare hanning
/estBpm hop-512 包络自相关 /padRequest 1.15 垫量 /bedLenVerdict 全按原样
镜像，垫量两行（80→92、62→71.3）与床长判据对 Python 实跑逐位一致；
**estBpm 奇偶校准**：1 kHz 正弦 @48k hop 512 = 每 hop 10.67 周期，包络震荡
测出 187.5 BPM——Python 实跑同为 187.5（测试按此断言，不按直觉的 null）。
Python 格式化三件套：pyFloat（整数带 .0、None→'None'、±inf）、pyG（:%g
6 位有效数字）、pyFixed（%.nf 银行家舍入）——verify_rate 的
inconclusive/MISMATCH 双态文案逐字符对齐。**@google/genai v2.30.0 JS SDK
与 Python SDK 形状不同**：`apiVersion` 直挂 options（无 httpConfig）、
connect 走 callbacks（onmessage/onerror/onclose，无 receive 轮询）、
audio chunk 是 **base64 字符串**（Buffer.from(ch.data,'base64')）、
play()/close() 同步 void、setWeightedPrompts({weightedPrompts})——
oneSession/captureRealtime（3 连断重试）/captureHttp（10 min AbortSignal，
Free Tier → FeuilleError）结构移植，与 Python 侧 HTTP 备路同为未实跑路径。
key 纪律：BGM_BED_ENV → ~/.config/feuille/bgm-bed.env，env 不覆盖、引号
顺剥镜像，密钥永不进仓库；**测试零真实 API**（--list-providers 打桩、凭据
探测纯函数）。pnpm-workspace.yaml `allowBuilds`：@google/genai/protobufjs
false（纯 JS postinstall 不需要）、esbuild true——strict-dep-builds 下
模板占位文本会炸 typecheck 的内层 install，两键必须落布尔。

### verify_skill_scripts.py 退役（skill_scripts 套件归零）

两个存活段（§1 copy 指纹/溯源、§2 bgm 垫量/床长）已全量进 vitest，脚本
git rm；verify_probes.py SUITES 摘牌（21 套 → **20 套**：architecture.md
行删 + 全文 7 处措辞、README.md 2 处）；verify_docs.py DEAD_PATTERNS 加
`verify_skill_scripts.py` 条目防「复制粘贴旧手册段落」回流。poetry/poster
段（color_contrast、audit_charset）先前批次已各自归流，本批归零收尾。

### 接线面 + 死代码核销

publish-copy SKILL.md（代码归属段「已归流 @feuille/copy」、Markdown style、
尾随空格/指纹门、验收判据表头、编辑层、Workflow step 4、资源段——含两处
verify_skill_scripts 指向改 vitest）；bgm-bed SKILL.md（frontmatter、两条
出床线表、matrix 不进生成命令的三处、代码归属段「已归流 @feuille/bgm」、
怎么用 step 0/2/3、matrix 样例块 step 3 的 `python -c` 复用改
`--recheck` 一条命令（判据演进重算不加新请求）、坑 1 反向验证指向、--recheck
块、资源段）；karaoke-video SKILL.md（`uv sync --group music` 退役——
@google/genai 已随包常装）；skills/README.md（Lyria 线改指 `feuille bgm gen`）；
one-page-poster SKILL.md **`feuille platform describe` 措辞修正**——platform
是 @feuille/core 库函数、没有 CLI 路由，SKILL.md 把它写成命令是幽灵命令。
两个 .py git rm，skills/{publish-copy,bgm-bed}/scripts/ 目录随之清空移除。
assets/example/ 归档按只读豁免不动。**死代码核销（P5-7 冗余审计裁定）**：
taglist、crop_backdrop 拷贝、describe 三项为 Python 侧死代码，**不迁移**，
随 P7 清场整块消失——本行即核销记录。

门禁：typecheck 干净；vitest **43 文件全绿（515 passed | 4 skipped）4 连绿**
（复跑共 8 轮全绿）；Python 侧 verify_skills.py 78/78、verify_probes cli
8 PASS / docs 13 PASS 复跑全绿。**P5-7f 收口。**

## P6：dsh 工具面全量接线（@feuille/dsh-plugin 从骨架到全量）

插件从 P1 骨架（usine_version 单工具）扩成全量工具面，四文件成型：
`capture.ts`（进程内 main 的 console 四出口捕获 + 串行锁——main 沿 CLI 口径
打 console、退退出码，工具把两者折成结构化 {exit_code, output}；FeuilleError
按叶子层惯例折 rc 1 + 报错文本，不外抛，模型读得到）、`discipline.ts`
（systemPrompt 纪律节：红线文本只有一份，order 10150 落在 WEB_SURFACE 与
DEPLOYMENT_PERSONA_SUFFIX 之间）、`tools.ts`（全部工具）、`index.ts`
（Config.publish 门 + 注册编排）。

**17 工具 = version + 13 家族 argv 工具 + verify/quota/video-generation**。
家族工具与 CLI 路由表同覆盖面（scene/lesson/persona/cover/framehash/ledger/
theme/copy/bgm/karaoke/poetry/poster/storyteller），`action` 选子命令、`argv`
残余参数与 `feuille <组> <命令>` 完全同一套口径，进程内直调包 main（无
subprocess 桥——迁移的核心接缝证明），未知子命令 rc 2。usine_verify 走子进程
（pnpm typecheck → 全量 vitest；usineRoot() 从 bundle 位置向上找
pnpm-workspace.yaml 定位，FEUILLE_ROOT 可覆盖）；usine_quota 包 `mmx quota`
只读。**usine_video_generation 是额度红线的机制承载**：机械校验先行（Hailuo
768P 6/10s、1080P 6s；H3 4–15s 整数 + ratio 必填；H3-Max 5–15s；prompt≤7000）
→ 展示清单（模型扣账性质/提示词/画幅/时长/分辨率/预估消耗——H3 768P 71 积分/秒、
2K 114、H3-Max 47，1000 积分=¥7；Hailuo 标「套餐额度不烧积分」）→
`ctx.approval.request()`（fail-closed、单次有效，非 allowed-once 一律不提交、
不重试、不换参数试探）→ 仅点头后走 mcode-tools submit/query/download 三动作。
**usine_publish 默认不注册**（config.publish === true 才动态 import
@feuille/publish 挂四平台）——发布不可达是工具面上根本没有，不是运行时报错；
fiber 先销毁则异步注册放弃（settled 标志）。接缝全走结构化最小面
（ToolDefinition/ToolRunContext/approval.request/systemPrompt.section），
不 link harness 类型链。esbuild externals 加 playwright；bundle 2.3mb；
全家族包进 dsh-plugin deps。dsh-v0.1.7-rc.2 的 approval 语义核对过源码：
'ask' 默认/无 answerer → 'unavailable'，审批对必须 turn 内成对审计。

**事故记录（诚实到脸上）**：allowed-once 用例首版没隔离 PATH，而本机
`~/.minimax/bin/mcode-tools` 真实存在——测试真的 spawn 了
submit_video_generation（Hailuo-2.3、6s、768P）。进程挂起 10 分钟无输出、
无 task_id、0:00.14 CPU（纯等待态），人工击杀；判断**大概率没有任务被创建**
（成功提交会很快回 task_id，挂起说明卡在等 MCode 运行时上下文），但无法证明
——**人需查一次 MCode 设置→用量与模型 确认无新任务**。修复：withoutMcodePath()
把 PATH 剥到 /usr/bin:/bin 让它结构性 ENOENT，测试注释写明事故与教训：红线对
**测试**同样成立，「本机应该没有 mcode-tools」是假设不是防线，宁可确定性失败
不可碰运气。这也反过来证明了一件事：approval 门在真实宿主里确实挡得住——
假 approval 一放行，通道就真的动了，所以门必须是 fail-closed 且单次有效。

**假 LLM 干跑（P6 验收形态）**：brief → usine_lesson new（② 注册表现取 +
选角当场验 + 空跑草稿自证，产物 brief.json 落盘断言）→ usine_scene draft
（scene.md）→ usine_scene parse（scene.json，sceneId 断言）→ usine_copy
check --facts（⑧ 发布词自检，数字溯源 PASS）→ usine_video_generation
Hailuo 提交 → 审批被拒 → asked-rejected 停车未提交 → usine_publish 不在
工具面。⑤⑥⑦ 媒体重步骤的 e2e 已由各包 vitest 套件覆盖，干跑验的是**工具面**
（每步经 dsh 工具进程内驱动）与红线边界断言；dsh web 真宿主 --patch 的
brief→自主产出实测留给 P8。

测试 18/18：注册面 17 名单逐一断言 + publish 缺席 + config 开启（动态 import
落定轮询）+ 先销毁放弃 + 反注册清空；纪律节红线文本五要素；红线九例（invalid
不进审批 ×2、无 approval/无 agent fail-closed、审批卡展示清单逐字段断言、
H3 426 积分≈¥2.98 速查表、allowed-once 才碰通道（PATH 剥离下 ENOENT 如实报）、
单次有效——再提交重新问、query/download 不走审批）；进程内捕获（copy 未知
旗标 FeuilleError→rc1 文本捕获、未知子命令 rc2、usineRoot 定位）。

门禁：typecheck 干净；vitest **43 文件（531 passed | 4 skipped）4 连绿**。
Python 侧无改动（verify_skills 78/78 上一批已绿，本批未触碰 skills/docs）。
**P6 收口。**

## P7：Python 清场（2026-10-18）——uv/Python 实现退役删除，归属纪律不随语言退役

**删除面（62 个 git 条目 + 两个未入库目录）**：src/feuille/ 全树（含 publish/）、
scripts/ 全套（verify_*.py 21 件 + verify_probes.py + verify_skills.py +
verify_docs.py）、pyproject.toml、uv.lock、migration/ 的采集与比对工具
（capture_golden.py、spike2_scenes_ref.py）、.venv/ 与 migration/__pycache__
（未入库）。**保留不动**：lessons/guangchaoshi-逛超市/review/build_prompts.py
（课堂数据，数据不动纪律）、skills/*/assets/example/ 与 examples/*.py
（只读归档）、examples/ H3 母版全程未触碰。

**ownership.json 账本重键**：模块 ID 从「tier.树路径」改为**「包.源文件」点分 ID**
（core.tts、publish.douyin），声明父 ID 覆盖其子模块（publish 覆盖 publish.*）。
清点闭合：29 个 core 源文件 + 9 个包 = library 16 + skill 专属 13 +
infrastructure 9，零孤儿零幻影。归属扫描面 = packages/*/src/**/*.ts（index.ts
桶文件与 *.d.ts 除外）。

**verify_skills.py → @feuille/gate（vitest 门禁）**：检查 0–14 全量移植
（路由覆盖、frontmatter、前置输入契约/边界段、豁免标记、Levenshtein≤2 幽灵
检测、no-islands 单向、name==dirname、12 语种 canon、README 四层产线、边界
转交、共享 example 字节一致、no-hardcoded-bins、归属 8/8b/9/10/11/12/13、
README map + 凿洞自证——假账本注入必 FAIL）。三方对账 = 账本 ↔ 实际模块 ↔
SKILL.md「拥有模块」行；13 处 SKILL.md 拥有模块行与 10 处「由 verify_skills.py
机检」措辞同步改记 @feuille/gate。3/3 首跑即绿。

**Edge 并行隔离**：真实驱动浏览器的 7 个测试文件（covers/textlayer/karaoke/
measure_korean/poster/publish/storyteller）单独成 edge project 串行
（singleFork——vitest 3.x 的 fileParallelism 是根级选项不可按 project 设）；
其余纯单元文件照常并行。根因：多实例并发抢浏览器进程，并行抖动四批三现。

**feuille CLI 实体化**：packages/cli/bin/feuille.js（spawnSync
`node --import tsx src/main.ts`；tsx 经 createRequire 从 bin 位置解析，入口
经 fileURLToPath——href 会被当相对路径）+ package.json bin 字段 + 根
devDependencies 挂 @feuille/cli（pnpm 不为无依赖者的 workspace bin 建链）。
`pnpm exec feuille …` 实跑验证：rc 0（help、persona validate）/ rc 2（未知）。

**文档清账**：docs/render-handbook.md（57× uv run feuille→feuille、验收表 →
`pnpm verify`、§0/§5 工具现实、124 行模块路径重键；python -m sys.path 事故
记录留史）、docs/toolchain.md（阶段表/依赖表全 TS 化）、docs/architecture.md
（状态行、门禁体系整节重写为 vitest 全量 + 按包清单表、CLI 路由表对齐真实
39 条、mermaid 节点）、docs/publish-lessons.md（§0.5 日志无缓冲、环境约定表
pnpm 化）、docs/publish-playbook.md:861 标注历史命令形态、languages/README.md
与 personas/voice.md（voiceId 核验口径 → 在册快照）、skills 侧 11 处 src/feuille
散文重写 + 模块路径重键。usine/AGENTS.md 11 对（工程基线/纪律 6/12/18/工程
约定/目录块）；workspace 根 AGENTS.md feuille 条目 → pnpm 约定（画字铁律改述
为成像库通则）；feuille 根 .gitignore 头注释 usine(TS/pnpm)。

**docs 门禁退役的诚实记录**：verify_docs.py（命令/脚本/符号/链接真实性五判据）
未单独移植——命令真实性由 @feuille/cli 路由测试与评审承担；「死入口零容忍」
仍是评审纪律，历史口径留档于 architecture.md §4。

门禁：typecheck 干净；vitest **44 文件（534 passed | 4 skipped）4 连绿**
（typecheck 修复一项：edge project fileParallelism → singleFork）。
**P7 收口。**
