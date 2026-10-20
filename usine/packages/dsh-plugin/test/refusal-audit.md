# Approval-gated refusal audit（已填）

审计范围：packages/dsh-plugin 登记的全部 usine_* 工具面（src/tools.ts）。全仓核对：`approval.request` 只在 videoGenerationTool 的 submit 动作出现一处（src/tools.ts）——**唯一的 approval 门控工具是 usine_video_generation**。usine_publish 的门是 config 门（`config.publish === true` 才注册——「发布不可达」红线），不是 approval 门，不进本表。usine_verify / usine_quota / 13 个 argv 家族工具均无 approval 门控。

## 2026-10-20 架构变更：审批从工具体内搬到了 dispatch 层

旧形态里，额度审批由工具体自己去 `ctx.approval` 取、自己写拒答文案、自己判 `asked-rejected` / `asked-cancelled` / `asked-unavailable`。**2026-10-20 的架构评审把这套搬走了**：

- 审批在 **dispatch 层**：`src/gate.ts` 的 pre-execute 瀑布对 `usine_video_generation` 的 `submit` 动作返回 `{kind: 'ask'}`，由 dsh-tools 自己的 serviceAsk 走 approval 服务（policy 优先；无 approval 服务即降级为 deny；无 agent 即 deny；拒绝 / 取消 / 不可用三种结论可区分）。
- 工具体**不再伸手**去要 approval 服务：它拿的是 dispatch 已经判完的结果。插件套件刻意断言「插件不去碰 ctx.approval」，就是为了防这个回退。
- 因此**拒答文案不再由插件写**——被拒绝 / 被取消 / 审批不可用时操作员看到的话，是**宿主**（dsh-tools / dsh 宿主）写的，不是本仓的代码。本表对那部分**只做声明，不做断言**。

本表因此只钉两件**本仓真的负责**的事：① 审批卡上写什么（`src/video.ts` 的 `submitReason` / `submitReasonEn`）；② 什么情况下才摆卡（`src/gate.ts`）。

## 钉版口径（钉语义不变量，不钉逐字全文）

**为什么不钉逐字全文**：逐字钉整段自由措辞，锁住的不只是行为，还有错误。2026-10-20 的实测就是实例：旧形态下拒答卡对 `rejected` / `cancelled` / `unavailable` 一律写「操作员在宿主的审批界面**拒绝**了它」，cancelled 时是假话；而当时的 `plugin.test.ts` 逐字钉住了整句，于是**测试亲手把假话钉成了契约**。改写措辞的自由度是这类文案的核心价值（它本来就要跟着操作员场景演进），被逐字钉住就等于把迭代能力交出去。

**口径**：审批卡必须同时满足下面五个不变量，测试只钉这五个不变量，**不钉句子怎么写**：

| 记号 | 不变量 | 为什么是它 |
|---|---|---|
| (a) | 点明这是「视频生成提交审批」，并说明母版一次生成后冻结 | 操作员要一眼知道这张卡批的是什么；母版纪律（一次生成、按画幅成对、生成后冻结）要写在卡上 |
| (b) | 写清模型与计费口径 | Hailuo 走 Token/M Plan 套餐额度（不烧积分）、H3 / H3 Max 只扣积分——两条账不是同一个，写混了就是额度事故 |
| (c) | 写清提示词 / 画幅 / 时长 / 分辨率 | 额度铁律要求调用前先展示提示词、画幅、时长、分辨率与预估消耗 |
| (d) | 写清预估消耗，且**与代码里的费率表同源** | 卡上写 426 积分而代码算 387，是最坏的一种不一致；费率表由 `skills/video-generation/SKILL.md` 钉版，parity 套件双向对账 |
| (e) | 参考素材的件数写清 | 带参考视频会按同价另计一份时长费，卡上不写就等于没告知 |

**不变的**：门槛条件（只有 `submit` 摆卡、只有额度工具受门控）、`config.publish === true` 才注册发布工具的红线默认值、拒答 / 取消 / 不可用三态可区分这一条由**宿主**保证（声明在本表，不在本仓断言）。

## 锚点（机器面）

下面是本表声称的**代码事实**——每条字面量必须仍然出现在所列文件里。这块围栏是合并器侧「规范同步闸」读的东西（`garage/spec_sync.py`）：候选改代码让某条锚点失效时，规范必须同批更新，否则该候选被拒绝合并并记明两个路径。围栏块与散文分家：散文给人读，围栏给机器读，「改了散文没改围栏」这种半更新会当场被复判（候选版围栏自己说错话同样违规）。

**要改措辞时**：改代码 → 同步改围栏里的字面量 → 同步改上面的分支明细。顺序反了会在合并时被拦下来，这正是这道闸的用途。

