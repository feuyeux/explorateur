# -*- coding: utf-8 -*-
"""persona.py — 人设契约校验器（②③ 数据检查层的 persona 半边）

契约文档：`personas/schema.md`（搬运自 explorateur/personas/）。本模块是它的机器判定：
`validate_persona(p) -> 问题列表`（纯函数、不做 I/O——因此反向验证可以直接喂坏数据）。

**合法值一律现取注册表，不复制**（纪律 7）：
- 脸型 → `rig.FACE_SPECS` 的键（那正是绘制规格的唯一事实源）；
- moves 槽位值 → `rig.POSE_CODES` 的键（姿态库的唯一事实源）；
- 声线安全域 → `tts.SAFE_RATE / SAFE_PITCH`（|rate|≤20%、|pitch|≤12Hz——越界劈嗓）。

**班底级不变量**（explorateur 选角规则）：每语种恰两人、一男一女、一活泼一沉稳
（活泼者当 A / 沉稳者当 B 的戏剧分工天然成立）；id 全局唯一（id = rnd 种子命名空间，
撞 id = 幂等破坏）。`validate_roster(personas)` 判这两条。

字段存在性按 schema 实存口径：`movement.seed`/`gaze` 不落 JSON（seed ≡ id、gaze 由
rig 统一实现）；`name.gloss`/`voice.timbre`/`relation`/`quirk` 是档案维度，缺了不炸
渲染但档案不完整——按「档案字段缺失」报。
"""
from __future__ import annotations

import re
import sys

from . import rig
from . import tts

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LOCALE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}$")
_SLOTS = ("point", "palm_open", "both_hands", "nod", "jump_celebrate",
          "mini_jump", "wave", "scratch_head", "deadpan_nod")
_PHYSICS = ("swing", "bounce", "reflect")
_OUTFIT_KINDS = ("tunic", "pinafore", "vest")


def _bad_hex(v) -> bool:
    return not isinstance(v, str) or not _HEX.match(v)


