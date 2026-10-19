// lesson.test.ts — verify_lesson.py §3 的 TS 对应（doctor 班底体检接线）+
// cmd_new / cmd_doctor 的移植验证。
//
// **doctor 班底体检接线（verify_lesson.py 同款三断言）**：坏班底（id 重复——
// 原始清单才抓得到，{id: persona} 索引会静默折叠）必须报 FAIL，好班底必须报
// OK。判定本体（validatePersona / validateRoster）的反向验证在 persona.test.ts，
// 这里验的是 lesson doctor 的接线（逐人走 personasDoc 原始清单）。
//
// 其余覆盖：scaffold_brief 的键序与错误渠道（style/shape/scenes/tokens 各打一枪）、
// 空跑草稿自证、freshness 深比较（45 与 PyFloat(45.0) 键序无关互等）、
// baselineHits 的「应命中数」口径、printReport 的显示宽度对齐、doctor 退出码。
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LESSONS_DIR } from "../src/data.js"
import { FeuilleError } from "../src/errors.js"
import * as lesson from "../src/lesson.js"
import * as ps from "../src/parse_scene.js"
import { SCENES } from "../src/scenes.js"
import { saveBaseline } from "../src/framehash.js"

const LESSON_ID = "guangchaoshi-逛超市"
const LESSON_DIR = join(LESSONS_DIR, LESSON_ID)

const tmps: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-lesson-"))
  tmps.push(d)
  return d
}
afterEach(() => {
  for (const d of tmps.splice(0)) rmSync(d, { recursive: true, force: true })
  vi.restoreAllMocks()
})

/** 开一门最小课（真实 languages/personas、临时 lessons）→ 返回 lessons 目录。 */
function newLesson(lessonsDir: string, extra: string[] = []): number {
  return lesson.cmdNew(["fruit", "--title", "水果", "--tokens", "apple:#D8453B,pear:#D9A62E",
    "--lessons", lessonsDir, ...extra])
}

/** 捕获 console.log 的返回行数组（Python print 的对应物）。 */
function captureLog(): string[] {
  const lines: string[] = []
  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => {
    lines.push(a.map(String).join(" "))
  })
  return lines
}


describe("doctor 班底体检接线（verify_lesson.py §3 对应）", () => {
  it("坏班底（id 重复，原始清单）→ FAIL 且 detail 含「重复」", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    mkdirSync(join(ld, "x"), { recursive: true })
    const bad = join(d, "personas")
    mkdirSync(bad)
    // 重复 id 只有**原始清单**抓得到：{id: persona} 索引会把第二条静默折叠
    // ——这正是班底体检走 personasDoc() 而不是 personas() 的原因。
    writeFileSync(join(bad, "personas.json"), JSON.stringify({ personas: [
      { id: "dup", locale: "zh-CN", gender: "female", energy: "lively" },
      { id: "dup", locale: "zh-CN", gender: "female", energy: "lively" },
    ] }), "utf8")

    const rep = lesson.tierReport("x", ld, bad)
    const roster = rep.checks.filter((c) => c.name === "班底体检")
    expect(roster.length).toBeGreaterThan(0)
    expect(roster[0]!.state).toBe(lesson.FAIL)
    expect(roster[0]!.detail).toContain("重复")
  })

  it("好班底（feuille 缺省班底）→ OK", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    mkdirSync(join(ld, "x"), { recursive: true })
    const rep = lesson.tierReport("x", ld, undefined)   // 缺省 = feuille 28 人班底
    const roster = rep.checks.filter((c) => c.name === "班底体检")
    expect(roster.length).toBeGreaterThan(0)
    expect(roster[0]!.state).toBe(lesson.OK)
    expect(roster[0]!.detail).toMatch(/人零问题（id 唯一 \/ 配对齐）$/)
  })
})


