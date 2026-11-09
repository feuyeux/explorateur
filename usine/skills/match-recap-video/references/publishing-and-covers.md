# 双平台收尾：发布描述 + 首页图

> 收尾这一步只做两件事：**两份发布描述**（B站 + 抖音）与**两张首页图**（B站横版、抖音竖版）。
> 成片本体是**同一条横版**（16:9）——本轮不做竖版成片（见「已知缺口」）。
> 写文案归 `publish-copy`，投递归 `multilingual-video-publishing`；本文件写的是
> **赛事域的接缝**：哪些事实能上文案/封面、比例怎么定、门怎么过。

## 平台配对与产物形态

| 平台 | 成片 | 首页图 | 尺寸 | 发布描述 |
|---|---|---|---|---|
| B站 | 同一条横版 16:9 | **横版 16:9** | 1920×1080 | `publish/bilibili.md`（标题/简介/标签/发布贴士） |
| 抖音 | 同一条横版 16:9（信息流留边） | **竖版 3:4** | 1080×1440 | `publish/douyin.md`（文案/话题/发布贴士） |

**为什么抖音是 3:4 而不是 9:16**：抖音的竖封面槽实为 3:4（发布器 `douyin.ts` 写死点「竖封面3:4」标签），传 9:16 会被居中裁掉上下各 240px——标题带正好被切没。3:4 是零裁切的原生比例，封面机制里对应规格键 `douyin34`。

**为什么 B站是 16:9 而不是 4:3**：B站编辑器有**两个**裁切框——4:3（首页推荐）与 16:9（个人空间），两边都得有文字。传 16:9、把所有文字块落在中央 4:3 安全区（x 240–1680），两个框都有字；传 4:3 则 16:9 那框会被平台裁掉两侧。

> 两道门口径不一致，**以封面机制为准**：`core.covers` 的 `SPECS.bilibili` 是 1920×1080 + `safe=[240,0,1680,1080]`（`feuille cover check` 尺寸不符即 FAIL）；发布端 `check_plan.ts` 的 `COVER_RATIO` 记的是 B站 4/3、抖音 3/4，但**比例不符只出 note、不判 FAIL**。所以 B站出 16:9 时 `check-plan` 会留一条比例 note——那是**已知的、正确的**提示，不是没做。

## 发布描述

### 契约（与 `publish-copy` 同源，不另立一份）

- **文件命名硬约定**：`publish/bilibili.md` / `publish/douyin.md`；段落名、字数上限（80 / 30）、末话题尾随空格、互动钩、置顶话术、AI 指纹、no-hard-wrap 全部由 `feuille copy check` 判，**判据是 publish-copy 的库实现，本 skill 不写第二份**。
- **只查这两个平台**：赛事线的成片是横版，小红书吃竖屏，**不投小红书**。用 `feuille copy check publish/ --platform bilibili,douyin --facts publish/facts.json`——不给 `--platform` 时三平台齐为硬门，缺 `xiaohongshu.md` 会判 FAIL，那一行与稿子质量无关。未选中的平台会明说「没查，不是 PASS」。
- **互动钩从赛事域取**：`publish-copy` 的钩子词表是卡拉OK线的（报数/点单/跟读）+ 通用词。赛事域用得上的是**评论区 / 弹幕 / 点单 / 催更**——「报数」「跟读」在足球内容里是假的，别硬套。

### 赛事域事实面（哪些能写进文案）

| 能写 | 来源 | 不能写 |
|---|---|---|
| 比分 | fact pack `latest_pick.score` | 比分方向自己排（主客颠倒） |
| 进球 / 换人 / 黄牌 / VAR 次数 | fact pack `event_counts` | 官方页没有的轴（该联赛不支持就说做不到） |
| 轮次 / 日期 / 赛季 | fact pack `latest_pick` | 比分牌读不出的分钟数（除非窗口表能推出） |
| 成片时长 / 成片分钟数 | ffprobe 实测 | 电平、dB、渲染参数（工艺不进文案） |
| 比赛分钟上限 | 窗口表「第 N 分钟」标题 | 球员中文名（**走每场的名单**，不另抄） |

**数字必须可溯源**：`feuille copy check --facts` 的「数字可溯源」门要求读者面（标题 + 正文）里**每一个数字**都能在事实表里找到出处。事实表由 `scripts/build_publish_facts.py` 从 fact pack + ffprobe + 窗口表生成，**每一项都有出处，不许手填**。没给 `--facts` 时这道门是 SKIP——**SKIP 不是 PASS**。

