// tts_windows.ts — 按窗口表逐窗合成中文旁白，实测时长，出 voice-report.json。
//
// 契约（对齐 match-recap-video skill）：
//   输入 windows.json：{"windows":[{key,t0,t1,anchor?,align?,say,...}]}
//   产物 <out-dir>/voice/<key>.mp3 + <out-dir>/voice-report.json
//        = {"segments":[{"key","file","duration"}]}   ← place_voice.py 认这个形状
//
// 为什么走 TS：仓库自带的 edge-tts 客户端（DRM v2 令牌 + 时钟偏斜修正 + 连接重试）
// 在 packages/core/src/tts；Python 的 edge-tts 7.2.8 在本机会 403。
//
// 实测口径（2026-11-08，zh-CN-YunjianNeural，rate -5%，四场欧冠/欧联 51 段）：
//   0.24–0.40 s/字，中位数 ≈ 0.33 s/字——写稿预算按 0.30–0.33 起，别按 0.20。
//   check_budget.py 会对 voice-report 做「同代检测」：改完窗口表不重跑 TTS，
//   旧实测时长会污染判据（超带宽即整份作废退回估算）。
//
// ⚠️ 本报告的「余量」按 t1−t0−时长 算，**不是落点预算**——落点预算是
//    t1−anchor−LEAD（place_voice.py 的公式），以 place_voice 的判决为准。
//    窗口紧时（实测超 anchor+LEAD 预算零点几秒）压一个字 ≈ 0.3s 就够。
//
// 退出码：0 = 全部段都在窗口内；1 = 有段超窗（要压词或拆窗，不许挪落点）；2 = 输入坏了。
// selftest：node --import tsx tts_windows.ts selftest   （离线：区间解析 + 输入契约）
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { join, resolve } from "node:path"

import { synthCached } from "../../../packages/core/src/tts/synth.js"

interface Win {
  key?: string
  t0?: number
  t1?: number
  src?: string
  anchor?: number
  align?: string
  say?: string
}

function arg(flag: string, fallback?: string): string | undefined {
  const i = process.argv.indexOf(flag)
  if (i >= 0 && process.argv[i + 1]) return process.argv[i + 1]
  return fallback
}

export function interval(w: Win): [number, number] | null {
  if (typeof w.t0 === "number" && typeof w.t1 === "number") return [w.t0, w.t1]
  if (typeof w.src === "string") {
    const m = w.src.match(/([\d.]+)\s*-\s*([\d.]+)/)
    if (m) return [Number(m[1]), Number(m[2])]
  }
  return null
}

export function parseWindows(doc: { windows?: Win[] } | Win[]): Win[] {
  return Array.isArray(doc) ? doc : (doc.windows ?? [])
}

function selftest(): number {
  let ok = true
  const check = (name: string, got: boolean) => {
    if (!got) ok = false
    console.log(`  [${got ? "PASS" : "FAIL"}] ${name}`)
  }
  check("interval 认 t0/t1", JSON.stringify(interval({ t0: 0, t1: 8.08 })) === "[0,8.08]")
  check("interval 认 src 紧凑写法", JSON.stringify(interval({ src: "9.48-20.0" })) === "[9.48,20]")
  check("interval 缺区间返回 null", interval({ key: "w01" }) === null)
  check("parseWindows 认 {windows:[…]}",
    parseWindows({ windows: [{ key: "w01" }] }).length === 1)
  check("parseWindows 认裸数组", parseWindows([{ key: "w01" }]).length === 1)
  check("空表拒收", parseWindows({ windows: [] }).length === 0)
  console.log(`selftest：${ok ? "全部通过" : "有用例失败"}`)
  return ok ? 0 : 1
}

async function main(): Promise<number> {
  if (process.argv[2] === "selftest") return selftest()
  const winPath = arg("--windows")
  const outDir = arg("--out-dir")
  if (!winPath || !outDir) {
    console.error("用法: node --import tsx tts_windows.ts --windows <windows.json> --out-dir <dir> [--voice zh-CN-YunjianNeural] [--rate -5%] ｜ selftest")
    return 2
  }
  const voice = arg("--voice", "zh-CN-YunjianNeural") as string
  const rate = arg("--rate", "-5%") as string
  const doc = JSON.parse(readFileSync(winPath, "utf8")) as { windows?: Win[] } | Win[]
  const windows: Win[] = parseWindows(doc)
  if (!windows.length) {
    console.error("窗口表为空")
    return 2
  }
  const voiceDir = join(resolve(outDir), "voice")
  const cacheDir = join(resolve(outDir), "voice-cache")
  mkdirSync(voiceDir, { recursive: true })
  mkdirSync(cacheDir, { recursive: true })

  const segments: { key: string; file: string; duration: number }[] = []
  let over = 0
  console.log(`${"key".padEnd(8)}${"实测".padStart(7)}${"窗口".padStart(12)}${"余量".padStart(8)}  旁白`)
  for (const w of windows) {
    const key = String(w.key ?? "")
    const text = String(w.say ?? "").trim()
    const iv = interval(w)
    if (!key) {
      console.error("有窗口缺 key")
      return 2
    }
    if (!text) continue // 无旁白的窗（纯卡片）不进音频轨
    if (!iv) {
      console.error(`${key}: 缺 t0/t1`)
      return 2
    }
    const [t0, t1] = iv
    const hit = await synthCached(text, voice, rate, "+0Hz", cacheDir)
    const dest = join(voiceDir, `${key}.mp3`)
    copyFileSync(hit.mp3, dest)
    const dur = hit.duration
    // 报告余量按窗长算（见文件头：落点预算以 place_voice 为准）
    const slack = t1 - t0 - dur
    if (slack < 0) over += 1
    segments.push({ key, file: `voice/${key}.mp3`, duration: Number(dur.toFixed(3)) })
    console.log(
      `${key.padEnd(8)}${dur.toFixed(2).padStart(7)}${`${t0.toFixed(1)}-${t1.toFixed(1)}`.padStart(12)}` +
        `${slack.toFixed(2).padStart(8)}${slack < 0 ? "  ❌超窗" : ""}  ${text.slice(0, 34)}`,
    )
  }
  writeFileSync(
    join(resolve(outDir), "voice-report.json"),
    JSON.stringify({ segments }, null, 1),
    "utf8",
  )
  console.log(`\n段数 ${segments.length}｜超窗 ${over}｜音色 ${voice}｜语速 ${rate}`)
  return over ? 1 : 0
}

main().then((code) => process.exit(code)).catch((e) => {
  console.error(e)
  process.exit(2)
})
