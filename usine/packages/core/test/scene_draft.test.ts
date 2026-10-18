// scene_draft.test.ts — 草稿生成器金样本 parity + 反向验证。
//
// **金样本判据（纪律 1）**：真实 brief（guangchaoshi-逛超市/brief.json）经 TS
// render 生成的全文，与 Python `feuille scene draft --brief ...` **落盘**入库的
// migration/golden/scene_draft.md **逐字节一致**——frontmatter、§0 全部机读字段、
// §2 每语种台词槽（引号对来自 manifest）、§5 词表格子、节拍表 n-K 记法，
// 全在这一条里。（不取 --print-plan 口径：print 会多补一个换行，落盘字节才是
// render 的真身。）
//
// 反向验证（纪律 2）：坏骨架（双 rest / 缺 n / rest 超载 / n 不一致）、坏取值
// （姿态/情绪/装置样式不在注册表）、坏选角、拒绝覆盖已定稿，定向破坏各自命中。
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LESSONS_DIR, cardsDoc, personas } from "../src/data.js"
import { FeuilleError } from "../src/errors.js"
import * as sd from "../src/scene_draft.js"

const LESSON_ID = "guangchaoshi-逛超市"
const BRIEF = JSON.parse(readFileSync(join(LESSONS_DIR, LESSON_ID, "brief.json"), "utf8"))
// Python `feuille scene draft` 落盘入库的金样本（确定性纯函数，逐字节可比）
const GOLDEN_PATH = fileURLToPath(new URL("../../../migration/golden/scene_draft.md", import.meta.url))
const GOLDEN = readFileSync(GOLDEN_PATH, "utf8")

const tmps: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-draft-"))
  tmps.push(d)
  return d
}
afterEach(() => {
  vi.restoreAllMocks()
  for (const d of tmps.splice(0)) rmSync(d, { recursive: true, force: true })
})

/** 渲染一口价：真实班底 + 真实语种注册表 + 渲染线注册表。 */
function renderBrief(brief: any = BRIEF): string {
  return sd.render(brief, personas(), cardsDoc(), sd.langs(), sd.registries())
}

describe("金样本字节 parity（Python 落盘口径）", () => {
  it("真实 brief → render 全文与入库金样本逐字节一致", () => {
    expect(renderBrief()).toBe(GOLDEN)
  })

  it("mainDraft 端到端：--brief 临时目录落盘 → 退出码 0 + 字节一致 + 欠账清单", () => {
    const d = tmp()
    copyFileSync(join(LESSONS_DIR, LESSON_ID, "brief.json"), join(d, "brief.json"))
    const logs: string[] = []
    vi.spyOn(console, "log").mockImplementation((...a) => logs.push(a.join(" ")))
    expect(sd.mainDraft(["--brief", join(d, "brief.json")])).toBe(0)
    expect(readFileSync(join(d, "scene.md"), "utf8")).toBe(GOLDEN)
    expect(logs[0]).toContain(`已生成草稿 → ${join(d, "scene.md")}`)
    // 3 语种 × 17 行 = 51 条台词槽；舞台三语种 brief 都给了 → 0
    expect(logs[1]).toContain("欠账清单：台词行=51")
    expect(logs[1]).toContain("待写舞台的语种=0")
  })

  it("mainDraft --print-plan：只打印不落盘 → 退出码 0", () => {
    const d = tmp()
    copyFileSync(join(LESSONS_DIR, LESSON_ID, "brief.json"), join(d, "brief.json"))
    const logs: string[] = []
    vi.spyOn(console, "log").mockImplementation((...a) => logs.push(a.join(" ")))
    expect(sd.mainDraft(["--brief", join(d, "brief.json"), "--print-plan"])).toBe(0)
    expect(logs.join("\n")).toBe(GOLDEN)
    // 只打印：scene.md 没有落盘
    expect(() => readFileSync(join(d, "scene.md"), "utf8")).toThrow()
  })

  it("缺 --brief → 退出码 2（argparse 同款口径）", () => {
    const errs: string[] = []
    vi.spyOn(console, "error").mockImplementation((...a) => errs.push(a.join(" ")))
    expect(sd.mainDraft([])).toBe(2)
    expect(errs[0]).toContain("usage:")
  })
})

