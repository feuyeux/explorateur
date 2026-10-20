// plugin.test.ts — dsh 插件的正面证据 + 红线机制验收。
//
// 测试吃的是**构建产物** dist/index.mjs（dsh 宿主实际加载的那个文件），不是
// TS 源——整条链（esbuild 打包 + external 解析 + 插件形状 + 工具注册 +
// 进程内 main 调用 + dispatch 层审批门）一次验证。
//
// 装配侧的证据在**真宿主**里，不在这个文件里：`pnpm --filter @feuille/dsh-plugin
// preflight` 跑四道零 LLM 机械检查（产物自足 / dsh 钉版一致 / 宿主起得来 /
// 插件真的挂上且工具面逐字相符）——见 packages/dsh-plugin/ask.mjs 与
// docs/dsh.md §8。vitest 这一层结构上**测不到**「宿主到底有没有某个服务」
// （fakeCtx 不做服务解析），所以那条线归 preflight 与真宿主实录管。
//
// 红线测试是本套件的主角：video-generation 的 submit 必须在 **dispatch 层**
// 被 tools/pre-execute 门拦下（返回 ask），合规清单上墙；不合规的提交不占用
// 一次人工审批；publish 默认连工具都不存在。
import { afterEach, describe, expect, it, vi } from "vitest"
import { Context } from "@deepseek-ai/cordis"
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

interface Registered {
  name: string
  description: string
  parameters: Record<string, unknown>
  output: { schema: Record<string, unknown>; render: (args: unknown, value: unknown) => unknown[] }
  execute: (args: unknown, exec: unknown) => Promise<unknown>
}

interface SectionRecord { name: string; order: number; text: string }

/** pre-execute 门返回的决策（dsh-tools 的 PreToolDecision 形状）。 */
interface GateDecision {
  kind: "allow" | "deny" | "cancel" | "ask"
  reason?: string
  displayReason?: { en: string; zh?: string }
}

/**
 * 最小假 Cordis ctx：effect（普通与 generator 两种形态）+ tools.register +
 * systemPrompt.section + on（事件监听）+ inject（可选服务）。
 *
 * 刻意**不提供** approval 服务：额度审批不再由工具体内自己去取——它在 dispatch 层
 * 由 dsh-tools 通过 ctx.get('approval') 取（无服务即降级为 deny）。插件若再伸手去
 * ctx.approval，这套件就会炸（那正是我们要防的回退）。
 */
function fakeCtx() {
  const registered: Registered[] = []
  const sections: SectionRecord[] = []
  const listeners = new Map<string, Array<(...args: any[]) => any>>()
  const disposers: Array<() => void> = []
  const skillProviders: Array<unknown> = []

  const makeCtx = (): any => ({
    registered,
    sections,
    listeners,
    skillProviders,
    effect(fn: () => unknown) {
      const r = fn()
      if (typeof r === "function") { disposers.push(r as () => void); return }
      if (r && typeof (r as Generator).next === "function") {
        const gen = r as Generator<unknown>
        let step = gen.next()
        while (!step.done) {
          const v = step.value
          if (typeof v === "function") disposers.push(v as () => void)
          step = gen.next()
        }
      }
    },
    on(event: string, listener: (...args: any[]) => any) {
      const arr = listeners.get(event) ?? []
      arr.push(listener)
      listeners.set(event, arr)
      return () => {
        const i = arr.indexOf(listener)
        if (i >= 0) arr.splice(i, 1)
      }
    },
    inject(_deps: unknown, callback: (ctx: unknown) => void) {
      // 模拟「可选服务已就位」：以子 ctx 立刻调用（子 ctx 与父 ctx 共享同一批登记面）。
      callback(makeCtx())
    },
    skills: {
      registerProvider(create: (control: unknown) => unknown) {
        // 只登记工厂、不真的造 FileSystemSkillProvider（它要真 ctx）；
        // 技能资产的实际行为由 dsh-skill-filesystem 自己的套件负责。
        skillProviders.push(create)
        return () => { const i = skillProviders.indexOf(create); if (i >= 0) skillProviders.splice(i, 1) }
      },
    },
    tools: {
      register(def: Registered) {
        registered.push(def)
        return () => {
          const i = registered.indexOf(def)
          if (i >= 0) registered.splice(i, 1)
        }
      },
    },
    systemPrompt: {
      section(s: SectionRecord) {
        sections.push(s)
        return () => {
          const i = sections.indexOf(s)
          if (i >= 0) sections.splice(i, 1)
        }
      },
    },
    dispose() {
      disposers.splice(0).forEach((d) => d())
    },
  })
  return makeCtx()
}

