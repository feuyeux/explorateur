---
name: bgm-bed
description: >
  Generate an instrumental BGM bed with the usable music backend (Google
  Lyria, verified end-to-end on the free tier; dead backends MiniMax/Suno/Udio
  are removed — see the provider table), measure it, and derive the exact `gain` to write back into the
  video config so the bed sits a measured distance under the narration — plus
  two self-checks that catch the two ways a generated bed silently fails (wrong
  sample-rate interpretation, and a bass drone masquerading as an arrangement).
  Also documents `matrix`, the keyless built-in generator verified end-to-end
  and usable as a finished-bed source (not a `--provider`: no duration
  parameter, and its billing is not publicly documented).
  Use when a finished video has narration but no music, when a BGM bed has to
  be produced reproducibly, or when an existing bed's level has to be justified
  with a measured number instead of a copied constant. The generation
  capability of the global music-generation skill (Lyria/Suno/Udio) is absorbed
  here; do not use that global skill for beds in this workspace. Not for mixing
  a bed into a finished video (karaoke-video does the linear amix,
  multilingual-video-poetry the sidechain), and not for TTS, subtitles, covers,
  speech or video generation.
---

# BGM 底床生成

一条底床 = **一段音频资产 + 一个反推出来的增益**。本 skill 只把这两样做成可复现的：
床怎么来（多供应商，哪个能用用哪个）、电平怎么定（实测反推）、怎么证明没挂错
（自检 + 退出码）。

**「生成床」和「把床混进成片」是两件事，别混**：

- 生成（本 skill）：一条够长、配器与电平都量过的 wav + 一个 `gain`；
- 混音（**不归本 skill**）：海报/卡片驱动的线性 `amix normalize=0` 在 `karaoke-video`，
  需要旁白把底床动态压住的侧链压缩在 `multilingual-video-poetry`。

本 skill 不实现任何一份混音滤镜图——那是 `library.audio` 的地盘。

## 供应商：能力已吸收，哪个能用用哪个

本 skill 的生成脚本只留**一条实测通路**（`--provider auto` 探测凭据、失败顺延；
`--provider X` 显式指定不顺延——框架留给未来新供应商）。全局 `music-generation`
skill（`~/.agents/skills/`，非本仓库资产）的封装能力并入后，**MiniMax / Suno /
Udio 三条死线于 2026-10-09 全部删除**，别再往回加：

| 供应商 | key | 状态（2026-10） |
|---|---|---|
| `lyria`（Google） | `GEMINI_API_KEY` 或 `~/.gemini_api_key` | **唯一整链实测过**：免费层实时端点 $0 可用（出口 IP 判区，见下） |
| `matrix`（MCode 内置） | **无 key**——用Code 登录态，走 `mcode-tools` | **整链实测过（2026-10-09，古典吉他纯器乐，判据 ok）**：但**不是 `--provider`**——入参无时长字段、计费不公开。见下 |

| 死线 | 删除原因（均实测） |
|---|---|
| `minimax`（开放平台 API） | 官方 2026-08-20 日落：两区付费音乐 API 不收新用户、免费模型停服；账户级 410/2153 闸门，换 key/主机/模型都绕不过（实测留痕见下）。**注意与 `matrix` 区分**：开放平台 API 日落 ≠ Code 内置音乐生成停用，后者实测仍可用 |
| `suno` / `udio` | 两家官方都没有公开 API，key 无官方获取渠道，第三方转售无担保 |

**`matrix` 为什么没进 `PROVIDERS`**：两个原因，缺一不可。

1. **入参没有 duration 字段**（`requests[].prompt/lyrics/format/sample_rate/bitrate`），
   床长固定、只能接受。bgm-bed 的床长判据（`bed_len_verdict`）和 `PAD_FACTOR=1.15`
   请求端垫量都建立在「能按目标时长请求」之上——塞进 `PROVIDERS`，
   `--provider auto` 就会顺延到一个必然触发 `bed_len_check` ⚠ 的后端，
   等于用退出码 2 骗上层。
