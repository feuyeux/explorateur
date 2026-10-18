// plugin-parity.test.ts — 智能体面钉版对账：工具面 ↔ CLI 路由 ↔ skills 知识三方一致。
//
// 「智能体面」（dsh 插件注册的工具 + skills howto）是 RSI wave 的正式改进
// 方向，而它横跨三处文本/代码：tools.ts 的 action 枚举、@feuille/cli 的
// COMMANDS 路由表、SKILL.md 的规格与积分速查。三处全靠人工约定同步——本
// 套件把约定钉成门禁：任何一侧漂移，`pnpm verify` 当场红，而不是等操作者
// 或模型在线上踩坑。
//
// 与 plugin.test.ts 的分工：那边吃构建产物 dist/index.mjs，验整条打包链 +
// 红线机制行为；这边吃 **src 源**（wave 实际编辑的面）做交叉对账。积分
// 数值的权威出处是 skills/video-generation/SKILL.md 的速查表——本套件从
// SKILL.md 读数、驱动审批卡算账，两边对不上就是红。
//
// 红线：本套件的所有 submit 用例都停在审批 rejected（never allowed-once），
// 根本走不到 mcode-tools 的 spawn 点；仍套 withoutMcodePath 作为结构性兜底
// ——测试在任何环境下都不得真的烧额度。
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { COMMANDS } from "@feuille/cli"
import type { ToolDefinition } from "@deepseek-ai/dsh-tools"

import { familyTools, usineVersion, videoGenerationTool } from "../src/tools.js"

// ---------------------------------------------------------------------------
// 通用件
// ---------------------------------------------------------------------------

const SKILL_PATH = fileURLToPath(
  new URL("../../../skills/video-generation/SKILL.md", import.meta.url))

/** SKILL.md 全文（读一次；缺文件 = 套件红，不静默跳过）。 */
const SKILL = readFileSync(SKILL_PATH, "utf8")

type ExecArg = Parameters<ToolDefinition["execute"]>[1]

/** 最小假 exec：有 agent（approval 可用），带可中止 signal（结构子集即可）。 */
function exec(): ExecArg {
  return {
    agent: { id: "parity" },
    signal: new AbortController().signal,
  } as unknown as ExecArg
}

/** 最小假 ctx：只挂 approval 服务，记录请求并返回固定结果（永不 allowed-once）。 */
function approvalCtx(outcome: string) {
  const requests: Array<Record<string, unknown>> = []
  return {
    requests,
    approval: {
      request: async (req: Record<string, unknown>) => {
        requests.push(req)
        return outcome
      },
    },
  }
}

/** 红线兜底：PATH 剥离下跑——测试用例必须连 spawn 点都到不了。 */
async function withoutMcodePath<T>(fn: () => Promise<T>): Promise<T> {
  const orig = process.env.PATH
  process.env.PATH = "/usr/bin:/bin"
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

/** 跑一次 submit，返回 {status, message}；停在 rejected，永不进通道。 */
async function submitOnce(over: Record<string, unknown> = {}) {
  const ctx = approvalCtx("rejected")
  const tool = videoGenerationTool(ctx)
  const r = (await withoutMcodePath(() =>
    tool.execute(submitArgs(over), exec()))) as { status: string; message: string }
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
// B. usine_video_generation ↔ skills/video-generation/SKILL.md
// ---------------------------------------------------------------------------

describe("视频线规格 ↔ SKILL.md 前置输入契约", () => {
  const tool = videoGenerationTool(approvalCtx("rejected"))
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

  it("边界矩阵：不合规格当场 invalid，不进审批（Hailuo 档位 / H3 整数与画幅 / H3-Max 档位 / prompt 上限）", async () => {
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
    }
  })

  it("合法组合越过机械门、停在审批（不 invalid 也不提交）", async () => {
    const ok: Array<Record<string, unknown>> = [
      { resolution: "1080P", duration: 6 },
      { model: "MiniMax-H3", resolution: "2K", duration: 15, ratio: "9:16" },
      { model: "MiniMax-H3-Max", resolution: "768P", duration: 5 },
      { prompt: "y".repeat(7000) },
    ]
    for (const over of ok) {
      const r = await submitOnce(over)
      expect(r.status).toBe("asked-rejected")
      expect(r.message).toContain("审批结果：rejected")
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
      const r = await submitOnce(c.over)
      expect(r.status, JSON.stringify(c.over)).toBe("asked-rejected")
      expect(r.message, JSON.stringify(c.over)).toContain(`约 ${credits} 积分（≈¥${yuan}）`)
    }
  })

  it("Hailuo 审批卡走套餐额度口径（不烧积分），与 SKILL.md 同一句话", async () => {
    const r = await submitOnce({ resolution: "1080P", duration: 6 })
    expect(r.status).toBe("asked-rejected")
    expect(r.message).toContain("套餐额度（不烧积分）")
    expect(SKILL).toContain("Token Plan / M Plan 套餐额度")
  })
})