> 实战里最容易踩的一条：**比赛分钟数**。母版 95 分钟、某球在第 38 分钟——这些数在 fact pack 里**没有**，只有窗口表能推出「最大比赛分钟」。推不出就不许写进文案（写了就等着溯源门报红）。

### 题眼与骨架

`assets/publish/` 下有一份**成稿样例**（《巴萨 6-1 阿拉维斯》，事实全部取自本 skill 的实跑记录）+ 一份配套事实表 `facts.example.json`，两份稿都能过判据门。换场次时改的是**标题与简介里的事实与队名**，骨架、钩子位置、贴士照抄。

题眼的选择原则（赛事域）：**比分之外的那件事**——逆转、VAR 改判、赛季首败、一场比赛的战术转折。没有那件事的场次，题眼就落在「几分钟讲完 95 分钟」的密度反差上，但那个数要有出处。

## 首页图

### 规格与做法

```bash
python3 scripts/make_covers.py --pack packs/barcelona.json \
    --facts cover_facts.json --master master.mp4 --backdrop-time 42.5 \
    --out build/cover --name barcelona-alaves --team-key barcelona
```

产出：`<name>_bilibili_1920x1080.png`、`<name>_douyin34_1080x1440.png`、两份 HTML、一份 `covers.json`、两张**裁切预览**（`preview_*.png`：B站那张是平台 4:3 裁切后的样子，抖音那张是上传即展示的样子）。

- **底图三选一**：`--backdrop-window w05`（配 `--windows`，取该窗中点）/ `--backdrop-time 42.5`（母版秒数）/ `--backdrop-image shots/w05-b.jpg`。
- **底图必须来自无字幕母版**：成片已经烧了三层字幕卡，再叠封面标题就是两层字打架。抽帧脚本统一预裁成 16:9（1920×1080），两张封面共用同一帧。
- **抖音 3:4 用「模糊铺底 + 16:9 完整画面内嵌」**：3:4 里直接裁 16:9 会丢掉 58% 的宽度（主体与边上的比分牌都可能出画）；内嵌保留整幅画面，比分牌完整可见——集锦首页图自证真场。
- **文字块用显式坐标，不用 `bottom` 锚定**：`edge_screenshot` 的窗口高 = 画布高 + 视口亏空（实测值随浏览器版本与机器变），`bottom:56px` 的元素会被压到画布外，裁完正好切掉底部文字。显式 `top` 坐标不受亏空影响。

### 版式是数据

文字块坐标在 `scripts/make_covers.py` 的 `LAYOUTS` 里，是数据不是代码：

- 每个版式声明画布尺寸、**安全区**（B站 = 平台 4:3 裁切窗口 x240–1680；抖音 = 整张画布）、四行文字块（`kicker` / `headline` / `scoreline` / `tagline`）的盒子与字号；
- `assert_layout()` 断言每个块 ⊆ 安全区、互不重叠、底边在画布内；`selftest` 里有**反向用例**（把块挪出安全区必须报红）；
- 改版式 = 改数据 + 跑 selftest。**越界的版式不许靠 CSS 裁字糊过去**（`headline` 超行直接判输入契约错）。

### 数字不许编

封面事实源（`--facts`）是**内容面**（四行文案 + 队名 + 配色），**数字面**由脚本对着 fact pack 校：

- 比分条必须含 fact pack 的比分，否则退出码 1；
- 主客颠倒 → 退出码 1；
- `headline` / `tagline` 里出现的比分声明必须等于事实源的比分（日期 `10-31` 不算比分）；
- 声明了 `goal_count` 就必须等于事件计数；
- `--team-key` 给了就查 `teams.json` 的中文队名，防队伍张冠李戴。

**fact pack 没解析出比赛（没有 `latest_pick.score`）→ 直接拒出封面**（退出码 2）：没有事实源的封面比没有封面更糟。

### 判据

| 门 | 怎么跑 | 不达标怎么读 |
|---|---|---|
| 版式与事实对账 | `python3 scripts/make_covers.py selftest` | 离线回归 + 反向验证 |
| 成品尺寸 | 脚本自检（读 PNG 头，尺寸 ≠ 规格 → 退出码 1） | 尺寸错了平台会二次裁切 |
| 展示裁切 | 看 `preview_*.png`（B站那张已按 4:3 裁过） | **文字被切掉只有人眼能判**，脚本判不了 |
| 发布描述 | `feuille copy check publish/ --platform bilibili,douyin --facts publish/facts.json` | 任一 ❌ → 不许进发布 |
| 素材在盘 | `feuille publish check-plan`（清单组装后） | 存在性闸门，别为了让它过而伪造路径 |

