// align.ts — 对齐层：录音 ↔ 谱面真值（Tier A）/ 录音实测（Tier B）。
//
// 两级真值（诚实轴，见 skills/music-annotate-video/SKILL.md「真值两级制」）：
//
// - **Tier A 谱面真值对齐**：MIDI 给出「谱面上此刻该响什么」，录音给出
//   「实际响了什么」。两边都做和弦分类，然后**按谱块顺序对拍**，得到
//   谱面时间 ↔ 录音时间的映射。
// - **Tier B 录音实测**：没有谱，就从录音里测旋律线（泛音和声评分 f0），
//   段落边界由探针（RMS 包络 / 高频峰簇）背书。
//
// **判据双条，缺一即 fail-closed**（不许当「差不多」读）：
//   ① 结构块落带内——谱块的起点必须落在观测段的时间带里；
//   ② 起点后 0.05–0.6s 的最强音级交集 ≥ 2/3。
// 任一条不满足，这一对配对判为不成立；连续不成立就整体报错，不硬凑。
import {
  CHORD_TEMPLATES,
  classifyChord,
  segmentLabels,
  smoothLabels,
  type ChordSegment,
  type ChordTemplate,
} from './chord.js'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { numOpt, parseArgs, strOpt } from './cli.js'
import {
  freqToMidi,
  magnitudeSpectrum,
  midiToFreq,
  rmsEnvelope,
  withDecoded,
  type Mono,
} from './dsp.js'
import { parseMidi, type MidiMeta } from './midi.js'

export interface AlignOptions {
  /** 分析帧跳（秒）。 */
  hopSec?: number
  /** FFT 窗长（样本）。 */
  fftSize?: number
  /** 众数平滑窗口（帧）。 */
  smoothWindow?: number
  /** 最短段（帧）。 */
  minSegmentFrames?: number
  /** 判定「结构块落带内」的容差（秒）。 */
  bandToleranceSec?: number
  /** 判定音级交集的窗口（秒）。 */
  intersectWindowSec?: number
  /** 置换检验次数（判据 3）。 */
  permutations?: number
  /** 置换的随机种子——**固定种子**，否则同一份输入两次跑出两个 p。 */
  seed?: number
  /**
   * 谱面的**按时间分层音级集**（判据 3 用；用 `timeLayers(midi, k)` 生成）。
   *
   * 为什么必须由调用方给：分层要按**整份 MIDI 的时间跨度**切，而 `alignBlocks`
   * 只拿到谱块（已经把时间信息压缩成 onset 序列，且单块不带总时长）。让本函数
   * 自己从谱块推总时长等于猜——最后一个块的 end 不是曲终。
   *
   * 不给 = 判据 3 无法量，`validated` 保持 false（fail-closed，不是「默认通过」）。
   */
  scoreLayers?: readonly (readonly number[])[]
}

const DEFAULTS: Required<Omit<AlignOptions, 'scoreLayers'>> = {
  hopSec: 0.05,
  fftSize: 4096,
  smoothWindow: 5,
  minSegmentFrames: 2,
  bandToleranceSec: 0.35,
  intersectWindowSec: 0.6,
  permutations: 2000,
  seed: 20261104,
}

/** 帧号 → 秒。 */
export function frameTime(frame: number, hopSec: number): number {
  return frame * hopSec
}

/** 观测到的和弦时间轴（对录音分类的结果）。 */
export interface ObservedChords {
  hopSec: number
  /** 每帧的模板（可能为 null = 该帧无有效和弦）。 */
  labels: (ChordTemplate | null)[]
  /** 每帧的相似度。 */
  scores: number[]
  /** 每帧的观测音级集。 */
  pcsPerFrame: number[][]
  /** 切段结果。 */
  segments: ChordSegment[]
}

/**
 * 对录音逐帧做和弦分类。
 *
 * 音级集从**频谱峰值**取：把频谱按半音分箱，对每帧取能量最高的若干个
 * 半音（默认 4 个）作为该帧的观测音级集。这个「取最强的几档」是折中：
 * 取太多会把内声部与经过音全算进来，模板匹配永远不准；取太少则只剩根音。
 */
export function observedChords(
  mono: Mono,
  opts: AlignOptions = {},
): ObservedChords {
  const o = { ...DEFAULTS, ...opts }
  const hop = Math.max(1, Math.round(o.hopSec * mono.sampleRate))
  const size = o.fftSize
  const nFrames = Math.max(0, Math.floor((mono.samples.length - size) / hop) + 1)

  const pcsPerFrame: number[][] = []
  const labels: (ChordTemplate | null)[] = []
  const scores: number[] = []

  for (let f = 0; f < nFrames; f++) {
    const mag = magnitudeSpectrum(mono, f * hop, size)
    const pcs = strongestPitchClasses(mag, mono.sampleRate, size, 4)
    pcsPerFrame.push(pcs)
    const m = classifyChord(pcs)
    labels.push(m.template)
    scores.push(m.score)
  }

  const smoothed = smoothLabels(labels, scores, o.smoothWindow)
  const segments = segmentLabels(smoothed, pcsPerFrame, scores, o.minSegmentFrames)
  return { hopSec: o.hopSec, labels: smoothed, scores, pcsPerFrame, segments }
}

/**
 * 从频谱取能量最强的若干个半音（观测音级集）。
 *
 * 分箱：对每个半音频率带，把该带内的谱线能量求和；再取最强的 N 个半音。
 * 半音带用 ±0.5 半音的边界切（避免一个泛音同时落进两个带）。
 */
export function strongestPitchClasses(
  mag: Float64Array,
  sampleRate: number,
  size: number,
  topN: number,
): number[] {
  const bandEnergy = new Float64Array(12)
  for (let k = 1; k < mag.length; k++) {
    const fr = (k * sampleRate) / size
    if (fr < 27.5) continue // A0 以下：钢琴与乐队都到不了，忽略
    const midi = freqToMidi(fr)
    const pc = Math.round(midi) % 12
    bandEnergy[pc] = bandEnergy[pc]! + mag[k]! * mag[k]!
  }
  const order = [...bandEnergy.keys()].sort((a, b) => bandEnergy[b]! - bandEnergy[a]!)
  return order.slice(0, topN).sort((a, b) => a - b)
}

