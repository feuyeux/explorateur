#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_schema.py — 场景数据前置校验层（parse 与 render 之间）

搬运自 explorateur/src/usine/scene_schema.py（466 行）。适配点（仅此三处，判据与
坑注逐字节照搬）：
- 判定源注册表改取 feuille 渲染线本体：`intro_cards.MOOD_FACE / POSE_CODES` →
  `feuille.rig`，`scene_video.DEVICE_STYLES` → `feuille.devices`（注册表已随 ⑥
  渲染线先行搬运；判定仍现取注册表，不抄名单——名单必腐烂，纪律 7）；
- main 的 scene_doc 取数加 lessons 目录（--lessons 参数，缺省 = feuille 仓库根
  lessons/，data.py 锚定）；
- 命令名 `usine-validate` → `uv run feuille scene validate`（feuille cli.py 路由表）。

使用契约：`validate_scene(scene, personas=None, cards=None) -> 问题列表`（空 = 通过）。
纯函数、不做 I/O、不抛异常——反向验证可以直接喂坏数据。选角/班底检查只在给了
personas 与 cards 两份数据时才跑（parse 自检不给、doctor 全量给）。

**为什么需要**：`scene.json` 此前是自由 dict，没有任何 schema 约束。字段缺失、token
对不上、装置 style 拼错，都要等到**渲染时**才炸，或者更糟——不炸但静默出错片。
`qa_scene` 第 1 组「产物规格」是出片**之后**才发现问题的，属于事后诸葛。

本模块是纯函数 `validate_scene()`：输入 scene dict（可选带班底数据），返回问题列表，
空列表 = 通过。不做 I/O、不抛异常，因此可以被反向验证脚本直接喂坏数据。

**人物数量不写死**：合法说话人 = §0.4 `roles` 里**本课自己声明**了谁，就是谁。
不再有一张写死的 `("A","B")` 白名单——那张表把「两人对话」当成了世界的上限，
第三个人出现时要改的是**剧本**（声明 C），不是**代码**。

判定依据全部来自既有事实源，零硬编码：
  - 情绪集   → rig.MOOD_FACE 的键
  - 姿态码集 → rig.POSE_CODES（+ 入场专用 bounce_in）
  - 装置样式 → devices.DEVICE_STYLES
  - 选角     → personas.json × intro-cards.json cast 表（dialogue）／
               §0.6 同台表按 `locale + energy` 唯一解出（polyglot）

接入点（两处）：
  1. parse_scene 写完 scene.json 立刻自检——解析阶段就失败，不产出半成品
  2. `uv run feuille scene validate --scene <id>` 独立复查，不重跑解析
