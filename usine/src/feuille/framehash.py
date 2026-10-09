# -*- coding: utf-8 -*-
"""framehash.py — 成片逐帧像素基线（⑬ 验收检查的像素判据）

root 参数化；ffmpeg / ffprobe 走 `feuille.platform` 解析。

**判据是什么**：`ffmpeg -f hash` 算的是**解码后每一帧像素**的 MD5，不是容器字节。
容器会因 mux 参数、时间戳写入顺序而变，字节哈希一碰就红；像素哈希只在
**画面真的变了**时才红——这正是「重构不许改画面」需要的那个判据。

**`-map 0:v` 是承重的**（实测）：少了它 ffmpeg 走默认流选择，同一支片子算出来
是不同数字——**不报错、不警告，只是数字不同**。换口径 = 拿另一把尺子量，
会得出「全部漂移」的假结论。

**基线按平台分桶**（桶 = 系统 + 架构 + 浏览器 + Pillow；ffmpeg 不进桶——它是合成器，
不参与逐帧像素，入桶只会让基线无谓失效）。跨平台的逐帧像素**本来就不可能一致**
（系统字体 → 字形栅格化不同），每台机器各采一份、互不比较；判据仍是
「与**本机**上次渲的相比有没有变」。共用一份基线 = 长期全红的假门禁，
而长期全红会被当噪音忽略——比没有门禁更糟。

帧数不同也算漂移且**必须单独判**：只比公共长度的话，「少了几帧尾巴」会被当成一致
——丢帧正是 -shortest 那类时机性事故的症状。
"""
from __future__ import annotations

import platform as _platform
import subprocess
from pathlib import Path

from . import platform as _pt

FPS_DEFAULT = 30.0


def framehash(path) -> str:
    """解码后全部帧的像素 MD5。失败即抛——静默跳过等于把「渲坏了」当「不在基线里」。"""
    ffmpeg = _pt.ffmpeg()
    if ffmpeg is None:
        raise SystemExit("缺 ffmpeg（resolver 未找到）")
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v",
         "-f", "hash", "-hash", "md5", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg hash 失败 {Path(path).name}: {r.stderr.strip()}")
    for line in r.stdout.splitlines():
        if line.startswith("MD5="):
            return line.strip()
    raise RuntimeError(f"ffmpeg 未输出 MD5：{Path(path).name}")


def per_frame(path) -> list[str]:
    """逐帧像素 MD5 列表。整支一个 MD5 只能回答「变没变」，
    回答不了「哪一帧开始变」——而那才是定位回归唯一有用的信息。"""
    ffmpeg = _pt.ffmpeg()
    if ffmpeg is None:
        raise SystemExit("缺 ffmpeg（resolver 未找到）")
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v",
         "-f", "framehash", "-hash", "md5", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg framehash 失败 {Path(path).name}: {r.stderr.strip()}")
    return [ln.split(",", 1)[1].strip()
            for ln in r.stdout.splitlines() if ln and not ln.startswith("#")]


def probe_fps(path) -> float:
    ffprobe = _pt.ffprobe()
    if ffprobe is None:
        return FPS_DEFAULT
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=avg_frame_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        num, _, den = r.stdout.strip().partition("/")
        f = float(num) / float(den)
        return f if f > 0 else FPS_DEFAULT
    except Exception:                                       # noqa: BLE001
        return FPS_DEFAULT


def first_drift(ref: list[str], cur: list[str]) -> tuple[int | None, int | None]:
    """(第一处不同的帧号, 末处不同的帧号)。帧数不同也算漂移（坑⑯ 的症状）。"""
    n = min(len(ref), len(cur))
    first = next((i for i in range(n) if ref[i] != cur[i]), None)
    last = next((i for i in range(n - 1, -1, -1) if ref[i] != cur[i]), None)
    if first is None and len(ref) != len(cur):
        first = last = n
    return first, last


def extract_frame(video, index: int, out_png) -> bool:
    """抽第 index 帧存 PNG 当证据图。失败返回 False（证据图是辅助，不是判据）。"""
    ffmpeg = _pt.ffmpeg()
    if ffmpeg is None:
        return False
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(video), "-map", "0:v",
         "-vf", f"select=eq(n\\,{index})", "-vsync", "0", "-frames:v", "1", str(out_png)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and out_png.exists()


