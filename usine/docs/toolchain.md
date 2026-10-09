---
title: "feuille 工具链（Toolchain）"
status: "工作流所用工具的清单（唯一事实源）；版本锁定与跨平台解析规则的权威在 ../AGENTS.md「工程约定」"
updated: { by: dsh/fuyao-work, at: 2026-10-07 }
---

# 工具链（Toolchain）

> 十三段工作流（[workflow.md](workflow.md)）会碰到的**全部工具**：§1 按阶段列「每段用什么」，§2–§3 按工具列版本与坑，§4 平台后台，§5 仓库内机制。
> 阶段编号：①内容创作（人工）②创意交接 ③设计 ④内容审计 ⑤音频 ⑥视频 ⑦封面 ⑧发布清单 ⑨平台发布 ⑩合集收录 ⑪发布后核对 ⑫指标回流 ⑬验收检查。
> 版本数字以 `uv.lock`（E 落地后）与 ../AGENTS.md「工程约定」为准。

---

## 1. 每个阶段用什么工具

| 阶段 | 工具 |
|---|---|
| ① 内容创作（人工） | 人写；无工程工具 |
| ② 创意交接 | Python（schema 纯函数校验，`uv run`）；H3 母版需求 = 人工逐次确认 |
| ③ 设计 | 人写设计稿（storyboard / 分镜提示词），落成 JSON 参数；无专属工具 |
| ④ 内容审计 | Python（格律审计：手写拆分 + 算法交叉验证） |
| ⑤ 音频 | edge-tts（需网络）、ffprobe（时长实测）、Python（时间轴补齐） |
| ⑥ 视频 | Edge headless（渲字）、ffmpeg（叠加 + 混音 + loudnorm）、Pillow（matte 合成 / 逐帧绘制）；画面基底 = H3 母版（仅内容项目，逐次确认额度）或程序化渲染 |
| ⑦ 封面 | Edge headless（叠字截图）、Pillow + magick（底图预裁、裁切安全拼图） |
| ⑧ 发布清单 | Python（文案解析 + 逐项核对） |
| ⑨ 平台发布 | Chrome + Playwright（发布器，四平台后台见 §4）；登录 / 风控人工 |
| ⑩ 合集收录 | Chrome + Playwright（创建合集 / 挂作品 / 核对）；Pillow（合集封面 1080×1080 重排） |
| ⑪ 发布后核对 | Chrome + Playwright（只读截图）；Pillow / magick（拼对照图） |
| ⑫ 指标回流 | 人工取数；Python（分组分析） |
| ⑬ 验收检查 | 渲染前：Python（schema / 文案 / 审计）；渲染后：ffmpeg（framehash 逐帧 `-map 0:v`）、numpy（画面探针）、magick（裁切安全拼图）、ffprobe（规格实测）；发布后核对 = ⑪ |
| 贯穿全程 | uv（Python 一律 `uv run`）、git（版本控制 / 事故恢复）、mavis-trash（删除走回收站，macOS 本机） |

---

## 2. 外部可执行工具（跨平台一律经 resolver 解析，不写死路径）

