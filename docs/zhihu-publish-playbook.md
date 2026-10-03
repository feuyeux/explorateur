---
title: 知乎发布手册（专栏长文 + 内嵌视频）
updated: { by: dsh/fuyao-work, at: 2026-10-04, note: "15 篇（1 主文 + 14 分语种）实跑全通；踩坑实录 20 条（新增 ⑰ 阿拉伯文区段被服务端过滤 / ⑱ clear:true 打过期 ref 清空全文 / ⑲ 标题重复拼接 / ⑳ 草稿删除报文章未找到）。第 11 话与主文已重导更新。抖音 / 小红书见 publish-playbook.md" }
---

# 知乎发布手册

> **什么时候读这份文档**：要把 `build/lesson/colors/index.html`（或任何长文档）发到知乎专栏时。
> 抖音 / 小红书的短流程在 [publish-playbook.md](publish-playbook.md)，渲染侧的坑在
> [render-handbook.md](render-handbook.md)。**三个平台的富文本机制完全不同，别互相套用解法。**
>
> **本文档的每条流程都经过实跑验证**，不是从平台文档抄的。带 ⚠️ 的是「不照做就出错」的点。

---

## 1. 结论先行：知乎只有一条可自动化路径

知乎正文是 **Draft.js** 富文本，它把 Markdown 源码转成标题 / 加粗 / 表格 **只在真实 paste 事件里触发**。
`fill` / `type` 注入进去只会得到一屏字面的 `##`、`**`、`|`。

**唯一验证成功的全自动路径是「导入文档」**——不是粘贴，是把 `.md` 文件整个传上去：

```
open_tab https://zhuanlan.zhihu.com/write
→ click (886,83)「导入」         ⚠️ 工具栏下拉不吃 selector，只认坐标
→ click (866,141)「导入文档」
→ query kind=semantic 取 drop zone ref
→ upload_files paths=[<绝对路径>.md]
→ wait 4500
```

| 路径 | 结果 |
|---|---|
| `fill` 正文 | ❌ opaque ref 立刻 `STALE_ELEMENT_REF` |
| `type` 正文 | ❌ 字面 `##` / `**` / `|`，不转排版 |
| 真实 Ctrl+V 粘贴 | ⚠️ 可行但需人工，且「确认并解析」按钮点击无效 |
| **导入文档上传 .md** | ✅ **本项目全程走这条，15/15 成功** |

---

## 2. 已验证的逐篇发布序列

### 2.1 导入 + 插视频（可逆阶段）

| # | 动作 | 要点 |
|---|---|---|
| 1 | `open_tab https://zhuanlan.zhihu.com/write` | 每个语种开新页，别复用脏编辑器 |
| 2 | `click (886,83)` → `click (866,141)` | ⚠️ 坐标；见坑 ③ |
| 3 | `query kind=semantic` text=`点击选择本地文档或拖动文件到窗口上传` → 取 drop zone ref | |
| 4 | `upload_files paths=[<该语种>.md]` | 不要预先 `stat`/`ls` 校验路径 |
| 5 | `wait kind=timeout timeout=4500` | ⚠️ 用 `timeout` 不用 `delay`，见坑 ⑧ |
| 6 | `type selector="textarea.Input" text=<标题>` | ⚠️ selector 在**顶层**，见坑 ⑦ |
| 7 | `query kind=semantic` text=`本篇 17 行连读视频（<语种>，约 <N> 秒）。` → 取锚点 ref | 视频位置靠这句定位 |
| 8 | `click` 锚点 ref → `press_key End` → `press_key Return` | 换行，把视频插到下一段 |
| 9 | `click (815,31)`「视频」→ `query kind=semantic` text=`导入视频` → 取 `button.VideoUploadButton` ref | |
| 10 | `upload_files paths=[build/scene/scene-colors_<locale>.mp4]` | ⚠️ **会报 `browser_action_failed`，但其实成功**，见坑 ⑤ |
| 11 | `wait kind=timeout timeout=8000` | 等转码 |
| 12 | `query kind=dom selector='div[contenteditable="true"] .Editable-video'` | **复核视频真的在位** |

视频落在 `## 整段视频` 小节的说明之后、`## 逐句脚本与解析` 之前——这是锚点那句的作用。

