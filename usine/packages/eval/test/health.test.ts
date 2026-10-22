// health.test.ts — @feuille/eval 的门禁套件。
//
// 纪律 1（好数据放行是第一条断言）：好课例算出来的健康分是好看的，compare 自己比自己
// 判 unchanged。
// 纪律 2（加了新检查就要做反向验证）：篡改一份 fixture 让失败出现，compare 必须报出
// 退化——恒过的探针等于没有探针。
// 纪律 8（没数据留 null 不填 0）：算不出来的指标是 null，且 null 与 0 在判定层后果
// 不同（null → not-comparable，不判退化；0 → 可判定）。
// 纪律 12（SKIP 与 PASS 分列）：本套件零网络、零浏览器、零额度。
import { spawnSync } from "node:child_process"
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import { afterEach, describe, expect, it, vi } from "vitest"

import {
  compareReports, computeHealth, main, reportText, SCHEMA_VERSION,
  type Direction, type HealthReport,
} from "../src/index.js"

/** 仓库根（packages/eval/test → usine 根）。 */
const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..")

const tmpRoots: string[] = []
function tmpDir(tag: string): string {
  const d = mkdtempSync(join(tmpdir(), `feuille-eval-${tag}-`))
  tmpRoots.push(d)
  return d
}
afterEach(() => {
  for (const d of tmpRoots.splice(0)) rmSync(d, { recursive: true, force: true })
  vi.restoreAllMocks()
})

/** 造一份只含一个指标的合成报告（compare 的四种结论用它构造，不碰真实课例）。 */
function synth(
  value: number | null,
  samples: number,
  direction: Direction = "higher_is_better",
  metric = "locale_matrix",
): HealthReport {
  return {
    schema_version: SCHEMA_VERSION,
    inputs_sha256: "0".repeat(64),
    metrics: { [metric]: { value, unit: "rate", samples, direction, detail: {} } },
  }
}

/** 截住 stdout / stderr（CLI 输出不刷屏，断言照样看得到）。 */
function captureStdout(): { out: () => string; err: () => string } {
  const chunks: string[] = []
  const errs: string[] = []
  vi.spyOn(process.stdout, "write").mockImplementation((chunk: unknown) => {
    chunks.push(String(chunk))
    return true
  })
  vi.spyOn(process.stderr, "write").mockImplementation((chunk: unknown) => {
    errs.push(String(chunk))
    return true
  })
  return { out: () => chunks.join(""), err: () => errs.join("") }
}

/** 仓库里**真能体检**的那门课。
 *
 * 这里不能再假设「lessons/ 下只有一课」：2026-10-22 实测，`lessons/` 下有三个
 * 目录，而只有一门同时带 `scene.json`（`scene.md` 的编译产物）。`computeHealth()`
 * 走 `sceneDoc()`，缺 `scene.json` 直接抛 `FeuilleError`——于是「按字母序取第一个」
 * 取到空壳课，三条反向验证用例全挂在 fixture 准备上，而不是挂在被测逻辑上。
 *
 * 所以按**有没有 `scene.json`** 挑：那才是 `computeHealth()` 真正需要的东西。
 */
function lessonIds(): string[] {
  const base = join(REPO, "lessons")
  return readdirSync(base)
    .filter((name) => name !== ".DS_Store")
    .filter((name) => existsSync(join(base, name, "scene.json")))
    .sort()
}

/** 把仓库里那门课复制到临时 lessons 目录（返回该目录）。 */
function copyLesson(): { lessonsDir: string; id: string } {
  const id = lessonIds()[0]!
  const dir = tmpDir("lessons")
  const lessonsDir = join(dir, "lessons")
  mkdirSync(lessonsDir, { recursive: true })
  cpSync(join(REPO, "lessons", id), join(lessonsDir, id), { recursive: true })
  return { lessonsDir, id }
}

// ================================================================ 确定性

describe("健康分：确定性", () => {
  it("连跑两次逐字节相同（无时间戳、无随机数、无绝对路径）", () => {
    const a = reportText(computeHealth())
    const b = reportText(computeHealth())
    expect(a).toBe(b)
    expect(a).not.toContain(REPO)          // 绝对路径不许进报告
    expect(a).not.toMatch(/\d{4}-\d{2}-\d{2}T/)  // 时间戳不许进报告
  })

  it("inputs_sha256 只随输入内容变：内容相同 → 哈希相同", () => {
    const a = computeHealth()
    const b = computeHealth()
    expect(a.inputs_sha256).toBe(b.inputs_sha256)
    expect(a.inputs_sha256).toMatch(/^[0-9a-f]{64}$/)
  })
})

// ================================================================ 纪律 8：null ≠ 0

