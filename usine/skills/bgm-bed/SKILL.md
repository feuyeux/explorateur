---
name: bgm-bed
description: >
  Generate an instrumental BGM bed via one of the two verified sources —
  Google Lyria (free-tier realtime endpoint, `feuille bgm gen`) or
  Minimax Code's built-in Matrix music tool
  (`connector__matrix__batch_text_to_music` via mcode-tools; keyless but
  callable only inside the MCode runtime; fixed ≈29s output) — measure it,
  and derive the exact `gain` for the video
  config so the bed sits a measured distance under the narration, plus
  self-checks that catch silent bed failures (wrong sample-rate
  interpretation; a bass drone masquerading as an arrangement). Use when a
  finished video has narration but no music, when a bed must be
  reproducible, or when a bed's level must be justified by measurement
  instead of a copied constant. Also covers the local-synthesis fallback
  line (no key, no network — the only way out when Lyria's quota is
  exhausted, which fails *silently*: exit code 0, no file written) and
  the "not harsh" tonal recipe (sawtooth harmonics fold back over
  Nyquist and are the real cause of harshness; bidirectional band
  verdict; bed sits 22 dB under narration). Not for mixing the bed into the video
  (karaoke-video: linear amix; multilingual-video-poetry: sidechain), and
  not for TTS, subtitles, covers, speech or video generation.
---

# BGM 床生成

一条底床 = **一段音频资产 + 一个反推出来的增益**。本 skill 只把这两样做成可复现的：
床怎么来（两条实测线：Lyria 脚本线、MCode 内置音乐）、电平怎么定（实测反推）、
怎么证明没挂错（自检 + 退出码）。**「生成床」和「把床混进成片」是两件事**：
混音是线性 `amix normalize=0`（`karaoke-video`）还是侧链压缩（`multilingual-video-poetry`）
由画面来源定，都不归本 skill——本 skill 不实现任何混音滤镜图，那是
`core.audio` 的地盘。

## 三条出床线

| 线 | key | 状态（2026-10 / 2026-11） |
|---|---|---|
| `lyria`（Google，`feuille bgm gen`） | `GEMINI_API_KEY`（统一配置 `explorateur/config/.env`） | **整链实测过**：免费层实时端点 $0 可用（出口 IP 判区，见下）。⚠️ **额度耗尽是「静默成功」**——退出码 0、一个文件不写，等窗口重试也一样，见「`local`」 |
| `local`（自己合成，振荡器 + ADSR + 和声垫 + 旋律） | **无 key、无网络** | **整链实测过（2026-11-14，20 组床 + 236 支成片）**：Lyria 不可用时的唯一出路；同口径边车，`feuille bgm gen` 可直接复用。见「`local`」 |
| `matrix`（MCode 内置 Matrix 工具集的音乐线） | **无 key**——用 Code 登录态，经 `mcode-tools`（**仅 MCode 运行时的 PATH 上**） | **整链实测过（2026-10-09，古典吉他纯器乐，判据 ok）**，但**不是 `feuille bgm gen` 的通路**——入参无时长字段、计费不公开，见下 |

**`matrix` 为什么不进 `feuille bgm gen`**，两个原因缺一不可：① 入参没有 duration 字段
（`requests[].prompt/lyrics/format/sample_rate/bitrate`），床长固定只能接受——床长
判据（`bed_len_verdict`）与 `PAD_FACTOR=1.15` 请求端垫量都建立在「能按目标时长
请求」之上，塞进生成命令后必然触发 `bed_len_check` ⚠，等于用退出码 2 骗上层；
② 计费不公开，`detect_providers()` 的凭据探测模型对无 key 的它不成立。
**它是成品床的来源，不是脚本通路**（用法见「`matrix`：成品床来源」）。

请求一律**纯器乐**（床要垫在旁白底下，人声床是配乐事故）。失败要响亮
（报端点形状、退出码非 0），不许把超时当好曲；生成前可用
`--list-providers` 探 Lyria 凭据，只看凭据不碰网络。

