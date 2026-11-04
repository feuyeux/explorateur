// tts-connect.test.ts — 连接类错误的判定与重试口径（2026-11-04 实测补）。
//
// 为什么要有这个用例：到 speech.platform.bing.com 的 TCP 连接受网络侧影响，
// 6 次尝试只成 2 次；根因是 Node `ws` 走 `autoSelectFamily` 时每个地址只等
// `autoSelectFamilyAttemptTimeout`（默认 250ms），慢应答的地址全被放弃 →
// 抛 AggregateError（内含 ETIMEDOUT / ENETUNREACH）。修法两条：
//   ① 把该超时抬到秒级（CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS）；
//   ② 连接类错误按线性退避重试（isConnectError 判定）。
//
// 本用例离线跑：只断言**判定口径**与**超时值**，不触网。
// 「真的连得上」由真机批量预生成验证，不在单测里做网络依赖断言。
import { describe, expect, it } from "vitest"

import {
  CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS,
  isConnectError,
  NoAudioReceived,
} from "../src/tts/client.js"

/** 造一个带 socket errno 的错误。 */
function sockErr(code: string): Error {
  return Object.assign(new Error(`connect ${code}`), { code })
}

/** 造 Node 的 happy-eyeballs 失败形态：AggregateError 裹着多个内层 errno。 */
function aggErr(...codes: string[]): AggregateError {
  return new AggregateError(codes.map(sockErr), "")
}

describe("连接类错误判定（isConnectError）", () => {
  it("AggregateError 裹 ETIMEDOUT / ENETUNREACH → 算连接错误", () => {
    expect(isConnectError(aggErr("ETIMEDOUT", "ENETUNREACH"))).toBe(true)
    expect(isConnectError(aggErr("ECONNREFUSED", "ECONNRESET"))).toBe(true)
    expect(isConnectError(aggErr("EHOSTUNREACH", "EAI_AGAIN"))).toBe(true)
  })

  it("单层 socket errno → 算连接错误", () => {
    expect(isConnectError(sockErr("ETIMEDOUT"))).toBe(true)
    expect(isConnectError(sockErr("ENETUNREACH"))).toBe(true)
  })

  it("业务类错误 → 不算连接错误（不许重试）", () => {
    expect(isConnectError(new NoAudioReceived())).toBe(false)
    expect(isConnectError(new Error("bad voice"))).toBe(false)
    expect(isConnectError(sockErr("EACCES"))).toBe(false)
    expect(isConnectError(undefined)).toBe(false)
    expect(isConnectError("字符串错误")).toBe(false)
  })

  it("混合 errno（有一个不是连接错）→ 不算连接错误（不重试）", () => {
    // 口径是「全是连接错才重试」：混进别的错误说明根因不是网络，别烧重试。
    expect(isConnectError(aggErr("ETIMEDOUT", "EACCES"))).toBe(false)
  })
})

describe("autoSelectFamily 每地址等待（CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS）", () => {
  it("必须明显高于 Node 默认的 250ms", () => {
    // 默认 250ms 是这次故障的根因：慢应答的地址在应答之前就被放弃。
    expect(CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS).toBeGreaterThan(250)
  })

  it("也不能长到把失败拖成分钟级挂起（实测 8000ms → 失败要 20s+）", () => {
    expect(CONNECT_FAMILY_ATTEMPT_TIMEOUT_MS).toBeLessThanOrEqual(5_000)
  })
})
