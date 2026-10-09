---
name: multilingual-video-publishing
description: >
  Publish one video batch to Douyin, Xiaohongshu (xhs) and Bilibili via the
  feuille Playwright publishers, with a collection where the platform supports
  one and honest fallbacks where it does not. Use when taking finished video
  deliverables live — from either production line (karaoke-video or
  multilingual-video-poetry) — when building a Douyin collection, when
  Bilibili collection or upload form controls seem unreachable, when a publish
  batch reports success but the work must be verified in the manage list, or
  when routing a publish run through feuille's manifest and CLI layer. Also
  use when a publish script must not guess asset filenames or platform
  limits. Not for writing the publishing copy (that is publish-copy) and not
  for producing the video.
---

# 多语种成片发布（抖音 / 小红书 / B站）

把已完成的成片批量投出去，并**如实报告哪些做得到、哪些做不到**。

参考实现见 `assets/example/`（24 条 = 12 语种 × 横竖两版，源文件已归档）。
底层是 `src/feuille/publish/`（Playwright + 系统 Chrome + 持久 profile），
**不是 Browser 工具**——两者的登录态、profile、判据体系都不一样，不要混用。

## 前置输入契约

开工前必须拿到这 4 条。**缺哪条先问哪条**。

| # | 必须明确 | 缺了会怎样 |
|---|---|---|
| 1 | **成片已在盘**，且命名体系已 `ls` 核对过 | `build_manifest` 的存在性闸门会拦下全批——**不要为了让它过而伪造路径** |
| 2 | 封面文件同样在盘 | 同上；封面序号体系常与成片不同 |
| 3 | 发布词从哪来 | 指向 `publish-copy` 的产出，或用户自备；**本 skill 不写文案** |
| 4 | 标题/正文超限、正则等对外责任项的用户拍板值 | 缺省即带病发布——纪律 19，宁可整条不发 |

清单组装**没有 CLI 叶子**——`feuille.manifest.build_manifest` 吃的是带闭包的
plans 契约（video / cover 是函数不是路径），只能从项目脚本组装：参考
`assets/example/plans.py`（组装 plans → `build_manifest` 落盘），再用本 skill 的
`scripts/check_plan.py` 做零流量自检。

## 边界

**本 skill 只做「投递」，不碰内容**：发作品、建合集、回合列表核验。两条产线的成片都吃——`karaoke-video` 的海报驱动成片、`multilingual-video-poetry` 的实拍驱动成片。

唯一权威判据是**回作品管理列表核验到这条作品**；脚本自报与退出码都不算证据。

**不做 / 转交**：

- 写发布词/标题/话题标签 → `publish-copy`
- 生产成片（三条线都转）→ `karaoke-video`（单卡片）/ `storyteller-video`（多幕评书）/ `multilingual-video-poetry`（实拍驱动）
- 做海报 → `one-page-poster`

## 代码归属

拥有模块：publish

`publish`（发布器本体：`base` / `login` / `douyin` / `xhs` / `bilibili` / `collections` / `veriflive`）是本 skill 名下唯一的模块；`manifest` 与 `metrics` 在 **library**（`lesson-scene` 也要用），本 skill 跨用、不拥有。事实源见 `usine/ownership.json`，由 `verify_skills.py` 与本段双向机检。

`publish/` 对包内其他模块**零依赖**——它自成一体。

## 一条都不能省的顺序

```
文案单一事实源 → 素材存在性前置校验 → 平台清单 → 发作品 → 建合集 → 回列表核验
```

**先发作品再建合集。** 抖音的合集创建页**只列已发布作品**，作品还没发时
面板是空的，什么都挂不上。合集不是「发布前的准备」，是发布之后的一步。

## 平台能力不对等——先查再承诺

| | 作品发布 | 合集 | 备注 |
|---|---|---|---|
| 抖音 | ✅ | ✅ 全流程支持 | 标题 ≤30 字，正文末尾**必须留尾随空格** |
| 小红书 | ✅（像素探测发布键 + 封面硬闸门 + 风控停等，随 yiyezhiqiu 实测整链搬运；`publish xhs` 有 CLI 叶子） | ❌ **未实现**（`collections.py` 只有抖音全流程；源项目的小红书只有逐条「选择合集」链路，未随蒸馏搬运） | 草稿箱计数**不是**判据（编辑即自动存草稿） |
| B站 | ✅ | ❌ **需创作中心 Lv2** | 分区与创作声明是必填闸门，选不中就整条不发 |

⚠️ **B 站合集是账号等级门槛，不是配置问题。** 等级不够时编辑页的
「加入合集」是灰字、**没有任何可点控件**，合集管理页 404 或重定向。
遇到这种情况**不要绕、不要硬闯、不要假装能做**——如实告诉用户本批
只裸投稿，合集等升到 Lv2 再补挂。这是本skill 最重要的一条。