**key 的统一配置**：`explorateur/config/.env`（全工作区唯一配置点，théâtre 波次与 usine 流水线同源；样例与说明见 `explorateur/config/env.sample`）。优先级：**环境变量 > config/.env**；旧位置（`~/.config/feuille/keys.env`、`bgm-bed.env`、`~/.gemini_api_key`）自 2026-10-19 起退役不再读取；该文件被 explorateur 根 `.gitignore` 兜底，密钥永不进仓库（`BGM_BED_ENV` 仅测试显式改指用）。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **床要盖多长**（成片时长 + 余量） | 床短于成片 → 尾部裸奔，底床断在半路。床长判据照常验收，短了照样拦。走 `matrix` 时这项**无法直接满足**（无 duration 入参，实测固定 ≈29s，见「两个硬约束」） |
| 2 | **配器与情绪的加权短词** | Lyria 实时端点吃短词；给段落标签长指令会跑偏 |
| 3 | **旁白实测电平**，或明确的「低 N dB」目标 | 没有它 `gain` 只能抄常数，而抄错没有任何东西会报错 |
| 4 | **Lyria 的 key**（matrix 线无 key；统一配置 `explorateur/config/.env`，`--list-providers` 先探） | 全空 → 脚本线无从生成，转告用户缺哪把 key |
| 5 | **这床垫在谁底下**（线性固定偏移 / 侧链动态余量） | 两者的配比判据不同，用错判据会得出相反结论 |

**先量旁白，再生成床。** `gain` 是床与旁白之比的产物；顺序反过来就只能靠猜。
旁白电平从 TTS 成品的真实语音区间量（成片链路不做过响度归一，量到的就是成片里的值）。

## 边界

**本 skill 是「底床生成 + 床位定标」的唯一事实源**：出床线调用（Lyria / local /
matrix）、采样率解读、频段与拍速自检、`gain` 反推、**音色的「不刺耳」口径**。

**不做 / 转交**：

- 把已有的床混进成片、渲染状态帧、烧字幕 → `karaoke-video`（线性 `amix`）或 `storyteller-video`（多幕评书，同线性压法）
- 实拍母版压字幕 + 侧链把底床动态压住 → `multilingual-video-poetry`
- 人声合成、词级时间戳 → `core.tts`，经上面两条线使用
- **视频生成**（`connector__matrix__submit_video_generation` 的 Hailuo-2.3 / H3 /
  H3 Max 三条线）→ `video-generation`（**选哪条线看额度**：Hailuo 走套餐额度、
  H3 烧积分；铁律原文在 `usine/AGENTS.md`）。Hailuo-2.3 是**静音视频**，出不了床，
  别把它当音乐线
- 做海报、字体子集、逐字着色 → `one-page-poster`
- 写发布词 / 真的点发布 → `publish-copy` / `multilingual-video-publishing`
- 用全局 `music-generation` skill 生成床 → 本工程的床只从本 skill 的三条线
  （Lyria / local / matrix）出，不往它路由；它也不量频段、不反推 `gain`、没有验收判据

## 代码归属

拥有模块：bgm

供应商客户端（Lyria）与两项自检已归流到 **@feuille/bgm** 包，进程内直跑
`feuille bgm gen`。它只服务「生成床」这一件事，成片两条线
共用的是混音那半（`core.audio`），不是生成这半。事实源见 `usine/ownership.json`，
由 @feuille/gate 的 vitest 门禁（`pnpm verify`）与本段双向机检。

## 怎么用

```bash
# 0) 先探 Lyria 凭据（不动网络；key 统一配在 explorateur/config/.env，
#    样例见同目录 env.sample）
feuille bgm gen --list-providers

# 1) 量旁白：从 TTS 成品的真实语音区间量（tokens[0].start → 末 token 结束），
#    别量整条——整条含 intro/outro 与词间静音，量出来的数偏低，gain 会偏大。
#    取窗口法见 references §6。

# 2) 生成床（Lyria 的 Live API 客户端 @google/genai 已随 @feuille/bgm 常装）
feuille bgm gen \
    --out usine/examples/<项目>/video/bgm_raw.wav \
    --prompt "felt piano chords" \
    --prompt "pizzicato string melody" \
    --prompt "warm acoustic guitar" \
    --duration 80 --bpm 84 --density 0.7 --brightness 0.75 \
    --narration-rms-db -18.2

# 3) 把命令打印的 gain 写进 video.json 的 bgm 块，然后照常 build_video
```

