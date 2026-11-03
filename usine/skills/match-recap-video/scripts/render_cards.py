#!/usr/bin/env python3
"""render_cards.py — 赛事集锦的**双语字幕卡**：解说语（主）+ 中文（辅），并用实测层盒判排版。

**为什么字幕要跟解说语言走**：一条成片的旁白是什么语言，字幕就必须是那个语言——
底下一层中文是给中文观众的**辅助**，不是替代。原来的三层卡写死中文，解说换成外文
就与声音对不上了（观众听得懂英文、看的是中文字幕，两头都别扭）。

**双语卡长什么样**（对着 multilingual-video-poetry 的双语卡：目标语大、中文小）：

    解说语 title（白，大）      例：8' · Raphinha scores
    解说语 say  （金，大）      例：Eighth minute, Ferran crosses…
    中文   say  （淡，小）      例：第八分钟，费尔明右路传中…
    数据条 stat（淡金，小）     例：0-0 · before the 8th minute

    解说语 == 中文时**不出中文层**（不许同一句话印两遍）——那时的版式与原来的
    三层卡逐像素一致（LAYOUTS['mono']），已有成片不受影响。

**版式是数据**（LAYOUTS），不是代码里写死的坐标。每层声明一个盒子（top/高/字号），
渲染后用**实测**层盒（浏览器量出来的文本高度）去对：文字撑出盒子 = 越界 = 退出码 1。
不许拿字符数估算糊弄过去——外文比中文长 1.5–2 倍，希伯来/阿拉伯还多一层行距。

**字体栈与书写方向的事实源是 `languages/<locale>/manifest.json`**（不另抄）：
fontCss / displayFontCss / dir（ar-SA、he-IL 是 rtl）。系统字体 ⇒ 离线秒加载，
实测几何拿得到真字体度量（不是 fallback 的）。

用法：
    python3 scripts/render_cards.py --windows windows.json \\
        --i18n i18n.json --lang en-US --out cards
    python3 scripts/render_cards.py --selftest

退出码：0 = 过了；1 = 判据失败（层越界 / 层重叠 / 语种不齐）；2 = 输入契约不满足。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
USINE = SKILL.parents[1]
LANGS = USINE / "languages"

# ---------------------------------------------------------------------------
# 版式（数据，不是代码）。h = 该层允许占的最大高度（实测层高超出 = 越界）。
#
# mono 与现有三层卡逐像素一致：解说语就是中文时，成片不该因为这次改动变形。
#
# ⚠️ **h 是判据用的「允许高度」，不进渲染 HTML**（渲染只读 top / size / color /
# weight / 字体 / 方向）。所以调整 h 只改判据口径，不改画面。
#
# h 的定法：**按单行实测高 + 2px 亚像素余量**——实测 14 语种渲染（2026-11-03）：
#   bilingual title（44px 字号）：单行实测 62px  ⇒ 声明 64
#   mono     title（48px 字号）：单行实测 68px  ⇒ 声明 70
# 之前按估算写 60 / 66 ⇒ 每个语种都报「实测层高超出声明盒」，
# 而卡片画面其实一点问题没有——**判据比被改进对象更严**，是本仓库明令禁止的。
# 换句话说：h 该由实测反推，不是拍脑袋估。
# ---------------------------------------------------------------------------
LAYOUTS: dict[str, dict] = {
    "mono": {
        "canvas": (1920, 1080),
        "layers": [
            {"key": "title", "top": 578, "h": 70, "size": 48, "color": "#FFFFFF", "weight": 700},
            {"key": "say", "top": 682, "h": 150, "size": 46, "color": "#F7C948", "weight": 600},
            {"key": "stat", "top": 912, "h": 46, "size": 28, "color": "#E9C77A", "weight": 500},
        ],
    },
    "bilingual": {
        "canvas": (1920, 1080),
        "layers": [
            {"key": "title", "top": 470, "h": 64, "size": 44, "color": "#FFFFFF", "weight": 700},
            {"key": "say", "top": 542, "h": 186, "size": 42, "color": "#F7C948", "weight": 600},
            {"key": "zh", "top": 740, "h": 92, "size": 26, "color": "#E9C77A", "weight": 400},
            {"key": "stat", "top": 912, "h": 46, "size": 28, "color": "#E9C77A", "weight": 500},
        ],
    },
}

# 颜色（与现有三层卡同源，别另抄一份色值）
GOLD = "#F7C948"
GOLD_DIM = "#E9C77A"
WHITE = "#FFFFFF"

# 侧边距：正文块左右收进，给 16:9 转 4:3 的裁切留余量
SIDE = 132


class ContractError(Exception):
    """输入契约不满足（缺字段 / 文件不在盘 / 参数错）。"""


class VerdictError(Exception):
    """判据失败（层越界 / 层重叠 / 语种不齐）。"""


# ---------------------------------------------------------------------------
# 语言注册表（字体栈 / 书写方向的唯一事实源）
# ---------------------------------------------------------------------------
def lang_manifest(locale: str) -> dict:
    """读 languages/<locale>/manifest.json；缺 fontCss = 该语种没法排版。"""
    if not locale:
        raise ContractError("语种为空")
    d = LANGS / locale
    if not d.is_dir():
        raise ContractError(f"languages/{locale} 不存在——语种不在注册表里")
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise ContractError(f"languages/{locale}/{f.name} 不是合法 JSON：{exc}") from exc
        if isinstance(data, dict) and "fontCss" in data:
            return data
    raise ContractError(f"languages/{locale} 无带 fontCss 的 manifest")


def registry_locales() -> list[str]:
    """注册表里的全部语种（目录名）——能力覆盖面的事实源。"""
    return sorted(p.name for p in LANGS.iterdir() if p.is_dir()) if LANGS.is_dir() else []


def pick_layout(commentary_locale: str, zh_locale: str = "zh-CN") -> str:
    """解说语就是中文 ⇒ mono（不出第二层）；否则 bilingual。"""
    return "mono" if commentary_locale == zh_locale else "bilingual"


# ---------------------------------------------------------------------------
# HTML（底色占位符 __BG__ 由渲染入口替换成白底/黑底各一份 → 双 matte 出精确 alpha）
# ---------------------------------------------------------------------------
def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _layer_html(key: str, spec: dict, text: str, font: str, direction: str) -> str:
    side = SIDE if key in ("say", "zh") else 0
    weight = spec["weight"]
    return (
        f'<div class="lay" data-layer="{key}" style="top:{spec["top"]}px;'
        f"left:{side}px;right:{side}px;font-size:{spec['size']}px;font-weight:{weight};"
        f'color:{spec["color"]};font-family:{font};direction:{direction};">'
        f"{esc(text)}</div>"
    )


def card_html(
    layers_spec: list[dict],
    texts: dict[str, str],
    font: str,
    display_font: str,
    direction: str,
    zh_font: str,
    width: int,
    height: int,
) -> str:
    """一张卡的整页 HTML。测量脚本把每层的实测盒写进 <title>（渲染入口同一次运行取回）。"""
    body: list[str] = []
    for spec in layers_spec:
        key = spec["key"]
        text = texts.get(key, "")
        if not text:
            continue
        if key == "title":
            body.append(_layer_html(key, spec, text, display_font, direction))
        elif key == "zh":
            body.append(_layer_html(key, spec, text, zh_font, "ltr"))
        else:
            body.append(_layer_html(key, spec, text, font, direction))
    # 标题上方的金色分隔条（现有着色卡同款）
    first = layers_spec[0]
    body.insert(
        0,
        f'<div style="position:absolute;left:0;right:0;top:{first["top"] - 22}px;text-align:center;">'
        f'<i style="display:block;width:84px;height:4px;background:{GOLD};margin:0 auto;'
        'border-radius:2px;box-shadow:0 2px 10px rgba(0,0,0,.7);"></i></div>',
    )
    measure = """
