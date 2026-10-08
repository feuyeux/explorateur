# Lyria 外场笔记（实测，非文档转述）

> 全部结论来自 2026-10-09 在一台 **免费层 Gemini API key + 香港出口**的机器上跑出来的。
> 文档只写「支持哪些模型」，不写「你这把 key 现在能调哪个」——后者只能实测。

## 1. 端点与配额

| model | 端点 | 免费层 key 的实际结果 | 计费 |
|---|---|---|---|
| `lyria-3.5` | `POST /v1beta/interactions` | 429 `Rate limit exceeded for model lyria-3-pro (limit: 0 requests per day on Free Tier)` | $0.04–0.08 / 首 |
| `lyria-3-pro-preview` | 同上 | 同上（429，模型名即自身） | 同上 |
| `lyria-3-clip-preview` | 同上 | 429 `… for model lyria-3-clip (limit: 0 requests per day …)` | 同上 |
| `lyria-realtime-exp` | Live API WebSocket `google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateMusic` | **可用** | $0 |
| `lyria-002` | Vertex `:predict` | 本机无 gcloud / 无 ADC，未验证 | — |

要点：

- **`lyria-3.5` 的报错里写的是 `lyria-3-pro`**（内部路由）。按报错里的名字去查配额会
  找错模型——先知道它是别名。
- **`lyria-realtime-exp` 不在 `interactions` 端点上**，POST 过去是
  `400 Model 'lyria-realtime-exp' not found. Did you mean 'lyria-3-clip-preview'?`。
  它是流式 Live 模型，走 `client.aio.live.music.connect(model=…)`。
- **免费层探测技巧**：用**空提示词**探配额。限流器先于参数校验应答，于是
  `429` = 免费层额度 0，`400` = 端点不支持该模型 —— 两者都不计费。
  拿真实提示词去探，一旦模型可用就会真扣钱。
- Live 音乐是 **mldev only**（SDK 里显式 `raise NotImplementedError` for Vertex AI），
  也就是说**没有 Vertex 兜底**：出口地区不对就是不对。

## 2. 地区围栏：为什么「别的能调它不能」

实时音乐端点**按出口 IP 判区**，且比同一 key 的其它端点严得多。实测同一把 key、同一
出口 IP：

| 调用 | 香港出口的结果 |
|---|---|
| `GET /v1beta/models` | **200**，返回 62 个模型（含 4 个 Lyria） |
| `POST /interactions`（`lyria-3.5`） | **429 配额错**（说明请求已通过地区检查，卡在配额） |
| Live `BidiGenerateMusic` | **建连后秒断**，close frame 原文：`User location is not supported for the API use.` |

所以**看到 429 不代表地区没问题**——它只说明那一个端点放行了。模型清单里能看见
Lyria 也不代表能调。

官方支持区（ai.google.dev/available_regions）里有日本 / 台湾 / 新加坡 / 美国，
**没有香港、也没有中国大陆**。换出口到上述任一区后，同一段脚本一次通过。

**症状 → 病因对照**（SDK 把 close frame 包成了 1006/1007，所以要从症状认病因）：

```
RuntimeError: 音乐流中断：APIError: 1006 None. abnormal closure [internal]
              ｜已采集 0 字节（0.0s）/ 请求 10s，断在开流后 11.5s
```

- **0 字节 + 秒级断流** → 地区围栏（不是配额、也不是代码错）
- **拿到一段才断** → 流中断，重试即可（脚本对建连错误有退避重试，流内错误不重试）
- **429** → 免费层额度 0，换 `lyria-realtime-exp`（$0）或换付费层

## 3. 采样率：SDK 不给你协商，只能按模型卡解读

`LiveMusicGenerationConfig`（google-genai 2.29）的字段只有
`temperature / top_k / seed / guidance / bpm / density / brightness / scale /
mute_bass / mute_drums / only_bass_and_drums / music_generation_mode`——
**没有 `audio_format`，也没有 `sample_rate_hz`**（JS 文档里有，Python 类型没暴露）。

所以只能按模型卡声明的 **48 kHz / 立体声 / 16 bit PCM** 解读 wav 头。写错的后果是
整条片子变调，而且**不会报错**，所以必须反查。

**反查原理**：请求 `bpm` → 生成 → 估实测拍速 → 看差多少。

```
rate_mismatch_bpm = detected / (48000/44100)   或   detected * (48000/44100)
```

- 换算后命中 `bpm`（或其 ×2 / ÷2）→ **采样率读错了，文件不能用**
- 直接就命中 → 48 kHz 解读可信
- 都不命中 → 多半是模型没照 bpm 走（`bpm` 是软提示），**拍速法判不了采样率**，
  标 inconclusive，请人耳确认音高

⚠️ **判据分支顺序反了会误杀**：0.9188 与 1.0 相差很小，直读与换算读可能**同时**
命中 ±5% 容差。实测踩过：175.8 BPM 同时落进「直读 168±5%」和「÷1.0884 后 161.5≈168」，
先查换算比就把正常文件判成了 MISMATCH。**必须先认直读**（模型卡声明、且 L≠R
佐证真立体声），直读对不上才去问换算比。

## 4. 配器：必须量频段，不能靠听