## `local`：本地合成兜底（第三条线，Lyria 额度耗尽时的唯一出路）

Lyria 免费层额度会耗尽，而**额度耗尽的表现是「静默成功」**——进程退出码 0、
一个文件都不写（`ai.live.music.connect()` 的 promise 永不 resolve，Node 事件循环
空转退出）。所以**光看退出码会把「没出床」当成「出好了」**：调用方必须自己查
「文件落盘了吗」。等窗口重试也一样。

第三条线是**自己合成床**：振荡器 + ADSR + 和声垫 + 旋律，产出同口径的边车
（`provider: 'local-synth'`、`tonal_check`、`bed_len_check`、`suggested_gain`、
`gain_basis` 字段与 Lyria 那条完全一致），所以 `feuille bgm gen` 复用它时
**不分提供方**。用法：Lyria 不可用（无 key / 额度耗尽 / 网络不通）时直接走这条。

### 合成床的音色口径（这一路的要点，Lyria 那条不适用）

**刺耳的根因是合成方式，不是音量。** 旋律的奇次谐波若用**裸锯齿波**
（`2*(phase%1)-1`）合成，谐波会越过 Nyquist 频率**折返回来**叠成金属味噪点——
这是「刺耳」的主因，把音量调小只会让它变成「小而尖」。所以：

| 要素 | 别这么做 | 这么做 | 为什么 |
|---|---|---|---|
| 谐波波形 | 裸锯齿 | **纯正弦叠加**，只取前 3 个谐波，逐次 `0.55**h` 衰减 | 锯齿的无限谐波是折返噪点的来源；正弦叠加没有折返 |
| 音区 | 分音散到几 kHz | 旋律基频之上的分音压到 **≤ 660 Hz** | 否则落进人耳最敏感的 1–3 kHz |
| 高频层 | 和弦音 4×/6×/8× 分音 | **删掉** | 落在 3–10 kHz，正是「刺耳」的频段 |
| 低频轰击 | 每拍一记 78 Hz 底鼓 | **删掉** | 与旁白争注意力，床位再低也显吵 |
| 整形 | — | 80 Hz 高通 + **2600 Hz 两级低通**（−12 dB/oct） | 一次去掉嗡鸣与亮刺 |

单极点低通系数必须是 `k = 1 − exp(−2π·fc/fs)`；写成 `1 − 2π·fc/fs` 会把截止
频率压到 ~670 Hz（实测：整条床只剩闷响）。

### 判据要**双向**：只判「太暗」会把床一路推到刺耳那侧

这是合成床最容易踩的坑——「床不够亮就调亮」是个单边判据，而调亮过头就直接
刺耳。所以频段判据必须两侧都有界：

| 条件 | 读法 |
|---|---|
| `<100 Hz > 45%` | 嗡鸣（配器被带成了低音 drone） |
| `>3 kHz > 6%` | 过亮刺耳 |
| `1–3 kHz > 25%` | 人耳最敏感段过亮 |
| `400 Hz–3 kHz < 3%` | 发闷 |

合成床做完的实测形态：`>3 kHz` 一律 **0%**、`1–3 kHz` ≤ **6.9%**、`<100 Hz`
**0%**、RMS −24.4 ~ −27 dBFS。

⚠️ **频段占比不能用「每频段 N 个 Goertzel 探测点」算**——必须用**等间隔 bin 的
FFT 谱**（探测点法会把某些频段的占比算偏）。单极点滤波的系数同理，见上。

### 床位间距：22 dB，不是 16 dB

床比旁白低 **22 dB**（不是 16 dB）。16 dB 时床已经会分走注意力——「不占主导」
不是「还能听见」，是「听见了也知道它在垫」。目标间距写进 `TARGET_UNDER_DB`，
**两边脚本（生成线与复用线）必须同值**，否则算出来的 gain 与判据对不上。

