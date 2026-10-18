// data.test.ts — 数据入口唯一事实源的契约验证（Python 侧无独立 verify——
// data.py 由 personas/scene 线间接覆盖；这里把它的使用契约直接钉成断言：
// 目录定位、索引形状、只读缓存同引用、目录参数化互不串味、未知语种报错）。
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"

import {
  ROOT, cardsDoc, extrasDoc, flags, fontsCss, langLabel, languageManifests,
  personas, personasDoc, resetDataCacheForTests, storytellers,
} from "../src/data.js"
import { FeuilleError } from "../src/errors.js"

const tmpRoots: string[] = []
function tmp(): string {
  const d = mkdtempSync(join(tmpdir(), "feuille-data-"))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
  resetDataCacheForTests()
})

describe("数据根定位", () => {
  it("ROOT 向上定位仓库根（pnpm-workspace.yaml 所在层），默认路径挂着", () => {
    expect(ROOT).not.toBe("")
    expect(personasDoc()["personas"].length).toBe(28)
    expect(cardsDoc()["cards"].length).toBe(28)
  })
})

describe("索引形状（渲染线 / 探针线 / 场景线统一取这里）", () => {
  it("personas() → {id: persona}，28 人全员有 id", () => {
    const idx = personas()
    expect(Object.keys(idx).length).toBe(28)
    expect(idx["xiaoman"]["id"]).toBe("xiaoman")
  })
  it("languageManifests() 语种目录（跳过 README.md / .DS_Store 等非目录）", () => {
    const langs = languageManifests()
    for (const key of ["zh-CN", "en-US", "ar-SA", "he-IL", "hi-IN", "ru-RU", "el-GR", "ja-JP", "ko-KR"]) {
      expect(langs[key], `语种 ${key}`).toBeDefined()
    }
    expect(Object.keys(langs)).not.toContain("README.md")
  })
  it("fontsCss / flags / langLabel 取自语种目录", () => {
    expect(typeof fontsCss()["zh-CN"]).toBe("string")
    expect(flags()["zh-CN"]!.length).toBeGreaterThan(0)
    expect(langLabel("zh-CN")).toBe("汉语")
    expect(() => langLabel("xx-XX")).toThrow(FeuilleError)
    expect(() => langLabel("xx-XX")).toThrow("无此语种目录")
  })
})

describe("只读缓存契约", () => {
  it("进程内缓存返回同一对象（mutate 会污染同进程其他读者）", () => {
    expect(personasDoc()).toBe(personasDoc())
    expect(personas()).toBe(personas())
  })
  it("缓存按目录实参分键，不同目录互不串味", () => {
    const d = tmp()
    const custom = join(d, "personas")
    mkdirSync(custom, { recursive: true })
    writeFileSync(join(custom, "personas.json"),
      JSON.stringify({ personas: [{ id: "only-one" }] }), "utf8")
    expect(Object.keys(personas(custom))).toEqual(["only-one"])
    expect(Object.keys(personas()).length).toBe(28)
  })
})

describe("编外专班（storyteller.json）", () => {
  it("默认随班底版本化；缺失目录 = 空专班", () => {
    const ex = storytellers(join(tmp())) // 空目录 → storyteller.json 不存在
    expect(Object.keys(ex)).toEqual([])
    expect(extrasDoc(join(tmp())).personas).toEqual([])
  })
})
