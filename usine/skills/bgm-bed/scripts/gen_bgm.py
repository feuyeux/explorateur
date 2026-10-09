#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_bgm.py — 生成成片用的纯器乐 BGM 床（多供应商：哪个能用用哪个）

成片里的 BGM 是一条**独立资产**：先用这个脚本生成并实测，再把 `bgm` 块写进
`video.json`（`build_video.py` 只做「裁到画面网格 + 两端淡 + 定增益 + `amix`」，
不会凭空变出音乐来）。床的电平是**反推**出来的，不是抄模板常数：本脚本量出床的
实际电平，配合 `--narration-rms-db` 直接给出该写进 `video.json` 的 `gain`。

## 供应商（能力已并入本脚本；全局 music-generation skill 不再是本工程的通路）

`--provider auto`（默认）按下列顺序探测凭据，哪个能用用哪个；某一供应商生成
失败（配额 / 围栏 / 端点形状不符）就顺延到下一个。`--provider X` 显式指定时不
顺延——失败就是失败。

| 供应商 | key（环境变量） | 状态 |
|---|---|---|
| `lyria`（Google） | `GEMINI_API_KEY` 或 `~/.gemini_api_key` | 实测可用（免费层走实时端点） |

Suno / Udio 官方都**没有**公开 API（key 无官方获取渠道，第三方转售无担保）；
MiniMax 音乐 API 自 **2026-08-20 起两区都不收新用户**（账户级 410/2153 闸门，
换 key/主机/模型都绕不过，实测见 SKILL.md）。三条死线已于 2026-10-09 删除
——别再往回加。

请求一律**纯器乐**——床要垫在旁白底下，人声床是配乐事故。时长由 lyria
实时后端的采集秒数控制，**床长判据（≥ 成片时长）照常验收**，短了就报。

`--list-providers` 只做凭据探测不动网络，适合先看一眼哪条线通。

## 用法

    uv run --project usine --group music python \
        skills/bgm-bed/scripts/gen_bgm.py \
        --out examples/pencil/video/bgm_raw.wav \
        --provider auto \
        --prompt "soft felt piano" --prompt "gentle pizzicato strings" \
        --duration 62 --bpm 72 --narration-rms-db -21.4

`--group music` 装 `google-genai`（Lyria 实时端点的 Live API 客户端）。不装也能
跑，但 lyria 只剩 `--model lyria-3.5` 那条 HTTP 后端可用。

## Lyria 选哪个模型（2026-10 实测，免费层 key = 0 额度的那三个会被直接拒）

| 模型 | 端点 | 免费层 key | 计费 | 形态 |
|---|---|---|---|---|
| `lyria-realtime-exp`（默认） | Live API WebSocket | **可用** | $0 | 流式裸 PCM，采样率/声道由服务端定 |
| `lyria-3.5` / `lyria-3-pro-preview` / `lyria-3-clip-preview` | `POST /v1beta/interactions` | 429「0 requests per day on Free Tier」 | $0.04–0.08 / 首 | 一次请求整首 |

`lyria-realtime-exp` 按设计**不出人声**（模型卡：instrumental … with no vocals）。
提示词走**加权短词**（`WeightedPrompt`），多个 `--prompt` 按序降权，或直接
`--text` 给一段。

## 输出

- `<out>`：wav（48 kHz / 立体声 / 16 bit PCM，非实时后端经平台解码器统一到此格式）
- `<out>.json`：供应商、提示词、模型、实测时长/电平、**实测拍速对照**——床的事实源
- stdout：实测报告 + 该写进 `video.json` 的 `gain`

**为什么 Lyria 实时后端不写死采样率**：SDK 的 `LiveMusicGenerationConfig` 没有
`audio_format` 字段，采样率是服务端定的。所以脚本用**实测拍速反查**：请求 72 BPM，
若成品的自相关峰值落在 72 BPM 的 ±5%（含 ×2 / ÷2 折叠），说明按 48 kHz 解读是
对的；否则 wav 头就是错的，整条片子会变调——这种情况必须当场报错，不许把错的
文件当成功交出去。其余后端自带容器，采样率由音频头决定，无需反查。