def validate_persona(p: dict, *, where: str = "") -> list[str]:
    """一个人设的全部问题（空列表 = 通过）。where 用于批量报错时定位（如 id）。"""
    w = where or str(p.get("id") or "<无 id>")
    problems: list[str] = []
    add = problems.append

    # ---- 身份 ----
    if not isinstance(p.get("id"), str) or not p["id"].strip():
        add(f"{w}: id 缺失或为空（id = rnd 种子命名空间，空 id 破坏幂等）")
    if not isinstance(p.get("locale"), str) or not _LOCALE.match(p.get("locale", "")):
        add(f"{w}: locale 非法（{p.get('locale')!r}，应为 xx-XX）")
    if p.get("gender") not in ("female", "male"):
        add(f"{w}: gender 非法（{p.get('gender')!r}）")
    if p.get("energy") not in ("lively", "steady"):
        add(f"{w}: energy 非法（{p.get('energy')!r}，活泼/沉稳决定 bounce 与语速基线族）")
    name = p.get("name") or {}
    for k in ("native", "latin"):
        if not isinstance(name.get(k), str) or not name[k].strip():
            add(f"{w}: name.{k} 缺失")
    for k in ("archetype", "quirk"):
        if not isinstance(p.get(k), str) or not p[k].strip():
            add(f"{w}: 档案字段 {k} 缺失（2026-10-03 起 28 人全量入档）")
    rel = p.get("relation") or {}
    if not isinstance(rel.get("partner"), str) or not rel["partner"].strip():
        add(f"{w}: relation.partner 缺失（语种内搭档）")

    # ---- 声线（消费方 = feuille.tts / rig 的情绪增量）----
    # 实存 JSON 无 engine 字段（引擎由 feuille.tts 固定为 edge-tts）；带上了就必须对。
    v = p.get("voice") or {}
    if v.get("engine") is not None and v["engine"] != "edge-tts":
        add(f"{w}: voice.engine 应为 edge-tts（得 {v['engine']!r}）")
    if not isinstance(v.get("voiceId"), str) or not v["voiceId"].strip():
        add(f"{w}: voiceId 缺失（固定音色，永不随场景重选）")
    r = tts.parse_signed(v.get("rate", "+0%"))
    pi = tts.parse_signed(v.get("pitch", "+0Hz"))
    if not (tts.SAFE_RATE[0] <= r <= tts.SAFE_RATE[1]):
        add(f"{w}: rate {v.get('rate')!r} 越出安全域 ±{tts.SAFE_RATE[1]}%（劈嗓）")
    if not (tts.SAFE_PITCH[0] <= pi <= tts.SAFE_PITCH[1]):
        add(f"{w}: pitch {v.get('pitch')!r} 越出安全域 ±{tts.SAFE_PITCH[1]}Hz")
    if not isinstance(v.get("timbre"), str) or not v["timbre"].strip():
        add(f"{w}: voice.timbre 缺失（选型依据）")

    # ---- 运动（消费方 = rig.face_geo / draw_character）----
    m = p.get("movement") or {}
    face = m.get("face")
    if face not in rig.FACE_SPECS:                      # ← 现取注册表
        add(f"{w}: movement.face {face!r} 不在 FACE_SPECS（{sorted(rig.FACE_SPECS)}）")
    for k in ("bounce", "blinkCycleSec", "breathAmp"):
        val = m.get(k)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            add(f"{w}: movement.{k} 应为正数（得 {val!r}）")

    # ---- moves 槽位表（值必须是姿态库里的码）----
    moves = p.get("moves") or {}
    for slot, code in moves.items():
        if slot not in _SLOTS:
            add(f"{w}: moves 槽位 {slot!r} 不在已知槽位表（{_SLOTS}）——私加槽位=剧本语义漂移")
        if code not in rig.POSE_CODES:                  # ← 现取注册表
            add(f"{w}: moves.{slot} = {code!r} 不在 POSE_CODES（姿态库 {len(rig.POSE_CODES)} 码）")

    # ---- 调色板（六键、hex；identity 在**顶层**（语种标识色，每人恰一处点缀）；
    #      描边/五官常量色走 rig.THEME，不在此表）----
    if _bad_hex(p.get("identity")):
        add(f"{w}: identity 非法（{p.get('identity')!r}，应为 #RRGGBB）")
    pal = p.get("palette") or {}
    for k in ("hair", "hairHighlight", "skin", "skinShade",
              "outfitTop", "outfitBottom"):
        if _bad_hex(pal.get(k)):
            add(f"{w}: palette.{k} 非法（{pal.get(k)!r}，应为 #RRGGBB）")
    # hairStyle 的合法形由 draw_character 的分支决定（无注册表可现取）——只判非空
    if not isinstance(p.get("hairStyle"), str) or not p["hairStyle"].strip():
        add(f"{w}: hairStyle 缺失（绘制分支按它选发型）")

    # ---- 可选段 ----
    outfit = p.get("outfit") or {}
    if "bottom" in outfit and outfit["bottom"] not in ("skirt",):
        add(f"{w}: outfit.bottom 非法（{outfit['bottom']!r}）")
    if "kind" in outfit and outfit["kind"] not in _OUTFIT_KINDS:
        add(f"{w}: outfit.kind 非法（{outfit['kind']!r}，{_OUTFIT_KINDS}）")
    # ---- 挂件（实存口径：{code, accent?, physics?}——code 是绘制分支的判据，
    #      如 qa_shape 以 code=="beard" 分流下颌探针）----
    accs = p.get("accessories") or []
    if not isinstance(accs, list):
        add(f"{w}: accessories 应为列表")
        accs = []
    for i, a in enumerate(accs):
        if not isinstance(a, dict):
            add(f"{w}: accessories[{i}] 应为对象")
            continue
        if not isinstance(a.get("code"), str) or not a["code"].strip():
            add(f"{w}: accessories[{i}].code 缺失（绘制分支按它选挂件）")
        if a.get("accent") is not None and not isinstance(a["accent"], bool):
            add(f"{w}: accessories[{i}].accent 应为布尔")
        if a.get("physics") is not None and a["physics"] not in _PHYSICS:
            add(f"{w}: accessories[{i}].physics 非法（{a.get('physics')!r}）")
    skin = p.get("skin") or {}
    for i, patch in enumerate(skin.get("patches") or []):
        if _bad_hex(patch.get("color")):
            add(f"{w}: skin.patches[{i}].color 非法 hex")
    return problems


