// plugin.test.ts — dsh 插件最小骨架（P1）的正面证据。
//
// 测试吃的是**构建产物** dist/index.mjs（dsh 宿主实际加载的那个文件），
// 不是 TS 源——整条链（esbuild 打包 + external 解析 + 插件形状 + 工具注册）
// 一次验证。dsh 侧的接缝（--patch 加载 + 激活）由 dsh web 启动实录证明
// （migration/README.md spike 3 结论）。
import { describe, expect, it } from "vitest"
import { fileURLToPath } from "node:url"
import { VERSION } from "@feuille/core"

interface Registered {
  name: string
  description: string
  parameters: Record<string, unknown>
  output: { schema: Record<string, unknown>; render: (args: unknown, value: unknown) => unknown[] }
  execute: (args: unknown, exec: unknown) => Promise<unknown>
}

/** 最小假 Cordis ctx：只提供 apply() 用到的 effect + tools.register 两个面。 */
function fakeCtx() {
  const registered: Registered[] = []
  const disposers: Array<() => void> = []
  return {
    registered,
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
  }
}

describe("dsh 插件骨架（吃构建产物 dist/index.mjs）", () => {
  it("apply() 在 ctx 上注册 usine_version 工具，schema 形状符合 dsh ToolDefinition", async () => {
    const plugin = await import(fileURLToPath(new URL("../dist/index.mjs", import.meta.url)))
    expect(plugin.name).toBe("feuille-usine")
    expect(plugin.inject).toContain("tools")

    const ctx = fakeCtx()
    ;(plugin.apply as (c: unknown) => void)(ctx)
    expect(ctx.registered.map((t) => t.name)).toEqual(["usine_version"])

    const tool = ctx.registered[0]!
    expect(tool.description).toContain("feuille")
    expect(tool.parameters).toEqual({ type: "object", properties: {}, additionalProperties: false })
    expect(tool.output.schema).toEqual({
      type: "object",
      properties: { version: { type: "string" } },
      required: ["version"],
      additionalProperties: false,
    })
    // 进程内 @feuille/core 调用接缝（无 subprocess 桥）
    const value = (await tool.execute({}, { signal: AbortSignal.timeout(5000) })) as { version: string }
    expect(value.version).toBe(VERSION)
    // render 是纯投影：Native text 块
    const blocks = tool.output.render({}, value) as Array<{ type: string; text: string }>
    expect(blocks).toEqual([{ type: "text", text: JSON.stringify(value) }])
  })

  it("反向验证：fiber 销毁（effect 回调反注册）后工具面清空", async () => {
    const plugin = await import(fileURLToPath(new URL("../dist/index.mjs", import.meta.url)))
    const ctx = fakeCtx()
    ;(plugin.apply as (c: unknown) => void)(ctx)
    expect(ctx.registered).toHaveLength(1)
    ctx.dispose()
    expect(ctx.registered).toHaveLength(0)
  })
})