**外部可执行文件**（量电平 / 解码容器用）走 `feuille.platform` 解析，找不到显式失败。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

try:
    from feuille import platform
except ImportError:                                   # pragma: no cover
    sys.exit("feuille 不可导入：请用 `uv run --project usine python …` 运行"
             "（AGENTS.md uv 统一）")

# 文档声明的流格式（Lyria RealTime 模型卡：48 kHz / Stereo / Raw 16-bit PCM）。
# 服务端没给协商字段，只能按文档解读——并用实测拍速反查，见 _verify_rate。
RATE, CHANNELS, WIDTH = 48000, 2, 2
# 唯一值得考虑的另一种解读：48 k ↔ 44.1 k。差 8.9%，是采样率读错时唯一能解释的量。
RATE_RATIOS = (RATE / 44100, 44100 / RATE)

# auto 模式的探测顺序。minimax/suno/udio 三条死线已于 2026-10-09 删除
# （minimax 官方日落两区关死新用户、suno/udio 无官方 API），别加回来。
PROVIDERS = ("lyria",)


class ProviderError(RuntimeError):
    """单个供应商生成失败。auto 模式捕获后顺延到下一个；显式指定则上抛。"""


def _tool(name: str) -> str:
    got = getattr(platform, name)() or ""
    if not got:
        sys.exit(f"找不到 {name}（feuille.platform 解析）；装好后重跑")
    return got


# ---------------------------------------------------------------- 凭据探测

def _key_file() -> Path:
    """统一 key 文件：~/.config/feuille/bgm-bed.env（BGM_BED_ENV 可改指任意路径）。

    放在 $HOME 下是刻意的——密钥永不进仓库（usine/AGENTS.md 纪律：key 走环境
    或用户目录，不落盘到 git 管辖范围）。样例见 references/keys.env.sample。
    """
    return Path(os.environ.get("BGM_BED_ENV", "").strip()
                or Path.home() / ".config" / "feuille" / "bgm-bed.env")


def load_env_file() -> Path | None:
    """把 key 文件里的变量灌进环境——**不覆盖已有环境变量**（环境优先于文件）。

    返回实际加载的文件（不存在/没可解析行返回 None），供探测报告显示来源；
    找不到不是错误（纯环境变量也能跑），只影响报告里那行提示。
    """
    f = _key_file()
    if not f.is_file():
        return None
    got = False
    for line in f.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
            got = True
    return f if got else None


def _lyria_key() -> str | None:
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        return env
    f = Path.home() / ".gemini_api_key"
    if f.is_file():
        key = f.read_text("utf-8").strip()
        if key:
            return key
    return None


def detect_providers() -> list[tuple[str, str]]:
    """[(供应商, 凭据来源描述)]，按 PROVIDERS 顺序。只看凭据在不在，不碰网络。"""
    rows = []
    if _lyria_key():
        rows.append(("lyria", "GEMINI_API_KEY / ~/.gemini_api_key"))
    return rows


def _load_lyria_key() -> str:
    key = _lyria_key()
    if not key:
        sys.exit("找不到 Lyria key：设 GEMINI_API_KEY 或写 ~/.gemini_api_key")
    return key


# ---------------------------------------------------------------- HTTP 小件

# 走 CDN 的官方端点可能按 UA 拦脚本（2026-10 实测 api.sunoapi.org 裸 urllib
# UA 被 1010 直接拦，带浏览器 UA 才放行）；统一带浏览器 UA 无害。
_HTTP_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": _HTTP_UA, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get_json(url: str, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": _HTTP_UA, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _download(url: str, timeout: int = 300) -> bytes:
    with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": _HTTP_UA}),
            timeout=timeout) as r:
        return r.read()


def _http_error(e: urllib.error.HTTPError, provider: str) -> ProviderError:
    body = b""
    if e.fp:
        try:
            body = e.read()
        except Exception:
            pass
    return ProviderError(f"{provider} HTTP {e.code}：{body.decode(errors='replace')[:300]}")