/** 谱面里的一个和弦块。 */
export interface ScoreBlock {
  /** 谱面时间（秒）。 */
  onset: number
  /** 块结束（秒）。 */
  end: number
  /** 音级集。 */
  pcs: number[]
  /** 块内的音符。 */
  noteCount: number
}

/**
 * 从 MIDI 推导和弦块：按**起音**分组（起音相差在 `onsetTolerance` 内的
 * 音符归同一块）。
 *
 * 为什么按起音分而不是固定节拍：真实编配的和弦块长度不等（1 拍、2 拍、
 * 半拍都常见），按起音分组才与「听到的和弦」对齐。
 */
export function scoreBlocks(midi: MidiMeta, onsetTolerance = 0.06): ScoreBlock[] {
  const notes = [...midi.notes].sort((a, b) => a.start - b.start || a.pitch - b.pitch)
  const blocks: ScoreBlock[] = []
  let cur: ScoreBlock | null = null
  for (const n of notes) {
    if (cur && n.start - cur.onset <= onsetTolerance) {
      cur.pcs.push(n.pitch % 12)
      cur.end = Math.max(cur.end, n.end)
      cur.noteCount++
      continue
    }
    cur = { onset: n.start, end: n.end, pcs: [n.pitch % 12], noteCount: 1 }
    blocks.push(cur)
  }
  return blocks
}

/** 一次配对的判定。 */
export interface PairVerdict {
  blockIndex: number
  segmentIndex: number
  /** 谱面时间（秒）——作曲谱上的位置，不是录音里的位置。 */
  scoreTime: number
  /** 观测段的录音时间带（秒）。 */
  segStart: number
  segEnd: number
  /** 该段的录音时间是否与**全局速度拟合**一致（残差 ≤ 容差）。 */
  inBand: boolean
  /** 该段录音里真听到的音级与谱块音级的交集比例。 */
  intersection: number
  /** 交集 ≥ 2/3？ */
  intersectOk: boolean
  /** 两条判据都过？ */
  ok: boolean
  /** 配对理由。 */
  reason: string
}

/** 谱块 ↔ 观测段的配对结果。 */
export interface AlignResult {
  pairs: PairVerdict[]
  /** 全部配对都过？ */
  allOk: boolean
  /**
   * 谱面时间 → 录音时间的线性映射 `t_obs ≈ scale · t_score + offset`。
   * 演出是自由速度（rubato）与不同版本，所以这是一个**近似**：用它落摘录
   * 时间码之前，必须回头对着 `notes/probe` 的起音与段落收口核一遍。
   */
  offsetSec: number
  scale: number
  /** 拟合残差的中位数（秒）——演出偏离恒定速度多少，**只作诊断**。 */
  medianResidualSec: number
  /** 局部速度比的中位数（录音秒 / 谱面秒）——判据 2 的基准。 */
  medianLocalRatio: number
  /** 这条路到底「配得比乱配好多少」——判据 3 的读数。 */
  discrimination: Discrimination
  /**
   * 这条路能不能当真值用。
   *
   * **2026-11-06 起不再是恒 false**：判据 3 换成 `orderGain`（时间直对 vs 循环
   * 平移）后，在春/秋两首曲子的四象限受控实验里正例全过（p 0.020/0.029）、
   * 负例全拒（p 0.074/0.332），加混响与噪声后结论不变。判决条件 = p ≤ 0.05
   * **且** pathMean > nullMean（增益为正）。
   *
   * 但仍是 fail-closed：**没给 `scoreLayers` 就是 false**（判据 3 量不了，
   * 不许当默认通过）。而且实测口径必须说清——那是**合成音频**的读数（用
   * Mutopia 的 MIDI 自行合成，真值已知），**真实录音上的读数还没量过**
   * （本机 commons.wikimedia.org 连不通，春的真实录音取不到）。真实录音有
   * 音色、内声部掩蔽与踏板，间隔会变窄；在真录音上复现之前，摘录时间码
   * 仍应以 `notes/probe` 的起音与段落证据为准，Tier A 作旁证。
   */
  validated: boolean
  /** 为什么不 validated——逐条写明，不写「差不多」。 */
  validationNote: string
}

/**
 * 对拍的**辨别力**：DTW 路径上的音级交集均值，对比「同边距分布下随机配对」
 * 的零分布。
 *
 * 为什么要这一条：逐对判据（交集 ≥ 2/3、局部速度比在带内）在**配错**的谱上
 * 也大量通过——和弦模板只有 12 个音级类别，任何两条古典乐句的交集都过 2/3，
 * 而速度比的带只看「有没有突变」。实测：春的录音配春的谱通过 64.5%，配**秋**
 * 的谱通过 55.4%——这个差距不足以下任何结论。逐对判据是**必要条件**，不是
 * 「配对了」的证据。
 *
 * 于是判据 3 量的是**增量**：路径上的平均交集 vs 置换零分布（把配对随机打乱，
 * 边距分布不变），单侧精确置换检验。零分布宽度只报不判，判决用 `pValue`。
 */
export interface Discrimination {
  /** DTW 路径上的平均音级交集。 */
  pathMean: number
  /** 置换零分布的均值。 */
  nullMean: number
  /** 零分布的标准差——「差别有多大才算大」的量纲。 */
  nullSd: number
  /** 单侧精确置换检验的 p（`permutations + 1` 为分母，不会给出 0）。 */
  pValue: number
  /** 做了多少次置换。 */
  permutations: number
}

/** 判定「配对了」的 p 门限。取 0.05：见 `orderGain` 的实测分布。 */
export const ALIGN_P_VALUE = 0.05