describe("落盘纪律（拒覆盖已定稿）", () => {
  it("目标存在且无草稿标记 → FeuilleError 拒绝覆盖；--force 才放行", () => {
    const d = tmp()
    copyFileSync(join(LESSONS_DIR, LESSON_ID, "brief.json"), join(d, "brief.json"))
    writeFileSync(join(d, "scene.md"), "# 已定稿，没有 draft 标记", "utf8")
    expect(() => sd.mainDraft(["--brief", join(d, "brief.json")])).toThrow(FeuilleError)
    expect(readFileSync(join(d, "scene.md"), "utf8")).toBe("# 已定稿，没有 draft 标记")
    vi.spyOn(console, "log").mockImplementation(() => {})
    expect(sd.mainDraft(["--brief", join(d, "brief.json"), "--force"])).toBe(0)
    expect(readFileSync(join(d, "scene.md"), "utf8")).toBe(GOLDEN)
  })

  it("目标存在但带草稿标记 → 免 --force 直接重写", () => {
    const d = tmp()
    copyFileSync(join(LESSONS_DIR, LESSON_ID, "brief.json"), join(d, "brief.json"))
    writeFileSync(join(d, "scene.md"), "---\ngenerated: { by: scene_draft, draft: true }\n---", "utf8")
    vi.spyOn(console, "log").mockImplementation(() => {})
    expect(sd.mainDraft(["--brief", join(d, "brief.json")])).toBe(0)
    expect(readFileSync(join(d, "scene.md"), "utf8")).toBe(GOLDEN)
  })

  it("--gaps：只数欠账不生成；目标不存在 → FeuilleError", () => {
    const d = tmp()
    copyFileSync(join(LESSONS_DIR, LESSON_ID, "brief.json"), join(d, "brief.json"))
    expect(() => sd.mainDraft(["--brief", join(d, "brief.json"), "--gaps"]))
      .toThrow(/没有 .*scene\.md/)
    const logs: string[] = []
    vi.spyOn(console, "log").mockImplementation((...a) => logs.push(a.join(" ")))
    expect(sd.mainDraft(["--brief", join(d, "brief.json"), "--gaps", "--out", GOLDEN_PATH])).toBe(0)
    expect(logs[0]).toContain("欠账清单：台词行=51")
  })
})

describe("骨架展开（expand_skeleton / beat_table_md）", () => {
  it("rest 之前的节起止写死、rest 起点写死终点 n-K、rest 之后起止都 n-K", () => {
    const beats = sd.expandSkeleton(BRIEF["skeleton"], 17)
    expect(beats.map((b) => [b.beat, b.from, b.to, b.count, b.relFrom, b.relTo])).toEqual([
      ["open", 0, 0, 1, false, false],
      ["reply", 1, 1, 1, false, false],
      ["round", 2, 13, 12, false, true],
      ["summary", 14, 14, 1, true, true],
      ["bye", 15, 16, 2, true, true],
    ])
    const table = sd.beatTableMd(beats, 17)
    expect(table).toContain("| round | 2 | n-4 | even | A |")
    expect(table).toContain("| summary | n-3 | n-3 | - | - |")
    expect(table).toContain("| bye | n-2 | n-1 | - | - |")
  })

  it("没有 rest 的骨架：n 与各节之和必须一致；不给 n 就报错", () => {
    const sk = [{ beat: "a", lines: 2 }, { beat: "b", lines: 3 }]
    expect(sd.expandSkeleton(sk, 5).map((b) => [b.from, b.to])).toEqual([[0, 1], [2, 4]])
    expect(() => sd.expandSkeleton(sk, 6)).toThrow(/n=6 与骨架各节之和 5 不一致/)
    expect(() => sd.expandSkeleton(sk, null)).toThrow(/必须给出总行数 n/)
    expect(() => sd.expandSkeleton(sk)).toThrow(/必须给出总行数 n/)
  })

  it("两个 rest → FeuilleError；rest 行数超载 → FeuilleError", () => {
    const two = [{ beat: "a", lines: "rest" }, { beat: "b", lines: "rest" }]
    expect(() => sd.expandSkeleton(two, 5)).toThrow(/只能有一个 rest，实得 \['a', 'b'\]/)
    expect(() => sd.expandSkeleton(
      [{ beat: "a", lines: 5 }, { beat: "b", lines: "rest" }], 4))
      .toThrow(/rest 只剩 -1 行（总 4 - 固定 5）/)
    // rest 在场且未给 n：条件与文案按 Python 原样（文案说「不需要再给」，实际必须给）
    expect(() => sd.expandSkeleton([{ beat: "a", lines: "rest" }]))
      .toThrow(/骨架含 rest 项时不需要再给 n/)
  })

  it("骨架缺 lines 键 → 裸错崩溃（Python KeyError 同款通道，不是 FeuilleError）", () => {
    expect(() => sd.expandSkeleton([{ beat: "a" }], 3)).toThrow(/KeyError: 'lines'/)
  })
})

