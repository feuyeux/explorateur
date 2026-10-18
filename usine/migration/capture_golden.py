# -*- coding: utf-8 -*-
"""capture_golden.py — TS 迁移金样本采集（迁移工具，P7 清场时随 migration/ 一并退役）

用途：在 Python 引擎还活着的时候，把各模块对 canonical 语料的输出落盘成
金样本（migration/golden/）。TS 侧以此为 parity 判据：

- 纯函数（缓存键 / 滤镜图 / 时间轴 / HTML 模板）→ **逐字节对齐**
- 环境相关（视口亏空 / 像素 / 时长）→ 带机桶元数据，断**结构与几何**

用法：uv run python migration/capture_golden.py [tts|audio|timeline|textlayer|all]
"""
from __future__ import annotations

import hashlib
import json
import platform as _sysplatform
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

GOLDEN = Path(__file__).resolve().parent / "golden"
ASSETS = GOLDEN / "assets"


def _meta() -> dict:
    from feuille import platform as pt
    meta = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "machine": f"{_sysplatform.system()}/{_sysplatform.machine()}",
        "python": sys.version.split()[0],
        "browser": str(pt.browser()),
        "ffmpeg": pt.ffmpeg(),
        "ffprobe": pt.ffprobe(),
    }
    try:
        import edge_tts
        meta["edge_tts"] = getattr(edge_tts, "__version__", "unknown")
    except Exception:
        pass
    return meta