/**
 * **顺序增益**：按时间直对，比任意循环平移好多少。
 *
 * ## 为什么要换掉「DTW 路径上的 pathMean + 循环平移零分布」
 *
 * 2026-11-04 的阴性对照失败（春的录音配秋的谱同样 p=0.0005）当时的归因是
 * 「和弦模板特征没有判别力，要用旋律轮廓替换」。**2026-11-06 的受控实验推翻
 * 了这个归因**——特征是有判别力的，坏的是统计量与零分布的**配对**：
 *
 * 用 Mutopia 的春谱与秋谱（真 MIDI），以春谱合成音频（真值已知）量四象限：
 *
 * | 象限 | DTW pathMean | 旧 p（循环平移） |
 * |---|---|---|
 * | 春音频 × 春谱 ★ | 0.733 | 4.998e-4 |
 * | 春音频 × 秋谱 | 0.486 | 4.998e-4 |
 * | 秋音频 × 春谱 | 0.524 | 4.998e-4 |
 * | 秋音频 × 秋谱 ★ | 0.566 | 4.998e-4 |
 *
 * pathMean 确实分得开（0.73 vs 0.49），但**四个象限的 p 全是同一个最小 p**。
 * 原因：统计量在 DTW 路径上取，而 DTW 的跳过自由**已经把顺序一致性买下来了**
 * ——路径总能挑出最像的那一半配对；再拿「循环平移」当零分布，路径当然永远
 * 赢平移。统计量与零分布测的不是同一件事。
 *
 * 提高跳过代价不能修（0.5→2.0 时秋的间隔只从 0.058 升到 0.089）。把谱块
 * 等分成与段数相同（1:1）也不能修（春 0.459 vs 0.377，秋 0.367 vs 0.305）：
 * 那仍然是在挑拣后的路径上量。
 *
 * ## 修法：不做 DTW，直接量「顺序」本身的信息量
 *
 * `gain = mean_i fuzzy(score_i, obs_i) − mean_{shift≠0} mean_i fuzzy(score_i, obs_{i+shift})`
 *
 * 两侧各自按时间从头到尾等分成 k 层（k = 观测段数），逐层比音级相似度。
 * 同曲同段时「直对」应当明显好于「任意平移」；不同曲时顺序不携带信息，
 * 增益趋零。实测（2000 次平移，同一批素材）：
 *
 * | 象限 | 增益 | p（干净） | p（混响+噪声） |
 * |---|---|---|---|
 * | 春×春 ★ | +0.029 | 0.022 | 0.020 |
 * | 秋×秋 ★ | +0.023 | 0.041 | 0.029 |
 * | 春×秋 | +0.004 | 0.191 | 0.332 |
 * | 秋×春 | +0.005 | 0.124 | 0.074 |
 *
 * 正例全过、负例全拒，且加混响与噪声（SNR≈10dB）后结论不变。门限取 0.05：
 * 正例最差 0.041、负例最好 0.074，中间有隙。**这是合成音频的读数**——
 * 真实录音有音色、内声部掩蔽与踏板，间隔会变窄；真实录音上的读数还没量过
 * （本机 commons.wikimedia.org 连不通，春的真实录音取不到）。所以 `validated`
 * 仍保持 fail-closed 保守，但**判据本身不再是恒真**——它现在能分辨了。
 *
 * ## 为什么不用「留出法两半一致性」
 *
 * 也试过：正例两半差 0.010、负例 0.003（春），秋正 0.007、秋负 0.023。
 * 不一致度的方向在两组间翻转，没有稳定符号，做不了判据。
 */
export function orderGain(
  scoreLayers: readonly (readonly number[])[],
  obsLayers: readonly (readonly number[])[],
  permutations = 2000,
  seed = 20261106,
): Discrimination {
  const k = Math.min(scoreLayers.length, obsLayers.length)
  if (k < 8) {
    // 层数太少时可用平移量不足，量不出顺序信息。不给判决（p=1）。
    return { pathMean: 0, nullMean: 0, nullSd: 0, pValue: 1, permutations: 0 }
  }
  const S = scoreLayers.slice(0, k)
  const O = obsLayers.slice(0, k)
  const pathMean = meanOf(S.map((b, i) => fuzzyOf(b, O[i]!)))

  let st = seed | 0 || 1
  const rnd = (): number => {
    st ^= st << 13; st |= 0
    st ^= st >>> 17
    st ^= st << 5; st |= 0
    return (st >>> 0) / 4294967296
  }
  const nulls: number[] = []
  let hits = 0
  for (let p = 0; p < permutations; p++) {
    const sh = 1 + Math.floor(rnd() * (k - 1))
    const v = meanOf(S.map((b, i) => fuzzyOf(b, O[(i + sh) % k]!)))
    nulls.push(v)
    if (v >= pathMean) hits++
  }
  const nullMean = meanOf(nulls)
  const variance = nulls.length
    ? meanOf(nulls.map((x) => (x - nullMean) ** 2))
    : 0
  return {
    pathMean,
    nullMean,
    nullSd: Math.sqrt(variance),
    pValue: (hits + 1) / (permutations + 1),
    permutations,
  }
}

function meanOf(xs: readonly number[]): number {
  return xs.reduce((a, b) => a + b, 0) / (xs.length || 1)
}

/**
 * 把音符流按时间等分成 k 层，每层取音级并集。
 *
 * 为什么要「按时间」而不是「按谱块」：谱块密度取决于织体（复调段一块一音、
 * 和弦段一块五音），按块数等分会让两层覆盖完全不同的时间跨度。按时间等分
 * 才与「观测段是按时间聚出来的」可比。
 */
