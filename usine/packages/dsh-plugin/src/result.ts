// result.ts —— 工具面统一结果契约（17 个工具同一套 schema）。
//
// 为什么统一：dsh 按 output.schema 机检每次成功调用的返回值（additionalProperties /
// enum / required 全部强制执行，见 dsh-tools 的 assertSupportedJsonSchema + 运行时校验），
// 所以契约写在代码里就是可执行的——模型看得见、门禁拦得住、跑不偏。以前是两套：
// 13 个 argv 家族用 {exit_code, output}，usine_video_generation 用 {status, message, …}，
// 纪律文本只覆盖了其中一套（对另一套是错的）。现在一套到底。
//
// 语义三档（与 CLI 退出码口径同源，退出码本身落进 detail.exit_code 供机器读）：
// - ok      ：调用达成预期。业务上「检查通过」。
// - invalid ：用法/参数不合规——模型该改参再调，不是环境坏了。
// - failed  ：检查不过或执行失败——环境/依赖/产物问题，重试前先看 output。
//
// 纪律对应：「ok=true 且 status=ok 才是过；status=invalid 是要改参；status=failed 是没过
// 或出错；SKIP 不是 PASS」。拒绝（额度审批）不进这套契约——它在 dispatch 层被 dsh 拦掉，
// 工具体根本没跑，模型看到的是 dsh 原生的工具错误。

import type { JsonSchemaNode } from '@deepseek-ai/dsh-tools'

/** 三档状态。 */
export type UsineStatus = 'ok' | 'invalid' | 'failed'

/** 工具返回值的统一形状。 */
export interface UsineResult {
  /** true = 达成预期（只有 status='ok' 时为 true）。 */
  ok: boolean
  /** 三档状态，见 UsineStatus。 */
  status: UsineStatus
  /** 人类可读输出全文（含报错文本）。 */
  output: string
  /** 工具特有结构化补充（如 task_id、exit_code、路径与字节数）。 */
  detail?: Record<string, unknown>
}

/** 全部工具共用的 output.schema（受 dsh 强制执行，非法返回值会被 registry 拒）。 */
export const RESULT_SCHEMA: JsonSchemaNode = {
  type: 'object',
  properties: {
    ok: { type: 'boolean', description: 'true = 本次调用达成预期（只有 status=ok 时为真）' },
    status: {
      type: 'string',
      enum: ['ok', 'invalid', 'failed'],
      description: 'ok=过；invalid=用法或参数不合规（该改参再调）；failed=检查不过或执行失败',
    },
    output: { type: 'string', description: '人类可读输出全文（含报错文本）' },
    detail: { type: 'object', additionalProperties: true, description: '工具特有结构化补充（如 exit_code、task_id）' },
  },
  required: ['ok', 'status', 'output'],
  additionalProperties: false,
}

/** output.render：把结构化值摊平成模型可读文本（dsh 的 lossless-JSON 投影）。 */
export const renderResult = (_args: unknown, value: unknown) => [
  { type: 'text' as const, text: JSON.stringify(value) },
]

/** 造一个成功结果。 */
export const ok = (output: string, detail?: Record<string, unknown>): UsineResult => ({
  ok: true,
  status: 'ok',
  output,
  ...(detail === undefined ? {} : { detail }),
})

/** 造一个「用法/参数不合规」结果。 */
export const invalid = (output: string, detail?: Record<string, unknown>): UsineResult => ({
  ok: false,
  status: 'invalid',
  output,
  ...(detail === undefined ? {} : { detail }),
})

/** 造一个「检查不过或执行失败」结果。 */
export const failed = (output: string, detail?: Record<string, unknown>): UsineResult => ({
  ok: false,
  status: 'failed',
  output,
  ...(detail === undefined ? {} : { detail }),
})

/**
 * 把 CLI 口径的退出码折成三档状态——单一映射，CLI 与工具面共用。
 * 0=过；2=用法错误（改参）；1=检查不过或出错（failed）。
 */
export const fromExitCode = (
  exitCode: number,
  output: string,
  extra?: Record<string, unknown>,
): UsineResult => {
  const detail = { ...(extra ?? {}), exit_code: exitCode }
  if (exitCode === 0) return ok(output, detail)
  if (exitCode === 2) return invalid(output, detail)
  return failed(output, detail)
}