# ---------------------------------------------------------------- lyria（实测过）

async def _capture_realtime(key, model, prompts, cfg_kwargs, seconds, attempts=3):
    """建连抖动的退避重试。

    只重试 **建连** 类错误（TLS 握手重置 / 连接被断开）——实测经代理跑 WebSocket
    时偶发。地区围栏、配额、流中断都不重试：那些再连一次还是同样的结果，
    无脑重试只会把一条有用的报错埋掉。
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await _one_session(key, model, prompts, cfg_kwargs, seconds)
        except OSError as e:
            last = e
            print(f"  建连失败（第 {i + 1}/{attempts} 次）：{type(e).__name__}: {e}")
            await asyncio.sleep(2 * (i + 1))
    raise ProviderError(f"连续 {attempts} 次连不上音乐流：{last}")


async def _one_session(key, model, prompts, cfg_kwargs, seconds):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    chunks: list[bytes] = []
    async with client.aio.live.music.connect(model=f"models/{model}") as session:
        await session.set_weighted_prompts(
            prompts=[types.WeightedPrompt(text=t, weight=w) for t, w in prompts])
        await session.set_music_generation_config(
            config=types.LiveMusicGenerationConfig(**cfg_kwargs))
        # 播放前先起接收：流式会话不先抽水，首段会被丢掉
        err: list[BaseException] = []

        async def pump():
            try:
                async for msg in session.receive():
                    sc = getattr(msg, "server_content", None)
                    if sc is None:
                        continue
                    for ch in (sc.audio_chunks or []):
                        if ch.data:
                            chunks.append(ch.data)
            except asyncio.CancelledError:
                raise                       # 正常收尾，不是错误
            except BaseException as exc:    # 流中途出错要报出来，不能半首当成功
                err.append(exc)

        task = asyncio.create_task(pump())
        t0 = time.monotonic()
        await asyncio.sleep(1.5)          # 握手 + 生成器预热
        await session.play()
        try:
            await asyncio.sleep(seconds)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        got = sum(len(c) for c in chunks)
        if err:
            elapsed = time.monotonic() - t0
            # 报错时必须能看出「断在哪、已经拿到多少」——否则只能盲重试
            hint = ""
            if got == 0 and elapsed < 20:
                # 2026-10 实测：秒级断流 + 0 字节 = 地区围栏，不是配额也不是代码。
                # 服务端 close frame 写的是「User location is not supported」，
                # SDK 把它包成 1006/1007，所以要从「症状」认病因。
                hint = ("\n↳ 0 字节秒断：**多半是地区围栏**，不是配额也不是本脚本。"
                        "\n  Live 音乐端点比普通 API 更严——同一把 key、同一出口 IP 下 "
                        "`models.list` 能 200、\n  `lyria-3.5` 能回 429 配额错，"
                        "只有 `live.music` 会按出口 IP 判区。\n"
                        "  官方支持区（ai.google.dev/available_regions）里有日本 / 台湾 / "
                        "新加坡 / 美国，**没有香港**。\n"
                        "  → 换代理出口到上述任一区再跑；或换付费层 key 走 "
                        "`--model lyria-3.5` 的 HTTP 后端。")
            raise ProviderError(
                f"音乐流中断：{type(err[0]).__name__}: {err[0]}｜"
                f"已采集 {got} 字节（{got / (RATE * CHANNELS * WIDTH):.1f}s）/ "
                f"请求 {seconds:g}s，断在开流后 {elapsed:.1f}s{hint}") from err[0]
    return b"".join(chunks)


def _capture_http(key, model, prompt, _prompts, _cfg, _seconds):
    """付费层的一次成型路径（免费层会被 429 挡掉）。"""
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps({"model": model, "input": prompt}).encode(),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            doc = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "Free Tier" in body:
            sys.exit(f"{model} 在这把 key 上是付费模型，免费层额度为 0：\n{body[:300]}\n"
                     f"→ 换 --model lyria-realtime-exp（$0）")
        raise ProviderError(f"lyria HTTP {e.code}：{body[:300]}") from e
    # outputs 里 type=="audio" 的 data 是 base64 音频（文档形状）。这条
    # HTTP 路径从未在付费 key 上实测过（免费层直接 429），所以下面解不出
    # 容器就大声失败，绝不把「猜测的格式」当事实写盘。
    for out in doc.get("outputs") or []:
        if out.get("type") == "audio" and out.get("data"):
            return base64.b64decode(out["data"])
    raise ProviderError(f"lyria 响应里没有音频（顶层键：{sorted(doc)}）")


def _gen_lyria(args) -> tuple[bytes, bool]:
    """→ (音频, is_raw_pcm)。raw PCM 只有实时后端；HTTP 后端自带容器。"""
    key = _load_lyria_key()
    realtime = args.model == "lyria-realtime-exp"
    if not realtime and not args.text:
        sys.exit("--text 是 --model lyria-3.x 这条 HTTP 后端必需的")
    if realtime:
        prompts = [(t, max(0.1, round(1.0 - 0.1 * i, 1)))
                   for i, t in enumerate(args.prompt or [])]
        if not prompts:
            sys.exit("至少给一个 --prompt（realtime 后端吃加权短词）")
        from google.genai.types import Scale, MusicGenerationMode
        cfg = dict(bpm=args.bpm, density=args.density, brightness=args.brightness,
                   mute_drums=True, scale=Scale.A_MAJOR_G_FLAT_MINOR,
                   music_generation_mode=MusicGenerationMode.QUALITY)
        print(f"[lyria] {args.model} 采集 {args.duration:g}s · "
              f"{' + '.join(f'{t}({w})' for t, w in prompts)}")
        pcm = asyncio.run(_capture_realtime(key, args.model, prompts, cfg, args.duration))
        return pcm, True
    print(f"[lyria] {args.model} 一次性生成")
    return _capture_http(key, args.model, args.text, args.prompt, None, args.duration), False


GEN = {"lyria": _gen_lyria}


# ---------------------------------------------------------------- 解码与实测

def _to_pcm(payload: bytes) -> bytes:
    """自带容器的音频（lyria HTTP 后端）不能当裸 PCM 用。

    统一先用 _tool("ffmpeg") 解码到本脚本的约定格式；解不动说明响应形状与假设
    不符，该响亮失败而不是静默出废文件。
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".audio") as t:
        t.write(payload)
        t.flush()
        d = subprocess.run([_tool("ffmpeg"), "-v", "error", "-i", t.name,
                            "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS),
                            "pipe:1"], capture_output=True, timeout=300)
    if d.returncode != 0 or not d.stdout:
        sys.exit("供应商音频解码失败（端点形状与假设不符——lyria HTTP "
                 "这几条通路从未实测过，请把上面的报错留存）：\n"
                 + d.stderr.decode(errors="replace")[:300])
    return d.stdout


