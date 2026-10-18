// timeline.ts — 行时间轴与词级进度轴（timeline.py 的 TS 移植；⑤ 补齐 + ⑥ 渲染共用）。
//
// karaokePoints / fracAt 是「词级时间戳一轴多用」里的渲染轴：换台词
// 自动重对齐，不需要新数据。
//
// 口径（与已验收的成片一致）：
//
//     start[0]     = 0
//     start[i]     = start[i-1] + speech_dur[i-1] + line_gap
//     tail_silence = file_dur - speech_dur        // edge-tts 垫的尾静音，行距吸收它
//
// `speech_dur` 取词级时间戳的行时长（tts.effectiveDur），`file_dur` 由
// ffprobe 实测 mp3——**一律实测，不用清单里手抄的值**。调用方持有
// synthCached 返回的实测时长时可经 `durs` 传入（命中零探测的性能修复，
// 设计内置而非后补）；缺省仍逐行实测，Python 口径不变。
import { join } from "node:path"

import { probeDuration } from "./audio.js"
import { roundHalfEven } from "./num.js"
import type { Word } from "./tts/pure.js"

export interface KaraokeWord {
  /** 词面 */
  w: string
  /** 词首秒（**绝对**时间戳） */
  s: number
  /** 词尾秒 */
  e: number
}

export interface TimelineLine {
  /** 缓存文件名（mp3 路径 = audioDir/{key}.mp3） */
  key: string
  /** 词级真值行时长（tts.effectiveDur） */
  dur: number
  /** 词表（enrich 只透传；karaokePoints 需绝对时间戳的 s/e 形态） */
  words?: (Word | KaraokeWord)[]
  speechDur?: number
  fileDur?: number
  tailSilence?: number
  start?: number
}

/** 纯函数：行起始秒累进。start[0]=0，其后 = 前一起点 + 前一行语音长 + 行距。 */
export function computeStarts(speechDurs: readonly number[], gap: number): number[] {
  const starts: number[] = []
  let t = 0.0
  for (const d of speechDurs) {
    starts.push(roundHalfEven(t, 3))
    t = t + d + gap
  }
  return starts
}

/** 就地补齐每行的 speechDur / fileDur / tailSilence / start，返回 [total, span]。
 *
 * `durs`：可选的实测时长表（key → 秒）。传入时不再 ffprobe——synthCached
 * 已经探过的时长直接复用（全缓存命中时零探测）。
 */
export function enrichLines(
  lines: TimelineLine[],
  gap: number,
  audioDir: string,
  durs?: ReadonlyMap<string, number>,
): [number, number] {
  const speechDurs = lines.map((ln) => roundHalfEven(Number(ln.dur), 3))
  const starts = computeStarts(speechDurs, gap)
  lines.forEach((ln, i) => {
    const pre = durs?.get(ln.key)
    const raw = pre !== undefined ? pre : probeDuration(join(audioDir, `${ln.key}.mp3`))
    const fileDur = roundHalfEven(raw, 3)
    ln.speechDur = speechDurs[i]!
    ln.fileDur = fileDur
    ln.tailSilence = roundHalfEven(fileDur - speechDurs[i]!, 3)
    ln.start = starts[i]!
  })
  const sum = speechDurs.reduce((a, b) => a + b, 0)
  const total = roundHalfEven(sum, 3)
  const span = roundHalfEven(sum + gap * Math.max(0, lines.length - 1), 3)
  return [total, span]
}

// ---------------------------------------------------------------- 词级进度轴

/** 一行台词的 [t, frac] 词首/词尾字符进度点。
 *
 * 词级时间戳一轴多用（口型开合 / 逐词高亮 / 手势触发）里卡拉OK那轴的唯一实现。
 * line 需带 `words`（**绝对**时间戳：每词 s/e 秒）、`start`、`dur`——
 * 相对词表（tts 输出的 t/d）要先加 start 转成绝对时间。
 */
export function karaokePoints(line: {
  start: number
  dur: number
  words: KaraokeWord[]
}): Array<[number, number]> {
  const words = line.words
  // 字符进度按码点数（Python len()）——UTF-16 的 .length 会把增补平面字符算两码元
  const total =
    words.reduce((n, w) => n + [...w.w].length, 0) + Math.max(0, words.length - 1)
  const pts: Array<[number, number]> = [[line.start, 0.0]]
  let c = 0.0
  words.forEach((w, i) => {
    c += [...w.w].length
    pts.push([Math.max(w.s, line.start), c / total])
    c += i < words.length - 1 ? 1 : 0
    pts.push([w.e, c / total])
  })
  pts.push([line.start + line.dur + 0.15, 1.0])
  return pts
}

/** 在进度点上线性插值取 t 时刻的字符进度 [0,1]。区间外夹到 0 / 1。 */
export function fracAt(pts: Array<[number, number]>, t: number): number {
  if (t <= pts[0]![0]) return 0.0
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i]![0]) {
      const [t0, f0] = pts[i - 1]!
      const [t1, f1] = pts[i]!
      if (t1 <= t0) return f1
      return f0 + ((f1 - f0) * (t - t0)) / (t1 - t0)
    }
  }
  return 1.0
}