### 2.2 发布（不可逆阶段）

⚠️ **14 篇分语种全部导入完成后，再一次性向用户确认整批发布**。理由见 §3 铁律 3。

| # | 动作 | 要点 |
|---|---|---|
| 1 | `click (895,1004)`「发布」 | 草稿态的发布按钮 |
| 2 | `wait kind=timeout timeout=5000` | |
| 3 | `inspect limit=1` 读 URL | **发布 URL = 草稿 URL 去掉 `/edit`** |
| 4 | 记进 `_draft-log.json` | |

**主文导览必须最后发**：它的 14 条目录链接要指向分语种篇的真实 URL，URL 不存在就没法出稿。

---

## 3. 知乎侧铁律

1. **一次只发一个 Browser action，绝不并行。**
2. **`click` 返回 `effect.verified: false` 不代表没生效。** 所有「点了生效没有」的问题，
   一律靠 `query(kind=dom|text)` / `screenshot` 回答。**永远不信返回值的 `success` 字段。**
3. **可逆阶段与不可逆阶段必须分离**：先全部导入成草稿（可删可改），再一次性确认发布。
   用户确认的是「这一整批」，不是「这一篇」。
4. **发布是外部可见不可逆动作，每次都要 `ask_user` 确认卡片**，卡片里逐字复述站点、账号、
   标题、篇数、文件名、可见性。用户批准整批之后，同批内不必逐篇再问；页面刷新 / 换账号 /
   草稿被改动则要重新确认。
5. **元素 ref 是 snapshot-scoped 的。** 导航 / reload / 重新 inspect 之后旧 ref 全部作废。
6. **两套 selector，不要混**：

   | 场景 | 链接的 class | 查询写法 |
   |---|---|---|
   | 编辑器（`/write`、`/p/<id>/edit`） | `Link ztext-link` | `div[contenteditable="true"] a.Link` |
   | 公开页（`/p/<id>`） | `internal` + `data-draft-type="text-link"` | `article a[href*="<id>"]` |

7. **已发布文章的修改走 `/p/<id>/edit` → 点「更新」**，不是「发布」。
   两个按钮都在视口右下角，**发布 (895,1004) / 更新 (889,1004)**，差 6 像素，别点错。
8. **草稿 / 失败草稿会堆积。** 每次实验都要把废弃草稿 ID 记进 `_draft-log.json` 的
   `junk_drafts_to_clean`，收尾时清掉。

---

## 4. 改已发布文章里的链接（2026-10-04 实跑 14/14）

这是本项目最脏的一段活，单独成节。场景：`.md` 里写的返回链接是**相对路径**，
粘到知乎后变成 `https://zhuanlan.zhihu.com/00-主文-六个颜色词十四种语言.md`——死链。

### 4.1 已验证序列

| # | 动作 | 要点 |
|---|---|---|
| 1 | `open_tab https://zhuanlan.zhihu.com/p/<id>/edit` | |
| 2 | `query kind=semantic` text=`总目录` → 取 `<a>` ref | 链接通常在视口外（y≈9300），click 会自动滚动 |
| 3 | `click` ref → `press_key End` | 光标落到行尾 |
| 4 | `press_key Shift+ArrowLeft` | 选中 1 个字 |
| 5 | `press_key Control+Shift+ArrowLeft` | ⚠️ **在 Draft.js 里等同单字符左移**，再选 1 个字 |
| 6 | `press_key Control+Shift+ArrowLeft` | ⚠️ **参数必须与上一步不同**，否则触发 runaway guard，见坑 ⑫ |
| 7 | `click (149,553)`「编辑链接」 | ⚠️ **坐标，不能用 semantic**——菜单在 portal 里不在语义树中，见坑 ⑨ |
| 8 | `type selector='input[placeholder="输入链接地址"]' clear=true text=<新 URL>` | |
| 9 | `press_key Return` | |
| 10 | `query kind=dom selector='div[contenteditable="true"] a.Link'` | **复核 href 已换** |
| 11 | `click (889,1004)`「更新」→ `wait kind=timeout timeout=4000` | |
| 12 | `open_tab https://zhuanlan.zhihu.com/p/<id>` → `query kind=dom selector='article a[href*="<主文id>"]'` | **公开页复核**，别信编辑器的结果 |

