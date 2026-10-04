#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""framehash — 成片逐帧哈希基线工具（P2-4 视觉基线库的地基）。

**判据是什么**：`ffmpeg -f hash` 算的是**解码后每一帧像素**的 MD5，不是容器字节。
容器会因为 mux 参数、时间戳写入顺序而变，字节哈希一碰就红；像素哈希只在**画面真的变了**
的时候才红——这正是「重构不许改画面」这条纪律需要的那个判据。

    uv run python scripts/framehash.py                      # 对照 build/baseline/framehash-before.txt
    uv run python scripts/framehash.py --baseline p1.txt     # 换基线
    uv run python scripts/framehash.py --save p1.txt         # 把当前状态写成新基线
    uv run python scripts/framehash.py --dir build/scene --glob 'scene-colors_*.mp4'

退出码：0 全一致 / 1 有差异或缺失（可直接当门禁用）。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DIRS = ("build/intro", "build/scene")
DRIFT_DIR = ROOT / "build/baseline/drift"
REF_DIR = ROOT / "build/baseline/ref"
FPS_DEFAULT = 30.0


def framehash(path: pathlib.Path) -> str:
    """解码后全部帧的像素 MD5。失败即抛——静默跳过等于把「渲坏了」当成「不在基线里」。

    **`-map 0:v` 是承重的**（2026-10-04 实测）：少了它 ffmpeg 走默认流选择，同一支片子
    算出来是 `e94654c8…`，加上才是 `de149ce1a0ee…`——**不报错、不警告，只是数字不同**。
    基线 `framehash-before.txt` 与 qa_scene/qa_motion 的幂等判据用的都是带 `-map` 的口径，
    换口径 = 拿一把不同的尺子去量，会得出「全部漂移」的假结论（46/48 全红）。
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v",
         "-f", "hash", "-hash", "md5", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg hash 失败 {path.name}: {r.stderr.strip()}")
    for line in r.stdout.splitlines():
        if line.startswith("MD5="):
            return line.strip()
    raise RuntimeError(f"ffmpeg 未输出 MD5：{path.name}")


# ---------- P2-4：逐帧基线与漂移定位 ----------

def per_frame(path: pathlib.Path) -> list[str]:
    """逐帧像素 MD5 列表。

    整支一个 MD5 只能回答「变了/没变」，**回答不了「哪一帧开始变的」**——而后者才是
    定位回归时唯一有用的信息：第 137 帧 / t=4.57s 足以让人去查那 0.1 秒发生了什么。
    `-map 0:v` 同样承重，理由见 framehash()。
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v",
         "-f", "framehash", "-hash", "md5", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg framehash 失败 {path.name}: {r.stderr.strip()}")
    return [ln.split(",", 1)[1].strip()
            for ln in r.stdout.splitlines() if ln and not ln.startswith("#")]


