// tools/qa-frames.mjs —— 从**成片**里抽关键帧存证（人眼看帧）
//
// 为什么从成片抽、而不是直接截 HTML：HTML 截帧只证明「页面能这样渲染」，
// 成片抽帧证明「成片里真的有这一帧」。时序用工厂同一组数字算
// （intro + 逐语种 seg.wav 时长累进，与 verify-sync 同一口径）。
//
// 用法：node tools/qa-frames.mjs [--only ep01-white-queen] [--fmt portrait]
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DATA = JSON.parse(readFileSync(join(ROOT, 'data', 'series.json'), 'utf8'))

const argv = process.argv.slice(2)
const only = argv.includes('--only') ? argv[argv.indexOf('--only') + 1] : null
const fmt = argv.includes('--fmt') ? argv[argv.indexOf('--fmt') + 1] : 'portrait'

function probeDur(p) {
  if (!existsSync(p)) return null
  const r = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
    { encoding: 'utf8' })
  const v = Number((r.stdout || '').trim())
  return Number.isFinite(v) ? v : null
}

for (const ep of DATA.episodes) {
  if (only && ep.id !== only) continue
  const dir = join(ROOT, 'episodes', ep.id)
  const mp4 = join(dir, 'out', `${ep.id}_${fmt}.mp4`)
  if (!existsSync(mp4)) { console.log(`!! 缺成片：${ep.id}`); continue }
  const cfg = JSON.parse(readFileSync(join(dir, 'video.json'), 'utf8'))
  const framesDir = join(dir, fmt === 'portrait' ? 'frames_v' : 'frames')
  const qa = join(dir, 'qa')
  mkdirSync(qa, { recursive: true })

  // 场景起点：intro + 前面各语种 seg.wav 的时长累进
  let t = cfg.intro
  const grabs = []
  for (const loc of cfg.locales) {
    const seg = join(framesDir, `${loc}-seg.wav`)
    const dur = probeDur(seg)
    if (dur === null) { console.log(`!! 缺 ${loc}-seg.wav：${ep.id}`); break }
    // 抓「第一个 token 唱到一半」的帧：pre 帧（全暗）没有信息量
    const toks = JSON.parse(readFileSync(join(dir, 'tts', `${loc}.json`), 'utf8')).tokens
    const firstLen = toks.length > 1 ? toks[1].start - toks[0].start : Math.min(2, dur)
    grabs.push({ loc, t: t + cfg.preroll + firstLen / 2 })
    t += dur
  }
  grabs.push({ loc: 'intro', t: cfg.intro / 2 })
  grabs.push({ loc: 'outro', t: t + cfg.outro / 2 })

  for (const g of grabs) {
    const out = join(qa, `${g.loc}.png`)
    const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', g.t.toFixed(2),
      '-i', mp4, '-frames:v', '1', out], { encoding: 'utf8' })
    if (r.status !== 0) console.log(`  !! 抓帧失败 ${ep.id}/${g.loc} t=${g.t.toFixed(2)}: ${(r.stderr ?? '').slice(0, 120)}`)
  }
  console.log(`${ep.id}  抽 ${grabs.length} 帧 → ${qa.replace(ROOT, '.')}`)
}