const DIST = fileURLToPath(new URL("../dist/index.mjs", import.meta.url))

async function loadPlugin(): Promise<{
  name: string
  inject: string[]
  apply: (ctx: unknown, config?: { publish?: boolean }) => void
  usineRoot?: () => string
  toolNames?: readonly string[]
}> {
  return import(DIST)
}

function names(ctx: ReturnType<typeof fakeCtx>): string[] {
  return (ctx.registered as Registered[]).map((t: Registered) => t.name).sort()
}

function tool(ctx: ReturnType<typeof fakeCtx>, name: string): Registered {
  const t = (ctx.registered as Registered[]).find((t: Registered) => t.name === name)
  if (!t) throw new Error(`工具未注册：${name}（已注册：${names(ctx).join(", ")}）`)
  return t
}

/** 取插件装上的 dispatch 层审批门。 */
function gateOf(ctx: ReturnType<typeof fakeCtx>): (exec: unknown, next: () => Promise<GateDecision>) => Promise<GateDecision> {
  const list = ctx.listeners.get("tools/pre-execute")
  if (!list || list.length === 0) throw new Error("插件没有注册 tools/pre-execute 门")
  return list[0] as never
}

const exec = (agent?: unknown) => ({ callId: "c1", name: "x", signal: AbortSignal.timeout(60_000), agent })

/** 门看到的调用形状（dsh 的 ToolExecution 最小面）。 */
const gateExec = (name: string, args: unknown) => ({
  name,
  arguments: args,
  callId: "c1",
  signal: AbortSignal.timeout(60_000),
  agent: { id: "a" },
})

const tmps: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "dsh-plugin-"))
  tmps.push(d)
  return d
}

/**
 * 结构性隔绝 mcode-tools：任何会碰视频生成通道的用例必须包在它里面跑。
 * 本机 ~/.minimax/bin/mcode-tools 真实存在——2026-10-18 事故：allowed-once
 * 用例没隔离时真的 spawn 了 submit_video_generation（进程挂起 10 分钟后被
 * 人工击杀）。铁律「任何情况下不自动调用视频生成 API」对**测试**同样成立，
 * 靠 PATH 剥离让它 ENOENT——宁可确定性失败，不可碰运气。
 */
async function withoutMcodePath<T>(fn: () => Promise<T>): Promise<T> {
  const orig = process.env.PATH
  // 置空而非留 POSIX 系统目录：跨平台（Windows/POSIX 都无可用查找路径），
  // 且不会撞上恰好装在 /usr/bin 的 mcode-tools。
  process.env.PATH = ""
  try {
    return await fn()
  } finally {
    process.env.PATH = orig
  }
}
afterEach(() => {
  vi.restoreAllMocks()
  tmps.splice(0).forEach((d) => rmSync(d, { recursive: true, force: true }))
})

// ---------------------------------------------------------------------------
// 注册面
// ---------------------------------------------------------------------------

