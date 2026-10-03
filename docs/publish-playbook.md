---
title: 多平台发布手册（抖音 / 小红书）
updated: { by: dsh/fuyao-work, at: 2026-10-04, note: "02:00 补：05–14 跑完（小红书 14/14 全发完），踩坑实录 18 → 23 条（新增合集下拉被视口裁掉 / 合集选中态看 class / 发布按钮用 ref 不用坐标 / 上传后别先 sleep / generation 跳回 1 = 页面重建），§5.2 换成实跑 10/10 的顺序。事实源文案见 lessons/colors/publish/{douyin,xiaohongshu}-copy.md" }
---

# 多平台发布手册（抖音 / 小红书）

> **什么时候读这份文档**：要把 `build/scene/scene-colors_*.mp4`（或任何成片）发到
> 抖音 / 小红书创作服务平台时。渲染相关的坑在 [render-handbook.md](render-handbook.md)，
> 这里只管「成片出去以后」这一段。
>
> **知乎专栏不在这份文档里**。知乎走的是「Markdown 导入文档 + 内嵌视频 + 改已发布链接」，
> 富文本机制与抖音 / 小红书完全不同（知乎是 Draft.js，转换只在 paste 事件触发），
> 流程与踩坑见 [zhihu-publish-playbook.md](zhihu-publish-playbook.md)。
>
> **本文档的每条流程都经过实跑验证**，不是从平台文档抄的。带 ⚠️ 的是「不照做就出错」的点。

---

## 1. 账号与入口速查

| 项 | 抖音 | 小红书 |
|---|---|---|
| 创作者后台 | `https://creator.douyin.com/` | `https://creator.xiaohongshu.com/` |
| 发布页 | `/creator-micro/content/post/video?enter_from=publish_page` | `/publish/publish` |
| 内容管理 | `/creator-micro/content/manage` | `/new/note-manager` |
| 合集管理 | `/creator-micro/content/manage?tab=collections` | **不存在** |
| 本项目账号 | `lapin` / 抖音号 `LapinAvecCulture` | `lapin` / 小红书号 `feuyeux` |
| 登录方式 | 扫码（用户本人完成） | 扫码（用户本人完成） |

**认证一律由用户接管**：扫码、手机号、验证码、密码、验证码全部是用户操作，agent 不得代填。
登录成功的判据是**账号昵称 + 头像菜单里的「退出登录」同时出现**，不是「页面长得像后台」。

---

## 2. 硬性限制对照

| 项 | 抖音 | 小红书 |
|---|---|---|
| 标题上限 | 30 字 | **20 字** ⚠️ |
| 正文上限 | 1000 字 | 1000 字 |
| 合集标题上限 | 20 字 | 20 字 |
| 合集简介上限 | 200 字 | **50 字** |
| 视频上限 | — | 4 小时 / 20 GB |
| 正文编辑器 | Slate（`contenteditable`） | ProseMirror / tiptap（`contenteditable`） |
| 「第 N 集」编号 | **平台自动分配，不要手动设** | 同左 |

⚠️ **抖音的 29 字标题原样搬到小红书会红字报错**（显示 `28/20`）。本项目的标题方案就是
为此重排的：小红书用 `14种语言聊颜色｜NN语种 场景关键词`，砍掉「第」「话」「：」三个冗余字。

---

## 3. 跨平台铁律

1. **一次只发一个 Browser action，绝不并行。** Browser action 共享页面/快照/navigation 状态，
   并行会互相踩。
2. **`click` 返回 `effect.verified: false` 不代表没生效**，只代表「输入已投递、效果未验证」。
   必须 `inspect` / `query` / `screenshot` 复核后才能声称成功。
3. **`fill` 返回 `ACTION_EFFECT_MISMATCH` 也不代表失败**（见坑 ④⑤）。永远以
   `query kind=dom` 读回的 DOM 为准，不相信返回值的 `success` 字段。
