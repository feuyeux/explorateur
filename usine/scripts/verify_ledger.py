#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ledger.py — 缓存账本的反向验证（注册制 + root 参数化）

**第 0 条纪律是好数据放行**：登记 → status 必须报 fresh；这条不过，后面的
「能抓坏」全部没有意义。

其余各条各防一种真实退化：
- 改一个字节 → 指纹必变（模块与数据各验一次）
- 读不到的输入 → 指纹 None（保守判过期，绝不假设没影响）
- 产物被删 / 账本没这条 / 指纹不符 → 判过期
- 账本损坏 → 降级为空账本而不是抛异常
- 版本升级 → 整本作废
- 未注册的线 → 指纹算不出
- 不同 unit 键不碰撞；extra 账本自描述复算

全部断言自带夹具（临时 root / 临时数据文件），不碰真实源码与真实产物——
门禁必须能在任何没渲过东西的机器上跑（纪律 12：没验不许长得像验过了）。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feuille import ledger                      # noqa: E402


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []
    tmp = tempfile.TemporaryDirectory(prefix="feuille-ledger-")
    root = pathlib.Path(tmp.name)
    data_file = root / "data.json"
    data_file.write_text('{"a": 1}', "utf-8")

    ledger.register_line("testline", modules=["__init__.py"], data=["data.json"])
    ledger.register_line("testglobe", modules=["__init__.py"], data=["@langs/*/manifest.json"])
    (root / "langs" / "zh-CN").mkdir(parents=True)
    (root / "langs" / "zh-CN" / "manifest.json").write_text("{}", "utf-8")

    # ---- 0. 好数据放行 ----
    art = pathlib.Path("build/out.bin")
    (root / art).parent.mkdir(parents=True)
    (root / art).write_text("x", "utf-8")
    ledger.record(root, "testline", "unit-a", [str(art)])
    ok, why = ledger.status_of(root, "testline", "unit-a", [str(art)])
    rows.append((ok, f"好数据放行：登记后 status=fresh（{why}）"))

    # ---- 1. 敏感性：改一个字节的**数据** → 指纹必变 → 判过期 ----
    data_file.write_text('{"a": 2}', "utf-8")
    ok, why = ledger.status_of(root, "testline", "unit-a", [str(art)])
    rows.append((not ok and "指纹" in why,
                 f"数据文件改一个字节 → 判过期（{why}）"))
    data_file.write_text('{"a": 1}', "utf-8")

    # ---- 2. 敏感性：_digest 对任意输入的字节级变化（不碰真实源码）----
    a = root / "mod_a.py"; a.write_text("x = 1\n", "utf-8")
    b = root / "data_b.json"; b.write_text("{}", "utf-8")
    base = ledger._digest([("mod:a", a), ("data:b", b)])
    a.write_text("x = 2\n", "utf-8")
    rows.append((base != ledger._digest([("mod:a", a), ("data:b", b)]),
                 "改一个模块的字节 → 指纹必变"))
    rows.append((ledger._digest([("mod:a", a), ("data:b", root / "nope")]) is None,
                 "任何一项读不到 → _digest 返回 None（保守，不编指纹）"))

    # ---- 3. 产物被删 → 判过期 ----
    ok, why = ledger.status_of(root, "testline", "unit-a", [str(art) + ".gone"])
    rows.append((not ok and "产物缺失" in why, f"产物文件不存在 → 判过期（{why}）"))

    # ---- 4. 账本里没有这条 → 判过期 ----
    ok, why = ledger.status_of(root, "testline", "never-recorded", [str(art)])
    rows.append((not ok and "没有这条" in why, f"账本没这条 → 判过期（{why}）"))

    # ---- 5. 账本损坏 → 降级为空账本，不抛异常 ----
    ledger.ledger_path(root).write_text("{oops", "utf-8")
    ok, why = ledger.status_of(root, "testline", "unit-a", [str(art)])
    rows.append((not ok and "没有这条" in why,
                 f"账本文件损坏 → 降级为空账本而不是抛异常（{why}）"))
    ledger.record(root, "testline", "unit-a", [str(art)])     # 重建

    # ---- 6. 版本升级 → 整本作废 ----
    doc = ledger.load(root)
    doc["version"] = ledger.VERSION - 1
    doc["entries"]["testline:unit-a"] = {"fingerprint": "x", "artifacts": []}
    ledger.save(root, doc)
    ok, why = ledger.status_of(root, "testline", "unit-a", [str(art)])
    rows.append((not ok and "没有这条" in why,
                 f"账本版本不匹配 → 整本作废（{why}），旧结构条目不会被误读"))

    # ---- 7. 未注册的线 → 指纹算不出 ----
    ledger.record(root, "testline", "unit-a", [str(art)])
    rows.append((ledger.fingerprint(root, "never-registered", "u") is None,
                 "未注册的产物线 → 指纹算不出（None），不会拿别线的指纹凑数"))

    # ---- 8. 键不碰撞：不同 unit 互不覆盖 ----
    ledger.record(root, "testline", "unit-b", [str(art)])
    entries = ledger.load(root)["entries"]
    rows.append(("testline:unit-a" in entries and "testline:unit-b" in entries,
                 "不同 unit 键不碰撞（键不带身份段会互相覆盖）"))

    # ---- 9. extra 账本自描述 ----
    ledger.record(root, "testline", "unit-extra", [str(art)], extra=("16x9",))
    ok, why = ledger.status_of(root, "testline", "unit-extra", [str(art)])
    rows.append((ok, f"带 extra 的条目按记录复算 → fresh（{why}）"))
    ok, why = ledger.status_of(root, "testline", "unit-extra", [str(art)],
                               extra=("9x16",))
    rows.append((not ok, f"extra 换了值 → 指纹必变（{why}）"))

    # ---- 10. glob 数据线：目录内容变 → 判过期 ----
    ok, why = ledger.status_of(root, "testglobe", "g1", [str(art)])
    ok2 = ledger.fingerprint(root, "testglobe", "g1") is not None
    rows.append((ok2, f"@glob 数据线解析到目录内文件（{why}）"))
    (root / "langs" / "ja-JP").mkdir()
    (root / "langs" / "ja-JP" / "manifest.json").write_text("{}", "utf-8")
    fp1 = ledger.fingerprint(root, "testglobe", "g1")
    (root / "langs" / "ja-JP" / "manifest.json").write_text('{"x":1}', "utf-8")
    rows.append((fp1 != ledger.fingerprint(root, "testglobe", "g1"),
                 "glob 目录内文件字节变 → 指纹必变"))

    # ---- 11. 工具链不可读 = None（用 monkeypatch 模拟浏览器读不到）----
    old = ledger.toolchain
    ledger.toolchain = lambda: {"python": None, "pillow": None, "browser": None, "ffmpeg": None}
    try:
        rows.append((ledger.fingerprint(root, "testline", "unit-a") is None,
                     "Pillow 版本读不到 → 指纹 None（保守判过期，绝不假设没影响）"))
    finally:
        ledger.toolchain = old

    # ---- 12. report() 不炸、条目可读 ----
    fresh, stale = ledger.report(root)
    rows.append((fresh + stale > 0, f"report() 可跑（{fresh} 新鲜 / {stale} 过期）"))

    # ---- 13. CLI 叶子（feuille ledger status）的退出码口径 ----
    leaf_root = root / "leaf"
    rows.append((ledger.main_status(["--root", str(leaf_root)]) == 0,
                 "status 叶子：空账本 → 退出码 0（还没登记 ≠ 失败）"))
    leaf_root.mkdir(parents=True, exist_ok=True)
    leaf_data = leaf_root / "leaf.json"
    leaf_data.write_text("{}", "utf-8")
    leaf_art = leaf_root / "build" / "out.bin"
    leaf_art.parent.mkdir(parents=True, exist_ok=True)
    leaf_art.write_text("x", "utf-8")
    ledger.register_line("leafline", modules=["__init__.py"], data=["leaf.json"])
    ledger.record(leaf_root, "leafline", "u1", [str(leaf_art)])
    rows.append((ledger.main_status(["--root", str(leaf_root)]) == 0,
                 "status 叶子：全新鲜 → 退出码 0"))
    leaf_data.write_text('{"k": 1}', "utf-8")      # 输入指纹变了
    rows.append((ledger.main_status(["--root", str(leaf_root)]) == 1,
                 "status 叶子：有过期 → 退出码 1（「有活要干」的信号）"))
    return rows


def main() -> int:
    print("=" * 72)
    print("缓存账本（注册制 + root 参数化）")
    print("=" * 72)
    rows = check()
    fails = 0
    for ok, msg in rows:
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok
    print("=" * 72)
    print(f"{'OK' if not fails else 'FAIL'}：缓存账本 {len(rows) - fails}/{len(rows)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