### 听感只有人耳能判

机检能证明「频段占比达标 + 音量压在旁白之下」，**证不了「听着不刺耳」**。
所以合成/换床之后要出**两个样本**交付用户听：① 床单听（不带旁白）② 床+旁白
的真实混音。**别自己判定「应该不刺耳」就往下走**——机检全绿而听感刺耳，是这套
产线最典型的「绿了但没做对」。

## `matrix`：成品床来源（非脚本通路，已整链实测）

MCode 内置音乐生成（`connector__matrix__batch_text_to_music`）能出一条**纯器乐床**，
不需要任何 key——用 Code 的登录态，走 `mcode-tools` 通道。用途：Lyria 那把 key
没有时出床，或一次多出几个变体挑选。

**`mcode-tools` / `matrix` 的官方出处与运行环境**（2026-10-10 查证）：
`mcode-tools` 是 MiniMax Code（npm `@minimax-ai/code`）自带的**媒体工具启动器**
（与 agent 本体 `mcode` 并列），**只在 MCode 运行时进程的 PATH 上**——在其它
shell（含本仓库脚本的执行环境）里 `which mcode-tools` 找不到是正常的，别在那些
环境里硬调。`matrix` 是 MCode 内置图/音/视频工具集的**连接器 ID**（官方能力表
原文 "Search and Matrix image / audio / video tools"，经 Matrix MCP 装配；
App = Connector，调用名 `connector__matrix__<方法>`——视频线
`connector__matrix__submit_video_generation` 同源）。MCode 数据目录在
`~/.minimax/`，其内置技能 `mcode-tools-master` 是这条通道的官方用法说明。
工作样例可直接照抄：

```bash
# 1) 生成。lyrics 省略即纯器乐——床要垫在旁白底下，人声床是配乐事故。
#    prompt 用英文描述性写法更稳（模型吃具体乐器/织体/情绪，别写段落标签）。
mcode-tools connector call connector__matrix__batch_text_to_music --args '{
  "requests":[{
    "prompt":"solo classical guitar, fingerpicked nylon-string, gentle flowing arpeggios, slow and steady tempo, soothing calm and meditative mood, warm intimate close-mic recording, no percussion, no vocals, pure instrumental",
    "format":"wav", "sample_rate":44100,
    "output_file":"classical_guitar_calm.wav"
  }]}'
# → {"code":0,"total_success":1,"success_items":[{"node_id":"…","file_name":"…wav"}]}

# 2) 换下载直链并落盘（node_id 是唯一入口，不要自己拼 OSS/CDN 地址）
mcode-tools get_asset_url <node_id>
curl -sL -o bgm_raw.wav "<download_url>"

# 3) 跑判据。band_share / tonal_verdict / measure 直接复用 @feuille/bgm 的
#    唯一实现，不另写一份口径——先按「边车：这条线要手写」记齐边车，
#    再一条命令全量重算：
feuille bgm gen --out bgm_raw.wav --recheck
```

**一次最多 5 条**（`requests` 数组上限 5），适合一次出几个变体挑一条。
`format` 可选 `mp3`/`wav`，`sample_rate` 可选 16k/24k/32k/44.1k；
**PCM 不可用**（承载不了 AIGC 元数据）。

### 实测基线（2026-10-09，古典吉他纯器乐）

| 项 | 值 |
|---|---|
| 出曲时长 | **28.897s**（不可控，见下） |
| 容器 | RIFF WAVE / PCM 16 bit / 立体声 / **44100 Hz** |
| RMS 电平 | **−23.7 dBFS** |
| 峰值 | −4.6 dBFS |
| 频段占比 | `<100` 0.27%、`100-400` 53.56%、`400-1k` 36.6%、`1k-3k` 8.8%、`>3k` 0.77% |
| 配器判据 | **ok**（400 Hz–3k 共 45.4%） |

