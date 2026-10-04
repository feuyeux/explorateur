#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_schema.py — 场景数据前置校验层（parse 与 render 之间）

**为什么需要**：`scene.json` 此前是自由 dict，没有任何 schema 约束。字段缺失、token
对不上、装置 style 拼错，都要等到**渲染时**才炸，或者更糟——不炸但静默出错片。
`qa_scene` 第 1 组「产物规格」是出片**之后**才发现问题的，属于事后诸葛。

本模块是纯函数 `validate_scene()`：输入 scene dict（可选带班底数据），返回问题列表，
空列表 = 通过。不做 I/O、不抛异常，因此可以被反向验证脚本直接喂坏数据。

判定依据全部来自既有事实源，零硬编码：
  - 情绪集   → intro_cards.MOOD_FACE 的键
  - 姿态码集 → intro_cards.POSE_CODES（+ 入场专用 bounce_in）
  - 装置样式 → scene_video.DEVICE_STYLES
  - 选角     → personas.json（每 locale 男女各一人）× intro-cards.json cast 表

接入点（两处）：
  1. parse_scene 写完 scene.json 立刻自检——解析阶段就失败，不产出半成品
  2. `usine-validate --scene <id>` 独立复查，不重跑解析
"""
import re

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
VALID_SPEAKERS = ("A", "B")
ENERGIES = ("lively", "steady")
# 已实现的形态。**刻意只放真的能渲染的**：把未实现的形态写进注册表会造出
# 「声明合法但渲不出来」的坑，比直接报错更难查。骨架本身是数据（beats），换形态＝换节拍表；
# 但换一种形态的*画面*（独白/小测长什么样）仍需实现渲染，注册表随之增长。
FORMS = ("dialogue",)
# 入场动画不是 pose_for 注册的姿态码，单独放行（scene_video 入口处理）
ENTRY_POSE = "bounce_in"


def _registries():
    """延迟取事实源：避免 scene_schema ← parse_scene ← data ← intro_cards 的加载期环。"""
    from . import intro_cards
    from . import scene_video
    return {
        "moods": set(intro_cards.MOOD_FACE),
        "poses": set(intro_cards.POSE_CODES) | {ENTRY_POSE},
        "device_styles": set(scene_video.DEVICE_STYLES),
    }


def validate_scene(scene, personas=None, cards=None):
    """校验 scene dict。返回问题字符串列表（空 = 通过）。

    Args:
        scene: parse_scene 产出的 scene.json 内容
        personas: {id: persona}；给了才查选角与班底覆盖
        cards: intro-cards.json 全文（含 cast 表）；给了才查选角
    """
    reg = _registries()
    errs = []

    def bad(msg):
        errs.append(msg)

    # ---- 1. 顶层必填 ----
    for k in ("id", "sceneId", "title", "tokenOrder", "tokens", "tokenWords", "locales"):
        if not scene.get(k):
            bad(f"顶层字段缺失或为空：{k}")

    if errs:
        return errs                      # 必填都没齐，后面读会 KeyError

    # ---- 2. 时长预算 ----
    db = scene.get("durationBudget")
    if db is not None:
        if not (isinstance(db, (list, tuple)) and len(db) == 2):
            bad(f"durationBudget 应为 [lo, hi] 两元素，实得 {db!r}")
        elif not (float(db[0]) < float(db[1])):
            bad(f"durationBudget 区间反了：{db[0]} ≥ {db[1]}")

    # ---- 3. RTL 名单必须指向真实存在的 locale ----
    locales = scene["locales"]
    for lc in scene.get("rtlLocales") or []:
        if lc not in locales:
            bad(f"rtlLocales 列了不存在的 locale：{lc}")

    # ---- 4. token 表：键集一致 + chip 两型 ----
    order = list(scene["tokenOrder"])
    tokens = scene["tokens"]
    missing = [k for k in order if k not in tokens]
    extra = [k for k in tokens if k not in order]
    if missing:
        bad(f"tokenOrder 有、tokens 没有：{missing}")
    if extra:
        bad(f"tokens 有、tokenOrder 没有：{extra}")
    if len(set(order)) != len(order):
        dup = [k for k in set(order) if order.count(k) > 1]
        bad(f"tokenOrder 有重复 key：{dup}")
    for k in order:
        chip = tokens.get(k)
        if chip is None:
            continue
        s = str(chip).strip()
        # chip 两型的真实契约在 `scene_video.chip_color`：以 # 开头 = 色片（须是 #RRGGBB），
        # 其余非空字符串 = 字牌（走文字层贴图）。`parse_spec` 会把 md 里的引号 strip 掉，
        # 所以 `"1"` 与 `1` 在落库后不可区分——**引号只是书写习惯，不是判据**。
        if not s:
            bad(f"token {k!r} 的 chip 为空")
        elif s.startswith("#") and not HEX_RE.match(s):
            bad(f"token {k!r} 的 chip 非法：{chip!r}（以 # 开头必须是 #RRGGBB）")

    # ---- 5. 逐 locale ----
    for lc, loc in locales.items():
        for k in ("langLabel", "aName", "bName"):
            if not loc.get(k):
                bad(f"{lc}: 字段缺失或为空 {k}")
        if not loc.get("dialogue"):
            bad(f"{lc}: dialogue 为空（该语种没有台词）")

        # 5a. 词表覆盖：§5 词表必须与 §0 token 书写序一致
        words = (scene.get("tokenWords") or {}).get(lc)
        if words is None:
            bad(f"{lc}: tokenWords 缺该语种（§5 词表必须逐语种齐备）")
        else:
            wkeys = [w.get("key") for w in words]
            if wkeys != order:
                bad(f"{lc}: §5 词表列序/键集与 §0.1 token 书写序不一致：{wkeys} ≠ {order}")

        # 5b. 装置样式在注册表内
        dev = (loc.get("prop") or {}).get("device")
        if dev:
            st = dev.get("style")
            if st not in reg["device_styles"]:
                bad(f"{lc}: 装置 style {st!r} 不在 DEVICE_STYLES 注册表内")

        # 5c. 台词行
        seen_i = set()
        for ln in (loc.get("dialogue") or []):
            i = ln.get("i")
            if i in seen_i:
                bad(f"{lc}: 台词行号重复 i={i}")
            seen_i.add(i)
            sp = ln.get("speaker")
            if sp not in VALID_SPEAKERS:
                bad(f"{lc} #{i}: speaker={sp!r} 非法（只许 A/B）")
            if ln.get("mood") not in reg["moods"]:
                bad(f"{lc} #{i}: mood={ln.get('mood')!r} 不在情绪表内（{sorted(reg['moods'])}）")
            for pose in (ln.get("gesture") or {}).get("poses") or []:
                if pose not in reg["poses"]:
                    bad(f"{lc} #{i}: 手势码 {pose!r} 不在 POSE_CODES 注册表内")
            tk = ln.get("tokenKey")
            if tk and tk not in order:
                bad(f"{lc} #{i}: tokenKey={tk!r} 不在 §0.1 token 表内")
            if not (ln.get("text") or "").strip():
                bad(f"{lc} #{i}: 台词为空")

        # 5d. 该课自己声明的注记下限——在 parse 阶段就查，不等渲染。
        # （门禁要放在「还能便宜地修」的地方：处方是加 ⚑ 段，改文本远比改代码便宜。）
        floor = int(scene.get("noteFloor") or 0)
        if floor:
            n_note = sum(1 for ln in (loc.get("dialogue") or []) if ln.get("note"))
            if n_note < floor:
                bad(f"{lc}: ⚑ 注记行 {n_note} < §0 noteFloor 声明的 {floor}"
                    f"（注记按设计可选，但本课声明了就要够）")

    # ---- 6. 语体差承诺（§0.3）：列了就必须有非空 marker ----
    for lc, spec in (scene.get("speechLevels") or {}).items():
        if lc not in locales:
            bad(f"speechLevels 列了不存在的 locale：{lc}")
        if not (spec or {}).get("marker"):
            bad(f"speechLevels[{lc}] 缺 marker：§0.3 承诺的语体差没有验收标记，"
                f"这条承诺在文本层无法验证（等于没承诺）")

    # ---- 7. 选角可解（需要班底数据）----
    cast = {}
    if personas is not None and cards is not None:
        for lc, loc in locales.items():
            for role, want in (("A", loc.get("aName")), ("B", loc.get("bName"))):
                ids = [pid for pid, p in personas.items()
                       if p.get("locale") == lc and (cards.get("cast") or {}).get(pid) == role]
                if len(ids) != 1:
                    bad(f"{lc} {role} 角选派异常：{ids or '（班底里没有该 locale 的人）'}")
                    continue
                cast[(lc, role)] = personas[ids[0]]
                got = (personas[ids[0]].get("name") or {}).get("native")
                if want and got != want:
                    bad(f"{lc} {role} 角与剧本 §4 不符：档案 {got!r} ≠ 剧本 {want!r}")
                # §0.4 声明的角色气质要与实际选角对账：A/B 选反是真实发生过的错误，
                # 而剧本只写姓名、看不出谁活泼谁沉稳——声明就是为这件事准备的。
                want_energy = (scene.get("roles") or {}).get(role)
                if want_energy and personas[ids[0]].get("energy") != want_energy:
                    bad(f"{lc} {role} 角气质与 §0.4 声明不符："
                        f"{personas[ids[0]].get('name', {}).get('native')} 的 energy="
                        f"{personas[ids[0]].get('energy')!r} ≠ 声明 {want_energy!r}")
        known = {p.get("locale") for p in personas.values()}
        for lc in locales:
            if lc not in known:
                bad(f"{lc}: 班底里没有这个语种的人（personas.json 无对应 locale）")

    # ---- 8. 跨文件彩蛋引用（需要班底数据）----
    # 剧本里「班底彩蛋：江远夹克 #35486E」这类批注必须指向**本课某位演员真实色板**里的值。
    # 抓的是 md 里的悬空引用：人设改色板后，剧本里的旧色值不会自动跟着变。
    if personas is not None and cards is not None:
        for lc, loc in locales.items():
            performers = [cast[(lc, r)] for r in ("A", "B") if (lc, r) in cast]
            for ln in (loc.get("dialogue") or []):
                egg = ln.get("easterEgg")
                if not egg:
                    continue
                i = ln.get("i")
                hexv = str(egg.get("hex") or "").upper()
                label = egg.get("label") or ""
                named = [p for p in performers
                         if (p.get("name") or {}).get("native")
                         and (p["name"]["native"] in label)]
                if len(named) == 1:
                    owner = named[0]
                    where = _palette_hexes(owner)
                    if hexv not in where:
                        bad(f"{lc} #{i}: 彩蛋色值 {hexv} 不在 {owner['name']['native']} "
                            f"的色板里（标注「{label}」）——换角/改色板后剧本没跟着改")
                elif len(named) > 1:
                    bad(f"{lc} #{i}: 彩蛋标注「{label}」同时匹配多位演员，指代不唯一")
                else:
                    union = set().union(*(_palette_hexes(p) for p in performers)) if performers else set()
                    if hexv not in union:
                        bad(f"{lc} #{i}: 彩蛋色值 {hexv} 不在本课任何演员的色板里"
                            f"（标注「{label}」未能解析到演员名）")

    # ---- 8. 形态 / 角色 / 骨架声明（§0.4 §0.5）----
    # 已实现的形态只有 dialogue；骨架本身是数据（beats），换形态＝换一张节拍表。
    # 这里只承认**真的能渲染**的形态——把未实现的形态写进注册表会造出
    # 「声明合法但渲不出来」的坑，比直接报错更难查。
    form = scene.get("form") or "dialogue"
    if form not in FORMS:
        bad(f"form={form!r} 尚未实现（已实现：{sorted(FORMS)}）")

    roles = scene.get("roles") or {}
    for r, energy in roles.items():
        if r not in VALID_SPEAKERS:
            bad(f"roles 声明了非 A/B 的角色：{r!r}")
        if energy not in ENERGIES:
            bad(f"roles[{r}] 的 energy={energy!r} 不认识（{sorted(ENERGIES)}）")

    beats = scene.get("beats") or []
    if not beats:
        bad("§0.5 缺骨架节拍表（beats）——台词行的角色/问句归属没有来源")
    for b in beats:
        if b.get("ask") not in ("even", "odd", "-", "none", ""):
            bad(f"节拍 {b.get('beat')!r} 的 ask={b.get('ask')!r} 只能是 even/odd/-")
        ab = b.get("askBy") or "-"
        if ab not in VALID_SPEAKERS and ab != "-":
            bad(f"节拍 {b.get('beat')!r} 的 askBy={ab!r} 只能是 A/B/-")
        if ab != "-" and roles and ab not in roles:
            bad(f"节拍 {b.get('beat')!r} 的 askBy={ab!r} 未在 §0.4 roles 里声明")
    seen_beats = [b.get("beat") for b in beats]
    if len(set(seen_beats)) != len(seen_beats):
        bad(f"节拍名有重复：{seen_beats}")

    return errs


def _palette_hexes(persona):
    """一个人设身上所有可被剧本引用的 hex：色板各槽 + identity。"""
    out = set()
    for v in (persona.get("palette") or {}).values():
        if isinstance(v, str) and v.startswith("#"):
            out.add(v.upper())
    ident = persona.get("identity")
    if isinstance(ident, str) and ident.startswith("#"):
        out.add(ident.upper())
    return out


def main(argv=None):
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="场景数据前置校验（parse 与 render 之间）")
    ap.add_argument("--scene", required=True, help="场景 id，如 colors")
    ap.add_argument("--no-cast", action="store_true", help="跳过选角/班底检查")
    args = ap.parse_args(argv)

    from .data import cards_doc, personas, scene_doc
    scene = scene_doc(args.scene)
    errs = validate_scene(scene,
                          None if args.no_cast else personas(),
                          None if args.no_cast else cards_doc())
    head = f"场景 {scene.get('id')}：{scene.get('title')}（{len(scene.get('locales') or {})} 语种）"
    print("=" * 66)
    print(f"场景数据校验：{head}")
    print("=" * 66)
    if not errs:
        print("  SCENE SCHEMA PASS")
        return 0
    for e in errs:
        print(f"  FAIL {e}")
    print(f"\n{len(errs)} 项不合规")
    return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
