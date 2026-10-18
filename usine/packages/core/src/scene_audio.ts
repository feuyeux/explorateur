// scene_audio.ts — 场景课 TTS 叶子（④成片·语音线第一段；scene_audio.py 的 TS 移植）
//
// `feuille scene tts --scene <id>`：
//
//     lessons/<id>/scene.json（先 parse）
//       └─ 每语种逐台词行：班底 persona 声线（§0.4 roles 声明驱动选角，
//          mood 增量查 scene 级 moodVoices，缺省 ±0 不猜）
//       └─ tts.synthCached（内容寻址缓存，改台词只重合成那行）
//       └─ timeline.enrichLines（gap=0.35s，词级真值裁尾；durs 传入实测时长，
//          全缓存命中零探测——P3 的性能修复在这里传导）
//       └─ build/scene/audio/scene-<sid>_<lc>.timeline.json（doctor ④ 查的产物）
//          + 逐行 mp3（line-<i>.mp3，compose 线直接消费）
//
// 台账：ledger kind="scene-audio"、unit=<sid>/<lc>、extra=(sid, scene.md sha16,
// gap)——scene.md 变 → 指纹变 → 该语种重做；statusOf 按**条目里记录的那份**
// extra 复算（账本自描述，调用方漏传不会永久误红）。
//
// 声线映射（与 scene_schema §8 选角可解同一条链）：**§0.4 roles 声明驱动**——
// 按 energy 在该语种班底里唯一解人。roles 是每课自己的声明，不是固定 A=活泼。
// mood 增量表**缺省空**：MOOD_FACE 只定义表情几何不定义声线——谁要把情绪接进
// 声线，必须显式给表（scene 级 moodVoices），本模块不发明默认值。
//
// 序列化口径：timeline.json 落盘用 **Python 侧同款 snake_case 键序**
// （i→…→dur→speech_dur→file_dur→tail_silence→start；顶层 locale→lines→gap→
// totalDur→spanDur），经 parse_scene.pyJsonDump 写出——doctor ④ 与 compose 线
// 消费的是落盘形态；内存口径 = TS camelCase（timeline.ts 的 TimelineLine），
// 两态之间 toPyTimeline 显式转换。
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { createHash } from "node:crypto"
import { basename, dirname, join, relative, resolve } from "node:path"

import { LESSONS_DIR, personas, sceneDoc } from "./data.js"
import { FeuilleError } from "./errors.js"
import * as ledger from "./ledger.js"
import { pyJsonDump, scenePaths } from "./parse_scene.js"
import { probeDuration } from "./audio.js"
import { enrichLines, type TimelineLine } from "./timeline.js"
import { effectiveDur, synthCached, voiceParams, type Word } from "./tts/index.js"

type Json = any

// 行距（秒）：与 verify_timeline 的缺省口径一致（gap=0.35）。
export const LINE_GAP = 0.35

// 产物线注册：指纹只由「确实可能影响该产物」的东西构成——TTS 内核 + 时间轴 +
// 音频探测 + 班底数据（voiceId/rate/pitch 都在 personas.json 里）+ 全部 scene.md
// （@glob，不用索引文件当第二事实源）。工具链由 ledger.fingerprint 自动并入。
export const REGISTER_KIND = "scene-audio"

export function registerSceneAudioLine(): void {
  ledger.registerLine(
    REGISTER_KIND,
    // Python 侧 ("tts.py", "timeline.py", "audio.py") 的对应物：tts.py 拆成的
    // 五个 TS 文件全部入指纹（client/drm 影响合成输出，同样可能改动产物）。
    ["tts/synth.ts", "tts/pure.ts", "tts/client.ts", "tts/drm.ts", "tts/split.ts", "timeline.ts", "audio.ts"],
    ["@lessons/*/scene.md", "personas/personas.json"],
  )
}

/** 项目根 = lessons 目录上推一层（与 lesson doctor 同一条约定）。 */
export function sceneRoot(lessonsDir?: string): string {
  return lessonsDir ? dirname(resolve(lessonsDir)) : dirname(LESSONS_DIR)
}

/** 班底选角：§0.4 roles 声明驱动（role → energy → 该语种班底里唯一的人）。
 *
 * 每个角色都必须恰好解出一个人，取不到就显式报错，绝不静默回落。
 */
export function pickCast(people: Json[], roles: Record<string, string>, locale: string): Record<string, Json> {
  const by: Record<string, Json> = {}
  for (const [role, energy] of Object.entries(roles)) {
    const cands = people.filter((p) => p["energy"] === energy)
    if (cands.length !== 1) {
      throw new FeuilleError(
        `${locale}: ${role} 角按 energy='${energy}' 在班底解出 ${cands.length} 人`
        + "（应为恰 1；先跑 scene validate 对齐 §0.4/§0.6）")
    }
    by[role] = cands[0]!
  }
  return by
}

