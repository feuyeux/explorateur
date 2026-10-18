// @feuille/dsh-plugin —— feuille 的 dsh 原生智能体插件（P1 最小骨架）。
//
// Cordis 插件形状：`export const name` + `apply(ctx)`；工具经 `ctx.tools.register()`
// 注册（raw ToolDefinition——defineTool 是带校验的类型面包装，MCP 工具走的就
// 是 raw 通道，最小骨架不引入 dsh 运行时依赖）。注册随插件 fiber 销毁而注销
// （effect-based）。
//
// dsh 钉版 dsh-v0.1.7-rc.2（/Users/han/coding/deepseek-harness），升级单独裁定。
// 本文件只 import 类型（编译期擦除）+ @feuille/core（进程内原生调用——这是
// 本次迁移的核心接缝证明：无 subprocess 桥）。
import type { Context } from '@deepseek-ai/cordis'
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import { VERSION } from '@feuille/core'

export const name = 'feuille-usine'
export const inject = ['tools']

/** usine_version —— 迁移期自检工具：证明 工具注册 + 进程内 core 调用 两条接缝。 */
const usineVersion: ToolDefinition = {
  name: 'usine_version',
  description: '查询 feuille usine 视频产线核心包（@feuille/core）的版本号。只读自检工具，无副作用。',
  parameters: {
    type: 'object',
    properties: {},
    additionalProperties: false,
  },
  output: {
    schema: {
      type: 'object',
      properties: { version: { type: 'string' } },
      required: ['version'],
      additionalProperties: false,
    },
    render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
  },
  async execute() {
    // 进程内原生调用 @feuille/core（无 subprocess 桥）
    return { version: VERSION }
  },
}

export function apply(ctx: Context) {
  ctx.effect(() => ctx.tools.register(usineVersion))
}