## 平台改版与选择器纪律

抖音合集那次「挂不进去」的三层根因（[references/platform-capabilities.md](references/platform-capabilities.md) §2b）
全是**写死的实测值**：绝对坐标常量、文本过滤词、把正常分页当故障。纪律沉淀：

1. **探针只读不点，结论必须沉淀**（纪律 14）：重摸 DOM 的结论写进
   `references/platform-capabilities.md`，带验证方式与日期——能复用的只有结论，不是探针代码。
2. **几何量必须相对视口**：选择器里不许出现「x < 1500」这类绝对坐标，viewport 一换就全灭
   （§2b 坑①）。非相对不可的量，注释里必须带「实测日期 + 视口条件」锚。
3. **文本过滤词 = 静默漏挂源**（§2b 坑②）：面板候选一律「未添加的全返回」，数量核对交给
   调用方——JS 里 `includes(项目词)` 会把不含关键词的条目静默吞掉。
4. **跨项目复用前先用探针重摸**：上一项目实测的常量，在下一个项目一律当作未验证。

## 素材命名：让存在性校验替你抓错

`build_manifest` 会逐条校验视频与封面**真实在盘**，这是最便宜的一道闸门——
比发到一半才发现文件不存在便宜得多。**不要在脚本里绕开它，
更不要为了「让它过」而伪造路径。**

实测踩过的两个坑（都被这道闸门当场抓住）：

- **成片与封面的命名体系不同**：成片是 `竖版四季_俄语.mp4`（无序号、用中文语种名），
  封面是 `13_竖版_中文.png`（有序号）。**封面序号是全局连续的**，
  横版 01–12、竖版 13–24，**不是每个版式各自从 01 重开**。
  猜成 locale（`ru-RU`）或猜成按版式重排，全批 24 条都会被拦下。

**规则：先 `ls` 看真实命名，再写映射。** 凭「看起来应该是这样」拼路径
在这道闸门前必被拦。

## 发布设置是责任项，不能替用户默认

分区、创作声明、合集、可见性这类字段**有实际对外责任**，必须用户明确拍板
（纪律 19）。宁可整条不发，也不带病发布——两个发布器都内置了这道闸门：
必填项选不中就中止，封面没换上就中止。

认证与风控一律人工（纪律 21）：扫码、验证码**只等待不代填**，
风控**停下不自动重试**。

## 判据：退出码与脚本自报都不算证据

**唯一权威判据是回作品管理列表核验到这条作品。**

- 脚本说成功 ≠ 成功；`click` 的 `verified` 恒为 false；
- **草稿箱计数不是判据**——小红书在编辑过程中就自动存草稿，
  发布成功后草稿不清理，计数与成功**没有对应关系**。
  照它判会把成功报成失败，进而触发重发（那会产生真的重复作品）。

### 核验要用**服务端过滤**，不要靠滚屏读列表

管理页是懒加载 + 分页，滚屏读全文会漏——实测同一批稿件两次核验
分别报「缺中文+日语」和「缺中文+德语」，而稿件时间戳是连续的。

**假阴性的危害和假阳性一样大**：都会导致重发已发过的稿件。

```
用平台的搜索框逐条查标题 → 服务端过滤，不依赖客户端渲染完整
比对前归一化（去 harakat 元音符号、去空白、小写）——平台会做码位归一
```

**同一份数据两次跑出不同的缺失名单，而数据没变——先怀疑判据，不怀疑数据。**

截图 > 像素 > 脚本自报。只有**作品管理页缩略图里能看见文字**才算封面生效。

## 长任务会被打断，靠磁盘接力

12+ 条的批次是小时级的，不要指望一个进程跑完。**每条的结果立刻落
`result JSON`**，被中断时从它读续跑点。重跑要按 `no` 过滤，
不要从第 1 条重来——已发出的会变成重复作品。

## 交付前自检

1. 清单 `problems` 为空（素材齐、标题不超限）
2. 两平台的作品数与清单条数一致
3. 抖音合集内作品数 == 12（**回合集详情页读「总集数」，不看脚本自报**）
4. B 站：分区与创作声明是用户拍板的值，**没替用户勾任何对外声明**
5. 说不清的部分**已经如实说明**，没有拿「大概可以」糊过去
6. 本批用到的平台能力条目**没过保质期**：`references/platform-capabilities.md` 每条结论都带验证方式与日期——跨项目复用、或平台改版风声后，先用探针重摸再承诺（选择器纪律第 4 条）

## 手册与代码

- `docs/publish-playbook.md` — 32 条坑、每步判据、三条元规则
- `docs/publish-lessons.md` — 各平台实测踩坑与**已排除的嫌疑**
- `src/feuille/publish/` — 发布器本体
- `assets/example/plans.py` / `go_douyin.py` — 本 skill 的可跑实现，见该目录 `README.md`