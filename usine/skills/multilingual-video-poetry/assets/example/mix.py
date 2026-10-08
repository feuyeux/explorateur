# -*- coding: utf-8 -*-
"""四季成片：BGM 铺底 + 12 语种旁白混音 → 挂到横竖两版视频上。

**视频流直接 `-c:v copy`** —— 慢放已经编过一次（CRF 17），混音只换音轨，
不再重编码画面：24 次挂载从「重渲染」降成「重封装」，画质零损失。

**混音层次**（按前景／底床定，不是拍脑袋）：
  旁白  -16 LUFS（前景，始终听得清）
  BGM   -24 LUFS（底床），被旁白侧链压低 —— **实测 6.6 dB**
        （量法：单独渲一条被压后的 BGM 轨，比「人声段」与「空档段」的均方电平，
          -32.4 dB vs -25.8 dB。两边取自同一条轨，曲子自身力度起伏被抵消。）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from 配文 import LANGS, SEASONS, TOTAL, WINDOWS  # noqa: E402

BGM_CHOICES = {
    # `user` = 用户自己提供的曲子；起点 100s 是**实测**挑的，不是随手填的：
    # 逐 1s 量 RMS 后，整首最饱满的 20s 窗口在 99–119s（均 −10.5 dB）；
    # 而开头 0–20s 只有 −30.9 dB（弱起 + 15–20s 明显塌陷），直接取头会很差。
    "user": ("bgm_user.mp3", 100.0),
    "a": ("piano_a.wav", 0.0),
    "b": ("piano_b.wav", 0.0),
    "c": ("piano_c.wav", 0.0),
}
VOICE_DIR = HERE / "voice"
MIX_DIR = HERE / "mix"
REPORT = json.loads((HERE / "voice-report.json").read_text("utf-8"))
DUR = {(r["lang"], r["season"]): r["duration"] for r in REPORT}

# 旁白落点：季首 + 起拍余量（让画面先换季，声音再进来）
LEAD = 0.55


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # ffmpeg 的真实原因只在 stderr 里，不透出来就只能猜
        raise RuntimeError(f"ffmpeg 失败（{cmd[0]}）:\n{r.stderr[-2500:]}")


def build_mix(lang: str, bgm: Path | None, bgm_start: float = 0.0) -> Path:
    """四段旁白按季首对位落进 20s。

    `bgm=None` → 只出人声干声（BGM 由用户后期自己叠，见 `none`）。
    `bgm_start` → 从曲子第几秒起取（BGM 较长时避开弱起，见 BGM_CHOICES 注释）。
    """
    out = MIX_DIR / f"{lang}.m4a"
    # 每段起点 = 季首 + LEAD；若会顶出该季窗口，则回贴到窗口末尾
    parts, delays = [], []
    # 有 BGM 时它是 [0:a]，旁白从 [1:a] 起；干声模式 BGM 缺席，全部前移一位
    off = 1 if bgm is not None else 0
    for season in SEASONS:
        w0, w1 = WINDOWS[season]
        d = DUR[(lang, season)]
        start = min(w0 + LEAD, max(w0, w1 - d))
        delays.append(int(round(start * 1000)))
        parts.append(f"[{SEASONS.index(season) + off}:a]")
    voice = "".join(f"{p}adelay={ms}|{ms},apad[v{i}];"
                    for i, (p, ms) in enumerate(zip(parts, delays)))
    vjoin = "".join(f"[v{i}]" for i in range(len(parts)))
    vsum = (f"{vjoin}amix=inputs={len(parts)}:normalize=0:duration=longest,"
            f"loudnorm=I=-16:TP=-1.5:LRA=11,apad,atrim=0:{TOTAL}")

    if bgm is None:
        # 干声：不铺底、不侧链。整体压到 -17 LUFS，给后期叠 BGM 留总线限幅余量。
        fc = (voice + vsum
              + f",afade=t=out:st={TOTAL - 1.2}:d=1.2[mix]")
        inputs = [a for s in SEASONS
                  for a in ("-i", str(VOICE_DIR / f"{lang}.{s}.mp3"))]
    else:
        # ⚠️ `asplit=2` 不是可选的，是这个 bug 的修复本身。
        # 同一个 filter 输出 `[voice]` 若被 `sidechaincompress`（当触发轨）和
        # `amix`（当主轨）**同时引用**，ffmpeg 不会自动拆分，结果是人声被整体压掉
        # 25–30 dB —— 实测 t=6.1s 处人声干轨 −15.2 dB，混音只剩 −41.3 dB。
        # 症状是「BGM 忽隐忽现、又听不到人声」：BGM 被侧链压深了，
        # 而本该盖过它的人声根本没进来，只剩 BGM 一头忽强忽弱。
        # 显式拆成 [vm]（主轨，混音用）+ [vs]（触发轨，侧链用）后恢复正常。
        #
        # sidechaincompress 的参数序是 [主][旁白]：BGM 是主轨（被压），
        # 旁白是触发轨（说了算）——方向反了就会变成「有人声才铺底」。
        # 淡出必须收在**画面结束的那一刻**，不能戛然而止，也不能提前哑掉。
        # 这里踩过两个坑，都写在下面：
        #  1. `loudnorm` 排在 `afade` **之后** —— loudnorm 是动态滤镜，自带缓冲，
        #     放在淡出后面会把淡出的尾巴冲掉；实测 BGM 在 17.3s 就变成 -inf 静音，
        #     而画面还剩 2.6s。归一化必须在塑形之前。
        #  2. `atrim` 的终点等于淡出终点 —— 没有余量，淡出其实是在淡曲子自己的结尾，
        #     等于没淡。多取 1 秒源，淡出才有真正的音乐可淡。
        fc = (f"[0:a]atrim=start={bgm_start}:end={bgm_start + TOTAL + 1},"
              f"asetpts=N/SR/TB,"
              f"loudnorm=I=-24:TP=-2:LRA=7,"          # 1 · 归一化在淡出之前
              f"afade=t=in:st=0:d=1.5,"
              f"atrim=0:{TOTAL},"
              f"afade=t=out:st={TOTAL - 3.5}:d=3.5[bg];"   # 2 · 多取 1 秒，淡出收在 19.958s
              + voice + vsum + ",asplit=2[vm][vs];"
              f"[bg][vs]sidechaincompress=threshold=0.02:ratio=8:attack=20:"
              f"release=380:makeup=1[duck];"
              f"[duck][vm]amix=inputs=2:normalize=0:dropout_transition=0,"
              f"alimiter=limit=0.95[mix]")
        inputs = ["-i", str(bgm)]
        for s in SEASONS:
            inputs += ["-i", str(VOICE_DIR / f"{lang}.{s}.mp3")]
    cmd = ["ffmpeg", "-y", "-v", "error"] + inputs
    # edge-tts 是 24k 单声道，loudnorm 会把内部重采样提到 192k，AAC 就写成 96k 单声道
    # —— 白白撑大文件。显式钉回 48k 立体声；`-t` 兜住 apad 的无限尾巴。
    cmd += ["-filter_complex", fc, "-map", "[mix]",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", f"{TOTAL:.3f}", str(out)]
    run(cmd)
    return out


def mux(lang: str, audio: Path) -> list[Path]:
    """挂到**已烧字幕**的 .sub.mp4 上，不是裸的 _20s.mp4 —— 否则字幕被丢掉。"""
    outs = []
    for orient in ("横版", "竖版"):
        src = HERE / f"{orient}四季_{lang}.sub.mp4"
        if not src.exists():
            raise FileNotFoundError(f"缺 {src.name}，先跑 subtitles.py 烧字幕")
        dst = HERE / f"{orient}四季_{lang}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(audio),
             "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart", str(dst)])
        outs.append(dst)
    return outs


def main() -> int:
    # uv run python examples/sijijie/mix.py none   → 只出人声，BGM 后期自己叠
    # uv run python examples/sijijie/mix.py user  → 用用户提供的曲子（从实测最饱满处起）
    # uv run python examples/sijijie/mix.py a|b|c  → 用指定的钢琴候选
    key = (sys.argv[1] if len(sys.argv) > 1 else "user").lower()
    if key == "none":
        bgm, start = None, 0.0
    elif key in BGM_CHOICES:
        name, start = BGM_CHOICES[key]
        p = HERE / name
        if not p.exists():
            print(f"缺 {name}")
            return 2
        bgm = p
    else:
        print(f"BGM 只可选 none/user/{'/'.join(k for k in BGM_CHOICES if k != 'user')}，"
              f"收到 {key!r}")
        return 2
    MIX_DIR.mkdir(exist_ok=True)
    print(f"BGM = {bgm.name if bgm else '（无 · 纯人声干声）'}"
          + (f"  起点 {start:.0f}s" if bgm else "") + "\n")
    print(f"{'语种':<6}{'旁白落点(秒)':<28}成片")
    for lang in LANGS:
        audio = build_mix(lang, bgm, start)
        files = mux(lang, audio)
        starts = []
        for season in SEASONS:
            w0, w1 = WINDOWS[season]
            d = DUR[(lang, season)]
            starts.append(f"{min(w0 + LEAD, max(w0, w1 - d)):.2f}")
        print(f"{lang:<6}{' / '.join(starts):<28}"
              + " · ".join(f.name for f in files))
    print(f"\n{len(LANGS)} 语种 × 2 版 = {len(LANGS) * 2} 条成片（视频流 copy，未重编码）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