describe("cmd_new：开坑", () => {
  it("scaffold + 空跑草稿自证 + 落盘（键序 = 落库序）", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    const lines = captureLog()
    expect(newLesson(ld)).toBe(0)

    const briefPath = join(ld, "fruit", "brief.json")
    const raw = readFileSync(briefPath, "utf8")
    expect(raw.endsWith("\n")).toBe(true)
    const brief = JSON.parse(raw)
    expect(Object.keys(brief)).toEqual(["sceneId", "title", "goal", "structure",
      "description", "form", "durationBudget", "noteFloor", "askBalance", "locales",
      "lines", "tokens", "devices", "roles", "skeleton", "spec", "noteOn", "stage"])
    // rounds=3 → 5+2×3 = 11 行（换课只换 rounds，不手算 n-K 边界）
    expect(brief["lines"]).toBe(11)
    expect(brief["tokens"]).toEqual([
      { key: "apple", chip: "#D8453B" }, { key: "pear", chip: "#D9A62E" }])
    expect(brief["devices"]["zh-CN"]).toEqual({
      style: "tray", shape: "round", cellW: 112, cellH: 112, well: "#F5F3EE" })
    expect(brief["skeleton"].length).toBe(5)
    expect(brief["noteOn"]).toEqual({ bye: ["", "exit"] })   // A 出画 / B 原地挥手
    expect(brief["spec"]["open.pose"]).toBe("bounce-in both-hands")

    // 打印：显示路径相对项目根（lessons 上推一层），显示代码不该让命令失败
    expect(lines.some((l) => l.includes("已写 lessons/fruit/brief.json") || l.includes("已写 lessons\\fruit\\brief.json"))).toBe(true)
    expect(lines.some((l) => l.includes("选角已验：zh-CN") && l.includes("×"))).toBe(true)
    expect(lines.some((l) => l.includes("空跑草稿通过——这份 brief 渲得出来"))).toBe(true)
    expect(lines.some((l) => l.includes("⚑ note-floor=0"))).toBe(true)
  })

  it("id / 选角 / 旗标错误渠道（各打一枪，判据与被测分开）", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    // 课程 id：路径分隔符 / 前导点都拒（= lessons/<id>/ 的目录名契约）
    expect(() => lesson.cmdNew(["a/b", "--title", "t", "--lessons", ld]))
      .toThrow(/课程 id 不合法：'a\/b'/)
    expect(() => lesson.cmdNew([".hid", "--title", "t", "--lessons", ld]))
      .toThrow(/课程 id 不合法/)
    // tokens：缺 chip / 空串 / 重复 key / 坏色片
    expect(() => newLesson(ld, ["--tokens", "keyonly"])).toThrow(/--tokens 项缺 chip：'keyonly'/)
    expect(() => newLesson(ld, ["--tokens", "  "])).toThrow(/--tokens 是空的/)
    expect(() => newLesson(ld, ["--tokens", "a:#111111,a:#222222"])).toThrow(/重复 key：a/)
    expect(() => newLesson(ld, ["--tokens", "a:#12"])).toThrow(/像色片但不是 #RRGGBB/)
    expect(() => newLesson(ld, ["--tokens", "a:"])).toThrow(/chip 为空/)
    // 语种 / 轮数 / 背景原语 / 装置
    expect(() => newLesson(ld, ["--locales", "xx-XX"])).toThrow(/没有语种目录：\['xx-XX'\]/)
    expect(() => newLesson(ld, ["--rounds", "0"])).toThrow(/--rounds 至少 1/)
    expect(() => newLesson(ld, ["--scenes", "nope"])).toThrow(/不存在的背景原语：\['nope'\]/)
    expect(() => newLesson(ld, ["--style", "nope"])).toThrow(/不在 DEVICE_STYLES 注册表内/)
    expect(() => newLesson(ld, ["--shape", "nope"])).toThrow(/--shape 'nope' 不合法/)
  })

  it("--tokens-file（chip 含逗号时的正道）与 --scenes 写进 devices", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    const tf = join(d, "tokens.json")
    writeFileSync(tf, JSON.stringify([
      { key: "hello", chip: "你好，世界" }]), "utf8")
    const sceneName = Object.keys(SCENES)[0]!
    expect(newLesson(ld, ["--tokens-file", tf, "--scenes", sceneName])).toBe(0)
    const brief = JSON.parse(readFileSync(join(ld, "fruit", "brief.json"), "utf8"))
    expect(brief["tokens"]).toEqual([{ key: "hello", chip: "你好，世界" }])
    expect(brief["devices"]["zh-CN"]["scenes"]).toEqual([sceneName])
  })

  it("拒覆盖已有 brief；--force 覆盖", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    expect(newLesson(ld)).toBe(0)
    expect(() => newLesson(ld)).toThrow(/已存在。加 --force 覆盖。/)
    expect(newLesson(ld, ["--force"])).toBe(0)
  })

  it("用法错 → 2（argparse 同款口径：缺 id / 缺 --title / 坏 int / 坏 choices）", () => {
    const ld = join(tmp(), "lessons")
    expect(lesson.cmdNew(["--title", "t", "--lessons", ld])).toBe(2)
    expect(lesson.cmdNew(["fruit", "--lessons", ld])).toBe(2)
    expect(newLesson(ld, ["--rounds", "abc"])).toBe(2)
    expect(newLesson(ld, ["--ask-balance", "nope"])).toBe(2)
  })
})


