#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lesson.py — 新课接入的两个动作：`new`（开坑）与 `doctor`（体检）

搬运自 explorateur/src/usine/lesson.py（607 行；源文件全部内容就是这两个动作）。
适配点（坑注/准则注与函数体逐字节照搬）：
- **目录全部参数化**：lessons 经 `--lessons`（缺省 = feuille 仓库根 lessons/，
  data.py 锚定）；personas / languages 经 `--personas` / `--languages`
  （缺省 = feuille 能力数据目录）。项目根（build/ 产物、publish/ 台账、
  build/baseline/ 基线所在层）= lessons 目录上推一层——与 explorateur 仓库布局同构；
- 注册表改取 feuille 渲染线：`intro_cards.SCENES` → `scenes.SCENES`、
  `scene_video.DEVICE_STYLES` → `devices.DEVICE_STYLES`、`MOOD_FACE` → `rig.MOOD_FACE`
  （经 `scene_draft._registries()` 现取，不抄名单——名单必腐烂）；
- 发布层判据接 feuille 事实源：平台文案名按 `manifest.PLATFORMS` 的 `{plat}-copy.md`
  契约派生（copy 显式 None 的平台不走逐支模板）；台账路径 = `metrics.ledger_path(root)`；
  逐帧基线 = `framehash.baseline_path(root)`（baseline_hits 搬运适配 + 按平台分桶）；
- 「下一步」命令全部改写为 feuille 命名空间（cli.py 路由表）。其中场景渲染管线
  （scene tts/assets/render）、教学文档（lesson build/dump）、发布台账构建、qa_scene
  **未随本次蒸馏搬运**——这些命令是渲染线落位后的预留入口；检查本体（产物存在性 /
  台账 / 基线覆盖）不依赖入口存在，现在就工作；
- `--all` 在 lessons 目录尚不存在时回落到 find_scene_ids（源仓库 lessons/ 恒存在，
  feuille 缺省没有——不守会 FileNotFoundError）；
- cli.py 契约：`main_new` / `main_doctor` 包装（统一入口以 `fn(argv)` 调用）。

使用契约：`cmd_new(argv)` 开坑（拒覆盖已有 brief；空跑草稿生成证明这份 brief 渲得出来）；
`cmd_doctor(argv)` 七层体检（①创意…⑦验收），每条未完成带下一条命令，返回码
0 = 无 FAIL（--strict 时可选拘认 TODO 计失败）/ 1 = 有 FAIL / 2 = 用法错。

**为什么要有这两个动作**：colors / numbers 两门课跑完之后，接入流程实际是 6 步——

    brief.json → scene.md 结构草稿 → 填台词 → parse → validate → 渲染

这 6 步本身没有错。错在**没有一个地方能回答「这课到哪一步了、下一步敲什么」**：
第三门课来的时候这 6 步要靠记忆重走一遍，而每一步都有静默失败：

| 步骤 | 静默失败的样子 |
| --- | --- |
| brief 里 style/pose 写错 | 草稿生成时才炸，炸在「渲染会炸」这种看不出病因的提示上 |
| 台词没填完 | `scene.md` 里还留着 `TODO`，照样能 parse、照样渲出一支骨架错乱的成片 |
| 改了 `scene.md` 忘了重跑 parse | 成片与剧本脱节，`git diff` 里看不出任何异常 |
| 要开第 3 门课 | 不知道该复制谁、哪些字段必填、哪些是可选、`--rounds` 换算成几行 |

`new` 把**能从注册表现取的一律现取**（合法 style/shape/mood/pose、班底真实选角、
各语种真实引号对、6→2 井位几何默认值），只把真正需要人做主的四件事留成 TODO；
生成后立刻用 `scene_draft.render` 空跑一遍，**在作者投入任何时间之前**证明这份 brief
渲得出来。`doctor` 把 6 步的完成度变成一张可机读的表，**每条未完成都带下一条命令**。

**为什么这两件事必须机器做**：手写第 3 份 brief 的最大成本不是 JSON，是「哪些取值合法」
这种要去 `scenes.SCENES` / `devices.DEVICE_STYLES` / `rig.MOOD_FACE` 里翻的隐性知识。
这些注册表会随渲染线一起长，所以手抄的模板必然腐烂——而腐烂的模板造出的是
「声明合法但渲不出来」的坑，比直接报错更难查（`scene_schema.FORMS` 的注释记着同一个病）。

用法：
    uv run feuille lesson new fruit --title "…" --tokens "apple:#D8453B,pear:#D9A62E"
    uv run feuille lesson new fruit --tokens-file tokens.json --locales zh-CN,en-US,ja-JP
    uv run feuille lesson doctor --scene fruit          # 单课体检（缺哪、下一步敲什么）
    uv run feuille lesson doctor --all                  # 全课体检
    uv run feuille lesson doctor --all --json           # 机读（CI / 看板用）
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .data import LESSONS_DIR