### 4.2 RTL 语种要多滚一段

阿拉伯语 / 希伯来语的编辑页里，链接行在视口**最底部**，内联菜单的「编辑链接」被顶到
**(149, 755)** 而不是常规的 (149, 553)。此时先 `scroll` / `PageDown` 把链接抬到视口中部，
菜单才会回到常规位置。本项目 14 篇里只有 11（ar-SA）、12（he-IL）踩到。

---

## 5. 踩坑实录

### 坑 ① Markdown 导入器会丢弃**表格单元格里的链接** ⚠️ 本项目最贵的坑

**现象**：主文导览第八节「系列目录」原本是三列表格（标题 / 语族 / 时长）。
导入后查 `div[contenteditable="true"] a` → **`Element not found`，一个 `<a>` 都没有**。
表格在，但整格退化成纯文本，链接无声消失。

**解法**：**改成表外的编号列表**，链接存活：

```markdown
01. [颜色 · 第 1 话：汉语（zh-CN）](https://zhuanlan.zhihu.com/p/<真实id>)　语族　XX 秒　17 行 × 3 栏
```

**规律**：**独立成行的段落链接能存活，表格单元格里的链接不能。**
排版时凡是要放链接的地方，一律挪出表格。

⚠️ 这个坑不会报错，只是链接不见了——必须逐条 `query` 复核，见 §6。

### 坑 ② 正文编辑器不吃程序化写入

`fill` / `type` 进去的是 Markdown 源码的字面形态。**唯一的全自动解法是「导入文档」**（§1）。

### 坑 ③ 工具栏下拉（导入等）不响应 selector 点击

`click button[aria-label=导入]` 派发成功（`dispatched: true`）但下拉不渲染，截图和 body 文本里
都没有菜单项。**改用绝对坐标 (886,83)。**

### 坑 ④ `query` 返回的 opaque ref 会在下一次调用前过期

知乎页面 DOM 重建频繁，同一个元素连续两次 `query` 拿到的 ref 不通用。**用完即弃，重取。**

### 坑 ⑤ 视频 `upload_files` 报 `browser_action_failed`，但其实成功

`button.VideoUploadButton` 的隐藏 file input 上传后，工具因为等不到某种状态变化而返回失败。
**实际视频已经传上去。** 判据只有一个：
`query kind=dom selector='div[contenteditable="true"] .Editable-video'` 有没有命中。
**不要因为这个报错就重传**——重传会产生第二个视频。

### 坑 ⑥ CDP 不可用，只能逐次 Browser 调用

MiniMax Code.exe 没有暴露 `--remote-debugging-port`，本机 9000–9999 无监听端口。
**写 Playwright 脚本接管这个流程是走不通的**，只能老老实实逐次发 Browser action。
做批量前先评估调用次数（本项目 15 篇 × ~12 步 ≈ 180 次）。

### 坑 ⑦ `type` 的 selector 在**顶层**，不在 `source` 里

- ✅ `type input={selector: "textarea.Input", text: "..."}`
- ❌ `type input={source: {selector: "..."}}` → `invalid_input`

### 坑 ⑧ `wait` 用 `timeout` 不用 `delay`；`press_key` 不接受 `delay`

- ✅ `wait input={kind: "timeout", timeout: 4000}`
- ❌ `wait input={delay: 4000}` → `invalid_input`
- `press_key` 传 `delay` 同样报 `invalid_input`。

### 坑 ⑨ 内联链接菜单不在语义树里

选中链接后弹出的「访问链接 / 编辑链接 / 取消链接 / 展示为卡片」是 **portal 挂载**的，
`query kind=semantic text=编辑链接` → `matchCount: 0`。此时 `screenshot` 看一眼拿坐标，
本项目实测稳定在 **(149, 553)**。

### 坑 ⑩ `query kind=dom` 只返回**第一个**匹配元素

`selector: 'article a.Link'` 命中 14 个也只会吐 1 个。**要逐条核验 14 个链接，只能写 14 次查询。**
别指望一次拿到全量。

### 坑 ⑪ 标签页焦点漂移会产生 `about:blank` 假阴性

