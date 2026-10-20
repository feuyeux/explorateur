# Approval-gated refusal audit（已填）

审计范围：packages/dsh-plugin 登记的全部 usine_* 工具面（src/tools.ts）。全仓核对：
`approval.request` 只在 videoGenerationTool 的 submit 动作出现一处（src/tools.ts）——
**唯一的 approval 门控工具是 usine_video_generation**。usine_publish 的门是 config 门
（`config.publish === true` 才注册——「发布不可达」红线），不是 approval 门，不进本表。
usine_verify / usine_quota / 13 个 argv 家族工具均无 approval 门控。

审批缺席/未获得时操作员可见的拒绝语按分支共 4 条，逐条对照标准 (a)(b)(c) 核对；
主表按模板一行一个门控工具，分支明细在表后。

| tool | approval required | current refusal wording | names the tool | names the missing approval | says how to grant or retry | action taken |
|------|-------------------|-------------------------|----------------|----------------------------|----------------------------|--------------|
| usine_video_generation | 是——每次 submit 必须人工点头（fail-closed、单次有效） | `usine_video_generation 的 submit 已拒绝——调用所需的 approval 审批未获得（宿主没有 approval 服务）；fail closed，未提交。要过这道门：在带 approval 服务的宿主里重新发起本次调用，审批卡会再次摆出，人工点头（allowed-once）后才提交。` + 审批卡 reason | 是 | 是（调用所需的 approval 审批未获得） | 是（带 approval 服务的宿主里重新发起本次调用，人工点头 allowed-once） | 已改写（原语缺 (a)(c)，见改写记录），pins 在 plugin.test.ts |

## 分支明细（同一 submit 路径的其余 3 条拒绝语；分支2/3 本 wave 已改写，分支4 保留）

- **分支2（无 agent 执行上下文）**：`usine_video_generation 的 submit 已拒绝——本次调用没有 agent 执行上下文，所需的 approval 审批无法请求（审批卡需要它才能摆出）；fail closed，未提交。要过这道门：在提供 agent 执行上下文的宿主里重新发起本次调用，审批卡会再次摆出，人工点头（allowed-once）后才提交。注意：每一次消耗额度的 submit 都要单独一次人工点头，此前给过的许可（例如「你直接跑」）不会免除之后这次 approval。` + reason
  —— 动作：**已改写**（原语：`无 agent 执行上下文，approval 不可请求——fail closed，未提交。` + reason）。
  判读：(a) 是（字面 `usine_video_generation`）；(b) 是（`所需的 approval 审批无法请求`）；(c) 是（在提供 agent 执行上下文的宿主里重新发起本次调用，人工点头 allowed-once；并注明每次 submit 各需一次点头，「你直接跑」不免除）。
  status（asked-unavailable）、门控条件、审批卡 reason 与 composition（message + reason）均未改；pins 在 plugin.test.ts。
- **分支3（approval.request 抛错）**：`审批请求失败（<错误>）——usine_video_generation 的 submit 所需的 approval 审批没有拿到；fail closed，未提交。要过这道门：在 approval 服务可用、并且提供 agent 执行上下文的宿主里重新发起本次调用，审批卡会再次摆出，人工点头（allowed-once）后才提交。注意：每一次消耗额度的 submit 都要单独一次人工点头，此前给过的许可（例如「你直接跑」）不会免除之后这次 approval。` + reason
  —— 动作：**已改写**（原语：`审批请求失败（<错误>）——fail closed，未提交。` + reason）。
  判读：(a) 是（字面 `usine_video_generation`）；(b) 是（`所需的 approval 审批没有拿到`）；(c) 是（在 approval 服务可用且提供 agent 执行上下文的宿主里重新发起本次调用，人工点头 allowed-once；并注明每次 submit 各需一次点头，「你直接跑」不免除）。
  动态错误文本仍原样代入 `审批请求失败（${error}）`；status（asked-unavailable）、门控条件、审批卡 reason 与 composition（message + reason）均未改；pins 在 plugin.test.ts。
- **分支4（审批被拒/取消）**：`审批结果：${outcome}——未提交。` + reason
  —— (b) 最接近标准（结果值 rejected 即「审批未授予」），(a) 缺字面工具名（reason 卡有
  「[视频生成提交审批]」标题）、(c) 无指引；plugin-parity.test.ts 已逐字钉 `审批结果：rejected`，保留原文。

## 改写记录（项目步骤 2）

原分支1拒绝语（改前）：`宿主没有 approval 服务——fail closed，未提交。`
—— (a) 无字面工具名（reason 卡只有「视频生成提交审批」标题）；(c) 无授予/重试方式 →
四条中最差、且正好是「approval 缺席」的规范拒绝语，故改写为上表措辞：三点全中。
**改动仅这一条 message 字符串**：status（asked-unavailable）、门控条件、审批卡 reason、
其余三条分支一字未动——改前被拒的调用照旧被拒，改前放行的调用照旧放行；
usine 工具面/schema/校验/控制流零改动。
（该记录描述的是**上一 wave**：当时只改分支1，其余三条保留。本 wave 沿同一标准把分支2、分支3 也改写为三点全中，见上方分支明细；分支1、分支4 与主表未再变动。）
