# tools/foodnames ——「各国美食名称」系列产线

一条 **12 语种视频系列**的批量产线：每一期是「一道菜/一样吃的在 12 种语言里的名字」，海报 12 格、视频 12 场景卡拉OK、横竖双画幅成片、三版封面、三平台发布词。

**第 01 期（寿司）是手写的**；从第 02 期起全部由本目录的数据 + 模板生成。第 01 期已反写成数据（`data/ep01-sushi.json`）当作**回归基准**：生成器重出的第 01 期必须与手写版同构（叠印门矩形逐位相同、旁白实测电平与时长复算出同样的数）。

## 目录

| 路径 | 作用 |
|---|---|
| `data/epNN-<slug>.json` | 一期的全部内容事实源（12 语种的词形/来源标签/旁白句/转写/人设） |
| `templates/` | 从第 01 期剥出来的 CSS 与自适应 JS（与期数无关的部分） |
| `build_episode.mjs` | 数据 → `poster_src.html` / `video_src.html` / `voices.json` / `fonts.json` |
| `run_episode.mjs` | 一期从数据跑到「可发布」（含全部门禁与发布侧清单） |
| `run_series.mjs` | 批量跑若干期（并发可调；任一期红即非零退出） |
| `make_publish.mjs` | 发布侧产物：`facts.json`（事实表）+ `copy-*.md` + `manifest.json` |
| `audit_copy_numbers.mjs` | 离线预检：发布词读者面的每个数字能否在事实表里找到出处 |
| `check_fused_glyph.mjs` | 像素门：韩语融合音节必须渲成渐变字形，不能是实心色块 |
| `check_sentence_matches.mjs` | **离线门**：画面上的句子必须与数据里的旁白句逐词一致（零浏览器，合并门禁可跑） |
| `check_video_layout.mjs` | **版式门**：词形是不是主角、留白、暗词可读性、高亮是不是品牌色（注音对齐） |
| `check_series_consistency.mjs` | 跨期一致性门（12 格 / 语种序 / 版式结构件 / 画幅与清单） |
| `check_ep01_regression.mjs` | 第 01 期回归基准门（生成器重出 == 已交付手写版） |
| `series_report.mjs` | 只读汇总：12 期实测产物一览 |
| `patch_publish.mjs` | 一次性：修 worker 交回的发布词里的文件名/封面贴士硬伤 |
| `measure_narration.mjs` | 旁白语音窗实测 + 时间线预算（成片前先量旁白再定床位） |
| `extract_templates.mjs` | 一次性：把第 01 期手写源文件剥成模板（改模板时重跑） |

## 两条视频门（2026-10-21 加）

12 期已交付的成片有**五处可见缺陷**，两道门把它们变成可机检的数字：

| 门 | 量什么 | 跑法 | 2026-10-21 实测（旧 12 期） |
|---|---|---|---|
| `check_sentence_matches.mjs` | 画面句子 == 配音念的那句（去空白去标点后逐词比） | `node --import tsx tools/foodnames/check_sentence_matches.mjs --all` | **54/144 个语种-期组合不一致**（37%） |
| `check_video_layout.mjs` | 主角占比 / 空白带 / 暗词不透明度 / 高亮色 / 注音对位 | `node --import tsx tools/foodnames/check_video_layout.mjs --out examples/foodnames-ep01-sushi` | 12 期合计 **954 条不达标** |

**版式门的阈值**（写在 `check_video_layout.mjs` 的 `TH` 里，**量之前定的，不许事后挪**）：主角墨迹高 ≥ 画面高 12% **或**宽 ≥ 画面宽 30%；最大空白水平带 ≤ 画面高 15%；非当前 token 不透明度 ≥ 0.45；注音列与字心水平偏差 ≤ 3px；品牌色 `c9403a` / `2f5d9e` / `b8860b`。

