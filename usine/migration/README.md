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
