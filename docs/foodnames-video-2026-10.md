# foodnames 视频线的 RSI 修复记录（2026-10-21）

> 这份文档记录一次**跨两条 RSI 线路**的实验：目标是把 `usine/examples/foodnames-*`
> 系列成片里量得出来的缺陷修掉，并产出新一代 `usine/examples/foodnames-ii-*`。
> 结论在最后一节，过程与证据在前。
>
> 口径提醒：本文里的「之前 / 之后」都是**同一套判据**量出来的数字；
> 判据本身见 `usine/tools/foodnames/README.md` 的「两条视频门」一节。

## 一、先把「明显的问题」变成能机检的数字

用户说的「有明显的问题」原本是观感。观感不能当验收口径，所以第一步是把它拆成
**五条可机检的缺陷**，每条配一道能跑的判据。

| 编号 | 缺陷 | 判据怎么量 | 旧 12 期实测 |
|---|---|---|---|
| **D1** | **画面上的句子不是配音念的那一句**（最重） | `check_sentence_matches.mjs`：跑真实构建器抽画面可见文字，与数据里的旁白句去空白去标点后逐词比 | **54/144 个语种-期组合不一致**（37%） |
| **D2** | 视频里没有「菜名」这个主角（词只是句首的一个 token，词形墨迹只占画面高 4.5%–13.3%） | `check_video_layout.mjs`：DOM 探针量词形盒子的实际占比 | 12 期全中 |
| **D3** | 竖屏最大空白带 26%–30% | 同上，像素层扫最大空带 | 12 期全中 |
| **D4** | 未唱到的 token 不透明度 0.18（几乎隐形） | 同上，量实际不透明度 | 12 期全中 |
| **D5** | 当前词高亮是中性灰 `rgba(44,38,32,.09)`，不在页脚图例承诺的三色里 | 同上，量实际高亮色 | 12 期全中 |
| ~~D6~~ | ~~注音对位偏移~~ | —— | **实测 0.0–1.4px，不是缺陷，被量尺子否掉** |

D1 的现场（法语第 01 期，画面 vs 配音）：

```
fr-FR  画面 "sushi sushi est un plat japonais"   配音 "Le sushi est un plat japonais"
ja-JP  画面 "茶ちゃ は 中国 から 来た"              配音 "茶は中国から来た"
```

根因在 `usine/tools/foodnames/build_episode.mjs`：为了给菜名上色，它把句子的
**第一个 token 无条件替换成词形**。句首不是那个词的语种——冠词（Le / El / Το）、
日语助词「は」、韩语助词「는」——那个 token 被吃掉，词本身若在句中再现就重复一遍。
后果是**音画不同步**：卡拉OK 按 token 逐个亮，token 数没变但内容整体错开一词。

`verify-sync` 门抓不到它——那个门只数词数，不比词。

**旧 12 期的完整基线**：版式门合计 **954 条不达标**（每期 76–83 条），句子门 **54 处**。

## 二、让两条 RSI 线路看得见这条产线

两处结构性改动（都先于跑批落地，否则 RSI 线路对这条产线**结构性不可达**）：

1. **铺开闸**（`garage/spread.py` + `garage/config/spread.json`）：原先 `tools/` 全被归进
   `other`，而 `other` 不在冷区名单 —— RSI 波次永远看不到 foodnames 这条产线。
   现在 `tools/` 是一等顶层单位，`package_priority` 里也有它。
2. **出题面**（`garage/config/roles-usine/curriculum-usine.yaml`）：TARGET MENU 加了
   G 目标（foodnames 视频线），WAVE BRIEF 带上 D1–D5 的简报，**并写明「不要侦察，
   直接出题」**——出题席的切片装不下侦察。

另外把出题席的**推理档位**从 `max` 降到 `low`，理由见下一节。

## 三、A 线（RSIAgent × garage）：出题席卡死与档位反转

### 3.1 第一波 `foodnames-video`：出题席切片被砍

出题席切片 280s，被杀时**一题都没出**（wave 状态 `safety_ceiling`）：
首响应 207s + 第二轮 74s = 281s。

修法一：切片抬到 400s（对齐 DRS 口径——同一台机器的两种口径），run ceiling
1500s → 1700s。