def validate_roster(personas: list) -> list[str]:
    """班底级不变量：id 唯一；每语种恰 {一男一女} × {一活泼一沉稳}。"""
    problems: list[str] = []
    ids: dict[str, int] = {}
    by_locale: dict[str, list] = {}
    for p in personas:
        pid = p.get("id")
        ids[pid] = ids.get(pid, 0) + 1
        by_locale.setdefault(p.get("locale", "?"), []).append(p)
    for pid, n in ids.items():
        if n > 1:
            problems.append(f"id {pid!r} 重复 {n} 次（id = 种子命名空间，撞 id 破坏幂等）")
    for loc, ps in sorted(by_locale.items()):
        genders = sorted(p.get("gender", "?") for p in ps)
        energies = sorted(p.get("energy", "?") for p in ps)
        if len(ps) != 2 or genders != ["female", "male"] or energies != ["lively", "steady"]:
            problems.append(
                f"{loc}: 班底配对应为 一男一女 × 一活泼一沉稳（实得 gender={genders} "
                f"energy={energies}，{len(ps)} 人）——活泼当 A / 沉稳当 B 的选角分工依赖它")
    return problems


def main(argv=None) -> int:
    """cli.py 路由入口：`uv run feuille persona validate`（无参可调用——
    缺省体检 feuille/personas 班底）。

    人设契约的**独立**体检入口：不经过任何 skill 文档或课件目录也能跑。
    判定本体就是上面的 `validate_persona` / `validate_roster`（纯函数，
    反向验证在 scripts/verify_personas.py）；这里只做取数与报告。
    逐人走**原始清单**（`personas_doc()`）而不是 `{id: persona}` 索引——
    索引会把重复 id 静默折叠成一个，班底级「id 唯一」就永远验不出来。
    """
    import argparse
    # router 契约（cli.py）：`fn()` 裸调 = 剩余参数为空——None 必须当 [] 处理，
    # 不能回落 sys.argv（那会把 router 已 pop 掉的组名/命令名又吃回去，
    # `feuille lesson doctor` 裸调就是这么撞的 unrecognized arguments）。
    # 模块直跑的参数由 __main__ 块显式传 sys.argv[1:]。
    argv = list(argv) if argv is not None else []
    ap = argparse.ArgumentParser(
        prog="feuille persona validate",
        description="人设契约体检：逐人 validate_persona + 班底不变量 validate_roster")
    ap.add_argument("--personas", default=None,
                    help="personas 目录（缺省 = feuille/personas 班底）")
    args = ap.parse_args(argv)

    from .data import personas_doc
    plist = personas_doc(args.personas)["personas"]

    problems: list[str] = []
    for p in plist:
        problems += validate_persona(p)
    problems += validate_roster(plist)

    print("=" * 66)
    print(f"人设契约体检：{len(plist)} 人班底（validate_persona 逐人 + 班底不变量）")
    print("=" * 66)
    if not problems:
        print("  PERSONA PASS：逐人零问题；班底不变量全过"
              "（id 唯一 / 每语种一男一女 × 一活泼一沉稳）")
        return 0
    for e in problems:
        print(f"  FAIL {e}")
    print(f"\n{len(problems)} 项不合规")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