def _lessons(lessons_dir=None):
    """lessons 目录参数 → Path（None / 空 = 缺省：feuille 仓库根 lessons/，data.py 锚定）。

    项目根（build/ 产物与 publish/ 台账所在层）由 lessons 目录上推一层得到：
    内容项目把 --lessons 指进来，产物与台账就在它旁边——与 explorateur 布局同构。
    """
    return Path(lessons_dir) if lessons_dir else LESSONS_DIR

# 两门示范课共用的骨架：开场 1 + 接题 1 + 来回 2×rounds + 收束 1 + 告别 2。
# 这是**从 colors/numbers 提炼出来的结构常量**（rounds=6 时 5+12=17 行 = numbers 的 n=17），
# 换课只换 `rounds`，不必手算 n-K 边界——手算正是坑㉗（`apply_beats` 抛「某行未被节拍覆盖」）的来源。
FIXED_LINES = 1 + 1 + 1 + 2          # open + reply + summary + bye
DEFAULT_STYLE = "tray"
DEFAULT_SHAPE = "round"
DEFAULT_CELL = 112
# 两门课的 `well` 都是同一个浅中性色。**字牌 chip 必须有 well**——井底色不给，
# 深色数字贴在透明底上看不清，而这件事在 numbers 课渲坏过一次才被发现。
DEFAULT_WELL = "#F5F3EE"


# ================================================================ 事实源现取
def _registries():
    """情绪 / 姿态 / 装置 / 背景原语的合法取值——**从渲染线现取，绝不手抄**。

    抄一份 = 迟早腐烂；腐烂的注册表会造出「声明合法但渲不出来」的坑。
    """
    from . import scenes
    from .scene_draft import _registries as _draft_registries
    # 前三项直接复用 `scene_draft._registries()`：那正是 `render()` 自己做集合运算时
    # 依赖的那一份。自己再抄一份看着等价，实际会漂——`render` 里 `codes - reg["poses"]`
    # 要求的是 **set** 而非 list，传 list 会在草稿生成阶段抛
    # 「unsupported operand type(s) for -: 'set' and 'list'」，看不出病因。
    reg = dict(_draft_registries())
    # 背景原语与井形是 scene_draft 不关心的两项。井形取自 devices.draw_device 的分支
    # （circle / poly / rect，其余走 round），不是一个独立枚举——
    # 多声明一个 shape 就会造出「声明合法但画成方块」的偏差。
    reg["scenes"] = set(scenes.SCENES)
    reg["shapes"] = {"round", "circle", "rect", "poly"}
    return reg


def _langs(languages_dir=None):
    from .data import language_manifests
    m = language_manifests(languages_dir)
    if not m:
        raise SystemExit("语种目录为空：先建 languages/<locale>/manifest.json（见 languages/README.md）")
    return m


# ================================================================ new：开坑
def parse_tokens(spec: str | None, token_file: str | None) -> list[dict]:
    """`--tokens` 文本 / `--tokens-file` JSON → `[{key, chip}]`。

    chip 两型与 `devices.chip_color` 的真实契约同源：以 `#` 开头 = 色片（须 #RRGGBB），
    其余非空 = 字牌（走文字层贴图）。这里**当场校验**，因为色片写错要到渲完 14 支才发现。

    逗号是分隔符，所以 chip 自身不能含逗号——真要教带逗号的字，就用 `--tokens-file`。
    """
    if token_file:
        raw = json.loads(Path(token_file).read_text("utf-8"))
        items = [{"key": t["key"], "chip": str(t["chip"])} for t in raw]
    else:
        if not spec:
            raise SystemExit("要教什么词？给 --tokens \"key:chip,key:chip\" 或 --tokens-file")
        items = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise SystemExit(f"--tokens 项缺 chip：{part!r}（应写 key:#RRGGBB 或 key:\"文本\"）")
            k, chip = part.split(":", 1)
            items.append({"key": k.strip(), "chip": chip.strip().strip('"')})
    if not items:
        raise SystemExit("--tokens 是空的")
    seen = set()
    for t in items:
        k = t["key"]
        if not k:
            raise SystemExit(f"--tokens 里有空 key：{t!r}")
        if k in seen:
            raise SystemExit(f"--tokens 里有重复 key：{k}")
        seen.add(k)
        chip = t["chip"]
        if not chip:
            raise SystemExit(f"token {k!r} 的 chip 为空")
        if chip.startswith("#") and len(chip) != 7:
            raise SystemExit(f"token {k!r} 的 chip {chip!r} 像色片但不是 #RRGGBB"
                             "（字牌就写文本，别加 #）")
    return items