def measure(path: Path) -> dict:
    """时长 / RMS / 峰值。volumedetect 与 loudnorm 的输出都在 info 级，别加 -v error。"""
    r = subprocess.run([_tool("ffmpeg"), "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True,
                       timeout=300)
    rms = re.search(r"mean_volume: (-?[\d.inf]+) dB", r.stderr)
    peak = re.search(r"max_volume: (-?[\d.inf]+) dB", r.stderr)
    dur = subprocess.run([_tool("ffprobe"), "-v", "quiet", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True,
                         timeout=60).stdout.strip()
    f = lambda m: float(m.group(1)) if m else None
    return {"duration_s": round(float(dur), 3), "rms_dbfs": f(rms),
            "peak_dbfs": f(peak)}


def est_bpm(pcm: bytes, rate: int) -> float | None:
    """起始包络自相关估拍。用来反查「按 48 kHz 解读」这个假设（见模块头）。"""
    import numpy as np
    # 尾巴上不完整的帧丢掉（奇数字节、或奇数个样点都过不了 reshape(-1, 2)）
    pcm = pcm[:(len(pcm) // 2 // CHANNELS) * CHANNELS * 2]
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if x.size < rate:                                    # 不到 1 秒，谈不上拍
        return None
    x = x.reshape(-1, CHANNELS).mean(axis=1)
    hop = 512
    n = x.size // hop
    env = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2))
                    for i in range(n)], dtype=np.float32)
    onset = np.maximum(0.0, np.diff(env, prepend=env[0]))
    onset -= onset.mean()
    if not np.any(onset):
        return None
    fps = rate / hop
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 50)       # 只看 50–200 BPM
    if hi >= onset.size:
        return None
    corr = np.correlate(onset, onset, mode="full")[onset.size - 1:]
    k = lo + int(np.argmax(corr[lo:hi]))
    return round(60.0 * fps / k, 1)


