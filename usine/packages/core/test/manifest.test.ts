// manifest.test.ts — 发布清单机制的反向验证（verify_manifest.py 的 vitest 移植）。
//
// 第 0 条好数据放行（自包含合成夹具）：合成 12 语种 × 三平台文案稿全部解析
// 正确。反向各防一种退化：体例被改 → 拒解析；超限/无话题/钩子/条数不齐 → 抓；
// 手标字数错 → fillAnnotations 按 len() 回填；坑㉲ emoji 码位区间；素材缺失 →
// buildManifest 报「清单不齐」。
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import { FeuilleError } from "../src/errors.js"
import {
  buildManifest, checkCopy, fillAnnotations, hookShape, isEmoji, parseCopy,
} from "../src/manifest.js"

// 12 语种 × 三平台（合成夹具，自包含——通用能力的验证不依赖 examples 内容）
const LANGS: [string, string][] = [
  ["中文", "zh-CN"], ["英语", "en-US"], ["日语", "ja-JP"],
  ["韩语", "ko-KR"], ["法语", "fr-FR"], ["德语", "de-DE"],
  ["西班牙语", "es-ES"], ["俄语", "ru-RU"], ["阿拉伯语", "ar-SA"],
  ["印地语", "hi-IN"], ["葡萄牙语", "pt-BR"], ["意大利语", "it-IT"],
]

type Section = [number, string, string, string, string, string | null]

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-manifest-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
})

/** 按平台约定合成 12 语种文案稿：抖音 = 问句钩子 + 话题块、
 * 小红书 = emoji+问句钩子 + 话题在正文末行（无话题块）、B 站 = 陈述 + 话题块。 */
function makePlatformCopy(path: string, plat: string): void {
  const secs: Section[] = []
  LANGS.forEach(([lang, locale], i) => {
    const no = i + 1
    if (plat === "douyin") {
      secs.push([no, lang, locale, `一叶知秋·${lang}·第${String(no).padStart(2, "0")}话`,
        `秋天来了，${lang}里怎么形容它？第${String(no).padStart(2, "0")}话带你看。`,
        `#秋日 #${lang}`])
    } else if (plat === "xiaohongshu") {
      secs.push([no, lang, locale, `一叶知秋${String(no).padStart(2, "0")}·${lang}`,
        `🍂 秋天的${lang}你会说吗？第${String(no).padStart(2, "0")}话干货来啦。\n#秋日 #${lang}`,
        null])
    } else {
      secs.push([no, lang, locale, `【一叶知秋】第${String(no).padStart(2, "0")}话·${lang}·完整版`,
        `这一话用${lang}聊聊秋天。欢迎三连。`, `#秋日 #${lang}`])
    }
  })
  makeCopy(path, false, secs)
}

/** 合成一份文案稿夹具。sections: [no, lang, locale, title, body, topics] */
function makeCopy(path: string, withDuration: boolean, sections: Section[]): void {
  const out: string[] = []
  for (const [no, lang, locale, title, body, topics] of sections) {
    let head = `### ${String(no).padStart(2, "0")} · ${lang} \`${locale}\``
    if (withDuration) head += " · 00:52 · ✅ 已发布"
    out.push(head, "**标题**（99 字）", "```", title, "```",
      "**正文**（99 / 1000）", "```", body, "```")
    if (topics !== null) out.push("**话题**", "```", topics, "```")
    out.push(`源文件：\`build/video/${lang}_1080x1920.mp4\``, "")
  }
  writeFileSync(path, out.join("\n"), "utf8")
}

describe("好数据放行：合成 12 语种 × 三平台文案稿", () => {
  it.each([
    ["douyin", "douyin-copy.md", ["question"]],
    ["xiaohongshu", "xiaohongshu-copy.md", ["emoji+question"]],
    ["bilibili", "bilibili-copy.md", ["statement"]],
  ] as const)("%s：%s 全解析", (plat, fname, wantHooks) => {
    const d = tmp()
    const p = join(d, fname)
    makePlatformCopy(p, plat)
    const recs = parseCopy(p)
    expect(recs.map((r) => r.order)).toEqual(Array.from({ length: 12 }, (_, i) => i + 1))
    expect([...new Set(recs.map((r) => r.hook))].sort()).toEqual(wantHooks)
    expect(recs.every((r) => r.title && r.body && r.topics.length > 0 && r.locale
      && r.titleChars === [...r.title].length
      && r.bodyChars === [...r.body].length
      && r.topicCount === r.topics.length)).toBe(true)
    expect(checkCopy(p, plat, { expect: 12 })).toEqual([])
  })

  it("小红书话题从正文末行提取（无独立话题块的体例）", () => {
    const d = tmp()
    const p = join(d, "xiaohongshu-copy.md")
    makePlatformCopy(p, "xiaohongshu")
    const xhs = parseCopy(p)
    expect(xhs.every((r) => r.topics.length > 0 && r.topics[0] === "秋日")).toBe(true)
  })
})

describe("两版体例（带/不带时长）都解析", () => {
  const secs: Section[] = [
    [1, "中文", "zh-CN", "标题甲", "说到颜色，你会想到什么？正文一。", "#语言学习"],
    [2, "英语", "en-US", "标题乙", "🎨 秋天来了？正文二。\n#秋日", null],
  ]
  it("时长与已发布标记可选；源文件行与钩子分类", () => {
    const d = tmp()
    const p1 = join(d, "a.md")
    const p2 = join(d, "b.md")
    makeCopy(p1, true, secs)
    makeCopy(p2, false, secs)
    const ra = parseCopy(p1)
    const rb = parseCopy(p2)
    expect(ra.length).toBe(2)
    expect(rb.length).toBe(2)
    expect(ra[0]!.durationSec).toBe(52)
    expect(rb[0]!.durationSec).toBeNull()
    expect(ra[0]!.publishedMark).toBe(true)
    expect(rb[0]!.publishedMark).toBe(false)
    expect(rb[0]!.source!.endsWith("中文_1080x1920.mp4")).toBe(true)
    expect(rb[0]!.hook).toBe("question")
    expect(rb[1]!.hook).toBe("emoji+question")
  })
})

