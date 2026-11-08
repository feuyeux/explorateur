# -*- coding: utf-8 -*-
"""assemble.py — 一支成片的装配：字幕卡烧录 → 旁白绝对落位 → 无 BGM 混音 → 成片。

顺序不能换（SKILL.md 的作业序）：
    ① render_cards.py 出三层卡（走 TS 的 textlayer shoot，判据用实测层盒）
    ② 卡片按窗口区间叠到母版上（单帧输入 + between(t,…)）
    ③ place_voice.py plan 判旁白落点并出混音链（绝对锚点，不是拼接）
    ④ 跑混音链：旁白钉位 + 原声被侧链压低 → final.mp4

用法:
    python3 scripts/assemble.py --team-dir <目录> --master <母版.mp4> [--duck 0.14] [--out final.mp4]

烧录链的两个实拍坑（2026-11-08 五支成片实测）：
  - **overlay 必须 eof_action=repeat**（默认值）：卡片是单帧输入，`pass` 会在
    卡片帧 EOF 后停止合成——**所有卡片静默全灭**，机检全绿、
    时长读数正常，只有抽帧才看得见。selftest 把这条钉死；
  - **输入 0 = 母版（含原声），1..N = 旁白段**（按落点先后）；每段按 anchor
    用 adelay 钉绝对时间。落点判决 FAIL 就回去改文案/窗口，不许挪落点。

退出码：0 = 成片产出；1 = 装配失败（卡片缺 / 烧录失败 / 落点判决没过）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

def _need(binary: str) -> str:
    """解析外部可执行文件：优先 FEUILLE_<NAME> 环境变量覆盖，否则 PATH 里找。

    全仓的跨平台解析事实源是 @feuille/core 的 platform resolver；本脚本是
    skill 内的独立 Python，用同样的「可覆盖 + 找不到就报错」口径，
    不静默拿别的同名程序顶替。
    """
    import os
    import shutil
    env = os.environ.get(f"FEUILLE_{binary.upper()}")
    if env:
        if not Path(env).exists():
            raise RuntimeError(f"环境变量 FEUILLE_{binary.upper()} 指向的文件不存在：{env}")
        return env
    found = shutil.which(binary)
    if not found:
        raise RuntimeError(f"找不到 {binary}——请装好它，或用 FEUILLE_{binary.upper()} 指定路径。")
    return found

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, encoding="utf-8", errors="ignore")


def probe(path: Path) -> tuple[float, int, int]:
    r = run([_need(FFPROBE), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", str(path)])
    d = json.loads(r.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    return (float((d.get("format") or {}).get("duration") or 0.0),
            int(st.get("width") or 1920), int(st.get("height") or 1080))


def interval(w: dict) -> tuple[float, float]:
    """窗口区间：t0/t1 优先，兼容装配脚本沿用的紧凑写法 src。"""
    if isinstance(w.get("t0"), (int, float)) and isinstance(w.get("t1"), (int, float)):
        return float(w["t0"]), float(w["t1"])
    src = str(w.get("src") or "")
    a, b = src.split("-", 1)
    return float(a), float(b)


def build_overlay_chain(windows: list[dict], total: float,
                        W: int, H: int) -> tuple[list[str], str]:
    """卡片 overlay 链：单帧输入 + between(t,…) + eof_action=repeat。

    eof_action=repeat 是**刻意的**（overlay 的默认值）：单帧卡片输入在 EOF 后
    重复末帧，enable=between(t,t0,t1) 负责显隐。写成 pass 会让全部卡片在
    首帧之后静默消失——画面上永远看不到卡，机检发现不了。
    """
    chains: list[str] = []
    prev = "0:v"
    for i, w in enumerate(windows):
        t0, t1 = interval(w)
        chains.append(
            f"[{i + 1}:v]format=rgba,scale={W}:{H}[c{i}];"
            f"[{prev}][c{i}]overlay=0:0:enable='between(t,{max(0.0, t0):.3f},{min(total, t1):.3f})'"
            f":eof_action=repeat[v{i}]")
        prev = f"v{i}"
    return chains, prev


def selftest() -> int:
    """离线回归：链构造 + interval 兼容 + eof_action 坑钉死。"""
    ok = True

    def check(name: str, got: bool, want: bool) -> None:
        nonlocal ok
        if got != want:
            ok = False
        print(f"  [{'PASS' if got == want else 'FAIL'}] {name}")

    wins = [
        {"key": "w01", "t0": 0.0, "t1": 8.08},
        {"key": "w02", "src": "9.48-20.0"},
        {"key": "w03", "t0": 20.84, "t1": 29.08},
    ]
    check("interval 认 t0/t1", interval(wins[0]) == (0.0, 8.08), True)
    check("interval 认 src 紧凑写法", interval(wins[1]) == (9.48, 20.0), True)
    chains, last = build_overlay_chain(wins, 129.66, 1920, 1080)
    check("三窗三条链", len(chains) == 3, True)
    check("链尾标签 v2", last == "v2", True)
    check("全部 eof_action=repeat",
          all("eof_action=repeat" in c for c in chains), True)
    check("无 eof_action=pass（静默全灭卡的坑）",
          all("eof_action=pass" not in c for c in chains), True)
    check("enable=between 在位", all("enable='between(t," in c for c in chains), True)
    check("单帧输入无 -loop 1", all("-loop" not in c for c in chains), True)
    print("selftest：" + ("全部通过" if ok else "有用例失败"))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description="一支成片的装配")
    ap.add_argument("--team-dir", required=True, help="队伍目录（windows.json 所在）")
    ap.add_argument("--master", required=True, help="母版 mp4")
    ap.add_argument("--duck", type=float, default=0.14, help="原声压低系数（默认 0.14，换片重测）")
    ap.add_argument("--out", default="final.mp4")
    args = ap.parse_args(argv)

    team = Path(args.team_dir).resolve()
    master = Path(args.master).resolve()
    windows_path = team / "windows.json"
    cards_dir = team / "cards"
    burn = team / "build" / "burn.mp4"
    burn.parent.mkdir(parents=True, exist_ok=True)

    total, W, H = probe(master)
    print(f"母版：{master.name}  {W}x{H}  {total:.2f}s")

    windows_doc = json.loads(windows_path.read_text("utf-8"))
    windows = windows_doc["windows"] if isinstance(windows_doc, dict) else windows_doc

    # ① 字幕卡（解说语=中文 ⇒ mono 三层卡）
    # render_cards.py 要的是「解说语窗口表」：{"windows":[…], "i18n":{locale:{key:{…}}}}
    # 或纯语种表 {locale:{key:{…}}}。中文单语片的 i18n 层就是 zh-CN 自己——
    # 直接把窗口表本身当 i18n 传会被判「没有 zh-CN 这一份」。
    print("\n① 渲染字幕卡…")
    i18n_path = team / "i18n.json"
    i18n_path.write_text(json.dumps({
        "windows": windows,
        "i18n": {"zh-CN": {str(w["key"]): {"title": str(w.get("title", "")),
                                            "say": str(w.get("say", "")),
                                            "stat": str(w.get("stat", ""))}
                             for w in windows}},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    r = run([sys.executable, str(HERE / "render_cards.py"),
             "--windows", str(windows_path), "--i18n", str(i18n_path),
             "--lang", "zh-CN", "--out", str(cards_dir)])
    if r.returncode != 0:
        print((r.stdout or "")[-1500:])
        print((r.stderr or "")[-1500:])
        return r.returncode or 1

    # ② 烧录：单帧卡 + between(t,…) + eof_action=repeat，逐张串接（不是拼接）
    print("\n② 烧录字幕卡…")
    pngs = [cards_dir / f"card.{w['key']}.png" for w in windows]
    missing = [p.name for p in pngs if not p.exists()]
    if missing:
        print(f"缺卡片 PNG：{missing}")
        return 1
    chains, prev = build_overlay_chain(windows, total, W, H)
    cmd = [_need(FFMPEG), "-y", "-v", "error", "-i", str(master)]
    for p in pngs:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", ";".join(chains), "-map", f"[{prev}]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(burn)]
    r = run(cmd)
    if r.returncode != 0:
        print("烧录失败：", (r.stderr or "")[-2000:])
        return 1
    print(f"   → {burn.name}")

    # ③ 旁白落点（绝对锚点）
    print("\n③ 旁白落点判决…")
    place = team / "place.json"
    r = run([sys.executable, str(HERE / "place_voice.py"), "plan",
             "--windows", str(windows_path), "--voice", str(team / "voice-report.json"),
             "--total", f"{total:.3f}", "--duck", str(args.duck), "--out", str(place)])
    print((r.stdout or "").strip())
    if r.returncode != 0:
        print("落点判决没过，先改文案/窗口（不许挪落点）")
        return r.returncode or 1

    # ④ 混音（两层：旁白 + 被压低的原声，无 BGM）
    print("\n④ 混音出成片…")
    res = json.loads(place.read_text("utf-8"))
    chain = res["chain"]
    inputs = res["inputs"]
    cmd = [_need(FFMPEG), "-y", "-v", "error", "-i", str(burn)]
    for f in inputs[1:]:
        cmd += ["-i", str(team / f)]
    out = team / args.out
    cmd += ["-filter_complex", chain, "-map", "[aout]", "-map", "0:v",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out)]
    r = run(cmd)
    if r.returncode != 0:
        print("混音失败：", (r.stderr or "")[-2000:])
        return 1
    dur, w, h = probe(out)
    print(f"   → {out.name}  {w}x{h}  {dur:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