<script>
(async () => {
  try { await document.fonts.ready; } catch (e) { /* 字体门失败也照样量 */ }
  const out = {layers:{}};
  for (const el of document.querySelectorAll('[data-layer]')) {
    const r = el.getBoundingClientRect();
    out.layers[el.dataset.layer] = {
      top: Math.round(r.top), bottom: Math.round(r.bottom),
      h: Math.round(r.height), w: Math.round(r.width),
    };
  }
  document.title = JSON.stringify(out);
})();
</script>"""
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>"
        f"html,body{{margin:0;padding:0;width:{width}px;height:{height}px;overflow:hidden;"
        "background:__BG__;-webkit-font-smoothing:antialiased;}"
        ".lay{position:absolute;text-align:center;line-height:1.42;letter-spacing:.02em;"
        "text-shadow:0 2px 4px rgba(0,0,0,.9),0 5px 30px rgba(0,0,0,.78),0 14px 62px rgba(0,0,0,.62);}"
        "</style></head><body>" + "".join(body) + measure + "</body></html>"
    )


# ---------------------------------------------------------------------------
# 判据：实测层盒 vs 声明盒
# ---------------------------------------------------------------------------
def check_layers(specs: list[dict], measured: dict, canvas: tuple[int, int]) -> list[str]:
    """返回问题清单（空 = 过了）。

    三条：① 实测层高不许超出声明盒（文字撑出去 = 越界）；② 实测底不许压到下一层；
    ③ 声明盒本身不许重叠、不许出画布。
    """
    problems: list[str] = []
    w, h = canvas
    ordered = sorted(specs, key=lambda s: s["top"])
    for i, spec in enumerate(ordered):
        key = spec["key"]
        m = measured.get(key)
        if m is None:
            problems.append(f"{key}: 拿不到实测层盒（测量没写进 title）")
            continue
        if m["h"] > spec["h"]:
            problems.append(
                f"{key}: 实测层高 {m['h']}px 超出声明盒 {spec['h']}px（top={spec['top']}）"
            )
        if m["top"] < spec["top"] - 1:
            problems.append(f"{key}: 实测 top {m['top']} 与声明 {spec['top']} 对不上")
        if m["bottom"] > h:
            problems.append(f"{key}: 实测底 {m['bottom']} 超出画布高 {h}")
        if i + 1 < len(ordered):
            nxt = ordered[i + 1]
            if spec["top"] + spec["h"] > nxt["top"]:
                problems.append(
                    f"{key}→{nxt['key']}: 声明盒重叠（{spec['top']}+{spec['h']} > {nxt['top']}）"
                )
            if m["bottom"] > nxt["top"]:
                problems.append(
                    f"{key}→{nxt['key']}: 实测底 {m['bottom']} 压到下一层 {nxt['top']}"
                )
    return problems


# ---------------------------------------------------------------------------
# 渲染（走 CLI：pnpm exec feuille textlayer shoot）
# ---------------------------------------------------------------------------
def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """跑 feuille CLI（pnpm exec）。Windows 上 pnpm 可能是 .cmd/.exe 两种形态。"""
    exe = shutil.which("pnpm") or shutil.which("pnpm.cmd")
    if exe is None:
        raise ContractError("PATH 上找不到 pnpm——卡片渲染要走 `pnpm exec feuille textlayer shoot`")
    cmd = [exe, "exec", "feuille", *args]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *cmd]
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def render_cards(
    windows: list[dict],
    i18n: dict,
    lang: str,
    out_dir: Path,
    width: int = 1920,
    height: int = 1080,
    zh_locale: str = "zh-CN",
) -> dict:
    """渲染全部窗口的卡片，返回报告（层盒实测 + 问题清单）。"""
    manifest = lang_manifest(lang)
    zh_manifest = lang_manifest(zh_locale)
    font = str(manifest["fontCss"])
    display_font = str(manifest.get("displayFontCss") or manifest["fontCss"])
    direction = str(manifest.get("dir") or "ltr")
    zh_font = str(zh_manifest["fontCss"])

    mode = pick_layout(lang, zh_locale)
    spec = LAYOUTS[mode]
    specs = spec["layers"]

    # 先把输入契约查干净（缺窗口 / 缺中文 say），再落盘——别渲一半才报缺。
    for w in windows:
        key = str(w.get("key", ""))
        if not key:
            raise ContractError("窗口表里有缺 key 的条目")
        if key not in i18n:
            raise ContractError(f"解说语窗口表缺窗口 {key}——不许拿别的语言的文案顶替")
        if mode == "bilingual" and not str(w.get("say", "")):
            raise ContractError(f"窗口 {key} 没有中文 say——双语卡的中文层没有出处")

    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "lang": lang,
        "mode": mode,
        "direction": direction,
        "canvas": [width, height],
        "cards": [],
        "problems": [],
    }
    for w in windows:
        key = str(w.get("key", ""))
        if not key:
            raise ContractError("窗口表里有缺 key 的条目")
        if key not in i18n:
            raise ContractError(f"解说语窗口表缺窗口 {key}——不许拿别的语言的文案顶替")
        t = i18n[key]
        texts = {
            "title": str(t.get("title", "")),
            "say": str(t.get("say", "")),
            "stat": str(t.get("stat", "")),
        }
        if mode == "bilingual":
            # 中文层 = 窗口表里的中文 say（= 解说语那段的译文）
            zh_say = str(w.get("say", ""))
            if not zh_say:
                raise ContractError(f"窗口 {key} 没有中文 say——双语卡的中文层没有出处")
            texts["zh"] = zh_say
        else:
            # 解说语就是中文：三层都用中文窗口表
            texts = {
                "title": str(w.get("title", "")),
                "say": str(w.get("say", "")),
                "stat": str(w.get("stat", "")),
            }

        html = card_html(specs, texts, font, display_font, direction, zh_font, width, height)
        tpl = out_dir / f"card.{key}.html"
        png = out_dir / f"card.{key}.png"
        tpl.write_text(html, "utf-8")
        proc = run_cli(
            [
                "textlayer", "shoot",
                "--html", str(tpl),
                "--out", str(png),
                "--width", str(width),
                "--height", str(height),
                "--workdir", str(out_dir),
            ],
            USINE,
        )
        if proc.returncode != 0 or not png.exists():
            raise VerdictError(
                f"卡片渲染失败（{key}）：{(proc.stderr or proc.stdout).strip()[:600]}"
            )
        measure_file = Path(f"{png}.measure.json")
        measured: dict = {}
        if measure_file.exists():
            payload = json.loads(measure_file.read_text("utf-8"))
            measured = payload.get("layers", {}) if isinstance(payload, dict) else {}
        problems = check_layers(specs, measured, (width, height))
        report["cards"].append(
            {
                "key": key,
                "png": str(png),
                "measured": measured,
                "problems": problems,
            }
        )
        report["problems"].extend(f"{key}: {p}" for p in problems)
    return report


# ---------------------------------------------------------------------------
# selftest（纯函数回归：不碰浏览器、不渲图）
# ---------------------------------------------------------------------------
def _fixture() -> tuple[list[dict], dict]:
    wins = [
        {
            "key": "w02",
            "t0": 10.0,
            "t1": 20.0,
            "title": "第8分钟 · 拉菲尼亚破门",
            "say": "第八分钟，费尔明右路传中，拉菲尼亚后点包抄破门，一比零。",
            "stat": "0-0 · 第8分钟前",
        }
    ]
    i18n = {
        "w02": {
            "title": "8' · Raphinha scores",
            "say": "Eighth minute: Ferran crosses from the right, Raphinha finishes at the far post.",
            "stat": "0-0 · before the 8th minute",
        }
    }
    return wins, i18n


def selftest() -> int:
    passed = 0
    failed: list[str] = []

    def case(name: str, fn) -> None:
        nonlocal passed
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except AssertionError as exc:
            failed.append(name)
            print(f"  ❌ {name}：{exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  ❌ {name}：{type(exc).__name__} {exc}")

    def expect_raises(exc_type, fn) -> None:
        try:
            fn()
        except exc_type:
            return
        raise AssertionError(f"本该抛 {exc_type.__name__}")

    # 1. 版式自洽：盒子不重叠、全在画布内
    def t_layout():
        for mode, spec in LAYOUTS.items():
            w, h = spec["canvas"]
            layers = sorted(spec["layers"], key=lambda s: s["top"])
            for s in layers:
                assert s["top"] >= 0, f"{mode}/{s['key']} top 越界"
                assert s["top"] + s["h"] <= h, f"{mode}/{s['key']} 盒子超出画布"
            for a, b in zip(layers, layers[1:]):
                assert a["top"] + a["h"] <= b["top"], f"{mode}: {a['key']}→{b['key']} 盒子重叠"

    case("版式自洽：盒子不重叠、不出画布", t_layout)

    # 2. mono 与现有着色卡一致（解说语=中文 ⇒ 三层，坐标不许漂）
    def t_mono():
        mono = {s["key"]: s for s in LAYOUTS["mono"]["layers"]}
        assert mono["title"]["top"] == 578, "mono title 坐标漂了"
        assert mono["say"]["top"] == 682, "mono say 坐标漂了"
        assert mono["stat"]["top"] == 912, "mono stat 坐标漂了"
        assert "zh" not in mono, "mono 不许有中文层（解说语就是中文）"

    case("mono 版式与现有着色卡逐坐标一致", t_mono)

    # 3. 版式选择：解说语=中文 ⇒ mono；否则 bilingual
    def t_pick():
        assert pick_layout("zh-CN") == "mono"
        assert pick_layout("zh-HK") == "bilingual"
        assert pick_layout("en-US") == "bilingual"
        assert pick_layout("ar-SA") == "bilingual"

    case("版式选择：解说语=中文才走 mono", t_pick)

    # 4. 语言注册表：14 语种都在，字体栈与方向读得到
    def t_registry():
        locales = registry_locales()
        assert len(locales) >= 14, f"注册表只有 {len(locales)} 个语种：{locales}"
        for loc in locales:
            m = lang_manifest(loc)
            assert m.get("fontCss"), f"{loc} 无 fontCss"
            assert m.get("dir") in ("ltr", "rtl"), f"{loc} 的 dir 非法：{m.get('dir')}"
        assert lang_manifest("ar-SA")["dir"] == "rtl", "ar-SA 应当是 rtl"

    case("语言注册表：全部语种都有字体栈与书写方向", t_registry)

    # 5. 反向：未知语种要报缺（不许静默用默认字体）
    def t_unknown():
        expect_raises(ContractError, lambda: lang_manifest("xx-XX"))
        expect_raises(ContractError, lambda: lang_manifest(""))

    case("反向：未知语种显式报缺，不静默换字体", t_unknown)

    # 6. 实测层盒判据：撑出盒子 = 越界（要能抓到）
    def t_overflow():
        specs = LAYOUTS["bilingual"]["layers"]
        good = {s["key"]: {"top": s["top"], "bottom": s["top"] + s["h"] - 1, "h": s["h"] - 1}
                for s in specs}
        assert check_layers(specs, good, (1920, 1080)) == [], "正常层盒不该报问题"
        bad = dict(good)
        say = next(s for s in specs if s["key"] == "say")
        bad["say"] = {"top": say["top"], "bottom": say["top"] + say["h"] + 40, "h": say["h"] + 40}
        problems = check_layers(specs, bad, (1920, 1080))
        assert any("超出声明盒" in p for p in problems), f"层高撑出盒子没被抓：{problems}"

    case("排版判据：实测层高撑出声明盒 ⇒ 报越界", t_overflow)

    # 7. 反向：缺测量 = 判不出（不许当过了）
    def t_missing_measure():
        specs = LAYOUTS["bilingual"]["layers"]
        problems = check_layers(specs, {}, (1920, 1080))
        assert len(problems) == len(specs), f"缺测量应逐层报出，实际 {problems}"

    case("反向：拿不到实测层盒 ⇒ 逐层报「判不出」", t_missing_measure)

    # 8. HTML：双语时中文层在、解说语在；mono 时没有中文层
    def t_html():
        man = lang_manifest("en-US")
        specs = LAYOUTS["bilingual"]["layers"]
        html = card_html(
            specs,
            {"title": "8' · Raphinha scores", "say": "Eighth minute…", "zh": "第八分钟…",
             "stat": "0-0"},
            str(man["fontCss"]), str(man.get("displayFontCss") or man["fontCss"]),
            str(man["dir"]), str(lang_manifest("zh-CN")["fontCss"]), 1920, 1080,
        )
        assert "__BG__" in html, "底色占位符没了（双 matte 会失效）"
        assert 'data-layer="zh"' in html, "双语卡没有中文层"
        assert 'data-layer="say"' in html, "双语卡没有解说语层"
        assert "document.title" in html, "没有测量脚本"
        mono_html = card_html(
            LAYOUTS["mono"]["layers"],
            {"title": "T", "say": "S", "stat": "0-0"},
            "f", "f", "ltr", "f", 1920, 1080,
        )
        assert 'data-layer="zh"' not in mono_html, "mono 卡不该有中文层"

    case("HTML：双语出中文层、mono 不出，底色占位符在", t_html)

    # 9. 反向：解说语窗口表缺窗口 ⇒ 报缺（不许拿别的文案顶）
    def t_missing_window():
        wins, i18n = _fixture()
        i18n.pop("w02")
        expect_raises(
            ContractError,
            lambda: render_cards(wins, i18n, "en-US", Path(os.devnull)),
        )

    case("反向：解说语窗口表缺窗口 ⇒ 报缺不顶替", t_missing_window)

    print(f"\n{'通过' if not failed else '未通过'}：{passed}/{passed + len(failed)}")
    if failed:
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


def load_i18n_file(path: Path) -> tuple[list[dict], dict[str, dict]]:
    """读解说语窗口表。

    两种形态都认：
    1. `{"windows": [...], "i18n": {locale: {key: {...}}}}`（夹具与项目自用的形态，
       窗口表与多语种表在同一个文件里）；
    2. `{locale: {key: {...}}}`（纯语种表，窗口表另给）。
    """
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict):
        raise ContractError("解说语窗口表必须是 JSON 对象")
    if "i18n" in data and isinstance(data["i18n"], dict):
        wins = data.get("windows")
        return (list(wins) if isinstance(wins, list) else []), data["i18n"]
    return [], data


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--selftest":
        return selftest()

    ap = argparse.ArgumentParser(description="双语字幕卡渲染（解说语 + 中文）+ 实测层盒排版判据")
    ap.add_argument("--windows", help="中文窗口表 JSON（title/say/stat）")
    ap.add_argument("--i18n", help="解说语窗口表 JSON：{locale: {key: {title, say, stat}}}")
    ap.add_argument("--lang", help="解说所用语言（languages/ 注册表里的 locale）；all = 表里全部语种")
    ap.add_argument("--out", default="cards", help="卡片输出目录")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    args = ap.parse_args(argv)

    try:
        if not args.i18n or not args.lang:
            raise ContractError("需要 --i18n 与 --lang 两个参数")
        file_wins, i18n_all = load_i18n_file(Path(args.i18n))
        if args.windows:
            windows = json.loads(Path(args.windows).read_text("utf-8"))
            if isinstance(windows, dict):
                windows = windows.get("windows", [])
        else:
            windows = file_wins
        if not windows:
            raise ContractError("没有中文窗口表（--windows，或 i18n 文件里带 windows）")
        if args.lang == "all":
            langs = sorted(i18n_all.keys())
            if not langs:
                raise ContractError("解说语窗口表里一个语种都没有")
        else:
            langs = [args.lang]
        for lang in langs:
            if lang not in i18n_all:
                raise ContractError(f"解说语窗口表里没有 {lang} 这一份")

        reports = []
        problems: list[str] = []
        for lang in langs:
            out_dir = Path(args.out) if len(langs) == 1 else Path(args.out) / lang
            rep = render_cards(
                list(windows), i18n_all[lang], lang, out_dir, args.width, args.height,
            )
            reports.append(rep)
            problems.extend(f"[{lang}] {p}" for p in rep["problems"])
            print(f"  · {lang}: {len(rep['cards'])} 张（版式 {rep['mode']}，方向 {rep['direction']}）")
    except ContractError as exc:
        print(f"❌ 输入契约不满足：{exc}", file=sys.stderr)
        return 2
    except VerdictError as exc:
        print(f"❌ 判据失败：{exc}", file=sys.stderr)
        return 1

    report_file = Path(args.out) / "cards-report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps(reports[0] if len(reports) == 1 else reports, ensure_ascii=False, indent=1) + "\n",
        "utf-8",
    )
    print(f"\n卡片 {sum(len(r['cards']) for r in reports)} 张 → {args.out}")
    print(f"报告 → {report_file}")
    if problems:
        print(f"\n❌ 排版判据未过（{len(problems)} 条）：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✅ 排版判据全过（每层实测高度都在自己的盒子里）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
