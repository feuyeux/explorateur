// tools.ts —— dsh 工具面：feuille usine 的全部产线动词。
//
// 设计口径：
// - **argv 家族工具**：每个产线家族一个工具（usine_scene / usine_lesson / …），
//   `action` 选子命令、`argv` 是残余参数——与 feuille CLI 完全同一套口径，
//   进程内直调包 main（无 subprocess 桥），输出被捕获进结构化结果。
// - **统一结果契约**：全部工具返回同一套 {ok, status, output, detail?}（见 result.ts），
//   dsh 按 output.schema 机检返回值——契约跑不偏。CLI 退出码语义（0/1/2）折进
//   status 与 detail.exit_code，与 CLI 同口径。
// - **usine_video_generation**：额度红线**不在工具体内**——审批在 dispatch 层的
//   tools/pre-execute 门（见 gate.ts），由 dsh-tools 走 approval 服务。未获批准时
//   工具体根本不执行（模型看到的是 dsh 原生的工具错误，不是本工具的一个 status）。
// - **usine_publish**：默认**不注册**（config 显式开启才挂）——发布不可达
//   不是运行时报错，是工具面里根本没有。
// - **usine_verify / usine_quota**：门禁与额度查询是子进程步骤（vitest/
//   mmx 本来就是进程外程序），其余全在进程内。
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import { spawn } from 'node:child_process'
import crossSpawn from 'cross-spawn'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import {
  parse_scene, scene_schema, scene_draft, scene_audio, lesson,
  persona, covers, framehash, ledger, themes, VERSION,
  platform,
} from '@feuille/core'
import { checkPublishCopy } from '@feuille/copy'
import { gen_bgm } from '@feuille/bgm'
import { gen_tts, build_video, verify_sync, scan_blank } from '@feuille/karaoke'
import { audio_profile, color_contrast } from '@feuille/poetry'
import {
  fetch_fonts, assemble, render_poster, render_page, audit_charset,
  fit_diag, verify_colors, check_overlay, make_covers, measure_korean,
} from '@feuille/poster'
import { render_act_frames, assemble_storyteller } from '@feuille/storyteller'

import { runMain } from './capture.js'
import { RESULT_SCHEMA, failed, fromExitCode, invalid, ok, renderResult } from './result.js'
import { parseSubmit, submitCost, VIDEO_MODELS } from './video.js'

// ---------------------------------------------------------------------------
// 通用件
// ---------------------------------------------------------------------------

type MainFn = (argv: string[]) => Promise<number> | number