def default_spec(rounds: int, reg: dict) -> dict:
    """每节拍的情绪/姿态——**两门示范课的同一套**（`bounce-in` 入场 → `nod` 接题 →
    `point` 提问 / `palm-open` 回答 → `jump-celebrate` 收束 → `wave` 告别）。

    取值全部来自注册表，所以这份默认是**可渲的**：写一个注册表里没有的姿态，
    草稿生成时就会以「不在 POSE_CODES 注册表内（渲染会炸）」当场拒绝。
    """
    need = {"happy", "neutral", "encouraging"}
    if not need <= set(reg["moods"]):
        raise SystemExit(f"MOOD_FACE 缺默认骨架要用的情绪：{sorted(need - set(reg['moods']))}")
    return {
        "open.mood": "happy",
        "open.pose": "bounce-in both-hands",
        "reply.speakers": "B",
        "reply.mood": "neutral",
        "reply.pose": "nod",
        "round.moodAsk": "happy",
        "round.poseAsk": "point",
        "round.moodReply": "neutral",
        "round.poseReply": "palm-open",
        "summary.mood": "happy",
        "summary.pose": "jump-celebrate",
        "bye.speakers": ["B", "A"],
        "bye.mood": ["encouraging", "happy"],
        "bye.pose": ["wave", "wave"],
    }


def scaffold_brief(sid: str, title: str, tokens: list[dict], locales: list[str],
                   rounds: int, style: str, shape: str, cell: int, well: str,
                   duration_budget: str, note_floor: int, ask_balance: str,
                   goal: str, structure: str, reg: dict) -> dict:
    """拼一份**能渲**的 brief：能现取的一律现取，留给人做主的只有 TODO。"""
    if style not in reg["device_styles"]:
        raise SystemExit(f"--style {style!r} 不在 DEVICE_STYLES 注册表内。"
                         f"合法值：{', '.join(sorted(reg['device_styles']))}")
    if shape not in reg["shapes"]:
        raise SystemExit(f"--shape {shape!r} 不合法。合法值：{', '.join(sorted(reg['shapes']))}")
    lines = FIXED_LINES + 2 * rounds
    return {
        "sceneId": sid,
        "title": title,
        "goal": goal or "TODO：一句话说清这课教什么",
        "structure": structure or f"开场提议 → {rounds} 轮一来一往 → 开心再会",
        "description": f"TODO：一句话说明这课与既有课的可对照差异（colors 色片 / numbers 字牌）",
        "form": "dialogue",
        "durationBudget": duration_budget,
        "noteFloor": note_floor,
        "askBalance": ask_balance,
        "locales": locales,
        "lines": lines,
        "tokens": tokens,
        "devices": {lc: {"style": style, "shape": shape, "cellW": cell,
                         "cellH": cell, "well": well} for lc in locales},
        "roles": {"A": {"energy": "lively", "note": "先问方 · 节奏引擎"},
                  "B": {"energy": "steady", "note": "沉稳接题方 · 短问稳答"}},
        "skeleton": [
            {"beat": "open", "lines": 1},
            {"beat": "reply", "lines": 1},
            {"beat": "round", "lines": "rest", "ask": "even", "askBy": "A"},
            {"beat": "summary", "lines": 1},
            {"beat": "bye", "lines": 2},
        ],
        "spec": default_spec(rounds, reg),
        # 逐行给：只有 A（最后一行动作者）蹦跳出画，B 原地挥手。写成字符串
        # `{"bye": "exit"}` 会把 exit 铺满整节，于是两人一起跑出画——
        # numbers 课的定稿是 A 出画 / B 祝福，所以这里对齐定稿而不是对齐旧 brief。
        "noteOn": {"bye": ["", "exit"]},
        "stage": {lc: "TODO：这门课的舞台与道具（按语种自洽，不从中文直译）" for lc in locales},
    }


