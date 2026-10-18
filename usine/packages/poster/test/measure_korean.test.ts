// measure_korean.test.ts — @feuille/poster measure_korean 的反向验证门禁。
//
//   hangulSyllableName  Python unicodedata.name 真值表（LVT 算法名 + '?' 回退）
//   CLUSTER_FINALS      11 个复合终声码位（NFD 拆不出双 jamo——A-03 많 的根源）
//   jamoDeomp           合法/非法输入（NFD + 码位带校验）
//   掩膜代数            mOr/mAnd/mNot/dilate/erode/labelComponents（8 连通）
//   largestRect         直方图栈算法（全真矩形 / 空掩膜 → null）
//   rectCover           贪心 + cap；expandRects 禁区外扩；dedupeRects 含置去重
//   coverVowel          不相交放行 / 红蓝叠墨响亮失败 / 盖不满响亮失败
//   classify            终声带 + 右半带 + 横向元音底组 + 融合连通域 + 无元音
//   emitRule            双值百分比定位的精确格式
//   e2e                 真 Noto Sans KR 子集 → 차 一次量测 → .kCC28 规则 + verify PASS
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, afterEach, describe, expect, it, vi } from 'vitest'

import { FeuilleError, platform } from '@feuille/core'

import { fetch_fonts } from '../src/index.js'
import * as mk from '../src/measure_korean.js'
import type { BMask, Comp, Rect } from '../src/measure_korean.js'

const HAS_BROWSER = platform.browserPath() !== null

function M(h: number, w: number, cells: Array<[number, number]>): BMask {
  const m = mk.mNew(h, w)
  for (const [y, x] of cells) m.d[y * w + x] = 1
  return m
}

function comp(x0: number, y0: number, x1: number, y1: number): Comp {
  const mask = M(y1 - y0 + 1, x1 - x0 + 1, [])
  return { mask, x0, x1, y0, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 }
}

function captureLog(): { log: string[] } {
  const log: string[] = []
  vi.spyOn(console, 'log').mockImplementation((...a: unknown[]) => {
    log.push(a.map(String).join(''))
  })
  return { log }
}

afterEach(() => {
  vi.restoreAllMocks()
})

// ============ unicodedata.name 移植 ============

describe('hangulSyllableName：Python unicodedata 真值（UAX34 LVT 算法名）', () => {
  // 真值由系统 python3 unicodedata.name 生成校准（含 19 初声里的
  // ㅇ=''、ㅈ=J、ㅊ=C，与 28 终声里的单ㄹ='L'）
  const TRUTH: Array<[string, string]> = [
    ['차', 'HANGUL SYLLABLE CA'], // ㅊ → C（不是 CHA）
    ['한', 'HANGUL SYLLABLE HAN'], // ㅎ 初声出现（曾因缺 'J' 项整体错位的回归锚）
    ['자', 'HANGUL SYLLABLE JA'], // ㅈ → J
    ['하', 'HANGUL SYLLABLE HA'],
    ['호', 'HANGUL SYLLABLE HO'],
    ['많', 'HANGUL SYLLABLE MANH'], // 复合终声 ㄶ → NH
    ['값', 'HANGUL SYLLABLE GABS'], // ㅄ → BS
    ['없', 'HANGUL SYLLABLE EOBS'],
    ['복', 'HANGUL SYLLABLE BOG'], // ㅋ 终声前的 ㄱ → G（不是 K）
    ['요', 'HANGUL SYLLABLE YO'], // ㅇ 初声不出现
    ['국', 'HANGUL SYLLABLE GUG'],
    ['떨', 'HANGUL SYLLABLE DDEOL'], // 单ㄹ 终声 → L（不是 R）
    ['관', 'HANGUL SYLLABLE GWAN'],
    ['원', 'HANGUL SYLLABLE WEON'],
    ['핥', 'HANGUL SYLLABLE HALT'], // ㄹㅌ → LT
    ['넓', 'HANGUL SYLLABLE NEOLB'], // ㄹㅂ → LB
    ['좋', 'HANGUL SYLLABLE JOH'],
    ['아', 'HANGUL SYLLABLE A'],
    ['톤', 'HANGUL SYLLABLE TON'],
  ]

  it('19 个真值样本逐一对上（迁移期两处转写表错位都在这里被咬住过）', () => {
    for (const [s, want] of TRUTH) {
      expect(mk.hangulSyllableName(s)).toBe(want)
    }
  })

  it('非音节 → ?（unicodedata 回退口径）', () => {
    expect(mk.hangulSyllableName('A')).toBe('?')
    expect(mk.hangulSyllableName('ㄱ')).toBe('?')
  })
})