4. **元素 ref 是 snapshot-scoped 的。** 导航 / reload / 重新 inspect 之后，旧 ref 全部作废，
   必须重新取。绝不复用上一轮的 ref。
5. **发布成功判据**（两个都要）：URL 出现 `published=true` **且** 表单重置为上传页、
   草稿箱计数为 0。只看其中一个都可能误判。
6. **合集作品数递增是最好的旁证**：每发一支记一次「总集数」，出现跳号就说明有支没进去。
7. **上传后必须等转码**：`Start-Sleep -Seconds 25`。不等的话标题框还没出现。
8. **批量发布前先跟用户确认一次整批**，拿到确认后同批内不必逐支再问；
   但只要**页面刷新、换账号、草稿被改动**，就要重新确认。

---

## 4. 抖音发布流程

### 4.1 前置：合集必须先建

⚠️ **抖音的合集入口只有创建页一个，且创建页只列「已发布作品」**。所以顺序是：

```
内容管理 → 合集管理 → 创建合集（可以建空的）→ 再逐支发布时在发布页勾选
```

发布页的「添加至合集」下拉**没有新建入口**，空合集必须提前建好，否则下拉里根本看不到它。

### 4.2 逐支发布（已验证序列）

| # | 动作 | 要点 |
|---|---|---|
| 1 | `navigate` 发布页（`replaceCurrentTab: true`） | 单标签页流程 |
| 2 | `query kind=semantic` text=`上传视频` → 取上传卡 ref | |
| 3 | `upload_files` paths=[`build/scene/scene-colors_<locale>.mp4`] | 不要预先 `stat`/`ls` 校验路径 |
| 4 | `bash: Start-Sleep -Seconds 25` | 等转码 |
| 5 | `query kind=editable` | 取标题 input + `.zone-container[contenteditable="true"]` ref |
| 6 | `fill` 标题 | 普通 input，返回 `success: true`，核对 `textLength` = 目标字数 |
| 7 | `fill` 正文 | ⚠️ **末尾保留一个尾随空格**，见坑 ① |
| 8 | `query kind=dom` selector=`.zone-container[contenteditable="true"]` | **复核**，不信 fill 返回值 |
| 9 | `query kind=semantic` text=`请选择合集` → click | |
| 10 | `query kind=semantic` text=`<合集名>` → click | |
| 11 | `scroll` down 900 | |
| 12 | `screenshot` | 复核：合集名已选 / 允许下载 / 公开 / 立即发布 |
| 13 | `click` 发布 | 位置随 viewport 变，见下 |

**发布按钮坐标**（`click position`，绝对 CSS 像素）：
- viewport 1108×1087 → **(233, 974)**
- viewport 1363×1087 → **(364, 992)**

⚠️ 坐标随 viewport 宽度漂移，**每次都先 `inspect`/`query` 看当前 rect**，不要照抄上面的数。

### 4.3 发布设置

公开可见 / 允许下载 / 立即发布（不定时）。

---

## 5. 小红书发布流程

### 5.1 前置：合集在第 01 支的表单里一次建好

⚠️ **小红书笔记管理里没有合集 tab，头像菜单里也没有**。合集只有一个入口：

```
发布笔记 → 加入合集 → 选择合集 → 创建合集
```

点「创建并加入」可以**一次完成建集 + 挂到当前这支**。这跟抖音正好相反
（抖音要先建空集，小红书可以边发边建）。

本项目的合集就是在第 01 支的表单里创建的，之后 13 支只需在下拉里点第一位。

### 5.2 逐支发布（已验证序列，05–14 实跑 10/10）