**D1（最重）：画面句子与配音不是同一句。** `build_episode.mjs` 为了给菜名上色，把句子的 **第一个 token** 无条件替换成词形。凡是句首不是那个词的语种——冠词（Le / El / Το）、日语助词「は」、韩语助词「는」——那个 token 被**吃掉**；词本身若在句子里还出现一次，就**重复**一遍：

```
fr-FR  画面 "sushi sushi est un plat japonais"   配音 "Le sushi est un plat japonais"
ja-JP  画面 "茶ちゃ は 中国 から 来た"              配音 "茶は中国から来た"
```

两条后果都致命：① **音画不同步**——卡拉OK 按 token 逐个亮，token 数没变但内容整体错开一词（念「Le」时画面亮的是「sushi」）；② 观众读到的句子语法是坏的。`verify-sync` 门**抓不到**它：那个门只数词数，不比词。

**D2–D5（版式）**：视频里没有「菜名」这个主角（`.stage` 装的是整句，词只是句首的 token，词形墨迹只占画面高 4.5%–13.3%）；竖屏最大空白带 26%–30%；未唱到的 token 不透明度 0.18（几乎隐形）；当前词高亮是中性灰 `rgba(44,38,32,0.09)`，不在页脚图例承诺的三色（`#c9403a` / `#2f5d9e` / `#b8860b`）里。**海报是仓内的参照实现**——那里词就是主角。

> `check_video_layout.mjs` 的探针在**只留目标语种那一格**的副本上跑（`_vl_probe_*.html`
> 留在期目录里便于复查），量的是**渲染后**的事实：实际盒子大小、实际不透明度、实际
> 高亮色。它需要已渲染的成片（`examples/` 不入库），所以它**不在合并门禁里**；
> `check_sentence_matches.mjs` 是纯文本、零浏览器，合并门禁与 guest 里都能跑。

## 2026-10-21 的修复（RSI 波次 wave-1 落地）

D1–D5 的修法是 **RSIAgent 波次自己写的**（出题席出题 → Actor 改 → 验证席判 → 合并成真提交 `6985542`，tag `theatre/wave-1`）。改动落在三个文件：

| 文件 | 改了什么 |
|---|---|
| `build_episode.mjs` | **D1**：不再无条件替换第一个 token。新增 `wordSpan()` 在 token 序列里**定位**词形（整词匹配 → 逐字符流匹配，容忍阿拉伯语定冠词 `ال`，允许词续在 token 内部），只给那一段上色；token 序列一个不动。构建期还有一道 `throw`：画面可见文字 != token 序列就当场炸。**D2**：词形升成独立元素 `.hero` |
| `templates/video_style.css` | **D4**：`.tok.dim` 不透明度 0.18 → 0.45。**D5**：当前 token 的高亮按 token 种类取品牌三色（`.tok.cur.kv/.kc/.kt`）。**D2/D3**：`.hero` 自成一块并由脚本拟合字号；竖屏 `space-between` 均摊空间、去掉大边距（空白带 ≤ 15%） |
| `templates/video_script.js` | **D2**：对 `.hero` 二分拟合字号（竖屏 **800**×700 / 横屏 1700×420 CSS px）；卡拉OK 改为按句子 token 逐个上状态（顺序 == 念的顺序） |

**修完之后的数字**（同一套判据、同一批数据、12 期 × 12 语种 × 2 画幅 = 144 个组合）：句子门 **144/144 逐词一致**（原 54 处不一致）；版式门（**像素层**逐行扫的那把尺子）12 期 **0 条不达标**（原 954 条）。

> 竖屏拟合框从 960 收到 800，是因为**短词**（如 he-IL 的「תה」）被撑到 ~870px 字号时，
> 字形上方那圈行内上边距（≈0.25em ≈ 218px）会变成「画面空掉一大块」——实测那一帧的
> 最大空带 15.26%（阈值 15%）。收到 800 后同一帧 14.48%，其余 143 个组合实测无变化。
> **阈值是量之前定的，不许事后挪。**

