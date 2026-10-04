#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger.py — 产物缓存账本 `build/manifest.json`（P2-2）

**它解决什么**：`render` 此前**每次全渲**（32 张卡 ≈ 3 分钟，14 支场景成片更久），
因为没有任何东西能回答「这批产物还是不是当前代码/数据渲出来的」。于是每次改一行
探针代码，都得重渲全部才能确认自己没改坏画面——而重渲完只能靠 framehash 反查。

有了账本：
- `usine-ledger status` 立刻回答「哪些产物过期了、因为什么」——**不用渲**；
- `render` 可以跳过指纹未变的单元；
- 改完代码后知道该**只重渲哪几条线**，而不是全部。

**保守优先：宁可多渲，不可漏渲。** 零像素漂移是硬判据，所以：
- 指纹只由「**确实可能影响该产物**」的模块 + 数据文件 + 工具链版本构成，
  但模块的粒度是**文件级**——只要某个渲染模块被碰过，该线的全部产物一律作废；
- 指纹算不出来的输入（读不到的文件、未知工具链）→ 直接判为**过期**，绝不假设它没影响；
- 产物文件本身不存在 → 无论指纹是否匹配，一律过期（只比输入哈希的账本会在这里骗人）。

**这不是缓存的正确性依据，只是省时间的依据。** 真正的判据仍是 framehash：
账本说「fresh」只意味着「没理由重渲」，不意味着「画面是对的」。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from usine import ROOT

LEDGER_PATH = ROOT / "build" / "manifest.json"
# 账本 schema 版本。**键的格式是 schema 的一部分**：2026-10-04 v1 的键是 `scene:zh-CN`，
# 两门课同语种时互相覆盖（坑㉣），v2 改成 `scene:<sceneId>/<locale>`。升版本让 v1 的
# 全部条目一次性作废——比在 `status` 里长期挂着 14 条永远 STALE 的僵尸记录干净。
# 版本不匹配 → 整本作废（`load`），下次 render 自然重建。
VERSION = 2

# 每条产物线**可能**受影响的源码模块。粒度是文件级：碰了就是整线作废。
# 为什么不做得更细（按函数/类）：模块之间互相 import 极深（scene_video 直接用
# intro_cards.draw_character），细粒度一旦算错，代价是「跳过了本该重渲的产物」——
# 那会静默产出一支旧画面，而且没有任何东西会报错。粗粒度的代价只是多渲几秒。
LINE_MODULES = {
    "intro-card": ["__init__.py", "data.py", "media.py", "intro_cards.py"],
    "intro-text": ["__init__.py", "data.py", "media.py", "intro_cards.py"],
    "scene": ["__init__.py", "data.py", "media.py", "parse_scene.py",
              "scene_schema.py", "intro_cards.py", "scene_video.py"],
}
# 各线的数据输入（相对仓库根）。缺文件 → 判过期（见 `fingerprint`）。
# 语种目录按**整目录**算一个指纹（排序后的逐文件 sha），而不是预先维护一份索引文件——
# 索引文件本身会成为第二个事实源，改了目录忘了改索引就会让指纹失真。
LINE_DATA = {
    "intro-card": ["personas/personas.json", "personas/intro-cards.json", "@languages"],
    "intro-text": ["personas/personas.json", "personas/intro-cards.json", "@languages"],
    "scene": ["personas/personas.json", "personas/intro-cards.json", "@languages"],
}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def toolchain() -> dict:
    """工具链指纹。Edge 版本取自可执行文件的 mtime+size——拿不到就写 null，
    读不进版本不代表它没变（保守方向：null 会被 `_edge` 判成不可信）。"""
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    try:
        import PIL
        pillow = PIL.__version__
    except Exception:                                       # noqa: BLE001
        pillow = None
    if edge.exists():
        st = edge.stat()
        edge_id = f"{st.st_size}-{int(st.st_mtime)}"
    else:
        edge_id = None
    return {
        "python": platform.python_version(),
        "pillow": pillow,
        "edge": edge_id,
        "ffmpeg": _ffmpeg_version(),
    }


def _ffmpeg_version() -> str | None:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=20)
        return r.stdout.splitlines()[0].strip() if r.returncode == 0 else None
    except Exception:                                       # noqa: BLE001
        return None


