// scene_schema.test.ts — 课件线校验层的反向验证（verify_lesson.py §1–§2 的 vitest 移植；
// §3 doctor 班底体检接线随 lesson.ts（P5-5）补）。
//
// 门禁自己没人验的反向验证套件，证两件事：
// 1. **好数据放行是第一条断言**（纪律 1）：一份**用遍全部注册值**的演习场景
//    （每个 mood / 每个 pose / 每个 device_style 至少出现一次）零问题通过。
//    这同时是注册表↔校验层的契约测试：rig / devices 改注册表，本套就炸，
//    不用等下一门课渲染到一半。
// 2. **凿洞必被抓**（纪律 2）：坏 mood / 坏 pose / 坏装置样式 / 幽灵说话人 /
//    token 表错位 / 空角色表 / 缺节拍表 / 行号重复 / 形态-同台表错配，
//    定向破坏必须各自命中对应报错。
// 另加一条实弹：仓库里真实课件（guangchaoshi-逛超市/scene.json）× 真实班底
// × 亮相卡 cast 表零问题——选角/班底检查（§8）走全量数据。
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { MOOD_FACE, POSE_CODES } from "../src/rig.js"
import { DEVICE_STYLES } from "../src/devices.js"
import { cardsDoc, LESSONS_DIR, personas } from "../src/data.js"
import { ENTRY_POSE, validateScene } from "../src/scene_schema.js"

type Scene = Record<string, any>

/** 用遍全部注册值的演习场景（合成数据，不落盘，personas 不给 = 跳过选角检查）。
 * locales 一台装置一岛（16 个 device_style 全用遍）；台词行轮转铺满
 * 6 个 mood 与 38 个姿态码（37 POSE_CODES + bounce_in）。 */
function drillScene(): Scene {
  const moods = Object.keys(MOOD_FACE).sort()
  const poses = [...POSE_CODES, ENTRY_POSE].sort()
  const styles = Object.keys(DEVICE_STYLES).sort()
  const n = Math.max(moods.length, poses.length, styles.length)
  const scene: Scene = {
    id: "registry-drill", sceneId: "registry-drill",
    title: "全注册表演习（合成，不落盘）",
    tokenOrder: ["t0"], tokens: { t0: "#35486E" },
    tokenWords: {},
    roles: { A: "lively", B: "steady" },
    beats: [{ beat: "b1", ask: "-" }],
    locales: {},
  }
  styles.forEach((st, li) => {
    const lc = `L${li}`
    scene["locales"][lc] = {
      langLabel: `语种${li}`, aName: `甲${li}`, bName: `乙${li}`,
      prop: { device: { style: st } },
      dialogue: [],
    }
    scene["tokenWords"][lc] = [{ key: "t0" }]
  })
  for (let i = 0; i < n; i++) {
    const lc = `L${i % styles.length}`
    scene["locales"][lc]["dialogue"].push({
      i: i + 1,
      speaker: i % 2 === 0 ? "A" : "B",
      mood: moods[i % moods.length],
      gesture: { poses: [poses[i % poses.length]] },
      tokenKey: "t0",
      text: `演习行 ${i + 1}`,
    })
  }
  return scene
}

describe("课件校验层：全注册表演习 + 定向凿洞", () => {
  it("好数据放行：全注册表演习零问题（mood × pose × device_style 全用遍）", () => {
    const errs = validateScene(drillScene())
    expect(errs).toEqual([])
  })

  it("凿洞必被抓：十种定向破坏各自命中对应报错", () => {
    const base = drillScene()
    const hit = (mutate: (s: Scene) => void, expectSub: string, what: string) => {
      const s = structuredClone(base)
      mutate(s)
      const errs = validateScene(s)
      const caught = errs.some((e) => e.includes(expectSub))
      expect(caught, `${what} → 应报「${expectSub}」（实得 ${JSON.stringify(errs.slice(0, 2))}）`).toBe(true)
    }

    hit((s) => { s["locales"]["L0"]["dialogue"][0]["mood"] = "__nope__" },
      "不在情绪表内", "坏 mood __nope__")
    hit((s) => { s["locales"]["L0"]["dialogue"][0]["gesture"]["poses"] = ["__nope__"] },
      "POSE_CODES", "坏姿态码 __nope__")
    hit((s) => { s["locales"]["L0"]["prop"]["device"]["style"] = "__nope__" },
      "DEVICE_STYLES", "坏装置样式 __nope__")
    hit((s) => { s["locales"]["L0"]["dialogue"][0]["speaker"] = "C" },
      "非法", "幽灵说话人 C（§0.4 未声明）")
    hit((s) => { s["tokens"]["ghost"] = "#000000" },
      "tokens 有、tokenOrder 没有", "token 表多出幽灵键")
    hit((s) => { s["roles"] = {} },
      "§0.4 没声明任何角色", "空角色表")
    hit((s) => { delete s["beats"] },
      "缺骨架节拍表", "缺节拍表")
    hit((s) => { s["locales"]["L0"]["dialogue"][1]["i"] = s["locales"]["L0"]["dialogue"][0]["i"] },
      "台词行号重复", "台词行号重复")
    hit((s) => { s["cast"] = [{ role: "A", locale: "L0", framing: "full" }] },
      "form=dialogue 不该有", "dialogue 形态带 §0.6 同台表")
    hit((s) => { s["form"] = "polyglot"; delete s["cast"] },
      "缺 §0.6 同台表", "polyglot 缺同台表")
  })
})

describe("课件校验层：真实课件 × 真实班底（§8 选角/彩蛋全量数据）", () => {
  it("guangchaoshi-逛超市/scene.json 零问题（dialogue × 3 语种）", () => {
    const scene = JSON.parse(readFileSync(
      join(LESSONS_DIR, "guangchaoshi-逛超市", "scene.json"), "utf8"))
    const errs = validateScene(scene, personas(), cardsDoc())
    expect(errs).toEqual([])
  })
})