def cmd_new(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="feuille lesson new",
        description="新课开坑：生成 lessons/<id>/brief.json（能现取的一律现取）")
    ap.add_argument("id", help="课程 id，如 fruit（= lessons/fruit/）")
    ap.add_argument("--title", required=True, help="课程标题（会进 scene.md 标题与文件名之外的地方）")
    ap.add_argument("--tokens", default="", help='教学 token：key:#RRGGBB 或 key:"字牌"（逗号分隔）')
    ap.add_argument("--tokens-file", default=None, help="token JSON 数组 [{key,chip}]（chip 含逗号时用）")
    ap.add_argument("--locales", default="zh-CN,en-US",
                    help="语种逗号列表（缺省 zh-CN,en-US：先把一课跑通再加语种）")
    ap.add_argument("--rounds", type=int, default=3, help="一来一往轮数（骨架行数 = 5+2×rounds）")
    ap.add_argument("--style", default=DEFAULT_STYLE, help="装置 style（默认 tray）")
    ap.add_argument("--shape", default=DEFAULT_SHAPE, help="井形 round|circle|rect|poly")
    ap.add_argument("--cell", type=int, default=DEFAULT_CELL, help="井宽=井高（像素）")
    ap.add_argument("--well", default=DEFAULT_WELL, help="空井底色（字牌 chip 必须给）")
    ap.add_argument("--scenes", default="", help="背景原语，逗号分隔（留空 = TODO，由作者按舞台定）")
    ap.add_argument("--duration-budget", default="20-55", help="时长预算，如 20-55")
    ap.add_argument("--note-floor", type=int, default=0, help="每语种注记行数下限（colors/numbers 都是 3）")
    ap.add_argument("--ask-balance", default="any", choices=["any", "symmetric"],
                    help="问句在 A/B 间的分布要求（缺省 any = 不要求）")
    ap.add_argument("--lessons", default=None,
                    help="lessons 目录（缺省 = feuille 仓库根 lessons/；内容项目指自己的目录）")
    ap.add_argument("--languages", default=None,
                    help="languages 目录（缺省 = feuille/languages 语种注册表）")
    ap.add_argument("--personas", default=None,
                    help="personas 目录（缺省 = feuille/personas 班底）")
    ap.add_argument("--force", action="store_true", help="允许覆盖已有 brief.json")
    args = ap.parse_args(argv)

    sid = args.id.strip()
    if not sid or "/" in sid or sid.startswith("."):
        raise SystemExit(f"课程 id 不合法：{sid!r}（纯目录名，不要路径分隔符或前导点）")
    out_dir = _lessons(args.lessons) / sid
    brief_path = out_dir / "brief.json"
    if brief_path.exists() and not args.force:
        raise SystemExit(f"{brief_path} 已存在。加 --force 覆盖。")

    reg = _registries()
    langs = _langs(args.languages)
    locales = [c.strip() for c in args.locales.split(",") if c.strip()]
    unknown = [lc for lc in locales if lc not in langs]
    if unknown:
        raise SystemExit(f"没有语种目录：{unknown}（先建 languages/<loc>/manifest.json）")
    if args.rounds < 1:
        raise SystemExit(f"--rounds 至少 1（实得 {args.rounds}）")
    bad_scenes = [s for s in (c.strip() for c in args.scenes.split(",")) if s and s not in reg["scenes"]]
    if bad_scenes:
        raise SystemExit(f"--scenes 里有不存在的背景原语：{bad_scenes}\n"
                         f"合法值见 `uv run python -c \"from feuille import scenes;"
                         f"print(sorted(scenes.SCENES))\"`")

    brief = scaffold_brief(
        sid=sid, title=args.title, tokens=parse_tokens(args.tokens, args.tokens_file),
        locales=locales, rounds=args.rounds, style=args.style, shape=args.shape,
        cell=args.cell, well=args.well, duration_budget=args.duration_budget,
        note_floor=args.note_floor, ask_balance=args.ask_balance, goal="",
        structure="", reg=reg)
    if args.scenes:
        for lc in locales:
            brief["devices"][lc]["scenes"] = [c.strip() for c in args.scenes.split(",") if c.strip()]

    # 选角当场验：班底里该语种必须恰好有 A/B 各一人。错在这里是**最好的时机**——
    # 等到写完 14 份剧本才发现某个语种没有 A 角，白写。
    from .data import cards_doc, personas
    from .scene_draft import cast_for
    pers, cards = personas(args.personas), cards_doc(args.personas)
    for lc in locales:
        cast_for(lc, pers, cards)

    # 空跑一遍草稿生成：**证明这份 brief 渲得出来**，在作者投入任何时间之前。
    from .scene_draft import gaps, render
    md = render(brief, pers, cards, langs, reg)
    g = gaps(md)

    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", "utf-8")

    n_lines = brief["lines"]
    # `relative_to(项目根)` 在 lessons 目录被指向仓库外时会抛 ValueError，
    # 而这里只是给人看的一行字——**显示代码不该有能力让命令失败**。
    # （explorateur verify_new_lesson.py 正是把 LESSONS_DIR 指到临时目录，实测走到过
    # 这条；feuille 的 --lessons 同样把它变成常态，所以照搬这条守则。）
    def _shown(p: Path) -> str:
        try:
            return str(p.relative_to(_lessons(args.lessons).parent))
        except ValueError:
            return str(p)
    print(f"已写 {_shown(brief_path)}　（{len(brief['tokens'])} 个 token × "
          f"{len(locales)} 语种 = {n_lines} 行台词）")
    print(f"选角已验：{ '、'.join(f'{lc} {cast_for(lc, pers, cards)['A']}×{cast_for(lc, pers, cards)['B']}' for lc in locales) }")
    print(f"装置已验：style={args.style} shape={args.shape} well={args.well}（井位取自注册表，非手抄）")
    print("空跑草稿通过——这份 brief 渲得出来。欠账：" + "　".join(f"{k}={v}" for k, v in g.items()))
    print()
    print("接下来（②生成结构草稿 → ③填台词 → ④全链路）：")
    print(f"  uv run feuille scene draft --brief lessons/{sid}/brief.json")
    print(f"  uv run python -m feuille.scene_draft --brief lessons/{sid}/brief.json --gaps   # 看还欠多少")
    print(f"  # 填完所有 TODO 后：")
    print(f"  uv run feuille scene parse --scene {sid} && uv run feuille scene validate --scene {sid}")
    print(f"  uv run feuille lesson doctor --scene {sid}      # 体检：还差哪几项")
    print()
    print("需要你做主的四件事（工具替不了）：")
    print(f"  1. 舞台：{len(locales)} 个语种各自的 stage（brief.stage，现在都是 TODO）")
    print("  2. 台词：每语种 %d 行（引号对已按 languages/<loc>/manifest.json 填好）" % n_lines)
    print(f"  3. 词表：§5 每语种 {len(brief['tokens'])} 格（tokenWords，写作序 = §0.1）")
    if not args.scenes:
        print(f"  4. 背景原语：§0.2 scenes（合法值 {len(reg['scenes'])} 个："
              f"{' '.join(sorted(reg['scenes'])[:8])} …）")
    if args.note_floor < 3:
        print(f"  ⚑ note-floor={args.note_floor}，而 colors/numbers 两门课都是 3——"
              "低于它就是主动放宽质量线，确认是有意的")
    return 0


