// synth.ts — 内容寻址缓存合成（tts.py synth_cached 的 TS 移植 + 性能修复内置）。
//
// 缓存三件套：
// - `{key}.mp3`  合成音频
// - `{key}.json` 词表（**纯数组**形态，与 Python 迁移期缓存互读）
// - `{key}.dur`  实测时长边车——HIT 直接读它，**命中零 ffprobe**（本迁移的
//   设计内置性能修复；边车缺失时探测一次并补写，下个进程起零探测）。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { join } from "node:path"

import { probeDuration } from "../audio.js"
import { synthLine, RETRY_TRIES } from "./client.js"
import { contentHash, type Word } from "./pure.js"

export interface SynthHit {
  key: string
  /** 缓存音频路径 */
  mp3: string
  words: Word[]
  state: "HIT" | "NEW"
  /** 实测时长秒（HIT 读 {key}.dur 边车；NEW 探测后写边车） */
  duration: number
}

/** 词表 meta：老形态 {words:[…]} 与纯数组形态都认（迁移期直读 Python 缓存）。 */
function readMeta(metaP: string): Word[] {
  const parsed: unknown = JSON.parse(readFileSync(metaP, "utf8"))
  if (Array.isArray(parsed)) return parsed as Word[]
  const obj = parsed as { words?: Word[] }
  if (obj !== null && typeof obj === "object" && Array.isArray(obj.words)) return obj.words
  throw new Error(`缓存词表形态不认识：${metaP}`)
}

function readDuration(durP: string, mp3P: string): number {
  if (existsSync(durP)) return Number.parseFloat(readFileSync(durP, "utf8").trim())
  const d = probeDuration(mp3P)
  writeFileSync(durP, String(d)) // 补写边车：此后命中零探测
  return d
}

/** 内容寻址缓存合成：命中（mp3+json 都在）直接复用；miss 才请求。
 * state 供台账打印「N新/N命中」。 */
export async function synthCached(
  text: string,
  voice: string,
  rate: string,
  pitch: string,
  cacheDir: string,
  tries: number = RETRY_TRIES,
): Promise<SynthHit> {
  mkdirSync(cacheDir, { recursive: true })
  const key = contentHash(voice, rate, pitch, text)
  const mp3P = join(cacheDir, `${key}.mp3`)
  const metaP = join(cacheDir, `${key}.json`)
  const durP = join(cacheDir, `${key}.dur`)
  if (existsSync(mp3P) && existsSync(metaP)) {
    return { key, mp3: mp3P, words: readMeta(metaP), state: "HIT", duration: readDuration(durP, mp3P) }
  }
  const { mp3, words } = await synthLine({ text, voice, rate, pitch }, tries)
  writeFileSync(mp3P, mp3)
  const duration = probeDuration(mp3P)
  writeFileSync(durP, String(duration))
  writeFileSync(metaP, JSON.stringify(words, null, 1))
  return { key, mp3: mp3P, words, state: "NEW", duration }
}
