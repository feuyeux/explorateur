# 双语字幕卡（解说语 + 中文）

> 本文件是 `skills/match-recap-video` 的**双语字幕卡**契约：卡长什么样、怎么排、怎么判、
> 踩过哪些坑。配套脚本 `scripts/render_cards.py`，能力夹具
> `assets/fixtures/i18n/bilingual-cards.json`。

## 为什么要双语卡

一条成片的**旁白是什么语言，字幕就必须是那个语言**。

原来的三层卡（`title` / `say` / `stat`）写死中文。解说换成外文之后就出现两头别扭：观众听得懂英文，眼睛看的却是中文字幕——字幕对不上声音，等于没有字幕。

所以：**解说语是主层**（`title` / `say` / `stat` 全部用解说语），**中文是辅助层**（一层小字的 `zh`）。这与 `multilingual-video-poetry` 的双语卡一致：目标语大、中文小。

**不做平台字幕文件（`.txt`）**——那是平台自己的字幕轨，与卡片是两回事。

## 卡长什么样

### 双语版式（解说语 ≠ 中文）

```
    解说语 title（白，大）      8' · Raphinha scores
    解说语 say  （金，大）      Eighth minute: Ferran crosses from the right…
    中文   say  （淡，小）      第八分钟，费尔明右路传中，拉菲尼亚后点包抄破门，一比零。
    数据条 stat（淡金，小）     0-0 · before the 8th minute
```

### 单语版式（解说语 == 中文）

```
    title（白，大）   第8分钟 · 拉菲尼亚破门
    say  （金，大）   第八分钟，费尔明右路传中，拉菲尼亚后点包抄破门，一比零。
    stat（淡金，小）  0-0 · 第8分钟前
```

**解说语 == 中文时不出中文层**——同一句话印两遍是噪音。那时的版式与原来的三层卡 **逐坐标一致**（`LAYOUTS['mono']`：title 578 / say 682 / stat 912），已有成片不受影响。

## 版式是数据，不是代码

`render_cards.py` 的 `LAYOUTS` 里每一层声明一个盒子（`top` / `h` / `size` / `color` / `weight`）：

| 版式 | 层 | top | h（允许高度） | 字号 |
|---|---|---|---|---|
| `mono` | title | 578 | 70 | 48 |
| `mono` | say | 682 | 150 | 46 |
| `mono` | stat | 912 | 46 | 28 |
| `bilingual` | title | 470 | 64 | 44 |
| `bilingual` | say | 542 | 186 | 42 |
| `bilingual` | zh | 740 | 92 | 26 |
| `bilingual` | stat | 912 | 46 | 28 |

**`h` 只参与判据，不进渲染 HTML**（渲染只读 `top` / `size` / `color` / `weight` / 字体 / 方向）。所以调 `h` 改的是判据口径，画面不变。

### `h` 的定法：按实测反推，不是拍脑袋估

`h` = 该层允许占的最大高度。**定法是「单行实测高 + 2px 亚像素余量」**：

- `bilingual` title（44px 字号）：单行实测 **62px** ⇒ 声明 64
- `mono` title（48px 字号）：单行实测 **68px** ⇒ 声明 70

第一次跑 14 语种时按估算写了 60 / 66 ⇒ **每个语种都报「实测层高超出声明盒」**，而卡片画面其实一点问题没有。这是「判据比被改进对象更严」——本仓库明令禁止，所以改的是**声明盒**，不是画面。

## 排版判据：实测层盒，不是字符数估算

渲染后用浏览器量出的**实测层盒**（`getBoundingClientRect`）去对声明盒。三条：

1. **实测层高不许超出声明盒**（文字撑出盒子 = 越界）；
2. **实测底不许压到下一层**；
3. **声明盒本身不许重叠、不许出画布**。

**为什么必须实测**：外文比中文长 1.5–2 倍，希伯来 / 阿拉伯还多一层行距。实测（14 语种，同一窗口 w02）：

| 语种 | title | say | zh | stat |
|---|---|---|---|---|
| en-US / es-ES / it-IT / ja-JP / ko-KR / ar-SA / he-IL / hi-IN / zh-HK | 62 | 60 | 37 | 40 |
| de-DE / el-GR / fr-FR / ru-RU | 62 | **119** | 37 | 40 |
| zh-CN（mono） | 68 | 65 | — | 40 |