export function timeLayers(
  midi: { duration: number; notes: readonly { start: number; pitch: number }[] },
  k: number,
): number[][] {
  if (k <= 0) return []
  const dur = Math.max(1e-9, midi.duration)
  const buckets: Array<Set<number>> = Array.from({ length: k }, () => new Set<number>())
  for (const n of midi.notes) {
    const idx = Math.min(k - 1, Math.floor((n.start / dur) * k))
    buckets[idx]!.add(n.pitch % 12)
  }
  return buckets.map((s) => [...s].sort((a, b) => a - b))
}

/**
 * 谱块顺序 ↔ 观测段顺序的 **DTW 对拍**。
 *
 * 为什么不能「按谱面时间比录音时间」（第一版就是这样，实测 457 个谱块通过
 * 0 个）：谱块带的是**作曲谱上的时间**（第一个谱块 onset=0），观测段带的是
 * **这段录音里的时间**（可能从 48s 才开始）。两者之间隔着「演出速度 + 版本
 * 差异 + 可能被剪掉的部分」，没有可比性。真正可比的是**顺序与音级内容**，
 * 于是用序列对拍（DTW）求出路径，再由路径反推时间映射。
 *
 * 两条判据都量**录音侧**的事实：
 * 1. `intersectOk` —— 在该观测段的帧区间上，真听到的音级与谱块音级的
 *    交集 ≥ 2/3。这是「谱上这组音，录音里此刻真在响」的检验。
 * 2. `inBand` —— 该段的录音时间与全局速度拟合（一条 least-squares 直线）
 *    的残差在容差内。残差大 = 这一处与整体速度不一致（自由速度、剪接、
 *    或者配错了）。**不用绝对时间容差**：演出速度未知，绝对容差没有意义。
 *
 * fail-closed：没有匹配到、音级不交集、或偏离拟合线，都记不成立。
 */