"""
import re

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ENERGIES = ("lively", "steady")
# 取景（framing）是**场景级的摆位决定**，不是人物的固有属性：同一个人可以这一课站姿、
# 下一课坐长椅。写在剧本 §0.6，不写进 personas.json。
FRAMINGS = ("full", "seated", "bust")
# 已实现的形态。**刻意只放真的能渲染的**：把未实现的形态写进注册表会造出
# 「声明合法但渲不出来」的坑，比直接报错更难查。骨架本身是数据（beats），换形态＝换节拍表；
# 但换一种形态的*画面*（独白/小测长什么样）仍需实现渲染，注册表随之增长。
#   dialogue = 每语种一份独立剧本，每份两个（或 N 个）角色在本语种内对话
#   polyglot = 一份共享剧本同台多人，每人各说各的语种（每行带语种标记）
FORMS = ("dialogue", "polyglot")
# 入场动画不是 pose_for 注册的姿态码，单独放行（scene_video 入口处理）
ENTRY_POSE = "bounce_in"


def declared_roles(scene):
    """本课声明的合法角色（§0.4 roles 的键），按声明序。**空 = 没人可说话**。

    这是「合法说话人」的唯一事实源：说话人白名单不是代码里的一张表，而是剧本自己
    声明的角色集合。加第三个人 = 剧本 §0.4 多写一行，代码零改动。
    """
    return list((scene.get("roles") or {}).keys())


def is_shared_stage(scene):
    """polyglot = 多人同台共用**一份**剧本（`scene["dialogue"]`），不是每语种一份。"""
    return (scene.get("form") or "dialogue") == "polyglot"


def units_of(scene):
    """剧本的渲染单元：[(unit_key, locale, lines, loc_dict)]。

    dialogue → 每语种一个单元（unit_key = locale，各说各的，各渲一支片子）。
    polyglot → 只有一个单元（unit_key = 舞台），台词里每行自带语种。
    校验层、渲染层、qa 探针都按这份清单走，不各自 if/else 一遍。
    """
    if is_shared_stage(scene):
        lines = scene.get("dialogue") or []
        locales = scene.get("locales") or {}
        return [("stage", None, lines, {"locales": locales})]
    out = []
    for lc, loc in (scene.get("locales") or {}).items():
        out.append((lc, lc, loc.get("dialogue") or [], loc))
    return out


def _registries():
    """延迟取事实源：避免 scene_schema ← parse_scene ← data ← rig/devices 的加载期环。"""
    from . import devices
    from . import rig
    return {
        "moods": set(rig.MOOD_FACE),
        "poses": set(rig.POSE_CODES) | {ENTRY_POSE},
        "device_styles": set(devices.DEVICE_STYLES),
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

    form = scene.get("form") or "dialogue"
    shared = is_shared_stage(scene)
    roles = scene.get("roles") or {}
    allowed_speakers = declared_roles(scene)

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
        # chip 两型的真实契约在 `devices.chip_color`：以 # 开头 = 色片（须是 #RRGGBB），
        # 其余非空字符串 = 字牌（走文字层贴图）。`parse_spec` 会把 md 里的引号 strip 掉，
        # 所以 `"1"` 与 `1` 在落库后不可区分——**引号只是书写习惯，不是判据**。
        if not s:
            bad(f"token {k!r} 的 chip 为空")
        elif s.startswith("#") and not HEX_RE.match(s):
            bad(f"token {k!r} 的 chip 非法：{chip!r}（以 # 开头必须是 #RRGGBB）")

    # ---- 5. §0.4 角色声明（先于台词：说话人合法性全靠它）----
    if not roles:
        bad("§0.4 没声明任何角色——合法说话人由本课声明驱动，没有声明就没有人能说话")
    for r, energy in roles.items():
        if energy not in ENERGIES:
            bad(f"roles[{r}] 的 energy={energy!r} 不认识（{sorted(ENERGIES)}）")

    # ---- 5b. §0.6 同台表（仅 polyglot 需要：角色 ↔ 语种 ↔ 取景的绑定）----
    cast = scene.get("cast") or []
    cast_roles = [c.get("role") for c in cast]
    if shared:
        if not cast:
            bad("form=polyglot 但缺 §0.6 同台表——每个角色必须绑定一个语种与一种取景")
        for c in cast:
            r = c.get("role")
            if r not in roles:
                bad(f"§0.6 声明了 §0.4 没有的角色：{r!r}")
            if not c.get("locale"):
                bad(f"§0.6 角色 {r!r} 没绑定 locale（polyglot 里每行台词都要认语种）")
            elif c["locale"] not in locales:
                bad(f"§0.6 角色 {r!r} 绑定的 locale 不在 locales 内：{c['locale']!r}")
            fr = c.get("framing")
            if fr not in FRAMINGS:
                bad(f"§0.6 角色 {r!r} 的 framing={fr!r} 不认识（{sorted(FRAMINGS)}）")
        if len(set(cast_roles)) != len(cast_roles):
            bad(f"§0.6 有角色重复：{cast_roles}")
        missing_in_cast = [r for r in roles if r not in cast_roles]
        if missing_in_cast:
            bad(f"§0.4 声明了角色但 §0.6 没给他安排语种/取景：{missing_in_cast}")
        used = {ln.get("speaker") for _, _, lines, _ in units_of(scene) for ln in lines}
        ghost = sorted(x for x in used if x and x not in allowed_speakers)
        if ghost:
            bad(f"台词里出现了 §0.4 未声明的角色：{ghost}")
    else:
        for c in cast:
            bad(f"form=dialogue 不该有 §0.6 同台表（角色 {c.get('role')!r}）——"
                f"dialogue 形态的角色按语种各配各的")

    # ---- 6. 逐渲染单元 ----
    for unit_key, lc, lines, loc in units_of(scene):
        if shared:
            if not lines:
                bad("共享剧本（polyglot）的台词为空")
            # 每行必须自带语种：同台一份剧本混着好几种语言，`annotate` 要按**这行是谁在说**
            # 去取词表。缺了语标，那一行会去查一张空壳的词表，token 静默不亮——症状要到
            # 看片才发现「这一轮怎么没点亮」。解析层会拒，但 scene.json 是能被手改、
            # 也能被别的工具写出来的，校验层不能只在解析层守这条。
            no_lang = [ln.get("i") for ln in lines if not (ln.get("lang") or "")]
            if no_lang:
                bad(f"共享剧本里这些行没标语种：{no_lang[:8]}——"
                    f"同台形态每行都要写 `**角色 · locale**`")
            for ln in lines:
                lc = ln.get("lang")
                if lc and lc not in locales:
                    bad(f"#{ln.get('i')}: 台词行标的 locale {lc!r} 不在本课 locales 内")
            _check_lines(bad, lines, unit_key, allowed_speakers, reg, order)
            _check_notes(bad, lines, scene)
            continue

        for k in ("langLabel", "aName", "bName"):
            if not loc.get(k):
                bad(f"{lc}: 字段缺失或为空 {k}")
        if not loc.get("dialogue"):
            bad(f"{lc}: dialogue 为空（该语种没有台词）")

        # 6a. 词表覆盖：§5 词表必须与 §0 token 书写序一致
        words = (scene.get("tokenWords") or {}).get(lc)
        if words is None:
            bad(f"{lc}: tokenWords 缺该语种（§5 词表必须逐语种齐备）")
        else:
            wkeys = [w.get("key") for w in words]
            if wkeys != order:
                bad(f"{lc}: §5 词表列序/键集与 §0.1 token 书写序不一致：{wkeys} ≠ {order}")

        # 6b. 装置样式在注册表内
        dev = (loc.get("prop") or {}).get("device")
        if dev:
            st = dev.get("style")
            if st not in reg["device_styles"]:
                bad(f"{lc}: 装置 style {st!r} 不在 DEVICE_STYLES 注册表内")

        # 6c. 台词行
        _check_lines(bad, lines, unit_key, allowed_speakers, reg, order, locale=lc)
        _check_notes(bad, lines, scene, locale=lc)

    # polyglot 的词表同样逐语种校验（台词按行取语种，词表按语种给）
    if shared:
        for lc in locales:
            words = (scene.get("tokenWords") or {}).get(lc)
            if words is None:
                bad(f"{lc}: tokenWords 缺该语种（同台每行台词都按自己的语种取词）")
            else:
                wkeys = [w.get("key") for w in words]
                if wkeys != order:
                    bad(f"{lc}: §5 词表列序/键集与 §0.1 token 书写序不一致：{wkeys} ≠ {order}")
            dev = (locales[lc].get("prop") or {}).get("device")
            if dev and dev.get("style") not in reg["device_styles"]:
                bad(f"{lc}: 装置 style {dev.get('style')!r} 不在 DEVICE_STYLES 注册表内")

    # ---- 7. 语体差承诺（§0.3）：列了就必须有非空 marker ----
    for lc, spec in (scene.get("speechLevels") or {}).items():
        if lc not in locales:
            bad(f"speechLevels 列了不存在的 locale：{lc}")
        if not (spec or {}).get("marker"):
            bad(f"speechLevels[{lc}] 缺 marker：§0.3 承诺的语体差没有验收标记，"
                f"这条承诺在文本层无法验证（等于没承诺）")

    # ---- 8. 选角可解（需要班底数据）----
    if personas is not None and cards is not None:
        if shared:
            _check_shared_cast(bad, scene, personas, cards, cast)
        else:
            for lc in locales:
                for role in allowed_speakers:
                    # 姓名槽位随角色名走：§2 的小节头写 `<role>Name`（A→aName / B→bName）。
                    # 沿用既有键名，既有课零改动；第三个人只需在 md 里多写一个 cName。
                    want = locales[lc].get(f"{role.lower()}Name")
                    p = _find_dialogue_role(personas, cards, lc, role)
                    if p is None:
                        bad(f"{lc} {role} 角选派异常：班底里没有该 locale 的人或 cast 表没派角")
                        continue
                    got = (p.get("name") or {}).get("native")
                    if want and got != want:
                        bad(f"{lc} {role} 角与剧本 §4 不符：档案 {got!r} ≠ 剧本 {want!r}")
                    _check_energy(bad, p, role, roles.get(role), lc)
                if lc not in {p.get("locale") for p in personas.values()}:
                    bad(f"{lc}: 班底里没有这个语种的人（personas.json 无对应 locale）")
        # 8b. 跨文件彩蛋引用
        _check_eggs(bad, scene, personas, cards, cast, allowed_speakers)

    # ---- 9. 形态 / 骨架声明（§0.4 §0.5）----
    if form not in FORMS:
        bad(f"form={form!r} 尚未实现（已实现：{sorted(FORMS)}）")

    beats = scene.get("beats") or []
    if not beats:
        bad("§0.5 缺骨架节拍表（beats）——台词行的角色/问句归属没有来源")
    for b in beats:
        if b.get("ask") not in ("even", "odd", "-", "none", ""):
            bad(f"节拍 {b.get('beat')!r} 的 ask={b.get('ask')!r} 只能是 even/odd/-")
        ab = b.get("askBy") or "-"
        if ab != "-" and ab not in allowed_speakers:
            bad(f"节拍 {b.get('beat')!r} 的 askBy={ab!r} 未在 §0.4 roles 里声明")
    seen_beats = [b.get("beat") for b in beats]
    if len(set(seen_beats)) != len(seen_beats):
        bad(f"节拍名有重复：{seen_beats}")

    return errs


# ------------------------------------------------------------------ 台词行（两形态共用）

def _check_lines(bad, lines, unit_key, allowed, reg, order, locale=None):
    """逐行校验：说话人 ∈ §0.4 声明的角色、情绪/手势/词在注册表内、台词非空。"""
    where = f"{locale} " if locale else ""
    if not allowed:
        bad(f"{where}台词存在但 §0.4 没声明任何角色，无法判断说话人是否合法")
        return
    seen_i = set()
    for ln in lines:
        i = ln.get("i")
        if i in seen_i:
            bad(f"{where}台词行号重复 i={i}")
        seen_i.add(i)
        sp = ln.get("speaker")
        if sp not in allowed:
            bad(f"{where}#{i}: speaker={sp!r} 非法（本课 §0.4 声明的角色：{allowed}）")
        if ln.get("mood") not in reg["moods"]:
            bad(f"{where}#{i}: mood={ln.get('mood')!r} 不在情绪表内（{sorted(reg['moods'])}）")
        for pose in (ln.get("gesture") or {}).get("poses") or []:
            if pose not in reg["poses"]:
                bad(f"{where}#{i}: 手势码 {pose!r} 不在 POSE_CODES 注册表内")
        tk = ln.get("tokenKey")
        if tk and tk not in order:
            bad(f"{where}#{i}: tokenKey={tk!r} 不在 §0.1 token 表内")
        if not (ln.get("text") or "").strip():
            bad(f"{where}#{i}: 台词为空")


def _check_notes(bad, lines, scene, locale=None):
    """该课自己声明的 ⚑ 注记行下限——在 parse 阶段就查，不等渲染。
    （门禁要放在「还能便宜地修」的地方：处方是加 ⚑ 段，改文本远比改代码便宜。）"""
    floor = int(scene.get("noteFloor") or 0)
    if not floor:
        return
    n_note = sum(1 for ln in lines if ln.get("note"))
    if n_note < floor:
        bad(f"{locale or ''}: ⚑ 注记行 {n_note} < §0 noteFloor 声明的 {floor}"
            f"（注记按设计可选，但本课声明了就要够）")


# ------------------------------------------------------------------ 选角

def _find_dialogue_role(personas, cards, locale, role):
    """dialogue 形态：某语种的某角色 = 班底里 locale 匹配且 cast 表派了这个角的那一个。"""
    ids = [pid for pid, p in personas.items()
           if p.get("locale") == locale and (cards.get("cast") or {}).get(pid) == role]
    return personas[ids[0]] if len(ids) == 1 else None


def _check_shared_cast(bad, scene, personas, cards, cast):
    """polyglot 形态：角色 ↔ 演员靠 §0.6 的 `locale + energy` 唯一解出。

    为什么不用 intro-cards 的 cast 表：那张表记的是**亮相卡**里谁演 A/B，一个演员
    在全表里只有一个角色。同台三人分属三个语种，Chloé 在卡表里是 A、Аня 是 B，
    而本课要让她们演 A/B/C——表里根本没有 C。按 `locale + energy` 解则唯一且可验。
    """
    for c in cast:
        role, lc = c.get("role"), c.get("locale")
        if not role or not lc:
            continue
        want_energy = (scene.get("roles") or {}).get(role)
        cands = [p for p in personas.values() if p.get("locale") == lc]
        if not cands:
            bad(f"{role} 角绑定 {lc}，但班底里没有这个语种的人")
            continue
        picked = [p for p in cands if p.get("energy") == want_energy] if want_energy else list(cands)
        if len(picked) != 1:
            bad(f"{role} 角在 {lc} 里按 energy={want_energy!r} 解出 {len(picked)} 个："
                f"{[p['name']['native'] for p in picked] or '（无）'}——必须唯一")
            continue
        _check_energy(bad, picked[0], role, want_energy, lc, label=f"{lc} ")


def _check_energy(bad, p, role, want_energy, locale, label=""):
    """§0.4 声明的角色气质要与实际选角对账：A/B 选反是真实发生过的错误，
    而剧本只写姓名、看不出谁活泼谁沉稳——声明就是为这件事准备的。"""
    if want_energy and p.get("energy") != want_energy:
        bad(f"{label}{role} 角气质与 §0.4 声明不符："
            f"{(p.get('name') or {}).get('native')} 的 energy="
            f"{p.get('energy')!r} ≠ 声明 {want_energy!r}")


def _check_eggs(bad, scene, personas, cards, cast, allowed_speakers):
    """剧本里「班底彩蛋：江远夹克 #35486E」这类批注必须指向**本课某位演员真实色板**里的值。
    抓的是 md 里的悬空引用：人设改色板后，剧本里的旧色值不会自动跟着变。"""
    for unit_key, lc, lines, loc in units_of(scene):
        if lc is not None:
            performers = [p for p in (_find_dialogue_role(personas, cards, lc, r)
                                      for r in allowed_speakers) if p]
        else:
            performers = [p for p in (_find_shared_role(personas, scene, c) for c in cast) if p]
        for ln in lines:
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
                if hexv not in _palette_hexes(owner):
                    bad(f"{lc or ''} #{i}: 彩蛋色值 {hexv} 不在 {owner['name']['native']} "
                        f"的色板里（标注「{label}」）——换角/改色板后剧本没跟着改")
            elif len(named) > 1:
                bad(f"{lc or ''} #{i}: 彩蛋标注「{label}」同时匹配多位演员，指代不唯一")
            else:
                union = set().union(*(_palette_hexes(p) for p in performers)) if performers else set()
                if hexv not in union:
                    bad(f"{lc or ''} #{i}: 彩蛋色值 {hexv} 不在本课任何演员的色板里"
                        f"（标注「{label}」未能解析到演员名）")


def _find_shared_role(personas, scene, c):
    """同台表里某个角色解出的演员（与 _check_shared_cast 同一判据，供彩蛋校验复用）。"""
    want = (scene.get("roles") or {}).get(c.get("role"))
    cands = [p for p in personas.values() if p.get("locale") == c.get("locale")]
    picked = [p for p in cands if p.get("energy") == want] if want else list(cands)
    return picked[0] if len(picked) == 1 else None


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
    ap.add_argument("--lessons", default=None,
                    help="lessons 目录（缺省 = feuille 仓库根 lessons/；内容项目指自己的目录）")
    ap.add_argument("--no-cast", action="store_true", help="跳过选角/班底检查")
    args = ap.parse_args(argv)

    from .data import cards_doc, personas, scene_doc
    scene = scene_doc(args.scene, args.lessons)
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
