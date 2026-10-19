// plugin.test.ts — dsh 插件（P6 全量工具面）的正面证据 + 红线机制验收。
//
// 测试吃的是**构建产物** dist/index.mjs（dsh 宿主实际加载的那个文件），不是
// TS 源——整条链（esbuild 打包 + external 解析 + 插件形状 + 工具注册 +
// 进程内 main 调用 + approval 门）一次验证。dsh 侧的接缝（--patch 加载 +
// 激活）由 dsh web 启动实录证明（migration/README.md spike 3 结论）。
//
// 红线测试是本套件的主角：video-generation 必须「问了才动、没点头不动、
// 问的卡上有完整的展示清单」；publish 默认连工具都不存在。
import { afterEach, describe, expect, it, vi } from "vitest"
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

interface ApprovalReq {
  agent: unknown
  toolName: string
  callId?: unknown
  reason?: string
  displayReason?: { en: string }
  signal?: AbortSignal
}

/** 最小假 Cordis ctx：effect + tools.register + systemPrompt.section + 可选 approval。 */
function fakeCtx(approvalOutcome?: string) {
  const registered: Registered[] = []
  const sections: SectionRecord[] = []
  const approvalRequests: ApprovalReq[] = []
  const disposers: Array<() => void> = []
  return {
    registered,
    sections,
    approvalRequests,
    effect(fn: () => () => void) {
      disposers.push(fn())
    },
    dispose() {
      disposers.splice(0).forEach((d) => d())
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
    ...(approvalOutcome === undefined
      ? {}
      : {
          approval: {
            async request(req: ApprovalReq) {
              approvalRequests.push(req)
              return approvalOutcome
            },
          },
        }),
  }
}

const DIST = fileURLToPath(new URL("../dist/index.mjs", import.meta.url))

async function loadPlugin(): Promise<{
  name: string
  inject: string[]
  apply: (ctx: unknown, config?: { publish?: boolean }) => void
  usineRoot?: () => string
}> {
  return import(DIST)
}

function names(ctx: ReturnType<typeof fakeCtx>): string[] {
  return ctx.registered.map((t) => t.name).sort()
}

function tool(ctx: ReturnType<typeof fakeCtx>, name: string): Registered {
  const t = ctx.registered.find((t) => t.name === name)
  if (!t) throw new Error(`工具未注册：${name}（已注册：${names(ctx).join(", ")}）`)
  return t
}

const exec = (agent?: unknown) => ({ callId: "c1", name: "x", signal: AbortSignal.timeout(60_000), agent })

const tmps: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "dsh-plugin-"))
  tmps.push(d)
  return d
}