describe("tierReport：七层体检", () => {
  it("只有 brief 的新课：① OK、②③④⑦ TODO、⑤ 无行、⑥ TODO、无 FAIL", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    newLesson(ld)
    const rep = lesson.tierReport("fruit", ld)
    const by = (name: string) => rep.checks.filter((c) => c.name === name)
    expect(by("brief.json")[0]!.state).toBe(lesson.OK)
    expect(by("brief.json")[0]!.detail).toContain("2 token × 2 语种 · 11 行 · style={'tray'}")
    expect(by("scene.md")[0]!.state).toBe(lesson.TODO_STATE)
    expect(by("scene.json")[0]!.detail).toBe("没有剧本可解析")
    expect(by("成片")[0]!.detail).toBe("等 scene.json 出来")
    expect(by("平台文案")[0]!.state).toBe(lesson.TODO_STATE)
    expect(by("发布台账")[0]!.detail).toBe("台账里没有这课")
    expect(by("场景线验收")[0]!.detail).toBe("等成片出来")
    // ⑤ 文档只在 locs 非空时出现——新课还没有语种清单，整层无行
    expect(rep.checks.filter((c) => c.tier === "⑤文档").length).toBe(0)
    expect(rep.failed.length).toBe(0)
  })

  it("真实课件（金样本）：freshness 深比较（键序无关、45==45.0）→ OK；改 json → FAIL", () => {
    const d = tmp()
    const ld = join(d, "lessons", LESSON_ID)
    mkdirSync(ld, { recursive: true })
    copyFileSync(join(LESSON_DIR, "scene.md"), join(ld, "scene.md"))
    expect(ps.mainParse(["--scene", LESSON_ID, "--lessons", join(d, "lessons")])).toBe(0)

    const rep = lesson.tierReport(LESSON_ID, join(d, "lessons"))
    const by = (name: string) => rep.checks.filter((c) => c.name === name)
    // parseScene 出的 durationBudget 是 PyFloat(45.0)，落库 JSON 回读是 45：
    // Python 45 == 45.0 为 True——pyEq 必须同口径，否则每课都误报「不新鲜」
    expect(by("scene.json 新鲜度")[0]!.state).toBe(lesson.OK)
    expect(by("schema 前置校验")[0]!.state).toBe(lesson.OK)
    expect(by("班底体检")[0]!.state).toBe(lesson.OK)

    // 改 json 不重跑 parse = 最阴的漂移：成片与剧本脱节而 git diff 干净
    const stale = JSON.parse(readFileSync(join(ld, "scene.json"), "utf8"))
    stale["title"] = "漂移"
    writeFileSync(join(ld, "scene.json"), JSON.stringify(stale), "utf8")
    const rep2 = lesson.tierReport(LESSON_ID, join(d, "lessons"))
    expect(rep2.checks.filter((c) => c.name === "scene.json 新鲜度")[0]!.state)
      .toBe(lesson.FAIL)

    // ④ 成片：有 locs 但 build/scene/audio 没产物 → 逐项 TODO
    const rep3 = lesson.tierReport(LESSON_ID, join(d, "lessons"))
    const tts = rep3.checks.filter((c) => c.name === "语音")[0]!
    expect(tts.state).toBe(lesson.TODO_STATE)
    expect(tts.detail).toMatch(/^缺 \d+ 语种：/)
    expect(rep3.checks.filter((c) => c.name === "逐帧像素基线")[0]!.state)
      .toBe(lesson.SKIP)   // 还没有基线表 → SKIP，不是 TODO（「没渲」≠「漏了」）
  })
})