2. **计费不公开**（无官方文档说明它扣不扣积分、扣多少），`detect_providers()`
   的「凭据探测」模型对它不成立——它没有 key，探测无从谈起。

**它是成品床的来源，不是 provider。** 用法与实测基线见「`matrix`：成品床来源」。

请求一律**纯器乐**（床要垫在旁白底下，人声床是配乐事故）。失败要响亮
（报端点形状、退出码非 0），不许把超时当好曲；探测用
`--list-providers`，只看凭据不碰网络。

**key 的统一配置**：`~/.config/feuille/bgm-bed.env`（样例与说明见
[references/keys.env.sample](references/keys.env.sample)；`BGM_BED_ENV` 可改指
任意路径）。优先级：**环境变量 > key 文件 > `~/.gemini_api_key`（Lyria 旧位）**；
文件在 $HOME 下，密钥永不进仓库。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **床要盖多长**（成片时长 + 余量） | 床短于成片 → 尾部裸奔，底床断在半路。床长判据照常验收，短了照样拦。走 `matrix` 时这项**无法直接满足**（该线无 duration 入参，实测固定 ≈29s），须量测后确认或循环接长 |
| 2 | **配器与情绪的加权短词** | Lyria 实时端点吃短词；给段落标签长指令会跑偏。其余供应商吃拼接后的普通字符串 |
| 3 | **旁白实测电平**，或明确的「低 N dB」目标 | 没有它 `gain` 只能抄常数，而抄错没有任何东西会报错 |
| 4 | **供应商的 key**（见上表；统一配置 `~/.config/feuille/bgm-bed.env`，`--list-providers` 先探） | 全空 → 无从生成，转告用户缺哪把 key |
| 5 | **这床垫在谁底下**（线性固定偏移 / 侧链动态余量） | 两者的配比判据不同，用错判据会得出相反结论 |

**先量旁白，再生成床。** `gain` 是床与旁白之比的产物；顺序反过来就只能靠猜。
旁白电平从 TTS 成品的真实语音区间量（成片链路不做过响度归一，量到的就是成片里的值）。

## 边界

**本 skill 是「底床生成 + 床位定标」的唯一事实源**：供应商调用（Lyria）、
采样率解读、频段与拍速自检、`gain` 反推。

**不做 / 转交**：

- 把已有的床混进成片、渲染状态帧、烧字幕 → `karaoke-video`（线性 `amix`）或 `storyteller-video`（多幕评书，同线性压法）
- 实拍母版压字幕 + 侧链把底床动态压住 → `multilingual-video-poetry`
- 人声合成、词级时间戳 → `library.tts`，经上面两条线使用
- **视频生成**（`connector__matrix__submit_video_generation` 的 Hailuo-2.3 / H3 /
  H3 Max 三条线）→ `video-generation`（**选哪条线看额度**：Hailuo 走套餐额度、
  H3 烧积分；铁律原文在 `usine/AGENTS.md`）。Hailuo-2.3 是**静音视频**，出不了床，
  别把它当音乐线
- 做海报、字体子集、逐字着色 → `one-page-poster`
- 写发布词 / 真的点发布 → `publish-copy` / `multilingual-video-publishing`
- 用全局 `music-generation` skill 生成床 → 它的三家通路已并入本 skill
  （Lyria/Suno/Udio），且它不量频段、不反推 `gain`、没有验收判据——在本工程
  里它已被取代，装不装都不往它路由

## 代码归属

拥有模块：（无）

供应商客户端（Lyria）与两项自检是本 skill 的持久脚本
`scripts/gen_bgm.py`。它没有进 library——它只服务「生成床」这一件事，成片两条线
共用的是混音那半（`library.audio`），不是生成这半。事实源见 `usine/ownership.json`，
由 `verify_skills.py` 与本段双向机检。

## 怎么用

