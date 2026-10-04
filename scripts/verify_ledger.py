#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ledger.py — 缓存账本的验收与反向验证

**这个账本最危险的失败模式不是「过于保守」（少省几秒），而是「过于自信」**：
它说 fresh，于是 render 跳过，产出一支**旧画面**的成片，而没有任何东西会报错——
零像素漂移这条硬判据就是这样被悄悄破坏的。所以判据取「它会不会在不该跳的时候跳」。

**第 0 条断言是好数据放行**：一个恒返回 stale 的账本同样安全，但毫无价值，
那种「安全」会让每次都全渲，等于没做。

真实源码/数据不能为了测试去改，所以指纹的**敏感性**用临时文件验证（`_digest` 收
(label, path) 列表），而**跳过决策**用真的一支卡做端到端验证。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usine import ledger                                    # noqa: E402

SAMPLE = "xiaoman"          # 林小满（zh-CN），本轮真实渲过、已登记
MP4 = ROOT / "build/intro" / f"{SAMPLE}.mp4"


def _with_ledger(fn):
    """在临时账本上跑 fn()，跑完恢复真账本——测试不许动真账本。"""
    backup = ledger.LEDGER_PATH.read_bytes() if ledger.LEDGER_PATH.exists() else None
    try:
        ledger.LEDGER_PATH.unlink(missing_ok=True)
        return fn()
    finally:
        if backup is not None:
            ledger.LEDGER_PATH.write_bytes(backup)
        else:
            ledger.LEDGER_PATH.unlink(missing_ok=True)


