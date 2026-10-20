// plugin-parity.test.ts — 智能体面钉版对账：工具面 ↔ CLI 路由 ↔ skills 知识 ↔ 旗标词表。
//
// 「智能体面」（dsh 插件注册的工具 + skills howto）是 RSI wave 的正式改进
// 方向，而它横跨几处文本/代码：tools.ts 的 action 枚举、@feuille/cli 的
// COMMANDS 路由表、SKILL.md 的规格与积分速查、库层解析的旗标词表。四处全靠人工
// 约定同步——本套件把约定钉成门禁：任何一侧漂移，`pnpm verify` 当场红，而不是等
// 操作者或模型在线上踩坑。
//
// 与 plugin.test.ts 的分工：那边吃构建产物 dist/index.mjs，验整条打包链 +
// 红线机制行为；这边吃 **src 源**（wave 实际编辑的面）做交叉对账。积分
// 数值的权威出处是 skills/video-generation/SKILL.md 的速查表——本套件从
// SKILL.md 读数、驱动审批卡算账，两边对不上就是红。
//
// 红线：本套件只驱动**门**（tools/pre-execute 的 ask 决策），不驱动工具体；
// 且所有会碰通道的用例都套 withoutMcodePath 作为结构性兜底——测试在任何环境
// 下都不得真的烧额度。
import { readFileSync, readdirSync, statSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { COMMANDS } from "@feuille/cli"
import type { ToolDefinition } from "@deepseek-ai/dsh-tools"

import { familyTools, usineVersion, videoGenerationTool } from "../src/tools.js"
import { videoApprovalGate } from "../src/gate.js"
import { TOOL_NAMES } from "../src/toolnames.js"

// ---------------------------------------------------------------------------
// 通用件
// ---------------------------------------------------------------------------

const SKILL_PATH = fileURLToPath(
  new URL("../../../skills/video-generation/SKILL.md", import.meta.url))

/** SKILL.md 全文（读一次；缺文件 = 套件红，不静默跳过）。 */
const SKILL = readFileSync(SKILL_PATH, "utf8")

type ExecArg = Parameters<ToolDefinition["execute"]>[1]

/** 最小假 exec：结构子集即可（工具面只读 signal 与 agent）。 */
function exec(): ExecArg {
  return {
    agent: { id: "parity" },
    signal: new AbortController().signal,
  } as unknown as ExecArg
}

/** 红线兜底：PATH 剥离下跑——测试用例必须连 spawn 点都到不了。 */
async function withoutMcodePath<T>(fn: () => Promise<T>): Promise<T> {
  const orig = process.env.PATH
  // 置空而非留 POSIX 系统目录：跨平台（Windows/POSIX 都无可用查找路径）。
  process.env.PATH = ""
  try {
    return await fn()
  } finally {
    process.env.PATH = orig
  }
}

/** submit 参数体（默认 Hailuo 合法组合；over 覆盖单字段）。 */
function submitArgs(over: Record<string, unknown> = {}) {
  return {
    action: "submit",
    model: "MiniMax-Hailuo-2.3",
    prompt: "测试提示词（不提交，停在审批）",
    duration: 6,
    resolution: "768P",
    ...over,
  }
}

/** 门看到的调用形状（dsh 的 ToolExecution 最小面）。 */
function gateExec(args: unknown) {
  return {
    name: "usine_video_generation",
    arguments: args,
    callId: "c1",
    signal: new AbortController().signal,
    agent: { id: "parity" },
  } as never
}

/** 跑一次门，返回决策（ask / allow）。 */
async function gateOnce(over: Record<string, unknown> = {}) {
  const gate = videoApprovalGate()
  const decision = await gate(gateExec(submitArgs(over)), async () => ({ kind: "allow" }) as never)
  return decision as { kind: string; reason?: string; displayReason?: { en: string; zh?: string } }
}

/** 跑一次 submit 工具体，返回统一结果契约。 */
async function submitOnce(over: Record<string, unknown> = {}) {
  const tool = videoGenerationTool()
  const r = (await withoutMcodePath(() =>
    tool.execute(submitArgs(over), exec()))) as { ok: boolean; status: string; output: string }
  return r
}

/** 从 family 工具定义里取 action 枚举。 */
function actionEnum(tool: { name: string; parameters: Record<string, unknown> }) {
  const props = (tool.parameters as { properties: Record<string, { enum?: string[] }> }).properties
  return props.action?.enum ?? []
}

// ---------------------------------------------------------------------------
// A. argv 家族工具 ↔ @feuille/cli COMMANDS 路由
// ---------------------------------------------------------------------------

describe("工具面 ↔ CLI 路由双向对账", () => {
  const tools = familyTools()
  const names = tools.map((t) => t.name)

  it("13 个 argv 家族工具，注册名与覆盖面逐字钉死（面变 = 门禁红，逼迫显式更新）", () => {
    expect([...names].sort()).toEqual([
      "usine_bgm", "usine_copy", "usine_cover", "usine_framehash",
      "usine_karaoke", "usine_ledger", "usine_lesson", "usine_persona",
      "usine_poetry", "usine_poster", "usine_scene", "usine_storyteller",
      "usine_theme",
    ])
  })

  it("每个家族的 action 枚举与 CLI `${grp}/${cmd}` 路由组双向一致", () => {
    for (const tool of tools) {
      const grp = tool.name.slice("usine_".length)
      const fromTool = [...actionEnum(tool)].sort()
      const fromCli = Object.keys(COMMANDS)
        .filter((k) => k.startsWith(`${grp}/`))
        .map((k) => k.slice(grp.length + 1))
        .sort()
      // 双向：工具多出的 action 是 CLI 没有的死路由；CLI 多出的是模型
      // 面上「看不见的产线动词」——两边任何一侧漂移都得红。
      expect(fromTool, `${tool.name} vs feuille ${grp} 路由`).toEqual(fromCli)
    }
  })

  it("CLI 路由组没有漏挂家族工具（version 与 publish 的豁免各有其锚）", () => {
    const cliGroups = new Set(Object.keys(COMMANDS).map((k) => k.split("/")[0]))
    const toolGroups = new Set(names.map((n) => n.slice("usine_".length)))
    for (const grp of cliGroups) {
      if (grp === "version") {
        // version 是无参自检工具，不是 argv 家族——单独钉：
        expect(usineVersion.name).toBe("usine_version")
        expect(COMMANDS.version).toBeDefined()
        continue
      }
      if (grp === "publish") {
        // 发布默认不可达是设计：publish 在 CLI 有路由、在默认工具面
        // **没有**这个工具（config 显式开启才注册——plugin.test.ts 验证）。
        expect(names).not.toContain("usine_publish")
        continue
      }
      expect(toolGroups, `CLI 组 ${grp} 没有对应的 argv 家族工具`).toContain(grp)
    }
  })

  it("argv 家族的 action/argv 都是必填、残余参数是 string 数组（canonical 契约）", () => {
    for (const tool of tools) {
      const params = tool.parameters as {
        required?: string[]
        properties: Record<string, { type?: string }>
      }
      expect(params.required, tool.name).toEqual(["action", "argv"])
      expect(params.properties.argv?.type, tool.name).toBe("array")
      expect(actionEnum(tool).length, tool.name).toBeGreaterThan(0)
    }
  })
})

// ---------------------------------------------------------------------------
// B. 工具面契约（TOOL_NAMES）↔ 实际注册面
// ---------------------------------------------------------------------------

describe("工具面契约 ↔ 代码", () => {
  it("契约里的 17 个工具名与家族+独立工具的实现逐字一致", () => {
    const implemented = [usineVersion.name, ...familyTools().map((t) => t.name),
      "usine_verify", "usine_quota", "usine_video_generation"]
    expect([...implemented].sort()).toEqual([...TOOL_NAMES].sort())
  })

  it("契约里没有 publish（发布默认不可达，名单里出现它就等于宣称随时能发布）", () => {
    expect(TOOL_NAMES).not.toContain("usine_publish" as never)
  })
})

// ---------------------------------------------------------------------------
// C. 视频线规格 ↔ SKILL.md 前置输入契约
// ---------------------------------------------------------------------------

describe("视频线规格 ↔ SKILL.md 前置输入契约", () => {
  const tool = videoGenerationTool()
  const modelEnum = ((tool.parameters as { properties: Record<string, { enum?: string[] }> })
    .properties).model?.enum ?? []

  it("三条视频线与 SKILL.md 选线表逐字对上（模型名漂移 = 红）", () => {
    expect([...modelEnum].sort()).toEqual([
      "MiniMax-H3", "MiniMax-H3-Max", "MiniMax-Hailuo-2.3",
    ])
    for (const m of modelEnum) expect(SKILL).toContain(m)
  })

  it("SKILL.md 的选线表仍在（规格矩阵的权威出处被改动时逼迫重推导）", () => {
    // 这些子串是下面边界矩阵的出处；SKILL.md 改写措辞会红——这是有意的：
    // 规格文档变了而校验器没跟上，正是本套件要拦的漂移。
    expect(SKILL).toContain("768P 6s / 10s、1080P 6s")
    expect(SKILL).toContain("768P / 2K，4–15s 整数")
    expect(SKILL).toContain("480P / 768P，5–15s 整数")
    expect(SKILL).toContain("prompt` 上限 7000 字符")
  })

  it("边界矩阵：不合规格当场 invalid，且**不占人工审批**（门放行 → 工具体回 invalid）", async () => {
    const invalid: Array<[string, Record<string, unknown>]> = [
      ["Hailuo 1080P 只有 6s", { resolution: "1080P", duration: 10 }],
      ["Hailuo 768P 只有 6/10s", { duration: 12 }],
      ["Hailuo 没有 2K", { resolution: "2K" }],
      ["H3 缺 ratio", { model: "MiniMax-H3", resolution: "768P", duration: 6 }],
      ["H3 没有 480P", {
        model: "MiniMax-H3", resolution: "480P", duration: 6, ratio: "16:9",
      }],
      ["H3 时长上界 15", {
        model: "MiniMax-H3", resolution: "768P", duration: 16, ratio: "16:9",
      }],
      ["H3 时长下界 4（非整数也不行）", {
        model: "MiniMax-H3", resolution: "768P", duration: 3.5, ratio: "16:9",
      }],
      ["H3-Max 没有 2K", {
        model: "MiniMax-H3-Max", resolution: "2K", duration: 8,
      }],
      ["H3-Max 时长下界 5", {
        model: "MiniMax-H3-Max", resolution: "480P", duration: 4,
      }],
      ["H3-Max 时长上界 15", {
        model: "MiniMax-H3-Max", resolution: "768P", duration: 16,
      }],
      ["prompt 超上限", { prompt: "x".repeat(7001) }],
    ]
    for (const [why, over] of invalid) {
      const r = await submitOnce(over)
      expect(r.status, why).toBe("invalid")
      // 不合规的提交不摆审批卡（人工审批是稀缺资源）
      const d = await gateOnce(over)
      expect(d.kind, `${why}：门应当放行`).toBe("allow")
    }
  })

  it("合法组合：门摆审批卡（ask），工具体在放行后才可能碰通道", async () => {
    const ok: Array<Record<string, unknown>> = [
      { resolution: "1080P", duration: 6 },
      { model: "MiniMax-H3", resolution: "2K", duration: 15, ratio: "9:16" },
      { model: "MiniMax-H3-Max", resolution: "768P", duration: 5 },
      { prompt: "y".repeat(7000) },
    ]
    for (const over of ok) {
      const d = await gateOnce(over)
      expect(d.kind, JSON.stringify(over)).toBe("ask")
      expect(d.reason).toContain("[视频生成提交审批]")
    }
  })
})

describe("积分速查 ↔ 审批卡算账", () => {
  /** SKILL.md 速查行里抠 `≈ N 积分/秒`（H3 768P / 2K、H3-Max 480P 各一个）。 */
  function skillRate(re: RegExp): number {
    const m = SKILL.match(re)
    if (!m) throw new Error(`SKILL.md 积分速查缺条目：${re}`)
    return Number(m[1])
  }

  it("SKILL.md 速查表可解析且给出三档积分率 + 汇率", () => {
    expect(Number.isFinite(skillRate(/H3 768P ¥[\d.]+\/秒\s*≈ (\d+) 积分\/秒/))).toBe(true)
    expect(Number.isFinite(skillRate(/2K ¥[\d.]+\/秒\s*≈ (\d+) 积分\/秒/))).toBe(true)
    expect(Number.isFinite(skillRate(/H3 Max 480P ¥[\d.]+\/秒\s*≈ (\d+) 积分\/秒/))).toBe(true)
    expect(SKILL).toMatch(/1000 积分 = ¥7/)
  })

  it("审批卡的预估消耗 = SKILL.md 积分率 × 时长，汇率换算一致（漂移即红）", async () => {
    const rate768 = skillRate(/H3 768P ¥[\d.]+\/秒\s*≈ (\d+) 积分\/秒/)
    const rate2k = skillRate(/2K ¥[\d.]+\/秒\s*≈ (\d+) 积分\/秒/)
    const rateMax = skillRate(/H3 Max 480P ¥[\d.]+\/秒\s*≈ (\d+) 积分\/秒/)
    const cases: Array<{ over: Record<string, unknown>; rate: number; secs: number }> = [
      { over: { model: "MiniMax-H3", resolution: "768P", duration: 6, ratio: "16:9" }, rate: rate768, secs: 6 },
      { over: { model: "MiniMax-H3", resolution: "2K", duration: 4, ratio: "16:9" }, rate: rate2k, secs: 4 },
      { over: { model: "MiniMax-H3-Max", resolution: "480P", duration: 5 }, rate: rateMax, secs: 5 },
    ]
    for (const c of cases) {
      const credits = c.rate * c.secs
      const yuan = ((credits * 7) / 1000).toFixed(2)
      const d = await gateOnce(c.over)
      expect(d.kind, JSON.stringify(c.over)).toBe("ask")
      expect(d.reason, JSON.stringify(c.over)).toContain(`约 ${credits} 积分（≈¥${yuan}）`)
    }
  })

  it("Hailuo 审批卡走套餐额度口径（不烧积分），与 SKILL.md 同一句话", async () => {
    const d = await gateOnce({ resolution: "1080P", duration: 6 })
    expect(d.kind).toBe("ask")
    expect(d.reason).toContain("套餐额度（不烧积分）")
    expect(SKILL).toContain("Token Plan / M Plan 套餐额度")
  })
})

// ---------------------------------------------------------------------------
// D. inject 声明 ↔ apply 实际取用的 ctx 服务
// ---------------------------------------------------------------------------
//
// 这条断言来自两次真实事故的合并：
//  · 2026-10-18 首测：inject 漏了 'approval'，而工具体在 apply 期就取 ctx.approval
//    ——真 cordis 抛 "cannot get property ... without inject"，整个插件加载失败、
//    17 个工具面全丢，而宿主**毫无感知**（dsh 静默吞 apply 抛错，boot 照样成功）。
//  · 2026-10-20 评审：inject 多了 'approval' / 'skills'——声明了但宿主没提供的
//    服务会让 fiber 永远 pending，插件**同样永不生效**，症状一模一样。
// 所以规则是两条：装配期取用的服务必须被声明（inject 或 ctx.inject 的 deps），
// 而**可选服务不许进 inject**（进了就变成硬依赖）。
//
// 为什么 vitest 看不见：plugin.test.ts 的 fakeCtx 不校验 inject，假 ctx 上取什么
// 都返回 undefined，插件照样"跑通"。所以这条门禁必须静态读 src。

describe("inject 声明 ↔ apply 实际取用的 ctx 服务", () => {
  const SRC = fileURLToPath(new URL("../src/index.ts", import.meta.url))
  const source = readFileSync(SRC, "utf8")

  /** `export const inject = ['tools', 'systemPrompt', ...]` 里声明的服务名。 */
  function declaredInject(): string[] {
    const m = source.match(/export const inject\s*=\s*\[([^\]]*)\]/)
    if (!m) throw new Error("src/index.ts 找不到 `export const inject = [...]`")
    const body: string = m[1] ?? ""
    return [...body.matchAll(/['"]([^'"]+)['"]/g)].flatMap((x) => [x[1] ?? ""])
  }

  /** `ctx.inject(['skills'], …)` 这类「可选服务」的 deps 名单。 */
  function optionalInject(): string[] {
    const out: string[] = []
    for (const m of source.matchAll(/ctx\.inject\(\s*\[([^\]]*)\]/g)) {
      for (const s of m[1]!.matchAll(/['"]([^'"]+)['"]/g)) out.push(s[1] ?? "")
    }
    return out
  }

  /**
   * apply() 函数体里在**装配期**访问的 ctx 服务。装配期访问才是致命的：工具
   * execute 里的访问发生在 apply 成功之后，缺 inject 不会让整个插件加载失败。
   */
  function applyTimeServices(): string[] {
    const start = source.indexOf("export function apply(")
    if (start < 0) throw new Error("src/index.ts 找不到 `export function apply(`")
    const rest = source.slice(start + 1)
    const next = rest.search(/\nexport\s/)
    const text = next > 0 ? rest.slice(0, next) : rest
    const found = new Set<string>()
    for (const m of text.matchAll(/\bctx\.(\w+)\b/g)) found.add(m[1] ?? "")
    for (const m of text.matchAll(
      /\(\s*ctx\s+as\s+unknown\s+as\s+\{[\s\S]*?\}\s*\)\s*\.\s*(\w+)/g,
    )) found.add(m[1] ?? "")
    for (const m of text.matchAll(
      /\(\s*skillCtx\s+as\s+unknown\s+as\s+\{[\s\S]*?\}\s*\)\s*\.\s*(\w+)/g,
    )) found.add(m[1] ?? "")
    found.delete("effect")
    found.delete("inject")
    found.delete("on")
    return [...found].filter((name) => name.length > 0).sort()
  }

  it("inject 是显式声明且非空", () => {
    const declared = declaredInject()
    expect(declared.length).toBeGreaterThan(0)
    expect(new Set(declared).size).toBe(declared.length)
  })

  it("apply 装配期取用的每个 ctx 服务都被声明过（在 inject 里，或在 ctx.inject 的 deps 里）", () => {
    const declared = new Set([...declaredInject(), ...optionalInject()])
    const used = applyTimeServices()
    expect(used.length, "解析出的 apply 期服务应非空，否则断言本身失效").toBeGreaterThan(0)
    const missing = used.filter((service) => !declared.has(service))
    expect(
      missing,
      `apply 期访问了未声明的服务 ${missing.join(", ")}——真 cordis 会抛 ` +
        `"cannot get property ... without inject" 并静默丢掉整个工具面`,
    ).toEqual([])
  })

  it("可选服务（approval / skills）不进 inject——多声明等于把可选能力变成硬依赖", () => {
    const declared = new Set(declaredInject())
    for (const optional of ["approval", "skills"]) {
      expect(declared.has(optional), `inject 不该包含 ${optional}：宿主一缺它，插件永不生效`).toBe(false)
    }
    // 硬依赖必须在：工具注册与 systemPrompt 分节是插件的立身之本。
    for (const hard of ["tools", "systemPrompt"]) {
      expect(declared.has(hard), `inject 必须包含 ${hard}`).toBe(true)
    }
  })

  it("skills 走 ctx.inject 的可选通道（宿主没装 skills 服务就整段跳过，工具面不受影响）", () => {
    expect(optionalInject()).toContain("skills")
  })

  it("门禁能复现两次事故：inject 漏声明时报红、inject 多声明可选服务时报红", () => {
    // 负控制 1：少声明（2026-10-18 事故）——用到的服务不在声明里 → 必须报红。
    const used = applyTimeServices()
    const withoutApproval = declaredInject().filter((s) => s !== "approval")
    const gated = [...used, "approval"]
    const missing = gated.filter((s) => !withoutApproval.includes(s))
    expect(missing, "inject 漏声明时门禁必须报红").toContain("approval")
    // 负控制 2：多声明（2026-10-20 评审）——把 approval 写回 inject → 必须报红。
    const withApproval = [...declaredInject(), "approval"]
    expect(
      withApproval.filter((s) => ["approval", "skills"].includes(s)),
      "inject 含可选服务时门禁必须报红",
    ).toEqual(["approval"])
  })

  it("apply 期取用的服务集合确实非平凡（防止解析器静默失效）", () => {
    const used = applyTimeServices()
    for (const expected of ["tools", "systemPrompt", "skills"]) {
      expect(used, `apply 期必须解析出 ${expected}`).toContain(expected)
    }
  })
})

