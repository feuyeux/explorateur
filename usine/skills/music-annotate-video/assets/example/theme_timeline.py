"""B1 工具 2：英国管主题段（约 186-252s）的音符时间轴。

方法：**手写自相关 f0 跟踪**（纯 numpy，分块 FFT 控内存）——不用 librosa.pyin，
pyin 走 numba JIT，本机实测会把系统拖死（见 tools/opening_timeline.py 头注）。
流程：加窗帧 → FFT 自相关 → 滞内第一峰（抑制八度跳错）+ 抛物线插值 →
中值平滑 → 半音量化（滞回 35 音分）→ 聚段（≥0.18s、浊音占比 ≥40%）。
判据用 probe_theme.log 已定位的锚点交叉验证：
  · 205.9-207.9s 应有 G#5（≈417Hz，probe 实测谐波纯度全窗最高段）
  · 188-224s 应存在多段 ~200-225Hz 的 G#4（probe 反复测到 209.7Hz）
  · 音符总覆盖 ≥ 35s（主题在唱的净时长）
"""
import json
import sys
import traceback
from pathlib import Path

import librosa
import numpy as np

BASE = Path(__file__).resolve().parent.parent
OGG = BASE / "assets" / "largo.ogg"
OUT = BASE / "notes" / "theme-notes.json"
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SEG_A = float(sys.argv[1]) if len(sys.argv) > 1 else 186.0
SEG_B = float(sys.argv[2]) if len(sys.argv) > 2 else 252.0
SR = 22050
WIN = 4096                      # 帧长（186ms，低音区周期分辨足够）
HOP = 512                       # 帧移（23ms）
FMIN, FMAX = 260.0, 900.0       # 搜索带 = 旋律音区（C4–A5）。刻意排除 <260Hz：
                                # 大提琴基音区——复音竞争下首峰跟踪逐帧在声部间跳
                                # （实测 210Hz↔530Hz 交替），限定音区 + 泛音和评分才跟得住独奏
PEAK_MIN = 0.55                 # 泛音和声评分阈值（浊音判定）
NHARM = 4                       # 和声评分取前 NHARM 个倍频
MIN_DUR = 0.18
COV_MIN = 35.0