def _verify_rate(measured_bpm: float | None, want_bpm: int) -> str:
    """用拍速反查「按 48 kHz 解读」这个假设。

    两种病因必须分开：**采样率读错**（文件整体变调，致命）和**模型没照 bpm 走**
    （Lyria RealTime 把 bpm 当软提示，音乐本身没毛病）。混为一谈就会把好曲子
    当坏文件扔掉。所以先认「按文档的 48 kHz 直读」，直读对不上才去问
    「有没有某个采样率误读的换算比能解释它」——顺序反过来会误杀。
    """
    if measured_bpm is None:
        return "inconclusive（起始包络过弱，测不出拍速）——请人耳确认音高正常"
    folds = (want_bpm, want_bpm * 2, want_bpm / 2)
    # 先认直接解读：48 kHz 是模型卡声明、且 L≠R（真立体声）佐证过的格式。
    # 顺序反了会误杀——0.9188 与 1.0 相差很小，两个分支可能同时「解释」同一个拍速，
    # 先查换算比就会把本来正常的文件判成 MISMATCH（实测踩过：175.8 BPM 同时落进
    # 「直接 168±5%」和「÷1.0884 后 161.5≈168」两个分支）。
    for cand in folds:
        if abs(measured_bpm - cand) <= cand * 0.05:
            return (f"ok（实测 {measured_bpm} BPM 命中请求 {want_bpm:g} 的 "
                    f"{cand / want_bpm:g} 倍，48 kHz 解读可信）")
    for ratio in RATE_RATIOS:                     # 48k↔44.1k 之间读错
        for got in (measured_bpm / ratio, measured_bpm * ratio):
            for cand in folds:
                if abs(got - cand) <= cand * 0.05:
                    return (f"MISMATCH：实测 {measured_bpm} BPM 对不上 {want_bpm:g}，"
                            f"但换算比 {ratio:.4f} 后 ≈ {got:.0f} BPM —— "
                            f"采样率解读很可能错了，**不要用这个文件**")
    return (f"inconclusive：实测 {measured_bpm} BPM 离请求 {want_bpm:g} 远，"
            f"也套不上 48k↔44.1k 的换算比——更像模型没照 bpm 走"
            f"（Lyria RealTime 把 bpm 当软提示）；拍速法判不了采样率，请人耳确认音高。")


def band_share(path: Path, seconds: float = 15.0) -> dict:
    """前若干秒的能量频段分布。"""
    import numpy as np
    with wave.open(str(path)) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        frames = min(w.getnframes(), int(sr * seconds))   # readframes 数的是帧，不是样点
        x = np.frombuffer(w.readframes(frames), dtype="<i2").astype(np.float32) / 32768
    x = x.reshape(-1, ch).mean(axis=1)
    if x.size < sr:
        return {}
    S = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    fr = np.fft.rfftfreq(x.size, 1 / sr)
    p = S ** 2
    tot = p.sum() or 1.0
    bands = {"<100": (0, 100), "100-400": (100, 400), "400-1k": (400, 1000),
             "1k-3k": (1000, 3000), ">3k": (3000, sr / 2)}
    return {k: round(float(p[(fr >= lo) & (fr < hi)].sum() / tot * 100), 2)
            for k, (lo, hi) in bands.items()}