| # | 动作 | 要点 |
|---|---|---|
| 1 | `query kind=semantic` text=`上传视频` → 取 `class` 含 `upload-button` 的 button ref | |
| 2 | `upload_files` paths=[`build/scene/scene-colors_<locale>.mp4`] | |
| 3 | `query kind=editable` → 取标题 input + `.tiptap.ProseMirror` ref | **不要先 sleep**（坑 ㉒） |
| 4 | `fill` 标题 | 普通 input，`success: true`，核对 `textLength` = 目标字数 |
| 5 | `fill` 正文 | ⚠️ **预期返回 `ACTION_EFFECT_MISMATCH`，属正常**（坑 ③） |
| 6 | `press_key` key=`Tab` | ⚠️ **关键**：关掉话题联想面板（坑 ②） |
| 7 | `bash: Start-Sleep -Seconds 22` | 此时转码完成 |
| 8 | `query kind=dom` selector=`.tiptap.ProseMirror` | 复核正文，末段必须是纯文本标签 |
| 9 | `press_key` key=`PageDown` | ⚠️ **关键**：把合集按钮抬进视口上半部（坑 ⑲ + 坑 ⑥） |
| 10 | `query kind=semantic` text=`选择合集`（`class="collection-plugin-button"`）→ click | |
| 11 | `query kind=semantic` text=`<合集名>`（下拉第一位，`class="item-content"`）→ click | |
| 12 | `query kind=semantic` text=`<合集名>`（下拉已关） | class 变 `collection-plugin-choose` = 已选（坑 ⑳） |
| 13 | `query kind=text` selector=`body` maxChars=300 | 确认 `scene-colors_<locale>.mp4` 在位 |
| 14 | `query kind=semantic` text=`发布` → 取 `class="ce-btn bg-red"` 的 button → click | ⚠️ 挑对按钮，见坑 ㉑ |
| 15 | `bash: Start-Sleep -Seconds 6` | |
| 16 | `query kind=text` selector=`body` maxChars=300 | URL 含 `published=true`、正文为「上传视频」、草稿箱不增 |

**发布按钮**：用 `ce-btn bg-red` 的 ref，不要用坐标。坐标随视口高度漂移
（1060×1029 → y=984；1060×1087 → y=1043），本项目实测两种都出现过。

### 5.3 发布设置

公开可见 / 定时发布**关闭** / 加入合集。

---

## 6. 踩坑实录

### 坑 ① 抖音正文末尾标签被联想面板吃掉（已造成线上事故）

**现象**：抖音第 01 支英语的正文发出后是 242 字，正确版本只有 124 字。实际内容 =
`[完整正文] #语言学习 #X[重复整段正文] #语言学习 #多语言对比 #英语口语 #英语学习语言对比
#英语口语 #英语学习 #小语种就业前景`。

**原因**：正文末尾的 `#小语种` 在 blur 时被 Slate 识别成话题候选，弹出联想面板并**选中了一个
无关联想词**（`就业前景`）；随后 `fill` 的插入语义导致原文被重复追加。

**解法**：⚠️ **正文最后一个标签后面必须留一个尾随空格**。尾随空格让 Slate 判定话题未闭合，
联想面板不弹，标签保持纯文本。第 03 支起验证有效。

**教训**：话题/标签类富文本，**一律在末尾加尾随空格**，抖音、小红书都适用
（小红书用 `Tab` 方案，见坑 ②）。

### 坑 ② 小红书话题联想面板会替换末尾标签

**现象**：填完正文，正文末尾的 `#小语种` 变成一个 `.suggestion` 装饰 span，内容被替换。

**解法**：填完正文立刻 `press_key key=Tab` 移开焦点。`.suggestion` 装饰 span 消失，
标签文字保持不变。第 02、03、04 支均验证有效。

⚠️ **`press_key key=Escape` 无效**，面板仍在。别浪费时间试 Escape。

**复核方式**：`query kind=dom` selector=`.tiptap.ProseMirror`，确认末段是纯文本、没有
`<span class="suggestion">`。

### 坑 ③ 小红书正文 `fill` 必然返回 `ACTION_EFFECT_MISMATCH`