describe("体例被改 → 拒解析", () => {
  it("缺标题块 → 当场报错，不静默降级", () => {
    const d = tmp()
    const broken = join(d, "broken.md")
    writeFileSync(broken, "### 01 · 中文 `zh-CN`\n**正文**\n```\n只有正文没标题。\n```\n", "utf8")
    expect(() => parseCopy(broken)).toThrow(FeuilleError)
    expect(() => parseCopy(broken)).toThrow("缺标题或正文块")
  })
  it("文案文件不存在 → 显式报错", () => {
    expect(() => parseCopy("/nonexistent/nope.md")).toThrow("文案事实源不存在")
  })
})

describe("平台检查：超限/无话题/钩子/条数", () => {
  it("四类问题全抓", () => {
    const d = tmp()
    const bad = join(d, "bad.md")
    makeCopy(bad, false, [
      [1, "中文", "zh-CN", "这是一个特别特别特别特别特别长的标题超过二十个字了",
        "🎨 有 emoji 开场？但约定要 question。", "#话题"],
      [2, "英语", "en-US", "好标题", "没有话题符号的话题块省略。", null],
    ])
    const probs = checkCopy(bad, "xiaohongshu", { expect: 3 })
    expect(probs.some((p) => p.includes("标题"))).toBe(true)
    expect(probs.some((p) => p.includes("钩子"))).toBe(true)
    expect(probs.some((p) => p.includes("话题"))).toBe(true)
    expect(probs.some((p) => p.includes("条数"))).toBe(true)
  })
})

describe("坑㉲：emoji 判定走码位区间", () => {
  it("`ch in '🎰-🫿'` 成员测试恒 False——本模块按码位区间判", () => {
    expect(isEmoji("🎨")).toBe(true)
    expect(isEmoji("标")).toBe(false)
    expect("🎰-🫿".includes("🎨")).toBe(false) // 坑本身
  })
  it("hookShape：首句形态交叉分类", () => {
    expect(hookShape("🎨 秋天来了？")).toBe("emoji+question")
    expect(hookShape("秋天来了？")).toBe("question")
    expect(hookShape("🎨 秋天来了。")).toBe("emoji")
    expect(hookShape("秋天来了。")).toBe("statement")
    expect(hookShape("")).toBe("empty")
    // 取首句不取首行：问句在最前、后面还有句读，按行切会判成陈述句
    expect(hookShape("你见过吗？秋风吹尽满山金，一叶知秋。")).toBe("question")
  })
})

describe("fillAnnotations：手标错 → len() 实测回填（往返一致）", () => {
  it("4 处全被回填，回填后标注 = len() 实测", () => {
    const d = tmp()
    const p = join(d, "b.md")
    makeCopy(p, false, [
      [1, "中文", "zh-CN", "标题甲", "说到颜色，你会想到什么？正文一。", "#语言学习"],
      [2, "英语", "en-US", "标题乙", "🎨 秋天来了？正文二。\n#秋日", null],
    ])
    const recs = parseCopy(p)
    const n = fillAnnotations(p, recs)
    expect(n).toBe(4)
    const recs2 = parseCopy(p)
    expect(recs2.every((r) => r.titleChars === [...r.title].length)).toBe(true)
    const text = readFileSync(p, "utf8")
    expect(text).toContain("（3 字）") // 标题甲 = 3 字
  })
})

describe("buildManifest：素材存在性前置", () => {
  it("封面不存在 → 清单不齐；素材齐 → 清单 2 条、话题成列表、落盘可回读", () => {
    const d = tmp()
    const p = join(d, "b.md")
    makeCopy(p, false, [
      [1, "中文", "zh-CN", "标题甲", "说到颜色，你会想到什么？正文一。", "#语言学习"],
      [2, "英语", "en-US", "标题乙", "🎨 秋天来了？正文二。\n#秋日", null],
    ])
    const vid = join(d, "video", "中文_1080x1920.mp4")
    const cov = join(d, "covers", "中文_douyin34_1080x1440.png")
    mkdirSync(join(d, "video"), { recursive: true })
    mkdirSync(join(d, "covers"), { recursive: true })
    writeFileSync(vid, "x")
    const plans = {
      douyin: { copy: p, video: () => vid, cover: () => cov },
    }
    const [, probs1] = buildManifest(plans)
    expect(probs1.some((p2) => p2.includes("封面缺失"))).toBe(true)
    writeFileSync(cov, "x")
    const [man, probs2] = buildManifest(plans, join(d, "manifest.json"))
    expect(probs2).toEqual([])
    expect(man.douyin!.length).toBe(2)
    expect(man.douyin![0]!.video.endsWith(".mp4")).toBe(true)
    expect(man.douyin![0]!.tags).toEqual(["语言学习"])
    expect(man.douyin![1]!.tags).toEqual(["秋日"])
    const back = JSON.parse(readFileSync(join(d, "manifest.json"), "utf8"))
    expect(back.douyin).toEqual(man.douyin)
  })
})