```anchors
# 规范声称的代码事实：<文件路径> <该文件里必须仍然存在的字面量>
packages/dsh-plugin/src/video.ts [视频生成提交审批] 母版生产，一次生成后冻结
packages/dsh-plugin/src/video.ts （走 Token/M Plan 套餐额度，不烧积分）
packages/dsh-plugin/src/video.ts （只扣积分，不吃套餐额度）
packages/dsh-plugin/src/video.ts 套餐额度（不烧积分）
packages/dsh-plugin/src/video.ts 预估消耗：
packages/dsh-plugin/src/video.ts 画幅：
packages/dsh-plugin/src/video.ts 参考素材：
packages/dsh-plugin/src/gate.ts kind: 'ask'
packages/dsh-plugin/src/gate.ts 不合规 → 不摆卡
packages/dsh-plugin/src/gate.ts 无 agent 即 deny
```

## 主表

| tool | approval required | 本仓负责的部分 | 钉住的不变量 | 状态 |
|------|-------------------|----------------|------------|------|
| usine_video_generation | 是——每次 submit 必须人工点头（fail-closed、单次有效） | 摆卡条件（`src/gate.ts`）+ 审批卡文案（`src/video.ts`） | (a)(b)(c)(d)(e) | 已钉版 |
| usine_publish | 否——config 门（`config.publish === true` 才注册） | 发布不可达由 config 默认值保证 | 红线默认值不可放松 | 不进本表 |

## 分支明细

### 分支 1 —— 提交不合规（invalid）：不摆卡

- 判定源：`src/video.ts` 的 `parseSubmit`（不合规 → `{ok: false, reason}`）。
- 行为：**不占用一次人工审批**。人工审批是稀缺资源，不该花在一次注定被拒的提交上。`src/gate.ts` 直接放行给工具体，由工具体回结构化的 `invalid`，模型据此改参。
- 门控条件：只有 `usine_video_generation` 的 `submit` 动作进这道判断；其余动作（query / download / 其它工具）原样放行。
- 钉版位置：`src/gate.ts` 的注释与 `plugin-parity.test.ts` 的对账。

### 分支 2 —— 提交合规：摆卡 `{kind: 'ask'}`

- 判定源：`parseSubmit` 返回 `{ok: true, req}`。
- 行为：返回 `{kind: 'ask', reason, displayReason: {en, zh}}`；`reason` 来自 `submitReason(req)`，英文版来自 `submitReasonEn(req)`（宿主按 locale 取，缺 en 会回退到空）。
- 卡上内容：(a) 标题与母版纪律、(b) 模型与计费口径、(c) 提示词/画幅/时长/分辨率、(d) 预估消耗、(e) 参考素材件数。
- 钉版位置：`src/video.ts`；数值口径由 `plugin-parity.test.ts` 与 `skills/video-generation/SKILL.md` 双向对账。

### 分支 3 —— 宿主侧的三种未获准结论（rejected / cancelled / unavailable）

- **本仓不写这句话**：三种结论的措辞由宿主（dsh-tools / dsh 宿主）给出，并且**必须可区分**——「拒绝」「取消」「结论不可用」是三件不同的事，对操作员说错事实比不说更糟。
- 本仓的义务到此为止：插件**不得**自己去取 approval、自己去判结论、自己去写拒答文案。套件刻意断言插件不去碰 `ctx.approval`（那正是要防的回退）。
- 声明（不断言）：宿主保证 policy 优先、无 approval 服务即降级为 deny、无 agent 即 deny。

## 同步纪律（2026-10-20 新立）

**改了本表覆盖的代码，必须同 commit 更新本表。** 理由与代价：这层规范是被自动化流程（RSI 合并器）消费的对象——2026-10-20 就出现过一次真实漂移：DRS 那一轮改了拒答分支 4 的文案却没有更新本表，本表仍写着分支 4「保留」并贴出旧文案，下一轮出题若把本表当规范读，会把已经改过的分支当成待办再改一遍。合并器侧有对应的一道闸（`garage/` 侧「规范同步闸」）：候选改动了本表覆盖的源文件而没有同批更新本表，该候选被拒绝合并并记明两个路径。

**存量漂移不冤判候选**：合并前就与代码对不上的锚点记成 notice（可见但不拦），只否决**本次候选造成**的漂移——否则一道失效的闸会把整条流水线卡死，而卡死的闸没人看得见。

## 改写记录

| 轮次 | 改了什么 | 依据 |
|---|---|---|
| wave-1（`refusal-card-clarity`） | 分支 1 的拒绝语 | 原语 `宿主没有 approval 服务——fail closed，未提交。` 缺 (a)(c) |
| drs-1 | 分支 4（第一版，全 outcome 同一句「拒绝」） | 原语 `审批结果：${outcome}——未提交。` 缺 (a)(c)(d) |
| wave-1（`vg_refusal_words`） | 分支 2、分支 3 的拒绝语 | 原语各缺 (a)(c)(d) |
| 2026-10-20 手工修正 | 分支 4 改为按 outcome 如实说；本表由「贴逐字全文」改为「钉语义不变量」 | 逐字钉把「cancelled 被说成拒绝」的假话钉成了契约 |
| 2026-10-20 架构评审 | 审批搬进 dispatch 层，工具体内的拒答分支整体消失；本表改为只钉「摆卡条件 + 审批卡文案」，拒答措辞改为声明宿主责任 | 审批在 dispatch 层，红线才成立（工具体内自己拿 approval = 工具已经执行过，宿主也没法按工具名否决） |