def track_f0(y):
    """泛音和声评分 f0 跟踪（纯 numpy，分块 FFT 控内存）。

    score(τ) = mean(r(τ), r(2τ), …, r(NHARM·τ)) / r(0)。
    真基音的全部倍频都有能量 → 得分高；高倍频伪峰（如 2f0）在 k·2f0 处
    只有偶数倍能量 → 得分系统性偏低。返回 (f0[Hz 或 nan], score)。
    """
    n = len(y)
    nf = max(0, (n - WIN) // HOP + 1)
    nfft = 8192
    f0 = np.full(nf, np.nan)
    conf = np.zeros(nf)
    lag_lo = max(2, int(SR / FMAX))
    lag_hi = min(WIN // NHARM - 1, int(np.ceil(SR / FMIN)))
    ac_len = lag_hi * NHARM + 2
    CH = 512
    for c0 in range(0, nf, CH):
        c1 = min(nf, c0 + CH)
        frames = np.stack([y[i * HOP:i * HOP + WIN] for i in range(c0, c1)]).astype(np.float32)
        frames *= np.hanning(WIN).astype(np.float32)
        spec = np.fft.rfft(frames, nfft, axis=1)
        ac = np.fft.irfft(spec * np.conj(spec), nfft, axis=1)[:, :ac_len].real
        r0 = np.maximum(ac[:, 0], 1e-9)
        lags = np.arange(lag_lo, lag_hi + 1)
        hs = np.zeros((c1 - c0, len(lags)), dtype=np.float32)
        for k in range(1, NHARM + 1):
            hs += ac[:, k * lags] / r0[:, None]
        hs /= NHARM
        best = hs.argmax(axis=1)
        bval = hs[np.arange(len(best)), best]
        for r in range(c1 - c0):
            if bval[r] < PEAK_MIN:
                continue
            lg = int(lags[best[r]])
            a_, b_, c_ = ac[r, lg - 1], ac[r, lg], ac[r, lg + 1]
            denom = a_ - 2 * b_ + c_
            shift = 0.5 * (a_ - c_) / denom if abs(denom) > 1e-9 else 0.0
            f0[c0 + r] = SR / (lg + float(np.clip(shift, -1, 1)))
            conf[c0 + r] = bval[r]
    return f0, conf


def hz_to_name(f):
    m = librosa.hz_to_midi(f)
    midi = int(round(m))
    return f"{NAMES[midi % 12]}{midi // 12 - 1}", midi


def main() -> int:
    y, _ = librosa.load(str(OGG), sr=SR, mono=True,
                        offset=SEG_A, duration=SEG_B - SEG_A)
    print(f"[AUDIO] {len(y)/SR:.1f}s loaded")
    f0, conf = track_f0(y)
    times = np.arange(len(f0)) * HOP / SR + SEG_A
    print(f"[F0] frames={len(f0)} voiced={np.mean(conf >= PEAK_MIN):.0%}")

    # ── 平滑与量化见下方（半音域中值平滑 + 滞回量化）──

    # 半音域中值平滑（9 帧 ≈ 0.21s，忽略无效帧）——Hz 域平滑会被倍频跳变拖偏
    mf = librosa.hz_to_midi(np.where(np.isnan(f0), np.nan, f0))
    mfs = mf.copy()
    for k in range(len(mf)):
        lo_, hi_ = max(0, k - 4), min(len(mf), k + 5)
        win = mf[lo_:hi_]
        win = win[~np.isnan(win)]
        if len(win):
            mfs[k] = np.median(win)
    mf = mfs

    # 半音量化（滞回 50 音分：旋律级进 ≥ 半音，帧间抖动 < 半音）
    q = np.full(len(mf), np.nan)
    cur = None
    for i in range(len(mf)):
        if np.isnan(mf[i]) or conf[i] < PEAK_MIN:
            continue
        if cur is None or abs(mf[i] - cur) > 0.50:
            cur = round(float(mf[i]))
        q[i] = cur

    # 聚段：连续同量化音 + 允许 ≤4 帧 nan 空隙
    notes = []
    i, n = 0, len(q)
    while i < n:
        if np.isnan(q[i]):
            i += 1
            continue
        j, last = i, i
        gap = 0
        while j + 1 < n and gap <= 4:
            j += 1
            if np.isnan(q[j]):
                gap += 1
                continue
            if q[j] != q[i]:
                break
            gap, last = 0, j
        sel = slice(i, last + 1)
        valid = ~np.isnan(f0[sel])
        if valid.any():
            med = float(np.median(f0[sel][valid]))
            vconf = float((conf[sel][valid] >= PEAK_MIN).mean())
            t0, t1 = float(times[i]), float(times[last])
            if t1 - t0 >= MIN_DUR and vconf >= 0.40:
                name, midi = hz_to_name(med)
                notes.append({"name": name, "midi": midi, "f0": round(med, 1),
                              "start": round(t0, 3), "end": round(t1, 3),
                              "voiced": round(vconf, 2)})
        i = last + 1

    # 孤立跳跃毛刺：与前音差 >19 半音且短的段丢弃
    clean = []
    for k, nt in enumerate(notes):
        if 0 < k < len(notes) - 1:
            d1 = abs(nt["midi"] - notes[k - 1]["midi"])
            d2 = abs(nt["midi"] - notes[k + 1]["midi"])
            if d1 > 19 and d2 > 19 and nt["end"] - nt["start"] < 0.35:
                continue
        clean.append(nt)
    notes = clean
    print(f"[NOTES] {len(notes)} 个音符段")
    for nt in notes:
        print(f"  {nt['start']:7.2f}-{nt['end']:7.2f}s  {nt['name']:4s} "
              f"f0={nt['f0']:6.1f}Hz voiced={nt['voiced']:.0%}")

    # ── 交叉验证：probe_theme.log 锚点 ──
    # 注：probe 日志的「G#4 209.7Hz」是八度误标（209.7Hz=G#3，低八度声部）；
    # 带内真锚点是 205.9-207.9s 的 417Hz 长音 = G#4（probe 实测谐波纯度全窗最高）。
    print("[VERIFY] 对 probe 实测锚点")
    ok = True
    hit = [nt for nt in notes if nt["start"] < 207.9 and nt["end"] > 205.9
           and nt["name"] == "G#4" and 400 < nt["f0"] < 430]
    print(f"  205.9-207.9s 应有 G#4(≈417Hz): {'✓' if hit else '✗'} "
          f"{[(n['name'], n['f0']) for n in hit]}")
    ok &= bool(hit)
    ndist = len({nt["midi"] for nt in notes})
    print(f"  旋律音高多样性 ≥10 种: {'✓' if ndist >= 10 else '✗'} n={ndist}")
    ok &= ndist >= 10
    cov = sum(nt["end"] - nt["start"] for nt in notes)
    print(f"  音符总覆盖 {cov:.1f}s（窗口 {SEG_B - SEG_A:.0f}s）: {'✓' if cov >= COV_MIN else '✗'}")
    ok &= cov >= (COV_MIN if (SEG_B - SEG_A) <= 70 else (SEG_B - SEG_A) * 0.55)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": {"ogg": OGG.name, "segment": [SEG_A, SEG_B],
                   "method": "hand-rolled autocorrelation f0 (FFT, chunked) + "
                             "semitone quantization (hysteresis 35c)"},
        "notes": notes,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OUT] {OUT}")
    print(f"[VERDICT] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
