# -*- coding: utf-8 -*-
"""match_theme.py —— 教学视频垂域主题自动匹配器。

根据用户要生成的视频内容、学科门类、语言及话题，自动推荐最合适的视觉主题及颜色方案：
  1. warm-paper    : 人文国学 / 经典启蒙 / 诗词书法 / 传统文史 (古典宣纸/暖黄墨香)
  2. clean-paper   : 现代语言 / 通识精读 / 词汇语法 / 科普学术 (极简素雅/高清晰度)
  3. dark-ink      : 深度研读 / 哲学考据 / 夜读典籍 / 考研理论 (沉浸墨玉/深色护眼)
  4. desert-sand   : 丝路中东 / 历史地理 / 异域文明 / 阿语偏正 (阿拉伯金沙/赭石风貌)
  5. botanical-tea : 自然博物 / 茶道生活 / 节气美学 / 汉方植物 (竹青苍翠/自然淡雅)

用法：
    # 作为模块调用
    from match_theme import match_theme, describe_themes
    theme_info = match_theme("阿拉伯语偏正结构语法精讲", lang="ar")
    print(theme_info["theme"]) # -> "desert-sand"

    # CLI 跑法：
    uv run python match_theme.py "论语八则讲解"
    uv run python match_theme.py "一杯茶的十二种语言" --lang ja
"""
from __future__ import annotations

import argparse
import re
from typing import TypedDict


class ThemeMeta(TypedDict):
    theme: str
    name: str
    domain: str
    rationale: str
    accent_color: str
    paper_color: str


THEMES: dict[str, ThemeMeta] = {
    "warm-paper": {
        "theme": "warm-paper",
        "name": "古卷暖纸 (Warm Paper)",
        "domain": "人文国学 · 古典启蒙 · 诗词书法 · 传统文史",
        "rationale": "微温的古宣纸底衬，温润如玉，适合古诗文、书法、经典释读与母语启蒙。",
        "accent_color": "#b8860b",
        "paper_color": "#f7f2e6",
    },
    "clean-paper": {
        "theme": "clean-paper",
        "name": "素雅学林 (Clean Paper)",
        "domain": "现代外语 · 实用语法 · 考试通关 · 科普通识",
        "rationale": "极简书本白与学术蓝点缀，对比度极高，适合高信息密度的句型拆解与例句精读。",
        "accent_color": "#0969da",
        "paper_color": "#fbfbf9",
    },
    "dark-ink": {
        "theme": "dark-ink",
        "name": "玄墨夜读 (Dark Ink)",
        "domain": "深度思辨 · 哲学法理 · 考据理论 · 深宵静听",
        "rationale": "墨玉暗底与流光金字，极佳暗部沉浸感，减少视疲劳，适合严肃晦涩与理论深度课件。",
        "accent_color": "#d4af37",
        "paper_color": "#1c1b18",
    },
    "desert-sand": {
        "theme": "desert-sand",
        "name": "丝路金沙 (Desert Sand)",
        "domain": "闪含语系 · 丝路文明 · 中东阿拉伯 · 历史地理",
        "rationale": "戈壁细沙淡黄配琥珀金棕与波斯蓝，天然契合阿拉伯语、希伯来语及丝路沿线语言文化。",
        "accent_color": "#a67012",
        "paper_color": "#faf5eb",
    },
    "botanical-tea": {
        "theme": "botanical-tea",
        "name": "青竹茗香 (Botanical Tea)",
        "domain": "茶道雅趣 · 节气博物 · 东方美学 · 自然生活",
        "rationale": "嫩竹微青、松烟墨字与龙井绿点缀，传递自然清爽与草木生机，契合茶文化与生态博物。",
        "accent_color": "#367850",
        "paper_color": "#f4f7f2",
    },
}

