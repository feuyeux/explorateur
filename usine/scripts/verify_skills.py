#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_skills.py — skills/ 的**去歧义**门禁

仓库里有两个产线（海报驱动 / 实拍驱动），七个 skill 曾各说各话：
`multilingual-video-poetry` 与 `karaoke-video` 都在 description 里宣称
「多语种 + TTS + RTL 排版」却都不说画面从哪来，agent 只能靠猜——
于是把「一支铅笔 12 语种视频」路由到了实拍那条线，卡在「母版从哪来」
这个**正确路径下根本不该出现**的问题上。

本套件机检的就是拆掉这些歧义所立的规矩，全部是静态文件检查，**不碰浏览器与成片**
（纪律 12：门禁必须能在任何没渲过东西的机器上跑）：

- 每个 SKILL.md 都有 `## 前置输入契约` 与 `## 边界`——缺一条 = 契约丢了
- 每个 description 都带排除语句（`Not for` / `Do NOT use`）——这是 agent 的路由依据
- `## 边界` 里转交的 skill 名**必须真实存在**——不许转交幽灵
- 每个 skill 至少被**另一个 skill 的边界段**引用——不许有孤岛
- `name:` 字段必须等于目录名——路由表与实现失配
- 12 语种规范顺序只在 `one-page-poster` 定义——事实源唯一，不许各抄一份
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SRC = ROOT / "src" / "feuille"
REQUIRED_SECTIONS = ("## 前置输入契约", "## 边界")
EXCLUSION_MARKERS = ("not for", "do not use", "不用", "不适用")