频段形态是这条线的强项：能量集中在 100 Hz–1 kHz 的拨弦织体区，`<100 Hz` 仅
0.27%——没有坑 2 的低音嗡鸣（嗡鸣床特征是 `>3k`<1% **且** `<100`>45%）。
古典/拨弦类配器实测干净。

### 两个硬约束

1. **时长不可控**：入参**没有 duration**，出曲长度固定（实测 ≈29s）。成片超过
   这个长度 → 尾部裸奔，只能循环接长或改走 Lyria。床长判据照跑：量到的
   `duration_s` 拿去对 `duration_target_s` 比。
2. **计费不透明**：官方文档未公开这条线的计费规则（M Plan 积分文档只笼统说积分
   覆盖「图片、音频及视频等多模态创作」，FAQ 积分包清单里**没有音乐**）。**别假设
   免费，也别照第三方聚合站的价目当官方价**。要确认真实扣减：生成前后各看一次
   `设置 → 用量与模型` 的积分余额（或 `mmx quota`）。

⚠️ **电平比 Lyria 床明显低**（−23.7 vs 常见 −10~−14 dBFS），所以 **gain 一定要按
实测值算**：旁白 −18 dBFS、目标低 **22 dB** 时 `gain ≈ 0.50`，比 Lyria 边车里
0.10 量级的常数大一截。抄常数必错（前置输入契约第 3 条）。

### 边车：这条线要手写

产物是 **wav + 同名 `.json` 边车**，**床的事实源在边车**——只留 wav 等于把
「为什么是这个 gain」弄丢了。边车记着供应商、提示词、模型、目标床长
（`duration_target_s`）、实际请求（`duration_requested_s`，实时后端含垫量与
`pad_factor`）、实测时长、电平、频段占比、床长判据（`bed_len_check`）与建议
`gain`。

`feuille bgm gen` 不管 matrix 这条线，所以边车**得自己写**，但至少记齐 Lyria 边车的
关键字段（`provider`/`model`/`prompts`/`measured`/`band_share_pct`/`tonal_check`/
`bed_len_check`/`suggested_gain`/`gain_basis`）。⚠️ **`bpm_requested` 与 `model`
两个键必须写**，否则 `--recheck` 会直接拒绝（`缺 bpm_requested/model——它可能不是
本脚本写的`）；matrix 无 bpm 参数，`bpm_requested` 填 `null` 占位即可，但键不能少。

生成后照常写 `video.json` 的 bgm 块。

判据演进后不必重新生成（Lyria RealTime 不吃 seed，重生成会拿到另一首）：

```bash
NARRATION_RMS_DB=-18.2 feuille bgm gen --out …/bgm_raw.wav --recheck
```

（`--recheck` 也认 `--narration-rms-db` / `--target-under-db`，与生成路径同一套参数；
`NARRATION_RMS_DB` 环境变量仍是后备。）

## 每一步的验收判据

没有可测判据就等于没做完：

| 步骤 | 判据 | 不达标怎么读 |
|---|---|---|
| 凭据探测 | `--list-providers` ✓ | ✗ = 缺 key，转告用户缺哪把（退出码 1） |
| 采集 | 成曲 **≥ 目标床长**（`--duration`）——收流按「凑够音频秒数」判，不按 wall 时间；请求端另垫 **1.15×** 作余量（坑 1） | 垫了还短 → `bed_len_check` ⚠ → **退出码 2**，文件落盘供排查但**不要挂床** |
| 采样率 | 拍速反查 `ok`（仅 Lyria 实时后端） | `MISMATCH` = 采样率解读错了，文件不能用；自带容器的来源 n/a |
| 配器 | 频段判据 `ok`（**双向**：太暗 = 低音嗡鸣；过亮刺耳 = `>3 kHz`/`1–3 kHz` 越界） | 单边判据会把床一路推到刺耳那侧，见「`local`」 |
| 床长 | 床 ≥ 成片时长（`bed_len_verdict` 按目标验收） | 短了尾部裸奔；垫量 + 退出码 2 双保险 |
| 床位（混完） | 床比旁白低 **22 dB** | 低了盖人声，高了抢 |
| 连续性（混完） | 主体段逐 0.5s **零段低于 −45 dBFS** | 有段 = 断流 |
| 平稳性（混完） | 主体段动态范围 **≤ 12 dB** | 超出 = 床自己在起伏，听感忽强忽弱 |
| 成片 | 人声窗 − 空档窗 ≥ 8 dB（LUFS 口径） | 见 `references` |