# ================================================================ doctor：体检

def baseline_hits(scene_id: str, locales: list[str], root,
                  path=None) -> tuple[int, int, Path]:
    """`(命中数, 应命中数, 基线文件路径)`。

    搬运自 explorateur/src/usine/framehash_baseline.py `baseline_hits`（104–117 行），
    适配两点：基线路径改经 `feuille.framehash.baseline_path`（**按平台分桶**——跨平台
    像素基线本来就不可比，见 framehash.py 头注），root 参数化（= lessons 目录上推一层）。
    **为什么按「应命中数」而不是「总数」**：一门课刚建时成片一支都没有，
    此时 `命中 0 / 应命中 0` 是「还没渲」，不是「漏了基线」——两者不能混报，
    否则新课上线的第一屏就会显示一条红色「基线缺失」，而它其实什么也没做错。
    """
    from . import framehash
    p = Path(path) if path else framehash.baseline_path(root)
    table = framehash.read_baseline(p)
    names = {f"scene-{scene_id}_{lc}.mp4" for lc in locales}
    if not table:
        return 0, 0, p
    return len(names & set(table)), len(names), p


OK, TODO, FAIL, SKIP = "ok", "todo", "fail", "skip"
MARK = {OK: "[ ok ]", TODO: "[todo]", FAIL: "[FAIL]", SKIP: "[skip]"}


def _pad(text: str, width: int = 18) -> str:
    """按**显示宽度**补齐（CJK 记 2 格），不是按字符数。

    `f"{'成片 mp4':<18}"` 对 6 个字符补 12 格、对 4 个汉字只补 14 格——
    两行在终端里就错开，表格看着像坏了。仓库里其它地方也在意这类对齐。
    """
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - w)


@dataclass
class Check:
    tier: str
    name: str
    state: str
    detail: str = ""
    nxt: str = ""


@dataclass
class Report:
    scene: str
    checks: list = field(default_factory=list)

    @property
    def failed(self):
        return [c for c in self.checks if c.state == FAIL]

    @property
    def pending(self):
        return [c for c in self.checks if c.state == TODO]


