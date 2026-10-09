# -*- coding: utf-8 -*-
"""platform.py — 外部可执行文件（浏览器 / ffmpeg / ffprobe / magick）的跨平台解析，全仓唯一事实源

**它防的两种静默故障**（两次真实事故换来的）：

1. 写死路径在别的系统上直接 file-not-found——而浏览器明明装了；
2. 更阴的：账本类工具读到 `null` 按「不可信 = 保守判过期」处理——
   **每个产物永久判过期、每次全量重做，且没有任何东西报错**。缓存就这么悄悄变成「不存在」。

**为什么 Edge 排在 Chrome 前面**：像素基线是在 Edge 上采的，Edge 在候选首位
才能保证 Windows 渲染结果逐像素不变；macOS / Linux 没装 Edge 时自然落到同为
Chromium 的 Chrome（`--headless=new` / `--screenshot` 用法通用）。

**为什么允许环境变量覆盖**：`FEUILLE_BROWSER=/path/to/chromium` 不碰代码就能换浏览器
做 A/B（字形差异、版本回归）。**显式指定却找不到 = 配置错误，必须返回 None**，
不能静默换人——否则用户以为在对比 A 版，实际渲的是 B 版，A/B 差异正是要量的东西。

**magick 不收 `convert` 做兜底**：Windows 系统自带的 `convert.exe` 是文件系统转换工具，
跟 ImageMagick 毫无关系——按名字兜底会静默调错程序。ImageMagick 7 的命令名就是 `magick`。

**探测不到一律返回 None，绝不编造路径**。调用方拿到 None 必须显式失败并说清缺什么
（`missing()` 就是给报错用的），不能退化成「用系统默认」。
"""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

# ---------------------------------------------------------------- 浏览器候选
# (内核名, 路径或命令名)。**顺序即优先级**：edge 在 chrome 前（像素基线同源），见模块头。
_BROWSERS: tuple[tuple[str, str], ...] = (
    # ---- Windows ----
    ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ("edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ("edge", "msedge"),
    # ---- macOS（.app 内部可执行名 = 产品名）----
    ("edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ("edge", "~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ("edge", "microsoft-edge"),
    # ---- Linux ----
    ("edge", "/usr/bin/microsoft-edge"),
    ("edge", "/opt/microsoft/msedge/msedge"),
    ("edge", "microsoft-edge-stable"),
    # ---- Chromium 同源的 Chrome：Edge 没装时的落点（发布器也用它 + 持久 profile）----
    ("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("chrome", "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("chrome", "google-chrome"),
    ("chrome", "google-chrome-stable"),
    ("chrome", "/usr/bin/google-chrome"),
    ("chrome", "/opt/google/chrome/chrome"),
    ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ("chrome", "chrome"),
    # ---- 最后的兜底 ----
    ("chromium", "chromium"),
    ("chromium", "chromium-browser"),
    ("chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
)

# ffmpeg / ffprobe / magick：先 PATH，再各平台常见安装位。
# Windows 补 scoop 的 shim 目录——它不在 PATH 时会直接说「缺 ffmpeg」，而 ffmpeg 明明装了。
_FFMPEG = ("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
           "/usr/bin/ffmpeg", r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
           r"C:\Users\%USERNAME%\scoop\shims\ffmpeg.exe")
_FFPROBE = ("ffprobe", "/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe",
            "/usr/bin/ffprobe", r"C:\ProgramData\chocolatey\bin\ffprobe.exe",
            r"C:\Users\%USERNAME%\scoop\shims\ffprobe.exe")
_MAGICK = ("magick", "/opt/homebrew/bin/magick", "/usr/local/bin/magick",
           "/usr/bin/magick", r"C:\ProgramData\chocolatey\bin\magick.exe")


def _first(candidates) -> str | None:
    """候选列表 → 第一个真实存在的可执行文件（或 None）。**不编造路径。**"""
    for cand in candidates:
        p = Path(os.path.expandvars(os.path.expanduser(cand)))
        if p.is_file():
            return str(p)
        found = shutil.which(cand)
        if found:
            return found
    return None


def browser(only: str | None = None) -> tuple[str, str] | None:
    """`(内核名, 绝对路径)` 或 None。

    only=None：按候选顺序取第一个（edge → chrome → chromium）——渲字用这个。
    only="chrome"：只认 Chrome——发布器用这个（持久 profile 与 Chrome 绑定；
                  Edge 上没有那些登录态）。
    `FEUILLE_BROWSER` 优先于一切（显式指定找不到 = 配置错误，返回 None，不静默换人）。
    """
    override = os.environ.get("FEUILLE_BROWSER")
    if override:
        p = Path(os.path.expanduser(override))
        if p.is_file():
            return ("custom", str(p))
        found = shutil.which(override)
        if found:
            return ("custom", found)
        return None
    for name, cand in _BROWSERS:
        if only and name != only:
            continue
        p = Path(os.path.expandvars(os.path.expanduser(cand)))
        if p.is_file():
            return (name, str(p))
        found = shutil.which(cand)
        if found:
            return (name, found)
    return None


def browser_path(only: str | None = None) -> str | None:
    b = browser(only)
    return b[1] if b else None


def ffmpeg() -> str | None:
    return _first(_FFMPEG)


def ffprobe() -> str | None:
    return _first(_FFPROBE)


def magick() -> str | None:
    """ImageMagick 7（裁切安全拼图 / 对照图拼版用）。不收 `convert` 兜底，见模块头。"""
    return _first(_MAGICK)


def missing() -> list[str]:
    """缺哪些外部件——供报错与体检如实说「缺什么」。"""
    out = []
    if not browser():
        out.append("浏览器（Edge / Chrome / Chromium 任一，或设 FEUILLE_BROWSER）")
    if not ffmpeg():
        out.append("ffmpeg")
    if not ffprobe():
        out.append("ffprobe")
    if not magick():
        out.append("magick（ImageMagick 7，裁切安全拼图用）")
    return out


def describe() -> dict:
    """本机解析结果——给体检与排障，一眼说清「用的是哪一件」。"""
    b = browser()
    ffm, ffpr, mg = ffmpeg(), ffprobe(), magick()
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "browser": f"{b[0]}: {b[1]}" if b else None,
        "ffmpeg": ffm,
        "ffprobe": ffpr,
        "magick": mg,
        "missing": missing(),
    }