| 工具 | 阶段 | 用途 | 关键口径与坑 | 跨平台注意 | 先例 |
|---|---|---|---|---|---|
| **uv** | 全阶段（工程基座） | Python 环境与依赖管理 | 一切 Python 调用走 `uv run`；`uv sync --group publish` / `--group music` 按需装可选组；锁文件自动同步 | Win / macOS / Linux 官方支持 | — |
| **Python 3** | ②–⑬ | 脚本运行时 | 经 `uv run` 调用，不直接用系统 / homebrew python；过渡态例外见 AGENTS.md | 同上 | — |
| **Microsoft Edge**（headless） | ⑥渲字 ⑦封面 | 文字层 / 封面截图渲染 | `raqm=False` 的唯一正确出路（阿/希/天城文必须走它）；`--window-size` ≠ 视口高，先探后补（`viewport_deficit`）；与像素基线同源故 resolver 排首位 | 候选链 Edge → Chrome → Chromium；环境变量可临时覆盖 | `feuille.textlayer.viewport_deficit` |
| **Google Chrome** | ⑨发布 ⑩合集收录 ⑪发布后核对 | Playwright 驱动 + 持久 profile | 用**系统 Chrome**（`executable_path`），不用 Playwright 自带浏览器——四平台 profile 各一、绑定登录态 | 写死的 `/Applications/...` 路径是已核实缺陷，现已改走 resolver | `feuille.publish` |
| **Chromium** | 备选 | resolver 第三候选 | 找不到浏览器返回 None 并显式失败，绝不退化「系统默认」 | 三系统 | `feuille.platform` |
| **ffmpeg** | ⑥合成 ⑬验收 | 基底叠加、混音（loudnorm −14 LUFS）、逐帧像素哈希 | `apad` 必须前置 `loudnorm`（EOF 冲刷竞态，10 连跑丢补尾 3 次）；时长控制 `-t` + 前置 apad/atrim，**禁 `-shortest`**；像素判据 `-map 0:v -f hash -hash md5`（少 `-map 0:v` 数字不同且不报错） | 三系统；经 resolver | `feuille.audio.compose_track`；`feuille.framehash` |
| **ffprobe** | ⑤时间轴 ⑬验收 | 时长 / 流 / 规格实测 | `file_dur` 以 ffprobe 实测为准（edge-tts 尾部垫 ~0.95s 静音） | 三系统；经 resolver | `feuille.timeline` |
| **ImageMagick** `magick` | ⑦裁切安全 ⑪拼图 ⑬ | 按平台真实展示比例裁切封面、拼对照图 | 上传比例 ≠ 展示比例（小红书 3:4 上下各切 240、B站首页 4:3 左右各切 240） | 三系统；经 resolver | `feuille.covers` |
| **bash** | 批量产线（历史参考） | 批量校验 / 实测时长 / 渲染脚本 | 只对传输层错误重试（`NoAudioReceived` 等），渲染/预算错误重试无意义；workers ≤5（10 并发压垮内存） | ⚠️ **Windows 无原生 bash——feuille 的批处理不沿用此形态**，统一入口走 `uv run feuille` | — |
| **git** | 全程 | 版本控制 + 事故恢复 | `git show` 旧版文件逐字节回填；⚑ U+2691 易写成 ⚡ U+26A1 | 三系统 | — |
| **mavis-trash** | 清理 / 删除 | 删除走回收站，不用 `rm -rf` | workspace 约定：`/Users/han/.minimax/bin/mavis-trash --` | ⚠️ macOS 本机工具；跨平台时需等价回收站方案 | workspace 约定 |
| **Hailuo-2.3 / H3 / H3 Max**（mcode-tools） | ⑥ 基底（提示词出自 ③ 分镜；**仅内容项目**） | 文生 / 图生视频母版 | **铁律：绝不自动调用**，逐次展示提示词/画幅/时长/分辨率/消耗并取得明确同意；一次生成、按画幅成对、生成后冻结，后续只叠加（见 AGENTS.md 铁律）。**默认 Hailuo-2.3**：走套餐额度不烧积分；只有时长/画质不够才升H3（只扣积分） | 网页 / API | `examples/yiyezhiqiu/masters/` |

---

## 3. Python 依赖（uv 锁定；版本权威在 `uv.lock`）

