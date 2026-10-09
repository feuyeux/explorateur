# -*- coding: utf-8 -*-
"""tts.py — edge-tts 语音合成内核（⑤ 音频）

经验（全部实测过）：

- **WordBoundary**：edge-tts 7.2.8 默认只发 `SentenceBoundary`，
  必须传 `boundary="WordBoundary"` 才有词级时间戳。
- **尾部静音**：每请求垫 ~0.5–1.5s（实测 ~0.95s）静音。
  行时长 = `min(探针时长, 末词 end + 0.2s)`——词级真值裁尾。
- **伪词兜底**：无词边界事件的语言整行一个伪词 `{"t":0.05,"d":0.5,"w":text[:12]}`；
  **伪词不裁尾**（裁了会误伤）。
- **NoAudioReceived**：偶发、同文本重试即成功、相邻请求互相影响——服务端瞬时抖动
  （参数错误会**稳定复现**，可区分）。只按它重试 + 线性退避；其余异常照常抛。
- **语速语种差异大**（韩语比中文慢 5–29%）：处方是**放宽预算、不压台词**，
  预算检查卡在 TTS 这一步（改文本便宜）。
- **声线安全域**：|rate|≤20%、|pitch|≤12Hz——调预算不动声线。
- **内容寻址缓存**：`sha256(voiceId|rate|pitch|text)[:16]` 即文件名——
  改台词只重合成那行，改声线全员失效；miss 才请求。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import edge_tts

# 重试退避基数（秒，线性 × 尝试次数）。测试把它改 0，免得反向验证慢。
RETRY_BACKOFF = 1.2
RETRY_TRIES = 5

# 声线安全域：越界声音会破音、发机械声。
SAFE_RATE = (-20, 20)
SAFE_PITCH = (-12, 12)


def content_hash(*parts) -> str:
    """内容寻址缓存键：sha256("|".join(parts))[:16]。口径不许变——变了等于换缓存空间。"""
    return hashlib.sha256("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:16]


def parse_signed(v) -> int:
    """把 "+7%" / "-3Hz" 解析成整数偏移；空/垃圾输入 → 0（不猜）。

    口径：strip 后去尾部单位再转数。曾因在前导 `+` 上断循环把人设基线
    **静默读成 0**（12 语种全跑在项目偏移上，结果碰巧可用——那是运气不是设计），故以此为戒。
    """
    s = str(v).strip().rstrip("%Hz")
    try:
        return int(float(s))
    except ValueError:
        return 0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def voice_params(base_rate, base_pitch, rate_off: int = 0, pitch_off: int = 0) -> tuple[str, str]:
    """人设基线 + 项目偏移，夹取在安全域内，返回 edge-tts 的 rate/pitch 串。

    例：诗朗诵整体放缓 = 基线 +8%、偏移 -8 → 0%；再慢也要夹在 -20%。
    """
    r = clamp(parse_signed(base_rate) + rate_off, *SAFE_RATE)
    p = clamp(parse_signed(base_pitch) + pitch_off, *SAFE_PITCH)
    return f"{r:+d}%", f"{p:+d}Hz"


def is_fake_word(words: list[dict], text: str) -> bool:
    """伪词判定：整行只有一个词、且词面是文本前 12 字。
    伪词是兜底产物，裁尾与卡拉OK都要绕开它。"""
    return len(words) == 1 and words[0]["w"] == text[:12]


def effective_dur(words: list[dict], probe_dur: float, text: str) -> float:
    """行时长：词级真值裁尾 min(探针时长, 末词 end + 0.2s)；伪词不裁（裁了会误伤）。"""
    if not words or is_fake_word(words, text):
        return probe_dur
    end = words[-1]["t"] + words[-1]["d"]
    return min(probe_dur, end + 0.20)


async def _synth_once(text: str, voice: str, rate: str, pitch: str):
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    mp3 = bytearray()
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "t": chunk["offset"] / 1e7,
                "d": chunk["duration"] / 1e7,
                "w": chunk["text"],
            })
    if not words:  # 无词边界事件的语言：整行一个伪词兜底（见 effective_dur 的绕开逻辑）
        words = [{"t": 0.05, "d": 0.5, "w": text[:12]}]
    return bytes(mp3), words


async def synth_line(text: str, voice: str, rate: str, pitch: str,
                     tries: int = RETRY_TRIES) -> tuple[bytes, list[dict]]:
    """合成一行，返回 (mp3 字节, 词级时间戳)。

    只对 `NoAudioReceived` 重试（瞬时抖动；参数错误会稳定复现，重试无意义
    还烧时间），线性退避；其余异常第一次就抛。
    """
    last = None
    for attempt in range(1, tries + 1):
        try:
            return await _synth_once(text, voice, rate, pitch)
        except edge_tts.exceptions.NoAudioReceived as e:
            last = e
            if attempt < tries:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
    raise last


async def synth_cached(text: str, voice: str, rate: str, pitch: str,
                       cache_dir, tries: int = RETRY_TRIES) -> dict:
    """内容寻址缓存合成：`cache_dir/{key}.mp3` + `{key}.json`（词表）。

    命中（两个文件都在）直接复用；miss 才请求。返回
    `{key, mp3, words, state: "HIT"|"NEW"}`——state 供台账打印「N新/N命中」。
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = content_hash(voice, rate, pitch, text)
    mp3_p = cache_dir / f"{key}.mp3"
    meta_p = cache_dir / f"{key}.json"
    if mp3_p.exists() and meta_p.exists():
        return {"key": key, "mp3": mp3_p, "words": json.loads(meta_p.read_text("utf-8")),
                "state": "HIT"}
    mp3, words = await synth_line(text, voice, rate, pitch, tries)
    mp3_p.write_bytes(mp3)
    meta_p.write_text(json.dumps(words, ensure_ascii=False, indent=1), "utf-8")
    return {"key": key, "mp3": mp3_p, "words": words, "state": "NEW"}