### 3.2 第二波 `foodnames-video2`：档位反转，19 分钟一次都没答上

第二波在 400s 切片下仍然反复 `APITimeoutError`（21:29–21:50，约 19 分钟，
出题席一次都没答上）。

按 yaml 里自己写着的规矩（「改旋钮前先跑探针」）跑了 `garage/probe_curriculum_effort.py`
——同一份**当前**出题面（24067 字符 system + 8412 字符 user）、同一批字节、同一个网关：

| effort | 结果 |
|---|---|
| `low` | **7.2s 答出**（prompt 7411 / completion 1883，正文 7471 字），且答的是「target G, D1 primary + D2–D5 fix direction」 |
| `max` | **200s 内没有答案**（TimeoutError） |

也就是说 2026-10-19 那次「max 比 medium 快」的测量**已经反转**——不是「低档思考更久」
那种直觉，而是「max 这一档现在根本不答」。于是出题席改到 `low`。

### 3.3 第三波 `foodnames-video3`：出题席一击命中，Actor 差一轮没写完收尾

- 21:53:23 出题席一次答出（in=7664 / out=2112），并写出 `episodes/ep001/project.md`；
- 该 project 的关键段落（逐字）：
  - D1 的病灶与修法方向：「build_episode.mjs currently makes the food name the hero token
    by REPLACING the first sentence token with the word form … FIX DIRECTION: give the word
    its colour/highlight on the token that really IS the word … never change the token
    sequence itself」；
  - **可检查性拆分**：「the gates for D2-D5 … need a RENDERED episode which this guest
    cannot produce … do NOT go looking for a rendered-frame gate - it does not exist here.
    D1 is the only part with a runnable gate, and it must pass」；
  - 验收顺序：`check_sentence_matches.mjs --all` → exit 0；`pnpm verify` → exit 0。
- Actor 随后在 guest 里逐个语种算出「句子里哪个 token 才是那个词」，改好构建器、
  抽出共享判定源 `hero_token.mjs`、写完回归测试 `sentence-tokens.test.mjs`。
- **22:03:53 撞上 Actor 席的 580s 切片上限被杀**：第 38 轮迭代，差一轮没写完收尾，
  整波零产出（`memory_bytes: 0`、`projects: 0`）。

### 3.4 第四次修：Actor 席切片 580s → 950s（切片是天花板不是地板）

`actor-usine.yaml` 自己声明 `wall_clock_secs: 950s`，而计划里的 580s 才是真正的约束
（`apply_slices` 只收紧不放松）——**两个口径必须对齐，否则「计划」就是假账**。
现在计划、声明、生效三处同数（950），run ceiling 1700 → 2050s。

### 3.5 第四次波 `foodnames-video4`：还是差一口气——Actor 在**自建渲染器**

950s 切片下，Actor 又被砍（22:29:56，第 35 轮迭代）。读它的最后六轮才发现真因：
**它不是在写代码，它在 guest 里搭浏览器渲染**（iter 36 写 `fn_drive.py`、
iter 37 跑它、iter 38 改 `--formats` 参数、iter 39 再跑）——为了**验证** D2–D5。

而题面里明明写着「guest 里量不到 D2–D5，别去找不存在的门」。

**教训**：题面给了「结论」（D2–D5 量不到），但没给「上界」（不许自建渲染器）。
Actor 想自证，于是把切片烧在搭渲染器上。这正是「**上界必须写进 brief**」那条：
切片吸收不了无界的任务。

修法：WAVE BRIEF 里加三条**上界**（2026-10-21 实测写进 `curriculum-usine.yaml`）：

1. **不许自建渲染器**（不许写 driver、不许拉 headless Chrome 去验 D2–D5）——
   D2–D5 是合并后由工作区主人验的，Actor 的活是让 CSS/标记**达到 brief 里的数字**，
   并在报告里写清每处改动满足哪个数字；
2. **门禁跑法有上界**：`check_sentence_matches.mjs --all` 最多两次（改前一次、改后一次），
   `pnpm verify` 最多一次——重跑同一道门不是新证据（实测一次 94s、另一次 158s，
   四次就吃掉三分之一切片）；
3. **交付物有上界**：`tools/foodnames/` 下最多三个文件改动（构建器、样式表、一个测试文件）。