| 包 | 锁定 | 阶段 | 用途 | 关键口径与坑 |
|---|---|---|---|---|
| **edge-tts** | `==7.2.8` | ⑤ TTS | 语音合成 + 词级时间戳 | `boundary="WordBoundary"`（默认只发句边界）；行时长 = `min(探针时长, 末词 end + 0.2s)` 裁尾部静音；识别伪词兜底；`NoAudioReceived` 瞬时抖动按退避重试（参数错误会稳定复现，可区分）；**需网络**（微软语音服务）；语速语种差异大（韩语比中文慢 5–29%→放宽预算不压台词） |
| **Pillow** | `==12.3.0` | ⑥⑦⑬ | 逐帧绘制、matte 合成、探针取样 | **像素基线锚点，升级前必须重验 framehash**；本机 `raqm=False` → 不许 Pillow 画字，文字一律 Edge 截图；透明叠加层走白/黑双 matte（`alpha=255−(C_w−C_b)`） |
| **numpy** | `==2.3.5` | ⑬ 探针 | 像素 / 几何计算 | 探针容差注意逐通道 vs 欧氏距离（大窗数色会被布景污染，改几何定位） |
| **playwright**（可选组 `publish`） | E 落地时锁定 | ⑨⑩⑪ | 平台自动化（发布器 / 合集 / 只读核对） | `uv sync --group publish` 后照常 `uv run`；过渡态在 `/opt/homebrew/bin/python3`；驱动系统 Chrome + 持久 profile；认证 / 风控一律人工 |
| **google-genai**（可选组 `music`） | `>=2.29` | ⑤（仅 BGM） | Lyria 底床生成（Live API 客户端） | `uv sync --group music` 后照常 `uv run`；**免费层只有 `lyria-realtime-exp` 可用**，且 Live 音乐端点**按出口 IP 判区**（比普通 API 严）；采样率无协商字段，按模型卡 48 kHz/立体声解读并用拍速反查；判据与坑见 skill `bgm-bed` |

> 标准库同样承重的：`hashlib`（内容寻址缓存键 `sha256(voiceId|rate|pitch|text)[:16]`、framehash）、`zipfile`（交付打包须置 UTF-8 flag bit 0x800）、`pathlib`（跨平台路径，不拼平台专属分隔符）。

---

## 4. 平台创作者后台（⑨⑩⑪ 的操作对象；无 API，只能浏览器逐步操作）

| 平台 | 后台入口 | profile | 硬限制（实测） | 先例 |
|---|---|---|---|---|
| **抖音** | `creator.douyin.com/creator-micro/` | `~/.douyin_creator_profile` | 标题 ≤30 字；正文 ≤1000 字；**每作品最多修改 5 次**；封面槽实为 3:4；合集需先建 | `feuille.publish.douyin`（两步：先发再 `fix_covers` 补封面） |
| **小红书** | `creator.xiaohongshu.com` | `~/.xhs_creator_profile` | 标题 ≤**20** 字⚠️（29 字抖音标题直接红字）；话题在正文末行；发布按钮 DOM 不可见（像素探测 #FF2442）；风控「Scan to verify」停下等人；**无合集管理页** | `feuille.publish.xhs` + `feuille.publish.veriflive` |
| **B 站** | `member.bilibili.com/platform/` | `~/.bili_creator_profile` | 标题 ≤80 字；创作声明必填 6 值白名单（勾「自制」版权声明填不满必填框）；合集需权益 Lv2；「立即投稿」后有二次确认；成功词表须含「稿件**投递**成功」 | `feuille.publish.bilibili` + `feuille.publish.veriflive` |
| **知乎** | `zhuanlan.zhihu.com` | `~/.zhihu_creator_profile` | 长文唯一可自动化路径 =「导入文档」上传 .md（Draft.js 只在真实 paste 转换）；**一篇文章最多 10 个视频**（实测 12 支插到第 10 支卡住）；**阿拉伯语有违规风险**（宗教语境靠近红线，逐条风险表见 docs/publish-lessons.md §4.1b）；阿拉伯文区段 U+0600–06FF 存盘被剥（平台限制）；雪花 ID 精度 bug 致草稿删不掉；**无合集**（主文导览互链代替） | `zhihu-publish-playbook`（人工导入 .md） + docs/publish-lessons.md |

> 通用铁律（AGENTS.md 纪律 19–21 + 5）：宁可整条不发，也不带病发布；发布成功唯一权威判据 = 回列表核验到作品；发布后核对只读、截图取证；扫码 / 风控一律人工。

---

## 5. 仓库内机制工具

feuille 自有的机制模块全部在 `src/feuille/`，每件带反向验证（`uv run feuille verify` 一条命令全量跑）。