富文本归一化后 DOM 文本与请求值不完全相等（换行变成 `<p>`、尾随字符被 trim）。
**这是正常的**。`effect.textChanged: true` + `textLength` 接近目标值即可，
真正的判据是随后 `query kind=dom` 读回的 HTML。抖音正文 `fill` 同理。

### 坑 ④ 抖音 `fill` 对非空 contenteditable 是插入不是覆盖

往已有内容的编辑器里 `fill` 会**追加**而不是替换。而且：

- `Control+a` 在注入通道**不生效**；
- 可靠的清空方式 = **`drag` 拉选 + `press_key Backspace`，做两轮**。

第 01 支正文污染事故的第二重成因就是这里。

### 坑 ⑤ `click` / `fill` 的 `success: true` 都不是效果证明

`click` 的 `effect.verified` 恒为 `false`。所有「点了之后到底生效没有」的问题，
一律靠 `inspect` / `query(kind=text|dom)` / `screenshot` 回答。

### 坑 ⑥ 小红书发布页内层滚动容器不能用 `scroll` action

`scroll` 返回 `moved: false, atEnd: true`，但页面明显还能往下滚——只是滚的不是它认定的那个容器。

**解法**：先让页面获得焦点（点一个中性区域或 `Tab`），再 `press_key key=PageDown`。
另外 `press_key key=PageUp` 有时完全无效（焦点不在滚动容器上），此时改用
`query` 读 DOM 复核内容，不要反复试滚动。

### 坑 ⑦ 抖音合集与小红书合集的建立方式相反

| | 建空集 | 表单里建集 | 笔记管理里有合集 tab |
|---|---|---|---|
| 抖音 | ✅ 必须 | ❌ 无入口 | ✅ `?tab=collections` |
| 小红书 | ❌ 无此路径 | ✅ 「创建并加入」 | ❌ **没有** |

不知道这点会在抖音卡住（空合集不预建，下拉里永远看不到目标合集）。

### 坑 ⑧ 抖音审核中的作品不能提交编辑

第 01 支首次尝试修改时因审核中，「提交修改」不可用。**等审核状态变「通过」再改**。
这也是为什么第 01 支的修正在 14 支全部发完、全部通过之后才做。

### 坑 ⑨ `inspect` 可能返回 `BROWSER_RESULT_TOO_LARGE`

发布页 DOM 很大，`inspect` 会超 64 KiB 预算。**改用定向查询**：
`query kind=editable`（取输入框）、`query kind=semantic`（按可见文字定位控件）、
`query kind=text` + 窄 selector（读内容）。不要反复重试 `inspect`。

### 坑 ⑩ `screenshot` 可能返回旧帧

连续截图字节数几乎相同时，说明抓到的是同一帧。**同状态下 DOM query 与 screenshot 矛盾时，
以 DOM query 为准**。判断「页面变了没」用 `query`，`screenshot` 只用来读布局和视觉状态。

### 坑 ⑪ 阿拉伯语 / 希伯来语正文里的「查到」是错字

`从红色一路查到白色` 应为 **`问到`**。抖音 09、10 两支已带这个错字发出，
小红书版已改对。两平台都是 RTL 语种，错字来源相同，属笔误而非 RTL 排版需要。

### 坑 ⑫ 用户可能同时操作同一个浏览器面板

焦点会漂移，出现重复操作或漏操作。**每次动作前用 `query` 确认页面仍在预期状态**，
不要凭上一轮的记忆继续。

### 坑 ⑬ 上传前不要用 shell 校验文件路径

`upload_files` 自己会校验存在性、类型、授权、数量、体积。
预先 `stat` / `ls` / `test` 是浪费，且可能因路径写法差异产生假阴性。

### 坑 ⑭ 小红书草稿箱计数是发布成功的免费校验

发布后草稿箱应回到 `(0)`。如果计数增加，说明那支没发出去、留成了草稿。

### 坑 ⑮ 上下文压缩会让 Browser skill 加载凭据失效

