// parse_scene.test.ts — 解析器金样本 parity + 反向验证。
//
// **金样本判据（纪律 1）**：真实课件（guangchaoshi-逛超市/scene.md）经 TS 解析器
// 落盘，与 Python 引擎生成并入库的 scene.json **逐字节一致**（Python 侧已实测
// 重生成字节不变——入库文件就是有效金样本）。键序、JSON 转义、浮点口径
// （durationBudget 45.0/55.0）、token 标注、节拍归属，全在这一条里。
//
// 反向验证（纪律 2）：坏行/留白节拍/重叠节拍/缺表/坏格式，定向破坏各自命中。
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import { LESSONS_DIR, sceneDoc } from "../src/data.js"
import { FeuilleError } from "../src/errors.js"
import * as ps from "../src/parse_scene.js"

const LESSON_ID = "guangchaoshi-逛超市"
const LESSON_DIR = join(LESSONS_DIR, LESSON_ID)
// Python 引擎生成、已入库的 scene.json = 金样本（重生成字节不变已实测）
const GOLDEN = readFileSync(join(LESSON_DIR, "scene.json"), "utf8")

const tmps: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-parse-"))
  tmps.push(d)
  return d
}
afterEach(() => {
  for (const d of tmps.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe("金样本字节 parity（Python 落库口径）", () => {
  it("真实课件解析 → pyJsonDump 与入库 scene.json 逐字节一致", () => {
    const [doc] = ps.parseScene(LESSON_ID)
    expect(ps.pyJsonDump(doc)).toBe(GOLDEN)
  })

  it("mainParse 端到端：--lessons 临时目录落盘 → 退出码 0 + 字节一致", () => {
    const d = tmp()
    mkdirSync(join(d, LESSON_ID), { recursive: true })
    copyFileSync(join(LESSON_DIR, "scene.md"), join(d, LESSON_ID, "scene.md"))
    expect(ps.mainParse(["--scene", LESSON_ID, "--lessons", d])).toBe(0)
    expect(readFileSync(join(d, LESSON_ID, "scene.json"), "utf8")).toBe(GOLDEN)
  })
})

describe("路径约定与场景发现", () => {
  it("findSceneIds / scenePaths / analysisDir", () => {
    expect(ps.findSceneIds()).toEqual([LESSON_ID])
    expect(ps.findSceneIds("/nonexistent-lessons-dir")).toEqual([])   // 缺目录 → 空，不炸
    const [md, js] = ps.scenePaths("x", "/tmp/l")
    expect(md).toBe(join("/tmp/l", "x", "scene.md"))
    expect(js).toBe(join("/tmp/l", "x", "scene.json"))
    expect(ps.analysisDir("x", "/tmp/l")).toBe(join("/tmp/l", "x", "analysis"))
  })

  it("data.sceneDoc 接线：读回落盘 scene.json；缺文件 → FeuilleError", () => {
    const doc = sceneDoc(LESSON_ID)
    expect(doc["id"]).toBe(LESSON_ID)
    expect(doc["tokenOrder"]).toEqual(["where", "milk", "price", "cheaper", "card"])
    expect(doc["durationBudget"]).toEqual([45, 55])
    expect(() => sceneDoc("no-such-scene")).toThrow(FeuilleError)
  })

  it("剧本不存在 → FeuilleError（并列出已有场景）", () => {
    expect(() => ps.parseScene("no-such-scene")).toThrow(FeuilleError)
  })
})

describe("parse_line：台词行体例", () => {
  it("引号优先级 + 注音 + 对照只认首段 + 手势词/姿态码 + ⚑ 注记", () => {
    const ln = ps.parseLine(
      "- **A**（happy）：「どこ？」（*doko*）——在哪里｜「ここ」处 `point`｜⚑远距离指物用指示词")
    expect(ln).toMatchObject({
      speaker: "A", mood: "happy", text: "どこ？", romanization: "doko",
      gloss: "在哪里", note: "远距离指物用指示词", exits: false,
    })
    expect(ln!["gesture"]).toEqual({ word: "ここ", poses: ["point"] })
    expect(!("lang" in ln!)).toBe(true)   // lang 只在真写了语种时才落库
  })

  it("polyglot 语标段（· 分隔）；`·` 后面没有 = 不落 lang", () => {
    const ln = ps.parseLine('- **A · en-US**（happy）："hello"——你好')
    expect(ln!["lang"]).toBe("en-US")
    const ln2 = ps.parseLine("- **A ·**（happy）：「好」——好")
    expect(!("lang" in ln2!)).toBe(true)
  })

  it("法俄引号对（«»）与出画标记", () => {
    const ln = ps.parseLine("- **B**（puzzled）：«Привет»——你好｜出画")
    expect(ln!["text"]).toBe("Привет")
    expect(ln!["exits"]).toBe(true)
  })

  it("非台词行 → null；缺引号 → 报错", () => {
    expect(ps.parseLine("普通段落")).toBe(null)
    expect(() => ps.parseLine("- **A**（happy）：没有引号")).toThrow("引号解析失败")
  })
})

describe("apply_beats：骨架节拍", () => {
  const mkLn = (speaker: string) => ({ speaker } as Record<string, any>)

  it("完整覆盖 + even 问句按绝对行号归属", () => {
    const d = [mkLn("A"), mkLn("B"), mkLn("A")]
    ps.applyBeats(d, [{ beat: "r", from: "0", to: "n-1", ask: "even", askBy: "-" }], "zh-CN")
    expect(d.map((l) => [l["i"], l["role"], l["isQuestion"]]))
      .toEqual([[0, "r", true], [1, "r", false], [2, "r", true]])
  })

  it("n-K 记法 + askBy 说话人过滤", () => {
    const d = [mkLn("A"), mkLn("B"), mkLn("A"), mkLn("B")]
    ps.applyBeats(d, [
      { beat: "open", from: "0", to: "0", ask: "-" },
      { beat: "q", from: "1", to: "n-2", ask: "odd", askBy: "B" },
      { beat: "bye", from: "n-1", to: "n-1", ask: "-" },
    ], "x")
    expect(d.map((l) => l["role"])).toEqual(["open", "q", "q", "bye"])
    expect(d.map((l) => l["isQuestion"])).toEqual([false, true, false, false])
  })

  it("留白 → 完整性报错", () => {
    const d = [mkLn("A"), mkLn("B")]
    expect(() => ps.applyBeats(d, [{ beat: "r", from: "0", to: "0", ask: "-" }], "x"))
      .toThrow("未被任何节拍覆盖")
  })

  it("重叠 → 报错；区间反了 → 报错", () => {
    const d = [mkLn("A"), mkLn("B")]
    const beats = [{ beat: "a", from: "0", to: "1", ask: "-" }, { beat: "b", from: "1", to: "1", ask: "-" }]
    expect(() => ps.applyBeats([...d], beats, "x")).toThrow("被两个节拍覆盖")
    expect(() => ps.applyBeats([...d], [{ beat: "a", from: "2", to: "0", ask: "-" }], "x"))
      .toThrow("区间反了")
  })

  it("声明了问句却一条没产生 → 报错（even/odd 写反的真实事故口径）", () => {
    const d = [mkLn("A")]
    expect(() => ps.applyBeats(d, [{ beat: "r", from: "0", to: "n-1", ask: "odd", askBy: "-" }], "x"))
      .toThrow("没有一行被判为问句")
  })
})

describe("_match_token：最长命中", () => {
  it("互为子串的词取最长（ouest ⊃ est——按序命中会点亮「东」的真实事故）", () => {
    const words = [
      { key: "east", word: "est", forms: ["est"], romanization: "" },
      { key: "west", word: "ouest", forms: ["ouest"], romanization: "" },
    ]
    expect(ps.matchToken(words, "le vent vient de l'ouest")!["key"]).toBe("west")
    expect(ps.matchToken(words, "il est là")!["key"]).toBe("east")
    expect(ps.matchToken(words, "rien du tout")).toBe(null)
  })

  it("大小写不敏感 + 词干子串命中变格形（красн → красного）", () => {
    const words = [{ key: "red", word: "красный", forms: ["красн"], romanization: "" }]
    expect(ps.matchToken(words, "красного хлеба")!["key"]).toBe("red")
    expect(ps.matchToken(words, "КРАСНАЯ")!["key"]).toBe("red")
  })
})

describe("parse_spec：§0 机读规格", () => {
  const TINY = [
    "## 0. 规格",
    "sceneId: tiny",
    "title: 微",
    "rtlLocales:",
    "",
    "### 0.1 token",
    "| key | chip |",
    "| --- | --- |",
    "| a | #111111 |",
    "",
    "### 0.5 节拍",
    "| beat | from | to | ask | askBy |",
    "| --- | --- | --- | --- | --- |",
    "| r | 0 | n | - | - |",
    "",
  ].join("\n")

  it("meta_val 的 [^\\S\\n] 坑：留空 rtlLocales 不把下一行吞成值", () => {
    const spec = ps.parseSpec(TINY)
    expect(spec.meta["rtlLocales"]).toEqual([])
    expect(spec.meta["sceneId"]).toBe("tiny")
    expect(spec.meta["form"]).toBe("dialogue")
    expect(spec.tokenOrder).toEqual(["a"])
    expect(spec.beats).toEqual([{ beat: "r", from: "0", to: "n", ask: "-", askBy: "-" }])
  })

  it("durationBudget：40-55 → [40.0, 55.0]（Python float 落库口径）", () => {
    const spec = ps.parseSpec(TINY.replace("rtlLocales:", "durationBudget: 40-55"))
    expect(ps.pyJsonDump(spec.meta["durationBudget"])).toBe("[\n 40.0,\n 55.0\n]")
    expect(() => ps.parseSpec(TINY.replace("rtlLocales:", "durationBudget: 四十")))
      .toThrow("§0 durationBudget 格式应为")
  })

  it("缺 §0 / 缺 token 表 / token 重复 / 缺节拍表", () => {
    expect(() => ps.parseSpec("## 2. 台词\n")).toThrow("缺 §0 场景规格节")
    expect(() => ps.parseSpec(TINY.replace("| a | #111111 |", ""))).toThrow("缺教学 token 表")
    expect(() => ps.parseSpec(TINY.replace(
      "| a | #111111 |", "| a | #111111 |\n| a | #222222 |"))).toThrow("§0 token 重复：a")
    expect(() => ps.parseSpec(TINY.replace("| r | 0 | n | - | - |", ""))).toThrow("缺骨架节拍表")
  })
})

describe("parse 自检（不产出半成品 scene.json）", () => {
  it("缺 locales（无 §2 剧本）→ 前置校验就地失败", () => {
    const d = tmp()
    mkdirSync(join(d, "t"), { recursive: true })
    writeFileSync(join(d, "t", "scene.md"), "## 0. 规格\nsceneId: t\ntitle: 微\n"
      + "### 0.1 token\n| key | chip |\n| --- | --- |\n| a | #111111 |\n"
      + "### 0.5 节拍\n| beat | from | to | ask | askBy |\n| --- | --- | --- | --- | --- |\n| r | 0 | n | - | - |\n", "utf8")
    expect(() => ps.parseScene("t", d)).toThrow("场景数据不合规")
  })
})
