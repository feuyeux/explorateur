#!/usr/bin/env python3
"""place_voice.py — 把实测过的旁白段落到母版的**绝对时间**上，并判落点对齐。

为什么单独有这一步：窗口表给的是「画面上这一镜在哪」，而旁白要对齐的是
「这一镜里**动作发生**的那一帧」。两者不是同一点——一个 6s 的镜头里，起球
可能在 t0+2s、球过线在 t0+4s。旁白贴在窗口起点进，结果词就抢在画面前面
（早了）；紧窗时又把 LEAD 静默回贴到 `t1 - 时长`，同一句话反而拖到动作
之后（晚了）。四场实跑的「有的早、有的晚」就是同一条规则在两种窗型下的
两个极端。

四条规矩（SKILL.md「旁白落点」的机检版）：

  1. **绝对时间**：每段起点 = `anchor + LEAD`，用 `adelay` 各自钉在时间线
     上。**不许把段按顺序拼接**（`concat` / 累加时长）——一段的误差会累加到
     后面每一段，片子越长偏得越多。
  2. **anchor 是画面锚点**：这一窗旁白要对齐的那一帧。缺省 = `t0`。
     `align: 'start'`（缺省）让**起句**落在 `anchor + LEAD`——动作起手时开口；
     `align: 'end'` 让**收句**落在 `anchor`——短卡片窗（比分动画 / 图形页）
     收在画面上那一下。回放窗把 start 锚点往后放 0.3–0.5s（先让观众认出
     「这是回放」），不另设第二个 lead 参数。
  3. **LEAD 固定、不静默回贴**：放不下就是 FAIL。修法只有两条——压词
     （build_voice 的 slack 判据）或拆窗（把长镜切成两镜），**不许挪落点**：
     挪了就没有「对齐」这回事了。
  4. **一段不许越过 `t1`**：越界就是旁白压到下一镜的画面上。

音频床：**没有 BGM**。赛事线的底是母版自己的现场原声（观众 / 解说），
被旁白侧链压低；教学线才铺音乐床，别把 `bgm-bed` 接回来。

用法：
    python3 place_voice.py plan --windows windows.json --voice voice-report.json \\
        --total 162 --out place.json
    python3 place_voice.py plan --windows windows.json --voice voice-report.json \\
        --total 162 --no-duck --chain-only
    python3 place_voice.py selftest

`voice-report.json` 是 **TTS 实测**的产物（build_voice 每段合成后立刻量），
契约：`{"segments": [{"key": "w05", "file": "voice/w05.mp3", "duration": 3.21}]}`
或同结构的裸列表；`key` 也可写成 `window`。时长不是估的——估出来的落点
和实际音频对不上，正是这一步要防的事。

退出码：0 = 落点全部合法（可能有 WARN）；1 = 有 FAIL（越界 / 叠音 / 缺段）；
2 = 输入坏了（缺 --total、窗口表非法、voice-report 读不动）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_windows as cw  # noqa: E402  （窗口表 schema 的解析只有它一处）

LEAD = 0.45            # 画面先到位，声音再进来
DEFAULT_DUCK = 0.14    # 原声电平（2026-11-02 实跑 0.16→0.14 后旁白压得住；换片重测）
ALIGNS = {"start", "end"}


# ---------------------------------------------------------------- 输入


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_voice(doc: object) -> tuple[list[dict], list[str]]:
    """voice-report → [{key, duration, file}]。契约坏了返回错误（调用方退 2）。"""
    entries = doc.get("segments") if isinstance(doc, dict) else doc
    if not isinstance(entries, list) or not entries:
        return [], ["voice-report 里没有 segments（或不是列表）"]
    out, errors, seen = [], [], set()
    for i, ent in enumerate(entries, start=1):
        if not isinstance(ent, dict):
            errors.append(f"voice-report 第 {i} 条不是对象")
            continue
        key = str(ent.get("key") or ent.get("window") or "").strip()
        if not key:
            errors.append(f"voice-report 第 {i} 条缺 key")
            continue
        if key in seen:
            errors.append(f"voice-report 里 {key} 重复——同一段旁白给了两个时长，"
                          "判不出用哪个")
            continue
        seen.add(key)
        try:
            dur = float(ent["duration"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{key}: 缺实测 duration（秒）——不许用估算值代替")
            continue
        if dur <= 0:
            errors.append(f"{key}: duration 必须 > 0，实为 {dur}")
            continue
        out.append({"key": key, "duration": dur,
                    "file": str(ent.get("file") or "")})
    return out, errors


def windows_of(doc: object) -> tuple[list[dict], list[str]]:
    """取窗口表 + 输入契约（枚举 / 时间区间 / anchor）。"""
    errors = cw.validate_table(doc)
    if errors:
        return [], errors
    return list(doc["windows"]), []


# ---------------------------------------------------------------- 落点


def _interval_of(win: dict) -> tuple[float, float]:
    """窗口区间。契约层（cw.validate_table）已保证存在，这里再兜一层。

    裸解包会抛 `TypeError: cannot unpack non-iterable NoneType`——退出码 1（像落点判决失败），
    而实际是「输入契约坏了」，该退 2。宁可报一句人话。
    """
    iv = cw._interval(win)
    if iv is None:
        key = str(win.get("key") or "?")
        raise ValueError(
            f"{key}: 缺时间区间（t0/t1 或 src）——输入契约坏了，请先过 check_windows.py")
    return iv


def anchor_of(win: dict) -> tuple[float, bool]:
    """(锚点, 是否显式给出)。缺省 = t0：画面一进就说，宁早勿晚以外的窗型才需要改。"""
    t0, _ = _interval_of(win)  # 同一份区间解析，不在此另抄一份 schema
    if win.get("anchor") is None:
        return t0, False
    return float(win["anchor"]), True


def align_of(win: dict) -> str:
    return str(win.get("align") or "start").strip().lower()


def plan(
    windows: list[dict],
    voice: list[dict],
    lead: float,
    total: float | None,
) -> dict:
    """算每段的绝对落点，并逐条判「放得下 / 不叠 / 不越界」。"""
    by_key = {str(w.get("key")): w for w in windows}
    seg_by_key = {s["key"]: s for s in voice}
    fails: list[str] = []
    warns: list[str] = []
    placed: list[dict] = []

    # 表对不上的方向两边都要查：窗口有词没音频、有音频没窗口。
    for key, win in by_key.items():
        if str(win.get("say", "") or "").strip() and key not in seg_by_key:
            fails.append(f"{key}: 有 say 但没有实测音频——这一段没东西可放")
    for key in seg_by_key:
        if key not in by_key:
            fails.append(f"{key}: voice-report 里的段在窗口表里不存在（key 写错了？）")

    for key, win in by_key.items():
        seg = seg_by_key.get(key)
        if seg is None:
            continue
        t0, t1 = _interval_of(win)
        anchor, explicit = anchor_of(win)
        align = align_of(win)
        d = seg["duration"]
        # start 对齐：起句落在 anchor + LEAD；end 对齐：收句落在 anchor（卡片短窗）
        start = anchor + lead if align == "start" else anchor - d
        end = start + d
        slack = t1 - end
        item = {
            "key": key, "kind": win.get("kind"), "align": align,
            "t0": round(t0, 3), "t1": round(t1, 3), "anchor": round(anchor, 3),
            "start": round(start, 3), "end": round(end, 3),
            "duration": round(d, 3), "slack": round(slack, 3),
            "file": seg["file"], "delay_ms": int(round(start * 1000)),
        }
        placed.append(item)
        if start < t0 - 1e-6:
            fails.append(
                f"{key}: 落点 {start:.2f}s 早于窗口起点 {t0:.2f}s"
                "——这句会压在上一镜的画面上")
        if slack < -1e-6:
            remedy = "压词或拆窗" + ("，或把 anchor 往前挪回到动作起手" if align == "end"
                                     else "")
            fails.append(
                f"{key}: 旁白到 {end:.2f}s，越过窗口终点 {t1:.2f}s（超 {-slack:.2f}s）"
                f"——{remedy}，不许把落点往前挪")
        if not explicit and align == "start" and (t1 - t0) > 4.0:
            warns.append(
                f"{key}: {t1 - t0:.1f}s 的长窗没给 anchor，旁白从 {start:.2f}s 进；"
                "动作若在窗内后半段，这句就抢在画面前面")
        if str(win.get("kind", "")).lower() == "replay" and align == "start" \
                and not explicit:
            warns.append(
                f"{key}: 回放窗没给 anchor——首句建议后放 0.3–0.5s，先让观众认出这是回放")

    placed.sort(key=lambda p: p["start"])
    for prev, nxt in zip(placed, placed[1:]):
        if nxt["start"] < prev["end"] - 1e-6:
            fails.append(
                f"{prev['key']} 与 {nxt['key']} 叠音：前段到 {prev['end']:.2f}s，"
                f"后段 {nxt['start']:.2f}s 就进——两句会同时响")
    if total is not None:
        for p in placed:
            if p["end"] > total + 1e-6:
                fails.append(f"{p['key']}: 落点越过母版时长 {total:.2f}s")

    return {"lead": lead, "total": total, "segments": placed,
            "fail": fails, "warn": warns, "pass": not fails}


# ---------------------------------------------------------------- 混音链


def build_chain(placed: list[dict], total: float, duck: float | None) -> str:
    """旁白按绝对时间钉位 → 原声被旁白侧链压低 → 两层合并。**没有 BGM 输入。**

    输入次序：`0` = 母版（含原声），`1..N` = 旁白段（按 start 排序）。
    已知坑（别简化掉）：`[voice]` 同时被 `sidechaincompress`（触发）与 `amix`
    （主轨）引用时必须 `asplit=2` 拆开，否则滤镜会把人声整体压掉
    25–30 dB；`loudnorm` 必须在塑形之前。
    """
    parts = [f"[{i}:a]adelay={p['delay_ms']}|{p['delay_ms']},apad[v{i - 1}]"
             for i, p in enumerate(placed, start=1)]
    n = len(placed)
    join = (f"{''.join(f'[v{i}]' for i in range(n))}"
            f"amix=inputs={n}:normalize=0:duration=longest") if n > 1 else "[v0]"
    voice = (f"{join},loudnorm=I=-16:TP=-1.5:LRA=11,apad,"
             f"atrim=0:{total:.3f}")
    if duck is None:
        return ";".join(parts + [f"{voice}[aout]"])
    return ";".join(parts + [
        f"{voice},asplit=2[vm][vs];"
        f"[0:a]atrim=0:{total:.3f},volume={duck:.3f}[amb];"
        f"[amb][vs]sidechaincompress=threshold=0.02:ratio=8:attack=20:"
        f"release=380:makeup=1[duck];"
        f"[duck][vm]amix=inputs=2:normalize=0:dropout_transition=0,"
        f"alimiter=limit=0.95[aout]",
    ])


# ---------------------------------------------------------------- 反向验证


def selftest() -> int:
    """好例必须过；「早 / 晚 / 叠音 / 缺段」四类坏例必须各自被抓到。"""
    bad = 0

    def case(name: str, ok: bool, detail: object = "") -> None:
        nonlocal bad
        tail = f"  {detail}" if detail else ""
        print(f"{'PASS' if ok else 'FAIL'}  {name}{tail}")
        if not ok:
            bad += 1

    def win(key, t0, t1, say="一句词", kind="live", anchor=None, align=None):
        w = {"key": key, "kind": kind, "visible": "event", "t0": t0, "t1": t1,
             "see": "画面", "title": "题", "say": say, "stat": "0-0"}
        if anchor is not None:
            w["anchor"] = anchor
        if align is not None:
            w["align"] = align
        return w

    def seg(key, d, file="v.mp3"):
        return {"key": key, "duration": d, "file": file}

    # 1 · 好例：绝对落点，窗间空档原样保留（拼接会把它吃掉）
    res = plan([win("w1", 10, 14), win("w2", 30, 34)],
               [seg("w1", 2.0), seg("w2", 2.0)], LEAD, 40)
    starts = [p["start"] for p in res["segments"]]
    case("好例全部合法", res["pass"], f"fail={res['fail']}")
    case("落点 = anchor + LEAD（绝对时间）",
         abs(starts[0] - 10.45) < 1e-6 and abs(starts[1] - 30.45) < 1e-6,
         f"starts={starts}")
    # 2 · 拼接漂移：按前一段结束处接下一段，会把 w2 提前 18s
    concat_start = starts[0] + 2.0
    case("拼接会漂（本条锁住「不许 concat」）", abs(concat_start - starts[1]) > 5,
         f"concat={concat_start:.2f}s vs 绝对={starts[1]:.2f}s")

    # 3 · 晚了：时长放不下（修法是压词 / 拆窗，不是挪落点）
    res = plan([win("w1", 10, 12)], [seg("w1", 2.0)], LEAD, 20)
    case("超窗被抓", not res["pass"] and "越过窗口终点" in res["fail"][0],
         res["fail"][0] if res["fail"] else "未报")

    # 4 · 早了：长窗没给 anchor，只 WARN（判决前必须显式处理）
    res = plan([win("w1", 10, 20)], [seg("w1", 2.0)], LEAD, 20)
    case("长窗缺 anchor 只 WARN", res["pass"] and any("长窗没给 anchor" in w
                                                   for w in res["warn"]))

    # 5 · 回放窗把 anchor 后放：落点随之推迟（同一个机制，不另设参数）
    res = plan([win("w1", 10, 20, kind="replay", anchor=10.5)],
               [seg("w1", 2.0)], LEAD, 20)
    case("回放窗 anchor 生效", abs(res["segments"][0]["start"] - 10.95) < 1e-6,
         f"start={res['segments'][0]['start']}")

    # 5b · end 对齐：短卡片窗收在图形页落点上，起句落在窗内
    res = plan([win("w1", 42, 43.6, kind="graphic", anchor=43.4, align="end")],
               [seg("w1", 1.2)], LEAD, 50)
    p = res["segments"][0]
    case("end 对齐收在锚点", res["pass"] and abs(p["end"] - 43.4) < 1e-6,
         f"start={p['start']} end={p['end']}")

    # 5c · end 对齐太长：起句会跑到窗口前面（= 压在上一镜画面上）
    res = plan([win("w1", 42, 43.6, kind="graphic", anchor=43.4, align="end")],
               [seg("w1", 2.0)], LEAD, 50)
    case("end 对齐起句越界被抓", not res["pass"]
         and any("早于窗口起点" in f for f in res["fail"]))

    # 6 · 叠音：两句同时响
    res = plan([win("w1", 10, 20), win("w2", 11, 20)],
               [seg("w1", 5.0), seg("w2", 5.0)], LEAD, 25)
    case("叠音被抓", not res["pass"] and any("叠音" in f for f in res["fail"]))

    # 7 · 表对不上：有词没音频 / 有音频没窗口
    res = plan([win("w1", 10, 20), win("w2", 21, 25)], [seg("w1", 2.0)], LEAD, 25)
    case("缺段被抓", not res["pass"] and any("没有实测音频" in f for f in res["fail"]))
    res = plan([win("w1", 10, 20)], [seg("w1", 2.0), seg("w9", 2.0)], LEAD, 25)
    case("多余段被抓", not res["pass"] and any("不存在" in f for f in res["fail"]))

    # 8 · 输入契约：anchor 出窗、重复 key、缺时长、end 缺 anchor
    errs = cw.validate_table({"windows": [win("w1", 10, 20, anchor=25)]})
    case("anchor 出窗 = 输入错误", bool(errs), errs[:1])
    errs = cw.validate_table({"windows": [win("w1", 10, 20, align="end")]})
    case("end 缺 anchor = 输入错误", bool(errs), errs[:1])
    errs = cw.validate_table({"windows": [win("w1", 10, 20, align="middle")]})
    case("align 枚举笔误 = 输入错误", bool(errs), errs[:1])
    _, errs = load_voice({"segments": [seg("w1", 2.0), seg("w1", 3.0)]})
    case("重复 key = 输入错误", bool(errs), errs[:1])
    _, errs = load_voice({"segments": [{"key": "w1"}]})
    case("缺时长 = 输入错误", bool(errs), errs[:1])

    # 9 · 混音链：必须有 asplit、不许有 BGM 输入
    chain = build_chain([{"key": "w1", "delay_ms": 10450},
                         {"key": "w2", "delay_ms": 30450}], 40, DEFAULT_DUCK)
    case("链钉住绝对时间", "adelay=10450|10450" in chain
         and "adelay=30450|30450" in chain)
    case("侧链前先 asplit", "asplit=2[vm][vs]" in chain)
    case("链里没有 BGM 输入", "[1:a]atrim" not in chain, chain[:60])

    # 10 · 链必须真跑一次：内存里拼对了不等于 ffmpeg 收，更不等于声音真落在锚点上
    #      （纪律：自检只测内存里的对象，等于没测）
    import probe_scoreboard as ps  # 外部可执行解析口径的唯一实现（可覆盖 + 找不到就报错）
    try:
        exe = ps._need("ffmpeg")
    except Exception as exc:  # noqa: BLE001 —— 环境缺件必须报红，不许当跳过
        case("链能真跑（ffmpeg）", False, str(exc))
        exe = None
    if exe:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "mix.m4a"
            chain = build_chain([{"key": "w1", "delay_ms": 450},
                                 {"key": "w2", "delay_ms": 2450}], 3.0, DEFAULT_DUCK)
            r = subprocess.run(
                [exe, "-y", "-v", "error",
                 "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
                 "-f", "lavfi", "-i", "sine=frequency=660:duration=0.5",
                 "-filter_complex", chain, "-map", "[aout]", "-t", "3", str(out)],
                capture_output=True, text=True)
            case("链能真跑（ffmpeg 收尾）", r.returncode == 0 and out.exists(),
                 (r.stderr or "")[-300:])
            if out.exists():
                def db(ss: float, t: float) -> float | None:
                    m = subprocess.run(
                        [exe, "-ss", str(ss), "-t", str(t), "-i", str(out),
                         "-af", "volumedetect", "-f", "null", "-"],
                        capture_output=True, text=True)
                    hit = re.search(r"mean_volume:\s*(-?[\d.]+) dB", m.stderr)
                    return float(hit.group(1)) if hit else None

                before, after = db(0.0, 0.35), db(0.5, 1.4)
                case("声音真落在 0.45s（之前是静音）",
                     before is not None and after is not None
                     and before < -70 and after > before + 20,
                     f"0–0.35s={before} dB, 0.5–1.9s={after} dB")

    print()
    print(f"反向验证：{'全部通过' if not bad else f'{bad} 条不通过'}")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="match-recap-video 旁白落点：绝对锚点 + 越界判据")
    ap.add_argument("cmd", choices=["plan", "selftest"])
    ap.add_argument("--windows", help="窗口表 JSON")
    ap.add_argument("--voice", help="TTS 实测报告 JSON（key + duration）")
    ap.add_argument("--total", type=float, help="母版时长（秒）；出链必填")
    ap.add_argument("--lead", type=float, default=LEAD, help=f"起拍余量（默认 {LEAD}s）")
    ap.add_argument("--duck", type=float, default=DEFAULT_DUCK,
                    help=f"原声底床电平（默认 {DEFAULT_DUCK}；0 = 不压低原声）")
    ap.add_argument("--no-duck", action="store_true", help="只出旁白轨（原声由后期另挂）")
    ap.add_argument("--chain-only", action="store_true", help="只打印混音滤镜链")
    ap.add_argument("--out", help="落点计划 JSON 路径")
    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()
    if not args.windows or not args.voice:
        print("plan 需要 --windows 与 --voice", file=sys.stderr)
        return 2
    if args.total is None:
        print("plan 需要 --total（母版时长来自 ffprobe；落点判据不能拿窗口末当片长）",
              file=sys.stderr)
        return 2

    try:
        wdoc = load_json(Path(args.windows))
        vdoc = load_json(Path(args.voice))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"输入读不动：{exc}", file=sys.stderr)
        return 2
    windows, errs = windows_of(wdoc)
    voice, verrs = load_voice(vdoc)
    if errs or verrs:
        for e in errs + verrs:
            print(f"输入契约：{e}", file=sys.stderr)
        return 2

    try:
        res = plan(windows, voice, args.lead, args.total)
    except ValueError as exc:
        print(f"输入契约：{exc}", file=sys.stderr)
        return 2
    res["chain"] = build_chain(
        res["segments"], args.total, None if args.no_duck else args.duck)
    res["inputs"] = ["0"] + [p["file"] for p in res["segments"]]

    if args.out:
        Path(args.out).write_text(
            json.dumps(res, ensure_ascii=False, indent=2), "utf-8")

    if args.chain_only:
        print(res["chain"])
    else:
        print(f"{'窗':<6}{'对齐':<6}{'窗区间':>14}{'锚点':>8}{'落点':>8}{'到时':>8}{'余量':>8}")
        for p in res["segments"]:
            print(f"{p['key']:<6}{p['align']:<6}{p['t0']:6.2f}–{p['t1']:<7.2f}"
                  f"{p['anchor']:8.2f}{p['start']:8.2f}{p['end']:8.2f}"
                  f"{p['slack']:+8.2f}{'' if p['file'] else '  (缺 file)'}")
        for w in res["warn"]:
            print(f"  [WARN] {w}")
        for f in res["fail"]:
            print(f"  [FAIL] {f}")
        print("结论：" + ("PASS" if res["pass"] else "FAIL"))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