长流程里如果发生过上下文压缩，**压缩后必须重新 `skill` 一次
`browser-use:control-in-app-browser`**，否则 Browser 调用返回 `SKILL_REQUIRED`。

### 坑 ⑯ `open_tab` 传入的 URL fragment 不会生效

会沿用上一次的 hash。要验证 `#hash` 深链必须让页面自己跳（壳页 `location.replace(...)`）。

### 坑 ⑰ 正文标签里的易混码位

`；`(U+FF1B) vs `;`(U+037E 希腊问号)、全半角问号、`-`/`–`/`—`、各类引号——
在发布文案里写这些字符时，**编辑完立刻回读该行打印码位确认**，别靠肉眼看 diff。
写检查脚本本身时尤其危险：脚本里的字面量被静默归一，会导致验收永远误判。

### 坑 ⑱ 平台频率限制

单日连发 14 支会触发频率风控。本项目 2026-10-03 抖音 14 支、2026-10-04 小红书分批
均未被限流，但这是**用户明确接受的风险**，不是平台保证。换时间窗发更稳。

### 坑 ⑲ 合集下拉被视口裁掉 = 查不到任何选项

**现象**：`选择合集` 按钮点击「成功」，但紧接着查合集名返回 `matchCount: 0`——
看起来像下拉没打开，或合集不存在。

**真实原因**：合集下拉**向下展开**。按钮在视口底部时（实测 y=986 / 视口高 1029），
下拉整体落在视口外，DOM 里有、屏幕上没有。

**解法**：点之前先看按钮 rect，**y > 视口高 - 120 就先 `press_key PageDown`**，
把它抬到视口上半部再点。抬到 y≈142 后下拉落在 y≈181，稳定可查。

⚠️ 这是「查不到」的假阴性。**不要**因为 `matchCount: 0` 就去改代码或怀疑合集被删。

### 坑 ⑳ 合集有没有选中，看 class 变没变

比截图可靠，也比读全页文本省一次大查询：

| class | 含义 |
|---|---|
| `collection-plugin-button` | **未选**。下拉关闭时查合集名 → `matchCount: 0` |
| `collection-plugin-choose` | **已选**。同时 `class="collection-name"` 显示名字 |

选完关掉下拉，查一次合集名：命中 `collection-plugin-choose` = 已选，0 匹配 = 没选上。
右侧预览卡还会出现 `合集·<合集名>`（`class="info-card-text main"`），是第二重旁证。

### 坑 ㉑ 发布按钮有稳定 ref，别用坐标

`class="ce-btn bg-red"` 的 `<button>`，用 `query kind=semantic` text=`发布` 取。
注意同名的「发布笔记」侧栏入口也在匹配结果里，**要挑 `class` 含 `ce-btn bg-red` 的那个**。

坐标会随视口高度漂移（1060×1029 时在 y=984，1060×1087 时在 y=1043），
本项目 14 支里实际就撞到过一次 1043 失效、984 才准。**ref 不漂，坐标漂。**

### 坑 ㉒ 上传后别急着睡 25 秒——表单立刻就有了

实测**上传完成后标题/正文字段立刻渲染**（视频还在「上传中」），不必等转码。
旧流程是「上传 → `Start-Sleep 25` → 再取 ref」，实测那 25 秒里页面可能重建，
导致刚取的 ref 全部 `STALE_ELEMENT_REF`，**已上传的视频被存成草稿**（草稿箱 0→1），
这一支白传一遍。

**更稳的顺序**（05–14 实跑 10/10）：

```
upload_files
→ 立刻 query kind=editable 取 ref（不等）
→ fill 标题 → fill 正文 → press_key Tab
→ Start-Sleep 22（此时转码也完成了）
→ query kind=dom .tiptap.ProseMirror 复核正文
→ press_key PageDown（把合集按钮抬进视口上半部）
→ 选合集 → query 确认 class 变 choose
→ query kind=semantic text=发布 取 ce-btn ref → click
→ Start-Sleep 6 → query kind=text 确认表单已重置
```