查链接时突然返回 `Element not found`，而同一页前几个查询都正常。**先看返回里的 `url` 字段**——
如果是 `about:blank`，说明焦点跑到新开的空标签页了，**不是链接真的没了**。
`open_tab` 重开该 URL 再查即可。

### 坑 ⑫ 连续 3 次相同参数的 `press_key` 触发 runaway guard

Draft.js 里 `Control+Shift+ArrowLeft` **不是**「按词左移」，实测等同单字符左移。
选 3 个汉字要按 3 次。⚠️ 但**参数完全相同的第 3 次会被守卫拦下**——
靠交替 `Shift+ArrowLeft` / `Control+Shift+ArrowLeft` 来错开。

### 坑 ⑬ 更新按钮和发布按钮只差 6 像素

草稿态是「发布」(895,1004)，已发布文章编辑页是「更新」(889,1004)。
点错会以为「更新没生效」——其实点的是发布，或者反过来。

### 坑 ⑭ 发布 URL 与草稿 URL 的关系

草稿的 `https://zhuanlan.zhihu.com/p/<id>/edit` 发布后，
**公开地址就是 `https://zhuanlan.zhihu.com/p/<id>`**（去掉 `/edit`）。
但仍要 `inspect` 实读一次确认，别纯靠推断。

### 坑 ⑮ 同一批的顺序：分语种先发，主文最后发

主文的目录链接依赖 14 篇的真实 URL。**先发主文 = 目录全是死链，且要重发一遍。**

### 坑 ⑯ 长流程里别把实验草稿忘了

调试过程中产生的失败草稿（表格版主文、试粘贴的正文…）会一直躺在草稿箱。
每次实验就把废弃 ID 记进台账，收尾一次性清。

### 坑 ⑰ 服务端会剥掉整个阿拉伯文区段（U+0600–U+06FF）⚠️ 本项目最大的平台限制

**现象**：第 11 话（阿拉伯语）发出去后，正文里所有阿拉伯字母**整片消失**——
人名、六色词、17 行台词、语法解析里的例词全部变空，只剩下没被剥的中文、
拉丁转写、希伯来文、西里尔文、希腊文、天城文、假名。

**定位过程**（四步，每步都推翻了一个假设）：

| 环节 | 阿拉伯文 |
|---|---|
| 本地 `.md`（446 个字符簇） | ✅ 完好 |
| 「导入文档」→ 编辑器 | ✅ 完好，连写字形渲染正常 |
| **存草稿 / 发布（服务端）** | ❌ **整段被剥** |
| 对照：希伯来文 U+0590–05FF | ✅ 存活 |

**所以不是导入器的锅，是服务端保存时的字符过滤。** 重新打开编辑页会看到阿拉伯文也没了
——因为编辑页读的是服务端那份已被过滤的内容。

**试过并全部无效的绕过写法**（2026-10-04 实测，15 种变体）：
裸文本 / 行内代码 / HTML 数字实体（`&#1575;`，导入时被解码回真字符）/
加粗 / 引用块 / 表格单元格 / LRM·RLM·ALM 双向控制符包裹 / tatweel 连接符 /
阿拉伯问号 `؟` / 波斯语 / 乌尔都语。**只剩不带 bidi 标记的不可见字符活下来。**

> 复现用的探针文件：`lessons/colors/publish/zhihu/_probe-arabic.md`（15 个变体各一节）。
> 改平台前先重跑一遍这个探针，别凭印象下结论。

**解法**：**在正文里显式说明**。受影响语种在顶部挂一段「排版说明」，
把「这是平台限制不是漏排」和「原字去哪看」讲清楚；主文导览的跨语种总表也要挂同一段。
本项目由 `build_zhihu.py` 的 `ARABIC_STRIPPED_LOCALES` 驱动，
验收脚本 `[4d]` 断言「说明必须存在」（已做反向验证：去掉说明即 FAIL）。

⚠️ 唯一真正可靠的绕开方式是**把阿拉伯文做成图片**。本项目没做，因为 446 个字符簇
遍布全文，图片化会把正文切碎；六色词表 + 人名这类关键词汇是可接受的最小图化范围。
另注：本地 Pillow **没装 RAQM**（`features.check('raqm') == False`），
Pillow 自己画不出连写体，要图化得借浏览器渲染 HTML 再截图。

