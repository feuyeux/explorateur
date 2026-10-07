#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_platform.py — 跨平台解析的反向验证（搬运自 explorateur，终态精简）

**它要证的那句话**：「feuille 在 Windows / macOS / Linux 上都能跑。」

这句话在有产物的机器上看起来永远是绿的，全靠记忆——所以把「会不会退化成单平台」
变成断言。四条判据各对应一种真实退化：

1. **代码里不再有写死的可执行文件路径**（explorateur 的坑：写死 Windows Edge 路径
   → macOS 静默失效；yiyezhiqiu 的已核实缺陷③：发布器写死 `/Applications/...` Chrome
   → 跨平台必炸）。判据两条：Windows 盘符路径 + macOS .app 路径，候选表之外不许出现。
2. **浏览器解析落到真实存在的文件上**；`FEUILLE_BROWSER` 指到不存在的路径必须返回 None
   （不静默换人）。
3. **候选全不命中必须返回 None**（拿不到就说拿不到，不编造路径）。
4. **候选表覆盖三套系统**——只列 Windows 的表在 macOS 上必然落空。

**第 0 条纪律是好数据放行**：恒判 FAIL 的检查毫无价值。

（字体栈覆盖、像素基线分桶两条判据待对应模块落地后并入本套。）
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import platform as pt          # noqa: E402

# 写死的可执行文件路径：Windows 盘符，或 macOS .app 内部路径。
# 只查代码，不查文档——文档里出现 `C:\Program Files` 是正常的（说明来龙去脉）。
_WIN_EXE = re.compile(r"""[A-Za-z]:\\?[A-Za-z0-9_ .\\-]+\.(?:exe|cmd|bat)\b""", re.I)
_MAC_APP = re.compile(r"""/Applications/[\w .]+\.app/""")

# 唯一合法例外：候选表自己（它出现系统路径是职责所在；全仓禁止会把候选表拆散成
# 多处，那正是「第二个事实源」的由来）。
ALLOWED = {"src/feuille/platform.py"}


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []

    # ---- 0. 好数据放行：本机在装的件必须解析得到 ----
    import importlib.util
    pyff = importlib.util.find_spec  # noqa: F841  （仅说明：Python 自身已由 uv 保证）
    for name, resolver in (("ffmpeg", pt.ffmpeg), ("ffprobe", pt.ffprobe)):
        installed = shutil.which(name) is not None
        got = resolver()
        if installed:
            rows.append((got is not None, f"本机装有 {name} → resolver 解析到（{got}）"))
        else:
            rows.append((True, f"本机未装 {name}（不算失败；缺件由 missing() 如实报）"))

    # ---- 1. 候选表之外不许写死可执行文件路径 ----
    hits = []
    n_files = 0
    for p in sorted((ROOT / "src").rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        n_files += 1
        if rel in ALLOWED:
            continue
        text = p.read_text("utf-8")
        for m in _WIN_EXE.finditer(text):
            hits.append(f"{rel}: {m.group(0)}")
        for m in _MAC_APP.finditer(text):
            hits.append(f"{rel}: {m.group(0)}")
    rows.append((not hits,
                 f"候选表之外，src/ 里没有写死的可执行路径（扫 {n_files} 个文件，"
                 f"白名单 {sorted(ALLOWED)}）"
                 + (f"　**仍有：{hits[:3]}**" if hits else "")))

    # ---- 2. 浏览器解析 ----
    b = pt.browser()
    rows.append((b is not None,
                 f"浏览器解析到 {b[0]}: {b[1]}" if b
                 else "本机找不到 Chromium 内核浏览器（缺它只是渲不了，解析逻辑由下两条证明）"))
    if b:
        bp = pathlib.Path(b[1])
        rows.append((bp.is_file() and bp.stat().st_mode & 0o111 != 0,
                     f"解析到的浏览器路径真实存在且可执行（{bp.name}）"))

    # 2a. FEUILLE_BROWSER 指到不存在的路径 → 必须 None（不静默换人）
    old = os.environ.get("FEUILLE_BROWSER")
    os.environ["FEUILLE_BROWSER"] = "/nonexistent/definitely-not-a-browser"
    try:
        rows.append((pt.browser() is None,
                     "FEUILLE_BROWSER 指向不存在的文件 → 返回 None（不静默换浏览器）"))
    finally:
        if old is None:
            os.environ.pop("FEUILLE_BROWSER", None)
        else:
            os.environ["FEUILLE_BROWSER"] = old

    # 2b. only="chrome" 只认 chrome 候选——拿到的一定是 chrome（或 None）
    cb = pt.browser(only="chrome")
    rows.append((cb is None or cb[0] == "chrome",
                 f"browser(only='chrome') 不会落到别家内核（得到 {cb[0] if cb else None}）"))

    # ---- 3. 候选全不命中 → None，不编造 ----
    rows.append((pt._first(["/nonexistent/a", "definitely-not-a-command-xyz"]) is None,
                 "候选全不命中 → 返回 None（拿不到就说拿不到，不编造路径）"))

    # ---- 4. 候选表覆盖三套系统 ----
    cands = [c for _, c in pt._BROWSERS]
    has_win = any(re.match(r"[A-Za-z]:", c) for c in cands)
    has_mac = any(c.startswith("/Applications/") for c in cands)
    has_nix = any("/usr/bin/" in c or "/opt/" in c for c in cands)
    rows.append((has_win and has_mac and has_nix,
                 f"浏览器候选表 {len(cands)} 条，覆盖 Windows/macOS/Linux"
                 f"（win={has_win} mac={has_mac} nix={has_nix}）"))

    # magick 解析同样不许编造；且绝不能用 convert 兜底（Windows 的 convert 是文件系统工具）
    rows.append((all("convert" not in c for c in pt._MAGICK),
                 "magick 候选表不含 convert（Windows 系统自带 convert.exe 是文件系统工具）"))
    rows.append((pt._first(["/nonexistent/magick", "definitely-not-magick-xyz"]) is None,
                 "magick 候选全不命中 → None"))
    return rows


def main() -> int:
    print("=" * 72)
    print("跨平台：外部件解析（浏览器 / ffmpeg / ffprobe / magick）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：跨平台解析 {len(rows) - fails}/{len(rows)} 项")
    if fails:
        print(f"缺件清单（missing()）：{pt.missing()}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