> ⚠️ 这次合并**带进了一个下游回归**，是工作区主人跑完整产线才抓到的（合并门禁管不到
> `tools/`）：波次把韩语在视频侧改成了 `.cv` 融合渐变，理由是「补丁是按海报字号实测的
> 像素」——**前提是错的**。补丁用的是**百分比**定位（`background-position/size` 全是 %），
> 测量页自己写明「任意 font-size 可迁移」。代价很实：注入 `video_src.html` 的 `.k####`
> 规则变成「无人穿戴的孤儿规则」，`poster audit-charset` 当场红，**整条产线在第 12 步
> 停住**；而且韩语丢掉了页脚图例承诺的元音/辅音分色。修法：视频侧继续用实测补丁，
> `.cv` 只留给数据里显式声明的**融合音节**（`ko_fused_syllables`）。
> 另外 `.ksyl` 的 `line-height` 必须留 **1.28**——补丁量在「advance × 1.28 行高」的
> 盒子上，行高一改补丁就错位（字号变了没关系，百分比会跟着缩放）。

## 2026-10-22 的修复：渲染环境翻转把画布底部切掉（视口亏空）

2026-10-22 重新生成 12 期，**12 期全卡在第 14 步**（`poster verify-colors` 报 `grid not found`）。根因不在版式，在**出图**：Chromium 的 `--window-size=W,H` 给的是 **窗口**尺寸，实际**视口**更矮——本机实测 Edge 144.0.3719.82 矮 **93 CSS px**（宽度 24；四种窗口尺寸都一样），于是**画布底部 93px 根本没被画上**，海报网格的底边正好落在那儿。

**产线用的浏览器是 Edge 不是 Chrome**：`platform.browserPath()` 实测输出 `edge: C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`（候选表 edge 在 chrome 前，`FEUILLE_BROWSER` 为空）。Chrome 155 确实在 10-20 08:23 自动升级过，但产线压根没调用它——第一版把它当根因是错的，已订正。

**破口跟内容无关、跟浏览器升级也无关**：拿 10-20 交付的**旧期** `index.html` 用今天的 Edge、同样参数、不带补偿重渲，**底边同样被切**；而同一份 HTML、同一枚 Edge 二进制（自 1 月起没换过）10-20 渲得完整、之后渲不全——翻转在渲染环境侧（显示/桌面会话/DPI 布局那一类），具体哪一项没定位到。

仓库里早就有这个坑的补丁，但**产线走的那条路没有**：

| 渲染口 | 谁在用 | 之前有没有补偿 |
|---|---|---|
| `core/textlayer.ts` | 视频帧 | 有（自己探亏空） |
| `poster/src/render_page.ts` | Windows 整页渲染器 | 有，但**写死了常数 (24, 93)**（旧版 Edge 探的） |
| `poster/src/render_poster.ts` | **CLI 的 `poster render`（产线走这条）** | **没有** |

修法（`core/src/platform.ts` 新增 `viewportDeficit(browser)`）：渲一页只报 `innerHeight` / `clientWidth` 的探针页，**量出**亏空并按浏览器路径 memoize；三个渲染口都改成按实测亏空补窗口高度，渲完把 PNG 裁回 `w*scale × h*scale`。

两条实测出来的细节：

- **只补高度**。宽度也补的话（`--hide-scrollbars` 让排版宽度等于窗口宽），居中内容会被整体推开——海报网格竖线从 `[101, 860, 1619, 2378]` 挪到 `[117, 876, 1635, 2394]`。
- **韩语测量页也得补**（`poster measure-korean`）：三音节词（例：초콜릿）的第三个音节正好落在被切掉的区间里，墨迹掩膜被切 → 量出来的连通域是残的。

**修复的还原性**：用修好的渲染口重渲**旧期**的 `index.html`，输出与 10-20 交付的 `poster.png` **逐像素 AE = 0**（2480×3508 全等）——不是「画得更好看」，是把那天的行为精确还原。