/** 造一个 argv 家族工具：action → 包内 main，argv 原样透传。 */
function argvTool(spec: {
  name: string
  description: string
  actions?: Record<string, MainFn>
  argvDoc: string
}): ToolDefinition {
  const hasActions = spec.actions !== undefined
  const properties: Record<string, unknown> = {
    argv: { type: 'array', items: { type: 'string' }, description: spec.argvDoc },
  }
  if (hasActions) {
    properties.action = {
      type: 'string',
      enum: Object.keys(spec.actions!),
      description: '子命令（与 feuille CLI 的命令名一致）',
    }
  }
  return {
    name: spec.name,
    description: spec.description,
    parameters: {
      type: 'object',
      properties,
      required: hasActions ? ['action', 'argv'] : ['argv'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    async execute(args) {
      const a = args as { action?: string; argv?: string[] }
      const argv = Array.isArray(a.argv) ? a.argv.map(String) : []
      if (!hasActions) {
        // 无 action 的工具：唯一实现就是那一个 main（actions 省略时必有一个入口）。
        const only = Object.values(spec.actions ?? {})[0]
        if (!only) return invalid('该工具没有可执行入口（实现缺陷）')
        const r = await runMain(only, argv)
        return fromExitCode(r.exit_code, r.output)
      }
      const fn = spec.actions![a.action ?? '']
      if (fn === undefined) {
        // 未知子命令 = 用法错误（CLI 同口径：退出码 2）。
        return fromExitCode(2, `未知子命令：${a.action ?? '(空)'}；可用：${Object.keys(spec.actions!).join(' / ')}\n`)
      }
      const r = await runMain(fn, argv)
      return fromExitCode(r.exit_code, r.output)
    },
  }
}

/** win32 下裸名解析成绝对路径再 spawn：CreateProcess（无 shell）只执行 .exe，
 * .cmd/.bat shim 会静默 ENOENT。解析到 shim 时按通道策略分流（见 runCapture）：
 * argv 全由代码写死的通道（verify/quota——无模型可控内容）经 cross-spawn 执行
 * shim（cmd.exe + 库级转义，无注入面）；argv 带模型可控内容的通道
 * （mcode-tools 的 --args 带用户 prompt JSON）fail-closed 并给出修法——
 * 本通道不开 shell（注入红线），与门禁预检 gate_preflight 对 standalone
 * pnpm 的要求同源。 */
function resolveSpawnCmd(cmd: string): { cmd: string; shim?: string } {
  if (process.platform !== 'win32') return { cmd }
  const found = platform.which(cmd)
  if (!found) return { cmd }
  if (/\.(cmd|bat)$/i.test(found)) return { cmd, shim: found }
  return { cmd: found }
}

/** 子进程捕获跑（verify/quota/mcode-tools 通道用；观察 signal）。 */
function runCapture(cmd: string, args: string[], opts: {
  cwd?: string
  signal?: AbortSignal
  input?: string
  /** argv 全由代码写死（无模型可控内容）——win32 上允许经 cross-spawn 执行 .cmd/.bat shim。 */
  fixedArgv?: boolean
}): Promise<{ code: number; output: string; notFound: boolean }> {
  return new Promise((res) => {
    const resolved = resolveSpawnCmd(cmd)
    if (resolved.shim && !opts.fixedArgv) {
      res({
        code: 127,
        output: `${cmd} 在 PATH 上解析到 ${resolved.shim}（.cmd/.bat shim）。`
          + `本通道的 argv 带模型可控内容，不开 shell（注入红线）：`
          + `请装 standalone 版（.exe，如 standalone mcode-tools）并确保它排在 shim 之前。\n`,
        notFound: true,
      })
      return
    }
    const doSpawn = resolved.shim ? crossSpawn : spawn
    const spawnTarget = resolved.shim ?? resolved.cmd
    let child: ReturnType<typeof spawn>
    try {
      child = doSpawn(spawnTarget, args, { cwd: opts.cwd, stdio: ['pipe', 'pipe', 'pipe'] }) as ReturnType<typeof spawn>
    } catch {
      res({ code: 127, output: `无法启动 ${cmd}\n`, notFound: true })
      return
    }
    const chunks: string[] = []
    const cap = (b: Buffer) => { chunks.push(b.toString('utf8')) }
    child.stdout?.on('data', cap)
    child.stderr?.on('data', cap)
    if (opts.input !== undefined) child.stdin?.end(opts.input)
    else child.stdin?.end()
    child.on('error', (e: NodeJS.ErrnoException) => {
      if (e.code === 'ENOENT') res({ code: 127, output: `${cmd} 不在 PATH（ENOENT）\n`, notFound: true })
      else res({ code: 126, output: `启动失败：${e.message}\n`, notFound: false })
    })
    child.on('close', (code) => {
      res({ code: code ?? 1, output: chunks.join(''), notFound: false })
    })
    const kill = () => { try { child.kill('SIGKILL') } catch { /* 已退出 */ } }
    if (opts.signal) {
      if (opts.signal.aborted) kill()
      else opts.signal.addEventListener('abort', kill, { once: true })
    }
  })
}

/** usine 工作区根：优先按 bundle 位置推（dist 上三级），再试 cwd / cwd/usine。 */
export function usineRoot(): string {
  const fromBundle = fileURLToPath(new URL('../../../', import.meta.url))
  for (const c of [fromBundle, process.cwd(), resolve(process.cwd(), 'usine')]) {
    if (existsSync(resolve(c, 'pnpm-workspace.yaml'))) return c
  }
  return fromBundle
}

// ---------------------------------------------------------------------------
// 家族工具（全量：与 CLI 路由表同覆盖面）
// ---------------------------------------------------------------------------

export const usineVersion: ToolDefinition = {
  name: 'usine_version',
  description: '查询 feuille usine 视频产线核心包（@feuille/core）的版本号。只读自检工具，无副作用。',
  parameters: { type: 'object', properties: {}, additionalProperties: false },
  output: { schema: RESULT_SCHEMA, render: renderResult },
  async execute() {
    return ok(`usine core 版本：${VERSION}`, { version: VERSION })
  },
}

/** 全家族 argv 工具（注册面与 feuille CLI 路由一一对应，publish 除外——它默认不注册）。 */
export function familyTools(): ToolDefinition[] {
  return [
    argvTool({
      name: 'usine_scene',
      description: '场景课产线（② 创意交接 → ⑤ 音频）。进程内直跑 @feuille/core；退出码 0/1/2 与 CLI 同口径。',
      actions: {
        parse: parse_scene.mainParse,
        validate: scene_schema.mainValidate,
        draft: scene_draft.mainDraft,
        tts: scene_audio.mainTts,
      },
      argvDoc: '残余参数，与 `feuille scene <子命令>` 完全一致（如 ["--out", "…/scene.json", "…/scene.md"]）',
    }),
    argvTool({
      name: 'usine_lesson',
      description: '课件就绪度（新课开坑 + ①–⑦ 七层体检，每条未完成带下一条命令）。',
      actions: { new: lesson.mainNew, doctor: lesson.mainDoctor },
      argvDoc: '残余参数，与 `feuille lesson <子命令>` 一致（如 ["<lesson_id>"]）',
    }),
    argvTool({
      name: 'usine_persona',
      description: '人设契约体检：28 人班底逐人 validatePersona + 班底不变量（有问题 → 退出码 1）。',
      actions: { validate: persona.mainValidate },
      argvDoc: '残余参数，与 `feuille persona validate` 一致（--personas 可改班底目录）',
    }),
    argvTool({
      name: 'usine_cover',
      description: '封面产线（⑦）：整页 HTML → 平台规格整图截图；check 验尺寸 + 外圈众数底色。',
      actions: { make: covers.mainMake, check: covers.mainCheck },
      argvDoc: '残余参数，与 `feuille cover make|check` 一致',
    }),
    argvTool({
      name: 'usine_framehash',
      description: '逐帧像素基线：save 采集分桶落盘，check 零漂移门禁（diff/gone → 退出码 1）。',
      actions: { save: framehash.mainSave, check: framehash.mainCheck },
      argvDoc: '残余参数，与 `feuille framehash save|check` 一致',
    }),
    argvTool({
      name: 'usine_ledger',
      description: '产物缓存账本：谁过期了、因为什么（有过期 → 退出码 1）。',
      actions: { status: ledger.mainStatus },
      argvDoc: '残余参数，与 `feuille ledger status` 一致（--root 可参数化）',
    }),
    argvTool({
      name: 'usine_theme',
      description: '主题自动匹配：话题/语种 → 5 套垂域主题推荐。',
      actions: { match: themes.main },
      argvDoc: '残余参数，与 `feuille theme match` 一致',
    }),
    argvTool({
      name: 'usine_copy',
      description: '发布词自检（⑧ 前置）：三平台标题字数/尾随空格/互动钩/置顶话术/no-hard-wrap/AI 指纹 + --facts 数字溯源。零平台流量。',
      actions: { check: checkPublishCopy.main },
      argvDoc: '残余参数，与 `feuille copy check` 一致（写完必跑 --facts facts.json；未给 --facts 数字溯源是 SKIP 不是 PASS）',
    }),
    argvTool({
      name: 'usine_bgm',
      description: '纯器乐 BGM 床生成（Google Lyria realtime，免费层 $0、出口 IP 判区）+ 实测判据（拍速反查/频段分布/床长）。key（GEMINI_API_KEY）在 explorateur/config/.env，不进仓库。',
      actions: { gen: gen_bgm.main },
      argvDoc: '残余参数，与 `feuille bgm gen` 一致（--list-providers 只探凭据不碰网络；--recheck 只重算判据）',
    }),
    argvTool({
      name: 'usine_karaoke',
      description: '词级卡拉OK成片线：tts 词级时间线 → build 状态帧渲染+组装 → verify-sync AV 同步验收 → scan-blank 白页扫描。',
      actions: {
        tts: gen_tts.main,
        build: build_video.main,
        'verify-sync': verify_sync.main,
        'scan-blank': scan_blank.main,
      },
      argvDoc: '残余参数，与 `feuille karaoke <子命令>` 一致',
    }),
    argvTool({
      name: 'usine_poetry',
      description: '实拍母版成片诊断线：audio-profile 人声段 vs 空档段 LUFS 对比（人声被盖住检测）；color-contrast 文字压实拍量化（逐季 --gate 二值判据）。',
      actions: { 'audio-profile': audio_profile.main, 'color-contrast': color_contrast.main },
      argvDoc: '残余参数，与 `feuille poetry <子命令>` 一致',
    }),
    argvTool({
      name: 'usine_poster',
      description: '海报产线（⑦ 封面基底）：字体子集抓取 / 组装 / 截图 / 字符子集门 / fit 诊断 / 四色验收 / 叠印对齐 / 封面变体 / 韩文字素测量。',
      actions: {
        'fetch-fonts': fetch_fonts.main,
        assemble: assemble.main,
        render: render_poster.main,
        'render-page': render_page.main,
        'audit-charset': audit_charset.main,
        'fit-diag': fit_diag.main,
        'verify-colors': verify_colors.main,
        'check-overlay': check_overlay.main,
        'make-covers': make_covers.main,
        'measure-korean': measure_korean.main,
      },
      argvDoc: '残余参数，与 `feuille poster <子命令>` 一致',
    }),
    argvTool({
      name: 'usine_storyteller',
      description: '评书成片线：render-frames 幕帧渲染（舞台+人物+卡拉OK字卡）→ assemble 叠化转场 + 醒木混音。',
      actions: {
        'render-frames': render_act_frames.main,
        assemble: assemble_storyteller.main,
      },
      argvDoc: '残余参数，与 `feuille storyteller <子命令>` 一致',
    }),
  ]
}

// ---------------------------------------------------------------------------
// usine_verify —— 门禁子进程（typecheck + 全量 vitest）
// ---------------------------------------------------------------------------

export function verifyTool(): ToolDefinition {
  return {
    name: 'usine_verify',
    description: '跑 usine 的 TS 门禁：`pnpm -s typecheck` 全绿后再跑全量 vitest（usine 工作区根自动定位）。只读判据不修代码；vitest 较慢（≈1 分钟），不要并发跑多个。',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    async execute(_args, exec) {
      const root = usineRoot()
      const tc = await runCapture('pnpm', ['-s', 'typecheck'], { cwd: root, signal: exec.signal, fixedArgv: true })
      const tcOut = `== pnpm -s typecheck（${root}）==\n${tc.output}`
      if (tc.notFound) return failed(tcOut, { exit_code: tc.code })
      if (tc.code !== 0) return failed(tcOut + '\ntypecheck 未过，vitest 不跑。\n', { exit_code: tc.code })
      const vt = await runCapture('pnpm', ['-s', 'vitest', 'run'], { cwd: root, signal: exec.signal, fixedArgv: true })
      const out = tcOut + `\n== pnpm -s vitest run ==\n${vt.output}`
      return fromExitCode(vt.code, out)
    },
  }
}

// ---------------------------------------------------------------------------
// usine_quota —— MiniMax 套餐额度查询（只读）
// ---------------------------------------------------------------------------

export function quotaTool(): ToolDefinition {
  return {
    name: 'usine_quota',
    description: '查 MiniMax 套餐额度（`mmx quota`，只读不烧额度）。提交视频生成前先看：额度够走 Hailuo-2.3（套餐额度），不够再考虑 H3（只扣积分）。mmx 是独立 CLI，不在 PATH 时会如实报 ENOENT。',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    async execute(_args, exec) {
      const r = await runCapture('mmx', ['quota'], { signal: exec.signal, fixedArgv: true })
      return fromExitCode(r.code, r.output)
    },
  }
}

// ---------------------------------------------------------------------------
// usine_video_generation —— 额度红线的执行侧（审批在 dispatch 层的 pre-execute 门）
// ---------------------------------------------------------------------------

export function videoGenerationTool(): ToolDefinition {
  return {
    name: 'usine_video_generation',
    description: '视频生成（母版生产，额度红线）：三条 mcode-tools 视频线（Hailuo-2.3 走套餐额度 / H3、H3-Max 只扣积分）。**submit 动作会先在 dispatch 层弹人工审批卡**（卡上展示提示词/画幅/时长/分辨率/预估消耗），未获批准时本工具根本不会执行——你会收到一条工具错误，那表示「没批准、没提交、没烧额度」，不要换参数重试试探。动作：submit（审批后提交异步任务）、query（轮询 task_id）、download（video_url 落盘）。一次生成、按画幅成对、生成后冻结，永不重复消耗。',
    parameters: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['submit', 'query', 'download'], description: 'submit=提交生成任务（需人工审批），query=轮询任务状态，download=取回落盘' },
        model: { type: 'string', enum: VIDEO_MODELS, description: 'submit/query 必填' },
        prompt: { type: 'string', description: 'submit 必填：主体/动作/场景/镜头/情绪的画面描述（≤7000 字符）' },
        duration: { type: 'integer', description: 'submit 必填：秒。Hailuo 6/10；H3 4–15；H3-Max 5–15' },
        resolution: { type: 'string', enum: ['480P', '768P', '1080P', '2K'], description: 'submit 必填' },
        ratio: { type: 'string', description: '画幅（如 16:9 / 9:16，母版按画幅成对）。H3 submit 必填，Hailuo 不需要' },
        reference_urls: { type: 'array', items: { type: 'string' }, description: 'H3 参考素材 URL（本地先 upload_temp_url；参考视频按同价另计时长费）' },
        task_id: { type: 'string', description: 'query 必填' },
        video_url: { type: 'string', description: 'download 必填（query 成功后拿到，7 天内有效）' },
        out: { type: 'string', description: 'download 必填：母版落盘路径（交付物放工作区项目目录）' },
      },
      required: ['action'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    async execute(args, exec) {
      const a = args as {
        action: string; model?: string; prompt?: string; duration?: number
        resolution?: string; ratio?: string; reference_urls?: string[]
        task_id?: string; video_url?: string; out?: string
      }

      if (a.action === 'query') {
        if (!a.model || !a.task_id) return invalid('query 需要 model + task_id')
        const r = await runCapture('mcode-tools', [
          'connector', 'call', 'connector__matrix__query_video_generation', '--args',
          JSON.stringify({ task_id: a.task_id, model: a.model }),
        ], { signal: exec.signal })
        const task_id = extractTaskId(r.output) ?? a.task_id
        return fromExitCode(r.code, r.output, { task_id })
      }

      if (a.action === 'download') {
        if (!a.video_url || !a.out) return invalid('download 需要 video_url + out')
        try {
          const { writeFile } = await import('node:fs/promises')
          const resp = await fetch(a.video_url, { signal: exec.signal })
          if (!resp.ok) return failed(`HTTP ${resp.status}`, { url: a.video_url })
          const buf = Buffer.from(await resp.arrayBuffer())
          await writeFile(a.out, buf)
          return ok(`母版落盘：${a.out}（${buf.length} 字节）`, { path: a.out, bytes: buf.length })
        } catch (e) {
          return failed(e instanceof Error ? e.message : String(e), { url: a.video_url })
        }
      }

      if (a.action !== 'submit') {
        return invalid(`未知动作：${a.action}（submit / query / download）`)
      }

      // submit 走到这里 = dispatch 层的审批门已经放行（allowed-once）。
      // 门与工具体共用 video.ts 的判定源，这里再校验一次是纵深防御：万一门被绕过
      // （宿主缺 approval 服务时门不会 ask），不合规的提交照样当场被拒。
      const parsed = parseSubmit(a)
      if (!parsed.ok) return invalid(parsed.reason)
      const { req } = parsed

      const payload: Record<string, unknown> = {
        model: req.model, prompt: req.prompt, duration: req.duration, resolution: req.resolution,
      }
      if (req.ratio) payload.ratio = req.ratio
      if (req.reference_urls?.length) payload.reference_urls = req.reference_urls
      const r = await runCapture('mcode-tools', [
        'connector', 'call', 'connector__matrix__submit_video_generation', '--args', JSON.stringify(payload),
      ], { signal: exec.signal })
      const task_id = extractTaskId(r.output)
      const detail: Record<string, unknown> = { cost: submitCost(req) }
      if (task_id) detail.task_id = task_id
      if (r.code === 0) return ok(r.output, detail)
      return failed(r.output, detail)
    },
  }
}

/** 从 mcode-tools stdout 里尽力抠 task_id（防御式：不假定回包形状）。 */
function extractTaskId(text: string): string | undefined {
  const m = text.match(/"task_id"\s*:\s*"([^"]+)"/) ?? text.match(/"id"\s*:\s*"([^"]+)"/)
  return m?.[1]
}

// ---------------------------------------------------------------------------
// usine_publish —— 默认不注册，config 显式开启才挂（发布不可达是有意设计）
// ---------------------------------------------------------------------------

export async function publishTool(): Promise<ToolDefinition> {
  const pub = await import('@feuille/publish')
  return argvTool({
    name: 'usine_publish',
    description: '平台发布（⑨，默认不可达——config 显式开启才注册）。认证与风控永远人工：只等待扫码，绝不代填凭据，绝不自动重试。',
    actions: {
      login: (argv: string[]) => (argv.length ? pub.login.login(argv) : pub.login.login()),
      douyin: pub.douyin.main,
      xhs: pub.xhs.main,
      bilibili: pub.bilibili.main,
    },
    argvDoc: '残余参数，与 `feuille publish <平台>` 一致（manifest 参数解析在 base.manifestArgs）',
  })
}
