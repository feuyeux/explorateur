# 视觉资料研究（Firecrawl）

给「作曲家生平 / 作品 / 乐器 / 时代场景」找**可用的史料图**，不是找「好看的图」。
本文件是 `SKILL.md` 第 0 步的展开：检索 → 验身份 → 验许可 → 下载校验 → 入账 →
用进画面。目标是把画面从「纯图表」提升到「图表 + 史料」，同时不让版权和错图
混进成片。

## 先定缺口，再检索

每部作品最多 3–5 张，每张必须服务一个旁白节拍：

| 缺口 | 典型画面 | 用在哪 |
|---|---|---|
| 作曲家肖像 | 油画/银版照片/晚年留影 | 生平时间轴 |
| 作品手稿 / 初版扉页 | 总谱手稿、首版标题页 | 作品导览、曲式段 |
| 乐器 / 时代场景 | 19 世纪乐队版画、英国管/圆号实物 | 乐器岗位图谱 |
| 城市 / 剧院 | 首演城市、音乐厅老照片 | 生平与首演锚点 |

**没有合适素材就空着**，用图表补，不许拿未授权图或 AI「历史照」凑数。

## 检索（Firecrawl）

```bash
# 1) 肖像：把 PD / Wikimedia Commons 写进查询，减少版权噪音
firecrawl search "Antonin Dvorak portrait public domain Wikimedia Commons" \
  --sources images --limit 20 --json -o .firecrawl/img-portrait.json

# 2) 手稿 / 初版扉页
firecrawl search "New World Symphony manuscript title page public domain" \
  --sources images --limit 20 --json -o .firecrawl/img-manuscript.json

# 3) 乐器 / 时代场景
firecrawl search "english horn historical photograph public domain" \
  --sources images --limit 20 --json -o .firecrawl/img-instrument.json
```

输出是 `data.images[]`，每条有 `title` / `imageWidth` / `imageHeight` / `url`
（出处页）/ `imageUrl`（直链或缩略图）。先做一次表，不要一张张点：

```bash
jq -r '.data.images[] | [.title, .imageWidth, .imageHeight, .url] | @tsv' \
  .firecrawl/img-portrait.json
```

**`imageUrl` 不是许可证据**，`url` 才是。直接拿 `imageUrl` 当出处 = 把缩略图/
聚合站的转载当原始馆藏。

搜索花费 2 credits；同一查询不要反复跑。`firecrawl --status` 先看余额，
结果落 `.firecrawl/` 复用（该目录应保持在交付物之外）。

## 验身份（比验许可更容易翻车）

搜到的「Dvořák 肖像」可能是：别的作曲家、后人塑像、演员定妆照、AI 生成图。
逐张核对：

1. **出处页**：Wikimedia Commons 的 `File:` 页、IMSLP、LOC、国家图书馆、
   博物馆 open access 页；页面上要有作者、年代、对象名。
2. **交叉核对**：用作品目录/传记年表确认年代与人物；有多个版本时选
   **与该段旁白年代最接近**的一张。
3. **图注写清**：人物 + 年代 + 作者/来源；不确定的写「据…藏」，
   不写「这就是他年轻时的照片」这类无法证实的断言。

## 验许可

```bash
firecrawl scrape "<File: 页 URL>" --only-main-content -o .firecrawl/license.md
```

| 许可 | 能不能用 | 备注 |
|---|---|---|
| PD-old / PD-US / CC0 | 可以 | 首选；仍登记来源 |
| CC BY / CC BY-SA | 可以 | 必须保留 attribution + 许可链接；SA 需注意演绎条款 |
| 现代演出照 / 专辑封面 / 版权谱例 | **不可以用** | 除非拿到明确许可 |
| "Fair use" / 来源不明 / 全版权 | **不可以用** | `unknown` 一律当不可用 |
| AI 生成「历史照」 | **不可以当史料** | 如使用必须标「示意图/AI 生成」 |