回归钉子：`packages/poster/test/poster.test.ts` 的「画布底边必须真的被画上」（页底 40px 蓝带必须出现在输出的最后一行；撤掉补偿即红，已验证）。

## 一期怎么跑

```powershell
$env:FEUILLE_BROWSER = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:CHROME_BIN     = "C:\Program Files\Google\Chrome\Application\chrome.exe"
pnpm exec tsx tools/foodnames/run_episode.mjs `
  --data tools/foodnames/data/ep02-coffee.json `
  --out  examples/foodnames-ep02-coffee `
  --bgm  examples/_beds/bed-a.wav `
  --bgm-json examples/_beds/bed-a.wav.json
```

产线按顺序跑，任一门禁红就**当场非零退出**（不留半成品）：生成源文件 → 字体子集 → 韩语补丁实测注入 → 海报 → 三版封面 → 门禁（字符子集 / 适配 / 逐格颜色 / 叠印配准）→ 配音 → 旁白实测 → 床位反推 → 双画幅成片 → 同步门 + 白帧门 → 发布侧（`facts.json` / `manifest.json` / `copy check` / `check-plan`）。

## 批量跑多期

```powershell
node --import tsx tools/foodnames/run_series.mjs --eps 03 04 05 06 --jobs 2
```

`--jobs` 是并发期数。**并发别开太大**：每期都要起 headless Chrome 截图，Chrome 不带 `--user-data-dir` 时会共用默认 profile，抢得厉害就出白帧/错图（`scan-blank` 与 `verify-sync` 会响亮地红掉，不会静默过）。机器 22 核 / 47GB 时 `--jobs 2` 稳，`--jobs 4` 要盯住门禁。

## 发布侧：一份「事实表」管住所有数字

发布词里出现的一切数字都要能溯源（`feuille copy check --facts`）。**事实表是算出来的，不是抄文案**：

- `make_publish.mjs` 从数据 + 实测产物算出 `publish/facts.json`：结构量（12 语种 / N 条来路 / 各来源语言的格数 / 各语种位次）与实测量（时长 / 帧数 / fps / 分辨率 / 旁白实测电平 / 床实测电平与时长 / 增益）。
- 内容型事实（年份之类的「不是量出来的、但可核对的数」）由数据文件的 `extra_facts` 带进来——**脚本里不写死任何具体年份**。
- `copy-*.md` 与 `manifest.json` **只抽取** `publish/{xiaohongshu,douyin,bilibili}.md`，一个字都不改写（清单与稿件同源，免得互相拆台）。

`audit_copy_numbers.mjs` 是**离线预检**：成片还没出来时也能查「读者面数字有没有出处」，把返工挡在写稿阶段而不是产线阶段。

### 换一批重渲的产线时，发布词怎么带过来（2026-10-22 实测）

`foodnames-ii-*` 那一批是**同数据重渲**的（RSI 波次改的是构建器与模板，**数据文件一个字没动**），所以发布词可以带过来——但**三件事必须逐项核过**：

| 搬什么 | 能不能搬 | 凭什么 |
|---|---|---|
| 语言学内容（来路、谁借谁、每格位次） | **能** | 数据没变 → 结构量逐项核对一致（语种数 / 来路数 / 各「借自 X」的格数 / 每格位次） |
| 规格数字（时长、帧数、电平、gain） | **不能** | 重渲过，规格全变——但读者面正文里没有这些数，`facts.json` 由 `make_publish.mjs` 从**新成片**实测生成，规格自动跟着新交付物走 |
| 描述画面的句子 | **不能** | 旧稿有一句「视频里它们各自站在句子里」，那说的是**旧版画面**（词形只是句首的一个 token）。新版词形是独立主角 → 按「不解释画面」**删掉画面那半句、留下语言学那半句**，不是改写成另一句画面描述 |

判据一句话：**这句话说的是「交付物」还是「内容」**——说交付物的要重取，说内容的才可带，说画面的**一句都不能照搬**。

带过来之后必须过两道门（`make_publish.mjs` 之后）：