export function alignBlocks(
  blocks: readonly ScoreBlock[],
  observed: ObservedChords,
  opts: AlignOptions = {},
): AlignResult {
  const o = { ...DEFAULTS, ...opts }
  const hop = o.hopSec

  // 只看有分类标签的观测段（无标签 = 该段没测出和弦，不能拿来配）。
  const segs = observed.segments.filter((s) => s.label)

  // 合并相邻同音级集的谱块：同一和弦被拆成多块（不同声部先后起音）时，
  // 逐块对拍会让 DTW 反复配到同一段上。
  type Blk = { onset: number; end: number; pcs: number[] }
  const merged: Blk[] = []
  for (const b of blocks) {
    const prev = merged[merged.length - 1]
    const same = prev && prev.pcs.length === b.pcs.length
      && prev.pcs.every((p, i) => p === b.pcs[i])
    if (same) prev.end = Math.max(prev.end, b.end)
    else merged.push({ onset: b.onset, end: b.end, pcs: b.pcs })
  }

  const n = merged.length
  const m = segs.length
  if (!n || !m) {
    return {
    pairs: [], allOk: false, offsetSec: 0, scale: 1,
    medianResidualSec: 0, medianLocalRatio: 1,
    discrimination: { pathMean: 0, nullMean: 0, nullSd: 0, pValue: 1, permutations: 0 },
    validated: false, validationNote: '没有可配对的谱块或观测段',
  }
  }

  // 代价：1 − 模糊 Jaccard（音级集越像越便宜）。
  const cost = (i: number, j: number): number => {
    const a = merged[i]!.pcs
    const b = segs[j]!.pcs
    return 1 - fuzzyOf(a, b)
  }

  // 跳过一方的代价：谱块或观测段被跳过说明演奏/版本有差异，罚一半——
  // 既不禁止（真会有反复、删节、装饰），也不免费（否则可以把整条路径
  // 用跳过凑成零代价）。
  const SKIP = 0.5

  // DP：D[i][j] = 前 i 个谱块 与 前 j 个观测段 的最小累计代价。
  const D: Float64Array[] = Array.from({ length: n + 1 }, () => new Float64Array(m + 1))
  for (let i = 1; i <= n; i++) D[i]![0] = D[i - 1]![0]! + SKIP
  for (let j = 1; j <= m; j++) D[0]![j] = D[0]![j - 1]! + SKIP
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const diag = D[i - 1]![j - 1]! + cost(i - 1, j - 1)
      const up = D[i - 1]![j]! + SKIP
      const left = D[i]![j - 1]! + SKIP
      D[i]![j] = Math.min(diag, up, left)
    }
  }

  // 回溯：只有 **diag** 步骤算「配对」，up/left 是被跳过的一方。
  const matched: Array<{ bi: number; si: number }> = []
  let i = n
  let j = m
  while (i > 0 && j > 0) {
    const d = D[i]![j]!
    if (Math.abs(d - (D[i - 1]![j - 1]! + cost(i - 1, j - 1))) < 1e-9) {
      matched.push({ bi: i - 1, si: j - 1 })
      i--; j--
    } else if (Math.abs(d - (D[i - 1]![j]! + SKIP)) < 1e-9) {
      i--
    } else {
      j--
    }
  }
  matched.reverse()

  // 同一个谱块可能被路径配到**多个**观测段（斜着走之前连续 hit 同一块）——
  // 上面的回溯里每个 diag 步都推进两边，所以每个块至多一对。这里无需再去重。

  // 全局速度拟合：t_obs ≈ scale·t_score + offset。少于两对时用恒等映射
  // （没有信息可拟合，**不许**假装拟合出来了）。
  let scale = 1
  let offsetSec = 0
  if (matched.length >= 2) {
    const xs = matched.map((p) => merged[p.bi]!.onset)
    const ys = matched.map((p) => frameTime(segs[p.si]!.start, hop))
    const mx = xs.reduce((a, b) => a + b, 0) / xs.length
    const my = ys.reduce((a, b) => a + b, 0) / ys.length
    let num = 0
    let den = 0
    for (let k = 0; k < xs.length; k++) {
      num += (xs[k]! - mx) * (ys[k]! - my)
      den += (xs[k]! - mx) ** 2
    }
    if (den > 1e-9) {
      scale = num / den
      offsetSec = my - scale * mx
    } else {
      // 所有谱块同一时刻（单和弦作品）：只能给平移。
      scale = 1
      offsetSec = my - mx
    }
  }

  // 局部速度比必须在**一个窗口**上量，不能拿相邻两对直接除：观测段的平均
  // 长度（≈0.28s，hop 0.05 下的和弦分段）与谱块的平均长度（≈0.13s 谱面秒 ×
  // 速度 ≈0.46s 录音秒）是同一个量级，相邻两对的比值里带着半段的量化误差，
  // 噪声达到 ±2 倍——那是**量具的分辨率**，不是演奏的速度。窗口取 8 对
  // （≈1 秒谱面、≈3.6 秒录音），量化误差被平均掉，剩下的是真的速度。
  const W = 8
  const segStartOf = (k: number): number => frameTime(segs[matched[k]!.si]!.start, hop)
  const scoreOf = (k: number): number => merged[matched[k]!.bi]!.onset
  const localRatio: number[] = []
  for (let k = 0; k < matched.length; k++) {
    const lo = Math.max(0, k - Math.floor(W / 2))
    const hi = Math.min(matched.length - 1, lo + W)
    const lo2 = Math.max(0, hi - W)
    const dScore = scoreOf(hi) - scoreOf(lo2)
    const dObs = segStartOf(hi) - segStartOf(lo2)
    // 谱面上同一时刻（和弦内的分声部）或窗口没有跨度：量不出速度。
    localRatio.push(dScore > 0.02 ? dObs / dScore : NaN)
  }
  const finite = localRatio.filter((r) => Number.isFinite(r) && r > 0)
  const medianRatio = finite.length
    ? [...finite].sort((a, b) => a - b)[Math.floor(finite.length / 2)]!
    : 1

  // 判定阈值（**明写的阈值**，不是「差不多」）：局部速度比落在
  // [中位数 / 2, 中位数 × 2] 内算跟得上。取 2 倍的理由：一个乐章内的自由速度
  // 与段落伸缩常在 ±50% 内，2 倍已经在带外缘；而**配错**的路径给出的是十倍
  // 以上的跳变（见 `alignBlocks` 的阴性对照测试）。改这个数要连着改本注释、
  // 下面的 reason，以及那条测试。
  const RATIO_FACTOR = 2

  // 逐对判定。
  const pairs: PairVerdict[] = []
  const residuals: number[] = []
  for (let k = 0; k < matched.length; k++) {
    const { bi, si } = matched[k]!
    const b = merged[bi]!
    const seg = segs[si]!
    const segStart = frameTime(seg.start, hop)
    const segEnd = frameTime(seg.end, hop)

    // 判据 1：在这段的录音帧上真听到的音级与谱块音级的交集。
    const pcsInSeg = new Set<number>()
    for (let f = seg.start; f <= seg.end; f++) {
      for (const p of observed.pcsPerFrame[f] ?? []) pcsInSeg.add(p % 12)
    }
    const bSet = new Set(b.pcs.map((p) => p % 12))
    let inter = 0
    for (const p of bSet) if (pcsInSeg.has(p)) inter++
    const intersection = bSet.size === 0 ? 0 : inter / bSet.size
    const intersectOk = intersection >= 2 / 3

    // 判据 2：这一对所在窗口的局部速度比是否在带内。量不出速度
    // （和弦内分声部 / 窗口无跨度）→ 不给判定（fail-closed，不当「过」）。
    const r = localRatio[k]
    const rs = Number.isFinite(r) ? [r] : []
    const ratioOk = rs.length === 0
      ? false
      : rs.every((x) => x! > medianRatio / RATIO_FACTOR && x! < medianRatio * RATIO_FACTOR)
    const inBand = ratioOk

    // 残差只作诊断（自由速度下它本来就该大于容差，不能当判据）。
    residuals.push(Math.abs(segStart - (scale * b.onset + offsetSec)))

    const ok = inBand && intersectOk
    let reason: string
    if (ok) reason = '两条判据都过'
    else if (!intersectOk && !ratioOk) {
      reason = `音级交集 ${intersection.toFixed(2)} < 2/3；且局部速度比 ${rs.map((r) => r!.toFixed(1)).join('/')} 出带 `
        + `[${(medianRatio / RATIO_FACTOR).toFixed(1)}, ${(medianRatio * RATIO_FACTOR).toFixed(1)}]`
    } else if (!intersectOk) reason = `音级交集 ${intersection.toFixed(2)} < 2/3`
    else if (rs.length === 0) reason = '只有一对，量不出局部速度比——不判定（fail-closed）'
    else {
      reason = `局部速度比 ${rs.map((r) => r!.toFixed(1)).join('/')} 出带 `
        + `[${(medianRatio / RATIO_FACTOR).toFixed(1)}, ${(medianRatio * RATIO_FACTOR).toFixed(1)}]`
    }

    pairs.push({
      blockIndex: bi, segmentIndex: si, scoreTime: b.onset,
      segStart, segEnd, inBand, intersection, intersectOk, ok, reason,
    })
  }

  residuals.sort((a, b) => a - b)
  const medianResidualSec = residuals.length
    ? residuals[Math.floor(residuals.length / 2)]!
    : 0

  // 判据 3：辨别力。
  //
  // 2026-11-06 起用 `orderGain`（时间直对 vs 循环平移），不再用 DTW 路径上的
  // `measureDiscrimination`——后者的统计量已经被 DTW 的挑拣污染，四象限 p 全
  // 等于最小 p，量不出配错。旧读数留在 `measureDiscrimination` 里作归档。
  //
  // **观测侧必须用全部段，不是 `matched`**（2026-11-06 实测踩到）：`matched`
  // 是 DTW 挑出来的稀疏子集（夹具里 60 段只配上 10 段），拿它跟「按时间切满
  // 全曲的谱层」逐层比，等于把曲首的谱层跟散落全曲的段对比——量的是一段时间
  // 轴错位，不是「顺序对不对」。两侧都必须是覆盖同一整段时长的完整分层。
  const obsLayers = segs.map((s) => s.pcs)
  const scoreLayers = o.scoreLayers
  const discrimination = scoreLayers !== undefined && scoreLayers.length > 0
    ? orderGain(scoreLayers, obsLayers, o.permutations, o.seed)
    : {
        pathMean: 0, nullMean: 0, nullSd: 0, pValue: 1, permutations: 0,
      }

  // 判据 3 的判决：p 过门限**且**增益为正（p 小但增益为负 = 直对比平移还差，
  // 那是反向证据，不是证据）。
  const orderOk = scoreLayers !== undefined
    && scoreLayers.length > 0
    && discrimination.pValue <= ALIGN_P_VALUE
    && discrimination.pathMean > discrimination.nullMean

  return {
    pairs,
    allOk: pairs.length > 0 && pairs.every((p) => p.ok),
    offsetSec,
    scale,
    medianResidualSec,
    medianLocalRatio: medianRatio,
    discrimination,
    validated: orderOk,
    validationNote: orderOk
      ? `判据 3 通过：顺序增益 +${(discrimination.pathMean - discrimination.nullMean).toFixed(3)}`
        + `（p=${discrimination.pValue.toFixed(4)} ≤ ${ALIGN_P_VALUE}）`
      : scoreLayers === undefined || scoreLayers.length === 0
        ? '判据 3 未量：没给 scoreLayers（fail-closed）。'
          + ' 摘录时间码请走 notes/probe。'
        : `判据 3 未过：顺序增益 ${(discrimination.pathMean - discrimination.nullMean).toFixed(3)}`
          + `（p=${discrimination.pValue.toFixed(4)}）。`
          + ' 摘录时间码请走 notes/probe。',
  }
}