def diff_png(ref_png, cur_png, out_png) -> bool:
    """参考帧 vs 当前帧差异热力图（红=差得多）。没有参考帧就诚实返回 False——
    **不做「假装有参考」的合成图**：造一张像差异图的图比不给更坏。"""
    try:
        from PIL import Image, ImageChops
    except Exception:                                       # noqa: BLE001
        return False
    ref_png, cur_png = Path(ref_png), Path(cur_png)
    if not (ref_png.exists() and cur_png.exists()):
        return False
    a = Image.open(ref_png).convert("RGB")
    b = Image.open(cur_png).convert("RGB")
    if a.size != b.size:
        return False
    d = ImageChops.difference(a, b).convert("L")
    d = d.point(lambda v: min(255, v * 6))          # 放大微弱差异，否则肉眼全黑
    heat = Image.merge("RGB", (d, d.point(lambda v: 255 - v), Image.new("L", d.size, 255)))
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    heat.save(out_png)
    return True


# ---------------------------------------------------------------- 分桶

def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in ".-" else "-" for c in s.lower())


def bucket() -> str:
    """本机像素桶标识（故意**可读**不取哈希：「基线为什么全红」需要一眼看出
    是平台不同还是浏览器换了）。桶 = 系统 + 架构 + 浏览器 + Pillow。"""
    b = _pt.browser()
    name = b[0] if b else "no-browser"
    try:
        import PIL
        pillow = PIL.__version__
    except Exception:                                       # noqa: BLE001
        pillow = "no-pillow"
    return "-".join([_slug(_platform.system() or "unknown"),
                     _slug(_platform.machine() or "unknown"),
                     _slug(name), _slug(f"pillow{pillow}")])


def baseline_path(root, bucket_id: str | None = None) -> Path:
    return Path(root) / "build" / "baseline" / f"framehash-{bucket_id or bucket()}.txt"