def probe_fps(path: pathlib.Path) -> float:
    """容器帧率（把帧号换算成秒）。读不到就退回 30——只影响报告里的时间标注。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=avg_frame_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        num, _, den = r.stdout.strip().partition("/")
        f = float(num) / float(den)
        return f if f > 0 else FPS_DEFAULT
    except Exception:                                       # noqa: BLE001
        return FPS_DEFAULT


def first_drift(ref: list[str], cur: list[str]) -> tuple[int | None, int | None]:
    """(第一处不同的帧号, 末处不同的帧号)。帧数不同也算漂移。

    **帧数不同必须单独判**：只比公共长度的话，「少了几帧尾巴」会被当成一致——
    而丢帧正是 -shortest 时机性丢内部视频帧那类事故（手册坑⑯）的症状。
    """
    n = min(len(ref), len(cur))
    first = next((i for i in range(n) if ref[i] != cur[i]), None)
    last = next((i for i in range(n - 1, -1, -1) if ref[i] != cur[i]), None)
    if first is None and len(ref) != len(cur):
        first = last = n
    return first, last


def extract_frame(video: pathlib.Path, index: int, out_png: pathlib.Path) -> bool:
    """抽出第 index 帧存 PNG 当证据图。失败返回 False（不抛——证据图是辅助，不是判据）。"""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", "0:v",
         "-vf", f"select=eq(n\\,{index})", "-vsync", "0", "-frames:v", "1", str(out_png)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and out_png.exists()


def diff_png(ref_png: pathlib.Path, cur_png: pathlib.Path, out_png: pathlib.Path) -> bool:
    """参考帧 vs 当前帧的差异热力图（红=差得多）。没有参考帧就诚实地返回 False。

    **不做「假装有参考」的合成图**：没有 ref 就没有差异图，只报帧号——
    造一张看起来很像差异图的图片，比不给更坏。
    """
    try:
        from PIL import Image, ImageChops
    except Exception:                                       # noqa: BLE001
        return False
    if not (ref_png.exists() and cur_png.exists()):
        return False
    a = Image.open(ref_png).convert("RGB")
    b = Image.open(cur_png).convert("RGB")
    if a.size != b.size:
        return False
    d = ImageChops.difference(a, b).convert("L")
    d = d.point(lambda v: min(255, v * 6))                # 放大微弱差异，否则肉眼全黑
    heat = Image.merge("RGB", (d, d.point(lambda v: 255 - v), Image.new("L", d.size, 255)))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    heat.save(out_png)
    return True


def collect(dirs, pattern: str | None) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in dirs:
        p = ROOT / d
        if not p.is_dir():
            continue
        out += sorted(p.glob(pattern or "*.mp4"))
    return out


def read_baseline(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"基线不存在：{path}")
    out = {}
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        name, h = line.split()
        out[name] = h
    return out


def classify(base: dict[str, str], cur: dict[str, str], subset: bool) -> dict:
    """比对结果分桶。抽成纯函数是为了能拿已知数据反向验证（见 selftest）。

    `subset=True`（本次只查 --dir/--glob 子集）时，基线里不在范围内的条目归 `skipped`
    而**不是** `gone`——否则一次合法的子集核查就会报 FAIL。
    """
    missing = sorted(set(base) - set(cur))
    return {
        "same": [n for n in sorted(cur) if n in base and base[n] == cur[n]],
        "diff": [n for n in sorted(cur) if n in base and base[n] != cur[n]],
        "new": sorted(set(cur) - set(base)),
        "gone": [] if subset else missing,
        "skipped": missing if subset else [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", default=None, help=f"目录，可重复（默认 {' '.join(DEFAULT_DIRS)}）")
    ap.add_argument("--glob", default=None, help="文件名通配（默认 *.mp4）")
    ap.add_argument("--baseline", default=str(ROOT / "build/baseline/framehash-before.txt"))
    ap.add_argument("--save", default=None, help="把当前结果写到这个基线文件后退出")
    ap.add_argument("--save-frames", default=None, metavar="DIR",
                    help="把每支成片的**逐帧** MD5 写进 DIR/<name>.frames.txt（P2-4 视觉基线库）")
    ap.add_argument("--locate", action="store_true", help="发现整支漂移时进一步定位到帧号并抽证据图")
    ap.add_argument("--drift-limit", type=int, default=1, help="每支最多抽几帧证据图（默认 1）")
    args = ap.parse_args()

    dirs = args.dir or list(DEFAULT_DIRS)
    # 显式指定了 --dir/--glob = 这次只想查一个子集。此时基线里「不在本次范围内」的条目
    # 根本不是 GONE，把它算成缺失会让一次合法的子集核查报 FAIL——**门禁喊狼嚎比没门禁更坏**
    # （与坑㉛ 同源：拿不合法的口径去判，会得到「全红」的假结论）。
    subset = args.dir is not None or args.glob is not None

    videos = collect(dirs, args.glob)
    if not videos:
        raise SystemExit(f"没找到成片：dirs={dirs} glob={args.glob}")

    if args.save_frames:
        out = pathlib.Path(args.save_frames)
        out.mkdir(parents=True, exist_ok=True)
        for p in videos:
            (out / f"{p.name}.frames.txt").write_text("\n".join(per_frame(p)), "utf-8")
        print(f"已写逐帧基线 {len(videos)} 支 → {out}")
        return 0

    cur = {p.name: framehash(p) for p in videos}

    if args.save:
        target = pathlib.Path(args.save)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(f"{n}  {cur[n]}\n" for n in sorted(cur)), "utf-8")
        print(f"已写基线 {len(cur)} 行 → {target}")
        return 0

    base = read_baseline(pathlib.Path(args.baseline))
    r = classify(base, cur, subset)

    print("=" * 72)
    scope = "（子集核查）" if subset else ""
    print(f"逐帧像素基线：{len(r['same'])}/{len(cur)} 一致{scope}　"
          f"（基线 {len(base)} 行 / 当前 {len(cur)} 支）")
    print("=" * 72)
    for n in r["diff"]:
        print(f"  [DRIFT] {n}  {base[n]} → {cur[n]}")
    for n in r["new"]:
        print(f"  [NEW]   {n}  {cur[n]}")
    for n in r["gone"]:
        print(f"  [GONE]  {n}  基线里有、当前没有")
    if r["skipped"]:
        print(f"  [跳过]  基线中另有 {len(r['skipped'])} 支不在本次 --dir/--glob 范围内，未参与比对")
    if not (r["diff"] or r["new"] or r["gone"]):
        print("  零漂移：全部成片逐帧一致")

    # P2-4：整支漂移的，落到「哪一帧」并抽证据图
    if r["diff"] and args.locate:
        locate(r["diff"], cur, base, subset, args.drift_limit)
    return 1 if (r["diff"] or r["gone"]) else 0


def locate(names, cur, base, subset, limit: int) -> None:
    """漂移定位：逐帧基线 → 第一处不同的帧号/秒 → 抽证据图（有参考帧就给差异热力图）。"""
    fbase = ROOT / "build/baseline/frames"
    print("-" * 72)
    print("漂移定位（逐帧基线）")
    print("-" * 72)
    for n in names:
        ref_file = fbase / f"{n}.frames.txt"
        if not ref_file.exists():
            print(f"  [?] {n}：没有逐帧基线（{ref_file.name}）——"
                  f"先跑 `--save-frames <路径>` 采集；只报整支漂移")
            continue
        ref = ref_file.read_text("utf-8").split()
        got = per_frame(ROOT / "build/intro" / n) if (ROOT / "build/intro" / n).exists() \
            else per_frame(ROOT / "build/scene" / n)
        f, l = first_drift(ref, got)
        if f is None:
            print(f"  [?] {n}：整支 MD5 不同但逐帧一致（容器/编码层差异，画面没变）")
            continue
        fps = probe_fps(ROOT / "build/intro" / n if (ROOT / "build/intro" / n).exists()
                        else ROOT / "build/scene" / n)
        ndiff = sum(1 for i in range(min(len(ref), len(got))) if ref[i] != got[i])
        print(f"  [DRIFT] {n}：第 {f} 帧（t={f / fps:.2f}s）起，末处第 {l} 帧，"
              f"共 {ndiff}/{min(len(ref), len(got))} 帧不同"
              + (f"，帧数 {len(ref)}→{len(got)}" if len(ref) != len(got) else ""))
        for k in range(min(limit, 1)):
            idx = f + k
            video = ROOT / "build/intro" / n if (ROOT / "build/intro" / n).exists() \
                else ROOT / "build/scene" / n
            cur_png = DRIFT_DIR / f"{n}.f{idx}.png"
            if extract_frame(video, idx, cur_png):
                ref_png = REF_DIR / f"{n}.f{idx}.png"
                dp = DRIFT_DIR / f"{n}.f{idx}.diff.png"
                if diff_png(ref_png, cur_png, dp):
                    print(f"          证据图 {cur_png.relative_to(ROOT)} + 差异热力图 {dp.relative_to(ROOT)}")
                else:
                    print(f"          证据图 {cur_png.relative_to(ROOT)}"
                          f"（无参考帧 {ref_png.name}，只给当前帧不伪造差异图）")


# ---------- 反向验证：拿已知坏数据证明这道门禁真的会红 ----------
# 「全绿」本身证明不了什么——一个恒返回「一致」的脚本也全绿。这里造三支坏片子喂进去，
# 要求每一支都被判成漂移；再把原片子喂回去要求放行。

def selftest() -> int:
    """-c:v copy 重封一只 mp4 但换像素（如叠加噪点滤镜）→ 必须是 DRIFT。"""
    print("=" * 72)
    print("反向验证：注入已知坏成片，framehash 门禁必须判 DRIFT")
    print("=" * 72)
    src = next(iter(collect(("build/intro",), None)), None)
    if src is None:
        print("  [SKIP] 没有可用的成片，跳过反向验证")
        return 0
    tmp = ROOT / "build/baseline/_fh_selftest.mp4"
    fails = 0

    good = framehash(src)
    print(f"  样本：{src.name}  {good}")

    cases = [
        ("改一帧像素（eq=brightness=0.06）",
         ["-vf", "eq=brightness=0.06:enable='eq(n\\,100)'"]),
        ("改色度（hue=h=90）",
         ["-vf", "hue=h=90"]),
        ("抽掉 1/10 的帧（帧数变了，像素序列必变）",
         ["-vf", "select='not(mod(n\\,10))'", "-vsync", "vfr"]),
    ]
    for desc, extra in cases:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src), *extra,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-an", str(tmp)],
            capture_output=True, text=True)
        if r.returncode != 0 or not tmp.exists():
            print(f"  [FAIL] {desc} → 造坏数据失败：{r.stderr.strip()[:120]}")
            fails += 1
            continue
        bad = framehash(tmp)
        ok = bad != good
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc} → {bad[:19]}… "
              + ("（已判漂移）" if ok else "（竟然判成一致——门禁恒真）"))
        fails += not ok
    tmp.unlink(missing_ok=True)

    # 分桶逻辑的反向验证：造四种已知输入，要求分类结果逐条对上。
    print("-" * 72)
    B = {"a.mp4": "MD5=1", "b.mp4": "MD5=2", "c.mp4": "MD5=3"}
    buckets = [
        ("全一致", {"a.mp4": "MD5=1", "b.mp4": "MD5=2", "c.mp4": "MD5=3"}, False,
         dict(same=["a.mp4", "b.mp4", "c.mp4"], diff=[], new=[], gone=[], skipped=[])),
        ("像素变了", {"a.mp4": "MD5=X", "b.mp4": "MD5=2", "c.mp4": "MD5=3"}, False,
         dict(same=["b.mp4", "c.mp4"], diff=["a.mp4"], new=[], gone=[], skipped=[])),
        ("整支不见了（全量核查必须报 GONE）",
         {"a.mp4": "MD5=1", "b.mp4": "MD5=2"}, False,
         dict(same=["a.mp4", "b.mp4"], diff=[], new=[], gone=["c.mp4"], skipped=[])),
        ("整支不见了（子集核查**不能**报 GONE，否则合法跑法被误判）",
         {"a.mp4": "MD5=1", "b.mp4": "MD5=2"}, True,
         dict(same=["a.mp4", "b.mp4"], diff=[], new=[], gone=[], skipped=["c.mp4"])),
        ("新增一支（只提示不判失败）",
         {**{"a.mp4": "MD5=1", "b.mp4": "MD5=2", "c.mp4": "MD5=3"}, "d.mp4": "MD5=4"}, False,
         dict(same=["a.mp4", "b.mp4", "c.mp4"], diff=[], new=["d.mp4"], gone=[], skipped=[])),
    ]
    for desc, cur, sub, want in buckets:
        got = classify(B, cur, sub)
        ok = got == want
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}"
              + ("" if ok else f" → 得到 {got}，应为 {want}"))
        fails += not ok

    # P2-4 定位的精确性：改了第 N 帧，first_drift 必须**恰好**报 N。
    # 判据取「精确到那一帧」而不是「报了个漂移」——后者是随便哪个恒真实现都能过的。
    #
    # **对照与被测都用无损编码**（`libx264 -qp 0`）。这一点是被逼出来的：
    # 先用有损的 `crf=18` 试，「改第 37 帧」定位到第 **28** 帧，恒定偏 −8/−9。
    # 原因是 x264 的 rate-control lookahead（默认 40 帧）与 B 帧金字塔——改一帧会
    # 改变前后若干帧的码率分配，**有损重编码本来就会扰动邻近帧**。所以：
    #   · 尺子（对照）必须和被测物走同一条编码路径，否则量的是编码噪声；
    #   · 有损重编码会引入最多 ~12 帧（0.4s）的定位误差——真要精确定位请用无损对照。
    print("-" * 72)
    print("逐帧定位：改第 N 帧 → 必须精确定位到 N（无损对照，隔离编码噪声）")
    print("-" * 72)
    LOSS = ["-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an"]
    ctrl = ROOT / "build/baseline/_fh_ctrl.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *LOSS, str(ctrl)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not ctrl.exists():
        print("  [FAIL] 造对照组失败")
        fails += 1
    else:
        ctrl_frames = per_frame(ctrl)
        noisy = per_frame(src) != ctrl_frames
        print(f"  [{'PASS' if not noisy else 'FAIL'}] 无损对照与原片逐帧一致"
              f"（{'不一致' if noisy else '一致'}——不一致就说明对照没起到隔离作用）")
        fails += noisy
        for n_expect in (0, 37, 100, len(ctrl_frames) - 1):
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(src),
                 "-vf", f"eq=brightness=0.08:enable='eq(n\\,{n_expect})'", *LOSS, str(tmp)],
                capture_output=True, text=True)
            if r.returncode != 0 or not tmp.exists():
                print(f"  [FAIL] 改第 {n_expect} 帧 → 造坏数据失败")
                fails += 1
                continue
            f, _l = first_drift(ctrl_frames, per_frame(tmp))
            ok = f == n_expect
            print(f"  [{'PASS' if ok else 'FAIL'}] 改第 {n_expect} 帧 → 定位到第 {f} 帧"
                  + ("" if ok else "（定位不准——比只报漂移更坏：会把人引到错误的时间点）"))
            fails += not ok
        # 丢尾巴（帧数变少）也必须被抓住
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(ctrl),
             "-vf", "select='lt(n\\,{})'".format(len(ctrl_frames) - 5), "-vsync", "vfr",
             *LOSS, str(tmp)],
            capture_output=True, text=True)
        if r.returncode == 0 and tmp.exists():
            got_frames = per_frame(tmp)
            f, _l = first_drift(ctrl_frames, got_frames)
            ok = len(got_frames) < len(ctrl_frames) and f is not None
            print(f"  [{'PASS' if ok else 'FAIL'}] 砍掉最后 5 帧（{len(ctrl_frames)}→{len(got_frames)}）"
                  f" → 必须判漂移（定位到第 {f} 帧）")
            fails += not ok
        else:
            print("  [FAIL] 砍尾巴：造坏数据失败")
            fails += 1
    ctrl.unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)

    total = len(cases) + len(buckets) + 7
    print(f"\n{'OK' if not fails else 'FAIL'}：反向验证 {total - fails}/{total} 条生效")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
