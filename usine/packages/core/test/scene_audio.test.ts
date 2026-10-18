// scene_audio.test.ts — 场景课 TTS 叶子的反向验证（verify_scene_audio.py 的
// vitest 对应移植）+ 离线端到端。
//
// 第 0 条好数据放行（纪律 1）：真实班底的选角映射（ru-RU A=lively→misha、
// B=steady→anya）、情绪增量缺省、口径常量，必须全对。其余各防一种真实退化：
//
// - 选角映射：§0.4 roles 声明驱动（role → energy → 班底唯一人）；A 声明 steady
//   就配沉稳声线（不认硬编码 A=活泼）；班底配对破坏时**显式报错**不静默回落
// - 情绪增量：moodVoices 没声明的 mood = ±0（不发明默认值）；声明了就生效
// - 台账：extra=(sid, sha, gap) 自描述——statusOf 漏传 extra 时按条目里那份
//   复算，不会永久误红；scene.md 变 → 指纹变（sha 进 extra）
// - 裁尾哨兵：空 words/伪词行的 probe 必须是**实测**时长，不是 1e9 哨兵
// - 离线端到端：预置内容寻址缓存（真 mp3 + 词表）→ runScene 全程零网络，
//   落盘 snake_case 键序 timeline.json + line-XX.mp3 + 台账 + 二跑 [SKIP]
//
// 真实网络合成不在这里跑（verify_tts / tts-live 已覆盖 synthCached 的网络
// 路径）；本套件全部断言离线可跑。
import { execFileSync } from "node:child_process"
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ffmpeg } from "../src/platform.js"
import { LESSONS_DIR, personas } from "../src/data.js"
import { FeuilleError } from "../src/errors.js"
import * as ledger from "../src/ledger.js"
import * as sa from "../src/scene_audio.js"
import { contentHash, voiceParams } from "../src/tts/index.js"

const SID = "guangchaoshi-逛超市"
const FFMPEG = ffmpeg()
const SRC_DIR = fileURLToPath(new URL("../src", import.meta.url))

const tmps: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-sa-"))
  tmps.push(d)
  return d
}
afterEach(() => {
  vi.restoreAllMocks()
  for (const d of tmps.splice(0)) rmSync(d, { recursive: true, force: true })
})

function ruPeople(): any[] {
  return Object.values(personas()).filter((p) => p["locale"] === "ru-RU")
}

describe("第 0 条：好数据放行（纯函数，离线）", () => {
  it("ru 选角：roles A=lively→misha、B=steady→anya", () => {
    const by = sa.pickCast(ruPeople(), { A: "lively", B: "steady" }, "ru-RU")
    expect(by["A"]["id"]).toBe("misha")
    expect(by["B"]["id"]).toBe("anya")
  })

  it("roles 声明驱动：A 声明 steady → A 配沉稳声线（不认硬编码 A=活泼）", () => {
    const by = sa.pickCast(ruPeople(), { A: "steady", B: "lively" }, "ru-RU")
    expect(by["A"]["id"]).toBe("anya")
    expect(by["B"]["id"]).toBe("misha")
  })

  it("班底配对破坏 → FeuilleError 显式报错（不静默回落）", () => {
    const people = ruPeople()
    const bad = [{ ...people[0]! }, { ...people[0]! }]
    expect(() => sa.pickCast(bad, { A: "lively", B: "steady" }, "test")).toThrow(FeuilleError)
  })

  it("LINE_GAP=0.35（与 verify_timeline 同口径）", () => {
    expect(sa.LINE_GAP).toBe(0.35)
  })
})

describe("情绪增量（moodVoices）", () => {
  it("无该 mood → ±0（不猜）；声明的增量生效", () => {
    expect(sa.moodOffset("happy", {})).toEqual([0, 0])
    expect(sa.moodOffset("happy", { happy: { rate: 4, pitch: 2 } })).toEqual([4, 2])
  })
})