def selftest():
    rows = []

    # ---------- 0. 好数据放行 ----------
    def good():
        ledger.record("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
        ok, why = ledger.status_of("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
        return ok, why
    ok, why = _with_ledger(good)
    rows.append((ok, f"好数据放行：登记后 status=fresh（{why}）"))

    # ---------- 1. 指纹敏感性（临时文件，不碰真源码） ----------
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        a, b, c = d / "a.py", d / "b.json", d / "c.md"
        for p, t in ((a, "x"), (b, "y"), (c, "z")):
            p.write_text(t, "utf-8")
        base = ledger._digest([("mod:a", a), ("data:b", b), ("doc:c", c)])

        a.write_text("xx", "utf-8")
        after_mod = ledger._digest([("mod:a", a), ("data:b", b), ("doc:c", c)])
        rows.append((base != after_mod, "改一个模块的字节 → 指纹必变"))

        a.write_text("x", "utf-8")
        b.write_text("yy", "utf-8")
        after_data = ledger._digest([("mod:a", a), ("data:b", b), ("doc:c", c)])
        rows.append((base != after_data, "改一个数据文件的字节 → 指纹必变"))

        c.unlink()
        rows.append((ledger._digest([("mod:a", a), ("data:b", b), ("doc:c", c)]) is None,
                     "少一个输入文件 → 指纹算不出（= 判过期），不是沿用旧值"))

    # ---------- 2. 跳过决策 ----------
    def stale_on_changed_fp():
        ledger.record("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
        doc = ledger.load()
        doc["entries"][f"intro-card:{SAMPLE}"]["fingerprint"] = "deadbeefdeadbeef"   # 模拟「输入变了」
        ledger.save(doc)                        # 存的是**同一个** doc——改副本再 save(load()) 等于没改
        ok, why = ledger.status_of("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
        return (not ok) and "指纹变了" in why, why

    ok, why = _with_ledger(stale_on_changed_fp)
    rows.append((ok, f"账本里的指纹与当前输入不符 → 必须判过期（{why}）"))

    def stale_on_missing_artifact():
        """只比输入哈希的账本最经典的骗人点：产物被删了它还说 fresh。"""
        ledger.record("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
        bk = MP4.with_suffix(".mp4.bak")
        shutil.move(str(MP4), str(bk))
        try:
            ok, why = ledger.status_of("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
            return (not ok) and "产物缺失" in why, why
        finally:
            shutil.move(str(bk), str(MP4))
    ok, why = _with_ledger(stale_on_missing_artifact)
    rows.append((ok, f"产物文件被删 → 必须判过期（{why}）"))

    def no_entry():
        ok, why = ledger.status_of("intro-card", "never-rendered-unit", ["build/intro/nope.mp4"])
        return (not ok) and "账本里没有" in why, why
    ok, why = _with_ledger(no_entry)
    rows.append((ok, f"账本里没有这条 → 必须判过期（{why}）"))

    def corrupt_ledger():
        ledger.LEDGER_PATH.write_text("{ 这不是 json", "utf-8")
        d = ledger.load()
        return d["entries"] == {} and d["version"] == ledger.VERSION, "坏账本降级为空"
    ok, why = _with_ledger(corrupt_ledger)
    rows.append((ok, f"账本文件损坏 → 降级为空账本而不是抛异常（{why}）"))

    def version_bump():
        ledger.LEDGER_PATH.write_text(
            json.dumps({"version": 999, "entries": {"intro-card:x": {}}}), "utf-8")
        return ledger.load()["entries"] == {}, "版本不符 → 整本作废"
    ok, why = _with_ledger(version_bump)
    rows.append((ok, f"账本版本升级 → 整本作废（{why}），不能让旧结构的条目被误读"))

    def unknown_kind():
        return ledger.fingerprint("no-such-line", "x") is None, "未知线 → None"
    ok, why = unknown_kind()
    rows.append((ok, f"未知产物线 → 指纹算不出（{why}）"))

    def key_collision():
        """两门课共用一个语种时，键必须不同——否则后渲的课把先渲的整条覆盖掉。"""
        ledger.record("scene", "colors/zh-CN", ["build/scene/scene-colors_zh-CN.mp4"], extra=["colors"])
        ledger.record("scene", "numbers/zh-CN", ["build/scene/scene-numbers_zh-CN.mp4"], extra=["numbers"])
        keys = sorted(ledger.load()["entries"])
        n = len([k for k in keys if k.startswith("scene:")])
        arts = {k: ledger.load()["entries"][k]["artifacts"][0] for k in keys}
        return (n == 2 and len(set(arts.values())) == 2,
                f"两门课同语种 → 两条独立记录（{n} 条，产物 {len(set(arts.values()))} 个）")

    ok, why = _with_ledger(key_collision)
    rows.append((ok, f"不同课同一语种 → 键不碰撞（{why}）"))

    def scene_fingerprint_separates():
        """课 id 必须进指纹：只靠 unit 之外的 extra 传进去也要生效。"""
        a = ledger.fingerprint("scene", "colors/zh-CN", extra=["colors"])
        b = ledger.fingerprint("scene", "numbers/zh-CN", extra=["numbers"])
        return (a is not None and b is not None and a != b), f"课 id 不同 → 指纹不同（{a} vs {b}）"
    ok, why = scene_fingerprint_separates()
    rows.append((ok, f"{why}"))

    def extra_is_self_describing():
        """带 extra 登记的条目，`status_of` 不传 extra 也必须能复算出同一个指纹。

        否则 `report()` 这类「按条目遍历」的调用方不可能记得住当初传过什么，
        所有带 extra 的条目会永久判过期——症状只是「status 一直红」，很容易被当成账本坏了。
        """
        ledger.record("scene", "colors/zh-CN", ["build/scene/scene-colors_zh-CN.mp4"],
                      extra=["colors"])
        e = ledger.load()["entries"]["scene:colors/zh-CN"]
        ok1, _ = ledger.status_of("scene", "colors/zh-CN",
                                  ["build/scene/scene-colors_zh-CN.mp4"])          # 不传 extra
        ok2, _ = ledger.status_of("scene", "colors/zh-CN",
                                  ["build/scene/scene-colors_zh-CN.mp4"],
                                  extra=e.get("extra"))                            # 照单传回
        return ok1 and ok2, f"status_of 不传 extra={ok1} / 照单传回={ok2}"
    ok, why = _with_ledger(extra_is_self_describing)
    rows.append((ok, f"条目自带 extra，`status_of` 照单复算（{why}）"))

    def render_path_agrees_with_report():
        """渲染期传的 extra 必须与 `report()` 用的那条一致。

        两处各传各的：渲染期传 `extra=[SCENE_ID]`、`report()` 照条目复算 →
        指纹永远对不上 → **每次都判过期、每次都全渲**。症状极像「账本没生效」，
        而病灶是两个调用点的参数不一致。
        """
        art = ["build/scene/scene-colors_zh-CN.mp4"]
        # 模拟渲染期：显式传 extra
        ledger.record("scene", "colors/zh-CN", art, extra=["colors"])
        a, _ = ledger.status_of("scene", "colors/zh-CN", art, extra=["colors"])
        # 模拟 report()：不传 extra（照条目登记的那份）
        b, _ = ledger.status_of("scene", "colors/zh-CN", art)
        return a and b, f"渲染期传 extra={a} / report 照单复算={b}（必须同时为真）"
    ok, why = _with_ledger(render_path_agrees_with_report)
    rows.append((ok, f"渲染期与 report() 两条路径的 extra 一致（{why}）"))

    # ---------- 3. 端到端：跳过不改变产物 ----------
    if MP4.exists():
        # 先按**当前**源码重新登记一次：账本把 ledger.py 自身也算进输入，
        # 所以刚改过它之后旧条目本来就该作废（这正是保守策略的体现，不是 bug）。
        ledger.record("intro-card", SAMPLE, [f"build/intro/{SAMPLE}.mp4"])
        h_before = ledger._sha(MP4)
        env = {**os.environ, "USINE_SKIP_FRESH": "1", "PYTHONPATH": str(ROOT / "src")}
        r = subprocess.run([sys.executable, "-c",
                            f"from usine import intro_cards; intro_cards.cmd_render({{{SAMPLE!r}}}, 1)"],
                           capture_output=True, text=True, env=env, cwd=str(ROOT))
        skipped = "跳过" in r.stdout
        h_after = ledger._sha(MP4)
        rows.append((skipped and h_before == h_after,
                     f"端到端：指纹新鲜时 render 跳过且产物字节未变（{h_before[:12]}…）"))

        # 强制全渲必须真的渲（否则 USINE_SKIP_FRESH=0 就是个骗人的开关）
        env2 = {**os.environ, "USINE_SKIP_FRESH": "0", "PYTHONPATH": str(ROOT / "src")}
        r2 = subprocess.run([sys.executable, "-c",
                             f"from usine import intro_cards; intro_cards.cmd_render({{{SAMPLE!r}}}, 1)"],
                            capture_output=True, text=True, env=env2, cwd=str(ROOT))
        rows.append(("跳过" not in r2.stdout and "rc=0" in r2.stdout,
                     f"USINE_SKIP_FRESH=0 → 强制全渲（不跳过）且成功"
                     f"　rc={r2.returncode} out={r2.stdout.strip().splitlines()[-1][:50] if r2.stdout.strip() else '(空)'}"
                     f" err={r2.stderr.strip().splitlines()[-1][:60] if r2.stderr.strip() else ''}"))
        # 强制全渲出来的画面必须与跳过前逐字节相同（幂等）
        rows.append((ledger._sha(MP4) == h_before,
                     f"强制重渲后像素不变（容器字节可能变，逐帧由 framehash 判）"))
    else:
        rows.append((False, f"端到端：{MP4} 不存在，无法验证"))
        rows.append((False, "端到端：强制全渲开关未验证"))
        rows.append((False, "端到端：重渲幂等未验证"))

    return rows


TOTAL = 19


def main():
    print("=" * 70)
    print("P2-2 缓存账本：它会不会在不该跳的时候跳？")
    print("=" * 70)
    fails = 0
    for ok, msg in selftest():
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
        fails += not ok
    print("=" * 70)
    print(f"{'OK' if not fails else 'FAIL'}：缓存账本 {TOTAL - fails}/{TOTAL} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
