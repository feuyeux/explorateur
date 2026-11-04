// chord.ts — 和弦模板库 + 模糊 Jaccard 分类 + 众数平滑 + 切段。
//
// 为什么是「模板分类」而不是「序列对齐」：子序列 DTW 的代价每步累加，
// 结构性把 19s 的参考序列压进 2.1s 音频（实测映射点全挤在 8.4–10.5s），
// 这是代价模型的结构性质，不是 bug（traps §1）。替代路径就是本文件：
// 逐帧分类 → 众数平滑 → 切段 → 按乐谱块顺序对拍。
//
// **去重组**（traps §1 的第二个坑）：重复音级集的和弦块（块 0 与块 2 同为
// E–G♯–B）如果直接逐块 argmax，argmax 恒取第一个模板、后一块永远匹配
// 不到。所以分类时必须把**已经用掉的模板**排除掉，让同音级集的后一块
// 去匹配别的模板。
import { PITCH_NAMES } from './dsp.js'

/** 和弦类型：相对根音的半音集合。 */
const CHORD_SHAPES: ReadonlyArray<readonly [string, readonly number[]]> = [
  ["", [0, 4, 7]],        // major
  ["m", [0, 3, 7]],       // minor
  ["dim", [0, 3, 6]],
  ["aug", [0, 4, 8]],
  ["5", [0, 7]],          // power chord
  ["sus2", [0, 2, 7]],
  ["sus4", [0, 5, 7]],
  ["maj7", [0, 4, 7, 11]],
  ["7", [0, 4, 7, 10]],
  ["m7", [0, 3, 7, 10]],
  ["m7b5", [0, 3, 6, 10]],
  ["dim7", [0, 3, 6, 9]],
  ["6", [0, 4, 7, 9]],
  ["m6", [0, 3, 7, 9]],
  ["add9", [0, 2, 4, 7]],
  ["9", [0, 4, 7, 10, 2]],
]

export interface ChordTemplate {
  /** 模板 id（根音名 + 类型，如 "Eb" / "Cmaj7"）。 */
  id: string
  /** 根音音级（0..11）。 */
  root: number
  /** 类型后缀。 */
  suffix: string
  /** 音级集合。 */
  pcs: number[]
  /** 全部模板里的序号（去重组时用作「已用掉」的键）。 */
  index: number
}

/** 全部模板（12 根音 × 类型）。顺序固定——argmax 取「第一个最大」时
 * 结果必须可复现。 */
export const CHORD_TEMPLATES: readonly ChordTemplate[] = (() => {
  const out: ChordTemplate[] = []
  for (let root = 0; root < 12; root++) {
    for (const [suffix, iv] of CHORD_SHAPES) {
      out.push({
        id: `${PITCH_NAMES[root]!}${suffix}`,
        root,
        suffix,
        pcs: iv.map((i) => (root + i) % 12).sort((a, b) => a - b),
        index: out.length,
      })
    }
  }
  return out
})()

/** 音级集合的规范键（升序去重，用作「同一音级集」的判据）。 */
export function pcSetKey(pcs: readonly number[]): string {
  return [...new Set(pcs.map((p) => ((p % 12) + 12) % 12))].sort((a, b) => a - b).join(",")
}

/**
 * 模糊 Jaccard：观测音级集 A 与模板 B 的相似度。
 *
 * A 的每个音级在 B 里找最佳匹配：完全相同记 1，相邻半音记 0.5（容忍
 * 走音与内声部的半音经过音），否则 0。分母取 max(|A|,|B|)——比标准
 * Jaccard 更宽容，因为现场录音的音级集常比模板多（内声部/经过音）。
 */
export function fuzzyJaccard(a: readonly number[], b: readonly number[]): number {
  if (a.length === 0 || b.length === 0) return 0
  let overlap = 0
  for (const x of a) {
    let best = 0
    for (const y of b) {
      const d = Math.min((x - y + 12) % 12, (y - x + 12) % 12)
      const s = d === 0 ? 1 : d === 1 ? 0.5 : 0
      if (s > best) best = s
    }
    overlap += best
  }
  return overlap / Math.max(a.length, b.length)
}

