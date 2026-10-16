# -*- coding: utf-8 -*-
"""scene_audio.py — 场景课 TTS 叶子（④成片·语音线第一段）

`uv run feuille scene tts --scene <id>`：

    lessons/<id>/scene.json（先 parse）
      └─ 每语种逐台词行：班底 persona 声线（§0.4 roles 声明驱动选角，
         mood 增量查 scene 级 moodVoices，缺省 ±0 不猜）
      └─ feuille.tts.synth_cached（内容寻址缓存，改台词只重合成那行）
      └─ timeline.enrich_lines（gap=0.35s，词级真值裁尾；ffprobe 实测 file_dur）
      └─ build/scene/audio/scene-<sid>_<lc>.timeline.json（doctor ④ 查的产物）
         + 逐行 mp3（line-<i>.mp3，compose 线直接消费）

台账：ledger kind="scene-audio"、unit=<sid>/<lc>、
extra=(sid, scene.md sha16, gap)——scene.md 变 → 指纹变 → 该语种重做；
status_of 按**条目里记录的那份** extra 复算（账本自描述，调用方漏传不会永久误红）。

声线映射（与 scene_schema §8 选角可解同一条链）：**§0.4 roles 声明驱动**——
scene.json 顶层 roles 给每个角色声明 energy（如 {"A": "lively", "B": "steady"}），
本模块按 energy 在该语种班底里唯一解人。roles 是每课自己的声明，不是固定
A=活泼：A 声明 steady 的合法课照办（A 就配沉稳声线），第三角色 C 同理
（班底每语种恰一活泼一沉稳由 validate_roster 保证；两角色声明同一 energy =
同一个人配两个声线位）。aName/bName 与选角的一致性由 schema §8 保证，本模块
不看名字——曾经收了名字却不看，A=steady 的合法课会被静默换成活泼声线。
mood 增量表**缺省空**：edge-tts 的 rate/pitch 是声线安全域（±20%/±12Hz）内的
线性偏移，MOOD_FACE 只定义表情几何不定义声线——谁要把情绪接进声线，必须
显式给表（scene 级 moodVoices），本模块不发明默认值。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from pathlib import Path

from .data import LESSONS_DIR, personas, scene_doc
from .errors import FeuilleError
from .ledger import record, status_of
from .parse_scene import scene_paths
from .timeline import enrich_lines

# 行距（秒）：与 scripts/verify_timeline.py 的缺省口径一致（gap=0.35）。
LINE_GAP = 0.35

# 产物线注册：指纹只由「确实可能影响该产物」的东西构成——TTS 内核 + 时间轴 +
# 班底数据（voiceId/rate/pitch 都在 personas.json 里）+ 全部 scene.md（@glob，
# 不用索引文件当第二事实源）。工具链（python/pillow/浏览器/ffmpeg）由
# ledger.fingerprint 自动并入。
register_kind = "scene-audio"


def _register_line() -> None:
    from . import ledger
    ledger.register_line(
        register_kind,
        modules=("tts.py", "timeline.py", "audio.py"),
        data=("@lessons/*/scene.md", "personas/personas.json"),
    )


def _scene_root(lessons_dir) -> Path:
    """项目根 = lessons 目录上推一层（与 lesson.py doctor 同一条约定）。"""
    return Path(lessons_dir).resolve().parent if lessons_dir else LESSONS_DIR.parent


def _pick_cast(people: list[dict], roles: dict, locale: str) -> dict[str, dict]:
    """班底选角：§0.4 roles 声明驱动（role → energy → 该语种班底里唯一的人）。

    roles 是 scene.json 顶层 §0.4 的声明（schema 逐角色校验过 energy 合法、
    §8 保证选角人 native name == aName/bName）。每个角色都必须恰好解出一个人，
    取不到就显式报错，绝不静默回落。
    """
    by: dict[str, dict] = {}
    for role, energy in roles.items():
        cands = [p for p in people if p.get("energy") == energy]
        if len(cands) != 1:
            raise FeuilleError(
                f"{locale}: {role} 角按 energy={energy!r} 在班底解出 {len(cands)} 人"
                f"（应为恰 1；先跑 scene validate 对齐 §0.4/§0.6）")
        by[role] = cands[0]
    return by


def _mood_offset(mood: str, mood_voices: dict) -> tuple[int, int]:
    """情绪声线增量：(rate, pitch)。表里没有该 mood = ±0（不猜）。

    moodVoices 形状（scene.md §0 可选声明 / scene.json 透传）：
      {"happy": {"rate": 4, "pitch": 2}, "encouraging": {"rate": -2}}
    """
    m = mood_voices.get(mood) or {}
    return int(m.get("rate", 0)), int(m.get("pitch", 0))


def build_locale_timeline(doc: dict, lc: str, cache_dir: Path,
                          gap: float = LINE_GAP) -> dict:
    """单语种：逐行合成 → enrich_lines → timeline dict（不落盘，便于测试）。

    timeline dict 与 doctor ④ 查的文件一致：
    {locale, lines:[{i, speaker, mood, text, key, words, dur, speech_dur,
                     file_dur, tail_silence, start}], gap, totalDur, spanDur}
    """
    from .tts import parse_signed, synth_cached, voice_params

    loc = doc["locales"][lc]
    dialogue = loc["dialogue"]
    if not dialogue:
        raise FeuilleError(f"{lc}: 该语种无台词（polyglot 形态请走共享剧本线）")

    people = [p for p in personas().values() if p.get("locale") == lc]
    roles = doc.get("roles") or {}
    if not roles:
        raise FeuilleError(f"{lc}: scene.json 缺 §0.4 roles 声明（先跑 scene validate）")
    by_speaker = _pick_cast(people, roles, lc)
    # 情绪增量：scene.json §0 声明了才有；没声明 = ±0（不发明默认值）
    mood_voices = doc.get("moodVoices") or {}

    async def _run():
        lines = []
        for ln in dialogue:
            if ln["speaker"] not in by_speaker:
                raise FeuilleError(
                    f"{lc} #{ln.get('i')}: 说话人 {ln['speaker']!r} 不在 §0.4 roles "
                    f"{sorted(by_speaker)} 里（先跑 scene validate）")
            p = by_speaker[ln["speaker"]]
            v = p["voice"]
            r_off, p_off = _mood_offset(ln["mood"], mood_voices)
            rate, pitch = voice_params(v["rate"], v["pitch"], r_off, p_off)
            # persona 声线带符号（"+6%"），voice_params 已统一夹取安全域；
            # 缓存键含 rate/pitch 串——同一 persona 同一文本不同情绪增量自然分键。
            got = await synth_cached(ln["text"], v["voiceId"], rate, pitch, cache_dir)
            lines.append({
                "i": ln["i"], "speaker": ln["speaker"], "mood": ln["mood"],
                "text": ln["text"], "key": got["key"], "words": got["words"],
                "dur": None,          # 词级真值，下面填
            })
            lines[-1]["dur"] = _effective_dur(got["words"], ln["text"],
                                             cache_dir / f"{got['key']}.mp3")
        return lines

    lines = asyncio.run(_run())
    audio_dir = cache_dir
    total, span = enrich_lines(lines, gap, audio_dir)
    return {"locale": lc, "lines": lines, "gap": gap,
            "totalDur": total, "spanDur": span}


def _effective_dur(words: list[dict], text: str, mp3: Path) -> float:
    """tts.effective_dur 的薄封装（import 在函数内避免模块级循环）。

    probe_dur 用**实测文件时长**，不能用 1e9 哨兵：words 空/伪词的行
    effective_dur 会原样返回 probe_dur——哨兵值直灌 enrich_lines 后
    starts/totalDur/tail_silence 全线炸掉（tail_silence ≈ -1e9 秒）。
    """
    from .audio import probe_duration
    from .tts import effective_dur
    return effective_dur(words, probe_duration(mp3), text)


def scene_md_sha16(lessons_dir, sid: str) -> str:
    md_p, _ = scene_paths(sid, lessons_dir)
    return hashlib.sha256(md_p.read_bytes()).hexdigest()[:16]


def run_scene(lessons_dir, sid: str, *, gap: float = LINE_GAP,
              force: bool = False) -> int:
    """单课全语种 TTS：逐语种跑 build_locale_timeline，落 timeline.json + 台账。"""
    _register_line()
    doc = scene_doc(sid, lessons_dir)
    root = _scene_root(lessons_dir)
    out_dir = root / "build" / "scene" / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = scene_md_sha16(lessons_dir, sid)
    extra = (sid, sha, str(gap))

    ok_all = True
    for lc in doc["locales"]:
        unit = f"{sid}/{lc}"
        tl_path = out_dir / f"scene-{sid}_{lc}.timeline.json"
        artifacts = [tl_path.relative_to(root).as_posix()]
        fresh, why = status_of(root, register_kind, unit, artifacts)
        if fresh and not force:
            print(f"  [SKIP] {lc}：{why}")
            continue
        tl = build_locale_timeline(doc, lc, out_dir, gap=gap)
        # 逐行 mp3 落到产物目录（compose 线直接消费）；
        # 缓存命中时 mp3 已在缓存位，这里做产物位副本（指纹保护的是产物，不是缓存）。
        # 缺源即报错：静默跳过会让上一次构建的旧 line-XX.mp3 原地存活，
        # compose 线消费到错配音频而台账全绿。
        for ln in tl["lines"]:
            src = out_dir / f"{ln['key']}.mp3"
            if not src.exists():
                raise FeuilleError(f"{lc}: 行 {ln['i']} 的缓存音源缺失：{src.name}")
            shutil.copyfile(src, out_dir / f"line-{ln['i']:02d}.mp3")
        tl_path.write_text(json.dumps(tl, ensure_ascii=False, indent=1), "utf-8")
        record(root, register_kind, unit, artifacts, extra=extra)
        n = len(tl["lines"])
        print(f"  [OK] {lc}: {n} 行 · speech {tl['totalDur']:.1f}s · "
              f"span {tl['spanDur']:.1f}s → {tl_path.name}")
        ok_all &= n > 0
    return 0 if ok_all else 1


def main(argv=None) -> int:
    """cli.py 路由入口：`uv run feuille scene tts --scene <id>`。"""
    ap = argparse.ArgumentParser(
        prog="feuille scene tts",
        description="场景课 TTS：scene.json × 班底声线 → timeline.json（④成片·语音）")
    ap.add_argument("--scene", required=True, help="场景 id，如 guangchaoshi-逛超市")
    ap.add_argument("--lessons", default=None,
                    help="lessons 目录（缺省 = feuille 仓库根 lessons/）")
    ap.add_argument("--gap", type=float, default=LINE_GAP,
                    help=f"行距秒（缺省 {LINE_GAP}，与 verify_timeline 口径一致）")
    ap.add_argument("--force", action="store_true", help="忽略台账判定，全量重做")
    a = ap.parse_args(list(argv) if argv is not None else [])
    try:
        return run_scene(a.lessons, a.scene, gap=a.gap, force=a.force)
    except FeuilleError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