/** 情绪声线增量：(rate, pitch)。表里没有该 mood = ±0（不猜）。
 *
 * moodVoices 形状（scene.md §0 可选声明 / scene.json 透传）：
 *   {"happy": {"rate": 4, "pitch": 2}, "encouraging": {"rate": -2}}
 */
export function moodOffset(mood: string, moodVoices: Json): [number, number] {
  const m = moodVoices[mood] || {}
  return [Math.trunc(Number(m["rate"] ?? 0)), Math.trunc(Number(m["pitch"] ?? 0))]
}

/** 词级真值行时长：probeDuration 必须用**实测文件时长**，不能用 1e9 哨兵——
 * words 空/伪词的行 effectiveDur 会原样返回 probe 值，哨兵直灌 enrichLines
 * 后 starts/totalDur/tailSilence 全线炸（tail_silence ≈ -1e9 秒）。 */
export function effectiveDurOf(words: Word[], text: string, mp3: string): number {
  return effectiveDur(words, probeDuration(mp3), text)
}

/** 单语种台词行（enrich 就地补齐 camelCase 字段；落盘经 toPyTimeline 转键序）。 */
export interface SceneLine extends TimelineLine {
  i: number
  speaker: string
  mood: string
  text: string
}

export interface LocaleTimeline {
  locale: string
  lines: SceneLine[]
  gap: number
  totalDur: number
  spanDur: number
}

/** 单语种：逐行合成 → enrichLines → timeline（不落盘，便于测试）。 */
export async function buildLocaleTimeline(
  doc: Json, lc: string, cacheDir: string, gap: number = LINE_GAP,
): Promise<LocaleTimeline> {
  const loc = doc["locales"][lc]
  const dialogue = loc["dialogue"]
  if (!dialogue?.length) {
    throw new FeuilleError(`${lc}: 该语种无台词（polyglot 形态请走共享剧本线）`)
  }

  const people = Object.values(personas()).filter((p) => p["locale"] === lc)
  const roles = doc["roles"] || {}
  if (!Object.keys(roles).length) {
    throw new FeuilleError(`${lc}: scene.json 缺 §0.4 roles 声明（先跑 scene validate）`)
  }
  const bySpeaker = pickCast(people, roles, lc)
  // 情绪增量：scene.json §0 声明了才有；没声明 = ±0（不发明默认值）
  const moodVoices = doc["moodVoices"] || {}

  const lines: SceneLine[] = []
  const durs = new Map<string, number>()   // synthCached 已探的实测时长 → 命中零探测
  for (const ln of dialogue) {
    if (!(ln["speaker"] in bySpeaker)) {
      throw new FeuilleError(
        `${lc} #${ln["i"]}: 说话人 '${ln["speaker"]}' 不在 §0.4 roles `
        + `[${Object.keys(bySpeaker).sort().map((k) => `'${k}'`).join(", ")}] 里（先跑 scene validate）`)
    }
    const p = bySpeaker[ln["speaker"]]!
    const v = p["voice"]
    const [rOff, pOff] = moodOffset(ln["mood"], moodVoices)
    const [rate, pitch] = voiceParams(v["rate"], v["pitch"], rOff, pOff)
    // persona 声线带符号（"+6%"），voiceParams 已统一夹取安全域；
    // 缓存键含 rate/pitch 串——同一 persona 同一文本不同情绪增量自然分键。
    const got = await synthCached(ln["text"], v["voiceId"], rate, pitch, cacheDir)
    durs.set(got.key, got.duration)
    const line: SceneLine = {
      i: ln["i"], speaker: ln["speaker"], mood: ln["mood"], text: ln["text"],
      key: got.key, words: got.words,
      dur: 0,   // 词级真值，下一行填
    }
    line.dur = effectiveDurOf(got.words, ln["text"], join(cacheDir, `${got.key}.mp3`))
    lines.push(line)
  }

  const [total, span] = enrichLines(lines, gap, cacheDir, durs)
  return { locale: lc, lines, gap, totalDur: total, spanDur: span }
}

/** 落盘形态：Python scene_audio 写盘的键序与命名（snake_case 补齐字段）——
 * doctor ④ 与 compose 线消费的是这份形态，与迁移期 Python 产物互读。 */
