# ffmpeg 滤镜图四个坑

全部为实测复现。**症状与根因的对应关系不要靠猜**——按
`scripts/audio_profile.py` 拆轨逐段对比来定位。

---

## 坑 1 · `asplit` 缺失 → 人声被整体压掉 25–30 dB

### 症状

听感是「BGM 忽隐忽现，且完全没有 TTS 旁白」。看起来像两个问题，实际是**一个**。

### 成因

同一个 filter 输出被**两个**滤镜同时引用时，ffmpeg **不会自动拆分**：

```bash
# 错：[voice] 既当 sidechaincompress 的触发轨，又当 amix 的主轨
[bg][voice]sidechaincompress=...[duck];
[duck][voice]amix=inputs=2:normalize=0[b]
```

### 实测

| t | 人声干轨 | 混音 |
|---|---|---|
| 6.10s | −15.2 dB | −41.3 dB |
| 6.50s | −16.4 dB | −42.1 dB |
| 7.00s | −16.5 dB | −43.5 dB |

### 修法

显式 `asplit=2`，拆成主轨与触发轨：

```bash
...,loudnorm=...,apad,atrim=0:TOTAL,asplit=2[vm][vs];
[bg][vs]sidechaincompress=...[duck];
[duck][vm]amix=inputs=2:normalize=0:dropout_transition=0,alimiter=limit=0.95[mix]
```

### 为什么症状有欺骗性

侧链拿到的是完好的 `[voice]`，所以 BGM 一直在被**正确压低**——压低动作是生效的。
缺的只是人声本身。于是听到的是「本该出人声的时候 BGM 突然沉下去，却什么人都没听见」。
**只看最终混音永远定位不到**，必须与人声干轨对比。

### 已排除的嫌疑（省得重查）

下面这些都**不是**原因，实测无效：

- `dropout_transition=0` — 加不加结果完全一致
- `alimiter` — 去掉后数值不变
- `loudnorm` — 去掉后仍复现

---

## 坑 2 · `loudnorm` 排在 `afade` 之后 → 淡出尾巴被冲掉

### 症状

BGM 在画面结束前 2.6 秒就变成 `-inf` 数字静音，听感「戛然而止」。

### 成因

`loudnorm` 是**动态滤镜、自带缓冲**。放在淡出之后，它会把淡出的尾巴冲掉。

实测：该链路的 `sidechaincompress` 输出只有 **13.2 秒**，而主轨 19.916s、
触发轨 19.958s——侧链提前收流，主混音随之为空。

### 修法

**归一化必须在塑形之前**：

```bash
[0:a]atrim=start=BGM_START:end=BGM_START+TOTAL+1,asetpts=N/SR/TB,
     loudnorm=I=-24:TP=-2:LRA=7,        # ← 先归一化
     afade=t=in:st=0:d=1.5,             # ← 再塑形
     atrim=0:TOTAL,
     afade=t=out:st=TOTAL-3.5:d=3.5[bg]
```

---

## 坑 3 · `atrim` 终点等于淡出终点 → 没有余量可淡

淡出其实是在淡曲子自己的结尾，等于没淡。**多取 1 秒源**，淡出才有真正的音乐可淡。

修完尾部实测（逐 0.25s RMS）：

```
16.5s −26.8 → 18.0s −29.9 → 19.0s −38.0 → 19.7s −51.8 → 19.9s −78.8
```

3.5 秒平滑淡出，正好收在画面结束那一刻。

---

## 坑 4 · `concat` 拼接等长完整轨道 → 时长成倍

烧字幕时若每个分支都是**完整长度的基础视频**叠一张卡：

```bash
# 错：每个 [v{i}] 都是 20 秒完整视频，concat 后变 80 秒
[0:v][c0]overlay=...[v0]; ... [v3]concat=n=4:v=1:a=0[v]
```

正确做法是**在同一条时间线上串行叠加**，用 `enable` 控制各卡片的时间窗：

```bash
[0:v][c0]overlay=0:0:enable='between(t,s0,e0)'[v0]
[v0][c1]overlay=0:0:enable='between(t,s1,e1)'[v1]
[v1][c2]...[v2]
[v2][c3]...[vout]
```

**`-t TOTAL` 是必需的**：`-loop 1` 的卡片输入是无限流，不设上限 ffmpeg 不收尾。

---

## 其他实测事实

- `sidechaincompress` 参数序是 `[主][旁白]`：BGM 当主轨（被压），旁白当触发轨。
  **方向反了会变成「有人声才铺底」。**
- edge-tts 输出是 24k 单声道，`loudnorm` 会把内部重采样提到 192k，AAC 就写成
  96k 单声道，白白撑大文件。显式钉 `-ar 48000 -ac 2`。
- `amix` 的滤镜段之间**必须用 `;` 分隔**，漏一个报 `Trailing garbage after a filter`。
- 滤镜输出被引用两次时 ffmpeg 会因未连接的输出报错，用 `anullsink` 消化掉多余分支。