describe("裁尾哨兵：空 words 行的 dur 回落实测时长", () => {
  it("空 words 行：effectiveDurOf = 实测时长（≈3s），不是 1e9 哨兵", () => {
    const d = tmp()
    const mp3 = join(d, "fake.mp3")
    execFileSync(FFMPEG!, ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", mp3])
    const got = sa.effectiveDurOf([], "Пойдём!", mp3)
    expect(Math.abs(got - 3.0)).toBeLessThan(0.1)
    expect(got).toBeLessThan(1e8)
  })
})

describe("台账：extra 自描述 + scene.md sha 进指纹", () => {
  // tempdir 必须模拟真实 root 布局：root/lessons/<id>/scene.md（@glob 的数据）
  // ——glob 相对 root 解析，空 tempdir 里 glob 不中 = 保守判过期（账本的正确
  // 行为，不是缺陷；真实布局下 lessons/ 与 build/ 同根）。
  it("产物缺失判过期；记账后漏传 extra 按条目里那份复算；sha 变则指纹变", () => {
    const root = tmp()
    const lessonsDir = join(root, "lessons")
    mkdirSync(join(lessonsDir, SID), { recursive: true })
    copyFileSync(join(LESSONS_DIR, SID, "scene.md"), join(lessonsDir, SID, "scene.md"))
    mkdirSync(join(root, "personas"))
    copyFileSync(join(LESSONS_DIR, "..", "personas", "personas.json"), join(root, "personas", "personas.json"))
    sa.registerSceneAudioLine()
    const sha = sa.sceneMdSha16(lessonsDir, SID)
    const extra = [SID, sha, "0.35"]

    // 产物不存在 → 过期（Python verify 同款：只断言判过期，不钉 why 的措辞——
    // 账本里没有这条时先命中「首建」判据）
    const [ok0] = ledger.statusOf(root, sa.REGISTER_KIND, `${SID}/ru-RU`, ["build/scene/audio/x.json"])
    expect(ok0).toBe(false)

    // 记账后（带 extra）：产物仍缺失 → 仍过期；补上产物 → fresh
    const art = "build/scene/audio/fake.json"
    ledger.record(root, sa.REGISTER_KIND, `${SID}/ru-RU`, [art], extra)
    const [ok1] = ledger.statusOf(root, sa.REGISTER_KIND, `${SID}/ru-RU`, [art])   // 漏传 extra
    expect(ok1).toBe(false)
    mkdirSync(join(root, "build", "scene", "audio"), { recursive: true })
    writeFileSync(join(root, art), "{}", "utf8")
    const [ok2] = ledger.statusOf(root, sa.REGISTER_KIND, `${SID}/ru-RU`, [art])   // 漏传 extra
    expect(ok2).toBe(true)

    // scene.md 变 → sha 变 → extra 变 → 指纹变（statusOf 用条目里的旧 sha）
    const fpOld = ledger.fingerprint(root, sa.REGISTER_KIND, "u", extra)
    const fpNew = ledger.fingerprint(root, sa.REGISTER_KIND, "u", [SID, "0".repeat(16), "0.35"])
    expect(fpOld).not.toBe(fpNew)
  })
})

describe("叶子可达 + 产物命名（doctor ④ 探针同源）", () => {
  it("路由表登记 scene/tts（可达性由 cli 路由反向验证全量机检）", async () => {
    const leaf = (await import("../../cli/src/commands.js")).COMMANDS["scene/tts"]
    expect(leaf).toBeTruthy()
    const mod = await leaf!.load()
    expect(typeof mod.main).toBe("function")
  })

  it("说话人不在 roles 里 → FeuilleError（名单按 Python sorted-list 口径印）", async () => {
    const doc = {
      sceneId: "mini",
      locales: { "ru-RU": { dialogue: [{ i: 0, speaker: "C", mood: "happy", text: "Привет!" }] } },
      roles: { A: "lively", B: "steady" },
    }
    await expect(sa.buildLocaleTimeline(doc, "ru-RU", tmp()))
      .rejects.toThrow(/说话人 'C' 不在 §0.4 roles \['A', 'B'\] 里/)
  })

  it("timeline 文件名格式串在 scene_audio 源码里（doctor ④ 探针 ↔ 落盘同格式串）", () => {
    const src = readFileSync(join(SRC_DIR, "scene_audio.ts"), "utf8")
    expect(src).toContain("scene-${sid}_${lc}.timeline.json")
    expect(src).toContain('"build", "scene", "audio"')
    expect(sa.timelineName(SID, "ru-RU")).toBe(`scene-${SID}_ru-RU.timeline.json`)
  })
})

describe("离线端到端：预置缓存 → runScene 全程零网络", () => {
  it("runScene 落盘 snake_case timeline.json + line-XX.mp3 + 台账；二跑 [SKIP]", async () => {
    const root = tmp()
    const sid = "mini"
    const lessonsDir = join(root, "lessons")
    mkdirSync(join(lessonsDir, sid), { recursive: true })
    writeFileSync(join(lessonsDir, sid, "scene.md"), "# mini\n", "utf8")
    mkdirSync(join(root, "personas"))
    copyFileSync(join(LESSONS_DIR, "..", "personas", "personas.json"), join(root, "personas", "personas.json"))

    const doc = {
      sceneId: sid,
      locales: {
        "ru-RU": {
          dialogue: [
            { i: 0, speaker: "A", mood: "happy", text: "Привет, как дела?" },
            { i: 1, speaker: "B", mood: "neutral", text: "Отлично!" },
          ],
        },
      },
      roles: { A: "lively", B: "steady" },
      moodVoices: { happy: { rate: 4, pitch: 2 } },
    }
    writeFileSync(join(lessonsDir, sid, "scene.json"), JSON.stringify(doc), "utf8")

    // 预置内容寻址缓存：键 = contentHash(voiceId, rate, pitch, text)——
    // 声线与增量的取值链和产线同一套（pickCast → moodOffset → voiceParams）
    const by = sa.pickCast(ruPeople(), doc.roles, "ru-RU")
    const outDir = join(root, "build", "scene", "audio")
    mkdirSync(outDir, { recursive: true })
    const durs = [1, 2]   // 行 0：1s（真词表裁尾）；行 1：2s（空词表走实测）
    doc.locales["ru-RU"].dialogue.forEach((ln, idx) => {
      const v = by[ln.speaker]["voice"]
      const [rOff, pOff] = sa.moodOffset(ln.mood, doc.moodVoices)
      const [rate, pitch] = voiceParams(v["rate"], v["pitch"], rOff, pOff)
      const key = contentHash(v["voiceId"], rate, pitch, ln.text)
      const mp3 = join(outDir, `${key}.mp3`)
      execFileSync(FFMPEG!, ["-y", "-f", "lavfi", "-i", `sine=frequency=440:duration=${durs[idx]}`, mp3])
      const words = idx === 0 ? [{ t: 0.1, d: 0.5, w: "Привет" }] : []
      writeFileSync(join(outDir, `${key}.json`), JSON.stringify(words), "utf8")
    })

    const logs: string[] = []
    vi.spyOn(console, "log").mockImplementation((...a) => logs.push(a.join(" ")))
    expect(await sa.runScene(lessonsDir, sid)).toBe(0)

    const tlPath = join(outDir, sa.timelineName(sid, "ru-RU"))
    // 落盘键序与缩进 = Python json.dumps(ensure_ascii=False, indent=1) 口径
    expect(readFileSync(tlPath, "utf8").startsWith(
      '{\n "locale": "ru-RU",\n "lines": [\n  {\n   "i": 0,\n   "speaker": "A",')).toBe(true)
    const tl = JSON.parse(readFileSync(tlPath, "utf8"))
    expect(Object.keys(tl)).toEqual(["locale", "lines", "gap", "totalDur", "spanDur"])
    expect(Object.keys(tl.lines[0])).toEqual(
      ["i", "speaker", "mood", "text", "key", "words", "dur", "speech_dur", "file_dur", "tail_silence", "start"])
    // 行 0：真词表裁尾 min(实测≈1s, 末词 end 0.6 + 0.2) ≈ 0.8；行 1：空词表 = 实测 ≈ 2s
    expect(tl.lines[0].dur).toBeGreaterThan(0.7)
    expect(tl.lines[0].dur).toBeLessThan(0.85)
    expect(tl.lines[1].dur).toBeGreaterThan(1.9)
    // start 累进：start[1] = dur[0] + gap
    expect(tl.lines[1].start).toBe(tl.lines[0].dur + 0.35)
    expect(tl.totalDur).toBeCloseTo(tl.lines[0].dur + tl.lines[1].dur, 5)
    expect(tl.spanDur).toBeCloseTo(tl.totalDur + 0.35, 5)
    // 产物位逐行 mp3
    expect(readFileSync(join(outDir, "line-00.mp3")).length).toBeGreaterThan(0)
    expect(readFileSync(join(outDir, "line-01.mp3")).length).toBeGreaterThan(0)
    // 台账：extra=(sid, sha, "0.35")
    const e = ledger.load(root).entries[`scene-audio:${sid}/ru-RU`]
    expect(e?.extra).toEqual([sid, sa.sceneMdSha16(lessonsDir, sid), "0.35"])
    expect(logs.join("\n")).toContain(`[OK] ru-RU: 2 行`)

    // 二跑不 --force：台账 fresh → [SKIP]，退出码仍 0
    expect(await sa.runScene(lessonsDir, sid)).toBe(0)
    expect(logs.filter((l) => l.includes("[SKIP] ru-RU")).length).toBe(1)
  })

  it("mainTts：缺 --scene → 2；FeuilleError（缺 roles 声明）→ stderr + 1", async () => {
    const root = tmp()
    const sid = "mini"
    const lessonsDir = join(root, "lessons")
    mkdirSync(join(lessonsDir, sid), { recursive: true })
    writeFileSync(join(lessonsDir, sid, "scene.md"), "# mini\n", "utf8")
    writeFileSync(join(lessonsDir, sid, "scene.json"), JSON.stringify({
      sceneId: sid,
      locales: { "ru-RU": { dialogue: [{ i: 0, speaker: "A", mood: "happy", text: "Привет!" }] } },
    }), "utf8")
    const errs: string[] = []
    vi.spyOn(console, "error").mockImplementation((...a) => errs.push(a.join(" ")))
    expect(await sa.mainTts([])).toBe(2)
    expect(errs[0]).toContain("usage:")
    expect(await sa.mainTts(["--scene", sid, "--lessons", lessonsDir])).toBe(1)
    expect(errs[1]).toContain("缺 §0.4 roles 声明")
  })
})