```powershell
feuille copy check <期目录>\publish --facts <期目录>\publish\facts.json   # 8 条机检，含数字溯源
feuille publish check-plan <期目录>\publish\manifest.json --root <期目录>
```

「作者手写的内容」不等于「不能自动化」：**内容不重写、规格不抄、画面描述逐句核**——自动化的是搬运与重算，不是内容本身。

### origin_locale（词源语）

`manifest` 的 `locale` 字段记的是「这个词从哪来」，不是配音语种。口径 = **12 格内词源链的最上游格**；链的起点不在 12 格内时（例：披萨 12 格全部借自意大利语），就记那个上游语言的 locale（`it-IT`）。数据文件里显式写 `origin_locale`；没写时 `make_publish.mjs` 按「唯一一格不是借来的」推导，推不出就报错——**不猜**。

## 数据格式

一期 = 一个 JSON。`words` 数组固定 12 项，顺序必须是中、英、德、法、西、俄、希腊、印地、阿拉伯、希伯来、日、韩。

```jsonc
{
 "episode": 2, "slug": "coffee",
 "title_zh": "咖啡", "title_en": "COFFEE",
 "origin_locale": "ar-SA",                    // 词源语（manifest 的 locale 字段）
 "series_sub": "各国美食名称 · 第 02 期",
 "spine": "一句话题眼（发布词的脊柱）",
 "chain": "词源链（发布词用）",
 "extra_facts": { "english_entry_year": 1582 },  // 内容型事实（年份等）→ facts.json
 "words": [{
   "locale": "zh-CN", "label": "汉语", "label_en": "CHINESE",
   "natv": "中文", "natv_class": "f-sc",       // 语种母名 + 字体类
   "script": "sc",                              // sc/jp/kr/ar/he/deva/latin/cyrillic/greek
   "word": "咖啡",          // 海报/封面用形（词条形）
   "inline": "咖啡",        // 视频句中用形（首字母大写等正字法差异）
   "zhuyin": [["咖", "<span class=\"c\">ㄎ</span>..."]],  // sc 专用：逐字注音
   "ko_syllables": ["커", "피"],              // kr 专用：逐音节（补丁由工具实测）
   "italic": true,                             // 斜体（西语等规范要求）
   "tag": "借自英语",                           // 来源标签（这期最有信息量的一列）
   "translit_html": "...",                      // 转写行（可含 .c/.v 着色）
   "sentence": "咖啡是一种饮料",                  // 旁白句
   "tokens": ["咖啡", "是", "一种", "饮料"],       // 卡拉OK逐词切分
   "persona": { "name": "林小满", "latin": "Lín Xiǎomǎn" },
   "gender": "f", "voice": "zh-CN-XiaoxiaoNeural", "voice_short": "Xiaoxiao Neural",
   "foot_html": "元音 <span class=\"v\">■</span> · ..."
 }]
}
```

**逐字着色是规则推导的**，不是逐期手抄：

| script | 规则 |
|---|---|
| latin / cyrillic / greek | 元音连成一段（红），辅音连成一段（蓝） |
| jp | 纯元音假名 `.v`；带声母的 `.cv`（红蓝渐变）；长音符 ー `.n` |
| ar / he / deva | 两行叠印：下层整词红，上层辅音 `.c`、母音字母/符号 `.t`（透明，让下层透出来） |
| kr | 逐音节 `.ksyl k<码位>`，补丁几何由 `measure-korean` 实测注入（每期音节不同，不能跨期复用） |
| sc | 逐字成列，注音在本字列里（`.zi` / `.hz` / `.annot`） |

覆盖不了的（例：日语汉字词）用 `word_html` 直接写 HTML。

## 三条纪律