### 3.6 第五波 `foodnames-video5`：**落地**（真提交）

出题席 22:43:07 交卷（网关超时拖了 9 分钟，`infra_pause_secs: 520`，实际作答只用 20.5s），
题面把三条上界原样带进去了（`NO SELF-BUILT RENDERER` / `BOUND THE GATE RUNS` /
`AT MOST THREE FILES`），项目 id 是 `foodnames-d1-hero`。

Actor 席这次**没有自建渲染器**，改成按数据普查 + 按数字施工：

- 逐个语种算出「句子里哪个 token 才是那个词」（fr / es / el 命中 index 1，其余 index 0）；
- 新增 `wordSpan()`：整词匹配 → 逐字符流匹配（容忍阿拉伯语定冠词 `ال`，允许词续在 token 内部）；
- **句子 token 序列一个不动**，只给定位到的那一段上色；
- 词形升成独立元素 `.hero`，与 `.stage > .sentence` 分开；
- CSS：` .tok.dim` 0.18 → 0.45；`.tok.cur.kv/.kc/.kt` 取品牌三色；
- `video_script.js`：对 `.hero` 二分拟合字号，卡拉OK 改为按句子 token 逐个上状态。

22:59 Actor 席收工，23:04 验证席出 **PASS**，23:06 波次完成，合并成**真提交**：

```
6985542 theatre(wave-1): accept ep001 (foodnames-d1-hero)
01da48c theatre-memory(wave-1): snapshot the wave's memory tree
tag: theatre/wave-1
```

落地后本地复验：**句子门 144/144 逐词一致，退出码 0**（原 54 处不一致）；
版式门（DOM 层）**12 期 0 条不达标**（原 954 条）。

波次还留下了 4 个记忆件（`garage/memory-snapshots/wave-001/`），其中 `project_foodnames.md`
把病灶抽成了可复用的类别（「任何卡拉OK句子行都会犯这个错」），并给出两条实测更正——
下面那条就是它抓出来的。

## 三之二、合并带进来的下游回归：韩语补丁（工作区主人抓到的）

波次落地后跑完整产线，第 12 步 `poster audit-charset` **六期全红**：

```
PATCH-RULE BINDING PROBLEMS:
  orphan rule .kC2A4 is defined but worn by no glyph
```

**病因**：波次把韩语在视频侧改成了 `.cv` 融合渐变，理由写在代码注释里——
「补丁类 `.k####` 的 background-position 是按**海报**字号实测的；视频的主角词被拟合到另一个
字号，补丁必然错位 → 视频一律走 `.cv`」。

**这个前提是错的。** 补丁用的是**百分比**定位：

```css
.kC2A4 { background-position: 0.0% 100.0%, 0 0; background-size: 100.0% 38.7%, 100% 100%; }
```

而测量页自己写着「（advance × line-height），**任意 font-size 可迁移**」
（`packages/poster/src/measure_korean.ts`）。所以「字号变了补丁就错位」不成立。

**代价有两处，都很实**：

1. 注入 `video_src.html` 的 `.k####` 规则变成「无人穿戴的孤儿规则」，
   `poster audit-charset` 当场红，**整条产线在第 12 步停住**——12 期一期都出不来；
2. 韩语丢掉页脚图例承诺的**元音/辅音分色**（整词只剩一条对角渐变），与图例自相矛盾。

**修法**：视频侧继续用实测补丁，`.cv` 只留给数据里显式声明的**融合音节**
（`ko_fused_syllables`，那才是没有补丁可用的场合）。另外把 `.ksyl` 的 `line-height` 留回
**1.28**——补丁量在「advance × 1.28 行高」的盒子上，行高一改墨迹在盒里的相对位置就变
（字号变了没关系，百分比会跟着缩放）。

**这一条是本轮最值钱的方法论**：合并门禁管不到 `tools/`（`vitest.config.ts` 的 include 只有
`packages/*/test/**/*.test.ts`），所以「波次说它修好了」和「产线还能跑」是两件事。
**只有把整条产线真跑一遍，才知道合并带进来了什么。**

## 三之三、guest 里那道结构门是**环境性红**（量到的不是缺陷）

波次日志里 Actor 反复撞同一道门：`packages/gate/test/layout.test.ts` 报