describe('CLUSTER_FINALS：两个声母构成的终声（NFD 拆不开）', () => {
  it('11 个码位：많/값/넓/핥 的 T 都在，单 ㄹ（떨）不在', () => {
    expect(mk.CLUSTER_FINALS.size).toBe(11)
    expect(mk.CLUSTER_FINALS.has('많'.normalize('NFD').codePointAt(2)!)).toBe(true) // ᆭ U+11AD
    expect(mk.CLUSTER_FINALS.has('값'.normalize('NFD').codePointAt(2)!)).toBe(true) // ㅄ U+11B9
    expect(mk.CLUSTER_FINALS.has('넓'.normalize('NFD').codePointAt(2)!)).toBe(true) // ㄼ U+11B6
    expect(mk.CLUSTER_FINALS.has('핥'.normalize('NFD').codePointAt(2)!)).toBe(true) // ㄾ U+11BA
    expect(mk.CLUSTER_FINALS.has('떨'.normalize('NFD').codePointAt(2)!)).toBe(false) // 单 ㄹ
  })
})

// ============ jamoDeomp ============

describe('jamoDeomp：NFD 分解 + 码位带校验', () => {
  it('차 → (U+110E, U+1161, null)；많 → 终声是 ᆭ（复合终声单码位）', () => {
    const [L, V, T] = mk.jamoDeomp('차')
    expect(L.codePointAt(0)).toBe(0x110e) // NFD 初声 jamo（ㅊ），非兼容 jamo U+314A
    expect(V.codePointAt(0)).toBe(0x1161)
    expect(T).toBeNull()
    const t = mk.jamoDeomp('많')[2]
    expect(t!.codePointAt(0)).toBe(0x11ad)
  })

  it('非法输入响亮失败（非预组音节 / 兼容 jamo）', () => {
    expect(() => mk.jamoDeomp('A')).toThrow(FeuilleError)
    expect(() => mk.jamoDeomp('ㄱ')).toThrow(FeuilleError) // 兼容 jamo U+3131 不在 U+1100 块
    expect(() => mk.jamoDeomp('ㅏ')).toThrow(FeuilleError)
  })
})

// ============ 掩膜代数 ============

describe('掩膜代数：mOr/mAnd/mNot/dilate/erode', () => {
  it('布尔代数：or/and/not/andNot 逐位', () => {
    const a = M(1, 4, [[0, 0], [0, 1]])
    const b = M(1, 4, [[0, 1], [0, 2]])
    expect([...mk.mOr(a, b).d]).toEqual([1, 1, 1, 0])
    expect([...mk.mAnd(a, b).d]).toEqual([0, 1, 0, 0])
    expect([...mk.mNot(a).d]).toEqual([0, 0, 1, 1])
    expect([...mk.mAndNot(a, b).d]).toEqual([1, 0, 0, 0])
  })

  it('dilate：方形结构元（Chebyshev 半径）逐次外扩（5×5 中心 → 9 → 25 px）', () => {
    const m = M(5, 5, [[2, 2]])
    expect(mk.mCount(mk.dilate(m, 1))).toBe(9) // 方形不是十字：含对角
    expect(mk.mCount(mk.dilate(m, 2))).toBe(25)
    expect(mk.mCount(mk.dilate(m, 0))).toBe(1) // r=0 原样拷贝
  })

  it('erode：dilate 的逆对（实心块 → 内缩核；孤立单点 → 空）', () => {
    // 7×7 里 (1..5)×(1..5) 实心块 → 腐蚀 1 → 内部 3×3
    const cells: Array<[number, number]> = []
    for (let y = 1; y <= 5; y++) for (let x = 1; x <= 5; x++) cells.push([y, x])
    const e = mk.erode(M(7, 7, cells), 1)
    expect(mk.mCount(e)).toBe(9)
    expect(e.d[2 * 7 + 2]).toBe(1) // 内部保住
    expect(e.d[1 * 7 + 1]).toBe(0) // 边界被吃掉
    // 孤立单点：邻域永不满 → 腐蚀即空
    expect(mk.mAny(mk.erode(M(5, 5, [[2, 2]]), 1))).toBe(false)
  })
})