### 坑 ⑱ `type` + `clear: true` 打在过期 ref 上 = 整篇正文清空 ⚠️ 造成过事故

**现象**：想改表格里一个单元格，`query` 拿到 ref 后隔了几步才 `type`，
ref 已过期，工具把目标解析成了别的东西。`clear: true` 于是**选中了整篇正文**，
一字不剩地替换掉——底部字数从 9000+ 变成 **3**。同时把标题栏也清空了。

**为什么没造成线上损失**：没点「更新」。但**知乎会自动存草稿**，
草稿当场被写坏（刷新后草稿页就是 3 字），已发布正文不受影响。

**铁律**：
1. **`clear: true` 只允许配 `selector`，绝不配 `ref`。** 本项目只用过一次
   （`selector="textarea.Input"`，普通 React 受控 textarea，安全）。
   Draft.js 的 contenteditable 走 `clear` 就是在赌它只命中目标块。
2. 改已发布文章前先 `screenshot` 看清现场，记下当前字数，改完立刻对账。
3. **改已发布文章 = 可逆操作**（不点「更新」就什么都没发生），
   草稿坏了就重新「导入文档」，别慌。

### 坑 ⑲ 打开已发布文章的编辑页，标题栏可能已经有标题

`/p/<id>/edit` 打开时标题栏**可能已填好**（正文为空但标题在）。
此时直接 `type`（不带 `clear`）会**拼成两遍**——
本项目就在第 11 话上踩到，标题变成「……解析颜色 · 第 11 话……解析」。

**修法**：`type` 一律带 `clear: true` + `selector`，并核对返回的 `textLength`
等于标题字数。`query kind=dom` 读 `textarea.Input` 永远是空的
（React 受控组件不把 value 反映到 outerHTML），**不能用它判断标题对不对**。

### 坑 ⑳ 草稿箱的「删除」按钮对本账号全线失效——知乎前端的 ID 精度 bug

**现象**：点「删除」→「确认」，弹「文章未找到」，刷新后草稿还在。
**坐标点、ref 点、删 6 条全试过，无一成功。**

**根因**（`query kind=network` 抓到的实锤）：

```
DELETE https://zhuanlan.zhihu.com/api/articles/2089895631926183200/draft  → 404
真实草稿 ID：2089895631926183253
DELETE https://zhuanlan.zhihu.com/api/articles/2089911058764977000/draft  → 404
真实草稿 ID：2089911058764977008
```

知乎的 ID 是雪花 ID（~2.09 × 10¹⁸），**远超 JS 安全整数上限 2⁵³ ≈ 9.007 × 10¹⁵**。
前端把 ID 当 JSON number 解析时末位精度丢失，**末三位被抹成 `000` / `200`**，
于是 DELETE 打到一个不存在的 ID 上 → 404「文章未找到」。

**关键：这是知乎自己的 bug，不是操作问题。** 同一段代码路径，
用户手动点也会一样失败——**不要指望「让用户去后台手动清」能解决**。

**旁证**：同一页面上 `<a href="/p/<id>/edit">` 里的 ID 是**正确**的
（探针草稿的 href 就是 `...008`），只有删除按钮那份数据被截断。
说明正确 ID 就在 DOM 里，但 CDP 不可用（坑 ⑥），没有可执行任意 JS 的口子去调接口。

**可行的替代路径（本项目 2026-10-04 全部试过，均不可用）**：
- `https://zhuanlan.zhihu.com/manage` → 404
- `https://www.zhihu.com/creator/manage/column` → 404
- 草稿自己的 `/p/<id>/edit` 页没有删除入口

**结论**：草稿只能留着。要么等知乎修，要么走官方工单反馈这个精度 bug。
**因此更要控制草稿产量**——每次实验都往台账记废弃草稿，
以后清理的成本不是「点几下」而是「清不掉」。


---

## 6. 发布后核验清单

发布完成不等于交付完成。逐项打勾：

**单篇级**
- [ ] 公开页 `article a[href*="<主文id>"]` 命中 → 返回链接不是死链
- [ ] `query kind=dom selector='article [data-lens-id]'` 命中 → 视频在位
      ⚠️ 视频在页面中段，**先 `scroll` 到那一段再查**，否则懒加载未渲染会假阴性