```bash
# 0) 先看哪条供应商线通（只探测凭据，不动网络；key 统一配在
#    ~/.config/feuille/bgm-bed.env，样例见 references/keys.env.sample）
uv run --project usine --group music python \
    usine/skills/bgm-bed/scripts/gen_bgm.py --list-providers

# 1) 量旁白：从 TTS 成品的真实语音区间量（tokens[0].start → 末 token 结束），
#    别量整条——整条含 intro/outro 与词间静音，量出来的数偏低，gain 会偏大。
#    取窗口法见 references §6。

# 2) 生成床（--provider auto 按凭据顺延；--group music 装 Lyria 的 Live API 客户端）
uv run --project usine --group music python \
    usine/skills/bgm-bed/scripts/gen_bgm.py \
    --out usine/examples/<项目>/video/bgm_raw.wav \
    --provider auto \
    --prompt "felt piano chords" \
    --prompt "pizzicato string melody" \
    --prompt "warm acoustic guitar" \
    --duration 80 --bpm 84 --density 0.7 --brightness 0.75 \
    --narration-rms-db -18.2

# 3) 把脚本打印的 gain 写进 video.json 的 bgm 块，然后照常 build_video
```

## `matrix`：成品床来源（非 provider，已整链实测）

MCode 内置音乐生成（`connector__matrix__batch_text_to_music`）能出一条**纯器乐床**，
不需要任何 key——用 Code 的登录态，走 `mcode-tools` 通道。**它不进 `gen_bgm.py`
的 `PROVIDERS`**（两个原因见供应商段）。用途：Lyria 那把 key 没有时出床，
或一次多出几个变体挑选。

**已整链实测通过（2026-10-09，纯器乐古典吉他）**，工作样例可直接照抄：

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

# 3) 跑判据。band_share / tonal_verdict / measure 直接复用本skill 的脚本，
#    不另写一份口径：
uv run --project usine python -c "
import sys; sys.path.insert(0, 'usine/skills/bgm-bed/scripts')
import gen_bgm as g; from pathlib import Path
p = Path('bgm_raw.wav')
print(g.measure(p)); b = g.band_share(p); print(b, g.tonal_verdict(b))"
```

**一次最多 5 条**（`requests` 数组上限 5），适合一次出几个变体挑一条。
`format` 可选 `mp3`/`wav`，`sample_rate` 可选 16k/24k/32k/44.1k；
**PCM 不可用**（承载不了 AIGC 元数据）。出曲长约 29s（见下实测）。

### 实测基线（2026-10-09，古典吉他纯器乐）

| 项 | 值 |
|---|---|
| 出曲时长 | **28.897s**（不可控，见下） |
| 容器 | RIFF WAVE / PCM 16 bit / 立体声 / **44100 Hz** |
| RMS 电平 | **−23.7 dBFS** |
| 峰值 | −4.6 dBFS |
| 频段占比 | `<100` 0.27%、`100-400` 53.56%、`400-1k` 36.6%、`1k-3k` 8.8%、`>3k` 0.77% |
| 配器判据 | **ok**（400 Hz–3k 共 45.4%） |

**频段形态是这条线的强项**：能量集中在 100 Hz–1 kHz 的拨弦织体区，
`<100 Hz` 仅 0.27%——没有坑 2 的低音嗡鸣（嗡鸣床特征是 `>3k`<1% **且**
`<100`>45%）。古典/拨弦类配器实测干净。

⚠️ **但电平比 Lyria 床明显低**（−23.7 vs 常见 −10~−14 dBFS），所以 **gain 一定要
按实测值算**：旁白 −18 dBFS、目标低 16 dB 时 `gain ≈ 0.50`，比 Lyria 边车里
0.10 量级的常数大一截。抄常数必错（前置输入契约第 3 条）。

### 两个硬约束

1. **时长不可控**：入参**没有 duration**，出曲长度固定（实测 ≈29s）。
   成片超过这个长度 → 尾部裸奔，只能循环接长或改走 Lyria。
   **床长判据照跑**：量到的 `duration_s` 拿去对 `duration_target_s` 比。
2. **计费不透明**：官方文档未公开这条线的计费规则（M Plan 积分文档只笼统说
   积分覆盖「图片、音频及视频等多模态创作」，M Plan FAQ 的积分包清单里**没有音乐**；
   开放平台 Music-3.0/2.6 整行标「已下线」）。**别假设免费，也别照第三方
   "MiniMax Music"站的 $0.15/首、credits/首当官方价**——那些是聚合站自己的账。
   要确认真实扣减：生成前后各看一次 `设置 → 用量与模型` 的积分余额（或 `mmx quota`）。

### 边车：这条线要手写

`gen_bgm.py` 不管这条线，所以 `bgm_raw.json` 边车**得自己写**——但**床的事实源
在边车**，只留 wav 等于把「为什么是 0.50」弄丢了。至少记齐 `gen_bgm.py` 边车的
关键字段（`provider`/`model`/`prompts`/`measured`/`band_share_pct`/`tonal_check`/
`bed_len_check`/`suggested_gain`/`gain_basis`）。

⚠️ **`bpm_requested` 与 `model` 两个键必须写**，否则 `--recheck` 会直接拒绝
（`缺 bpm_requested/model——它可能不是本脚本写的`）。matrix 无 bpm 参数，
`bpm_requested` 填 `null` 即可占位，但键不能少。

生成后照常写 `video.json` 的 bgm 块；混音仍归 `karaoke-video`（线性）或
`multilingual-video-poetry`（侧链）。

产物是 **wav + 同名 `.json` 边车**。边车记着供应商、提示词、模型、目标床长
（`duration_target_s`）、实际请求（`duration_requested_s`，实时后端含垫量与
`pad_factor`）、实测时长、电平、频段占比、床长判据（`bed_len_check`）与建议
`gain`——**床的事实源在边车**，不是那个 wav。只留 wav 就等于把「为什么是
0.1012」弄丢了。

判据演进后不必重新生成（Lyria RealTime 不吃 seed，重生成会拿到另一首）：

```bash
NARRATION_RMS_DB=-18.2 uv run --project usine python \
    usine/skills/bgm-bed/scripts/gen_bgm.py --out …/bgm_raw.wav --recheck
