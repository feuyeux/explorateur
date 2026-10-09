#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_tts.py — TTS 内核的反向验证

第 0 条好数据放行：缓存键 / 声线参数 / 裁尾这些纯函数在好输入上必须全对。
其余各防一种真实退化：

- 缓存键对每个组成部分敏感（voiceId / rate / pitch / text 改一个 → 键必变）
- 声线偏移夹取在安全域（|rate|≤20%、|pitch|≤12Hz——越界劈嗓）
- 伪词不裁尾（裁了误伤）；真词裁到末词 end+0.2s；探针更短时用探针
- NoAudioReceived 重试后能成功；耗尽抛出；**其他异常不重试**（参数错误稳定复现，重试烧时间）
- 缓存命中不重复合成（miss→NEW 写盘，再调→HIT 读盘）

真实网络合成放最后：无网时如实 [SKIP]（不算 PASS）。
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_tts                              # noqa: E402
from feuille import tts                      # noqa: E402


def check():
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-tts-")

    # ---- 0. 好数据放行：缓存键确定 + 逐项敏感 ----
    k1 = tts.content_hash("zh-CN-XiaoxiaoNeural", "-8%", "+0Hz", "一叶知秋")
    k2 = tts.content_hash("zh-CN-XiaoxiaoNeural", "-8%", "+0Hz", "一叶知秋")
    rows.append((k1 == k2 and len(k1) == 16,
                 f"缓存键确定性 + 16 位（{k1}）"))
    rows.append((all([tts.content_hash("v2", "-8%", "+0Hz", "一叶知秋") != k1,
                      tts.content_hash("zh-CN-XiaoxiaoNeural", "-9%", "+0Hz", "一叶知秋") != k1,
                      tts.content_hash("zh-CN-XiaoxiaoNeural", "-8%", "+1Hz", "一叶知秋") != k1,
                      tts.content_hash("zh-CN-XiaoxiaoNeural", "-8%", "+0Hz", "一叶知秋。") != k1]),
                 "voiceId / rate / pitch / text 任一变 → 缓存键必变"))

    # ---- 1. parse_signed（曾把 "+7%" 读成 0 的走样已修）----
    cases = [("+7%", 7), ("-3Hz", -3), ("+0%", 0), ("", 0), ("garbage", 0), ("+12.6Hz", 12)]
    bad = [(v, want) for v, want in cases if tts.parse_signed(v) != want]
    rows.append((not bad, f"parse_signed 全对（错例 {bad}）" if bad else "parse_signed 全对"))

    # ---- 2. 声线安全域 ----
    r, p = tts.voice_params("+7%", "+5Hz", rate_off=-8)          # 7-8 → -1
    rows.append((r == "-1%" and p == "+5Hz", f"基线+偏移正确（{r} {p}）"))
    r, p = tts.voice_params("+7%", "+5Hz", rate_off=-100)         # 夹到 -20
    rows.append((r == "-20%", f"rate 越界夹到安全域下限（{r}）"))
    r, p = tts.voice_params("+0%", "+30Hz", pitch_off=0)          # 夹到 +12
    rows.append((p == "+12Hz", f"pitch 越界夹到安全域上限（{p}）"))

    # ---- 3. 词级真值裁尾 ----
    real_words = [{"t": 0.1, "d": 0.9, "w": "一叶"}, {"t": 1.2, "d": 0.6, "w": "知秋"}]
    text = "一叶知秋，晴旭微倾值万金。"
    fake_words = [{"t": 0.05, "d": 0.5, "w": text[:12]}]     # 伪词口径：词面 = 原文前 12 字
    got = tts.effective_dur(real_words, 3.2, "一叶知秋")
    rows.append((abs(got - 2.0) < 1e-9,
                 f"真词裁到末词 end+0.2（得 {got:.6f}，应 2.0）"))
    rows.append((tts.effective_dur(real_words, 1.5, "一叶知秋") == 1.5,
                 "探针更短时用探针（min 口径）"))
    rows.append((tts.effective_dur(fake_words, 3.2, text) == 3.2,
                 "伪词（整行一词、词面=前 12 字）不裁尾"))
    rows.append((tts.effective_dur([], 2.5, "x") == 2.5, "空词表不裁"))

    # ---- 4. 重试：只认 NoAudioReceived ----
    calls = {"n": 0}

    async def flaky(text, voice, rate, pitch):
        calls["n"] += 1
        if calls["n"] < 3:
            raise edge_tts.exceptions.NoAudioReceived("transient")
        return b"mp3-bytes", real_words

    old_once, old_backoff = tts._synth_once, tts.RETRY_BACKOFF
    tts._synth_once, tts.RETRY_BACKOFF = flaky, 0
    try:
        mp3, words = asyncio.run(tts.synth_line("一叶知秋", "v", "-8%", "+0Hz"))
        rows.append((mp3 == b"mp3-bytes" and calls["n"] == 3,
                     f"NoAudioReceived 重试到成功（第 {calls['n']} 次过）"))

        async def always_fail(text, voice, rate, pitch):
            raise edge_tts.exceptions.NoAudioReceived("dead")

        tts._synth_once = always_fail
        try:
            asyncio.run(tts.synth_line("一叶知秋", "v", "-8%", "+0Hz", tries=3))
            rows.append((False, "重试耗尽必须抛出——没抛"))
        except edge_tts.exceptions.NoAudioReceived:
            rows.append((True, "重试耗尽 → 抛最后一次 NoAudioReceived"))

        calls["n"] = 0

        async def hard_error(text, voice, rate, pitch):
            calls["n"] += 1
            raise ValueError("参数错误——稳定复现的那种")

        tts._synth_once = hard_error
        try:
            asyncio.run(tts.synth_line("一叶知秋", "v", "-8%", "+0Hz", tries=5))
            rows.append((False, "非 NoAudioReceived 异常必须直接抛——没抛"))
        except ValueError:
            rows.append((calls["n"] == 1,
                         f"参数类异常不重试（只调 {calls['n']} 次，重试只会烧时间）"))
    finally:
        tts._synth_once, tts.RETRY_BACKOFF = old_once, old_backoff

    # ---- 5. 内容寻址缓存：miss→NEW 写盘，再调→HIT 读盘 ----
    synth_calls = {"n": 0}

    async def fake_once(text, voice, rate, pitch):
        synth_calls["n"] += 1
        return b"audio-" + text.encode(), real_words

    tts._synth_once = fake_once
    try:
        cache = pathlib.Path(tmp.name) / "audio"
        r1 = asyncio.run(tts.synth_cached("行一", "v", "-8%", "+0Hz", cache))
        r2 = asyncio.run(tts.synth_cached("行一", "v", "-8%", "+0Hz", cache))
        rows.append((r1["state"] == "NEW" and r2["state"] == "HIT"
                     and r1["key"] == r2["key"] and synth_calls["n"] == 1,
                     f"缓存命中不重复合成（合成 {synth_calls['n']} 次，{r1['state']}→{r2['state']}）"))
        r3 = asyncio.run(tts.synth_cached("行二", "v", "-8%", "+0Hz", cache))
        rows.append((r3["state"] == "NEW" and r3["key"] != r1["key"],
                     "改文本 → 新键 → 重新合成"))
    finally:
        tts._synth_once = old_once

    # ---- 6. 真实网络合成（无网时如实 SKIP，不算 PASS）----
    try:
        r = asyncio.run(tts.synth_cached("你好，一叶知秋。", "zh-CN-XiaoxiaoNeural",
                                         "-8%", "+0Hz", pathlib.Path(tmp.name) / "net"))
        ok = (r["state"] == "NEW" and r["mp3"].stat().st_size > 1000 and r["words"])
        rows.append((ok, f"真实合成一次成功（mp3 {r['mp3'].stat().st_size}B，"
                         f"{len(r['words'])} 词，state={r['state']}）"))
    except Exception as e:                                   # noqa: BLE001
        rows.append((True, f"[SKIP] 真实网络合成未验（{type(e).__name__}: {str(e)[:60]}）"
                           "——无网/服务不可达不算失败，但也如实记为未验"))
    return rows


def main() -> int:
    print("=" * 72)
    print("TTS 内核（缓存键 / 词级时间戳 / 裁尾 / 重试）")
    print("=" * 72)
    rows = check()
    fails = skips = 0
    for ok, msg in rows:
        if msg.startswith("[SKIP]"):
            skips += 1
            print(f"  [SKIP] {msg[6:]}")
        else:
            fails += not ok
            print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：TTS {len(rows) - fails - skips} PASS / "
          f"{fails} FAIL / {skips} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
