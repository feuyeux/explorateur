// metrics.test.ts — 指标回流机制的反向验证（verify_metrics.py 的 vitest 移植）。
//
// 第 0 条好数据放行：好台账 + 好指标合并后 check 全过。反向各防一种真实退化：
// 悬空引用当场报错；两级凭据分开判；指标取值域全抓；null ≠ 0；部分回填不炸；
// 样本不足不排名；台账落盘往返 + 版本护栏。
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"

import { data } from "../src/index.js"
import { FeuilleError } from "../src/errors.js"
import { analyze, bucket, check, ledgerPath, load, mergeResults, save, VERSION } from "../src/metrics.js"

type Json = data.Json

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-metrics-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
  vi.restoreAllMocks()
})

let writes: string[] = []
function captureWrites(): void {
  writes = []
  vi.spyOn(process.stdout, "write").mockImplementation((chunk: unknown) => {
    writes.push(String(chunk))
    return true
  })
}

function makeVid(d: string): string {
  const vid = join(d, "build", "video", "x.mp4")
  mkdirSync(join(d, "build", "video"), { recursive: true })
  writeFileSync(vid, "x")
  return vid
}

function entry(key: string, kw: Record<string, unknown> = {}): Json {
  return {
    key, platform: "douyin", locale: "zh-CN", lang: "中文",
    title_chars: 20, video: "build/video/x.mp4", metrics: null, ...kw,
  }
}

describe("好数据放行", () => {
  it("合并按整体替换 metrics；好台账 check 全过", () => {
    const d = tmp()
    makeVid(d)
    const good: Json = { version: VERSION, entries: {
      "中文/zh-CN/douyin": entry("中文/zh-CN/douyin",
        { published: true, url: "https://…", metrics: { views: 100, likes: 10, completionRate: 0.52 } }),
      "英语/en-US/douyin": entry("英语/en-US/douyin",
        { locale: "en-US", lang: "英语", published: true,
          verifiedBy: "回列表核验", verifiedAt: "2026-10-07",
          metrics: { views: 200, likes: 20, completionRate: 0.61 } }),
    } }
    const n = mergeResults(good, { results: {
      "中文/zh-CN/douyin": { published: true, url: "https://…", metrics: { views: 100 } },
    } })
    const m = good.entries["中文/zh-CN/douyin"].metrics
    expect(n).toBe(1)
    expect(m).toEqual({ views: 100 })
    expect(check(good, d)).toEqual([])
  })
})

describe("悬空引用 → 当场报错", () => {
  it("键不在台账 → 报错，不静默挂错行", () => {
    const doc: Json = { version: VERSION, entries: { "a/zh-CN/douyin": entry("a/zh-CN/douyin", { lang: "a" }) } }
    expect(() => mergeResults(doc, { results: { "不存在/zh-CN/douyin": { published: true } } }))
      .toThrow(FeuilleError)
    expect(() => mergeResults(doc, { results: { "不存在/zh-CN/douyin": { published: true } } }))
      .toThrow("没有对应记录")
  })
})

describe("两级凭据分开判", () => {
  it("只有方式没日期 → 报「缺核验日期」，不是「无任何凭据」", () => {
    const d = tmp()
    makeVid(d)
    const doc: Json = { version: VERSION, entries: {
      "a/zh-CN/douyin": entry("a/zh-CN/douyin", { lang: "a", published: true, verifiedBy: "回列表核验" }),
      "b/zh-CN/douyin": entry("b/zh-CN/douyin", { lang: "b", published: true }),
      "c/zh-CN/douyin": entry("c/zh-CN/douyin", { lang: "c", published: true, url: "https://…" }),
    } }
    const probs = check(doc, d)
    const p1 = probs.filter((p) => p.startsWith("a/"))
    const p2 = probs.filter((p) => p.startsWith("b/"))
    const p3 = probs.filter((p) => p.startsWith("c/"))
    expect(p1.length).toBe(1)
    expect(p1[0]).toContain("缺 verifiedAt")
    expect(p2.length).toBe(1)
    expect(p2[0]).toContain("无任何凭据")
    expect(p3).toEqual([])
  })
})