def _tier_report(sid: str, lessons_dir=None, personas_dir=None) -> Report:
    """一节课的完成度。**每一层都以「下一条命令」收尾**——体检的价值不是骂人，是接手。

    分层依据是 colors / numbers 两门课**实际产出过的文件**（而不是想象中的步骤）：
    brief.json 只在 numbers 有（colors 早于草稿生成器），analysis/ 与 publish/ 只在
    colors 有（numbers 只跑到成片就停了）——所以「必做」只有到成片那几层，
    文档层与发布层是**可选层**，未做记 todo 而不是 fail。
    """
    # 项目根 = lessons 目录上推一层（build/ 产物、publish/ 台账、build/baseline/ 基线
    # 都在这层；explorateur 里就是 ROOT，参数化后由 --lessons 推导，布局同构）。
    root = _lessons(lessons_dir).parent
    scene_out = root / "build" / "scene"
    rep = Report(sid)
    d = _lessons(lessons_dir) / sid
    md_p, json_p = d / "scene.md", d / "scene.json"
    brief_p = d / "brief.json"

    def add(tier, name, state, detail="", nxt=""):
        rep.checks.append(Check(tier, name, state, detail, nxt))

    # ---- ① 创意 ----
    # brief.json 是**可选输入**，不是必填：colors 课早于草稿生成器，直接手写 scene.md，
    # 至今没补 brief。所以「没 brief」只在连 scene.md 都没有时才是欠账——
    # 对已有剧本的课报「去补 brief」是误导（会诱发一次没必要的重写）。
    if not brief_p.exists() and md_p.exists():
        add("①创意", "brief.json", SKIP, "无 brief（直接维护 scene.md，可选）")
    elif not brief_p.exists():
        add("①创意", "brief.json", TODO, "还没有教学创意",
            f"uv run feuille lesson new {sid} --title \"…\" --tokens \"k:#RRGGBB\"")
    else:
        try:
            brief = json.loads(brief_p.read_text("utf-8"))
        except Exception as e:                              # noqa: BLE001
            brief = None
            add("①创意", "brief.json", FAIL, f"JSON 解析失败：{e}")
        if brief is not None:
            n_tok = len(brief.get("tokens") or [])
            n_loc = len(brief.get("locales") or [])
            add("①创意", "brief.json", OK,
                f"{n_tok} token × {n_loc} 语种 · {brief.get('lines')} 行 · "
                f"style={ {v.get('style') for v in (brief.get('devices') or {}).values()} }")

    # ---- ② 剧本 ----
    if not md_p.exists():
        add("②剧本", "scene.md", TODO, "还没有剧本",
            f"uv run feuille scene draft --brief lessons/{sid}/brief.json")
    else:
        text = md_p.read_text("utf-8")
        from .scene_draft import DRAFT_MARK, gaps
        g = gaps(text)
        debt = g["仍带 TODO 的台词行"] + g["词表/表格里的 TODO 格"] + g["待写舞台的语种"]
        if debt:
            add("②剧本", "scene.md 欠账", TODO,
                "　".join(f"{k}={v}" for k, v in g.items()),
                f"uv run python -m feuille.scene_draft --brief lessons/{sid}/brief.json --gaps")
        else:
            add("②剧本", "scene.md 欠账", OK, "TODO 清零")
        # `draft: true` = 还没定稿。scene_draft 默认拒覆盖带这个标记的文件——
        # 留着它就等于「随时可能被草稿生成器整份抹掉」，定稿就该摘掉。
        if DRAFT_MARK in text[:2000]:
            add("②剧本", "已定稿", TODO, f"frontmatter 仍带 `{DRAFT_MARK}` → scene-draft 会覆盖它",
                "定稿后删掉 frontmatter 里的 draft 标记")
        else:
            add("②剧本", "已定稿", OK, "无 draft 标记，重跑草稿不会覆盖")

    # ---- ③ 数据 ----
    scene = None
    if not md_p.exists():
        add("③数据", "scene.json", TODO, "没有剧本可解析",
            f"uv run feuille scene parse --scene {sid}")
    else:
        from .parse_scene import parse_scene as _parse
        try:
            fresh, _ = _parse(sid, lessons_dir)
            scene = fresh
        except SystemExit as e:
            add("③数据", "scene.json", FAIL, str(e))
        except Exception as e:                              # noqa: BLE001
            add("③数据", "scene.md 不合解析体例", FAIL, f"{type(e).__name__}: {e}")
        if scene is not None:
            if not json_p.exists():
                add("③数据", "scene.json", TODO, "还没落盘",
                    f"uv run feuille scene parse --scene {sid}")
            elif json.loads(json_p.read_text("utf-8")) != scene:
                # 这是最阴的一种漂移：剧本改了、JSON 没重跑，成片与剧本脱节而 git diff 干净。
                add("③数据", "scene.json 新鲜度", FAIL, "scene.md 改了但 scene.json 没重跑（成片会与剧本脱节）",
                    f"uv run feuille scene parse --scene {sid}")
            else:
                add("③数据", "scene.json 新鲜度", OK, "与 scene.md 逐字段一致")

            from .data import cards_doc, personas
            from .scene_schema import validate_scene
            errs = validate_scene(scene, personas(personas_dir), cards_doc(personas_dir))
            if errs:
                add("③数据", "schema 前置校验", FAIL, f"{len(errs)} 项：" + errs[0],
                    f"uv run feuille scene validate --scene {sid}")
            else:
                add("③数据", "schema 前置校验", OK,
                    f"{len(scene['locales'])} 语种 × {len(scene['tokenOrder'])} token")

    # ---- ④ 成片 ----
    locs = list(scene["locales"]) if scene and scene.get("locales") else []
    if not locs:
        add("④成片", "成片", TODO, "等 scene.json 出来")
    else:
        miss_tts = [lc for lc in locs if not (scene_out / "audio" / f"scene-{sid}_{lc}.timeline.json").exists()]
        miss_txt = [lc for lc in locs if not (scene_out / "text").exists()
                    or not (scene_out / "text" / f"pill_scene-{sid}_{lc}.png").exists()]
        miss_mp4 = [lc for lc in locs if not (scene_out / f"scene-{sid}_{lc}.mp4").exists()]
        pref = f"scene-{sid}"
        add("④成片", "语音", OK if not miss_tts else TODO,
            "全语种齐" if not miss_tts else f"缺 {len(miss_tts)} 语种：{', '.join(miss_tts[:6])}",
            "" if not miss_tts else f"uv run feuille scene tts --scene {sid}（渲染线预留）")
        add("④成片", "文字层", OK if not miss_txt else TODO,
            "全语种齐" if not miss_txt else f"缺 {len(miss_txt)} 语种：{', '.join(miss_txt[:6])}",
            "" if not miss_txt else f"uv run feuille scene assets --scene {sid}（渲染线预留）")
        add("④成片", "成片 mp4", OK if not miss_mp4 else TODO,
            f"{len(locs) - len(miss_mp4)}/{len(locs)} 支" if not miss_mp4
            else f"缺 {len(miss_mp4)} 支：{', '.join(miss_mp4[:6])}",
            "" if not miss_mp4 else f"uv run feuille scene render --scene {sid}（渲染线预留）")

    # ---- ⑤ 文档（可选层：numbers 就没做，也完全不影响成片）----
    if locs:
        ad = d / "analysis"
        no_src = [lc for lc in locs if not (ad / "_source" / f"{lc}.md").exists()]
        no_ana = [lc for lc in locs if not (ad / f"{lc}.json").exists()]
        html = root / "build" / "lesson" / sid / "index.html"
        add("⑤文档", "解析源文本", OK if not no_src else TODO,
            "全语种齐" if not no_src else f"缺 {len(no_src)} 语种",
            "" if not no_src else f"uv run feuille lesson dump --scene {sid}（教学文档管线未蒸馏，预留）")
        add("⑤文档", "逐句解析", OK if not no_ana else TODO,
            "全语种齐" if not no_ana else f"缺 {len(no_ana)} 语种（人工产出，无法自动生成）",
            "" if not no_ana else f"编辑 lessons/{sid}/analysis/{{locale}}.json")
        add("⑤文档", "教学文档 HTML", OK if html.exists() else TODO,
            str(html.relative_to(root)) if html.exists() else "还没合并",
            "" if html.exists() else f"uv run feuille lesson build --scene {sid}（教学文档管线未蒸馏，预留）")

    # ---- ⑥ 发布（可选层）----
    # 平台文案文件名按 `feuille.manifest` 的 parse_copy 契约（`{plat}-copy.md`）从平台表
    # 派生：**显式**写了 `"copy": None` 的平台（知乎：一课一篇长文）不走逐支模板；
    # 没声明 copy 键的平台 = 逐支模板平台（douyin / xiaohongshu / bilibili）。
    # 台账路径走 `feuille.metrics.ledger_path`（root 参数化）。
    from .manifest import PLATFORMS
    from .metrics import ledger_path
    copies = [f"{plat}-copy.md" for plat, m in PLATFORMS.items()
              if not ("copy" in m and not m["copy"])]
    no_copy = [c for c in copies if not (d / "publish" / c).exists()]
    ledger_n = 0
    ledger = ledger_path(root)
    if ledger.exists():
        ledger_n = sum(1 for e in json.loads(ledger.read_text("utf-8"))["entries"].values()
                       if e.get("lesson") == sid)
    add("⑥发布", "平台文案", OK if not no_copy else TODO,
        f"齐（{', '.join(copies)}）" if not no_copy else f"缺 {', '.join(no_copy)}",
        "" if not no_copy else f"写进 lessons/{sid}/publish/{{plat}}-copy.md")
    add("⑥发布", "发布台账", OK if ledger_n else TODO,
        f"{ledger_n} 条" if ledger_n else "台账里没有这课",
        "" if ledger_n else "uv run feuille publish build（台账构建未蒸馏，预留）")

    # ---- ⑦ 验收 ----
    # qa_scene（场景线逐项探针）未随蒸馏搬运：它逐帧读 mp4，依赖场景渲染管线（⑥）。
    # 状态位照搬（没成片 = todo / 有 mp4 无成片可验 = skip / 有成片 = 该跑没跑），
    # 「下一步」如实说明判据暂由逐帧像素基线承担——**「没验」不许长得像「验过了」**。
    if not locs:
        add("⑦验收", "场景线验收", TODO, "等成片出来",
            "qa_scene 未蒸馏（场景渲染线落位后随迁）；验收暂以下方像素基线为准")
    elif not any((scene_out / f"scene-{sid}_{lc}.mp4").exists() for lc in locs):
        add("⑦验收", "场景线验收", SKIP, "没有成片可验（qa_scene 要逐帧读 mp4）",
            f"uv run feuille scene render --scene {sid} 之后才有意义（渲染线预留）")
    else:
        add("⑦验收", "场景线验收", TODO, "跑一次确认没退化",
            "qa_scene 未蒸馏（场景渲染线落位后随迁）；验收暂以下方像素基线为准")
    # 逐帧像素基线是**零像素漂移**这条硬判据的载体。基线是一个
    # `{成片名: hash}` 表（build/baseline/framehash-<平台桶>.txt，见 framehash.baseline_path），
    # 所以这里直接查表，而不是报一句「记得跑」——「跑过了」和「覆盖到这课了」是两件事。
    have, total, base_p = baseline_hits(sid, locs, root)          # noqa: PLC0415
    if not total:
        add("⑦验收", "逐帧像素基线", SKIP, "还没有基线表（成片渲完才有东西可比）",
            "uv run feuille framehash save")
    elif have < total:
        add("⑦验收", "逐帧像素基线", TODO, f"基线覆盖 {have}/{total} 支，缺的这几支漂移了也没人知道",
            "uv run feuille framehash save")
    else:
        add("⑦验收", "逐帧像素基线", OK, f"{have}/{total} 支在基线内（{base_p}）")

    return rep