/**
 * 结构性隔绝 mcode-tools：允许 any approval 通过的用例必须包在它里面跑。
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
    const ctx = fakeCtx("allowed-once")
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

  it("inject 声明 tools + systemPrompt + approval + skills；publish 未声明（它是 config 门不是服务门）", async () => {
    const plugin = await loadPlugin()
    expect(plugin.name).toBe("feuille-usine")
    // approval 必须声明：videoGenerationTool 在 apply 期就取 ctx.approval，真
    // cordis 对未声明就访问的服务抛 "cannot get property ... without inject"，
    // 整个插件加载失败、工具面全丢（2026-10-18 dsh 宿主真跑首测抓到；本文件
    // 的 fakeCtx 不校验 inject，这里把声明钉住防回退）。
    // skills 同理：apply 期注册 usine 技能资产（默认自动加载）要取 ctx.skills。
    expect(plugin.inject).toEqual(["tools", "systemPrompt", "approval", "skills"])
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
    expect(s.text).toContain("fail-closed")
    expect(s.text).toContain("宁可多问一次，不要擅自烧")
    expect(s.text).toContain("SKIP 不是 PASS")
    expect(s.text).toContain("永不重复消耗")
    expect(s.text).toContain("绝不代填凭据")
  })
})

// ---------------------------------------------------------------------------
// 红线机制：video-generation 的 approval 门
// ---------------------------------------------------------------------------

describe("usine_video_generation：额度红线由机制承载", () => {
  const submit = (over: Record<string, unknown> = {}) => ({
    action: "submit",
    model: "MiniMax-Hailuo-2.3",
    prompt: "一片落叶飘过十二种语言的秋天",
    duration: 6,
    resolution: "768P",
    ...over,
  })

  it("参数不合规格 → invalid，且根本不进审批（Hailuo 没有 12s 档）", async () => {
    const ctx = fakeCtx("allowed-once")
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(
      submit({ duration: 12 }), exec({ id: "a" }))) as { status: string; message: string }
    expect(r.status).toBe("invalid")
    expect(r.message).toContain("Hailuo-2.3 768P 只有 6s / 10s")
    expect(ctx.approvalRequests).toHaveLength(0)
  })

  it("H3 缺 ratio → invalid，不进审批", async () => {
    const ctx = fakeCtx("allowed-once")
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(
      submit({ model: "MiniMax-H3", resolution: "768P" }), exec({ id: "a" }))) as { status: string }
    expect(r.status).toBe("invalid")
    expect(ctx.approvalRequests).toHaveLength(0)
  })

  it("无 approval 服务 → fail closed：asked-unavailable，未提交；拒绝语点名被拒工具 + 所需 approval + 重试路径（refusal-audit 钉版）", async () => {
    const ctx = fakeCtx() // 不带 approval
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(submit(), exec({ id: "a" }))) as { status: string; message: string }
    expect(r.status).toBe("asked-unavailable")
    expect(r.message).toContain("fail closed")
    expect(ctx.approvalRequests).toHaveLength(0)
    // 钉版 packages/dsh-plugin/test/refusal-audit.md：approval 缺席的拒绝语必须三点全中——
    // (a) 点名被拒工具 (b) 说清所需 approval 审批未获得 (c) 给出授予/重试路径；逐字钉，漂移即红。
    expect(r.message).toContain("usine_video_generation")
    expect(r.message).toContain("approval 审批未获得")
    expect(r.message).toContain("要过这道门：在带 approval 服务的宿主里重新发起本次调用")
    expect(r.message).toContain("审批卡会再次摆出，人工点头（allowed-once）后才提交")
    expect(r.message).toContain("未提交")
  })

  it("无 agent 执行上下文 → fail closed", async () => {
    const ctx = fakeCtx("allowed-once")
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(submit(), exec(undefined))) as { status: string }
    expect(r.status).toBe("asked-unavailable")
    expect(ctx.approvalRequests).toHaveLength(0)
  })

  it("审批卡展示清单齐：提示词/画幅/时长/分辨率/预估消耗；Hailuo 标注套餐额度不烧积分", async () => {
    const ctx = fakeCtx("rejected")
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_video_generation").execute(submit(), exec({ id: "a" }))) as { status: string; message: string }
    expect(ctx.approvalRequests).toHaveLength(1)
    const req = ctx.approvalRequests[0]!
    expect(req.toolName).toBe("usine_video_generation")
    expect(req.reason).toContain("[视频生成提交审批]")
    expect(req.reason).toContain("一片落叶飘过十二种语言的秋天")
    expect(req.reason).toContain("时长：6 秒")
    expect(req.reason).toContain("分辨率：768P")
    expect(req.reason).toContain("套餐额度（不烧积分）")
    expect(req.displayReason!.en).toBe(req.reason)
    expect(r.status).toBe("asked-rejected")
    expect(r.message).toContain("未提交")
  })

  it("H3 768P 6s 预估 426 积分（≈¥2.98）——积分速查表进审批卡", async () => {
    const ctx = fakeCtx("rejected")
    ;(await loadPlugin()).apply(ctx)
    await tool(ctx, "usine_video_generation").execute(
      submit({ model: "MiniMax-H3", ratio: "16:9", resolution: "768P" }), exec({ id: "a" }))
    expect(ctx.approvalRequests[0]!.reason).toContain("约 426 积分")
    expect(ctx.approvalRequests[0]!.reason).toContain("≈¥2.98")
    expect(ctx.approvalRequests[0]!.reason).toContain("画幅：16:9")
  })

  it("allowed-once 才碰 mcode-tools 通道（PATH 剥离 → submit-failed 如实报 ENOENT，审批只问一次）", async () => {
    const ctx = fakeCtx("allowed-once")
    ;(await loadPlugin()).apply(ctx)
    const r = await withoutMcodePath(() =>
      tool(ctx, "usine_video_generation").execute(submit(), exec({ id: "a" }))) as { status: string; output: string }
    expect(ctx.approvalRequests).toHaveLength(1)
    expect(r.status).toBe("submit-failed")
    expect(r.output).toContain("mcode-tools")
  }, 15_000)

  it("rejected 后不重试不试探——再提交另问一次，无残余授权", async () => {
    const ctx = fakeCtx("rejected")
    ;(await loadPlugin()).apply(ctx)
    const t = tool(ctx, "usine_video_generation")
    await t.execute(submit(), exec({ id: "a" }))
    const r = (await t.execute(submit(), exec({ id: "a" }))) as { status: string }
    expect(r.status).toBe("asked-rejected")
    expect(ctx.approvalRequests).toHaveLength(2) // 单次有效：第二次也要重新问
  })

  it("query / download 的参数校验通道", async () => {
    const ctx = fakeCtx("allowed-once")
    ;(await loadPlugin()).apply(ctx)
    const t = tool(ctx, "usine_video_generation")
    const q = (await t.execute({ action: "query" }, exec({ id: "a" }))) as { status: string }
    const d = (await t.execute({ action: "download", out: "/tmp/x.mp4" }, exec({ id: "a" }))) as { status: string }
    const u = (await t.execute({ action: "wat" }, exec({ id: "a" }))) as { status: string }
    expect(q.status).toBe("invalid")
    expect(d.status).toBe("invalid")
    expect(u.status).toBe("invalid")
    expect(ctx.approvalRequests).toHaveLength(0) // 只有 submit 走审批
  })
})

// ---------------------------------------------------------------------------
// 进程内 main 捕获接缝（无 subprocess 桥）
// ---------------------------------------------------------------------------

describe("argv 家族工具：进程内 main 调用 + 输出捕获", () => {
  it("FeuilleError 错误渠道：copy 未知旗标 → exit_code 1 + 报错文本被捕获（异常不外抛，模型读得到）", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_copy").execute(
      { action: "check", argv: ["--wat"] }, exec())) as { exit_code: number; output: string }
    expect(r.exit_code).toBe(1)
    expect(r.output).toContain("未知旗标：--wat")
  })

  it("未知子命令 → exit_code 2 + 可用清单", async () => {
    const ctx = fakeCtx()
    ;(await loadPlugin()).apply(ctx)
    const r = (await tool(ctx, "usine_scene").execute(
      { action: "nope", argv: [] }, exec())) as { exit_code: number; output: string }
    expect(r.exit_code).toBe(2)
    expect(r.output).toContain("未知子命令：nope")
    expect(r.output).toContain("parse / validate / draft / tts")
  })

  it("usineRoot() 从 bundle 位置定位 usine 工作区根（verify 工具的 cwd）", async () => {
    const plugin = (await loadPlugin()) as { usineRoot?: () => string }
    expect(plugin.usineRoot).toBeDefined()
    const root = plugin.usineRoot!()
    expect(existsSync(join(root, "pnpm-workspace.yaml"))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 假 LLM 干跑验收：brief → ② 创意交接产物 → ③ scene.json → ⑧ 发布词自检
//                → Hailuo 处 approval/asked 停车 → 发布不可达
// ⑤⑥⑦（TTS/成片/封面）是媒体重步骤，e2e 已由各自包的 vitest 套件覆盖；
// 这里验的是**工具面**：每一步都经 dsh 工具进程内驱动，红线在边界上被断言。
// ---------------------------------------------------------------------------

describe("假 LLM 干跑：产线经工具面驱动，红线在 Hailuo 处停车", () => {
  it("brief → lesson new（②）→ scene draft/parse（③）→ copy check（⑧）→ video-generation 审批停车 → publish 不可达", async () => {
    const plugin = await loadPlugin()
    const ctx = fakeCtx("rejected") // 人没点头
    plugin.apply(ctx)
    const agent = { id: "fake-llm" }
    const call = (name: string, args: unknown) => tool(ctx, name).execute(args, exec(agent))
    const d = tmp()
    const ld = join(d, "lessons")

    // ② 创意交接：新课开坑（注册表现取 + 选角当场验 + 空跑草稿自证）
    const rNew = (await call("usine_lesson", {
      action: "new",
      argv: ["leaf", "--title", "落叶", "--tokens", "apple:#D8453B", "--lessons", ld],
    })) as { exit_code: number; output: string }
    expect(rNew.exit_code).toBe(0)
    // lesson new 的回显路径带平台分隔符（Mac 正斜杠 / Windows 反斜杠）——
    // 断言跟随 path.join，别钉死某一端的分隔符。
    expect(rNew.output).toContain(`已写 ${join("lessons", "leaf", "brief.json")}`)
    expect(existsSync(join(ld, "leaf", "brief.json"))).toBe(true)

    // ③ 设计：brief → scene.md（草稿）→ scene.json（解析）
    const rDraft = (await call("usine_scene", {
      action: "draft", argv: ["--brief", join(ld, "leaf", "brief.json")],
    })) as { exit_code: number; output: string }
    expect(rDraft.exit_code).toBe(0)
    expect(existsSync(join(ld, "leaf", "scene.md"))).toBe(true)

    const rParse = (await call("usine_scene", {
      action: "parse", argv: ["--scene", "leaf", "--lessons", ld],
    })) as { exit_code: number }
    expect(rParse.exit_code).toBe(0)
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
    })) as { exit_code: number; output: string }
    expect(rCopy.exit_code).toBe(0)
    expect(rCopy.output).toContain("数字溯源")

    // ⑥ 母版：视频生成——Hailuo 提交，审批被拒 → 红线停车，未提交任何东西
    const rVideo = (await call("usine_video_generation", {
      action: "submit",
      model: "MiniMax-Hailuo-2.3",
      prompt: "一片落叶在秋天里归根",
      duration: 6,
      resolution: "768P",
    })) as { status: string; message: string }
    expect(rVideo.status).toBe("asked-rejected")
    expect(rVideo.message).toContain("未提交")
    expect(ctx.approvalRequests).toHaveLength(1)
    expect(ctx.approvalRequests[0]!.reason).toContain("[视频生成提交审批]")

    // ⑨ 平台发布：工具面上根本没有——不可达是设计
    expect(names(ctx)).not.toContain("usine_publish")
  }, 60_000)
})
