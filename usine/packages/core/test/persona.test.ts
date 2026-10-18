// persona.test.ts — 人设契约校验器的反向验证（verify_personas.py 的 vitest 移植）。
//
// 第 0 条好数据放行：**28 人班底全部通过**（validatePersona 逐人零问题 +
// validateRoster 零问题）——判据写反时这条会全红。
//
// 反向：定向破坏必须被抓（每条对应一类真实退化）：
// 坏脸型（不在 FACE_SPECS）、坏姿态码（不在 POSE_CODES）、坏 hex、缺调色板键、
// 声线越安全域、locale 非法、档案字段缺失、moves 私加槽位、
// 班底撞 id、语种配对破坏（两人同 energy）。
// 夹具 = personas/personas.json（审计过的 28 人，经 data.personasDoc 原始清单）。
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import { personasDoc } from "../src/data.js"
import * as persona from "../src/persona.js"
import * as rig from "../src/rig.js"

type Json = Record<string, any>
const PERSONAS = personasDoc()["personas"] as Json[]

const tmpRoots: string[] = []
function writeTempRoster(plist: Json[]): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-persona-"))
  tmpRoots.push(d)
  writeFileSync(join(d, "personas.json"), JSON.stringify({ personas: plist }))
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("第 0 条好数据放行", () => {
  it("28 人班底逐人校验零问题", () => {
    const bad: string[] = []
    for (const p of PERSONAS) bad.push(...persona.validatePersona(p))
    expect(bad, bad.slice(0, 2).join("\n")).toEqual([])
  })

  it("班底级不变量通过（14 语种配对齐全）", () => {
    const roster = persona.validateRoster(PERSONAS)
    expect(roster, roster.slice(0, 2).join("\n")).toEqual([])
  })
})

describe("反向：定向破坏必须被抓", () => {
  const base = structuredClone(PERSONAS[0]!)  // xiaoman

  function corrupt(mutate: (p: Json) => void, expectKw: string, what: string): void {
    it(`${what} → 被抓`, () => {
      const p = structuredClone(base)
      mutate(p)
      const probs = persona.validatePersona(p)
      const hit = probs.some((s) => s.includes(expectKw))
      expect(hit, `漏了！问题列表：${probs.slice(0, 2).join(" / ")}`).toBe(true)
    })
  }

  corrupt((p) => { p["movement"]["face"] = "diamond" }, "FACE_SPECS", "坏脸型 diamond")
  corrupt((p) => { p["moves"]["wave"] = "moonwalk" }, "POSE_CODES", "moves.wave = 不存在的姿态码")
  corrupt((p) => { p["palette"]["skin"] = "#F5C9A" }, "#RRGGBB", "调色板坏 hex")
  corrupt((p) => { delete p["palette"]["outfitBottom"] }, "palette.outfitBottom", "缺调色板键")
  corrupt((p) => { p["voice"]["rate"] = "+99%" }, "安全域", "rate 越安全域 +99%")
  corrupt((p) => { p["voice"]["pitch"] = "-40Hz" }, "安全域", "pitch 越安全域 -40Hz")
  corrupt((p) => { p["locale"] = "zh_CN" }, "locale", "locale 分隔符非法")
  corrupt((p) => { p["quirk"] = "" }, "quirk", "档案字段 quirk 清空")
  corrupt((p) => { p["moves"]["backflip"] = "jump_celebrate" }, "槽位", "moves 私加槽位 backflip")
  corrupt((p) => { p["accessories"].push({ code: "watch", physics: "explode" }) },
    "physics", "挂件 physics 非法")
  corrupt((p) => { p["movement"]["blinkCycleSec"] = 0 }, "正数", "眨眼周期 0")
  corrupt((p) => { p["energy"] = "chaotic" }, "energy", "energy 非法")
})

describe("班底反向与注册表活性", () => {
  it("班底撞 id → 被抓", () => {
    const roster = structuredClone(PERSONAS)
    roster.push(structuredClone(roster[0]!))
    expect(persona.validateRoster(roster).some((s) => s.includes("重复"))).toBe(true)
  })

  it("同语种两人同 energy → 配对不变量被抓", () => {
    const roster2 = structuredClone(PERSONAS)
    roster2[1]!["energy"] = roster2[0]!["energy"]  // 同语种两人同 energy
    expect(persona.validateRoster(roster2).some((s) => s.includes("一活泼一沉稳"))).toBe(true)
  })

  it("FACE_SPECS 六型脸在位（校验对着它查，不另抄）", () => {
    expect(Object.keys(rig.FACE_SPECS).sort())
      .toEqual(["heart", "oval", "round", "square", "tall", "wide"])
  })

  it("POSE_CODES ≥ 30 码在位（moves 校验的现取来源）", () => {
    expect(rig.POSE_CODES.size).toBeGreaterThanOrEqual(30)
  })
})

describe("CLI 入口（feuille persona validate）", () => {
  it("缺省班底：28 人零问题，退出码 0", () => {
    const rc = persona.mainValidate([])
    expect(rc).toBe(0)
  })

  it("坏班底目录：逐人 + 班底问题逐条报出，退出码 1", () => {
    const bad = structuredClone(PERSONAS) as Json[]
    bad[0]!["id"] = bad[1]!["id"]  // 撞 id（班底级）
    bad[2]!["locale"] = "zh_CN"    // 逐人级
    const dir = writeTempRoster(bad)
    const rc = persona.mainValidate(["--personas", dir])
    expect(rc).toBe(1)
  })
})