// ---------------------------------------------------------------------------
// E. 旗标词表 ↔ SKILL.md
// ---------------------------------------------------------------------------
//
// 旗标层以前零机检：CLI 改了旗标名，SKILL.md 照旧，模型照旧按旧名拼 argv——
// 线上才发现。SKILL.md 是**给智能体看的说明书**，它写的每个 CLI 旗标都必须
// 真实存在：这是「文档不许漂移」的最小可机检形态。
//
// 口径：旗标 = 库层源码里以字符串字面量出现的 '--xxx'（即真实可传的旗标）。
// 排除两类噪音：① 测试目录里的假旗标；② SKILL.md 里的 CSS 自定义属性
// （`--gold: #b8860b` 这种排版记号，不是 CLI 旗标）。

/** 库层源码（排除 test / node_modules）里的全部 '--xxx' 字面量。 */
function libraryFlags(): Set<string> {
  const out = new Set<string>()
  const walk = (dir: string) => {
    for (const e of readdirSync(dir)) {
      if (e === "test" || e === "node_modules" || e === "dist") continue
      const p = join(dir, e)
      if (statSync(p).isDirectory()) { walk(p); continue }
      if (!p.endsWith(".ts")) continue
      const t = readFileSync(p, "utf8")
      for (const m of t.matchAll(/['"](--[a-z][a-z0-9-]*)['"]/g)) out.add(m[1]!)
    }
  }
  walk(fileURLToPath(new URL("../../", import.meta.url)))
  return out
}

/** SKILL.md 里当 CLI 旗标用的 '--xxx'（排除 CSS 自定义属性）。 */
function skillFlags(): Array<{ skill: string; flag: string }> {
  const out: Array<{ skill: string; flag: string }> = []
  const skillsDir = fileURLToPath(new URL("../../../skills/", import.meta.url))
  for (const d of readdirSync(skillsDir)) {
    let text: string
    try { text = readFileSync(join(skillsDir, d, "SKILL.md"), "utf8") } catch { continue }
    for (const m of text.matchAll(/(--[a-z][a-z0-9-]*)(:?)/g)) {
      if (m[2]) continue // CSS 自定义属性（`--gold: …`），不是 CLI 旗标
      out.push({ skill: d, flag: m[1]! })
    }
  }
  return out
}

describe("旗标词表 ↔ SKILL.md", () => {
  it("SKILL.md 里写的每个 CLI 旗标都在库层真实存在（旗标改名 → 说明书漂移 → 红）", () => {
    const lib = libraryFlags()
    expect(lib.size, "库层旗标词表解析为空 = 解析器失效").toBeGreaterThan(10)
    const unknown = skillFlags().filter(({ flag }) => !lib.has(flag))
    expect(
      unknown.map((u) => `${u.skill}: ${u.flag}`),
      "SKILL.md 写了库层不存在的旗标——模型会照着拼一个不存在的参数",
    ).toEqual([])
  })

  it("负控制：解析器能看见 SKILL.md 的旗标（不是解析不出才绿）", () => {
    const flags = skillFlags()
    expect(flags.length, "SKILL.md 旗标应非空").toBeGreaterThan(5)
    expect(flags.some((f) => f.flag === "--facts")).toBe(true)
  })
})