describe("工具面注册（吃构建产物 dist/index.mjs）", () => {
  it("apply() 默认注册 17 个工具（version + 13 家族 + verify/quota/video-generation），publish 不在——发布不可达是设计不是报错", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx()
    plugin.apply(ctx)
    expect(names(ctx)).toEqual([
      "usine_bgm", "usine_copy", "usine_cover", "usine_framehash",
      "usine_karaoke", "usine_ledger", "usine_lesson", "usine_persona",
      "usine_poetry", "usine_poster", "usine_quota", "usine_scene",
      "usine_storyteller", "usine_theme", "usine_verify", "usine_version",
      "usine_video_generation",
    ])
    expect(names(ctx)).not.toContain("usine_publish")
  })

  it("inject 只声明 tools——可选服务（approval / skills / systemPrompt）一律不进 inject", async () => {
    const plugin = await loadPlugin()
    expect(plugin.name).toBe("feuille-usine")
    // 钉住这条：声明了但宿主没提供的服务会让 fiber 永远 pending，插件永不生效、
    // 工具面全空且不报错（2026-10-20 架构评审发现 approval / skills 曾被写进
    // inject，正是这个坑；本轮复查发现 systemPrompt 是同一个坑的第三个实例）。
    // 可选服务一律走 ctx.get / ctx.inject。
    expect(plugin.inject).toEqual(["tools"])
  })

  it("工具面契约（toolNames）与实际注册逐字相同——少一个就红", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx()
    plugin.apply(ctx)
    expect([...(plugin.toolNames ?? [])].sort()).toEqual(names(ctx))
    expect(plugin.toolNames?.length).toBe(17)
  })

  // 这条用**真 cordis context**（不是 fakeCtx）：fakeCtx 不做服务解析，
  // 看不见 inject 的 AND 语义——「宿主缺某个 inject 服务 → 整个插件不生效」
  // 这一类病在假 ctx 上永远测不出来（详见 dsh.md §8「分工」）。
  it("真 cordis：宿主缺 systemPrompt 服务时，工具面照常全（inject 只声明 tools）", async () => {
    const plugin = await loadPlugin()

    /** 装一个只提供 tools（可选按需）的真 cordis 宿主。 */
    const boot = async (withSystemPrompt: boolean) => {
      const registered: string[] = []
      const sections: string[] = []
      const ctx = new Context()
      ctx.provide("tools", {
        register(def: { name: string }) {
          registered.push(def.name)
          return () => {}
        },
      })
      if (withSystemPrompt) {
        ctx.provide("systemPrompt", {
          section(s: { name: string }) {
            sections.push(s.name)
            return () => {}
          },
        })
      }
      await ctx.plugin(plugin)
      await new Promise((r) => setTimeout(r, 200))
      return { registered, sections }
    }

    // 对照组：宿主有 systemPrompt → 工具面全 + 纪律文本节挂上。
    const full = await boot(true)
    expect(full.registered.length).toBe(17)
    expect(full.sections).toEqual(["feuille:discipline"])

    // 实验组：宿主没有 systemPrompt → 纪律文本节挂不上（可选服务缺席），
    // 但**工具面必须照常全**——这正是「systemPrompt 不进 inject」的意义。
    // 改前（systemPrompt 在 inject 里）：注册工具数 = 0，插件永不生效且不报错。
    const bare = await boot(false)
    expect(bare.sections).toEqual([])
    expect(
      bare.registered.length,
      "宿主缺 systemPrompt 时插件仍应注册全部工具（inject 只声明 tools）",
    ).toBe(17)
  })

  it("config.publish === true 才注册 usine_publish；fiber 先销毁则异步注册放弃", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx()
    plugin.apply(ctx, { publish: true })
    // 动态 import 解析后注册——轮询等它出现（最长 2s）
    for (let i = 0; i < 40 && !names(ctx).includes("usine_publish"); i++) {
      await new Promise((r) => setTimeout(r, 50))
    }
    expect(names(ctx)).toContain("usine_publish")
    ctx.dispose()
    expect(ctx.registered).toHaveLength(0)

    // 先 dispose 再等动态 import：settled 标志让注册放弃
    const ctx2 = fakeCtx()
    plugin.apply(ctx2, { publish: true })
    ctx2.dispose()
    await new Promise((r) => setTimeout(r, 150))
    expect(ctx2.registered).toHaveLength(0)
  })

  it("反向验证：fiber 销毁（effect 回调反注册）后工具面与纪律节全清空", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx()
    plugin.apply(ctx)
    expect(ctx.registered.length).toBeGreaterThan(0)
    expect(ctx.sections).toHaveLength(1)
    ctx.dispose()
    expect(ctx.registered).toHaveLength(0)
    expect(ctx.sections).toHaveLength(0)
  })
})