def tonal_verdict(bands: dict) -> str:
    """床的「亮不亮」判据。

    实测踩过的坑：稀疏提示词 + brightness 0.4 会让 Lyria RealTime 吐一条
    **低频嗡鸣**——>3 kHz 只剩 0.1%、70% 能量压在 60–100 Hz，戴着耳机也听不出来
    （旁白盖住了），但混音后床等于没有。配器不对要靠频段占比判，不能靠「听」。
    """
    if not bands:
        return "inconclusive（不足 1 秒，测不了）"
    body = bands["400-1k"] + bands["1k-3k"]
    if bands[">3k"] < 1.0 and bands["<100"] > 45:
        return (f"⚠ 太暗：>3 kHz 仅 {bands['>3k']}%、<100 Hz 占 {bands['<100']}%"
                f"——多半提示词把模型带成了低音嗡鸣；调高 brightness/密度后重生成")
    if body < 3.0:
        return f"⚠ 中高频偏少（400 Hz–3 kHz 共 {body:.1f}%），床会听着发闷"
    return f"ok（400 Hz–3 kHz 共 {body:.1f}%，>3 kHz {bands['>3k']}%）"


def _is_realtime_pcm(provider: str, model: str | None) -> bool:
    """只有 Lyria 实时后端回裸 PCM；其余自带容器。"""
    return provider == "lyria" and model == "lyria-realtime-exp"


# ---------------------------------------------------------------- 主流程

def _recheck(out: Path, side: Path, narration_db: float | None,
             target_db: float) -> int:
    """按现有边车重算判据并回写。

    判据会演进（实测踩坑就会改），但音乐不必为改判据重生成一次——Lyria
    RealTime 不接受 seed，重生成拿到的也是另一首。边车里的结论是**推出来的**，
    推论的前提变了就该重推，不该手改。
    """
    if not (out.is_file() and side.is_file()):
        sys.exit(f"{out} 或边车不存在，没什么可复核的")
    rec = json.loads(side.read_text("utf-8"))
    if "bpm_requested" not in rec or "model" not in rec:
        sys.exit(f"{side} 缺 bpm_requested/model——它可能不是本脚本写的，"
                 "或是旧版边车；没有这两个前提判据推不出来")
    if narration_db is None:
        env = os.environ.get("NARRATION_RMS_DB")
        narration_db = float(env) if env else None
    rec["measured"] = measure(out)
    with wave.open(str(out), "rb") as w:
        pcm = w.readframes(w.getnframes())
    rec["bpm_detected"] = est_bpm(pcm, RATE)
    rec["rate_check"] = (_verify_rate(rec["bpm_detected"], rec["bpm_requested"])
                         if _is_realtime_pcm(rec.get("provider", "lyria"), rec["model"])
                         else "n/a（自带容器，采样率由音频头决定）")
    bands = band_share(out)
    rec["band_share_pct"] = bands
    rec["tonal_check"] = tonal_verdict(bands)
    if narration_db is not None:
        rec["suggested_gain"] = round(10 ** ((narration_db - target_db
                                             - rec["measured"]["rms_dbfs"]) / 20), 4)
        rec["gain_basis"] = (f"旁白 {narration_db:g} dBFS − 目标 {target_db:g} dB"
                             f" − 床 {rec['measured']['rms_dbfs']} dBFS")
    side.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"\n  {out.name}  {rec['measured']['duration_s']}s  "
          f"RMS {rec['measured']['rms_dbfs']} dBFS")
    print(f"  拍速反查：{rec['rate_check']}")
    print(f"  配器判据：{rec['tonal_check']}")
    if "suggested_gain" in rec:
        print(f"  → gain {rec['suggested_gain']}（{rec['gain_basis']}）")
    blocked = str(rec["rate_check"]).startswith("MISMATCH") or "⚠" in rec["tonal_check"]
    return 2 if blocked else 0


