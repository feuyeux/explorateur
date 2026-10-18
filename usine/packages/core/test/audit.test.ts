// audit.test.ts — 格律计数审计的反向验证（verify_audit.py §0–§1 的 vitest 移植；
// §2 节替换属 section_patch（lesson 族，P5 迁入时补），§3 打包已在 packaging.test.ts）。
//
// 合成多语诗稿的每个计数器都命中**手工独立数出**的期望值（防循环验证——
// 期望值不用被测算法反推）。
import { afterEach, describe, expect, it, vi } from "vitest"

import { auditAll, auditOne, countAr, countDeVowelGroups, countElSyllables,
  countEsVowelGroups, countHe, countHi, countHiMatras, countKoBlocks,
  countRuVowels, countZhChars, hebrewSyllables, hindiSplit } from "../src/audit.js"

// 合成多语诗稿（自包含夹具）。每行期望值都是手工独立数出的（Python 门禁
// verify_audit 同一夹具同值——跨语言逐值一致本身就是 parity 判据）。
const POEM: Record<string, string[]> = {
  "中文": ["秋风吹尽满山金，一叶知秋天地心。"],                      // [7, 7]
  "印地语": ["एक पत्ता गिरा शीतकाल आया, पेड़ नंगे हुए धरती ठंडी।",  // 24 = 13+11
    "ठंडी हवा चली सूखे पत्ते झड़े, धरती ठंडी पेड़ नंगे खड़े।"],
  "阿拉伯语": ["الرِّيحُ تَهُبُّ وَالوَرَقُ يَسْقُطُ",                 // 17
    "القَمَرُ يَشْرَقُ عَلى الوُرُودِ"],                    // 16
  "希伯来语": ["סְתָיו בָּא, הָרוּחַ קָרָה",                       // 8
    "עָלֶה נוֹפֵל עַל הָאָרֶץ"],                           // 9
  "俄语": ["Лист одинок, но лес богат.",                          // 8
    "Осень идёт, и лист летит."],                           // 8
  "希腊语": ["Ένα φύλλο πέφτει σιγά.", "Ο ουρανός αλλάζει χρώμα."],  // [8, 9]
  "德语": ["Das Blatt fällt auf den stillen See.",                // 8
    "Still schweigt die Welt, wie sie will."],               // 7
  "西班牙语": ["La hoja cae, el viento la lleva.", "El otoño canta."],  // [10, 6]
  "韩语": ["단풍 드는 가을밤", "바람 불면 낙엽도",
    "높은 하늘 구름도", "모두 가을 길 따라"],                  // 7×4
}

let writes: string[] = []
afterEach(() => {
  writes = []
  vi.restoreAllMocks()
})

function captureWrites(): void {
  vi.spyOn(process.stdout, "write").mockImplementation((chunk: unknown) => {
    writes.push(String(chunk))
    return true
  })
}

describe("计数器对合成诗稿命中手数期望值", () => {
  it("印地语 Matra = 24+24（Doha 24 = 13+11）", () => {
    expect(countHi(POEM["印地语"]!)).toEqual([24, 24])
  })
  it("Doha 前后半 = 13+11", () => {
    expect(hindiSplit(POEM["印地语"]![0]!)).toEqual([13, 11])
  })
  it("阿拉伯语音节 = 17+16（一核一音节）", () => {
    expect(countAr(POEM["阿拉伯语"]!)).toEqual([17, 16])
  })
  it("希伯来语音节 = 8+9（闭音节优先）", () => {
    expect(countHe(POEM["希伯来语"]!)).toEqual([8, 9])
    expect(hebrewSyllables("סְתָיו בָּא, הָרוּחַ קָרָה")).toHaveLength(8)
  })
  it("中文按字数（逗号才是断句处）= 7+7", () => {
    expect(countZhChars(POEM["中文"]!)).toEqual([7, 7])
  })
  it("俄语元音 = 8+8", () => {
    expect(countRuVowels(POEM["俄语"]!)).toEqual([8, 8])
  })
  it("希腊语音节（双元音算一；句首大写元音也数）= 8+9", () => {
    expect(countElSyllables(POEM["希腊语"]!)).toEqual([8, 9])
  })
  it("德语元音组（sch→X、ie/ee 算一）= 8+7", () => {
    expect(countDeVowelGroups(POEM["德语"]!)).toEqual([8, 7])
  })
  it("西语元音组 = 10+6", () => {
    expect(countEsVowelGroups(POEM["西班牙语"]!)).toEqual([10, 6])
  })
  it("韩语谚文方块 = 7×4；组合型字母双写收一", () => {
    expect(countKoBlocks(POEM["韩语"]!)).toEqual([7, 7, 7, 7])
    expect(countKoBlocks(["ㄱㅏㄴ"])).toEqual([1])
  })
  it("印地依附元音与虚音记 0（matra 口径）", () => {
    expect(countHiMatras("क्")).toBe(1)
    expect(countHiMatras("ा")).toBe(0)
  })
})

describe("auditAll 全批跑：三态汇总", () => {
  it("通过 3 · 不作声称 1 · 需处理 0", () => {
    captureWrites()
    const res = auditAll([
      { lang: "中文", lines: POEM["中文"]!, claim: [7, 7] },
      { lang: "俄语", lines: POEM["俄语"]!, claim: [8, 8] },
      { lang: "希腊语", lines: POEM["希腊语"]!, claim: [8, 9] },
      { lang: "阿拉伯语", lines: POEM["阿拉伯语"]!, noClaim: true },
    ])
    const tail = writes.join("").split("\n").find((ln) => ln.startsWith("实测通过"))!
    expect(res.slice(0, 3).every((r) => r.status.startsWith("✅"))).toBe(true)
    expect(res[3]!.status.startsWith("○")).toBe(true)
    expect(tail).toContain("通过 3")
    expect(tail).toContain("不作声称 1")
    expect(tail).toContain("需处理 0")
  })
})

describe("三态审计逻辑（纯函数定向验证）", () => {
  it("声称与实测相符 → ✅", () => {
    const ok = auditOne("中文", ["霜柯初陨知天地，晴旭微倾值万金。"], { claim: [7, 7] })
    expect(ok.status.startsWith("✅")).toBe(true)
  })
  it("声称不符 → ❌（消息带实测值）", () => {
    const bad = auditOne("中文", ["一二三四五六七，一二三四五六七。"], { claim: [5, 5] })
    expect(bad.status.startsWith("❌")).toBe(true)
    expect(bad.status).toContain("实测 [7, 7]")
  })
  it("主动不作声称 → ○ 第三态（不算失败）", () => {
    const nc = auditOne("中文", ["一二三四五六七"], { noClaim: true })
    expect(nc.status.startsWith("○")).toBe(true)
  })
  it("无声称且未声明不作声称 → ❌ 未登记", () => {
    const un = auditOne("中文", ["一二三"])
    expect(un.status.startsWith("❌")).toBe(true)
    expect(un.status).toContain("未登记")
  })
  it("手写 ≠ 算法 → 以算法为准并告警", () => {
    const mixed = auditOne("俄语", ["Один листок"],
      { splits: [["О", "дин", "ли", "сток", "лишний"]] })
    expect(mixed.warn).not.toBe("")
    expect(mixed.actual).toEqual(mixed.algo)
  })
})