// ---------------------------------------------------------------------------
// systemPrompt 纪律节
// ---------------------------------------------------------------------------

describe("systemPrompt 纪律节", () => {
  it("注册 feuille:discipline 节，红线文本齐：额度红线 / 发布不可达 / SKIP 不是 PASS / 母版纪律", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx()
    plugin.apply(ctx)
    const s = ctx.sections[0]!
    expect(s.name).toBe("feuille:discipline")
    expect(Number.isFinite(s.order)).toBe(true)
    // 判据口径必须与统一结果契约一致（result.ts）：ok=true 且 status=ok 才是过。
    expect(s.text).toContain("ok=true 且 status=ok 才是过")
    expect(s.text).toContain("status=invalid")
    expect(s.text).toContain("status=failed")
    expect(s.text).toContain("宁可多问一次，不要擅自烧")
    expect(s.text).toContain("工具**根本不会执行**")
    expect(s.text).toContain("不要换参数反复试探")
    expect(s.text).toContain("SKIP 不是 PASS")
    expect(s.text).toContain("永不重复消耗")
    expect(s.text).toContain("绝不代填凭据")
  })
})

// ---------------------------------------------------------------------------
// 红线机制：额度审批在 dispatch 层（tools/pre-execute），不在工具体内
// ---------------------------------------------------------------------------

describe("usine_video_generation：额度红线由 dispatch 层的 pre-execute 门承载", () => {
  const submit = (over: Record<string, unknown> = {}) => ({
    action: "submit",
    model: "MiniMax-Hailuo-2.3",
    prompt: "一片落叶飘过十二种语言的秋天",
    duration: 6,
    resolution: "768P",
    ...over,
  })
  const allow = async (): Promise<GateDecision> => ({ kind: "allow" })

  it("合规 submit → 门返回 ask（不是 deny、不是 allow）：审批在派发前发生", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const d = await gateOf(ctx)(gateExec("usine_video_generation", submit()), allow)
    expect(d.kind).toBe("ask")
  })

  it("审批卡展示清单齐：提示词/画幅/时长/分辨率/预估消耗；Hailuo 标注套餐额度不烧积分", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const d = await gateOf(ctx)(gateExec("usine_video_generation", submit()), allow)
    const reason = d.reason ?? ""
    expect(reason).toContain("[视频生成提交审批]")
    expect(reason).toContain("一片落叶飘过十二种语言的秋天")
    expect(reason).toContain("时长：6 秒")
    expect(reason).toContain("分辨率：768P")
    expect(reason).toContain("套餐额度（不烧积分）")
    // displayReason 必须带 en（宿主按 locale 取，缺 en 会回退到空）并带中文版。
    expect(d.displayReason?.en).toBeTruthy()
    expect(d.displayReason?.zh).toContain("视频生成提交审批")
  })

  it("参数不合规格 → 门放行（不占用一次人工审批），由工具体回 invalid", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const d = await gateOf(ctx)(gateExec("usine_video_generation", submit({ duration: 12 })), allow)
    expect(d.kind).toBe("allow")
  })

  it("H3 缺 ratio → 门放行（不合规不占审批额度）", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const d = await gateOf(ctx)(
      gateExec("usine_video_generation", submit({ model: "MiniMax-H3", resolution: "768P" })), allow)
    expect(d.kind).toBe("allow")
  })

  it("query / download / 其他工具 → 门放行（只有 submit 走审批）", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const gate = gateOf(ctx)
    expect((await gate(gateExec("usine_video_generation", { action: "query", task_id: "t" }), allow)).kind).toBe("allow")
    expect((await gate(gateExec("usine_video_generation", { action: "download" }), allow)).kind).toBe("allow")
    expect((await gate(gateExec("usine_version", {}), allow)).kind).toBe("allow")
    expect((await gate(gateExec("usine_scene", { action: "parse" }), allow)).kind).toBe("allow")
  })

  it("H3 768P 6s 预估 426 积分（≈¥2.98）——积分速查表进审批卡", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const d = await gateOf(ctx)(
      gateExec("usine_video_generation", submit({ model: "MiniMax-H3", ratio: "16:9", resolution: "768P" })), allow)
    expect(d.reason).toContain("约 426 积分")
    expect(d.reason).toContain("≈¥2.98")
    expect(d.reason).toContain("画幅：16:9")
  })
})

