---
name: bgm-bed
description: >
  Generate an instrumental BGM bed with Google Lyria (Gemini API), measure it,
  and derive the exact `gain` to write back into the video config so the bed
  sits a measured distance under the narration — plus two self-checks that
  catch the two ways a generated bed silently fails (wrong sample-rate
  interpretation, and a bass drone masquerading as an arrangement). Use when a
  finished video has narration but no music, when a BGM bed has to be produced
  reproducibly, or when an existing bed's level has to be justified with a
  measured number instead of a copied constant. Not for mixing a bed into a
  finished video (karaoke-video does the linear amix, multilingual-video-poetry
  the sidechain), and not for TTS, subtitles, covers or publishing.
---

# BGM 底床生成

一条底床 = **一段音频资产 + 一个反推出来的增益**。本 skill 只把这两样做成可复现的：
床怎么来（Lyria）、电平怎么定（实测反推）、怎么证明没挂错（自检 + 退出码）。

**「生成床」和「把床混进成片」是两件事，别混**：

- 生成（本 skill）：一条够长、配器与电平都量过的 wav + 一个 `gain`；
- 混音（**不归本 skill**）：海报/卡片驱动的线性 `amix normalize=0` 在 `karaoke-video`，
  需要旁白把底床动态压住的侧链压缩在 `multilingual-video-poetry`。

本 skill 不实现任何一份混音滤镜图——那是 `library.audio` 的地盘。

## 前置输入契约

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **床要盖多长**（成片时长 + 余量） | 床短于成片 → 尾部裸奔，底床断在半路 |
| 2 | **配器与情绪的加权短词** | Lyria RealTime 吃短词；给段落标签长指令会跑偏 |
| 3 | **旁白实测电平**，或明确的「低 N dB」目标 | 没有它 `gain` 只能抄常数，而抄错没有任何东西会报错 |
| 4 | **API key 与出口地区** | 免费层只有 `lyria-realtime-exp`；实时端点按出口 IP 判区 |
| 5 | **这床垫在谁底下**（线性固定偏移 / 侧链动态余量） | 两者的配比判据不同，用错判据会得出相反结论 |

**先量旁白，再生成床。** `gain` 是床与旁白之比的产物；顺序反过来就只能靠猜。
旁白电平从 TTS 成品的真实语音区间量（成片链路不做过响度归一，量到的就是成片里的值）。

## 边界

**本 skill 是「底床生成 + 床位定标」的唯一事实源**：Lyria 调用、采样率解读、
频段与拍速自检、`gain` 反推。

**不做 / 转交**：

- 把已有的床混进成片、渲染状态帧、烧字幕 → `karaoke-video`（线性 `amix`）
- 实拍母版压字幕 + 侧链把底床动态压住 → `multilingual-video-poetry`
- 人声合成、词级时间戳 → `library.tts`，经上面两条线使用
- 做海报、字体子集、逐字着色 → `one-page-poster`
- 写发布词 / 真的点发布 → `publish-copy` / `multilingual-video-publishing`

## 代码归属

拥有模块：（无）

Lyria 客户端与两项自检是本 skill 的持久脚本 `scripts/gen_bgm.py`。它没有进
library——它只服务「生成床」这一件事，成片两条线共用的是混音那半（`library.audio`），
不是生成这半。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

## 怎么用

```bash
# 1) 量旁白：从 TTS 成品的真实语音区间量（tokens[0].start → 末 token 结束），
#    别量整条——整条含 intro/outro 与词间静音，量出来的数偏低，gain 会偏大。
#    取窗口法见 references §6。

# 2) 生成床（--group music 装 Live API 客户端）
uv run --project usine --group music python \
    skills/bgm-bed/scripts/gen_bgm.py \
    --out examples/<项目>/video/bgm_raw.wav \
    --prompt "felt piano chords" \
    --prompt "pizzicato string melody" \
    --prompt "warm acoustic guitar" \
    --duration 80 --bpm 84 --density 0.7 --brightness 0.75 \
    --narration-rms-db -18.2

# 3) 把脚本打印的 gain 写进 video.json 的 bgm 块，然后照常 build_video
```

产物是 **wav + 同名 `.json` 边车**。边车记着模型、提示词、实测时长、电平、频段占比与
建议 `gain`——**床的事实源在边车**，不是那个 wav。只留 wav 就等于把「为什么是 0.1012」
弄丢了。

判据演进后不必重新生成（Lyria RealTime 不吃 seed，重生成会拿到另一首）：

```bash
NARRATION_RMS_DB=-18.2 uv run --project usine python \
    skills/bgm-bed/scripts/gen_bgm.py --out …/bgm_raw.wav --recheck
```

## 每一步的验收判据

没有可测判据就等于没做完：

| 步骤 | 判据 | 不达标怎么读 |
|---|---|---|
| 采集 | 成曲 **≥ 成片时长 + 余量** | 实测请求 80s 只拿到 78.0s，短 10% 是常态 |
| 采样率 | 拍速反查 `ok` | `MISMATCH` = 采样率解读错了，文件不能用 |
| 配器 | 频段判据 `ok` | `太暗` = 拿到的是低音嗡鸣，不是配器 |
| 床长 | 床 ≥ 成片时长 | 短了尾部裸奔 |
| 床位（混完） | 床比旁白低 **15–18 dB** | 低了盖人声，高了抢 |
| 连续性（混完） | 主体段逐 0.5s **零段低于 −45 dBFS** | 有段 = 断流 |
| 平稳性（混完） | 主体段动态范围 **≤ 12 dB** | 超出 = 床自己在起伏，听感忽强忽弱 |
| 成片 | 人声窗 − 空档窗 ≥ 8 dB（LUFS 口径） | 见 `references` |

⚠️ **生成类命令默认不覆盖**已有文件（纪律 13），要覆盖显式 `--force`。
⚠️ **判据不通过要让退出码说话**：文件照样落盘供排查，但退出码非 0，上层不会误当成功。

## 实测：哪个模型能用（2026-10-09，免费层 key）

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

1. **床比请求短约 10%**（请求 62s → 实得 54.0s）。按成片时长去要，尾部会裸奔。
2. **稀疏提示词 + 低 brightness 会换来一条低音嗡鸣**：>3 kHz 只剩 0.1%、64% 能量压在
   100 Hz 以下。旁白一盖完全听不出来，混完等于没挂床——**必须量频段，不能靠听**。
3. **`bpm` 是软提示**：请求 84，实测拍速 175.8。拍速对不上**不能**判死刑，只有
   48k↔44.1k 的换算比能解释它时才是采样率读错。

细节、报错速查表与判据的反向验证见
[references/lyria-field-notes.md](references/lyria-field-notes.md)。

## 资源

- `scripts/gen_bgm.py` — Lyria 床生成 + 实测（`--recheck` 只重算判据不重生成）
- `references/lyria-field-notes.md` — 端点/配额/地区围栏、两项自检的原理与阈值、
  报错速查、床位实测取窗口法