```
仓库根多了 ["AppData","bin","evolution_project","work"]
```

查下来：guest 的 seed 是「把 **usine 前缀**的 git-archive 解到 `/home/user`」，于是
`packages/gate/test/layout.test.ts` 算出来的「仓库根」= `/home/user` = **HOME**，
里面那四个目录是 **harness 自己的**（`bin` / `work` 是建机时的，`AppData` 是
Windows 版 Node 跑 vitest 时自己长出来的）。

也就是说：这道门在 guest 里**量错了目录**——它把 harness 的家当当成了「内容产物」。
真仓库里它是绿的（仓库根只有 `usine/ garage/ garage-ii/ theatre-ii/ théâtre/ config/ docs/`）。

**代价**：Actor 拿它当自己的验收信号，绕着它耗掉十几次迭代；验证席也因为 `AppData`
还在，连着 5 轮跑同一条命令（重复确认不是新证据）。

**处置**：本轮不动这道门——它是「人手工维护的白名单」，动它的收益（省几轮迭代）远小于
风险（把一条故意的门改成"对 guest 放行"）。记在这里，作为后续单独一件事。

## 四、B 线（harness2 × garage-ii）：它能改什么、改不到什么



### 4.1 这一格量的是什么

`garage-ii/bench_usine.py` 加了 `foodnames-scene` 一格，判据是两条**结构无关**的
静态事实（不认 class 名、不认 DOM 形状）：

1. 有没有一个元素的可见文字**恰好等于**那句旁白；
2. 词形有没有**独立于**那句话成元素（「词只是句首的一个 token」不算）。

夹具直接读产线的数据文件（`tools/foodnames/data/ep01-sushi.json`），不另抄一份——
抄一份就会漂，漂了的夹具会让「判据失败」变成「夹具过期」。

这一格量的是**harness 有没有把这条产线的 house rule 教给智能体**：基准 harness 的
`skills/` 里没有 foodnames 手册，所以智能体不知道「词是主角」「旁白句不许被改写」。

### 4.2 B 线改不到已交付的成片（这一条必须讲清）

harness2 演化的是 **harness 树**（systemprompt / guardrails / skills），也就是
「智能体现场怎么搭一个场景」。而已交付的 12 期成片是 **`build_episode.mjs` 跑出来的
代码产物**——B 线的杠杆够不着它。

所以两条线的分工是：

- **A 线改记忆 + 改仓库代码** → 能直接改掉已交付成片的生成方式；
- **B 线改 harness** → 改的是「智能体现场搭出来的场景 HTML」，
  要落到已交付成片上，还得有人把 harness 里的版式知识搬进
  `build_episode.mjs` / `templates/video_style.css`。

这不是「B 线没用」，是**两条线的杠杆不一样**，报告里不许含糊。

## 五、跑批过程中修掉的两个真缺陷

### 5.1 B 线：相对 run root 会让一次 rollout 静默死掉（`garage-ii/usine_adapter.py`）

`--root` 传相对路径时，argv 里传给 `dsh_run.mjs` 的全是相对路径，而**子进程的 cwd 是
workspace**（不是发起进程的工作目录）——任务文件被解析到
`workspace\..\garage-ii-result\..`，读不到，rollout 当场死。

症状很有欺骗性：臂记录里写的是**「判据跑不成（不是零分）」**，而 run 目录里多出一层
同名嵌套目录（`events.jsonl` 落在里面），看起来像「模型没干活」。

修法：run root 在适配层构造时就 `resolve()` 成绝对路径；离线自检
（`garage-ii/smoke_dsh_bridge.py` 的 `[6b]`）钉住「传给 `dsh_run.mjs` 的路径全是绝对的」。

### 5.2 B 线：repeat 相位与 sweep 相位用的不是同一把锁

`_phase_sweep` 与 `_phase_reselect` 的锁在 `<root>/adapt/.sweep.lock`，
而 `_phase_repeat` 的锁在 `<root>/.sweep.lock`——**两个不同的文件**。
锁的本意是「同一个 root 上不许同时跑两个跑批」（产物会互相覆盖而且不报错），
现在两个相位各锁各的，等于没锁到同一件事上。

## 六、结论

（待填：见最后一节「结论与交付」）