def read_baseline(path) -> dict[str, str]:
    """基线表 → {成片文件名: 哈希}。不存在返回空表不抛——
    「没有基线 → 明确报错」由 compare 层负责，这里只读。"""
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for ln in path.read_text("utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            name, _, h = ln.partition("  ")
            if h:
                out[name.strip()] = h.strip()
    return out


def save_baseline(hashes: dict[str, str], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{n}  {hashes[n]}\n" for n in sorted(hashes)), "utf-8")
    return path


def classify(base: dict[str, str], cur: dict[str, str], subset: bool) -> dict:
    """比对结果分桶（纯函数，供反向验证）。`subset=True`（--dir/--glob 子集核查）时，
    基线里不在范围内的条目归 skipped 而**不是** gone——否则一次合法的子集核查
    就会报 FAIL（门禁喊狼嚎比没门禁更坏）。"""
    missing = sorted(set(base) - set(cur))
    return {
        "same": [n for n in sorted(cur) if n in base and base[n] == cur[n]],
        "diff": [n for n in sorted(cur) if n in base and base[n] != cur[n]],
        "new": sorted(set(cur) - set(base)),
        "gone": [] if subset else missing,
        "skipped": missing if subset else [],
    }


def compare(videos, baseline_file, *, subset: bool = False,
            locate: bool = False, drift_limit: int = 1, ref_dir=None) -> tuple[dict, int]:
    """当前成片集 vs 基线。返回 (分类结果, 退出码 0/1)。定位模式另抽证据图与差异热力图。"""
    videos = [Path(v) for v in videos]
    if not videos:
        raise SystemExit("没找到成片：videos 为空")
    cur = {p.name: framehash(p) for p in videos}
    base = read_baseline(baseline_file)
    r = classify(base, cur, subset)
    print("=" * 72)
    print(f"逐帧像素基线：{len(r['same'])}/{len(cur)} 一致"
          f"{'（子集核查）' if subset else ''}　（基线 {len(base)} 行 / 当前 {len(cur)} 支）")
    print("=" * 72)
    for n in r["diff"]:
        print(f"  [DRIFT] {n}  {base.get(n, '?')} → {cur[n]}")
    for n in r["new"]:
        print(f"  [NEW]   {n}  {cur[n]}")
    for n in r["gone"]:
        print(f"  [GONE]  {n}  基线里有、当前没有")
    if r["skipped"]:
        print(f"  [跳过]  基线中另有 {len(r['skipped'])} 支不在本次范围内，未参与比对")
    if not (r["diff"] or r["new"] or r["gone"]):
        print("  零漂移：全部成片逐帧一致")
    if locate and r["diff"] and ref_dir is not None:
        ref_dir = Path(ref_dir)
        ref_dir.mkdir(parents=True, exist_ok=True)
        for name in r["diff"][:drift_limit]:
            video = next(v for v in videos if v.name == name)
            frames = per_frame(video)
            ref_file = ref_dir / f"{name}.frames.txt"
            if not ref_file.exists():        # 基线只存整支哈希时，帧级定位无从谈起
                continue
            ref = ref_file.read_text("utf-8").splitlines()
            first, last = first_drift(ref, frames)
            if first is None:
                continue
            fps = probe_fps(video)
            print(f"    {name}: 第 {first} 帧漂移（t={first / fps:.2f}s），"
                  f"末异帧 {last}；参考帧 {len(ref)} vs 当前 {len(frames)}")
            extract_frame(video, first, ref_dir / f"{name}-cur-{first}.png")
    return r, 1 if (r["diff"] or r["gone"]) else 0


# ---- CLI 适配层（feuille framehash save|check）--------------------------------
# 库函数已有全部判据；叶子只做「发现产物 → 调库 → 定退出码」的薄编排。
# 与 covers.main_make/main_check 同一形态：路由表只登记无参可调用的 main*。


def _discover_videos(root) -> list[Path]:
    """build/ 下全部成片（全量发现——子集基线会随目录演变而烂）。

    没有产物时显式报错退出，绝不静默产出一个空基线（坑㉟ 的病：
    「筛不中照样成功退出」比报错危险得多）。
    """
    build = Path(root) / "build"
    if not build.is_dir():
        raise SystemExit(f"没有 build/ 目录（root={root}）——基线登记的是产物，先有产物")
    vids = sorted(build.rglob("*.mp4"))
    if not vids:
        raise SystemExit(f"build/ 下没有 mp4（root={root}）——没找到成片，videos 为空")
    return vids


def main_save(argv=None) -> int:
    """cli.py 路由入口：`feuille framehash save [--root DIR]`。

    采基线：build/ 全部成片的整支像素哈希 → 按平台分桶落盘（baseline_path）。
    **坑㉞ 的纪律内建**：采完立刻回读自证——落盘表逐条与当前哈希一致才算数；
    不回读的话，「采基线」这个动作本身就可能是把当时的 bug 固化成标准。
    """
    import argparse
    ap = argparse.ArgumentParser(prog="feuille framehash save")
    ap.add_argument("--root", default=".", help="项目根（build/ 与基线文件所在层）")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    cur = {p.name: framehash(p) for p in _discover_videos(root)}
    out = save_baseline(cur, baseline_path(root))
    back = read_baseline(out)
    mismatch = [n for n, h in cur.items() if back.get(n) != h]
    extra = [n for n in back if n not in cur]
    if mismatch or extra:
        raise SystemExit(f"基线回读自证失败（写 {len(cur)} 读 {len(back)}）："
                         f"不符 {mismatch[:3]} 多出 {extra[:3]} → {out}")
    print(f"基线已采：{len(cur)} 支 → {out}")
    print(f"分桶：{bucket()}（基线按平台分桶，跨平台不可比）")
    return 0


def main_check(argv=None) -> int:
    """cli.py 路由入口：`feuille framehash check [--root DIR] [--subset]`。

    门禁：当前 build/ 全部成片 vs 基线。退出码沿用 `compare` 的口径
    （diff 或 gone → 1）；`--subset` 时基线里不在本次范围的条目归跳过、不判缺失
    ——否则一次合法的子集核查就会喊狼嚎，长期全红会被当噪音忽略。
    """
    import argparse
    ap = argparse.ArgumentParser(prog="feuille framehash check")
    ap.add_argument("--root", default=".", help="项目根")
    ap.add_argument("--subset", action="store_true",
                    help="子集核查：基线中不在 build/ 范围内的条目按跳过计，不判缺失")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    _, rc = compare(_discover_videos(root), baseline_path(root), subset=a.subset)
    return rc