# 关键字规则画像
KEYWORDS_RULES: list[tuple[str, list[str]]] = [
    # 1. 丝路金沙 (desert-sand)
    ("desert-sand", [
        "阿拉伯", "阿语", "偏正", "idafa", "arabic", "ar-", "沙特", "中东", "沙漠", "金沙",
        "希伯来", "波斯", "丝绸之路", "埃及", "伊斯兰", "古兰", "骆驼", "绿洲", "戈壁",
        "semitic", "hebrew", "quran", "cairo", "bazaar"
    ]),
    # 2. 青竹茗香 (botanical-tea)
    ("botanical-tea", [
        "茶", "一杯茶", "茶道", "茶叶", "茗", "草木", "植物", "博物", "节气", "春茶", "自然",
        "竹", "花鸟", "园林", "立春", "清明", "采茶", "绿茶", "龙井", "普洱", "生态",
        "tea", "botanical", "spring", "herb", "garden", "nature"
    ]),
    # 3. 玄墨夜读 (dark-ink)
    ("dark-ink", [
        "哲学", "思辨", "考据", "理论", "玄学", "夜读", "深度", "逻辑", "法学", "原典",
        "黑夜", "精研", "康德", "黑格尔", "先秦名家", "辨析", "研讨", "沉浸", "暗色",
        "philosophy", "theory", "logic", "deep", "night", "speculation"
    ]),
    # 4. 人文国学 (warm-paper)
    ("warm-paper", [
        "国学", "古文", "诗词", "唐诗", "宋词", "文言文", "书法", "论语", "诗经", "一本书",
        "孟子", "庄子", "汉字", "幼学", "启蒙", "成语", "千字文", "三字经", "古琴", "说书",
        "poem", "chinese classical", "calligraphy", "storyteller"
    ]),
    # 5. 现代学术与外语精读 (clean-paper)
    ("clean-paper", [
        "英语", "日语", "韩语", "德语", "法语", "西语", "俄语", "语法", "词汇", "考研", "托福",
        "雅思", "gre", "四六级", "精读", "听力", "对话", "通识", "科普", "论文", "教学",
        "english", "grammar", "vocabulary", "lesson", "academic", "exam"
    ]),
]


def match_theme(topic: str = "", *, lang: str = "", explicit: str = "") -> ThemeMeta:
    """根据话题文本与语种标签自动计算最匹配的主题。"""
    if explicit and explicit in THEMES:
        return THEMES[explicit]

    query = (topic + " " + lang).lower()

    # 1. 语言强约束规则
    if lang.lower().startswith(("ar", "he", "fa", "ur")):
        return THEMES["desert-sand"]

    # 2. 关键词评分与规则匹配
    best_theme = "warm-paper"  # 默认古籍暖纸，作为中文古典基线
    max_score = 0

    for theme_key, kws in KEYWORDS_RULES:
        score = sum(1 for kw in kws if kw in query)
        if score > max_score:
            max_score = score
            best_theme = theme_key

    # 3. 若无任何命中的外语类话题，优先退化至 clean-paper
    if max_score == 0:
        if lang and not lang.startswith("zh"):
            best_theme = "clean-paper"
        elif any(c in query for c in ("课", "讲", "课件", "学", "grammar", "study")):
            best_theme = "clean-paper"

    return THEMES[best_theme]


def describe_themes() -> list[ThemeMeta]:
    """返回全部 5 套教学主题清单。"""
    return list(THEMES.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="教学视频多主题自动匹配器")
    parser.add_argument("topic", nargs="?", default="", help="视频话题或课程标题")
    parser.add_argument("--lang", default="", help="主要语种代码 (如 ar, zh, ja, en)")
    parser.add_argument("--list", action="store_true", help="列出全部支持的主题")
    args = parser.parse_args()

    if args.list or not args.topic:
        print("【5 套教学视频垂域专属主题】")
        for t in describe_themes():
            print(f"- {t['theme']:<15} {t['name']:<25} 适用: {t['domain']}")
            print(f"  设计立意: {t['rationale']}")
            print(f"  标志色: 纸色 {t['paper_color']} · 焦点色 {t['accent_color']}\n")
    else:
        res = match_theme(args.topic, lang=args.lang)
        print(f"输入话题: '{args.topic}' (语言: '{args.lang}')")
        print(f"-> 匹配主题: [{res['theme']}] {res['name']}")
        print(f"   适用垂域: {res['domain']}")
        print(f"   立意依据: {res['rationale']}")
