// @feuille/dsh-plugin —— feuille 的 dsh 原生智能体插件（P6 全量工具面）。
//
// Cordis 插件形状：`export const name` + `apply(ctx)`；工具经 `ctx.tools.register()`
// 注册（raw ToolDefinition），随插件 fiber 销毁而注销（effect-based）。
//
// 红线的机制承载（文本版见 ./discipline.ts 的 systemPrompt 纪律节）：
// - video-generation：每次执行强制 approval.request()，fail-closed、单次有效；
// - publish：默认不注册（config.publish === true 才挂）——不可达不是报错。
//
// dsh 钉版 dsh-v0.1.7-rc.2（/Users/han/coding/deepseek-harness），升级单独裁定。
// 本文件只 import 类型（编译期擦除）+ @feuille/* 包（进程内原生调用——
// 本次迁移的核心接缝证明：无 subprocess 桥；verify/quota/video 通道除外，
// 它们本来就是进程外程序）。
import type { Context } from '@deepseek-ai/cordis'
import {
  DISCIPLINE_SECTION_NAME, DISCIPLINE_SECTION_ORDER, DISCIPLINE_TEXT,
} from './discipline.js'
import {
  familyTools, publishTool, quotaTool, usineVersion, verifyTool, videoGenerationTool,
} from './tools.js'

export { usineRoot } from './tools.js'

export const name = 'feuille-usine'
// inject 必须含 'approval'：videoGenerationTool 在 apply 期就取 ctx.approval，
// 真 cordis 对未声明就访问的服务抛 "cannot get property ... without inject"，
// 整个插件加载失败、17 工具面全丢（2026-10-18 dsh 宿主真跑首测抓到；vitest 的
// fakeCtx 不校验 inject，测试面永远看不见这类断点）。
export const inject = ['tools', 'systemPrompt', 'approval']

// 供测试/诊断定位 usine 工作区根（verify 工具同款逻辑）。

/** 插件配置（dsh 宿主侧 config 传入）。 */
export interface Config {
  /** 发布工具显式开启（默认 false：usine_publish 不注册，发布不可达是有意设计）。 */
  publish?: boolean
}

// 结构化接缝：systemPrompt.section 的最小面（不 link harness 类型链）。
interface SystemPromptLike {
  section(s: { name: string; order: number; text: string }): () => void
}

export function apply(ctx: Context, config: Config = {}) {
  const systemPrompt = (ctx as unknown as { systemPrompt?: SystemPromptLike }).systemPrompt
  if (systemPrompt) {
    ctx.effect(() =>
      systemPrompt.section({
        name: DISCIPLINE_SECTION_NAME,
        order: DISCIPLINE_SECTION_ORDER,
        text: DISCIPLINE_TEXT,
      }))
  }

  for (const tool of [usineVersion, ...familyTools()]) {
    ctx.effect(() => ctx.tools.register(tool))
  }
  ctx.effect(() => ctx.tools.register(verifyTool()))
  ctx.effect(() => ctx.tools.register(quotaTool()))
  ctx.effect(() => ctx.tools.register(videoGenerationTool(ctx)))

  // 发布默认不可达：工具面上根本没有这个工具，而不是「调了会报错」。
  // 工具本体经动态 import 取 @feuille/publish（playwright 是可选依赖，
  // 只有真发布路径才碰）——异步注册完成前 fiber 销毁则直接放弃。
  if (config.publish === true) {
    ctx.effect(() => {
      let disposer: (() => void) | undefined
      let settled = false
      void publishTool().then((tool) => {
        if (settled) return
        settled = true
        disposer = ctx.tools.register(tool)
      })
      return () => { settled = true; disposer?.() }
    })
  }
}