公有领域也要登记来源与 attribution——「PD」不等于「不用署名来源」。

## 下载与校验

```bash
# 下载直链（不要把 imageUrl 直接塞进画面）
curl -L --fail --output assets/images/src-003.jpg "<direct-image-url>"

# sha256（跨平台，Node 内建）
node -e "const{createHash}=require('node:crypto');const{readFileSync}=require('node:fs');console.log(createHash('sha256').update(readFileSync(process.argv[1])).digest('hex'))" assets/images/src-003.jpg

# 尺寸（用 platform.ffprobe() / platform.magick() 解析出的可执行文件，不写死）
ffprobe -v error -select_streams v:0 -show_entries stream=width,height \
  -of csv=s=x:p=0 assets/images/src-003.jpg
```

**尺寸门槛**（`validate-facts.mjs` 会机检）：

| 用途 | 长边下限 | 说明 |
|---|---|---|
| `full-bleed` / `background` | ≥1600px | 全屏铺底；实得 296×393 的肖像直接拒 |
| `inset` | ≥900px | 卡片/侧栏；仍要保证不糊 |

同时人眼过：无 watermark、无黑边/信箱边、无明显 AI 放大纹理、无过度 JPEG
压缩；裁切不能切掉脸、标题或关键乐器。色调可统一到纸色主题，但不要改历史
内容（不补画、不换脸）。

## 入账（两份 JSON）

1. `sources.json` 加一条 `kind: "image"`：

```json
{
  "id": "src-003",
  "kind": "image",
  "title": "Antonín Dvořák, c. 1890",
  "creator": "Unknown photographer",
  "date": "c. 1890",
  "url": "https://commons.wikimedia.org/wiki/File:...",
  "file_url": "https://upload.wikimedia.org/...",
  "license": "PD-old-70",
  "license_url": "https://...",
  "attribution": "Public domain, via Wikimedia Commons",
  "retrieved": "2026-11-02",
  "sha256": "…",
  "width": 2100,
  "height": 2600
}
```

2. `facts.json` 的 `visuals[]` 把「用途 → 来源」绑死：

```json
{
  "key": "composer-portrait",
  "source_id": "src-003",
  "usage": "inset",
  "placement": "bio-timeline",
  "caption": "Dvořák, c. 1890 · Wikimedia Commons"
}
```

`usage` 只许 `full-bleed` / `inset` / `background`；`caption` 必须带年代与来源。
交付前跑：

```bash
node assets/template/validate-facts.mjs --facts facts.json --sources sources.json
```

它会检查：图片有没有 `creator/date/file_url/width/height`、视觉条目绑的是不是
`image` 来源、`full-bleed` 长边是否 ≥1600、`inset` 是否 ≥900、有没有占位符。

## 用进画面

- 肖像 → 生平时间轴；手稿/扉页 → 作品导览；乐器/场景 → 乐器图谱。
- 每张图配**一句**图注，图注里的年代/作者与 `facts.json` 一致；不要在图里
  再写一段旁白（画面信息过载）。
- 制作信息页列图片 credits；CC BY / CC BY-SA 的 attribution 原样保留。
- 图只作旁证，不作论据：画面说「这是 1893 年首演的海报」，旁白/图注必须能
  在来源页找到同一句话。

## 失败模式（先记住）

1. **缩略图当原图**：搜索结果的 `imageUrl` 是 300px 代理，铺满 1920 就糊。
2. **错人**：同名/同姓作曲家的肖像、后人雕像、演员剧照。
3. **错年代**：用晚年照片讲青年时期；用现代音乐厅照片讲 1893 年首演。
4. **错许可**：把聚合站/博客的转载当原始馆藏；把版权谱例当 PD。
5. **AI 当史料**：生成图不标注，观众会当成历史照片。
6. **一张图讲太多**：3–5 张足够；每张服务一个旁白节拍。