function toPyTimeline(tl: LocaleTimeline): Record<string, unknown> {
  return {
    locale: tl.locale,
    lines: tl.lines.map((ln) => ({
      i: ln.i, speaker: ln.speaker, mood: ln.mood, text: ln.text,
      key: ln.key, words: ln.words, dur: ln.dur,
      speech_dur: ln.speechDur, file_dur: ln.fileDur,
      tail_silence: ln.tailSilence, start: ln.start,
    })),
    gap: tl.gap, totalDur: tl.totalDur, spanDur: tl.spanDur,
  }
}

/** timeline 产物名：doctor ④ 的探针与这里的落盘同一条格式串（lesson.ts 复用）。 */
export function timelineName(sid: string, lc: string): string {
  return `scene-${sid}_${lc}.timeline.json`
}

export function sceneMdSha16(lessonsDir: string | undefined, sid: string): string {
  const [mdP] = scenePaths(sid, lessonsDir)
  const h = createHash("sha256")
  h.update(readFileSync(mdP))
  return h.digest("hex").slice(0, 16)
}

/** 单课全语种 TTS：逐语种跑 buildLocaleTimeline，落 timeline.json + 台账。 */
export async function runScene(
  lessonsDir: string | undefined, sid: string,
  opts: { gap?: number; force?: boolean } = {},
): Promise<number> {
  const gap = opts.gap ?? LINE_GAP
  const force = opts.force ?? false
  registerSceneAudioLine()
  const doc = sceneDoc(sid, lessonsDir)
  const root = sceneRoot(lessonsDir)
  const outDir = join(root, "build", "scene", "audio")
  mkdirSync(outDir, { recursive: true })
  const sha = sceneMdSha16(lessonsDir, sid)
  const extra = [sid, sha, String(gap)]

  let okAll = true
  for (const lc of Object.keys(doc["locales"])) {
    const unit = `${sid}/${lc}`
    const tlPath = join(outDir, timelineName(sid, lc))
    const artifacts = [relative(root, tlPath)]
    const [fresh, why] = ledger.statusOf(root, REGISTER_KIND, unit, artifacts)
    if (fresh && !force) {
      console.log(`  [SKIP] ${lc}：${why}`)
      continue
    }
    const tl = await buildLocaleTimeline(doc, lc, outDir, gap)
    // 逐行 mp3 落到产物目录（compose 线直接消费）；缓存命中时 mp3 已在缓存位，
    // 这里做产物位副本（指纹保护的是产物，不是缓存）。缺源即报错：静默跳过会让
    // 上一次构建的旧 line-XX.mp3 原地存活，compose 线消费到错配音频而台账全绿。
    for (const ln of tl.lines) {
      const src = join(outDir, `${ln.key}.mp3`)
      if (!existsSync(src)) {
        throw new FeuilleError(`${lc}: 行 ${ln.i} 的缓存音源缺失：${basename(src)}`)
      }
      copyFileSync(src, join(outDir, `line-${String(ln.i).padStart(2, "0")}.mp3`))
    }
    writeFileSync(tlPath, pyJsonDump(toPyTimeline(tl)), "utf8")
    ledger.record(root, REGISTER_KIND, unit, artifacts, extra)
    const n = tl.lines.length
    console.log(`  [OK] ${lc}: ${n} 行 · speech ${tl.totalDur.toFixed(1)}s · `
      + `span ${tl.spanDur.toFixed(1)}s → ${basename(tlPath)}`)
    okAll = okAll && n > 0
  }
  return okAll ? 0 : 1
}

// ---------------------------------------------------------------- CLI

/** argparse 同款取值：`--k v` 与 `--k=v` 两种写法都收。 */
function argValue(argv: string[], flag: string): string | undefined {
  const i = argv.indexOf(flag)
  if (i >= 0) return argv[i + 1]
  const p = `${flag}=`
  const j = argv.findIndex((a) => a.startsWith(p))
  return j >= 0 ? argv[j]!.slice(p.length) : undefined
}

/** `feuille scene tts --scene <id> [--lessons DIR] [--gap S] [--force]`。 */
export async function mainTts(argv: string[] = []): Promise<number> {
  const sceneId = argValue(argv, "--scene")
  if (sceneId === undefined) {
    console.error("usage: feuille scene tts --scene <id> [--lessons DIR] [--gap S] [--force]")
    return 2
  }
  const lessonsDir = argValue(argv, "--lessons")
  const gap = argValue(argv, "--gap") !== undefined ? Number(argValue(argv, "--gap")) : LINE_GAP
  const force = argv.includes("--force")
  try {
    return await runScene(lessonsDir, sceneId, { gap, force })
  } catch (e) {
    if (e instanceof FeuilleError) {
      console.error(String(e))
      return 1
    }
    throw e
  }
}
