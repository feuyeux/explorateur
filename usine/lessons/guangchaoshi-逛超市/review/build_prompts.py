# -*- coding: utf-8 -*-
"""从 scene.md 机械提取台词，生成三语种对抗审查提示词文件。

不手抄台词——审查对象必须逐字来自 scene.md（门禁的真相不能来自被它校验的东西之外
的转写）。手势段（含「 处 `」）移除，⚑ 教学注记保留（注记同样要审）。
"""
from pathlib import Path

LESSON = Path(__file__).resolve().parent.parent
REVIEW = Path(__file__).resolve().parent
SCENE = LESSON / "scene.md"

LANGS = [
    ("ru", "ru-RU", "### 2.1"),
    ("yue", "zh-HK", "### 2.2"),
    ("ja", "ja-JP", "### 2.3"),
]
KEY_OF_LOCALE = {"ru-RU": "ru", "zh-HK": "yue", "ja-JP": "ja"}

REGISTER = {
    "ru": """【语体承诺】全程 ты 体（同龄好友）；对店员才用 вы——台词中不应出现 вы 体形式。
【注音口径】括号内（*…*）是口语近似式拉丁转写，不是学术转写；只审「转写与俄语原文逐词对得上、拼写无讹」，不苛求学术式规范。""",
    "yue": """【语体承诺】全程口语粤文（按口语音书写的通行粤语用字：喺/嘅/唔/咁/冇等），繁体字形。
【注音口径】括号内（*…*）是粤拼 jyutping（数字声调）；逐字核对声母、韵母、声调数字。
【对照口径】中文对照给的是普通话说法（粤语原意的普通话转述），不是逐字直译；审「普通话说法是否准确传达粤语原意」。""",
    "ja": """【语体承诺】全程です・ます体（礼貌体贯穿）；邀请用〜ませんか。
【注音口径】括号内（*…*）是 Hepburn 式罗马字（长音 ā/ī/ū/ē/ō 带 macron）；逐词核对，注意拨音/促音/长音的罗马字表记。""",
}

COMMON = """【任务性质】
对抗审查：你的任务是**找出错误**，不是确认无误。大模型有顺从性——问「对不对」多半会说对；所以这里只要发现，不要表扬，也不要「总体没问题」式的收尾。

【材料背景】
中文短视频教学课「逛超市」的台词定稿。场景：超市购物——找牛奶 → 问价 → 要便宜替代 → 确认刷卡付款 → 塑料袋收尾。角色：A＝提议/提问方，B＝熟悉这家店的接题方，两人是同龄好友。台词行数应为 17 行，若你数出的不是 17 行，请将此异常列为第一条发现。价格均为教学虚构价，价格数字的合理性不在审查范围。手势与舞台指示已在摘录时移除，不用管画面呈现。

【审查维度】逐行检查：
1. 语法（一致关系、动词体、语序、助词等）
2. 拼写、用字、标点
3. 注音/罗马字与原文的逐词一致
4. 语体一致性（本课语体承诺见下）
5. 自然度：母语者在这个场景下会不会真的这么说（书面腔、直译腔都算发现）
6. 中文对照是否忠实传达原句意思（对照组不判文采）
7. ⚑ 教学注记里的语言说法与语法讲解是否正确（注记讲给中文观众，其中引用的外语例形同样要审）

【输出格式】每个发现一条：
行号｜原文片段｜问题（注明维度）｜修改建议｜置信度（高/中/低）
拿不准但可疑的也报，置信度标「低」并写明疑点。
整个语言若一行错都找不到，只写「未发现错误」四个字。
禁止输出确认性内容（「总体正确」「设计不错」等）。

"""


def extract():
    text = SCENE.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    dialogue = {key: [] for key, _, _ in LANGS}
    tokens = {}
    cur = None
    in_tokens = False
    for ln in lines:
        if ln.startswith("## 5."):
            in_tokens = True
            cur = None
            continue
        if ln.startswith("## "):
            in_tokens = False
            cur = None
            continue
        matched = False
        for key, _loc, header in LANGS:
            if ln.startswith(header):
                cur = key
                matched = True
                break
        if matched:
            continue
        if in_tokens:
            stripped = ln.strip()
            for loc, key in KEY_OF_LOCALE.items():
                if stripped.startswith(f"| {loc} |"):
                    tokens[key] = stripped
        if cur and (ln.startswith("- **A**") or ln.startswith("- **B**")):
            parts = [p for p in ln.split("｜") if " 处 `" not in p]
            dialogue[cur].append("｜".join(parts).lstrip("- ").strip())
    return dialogue, tokens


def main():
    REVIEW.mkdir(exist_ok=True)
    dialogue, tokens = extract()
    ok = True
    for key, loc, _header in LANGS:
        rows = dialogue[key]
        if len(rows) != 17:
            ok = False
            print(f"[FAIL] {loc}: 期望 17 行台词，实际 {len(rows)} 行")
            continue
        body = [f"{i + 1}. {row}" for i, row in enumerate(rows)]
        token_line = tokens.get(key, "(§5 词表行缺失)")
        if token_line.startswith("(§5"):
            ok = False
        content = (
            f"# 「逛超市」台词对抗审查·{loc}\n\n"
            + COMMON
            + REGISTER[key]
            + "\n\n【台词】（行号在行首）\n"
            + "\n".join(body)
            + "\n\n【本课 token 词表（§5 摘录，含注音；注音与用形同样要审）】\n"
            + "| locale | where | milk | price | cheaper | card |\n| --- | --- | --- | --- | --- | --- |\n"
            + token_line
            + "\n"
        )
        out = REVIEW / f"prompt-{key}.md"
        out.write_text(content, encoding="utf-8")
        print(f"[OK] {loc}: 17 行台词 -> {out.name} ({len(content)} chars)")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