/** 一次分类的结果。 */
export interface ChordMatch {
  template: ChordTemplate | null
  score: number
  /** 候选的前几名（调试用）。 */
  top: Array<{ id: string; score: number }>
}

/**
 * 逐帧分类：A 的音级集匹配哪个模板。
 *
 * `excludeTemplates` 是**去重组**的抓手：已经用掉的模板不再参与 argmax，
 * 于是同音级集的后续块会去匹配别的模板。
 */
export function classifyChord(
  pcs: readonly number[],
  excludeTemplates: ReadonlySet<number> = new Set(),
): ChordMatch {
  if (pcs.length === 0) return { template: null, score: 0, top: [] }
  let best: ChordTemplate | null = null
  let bestScore = -1
  const top: Array<{ id: string; score: number }> = []
  for (const t of CHORD_TEMPLATES) {
    if (excludeTemplates.has(t.index)) continue
    const s = fuzzyJaccard(pcs, t.pcs)
    if (s > bestScore) {
      bestScore = s
      best = t
    }
    if (s >= 0.5) top.push({ id: t.id, score: s })
  }
  top.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id))
  return { template: best, score: bestScore, top: top.slice(0, 5) }
}

/**
 * 众数平滑：窗口内取出现最多的标签（同数时取窗口内总相似度高的）。
 *
 * 为什么不平滑会碎：单帧的音级集随演奏的经过音跳变，逐帧 argmax 会让
 * 和弦标签在一拍内闪好几个。窗口取奇数帧（默认 5）。
 */
export function smoothLabels(
  labels: readonly (ChordTemplate | null)[],
  scores: readonly number[],
  window = 5,
): (ChordTemplate | null)[] {
  const n = labels.length
  const out: (ChordTemplate | null)[] = new Array(n)
  const half = Math.floor(window / 2)
  for (let i = 0; i < n; i++) {
    const lo = Math.max(0, i - half)
    const hi = Math.min(n - 1, i + half)
    const count = new Map<number, number>()
    const weight = new Map<number, number>()
    for (let j = lo; j <= hi; j++) {
      const t = labels[j]
      if (!t) continue
      count.set(t.index, (count.get(t.index) ?? 0) + 1)
      weight.set(t.index, (weight.get(t.index) ?? 0) + (scores[j] ?? 0))
    }
    let bestIdx = -1
    let bestCount = 0
    let bestWeight = -1
    for (const [idx, c] of count) {
      const w = weight.get(idx) ?? 0
      if (c > bestCount || (c === bestCount && w > bestWeight)) {
        bestIdx = idx
        bestCount = c
        bestWeight = w
      }
    }
    out[i] = bestIdx >= 0 ? CHORD_TEMPLATES[bestIdx]! : null
  }
  return out
}

/** 一个切段。 */
export interface ChordSegment {
  /** 起始帧号（含）。 */
  start: number
  /** 结束帧号（不含）。 */
  end: number
  label: string | null
  /** 该段观测到的音级集。 */
  pcs: number[]
  /** 平均相似度。 */
  score: number
}

/**
 * 切段：连续同标签的帧归一段，短于 `minFrames` 的碎段并进邻段。
 *
 * minFrames 的作用：抑制一帧一变的闪烁（众数平滑后仍可能留下孤帧）。
 */
export function segmentLabels(
  labels: readonly (ChordTemplate | null)[],
  pcsPerFrame: readonly number[][],
  scores: readonly number[],
  minFrames = 2,
): ChordSegment[] {
  const segs: ChordSegment[] = []
  let i = 0
  while (i < labels.length) {
    const key = labels[i]?.id ?? null
    let j = i + 1
    while (j < labels.length && (labels[j]?.id ?? null) === key) j++
    segs.push({
      start: i,
      end: j,
      label: key,
      pcs: [...new Set(pcsPerFrame.slice(i, j).flat())].sort((a, b) => a - b),
      score: scores.slice(i, j).reduce((a, b) => a + b, 0) / Math.max(1, j - i),
    })
    i = j
  }
  // 碎段并进邻段：孤帧段（长度 < minFrames）直接删掉——它不承载信息，
  // 留着只会在画面上多出一个闪点。
  return segs.filter((s) => s.end - s.start >= minFrames || s.label === null)
}