describe("行归属（assign_lines）", () => {
  it("问句节按 ask 奇偶发问、Ask/Reply 变体各取各的；非问句节整节同一人", () => {
    const beats = sd.expandSkeleton(BRIEF["skeleton"], 17)
    const plan = sd.assignLines(beats, BRIEF["spec"])
    expect(plan.length).toBe(17)   // 一份骨架 17 行；render 再按 3 语种各铺一份
    // open：A happy bounce_in（姿态串按空格拆，渲染时逐个反引号化）
    expect(plan[0]).toMatchObject({ i: 0, speaker: "A", mood: "happy", pose: "bounce-in both-hands", isQuestion: false })
    // reply 节：B neutral nod
    expect(plan[1]).toMatchObject({ i: 1, speaker: "B", mood: "neutral", pose: "nod" })
    // round 节 ask=even askBy=A：偶数行 A happy point（问）、奇数行 B neutral palm-open（答）
    expect(plan[2]).toMatchObject({ speaker: "A", mood: "happy", pose: "point", isQuestion: true })
    expect(plan[3]).toMatchObject({ speaker: "B", mood: "neutral", pose: "palm-open", isQuestion: false })
    expect(plan[13]).toMatchObject({ speaker: "B", mood: "neutral", pose: "palm-open", isQuestion: false })
    // summary：A happy jump-celebrate
    expect(plan[14]).toMatchObject({ i: 14, speaker: "A", mood: "happy", pose: "jump-celebrate" })
    // bye 节：列表按行偏移逐行给（B encouraging wave → A happy wave）
    expect(plan[15]).toMatchObject({ i: 15, speaker: "B", mood: "encouraging", pose: "wave" })
    expect(plan[16]).toMatchObject({ i: 16, speaker: "A", mood: "happy", pose: "wave" })
  })

  it("列表短于节长 → 越界行退回缺省（A / neutral / 空）", () => {
    const plan = sd.assignLines(
      [{ beat: "b", from: 0, to: 2, count: 3, ask: "-", askBy: "-", relFrom: false, relTo: false }],
      { "b.speakers": ["B"], "b.mood": ["happy"], "b.pose": ["wave"] })
    expect(plan[1]).toMatchObject({ speaker: "A", mood: "neutral", pose: "" })
  })
})

describe("选角（cast_for）", () => {
  it("真实班底：ru-RU 的 A/B 各一人、名字取 native", () => {
    const cast = sd.castFor("ru-RU", personas(), cardsDoc())
    expect(cast).toEqual({ A: "Миша", B: "Аня" })
  })

  it("该语种班底没人 → FeuilleError（名单空时给人话提示）", () => {
    expect(() => sd.castFor("xx-XX", personas(), cardsDoc()))
      .toThrow(/xx-XX A 角选派异常：班底里没有该 locale 的人——先补/)
  })
})

describe("render 反向验证：坏输入定向命中", () => {
  const hit = (mutate: (b: any) => void, re: RegExp) => {
    const b = structuredClone(BRIEF)
    mutate(b)
    expect(() => renderBrief(b), re.source).toThrow(re)
  }

  it("语种目录缺失 / 骨架两行不足 / 坏姿态 / 坏情绪 / 坏装置样式", () => {
    hit((b) => b["locales"].push("xx-XX"), /没有语种目录：\['xx-XX'\]/)
    hit((b) => { b["skeleton"] = [{ beat: "a", lines: 1 }]; b["lines"] = 1 }, /骨架只展开出 1 行台词/)
    hit((b) => b["spec"]["open.pose"] = "no-such-pose", /姿态 \['no_such_pose'\] 不在 POSE_CODES/)
    hit((b) => b["spec"]["open.mood"] = "no-such-mood", /情绪 \['no-such-mood'\] 不在 MOOD_FACE/)
    hit((b) => b["devices"]["ru-RU"]["style"] = "no-such-style", /style \['no-such-style'\] 不在 DEVICE_STYLES/)
    // 装置表 style 缺失：Python 集合里进了 None → 报错名单印 None（原样镜像）
    hit((b) => delete b["devices"]["ru-RU"]["style"], /style \[None\] 不在 DEVICE_STYLES/)
  })

  it("levels 可选节：给了就渲染 §0.3，没给整节缺席（金样本无此节）", () => {
    const b = structuredClone(BRIEF)
    b["levels"] = { "ru-RU": { a: "正式", b: "口语", marker: "您", note: "敬语对照" } }
    const md = renderBrief(b)
    expect(md).toContain("### 0.3 语种文本规范")
    expect(md).toContain("| ru-RU | 正式 | 口语 | 您 | 敬语对照 |")
    expect(GOLDEN).not.toContain("### 0.3")
  })

  it("rtlLocales 可选行按需出现（金样本无此行）", () => {
    const b = structuredClone(BRIEF)
    b["rtlLocales"] = ["he-IL"]
    expect(renderBrief(b)).toContain("rtlLocales: he-IL")
    expect(GOLDEN).not.toContain("rtlLocales:")
  })

  it("noteOn：⚑TODO 与 ＋蹦跳出画 按节内偏移点亮（bye 只有末行 exit）", () => {
    const lines = GOLDEN.split("\n")
    const byeFirst = lines.find((l) => l.startsWith("- **B**（encouraging）"))
    const byeLast = lines.find((l) => l.includes("＋蹦跳出画"))
    expect(byeFirst).toBeTruthy()
    expect(byeLast).toBeTruthy()
    expect(byeFirst).not.toContain("出画")
    expect(byeLast).toMatch(/- \*\*A\*\*（happy）：«TODO»｜«TODO» 处 `wave`＋蹦跳出画/)
  })
})

describe("欠账清单（gaps）", () => {
  it("逐类计数（Python 实测口径）：51 台词槽全带 TODO、§5 表 3 行、舞台 0", () => {
    expect(sd.gaps(GOLDEN)).toEqual({
      "台词行": 51,
      "仍带 TODO 的台词行": 51,
      "词表/表格里的 TODO 格": 3,
      "待写舞台的语种": 0,
    })
  })
})
