# tools/foodnames —— 「各国美食名称」系列产线

一条 **12 语种视频系列**的批量产线：每一期是「一道菜/一样吃的在 12 种语言里的名字」，
海报 12 格、视频 12 场景卡拉OK、横竖双画幅成片、三版封面、三平台发布词。

**第 01 期（寿司）是手写的**；从第 02 期起全部由本目录的数据 + 模板生成。
第 01 期已反写成数据（`data/ep01-sushi.json`）当作**回归基准**：生成器重出的第 01 期
必须与手写版同构（叠印门矩形逐位相同、旁白实测电平与时长复算出同样的数）。

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
| `patch_publish.mjs` | 一次性：修 worker 交回的发布词里的文件名/封面贴士硬伤 |
| `measure_narration.mjs` | 旁白语音窗实测 + 时间线预算（成片前先量旁白再定床位） |
| `extract_templates.mjs` | 一次性：把第 01 期手写源文件剥成模板（改模板时重跑） |

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

产线按顺序跑，任一门禁红就**当场非零退出**（不留半成品）：
生成源文件 → 字体子集 → 韩语补丁实测注入 → 海报 → 三版封面 → 门禁
（字符子集 / 适配 / 逐格颜色 / 叠印配准）→ 配音 → 旁白实测 → 床位反推 →
双画幅成片 → 同步门 + 白帧门 → 发布侧（`facts.json` / `manifest.json` /
`copy check` / `check-plan`）。

## 批量跑多期

```powershell
node --import tsx tools/foodnames/run_series.mjs --eps 03 04 05 06 --jobs 2
```

`--jobs` 是并发期数。**并发别开太大**：每期都要起 headless Chrome 截图，
Chrome 不带 `--user-data-dir` 时会共用默认 profile，抢得厉害就出白帧/错图
（`scan-blank` 与 `verify-sync` 会响亮地红掉，不会静默过）。
机器 22 核 / 47GB 时 `--jobs 2` 稳，`--jobs 4` 要盯住门禁。

## 发布侧：一份「事实表」管住所有数字

发布词里出现的一切数字都要能溯源（`feuille copy check --facts`）。
**事实表是算出来的，不是抄文案**：

- `make_publish.mjs` 从数据 + 实测产物算出 `publish/facts.json`：
  结构量（12 语种 / N 条来路 / 各来源语言的格数 / 各语种位次）
  与实测量（时长 / 帧数 / fps / 分辨率 / 旁白实测电平 / 床实测电平与时长 / 增益）。
- 内容型事实（年份之类的「不是量出来的、但可核对的数」）由数据文件的
  `extra_facts` 带进来——**脚本里不写死任何具体年份**。
- `copy-*.md` 与 `manifest.json` **只抽取** `publish/{xiaohongshu,douyin,bilibili}.md`，
  一个字都不改写（清单与稿件同源，免得互相拆台）。

`audit_copy_numbers.mjs` 是**离线预检**：成片还没出来时也能查
「读者面数字有没有出处」，把返工挡在写稿阶段而不是产线阶段。

### origin_locale（词源语）

`manifest` 的 `locale` 字段记的是「这个词从哪来」，不是配音语种。
口径 = **12 格内词源链的最上游格**；链的起点不在 12 格内时（例：披萨 12 格
全部借自意大利语），就记那个上游语言的 locale（`it-IT`）。
数据文件里显式写 `origin_locale`；没写时 `make_publish.mjs` 按
「唯一一格不是借来的」推导，推不出就报错——**不猜**。

## 数据格式

一期 = 一个 JSON。`words` 数组固定 12 项，顺序必须是
中、英、德、法、西、俄、希腊、印地、阿拉伯、希伯来、日、韩。

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

1. **事实分级照旧**：词典级可断言；口语级写「口语里」；假说级带「据说」；不确定的宁可不写。
   每格的「来源」标签按 **Wiktionary 的直接借词方向**写（en 的 coffee ← 荷兰 koffie，
   不是 ← 阿拉伯；阿拉伯格才写「词源」），有争议的写「有争议」而不是替它选一个。
2. **字体子集由门禁自己算**：`build_episode.mjs` 先建空名单，让 `audit-charset`
   （家族栈口径）报缺字，补进去直到收敛——不另写一份字符收集器。
3. **床位每期重算**：`gain = 10^((旁白实测 − 16dB − 床实测)/20)`。
   床可以跨期复用（事实源是它的边车 json），增益不行。

## 已知坑（都在本目录的代码里留了注释）

- `check-overlay` 的矩形是 **CSS px**（工具自己乘 `--scale`），且必须是**词形墨迹框**——
  从 `fit-diag` 的 dump 里取（`DIAG` JSON 的 `word: [x,y,w,h]`），别从网格线推。
- edge-tts 的词边界**不带标点**（俄语 `Суши, японское блюдо` 的边界是 `Суши`），
  所以「tokens 拼得出句子」的校验要去标点后比。
- 韩语的 script 键是 `kr`（不是 `ko`）——写错会静默走不到补丁分支，格子全黑。
- PowerShell 里 `$U?lang=…` 里的 `?` 会被当三元运算符，整段吃掉。
