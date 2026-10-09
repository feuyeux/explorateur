# -*- coding: utf-8 -*-
"""ledger.py — 产物缓存账本（build/manifest.json）：谁新鲜、谁过期了、为什么

root 参数化：feuille 是库，账本跟着**内容项目**走（`root/build/manifest.json`）。
产物线注册制：`register_line(kind, modules, data)` 由使用方声明每条产物线的输入。
工具链解析走 `feuille.platform`——写死路径在别的机器上读不到 → resolver 返回
null → 全部产物永久判过期、每次全量重做，且**没有任何东西报错**（真实事故）。

**它解决什么**：render 曾每次全渲，因为没有任何东西能回答「这批产物还是不是
当前代码/数据渲出来的」。有了账本：`report()` 立刻回答哪些产物过期、因为什么
（不用渲）；渲染可以跳过指纹未变的单元；改完代码知道该只重做哪几条线。

**保守优先：宁可多渲，不可漏渲**。零像素漂移是硬判据：
- 指纹只由「确实可能影响该产物」的模块 + 数据 + 工具链构成，粒度是**文件级**——
  模块互相 import 极深，细粒度指纹一旦算错，代价是静默跳过本该重渲的产物且
  无任何报错；粗粒度的代价只是多渲几秒。
- 指纹算不出来的输入（读不到的文件、未知工具链）→ 直接判过期，绝不假设没影响；
- 产物文件本身不存在 → 无论指纹是否匹配一律过期（只比输入哈希的账本会在这里骗人）。

**这不是缓存正确性的依据，只是省时间的依据**。真正判据是逐帧像素比对；
账本说 fresh 只意味着「没理由重渲」，不意味着「画面对」。

三条守门规则（内嵌在实现里）：
1. 账本**不把自己算进指纹**——否则调试账本本身 = 全部产物作废。改 `_digest` /
   `fingerprint` 的算法必须升 `VERSION`（摘要里已含版本号，升版本即令旧指纹全部失效）。
2. 账本键必须能区分产物身份（`kind:unit`，如 `scene:colors/zh-CN`）——
   不带身份段的键在两条线同 unit 时互相覆盖。
3. `status_of` 对带 extra 的条目按**条目里记录的那份**复算（账本自描述）——
   调用方漏传会让条目永久判过期，症状只是「一直红」。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# 账本 schema 版本。**键的格式是 schema 的一部分**：v1 的键是 `scene:zh-CN`，
# 两门课同语种时互相覆盖；v2 起 `scene:<unit>` 由使用方保证唯一。版本不匹配 → 整本作废。
VERSION = 2

# 已注册的产物线：kind -> (feuille 包内模块文件名, 数据路径模式)。
# modules：**文件级**，粒度理由见模块头。data：相对内容项目 root；
#   以 "@" 开头 = glob 模式（如 "@languages/*/manifest.json" 整目录逐文件入指纹——
#   不用索引文件，索引本身会成为第二个事实源）。
_LINES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

_PACKAGE_DIR = Path(__file__).resolve().parent


def register_line(kind: str, modules: Sequence[str], data: Sequence[str]) -> None:
    """声明一条产物线的输入。重复注册同一 kind = 覆盖（测试与重配置用）。"""
    _LINES[kind] = (tuple(modules), tuple(data))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def toolchain() -> dict:
    """工具链指纹：Python / Pillow / 浏览器（哪种 + size+mtime）/ ffmpeg。

    浏览器带**名字**（edge / chrome / chromium / custom）：都属 Chromium，但字形
    栅格化与默认字体回退链并不完全相同，只记版本号不记「是哪一种」，
    等于把「换了浏览器」藏进指纹里。读不到 = None = 保守判过期（理由见模块头）。

    ffmpeg 参与指纹（它是合成器，影响成片）；magick 不参与——它只做验证侧的
    裁切拼图，不生成受指纹保护的产物，入桶只会让指纹无谓失效。
    """
    from . import platform as pt
    try:
        import PIL
        pillow = PIL.__version__
    except Exception:                                       # noqa: BLE001
        pillow = None
    b = pt.browser()
    if b:
        try:
            st = Path(b[1]).stat()
            browser_id = f"{b[0]}:{st.st_size}-{int(st.st_mtime)}"
        except OSError:
            browser_id = None
    else:
        browser_id = None
    return {
        "python": platform.python_version(),
        "pillow": pillow,
        "browser": browser_id,
        "ffmpeg": _run_first_line(["ffmpeg", "-version"]),
    }


def _run_first_line(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout.splitlines()[0].strip() if r.returncode == 0 else None
    except Exception:                                       # noqa: BLE001
        return None


def _digest(parts) -> str | None:
    """(标签, 路径) 列表 → 指纹。**任何一项读不到就返回 None（= 判过期）**。

    独立成函数是为了敏感性测试：真实源码/数据不能为了测试去改，
    而「改一个字节指纹会不会变」正是这个账本最需要被证明的事。
    """
    h = hashlib.sha256()
    h.update(f"v{VERSION}".encode())
    for label, path in parts:
        p = Path(path)
        if not p.is_file():
            return None
        h.update(f"|{label}:{_sha(p)}".encode())
    return h.hexdigest()[:16]


def input_parts(root: Path, kind: str) -> list[tuple[str, Path]] | None:
    """该产物线的全部输入（标签, 路径）。未注册的线返回 None（= 指纹算不出）。"""
    root = Path(root)
    if kind not in _LINES:
        return None
    modules, data = _LINES[kind]
    tc = toolchain()
    if tc["pillow"] is None:
        return None                       # Pillow 版本读不到 → 不敢假设没影响
    parts: list[tuple[str, Path]] = []
    parts += [(f"mod:{n}", _PACKAGE_DIR / n) for n in modules]
    for rel in data:
        if rel.startswith("@"):
            matches = sorted(root.glob(rel[1:])) if root.is_dir() else []
            if not matches:
                return None               # glob 一条都不中 → 不敢假设没影响
            parts += [(f"data:{m.relative_to(root).as_posix()}", m) for m in matches]
        else:
            parts.append((f"data:{rel}", root / rel))
    return parts


def fingerprint(root: Path, kind: str, unit: str, extra=()) -> str | None:
    """该单元产物的输入指纹。**任何一项读不到就返回 None = 判为过期**。"""
    root = Path(root)
    tc = toolchain()
    parts = input_parts(root, kind)
    if parts is None:
        return None
    base = _digest(parts)
    if base is None:
        return None
    h = hashlib.sha256(
        f"{base}|{kind}|{unit}|{tc['pillow']}|{tc['python']}"
        f"|{tc['ffmpeg']}|{tc['browser']}|{'|'.join(map(str, extra))}".encode())
    return h.hexdigest()[:16]


def ledger_path(root: Path) -> Path:
    return Path(root) / "build" / "manifest.json"


def load(root: Path) -> dict:
    if not ledger_path(root).exists():
        return {"version": VERSION, "updatedAt": None, "entries": {}}
    try:
        d = json.loads(ledger_path(root).read_text("utf-8"))
    except Exception:                                       # noqa: BLE001
        # 账本坏了就当没有：它是省时间的依据，不是正确性依据，不能因此拦住构建
        return {"version": VERSION, "updatedAt": None, "entries": {}}
    if d.get("version") != VERSION:
        return {"version": VERSION, "updatedAt": None, "entries": {}}
    d.setdefault("entries", {})
    return d


def save(root: Path, doc: dict) -> None:
    p = ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, p)                    # 原子换：中途断电不会留下半个账本


def status_of(root: Path, kind: str, unit: str, artifacts, extra=None) -> tuple[bool, str]:
    """(是否新鲜, 原因)。产物缺失一律判过期——只比输入哈希的账本会在这里骗人。

    `extra=None` = **用条目里记录的那份**（账本自描述）。这不是省事，是必需：
    调用方不可能记得住当初 record() 传过什么，漏传会让所有带 extra 的条目
    永久判过期——症状只是「status 一直红」，很容易被当成账本坏了。
    """
    root = Path(root)
    e = load(root)["entries"].get(f"{kind}:{unit}")
    fp = fingerprint(root, kind, unit,
                     (e.get("extra") or ()) if (extra is None and e) else (extra or ()))
    if fp is None:
        return False, "指纹算不出（模块/数据/工具链读不到），保守判过期"
    if e is None:
        return False, "账本里没有这条（首次构建或账本被清）"
    if e.get("fingerprint") != fp:
        return False, "输入指纹变了（源码/数据/工具链有改动）"
    missing = [a for a in artifacts if not (Path(root) / a).exists()]
    if missing:
        return False, f"产物缺失：{missing[:3]}"
    return True, "指纹一致且产物齐全"


def record(root: Path, kind: str, unit: str, artifacts, extra=()) -> None:
    root = Path(root)
    doc = load(root)
    doc["entries"][f"{kind}:{unit}"] = {
        "kind": kind, "unit": unit,
        "fingerprint": fingerprint(root, kind, unit, extra),
        "extra": [str(x) for x in extra],       # 随条目存下，status_of 照单复算
        "artifacts": [str(a) for a in artifacts],
        "toolchain": toolchain(),
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save(root, doc)


def report(root: Path, kinds=None) -> tuple[int, int]:
    """列出全部已登记单元的新鲜度。返回 (新鲜, 过期)。"""
    root = Path(root)
    doc = load(root)
    stale, fresh = [], []
    for key, e in sorted(doc["entries"].items()):
        if kinds and e.get("kind") not in kinds:
            continue
        ok, why = status_of(root, e["kind"], e["unit"], e.get("artifacts") or [])
        (fresh if ok else stale).append((key, why))
    print("=" * 68)
    print(f"缓存账本：{len(fresh)} 新鲜 / {len(stale)} 过期"
          f"（{ledger_path(root)}）")
    print("=" * 68)
    for k, why in stale:
        print(f"  [STALE] {k:<28} {why}")
    for k, _ in fresh:
        print(f"  [OK]    {k}")
    if not doc["entries"]:
        print("  （空：先跑一次 render 才会登记）")
    return len(fresh), len(stale)


def main_status(argv=None) -> int:
    """cli.py 路由入口：`feuille ledger status [--root DIR] [--kind KIND]`。

    回答「谁过期了、因为什么」。有过期 → 退出码 1：账本说过期就是
    「有活要干」的信号，失败判定一律看退出码（AGENTS.md 工程约定）；
    空账本不算失败（还没登记过任何产物，如实报空）。
    """
    import argparse
    ap = argparse.ArgumentParser(prog="feuille ledger status")
    ap.add_argument("--root", default=".", help="项目根（build/manifest.json 所在层）")
    ap.add_argument("--kind", action="append", default=None,
                    help="只看某产物线（可多次给，如 --kind scene）")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if not load(root)["entries"]:
        print(f"账本是空的（{ledger_path(root)}）——还没有登记过任何产物")
        return 0
    fresh, stale = report(root, a.kind)
    return 1 if stale else 0