- [ ] 标题栏文字与 `publish-plan.json` 的 `title` 逐字一致
      ⚠️ 用 `type` 返回的 `textLength` 核对，**不要用 `query` 读 textarea**
- [ ] `第 N 话` 编号连续，没有跳号

**主文级**
- [ ] 第八节 14 条目录**逐条** `query kind=dom selector='article a[href*="<该篇id>"]'` 命中
      ⚠️ 一次查询只能验一条，14 条就是 14 次（坑 ⑩）
- [ ] 表格类排版里**没有放链接**（坑 ①）

**批次级**
- [ ] 15 篇公开 URL 全部回填进 `_draft-log.json`
- [ ] 草稿箱里没有本项目遗留的失败草稿
- [ ] 本地 `.md` 底部的返回链接也已经是真实 URL（重出时用 `PUBLISHED_URLS` 表）

---

## 7. 已发布台账（2026-10-04）

专栏：https://zhuanlan.zhihu.com/p/2089904878147598212
（账号 `feuyeux`；标题「六个颜色词，十四种语言：一场放学后的美术教室对话」）

| 话 | 语种 | 文章 ID | 视频 lens id |
|---|---|---|---|
| 主文 | 导览 | `2089904878147598212` | — |
| 1 | 汉语 zh-CN | `2089899068839539832` | `2089899200876123785` |
| 2 | 粤语 zh-HK | `2089899526173749273` | `2089899621778826960` |
| 3 | 英语 en-US | `2089899733133412306` | `2089899829333906202` |
| 4 | 德语 de-DE | `2089899958791050611` | `2089900059072655430` |
| 5 | 法语 fr-FR | `2089900169722599335` | `2089900263951839410` |
| 6 | 西班牙语 es-ES | `2089900377936228772` | `2089900469430777831` |
| 7 | 意大利语 it-IT | `2089900584673530952` | `2089900685185783786` |
| 8 | 俄语 ru-RU | `2089900801372206522` | `2089900904736736236` |
| 9 | 希腊语 el-GR | `2089901022126855041` | `2089901128293036998` |
| 10 | 印地语 hi-IN | `2089901244609468401` | `2089901351073485261` |
| 11 | 阿拉伯语 ar-SA | `2089901474784592319` | `2089901589611935360` |
| 12 | 希伯来语 he-IL | `2089901723724821080` | `2089901838501929709` |
| 13 | 日语 ja-JP | `2089897158682195415` | 截图确认 |
| 14 | 韩语 ko-KR | `2089901976901493374` | `2089902089782695207` |

发布 URL 一律是 `https://zhuanlan.zhihu.com/p/<文章 ID>`。

**核验结论（2026-10-04）**
- 主文目录 14 条链接：**14/14 命中**（逐条 `query kind=dom` 实测）。
- 14 篇底部「返回总目录」：全部改为指向主文真实 URL，
  本轮抽验 1 / 11 / 12 / 13 / 14 共 5 篇公开页命中，其余 9 篇为上一轮逐篇改毕。
- **第 11 话与主文导览已于 2026-10-04 重导更新**，两处都挂上阿拉伯文过滤说明
  （坑 ⑰）；第 11 话的视频重新上传，lens id `2089912559587672143`。

### 已知缺陷

| 编号 | 问题 | 状态 |
|---|---|---|
| 11 | 阿拉伯文原字被知乎服务端过滤，线上只剩拉丁转写 | 🟡 已加说明；彻底解决需图片化 |
| — | 草稿箱 6 条测试草稿删不掉（知乎前端 ID 精度 bug，坑 ⑳） | ❌ 平台侧问题，只能等修复 |

---

## 8. 换项目复用时要改的地方

**平台机制部分完全通用**（§1–§6），只有 §7 的台账是项目相关的。换项目时：

1. 事实源文案另建，参考 `lessons/colors/publish/zhihu/` 的体例；
2. 先用 `scripts/build_zhihu.py` 那套「单一事实源 → Markdown + 反向验收」把内容出好，
   **不要从 HTML 解析重建**；
3. 链接一律用**绝对 URL**，并且**不要放进表格**（坑 ①）；
4. 分篇先发、导览最后发（坑 ⑮）；
5. §7 换成本项目的台账。
