#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_shape_fixes.py — 坑⑱ 几何修复的**反向验证**（回归测试）

为什么要有这个文件（照抄 render-handbook §4 对 verify_text_contract.py 的要求）：
「拿已知坏数据证明检查会 FAIL，再拿好数据证明放行」。只跑「修复后全绿」的测试等于没测——
探针完全可能因为取样窗取偏、阈值过松、图层顺序假设错误而**恒真**。

做法：把几何/颜色接缝猴补丁成**修复前的取值**，再跑同一套 qa_shape 探针，
要求对应探针必须 FAIL；不补丁时必须全 PASS。

  旧取值（2026-10-03 坑⑱ 之前）：
    sh_out   = torso_hw·0.62        ← 等价于「没有肩部体块」，肩楔失效
    hip_hw   = leg_cx + leg_w·0.62  ← 胯块只按腿外缘铺，躯干下缘与双腿之间是空的
    sleeve_color() → base           ← 袖子与衣同色，上臂读不出来

另外覆盖坑㉑（顶戴墨镜探针）：`glasses_frame` / `glasses_lens`。

用法：uv run python scripts/verify_shape_fixes.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from usine import char_sheet                                # noqa: E402
from usine import intro_cards as ic                          # noqa: E402
from usine import qa_char                                    # noqa: E402
from usine import qa_shape                                   # noqa: E402
from usine.intro_cards import load_data                      # noqa: E402

_G0 = ic.face_geo
_S0 = ic.sleeve_color
_D0 = ic.draw_character
_SH0 = dict(ic.SUNGLASS_HEAD)
_FP0 = ic.face_profile
_JP0 = ic.jaw_point
_HAIR_KEEP0 = ic.HAIR_CHEEK_KEEP


def legacy_geo(**over):
    """face_geo 变体：算出现值后按 over 覆盖（None = 回退到旧算法）。

    `sh_out="neck"` 是一个**语义开关**而不是数值，单独翻译成「肩部体块不外扩」。
    """
    def _g(face):
        g = dict(_G0(face))
        g.update({k: v for k, v in over.items() if v is not None})
        if "hip_hw" in over and over["hip_hw"] is None:
            g["hip_hw"] = g["leg_cx"] + g["leg_w"] * 0.62          # 旧值
        if over.get("sh_out") == "neck":
            g["sh_out"] = g["neck_hw"]                             # 旧失效模式
        return g
    return _g


def legacy_shoulder_draw():
    """只在**绘制期间**把 `face_geo` 换成旧的窄肩楔，探针仍用现行几何读判定窗。

    踩过的坑：直接在 `face_geo` 上把 `sh_out` 调小是不行的——探针的扫描窗
    ±1.15·sh_out 会跟着缩，旧缺陷的洞直接跑到窗外，探针变成恒真（0/28 命中）。
    绘制与判定必须用两套几何，这正是「渲染端几何」与「探针几何」要分开的原因。
    """
    d0 = ic.draw_character

    def _draw(img, drw, p, t, ctx):
        saved = ic.face_geo
        ic.face_geo = lambda f: {**saved(f), "sh_out": saved(f)["neck_hw"] + 0.004 * saved(f)["H"]}
        try:
            return d0(img, drw, p, t, ctx)
        finally:
            ic.face_geo = saved
    return _draw


def run(ids, tags, damage=None):
    personas, doc = load_data()
    cards = {c["id"]: c for c in doc["cards"]}
    acc = {}
    for pid in ids:
        res, _ = qa_shape.probe_persona(personas[pid], cards.get(pid), damage=(damage or {}).get(pid))
        for r in res:
            tag = r["probe"].split()[0]
            if tag in tags:
                acc.setdefault(tag, []).append(r["ok"])
    return acc