describe("usine_video_generation：工具体（审批放行之后才跑）", () => {
  const submit = (over: Record<string, unknown> = {}) => ({
    action: "submit",
    model: "MiniMax-Hailuo-2.3",
    prompt: "一片落叶飘过十二种语言的秋天",
    duration: 6,
    resolution: "768P",
    ...over,
  })

  it("参数不合规格 → status=invalid，不碰 mcode-tools 通道", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(
      submit({ duration: 12 }), exec({ id: "a" }))) as { status: string; output: string; ok: boolean }
    expect(r.status).toBe("invalid")
    expect(r.ok).toBe(false)
    expect(r.output).toContain("Hailuo-2.3 768P 只有 6s / 10s")
  })

  it("H3 缺 ratio → status=invalid", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(
      submit({ model: "MiniMax-H3", resolution: "768P" }), exec({ id: "a" }))) as { status: string }
    expect(r.status).toBe("invalid")
  })

  it("submit 走 mcode-tools 通道：PATH 剥离 → status=failed 且如实报 ENOENT（绝不烧额度）", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await withoutMcodePath(() =>
      tool(ctx, "usine_video_generation").execute(submit(), exec({ id: "a" })))) as
      { status: string; output: string; ok: boolean; detail?: Record<string, unknown> }
    expect(r.status).toBe("failed")
    expect(r.ok).toBe(false)
    expect(r.output).toContain("mcode-tools")
    // 预估消耗仍随结果回声（模型据此向操作员复述）
    expect(r.detail?.cost).toContain("套餐额度")
  }, 15_000)

  it("query / download 的参数校验通道", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const t = tool(ctx, "usine_video_generation")
    const q = (await t.execute({ action: "query" }, exec({ id: "a" }))) as { status: string }
    const d = (await t.execute({ action: "download", out: "/tmp/x.mp4" }, exec({ id: "a" }))) as { status: string }
    const u = (await t.execute({ action: "wat" }, exec({ id: "a" }))) as { status: string }
    expect(q.status).toBe("invalid")
    expect(d.status).toBe("invalid")
    expect(u.status).toBe("invalid")
  })
})

// ---------------------------------------------------------------------------
// 统一结果契约：全部工具同一套 schema，dsh 按 schema 机检返回值
// ---------------------------------------------------------------------------

describe("统一结果契约", () => {
  it("全部工具的 output.schema 逐字相同（ok / status / output / detail）", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const schemas = (ctx.registered as Registered[]).map((t: Registered) => JSON.stringify(t.output.schema))
    expect(new Set(schemas).size).toBe(1)
    const s = (ctx.registered as Registered[])[0]!.output.schema as Record<string, any>
    expect(Object.keys(s.properties ?? {}).sort()).toEqual(["detail", "ok", "output", "status"])
    expect(s.required).toEqual(["ok", "status", "output"])
    expect((s.properties as any).status.enum).toEqual(["ok", "invalid", "failed"])
  })

  it("工具返回值符合契约：{ok, status, output} 三件齐，detail 可选", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_version").execute({}, exec())) as Record<string, unknown>
    expect(r.ok).toBe(true)
    expect(r.status).toBe("ok")
    expect(typeof r.output).toBe("string")
  })
})

