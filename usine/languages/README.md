# languages/ — 语种目录


**新增语种 = 新建一个目录。** 这里存的是**语种自身的属性**（文字、旗、书写方向、字体栈），
不是某一门课的剧本属性，也不是某个角色的档案属性。

## 为什么要有这个目录（2026-10-04 P1-4）

加语种过去要同时改三个地方：

| 原来在哪 | 存的是什么 | 漏改的症状 |
|---|---|---|
| `src/usine/intro_cards.py` `FONT_CSS` | 字体栈 | 字体回落系统默认 |
| `src/usine/intro_cards.py` `FLAG` | 国旗 emoji | 语言牌上**没有旗** |
| `personas/personas.json` `langLabel` | 语种文字（「汉语」） | 语言牌上只剩一个 locale 码 |

三处都**不报错**——漏改只会静静渲出一个残缺的语言牌。更糟的是 `langLabel` 每个语种在
28 条人设记录里各存一份（2 人/语种），实际只有 14 个不同值。

现在三样都从本目录派生（`src/usine/data.py`：`fonts_css()` / `flags()` / `lang_label()`），
`intro_cards` 不再抄第二份。

## 体例

每个语种一个目录，里面一个 `manifest.json`：

```json
{
 "locale": "zh-CN",
 "label": "汉语",
 "flag": "🇨🇳",
 "dir": "ltr",
 "fontCss": "'Microsoft YaHei', sans-serif"
}
```

| 字段 | 必填 | 约束 |
|---|---|---|
| `locale` | ✓ | 必须等于目录名 |
| `label` | ✓ | 语言牌上的语种文字，非空 |
| `flag` | ✓ | **必须是 locale 里 ISO 区码的区域指示符对**（`zh-CN` → `CN`） |
| `dir` | ✓ | `ltr` 或 `rtl` |
| `fontCss` | ✓ | CSS `font-family` 栈，**必须以 `sans-serif` 兜底** |
| `displayFontCss` | | 可选的展示字体栈（诗配文/海报这类需要书体感时用）。**不是必填**：没写就用 `fontCss`。`data.py` 按键透传，加键不影响其他项目。约定：**衬线书体在前，按 macOS → Windows → Linux 顺序各给一个衬线命中，末尾整段接回原 `fontCss`**（缺字兜底，行为与从前完全一致；接回段造成的跨段重复字体无害）。展示栈不受「Windows 字体留首位」约束——那是 `fontCss` 的像素基线纪律——但三套系统都必须在落到无衬线基线**前**命中一个衬线。接回段之后**不再追加 `serif`**：通用族 `sans-serif` 必命中，排在它后面的都是死 token |

### 为什么国旗必须等于 ISO 区码

手册坑⑬的原话是「**错旗比字母对更糟**」。Windows 的 Segoe UI Emoji 没有国旗字形，会
回退渲染成 ISO 双字母对（CN/DE…）——那是有意的降级；但如果是把**另一个国家的旗**配上去，
就是错旗，而错旗不会以任何形式暴露。所以门禁判的是「这两个码位真的是那个国家吗」，
不是「`flag` 字段存在」。

`flag` 必须是**成对**的 U+1F1E6–U+1F1FF 区域指示符（每个国家的旗在 Unicode 里是两个码位）。

## 门禁

⚠️ 如实记录：原 `run.ps1 langs` / `scripts/verify_languages.py` 门禁（71 项检查 + 坏数据自测）
在「重构为 humming / reading / usine 三项目工作区」时**没有搬过来**，当前语言目录**没有专属机检**
（`verify_probes.py` 的 17 套件里没有 languages）。新增语种后至少手动核对：
`locale` = 目录名、`flag` 为对应区域指示符对、`fontCss` 以 `sans-serif` 兜底、
`displayFontCss` 末尾整段接回原 `fontCss`。

## 与剧本 §0 `rtlLocales` 的关系

`rtl` 在两处都有，**都要改**：

- 本目录 `dir` —— 书写系统属性，新增语种建目录时就带上；
- 剧本 §0 `rtlLocales` —— §0 声明体例的一部分（场景线从那里读，**没有**改成读目录）。

剧本那一份是场景线的渲染输入，改动它才会影响场景成片；本目录这一份是全局记录。
两者不一致时门禁不会报（它们分属两条线），但会让人困惑——改 RTL 语种时记得两边都改。

## 新增语种清单

1. 建 `languages/<id>/manifest.json`（上表五个字段）
2. `personas/personas.json` 加档案（voiceId 先 `edge_tts.list_voices()` 核验，在册清单见 [../personas/voice.md §3](../personas/voice.md)）
3. `personas/intro-cards.json` 加卡（RTL 语种卡上要 `rtl:true`）
4. 剧本 §0 `rtlLocales` 若是 RTL 语种要补上
5. 按上面的「门禁」逐项手动核对 → `uv run feuille verify` 全量过