describe("baselineHits：「应命中数」口径", () => {
  it("命中/应命中/路径；空表与缺表都是 (0,0)", () => {
    const d = tmp()
    const baseP = join(d, "base.txt")
    saveBaseline({ "scene-x_zh-CN.mp4": "h1", "other.mp4": "h2" }, baseP)
    const [have, total, p] = lesson.baselineHits("x", ["zh-CN", "en-US"], d, baseP)
    expect([have, total]).toEqual([1, 2])
    expect(p).toBe(baseP)
    // 「跑过了」和「覆盖到这课了」是两件事：表存在但没这门课 → 0/2
    const [h2] = lesson.baselineHits("y", ["zh-CN"], d, baseP)
    expect(h2).toBe(0)
    // 新课刚建：命中 0 / 应命中 0 = 「还没渲」，不是「漏了基线」
    const empty = join(d, "empty.txt")
    saveBaseline({}, empty)
    expect(lesson.baselineHits("x", ["zh-CN"], d, empty).slice(0, 2)).toEqual([0, 0])
    expect(lesson.baselineHits("x", ["zh-CN"], d, join(d, "nope.txt")).slice(0, 2))
      .toEqual([0, 0])
  })
})


describe("printReport：显示宽度对齐", () => {
  it("CJK 记 2 格的 _pad：表格两行在同一显示列收尾", () => {
    const rep = new lesson.Report("x")
    rep.checks.push({ tier: "①创意", name: "brief.json", state: lesson.OK, detail: "d", nxt: "" })
    rep.checks.push({ tier: "①创意", name: "班底体检", state: lesson.OK, detail: "d", nxt: "" })
    const lines = captureLog()
    lesson.printReport(rep)
    const row = (i: number) => lines.filter((l) => l.startsWith("  [ ok ]"))[i]!
    // 显示列宽（CJK 记 2）：JS indexOf 记 UTF-16 下标，「班底体检」4 字符占 8 列
    const dispCol = (s: string, i: number) => [...s.slice(0, i)]
      .reduce((w, ch) => w + (ch.codePointAt(0)! >= 0x2e80 ? 2 : 1), 0)
    // "brief.json" 9 列 vs "班底体检" 8 列——补齐后两行的 detail 起始显示列一致
    expect(dispCol(row(0), row(0).indexOf("d"))).toBe(28)
    expect(dispCol(row(1), row(1).indexOf("d"))).toBe(28)
    expect(lines[0]).toBe("=".repeat(78))
    expect(lines).toContain("课程体检：x")
    expect(lines.some((l) => l.includes("x：还差 0 项") || l.includes("x：就绪"))).toBe(true)
  })

  it("TODO/FAIL 行带「└─ 下一步：」；OK/SKIP 行不带", () => {
    const rep = new lesson.Report("x")
    rep.checks.push({ tier: "②剧本", name: "scene.md", state: lesson.TODO_STATE,
      detail: "还没有剧本", nxt: "feuille scene draft …" })
    rep.checks.push({ tier: "②剧本", name: "已定稿", state: lesson.OK,
      detail: "d", nxt: "不该出现" })
    const lines = captureLog()
    lesson.printReport(rep)
    expect(lines.some((l) => l.includes("└─ 下一步：feuille scene draft"))).toBe(true)
    expect(lines.some((l) => l.includes("不该出现"))).toBe(false)
  })
})


