// measure_narration.mjs — 成片前的两个前置量（每期都要量，不能抄上一期的数）：
//   1) 时间线总长（与 packages/karaoke/src/build_video.ts 的 d30 网格同款）
//   2) 旁白实测电平（真实语音窗：tokens[0].start → 末 token end，不量整条）
// 口径见 skills/bgm-bed/references/lyria-field-notes.md §6。
//
// 跑法：node measure_narration.mjs <project-dir>
// 输出 JSON 到 stdout（runner 直接消费），人看的话再跑一次带 --pretty。
import { execFileSync, spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const P = process.argv[2]
if (!P) { console.error('usage: node measure_narration.mjs <project-dir>'); process.exit(2) }

const FPS = 30
const d30 = (d) => Math.ceil(d * FPS - 1e-9) / FPS

const cfg = JSON.parse(readFileSync(join(P, 'video.json'), 'utf8'))
const locales = cfg.locales
const PREROLL = cfg.preroll, TAIL = cfg.tail, DONE = cfg.done, INTRO = cfg.intro, OUTRO = cfg.outro

function probeDuration(file) {
  const out = execFileSync('ffprobe', [
    '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=noprint_wrappers=1:nokey=1', file,
  ], { encoding: 'utf8' })
  return parseFloat(out.trim())
}

function meanVolumeDb(file, start, dur) {
  // volumedetect 的结果打在 stderr（level=info），stdout 只有 null muxer 的空流
  const r = spawnSync('ffmpeg', [
    '-hide_banner', '-nostats', '-i', file,
    '-ss', start.toFixed(3), '-t', dur.toFixed(3),
    '-af', 'volumedetect', '-f', 'null', '-',
  ], { encoding: 'utf8' })
  const m = /mean_volume:\s*(-?[\d.]+) dB/.exec(r.stderr ?? '')
  if (!m) throw new Error(`no mean_volume for ${file}\n${(r.stderr ?? '').slice(-600)}`)
  return parseFloat(m[1])
}

const rows = []
let totalScene = 0
for (const loc of locales) {
  const j = JSON.parse(readFileSync(join(P, 'tts', `${loc}.json`), 'utf8'))
  const toks = j.tokens
  const mp3 = join(P, 'tts', `${loc}.mp3`)
  const adur = probeDuration(mp3)
  const k = toks.length
  let scene = d30(PREROLL)
  for (let s = 0; s < k; s++) {
    const d = s < k - 1 ? toks[s + 1].start - toks[s].start : adur - toks[s].start + TAIL
    scene += d30(d)
  }
  scene += d30(DONE)
  totalScene += scene

  const wStart = toks[0].start
  const wEnd = toks[k - 1].end
  const wDur = Math.max(0.05, wEnd - wStart)
  rows.push({ loc, k, adur, scene, wStart, wEnd, rms: meanVolumeDb(mp3, wStart, wDur) })
}

// 拼接后的等效 RMS（按窗长加权的功率平均，不是算术平均）
let pSum = 0, nSum = 0
for (const r of rows) {
  const w = r.wEnd - r.wStart
  pSum += w * Math.pow(10, r.rms / 10)
  nSum += w
}
const eqRms = 10 * Math.log10(pSum / nSum)
const loudest = rows.reduce((a, b) => (b.rms > a.rms ? b : a))
const quietest = rows.reduce((a, b) => (b.rms < a.rms ? b : a))
const total = d30(INTRO) + totalScene + d30(OUTRO)

const out = {
  scenes: rows.map((r) => ({ loc: r.loc, tokens: r.k, mp3_s: +r.adur.toFixed(3), rms_dbfs: r.rms, scene_s: +r.scene.toFixed(3) })),
  narration_rms_dbfs: +eqRms.toFixed(2),
  loudest: { loc: loudest.loc, rms_dbfs: loudest.rms },
  quietest: { loc: quietest.loc, rms_dbfs: quietest.rms },
  spread_db: +(loudest.rms - quietest.rms).toFixed(1),
  scene_sum_s: +totalScene.toFixed(2),
  video_total_s: +total.toFixed(2),
  bed_target_s: +total.toFixed(1),
}

if (process.argv.includes('--pretty')) {
  for (const r of out.scenes) {
    console.log(`${r.loc.padEnd(6)} tok=${String(r.tokens).padStart(2)}  mp3=${r.mp3_s.toFixed(2)}s  rms=${r.rms_dbfs.toFixed(1)} dBFS  scene=${r.scene_s.toFixed(2)}s`)
  }
  console.log(`----\nnarration rms (energy-weighted) = ${out.narration_rms_dbfs} dBFS`)
  console.log(`loudest=${out.loudest.loc} ${out.loudest.rms_dbfs}  quietest=${out.quietest.loc} ${out.quietest.rms_dbfs}  spread=${out.spread_db} dB`)
  console.log(`scene sum=${out.scene_sum_s}s  video total=${out.video_total_s}s  bed target=${out.bed_target_s}s`)
} else {
  console.log(JSON.stringify(out))
}