> ⚠️ **别拿 `feuille cover check` 当本场景的门**：它判「尺寸 + 外圈众数底色」，底色闸门是给**纯底色封面**（海报式）设计的。集锦首页图是照片底图，外圈是画面本身，**用它必红，而那不是缺陷**。尺寸由脚本自检，文字安全区由 `assert_layout` 判，展示裁切由预览图 + 人眼判——三件事各有各的门。

### 投递时的两个平台差异（别照抄另一条产线）

- **抖音的封面是发布后补**：先发视频，再用编辑流程补封面；每支**最多改 5 次**（补封面算 1 次）⇒ **先只补 1 支验落库**，确认管理页缩略图里真出文字，再批量。
- **B站合集要创作中心 Lv2**：等级不够时编辑页是灰字、无可点控件 ⇒ 本批**裸投稿**，如实说合集等升级再补挂。

### 存草稿模式的落点与封面安全区

赛事线的收尾这一轮走的是「**存草稿，不发布**」（`publish --draft`）。两平台的落点差得很远，**别把一边的结论套到另一边**：

| | B站 | 抖音 |
|---|---|---|
| 草稿落点 | `member.bouyuan.com/platform/upload-manager/article?group=draft`（点顶部「草稿 N」tab 才切到草稿列表） | **PC 端没有落点**——既没有列表页也没有接口；只能上手机 App 的作品管理看未发布条目 |
| 可核验性 | **可核验**：草稿箱条目含标题 + 落库时间 + **封面缩略图** | 只能核验到「点键后新出现的横幅」这一**瞬时**信号——横幅同一天 8:07 在、11:10 没了，不能当长期凭据 |
| 草稿带封面吗 | **带**（实测草稿箱 4 条全带封面） | **不带**（封面按既有纪律**发布后补**，每支 ≤5 次） |
| 稿件状态页提示 | 「部分草稿可能会过期，仅保存部分字段」「暂不保存：卡片配置、章节配置等信息」 | 「你还有上次未发布的视频，是否继续编辑？」——**绝不能点它旁边的「放弃」**，那是删除上一条 |

**封面裁切安全区**：B站编辑器有 4:3（首页推荐）与 16:9（个人空间）两个框，本 skill 传 16:9 ⇒ 关键文字必须整体落在中央 4:3 保留区 **x240–1680**。这条由 `make_covers.py` 的 `assert_layout()` **机检**（每个文字块 ⊆ 安全区、互不重叠、底边在画布内），selftest 里还有反向用例（把块挪出安全区必须报红）⇒ 改版式时不必人肉复算，改完跑 `python3 scripts/make_covers.py selftest` 即可。已知取舍：右下角的 `#BarçaAlavés` 标签会落在 4:3 框外，被首页推荐裁掉一点——**这是取舍不是缺陷**。

> 平台侧的存草稿机制（草稿键形态、落库判据、上传完成闸门）见 `multilingual-video-publishing/references/platform-capabilities.md` §12；本 skill 只记**赛事域的落点与封面**。

## 已知缺口（本轮明确不做）

- **竖版成片（9:16）**：本轮抖音收的是**同一条横版成片**（信息流里留边）。要竖版成片得回到装配段重烧字幕卡、重排几何、复用混音轨——那是另一个活，别在收尾段顺手做。
- **抖音合集**：平台支持，但本 skill 的收尾不做合集（发布侧的决定）。

## 收尾清单

```bash
# 1) 首页图（两张）
python3 scripts/make_covers.py --pack <pack>.json --facts cover_facts.json \
    --master <无字幕母版>.mp4 --backdrop-time <秒> --out build/cover --name <slug>

# 2) 发布描述的数字溯源表
python3 scripts/build_publish_facts.py --pack <pack>.json \
    --video <成片>.mp4 --master <母版>.mp4 --windows windows.json --out publish/facts.json

# 3) 发布描述机检（只查 B站 + 抖音）
pnpm exec feuille copy check publish/ --platform bilibili,douyin --facts publish/facts.json

# 4) 素材与清单在盘自检（发布前）
pnpm exec feuille publish check-plan <manifest.json>
```

**发布永不自动**：投递归 `multilingual-video-publishing`，用户喊了才发。