describe("纪律 8：没数据留 null 不填 0", () => {
  it("算不出来的指标是 null（不是 0），并写明无可离线复算的入口", () => {
    const r = computeHealth()
    for (const name of ["layout_fit", "timeline_alignment"] as const) {
      const m = r.metrics[name]!
      expect(m.value).toBeNull()
      expect(m.value).not.toBe(0)
      expect(m.samples).toBe(0)
      expect(String(m.detail["reason"])).toContain("无可离线复算的入口")
    }
  })

  it("null 与 0 在判定层后果不同：null → not-comparable（不判退化）", () => {
    const result = compareReports(synth(0, 14), synth(null, 14))
    expect(result.metrics[0]!.verdict).toBe("not-comparable")
    expect(result.exit_code).toBe(0)
    expect(result.regressed).toEqual([])
    expect(result.not_comparable).toEqual(["locale_matrix"])
  })

  it("样本不足（<5）→ not-comparable，不判退化（纪律 8）", () => {
    const result = compareReports(synth(0.2, 3), synth(0.9, 3))
    expect(result.metrics[0]!.verdict).toBe("not-comparable")
    expect(result.metrics[0]!.reason).toContain("样本不足")
    expect(result.exit_code).toBe(0)
  })
})

// ================================================================ 指标口径

describe("指标口径：语种矩阵", () => {
  it("分母 = 语种注册表（14 个语种），分子 = 跑过同一套 schema 校验且零错误的语种", () => {
    const r = computeHealth()
    const m = r.metrics["locale_matrix"]!
    expect(m.unit).toBe("rate")
    expect(m.direction).toBe("higher_is_better")
    expect(m.samples).toBe(14)
    const detail = m.detail as Record<string, unknown>
    expect(detail["registry"]).toContain("14")
    const rows = detail["locales"] as Array<{ locale: string; status: string; reasons: string[] }>
    expect(rows).toHaveLength(14)
    // 每行都要有可判定的状态与理由，不许留白
    for (const row of rows) {
      expect(["pass", "fail", "not_covered"]).toContain(row.status)
      if (row.status !== "pass") expect(row.reasons.length).toBeGreaterThan(0)
    }
  })

  it("未覆盖的语种算未通过（矩阵未覆盖是事实，不是「不知道」）", () => {
    const r = computeHealth()
    const detail = r.metrics["locale_matrix"]!.detail as Record<string, unknown>
    const rows = detail["locales"] as Array<{ locale: string; covered: boolean; status: string }>
    const missed = rows.filter((x) => !x.covered)
    expect(missed.length).toBeGreaterThan(0)
    for (const row of missed) expect(row.status).toBe("not_covered")
    const passed = Number(detail["passed"])
    const covered = Number(detail["covered"])
    expect(passed).toBeLessThanOrEqual(covered)
    expect(r.metrics["locale_matrix"]!.value).toBeCloseTo(passed / 14, 6)
  })
})

// ================================================================ compare 四态

describe("compare：四种结论", () => {
  it("regressed → 退出码非 0", () => {
    const result = compareReports(synth(0.5, 14), synth(0.2, 14))
    expect(result.metrics[0]!.verdict).toBe("regressed")
    expect(result.exit_code).not.toBe(0)
    expect(result.regressed).toEqual(["locale_matrix"])
  })

  it("improved → 退出码 0", () => {
    const result = compareReports(synth(0.2, 14), synth(0.5, 14))
    expect(result.metrics[0]!.verdict).toBe("improved")
    expect(result.exit_code).toBe(0)
  })

  it("unchanged → 退出码 0", () => {
    const result = compareReports(synth(0.5, 14), synth(0.5, 14))
    expect(result.metrics[0]!.verdict).toBe("unchanged")
    expect(result.exit_code).toBe(0)
  })

  it("not-comparable（基线为 null）→ 退出码 0 且如实标 not-comparable", () => {
    const result = compareReports(synth(null, 14), synth(0.5, 14))
    expect(result.metrics[0]!.verdict).toBe("not-comparable")
    expect(result.exit_code).toBe(0)
  })

  it("方向不同的两个指标不互相比（口径变了就不是同一个量）", () => {
    const result = compareReports(synth(0.5, 14, "higher_is_better"), synth(0.2, 14, "lower_is_better"))
    expect(result.metrics[0]!.verdict).toBe("not-comparable")
    expect(result.exit_code).toBe(0)
  })
})

// ================================================================ 反向验证（纪律 2）