describe('labelComponents：8 连通（对角相接算同一连通域）', () => {
  it('对角链 → 1 个域；远处孤点 → 第 2 个域（行主序发现序）', () => {
    // 4×3：主对角线 + 左下孤点
    const m = M(4, 3, [[0, 0], [1, 1], [2, 2], [3, 0]])
    const comps = mk.labelComponents(m)
    expect(comps).toHaveLength(2)
    expect(comps[0]!.ys.sort()).toEqual([0, 1, 2]) // 对角链
    expect(comps[1]!.ys).toEqual([3]) // 孤点后发现
  })
})

// ============ largestRect ============

describe('largestRect：全 True 最大轴对齐矩形', () => {
  it('全真 → 整幅；空 → null；L 形 → 最大子矩形面积', () => {
    const full = M(3, 4, [[0, 0], [0, 1], [0, 2], [0, 3], [1, 0], [1, 1], [1, 2], [1, 3], [2, 0], [2, 1], [2, 2], [2, 3]])
    expect(mk.largestRect(full)).toEqual([12, 0, 0, 3, 2])

    expect(mk.largestRect(M(3, 3, []))).toBeNull()

    // L 形：竖 1×3 + 横 3×1（共享角）→ 最大子矩形面积 3
    const l = M(3, 3, [[0, 0], [1, 0], [2, 0], [2, 1], [2, 2]])
    const r = mk.largestRect(l)
    expect(r![0]).toBe(3)
  })
})

// ============ rectCover / expandRects / dedupeRects ============

describe('rectCover：贪心最大矩形 + cap', () => {
  it('两个分离块 → 两条矩形、无残墨', () => {
    const m = M(8, 8, [
      [0, 0], [0, 1], [0, 2], [0, 3], [1, 0], [1, 1], [1, 2], [1, 3], [2, 0], [2, 1], [2, 2], [2, 3], [3, 0], [3, 1], [3, 2], [3, 3],
      [4, 5], [4, 6], [4, 7], [5, 5], [5, 6], [5, 7], [6, 5], [6, 6], [6, 7], [7, 5], [7, 6], [7, 7],
    ])
    const [rects, rest] = mk.rectCover(m)
    expect(rects).toHaveLength(2)
    expect(mk.mAny(rest)).toBe(false)
  })

  it('cap=4：5 个孤立点只盖 4 个，第 5 个残在返回掩膜里（Python 同款 cap 行为）', () => {
    const m = M(1, 10, [[0, 0], [0, 2], [0, 4], [0, 6], [0, 8]])
    const [rects, rest] = mk.rectCover(m, 4)
    expect(rects).toHaveLength(4)
    expect(mk.mCount(rest)).toBe(1)
  })
})

describe('expandRects：向禁区外扩到扩不动', () => {
  it('单点矩形 + 一个禁区点 → 被挡在禁区前（其余三向到边）', () => {
    const forbidden = M(9, 9, [[4, 4]])
    const rects: Rect[] = [[1, 1, 1, 1]]
    mk.expandRects(rects, forbidden, [9, 9])
    // 上/左/右到边；下探到 y=3（y=4 整行含禁区点，挡住）
    expect(rects[0]).toEqual([0, 0, 8, 3])
  })
})