```

（`--recheck` 也认 `--narration-rms-db` / `--target-under-db`，与生成路径同一套参数；
`NARRATION_RMS_DB` 环境变量仍是后备。）

## 每一步的验收判据

没有可测判据就等于没做完：

| 步骤 | 判据 | 不达标怎么读 |
|---|---|---|
| 供应商探测 | `--list-providers` 至少一家 ✓ | 全 ✗ = 缺 key，转告用户缺哪把（退出码 1） |
| 采集 | 成曲 **≥ 目标床长**（`--duration`）——请求端已自动垫 **1.15×**（实时后端短约 10% 是实测规律，坑 1 的结构化对策） | 垫了还短 → `bed_len_check` ⚠ → **退出码 2**，文件落盘供排查但**不要挂床** |
| 采样率 | 拍速反查 `ok`（仅 Lyria 实时后端） | `MISMATCH` = 采样率解读错了，文件不能用；其余供应商自带容器，n/a |
| 配器 | 频段判据 `ok` | `太暗` = 拿到的是低音嗡鸣，不是配器 |
| 床长 | 床 ≥ 成片时长（`bed_len_verdict` 按目标验收） | 短了尾部裸奔；垫量 + 退出码 2 双保险 |
| 床位（混完） | 床比旁白低 **15–18 dB** | 低了盖人声，高了抢 |
| 连续性（混完） | 主体段逐 0.5s **零段低于 −45 dBFS** | 有段 = 断流 |
| 平稳性（混完） | 主体段动态范围 **≤ 12 dB** | 超出 = 床自己在起伏，听感忽强忽弱 |
| 成片 | 人声窗 − 空档窗 ≥ 8 dB（LUFS 口径） | 见 `references` |

⚠️ **生成类命令默认不覆盖**已有文件（纪律 13），要覆盖显式 `--force`。
⚠️ **判据不通过要让退出码说话**：文件照样落盘供排查，但退出码非 0，上层不会误当成功。
自检 FAIL 的床**别删**——改名归档进 `rejected/`（边车一起），攒几份之后阈值就有历史可回溯（纪律 17：负结果即时落盘）。
⚠️ **auto 顺延只在生成失败时发生**；全部失败会汇总各自报错再退出 1。

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

MiniMax 实测留痕（2026-10-09，线已删）：`POST /v1/music_generation` 直接
**HTTP 410 / status_code 2153**——「This Music API is no longer available to new
users. Existing paying customers can continue to use the service.」本账户不在存量
名单，官方指路 MiniMax Audio（minimax.io/audio）或开源模型 MiniMax-Music3
（HuggingFace）。国际区（api.minimax.io）文档挂着**同一条日落公告**（2026-08-20
起付费音乐 API 不收新用户、music-*-free 全部停用，定价表音乐行全标
Discontinued）——**两区对新用户都是死的，别按文档残留的 music-3.0-free 再去试**。
换新 key 在文档主机 api.minimax.cn 重测（music-2.6 / music-2.6-free /
music-3.0-free 三个模型）：鉴权通过、依然 2153——**闸门在账户侧，不在 key/主机/模型**。
整链判定：**存量账户之外这条路走不通**；脚本侧行为正确（日落警告在前、410
响亮失败、退出码 1）——判据表是给所有供应商共用的，供应商栏的状态是各自的。

Suno / Udio 死线删除前的实测留痕（2026-10-09）：两家官方均无公开 API；曾按转售商
sunoapi.org 文档形状实现并验到鉴权层（Cloudflare 拦裸 UA → 带浏览器 UA 后假 key 得
文档形状的 401），因 key 只能向第三方转售商买、无官方渠道担保而删除。`gen_bgm.py`
的 HTTP 小件保留浏览器 UA（走 CDN 的端点可能按 UA 拦脚本），这段留痕是它的出处。

## 四个真踩过的坑

1. **床比请求短约 10%**（请求 62s → 实得 54.0s；请求 80s → 实得 78.0s）。
   **已结构化**：`--duration` 是**目标床长**，实时后端请求端自动垫 1.15×
   （`pad_request`），床长判据按目标验收（`bed_len_verdict`），垫了还短 → 退出码 2。
   两个纯函数的反向验证在 `usine/scripts/verify_skill_scripts.py`
   （凿洞用的就是这两组实测事故数字）。
2. **稀疏提示词 + 低 brightness 会换来一条低音嗡鸣**：>3 kHz 只剩 0.1%、64% 能量压在
   100 Hz 以下。旁白一盖完全听不出来，混完等于没挂床——**必须量频段，不能靠听**。
3. **`bpm` 是软提示**：请求 84，实测拍速 175.8。拍速对不上**不能**判死刑，只有
   48k↔44.1k 的换算比能解释它时才是采样率读错。
4. **CDN 端点会按 UA 拦脚本**：403/1010 不代表端点死了，换浏览器 UA 再下结论；
   但 429/430（配额/频次）是真拒绝，别重试，换线。

细节、报错速查表与判据的反向验证见
[references/lyria-field-notes.md](references/lyria-field-notes.md)。

## 资源

- `scripts/gen_bgm.py` — 多供应商床生成 + 实测（`--provider auto` 顺延；
  `--recheck` 只重算判据不重生成；`--list-providers` 只探测凭据；
  `--duration` = 目标床长，实时后端请求端自动垫 1.15×，床长判据按目标验收）
- `references/keys.env.sample` — 统一 key 文件样例（复制到
  `~/.config/feuille/bgm-bed.env`；环境变量优先于文件）
- `references/lyria-field-notes.md` — Lyria 端点/配额/地区围栏、两项自检的
  原理与阈值、报错速查、床位实测取窗口法