describe("指标取值域 + 指标挂未发布", () => {
  it("计数负数 / 比率越界 / 未知指标 / 指标挂未发布 → 全抓", () => {
    const d = tmp()
    makeVid(d)
    const doc: Json = { version: VERSION, entries: {
      "d/zh-CN/douyin": entry("d/zh-CN/douyin", { published: true, url: "u", metrics: { views: -5 } }),
      "e/zh-CN/douyin": entry("e/zh-CN/douyin", { published: true, url: "u", metrics: { completionRate: 1.5 } }),
      "f/zh-CN/douyin": entry("f/zh-CN/douyin", { published: true, url: "u", metrics: { happiness: 3 } }),
      "g/zh-CN/douyin": entry("g/zh-CN/douyin", { metrics: { views: 100 } }),
    } }
    const probs = check(doc, d)
    expect(probs.some((p) => p.includes("不是非负整数"))).toBe(true)
    expect(probs.some((p) => p.includes("0–1"))).toBe(true)
    expect(probs.some((p) => p.includes("未知指标"))).toBe(true)
    expect(probs.some((p) => p.includes("没标已发布"))).toBe(true)
  })
})

describe("null ≠ 0 与部分回填", () => {
  it("全 null 台账分析 → 如实说「不知道」（退出码 0，不编数据）", () => {
    const empty: Json = { version: VERSION, entries: {
      "h/zh-CN/douyin": entry("h/zh-CN/douyin"),
      "i/en-US/douyin": entry("i/en-US/douyin") } }
    captureWrites()
    const rc = analyze(empty)
    expect(rc).toBe(0)
    const out = writes.join("")
    expect(out).toContain("不知道")
    expect(out).toContain("尚未回填")
  })
  it("只回填 likes 时查 views → 0/6 如实报告，不炸", () => {
    const entries: Json = {}
    for (let i = 0; i < 6; i++) {
      entries[`lang${i}/zh-CN/douyin`] = entry(`lang${i}/zh-CN/douyin`,
        { published: true, url: "u", metrics: { likes: 10 + i } })
    }
    captureWrites()
    const rc = analyze({ version: VERSION, entries }, "views")
    expect(rc).toBe(0)
    const out = writes.join("")
    expect(out).toContain("有指标 0/6")
  })
})

describe("样本不足不排名 + 分箱", () => {
  it("question（n=6）排名，emoji（n=4）不排", () => {
    const entries: Json = {}
    for (let i = 0; i < 6; i++) {
      entries[`x${i}/zh-CN/douyin`] = entry(`x${i}/zh-CN/douyin`,
        { published: true, url: "u", hook: "question", title_chars: 120, metrics: { views: 100 + i * 50 } })
    }
    for (let i = 0; i < 4; i++) {
      entries[`y${i}/zh-CN/douyin`] = entry(`y${i}/zh-CN/douyin`,
        { published: true, url: "u", hook: "emoji", title_chars: 30, metrics: { views: 999 + i } })
    }
    captureWrites()
    analyze({ version: VERSION, entries }, "views", { dims: [["hook", "钩子", false]] })
    const out = writes.join("")
    expect(out).toContain("question")
    expect(out.split("样本不足")[0]).not.toContain("emoji")
    expect(out).toContain("样本不足未排")
  })
  it("分箱正确", () => {
    expect(bucket(120)).toBe("100-150")
    expect(bucket(20)).toBe("0-100")
    expect(bucket(null)).toBe("(缺)")
  })
})

describe("台账落盘往返 + 版本护栏", () => {
  it("save→load 往返一致；版本不匹配拒读", () => {
    const d = tmp()
    const good: Json = { version: VERSION, entries: {
      "中文/zh-CN/douyin": entry("中文/zh-CN/douyin",
        { published: true, url: "https://…", metrics: { views: 100 } }),
    } }
    save(d, good)
    expect(load(d).entries["中文/zh-CN/douyin"].metrics.views).toBe(100)
    const bad = load(d)
    bad.version = 0
    save(d, bad)
    expect(() => load(d)).toThrow(FeuilleError)
    expect(() => load(d)).toThrow("版本")
    // 台账不存在 → 显式报错
    const d2 = tmp()
    expect(() => load(d2)).toThrow("台账不存在")
    expect(ledgerPath(d)).toBe(join(d, "publish", "ledger.json"))
  })
})
