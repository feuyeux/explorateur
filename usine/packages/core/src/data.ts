// data.ts — 数据入口唯一事实源（data.py 的 TS 移植：personas / intro-cards /
// languages / scene.json）。
//
// 数据在哪、怎么读、读成什么形状，只在本模块定义一次——此前 personas.json
// 被多处各自 JSON.parse、路径各自手抄，改目录结构时必漏。
//
// 目录参数化：personas/ 与 languages/ 是**能力数据**（班底 + 语种注册表，
// 渲染与校验共用），缺省 = 仓库根下这份；lessons/ 是内容项目数据，
// 内容项目把自己的目录指进来。缓存按实参分键，不同目录互不串味。
//
// 不变量：经本模块取回的数据是**只读**的。进程内缓存返回同一对象，任何
// 模块 mutate 它都会污染同进程内的其他读者。
import { existsSync, readFileSync, statSync, readdirSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { FeuilleError } from "./errors.js"

// 只读 JSON 文档的承载形状：消费方（persona/rig/scenes）按需收窄。
// 本模块只做「读与索引」，不做 schema 判定（那是 persona.ts 的事）。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any

// ROOT 由本文件位置向上定位仓库根（pnpm-workspace.yaml 所在层），
// 包内默认路径（personas/ languages/ lessons/）不依赖 cwd。
// 环境变量 FEUILLE_ROOT 允许覆盖：非源码树形态用它把数据根指回仓库。
function findRoot(): string {
  if (process.env.FEUILLE_ROOT) return resolve(process.env.FEUILLE_ROOT)
  let dir = dirname(fileURLToPath(import.meta.url))
  for (;;) {
    if (existsSync(join(dir, "pnpm-workspace.yaml"))) return dir
    const parent = dirname(dir)
    if (parent === dir) {
      throw new FeuilleError(
        "feuille 数据根定位失败：从包位置向上没有 pnpm-workspace.yaml"
        + "——设置环境变量 FEUILLE_ROOT 指向 feuille 仓库根（含 personas/ languages/）",
      )
    }
    dir = parent
  }
}

export const ROOT = findRoot()

export const PERSONAS_DIR = join(ROOT, "personas")
export const PERSONAS_PATH = join(PERSONAS_DIR, "personas.json")
export const CARDS_PATH = join(PERSONAS_DIR, "intro-cards.json")
export const LANGUAGES_DIR = join(ROOT, "languages")
export const LESSONS_DIR = join(ROOT, "lessons")

function readJson(path: string): Json {
  return JSON.parse(readFileSync(path, "utf8"))
}

/** 可选目录参数 → 路径：null/undefined/空串 = 缺省目录。 */
function dirOr(given: string | undefined | null, dflt: string): string {
  return given ? resolve(given) : dflt
}

// 进程内缓存（Python lru_cache 按实参分键的对应）：键 = 实参（undefined
// 用哨兵），值 = 只读文档。测试用 resetDataCacheForTests 清缓存。
const cache = new Map<string, Json>()

function cached<T>(key: string, make: () => T): T {
  if (!cache.has(key)) cache.set(key, make())
  return cache.get(key) as T
}

/** personas.json 全文（含顶层字段）。只读。 */
export function personasDoc(personasDir?: string): Json {
  return cached(`personas:${personasDir ?? ""}`, () =>
    readJson(join(dirOr(personasDir, PERSONAS_DIR), "personas.json")))
}

/** 班底之外的**编外专班**（storyteller.json：说书人等单角色专职）。
 *
 * 为什么不进 personas.json：班底级不变量（每语种恰一男一女 × 一活泼一沉稳，
 * persona.validateRoster）会把编外角色判成破坏配对，而编外专班本来就不占
 * A/B 选角槽。逐人字段契约与班底**同一份** validatePersona（脸型/音色/
 * 挂件全走同一注册表），只在 roster 配对不变量上豁免。
 *
 * 目录参数化同 personas：缺省 = PERSONAS_DIR（与 personas.json 同目录，
 * 随班底一起版本化）。文件缺失 = 空专班（调用方无需判文件存在）。
 */
export function extrasDoc(extrasDir?: string): Json {
  return cached(`extras:${extrasDir ?? ""}`, () => {
    const path = join(dirOr(extrasDir, PERSONAS_DIR), "storyteller.json")
    if (!existsSync(path)) return { note: "", personas: [] }
    return readJson(path)
  })
}

/** {id: persona} 索引（编外专班）。未配置 = 空。 */
export function storytellers(extrasDir?: string): Record<string, Json> {
  const out: Record<string, Json> = {}
  for (const p of extrasDoc(extrasDir)["personas"] as Json[]) out[p["id"]] = p
  return out
}

/** {locale: languages/<locale>/manifest.json}。语种目录——**语种知识的事实源**。
 *
 * 此前语种的东西散在三处：字体栈、国旗 emoji、`personas[].langLabel`。加一个
 * 语种要同时改三处，漏一处不报错，只是静静渲出一个「没有旗的语言牌」——
 * 这类洞只能靠目录化 + 门禁堵。
 *
 * 语种目录收的是**语种自身的属性**（文字、旗、书写方向、字体栈），不是某一
 * 门课的剧本属性：`rtl` 同时也出现在剧本 §0 `rtlLocales`（那是 §0 声明体例
 * 的一部分，保留），两者必须一致。
 */
export function languageManifests(languagesDir?: string): Record<string, Json> {
  return cached(`langs:${languagesDir ?? ""}`, () => {
    const base = dirOr(languagesDir, LANGUAGES_DIR)
    const out: Record<string, Json> = {}
    if (!existsSync(base) || !statSync(base).isDirectory()) return out
    for (const name of readdirSync(base).sort()) {
      const f = join(base, name, "manifest.json")
      if (statSync(join(base, name)).isDirectory() && existsSync(f)) {
        out[name] = readJson(f)
      }
    }
    return out
  })
}

/** {locale: CSS font-family 栈}——供文字层渲染用。 */
export function fontsCss(languagesDir?: string): Record<string, string> {
  return cached(`fonts:${languagesDir ?? ""}`, () => {
    const out: Record<string, string> = {}
    for (const [loc, m] of Object.entries(languageManifests(languagesDir))) {
      out[loc] = m["fontCss"]
    }
    return out
  })
}

/** {locale: 国旗 emoji}。Windows Segoe UI Emoji 无国旗字形 → 渲染为 ISO 双字母对
 * （见手册坑⑬：禁为「补旗」私画简化国旗，错旗比字母对更糟）。 */
export function flags(languagesDir?: string): Record<string, string> {
  return cached(`flags:${languagesDir ?? ""}`, () => {
    const out: Record<string, string> = {}
    for (const [loc, m] of Object.entries(languageManifests(languagesDir))) {
      out[loc] = m["flag"]
    }
    return out
  })
}

/** 语种文字（语言牌上的「汉语」「希腊语」）。未知语种即报错，不静默回落成裸 locale。 */
export function langLabel(locale: string, languagesDir?: string): string {
  const m = languageManifests(languagesDir)[locale]
  if (!m) {
    throw new FeuilleError(
      `无此语种目录：languages/${locale}/manifest.json（新增语种=新建目录）`)
  }
  return m["label"]
}

/** {id: persona} 索引。渲染线、探针线、场景线统一取这里。 */
export function personas(personasDir?: string): Record<string, Json> {
  return cached(`idx:${personasDir ?? ""}`, () => {
    const out: Record<string, Json> = {}
    for (const p of personasDoc(personasDir)["personas"] as Json[]) out[p["id"]] = p
    return out
  })
}

/** intro-cards.json 全文（28 张卡的台词/情绪/手势/选角）。只读。 */
export function cardsDoc(personasDir?: string): Json {
  return cached(`cards:${personasDir ?? ""}`, () =>
    readJson(join(dirOr(personasDir, PERSONAS_DIR), "intro-cards.json")))
}

// scene_doc（lessons/<id>/scene.json）依赖 parse_scene（lesson 族，P5 迁入）——
// 届时以延迟 import 的同款契约补上，避免现在留一个指向空模块的口子。

/** 测试 seam：清进程内数据缓存（vitest 内隔离用；生产代码不许调）。 */
export function resetDataCacheForTests(): void {
  cache.clear()
}