describe('dedupeRects：被包含的矩形剔除（外扩残条收敛）', () => {
  it('大吃小；等大的重复只留一个', () => {
    const got = mk.dedupeRects([[0, 0, 10, 10], [2, 2, 5, 5], [0, 0, 10, 10]])
    expect(got).toEqual([[0, 0, 10, 10]])
  })
})

// ============ coverVowel ============

describe('coverVowel：红矩形垫片的三道闸', () => {
  it('红蓝不相交 → 矩形放行（盖全红、不碰蓝）', () => {
    const red = M(4, 16, [
      [0, 0], [0, 1], [0, 2], [0, 3],
      [1, 0], [1, 1], [1, 2], [1, 3],
      [2, 0], [2, 1], [2, 2], [2, 3],
      [3, 0], [3, 1], [3, 2], [3, 3],
    ])
    const blue = M(4, 16, [[1, 10], [1, 11], [2, 10], [2, 11]])
    const [rects, err] = mk.coverVowel(red, blue, 2)
    expect(err).toBeNull()
    expect(rects).not.toBeNull()
    expect(rects!.length).toBeGreaterThanOrEqual(1)
    // 每条矩形离蓝墨 ≥ margin（右边缘不越过 dilate(blue,2) 的左墙 x=8）
    for (const [, , x1] of rects!) expect(x1).toBeLessThanOrEqual(7)
  })

  it('凿洞：红蓝墨重叠 → 响亮失败（不做任何拆分兜底）', () => {
    const red = M(3, 3, [[1, 1], [0, 0]])
    const blue = M(3, 3, [[1, 1], [2, 2]])
    const [rects, err] = mk.coverVowel(red, blue, 2)
    expect(rects).toBeNull()
    expect(err).toBe('vowel and consonant ink overlap')
  })

  it('凿洞：cap 内盖不满的红墨 → 响亮失败', () => {
    // closing = erode(dilate(red,2),2) ⊇ red：17 个相距 6px 的孤立红点 →
    // 17 个互不合并的 5×5 closing 块，贪心 cap=12 + strip cap=4 只盖得下
    // 16 块 → 第 17 个点盖不满。蓝竖条纹（每对点之间一道）把每块的扩边
    // 挡在墙内——真量测里蓝墨就是这么包住元音区的；不设墙时扩边会沿
    // 自由行一路铺满全幅、反而盖得全
    const w = 106
    const h = 13
    const blueCells: Array<[number, number]> = []
    for (let k = 0; k <= 17; k++) for (let y = 0; y < h; y++) blueCells.push([y, 1 + 6 * k])
    const blue = M(h, w, blueCells)
    const red = M(h, w, Array.from({ length: 17 }, (_, k) => [6, 4 + 6 * k] as [number, number]))
    const [rects, err] = mk.coverVowel(red, blue, 2)
    expect(rects).toBeNull()
    expect(err).toBe('1 vowel px not coverable')
  })
})

// ============ classify ============