/**
 * 置换检验：路径上的平均音级交集 vs **循环平移**零分布。
 *
 * **2026-11-06：这个函数已被 `orderGain` 取代，不要再用于判决。**
 *
 * 它保留下来只为一件事：归档实测要能复现当时的读数。病灶是统计量与零分布
 * 不配对——统计量取自 DTW 路径（挑拣自由已经把顺序一致性买下来了），零分布
 * 却用循环平移，于是任何真实音乐对任何谱都赢平移，四象限 p 全等于最小 p。
 * 详见 `orderGain` 的注释与实测表。
 *
 * 当时的理由（为什么循环平移而不是打乱配对）本身是对的：打乱配对只检验
 * 「这段录音里有和弦结构」，任何古典谱都能通过。教训是**零分布正确不等于
 * 统计量正确**——两件事要分开验。
 */
export function measureDiscrimination(
  scorePcs: readonly (readonly number[])[],
  obsPcs: readonly (readonly number[])[],
  permutations = 2000,
  seed = 20261104,
): Discrimination {
  const n = Math.min(scorePcs.length, obsPcs.length)
  if (n < 4) {
    // 少于 4 对时循环平移几乎等于原配对（可用平移量只有 1~2 个），量不出
    // 辨别力。不给判决（p=1），交给调用方 fail-closed。
    return { pathMean: 0, nullMean: 0, nullSd: 0, pValue: 1, permutations: 0 }
  }
  const meanAtShift = (shift: number): number => {
    let acc = 0
    for (let k = 0; k < n; k++) acc += fuzzyOf(scorePcs[k]!, obsPcs[(k + shift) % n]!)
    return acc / n
  }
  const pathMean = meanAtShift(0)

  // 可用平移量：1 … n-1（0 就是路径本身）。
  const shifts = Array.from({ length: n - 1 }, (_, i) => i + 1)
  // xorshift32：小、可复现、无依赖。
  let st = seed | 0 || 1
  const rnd = (): number => {
    st ^= st << 13; st |= 0
    st ^= st >>> 17
    st ^= st << 5; st |= 0
    return ((st >>> 0) % 1000000) / 1000000
  }
  let hits = 0
  const nulls: number[] = []
  for (let p = 0; p < permutations; p++) {
    const shift = shifts[Math.floor(rnd() * shifts.length)]!
    const v = meanAtShift(shift)
    nulls.push(v)
    if (v >= pathMean) hits++
  }
  const nullMean = nulls.reduce((a, b) => a + b, 0) / (nulls.length || 1)
  const variance = nulls.length
    ? nulls.reduce((a, b) => a + (b - nullMean) ** 2, 0) / nulls.length
    : 0
  return {
    pathMean,
    nullMean,
    nullSd: Math.sqrt(variance),
    pValue: (hits + 1) / (permutations + 1),
    permutations,
  }
}