def damage_box(pid, tag):
    """按 face_geo 推出该探针判定窗正中的一块矩形（合成打洞用）。"""
    personas, doc = load_data()
    G = ic.face_geo(personas[pid]["movement"]["face"])
    cx, Hh = G["cx"], G["H"]
    sh_y = G["torso_top"] + G["sh_dy"]
    p = personas[pid]
    tunic = (p.get("outfit") or {}).get("kind") == "tunic"
    tb = G["torso_top"] + G["torso_h"] * (1.30 if tunic else 1.0)
    if tag == "A1":
        y0, y1 = int(G["chin"] - Hh * 0.02), int(sh_y - Hh * 0.02)
    else:
        y0, y1 = int(tb - Hh * 0.16), int(tb + Hh * 0.10)
    half = (G["sh_out"] if tag == "A1" else G["torso_hw"] * 0.72) * 0.55
    return (int(cx + G["neck_hw"] * 1.2), y0 + 2, int(cx + half), y1 - 2)


def check(label, ids, tag, expect_fail, damage=None):
    acc = run(ids, {tag}, damage=damage)
    vs = acc.get(tag, [])
    n_fail = sum(1 for v in vs if not v)
    ok = (n_fail > 0) if expect_fail else (n_fail == 0)
    tag_txt = f"{n_fail}/{len(vs)} 判 FAIL" if expect_fail else f"{len(vs) - n_fail}/{len(vs)} PASS"
    print(f"   {'OK  ' if ok else 'FAIL'} {label} —— {tag_txt}")
    return 0 if ok else 1


# ---------- 坑㉑：顶戴墨镜探针（glasses_frame 阶跃 / glasses_lens 点） ----------

def _render_sunglasses_persona(pid, personas, tmpdir):
    """把人物层压纸底存成 png 当作 qa_char 的输入（与成片同源，不另画一遍）。"""
    p = personas[pid]
    flat = char_sheet.flatten(char_sheet.figure(p, None, scale=1.0))
    path = Path(tmpdir) / f"_verify_{pid}.png"
    flat.save(path)
    return path


def _glasses_probe(pid, frame):
    """跑 qa_char 并只取墨镜那两条探针的 (ok) 结果。"""
    got = []
    qa_char.check(pid, str(frame), verbose=False, results_out=got)
    return {r[0]: r[1] for r in got if r[0].startswith("glasses_")}


def check_glasses(label, expect, got):
    """expect = {'glasses_frame': True, 'glasses_lens': True}（True = 应当 PASS）"""
    ok = True
    for name, want_ok in expect.items():
        g = got.get(name)
        mark = "OK  " if g is want_ok else "FAIL"
        print(f"   {mark} {label} · {name:15s} 期望 {'PASS' if want_ok else 'FAIL'}，实测 "
              f"{'PASS' if g else ('FAIL' if g is not None else '缺探针')}")
        ok = ok and g is want_ok
    return 0 if ok else 1


# ---------- 坑㉓：下颌轮廓（heart 针尖下巴 / square 脸被拉宽 / 发帘夹出尖楔） ----------

def legacy_heart_profile(face, v):
    """旧心形下颌的半宽系数：x(t)=1−1.2t+0.2t²、y(t)=0.42+1.26t−0.64t²（t 反解）。"""
    if face != "heart":
        return _FP0(face, v)
    if v <= 0.42:
        return 1.0
    if v >= 1.04:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(48):                      # y(t) 单调，二分反解 t
        t = (lo + hi) / 2
        if 0.42 + 1.26 * t - 0.64 * t * t < v:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2
    return 1 - 1.2 * t + 0.2 * t * t


def legacy_square_profile(face, v):
    """旧方颌 polygon 的半宽系数：v=0.55→0.60、0.80→**0.92**、0.985→0.80（比椭圆宽）。"""
    if face != "square":
        return _FP0(face, v)
    ell = math.sqrt(max(0.0, 1.0 - min(1.0, v) ** 2))
    if v <= 0.55:
        return ell
    if v <= 0.80:
        return max(ell, 0.60 + (0.92 - 0.60) * (v - 0.55) / 0.25)
    if v <= 0.985:
        return 0.92 + (0.80 - 0.92) * (v - 0.80) / 0.185
    return 0.0