describe("反向验证：篡改 fixture 必须报出退化（恒过的探针等于没有探针）", () => {
  it("好课例跟自己比 → unchanged（纪律 1：好数据放行是第一条断言）", () => {
    const { lessonsDir, id } = copyLesson()
    const baseline = computeHealth({ lessonsDir, lessonId: id })
    const candidate = computeHealth({ lessonsDir, lessonId: id })
    const result = compareReports(baseline, candidate)
    expect(result.regressed).toEqual([])
    expect(result.metrics.find((m) => m.metric === "locale_matrix")!.verdict).toBe("unchanged")
    expect(result.exit_code).toBe(0)
  })

  it("把一个语种的台词清空 → 通过率下降 → compare 报 regressed → 退出码非 0", () => {
    const { lessonsDir, id } = copyLesson()
    const baseline = computeHealth({ lessonsDir, lessonId: id })
    const before = baseline.metrics["locale_matrix"]!.value as number

    // 凿洞：拿掉一个语种的全部台词（schema 校验会当场报「dialogue 为空」）
    const scenePath = join(lessonsDir, id, "scene.json")
    const doc = JSON.parse(readFileSync(scenePath, "utf8")) as Record<string, any>
    const target = Object.keys(doc["locales"]).sort()[0]!
    doc["locales"][target]["dialogue"] = []
    writeFileSync(scenePath, JSON.stringify(doc, null, 2), "utf8")

    const candidate = computeHealth({ lessonsDir, lessonId: id })
    const after = candidate.metrics["locale_matrix"]!.value as number
    expect(after).toBeLessThan(before)

    const result = compareReports(baseline, candidate)
    const row = result.metrics.find((m) => m.metric === "locale_matrix")!
    expect(row.verdict).toBe("regressed")
    expect(result.regressed).toEqual(["locale_matrix"])
    expect(result.exit_code).not.toBe(0)
    // 失败原因要可判定：校验器的原话进报告，不做语义猜测
    const detail = candidate.metrics["locale_matrix"]!.detail as Record<string, unknown>
    const rows = detail["locales"] as Array<{ locale: string; status: string; reasons: string[] }>
    const bad = rows.find((r) => r.locale === target)!
    expect(bad.status).toBe("fail")
    expect(bad.reasons.join("；")).toContain("dialogue")
  })

  it("篡改 token chip（非法色片）→ 整课例结构坏掉 → 通过率下跌 → 报 regressed", () => {
    const { lessonsDir, id } = copyLesson()
    const baseline = computeHealth({ lessonsDir, lessonId: id })
    const scenePath = join(lessonsDir, id, "scene.json")
    const doc = JSON.parse(readFileSync(scenePath, "utf8")) as Record<string, any>
    const key = Object.keys(doc["tokens"]).sort()[0]!
    doc["tokens"][key] = "#ZZZ"        // 非法色片：校验器必报
    writeFileSync(scenePath, JSON.stringify(doc, null, 2), "utf8")
    const candidate = computeHealth({ lessonsDir, lessonId: id })
    const result = compareReports(baseline, candidate)
    expect(result.regressed).toEqual(["locale_matrix"])
    expect(result.exit_code).not.toBe(0)
  })
})

// ================================================================ CLI

describe("CLI：health / compare", () => {
  it("health 把 JSON 打到 stdout", () => {
    const cap = captureStdout()
    expect(main(["health"])).toBe(0)
    const doc = JSON.parse(cap.out()) as HealthReport
    expect(doc.schema_version).toBe(SCHEMA_VERSION)
    expect(Object.keys(doc.metrics).sort()).toEqual(["layout_fit", "locale_matrix", "timeline_alignment"])
  })

  it("compare：regressed → 退出码非 0；improved → 0；not-comparable → 0 且如实标注", () => {
    const dir = tmpDir("cmp")
    const base = join(dir, "base.json")
    const cand = join(dir, "cand.json")
    writeFileSync(base, reportText(synth(0.5, 14)), "utf8")
    writeFileSync(cand, reportText(synth(0.2, 14)), "utf8")
    let cap = captureStdout()
    expect(main(["compare", "--baseline", base, "--candidate", cand])).not.toBe(0)
    expect(cap.out()).toContain("regressed")
    expect(cap.out()).toContain("locale_matrix")

    writeFileSync(cand, reportText(synth(0.9, 14)), "utf8")
    cap = captureStdout()
    expect(main(["compare", "--baseline", base, "--candidate", cand])).toBe(0)
    expect(cap.out()).toContain("improved")

    writeFileSync(cand, reportText(synth(0.2, 3)), "utf8")
    cap = captureStdout()
    expect(main(["compare", "--baseline", base, "--candidate", cand])).toBe(0)
    expect(cap.out()).toContain("not-comparable")
  })

  it("compare 缺参数 → 退出码 2（用法错）", () => {
    captureStdout()
    expect(main(["compare", "--baseline", "x.json"])).toBe(2)
  })

  it("未知命令 → 退出码 2", () => {
    captureStdout()
    expect(main(["nope"])).toBe(2)
  })

  it("端到端：真跑一次 node --import tsx（bin 路径可执行）", () => {
    const dir = tmpDir("e2e")
    const base = join(dir, "base.json")
    const cand = join(dir, "cand.json")
    writeFileSync(base, reportText(synth(0.5, 14)), "utf8")
    writeFileSync(cand, reportText(synth(0.2, 14)), "utf8")
    const r = spawnSync(process.execPath, [
      "--import", "tsx", join(REPO, "packages", "eval", "src", "index.ts"),
      "compare", "--baseline", base, "--candidate", cand,
    ], { cwd: REPO, encoding: "utf8" })
    expect(r.status).not.toBe(0)
    expect(r.stdout).toContain("regressed")
  })
})