def _list_providers(env_file: Path | None) -> int:
    """只做凭据探测，不动网络——auto 之前先看一眼哪条线通。"""
    got = detect_providers()
    print("供应商凭据探测（探测顺序 = auto 顺延顺序）：")
    for p in PROVIDERS:
        hit = next((src for name, src in got if name == p), None)
        state = f"✓ {hit}" if hit else "✗ 无凭据"
        print(f"  {p:8s} {state}")
    if env_file:
        print(f"  key 文件已加载：{env_file}")
    else:
        print(f"  key 文件：{_key_file()}（不存在或没可解析行；"
              "样例见 skills/bgm-bed/references/keys.env.sample）")
    if not got:
        print("\n没有可用的供应商凭据：\n"
              "  lyria    GEMINI_API_KEY（或 ~/.gemini_api_key）——实测过，免费层可用\n"
              f"统一配置：把 key 写进 {_key_file()}（环境变量优先于该文件）")
        return 1
    print(f"\nauto 将按此顺序尝试：{' → '.join(n for n, _ in got)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="生成成片用的纯器乐 BGM 床（多供应商）")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出 wav（<out>.json 同名边车；--list-providers 时可省）")
    ap.add_argument("--provider", choices=("auto", *PROVIDERS), default="auto",
                    help="auto=按凭据探测顺序哪个能用用哪个，失败顺延（默认）")
    ap.add_argument("--prompt", action="append", default=None,
                    help="提示词，可重复（lyria 实时后端当加权短词，权重 1.0 起每个递减 0.1，下限 0.1；其余后端拼接成字符串）")
    ap.add_argument("--text", help="整段提示词（lyria HTTP 后端必需；其余后端优先于 --prompt）")
    ap.add_argument("--model", default=None,
                    help="供应商内选型：lyria 默认 lyria-realtime-exp")
    ap.add_argument("--duration", type=float, default=62.0,
                    help="时长（秒）：lyria 实时=采集秒数（床长判据照常验收）")
    ap.add_argument("--bpm", type=int, default=72)
    ap.add_argument("--density", type=float, default=0.6, help="0–1，床要疏不要满（lyria 实时后端）")
    ap.add_argument("--brightness", type=float, default=0.4, help="lyria 实时后端")
    ap.add_argument("--narration-rms-db", type=float,
                    help="旁白实测 RMS（dBFS）；给了就反推该写进 video.json 的 gain")
    ap.add_argument("--target-under-db", type=float, default=16.0,
                    help="床比旁白低多少 dB（默认 16，落在两条成片线的 15–18 区间）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的定稿文件")
    ap.add_argument("--recheck", action="store_true",
                    help="不生成，只按现有边车重算判据并回写（判据演进后省一次调用）")
    ap.add_argument("--list-providers", action="store_true",
                    help="只探测各供应商凭据并退出（不动网络）")
    args = ap.parse_args()

    if args.list_providers:
        return _list_providers(load_env_file())
    if args.out is None:
        sys.exit("--out 必填（--list-providers 除外）")
    load_env_file()

    out = args.out.expanduser().resolve()
    side = out.with_suffix(out.suffix + ".json")
    if args.recheck:
        return _recheck(out, side, args.narration_rms_db, args.target_under_db)
    for p in (out, side):
        if p.exists() and not args.force:
            sys.exit(f"{p} 已存在；生成类命令默认不覆盖（纪律 13）。确要覆盖加 --force")

    # lyria 的实时后端是免费层唯一通路，其缺省选型不能因为供应商重构漂移
    if args.provider == "lyria" and args.model is None:
        args.model = "lyria-realtime-exp"

    if not (args.prompt or args.text):
        sys.exit("至少给一个 --prompt 或一段 --text——lyria 要提示词")

    if args.provider == "auto":
        order = [n for n, _ in detect_providers()]
        if not order:
            sys.exit("auto 模式没有任何可用凭据。跑 --list-providers 看各供应商需要哪把 key")
    else:
        order = [args.provider]

    failures = []
    pcm = None
    provider = None
    for prov in order:
        if prov == "lyria" and args.model is None:
            args.model = "lyria-realtime-exp"
        try:
            audio, raw_pcm = GEN[prov](args)
            pcm = audio if raw_pcm else _to_pcm(audio)
            provider = prov
            break
        except ProviderError as e:
            failures.append((prov, str(e)))
            if args.provider == "auto":
                print(f"  [{prov}] 失败 → 顺延下一个供应商")
            else:
                print(f"FAIL：[{prov}] {e}")
                return 1
    if provider is None:
        print("\nFAIL：所有供应商都没出床：")
        for prov, msg in failures:
            print(f"  [{prov}] {msg}")
        return 1

    if len(pcm) < rate_guard_bytes():
        sys.exit(f"收到的音频只有 {len(pcm)} 字节（不足 2 秒），不成曲——"
                 "多半是配额/网络问题，重试")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(WIDTH)
        w.setframerate(RATE)
        w.writeframes(pcm)

    m = measure(out)
    bpm_seen = est_bpm(pcm, RATE)
    realtime = _is_realtime_pcm(provider, args.model)
    verdict = (_verify_rate(bpm_seen, args.bpm) if realtime
               else "n/a（自带容器，采样率由音频头决定）")
    bands = band_share(out)
    tonal = tonal_verdict(bands)
    if not realtime and m["duration_s"] + 1 < args.duration:
        print(f"⚠ 成曲只有 {m['duration_s']}s < 请求 {args.duration:g}s——"
              f"挂床前先确认它 ≥ 成片时长，否则尾部会裸奔")

    model = args.model or {"lyria": "lyria-realtime-exp"}[provider]
    rec = {"provider": provider, "model": model, "prompts": args.prompt or [],
           "text": args.text, "bpm_requested": args.bpm,
           "duration_requested_s": args.duration,
           "format": {"rate": RATE, "channels": CHANNELS, "bit_depth": WIDTH * 8},
           "measured": m, "bpm_detected": bpm_seen, "rate_check": verdict,
           "band_share_pct": bands, "tonal_check": tonal}

    if m["rms_dbfs"] is not None and args.narration_rms_db is not None:
        gain = 10 ** ((args.narration_rms_db - args.target_under_db - m["rms_dbfs"]) / 20)
        rec["suggested_gain"] = round(gain, 4)
        rec["gain_basis"] = (f"旁白 {args.narration_rms_db:g} dBFS − 目标 "
                             f"{args.target_under_db:g} dB − 床 {m['rms_dbfs']:g} dBFS")

    side.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print(f"\n  {out.name}  [{provider}]  {m['duration_s']}s  RMS {m['rms_dbfs']} dBFS  "
          f"峰值 {m['peak_dbfs']} dBFS")
    print(f"  拍速反查：{verdict}")
    print(f"  频段分布：{'  '.join(f'{k} {v}%' for k, v in bands.items()) or 'n/a'}")
    print(f"  配器判据：{tonal}")
    if "suggested_gain" in rec:
        print(f"  → video.json 写 \"gain\": {rec['suggested_gain']}"
              f"（{rec['gain_basis']}）")
    print(f"  边车：{side}")
    # 判据不通过要让**退出码**说话。文件照样落盘供排查，但「打印了警告却返回 0」
    # 就是纪律 12 说的那种假绿灯——上层脚本会把它当成功继续往下走。
    blocked = verdict.startswith("MISMATCH") or tonal.startswith("⚠")
    if blocked:
        print(f"\nFAIL：{'；'.join(x for x in (verdict, tonal) if '⚠' in x or x.startswith('MISMATCH'))}")
        print("      文件已落盘供排查，但**不要**把它挂进 video.json。")
        return 2
    return 0


def rate_guard_bytes() -> int:
    """低于 2 秒的数据一律当失败——省得把半截断流当成功交出去。"""
    return RATE * CHANNELS * WIDTH * 2


if __name__ == "__main__":
    sys.exit(main())