德语 / 希腊语 / 法语 / 俄语的 `say` 折成两行（119px）——用字符数估算绝对看不出来。

## 字体栈与书写方向：唯一事实源是 `languages/<locale>/manifest.json`

- `fontCss` / `displayFontCss`：字体栈（系统字体 ⇒ 离线秒加载，实测几何拿得到真字体度量，不是 fallback 的）
- `dir`：`ar-SA` / `he-IL` 是 `rtl`

**不另抄一份**。注册表 14 语种：ar-SA / de-DE / el-GR / en-US / es-ES / fr-FR / he-IL /hi-IN / it-IT / ja-JP / ko-KR / ru-RU / zh-CN / zh-HK。

中文层恒用 `zh-CN` 的字体栈且 `direction: ltr`——中文辅助层永远是 LTR，不管解说语是不是 RTL。

## 怎么用

```bash
# 单语种
python3 scripts/render_cards.py \
    --windows windows.json \
    --i18n i18n.json --lang en-US --out cards

# 注册表全覆盖（表里全部语种各出一份）
python3 scripts/render_cards.py \
    --i18n assets/fixtures/i18n/bilingual-cards.json --lang all --out build/cards

# 离线回归（不碰浏览器、不渲图）
python3 scripts/render_cards.py --selftest
```

### 输入契约

两种形态都认：

1. `{"windows": [...], "i18n": {locale: {key: {...}}}}`——窗口表与多语种表在同一个文件里；
2. `{locale: {key: {...}}}`——纯语种表，窗口表用 `--windows` 另给。

窗口表（中文）每条要有 `key` / `title` / `say` / `stat`；`say` 是**中文辅助层的出处**。解说语窗口表按 `key` 对齐，**缺窗口直接报缺**（退出码 2）——不许拿别的语言的文案顶替。

### 退出码

- `0`：过了
- `1`：判据失败（层越界 / 层重叠 / 语种不齐）
- `2`：输入契约不满足（缺字段 / 缺窗口 / 文件不在盘）

## 渲染走 CLI，不另写渲染器

`render_cards.py` 只做**编排 + 判据**，渲染交给 TS 运行时：

```bash
pnpm exec feuille textlayer shoot --html card.html --out card.png --width 1920 --height 1080
```

`textlayer shoot` 一次运行同时出**双 matte**（白底 + 黑底）与测量结果（`<out>.png.measure.json` 里是各层的实测盒）——**测量不额外花一次浏览器启动**。

⚠️ `--dump-dom` 必须插在 URL **之前**（放后面会被当成第二个地址）。

## 坑表

| 坑 | 症状 | 根因 | 修法 |
|---|---|---|---|
| 声明盒拍脑袋估 | 14 语种全报「超出声明盒」，画面却没问题 | `h` 没按实测反推 | `h` = 单行实测 + 2px 余量 |
| 只看字幕层高度 | 忘了 `zh` 层也占位 | 四层各要判 | 判据遍历**所有**层 |
| 用字符数估外文长度 | 德/法/俄的 `say` 折两行没被发现 | 外文长 1.5–2 倍 | 一律用实测层盒 |
| RTL 层方向写死 ltr | 阿拉伯语 / 希伯来语整段错位 | 方向没从 manifest 读 | `dir` 取自 `languages/<locale>/manifest.json` |
| 中文层也跟着 RTL | 中文辅助层左右反了 | 中文层方向没固定 | 中文层恒 `direction: ltr` |
| 同一句话印两遍 | 中解说时的卡上出现两层一样的字 | 没判「解说语 == 中文」 | `pick_layout()` → `mono` 版式无 `zh` 层 |

## 与既有机制的关系

- **卡片渲染**走 `packages/core/src/textlayer.ts`（library 层），本 skill 不另写渲染器；
- **三层卡装配**沿用 `multilingual-video-poetry`（透明 PNG 逐张 overlay 烧录）；
- **解说语文案**由项目自己的窗口表给，夹具里的文案是**夹具不是事实源**。

## 已知缺口

- 本轮只验到**一个窗口**（w02）在 14 语种下的排版；长窗口（`say` 折三行以上）没验过，判据会报越界——那是要压词的信号，不是缺陷。
- **不做平台字幕文件（`.txt`）**：成片自带双语卡，平台字幕轨另说。