稀疏提示词（`calm slow sparse underscore`）+ `brightness 0.4` 会让 Lyria RealTime
吐一条**低频嗡鸣**。实测那条 54.0s 的床：

| 频段 | 能量占比 |
|---|---|
| < 100 Hz | **64.5%** |
| 100–400 Hz | 30.2% |
| 400 Hz–1 kHz | 4.7% |
| 1 kHz–3 kHz | 0.4% |
| > 3 kHz | **0.1%** |

旁白一盖就完全听不出来，混完等于没挂床。**所以判据是频段占比，不是耳朵**：

- `< 100 Hz > 45%` 且 `> 3 kHz < 1%` → 太暗，多半是提示词把模型带成了嗡鸣；
  调高 `brightness`（0.4 → 0.75）与 `density`（0.6 → 0.7）后重生成。
- `400 Hz–3 kHz 合计 < 3%` → 中高频偏少，床会发闷。

调亮后的同一提示词组：`< 100 Hz 0.08% / 100–400 46.9% / 400 Hz–1 kHz 51.7%`，
判据 ok。

⚠️ 别把阈值过拟合到单条样本上：上面两条只抓**实测踩到过的灾难**（嗡鸣），
不是通用音色审美标准。

**注意 RealTime 的输出本身就是限带的**（1 kHz 以上几乎为空）——这是模型/流格式的
特性，不是你配置错了。别为了「把高频补出来」反复重生成。

## 5. 反向验证（判据自身也要被验）

两个自检都不能只有正向表现。反向验证用合成数据喂：

| 用例 | 期望 |
|---|---|
| 拍速 = 请求值 / ×2 / ÷2（±5% 内） | `ok` |
| 拍速 = 请求值 ×(48000/44100)（±5% 内） | `MISMATCH` |
| 拍速 = 请求值 ×(44100/48000)（±5% 内） | `MISMATCH` |
| 拍速差很远且套不上换算比 | `inconclusive` |
| 合成 70 Hz 正弦（纯低频） | 频段判据 `⚠ 太暗`，**退出码 2** |

**好数据必须先全 PASS**（纪律 1）——反向验证的前提是好数据能过，否则你证明的只是
「能抓到坏的」。

## 6. 床位反推与混后验收

`gain` 是**推出来的**，不是抄的：

```
gain = 10 ^ ((旁白实测 RMS dBFS − 目标低多少 dB − 床实测 RMS dBFS) / 20)
```

实例：旁白 −18.2 dBFS、目标低 16 dB、床 −14.3 dBFS → `gain 0.1012`。
换床就重算；手改 `gain` 之后**没有任何东西会告诉你它错了**。

**量旁白电平**：从 TTS 的真实语音区间量（`tokens[0].start` 到末 token 结束），
别量整条——整条含 intro/outro/词间静音，量出来的数偏低，`gain` 会偏大。

**混完验收**（床轨由 `build_video` 落在 `<frames>/_bgm_track.wav`，已含 gain 与两端淡）：

1. **床位**：`volumedetect` 量 `_bgm_track.wav` 的 RMS，减去旁白实测值 → 目标 15–18 dB。
2. **连续性**：逐 0.5s 电平，**排除两端淡入淡出区**（1.5s / 3.0s）后不得有段
   低于 −45 dBFS。不排除会把淡出尾巴误报成「断流」——实测踩过：52.0s 的 −52.5 dBFS
   是设计中的淡出，不是断点。
3. **平稳性**：主体段动态范围 ≤ 12 dB。超出说明床自己在起伏，听感忽强忽弱。
4. **成片人声 vs 空档**：用 `audio_profile.py`（在 `multilingual-video-poetry`）按
   LUFS 口径量，差 ≥ 8 dB。⚠️ **配比判据用 LUFS 不用 RMS**——同一段混音两种口径
   能差 6 dB 以上，拿 RMS 会得出「不达标」的假结论。

## 7. 报错速查

| 现象 | 病因 | 处置 |
|---|---|---|
| `429 … limit: 0 requests per day on Free Tier` | 免费层跑付费模型 | 换 `--model lyria-realtime-exp`（$0） |
| `400 Model 'lyria-realtime-exp' not found`（在 `interactions` 上） | 用错端点 | 它是 Live API 流式模型，不是 `interactions` |
| `1006/1007` + 0 字节 + 秒断 | 地区围栏 | 换出口到日本/台湾/新加坡/美国 |
| `ConnectionResetError`（建连时） | TLS 抖动 | 脚本已对建连错误退避重试，直接重跑 |
| `APIError` 在流中断且已收到字节 | 会话被掐 | 已收到的字节会被丢弃，报错信息里带采集量 |
| 自检 `太暗` | 提示词带成了低音嗡鸣 | 调高 brightness / density 重生成 |
| 自检 `MISMATCH` | 采样率解读可能错 | 别用这个文件；先看 close frame 原文 |

## 8. 生成不出来的床 ≠ 不挂床

免费层 + 受限地区下 Lyria RealTime 可能整条路走不通。此时**诚实降级**：
去掉 `video.json` 的 `bgm` 块，或把 `bgm.file` 指向一条已有的纯器乐 wav。
`build_video` 只做裁剪/淡入淡出/定增益，床从哪来跟它无关——**但别让上层以为
床已经挂上了**（`bgm.file` 指向不存在的文件要显式失败，不许静默跳过）。