def print_report(rep: Report) -> None:
    print("=" * 78)
    print(f"课程体检：{rep.scene}")
    print("=" * 78)
    tier = None
    for c in rep.checks:
        if c.tier != tier:
            tier = c.tier
            print(f"\n{tier}")
        print(f"  {MARK[c.state]} {_pad(c.name)} {c.detail}")
        if c.nxt and c.state in (TODO, FAIL):
            print(f"         └─ 下一步：{c.nxt}")
    nf, nt = len(rep.failed), len(rep.pending)
    print()
    print("=" * 78)
    verdict = "就绪" if not nf and not nt else (f"FAIL {nf} 项" if nf else f"还差 {nt} 项")
    print(f"{rep.scene}：{verdict}　（{len(rep.checks)} 项检查）")
    print("=" * 78)


def cmd_doctor(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="feuille lesson doctor",
                                 description="新课就绪度体检：每层给下一条命令")
    ap.add_argument("--scene", default="", help="课程 id（缺省 = 全部）")
    ap.add_argument("--lessons", default=None,
                    help="lessons 目录（缺省 = feuille 仓库根 lessons/；内容项目指自己的目录）")
    ap.add_argument("--personas", default=None,
                    help="personas 目录（缺省 = feuille/personas 班底）")
    ap.add_argument("--all", action="store_true", help="体检全部课")
    ap.add_argument("--json", action="store_true", help="机读输出（CI / 看板）")
    ap.add_argument("--strict", action="store_true",
                    help="把可选层（⑤文档/⑥发布）的未完成也算失败")
    args = ap.parse_args(argv)

    from .parse_scene import find_scene_ids
    # --all 在 lessons 目录尚不存在时回落到 find_scene_ids（源仓库 lessons/ 恒存在，
    # feuille 缺省没有——iterdir 会 FileNotFoundError，这不是「还没有课」该有的死法）。
    ids = [args.scene] if args.scene else (
        sorted(p.name for p in _lessons(args.lessons).iterdir() if p.is_dir())
        if args.all and _lessons(args.lessons).is_dir() else find_scene_ids(args.lessons))
    if not ids:
        print(f"还没有课。`uv run feuille lesson new <id> --title \"…\" --tokens \"k:#RRGGBB\"` 开一门。")
        return 0
    if args.scene and not (_lessons(args.lessons) / args.scene).is_dir():
        print(f"没有 lessons/{args.scene}/。开一门：uv run feuille lesson new {args.scene} ...")
        return 1

    reports = [_tier_report(sid, args.lessons, args.personas) for sid in ids]
    if args.json:
        print(json.dumps([{
            "scene": r.scene,
            "failed": len(r.failed),
            "pending": len(r.pending),
            "checks": [{"tier": c.tier, "name": c.name, "state": c.state,
                        "detail": c.detail, "next": c.nxt} for c in r.checks],
        } for r in reports], ensure_ascii=False, indent=2))
    else:
        for r in reports:
            print_report(r)
            if len(reports) > 1:
                print()

    OPTIONAL = ("⑤文档", "⑥发布")
    hard = [c for r in reports for c in r.failed]
    soft = [c for r in reports for c in r.pending
            if not (args.strict and c.tier in OPTIONAL)]
    if hard:
        return 1
    return 1 if (args.strict and soft) else 0


# ================================================================ CLI
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "new":
        return cmd_new(rest)
    if cmd == "doctor":
        return cmd_doctor(rest)
    print(f"未知命令 {cmd!r}。可用：new / doctor", file=sys.stderr)
    return 2


def main_new(argv=None) -> int:
    """cli.py 路由入口：`uv run feuille lesson new …`（统一入口以 fn(argv) 调用，
    argv 为去掉组名/命令名后的剩余参数）。"""
    return cmd_new(argv)


def main_doctor(argv=None) -> int:
    """cli.py 路由入口：`uv run feuille lesson doctor …`。"""
    return cmd_doctor(argv)


if __name__ == "__main__":
    sys.exit(main())