def _save(name: str, payload: dict) -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    out = {"_meta": _meta(), "data": payload}
    (GOLDEN / f"{name}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(f"[golden] {name}.json 已落盘")


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# --------------------------------------------------------------------- tts

TTS_TEXTS = [
    ("zh-CN-XiaoxiaoNeural", "落叶知秋，岁月如歌。"),
    ("zh-CN-YunxiNeural", "一条轰鸣着机器的工厂。"),
    ("en-US-AriaNeural", "The wind rises, and the leaves remember."),
]


def capture_tts() -> None:
    import asyncio
    from feuille import tts

    data: dict = {}

    # 纯函数：内容寻址缓存键（口径不许变——TS 必须逐字节复现同一 sha256 口径）
    data["content_hash"] = [
        {"parts": [v, r, p, t], "key": tts.content_hash(v, r, p, t)}
        for v, t in TTS_TEXTS for r in ("+0%", "+8%", "-12%") for p in ("+0Hz", "-4Hz")
    ]
    data["parse_signed"] = [
        {"v": v, "out": tts.parse_signed(v)}
        for v in ("+7%", "-3Hz", "", "12%Hz", "garbage", "  +12  ", "12H", "12z", "-20%", "0")
    ]
    data["voice_params"] = [
        {"base_rate": br, "base_pitch": bp, "rate_off": ro, "pitch_off": po,
         "out": list(tts.voice_params(br, bp, ro, po))}
        for br, bp in (("+0%", "+0Hz"), ("+8%", "-3Hz"), ("-15%", "+12Hz"), ("bad", "bad"))
        for ro, po in ((0, 0), (-8, 0), (10, 5), (-30, -30))
    ]
    data["is_fake_word"] = [
        {"words": w, "text": t, "out": tts.is_fake_word(w, t)}
        for w, t in (
            ([{"t": 0.05, "d": 0.5, "w": "落叶知秋，岁月如歌。"[:12]}], "落叶知秋，岁月如歌。"),
            ([{"t": 0.1, "d": 0.4, "w": "落叶"}, {"t": 0.6, "d": 0.4, "w": "知秋"}], "落叶知秋"),
            ([{"t": 0.05, "d": 0.5, "w": "别的词面"}], "落叶知秋"),
        )
    ]
    data["effective_dur"] = [
        {"words": w, "probe": pd, "text": t, "out": tts.effective_dur(w, pd, t)}
        for w, pd, t in (
            ([{"t": 0.1, "d": 0.4, "w": "落叶"}, {"t": 0.6, "d": 0.4, "w": "知秋"}], 3.2, "落叶知秋"),
            ([{"t": 0.05, "d": 0.5, "w": "落叶知秋，岁月如歌。"[:12]}], 3.2, "落叶知秋，岁月如歌。"),
            ([], 2.8, "空词表"),
        )
    ]

    # 真合成（免费服务）：词级时间戳 + mp3 落盘。服务端输出可能随时间漂，
    # 词表作**语义**参照（词数/词面/单调时间轴），mp3 哈希作机桶内参照。
    synth = []
    ASSETS.mkdir(parents=True, exist_ok=True)
    cache = ASSETS / "tts-cache"

    async def run():
        for voice, text in TTS_TEXTS:
            r = await tts.synth_cached(text, voice, "+0%", "+0Hz", cache)
            from feuille.audio import probe_duration
            synth.append({
                "voice": voice, "text": text, "key": r["key"], "state": r["state"],
                "words": r["words"],
                "mp3_sha256": _sha(r["mp3"]),
                "mp3_bytes": Path(r["mp3"]).stat().st_size,
                "probe_duration": round(probe_duration(r["mp3"]), 3),
            })
    asyncio.run(run())
    data["synth"] = synth
    _save("tts", data)


# ------------------------------------------------------------- tts split
# 4096 字节分片是 edge-tts 7.3.1 的字节级算法（换行>空格>UTF-8 安全点>& 实体
# 调整），跨语言逐字节可对齐——含上游 quirk（无分隔符长文本的安全切点在整段
# 剩余文本上求，可能产出超限单块）：按行为钉住，不"顺手修"。

def capture_tts_split() -> None:
    import base64 as b64mod
    from edge_tts.communicate import split_text_by_byte_length

    corpus = [
        ("long_ascii_spaces", "word " * 1200, 4096),             # 空格优先
        ("long_ascii_newlines", "line of text\n" * 400, 4096),   # 换行优先于空格
        ("long_ascii_nospace", "a" * 9000, 4096),                # 无分隔 → 超限单块 quirk
        ("chinese", "落叶知秋，岁月如歌。" * 300, 4096),           # 多字节边界
        ("arabic", "أوراق الخريف تتناثر في الريح. " * 200, 4096),
        ("entity_amp", "cat &amp; dog; " * 500, 4096),           # 实体整体不被切断
        ("entity_raw", "a & b & c; d & e", 4),                   # & 调整到 0 → 前进 1
        ("small", "落叶知秋", 4096),                               # 单段 + strip
        ("padded", "   \n\t 落叶知秋  \r\n ", 4096),               # 首尾空白剥除
        ("tiny_limit", "落叶知秋，岁月如歌。", 16),                 # 极小限长（多字节切点）
    ]
    data = {"cases": []}
    for label, text, limit in corpus:
        chunks = list(split_text_by_byte_length(text, limit))
        data["cases"].append({
            "label": label, "text": text, "byte_length": limit,
            "chunks_b64": [b64mod.b64encode(c).decode("ascii") for c in chunks],
            "chunk_bytes": [len(c) for c in chunks],
        })
    _save("tts_split", data)


# ------------------------------------------------------------------- audio

def capture_audio() -> None:
    from feuille import audio

    data: dict = {}
    data["filter_graph"] = [
        {"n": 1, "starts": [0.0], "dur": 10.0, "loudness_i": -16,
         "out": audio.filter_graph(1, [0.0], 10.0)},
        {"n": 2, "starts": [0.0, 1.5], "dur": 12.5, "loudness_i": -16,
         "out": audio.filter_graph(2, [0.0, 1.5], 12.5)},
        {"n": 3, "starts": [0.0, 2.0, 4.0], "dur": 15.0, "loudness_i": -14,
         "out": audio.filter_graph(3, [0.0, 2.0, 4.0], 15.0, -14)},
    ]
    # 对金样本 mp3 实测时长（ffmpeg 版本进元数据；同桶内确定性）
    cache = ASSETS / "tts-cache"
    durs = {}
    for p in sorted(cache.glob("*.mp3")):
        durs[p.name] = round(audio.probe_duration(p), 3)
    data["probe_duration"] = durs
    _save("audio", data)


# ---------------------------------------------------------------- timeline

def capture_timeline() -> None:
    from feuille import timeline

    data: dict = {}
    data["compute_starts"] = [
        {"speech_durs": d, "gap": g, "out": timeline.compute_starts(d, g)}
        for d, g in (
            ([1.2, 0.8, 2.0], 0.35),
            ([], 0.5),
            ([3.3], 0.5),
            ([1.0, 1.0, 1.0, 1.0], 0.0),
        )
    ]
    line = {
        "start": 2.5, "dur": 2.4,
        "words": [{"s": 2.5, "e": 2.9, "w": "落叶"}, {"s": 2.9, "e": 3.4, "w": "知秋"},
                  {"s": 3.4, "e": 4.3, "w": "岁月"}],
    }
    pts = timeline.karaoke_points(line)
    data["karaoke_points"] = {"line": line, "out": pts}
    data["frac_at"] = [
        {"pts": pts, "t": t, "out": timeline.frac_at(pts, t)}
        for t in (0.0, 2.5, 2.7, 3.0, 3.45, 4.29, 4.9, 5.5, 99.0)
    ]
    # enrich_lines 用金样本 mp3 实测（键名即缓存键）
    from feuille import tts as _t
    from feuille.audio import probe_duration
    cache = ASSETS / "tts-cache"
    lines = []
    for voice, text in TTS_TEXTS:
        key = _t.content_hash(voice, "+0%", "+0Hz", text)
        words_p = cache / f"{key}.json"
        if not words_p.exists():
            continue
        words = json.loads(words_p.read_text("utf-8"))
        probe = round(probe_duration(cache / f"{key}.mp3"), 3)
        lines.append({"key": key,
                      "dur": round(_t.effective_dur(words, probe, text), 3),
                      "words": words})
    if lines:
        enriched = [dict(ln) for ln in lines]
        total, span = timeline.enrich_lines(enriched, 0.4, cache)
        data["enrich_lines"] = {"gap": 0.4, "lines_in": lines,
                                "lines_out": enriched, "total": total, "span": span}
    _save("timeline", data)


# --------------------------------------------------------------- textlayer

def capture_textlayer() -> None:
    from feuille import textlayer

    data: dict = {}
    # 纯函数：转义与整页 HTML（TS 逐字节对齐目标）
    data["html_escape"] = [
        {"s": s, "out": textlayer.html_escape(s)}
        for s in ('落叶知秋', 'a<b>&c>"d"', "أوراق الخريف", "plain")
    ]
    data["page"] = [
        {"w": w, "h": h, "body": body, "bg": bg, "font": font, "dir_": d,
         "out": textlayer.page(w, h, body, bg=bg, font=font, dir_=d)}
        for w, h, body, bg, font, d in (
            (480, 320, '<div style="font-size:64px">落叶知秋</div>', "#FFFFFF", "sans-serif", "ltr"),
            (480, 320, '<div style="font-size:48px">أوراق الخريف</div>', "#000000", "sans-serif", "rtl"),
        )
    ]
    # 视口亏空（机桶金样本：换机重采；本桶内作为 TS 复用同一浏览器的对照）
    vd = {}
    for ch in (300, 800):
        deficit, win_h = textlayer.viewport_deficit(ch, workdir=ASSETS)
        vd[str(ch)] = {"deficit": deficit, "win_h": win_h}
    data["viewport_deficit"] = vd

    # 像素金样本（机桶内）：不透明整图 + 透明层双 matte
    wd = ASSETS / "textlayer"
    wd.mkdir(parents=True, exist_ok=True)

    opaque_html = textlayer.page(
        480, 320, '<div style="font-size:64px;color:#1a3a8a">落叶知秋</div>', bg="#F5F0E6")
    opaque_png = wd / "opaque.png"
    textlayer.edge_screenshot(opaque_html, opaque_png, width=480, canvas_h=320, workdir=wd)
    data["opaque_shot"] = {
        "html": opaque_html, "png_sha256": _sha(opaque_png),
        "size": list(Image_size(opaque_png)),
    }

    def matte_html(bg: str) -> str:
        return textlayer.page(
            480, 320,
            '<div style="font-size:48px;color:#2b2b2b;text-shadow:0 2px 6px rgba(0,0,0,.35)">'
            'أوراق الخريف</div>', bg=bg, dir_="rtl")

    matte_png = wd / "matte.png"
    textlayer.shoot_matte(matte_html, matte_png, width=480, canvas_h=320, workdir=wd)
    stats = alpha_stats(matte_png)
    data["matte_shot"] = {
        "html_white": matte_html("#FFFFFF"), "html_black": matte_html("#000000"),
        "png_sha256": _sha(matte_png), "alpha_stats": stats,
    }
    _save("textlayer", data)


def Image_size(p):
    from PIL import Image
    with Image.open(p) as im:
        return im.size


def alpha_stats(p):
    """alpha 结构统计：覆盖率 / 非零 alpha 的均值与包围盒——TS parity 断结构与几何。"""
    import numpy as np
    from PIL import Image
    arr = np.asarray(Image.open(p).convert("RGBA"), dtype=np.uint8)
    a = arr[..., 3]
    nz = a > 0
    ys, xs = np.nonzero(nz)
    return {
        "size": [int(a.shape[1]), int(a.shape[0])],
        "coverage": round(float(nz.mean()), 5),
        "alpha_mean_nonzero": round(float(a[nz].mean()), 2),
        "alpha_max": int(a.max()),
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None,
    }


# ------------------------------------------------------------------ ledger
# _digest 是纯字节数学（sha256("v2" + "|label:sha" 逐段)），跨语言可逐字节对齐——
# 这是批次 2 的核心 parity 判据。夹具文件**内嵌**在金样本里（bytes_b64），
# TS 测试在临时目录重建同字节文件后复算，不依赖任何本机文件。

import base64 as _base64
import tempfile as _tempfile


def capture_ledger() -> None:
    from feuille import ledger

    fixtures = [
        ("mod_a.py", b"x = 1\n"),
        ("data_b.json", '{"a": 1, "\u4e2d\u6587": "\u843d\u53f6"}\n'.encode("utf-8")),
        ("bin.bin", bytes([0, 1, 2, 0x80, 0xFD, 0xFE, 0xFF, 10])),
    ]
    data: dict = {}
    with _tempfile.TemporaryDirectory(prefix="feuille-golden-ledger-") as td:
        d = Path(td)
        for name, content in fixtures:
            (d / name).write_bytes(content)
        parts = [("mod:a", d / "mod_a.py"), ("data:b", d / "data_b.json")]
        data["fixtures"] = [{"name": n, "bytes_b64": _base64.b64encode(c).decode("ascii")}
                            for n, c in fixtures]
        data["sha256"] = {n: ledger._sha(d / n) for n, _ in fixtures}
        data["digest"] = {
            "two_parts": ledger._digest(parts),
            "order_swapped": ledger._digest(list(reversed(parts))),
            "label_changed": ledger._digest([("zzz:a", d / "mod_a.py"),
                                             ("data:b", d / "data_b.json")]),
            "with_binary": ledger._digest(parts + [("data:bin", d / "bin.bin")]),
            "empty": ledger._digest([]),
            "missing": ledger._digest([("mod:a", d / "nope.py")]),
        }
        (d / "mod_a.py").write_bytes(b"x = 2\n")          # 改一个字节
        data["digest"]["one_byte_changed"] = ledger._digest(parts)
        (d / "mod_a.py").write_bytes(b"x = 1\n")
        data["digest"]["reproducible"] = ledger._digest(parts)
    _save("ledger", data)


# --------------------------------------------------------------- framehash
# classify / first_drift / 基线文件格式：纯函数 + 纯文本格式，逐字节可对齐。
# （framehash 本体依赖 ffmpeg 解码像素，按桶逐机重采，不进跨语言金样本。）

def capture_framehash() -> None:
    from feuille import framehash as fh

    data: dict = {}
    base = {"a.mp4": "MD5=aaa", "b.mp4": "MD5=bbb", "old.mp4": "MD5=dead"}
    cur = {"a.mp4": "MD5=aaa", "b.mp4": "MD5=ccc", "c.mp4": "MD5=ccc"}
    data["classify"] = {
        "base": base, "cur": cur,
        "full": fh.classify(base, cur, False),
        "subset": fh.classify(base, cur, True),
        "empty_base": fh.classify({}, cur, False),
    }
    frames_full = [f"MD5=f{i}" for i in range(15)]
    frames_mid = list(frames_full)
    frames_mid[7] = "MD5=xxx"
    frames_tail = frames_full[:12] + ["MD5=zzz", "MD5=zzz2"]
    data["first_drift"] = [
        {"ref": frames_full, "cur": frames_full,
         "out": list(fh.first_drift(frames_full, frames_full))},
        {"ref": frames_full, "cur": frames_mid,
         "out": list(fh.first_drift(frames_full, frames_mid))},
        {"ref": frames_full, "cur": frames_full[:9],
         "out": list(fh.first_drift(frames_full, frames_full[:9]))},
        {"ref": frames_full, "cur": frames_tail,
         "out": list(fh.first_drift(frames_full, frames_tail))},
    ]
    with _tempfile.TemporaryDirectory(prefix="feuille-golden-fh-") as td:
        b = fh.save_baseline({"b.mp4": "MD5=bbb", "a.mp4": "MD5=aaa",
                              "中文视频.mp4": "MD5=ccc"}, Path(td) / "base.txt")
        data["baseline_text"] = b.read_text("utf-8")
        data["baseline_roundtrip"] = fh.read_baseline(b)
    _save("framehash", data)


# -------------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    steps = {
        "tts": capture_tts, "tts_split": capture_tts_split,
        "audio": capture_audio,
        "timeline": capture_timeline, "textlayer": capture_textlayer,
        "ledger": capture_ledger, "framehash": capture_framehash,
    }
    todo = list(steps) if not argv else [a for a in argv]
    for name in todo:
        if name not in steps:
            print(f"unknown section: {name}", file=sys.stderr)
            return 2
        print(f"[capture] {name} ...")
        steps[name]()
    print("[done] golden 落盘于 migration/golden/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