// ---------------------------------------------------------------------------
// 进程内 main 捕获接缝（无 subprocess 桥）
// ---------------------------------------------------------------------------

describe("argv 家族工具：进程内 main 调用 + 输出捕获", () => {
  it("FeuilleError 错误渠道：copy 未知旗标 → status=failed + 报错文本被捕获（异常不外抛，模型读得到）", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_copy").execute(
      { action: "check", argv: ["--wat"] }, exec())) as { status: string; output: string; detail?: Record<string, unknown> }
    expect(r.status).toBe("failed")
    expect(r.output).toContain("未知旗标：--wat")
    expect(r.detail?.exit_code).toBe(1)
  })

  it("未知子命令 → status=invalid + 可用清单", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_scene").execute(
      { action: "nope", argv: [] }, exec())) as { status: string; output: string; detail?: Record<string, unknown> }
    expect(r.status).toBe("invalid")
    expect(r.output).toContain("未知子命令：nope")
    expect(r.output).toContain("parse / validate / draft / tts")
    expect(r.detail?.exit_code).toBe(2)
  })

  it("捕获是**上下文作用域**的：两个 main 并发跑不交错，宿主噪声不被吞", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    // 两个并发调用：各自的输出必须各自完整，不得互相截断或串台。
    const [a, b] = await Promise.all([
      tool(ctx, "usine_ledger").execute({ action: "status", argv: ["--root", tmp()] }, exec()),
      tool(ctx, "usine_theme").execute({ action: "match", argv: ["--lang", "zh"] }, exec()),
    ])
    const ta = a as { output: string }
    const tb = b as { output: string }
    expect(typeof ta.output).toBe("string")
    expect(typeof tb.output).toBe("string")
    // 宿主噪声（窗口外写的 stdout）不得进工具输出：这里用一次窗口外的写做探针。
    const probe = "HOST-NOISE-PROBE"
    process.stdout.write(probe)
    const c = (await tool(ctx, "usine_theme").execute({ action: "match", argv: ["--lang", "zh"] }, exec())) as { output: string }
    expect(c.output).not.toContain(probe)
  }, 30_000)

  it("usineRoot() 从 bundle 位置定位 usine 工作区根（verify 工具的 cwd）", async () => {
    const plugin = (await loadPlugin()) as { usineRoot?: () => string }
    expect(plugin.usineRoot).toBeDefined()
    const root = plugin.usineRoot!()
    expect(existsSync(join(root, "pnpm-workspace.yaml"))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 假 LLM 干跑验收：brief → ② 创意交接产物 → ③ scene.json → ⑧ 发布词自检
//                → Hailuo 处在 dispatch 层停车 → 发布不可达
// ⑤⑥⑦（TTS/成片/封面）是媒体重步骤，e2e 已由各自包的 vitest 套件覆盖；
// 这里验的是**工具面**：每一步都经 dsh 工具进程内驱动，红线在边界上被断言。
// ---------------------------------------------------------------------------

describe("假 LLM 干跑：产线经工具面驱动，红线在 Hailuo 处置前停车", () => {
  it("brief → lesson new（②）→ scene draft/parse（③）→ copy check（⑧）→ 审批门前停车（工具未执行）→ publish 不可达", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx()
    plugin.apply(ctx)
    const agent = { id: "fake-llm" }
    const call = (name: string, args: unknown) => tool(ctx, name).execute(args, exec(agent))
    const d = tmp()
    const ld = join(d, "lessons")

    // ② 创意交接：新课开坑（注册表现取 + 选角当场验 + 空跑草稿自证）
    const rNew = (await call("usine_lesson", {
      action: "new",
      argv: ["leaf", "--title", "落叶", "--tokens", "apple:#D8453B", "--lessons", ld],
    })) as { ok: boolean; status: string; output: string; detail?: Record<string, unknown> }
    expect(rNew.ok).toBe(true)
    expect(rNew.status).toBe("ok")
    // lesson new 的回显路径带平台分隔符（Mac 正斜杠 / Windows 反斜杠）——
    // 断言跟随 path.join，别钉死某一端的分隔符。
    expect(rNew.output).toContain(`已写 ${join("lessons", "leaf", "brief.json")}`)
    expect(existsSync(join(ld, "leaf", "brief.json"))).toBe(true)

    // ③ 设计：brief → scene.md（草稿）→ scene.json（解析）
    const rDraft = (await call("usine_scene", {
      action: "draft", argv: ["--brief", join(ld, "leaf", "brief.json")],
    })) as { ok: boolean; output: string }
    expect(rDraft.ok).toBe(true)
    expect(existsSync(join(ld, "leaf", "scene.md"))).toBe(true)

    const rParse = (await call("usine_scene", {
      action: "parse", argv: ["--scene", "leaf", "--lessons", ld],
    })) as { ok: boolean }
    expect(rParse.ok).toBe(true)
    const scene = JSON.parse(readFileSync(join(ld, "leaf", "scene.json"), "utf8"))
    expect(scene["sceneId"]).toBe("leaf")

    // ⑧ 发布清单前置：发布词自检（零平台流量），--facts 数字溯源全对上
    const pub = join(d, "publish")
    const facts = join(d, "facts.json")
    mkdirSync(pub, { recursive: true })
    writeFileSync(join(pub, "xiaohongshu.md"),
      "## 标题（20 字内）\n好标题\n\n## 正文\n一支可以跟读的落叶，评论区告诉我。\n\n"
      + "## 话题标签\n#落叶 #秋天 \n\n## 发布贴士\n发布后自己置顶（\"报数\"）\n", "utf8")
    writeFileSync(join(pub, "douyin.md"),
      "## 文案\n好标题\n\n一支可以跟读的落叶，评论区告诉我。\n\n## 话题\n#落叶 #秋天 \n\n## 发布贴士\n发布后自己置顶（\"报数\"）\n", "utf8")
    writeFileSync(join(pub, "bilibili.md"),
      "## 标题\n好标题\n\n## 简介\n一支可以跟读的落叶，评论区告诉我。\n\n## 标签\n落叶 多语言\n\n## 发布贴士\n发布后自己置顶（\"报数\"）\n", "utf8")
    writeFileSync(facts, JSON.stringify({ "成片秒数": 12.3 }), "utf8")
    const rCopy = (await call("usine_copy", {
      action: "check", argv: [pub, "--facts", facts],
    })) as { ok: boolean; output: string }
    expect(rCopy.ok).toBe(true)
    expect(rCopy.output).toContain("数字溯源")

    // ⑥ 母版：视频生成——门在**派发前**问审批，未获批准则工具体根本不执行。
    // 这里断言的是「门问 + 工具没跑」这条链，而不是工具体里的某个 status。
    const submitArgs = {
      action: "submit",
      model: "MiniMax-Hailuo-2.3",
      prompt: "一片落叶在秋天里归根",
      duration: 6,
      resolution: "768P",
    }
    const decision = await gateOf(ctx)(gateExec("usine_video_generation", submitArgs), async () => ({ kind: "allow" }))
    expect(decision.kind).toBe("ask")
    expect(decision.reason).toContain("[视频生成提交审批]")
    // 门问了就停：工具体一次都没被调用（没有 task_id、没有通道输出）。
    const rVideo = (await withoutMcodePath(() => call("usine_video_generation", submitArgs))) as
      { status: string; detail?: Record<string, unknown> }
    expect(rVideo.detail?.task_id).toBeUndefined()

    // ⑨ 平台发布：工具面上根本没有——不可达是设计
    expect(names(ctx)).not.toContain("usine_publish")
  }, 60_000)
})