1. **事实分级照旧**：词典级可断言；口语级写「口语里」；假说级带「据说」；不确定的宁可不写。每格的「来源」标签按 **Wiktionary 的直接借词方向**写（en 的 coffee ← 荷兰 koffie，不是 ← 阿拉伯；阿拉伯格才写「词源」），有争议的写「有争议」而不是替它选一个。
2. **字体子集由门禁自己算**：`build_episode.mjs` 先建空名单，让 `audit-charset`（家族栈口径）报缺字，补进去直到收敛——不另写一份字符收集器。
3. **床位每期重算**：`gain = 10^((旁白实测 − 16dB − 床实测)/20)`。床可以跨期复用（事实源是它的边车 json），增益不行。

## 已知坑（都在本目录的代码里留了注释）

- **`background:` 简写会重置 `background-clip`**（2026-10-20 实测事故，ep04/ep11 中招）。`.ksyl.cv`（韩语融合音节的整字渐变）若写成 `background: linear-gradient(...)`，简写会把 `background-clip` 打回 `border-box`；而 `.ksyl.cv` 的权重 (0,2,0) 高于 `.cv`/ `.ksyl` 的 `background-clip: text` (0,1,0) → 渐变不再裁到字形里，而是**画满整个 inline-block 盒子**，韩语融合音节渲染成实心色块。**凡是靠 `background-clip: text` 上色的规则，一律用 `background-image:` 长写，并在同一条规则里自带 `-webkit-background-clip: text; background-clip: text;color: transparent;`**（别指望别的规则兜底）。视频侧 `video_style.css` 没有 `.ksyl.cv` 规则 → **成片正常、只有海报/封面坏**，肉眼极难发现；`check_fused_glyph.mjs` 这个像素门就是为此加的。
- `check_fused_glyph.mjs` 判据：量韩语格里**彩色像素的最大实心轴对齐矩形**。正常笔画是细长条（实测长宽比 8.8~10.2），色块是又大又方正（实测 134×134，长宽比 1.00）。判为失败的条件：短边 ≥ 60px 且长宽比 < 3。「实心块」本身不是病（横/竖笔画就是实心的），**又大又方正**才是。
- `check-overlay` 的矩形是 **CSS px**（工具自己乘 `--scale`），且必须是**词形墨迹框**——从 `fit-diag` 的 dump 里取（`DIAG` JSON 的 `word: [x,y,w,h]`），别从网格线推。
- edge-tts 的词边界**不带标点**（俄语 `Суши, японское блюдо` 的边界是 `Суши`），所以「tokens 拼得出句子」的校验要去标点后比。
- 韩语的 script 键是 `kr`（不是 `ko`）——写错会静默走不到补丁分支，格子全黑。
- PowerShell 里 `$U?lang=…` 里的 `?` 会被当三元运算符，整段吃掉。
- **工具面里叶子不许读 stdin**（2026-10-22 实测事故，B 线跑批查出来的）：`poster fit-diag` / `poetry audio-profile` 缺参数时去读 stdin（`readFileSync(0)`），而 dsh 的工具面是**同进程**派发叶子（`dsh-plugin` 的 `runMain` 直接 `await fn(argv)`），stdin 是**宿主自己那根永远不关的管道** → `readFileSync(0)` **永久阻塞**，一条 rollout 的时间预算被整个烧光、什么也交不出来（实测两轮 16 条 rollout 里 9 条卡在工具调用，8 条卡在这**同一个**调用上；演化臂 4/4 全踩）。修法**掐在边界**、不改被测行为：工具面里没有可用的 stdin（`dsh-plugin` 的 `install()` 设 `FEUILLE_STDIN=off`），叶子缺参数或文件不存在 → **立刻 exit 2 + 用法错**；管道用法 `-` 显式保留，**CLI 那条路一个字没改**。钉子：叶子级 `packages/poster/test/fit_diag.test.ts`（空参 → 2、文件不存在 → 2、给了文件 → 0）+ 工具面级 `packages/dsh-plugin/test/plugin.test.ts`（吃构建产物、走真工具面调一次 `usine_poster fit-diag` 空参，断言**立刻** exit 2 而不是挂死）。
