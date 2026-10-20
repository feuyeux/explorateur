// @feuille/dsh-plugin —— feuille 的 dsh 原生智能体插件。
//
// Cordis 插件形状：`export const name` + `export const inject` + `apply(ctx, config)`。
//
// 三条结构决定（都是 2026-10-20 架构评审后改的，改动理由写在这里，别删）：
//
// 1. **inject 只留硬依赖**（tools + systemPrompt）。approval / skills 是**可选**服务：
//    声明进 inject 等于「宿主必须提供」，宿主一缺整个插件就永不生效、工具面全空
//    且不报错（cordis 的 fiber 会一直 pending）。所以：额度审批走 dsh 自带的
//    tools/pre-execute 门（门内由 dsh-tools 用 ctx.get('approval') 取服务——上游
//    自己的写法），技能注册走 ctx.inject(['skills'], …)（服务到齐才跑，没到就跳过，
//    不影响工具面）。
//
// 2. **红线机制在 dispatch 层，不在工具体内**。见 gate.ts：submit 走
//    tools/pre-execute 瀑布返回 {kind:'ask'}，由 dsh-tools 的 serviceAsk 走
//    approval 服务（policy 优先、无服务即 deny、无 agent 即 deny、拒绝/取消/不可用
//    三种可区分理由），审计走 approval/asked + approval/decided。未获批准时工具体
//    根本不执行——工具「跑了才说不行」不算红线。
//
// 3. **工具面只有一份实现、只有一套结果契约**。main 在业务包里（CLI 与工具面共享
//    同一份 main），结果统一 {ok, status, output, detail?}（result.ts，dsh 按
//    output.schema 机检返回值）。
//
// dsh 依赖按 package.json 依赖定义接入（@deepseek-ai/* npm 发布版），升级单独裁定。
// 本文件只 import 类型（编译期擦除）+ @feuille/* 包（进程内原生调用——本次迁移的
// 核心接缝证明：无 subprocess 桥；verify/quota/video 通道除外，它们本来就是进程外程序）。
import type { Context } from '@deepseek-ai/cordis'
import type { SkillProviderControl } from '@deepseek-ai/dsh-skill'
import { FileSystemSkillProvider } from '@deepseek-ai/dsh-skill-filesystem'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import {
  DISCIPLINE_SECTION_NAME, DISCIPLINE_SECTION_ORDER, DISCIPLINE_TEXT,
} from './discipline.js'
import {
  familyTools, publishTool, quotaTool, usineRoot, usineVersion, verifyTool, videoGenerationTool,
} from './tools.js'
import { videoApprovalGate } from './gate.js'
import { TOOL_NAMES } from './toolnames.js'

export { usineRoot } from './tools.js'
/** 工具面的外部契约（智能体应当能调用的 17 个工具名）——preflight 与门禁拿它对账。 */
export { TOOL_NAMES as toolNames } from './toolnames.js'

export const name = 'feuille-usine'
// inject 只声明**硬依赖**：工具注册与 systemPrompt 分节。
// 声明了但宿主没提供的服务会让 fiber 永远 pending（插件永不生效、工具面全空且
// 不报错）——2026-10-20 评审发现 approval / skills 被写进 inject 正是这个坑：
// 宿主缺任一服务，17 个工具一起消失。approval 由 dsh-tools 在门内用 ctx.get 取，
// skills 由 ctx.inject(['skills'], …) 等到再注册。
export const inject = ['tools', 'systemPrompt']

/** 插件配置（dsh 宿主侧 config 传入）。 */
export interface Config {
  /** 发布工具显式开启（默认 false：usine_publish 不注册，发布不可达是有意设计）。 */
  publish?: boolean
}

// 结构化接缝：systemPrompt.section 的最小面（不 link harness 类型链）。
interface SystemPromptLike {
  section(s: { name: string; order: number; text: string }): () => void
}

// 结构化接缝：skills 服务的最小面（不 link harness 类型链）。
interface SkillsLike {
  registerProvider(create: (control: SkillProviderControl) => unknown): () => void
}

/**
 * 装配清单：写在宿主启动时（由 preflight 通过 FEUILLE_DSH_MANIFEST 指定路径拉取）。
 * 用途只有一个——让「插件到底挂上去了没有」变成可机械核验的事实，而不是
 * 「宿主起得来就算过」（dsh 静默吞 apply 错，宿主照常启动，工具面却全空）。
 * 没设该环境变量就不写（生产宿主不留痕）。
 */
function writeManifest(tools: string[], publish: boolean): void {
  const path = process.env.FEUILLE_DSH_MANIFEST
  if (!path) return
  try {
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, JSON.stringify({ tools, publish, loadedAt: new Date().toISOString() }, null, 2))
  } catch {
    // 清单是诊断件，写不进去不该掀翻插件装配。
  }
}

export function apply(ctx: Context, config: Config = {}) {
  // ---- 1. 纪律 systemPrompt 节：文本管「知道」，机制管「做到」 ----
  const systemPrompt = (ctx as unknown as { systemPrompt?: SystemPromptLike }).systemPrompt
  if (systemPrompt) {
    ctx.effect(() =>
      systemPrompt.section({
        name: DISCIPLINE_SECTION_NAME,
        order: DISCIPLINE_SECTION_ORDER,
        text: DISCIPLINE_TEXT,
      }))
  }

  // ---- 2. 工具注册（argv 家族 + 三条线）----
  const alwaysOn = [usineVersion, ...familyTools(), verifyTool(), quotaTool(), videoGenerationTool()]
  for (const tool of alwaysOn) {
    ctx.effect(() => ctx.tools.register(tool))
  }

  // ---- 3. 自检：注册面必须与外部契约逐字相同（少一个就当场抛，不留到对话里）----
  const actual = alwaysOn.map((t) => t.name).sort()
  const expected = [...TOOL_NAMES].sort()
  if (actual.length !== expected.length || actual.some((n, i) => n !== expected[i])) {
    throw new Error(
      `feuille-usine 工具面与契约不一致：\n  实际：${actual.join(' / ')}\n  契约：${expected.join(' / ')}\n`
      + '（契约在 src/toolnames.ts；改了工具面必须同步改契约，否则门禁与 preflight 会红）',
    )
  }

  // ---- 4. 额度红线：dispatch 层的 pre-execute 门 ----
  // 门返回 {kind:'ask'} 后由 dsh-tools 走 approval 服务；拒绝时工具体不会执行。
  ctx.effect(function* () {
    yield ctx.on('tools/pre-execute', videoApprovalGate(), { global: true })
  })

  // ---- 5. 技能资产：可选服务，宿主没装 skills 服务就整段跳过（工具面不受影响）----
  ctx.inject(['skills'], (skillCtx) => {
    const skills = (skillCtx as unknown as { skills?: SkillsLike }).skills
    if (!skills) return
    skillCtx.effect(() =>
      skills.registerProvider((control) =>
        new FileSystemSkillProvider(skillCtx, control, {
          providerName: 'feuille-usine-skills',
          includeDefaultRoots: false,
          customSkillDirs: [resolve(usineRoot(), 'skills')],
          watch: false,
        })))
  })

  // ---- 6. 发布默认不可达：工具面上根本没有这个工具，而不是「调了会报错」----
  // 工具本体经动态 import 取 @feuille/publish（playwright 是可选依赖，只有真发布
  // 路径才碰）——异步注册完成前 fiber 销毁则直接放弃。
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

  // ---- 7. 装配清单（仅 preflight 会拉；生产宿主不留痕）----
  writeManifest(actual, config.publish === true)
}