### 坑 ㉓ 页面重建的信号：generation 跳回 1

`navigation.generation` 是页面代号。正常递增（5 → 6 → 9 → 13…）；
**突然跳回 1 = 整个页面被重建**，此前所有 ref 全部作废，必须重新 `query`。

同时若视口在 **1060×1029** 与 **1280×720** 之间反复跳变，说明有人在同时拖浏览器面板
（见坑 ⑫）。这种情况下 `STALE_ELEMENT_REF` 会连发，重试同一动作只会继续失败——
换成 `position` 点击或干脆让出控制权。

---

## 7. 发布后核验清单

发布完成不等于交付完成。逐项打勾：

**单支级**
- [ ] 发布后 `query` 确认 URL 含 `published=true`
- [ ] 表单已重置为上传页，草稿箱计数为 0（小红书）
- [ ] 标题显示的字数 = 预期字数（防截断）
- [ ] 正文 DOM 末尾是纯文本标签，没有 `.suggestion` / 话题卡 span

**整批级**
- [ ] 内容管理页作品总数 = 原有数 + 14
- [ ] 逐支审核状态都是「通过」（抖音）
- [ ] 合集详情页「总集数」= 14
- [ ] 逐支标题与正文跟 `lessons/colors/publish/*.md` 对得上

**跨平台级**
- [ ] 两个平台的编号/顺序一致
- [ ] 已知内容缺陷已登记（见 §8）

---

## 8. 已发布台账

### 抖音 `LapinAvecCulture`

- 合集「十四种语言聊颜色全集」：https://creator.douyin.com/creator-micro/work-management/collection-detail/7692462700349098030?enter_from=collect-manage
- 作品总数 21（原 7 + 新 14），01–14 **全部审核通过、全部进合集**（总集数 14）。

**遗留缺陷**
| 编号 | 问题 | 状态 |
|---|---|---|
| 01 | 正文被联想面板污染：重复整段 + 错话题 `#小语种就业前景`，242 字（应为 124 字） | ⬜ 待修 |
| 09 / 10 | 正文「从红色一路**查**到白色」应为「**问**到」 | ⬜ 待修 |

### 小红书 `feuyeux`

- 合集「十四种语言聊颜色全集」（简介 36/50）。
- **14 支已全部发布**（2026-10-04 01:16–01:49），全部已勾选合集。
- 笔记管理页直接核验到 05–14 共 10 支，标题与时长与源文件一一对应
  （05 it-IT 00:50 / 06 ru-RU 00:50 / 07 el-GR 00:46 / 08 hi-IN 00:54 / 09 ar-SA 00:54 /
  10 he-IL 00:47 / 11 ja-JP 00:54 / 12 ko-KR 00:50 / 13 zh-HK 00:50 / 14 zh-CN 00:45）。
- 01–04 为发布当场核验（表单重置 + `published=true` + 草稿箱 0）。
  合集篇数单调递增可反证无缺号：编 05 时预览显示「共 5 篇」= 已发 4 篇 + 当前这支，
  编 06 → 共 6 篇，编 07 → 共 7 篇。
- 审核状态：05–13 已出结果（无「审核中」标记），**14 汉语发布时仍为「审核中」**，属正常。

**遗留**
- 草稿箱残留 1 条：05 意大利语首次上传时被页面重载打断、存成草稿。内容与已发布的
  05 重复，可在草稿箱删除。

---

## 9. 换项目复用时要改的地方

这份文档里**平台机制部分完全通用**（§1 §2 §3 §4 §5 §6 §7），
只有 §8 的台账和 §9 之后的文案是项目相关的。换项目时：

1. 改 §1 的账号与入口；
2. 改 §2 的实际限制（平台可能改版，先实测一条再填表）；
3. 文案另建事实源文件，参考 `lessons/colors/publish/` 的体例；
4. §8 换成本项目的台账。