def main():
    personas, _doc = load_data()
    ids = list(personas)
    bad = 0
    try:
        print("== 1. 现状：探针必须全 PASS ==")
        acc = run(ids, {"A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "D3", "E1", "E2"})
        n_bad = sum(1 for vs in acc.values() for v in vs if not v)
        print("   " + "  ".join(f"{k}={sum(1 for v in vs if v)}/{len(vs)}"
                                 for k, vs in sorted(acc.items())))
        if n_bad:
            print(f"   FAIL: 现状仍有 {n_bad} 项不通过")
            bad += 1
        else:
            print("   OK")

        print("\n== 2. 反向：探针灵敏度（合成打洞，洞口必须落在判定窗里）==")
        bad += check("A1 判定窗内凿洞", ids, "A1", True,
                     damage={pid: {"A1": damage_box(pid, "A1")} for pid in ids})
        bad += check("A2 判定窗内凿洞", ids, "A2", True,
                     damage={pid: {"A2": damage_box(pid, "A2")} for pid in ids})

        print("\n== 3. 反向：注回修复前的取值，对应探针必须 FAIL ==")
        ic.draw_character = legacy_shoulder_draw()
        bad += check("旧肩楔（肩部体块不外扩）", ids, "A1", True)
        ic.draw_character = _D0
        ic.face_geo = qa_shape.face_geo = legacy_geo(hip_hw=None)
        bad += check("胯块只按腿外缘铺（旧值）", ids, "A2", True)
        ic.face_geo = qa_shape.face_geo = _G0

        print("\n== 4. 反向：袖子与衣同色 → B1 必须 FAIL ==")
        ic.sleeve_color = lambda base, f=0.13: base
        bad += check("sleeve_color 退回同色（旧行为）", ids, "B1", True)
        ic.sleeve_color = _S0

        # ---- 坑㉓：下颌轮廓 ----
        print("\n== 5. 反向：注回旧方颌（v=0.80 处外扩到 0.92·rx）→ D2 必须 FAIL ==")
        ic.face_profile = legacy_square_profile
        qa_shape.face_profile = legacy_square_profile
        bad += check("旧 square 下颌 polygon", ids, "D2", True)
        ic.face_profile = qa_shape.face_profile = _FP0

        print("\n== 6. 反向：注回旧心形（顶点折返的横向针尖）→ D3 必须 FAIL ==")
        # 注意挂 D3 不挂 D1：旧形在 v=0.90 处还有 0.43·rx，宽度是够的，
        # 针尖只活在最后那 4px 里——只有「斜率必须越来越陡」才抓得到（D1 抓不到）。
        def legacy_jaw_point(face, s):
            if face != "heart":
                return _JP0(face, s)
            return 1 - 1.2 * s + 0.2 * s * s, 0.42 + 1.26 * s - 0.64 * s * s
        ic.jaw_point = legacy_jaw_point
        try:
            bad += check("旧 heart 下颌折线（二阶导 +0.4 外凸）",
                         [i for i in ids if personas[i]["movement"]["face"] == "heart"], "D3", True)
        finally:
            ic.jaw_point = _JP0

        print("\n== 7. 反向：撤掉发帘内缘下限（头发夹进下颌）→ D1 必须 FAIL ==")
        ic.HAIR_CHEEK_KEEP = 0.0                              # 下限归零 = 退回「内缘跟头缘走」
        try:
            bad += check("side_curtain 内缘无下限（旧行为）",
                         [i for i in ids if personas[i]["hairStyle"] in
                          ("bob", "bob_bangs", "wavy_lob", "wavy_long", "long_straight", "long_bangs")],
                         "D1", True)
        finally:
            ic.HAIR_CHEEK_KEEP = _HAIR_KEEP0

        print("\n== 8. 反向：胡须退回旧 PIE（糊到脖子上、嘴上没胡子）→ E1/E2 必须 FAIL ==")
        beard_ids = [i for i in ids
                     if "beard" in {a["code"] for a in personas[i].get("accessories", [])}]
        ic.BEARD_LEGACY = True
        try:
            bad += check("旧胡须 PIE → 胡须下过脖子", beard_ids, "E1", True)
            bad += check("旧胡须 PIE → 嘴上无八字胡", beard_ids, "E2", True)
        finally:
            ic.BEARD_LEGACY = False

        # ---- 坑㉑：顶戴墨镜 ----
        import tempfile
        sg_ids = [pid for pid in ids
                  if "sunglasses_head" in {a["code"] for a in personas[pid].get("accessories", [])}]
        with tempfile.TemporaryDirectory() as td:
            frames = {pid: _render_sunglasses_persona(pid, personas, td) for pid in sg_ids}
            base = {pid: _glasses_probe(pid, frames[pid]) for pid in sg_ids}

            print(f"\n== 9. 坑⑳ 顶戴墨镜：现状必须全 PASS（{len(sg_ids)} 人）==")
            for pid, got in base.items():
                bad += check_glasses(f"{pid} 现状", {"glasses_frame": True, "glasses_lens": True}, got)

            print("\n== 10. 反向：镜框被头发吞掉（金属色 == 发色）→ glasses_frame 阶跃必为 0 ==")
            # omar 发色 (43,37,48) 与 metal_dark (44,44,52) 本就只差 8.1；
            # 把镜框画成发色就精确复现「框看不见」——阶跃探针必须 FAIL。
            hair = ic.hexc(personas[sg_ids[0]]["palette"]["hair"])
            md0 = ic.THEME["metal_dark"]
            ic.THEME["metal_dark"] = hair      # 原地改：qa_char 直接 import 的是同一个 dict
            try:
                for pid in sg_ids:
                    f2 = _render_sunglasses_persona(pid, personas, td)
                    bad += check_glasses(f"{pid} 镜框染成发色",
                                         {"glasses_frame": False, "glasses_lens": True},
                                         _glasses_probe(pid, f2))
            finally:
                ic.THEME["metal_dark"] = md0

            print("\n== 11. 反向：镜片被吞掉（lens 椭圆退化为零高）→ glasses_lens 必须 FAIL ==")
            ic.SUNGLASS_HEAD = {**ic.SUNGLASS_HEAD, "lens_up": 0.0, "lens_dn": 0.0}
            try:
                for pid in sg_ids:
                    f2 = _render_sunglasses_persona(pid, personas, td)
                    bad += check_glasses(f"{pid} 镜片消失",
                                         {"glasses_frame": True, "glasses_lens": False},
                                         _glasses_probe(pid, f2))
            finally:
                ic.SUNGLASS_HEAD = dict(_SH0)

            print("\n== 12. 根因留证：旧魔数取样点 (hy-0.76ry) 读到的必须是镜片而不是镜框 ==")
            for pid in sg_ids:
                p = personas[pid]
                G = ic.face_geo(p["movement"]["face"])
                im = char_sheet.flatten(char_sheet.figure(p, None, scale=1.0))
                old = im.getpixel((int(G["cx"] - ic.SUNGLASS_HEAD["dx"]),
                                   int(G["hy"] - G["ry"] * 0.76)))
                is_lens = sum((a - b) ** 2 for a, b in zip(old, ic.THEME["lens"])) ** 0.5 <= 12
                mark = "OK  " if is_lens else "FAIL"
                print(f"   {mark} {pid} 旧点像素={tuple(old[:3])} lens={ic.THEME['lens']} → "
                      f"{'确认落在镜片上（这正是旧探针恒 FAIL 的原因）' if is_lens else '不是镜片，根因判断有误'}")
                bad += 0 if is_lens else 1
    finally:
        ic.face_geo = qa_shape.face_geo = _G0
        ic.sleeve_color = _S0
        ic.draw_character = _D0
        ic.SUNGLASS_HEAD = dict(_SH0)

    print("\nSHAPE FIX VERIFY " + ("PASS" if not bad else f"FAIL ({bad})"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