def parse_skill(path: pathlib.Path) -> tuple[dict, str]:
    """切出 frontmatter 与正文。frontmatter 只解 name/description 两个键。

    **永远返回两个键**（缺失时为空串）——门禁自己崩溃比门禁 FAIL 更糟：
    崩溃会让人以为「环境坏了」而跳过它，FAIL 才会被人修。
    """
    text = path.read_text("utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {"name": "", "description": ""}, text
    head, body = m.group(1), m.group(2)
    name = re.search(r"^name:\s*(\S+)\s*$", head, re.M)
    dm = re.search(r"description:\s*>?\s*\n?(.*?)(?=\n[a-z_]+:|\Z)", head, re.S | re.M)
    return ({"name": name.group(1) if name else "",
             "description": (dm.group(1) if dm else "").strip()}, body)


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []
    skill_dirs = sorted(d for d in SKILLS.iterdir()
                        if d.is_dir() and (d / "SKILL.md").exists())
    parsed = {d.name: parse_skill(d / "SKILL.md") for d in skill_dirs}
    names = set(parsed)

    # ---- 0. 路由表存在，且列出全部 skill ----
    index = SKILLS / "README.md"
    if not index.exists():
        rows.append((False, "skills/README.md 缺失——没有总路由表，agent 只能靠猜"))
    else:
        idx = index.read_text("utf-8")
        missing = sorted(n for n in names if n not in idx)
        rows.append((not missing,
                     f"README.md 路由表覆盖全部 {len(names)} 个 skill"
                     + (f"　**漏 {missing}**" if missing else "")))

    # ---- 1. frontmatter 必须可解析（name + description 都非空）----
    for name in sorted(names):
        fm = parsed[name][0]
        ok = bool(fm["name"]) and bool(fm["description"])
        rows.append((ok,
                     f"{name} 的 frontmatter 可解析（name 与 description 都在）"
                     + ("" if ok else "　**frontmatter 缺字段或分隔符坏了**")))

    # ---- 2. 每个 skill 都有前置输入契约 + 边界 ----
    for name in sorted(names):
        body = parsed[name][1]
        miss = [s for s in REQUIRED_SECTIONS if s not in body]
        rows.append((not miss,
                     f"{name} 有「前置输入契约」与「边界」"
                     + (f"　**缺 {miss}**" if miss else "")))

    # ---- 3. description 必须带排除语句 ----
    for name in sorted(names):
        desc = parsed[name][0]["description"].lower()
        has = any(mk in desc for mk in EXCLUSION_MARKERS)
        rows.append((has,
                     f"{name} 的 description 写明了「不做什么」"
                     + ("" if has else "　**缺排除语句，agent 无从排除**")))

    # ---- 4. 边界里转交的 skill 必须真实存在 ----
    for name in sorted(names):
        body = parsed[name][1]
        seg = body.split("## 边界", 1)
        refs = set()
        if len(seg) == 2:
            tail = seg[1].split("\n## ", 1)[0]
            refs = {r for r in names | set(re.findall(r"`([a-z][a-z0-9-]{3,})`", tail))
                    if r.endswith(("-video", "-poster", "-copy", "-publishing"))}
            refs = {r for r in refs if r != name}
        ghosts = sorted(r for r in refs if r not in names)
        rows.append((not ghosts,
                     f"{name} 转交的目标都存在"
                     + (f"　**幽灵 {ghosts}**" if ghosts else "")))

    # ---- 5. 没有孤岛：每个 skill 都被另一个 skill 的边界引用 ----
    referenced: dict[str, set[str]] = {n: set() for n in names}
    for src in names:
        body = parsed[src][1]
        if "## 边界" not in body:
            continue
        tail = body.split("## 边界", 1)[1].split("\n## ", 1)[0]
        for tgt in names:
            if tgt != src and tgt in tail:
                referenced[src].add(tgt)
                referenced[tgt].add(src)
    for name in sorted(names):
        ok = bool(referenced[name])
        rows.append((ok, f"{name} 至少被一个 skill 双向关联"
                     + ("" if ok else "　**孤岛：谁都不指向它**")))

    # ---- 6. name 必须等于目录名 ----
    for name in sorted(names):
        declared = parsed[name][0]["name"]
        rows.append((declared == name,
                     f"{name} 的 frontmatter name 与目录名一致"
                     + ("" if declared == name else f"　**声明的是 {declared!r}**")))

    # ---- 7. 12 语种规范顺序只有一个事实源 ----
    canon = "中 zh"
    holders = sorted(n for n in names
                     if canon in (SKILLS / n / "SKILL.md").read_text("utf-8"))
    rows.append((holders == ["one-page-poster"],
                 "12 语种规范顺序只在 one-page-poster 定义"
                 + ("" if holders == ["one-page-poster"]
                    else f"　**重复定义于 {holders}**")))
    rows += _check_ownership(names)
    rows += _check_no_hardcoded_bins()
    return rows


def _check_no_hardcoded_bins() -> list[tuple[bool, str]]:
    """skill 的持久脚本不得硬编码外部可执行文件名。

    这不是洁癖：`render_poster.sh` 曾写死 `google-chrome`，而 SKILL.md 却写着
    「可用 $CHROME_BIN 覆盖」——文档说谎 + 在只有 Edge 的机器上直接失败。
    外部可执行文件（浏览器 / ffmpeg / ffprobe / magick）的解析是
    `library/platform.py` 的唯一事实源（AGENTS.md 跨平台硬约定 1），skill 脚本
    只许调它。`assets/example/` 豁免：那是历史项目的只读归档（实跑在本机项目
    目录，不随约定翻新）；`scripts/` 等持久工具必须守约。
    """
    hard = re.compile(r"(?<![\w/.-])(google-chrome|chromium|msedge|ffmpeg|ffprobe|magick)"
                      r"(?![\w-])")
    offenders = []
    quoted = re.compile(r"'[^']*'|\"[^\"]*\"")
    for p in sorted(SKILLS.rglob("*")):
        if p.suffix not in (".sh", ".py") or not p.is_file():
            continue
        parts = p.relative_to(SKILLS).parts
        if "example" in parts:            # assets/example = 历史归档，豁免
            continue
        for i, ln in enumerate(p.read_text("utf-8").splitlines(), 1):
            code = ln.strip()
            if not code or code.startswith("#"):
                continue
            # 剥掉引号内的内容：报错文案里提一嘴可执行名不算硬编码
            if hard.search(quoted.sub("", code)):
                offenders.append(f"{p.relative_to(SKILLS)}:{i}")
    return [(not offenders,
             "skill 持久脚本不硬编码浏览器/ffmpeg/ffprobe/magick 名"
             "（走 library 的 platform resolver；assets/example 归档豁免）"
             + (f"　**硬编码于 {offenders}**" if offenders else ""))]


def _check_ownership(names: set[str]) -> list[tuple[bool, str]]:
    """`ownership.json` 与磁盘、与 SKILL.md 三方一致。

    这是「skill 之外不该有业务代码」的机检形态：不是说文件必须搬走，而是
    **每个模块的归属必须唯一、显式、可查**——搬不搬是第二步，歧义先除掉。
    """
    rows: list[tuple[bool, str]] = []
    opath = ROOT / "ownership.json"
    if not opath.exists():
        return [(False, "ownership.json 缺失——模块归属无事实源，等于没声明")]

    own = json.loads(opath.read_text("utf-8"))
    skill_map: dict[str, dict] = own.get("skills", {})
    library: dict = own.get("library", {})
    infra: dict = own.get("infrastructure", {})
    unclaimed: dict = own.get("unclaimed", {})

    # ---- 8. 归属清单里的 owner 必须都是真 skill / 真模块 ----
    ghosts = sorted(s for s in skill_map if s not in names)
    rows.append((not ghosts,
                 f"ownership.json 里 {len(skill_map)} 个 owner 都是真 skill"
                 + (f"　**幽灵 {ghosts}**" if ghosts else "")))

    # ---- 8b. 存量必须消化完：unclaimed 为空 ----
    rows.append((not unclaimed,
                 f"存量代码全部消化完（unclaimed 为空）"
                 + (f"　**仍有 {len(unclaimed)} 个无主：{sorted(unclaimed)}**"
                    if unclaimed else "")))

    # ---- 9. 每个真实模块都能归到唯一归属（子模块随包走）----
    mod_owned = {m for mods in skill_map.values() for m in mods}
    declared = mod_owned | set(library) | set(infra) | set(unclaimed)
    actual = set()
    for p in SRC.rglob("*.py"):
        parts = list(p.relative_to(SRC).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]          # publish/__init__.py 就是 publish 本身
        if parts:
            actual.add(".".join(parts))
    orphans, ambiguous = [], []
    for m in sorted(actual):
        cands = [d for d in declared if m == d or m.startswith(d + ".")]
        if not cands:
            orphans.append(m)
        elif len({len(c) for c in cands}) > 1:
            ambiguous.append((m, sorted(cands)))
    rows.append((not orphans,
                 f"{len(actual)} 个模块全部有归属声明"
                 + (f"　**无主 {orphans}**" if orphans else "")))
    rows.append((not ambiguous,
                 "没有模块同时落进两个归属（最长前缀唯一）"
                 + (f"　**撞车 {ambiguous}**" if ambiguous else "")))

    # ---- 10. 声明的必须真实存在（不许幽灵归属）----
    phantom = sorted(d for d in declared if not any(
        a == d or a.startswith(d + ".") for a in actual))
    rows.append((not phantom,
                 f"{len(declared)} 条归属声明都能在磁盘上找到模块"
                 + (f"　**幽灵 {phantom}**" if phantom else "")))

    # ---- 11. unclaimed 必须写明原因，否则等于没声明 ----
    no_reason = sorted(k for k, v in unclaimed.items() if not str(v).strip())
    rows.append((not no_reason,
                 f"{len(unclaimed)} 个 unclaimed 模块都写了原因"
                 + (f"　**缺原因 {no_reason}**" if no_reason else "")))

    # ---- 12. 每个 skill 的 SKILL.md 必须声明它拥有的模块（双向）----
    # 约定：`拥有模块：a, b` 这一行是机检读的那一份，正文其余部分随便写
    # （否则散文里出现的跨用模块名会被误判成归属）。
    mism = []
    for sk, mods in skill_map.items():
        line = _owned_line(sk)
        if line is None:
            mism.append((sk, "没有「拥有模块：」行"))
            continue
        listed = set() if "（无）" in line else {
            x.strip() for x in line.split("：", 1)[1].split(",") if x.strip()}
        listed = {x.strip("` ") for x in listed}
        # 畸形行必须当场报错，而不是和清单对出困惑的 diff
        bad = sorted(x for x in listed
                     if x != "（无）" and not re.fullmatch(r"[a-z_][a-z0-9_]*", x))
        if bad:
            mism.append((sk, f"「拥有模块」行格式非法 {bad}"))
            continue
        if listed != set(mods):
            mism.append((sk, f"文档 {sorted(listed)} ≠ 清单 {sorted(mods)}"))
    rows.append((not mism,
                 "每个 skill 的「拥有模块」行与 ownership.json 一致"
                 + (f"　**不一致 {mism}**" if mism else "")))

    # ---- 13. 代码归属段的散文不许做归属断言（防 prose 说谎）----
    # 机检行「拥有模块：a, b」是**唯一**合法的归属断言处。真实事故：曾同时有
    # 四份 SKILL.md 的散文写着「本 skill 拥有 X」「X 的归属虽记在本 skill」，
    # 而 ownership.json 里 X 全在 library——机检行是对的、散文是反的，检查 12
    # 只读机检行所以全绿。散文要说归属，只能引用 ownership.json。
    # 判据（段内、机检行以外）：
    # - 非否定式的「拥有」或「归属…本 skill」→ 断言，FAIL；
    # - 「Y 的 X」紧邻对（Y ∈ skill 名/library/infrastructure，X ∈ 已声明模块，
    #   间隔 ≤8 个非反引号字符）→ X 必须真的在 Y 名下；远距提及不判，避免误伤。
    assert_re = re.compile(r"(?<!不)拥有|归属[^\n]{0,10}本\s*skill")
    owners: dict[str, set] = {n: set(skill_map.get(n, {})) for n in names}
    owners["library"] = set(library)
    owners["infrastructure"] = set(infra)
    bad: list[str] = []
    for sk in sorted(names):
        body = (SKILLS / sk / "SKILL.md").read_text("utf-8")
        if "## 代码归属" not in body:
            continue                      # 缺段由检查 2/12 报，不重复
        seg = body.split("## 代码归属", 1)[1].split("\n## ", 1)[0]
        for ln in seg.splitlines():
            s = ln.strip()
            if not s or s.startswith("拥有模块："):
                continue
            plain = s.replace("*", "")
            if assert_re.search(plain):
                bad.append(f"{sk}: 散文断言归属（要说归属只能引用 ownership.json）：{s[:40]}")
                continue
            for other, owned in owners.items():
                if other == sk:
                    continue
                for m in declared:
                    if m in owned:
                        continue
                    if re.search(re.escape(other) + r"`?[^\n`]{0,8}`" + re.escape(m) + r"`",
                                 plain):
                        bad.append(f"{sk}: 散文把 {m} 记在 {other} 名下：{s[:40]}")
    rows.append((not bad,
                 "代码归属段散文不做虚假归属断言"
                 + (f"　**{bad}**" if bad else "")))
    return rows


def _owned_line(skill: str) -> str | None:
    """取 SKILL.md「## 代码归属」段里的 `拥有模块：…` 那一行。"""
    p = SKILLS / skill / "SKILL.md"
    if not p.exists():
        return None
    body = p.read_text("utf-8")
    if "## 代码归属" not in body:
        return None
    seg = body.split("## 代码归属", 1)[1].split("\n## ", 1)[0]
    for ln in seg.splitlines():
        if ln.strip().startswith("拥有模块："):
            return ln.strip()
    return None


def main() -> int:
    rows = check()
    print("=" * 72)
    print("skills/ 去歧义门禁：前置契约 · 边界 · 转交 · 事实源")
    print("=" * 72)
    ok = True
    for good, why in rows:
        print(f"  [{'PASS' if good else 'FAIL'}] {why}")
        ok = ok and good
    npass = sum(1 for g, _ in rows if g)
    if ok:
        print(f"\nOK：skills 边界 {npass}/{len(rows)} 项")
        return 0
    print(f"\nFAIL：skills 边界 {npass}/{len(rows)} 项")
    return 1


if __name__ == "__main__":
    sys.exit(main())