def _digest(parts) -> str | None:
    """(标签, 路径) 列表 → 指纹。**任何一项读不到就返回 None（= 判过期）**。

    抽成独立函数是为了能拿临时文件做敏感性测试：真实源码/数据不能为了测试去改，
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


def input_parts(kind: str) -> list[tuple[str, str]] | None:
    """该产物线的全部输入（标签, 绝对路径）。语种目录展开成逐个 manifest。

    **刻意不含 `ledger.py` 自己**：账本代码不参与渲染，把它算进输入只会造成
    「调试账本 → 48 支产物全部作废 → 必须重渲十几分钟」这种纯浪费（坑㉟）。
    指纹算法变了怎么办？升 `VERSION`——`_digest` 的摘要里已经含 `v{VERSION}`，
    升版本即令全部旧指纹失效。**改 `_digest` / `fingerprint` 的算法必须升 VERSION。**
    """
    if kind not in LINE_MODULES:
        return None
    parts: list[tuple[str, str]] = []
    tc = toolchain()
    if tc["pillow"] is None:
        return None                          # Pillow 版本读不到 → 不敢假设没影响
    parts += [(f"mod:{n}", Path(__file__).parent / n) for n in LINE_MODULES[kind]]
    for rel in LINE_DATA.get(kind, []):
        if rel == "@languages":
            d = ROOT / "languages"
            mans = sorted(d.glob("*/manifest.json")) if d.is_dir() else []
            if not mans:
                return None                  # 语种目录空了 → 不敢假设没影响
            parts += [(f"lang:{p.parent.name}", p) for p in mans]
        else:
            parts.append((f"data:{rel}", ROOT / rel))
    return parts


def fingerprint(kind: str, unit: str, extra=()) -> str | None:
    """该单元产物的输入指纹。**任何一项读不到就返回 None = 判为过期**。"""
    tc = toolchain()
    parts = input_parts(kind)
    if parts is None:
        return None
    base = _digest(parts)
    if base is None:
        return None
    h = hashlib.sha256(f"{base}|{kind}|{unit}|{tc['pillow']}|{tc['python']}|"
                       f"{tc['ffmpeg']}|{tc['edge']}|{'|'.join(map(str, extra))}".encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- 账本读写

def load() -> dict:
    if not LEDGER_PATH.exists():
        return {"version": VERSION, "updatedAt": None, "entries": {}}
    try:
        d = json.loads(LEDGER_PATH.read_text("utf-8"))
    except Exception:                                       # noqa: BLE001
        # 账本坏了就当没有：它是省时间的依据，不是正确性依据，不能因此拦住构建
        return {"version": VERSION, "updatedAt": None, "entries": {}}
    if d.get("version") != VERSION:
        return {"version": VERSION, "updatedAt": None, "entries": {}}
    d.setdefault("entries", {})
    return d


def save(doc: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, LEDGER_PATH)              # 原子换：中途断电不会留下半个账本


def status_of(kind: str, unit: str, artifacts, extra=None) -> tuple[bool, str]:
    """(是否新鲜, 原因)。产物缺失一律判过期——只比输入哈希的账本会在这里骗人。

    `extra=None` = **用条目里记录的那份**（账本自描述）。这不是省事，是必需：
    调用方（`report()` 之类）不可能记得住当初 `record()` 时传过什么，于是所有带 extra
    的条目会永久判过期——而症状只是「status 一直红」，很容易被当成账本坏了。
    """
    e = load()["entries"].get(f"{kind}:{unit}")
    fp = fingerprint(kind, unit, (e.get("extra") or ()) if (extra is None and e) else
                     (extra or ()))
    if fp is None:
        return False, "指纹算不出（模块/数据/工具链读不到），保守判过期"
    if e is None:
        return False, "账本里没有这条（首次构建或账本被清）"
    if e.get("fingerprint") != fp:
        return False, "输入指纹变了（源码/数据/工具链有改动）"
    missing = [a for a in artifacts if not (ROOT / a).exists()]
    if missing:
        return False, f"产物缺失：{missing[:3]}"
    return True, "指纹一致且产物齐全"


def record(kind: str, unit: str, artifacts, extra=()) -> None:
    doc = load()
    doc["entries"][f"{kind}:{unit}"] = {
        "kind": kind, "unit": unit,
        "fingerprint": fingerprint(kind, unit, extra),
        "extra": [str(x) for x in extra],       # 随条目存下，`status_of` 照单复算
        "artifacts": [str(a) for a in artifacts],
        "toolchain": toolchain(),
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save(doc)


def report(kinds=None) -> tuple[int, int]:
    """列出全部已登记单元的新鲜度。返回 (新鲜, 过期)。"""
    doc = load()
    stale, fresh = [], []
    for key, e in sorted(doc["entries"].items()):
        if kinds and e.get("kind") not in kinds:
            continue
        ok, why = status_of(e["kind"], e["unit"], e.get("artifacts") or [])
        (fresh if ok else stale).append((key, why))
    print("=" * 68)
    print(f"缓存账本：{len(fresh)} 新鲜 / {len(stale)} 过期（{LEDGER_PATH.relative_to(ROOT)}）")
    print("=" * 68)
    for k, why in stale:
        print(f"  [STALE] {k:<28} {why}")
    for k, _ in fresh:
        print(f"  [OK]    {k}")
    if not doc["entries"]:
        print("  （空：先跑一次 render 才会登记）")
    return len(fresh), len(stale)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="产物缓存账本 build/manifest.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="列出各产物的新鲜度")
    s.add_argument("--kind", action="append", default=None,
                   help=f"只看某条线（{'/'.join(LINE_MODULES)}）")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        _, stale = report(set(args.kind) if args.kind else None)
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