⚠️ **生成类命令默认不覆盖**已有文件（纪律 13），要覆盖显式 `--force`。
⚠️ **判据不通过要让退出码说话**：文件照样落盘供排查，但退出码非 0，上层不会误当成功。
自检 FAIL 的床**别删**——改名归档进 `rejected/`（边车一起），攒几份之后阈值就有历史可回溯（纪律 17：负结果即时落盘）。

## 实测：Lyria 哪个模型能用（2026-10-09，免费层 key）

| model | 端点 | 免费层 key | 计费 |
|---|---|---|---|
| `lyria-realtime-exp`（默认） | Live API WebSocket `BidiGenerateMusic` | **可用** | $0 |
| `lyria-3.5` / `lyria-3-pro-preview` / `lyria-3-clip-preview` | `POST /v1beta/interactions` | 429 `limit: 0 requests per day on Free Tier` | $0.04–0.08 / 首 |

- `lyria-3.5` 内部路由到 `lyria-3-pro`，所以它的 429 里写的是 `lyria-3-pro`。
- `lyria-realtime-exp` **不在** `interactions` 上（400 Model not found），是流式 Live 模型。

**实时音乐端点按出口 IP 判区，比普通 API 严**：香港出口下 `models.list` 返 200、
`lyria-3.5` 返 429 配额错，唯独 `live.music` 直接 `User location is not supported`
秒断。官方支持区里有日本 / 台湾 / 新加坡 / 美国，**没有香港**。换出口即可，$0 路线不变。

## 三个真踩过的坑

1. **床比请求短一半**（2026-10-19：请求 76.1s → 实得 36.0s；换短一点的请求 69s → 42s，比例随长度下滑）。
   **根因不在后端**：`oneSession` 按「1 s wall 收 1 s 音频」睡，实测到账只有 **0.5–0.6× 实时**
   （150 s wall 收到 88 s 音频），于是每次都在一半处 `close()`。已改成「凑够音频字节再关」：
   `want = seconds × 48000 × 2 × 2`，wall 上限 2.5× 请求秒 + 30 s，20 s 无新数据即判流断，
   多收的尾巴截掉。`--duration` 仍是**目标床长**，请求端垫 1.15× 只作余量；
   床长判据按目标验收，垫了还短 → 退出码 2。原先记的「后端短约 10%」是这个缺陷的假象。
   两个纯函数的反向验证在 `usine/packages/bgm/test/`（vitest；凿洞用的就是早期那两组
   62s→54.0s / 80s→78.0s 的实测数字——它们同样是这个缺陷造成的）。
2. **稀疏提示词 + 低 brightness 会换来一条低音嗡鸣**：>3 kHz 只剩 0.1%、64% 能量压在
   100 Hz 以下。旁白一盖完全听不出来，混完等于没挂床——**必须量频段，不能靠听**。
3. **`bpm` 是软提示**：请求 84，实测拍速 175.8。拍速对不上**不能**判死刑，只有
   48k↔44.1k 的换算比能解释它时才是采样率读错。

细节、报错速查表与判据的反向验证见
[references/lyria-field-notes.md](references/lyria-field-notes.md)。

## 资源

- `feuille bgm gen`（@feuille/bgm 包）— Lyria 床生成 + 实测（`--recheck` 只重算判据不重生成；
  `--list-providers` 只探测凭据；`--duration` = 目标床长，实时后端请求端自动垫
  1.15×）
- `references/keys.env.sample` — 已退役的旧样例，仅存指向 `explorateur/config/.env`（现行唯一配置点）的迁移指引；现行样例是 `explorateur/config/env.sample`
- `references/lyria-field-notes.md` — Lyria 端点/配额/地区围栏、两项自检的
  原理与阈值、报错速查、床位实测取窗口法