describe("cmd_doctor：退出码与清单", () => {
  it("还没有课 → 打印开坑指引 + 0", () => {
    const d = tmp()
    const lines = captureLog()
    expect(lesson.cmdDoctor(["--lessons", join(d, "nope")])).toBe(0)
    expect(lines.some((l) => l.includes("还没有课"))).toBe(true)
  })

  it("--scene 指到不存在的课 → 打印 + 1", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    mkdirSync(ld, { recursive: true })
    const lines = captureLog()
    expect(lesson.cmdDoctor(["--scene", "x", "--lessons", ld])).toBe(1)
    expect(lines.some((l) => l.includes("没有 lessons/x/"))).toBe(true)
  })

  it("新课体检：有欠账但无 FAIL → 0；--strict 把硬欠账计失败 → 1", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    newLesson(ld)
    const lines = captureLog()
    expect(lesson.cmdDoctor(["--scene", "fruit", "--lessons", ld])).toBe(0)
    expect(lines.some((l) => l.includes("fruit：还差"))).toBe(true)
    // ②③④⑦ 不是可选拝始化层：--strict 下这些 todo 计失败
    expect(lesson.cmdDoctor(["--scene", "fruit", "--lessons", ld, "--strict"])).toBe(1)
  })

  it("真实课件（md+json 就绪、产物未渲）：无 FAIL → 0；--strict 计硬层欠账 → 1", () => {
    const d = tmp()
    const ld = join(d, "lessons", LESSON_ID)
    mkdirSync(ld, { recursive: true })
    copyFileSync(join(LESSON_DIR, "scene.md"), join(ld, "scene.md"))
    copyFileSync(join(LESSON_DIR, "scene.json"), join(ld, "scene.json"))
    const lines = captureLog()
    // ④成片/⑦验收 欠账是 pending 不是 FAIL：非 strict 放行（文档层发布层同理可选）
    expect(lesson.cmdDoctor(["--scene", LESSON_ID, "--lessons", join(d, "lessons")])).toBe(0)
    expect(lines.some((l) => l.includes(`${LESSON_ID}：还差`))).toBe(true)
    // --strict：④成片（硬层）的 pending 计失败；⑤文档/⑥发布（OPTIONAL）不计——
    // 这里同时证明 OPTIONAL 过滤不误伤：⑤整层无行、⑥ pending 被排除后退出码
    // 仍由 ④ 的 pending 定为 1
    expect(lesson.cmdDoctor(["--scene", LESSON_ID, "--lessons", join(d, "lessons"),
      "--strict"])).toBe(1)
  })

  it("--json 机读：键序 scene→failed→pending→checks，tier 序 ①…⑦", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    newLesson(ld)
    const lines = captureLog()
    expect(lesson.cmdDoctor(["--scene", "fruit", "--lessons", ld, "--json"])).toBe(0)
    const out = JSON.parse(lines.join("\n"))
    expect(out.length).toBe(1)
    expect(Object.keys(out[0])).toEqual(["scene", "failed", "pending", "checks"])
    expect(out[0]["scene"]).toBe("fruit")
    expect(out[0]["failed"]).toBe(0)
    const checkKeys = Object.keys(out[0]["checks"][0])
    expect(checkKeys).toEqual(["tier", "name", "state", "detail", "next"])
    const tiers = [...new Set(out[0]["checks"].map((c: any) => c["tier"]))]
    expect(tiers).toEqual(["①创意", "②剧本", "③数据", "④成片", "⑥发布", "⑦验收"])
  })

  it("--all：iterdir 全目录排序；多报告间空行分隔", () => {
    const d = tmp()
    const ld = join(d, "lessons")
    newLesson(ld)                       // fruit
    mkdirSync(join(ld, "aaa"), { recursive: true })   // 空目录也算一门（iterdir 口径）
    const lines = captureLog()
    expect(lesson.cmdDoctor(["--all", "--lessons", ld])).toBe(0)
    expect(lines.filter((l) => l === "课程体检：aaa").length).toBe(1)
    expect(lines.filter((l) => l === "课程体检：fruit").length).toBe(1)
    expect(lines.indexOf("课程体检：aaa")).toBeLessThan(lines.indexOf("课程体检：fruit"))
  })
})