/** 模糊 Jaccard（与 chord.ts 同一口径，这里局部复算以免 import 循环语义）。 */
function fuzzyOf(a: readonly number[], b: readonly number[]): number {
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

// ============================================================
//  Tier B：泛音和声评分 f0（无谱时的旋律线）
// ============================================================

/** 旋律线的测量结果。 */
export interface MelodyTrack {
  hopSec: number
  /** 每帧的连续 MIDI 值（无音高 = null）。 */
  midi: (number | null)[]
  /** 量化后的 MIDI 音号（滞回量化后）。 */
  quantized: (number | null)[]
  /** 旋律段。 */
  segments: MelodySegment[]
}

/** 一个旋律段。 */
export interface MelodySegment {
  startFrame: number
  endFrame: number
  /** 段内主导音号。 */
  midi: number | null
  /** 段内主导音号的中位频率（Hz）。 */
  freq: number | null
}

/**
 * 泛音和声评分 f0。
 *
 * score(τ) = mean(r(τ), r(2τ), r(3τ), r(4τ)) / r(0)，其中 r 是幅度谱——
 * 谐波越多、越强，τ 越可能是基频。分母取该帧的总幅度（等价于 r(0) 的
 * 归一化作用），使分数在帧间可比。
 *
 * 三个必要的工程细节（traps §3）：
 * - **搜索带限定旋律音区**：默认 MIDI 55–88（G3–E6），排除伴奏基音区，
 *   否则独奏 + 低八度伴奏时逐帧在两个声部间跳（实测 210Hz↔530Hz）。
 * - **八度守卫**：若 τ/2 的分数显著高于 τ，判为八度偏高，取 τ/2。
 * - **搜索带外的候选不算**：频谱在候选频率处用线性插值取幅值。
 */
export function melodyF0(
  mono: Mono,
  opts: AlignOptions & { loMidi?: number; hiMidi?: number } = {},
): MelodyTrack {
  const o = { ...DEFAULTS, ...opts }
  const loMidi = opts.loMidi ?? 55
  const hiMidi = opts.hiMidi ?? 88
  const hop = Math.max(1, Math.round(o.hopSec * mono.sampleRate))
  const size = o.fftSize
  const nFrames = Math.max(0, Math.floor((mono.samples.length - size) / hop) + 1)
  const midi: (number | null)[] = []

  for (let f = 0; f < nFrames; f++) {
    const mag = magnitudeSpectrum(mono, f * hop, size)
    let total = 0
    for (let k = 1; k < mag.length; k++) total += mag[k]!
    if (total <= 0) {
      midi.push(null)
      continue
    }
    let bestP = -1
    let bestScore = 0
    const scores = new Map<number, number>()
    for (let p = loMidi; p <= hiMidi; p++) {
      const f0 = midiToFreq(p)
      let s = 0
      for (let h = 1; h <= 4; h++) {
        s += magAt(mag, mono.sampleRate, size, f0 * h) / h
      }
      scores.set(p, s)
      if (s > bestScore) {
        bestScore = s
        bestP = p
      }
    }
    // 八度守卫：半频候选的分数高出一截 → 取低八度
    if (bestP > loMidi) {
      const half = scores.get(bestP - 12) ?? 0
      if (half > bestScore * 1.6) {
        bestP -= 12
        bestScore = half
      }
    }
    // 连续值：分数加权后的亚半音精度（用相邻候选插值）
    midi.push(refineMidi(scores, bestP))
  }

  const smoothed = medianSmoothMidi(midi, 5)
  const quantized = hysteresisQuantize(smoothed)
  const segments = segmentMelody(quantized)
  return { hopSec: o.hopSec, midi: smoothed, quantized, segments }
}

/** 谱线插值取幅值。 */
function magAt(
  mag: Float64Array,
  sampleRate: number,
  size: number,
  freq: number,
): number {
  const bin = (freq * size) / sampleRate
  if (bin < 0 || bin >= mag.length - 1) return 0
  const i = Math.floor(bin)
  const frac = bin - i
  return mag[i]! * (1 - frac) + mag[i + 1]! * frac
}

/** 亚半音精修：在最优候选附近用分数抛物线插值。 */
function refineMidi(scores: Map<number, number>, best: number): number {
  const y0 = scores.get(best - 1) ?? 0
  const y1 = scores.get(best) ?? 0
  const y2 = scores.get(best + 1) ?? 0
  const denom = y0 - 2 * y1 + y2
  if (denom === 0) return best
  const delta = (0.5 * (y0 - y2)) / denom
  if (!Number.isFinite(delta) || Math.abs(delta) > 1) return best
  return best + delta
}

/** 半音域中值平滑（不是算术平均——中值对半音跳变更稳）。 */
export function medianSmoothMidi(
  midi: readonly (number | null)[],
  window = 5,
): (number | null)[] {
  const half = Math.floor(window / 2)
  const out: (number | null)[] = new Array(midi.length)
  for (let i = 0; i < midi.length; i++) {
    const vals: number[] = []
    for (let j = Math.max(0, i - half); j <= Math.min(midi.length - 1, i + half); j++) {
      const v = midi[j]
      if (v !== null && v !== undefined) vals.push(v)
    }
    out[i] = vals.length ? vals.slice().sort((a, b) => a - b)[Math.floor(vals.length / 2)]! : null
  }
  return out
}

/**
 * 滞回量化：连续 MIDI 值 → 稳定音号。
 *
 * 迟滞的意义：值在 60.4 与 60.6 之间抖动时，普通取整会在 60/61 之间
 * 闪。滞回要求「新音号要连续 N 帧都超过阈值才换」。
 */
export function hysteresisQuantize(
  midi: readonly (number | null)[],
  hysteresisFrames = 4,
): (number | null)[] {
  const out: (number | null)[] = new Array(midi.length)
  let current: number | null = null
  let pending: number | null = null
  let pendingCount = 0
  for (let i = 0; i < midi.length; i++) {
    const v = midi[i]
    if (v === null || v === undefined) {
      out[i] = current
      continue
    }
    const rounded = Math.round(v)
    if (current === null) {
      current = rounded
      out[i] = current
      continue
    }
    if (rounded === current) {
      pending = null
      pendingCount = 0
      out[i] = current
      continue
    }
    // 迟回：新音号连续 hysteresisFrames 帧成立才换
    if (pending === rounded) pendingCount++
    else {
      pending = rounded
      pendingCount = 1
    }
    if (pendingCount >= hysteresisFrames) {
      current = pending
      pending = null
      pendingCount = 0
    }
    out[i] = current
  }
  return out
}

/** 旋律段切分（量化音号连续相同的帧归一段）。 */
export function segmentMelody(q: readonly (number | null)[]): MelodySegment[] {
  const segs: MelodySegment[] = []
  let i = 0
  while (i < q.length) {
    const key = q[i] ?? null
    let j = i + 1
    while (j < q.length && (q[j] ?? null) === key) j++
    segs.push({
      startFrame: i,
      endFrame: j,
      midi: key,
      freq: key === null ? null : midiToFreq(key),
    })
    i = j
  }
  return segs.filter((s) => s.midi !== null && s.endFrame - s.startFrame >= 2)
}

/** 探针用的 RMS 便捷封装（对齐层也用得上）。 */
export function envelopeOf(mono: Mono, hopSec = 0.05): Float64Array {
  return rmsEnvelope(mono, hopSec, hopSec)
}

// ============================================================
//  CLI：feuille music align
// ============================================================

/**
 * `feuille music align <recording> [--score <midi>] [--out <dir>] [--name <n>]`
 *
 * 有 `--score` → Tier A（谱面真值对拍）：按谱块顺序把谱面与录音对齐，
 * 每对配对都过「落带内 + 音级交集 ≥ 2/3」两条判据；任一条不过就记为
 * 不成立（fail-closed，不硬凑）。
 * 无 `--score` → Tier B（录音实测）：泛音和声评分 f0 → 旋律线。
 *
 * 产出：`<out>/<name>-align.json`（配对与判定）+ 终端摘要。
 */
export async function main(argv: string[]): Promise<number> {
  const args = parseArgs(argv)
  const src = args.positional[0]
  if (!src) {
    console.error('usage: feuille music align <recording> [--score <midi>] [--out <dir>] '
      + '[--name <n>] [--hop 0.05] [--experimental]')
    return 2
  }
  const outDir = strOpt(args, 'out', 'notes')
  const name = strOpt(args, 'name', src.replace(/^.*[/\\]/, '').replace(/\.[^.]+$/, ''))
  const scorePath = args.opts['score']
  const hop = numOpt(args, 'hop', 0.05)

  mkdirSync(outDir, { recursive: true })
  const payload = withDecoded(src, (mono) => {
    const observed = observedChords(mono, { hopSec: hop })
    if (!scorePath) {
      const mel = melodyF0(mono, { hopSec: hop })
      return {
        tier: 'B' as const,
        source: src,
        hopSec: hop,
        observedSegments: observed.segments.length,
        melodySegments: mel.segments.length,
        melody: mel.segments.map((s) => ({
          start_s: s.startFrame * hop,
          end_s: s.endFrame * hop,
          midi: s.midi,
          freq: s.freq,
        })),
        // 和弦段也落盘：状态帧要画「实测和弦铺底」，光有一个段数画不出来。
        // **这是实测的模板分类结果，不是谱面真值**——画面上必须照实标。
        chords: observed.segments.map((s) => ({
          start_s: s.start * hop,
          end_s: s.end * hop,
          label: s.label,
          score: Number(s.score.toFixed(3)),
        })),
        pairs: [] as PairVerdict[],
        allOk: true,
      }
    }
    const midi = parseMidi(readFileSync(scorePath))
    const blocks = scoreBlocks(midi)
    // 观测段数决定分层数：两侧都切同样多的层，才能逐层直对（判据 3）。
    // 段数在 alignBlocks 内部才过滤（只留有标签的），这里先用同样的口径数一遍。
    const nLayers = observed.segments.filter((s) => s.label).length
    const layers = timeLayers(midi, nLayers)
    const result = alignBlocks(blocks, observed, { hopSec: hop, scoreLayers: layers })
    return {
      tier: 'A' as const,
      source: src,
      score: scorePath,
      hopSec: hop,
      scoreBlocks: blocks.length,
      observedSegments: observed.segments.length,
      pairs: result.pairs,
      allOk: result.allOk,
      offsetSec: result.offsetSec,
      scale: result.scale,
      medianResidualSec: result.medianResidualSec,
      medianLocalRatio: result.medianLocalRatio,
      discrimination: result.discrimination,
      validated: result.validated,
      validationNote: result.validationNote,
    }
  })

  const outPath = join(outDir, `${name}-align.json`)
  writeFileSync(outPath, JSON.stringify(payload, null, 1), 'utf8')
  if (payload.tier === 'A') {
    const ok = payload.pairs.filter((p) => p.ok).length
    console.log(`align (Tier A): ${src} × ${payload.score}`)
    console.log(`  谱块 ${payload.scoreBlocks} · 观测段 ${payload.observedSegments} · `
      + `判定通过 ${ok}/${payload.pairs.length}`)
    console.log(`  速度拟合 t_obs ≈ ${payload.scale.toFixed(3)}·t_score `
      + `${payload.offsetSec >= 0 ? '+' : '−'} ${Math.abs(payload.offsetSec).toFixed(2)}s · `
      + `残差中位数 ${payload.medianResidualSec.toFixed(2)}s`)
    console.log(`  局部速度比中位数 ${payload.medianLocalRatio.toFixed(2)}（录音秒/谱面秒，判据 2 的基准）`)
    console.log(`  → ${outPath}`)
    const d = payload.discrimination
    console.log(`  辨别力：路径交集 ${d.pathMean.toFixed(3)} vs 零分布 `
      + `${d.nullMean.toFixed(3)}±${d.nullSd.toFixed(3)} · p=${d.pValue.toFixed(4)} `
      + `（${d.permutations} 次置换，门限 ${ALIGN_P_VALUE}）`)

    if (!payload.validated) {
      // 默认 fail-closed：这条路径**没有**被验证过，不许拿来落摘录时间码。
      console.error(`  未验证：${payload.validationNote}`)
      if (!args.flags.has('experimental')) return 1
      console.error('  （--experimental：只输出研究用的路径，结果不许进成片。）')
    }
    if (!payload.allOk) {
      console.log(`  逐对判据 ${ok}/${payload.pairs.length} 通过（必要条件，非证据）——`
        + '未过的配对按 unverified 记，摘录时间码以 notes/probe 的起音为准，不按谱面推。')
    }
  } else {
    console.log(`align (Tier B · 录音实测): ${src}`)
    console.log(`  观测段 ${payload.observedSegments} · 旋律段 ${payload.melodySegments}`)
    console.log(`  → ${outPath}`)
  }
  return 0
}
