"""B1 工具 1：开场合弦铺底（0-25s）的音符时间轴。

方法（PLAN.md §5.3 纪律的落法，第三版）：
  1. 解析 CC0 MIDI（Largo 前 5 小节，70 音符）→ 按 tick 聚成和弦块。
  2. 和弦模板逐帧分类：模糊 Jaccard（模板音级集 vs 录音 chroma）argmax + 众数平滑
     → 切成连续段。**不用 DTW**——子序列 DTW 的代价每步累加，结构性偏向把
     参考压进最短的音频段（本机实测：19s 参考被压进 2.1s，正是 B0 假阳性教训的根源）。
  3. 段序对拍：MIDI 和弦块顺序是乐谱事实——把块序列按顺序映射到段序列上。
     重复模板（块 0 与块 2 同为 E-G#-B）天然由顺序区分。
  4. 判据（三条同时成立才算过）：
     a. 结构块（0-5、7）的映射起点落在 B0 实测粗窗带内（2s 窗扫描表，7/7 已核）；
     b. 映射起点后 0.05-0.6s 的录音最强音级与块音级交集 ≥ 2/3（逐和弦对拍）；
     c. 内声部块（6、8：起音落在前一块时值内部，无新和弦强起）按块内比例插值，
        只查单调与带；全部块起点单调递增。
     任何一条不满足即退出 1。
"""
import json
import sys
import traceback
from pathlib import Path

import librosa
import numpy as np

BASE = Path(__file__).resolve().parent.parent
OGG = BASE / "assets" / "largo.ogg"
MIDI = BASE / "assets" / "largo-5bars.midi"
OUT = BASE / "notes" / "opening-notes.json"
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

WIN_A, WIN_B = 0.0, 30.0
HOP = 512                       # chroma hop（23ms）
SIM_MIN = 0.30                  # 帧分类最低相似度（低于=未分类）
SMOOTH = 21                     # 众数平滑窗（帧）
RUN_MIN = 13                    # 段最短时长（帧，0.3s）
HIT_FRAC = 2 / 3
# B0 实测粗窗（2s 窗扫描表，PLAN §5.3(a)）→ 各块映射起点的容许带。
# 块 6/7 的左沿推导：块 5 名义时值 1s + 块 6（D#，384 tick ≈ 1s 名义）夹在中间，
# 故块 6 ≥ 块 5 起点，块 7 ≥ 块 5 起点 + 2s 名义下限再放宽。
BANDS = [(0.0, 2.5), (3.0, 6.5), (5.0, 9.5), (9.0, 12.5), (11.0, 15.0),
         (15.0, 19.0), (15.5, 22.5), (18.0, 23.5), (20.0, 27.0)]
# 结构块（有新和弦强起，须过 a+b 判据）；其余为内声部块（只过 c 判据）
STRUCTURAL = {0, 1, 2, 3, 4, 5, 7}


def midi_notes(path: Path):
    import mido

    mid = mido.MidiFile(str(path))
    tpq = mid.ticks_per_beat
    tempo = 500000
    for trk in mid.tracks:
        for msg in trk:
            if msg.type == "set_tempo":
                tempo = msg.tempo
                break
        else:
            continue
        break
    notes = []
    for trk in mid.tracks:
        t = 0
        for msg in trk:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                notes.append([t, None, msg.note])
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                for n in reversed(notes):
                    if n[2] == msg.note and n[1] is None:
                        n[1] = t
                        break
    notes = [n for n in notes if n[1] is not None]
    notes.sort()
    return notes, tpq, tempo