describe('classify：几何先验标 V/C', () => {
  it('终声带：底带域标 C（thr = top + 0.80·hink）', () => {
    const comps = [comp(0, 0, 4, 10), comp(6, 0, 10, 10), comp(0, 12, 3, 16)]
    const [labels, err] = mk.classify(comps, true, 0x1161)
    expect(err).toBeNull()
    expect(labels).toEqual(['C', 'V', 'C'])
  })

  it('终声在场但没有域够到底带 → 响亮失败', () => {
    // 全部连通域同高（hink=0 → thr=0.8·1）：没有任何 y1 越线
    const comps = [comp(0, 0, 2, 0), comp(3, 0, 5, 0)]
    const [, err] = mk.classify(comps, true, 0x1161)
    expect(err).toContain('no component reaches the bottom band')
  })

  it('竖排元音：右半带（cx-left > 0.5·wink）标 V', () => {
    const comps = [comp(0, 0, 4, 10), comp(6, 0, 10, 10)]
    const [labels, err] = mk.classify(comps, false, 0x1161) // ㅏ：非横向
    expect(err).toBeNull()
    expect(labels).toEqual(['C', 'V'])
  })

  it('横向元音：非终声域的最底一组标 V（相对窗口，不吃绝对阈值）', () => {
    // ㅗ/ㅜ 型：元音墨在底部但不进右半带——必须靠底组规则
    const a = comp(0, 0, 9, 10) // 初声：宽、居左上（cx 4.5 不越 0.5·wink=4.5）
    const b = comp(0, 8, 4, 16) // 元音：中下（cx 2 不越右半带，cy 12 在最底组）
    const [labels, err] = mk.classify([a, b], false, 0x1169) // ㅘ：横向
    expect(err).toBeNull()
    expect(labels).toEqual(['C', 'V'])
  })

  it('凿洞：初声+中声融合成单一连通域 → 响亮失败（A-03 요 实锤形态）', () => {
    const comps = [comp(0, 0, 10, 10)]
    const [, err] = mk.classify(comps, false, 0x1169)
    expect(err).toContain('ONE fused component')
    expect(err).toContain('--vowel-comp')
  })

  it('凿洞：没有任何域被标成元音 → 响亮失败', () => {
    // 两个域都窄、都居左：cx 都不越 0.5·wink=1（严格大于判据）
    const comps = [comp(0, 0, 2, 10), comp(0, 11, 1, 14)]
    const [, err] = mk.classify(comps, false, 0x1161)
    expect(err).toBe('no component labeled vowel')
  })
})

// ============ emitRule ============

describe('emitRule：双值百分比定位（Chrome 百分比对齐公式）', () => {
  it('单矩形：image/position/size 三行精确格式 + 末位 cons 全幅层', () => {
    const got = mk.emitRule('kCC28', [[10, 20, 29, 39]], 100, 50)
    const want = [
      '.kCC28 {',
      '  background-image: linear-gradient(var(--vowel),var(--vowel)), linear-gradient(var(--cons),var(--cons));',
      '  background-position: 12.5% 66.7%, 0 0;',
      '  background-size: 20.0% 40.0%, 100% 100%;',
      '}',
    ].join('\n')
    expect(got).toBe(want)
  })

  it('image 尺寸 ≥ 盒子 → 定位百分比退 0.0%（除零护）', () => {
    const got = mk.emitRule('kCC28', [[0, 0, 99, 49]], 100, 50)
    expect(got).toContain('background-position: 0.0% 0.0%, 0 0;')
  })
})

// ============ e2e：真字体真浏览器（免费本机渲字，零额度） ============

describe('measure-korean e2e：차 全链路（fetch_fonts → measure → verify）', () => {
  const d = mkdtempSync(join(tmpdir(), 'mk-test-'))
  afterAll(() => rmSync(d, { recursive: true, force: true }))

  it(HAS_BROWSER
    ? 'Noto Sans KR 子集 + 200px 量测 → .kCC28 规则 + verify PASS'
    : '跳过：本机无 Chromium 系浏览器', { timeout: 300_000 }, async () => {
    if (!HAS_BROWSER) return
    const spec = join(d, 'fonts.json')
    writeFileSync(spec, JSON.stringify([
      { family: 'OBS KR', google: 'Noto+Sans+KR:wght@400', text: '차' },
    ]), 'utf-8')
    expect(await fetch_fonts.main([spec])).toBe(0)
    const out = join(d, 'k')
    const { log } = captureLog()
    const rc = await mk.main([
      '차', '--family', "'OBS KR'", '--css', join(d, 'fonts.css'), '--out', out,
    ])
    const out_ = log.join('\n')
    if (rc !== 0) console.error(out_) // 失败时把量测表吐给诊断
    expect(rc).toBe(0)
    expect(out_).toContain('.kCC28 {') // 차 = U+CC28：码位是规则名
    expect(out_).toContain('HANGUL SYLLABLE CA') // 真值打印（操作员不用猜）
    expect(out_).toContain('verify 차: PASS')
    expect(out_).toMatch(/patches: \d+ red rect\(s\)/) // ㅊ|ㅏ 两连通域；矩形数随 AA 洞浮动
  })
})
