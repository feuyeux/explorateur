#!/usr/bin/env python3
"""browser_shim.py —— 跑批专用的浏览器垫片：headless 渲染**不碰用户钥匙串**。

## 这层垫片解决什么（2026-10-20 实测，不是推测）

**先说清楚事实，别把两件事混成一件**（这一段是查完才写的）：

- 用户报的 macOS 钥匙串弹窗，**取证结论是「不是跑批拉起来的」**：弹窗宿主是
  `SecurityAgent`，那一次申请钥匙串的是
  `~/.cache/puppeteer/chrome/mac_arm-152.0.7977.42/…/Google Chrome for Testing`
  （**puppeteer 装的 CfT**，而且是 headful），它的 `responsible` 是
  `com.minimax.agent.cn`（**本助手自己的运行时**，不是跑批）。dsh 运行时里
  没有浏览器工具，跑批的工具面里也没有 browser 工具。
- **但跑批自己确实有一个同类的隐患**：基准智能体在海报格里**手搓浏览器**——
  冻结的 `skills/one-page-poster/SKILL.md` 第 6 步就写着
  `google-chrome --headless --dump-dom "file://…?verify=1"`，而它的命令行里
  **没有** `--use-mock-keychain --password-store=basic`（那对旗标只在工具面
  自己的启动点上有，`usine/packages/core/src/platform.ts:155`）。
  **手册教智能体走的那条命令，违反了本仓「headless 渲染绝不碰用户钥匙串」的纪律。**

所以这层垫片是**跑批边界的加固**（把「被测对象教出来的钥匙串风险」挡在跑批外），
不是「弹窗的修复」——弹窗的真凶在别处（见 `BENCH-APPENDIX-2026-10.md` §16.1）。

## 受控实验记录（2026-10-20，同一条命令，变量只有一个）

| 场景 | 钥匙串弹窗 | 退出码 |
|---|---|---|
| 真实 HOME + 真实 profile | 无（`Chrome Safe Storage` 早就在，ACL 已信它） | 0 |
| 真实 HOME + 全新 `--user-data-dir` | **无** | 0 |
| **沙箱 HOME**（`HOME=/tmp/xxx`）+ 全新 profile | **有**（要去新建/解密钥匙串项） | **2**（挂死） |
| 上述任一 + `--use-mock-keychain --password-store=basic` | **无** | 0 |
| `sandbox-exec` 封掉钥匙串 + SecurityAgent 的 mach lookup | **照样有**（securityd 仍然把 SecurityAgent 拉起来） | 0 |

两条结论：**沙箱 HOME 不是解药**（弹窗照旧，还挂死——正是 `platform.ts:149-153`
注释里记的「HOME 非真实家目录时 Edge headless 稳定以 2 退出」）；**sandbox-exec
也拦不住**。唯一稳定的抓手是**那对 mock-keychain 旗标**。

## 这层垫片做什么、不做什么

**做**：把跑批里的**每一次**浏览器启动都包上 mock-keychain 旗标，并让「智能体找浏览器」
这一步优先撞到垫片（而不是 `/Applications/…` 里的裸二进制）。

**不做**（红线）：
1. **不改工具面用的浏览器**。`platform.browser()` 的候选顺序是 edge → chrome →
   chromium；垫片**照抄这个顺序**解析出同一个二进制，工具面拿到的还是它。
   换了浏览器 = 换像素基线 = 污染读数。
2. **不改被测行为**。智能体照样手搓浏览器、照样绕过工具面——判据
   `no_tool_face_bypass` 照样命中。垫片只掐掉「摸用户钥匙串」这个副作用。
3. **不碰用户钥匙串**。不改 ACL、不删项、不 `security list-keychains`。
   旗标是 Chrome 自己的「用假钥匙串」开关，与用户数据无关。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

#: 与 `usine/packages/core/src/platform.ts` 的 `HEADLESS_FLAGS` 逐字一致。
#: 那里写明「两者都不影响光栅化，像素基线不受牵动」——所以加旗标不污染读数。
MOCK_KEYCHAIN_FLAGS: tuple[str, ...] = ("--use-mock-keychain", "--password-store=basic")

#: `platform.BROWSERS` 的候选顺序（edge 在 chrome 前，**顺序即优先级**）。
#: 只抄「macOS 上真实存在得起来」的那几条；裸名候选交给 PATH 解析。
_ABSOLUTE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ("edge", "~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("chrome", "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("chrome", "/usr/bin/google-chrome"),
    ("chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
)

#: 裸名候选（`platform.BROWSERS` 里的 `which()` 那一档）。解析时要**跳过垫片目录**，
#: 否则垫片会把自己解析出来。
_BARE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("edge", "microsoft-edge"),
    ("edge", "msedge"),
    ("chrome", "google-chrome"),
    ("chrome", "google-chrome-stable"),
    ("chrome", "chrome"),
    ("chromium", "chromium"),
    ("chromium", "chromium-browser"),
)

#: 垫片在 PATH 上提供的命令名 → 它们各自该指向哪个真实浏览器（按名字优先）。
#: 名字对不上真实浏览器时（`google-chrome` 找 Chrome），给该名字的**同族**浏览器；
#: 一个都没有才回落到平台解析出来的那个。
_SHIM_NAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("google-chrome", ("chrome", "chromium", "edge")),
    ("google-chrome-stable", ("chrome", "chromium", "edge")),
    ("chrome", ("chrome", "chromium", "edge")),
    ("chromium", ("chromium", "chrome", "edge")),
    ("chromium-browser", ("chromium", "chrome", "edge")),
    ("msedge", ("edge", "chrome", "chromium")),
    ("microsoft-edge", ("edge", "chrome", "chromium")),
)

#: 垫片的「通用名」：给 `$CHROME_BIN` 用。手册说 `$CHROME_BIN` 可显式覆盖浏览器
#: 解析——所以它必须指向**工具面本来就会用的那个**浏览器，否则等于替工具面换了浏览器。
CANONICAL_NAME = "chromium-safe"


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p)))


def _which(cmd: str, *, skip_dirs: set[str] | None = None) -> Path | None:
    """`shutil.which` 的最小实现，但能跳过指定目录（垫片目录自己）。"""
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        if not d:
            continue
        if skip_dirs and os.path.realpath(d) in skip_dirs:
            continue
        cand = Path(d) / cmd
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    return None


def resolve_platform_browser(*, skip_dirs: set[str] | None = None) -> tuple[str, Path] | None:
    """照抄 `platform.BROWSERS` 的顺序解析出**工具面会用的那个**浏览器。

    顺序即优先级（edge 在 chrome 前）——垫片必须解析出同一个二进制，
    否则等于在测量中途换了工具面的浏览器，像素基线就废了。
    """
    for name, cand in _ABSOLUTE_CANDIDATES:
        p = _expand(cand)
        if p.is_file() and os.access(p, os.X_OK):
            return name, p
    for name, cand in _BARE_CANDIDATES:
        found = _which(cand, skip_dirs=skip_dirs)
        if found is not None:
            return name, found
    return None


def _find_family(preferred: tuple[str, ...], platform: tuple[str, Path]) -> Path:
    """按名字族找真实浏览器；找不到就用平台解析出来的那个。"""
    by_name: dict[str, Path] = {platform[0]: platform[1]}
    for name, cand in _ABSOLUTE_CANDIDATES:
        p = _expand(cand)
        if p.is_file() and os.access(p, os.X_OK):
            by_name.setdefault(name, p)
    for want in preferred:
        if want in by_name:
            return by_name[want]
    return platform[1]


class BrowserShim:
    """跑批专用的浏览器垫片（临时目录，进程结束即销毁）。"""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="usine-browser-shim-"))
        self._names: dict[str, Path] = {}
        self.platform_browser: tuple[str, Path] | None = None
        self._build()

    # ── 构造 ────────────────────────────────────────────────────────────────
    def _write(self, name: str, target: Path) -> None:
        path = self.dir / name
        path.write_text(
            "#!/bin/sh\n"
            "# 跑批垫片：headless 渲染不碰用户钥匙串（mock keychain）。\n"
            "# 目标二进制与工具面 platform.browserPath() 解析出的是同一个。\n"
            f'exec "{target}" {" ".join(MOCK_KEYCHAIN_FLAGS)} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
        self._names[name] = target

    def _build(self) -> None:
        skip = {os.path.realpath(self.dir)}
        plat = resolve_platform_browser(skip_dirs=skip)
        if plat is None:
            # 没有浏览器就老实说没有：垫片不造「假装有浏览器」的东西。
            return
        self.platform_browser = plat
        self._write(CANONICAL_NAME, plat[1])
        for name, preferred in _SHIM_NAMES:
            self._write(name, _find_family(preferred, plat))

    # ── 消费 ────────────────────────────────────────────────────────────────
    def env_patch(self) -> dict[str, str]:
        """给 dsh 子进程的环境补丁（空字典 = 没有浏览器，不装任何东西）。"""
        if self.platform_browser is None:
            return {}
        out = {
            # 手册写明「`$CHROME_BIN` 可显式覆盖」浏览器解析——手册是**被测对象**，
            # 所以这个钩子必须真的可用。指向垫片 = 同一个二进制 + mock 旗标。
            #
            # **不设 FEUILLE_BROWSER**：它会盖掉 `platform.browser()` 的全部候选，
            # 于是 `publish/src/base.ts:126` 的 `platform.browser(only='chrome')`
            # （发布器只认 Chrome）会被拐到 Edge —— 那就是替工具面换了浏览器。
            # PATH 影子也不怕抢：`platform.BROWSERS` 里绝对路径候选排在裸名候选
            # **前面**，本机 Edge 的绝对路径存在 ⇒ 工具面拿到的还是 Edge。
            "CHROME_BIN": str(self.dir / CANONICAL_NAME),
        }
        return out

    def path_prefix(self) -> str:
        return str(self.dir)

    def manifest(self) -> dict[str, object]:
        """落盘用的证据（不含任何凭据）。"""
        return {
            "shim_dir": str(self.dir),
            "platform_browser": (
                {"name": self.platform_browser[0], "path": str(self.platform_browser[1])}
                if self.platform_browser
                else None
            ),
            "flags": list(MOCK_KEYCHAIN_FLAGS),
            "names": {n: str(t) for n, t in sorted(self._names.items())},
            "env": self.env_patch(),
        }

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def selfcheck(shim: BrowserShim, *, timeout: int = 60) -> dict[str, object]:
    """机检：垫片启动一次 headless 浏览器，**不拉起 SecurityAgent**（= 不弹窗）。

    这是「弹窗真的没了」的**可机检事实**，不是散文：SecurityAgent 是 macOS
    钥匙串弹窗的宿主进程，它出现 = 弹窗出现。

    2026-10-20 实测对照：同一条命令，裸二进制 + 全新 profile → SecurityAgent 出现；
    垫片（mock 旗标）→ 不出现、退出码 0、DOM 正常。
    """
    if shim.platform_browser is None:
        return {"ok": False, "reason": "no-browser"}
    tmp = Path(tempfile.mkdtemp(prefix="usine-shim-check-"))
    page = tmp / "p.html"
    page.write_text("<html><body><h1>ok</h1></body></html>", encoding="utf-8")
    profile = tmp / "profile"
    out = tmp / "dom.html"
    argv = [
        str(shim.dir / CANONICAL_NAME),
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=4000",
        "--dump-dom",
        page.as_uri(),
    ]
    pop = False
    proc = subprocess.Popen(  # noqa: S603
        argv, stdout=open(out, "wb"), stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(timeout):
            if proc.poll() is not None:
                break
            if _security_agent_running():
                pop = True
                break
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "ok": (not pop) and proc.returncode == 0,
        "security_agent": pop,
        "exit_code": proc.returncode,
    }


def _security_agent_running() -> bool:
    """macOS 钥匙串弹窗的宿主进程还在不在。"""
    try:
        out = subprocess.run(  # noqa: S603
            ["pgrep", "-x", "SecurityAgent"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.stdout.strip())


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    s = BrowserShim()
    try:
        print(json.dumps({"manifest": s.manifest(), "selfcheck": selfcheck(s)}, ensure_ascii=False, indent=2))
    finally:
        s.close()