def main() -> int:
    notes, tpq, tempo = midi_notes(MIDI)
    print(f"[MIDI] notes={len(notes)} tpq={tpq} tempo={tempo}")

    blocks = []
    for on, off, pitch in notes:
        if blocks and blocks[-1]["tick"] == on:
            blocks[-1]["pitches"].append(pitch)
            blocks[-1]["tick_end"] = max(blocks[-1]["tick_end"], off)
        else:
            blocks.append({"tick": on, "tick_end": off, "pitches": [pitch]})
    for b in blocks:
        b["pcs"] = sorted({p % 12 for p in b["pitches"]})
    print(f"[BLOCKS] {len(blocks)} 个和弦块")

    # ── 音频 chroma（限窗 0-30s）──
    y, sr = librosa.load(str(OGG), sr=22050, mono=True,
                         offset=WIN_A, duration=WIN_B - WIN_A)
    C = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    times = librosa.times_like(C, sr=sr, hop_length=HOP) + WIN_A
    Cn = C / np.maximum(C.sum(axis=0), 1e-9)
    print(f"[CHROMA] {C.shape}")

    # ── 模板分类（模糊 Jaccard）——同音级集的块先并成组，消除 argmax 平局偏置 ──
    group = {}                       # 块号 → 组号
    groups = []                      # 组号 → 音级集
    for i, b in enumerate(blocks):
        key = tuple(b["pcs"])
        if key not in group:
            group[key] = len(groups)
            groups.append(b["pcs"])
        gid = group[key]
        group_of_block = group       # noqa: F841（可读性：下方按块查组）
        b["group"] = gid
    T = np.zeros((len(groups), 12))
    for g, pcs in enumerate(groups):
        T[g, pcs] = 1.0
        T[g] /= T[g].sum()
    sim = np.zeros((len(groups), C.shape[1]))
    for g in range(len(groups)):
        inter = np.minimum(T[g][:, None], Cn).sum(axis=0)
        union = np.maximum(T[g][:, None], Cn).sum(axis=0)
        sim[g] = inter / union
    cls = sim.argmax(axis=0)
    cls[sim.max(axis=0) < SIM_MIN] = -1

    # 众数平滑（±SMOOTH//2 帧，忽略未分类帧；全未分类则保持 -1）
    half = SMOOTH // 2
    sm = cls.copy()
    for k in range(len(cls)):
        lo_, hi_ = max(0, k - half), min(len(cls), k + half + 1)
        win = cls[lo_:hi_]
        win = win[win >= 0]
        if len(win):
            vals, counts = np.unique(win, return_counts=True)
            sm[k] = vals[counts.argmax()]
    cls = sm

    # ── 切段 ──
    runs = []  # [group, start_idx, end_idx)
    k = 0
    n_f = len(cls)
    while k < n_f:
        j = k
        while j < n_f and cls[j] == cls[k]:
            j += 1
        if cls[k] >= 0 and j - k >= RUN_MIN:
            runs.append([int(cls[k]), k, j])
        k = j
    print(f"[RUNS] {len(runs)} 段: " +
          " ".join(f"{''.join(NAMES[p] for p in groups[g])}@{times[a]:.1f}"
                   for g, a, _ in runs))

    # ── 顺序对拍：块序列 → 段序列（按组匹配，天然区分重复组）──
    anchors = [None] * len(blocks)   # [t_start, t_end] 秒
    run_ptr = 0
    prev_on = -1.0
    all_pass = True
    struct_fail = False
    print("[VERIFY]")
    for i in sorted(STRUCTURAL):
        b = blocks[i]
        got = None
        while run_ptr < len(runs):
            rg, ra, rb = runs[run_ptr]
            if rg == b["group"] and times[ra] > prev_on + 0.10:
                got = (float(times[ra]), float(times[rb]))
                run_ptr += 1
                break
            run_ptr += 1
        if got is None:
            print(f"  块{i} {[NAMES[p] for p in b['pcs']]} 无匹配段 ✗")
            all_pass = False
            struct_fail = True
            continue
        on = got[0]
        lo, hi = BANDS[i]
        ok_band = lo <= on <= hi
        m = (times >= on + 0.05) & (times <= on + 0.6)
        top3 = np.argsort(-C[:, m].mean(axis=1))[:3] if m.any() else []
        hit = len(set(b["pcs"]) & set(int(t) for t in top3)) / len(b["pcs"])
        ok_hit = hit >= HIT_FRAC
        ok = ok_band and ok_hit
        all_pass &= ok
        anchors[i] = list(got)
        prev_on = on
        print(f"  块{i} tick={b['tick']:5d} {','.join(NAMES[p] for p in b['pcs']):14s} "
              f"起点 {on:6.2f}s 带[{lo}-{hi}] {'✓' if ok_band else '✗'} "
              f"对拍 {[NAMES[t] for t in top3]} 交集 {hit:.0%} {'✓' if ok_hit else '✗'}")
    if struct_fail:
        print("[VERDICT] FAIL（结构块未全过，内声部块不再插值）")
        return 1

    # 结构块的锚点区间右沿 = 下一结构块起点（末块取最后一段终点 + 2s 上限）
    order = sorted(STRUCTURAL)
    for k in range(len(order) - 1):
        anchors[order[k]][1] = anchors[order[k + 1]][0]
    anchors[order[-1]][1] = min(WIN_B, times[runs[-1][2] - 1] + 2.0)

    for i in range(len(blocks)):
        if i in STRUCTURAL:
            continue
        b = blocks[i]
        # 内声部块：起音 tick 落在前一结构块时值内部 → 块内比例插值
        k_prev = max(k for k in STRUCTURAL if k < i)
        p_tick0, p_tick1 = blocks[k_prev]["tick"], blocks[k_prev]["tick_end"]
        pa, pb = anchors[k_prev]
        frac = (b["tick"] - p_tick0) / max(1, p_tick1 - p_tick0)
        on = pa + frac * (pb - pa)
        lo, hi = BANDS[i]
        # 内声部块落在 k_prev 区间内（frac∈[0,1] 保证）；时序正确性由最终
        # 「按乐谱块序的单调性」统一判——不与处理顺序的 prev_on 比较
        # （块 7 先于块 6 被处理，prev_on 已越过块 6 的时点，比较必然假阴性）。
        ok = lo <= on <= hi
        all_pass &= ok
        anchors[i] = [on, pb]
        print(f"  块{i}(内声部) tick={b['tick']:5d} 插值起点 {on:6.2f}s "
              f"带[{lo}-{hi}] {'✓' if lo <= on <= hi else '✗'}")
    onsets = [a[0] for a in anchors if a is not None]
    mono = all(onsets[k] < onsets[k + 1] for k in range(len(onsets) - 1))
    print(f"  单调性: {'✓' if mono else '✗'}")
    all_pass &= mono
    if not all_pass:
        print("[VERDICT] FAIL")
        return 1

    # ── tick→秒 分段线性映射（锚点=各块起点）→ 逐音符时间轴 ──
    atick = np.array([b["tick"] for b in blocks], dtype=float)
    asec = np.array(onsets, dtype=float)
    atick_end = np.array([b["tick_end"] for b in blocks], dtype=float)
    # 末块终点：按块内时值比例外推（约 tempo 拉伸系数 = 末块实测/名义）
    nominal_last = (atick_end[-1] - atick[-1]) * (tempo / 1e6 / tpq)
    stretch = max(1.0, (anchors[-1][1] - onsets[-1]) / max(0.01, nominal_last))

    def tick_to_time(tick):
        if tick <= atick[0]:
            return float(asec[0] + tick * (tempo / 1e6 / tpq) * stretch)
        k = int(np.searchsorted(atick, tick, side="right") - 1)
        if k >= len(atick) - 1:
            return float(asec[k] + (tick - atick[k]) * (tempo / 1e6 / tpq) * stretch)
        return float(asec[k] + (tick - atick[k]) / (atick[k + 1] - atick[k])
                     * (asec[k + 1] - asec[k]))

    out_notes = [{"pitch": p, "name": f"{NAMES[p % 12]}{p // 12 - 1}",
                  "start": round(tick_to_time(on), 3),
                  "end": round(tick_to_time(off), 3)}
                 for on, off, p in notes]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": {"midi": MIDI.name, "ogg": OGG.name,
                   "method": "chord-template frame classification + order-matched runs, "
                             "structural blocks gated by band+chroma cross-check (no DTW)"},
        "blocks": [{"tick": b["tick"], "pcs": [NAMES[p] for p in b["pcs"]],
                    "names": sorted({f"{NAMES[p % 12]}{p // 12 - 1}" for p in b["pitches"]}),
                    "structural": i in STRUCTURAL,
                    "t_start": round(onsets[i], 3),
                    "t_end": round(anchors[i][1], 3)}
                   for i, b in enumerate(blocks)],
        "notes": out_notes,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OUT] {OUT} ({len(out_notes)} notes)")
    print("[VERDICT] PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
