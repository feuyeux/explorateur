// gate.ts —— 额度红线的原生承载：tools/pre-execute 瀑布 + {kind:'ask'}。
//
// 为什么不写在工具体内：dsh 的审批位在 **dispatch 层**。pre-execute 瀑布返回 ask，
// 由 dsh-tools 自己的 serviceAsk 走 approval 服务（policy 优先、无 approval 服务即
// 降级为 deny、无 agent 即 deny、拒绝/取消/不可用三种可区分的拒绝理由），审计走
// approval/asked + approval/decided 事件对。
//
// 写在工具体内的后果（本文件存在的理由）：「拒绝」会退化成「工具跑完了、返回一句
// status」——红线在 dispatch 层就不成立了（工具已经执行过），宿主也没法按工具名
// 否决（宿主唯一能挂否决策略的接缝就是 pre-execute），审计链断在工具体里。
//
// 门只管一件事：**该不该问、问什么**。合不合法、花多少、卡上写什么，都在 video.ts
// （与工具体共用的唯一判定源）。不合规的提交不占用一次人工审批——放行给工具体，
// 由它回结构化的 invalid。
import type { PreToolDecision, ToolExecution } from '@deepseek-ai/dsh-tools'

import { parseSubmit, submitReason, submitReasonEn } from './video.js'

/** 受门控的工具名。 */
export const GATED_TOOL = 'usine_video_generation'

/** pre-execute 监听器的形状（cordis 事件面，结构化最小面）。 */
export type GateListener = (
  exec: ToolExecution,
  next: () => Promise<PreToolDecision>,
) => Promise<PreToolDecision>

/**
 * 造额度审批门：只对 `usine_video_generation` 的 `submit` 动作摆卡。
 * 其余调用（query / download / 其他工具）原样放行。
 */
export function videoApprovalGate(): GateListener {
  return async (exec, next) => {
    if (exec.name !== GATED_TOOL) return next()
    const args = exec.arguments as { action?: string } | undefined
    if (args?.action !== 'submit') return next()
    const parsed = parseSubmit(exec.arguments)
    // 不合规 → 不摆卡：人工审批是稀缺资源，不该花在一次注定被拒的提交上。
    // 放行给工具体，由它回结构化的 invalid（status=invalid，模型据此改参）。
    if (!parsed.ok) return next()
    const reason = submitReason(parsed.req)
    return {
      kind: 'ask',
      reason,
      displayReason: { en: submitReasonEn(parsed.req), zh: reason },
    }
  }
}
